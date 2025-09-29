# ======================= Enhanced Leech Handler (keep existing code) =======================
import os
import time
import asyncio
from mimetypes import guess_type
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from services.terabox import TeraboxResolver
from services.downloader import fetch_to_temp

# ---- Formatting helpers ----
def _fmt_size(n: int | None) -> str:
    if n is None:
        return "unknown"
    f = float(n)
    for u in ["B","KB","MB","GB","TB"]:
        if f < 1024:
            return f"{f:.2f} {u}"
        f /= 1024
    return f"{f:.2f} PB"

def _progress_bar(p: float, width: int = 20) -> str:
    p = max(0.0, min(1.0, p))
    done = int(p * width)
    return "█" * done + "░" * (width - done)

def _fmt_eta(sec: float) -> str:
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m}m{s}s"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"

# ---- Media upload chooser ----
async def _send_media(context: ContextTypes.DEFAULT_TYPE, chat_id: int, path: str, filename: str):
    mime, _ = guess_type(filename)
    ext = (os.path.splitext(filename)[1] or "").lower()
    if (mime and mime.startswith("video/")) or ext in (".mp4", ".mov", ".m4v"):
        await context.bot.send_video(chat_id=chat_id, video=open(path, "rb"),
                                     caption=f"📄 Name: {filename}", supports_streaming=True)
        return
    if (mime and mime.startswith("audio/")) or ext in (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"):
        await context.bot.send_audio(chat_id=chat_id, audio=open(path, "rb"),
                                     caption=f"📄 Name: {filename}")
        return
    if (mime and mime.startswith("image/")) or ext in (".jpg", ".jpeg", ".png", ".webp"):
        await context.bot.send_photo(chat_id=chat_id, photo=open(path, "rb"),
                                     caption=f"📄 Name: {filename}")
        return
    await context.bot.send_document(chat_id=chat_id, document=open(path, "rb"),
                                    caption=f"📄 Name: {filename}")

resolver_v2 = TeraboxResolver()

async def leech_handler_v2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.effective_message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await context.bot.send_message(chat_id, "Usage: /leech <terabox_share_url>")
        return
    share_url = parts[1].replace("\\", "/").strip()

    # Initial message
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
    path_holder = {}

    async def progress_loop(message_id: int):
        while running:
            try:
                done = 0
                pth = path_holder.get("path")
                if pth and os.path.exists(pth):
                    try:
                        done = os.path.getsize(pth)
                    except Exception:
                        done = 0
                p = (done / total) if total and total > 0 else 0.0
                bar = _progress_bar(p)
                elapsed = max(0.001, time.time() - start)
                speed = done / elapsed
                eta = (total - done) / speed if total and speed > 0 else 0
                text = (
                    f"🟩 Download: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"🧮 {bar} {p*100:0.2f}%\n"
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

    # Download and upload
    temp_path = None
    try:
        await status.edit_text("⬇️ Downloading...")
        temp_path, meta = await fetch_to_temp(meta)
        path_holder["path"] = temp_path

        # Stop progress loop and show final
        running = False
        await asyncio.sleep(0)
        done = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
        final = (
            f"✅ Completed\n"
            f"📄 Name: {title}\n"
            f"🗂️ Size: {_fmt_size(total)}\n"
            f"📦 Processed: {_fmt_size(done)}"
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

def get_enhanced_handler():
    # Register this in your Application builder in addition to the existing handler if desired
    return CommandHandler("leech", leech_handler_v2)
# ===================== End Enhanced Leech Handler (additive) =====================
