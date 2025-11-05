# main.py — 1D “temiz” hacim botu (kırmızı mumları ele, yeşil + tepeye yakın şartı)
import os, time, ccxt, pandas as pd, requests

# ---- Günlük versiyon ayarları ----
EXCHANGE         = os.getenv("EXCHANGE", "mexc")      # binance|mexc|kucoin|bybit|gateio
QUOTE            = os.getenv("QUOTE", "USDT")
TIMEFRAME        = os.getenv("TIMEFRAME", "1d")        # ✅ Günlük analiz
LIMIT            = int(os.getenv("LIMIT", "200"))
VOL_LOOKBACK     = int(os.getenv("VOL_LOOKBACK", "6")) # ✅ Son 6 günlük hacim ortalaması
VOL_MULTIPLIER   = float(os.getenv("VOL_MULTIPLIER", "2.0"))
PRICE_MAX_CHANGE = float(os.getenv("PRICE_MAX_CHANGE", "0.06")) # günlük mum max %6
PRICE_MIN_CHANGE = float(os.getenv("PRICE_MIN_CHANGE", "0.00")) # 0.00 → kırmızıları ele
BULLISH_ONLY     = os.getenv("BULLISH_ONLY", "true").lower() == "true"
MAX_MARKETS      = int(os.getenv("MAX_MARKETS", "400"))
CSV_OUT          = os.getenv("CSV_OUT", "volume_spike_daily_clean.csv")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID          = os.getenv("CHAT_ID")


def load_exchange(name):
    ex = getattr(ccxt, name)({'enableRateLimit': True})
    ex.load_markets()
    return ex


def pick_symbols(ex, quote="USDT", max_markets=500):
    syms = []
    for s, m in ex.markets.items():
        if m.get("active") and m.get("spot") and m.get("quote") == quote:
            syms.append(s)
    return sorted(set(syms))[:max_markets]


def early_volume_spike(df, idx):
    if idx < VOL_LOOKBACK:
        return False

    vol_avg = df["volume"].iloc[idx - VOL_LOOKBACK: idx].mean()
    vol_cond = df["volume"].iloc[idx] >= VOL_MULTIPLIER * max(vol_avg, 1e-9)

    c_now  = df["close"].iloc[idx]
    c_prev = df["close"].iloc[idx - 1]

    change = (c_now - c_prev) / max(c_prev, 1e-12)
    price_band_ok = (change >= PRICE_MIN_CHANGE) and (change <= PRICE_MAX_CHANGE)

    if not (vol_cond and price_band_ok):
        return False

    if BULLISH_ONLY:
        o = df["open"].iloc[idx]
        h = df["high"].iloc[idx]
        l = df["low"].iloc[idx]
        c = c_now

        rng = max(h - l, 1e-12)
        body = abs(c - o) / rng
        near_high = (h - c) / rng <= 0.35      # tepeye daha yakın
        if not (c > o and body >= 0.35 and near_high):
            return False

    return True


def analyze_symbol(ex, symbol):
    try:
        raw = ex.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)
        if not raw:
            return None

        df = pd.DataFrame(raw, columns=["time","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert("Europe/Istanbul")

        idx = len(df) - 1
        if early_volume_spike(df, idx):
            return {
                "symbol": symbol,
                "bar_time": df["time"].iloc[idx],
                "close": float(df["close"].iloc[idx]),
                "volume": float(df["volume"].iloc[idx]),
            }
    except Exception:
        pass
    
    return None


def send_to_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram yok.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=15)
    except:
        pass


def main():
    ex = load_exchange(EXCHANGE)
    symbols = pick_symbols(ex, QUOTE, MAX_MARKETS)
    print(f"{EXCHANGE.upper()} {QUOTE} — Günlük tarama: {len(symbols)} parite")

    hits = []
    for i, sym in enumerate(symbols, 1):
        res = analyze_symbol(ex, sym)
        if res:
            hits.append(res)
            print(f"[MATCH] {sym} @ {res['bar_time']} close={res['close']:.6g}")

        if i % 20 == 0:
            time.sleep(0.25)

    df = pd.DataFrame(hits)
    if not df.empty:
        df.sort_values(["bar_time", "symbol"], inplace=True)
        df.to_csv(CSV_OUT, index=False)

        lines = ["🔥 Günlük (1D) Erken Hacim Sinyalleri 🔥", ""]
        for _, r in df.iterrows():
            lines.append(f"{r['symbol']} | Close={r['close']:.6g} | Vol={int(r['volume']):,}")

        send_to_telegram("\n".join(lines))
        print(f"CSV kaydedildi: {CSV_OUT}")
    else:
        print("Eşleşme yok.")
        send_to_telegram("📭 Günlük 1D taramada eşleşme yok.")


if __name__ == "__main__":
    main()

