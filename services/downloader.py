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
    max_retries: int = 10,  # Increased from 5 to 10 retries
    chunk_size: int = 32768  # Smaller chunks for better stability
) -> tuple[str, FileMeta]:
    """
    Download file from meta.url to a temporary file with enhanced retry logic
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
    consecutive_failures = 0  # Track consecutive failures
    
    # Enhanced HTTP client with better timeout handling
    timeout = httpx.Timeout(
        timeout=120.0,  # Overall timeout
        connect=30.0,   # Connection timeout 
        read=60.0,      # Read timeout
        write=30.0,     # Write timeout
        pool=30.0       # Pool timeout
    )
    
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        limits=httpx.Limits(
            max_keepalive_connections=1,  # Single connection
            max_connections=1,
            keepalive_expiry=30.0
        ),
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "identity",  # Disable compression for stability
            "Connection": "close"  # Force connection close after each request
        }
    ) as client:
        
        while retry_count < max_retries:
            try:
                logger.info(f"📥 Download attempt #{retry_count + 1}/{max_retries} from: {meta.url[:100]}...")
                
                headers = {}
                if downloaded > 0:
                    headers["Range"] = f"bytes={downloaded}-"
                    logger.info(f"📊 Resuming download from byte {downloaded:,}")
                
                # Start streaming request
                async with client.stream("GET", meta.url, headers=headers) as response:
                    logger.info(f"📡 Response status: {response.status_code}")
                    
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
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            raise DownloadError(f"Server consistently returning {response.status_code}")
                        continue
                    
                    # Reset consecutive failures on successful response
                    consecutive_failures = 0
                    
                    # Get content length
                    content_length = response.headers.get("content-length")
                    if content_length:
                        total_size = int(content_length)
                        if downloaded == 0 and not meta.size:
                            meta.size = total_size
                        expected_total = downloaded + total_size
                        logger.info(f"📏 Content length: {total_size:,} bytes, Expected total: {expected_total:,}")
                    else:
                        total_size = meta.size or 0
                        expected_total = total_size
                        logger.warning(f"⚠️ No content-length header, using meta size: {total_size:,}")
                    
                    # Open file for writing
                    mode = "ab" if downloaded > 0 else "wb"
                    bytes_in_chunk = 0
                    last_progress_time = time.time()
                    
                    try:
                        with open(temp_path, mode) as f:
                            logger.info(f"📝 Writing to: {temp_path}")
                            
                            async for chunk in response.aiter_bytes(chunk_size):
                                if not chunk:
                                    continue
                                
                                f.write(chunk)
                                downloaded += len(chunk)
                                bytes_in_chunk += len(chunk)
                                
                                # Call progress callback periodically
                                current_time = time.time()
                                if on_progress and (current_time - last_progress_time) > 3.0:  # Every 3 seconds
                                    try:
                                        on_progress(downloaded, expected_total)
                                        last_progress_time = current_time
                                    except Exception as e:
                                        logger.warning(f"⚠️ Progress callback error: {e}")
                            
                            # Final progress update
                            if on_progress:
                                try:
                                    on_progress(downloaded, expected_total)
                                except Exception:
                                    pass
                    
                    except Exception as chunk_error:
                        logger.error(f"💥 Chunk processing error: {chunk_error}")
                        raise chunk_error
                    
                    # Check if download completed successfully
                    if expected_total and downloaded >= expected_total:
                        logger.info(f"✅ Download completed: {downloaded:,}/{expected_total:,} bytes")
                        break
                    elif not expected_total and bytes_in_chunk > 0:
                        logger.info(f"✅ Download completed: {downloaded:,} bytes (no size info)")
                        break
                    else:
                        # Incomplete download - will retry
                        logger.warning(f"⚠️ Download incomplete: {downloaded:,}/{expected_total:,} bytes, will retry")
                        raise DownloadError(f"Incomplete download: got {downloaded:,}, expected {expected_total:,}")
                        
            except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                retry_count += 1
                consecutive_failures += 1
                logger.error(f"⏰ Timeout error (attempt {retry_count}): {e}")
                if retry_count < max_retries:
                    # Progressive backoff: 2s, 4s, 8s, 16s, 30s (max)
                    wait_time = min(2 ** retry_count, 30)
                    logger.info(f"⏳ Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                continue
                
            except (httpx.HTTPError, DownloadError) as e:
                retry_count += 1
                consecutive_failures += 1
                logger.error(f"🌐 HTTP/Download error (attempt {retry_count}): {e}")
                if retry_count < max_retries:
                    # Progressive backoff with longer waits for HTTP errors
                    wait_time = min(3 ** retry_count, 60)  # 3s, 9s, 27s, 60s (max)
                    logger.info(f"⏳ Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                continue
                
            except Exception as e:
                retry_count += 1
                consecutive_failures += 1
                logger.error(f"❌ Unexpected error (attempt {retry_count}): {e}")
                if retry_count < max_retries:
                    wait_time = min(5 ** retry_count, 120)  # Exponential backoff, max 2 min
                    logger.info(f"⏳ Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                continue
    
    # Check if we exhausted all retries
    if retry_count >= max_retries:
        logger.error(f"❌ Download failed after {max_retries} attempts")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        
        # Better error message based on what actually happened
        if consecutive_failures >= 5:
            raise DownloadError("Server connection unstable. Terabox servers may be overloaded. Try again later.")
        else:
            raise DownloadError(f"Download failed after {max_retries} attempts. Connection issues with Terabox servers.")
    
    # Verify file exists and has content
    if not os.path.exists(temp_path):
        logger.error(f"❌ Downloaded file does not exist: {temp_path}")
        raise DownloadError("Downloaded file missing")
    
    file_size = os.path.getsize(temp_path)
    if file_size == 0:
        logger.error(f"❌ Downloaded file is empty")
        try:
            os.remove(temp_path)
        except:
            pass
        raise DownloadError("Downloaded file is empty")
    
    logger.info(f"✅ Download successful: {temp_path} ({file_size:,} bytes)")
    
    # Update meta with actual file size
    meta.size = file_size
    
    return temp_path, meta
