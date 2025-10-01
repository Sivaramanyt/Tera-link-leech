#!/usr/bin/env python3
# bot.py - PHASE 2: REAL DOWNLOADS + 120MB + STREAMING

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

# Try brotli import
try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False
    print("⚠️ WARNING: brotli not available - some downloads may fail")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Constants
MAX_FILE_SIZE = 120 * 1024 * 1024  # 120MB
WDZONE_API = "https://wdzone-terabox-api.vercel.app/api"

class SimpleHealthServer:
    async def handle_request(self, reader, writer):
        try:
            request = await reader.read(1024)
            response_body = '{"status": "healthy", "service": "terabox_bot_phase2"}'
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                "Connection: close\r\n\r\n"
                f"{response_body}"
            )
            writer.write(response.encode('utf-8'))
            await writer.drain()
            writer.close()
        except Exception as e:
            logger.warning(f"Health server error: {e}")
    
    async def start(self, port):
        server = await asyncio.start_server(self.handle_request, '0.0.0.0', port)
        logger.info(f"🏥 Phase 2 health server started on port {port}")
        async with server:
            await server.serve_forever()

def ensure_single_instance():
    try:
        lock_file = os.path.join(tempfile.gettempdir(), 'terabox_bot_phase2.lock')
        lock_fd = open(lock_file, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        logger.info(f"🔒 Phase 2 lock acquired: PID {os.getpid()}")
        return lock_fd
    except (IOError, OSError):
        logger.error("❌ Another Phase 2 instance running!")
        sys.exit(1)

def format_size(bytes_count):
    """Format bytes to human readable"""
    if not bytes_count:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} TB"

def parse_size_string(size_str):
    """Parse size strings like '6.34 MB' into bytes"""
    if not size_str:
        return None
    
    try:
        size_str = size_str.strip().upper()
        match = re.match(r'([0-9.]+)\s*([KMGT]?B)', size_str)
        if not match:
            return None
        
        number = float(match.group(1))
        unit = match.group(2)
        
        multipliers = {
            'B': 1,
            'KB': 1024,
            'MB': 1024**2,
            'GB': 1024**3,
            'TB': 1024**4
        }
        
        return int(number * multipliers.get(unit, 1))
        
    except Exception as e:
        logger.warning(f"⚠️ Size parsing error: {e}")
        return None

def decode_response_content(response):
    """Safely decode response content handling Brotli, Gzip, and plain text"""
    try:
        content_encoding = response.headers.get('content-encoding', '').lower()
        raw_content = response.content
        
        # Handle Brotli compression
        if content_encoding == 'br' and HAS_BROTLI:
            try:
                decompressed = brotli.decompress(raw_content)
                return decompressed.decode('utf-8')
            except Exception as e:
                logger.warning(f"⚠️ Brotli decompression failed: {e}")
        
        # Try direct decoding
        try:
            return response.text
        except Exception:
            pass
        
        # Fallback to raw decode
        for encoding in ['utf-8', 'latin-1']:
            try:
                return raw_content.decode(encoding)
            except UnicodeDecodeError:
                continue
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Content decoding error: {e}")
        return None

async def resolve_terabox_url(url: str):
    """Phase 2: Real Terabox URL resolution"""
    try:
        logger.info(f"🌐 Phase 2 resolving: {url}")
        
        timeout = httpx.Timeout(30.0, connect=10.0)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*"
        }
        
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.get(WDZONE_API, params={"url": url})
            
            logger.info(f"📡 Phase 2 API Response: {response.status_code}")
            
            if response.status_code != 200:
                return None, None, None
            
            # Decode content
            text_content = decode_response_content(response)
            if not text_content:
                logger.error(f"❌ Could not decode response")
                return None, None, None
            
            # Parse JSON
            try:
                data = json.loads(text_content)
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON parsing failed: {e}")
                return None, None, None
            
            # Check status
            status = data.get("✅ Status") or data.get("status")
            if status != "Success":
                logger.error(f"❌ API status not success: {status}")
                return None, None, None
            
            # Extract info
            extracted_info = data.get("📜 Extracted Info")
            if not extracted_info:
                return None, None, None
            
            if isinstance(extracted_info, list) and len(extracted_info) > 0:
                file_info = extracted_info[0]
            elif isinstance(extracted_info, dict):
                file_info = extracted_info
            else:
                return None, None, None
            
            # Get file details
            download_url = file_info.get("🔽 Direct Download Link")
            filename = file_info.get("📂 Title")
            size_str = file_info.get("📏 Size")
            
            if not download_url or not filename:
                return None, None, None
            
            file_size = parse_size_string(size_str)
            
            logger.info(f"✅ Phase 2 resolved: {filename} ({format_size(file_size) if file_size else 'unknown'})")
            return download_url, filename, file_size
            
    except Exception as e:
        logger.error(f"❌ Phase 2 resolve error: {e}")
        return None, None, None

async def download_file_phase2(url: str, filename: str, status_message, context, chat_id):
    """Phase 2: Real file download with streaming progress"""
    try:
        logger.info(f"⬇️ Phase 2 downloading: {filename}")
        
        # Create temp file
        fd, temp_path = tempfile.mkstemp(prefix="tb_p2_", suffix=f"_{filename}")
        os.close(fd)
        
        timeout = httpx.Timeout(600.0, connect=30.0)  # 10 minute download timeout
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    logger.error(f"❌ Phase 2 download failed: HTTP {response.status_code}")
                    return None
                
                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0
                start_time = time.time()
                last_update = 0
                
                logger.info(f"📦 Phase 2 starting download: {format_size(total_size)}")
                
                with open(temp_path, "wb") as f:
                    async for chunk in response.aiter_bytes(512 * 1024):  # 512KB chunks for memory efficiency
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            current_time = time.time()
                            
                            # Update progress every 3 seconds
                            if current_time - last_update >= 3 and total_size > 0:
                                elapsed = current_time - start_time
                                speed = downloaded / elapsed if elapsed > 0 else 0
                                progress = downloaded / total_size
                                eta = (total_size - downloaded) / speed if speed > 0 else 0
                                
                                # Progress bar
                                bar_length = 22
                                filled = int(progress * bar_length)
                                bar = "█" * filled + "░" * (bar_length - filled)
                                
                                # Memory info
                                memory = psutil.virtual_memory()
                                memory_mb = memory.available / (1024 * 1024)
                                
                                try:
                                    await status_message.edit_text(
                                        f"🚀 **PHASE 2 ENHANCED DOWNLOAD** 🚀\n\n"
                                        f"📊 **Progress:** `{bar}` {progress*100:.1f}%\n\n"
                                        f"📥 **Downloaded:** {format_size(downloaded)}\n"
                                        f"📏 **Total Size:** {format_size(total_size)}\n"
                                        f"⚡ **Speed:** {format_size(int(speed))}/s\n"
                                        f"⏱️ **ETA:** {eta:.0f}s\n"
                                        f"🧠 **Memory:** {memory_mb:.0f}MB free\n"
                                        f"🎯 **Tech:** 120MB optimized streaming"
                                    )
                                    last_update = current_time
                                except Exception as e:
                                    logger.warning(f"⚠️ Progress update error: {e}")
        
        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            final_size = os.path.getsize(temp_path)
            logger.info(f"✅ Phase 2 download completed: {format_size(final_size)}")
            return temp_path
        else:
            logger.error(f"❌ Phase 2 download failed: empty or missing file")
            return None
        
    except Exception as e:
        logger.error(f"❌ Phase 2 download error: {e}")
        return None

# Handler functions
async def start_handler(update, context):
    await update.message.reply_text(
        "🔥 **Terabox Leech Pro Bot - Phase 2** 🔥\n\n"
        "Send: `/leech <terabox_link>`\n\n"
        "**🚀 Phase 2 Features:**\n"
        "✅ **Real downloads** with wdzone API\n"
        "✅ **120MB limit** for maximum speed\n"
        "✅ **Streaming progress** with memory monitoring\n"
        "✅ **Brotli decompression** support\n"
        "✅ **Ultra-fast processing** (1-3 MB/s)\n\n"
        "**Status:** ✅ Phase 2 Online\n"
        "**Version:** Enhanced Real Downloads"
    )

async def debug_handler(update, context):
    memory = psutil.virtual_memory()
    await update.message.reply_text(
        f"🤖 **Phase 2 Debug Info** 🤖\n\n"
        f"🧠 **Memory:** {memory.available/(1024*1024):.1f}MB available\n"
        f"📊 **CPU:** {psutil.cpu_percent()}%\n"
        f"🔧 **HTTPx:** {httpx.__version__}\n"
        f"🗜️ **Brotli:** {'✅ Available' if HAS_BROTLI else '❌ Missing'}\n"
        f"📦 **Packages:** 4 enhanced packages\n"
        f"🎯 **Phase:** 2 (Real Downloads)"
    )

async def phase2_leech_handler(update, context):
    """Phase 2: Real enhanced leech with full download functionality"""
    try:
        text = update.effective_message.text or ""
        parts = text.split(maxsplit=1)
        
        if len(parts) < 2:
            await update.message.reply_text(
                "**🔥 Phase 2 Enhanced Terabox Leech 🔥**\n\n"
                "**Usage:** `/leech <terabox_link>`\n\n"
                "**🚀 Phase 2 Features:**\n"
                "✅ **Real downloads** up to 120MB\n"
                "✅ **1-3 MB/s** download speeds\n"
                "✅ **Streaming progress** tracking\n"
                "✅ **Memory-optimized** processing\n"
                "✅ **Brotli decompression** support\n\n"
                "**Example:**\n"
                "`/leech https://terabox.com/s/1abc...`"
            )
            return
        
        url = parts[1].strip()
        chat_id = update.effective_chat.id
        
        # Validate URL
        if not any(domain in url.lower() for domain in ["terabox", "1024tera"]):
            await update.message.reply_text("❌ Please provide a valid Terabox link.")
            return
        
        # Start processing
        status = await update.message.reply_text("🔍 **Phase 2: Resolving Terabox link...**")
        
        # Step 1: Resolve URL
        download_url, filename, file_size = await resolve_terabox_url(url)
        
        if not download_url:
            await status.edit_text(
                "❌ **Phase 2 Resolution Failed**\n\n"
                "🔗 Link expired, invalid, or server error\n"
                "💡 Please get a fresh link from Terabox"
            )
            return
        
        # Step 2: Check file size (120MB limit)
        if file_size and file_size > MAX_FILE_SIZE:
            await status.edit_text(
                f"⚖️ **Phase 2 File Size Check**\n\n"
                f"📂 **File:** {filename}\n"
                f"📏 **Size:** {format_size(file_size)}\n"
                f"🚫 **Limit:** 120MB\n\n"
                f"🚀 **Why 120MB in Phase 2?**\n"
                f"• **Maximum speed:** 1-3 MB/s downloads\n"
                f"• **Memory-safe:** Streaming technology\n"
                f"• **Optimal balance:** Speed vs reliability\n"
                f"• **Free tier optimized:** No OOM crashes"
            )
            return
        
        # Step 3: Show file info
        await status.edit_text(
            f"📁 **Phase 2 File Information**\n\n"
            f"📂 **Name:** {filename}\n"
            f"📏 **Size:** {format_size(file_size) if file_size else 'Detecting...'}\n"
            f"🚀 **Expected Speed:** {'1-3 MB/s' if file_size and file_size > 50*1024*1024 else '500KB-1MB/s'}\n"
            f"🎯 **Technology:** Phase 2 streaming\n\n"
            f"⬇️ **Starting Phase 2 enhanced download...**"
        )
        
        # Step 4: Download with streaming progress
        download_start = time.time()
        temp_path = await download_file_phase2(download_url, filename, status, context, chat_id)
        
        if not temp_path:
            await status.edit_text(
                "❌ **Phase 2 Download Failed**\n\n"
                "🌐 Server error, timeout, or connection issue\n"
                "🔄 Please try again - servers may be unstable"
            )
            return
        
        download_time = time.time() - download_start
        actual_size = os.path.getsize(temp_path)
        avg_speed = actual_size / download_time if download_time > 0 else 0
        
        # Step 5: Upload to Telegram
        await status.edit_text(
            f"✅ **Phase 2 Download Complete!**\n\n"
            f"📁 **Name:** {filename}\n"
            f"📏 **Size:** {format_size(actual_size)}\n"
            f"⏱️ **Time:** {download_time:.1f}s\n"
            f"⚡ **Speed:** {format_size(int(avg_speed))}/s\n\n"
            f"📤 **Starting streaming upload...**"
        )
        
        # Memory-optimized upload
        try:
            upload_start = time.time()
            
            with open(temp_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    caption=f"📁 **{filename}**\n📏 **{format_size(actual_size)}**\n⚡ **{format_size(int(avg_speed))}/s**\n\n💎 **Phase 2** via @Terabox_leech_pro_bot",
                    filename=filename,
                    read_timeout=300,
                    write_timeout=300
                )
            
            upload_time = time.time() - upload_start
            total_time = time.time() - download_start
            
            # Success cleanup
            await status.delete()
            
            logger.info(f"✅ Phase 2 leech completed: {filename} in {total_time:.1f}s total")
            
        except Exception as upload_error:
            logger.error(f"❌ Phase 2 upload error: {upload_error}")
            await status.edit_text(
                f"❌ **Phase 2 Upload Failed**\n\n"
                f"📁 **Downloaded:** {filename}\n"
                f"📏 **Size:** {format_size(actual_size)}\n"
                f"❌ **Upload Error:** {str(upload_error)[:100]}\n\n"
                f"💡 File downloaded successfully but upload failed"
            )
        
        # Cleanup temp file
        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
                logger.info(f"🧹 Phase 2 cleanup completed")
        except Exception as e:
            logger.warning(f"⚠️ Phase 2 cleanup error: {e}")
            
    except Exception as e:
        logger.error(f"❌ Phase 2 leech error: {e}")
        try:
            await update.message.reply_text(f"❌ **Phase 2 Error**\n\n``````")
        except:
            pass

async def error_handler(update, context):
    logger.error(f"❌ Phase 2 ERROR: {context.error}")

async def run_health_server():
    port = int(os.getenv('PORT', 8000))
    health_server = SimpleHealthServer()
    await health_server.start(port)

async def run_bot():
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("❌ BOT_TOKEN not found!")
        sys.exit(1)
    
    logger.info(f"🔑 Phase 2 bot token: {bot_token[:10]}...")
    
    application = Application.builder().token(bot_token).build()
    
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("leech", phase2_leech_handler))
    application.add_handler(CommandHandler("debug", debug_handler))
    application.add_error_handler(error_handler)
    
    logger.info("📝 Phase 2 handlers added successfully")
    
    await application.initialize()
    await application.start()
    
    logger.info("🚀 Starting Phase 2 enhanced polling...")
    await application.updater.start_polling(drop_pending_updates=True)
    
    logger.info("✅ Phase 2 bot started successfully!")
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Phase 2 bot stopped")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

async def main():
    try:
        lock_fd = ensure_single_instance()
        logger.info("🚀 Starting PHASE 2 Enhanced Terabox Bot with Real Downloads...")
        
        await asyncio.gather(
            run_health_server(),
            run_bot()
        )
        
    except Exception as e:
        logger.error(f"❌ Phase 2 fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Phase 2 stopped")
    except Exception as e:
        logger.error(f"❌ Phase 2 startup error: {e}")
        sys.exit(1)
        
