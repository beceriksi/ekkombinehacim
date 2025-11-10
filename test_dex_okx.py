# test_dex_okx.py
import requests
import time

DEX_URL = "https://api.dexscreener.com/latest/dex/tokens"
OKX_URL = "https://www.okx.com/api/v5/market/candles"

def get_top_dex_coins(limit=100):
    print("🔍 Dexscreener coin listesi çekiliyor...")
    try:
        r = requests.get("https://api.dexscreener.com/latest/dex/tokens", timeout=15)
        j = r.json()
        coins = []
        for item in j.get("pairs", []):
            sym = item.get("baseToken", {}).get("symbol")
            if sym:
                coins.append(sym + "-USDT")
        coins = list(dict.fromkeys(coins))  # dup kaldır
        print(f"✅ Dexscreener toplam coin: {len(coins)}")
        return coins[:limit]
    except Exception as e:
        print("❌ Dexscreener ERROR:", e)
        return []

def test_okx_kline(symbol):
    print(f"• {symbol}: ", end="")
    try:
        # format OKX: "BTC-USDT"
        r = requests.get(OKX_URL + f"?instId={symbol}&bar=1H&limit=5", timeout=10)
        j = r.json()
        if j.get("data"):
            print("✅ OKX veri var")
        else:
            print("❌ veri yok")
    except Exception:
        print("❌ hata")

print("🔎 Dexscreener + OKX Test Başlıyor...\n")

coins = get_top_dex_coins(10)
if not coins:
    print("❌ Coin listesi bulunamadı!")
else:
    print("\n🔍 İlk 10 coin için OKX 1H kline testi:")
    for s in coins:
        test_okx_kline(s)
        time.sleep(0.3)

print("\n✅ Test bitti.")
