import os, time, requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# --- Secrets ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# --- Endpoints ---
MEXC_FAPI = "https://contract.mexc.com"
BINANCE = "https://api.binance.com"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"

# ---------- utils ----------
def ts(): return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def jget(url, params=None, retries=3, timeout=12):
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except:
            time.sleep(0.5)
    return None

def telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(text); return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
        )
    except:
        pass

# ---------- indicators ----------
def ema(x, n): return x.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0); dn = -d.clip(upper=0)
    rs = up.ewm(alpha=1/n, adjust=False).mean() / (dn.ewm(alpha=1/n, adjust=False).mean() + 1e-12)
    return 100 - (100/(1+rs))

def macd(s, f=12, m=26, sig=9):
    fast = ema(s,f); slow = ema(s,m)
    line = fast - slow
    signal = line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal

def adx(df, n=14):
    up = df['high'].diff(); dn = -df['low'].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift()).abs()
    tr3 = (df['low'] - df['close'].shift()).abs()
    tr = pd.DataFrame({'a':tr1,'b':tr2,'c':tr3}).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False).mean()
    plus_di = 100*pd.Series(plus_dm).ewm(alpha=1/n, adjust=False).mean()/(atr+1e-12)
    minus_di = 100*pd.Series(minus_dm).ewm(alpha=1/n, adjust=False).mean()/(atr+1e-12)
    dx = ((plus_di - minus_di).abs()/((plus_di + minus_di)+1e-12))*100
    return dx.ewm(alpha=1/n, adjust=False).mean()

def bos_up(df, look=30, excl=1):
    hh = df['high'][:-excl].tail(look).max()
    return df['close'].iloc[-1] > hh

def bos_dn(df, look=30, excl=1):
    ll = df['low'][:-excl].tail(look).min()
    return df['close'].iloc[-1] < ll

def volume_spike(df, n=20, r=1.3):
    if len(df) < n+2: return False, 1.0
    last = df['volume'].iloc[-1]
    base = df['volume'].iloc[-(n+1):-1].mean()
    ratio = last/(base + 1e-12)
    return ratio >= r, ratio

# ---------- market notes ----------
def coin_state(symbol, interval):
    d = jget(f"{BINANCE}/api/v3/klines", {"symbol":symbol,"interval":interval,"limit":200})
    if not d: return "NÖTR"
    df = pd.DataFrame(d, columns=["t","o","h","l","c","v","ct","x1","x2","x3","x4","x5"]).astype(float)
    c = df['c']; e20,e50 = ema(c,20).iloc[-1], ema(c,50).iloc[-1]; rr = rsi(c,14).iloc[-1]
    if e20>e50 and rr>50: return "GÜÇLÜ"
    if e20<e50 and rr<50: return "ZAYIF"
    return "NÖTR"

def btc_eth_state_1h_4h():
    return (coin_state("BTCUSDT","1h"), coin_state("ETHUSDT","1h"),
            coin_state("BTCUSDT","4h"), coin_state("ETHUSDT","4h"))

def market_note():
    g = jget(COINGECKO_GLOBAL)
    try:
        total_pct = float(g["data"]["market_cap_change_percentage_24h_usd"])
        btc_dom   = float(g["data"]["market_cap_percentage"]["btc"])
        usdt_dom  = float(g["data"]["market_cap_percentage"]["usdt"])
    except:
        return "Piyasa: veri alınamadı."
    tkr = jget(f"{BINANCE}/api/v3/ticker/24hr", {"symbol":"BTCUSDT"})
    try: btc_pct = float(tkr["priceChangePercent"])
    except: btc_pct = None
    arrow = "↑" if (btc_pct is not None and btc_pct>total_pct) else ("↓" if (btc_pct is not None and btc_pct<total_pct) else "→")
    dirb  = "↑" if (btc_pct is not None and btc_pct>0) else ("↓" if (btc_pct is not None and btc_pct<0) else "→")
    total2 = "↑ (Altlara giriş)" if arrow=="↓" and total_pct>=0 else ("↓ (Çıkış)" if arrow=="↑" and total_pct<=0 else "→ (Karışık)")
    usdt_note = f"{usdt_dom:.1f}%"
    if usdt_dom>=7.0: usdt_note+=" (riskten kaçış)"
    elif usdt_dom<=5.0: usdt_note+=" (risk alımı)"
    return f"Piyasa: BTC {dirb} + BTC.D {arrow} (BTC.D {btc_dom:.1f}%) | Total2: {total2} | USDT.D: {usdt_note}"

# ---------- mexc ----------
def mexc_symbols():
    d = jget(f"{MEXC_FAPI}/api/v1/contract/detail")
    if not d or "data" not in d: return []
    return [s["symbol"] for s in d["data"] if s.get("quoteCoin")=="USDT"]

def klines_mexc(sym, interval="1h", limit=200):
    d = jget(f"{MEXC_FAPI}/api/v1/contract/kline/{sym}", {"interval": interval, "limit": limit})
    if not d or "data" not in d: return None
    df = pd.DataFrame(d["data"], columns=["ts","open","high","low","close","volume","turnover"]).astype(
        {"open":"float64","high":"float64","low":"float64","close":"float64","volume":"float64","turnover":"float64"}
    )
    return df

def funding_rate_mexc(sym):
    d = jget(f"{MEXC_FAPI}/api/v1/contract/funding_rate", {"symbol": sym})
    try: return float(d["data"]["fundingRate"])
    except: return None

# ---------- core logic ----------
def _gap_ok(close_series, pct=0.08):
    if len(close_series) < 2: return False
    return abs(float(close_series.iloc[-1]/close_series.iloc[-2] - 1)) <= pct

def analyze_1h_trigger(sym):
    df = klines_mexc(sym, "1h", 200)
    if df is None or len(df) < 80: return None, "short"
    # likidite 1H: son 1H turnover >= 500k
    if float(df["turnover"].iloc[-1]) < 500_000: return None, "lowliq"
    c, h, l = df['close'], df['high'], df['low']

    if not _gap_ok(c, 0.08): return None, "gap"  # GAP %8

    e20, e50 = ema(c,20).iloc[-1], ema(c,50).iloc[-1]
    trend_up = e20 > e50
    rr = float(rsi(c,14).iloc[-1])
    m, ms, _ = macd(c); macd_up = m.iloc[-1] > ms.iloc[-1]; macd_dn = not macd_up
    av = float(adx(pd.DataFrame({'high':h,'low':l,'close':c}),14).iloc[-1])
    strong = av >= 10
    bosU, bosD = bos_up(df,30), bos_dn(df,30)
    v_ok, v_ratio = volume_spike(df, 20, 1.3)
    if not v_ok: return None, "novol"

    last_down = float(c.iloc[-1]) < float(c.iloc[-2])

    side = None
    if trend_up and rr > 52 and macd_up and strong:
        side = "BUY"
    elif (not trend_up) and rr < 48 and macd_dn and strong and last_down:
        side = "SELL"
    else:
        return None, None

    fr = funding_rate_mexc(sym)
    frtxt = ""
    if fr is not None:
        if fr > 0.01: frtxt = f" | Funding:+{fr:.3f}"
        elif fr < -0.01: frtxt = f" | Funding:{fr:.3f}"

    line = f"{sym} | 1H | Trend:{'↑' if trend_up else '↓'} | RSI:{rr:.1f} | Hacim x{v_ratio:.2f} | ADX:{av:.0f} | BoS:{'↑' if bosU else ('↓' if bosD else '-')} | Fiyat:{float(c.iloc[-1])}{frtxt}"
    return (side, line), None

def _allow_with_4h_filter(sym, side):
    # 4H filtre: BUY için 4H GÜÇLÜ, SELL için 4H ZAYIF
    d = klines_mexc(sym, "4h", 260)
    if d is None or len(d) < 120: return False
    c = d['close']
    e20, e50 = ema(c,20).iloc[-1], ema(c,50).iloc[-1]
    rr = float(rsi(c,14).iloc[-1])
    if side == "BUY":
        return (e20 > e50) and (rr > 50)
    else:
        return (e20 < e50) and (rr < 50)

def main():
    btc1h, eth1h, btc4h, eth4h = btc_eth_state_1h_4h()
    note = market_note()

    syms = mexc_symbols()
    if not syms:
        telegram("⚠️ Sembol listesi alınamadı (MEXC)."); return

    buys, sells = [], []
    skipped = {"short":0,"lowliq":0,"gap":0,"novol":0,"filter":0}
    for i, s in enumerate(syms):
        try:
            res, flag = analyze_1h_trigger(s)
            if flag in skipped: skipped[flag]+=1
            if res:
                side, line = res
                if _allow_with_4h_filter(s, side):
                    if side == "BUY": buys.append(f"- {line}")
                    else: sells.append(f"- {line.replace('1H','1H')}")
                else:
                    skipped["filter"] += 1
        except:
            pass
        if i % 15 == 0: time.sleep(0.25)

    header = [
        f"⚡ *Kombine 1H + 4H Filtre*",
        f"⏱ {ts()}",
        f"BTC: {btc1h} (1H) / {btc4h} (4H) | ETH: {eth1h} (1H) / {eth4h} (4H)",
        note
    ]
    if buys:
        header.append("\n🟢 *BUY (onaylı):*")
        header.extend(buys[:25])
    if sells:
        header.append("\n🔴 *SELL (onaylı):*")
        header.extend(sells[:25])
    if not buys and not sells:
        header.append("\nℹ️ Şu an onaylı sinyal yok.")

    header.append(f"\n📊 Özet: BUY:{len(buys)} | SELL:{len(sells)} | Atlanan (likidite:{skipped['lowliq']}, gap:{skipped['gap']}, hacim:{skipped['novol']}, filtre:{skipped['filter']})")
    telegram("\n".join(header))

if __name__ == "__main__":
    main()
