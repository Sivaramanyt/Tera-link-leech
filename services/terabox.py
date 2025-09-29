# services/terabox.py
import asyncio
import re
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_fixed
import httpx
from services.downloader import FileMeta

try:
    from terabox_linker import get_direct_link  # if added later
except Exception:
    get_direct_link = None

_JSON_RE = re.compile(r'window\.pageData\s*=\s*(\{.*?\});', re.DOTALL)
_NAME_RE = re.compile(r'"server_filename"\s*:\s*"([^"]+)"')
_SIZE_RE = re.compile(r'"size"\s*:\s*(\d+)')
_URL_RE = re.compile(r'"dlink"\s*:\s*"([^"]+)"')

class TeraboxResolver:
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def resolve(self, share_url: str) -> FileMeta:
        direct_url, name, size = await self._resolve_with_library(share_url)
        if not direct_url:
            direct_url, name, size = await self._resolve_fallback(share_url)
        if not direct_url:
            raise RuntimeError("Unable to resolve direct link")
        return FileMeta(name=name or "file", size=size, url=direct_url)

    async def _resolve_with_library(self, share_url: str):
        if get_direct_link is None:
            return None, None, None
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: get_direct_link(share_url))
            return data.get("url"), data.get("name"), data.get("size")
        except Exception:
            return None, None, None

    async def _resolve_fallback(self, share_url: str):
        # Normalize possible backslashes from copied links
        url = share_url.replace("\\", "/").strip()
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.terabox.com/",
        }
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=20) as client:
            r = await client.get(url)
            r.raise_for_status()
            html = r.text

            # Look for JSON blob with pageData
            m = _JSON_RE.search(html)
            if m:
                blob = m.group(1)
                name = _NAME_RE.search(blob)
                size = _SIZE_RE.search(blob)
                dlink = _URL_RE.search(blob)
                file_name = name.group(1) if name else None
                file_size = int(size.group(1)) if size else None
                direct = dlink.group(1).encode("utf-8").decode("unicode_escape") if dlink else None
                return direct, file_name, file_size

            # As a fallback, try an API-like redirect present in some shares
            # Many Terabox shares expose a final redirect to a file CDN; follow it
            # HEAD to get content-length and name
            r2 = await client.get(url)
            if r2.is_redirect and r2.next_request:
                final = r2.next_request.url
                # Try to peek headers
                h = await client.head(final)
                size = int(h.headers.get("content-length") or 0) or None
                name = None
                cd = h.headers.get("content-disposition", "")
                if "filename=" in cd:
                    name = cd.split("filename=")[-1].strip('"; ')
                return str(final), name, size

        return None, None, None
        
