import logging
import os
import re
import sqlite3
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, ConversationHandler
)

# ---------- Configuration & Setup ----------

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/Hawassa_Rental")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "Jatech_support")
DB_FILE = "/data/rental_bot.db"  # /data is a persistent Railway volume — survives redeploys

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
    "tabor": "Tabor", "ታቦር": "Tabor",
    "hawela": "Hawela-Tula", "ቱላ": "Hawela-Tula", "ሐዋላ": "Hawela-Tula",
    "addis ketema": "Addis Ketema", "አዲስ ከተማ": "Addis Ketema",
    "hayek dare": "Hayek Dare", "ኃይቅ ዳር": "Hayek Dare", "ሀይቅ ዳር": "Hayek Dare",
    "menehariya": "Menehariya", "መነሀሪያ": "Menehariya", "መነሃሪያ": "Menehariya",
    "misrak": "Misrak", "ምስራቅ": "Misrak",
    "bahile adarash": "Bahile Adarash", "ባህለ አዳራሽ": "Bahile Adarash", "ባህል አዳራሽ": "Bahile Adarash",
    "mehal ketema": "Mehal Ketema", "ማዕከል ከተማ": "Mehal Ketema", "መሀል ከተማ": "Mehal Ketema"
}

BUDGETS = [
    ("2000-5000 ብር / ETB", 2000, 5000),
    ("5000-10000 ብር / ETB", 5000, 10000),
    ("10000-15000 ብር / ETB", 10000, 15000),
    ("15000+ ብር / ETB", 15000, None),
]

ROOM_TYPES = ["ባለ 1", "ባለ 2", "ባለ 3", "ባለ 4", "ሙሉ ግቢ"]

PHONE_REGEX = re.compile(r"(?:\+251|0)9\d{8}")

# Conversation states for landlord self-submission
SUB_SUBCITY, SUB_ROOM, SUB_PRICE, SUB_PHONE, SUB_PHOTO = range(5)


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
                verified INTEGER DEFAULT 0,
                self_submitted INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                subcity TEXT,
                room TEXT,
                budget_low INTEGER,
                budget_high INTEGER,
                results_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                reporter_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def register_user(user):
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
        """, (user.id, user.username, user.first_name))
        conn.commit()


def save_listing(message_id, subcity, room, price, phone, raw_text, self_submitted=0):
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO listings (message_id, subcity, room, price, phone, raw_text, self_submitted)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (message_id, subcity, room, price, phone, raw_text, self_submitted))
        conn.commit()


def mark_verified(message_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE listings SET verified = 1 WHERE message_id = ?", (message_id,))
        conn.commit()
        return cursor.rowcount > 0


def delete_listing(message_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM listings WHERE message_id = ?", (message_id,))
        conn.commit()
        return cursor.rowcount > 0


def log_search(user_id, subcity, room, budget_low, budget_high, results_count):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO searches (user_id, subcity, room, budget_low, budget_high, results_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, subcity, room, budget_low, budget_high, results_count))
        conn.commit()


def save_report(message_id, reporter_id):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO reports (message_id, reporter_id) VALUES (?, ?)
        """, (message_id, reporter_id))
        conn.commit()


def get_stats():
    with get_db() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_listings = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        total_reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        searches_today = conn.execute(
            "SELECT COUNT(*) FROM searches WHERE date(created_at) = date('now')"
        ).fetchone()[0]
        return total_users, total_listings, total_reports, searches_today


def get_popular_searches(limit=10):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT subcity, room, COUNT(*) as cnt
            FROM searches
            GROUP BY subcity, room
            ORDER BY cnt DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return rows


def search_listings(subcity, room, budget_low, budget_high):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM listings WHERE subcity = ? AND room = ?
            ORDER BY verified DESC
        """, (subcity, room))
        rows = cursor.fetchall()

    exact = []
    related = []

    for row in rows:
        price = row["price"]
        if price is not None:
            in_range = True
            if price < budget_low:
                in_range = False
            if budget_high is not None and price > budget_high:
                in_range = False
            (exact if in_range else related).append(row)
        else:
            related.append(row)

    return exact, related


def parse_listing(text: str):
    text_lower = text.lower()

    subcity = None
    for keyword, canonical_name in SUBCITY_MAP.items():
        if keyword in text_lower:
            subcity = canonical_name
            break

    room = None
    text_no_spaces = text.replace(" ", "")
    for r in ROOM_TYPES:
        if r in text or r.replace(" ", "") in text_no_spaces:
            room = r
            break

    clean_text = text.replace(",", "")
    price_match = re.search(r"(\d{3,7})\s*(?:ብር|etb|birr)", clean_text, re.IGNORECASE)
    price = int(price_match.group(1)) if price_match else None

    phone_match = PHONE_REGEX.search(text)

    return {
        "subcity": subcity,
        "room": room,
        "price": price,
        "phone": phone_match.group(0) if phone_match else None,
    }


async def is_user_joined(bot, user_id: int) -> bool:
    if not CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        logger.error(f"Error checking channel membership: {e}")
        return True


# ---------- Inline Keyboards ----------

def get_force_join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 ቻናሉን ይቀላቀሉ (Join Channel)", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ አረጋግጥ (Verify Join)", callback_data="check_join")]
    ])


def get_language_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("አማርኛ 🇪🇹", callback_data="lang:am"),
            InlineKeyboardButton("English 🇬🇧", callback_data="lang:en"),
        ]
    ])


def get_role_keyboard(lang="am"):
    if lang == "am":
        buttons = [
            [InlineKeyboardButton("🏠 አከራይ / ሻጭ", callback_data="role:landlord")],
            [InlineKeyboardButton("🔍 ተከራይ", callback_data="role:tenant")],
            [InlineKeyboardButton("🌐 ቋንቋ ቀይር", callback_data="back_to_lang")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("🏠 Landlord / Seller", callback_data="role:landlord")],
            [InlineKeyboardButton("🔍 Tenant", callback_data="role:tenant")],
            [InlineKeyboardButton("🌐 Change Language", callback_data="back_to_lang")]
        ]
    return InlineKeyboardMarkup(buttons)


def get_landlord_keyboard(lang="am"):
    submit_label = "📝 ቤት ይመዝግቡ (Submit a listing)" if lang == "am" else "📝 Submit a listing"
    contact_label = "💬 አድሚን ያናግሩ (Contact Admin)" if lang == "am" else f"💬 Contact Admin (@{SUPPORT_USERNAME})"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(submit_label, callback_data="landlord_submit_start")],
        [InlineKeyboardButton(contact_label, url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(main_menu_label, callback_data="restart_search")]
    ])


def get_subcity_keyboard(lang="am", prefix="subcity"):
    buttons = [[InlineKeyboardButton(sc, callback_data=f"{prefix}:{sc}")] for sc in SUBCITIES]
    back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
    buttons.append([InlineKeyboardButton(back_label, callback_data="back_to_role")])
    return InlineKeyboardMarkup(buttons)


def get_budget_keyboard(lang="am"):
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"budget:{low}:{high or ''}")]
        for label, low, high in BUDGETS
    ]
    back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
    buttons.append([InlineKeyboardButton(back_label, callback_data="back_to_subcity")])
    buttons.append([InlineKeyboardButton(main_menu_label, callback_data="restart_search")])
    return InlineKeyboardMarkup(buttons)


def get_room_keyboard(lang="am", prefix="room"):
    buttons = [[InlineKeyboardButton(r, callback_data=f"{prefix}:{r}")] for r in ROOM_TYPES]
    if prefix == "room":
        back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
        main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
        buttons.append([InlineKeyboardButton(back_label, callback_data="back_to_budget")])
        buttons.append([InlineKeyboardButton(main_menu_label, callback_data="restart_search")])
    return InlineKeyboardMarkup(buttons)


def get_result_action_keyboard(lang="am"):
    contact_label = f"💬 ያናግሩ / Contact (@{SUPPORT_USERNAME})"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(contact_label, url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(main_menu_label, callback_data="restart_search")]
    ])


def get_report_keyboard(message_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚩 Report this listing", callback_data=f"report:{message_id}")]
    ])


# ---------- Channel Listener ----------

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post or update.edited_channel_post
    if not post or not (post.text or post.caption):
        return
    if CHANNEL_ID and post.chat.id != CHANNEL_ID:
        return

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
    logger.info(f"Listing saved — Msg ID: {post.message_id} | Subcity: {parsed['subcity']} | Room: {parsed['room']} | Price: {parsed['price']}")


# ---------- User Handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    context.user_data.clear()

    joined = await is_user_joined(context.bot, user.id)
    if not joined:
        text = (
            "ቦቱን ለመጠቀም እባክዎ አስቀድመው የቴሌግራም ቻናላችንን ይቀላቀሉ!\n\n"
            "Please join our channel first to use this bot!"
        )
        if update.message:
            await update.message.reply_text(text, reply_markup=get_force_join_keyboard())
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, reply_markup=get_force_join_keyboard())
        return

    text = "እባክዎ ቋንቋ ይምረጡ / Please choose your language:"
    if update.message:
        await update.message.reply_text(text, reply_markup=get_language_keyboard())
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=get_language_keyboard())
    return ConversationHandler.END


async def on_check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    joined = await is_user_joined(context.bot, user_id)
    if joined:
        await query.answer("ተረጋግጧል! አመሰግናለሁ። / Verified!")
        text = "እባክዎ ቋንቋ ይምረጡ / Please choose your language:"
        await query.edit_message_text(text, reply_markup=get_language_keyboard())
    else:
        await query.answer("እባክዎ አስቀድመው ቻናሉን ይቀላቀሉ! / Please join the channel first!", show_alert=True)


async def on_language_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("lang:"):
        context.user_data["lang"] = query.data.split(":", 1)[1]
    lang = context.user_data.get("lang", "am")
    text = (
        "እባክዎ ከታች ካሉት ይምረጡ:\nአከራይ ነዎት ወይስ ተከራይ?"
        if lang == "am"
        else "Please select your option:\nAre you a landlord or a tenant?"
    )
    await query.edit_message_text(text, reply_markup=get_role_keyboard(lang))


async def on_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("role:"):
        context.user_data["role"] = query.data.split(":", 1)[1]

    role = context.user_data.get("role", "tenant")
    lang = context.user_data.get("lang", "am")

    if role == "landlord":
        text = (
            "ቤትዎን በራስዎ ማስመዝገብ ወይም አድሚን ማናገር ይችላሉ።"
            if lang == "am"
            else "You can submit your listing yourself, or contact the admin."
        )
        await query.edit_message_text(text, reply_markup=get_landlord_keyboard(lang))
    else:
        text = (
            "የትኛው ክፍለ ከተማ ውስጥ ቤት ይፈልጋሉ?"
            if lang == "am"
            else "Which sub-city are you looking in?"
        )
        await query.edit_message_text(text, reply_markup=get_subcity_keyboard(lang))


async def on_subcity_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("subcity:"):
        context.user_data["subcity"] = query.data.split(":", 1)[1]
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
    user_id = update.effective_user.id

    exact_results, related_results = search_listings(subcity, room, budget_low, budget_high)
    log_search(user_id, subcity, room, budget_low, budget_high, len(exact_results))

    if not exact_results and not related_results:
        no_match_text = "ይቅርታ፣ ተመሳሳይ ቤት አልተገኘም። No matching house found yet."
        await query.edit_message_text(no_match_text, reply_markup=get_result_action_keyboard(lang))
        return

    header_text = (
        f"🎯 **ትክክለኛ ፍለጋ ({len(exact_results)})**"
        if lang == "am" else f"🎯 **Exact Matches ({len(exact_results)})**"
    )
    await query.edit_message_text(header_text, parse_mode="Markdown")

    async def send_result(r):
        verified_tag = "✅ Verified\n" if r["verified"] else ""
        if verified_tag:
            await context.bot.send_message(chat_id=query.message.chat_id, text=verified_tag)
        try:
            await context.bot.forward_message(
                chat_id=query.message.chat_id,
                from_chat_id=CHANNEL_ID or query.message.chat_id,
                message_id=r["message_id"]
            )
        except Exception:
            await context.bot.send_message(chat_id=query.message.chat_id, text=r["raw_text"])
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⬆️",
            reply_markup=get_report_keyboard(r["message_id"])
        )

    for r in exact_results[:5]:
        await send_result(r)

    if related_results:
        related_header = f"\n💡 **Related Searches ({len(related_results[:3])}):**"
        await context.bot.send_message(chat_id=query.message.chat_id, text=related_header, parse_mode="Markdown")
        for r in related_results[:3]:
            await send_result(r)

    completion_text = (
        f"ለበለጠ መረጃ ወይም ለትዕዛዝ ያናግሩ: @{SUPPORT_USERNAME}"
        if lang == "am" else f"For more information contact: @{SUPPORT_USERNAME}"
    )
    await context.bot.send_message(
        chat_id=query.message.chat_id, text=completion_text, reply_markup=get_result_action_keyboard(lang)
    )


async def on_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Reported — thank you.")
    message_id = int(query.data.split(":", 1)[1])
    reporter_id = update.effective_user.id
    save_report(message_id, reporter_id)

    if ADMIN_ID:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🚩 Listing {message_id} was reported by user {reporter_id}. Check it with /delete {message_id} if it's fake."
        )


# ---------- Landlord Self-Submission Flow ----------

async def landlord_submit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["submission"] = {}
    lang = context.user_data.get("lang", "am")
    text = "ቤትዎ የትኛው ክፍለ ከተማ ውስጥ ነው?" if lang == "am" else "Which sub-city is your house in?"
    await query.edit_message_text(text, reply_markup=get_subcity_keyboard(lang, prefix="lsubcity"))
    return SUB_SUBCITY


async def submit_subcity_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["submission"]["subcity"] = query.data.split(":", 1)[1]
    lang = context.user_data.get("lang", "am")
    text = "ባለ ስንት ክፍል ነው?" if lang == "am" else "How many rooms?"
    await query.edit_message_text(text, reply_markup=get_room_keyboard(lang, prefix="lroom"))
    return SUB_ROOM


async def submit_room_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["submission"]["room"] = query.data.split(":", 1)[1]
    lang = context.user_data.get("lang", "am")
    text = "ዋጋውን በቁጥር ብቻ ይላኩ (ለምሳሌ: 7000)" if lang == "am" else "Send the price as a number only (e.g. 7000)"
    await query.edit_message_text(text)
    return SUB_PRICE


async def submit_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "am")
    price_text = update.message.text.strip()
    if not price_text.isdigit():
        text = "እባክዎ ቁጥር ብቻ ይላኩ (ለምሳሌ: 7000)" if lang == "am" else "Please send digits only (e.g. 7000)"
        await update.message.reply_text(text)
        return SUB_PRICE
    context.user_data["submission"]["price"] = int(price_text)
    text = "የስልክ ቁጥርዎን ይላኩ (0912345678)" if lang == "am" else "Send your phone number (0912345678)"
    await update.message.reply_text(text)
    return SUB_PHONE


async def submit_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "am")
    phone_text = update.message.text.strip()
    if not PHONE_REGEX.match(phone_text):
        text = "ትክክለኛ ስልክ ቁጥር አልገባም። እንደገና ይሞክሩ።" if lang == "am" else "That doesn't look like a valid phone number. Try again."
        await update.message.reply_text(text)
        return SUB_PHONE
    context.user_data["submission"]["phone"] = phone_text
    text = (
        "የቤቱን ፎቶ ይላኩ (ወይም /skip ብለው ፎቶ ይዝለሉ)"
        if lang == "am" else "Send a photo of the house (or /skip to skip)"
    )
    await update.message.reply_text(text)
    return SUB_PHOTO


def _build_caption(sub, lang):
    subcity = sub["subcity"]
    room = sub["room"]
    price = sub["price"]
    phone = sub["phone"]
    return (
        f"🆕 ራሱ የተመዘገበ ቤት / Self-submitted listing\n\n"
        f"{subcity} Sub-City\n"
        f"{room} ክፍል ቤት\n"
        f"ዋጋ {price} ብር\n\n"
        f"ስልክ: {phone}"
    )


async def _finalize_submission(update: Update, context: ContextTypes.DEFAULT_TYPE, photo_file_id=None):
    sub = context.user_data["submission"]
    lang = context.user_data.get("lang", "am")
    caption = _build_caption(sub, lang)

    if not CHANNEL_ID:
        await update.message.reply_text("Channel not configured — contact admin.")
        return ConversationHandler.END

    if photo_file_id:
        sent = await context.bot.send_photo(chat_id=CHANNEL_ID, photo=photo_file_id, caption=caption)
    else:
        sent = await context.bot.send_message(chat_id=CHANNEL_ID, text=caption)

    save_listing(
        message_id=sent.message_id,
        subcity=sub["subcity"],
        room=sub["room"],
        price=sub["price"],
        phone=sub["phone"],
        raw_text=caption,
        self_submitted=1
    )

    confirm_text = (
        "ቤትዎ በተሳካ ሁኔታ ተለጥፏል! አድሚን በቅርቡ ያረጋግጣል።"
        if lang == "am" else "Your listing has been posted! An admin will verify it soon."
    )
    await update.message.reply_text(confirm_text, reply_markup=get_result_action_keyboard(lang))

    if ADMIN_ID:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🆕 New self-submitted listing (msg {sent.message_id}). Verify with /verify {sent.message_id}"
        )

    context.user_data.pop("submission", None)
    return ConversationHandler.END


async def submit_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = update.message.photo[-1].file_id
    return await _finalize_submission(update, context, photo_file_id=photo_file_id)


async def submit_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _finalize_submission(update, context, photo_file_id=None)


async def submit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "am")
    context.user_data.pop("submission", None)
    text = "ተሰርዟል።" if lang == "am" else "Cancelled."
    await update.message.reply_text(text)
    return ConversationHandler.END


# ---------- Admin Handlers ----------

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total_users, total_listings, total_reports, searches_today = get_stats()
    text = (
        f"📊 **Hawassa Rental Bot Statistics**\n\n"
        f"👥 **Total Registered Users:** {total_users}\n"
        f"🔍 **Searches Today:** {searches_today}\n"
        f"🏠 **Total Active Listings:** {total_listings}\n"
        f"🚩 **Total Reports:** {total_reports}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def admin_popular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    rows = get_popular_searches()
    if not rows:
        await update.message.reply_text("No searches logged yet.")
        return
    lines = ["📈 **Top searches:**\n"]
    for row in rows:
        lines.append(f"{row['subcity']} — {row['room']}: {row['cnt']} searches")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def admin_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: `/verify <message_id>`", parse_mode="Markdown")
        return
    msg_id = int(context.args[0])
    ok = mark_verified(msg_id)
    if ok:
        await update.message.reply_text(f"✅ Listing `{msg_id}` marked as verified.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Listing `{msg_id}` not found.", parse_mode="Markdown")


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    broadcast_text = " ".join(context.args)
    if not broadcast_text:
        await update.message.reply_text("Usage: `/broadcast Your message here`", parse_mode="Markdown")
        return
    with get_db() as conn:
        users = conn.execute("SELECT user_id FROM users").fetchall()
    success_count, fail_count = 0, 0
    for user in users:
        try:
            await context.bot.send_message(chat_id=user["user_id"], text=broadcast_text)
            success_count += 1
        except Exception:
            fail_count += 1
    await update.message.reply_text(f"📢 Broadcast Finished!\n\n✅ Sent to: {success_count}\n❌ Failed: {fail_count}")


async def admin_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: `/delete <message_id>`", parse_mode="Markdown")
        return
    msg_id = int(context.args[0])
    removed = delete_listing(msg_id)
    if removed:
        await update.message.reply_text(f"✅ Listing `{msg_id}` removed.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Listing `{msg_id}` not found.", parse_mode="Markdown")


# ---------- Main Execution ----------

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel_post))
    app.add_handler(CommandHandler("start", start))

    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("popular", admin_popular))
    app.add_handler(CommandHandler("verify", admin_verify))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("delete", admin_delete))

    submission_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(landlord_submit_start, pattern=r"^landlord_submit_start$")],
        states={
            SUB_SUBCITY: [CallbackQueryHandler(submit_subcity_chosen, pattern=r"^lsubcity:")],
            SUB_ROOM: [CallbackQueryHandler(submit_room_chosen, pattern=r"^lroom:")],
            SUB_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_price_received)],
            SUB_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_phone_received)],
            SUB_PHOTO: [
                MessageHandler(filters.PHOTO, submit_photo_received),
                CommandHandler("skip", submit_skip_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", submit_cancel)],
    )
    app.add_handler(submission_conv)

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
    app.add_handler(CallbackQueryHandler(on_report, pattern=r"^report:"))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
