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
    max_retries: int = 15,  # Increased retries for unstable servers
    base_chunk_size: int = None
) -> tuple[str, FileMeta]:
    """
    ULTRA-AGGRESSIVE downloader for unstable Terabox servers with immediate retry strategy
    """
    logger.info(f"🚀 Starting ULTRA-AGGRESSIVE download: {meta.name} ({meta.size} bytes)")
    
    # Create temp file
    fd, temp_path = tempfile.mkstemp(
        prefix="terabox_",
        suffix=f"_{meta.name}",
        dir=None
    )
    os.close(fd)
    
    downloaded = 0
    retry_count = 0
    download_start_time = time.time()
    
    # Track partial downloads for resume
    resume_ranges = []
    
    while retry_count < max_retries:
        try:
            # ULTRA-AGGRESSIVE: Start with small chunks, increase if stable
            if retry_count < 3:
                chunk_size = 65536   # 64KB - very small for unstable connections
            elif retry_count < 6:
                chunk_size = 131072  # 128KB
            else:
                chunk_size = 32768   # 32KB - fallback to your original size
            
            logger.info(f"🚀 ULTRA attempt #{retry_count + 1}/{max_retries} - Chunk: {chunk_size//1024}KB")
            
            # ULTRA-AGGRESSIVE HTTP settings - fastest possible failure detection
            timeout = httpx.Timeout(
                timeout=30.0,      # Much faster total timeout
                connect=5.0,       # Ultra-fast connection timeout
                read=10.0,         # Ultra-fast read timeout
                write=5.0,         # Ultra-fast write timeout
                pool=5.0           # Ultra-fast pool timeout
            )
            
            # Multiple user agents to avoid rate limiting
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ]
            
            headers = {
                "User-Agent": user_agents[retry_count % len(user_agents)],
                "Accept": "*/*",
                "Accept-Encoding": "identity",  # Disable compression for speed
                "Connection": "close",          # Force new connection each time
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "DNT": "1"
            }
            
            # Add resume header if we have partial data
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"
                logger.info(f"📊 RESUMING from byte {downloaded:,}")
            
            # Use fresh client with aggressive settings
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                limits=httpx.Limits(
                    max_keepalive_connections=0,  # No keepalive - fresh connections
                    max_connections=1,            # Single connection
                    keepalive_expiry=0            # No connection reuse
                ),
                headers=headers
            ) as client:
                
                logger.info(f"🌐 Connecting to: {meta.url[:80]}...")
                
                # Start streaming request
                async with client.stream("GET", meta.url) as response:
                    logger.info(f"📡 Response: {response.status_code}")
                    
                    # Handle status codes aggressively
                    if response.status_code not in [200, 206]:
                        if response.status_code in [404, 403]:
                            raise DownloadError(f"File not accessible (HTTP {response.status_code})")
                        else:
                            logger.warning(f"⚠️ Unexpected status {response.status_code}, retrying...")
                            retry_count += 1
                            continue
                    
                    # Get content info
                    content_length = response.headers.get("content-length")
                    if content_length:
                        if response.status_code == 206:  # Partial content
                            remaining_size = int(content_length)
                            expected_total = downloaded + remaining_size
                        else:  # Full content
                            expected_total = int(content_length)
                            if not meta.size:
                                meta.size = expected_total
                    else:
                        expected_total = meta.size or 0
                    
                    logger.info(f"📏 Expecting {expected_total:,} bytes total, downloading from {downloaded:,}")
                    
                    # Open file for writing
                    mode = "ab" if downloaded > 0 else "wb"
                    bytes_this_attempt = 0
                    last_progress_time = time.time()
                    stall_timeout = 5.0  # 5 second stall timeout
                    
                    try:
                        with open(temp_path, mode) as f:
                            logger.info(f"📝 Writing to: {temp_path}")
                            
                            async for chunk in response.aiter_bytes(chunk_size):
                                current_time = time.time()
                                
                                if not chunk:
                                    continue
                                
                                f.write(chunk)
                                downloaded += len(chunk)
                                bytes_this_attempt += len(chunk)
                                
                                # ULTRA-AGGRESSIVE progress reporting (every 512KB)
                                if downloaded % (512 * 1024) == 0:
                                    if on_progress:
                                        try:
                                            on_progress(downloaded, expected_total)
                                        except Exception:
                                            pass
                                    
                                    # Check for stalls
                                    if current_time - last_progress_time > stall_timeout:
                                        logger.warning(f"⚠️ Download stalled for {stall_timeout}s, breaking to retry")
                                        break
                                    
                                    last_progress_time = current_time
                                
                                # Speed logging every 2MB
                                if bytes_this_attempt > 0 and bytes_this_attempt % (2 * 1024 * 1024) == 0:
                                    attempt_elapsed = current_time - (download_start_time + (retry_count * 2))
                                    if attempt_elapsed > 0:
                                        speed = bytes_this_attempt / attempt_elapsed
                                        logger.info(f"🚀 Speed: {format_speed(speed)}, Downloaded: {downloaded:,}/{expected_total:,}")
                            
                            # Check completion
                            if expected_total and downloaded >= expected_total:
                                total_elapsed = time.time() - download_start_time
                                avg_speed = downloaded / total_elapsed if total_elapsed > 0 else 0
                                logger.info(f"✅ ULTRA download completed: {downloaded:,} bytes in {total_elapsed:.1f}s")
                                logger.info(f"🚀 Average speed: {format_speed(avg_speed)}")
                                break
                            elif bytes_this_attempt > 0:
                                # Made progress, continue with next attempt
                                logger.info(f"📊 Progress: {downloaded:,}/{expected_total:,} bytes ({(downloaded/expected_total)*100:.1f}%)")
                                # Short delay before retry
                                await asyncio.sleep(0.5)
                                retry_count += 1
                                continue
                            else:
                                # No progress made
                                logger.warning(f"⚠️ No data received on attempt {retry_count + 1}")
                                raise DownloadError("No data received from server")
                    
                    except Exception as write_error:
                        logger.warning(f"⚠️ Write error: {write_error}")
                        retry_count += 1
                        continue
                        
        except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            retry_count += 1
            logger.warning(f"⏰ Timeout on attempt {retry_count}: {e}")
            
            # ULTRA-FAST retry - no waiting for timeouts
            if retry_count < max_retries:
                logger.info(f"⚡ INSTANT retry #{retry_count + 1}...")
                await asyncio.sleep(0.1)  # Tiny delay
                continue
                
        except (httpx.HTTPError, httpx.RemoteProtocolError) as e:
            retry_count += 1
            error_msg = str(e).lower()
            
            if "peer closed connection" in error_msg:
                logger.info(f"🔄 Server dropped connection (attempt {retry_count}) - INSTANT retry")
                # INSTANT retry for peer closed errors
                await asyncio.sleep(0.1)
                continue
            else:
                logger.warning(f"🌐 HTTP error (attempt {retry_count}): {e}")
                if retry_count < max_retries:
                    await asyncio.sleep(0.5)
                    continue
                
        except Exception as e:
            retry_count += 1
            logger.error(f"❌ Unexpected error (attempt {retry_count}): {e}")
            if retry_count < max_retries:
                await asyncio.sleep(1.0)
                continue
    
    # Check final result
    if retry_count >= max_retries:
        logger.error(f"❌ ULTRA download failed after {max_retries} attempts")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        raise DownloadError(f"Download failed after {max_retries} attempts - Terabox servers extremely unstable")
    
    # Verify file
    if not os.path.exists(temp_path):
        raise DownloadError("Downloaded file missing")
    
    file_size = os.path.getsize(temp_path)
    if file_size == 0:
        try:
            os.remove(temp_path)
        except:
            pass
        raise DownloadError("Downloaded file is empty")
    
    # Success
    total_elapsed = time.time() - download_start_time
    avg_speed = file_size / total_elapsed if total_elapsed > 0 else 0
    logger.info(f"✅ ULTRA download SUCCESS: {temp_path} ({file_size:,} bytes)")
    logger.info(f"🚀 Final speed: {format_speed(avg_speed)} over {total_elapsed:.1f}s with {retry_count} attempts")
    
    meta.size = file_size
    return temp_path, meta

def format_speed(bytes_per_sec: float) -> str:
    """Format speed to human readable string"""
    if bytes_per_sec == 0:
        return "0 B/s"
    
    for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
        if bytes_per_sec < 1024.0:
            return f"{bytes_per_sec:.1f} {unit}"
        bytes_per_sec /= 1024.0
    return f"{bytes_per_sec:.1f} TB/s"
                    
