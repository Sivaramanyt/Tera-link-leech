# services/downloader.py
import os
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

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.terabox.com/",
    "Accept": "*/*",
}

async def fetch_to_temp(meta: FileMeta, timeout: int = 180) -> tuple[str, FileMeta]:
    async with httpx.AsyncClient(timeout=timeout, headers=DEFAULT_HEADERS, follow_redirects=True) as client:
        # Try HEAD to get size/name
        if meta.size is None or not meta.name:
            try:
                h = await client.head(meta.url)
                clen = int(h.headers.get("content-length") or 0)
                if clen > 0:
                    meta.size = clen
                cd = h.headers.get("content-disposition", "")
                if "filename=" in cd and not meta.name:
                    meta.name = cd.split("filename=")[-1].strip('"; ')
            except Exception:
                pass

        # GET for the actual content
        r = await client.get(meta.url)
        r.raise_for_status()

        # Guard: refuse HTML/text responses which indicate the resolver returned a page, not a file
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/html" in ctype or "text/plain" in ctype:
            raise RuntimeError("Resolved URL returned HTML/text, not a file")

        # Re-check size and filename
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

        # Stream to temp file
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
                
