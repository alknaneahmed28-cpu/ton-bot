# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""TON Telegram channel publisher: one combined text-only market update."""
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


def send_text(message, chat_id=None, reply_markup=None):
    target = chat_id or CHAT_ID
    log.info("Sending Telegram message to %s", target)
    payload = {
        "chat_id": target,
        "text": message,
        "disable_web_page_preview": "true",
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    result = telegram("sendMessage", payload)
    log.info("Telegram message sent successfully to %s (message_id=%s)", target, (result or {}).get("message_id"))
    return result


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
    override = num(os.getenv("IQD_RATE_OVERRIDE"))
    if override and override > 0:
        return override
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

def build_post(data, rate, previous):
    now = datetime.now(BAGHDAD)

    price = data["price"]
    iqd = f"{price * rate:,.0f} د.ع" if rate is not None else "غير متوفر"
    high = f"${data['high']:.4f}" if data["high"] is not None else "غير متوفر"
    low = f"${data['low']:.4f}" if data["low"] is not None else "غير متوفر"

    if previous is None:
        diff = "بانتظار التحديث القادم"
    else:
        delta = price - previous
        diff = f"{delta:+.4f} USD"

    if len(data["prices"]) >= 15:
        prices = data["prices"]
        current = prices[-1]
        sma7 = sum(prices[-7:]) / 7
        sma14 = sum(prices[-14:]) / 14

        if current < sma7 < sma14:
            trend = "🔴 اتجاه هابط قصير الأجل"
        elif current > sma7 > sma14:
            trend = "🟢 اتجاه صاعد قصير الأجل"
        else:
            trend = "🟡 اتجاه متذبذب أو غير واضح"

        value_rsi = rsi(prices, 14)
        rsi_value = f"{value_rsi:.1f}" if value_rsi is not None else "غير متوفر"
    else:
        trend = "بيانات غير كافية حالياً"
        rsi_value = "غير متوفر"

    if rate is not None:
        calc_1 = f"{price * rate:,.0f}"
        calc_10 = f"{price * rate * 10:,.0f}"
        calc_100 = f"{price * rate * 100:,.0f}"
    else:
        calc_1 = calc_10 = calc_100 = "غير متوفر"

    return (
        "┏━━━━━━━━━━━━━━━━━━━┓\n"
        "💎 سوق TON المباشر | LIVE\n"
        "┗━━━━━━━━━━━━━━━━━━━┛\n"
        "💵 الأسعار\n"
        f"• USDT: ${price:.4f}\n"
        f"• IQD: {iqd}\n"
        "📊 تفاصيل الـ 24 ساعة\n"
        f"🔻 التغير: {format_change(data['change'])}\n"
        f"🔝 أعلى قمة: {high}\n"
        f"🔻 أدنى قاع: {low}\n"
        f"✳️ التحديث: {diff}\n"
        "⚙️ التحليل الفني\n"
        f"• المسار: {trend}\n"
        f"• RSI (14): {rsi_value}\n"
        "🖩 التحويل السريع\n"
        f"▫️ 1 TON  ➔ {calc_1} د.ع\n"
        f"▫️ 10 TON ➔ {calc_10} د.ع\n"
        f"▫️ 100 TON ➔ {calc_100} د.ع\n"
        "───────────────────\n"
        f"⏰ التحديث: {now.strftime('%I:%M:%S %p')}\n"
        f"📆 التاريخ: {now.strftime('%d-%m-%Y')} — توقيت بغداد\n"
        "🔔 التنبيهات مفعلة عبر إعدادات البوت\n"
        "⚠️ ليست توصية استثمارية\n"
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
    state["last_price"] = data["price"]


def daily_report(data, rate):
    now = datetime.now(BAGHDAD)
    iqd = f"{data['price'] * rate:,.0f} د.ع" if rate is not None else "غير متوفر حالياً"
    high = f"${data['high']:.4f}" if data["high"] is not None else "غير متوفر"
    low = f"${data['low']:.4f}" if data["low"] is not None else "غير متوفر"
    return (
        "📅╔════════════════════╗\n"
        "       TON • التقرير اليومي\n"
        "╚════════════════════╝\n\n"
        f"💵 السعر الحالي: ${data['price']:.4f} USDT\n"
        f"🇮🇶 بالدينار العراقي: {iqd}\n"
        f"📈 تغيّر 24 ساعة: {format_change(data['change'])}\n"
        f"◥ أعلى سعر 24 ساعة: {high}\n"
        f"◢ أقل سعر 24 ساعة: {low}\n\n"
        f"{analysis_text(data)}\n\n"
        f"🕒 {now.strftime('%I:%M %p')} — توقيت بغداد\n"
        "⚠️ معلومات عامة وليست توصية استثمارية.\n"
        "💎 @Gram_Price_Today"
    )


def is_admin(sender_id):
    return str(sender_id) in ADMIN_IDS


def notify_owner_about_addition(chat, actor, state):
    chat_id = str(chat.get("id", ""))
    if not chat_id:
        return
    chat_type = chat.get("type", "unknown")
    chat_title = chat.get("title") or chat.get("username") or "بدون اسم"
    actor_name = "غير معروف"
    actor_id = "غير متوفر"
    if actor:
        actor_id = str(actor.get("id", "غير متوفر"))
        actor_name = " ".join(x for x in [actor.get("first_name"), actor.get("last_name")] if x) or actor.get("username") or actor_id
    state.setdefault("pending_chats", {})[chat_id] = {
        "title": chat_title,
        "type": chat_type,
        "requested_by": actor_id,
        "created_at": datetime.now(BAGHDAD).isoformat(),
    }
    keyboard = {"inline_keyboard": [[
        {"text": "✅ موافقة", "callback_data": f"access:approve:{chat_id}"},
        {"text": "❌ رفض", "callback_data": f"access:reject:{chat_id}"},
    ]]}
    for owner in ADMIN_IDS:
        try:
            send_text(
                "🔐 طلب إضافة بوت TON\n\n"
                f"📍 المكان: {chat_title}\n"
                f"🆔 Chat ID: {chat_id}\n"
                f"🏷 النوع: {chat_type}\n"
                f"👤 من أضافه: {actor_name} ({actor_id})\n\n"
                "اختر موافقة أو رفض. قبل الموافقة، لن ينفذ البوت أوامر إدارية في هذا المكان.",
                owner,
                keyboard,
            )
        except Exception as exc:
            log.warning("Could not notify owner %s: %s", owner, exc)
    save_state(state)


def handle_callback(update, state):
    query = update.get("callback_query") or {}
    sender_id = str((query.get("from") or {}).get("id", ""))
    callback_id = query.get("id")
    data = query.get("data", "")
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "access" or parts[1] not in {"approve", "reject"}:
        if callback_id:
            telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": "زر غير معروف"})
        return
    if not is_admin(sender_id):
        if callback_id:
            telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": "هذا الزر مخصص لمالك البوت فقط", "show_alert": "true"})
        return
    action, chat_id = parts[1], parts[2]
    pending = state.setdefault("pending_chats", {})
    entry = pending.get(chat_id)
    if not entry:
        if callback_id:
            telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": "هذا الطلب غير موجود أو تمت معالجته"})
        return
    if action == "approve":
        approved = state.setdefault("approved_chats", [])
        if chat_id not in approved:
            approved.append(chat_id)
        pending.pop(chat_id, None)
        message = f"✅ تمت الموافقة على {entry.get('title', chat_id)}\n🆔 {chat_id}\nالبوت سيقبل أوامره الإدارية في هذا المكان."
        answer = "تمت الموافقة"
    else:
        pending.pop(chat_id, None)
        try:
            telegram("leaveChat", {"chat_id": chat_id})
            message = f"❌ تم رفض {entry.get('title', chat_id)} وغادره البوت."
        except Exception as exc:
            message = f"❌ تم تسجيل رفض {entry.get('title', chat_id)}، لكن تعذرت مغادرة المكان تلقائياً: {exc}"
        answer = "تم الرفض"
    save_state(state)
    if callback_id:
        telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": answer})
    try:
        telegram("editMessageText", {
            "chat_id": str((query.get("message") or {}).get("chat", {}).get("id", sender_id)),
            "message_id": str((query.get("message") or {}).get("message_id", "")),
            "text": message,
        })
    except Exception as exc:
        log.warning("Could not edit approval message: %s", exc)


def handle_updates(state):
    offset = int(state.get("update_offset", 0))
    updates = telegram("getUpdates", {
        "offset": offset + 1,
        "timeout": 1,
        "allowed_updates": json.dumps(["message", "callback_query", "my_chat_member"]),
    }, timeout=5) or []
    for update in updates:
        state["update_offset"] = max(int(state.get("update_offset", 0)), int(update.get("update_id", 0)))
        if update.get("callback_query"):
            try:
                handle_callback(update, state)
            except Exception as exc:
                log.warning("Approval callback failed: %s", exc)
            continue
        if update.get("my_chat_member"):
            change = update["my_chat_member"]
            chat = change.get("chat") or {}
            old_status = (change.get("old_chat_member") or {}).get("status", "left")
            new_status = (change.get("new_chat_member") or {}).get("status", "left")
            if new_status in {"member", "administrator"} and old_status not in {"member", "administrator", "creator"}:
                notify_owner_about_addition(chat, change.get("from"), state)
            continue
        msg = update.get("message") or {}
        sender_id = str((msg.get("from") or {}).get("id", ""))
        if not is_admin(sender_id):
            continue
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if chat.get("type") != "private" and chat_id not in set(state.get("approved_chats", [])):
            continue
        command_parts = (msg.get("text") or "").split()
        command = command_parts[0].lower().split("@")[0] if command_parts else ""
        if command == "/price":
            try:
                data = fetch_market()
                send_text(build_post(data, (num(state.get("iqd_rate_override")) or fetch_iqd_rate()), state.get("last_price")), chat_id)
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
                send_text(daily_report(data, (num(state.get("iqd_rate_override")) or fetch_iqd_rate())), chat_id)
            except Exception as exc:
                send_text(f"تعذر إعداد التقرير حالياً: {exc}", chat_id)
        elif command == "/status":
            send_text("✅ بوت TON يعمل بنظام GitHub Actions كل 10 دقائق.", chat_id)
        elif command == "/calc" and len(command_parts) >= 2:
            qty = num(command_parts[1])
            if qty is None or qty < 0:
                send_text("استخدم الأمر هكذا: /calc 10", chat_id)
            else:
                try:
                    market = fetch_market()
                    rate = num(state.get("iqd_rate_override")) or fetch_iqd_rate()
                    usd = qty * market["price"]
                    iqd = f"{usd * rate:,.0f} د.ع" if rate else "غير متوفر"
                    send_text(f"🧮 حاسبة TON\nالكمية: {qty:g} TON\nالقيمة: ${usd:,.4f}\nبالدينار: {iqd}", chat_id)
                except Exception as exc:
                    send_text(f"تعذر الحساب حالياً: {exc}", chat_id)
        elif command == "/iqd" and len(command_parts) >= 2:
            rate = num(command_parts[1])
            if rate and rate > 0:
                state["iqd_rate_override"] = rate
                send_text(f"✅ تم ضبط سعر الصرف: 1 USD = {rate:,.0f} IQD", chat_id)
            else:
                send_text("استخدم الأمر هكذا: /iqd 1310", chat_id)
    save_state(state)


def run_cycle(state):
    log.info("Starting scheduled bot cycle; target channel=%s", CHAT_ID)
    try:
        handle_updates(state)
    except Exception as exc:
        log.warning("Telegram polling failed: %s", exc)

    data = fetch_market()
    log.info("Market data fetched: TON price=$%.6f; 24h change=%s", data["price"], data.get("change"))
    rate = num(state.get("iqd_rate_override")) or fetch_iqd_rate()
    fingerprint = {
        key: round(data.get(key), 7) if data.get(key) is not None else None
        for key in ("price", "change", "high", "low")
    }
    publish_market_update(data, rate, state)
    log.info("Single combined text-only market post sent")
    state["fingerprint"] = fingerprint
    state["last_market_update"] = datetime.now(BAGHDAD).isoformat()

    save_state(state)
    log.info("Scheduled bot cycle completed successfully")


def main():
    state = load_state()
    log.info("Starting one-shot TON bot update and access-control check")
    try:
        run_cycle(state)
    except Exception:
        save_state(state)
        log.exception("TON bot cycle failed")
        raise


if __name__ == "__main__":
    main()
