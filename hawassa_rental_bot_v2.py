"""
Hawassa Rental Telegram Bot — Fully Integrated Production Code
==============================================================
Features:
- Railway Persistent Volume Auto-Detection (Prevents data loss on restart)
- Admin-Only Step-by-Step Interactive Post Creation (/post)
- Interactive Broadcast supporting Text, Photos, and Videos (/broadcast)
- /stats and /status showing usernames, last subcity, and room searched
- HTML Parsing (Zero markdown crash errors)
"""

import logging
import os
import re
import sqlite3
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters
)

# ---------- Configuration & Setup ----------

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/Hawassa_Rental")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "Jatech_support")

# Automatically use Railway's persistent /data volume if available, else local file
DB_FILE = os.getenv("DB_PATH", "/data/rental_bot.db")
if not os.path.exists("/data") and not os.path.isabs(DB_FILE):
    DB_FILE = "rental_bot.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

SUBCITIES = [
    "Tabor", "Hawela-Tula", "Addis Ketema", "Hayek Dare",
    "Menehariya", "Misrak", "Bahile Adarash", "Mehal Ketema",
]

SUBCITY_MAP = {
    "Tabor": "tabor", "ታቦር": "Tabor",
    "Hawela": "hawela-Tula", "ቱላ": "Hawela-Tula", "ሐዋላ": "Hawela-Tula",
    "Addis ketema": "addis Ketema", "አዲስ ከተማ": "Addis Ketema",
    "Hayek dare": "hayek Dare", "ኃይቅ ዳር": "Hayek Dare", "ሀይቅ ዳር": "Hayek Dare",
    "Menehariya": "menehariya", "መነሀሪያ": "Menehariya", "መነሃሪያ": "Menehariya",
    "Misrak": "misrak", "ምስራቅ": "Misrak",
    "Bahile adarash": "bahile Adarash", "ባህለ አዳራሽ": "Bahile Adarash", "ባህል አዳራሽ": "Bahile Adarash",
    "Mehal ketema": "mehal Ketema", "ማዕከል ከተማ": "Mehal Ketema", "መሀል ከተማ": "Mehal Ketema"
}

BUDGETS = [
    ("2000-5000 ብር / ETB", 2000, 5000),
    ("5000-10000 ብር / ETB", 5000, 10000),
    ("10000-15000 ብር / ETB", 10000, 15000),
    ("15000+ ብር / ETB", 15000, None),
]

ROOM_TYPES = ["ባለ 1", "ባለ 2", "ባለ 3", "ባለ 4", "ሙሉ ግቢ"]

PHONE_REGEX = re.compile(r"(?:\+251|0)9\d{8}")


# ---------- Database Helper Functions ----------

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER UNIQUE,
                subcity TEXT,
                room TEXT,
                price INTEGER,
                phone TEXT,
                raw_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_subcity TEXT,
                last_room TEXT
            )
        """)
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN last_subcity TEXT")
            cursor.execute("ALTER TABLE users ADD COLUMN last_room TEXT")
        except Exception:
            pass
            
        conn.commit()


def register_user(user):
    with get_db() as conn:
        user_exists = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,)).fetchone()
        if not user_exists:
            conn.execute("""
                INSERT INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
            """, (user.id, user.username, user.first_name))
        else:
            conn.execute("""
                UPDATE users SET username = ?, first_name = ? WHERE user_id = ?
            """, (user.username, user.first_name, user.id))
        conn.commit()


def update_user_search(user_id, subcity=None, room=None):
    with get_db() as conn:
        if subcity:
            conn.execute("UPDATE users SET last_subcity = ? WHERE user_id = ?", (subcity, user_id))
        if room:
            conn.execute("UPDATE users SET last_room = ? WHERE user_id = ?", (room, user_id))
        conn.commit()


def save_listing(message_id, subcity, room, price, phone, raw_text):
    if not message_id or not subcity:
        return
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO listings (message_id, subcity, room, price, phone, raw_text)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (message_id, subcity, room, price, phone, raw_text))
        conn.commit()


def delete_listing(message_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM listings WHERE message_id = ?", (message_id,))
        conn.commit()
        return cursor.rowcount > 0


def search_listings(subcity, room, budget_low, budget_high):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM listings WHERE subcity = ? AND room = ?", (subcity, room))
        rows = cursor.fetchall()

        if not rows and subcity:
            cursor.execute("SELECT * FROM listings WHERE subcity = ?", (subcity,))
            rows = cursor.fetchall()

    exact = []
    related = []

    for row in rows:
        price = row["price"]
        if price is not None and budget_low is not None:
            in_range = True
            if price < budget_low: in_range = False
            if budget_high is not None and price > budget_high: in_range = False
            if in_range:
                exact.append(row)
            else:
                related.append(row)
        else:
            related.append(row)

    return exact, related


async def is_user_joined(bot, user_id: int) -> bool:
    if not CHANNEL_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        logger.error(f"Error checking channel membership: {e}")
        return True


# ---------- Inline Keyboards ----------

def get_force_join_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("📢 ቻናሉን ይቀላቀሉ (Join Channel)", url=CHANNEL_LINK)],[InlineKeyboardButton("✅ አረጋግጥ (Verify Join)", callback_data="check_join")]])

def get_language_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("አማርኛ 🇪🇹", callback_data="lang:am"), InlineKeyboardButton("English 🇬🇧", callback_data="lang:en")]])

def get_role_keyboard(lang="am"):
    if lang == "am":
        buttons = [[InlineKeyboardButton("🏠 አከራይ / ሻጭ", callback_data="role:landlord")], [InlineKeyboardButton("🔍 ተከራይ", callback_data="role:tenant")], [InlineKeyboardButton("🌐 ቋንቋ ቀይር", callback_data="back_to_lang")]]
    else:
        buttons = [[InlineKeyboardButton("🏠 Landlord / Seller", callback_data="role:landlord")], [InlineKeyboardButton("🔍 Tenant", callback_data="role:tenant")], [InlineKeyboardButton("🌐 Change Language", callback_data="back_to_lang")]]
    return InlineKeyboardMarkup(buttons)

def get_landlord_keyboard(lang="am"):
    contact_label = "💬 አድሚን ያናግሩ (Contact Admin)" if lang == "am" else f"💬 Contact Admin (@{SUPPORT_USERNAME})"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
    return InlineKeyboardMarkup([[InlineKeyboardButton(contact_label, url=f"https://t.me/{SUPPORT_USERNAME}")], [InlineKeyboardButton(main_menu_label, callback_data="restart_search")]])

def get_subcity_keyboard(lang="am"):
    buttons = [[InlineKeyboardButton(sc, callback_data=f"subcity:{sc}")] for sc in SUBCITIES]
    back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
    buttons.append([InlineKeyboardButton(back_label, callback_data="back_to_role")])
    return InlineKeyboardMarkup(buttons)

def get_budget_keyboard(lang="am"):
    buttons = [[InlineKeyboardButton(label, callback_data=f"budget:{low}:{high or ''}")] for label, low, high in BUDGETS]
    back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
    buttons.append([InlineKeyboardButton(back_label, callback_data="back_to_subcity")])
    buttons.append([InlineKeyboardButton(main_menu_label, callback_data="restart_search")])
    return InlineKeyboardMarkup(buttons)

def get_room_keyboard(lang="am"):
    buttons = [[InlineKeyboardButton(r, callback_data=f"room:{r}")] for r in ROOM_TYPES]
    back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
    buttons.append([InlineKeyboardButton(back_label, callback_data="back_to_budget")])
    buttons.append([InlineKeyboardButton(main_menu_label, callback_data="restart_search")])
    return InlineKeyboardMarkup(buttons)

def get_result_action_keyboard(lang="am"):
    contact_label = f"💬 ያናግሩ / Contact (@{SUPPORT_USERNAME})"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
    return InlineKeyboardMarkup([[InlineKeyboardButton(contact_label, url=f"https://t.me/{SUPPORT_USERNAME}")], [InlineKeyboardButton(main_menu_label, callback_data="restart_search")]])


# ---------- Channel Listener ----------

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post or update.edited_channel_post
    if not post or not (post.text or post.caption): return
    if CHANNEL_ID and post.chat.id != CHANNEL_ID: return

    post_text = post.text or post.caption
    parsed = parse_listing(post_text)

    save_listing(
        message_id=post.message_id,
        subcity=parsed["subcity"],
        room=parsed["room"],
        price=parsed["price"],
        phone=parsed["phone"],
        raw_text=post_text
    )


# ---------- States for Conversations ----------
(
    POST_PHOTO, POST_SUBCITY, POST_TYPE, POST_ROOM, POST_PRICE, POST_PHONE,
    BROADCAST_MSG
) = range(7)


# ---------- Admin Post Creation Wizard ----------

async def start_post_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    context.user_data["admin_post"] = {}
    await update.message.reply_text("📸 <b>ማስታወቂያ መፍጠሪያ (Post Creator)</b>\n\nእባክዎ የቤቱን ፎቶ ይላኩ (Please send the house photo):", parse_mode="HTML")
    return POST_PHOTO

async def process_post_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["admin_post"]["photo"] = update.message.photo[-1].file_id
    buttons = [[InlineKeyboardButton(sc, callback_data=f"post_sc:{sc}")] for sc in SUBCITIES]
    await update.message.reply_text("📍 <b>ክፍለ ከተማ ይምረጡ (Select Subcity):</b>", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
    return POST_SUBCITY

async def process_post_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_post"]["subcity"] = query.data.split(":", 1)[1]
    buttons = [[InlineKeyboardButton("🏠 የሚከራይ (For Rent)", callback_data="post_type:የሚከራይ")], [InlineKeyboardButton("🏷️ የሚሸጥ (For Sale)", callback_data="post_type:የሚሸጥ")]]
    await query.edit_message_text("🏷️ <b>የማስታወቂያ ዓይነት ይምረጡ (Select Category):</b>", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
    return POST_TYPE

async def process_post_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_post"]["listing_type"] = query.data.split(":", 1)[1]
    buttons = [[InlineKeyboardButton(r, callback_data=f"post_room:{r}")] for r in ROOM_TYPES]
    await query.edit_message_text("🚪 <b>የክፍል ብዛት ይምረጡ (Select Room Type):</b>", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
    return POST_ROOM

async def process_post_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_post"]["room"] = query.data.split(":", 1)[1]
    await query.edit_message_text("💰 <b>የቤቱን ዋጋ ያስገቡ (Enter Price in ETB/ብር):</b>\n<i>ምሳሌ: 8000 ወይም 10000</i>", parse_mode="HTML")
    return POST_PRICE

async def process_post_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clean_price = re.sub(r"[^\d]", "", update.message.text.strip())
    if not clean_price:
        await update.message.reply_text("❌ እባክዎ ቁጥር ብቻ ያስገቡ (Please enter numbers only):")
        return POST_PRICE
    context.user_data["admin_post"]["price"] = int(clean_price)
    await update.message.reply_text("📞 <b>የስልክ ቁጥር ያስገቡ (Enter Phone Number):</b>\n<i>ምሳሌ: 0911223344</i>", parse_mode="HTML")
    return POST_PHONE

async def process_post_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["admin_post"]["phone"] = update.message.text.strip()
    data = context.user_data["admin_post"]

    caption = (f"🏠 <b>{data['listing_type']} ቤት</b>\n\n📍 <b>ቦታ (Location):</b> {data['subcity']}\n🚪 <b>ክፍል (Room):</b> {data['room']}\n"
               f"💰 <b>ዋጋ (Price):</b> {data['price']} ብር / ETB\n📞 <b>ስልክ (Phone):</b> {data['phone']}\n\n💬 <b>ለበለጠ መረጃ (Contact):</b> @{SUPPORT_USERNAME}")
    contact_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💬 አድሚን ያናግሩ / Contact Admin", url=f"https://t.me/{SUPPORT_USERNAME}")]])

    try:
        msg = await context.bot.send_photo(chat_id=CHANNEL_ID, photo=data["photo"], caption=caption, parse_mode="HTML", reply_markup=contact_keyboard)
        save_listing(msg.message_id, data['subcity'], data['room'], data['price'], data['phone'], caption)
        await update.message.reply_text("✅ ማስታወቂያው በስኬት ተለጥፎ ዳታቤዝ ውስጥ ገብቷል!")
    except Exception as e:
        await update.message.reply_text(f"❌ Post failed.\nError: {e}")

    context.user_data.pop("admin_post", None)
    return ConversationHandler.END


# ---------- Interactive Broadcast Wizard ----------

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    await update.message.reply_text(
        "📢 <b>Broadcast Mode Started</b>\n\n"
        "You can now send the broadcast message. You can send text, a photo, or a video with a caption.\n\n"
        "<i>(Type /cancel to abort)</i>",
        parse_mode="HTML"
    )
    return BROADCAST_MSG

async def receive_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        users = conn.execute("SELECT user_id FROM users").fetchall()

    success_count = 0
    fail_count = 0
    
    await update.message.reply_text("⏳ Sending broadcast, please wait...")

    for user in users:
        try:
            await context.bot.copy_message(
                chat_id=user["user_id"],
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id
            )
            success_count += 1
        except Exception:
            fail_count += 1

    await update.message.reply_text(
        f"📢 <b>Broadcast Finished!</b>\n\n"
        f"✅ Sent to: {success_count}\n"
        f"❌ Failed: {fail_count}",
        parse_mode="HTML"
    )
    return ConversationHandler.END


async def cancel_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("admin_post", None)
    await update.message.reply_text("❌ Action cancelled.")
    return ConversationHandler.END


# ---------- User Handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    context.user_data.clear()

    joined = await is_user_joined(context.bot, user.id)
    if not joined:
        text = "ቦቱን ለመጠቀም እባክዎ አስቀድመው የቴሌግራም ቻናላችንን ይቀላቀሉ!\nPlease join our channel first to use this bot!"
        if update.message: await update.message.reply_text(text, reply_markup=get_force_join_keyboard())
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, reply_markup=get_force_join_keyboard())
        return

    text = "እባክዎ ቋንቋ ይምረጡ / Please choose your language:"
    if update.message: await update.message.reply_text(text, reply_markup=get_language_keyboard())
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=get_language_keyboard())


async def on_check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    joined = await is_user_joined(context.bot, update.effective_user.id)
    if joined:
        await query.answer("ተረጋግጧል! / Verified!")
        await query.edit_message_text("እባክዎ ቋንቋ ይምረጡ / Please choose your language:", reply_markup=get_language_keyboard())
    else:
        await query.answer("እባክዎ አስቀድመው ቻናሉን ይቀላቀሉ! / Please join the channel first!", show_alert=True)


async def on_language_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("lang:"): context.user_data["lang"] = query.data.split(":", 1)[1]
    lang = context.user_data.get("lang", "am")
    text = "እባክዎ ከታች ካሉት ይምረጡ:\nአከራይ ነዎት ወይስ ተከራይ?" if lang == "am" else "Are you a landlord or a tenant?"
    await query.edit_message_text(text, reply_markup=get_role_keyboard(lang))


async def on_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("role:"): context.user_data["role"] = query.data.split(":", 1)[1]
    role, lang = context.user_data.get("role", "tenant"), context.user_data.get("lang", "am")

    if role == "landlord":
        text = "የሚከራይ ወይም የሚሸጥ ቤት ለማስተዋወቅ አድሚን ያናግሩ።" if lang == "am" else "To advertise a house, please contact the admin."
        await query.edit_message_text(text, reply_markup=get_landlord_keyboard(lang))
    else:
        text = "የትኛው ክፍለ ከተማ ውስጥ ቤት ይፈልጋሉ?" if lang == "am" else "Which sub-city are you looking in?"
        await query.edit_message_text(text, reply_markup=get_subcity_keyboard(lang))


async def on_subcity_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("subcity:"):
        subcity = query.data.split(":", 1)[1]
        context.user_data["subcity"] = subcity
        update_user_search(update.effective_user.id, subcity=subcity)

    lang = context.user_data.get("lang", "am")
    text = "የገንዘብ መጠንዎን ይምረጡ:" if lang == "am" else "Select your budget range:"
    await query.edit_message_text(text, reply_markup=get_budget_keyboard(lang))


async def on_budget_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("budget:"):
        _, low, high = query.data.split(":")
        context.user_data["budget_low"] = int(low)
        context.user_data["budget_high"] = int(high) if high else None

    lang = context.user_data.get("lang", "am")
    text = "ባለ ስንት ክፍል ነው መከራየት የፈለጉት?" if lang == "am" else "How many rooms are you looking for?"
    await query.edit_message_text(text, reply_markup=get_room_keyboard(lang))


async def on_room_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    room = query.data.split(":", 1)[1]
    subcity = context.user_data.get("subcity")
    budget_low = context.user_data.get("budget_low")
    budget_high = context.user_data.get("budget_high")
    lang = context.user_data.get("lang", "am")
    
    update_user_search(update.effective_user.id, room=room)

    exact_results, related_results = search_listings(subcity, room, budget_low, budget_high)

    if not exact_results and not related_results:
        await query.edit_message_text("ይቅርታ፣ ተመሳሳይ ቤት አልተገኘም። No matching house found yet.", reply_markup=get_result_action_keyboard(lang))
        return

    header_text = f"🎯 <b>ትክክለኛ ፍለጋ ({len(exact_results)})</b>" if lang == "am" else f"🎯 <b>Exact Matches ({len(exact_results)})</b>"
    await query.edit_message_text(header_text, parse_mode="HTML")

    for r in exact_results[:5]:
        try: await context.bot.forward_message(chat_id=query.message.chat_id, from_chat_id=CHANNEL_ID or query.message.chat_id, message_id=r["message_id"])
        except Exception: await context.bot.send_message(chat_id=query.message.chat_id, text=r["raw_text"])

    if related_results:
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"\n💡 <b>ተዛማጅ ፍለጋዎች (የተለያየ ዋጋ) / Related Searches ({len(related_results[:3])}):</b>", parse_mode="HTML")
        for r in related_results[:3]:
            try: await context.bot.forward_message(chat_id=query.message.chat_id, from_chat_id=CHANNEL_ID or query.message.chat_id, message_id=r["message_id"])
            except Exception: await context.bot.send_message(chat_id=query.message.chat_id, text=r["raw_text"])

    comp_text = f"ለበለጠ መረጃ ያናግሩ: @{SUPPORT_USERNAME}\nወደ ዋናው ማውጫ ለመመለስ ይጫኑ:" if lang == "am" else f"Contact: @{SUPPORT_USERNAME}\nTap below to go back:"
    await context.bot.send_message(chat_id=query.message.chat_id, text=comp_text, reply_markup=get_result_action_keyboard(lang))


# ---------- Admin /stats & /delete ----------

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return

    with get_db() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_listings = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        
        recent_users = conn.execute(
            "SELECT username, first_name, last_subcity, last_room FROM users ORDER BY joined_at DESC LIMIT 30"
        ).fetchall()

    text_lines = [
        f"📊 <b>Bot Statistics</b>",
        f"🏠 <b>Total Active Listings:</b> {total_listings}",
        f"👥 <b>Total Registered Users:</b> {total_users}\n",
        f"<b>📋 Recent User Searches:</b>"
    ]

    for u in recent_users:
        name = u["username"]
        if name:
            display_name = f"@{name}"
        else:
            display_name = u["first_name"] or "Unknown User"
            
        loc = u["last_subcity"] or "No location yet"
        rm = u["last_room"] or "No room yet"
        
        text_lines.append(f"👤 {display_name} | 📍 {loc} | 🚪 {rm}")

    final_text = "\n".join(text_lines)
    await update.message.reply_text(final_text[:4000], parse_mode="HTML")


async def admin_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: `/delete <message_id>`")
        return
    msg_id = int(context.args[0])
    removed = delete_listing(msg_id)
    if removed: await update.message.reply_text(f"✅ Listing <b>{msg_id}</b> successfully removed from database.", parse_mode="HTML")
    else: await update.message.reply_text(f"❌ Listing <b>{msg_id}</b> not found in database.", parse_mode="HTML")


# ---------- Main Execution ----------

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    post_handler = ConversationHandler(
        entry_points=[CommandHandler("post", start_post_wizard)],
        states={
            POST_PHOTO: [MessageHandler(filters.PHOTO, process_post_photo)],
            POST_SUBCITY: [CallbackQueryHandler(process_post_subcity, pattern=r"^post_sc:")],
            POST_TYPE: [CallbackQueryHandler(process_post_type, pattern=r"^post_type:")],
            POST_ROOM: [CallbackQueryHandler(process_post_room, pattern=r"^post_room:")],
            POST_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_post_price)],
            POST_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_post_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel_wizard)],
    )
    
    broadcast_handler = ConversationHandler(
        entry_points=[CommandHandler("broadcast", start_broadcast)],
        states={
            BROADCAST_MSG: [MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO & ~filters.COMMAND, receive_broadcast)],
        },
        fallbacks=[CommandHandler("cancel", cancel_wizard)],
    )

    app.add_handler(post_handler)
    app.add_handler(broadcast_handler)

    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel_post))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("status", admin_stats))
    app.add_handler(CommandHandler("delete", admin_delete))

    app.add_handler(CallbackQueryHandler(start, pattern=r"^restart_search$"))
    app.add_handler(CallbackQueryHandler(start, pattern=r"^back_to_lang$"))
    app.add_handler(CallbackQueryHandler(on_check_join, pattern=r"^check_join$"))
    app.add_handler(CallbackQueryHandler(on_language_chosen, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(on_role_chosen, pattern=r"^role:"))
    app.add_handler(CallbackQueryHandler(on_language_chosen, pattern=r"^back_to_role$"))
    app.add_handler(CallbackQueryHandler(on_subcity_chosen, pattern=r"^subcity:"))
    app.add_handler(CallbackQueryHandler(on_role_chosen, pattern=r"^back_to_subcity$"))
    app.add_handler(CallbackQueryHandler(on_budget_chosen, pattern=r"^budget:"))
    app.add_handler(CallbackQueryHandler(on_subcity_chosen, pattern=r"^back_to_budget$"))
    app.add_handler(CallbackQueryHandler(on_room_chosen, pattern=r"^room:"))

    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
