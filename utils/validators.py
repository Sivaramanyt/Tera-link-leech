# utils/validators.py
import re

_TB_RE = re.compile(r"(terabox|nephobox|4funbox)\.com", re.IGNORECASE)

def is_terabox_url(url: str) -> bool:
    return bool(_TB_RE.search(url))

def sanitize_filename(name: str) -> str:
    return re.sub(r"[^\w\-. ]", "_", name)
