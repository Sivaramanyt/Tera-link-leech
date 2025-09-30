# services/downloader.py

import asyncio
import tempfile
import os
import time
import httpx
import logging
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class FileMeta:
    def __init__(self, name: str, size: Optional[int] = None, url: str = ""):
        self.name = name
        self.size = size
        self.url = url

class DownloadError(Exception):
    """Custom exception for download errors"""
    pass

async def fetch_to_temp(
    meta: FileMeta,
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    max_retries: int = 5,
    chunk_size: int = 65536
) -> tuple[str, FileMeta]:
    """
    Download file from meta.url to a temporary file with retry logic for expired links
    """
    logger.info(f"🌐 Starting download: {meta.name} ({meta.size} bytes)")
    
    # Create temp file
    fd, temp_path = tempfile.mkstemp(
        prefix="terabox_",
        suffix=f"_{meta.name}",
        dir=None
    )
    os.close(fd)
    
    downloaded = 0
    retry_count = 0
    
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=30.0),
        follow_redirects=True,
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
    ) as client:
        
        while retry_count < max_retries:
            try:
                logger.info(f"📥 Download attempt #{retry_count + 1} from: {meta.url[:100]}...")
                
                headers = {}
                if downloaded > 0:
                    headers["Range"] = f"bytes={downloaded}-"
                    logger.info(f"📊 Resuming download from byte {downloaded}")
                
                async with client.stream("GET", meta.url, headers=headers) as response:
                    logger.info(f"📡 Response status: {response.status_code}")
                    logger.info(f"📡 Response headers: {dict(response.headers)}")
                    
                    # Handle different status codes
                    if response.status_code == 400:
                        logger.error(f"❌ 400 Bad Request - Link may be expired")
                        raise DownloadError("Download link expired or invalid")
                    
                    elif response.status_code == 404:
                        logger.error(f"❌ 404 Not Found - File not available")
                        raise DownloadError("File not found on server")
                    
                    elif response.status_code == 403:
                        logger.error(f"❌ 403 Forbidden - Access denied")
                        raise DownloadError("Access denied to file")
                    
                    elif response.status_code not in [200, 206]:
                        logger.error(f"❌ Unexpected status code: {response.status_code}")
                        raise DownloadError(f"Server returned {response.status_code}")
                    
                    # Get content length
                    content_length = response.headers.get("content-length")
                    if content_length:
                        total_size = int(content_length)
                        if downloaded == 0 and not meta.size:
                            meta.size = total_size
                        logger.info(f"📏 Content length: {total_size} bytes")
                    else:
                        total_size = meta.size
                        logger.warning(f"⚠️ No content-length header, using meta size: {total_size}")
                    
                    # Open file for writing (append mode if resuming)
                    mode = "ab" if downloaded > 0 else "wb"
                    
                    with open(temp_path, mode) as f:
                        logger.info(f"📝 Writing to: {temp_path}")
                        
                        async for chunk in response.aiter_bytes(chunk_size):
                            if not chunk:
                                continue
                            
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Call progress callback
                            if on_progress:
                                try:
                                    on_progress(downloaded, total_size)
                                except Exception as e:
                                    logger.warning(f"⚠️ Progress callback error: {e}")
                    
                    # Check if download completed successfully
                    if total_size and downloaded >= total_size:
                        logger.info(f"✅ Download completed: {downloaded}/{total_size} bytes")
                        break
                    elif not total_size:
                        # No size info, assume complete if we got data
                        logger.info(f"✅ Download completed: {downloaded} bytes (no size info)")
                        break
                    else:
                        logger.warning(f"⚠️ Download incomplete: {downloaded}/{total_size} bytes")
                        # Continue to retry
                        
            except (httpx.TimeoutException, httpx.ConnectTimeout) as e:
                retry_count += 1
                logger.error(f"⏰ Timeout error (attempt {retry_count}): {e}")
                if retry_count < max_retries:
                    wait_time = min(2 ** retry_count, 30)  # Exponential backoff, max 30s
                    logger.info(f"⏳ Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                continue
                
            except (httpx.HTTPError, DownloadError) as e:
                retry_count += 1
                logger.error(f"🌐 HTTP/Download error (attempt {retry_count}): {e}")
                if retry_count < max_retries:
                    wait_time = min(2 ** retry_count, 30)  # Exponential backoff, max 30s
                    logger.info(f"⏳ Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                continue
                
            except Exception as e:
                retry_count += 1
                logger.error(f"❌ Unexpected error (attempt {retry_count}): {e}")
                if retry_count < max_retries:
                    wait_time = min(2 ** retry_count, 30)
                    logger.info(f"⏳ Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                continue
    
    # Check if we failed all retries
    if retry_count >= max_retries:
        logger.error(f"❌ Download failed after {max_retries} attempts")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise DownloadError(f"Download failed after {max_retries} attempts. Link may be expired.")
    
    # Verify file exists and has content
    if not os.path.exists(temp_path):
        logger.error(f"❌ Downloaded file does not exist: {temp_path}")
        raise DownloadError("Downloaded file missing")
    
    file_size = os.path.getsize(temp_path)
    if file_size == 0:
        logger.error(f"❌ Downloaded file is empty")
        os.remove(temp_path)
        raise DownloadError("Downloaded file is empty")
    
    logger.info(f"✅ Download successful: {temp_path} ({file_size} bytes)")
    
    # Update meta with actual file size
    meta.size = file_size
    
    return temp_path, meta
    
