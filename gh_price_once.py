import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ.get("CHAT_ID", "@Gram_Price_Today")

DECIMALS = 4
IQD_RATE_MANUAL = 0  # Set market rate (e.g. 1500), or 0 to use the API rate.
IQD_RATE_FALLBACK = 1310
STATE_FILE = "last_price.txt"
BAGHDAD = timezone(timedelta(hours=3))
HEADERS = {"User-Agent": "Mozilla/5.0 ton-price-bot"}


def get_json(url, data=None):
    request = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def get_price():
    errors = []
    try:
        data = get_json(
            "https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT"
        )
        price = float(data["price"])
        if price > 0:
            return price
    except Exception as exc:
        errors.append(f"Binance TON: {exc}")

    try:
        data = get_json(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=the-open-network&vs_currencies=usd"
        )
        price = float(data["the-open-network"]["usd"])
        if price > 0:
            return price
    except Exception as exc:
        errors.append(f"CoinGecko TON: {exc}")

    raise SystemExit("تعذّر جلب السعر من جميع المصادر: " + " | ".join(errors))


def get_iqd_rate():
    if IQD_RATE_MANUAL > 0:
        return IQD_RATE_MANUAL
    try:
        return float(
            get_json("https://open.er-api.com/v6/latest/USD")["rates"]["IQD"]
        )
    except Exception as exc:
        print("تعذّر جلب سعر الدينار، استخدام السعر الاحتياطي:", exc)
        return IQD_RATE_FALLBACK


def get_candles():
    """Fetch completed 1-hour TON/USDT candles with volume from Binance."""
    try:
        candles = get_json(
            "https://api.binance.com/api/v3/klines"
            "?symbol=TONUSDT&interval=1h&limit=120"
        )
        # Ignore the final candle because it may still be forming.
        candles = candles[:-1]
        if len(candles) >= 60:
            return {
                "closes": [float(k[4]) for k in candles],
                "highs": [float(k[2]) for k in candles],
                "lows": [float(k[3]) for k in candles],
                "volumes": [float(k[5]) for k in candles],
            }
    except Exception as exc:
        print("تعذّر جلب شموع TON من Binance:", exc)
    return None


def ema(values, period):
    if len(values) < period:
        return []
    alpha = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for value in values[period:]:
        result.append(value * alpha + result[-1] * (1 - alpha))
    return [None] * (period - 1) + result


def rsi_series(closes, period=14):
    if len(closes) < period + 1:
        return []
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    values = [None] * period

    def value(gain, loss):
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        rs = gain / loss
        return 100 - 100 / (1 + rs)

    values.append(value(avg_gain, avg_loss))
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        values.append(value(avg_gain, avg_loss))
    return values


def technical_analysis(candles):
    """Rule-based signals, not guaranteed predictions. Uses completed 1h candles."""
    if not candles:
        return None

    closes = candles["closes"]
    highs = candles["highs"]
    lows = candles["lows"]
    volumes = candles["volumes"]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi = rsi_series(closes, 14)
    macd_fast = ema(closes, 12)
    macd_slow = ema(closes, 26)
    if not ema20 or not ema50 or not rsi or len(closes) < 60:
        return None

    # Align EMA series by index; MACD is EMA12 - EMA26.
    macd_line = []
    for fast, slow in zip(macd_fast, macd_slow):
        if fast is None or slow is None:
            macd_line.append(None)
        else:
            macd_line.append(fast - slow)
    valid_macd = [x for x in macd_line if x is not None]
    signal_valid = ema(valid_macd, 9)
    signal_line = [None] * (len(macd_line) - len(signal_valid)) + signal_valid

    i = len(closes) - 1
    prev = i - 1
    if any(series[i] is None for series in (ema20, ema50, rsi, macd_line, signal_line)):
        return None
    if any(series[prev] is None for series in (macd_line, signal_line)):
        return None

    average_volume = sum(volumes[-21:-1]) / 20
    volume_ok = average_volume > 0 and volumes[-1] >= average_volume * 1.10
    macd_bull_cross = macd_line[prev] <= signal_line[prev] and macd_line[i] > signal_line[i]
    macd_bear_cross = macd_line[prev] >= signal_line[prev] and macd_line[i] < signal_line[i]

    # Buy only when trend, momentum and volume agree. These are conservative rules.
    trend_up = closes[i] > ema20[i] > ema50[i]
    trend_down = closes[i] < ema20[i] < ema50[i]
    buy = trend_up and 40 <= rsi[i] <= 65 and macd_bull_cross and volume_ok
    sell = (macd_bear_cross and (trend_down or rsi[i] >= 60)) or (
        trend_down and rsi[i] < 40 and volume_ok
    )

    reasons = []
    if closes[i] > ema20[i]:
        reasons.append("السعر فوق EMA20")
    else:
        reasons.append("السعر تحت EMA20")
    if ema20[i] > ema50[i]:
        reasons.append("الاتجاه المتوسط صاعد")
    else:
        reasons.append("الاتجاه المتوسط غير صاعد")
    reasons.append(f"RSI = {rsi[i]:.1f}")
    reasons.append("حجم التداول أعلى من المتوسط" if volume_ok else "حجم التداول لا يؤكد الإشارة")

    return {
        "buy": buy,
        "sell": sell,
        "rsi": rsi[i],
        "ema20": ema20[i],
        "ema50": ema50[i],
        "close": closes[i],
        "high24": max(highs[-24:]),
        "low24": min(lows[-24:]),
        "change24": (closes[i] / closes[-25] - 1) * 100 if closes[-25] else 0,
        "volume_ok": volume_ok,
        "reasons": reasons,
    }


def time_12h():
    now = datetime.now(BAGHDAD)
    return f"{now:%I:%M:%S} {'ص' if now.hour < 12 else 'م'}"


def build_text(price, old, analysis):
    iqd = price * get_iqd_rate()
    if old is None:
        heading, diff = "💎 <b>سعر TON الآن</b>", ""
    elif price == old:
        heading, diff = "⚪ <b>سعر TON الآن</b>", "\n📊 التغيّر منذ آخر تحديث: بدون تغيير"
    else:
        delta = price - old
        heading = ("🟢 <b>صعود</b> ▲" if delta > 0 else "🔴 <b>نزول</b> ▼") + " | <b>TON</b>"
        percent = (delta / old * 100) if old else 0
        diff = f"\n📊 التغيّر منذ آخر تحديث: <code>{delta:+.{DECIMALS}f}$</code> ({percent:+.2f}%)"

    text = (
        f"{heading}\n━━━━━━━━━━━━━━\n"
        f"💵 السعر بالدولار: <b>${price:.{DECIMALS}f}</b>\n"
        f"🇮🇶 السعر بالدينار: <b>{iqd:,.0f} د.ع</b>{diff}\n"
    )

    if analysis:
        if analysis["buy"]:
            signal = "🟢 <b>إشارة شراء محتملة</b>"
        elif analysis["sell"]:
            signal = "🔴 <b>إشارة بيع/تقليل مخاطرة محتملة</b>"
        else:
            signal = "🟡 <b>انتظار — لا توجد إشارة قوية الآن</b>"

        text += (
            "━━━━━━━━━━━━━━\n"
            f"📅 تغيّر آخر 24 ساعة (شموع ساعة): <b>{analysis['change24']:+.2f}%</b>\n"
            f"⬆️ أعلى 24 ساعة: ${analysis['high24']:.{DECIMALS}f}\n"
            f"⬇️ أقل 24 ساعة: ${analysis['low24']:.{DECIMALS}f}\n"
            f"📈 RSI (14): <b>{analysis['rsi']:.1f}</b>\n"
            f"📉 EMA20: ${analysis['ema20']:.{DECIMALS}f}\n"
            f"📉 EMA50: ${analysis['ema50']:.{DECIMALS}f}\n"
            "━━━━━━━━━━━━━━\n"
            f"{signal}\n"
            "🔎 <b>أسباب التقييم:</b>\n"
            + "\n".join(f"• {reason}" for reason in analysis["reasons"])
            + "\n\n<i>الإشارة مبنية على شموع ساعة مكتملة ومؤشرات فنية، وليست ضماناً للربح أو نصيحة مالية. لا تعتمد عليها وحدها.</i>\n"
        )
    else:
        text += (
            "━━━━━━━━━━━━━━\n"
            "🟡 <b>تعذّر تأكيد إشارة الشراء/البيع</b>\n"
            "بيانات الشموع غير متاحة حالياً؛ لا تعتبر هذا إشارة شراء أو بيع.\n"
        )

    return text + f"━━━━━━━━━━━━━━\n🕒 {time_12h()}"


def read_last_price():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return float(file.read().strip())
    except (OSError, ValueError):
        return None


def main():
    price = round(get_price(), DECIMALS)
    candles = get_candles()
    analysis = technical_analysis(candles)
    last = read_last_price()

    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": build_text(price, last, analysis),
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
    print("Message sent. Price:", price, "Signal:", (
        "BUY" if analysis and analysis["buy"] else
        "SELL" if analysis and analysis["sell"] else "WAIT"
    ))


if __name__ == "__main__":
    main()
