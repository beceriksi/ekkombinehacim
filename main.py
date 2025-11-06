import os, time, requests, pandas as pd, numpy as np
from datetime import datetime, timezone

# === Ayarlar ===
TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")

# --- API URL ---
MEXC="https://api.mexc.com"
BINANCE="https://api.binance.com"

def ts(): 
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# --- HTTP yardımcı ---
def jget(url, params=None, retries=4, timeout=10):
    for _ in range(retries):
        try:
            r=requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except:
            time.sleep(0.4)
    return None

def telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(msg)
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except:
        pass

# -------------------------
# ✅ 1 NUMARALI BOTTAKİ COIN ÇEKME SİSTEMİ
# -------------------------

def mexc_symbols(limit=150):
    """MEXC hacme göre coin çeker (1 numaralı bot ile birebir aynı)"""
    d=jget(f"{MEXC}/api/v3/ticker/24hr")
    if not d: 
        return []
    coins=[x for x in d if x.get("symbol","").endswith("USDT")]
    coins=sorted(coins, key=lambda x: float(x.get("quoteVolume",0)), reverse=True)
    return [c["symbol"] for c in coins[:limit]]

def binance_symbols(limit=150):
    """MEXC cevap vermezse fallback olarak Binance kullanılır."""
    d=jget(f"{BINANCE}/api/v3/exchangeInfo")
    if not d or "symbols" not in d:
        return []
    rows=[s["symbol"] for s in d["symbols"] 
          if s.get("quoteAsset")=="USDT" and s.get("status")=="TRADING"]
    return rows[:limit]

# -------------------------
# --- Göstergeler ---
# -------------------------

def ema(x,n): 
    return x.ewm(span=n, adjust=False).mean()

def rsi(s,n=14):
    d=s.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    rs=up.ewm(alpha=1/n, adjust=False).mean()/(dn.ewm(alpha=1/n, adjust=False).mean()+1e-12)
    return 100-(100/(1+rs))

def adx(df,n=14):
    up=df['high'].diff(); dn=-df['low'].diff()
    plus=np.where((up>dn)&(up>0),up,0.0); minus=np.where((dn>up)&(dn>0),dn,0.0)

    tr1=df['high']-df['low']
    tr2=(df['high']-df['close'].shift()).abs()
    tr3=(df['low']-df['close'].shift()).abs()
    tr=pd.DataFrame({'a':tr1,'b':tr2,'c':tr3}).max(axis=1)

    atr=tr.ewm(alpha=1/n, adjust=False).mean()
    plus_di=100*pd.Series(plus).ewm(alpha=1/n, adjust=False).mean()/(atr+1e-12)
    minus_di=100*pd.Series(minus).ewm(alpha=1/n, adjust=False).mean()/(atr+1e-12)

    dx=((plus_di-minus_di).abs()/((plus_di+minus_di)+1e-12))*100
    return dx.ewm(alpha=1/n, adjust=False).mean()

def volume_ratio(turnover,n=10):
    base=turnover.ewm(span=n, adjust=False).mean()
    return float(turnover.iloc[-1]/(base.iloc[-2]+1e-12))


# -------------------------
# --- Kline verisi ---
# -------------------------
def klines(sym, interval="1h", limit=200, from_binance=False):
    if not from_binance:
        d=jget(f"{MEXC}/api/v3/klines", {"symbol":sym,"interval":interval,"limit":limit})
        if not d: 
            return None
        try:
            df=pd.DataFrame(d, 
                columns=["t","o","h","l","c","v","qv","n","t1","t2","ig","ib"]).astype(float)
            df.rename(columns={"c":"close","h":"high","l":"low","qv":"turnover"}, inplace=True)
            return df
        except:
            return None
    else:
        d=jget(f"{BINANCE}/api/v3/klines", {"symbol":sym,"interval":interval,"limit":limit})
        if not d:
            return None
        try:
            df=pd.DataFrame(d,
                columns=["t","o","h","l","c","v","ct","qv","tr","tb","tq","ig"]).astype(float)
            df.rename(columns={"c":"close","h":"high","l":"low","v":"turnover"}, inplace=True)
            return df
        except:
            return None

# -------------------------
# --- Analiz ---
# -------------------------

def analyze(sym, interval, from_binance=False):
    df=klines(sym, interval, from_binance=from_binance)
    if df is None or len(df)<80:
        return None

    if df["turnover"].iloc[-1] < 150_000:
        return None

    c=df["close"]; h=df["high"]; l=df["low"]; t=df["turnover"]

    rr=float(rsi(c).iloc[-1])
    e20,e50=ema(c,20).iloc[-1], ema(c,50).iloc[-1]
    trend_up = e20 > e50

    v_ratio = volume_ratio(t,10)
    adx_val = float(adx(pd.DataFrame({"high":h,"low":l,"close":c}),14).iloc[-1])

    last_dir = (c.iloc[-1] - c.iloc[-2]) >= 0
    whale = t.iloc[-1] >= 800_000
    whale_side = "BUY" if last_dir else "SELL"

    side = None
    if trend_up and rr>=50 and v_ratio>=1.15:
        side = "BUY"
    elif (not trend_up) and rr<=60 and v_ratio>=1.10:
        side = "SELL"

    if not side:
        return None

    conf = int(min(100, (v_ratio*25)+(adx_val/3)+(rr/5)))

    return {
        "symbol": sym,
        "tf": interval.upper(),
        "side": side,
        "whale": whale,
        "whale_side": whale_side,
        "turnover": t.iloc[-1],
        "rsi": rr,
        "adx": adx_val,
        "trend": "↑" if trend_up else "↓",
        "v_ratio": v_ratio,
        "conf": conf
    }


# -------------------------
# --- Ana fonksiyon ---
# -------------------------

def main():
    syms = mexc_symbols()
    from_binance=False

    if not syms:
        syms = binance_symbols()
        from_binance=True
        telegram("⚠️ MEXC hata verdi, Binance Spot ile devam ediliyor.")

    if not syms:
        telegram("⛔ Hiç sembol alınamadı (MEXC & Binance).")
        return

    results = []

    for s in syms:
        for tf in ["1h","4h"]:
            res = analyze(s, tf, from_binance)
            if res:
                results.append(res)
        time.sleep(0.03)

    buys=[x for x in results if x["side"]=="BUY"]
    sells=[x for x in results if x["side"]=="SELL"]

    msg=[f"⚡ *Çoklu Zaman Dilimli Sinyaller*\n⏱ {ts()}\nTarama: {len(syms)} coin\nVeri: {'Binance' if from_binance else 'MEXC'}\n"]

    if buys:
        msg.append("\n🟢 *BUY Sinyalleri*")
        for x in sorted(buys,key=lambda x:x["conf"],reverse=True)[:10]:
            msg.append(f"- {x['symbol']} | {x['tf']} | Güven:{x['conf']}")

    if sells:
        msg.append("\n🔴 *SELL Sinyalleri*")
        for x in sorted(sells,key=lambda x:x["conf"],reverse=True)[:10]:
            msg.append(f"- {x['symbol']} | {x['tf']} | Güven:{x['conf']}")

    if not buys and not sells:
        msg.append("ℹ️ Sinyal yok.")

    telegram("\n".join(msg))


if __name__ == "__main__":
    main()
