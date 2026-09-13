import sqlite3
import dataclasses

@dataclasses.dataclass
class Offer:
    offer_id: int
    category: str
    title: str
    price: str
    project_owner: str
    description: str = ""

def init_db():
    conn = sqlite3.connect("mostaql_offers.db")
    cursor = conn.cursor()
    # Matches the table created by SQLModel in the original script
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS offer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id INTEGER NOT NULL UNIQUE,
            category TEXT,
            title TEXT,
            price TEXT,
            project_owner TEXT
        )
    ''')
    conn.commit()
    conn.close()

def offer_exists(offer_id: int) -> bool:
    conn = sqlite3.connect("mostaql_offers.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM offer WHERE offer_id = ?", (offer_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def add_offer(offer: Offer):
    conn = sqlite3.connect("mostaql_offers.db")
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO offer (offer_id, category, title, price, project_owner)
            VALUES (?, ?, ?, ?, ?)
        ''', (offer.offer_id, offer.category, offer.title, offer.price, offer.project_owner))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Already exists
    finally:
        conn.close()
