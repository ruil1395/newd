"""
База данных для хранения записей
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path


class Database:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    service_key TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    appointment_date DATE NOT NULL,
                    appointment_time TIME NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reminder_sent INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active'
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица отзывов
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    rating INTEGER NOT NULL,
                    comment TEXT,
                    photo_id TEXT,
                    appointment_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_approved INTEGER DEFAULT 0
                )
            """)
            
            # Таблица портфолио
            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    photo_id TEXT NOT NULL,
                    caption TEXT,
                    service_key TEXT,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
            """)
            
            # Таблица услуг с описанием
            conn.execute("""
                CREATE TABLE IF NOT EXISTS services_detail (
                    key TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    duration INTEGER,
                    price INTEGER,
                    is_active INTEGER DEFAULT 1
                )
            """)
            
            conn.commit()

    def add_user(self, user_id: int, username: str, first_name: str, last_name: str = None):
        """Добавить или обновить пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, created_at)
                VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM users WHERE user_id = ?), CURRENT_TIMESTAMP))
            """, (user_id, username, first_name, last_name, user_id))
            conn.commit()

    def create_appointment(
        self,
        user_id: int,
        service_key: str,
        service_name: str,
        appointment_date: str,
        appointment_time: str,
        username: str = None
    ) -> int:
        """Создать новую запись"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO appointments 
                (user_id, username, service_key, service_name, appointment_date, appointment_time)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, username, service_key, service_name, appointment_date, appointment_time))
            conn.commit()
            return cursor.lastrowid

    def get_appointment(
        self,
        date: str,
        time: str
    ) -> Optional[Dict[str, Any]]:
        """Получить запись на дату и время"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT a.*, u.first_name, u.last_name
                FROM appointments a
                LEFT JOIN users u ON a.user_id = u.user_id
                WHERE a.appointment_date = ? AND a.appointment_time = ?
                AND a.status = 'active'
            """, (date, time))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_appointments_by_date(self, date: str) -> List[Dict[str, Any]]:
        """Получить все записи на дату"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT a.*, u.first_name, u.last_name, u.username
                FROM appointments a
                LEFT JOIN users u ON a.user_id = u.user_id
                WHERE a.appointment_date = ? AND a.status = 'active'
                ORDER BY a.appointment_time
            """, (date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_appointments_by_user(self, user_id: int) -> List[Dict[str, Any]]:
        """Получить все записи пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM appointments
                WHERE user_id = ? AND status = 'active'
                ORDER BY appointment_date, appointment_time
            """, (user_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_user_appointment(self, user_id: int, date: str, time: str) -> Optional[Dict[str, Any]]:
        """Получить запись пользователя на дату и время"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM appointments
                WHERE user_id = ? AND appointment_date = ? AND appointment_time = ?
                AND status = 'active'
            """, (user_id, date, time))
            row = cursor.fetchone()
            return dict(row) if row else None

    def is_slot_booked(self, date: str, time: str) -> bool:
        """Проверить, занят ли слот"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) FROM appointments
                WHERE appointment_date = ? AND appointment_time = ?
                AND status = 'active'
            """, (date, time))
            count = cursor.fetchone()[0]
            return count > 0

    def get_booked_slots(self, date: str) -> List[str]:
        """Получить список занятых слотов на дату"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT appointment_time FROM appointments
                WHERE appointment_date = ? AND status = 'active'
            """, (date,))
            return [row[0] for row in cursor.fetchall()]

    def cancel_appointment(self, appointment_id: int, user_id: int = None) -> bool:
        """Отменить запись"""
        with sqlite3.connect(self.db_path) as conn:
            if user_id:
                cursor = conn.execute("""
                    UPDATE appointments SET status = 'cancelled'
                    WHERE id = ? AND user_id = ?
                """, (appointment_id, user_id))
            else:
                cursor = conn.execute("""
                    UPDATE appointments SET status = 'cancelled'
                    WHERE id = ?
                """, (appointment_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_appointments_for_reminder(self, target_time: datetime) -> List[Dict[str, Any]]:
        """Получить записи для напоминания (за час до)"""
        reminder_date = target_time.strftime("%Y-%m-%d")
        reminder_hour = target_time.strftime("%H:00")
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT a.*, u.first_name, u.last_name, u.username
                FROM appointments a
                LEFT JOIN users u ON a.user_id = u.user_id
                WHERE a.appointment_date = ? 
                AND a.appointment_time BETWEEN ? AND ?
                AND a.status = 'active'
                AND a.reminder_sent = 0
            """, (reminder_date, reminder_hour, reminder_hour))
            return [dict(row) for row in cursor.fetchall()]

    def mark_reminder_sent(self, appointment_id: int):
        """Отметить, что напоминание отправлено"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE appointments SET reminder_sent = 1
                WHERE id = ?
            """, (appointment_id,))
            conn.commit()

    def get_all_active_appointments(self) -> List[Dict[str, Any]]:
        """Получить все активные записи"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT a.*, u.first_name, u.last_name, u.username
                FROM appointments a
                LEFT JOIN users u ON a.user_id = u.user_id
                WHERE a.status = 'active'
                ORDER BY a.appointment_date, a.appointment_time
            """)
            return [dict(row) for row in cursor.fetchall()]

    # ========== Отзывы ==========
    def add_review(
        self,
        user_id: int,
        username: str,
        first_name: str,
        rating: int,
        comment: str = None,
        photo_id: str = None,
        appointment_id: int = None
    ) -> int:
        """Добавить отзыв"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO reviews (user_id, username, first_name, rating, comment, photo_id, appointment_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, username, first_name, rating, comment, photo_id, appointment_id))
            conn.commit()
            return cursor.lastrowid

    def get_reviews(self, limit: int = 10, approved_only: bool = True) -> List[Dict[str, Any]]:
        """Получить отзывы"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT * FROM reviews
                WHERE is_approved = 1 OR ? = 0
                ORDER BY created_at DESC
                LIMIT ?
            """
            cursor = conn.execute(query, (0 if not approved_only else 1, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_average_rating(self) -> float:
        """Получить средний рейтинг"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT AVG(rating) FROM reviews WHERE is_approved = 1
            """)
            result = cursor.fetchone()[0]
            return round(result, 2) if result else 0.0

    def approve_review(self, review_id: int) -> bool:
        """Одобрить отзыв"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE reviews SET is_approved = 1 WHERE id = ?
            """, (review_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ========== Портфолио ==========
    def add_portfolio_item(
        self,
        photo_id: str,
        caption: str = None,
        service_key: str = None
    ) -> int:
        """Добавить работу в портфолио"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO portfolio (photo_id, caption, service_key)
                VALUES (?, ?, ?)
            """, (photo_id, caption, service_key))
            conn.commit()
            return cursor.lastrowid

    def get_portfolio(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Получить работы из портфолио"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM portfolio
                WHERE is_active = 1
                ORDER BY uploaded_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def delete_portfolio_item(self, item_id: int) -> bool:
        """Удалить работу из портфолио"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE portfolio SET is_active = 0 WHERE id = ?
            """, (item_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ========== Услуги ==========
    def get_services_list(self) -> List[Dict[str, Any]]:
        """Получить список услуг"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM services_detail WHERE is_active = 1
            """)
            return [dict(row) for row in cursor.fetchall()]

    def add_service(
        self,
        key: str,
        name: str,
        description: str,
        duration: int,
        price: int
    ) -> bool:
        """Добавить услугу"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO services_detail (key, name, description, duration, price)
                VALUES (?, ?, ?, ?, ?)
            """, (key, name, description, duration, price))
            conn.commit()
            return True
