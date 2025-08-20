import os
import datetime
from pymongo import MongoClient
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes
)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
UPI_ID = os.getenv("UPI_ID")
FACEBOOK_LINK = os.getenv("FACEBOOK_LINK")

# MongoDB Setup
client = MongoClient(MONGO_URI)
db = client["ads_skip_bot"]
users_col = db["users"]

# ---------------- USER MANAGEMENT ----------------
def get_user(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "premium": False,
            "trial_start": datetime.datetime.utcnow(),
            "referrals": 0,
            "used_links": 0,
            "last_reset": datetime.datetime.utcnow().date()
        }
        users_col.insert_one(user)
    return user

def update_user(user_id, data):
    users_col.update_one({"user_id": user_id}, {"$set": data})

def reset_daily_usage(user):
    today = datetime.datetime.utcnow().date()
    if user.get("last_reset") != today:
        update_user(user["user_id"], {"used_links": 0, "last_reset": today})
        user["used_links"] = 0
    return user

# ---------------- COMMANDS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    msg = (
        "🚀 Welcome to Ads Skip Bot!\n\n"
        "✨ Features:\n"
        "1️⃣ Clear Ads Links\n"
        "2️⃣ Free: 4 links/day\n"
        "3️⃣ Premium: Unlimited\n"
        "4️⃣ Refer 10 = 1 day Premium\n"
        "5️⃣ 1-Day Free Trial Available\n\n"
        f"📌 Facebook Page: {FACEBOOK_LINK}\n"
    )
    await update.message.reply_text(msg)

async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    user = reset_daily_usage(user)

    # Trial check
    trial_expired = (datetime.datetime.utcnow() - user["trial_start"]).days >= 1

    if not user["premium"] and trial_expired and user["used_links"] >= 4:
        await update.message.reply_text("⚠️ Daily limit reached! Upgrade to Premium or Refer friends.")
        return

    # Simulate skipping ads link
    original = update.message.text
    if "http" not in original:
        await update.message.reply_text("❌ Please send a valid link.")
        return

    clean_link = original.split("?")[0]  # Example cleaning
    await update.message.reply_text(f"✅ Clean Link: {clean_link}")

    # Update usage
    if not user["premium"] and trial_expired:
        update_user(user["user_id"], {"used_links": user["used_links"] + 1})

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    ref_link = f"https://t.me/{context.bot.username}?start={user['user_id']}"
    await update.message.reply_text(f"👥 Invite your friends using:\n{ref_link}")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    trial_expired = (datetime.datetime.utcnow() - user["trial_start"]).days >= 1
    status = "Premium" if user["premium"] else "Trial" if not trial_expired else "Free"
    msg = (
        f"👤 Profile\n\n"
        f"💎 Status: {status}\n"
        f"🔗 Used Today: {user['used_links']}/4\n"
        f"👥 Referrals: {user['referrals']}\n"
    )
    await update.message.reply_text(msg)

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"💳 Pay using UPI:\n`{UPI_ID}`\n\nSend screenshot to admin after payment.",
        parse_mode="Markdown"
    )

# ---------------- ADMIN COMMANDS ----------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total_users = users_col.count_documents({})
    premium_users = users_col.count_documents({"premium": True})
    await update.message.reply_text(
        f"📊 Bot Stats\n\n👥 Total Users: {total_users}\n💎 Premium Users: {premium_users}"
    )

async def make_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /make_premium <user_id>")
        return
    target = int(context.args[0])
    update_user(target, {"premium": True})
    await update.message.reply_text(f"✅ User {target} is now Premium!")

# ---------------- MAIN ----------------
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("refer", refer))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("make_premium", make_premium))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, skip))

    app.run_polling()

if __name__ == "__main__":
    main()