# symbols_resolver.py
import requests, time

COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
MEXC_TICKER = "https://api.mexc.com/api/v3/ticker/24hr"
BINANCE_EXCHANGE = "https://api.binance.com/api/v3/exchangeInfo"
BYBIT_SYMBOLS = "https://api.bybit.com/spot/v1/symbols"  # public

def jget(url, params=None, retries=3, timeout=10):
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except:
            time.sleep(0.4)
    return None

def top200_coingecko_vs_bourses():
    params = {"vs_currency":"usd","order":"market_cap_desc","per_page":200,"page":1}
    cg = jget(COINGECKO_MARKETS, params)
    if not cg:
        return []
    # prepare exchange symbol sets
    mexc = jget(MEXC_TICKER) or []
    mexc_syms = { (x.get("symbol","") or "").upper()+"USDT" for x in mexc if "symbol" in x }
    bininfo = jget(BINANCE_EXCHANGE) or {}
    bin_syms = {s["symbol"] for s in bininfo.get("symbols", []) if s.get("quoteAsset")=="USDT"} if isinstance(bininfo, dict) else set()
    byb = jget(BYBIT_SYMBOLS) or {}
    byb_syms = { (s.get("name","") or "").replace("/","").upper() for s in (byb.get("result",[]) if isinstance(byb, dict) else []) }

    out = []
    for item in cg:
        coin = item.get("id")
        sym = (item.get("symbol","") or "").upper()
        cand = [sym+"USDT", sym+"/USDT", sym+"-USDT"]
        chosen = None; source = None
        for c in cand:
            if c in mexc_syms:
                chosen = c; source = "MEXC"; break
        if not chosen:
            for c in cand:
                if c in bin_syms:
                    chosen = c; source = "BINANCE"; break
        if not chosen:
            for c in cand:
                if c in byb_syms:
                    chosen = c; source = "BYBIT"; break
        if chosen:
            out.append({"coingecko_id": coin, "symbol": chosen, "exchange": source})
        else:
            # skip if not on main exchanges
            continue
    return out

if __name__ == "__main__":
    res = top200_coingecko_vs_bourses()
    print(f"Found {len(res)} mappings (top200 -> exchange symbol)")
    for r in res[:40]:
        print(r)
