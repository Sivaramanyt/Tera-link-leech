# services/downloader.py
import os
import tempfile
import httpx
from dataclasses import dataclass

@dataclass
class FileMeta:
    name: str
    size: int | None
    url: str

    def human_size(self) -> str:
        if self.size is None:
            return "unknown"
        size = self.size
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"

async def fetch_to_temp(meta: FileMeta, timeout: int = 120) -> tuple[str, FileMeta]:
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        # Try HEAD for size/filename if missing
        if meta.size is None:
            try:
                r = await client.head(meta.url)
                size = int(r.headers.get("content-length") or 0)
                meta.size = size if size > 0 else None
            except Exception:
                pass

        r = await client.get(meta.url)
        r.raise_for_status()

        # Infer filename from headers if needed
        fname = meta.name
        cd = r.headers.get("content-disposition", "")
        if "filename=" in cd:
            fname = cd.split("filename=")[-1].strip('"; ')
        if not fname:
            fname = "file.bin"

        fd, path = tempfile.mkstemp(prefix="tb_", suffix=f"_{fname}")
        os.close(fd)
        with open(path, "wb") as f:
            async for chunk in r.aiter_bytes():
                f.write(chunk)

        # Update meta with final name
        meta.name = fname
        return path, meta
