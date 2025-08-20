import datetime
import qrcode
import io
from pymongo import MongoClient
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# -----------------------------
# CONFIG
# -----------------------------
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
MONGO_URI = "YOUR_MONGO_URI"
UPI_ID = 70002561086@okbizaxix
ADMINS = 7896947963  # তোমাৰ Telegram ID

# -----------------------------
# DATABASE
# -----------------------------
client = MongoClient(MONGO_URI)
db = client["ads_skip_bot"]
users = db["users"]

# -----------------------------
# HELPERS
# -----------------------------
def is_admin(user_id):
    return user_id in ADMINS

def get_user(user_id):
    user = users.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "created_at": datetime.date.today().isoformat(),
            "free_trial": True,
            "premium_expiry": None,
            "referrals": 0,
            "daily_links": 0,
            "last_used": datetime.date.today().isoformat(),
            "banned": False
        }
        users.insert_one(user)
    return user

def update_user(user_id, data):
    users.update_one({"user_id": user_id}, {"$set": data})

def reset_daily_usage():
    today = datetime.date.today().isoformat()
    users.update_many({"last_used": {"$ne": today}}, {"$set": {"daily_links": 0, "last_used": today}})

# -----------------------------
# COMMANDS
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user(user_id)
    await update.message.reply_text(
        "👋 Welcome to Ads Skip Bot!\n\n"
        "✨ Features:\n"
        "• 1 Day Free Trial\n"
        "• 4 links/day (free)\n"
        "• Unlimited for Premium\n"
        "• Refer 10 users = +1 Day Premium\n\n"
        "📢 Follow our page: https://facebook.com/yourpage\n\n"
        "Use /skip <link> to clean ads."
    )

async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if user.get("banned"):
        await update.message.reply_text("🚫 You are banned from this bot.")
        return

    reset_daily_usage()

    # Premium check
    today = datetime.date.today().isoformat()
    premium = False
    if user.get("premium_expiry") and user["premium_expiry"] >= today:
        premium = True

    # Free trial check
    if not premium and user.get("free_trial"):
        premium = True
        update_user(user_id, {"free_trial": False, "premium_expiry": today})

    # Daily limit check
    if not premium:
        if user["daily_links"] >= 4:
            await update.message.reply_text("⚠️ Free limit reached (4/day).\nUpgrade to Premium using /pay")
            return
        update_user(user_id, {"daily_links": user["daily_links"] + 1})

    # Process link
    if len(context.args) == 0:
        await update.message.reply_text("Usage: /skip <ad-link>")
        return

    original_link = context.args[0]
    clean_link = original_link.replace("ads.", "")  # demo only
    await update.message.reply_text(f"✅ Clean Link:\n{clean_link}")

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) == 0:
        await update.message.reply_text("Usage: /refer <friend_user_id>")
        return

    friend_id = int(context.args[0])
    if friend_id == user_id:
        await update.message.reply_text("❌ You cannot refer yourself.")
        return

    friend = get_user(friend_id)
    users.update_one({"user_id": user_id}, {"$inc": {"referrals": 1}})

    me = get_user(user_id)
    if me["referrals"] % 10 == 0:
        new_expiry = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        update_user(user_id, {"premium_expiry": new_expiry})
        await update.message.reply_text("🎉 You got 1 day Premium for 10 referrals!")
    else:
        await update.message.reply_text("✅ Referral added.")

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qr_data = f"upi://pay?pa={UPI_ID}&pn=AdsSkipBot&am=100&cu=INR"
    img = qrcode.make(qr_data)
    bio = io.BytesIO()
    bio.name = "payment.png"
    img.save(bio, "PNG")
    bio.seek(0)
    await update.message.reply_photo(
        photo=bio,
        caption=f"💳 Pay ₹100 via UPI\n\nUPI ID: {UPI_ID}\n\nAfter payment send screenshot to Admin."
    )

# -----------------------------
# ADMIN COMMANDS
# -----------------------------
async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your Telegram ID: {update.effective_user.id}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized!")
        return

    total_users = users.count_documents({})
    premium_users = users.count_documents({"premium_expiry": {"$gte": datetime.date.today().isoformat()}})
    await update.message.reply_text(f"📊 Stats:\n\n👥 Total Users: {total_users}\n💎 Premium: {premium_users}")

async def make_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized!")
        return
    if len(context.args) == 0:
        await update.message.reply_text("Usage: /make_premium <user_id>")
        return
    uid = int(context.args[0])
    new_expiry = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    update_user(uid, {"premium_expiry": new_expiry})
    await update.message.reply_text(f"✅ User {uid} is now Premium for 30 days.")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized!")
        return
    if len(context.args) == 0:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    uid = int(context.args[0])
    update_user(uid, {"banned": True})
    await update.message.reply_text(f"🚫 User {uid} banned.")

# -----------------------------
# MAIN
# -----------------------------
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("skip", skip))
    app.add_handler(CommandHandler("refer", refer))
    app.add_handler(CommandHandler("pay", pay))

    # Admin
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("make_premium", make_premium))
    app.add_handler(CommandHandler("ban", ban))

    app.run_polling()

if __name__ == "__main__":
    main()