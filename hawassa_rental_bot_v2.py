"""
Hawassa Rental Bot — Forced Join, Role Selection & Related Search
==================================================================
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
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))  # e.g. -1001234567890
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/Hawassa_Rental")
DB_FILE = "/data/listings.json" if os.path.exists("/data") else "listings.json"
SUPPORT_USERNAME = "Jatech_support"

SUBCITIES = [
    "Tabor", "Hawela-Tula", "Addis Ketema", "Hayek Dare",
    "Menehariya", "Misrak", "Bahile Adarash", "Mehal Ketema",
]

BUDGETS = [
    ("2000-5000 ብር / ETB", 2000, 5000),
    ("5000-10000 ብር / ETB", 5000, 10000),
    ("10000-15000 ብር / ETB", 10000, 15000),
    ("15000+ ብር / ETB", 15000, None),
]

ROOM_TYPES = ["ባለ 1", "ባለ 2", "ባለ 3", "ባለ 4", "ሙሉ ግቢ"]

PHONE_REGEX = re.compile(r"(?:\+251|0)9\d{8}")
PRICE_REGEX = re.compile(r"(\d{3,6})\s*ብር")


# ---------- Database Helpers ----------

def load_listings():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_listings(listings):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)


def parse_listing(text: str):
    subcity = next((s for s in SUBCITIES if s.lower() in text.lower()), None)

    room = None
    text_no_spaces = text.replace(" ", "")
    for r in ROOM_TYPES:
        if r in text or r.replace(" ", "") in text_no_spaces:
            room = r
            break

    price_match = PRICE_REGEX.search(text)
    phone_match = PHONE_REGEX.search(text)

    return {
        "subcity": subcity,
        "room": room,
        "price": int(price_match.group(1)) if price_match else None,
        "phone": phone_match.group(0) if phone_match else None,
        "text": text,
    }


async def is_user_joined(bot, user_id: int) -> bool:
    if not CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        print(f"Error checking channel membership: {e}")
        return True


# ---------- Keyboards ----------

def get_force_join_keyboard():
    buttons = [
        [InlineKeyboardButton("📢 ቻናሉን ይቀላቀሉ (Join Channel)", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ አረጋግጥ (Verify Join)", callback_data="check_join")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_language_keyboard():
    buttons = [
        [
            InlineKeyboardButton("አማርኛ 🇪🇹", callback_data="lang:am"),
            InlineKeyboardButton("English 🇬🇧", callback_data="lang:en"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


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

    buttons = [
        [InlineKeyboardButton(contact_label, url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(main_menu_label, callback_data="restart_search")]
    ]
    return InlineKeyboardMarkup(buttons)


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
    contact_label = "💬 ያናግሩ / Contact"
    main_menu_label = "🏠 ወደ ዋናው ማውጫ ይመለሱ" if lang == "am" else "🏠 Main Menu"

    buttons = [
        [InlineKeyboardButton(contact_label, url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(main_menu_label, callback_data="restart_search")]
    ]
    return InlineKeyboardMarkup(buttons)


# ---------- Channel Post Handler ----------

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    listings = [l for l in listings if l.get("message_id") != post.message_id]
    listings.append(listing)
    save_listings(listings)
    print(f"Saved listing: {listing}")


# ---------- Command & Callback Flow ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id

    # 1. Check Forced Channel Join
    joined = await is_user_joined(context.bot, user_id)
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

    # 2. Show Language Selection
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

    role = query.data.split(":", 1)[1]
    context.user_data["role"] = role
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

    listings = load_listings()
    exact_results = []
    related_results = []

    for l in listings:
        if l.get("subcity") != subcity:
            continue
        if l.get("room") != room:
            continue

        price = l.get("price")
        if price is not None:
            is_exact = True
            if price < budget_low:
                is_exact = False
            if budget_high is not None and price > budget_high:
                is_exact = False

            if is_exact:
                exact_results.append(l)
            else:
                related_results.append(l)
        else:
            related_results.append(l)

    if not exact_results and not related_results:
        no_match_text = (
            "ይቅርታ፣ ተመሳሳይ ቤት አልተገኘም። No matching house found yet."
        )
        await query.edit_message_text(
            no_match_text, reply_markup=get_result_action_keyboard(lang)
        )
        return

    # Header Message
    header_text = (
        f"🎯 **ትክክለኛ ፍለጋ ({len(exact_results)})**"
        if lang == "am"
        else f"🎯 **Exact Matches ({len(exact_results)})**"
    )
    await query.edit_message_text(header_text, parse_mode="Markdown")

    # Send Exact Matches
    for r in exact_results[:5]:
        try:
            await context.bot.forward_message(
                chat_id=query.message.chat_id,
                from_chat_id=CHANNEL_ID or query.message.chat_id,
                message_id=r["message_id"]
            )
        except Exception:
            await context.bot.send_message(chat_id=query.message.chat_id, text=r["text"])

    # Send Related Matches
    if related_results:
        related_header = (
            f"\n💡 **ተዛማጅ ፍለጋዎች (የተለያየ ዋጋ) / Related Searches ({len(related_results[:3])}):**"
        )
        await context.bot.send_message(chat_id=query.message.chat_id, text=related_header, parse_mode="Markdown")

        for r in related_results[:3]:
            try:
                await context.bot.forward_message(
                    chat_id=query.message.chat_id,
                    from_chat_id=CHANNEL_ID or query.message.chat_id,
                    message_id=r["message_id"]
                )
            except Exception:
                await context.bot.send_message(chat_id=query.message.chat_id, text=r["text"])

    # Final Contact & Menu Options
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


# ---------- Main Execution ----------

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern=r"^restart_search$"))
    app.add_handler(CallbackQueryHandler(start, pattern=r"^back_to_lang$"))
    app.add_handler(CallbackQueryHandler(on_check_join, pattern=r"^check_join$"))
    app.add_handler(CallbackQueryHandler(on_language_chosen, pattern=r"^lang:"))
    app.add_handler(CallbackQueryHandler(on_language_chosen, pattern=r"^back_to_role$"))
    app.add_handler(CallbackQueryHandler(on_role_chosen, pattern=r"^role:"))
    app.add_handler(CallbackQueryHandler(on_role_chosen, pattern=r"^back_to_subcity$"))
    app.add_handler(CallbackQueryHandler(on_subcity_chosen, pattern=r"^subcity:"))
    app.add_handler(CallbackQueryHandler(on_subcity_chosen, pattern=r"^back_to_budget$"))
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
