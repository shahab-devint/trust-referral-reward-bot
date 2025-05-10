import logging
import uuid
import sqlite3
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import ChatInviteLink

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# SQLite database setup
DB_PATH = "bot_data.db"

def init_db():
    """Initialize SQLite database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            user_id TEXT PRIMARY KEY,
            referral_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invite_links (
            user_id TEXT PRIMARY KEY,
            link_id TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

async def debug_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log all incoming updates for debugging."""
    logger.info(f"Received update: {update}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command, including deep linking for referrals."""
    user_id = update.message.from_user.id
    logger.info(f"Start handler triggered by user {user_id}")
    
    # Check if the /start command includes a parameter (e.g., /start inviter_12345)
    if context.args:
        param = context.args[0]
        if param.startswith("inviter_"):
            try:
                inviter_id = int(param.split("_")[1])
                # Credit the inviter
                if inviter_id != user_id:  # Prevent self-referral
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR IGNORE INTO referrals (user_id, referral_count)
                        VALUES (?, 0)
                    """, (str(inviter_id),))
                    cursor.execute("""
                        UPDATE referrals SET referral_count = referral_count + 1
                        WHERE user_id = ?
                    """, (str(inviter_id),))
                    conn.commit()
                    cursor.execute("SELECT referral_count FROM referrals WHERE user_id = ?", (str(inviter_id),))
                    referral_count = cursor.fetchone()[0]
                    conn.close()
                    logger.info(f"User {inviter_id} invited user {user_id} via link. Total referrals: {referral_count}")
                    
                    # Check if the inviter reached 30 referrals
                    if referral_count == 30:
                        inviter = await context.bot.get_chat_member(GROUP_CHAT_ID, inviter_id)
                        congrats_message = (
                            f"🎉 تبریک میگم {inviter.user.first_name}! 🎉\n"
                            "تو ۳۰ تا از دوستات رو وارد گروه کردی تا پوست و موی بهتری داشته باشن!\n"
                            "لطفاً هدیه‌ت رو انتخاب کن و به ادمین گروه اطلاع بده تا برات ارسال کنه"
                        )
                        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=congrats_message)
                        # Send the predefined photo from URL
                        response = requests.get(PHOTO_PATH)
                        await context.bot.send_photo(chat_id=GROUP_CHAT_ID, photo=response.content)
            except Exception as e:
                logger.error(f"Error processing referral: {e}")
        await update.message.reply_text("خوش اومد! شما با لینک دعوت وارد این گروه شدی :)")
    else:
        await update.message.reply_text("درود! من تعداد نفراتی رو که با ما آشنا میکنی میشمرم! با /getlink لینک دعوتت رو دریافت کن و با /stats ببین چند نفر رو تا حالا معرفی کردی")

async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a unique invite link for the user."""
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    logger.info(f"Get_link handler triggered by user {user_id} in chat {chat_id}")
    
    try:
        # Generate a unique link ID
        link_id = str(uuid.uuid4()).replace("-", "")
        # Store the link ID in the database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO invite_links (user_id, link_id)
            VALUES (?, ?)
        """, (str(user_id), link_id))
        conn.commit()
        conn.close()
        
        # Create an invite link with a deep link parameter
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            name=f"Invite by {user_id}",
            creates_join_request=False,
            member_limit=1  # Single-use link for simplicity
        )
        # Append the deep link parameter
        deep_link = f"https://t.me{context.bot.username}?start=inviter_{user_id}"
        
        # Send the link to the user
        await update.message.reply_text(
            f"لینک اختصاصی شما: {deep_link}\n"
            f"هم میتونی خودت اد کنی و هم این لینک رو برای دوستات بفرستی"
        )
    except Exception as e:
        logger.error(f"Error generating invite link: {e}")
        await update.message.reply_text("ببخشید! نتونستم لینک بسازم. ادمین عیب یابی میکنه و درستش میکنه")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /stats command to show referral counts."""
    user_id = update.message.from_user.id
    logger.info(f"Stats handler triggered by user {user_id}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, referral_count FROM referrals WHERE referral_count > 0")
    referral_data = cursor.fetchall()
    conn.close()
    
    if not referral_data:
        await update.message.reply_text("فعلاً کسی از طرف شما نپیوسته!")
        return
    
    message = "تعداد دعوت‌ها:\n"
    for user_id, count in referral_data:
        user = await context.bot.get_chat_member(GROUP_CHAT_ID, int(user_id))
        message += f"{user.user.first_name} ({user_id}): {count} نفر\n"
    await update.message.reply_text(message)

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new members joining the group (direct additions)."""
    chat_id = update.message.chat_id
    logger.info(f"New_member handler triggered in chat {chat_id} with update: {update}")
    
    for member in update.message.new_chat_members:
        # Skip if the new member is the bot itself
        if member.id == context.bot.id:
            continue

        # Check if the update contains information about who added the member
        if update.message.from_user:
            inviter_id = update.message.from_user.id
            logger.info(f"Inviter ID: {inviter_id}, New member: {member.id}")
            # Credit the inviter for direct addition
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO referrals (user_id, referral_count)
                    VALUES (?, 0)
                """, (str(inviter_id),))
                cursor.execute("""
                    UPDATE referrals SET referral_count = referral_count + 1
                    WHERE user_id = ?
                """, (str(inviter_id),))
                conn.commit()
                cursor.execute("SELECT referral_count FROM referrals WHERE user_id = ?", (str(inviter_id),))
                referral_count = cursor.fetchone()[0]
                conn.close()
                
                logger.info(f"User {inviter_id} directly added a new member. Total referrals: {referral_count}")

                # Check if the inviter reached 30 referrals
                if referral_count == 30:
                    user = await context.bot.get_chat_member(chat_id, inviter_id)
                    congrats_message = (
                        f"🎉 تبریک میگم {user.user.first_name}! 🎉\n"
                        "تو ۳۰ تا از دوستات رو وارد گروه کردی تا پوست و موی بهتری داشته باشن!\n"
                        "لطفاً هدیه‌ت رو انتخاب کن و به ادمین گروه اطلاع بده تا برات ارسال کنه"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=congrats_message)
                    # Send the predefined photo from URL
                    response = requests.get(PHOTO_PATH)
                    await context.bot.send_photo(chat_id=chat_id, photo=response.content)
            except Exception as e:
                logger.error(f"Error processing direct addition: {e}")
        else:
            logger.warning(f"No inviter ID found for new member {member.id}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors caused by updates."""
    logger.warning(f"Update {update} caused error {context.error}")

def main():
    """Main function to run the bot."""
    # Initialize database
    init_db()
    
    # Replace with your new bot token from BotFather
    TOKEN = "YOUR_NEW_BOT_TOKEN"
    
    # Create the Application without JobQueue
    application = Application.builder().token(TOKEN).job_queue(None).build()
    
    # Add debug handler for all updates
    application.add_handler(MessageHandler(filters.ALL, debug_update), group=-1)
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getlink", get_link))
    application.add_handler(CommandHandler("stats", stats))
    
    # Add message handler for new members
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

# URL to the predefined photo
PHOTO_PATH = "https://s33.picofile.com/file/8484362042/Choose_Your_Gift.PNG"
# Group chat ID
GROUP_CHAT_ID = "-1001250582965"