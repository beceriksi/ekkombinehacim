import requests, time

print("🔍 Dexscreener coin listesi testi başlıyor...\n")

url = "https://api.dexscreener.io/latest/dex/tokens"

try:
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        print(f"❌ Dexscreener HTTP HATA: {r.status_code}")
    else:
        data = r.json()
        coins = data.get("pairs", [])
        print(f"✅ Coin listesi çekildi. Toplam: {len(coins)} tane pair.")
        for c in coins[:10]:
            print("•", c.get("symbol"), c.get("baseToken", {}).get("address"))
except Exception as e:
    print("❌ Dexscreener ERROR:", e)

print("\n✅ TEST BİTTİ")
