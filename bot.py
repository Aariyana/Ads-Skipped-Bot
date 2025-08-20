from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
import datetime, os, requests

# --- CONFIG ---
TOKEN = os.getenv("TELEGRAM_TOKEN")   # Railway/Heroku ত environment variable set কৰিবা
MONGO_URI = os.getenv("MONGO_URI")   # MongoDB Atlas URI
FACEBOOK_PAGE = "https://facebook.com/YourPageLink"

client = MongoClient(MONGO_URI)
db = client["ads_skip_bot"]
users = db["users"]

# --- DATABASE UTILS ---
async def get_user(user_id):
    user = users.find_one({"user_id": user_id})
    today = datetime.date.today()

    if not user:
        expiry = today + datetime.timedelta(days=1)  # 1 day trial
        user = {
            "user_id": user_id,
            "count": 0,
            "date": today.isoformat(),
            "premium_expiry": expiry.isoformat(),
            "trial_used": True,
            "referrals": 0
        }
        users.insert_one(user)
    return user

def is_premium(user):
    today = datetime.date.today()
    expiry = datetime.date.fromisoformat(user["premium_expiry"]) if user.get("premium_expiry") else None
    return expiry and expiry >= today

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user(update.effective_user.id)

    ref_id = None
    if context.args:
        try:
            ref_id = int(context.args[0])
        except:
            pass

    # Referral system
    if ref_id and ref_id != update.effective_user.id:
        ref_user = users.find_one({"user_id": ref_id})
        if ref_user:
            users.update_one({"user_id": ref_id}, {"$inc": {"referrals": 1}})
            ref_user = users.find_one({"user_id": ref_id})
            if ref_user["referrals"] % 10 == 0:
                new_expiry = datetime.date.today() + datetime.timedelta(days=1)
                users.update_one({"user_id": ref_id}, {"$set": {"premium_expiry": new_expiry.isoformat()}})
    
    msg = (
        "👋 Welcome to Ads-Skip Bot!\n\n"
        "🎁 You got 1 Day FREE Premium Trial (Unlimited links today).\n"
        "⚡ After that, Free users can clean 4 links/day.\n"
        "💎 Refer 10 friends = 1 Day Premium again!\n\n"
        f"📌 Follow us here: {FACEBOOK_PAGE}\n\n"
        f"🔗 Share referral link:\nhttps://t.me/{context.bot.username}?start={update.effective_user.id}"
    )
    await update.message.reply_text(msg)

async def clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = await get_user(uid)

    today = datetime.date.today()
    if user["date"] != today.isoformat():
        users.update_one({"user_id": uid}, {"$set": {"count": 0, "date": today.isoformat()}})
        user["count"] = 0

    if not is_premium(user):
        if user["count"] >= 4:
            await update.message.reply_text("⚠️ Daily Free limit reached (4/4). Upgrade to Premium or refer 10 friends!")
            return
        users.update_one({"user_id": uid}, {"$inc": {"count": 1}})
    
    link = update.message.text.strip()
    try:
        r = requests.head(link, allow_redirects=True, timeout=10)
        final_url = r.url
        await update.message.reply_text(f"✅ Clean Link: {final_url}")
    except:
        await update.message.reply_text("❌ Couldn’t clean this link.")

# --- BOT RUNNER ---
app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, clean))

app.run_polling()