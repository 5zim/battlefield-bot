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
    "Battlefield 2042": "1517290",
    "Battlefield 4": "1238860",
    "Battlefield 3": "1238820",
    "Battlefield Hardline": "1238880"
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
                print(f"Steam: {game_name} - {data.get('price_overview', 'Нет данных о цене')}", flush=True)
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

# EA App: Скидки и раздачи (упрощённый парсинг)
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
            # Ищем любые упоминания скидок
            discount_elements = soup.find_all(text=re.compile(r'\d+%\s*off|\d+%\s*discount', re.I))
            print(f"EA: Найдено упоминаний скидок: {len(discount_elements)}", flush=True)
            for elem in discount_elements:
                parent = elem.find_parent()
                title = parent.find("h3") or parent.find("h2") or parent.find("h4")
                if title and "Battlefield" in title.text:
                    print(f"EA: Найдена игра: {title.text}", flush=True)
                    discount = re.search(r'(\d+)%', elem)
                    if discount:
                        game_link = parent.find("a", href=True)
                        game_url = f"https://www.ea.com{game_link['href']}" if game_link else "https://www.ea.com/games/battlefield"
                        discounts.append({
                            "id": f"ea_{title.text}",
                            "name": title.text,
                            "discount": int(discount.group(1)),
                            "price": "Check on EA App",
                            "url": game_url
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
        url = "https://store.epicgames.com/graphql?operationName=getStoreFreeGames&variables=%7B%22locale%22:%22en-US%22,%22country%22:%22US%22,%22allowCountries%22:%22US%22%7D&extensions=%7B%22persistedQuery%22:%7B%22version%22:1,%22sha256Hash%22:%22d5c1a5b6b5a1a5b6b5a1a5b6b5a1a5b6b5a1a5b6b5a1a5b6b5a1a5b6b5a1a5b6%22%7D%7D"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers).json()
        games = response["data"]["Catalog"]["catalogOffers"]["elements"]
        print(f"Epic: Найдено игр: {len(games)}", flush=True)
        for game in games:
            title = game.get("title", "")
            if "Battlefield" in title:
                print(f"Epic: Найдена игра: {title}", flush=True)
                price = game["price"]["totalPrice"]["discountPrice"]
                if price == 0:  # Бесплатная раздача
                    product_slug = game.get("productSlug", game.get("urlSlug", ""))
                    discounts.append({
                        "id": f"epic_{game['id']}",
                        "name": title,
                        "discount": 100,  # Бесплатно = 100% скидка
                        "price": "Free",
                        "url": f"https://www.epicgames.com/store/en-US/p/{product_slug}"
                    })
    except Exception as e:
        print(f"Ошибка проверки Epic: {e}", flush=True)
    print(f"Найдено раздач в Epic: {len(discounts)}", flush=True)
    return discounts

# Prime Gaming: Скидки и раздачи (упрощённый парсинг)
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
        # Ищем любые упоминания "free" или "claim"
        free_elements = soup.find_all(text=re.compile(r'free|claim', re.I))
        print(f"Prime: Найдено упоминаний free/claim: {len(free_elements)}", flush=True)
        for elem in free_elements:
            parent = elem.find_parent()
            title = parent.find("h3") or parent.find("h2") or parent.find("h4")
            if title and "Battlefield" in title.text:
                print(f"Prime: Найдена игра: {title.text}", flush=True)
                game_link = parent.find("a", href=True)
                game_url = game_link['href'] if game_link else "https://gaming.amazon.com/home"
                if not game_url.startswith("http"):
                    game_url = f"https://gaming.amazon.com{game_url}"
                discounts.append({
                    "id": f"prime_{title.text}",
                    "name": title.text,
                    "discount": 100,  # Бесплатно
                    "price": "Free with Prime",
                    "url": game_url
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
