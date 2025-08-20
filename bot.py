import os
import logging
import requests
from urllib.parse import urlparse, parse_qs, urlunparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime, timedelta

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
        def find(self, *args, **kwargs): return []
        def count_documents(self, *args, **kwargs): return 0
    users_collection = DummyCollection()

def is_admin(user_id):
    """Check if user is admin"""
    return user_id in ADMIN_IDS

def expand_short_url(short_url):
    """Expand short URLs to see their final destination"""
    try:
        response = requests.head(short_url, allow_redirects=True, timeout=10)
        return response.url
    except:
        return short_url

def clean_ad_url(url):
    """Remove tracking parameters from URLs"""
    try:
        # First expand short URLs
        expanded_url = expand_short_url(url)
        
        parsed = urlparse(expanded_url)
        
        # Comprehensive list of tracking parameters to remove
        tracking_params = [
            # Google parameters
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'utm_id', 'utm_cid', 'utm_reader', 'utm_viz_id', 'utm_pubreferrer',
            'utm_swu', 'utm_referrer', 'utm_social', 'utm_social_type',
            
            # Facebook parameters
            'fbclid', 'fb_action_ids', 'fb_action_types', 'fb_source',
            'fb_ref', 'fb_comment_id', 'fbc', 'fblid', 'fbid',
            
            # Microsoft parameters
            'msclkid', 'msckid', 'mscid', 'mscfid',
            
            # Twitter parameters
            'twclid', 'twsrc', 'twod', 'twcr',
            
            # TikTok parameters
            'ttclid', 'tt_source', 'tt_medium', 'tt_campaign',
            
            # Pinterest parameters
            'pinclid', 'pin_placement', 'pin_source', 'pin_medium',
            
            # LinkedIn parameters
            'liclid', 'licreative', 'lidsp', 'li_fat_id',
            
            # Snapchat parameters
            'scclid', 'snap_origin', 'snap_origin_type',
            
            # Email parameters
            'vero_conv', 'vero_id', 'vero_rid', 'mc_cid', 'mc_eid',
            
            # General tracking
            'gclid', 'gclsrc', 'dclid', 'yclid', 'ipclid', 'rtd_cid',
            '_openstat', 'hmpl', 'hmcu', 'hmkw', 'hmci', 'hmsr', 'hmpl',
            'icid', 'iclp', 'vero_conv', 'vero_id', 'campaign_id',
            'clickid', 'affiliate_id', 'partner_id', 'ref_id', 'referral_code',
            'source', 'medium', 'campaign', 'term', 'content', 'affiliate',
            'clickId', 'transactionId', 'redirect_log_mongo_id',
            'redirect_mongo_id', 'sc_campaign', 'sc_channel', 'sc_content',
            'sc_country', 'sc_geo', 'sc_medium', 'sc_outcome', 'sc_page',
            'sc_group', 'sc_publisher', 'sc_publisher_name'
        ]
        
        # Keep only non-tracking query parameters
        query_params = parse_qs(parsed.query)
        clean_params = {}
        
        for key, values in query_params.items():
            key_lower = key.lower()
            is_tracking = any(track_param in key_lower for track_param in tracking_params)
            
            if not is_tracking:
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
        
        # Add admin badge if user is admin
        admin_badge = " 👑" if is_admin(user_id) else ""
        
        if not user:
            # Check for referral
            referral_id = context.args[0] if context.args else None
            
            new_user = {
                'user_id': user_id,
                'is_premium': True,  # Give free trial
                'premium_until': datetime.now() + timedelta(hours=24),
                'usage_count': 0,
                'total_cleaned': 0,
                'referral_id': referral_id,
                'referrals': [],
                'last_used': None,
                'join_date': datetime.now(),
                'free_trial_used': True
            }
            
            users_collection.insert_one(new_user)
            
            # Reward referrer
            if referral_id and referral_id.isdigit():
                users_collection.update_one(
                    {'user_id': int(referral_id)},
                    {'$push': {'referrals': user_id}}
                )
        
        welcome_text = f"""
🤖 *Welcome to Ads Link Cleaner Bot!* {admin_badge}

I remove tracking parameters and clean ads from URLs!

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

📱 *Follow us:* [Facebook Page]({FACEBOOK_PAGE})

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
        
        # If user doesn't exist, create them automatically
        if not user:
            new_user = {
                'user_id': user_id,
                'is_premium': True,
                'premium_until': datetime.now() + timedelta(hours=24),
                'usage_count': 0,
                'total_cleaned': 0,
                'referrals': [],
                'last_used': None,
                'join_date': datetime.now(),
                'free_trial_used': True
            }
            users_collection.insert_one(new_user)
            user = new_user
        
        # Check if user provided URL
        if not context.args:
            await update.message.reply_text("Please provide a URL to clean!\nExample: `/clean https://example.com?utm_source=facebook`", parse_mode='Markdown')
            return
        
        url = ' '.join(context.args)
        
        # Check if premium expired
        is_premium = user.get('is_premium', False)
        premium_until = user.get('premium_until')
        
        if premium_until and isinstance(premium_until, datetime):
            if datetime.now() > premium_until:
                is_premium = False
                users_collection.update_one(
                    {'user_id': user_id},
                    {'$set': {'is_premium': False}}
                )
        
        # Check daily limit for free users
        if not is_premium and user.get('usage_count', 0) >= FREE_DAILY_LIMIT:
            await update.message.reply_text(
                f"❌ *Daily Limit Reached!*\n\n"
                f"You've used {user.get('usage_count', 0)}/{FREE_DAILY_LIMIT} free cleans today.\n"
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

*Original URL:* 
`{url}`

*Cleaned URL:* 
`{cleaned_url}`

📊 *Stats Today:* {user.get('usage_count', 0) + 1}/{FREE_DAILY_LIMIT}
🎯 *Total Cleaned:* {user.get('total_cleaned', 0) + 1}

💎 *Status:* {'Premium (Free Trial)' if is_premium else 'Free'}
"""
        
        await update.message.reply_text(response_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error cleaning URL: {e}")
        await update.message.reply_text("❌ Error cleaning URL. Please send a valid URL starting with http:// or https://")

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
• UPI / Bank Transfer
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
        
        # Check premium status
        is_premium = user.get('is_premium', False)
        premium_until = user.get('premium_until')
        
        if premium_until and isinstance(premium_until, datetime):
            if datetime.now() > premium_until:
                is_premium = False
        
        status = "Premium 🎯" if is_premium else "Free ⭐"
        referrals = len(user.get('referrals', []))
        
        # Add admin info if user is admin
        admin_info = ""
        if is_admin(user_id):
            total_users = users_collection.count_documents({})
            premium_users = users_collection.count_documents({'is_premium': True})
            admin_info = f"\n👑 *Admin Stats:*\n• Total Users: {total_users}\n• Premium Users: {premium_users}"
        
        text = f"""
📊 *Your Statistics* 📊

*Status:* {status}
*Today's Usage:* {user.get('usage_count', 0)}/{FREE_DAILY_LIMIT}
*Total Cleaned:* {user.get('total_cleaned', 0)}
*Referrals:* {referrals}/{REFERRALS_PER_REWARD}
{admin_info}

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
    """Send payment information"""
    try:
        text = f"""
💳 *Payment Options* 💳

*UPI ID:* `{UPI_ID}`
*App:* OKBIZ Axis Bank

*Payment Plans:*
• 1 Week - ₹49
• 1 Month - ₹149  
• 3 Months - ₹399

📸 *After payment, send screenshot to @Admin*
⚡ *Activated within 5 minutes!*
"""
        
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in pay: {e}")
        await update.message.reply_text(f"*UPI ID:* `{UPI_ID}`\n\nSend payment screenshot to @Admin", parse_mode='Markdown')

async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == 'premium_buy':
        await pay(query.message, context)
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

# ==================== ADMIN COMMANDS ====================

async def make_premium(update: Update, context: CallbackContext) -> None:
    """Admin command to make user premium"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /make_premium <user_id> <days>\nExample: /make_premium 123456789 30")
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

async def user_info(update: Update, context: CallbackContext) -> None:
    """Admin command to get user information"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /userinfo <user_id>\nExample: /userinfo 123456789")
        return
    
    try:
        target_id = int(context.args[0])
        user = users_collection.find_one({'user_id': target_id})
        
        if not user:
            await update.message.reply_text("❌ User not found!")
            return
        
        is_premium = user.get('is_premium', False)
        premium_until = user.get('premium_until')
        referrals = len(user.get('referrals', []))
        
        text = f"""
👤 *User Information* 👤

*User ID:* `{target_id}`
*Status:* {'Premium 🎯' if is_premium else 'Free ⭐'}
*Premium Until:* {premium_until if premium_until else 'Not premium'}
*Total Cleaned:* {user.get('total_cleaned', 0)}
*Referrals:* {referrals}
*Join Date:* {user.get('join_date', 'Unknown')}
*Last Used:* {user.get('last_used', 'Never')}
"""
        
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in user_info: {e}")
        await update.message.reply_text("❌ Error fetching user information.")

async def broadcast(update: Update, context: CallbackContext) -> None:
    """Admin command to broadcast message to all users"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>\nExample: /broadcast Hello everyone!")
        return
    
    try:
        message = ' '.join(context.args)
        all_users = users_collection.find()
        success = 0
        failed = 0
        
        await update.message.reply_text("📢 Starting broadcast...")
        
        for user in all_users:
            try:
                await context.bot.send_message(
                    chat_id=user['user_id'],
                    text=f"📢 *Admin Broadcast:*\n\n{message}",
                    parse_mode='Markdown'
                )
                success += 1
            except:
                failed += 1
        
        await update.message.reply_text(
            f"✅ Broadcast completed!\n"
            f"• Success: {success}\n"
            f"• Failed: {failed}"
        )
        
    except Exception as e:
        logger.error(f"Error in broadcast: {e}")
        await update.message.reply_text("❌ Error in broadcast.")

async def admin_help(update: Update, context: CallbackContext) -> None:
    """Show admin help"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only command.")
        return
    
    text = """
👑 *Admin Commands* 👑

/make\_premium <user\_id> <days> - Make user premium
/userinfo <user\_id> - Get user information  
/broadcast <message> - Broadcast to all users
/stats - View user statistics with admin info

*Only admins can use these commands!*
"""
    
    await update.message.reply_text(text, parse_mode='Markdown')

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
    application.add_handler(CommandHandler("userinfo", user_info))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("admin", admin_help))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start polling
    logger.info("Starting Ads Cleaner Bot...")
    application.run_polling(
        poll_interval=1.0,
        timeout=30,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()