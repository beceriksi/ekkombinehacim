import os, time, math, requests, pandas as pd, numpy as np
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# =============== AYARLAR (ENV ile değiştirilebilir) ===============
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

TOP_N              = int(os.getenv("TOP_N",              "200"))   # OKX USDT spot ilk N
SCAN_TFS           = os.getenv("SCAN_TFS",              "1H").split(",")  # "1H" sabit önerim
MIN_TURNOVER_USD   = float(os.getenv("MIN_TURNOVER_USD", "100000"))# tek mumda min $ hacim
WHALE_L            = float(os.getenv("WHALE_L",          "300000"))
WHALE_XL           = float(os.getenv("WHALE_XL",         "800000"))
WHALE_XXL          = float(os.getenv("WHALE_XXL",        "2000000"))

VOL_EMA_N          = int(os.getenv("VOL_EMA_N",          "10"))    # hacim EMA periyodu
VOL_RATIO_BUY      = float(os.getenv("VOL_RATIO_BUY",    "1.25"))  # son mum / EMA-1
VOL_RATIO_SELL     = float(os.getenv("VOL_RATIO_SELL",   "1.15"))

CLUSTER_LOOKBACK   = int(os.getenv("CLUSTER_LOOKBACK",   "4"))     # son 4 mum
CLUSTER_MIN_HITS   = int(os.getenv("CLUSTER_MIN_HITS",   "2"))     # 4 mumdan en az 2’si spike
CLUSTER_SUM_RATIO  = float(os.getenv("CLUSTER_SUM_RATIO","1.60"))  # son 4 toplam / 4*EMA-2

RSI_BUY_MIN        = float(os.getenv("RSI_BUY_MIN",      "52.0"))
RSI_SELL_MAX       = float(os.getenv("RSI_SELL_MAX",     "48.0"))
ADX_MIN_BUY        = float(os.getenv("ADX_MIN_BUY",      "18.0"))  # düşükte noise artar
ADX_MIN_SELL       = float(os.getenv("ADX_MIN_SELL",     "15.0"))

MARKET_REQUIRE_UP  = os.getenv("MARKET_REQUIRE_UP", "true").lower()=="true"  # BUY için pazar filtre
MAX_ROWS_TELEGRAM  = int(os.getenv("MAX_ROWS_TELEGRAM",  "22"))    # iletideki satır limiti

# =============== SABİTLER ===============
OKX = "https://www.okx.com"
COINGECKO = "https://api.coingecko.com/api/v3"

# =============== GENEL UTİLLER ===============
def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def jget(url, params=None, retries=3, timeout=12):
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except:
            time.sleep(0.4)
    return None

def telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(text); return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    except: pass

# =============== GÖSTERGELER ===============
def ema(x, n): return x.ewm(span=n, adjust=False).mean()

def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0); dn = -d.clip(upper=0)
    rs = up.ewm(alpha=1/n, adjust=False).mean() / (dn.ewm(alpha=1/n, adjust=False).mean() + 1e-12)
    return 100 - (100 / (1 + rs))

def adx_from_hlc(h, l, c, n=14):
    up = h.diff(); dn = -l.diff()
    plus  = np.where((up>dn)&(up>0), up, 0.0)
    minus = np.where((dn>up)&(dn>0), dn, 0.0)
    tr = pd.DataFrame({'a':h-l, 'b':(h-c.shift()).abs(), 'c':(l-c.shift()).abs()}).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False).mean()
    plus_di  = 100*pd.Series(plus ).ewm(alpha=1/n, adjust=False).mean()/(atr+1e-12)
    minus_di = 100*pd.Series(minus).ewm(alpha=1/n, adjust=False).mean()/(atr+1e-12)
    dx = ((plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-12)) * 100
    return dx.ewm(alpha=1/n, adjust=False).mean()

# =============== OKX KAYNAKLARI ===============
def okx_top_usdt_spot(TOP=200):
    """
    OKX spot tickers içinden USDT paritelerini 24h quote hacmine göre sıralar.
    instId örn: 'BTC-USDT'
    """
    t = jget(f"{OKX}/api/v5/market/tickers", {"instType":"SPOT"})
    if not t or "data" not in t: return []
    rows = []
    for x in t["data"]:
        inst = x.get("instId","")
        if not inst.endswith("-USDT"): continue
        # volCcy24h genelde quote taraf (USDT) – yoksa fallback olarak 24h vol * son fiyat
        qc = x.get("volCcy24h")
        try:
            qv = float(qc) if qc is not None else float(x.get("last","0"))*float(x.get("vol24h","0"))
        except:
            qv = 0.0
        rows.append((inst, qv))
    rows.sort(key=lambda z: z[1], reverse=True)
    return [r[0] for r in rows[:TOP]]

def okx_candles(instId, bar="1H", limit=150):
    """
    OKX candles -> [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
    volCcy çoğu durumda base ccy değil; ama genelde quote USDT hacmi mevcut oluyor.
    Yoksa approx: mid_price * vol
    """
    d = jget(f"{OKX}/api/v5/market/candles", {"instId":instId, "bar":bar, "limit":limit})
    if not d or "data" not in d or len(d["data"])==0: return None
    arr = d["data"]  # reverse chronological -> ilk eleman en yeni
    arr.reverse()
    recs = []
    for row in arr:
        # değişen uzunluklara dayanıklı parse:
        ts, o, h, l, c = row[0], row[1], row[2], row[3], row[4]
        vol = row[5] if len(row) > 5 else "0"
        volCcy = row[6] if len(row) > 6 else None
        try:
            o=float(o); h=float(h); l=float(l); c=float(c)
            v=float(vol)
            if volCcy is not None:
                t = float(volCcy)
            else:
                mid = (o+c)/2.0
                t   = v * mid
            recs.append((int(ts), o, h, l, c, v, t))
        except:
            continue
    if not recs: return None
    df = pd.DataFrame(recs, columns=["ts","open","high","low","close","volume","turnover"])
    return df

# =============== HACİM–KÜMESİ ve SİNYAL MANTIĞI ===============
def vol_ratio_series(turnover, n=10):
    base = ema(turnover, n)
    # son mum / EMA-1 (son değer EMA’nın kendisi, bir önceki daha temiz)
    return turnover / (base.shift(1) + 1e-12)

def cluster_pass(df, n=VOL_EMA_N):
    """Son CLUSTER_LOOKBACK mum içinde kaç spike var ve toplam ratio yeterli mi?"""
    r = vol_ratio_series(df["turnover"], n)
    recent = r.iloc[-CLUSTER_LOOKBACK:]
    hits = int((recent >= VOL_RATIO_BUY).sum())
    # toplamsal eşik: son4 toplam / (4*EMA-2)
    ema_prev2 = ema(df["turnover"], n).shift(2).iloc[-1]
    cluster_sum = df["turnover"].iloc[-CLUSTER_LOOKBACK:].sum()
    cluster_ratio = float(cluster_sum / (CLUSTER_LOOKBACK * (ema_prev2 + 1e-12)))
    return (hits >= CLUSTER_MIN_HITS) and (cluster_ratio >= CLUSTER_SUM_RATIO), hits, cluster_ratio, float(r.iloc[-1])

def whale_tier(turnover_last):
    if turnover_last >= WHALE_XXL: return "XXL"
    if turnover_last >= WHALE_XL:  return "XL"
    if turnover_last >= WHALE_L:   return "L"
    return "-"

def market_filter_allow_buy():
    """Piyasa filtresi: BTC 1H trend & Coingecko Total2 hissiyatı (yaklaşık)."""
    if not MARKET_REQUIRE_UP: return True
    # BTC 1H trend
    btc = okx_candles("BTC-USDT","1H",120)
    if btc is None or len(btc)<40: return True  # veri yoksa engelleme
    e20 = ema(btc["close"],20).iloc[-1]
    e50 = ema(btc["close"],50).iloc[-1]
    trend_ok = e20 > e50

    g = jget(f"{COINGECKO}/global")
    total_ok = True
    try:
        total = float(g["data"]["market_cap_change_percentage_24h_usd"])
        total_ok = total >= -0.5   # çok negatifse BUY kısıtla
    except:
        pass
    return trend_ok and total_ok

def analyze_one(instId, tf):
    df = okx_candles(instId, tf, 180)
    if df is None or len(df)<60: return None, "short"
    # min likidite
    if float(df["turnover"].iloc[-1]) < MIN_TURNOVER_USD:
        return None, "lowliq"

    c = df["close"]; h = df["high"]; l = df["low"]; t = df["turnover"]
    e20 = float(ema(c,20).iloc[-1]); e50 = float(ema(c,50).iloc[-1])
    trend_up = e20 > e50
    rr = float(rsi(c,14).iloc[-1])
    adxv = float(adx_from_hlc(h,l,c,14).iloc[-1])

    # hacim kümesi
    cl_ok, cl_hits, cl_sum_ratio, v_ratio_last = cluster_pass(df, VOL_EMA_N)
    if not cl_ok: return None, "nocluster"

    side = None
    if trend_up and rr >= RSI_BUY_MIN and v_ratio_last >= VOL_RATIO_BUY and adxv >= ADX_MIN_BUY:
        if market_filter_allow_buy():
            side = "BUY"
        else:
            return None, "mkt"
    elif (not trend_up) and rr <= RSI_SELL_MAX and v_ratio_last >= VOL_RATIO_SELL and adxv >= ADX_MIN_SELL:
        side = "SELL"
    else:
        return None, "rules"

    # güven puanı (0–100)
    # bileşenler: v_ratio_last, cl_hits, cl_sum_ratio, adxv, rsi uzaklık, whale
    last_turn = float(t.iloc[-1])
    tier = whale_tier(last_turn)
    whale_bonus = {"-":0, "L":6, "XL":12, "XXL":18}[tier]
    rsi_comp = (rr-50) if side=="BUY" else (50-rr)  # BUY’da +, SELL’de rr küçükse +
    rsi_score = max(0, min(15, rsi_comp*1.0))
    adx_score = max(0, min(15, (adxv-ADX_MIN_BUY if side=="BUY" else adxv-ADX_MIN_SELL)))
    v_score   = max(0, min(25, (v_ratio_last-1.0)*25))          # 1.00 → 0, 2.00 → ~25
    cl_score  = max(0, min(20, (cl_hits-CLUSTER_MIN_HITS+1)*8)) # daha çok hit → daha iyi
    sum_score = max(0, min(15, (cl_sum_ratio-1.0)*15))
    conf = int(max(0, min(100, whale_bonus + rsi_score + adx_score + v_score + cl_score + sum_score)))

    return {
        "inst": instId,
        "tf": tf,
        "side": side,
        "rsi": rr,
        "adx": adxv,
        "trend": "↑" if trend_up else "↓",
        "v_ratio": v_ratio_last,
        "cl_hits": cl_hits,
        "cl_sum": cl_sum_ratio,
        "turnover": last_turn,
        "whale": tier,
        "conf": conf
    }, None

# =============== ANA AKIŞ ===============
def main():
    symbols = okx_top_usdt_spot(TOP_N)
    if not symbols:
        telegram(f"⛔ Coin listesi alınamadı (OKX). {ts()}"); return

    start = time.time()
    results, stats = [], {"short":0,"lowliq":0,"nocluster":0,"mkt":0,"rules":0}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(analyze_one, s, tf) for s in symbols for tf in SCAN_TFS]
        for f in as_completed(futs):
            try:
                r, flag = f.result()
                if r: results.append(r)
                elif flag: stats[flag] = stats.get(flag,0)+1
            except:
                pass

    buys  = [x for x in results if x["side"]=="BUY"]
    sells = [x for x in results if x["side"]=="SELL"]

    # ileti
    lines = [f"⚡ *OKX USDT Spot 1H Akıllı Tarama*\n⏱ {ts()}\n🔎 Tarama: {len(symbols)} coin | Süre: {int(time.time()-start)} sn"]
    if results:
        conf_avg = int(sum(x["conf"] for x in results)/max(1,len(results)))
        lines.append(f"🛡️ Güven Ort.: {conf_avg}/100")
    lines.append(f"🚧 Atl.: short:{stats['short']} | lowliq:{stats['lowliq']} | nocluster:{stats['nocluster']} | market:{stats['mkt']} | rules:{stats['rules']}")

    def fmt(x):
        return f"- {x['inst']} | {x['tf']} | {('🟢 BUY' if x['side']=='BUY' else '🔴 SELL')} | Güven:{x['conf']} | RSI:{x['rsi']:.1f} | ADX:{x['adx']:.0f} | vRatio:{x['v_ratio']:.2f} | Cluster:{x['cl_hits']}/{CLUSTER_LOOKBACK} Σ:{x['cl_sum']:.2f} | Whale:{x['whale']}"

    if buys:
        lines.append("\n🟢 *BUY (en yüksek güven)*")
        for x in sorted(buys, key=lambda z:z["conf"], reverse=True)[:MAX_ROWS_TELEGRAM//2]:
            lines.append(fmt(x))
    if sells:
        lines.append("\n🔴 *SELL (en yüksek güven)*")
        for x in sorted(sells, key=lambda z:z["conf"], reverse=True)[:MAX_ROWS_TELEGRAM//2]:
            lines.append(fmt(x))

    if not buys and not sells:
        lines.append("\nℹ️ Şu an kriterlere uyan sinyal yok (filtreler sıkı olduğunda normal).")

    telegram("\n".join(lines))

if __name__ == "__main__":
    main()
