"""
Hawassa Rental Telegram Bot — Fully Integrated Production Code
==============================================================
Features:
- Admin-Only Step-by-Step Interactive Post Creation (/post)
- Fix: Admin posts are now directly saved to the DB for Searching
- Fix: Markdown Parsing replaced with HTML to prevent crashes
- Photo Upload & Post Formatting with Contact Admin Button
- Bilingual Subcity Mapping (Amharic & English keywords)
- SQLite Database Indexing & Search with Subcity Fallback
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
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


def get_stats():
    with get_db() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_listings = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        return total_users, total_listings


def search_listings(subcity, room, budget_low, budget_high):
    with get_db() as conn:
        cursor = conn.cursor()
        # 1. Primary Query: Match Subcity & Room
        cursor.execute("""
            SELECT * FROM listings WHERE subcity = ? AND room = ?
        """, (subcity, room))
        rows = cursor.fetchall()

        # 2. Fallback: If no exact room match, retrieve all listings in subcity
        if not rows and subcity:
            cursor.execute("""
                SELECT * FROM listings WHERE subcity = ?
            """, (subcity,))
            rows = cursor.fetchall()

    exact = []
    related = []

    for row in rows:
        price = row["price"]
        if price is not None and budget_low is not None:
            in_range = True
            if price < budget_low:
                in_range = False
            if budget_high is not None and price > budget_high:
                in_range = False

            if in_range:
                exact.append(row)
            else:
                related.append(row)
        else:
            related.append(row)

    return exact, related


def parse_listing(text: str):
    text_lower = text.lower()

    # Subcity Parser
    subcity = None
    for keyword, canonical_name in SUBCITY_MAP.items():
        if keyword in text_lower:
            subcity = canonical_name
            break

    # Robust Room Parser
    room = None
    if any(k in text_lower for k in ["ባለ 1", "ባለ1", "1 ክፍል", "1 bedroom", "1bed"]):
        room = "ባለ 1"
    elif any(k in text_lower for k in ["ባለ 2", "ባለ2", "2 ክፍል", "2 bedroom", "2bed"]):
        room = "ባለ 2"
    elif any(k in text_lower for k in ["ባለ 3", "ባለ3", "3 ክፍል", "3 bedroom", "3bed"]):
        room = "ባለ 3"
    elif any(k in text_lower for k in ["ባለ 4", "ባለ4", "4 ክፍል", "4 bedroom", "4bed"]):
        room = "ባለ 4"
    elif "ሙሉ ግቢ" in text_lower or "full compound" in text_lower:
        room = "ሙሉ ግቢ"

    # Price Parser
    clean_text = text.replace(",", "")
    price_match = re.search(r"(\d{3,7})\s*(?:ብር|etb|birr)", clean_text, re.IGNORECASE)
    price = int(price_match.group(1)) if price_match else None

    # Phone Parser
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
    contact_label = "💬 አድሚን ያናግሩ (Contact Admin)" if lang == "am" else f"💬 Contact Admin (@{SUPPORT_USERNAME})"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(contact_label, url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(main_menu_label, callback_data="restart_search")]
    ])


def get_subcity_keyboard(lang="am"):
    buttons = [[InlineKeyboardButton(sc, callback_data=f"subcity:{sc}")] for sc in SUBCITIES]
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

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(contact_label, url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(main_menu_label, callback_data="restart_search")]
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
    logger.info(f"Listing Saved via Listener — Msg ID: {post.message_id}")


# ---------- Admin Post Creation Wizard ----------

(
    POST_PHOTO,
    POST_SUBCITY,
    POST_TYPE,
    POST_ROOM,
    POST_PRICE,
    POST_PHONE
) = range(6)


async def start_post_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Only admins can create posts.")
        return ConversationHandler.END

    context.user_data["admin_post"] = {}
    await update.message.reply_text(
        "📸 <b>ማስታወቂያ መፍጠሪያ (Post Creator)</b>\n\n"
        "እባክዎ የቤቱን ፎቶ ይላኩ (Please send the house photo):",
        parse_mode="HTML"
    )
    return POST_PHOTO


async def process_post_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = update.message.photo[-1].file_id
    context.user_data["admin_post"]["photo"] = photo_file_id

    buttons = [
        [InlineKeyboardButton(sc, callback_data=f"post_sc:{sc}")]
        for sc in SUBCITIES
    ]
    await update.message.reply_text(
        "📍 <b>ክፍለ ከተማ ይምረጡ (Select Subcity):</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )
    return POST_SUBCITY


async def process_post_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    subcity = query.data.split(":", 1)[1]
    context.user_data["admin_post"]["subcity"] = subcity

    buttons = [
        [InlineKeyboardButton("🏠 የሚከራይ (For Rent)", callback_data="post_type:የሚከራይ")],
        [InlineKeyboardButton("🏷️ የሚሸጥ (For Sale)", callback_data="post_type:የሚሸጥ")]
    ]
    await query.edit_message_text(
        "🏷️ <b>የማስታወቂያ ዓይነት ይምረጡ (Select Category):</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )
    return POST_TYPE


async def process_post_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    listing_type = query.data.split(":", 1)[1]
    context.user_data["admin_post"]["listing_type"] = listing_type

    buttons = [
        [InlineKeyboardButton(r, callback_data=f"post_room:{r}")]
        for r in ROOM_TYPES
    ]
    await query.edit_message_text(
        "🚪 <b>የክፍል ብዛት ይምረጡ (Select Room Type):</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )
    return POST_ROOM


async def process_post_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    room = query.data.split(":", 1)[1]
    context.user_data["admin_post"]["room"] = room

    await query.edit_message_text(
        "💰 <b>የቤቱን ዋጋ ያስገቡ (Enter Price in ETB/ብር):</b>\n"
        "<i>ምሳሌ: 8000 ወይም 10000</i>",
        parse_mode="HTML"
    )
    return POST_PRICE


async def process_post_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_text = update.message.text.strip()
    # Ensure they only typed numbers (removes commas and letters automatically)
    clean_price = re.sub(r"[^\d]", "", price_text)
    
    if not clean_price:
        await update.message.reply_text("❌ እባክዎ ቁጥር ብቻ ያስገቡ (Please enter numbers only):")
        return POST_PRICE

    context.user_data["admin_post"]["price"] = int(clean_price)

    await update.message.reply_text(
        "📞 <b>የስልክ ቁጥር ያስገቡ (Enter Phone Number):</b>\n"
        "<i>ምሳሌ: 0911223344</i>",
        parse_mode="HTML"
    )
    return POST_PHONE


async def process_post_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_text = update.message.text.strip()
    context.user_data["admin_post"]["phone"] = phone_text

    data = context.user_data["admin_post"]

    caption = (
        f"🏠 <b>{data['listing_type']} ቤት</b>\n\n"
        f"📍 <b>ቦታ (Location):</b> {data['subcity']}\n"
        f"🚪 <b>ክፍል (Room):</b> {data['room']}\n"
        f"💰 <b>ዋጋ (Price):</b> {data['price']} ብር / ETB\n"
        f"📞 <b>ስልክ (Phone):</b> {data['phone']}\n\n"
        f"💬 <b>ለበለጠ መረጃ (Contact):</b> @{SUPPORT_USERNAME}"
    )

    contact_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 አድሚን ያናግሩ / Contact Admin", url=f"https://t.me/{SUPPORT_USERNAME}")]
    ])

    try:
        # 1. Send the message to the channel
        msg = await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=data["photo"],
            caption=caption,
            parse_mode="HTML",
            reply_markup=contact_keyboard
        )
        
        # 2. CRITICAL FIX: Manually save this post to the database so it can be searched
        save_listing(
            message_id=msg.message_id,
            subcity=data['subcity'],
            room=data['room'],
            price=data['price'],
            phone=data['phone'],
            raw_text=caption
        )
        logger.info(f"Listing Saved via /post Command — Msg ID: {msg.message_id}")

        await update.message.reply_text("✅ ማስታወቂያው በስኬት ተለጥፎ ዳታቤዝ ውስጥ ገብቷል! (Post successfully published and added to search DB!)")
    except Exception as e:
        logger.error(f"Failed to post to channel: {e}")
        await update.message.reply_text(f"❌ Post failed. Make sure CHANNEL_ID is correct and bot is Admin.\nError: {e}")

    context.user_data.pop("admin_post", None)
    return ConversationHandler.END


async def cancel_post_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("admin_post", None)
    await update.message.reply_text("❌ Post creation cancelled.")
    return ConversationHandler.END


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
        lang = query.data.split(":", 1)[1]
        context.user_data["lang"] = lang

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
        role = query.data.split(":", 1)[1]
        context.user_data["role"] = role

    role = context.user_data.get("role", "tenant")
    lang = context.user_data.get("lang", "am")

    if role == "landlord":
        text = (
            "የሚከራይ ወይም የሚሸጥ ቤት ለማስተዋወቅ አድሚን ያናግሩ።"
            if lang == "am"
            else "To advertise a house for rent or sale, please contact the admin."
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
        subcity = query.data.split(":", 1)[1]
        context.user_data["subcity"] = subcity

    lang = context.user_data.get("lang", "am")
    text = (
        "የገንዘብ መጠንዎን ይምረጡ:"
        if lang == "am"
        else "Select your budget range:"
    )
    await query.edit_message_text(text, reply_markup=get_budget_keyboard(lang))


async def on_budget_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("budget:"):
        _, low, high = query.data.split(":")
        context.user_data["budget_low"] = int(low)
        context.user_data["budget_high"] = int(high) if high else None

    lang = context.user_data.get("lang", "am")
    text = (
        "ባለ ስንት ክፍል ነው መከራየት የፈለጉት?"
        if lang == "am"
        else "How many rooms are you looking for?"
    )
    await query.edit_message_text(text, reply_markup=get_room_keyboard(lang))


async def on_room_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    room = query.data.split(":", 1)[1]
    subcity = context.user_data.get("subcity")
    budget_low = context.user_data.get("budget_low")
    budget_high = context.user_data.get("budget_high")
    lang = context.user_data.get("lang", "am")

    exact_results, related_results = search_listings(subcity, room, budget_low, budget_high)

    if not exact_results and not related_results:
        no_match_text = (
            "ይቅርታ፣ ተመሳሳይ ቤት አልተገኘም። No matching house found yet."
        )
        await query.edit_message_text(
            no_match_text, reply_markup=get_result_action_keyboard(lang)
        )
        return

    header_text = (
        f"🎯 <b>ትክክለኛ ፍለጋ ({len(exact_results)})</b>"
        if lang == "am"
        else f"🎯 <b>Exact Matches ({len(exact_results)})</b>"
    )
    await query.edit_message_text(header_text, parse_mode="HTML")

    for r in exact_results[:5]:
        try:
            await context.bot.forward_message(
                chat_id=query.message.chat_id,
                from_chat_id=CHANNEL_ID or query.message.chat_id,
                message_id=r["message_id"]
            )
        except Exception:
            await context.bot.send_message(chat_id=query.message.chat_id, text=r["raw_text"])

    if related_results:
        related_header = (
            f"\n💡 <b>ተዛማጅ ፍለጋዎች (የተለያየ ዋጋ) / Related Searches ({len(related_results[:3])}):</b>"
        )
        await context.bot.send_message(chat_id=query.message.chat_id, text=related_header, parse_mode="HTML")

        for r in related_results[:3]:
            try:
                await context.bot.forward_message(
                    chat_id=query.message.chat_id,
                    from_chat_id=CHANNEL_ID or query.message.chat_id,
                    message_id=r["message_id"]
                )
            except Exception:
                await context.bot.send_message(chat_id=query.message.chat_id, text=r["raw_text"])

    completion_text = (
        f"ለበለጠ መረጃ ወይም ለትዕዛዝ ያናግሩ: @{SUPPORT_USERNAME}\nወደ ዋናው ማውጫ ለመመለስ ከታች ያለውን ቁልፍ ይጫኑ:"
        if lang == "am"
        else f"For more information contact: @{SUPPORT_USERNAME}\nTap below to go back to main menu:"
    )

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=completion_text,
        reply_markup=get_result_action_keyboard(lang)
    )


# ---------- Admin Handlers ----------

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    total_users, total_listings = get_stats()
    text = (
        f"📊 <b>Hawassa Rental Bot Statistics</b>\n\n"
        f"👥 <b>Total Registered Users:</b> {total_users}\n"
        f"🏠 <b>Total Active Listings:</b> {total_listings}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    broadcast_text = " ".join(context.args)
    if not broadcast_text:
        await update.message.reply_text("Usage: `/broadcast Your message here`")
        return

    with get_db() as conn:
        users = conn.execute("SELECT user_id FROM users").fetchall()

    success_count = 0
    fail_count = 0

    for user in users:
        try:
            await context.bot.send_message(chat_id=user["user_id"], text=broadcast_text)
            success_count += 1
        except Exception:
            fail_count += 1

    await update.message.reply_text(
        f"📢 Broadcast Finished!\n\n✅ Sent to: {success_count}\n❌ Failed: {fail_count}"
    )


async def admin_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: `/delete <message_id>`")
        return

    msg_id = int(context.args[0])
    removed = delete_listing(msg_id)

    if removed:
        await update.message.reply_text(f"✅ Listing <b>{msg_id}</b> successfully removed from database.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Listing <b>{msg_id}</b> not found in database.", parse_mode="HTML")


# ---------- Main Execution ----------

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Admin Interactive Post Creation Handler
    post_wizard_handler = ConversationHandler(
        entry_points=[CommandHandler("post", start_post_wizard)],
        states={
            POST_PHOTO: [MessageHandler(filters.PHOTO, process_post_photo)],
            POST_SUBCITY: [CallbackQueryHandler(process_post_subcity, pattern=r"^post_sc:")],
            POST_TYPE: [CallbackQueryHandler(process_post_type, pattern=r"^post_type:")],
            POST_ROOM: [CallbackQueryHandler(process_post_room, pattern=r"^post_room:")],
            POST_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_post_price)],
            POST_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_post_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel_post_wizard)],
    )

    app.add_handler(post_wizard_handler)

    # Channel Post Listener
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel_post))

    # User Commands
    app.add_handler(CommandHandler("start", start))

    # Admin Commands
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("delete", admin_delete))

    # Navigation Callbacks
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

    # Start Polling
    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
