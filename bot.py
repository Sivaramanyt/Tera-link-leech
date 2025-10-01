#!/usr/bin/env python3
import asyncio
import logging
import os
import sys
import tempfile
import fcntl
import time
import re
import json
import httpx
import psutil
from telegram.ext import Application, CommandHandler

try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 120 * 1024 * 1024
WDZONE_API = "https://wdzone-terabox-api.vercel.app/api"

class SimpleHealthServer:
    async def handle_request(self, reader, writer):
        try:
            await reader.read(1024)
            response = (
                "HTTP/1.1 200 OK
"
                "Content-Type: application/json
"
                "Connection: close

"
                '{"status": "healthy", "service": "terabox_bot_phase21"}'
            )
            writer.write(response.encode())
            await writer.drain()
            writer.close()
        except Exception as e:
            logger.warning(f"Health server error: {e}")

    async def start(self, port):
        server = await asyncio.start_server(self.handle_request, '0.0.0.0', port)
        logger.info(f"Health server started on port {port}")
        async with server:
            await server.serve_forever()

def ensure_single_instance():
    try:
        lock_file = os.path.join(tempfile.gettempdir(), 'terabox_bot_phase21.lock')
        lock_fd = open(lock_file, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd
    except:
        logger.error("Another instance is running")
        sys.exit(1)

def format_size(bytes_count):
    if not bytes_count:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} TB"

def parse_size_string(size_str):
    if not size_str:
        return None
    try:
        match = re.match(r'([0-9.]+)s*([KMGT]?B)', size_str.upper())
        if not match:
            return None
        number = float(match.group(1))
        unit = match.group(2)
        multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
        return int(number * multipliers.get(unit, 1))
    except:
        return None

def decode_response_content(response):
    try:
        if response.headers.get('content-encoding') == 'br' and HAS_BROTLI:
            try:
                return brotli.decompress(response.content).decode('utf-8')
            except Exception as e:
                logger.warning(f"Brotli decompression failed: {e}")
        return response.text
    except:
        for enc in ['utf-8', 'latin-1']:
            try:
                return response.content.decode(enc)
            except:
                continue
        return None

async def resolve_terabox_url(url: str):
    try:
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(WDZONE_API, params={"url": url})
            if response.status_code != 200:
                return None, None, None
            text_content = decode_response_content(response)
            if not text_content:
                return None, None, None
            data = json.loads(text_content)
            if data.get("✅ Status") != "Success":
                return None, None, None
            extracted_info = data.get("📜 Extracted Info")
            if not extracted_info:
                return None, None, None
            file_info = extracted_info[0] if isinstance(extracted_info, list) else extracted_info
            download_url = file_info.get("🔽 Direct Download Link")
            filename = file_info.get("📂 Title")
            size_str = file_info.get("📏 Size")
            if not download_url or not filename:
                return None, None, None
            file_size = parse_size_string(size_str)
            logger.info(f"Resolved: {filename} ({format_size(file_size) if file_size else 'unknown'})")
            return download_url, filename, file_size
    except Exception as e:
        logger.error(f"Resolve error: {e}")
        return None, None, None

async def download_file_phase21(url: str, filename: str, status_message, context, chat_id):
    try:
        fd, temp_path = tempfile.mkstemp(prefix="tb_p21_", suffix=f"_{filename}")
        os.close(fd)
        timeout = httpx.Timeout(600.0, connect=30.0)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Referer": "https://www.terabox.com/",
            "Origin": "https://www.terabox.com"
        }
        limits = httpx.Limits(max_keepalive_connections=0, max_connections=1)
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True, limits=limits, max_redirects=10) as client:
            try:
                head_response = await client.head(url)
                final_url = str(head_response.url)
            except Exception as redirect_error:
                logger.warning(f"Redirect check failed, using original URL: {redirect_error}")
                final_url = url
            async with client.stream("GET", final_url) as response:
                if response.status_code not in [200, 206]:
                    logger.error(f"Download failed: HTTP {response.status_code}")
                    logger.error(f"Response headers: {dict(response.headers)}")
                    return None
                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0
                start_time = time.time()
                last_update = 0
                with open(temp_path, "wb") as f:
                    async for chunk in response.aiter_bytes(256 * 1024):
                        if chunk:
                            f.write(chunk)
                            f.flush()
                            downloaded += len(chunk)
                            current_time = time.time()
                            if current_time - last_update >= 2:
                                elapsed = current_time - start_time
                                speed = downloaded / elapsed if elapsed > 0 else 0
                                progress = downloaded / total_size if total_size > 0 else 0
                                eta = (total_size - downloaded) / speed if speed > 0 and total_size > 0 else 0
                                bar_length = 22
                                filled = int(progress * bar_length)
                                bar = "█" * filled + "░" * (bar_length - filled)
                                try:
                                    await status_message.edit_text(
                                        f"🚀 Download Progress 🚀

"
                                        f"`{bar}` {progress*100:.1f}%
"
                                        f"Downloaded: {format_size(downloaded)}
"
                                        f"Total Size: {format_size(total_size) if total_size else 'Streaming'}
"
                                        f"Speed: {format_size(int(speed))}/s
"
                                        f"ETA: {eta:.0f}s"
                                    )
                                    last_update = current_time
                                except Exception as e:
                                    logger.warning(f"Progress update error: {e}")
        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            logger.info(f"Download completed: {format_size(os.path.getsize(temp_path))}")
            return temp_path
        logger.error("Download failed: empty or missing file")
        return None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None

async def start_handler(update, context):
    await update.message.reply_text(
        "🔥 Terabox Leech Pro Bot - Phase 2.1 🔥
"
        "Send: `/leech <terabox_link>`
"
        "120MB max size with redirect support
"
        "Real-time progress with streaming downloads
"
        "Memory optimized"
    )

async def debug_handler(update, context):
    mem = psutil.virtual_memory()
    await update.message.reply_text(
        f"🤖 Phase 2.1 Debug Info

Mem Available: {mem.available/(1024*1024):.1f}MB
"
        f"CPU Load: {psutil.cpu_percent()}%
"
        f"Brotli: {'Available' if HAS_BROTLI else 'Missing'}
"
        f"HTTPX Version: {httpx.__version__}"
    )

async def phase21_leech_handler(update, context):
    try:
        text = update.effective_message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(
                "**Usage:** `/leech <terabox_link>`
"
                "Supports up to 120MB with progress tracking
"
                "Redirect handling enabled"
            )
            return
        url = parts[1].strip()
        chat_id = update.effective_chat.id
        if not any(d in url.lower() for d in ["terabox", "1024tera"]):
            await update.message.reply_text("❌ Invalid Terabox link.")
            return
        status = await update.message.reply_text("Resolving Terabox link...")
        download_url, filename, file_size = await resolve_terabox_url(url)
        if not download_url:
            await status.edit_text("❌ Link resolution failed or expired link.")
            return
        if file_size and file_size > MAX_FILE_SIZE:
            await status.edit_text(f"⚠️ File too large ({format_size(file_size)}). Limit is 120MB.")
            return
        await status.edit_text(f"Downloading {filename} ({format_size(file_size) if file_size else 'unknown size'})...")
        start_time = time.time()
        temp_path = await download_file_phase21(download_url, filename, status, context, chat_id)
        if not temp_path:
            await status.edit_text("❌ Download failed or timed out.")
            return
        elapsed = time.time() - start_time
        actual_size = os.path.getsize(temp_path)
        avg_speed = actual_size / elapsed if elapsed > 0 else 0
        await status.edit_text(f"Download complete: {filename}
{format_size(actual_size)} in {elapsed:.1f}s
Speed: {format_size(int(avg_speed))}/s
Uploading...")
        try:
            with open(temp_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    caption=f"📁 {filename}
📏 {format_size(actual_size)}
⚡ {format_size(int(avg_speed))}/s
💎 via @Terabox_leech_pro_bot",
                    filename=filename,
                    read_timeout=300,
                    write_timeout=300
                )
            await status.delete()
        except Exception as e:
            await status.edit_text(f"❌ Upload failed: {str(e)[:100]}")
        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")
    except Exception as e:
        logger.error(f"Leech handler error: {e}")
        try:
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
        except:
            pass

async def error_handler(update, context):
    logger.error(f"Global error: {context.error}")

async def run_health_server():
    port = int(os.getenv('PORT', 8000))
    await SimpleHealthServer().start(port)

async def run_bot():
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("Missing BOT_TOKEN")
        sys.exit(1)
    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("leech", phase21_leech_handler))
    app.add_handler(CommandHandler("debug", debug_handler))
    app.add_error_handler(error_handler)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

async def main():
    try:
        ensure_single_instance()
        logger.info("Starting Terabox Bot Phase 2.1...")
        await asyncio.gather(run_health_server(), run_bot())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Startup error: {e}")
        sys.exit(1)
