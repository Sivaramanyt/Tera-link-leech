# services/terabox.py
import asyncio
import re
import json
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed
from services.downloader import FileMeta

# Optional external lib hook (safe if absent)
try:
    from terabox_linker import get_direct_link  # not required
except Exception:
    get_direct_link = None

# Regexes to extract pageData JSON Terabox embeds
_PAGE_DATA_RE = re.compile(r"window\.pageData\s*=\s*(\{.*?\});", re.DOTALL)
_DLINK_RE = re.compile(r'"dlink"\s*:\s*"([^"]+)"')
_NAME_RE = re.compile(r'"server_filename"\s*:\s*"([^"]+)"')
_SIZE_RE = re.compile(r'"size"\s*:\s*(\d+)')

class TeraboxResolver:
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def resolve(self, share_url: str) -> FileMeta:
        # 1) Try optional library
        url, name, size = await self._with_lib(share_url)
        if not url:
            # 2) Parse page HTML for pageData JSON with dlink/name/size
            url, name, size = await self._from_page(share_url)
        if not url:
            raise RuntimeError("Unable to resolve direct link")
        return FileMeta(name=name or "file", size=(int(size) if size else None), url=url)

    async def _with_lib(self, share_url: str):
        if not get_direct_link:
            return None, None, None
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: get_direct_link(share_url))
            return data.get("url"), data.get("name"), data.get("size")
        except Exception:
            return None, None, None

    async def _from_page(self, share_url: str):
        url = share_url.strip().replace("\\", "/")
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.terabox.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=25) as client:
            r = await client.get(url)
            r.raise_for_status()
            html = r.text

            # Extract pageData JSON if present
            m = _PAGE_DATA_RE.search(html)
            if m:
                raw = m.group(1)
                try:
                    data = json.loads(raw)
                    # Common locations:
                    # data["shareInfo"]["file_list"][0]["dlink"], ["server_filename"], ["size"]
                    file_list = (
                        data.get("shareInfo", {}).get("file_list")
                        or data.get("file_list")
                        or data.get("list")
                        or []
                    )
                    if isinstance(file_list, list) and file_list:
                        f0 = file_list[0]
                        dlink = f0.get("dlink")
                        name = f0.get("server_filename") or f0.get("filename")
                        size = f0.get("size")
                        if dlink:
                            return dlink.encode("utf-8").decode("unicode_escape"), name, size
                except Exception:
                    # Fallback to regex if JSON parse fails
                    pass

            # Regex fallback on HTML
            d = _DLINK_RE.search(html)
            if d:
                dlink = d.group(1).encode("utf-8").decode("unicode_escape")
                name = None
                n = _NAME_RE.search(html)
                if n:
                    name = n.group(1)
                s = _SIZE_RE.search(html)
                size = int(s.group(1)) if s else None
                return dlink, name, size

            # As last resort, follow possible redirect and infer headers
            try:
                r2 = await client.get(url)
                final_url = str(r2.url)
                if final_url and "terabox" not in final_url:
                    # Try to head the CDN URL
                    h = await client.head(final_url)
                    size = int(h.headers.get("content-length") or 0) or None
                    cd = h.headers.get("content-disposition", "")
                    name = None
                    if "filename=" in cd:
                        name = cd.split("filename=")[-1].strip('"; ')
                    return final_url, name, size
            except Exception:
                pass

        return None, None, None
    
