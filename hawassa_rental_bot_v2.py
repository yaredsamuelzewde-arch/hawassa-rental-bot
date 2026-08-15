"""
Hawassa Rental & Marketplace Telegram Bot — Fully Integrated Production Code (Railway Persistent Edition)
========================================================================================================
Features:
- Railway Persistent Volume + DB_PATH Environment Variable (Zero data loss on restart or redeploy)
- Multi-Category Support with Bilingual Admin Post Creator: Home (ቤት), Phone (ስልክ), and Laptop (ላፕቶപ്പ്)
- Custom Brand/Specification Filters & Budgets for Electronics (Up to 100,000+ ETB)
- Forward-to-Import: Forward old channel posts to the bot to add them instantly!
- Interactive Broadcast with Bilingual Button Menu (Contact Admin & Main Menu) (/stats, /broadcast)
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

# Bulletproof Database Path Configuration for Railway Persistence
DB_FILE = os.getenv("DB_PATH", "/data/rental_bot.db")
if not os.path.exists("/data") and not os.path.isabs(DB_FILE):
    DB_FILE = "rental_bot.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Categories & Filter Options
SUBCITIES = [
    "Tabor", "Hawela-Tula", "Addis Ketema", "Hayek Dare",
    "Menehariya", "Misrak", "Bahile Adarash", "Mehal Ketema",
]

PHONE_BRANDS = ["iPhone", "Samsung", "Tecno / Infinix", "Xiaomi", "Other Phone"]
LAPTOP_BRANDS = ["HP", "Dell", "Lenovo", "MacBook / Apple", "ASUS", "Other Laptop"]

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

PHONE_BUDGETS = [
    ("5000 - 10000 ብር / ETB", 5000, 10000),
    ("10000 - 20000 ብር / ETB", 10000, 20000),
    ("20000 - 30000 ብር / ETB", 20000, 30000),
    ("30000 - 50000 ብር / ETB", 30000, 50000),
    ("50000 - 100000 ብር / ETB", 50000, 100000),
    ("100000+ ብር / ETB", 100000, None),
]

LAPTOP_BUDGETS = [
    ("10000 - 20000 ብር / ETB", 10000, 20000),
    ("20000 - 30000 ብር / ETB", 20000, 30000),
    ("30000 - 50000 ብር / ETB", 30000, 50000),
    ("50000 - 100000 ብር / ETB", 50000, 100000),
    ("100000+ ብር / ETB", 100000, None),
]

HOME_BUDGETS = [
    ("2000 - 5000 ብር / ETB", 2000, 5000),
    ("5000 - 10000 ብር / ETB", 5000, 10000),
    ("10000 - 15000 ብር / ETB", 10000, 15000),
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
                category TEXT DEFAULT 'Home',
                item_type TEXT,
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
                last_category TEXT,
                last_item_type TEXT,
                last_room TEXT
            )
        """)
        for col, col_type in [("category", "TEXT DEFAULT 'Home'"), ("item_type", "TEXT"), 
                              ("last_category", "TEXT"), ("last_item_type", "TEXT"), ("last_room", "TEXT")]:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            except Exception:
                pass
        try:
            cursor.execute("ALTER TABLE listings ADD COLUMN category TEXT DEFAULT 'Home'")
            cursor.execute("ALTER TABLE listings ADD COLUMN item_type TEXT")
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


def update_user_search(user_id, category=None, item_type=None, room=None):
    with get_db() as conn:
        if category:
            conn.execute("UPDATE users SET last_category = ? WHERE user_id = ?", (category, user_id))
        if item_type:
            conn.execute("UPDATE users SET last_item_type = ? WHERE user_id = ?", (item_type, user_id))
        if room:
            conn.execute("UPDATE users SET last_room = ? WHERE user_id = ?", (room, user_id))
        conn.commit()


def save_listing(message_id, category, item_type, room, price, phone, raw_text):
    if not message_id:
        return
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO listings (message_id, category, item_type, room, price, phone, raw_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (message_id, category, item_type, room, price, phone, raw_text))
        conn.commit()


def delete_listing(message_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM listings WHERE message_id = ?", (message_id,))
        conn.commit()
        return cursor.rowcount > 0


def parse_listing_text(text):
    text_lower = text.lower()
    
    category = "Home"
    if any(k in text_lower for k in ["iphone", "samsung", "tecno", "infinix", "xiaomi", "ስልክ", "phone", "mobile"]):
        category = "Phone"
    elif any(k in text_lower for k in ["hp", "dell", "lenovo", "macbook", "asus", "laptop", "core i", "ላፕቶപ്പ്"]):
        category = "Laptop"

    item_type = "Tabor"
    room = "ባለ 1"

    if category == "Home":
        for key, val in SUBCITY_MAP.items():
            if key in text_lower:
                item_type = val
                break
        for r in ROOM_TYPES:
            if r in text:
                room = r
                break
    elif category == "Phone":
        item_type = "Other Phone"
        for brand in PHONE_BRANDS:
            if brand.lower().split("/")[0].strip() in text_lower:
                item_type = brand
                break
    elif category == "Laptop":
        item_type = "Other Laptop"
        for brand in LAPTOP_BRANDS:
            if brand.lower().split("/")[0].strip() in text_lower:
                item_type = brand
                break

    price = None
    price_match = re.findall(r'\b\d{3,6}\b', text)
    if price_match:
        price = int(price_match[0])
        
    phone_match = PHONE_REGEX.search(text)
    phone = phone_match.group(0) if phone_match else ""
    
    return category, item_type, room, price, phone


def search_listings(category, item_type, room, budget_low, budget_high):
    with get_db() as conn:
        cursor = conn.cursor()
        if category == "Home":
            cursor.execute("SELECT * FROM listings WHERE category = ? AND item_type = ? AND room = ?", (category, item_type, room))
            rows = cursor.fetchall()
            if not rows and item_type:
                cursor.execute("SELECT * FROM listings WHERE category = ? AND item_type = ?", (category, item_type))
                rows = cursor.fetchall()
        else:
            cursor.execute("SELECT * FROM listings WHERE category = ? AND item_type = ?", (category, item_type))
            rows = cursor.fetchall()
            if not rows:
                cursor.execute("SELECT * FROM listings WHERE category = ?", (category,))
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
        buttons = [
            [InlineKeyboardButton("🏠 ማስታወቂያ ማውጣት (Post / Advertise)", callback_data="role:landlord")],
            [InlineKeyboardButton("🔍 ቤት ወይም ዕቃ መፈለግ (Search)", callback_data="role:tenant")],
            [InlineKeyboardButton("🌐 ቋንቋ ቀይር (Change Language)", callback_data="back_to_lang")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("🏠 Post / Advertise Property", callback_data="role:landlord")],
            [InlineKeyboardButton("🔍 Search / Find Property", callback_data="role:tenant")],
            [InlineKeyboardButton("🌐 Change Language", callback_data="back_to_lang")]
        ]
    return InlineKeyboardMarkup(buttons)

def get_category_keyboard(lang="am"):
    if lang == "am":
        buttons = [
            [InlineKeyboardButton("🏠 ቤት (Home / Residential)", callback_data="cat:Home")],
            [InlineKeyboardButton("📱 ስልክ (Phones)", callback_data="cat:Phone")],
            [InlineKeyboardButton("💻 ላፕቶപ്പ് (Laptops)", callback_data="cat:Laptop")],
            [InlineKeyboardButton("⬅️ ተመለስ (Back)", callback_data="back_to_role")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("🏠 Home (Residential)", callback_data="cat:Home")],
            [InlineKeyboardButton("📱 Phone", callback_data="cat:Phone")],
            [InlineKeyboardButton("💻 Laptop", callback_data="cat:Laptop")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_role")]
        ]
    return InlineKeyboardMarkup(buttons)

def get_landlord_keyboard(lang="am"):
    contact_label = "💬 አድሚን ያናግሩ (Contact Admin)" if lang == "am" else f"💬 Contact Admin (@{SUPPORT_USERNAME})"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
    return InlineKeyboardMarkup([[InlineKeyboardButton(contact_label, url=f"https://t.me/{SUPPORT_USERNAME}")], [InlineKeyboardButton(main_menu_label, callback_data="restart_search")]])

def get_subcity_keyboard(lang="am"):
    buttons = [[InlineKeyboardButton(sc, callback_data=f"subcity:{sc}")] for sc in SUBCITIES]
    back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
    buttons.append([InlineKeyboardButton(back_label, callback_data="back_to_category")])
    return InlineKeyboardMarkup(buttons)

def get_phone_brand_keyboard(lang="am"):
    buttons = [[InlineKeyboardButton(brand, callback_data=f"phone_brand:{brand}")] for brand in PHONE_BRANDS]
    back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
    buttons.append([InlineKeyboardButton(back_label, callback_data="back_to_category")])
    return InlineKeyboardMarkup(buttons)

def get_laptop_brand_keyboard(lang="am"):
    buttons = [[InlineKeyboardButton(brand, callback_data=f"laptop_brand:{brand}")] for brand in LAPTOP_BRANDS]
    back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
    buttons.append([InlineKeyboardButton(back_label, callback_data="back_to_category")])
    return InlineKeyboardMarkup(buttons)

def get_budget_keyboard(category, lang="am"):
    if category == "Phone":
        budgets = PHONE_BUDGETS
        back_target = "back_to_phone_brand"
    elif category == "Laptop":
        budgets = LAPTOP_BUDGETS
        back_target = "back_to_laptop_brand"
    else:
        budgets = HOME_BUDGETS
        back_target = "back_to_subcity"

    buttons = [[InlineKeyboardButton(label, callback_data=f"budget:{low}:{high or ''}")] for label, low, high in budgets]
    back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
    buttons.append([InlineKeyboardButton(back_label, callback_data=back_target)])
    buttons.append([InlineKeyboardButton(main_menu_label, callback_data="restart_search")])
    return InlineKeyboardMarkup(buttons)

def get_room_keyboard(lang="am"):
    buttons = [[InlineKeyboardButton(r, callback_data=f"room:{r}")] for r in ROOM_TYPES]
    back_label = "⬅️ ተመለስ (Back)" if lang == "am" else "⬅️ Back"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
    buttons.append([InlineKeyboardButton(back_label, callback_data="back_to_subcity")])
    buttons.append([InlineKeyboardButton(main_menu_label, callback_data="restart_search")])
    return InlineKeyboardMarkup(buttons)

def get_result_action_keyboard(lang="am"):
    contact_label = f"💬 ያናግሩ / Contact (@{SUPPORT_USERNAME})"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"
    return InlineKeyboardMarkup([[InlineKeyboardButton(contact_label, url=f"https://t.me/{SUPPORT_USERNAME}")], [InlineKeyboardButton(main_menu_label, callback_data="restart_search")]])

def get_broadcast_action_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 አድሚን ያናግሩ / Contact Admin", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton("🏠 ዋና ማውጫ / Main Menu", callback_data="restart_search")]
    ])


# ---------- Channel Listener & Forward Import ----------

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post or update.edited_channel_post
    if not post or not (post.text or post.caption): return
    if CHANNEL_ID and post.chat.id != CHANNEL_ID: return

    post_text = post.text or post.caption
    category, item_type, room, price, phone = parse_listing_text(post_text)

    save_listing(
        message_id=post.message_id,
        category=category,
        item_type=item_type,
        room=room,
        price=price,
        phone=phone,
        raw_text=post_text
    )


async def handle_forwarded_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = update.message
    if not msg or not (msg.text or msg.caption): return

    text = msg.text or msg.caption
    category, item_type, room, price, phone = parse_listing_text(text)

    save_listing(msg.message_id, category, item_type, room, price, phone, text)
    await msg.reply_text(
        f"✅ <b>Post Imported Successfully!</b>\n\n"
        f"📦 <b>Category:</b> {category}\n"
        f"🏷️ <b>Item/Location:</b> {item_type}\n"
        f"🚪 <b>Room:</b> {room if category == 'Home' else 'N/A'}\n"
        f"💰 <b>Price:</b> {price} ETB\n"
        f"📞 <b>Phone:</b> {phone}",
        parse_mode="HTML"
    )


# ---------- States for Conversations ----------
(
    POST_PHOTO, POST_CATEGORY, POST_ITEM_TYPE, POST_ROOM, POST_PRICE, POST_PHONE,
    BROADCAST_MSG, POST_CUSTOM_NAME
) = range(8)


# ---------- Admin Post Creation Wizard (Bilingual Amharic & English) ----------

async def start_post_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    context.user_data["admin_post"] = {}
    await update.message.reply_text(
        "📸 <b>ማስታወቂያ መፍጠሪያ / Post Creator</b>\n\n"
        "እባክዎ የቤቱን ወይም የዕቃውን ፎቶ ይላኩ (Please send photo):",
        parse_mode="HTML"
    )
    return POST_PHOTO

async def process_post_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["admin_post"]["photo"] = update.message.photo[-1].file_id
    buttons = [
        [InlineKeyboardButton("🏠 ቤት (House / Residential)", callback_data="post_cat:Home")],
        [InlineKeyboardButton("📱 ስልክ (Phone)", callback_data="post_cat:Phone")],
        [InlineKeyboardButton("💻 ላፕቶപ്പ് (Laptop)", callback_data="post_cat:Laptop")]
    ]
    await update.message.reply_text(
        "📦 <b>ምድብ ይምረጡ / Select Category:</b>\n\n"
        "እባክዎ የሚለጥፉትን ምድብ ይምረጡ (Choose category to post):",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )
    return POST_CATEGORY

async def process_post_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split(":", 1)[1]
    context.user_data["admin_post"]["category"] = category

    if category == "Home":
        buttons = [[InlineKeyboardButton(sc, callback_data=f"post_item:{sc}")] for sc in SUBCITIES]
        await query.edit_message_text(
            "📍 <b>ክፍለ ከተማ ይምረጡ / Select Subcity (House):</b>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )
        return POST_ITEM_TYPE
    elif category == "Phone":
        buttons = [[InlineKeyboardButton(b, callback_data=f"post_item:{b}")] for b in PHONE_BRANDS]
        # Added the custom button here!
        buttons.append([InlineKeyboardButton("➕ አዲስ ጨምር (Add New)", callback_data="post_item:ADD_CUSTOM")])
        await query.edit_message_text(
            "📱 <b>የስልክ ብራንድ ይምረጡ / Select Phone Brand:</b>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )
        return POST_ITEM_TYPE
    else:
        buttons = [[InlineKeyboardButton(b, callback_data=f"post_item:{b}")] for b in LAPTOP_BRANDS]
        # Added the custom button here!
        buttons.append([InlineKeyboardButton("➕ አዲስ ጨምር (Add New)", callback_data="post_item:ADD_CUSTOM")])
        await query.edit_message_text(
            "💻 <b>የላፕቶፕ ብራንድ ይምረጡ / Select Laptop Brand:</b>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )
        return POST_ITEM_TYPE

async def process_post_item_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_type = query.data.split(":", 1)[1]
    category = context.user_data["admin_post"]["category"]

    # Intercept custom add
    if item_type == "ADD_CUSTOM":
        await query.edit_message_text(
            "✍️ <b>እባክዎ አዲሱን ስም/ብራንድ ያስገቡ (Please type the new name):</b>",
            parse_mode="HTML"
        )
        return POST_CUSTOM_NAME

    context.user_data["admin_post"]["item_type"] = item_type

    if category == "Home":
        buttons = [[InlineKeyboardButton(r, callback_data=f"post_room:{r}")] for r in ROOM_TYPES]
        await query.edit_message_text(
            "🚪 <b>የክፍል ብዛት ይምረጡ / Select Room Type:</b>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )
        return POST_ROOM
    else:
        context.user_data["admin_post"]["room"] = "N/A"
        await query.edit_message_text(
            "💰 <b>ዋጋ ያስገቡ (በብር / ETB):\n<i>ምሳሌ: 25000 (Enter price in numbers):</i></b>",
            parse_mode="HTML"
        )
        return POST_PRICE

async def process_custom_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    custom_name = update.message.text.strip()
    category = context.user_data["admin_post"]["category"]
    
    # Save it to the current admin post data
    context.user_data["admin_post"]["item_type"] = custom_name
    
    # Add it to the global list so everyone can see it dynamically
    if category == "Phone" and custom_name not in PHONE_BRANDS:
        if "Other Phone" in PHONE_BRANDS:
            PHONE_BRANDS.insert(PHONE_BRANDS.index("Other Phone"), custom_name)
        else:
            PHONE_BRANDS.append(custom_name)
            
    elif category == "Laptop" and custom_name not in LAPTOP_BRANDS:
        if "Other Laptop" in LAPTOP_BRANDS:
            LAPTOP_BRANDS.insert(LAPTOP_BRANDS.index("Other Laptop"), custom_name)
        else:
            LAPTOP_BRANDS.append(custom_name)

    context.user_data["admin_post"]["room"] = "N/A"
    await update.message.reply_text(
        "💰 <b>ዋጋ ያስገቡ (በብር / ETB):\n<i>ምሳሌ: 25000 (Enter price in numbers):</i></b>",
        parse_mode="HTML"
    )
    return POST_PRICE


async def process_post_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_post"]["room"] = query.data.split(":", 1)[1]
    await query.edit_message_text(
        "💰 <b>የቤቱን ዋጋ ያስገቡ (በብር / ETB):\n<i>ምሳሌ: 8000 (Enter price):</i></b>",
        parse_mode="HTML"
    )
    return POST_PRICE

async def process_post_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clean_price = re.sub(r"[^\d]", "", update.message.text.strip())
    if not clean_price:
        await update.message.reply_text("❌ እባክዎ ቁጥር ብቻ ያስገቡ / Please enter numbers only:")
        return POST_PRICE
    context.user_data["admin_post"]["price"] = int(clean_price)
    await update.message.reply_text(
        "📞 <b>የስልክ ቁጥር ያስገቡ / Enter Phone Number:</b>\n<i>ምሳሌ: 0911223344</i>",
        parse_mode="HTML"
    )
    return POST_PHONE

async def process_post_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["admin_post"]["phone"] = update.message.text.strip()
    data = context.user_data["admin_post"]

    room_line = f"🚪 <b>ክፍል (Room):</b> {data['room']}\n" if data['category'] == "Home" else ""
    caption = (
        f"🔥 <b>{data['category']} ማስታወቂያ</b>\n\n"
        f"🏷️ <b>ብራንድ/ቦታ (Brand/Location):</b> {data['item_type']}\n"
        f"{room_line}"
        f"💰 <b>ዋጋ (Price):</b> {data['price']} ብር / ETB\n"
        f"📞 <b>ስልክ (Phone):</b> {data['phone']}\n\n"
        f"💬 <b>ለበለጠ መረጃ (Contact):</b> @{SUPPORT_USERNAME}"
    )
    contact_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💬 አድሚን ያናግሩ / Contact Admin", url=f"https://t.me/{SUPPORT_USERNAME}")]])

    try:
        msg = await context.bot.send_photo(chat_id=CHANNEL_ID, photo=data["photo"], caption=caption, parse_mode="HTML", reply_markup=contact_keyboard)
        save_listing(msg.message_id, data['category'], data['item_type'], data['room'], data['price'], data['phone'], caption)
        await update.message.reply_text("✅ ማስታወቂያው በስኬት ተለጥፎ ዳታቤዝ ውስጥ ገብቷል!\n(Post successfully published & saved!)")
    except Exception as e:
        await update.message.reply_text(f"❌ Post failed.\nError: {e}")

    context.user_data.pop("admin_post", None)
    return ConversationHandler.END


# ---------- Interactive Broadcast Wizard ----------

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    await update.message.reply_text(
        "📢 <b>Broadcast Mode Started</b>\n\n"
        "Send your message, photo, or video. The bilingual button menu will be attached automatically.\n\n"
        "<i>(Type /cancel to abort)</i>",
        parse_mode="HTML"
    )
    return BROADCAST_MSG

async def receive_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        users = conn.execute("SELECT user_id FROM users").fetchall()

    success_count = 0
    fail_count = 0
    
    await update.message.reply_text("⏳ Sending broadcast with buttons, please wait...")

    for user in users:
        try:
            await context.bot.copy_message(
                chat_id=user["user_id"],
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id,
                reply_markup=get_broadcast_action_keyboard()
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
    text = "እባክዎ ከታች ካሉት ይምረጡ:\nማስታወቂያ ማውጣት ይፈልጋሉ ወይስ ቤት/ዕቃ መፈለግ?" if lang == "am" else "What would you like to do?"
    await query.edit_message_text(text, reply_markup=get_role_keyboard(lang))


async def on_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("role:"): context.user_data["role"] = query.data.split(":", 1)[1]
    role, lang = context.user_data.get("role", "tenant"), context.user_data.get("lang", "am")

    if role == "landlord":
        text = "ቤት ወይም ዕቃ ለማስተዋወቅ እባክዎ አድሚንን ያናግሩ።" if lang == "am" else "To advertise an item or property, please contact the admin."
        await query.edit_message_text(text, reply_markup=get_landlord_keyboard(lang))
    else:
        text = "ምን ዓይነት አገልግሎት ይፈልጋሉ? (እባክዎ ምድብ ይምረጡ)" if lang == "am" else "What are you looking for? (Please choose category)"
        await query.edit_message_text(text, reply_markup=get_category_keyboard(lang))


async def on_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("cat:"):
        category = query.data.split(":", 1)[1]
        context.user_data["category"] = category
        update_user_search(update.effective_user.id, category=category)

    category = context.user_data.get("category", "Home")
    lang = context.user_data.get("lang", "am")

    if category == "Home":
        text = "የትኛው ክፍለ ከተማ ውስጥ ቤት ይፈልጋሉ?" if lang == "am" else "Which sub-city are you looking in?"
        await query.edit_message_text(text, reply_markup=get_subcity_keyboard(lang))
    elif category == "Phone":
        text = "የትኛውን የስልክ ብራንድ ይፈልጋሉ?" if lang == "am" else "Which phone brand are you looking for?"
        await query.edit_message_text(text, reply_markup=get_phone_brand_keyboard(lang))
    else:
        text = "የትኛውን የላፕቶፕ ብራንድ ይፈልጋሉ?" if lang == "am" else "Which laptop brand are you looking for?"
        await query.edit_message_text(text, reply_markup=get_laptop_brand_keyboard(lang))


async def on_subcity_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("subcity:"):
        subcity = query.data.split(":", 1)[1]
        context.user_data["item_type"] = subcity
        update_user_search(update.effective_user.id, item_type=subcity)

    lang = context.user_data.get("lang", "am")
    text = "የገንዘብ መጠንዎን ይምረጡ:" if lang == "am" else "Select your budget range:"
    await query.edit_message_text(text, reply_markup=get_budget_keyboard("Home", lang))


async def on_phone_brand_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("phone_brand:"):
        brand = query.data.split(":", 1)[1]
        context.user_data["item_type"] = brand
        update_user_search(update.effective_user.id, item_type=brand)

    lang = context.user_data.get("lang", "am")
    text = "የስልክ ዋጋ መጠን ይምረጡ:" if lang == "am" else "Select phone budget range:"
    await query.edit_message_text(text, reply_markup=get_budget_keyboard("Phone", lang))


async def on_laptop_brand_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("laptop_brand:"):
        brand = query.data.split(":", 1)[1]
        context.user_data["item_type"] = brand
        update_user_search(update.effective_user.id, item_type=brand)

    lang = context.user_data.get("lang", "am")
    text = "የላፕቶፕ ዋጋ መጠን ይምረጡ:" if lang == "am" else "Select laptop budget range:"
    await query.edit_message_text(text, reply_markup=get_budget_keyboard("Laptop", lang))


async def on_budget_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("budget:"):
        _, low, high = query.data.split(":")
        context.user_data["budget_low"] = int(low)
        context.user_data["budget_high"] = int(high) if high else None

    category = context.user_data.get("category", "Home")
    lang = context.user_data.get("lang", "am")

    if category == "Home":
        text = "ባለ ስንት ክፍል ነው መከራየት የፈለጉት?" if lang == "am" else "How many rooms are you looking for?"
        await query.edit_message_text(text, reply_markup=get_room_keyboard(lang))
    else:
        await execute_search(query, context)


async def on_room_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    room = query.data.split(":", 1)[1]
    context.user_data["room"] = room
    update_user_search(update.effective_user.id, room=room)
    await execute_search(query, context)


async def execute_search(query, context):
    category = context.user_data.get("category", "Home")
    item_type = context.user_data.get("item_type")
    room = context.user_data.get("room", "ባለ 1")
    budget_low = context.user_data.get("budget_low")
    budget_high = context.user_data.get("budget_high")
    lang = context.user_data.get("lang", "am")

    exact_results, related_results = search_listings(category, item_type, room, budget_low, budget_high)

    if not exact_results and not related_results:
        await query.edit_message_text("ይቅርታ፣ ተዛማጅ ዕቃ/ቤት አልተገኘም። No matching items found yet.", reply_markup=get_result_action_keyboard(lang))
        return

    header_text = f"🎯 <b>ትክክለኛ ፍለጋ ({len(exact_results)})</b>" if lang == "am" else f"🎯 <b>Exact Matches ({len(exact_results)})</b>"
    await query.edit_message_text(header_text, parse_mode="HTML")

    for r in exact_results[:5]:
        try: await context.bot.forward_message(chat_id=query.message.chat_id, from_chat_id=CHANNEL_ID or query.message.chat_id, message_id=r["message_id"])
        except Exception: await context.bot.send_message(chat_id=query.message.chat_id, text=r["raw_text"])

    if related_results:
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"\n💡 <b>ተዛማጅ ፍለጋዎች / Related Searches ({len(related_results[:3])}):</b>", parse_mode="HTML")
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
            "SELECT username, first_name, last_category, last_item_type, last_room FROM users ORDER BY joined_at DESC LIMIT 30"
        ).fetchall()

    text_lines = [
        f"📊 <b>Bot Statistics</b>",
        f"🏠 <b>Total Active Listings:</b> {total_listings}",
        f"👥 <b>Total Registered Users:</b> {total_users}\n",
        f"<b>📋 Recent User Searches:</b>"
    ]

    for u in recent_users:
        name = u["username"]
        display_name = f"@{name}" if name else (u["first_name"] or "Unknown User")
        cat = u["last_category"] or "Home"
        item = u["last_item_type"] or "N/A"
        rm = f" | 🚪 {u['last_room']}" if cat == "Home" and u['last_room'] else ""
        
        text_lines.append(f"👤 {display_name} | 📦 {cat} ({item}{rm})")

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
            POST_CATEGORY: [CallbackQueryHandler(process_post_category, pattern=r"^post_cat:")],
            POST_ITEM_TYPE: [CallbackQueryHandler(process_post_item_type, pattern=r"^post_item:")],
            
            # The newly added state handler for Custom Name entry
            POST_CUSTOM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_custom_name)],
            
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
    app.add_handler(MessageHandler(filters.FORWARDED & filters.TEXT & filters.ChatType.PRIVATE, handle_forwarded_import))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("status", admin_stats))
    app.add_handler(CommandHandler("delete", admin_delete))

    app.add_handler(CallbackQueryHandler(start, pattern=r"^restart_search$"))
    app.add_handler(CallbackQueryHandler(start, pattern=r"^back_to_lang$"))
    app.add_handler(CallbackQueryHandler(on_role_chosen, pattern=r"^back_to_role$"))
    app.add_handler(CallbackQueryHandler(on_category_chosen, pattern=r"^back_to_category$"))
    app.add_handler(CallbackQueryHandler(on_subcity_chosen, pattern=r"^back_to_subcity$"))
    app.add_handler(CallbackQueryHandler(on_phone_brand_chosen, pattern=r"^back_to_phone_brand$"))
    app.add_handler(CallbackQueryHandler(on_laptop_brand_chosen, pattern=r"^back_to_laptop_brand$"))

    app.add_handler(CallbackQueryHandler(on_check_join, pattern=r"^check_join$"))
    app.add_handler(CallbackQueryHandler(on_language_chosen, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(on_role_chosen, pattern=r"^role:"))
    app.add_handler(CallbackQueryHandler(on_category_chosen, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(on_subcity_chosen, pattern=r"^subcity:"))
    app.add_handler(CallbackQueryHandler(on_phone_brand_chosen, pattern=r"^phone_brand:"))
    app.add_handler(CallbackQueryHandler(on_laptop_brand_chosen, pattern=r"^laptop_brand:"))
    app.add_handler(CallbackQueryHandler(on_budget_chosen, pattern=r"^budget:"))
    app.add_handler(CallbackQueryHandler(on_room_chosen, pattern=r"^room:"))

    logger.info("Bot starting with updated action-based navigation labels...")
    app.run_polling()

if __name__ == "__main__":
    main()
