import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from pymongo import MongoClient
from dotenv import load_dotenv
import aiohttp
import asyncio

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')  # Note: Typo in your env variable name
MONGODB_URI = os.getenv('MONGODB_URI')       # Note: Typo in your env variable name
DB_NAME = os.getenv('DB_NAME')
COLLECTION = os.getenv('COLLECTION')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_ID', '').split(',') if id.strip()]
FREE_DAILY_LIMIT = int(os.getenv('FREE_DAILY_LIMIT', 4))

# Initialize MongoDB client
try:
    client = MongoClient(MONGODB_URI)
    db = client[DB_NAME]
    users_collection = db[COLLECTION]
    logger.info("Connected to MongoDB successfully")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {e}")
    # Create a dummy collection to prevent crashes
    class DummyCollection:
        def find_one(self, *args, **kwargs): return None
        def update_one(self, *args, **kwargs): return None
    users_collection = DummyCollection()

async def start(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.effective_user.id
        user_data = users_collection.find_one({'user_id': user_id})
        
        if not user_data:
            # Referral system
            referral_id = context.args[0] if context.args else None
            new_user = {
                'user_id': user_id,
                'is_premium': False,
                'usage_count': 0,
                'referral_id': referral_id,
                'referrals': [],
                'last_used': None
            }
            users_collection.insert_one(new_user)
            
            # Reward referrer if applicable
            if referral_id:
                users_collection.update_one(
                    {'user_id': int(referral_id)},
                    {'$push': {'referrals': user_id}}
                )
        
        welcome_text = (
            "🤖 Welcome to the Ad Skipper Bot!\n\n"
            "I can help you skip ads on various platforms.\n\n"
            "🔹 /skip - Skip ads on a video\n"
            "🔹 /premium - Get premium features\n"
            "🔹 /referral - Get your referral link\n"
            "🔹 /stats - Check your usage statistics"
        )
        
        await update.message.reply_text(welcome_text)
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again later.")

async def skip_ads(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.effective_user.id
        user_data = users_collection.find_one({'user_id': user_id})
        
        if not user_data:
            await update.message.reply_text("Please use /start first to initialize your account.")
            return
        
        # Check if user has reached daily limit
        if not user_data.get('is_premium', False) and user_data.get('usage_count', 0) >= FREE_DAILY_LIMIT:
            await update.message.reply_text(
                "You've reached your daily free limit. Upgrade to premium for unlimited usage.\n\n"
                "Use /premium to learn more."
            )
            return
        
        # Process the ad skipping (implementation depends on your specific needs)
        # This is a placeholder for your actual ad-skipping logic
        
        # Update usage count
        users_collection.update_one(
            {'user_id': user_id},
            {'$inc': {'usage_count': 1}, '$set': {'last_used': datetime.now()}}
        )
        
        await update.message.reply_text("✅ Ads skipped successfully!")
    except Exception as e:
        logger.error(f"Error in skip_ads command: {e}")
        await update.message.reply_text("❌ Failed to skip ads. Please try again later.")

async def premium_info(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("💎 Get Premium", callback_data='premium_purchase')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "🌟 Premium Features 🌟\n\n"
        "• Unlimited ad skipping\n"
        "• Priority processing\n"
        "• Exclusive features\n"
        "• No daily limits\n\n"
        "Click below to purchase premium access!"
    )
    
    await update.message.reply_text(text, reply_markup=reply_markup)

async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == 'premium_purchase':
        await query.edit_message_text(
            "Please contact @AdminUsername to purchase premium access."
        )

async def referral_info(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.effective_user.id
        referral_link = f"https://t.me/YourBotUsername?start={user_id}"
        
        text = (
            "📨 Referral Program\n\n"
            f"Your referral link: {referral_link}\n\n"
            f"Earn {os.getenv('PREMIUM_DAYS_PER_REWARD', 1)} day of premium for every "
            f"{os.getenv('REFERRALS_PER_REWARD', 10)} friends who join using your link!"
        )
        
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Error in referral_info: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again later.")

def main() -> None:
    # Check if token is available
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not found in environment variables")
        return
    
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("skip", skip_ads))
    application.add_handler(CommandHandler("premium", premium_info))
    application.add_handler(CommandHandler("referral", referral_info))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start the bot
    if os.getenv('DYNO'):  # Running on Heroku
        port = int(os.environ.get('PORT', 8443))
        webhook_url = f"https://your-app-name.herokuapp.com/{TELEGRAM_TOKEN}"
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TELEGRAM_TOKEN,
            webhook_url=webhook_url
        )
    else:  # Running locally
        application.run_polling()

if __name__ == '__main__':
    main()