import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Load environment variables
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGO_URI = os.getenv("MONGODB_URI")
UPI_ID = os.getenv("UPI_ID")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip().isdigit()]

# ------------------------------
# Command Handlers
# ------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to EduBot!\n"
        "📌 Use /pay to get payment details.\n"
        "📌 Only admins can use /admin."
    )

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"💰 Payment Details:\n\n"
        f"📌 UPI ID: `{UPI_ID}`\n"
        f"✅ After payment, send screenshot here."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMINS:
        await update.message.reply_text("✅ Admin panel accessed!")
    else:
        await update.message.reply_text("❌ You are not authorized.")

# ------------------------------
# Main Function
# ------------------------------

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("admin", admin))

    print("🤖 Bot started successfully...")
    app.run_polling()

if __name__ == "__main__":
    main()