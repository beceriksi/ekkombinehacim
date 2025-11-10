import os, time, requests, pandas as pd, numpy as np
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== SECRETS ======
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

# ====== ENDPOINTS ======
MEXC      = "https://api.mexc.com"                 # Spot
COINGECKO = "https://api.coingecko.com/api/v3/global"

# ====== PARAMETRELER (gerekirse GitHub Secrets -> ENV ile değiştir) ======
TOP_N            = int(os.getenv("TOP_N", "200"))        # Hacme göre ilk N USDT çifti
MIN_TURNOVER_1H  = float(os.getenv("MIN_TURNOVER_1H", "300000"))   # 1H son bar USDT hacim tabanı
MIN_TURNOVER_4H  = float(os.getenv("MIN_TURNOVER_4H", "600000"))
MIN_TURNOVER_1D  = float(os.getenv("MIN_TURNOVER_1D", "2500000"))
VOL_EMA_N        = int(os.getenv("VOL_EMA_N", "10"))
BUY_VOL_RATIO    = float(os.getenv("BUY_VOL_RATIO", "1.15"))       # 1H/4H/1D için ortak kullanılır
SELL_VOL_RATIO   = float(os.getenv("SELL_VOL_RATIO", "0.95"))       # SELL için hacim şartı gevşek
ACCUM_LOOKBACK   = int(os.getenv("ACCUM_LOOKBACK", "48"))           # 1H içinde son X bar
ACCUM_MIN_HITS   = int(os.getenv("ACCUM_MIN_HITS", "4"))            # Son X bar içinde min BUY sayısı

# ====== Yardımcılar ======
def ts(): return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def jget(url, params=None, retries=3, timeout=12):
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except:
            time.sleep(0.3)
    return None

def telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(text); return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=20)
    except: pass

# ====== İndikatörler ======
def ema(x,n): return x.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d=s.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    rs = up.ewm(alpha=1/n, adjust=False).mean() / (dn.ewm(alpha=1/n, adjust=False).mean() + 1e-12)
    return 100 - (100/(1+rs))

def adx(df, n=14):
    up = df['high'].diff(); dn = -df['low'].diff()
    plus  = np.where((up>dn)&(up>0), up, 0.0)
    minus = np.where((dn>up)&(dn>0), dn, 0.0)
    tr1 = df['high']-df['low']
    tr2 = (df['high']-df['close'].shift()).abs()
    tr3 = (df['low'] -df['close'].shift()).abs()
    tr  = pd.DataFrame({'a':tr1,'b':tr2,'c':tr3}).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False).mean()
    plus_di  = 100*pd.Series(plus ).ewm(alpha=1/n, adjust=False).mean()/(atr+1e-12)
    minus_di = 100*pd.Series(minus).ewm(alpha=1/n, adjust=False).mean()/(atr+1e-12)
    dx = ((plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-12)) * 100
    return dx.ewm(alpha=1/n, adjust=False).mean()

def volume_ratio(turnover, n=VOL_EMA_N):
    base = turnover.ewm(span=n, adjust=False).mean()
    return float(turnover.iloc[-1] / (base.iloc[-2] + 1e-12))

# ====== Coin listesi (MEXC Spot – 1. bot mantığının aynısı) ======
def mexc_spot_top_usdt(limit=TOP_N):
    d = jget(f"{MEXC}/api/v3/ticker/24hr")
    if not d: return []
    rows = [x for x in d if x.get("symbol","").endswith("USDT")]
    rows.sort(key=lambda x: float(x.get("quoteVolume","0")), reverse=True)
    return [x["symbol"] for x in rows[:limit]]

# ====== Kline (MEXC Spot) ======
def klines(symbol, interval="1h", limit=240):
    d = jget(f"{MEXC}/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    if not d: return None
    try:
        df = pd.DataFrame(d, columns=[
            "t","o","h","l","c","v","qv","n","t1","t2","ig","ib"
        ])
        df = df.astype({"o":"float","h":"float","l":"float","c":"float","v":"float","qv":"float"})
        df.rename(columns={"c":"close","h":"high","l":"low","qv":"turnover"}, inplace=True)
        return df[["close","high","low","turnover"]]
    except:
        return None

# ====== Piyasa Notu (opsiyonel bilgilendirme) ======
def market_note():
    g = jget(COINGECKO)
    try:
        total = float(g["data"]["market_cap_change_percentage_24h_usd"])
        btcd  = float(g["data"]["market_cap_percentage"]["btc"])
        usdt  = float(g["data"]["market_cap_percentage"]["usdt"])
    except:
        return "Piyasa: veri alınamadı."
    total2 = "↑ (Altlara giriş)" if total>0 else ("↓ (Çıkış)" if total<0 else "→ (Karışık)")
    usdt_note = f"{usdt:.1f}%"
    if usdt>=7: usdt_note += " (riskten kaçış)"
    elif usdt<=5: usdt_note += " (risk alımı)"
    return f"Piyasa: BTC.D {btcd:.1f}% | Total2: {total2} | USDT.D: {usdt_note}"

# ====== Sinyal Koşulları ======
def buy_condition(c, h, l, t, tf):
    vratio = volume_ratio(t)
    e20, e50 = ema(c,20).iloc[-1], ema(c,50).iloc[-1]
    r = float(rsi(c).iloc[-1])
    trend_up = e20 > e50
    # Likidite tabanı
    liq_ok = (t.iloc[-1] >= (MIN_TURNOVER_1H if tf=="1h" else MIN_TURNOVER_4H if tf=="4h" else MIN_TURNOVER_1D))
    return (liq_ok and trend_up and r >= 50 and vratio >= BUY_VOL_RATIO), vratio, r, trend_up

def sell_condition(c, h, l, t, tf):
    vratio = volume_ratio(t)
    e20, e50 = ema(c,20).iloc[-1], ema(c,50).iloc[-1]
    r = float(rsi(c).iloc[-1])
    trend_down = e20 < e50
    ret1 = float(c.iloc[-1]/(c.iloc[-2]+1e-12) - 1.0)
    # SELL için hacmi şart koşmuyoruz; düşüş momentumu + trend kırmızı
    liq_ok = (t.iloc[-1] >= (MIN_TURNOVER_1H if tf=="1h" else MIN_TURNOVER_4H if tf=="4h" else MIN_TURNOVER_1D))
    return (liq_ok and trend_down and (r <= 48 or ret1 <= -0.015 or vratio <= SELL_VOL_RATIO)), vratio, r, (not trend_down)

def confidence_score(vratio, r, adx_val, trend_up):
    # 0–100 ölçeği
    base = 20
    sc = base + min(40, (vratio-1.0)*40) + min(25, max(0,(r-40))*1.0) + min(25, adx_val/2.5)
    if trend_up: sc += 5
    return int(max(0, min(100, sc)))

# ====== Accumulation (son 48 saat içinde ≥4 kez 1H BUY koşulu) ======
def accumulation_tag(df1h):
    if df1h is None or len(df1h) < max(60, ACCUM_LOOKBACK+50):
        return 0, False
    c, h, l, t = df1h["close"], df1h["high"], df1h["low"], df1h["turnover"]
    # Hesaplamaları bir defa yap
    e20 = ema(c,20); e50 = ema(c,50); r = rsi(c)
    base = t.ewm(span=VOL_EMA_N, adjust=False).mean()
    vratio = t / (base.shift(1) + 1e-12)
    cnt=0
    for i in range(len(c)-ACCUM_LOOKBACK, len(c)):
        if i < 55: continue
        liq_ok = t.iloc[i] >= MIN_TURNOVER_1H
        if liq_ok and (e20.iloc[i] > e50.iloc[i]) and (r.iloc[i] >= 50) and (vratio.iloc[i] >= BUY_VOL_RATIO):
            cnt += 1
    return cnt, (cnt >= ACCUM_MIN_HITS)

# ====== Tek sembol değerlendirme ======
def eval_symbol(sym):
    out = {"symbol": sym, "BUY": [], "SELL": [], "accum": None}
    # 1H / 4H / 1D verilerini çek
    d1h = klines(sym, "1h", 260)
    d4h = klines(sym, "4h", 260)
    d1d = klines(sym, "1d", 400)
    # Accumulation etiketi (1H içinden)
    acc_cnt, acc_flag = accumulation_tag(d1h)
    if acc_flag: out["accum"] = f"TOPLANIYOR (48s/≥4) [{acc_cnt}]"
    # 1H/4H/1D sinyalleri
    for tf, df in (("1h", d1h), ("4h", d4h), ("1d", d1d)):
        if df is None or len(df) < 60: continue
        c,h,l,t = df["close"], df["high"], df["low"], df["turnover"]
        # ADX bilgi amaçlı
        adx_val = float(adx(pd.DataFrame({"high":h,"low":l,"close":c}),14).iloc[-1])
        ok_buy, v_b, r_b, tr_up  = buy_condition(c,h,l,t,tf)
        ok_sell,v_s, r_s, _      = sell_condition(c,h,l,t,tf)
        if ok_buy:
            conf = confidence_score(v_b, r_b, adx_val, tr_up)
            out["BUY"].append((tf.upper(), conf, v_b, r_b, adx_val, float(c.iloc[-1])))
        if ok_sell:
            conf = confidence_score(max(1.0, v_s), max(0.0, 100-r_s), adx_val, False)
            out["SELL"].append((tf.upper(), conf, v_s, r_s, adx_val, float(c.iloc[-1])))
    return out

# ====== Ana ======
def main():
    syms = mexc_spot_top_usdt(TOP_N)
    if not syms:
        telegram("⛔ MEXC 24hr yanıtı yok; sembol listesi alınamadı.")
        return

    note = market_note()
    results = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(eval_symbol, s) for s in syms]
        for f in as_completed(futs):
            try:
                r = f.result()
                if r: results.append(r)
            except: pass

    buys, sells, accums = [], [], []
    for r in results:
        if r.get("accum"): accums.append((r["symbol"], r["accum"]))
        if r["BUY"]:
            # en yüksek güvenden birini göster
            best = sorted(r["BUY"], key=lambda z: z[1], reverse=True)[0]
            buys.append((r["symbol"],) + best)  # (sym, TF, conf, vratio, rsi, adx, last)
        if r["SELL"]:
            best = sorted(r["SELL"], key=lambda z: z[1], reverse=True)[0]
            sells.append((r["symbol"],) + best)

    buys.sort(key=lambda x: x[2], reverse=True)
    sells.sort(key=lambda x: x[2], reverse=True)

    lines = [
        f"⚡ *MEXC Spot Çoklu Tarama (1H • 4H • 1D)*",
        f"⏱ {ts()}",
        f"📊 Taranan: {len(syms)} coin | Süre: {int(time.time()-start)} sn",
        f"{note}",
    ]

    if accums:
        lines.append("\n🟪 *Toplanıyor Etiketleri* (1H, 48s içinde ≥4 BUY)")
        for s, tag in accums[:15]:
            lines.append(f"- {s} → {tag}")

    if buys:
        lines.append("\n🟢 *BUY (en iyi 15)*  |  Format: COIN | TF | Güven | Vx | RSI | ADX | Fiyat")
        for sym, tf, conf, v, r, ax, last in buys[:15]:
            lines.append(f"- {sym} | {tf} | {conf}/100 | x{v:.2f} | {r:.1f} | {ax:.0f} | {last:g}")

    if sells:
        lines.append("\n🔴 *SELL (en iyi 15)* |  Format: COIN | TF | Güven | Vx | RSI | ADX | Fiyat")
        for sym, tf, conf, v, r, ax, last in sells[:15]:
            lines.append(f"- {sym} | {tf} | {conf}/100 | x{v:.2f} | {r:.1f} | {ax:.0f} | {last:g}")

    if not buys and not sells and not accums:
        lines.append("\nℹ️ Şu an kriterlere uyan sinyal yok.")

    telegram("\n".join(lines))

if __name__ == "__main__":
    main()
