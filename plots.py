import matplotlib.pyplot as plt
import io
import pandas as pd
import matplotlib

# Настраиваем стиль "Киберпанк"
plt.style.use('dark_background')
# Принудительно ставим шрифт, который есть в Windows, чтобы русские буквы не ломались
matplotlib.rc('font', family='Arial')

def create_progress_chart(data):
    """
    Принимает данные из БД.
    Рисует картинку и возвращает её как файл (байты).
    """
    if not data:
        return None

    # 1. Превращаем данные в таблицу
    df = pd.DataFrame(data, columns=['date', 'weight', 'in', 'out'])
    
    # --- ФИКС ДАННЫХ ---
    df['weight'] = pd.to_numeric(df['weight'], errors='coerce')
    # Заменяем 0 и None на "числовую пустоту" (nan)
    df.loc[df['weight'] <= 0, 'weight'] = float('nan')
    
    # Интерполяция (соединяем точки)
    df['weight'] = df['weight'].interpolate(method='linear')
    # Заполняем начало, если первый день был без веса
    df['weight'] = df['weight'].bfill()
    
    # Формат даты ДД.ММ
    df['date_str'] = pd.to_datetime(df['date']).dt.strftime('%d.%m')

    # Создаем холст
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    
    # --- ГРАФИК 1: ВЕС ---
    if df['weight'].notna().any():
        # Убрали эмодзи из label
        ax1.plot(df['date_str'], df['weight'], color='#00ffcc', marker='o', linewidth=2, label='Вес (кг)')
        
        # Подписи значений
        for i, val in enumerate(df['weight']):
            if pd.notna(val):
                ax1.annotate(f"{val:.1f}", (i, val), 
                             xytext=(0, 10), textcoords='offset points', ha='center', color='white', fontsize=9)
    else:
        ax1.text(0.5, 0.5, "Внеси вес, чтобы увидеть график", ha='center', va='center', color='gray')

    # Убрали эмодзи из заголовка
    ax1.set_title('Динамика Веса', fontsize=14, color='white')
    ax1.grid(color='#444444', linestyle='--', linewidth=0.5)
    ax1.legend(loc='upper left')
    
    # --- ГРАФИК 2: КАЛОРИИ ---
    bmr = 1950 
    total_burn = bmr + df['out']
    
    # Убрали эмодзи из label
    bars = ax2.bar(df['date_str'], df['in'], color='#ff9900', alpha=0.7, label='Съел')
    ax2.plot(df['date_str'], total_burn, color='#00ff00', linestyle='--', linewidth=2, label='Расход')
    
    # Убрали эмодзи из заголовка
    ax2.set_title('Еда vs Расход', fontsize=14, color='white')
    ax2.grid(color='#444444', linestyle='--', linewidth=0.5)
    ax2.legend(loc='upper left')

    # Раскраска
    for i, bar in enumerate(bars):
        if df['in'][i] > total_burn[i]:
            bar.set_color('#ff4444') 
        else:
            bar.set_color('#44ff44') 

    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    
    return buf