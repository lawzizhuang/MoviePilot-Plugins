"""资源候选的敏感信息脱敏工具。"""
import re
from typing import Any

_URL_RE = re.compile(r"https?://[^\s<>\"'，。；;]+", re.IGNORECASE)
_PASSWORD_RE = re.compile(
    r"(?:提取码|访问码|密码|passcode|code)\s*[：:=]?\s*[A-Za-z0-9]{4,16}",
    re.IGNORECASE,
)


def sanitize_resource_text(value: Any, limit: int = 160) -> str:
    """移除候选文本中的完整 URL 与提取码，供日志和下载历史使用。"""
    text = str(value or "")
    text = _URL_RE.sub("[链接已脱敏]", text)
    text = _PASSWORD_RE.sub("[提取码已脱敏]", text)
    text = " ".join(text.split())
    return text[: max(20, min(int(limit or 160), 500))]
