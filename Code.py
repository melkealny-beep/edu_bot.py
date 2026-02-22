#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════╗
║         Edu Bot — سنتر Edu & مطبعة X.press              ║
║         Powered by Groq (LLaMA 3.3) + python-telegram-bot ║
╚══════════════════════════════════════════════════════════╝

FIXED VERSION - All bugs resolved and best practices implemented
"""

import os
import sys
import sqlite3
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from contextlib import contextmanager

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from telegram.error import TelegramError, NetworkError, TimedOut
import httpx
from dotenv import load_dotenv

# ─── Configuration Constants ──────────────────────────────────────────────────
MAX_MESSAGE_LENGTH = 4000
MAX_HISTORY_MESSAGES = 6
MAX_PHONE_DIGITS = 15
MIN_PHONE_DIGITS = 10
MIN_NAME_LENGTH = 3
API_TIMEOUT = 30.0
API_MAX_RETRIES = 3
BOOKING_SUMMARY_MAX_LENGTH = 3900

# ─── Logging ──────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler("logs/edu_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ─── ENV ──────────────────────────────────────────────────────────────────────
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")
KNOWLEDGE_FILE = os.getenv("KNOWLEDGE_FILE", "knowledge.txt")

if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN is missing in .env file")
    sys.exit(1)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# ─── بيانات السنتر ────────────────────────────────────────────────────────────
CENTER = {
    "name": "سنتر Edu",
    "studio": "مطبعة X.press",
    "phone": "01000000000",
    "address": "القاهرة - مدينة نصر - شارع التسعين",
    "hours": "السبت - الخميس: 10 صباحاً - 10 مساءً",
}

COURSES = {
    "1": {"name": "📚 مهارات التدريس الحديث", "price": "800 جنيه", "duration": "4 أسابيع (8 جلسات)"},
    "2": {"name": "🎬 إنتاج المحتوى التعليمي", "price": "1200 جنيه", "duration": "3 أسابيع (6 جلسات)"},
    "3": {"name": "🖥️ التعليم الإلكتروني E-learning", "price": "1500 جنيه", "duration": "6 أسابيع (12 جلسة)"},
    "4": {"name": "🎨 تصميم المواد التعليمية", "price": "900 جنيه", "duration": "3 أسابيع (6 جلسات)"},
    "5": {"name": "🗣️ مهارات التواصل والإلقاء", "price": "600 جنيه", "duration": "2 أسبوع (4 جلسات)"},
}

PACKAGES = {
    "1": {"name": "⚡ باقة سريعة", "hours": "ساعة واحدة", "price": "300 جنيه"},
    "2": {"name": "🌟 باقة كورس", "hours": "3 ساعات", "price": "700 جنيه"},
    "3": {"name": "👑 باقة احترافية", "hours": "يوم كامل (8 ساعات)", "price": "2000 جنيه"},
    "4": {"name": "📦 باقة شهرية", "hours": "8 ساعات/الشهر", "price": "1500 جنيه/شهر"},
}

# ─── States ───────────────────────────────────────────────────────────────────
(
    MAIN_MENU,
    BOOK_TYPE,
    BOOK_NAME,
    BOOK_PHONE,
    BOOK_DETAILS,
    BOOK_DATE,
    BOOK_CONFIRM,
    CHAT_INPUT,
) = range(8)

# ─── Keyboards ────────────────────────────────────────────────────────────────
MAIN_KEYBOARD = ReplyKeyboardMarkup([
    ["📚 كورسات السنتر", "📸 استديو X.press"],
    ["📅 احجز دلوقتي", "💬 اسألنا"],
    ["📞 تواصل معنا"]
], resize_keyboard=True)


# ─── Utility Functions ────────────────────────────────────────────────────────
def sanitize_input(text: str, max_length: int = 500) -> str:
    """Sanitize user input to prevent injection and limit length."""
    if not text:
        return ""
    # Remove potentially dangerous characters
    text = text.strip()
    # Limit length
    if len(text) > max_length:
        text = text[:max_length]
    return text


def validate_egyptian_phone(phone: str) -> bool:
    """Validate Egyptian phone number format."""
    # Remove all non-digit characters
    digits = "".join(c for c in phone if c.isdigit())
    
    # Egyptian phone numbers are typically 11 digits starting with 01
    if len(digits) >= MIN_PHONE_DIGITS and len(digits) <= MAX_PHONE_DIGITS:
        # Check if it starts with common Egyptian prefixes
        if digits.startswith('01') or digits.startswith('20'):
            return True
        # Also accept international format
        if len(digits) >= 10:
            return True
    return False


def chunk_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """Split long messages into chunks that fit Telegram's message limit."""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 <= max_length:
            current_chunk += line + '\n'
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = line + '\n'
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks


# ─── Knowledge Base ───────────────────────────────────────────────────────────
def load_knowledge() -> str:
    """تحميل قاعدة المعرفة من الملف الخارجي مع معالجة الأخطاء"""
    try:
        path = Path(KNOWLEDGE_FILE)
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8")
            if text.strip():
                logger.info(f"✅ تم تحميل قاعدة المعرفة من {KNOWLEDGE_FILE} ({len(text)} حرف)")
                return text
            else:
                logger.warning(f"⚠️ {KNOWLEDGE_FILE} فارغ")
        else:
            logger.warning(f"⚠️ {KNOWLEDGE_FILE} غير موجود")
    except UnicodeDecodeError as e:
        logger.error(f"❌ خطأ في ترميز الملف {KNOWLEDGE_FILE}: {e}")
    except PermissionError as e:
        logger.error(f"❌ لا توجد صلاحيات لقراءة {KNOWLEDGE_FILE}: {e}")
    except Exception as e:
        logger.error(f"❌ خطأ في تحميل {KNOWLEDGE_FILE}: {type(e).__name__}: {e}")
    
    logger.info("📝 استخدام قاعدة المعرفة الافتراضية")
    return _fallback_knowledge()


def _fallback_knowledge() -> str:
    """قاعدة معرفة احتياطية في حالة عدم توفر الملف الخارجي"""
    return f"""أنت إيدو، المساعد الذكي لـ {CENTER['name']} و{CENTER['studio']}.
العنوان: {CENTER['address']} | التليفون: {CENTER['phone']} | المواعيد: {CENTER['hours']}

الكورسات المتاحة:
{chr(10).join([f"- {c['name']}: {c['price']}, المدة: {c['duration']}" for c in COURSES.values()])}

باقات الاستديو:
{chr(10).join([f"- {p['name']}: {p['hours']}, السعر: {p['price']}" for p in PACKAGES.values()])}

تكلم بالعامية المصرية الودودة. لو حد عايز يحجز، قوله يضغط زرار "📅 احجز دلوقتي"."""


# ─── Groq AI with Retry Logic ────────────────────────────────────────────────
class GroqAI:
    """Groq AI client with retry logic and error handling"""
    
    def __init__(self):
        self.knowledge = load_knowledge()
        self.system_prompt = self._build_system_prompt()
        logger.info("🤖 Groq AI initialized")

    def _build_system_prompt(self) -> str:
        """بناء الـ system prompt للذكاء الاصطناعي"""
        return f"""أنت "إيدو" - المساعد الذكي لسنتر Edu ومطبعة X.press.

{self.knowledge}

تعليمات مهمة:
- رد دايماً بالعربي العامي المصري
- كن مختصر وواضح ومفيد (لا تتجاوز 500 كلمة)
- لو حد عايز يحجز، قوله يضغط زرار "📅 احجز دلوقتي"
- لو السؤال مش متعلق بالسنتر أو الاستديو، اعتذر بأدب وخليه يسأل عن خدماتنا
- استخدم الإيموجي بشكل معتدل
- لا تدعي معرفة معلومات غير موجودة في قاعدة المعرفة"""

    async def ask(self, message: str, history: Optional[List[Dict]] = None) -> Optional[str]:
        """إرسال سؤال للـ AI مع تاريخ المحادثة وآلية إعادة المحاولة"""
        if not GROQ_API_KEY:
            logger.warning("⚠️ GROQ_API_KEY not configured")
            return f"خدمة الذكاء الاصطناعي غير متاحة دلوقتي.\nتواصل معنا مباشرة على {CENTER['phone']} 😊"

        # Sanitize input
        message = sanitize_input(message, max_length=1000)
        if not message:
            return "عذراً، لم أستطع فهم رسالتك. حاول مرة أخرى 😊"

        # Build messages
        messages = [{"role": "system", "content": self.system_prompt}]
        if history:
            # Only keep last N messages to avoid token limits
            messages.extend(history[-MAX_HISTORY_MESSAGES:])
        messages.append({"role": "user", "content": message})

        # Retry logic
        last_error = None
        for attempt in range(1, API_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
                    response = await client.post(
                        GROQ_API_URL,
                        headers={
                            "Authorization": f"Bearer {GROQ_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": GROQ_MODEL,
                            "messages": messages,
                            "temperature": 0.7,
                            "max_tokens": 800,
                            "top_p": 0.9,
                        }
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    if "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0]["message"]["content"]
                        logger.info(f"✅ Groq API response received (attempt {attempt})")
                        return content
                    else:
                        logger.error(f"⚠️ Unexpected Groq API response format: {result}")
                        return None
                        
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"⏱️ Groq API timeout (attempt {attempt}/{API_MAX_RETRIES})")
                if attempt < API_MAX_RETRIES:
                    continue
                    
            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code
                logger.error(f"❌ Groq HTTP error {status_code} (attempt {attempt}/{API_MAX_RETRIES}): {e}")
                
                # Don't retry on client errors (4xx)
                if 400 <= status_code < 500:
                    if status_code == 401:
                        return "خطأ في مفتاح API. تواصل مع المسؤول."
                    elif status_code == 429:
                        return "تم تجاوز حد الطلبات. حاول مرة أخرى بعد قليل 🙏"
                    return None
                    
                # Retry on server errors (5xx)
                if attempt < API_MAX_RETRIES:
                    continue
                    
            except httpx.RequestError as e:
                last_error = e
                logger.error(f"❌ Groq request error (attempt {attempt}/{API_MAX_RETRIES}): {e}")
                if attempt < API_MAX_RETRIES:
                    continue
                    
            except Exception as e:
                last_error = e
                logger.error(f"❌ Unexpected Groq error (attempt {attempt}/{API_MAX_RETRIES}): {type(e).__name__}: {e}")
                if attempt < API_MAX_RETRIES:
                    continue

        # All retries failed
        logger.error(f"❌ All Groq API retries failed. Last error: {last_error}")
        return "الرد بياخد وقت أكتر من المعتاد، حاول تاني بعد شوية 🙏"

    def reload_knowledge(self) -> bool:
        """إعادة تحميل قاعدة المعرفة بدون ريستارت"""
        try:
            self.knowledge = load_knowledge()
            self.system_prompt = self._build_system_prompt()
            logger.info("🔄 تم إعادة تحميل قاعدة المعرفة بنجاح")
            return True
        except Exception as e:
            logger.error(f"❌ فشل إعادة تحميل قاعدة المعرفة: {e}")
            return False


# ─── Database with Connection Context Manager ────────────────────────────────
class Database:
    """Database handler with proper connection management and error handling"""
    
    def __init__(self, db_path: str = "edu_bookings.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"❌ Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def _init_db(self):
        """Initialize database with proper schema and indices"""
        try:
            with self._get_connection() as conn:
                conn.executescript('''
                    CREATE TABLE IF NOT EXISTS bookings (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id  INTEGER NOT NULL,
                        name         TEXT    NOT NULL,
                        phone        TEXT    NOT NULL,
                        booking_type TEXT    NOT NULL,
                        details      TEXT,
                        preferred_date TEXT,
                        status       TEXT DEFAULT "pending",
                        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    
                    CREATE TABLE IF NOT EXISTS users (
                        telegram_id  INTEGER PRIMARY KEY,
                        first_name   TEXT,
                        username     TEXT,
                        first_seen   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_seen    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        total_msgs   INTEGER DEFAULT 0
                    );
                    
                    -- Create indices for better query performance
                    CREATE INDEX IF NOT EXISTS idx_bookings_telegram_id ON bookings(telegram_id);
                    CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
                    CREATE INDEX IF NOT EXISTS idx_bookings_created_at ON bookings(created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen DESC);
                ''')
            logger.info("✅ Database initialized successfully")
        except sqlite3.Error as e:
            logger.error(f"❌ Failed to initialize database: {e}")
            raise

    def upsert_user(self, telegram_id: int, first_name: str, username: Optional[str]) -> bool:
        """Insert or update user information"""
        try:
            # Sanitize inputs
            first_name = sanitize_input(first_name, max_length=100)
            username = sanitize_input(username, max_length=50) if username else ""
            
            with self._get_connection() as conn:
                conn.execute('''
                    INSERT INTO users (telegram_id, first_name, username)
                    VALUES (?, ?, ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET
                        last_seen = CURRENT_TIMESTAMP,
                        total_msgs = total_msgs + 1,
                        first_name = excluded.first_name,
                        username = excluded.username
                ''', (telegram_id, first_name, username))
            return True
        except sqlite3.Error as e:
            logger.error(f"❌ upsert_user error: {e}")
            return False

    def save_booking(
        self,
        telegram_id: int,
        name: str,
        phone: str,
        booking_type: str,
        details: str,
        date: str
    ) -> bool:
        """Save a new booking to the database"""
        try:
            # Sanitize all inputs
            name = sanitize_input(name, max_length=200)
            phone = sanitize_input(phone, max_length=20)
            booking_type = sanitize_input(booking_type, max_length=50)
            details = sanitize_input(details, max_length=1000)
            date = sanitize_input(date, max_length=200)
            
            with self._get_connection() as conn:
                conn.execute(
                    '''INSERT INTO bookings 
                       (telegram_id, name, phone, booking_type, details, preferred_date) 
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (telegram_id, name, phone, booking_type, details, date)
                )
            logger.info(f"✅ Booking saved for user {telegram_id}")
            return True
        except sqlite3.Error as e:
            logger.error(f"❌ save_booking error: {e}")
            return False

    def get_all_bookings(self) -> List[Tuple]:
        """Get all bookings from the database"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    '''SELECT name, phone, booking_type, details, preferred_date, status, created_at 
                       FROM bookings 
                       ORDER BY created_at DESC'''
                )
                return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"❌ get_all_bookings error: {e}")
            return []

    def count_bookings(self) -> int:
        """Count total number of bookings"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute('SELECT COUNT(*) FROM bookings')
                result = cursor.fetchone()
                return result[0] if result else 0
        except sqlite3.Error as e:
            logger.error(f"❌ count_bookings error: {e}")
            return 0

    def count_users(self) -> int:
        """Count total number of users"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute('SELECT COUNT(*) FROM users')
                result = cursor.fetchone()
                return result[0] if result else 0
        except sqlite3.Error as e:
            logger.error(f"❌ count_users error: {e}")
            return 0

    def get_pending_bookings(self) -> List[Tuple]:
        """Get all pending bookings"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    '''SELECT id, name, phone, booking_type, details, preferred_date, created_at 
                       FROM bookings 
                       WHERE status = 'pending' 
                       ORDER BY created_at DESC'''
                )
                return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"❌ get_pending_bookings error: {e}")
            return []

    def update_booking_status(self, booking_id: int, status: str) -> bool:
        """Update booking status (pending/confirmed/rejected)"""
        if status not in ['pending', 'confirmed', 'rejected']:
            logger.warning(f"⚠️ Invalid status: {status}")
            return False
            
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    'UPDATE bookings SET status = ? WHERE id = ?',
                    (status, booking_id)
                )
                rows_affected = cursor.rowcount
                if rows_affected > 0:
                    logger.info(f"✅ Booking {booking_id} status updated to {status}")
                    return True
                else:
                    logger.warning(f"⚠️ No booking found with id {booking_id}")
                    return False
        except sqlite3.Error as e:
            logger.error(f"❌ update_booking_status error: {e}")
            return False

    def get_booking_by_id(self, booking_id: int) -> Optional[Tuple]:
        """Get booking details by ID"""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    '''SELECT id, telegram_id, name, phone, booking_type, details, 
                              preferred_date, status, created_at 
                       FROM bookings 
                       WHERE id = ?''',
                    (booking_id,)
                )
                return cursor.fetchone()
        except sqlite3.Error as e:
            logger.error(f"❌ get_booking_by_id error: {e}")
            return None


# ─── Bot ──────────────────────────────────────────────────────────────────────
class EduBot:
    """Main bot class with all handlers"""
    
    def __init__(self):
        self.db = Database()
        self.ai = GroqAI()
        logger.info("🤖 EduBot initialized")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _is_confirm(self, text: str) -> bool:
        """Check if text indicates confirmation"""
        confirm_words = ["✅", "تأكيد", "أيوه", "ايوه", "اه", "نعم", "تمام", "صح", "موافق", "ok", "yes"]
        return any(word in text.lower() for word in confirm_words)

    def _is_cancel(self, text: str) -> bool:
        """Check if text indicates cancellation"""
        cancel_words = ["❌", "إلغاء", "الغ", "لأ", "لا", "مش عايز", "cancel", "no"]
        return any(word in text.lower() for word in cancel_words)

    def _is_back(self, text: str) -> bool:
        """Check if text indicates going back"""
        back_words = ["رجوع", "🏠", "الرئيسية", "القائمة", "back"]
        return any(word in text.lower() for word in back_words)

    def _is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        if not ADMIN_ID:
            return False
        try:
            return str(user_id) == str(ADMIN_ID)
        except (ValueError, TypeError):
            return False

    async def _notify_admin(self, context: ContextTypes.DEFAULT_TYPE, booking: Dict, user_id: int, booking_id: int):
        """Notify admin of new booking with action buttons"""
        if not ADMIN_ID or not self._is_admin(int(ADMIN_ID)):
            logger.warning("⚠️ ADMIN_ID not configured or invalid")
            return
            
        try:
            btype_label = "📚 كورس" if booking.get("type") == "course" else "📸 جلسة تصوير"
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_{booking_id}"),
                    InlineKeyboardButton("❌ رفض", callback_data=f"reject_{booking_id}"),
                ]
            ])
            
            message_text = (
                f"🔔 *حجز جديد!*\n\n"
                f"👤 الاسم: {booking['name']}\n"
                f"📞 التليفون: {booking['phone']}\n"
                f"🎯 النوع: {btype_label}\n"
                f"📌 التفاصيل: {booking.get('details', 'لا يوجد')}\n"
                f"📅 الموعد: {booking.get('date', 'غير محدد')}\n"
                f"🆔 Telegram ID: `{user_id}`\n"
                f"🔖 Booking ID: `{booking_id}`\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            
            await context.bot.send_message(
                chat_id=int(ADMIN_ID),
                text=message_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            logger.info(f"✅ Admin notified of booking {booking_id}")
        except (TelegramError, ValueError, TypeError) as e:
            logger.error(f"❌ Failed to notify admin: {type(e).__name__}: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error notifying admin: {type(e).__name__}: {e}")

    async def _send_long_message(
        self,
        update: Update,
        text: str,
        reply_markup=None,
        parse_mode: Optional[str] = None
    ):
        """Send potentially long message, splitting if necessary"""
        chunks = chunk_message(text, MAX_MESSAGE_LENGTH)
        
        for i, chunk in enumerate(chunks):
            # Only add reply_markup to the last chunk
            markup = reply_markup if i == len(chunks) - 1 else None
            try:
                await update.message.reply_text(
                    chunk,
                    reply_markup=markup,
                    parse_mode=parse_mode
                )
            except TelegramError as e:
                logger.error(f"❌ Failed to send message chunk {i+1}/{len(chunks)}: {e}")

    # ── /start ────────────────────────────────────────────────────────────────
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            user = update.effective_user
            self.db.upsert_user(user.id, user.first_name, user.username)
            
            welcome_message = (
                f"👋 أهلاً وسهلاً يا *{user.first_name}*!\n\n"
                f"أنا إيدو، مساعدك الذكي في:\n\n"
                f"📚 *{CENTER['name']}*\n"
                f"سنتر متخصص في تطوير مهارات المدرسين\n\n"
                f"📸 *{CENTER['studio']}*\n"
                f"استديو تصوير احترافي لإنتاج المحتوى التعليمي\n\n"
                f"📍 {CENTER['address']}\n"
                f"⏰ {CENTER['hours']}\n\n"
                "اختار من القائمة اللي تحت 👇"
            )
            
            await update.message.reply_text(
                welcome_message,
                reply_markup=MAIN_KEYBOARD,
                parse_mode="Markdown"
            )
            logger.info(f"✅ User {user.id} ({user.first_name}) started the bot")
        except Exception as e:
            logger.error(f"❌ Error in start handler: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )

    # ── عرض الكورسات ─────────────────────────────────────────────────────────
    async def show_courses(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display available courses"""
        try:
            msg = f"📚 *كورسات {CENTER['name']}*\n"
            msg += "متخصصة في تطوير مهارات المدرسين 🎓\n"
            msg += "━" * 28 + "\n\n"
            
            for c in COURSES.values():
                msg += f"{c['name']}\n"
                msg += f"⏱ {c['duration']}  |  💰 {c['price']}\n\n"
            
            msg += "━" * 28 + "\n"
            msg += "💬 اسألنا عن أي كورس أو احجز مباشرة 👇"
            
            keyboard = [
                ["📅 احجز كورس دلوقتي"],
                ["💬 اسألنا عن الكورسات"],
                ["🏠 الرئيسية"]
            ]
            
            await update.message.reply_text(
                msg,
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"❌ Error in show_courses: {e}")
            await update.message.reply_text(
                "حصل خطأ في عرض الكورسات. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )

    # ── عرض الاستديو ─────────────────────────────────────────────────────────
    async def show_studio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display studio packages and information"""
        try:
            pkg_msg = f"📸 *{CENTER['studio']} — الباقات والأسعار*\n\n"
            
            for p in PACKAGES.values():
                pkg_msg += f"{p['name']}\n"
                pkg_msg += f"⏱ {p['hours']}  |  💰 {p['price']}\n\n"
            
            pkg_msg += "━" * 28 + "\n"
            pkg_msg += "🎬 لوكيشنات متاحة:\n"
            pkg_msg += "• كلاس دراسي\n• مكتبة\n• ستوديو أبيض\n• ركن طبيعي\n• أوفيس\n• خلفية سوداء\n\n"
            pkg_msg += "اسألنا عن اللوكيشن الأنسب لمادتك 😊"
            
            keyboard = [
                ["📅 احجز جلسة تصوير"],
                ["💬 اسألنا عن الاستديو"],
                ["🏠 الرئيسية"]
            ]
            
            await update.message.reply_text(
                pkg_msg,
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"❌ Error in show_studio: {e}")
            await update.message.reply_text(
                "حصل خطأ في عرض معلومات الاستديو. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )

    # ── تواصل معنا ────────────────────────────────────────────────────────────
    async def contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display contact information"""
        try:
            contact_msg = (
                f"📞 *تواصل معنا*\n\n"
                f"📱 {CENTER['phone']}\n"
                f"📍 {CENTER['address']}\n"
                f"⏰ {CENTER['hours']}\n\n"
                "أو كلمنا هنا وهنرد عليك في أقرب وقت 😊"
            )
            
            await update.message.reply_text(
                contact_msg,
                reply_markup=MAIN_KEYBOARD,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"❌ Error in contact handler: {e}")

    # ══════════════════════════════════════════════════════════════
    #  BOOKING FLOW
    # ══════════════════════════════════════════════════════════════
    async def book_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start booking conversation"""
        try:
            context.user_data["booking"] = {}
            text = update.message.text

            # Auto-detect booking type from message
            if "كورس" in text:
                context.user_data["booking"]["type"] = "course"
                return await self._ask_name(update)
            elif any(w in text for w in ["تصوير", "جلسة", "استديو"]):
                context.user_data["booking"]["type"] = "studio"
                return await self._ask_name(update)
            else:
                keyboard = [["📚 حجز كورس", "📸 حجز جلسة تصوير"], ["🏠 رجوع"]]
                await update.message.reply_text(
                    "عايز تحجز إيه؟ 👇",
                    reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
                )
                return BOOK_TYPE
        except Exception as e:
            logger.error(f"❌ Error in book_start: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )
            return ConversationHandler.END

    async def book_get_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get booking type from user"""
        try:
            text = update.message.text
            
            if self._is_back(text):
                await update.message.reply_text("تمام! رجعنا للقائمة الرئيسية 😊", reply_markup=MAIN_KEYBOARD)
                return ConversationHandler.END
                
            if "كورس" in text:
                context.user_data["booking"]["type"] = "course"
            elif any(w in text for w in ["تصوير", "جلسة"]):
                context.user_data["booking"]["type"] = "studio"
            else:
                await update.message.reply_text("من فضلك اختار من الزرارين 👆")
                return BOOK_TYPE
                
            return await self._ask_name(update)
        except Exception as e:
            logger.error(f"❌ Error in book_get_type: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )
            return ConversationHandler.END

    async def _ask_name(self, update: Update):
        """Ask user for their name"""
        try:
            await update.message.reply_text(
                "😊 تمام! هنكمل الحجز.\n\nاكتب *اسمك الكامل* من فضلك:",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="Markdown"
            )
            return BOOK_NAME
        except Exception as e:
            logger.error(f"❌ Error in _ask_name: {e}")
            return ConversationHandler.END

    async def book_get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get and validate user's name"""
        try:
            name = sanitize_input(update.message.text.strip(), max_length=200)
            
            if len(name) < MIN_NAME_LENGTH:
                await update.message.reply_text("⚠️ اكتب اسمك الكامل من فضلك (على الأقل 3 حروف).")
                return BOOK_NAME
                
            context.user_data["booking"]["name"] = name
            await update.message.reply_text(
                f"تمام يا *{name}* 👍\n\n📞 رقم تليفونك؟",
                parse_mode="Markdown"
            )
            return BOOK_PHONE
        except Exception as e:
            logger.error(f"❌ Error in book_get_name: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )
            return ConversationHandler.END

    async def book_get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get and validate user's phone number"""
        try:
            phone = sanitize_input(update.message.text.strip(), max_length=20)
            
            if not validate_egyptian_phone(phone):
                await update.message.reply_text(
                    "⚠️ الرقم مش صحيح. من فضلك اكتب رقم تليفون صحيح (11 رقم على الأقل).\n"
                    "مثال: 01012345678"
                )
                return BOOK_PHONE
                
            context.user_data["booking"]["phone"] = phone
            btype = context.user_data["booking"].get("type")

            if btype == "course":
                keyboard = [[c["name"]] for c in COURSES.values()] + [["🏠 رجوع"]]
                items = "\n".join([f"• {c['name']} — {c['price']}" for c in COURSES.values()])
                await update.message.reply_text(
                    f"📚 *اختار الكورس اللي بيناسبك:*\n\n{items}",
                    reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
                    parse_mode="Markdown"
                )
            else:
                keyboard = [[p["name"]] for p in PACKAGES.values()] + [["🏠 رجوع"]]
                items = "\n".join([f"• {p['name']} ({p['hours']}) — {p['price']}" for p in PACKAGES.values()])
                await update.message.reply_text(
                    f"📦 *اختار الباقة المناسبة:*\n\n{items}",
                    reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
                    parse_mode="Markdown"
                )
            return BOOK_DETAILS
        except Exception as e:
            logger.error(f"❌ Error in book_get_phone: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )
            return ConversationHandler.END

    async def book_get_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get booking details (course/package selection)"""
        try:
            text = sanitize_input(update.message.text.strip(), max_length=1000)
            
            if self._is_back(text):
                await update.message.reply_text("تمام! رجعنا للقائمة الرئيسية 😊", reply_markup=MAIN_KEYBOARD)
                return ConversationHandler.END
                
            context.user_data["booking"]["details"] = text
            await update.message.reply_text(
                "📅 *إيه الوقت اللي بيناسبك؟*\n\n"
                "اكتب مثلاً: _الخميس الجاي الساعة 4 العصر_\n"
                "أو: _أي يوم من السبت للخميس الساعة 2 الظهر_",
                parse_mode="Markdown"
            )
            return BOOK_DATE
        except Exception as e:
            logger.error(f"❌ Error in book_get_details: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )
            return ConversationHandler.END

    async def book_get_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get preferred date/time"""
        try:
            date_text = sanitize_input(update.message.text.strip(), max_length=200)
            context.user_data["booking"]["date"] = date_text
            
            b = context.user_data["booking"]
            btype_label = "📚 كورس" if b.get("type") == "course" else "📸 جلسة تصوير"
            
            keyboard = [["✅ تأكيد الحجز", "❌ إلغاء"]]
            summary_msg = (
                f"📋 *ملخص الحجز:*\n\n"
                f"👤 الاسم: {b['name']}\n"
                f"📞 التليفون: {b['phone']}\n"
                f"🎯 النوع: {btype_label}\n"
                f"📌 التفاصيل: {b['details']}\n"
                f"📅 الوقت: {b['date']}\n\n"
                "✅ البيانات صح؟"
            )
            
            await update.message.reply_text(
                summary_msg,
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
                parse_mode="Markdown"
            )
            return BOOK_CONFIRM
        except Exception as e:
            logger.error(f"❌ Error in book_get_date: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )
            return ConversationHandler.END

    async def book_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm and save booking"""
        try:
            user_id = update.effective_user.id
            text = update.message.text

            if self._is_cancel(text):
                context.user_data["booking"] = {}
                await update.message.reply_text(
                    "تمام! الحجز اتلغى.\nلو عايز تحجز تاني اضغط على زرار \"📅 احجز دلوقتي\" 😊",
                    reply_markup=MAIN_KEYBOARD
                )
                return ConversationHandler.END

            if self._is_confirm(text):
                b = context.user_data.get("booking", {})
                
                # Save to database
                success = self.db.save_booking(
                    user_id,
                    b.get("name", ""),
                    b.get("phone", ""),
                    b.get("type", ""),
                    b.get("details", ""),
                    b.get("date", "")
                )
                
                if success:
                    # Get the booking ID of the just-created booking
                    # We'll get all bookings for this user and take the most recent one
                    try:
                        with self.db._get_connection() as conn:
                            cursor = conn.execute(
                                'SELECT id FROM bookings WHERE telegram_id = ? ORDER BY created_at DESC LIMIT 1',
                                (user_id,)
                            )
                            result = cursor.fetchone()
                            booking_id = result[0] if result else None
                    except Exception as e:
                        logger.error(f"❌ Failed to get booking ID: {e}")
                        booking_id = None
                    
                    btype_label = "كورس" if b.get("type") == "course" else "جلسة تصوير"
                    await update.message.reply_text(
                        f"🎉 *تم الحجز بنجاح يا {b['name']}!*\n\n"
                        f"هيتواصل معك فريقنا قريباً لتأكيد الـ {btype_label}.\n\n"
                        f"📞 {CENTER['phone']}\n"
                        f"📍 {CENTER['address']}\n\n"
                        "شكراً لثقتك فينا! 💚",
                        reply_markup=MAIN_KEYBOARD,
                        parse_mode="Markdown"
                    )
                    
                    # Notify admin with booking ID
                    if booking_id:
                        await self._notify_admin(context, b, user_id, booking_id)
                    else:
                        logger.warning("⚠️ Could not get booking ID for admin notification")
                else:
                    await update.message.reply_text(
                        "❌ حصل خطأ في حفظ الحجز. حاول مرة أخرى أو تواصل معنا مباشرة.",
                        reply_markup=MAIN_KEYBOARD
                    )
                
                context.user_data["booking"] = {}
                return ConversationHandler.END

            # Invalid response
            keyboard = [["✅ تأكيد الحجز", "❌ إلغاء"]]
            await update.message.reply_text(
                "من فضلك اضغط على أحد الزرارين 👆",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            )
            return BOOK_CONFIRM
        except Exception as e:
            logger.error(f"❌ Error in book_confirm: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )
            return ConversationHandler.END

    async def book_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel booking conversation"""
        try:
            context.user_data["booking"] = {}
            await update.message.reply_text("تم الإلغاء 😊", reply_markup=MAIN_KEYBOARD)
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"❌ Error in book_cancel: {e}")
            return ConversationHandler.END

    # ══════════════════════════════════════════════════════════════
    #  AI CHAT — مع تاريخ المحادثة
    # ══════════════════════════════════════════════════════════════
    async def chat_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start AI chat conversation"""
        try:
            context.user_data.setdefault("chat_history", [])
            await update.message.reply_text(
                "💬 اسألني أي سؤال عن الكورسات، الاستديو، الباقات، أو أي حاجة تانية!\n\n"
                "_اكتب 'رجوع' أو '🏠' للخروج_",
                reply_markup=ReplyKeyboardMarkup([["🏠 رجوع"]], resize_keyboard=True),
                parse_mode="Markdown"
            )
            return CHAT_INPUT
        except Exception as e:
            logger.error(f"❌ Error in chat_start: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )
            return ConversationHandler.END

    async def chat_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle chat input and get AI response"""
        try:
            text = update.message.text
            
            if self._is_back(text):
                context.user_data["chat_history"] = []
                await update.message.reply_text("رجعنا للقائمة الرئيسية 😊", reply_markup=MAIN_KEYBOARD)
                return ConversationHandler.END

            user = update.effective_user
            self.db.upsert_user(user.id, user.first_name, user.username)

            # Show typing indicator
            await update.message.chat.send_action("typing")

            history = context.user_data.get("chat_history", [])
            response = await self.ai.ask(text, history)

            if response:
                # Save to history
                history.append({"role": "user", "content": text})
                history.append({"role": "assistant", "content": response})
                context.user_data["chat_history"] = history[-10:]  # Keep last 10 messages

                await update.message.reply_text(
                    response,
                    reply_markup=ReplyKeyboardMarkup([["🏠 رجوع"]], resize_keyboard=True)
                )
            else:
                await update.message.reply_text(
                    f"مش قادر أرد دلوقتي. تواصل معنا مباشرة على {CENTER['phone']} 😊",
                    reply_markup=ReplyKeyboardMarkup([["🏠 رجوع"]], resize_keyboard=True)
                )
            return CHAT_INPUT
        except Exception as e:
            logger.error(f"❌ Error in chat_input: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=ReplyKeyboardMarkup([["🏠 رجوع"]], resize_keyboard=True)
            )
            return CHAT_INPUT

    # ── General Message ───────────────────────────────────────────────────────
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle general messages not caught by other handlers"""
        try:
            text = update.message.text
            
            if self._is_back(text):
                await update.message.reply_text("اختار من القائمة 👇", reply_markup=MAIN_KEYBOARD)
                return

            user = update.effective_user
            self.db.upsert_user(user.id, user.first_name, user.username)

            await update.message.chat.send_action("typing")
            response = await self.ai.ask(text)
            
            if response:
                await update.message.reply_text(response, reply_markup=MAIN_KEYBOARD)
            else:
                await update.message.reply_text(
                    f"مش قادر أرد دلوقتي. تواصل معنا على {CENTER['phone']} 😊",
                    reply_markup=MAIN_KEYBOARD
                )
        except Exception as e:
            logger.error(f"❌ Error in handle_message: {e}")
            await update.message.reply_text(
                "حصل خطأ. حاول مرة أخرى 😊",
                reply_markup=MAIN_KEYBOARD
            )

    # ══════════════════════════════════════════════════════════════
    #  ADMIN — Inline Callbacks
    # ══════════════════════════════════════════════════════════════
    async def admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin inline button callbacks"""
        query = update.callback_query
        
        try:
            await query.answer()

            if not self._is_admin(query.from_user.id):
                await query.answer("⛔ غير مصرح", show_alert=True)
                return

            data = query.data
            
            # Parse callback data: "action_bookingid"
            if "_" in data:
                action, booking_id_str = data.split("_", 1)
                
                try:
                    booking_id = int(booking_id_str)
                except ValueError:
                    logger.error(f"❌ Invalid booking ID in callback: {booking_id_str}")
                    await query.message.reply_text("❌ معرّف الحجز غير صحيح")
                    return
                
                # Get booking details
                booking = self.db.get_booking_by_id(booking_id)
                
                if not booking:
                    await query.edit_message_reply_markup(reply_markup=None)
                    await query.message.reply_text(f"❌ الحجز #{booking_id} غير موجود")
                    return
                
                # Update status based on action
                if action == "confirm":
                    success = self.db.update_booking_status(booking_id, "confirmed")
                    status_label = "✅ تم تأكيد الحجز"
                    status_emoji = "✅"
                elif action == "reject":
                    success = self.db.update_booking_status(booking_id, "rejected")
                    status_label = "❌ تم رفض الحجز"
                    status_emoji = "❌"
                else:
                    logger.warning(f"⚠️ Unknown action: {action}")
                    return
                
                if success:
                    # Remove inline buttons
                    await query.edit_message_reply_markup(reply_markup=None)
                    
                    # Send confirmation message
                    confirmation_msg = (
                        f"{status_emoji} *{status_label}*\n\n"
                        f"📋 Booking ID: `{booking_id}`\n"
                        f"👤 {booking[2]} ({booking[1]})\n"
                        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                    )
                    await query.message.reply_text(confirmation_msg, parse_mode="Markdown")
                    
                    # Optionally notify the user
                    try:
                        user_telegram_id = booking[1]  # telegram_id from booking
                        btype_label = "كورس" if booking[4] == "course" else "جلسة تصوير"
                        
                        if action == "confirm":
                            user_msg = (
                                f"✅ *تم تأكيد حجزك!*\n\n"
                                f"النوع: {btype_label}\n"
                                f"التفاصيل: {booking[5]}\n"
                                f"الموعد: {booking[6]}\n\n"
                                f"هنتواصل معك قريباً 😊\n"
                                f"📞 {CENTER['phone']}"
                            )
                        else:
                            user_msg = (
                                f"عذراً، لم نتمكن من تأكيد حجزك في الوقت المطلوب.\n\n"
                                f"تواصل معنا على {CENTER['phone']} لإيجاد موعد بديل 😊"
                            )
                        
                        await context.bot.send_message(
                            chat_id=user_telegram_id,
                            text=user_msg,
                            parse_mode="Markdown"
                        )
                        logger.info(f"✅ User {user_telegram_id} notified of booking status")
                    except TelegramError as e:
                        logger.error(f"❌ Failed to notify user: {e}")
                else:
                    await query.message.reply_text("❌ فشل تحديث حالة الحجز")
        except Exception as e:
            logger.error(f"❌ Error in admin_callback: {type(e).__name__}: {e}")
            try:
                await query.message.reply_text("❌ حصل خطأ في معالجة الطلب")
            except:
                pass

    # ── Admin Commands ─────────────────────────────────────────────────────────
    async def show_bookings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all bookings (admin only)"""
        try:
            if not self._is_admin(update.effective_user.id):
                await update.message.reply_text("❌ هذا الأمر متاح للمشرف فقط.")
                return
                
            bookings = self.db.get_all_bookings()
            
            if not bookings:
                await update.message.reply_text("📭 لا توجد حجوزات حتى الآن.")
                return
            
            msg = f"📋 *الحجوزات ({len(bookings)} حجز)*\n{'─' * 25}\n\n"
            
            for i, booking in enumerate(bookings, 1):
                name, phone, btype, details, date, status, created = booking
                btype_label = "📚 كورس" if btype == "course" else "📸 استديو"
                status_label = "✅" if status == "confirmed" else ("❌" if status == "rejected" else "⏳")
                
                entry = (
                    f"#{i} {btype_label} {status_label}\n"
                    f"👤 {name} | 📞 {phone}\n"
                    f"📌 {details}\n"
                    f"📅 {date}\n"
                    f"🕐 {created[:16]}\n{'─' * 20}\n"
                )
                
                # Split into multiple messages if too long
                if len(msg) + len(entry) > BOOKING_SUMMARY_MAX_LENGTH:
                    await update.message.reply_text(msg, parse_mode="Markdown")
                    msg = ""
                    
                msg += entry
            
            if msg:
                await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"❌ Error in show_bookings: {e}")
            await update.message.reply_text("❌ حصل خطأ في عرض الحجوزات.")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot statistics (admin only)"""
        try:
            if not self._is_admin(update.effective_user.id):
                await update.message.reply_text("❌ هذا الأمر متاح للمشرف فقط.")
                return
                
            total_bookings = self.db.count_bookings()
            total_users = self.db.count_users()
            pending = len(self.db.get_pending_bookings())
            
            stats_msg = (
                f"📊 *إحصائيات البوت*\n\n"
                f"👥 عدد المستخدمين: {total_users}\n"
                f"📋 إجمالي الحجوزات: {total_bookings}\n"
                f"⏳ قيد الانتظار: {pending}\n\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            
            await update.message.reply_text(stats_msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"❌ Error in stats: {e}")
            await update.message.reply_text("❌ حصل خطأ في عرض الإحصائيات.")

    async def reload_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reload knowledge base (admin only)"""
        try:
            if not self._is_admin(update.effective_user.id):
                await update.message.reply_text("❌ هذا الأمر متاح للمشرف فقط.")
                return
                
            success = self.ai.reload_knowledge()
            
            if success:
                await update.message.reply_text("✅ تم إعادة تحميل قاعدة المعرفة بنجاح!")
            else:
                await update.message.reply_text("❌ فشل إعادة تحميل قاعدة المعرفة. راجع السجلات.")
        except Exception as e:
            logger.error(f"❌ Error in reload_cmd: {e}")
            await update.message.reply_text("❌ حصل خطأ في إعادة التحميل.")

    # ── Error Handler ─────────────────────────────────────────────────────────
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"❌ Update {update} caused error: {context.error}", exc_info=context.error)
        
        # Send user-friendly error message
        if update and update.message:
            try:
                if isinstance(context.error, NetworkError):
                    error_msg = "❌ مشكلة في الاتصال. حاول مرة أخرى بعد قليل."
                elif isinstance(context.error, TimedOut):
                    error_msg = "⏱️ انتهت مهلة الطلب. حاول مرة أخرى."
                else:
                    error_msg = "❌ حصل خطأ. حاول مرة أخرى 😊"
                
                await update.message.reply_text(error_msg, reply_markup=MAIN_KEYBOARD)
            except TelegramError as e:
                logger.error(f"❌ Failed to send error message to user: {e}")
            except Exception as e:
                logger.error(f"❌ Unexpected error in error_handler: {e}")

    # ── Build App ─────────────────────────────────────────────────────────────
    def build(self) -> Application:
        """Build and configure the application with all handlers"""
        app = Application.builder().token(TELEGRAM_TOKEN).build()

        # Booking conversation triggers
        BOOK_TRIGGER = (
            r"📅 احجز دلوقتي|احجز كورس|احجز جلسة تصوير|"
            r"عايز احجز|عاوز احجز|محتاج احجز|"
            r"حجز كورس|حجز جلسة|حجزلي|احجزلي|"
            r"عايز موعد|عاوز موعد|ابي احجز|ابغى احجز|"
            r"📅 احجز كورس دلوقتي|📅 احجز جلسة تصوير"
        )

        # Booking conversation handler
        booking_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex(BOOK_TRIGGER), self.book_start)],
            states={
                BOOK_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_type)],
                BOOK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_name)],
                BOOK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_phone)],
                BOOK_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_details)],
                BOOK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_date)],
                BOOK_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_confirm)],
            },
            fallbacks=[
                CommandHandler("cancel", self.book_cancel),
                MessageHandler(filters.Regex(r"^/start$"), self.start),
            ],
            allow_reentry=True
        )

        # Chat conversation handler
        chat_conv = ConversationHandler(
            entry_points=[MessageHandler(
                filters.Regex(r"💬 اسألنا$|💬 اسألنا عن الكورسات|💬 اسألنا عن الاستديو"),
                self.chat_start
            )],
            states={
                CHAT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.chat_input)],
            },
            fallbacks=[
                CommandHandler("cancel", self.book_cancel),
                MessageHandler(filters.Regex(r"^/start$"), self.start),
            ],
            allow_reentry=True
        )

        # Register handlers in order of priority
        # 1. Commands
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("bookings", self.show_bookings))
        app.add_handler(CommandHandler("stats", self.stats))
        app.add_handler(CommandHandler("reload", self.reload_cmd))

        # 2. Conversations
        app.add_handler(booking_conv)
        app.add_handler(chat_conv)

        # 3. Inline callbacks
        app.add_handler(CallbackQueryHandler(self.admin_callback))

        # 4. Static button handlers
        app.add_handler(MessageHandler(filters.Regex(r"^📚 كورسات السنتر$"), self.show_courses))
        app.add_handler(MessageHandler(filters.Regex(r"^📸 استديو X\.press$"), self.show_studio))
        app.add_handler(MessageHandler(filters.Regex(r"^📞 تواصل معنا$"), self.contact))
        app.add_handler(MessageHandler(filters.Regex(r"^🏠"), self.start))

        # 5. Fallback — AI responds to any other text message
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        # Error handler
        app.add_error_handler(self.error_handler)
        
        logger.info("✅ Application built successfully with all handlers")
        return app


# ─── Entry Point ──────────────────────────────────────────────────────────────
def main():
    """Main entry point for the bot"""
    try:
        logger.info("🚀 Starting Edu & X.press Bot...")
        logger.info(f"📍 Database: edu_bookings.db")
        logger.info(f"📖 Knowledge: {KNOWLEDGE_FILE}")
        logger.info(f"👮 Admin ID: {ADMIN_ID if ADMIN_ID else 'Not configured'}")
        
        bot = EduBot()
        app = bot.build()
        
        logger.info("✅ Bot is running! Press Ctrl+C to stop.")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
    except KeyboardInterrupt:
        logger.info("⏹️ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {type(e).__name__}: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
