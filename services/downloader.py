# services/downloader.py

import os
import math
import tempfile
import httpx
import asyncio
import random
import time
from urllib.parse import urlparse, unquote
from dataclasses import dataclass
from typing import Optional

@dataclass
class FileMeta:
    name: str
    size: int | None
    url: str
    
    def human_size(self) -> str:
        if self.size is None:
            return "unknown"
        size = float(self.size)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"

def _name_from_url(u: str) -> str | None:
    try:
        p = urlparse(u).path
        if p:
            candidate = os.path.basename(p)
            if candidate:
                return unquote(candidate)
    except Exception:
        pass
    return None

def _headers_for(url: str, range_hdr: str | None = None) -> dict:
    host = urlparse(url).netloc
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Referer": f"https://{host}/",
        "Origin": f"https://{host}",
        "Host": host,
        "DNT": "1",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    
    if range_hdr:
        h["Range"] = range_hdr
    
    return h

DEFAULT_MAX_WORKERS = int(os.getenv("TB_MAX_WORKERS", "2"))  # Reduced workers
MIN_CHUNK = 64 * 1024  # Smaller chunks
START_CHUNK = 128 * 1024  # Smaller initial chunk
BASE_BACKOFF = 0.5
MAX_BACKOFF = 8.0
MAX_RETRIES = 10  # Increased retries

async def _fetch_range(client: httpx.AsyncClient, url: str, start: int, end: int,
                      headers_fn, attempt_chunk: int, on_progress, total_size: int,
                      fhandle, write_offset: int):
    cur_start = start
    cur_chunk = attempt_chunk
    backoff = BASE_BACKOFF
    retries = 0
    
    while cur_start <= end and retries < MAX_RETRIES:
        cur_end = min(end, cur_start + cur_chunk - 1)
        
        try:
            # Add random delay between requests to avoid rate limiting
            await asyncio.sleep(random.uniform(0.1, 0.5))
            
            headers = headers_fn(f"bytes={cur_start}-{cur_end}")
            rr = await client.get(url, headers=headers)
            
            # Handle different HTTP status codes
            if rr.status_code == 400:
                print(f"HTTP 400 for range {cur_start}-{cur_end}, retrying with smaller chunk")
                retries += 1
                await asyncio.sleep(backoff)
                backoff = min(MAX_BACKOFF, backoff * 2)
                cur_chunk = max(MIN_CHUNK, cur_chunk // 2)
                continue
                
            if 500 <= rr.status_code < 600:
                print(f"Server error {rr.status_code}, retrying...")
                retries += 1
                await asyncio.sleep(backoff)
                backoff = min(MAX_BACKOFF, backoff * 2)
                cur_chunk = max(MIN_CHUNK, cur_chunk // 2)
                continue
            
            if rr.status_code == 429:  # Rate limited
                print("Rate limited, backing off...")
                retries += 1
                await asyncio.sleep(backoff)
                backoff = min(MAX_BACKOFF, backoff * 3)
                continue
                
            if rr.status_code not in (200, 206):
                raise RuntimeError(f"HTTP {rr.status_code}")
            
            data = rr.content
            if not data:
                print("Empty response, retrying...")
                retries += 1
                await asyncio.sleep(backoff)
                backoff = min(MAX_BACKOFF, backoff * 2)
                cur_chunk = max(MIN_CHUNK, cur_chunk // 2)
                continue
            
            # Success - reset backoff and write data
            backoff = BASE_BACKOFF
            retries = 0  # Reset retries on successful chunk
            
            fhandle.seek(write_offset + (cur_start - start))
            fhandle.write(data)
            
            if on_progress:
                try:
                    done_bytes = min(total_size, write_offset + (cur_start - start) + len(data))
                    on_progress(done_bytes, total_size)
                except Exception:
                    pass
            
            cur_start += len(data)
            continue
            
        except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError, httpx.TimeoutException) as e:
            print(f"Network error: {e}, retrying...")
            retries += 1
            await asyncio.sleep(backoff)
            backoff = min(MAX_BACKOFF, backoff * 2)
            cur_chunk = max(MIN_CHUNK, cur_chunk // 2)
            continue
        except Exception as e:
            print(f"Unexpected error: {e}")
            retries += 1
            if retries >= MAX_RETRIES:
                raise
            await asyncio.sleep(backoff)
            backoff = min(MAX_BACKOFF, backoff * 2)
            continue

async def download_parallel(client: httpx.AsyncClient, url: str, size: int, path: str,
                           headers_fn, on_progress=None, workers: Optional[int] = None):
    workers = min(workers or DEFAULT_MAX_WORKERS, 2)  # Limit workers to avoid 400 errors
    
    with open(path, "wb") as f:
        f.truncate(size)
    
    # Create fewer, larger segments to reduce HTTP requests
    base_seg = max(START_CHUNK * 16, size // max(1, workers * 4))
    segments = []
    s = 0
    while s < size:
        e = min(size - 1, s + base_seg - 1)
        segments.append((s, e))
        s = e + 1
    
    async def worker(idx: int, start: int, end: int):
        with open(path, "r+b") as f:
            await _fetch_range(client, url, start, end, headers_fn, START_CHUNK, 
                             on_progress, size, f, start)
    
    sem = asyncio.Semaphore(workers)
    
    async def run_seg(i, rng):
        async with sem:
            await worker(i, rng[0], rng[1])
            # Add delay between workers to prevent overwhelming the server
            await asyncio.sleep(random.uniform(0.5, 1.5))
    
    # Process segments sequentially to reduce server load
    for i, rng in enumerate(segments):
        await run_seg(i, rng)

async def fetch_to_temp(meta: FileMeta, timeout: int = 300, on_progress=None) -> tuple[str, FileMeta]:
    url = meta.url
    print(f"[downloader] workers={DEFAULT_MAX_WORKERS} start_chunk={START_CHUNK} min_chunk={MIN_CHUNK}")
    
    # Enhanced client configuration
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, read=120.0),
        follow_redirects=True,
        limits=httpx.Limits(
            max_keepalive_connections=2,
            max_connections=5,
            keepalive_expiry=30
        )
    ) as client:
        
        # First probe with retries
        for attempt in range(5):
            try:
                # Add random delay before first request
                await asyncio.sleep(random.uniform(1, 3))
                
                r0 = await client.get(url, headers=_headers_for(url, "bytes=0-0"))
                
                if r0.status_code == 400:
                    print(f"HTTP 400 on probe attempt {attempt + 1}, retrying...")
                    if attempt < 4:
                        await asyncio.sleep(random.uniform(2, 5))
                        continue
                    else:
                        raise RuntimeError("CDN consistently returns 400 - link may be expired")
                
                if r0.status_code not in (200, 206):
                    if attempt < 4:
                        await asyncio.sleep(random.uniform(1, 3))
                        continue
                    raise RuntimeError(f"CDN refused ranged request: {r0.status_code}")
                
                break  # Success
                
            except Exception as e:
                if attempt < 4:
                    print(f"Probe attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(random.uniform(2, 5))
                    continue
                raise
        
        final_url = str(r0.url)  # use the redirected, signed data host
        ctype = (r0.headers.get("content-type") or "").lower()
        
        if "text/html" in ctype or "text/plain" in ctype:
            raise RuntimeError("Resolved URL returned HTML/text, not a file")
        
        size = meta.size
        content_range = r0.headers.get("content-range")
        
        if size is None:
            if content_range and "/" in content_range:
                try:
                    size = int(content_range.split("/")[-1])
                except Exception:
                    size = None
        
        if size is None:
            cl = r0.headers.get("content-length")
            if cl:
                try:
                    size = int(cl)
                except Exception:
                    size = None
        
        meta.size = size
        
        if not meta.name:
            cd = r0.headers.get("content-disposition", "")
            if "filename=" in cd:
                meta.name = cd.split("filename=")[-1].strip('"; ')
            else:
                meta.name = _name_from_url(final_url) or "file"
        
        fd, path = tempfile.mkstemp(prefix="tb_", suffix=f"_{meta.name}")
        os.close(fd)
        
        if size is None:
            # Fallback to sequential download for unknown size
            written = 0
            r = await client.get(final_url, headers=_headers_for(final_url))
            r.raise_for_status()
            
            with open(path, "wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
                    written += len(chunk)
                    if on_progress:
                        try:
                            on_progress(written, 0)
                        except Exception:
                            pass
            
            if meta.size is None and written > 0:
                meta.size = written
            return path, meta
        
        # Warm-up with retry logic
        for attempt in range(3):
            try:
                await asyncio.sleep(random.uniform(0.5, 2))
                warm = await client.get(final_url, headers=_headers_for(final_url, "bytes=0-0"))
                if warm.status_code in (200, 206):
                    break
                if attempt < 2:
                    await asyncio.sleep(random.uniform(1, 3))
                    continue
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(random.uniform(1, 3))
                    continue
                print(f"Warm-up failed: {e}")
        
        # Parallel segmented download with enhanced error handling
        try:
            await download_parallel(client, final_url, size, path, _headers_for, 
                                  on_progress, workers=DEFAULT_MAX_WORKERS)
        except Exception as e:
            print(f"Parallel download failed: {e}, trying sequential download...")
            # Fallback to sequential download
            written = 0
            r = await client.get(final_url, headers=_headers_for(final_url))
            r.raise_for_status()
            
            with open(path, "wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
                    written += len(chunk)
                    if on_progress:
                        try:
                            on_progress(written, size or written)
                        except Exception:
                            pass
        
        if meta.size is None:
            try:
                meta.size = os.path.getsize(path)
            except Exception:
                pass
        
        return path, meta
