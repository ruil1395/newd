import asyncio
import logging
import re
import os
import time
import random
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any

import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

# Загружаем переменные окружения из .env
load_dotenv()

# ---------- Конфигурация ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables")

OPENDOTA_API_BASE = "https://api.opendota.com/api"
REQUEST_TIMEOUT = 30
CACHE_TTL = 3600  # 1 час
REQUEST_DELAY = 1.0  # задержка между запросами (чтобы не получить 429)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------- Глобальные кеши ----------
hero_winrate_cache = {
    "data": {},           # hero_id -> winrate, pick_rate, etc.
    "last_updated": 0
}

hero_matchups_cache = {}  # hero_id -> {opponent_id: winrate, ...} с timestamp
hero_list_cache = {       # кеш для списка героев
    "data": {},
    "last_updated": 0
}

# Маппинг hero_id -> имя и наоборот
hero_id_to_name = {}
hero_name_to_id = {}

# Добавим русские названия вручную для основных героев
RUSSIAN_HERO_NAMES = {
    "пудж": "pudge",
    "пульс": "pudge",
    "лина": "lina",
    "топор": "axe",
    "антимаг": "anti-mage",
    "анти": "anti-mage",
    "юггернаут": "juggernaut",
    "юггер": "juggernaut",
    "тайдхантер": "tidehunter",
    "тайд": "tidehunter",
    "спирит брейкер": "spirit_breaker",
    "спирит": "spirit_breaker",
    "клокверк": "clockwerk",
    "клок": "clockwerk",
    "инвокер": "invoker",
    "инвок": "invoker",
    "тень": "shadow_fiend",
    "сф": "shadow_fiend",
    "сларк": "slark",
    "фатом ассасин": "phantom_assassin",
    "па": "phantom_assassin",
    "ведьмак": "witch_doctor",
    "вд": "witch_doctor",
    "лич": "lich",
    "брудмазер": "broodmother",
    "бруд": "broodmother",
    "снэпфайр": "snapfire",
    "снэп": "snapfire",
    "бэтрайдер": "batrider",
    "бэт": "batrider",
    "древняя": "ancient_apparition",
    "аа": "ancient_apparition",
    "ларго": "largo",
}

# ---------- Инициализация маппинга героев ----------
async def fetch_heroes_list() -> Dict[int, str]:
    """Получает список героев с OpenDota и строит маппинг."""
    # Проверяем кеш
    now = time.time()
    if hero_list_cache["last_updated"] and now - hero_list_cache["last_updated"] < CACHE_TTL:
        return hero_list_cache["data"]
    
    url = f"{OPENDOTA_API_BASE}/heroes"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    heroes = await resp.json()
                    mapping = {}
                    for h in heroes:
                        hero_id_to_name[h["id"]] = h["localized_name"]
                        # Добавляем английское имя в нижнем регистре
                        eng_name = h["localized_name"].lower()
                        hero_name_to_id[eng_name] = h["id"]
                        
                        # Добавляем русские имена из нашего словаря
                        for rus_name, eng in RUSSIAN_HERO_NAMES.items():
                            if eng == eng_name or eng == h["localized_name"].lower():
                                hero_name_to_id[rus_name] = h["id"]
                    
                    hero_list_cache["data"] = hero_id_to_name
                    hero_list_cache["last_updated"] = now
                    logger.info(f"Loaded {len(heroes)} heroes")
                    return hero_id_to_name
                else:
                    logger.error(f"Failed to fetch heroes list: {resp.status}")
                    return {}
    except Exception as e:
        logger.exception("Error fetching heroes list")
        return {}

# ---------- 1. Динамические винрейты (обновление раз в час) ----------
async def update_winrates():
    """Фоновая задача: обновляет винрейты героев с OpenDota."""
    global hero_winrate_cache
    while True:
        try:
            logger.info("Updating winrates from OpenDota...")
            # Добавляем случайную задержку, чтобы не попасть под 429
            await asyncio.sleep(random.uniform(1, 3))
            
            url = f"{OPENDOTA_API_BASE}/heroStats"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                    if resp.status == 200:
                        stats = await resp.json()
                        new_data = {}
                        for h in stats:
                            hero_id = h["id"]
                            # 8.0 - верные ключи из API OpenDota
                            winrate = h.get("win_rate", 50.0)
                            pick_rate = h.get("pick_rate", 5.0)
                            new_data[hero_id] = {
                                "winrate": winrate,
                                "pick_rate": pick_rate,
                                "name": h.get("localized_name", f"Hero {hero_id}")
                            }
                        hero_winrate_cache["data"] = new_data
                        hero_winrate_cache["last_updated"] = time.time()
                        logger.info(f"Winrates updated: {len(new_data)} heroes")
                    elif resp.status == 429:
                        logger.warning("Rate limited (429), waiting longer...")
                        await asyncio.sleep(60)  # ждём минуту при 429
                    else:
                        logger.error(f"Failed to fetch heroStats: {resp.status}")
        except Exception as e:
            logger.exception("Error updating winrates")

        await asyncio.sleep(CACHE_TTL)

def get_hero_winrate(hero_id: int) -> float:
    data = hero_winrate_cache["data"].get(hero_id)
    return data["winrate"] if data else 50.0

def get_hero_pickrate(hero_id: int) -> float:
    data = hero_winrate_cache["data"].get(hero_id)
    return data["pick_rate"] if data else 5.0

# ---------- Реальная база контр-пиков (матчапы) ----------
async def get_hero_matchups(hero_id: int) -> Dict[int, float]:
    """Возвращает словарь {opponent_id: winrate} для героя (с кешированием)."""
    now = time.time()
    
    # Проверяем кеш
    if hero_id in hero_matchups_cache:
        data, ts = hero_matchups_cache[hero_id]
        if now - ts < CACHE_TTL:
            return data

    # Добавляем задержку, чтобы избежать 429
    await asyncio.sleep(REQUEST_DELAY)
    
    url = f"{OPENDOTA_API_BASE}/heroes/{hero_id}/matchups"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    matchups = await resp.json()
                    result = {}
                    for m in matchups:
                        # Проверяем наличие ключей и достаточное количество игр
                        if "hero_id" in m and "games_played" in m and m["games_played"] > 100:
                            if "wins" in m:
                                winrate = (m["wins"] / m["games_played"]) * 100
                                result[m["hero_id"]] = winrate
                    hero_matchups_cache[hero_id] = (result, now)
                    logger.info(f"Loaded {len(result)} matchups for hero {hero_id}")
                    return result
                elif resp.status == 429:
                    logger.warning(f"Rate limited for hero {hero_id}, waiting...")
                    await asyncio.sleep(30)
                    return {}
                else:
                    logger.error(f"Failed matchups for hero {hero_id}: {resp.status}")
                    return {}
    except Exception as e:
        logger.exception(f"Error fetching matchups for {hero_id}")
        return {}

async def get_counter_advantage(our_hero_id: int, enemy_hero_id: int) -> float:
    """Возвращает преимущество (в процентах) нашего героя против вражеского на основе статистики."""
    try:
        matchups = await get_hero_matchups(our_hero_id)
        return matchups.get(enemy_hero_id, 50.0) - 50.0
    except Exception as e:
        logger.error(f"Error calculating counter advantage: {e}")
        return 0.0

# ---------- Анализ игрока по Steam ID ----------
async def fetch_player_recent_matches(steam_id: str, limit: int = 20) -> Optional[List[Dict]]:
    """Получает последние матчи игрока через OpenDota."""
    await asyncio.sleep(REQUEST_DELAY)  # задержка
    
    url = f"{OPENDOTA_API_BASE}/players/{steam_id}/recentMatches"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    matches = await resp.json()
                    return matches[:limit]
                elif resp.status == 429:
                    logger.warning(f"Rate limited for player {steam_id}")
                    return None
                else:
                    logger.error(f"Failed player matches for {steam_id}: {resp.status}")
                    return None
    except Exception as e:
        logger.exception("Error fetching player matches")
        return None

def analyze_player_matches(matches: List[Dict]) -> str:
    """Анализирует список матчей игрока и возвращает текст."""
    if not matches:
        return "Нет данных о матчах."

    total = len(matches)
    wins = 0
    for m in matches:
        player_slot = m.get("player_slot", 0)
        radiant_win = m.get("radiant_win", False)
        if (player_slot < 128 and radiant_win) or (player_slot >= 128 and not radiant_win):
            wins += 1
    winrate = (wins / total) * 100 if total else 0

    hero_counts = defaultdict(int)
    for m in matches:
        hero_id = m.get("hero_id")
        if hero_id:
            hero_counts[hero_id] += 1

    top_heroes = sorted(hero_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    # Средние показатели
    total_kda = 0
    total_gpm = 0
    total_xpm = 0
    for m in matches:
        kills = m.get("kills", 0)
        deaths = m.get("deaths", 1)
        assists = m.get("assists", 0)
        if deaths > 0:
            total_kda += (kills + assists) / deaths
        total_gpm += m.get("gold_per_min", 0)
        total_xpm += m.get("xp_per_min", 0)
    
    avg_kda = total_kda / total if total else 0
    avg_gpm = total_gpm / total if total else 0
    avg_xpm = total_xpm / total if total else 0

    result = f"📊 **Анализ игрока** (последние {total} матчей)\n"
    result += f"🏆 Винрейт: {winrate:.1f}%\n"
    result += f"💀 Средний KDA: {avg_kda:.2f}\n"
    result += f"💰 GPM: {avg_gpm:.0f} | XPM: {avg_xpm:.0f}\n\n"

    result += "**Любимые герои:**\n"
    for hero_id, count in top_heroes:
        hero_name = hero_id_to_name.get(hero_id, f"ID {hero_id}")
        result += f"• {hero_name}: {count} игр ({count/total*100:.1f}%)\n"

    # Последние 5 матчей
    last_5 = matches[:5]
    result += "\n**Последние 5 матчей:**\n"
    for i, m in enumerate(last_5, 1):
        hero_name = hero_id_to_name.get(m.get("hero_id"), "Unknown")
        player_slot = m.get("player_slot", 0)
        radiant_win = m.get("radiant_win", False)
        win = "✅" if ((player_slot < 128) == radiant_win) else "❌"
        result += f"{i}. {hero_name} {win} | K/D/A: {m.get('kills',0)}/{m.get('deaths',0)}/{m.get('assists',0)}\n"

    return result

# ---------- Функции предсказания ----------
async def predict_next_picks_dynamic(enemies: List[int]) -> List[Tuple[int, float, str]]:
    """Топ-3 следующих пика врагов на основе реальных данных."""
    if not hero_winrate_cache["data"]:
        return []
    
    weights = {}
    reasons = {}

    for hero_id, data in hero_winrate_cache["data"].items():
        if hero_id not in enemies:
            # Вес = винрейт * пикрейт (нормируем)
            weights[hero_id] = data["winrate"] * data["pick_rate"] / 100
            reasons[hero_id] = f"мета (wr {data['winrate']:.1f}%, pick {data['pick_rate']:.1f}%)"

    if not weights:
        return []
    
    total = sum(weights.values())
    if total == 0:
        return []

    sorted_heroes = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:3]
    top3 = []
    for hero_id, weight in sorted_heroes:
        prob = (weight / total) * 100
        reason = reasons.get(hero_id, "популярный")
        top3.append((hero_id, prob, reason))
    return top3

async def recommend_allies_dynamic(enemies: List[int], allies: List[int]) -> List[Tuple[int, float, str]]:
    """Рекомендации на основе реальных матчапов."""
    if not hero_winrate_cache["data"]:
        return []
    
    scores = {}
    reasons = {}

    candidates = set(hero_winrate_cache["data"].keys()) - set(allies)

    for hero_id in candidates:
        score = 0
        reason_list = []

        # Считаем преимущество против каждого врага (максимум 5 врагов)
        counter_score = 0
        for e in enemies[:5]:  # ограничиваем количество запросов
            adv = await get_counter_advantage(hero_id, e)
            if adv > 5:
                counter_score += adv
                e_name = hero_id_to_name.get(e, f"id{e}")
                reason_list.append(f"+{adv:.1f}% против {e_name}")
        
        score += counter_score

        # Бонус за винрейт героя
        wr = get_hero_winrate(hero_id)
        score += wr * 0.3
        reason_list.append(f"винрейт {wr:.1f}%")

        if score > 0:
            scores[hero_id] = score
            reasons[hero_id] = ", ".join(reason_list[:3])  # ограничим длину причины

    if not scores:
        # Если нет данных по контр-пикам, используем просто винрейт
        for hero_id in candidates:
            wr = get_hero_winrate(hero_id)
            if wr > 52:  # только сильные герои
                scores[hero_id] = wr
                reasons[hero_id] = f"винрейт {wr:.1f}%"

    if not scores:
        return []

    sorted_heroes = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
    top3 = []
    for hero_id, score in sorted_heroes:
        win_chance = min(95, 50 + score)
        reason = reasons.get(hero_id, "универсальный")
        top3.append((hero_id, win_chance, reason))
    return top3

# ---------- Telegram Bot ----------
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Состояния
class PredictStates(StatesGroup):
    waiting_for_enemies = State()
    waiting_for_allies = State()

class MatchStates(StatesGroup):
    waiting_for_match_id = State()

class PlayerStates(StatesGroup):
    waiting_for_steam_id = State()

class HeroStates(StatesGroup):
    waiting_for_hero_name = State()

# Клавиатуры
def get_main_keyboard():
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/predict"), KeyboardButton(text="/match")],
            [KeyboardButton(text="/player"), KeyboardButton(text="/hero")],
            [KeyboardButton(text="/help")]
        ],
        resize_keyboard=True
    )
    return kb

# Команды
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я про-аналитик Dota 2 с **живыми данными OpenDota**.\n\n"
        "🔮 **Команды:**\n"
        "/predict — предсказать пики (с реальной статистикой)\n"
        "/match <ID> — глубокий анализ матча\n"
        "/player <steam_id> — анализ игрока (последние матчи)\n"
        "/hero <имя> — информация о герое (винрейт, пикрейт)\n"
        "/help — помощь\n\n"
        "Поехали!",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "🔍 **Как пользоваться:**\n\n"
        "**/predict** — введи имена врагов (например, Pudge Lina), затем свои пики (или 'нет').\n"
        "**/match 123456789** — анализ конкретного матча.\n"
        "**/player 123456789** — анализ игрока по Steam ID.\n"
        "**/hero Juggernaut** — информация о герое (можно по-русски).\n\n"
        "Все данные обновляются каждый час с OpenDota."
    )

@dp.message(Command("predict"))
async def cmd_predict(message: types.Message, state: FSMContext):
    await message.answer("🛡 Введи **пики врагов** (имена через пробел):\nПример: Pudge Lina Axe")
    await state.set_state(PredictStates.waiting_for_enemies)

@dp.message(PredictStates.waiting_for_enemies)
async def process_enemies(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    names = re.split(r'[,\s]+', text)
    enemy_ids = []
    unknown = []
    
    for name in names:
        if name in hero_name_to_id:
            enemy_ids.append(hero_name_to_id[name])
        else:
            unknown.append(name)
    
    if unknown:
        await message.answer(f"Неизвестные герои: {', '.join(unknown)}. Попробуй ещё раз.")
        return
    
    await state.update_data(enemies=enemy_ids)
    await message.answer("👥 Теперь введи **свои пики** (или 'нет'):\nПример: Juggernaut Lich")
    await state.set_state(PredictStates.waiting_for_allies)

@dp.message(PredictStates.waiting_for_allies)
async def process_allies(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    if text in ["нет", "skip", "-"]:
        ally_ids = []
    else:
        names = re.split(r'[,\s]+', text)
        ally_ids = []
        unknown = []
        for name in names:
            if name in hero_name_to_id:
                ally_ids.append(hero_name_to_id[name])
            else:
                unknown.append(name)
        if unknown:
            await message.answer(f"Неизвестные герои: {', '.join(unknown)}. Попробуй ещё раз.")
            return
    
    await state.update_data(allies=ally_ids)
    
    # Отправляем "печатает..." чтобы пользователь знал, что бот работает
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    data = await state.get_data()
    enemies = data["enemies"]
    allies = data.get("allies", [])

    # Отправляем сообщение о загрузке
    loading_msg = await message.answer("⏳ Анализирую данные... (может занять до 30 секунд)")

    try:
        # Получаем предсказания
        next_picks = await predict_next_picks_dynamic(enemies)
        recommendations = await recommend_allies_dynamic(enemies, allies)

        # Удаляем сообщение о загрузке
        await loading_msg.delete()

        lines = ["🔮 **Аналитика на живых данных**\n"]
        lines.append("**Скорее всего враги возьмут:**")
        if next_picks:
            for hero_id, prob, reason in next_picks:
                name = hero_id_to_name.get(hero_id, f"Hero {hero_id}")
                lines.append(f"• {name} — {prob:.1f}% ({reason})")
        else:
            lines.append("• Недостаточно данных для прогноза.")
        lines.append("")

        lines.append("**Наш топ-пик:**")
        if recommendations:
            for hero_id, winrate, reason in recommendations:
                name = hero_id_to_name.get(hero_id, f"Hero {hero_id}")
                lines.append(f"• {name} — {winrate:.1f}% побед")
                lines.append(f"  🎯 {reason}")
        else:
            lines.append("• Нет данных для рекомендаций.")

        if recommendations:
            best_id = recommendations[0][0]
            best_name = hero_id_to_name.get(best_id, "Unknown")
            lines.append(f"\n⚡ Бери **{best_name}** и рви их, бро!")
        else:
            lines.append("\n⚡ Попробуй взять метового героя с высоким винрейтом.")

        await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await loading_msg.delete()
        logger.exception("Error in predict")
        await message.answer("❌ Произошла ошибка при анализе. Попробуй позже.")
    
    await state.clear()

@dp.message(Command("match"))
async def cmd_match(message: types.Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        match_id = args[1].strip()
        await analyze_and_send_match(message, match_id)
    else:
        await message.answer("🔍 Введи **ID матча**:\nПример: /match 1234567890")
        await state.set_state(MatchStates.waiting_for_match_id)

@dp.message(MatchStates.waiting_for_match_id)
async def process_match_id(message: types.Message, state: FSMContext):
    match_id = message.text.strip()
    await analyze_and_send_match(message, match_id)
    await state.clear()

async def analyze_and_send_match(message: types.Message, match_id: str):
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    loading_msg = await message.answer(f"⏳ Анализирую матч {match_id}...")
    
    await asyncio.sleep(REQUEST_DELAY)
    
    url = f"{OPENDOTA_API_BASE}/matches/{match_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    await loading_msg.delete()
                    
                    result_text = f"📊 **Матч {match_id}**\n"
                    duration = data.get("duration", 0)
                    minutes = duration // 60
                    seconds = duration % 60
                    result_text += f"⏱ Длительность: {minutes}:{seconds:02d}\n"
                    result_text += f"🏆 Победила: {'Radiant' if data.get('radiant_win') else 'Dire'}\n\n"

                    # Топ по урону
                    players = data.get("players", [])
                    if players:
                        sorted_damage = sorted(players, key=lambda x: x.get("hero_damage", 0), reverse=True)[:3]
                        result_text += "**Топ по урону:**\n"
                        for p in sorted_damage:
                            hero_name = hero_id_to_name.get(p.get("hero_id"), f"ID {p.get('hero_id')}")
                            result_text += f"• {hero_name}: {p.get('hero_damage', 0):,}\n"

                    result_text += f"\n🔗 [Dotabuff](https://www.dotabuff.com/matches/{match_id})"
                    await message.answer(result_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
                else:
                    await loading_msg.delete()
                    await message.answer(f"❌ Матч не найден или ошибка API (код {resp.status}).")
    except Exception as e:
        await loading_msg.delete()
        logger.exception("Error fetching match")
        await message.answer("❌ Ошибка при получении данных.")

@dp.message(Command("player"))
async def cmd_player(message: types.Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        steam_id = args[1].strip()
        await analyze_player(message, steam_id)
    else:
        await message.answer("👤 Введи **Steam ID** (число или ссылка на профиль):\nПример: /player 123456789")
        await state.set_state(PlayerStates.waiting_for_steam_id)

@dp.message(PlayerStates.waiting_for_steam_id)
async def process_steam_id(message: types.Message, state: FSMContext):
    steam_id = message.text.strip()
    # Извлечь число из ссылки, если нужно
    match = re.search(r'\d+', steam_id)
    if match:
        steam_id = match.group()
    await analyze_player(message, steam_id)
    await state.clear()

async def analyze_player(message: types.Message, steam_id: str):
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    loading_msg = await message.answer(f"⏳ Загружаю данные игрока {steam_id}...")
    
    matches = await fetch_player_recent_matches(steam_id)
    
    await loading_msg.delete()
    
    if matches is None:
        await message.answer("❌ Не удалось получить данные. Проверь Steam ID или попробуй позже.")
        return
    
    if not matches:
        await message.answer("У игрока нет публичных матчей или они скрыты.")
        return
        
    analysis = analyze_player_matches(matches)
    await message.answer(analysis, parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("hero"))
async def cmd_hero(message: types.Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        hero_name = args[1].strip()
        await send_hero_info(message, hero_name)
    else:
        await message.answer("🧙 Введи **имя героя**:\nПример: /hero Juggernaut")
        await state.set_state(HeroStates.waiting_for_hero_name)

@dp.message(HeroStates.waiting_for_hero_name)
async def process_hero_name(message: types.Message, state: FSMContext):
    hero_name = message.text.strip()
    await send_hero_info(message, hero_name)
    await state.clear()

async def send_hero_info(message: types.Message, hero_input: str):
    name_lower = hero_input.lower()
    hero_id = hero_name_to_id.get(name_lower)
    
    if not hero_id:
        await message.answer("🤔 Не могу найти такого героя. Попробуй английское имя (например, Pudge).")
        return

    hero_name = hero_id_to_name.get(hero_id, hero_input)
    wr = get_hero_winrate(hero_id)
    pick = get_hero_pickrate(hero_id)

    text = f"**{hero_name}** — живые данные OpenDota\n"
    text += f"📊 Винрейт: {wr:.1f}% | Пикрейт: {pick:.1f}%\n\n"
    text += "💡 *Данные обновляются каждый час*"

    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

# ---------- Запуск бота с фоновой задачей ----------
async def on_startup():
    logger.info("Starting up...")
    # Загружаем список героев перед запуском
    await fetch_heroes_list()
    # Запускаем фоновое обновление винрейтов
    asyncio.create_task(update_winrates())
    logger.info("Startup complete")

async def on_shutdown():
    logger.info("Shutting down...")

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception("Fatal error")
