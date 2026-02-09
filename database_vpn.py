import sqlite3

DB_NAME = "vpn_storage.db"

def get_connection():
    return sqlite3.connect(DB_NAME)

def init_proxy_db():
    conn = get_connection()
    c = conn.cursor()
    # Создаем таблицу со всеми нужными полями
    c.execute('''CREATE TABLE IF NOT EXISTS vpn_proxies (
            url TEXT PRIMARY KEY, 
            type TEXT, 
            country TEXT, 
            is_ai INTEGER DEFAULT 0, 
            latency INTEGER DEFAULT 9999,
            fails INTEGER DEFAULT 0,
            last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def save_proxy_batch(proxies_list):
    conn = get_connection()
    c = conn.cursor()
    new_count = 0
    for url in proxies_list:
        try:
            proto = url.split("://")[0]
            c.execute("INSERT OR IGNORE INTO vpn_proxies (url, type) VALUES (?, ?)", (url, proto))
            if c.rowcount > 0: new_count += 1
        except: pass
    conn.commit()
    conn.close()
    return new_count

def get_proxies_to_check(limit=100):
    conn = get_connection()
    c = conn.cursor()
    # Берем те, что давно не проверялись или новые (latency 9999)
    c.execute("SELECT url FROM vpn_proxies WHERE fails < 5 ORDER BY last_check ASC LIMIT ?", (limit,))
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows

def update_proxy_status(url, latency, is_ai, country):
    """Обновленная функция: принимает 4 аргумента!"""
    conn = get_connection()
    c = conn.cursor()
    if latency is not None:
        # Если сервер живой
        c.execute("""UPDATE vpn_proxies 
                     SET latency=?, is_ai=?, country=?, fails=0, last_check=CURRENT_TIMESTAMP 
                     WHERE url=?""", (latency, is_ai, country, url))
    else:
        # Если сервер мертвый
        c.execute("UPDATE vpn_proxies SET fails = fails + 1, last_check=CURRENT_TIMESTAMP WHERE url=?", (url,))
    conn.commit()
    conn.close()

def get_best_proxies_for_sub():
    conn = get_connection()
    c = conn.cursor()
    # Отдаем только живых (latency < 9999)
    c.execute("""SELECT url FROM vpn_proxies 
                 WHERE fails < 3 AND latency < 2500 
                 ORDER BY is_ai DESC, latency ASC LIMIT 1000""")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows
