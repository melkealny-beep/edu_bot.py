#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════╗
║         Edu Bot — سنتر Edu & مطبعة X.press              ║
║         Powered by Groq (LLaMA 3.3) + python-telegram-bot ║
╚══════════════════════════════════════════════════════════╝
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    filters, ContextTypes
)
import httpx
from dotenv import load_dotenv

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
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
ADMIN_ID       = os.getenv("ADMIN_ID")
KNOWLEDGE_FILE = os.getenv("KNOWLEDGE_FILE", "knowledge.txt")

if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN غير موجود في .env")
    sys.exit(1)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"

# ─── بيانات السنتر ────────────────────────────────────────────────────────────
CENTER = {
    "name":    "سنتر Edu",
    "studio":  "مطبعة X.press",
    "phone":   "01000000000",
    "address": "القاهرة - مدينة نصر - شارع التسعين",
    "hours":   "السبت - الخميس: 10 صباحاً - 10 مساءً",
}

COURSES = {
    "1": {"name": "📚 مهارات التدريس الحديث",       "price": "800 جنيه",  "duration": "4 أسابيع (8 جلسات)"},
    "2": {"name": "🎬 إنتاج المحتوى التعليمي",       "price": "1200 جنيه", "duration": "3 أسابيع (6 جلسات)"},
    "3": {"name": "🖥️ التعليم الإلكتروني E-learning", "price": "1500 جنيه", "duration": "6 أسابيع (12 جلسة)"},
    "4": {"name": "🎨 تصميم المواد التعليمية",        "price": "900 جنيه",  "duration": "3 أسابيع (6 جلسات)"},
    "5": {"name": "🗣️ مهارات التواصل والإلقاء",      "price": "600 جنيه",  "duration": "2 أسبوع (4 جلسات)"},
}

PACKAGES = {
    "1": {"name": "⚡ باقة سريعة",    "hours": "ساعة واحدة",          "price": "300 جنيه"},
    "2": {"name": "🌟 باقة كورس",     "hours": "3 ساعات",             "price": "700 جنيه"},
    "3": {"name": "👑 باقة احترافية", "hours": "يوم كامل (8 ساعات)",  "price": "2000 جنيه"},
    "4": {"name": "📦 باقة شهرية",    "hours": "8 ساعات/الشهر",       "price": "1500 جنيه/شهر"},
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
    ["📅 احجز دلوقتي",  "💬 اسألنا"],
    ["📞 تواصل معنا"]
], resize_keyboard=True)

# ─── Knowledge Base ───────────────────────────────────────────────────────────
def load_knowledge() -> str:
    """تحميل قاعدة المعرفة من الملف الخارجي"""
    try:
        path = Path(KNOWLEDGE_FILE)
        if path.exists():
            text = path.read_text(encoding="utf-8")
            logger.info(f"✅ تم تحميل قاعدة المعرفة من {KNOWLEDGE_FILE}")
            return text
    except Exception as e:
        logger.error(f"خطأ في تحميل knowledge.txt: {e}")
    logger.warning("⚠️ knowledge.txt غير موجود، هيتم استخدام الـ fallback")
    return _fallback_knowledge()

def _fallback_knowledge() -> str:
    return f"""أنت إيدو، المساعد الذكي لـ {CENTER['name']} و{CENTER['studio']}.
العنوان: {CENTER['address']} | التليفون: {CENTER['phone']} | المواعيد: {CENTER['hours']}
تكلم بالعامية المصرية الودودة. لو حد عايز يحجز، قوله يضغط زرار احجز دلوقتي."""

# ─── Groq AI ──────────────────────────────────────────────────────────────────
class GroqAI:
    def __init__(self):
        self.knowledge = load_knowledge()
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        return f"""أنت "إيدو" - المساعد الذكي لسنتر Edu ومطبعة X.press.

{self.knowledge}

تعليمات مهمة:
- رد دايماً بالعربي العامي المصري
- كن مختصر وواضح ومفيد
- لو حد عايز يحجز، قوله يضغط زرار "📅 احجز دلوقتي"
- لو السؤال مش متعلق بالسنتر أو الاستديو، اعتذر بأدب وخليه يسأل عن خدماتنا"""

    async def ask(self, message: str, history: list = None) -> Optional[str]:
        """إرسال سؤال للـ AI مع تاريخ المحادثة"""
        if not GROQ_API_KEY:
            return f"خدمة الذكاء الاصطناعي غير متاحة دلوقتي.\nتواصل معنا مباشرة على {CENTER['phone']} 😊"

        messages = [{"role": "system", "content": self.system_prompt}]
        if history:
            messages.extend(history[-6:])  # آخر 6 رسائل فقط للحفاظ على الـ context
        messages.append({"role": "user", "content": message})

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    GROQ_API_URL,
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": GROQ_MODEL,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 800
                    }
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            return "الرد بياخد وقت أكتر من المعتاد، حاول تاني بعد شوية 🙏"
        except httpx.HTTPStatusError as e:
            logger.error(f"Groq HTTP error {e.response.status_code}: {e}")
            return None
        except Exception as e:
            logger.error(f"Groq error: {e}")
            return None

    def reload_knowledge(self):
        """إعادة تحميل قاعدة المعرفة بدون ريستارت"""
        self.knowledge = load_knowledge()
        self.system_prompt = self._build_system_prompt()
        logger.info("🔄 تم إعادة تحميل قاعدة المعرفة")

# ─── Database ─────────────────────────────────────────────────────────────────
class Database:
    def __init__(self, db_path: str = "edu_bookings.db"):
        self.db_path = db_path
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS bookings (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id  INTEGER NOT NULL,
                    name         TEXT    NOT NULL,
                    phone        TEXT    NOT NULL,
                    booking_type TEXT,
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
            ''')
            conn.commit()

    def upsert_user(self, telegram_id: int, first_name: str, username: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO users (telegram_id, first_name, username)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    last_seen = CURRENT_TIMESTAMP,
                    total_msgs = total_msgs + 1,
                    first_name = excluded.first_name
            ''', (telegram_id, first_name, username or ""))
            conn.commit()

    def save_booking(self, telegram_id, name, phone, booking_type, details, date) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'INSERT INTO bookings (telegram_id, name, phone, booking_type, details, preferred_date) VALUES (?,?,?,?,?,?)',
                    (telegram_id, name, phone, booking_type, details, date)
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"save_booking error: {e}")
            return False

    def get_all_bookings(self) -> list:
        try:
            with sqlite3.connect(self.db_path) as conn:
                return conn.execute(
                    'SELECT name, phone, booking_type, details, preferred_date, status, created_at FROM bookings ORDER BY created_at DESC'
                ).fetchall()
        except:
            return []

    def count_bookings(self) -> int:
        try:
            with sqlite3.connect(self.db_path) as conn:
                return conn.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]
        except:
            return 0

    def count_users(self) -> int:
        try:
            with sqlite3.connect(self.db_path) as conn:
                return conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        except:
            return 0

    def get_pending_bookings(self) -> list:
        try:
            with sqlite3.connect(self.db_path) as conn:
                return conn.execute(
                    "SELECT id, name, phone, booking_type, details, preferred_date, created_at FROM bookings WHERE status='pending' ORDER BY created_at DESC"
                ).fetchall()
        except:
            return []

    def update_booking_status(self, booking_id: int, status: str):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('UPDATE bookings SET status=? WHERE id=?', (status, booking_id))
                conn.commit()
        except Exception as e:
            logger.error(f"update_status error: {e}")

# ─── Bot ──────────────────────────────────────────────────────────────────────
class EduBot:
    def __init__(self):
        self.db  = Database()
        self.ai  = GroqAI()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _is_confirm(self, text: str) -> bool:
        return any(w in text for w in ["✅", "تأكيد", "أيوه", "ايوه", "اه", "نعم", "تمام", "صح", "موافق", "ok", "yes"])

    def _is_cancel(self, text: str) -> bool:
        return any(w in text for w in ["❌", "إلغاء", "الغ", "لأ", "لا", "مش عايز", "cancel", "no"])

    def _is_back(self, text: str) -> bool:
        return any(w in text for w in ["رجوع", "🏠", "الرئيسية", "القائمة"])

    def _is_admin(self, user_id: int) -> bool:
        return ADMIN_ID and str(user_id) == str(ADMIN_ID)

    async def _notify_admin(self, context, booking: dict, user_id: int):
        if not ADMIN_ID:
            return
        try:
            btype_label = "📚 كورس" if booking.get("type") == "course" else "📸 جلسة تصوير"
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_{user_id}"),
                    InlineKeyboardButton("❌ رفض",   callback_data=f"reject_{user_id}"),
                ]
            ])
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🔔 *حجز جديد!*\n\n"
                    f"👤 {booking['name']}\n"
                    f"📞 {booking['phone']}\n"
                    f"🎯 {btype_label}\n"
                    f"📌 {booking.get('details', '')}\n"
                    f"📅 {booking.get('date', '')}\n"
                    f"🆔 TG: {user_id}\n"
                    f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                ),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Admin notify error: {e}")

    # ── /start ────────────────────────────────────────────────────────────────
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.upsert_user(user.id, user.first_name, user.username)
        await update.message.reply_text(
            f"👋 أهلاً وسهلاً يا *{user.first_name}*!\n\n"
            f"أنا إيدو، مساعدك الذكي في:\n\n"
            f"📚 *{CENTER['name']}*\n"
            f"سنتر متخصص في تطوير مهارات المدرسين\n\n"
            f"📸 *{CENTER['studio']}*\n"
            f"استديو تصوير احترافي لإنتاج المحتوى التعليمي\n\n"
            f"📍 {CENTER['address']}\n"
            f"⏰ {CENTER['hours']}\n\n"
            "اختار من القائمة اللي تحت 👇",
            reply_markup=MAIN_KEYBOARD,
            parse_mode="Markdown"
        )

    # ── عرض الكورسات ─────────────────────────────────────────────────────────
    async def show_courses(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = f"📚 *كورسات {CENTER['name']}*\n"
        msg += "متخصصة في تطوير مهارات المدرسين 🎓\n"
        msg += "━" * 28 + "\n\n"
        for c in COURSES.values():
            msg += f"{c['name']}\n"
            msg += f"⏱ {c['duration']}  |  💰 {c['price']}\n\n"
        msg += "━" * 28 + "\n"
        msg += "💬 اسألنا عن أي كورس أو احجز مباشرة 👇"
        keyboard = [["📅 احجز كورس دلوقتي"], ["💬 اسألنا عن الكورسات"], ["🏠 الرئيسية"]]
        await update.message.reply_text(
            msg,
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
            parse_mode="Markdown"
        )

    # ── عرض الاستديو ─────────────────────────────────────────────────────────
    async def show_studio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        pkg_msg = f"📸 *{CENTER['studio']} — الباقات والأسعار*\n\n"
        for p in PACKAGES.values():
            pkg_msg += f"{p['name']}\n"
            pkg_msg += f"⏱ {p['hours']}  |  💰 {p['price']}\n\n"
        pkg_msg += "━" * 28 + "\n"
        pkg_msg += "🎬 لوكيشنات متاحة: كلاس دراسي | مكتبة | ستوديو أبيض | ركن طبيعي | أوفيس | خلفية سوداء\n\n"
        pkg_msg += "اسألنا عن اللوكيشن الأنسب لمادتك 😊"
        keyboard = [["📅 احجز جلسة تصوير"], ["💬 اسألنا عن الاستديو"], ["🏠 الرئيسية"]]
        await update.message.reply_text(
            pkg_msg,
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
            parse_mode="Markdown"
        )

    # ── تواصل معنا ────────────────────────────────────────────────────────────
    async def contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            f"📞 *تواصل معنا*\n\n"
            f"📱 {CENTER['phone']}\n"
            f"📍 {CENTER['address']}\n"
            f"⏰ {CENTER['hours']}\n\n"
            "أو كلمنا هنا وهنرد عليك في أقرب وقت 😊",
            reply_markup=MAIN_KEYBOARD,
            parse_mode="Markdown"
        )

    # ══════════════════════════════════════════════════════════════
    #  BOOKING FLOW
    # ══════════════════════════════════════════════════════════════
    async def book_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["booking"] = {}
        text = update.message.text

        if "كورس" in text:
            context.user_data["booking"]["type"] = "course"
            return await self._ask_name(update)
        elif any(w in text for w in ["تصوير", "جلسة", "استديو"]):
            context.user_data["booking"]["type"] = "studio"
            return await self._ask_name(update)
        else:
            keyboard = [["📚 حجز كورس", "📸 حجز جلسة تصوير"], ["🏠 رجوع"]]
            await update.message.reply_text(
                "حجز لـ إيه؟ 👇",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            )
            return BOOK_TYPE

    async def book_get_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if self._is_back(text):
            await update.message.reply_text("تمام! رجعنا 😊", reply_markup=MAIN_KEYBOARD)
            return ConversationHandler.END
        if "كورس" in text:
            context.user_data["booking"]["type"] = "course"
        elif any(w in text for w in ["تصوير", "جلسة"]):
            context.user_data["booking"]["type"] = "studio"
        else:
            await update.message.reply_text("اختار من الزرارين 👆")
            return BOOK_TYPE
        return await self._ask_name(update)

    async def _ask_name(self, update: Update):
        await update.message.reply_text(
            "😊 تمام! هنكمل الحجز.\n\nاكتب *اسمك الكامل* من فضلك:",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return BOOK_NAME

    async def book_get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        name = update.message.text.strip()
        if len(name) < 3:
            await update.message.reply_text("⚠️ اكتب اسمك الكامل من فضلك.")
            return BOOK_NAME
        context.user_data["booking"]["name"] = name
        await update.message.reply_text(f"تمام يا *{name}* 👍\n\n📞 رقم تليفونك؟", parse_mode="Markdown")
        return BOOK_PHONE

    async def book_get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        phone = update.message.text.strip()
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) < 10:
            await update.message.reply_text("⚠️ الرقم مش صح، حاول تاني (11 رقم على الأقل).")
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

    async def book_get_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        if self._is_back(text):
            await update.message.reply_text("تمام!", reply_markup=MAIN_KEYBOARD)
            return ConversationHandler.END
        context.user_data["booking"]["details"] = text
        await update.message.reply_text(
            "📅 *إيه الوقت اللي بيناسبك؟*\n\n"
            "اكتب مثلاً: _الخميس الجاي الساعة 4 العصر_",
            parse_mode="Markdown"
        )
        return BOOK_DATE

    async def book_get_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["booking"]["date"] = update.message.text.strip()
        b = context.user_data["booking"]
        btype_label = "📚 كورس" if b.get("type") == "course" else "📸 جلسة تصوير"
        keyboard = [["✅ تأكيد الحجز", "❌ إلغاء"]]
        await update.message.reply_text(
            f"📋 *ملخص الحجز:*\n\n"
            f"👤 الاسم: {b['name']}\n"
            f"📞 التليفون: {b['phone']}\n"
            f"🎯 النوع: {btype_label}\n"
            f"📌 التفاصيل: {b['details']}\n"
            f"📅 الوقت: {b['date']}\n\n"
            "✅ البيانات صح؟",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
            parse_mode="Markdown"
        )
        return BOOK_CONFIRM

    async def book_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text    = update.message.text

        if self._is_cancel(text):
            context.user_data["booking"] = {}
            await update.message.reply_text(
                "تمام! الحجز اتلغى.\nلو عايز تحجز تاني اضغط احجز دلوقتي 😊",
                reply_markup=MAIN_KEYBOARD
            )
            return ConversationHandler.END

        if self._is_confirm(text):
            b = context.user_data.get("booking", {})
            success = self.db.save_booking(
                user_id, b["name"], b["phone"],
                b.get("type", ""), b.get("details", ""), b.get("date", "")
            )
            if success:
                btype_label = "كورس" if b.get("type") == "course" else "جلسة تصوير"
                await update.message.reply_text(
                    f"🎉 *تم الحجز بنجاح يا {b['name']}!*\n\n"
                    f"هيتواصل معك فريقنا لتأكيد الـ {btype_label}.\n\n"
                    f"📞 {CENTER['phone']}\n"
                    f"📍 {CENTER['address']}",
                    reply_markup=MAIN_KEYBOARD,
                    parse_mode="Markdown"
                )
                await self._notify_admin(context, b, user_id)
            else:
                await update.message.reply_text("❌ حصل خطأ، حاول تاني.", reply_markup=MAIN_KEYBOARD)
            return ConversationHandler.END

        # لو ضغط حاجة تانية
        keyboard = [["✅ تأكيد الحجز", "❌ إلغاء"]]
        await update.message.reply_text(
            "اضغط على أحد الزرارين 👆",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return BOOK_CONFIRM

    async def book_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("تم الإلغاء. 😊", reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    # ══════════════════════════════════════════════════════════════
    #  AI CHAT — مع تاريخ المحادثة
    # ══════════════════════════════════════════════════════════════
    async def chat_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data.setdefault("chat_history", [])
        await update.message.reply_text(
            "💬 اسألني أي سؤال عن الكورسات، الاستديو، الباقات، أو أي حاجة تانية!\n"
            "_(اكتب 'رجوع' للخروج)_",
            reply_markup=ReplyKeyboardMarkup([["🏠 رجوع"]], resize_keyboard=True),
            parse_mode="Markdown"
        )
        return CHAT_INPUT

    async def chat_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if self._is_back(text):
            context.user_data["chat_history"] = []
            await update.message.reply_text("رجعنا للقائمة 😊", reply_markup=MAIN_KEYBOARD)
            return ConversationHandler.END

        user = update.effective_user
        self.db.upsert_user(user.id, user.first_name, user.username)

        await update.message.chat.send_action("typing")

        history = context.user_data.get("chat_history", [])
        response = await self.ai.ask(text, history)

        if response:
            # حفظ في الـ history
            history.append({"role": "user",      "content": text})
            history.append({"role": "assistant",  "content": response})
            context.user_data["chat_history"] = history[-10:]  # آخر 10 رسائل

            await update.message.reply_text(
                response,
                reply_markup=ReplyKeyboardMarkup([["🏠 رجوع"]], resize_keyboard=True)
            )
        else:
            await update.message.reply_text(
                f"مش قادر أرد دلوقتي، تواصل معنا مباشرة على {CENTER['phone']} 😊",
                reply_markup=ReplyKeyboardMarkup([["🏠 رجوع"]], resize_keyboard=True)
            )
        return CHAT_INPUT

    # ── General Message ───────────────────────────────────────────────────────
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # ══════════════════════════════════════════════════════════════
    #  ADMIN — Inline Callbacks
    # ══════════════════════════════════════════════════════════════
    async def admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if not self._is_admin(query.from_user.id):
            return

        data = query.data
        if data.startswith("confirm_") or data.startswith("reject_"):
            action, user_id = data.split("_", 1)
            label = "✅ تم تأكيد الحجز" if action == "confirm" else "❌ تم رفض الحجز"
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"{label} للمستخدم {user_id}")

    # ── Admin Commands ─────────────────────────────────────────────────────────
    async def show_bookings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ للمشرف فقط.")
            return
        bookings = self.db.get_all_bookings()
        if not bookings:
            await update.message.reply_text("📭 مفيش حجوزات لسه.")
            return
        msg = f"📋 *الحجوزات ({len(bookings)} حجز)*\n{'─'*25}\n\n"
        for i, (name, phone, btype, details, date, status, created) in enumerate(bookings, 1):
            btype_label  = "📚 كورس" if btype == "course" else "📸 استديو"
            status_label = "✅" if status == "confirmed" else ("❌" if status == "rejected" else "⏳")
            entry = (
                f"#{i} {btype_label} {status_label}\n"
                f"👤 {name} | 📞 {phone}\n"
                f"📌 {details}\n"
                f"📅 {date}\n"
                f"🕐 {created[:16]}\n{'─'*20}\n"
            )
            if len(msg) + len(entry) > 4000:
                await update.message.reply_text(msg, parse_mode="Markdown")
                msg = ""
            msg += entry
        if msg:
            await update.message.reply_text(msg, parse_mode="Markdown")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ للمشرف فقط.")
            return
        total_bookings = self.db.count_bookings()
        total_users    = self.db.count_users()
        pending        = len(self.db.get_pending_bookings())
        await update.message.reply_text(
            f"📊 *إحصائيات البوت*\n\n"
            f"👥 المستخدمين: {total_users}\n"
            f"📋 الحجوزات: {total_bookings}\n"
            f"⏳ قيد الانتظار: {pending}\n\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="Markdown"
        )

    async def reload_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إعادة تحميل قاعدة المعرفة بدون ريستارت"""
        if not self._is_admin(update.effective_user.id):
            return
        self.ai.reload_knowledge()
        await update.message.reply_text("✅ تم إعادة تحميل knowledge.txt بنجاح!")

    # ── Error Handler ─────────────────────────────────────────────────────────
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Error: {context.error}", exc_info=context.error)
        if update and update.message:
            try:
                await update.message.reply_text("❌ حصل خطأ، حاول تاني.", reply_markup=MAIN_KEYBOARD)
            except:
                pass

    # ── Build App ─────────────────────────────────────────────────────────────
    def build(self) -> Application:
        app = Application.builder().token(TELEGRAM_TOKEN).build()

        BOOK_TRIGGER = (
            r"📅 احجز دلوقتي|احجز كورس|احجز جلسة تصوير|"
            r"عايز احجز|عاوز احجز|محتاج احجز|"
            r"حجز كورس|حجز جلسة|حجزلي|احجزلي|"
            r"عايز موعد|عاوز موعد|ابي احجز|"
            r"📅 احجز كورس دلوقتي|📅 احجز جلسة تصوير"
        )

        booking_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex(BOOK_TRIGGER), self.book_start)],
            states={
                BOOK_TYPE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_type)],
                BOOK_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_name)],
                BOOK_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_phone)],
                BOOK_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_details)],
                BOOK_DATE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_date)],
                BOOK_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_confirm)],
            },
            fallbacks=[
                CommandHandler("cancel", self.book_cancel),
                MessageHandler(filters.Regex(r"^/start$"), self.start),
            ],
            allow_reentry=True
        )

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

        # Commands
        app.add_handler(CommandHandler("start",    self.start))
        app.add_handler(CommandHandler("bookings", self.show_bookings))
        app.add_handler(CommandHandler("stats",    self.stats))
        app.add_handler(CommandHandler("reload",   self.reload_cmd))

        # Conversations
        app.add_handler(booking_conv)
        app.add_handler(chat_conv)

        # Inline callbacks
        app.add_handler(CallbackQueryHandler(self.admin_callback))

        # Static handlers
        app.add_handler(MessageHandler(filters.Regex(r"^📚 كورسات السنتر$"),  self.show_courses))
        app.add_handler(MessageHandler(filters.Regex(r"^📸 استديو X\.press$"), self.show_studio))
        app.add_handler(MessageHandler(filters.Regex(r"^📞 تواصل معنا$"),      self.contact))
        app.add_handler(MessageHandler(filters.Regex(r"^🏠"),                  self.start))

        # Fallback — AI يرد على أي رسالة تانية
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        app.add_error_handler(self.error_handler)
        return app


# ─── Entry Point ──────────────────────────────────────────────────────────────
def main():
    logger.info("🚀 Starting Edu & X.press Bot...")
    bot = EduBot()
    app = bot.build()
    logger.info("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
