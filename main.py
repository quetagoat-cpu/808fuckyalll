import os
import telebot
import requests
import time
import threading
from database import add_alert, get_all_alerts, delete_alert
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from webapp import start_webapp_thread

# Токен берётся из переменной окружения BOT_TOKEN (задаётся на Railway в Variables)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Добавь его в переменные окружения (Railway → Variables).")
bot = telebot.TeleBot(BOT_TOKEN)

# Публичный URL, по которому открывается Mini App (Railway выдаёт его автоматически)
WEBAPP_URL = os.environ.get("WEBAPP_URL")

# ИСПРАВЛЕНО: правильный базовый URL публичного REST API Binance
BASE_URL = "https://api.binance.com/api/v3/ticker/price?symbol="

# Переменная для сохранения твоего ID чата
MY_CHAT_ID = None


def get_price(ticker: str) -> float:
    """Запрашивает текущую цену тикера у Binance и возвращает float."""
    response = requests.get(BASE_URL + ticker, timeout=10)
    response.raise_for_status()  # выбросит ошибку, если Binance ответил не 200
    data = response.json()
    return float(data["price"])


# Функция фонового мониторинга для второго потока
def check_market_alerts():
    print("Background alert monitoring started...", flush=True)
    while True:
        alerts = get_all_alerts()

        for alert_id, user_id, symbol, target_price, direction in alerts:
            try:
                current_price = get_price(symbol)

                triggered = (
                    (direction == "above" and current_price >= target_price) or
                    (direction == "below" and current_price <= target_price)
                )

                if triggered:
                    arrow = "выросла до" if direction == "above" else "упала до"
                    bot.send_message(
                        user_id,
                        f"🚨 {symbol} {arrow} {target_price} USDT! Текущая цена: {current_price}"
                    )
                    delete_alert(alert_id)
            except Exception as e:
                print(f"Ошибка при проверке {symbol}: {e}")

        time.sleep(60)  # Проверка раз в минуту


@bot.message_handler(commands=['start'])
def send_welcome(message):
    global MY_CHAT_ID
    MY_CHAT_ID = message.chat.id
    bot.reply_to(message, "Welcome, bro! Target monitoring is active. Type /price to open menu.")


@bot.message_handler(commands=['price'])
def send_price_menu(message):
    markup = InlineKeyboardMarkup()
    btn_btc = InlineKeyboardButton(text="Bitcoin (BTC)", callback_data="BTCUSDT")
    btn_eth = InlineKeyboardButton(text="Ethereum (ETH)", callback_data="ETHUSDT")
    btn_sol = InlineKeyboardButton(text="Solana (SOL)", callback_data="SOLUSDT")
    btn_ton = InlineKeyboardButton(text="Toncoin (TON)", callback_data="TONUSDT")
    markup.row(btn_btc, btn_eth)
    markup.row(btn_sol, btn_ton)

    # Кнопка Mini App прямо в меню цен
    if WEBAPP_URL:
        markup.add(InlineKeyboardButton(
            text="⚙️ Управлять алертами",
            web_app=WebAppInfo(url=WEBAPP_URL),
        ))

    bot.send_message(message.chat.id, "Select a coin to check the real-time price:", reply_markup=markup)


@bot.message_handler(commands=['alerts'])
def open_alerts_app(message):
    if not WEBAPP_URL:
        bot.reply_to(
            message,
            "⚠️ WEBAPP_URL не настроен. Добавь его в переменные окружения (Railway → Variables)."
        )
        return

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(
        text="📱 Открыть мои алерты",
        web_app=WebAppInfo(url=WEBAPP_URL),
    ))
    bot.send_message(
        message.chat.id,
        "Управление алертами — прямо здесь, без команд 👇",
        reply_markup=markup,
    )


@bot.message_handler(commands=['setalert'])
def set_alert_command(message):
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "Формат команды: /setalert BTCUSDT 70000")
        return
    try:
        symbol = parts[1].upper()
        target_price = float(parts[2])
    except ValueError:
        bot.reply_to(message, "Цена должна быть числом. Пример: /setalert BTCUSDT 70000")
        return

    try:
        current_price = get_price(symbol)
    except Exception as e:
        print("Error fetching price for", symbol, ":", e, flush=True)
        bot.reply_to(message, f"⚠️ Не удалось получить текущую цену {symbol}. Проверь тикер и попробуй снова.")
        return

    if target_price >= current_price:
        direction = "above"
        direction_text = "вырастет до"
    else:
        direction = "below"
        direction_text = "упадёт до"

    add_alert(message.from_user.id, symbol, target_price, direction)
    bot.reply_to(
        message,
        f"Alert set for {symbol}: сообщу, когда цена {direction_text} {target_price} USDT "
        f"(сейчас: {current_price} USDT)."
    )


@bot.callback_query_handler(func=lambda call: True)
def handle_button_click(call):
    bot.answer_callback_query(call.id)

    ticker = call.data
    try:
        current_price = get_price(ticker)
        rounded_price = round(current_price, 2)
        coin_name = ticker.replace("USDT", "")
        text_reply = f"{coin_name} price right now: {rounded_price} USDT"
        bot.send_message(call.message.chat.id, text_reply)
    except Exception as e:
        print("Error fetching price for", ticker, ":", e, flush=True)
        bot.send_message(call.message.chat.id, f"⚠️ Не удалось получить цену {ticker}. Попробуй ещё раз.")


# Запускаем веб-сервер Mini App в отдельном потоке
start_webapp_thread()

# Создаём и запускаем фоновый поток для слежки за ценой
alert_thread = threading.Thread(target=check_market_alerts)
alert_thread.daemon = True
alert_thread.start()

print("Main Telegram bot thread is running...", flush=True)
bot.infinity_polling()