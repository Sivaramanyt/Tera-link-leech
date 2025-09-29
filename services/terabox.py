# services/terabox.py
import asyncio
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_fixed
from services.downloader import FileMeta

# Third-party resolver (pinned in requirements)
try:
    from terabox_linker import get_direct_link  # hypothetical API
except Exception:
    get_direct_link = None

@dataclass
class ResolveResult:
    name: str
    size: int | None
    direct_url: str

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
            # Expected: {"url": "...", "name": "...", "size": 123}
            return data.get("url"), data.get("name"), data.get("size")
        except Exception:
            return None, None, None

    async def _resolve_fallback(self, share_url: str):
        # Minimal fallback: attempt to parse Terabox share redirect or JSON
        # Placeholder logic; can be expanded with HTML parsing if needed.
        return None, None, None
