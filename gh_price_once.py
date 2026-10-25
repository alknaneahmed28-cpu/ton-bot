import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# Set these in GitHub repository Settings > Secrets and variables > Actions.
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ.get("CHAT_ID", "@Gram_Price_Today")
DECIMALS = 4
IQD_RATE_MANUAL = 0  # Set market rate (e.g. 1500), or 0 to use the API rate.
IQD_RATE_FALLBACK = 1310
STATE_FILE = "last_price.txt"
BAGHDAD = timezone(timedelta(hours=3))
HEADERS = {"User-Agent": "Mozilla/5.0 ton-price-bot"}


def get_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


# Price sources
def binance(symbol):
    return lambda: float(
        get_json(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        )["price"]
    )


def coingecko():
    data = get_json(
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=the-open-network&vs_currencies=usd"
    )
    return float(data["the-open-network"]["usd"])


def get_price():
    errors = []
    for name, fn in (
        ("Binance GRAM", binance("GRAMUSDT")),
        ("Binance TON", binance("TONUSDT")),
        ("CoinGecko", coingecko),
    ):
        try:
            return fn()
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise SystemExit("All price sources failed: " + " | ".join(errors))


def get_iqd_rate():
    if IQD_RATE_MANUAL > 0:
        return IQD_RATE_MANUAL
    try:
        data = get_json("https://open.er-api.com/v6/latest/USD")
        return float(data["rates"]["IQD"])
    except Exception as exc:
        print("IQD rate failed:", exc)
        return IQD_RATE_FALLBACK


# Technical analysis (hourly candles)
def get_candles():
    """Return (closes, highs, lows) for about the last 48 hours, or None."""
    for symbol in ("GRAMUSDT", "TONUSDT"):
        try:
            candles = get_json(
                "https://api.binance.com/api/v3/klines"
                f"?symbol={symbol}&interval=1h&limit=48"
            )
            if len(candles) >= 30:
                return (
                    [float(candle[4]) for candle in candles],
                    [float(candle[2]) for candle in candles],
                    [float(candle[3]) for candle in candles],
                )
        except Exception as exc:
            print(f"Klines for {symbol} failed:", exc)

    try:
        data = get_json(
            "https://api.coingecko.com/api/v3/coins/the-open-network/"
            "market_chart?vs_currency=usd&days=2"
        )
        closes = [point[1] for point in data["prices"]][-48:]
        if len(closes) >= 30:
            return closes, closes, closes
    except Exception as exc:
        print("CoinGecko chart failed:", exc)

    return None


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    changes = [b - a for a, b in zip(closes, closes[1:])]
    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    relative_strength = avg_gain / avg_loss
    return 100 - 100 / (1 + relative_strength)


def analyze(price):
    candles = get_candles()
    if not candles:
        return None

    closes, highs, lows = candles
    closes = closes[:-1] + [price]
    rsi = calc_rsi(closes)
    if rsi is None:
        return None

    last_24 = closes[-24:]
    sma = sum(last_24) / len(last_24)
    reference = closes[-25] if len(closes) >= 25 else closes[0]

    return {
        "rsi": rsi,
        "change24": ((price - reference) / reference * 100) if reference else 0,
        "hi": max(max(highs[-24:]), price),
        "lo": min(min(lows[-24:]), price),
        "buy": rsi <= 40 and price < sma,
        "sell": rsi >= 60 and price > sma,
    }


def time_12h():
    now = datetime.now(BAGHDAD)
    return f"{now:%I:%M:%S} {'ص' if now.hour < 12 else 'م'}"


def build_text(price, old):
    iqd = price * get_iqd_rate()

    if old is None:
        heading = "💎 <b>سعر TON (GRAM) الآن</b>"
        difference = ""
    elif price == old:
        heading = "⚪ <b>سعر TON (GRAM) الآن</b>"
        difference = "\n📊 التغيّر: بدون تغيير"
    else:
        delta = price - old
        heading = (
            "🟢 <b>صعود</b> ▲" if delta > 0 else "🔴 <b>نزول</b> ▼"
        ) + " | <b>TON (GRAM)</b>"
        percent = delta / old * 100 if old else 0
        difference = (
            f"\n📊 التغيّر: <code>{delta:+.{DECIMALS}f}$</code> "
            f"({percent:+.2f}%)"
        )

    message = (
        f"{heading}\n"
        "━━━━━━━━━━━━━━\n"
        f"💵 الدولار: <b>${price:.{DECIMALS}f}</b>\n"
        f"🇮🇶 الدينار: <b>{iqd:,.0f} د.ع</b>"
        f"{difference}\n"
    )

    analysis = analyze(price)
    if analysis:
        message += (
            "━━━━━━━━━━━━━━\n"
            f"📅 24 ساعة: <b>{analysis['change24']:+.2f}%</b>\n"
            f"⬆️ الأعلى: ${analysis['hi']:.{DECIMALS}f}  "
            f"⬇️ الأقل: ${analysis['lo']:.{DECIMALS}f}\n"
            f"📈 مؤشر RSI: <b>{analysis['rsi']:.0f}</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"🛒 الوقت مناسب للشراء: <b>{'✅ نعم' if analysis['buy'] else '❌ لا'}</b>\n"
            f"💰 الوقت مناسب للبيع: <b>{'✅ نعم' if analysis['sell'] else '❌ لا'}</b>\n"
            "<i>⚠️ إشارة فنية بسيطة وليست نصيحة مالية.</i>\n"
        )

    message += f"━━━━━━━━━━━━━━\n🕒 {time_12h()}"
    return message


def main():
    price = round(get_price(), DECIMALS)

    last = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as file:
                last = float(file.read().strip())
        except (ValueError, OSError):
            pass

    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": build_text(price, last),
        "parse_mode": "HTML",
    }).encode("utf-8")

    response = get_json(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=payload,
    )
    if not response.get("ok"):
        raise SystemExit(f"Telegram rejected the message: {response}")

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        file.write(str(price))

    print("Sent price:", price)


if __name__ == "__main__":
    main()
