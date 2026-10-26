# Dependency-free TON price publisher; no matplotlib required.
#!/usr/bin/env python3
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ.get("CHAT_ID", "@Gram_Price_Today")
ADMIN_IDS = {x.strip() for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}
ALERT_USD = os.environ.get("ALERT_USD", "").strip()
STATE_FILE = "ton_state.json"
BAGHDAD = timezone(timedelta(hours=3))

BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/24hr?symbol=TONUSDT"
COINGECKO = "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd&include_24hr_change=true"
COINGECKO_HISTORY = "https://api.coingecko.com/api/v3/coins/the-open-network/market_chart?vs_currency=usd&days=1&interval=hourly"
FX_API = "https://open.er-api.com/v6/latest/USD"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "TONPriceBot/3.0"})
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tg(method, payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(payload).encode(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram API error"))
    return result.get("result")


def bot_username():
    try:
        return tg("getMe", {}).get("username", "")
    except Exception:
        return ""


def inline_keyboard():
    username = bot_username()
    start_url = f"https://t.me/{username}?start=stars" if username else "https://t.me/Gram_Price_Today"
    share_url = "https://t.me/share/url?url=https%3A%2F%2Ft.me%2FGram_Price_Today&text=تابعوا%20أسعار%20TON%20اليومية"
    return json.dumps({"inline_keyboard": [
        [{"text": "📢 الاشتراك بالقناة", "url": "https://t.me/Gram_Price_Today"},
         {"text": "📤 مشاركة القناة", "url": share_url}],
        [{"text": "⭐ حاسبة TON → Stars", "url": start_url}]
    ]}, ensure_ascii=False)


def send(message, chat_id=None, with_keyboard=False):
    payload = {
        "chat_id": chat_id or CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true"
    }
    if with_keyboard:
        payload["reply_markup"] = inline_keyboard()
    return tg("sendMessage", payload)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(STATE_FILE + ".tmp", STATE_FILE)


def market_data():
    data = {"price": None, "change": None, "high": None, "low": None}

    try:
        result = get_json(BINANCE_TICKER)
        data.update(
            price=number(result.get("lastPrice")),
            change=number(result.get("priceChangePercent")),
            high=number(result.get("highPrice")),
            low=number(result.get("lowPrice")),
        )
    except Exception as exc:
        print("Binance unavailable:", exc, file=sys.stderr)

    if data["price"] is None:
        try:
            result = get_json(COINGECKO)["the-open-network"]
            data["price"] = number(result.get("usd"))
            data["change"] = number(result.get("usd_24h_change"))
        except Exception as exc:
            print("CoinGecko unavailable:", exc, file=sys.stderr)

    if data["high"] is None or data["low"] is None:
        try:
            result = get_json(COINGECKO_HISTORY)
            prices = [
                number(row[1]) for row in result.get("prices", [])
                if len(row) > 1 and number(row[1]) is not None
            ]
            if prices:
                if data["high"] is None:
                    data["high"] = max(prices)
                if data["low"] is None:
                    data["low"] = min(prices)
        except Exception as exc:
            print("CoinGecko history unavailable:", exc, file=sys.stderr)

    return data


def fx_rate():
    try:
        result = get_json(FX_API)
        rate = number(result.get("rates", {}).get("IQD"))
        return rate if rate and rate > 0 else None
    except Exception as exc:
        print("Exchange rate unavailable:", exc, file=sys.stderr)
        return None


def change_text(value):
    if value is None:
        return "غير متوفر حالياً"
    if value > 0:
        return f"🟢 ▲ {value:+.2f}%"
    if value < 0:
        return f"🔴 ▼ {value:+.2f}%"
    return f"⚪ {value:+.2f}%"


def build_post(data, rate, previous):
    price = data["price"]
    now = datetime.now(BAGHDAD)

    iqd = f"{price * rate:,.0f} د.ع" if rate is not None else "غير متوفر حالياً"
    high = f"${data['high']:.4f}" if data["high"] is not None else "غير متوفر"
    low = f"${data['low']:.4f}" if data["low"] is not None else "غير متوفر"

    if previous is None:
        difference = "بانتظار التحديث القادم"
    else:
        delta = price - previous
        emoji = "🟢" if delta > 0 else "🔴" if delta < 0 else "⚪"
        difference = f"{emoji} {delta:+.4f} USD"

    return (
        "💎┏━━━━━━━━━━━━━━━━━━━━┓\n"
        "      TON  |  LIVE MARKET\n"
        "┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        "💵 السعر بالدولار\n"
        f"　➜ `${price:.4f} USDT`\n\n"
        "🇮🇶 السعر بالدينار العراقي\n"
        f"　➜ `{iqd}`\n\n"
        "📊 إحصائيات السوق\n"
        f"　📈 تغيّر 24 ساعة: `{change_text(data['change'])}`\n"
        f"　🔺 أعلى سعر: `{high}`\n"
        f"　🔻 أقل سعر: `{low}`\n\n"
        "📉 مقارنة بالتحديث السابق\n"
        f"　➜ `{difference}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🕒 آخر تحديث: `{now.strftime('%I:%M:%S %p')}`\n"
        f"📅 التاريخ: `{now.strftime('%d-%m-%Y')}`\n\n"
        "⚠️ الأسعار متغيرة باستمرار وقد تختلف بين المنصات. تحقق قبل التداول.\n\n"
        "💎 @Gram_Price_Today"
    )


def admin_commands(state):
    offset = int(state.get("update_offset", 0))
    updates = tg("getUpdates", {
        "offset": offset + 1,
        "timeout": 0,
        "allowed_updates": json.dumps(["message"])
    }) or []

    for update in updates:
        state["update_offset"] = max(
            int(state.get("update_offset", 0)), int(update.get("update_id", 0))
        )
        message = update.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        parts = (message.get("text") or "").strip().split()
        command = parts[0].lower().split("@")[0] if parts else ""
        user_id = str((message.get("from") or {}).get("id", ""))
        is_admin = user_id in ADMIN_IDS

        if command == "/start":
            send(
                "أهلاً بك! ⭐ لحساب النجوم اكتب:\n/stars 3\n\n"
                "أدخل كمية TON وسيحسب البوت عدد النجوم التقريبي حسب تقدير أندرويد وFragment.",
                chat_id
            )
        elif command == "/stars":
            if len(parts) != 2:
                send("اكتب الكمية بهذا الشكل: /stars 3", chat_id)
                continue
            amount = number(parts[1])
            if amount is None or amount <= 0 or amount > 1_000_000:
                send("⚠️ أدخل كمية TON صحيحة أكبر من صفر.", chat_id)
                continue
            data = market_data()
            if data["price"] is None:
                send("⚠️ تعذر جلب سعر TON المباشر حالياً. جرّب لاحقاً.", chat_id)
                continue
            usd_value = amount * data["price"]
            # Indicative assumptions only; actual Android price varies by region/store.
            android_per_star = number(os.environ.get("ANDROID_STAR_USD", "0.02")) or 0.02
            fragment_per_star = number(os.environ.get("FRAGMENT_STAR_USD", "0.015")) or 0.015
            android_stars = usd_value / android_per_star
            fragment_stars = usd_value / fragment_per_star
            send(
                f"⭐ حاسبة TON إلى Telegram Stars\n\n"
                f"كمية TON: {amount:g} TON\n"
                f"سعر TON المباشر: ${data['price']:.4f}\n"
                f"القيمة التقريبية: ${usd_value:.2f}\n\n"
                f"📱 أندرويد: نحو {android_stars:,.0f} نجمة (تقديري، ${android_per_star:.3f}/نجمة)\n"
                f"💎 Fragment: نحو {fragment_stars:,.0f} نجمة (تقديري، ${fragment_per_star:.3f}/نجمة)\n\n"
                "⚠️ أسعار النجوم تختلف حسب البلد والمنصة والضرائب. هذه مقارنة تقديرية وليست سعر شراء مضمون.",
                chat_id
            )
        elif is_admin and command == "/price":
            data = market_data()
            rate = fx_rate()
            if data["price"] is not None:
                send(build_post(data, rate, None), chat_id, with_keyboard=True)
            else:
                send("⚠️ تعذر جلب السعر؛ لم يتم إرسال رقم غير مؤكد.", chat_id)
        elif is_admin and command == "/status":
            send("✅ البوت يعمل عبر GitHub Actions. التفاعل قد يتأخر حتى 10 دقائق.", chat_id)
        elif is_admin and command == "/test":
            send("✅ اختبار الإرسال ناجح.", chat_id)

    save_state(state)


def main():
    state = load_state()
    data = market_data()

    if data["price"] is None:
        raise RuntimeError("تعذر جلب السعر؛ لن يتم نشر سعر غير مؤكد.")

    rate = fx_rate()
    previous = number(state.get("last_price"))
    message = build_post(data, rate, previous)

    try:
        admin_commands(state)
    except Exception as exc:
        print("Admin commands skipped:", exc, file=sys.stderr)

    fingerprint = {
        key: round(data[key], 7) if data[key] is not None else None
        for key in ("price", "change", "high", "low")
    }

    if state.get("fingerprint") != fingerprint:
        send(message, with_keyboard=True)
        state["fingerprint"] = fingerprint
    else:
        print("No market change; duplicate post skipped.")

    # Optional price-threshold alert; configure ALERT_USD in GitHub Variables.
    if ALERT_USD:
        threshold = number(ALERT_USD)
        if threshold and threshold > 0:
            side = "above" if data["price"] >= threshold else "below"
            old_side = state.get("alert_side")
            if old_side is not None and old_side != side:
                status = "تجاوز الحد للأعلى" if side == "above" else "هبط دون الحد"
                send(
                    "🔔 تنبيه TON\n"
                    f"السعر الحالي: ${data['price']:.4f}\n"
                    f"الحد المحدد: ${threshold:.4f}\n"
                    f"الحالة: {status}"
                )
            state["alert_side"] = side

    # Daily summary disabled: avoid publishing a second, duplicate-looking post.

    state["last_price"] = data["price"]
    state["last_run"] = datetime.now(BAGHDAD).isoformat()
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
