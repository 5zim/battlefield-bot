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

# Токен бота
TOKEN = os.getenv('TELEGRAM_TOKEN')
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
    if str(chat_id).startswith("-100"):
        return True

    current_time = time.time()

    # Сначала проверяем, есть ли уже тайм-аут
    if chat_id in timeouts and timeouts[chat_id] > current_time:
        remaining_time = int(timeouts[chat_id] - current_time)
        minutes, seconds = divmod(remaining_time, 60)
        message = f"Нубище, ты на тайм-ауте! Подожди ещё {minutes} минут {seconds} секунд, прежде чем снова писать. 🚬"
        bot.send_message(chat_id, message)
        print(f"Отправлено сообщение пользователю {chat_id}: {message}", flush=True)
        return False

    # Если тайм-аута нет, проверяем частоту команд
    if chat_id not in command_counts:
        command_counts[chat_id] = []
    command_counts[chat_id] = [t for t in command_counts[chat_id] if current_time - t < 60]
    command_counts[chat_id].append(current_time)

    # Проверяем количество команд
    if len(command_counts[chat_id]) >= 3:
        timeout_until = current_time + 3600
        timeouts[chat_id] = timeout_until
        message = "Нубище, я думаю тебе нужно перекурить часик. Ты отправил слишком много команд подряд. 🚬"
        bot.send_message(chat_id, message)
        print(f"Отправлено сообщение пользователю {chat_id}: {message}", flush=True)
        print(f"Пользователь {user_id} получил тайм-аут на 1 час", flush=True)
        return False
    elif len(command_counts[chat_id]) == 2:
        message = "Братан, остынь, не надо спамить, я тебе уже ответил ранее.😎"
        bot.send_message(chat_id, message)
        print(f"Отправлено сообщение пользователю {chat_id}: {message}", flush=True)
        print(f"Пользователь {user_id} получил предупреждение за спам", flush=True)

    return True

# CheapShark API: Скидки на игры
def get_cheapshark_deals():
    print("Проверяю скидки через CheapShark API... 🕵️‍♂️", flush=True)
    discounts = []
    seen_deals = set()
    try:
        stores_url = "https://www.cheapshark.com/api/1.0/stores"
        stores_response = requests.get(stores_url).json()
        store_map = {store["storeID"]: store["storeName"] for store in stores_response}
        print(f"CheapShark: Найдено магазинов: {len(store_map)}", flush=True)
        print(f"Список магазинов: {list(store_map.values())}", flush=True)

        for title in BATTLEFIELD_TITLES:
            deals_url = f"https://www.cheapshark.com/api/1.0/deals?title={title}&sortBy=Price"
            response = requests.get(deals_url).json()
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
        print(f"Ошибка проверки Epic: {e}", flush=True)
    print(f"Найдено раздач в Epic: {len(discounts)}", flush=True)
    return discounts

# GOG.com: Бесплатные раздачи и скидки
def get_gog_battlefield():
    print("Проверяю Battlefield в GOG.com... 🎁", flush=True)
    discounts = []
    try:
        url = "https://www.gog.com/en/games?priceRange=0,0"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.content, "html.parser")
        games = soup.find_all("a", class_="product-tile")
        print(f"GOG: Найдено бесплатных игр: {len(games)}", flush=True)
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
                print(f"GOG: Найдена бесплатная игра: {title}", flush=True)

        for title in BATTLEFIELD_TITLES:
            search_url = f"https://catalog.gog.com/v1/catalog?query={title}&order=desc:discounted&limit=10"
            response = requests.get(search_url, headers=headers).json()
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
                        print(f"GOG: Найдена скидка: {product['title']} - {discount}%", flush=True)
    except Exception as e:
        print(f"Ошибка проверки GOG: {e}", flush=True)
    print(f"Найдено в GOG.com: {len(discounts)}", flush=True)
    return discounts

# IndieGala: Бесплатные раздачи
def get_indiegala_battlefield():
    print("Проверяю Battlefield в IndieGala... 🎉", flush=True)
    discounts = []
    try:
        url = "https://freebies.indiegala.com/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.content, "html.parser")
        games = soup.find_all("div", class_="relative")
        print(f"IndieGala: Найдено бесплатных игр: {len(games)}", flush=True)
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
                print(f"IndieGala: Найдена бесплатная игра: {title}", flush=True)
    except Exception as e:
        print(f"Ошибка проверки IndieGala: {e}", flush=True)
    print(f"Найдено в IndieGala: {len(discounts)}", flush=True)
    return discounts

# Fanatical: Бесплатные раздачи
def get_fanatical_battlefield():
    print("Проверяю Battlefield в Fanatical... 🎈", flush=True)
    discounts = []
    try:
        url = "https://www.fanatical.com/en/blog/free-games"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.content, "html.parser")
        articles = soup.find_all("article")
        print(f"Fanatical: Найдено статей: {len(articles)}", flush=True)
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
                    print(f"Fanatical: Найдена бесплатная игра: {title}", flush=True)
    except Exception as e:
        print(f"Ошибка проверки Fanatical: {e}", flush=True)
    print(f"Найдено в Fanatical: {len(discounts)}", flush=True)
    return discounts

# Steam: Бесплатные раздачи через RSS-ленту
def get_steam_battlefield():
    print("Проверяю Battlefield в Steam (раздачи)... 🎮", flush=True)
    discounts = []
    try:
        url = "https://store.steampowered.com/feeds/news/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.content, "xml")
        items = soup.find_all("item")
        print(f"Steam: Найдено новостей: {len(items)}", flush=True)
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
                    print(f"Steam: Найдена бесплатная раздача: {title}", flush=True)
    except Exception as e:
        print(f"Ошибка проверки Steam: {e}", flush=True)
    print(f"Найдено в Steam: {len(discounts)}", flush=True)
    return discounts

# Очистка posted_items раз в неделю
def clear_posted_items():
    print("Очищаю posted_items... 🧹", flush=True)
    global posted_items
    posted_items.clear()
    print("posted_items очищен!", flush=True)

# Проверка и публикация
def check_battlefield(chat_id, user_chat_id=None):
    try:
        print("Запускаю проверку Battlefield... ⚔️", flush=True)
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
            message = "🔍 Пока Battlefield отдыхает от скидок и раздач."
            bot.send_message(chat_id, message)
            print(f"Отправлено сообщение в канал {chat_id}: {message}", flush=True)
            if user_chat_id:
                message = "✅ Проверка завершена! Новых скидок нет. Все актуальные скидки уже опубликованы в @SalePixel: https://t.me/SalePixel 📢"
                bot.send_message(user_chat_id, message)
                print(f"Отправлено сообщение пользователю {user_chat_id}: {message}", flush=True)
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
                    print(f"Отправлено сообщение в канал {chat_id}: {message}", flush=True)
                    print(f"Опубликовано: {item['name']}", flush=True)
                    posted_items.add(item_id)
                    new_discounts += 1

            if new_discounts == 0:
                message = "🔍 Новых скидок нет. Все актуальные скидки уже опубликованы! ✅"
                bot.send_message(chat_id, message)
                print(f"Отправлено сообщение в канал {chat_id}: {message}", flush=True)
                print("Отправлено сообщение: новых скидок нет", flush=True)

        if user_chat_id:
            if new_discounts > 0:
                message = f"✅ Проверка завершена! Найдено {new_discounts} новых скидок. Посмотри в @SalePixel: https://t.me/SalePixel 📢"
            else:
                message = "✅ Проверка завершена! Новых скидок нет. Все актуальные скидки уже опубликованы в @SalePixel: https://t.me/SalePixel 📢"
            bot.send_message(user_chat_id, message)
            print(f"Отправлено сообщение пользователю {user_chat_id}: {message}", flush=True)
            print(f"Отправлено уведомление пользователю {user_chat_id}", flush=True)
    except Exception as e:
        print(f"Ошибка в check_battlefield: {e}", flush=True)

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

        # Обработка новых участников группы
        if update.message and update.message.new_chat_members:
            chat_id = update.message.chat.id
            for new_member in update.message.new_chat_members:
                # Пропускаем, если новый участник — это сам бот
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
                print(f"Отправлено приветствие новому участнику {first_name} (ID: {user_id}) в чате {chat_id}", flush=True)

        # Обработка личных сообщений
        if update.message:
            print(f"Личное сообщение получено: {update.message}", flush=True)
            chat_id = update.message.chat.id
            user_id = update.message.from_user.id
            print(f"Текст сообщения: {update.message.text}, Chat ID: {chat_id}, Message ID: {update.message.message_id}", flush=True)
            if update.message.text == '/check':
                if not check_rate_limit(chat_id, user_id):
                    return 'OK', 200
                print("Команда /check получена в личке, запускаю проверку...", flush=True)
                chat_id = '@SalePixel'
                user_chat_id = update.message.chat.id
                check_battlefield(chat_id, user_chat_id)
            elif update.message.text == '/start':
                if not check_rate_limit(chat_id, user_id):
                    return 'OK', 200
                print("Команда /start получена в личке, отправляю приветствие...", flush=True)
                message = "👋 Привет! Я бот, который ищет скидки и раздачи на Battlefield. Напиши /check, чтобы запустить проверку. Все скидки публикуются в @SalePixel: https://t.me/SalePixel 📢"
                bot.send_message(update.message.chat.id, message)
                print(f"Отправлено сообщение пользователю {update.message.chat.id}: {message}", flush=True)
            else:
                print("Получена другая команда в личке, игнорирую", flush=True)

        # Обработка сообщений из канала
        elif update.channel_post:
            print(f"Сообщение из канала получено: {update.channel_post}", flush=True)
            chat_id = update.channel_post.chat.id
            print(f"Текст сообщения: {update.channel_post.text}, Chat ID: {chat_id}", flush=True)
            if update.channel_post.text == '/check':
                print("Команда /check получена в канале, запускаю проверку...", flush=True)
                chat_id = '@SalePixel'
                check_battlefield(chat_id)
            elif update.channel_post.text == '/start':
                print("Команда /start получена в канале, отправляю приветствие...", flush=True)
                message = "👋 Привет! Я бот, который ищет скидки и раздачи на Battlefield. Напиши /check, чтобы запустить проверку. Все скидки публикуются в @SalePixel: https://t.me/SalePixel 📢"
                bot.send_message(update.channel_post.chat.id, message)
                print(f"Отправлено сообщение в канал {update.channel_post.chat.id}: {message}", flush=True)
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

# Запуск
if __name__ == "__main__":
    print("Бот запущен! 🚀", flush=True)
    
    # Настройка планировщика с часовым поясом UTC
    scheduler = BackgroundScheduler(timezone=pytz.UTC)
    # Проверка в 12:00 UTC = 15:00 МСК
    scheduler.add_job(check_battlefield, 'cron', hour=12, minute=0, args=[CHAT_ID])
    scheduler.add_job(clear_posted_items, 'cron', day_of_week='mon', hour=0, minute=0)
    scheduler.start()
    print("Планировщик запущен с часовым поясом UTC", flush=True)

    set_webhook()
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
