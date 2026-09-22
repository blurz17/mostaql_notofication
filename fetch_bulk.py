import math
import time
import requests
import random
from bs4 import BeautifulSoup

# This configuration controls whether to use Tor to bypass Mostaql blocks
USE_TOR = False

# Only these two categories should be kept in the bulk output
ALLOWED_CATEGORIES = {
    "برمجة، تطوير المواقع والتطبيقات",
    "ذكاء اصطناعي وتعلم الآلة",
}

requests_session = requests.Session()
requests_session.headers = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'x-requested-with': 'XMLHttpRequest'
}

def set_new_proxy():
    if not USE_TOR:
        requests_session.proxies = {}
        return
    creds = str(random.randint(10000, 0x7fffffff)) + ":" + "foobar"
    requests_session.proxies = {
        'http': 'socks5h://{}@localhost:9050'.format(creds),
        'https': 'socks5h://{}@localhost:9050'.format(creds)
    }

def clean_text(text):
    import re
    return re.sub(r'\s+', ' ', text).strip() if text else 'N/A'

def run_bulk_scrape(num_target: int, use_tor: bool = True, progress_callback=None) -> str:
    global USE_TOR
    USE_TOR = use_tor

    # Because we filter down to two categories, we may need to page through
    # far more than num_target/25 pages to find enough matches. Keep going
    # until we hit the target, run out of data, or hit this safety cap.
    max_pages = math.ceil(num_target / 25) * 20 + 20
    msg = f"\nFetching up to {max_pages} pages to get {num_target} matching projects..."
    print(msg)
    if progress_callback: progress_callback(msg)

    all_txt_lines = []
    html_cards = []

    fetched_count = 0
    for page in range(1, max_pages + 1):
        set_new_proxy()
        url = f'https://mostaql.com/projects?page={page}&sort=latest'
        msg = f"--- Fetching API page {page}/{max_pages} ---"
        print(msg)
        if progress_callback: progress_callback(msg)
        
        try:
            response = requests_session.get(url, timeout=15)
            if response.status_code != 200:
                msg = f"Blocked or error on API page {page} (Status code {response.status_code})."
                print(msg)
                if progress_callback: progress_callback(msg)
                break
                
            data = response.json()
            collection = data.get('collection', [])
            
            if not collection:
                msg = "No more projects found on this page."
                print(msg)
                if progress_callback: progress_callback(msg)
                break
                
            for item in collection:
                if fetched_count >= num_target:
                    break
                    
                offer_id = item.get('id')
                if not offer_id:
                    continue
                
                msg = f"[{fetched_count}/{num_target}] Checking project {offer_id}..."
                print(msg)
                if progress_callback: progress_callback(msg)
                
                # Fetch full project page exactly like the main.py script
                set_new_proxy()
                proj_url = f"https://mostaql.com/project/{offer_id}"
                try:
                    proj_resp = requests_session.get(proj_url, timeout=15)
                    soup = BeautifulSoup(proj_resp.text, 'html.parser')
                    
                    category_el = soup.find_all('li', {'class': 'breadcrumb-item'})
                    category = category_el[-1].text.strip() if category_el else 'N/A'
                    
                    title_el = soup.find('h1')
                    title = title_el.text.strip() if title_el else 'N/A'
                    
                    budget_label = soup.find(lambda tag: tag.name == 'div' and 'الميزانية' in tag.text and len(tag.text) < 50)
                    price = budget_label.parent.text.replace('الميزانية', '').strip() if budget_label else 'N/A'
                    
                    owner_el = soup.find('a', class_='profile__name') or soup.find('bdi')
                    owner = owner_el.text.strip() if owner_el else 'N/A'
                    
                    desc_el = soup.find('div', class_='text-wrapper-div carda__content') or soup.find(id='project-meta-panel')
                    if not desc_el:
                        desc_el = soup.find('p', class_='project__brief') or soup.find('div', class_='project__brief')
                    description = desc_el.text.strip() if desc_el else 'No details found.'
                    
                except Exception as e:
                    print(f"Failed to fetch {proj_url}: {e}")
                    category, title, price, owner, description = "N/A", "N/A", "N/A", "N/A", "N/A"

                category = clean_text(category)
                title = clean_text(title)
                price = clean_text(price)
                owner = clean_text(owner)
                description = clean_text(description)

                # Skip projects that aren't in one of the two allowed categories
                if category not in ALLOWED_CATEGORIES:
                    time.sleep(1.5)
                    continue

                # Format for TXT file
                all_txt_lines.append(f"Title: {title}")
                all_txt_lines.append(f"Category: {category}")
                all_txt_lines.append(f"Budget: {price}")
                all_txt_lines.append(f"Owner: {owner}")
                all_txt_lines.append(f"Details: {description}")
                all_txt_lines.append("-" * 70)
                
                # Format for HTML file
                html_cards.append(f'''
                <div class="project-row">
                    <h2><a href="{proj_url}" target="_blank">{title}</a></h2>
                    <ul class="text-muted">
                        <li><strong>المجال:</strong> {category}</li>
                        <li><strong>الميزانية:</strong> {price}</li>
                        <li><strong>صاحب المشروع:</strong> {owner}</li>
                    </ul>
                    <div class="project__brief">{description}</div>
                </div>
                ''')
                
                fetched_count += 1
                msg = f"[{fetched_count}/{num_target}] Matched: {title}"
                print(msg)
                if progress_callback: progress_callback(msg)
                
                # Crucial sleep to prevent IP bans while mass-scraping individual pages
                time.sleep(1.5)
                
        except Exception as e:
            msg = f"Error fetching API page {page}: {e}"
            print(msg)
            if progress_callback: progress_callback(msg)
            break
            
        if fetched_count >= num_target:
            break
            
    msg = f"\nSuccessfully fetched {fetched_count} projects."
    print(msg)
    if progress_callback: progress_callback(msg)
    
    html_content = f'''<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>Mostaql Projects</title>
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
        .project-row {{ background: white; margin-bottom: 20px; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        a {{ text-decoration: none; color: #2386c8; font-size: 18px; font-weight: bold; }}
        .text-muted {{ color: #777; font-size: 14px; margin-top: 10px; margin-bottom: 15px; border-bottom: 1px solid #eee; padding-bottom: 10px; }}
        .project__brief {{ color: #333; line-height: 1.6; white-space: pre-wrap; }}
        ul {{ padding-left: 0; list-style: none; margin: 0; }}
        li {{ display: inline-block; margin-left: 20px; }}
    </style>
</head>
<body>
    <h1>أحدث {fetched_count} مشروع مستقل (بالتفاصيل الكاملة)</h1>
    {"".join(html_cards)}
</body>
</html>'''

    return html_content

if __name__ == "__main__":
    try:
        num = int(input("How many recent projects do you want to fetch? (e.g. 50): "))
    except ValueError:
        num = 25
    html_out = run_bulk_scrape(num, use_tor=False)
    with open('bulk_projects.html', 'w', encoding='utf-8') as f:
        f.write(html_out)
    print("Done! Saved to bulk_projects.html")
