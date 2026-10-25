import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ.get("CHAT_ID", "@Gram_Price_Today")
DECIMALS = 4
IQD_RATE_MANUAL = 0      # ضع رقم سعر السوق (مثل 1500) أو اتركه 0 للسعر الرسمي
IQD_RATE_FALLBACK = 1310
STATE_FILE = "last_price.txt"
BAGHDAD = timezone(timedelta(hours=3))
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


def get_iqd_rate():
    if IQD_RATE_MANUAL > 0:
        return IQD_RATE_MANUAL
    try:
        return float(get_json("https://open.er-api.com/v6/latest/USD")["rates"]["IQD"])
    except Exception as e:
        print("iqd rate failed:", e)
        return IQD_RATE_FALLBACK


def time_12h():
    now = datetime.now(BAGHDAD)
    return f"{now:%I:%M:%S} {'ص' if now.hour < 12 else 'م'}"


def build_text(price, old):
    iqd = price * get_iqd_rate()
    if old is None:
        head, diff = "💎 <b>سعر TON (GRAM) الان</b>", ""
    else:
        d = price - old
        head = ("🟢 <b>صعود</b> ▲" if d > 0 else "🔴 <b>نزول</b> ▼") + " | <b>TON (GRAM)</b>"
        diff = f"\n📊 التغيّر: <code>{d:+.{DECIMALS}f}$</code> ({d / old * 100:+.2f}%)"
    return (f"{head}\n"
            f"━━━━━━━━━━━━━━\n"
            f"💵 الدولار: <b>${price:.{DECIMALS}f}</b>\n"
            f"🇮🇶 الدينار: <b>{iqd:,.0f} د.ع</b>"
            f"{diff}\n"
            f"━━━━━━━━━━━━━━\n"
            f"🕒 {time_12h()}")


def main():
    price = round(get_price(), DECIMALS)

    last = None
    if os.path.exists(STATE_FILE):
        try:
            last = float(open(STATE_FILE).read().strip())
        except ValueError:
            pass

    if last is not None and price == last:
        print(f"unchanged ({price})")
        return

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": build_text(price, last),
        "parse_mode": "HTML",
    }).encode()
    res = get_json(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=data)
    if not res.get("ok"):
        raise SystemExit(f"telegram rejected: {res}")

    open(STATE_FILE, "w").write(str(price))
    print("sent:", price)


if __name__ == "__main__":
    main()
