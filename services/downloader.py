# services/downloader.py
import os
import math
import tempfile
import httpx
import asyncio
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
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "video/*,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Referer": f"https://{host}/",
        "Origin": f"https://{host}",
        "Host": host,
    }
    if range_hdr:
        h["Range"] = range_hdr
    return h

# Parallel segmented downloader config
DEFAULT_MAX_WORKERS = int(os.getenv("TB_MAX_WORKERS", "4"))
MIN_CHUNK = 256 * 1024
START_CHUNK = 512 * 1024  # initial subrequest size; adapts down on errors

async def _fetch_range(client: httpx.AsyncClient, url: str, start: int, end: int,
                       headers_fn, attempt_chunk: int, on_progress, total_size: int,
                       fhandle, write_offset: int):
    """
    Fetch a byte range [start, end] with retries; write directly at correct offset.
    Resumes inside the range on partial responses and halves chunk size on errors.
    """
    cur_start = start
    cur_chunk = attempt_chunk
    while cur_start <= end:
        cur_end = min(end, cur_start + cur_chunk - 1)
        try:
            rr = await client.get(url, headers=headers_fn(f"bytes={cur_start}-{cur_end}"))
            if rr.status_code not in (200, 206):
                raise RuntimeError(f"HTTP {rr.status_code}")
            data = rr.content
            if not data:
                raise httpx.ReadError("empty body")

            # Write exactly at desired position (no truncation)
            fhandle.seek(write_offset + (cur_start - start))
            fhandle.write(data)

            if on_progress:
                try:
                    done_bytes = min(total_size, write_offset + (cur_start - start) + len(data))
                    on_progress(done_bytes, total_size)
                except Exception:
                    pass

            got = len(data)
            cur_start += got
            continue

        except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError):
            # Adaptive: reduce subrequest size and retry
            cur_chunk = max(MIN_CHUNK, cur_chunk // 2)
            await asyncio.sleep(0.5)
            if cur_chunk <= MIN_CHUNK:
                # Final attempt for this slice
                rr = await client.get(url, headers=headers_fn(f"bytes={cur_start}-{cur_end}"))
                if rr.status_code in (200, 206) and rr.content:
                    data = rr.content
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
                raise

async def download_parallel(client: httpx.AsyncClient, url: str, size: int, path: str,
                            headers_fn, on_progress=None, workers: Optional[int] = None):
    """
    Download file in parallel byte ranges to 'path' with up to 'workers' tasks.
    """
    workers = workers or DEFAULT_MAX_WORKERS

    # Pre-allocate the file to full size (sparse)
    with open(path, "wb") as f:
        f.truncate(size)

    # Create balanced segments for workers
    base_seg = max(START_CHUNK * 8, size // max(1, workers * 16))
    segments = []
    s = 0
    while s < size:
        e = min(size - 1, s + base_seg - 1)
        segments.append((s, e))
        s = e + 1

    async def worker(idx: int, start: int, end: int):
        with open(path, "r+b") as f:
            await _fetch_range(client, url, start, end, headers_fn, START_CHUNK, on_progress, size, f, start)

    sem = asyncio.Semaphore(workers)

    async def run_seg(i, rng):
        async with sem:
            await worker(i, rng[0], rng[1])

    await asyncio.gather(*(run_seg(i, rng) for i, rng in enumerate(segments)))

async def fetch_to_temp(meta: FileMeta, timeout: int = 240, on_progress=None) -> tuple[str, FileMeta]:
    """
    Download to a temp file with CDN-friendly headers and parallel ranged GET.
    on_progress: optional callable(done_bytes:int, total_bytes:int|0)
    """
    url = meta.url

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # Probe with tiny range GET to learn size/name; avoids HEAD 403 path
        r0 = await client.get(url, headers=_headers_for(url, "bytes=0-0"))
        if r0.status_code not in (200, 206):
            raise RuntimeError(f"CDN refused ranged request: {r0.status_code}")

        ctype = (r0.headers.get("content-type") or "").lower()
        if "text/html" in ctype or "text/plain" in ctype:
            raise RuntimeError("Resolved URL returned HTML/text, not a file")

        # Determine total size
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

        # Determine name
        if not meta.name:
            cd = r0.headers.get("content-disposition", "")
            if "filename=" in cd:
                meta.name = cd.split("filename=")[-1].strip('"; ')
            else:
                meta.name = _name_from_url(str(r0.url)) or "file"

        # Prepare output
        fd, path = tempfile.mkstemp(prefix="tb_", suffix=f"_{meta.name}")
        os.close(fd)

        # If size unknown, stream single GET as fallback
        if size is None:
            written = 0
            r = await client.get(url, headers=_headers_for(url))
            r.raise_for_status()
            with open(path, "wb") as f:
                async for chunk in r.aiter_bytes():
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

        # Parallel segmented download
        await download_parallel(client, url, size, path, _headers_for, on_progress, workers=DEFAULT_MAX_WORKERS)

        # Finalize
        if meta.size is None:
            try:
                meta.size = os.path.getsize(path)
            except Exception:
                pass

        return path, meta
