# handlers/leech.py

import os
import time
import asyncio
import tempfile
import subprocess
import logging
import gc
import psutil
from mimetypes import guess_type
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.error import NetworkError, TimedOut, RetryAfter
from services.terabox import get_resolver, cleanup_resolver
from services.downloader import fetch_to_temp

# Configure logging
logger = logging.getLogger(__name__)

# ---------- Memory Management ----------
class MemoryManager:
    """Memory management utilities for free tier hosting"""
    
    @staticmethod
    async def get_memory_info() -> dict:
        """Get current memory usage information"""
        try:
            memory = psutil.virtual_memory()
            return {
                'total': memory.total / (1024 * 1024),
                'available': memory.available / (1024 * 1024),
                'used': memory.used / (1024 * 1024),
                'percent': memory.percent
            }
        except Exception as e:
            logger.warning(f"Failed to get memory info: {e}")
            return {'available': 200}  # Default safe value
    
    @staticmethod
    async def cleanup_memory():
        """Force garbage collection and memory cleanup"""
        try:
            gc.collect()
            await asyncio.sleep(0.1)  # Brief pause for cleanup
            logger.debug("🧠 Memory cleanup performed")
        except Exception as e:
            logger.warning(f"Memory cleanup failed: {e}")
    
    @staticmethod
    def check_memory_threshold(required_mb: float = 150) -> bool:
        """Check if we have enough memory for operation"""
        try:
            available = psutil.virtual_memory().available / (1024 * 1024)
            return available >= required_mb
        except:
            return True  # Default to allowing operation

# ---------- Formatting (Enhanced with Memory Info) ----------
def _fmt_size(n: int | None) -> str:
    if n is None:
        return "unknown"
    f = float(n)
    for u in ["B","KB","MB","GB","TB"]:
        if f < 1024:
            return f"{f:.2f} {u}"
        f /= 1024
    return f"{f:.2f} PB"

def _dot_bar(p: float, width: int = 20) -> str:
    p = max(0.0, min(1.0, p))
    filled = int(round(p * width))
    return "●" * filled + "○" * (width - filled)

def _fmt_eta(sec: float) -> str:
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m}m{s}s"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"

# ---------- Caption/footer ----------
BOT_FOOTER = "via @Terabox_leech_pro_bot"

def _with_footer(text: str) -> str:
    if not text:
        return BOT_FOOTER
    if BOT_FOOTER.lower() in text.lower():
        return text
    return f"{text}\n{BOT_FOOTER}"

# ---------- ffmpeg helpers (optional) ----------
def _probe_duration_seconds(path: str) -> int | None:
    try:
        out = subprocess.check_output(
            ["ffprobe","-v","error","-show_entries","format=duration","-of","default=nk=1:nw=1", path],
            stderr=subprocess.STDOUT, text=True
        ).strip()
        if out:
            return int(float(out))
    except Exception:
        return None
    return None

def _make_video_thumb(path: str) -> str | None:
    try:
        fd, thumb = tempfile.mkstemp(prefix="tb_thumb_", suffix=".jpg")
        os.close(fd)
        subprocess.check_call(
            ["ffmpeg","-y","-ss","3","-i",path,"-vframes","1","-vf","scale=720:-1","-q:v","3", thumb],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return thumb if os.path.exists(thumb) else None
    except Exception:
        return None

# ---------- Enhanced Media Sender with Memory Management ----------
async def _send_media_optimized(context: ContextTypes.DEFAULT_TYPE, chat_id: int, path: str, filename: str):
    """Enhanced media sender with memory optimization for free tier hosting"""
    logger.info(f"📤 Starting optimized media upload: {filename} to chat {chat_id}")
    
    # Get file information
    file_size = os.path.getsize(path)
    mime, _ = guess_type(filename)
    ext = (os.path.splitext(filename)[1] or "").lower()
    caption = _with_footer(f"📄 Name: {filename}\n📏 Size: {_fmt_size(file_size)}")
    
    # Memory check before upload
    memory_info = await MemoryManager.get_memory_info()
    available_mb = memory_info.get('available', 0)
    logger.info(f"🧠 Pre-upload memory: {available_mb:.1f}MB available, file size: {_fmt_size(file_size)}")
    
    # Force memory cleanup
    await MemoryManager.cleanup_memory()
    
    # Determine upload strategy based on file size and available memory
    large_file_threshold = 50 * 1024 * 1024  # 50MB
    memory_threshold = 150  # MB
    
    upload_as_document = (
        file_size > large_file_threshold or 
        available_mb < memory_threshold or
        not MemoryManager.check_memory_threshold()
    )
    
    # Enhanced timeout calculation
    timeout_seconds = min(300, max(60, file_size // (1024 * 1024) * 10))
    
    duration = None
    thumb = None
    
    try:
        # Only generate thumbnails for smaller files to save memory
        if not upload_as_document and file_size < large_file_threshold:
            if ext in (".mp4",".mov",".m4v",".mkv") or (mime and mime.startswith("video/")):
                try:
                    duration = _probe_duration_seconds(path)
                    thumb = _make_video_thumb(path)
                    logger.info(f"🎬 Video metadata - Duration: {duration}s, Thumb: {thumb is not None}")
                except Exception as e:
                    logger.warning(f"⚠️ Media probe error (continuing without metadata): {e}")
        
        # Upload with memory-optimized strategy
        if upload_as_document:
            logger.info(f"📄 Uploading as document (memory-optimized)")
            
            with open(path, "rb") as file:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=file,
                    filename=filename,
                    caption=caption,
                    read_timeout=timeout_seconds,
                    write_timeout=timeout_seconds,
                    connect_timeout=60,
                    thumbnail=open(thumb, "rb") if thumb else None,
                )
            logger.info(f"✅ Document uploaded successfully")
            
        else:
            # Try smart upload based on file type for smaller files
            try:
                if (mime and mime.startswith("video/")) or ext in (".mp4", ".mov", ".m4v", ".mkv"):
                    logger.info(f"📹 Uploading as video...")
                    
                    with open(path, "rb") as file:
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=file,
                            filename=filename,
                            caption=caption,
                            supports_streaming=True,
                            duration=duration if duration else None,
                            width=1280,
                            height=720,
                            read_timeout=timeout_seconds,
                            write_timeout=timeout_seconds,
                            connect_timeout=60,
                            thumbnail=open(thumb, "rb") if thumb else None,
                        )
                    logger.info(f"✅ Video uploaded successfully")
                
                elif (mime and mime.startswith("audio/")) or ext in (".mp3",".m4a",".aac",".flac",".ogg",".opus"):
                    logger.info(f"🎵 Uploading as audio...")
                    
                    with open(path, "rb") as file:
                        await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=file,
                            filename=filename,
                            caption=caption,
                            duration=duration if duration else None,
                            read_timeout=timeout_seconds,
                            write_timeout=timeout_seconds,
                            connect_timeout=60,
                            thumbnail=open(thumb, "rb") if thumb else None,
                        )
                    logger.info(f"✅ Audio uploaded successfully")
                
                elif (mime and mime.startswith("image/")) or ext in (".jpg",".jpeg",".png",".webp"):
                    logger.info(f"🖼️ Uploading as photo...")
                    
                    with open(path, "rb") as file:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=file,
                            filename=filename,
                            caption=caption,
                            read_timeout=timeout_seconds,
                            write_timeout=timeout_seconds,
                            connect_timeout=60,
                        )
                    logger.info(f"✅ Photo uploaded successfully")
                
                else:
                    logger.info(f"📄 Uploading as document...")
                    
                    with open(path, "rb") as file:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=file,
                            filename=filename,
                            caption=caption,
                            read_timeout=timeout_seconds,
                            write_timeout=timeout_seconds,
                            connect_timeout=60,
                            thumbnail=open(thumb, "rb") if thumb else None,
                        )
                    logger.info(f"✅ Document uploaded successfully")
                    
            except Exception as upload_error:
                logger.warning(f"⚠️ Primary upload failed, fallback to document: {upload_error}")
                
                # Fallback to document upload
                with open(path, "rb") as file:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=file,
                        filename=filename,
                        caption=caption,
                        read_timeout=timeout_seconds,
                        write_timeout=timeout_seconds,
                        connect_timeout=60,
                    )
                logger.info(f"✅ Fallback document upload successful")
        
        # Post-upload cleanup
        await MemoryManager.cleanup_memory()
        return True
        
    except (NetworkError, TimedOut) as network_error:
        logger.error(f"❌ Network error during upload: {network_error}")
        return False
        
    except RetryAfter as retry_error:
        logger.warning(f"⏳ Rate limited, need to wait {retry_error.retry_after} seconds")
        return False
        
    except Exception as e:
        logger.error(f"❌ Upload failed with error: {e}")
        return False
        
    finally:
        # Cleanup thumbnail file
        try:
            if thumb and os.path.exists(thumb):
                os.remove(thumb)
                logger.debug(f"🗑️ Thumbnail cleaned up")
        except Exception as e:
            logger.warning(f"⚠️ Thumbnail cleanup error: {e}")

# ---------- File Size Checker ----------
def check_file_size_limit(file_size: int, max_size: int = 80 * 1024 * 1024) -> tuple[bool, str]:
    """Check if file size is within limits for free tier hosting"""
    if file_size > max_size:
        return False, f"File size {_fmt_size(file_size)} exceeds limit of {_fmt_size(max_size)}"
    return True, ""
# ---------- Enhanced Handler with Memory Management ----------
async def leech_handler_v2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # COMPREHENSIVE DEBUG LOGGING
    logger.info(f"🎯 ===== LEECH HANDLER CALLED =====")
    logger.info(f"🎯 User ID: {update.effective_user.id}")
    logger.info(f"🎯 Chat ID: {update.effective_chat.id}")
    logger.info(f"🎯 Message text: '{update.effective_message.text}'")
    logger.info(f"🎯 Message type: {type(update.effective_message.text)}")
    
    # Initial memory check
    memory_info = await MemoryManager.get_memory_info()
    logger.info(f"🧠 Initial memory: {memory_info.get('available', 0):.1f}MB available")
    
    chat_id = update.effective_chat.id
    text = update.effective_message.text or ""
    parts = text.split(maxsplit=1)
    logger.info(f"🎯 Text parts: {parts}")
    logger.info(f"🎯 Parts length: {len(parts)}")
    
    if len(parts) < 2:
        logger.warning(f"⚠️ Invalid command format - missing URL")
        try:
            await context.bot.send_message(chat_id, "❌ Usage: /leech <terabox_link>")
            logger.info(f"✅ Usage message sent")
        except Exception as e:
            logger.error(f"❌ Failed to send usage message: {e}")
        return
    
    share_url = parts[1].replace("\\", "/").strip()
    logger.info(f"🔗 Processing URL: {share_url}")
    
    # Send initial status message
    try:
        status = await context.bot.send_message(
            chat_id, 
            f"🔎 Resolving Terabox link...\n🧠 Memory: {memory_info.get('available', 0):.0f}MB available"
        )
        logger.info(f"✅ Status message sent - ID: {status.message_id}")
    except Exception as e:
        logger.error(f"❌ Failed to send status message: {e}")
        return
    
    try:
        # Memory cleanup before resolution
        await MemoryManager.cleanup_memory()
        
        # Get resolver instance with comprehensive logging
        logger.info(f"🔧 Getting resolver instance...")
        resolver = await get_resolver()
        logger.info(f"✅ Resolver instance obtained")
        
        logger.info(f"🌐 Starting URL resolution...")
        meta = await resolver.resolve(share_url)
        logger.info(f"✅ URL resolved successfully: {meta.name}, {meta.size} bytes")
        
    except Exception as e:
        logger.error(f"❌ Resolution error: {e}")
        logger.error(f"❌ Error type: {type(e)}")
        
        error_msg = str(e)
        if "HTTP 400" in error_msg or "400" in error_msg or "expired" in error_msg.lower():
            response_text = "❌ Link resolution failed: Link expired or invalid. Please get a fresh link from Terabox."
        elif "RuntimeError" in error_msg or "Future" in error_msg:
            response_text = "❌ Resolver error: Service temporarily unavailable. Please try again in a moment."
        elif "timeout" in error_msg.lower():
            response_text = "❌ Request timeout: Terabox servers are slow. Please try again later."
        elif "null" in error_msg.lower() or "no extracted info" in error_msg.lower():
            response_text = "❌ Link expired or invalid. Please get a fresh link from Terabox."
        else:
            response_text = f"❌ Failed to resolve link: {error_msg}"
        
        try:
            await status.edit_text(response_text)
            logger.info(f"✅ Error message sent to user")
        except Exception as edit_error:
            logger.error(f"❌ Failed to edit status message: {edit_error}")
        return
    
    title = meta.name or "file"
    total = meta.size
    logger.info(f"📝 File details - Name: {title}, Size: {_fmt_size(total)}")
    
    # File size check for free tier
    if total:
        size_ok, size_error = check_file_size_limit(total)
        if not size_ok:
            try:
                await status.edit_text(
                    f"❌ **File Too Large for Free Tier**\n\n"
                    f"📂 **Name:** {title}\n"
                    f"📏 **Size:** {_fmt_size(total)}\n"
                    f"⚠️ **Limit:** 80MB for free tier hosting\n\n"
                    f"**Solutions:**\n"
                    f"• Try a smaller file\n"
                    f"• Use premium hosting for larger files\n"
                    f"• File compression may help"
                )
            except Exception as e:
                logger.error(f"❌ Failed to send size limit message: {e}")
            return
    
    try:
        await status.edit_text(
            f"📝 **File Information**\n\n"
            f"📂 **Name:** {title}\n"
            f"🗂️ **Size:** {_fmt_size(total)}\n"
            f"📁 **Total Files:** 1\n"
            f"🧠 **Memory:** {memory_info.get('available', 0):.0f}MB available"
        )
        logger.info(f"✅ File info sent to user")
    except Exception as e:
        logger.error(f"❌ Failed to update status with file info: {e}")
    
    start = time.time()
    running = True
    bytes_done = 0
    
    def _on_progress(done, total_hint):
        nonlocal bytes_done, total
        bytes_done = int(done)
        if not total and total_hint:
            try:
                total = int(total_hint)
            except Exception:
                pass
        
        # Log progress occasionally
        if bytes_done % (1024 * 1024 * 10) == 0:  # Every 10MB
            logger.info(f"📊 Progress: {_fmt_size(bytes_done)} / {_fmt_size(total)}")
    
    async def progress_loop(message_id: int):
        loop_count = 0
        while running:
            try:
                loop_count += 1
                done = bytes_done
                p = (done / total) if total and total > 0 else 0.0
                bar = _dot_bar(p, 20)
                elapsed = max(0.001, time.time() - start)
                speed = done / elapsed
                eta = (total - done) / speed if total and speed > 0 else 0
                
                # Get current memory for progress display
                current_memory = await MemoryManager.get_memory_info()
                memory_mb = current_memory.get('available', 0)
                
                text = (
                    f"⏩ 📥 {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"{bar} {p*100:0.2f}%\n"
                    f"📦 Processed: {_fmt_size(done)}\n"
                    f"🗂️ Size: {_fmt_size(total)}\n"
                    f"🚀 Speed: {_fmt_size(int(speed))}/s\n"
                    f"⏳ ETA: {_fmt_eta(eta)}\n"
                    f"🧠 Memory: {memory_mb:.0f}MB free"
                )
                
                await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
                
                if loop_count % 10 == 0:  # Log every 10 updates (30 seconds)
                    logger.info(f"🔄 Progress update #{loop_count}: {p*100:.1f}% complete, {memory_mb:.0f}MB free")
                    
            except Exception as e:
                logger.warning(f"⚠️ Progress update error: {e}")
            
            await asyncio.sleep(3)
    
    updater_task = asyncio.create_task(progress_loop(status.message_id))
    temp_path = None
    
    try:
        logger.info(f"⬇️ Starting download process...")
        await status.edit_text("⬇️ Starting download...")
        
        # Download with existing robust downloader
        temp_path, meta = await fetch_to_temp(meta, on_progress=_on_progress)
        logger.info(f"✅ Download completed - Path: {temp_path}")
        
        running = False
        await asyncio.sleep(0)  # Allow progress loop to exit
        
        # Verify downloaded file
        if not temp_path or not os.path.exists(temp_path):
            raise Exception("Downloaded file missing or invalid")
        
        actual_size = os.path.getsize(temp_path)
        done = bytes_done or actual_size
        
        # Final memory cleanup before upload
        await MemoryManager.cleanup_memory()
        final_memory = await MemoryManager.get_memory_info()
        
        final = (
            f"✅ **Download Completed**\n\n"
            f"📄 **Name:** {title}\n"
            f"🗂️ **Size:** {_fmt_size(total)}\n"
            f"📦 **Downloaded:** {_fmt_size(done)}\n"
            f"🧠 **Memory:** {final_memory.get('available', 0):.0f}MB free\n\n"
            f"📤 **Starting optimized upload...**\n"
            f"{BOT_FOOTER}"
        )
        
        try:
            await status.edit_text(final)
            logger.info(f"✅ Download completion message sent")
        except Exception as e:
            logger.warning(f"⚠️ Failed to edit completion message: {e}")
        
        logger.info(f"📤 Starting optimized media upload...")
        
        # Use optimized upload function
        upload_success = await _send_media_optimized(context, chat_id, temp_path, meta.name or title)
        
        if upload_success:
            logger.info(f"✅ Media upload completed successfully")
            try:
                await status.edit_text(
                    f"✅ **Upload Completed Successfully**\n\n"
                    f"📄 **Name:** {title}\n"
                    f"🗂️ **Size:** {_fmt_size(actual_size)}\n"
                    f"📦 **Processed:** {_fmt_size(done)}\n"
                    f"🎉 **Successfully uploaded to Telegram!**\n\n"
                    f"{BOT_FOOTER}"
                )
            except Exception as e:
                logger.warning(f"⚠️ Final status update failed: {e}")
        else:
            logger.error(f"❌ Media upload failed")
            error_memory = await MemoryManager.get_memory_info()
            try:
                await status.edit_text(
                    f"❌ **Upload Failed**\n\n"
                    f"📄 **Name:** {title}\n"
                    f"🗂️ **Size:** {_fmt_size(actual_size)}\n"
                    f"🧠 **Memory:** {error_memory.get('available', 0):.0f}MB available\n\n"
                    f"**Possible causes:**\n"
                    f"• Insufficient memory for upload\n"
                    f"• Network timeout\n"
                    f"• Telegram API rate limiting\n\n"
                    f"**The download was successful - issue is with upload only**"
                )
            except Exception as e:
                logger.warning(f"⚠️ Failed to send upload error message: {e}")
        
        # Cleanup status message for successful uploads
        if upload_success:
            try:
                await asyncio.sleep(2)  # Brief delay before cleanup
                await status.delete()
                logger.info(f"🗑️ Status message cleaned up")
            except Exception as e:
                logger.warning(f"⚠️ Status cleanup error: {e}")
                
    except Exception as e:
        logger.error(f"❌ Download/Upload error: {e}")
        logger.error(f"❌ Error type: {type(e)}")
        
        running = False
        
        error_msg = str(e)
        if "HTTP 400" in error_msg or "400" in error_msg or "expired" in error_msg.lower():
            response_text = "❌ Download failed: Link expired or server rejected request. Please get a fresh link from Terabox."
        elif "timeout" in error_msg.lower():
            response_text = "❌ Download timeout: File too large or connection too slow. Please try again later."
        elif "space" in error_msg.lower() or "disk" in error_msg.lower():
            response_text = "❌ Download failed: Insufficient server storage. Please try again later."
        else:
            response_text = f"❌ Download failed: {error_msg}"
        
        try:
            await status.edit_text(response_text)
            logger.info(f"✅ Error message sent to user")
        except Exception as edit_error:
            logger.error(f"❌ Failed to send error message: {edit_error}")
    
    finally:
        running = False
        
        # Cleanup progress task
        try:
            if updater_task:
                updater_task.cancel()
                try:
                    await updater_task
                except asyncio.CancelledError:
                    logger.info(f"✅ Progress task cancelled")
                    pass
        except Exception as e:
            logger.warning(f"⚠️ Task cleanup error: {e}")
        
        # Cleanup temporary file
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info(f"🗑️ Temporary file cleaned up: {temp_path}")
            except Exception as e:
                logger.warning(f"⚠️ Temp file cleanup error: {e}")
        
        # Final memory cleanup
        await MemoryManager.cleanup_memory()
        
        logger.info(f"🎯 ===== LEECH HANDLER COMPLETED =====")

# ---------- Cleanup Handler ----------
async def cleanup_handler():
    """Cleanup resources on shutdown"""
    logger.info(f"🧹 Running cleanup...")
    try:
        await cleanup_resolver()
        await MemoryManager.cleanup_memory()
        logger.info(f"✅ Cleanup completed")
    except Exception as e:
        logger.error(f"❌ Cleanup error: {e}")

# ---------- Export ----------
leech_handler = leech_handler_v2

def get_enhanced_handler():
    logger.info(f"🔧 Creating enhanced leech handler...")
    return CommandHandler("leech", leech_handler_v2)

def get_cleanup_handler():
    return cleanup_handler
        
