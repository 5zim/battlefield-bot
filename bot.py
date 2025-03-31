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
TOKEN = os.getenv('TELEGRAM_TOKEN')  # Токен из переменной окружения Render
bot = telebot.TeleBot(TOKEN)

# Чат для публикации
CHAT_ID = '@SalePixel'  # Твой канал

# Список Battlefield игр с их Steam ID
BATTLEFIELD_GAMES = {
    "Battlefield 1": "1237600",
    "Battlefield V": "1238810",
    "Battlefield 2042": "1517290"
}

# Flask приложение
app = Flask(__name__)

# Хранилище для отслеживания скидок
posted_items = set()

# Steam: Скидки и раздачи
def get_steam_battlefield():
    print("Проверяю Battlefield в Steam...", flush=True)
    discounts = []
    try:
        for game_name, app_id in BATTLEFIELD_GAMES.items():
            url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
            response = requests.get(url).json()
            if response[app_id]["success"]:
                data = response[app_id]["data"]
                if data.get("price_overview", {}).get("discount_percent", 0) > 0:
                    discount = {
                        "id": f"steam_{app_id}",
                        "name": game_name,
                        "discount": data["price_overview"]["discount_percent"],
                        "price": data["price_overview"]["final_formatted"],
                        "url": f"https://store.steampowered.com/app/{app_id}"
                    }
                    discounts.append(discount)
    except Exception as e:
        print(f"Ошибка проверки Steam: {e}", flush=True)
    print(f"Найдено в Steam: {len(discounts)}", flush=True)
    return discounts

# EA App: Скидки и раздачи
def get_ea_battlefield():
    print("Проверяю Battlefield в EA App...", flush=True)
    discounts = []
    try:
        url = "https://www.ea.com/games/battlefield"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        print(f"Получен ответ: Статус {response.status_code}", flush=True)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Ищем игры Battlefield (это пример, нужно адаптировать под реальную структуру сайта)
            games = soup.find_all("a", href=re.compile(r'/games/battlefield/'))
            for game in games:
                title = game.find("h3")
                if title and "Battlefield" in title.text:
                    price_elem = game.find("span", class_=re.compile(r'price|discount'))
                    if price_elem and "off" in price_elem.text.lower():
                        discount = re.search(r'(\d+)%', price_elem.text)
                        if discount:
                            discounts.append({
                                "id": f"ea_{title.text}",
                                "name": title.text,
                                "discount": int(discount.group(1)),
                                "price": "Check on EA App",  # Цена может быть сложнее спарсить
                                "url": f"https://www.ea.com{game['href']}"
                            })
    except Exception as e:
        print(f"Ошибка проверки EA: {e}", flush=True)
    print(f"Найдено в EA: {len(discounts)}", flush=True)
    return discounts

# Epic Games: Только бесплатные раздачи
def get_epic_battlefield():
    print("Проверяю Battlefield в Epic Games...", flush=True)
    discounts = []
    try:
        url = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers).json()
        games = response["data"]["Catalog"]["searchStore"]["elements"]
        for game in games:
            if "Battlefield" in game["title"]:
                price = game["price"]["totalPrice"]["discountPrice"]
                if price == 0:  # Бесплатная раздача
                    discounts.append({
                        "id": f"epic_{game['id']}",
                        "name": game["title"],
                        "discount": 100,  # Бесплатно = 100% скидка
                        "price": "Free",
                        "url": f"https://www.epicgames.com/store/en-US/p/{game['productSlug']}"
                    })
    except Exception as e:
        print(f"Ошибка проверки Epic: {e}", flush=True)
    print(f"Найдено раздач в Epic: {len(discounts)}", flush=True)
    return discounts

# Prime Gaming: Скидки и раздачи
def get_prime_battlefield():
    print("Проверяю Battlefield в Prime Gaming...", flush=True)
    discounts = []
    try:
        url = "https://gaming.amazon.com/home"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        # Ищем игры (пример, нужно адаптировать под структуру сайта)
        games = soup.find_all("div", class_=re.compile(r'offer|game'))
        for game in games:
            title = game.find("h3")
            if title and "Battlefield" in title.text:
                if "free" in game.text.lower():
                    discounts.append({
                        "id": f"prime_{title.text}",
                        "name": title.text,
                        "discount": 100,  # Бесплатно
                        "price": "Free with Prime",
                        "url": "https://gaming.amazon.com/home"
                    })
    except Exception as e:
        print(f"Ошибка проверки Prime: {e}", flush=True)
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
        bot.send_message(chat_id, "🔍 Пока Battlefield отдыхает от скидок и раздач. Солдаты, готовьте кошельки — ждём следующую атаку акций!")
        print("Отправлено сообщение об отсутствии скидок", flush=True)
    else:
        for item in all_discounts:
            item_id = item["id"]
            if item_id not in posted_items:
                message = (
                    f"🎮 {item['name']}\n"
                    f"🔥 Скидка: {item['discount']}%\n"
                    f"💰 Цена: {item['price']}\n"
                    f"🔗 [Купить]({item['url']})"
                )
                bot.send_message(chat_id, message, parse_mode="Markdown", disable_web_page_preview=True)
                posted_items.add(item_id)
                print(f"Опубликовано: {item['name']}", flush=True)

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
            print(f"Сообщение: {update.message.text}, Chat ID: {update.message.chat.id}, Message ID: {update.message.message_id}", flush=True)
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
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
