import logging
import os
import asyncio
import threading
from telegram.ext import Application
from handlers.start import start_handler
from handlers.leech import leech_handler
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# HTTP server for health check
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthHandler)
    logger.info("Health server running on port 8000")
    server.serve_forever()

async def dummy_set_commands(app):
    # Minimal or empty async command setup for now
    pass

async def error_handler(update, context):
    logger.error(f"Exception while handling update: {context.error}")

def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN environment variable is not set.")
        return

    # Start HTTP health server in background thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    logger.info("Starting Terabox Leech Bot with leech handler and error handling...")
    app = Application.builder().token(bot_token).build()

    # Register your handlers
    app.add_handler(start_handler)
    app.add_handler(leech_handler)

    # Register error handler
    app.add_error_handler(error_handler)

    # Run minimal async setup if needed
    asyncio.run(dummy_set_commands(app))

    # Run the bot synchronously (internally manages event loop)
    app.run_polling()

if __name__ == "__main__":
    main()
    
