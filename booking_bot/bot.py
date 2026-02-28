"""
Telegram Bot для записи на услуги
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from config import (
    BOT_TOKEN, ADMIN_ID, SERVICES, WORK_HOURS, 
    WORK_DAYS, DAYS_AHEAD, SLOT_INTERVAL, TIMEZONE
)
from database import Database

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize database
db = Database("./booking.db")

# Bot initialization
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)


# ---------- FSM States ----------
class BookingStates(StatesGroup):
    selecting_service = State()
    selecting_date = State()
    selecting_time = State()
    confirming = State()


# ---------- Keyboards ----------
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записаться")],
            [KeyboardButton(text="📋 Мои записи"), KeyboardButton(text="❌ Отменить запись")],
            [KeyboardButton(text="🎨 Открыть салон", web_app=types.WebAppInfo(url="https://ruil1395.github.io/Botest-/booking_bot/webapp/"))],
            [KeyboardButton(text="ℹ️ О нас"), KeyboardButton(text="📞 Контакты")],
        ],
        resize_keyboard=True
    )


def get_services_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с услугами"""
    keyboard = []
    for key, service in SERVICES.items():
        keyboard.append([
            InlineKeyboardButton(
                text=f"{service['name']} ({service['duration']} мин) - {service['price']}₽",
                callback_data=f"service_{key}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="❌ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_dates_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с датами (следующие 7 дней)"""
    keyboard = []
    row = []
    
    for i in range(min(7, DAYS_AHEAD)):
        date = datetime.now() + timedelta(days=i)
        weekday = date.weekday()
        
        # Skip non-working days
        if weekday not in WORK_DAYS:
            continue
        
        date_str = date.strftime("%d.%m")
        day_name = date.strftime("%A")
        day_names_ru = {
            'Monday': 'Пн', 'Tuesday': 'Вт', 'Wednesday': 'Ср',
            'Thursday': 'Чт', 'Friday': 'Пт', 'Saturday': 'Сб', 'Sunday': 'Вс'
        }
        day_ru = day_names_ru.get(day_name, day_name[:3])
        
        row.append(InlineKeyboardButton(
            text=f"{day_ru} {date_str}",
            callback_data=f"date_{date.strftime('%Y-%m-%d')}"
        ))
        
        if len(row) >= 2:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="❌ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_times_keyboard(date: str) -> InlineKeyboardMarkup:
    """Клавиатура со временем"""
    booked_slots = db.get_booked_slots(date)
    
    keyboard = []
    row = []
    
    start_hour = WORK_HOURS["start"]
    end_hour = WORK_HOURS["end"]
    
    current_time = datetime.now()
    is_today = date == current_time.strftime("%Y-%m-%d")
    
    for hour in range(start_hour, end_hour):
        for minute in range(0, 60, SLOT_INTERVAL):
            time_str = f"{hour:02d}:{minute:02d}"
            
            # Skip past times for today
            if is_today:
                slot_datetime = datetime.now().replace(hour=hour, minute=minute)
                if slot_datetime <= current_time:
                    continue
            
            # Check if slot is booked
            is_booked = time_str in booked_slots or time_str + ":00" in booked_slots
            
            if is_booked:
                button = InlineKeyboardButton(
                    text=f"❌ {time_str}",
                    callback_data="booked"
                )
            else:
                button = InlineKeyboardButton(
                    text=f"✅ {time_str}",
                    callback_data=f"time_{time_str}"
                )
            
            row.append(button)
            
            if len(row) >= 3:
                keyboard.append(row)
                row = []
    
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="❌ Назад к датам", callback_data="back_to_dates")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_confirm_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_booking"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_main")
        ]
    ])


def get_my_appointments_keyboard(appointments: list) -> InlineKeyboardMarkup:
    """Клавиатура моих записей"""
    keyboard = []
    
    for appt in appointments:
        date_str = appt['appointment_date']
        time_str = appt['appointment_time'][:5]
        service_name = appt['service_name']
        
        keyboard.append([
            InlineKeyboardButton(
                text=f"📅 {date_str} {time_str} - {service_name}",
                callback_data=f"view_{appt['id']}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton(text="❌ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_cancel_keyboard(appointment_id: int) -> InlineKeyboardMarkup:
    """Клавиатура отмены записи"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Да, отменить", callback_data=f"cancel_{appointment_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data="back_to_main")
        ]
    ])


# ---------- Handlers ----------

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start"""
    user = message.from_user
    
    # Save user to database
    db.add_user(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or ""
    )
    
    await message.answer(
        f"👋 Здравствуйте, {user.first_name}!\n\n"
        f"🏆 **Добро пожаловать в наш салон!**\n\n"
        f"📋 **Наши услуги:**\n"
        f"• Консультация - 30 мин (1000₽)\n"
        f"• Стрижка - 60 мин (1500₽)\n"
        f"• Маникюр - 90 мин (2000₽)\n"
        f"• Массаж - 60 мин (2500₽)\n\n"
        f"🕐 **Рабочее время:** Пн-Сб 9:00-20:00\n\n"
        f"📅 **Запишитесь онлайн** в любое удобное время!",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Команда /help"""
    help_text = """
📖 **Инструкция по использованию:**

**📅 Запись на услугу:**
1. Нажмите "📅 Записаться"
2. Выберите услугу
3. Выберите дату
4. Выберите свободное время
5. Подтвердите запись

**📋 Мои записи:**
• Просмотр всех ваших активных записей
• Возможность отмены

**❌ Отмена записи:**
• Выберите запись для отмены
• Подтвердите отмену

**Команды:**
/start - Запустить бота
/help - Эта справка
/mybookings - Мои записи
/cancel - Отменить запись

**🕐 Рабочее время:** Пн-Сб 9:00-20:00
**📞 Контакты:** @admin_support
"""
    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)


@dp.message(F.text == "📅 Записаться")
async def start_booking(message: types.Message, state: FSMContext):
    """Начать процесс записи"""
    await state.clear()
    await message.answer(
        "💆 **Выберите услугу:**",
        reply_markup=get_services_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(BookingStates.selecting_service)


@dp.callback_query(F.data.startswith("service_"))
async def service_selected(callback: types.CallbackQuery, state: FSMContext):
    """Выбор услуги"""
    service_key = callback.data.replace("service_", "")
    service = SERVICES.get(service_key)
    
    if not service:
        await callback.answer("❌ Услуга не найдена", show_alert=True)
        return
    
    await state.update_data(service_key=service_key, service_name=service['name'])
    
    await callback.message.edit_text(
        f"✅ Выбрано: **{service['name']}**\n"
        f"⏱ Длительность: {service['duration']} мин\n"
        f"💰 Цена: {service['price']}₽\n\n"
        f"📅 **Выберите дату:**",
        reply_markup=get_dates_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(BookingStates.selecting_date)


@dp.callback_query(F.data.startswith("date_"))
async def date_selected(callback: types.CallbackQuery, state: FSMContext):
    """Выбор даты"""
    date = callback.data.replace("date_", "")
    
    # Check if it's a working day
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    if date_obj.weekday() not in WORK_DAYS:
        await callback.answer("❌ В этот день мы не работаем", show_alert=True)
        return
    
    await state.update_data(appointment_date=date)
    
    # Format date for display
    date_display = date_obj.strftime("%d.%m.%Y (%A)")
    day_names_ru = {
        'Monday': 'Понедельник', 'Tuesday': 'Вторник', 'Wednesday': 'Среда',
        'Thursday': 'Четверг', 'Friday': 'Пятница', 'Saturday': 'Суббота', 'Sunday': 'Воскресенье'
    }
    for en, ru in day_names_ru.items():
        date_display = date_display.replace(en, ru)
    
    await callback.message.edit_text(
        f"📅 **{date_display}**\n\n"
        f"🕐 **Выберите свободное время:**\n"
        f"✅ - свободно\n"
        f"❌ - занято",
        reply_markup=get_times_keyboard(date),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(BookingStates.selecting_time)


@dp.callback_query(F.data == "back_to_dates")
async def back_to_dates(callback: types.CallbackQuery, state: FSMContext):
    """Назад к выбору даты"""
    data = await state.get_data()
    service_name = data.get('service_name', 'Услуга')
    
    await callback.message.edit_text(
        f"✅ Выбрано: **{service_name}**\n\n"
        f"📅 **Выберите дату:**",
        reply_markup=get_dates_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data.startswith("time_"))
async def time_selected(callback: types.CallbackQuery, state: FSMContext):
    """Выбор времени"""
    time = callback.data.replace("time_", "")
    await state.update_data(appointment_time=time)
    
    data = await state.get_data()
    service_name = data.get('service_name', 'Услуга')
    date = data.get('appointment_date', '')
    
    # Format date for display
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    date_display = date_obj.strftime("%d.%m.%Y")
    
    await callback.message.edit_text(
        f"📋 **Подтверждение записи**\n\n"
        f"💆 Услуга: **{service_name}**\n"
        f"📅 Дата: **{date_display}**\n"
        f"🕐 Время: **{time}**\n\n"
        f"Подтвердите запись:",
        reply_markup=get_confirm_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(BookingStates.confirming)


@dp.callback_query(F.data == "confirm_booking")
async def confirm_booking(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение записи"""
    data = await state.get_data()
    user_id = callback.from_user.id
    username = callback.from_user.username or ""
    
    service_key = data.get('service_key')
    service_name = data.get('service_name')
    date = data.get('appointment_date')
    time = data.get('appointment_time')
    
    if not all([service_key, service_name, date, time]):
        await callback.answer("❌ Ошибка: неполные данные", show_alert=True)
        await state.clear()
        return
    
    # Check if slot is still available
    if db.is_slot_booked(date, time):
        await callback.answer("❌ Это время уже занято! Выберите другое.", show_alert=True)
        await callback.message.edit_text(
            "❌ Это время уже занято!\n\n"
            "🕐 Выберите другое время:",
            reply_markup=get_times_keyboard(date),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Create appointment
    try:
        appointment_id = db.create_appointment(
            user_id=user_id,
            service_key=service_key,
            service_name=service_name,
            appointment_date=date,
            appointment_time=time,
            username=username
        )
        
        # Format date for display
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        date_display = date_obj.strftime("%d.%m.%Y")
        
        # Success message to user
        await callback.message.edit_text(
            f"✅ **Запись подтверждена!**\n\n"
            f"📋 Номер записи: #{appointment_id}\n"
            f"💆 Услуга: {service_name}\n"
            f"📅 Дата: {date_display}\n"
            f"🕐 Время: {time}\n\n"
            f"📍 Ждём вас! Не опаздывайте.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify admin
        if ADMIN_ID:
            try:
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"🔔 **Новая запись!**\n\n"
                         f"📋 #{appointment_id}\n"
                         f"👤 Клиент: {callback.from_user.first_name} (@{username})\n"
                         f"💆 Услуга: {service_name}\n"
                         f"📅 Дата: {date_display}\n"
                         f"🕐 Время: {time}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Failed to notify admin: {e}")
        
        logger.info(f"New appointment #{appointment_id} by user {user_id}")
        
    except Exception as e:
        logger.exception(f"Error creating appointment: {e}")
        await callback.answer("❌ Ошибка при создании записи", show_alert=True)
    
    await state.clear()


@dp.callback_query(F.data == "booked")
async def booked_slot(callback: types.CallbackQuery):
    """Попытка выбрать занятое время"""
    await callback.answer("❌ Это время уже занято", show_alert=True)


@dp.message(F.text == "📋 Мои записи")
async def my_appointments(message: types.Message):
    """Просмотр своих записей"""
    user_id = message.from_user.id
    appointments = db.get_appointments_by_user(user_id)
    
    if not appointments:
        await message.answer(
            "📭 У вас пока нет активных записей.\n\n"
            "📅 Нажмите 'Записаться', чтобы создать новую запись!",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Show appointments
    lines = ["📋 **Ваши записи:**\n"]
    for appt in appointments:
        date_str = appt['appointment_date']
        time_str = appt['appointment_time'][:5]
        service_name = appt['service_name']
        lines.append(f"📅 {date_str} {time_str} - {service_name}")
    
    await message.answer(
        "\n".join(lines),
        reply_markup=get_my_appointments_keyboard(appointments),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data.startswith("view_"))
async def view_appointment(callback: types.CallbackQuery):
    """Просмотр записи"""
    appointment_id = int(callback.data.replace("view_", ""))
    
    # Get appointment details (simplified - just show cancel option)
    await callback.message.edit_text(
        f"📋 **Запись #{appointment_id}**\n\n"
        f"Хотите отменить эту запись?",
        reply_markup=get_cancel_keyboard(appointment_id),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_appointment(callback: types.CallbackQuery):
    """Отмена записи"""
    appointment_id = int(callback.data.replace("cancel_", ""))
    user_id = callback.from_user.id
    
    success = db.cancel_appointment(appointment_id, user_id)
    
    if success:
        await callback.message.edit_text(
            f"✅ **Запись #{appointment_id} отменена**\n\n"
            f"Ждём вас снова! 🙏",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify admin
        if ADMIN_ID:
            try:
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"❌ **Запись отменена!**\n\n"
                         f"📋 #{appointment_id}\n"
                         f"👤 Клиент: {callback.from_user.first_name}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Failed to notify admin about cancellation: {e}")
    else:
        await callback.answer("❌ Не удалось отменить запись", show_alert=True)
    
    await callback.message.edit_reply_markup(reply_markup=None)


@dp.message(F.text == "❌ Отменить запись")
async def cancel_booking(message: types.Message):
    """Отмена записи через меню"""
    user_id = message.from_user.id
    appointments = db.get_appointments_by_user(user_id)
    
    if not appointments:
        await message.answer("📭 У вас нет активных записей для отмены.")
        return
    
    await message.answer(
        "📋 **Выберите запись для отмены:**",
        reply_markup=get_my_appointments_keyboard(appointments),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.message(F.text == "ℹ️ О нас")
async def about_us(message: types.Message):
    """О салоне"""
    await message.answer(
        "🏆 **Добро пожаловать в наш салон!**\n\n"
        "✨ Мы предоставляем качественные услуги с 2020 года.\n\n"
        "💆 **Наши преимущества:**\n"
        "• Опытные мастера\n"
        "• Премиум косметика\n"
        "• Уютная атмосфера\n"
        "• Гарантия качества\n\n"
        "📍 **Адрес:** ул. Примерная, 123\n"
        "🕐 **Режим работы:** Пн-Сб 9:00-20:00",
        parse_mode=ParseMode.MARKDOWN
    )


@dp.message(F.text == "📞 Контакты")
async def contacts(message: types.Message):
    """Контакты"""
    await message.answer(
        "📞 **Наши контакты:**\n\n"
        "📍 **Адрес:** ул. Примерная, 123\n"
        "📱 **Телефон:** +7 (999) 123-45-67\n"
        "💬 **Telegram:** @admin_support\n"
        "🌐 **Сайт:** www.example.com\n\n"
        "🕐 **Режим работы:**\n"
        "Пн-Сб: 9:00-20:00\n"
        "Вс: Выходной",
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    """Назад в главное меню"""
    await callback.message.edit_text(
        "🏠 **Главное меню**",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )


# ---------- Reminder System ----------

async def send_reminders():
    """Фоновая задача для отправки напоминаний"""
    while True:
        try:
            # Check for appointments in 1 hour
            target_time = datetime.now() + timedelta(hours=1)
            appointments = db.get_appointments_for_reminder(target_time)
            
            for appt in appointments:
                user_id = appt['user_id']
                appointment_id = appt['id']
                date = appt['appointment_date']
                time = appt['appointment_time'][:5]
                service_name = appt['service_name']
                
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"⏰ **Напоминание о записи!**\n\n"
                             f"💆 Услуга: {service_name}\n"
                             f"📅 Дата: {date}\n"
                             f"🕐 Время: {time}\n\n"
                             f"⏳ До записи остался 1 час.\n"
                             f"Ждём вас! 🙏",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    db.mark_reminder_sent(appointment_id)
                    logger.info(f"Reminder sent for appointment #{appointment_id}")
                    
                except Exception as e:
                    logger.error(f"Failed to send reminder to user {user_id}: {e}")
            
            # Sleep until next minute
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.exception(f"Error in reminder task: {e}")
            await asyncio.sleep(60)


# ---------- Main ----------

async def main():
    logger.info("Starting Booking Bot...")
    logger.info(f"Admin ID: {ADMIN_ID}")
    logger.info(f"Services: {list(SERVICES.keys())}")
    
    # Start reminder task
    asyncio.create_task(send_reminders())
    
    logger.info("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
