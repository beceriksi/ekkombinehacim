import requests
import pandas as pd
import time

BINANCE = "https://api.binance.com"

def jget(url, params=None, retries=3, timeout=12):
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except:
            time.sleep(0.3)
    return None

def get_top_coins(limit=30):
    d = jget(f"{BINANCE}/api/v3/ticker/24hr")
    if not d:
        print("❌ Binance ticker verisi GELMEDİ!")
        return []
    rows = [x for x in d if x.get("symbol","").endswith("USDT")]
    rows.sort(key=lambda x: float(x.get("quoteVolume","0")), reverse=True)
    coins = [x["symbol"] for x in rows[:limit]]
    print(f"✅ Binance SPOT (top {limit}) coin sayısı: {len(coins)}")
    return coins

def test_klines(symbol):
    d = jget(f"{BINANCE}/api/v3/klines", {"symbol": symbol, "interval": "1h", "limit": 50})
    if not d:
        return False
    try:
        df = pd.DataFrame(d)
        return len(df) > 0
    except:
        return False

def main():
    print("🧪 BINANCE COIN GÖRÜNÜRLÜK TESTİ BAŞLIYOR...")
    coins = get_top_coins(30)
    if not coins:
        print("❌ Coin listesi boş!")
        return

    print("\n🔍 İlk 10 coin için 1H kline testi:")
    for c in coins[:10]:
        ok = test_klines(c)
        if ok:
            print(f"✅ {c}: VERİ VAR")
        else:
            print(f"❌ {c}: VERİ YOK / HATALI")

    print("\n✅ Test bitti.")

if __name__ == "__main__":
    main()
