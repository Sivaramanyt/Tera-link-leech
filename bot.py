import os
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from handlers.leech import get_enhanced_handler
import asyncio

# Configure detailed logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start_handler(update, context):
    """Handle /start command with detailed logging"""
    logger.info(f"📨 START command received from user {update.effective_user.id}")
    
    welcome_msg = (
        "🚀 <b>Terabox Leech Pro Bot</b>\n\n"
        "📋 <b>Commands:</b>\n"
        "• /start - Show this help\n"
        "• /leech &lt;terabox_link&gt; - Download and send file\n\n"
        "📝 <b>Usage:</b>\n"
        "Send me a Terabox share link and I'll download it for you!\n\n"
        "⚡ <b>Example:</b>\n"
        "<code>/leech https://teraboxurl.com/s/1abc...</code>\n\n"
        "via @Terabox_leech_pro_bot"
    )
    
    try:
        await update.message.reply_text(
            welcome_msg,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        logger.info(f"✅ START response sent successfully")
    except Exception as e:
        logger.error(f"❌ START response failed: {e}")

async def debug_message_handler(update, context):
    """Debug handler to catch all messages"""
    user_id = update.effective_user.id
    message_text = update.message.text if update.message.text else "No text"
    
    logger.info(f"🔍 DEBUG: Message from user {user_id}: '{message_text}'")
    
    if message_text.startswith('/leech'):
        logger.info(f"🎯 LEECH command detected: '{message_text}'")
    else:
        logger.info(f"📝 Non-leech message: '{message_text}'")

async def error_handler(update, context):
    """Handle all errors with detailed logging"""
    logger.error(f"❌ ERROR occurred: {context.error}")
    logger.error(f"❌ Update that caused error: {update}")
    
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                f"❌ An error occurred: {str(context.error)}"
            )
        except Exception as e:
            logger.error(f"❌ Could not send error message: {e}")

def main():
    """Main function with comprehensive logging"""
    # Get bot token
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("❌ BOT_TOKEN not found in environment variables")
        return
    
    logger.info(f"🔑 Bot token found: {token[:10]}...")
    
    # Create application
    application = Application.builder().token(token).build()
    
    # Add handlers with logging
    logger.info("📝 Adding handlers...")
    
    # Start handler
    application.add_handler(CommandHandler("start", start_handler))
    logger.info("✅ START handler added")
    
    # Leech handler  
    leech_handler = get_enhanced_handler()
    application.add_handler(leech_handler)
    logger.info("✅ LEECH handler added")
    
    # Debug message handler (catches all messages)
    application.add_handler(MessageHandler(filters.TEXT, debug_message_handler))
    logger.info("✅ DEBUG message handler added")
    
    # Error handler
    application.add_error_handler(error_handler)
    logger.info("✅ ERROR handler added")
    
    # Start the bot
    logger.info("🚀 Starting Terabox Leech Pro Bot with debug logging...")
    
    try:
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"💥 Bot startup failed: {e}")

if __name__ == "__main__":
    main()
    
