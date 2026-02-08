import sqlite3
import json

DB_NAME = "proxies_pro.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS proxies
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  url TEXT UNIQUE,
                  type TEXT,
                  country TEXT,
                  is_ai INTEGER DEFAULT 0,
                  fails INTEGER DEFAULT 0,
                  last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def add_proxies(links):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    for link in links:
        try:
            c.execute("INSERT OR IGNORE INTO proxies (url, type) VALUES (?, ?)", 
                      (link, link.split('://')[0]))
        except: pass
    conn.commit()
    conn.close()

def get_all_for_check():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, url FROM proxies WHERE fails < 5") # Не проверяем совсем дохлых
    rows = c.fetchall()
    conn.close()
    return rows

def update_status(proxy_id, is_live, is_ai=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if is_live:
        c.execute("UPDATE proxies SET fails = 0, is_ai = ?, last_seen = CURRENT_TIMESTAMP WHERE id = ?", (is_ai, proxy_id))
    else:
        c.execute("UPDATE proxies SET fails = fails + 1 WHERE id = ?", (proxy_id,))
    conn.commit()
    conn.close()
