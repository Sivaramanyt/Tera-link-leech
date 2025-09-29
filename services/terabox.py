# services/terabox.py
import asyncio
import re
import json
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed
from services.downloader import FileMeta

# Optional external lib (not required). If added to requirements later, it will be used.
try:
    from terabox_linker import get_direct_link  # type: ignore
except Exception:
    get_direct_link = None

# Regex to capture the big JSON Terabox embeds on share pages
_PAGE_DATA_RE = re.compile(r"window\.pageData\s*=\s*(\{.*?\});", re.DOTALL)
_DLINK_RE = re.compile(r'"dlink"\s*:\s*"([^"]+)"')
_NAME_RE = re.compile(r'"server_filename"\s*:\s*"([^"]+)"')
_SIZE_RE = re.compile(r'"size"\s*:\s*(\d+)')

class TeraboxResolver:
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def resolve(self, share_url: str) -> FileMeta:
        # 1) Try optional third-party library if present
        url, name, size = await self._with_lib(share_url)
        if not url:
            # 2) Parse the share page for embedded JSON/regex fields
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

            # A) window.pageData JSON used on terabox.com
            m = _PAGE_DATA_RE.search(html)
            if m:
                raw = m.group(1)
                try:
                    data = json.loads(raw)
                    # Common locations for file list
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
                            direct = dlink.encode("utf-8").decode("unicode_escape")
                            return direct, name, size
                except Exception:
                    # If JSON parse fails, fall through to regex
                    pass

            # B) Regex fallback on HTML when JSON extraction fails
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

            # C) 1024terabox/1024tera variant: script defines `var list = [...]`
            try:
                jmatch = re.search(r"var\s+list\s*=\s*(\[\s*{.*?}\s*]);", html, re.DOTALL)
                if jmatch:
                    arr = json.loads(jmatch.group(1))
                    if isinstance(arr, list) and arr:
                        f0 = arr[0]
                        dlink = f0.get("dlink") or f0.get("url")
                        name = f0.get("server_filename") or f0.get("filename")
                        size = f0.get("size")
                        if dlink:
                            return dlink, name, size
            except Exception:
                pass

            # D) As last resort, follow redirect to CDN and infer headers
            try:
                r2 = await client.get(url)
                final_url = str(r2.url)
                if final_url and "terabox" not in final_url:
                    # Try to head the CDN URL for size and filename
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
            
