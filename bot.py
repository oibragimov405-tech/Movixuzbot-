import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# === SOZLAMALAR ===
# ============================================================
import os
BOT_TOKEN = os.getenv("BOT_TOKEN", "YANGI_TOKEN_BU_YERGA")   # @BotFather dan yangi token oling!
ADMIN_IDS = [123456789]               # Sizning Telegram ID ingiz (@userinfobot dan bilib oling)
ADMIN_USERNAME = "smmgarand"
UZCARD_NUMBER = "5614684704857034"
UZUM_NUMBER = "9860123456789012"

# ============================================================
# === DATABASE ===
# ============================================================
class Database:
    def __init__(self, db_path="bot.db"):
        self.db_path = db_path
        self.create_tables()

    def conn(self):
        return sqlite3.connect(self.db_path)

    def create_tables(self):
        with self.conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    balance INTEGER DEFAULT 0,
                    vip_until TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS films (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    code TEXT UNIQUE NOT NULL,
                    genre TEXT DEFAULT '',
                    file_id TEXT,
                    views INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS views_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    film_code TEXT,
                    viewed_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)

    def add_user(self, user_id, username, full_name):
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
                      (user_id, username, full_name))

    def get_balance(self, user_id):
        with self.conn() as c:
            row = c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row[0] if row else 0

    def add_balance(self, user_id, amount):
        with self.conn() as c:
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))

    def get_all_users(self):
        with self.conn() as c:
            rows = c.execute("SELECT user_id, username, full_name, balance, created_at FROM users ORDER BY created_at DESC").fetchall()
            return [{"user_id": r[0], "username": r[1], "full_name": r[2], "balance": r[3], "created_at": r[4]} for r in rows]

    def find_user(self, query):
        with self.conn() as c:
            if query.isdigit():
                row = c.execute("SELECT user_id, username, full_name, created_at FROM users WHERE user_id=?", (int(query),)).fetchone()
            else:
                row = c.execute("SELECT user_id, username, full_name, created_at FROM users WHERE username LIKE ?", (f"%{query}%",)).fetchone()
            if row:
                return {"user_id": row[0], "username": row[1], "full_name": row[2], "created_at": row[3]}
            return None

    def add_film(self, title, code, genre="", file_id=None):
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO films (title, code, genre, file_id) VALUES (?, ?, ?, ?)",
                      (title, code, genre, file_id))

    def get_film_by_code(self, code):
        with self.conn() as c:
            row = c.execute("SELECT * FROM films WHERE code=?", (code,)).fetchone()
            return self._film_dict(row) if row else None

    def search_films_by_name(self, query):
        with self.conn() as c:
            rows = c.execute("SELECT * FROM films WHERE title LIKE ?", (f"%{query}%",)).fetchall()
            return [self._film_dict(r) for r in rows]

    def get_all_films(self):
        with self.conn() as c:
            rows = c.execute("SELECT * FROM films ORDER BY created_at DESC").fetchall()
            return [self._film_dict(r) for r in rows]

    def delete_film(self, code):
        with self.conn() as c:
            c.execute("DELETE FROM films WHERE code=?", (code,))

    def update_film_title(self, code, new_title):
        with self.conn() as c:
            c.execute("UPDATE films SET title=? WHERE code=?", (new_title, code))

    def increment_views(self, code):
        with self.conn() as c:
            c.execute("UPDATE films SET views = views + 1 WHERE code=?", (code,))
            c.execute("INSERT INTO views_log (film_code) VALUES (?)", (code,))

    def _film_dict(self, row):
        if not row:
            return None
        return {"id": row[0], "title": row[1], "code": row[2], "genre": row[3], "file_id": row[4], "views": row[5]}

    def get_setting(self, key):
        with self.conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def set_setting(self, key, value):
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

    def get_stats(self):
        with self.conn() as c:
            users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            films = c.execute("SELECT COUNT(*) FROM films").fetchone()[0]
            total_views = c.execute("SELECT SUM(views) FROM films").fetchone()[0] or 0
            return {"users": users, "films": films, "total_views": total_views}

    def get_today_stats(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with self.conn() as c:
            new_users = c.execute("SELECT COUNT(*) FROM users WHERE created_at LIKE ?", (f"{today}%",)).fetchone()[0]
            today_views = c.execute("SELECT COUNT(*) FROM views_log WHERE viewed_at LIKE ?", (f"{today}%",)).fetchone()[0]
            return {"new_users": new_users, "today_views": today_views}

db = Database()

# ============================================================
# === STATES ===
# ============================================================
SEARCH_CODE = 0
ADMIN_FILM_TITLE, ADMIN_FILM_CODE, ADMIN_FILM_FILE, ADMIN_BROADCAST = range(10, 14)
ADMIN_HOMIYLIK = 20
ADMIN_SEARCH_USER, ADMIN_SEARCH_FILM = range(30, 32)
ADMIN_DELETE_FILM, ADMIN_EDIT_FILM_CODE, ADMIN_EDIT_FILM_TITLE = range(40, 43)

# ============================================================
# === KLAVIATURALAR ===
# ============================================================
def main_keyboard_user(is_admin=False):
    kb = [["🔍 Kino izlash"], ["💲 Reklama va Homiylik"]]
    if is_admin:
        kb.append(["🔧 Admin panel"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def search_keyboard():
    return ReplyKeyboardMarkup([["🔙 Orqaga"]], resize_keyboard=True)

def admin_keyboard():
    return ReplyKeyboardMarkup([
        ["📊 Statistika", "👥 Foydalanuvchilar"],
        ["🔎 Qidirish", "🎬 Kino boshqaruvi"],
        ["✅ To'lovni tasdiqlash", "📢 Xabar yuborish"],
        ["🤝 Homiylik sozlash"],
        ["🔙 Asosiy menyu"]
    ], resize_keyboard=True)

def kino_boshqaruvi_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Film qo'shish", "📋 Filmlar ro'yxati"],
        ["🗑 Film o'chirish", "✏️ Film tahrirlash"],
        ["🔙 Admin panel"]
    ], resize_keyboard=True)

def qidirish_keyboard():
    return ReplyKeyboardMarkup([
        ["👤 Foydalanuvchi qidirish", "🎬 Film qidirish"],
        ["🔙 Admin panel"]
    ], resize_keyboard=True)

# ============================================================
# /start
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username or "", user.full_name or "")
    is_admin = user.id in ADMIN_IDS
    await update.message.reply_text(
        f"⭐️ Xush kelibsiz, {user.first_name}!\n\n"
        "🎬 Kino botiga xush kelibsiz!\n"
        "Quyidagi bo'limlardan birini tanlang:",
        reply_markup=main_keyboard_user(is_admin)
    )

# ============================================================
# KINO IZLASH
# ============================================================
async def kino_izlash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔢 Kino kodini kiriting:", reply_markup=search_keyboard())
    return SEARCH_CODE

async def search_by_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    film = db.get_film_by_code(code)
    if not film:
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.\n\n🔢 Boshqa kod kiriting:", reply_markup=search_keyboard())
        return SEARCH_CODE
    text = (
        f"🎬 *{film['title']}*\n"
        f"📌 Kod: `{film['code']}`\n"
        f"👁 Ko'rishlar: {film['views']}\n"
        f"🎭 Janr: {film.get('genre', 'Nomalum')}"
    )
    db.increment_views(film['code'])
    if film.get('file_id'):
        await update.message.reply_video(film['file_id'], caption=text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")
    await update.message.reply_text("🔢 Boshqa kino kodini kiriting:", reply_markup=search_keyboard())
    return SEARCH_CODE

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = update.effective_user.id in ADMIN_IDS
    await update.message.reply_text("🏠 Asosiy menyu", reply_markup=main_keyboard_user(is_admin))
    return ConversationHandler.END

# ============================================================
# REKLAMA VA HOMIYLIK
# ============================================================
async def reklama_homiylik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = db.get_setting("homiylik") or f"Reklama va homiylik bo'yicha:\n\n👨‍💼 @{ADMIN_USERNAME} ga murojaat qiling"
    await update.message.reply_text(
        f"💲 *Reklama va Homiylik*\n\n{text}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 Adminga yozish", url=f"https://t.me/{ADMIN_USERNAME}")]])
    )

# ============================================================
# ADMIN PANEL
# ============================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Sizda ruxsat yo'q.")
        return
    await update.message.reply_text("🔧 *Admin panel*\nQuyidagi bo'limni tanlang:", parse_mode="Markdown", reply_markup=admin_keyboard())

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    stats = db.get_stats()
    today = db.get_today_stats()
    await update.message.reply_text(
        f"📊 *Statistika*\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👥 Jami foydalanuvchilar: *{stats['users']}*\n"
        f"🆕 Bugun qo'shildi: *{today['new_users']}*\n\n"
        f"🎬 Jami filmlar: *{stats['films']}*\n"
        f"👁 Jami ko'rishlar: *{stats['total_views']}*\n"
        f"🔥 Bugun ko'rishlar: *{today['today_views']}*\n"
        f"━━━━━━━━━━━━━━━",
        parse_mode="Markdown", reply_markup=admin_keyboard()
    )

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    users = db.get_all_users()
    text = f"👥 *Jami foydalanuvchilar: {len(users)}*\n\n"
    for i, u in enumerate(users[:30], 1):
        username = f"@{u['username']}" if u['username'] else "—"
        text += f"{i}. {u['full_name']} | {username} | `{u['user_id']}`\n"
    if len(users) > 30:
        text += f"\n... va yana {len(users) - 30} ta"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=admin_keyboard())

async def qidirish_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("🔎 *Qidirish*\nNimani qidirmoqchisiz?", parse_mode="Markdown", reply_markup=qidirish_keyboard())

async def search_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("👤 Foydalanuvchi ID si yoki username kiriting:")
    return ADMIN_SEARCH_USER

async def search_user_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip().lstrip("@")
    user = db.find_user(query)
    if not user:
        await update.message.reply_text("❌ Foydalanuvchi topilmadi.", reply_markup=qidirish_keyboard())
    else:
        username = f"@{user['username']}" if user['username'] else "—"
        await update.message.reply_text(
            f"👤 *Foydalanuvchi:*\n\n🆔 ID: `{user['user_id']}`\n👤 Ism: {user['full_name']}\n📛 Username: {username}\n📅 Qo'shilgan: {user.get('created_at','—')}",
            parse_mode="Markdown", reply_markup=qidirish_keyboard()
        )
    return ConversationHandler.END

async def search_film_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("🎬 Film nomi yoki kodini kiriting:")
    return ADMIN_SEARCH_FILM

async def search_film_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    films = db.search_films_by_name(query) or ([db.get_film_by_code(query)] if db.get_film_by_code(query) else [])
    if not films:
        await update.message.reply_text("❌ Film topilmadi.", reply_markup=qidirish_keyboard())
    else:
        text = f"🎬 *Natijalar ({len(films)} ta):*\n\n"
        for f in films:
            text += f"🎬 {f['title']} | Kod: `{f['code']}` | 👁{f['views']}\n"
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=qidirish_keyboard())
    return ConversationHandler.END

async def kino_boshqaruvi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    stats = db.get_stats()
    await update.message.reply_text(f"🎬 *Kino boshqaruvi*\n\nJami filmlar: *{stats['films']}* ta", parse_mode="Markdown", reply_markup=kino_boshqaruvi_keyboard())

async def admin_film_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    films = db.get_all_films()
    if not films:
        await update.message.reply_text("📭 Filmlar yo'q.", reply_markup=kino_boshqaruvi_keyboard())
        return
    text = f"📋 *Filmlar ro'yxati ({len(films)} ta):*\n\n"
    for f in films:
        text += f"🎬 {f['title']} | Kod: `{f['code']}` | 👁{f['views']}\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kino_boshqaruvi_keyboard())

async def add_film_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("🎬 Film nomini kiriting:")
    return ADMIN_FILM_TITLE

async def add_film_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['film_title'] = update.message.text
    await update.message.reply_text("🔢 Film kodini kiriting:")
    return ADMIN_FILM_CODE

async def add_film_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['film_code'] = update.message.text.strip()
    await update.message.reply_text("🎭 Janrni kiriting:")
    return ADMIN_FILM_FILE

async def add_film_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['film_genre'] = update.message.text.strip()
    await update.message.reply_text("📹 Film videosini yuboring (yoki /skip yozing):")
    return ADMIN_FILM_FILE + 1

async def add_film_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = update.message.video.file_id if update.message.video else None
    db.add_film(title=context.user_data['film_title'], code=context.user_data['film_code'], genre=context.user_data.get('film_genre',''), file_id=file_id)
    await update.message.reply_text(f"✅ Film qo'shildi!\n📌 {context.user_data['film_title']}\n🔢 {context.user_data['film_code']}", reply_markup=kino_boshqaruvi_keyboard())
    return ConversationHandler.END

async def delete_film_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("🗑 O'chirmoqchi bo'lgan film kodini kiriting:")
    return ADMIN_DELETE_FILM

async def delete_film_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    film = db.get_film_by_code(code)
    if not film:
        await update.message.reply_text("❌ Film topilmadi.", reply_markup=kino_boshqaruvi_keyboard())
    else:
        db.delete_film(code)
        await update.message.reply_text(f"✅ '{film['title']}' o'chirildi.", reply_markup=kino_boshqaruvi_keyboard())
    return ConversationHandler.END

async def edit_film_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("✏️ Tahrirlash uchun film kodini kiriting:")
    return ADMIN_EDIT_FILM_CODE

async def edit_film_get_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    film = db.get_film_by_code(code)
    if not film:
        await update.message.reply_text("❌ Film topilmadi.", reply_markup=kino_boshqaruvi_keyboard())
        return ConversationHandler.END
    context.user_data['edit_code'] = code
    await update.message.reply_text(f"Hozirgi nomi: *{film['title']}*\n\nYangi nomini kiriting:", parse_mode="Markdown")
    return ADMIN_EDIT_FILM_TITLE

async def edit_film_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.update_film_title(context.user_data['edit_code'], update.message.text.strip())
    await update.message.reply_text(f"✅ Film nomi yangilandi!", reply_markup=kino_boshqaruvi_keyboard())
    return ConversationHandler.END

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("📢 Yubormoqchi bo'lgan xabaringizni kiriting:")
    return ADMIN_BROADCAST

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    sent = 0
    for u in users:
        try:
            await context.bot.send_message(u['user_id'], update.message.text)
            sent += 1
        except:
            pass
    await update.message.reply_text(f"✅ {sent} ta foydalanuvchiga yuborildi.", reply_markup=admin_keyboard())
    return ConversationHandler.END

async def confirm_payment_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("✅ Format: `/topup USER_ID SUMMA`\n\nMasalan: `/topup 123456789 25000`", parse_mode="Markdown")

async def topup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        _, user_id, amount = update.message.text.split()
        db.add_balance(int(user_id), int(amount))
        await update.message.reply_text(f"✅ {user_id} ga {amount} so'm qo'shildi.")
        await context.bot.send_message(int(user_id), f"✅ Hisobingizga {amount} so'm qo'shildi!")
    except:
        await update.message.reply_text("❌ Format: /topup USER_ID SUMMA")

async def set_homiylik_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    current = db.get_setting("homiylik") or "Yo'q"
    await update.message.reply_text(f"🤝 Hozirgi matn:\n{current}\n\nYangi matn kiriting:")
    return ADMIN_HOMIYLIK

async def set_homiylik_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.set_setting("homiylik", update.message.text)
    await update.message.reply_text("✅ Yangilandi!", reply_markup=admin_keyboard())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await back_to_main(update, context)
    return ConversationHandler.END

# ============================================================
# MAIN
# ============================================================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    search_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 Kino izlash$"), kino_izlash)],
        states={SEARCH_CODE: [MessageHandler(filters.Regex("^🔙 Orqaga$"), back_to_main), MessageHandler(filters.TEXT & ~filters.COMMAND, search_by_code)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex("^🔙 Orqaga$"), back_to_main)]
    )
    add_film_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Film qo'shish$"), add_film_start)],
        states={
            ADMIN_FILM_TITLE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_film_title)],
            ADMIN_FILM_CODE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_film_code)],
            ADMIN_FILM_FILE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_film_file)],
            ADMIN_FILM_FILE+1:  [MessageHandler(filters.VIDEO | filters.TEXT, add_film_save)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    delete_film_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🗑 Film o'chirish$"), delete_film_start)],
        states={ADMIN_DELETE_FILM: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_film_do)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    edit_film_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✏️ Film tahrirlash$"), edit_film_start)],
        states={
            ADMIN_EDIT_FILM_CODE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_film_get_code)],
            ADMIN_EDIT_FILM_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_film_save)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    search_user_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^👤 Foydalanuvchi qidirish$"), search_user_start)],
        states={ADMIN_SEARCH_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_user_do)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    search_film_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎬 Film qidirish$"), search_film_start)],
        states={ADMIN_SEARCH_FILM: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_film_do)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Xabar yuborish$"), broadcast_start)],
        states={ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    homiylik_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🤝 Homiylik sozlash$"), set_homiylik_start)],
        states={ADMIN_HOMIYLIK: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_homiylik_save)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("topup", topup_command))
    app.add_handler(search_conv)
    app.add_handler(add_film_conv)
    app.add_handler(delete_film_conv)
    app.add_handler(edit_film_conv)
    app.add_handler(search_user_conv)
    app.add_handler(search_film_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(homiylik_conv)

    app.add_handler(MessageHandler(filters.Regex("^💲 Reklama va Homiylik$"), reklama_homiylik))
    app.add_handler(MessageHandler(filters.Regex("^🔧 Admin panel$"), admin_panel))
    app.add_handler(MessageHandler(filters.Regex("^📊 Statistika$"), admin_stats))
    app.add_handler(MessageHandler(filters.Regex("^👥 Foydalanuvchilar$"), admin_users))
    app.add_handler(MessageHandler(filters.Regex("^🔎 Qidirish$"), qidirish_menu))
    app.add_handler(MessageHandler(filters.Regex("^🎬 Kino boshqaruvi$"), kino_boshqaruvi))
    app.add_handler(MessageHandler(filters.Regex("^📋 Filmlar ro'yxati$"), admin_film_list))
    app.add_handler(MessageHandler(filters.Regex("^✅ To'lovni tasdiqlash$"), confirm_payment_start))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Asosiy menyu$"), back_to_main))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Admin panel$"), admin_panel))

    print("✅ Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
