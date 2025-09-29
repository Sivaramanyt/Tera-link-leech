# services/downloader.py
import os
import tempfile
import httpx
import random
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

def _browser_headers(file_url: str) -> dict:
    host = urlparse(file_url).netloc
    ip = ".".join(str(random.randint(1, 254)) for _ in range(4))
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "video/*,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",  # avoid gzip chunking issues
        "Connection": "keep-alive",
        "Referer": f"https://{host}/",
        "Origin": f"https://{host}",
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-site",
        "X-Forwarded-For": ip,
        "X-Real-IP": ip,
    }

async def fetch_to_temp(meta: FileMeta, timeout: int = 240) -> tuple[str, FileMeta]:
    headers = _browser_headers(meta.url)
    retries = 3
    last_err = None

    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
                # HEAD for size/name
                if meta.size is None or not meta.name:
                    try:
                        h = await client.head(meta.url)
                        # Some CDNs redirect on HEAD; follow_redirects=True handles that
                        clen = int(h.headers.get("content-length") or 0)
                        if clen > 0:
                            meta.size = clen
                        cd = h.headers.get("content-disposition", "")
                        if "filename=" in cd and not meta.name:
                            meta.name = cd.split("filename=")[-1].strip('"; ')
                    except Exception:
                        pass

                # GET content
                r = await client.get(meta.url)
                r.raise_for_status()

                ctype = (r.headers.get("content-type") or "").lower()
                if "text/html" in ctype or "text/plain" in ctype:
                    raise RuntimeError("Resolved URL returned HTML/text, not a file")

                if meta.size is None:
                    clen = int(r.headers.get("content-length") or 0)
                    if clen > 0:
                        meta.size = clen

                if not meta.name:
                    cd = r.headers.get("content-disposition", "")
                    if "filename=" in cd:
                        meta.name = cd.split("filename=")[-1].strip('"; ')
                    else:
                        meta.name = _name_from_url(str(r.url)) or "file"

                fd, path = tempfile.mkstemp(prefix="tb_", suffix=f"_{meta.name}")
                os.close(fd)
                written = 0
                with open(path, "wb") as f:
                    async for chunk in r.aiter_bytes():
                        f.write(chunk)
                        written += len(chunk)

                if meta.size is None and written > 0:
                    meta.size = written

                return path, meta

        except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError) as e:
            last_err = e
            if attempt < retries:
                continue
            raise RuntimeError(f"Connection lost during download after {retries} attempts") from e
        except Exception as e:
            # Other errors: re-raise with context
            raise

    if last_err:
        raise last_err
    raise RuntimeError("Unknown download error")
    
