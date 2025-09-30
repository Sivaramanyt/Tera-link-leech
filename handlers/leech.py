# handlers/leech.py

import os
import time
import asyncio
import tempfile
import subprocess
import logging
from mimetypes import guess_type
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from services.terabox import get_resolver, cleanup_resolver
from services.downloader import fetch_to_temp

# Configure logging
logger = logging.getLogger(__name__)

# ---------- Formatting ----------

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

# ---------- Media sender ----------

async def _send_media(context: ContextTypes.DEFAULT_TYPE, chat_id: int, path: str, filename: str):
    logger.info(f"📤 Sending media: {filename} to chat {chat_id}")
    
    mime, _ = guess_type(filename)
    ext = (os.path.splitext(filename)[1] or "").lower()
    caption = _with_footer(f"📄 Name: {filename}")
    
    duration = None
    thumb = None
    
    try:
        if ext in (".mp4",".mov",".m4v",".mkv") or (mime and mime.startswith("video/")):
            duration = _probe_duration_seconds(path)
            thumb = _make_video_thumb(path)
            logger.info(f"🎬 Video detected - Duration: {duration}s, Thumb: {thumb is not None}")
    except Exception as e:
        logger.warning(f"⚠️ Media probe error: {e}")
    
    try:
        if (mime and mime.startswith("video/")) or ext in (".mp4", ".mov", ".m4v", ".mkv"):
            logger.info(f"📹 Sending as video...")
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(path, "rb"),
                caption=caption,
                supports_streaming=True,
                duration=duration if duration else None,
                width=1280,
                height=720,
                thumbnail=open(thumb, "rb") if thumb else None,
            )
            logger.info(f"✅ Video sent successfully")
            return
        
        if (mime and mime.startswith("audio/")) or ext in (".mp3",".m4a",".aac",".flac",".ogg",".opus"):
            logger.info(f"🎵 Sending as audio...")
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=open(path, "rb"),
                caption=caption,
                duration=duration if duration else None,
                thumbnail=open(thumb, "rb") if thumb else None,
            )
            logger.info(f"✅ Audio sent successfully")
            return
        
        if (mime and mime.startswith("image/")) or ext in (".jpg",".jpeg",".png",".webp"):
            logger.info(f"🖼️ Sending as photo...")
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=open(path, "rb"),
                caption=caption,
            )
            logger.info(f"✅ Photo sent successfully")
            return
        
        logger.info(f"📄 Sending as document...")
        await context.bot.send_document(
            chat_id=chat_id,
            document=open(path, "rb"),
            caption=caption,
            thumbnail=open(thumb, "rb") if thumb else None,
        )
        logger.info(f"✅ Document sent successfully")
        
    except Exception as e:
        logger.error(f"❌ Media send error: {e}")
        raise
        
    finally:
        try:
            if thumb and os.path.exists(thumb):
                os.remove(thumb)
                logger.info(f"🗑️ Thumbnail cleaned up")
        except Exception as e:
            logger.warning(f"⚠️ Thumbnail cleanup error: {e}")

# ---------- Enhanced Handler with Debug Logging ----------

async def leech_handler_v2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # COMPREHENSIVE DEBUG LOGGING
    logger.info(f"🎯 ===== LEECH HANDLER CALLED =====")
    logger.info(f"🎯 User ID: {update.effective_user.id}")
    logger.info(f"🎯 Chat ID: {update.effective_chat.id}")
    logger.info(f"🎯 Message text: '{update.effective_message.text}'")
    logger.info(f"🎯 Message type: {type(update.effective_message.text)}")
    
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
        status = await context.bot.send_message(chat_id, "🔎 Resolving Terabox link...")
        logger.info(f"✅ Status message sent - ID: {status.message_id}")
    except Exception as e:
        logger.error(f"❌ Failed to send status message: {e}")
        return
    
    try:
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
    
    try:
        await status.edit_text(f"📝 Name: {title}\n🗂️ Size: {_fmt_size(total)}\n📁 Total Files: 1")
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
                
                text = (
                    f"⏩ 📥 {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"{bar} {p*100:0.2f}%\n"
                    f"📦 Processed: {_fmt_size(done)}\n"
                    f"🗂️ Size: {_fmt_size(total)}\n"
                    f"🚀 Speed: {_fmt_size(int(speed))}/s\n"
                    f"⏳ ETA: {_fmt_eta(eta)}"
                )
                
                await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
                
                if loop_count % 10 == 0:  # Log every 10 updates (30 seconds)
                    logger.info(f"🔄 Progress update #{loop_count}: {p*100:.1f}% complete")
                    
            except Exception as e:
                logger.warning(f"⚠️ Progress update error: {e}")
            await asyncio.sleep(3)
    
    updater_task = asyncio.create_task(progress_loop(status.message_id))
    temp_path = None
    
    try:
        logger.info(f"⬇️ Starting download process...")
        await status.edit_text("⬇️ Starting download...")
        
        temp_path, meta = await fetch_to_temp(meta, on_progress=_on_progress)
        logger.info(f"✅ Download completed - Path: {temp_path}")
        
        running = False
        await asyncio.sleep(0)
        
        done = bytes_done
        final = (
            f"✅ Completed\n"
            f"📄 Name: {title}\n"
            f"🗂️ Size: {_fmt_size(total)}\n"
            f"📦 Processed: {_fmt_size(done)}\n"
            f"{BOT_FOOTER}"
        )
        
        try:
            await status.edit_text(final)
            logger.info(f"✅ Completion message sent")
        except Exception as e:
            logger.warning(f"⚠️ Failed to edit completion message: {e}")
        
        logger.info(f"📤 Starting media upload...")
        await _send_media(context, chat_id, temp_path, meta.name or title)
        logger.info(f"✅ Media upload completed")
        
        try:
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
        
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info(f"🗑️ Temporary file cleaned up: {temp_path}")
            except Exception as e:
                logger.warning(f"⚠️ Temp file cleanup error: {e}")
        
        logger.info(f"🎯 ===== LEECH HANDLER COMPLETED =====")

# ---------- Cleanup Handler ----------

async def cleanup_handler():
    """Cleanup resources on shutdown"""
    logger.info(f"🧹 Running cleanup...")
    try:
        await cleanup_resolver()
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
        
