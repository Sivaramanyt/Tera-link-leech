# services/downloader.py
import os
import math
import tempfile
import httpx
from urllib.parse import urlparse, unquote
from dataclasses import dataclass

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

CHUNK = 1 * 1024 * 1024  # 1 MiB

async def fetch_to_temp(meta: FileMeta, timeout: int = 240, on_progress=None) -> tuple[str, FileMeta]:
    """
    Download to a temp file with CDN-friendly headers and ranged GET.
    on_progress: optional callable(done_bytes:int, total_bytes:int|0)
    """
    url = meta.url

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # Probe with a tiny range GET to discover size and prevent HEAD 403
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

        # Prepare output file
        fd, path = tempfile.mkstemp(prefix="tb_", suffix=f"_{meta.name}")
        os.close(fd)

        # If size unknown, single stream GET
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

        # Ranged download
        parts = math.ceil(size / CHUNK)
        written = 0
        with open(path, "wb") as f:
            for i in range(parts):
                start = i * CHUNK
                end = min(size - 1, start + CHUNK - 1)
                attempts = 3
                last_err = None
                for _ in range(attempts):
                    try:
                        rr = await client.get(url, headers=_headers_for(url, f"bytes={start}-{end}"))
                        if rr.status_code not in (200, 206):
                            last_err = RuntimeError(f"Chunk {i+1}/{parts} HTTP {rr.status_code}")
                            continue
                        f.write(rr.content)
                        written += len(rr.content)
                        if on_progress:
                            try:
                                on_progress(written, size)
                            except Exception:
                                pass
                        last_err = None
                        break
                    except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError) as e:
                        last_err = e
                        continue
                if last_err is not None:
                    raise RuntimeError(f"CDN refused chunk {i+1}/{parts}: {last_err}")

        if meta.size is None and written > 0:
            meta.size = written

        return path, meta
