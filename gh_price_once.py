#!/usr/bin/env python3
import json, os, sys, urllib.parse, urllib.request
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
    req = urllib.request.Request(url, headers={"User-Agent": "TONPriceBot/2.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8"))

def number(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def tg(method, payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    req = urllib.request.Request(url, data=urllib.parse.urlencode(payload).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=15) as r: result = json.loads(r.read().decode())
    if not result.get("ok"): raise RuntimeError(result.get("description", "Telegram API error"))
    return result.get("result")

def send(text, chat_id=None):
    return tg("sendMessage", {"chat_id": chat_id or CHAT_ID, "text": text, "disable_web_page_preview": "true"})

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f: return json.load(f)
    except (OSError, json.JSONDecodeError): return {}

def save_state(state):
    with open(STATE_FILE + ".tmp", "w", encoding="utf-8") as f: json.dump(state, f, ensure_ascii=False)
    os.replace(STATE_FILE + ".tmp", STATE_FILE)

def market_data():
    d = {"price": None, "change": None, "high": None, "low": None, "sources": []}
    try:
        x = get_json(BINANCE_TICKER)
        d.update(price=number(x.get("lastPrice")), change=number(x.get("priceChangePercent")),
                 high=number(x.get("highPrice")), low=number(x.get("lowPrice")))
        if d["price"] is not None: d["sources"].append("Binance")
    except Exception as e: print("Binance unavailable:", e, file=sys.stderr)
    if d["price"] is None:
        try:
            x = get_json(COINGECKO)["the-open-network"]
            d["price"], d["change"] = number(x.get("usd")), number(x.get("usd_24h_change"))
            if d["price"] is not None: d["sources"].append("CoinGecko")
        except Exception as e: print("CoinGecko unavailable:", e, file=sys.stderr)
    if d["high"] is None or d["low"] is None:
        try:
            x = get_json(COINGECKO_HISTORY)
            ps = [number(row[1]) for row in x.get("prices", []) if len(row) > 1]
            ps = [p for p in ps if p is not None]
            if ps:
                if d["high"] is None: d["high"] = max(ps)
                if d["low"] is None: d["low"] = min(ps)
                if "CoinGecko chart" not in d["sources"]: d["sources"].append("CoinGecko chart")
        except Exception as e: print("CoinGecko history unavailable:", e, file=sys.stderr)
    return d

def fx_rate():
    try:
        x = get_json(FX_API)
        v = number(x.get("rates", {}).get("IQD"))
        return (v, "open.er-api.com") if v and v > 0 else (None, None)
    except Exception as e:
        print("FX unavailable:", e, file=sys.stderr)
        return None, None

def pct(v):
    if v is None: return "غير متوفر حالياً"
    return f"{'🟢 ▲' if v > 0 else '🔴 ▼' if v < 0 else '⚪'} {v:+.2f}%"

def build_post(d, rate, previous):
    p = d["price"]
    now = datetime.now(BAGHDAD)
    iqd = f"{p * rate:,.0f} د.ع" if rate is not None else "غير متوفر (تعذر جلب سعر الصرف)"
    high = f"${d['high']:.4f}" if d["high"] is not None else "غير متوفر"
    low = f"${d['low']:.4f}" if d["low"] is not None else "غير متوفر"
    if previous is None: diff = "غير متوفر (بانتظار قراءة سابقة)"
    else:
        delta = p - previous
        diff = f"{'🟢' if delta > 0 else '🔴' if delta < 0 else '⚪'} {delta:+.4f} USD"
    sources = " / ".join(d["sources"]) or "غير متوفر"
    if rate is not None: sources += " / open.er-api.com"
    msg = (
        "╔════════════════════╗\n"
        "     💎 TON • MARKET\n"
        "╚════════════════════╝\n\n"
        f"💵 السعر بالدولار: ${p:.4f} USDT\n"
        f"🇮🇶 السعر بالدينار العراقي: {iqd}\n"
        f"📈 تغيّر 24 ساعة: {pct(d['change'])}\n"
        f"🔺 أعلى سعر 24 ساعة: {high}\n"
        f"🔻 أقل سعر 24 ساعة: {low}\n"
        f"📉 مقارنة بالتحديث السابق: {diff}\n\n"
        f"⏱️ الوقت: {now.strftime('%I:%M:%S %p')} بتوقيت بغداد\n"
        f"🌐 المصادر: {sources}\n"
        "🔗 Binance: https://www.binance.com/en/trade/TON_USDT\n"
        "🔗 CoinGecko: https://www.coingecko.com/en/coins/the-open-network\n\n"
        "⚠️ السوق يتغير بسرعة؛ تحقق من الأسعار قبل التداول."
    )
    return msg

def admin_commands(state):
    if not ADMIN_IDS: return
    offset = int(state.get("update_offset", 0))
    updates = tg("getUpdates", {"offset": offset + 1, "timeout": 0,
                               "allowed_updates": json.dumps(["message"])}) or []
    for u in updates:
        state["update_offset"] = max(int(state.get("update_offset", 0)), int(u.get("update_id", 0)))
        m = u.get("message") or {}
        user_id = str((m.get("from") or {}).get("id", ""))
        if user_id not in ADMIN_IDS: continue
        chat_id = str((m.get("chat") or {}).get("id", ""))
        text = (m.get("text") or "").split()
        cmd = text[0].lower().split("@")[0] if text else ""
        if cmd == "/price":
            d = market_data()
            rate, _ = fx_rate()
            send(build_post(d, rate, None) if d["price"] is not None else "⚠️ تعذر جلب السعر؛ لم يتم نشر رقم غير مؤكد.", chat_id)
        elif cmd == "/status":
            send("✅ البوت يعمل عبر مهمة GitHub Actions. ملاحظة: الأوامر تُفحص عند تشغيل المهمة وقد تتأخر حتى 10 دقائق.", chat_id)
        elif cmd == "/test":
            send("✅ اختبار الإرسال ناجح.", chat_id)
    save_state(state)

def main():
    state = load_state()
    d = market_data()
    if d["price"] is None:
        raise RuntimeError("تعذر جلب السعر من المصادر؛ لن يتم نشر سعر غير مؤكد.")
    rate, _ = fx_rate()
    previous = number(state.get("last_price"))
    message = build_post(d, rate, previous)

    try: admin_commands(state)
    except Exception as e: print("Admin commands skipped:", e, file=sys.stderr)

    fingerprint = {k: round(d[k], 7) if d[k] is not None else None for k in ("price", "change", "high", "low")}
    if state.get("fingerprint") != fingerprint:
        send(message)
        state["fingerprint"] = fingerprint
    else:
        print("No market change; duplicate post skipped.")

    # Optional alert threshold: send only on crossing it.
    if ALERT_USD:
        threshold = number(ALERT_USD)
        if threshold and threshold > 0:
            side = "above" if d["price"] >= threshold else "below"
            old_side = state.get("alert_side")
            if old_side is not None and old_side != side:
                send(f"🔔 تنبيه TON\nالسعر الحالي: ${d['price']:.4f}\nالحد المحدد: ${threshold:.4f}\nالحالة: {'تجاوز الحد للأعلى' if side == 'above' else 'هبط دون الحد'}")
            state["alert_side"] = side

    # First successful run each Baghdad day sends the daily summary.
    today = datetime.now(BAGHDAD).date().isoformat()
    if state.get("summary_date") != today:
        high = f"${d['high']:.4f}" if d["high"] is not None else "غير متوفر"
        low = f"${d['low']:.4f}" if d["low"] is not None else "غير متوفر"
        iqd = f"{d['price'] * rate:,.0f} د.ع" if rate is not None else "غير متوفر"
        send("📅 ملخص TON اليومي\n\n"
             f"💵 السعر: ${d['price']:.4f}\n"
             f"🇮🇶 بالدينار: {iqd}\n"
             f"📈 تغيّر 24 ساعة: {pct(d['change'])}\n"
             f"🔺 أعلى سعر: {high}\n🔻 أقل سعر: {low}\n"
             "⚠️ البيانات المتاحة فقط؛ ليست توصية استثمارية.")
        state["summary_date"] = today

    state["last_price"] = d["price"]
    state["last_run"] = datetime.now(BAGHDAD).isoformat()
    save_state(state)

if __name__ == "__main__":
    try: main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
