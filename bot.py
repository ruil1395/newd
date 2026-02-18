"""
Telegram Bot for Voice-Controlled Qwen Code
FREE VERSION - No OpenAI API, uses Vosk STT and file-based queue

Features:
1. Receive voice messages from Telegram
2. Convert speech to text using Vosk (free, offline)
3. Send text as prompt to Qwen Code via file queue
4. Return response from Qwen Code to user
"""

import asyncio
import logging
import os
import io
import json
import uuid
import wave
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode

# Vosk imports
from vosk import Model, KaldiRecognizer

# Load environment variables
load_dotenv()

# ---------- Configuration ----------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Paths for file-based queue
QUEUE_DIR = Path(os.getenv("QUEUE_DIR", "/tmp/qwen_queue"))
RESPONSES_DIR = Path(os.getenv("RESPONSES_DIR", "/tmp/qwen_responses"))
VOSK_MODEL_PATH = Path(os.getenv("VOSK_MODEL_PATH", "./vosk-model-ru"))

# Create directories
QUEUE_DIR.mkdir(parents=True, exist_ok=True)
RESPONSES_DIR.mkdir(parents=True, exist_ok=True)

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
# Vosk model (loaded once)
vosk_model: Optional[Model] = None


# ---------- Vosk Speech-to-Text ----------
def load_vosk_model():
    """Load Vosk model for Russian speech recognition."""
    global vosk_model
    model_path = VOSK_MODEL_PATH
    
    if not model_path.exists():
        logger.error(f"Vosk model not found at {model_path}")
        logger.error("Please download the model:")
        logger.error("  wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip")
        logger.error("  unzip vosk-model-small-ru-0.22.zip")
        logger.error("  mv vosk-model-small-ru-0.22 ./vosk-model-ru")
        return None
    
    try:
        vosk_model = Model(str(model_path))
        logger.info(f"Vosk model loaded from {model_path}")
        return vosk_model
    except Exception as e:
        logger.exception(f"Error loading Vosk model: {e}")
        return None


def convert_ogg_to_wav(ogg_data: bytes) -> bytes:
    """Convert OGG audio to WAV format for Vosk."""
    try:
        from pydub import AudioSegment

        ogg_buffer = io.BytesIO(ogg_data)
        
        # Try different formats
        audio = None
        for fmt in ["ogg", "mp3", "wav", "webm"]:
            try:
                ogg_buffer.seek(0)
                audio = AudioSegment.from_file(ogg_buffer, format=fmt)
                logger.info(f"Audio loaded as {fmt}")
                break
            except:
                continue
        
        if audio is None:
            # Last resort: try without format specification
            ogg_buffer.seek(0)
            audio = AudioSegment.from_file(ogg_buffer)
            logger.info("Audio loaded with auto-detect format")

        # Convert to mono 16kHz 16-bit (Vosk requirements)
        logger.info(f"Original audio: {audio.frame_rate}Hz, {audio.channels} channels, {audio.sample_width} bytes")
        audio = audio.set_channels(1)
        audio = audio.set_frame_rate(16000)
        audio = audio.set_sample_width(2)  # 16-bit
        logger.info(f"Converted audio: {audio.frame_rate}Hz, {audio.channels} channels, {audio.sample_width} bytes")

        wav_buffer = io.BytesIO()
        audio.export(wav_buffer, format="wav")
        wav_buffer.seek(0)

        wav_data = wav_buffer.read()
        logger.info(f"WAV size: {len(wav_data)} bytes")
        return wav_data
        
    except Exception as e:
        logger.exception(f"Error converting audio: {e}")
        # Fallback: return original data
        logger.warning("Returning original data without conversion")
        return ogg_data


async def speech_to_text(audio_bytes: bytes) -> Optional[str]:
    """
    Convert speech audio bytes to text using Vosk (offline, free).
    """
    global vosk_model

    logger.info(f"STT: Received {len(audio_bytes)} bytes of audio data")

    if vosk_model is None:
        logger.warning("STT: Model not loaded, attempting to load...")
        vosk_model = load_vosk_model()

    if vosk_model is None:
        logger.error("STT: Failed to load model")
        return None

    try:
        # Convert OGG to WAV
        logger.info("STT: Converting OGG to WAV...")
        wav_data = convert_ogg_to_wav(audio_bytes)
        logger.info(f"STT: Converted to {len(wav_data)} bytes WAV")
        
        wav_buffer = io.BytesIO(wav_data)

        # Open WAV file
        with wave.open(wav_buffer, "rb") as wf:
            # Check audio properties
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            duration = n_frames / sample_rate if sample_rate > 0 else 0
            logger.info(f"STT: WAV properties - {sample_rate}Hz, {n_frames} frames, {duration:.2f}s")

            # Create recognizer
            recognizer = KaldiRecognizer(vosk_model, sample_rate)
            recognizer.SetWords(True)  # Enable word-level timestamps

            # Process audio in chunks
            text_parts = []
            chunk_num = 0
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                chunk_num += 1

                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    if result.get("text"):
                        logger.info(f"STT: Partial result: {result['text']}")
                        text_parts.append(result["text"])
                else:
                    # Get partial results
                    partial = json.loads(recognizer.PartialResult())
                    if partial.get("partial"):
                        logger.debug(f"STT: Partial: {partial['partial']}")

            # Get final result
            logger.info("STT: Getting final result...")
            final_result = json.loads(recognizer.FinalResult())
            if final_result.get("text"):
                logger.info(f"STT: Final result: {final_result['text']}")
                text_parts.append(final_result["text"])
            else:
                logger.warning("STT: No text recognized in final result")

            full_text = " ".join(text_parts).strip()
            logger.info(f"STT: Complete text: '{full_text}'")
            return full_text if full_text else None

    except Exception as e:
        logger.exception(f"STT: Error during recognition: {e}")
        import traceback
        traceback.print_exc()
        return None


# ---------- File Queue Integration ----------
async def send_to_qwen_code(prompt: str, user_id: int) -> Optional[str]:
    """
    Send prompt to Qwen Code via file queue and wait for response.
    
    File queue mechanism:
    1. Create request file in QUEUE_DIR
    2. Wait for response file in RESPONSES_DIR
    3. Return response content
    """
    # Get conversation history for context
    history = user_conversations.get(user_id, [])
    
    # Create unique request ID
    request_id = str(uuid.uuid4())
    
    # Create request payload
    request_data = {
        "id": request_id,
        "user_id": user_id,
        "prompt": prompt,
        "history": history[-10:],  # Last 10 messages for context
        "timestamp": datetime.now().isoformat()
    }
    
    # Write request file
    request_file = QUEUE_DIR / f"{request_id}.json"
    try:
        with open(request_file, "w", encoding="utf-8") as f:
            json.dump(request_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Request {request_id} written to queue")
    except Exception as e:
        logger.exception(f"Error writing request file: {e}")
        return None
    
    # Wait for response (polling)
    response_file = RESPONSES_DIR / f"{request_id}.json"
    max_wait = 60  # Maximum wait time in seconds
    poll_interval = 1  # Poll every second
    waited = 0
    
    while waited < max_wait:
        await asyncio.sleep(poll_interval)
        waited += poll_interval
        
        if response_file.exists():
            try:
                # Read response
                with open(response_file, "r", encoding="utf-8") as f:
                    response_data = json.load(f)
                
                response_text = response_data.get("response", response_data.get("answer", ""))
                
                # Clean up response file
                try:
                    response_file.unlink()
                except:
                    pass
                
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
                
                # Clean up request file
                try:
                    request_file.unlink()
                except:
                    pass
                
                logger.info(f"Response received for request {request_id}")
                return response_text
                
            except Exception as e:
                logger.exception(f"Error reading response file: {e}")
                return None
    
    # Timeout - clean up request file
    logger.warning(f"Timeout waiting for response {request_id}")
    try:
        request_file.unlink()
    except:
        pass
    return None


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
        "• 🎤 Отправляй голосовые сообщения — я преобразую их в текст (Vosk STT)\n"
        "• 📝 Или пиши текстовые запросы напрямую\n"
        "• 📊 Просматривай историю диалогов\n\n"
        "🚀 **Начни с отправки голосового сообщения!**\n\n"
        "💡 *Все компоненты бесплатные и работают локально*",
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
• Я преобразую голос в текст (Vosk, бесплатно)
• Отправлю запрос в Qwen Code через файл-очередь
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
/status — Статус системы
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

    # Show last 10 exchanges
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
    await message.answer("🗑 История диалогов очищена!")


# Settings command
@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    user_id = message.from_user.id
    history_count = len(user_conversations.get(user_id, []))

    settings_text = f"""
⚙️ **Настройки:**

• История сообщений: {history_count}
• STT язык: Русский (Vosk)
• Модель STT: {VOSK_MODEL_PATH.name}
• Очередь: {QUEUE_DIR}

**Изменить настройки:**
• /clear — очистить историю
• /status — статус системы
"""
    await message.answer(settings_text, parse_mode=ParseMode.MARKDOWN)


# Status command
@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    """Check system status."""
    status_lines = ["🔍 **Статус системы:**\n"]
    
    # Check Vosk model
    if vosk_model is not None:
        status_lines.append("✅ Vosk модель: загружена")
    elif VOSK_MODEL_PATH.exists():
        status_lines.append("⚠️ Vosk модель: файл есть, не загружена")
    else:
        status_lines.append("❌ Vosk модель: не найдена")
    
    # Check queue directories
    queue_count = len(list(QUEUE_DIR.glob("*.json")))
    response_count = len(list(RESPONSES_DIR.glob("*.json")))
    status_lines.append(f"📁 Очередь запросов: {queue_count} файлов")
    status_lines.append(f"📁 Очередь ответов: {response_count} файлов")
    
    # Bot info
    status_lines.append(f"🤖 Бот: @{(await bot.get_me()).username}")
    
    await message.answer("\n".join(status_lines), parse_mode=ParseMode.MARKDOWN)


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
    status_msg = await message.answer("🎤 Распознаю голос (Vosk)...")

    try:
        text = await speech_to_text(audio_data)

        if not text:
            await status_msg.edit_text("❌ Не удалось распознать голос. Попробуйте ещё раз или отправьте текстом.\n\nУбедитесь, что модель Vosk загружена (/status)")
            return

        await status_msg.edit_text(f"📝 Распознано: _{text}_", parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.exception(f"Error in STT: {e}")
        await status_msg.edit_text("❌ Ошибка при распознавании речи.")
        return

    # Send to Qwen Code via file queue
    await status_msg.edit_text("🤖 Отправляю в Qwen Code (файл-очередь)...")

    try:
        response = await send_to_qwen_code(text, user_id)

        if not response:
            await status_msg.edit_text("❌ Ошибка при получении ответа от Qwen Code. Проверьте, что обработчик очереди запущен.\n\nОчередь: `/tmp/qwen_queue`")
            return

        # Send response
        await status_msg.delete()
        await message.answer(
            f"🤖 **Ответ Qwen Code:**\n\n{response}",
            parse_mode=ParseMode.MARKDOWN
        )

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
            await status_msg.edit_text("❌ Ошибка при получении ответа от Qwen Code.")
            return

        await status_msg.delete()
        await message.answer(
            f"🤖 **Ответ Qwen Code:**\n\n{response}",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.exception(f"Error getting Qwen response: {e}")
        await status_msg.edit_text("❌ Ошибка при обработке запроса.")


# ---------- Queue Monitor (optional background task) ----------
async def queue_monitor():
    """Background task to monitor queue status."""
    while True:
        await asyncio.sleep(60)  # Check every minute
        queue_count = len(list(QUEUE_DIR.glob("*.json")))
        if queue_count > 0:
            logger.info(f"Queue status: {queue_count} pending requests")


# ---------- Main ----------
async def main():
    logger.info("Starting Qwen Code Voice Bot (FREE VERSION)...")
    logger.info(f"Vosk model path: {VOSK_MODEL_PATH}")
    logger.info(f"Queue directory: {QUEUE_DIR}")
    logger.info(f"Responses directory: {RESPONSES_DIR}")
    
    # Load Vosk model
    load_vosk_model()
    
    # Start queue monitor
    asyncio.create_task(queue_monitor())
    
    logger.info("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
