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


# ===== السعر =====
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


# ===== التحليل الفني (شمعات ساعة) =====
def get_candles():
    """يرجع (closes, highs, lows) لآخر ~48 ساعة، أو None."""
    for sym in ("GRAMUSDT", "TONUSDT"):
        try:
            ks = get_json("https://api.binance.com/api/v3/klines"
                          f"?symbol={sym}&interval=1h&limit=48")
            if len(ks) >= 30:
                return ([float(k[4]) for k in ks],
                        [float(k[2]) for k in ks],
                        [float(k[3]) for k in ks])
        except Exception as e:
            print(f"klines {sym} failed:", e)
    try:
        d = get_json("https://api.coingecko.com/api/v3/coins/the-open-network/"
                     "market_chart?vs_currency=usd&days=2")
        closes = [p[1] for p in d["prices"]][-48:]
        if len(closes) >= 30:
            return closes, closes, closes
    except Exception as e:
        print("coingecko chart failed:", e)
    return None


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for a, b in zip(closes, closes[1:]):
        d = b - a
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def analyze(price):
    c = get_candles()
    if not c:
        return None
    closes, highs, lows = c
    closes = closes[:-1] + [price]          # آخر شمعة = السعر الحالي
    rsi = calc_rsi(closes)
    if rsi is None:
        return None
    last24 = closes[-24:]
    sma = sum(last24) / len(last24)
    ref = closes[-25] if len(closes) >= 25 else closes[0]
    return {
        "rsi": rsi,
        "change24": (price - ref) / ref * 100,
        "hi": max(max(highs[-24:]), price),
        "lo": min(min(lows[-24:]), price),
        # شراء: السوق مبالغ بنزوله (RSI منخفض) والسعر تحت متوسط 24 ساعة
        "buy": rsi <= 40 and price < sma,
        # بيع: السوق مبالغ بصعوده (RSI مرتفع) والسعر فوق متوسط 24 ساعة
        "sell": rsi >= 60 and price > sma,
    }


# ===== الرسالة =====
def time_12h():
    now = datetime.now(BAGHDAD)
    return f"{now:%I:%M:%S} {'ص' if now.hour < 12 else 'م'}"


def build_text(price, old):
    iqd = price * get_iqd_rate()
    if old is None:
        head, diff = "💎 <b>سعر TON (GRAM) الان</b>", ""
    elif price == old:
        head = "⚪ <b>سعر TON (GRAM) الان</b>"
        diff = "\n📊 التغيّر: بدون تغيير"
    else:
        d = price - old
        head = ("🟢 <b>صعود</b> ▲" if d > 0 else "🔴 <b>نزول</b> ▼") + " | <b>TON (GRAM)</b>"
        diff = f"\n📊 التغيّر: <code>{d:+.{DECIMALS}f}$</code> ({d / old * 100:+.2f}%)"

    text = (f"{head}\n"
            f"━━━━━━━━━━━━━━\n"
            f"💵 الدولار: <b>${price:.{DECIMALS}f}</b>\n"
            f"🇮🇶 الدينار: <b>{iqd:,.0f} د.ع</b>"
            f"{diff}\n")

    a = analyze(price)
    if a:
        text += (f"━━━━━━━━━━━━━━\n"
                 f"📅 24 ساعة: <b>{a['change24']:+.2f}%</b>\n"
                 f"⬆️ الأعلى: ${a['hi']:.{DECIMALS}f}  ⬇️ الأقل: ${a['lo']:.{DECIMALS}f}\n"
                 f"📈 مؤشر RSI: <b>{a['rsi']:.0f}</b>\n"
                 f"━━━━━━━━━━━━━━\n"
                 f"🛒 الوقت مناسب للشراء: <b>{'✅ نعم' if a['buy'] else '❌ لا'}</b>\n"
                 f"💰 الوقت مناسب للبيع: <b>{'✅ نعم' if a['sell'] else '❌ لا'}</b>\n"
                 f"<i>⚠️ إشارة فنية بسيطة وليست نصيحة مالية.</i>\n")
    text += f"━━━━━━━━━━━━━━\n🕒 {time_12h()}"
    return text


def main():
    price = round(get_price(), DECIMALS)

    last = None
    if os.path.exists(STATE_FILE):
        try:
            last = float(open(STATE_FILE).read().strip())
        except ValueError:
            pass

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
