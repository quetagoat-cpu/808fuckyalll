import os
import hmac
import hashlib
import json
import threading
from urllib.parse import parse_qsl

import requests
from flask import Flask, request, jsonify, render_template

from database import (
    get_user_alerts,
    add_alert,
    delete_user_alert,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

BASE_URL = "https://api.binance.com/api/v3/ticker/price?symbol="

app = Flask(__name__)


# ---------- Telegram initData validation ----------

def validate_init_data(init_data: str):
    """Проверяет подпись initData из Telegram WebApp. Возвращает dict user или None."""
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    try:
        return json.loads(parsed.get("user", "{}"))
    except Exception:
        return None


def current_user_id():
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_init_data(init_data)
    if not user:
        return None
    return user.get("id")


# ---------- Binance ----------

def get_price(symbol: str) -> float:
    r = requests.get(BASE_URL + symbol, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])


# ---------- Routes ----------

@app.get("/")
def index():
    return render_template("alerts.html")


@app.get("/api/alerts")
def list_alerts():
    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    rows = get_user_alerts(user_id)
    return jsonify([
        {"id": r[0], "symbol": r[1], "target_price": r[2], "direction": r[3]}
        for r in rows
    ])


@app.post("/api/alerts")
def create_alert():
    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    raw_target = data.get("target_price")

    if not symbol:
        return jsonify({"error": "Укажи тикер, например BTCUSDT"}), 400
    try:
        target = float(raw_target)
    except (TypeError, ValueError):
        return jsonify({"error": "Цена должна быть числом"}), 400

    try:
        current = get_price(symbol)
    except Exception:
        return jsonify({"error": f"Не удалось получить цену {symbol}. Проверь тикер."}), 400

    direction = "above" if target >= current else "below"
    add_alert(user_id, symbol, target, direction)
    return jsonify({"ok": True, "direction": direction, "current_price": current})


@app.delete("/api/alerts/<int:alert_id>")
def remove_alert(alert_id: int):
    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    deleted = delete_user_alert(alert_id, user_id)
    return jsonify({"ok": True, "deleted": deleted})


# ---------- Entrypoint for background thread ----------

def run_webapp():
    port = int(os.environ.get("PORT", 8080))
    print(f"WebApp server starting on 0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)


def start_webapp_thread():
    t = threading.Thread(target=run_webapp, daemon=True)
    t.start()
    return t