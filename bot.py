import os
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from handlers.leech import get_enhanced_handler
import asyncio
from threading import Thread
import http.server
import socketserver

# Configure detailed logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 🏥 NEW: Health check server for Koyeb
def start_health_server():
    """Start health check server so Koyeb knows bot is alive"""
    PORT = int(os.environ.get('PORT', 8000))
    
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            # Respond to GET health checks
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Terabox Bot: Healthy and Running!')
                
        def do_HEAD(self):
            # Respond to HEAD health checks (this fixes the 501 errors)
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
                
        def log_message(self, format, *args):
            # Suppress HTTP server logs to avoid spam
            pass
    
    try:
        with socketserver.TCPServer(("", PORT), HealthHandler) as httpd:
            logger.info(f"🏥 Health check server started on port {PORT}")
            httpd.serve_forever()
    except Exception as e:
        logger.error(f"❌ Health server error: {e}")

# Your existing start handler (keeping all your current code)
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
        "via @Terabox_leech_Pro_bot"
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

# Your existing debug handler (keeping all your current code)
async def debug_message_handler(update, context):
    """Debug handler to catch all messages"""
    user_id = update.effective_user.id
    message_text = update.message.text if update.message.text else "No text"
    
    logger.info(f"🔍 DEBUG: Message from user {user_id}: '{message_text}'")
    
    if message_text.startswith('/leech'):
        logger.info(f"🎯 LEECH command detected: '{message_text}'")
    else:
        logger.info(f"📝 Non-leech message: '{message_text}'")

# Your existing error handler (keeping all your current code)
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
    """Main function with comprehensive logging and health check server"""
    
    # 🏥 NEW: Start health check server in background thread
    logger.info("🏥 Starting health check server...")
    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Get bot token (your existing code)
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("❌ BOT_TOKEN not found in environment variables")
        return
    
    logger.info(f"🔑 Bot token found: {token[:10]}...")
    
    # Create application (your existing code)
    application = Application.builder().token(token).build()
    
    # Add handlers with logging (your existing code)
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
    
    # Start the bot (your existing code)
    logger.info("🚀 Starting Terabox Leech Pro Bot with debug logging and health checks...")
    
    try:
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"💥 Bot startup failed: {e}")

if __name__ == "__main__":
    main()
        
