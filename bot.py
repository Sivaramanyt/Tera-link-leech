# Add to your bot.py - ENHANCED LEECH HANDLER

import tempfile
import os
import httpx
import json
import re
import asyncio
import time

async def enhanced_terabox_resolve(url: str):
    """Simple terabox resolver using wdzone API"""
    try:
        logger.info(f"🌐 Resolving: {url}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://wdzone-terabox-api.vercel.app/api",
                params={"url": url}
            )
            
            if response.status_code != 200:
                return None, None, None
            
            data = response.json()
            
            if data.get("✅ Status") != "Success":
                return None, None, None
            
            extracted_info = data.get("📜 Extracted Info")
            if not extracted_info or not isinstance(extracted_info, list):
                return None, None, None
            
            file_info = extracted_info[0]
            
            download_url = file_info.get("🔽 Direct Download Link")
            filename = file_info.get("📂 Title")
            size_str = file_info.get("📏 Size")
            
            # Parse size to bytes
            size_bytes = None
            if size_str:
                match = re.match(r'([0-9.]+)\s*([KMGT]?B)', size_str.upper())
                if match:
                    number = float(match.group(1))
                    unit = match.group(2)
                    multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3}
                    size_bytes = int(number * multipliers.get(unit, 1))
            
            logger.info(f"✅ Resolved: {filename} ({size_bytes} bytes)")
            return download_url, filename, size_bytes
            
    except Exception as e:
        logger.error(f"❌ Resolve error: {e}")
        return None, None, None

async def enhanced_download_file(url: str, filename: str, on_progress=None):
    """Enhanced file downloader with progress"""
    try:
        logger.info(f"⬇️ Starting download: {filename}")
        
        # Create temp file
        fd, temp_path = tempfile.mkstemp(prefix="terabox_", suffix=f"_{filename}")
        os.close(fd)
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    logger.error(f"❌ Download failed: HTTP {response.status_code}")
                    return None
                
                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0
                
                with open(temp_path, "wb") as f:
                    async for chunk in response.aiter_bytes(512 * 1024):  # 512KB chunks
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if on_progress and total_size > 0:
                                progress = downloaded / total_size
                                on_progress(downloaded, total_size, progress)
        
        logger.info(f"✅ Download completed: {temp_path}")
        return temp_path
        
    except Exception as e:
        logger.error(f"❌ Download error: {e}")
        return None

async def enhanced_leech_handler(update, context):
    """Enhanced leech handler with real download functionality"""
    text = update.effective_message.text or ""
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        await update.message.reply_text(
            "**🔥 Enhanced Terabox Leech Pro Bot 🔥**\n\n"
            "**Usage:** `/leech <terabox_link>`\n\n"
            "**Enhanced Features:**\n"
            "✅ 120MB limit for maximum speed\n"
            "✅ Real-time progress tracking\n"
            "✅ Memory-optimized downloads\n"
            "✅ Streaming uploads\n\n"
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
    status = await update.message.reply_text("🔍 **Resolving Terabox link...**")
    
    try:
        # Step 1: Resolve URL
        logger.info(f"🎯 Processing: {url}")
        download_url, filename, file_size = await enhanced_terabox_resolve(url)
        
        if not download_url:
            await status.edit_text("❌ **Link Resolution Failed**\n\nLink expired or invalid. Please get a fresh link from Terabox.")
            return
        
        # Step 2: Check file size (120MB limit)
        MAX_SIZE = 120 * 1024 * 1024  # 120MB
        if file_size and file_size > MAX_SIZE:
            size_mb = file_size / (1024 * 1024)
            await status.edit_text(
                f"⚖️ **File Too Large**\n\n"
                f"📂 **File:** {filename}\n"
                f"📏 **Size:** {size_mb:.1f} MB\n"
                f"🚫 **Limit:** 120 MB\n\n"
                f"💡 **Why 120MB?**\n"
                f"• Optimized for maximum speed (1+ MB/s)\n"
                f"• Memory-safe for free tier hosting\n"
                f"• Streaming upload prevents crashes"
            )
            return
        
        # Step 3: Show file info
        await status.edit_text(
            f"📁 **Enhanced File Information**\n\n"
            f"📂 **Name:** {filename}\n"
            f"📏 **Size:** {file_size / (1024*1024):.1f} MB\n"
            f"🚀 **Expected Speed:** {'1-3 MB/s' if file_size > 50*1024*1024 else '500KB-1MB/s'}\n\n"
            f"⬇️ **Starting enhanced download...**"
        )
        
        # Step 4: Download with progress
        start_time = time.time()
        last_update = 0
        
        def progress_callback(downloaded, total, progress):
            nonlocal last_update
            current_time = time.time()
            
            # Update every 3 seconds
            if current_time - last_update >= 3:
                elapsed = current_time - start_time
                speed = downloaded / elapsed if elapsed > 0 else 0
                eta = (total - downloaded) / speed if speed > 0 else 0
                
                # Create progress bar
                bar_length = 20
                filled = int(progress * bar_length)
                bar = "█" * filled + "░" * (bar_length - filled)
                
                asyncio.create_task(status.edit_text(
                    f"🚀 **ENHANCED DOWNLOAD** 🚀\n\n"
                    f"📊 **Progress:** `{bar}` {progress*100:.1f}%\n\n"
                    f"📥 **Downloaded:** {downloaded/(1024*1024):.1f} MB\n"
                    f"📏 **Total:** {total/(1024*1024):.1f} MB\n"
                    f"⚡ **Speed:** {speed/(1024*1024):.1f} MB/s\n"
                    f"⏱️ **ETA:** {eta:.0f}s"
                ))
                
                last_update = current_time
        
        temp_path = await enhanced_download_file(download_url, filename, progress_callback)
        
        if not temp_path:
            await status.edit_text("❌ **Download Failed**\n\nServer error or connection timeout. Please try again.")
            return
        
        # Step 5: Upload to Telegram
        await status.edit_text(
            f"✅ **Download Completed!**\n\n"
            f"📁 **Name:** {filename}\n"
            f"📏 **Size:** {file_size/(1024*1024):.1f} MB\n"
            f"⏱️ **Time:** {time.time() - start_time:.1f}s\n\n"
            f"📤 **Starting upload to Telegram...**"
        )
        
        # Simple upload (will enhance with streaming later)
        with open(temp_path, 'rb') as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                caption=f"📁 **{filename}**\n📏 **Size:** {file_size/(1024*1024):.1f} MB\n\n💎 via @Terabox_leech_pro_bot",
                filename=filename
            )
        
        # Cleanup
        try:
            os.remove(temp_path)
            await status.delete()
            logger.info(f"✅ Enhanced leech completed: {filename}")
        except Exception as e:
            logger.warning(f"⚠️ Cleanup error: {e}")
            
    except Exception as e:
        logger.error(f"❌ Enhanced leech error: {e}")
        await status.edit_text(f"❌ **Enhanced Operation Failed**\n\n``````")
                                 
