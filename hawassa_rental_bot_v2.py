"""
Hawassa Rental Bot — button-flow version
==========================================
"""

import json
import re
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.environ["BOT_TOKEN"]  
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))  
DB_FILE = "/data/listings.json"  # Persistent volume for Railway

SUBCITIES = [
    "Tabor", "Hawela-Tula", "Addis Ketema", "Hayek Dare",
    "Menehariya", "Misrak", "Bahile Adarash", "Mehal Ketema",
]

# Updated to match your exact requested buttons
BUDGETS = [
    ("2000-5000", 2000, 5000),
    ("5000-10000", 5000, 10000),
    ("10000-15000", 10000, 15000),
    ("15000+", 15000, None),
]

# Updated to include the spaces you requested
ROOM_TYPES = ["ባለ 1", "ባለ 2", "ባለ 3", "ባለ 4", "ሙሉ ግቢ"]

PHONE_REGEX = re.compile(r"(?:\+251|0)9\d{8}")
PRICE_REGEX = re.compile(r"(\d{3,6})\s*ብር")


def load_listings():
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_listings(listings):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)


def parse_listing(text: str):
    subcity = next((s for s in SUBCITIES if s.lower() in text.lower()), None)
    room = next((r for r in ROOM_TYPES if r in text), None)
    price_match = PRICE_REGEX.search(text)
    phone_match = PHONE_REGEX.search(text)

    return {
        "subcity": subcity,
        "room": room,
        "price": int(price_match.group(1)) if price_match else None,
        "phone": phone_match.group(0) if phone_match else None,
        "text": text,
    }


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Includes the fix for catching edited channel posts
    post = update.channel_post or update.edited_channel_post
    if not post:
        return
    post_text = post.text or post.caption  
    if not post_text:
        return
    if CHANNEL_ID and post.chat.id != CHANNEL_ID:
        return  
    listing = parse_listing(post_text)
    listing["message_id"] = post.message_id
    listings = load_listings()
    listings.append(listing)
    save_listings(listings)
    print(f"Saved new listing: {listing}")


# ---------- Button flow ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    buttons = [[InlineKeyboardButton(sc, callback_data=f"subcity:{sc}")] for sc in SUBCITIES]
    await update.message.reply_text(
        "የትኛው ክፍለ ከተማ ውስጥ ቤት ይፈልጋሉ?\nWhich sub-city are you looking in?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def on_subcity_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    subcity = query.data.split(":", 1)[1]
    context.user_data["subcity"] = subcity

    buttons = [
        [InlineKeyboardButton(label, callback_data=f"budget:{low}:{high or ''}")]
        for label, low, high in BUDGETS
    ]
    # Updated text based on your request
    await query.edit_message_text(
        "የ ገንዘብ መጠንህን አስገባ (ለምሳሌ:- 5000 1000)",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def on_budget_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, low, high = query.data.split(":")
    context.user_data["budget_low"] = int(low)
    context.user_data["budget_high"] = int(high) if high else None

    buttons = [[InlineKeyboardButton(r, callback_data=f"room:{r}")] for r in ROOM_TYPES]
    # Updated text based on your request
    await query.edit_message_text(
        "ባለ ስንት ክፍል ነው መከራየር የፈለጉት",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def on_room_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    room = query.data.split(":", 1)[1]

    subcity = context.user_data.get("subcity")
    budget_low = context.user_data.get("budget_low")
    budget_high = context.user_data.get("budget_high")

    listings = load_listings()
    results = []
    for l in listings:
        if l.get("subcity") != subcity:
            continue
        if l.get("room") != room:
            continue
        price = l.get("price")
        if price is not None:
            if price < budget_low:
                continue
            if budget_high is not None and price > budget_high:
                continue
        results.append(l)

    if not results:
        await query.edit_message_text("ይቅርታ፣ ተመሳሳይ ቤት አልተገኘም። No matching house found yet.")
        return

    await query.edit_message_text(f"{len(results)} ቤት(ቶች) ተገኝተዋል! Found {len(results)} matching house(s):")
    
    for r in results[:5]:
        try:
            # This directly FORWARDS the message from the channel, 
            # bringing all photos and formatting with it exactly like @Phonofilmbot!
            await context.bot.forward_message(
                chat_id=query.message.chat_id,
                from_chat_id=CHANNEL_ID,
                message_id=r["message_id"]
            )
        except Exception:
            # Fallback text if the channel forwarding fails
            await context.bot.send_message(chat_id=query.message.chat_id, text=r["text"])


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_subcity_chosen, pattern=r"^subcity:"))
    app.add_handler(CallbackQueryHandler(on_budget_chosen, pattern=r"^budget:"))
    app.add_handler(CallbackQueryHandler(on_room_chosen, pattern=r"^room:"))
    app.add_handler(MessageHandler(
        filters.ChatType.CHANNEL & (filters.UpdateType.CHANNEL_POST | filters.UpdateType.EDITED_CHANNEL_POST),
        on_channel_post
    ))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
