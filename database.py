import sqlite3
import datetime

DB_NAME = "iron_monk.db"

def get_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    """Инициализация таблиц для КАЧАЛКИ"""
    conn = get_connection()
    c = conn.cursor()
    
    # Таблицы качалки
    c.execute('''CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER,
            date TEXT,
            weight REAL DEFAULT 0,
            calories_in INTEGER DEFAULT 0,
            calories_out INTEGER DEFAULT 0,
            steps_count INTEGER DEFAULT 0,
            daily_deficit_limit INTEGER DEFAULT NULL,
            PRIMARY KEY (user_id, date)
        )''')
    c.execute('''CREATE TABLE IF NOT EXISTS food_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            kcal INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
            user_id INTEGER PRIMARY KEY,
            target_deficit INTEGER DEFAULT 600
        )''')
    
    # Миграции (на всякий случай)
    try: c.execute("ALTER TABLE stats ADD COLUMN steps_count INTEGER DEFAULT 0")
    except: pass
    try: c.execute("ALTER TABLE stats ADD COLUMN daily_deficit_limit INTEGER DEFAULT NULL")
    except: pass
            
    conn.commit()
    conn.close()

def init_proxy_db():
    """Инициализация таблиц для ПРОКСИ (Этой функции у тебя не хватало!)"""
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS vpn_proxies (
            url TEXT PRIMARY KEY, 
            type TEXT, 
            country TEXT, 
            is_ai INTEGER DEFAULT 0, 
            latency INTEGER DEFAULT 9999,
            fails INTEGER DEFAULT 0,
            last_check TIMESTAMP)''')
    conn.commit()
    conn.close()

# ==========================================
# ФУНКЦИИ ДЛЯ ПРОКСИ
# ==========================================

def save_proxy_batch(proxies_list):
    conn = get_connection()
    c = conn.cursor()
    new_count = 0
    for url in proxies_list:
        try:
            proto = url.split("://")[0]
            c.execute("INSERT OR IGNORE INTO vpn_proxies (url, type, latency) VALUES (?, ?, 9999)", (url, proto))
            if c.rowcount > 0: new_count += 1
        except: pass
    conn.commit()
    conn.close()
    return new_count

def get_proxies_to_check(limit=100):
    conn = get_connection()
    c = conn.cursor()
    # Берем те, что давно не проверялись
    c.execute("""SELECT url FROM vpn_proxies 
                 WHERE fails < 5 
                 ORDER BY last_check ASC LIMIT ?""", (limit,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def update_proxy_status(url, latency, is_ai, country):
    conn = get_connection()
    c = conn.cursor()
    if latency is not None:
        c.execute("""UPDATE vpn_proxies 
                     SET latency=?, is_ai=?, country=?, fails=0, last_check=CURRENT_TIMESTAMP 
                     WHERE url=?""", (latency, is_ai, country, url))
    else:
        c.execute("UPDATE vpn_proxies SET fails = fails + 1, last_check=CURRENT_TIMESTAMP WHERE url=?", (url,))
    conn.commit()
    conn.close()

def get_best_proxies_for_sub():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""SELECT url FROM vpn_proxies 
                 WHERE fails < 3 AND latency < 2000 
                 ORDER BY is_ai DESC, latency ASC LIMIT 1000""")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ==========================================
# ФУНКЦИИ ДЛЯ КАЧАЛКИ
# ==========================================

def add_food(user_id, kcal, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO food_logs (user_id, date, kcal) VALUES (?, ?, ?)", (user_id, date, kcal))
    c.execute('''INSERT INTO stats (user_id, date, calories_in) VALUES (?, ?, ?)
                 ON CONFLICT(user_id, date) DO UPDATE SET calories_in = calories_in + ?''', (user_id, date, kcal, kcal))
    conn.commit()
    conn.close()

def get_food_logs(user_id, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, kcal FROM food_logs WHERE user_id = ? AND date = ?", (user_id, date))
    rows = c.fetchall()
    conn.close()
    return rows

def delete_food_entry(entry_id, user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT kcal, date FROM food_logs WHERE id = ? AND user_id = ?", (entry_id, user_id))
    row = c.fetchone()
    if row:
        kcal, date = row
        c.execute("DELETE FROM food_logs WHERE id = ?", (entry_id,))
        c.execute("UPDATE stats SET calories_in = calories_in - ? WHERE user_id = ? AND date = ?", (kcal, user_id, date))
        conn.commit()
        return True, kcal
    conn.close()
    return False, 0

def update_steps(user_id, total, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT steps_count FROM stats WHERE user_id = ? AND date = ?", (user_id, date))
    row = c.fetchone()
    old = row[0] if row else 0
    diff = total - old
    burn = int(diff * 0.05)
    if row:
        c.execute("UPDATE stats SET steps_count = ?, calories_out = calories_out + ? WHERE user_id = ? AND date = ?", (total, burn, user_id, date))
    else:
        c.execute("INSERT INTO stats (user_id, date, steps_count, calories_out) VALUES (?, ?, ?, ?)", (user_id, date, total, int(total*0.05)))
    conn.commit()
    conn.close()
    return burn

def add_burn(user_id, kcal, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO stats (user_id, date, calories_out) VALUES (?, ?, ?)
                 ON CONFLICT(user_id, date) DO UPDATE SET calories_out = calories_out + ?''', (user_id, date, kcal, kcal))
    conn.commit()
    conn.close()

def set_burn_absolute(user_id, kcal, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO stats (user_id, date, calories_out) VALUES (?, ?, ?)
                 ON CONFLICT(user_id, date) DO UPDATE SET calories_out = ?''', (user_id, date, kcal, kcal))
    conn.commit()
    conn.close()

def update_weight(user_id, weight, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO stats (user_id, date, weight) VALUES (?, ?, ?)
                 ON CONFLICT(user_id, date) DO UPDATE SET weight = ?''', (user_id, date, weight, weight))
    conn.commit()
    conn.close()

def set_global_deficit(user_id, amount):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (user_id, target_deficit) VALUES (?, ?)", (user_id, amount))
    conn.commit()
    conn.close()

def get_global_deficit(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT target_deficit FROM settings WHERE user_id = ?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else 600

def set_daily_deficit(user_id, amount, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO stats (user_id, date, daily_deficit_limit) VALUES (?, ?, ?)
                 ON CONFLICT(user_id, date) DO UPDATE SET daily_deficit_limit = ?''', (user_id, date, amount, amount))
    conn.commit()
    conn.close()

def get_effective_deficit(user_id, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT daily_deficit_limit FROM stats WHERE user_id = ? AND date = ?", (user_id, date))
    res = c.fetchone()
    conn.close()
    if res and res[0] is not None: return res[0]
    return get_global_deficit(user_id)

def get_stats(user_id, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT weight, calories_in, calories_out, steps_count FROM stats WHERE user_id = ? AND date = ?", (user_id, date))
    res = c.fetchone()
    conn.close()
    if res: return {'weight': res[0], 'in': res[1], 'out': res[2], 'steps': res[3]}
    return {'weight': 0, 'in': 0, 'out': 0, 'steps': 0}

def get_history(user_id, days=None):
    conn = get_connection()
    c = conn.cursor()
    query = "SELECT date, weight, calories_in, calories_out, daily_deficit_limit FROM stats WHERE user_id = ? ORDER BY date ASC"
    params = (user_id,)
    if days:
        query = "SELECT date, weight, calories_in, calories_out, daily_deficit_limit FROM stats WHERE user_id = ? ORDER BY date ASC LIMIT ?"
        params = (user_id, days)
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows
