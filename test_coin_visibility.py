import requests
import pandas as pd
import time

MEXC = "https://api.mexc.com"

def jget(url, params=None, retries=3, timeout=12):
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except:
            time.sleep(0.3)
    return None

def get_top_coins(limit=200):
    d = jget(f"{MEXC}/api/v3/ticker/24hr")
    if not d:
        print("❌ MEXC ticker verisi GELMEDİ!")
        return []
    rows = [x for x in d if x.get("symbol","").endswith("USDT")]
    rows.sort(key=lambda x: float(x.get("quoteVolume","0")), reverse=True)
    coins = [x["symbol"] for x in rows[:limit]]
    print(f"✅ MEXC SPOT (top {limit}) coin sayısı: {len(coins)}")
    return coins

def test_klines(symbol):
    d = jget(f"{MEXC}/api/v3/klines", {"symbol": symbol, "interval": "1h", "limit": 50})
    if not d:
        return False
    try:
        df = pd.DataFrame(d)
        return len(df) > 0
    except:
        return False

def main():
    print("🧪 MEXC COIN GÖRÜNÜRLÜK TESTİ BAŞLIYOR...")
    coins = get_top_coins(50)  # ilk 50 coin test edilecek
    if not coins:
        print("❌ Coin listesi boş → Bot coin göremiyor.")
        return

    print("\n🔍 İlk 10 coin için 1H kline testi:")
    for c in coins[:10]:
        ok = test_klines(c)
        if ok:
            print(f"✅ {c}: VERİ VAR")
        else:
            print(f"❌ {c}: VERİ YOK / HATALI")

    print("\n✅ Test bitti.")
    print("Eğer çoğu ❌ ise → MEXC kline endpoint sıkıntılıdır (anlık).")
    print("Eğer çoğu ✅ ise → Bot coinleri görüyor → SINYAL KOŞULLARI aşırı sıkı olabilir.")
    
if __name__ == "__main__":
    main()
