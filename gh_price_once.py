
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ.get("CHAT_ID", "@Gram_Price_Today")

DECIMALS = 4
IQD_RATE_MANUAL = 0
IQD_RATE_FALLBACK = 1310
BAGHDAD = timezone(timedelta(hours=3))
HEADERS = {"User-Agent": "Mozilla/5.0 ton-price-bot"}


def get_json(url, data=None):
    request = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def get_price():
    errors = []
    sources = [
        "https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT",
        "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd",
    ]

    for index, url in enumerate(sources):
        try:
            data = get_json(url)
            price = float(
                data["price"] if index == 0
                else data["the-open-network"]["usd"]
            )
            if price > 0:
                return price
        except Exception as exc:
            errors.append(str(exc))

    raise SystemExit("تعذّر جلب السعر: " + " | ".join(errors))


def get_iqd_rate():
    if IQD_RATE_MANUAL > 0:
        return IQD_RATE_MANUAL
    try:
        data = get_json("https://open.er-api.com/v6/latest/USD")
        return float(data["rates"]["IQD"])
    except Exception as exc:
        print("استخدام سعر الدينار الاحتياطي:", exc)
        return IQD_RATE_FALLBACK


def get_candles():
    try:
        data = get_json(
            "https://api.binance.com/api/v3/klines"
            "?symbol=TONUSDT&interval=1h&limit=120"
        )
        data = data[:-1]  # تجاهل الشمعة غير المكتملة
        if len(data) < 60:
            return None

        return {
            "closes": [float(k[4]) for k in data],
            "highs": [float(k[2]) for k in data],
            "lows": [float(k[3]) for k in data],
            "volumes": [float(k[5]) for k in data],
        }
    except Exception as exc:
        print("تعذّر جلب الشموع:", exc)
        return None


def ema(values, period):
    if len(values) < period:
        return []
    alpha = 2 / (period + 1)
    first = sum(values[:period]) / period
    result = [None] * (period - 1) + [first]
    current = first

    for value in values[period:]:
        current = value * alpha + current * (1 - alpha)
        result.append(current)

    return result


def rsi_series(closes, period=14):
    if len(closes) < period + 1:
        return []

    changes = [
        closes[i] - closes[i - 1]
        for i in range(1, len(closes))
    ]
    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def calculate(gain, loss):
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        rs = gain / loss
        return 100 - 100 / (1 + rs)

    result = [None] * period
    result.append(calculate(avg_gain, avg_loss))

    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        result.append(calculate(avg_gain, avg_loss))

    return result


def technical_analysis(candles):
    if not candles:
        return None

    closes = candles["closes"]
    highs = candles["highs"]
    lows = candles["lows"]
    volumes = candles["volumes"]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    rsi = rsi_series(closes)

    fast = ema(closes, 12)
    slow = ema(closes, 26)

    macd = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(fast, slow)
    ]

    # احسب خط الإشارة على قيم MACD المتاحة فقط
    valid = [x for x in macd if x is not None]
    signal_valid = ema(valid, 9)
    signal = [None] * (len(macd) - len(signal_valid)) + signal_valid

    i = len(closes) - 1
    prev = i - 1

    if not e20 or not e50 or not rsi or not signal:
        return None

    if any(
        series[index] is None
        for series in (e20, e50, rsi, macd, signal)
        for index in (prev, i)
    ):
        return None

    average_volume = sum(volumes[-21:-1]) / 20
    volume_ok = average_volume > 0 and volumes[-1] >= average_volume * 1.10

    bull_cross = macd[prev] <= signal[prev] and macd[i] > signal[i]
    bear_cross = macd[prev] >= signal[prev] and macd[i] < signal[i]

    trend_up = closes[i] > e20[i] > e50[i]
    trend_down = closes[i] < e20[i] < e50[i]

    buy = trend_up and 40 <= rsi[i] <= 65 and bull_cross and volume_ok
    sell = (
        bear_cross and (trend_down or rsi[i] >= 60)
    ) or (
        trend_down and rsi[i] < 40 and volume_ok
    )

    reasons = [
        "السعر فوق EMA20" if closes[i] > e20[i] else "السعر تحت EMA20",
        "الاتجاه المتوسط صاعد" if e20[i] > e50[i] else "الاتجاه المتوسط غير صاعد",
        f"RSI = {rsi[i]:.1f}",
        "حجم التداول أعلى من المتوسط" if volume_ok else "حجم التداول لا يؤكد الإشارة",
    ]

    return {
        "buy": buy,
        "sell": sell,
        "rsi": rsi[i],
        "ema20": e20[i],
        "ema50": e50[i],
        "high24": max(highs[-24:]),
        "low24": min(lows[-24:]),
        "change24": (closes[i] / closes[-25] - 1) * 100,
        "reasons": reasons,
    }


def time_12h():
    now = datetime.now(BAGHDAD)
    suffix = "ص" if now.hour < 12 else "م"
    return f"{now:%I:%M:%S} {suffix}"


def build_text(price, old, analysis):
    iqd = price * get_iqd_rate()

    if old is None:
        heading = "💎 <b>سعر TON الآن</b>"
        diff = ""
    elif price == old:
        heading = "⚪ <b>سعر TON الآن</b>"
        diff = "\n📊 التغيّر منذ آخر تحديث: بدون تغيير"
    else:
        delta = price - old
        heading = (
            "🟢 <b>صعود ▲ | TON</b>"
            if delta > 0 else "🔴 <b>نزول ▼ | TON</b>"
        )
        percent = delta / old * 100 if old else 0
        diff = (
            f"\n📊 التغيّر منذ آخر تحديث: "
            f"<code>{delta:+.{DECIMALS}f}$</code> "
            f"({percent:+.2f}%)"
        )

    message = (
        f"{heading}\n━━━━━━━━━━━━━━\n"
        f"💵 السعر بالدولار: <b>${price:.{DECIMALS}f}</b>\n"
        f"🇮🇶 السعر بالدينار: <b>{iqd:,.0f} د.ع</b>{diff}\n"
    )

    if analysis:
        if analysis["buy"]:
            signal = "🟢 <b>إشارة شراء محتملة</b>"
        elif analysis["sell"]:
            signal = "🔴 <b>إشارة بيع محتملة</b>"
        else:
            signal = "🟡 <b>انتظار — لا توجد إشارة قوية</b>"

        message += (
            "━━━━━━━━━━━━━━\n"
            f"📅 التغيّر خلال 24 ساعة: <b>{analysis['change24']:+.2f}%</b>\n"
            f"⬆️ أعلى 24 ساعة: ${analysis['high24']:.{DECIMALS}f}\n"
            f"⬇️ أقل 24 ساعة: ${analysis['low24']:.{DECIMALS}f}\n"
            f"📈 RSI (14): <b>{analysis['rsi']:.1f}</b>\n"
            f"📉 EMA20: ${analysis['ema20']:.{DECIMALS}f}\n"
            f"📉 EMA50: ${analysis['ema50']:.{DECIMALS}f}\n"
            "━━━━━━━━━━━━━━\n"
            f"{signal}\n🔎 <b>أسباب التقييم:</b>\n"
            + "\n".join(f"• {x}" for x in analysis["reasons"])
            + "\n\n<i>الإشارات احتمالية وليست ضماناً للربح أو نصيحة مالية.</i>\n"
        )
    else:
        message += (
            "━━━━━━━━━━━━━━\n"
            "🟡 تعذّر تأكيد الإشارة الفنية حالياً.\n"
        )

    return message + f"━━━━━━━━━━━━━━\n🕒 {time_12h()}"


def read_last_price():
    try:
        with open("last_price.txt", "r", encoding="utf-8") as file:
            return float(file.read().strip())
    except (OSError, ValueError):
        return None


def main():
    price = round(get_price(), DECIMALS)
    analysis = technical_analysis(get_candles())
    old = read_last_price()
    message = build_text(price, old, analysis)

    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }).encode("utf-8")

    result = get_json(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=payload,
    )

    if not result.get("ok"):
        raise SystemExit(f"Telegram error: {result}")

    with open("last_price.txt", "w", encoding="utf-8") as file:
        file.write(str(price))

    print("Message sent successfully:", price)


if __name__ == "__main__":
    main()
