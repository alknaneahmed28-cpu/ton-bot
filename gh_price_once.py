#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TON Price Bot - Arabic formatted market updates."""

import html
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
    x.strip()
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
}
POLL_SECONDS = max(30, int(os.getenv("POLL_SECONDS", "60")))
STATE_FILE = os.getenv("STATE_FILE", "ton_state.json")
BAGHDAD = timezone(timedelta(hours=3))

BINANCE_TICKER = (
    "https://api.binance.com/api/v3/ticker/24hr?symbol=TONUSDT"
)
COINGECKO_SIMPLE = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=the-open-network&vs_currencies=usd"
    "&include_24hr_change=true"
)
COINGECKO_MARKET = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&ids=the-open-network"
)

FX_API = "https://open.er-api.com/v6/latest/USD"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("ton-bot")


def get_json(url, timeout=15):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TONChannelBot/4.0"},
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
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(
            result.get("description", "Telegram API error")
        )

    return result.get("result")


def send_text(message, chat_id=None):
    return telegram(
        "sendMessage",
        {
            "chat_id": chat_id or CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
    )


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    temp_file = STATE_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False)

    os.replace(temp_file, STATE_FILE)


def fetch_market():
    data = {
        "price": None,
        "change": None,
        "high": None,
        "low": None,
        "volume": None,
        "market_cap": None,
    }

    # Get current price and 24-hour market statistics.
    try:
        ticker = get_json(BINANCE_TICKER)

        data.update({
            "price": num(ticker.get("lastPrice")),
            "change": num(ticker.get("priceChangePercent")),
            "high": num(ticker.get("highPrice")),
            "low": num(ticker.get("lowPrice")),
            "volume": num(ticker.get("quoteVolume")),
        })

    except Exception as exc:
        log.warning("Binance data unavailable: %s", exc)

    # Fallback for price and daily change.
    if data["price"] is None:
        try:
            item = get_json(COINGECKO_SIMPLE)["the-open-network"]
            data["price"] = num(item.get("usd"))
            data["change"] = num(item.get("usd_24h_change"))
        except Exception as exc:
            log.warning("CoinGecko price unavailable: %s", exc)

    # Retrieve market cap and other market data.
    try:
        markets = get_json(COINGECKO_MARKET)

        if markets:
            item = markets[0]

            if data["price"] is None:
                data["price"] = num(item.get("current_price"))

            if data["change"] is None:
                data["change"] = num(
                    item.get("price_change_percentage_24h")
                )

            if data["high"] is None:
                data["high"] = num(item.get("high_24h"))

            if data["low"] is None:
                data["low"] = num(item.get("low_24h"))

            if data["market_cap"] is None:
                data["market_cap"] = num(item.get("market_cap"))

            if data["volume"] is None:
                data["volume"] = num(item.get("total_volume"))

    except Exception as exc:
        log.warning("Market details unavailable: %s", exc)

    if data["price"] is None:
        raise RuntimeError(
            "Could not retrieve TON price. Try again later."
        )

    return data


def fetch_iqd_rate():
    try:
        response = get_json(FX_API)
        rate = num(response.get("rates", {}).get("IQD"))

        if rate and rate > 0:
            return rate

    except Exception as exc:
        log.warning("USD/IQD rate unavailable: %s", exc)

    return None


def format_money(value, decimals=4):
    if value is None:
        return "غير متوفر حالياً"

    return f"${value:,.{decimals}f}"


def format_large_money(value):
    if value is None:
        return "غير متوفر حالياً"

    absolute = abs(value)

    if absolute >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"

    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"

    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"

    return f"${value:,.2f}"


def format_change(value):
    if value is None:
        return "غير متوفر حالياً"

    if value > 0:
        return f"🟢 ▲ {value:+.2f}%"

    if value < 0:
        return f"🔴 ▼ {value:+.2f}%"

    return f"⚪ {value:+.2f}%"


def build_post(data, rate, previous=None):
    now = datetime.now(BAGHDAD)
    price = data["price"]

    if rate is not None:
        iqd = f"{price * rate:,.0f} د.ع"
    else:
        iqd = "غير متوفر حالياً"

    high = format_money(data.get("high"))
    low = format_money(data.get("low"))
    market_cap = format_large_money(data.get("market_cap"))
    volume = format_large_money(data.get("volume"))
    change = format_change(data.get("change"))

    # Escape dynamic values before inserting them into HTML.
    price_text = html.escape(format_money(price))
    iqd_text = html.escape(iqd)
    high_text = html.escape(high)
    low_text = html.escape(low)
    market_cap_text = html.escape(market_cap)
    volume_text = html.escape(volume)
    change_text = html.escape(change)

    timestamp = now.strftime("%I:%M %p")
    date_text = now.strftime("%d-%m-%Y")

    return (
        "💎 𓆩 <b>TON PRICE</b> 𓆪 💎\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🚀 <b>سـعـر تـون الـحـالـي بـعـد الـتـحـديـث</b>\n\n"

        "💵 <b>TON / USD</b>\n"
        f"➜ <b>{price_text}</b>\n\n"

        "🇮🇶 <b>السـعـر بـالـديـنـار الـعـراقـي</b>\n"
        f"➜ <b>{iqd_text}</b>\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>تـغـيّـرات الـسـوق | 24H</b>\n\n"

        f"📈 نسبة التغيّر: {change_text}\n"
        f"🟢 أعلى سعر: <code>{high_text}</code>\n"
        f"🔻 أقل سعر: <code>{low_text}</code>\n\n"

        "━━━━━━━━━━━━━━━━━━\n\n"

        f"💰 القيمة السوقية: <b>{market_cap_text}</b>\n"
        f"🔄 حجم التداول: <b>{volume_text}</b>\n\n"

        "━━━━━━━━━━━━━━━━━━\n\n"

        "🕒 <b>آخـر تـحـديـث</b>\n"
        f"⏱ <code>{timestamp} | توقيت بغداد</code>\n"
        f"📅 <code>{date_text}</code>\n\n"

        "⚠️ <i>الأسعار قابلة للتغيّر في أي وقت.</i>\n\n"

        "💎 <b>TON • PRICE UPDATE</b>"
    )


def publish_market_update(data, rate, state):
    post = build_post(data, rate)
    send_text(post)

    state["last_price"] = data["price"]
    log.info("Published TON market update: %s", data["price"])


def handle_updates(state):
    offset = int(state.get("update_offset", 0))

    updates = telegram(
        "getUpdates",
        {
            "offset": offset + 1,
            "timeout": 1,
            "allowed_updates": json.dumps(["message"]),
        },
        timeout=5,
    ) or []

    for update in updates:
        state["update_offset"] = max(
            int(state.get("update_offset", 0)),
            int(update.get("update_id", 0)),
        )

        message = update.get("message") or {}
        sender_id = str((message.get("from") or {}).get("id", ""))

        if sender_id not in ADMIN_IDS:
            continue

        chat_id = str((message.get("chat") or {}).get("id", ""))
        parts = (message.get("text") or "").split()
        command = parts[0].lower().split("@")[0] if parts else ""

        if command in ("/price", "/daily"):
            try:
                data = fetch_market()
                rate = fetch_iqd_rate()
                send_text(build_post(data, rate), chat_id)
            except Exception as exc:
                log.warning("Price command failed: %s", exc)
                send_text(
                    "تعذر جلب السعر حالياً. حاول مرة أخرى لاحقاً.",
                    chat_id,
                )

        elif command == "/status":
            send_text(
                "✅ بوت TON يعمل.\n"
                "📡 تحديث الأسعار تلقائي.\n"
                "💎 القناة: @Gram_Price_Today",
                chat_id,
            )

    save_state(state)


def run_cycle(state):
    try:
        handle_updates(state)
    except Exception as exc:
        log.warning("Telegram polling failed: %s", exc)

    data = fetch_market()
    rate = fetch_iqd_rate()

    fingerprint = {
        key: round(data.get(key), 7)
        if data.get(key) is not None else None
        for key in (
            "price",
            "change",
            "high",
            "low",
            "volume",
            "market_cap",
        )
    }

    if fingerprint != state.get("fingerprint"):
        publish_market_update(data, rate, state)
        state["fingerprint"] = fingerprint
        state["last_market_update"] = (
            datetime.now(BAGHDAD).isoformat()
        )
    else:
        log.info("Market data unchanged; skipping channel post.")

    save_state(state)


def main():
    state = load_state()

    # GitHub Actions: perform one cycle and exit.
    if os.getenv("RUN_ONCE", "0").lower() in {
        "1", "true", "yes"
    }:
        log.info("Running one GitHub Actions cycle.")
        run_cycle(state)
        return

    log.info(
        "Starting TON bot. Polling every %s seconds.",
        POLL_SECONDS,
    )

    while True:
        try:
            run_cycle(state)
        except Exception:
            log.exception("Market update failed")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
