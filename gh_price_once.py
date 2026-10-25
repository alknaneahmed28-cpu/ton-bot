import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["@Gram_Price_Today"]
DECIMALS = 2
STATE_FILE = "last_price.txt"
HEADERS = {"User-Agent": "Mozilla/5.0 ton-price-bot"}


def get_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def binance(sym):
    return lambda: float(get_json(
        f"https://api.binance.com/api/v3/ticker/price?symbol={sym}")["price"])


def coingecko():
    d = get_json("https://api.coingecko.com/api/v3/simple/price"
                 "?ids=the-open-network&vs_currencies=usd")
    return float(d["the-open-network"]["usd"])


def get_price():
    errors = []
    for name, fn in [("Binance GRAM", binance("GRAMUSDT")),
                     ("Binance TON", binance("TONUSDT")),
                     ("CoinGecko", coingecko)]:
        try:
            return fn()
        except Exception as e:
            errors.append(f"{name}: {e}")
    raise SystemExit("all sources failed: " + " | ".join(errors))


def main():
    price = get_price()
    shown = round(price, DECIMALS)

    last = None
    if os.path.exists(STATE_FILE):
        try:
            last = float(open(STATE_FILE).read().strip())
        except ValueError:
            pass

    if last is not None and shown == last:
        print(f"unchanged ({shown})")
        return

    if last is None or shown == last:
        arrow = "💎"
    else:
        arrow = "🟢 ▲" if shown > last else "🔴 ▼"
    text = (f"{arrow} سعر TON (GRAM) الان: ${shown:.{DECIMALS}f}\n"
            f"🕒 {datetime.now(timezone.utc):%H:%M} UTC")
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
    res = get_json(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=data)
    if not res.get("ok"):
        raise SystemExit(f"telegram rejected: {res}")

    open(STATE_FILE, "w").write(str(shown))
    print("sent:", shown)


if __name__ == "__main__":
    main()
