import ccxt
import requests
import time

MEXC = "https://contract.mexc.com"

def jget(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=8)
        return r.json()
    except:
        return None

def test_kline(sym):
    url = f"{MEXC}/api/v1/contract/kline/{sym}"
    d = jget(url, {"interval":"1h","limit":5})
    if not d or "data" not in d or not d["data"]:
        return False
    return True

def main():
    print("MEXC coin listesi test ediliyor...")
    
    try:
        ex = ccxt.mexc({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        markets = ex.load_markets()
    except Exception as e:
        print("CCXT market yükleme hatası:", str(e))
        return

    symbols_raw = []
    symbols_mexc_format = []

    for s, m in ex.markets.items():
        if m.get("contract") and m.get("quote") == "USDT" and m.get("linear"):
            # CCXT market id (MEXC API ile uyumlu olmalı)
            symbols_raw.append(m['id'])
            symbols_mexc_format.append(m['id'])

    symbols_raw = list(set(symbols_raw))

    print(f"\n✅ CCXT (swap) kaç coin buldu? {len(symbols_raw)} adet\n")

    if len(symbols_raw) == 0:
        print("⚠️ Coin listesi 0 — hiç coin çekemedi. Bu yüzden sinyal yok.")
        return

    # 3 adet coin seç test et
    test_coins = symbols_raw[:5]

    for sym in test_coins:
        ok = test_kline(sym)
        print(f"• {sym} → Kline veri: {'✅ ÇALIŞIYOR' if ok else '❌ BOŞ / HATALI'}")

    print("\nTest bitti.")

if __name__ == "__main__":
    main()
