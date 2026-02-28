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
