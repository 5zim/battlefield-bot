import telebot
import requests
import schedule
import time
import threading
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import re
from bs4 import BeautifulSoup

# Токен бота
TOKEN = '7790106263:AAHKNdO8yDrDbmZzoB8U64hMTNhPr0LkxrU'
bot = telebot.TeleBot(TOKEN)

# Чат для публикации
CHAT_ID = '@SalePixel'

# Хранилище
posted_items = set()
subscribers = set()

# Список Battlefield
BATTLEFIELD_GAMES = {
    'Battlefield 1': {'steam_id': 1238840},
    'Battlefield 3': {'steam_id': 1238820},
    'Battlefield 4': {'steam_id': 1238860},
    'Battlefield 5': {'steam_id': 1238810},
    'Battlefield 2042': {'steam_id': 1517290},
    'Battlefield Hardline': {'steam_id': 1238880}
}

# Кнопки
def create_buttons(link):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Купить/Забрать", url=link))
    return markup

# Steam: Скидки и раздачи
def get_steam_battlefield():
    print("Проверяю Battlefield в Steam...")
    discounts = []
    try:
        for title, info in BATTLEFIELD_GAMES.items():
            app_id = info['steam_id']
            url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200 and response.json()[str(app_id)]['success']:
                game_data = response.json()[str(app_id)]['data']
                if 'price_overview' in game_data:
                    discount_percent = game_data['price_overview']['discount_percent']
                    old_price = game_data['price_overview']['initial'] / 100
                    new_price = game_data['price_overview']['final'] / 100
                    if discount_percent >= 50 or new_price == 0:
                        discounts.append({
                            'title': title, 'platform': 'Steam',
                            'link': f"https://store.steampowered.com/app/{app_id}",
                            'image': game_data.get('header_image', ''),
                            'old_price': old_price, 'new_price': new_price,
                            'discount_percent': discount_percent
                        })
        print(f"Найдено в Steam: {len(discounts)}")
        return discounts
    except Exception as e:
        print(f"Ошибка Steam: {e}")
        return []

# EA App: Скидки и раздачи
def get_ea_battlefield():
    print("Проверяю Battlefield в EA App...")
    url = "https://www.ea.com/games"
    discounts = []
    try:
        print(f"Отправляю запрос к {url}")
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        print(f"Получен ответ: Статус {response.status_code}")
        if response.status_code != 200:
            print(f"Ошибка EA: Статус {response.status_code}")
            return discounts
        soup = BeautifulSoup(response.text, 'html.parser')
        game_elements = soup.find_all('div', class_=re.compile('game-card|title'))
        print(f"Найдено элементов для парсинга: {len(game_elements)}")
        for game in game_elements:
            title_elem = game.find('h3') or game.find('span', class_=re.compile('title'))
            if title_elem and 'Battlefield' in title_elem.text:
                title = title_elem.text.strip()
                price_elem = game.find(string=re.compile(r'\$\d+\.\d+|\bFREE\b'))
                if price_elem:
                    if 'FREE' in price_elem:
                        old_price = 0
                        new_price = 0
                        discount_percent = 100
                    else:
                        prices = re.findall(r'\$(\d+\.\d+)', price_elem)
                        if len(prices) == 2:
                            old_price = float(prices[0])
                            new_price = float(prices[1])
                            discount_percent = int(((old_price - new_price) / old_price) * 100)
                        else:
                            continue
                    if discount_percent >= 50 or new_price == 0:
                        link = game.find('a', href=True)['href'] if game.find('a') else url
                        image_elem = game.find('img')
                        image = image_elem['src'] if image_elem else 'https://www.ea.com/favicon.ico'
                        discounts.append({
                            'title': title, 'platform': 'EA App',
                            'link': link if link.startswith('http') else f"https://www.ea.com{link}",
                            'image': image,
                            'old_price': old_price, 'new_price': new_price,
                            'discount_percent': discount_percent
                        })
        print(f"Найдено в EA: {len(discounts)}")
        return discounts
    except Exception as e:
        print(f"Ошибка EA: {e}")
        return discounts

# Epic Games: Только бесплатные раздачи
def get_epic_battlefield():
    print("Проверяю Battlefield в Epic Games...")
    url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"Ошибка Epic: Статус {response.status_code}")
            return []
        data = response.json()
        games = data['data']['Catalog']['searchStore']['elements']
        free_games = []
        for game in games:
            if (game['price']['totalPrice']['discountPrice'] == 0 and 
                game['price']['totalPrice']['originalPrice'] > 0 and 
                'Battlefield' in game['title']):
                title = game['title']
                image = game['keyImages'][0]['url']
                slug = game.get('productSlug', title.lower().replace(' ', '-'))
                link = f"https://www.epicgames.com/store/en-US/p/{slug}"
                end_date = game.get('promotions', {}).get('promotionalOffers', [{}])[0].get('endDate')
                end_date = datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%S.%fZ") if end_date else None
                free_games.append({
                    'title': title, 'platform': 'Epic Games',
                    'link': link, 'image': image,
                    'old_price': game['price']['totalPrice']['originalPrice'] / 100,
                    'new_price': 0, 'discount_percent': 100,
                    'end_date': end_date
                })
        print(f"Найдено раздач в Epic: {len(free_games)}")
        return free_games
    except Exception as e:
        print(f"Ошибка Epic: {e}")
        return []

# Prime Gaming: Скидки и раздачи
def get_prime_battlefield():
    print("Проверяю Battlefield в Prime Gaming...")
    url = "https://gaming.amazon.com/home"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if response.status_code != 200:
            print(f"Ошибка Prime Gaming: Статус {response.status_code}")
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        games = soup.select('div[data-a-target="offer-card"]')
        discounts = []
        for game in games:
            title_elem = game.find('h3') or game.find('span', class_=re.compile('title'))
            if title_elem and 'Battlefield' in title_elem.text:
                title = title_elem.text.strip()
                price_elem = game.find(string=re.compile(r'\$\d+\.\d+|\bFREE\b'))
                if price_elem:
                    if 'FREE' in price_elem:
                        old_price = 0
                        new_price = 0
                        discount_percent = 100
                    else:
                        prices = re.findall(r'\$(\d+\.\d+)', price_elem)
                        if len(prices) == 2:
                            old_price = float(prices[0])
                            new_price = float(prices[1])
                            discount_percent = int(((old_price - new_price) / old_price) * 100)
                        else:
                            continue
                    if discount_percent >= 50 or new_price == 0:
                        link = game.find('a', href=True)['href'] if game.find('a') else url
                        image_elem = game.find('img')
                        image = image_elem['src'] if image_elem else 'https://gaming.amazon.com/favicon.ico'
                        discounts.append({
                            'title': title, 'platform': 'Prime Gaming',
                            'link': link if link.startswith('http') else f"https://gaming.amazon.com{link}",
                            'image': image,
                            'old_price': old_price, 'new_price': new_price,
                            'discount_percent': discount_percent
                        })
        print(f"Найдено в Prime Gaming: {len(discounts)}")
        return discounts
    except Exception as e:
        print(f"Ошибка Prime Gaming: {e}")
        return []

# Проверка и публикация
def check_battlefield():
    print("Запускаю проверку Battlefield...")
    steam_items = get_steam_battlefield()
    ea_items = get_ea_battlefield()
    epic_items = get_epic_battlefield()
    prime_items = get_prime_battlefield()
    all_items = steam_items + ea_items + epic_items + prime_items

    if not all_items:
        message = "🔍 Пока Battlefield отдыхает от скидок и раздач."
        try:
            bot.send_message(CHAT_ID, message)
            print("Отправлено сообщение об отсутствии скидок")
        except Exception as e:
            print(f"Ошибка отправки сообщения: {e}")
    else:
        for item in all_items:
            item_id = f"{item['platform']}_{item['title']}_{item['new_price']}"
            if item_id not in posted_items:
                if item['new_price'] == 0:
                    message = (f"Бесплатная раздача!\nИгра: {item['title']}\nПлатформа: {item['platform']}\n"
                               f"Старая цена: ${item['old_price']:.2f}")
                    if 'end_date' in item and item['end_date']:
                        message += f"\nДо конца: {item['end_date'].strftime('%Y-%m-%d %H:%M UTC')}"
                else:
                    message = (f"Скидка!\nИгра: {item['title']}\nПлатформа: {item['platform']}\n"
                               f"Старая цена: ${item['old_price']:.2f}\nНовая цена: ${item['new_price']:.2f}\n"
                               f"Скидка: {item['discount_percent']}%")
                buttons = create_buttons(item['link'])
                try:
                    bot.send_photo(CHAT_ID, item['image'], caption=message, reply_markup=buttons)
                    for subscriber in subscribers:
                        bot.send_photo(subscriber, item['image'], caption=message, reply_markup=buttons)
                    posted_items.add(item_id)
                    print(f"Опубликована: {item['title']} ({item['platform']})")
                except Exception as e:
                    print(f"Ошибка публикации: {e}")
                    bot.send_message(CHAT_ID, message, reply_markup=buttons)
                    for subscriber in subscribers:
                        bot.send_message(subscriber, message, reply_markup=buttons)
                    posted_items.add(item_id)
                time.sleep(3)

# Команды
@bot.message_handler(commands=['start'])
def send_welcome(message):
    print("Получена команда /start")
    bot.reply_to(message, "Привет! Я бот для скидок и раздач Battlefield (1, 3, 4, 5, 2042, Hardline) на Steam, EA App, Epic Games и Prime Gaming. Используй /subscribe!")

@bot.message_handler(commands=['subscribe'])
def subscribe(message):
    print("Получена команда /subscribe")
    subscribers.add(message.chat.id)
    bot.reply_to(message, "Ты подписался на уведомления о Battlefield!")

@bot.message_handler(commands=['unsubscribe'])
def unsubscribe(message):
    print("Получена команда /unsubscribe")
    if message.chat.id in subscribers:
        subscribers.remove(message.chat.id)
        bot.reply_to(message, "Ты отписался.")
    else:
        bot.reply_to(message, "Ты не подписан.")

# Расписание
def run_schedule():
    print("Запускаю расписание...")
    schedule.every(1).hours.do(check_battlefield)
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            print(f"Ошибка в расписании: {e}")
            time.sleep(60)  # Пауза перед повторной попыткой

# Запуск
if __name__ == "__main__":
    print("Бот запущен!")
    try:
        print("Начинаю первую проверку...")
        check_battlefield()  # Первая проверка сразу
        print("Запускаю поток расписания...")
        schedule_thread = threading.Thread(target=run_schedule, daemon=True)
        schedule_thread.start()
        print("Запускаю polling...")
        while True:
            try:
                bot.polling(none_stop=True, skip_pending=True, interval=5)
            except Exception as e:
                print(f"Ошибка polling: {e}")
                time.sleep(15)  # Перезапуск polling после ошибки
    except Exception as e:
        print(f"Критическая ошибка запуска: {e}")
