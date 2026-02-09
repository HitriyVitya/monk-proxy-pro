import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BufferedInputFile, FSInputFile

# --- МОДУЛИ ---
import database as db          # База качалки
import database_vpn as vpn_db  # База прокси
import plots                   # Графики
import analysis                # Анализ веса
import keep_alive              # Веб-сервер + Подписка
import proxy_vacuum            # Пылесос

# --- НАСТРОЙКИ ---
TOKEN = "8349554668:AAHX4Fk76PFTVHrlxPTl7TTvcWds-kb6tEs"
USER_TIMEZONE = 3

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_today_str():
    offset = timezone(timedelta(hours=USER_TIMEZONE))
    return datetime.now(offset).strftime("%Y-%m-%d")

def format_date_user(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.strftime("%d.%m.%Y")

async def get_working_date(state: FSMContext):
    data = await state.get_data()
    return data.get("selected_date", get_today_str())

# --- FSM ---
class Form(StatesGroup):
    waiting_for_food = State()
    waiting_for_weight = State()
    waiting_for_steps = State()
    waiting_for_gym = State()
    waiting_for_date = State()
    waiting_for_deficit_global = State()
    waiting_for_deficit_day = State()
    waiting_for_fix_burn = State()

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    kb = [
        [KeyboardButton(text="🍔 Внести еду"), KeyboardButton(text="⚖️ Внести вес")],
        [KeyboardButton(text="👣 Внести шаги"), KeyboardButton(text="🏋️‍♂️ Внести треню")],
        [KeyboardButton(text="✏️ Редактировать"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="📈 Графики"), KeyboardButton(text="🧠 Анализ")],
        [KeyboardButton(text="⚙️ Дефицит"), KeyboardButton(text="📅 Другая дата")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_deficit_menu():
    kb = [
        [KeyboardButton(text="🌍 Изменить ОБЩИЙ дефицит")],
        [KeyboardButton(text="📅 Изменить для ЭТОГО ДНЯ")],
        [KeyboardButton(text="🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_edit_menu():
    kb = [
        [KeyboardButton(text="❌ Удалить запись еды")],
        [KeyboardButton(text="🔥 Исправить Активность (Итог)")],
        [KeyboardButton(text="🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_analysis_keyboard():
    kb = [
        [InlineKeyboardButton(text="📅 7 Дней", callback_data="anal_7")],
        [InlineKeyboardButton(text="🗓 30 Дней", callback_data="anal_30")],
        [InlineKeyboardButton(text="♾ За всё время", callback_data="anal_all")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- ХЭНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    db.init_db()
    await state.update_data(selected_date=get_today_str())
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Меню"),
        BotCommand(command="stats", description="📊 Отчет"),
        BotCommand(command="export", description="💾 Бэкап")
    ])
    await message.answer(
        "💪 <b>Монах V7.0 (Ultimate)</b>.\n"
        "Слежу за фигурой и держу ВПН в тонусе.", 
        parse_mode="HTML", 
        reply_markup=get_main_keyboard()
    )

# --- ЭКСПОРТ (ДВЕ БАЗЫ) ---
@dp.message(Command("export"))
async def export_db(message: types.Message):
    await message.answer("📦 Пакую базы...")
    try:
        await message.reply_document(FSInputFile("iron_monk.db"), caption="💾 Данные Качалки")
        await message.reply_document(FSInputFile("vpn_storage.db"), caption="🌐 База Прокси")
    except Exception as e:
        await message.answer(f"Ошибка экспорта (возможно база пустая): {e}")

# --- ИМПОРТ (ВОССТАНОВЛЕНИЕ) ---
@dp.message(F.document)
async def import_db(message: types.Message):
    fname = message.document.file_name
    if fname in ["iron_monk.db", "vpn_storage.db"]:
        await message.answer(f"📥 Загружаю {fname}...")
        try:
            file_id = message.document.file_id
            file = await bot.get_file(file_id)
            await bot.download_file(file.file_path, fname)
            await message.answer("✅ База обновлена!", parse_mode="HTML")
        except Exception as e:
            await message.answer(f"Ошибка: {e}")
    else:
        await message.answer("Кидай файл 'iron_monk.db' или 'vpn_storage.db'")

# --- АНАЛИЗ ---
@dp.message(F.text == "🧠 Анализ")
async def analysis_menu(message: types.Message):
    await message.answer("Выбери период:", reply_markup=get_analysis_keyboard())

@dp.callback_query(F.data.startswith("anal_"))
async def process_analysis(callback: CallbackQuery):
    code = callback.data.split("_")[1]
    days = None 
    if code == "7": days = 7
    elif code == "30": days = 30
    
    try: await callback.message.edit_text("⏳ Считаю...")
    except: pass
    
    try:
        report = analysis.analyze_period(callback.from_user.id, days)
        await callback.message.edit_text(report, parse_mode="HTML")
    except Exception as e:
        await callback.message.edit_text(f"Ошибка анализа: {e}")
    await callback.answer()

# --- ГРАФИКИ ---
@dp.message(F.text == "📈 Графики")
async def show_charts(message: types.Message):
    wait_msg = await message.answer("🎨 Рисую...")
    data = db.get_history(message.from_user.id, 30)
    if not data:
        await wait_msg.edit_text("Нет данных.")
        return
    photo_file = plots.create_progress_chart(data)
    if photo_file:
        await message.reply_photo(photo=BufferedInputFile(photo_file.read(), filename="chart.png"))
        await wait_msg.delete()
    else:
        await wait_msg.edit_text("Ошибка рисования.")

# --- ЕДА ---
@dp.message(F.text == "🍔 Внести еду")
async def food_start(message: types.Message, state: FSMContext):
    date = await get_working_date(state)
    await message.answer(f"📅 [{format_date_user(date)}] Ккал:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_food)

@dp.message(Form.waiting_for_food)
async def food_process(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        val = int(message.text)
        date = await get_working_date(state)
        db.add_food(message.from_user.id, val, date)
        stats = db.get_stats(message.from_user.id, date)
        await message.answer(f"➕ Записал <b>{val}</b>. Итого: <b>{stats['in']}</b>", parse_mode="HTML", reply_markup=get_main_keyboard())
        await state.set_state(None)
    else: await message.answer("Цифрами.")

# --- ВЕС ---
@dp.message(F.text == "⚖️ Внести вес")
async def weight_start(message: types.Message, state: FSMContext):
    date = await get_working_date(state)
    await message.answer(f"📅 [{format_date_user(date)}] Вес:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_weight)

@dp.message(Form.waiting_for_weight)
async def weight_process(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        date = await get_working_date(state)
        db.update_weight(message.from_user.id, val, date)
        await message.answer(f"✅ Вес <b>{val}</b>.", parse_mode="HTML", reply_markup=get_main_keyboard())
        await state.set_state(None)
    except: await message.answer("Числом.")

# --- ШАГИ ---
@dp.message(F.text == "👣 Внести шаги")
async def steps_start(message: types.Message, state: FSMContext):
    date = await get_working_date(state)
    stats = db.get_stats(message.from_user.id, date)
    cur = stats['steps'] if stats['steps'] else 0
    await message.answer(f"Сейчас: <b>{cur}</b>\nВведи ИТОГ:", parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_steps)

@dp.message(Form.waiting_for_steps)
async def steps_process(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        new_total = int(message.text)
        date = await get_working_date(state)
        added = db.update_steps(message.from_user.id, new_total, date)
        msg = f"👣 Шаги: <b>{new_total}</b> ({added:+} ккал)."
        await message.answer(msg, parse_mode="HTML", reply_markup=get_main_keyboard())
        await state.set_state(None)
    else: await message.answer("Цифрами.")

# --- ТРЕНЯ ---
@dp.message(F.text == "🏋️‍♂️ Внести треню")
async def gym_start(message: types.Message, state: FSMContext):
    await message.answer("Ккал:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_gym)

@dp.message(Form.waiting_for_gym)
async def gym_process(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        val = int(message.text)
        date = await get_working_date(state)
        db.add_burn(message.from_user.id, val, date)
        await message.answer(f"🔥 Треня +{val}.", reply_markup=get_main_keyboard())
        await state.set_state(None)

# --- РЕДАКТИРОВАНИЕ ---
@dp.message(F.text == "✏️ Редактировать")
async def edit_start(message: types.Message):
    await message.answer("Меню правок:", reply_markup=get_edit_menu())

@dp.message(F.text == "❌ Удалить запись еды")
async def delete_food_start(message: types.Message, state: FSMContext):
    date = await get_working_date(state)
    logs = db.get_food_logs(message.from_user.id, date)
    if not logs:
        await message.answer("Записей нет.", reply_markup=get_main_keyboard())
        return
    buttons = [[InlineKeyboardButton(text=f"❌ {l[1]} ккал", callback_data=f"del_food_{l[0]}")] for l in logs]
    await message.answer(f"История {format_date_user(date)}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("del_food_"))
async def process_food_delete(callback: CallbackQuery):
    log_id = int(callback.data.split("_")[2])
    success, val = db.delete_food_entry(log_id, callback.from_user.id)
    if success: await callback.message.edit_text(f"✅ Удалил <b>{val}</b>.", parse_mode="HTML")
    else: await callback.message.edit_text("Ошибка.")
    await callback.answer()

@dp.message(F.text == "🔥 Исправить Активность (Итог)")
async def fix_burn_start(message: types.Message, state: FSMContext):
    await message.answer("Введи верный ИТОГ (Шаги + Треня):", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_fix_burn)

@dp.message(Form.waiting_for_fix_burn)
async def fix_burn_process(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        val = int(message.text)
        date = await get_working_date(state)
        db.set_burn_absolute(message.from_user.id, val, date)
        await message.answer("✅ Исправлено.", reply_markup=get_main_keyboard())
        await state.set_state(None)
    else: await message.answer("Цифрами.")

# --- ДЕФИЦИТ ---
@dp.message(F.text == "⚙️ Дефицит")
async def deficit_menu_start(message: types.Message):
    await message.answer("Настройки:", reply_markup=get_deficit_menu())

@dp.message(F.text == "🌍 Изменить ОБЩИЙ дефицит")
async def deficit_global_start(message: types.Message, state: FSMContext):
    current = db.get_effective_deficit(message.from_user.id, "check")
    await message.answer(f"Текущий: -{current}. Новый:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_deficit_global)

@dp.message(Form.waiting_for_deficit_global)
async def deficit_global_process(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        db.set_global_deficit(message.from_user.id, int(message.text))
        await message.answer(f"✅ Общий: -{message.text}", reply_markup=get_main_keyboard())
        await state.set_state(None)

@dp.message(F.text == "📅 Изменить для ЭТОГО ДНЯ")
async def deficit_day_start(message: types.Message, state: FSMContext):
    date = await get_working_date(state)
    await message.answer(f"Дефицит для {format_date_user(date)}:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_deficit_day)

@dp.message(Form.waiting_for_deficit_day)
async def deficit_day_process(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        date = await get_working_date(state)
        db.set_daily_deficit(message.from_user.id, int(message.text), date)
        await message.answer(f"✅ Для {format_date_user(date)}: -{message.text}", reply_markup=get_main_keyboard())
        await state.set_state(None)

# --- СТАТИСТИКА ---
@dp.message(F.text == "📊 Статистика")
async def stats_view(message: types.Message, state: FSMContext):
    date = await get_working_date(state)
    stats = db.get_stats(message.from_user.id, date)
    eff_deficit = db.get_effective_deficit(message.from_user.id, date)
    bmr = 1950
    total_burn = bmr + stats['out']
    allowed = total_burn - eff_deficit
    rem = allowed - stats['in']
    emoji = "🟢" if rem >= 0 else "🔴"
    label = f"{format_date_user(date)}"
    if date == get_today_str(): label += " (Сегодня)"
    
    text = (
        f"📅 <b>ОТЧЕТ {label}:</b>\n"
        f"🔥 Расход: <b>{stats['out']}</b> (+{bmr} база)\n"
        f"🛡 Дефицит: <b>-{eff_deficit}</b>\n"
        f"🍽 Лимит: <b>{allowed}</b>\n"
        f"🍔 Съел: <b>{stats['in']}</b>\n"
        f"👉 <b>Остаток: {emoji} {rem}</b>\n"
        f"⚖️ Вес: <b>{stats['weight']}</b>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())

# --- ДРУГАЯ ДАТА ---
@dp.message(F.text == "📅 Другая дата")
async def change_date_start(message: types.Message, state: FSMContext):
    await message.answer("Дата (ДД.ММ):", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_date)

@dp.message(Form.waiting_for_date)
async def change_date_process(message: types.Message, state: FSMContext):
    try:
        t = message.text.strip()
        y = datetime.now().year
        d_sql = datetime.strptime(f"{t}.{y}" if len(t)==5 else t, "%d.%m.%Y").strftime("%Y-%m-%d")
        await state.update_data(selected_date=d_sql)
        await message.answer(f"✅ Дата: {t}", reply_markup=get_main_keyboard())
        await state.set_state(None)
    except: await message.answer("Формат ДД.ММ")

@dp.message(F.text == "🔙 Назад")
async def back_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню", reply_markup=get_main_keyboard())

# -----------------------------------------------------------
# ЗАПУСК ВСЕГО
# -----------------------------------------------------------
async def main():
    print("🚀 Инициализация Качалки...")
    db.init_db()
    
    print("🚀 Инициализация Прокси-Базы...")
    vpn_db.init_proxy_db()
    
    print("🚀 Запуск Веб-сервера (Подписка + AntiSleep)...")
    asyncio.create_task(keep_alive.start_server())
    
    print("🚀 Запуск ВПН-Пылесоса (Фоновый режим)...")
    asyncio.create_task(proxy_vacuum.vacuum_job())
    
    print("🚀 Запуск Бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("Офф.")
