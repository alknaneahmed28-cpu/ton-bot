
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ.get("CHAT_ID", "@Gram_Price_Today")
BAGHDAD = timezone(timedelta(hours=3))


def get_json(url, data=None):
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "TON-Price-Bot/1.0"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def get_price():
    try:
        data = get_json(
            "https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT"
        )
        return float(data["price"])
    except Exception as e:
        print("Binance error:", e)

    data = get_json(
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=the-open-network&vs_currencies=usd"
    )
    return float(data["the-open-network"]["usd"])


def get_iqd_rate():
    try:
        data = get_json("https://open.er-api.com/v6/latest/USD")
        if data.get("result") == "success":
            return float(data["rates"]["IQD"])
    except Exception as e:
        print("Exchange rate error:", e)

    return 1310.0


def get_change_24h():
    try:
        data = get_json(
            "https://api.binance.com/api/v3/ticker/24hr?symbol=TONUSDT"
        )
        return float(data["priceChangePercent"])
    except Exception as e:
        print("24h change error:", e)
        return None


def send_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true"
    }).encode("utf-8")

    result = get_json(url, data=payload)

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")

    print("Message sent:", result["result"]["message_id"])


def main():
    price = get_price()
    rate = get_iqd_rate()
    change = get_change_24h()
    now = datetime.now(BAGHDAD).strftime("%Y-%m-%d | %I:%M:%S %p")

    change_text = (
        f"{change:+.2f}%"
        if change is not None else "غير متوفر"
    )

    message = (
        "💎 TON | تحديث السعر\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💵 السعر بالدولار: ${price:.4f}\n"
        f"🇮🇶 السعر بالدينار العراقي: {price * rate:,.0f} د.ع\n"
        f"📊 التغير خلال 24 ساعة: {change_text}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🕒 آخر تحديث: {now}\n"
        "📡 المصدر: Binance / CoinGecko\n"
        "⚠️ الأسعار تقريبية وقد تتغير."
    )

    # يرسل رسالة في كل تشغيل، دون مقارنة السعر السابق
    send_message(message)


if __name__ == "__main__":
    main()
