import sqlite3
import datetime

DB_NAME = "iron_monk.db"

def get_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # 1. Основная статистика (Добавили daily_deficit_limit)
    c.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER,
            date TEXT,
            weight REAL DEFAULT 0,
            calories_in INTEGER DEFAULT 0,
            calories_out INTEGER DEFAULT 0,
            steps_count INTEGER DEFAULT 0,
            daily_deficit_limit INTEGER DEFAULT NULL,
            PRIMARY KEY (user_id, date)
        )
    ''')
    
    # 2. История еды (Новая таблица!)
    c.execute('''
        CREATE TABLE IF NOT EXISTS food_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            kcal INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 3. Общие настройки
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            user_id INTEGER PRIMARY KEY,
            target_deficit INTEGER DEFAULT 600
        )
    ''')
    
    # --- МИГРАЦИИ (ЧТОБЫ НЕ СЛОМАТЬ СТАРУЮ БАЗУ) ---
    try:
        c.execute("ALTER TABLE stats ADD COLUMN steps_count INTEGER DEFAULT 0")
    except: pass
    
    try:
        c.execute("ALTER TABLE stats ADD COLUMN daily_deficit_limit INTEGER DEFAULT NULL")
    except: pass
        
    conn.commit()
    conn.close()

# --- ЕДА С ИСТОРИЕЙ ---
def add_food(user_id, kcal, date):
    conn = get_connection()
    c = conn.cursor()
    
    # 1. Добавляем запись в лог (историю)
    c.execute("INSERT INTO food_logs (user_id, date, kcal) VALUES (?, ?, ?)", (user_id, date, kcal))
    
    # 2. Обновляем общую сумму дня
    c.execute('''
        INSERT INTO stats (user_id, date, calories_in) VALUES (?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET calories_in = calories_in + ?
    ''', (user_id, date, kcal, kcal))
    
    conn.commit()
    conn.close()

def get_food_logs(user_id, date):
    """Возвращает список записей еды за день"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, kcal FROM food_logs WHERE user_id = ? AND date = ?", (user_id, date))
    rows = c.fetchall() # Вернет список [(1, 500), (2, 300)...]
    conn.close()
    return rows

def delete_food_entry(entry_id, user_id):
    """Удаляет конкретную запись и пересчитывает сумму"""
    conn = get_connection()
    c = conn.cursor()
    
    # Сначала узнаем, сколько там было калорий и какая дата
    c.execute("SELECT kcal, date FROM food_logs WHERE id = ? AND user_id = ?", (entry_id, user_id))
    row = c.fetchone()
    
    if row:
        kcal_to_remove = row[0]
        date = row[1]
        
        # Удаляем из лога
        c.execute("DELETE FROM food_logs WHERE id = ?", (entry_id,))
        
        # Вычитаем из общей статистики
        c.execute("UPDATE stats SET calories_in = calories_in - ? WHERE user_id = ? AND date = ?", 
                  (kcal_to_remove, user_id, date))
        
        conn.commit()
        return True, kcal_to_remove
    
    conn.close()
    return False, 0

# --- ДЕФИЦИТ ---
def set_global_deficit(user_id, amount):
    """Общая настройка"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (user_id, target_deficit) VALUES (?, ?)", (user_id, amount))
    conn.commit()
    conn.close()

def set_daily_deficit(user_id, amount, date):
    """Настройка ТОЛЬКО для этого дня"""
    conn = get_connection()
    c = conn.cursor()
    # Создаем запись дня если нет, и обновляем лимит
    c.execute('''
        INSERT INTO stats (user_id, date, daily_deficit_limit) VALUES (?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET daily_deficit_limit = ?
    ''', (user_id, date, amount, amount))
    conn.commit()
    conn.close()

def get_effective_deficit(user_id, date):
    """Самая умная функция: берет личный лимит дня, а если нет - общий"""
    conn = get_connection()
    c = conn.cursor()
    
    # 1. Пробуем найти лимит на день
    c.execute("SELECT daily_deficit_limit FROM stats WHERE user_id = ? AND date = ?", (user_id, date))
    day_res = c.fetchone()
    
    # 2. Если нашли и он не NULL - возвращаем его
    if day_res and day_res[0] is not None:
        conn.close()
        return day_res[0]
    
    # 3. Иначе берем общий из настроек
    c.execute("SELECT target_deficit FROM settings WHERE user_id = ?", (user_id,))
    global_res = c.fetchone()
    conn.close()
    
    return global_res[0] if global_res else 600

# --- ОСТАЛЬНОЕ (КАК БЫЛО) ---
def update_steps(user_id, current_steps_total, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT steps_count, calories_out FROM stats WHERE user_id = ? AND date = ?", (user_id, date))
    row = c.fetchone()
    if row:
        old_steps = row[0] if row[0] else 0
        diff_steps = current_steps_total - old_steps
        diff_burn = int(diff_steps * 0.05)
        c.execute("UPDATE stats SET steps_count = ?, calories_out = calories_out + ? WHERE user_id = ? AND date = ?", 
                  (current_steps_total, diff_burn, user_id, date))
    else:
        burn = int(current_steps_total * 0.05)
        c.execute("INSERT INTO stats (user_id, date, steps_count, calories_out) VALUES (?, ?, ?, ?)", 
                  (user_id, date, current_steps_total, burn))
    conn.commit()
    conn.close()
    if row: return int((current_steps_total - (row[0] if row[0] else 0)) * 0.05)
    else: return int(current_steps_total * 0.05)

def add_burn(user_id, kcal, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO stats (user_id, date, calories_out) VALUES (?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET calories_out = calories_out + ?
    ''', (user_id, date, kcal, kcal))
    conn.commit()
    conn.close()

def update_weight(user_id, weight, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO stats (user_id, date, weight) VALUES (?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET weight = ?
    ''', (user_id, date, weight, weight))
    conn.commit()
    conn.close()

def set_burn_absolute(user_id, kcal, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO stats (user_id, date, calories_out) VALUES (?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET calories_out = ?
    ''', (user_id, date, kcal, kcal))
    conn.commit()
    conn.close()

def get_stats(user_id, date):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT weight, calories_in, calories_out, steps_count FROM stats WHERE user_id = ? AND date = ?", (user_id, date))
    result = c.fetchone()
    conn.close()
    if result:
        return {'weight': result[0], 'in': result[1], 'out': result[2], 'steps': result[3]}
    return {'weight': 0, 'in': 0, 'out': 0, 'steps': 0}
def get_history(user_id, days=None):
    """
    Достает статистику. 
    days=30 -> последние 30 дней.
    days=None -> ВСЯ история с начала времен.
    """
    conn = get_connection()
    c = conn.cursor()
    
    query = "SELECT date, weight, calories_in, calories_out FROM stats WHERE user_id = ? ORDER BY date ASC"
    params = (user_id,)
    
    if days is not None:
        query = "SELECT date, weight, calories_in, calories_out FROM stats WHERE user_id = ? ORDER BY date ASC LIMIT ?"
        params = (user_id, days)
        
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows