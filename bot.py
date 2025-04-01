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

# Список Battlefield игр для поиска
BATTLEFIELD_TITLES = [
    "Battlefield 1",
    "Battlefield V",
    "Battlefield 2042",
    "Battlefield 4",
    "Battlefield 3",
    "Battlefield Hardline"
]

# Flask приложение
app = Flask(__name__)

# Хранилище для отслеживания скидок
posted_items = set()

# CheapShark API: Скидки на игры
def get_cheapshark_deals():
    print("Проверяю скидки через CheapShark API... 🕵️‍♂️", flush=True)
    discounts = []
    seen_deals = set()  # Для фильтрации дубликатов
    try:
        # Получаем список магазинов
        stores_url = "https://www.cheapshark.com/api/1.0/stores"
        stores_response = requests.get(stores_url).json()
        store_map = {store["storeID"]: store["storeName"] for store in stores_response}
        print(f"CheapShark: Найдено магазинов: {len(store_map)}", flush=True)
        print(f"Список магазинов: {list(store_map.values())}", flush=True)

        # Ищем скидки на Battlefield
        for title in BATTLEFIELD_TITLES:
            deals_url = f"https://www.cheapshark.com/api/1.0/deals?title={title}&sortBy=Price"
            response = requests.get(deals_url).json()
            for deal in response:
                if "Battlefield" in deal["title"]:
                    store_id = deal["storeID"]
                    store_name = store_map.get(store_id, "Unknown Store")
                    discount_percent = round(float(deal["savings"]))
                    if discount_percent > 0:  # Только если есть скидка
                        deal_key = f"{deal['title']}_{store_name}_{discount_percent}"  # Уникальный ключ для фильтрации
                        if deal_key not in seen_deals:
                            seen_deals.add(deal_key)
                            deal_id = deal["dealID"]
                            discounts.append({
                                "id": f"cheapshark_{deal_id}",
                                "name": deal["title"],
                                "discount": discount_percent,
                                "price": f"${deal['salePrice']}",
                                "url": f"https://www.cheapshark.com/redirect?dealID={deal_id}",
                                "store": store_name
                            })
                            print(f"CheapShark: Найдена скидка: {deal['title']} - {discount_percent}% в {store_name}", flush=True)
    except Exception as e:
        print(f"Ошибка проверки CheapShark: {e}", flush=True)
    print(f"Найдено скидок через CheapShark: {len(discounts)}", flush=True)
    return discounts

# Epic Games: Только бесплатные раздачи
def get_epic_battlefield():
    print("Проверяю Battlefield в Epic Games... 🎮", flush=True)
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
                        "url": f"https://www.epicgames.com/store/en-US/p/{product_slug}",
                        "store": "Epic Games"
                    })
    except Exception as e:
        print(f"Ошибка проверки Epic: {e}", flush=True)
    print(f"Найдено раздач в Epic: {len(discounts)}", flush=True)
    return discounts

# Prime Gaming: Парсинг через RSS (новый источник)
def get_prime_battlefield():
    print("Проверяю Battlefield в Prime Gaming через RSS... 📢", flush=True)
    discounts = []
    try:
        # Используем RSS-ленту от PC Gamer
        url = "https://www.pcgamer.com/rss"
        response = requests.get(url)
        soup = BeautifulSoup(response.content, 'lxml', features="xml")
        items = soup.find_all("item")
        print(f"Prime: Найдено элементов в RSS: {len(items)}", flush=True)
        for item in items:
            title = item.find("title").text if item.find("title") else ""
            if "Battlefield" in title and "Prime Gaming" in title:
                print(f"Prime: Найдена игра: {title}", flush=True)
                link = item.find("link").text if item.find("link") else "https://gaming.amazon.com/home"
                discounts.append({
                    "id": f"prime_{title}",
                    "name": title,
                    "discount": 100,  # Бесплатно
                    "price": "Free with Prime",
                    "url": link,
                    "store": "Prime Gaming"
                })
    except Exception as e:
        print(f"Ошибка проверки Prime: {e}", flush=True)
    print(f"Найдено в Prime Gaming: {len(discounts)}", flush=True)
    return discounts

# Очистка posted_items раз в неделю
def clear_posted_items():
    print("Очищаю posted_items... 🧹", flush=True)
    global posted_items
    posted_items.clear()
    print("posted_items очищен!", flush=True)

# Проверка и публикация
def check_battlefield(chat_id, user_chat_id=None):
    print("Запускаю проверку Battlefield... ⚔️", flush=True)
    all_discounts = (
        get_cheapshark_deals() +
        get_epic_battlefield() +
        get_prime_battlefield()
    )
    new_discounts = 0
    if not all_discounts:
        message = "🔍 Пока Battlefield отдыхает от скидок и раздач. Солдаты, готовьте кошельки — ждём следующую атаку акций! 💂‍♂️"
        bot.send_message(chat_id, message)
        print("Отправлено сообщение об отсутствии скидок", flush=True)
        if user_chat_id:
            bot.send_message(user_chat_id, f"✅ Проверка завершена! Новых скидок нет. Все актуальные скидки уже опубликованы в @SalePixel: https://t.me/SalePixel 📢")
    else:
        for item in all_discounts:
            item_id = item["id"]
            if item_id not in posted_items:
                message = (
                    f"🎮 **{item['name']}**\n"
                    f"🔥 Скидка: {item['discount']}%\n"
                    f"💰 Цена: {item['price']}\n"
                    f"🏪 Магазин: {item['store']}\n"
                    f"🔗 [Купить]({item['url']})"
                )
                bot.send_message(chat_id, message, parse_mode="Markdown", disable_web_page_preview=True)
                posted_items.add(item_id)
                print(f"Опубликовано: {item['name']}", flush=True)
                new_discounts += 1

        # Если новых скидок нет, отправляем сообщение в канал
        if new_discounts == 0:
            message = "🔍 Новых скидок нет. Все актуальные скидки уже опубликованы! ✅"
            bot.send_message(chat_id, message)
            print("Отправлено сообщение: новых скидок нет", flush=True)

    # Если запрос был из лички, отправляем пользователю уведомление
    if user_chat_id:
        if new_discounts > 0:
            bot.send_message(user_chat_id, f"✅ Проверка завершена! Найдено {new_discounts} новых скидок. Посмотри в @SalePixel: https://t.me/SalePixel 📢")
        else:
            bot.send_message(user_chat_id, "✅ Проверка завершена! Новых скидок нет. Все актуальные скидки уже опубликованы в @SalePixel: https://t.me/SalePixel 📢")
        print(f"Отправлено уведомление пользователю {user_chat_id}", flush=True)

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
            print(f"Личное сообщение получено: {update.message}", flush=True)
            print(f"Текст сообщения: {update.message.text}, Chat ID: {update.message.chat.id}, Message ID: {update.message.message_id}", flush=True)
            if update.message.text == '/check':
                print("Команда /check получена в личке, запускаю проверку...", flush=True)
                chat_id = '@SalePixel'
                user_chat_id = update.message.chat.id
                threading.Thread(target=check_battlefield, args=(chat_id, user_chat_id), daemon=True).start()
            elif update.message.text == '/start':
                print("Команда /start получена в личке, отправляю приветствие...", flush=True)
                bot.send_message(update.message.chat.id, "👋 Привет! Я бот, который ищет скидки и раздачи на Battlefield. Напиши /check, чтобы запустить проверку. Все скидки публикуются в @SalePixel: https://t.me/SalePixel 📢")
            else:
                print("Получена другая команда в личке, игнорирую", flush=True)

        # Проверка для каналов
        elif update.channel_post:
            print(f"Сообщение из канала получено: {update.channel_post}", flush=True)
            print(f"Текст сообщения: {update.channel_post.text}, Chat ID: {update.channel_post.chat.id}", flush=True)
            if update.channel_post.text == '/check':
                print("Команда /check получена в канале, запускаю проверку...", flush=True)
                chat_id = '@SalePixel'
                threading.Thread(target=check_battlefield, args=(chat_id,), daemon=True).start()
            elif update.channel_post.text == '/start':
                print("Команда /start получена в канале, отправляю приветствие...", flush=True)
                bot.send_message(update.channel_post.chat.id, "👋 Привет! Я бот, который ищет скидки и раздачи на Battlefield. Напиши /check, чтобы запустить проверку. Все скидки публикуются в @SalePixel: https://t.me/SalePixel 📢")
            else:
                print("Получена другая команда в канале, игнорирую", flush=True)

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
    print("Бот запущен! 🚀", flush=True)
    schedule.every().day.at("12:00").do(check_battlefield, chat_id='@SalePixel')  # Ежедневно в 12:00 UTC
    schedule.every().monday.at("00:00").do(clear_posted_items)  # Очистка posted_items каждую неделю в понедельник в 00:00 UTC
    threading.Thread(target=run_schedule, daemon=True).start()
    set_webhook()
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
