# handlers/leech.py

import os
import time
import asyncio
import tempfile
import subprocess
from mimetypes import guess_type

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from services.terabox import TeraboxResolver
from services.downloader import fetch_to_temp

# ---------------- Formatting helpers ----------------
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

# ---------------- Caption/footer ----------------
BOT_FOOTER = "via @Terabox_leech_pro_bot"

def _with_footer(text: str) -> str:
    if not text:
        return BOT_FOOTER
    if BOT_FOOTER.lower() in text.lower():
        return text
    return f"{text}\n{BOT_FOOTER}"

# ---------------- ffmpeg helpers (optional) ----------------
def _probe_duration_seconds(path: str) -> int | None:
    try:
        out = subprocess.check_output(
            ["ffprobe","-v","error","-select_streams","v:0",
             " -show_entries","format=duration","-show_entries","format=duration",
             "-of","default=nk=1:nw=1", path],
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

# ---------------- Media sender ----------------
async def _send_media(context: ContextTypes.DEFAULT_TYPE, chat_id: int, path: str, filename: str):
    mime, _ = guess_type(filename)
    ext = (os.path.splitext(filename)[1] or "").lower()
    caption = _with_footer(f"📄 Name: {filename}")

    duration = None
    thumb = None
    try:
        if ext in (".mp4",".mov",".m4v",".mkv") or (mime and mime.startswith("video/")):
            duration = _probe_duration_seconds(path)
            thumb = _make_video_thumb(path)
    except Exception:
        pass

    try:
        # Video
        if (mime and mime.startswith("video/")) or ext in (".mp4", ".mov", ".m4v"):
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
            return
        # Audio
        if (mime and mime.startswith("audio/")) or ext in (".mp3",".m4a",".aac",".flac",".ogg",".opus"):
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=open(path, "rb"),
                caption=caption,
                duration=duration if duration else None,
                thumbnail=open(thumb, "rb") if thumb else None,
            )
            return
        # Image
        if (mime and mime.startswith("image/")) or ext in (".jpg",".jpeg",".png",".webp"):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=open(path, "rb"),
                caption=caption,
            )
            return
        # Fallback
        await context.bot.send_document(
            chat_id=chat_id,
            document=open(path, "rb"),
            caption=caption,
            thumbnail=open(thumb, "rb") if thumb else None,
        )
    finally:
        try:
            if thumb and os.path.exists(thumb):
                os.remove(thumb)
        except Exception:
            pass

# ---------------- Resolver ----------------
resolver_v2 = TeraboxResolver()

# ---------------- Enhanced handler with real-time progress ----------------
async def leech_handler_v2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.effective_message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await context.bot.send_message(chat_id, "Usage: /leech <terabox_share_url>")
        return

    share_url = parts[1].replace("\\", "/").strip()

    # Initial status
    status = await context.bot.send_message(chat_id, "🔎 Resolving Terabox link...")
    try:
        meta = await resolver_v2.resolve(share_url)
    except Exception as e:
        await status.edit_text(f"❌ Failed to resolve link: {e}")
        return

    title = meta.name or "file"
    total = meta.size
    await status.edit_text(f"📝 Name: {title}\n🗂️ Size: {_fmt_size(total)}\n📁 Total Files: 1")

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

    async def progress_loop(message_id: int):
        while running:
            try:
                done = bytes_done
                p = (done / total) if total and total > 0 else 0.0
                bar = _dot_bar(p, 20)
                elapsed = max(0.001, time.time() - start)
                speed = done / elapsed
                eta = (total - done) / speed if total and speed > 0 else 0
                text = (
                    f"📥 {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"⏩ {bar} {p*100:0.2f}%\n"
                    f"📦 Processed: {_fmt_size(done)}\n"
                    f"🗂️ Size: {_fmt_size(total)}\n"
                    f"🚀 Speed: {_fmt_size(int(speed))}/s\n"
                    f"⏳ ETA: {_fmt_eta(eta)}"
                )
                await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
            except Exception:
                pass
            await asyncio.sleep(2)

    updater_task = asyncio.create_task(progress_loop(status.message_id))

    temp_path = None
    try:
        await status.edit_text("⬇️ Starting download...")
        temp_path, meta = await fetch_to_temp(meta, on_progress=_on_progress)

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
        except Exception:
            pass

        await _send_media(context, chat_id, temp_path, meta.name or title)
        try:
            await status.delete()
        except Exception:
            pass
    except Exception as e:
        running = False
        try:
            await status.edit_text(f"❌ Download failed: {e}")
        except Exception:
            pass
    finally:
        running = False
        try:
            updater_task.cancel()
        except Exception:
            pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

# Backward-compat alias (old import path)
leech_handler = leech_handler_v2

def get_enhanced_handler():
    return CommandHandler("leech", leech_handler_v2)
    
