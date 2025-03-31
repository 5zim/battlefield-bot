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
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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

# Настройка Selenium
def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    return driver

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

# EA App: Скидки и раздачи (с использованием Selenium)
def get_ea_battlefield():
    print("Проверяю Battlefield в EA App с помощью Selenium...", flush=True)
    discounts = []
    driver = None
    try:
        driver = setup_driver()
        url = "https://www.ea.com/games/battlefield"
        driver.get(url)
        # Ждём загрузки элементов
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        # Получаем HTML после выполнения JavaScript
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        # Ищем элементы с играми
        game_elements = soup.find_all("div", class_=re.compile(r'game|product|tile|card|ea-play-game|content'))
        print(f"EA: Найдено элементов: {len(game_elements)}", flush=True)
        for elem in game_elements:
            title = elem.find("h3") or elem.find("h2") or elem.find("h4") or elem.find("span", class_=re.compile(r'title|name'))
            if title and "Battlefield" in title.text:
                print(f"EA: Найдена игра: {title.text}", flush=True)
                discount_elem = elem.find(string=re.compile(r'\d+%\s*off|\d+%\s*discount|sale|deal', re.I))
                if discount_elem:
                    print(f"EA: Найдена скидка: {discount_elem}", flush=True)
                    discount = re.search(r'(\d+)%', discount_elem)
                    if discount:
                        game_link = elem.find("a", href=True)
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
    finally:
        if driver:
            driver.quit()
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
        response = requests.get(url, headers=headers)
        print(f"Epic: Статус ответа: {response.status_code}", flush=True)
        data = response.json()
        games = data["data"]["Catalog"]["searchStore"]["elements"]
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

# Prime Gaming: Скидки и раздачи (с использованием Selenium)
def get_prime_battlefield():
    print("Проверяю Battlefield в Prime Gaming с помощью Selenium...", flush=True)
    discounts = []
    driver = None
    try:
        driver = setup_driver()
        url = "https://gaming.amazon.com/home"
        driver.get(url)
        # Ждём загрузки элементов
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        # Получаем HTML после выполнения JavaScript
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        # Ищем элементы с играми
        game_elements = soup.find_all("div", class_=re.compile(r'item|offer|card|product|game|content'))
        print(f"Prime: Найдено элементов: {len(game_elements)}", flush=True)
        for elem in game_elements:
            title = elem.find("h3") or elem.find("h2") or elem.find("h4") or elem.find("span", class_=re.compile(r'title|name'))
            if title and "Battlefield" in title.text:
                print(f"Prime: Найдена игра: {title.text}", flush=True)
                free_elem = elem.find(string=re.compile(r'free|claim|gratis|prime', re.I))
                if free_elem:
                    print(f"Prime: Найдено упоминание free/claim: {free_elem}", flush=True)
                    game_link = elem.find("a", href=True)
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
    finally:
        if driver:
            driver.quit()
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
