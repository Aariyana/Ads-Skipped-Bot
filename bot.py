import os
import re
import logging
import asyncio
import datetime as dt
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, urljoin

import requests
from bs4 import BeautifulSoup
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ------------------- ENV -------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # required
MONGODB_URI   = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017")
DB_NAME       = os.getenv("DB_NAME", "ads_skip_bot")
COLLECTION    = os.getenv("COLLECTION", "users")
FACEBOOK_PAGE = os.getenv("FACEBOOK_PAGE", "https://facebook.com/yourpage")
ALLOWED_USERS = {u.strip() for u in os.getenv("ALLOWED_USERS", "").split(",") if u.strip()}

# Referral → every 10 unique referrals = 1 day premium
REFERRALS_PER_REWARD = int(os.getenv("REFERRALS_PER_REWARD", "10"))
PREMIUM_DAYS_PER_REWARD = int(os.getenv("PREMIUM_DAYS_PER_REWARD", "1"))

# Daily free limit
FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "4"))

# Asia/Kolkata for “today” rollover (matches your timezone)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# ------------------- LOGGING -------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("AdsSkipBot")

# ------------------- DB -------------------
mongo: AsyncIOMotorClient = AsyncIOMotorClient(MONGODB_URI)
db = mongo[DB_NAME]
users = db[COLLECTION]

# ------------------- URL CLEAN HELPERS -------------------
TRACKING_PARAMS = {
    "utm_source","utm_medium","utm_campaign","utm_term","utm_content","utm_id",
    "gclid","fbclid","igshid","msclkid","vero_conv","vero_id","ref","ref_src",
    "ref_url","spm","ampshare","utm_reader"
}

SHORTENER_HOSTS = {
    "bit.ly","t.co","goo.gl","tinyurl.com","is.gd","buff.ly","ow.ly","rebrand.ly",
    "ift.tt","linktr.ee","cutt.ly","s.id","v.gd","soo.gd","bl.ink","shorte.st",
    "adf.ly","ouo.io","linkvertise.com","clk.sh","exe.io","bc.vc","shrtco.de","shr.link",
    "lnkd.in","1drv.ms","rb.gy","qr.ae","trib.al","smarturl.it","spotify.link"
}

url_regex = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)

def strip_tracking(url: str) -> str:
    try:
        parts = list(urlparse(url))
        q = parse_qsl(parts[4], keep_blank_values=True)
        q = [(k, v) for (k, v) in q if k not in TRACKING_PARAMS]
        parts[4] = urlencode(q, doseq=True)
        return urlunparse(parts)
    except Exception:
        return url

def is_html(content_type: Optional[str]) -> bool:
    return bool(content_type) and "text/html" in content_type.lower()

def is_shortener(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        return any(host == h or host.endswith("." + h) for h in SHORTENER_HOSTS)
    except Exception:
        return False

def extract_meta_refresh(html: str, base_url: str) -> Optional[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        meta = soup.find("meta", attrs={"http-equiv": lambda v: v and v.lower() == "refresh"})
        if not meta:
            return None
        content = meta.get("content", "")
        m = re.search(r"url=(.+)$", content, flags=re.IGNORECASE)
        if not m:
            return None
        u = m.group(1).strip().strip("'\"")
        return urljoin(base_url, u)
    except Exception:
        return None

def follow_redirects(url: str, timeout: int = 12) -> str:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (AdsSkipBot)"})
    try:
        r = s.head(url, allow_redirects=True, timeout=timeout)
        final_url = r.url
        if is_html(r.headers.get("Content-Type", "")):
            g = s.get(final_url, allow_redirects=True, timeout=timeout)
            final_url = g.url
            extracted = extract_meta_refresh(g.text, base_url=final_url)
            if extracted:
                final_url = extracted
        return final_url
    except requests.RequestException:
        try:
            g = s.get(url, allow_redirects=True, timeout=timeout)
            final_url = g.url
            if is_html(g.headers.get("Content-Type", "")):
                extracted = extract_meta_refresh(g.text, base_url=final_url)
                if extracted:
                    final_url = extracted
            return final_url
        except Exception:
            return url

def clean_url(raw: str) -> str:
    final_url = follow_redirects(raw)
    return strip_tracking(final_url or raw)

# ------------------- USER MODEL HELPERS -------------------
async def today_ist() -> dt.date:
    return dt.datetime.now(tz=IST).date()

async def get_or_create_user(u: "telegram.User") -> dict:
    doc = await users.find_one({"_id": u.id})
    if doc:
        return doc
    doc = {
        "_id": u.id,
        "username": u.username,
        "first_name": u.first_name,
        "created_at": dt.datetime.utcnow(),
        "daily_date": (await today_ist()).isoformat(),
        "daily_count": 0,
        "premium_expiry": None,     # ISO datetime or None (UTC)
        "referrals": 0,             # total unique referrals
        "reward_packs_awarded": 0,  # how many 10-referral packs already rewarded
        "referred_by": None,        # user_id
    }
    await users.insert_one(doc)
    return doc

async def is_premium(user_doc: dict) -> bool:
    exp = user_doc.get("premium_expiry")
    if not exp:
        return False
    if isinstance(exp, str):
        exp_dt = dt.datetime.fromisoformat(exp.replace("Z",""))
    else:
        exp_dt = exp
    return exp_dt > dt.datetime.utcnow()

async def ensure_daily_window(user_doc: dict) -> dict:
    # reset daily count if local (IST) date changed
    t = await today_ist()
    if user_doc.get("daily_date") != t.isoformat():
        await users.update_one(
            {"_id": user_doc["_id"]},
            {"$set": {"daily_date": t.isoformat(), "daily_count": 0}}
        )
        user_doc["daily_date"] = t.isoformat()
        user_doc["daily_count"] = 0
    return user_doc

async def increment_daily_if_needed(user_doc: dict) -> None:
    if not await is_premium(user_doc):
        await users.update_one(
            {"_id": user_doc["_id"]},
            {"$inc": {"daily_count": 1}}
        )

async def check_daily_limit(user_doc: dict) -> bool:
    # True if allowed to use now
    user_doc = await ensure_daily_window(user_doc)
    if await is_premium(user_doc):
        return True
    return user_doc.get("daily_count", 0) < FREE_DAILY_LIMIT

async def extend_premium(user_id: int, days: int) -> None:
    now = dt.datetime.utcnow()
    doc = await users.find_one({"_id": user_id}, {"premium_expiry": 1})
    current = doc.get("premium_expiry") if doc else None
    if current:
        if isinstance(current, str):
            current = dt.datetime.fromisoformat(current.replace("Z",""))
        base = current if current > now else now
    else:
        base = now
    new_expiry = base + dt.timedelta(days=days)
    await users.update_one({"_id": user_id}, {"$set": {"premium_expiry": new_expiry}})

async def handle_referral(new_user: dict, ref_id: int) -> None:
    # count only first time (no self-referrals)
    if new_user.get("referred_by") or new_user["_id"] == ref_id:
        return
    await users.update_one({"_id": new_user["_id"]}, {"$set": {"referred_by": ref_id}})
    # increment referrer's referrals
    ref = await users.find_one_and_update(
        {"_id": ref_id},
        {"$inc": {"referrals": 1}},
        return_document=True
    )
    if not ref:
        # if referrer not in DB yet, create and then increment
        await users.insert_one({
            "_id": ref_id,
            "username": None,
            "first_name": None,
            "created_at": dt.datetime.utcnow(),
            "daily_date": (await today_ist()).isoformat(),
            "daily_count": 0,
            "premium_expiry": None,
            "referrals": 1,
            "reward_packs_awarded": 0,
            "referred_by": None,
        })
        ref = await users.find_one({"_id": ref_id})

    # compute reward packs
    total_refs = ref.get("referrals", 0)
    earned_packs = total_refs // REFERRALS_PER_REWARD
    already_awarded = ref.get("reward_packs_awarded", 0)
    if earned_packs > already_awarded:
        new_packs = earned_packs - already_awarded
        await extend_premium(ref_id, new_packs * PREMIUM_DAYS_PER_REWARD)
        await users.update_one(
            {"_id": ref_id},
            {"$set": {"reward_packs_awarded": earned_packs}}
        )

# ------------------- COMMANDS -------------------
def referral_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{bot_username}?start={user_id}"

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    doc = await get_or_create_user(u)

    # Handle deep-link referral: /start <ref_id>
    if context.args:
        try:
            ref_id = int(context.args[0])
            await handle_referral(doc, ref_id)
        except Exception:
            pass

    bot_user = await context.bot.get_me()
    prem = await is_premium(doc)
    doc = await ensure_daily_window(doc)
    remaining = "∞" if prem else max(0, FREE_DAILY_LIMIT - doc.get("daily_count", 0))

    text = (
        f"👋 Hi {u.first_name or 'there'}!\n"
        f"Paste any ad/shortened link and I’ll return a clean link.\n\n"
        f"🌐 Our Facebook Page: {FACEBOOK_PAGE}\n\n"
        f"🆓 Free: {FREE_DAILY_LIMIT} links/day\n"
        f"💎 Premium: Unlimited (1 day free per {REFERRALS_PER_REWARD} referrals)\n\n"
        f"🔗 Your referral link:\n{referral_link(bot_user.username, u.id)}\n\n"
        f"📊 Status: {'Premium' if prem else 'Free'} • Today remaining: {remaining}"
    )
    await update.message.reply_text(text, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 How to use:\n"
        "Send me any URL with ads/shorteners. I’ll follow redirects and remove tracking params.\n\n"
        "Commands:\n"
        "/start – Intro + referral link + FB page\n"
        "/me – Your status, usage, referrals\n"
        "/referral – Show your referral link\n"
        "/premium – Show premium expiry"
    )

async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    doc = await get_or_create_user(u)
    doc = await ensure_daily_window(doc)
    prem = await is_premium(doc)

    exp = doc.get("premium_expiry")
    exp_str = exp.isoformat(timespec="seconds") + "Z" if isinstance(exp, dt.datetime) else (exp or "—")
    remaining = "∞" if prem else max(0, FREE_DAILY_LIMIT - doc.get("daily_count", 0))

    bot_user = await context.bot.get_me()
    text = (
        f"👤 User: {u.id}\n"
        f"Plan: {'Premium' if prem else 'Free'}\n"
        f"Premium Expiry: {exp_str}\n"
        f"Today Used: {doc.get('daily_count', 0)}/{FREE_DAILY_LIMIT if not prem else '∞'}\n"
        f"Referrals: {doc.get('referrals', 0)}\n\n"
        f"🔗 Referral: {referral_link(bot_user.username, u.id)}"
    )
    await update.message.reply_text(text, disable_web_page_preview=True)

async def cmd_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await get_or_create_user(u)
    bot_user = await context.bot.get_me()
    link = referral_link(bot_user.username, u.id)
    await update.message.reply_text(f"🔗 Share this link with friends:\n{link}")

async def cmd_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    doc = await get_or_create_user(u)
    exp = doc.get("premium_expiry")
    if not await is_premium(doc):
        await update.message.reply_text("❌ You are not premium.\nRefer 10 friends to get 1 day premium.")
        return
    exp_str = exp.isoformat(timespec="seconds") + "Z" if isinstance(exp, dt.datetime) else (exp or "—")
    await update.message.reply_text(f"✅ Premium active.\nExpires: {exp_str}")

# ------------------- CLEAN HANDLER -------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user

    # Optional allowlist
    if ALLOWED_USERS and str(u.id) not in ALLOWED_USERS:
        await msg.reply_text("⛔ You are not allowed to use this bot.")
        return

    doc = await get_or_create_user(u)
    allowed = await check_daily_limit(doc)
    if not allowed:
        await msg.reply_text(
            f"⚠️ Daily limit reached ({FREE_DAILY_LIMIT}/{FREE_DAILY_LIMIT}).\n"
            f"Refer {REFERRALS_PER_REWARD} friends to get 1 day Premium (unlimited).\n"
            "Use /referral to get your link."
        )
        return

    text = msg.text or ""
    m = url_regex.search(text)
    if not m:
        await msg.reply_text("❗ Send a valid URL.")
        return

    raw_url = m.group(1).strip()
    try:
        await msg.chat.send_action("typing")
        cleaned = clean_url(raw_url)
        await increment_daily_if_needed(doc)
        await msg.reply_text(f"✅ Clean Link:\n{cleaned}", disable_web_page_preview=True)
    except Exception as e:
        log.exception("clean error: %s", e)
        await msg.reply_text("❌ Error while processing this link.")

# ------------------- MAIN -------------------
def main():
    if not TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN not set")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("me",    cmd_me))
    app.add_handler(CommandHandler("referral", cmd_referral))
    app.add_handler(CommandHandler("premium",  cmd_premium))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()