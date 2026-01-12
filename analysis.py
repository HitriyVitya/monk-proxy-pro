import database as db
import pandas as pd

def analyze_period(user_id, days=None):
    # Достаем данные: если days=None, база вернет ВСЁ
    rows = db.get_history(user_id, days)
    
    period_name = f"За последние {days} дней" if days else "За ВСЁ время"
    
    if not rows or len(rows) < 2:
        return "📉 Недостаточно данных для анализа. Нужно хотя бы 2 дня записей."

    df = pd.DataFrame(rows, columns=['date', 'weight', 'in', 'out'])
    
    # Чистим данные
    df['weight'] = pd.to_numeric(df['weight'], errors='coerce')
    df['weight'] = df['weight'].interpolate().bfill() # Заполняем дырки
    
    # --- БАЗОВАЯ МАТЕМАТИКА ---
    first_weight = df.iloc[0]['weight']
    last_weight = df.iloc[-1]['weight']
    min_weight = df['weight'].min()
    max_weight = df['weight'].max()
    
    total_change = last_weight - first_weight
    days_count = len(df)
    
    # --- СРЕДНИЕ ПОКАЗАТЕЛИ ---
    avg_in = df['in'].mean()
    avg_activity = df['out'].mean() # Только активность
    bmr = 1950 # Твоя база
    avg_total_burn_calc = bmr + avg_activity # Расчетный расход
    
    # --- УМНЫЙ TDEE (ОБРАТНЫЙ РАСЧЕТ) ---
    # 1 кг жира = 7700 ккал
    # Мы потеряли X кг. Значит общий дефицит был X * 7700.
    # Реальный TDEE = (Сумма съеденного + Потерянное_в_ккал) / дней
    
    fat_loss_kcal = total_change * 7700 * -1 # Если похудели (-), то это плюс к расходу
    real_tdee = avg_in + (fat_loss_kcal / days_count)
    
    # Разница между тем, что ты думаешь (Калькулятор) и Реальностью
    metabolic_gap = real_tdee - avg_total_burn_calc
    
    # --- ВЫВОДЫ ---
    if total_change < 0:
        trend = "📉 Худеем"
        comment = f"Скинул <b>{abs(total_change):.1f} кг</b> чистого веса."
    elif total_change > 0:
        trend = "📈 Набираем"
        comment = f"Набрал <b>{total_change:.1f} кг</b>."
    else:
        trend = "⚖️ Стоим на месте"
        comment = "Вес стабилен."

    gap_str = ""
    if abs(metabolic_gap) > 200:
        sign = "+" if metabolic_gap > 0 else ""
        gap_str = f"\n(Твой метаболизм работает на <b>{sign}{metabolic_gap:.0f} ккал</b> от расчетного!)"

    text = (
        f"🧠 <b>АНАЛИЗ: {period_name}</b>\n"
        f"<i>(Дней в отчете: {days_count})</i>\n\n"
        
        f"{trend}: {first_weight:.1f} -> <b>{last_weight:.1f} кг</b>\n"
        f"{comment}\n"
        f"Минимум был: {min_weight:.1f} | Максимум: {max_weight:.1f}\n\n"
        
        f"📊 <b>Средние цифры:</b>\n"
        f"🍔 Ел: <b>{avg_in:.0f}</b> ккал\n"
        f"🔥 Активность: <b>{avg_activity:.0f}</b> ккал\n\n"
        
        f"🕵️‍♂️ <b>Детектив TDEE:</b>\n"
        f"Твой реальный расход: <b>~{real_tdee:.0f} ккал</b>"
        f"{gap_str}"
    )
    
    return text