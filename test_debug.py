import os, time, requests
import pandas as pd

MEXC = "https://api.mexc.com"
BINANCE = "https://api.binance.com"

def jget(url, params=None, retries=2, timeout=7):
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except:
            time.sleep(0.4)
    return None

print("\n🔍 DEBUG TEST BAŞLIYOR 🔍\n")

# -----------------------------
# 1) COIN LİSTESİ TESTİ
# -----------------------------
print("✅ Coin listesi çekilmeye çalışılıyor...")

data = jget(f"{MEXC}/api/v3/ticker/24hr")

if not data:
    print("❌ MEXC 24hr endpoint veri vermedi!")
else:
    coins = [x["symbol"] for x in data if x["symbol"].endswith("USDT")]
    print(f"✅ Coin listesi geldi. Coin sayısı: {len(coins)}")
    print(f"➡️ İlk 10 coin: {coins[:10]}")

# -----------------------------
# 2) KLINE TESTİ (İlk 10 coin)
# -----------------------------

print("\n✅ İlk 10 coin için 1H kline test ediliyor...\n")

def test_kline(sym):
    kk = jget(f"{MEXC}/api/v3/klines",
              {"symbol": sym, "interval": "1h", "limit": 100})
    if not kk:
        print(f"❌ {sym}: KLINE VERİ YOK / HATALI")
    else:
        try:
            df = pd.DataFrame(kk)
            print(f"✅ {sym}: {len(df)} mum geldi")
        except:
            print(f"❌ {sym}: DF DÖNÜŞTÜRME HATASI")

if data:
    for sym in coins[:10]:
        test_kline(sym)
else:
    print("‼️ Coin listesi alınamadığı için kline testi atlandı.")

print("\n🔍 DEBUG TEST BİTTİ 🔍\n")
print("🟩 Eğer çoğu ✅ ise → MEXC kline endpoint düzgün çalışıyor.")
print("🟥 Eğer çoğu ❌ ise → MEXC kline endpoint anlık sıkıntılı veya rate limit var.")
