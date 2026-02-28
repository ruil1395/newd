"""
Telegram Bot для записи на услуги
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any
from pathlib import Path

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.enums import ParseMode

from config import (
    BOT_TOKEN, ADMIN_ID, SERVICES, EXTRA_SERVICES, WORK_HOURS, 
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


class ReviewStates(StatesGroup):
    rating = State()
    comment = State()
    photo = State()


class AdminStates(StatesGroup):
    portfolio_photo = State()
    portfolio_caption = State()
    service_name = State()
    service_description = State()
    service_duration = State()
    service_price = State()
    # Для редактирования
    edit_field = State()
    edit_value = State()
    delete_confirm = State()


# ---------- Keyboards ----------
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записаться")],
            [KeyboardButton(text="💆 Услуги"), KeyboardButton(text="⭐ Отзывы")],
            [KeyboardButton(text="📸 Портфолио"), KeyboardButton(text="📋 Мои записи")],
            [KeyboardButton(text="❌ Отменить запись")],
            [KeyboardButton(text="🎨 Открыть салон", web_app=types.WebAppInfo(url="https://ruil1395.github.io/newd/booking_bot/webapp/index.html"))],
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
                callback_data=f"svc_{key}"
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
        f"🏆 **Добро пожаловать!**\n\n"
        f"📋 **Наши услуги:**\n"
        f"• Индивидуальный подход к каждому клиенту\n"
        f"• Гарантия качества\n"
        f"• Лучшие цены\n\n"
        f"🕐 **Рабочее время:** Пн-Сб 9:00-20:00\n\n"
        f"📅 **Запишитесь онлайн** в любое удобное время!\n\n"
        f"💡 *Выберите нужный раздел в меню ниже* 👇",
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


@dp.callback_query(F.data.startswith("svc_"))
async def service_selected(callback: types.CallbackQuery, state: FSMContext):
    """Выбор услуги"""
    service_key = callback.data.replace("svc_", "")
    logger.info(f"Callback received: {callback.data}, service_key: {service_key}")
    logger.info(f"Available SERVICES keys: {list(SERVICES.keys())}")
    
    service = SERVICES.get(service_key)

    if not service:
        logger.warning(f"Service {service_key} not found!")
        await callback.answer(f"❌ Услуга не найдена: {service_key}", show_alert=True)
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
    """О компании"""
    await message.answer(
        "🏆 **Добро пожаловать!**\n\n"
        "✨ Мы предоставляем качественные услуги с профессиональным подходом.\n\n"
        "💎 **Наши преимущества:**\n"
        "• Опытные специалисты\n"
        "• Гарантия качества\n"
        "• Индивидуальный подход\n"
        "• Лучшие цены на рынке\n\n"
        "📍 **Адрес:** укажите ваш адрес\n"
        "🕐 **Режим работы:** Пн-Сб 9:00-20:00",
        parse_mode=ParseMode.MARKDOWN
    )


@dp.message(F.text == "📞 Контакты")
async def contacts(message: types.Message):
    """Контакты"""
    await message.answer(
        "📞 **Наши контакты:**\n\n"
        "📍 **Адрес:** укажите ваш адрес\n"
        "📱 **Телефон:** укажите ваш телефон\n"
        "💬 **Telegram:** укажите ваш контакт\n"
        "🌐 **Сайт:** укажите ваш сайт\n\n"
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


# ========== РАЗДЕЛ: УСЛУГИ ==========

def get_services_list_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура со списком всех услуг"""
    keyboard = []
    
    # Основные услуги
    for key, service in SERVICES.items():
        keyboard.append([
            InlineKeyboardButton(
                text=f"{service['name']} - {service['price']}₽",
                callback_data=f"service_detail_{key}"
            )
        ])
    
    # Дополнительные услуги
    if EXTRA_SERVICES:
        keyboard.append([InlineKeyboardButton(text="➖" * 15, callback_data="ignore")])
        for key, service in EXTRA_SERVICES.items():
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{service['name']} - {service['price']}₽",
                    callback_data=f"service_detail_{key}"
                )
            ])
    
    keyboard.append([InlineKeyboardButton(text="❌ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@dp.message(F.text == "💆 Услуги")
async def show_services(message: types.Message):
    """Показать все услуги"""
    all_services = {**SERVICES, **EXTRA_SERVICES}
    
    text = "💆 **Услуги и цены:**\n\n"
    
    text += "**📋 Основные услуги:**\n"
    for service in SERVICES.values():
        text += f"• {service['name']} - {service['duration']} мин - {service['price']}₽\n"
    
    if EXTRA_SERVICES:
        text += "\n**➕ Дополнительные опции:**\n"
        for service in EXTRA_SERVICES.values():
            text += f"• {service['name']} - {service['duration']} мин - {service['price']}₽\n"
    
    text += "\n_Нажмите на услугу для подробностей_ 👇"
    
    await message.answer(
        text,
        reply_markup=get_services_list_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data.startswith("service_detail_"))
async def show_service_detail(callback: types.CallbackQuery):
    """Показать подробности услуги"""
    service_key = callback.data.replace("service_detail_", "")
    all_services = {**SERVICES, **EXTRA_SERVICES}
    
    service = all_services.get(service_key)
    if not service:
        await callback.answer("❌ Услуга не найдена", show_alert=True)
        return
    
    text = (
        f"{service['name']}\n\n"
        f"⏱ **Длительность:** {service['duration']} мин\n"
        f"💰 **Цена:** {service['price']}₽\n\n"
        f"📝 **Описание:**\n"
        f"{service['description']}\n\n"
        f"📅 **Записаться на эту услугу:**"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Записаться", callback_data=f"service_{service_key}")],
            [InlineKeyboardButton(text="❌ Назад", callback_data="back_to_services")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data == "back_to_services")
async def back_to_services(callback: types.CallbackQuery):
    """Назад к списку услуг"""
    await show_services(callback.message)


# ========== РАЗДЕЛ: ОТЗЫВЫ ==========

def get_rating_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с оценками"""
    keyboard = []
    row = []
    for i in range(1, 6):
        row.append(InlineKeyboardButton(text=f"{i}⭐", callback_data=f"rating_{i}"))
        if len(row) >= 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@dp.message(F.text == "⭐ Отзывы")
async def show_reviews(message: types.Message):
    """Показать отзывы"""
    reviews = db.get_reviews(limit=10)
    avg_rating = db.get_average_rating()
    
    if not reviews:
        text = (
            "⭐ **Отзывы**\n\n"
            "Пока нет отзывов. Будьте первым!\n\n"
            "📝 **Оставьте отзыв:**"
        )
    else:
        text = f"⭐ **Отзывы клиентов** (средний рейтинг: {avg_rating}⭐)\n\n"
        for i, review in enumerate(reviews[:5], 1):
            stars = "⭐" * review['rating']
            name = review.get('first_name', 'Клиент')
            text += f"{i}. {stars} — {name}\n"
            if review.get('comment'):
                text += f"   _{review['comment']}_\n"
            text += "\n"
        text += "📝 **Оставьте свой отзыв:**"
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Оставить отзыв", callback_data="write_review")],
            [InlineKeyboardButton(text="❌ Назад", callback_data="back_to_main")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data == "write_review")
async def start_review(callback: types.CallbackQuery, state: FSMContext):
    """Начать писать отзыв"""
    await state.clear()
    await callback.message.edit_text(
        "⭐ **Оставьте отзыв**\n\n"
        "Оцените нашу работу от 1 до 5 звёзд:",
        reply_markup=get_rating_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(ReviewStates.rating)


@dp.callback_query(F.data.startswith("rating_"))
async def set_rating(callback: types.CallbackQuery, state: FSMContext):
    """Установить оценку"""
    rating = int(callback.data.replace("rating_", ""))
    await state.update_data(rating=rating)
    
    stars = "⭐" * rating
    await callback.message.edit_text(
        f"{stars} Вы поставили оценку: **{rating}**\n\n"
        "📝 **Напишите ваш отзыв:**\n"
        "(или отправьте /skip чтобы пропустить)",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(ReviewStates.comment)


@dp.message(ReviewStates.comment, F.text)
async def save_comment(message: types.Message, state: FSMContext):
    """Сохранить комментарий"""
    if message.text == "/skip":
        await save_review(message, state, comment=None)
        return
    
    await state.update_data(comment=message.text)
    await save_review(message, state, comment=message.text)


async def save_review(message: types.Message, state: FSMContext, comment=None):
    """Сохранить отзыв"""
    data = await state.get_data()
    user = message.from_user
    
    review_id = db.add_review(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        rating=data['rating'],
        comment=comment
    )
    
    stars = "⭐" * data['rating']
    await message.answer(
        f"✅ **Спасибо за отзыв!**\n\n"
        f"Ваша оценка: {stars}\n"
        f"Отзыв отправлен на модерацию.\n\n"
        f"ID отзыва: #{review_id}",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Уведомить админа
    if ADMIN_ID:
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=f"📝 **Новый отзыв!**\n\n"
                     f"👤 {user.first_name} (@{user.username})\n"
                     f"⭐ Оценка: {data['rating']}/5\n"
                     f"📝 Комментарий: {comment or 'Без комментария'}\n\n"
                     f"ID: #{review_id}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Failed to notify admin about review: {e}")
    
    await state.clear()


# ========== РАЗДЕЛ: ПОРТФОЛИО ==========

@dp.message(F.text == "📸 Портфолио")
async def show_portfolio(message: types.Message):
    """Показать портфолио работ"""
    portfolio = db.get_portfolio(limit=10)
    
    if not portfolio:
        await message.answer(
            "📸 **Портфолио**\n\n"
            "Пока нет работ в портфолио.\n"
            "Заходите позже! 🙏",
            reply_markup=get_main_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Показываем первое фото с описанием
    item = portfolio[0]
    caption = f"📸 **Портфолио**\n\n{item.get('caption', 'Без описания')}\n\n"
    
    if len(portfolio) > 1:
        caption += f"_Фото 1 из {len(portfolio)}_\n\n"
        caption += "Используйте кнопки для навигации 👇"
    
    keyboard = []
    if len(portfolio) > 1:
        keyboard.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data="portfolio_prev_0"),
            InlineKeyboardButton(text="➡️ Вперёд", callback_data="portfolio_next_0")
        ])
    keyboard.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="back_to_main")])
    
    # Отправляем фото
    try:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=item['photo_id'],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Failed to send portfolio photo: {e}")
        await message.answer("❌ Ошибка при загрузке фото", reply_markup=get_main_keyboard())


@dp.callback_query(F.data.startswith("portfolio_"))
async def navigate_portfolio(callback: types.CallbackQuery):
    """Навигация по портфолио"""
    action, idx = callback.data.replace("portfolio_", "").split("_")
    idx = int(idx)
    
    portfolio = db.get_portfolio(limit=10)
    if not portfolio:
        await callback.answer("Нет работ", show_alert=True)
        return
    
    if action == "next":
        idx = min(idx + 1, len(portfolio) - 1)
    elif action == "prev":
        idx = max(idx - 1, 0)
    
    item = portfolio[idx]
    caption = f"📸 **Портфолио**\n\n{item.get('caption', 'Без описания')}\n\n"
    caption += f"_Фото {idx + 1} из {len(portfolio)}_"
    
    keyboard = []
    if len(portfolio) > 1:
        keyboard.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"portfolio_prev_{idx}"),
            InlineKeyboardButton(text="➡️ Вперёд", callback_data=f"portfolio_next_{idx}")
        ])
    keyboard.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="back_to_main")])
    
    try:
        await callback.message.edit_media(
            media=types.InputMediaPhoto(media=item['photo_id'], caption=caption),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    except Exception as e:
        logger.error(f"Failed to edit portfolio media: {e}")


# ========== АДМИН ПАНЕЛЬ ==========

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Админ панель"""
    if message.from_user.id != ADMIN_ID:
        return
    
    await message.answer(
        "⚙️ **Админ панель**\n\n"
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📸 Добавить работу", callback_data="admin_add_portfolio")],
            [InlineKeyboardButton(text="📋 Управление услугами", callback_data="admin_services")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🔄 Перезапустить бота", callback_data="admin_restart")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data == "admin_restart")
async def admin_restart_bot(callback: types.CallbackQuery):
    """Перезапуск бота"""
    await callback.message.edit_text(
        "🔄 **Перезапуск бота**\n\n"
        "⚠️ Вы уверены?\n\n"
        "Бот будет перезапущен в течение 5 секунд.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, перезапустить", callback_data="restart_confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data == "restart_confirm")
async def admin_restart_confirm(callback: types.CallbackQuery):
    """Подтверждение перезапуска"""
    await callback.message.answer(
        "🔄 Бот перезапускается...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Отправляем команду на перезапуск через subprocess
    import subprocess
    import sys
    import os
    
    # Получаем путь к текущему скрипту
    script_path = os.path.abspath(__file__)
    
    # Запускаем новый процесс
    subprocess.Popen([sys.executable, script_path], start_new_session=True)
    
    # Завершаем текущий процесс
    await asyncio.sleep(2)
    os._exit(0)


@dp.callback_query(F.data == "admin_add_portfolio")
async def admin_add_portfolio(callback: types.CallbackQuery, state: FSMContext):
    """Добавить работу в портфолио"""
    await state.clear()
    await callback.message.edit_text(
        "📸 **Добавить работу в портфолио**\n\n"
        "Отправьте фото вашей работы:",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(AdminStates.portfolio_photo)


@dp.message(AdminStates.portfolio_photo, F.photo)
async def save_portfolio_photo(message: types.Message, state: FSMContext):
    """Сохранить фото портфолио"""
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    
    await message.answer(
        "📝 **Введите описание работы:**\n"
        "(или отправьте /skip чтобы пропустить)",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(AdminStates.portfolio_caption)


@dp.message(AdminStates.portfolio_caption, F.text)
async def save_portfolio_caption(message: types.Message, state: FSMContext):
    """Сохранить описание работы"""
    if message.text == "/skip":
        await save_portfolio_item(message, state, caption=None)
        return
    
    await state.update_data(caption=message.text)
    await save_portfolio_item(message, state, caption=message.text)


async def save_portfolio_item(message: types.Message, state: FSMContext, caption=None):
    """Сохранить работу в портфолио"""
    data = await state.get_data()
    
    item_id = db.add_portfolio_item(
        photo_id=data['photo_id'],
        caption=caption
    )
    
    await message.answer(
        f"✅ **Работа добавлена в портфолио!**\n\n"
        f"ID: #{item_id}",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.clear()


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    """Статистика"""
    total_appointments = len(db.get_all_active_appointments())
    total_reviews = len(db.get_reviews(limit=1000))
    avg_rating = db.get_average_rating()
    total_portfolio = len(db.get_portfolio(limit=1000))

    text = (
        "📊 **Статистика**\n\n"
        f"📅 Активных записей: {total_appointments}\n"
        f"⭐ Отзывов: {total_reviews}\n"
        f"🏆 Средний рейтинг: {avg_rating}⭐\n"
        f"📸 Работ в портфолио: {total_portfolio}"
    )

    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.MARKDOWN
    )


# ========== УПРАВЛЕНИЕ УСЛУГАМИ ==========

@dp.callback_query(F.data == "admin_services")
async def admin_services_menu(callback: types.CallbackQuery):
    """Меню управления услугами"""
    await callback.message.edit_text(
        "📋 **Управление услугами**\n\n"
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить услугу", callback_data="admin_service_add")],
            [InlineKeyboardButton(text="📝 Редактировать услугу", callback_data="admin_service_edit")],
            [InlineKeyboardButton(text="❌ Удалить услугу", callback_data="admin_service_delete")],
            [InlineKeyboardButton(text="📋 Список услуг", callback_data="admin_service_list")],
            [InlineKeyboardButton(text="❌ Назад", callback_data="admin")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data == "admin_service_list")
async def admin_service_list(callback: types.CallbackQuery):
    """Список всех услуг"""
    all_services = {**SERVICES, **EXTRA_SERVICES}
    
    text = "📋 **Все услуги:**\n\n"
    for key, service in all_services.items():
        text += f"**{key}**: {service['name']}\n"
        text += f"  ⏱ {service['duration']} мин | 💰 {service['price']}₽\n"
        text += f"  _{service['description']}_\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Назад", callback_data="admin_services")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data == "admin_service_add")
async def admin_service_add_start(callback: types.CallbackQuery, state: FSMContext):
    """Начать добавление услуги"""
    await state.clear()
    await callback.message.edit_text(
        "➕ **Добавление новой услуги**\n\n"
        "Введите **ключ услуги** (латиницей, без пробелов):\n"
        "Пример: `consultation`, `haircut_premium`, `service_5`",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(AdminStates.service_name)


@dp.message(AdminStates.service_name, F.text)
async def admin_service_add_key(message: types.Message, state: FSMContext):
    """Сохранить ключ услуги"""
    key = message.text.strip().lower().replace(' ', '_')
    await state.update_data(service_key=key)
    
    await message.answer(
        f"✅ Ключ: `{key}`\n\n"
        "Теперь введите **название услуги**:\n"
        "Пример: `Стрижка женская`, `Консультация юриста`",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(AdminStates.service_description)


@dp.message(AdminStates.service_description, F.text)
async def admin_service_add_name(message: types.Message, state: FSMContext):
    """Сохранить название услуги"""
    await state.update_data(service_name=message.text.strip())
    
    await message.answer(
        f"✅ Название: `{message.text.strip()}`\n\n"
        "Введите **длительность** (в минутах):\n"
        "Пример: `60`, `90`, `30`",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(AdminStates.service_duration)


@dp.message(AdminStates.service_duration, F.text)
async def admin_service_add_duration(message: types.Message, state: FSMContext):
    """Сохранить длительность"""
    try:
        duration = int(message.text.strip())
        await state.update_data(service_duration=duration)
        
        await message.answer(
            f"✅ Длительность: `{duration}` мин\n\n"
            "Введите **цену** (в рублях):\n"
            "Пример: `1500`, `2000`",
            parse_mode=ParseMode.MARKDOWN
        )
        await state.set_state(AdminStates.service_price)
    except ValueError:
        await message.answer("❌ Введите число! Попробуйте ещё раз:")


@dp.message(AdminStates.service_price, F.text)
async def admin_service_add_price(message: types.Message, state: FSMContext):
    """Сохранить цену и создать услугу"""
    try:
        price = int(message.text.strip())
        data = await state.get_data()
        
        # Добавляем услугу в БД
        db.add_service(
            key=data['service_key'],
            name=data['service_name'],
            description="Услуга добавлена через админ-панель",
            duration=data['service_duration'],
            price=price
        )
        
        await message.answer(
            f"✅ **Услуга добавлена!**\n\n"
            f"🔑 Ключ: `{data['service_key']}`\n"
            f"📝 Название: {data['service_name']}\n"
            f"⏱ Длительность: {data['service_duration']} мин\n"
            f"💰 Цена: {price}₽\n\n"
            f"Теперь добавьте услугу в `config.py` для полноценной работы.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить ещё", callback_data="admin_service_add")],
                [InlineKeyboardButton(text="📋 Управление услугами", callback_data="admin_services")],
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введите число! Попробуйте ещё раз:")


@dp.callback_query(F.data == "admin_service_edit")
async def admin_service_edit(callback: types.CallbackQuery):
    """Редактирование услуги"""
    all_services = {**SERVICES, **EXTRA_SERVICES}
    
    keyboard = []
    for key, service in all_services.items():
        keyboard.append([
            InlineKeyboardButton(
                text=f"{service['name']} - {service['price']}₽",
                callback_data=f"admin_edit_{key}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="❌ Назад", callback_data="admin_services")])
    
    await callback.message.edit_text(
        "📝 **Выберите услугу для редактирования:**",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data.startswith("admin_edit_"))
async def admin_service_edit_select(callback: types.CallbackQuery, state: FSMContext):
    """Выбор услуги для редактирования"""
    service_key = callback.data.replace("admin_edit_", "")
    all_services = {**SERVICES, **EXTRA_SERVICES}
    service = all_services.get(service_key)
    
    if not service:
        await callback.answer("❌ Услуга не найдена", show_alert=True)
        return
    
    await state.update_data(edit_service_key=service_key)
    
    text = (
        f"📝 **Редактирование услуги**\n\n"
        f"🔑 Ключ: `{service_key}`\n"
        f"📝 Название: {service['name']}\n"
        f"⏱ Длительность: {service['duration']} мин\n"
        f"💰 Цена: {service['price']}₽\n"
        f"📄 Описание: {service['description']}\n\n"
        f"**Выберите поле для изменения:**"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Название", callback_data="edit_field_name")],
            [InlineKeyboardButton(text="⏱ Длительность", callback_data="edit_field_duration")],
            [InlineKeyboardButton(text="💰 Цена", callback_data="edit_field_price")],
            [InlineKeyboardButton(text="📄 Описание", callback_data="edit_field_description")],
            [InlineKeyboardButton(text="❌ Назад", callback_data="admin_services")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(AdminStates.edit_field)


@dp.callback_query(F.data.startswith("edit_field_"))
async def admin_edit_field_select(callback: types.CallbackQuery, state: FSMContext):
    """Выбор поля для редактирования"""
    field = callback.data.replace("edit_field_", "")
    data = await state.get_data()
    service_key = data.get('edit_service_key')
    
    all_services = {**SERVICES, **EXTRA_SERVICES}
    service = all_services.get(service_key)
    
    if not service:
        await callback.answer("❌ Услуга не найдена", show_alert=True)
        return
    
    await state.update_data(edit_field=field)
    
    field_names = {
        'name': 'название',
        'duration': 'длительность (в минутах)',
        'price': 'цену (в рублях)',
        'description': 'описание'
    }
    
    current_value = service.get(field, 'Нет')
    
    await callback.message.edit_text(
        f"✏️ **Изменение: {field_names.get(field, field)}**\n\n"
        f"Текущее значение: `{current_value}`\n\n"
        f"Введите **новое значение**:",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(AdminStates.edit_value)


@dp.message(AdminStates.edit_value, F.text)
async def admin_edit_save(message: types.Message, state: FSMContext):
    """Сохранение изменений"""
    data = await state.get_data()
    service_key = data.get('edit_service_key')
    field = data.get('edit_field')
    new_value = message.text.strip()
    
    # Читаем config.py
    config_path = Path("./config.py")
    if not config_path.exists():
        config_path = Path("/workspaces/newd/booking_bot/config.py")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Преобразуем значение
        if field in ['duration', 'price']:
            new_value = int(new_value)
        elif field == 'name':
            pass
        else:
            pass
        
        # Ищем и заменяем значение в SERVICES или EXTRA_SERVICES
        # Находим текущее значение
        pattern = rf'("{service_key}".*?)"{field}":\s*("[^"]*"|\d+)'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            if field in ['duration', 'price']:
                replacement = f'{match.group(1)}"{field}": {new_value}'
            else:
                replacement = f'{match.group(1)}"{field}": "{new_value}"'
            
            content = content.replace(match.group(0), replacement)
            
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            await message.answer(
                f"✅ **Изменено!**\n\n"
                f"🔑 Услуга: `{service_key}`\n"
                f"📝 {field}: `{new_value}`\n\n"
                f"⚠️ **Перезапустите бота** для применения изменений!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📝 Редактировать ещё", callback_data="admin_service_edit")],
                    [InlineKeyboardButton(text="📋 Управление услугами", callback_data="admin_services")],
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await message.answer(
                f"❌ Не удалось найти услугу в config.py\n\n"
                f"Возможно, услуга имеет другой формат.\n"
                f"Измените вручную в файле config.py",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Управление услугами", callback_data="admin_services")],
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
        
        await state.clear()
        
    except Exception as e:
        logger.exception(f"Error editing service: {e}")
        await message.answer(
            f"❌ Ошибка при редактировании: {e}\n\n"
            f"Измените вручную в config.py",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Управление услугами", callback_data="admin_services")],
            ])
        )
        await state.clear()


@dp.callback_query(F.data == "admin_service_delete")
async def admin_service_delete(callback: types.CallbackQuery, state: FSMContext):
    """Удаление услуги"""
    all_services = {**SERVICES, **EXTRA_SERVICES}
    
    keyboard = []
    for key, service in all_services.items():
        keyboard.append([
            InlineKeyboardButton(
                text=f"❌ {service['name']}",
                callback_data=f"admin_delete_{key}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="❌ Назад", callback_data="admin_services")])
    
    await callback.message.edit_text(
        "❌ **Удаление услуги**\n\n"
        "⚠️ Выберите услугу для удаления:\n\n"
        "После выбора услуга будет удалена из config.py",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data.startswith("admin_delete_"))
async def admin_service_delete_confirm(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение удаления услуги"""
    service_key = callback.data.replace("admin_delete_", "")
    all_services = {**SERVICES, **EXTRA_SERVICES}
    service = all_services.get(service_key)
    
    if not service:
        await callback.answer("❌ Услуга не найдена", show_alert=True)
        return
    
    await state.update_data(delete_service_key=service_key, delete_service_name=service['name'])
    
    await callback.message.edit_text(
        f"⚠️ **Вы уверены?**\n\n"
        f"Будет удалена услуга:\n"
        f"🔑 Ключ: `{service_key}`\n"
        f"📝 Название: {service['name']}\n"
        f"💰 Цена: {service['price']}₽\n\n"
        f"Это действие нельзя отменить!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Да, удалить", callback_data="delete_confirm_yes")],
            [InlineKeyboardButton(text="❌ Нет, отмена", callback_data="admin_service_delete")],
        ]),
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data == "delete_confirm_yes")
async def admin_service_delete_execute(callback: types.CallbackQuery, state: FSMContext):
    """Удаление услуги из config.py"""
    data = await state.get_data()
    service_key = data.get('delete_service_key')
    
    config_path = Path("./config.py")
    if not config_path.exists():
        config_path = Path("/workspaces/newd/booking_bot/config.py")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Находим и удаляем услугу
        # Паттерн для поиска блока услуги
        pattern = rf'"{service_key}":\s*\{{[^}}]*\}},?\s*\n'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            content = content.replace(match.group(0), '')
            
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            await callback.message.edit_text(
                f"✅ **Услуга удалена!**\n\n"
                f"🔑 Ключ: `{service_key}`\n\n"
                f"⚠️ **Перезапустите бота** для применения изменений!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Удалить ещё", callback_data="admin_service_delete")],
                    [InlineKeyboardButton(text="📋 Управление услугами", callback_data="admin_services")],
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await callback.message.edit_text(
                f"❌ Не удалось найти услугу в config.py\n\n"
                f"Удалите вручную из файла config.py",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Управление услугами", callback_data="admin_services")],
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
        
        await state.clear()
        
    except Exception as e:
        logger.exception(f"Error deleting service: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при удалении: {e}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Управление услугами", callback_data="admin_services")],
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        await state.clear()


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
