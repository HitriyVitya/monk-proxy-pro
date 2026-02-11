import sqlite3

DB_NAME = "vpn_storage.db"

def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

def init_proxy_db():
    conn = get_connection(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS vpn_proxies (
            url TEXT PRIMARY KEY, type TEXT, country TEXT, 
            tier INTEGER DEFAULT 3, 
            latency INTEGER DEFAULT 9999,
            fails INTEGER DEFAULT 0, 
            last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'auto')''')
    conn.commit(); conn.close()

def save_proxy_batch(proxies_list, source='auto', tier_dict=None):
    """
    proxies_list: список URL
    tier_dict: {url: tier} если данные с компа
    """
    conn = get_connection(); c = conn.cursor()
    for url in proxies_list:
        try:
            proto = url.split("://")[0]
            if source == 'pc':
                t = tier_dict.get(url, 3)
                # Если с компа - сбрасываем фейлы и ставим статус элиты
                c.execute("""INSERT INTO vpn_proxies (url, type, tier, source, fails) 
                             VALUES (?, ?, ?, 'pc', 0)
                             ON CONFLICT(url) DO UPDATE SET source='pc', tier=?, fails=0""", 
                             (url, proto, t, t))
            else:
                # Если пылесос - добавляем только новых
                c.execute("INSERT OR IGNORE INTO vpn_proxies (url, type, source) VALUES (?, ?, 'auto')", (url, proto))
        except: pass
    conn.commit(); conn.close()

def get_proxies_to_check(limit=150):
    conn = get_connection(); c = conn.cursor()
    # Проверяем тех, кто давно не чекался. Элиту чекаем чаще.
    c.execute("SELECT url FROM vpn_proxies WHERE fails < 20 ORDER BY last_check ASC LIMIT ?", (limit,))
    rows = [r[0] for r in c.fetchall()]
    conn.close(); return rows

def update_proxy_status(url, latency, country):
    conn = get_connection(); c = conn.cursor()
    if latency is not None:
        c.execute("UPDATE vpn_proxies SET latency=?, country=?, fails=0, last_check=CURRENT_TIMESTAMP WHERE url=?", (latency, country, url))
    else:
        c.execute("UPDATE vpn_proxies SET fails = fails + 1, last_check=CURRENT_TIMESTAMP WHERE url=?", (url,))
    conn.commit(); conn.close()

def get_best_proxies_for_sub(total_limit=1000):
    """Самая умная выборка с квотами"""
    conn = get_connection(); c = conn.cursor()
    
    # Сначала берем всё живое (fails < 3) и быстрое
    # Приоритет: 1. Tier (1-2-3) 2. Source (pc выше auto) 3. Latency
    c.execute("""
        SELECT url, latency, tier, country, source FROM vpn_proxies 
        WHERE fails < 3 AND latency < 3500
        ORDER BY tier ASC, 
                 CASE WHEN source = 'pc' THEN 0 ELSE 1 END ASC, 
                 latency ASC 
        LIMIT ?
    """, (total_limit,))
    
    rows = c.fetchall()
    conn.close()
    return rows
