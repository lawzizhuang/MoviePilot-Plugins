"""订阅资源搜索处理器。"""
from typing import Any, Dict, List, Optional

from app.log import logger
from app.schemas import MediaInfo
from app.schemas.types import MediaType


class SearchHandler:
    """只使用 Telegram 公开频道搜索 115 分享链接。"""

    def __init__(self, telegram_client, telegram_enabled: bool = False) -> None:
        self._telegram_client = telegram_client
        self._telegram_enabled = bool(telegram_enabled)

    def get_enabled_sources(self) -> List[str]:
        if self._telegram_enabled and self._telegram_client and self._telegram_client.channels:
            return ["telegram"]
        return []

    def search_resources(
        self,
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return self.search_single_source("telegram", mediainfo, media_type, season)

    def search_single_source(
        self,
        source: str,
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if source != "telegram":
            logger.warning(f"未知的搜索源：{source}")
            return []
        if not self._telegram_enabled or not self._telegram_client:
            return []

        for keyword in self._build_keywords(mediainfo, media_type, season):
            logger.info(f"使用 Telegram 公开频道搜索：{mediainfo.title}，关键词：{keyword!r}")
            results = self._telegram_client.search_115_resources(keyword, required_title=mediainfo.title)
            if results:
                logger.info(f"Telegram 关键词 {keyword!r} 找到 {len(results)} 个 115 资源")
                return results
        return []

    @staticmethod
    def _build_keywords(
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int],
    ) -> List[str]:
        title = str(getattr(mediainfo, "title", "") or "").strip()
        year = str(getattr(mediainfo, "year", "") or "").strip()
        if not title:
            return []

        candidates: List[str] = []
        if media_type == MediaType.TV and season and season > 1:
            candidates.extend([f"{title} 第{season}季", f"{title} {season}"])
        if year:
            candidates.append(f"{title} {year}")
        candidates.append(title)

        output: List[str] = []
        seen = set()
        for keyword in candidates:
            normalized = keyword.casefold()
            if normalized not in seen:
                seen.add(normalized)
                output.append(keyword)
        return output

    # 与旧同步处理器保持同一接口；Telegram 源不存在积分状态。
    def set_data_funcs(self, get_data_func, save_data_func) -> None:
        return None

    def reset_task_spent_points(self) -> None:
        return None

    def reset_sub_spent_points(self, sub_key: str = "") -> None:
        return None

    def clear_sub_points(self, sub_key: str) -> None:
        return None
