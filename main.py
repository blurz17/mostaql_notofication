import requests
import os
import random
import telebot
try:
    import config
    BOT_TOKEN = config.bot_token
    CHAT_IDS = config.chat_ids
except ImportError:
    BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    CHAT_IDS = [int(x.strip()) for x in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if x.strip()]

if not BOT_TOKEN or not CHAT_IDS:
    raise ValueError("Missing Bot Token or Chat IDs in configuration.")
import time
import logging
import threading
import uuid
import os
from flask import Flask, request, redirect, render_template_string, jsonify, send_file
from fetch_bulk import run_bulk_scrape
try:
    from config import *
except ImportError:
    pass
bot_token = BOT_TOKEN
chat_ids = CHAT_IDS
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

# Only these two categories should trigger Telegram alerts / be kept
ALLOWED_CATEGORIES = {
    "برمجة، تطوير المواقع والتطبيقات",
    "ذكاء اصطناعي وتعلم الآلة",
}

project_page_url  = "https://mostaql.com/project/"
projects_page_url = 'https://mostaql.com/projects?category=business,development,engineering-architecture,design,marketing,writing-translation,support&budget_max=10000&sort=latest&_=1688336827002'

requests_session = requests.Session()
requests_session.headers = {
    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'x-requested-with': 'XMLHttpRequest'
}

# --- CONFIGURATION ---
# Set to False if you run this on a local home network and don't need Tor
USE_TOR = True
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
    
    try:
        # Added timeout to prevent hanging
        response = requests_session.get(project_page_url + str(offer_id), timeout=15)
    except Exception as e:
        logger.error(f'Timeout or connection error fetching {offer_id}: {e}')
        return None
    
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

def send_document_to_telegram(chat_id, file_path, caption):
    try:
        with open(file_path, 'rb') as f:
            bot.send_document(
                chat_id=chat_id,
                document=f,
                caption=caption
            )
            logger.info(f"Successfully sent bulk document to {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send document to {chat_id}: {e}")

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mostaql Bot Dashboard</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #121212; color: #fff; margin: 0; padding: 2rem; display: flex; flex-direction: column; align-items: center; }
        .card { background: #1e1e1e; border-radius: 12px; padding: 2rem; width: 100%; max-width: 500px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); margin-bottom: 2rem; }
        h2 { margin-top: 0; color: #4facfe; }
        .status { display: inline-block; padding: 0.5rem 1rem; border-radius: 20px; font-weight: bold; margin-bottom: 1rem; }
        .status.active { background: #1b5e20; color: #a5d6a7; }
        .status.paused { background: #b71c1c; color: #ffcdd2; }
        .btn { background: #4facfe; color: #fff; border: none; padding: 0.75rem 1.5rem; border-radius: 6px; cursor: pointer; font-size: 1rem; font-weight: bold; width: 100%; transition: 0.3s; }
        .btn:hover { background: #00f2fe; }
        .btn-danger { background: #e53935; }
        .btn-danger:hover { background: #ff5252; }
        input[type="number"] { width: 100%; padding: 0.75rem; border-radius: 6px; border: 1px solid #333; background: #2d2d2d; color: #fff; margin-bottom: 1rem; box-sizing: border-box; }
        .warning { font-size: 0.85rem; color: #ffb74d; margin-bottom: 1rem; }
    </style>
</head>
<body>
    <div class="card">
        <h2>🤖 Telegram Bot Status</h2>
        <div class="status {{ 'active' if bot_active else 'paused' }}">
            {{ '🟢 ACTIVE (Scraping every minute)' if bot_active else '🔴 PAUSED' }}
        </div>
        <form action="/toggle" method="POST">
            <button class="btn {{ 'btn-danger' if bot_active else '' }}" type="submit">
                {{ 'Pause Bot' if bot_active else 'Start Bot' }}
            </button>
        </form>
    </div>

    <div class="card">
        <h2>📥 Fetch Bulk Projects</h2>
        <p class="warning">⚠️ Notice: Fetching more than 50 projects via the web may timeout. Keep it small for web downloads!</p>
        <form action="/bulk" method="POST">
            <label for="num_projects">Number of Projects to Fetch:</label>
            <input type="number" id="num_projects" name="num_projects" value="500" min="1" required>
            <button class="btn" type="submit">Fetch & View Now</button>
        </form>
    </div>
</body>
</html>'''

app = Flask(__name__)
bot_active = True
tasks = {}

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, bot_active=bot_active)

@app.route('/toggle', methods=['POST'])
def toggle():
    global bot_active
    bot_active = not bot_active
    return redirect('/')

LOADING_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Fetching Projects...</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background-color: #121212; color: #fff; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #1e1e1e; border-radius: 12px; padding: 2rem; width: 100%; max-width: 500px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); text-align: center; }
        h2 { color: #4facfe; margin-top: 0; }
        #log { background: #000; color: #0f0; padding: 1rem; border-radius: 8px; font-family: monospace; font-size: 0.9rem; margin: 1rem 0; min-height: 50px; text-align: left; }
        .btn { background: #4facfe; color: #fff; text-decoration: none; padding: 0.75rem 1.5rem; border-radius: 6px; font-weight: bold; display: none; transition: 0.3s; margin-top: 1rem; }
        .btn:hover { background: #00f2fe; }
        .btn-home { background: #333; margin-top: 10px; display: inline-block; }
    </style>
</head>
<body>
    <div class="card">
        <h2>⏳ Scraping in Progress...</h2>
        <p>Your server is securely scraping Mostaql using Tor. Please wait.</p>
        <div id="log">Initializing...</div>
        <a id="download-btn" class="btn" href="#">📥 Download HTML File</a>
        <br><a href="/" class="btn btn-home" style="display:inline-block">← Back to Dashboard</a>
    </div>

    <script>
        const taskId = "{{ task_id }}";
        const logEl = document.getElementById('log');
        const downloadBtn = document.getElementById('download-btn');
        
        const interval = setInterval(async () => {
            const res = await fetch('/status/' + taskId);
            const data = await res.json();
            
            logEl.innerText = data.progress;
            
            if (data.status === 'done') {
                clearInterval(interval);
                downloadBtn.href = '/download/' + taskId;
                downloadBtn.style.display = 'inline-block';
                logEl.innerText += "\\n\\n✅ Finished successfully!";
            } else if (data.status === 'error') {
                clearInterval(interval);
                logEl.style.color = '#ff5252';
                logEl.innerText += "\\n\\n❌ Error occurred.";
            }
        }, 2000);
    </script>
</body>
</html>'''

def background_task(num, task_id):
    def progress_callback(msg):
        tasks[task_id]['progress'] = msg
        
    try:
        html = run_bulk_scrape(num, use_tor=USE_TOR, progress_callback=progress_callback)
        os.makedirs('downloads', exist_ok=True)
        filepath = f"downloads/{task_id}.html"
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
            
        tasks[task_id]['status'] = 'done'
        
        # Send the file via Telegram to the user!
        progress_callback("Sending file to your Telegram app...")
        for chat_id in chat_ids:
            send_document_to_telegram(chat_id, filepath, f"Here are your {num} Mostaql projects! 🚀")
            
        progress_callback("Done! Sent to your Telegram.")
    except Exception as e:
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['progress'] = str(e)

@app.route('/bulk', methods=['POST'])
def bulk():
    try:
        num = int(request.form.get('num_projects', 25))
    except ValueError:
        num = 25
    
    task_id = str(uuid.uuid4())
    tasks[task_id] = {'status': 'processing', 'progress': 'Initializing Tor connection...'}
    
    threading.Thread(target=background_task, args=(num, task_id), daemon=True).start()
    return render_template_string(LOADING_TEMPLATE, task_id=task_id)

@app.route('/status/<task_id>')
def status(task_id):
    return jsonify(tasks.get(task_id, {'status': 'error', 'progress': 'Task not found'}))

@app.route('/download/<task_id>')
def download(task_id):
    filepath = f"downloads/{task_id}.html"
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True, download_name=f"mostaql_bulk_{task_id[:6]}.html")
    return "File not found", 404

@app.route('/ping')
@app.route('/', methods=['HEAD'])
def ping():
    return "OK", 200

def scraping_loop():
    logger.info("Waiting 30 seconds for Tor to initialize...")
    time.sleep(30)
    
    while True:
        if not bot_active:
            time.sleep(10)
            continue
            
        set_new_proxy()
        try:
            response = requests_session.get(projects_page_url, timeout=15)
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
                
                # 1. Check if offer exists in DB
                if offer_exists(offer_id):
                    continue
                
                # 2. Fetch HTML page details (Fixed redundant request)
                offer_to_send = get_offer_description(offer_id)
                if not offer_to_send:
                    continue
                
                # 3. Add to Database (always, so we don't refetch it again next loop)
                add_offer(offer_to_send)
                
                # 4. Only alert for the two categories we care about
                if offer_to_send.category not in ALLOWED_CATEGORIES:
                    logger.info(f'Skipping offer_id {offer_id} - category not allowed: {offer_to_send.category}')
                    continue
                
                # 5. Send Telegram alerts
                for chat_id in chat_ids:
                    send_alert(chat_id, offer_to_send)

        except Exception as e:
            logger.error(f'Error occurred in main loop: {e}')
            
        logger.info('Sleeping for 1 minute to release resources')
        time.sleep(60)

if __name__ == '__main__':
    # Start the scraping bot in a background thread
    threading.Thread(target=scraping_loop, daemon=True).start()
    
    # Start the beautiful Flask UI server on the main thread
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
