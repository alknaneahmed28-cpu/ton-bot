#!/usr/bin/env python3
"""TON price publisher for GitHub Actions: one update per run."""
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
CHAT_ID = os.getenv("CHAT_ID", "@Gram_Price_Today").strip()
ADMIN_IDS = {
    x.strip() for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
}
STATE_FILE = os.getenv("STATE_FILE", "ton_state.json")
BAGHDAD = timezone(timedelta(hours=3))

STARS_USD_REWARD = 0.013
ALERT_PERCENT = 3.0

BINANCE_TICKER = (
    "https://api.binance.com/api/v3/ticker/24hr?symbol=TONUSDT"
)
COINGECKO_SIMPLE = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=the-open-network&vs_currencies=usd"
    "&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true"
)
COINGECKO_MARKET = (
    "https://api.coingecko.com/api/v3/coins/the-open-network"
    "?localization=false&tickers=false&market_data=true"
    "&community_data=false&developer_data=false"
)
FX_API = "https://open.er-api.com/v6/latest/USD"

CHANNEL_URL = "https://t.me/Gram_Price_Today"
SHARE_URL = (
    "https://t.me/share/url?"
    "url=https%3A%2F%2Ft.me%2FGram_Price_Today"
    "&text=%D8%AA%D8%A7%D8%A8%D8%B9%20%D8%A3%D8%B3%D8%B9%D8%A7%D8%B1"
    "%20TON%20%D9%85%D8%B9%20%D9%82%D9%86%D8%A7%D8%A9%20"
    "Gram%20Price%20Today"
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("ton-bot")


def get_json(url, timeout=15):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TONChannelBot/5.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def telegram(method, payload, timeout=20):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")

    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram API error"))

    return result.get("result")


def send_text(message, chat_id=None, reply_markup=None):
    payload = {
        "chat_id": chat_id or CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(
            reply_markup, ensure_ascii=False
        )
    return telegram("sendMessage", payload)


def channel_keyboard():
    # Stars button removed; keep only share and subscribe.
    return {
        "inline_keyboard": [
            [
                {"text": "📤 مشاركة القناة", "url": SHARE_URL},
                {"text": "📢 الاشتراك بالقناة", "url": CHANNEL_URL},
            ]
        ]
    }


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    temporary = STATE_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False)
    os.replace(temporary, STATE_FILE)


def fetch_market():
    data = {
        "price": None,
        "change": None,
        "high": None,
        "low": None,
        "market_cap": None,
        "volume": None,
    }

    # Try Binance first. HTTP 451 and other errors fall back to CoinGecko.
    try:
        ticker = get_json(BINANCE_TICKER)
        data.update(
            price=num(ticker.get("lastPrice")),
            change=num(ticker.get("priceChangePercent")),
            high=num(ticker.get("highPrice")),
            low=num(ticker.get("lowPrice")),
        )
        log.info("Price source: Binance")
    except Exception as exc:
        log.warning("Binance unavailable; trying CoinGecko: %s", exc)

    # CoinGecko simple endpoint is the main fallback.
    if data["price"] is None:
        try:
            coin = get_json(COINGECKO_SIMPLE)["the-open-network"]
            data.update(
                price=num(coin.get("usd")),
                change=num(coin.get("usd_24h_change")),
                market_cap=num(coin.get("usd_market_cap")),
                volume=num(coin.get("usd_24h_vol")),
            )
            log.info("Price source: CoinGecko simple")
        except Exception as exc:
            log.warning("CoinGecko simple unavailable: %s", exc)

    # If price is available but high/low or market data is missing,
    # attempt to fill in the missing values from CoinGecko market data.
    if (
        data["price"] is not None
        and (
            data["high"] is None
            or data["low"] is None
            or data["market_cap"] is None
            or data["volume"] is None
        )
    ):
        try:
            market = get_json(COINGECKO_MARKET).get("market_data", {})
            usd = market.get("current_price", {}).get("usd")
            high = num(market.get("high_24h", {}).get("usd"))
            low = num(market.get("low_24h", {}).get("usd"))

            if data["high"] is None:
                data["high"] = high
            if data["low"] is None:
                data["low"] = low
            if data["market_cap"] is None:
                data["market_cap"] = num(
                    market.get("market_cap", {}).get("usd")
                )
            if data["volume"] is None:
                data["volume"] = num(
                    market.get("total_volume", {}).get("usd")
                )
            if data["change"] is None:
                data["change"] = num(
                    market.get("price_change_percentage_24h")
                )
            if data["price"] is None:
                data["price"] = num(usd)
        except Exception as exc:
            log.warning("CoinGecko market data unavailable: %s", exc)

    if data["price"] is None:
        raise RuntimeError(
            "تعذر جلب سعر TON من Binance وCoinGecko؛ لم يتم نشر سعر غير مؤكد."
        )

    return data


def fetch_iqd_rate(state):
    override = num(state.get("iqd_rate_override"))
    if override and override > 0:
        return override

    try:
        rate = num(get_json(FX_API).get("rates", {}).get("IQD"))
        return rate if rate and rate > 0 else None
    except Exception as exc:
        log.warning("USD/IQD exchange rate unavailable: %s", exc)
        return None


def format_change(value):
    if value is None:
        return "غير متوفر"
    if value > 0:
        return f"🟢 ▲ {value:+.2f}%"
    if value < 0:
        return f"🔴 ▼ {value:+.2f}%"
    return f"⚪ {value:+.2f}%"


def build_post(data, rate, previous):
    now = datetime.now(BAGHDAD)
    price = data["price"]

    iqd = (
        f"{price * rate:,.0f} د.ع"
        if rate is not None
        else "غير متوفر حالياً"
    )
    high = (
        f"${data['high']:.4f}"
        if data["high"] is not None else "غير متوفر"
    )
    low = (
        f"${data['low']:.4f}"
        if data["low"] is not None else "غير متوفر"
    )
    market_cap = (
        f"${data['market_cap'] / 1e9:.2f}B"
        if data.get("market_cap") is not None else "غير متوفر"
    )
    volume = (
        f"${data['volume'] / 1e6:.2f}M"
        if data.get("volume") is not None else "غير متوفر"
    )

    if previous is None or not previous:
        delta = "بانتظار التحديث القادم"
    else:
        delta = f"{((price - previous) / previous * 100):+.2f}%"

    return (
        "💎 𓆩 TON PRICE 𓆪 💎\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🚀 سعر تون الحالي بعد التحديث\n\n"
        f"💵 TON / USD\n➜ ${price:.4f}\n\n"
        f"🇮🇶 السعر بالدينار العراقي\n➜ {iqd}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 تغيّرات السوق | 24H\n\n"
        f"📈 نسبة التغيّر: {format_change(data['change'])}\n"
        f"🟢 أعلى سعر: {high}\n"
        f"🔻 أقل سعر: {low}\n"
        f"📉 مقارنة بالتحديث السابق: {delta}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 القيمة السوقية: {market_cap}\n"
        f"🔄 حجم التداول: {volume}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🕒 آخر تحديث: {now.strftime('%I:%M %p')} | توقيت بغداد\n"
        f"📅 {now.strftime('%d-%m-%Y')}\n\n"
        "⚠️ الأسعار قابلة للتغيّر في أي وقت.\n\n"
        "💎 TON • PRICE UPDATE"
    )


def check_strong_movement(data, state, now_ts):
    history = state.get("price_history", [])
    history = [
        item for item in history
        if now_ts - float(item.get("t", 0)) <= 3 * 3600
    ]

    eligible = [
        item for item in history
        if now_ts - float(item.get("t", 0)) >= 55 * 60
    ]
    reference = (
        max(eligible, key=lambda item: float(item.get("t", 0)))
        if eligible else None
    )

    if reference and reference.get("p"):
        pct = (data["price"] / float(reference["p"]) - 1) * 100
        last_alert = float(state.get("last_strong_alert_ts", 0) or 0)

        if (
            abs(pct) >= ALERT_PERCENT
            and now_ts - last_alert >= 55 * 60
        ):
            direction = "🚀 صعود قوي" if pct > 0 else "🚨 هبوط قوي"
            message = (
                f"{direction} في سعر TON!\n\n"
                f"⚡ التغيّر خلال نحو ساعة: {pct:+.2f}%\n"
                f"💵 السعر الحالي: ${data['price']:.4f}\n"
                f"🕒 {datetime.now(BAGHDAD).strftime('%I:%M %p')} — توقيت بغداد\n\n"
                "⚠️ تنبيه آلي لحركة السوق، وليس توصية مالية."
            )
            send_text(message, reply_markup=channel_keyboard())
            state["last_strong_alert_ts"] = now_ts

    history.append({"t": now_ts, "p": data["price"]})
    state["price_history"] = history[-30:]


def stars_message(count, price, rate):
    usd = count * STARS_USD_REWARD
    ton = usd / price if price else 0
    iqd = usd * rate if rate else None
    iqd_text = f"{iqd:,.0f} د.ع" if iqd is not None else "غير متوفر حالياً"

    return (
        "⭐ حاسبة Telegram Stars\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⭐ عدد النجوم: {count:,}\n"
        f"💵 قيمة المكافأة التقديرية: ${usd:,.2f}\n"
        f"🇮🇶 بالدينار العراقي: {iqd_text}\n"
        f"💎 ما يعادل TON تقريباً: {ton:.4f} TON\n\n"
        "ℹ️ الحساب على أساس 0.013$ لكل نجمة كقيمة مكافأة للمطوّر، "
        "وليس سعر الشراء. قد تختلف القيمة الفعلية والرسوم."
    )


def handle_updates(state):
    offset = int(state.get("update_offset", 0))
    updates = telegram(
        "getUpdates",
        {
            "offset": offset + 1,
            "timeout": 0,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        },
        timeout=5,
    ) or []

    for update in updates:
        state["update_offset"] = max(
            int(state.get("update_offset", 0)),
            int(update.get("update_id", 0)),
        )

        # Ignore old Stars-button callbacks; the button is no longer displayed.
        if update.get("callback_query"):
            query = update["callback_query"]
            if query.get("data") == "stars_calc":
                telegram(
                    "answerCallbackQuery",
                    {
                        "callback_query_id": query["id"],
                        "text": "أرسل /stars 1000 لحساب النجوم.",
                        "show_alert": "true",
                    },
                )
            continue

        msg = update.get("message") or {}
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            continue

        sender_id = str((msg.get("from") or {}).get("id", ""))
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        parts = text.split()
        command = parts[0].lower().split("@")[0]
        args = parts[1:]
        is_admin = sender_id in ADMIN_IDS

        if command == "/start":
            send_text(
                "أهلاً بك في بوت TON.\n"
                "أرسل /stars 1000 لحساب قيمة النجوم.\n"
                f"تابع القناة: {CHANNEL_URL}",
                chat_id,
            )

        elif command == "/stars":
            if (
                not args
                or not args[0].isdigit()
                or int(args[0]) < 1
                or int(args[0]) > 10_000_000
            ):
                send_text("استخدم الأمر هكذا:\n/stars 1000", chat_id)
                continue

            try:
                market = fetch_market()
                rate = fetch_iqd_rate(state)
                send_text(
                    stars_message(int(args[0]), market["price"], rate),
                    chat_id,
                )
            except Exception as exc:
                log.exception("Stars calculation failed")
                send_text(f"تعذر الحساب حالياً: {exc}", chat_id)

        elif command == "/iqd":
            if not is_admin:
                send_text("⛔ هذا الأمر للمشرفين فقط.", chat_id)
                continue

            if not args:
                current = fetch_iqd_rate(state)
                current_text = (
                    f"{current:,.2f} د.ع لكل دولار"
                    if current is not None else "غير متوفر"
                )
                send_text(
                    f"سعر الصرف الحالي: {current_text}\n"
                    "لتغييره: /iqd 1500\n"
                    "للعودة للسعر التلقائي: /iqd auto",
                    chat_id,
                )

            elif args[0].lower() == "auto":
                state.pop("iqd_rate_override", None)
                save_state(state)
                send_text(
                    "✅ تم إلغاء السعر اليدوي والعودة لسعر الصرف التلقائي.",
                    chat_id,
                )

            else:
                new_rate = num(args[0])
                if new_rate is None or not 1 <= new_rate <= 1_000_000:
                    send_text("أدخل سعراً صحيحاً، مثال: /iqd 1500", chat_id)
                else:
                    state["iqd_rate_override"] = new_rate
                    save_state(state)
                    send_text(
                        f"✅ تم تحديث سعر الصرف إلى {new_rate:,.2f} "
                        "دينار لكل دولار.",
                        chat_id,
                    )

        elif command == "/price" and is_admin:
            try:
                data = fetch_market()
                send_text(
                    build_post(
                        data,
                        fetch_iqd_rate(state),
                        num(state.get("last_price")),
                    ),
                    chat_id,
                    channel_keyboard(),
                )
            except Exception as exc:
                log.exception("Manual price command failed")
                send_text(f"تعذر جلب السعر حالياً: {exc}", chat_id)

        elif command == "/status" and is_admin:
            send_text(
                "✅ بوت TON يعمل بنظام تشغيل واحد لكل Workflow.\n"
                "تنبيه الحركة القوية عند ±3% تقريباً خلال ساعة.",
                chat_id,
            )

        elif command in {"/analysis", "/chart", "/daily"} and is_admin:
            send_text(
                "الرسم البياني والتقرير المنفصل متوقفان؛ "
                "بيانات السوق موجودة في رسالة واحدة.",
                chat_id,
            )

    save_state(state)


def run_cycle(state):
    # Handle commands if getUpdates is available. Publishing still proceeds
    # if command polling fails.
    try:
        handle_updates(state)
    except Exception as exc:
        log.warning("Telegram updates failed: %s", exc)

    data = fetch_market()
    rate = fetch_iqd_rate(state)
    now_ts = time.time()

    check_strong_movement(data, state, now_ts)

    fingerprint = {
        key: round(data.get(key), 7) if data.get(key) is not None else None
        for key in (
            "price", "change", "high", "low", "market_cap", "volume"
        )
    }

    # Publish if market data changed OR this is the first run with no
    # stored fingerprint, so an empty state still gets its first post.
    if state.get("fingerprint") != fingerprint:
        send_text(
            build_post(data, rate, num(state.get("last_price"))),
            reply_markup=channel_keyboard(),
        )
        state["last_price"] = data["price"]
        state["fingerprint"] = fingerprint
        state["last_market_update"] = datetime.now(BAGHDAD).isoformat()
        log.info("Channel post sent successfully.")
    else:
        log.info("Market data unchanged; skipping channel post.")

    save_state(state)


def main():
    state = load_state()
    log.info("Starting one-shot TON price update.")
    run_cycle(state)
    log.info("Update completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("TON price update failed.")
        raise
