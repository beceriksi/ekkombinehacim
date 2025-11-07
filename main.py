# main.py
import os, time, requests, pandas as pd, numpy as np
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import symbols_resolver as resolver

# === Settings (env or defaults) ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

MEXC = "https://api.mexc.com"
BINANCE = "https://api.binance.com"
BYBIT = "https://api.bybit.com"

SCAN_LIMIT = 200            # top200 from coingecko (resolver)
TF_LIST = ["15m","1h"]      # primary timeframes (we'll still fetch 4h for confidence)
TF_CONF = "4h"              # used only for confidence (not blocking)
MIN_TURNOVER = 100_000     # USD turnover lower bound (adjustable)
VOL_R_BUY = 1.15
VOL_R_SELL = 1.10

# ---- helpers ----
def ts(): return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def jget(url, params=None, retries=3, timeout=10):
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except:
            time.sleep(0.35)
    return None

def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(text); return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode":"Markdown"}, timeout=10)
    except Exception as e:
        print("tg err", e)

# ---- indicators ----
def ema(series, n): return series.ewm(span=n, adjust=False).mean()
def rsi(series, n=14):
    d = series.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    rs = up.ewm(alpha=1/n, adjust=False).mean() / (dn.ewm(alpha=1/n, adjust=False).mean() + 1e-12)
    return 100 - (100/(1+rs))
def adx(df, n=14):
    up = df['high'].diff(); dn = -df['low'].diff()
    plus = np.where((up>dn)&(up>0), up, 0.0); minus = np.where((dn>up)&(dn>0), dn, 0.0)
    tr1 = df['high']-df['low']; tr2 = (df['high']-df['close'].shift()).abs(); tr3 = (df['low']-df['close'].shift()).abs()
    tr = pd.DataFrame({'a':tr1,'b':tr2,'c':tr3}).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False).mean()
    plus_di = 100*pd.Series(plus).ewm(alpha=1/n, adjust=False).mean()/(atr+1e-12)
    minus_di = 100*pd.Series(minus).ewm(alpha=1/n, adjust=False).mean()/(atr+1e-12)
    dx = ((plus_di-minus_di).abs()/((plus_di+minus_di)+1e-12))*100
    return dx.ewm(alpha=1/n, adjust=False).mean()

def volume_ratio(turnover, n=10):
    base = turnover.ewm(span=n, adjust=False).mean()
    return float(turnover.iloc[-1] / (base.iloc[-2] + 1e-12))

# ---- klines per exchange ----
def klines_mexc(sym, interval, limit=200):
    d = jget(f"{MEXC}/api/v3/klines", {"symbol":sym, "interval":interval, "limit":limit})
    if not d: return None
    try:
        df = pd.DataFrame(d, columns=["t","o","h","l","c","v","qv","n","t1","t2","ig","ib"]).astype(float)
        df.rename(columns={"c":"close","h":"h","l":"l","qv":"turnover"}, inplace=True)
        return df
    except:
        return None

def klines_binance(sym, interval, limit=200):
    d = jget(f"{BINANCE}/api/v3/klines", {"symbol":sym, "interval":interval, "limit":limit})
    if not d: return None
    try:
        df = pd.DataFrame(d, columns=[
            "t","o","h","l","c","v","ct","qv","tr","tb","tq","ig"
        ])
        df = df.astype({"o":"float","h":"float","l":"float","c":"float","v":"float","qv":"float"})
        df.rename(columns={"c":"close","h":"h","l":"l","qv":"turnover"}, inplace=True)
        return df
    except:
        return None

def klines_bybit(sym, interval, limit=200):
    d = jget(f"{BYBIT}/spot/quote/v1/kline", {"symbol": sym.replace("/",""), "interval": interval, "limit": limit})
    # Bybit public endpoints vary; fallback to None if not available
    if not d or "result" not in d:
        return None
    try:
        df = pd.DataFrame(d["result"])
        # ensure proper numeric columns; Bybit structure may differ — try common keys
        if "close" in df.columns and "high" in df.columns and "low" in df.columns and "turnover" in df.columns:
            df = df.astype({"close":"float","high":"float","low":"float","turnover":"float"})
            return df
    except:
        pass
    return None

def fetch_klines(sym, exchange_name, interval):
    try:
        if exchange_name == "MEXC":
            return klines_mexc(sym, interval)
        if exchange_name == "BINANCE":
            return klines_binance(sym, interval)
        if exchange_name == "BYBIT":
            return klines_bybit(sym, interval)
    except:
        return None
    return None

# ---- analyze single symbol/timeframe ----
def analyze_pair(entry):
    # entry: {"coingecko_id","symbol","exchange"}
    sym = entry["symbol"]
    exch = entry["exchange"]
    results = []
    for tf in TF_LIST + [TF_CONF]:
        df = fetch_klines(sym, exch, tf)
        if df is None or len(df) < 60:
            continue
        # ensure turnover column exists
        if "turnover" not in df.columns:
            # try quote volume or qv
            if "qv" in df.columns:
                df["turnover"] = df["qv"].astype(float)
            elif "quote_volume" in df.columns:
                df["turnover"] = df["quote_volume"].astype(float)
            else:
                continue
        # filter small turnover
        if float(df["turnover"].iloc[-1]) < MIN_TURNOVER:
            continue
        c = df["close"].astype(float)
        h = df["h"].astype(float) if "h" in df.columns else df["high"].astype(float)
        l = df["l"].astype(float) if "l" in df.columns else df["low"].astype(float)
        v = df["turnover"].astype(float)
        rr = float(rsi(c).iloc[-1])
        e20 = float(ema(c,20).iloc[-1]); e50 = float(ema(c,50).iloc[-1])
        trend_up = e20 > e50
        v_ratio = volume_ratio(v, 10)
        adx_val = float(adx(pd.DataFrame({"high":h,"low":l,"close":c}), 14).iloc[-1])
        last_dir = (c.iloc[-1] - c.iloc[-2]) >= 0
        side = None
        if tf != TF_CONF:  # signal timeframes
            if trend_up and rr >= 50 and v_ratio >= VOL_R_BUY:
                side = "BUY"
            elif (not trend_up) and rr <= 60 and v_ratio >= VOL_R_SELL:
                side = "SELL"
        else:  # confidence timeframe 4h
            # compute confidence boost only
            side = None
        results.append({
            "symbol": sym,
            "exchange": exch,
            "tf": tf,
            "side": side,
            "rsi": rr,
            "adx": adx_val,
            "trend_up": trend_up,
            "v_ratio": v_ratio,
            "turnover": float(v.iloc[-1]),
            "last_dir": last_dir
        })
    return results

# ---- main scan ----
def main():
    print("Resolver mapping...")
    mappings = resolver.top200_coingecko_vs_bourses()
    if not mappings:
        send_telegram("⛔ Resolver: Top200 mapping alınamadı.")
        return
    # optional limit
    mappings = mappings[:SCAN_LIMIT]
    print(f"Scanning {len(mappings)} symbols (mapped to exchanges).")
    start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(analyze_pair, m) for m in mappings]
        for f in as_completed(futures):
            try:
                r = f.result()
                if r:
                    results.extend(r)
            except:
                pass

    # collect signals from primary TF_LIST
    buys = []
    sells = []
    conf_map = {}  # symbol -> confidence from 4h
    for item in results:
        if item["tf"] == TF_CONF:
            # compute simple confidence score
            score = int(min(100, (item["v_ratio"]*25) + (item["adx"]/3) + (item["rsi"]/5)))
            conf_map[item["symbol"]] = score

    for item in results:
        if item["tf"] in TF_LIST and item["side"] in ("BUY","SELL"):
            conf = conf_map.get(item["symbol"], 50)
            line = f"{item['symbol']} ({item['exchange']}) | {item['tf']} | {item['side']} | RSI:{item['rsi']:.0f} | ADX:{item['adx']:.0f} | Volx:{item['v_ratio']:.2f} | Conf:{conf}"
            if item["side"] == "BUY":
                buys.append((conf, line))
            else:
                sells.append((conf, line))

    # deduplicate and sort by confidence
    buys = sorted({l for _, l in buys}, key=lambda x: -int(x.split("|")[-1].split(":")[-1].strip()))[:30]
    sells = sorted({l for _, l in sells}, key=lambda x: -int(x.split("|")[-1].split(":")[-1].strip()))[:30]

    runtime = int(time.time() - start)
    header = f"⚡ *Multi-TF Scanner* • {ts()}\nScanned:{len(mappings)} • Süre:{runtime}s\n"
    body = []
    if buys:
        body.append("🟢 *BUY*:")
        body += buys[:20]
    if sells:
        body.append("\n🔴 *SELL*:")
        body += sells[:20]
    if not buys and not sells:
        body.append("ℹ️ Kriterlere uyan sinyal yok.")
    text = header + "\n".join(body)
    send_telegram(text)
    print("Done. Sent telegram.")

if __name__ == "__main__":
    main()
