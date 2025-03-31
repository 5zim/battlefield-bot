import requests
from datetime import datetime
import telebot
import re
from bs4 import BeautifulSoup
from flask import Flask, request
import threading
import schedule
import time
import os

# Токен бота
TOKEN = os.getenv('TELEGRAM_TOKEN')  # Токен берётся из переменной окружения Render
bot = telebot.TeleBot(TOKEN)

# Чат для публикации
CHAT_ID = '@SalePixel'  # Твой канал

# Список Battlefield игр с их Steam ID
BATTLEFIELD_GAMES = {
    # Добавь Steam ID игр, если нужно, например:
    # "Battlefield 1": "1237600",
    # "Battlefield V": "1238810"
}

# Flask приложение
app = Flask(__name__)

# Хранилище для отслеживания скидок
posted_items = set()

# Steam: Скидки и раздачи
def get_steam_battlefield():
    print("Проверяю Battlefield в Steam...", flush=True)
    discounts = []
    # Здесь должен быть код для проверки Steam (например, через Steam API)
    # Пока возвращаем пустой список для примера
    print(f"Найдено в Steam: {len(discounts)}", flush=True)
    return discounts

# EA App: Скидки и раздачи
def get_ea_battlefield():
    print("Проверяю Battlefield в EA App...", flush=True)
    discounts = []
    try:
        url = "https://www.ea.com/games"
        print(f"Отправляю запрос к {url}", flush=True)
        response = requests.get(url)
        print(f"Получен ответ: Статус {response.status_code}", flush=True)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Здесь парсинг скидок (добавь логику, если нужно)
            print(f"Найдено элементов для парсинга: 0", flush=True)
    except Exception as e:
        print(f"Ошибка проверки EA: {e}", flush=True)
    print(f"Найдено в EA: {len(discounts)}", flush=True)
    return discounts

# Epic Games: Только бесплатные раздачи
def get_epic_battlefield():
    print("Проверяю Battlefield в Epic Games...", flush=True)
    discounts = []
    # Здесь парсинг Epic Games (добавь логику, если нужно)
    print(f"Найдено раздач в Epic: {len(discounts)}", flush=True)
    return discounts

# Prime Gaming: Скидки и раздачи
def get_prime_battlefield():
    print("Проверяю Battlefield в Prime Gaming...", flush=True)
    discounts = []
    # Здесь парсинг Prime Gaming (добавь логику, если нужно)
    print(f"Найдено в Prime Gaming: {len(discounts)}", flush=True)
    return discounts

# Проверка и публикация
def check_battlefield(chat_id):
    print("Запускаю проверку Battlefield...", flush=True)
    all_discounts = (
        get_steam_battlefield() +
        get_ea_battlefield() +
        get_epic_battlefield() +
        get_prime_battlefield()
    )
    if not all_discounts:
        bot.send_message(chat_id, "🔍 Пока Battlefield отдыхает от скидок и раздач.")
        print("Отправлено сообщение об отсутствии скидок", flush=True)
    else:
        for item in all_discounts:
            item_id = item.get('id', str(datetime.now()))  # Уникальный ID для скидки
            if item_id not in posted_items:
                # Здесь отправка сообщения о скидке (добавь форматирование)
                bot.send_message(chat_id, f"Найдена скидка: {item}")
                posted_items.add(item_id)

# Корневой маршрут для проверки Render
@app.route('/', methods=['GET'])
def home():
    print("Проверка корневого маршрута", flush=True)
    return "Bot is alive. Use /check in Telegram to trigger.", 200

# Обработка webhook-запросов от Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    print("Получен запрос на /webhook", flush=True)
    try:
        data = request.get_json()
        if not data:
            print("Ошибка: Пустой JSON", flush=True)
            return 'Bad Request', 400
        print(f"Полученные данные: {data}", flush=True)
        update = telebot.types.Update.de_json(data)
        if not update:
            print("Ошибка: Не удалось распарсить Update", flush=True)
            return 'Bad Request', 400

        # Проверка для личных сообщений и групп
        if update.message:
            print(f"Сообщение: {update.message.text}, Chat ID: {update.message.chat.id}", flush=True)
            if update.message.text == '/check':
                chat_id = '@SalePixel'
                threading.Thread(target=check_battlefield, args=(chat_id,), daemon=True).start()

        # Проверка для каналов
        elif update.channel_post:
            print(f"Сообщение из канала: {update.channel_post.text}, Chat ID: {update.channel_post.chat.id}", flush=True)
            if update.channel_post.text == '/check':
                chat_id = '@SalePixel'
                threading.Thread(target=check_battlefield, args=(chat_id,), daemon=True).start()

        return 'OK', 200
    except Exception as e:
        print(f"Ошибка в webhook: {e}", flush=True)
        return 'Error', 500

# Установка webhook при запуске
def set_webhook():
    webhook_url = 'https://battlefield-bot.onrender.com/webhook'
    try:
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        print(f"Webhook установлен: {webhook_url}", flush=True)
    except Exception as e:
        print(f"Ошибка установки webhook: {e}", flush=True)

# Функция для расписания
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(60)

# Запуск
if __name__ == "__main__":
    print("Бот запущен!", flush=True)
    schedule.every().day.at("12:00").do(check_battlefield, chat_id='@SalePixel')  # Ежедневно в 12:00 UTC
    threading.Thread(target=run_schedule, daemon=True).start()
    set_webhook()
    port = int(os.getenv('PORT', 8000))  # Бери порт из переменной окружения, по умолчанию 8000
app.run(host='0.0.0.0', port=port)
