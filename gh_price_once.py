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

