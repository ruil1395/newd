"""
Конфигурация бота для записи на услуги
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# ID администратора (кому отправлять уведомления о новых записях)
ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", "0"))

# База данных
DATABASE_PATH = os.getenv("DATABASE_PATH", "./booking.db")

# Часовой пояс (для отображения времени)
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Услуги (название, длительность в минутах, цена)
SERVICES = {
    "consultation": {"name": "📋 Консультация", "duration": 30, "price": 1000},
    "haircut": {"name": "✂️ Стрижка", "duration": 60, "price": 1500},
    "manicure": {"name": "💅 Маникюр", "duration": 90, "price": 2000},
    "massage": {"name": "💆 Массаж", "duration": 60, "price": 2500},
}

# Рабочие часы (начало, конец)
WORK_HOURS = {"start": 9, "end": 20}

# Дни недели для записи (0 = понедельник, 6 = воскресенье)
WORK_DAYS = [0, 1, 2, 3, 4, 5]  # Пн-Сб

# Количество дней вперёд для записи
DAYS_AHEAD = 14

# Интервал слотов (минуты)
SLOT_INTERVAL = 30

if not BOT_TOKEN:
    raise ValueError("No TELEGRAM_BOT_TOKEN found in environment variables")
