import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime
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
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') or os.getenv('TELECRAM_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI') or os.getenv('MONGODB_URT', '')
DB_NAME = os.getenv('DB_NAME', 'Aariyan')
COLLECTION = os.getenv('COLLECTION', 'users')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_ID', '').split(',') if id.strip()]
FREE_DAILY_LIMIT = int(os.getenv('FREE_DAILY_LIMIT', 4))

# Fix MongoDB URI if missing protocol
if MONGODB_URI and not MONGODB_URI.startswith(('mongodb://', 'mongodb+srv://')):
    MONGODB_URI = 'mongodb+srv://' + MONGODB_URI

# Initialize MongoDB client
try:
    if MONGODB_URI and not MONGODB_URI.endswith('Aariyan:Abora2969@cluster0'):  # Fix for your bad URI
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]
        users_collection = db[COLLECTION]
        logger.info("Connected to MongoDB successfully")
        
        # Test connection
        users_collection.find_one({})
        logger.info("MongoDB connection test successful")
    else:
        raise ValueError("Invalid MongoDB URI")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {e}")
    # Create a complete dummy collection
    class DummyCollection:
        def find_one(self, *args, **kwargs): return None
        def update_one(self, *args, **kwargs): return None
        def insert_one(self, *args, **kwargs): return None
        def update_many(self, *args, **kwargs): return None
    users_collection = DummyCollection()
    logger.warning("Using dummy collection - database operations will not be saved")

async def start(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.effective_user.id
        user_data = users_collection.find_one({'user_id': user_id})
        
        if not user_data:
            # Create new user
            new_user = {
                'user_id': user_id,
                'is_premium': False,
                'usage_count': 0,
                'referrals': [],
                'last_used': None,
                'join_date': datetime.now()
            }
            
            # Only insert if we have a real database connection
            if hasattr(users_collection, 'insert_one'):
                users_collection.insert_one(new_user)
                logger.info(f"New user created: {user_id}")
        
        welcome_text = (
            "🤖 Welcome to the Ad Skipper Bot!\n\n"
            "I can help you skip ads on various platforms.\n\n"
            "🔹 /skip - Skip ads on a video\n"
            "🔹 /premium - Get premium features\n"
            "🔹 /referral - Get your referral link\n"
            "🔹 /stats - Check your usage statistics\n\n"
            "Type /skip to get started!"
        )
        
        await update.message.reply_text(welcome_text)
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text("🚀 Welcome to Ad Skipper Bot! Use /skip to start!")

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
        
        # Update usage count only if we have a real database
        if hasattr(users_collection, 'update_one'):
            users_collection.update_one(
                {'user_id': user_id},
                {'$inc': {'usage_count': 1}, '$set': {'last_used': datetime.now()}}
            )
        
        await update.message.reply_text("✅ Ads skipped successfully!")
    except Exception as e:
        logger.error(f"Error in skip_ads command: {e}")
        await update.message.reply_text("❌ Failed to skip ads. Please try again later.")

# ... (keep the rest of your functions the same) ...

def main() -> None:
    # Emergency stop any other running instances
    try:
        import requests
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/close", timeout=5)
        logger.info("Closed any previous bot instances")
    except:
        pass
    
    # Check if token is available
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not found in environment variables")
        return
    
    # Create application with better settings
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("skip", skip_ads))
    application.add_handler(CommandHandler("premium", premium_info))
    application.add_handler(CommandHandler("referral", referral_info))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start the bot with improved polling
    logger.info("Starting bot with polling...")
    application.run_polling(
        poll_interval=1.0,
        timeout=30,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == '__main__':
    main()