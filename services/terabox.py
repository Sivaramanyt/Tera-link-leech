# services/terabox.py
import asyncio
import re
import json
import httpx
from urllib.parse import urlparse, parse_qs
from tenacity import retry, stop_after_attempt, wait_fixed
from services.downloader import FileMeta

# Optional external lib
try:
    from terabox_linker import get_direct_link  # type: ignore
except Exception:
    get_direct_link = None

_PAGE_DATA_RE = re.compile(r"window\.pageData\s*=\s*(\{.*?\});", re.DOTALL)

class TeraboxResolver:
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def resolve(self, share_url: str) -> FileMeta:
        url, name, size = await self._with_lib(share_url)
        if not url:
            url, name, size = await self._resolve_terabox_or_1024(share_url)
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

    async def _resolve_terabox_or_1024(self, share_url: str):
        url = share_url.strip().replace("\\", "/")
        base_headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.terabox.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(headers=base_headers, follow_redirects=True, timeout=25) as client:
            r = await client.get(url)
            r.raise_for_status()
            final_url = str(r.url)
            html = r.text
            host = urlparse(final_url).netloc.lower()

            # Path A: Official terabox pageData JSON has dlink
            m = _PAGE_DATA_RE.search(html)
            if m:
                try:
                    data = json.loads(m.group(1))
                    files = (
                        data.get("shareInfo", {}).get("file_list")
                        or data.get("file_list")
                        or data.get("list")
                        or []
                    )
                    if isinstance(files, list) and files:
                        f0 = files[0]
                        dlink = f0.get("dlink")
                        name = f0.get("server_filename") or f0.get("filename")
                        size = f0.get("size")
                        if dlink:
                            return dlink.encode("utf-8").decode("unicode_escape"), name, size
                except Exception:
                    pass

            # Path B: 1024terabox/1024tera flow using share/list then transfer to get temp dlink
            q = parse_qs(urlparse(final_url).query)
            surl = (q.get("surl") or q.get("shorturl") or [None])[0]
            pwd = (q.get("pwd") or q.get("password") or [None])[0]
            if any(k in host for k in ["1024tera", "1024terabox"]) and surl:
                api_list = f"https://www.1024tera.com/share/list?surl={surl}&page=1&pageSize=50"
                if pwd:
                    api_list += f"&pwd={pwd}"
                try:
                    jl = await client.get(api_list, headers={"Accept": "application/json"})
                    jl.raise_for_status()
                    data = jl.json()
                    files = data.get("list") or data.get("data") or data.get("files") or []
                    if isinstance(files, list) and files:
                        f0 = files[0]
                        fs_id = f0.get("fs_id") or f0.get("fsid") or f0.get("id")
                        name = f0.get("server_filename") or f0.get("filename")
                        size = f0.get("size")
                        # If list already contains dlink, use it
                        dlink = f0.get("dlink") or f0.get("url")
                        if dlink:
                            return dlink, name, size
                        # Otherwise call transfer API to obtain temp direct link
                        # Common endpoints seen in mirrors:
                        # - /share/transfer {surl, fs_id}
                        # - /share/transfer? s.t. JSON body
                        # - /api/file/transfer
                        transfer_candidates = [
                            "https://www.1024tera.com/share/transfer",
                            "https://www.1024tera.com/api/file/transfer",
                        ]
                        payload = {"surl": surl, "fs_id": fs_id}
                        if pwd: payload["pwd"] = pwd
                        for ep in transfer_candidates:
                            try:
                                jt = await client.post(
                                    ep,
                                    headers={
                                        "Accept": "application/json, text/plain, */*",
                                        "Content-Type": "application/json;charset=UTF-8",
                                    },
                                    json=payload,
                                )
                                if jt.status_code == 200:
                                    jd = jt.json()
                                    # Look for direct url fields
                                    cand = (
                                        jd.get("dlink")
                                        or jd.get("url")
                                        or jd.get("data", {}).get("dlink")
                                        or jd.get("data", {}).get("url")
                                    )
                                    if cand:
                                        return cand, name, size
                            except Exception:
                                continue
                except Exception:
                    pass

            # Path C: as a very last resort, try to follow non-terabox CDN redirect and head it
            try:
                if final_url and "terabox" not in final_url:
                    h = await client.head(final_url)
                    size = int(h.headers.get("content-length") or 0) or None
                    cd = h.headers.get("content-disposition", "")
                    name = None
                    if "filename=" in cd:
                        name = cd.split("filename=")[-1].strip('\"; ')
                    return final_url, name, size
            except Exception:
                pass

        return None, None, None
            
