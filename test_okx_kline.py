import requests

print("🔍 OKX KLINE TESTİ BAŞLIYOR...")

url = "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1H"

try:
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        print("❌ HTTP HATA:", r.status_code)
    else:
        data = r.json()
        if "data" in data and len(data["data"])>0:
            print("✅ OKX KLINE OK — Veri geldi")
            print("Örnek mum:", data["data"][0])
        else:
            print("❌ Kline boş, veri yok!")
except Exception as e:
    print("❌ Exception:", str(e))

print("✅ TEST BİTTİ")
