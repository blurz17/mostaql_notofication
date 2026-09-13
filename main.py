import requests
import random
import telebot
import time
import logging
from config import *
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import init_db, offer_exists, add_offer, Offer
from bs4 import BeautifulSoup

import sys
# Setup built-in logging instead of loguru
# We remove the StreamHandler to avoid UnicodeEncodeError in Windows PowerShell
# All logs will safely go to mostaql_bot.log in UTF-8.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler("mostaql_bot.log", mode="w", encoding="utf-8")
    ]
)
# Add a custom stream handler that ignores encoding errors for the console
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
console_handler.stream = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1, closefd=False)
logging.getLogger().addHandler(console_handler)

logger = logging.getLogger(__name__)

init_db()

bot = telebot.TeleBot(bot_token)

project_page_url  = "https://mostaql.com/project/"
projects_page_url = 'https://mostaql.com/projects?category=business,development,engineering-architecture,design,marketing,writing-translation,support&budget_max=10000&sort=latest&_=1688336827002'

requests_session = requests.Session()
requests_session.headers = {
    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'x-requested-with': 'XMLHttpRequest'
}

# --- CONFIGURATION ---
# Set to False if you run this on a local home network and don't need Tor
USE_TOR = False 
# ---------------------

def set_new_proxy():
    if not USE_TOR:
        requests_session.proxies = {}
        return
        
    creds = str(random.randint(10000, 0x7fffffff)) + ":" + "foobar"
    requests_session.proxies = {
        'http': 'socks5h://{}@localhost:9050'.format(creds),
        'https': 'socks5h://{}@localhost:9050'.format(creds)
    }

def clean_text(text, max_len=1000):
    if not text:
        return "N/A"
    # Remove excessive newlines and spaces
    import re
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_len] + '...' if len(text) > max_len else text

def get_offer_description(offer_id):
    logger.info(f'Fetching offer_id: {offer_id}')
    set_new_proxy()
    response = requests_session.get(project_page_url + str(offer_id))
    
    # Use built-in html.parser instead of lxml
    soup = BeautifulSoup(response.text, 'html.parser')
    
    try:
        category_el = soup.find_all('li', {'class': 'breadcrumb-item'})
        category = category_el[-1].text.strip() if category_el else 'N/A'
        
        title_el = soup.find('h1')
        title = title_el.text.strip() if title_el else 'N/A'
        
        budget_label = soup.find(lambda tag: tag.name == 'div' and 'الميزانية' in tag.text and len(tag.text) < 50)
        price = budget_label.parent.text.replace('الميزانية', '').strip() if budget_label else 'N/A'
        
        # In the new Mostaql layout, the owner is usually an anchor with class profile__name or within a <bdi> tag
        owner_el = soup.find('a', class_='profile__name') or soup.find('bdi')
        project_owner = owner_el.text.strip() if owner_el else 'N/A'
        
        # Extract project description
        desc_el = soup.find('div', class_='text-wrapper-div carda__content') or soup.find(id='project-meta-panel')
        # If the exact class isn't found, find the first large paragraph after the title
        if not desc_el:
            desc_el = soup.find('p', class_='project__brief') or soup.find('div', class_='project__brief')
        description = desc_el.text.strip() if desc_el else 'No details found.'
        
    except Exception as e:
        logger.error(f'Failed to parse offer_id {offer_id}. (Maybe blocked or HTML changed): {e}')
        return None

    logger.info(f'Parsed offer_id: {offer_id} | title: {title}')
    return Offer(
        offer_id=offer_id,
        category=clean_text(category, 100),
        title=clean_text(title, 200),
        price=clean_text(price, 100),
        project_owner=clean_text(project_owner, 100),
        description=clean_text(description, 1000)
    )

def build_message(offer: Offer):
    return f'''📣📣 New Job Alert 📣📣

🔹 Field: {offer.category}
---------------------------------
🔹 Title: {offer.title}
---------------------------------
🔹 Budget: {offer.price}
---------------------------------
🔹 Employer: {offer.project_owner}
---------------------------------
🔹 Details: 
{offer.description}
'''

def send_alert(chat_id, offer: Offer):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("⬅️ Click here to visit the project's page ➡️", url=project_page_url + str(offer.offer_id)))
    try:
        bot.send_message(
            chat_id=chat_id,
            text=build_message(offer),
            reply_markup=markup,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f'Failed to send alert to {chat_id}: {e}')

while True:
    set_new_proxy()
    try:
        response = requests_session.get(projects_page_url)
        # Handle cases where response might not be JSON (e.g. 403 Forbidden)
        try:
            offers = response.json().get('collection', [])
        except ValueError:
            logger.error(f"Failed to parse JSON. Status code: {response.status_code}")
            offers = []
            
        if offers:
            logger.info(f'Fetched {len(offers)} offers from API')

        for offer_data in offers:
            offer_id = offer_data.get('id')
            if not offer_id:
                continue

            # 1. Skip if already processed in DB
            if offer_exists(offer_id):
                continue
            
            # 2. Fetch HTML page details (Fixed redundant request)
            offer_to_send = get_offer_description(offer_id)
            if not offer_to_send:
                continue
            
            # 3. Add to Database
            add_offer(offer_to_send)
            
            # 4. Send Telegram alerts
            for chat_id in chat_ids:
                send_alert(chat_id, offer_to_send)

    except Exception as e:
        logger.error(f'Error occurred in main loop: {e}')
        
    logger.info('Sleeping for 1 minute to release resources')
    time.sleep(60)
