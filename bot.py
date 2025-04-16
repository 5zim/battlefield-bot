import requests
from datetime import datetime
import telebot
import re
from bs4 import BeautifulSoup
from flask import Flask, request
import time
import os
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Токен бота
TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TOKEN:
    logger.error("TELEGRAM_TOKEN не задан")
    exit(1)
bot = telebot.TeleBot(TOKEN)

# Чат для публикации
CHAT_ID = '@SalePixel'

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

# Хранилища для ограничения частоты команд
command_counts = {}
timeouts = {}

# Проверка ограничения частоты команд
def check_rate_limit(chat_id, user_id):
    if str(chat_id).startswith("-100"):  # Пропускаем каналы
        return True

    current_time = time.time()

    if chat_id in timeouts and timeouts[chat_id] > current_time:
        remaining_time = int(timeouts[chat_id] - current_time)
        minutes, seconds = divmod(remaining_time, 60)
        message = f"Нубище, ты на тайм-ауте! Подожди ещё {minutes} минут {seconds} секунд. 🚬"
        bot.send_message(chat_id, message)
        logger.info(f"Пользователь {user_id} на тайм-ауте: {message}")
        return False

    if chat_id not in command_counts:
        command_counts[chat_id] = []
    command_counts[chat_id] = [t for t in command_counts[chat_id] if current_time - t < 60]
    command_counts[chat_id].append(current_time)

    # Увеличиваем лимит до 5 команд в минуту для тестов
    if len(command_counts[chat_id]) >= 5:
        timeout_until = current_time + 3600
        timeouts[chat_id] = timeout_until
        message = "Нубище, перекури часик, слишком много команд! 🚬"
        bot.send_message(chat_id, message)
        logger.info(f"Пользователь {user_id} получил тайм-аут на 1 час")
        return False
    elif len(command_counts[chat_id]) == 4:
        message = "Братан, не спами, я уже работаю! 😎"
        bot.send_message(chat_id, message)
        logger.info(f"Пользователь {user_id} получил предупреждение за спам")
    return True

# CheapShark API: Скидки на игры
def get_cheapshark_deals():
    logger.info("Проверяю скидки через CheapShark API...")
    discounts = []
    seen_deals = set()
    try:
        stores_url = "https://www.cheapshark.com/api/1.0/stores"
        stores_response = requests.get(stores_url).json()
        store_map = {store["storeID"]: store["storeName"] for store in stores_response}
        logger.info(f"CheapShark: Найдено магазинов: {len(store_map)}")

        for title in BATTLEFIELD_TITLES:
            deals_url = f"https://www.cheapshark.com/api/1.0/deals?title={title}&sortBy=Price"
            response = requests.get(deals_url).json()
            time.sleep(1)  # Задержка для избежания лимитов
            for deal in response:
                deal_title = deal["title"]
                if "Battlefield" in deal_title and "Medieval" not in deal_title:
                    matches_title = any(bf_title in deal_title for bf_title in BATTLEFIELD_TITLES)
                    if matches_title:
                        store_id = deal["storeID"]
                        store_name = store_map.get(store_id, "Unknown Store")
                        discount_percent = round(float(deal["savings"]))
                        if discount_percent > 0:
                            deal_key = f"{deal['title']}_{store_name}_{discount_percent}"
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
                                logger.info(f"CheapShark: Найдена скидка: {deal['title']} - {discount_percent}% в {store_name}")
    except Exception as e:
        logger.error(f"Ошибка проверки CheapShark: {e}")
    logger.info(f"Найдено скидок через CheapShark: {len(discounts)}")
    return discounts

# Epic Games: Только бесплатные раздачи
def get_epic_battlefield():
    logger.info("Проверяю Battlefield в Epic Games...")
    discounts = []
    try:
        url = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        logger.info(f"Epic: Статус ответа: {response.status_code}")
        data = response.json()
        games = data["data"]["Catalog"]["searchStore"]["elements"]
        logger.info(f"Epic: Найдено игр: {len(games)}")
        for game in games:
            title = game.get("title", "")
            if "Battlefield" in title:
                logger.info(f"Epic: Найдена игра: {title}")
                price = game["price"]["totalPrice"]["discountPrice"]
                if price == 0:
                    product_slug = game.get("productSlug", game.get("urlSlug", ""))
                    discounts.append({
                        "id": f"epic_{game['id']}",
                        "name": title,
                        "discount": 100,
                        "price": "Free",
                        "url": f"https://www.epicgames.com/store/en-US/p/{product_slug}",
                        "store": "Epic Games"
                    })
    except Exception as e:
        logger.error(f"Ошибка проверки Epic: {e}")
    logger.info(f"Найдено раздач в Epic: {len(discounts)}")
    return discounts

# GOG.com: Бесплатные раздачи и скидки
def get_gog_battlefield():
    logger.info("Проверяю Battlefield в GOG.com...")
    discounts = []
    try:
        url = "https://www.gog.com/en/games?priceRange=0,0"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.content, "html.parser")
        games = soup.find_all("a", class_="product-tile")
        logger.info(f"GOG: Найдено бесплатных игр: {len(games)}")
        for game in games:
            title_element = game.find("span", class_="product-tile__title")
            if not title_element:
                continue
            title = title_element.text.strip()
            if "Battlefield" in title:
                game_url = "https://www.gog.com" + game.get("href")
                discounts.append({
                    "id": f"gog_giveaway_{title}",
                    "name": title,
                    "discount": 100,
                    "price": "Free",
                    "url": game_url,
                    "store": "GOG.com"
                })
                logger.info(f"GOG: Найдена бесплатная игра: {title}")

        for title in BATTLEFIELD_TITLES:
            search_url = f"https://catalog.gog.com/v1/catalog?query={title}&order=desc:discounted&limit=10"
            response = requests.get(search_url, headers=headers).json()
            time.sleep(1)
            products = response.get("products", [])
            for product in products:
                if "Battlefield" in product["title"]:
                    discount = product.get("price", {}).get("discountPercentage", 0)
                    if discount > 0:
                        price = product["price"]["finalPrice"]
                        product_url = f"https://www.gog.com{product['url']}"
                        discounts.append({
                            "id": f"gog_discount_{product['id']}",
                            "name": product["title"],
                            "discount": discount,
                            "price": price,
                            "url": product_url,
                            "store": "GOG.com"
                        })
                        logger.info(f"GOG: Найдена скидка: {product['title']} - {discount}%")
    except Exception as e:
        logger.error(f"Ошибка проверки GOG: {e}")
    logger.info(f"Найдено в GOG.com: {len(discounts)}")
    return discounts

# IndieGala: Бесплатные раздачи
def get_indiegala_battlefield():
    logger.info("Проверяю Battlefield в IndieGala...")
    discounts = []
    try:
        url = "https://freebies.indiegala.com/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.content, "html.parser")
        games = soup.find_all("div", class_="relative")
        logger.info(f"IndieGala: Найдено бесплатных игр: {len(games)}")
        for game in games:
            title_element = game.find("h5", class_="font-bold")
            if not title_element:
                continue
            title = title_element.text.strip()
            if "Battlefield" in title:
                game_url = game.find("a", class_="relative")["href"]
                discounts.append({
                    "id": f"indiegala_{title}",
                    "name": title,
                    "discount": 100,
                    "price": "Free",
                    "url": game_url,
                    "store": "IndieGala"
                })
                logger.info(f"IndieGala: Найдена бесплатная игра: {title}")
    except Exception as e:
        logger.error(f"Ошибка проверки IndieGala: {e}")
    logger.info(f"Найдено в IndieGala: {len(discounts)}")
    return discounts

# Fanatical: Бесплатные раздачи
def get_fanatical_battlefield():
    logger.info("Проверяю Battlefield в Fanatical...")
    discounts = []
    try:
        url = "https://www.fanatical.com/en/blog/free-games"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.content, "html.parser")
        articles = soup.find_all("article")
        logger.info(f"Fanatical: Найдено статей: {len(articles)}")
        for article in articles:
            title_element = article.find("h2")
            if not title_element:
                continue
            title = title_element.text.strip()
            if "Battlefield" in title:
                link_element = article.find("a")
                if link_element and "href" in link_element.attrs:
                    game_url = "https://www.fanatical.com" + link_element["href"]
                    discounts.append({
                        "id": f"fanatical_{title}",
                        "name": title,
                        "discount": 100,
                        "price": "Free",
                        "url": game_url,
                        "store": "Fanatical"
                    })
                    logger.info(f"Fanatical: Найдена бесплатная игра: {title}")
    except Exception as e:
        logger.error(f"Ошибка проверки Fanatical: {e}")
    logger.info(f"Найдено в Fanatical: {len(discounts)}")
    return discounts

# Steam: Бесплатные раздачи через RSS-ленту
def get_steam_battlefield():
    logger.info("Проверяю Battlefield в Steam (раздачи)...")
    discounts = []
    try:
        url = "https://store.steampowered.com/feeds/news/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.content, "xml")
        items = soup.find_all("item")
        logger.info(f"Steam: Найдено новостей: {len(items)}")
        for item in items:
            title = item.find("title").text.strip()
            if "Battlefield" in title and "free" in title.lower():
                link = item.find("link").text.strip()
                matches_title = any(bf_title in title for bf_title in BATTLEFIELD_TITLES)
                if matches_title:
                    discounts.append({
                        "id": f"steam_{title}",
                        "name": title,
                        "discount": 100,
                        "price": "Free",
                        "url": link,
                        "store": "Steam"
                    })
                    logger.info(f"Steam: Найдена бесплатная раздача: {title}")
    except Exception as e:
        logger.error(f"Ошибка проверки Steam: {e}")
    logger.info(f"Найдено в Steam: {len(discounts)}")
    return discounts

# Очистка posted_items раз в неделю
def clear_posted_items():
    logger.info("Очищаю posted_items...")
    global posted_items
    posted_items.clear()
    logger.info("posted_items очищен!")

# Проверка и публикация
def check_battlefield(chat_id, user_chat_id=None):
    try:
        logger.info("Запускаю проверку Battlefield...")
        all_discounts = (
            get_cheapshark_deals() +
            get_epic_battlefield() +
            get_gog_battlefield() +
            get_indiegala_battlefield() +
            get_fanatical_battlefield() +
            get_steam_battlefield()
        )
        new_discounts = 0
        if not all_discounts:
            message = "🔍 Пока Battlefield отдыхает от скидок и раздач. Ждём следующую атаку акций! 💂‍♂️"
            bot.send_message(chat_id, message)
            logger.info(f"Отправлено сообщение в канал {chat_id}: {message}")
            if user_chat_id:
                message = "✅ Проверка завершена! Новых скидок нет. Все актуальные скидки в @SalePixel: https://t.me/SalePixel 📢"
                bot.send_message(user_chat_id, message)
                logger.info(f"Отправлено сообщение пользователю {user_chat_id}: {message}")
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
                    logger.info(f"Отправлено сообщение в канал {chat_id}: {message}")
                    logger.info(f"Опубликовано: {item['name']}")
                    posted_items.add(item_id)
                    new_discounts += 1

            if new_discounts == 0:
                message = "🔍 Новых скидок нет. Все актуальные скидки уже опубликованы! ✅"
                bot.send_message(chat_id, message)
                logger.info(f"Отправлено сообщение в канал {chat_id}: {message}")

        if user_chat_id:
            if new_discounts > 0:
                message = f"✅ Проверка завершена! Найдено {new_discounts} новых скидок. Посмотри в @SalePixel: https://t.me/SalePixel 📢"
            else:
                message = "✅ Проверка завершена! Новых скидок нет. Все актуальные скидки уже опубликованы в @SalePixel: https://t.me/SalePixel 📢"
            bot.send_message(user_chat_id, message)
            logger.info(f"Отправлено сообщение пользователю {user_chat_id}: {message}")
    except Exception as e:
        logger.error(f"Ошибка в check_battlefield: {e}")

# Корневой маршрут для проверки Render
@app.route('/', methods=['GET'])
def home():
    logger.info("Проверка корневого маршрута")
    return "Bot is alive. Use /check in Telegram to trigger.", 200

# Обработка webhook-запросов от Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("Получен запрос на /webhook")
    try:
        data = request.get_json()
        if not data:
            logger.error("Пустой JSON")
            return 'Bad Request', 400
        logger.info(f"Полученные данные: {data}")
        update = telebot.types.Update.de_json(data)
        if not update:
            logger.error("Не удалось распарсить Update")
            return 'Bad Request', 400
        bot.process_new_updates([update])
        logger.info("Обновление успешно обработано")
        return 'OK', 200
    except Exception as e:
        logger.error(f"Ошибка в webhook: {str(e)}")
        return 'Error', 500

# Установка webhook при запуске
def set_webhook():
    webhook_url = 'https://battlefield-bot.onrender.com/webhook'
    try:
        bot.remove_webhook()
        time.sleep(0.1)
        bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook установлен: {webhook_url}")
    except Exception as e:
        logger.error(f"Ошибка установки webhook: {e}")

# Обработка команд
@bot.message_handler(commands=['check'])
def handle_check(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    logger.info(f"Текст сообщения: {message.text}, Chat ID: {chat_id}, Message ID: {message.message_id}")
    
    if message.chat.type == 'private':
        logger.info("Команда /check получена в личке, запускаю проверку...")
        if check_rate_limit(chat_id, user_id):
            check_battlefield(CHAT_ID, user_chat_id=chat_id)
    elif message.chat.type in ['group', 'supergroup', 'channel']:
        logger.info("Команда /check получена в канале, запускаю проверку...")
        check_battlefield(CHAT_ID)

@bot.message_handler(content_types=['new_chat_members'])
def handle_new_members(message):
    chat_id = message.chat.id
    for new_member in message.new_chat_members:
        if new_member.id == bot.get_me().id:
            continue
        first_name = new_member.first_name if new_member.first_name else "друг"
        user_id = new_member.id
        welcome_message = (
            f"👋 Привет, {first_name}! Добро пожаловать в нашу группу! 🎉\n"
            "Я бот, который ищет скидки и раздачи на Battlefield. "
            "Напиши /check, чтобы запустить проверку. "
            "Все скидки публикуются в @SalePixel: https://t.me/SalePixel 📢"
        )
        bot.send_message(chat_id, welcome_message)
        logger.info(f"Отправлено приветствие новому участнику {first_name} (ID: {user_id}) в чате {chat_id}")

# Запуск
if __name__ == "__main__":
    logger.info("Бот запущен!")
    
    # Настройка планировщика с часовым поясом МСК
    scheduler = BackgroundScheduler(timezone=pytz.timezone('Europe/Moscow'))
    scheduler.add_job(
        check_battlefield,
        'cron',
        hour=15,
        minute=0,
        args=[CHAT_ID],
        misfire_grace_time=3600  # Допуск на пропущенные задачи: 1 час
    )
    scheduler.add_job(
        clear_posted_items,
        'cron',
        day_of_week='mon',
        hour=0,
        minute=0,
        misfire_grace_time=3600
    )
    # Тестовая задача для немедленного выполнения
    scheduler.add_job(
        check_battlefield,
        'date',
        run_date=datetime.now(pytz.timezone('Europe/Moscow')),
        args=[CHAT_ID]
    )
    scheduler.start()
    logger.info("Планировщик запущен с часовым поясом МСК")

    set_webhook()
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
