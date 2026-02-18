"""
Telegram Bot for Voice-Controlled Qwen Code with Feedback System

Features:
1. Receive voice messages from Telegram
2. Convert speech to text (STT) using OpenAI Whisper API
3. Send text as prompt to Qwen Code
4. Return response from Qwen Code to user
5. Collect feedback (rating, comment, clarification)
"""

import asyncio
import logging
import os
import io
import tempfile
from typing import Optional, Dict, Any
from datetime import datetime

import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    FSInputFile, InputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

# Load environment variables
load_dotenv()

# ---------- Configuration ----------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # For Whisper STT
QWEN_CODE_API_URL = os.getenv("QWEN_CODE_API_URL", "http://localhost:8080/api")

if not BOT_TOKEN:
    raise ValueError("No TELEGRAM_BOT_TOKEN found in environment variables")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------- Global Storage ----------
# Store conversation history per user
user_conversations: Dict[int, list] = {}
# Store pending feedback data
pending_feedback: Dict[int, Dict[str, Any]] = {}

# ---------- States ----------
class FeedbackStates(StatesGroup):
    waiting_for_rating = State()
    waiting_for_comment = State()
    waiting_for_clarification = State()


# ---------- Speech-to-Text (OpenAI Whisper) ----------
async def speech_to_text(audio_bytes: bytes) -> Optional[str]:
    """
    Convert speech audio bytes to text using OpenAI Whisper API.
    """
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set, STT will not work")
        return None

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }

    # Create form data with audio file
    data = aiohttp.FormData()
    data.add_field(
        'file',
        audio_bytes,
        filename='voice.ogg',
        content_type='audio/ogg'
    )
    data.add_field('model', 'whisper-1')
    data.add_field('language', 'ru')  # Default to Russian

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    text = result.get('text', '').strip()
                    logger.info(f"STT result: {text}")
                    return text
                else:
                    error_text = await resp.text()
                    logger.error(f"STT API error: {resp.status} - {error_text}")
                    return None
    except Exception as e:
        logger.exception(f"Error in speech-to-text: {e}")
        return None


# ---------- Qwen Code API Integration ----------
async def send_to_qwen_code(prompt: str, user_id: int) -> Optional[str]:
    """
    Send prompt to Qwen Code API and get response.
    """
    # Get conversation history for context
    history = user_conversations.get(user_id, [])

    payload = {
        "prompt": prompt,
        "history": history[-10:],  # Last 10 messages for context
        "timestamp": datetime.now().isoformat()
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                QWEN_CODE_API_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    response_text = result.get('response', result.get('answer', str(result)))

                    # Store in conversation history
                    if user_id not in user_conversations:
                        user_conversations[user_id] = []
                    user_conversations[user_id].append({
                        "role": "user",
                        "content": prompt,
                        "timestamp": datetime.now().isoformat()
                    })
                    user_conversations[user_id].append({
                        "role": "assistant",
                        "content": response_text,
                        "timestamp": datetime.now().isoformat()
                    })

                    return response_text
                else:
                    error_text = await resp.text()
                    logger.error(f"Qwen Code API error: {resp.status} - {error_text}")
                    return None
    except aiohttp.ClientError as e:
        logger.exception(f"Network error calling Qwen Code: {e}")
        return None
    except Exception as e:
        logger.exception(f"Error calling Qwen Code: {e}")
        return None


# ---------- Feedback System ----------
async def request_feedback(message: types.Message, response_text: str):
    """
    Request feedback from user after receiving Qwen Code response.
    """
    user_id = message.from_user.id

    # Store pending response for feedback
    pending_feedback[user_id] = {
        "response": response_text,
        "timestamp": datetime.now().isoformat(),
        "prompt": user_conversations.get(user_id, [])[-1]["content"] if user_conversations.get(user_id) else ""
    }

    # Create feedback keyboard
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="⭐⭐⭐⭐⭐", callback_data="rating_5")
    keyboard.button(text="⭐⭐⭐⭐", callback_data="rating_4")
    keyboard.button(text="⭐⭐⭐", callback_data="rating_3")
    keyboard.button(text="⭐⭐", callback_data="rating_2")
    keyboard.button(text="⭐", callback_data="rating_1")
    keyboard.adjust(5)

    keyboard.button(text="💬 Оставить комментарий", callback_data="feedback_comment")
    keyboard.button(text="❓ Уточнить ответ", callback_data="feedback_clarify")
    keyboard.button(text="✅ Готово, спасибо!", callback_data="feedback_done")
    keyboard.adjust(3)

    await message.answer(
        "📊 **Оцените ответ:**\n\n"
        "Нажмите на звёзды для оценки или выберите другой вариант:",
        reply_markup=keyboard.as_markup(),
        parse_mode=ParseMode.MARKDOWN
    )


# ---------- Telegram Bot Initialization ----------
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)


# Main keyboard
def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎤 Голосовое сообщение")],
            [KeyboardButton(text="📝 Текстовый запрос")],
            [KeyboardButton(text="📊 История"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True
    )


# Start command
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "🤖 Я бот для голосового управления **Qwen Code**.\n\n"
        "🎯 **Возможности:**\n"
        "• 🎤 Отправляй голосовые сообщения — я преобразую их в текст и отправлю в Qwen Code\n"
        "• 📝 Или пиши текстовые запросы напрямую\n"
        "• ⭐ Оценивай ответы и оставляй комментарии\n"
        "• 📊 Просматривай историю диалогов\n\n"
        "🚀 **Начни с отправки голосового сообщения!**",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )


# Help command
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """
📖 **Инструкция по использованию:**

**1. Голосовые сообщения:**
• Нажмите и удерживайте кнопку микрофона в Telegram
• Скажите ваш запрос для Qwen Code
• Отправьте сообщение
• Я преобразую голос в текст и отправлю в Qwen Code
• Получите ответ и сможете оценить его

**2. Текстовые запросы:**
• Просто напишите ваш запрос текстом
• Я отправлю его в Qwen Code

**3. Обратная связь:**
• После ответа Qwen Code вы увидите кнопки для оценки
• ⭐⭐⭐⭐⭐ — оценка качества ответа
• 💬 Оставить комментарий — напишите ваш отзыв
• ❓ Уточнить ответ — задайте уточняющий вопрос

**Команды:**
/start — Запустить бота
/help — Эта справка
/history — История диалогов
/clear — Очистить историю
/settings — Настройки
"""
    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)


# History command
@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    user_id = message.from_user.id
    history = user_conversations.get(user_id, [])

    if not history:
        await message.answer("📭 История пуста. Начните диалог с голосового или текстового запроса!")
        return

    # Show last 5 exchanges
    recent = history[-10:]
    lines = ["📊 **История диалога:**\n"]

    for i, msg in enumerate(recent):
        role = "👤 Вы" if msg["role"] == "user" else "🤖 Qwen"
        content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
        lines.append(f"{role}: {content}")

    await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# Clear history command
@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_conversations:
        del user_conversations[user_id]
    if user_id in pending_feedback:
        del pending_feedback[user_id]
    await message.answer("🗑 История диалогов очищена!")


# Settings command
@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    user_id = message.from_user.id
    history_count = len(user_conversations.get(user_id, []))

    settings_text = f"""
⚙️ **Настройки:**

• История сообщений: {history_count}
• STT язык: Русский
• Модель STT: Whisper-1

**Изменить настройки:**
• /language — изменить язык распознавания
• /clear — очистить историю
"""
    await message.answer(settings_text, parse_mode=ParseMode.MARKDOWN)


# Handle voice messages
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user_id = message.from_user.id

    # Send "typing" status
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Get voice file
    voice = message.voice
    file_id = voice.file_id

    # Download voice file
    try:
        file = await bot.get_file(file_id)
        audio_bytes = await bot.download_file(file.file_path)
        audio_data = audio_bytes.read()

        logger.info(f"Received voice message from user {user_id}: {len(audio_data)} bytes")

    except Exception as e:
        logger.exception(f"Error downloading voice file: {e}")
        await message.answer("❌ Ошибка при загрузке голосового сообщения. Попробуйте ещё раз.")
        return

    # Convert speech to text
    status_msg = await message.answer("🎤 Распознаю голос...")

    try:
        text = await speech_to_text(audio_data)

        if not text:
            await status_msg.edit_text("❌ Не удалось распознать голос. Попробуйте ещё раз или отправьте текстом.")
            return

        await status_msg.edit_text(f"📝 Распознано: _{text}_", parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.exception(f"Error in STT: {e}")
        await status_msg.edit_text("❌ Ошибка при распознавании речи.")
        return

    # Send to Qwen Code
    await status_msg.edit_text("🤖 Отправляю в Qwen Code...")

    try:
        response = await send_to_qwen_code(text, user_id)

        if not response:
            await status_msg.edit_text("❌ Ошибка при получении ответа от Qwen Code. Попробуйте позже.")
            return

        # Send response
        await status_msg.delete()
        await message.answer(
            f"🤖 **Ответ Qwen Code:**\n\n{response}",
            parse_mode=ParseMode.MARKDOWN
        )

        # Request feedback
        await request_feedback(message, response)

    except Exception as e:
        logger.exception(f"Error getting Qwen response: {e}")
        await status_msg.edit_text("❌ Ошибка при обработке запроса.")


# Handle text messages (as Qwen prompts)
@dp.message(F.text)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    text = message.text

    # Skip commands and button callbacks
    if text.startswith('/'):
        return

    # Skip if it's a button text
    button_texts = ["🎤 Голосовое сообщение", "📝 Текстовый запрос", "📊 История", "⚙️ Настройки", "❓ Помощь"]
    if text in button_texts:
        await message.answer("👆 Используйте кнопки ниже или отправьте голосовое/текстовое сообщение!")
        return

    # Send "typing" status
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Send to Qwen Code
    status_msg = await message.answer("🤖 Обрабатываю запрос...")

    try:
        response = await send_to_qwen_code(text, user_id)

        if not response:
            await status_msg.edit_text("❌ Ошибка при получении ответа от Qwen Code. Попробуйте позже.")
            return

        await status_msg.delete()
        await message.answer(
            f"🤖 **Ответ Qwen Code:**\n\n{response}",
            parse_mode=ParseMode.MARKDOWN
        )

        # Request feedback
        await request_feedback(message, response)

    except Exception as e:
        logger.exception(f"Error getting Qwen response: {e}")
        await status_msg.edit_text("❌ Ошибка при обработке запроса.")


# Feedback callback handlers
@dp.callback_query(F.data.startswith("rating_"))
async def process_rating(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    rating = callback.data.split("_")[1]

    # Store rating
    if user_id in pending_feedback:
        pending_feedback[user_id]["rating"] = int(rating)
        pending_feedback[user_id]["rating_timestamp"] = datetime.now().isoformat()

    # Log feedback
    logger.info(f"User {user_id} rated: {rating} stars")

    # Update message
    stars = "⭐" * int(rating)
    await callback.message.edit_text(f"✅ Спасибо за оценку: {stars}")

    # Offer to leave a comment
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="💬 Оставить комментарий", callback_data="feedback_comment")
    keyboard.button(text="✅ Готово!", callback_data="feedback_done")
    keyboard.adjust(1)

    await callback.message.answer(
        "Хотите оставить комментарий к оценке?",
        reply_markup=keyboard.as_markup()
    )


@dp.callback_query(F.data == "feedback_comment")
async def process_comment_request(callback: types.CallbackQuery):
    await callback.message.answer(
        "📝 Напишите ваш комментарий (или отправьте голосовым):"
    )
    await callback.answer()


@dp.callback_query(F.data == "feedback_clarify")
async def process_clarify_request(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if user_id in pending_feedback:
        pending_feedback[user_id]["clarification_requested"] = True

    await callback.message.answer(
        "❓ Напишите ваш уточняющий вопрос, и я отправлю его в Qwen Code:"
    )
    await callback.answer()


@dp.callback_query(F.data == "feedback_done")
async def process_feedback_done(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    # Log final feedback
    if user_id in pending_feedback:
        feedback = pending_feedback[user_id]
        logger.info(f"Feedback completed for user {user_id}: {feedback}")

        # Clear pending feedback
        del pending_feedback[user_id]

    await callback.message.answer("✅ Спасибо за обратную связь!")
    await callback.answer()


# Handle clarification messages
@dp.message(F.text, FeedbackStates.waiting_for_clarification)
async def process_clarification_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    clarification = message.text

    # Send clarification to Qwen Code
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Get original context
    original_prompt = ""
    original_response = ""
    if user_id in pending_feedback:
        original_prompt = pending_feedback[user_id].get("prompt", "")
        original_response = pending_feedback[user_id].get("response", "")

    # Build clarification prompt
    full_prompt = f"""
Original request: {original_prompt}
Original response: {original_response}

User clarification question: {clarification}

Please provide a more detailed or clarified answer.
"""

    response = await send_to_qwen_code(full_prompt, user_id)

    if response:
        await message.answer(
            f"🤖 **Уточнённый ответ:**\n\n{response}",
            parse_mode=ParseMode.MARKDOWN
        )
        await request_feedback(message, response)
    else:
        await message.answer("❌ Ошибка при получении уточнённого ответа.")

    await state.clear()


# Handle comment messages
@dp.message(F.text)
async def process_comment_text(message: types.Message):
    user_id = message.from_user.id
    comment = message.text

    # Check if user is in feedback mode
    if user_id in pending_feedback and pending_feedback[user_id].get("comment_requested"):
        pending_feedback[user_id]["comment"] = comment
        pending_feedback[user_id]["comment_timestamp"] = datetime.now().isoformat()

        logger.info(f"User {user_id} left comment: {comment}")

        await message.answer("✅ Спасибо за ваш комментарий!")

        # Clear pending
        del pending_feedback[user_id]
        return

    # Otherwise, treat as normal text message (handled by handle_text)
    await handle_text(message)


# Handle voice comments
@dp.message(F.voice)
async def handle_voice_comment(message: types.Message):
    user_id = message.from_user.id

    # Check if user is in feedback mode
    if user_id in pending_feedback and pending_feedback[user_id].get("comment_requested"):
        # Download and transcribe
        voice = message.voice
        file = await bot.get_file(voice.file_id)
        audio_bytes = await bot.download_file(file.file_path)

        text = await speech_to_text(audio_bytes.read())

        if text:
            pending_feedback[user_id]["comment"] = f"(voice) {text}"
            await message.answer(f"✅ Комментарий принят: _{text}_", parse_mode=ParseMode.MARKDOWN)
            del pending_feedback[user_id]
        else:
            await message.answer("❌ Не удалось распознать голосовой комментарий.")
        return

    # Otherwise, handle as normal voice message
    await handle_voice(message)


# ---------- Main ----------
async def main():
    logger.info("Starting Qwen Code Voice Bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
