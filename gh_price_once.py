
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TON Telegram channel publisher: change-based updates, chart, analysis, daily report."""
import io
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
CHAT_ID = os.getenv("CHAT_ID", "@Gram_Price_Today").strip()
ADMIN_IDS = {x.strip() for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
POLL_SECONDS = max(30, int(os.getenv("POLL_SECONDS", "60")))
STATE_FILE = os.getenv("STATE_FILE", "ton_state.json")
BAGHDAD = timezone(timedelta(hours=3))

BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/24hr?symbol=TONUSDT"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines?symbol=TONUSDT&interval=1h&limit=48"
COINGECKO_SIMPLE = "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd&include_24hr_change=true"
COINGECKO_CHART = "https://api.coingecko.com/api/v3/coins/the-open-network/market_chart?vs_currency=usd&days=1&interval=hourly"
FX_API = "https://open.er-api.com/v6/latest/USD"

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ton-bot")


def get_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "TONChannelBot/3.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def telegram(method, payload, timeout=20):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram API error"))
    return result.get("result")


def send_text(message, chat_id=None):
    return telegram("sendMessage", {
        "chat_id": chat_id or CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true",
    })


def send_photo(photo_bytes, caption, chat_id=None):
    boundary = "----TONBotBoundary7MA4YWxkTrZu0gW"
    fields = {
        "chat_id": str(chat_id or CHAT_ID),
        "caption": caption,
    }
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="photo"; filename="ton_chart.png"\r\n')
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(photo_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram photo error"))
    return result.get("result")


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def fetch_market():
    data = {"price": None, "change": None, "high": None, "low": None, "prices": [], "times": []}
    try:
        t = get_json(BINANCE_TICKER)
        data.update(
            price=num(t.get("lastPrice")),
            change=num(t.get("priceChangePercent")),
            high=num(t.get("highPrice")),
            low=num(t.get("lowPrice")),
        )
    except Exception as exc:
        log.warning("Binance ticker unavailable: %s", exc)

    if data["price"] is None:
        try:
            item = get_json(COINGECKO_SIMPLE)["the-open-network"]
            data["price"] = num(item.get("usd"))
            data["change"] = num(item.get("usd_24h_change"))
        except Exception as exc:
            log.warning("CoinGecko price unavailable: %s", exc)

    try:
        klines = get_json(BINANCE_KLINES)
        closes, times = [], []
        for row in klines:
            if len(row) >= 5:
                close = num(row[4])
                if close is not None:
                    closes.append(close)
                    times.append(datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).astimezone(BAGHDAD))
        if closes:
            data["prices"], data["times"] = closes, times
            if data["high"] is None:
                data["high"] = max(closes)
            if data["low"] is None:
                data["low"] = min(closes)
    except Exception as exc:
        log.warning("Binance chart data unavailable: %s", exc)

    if len(data["prices"]) < 2:
        try:
            chart = get_json(COINGECKO_CHART)
            rows = chart.get("prices", [])
            prices, times = [], []
            for stamp, value in rows:
                price = num(value)
                if price is not None:
                    prices.append(price)
                    times.append(datetime.fromtimestamp(stamp / 1000, tz=timezone.utc).astimezone(BAGHDAD))
            if prices:
                data["prices"], data["times"] = prices, times
                if data["high"] is None:
                    data["high"] = max(prices)
                if data["low"] is None:
                    data["low"] = min(prices)
        except Exception as exc:
            log.warning("CoinGecko chart unavailable: %s", exc)

    if data["price"] is None:
        raise RuntimeError("Could not retrieve TON price from available price services.")
    return data


def fetch_iqd_rate():
    try:
        rate = num(get_json(FX_API).get("rates", {}).get("IQD"))
        return rate if rate and rate > 0 else None
    except Exception as exc:
        log.warning("USD/IQD exchange rate unavailable: %s", exc)
        return None


def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0) for x in changes[-period:]]
    losses = [abs(min(x, 0)) for x in changes[-period:]]
    avg_gain, avg_loss = sum(gains) / period, sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analysis_text(data):
    prices = data["prices"]
    if len(prices) < 15:
        return "📊 التحليل الفني: بيانات غير كافية حالياً"
    current = prices[-1]
    sma7 = sum(prices[-7:]) / 7
    sma14 = sum(prices[-14:]) / 14
    value_rsi = rsi(prices, 14)
    if current > sma7 > sma14:
        trend = "🟢 اتجاه صاعد قصير الأجل"
    elif current < sma7 < sma14:
        trend = "🔴 اتجاه هابط قصير الأجل"
    else:
        trend = "🟡 اتجاه متذبذب أو غير واضح"
    if value_rsi is None:
        rsi_line = "RSI: غير متوفر"
    else:
        label = "منطقة تشبع شرائي محتملة" if value_rsi >= 70 else "منطقة تشبع بيعي محتملة" if value_rsi <= 30 else "ضمن النطاق المعتاد"
        rsi_line = f"RSI(14): {value_rsi:.1f} — {label}"
    return f"📊 التحليل الفني\n{trend}\n{rsi_line}\n📌 تحليل آلي مبسّط، وليس توصية استثمارية."


def make_chart(data):
    prices, times = data["prices"], data["times"]
    if len(prices) < 2 or len(times) != len(prices):
        return None
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(times, prices, linewidth=2)
    ax.set_title("TON / USDT — Last 24-48 hours")
    ax.set_xlabel("Baghdad time")
    ax.set_ylabel("Price (USDT)")
    ax.grid(True, alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=BAGHDAD))
    fig.autofmt_xdate()
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=140)
    plt.close(fig)
    return buffer.getvalue()


def build_post(data, rate, previous):
    now = datetime.now(BAGHDAD)
    price = data["price"]
    iqd = f"{price * rate:,.0f} د.ع" if rate is not None else "غير متوفر حالياً"
    high = f"${data['high']:.4f}" if data["high"] is not None else "غير متوفر"
    low = f"${data['low']:.4f}" if data["low"] is not None else "غير متوفر"
    if previous is None:
        diff = "بانتظار التحديث القادم"
    else:
        delta = price - previous
        emoji = "🟢" if delta > 0 else "🔴" if delta < 0 else "⚪"
        diff = f"{emoji} {delta:+.4f} USD"
    return (
        "💎┏━━━━━━━━━━━━━━━━━━━━┓\n"
        "      TON  |  LIVE MARKET\n"
        "┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        "💵 السعر بالدولار\n"
        f"　➜ `${price:.4f} USDT`\n\n"
        "🇮🇶 السعر بالدينار العراقي\n"
        f"　➜ `{iqd}`\n\n"
        "📊 إحصائيات السوق\n"
        f"　📈 تغيّر 24 ساعة: `{format_change(data['change'])}`\n"
        f"　🔺 أعلى سعر: `{high}`\n"
        f"　🔻 أقل سعر: `{low}`\n\n"
        "📉 مقارنة بالتحديث السابق\n"
        f"　➜ `{diff}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🕒 آخر تحديث: `{now.strftime('%I:%M:%S %p')}`\n"
        f"📅 التاريخ: `{now.strftime('%d-%m-%Y')}`\n\n"
        "⚠️ الأسعار متغيرة باستمرار وقد تختلف بين المنصات. تحقق قبل التداول.\n\n"
        "💎 @Gram_Price_Today"
    )


def format_change(value):
    if value is None:
        return "غير متوفر حالياً"
    if value > 0:
        return f"🟢 ▲ {value:+.2f}%"
    if value < 0:
        return f"🔴 ▼ {value:+.2f}%"
    return f"⚪ {value:+.2f}%"


def publish_market_update(data, rate, state):
    previous = num(state.get("last_price"))
    post = build_post(data, rate, previous)
    send_text(post)
    chart = make_chart(data)
    if chart:
        send_photo(chart, "📉 حركة سعر TON — الرسم البياني للفترة المتاحة")
    send_text(analysis_text(data))
    state["last_price"] = data["price"]


def daily_report(data, rate):
    now = datetime.now(BAGHDAD)
    iqd = f"{data['price'] * rate:,.0f} د.ع" if rate is not None else "غير متوفر حالياً"
    high = f"${data['high']:.4f}" if data["high"] is not None else "غير متوفر"
    low = f"${data['low']:.4f}" if data["low"] is not None else "غير متوفر"
    return (
        "📅┏━━━━━━━━━━━━━━━━━━━━┓\n"
        "       TON • التقرير اليومي\n"
        "┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"💵 السعر الحالي: ${data['price']:.4f} USDT\n"
        f"🇮🇶 بالدينار العراقي: {iqd}\n"
        f"📈 تغيّر 24 ساعة: {format_change(data['change'])}\n"
        f"🔺 أعلى سعر 24 ساعة: {high}\n"
        f"🔻 أقل سعر 24 ساعة: {low}\n\n"
        f"{analysis_text(data)}\n\n"
        f"🕒 {now.strftime('%I:%M %p')} — توقيت بغداد\n"
        "⚠️ معلومات عامة وليست توصية استثمارية.\n"
        "💎 @Gram_Price_Today"
    )


def handle_updates(state):
    offset = int(state.get("update_offset", 0))
    updates = telegram("getUpdates", {
        "offset": offset + 1,
        "timeout": 1,
        "allowed_updates": json.dumps(["message"]),
    }, timeout=5) or []
    for update in updates:
        state["update_offset"] = max(int(state.get("update_offset", 0)), int(update.get("update_id", 0)))
        msg = update.get("message") or {}
        sender_id = str((msg.get("from") or {}).get("id", ""))
        if sender_id not in ADMIN_IDS:
            continue
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        command_parts = (msg.get("text") or "").split()
        command = command_parts[0].lower().split("@")[0] if command_parts else ""
        if command == "/price":
            try:
                data = fetch_market()
                send_text(build_post(data, fetch_iqd_rate(), state.get("last_price")), chat_id)
            except Exception as exc:
                send_text(f"تعذر جلب السعر حالياً: {exc}", chat_id)
        elif command == "/analysis":
            try:
                send_text(analysis_text(fetch_market()), chat_id)
            except Exception as exc:
                send_text(f"تعذر إعداد التحليل حالياً: {exc}", chat_id)
        elif command == "/chart":
            try:
                chart = make_chart(fetch_market())
                if chart:
                    send_photo(chart, "📉 حركة سعر TON", chat_id)
                else:
                    send_text("بيانات الرسم البياني غير متوفرة حالياً.", chat_id)
            except Exception as exc:
                send_text(f"تعذر إعداد الرسم البياني: {exc}", chat_id)
        elif command == "/daily":
            try:
                data = fetch_market()
                send_text(daily_report(data, fetch_iqd_rate()), chat_id)
            except Exception as exc:
                send_text(f"تعذر إعداد التقرير حالياً: {exc}", chat_id)
        elif command == "/status":
            send_text("✅ بوت TON يعمل بنظام 24/7 عبر polling.", chat_id)
    save_state(state)


def run_cycle(state):
    try:
        handle_updates(state)
    except Exception as exc:
        log.warning("Telegram polling failed: %s", exc)

    data = fetch_market()
    rate = fetch_iqd_rate()
    fingerprint = {
        key: round(data.get(key), 7) if data.get(key) is not None else None
        for key in ("price", "change", "high", "low")
    }
    if fingerprint != state.get("fingerprint"):
        publish_market_update(data, rate, state)
        state["fingerprint"] = fingerprint
        state["last_market_update"] = datetime.now(BAGHDAD).isoformat()
    else:
        log.info("Market data unchanged; skipping channel post.")

    today = datetime.now(BAGHDAD).date().isoformat()
    if state.get("daily_report_date") != today:
        send_text(daily_report(data, rate))
        state["daily_report_date"] = today
    save_state(state)


def main():
    state = load_state()
    if os.getenv("RUN_ONCE", "0").lower() in {"1", "true", "yes"}:
        log.info("Running one GitHub Actions cycle.")
        run_cycle(state)
        return

    log.info("Starting continuous TON bot; polling every %s seconds", POLL_SECONDS)
    while True:
        try:
            run_cycle(state)
        except Exception as exc:
            log.exception("Market cycle failed: %s", exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
