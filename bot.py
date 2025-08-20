import os
import logging
import re
import requests
from urllib.parse import urlparse, parse_qs, urlunparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime, timedelta
from io import BytesIO

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')
DB_NAME = os.getenv('DB_NAME', 'AdsCleaner')
COLLECTION = os.getenv('COLLECTION', 'users')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_ID', '').split(',') if id.strip()]
FREE_DAILY_LIMIT = int(os.getenv('FREE_DAILY_LIMIT', 4))
REFERRALS_PER_REWARD = int(os.getenv('REFERRALS_PER_REWARD', 10))
PREMIUM_DAYS_PER_REWARD = int(os.getenv('PREMIUM_DAYS_PER_REWARD', 1))
FACEBOOK_PAGE = os.getenv('FACEBOOK_PAGE', 'https://www.facebook.com/yourpage')
UPI_ID = os.getenv('UPI_ID', 'yourupi@id')

# Initialize MongoDB
try:
    client = MongoClient(MONGODB_URI)
    db = client[DB_NAME]
    users_collection = db[COLLECTION]
    logger.info("Connected to MongoDB successfully")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {e}")
    class DummyCollection:
        def find_one(self, *args, **kwargs): return None
        def update_one(self, *args, **kwargs): return None
        def insert_one(self, *args, **kwargs): return None
    users_collection = DummyCollection()

def clean_ad_url(url):
    """Remove tracking parameters from URLs"""
    try:
        parsed = urlparse(url)
        
        # Common ad tracking parameters to remove
        tracking_params = [
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'fbclid', 'gclid', 'msclkid', 'dclid', 'vero_conv', 'vero_id',
            'yclid', '_openstat', 'hmpl', 'hmcu', 'hmkw', 'hmci'
        ]
        
        # Keep only non-tracking query parameters
        query_params = parse_qs(parsed.query)
        clean_params = {}
        
        for key, values in query_params.items():
            if key.lower() not in [p.lower() for p in tracking_params]:
                clean_params[key] = values[0] if len(values) == 1 else values
        
        # Rebuild clean URL
        clean_query = '&'.join([f"{k}={v}" for k, v in clean_params.items()])
        clean_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            clean_query,
            parsed.fragment
        ))
        
        return clean_url
    except Exception as e:
        logger.error(f"Error cleaning URL: {e}")
        return url

async def start(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.effective_user.id
        user = users_collection.find_one({'user_id': user_id})
        
        if not user:
            # Check for referral
            referral_id = context.args[0] if context.args else None
            
            new_user = {
                'user_id': user_id,
                'is_premium': False,
                'premium_until': None,
                'usage_count': 0,
                'total_cleaned': 0,
                'referral_id': referral_id,
                'referrals': [],
                'last_used': None,
                'join_date': datetime.now(),
                'free_trial_used': False
            }
            
            # Give 24-hour free trial for new users
            if not user:
                new_user['is_premium'] = True
                new_user['premium_until'] = datetime.now() + timedelta(hours=24)
                new_user['free_trial_used'] = True
            
            users_collection.insert_one(new_user)
            
            # Reward referrer
            if referral_id and referral_id.isdigit():
                users_collection.update_one(
                    {'user_id': int(referral_id)},
                    {'$push': {'referrals': user_id}}
                )
        
        welcome_text = f"""
🤖 *Welcome to Ads Link Cleaner Bot!* 🤖

I can remove tracking parameters and clean ads from your URLs!

✨ *Features:*
• Clean ad tracking parameters
• {FREE_DAILY_LIMIT} free cleans daily
• Premium for unlimited cleans
• Referral rewards system

🔧 *Commands:*
/clean [url] - Clean ad links
/premium - Get premium access  
/referral - Your referral link
/stats - Your usage statistics
/pay - Payment options

📱 *Follow us:* {FACEBOOK_PAGE}

*Send me any URL with ads to get started!* 🚀
"""
        
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in start: {e}")
        await update.message.reply_text("Welcome! Send me any URL to clean ads from it! 🚀")

async def clean_url(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.effective_user.id
        user = users_collection.find_one({'user_id': user_id})
        
        if not user:
            await update.message.reply_text("Please use /start first to setup your account!")
            return
        
        # Check if user provided URL
        if not context.args:
            await update.message.reply_text("Please provide a URL to clean!\nExample: /clean https://example.com?utm_source=facebook")
            return
        
        url = ' '.join(context.args)
        
        # Check daily limit for free users
        if not user.get('is_premium', False) and user.get('usage_count', 0) >= FREE_DAILY_LIMIT:
            await update.message.reply_text(
                f"❌ *Daily Limit Reached!*\n\n"
                f"You've used {FREE_DAILY_LIMIT} free cleans today.\n"
                "Upgrade to premium for unlimited cleans!\n\n"
                "Use /premium to learn more!",
                parse_mode='Markdown'
            )
            return
        
        # Clean the URL
        cleaned_url = clean_ad_url(url)
        
        # Update user stats
        users_collection.update_one(
            {'user_id': user_id},
            {
                '$inc': {'usage_count': 1, 'total_cleaned': 1},
                '$set': {'last_used': datetime.now()}
            }
        )
        
        # Send cleaned URL
        response_text = f"""
✅ *URL Cleaned Successfully!* ✅

*Original:* `{url}`
*Cleaned:* `{cleaned_url}`

📊 *Stats Today:* {user.get('usage_count', 0) + 1}/{FREE_DAILY_LIMIT} cleans
🎯 *Total Cleaned:* {user.get('total_cleaned', 0) + 1}

*Want unlimited cleans?* Use /premium
"""
        
        await update.message.reply_text(response_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error cleaning URL: {e}")
        await update.message.reply_text("❌ Error cleaning URL. Please try again with a valid URL.")

async def premium_info(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("💎 Get Premium", callback_data='premium_buy')],
        [InlineKeyboardButton("📊 Benefits", callback_data='premium_benefits')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""
🌟 *Premium Membership* 🌟

*Benefits:*
• ✅ Unlimited URL cleaning
• ✅ No daily limits  
• ✅ Priority processing
• ✅ Exclusive features

*Pricing:*
• 1 Week - ₹49
• 1 Month - ₹149
• 3 Months - ₹399

*Payment Methods:*
• UPI
• Referral rewards

*Click below to get premium!* 🚀
"""
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def stats(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.effective_user.id
        user = users_collection.find_one({'user_id': user_id})
        
        if not user:
            await update.message.reply_text("Please use /start first!")
            return
        
        status = "Premium 🎯" if user.get('is_premium', False) else "Free ⭐"
        referrals = len(user.get('referrals', []))
        
        text = f"""
📊 *Your Statistics* 📊

*Status:* {status}
*Today's Usage:* {user.get('usage_count', 0)}/{FREE_DAILY_LIMIT}
*Total Cleaned:* {user.get('total_cleaned', 0)}
*Referrals:* {referrals}/{REFERRALS_PER_REWARD}

*Premium Until:* {user.get('premium_until', 'Not active')}

*Earn free premium by referring friends!*
Use /referral to get your link.
"""
        
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in stats: {e}")
        await update.message.reply_text("❌ Error fetching statistics.")

async def referral_info(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.effective_user.id
        bot_username = (await context.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={user_id}"
        
        user = users_collection.find_one({'user_id': user_id})
        referrals = len(user.get('referrals', [])) if user else 0
        
        text = f"""
📨 *Referral Program* 📨

*Your Link:* `{referral_link}`

*Stats:* {referrals}/{REFERRALS_PER_REWARD} referrals

*Reward:* {PREMIUM_DAYS_PER_REWARD} day premium for every {REFERRALS_PER_REWARD} referrals!

*Share your link and earn free premium!* 🎁
"""
        
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in referral: {e}")
        await update.message.reply_text("❌ Error generating referral link.")

async def pay(update: Update, context: CallbackContext) -> None:
    """Send UPI QR code for payment"""
    try:
        # Create QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(UPI_ID)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        bio = BytesIO()
        bio.name = 'qrcode.png'
        img.save(bio, 'PNG')
        bio.seek(0)
        
        text = f"""
💳 *Payment Options* 💳

*UPI ID:* `{UPI_ID}`

*Payment Plans:*
• 1 Week - ₹49
• 1 Month - ₹149  
• 3 Months - ₹399

*After payment, send screenshot to @Admin*
"""
        
        await update.message.reply_photo(photo=bio, caption=text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in pay: {e}")
        await update.message.reply_text(f"UPI ID: `{UPI_ID}`\n\nSend payment screenshot to @Admin", parse_mode='Markdown')

async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == 'premium_buy':
        await pay(query, context)
    elif query.data == 'premium_benefits':
        await query.edit_message_text("""
🎯 *Premium Benefits* 🎯

• Unlimited URL cleaning (no daily limits)
• 5x faster processing speed  
• Exclusive early access to new features
• Priority customer support
• No waiting times during peak hours

*Upgrade today for the best experience!* 🚀
""", parse_mode='Markdown')

# Admin commands
async def make_premium(update: Update, context: CallbackContext) -> None:
    """Admin command to make user premium"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /make_premium <user_id> <days>")
        return
    
    try:
        target_id = int(context.args[0])
        days = int(context.args[1]) if len(context.args) > 1 else 30
        
        premium_until = datetime.now() + timedelta(days=days)
        
        users_collection.update_one(
            {'user_id': target_id},
            {
                '$set': {
                    'is_premium': True,
                    'premium_until': premium_until
                }
            },
            upsert=True
        )
        
        await update.message.reply_text(f"✅ User {target_id} is now premium for {days} days!")
        
    except Exception as e:
        logger.error(f"Error in make_premium: {e}")
        await update.message.reply_text("❌ Error making user premium.")

def main() -> None:
    if not TELEGRAM_TOKEN:
        logger.error("No Telegram token found!")
        return
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clean", clean_url))
    application.add_handler(CommandHandler("premium", premium_info))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("referral", referral_info))
    application.add_handler(CommandHandler("pay", pay))
    application.add_handler(CommandHandler("make_premium", make_premium))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start polling
    logger.info("Starting Ads Cleaner Bot...")
    application.run_polling()

if __name__ == '__main__':
    main()