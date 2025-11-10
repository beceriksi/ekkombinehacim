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

print("\n🔍 MEXC COIN GÖRÜNÜRLÜK TESTİ BAŞLIYOR...\n")

# -----------------------------
# 1) COIN LİSTESİ TESTİ
# -----------------------------
data = jget(f"{MEXC}/api/v3/ticker/24hr")

if not data:
    print("❌ MEXC 24hr endpoint VERİ VERMEDİ!")
    exit()

coins = [x["symbol"] for x in data if x["symbol"].endswith("USDT")]

print(f"✅ MEXC SPOT (top 50) coin sayısı: {len(coins[:50])}\n")

print("🔍 İlk 10 coin için 1H kline testi:\n")

def test(sym):
    k = jget(f"{MEXC}/api/v3/klines",
             {"symbol": sym, "interval": "1h", "limit": 100})
    if not k:
        print(f"❌ {sym}: VERİ YOK / HATALI")
    else:
        try:
            df = pd.DataFrame(k)
            print(f"✅ {sym}: {len(df)} mum geldi")
        except:
            print(f"❌ {sym}: DF DÖNÜŞTÜRME HATALI")

for sym in coins[:10]:
    test(sym)

print("\n✅ Test bitti.\n")
print("Eğer çoğu ❌ ise → MEXC kline endpoint sıkıntılıdır (anlık).")
print("Eğer çoğu ✅ ise → Bot coinleri görüyor → SİNYAL KOŞULLARI aşırı sıkı olabilir.")
