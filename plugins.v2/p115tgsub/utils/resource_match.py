"""资源年份匹配工具。"""
import re
from typing import Any, Iterable

_YEAR_AFTER_TITLE_TEMPLATE = r"{title}(?:\s|[._\-（(\[【])*\s*((?:19|20)\d{{2}})(?!\d|-\d)"


def _years_after_title(value: Any, title: Any) -> set[str]:
    """仅识别片名后紧邻的年份，避免正文中的发布日期参与候选拒绝。"""
    title_text = str(title or "").strip()
    if not title_text:
        return set()
    pattern = re.compile(_YEAR_AFTER_TITLE_TEMPLATE.format(title=re.escape(title_text)), re.IGNORECASE)
    return set(pattern.findall(str(value or "")))


def resource_year_matches(
    expected_year: Any,
    candidate_title: Any,
    *,
    title: Any = "",
    canonical_titles: Iterable[Any] = (),
) -> bool:
    """只以片名紧邻的资源年份校验，正文日期不参与拒绝。"""
    target = str(expected_year or "").strip()
    if not target:
        return True
    for value in (candidate_title, *canonical_titles):
        years = _years_after_title(value, title)
        if years and target not in years:
            return False
    return True
