# test_binance_visibility.py
import requests
import pandas as pd
from datetime import datetime, timezone

BINANCE = "https://api.binance.com"

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def jget(url, params=None, timeout=8):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except:
        return None
    return None

print(f"🔍 BINANCE COIN GÖRÜNÜRLÜK TESTİ BAŞLIYOR...\n⏱ {ts()}\n")

# ✅ 1 — Coin listesini çek
tickers = jget(f"{BINANCE}/api/v3/ticker/24hr")
if not tickers:
    print("❌ Coin listesi alınamadı (Binance API)")
    exit()

# En yüksek hacimli 100 USDT coini seç
rows = [x for x in tickers if x.get("symbol", "").endswith("USDT")]
rows = sorted(rows, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)

coins = rows[:100]
print(f"✅ Binance top100 coin alındı. Coin sayısı: {len(coins)}")

# ✅ 2 — İlk 10 coin'in 1H kline testini yapalım
print("\n🔍 İlk 10 coin 1H kline testi:\n")

for c in coins[:10]:
    sym = c["symbol"]
    kl = jget(f"{BINANCE}/api/v3/klines", {"symbol": sym, "interval": "1h", "limit": 120})

    if kl and len(kl) > 10:
        try:
            df = pd.DataFrame(kl)
            close_val = float(df.iloc[-1][4])
            vol_val = float(df.iloc[-1][7])
            print(f"✅ {sym} → Kline OK | Close:{close_val:.4f} | Hacim:{vol_val:.0f}")
        except:
            print(f"⚠️ {sym} → Veri var ama işlenemedi")
    else:
        print(f"❌ {sym} → 1H kline YOK")

print("\n✅ Test tamamlandı.\n")
print("Eğer çok sayıda ✅ görüyorsan → Binance veri çekme düzgün.\nEğer çok ❌ görüyorsan → internet bağlantısı / API limit olabilir.\n")
