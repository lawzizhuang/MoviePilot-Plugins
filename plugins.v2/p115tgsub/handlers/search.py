"""订阅资源搜索处理器。"""
from typing import Any, Dict, List, Optional

from app.log import logger
from app.schemas import MediaInfo
from app.schemas.types import MediaType


class SearchHandler:
    """使用 Telegram 公开频道搜索 115 与夸克分享链接。"""

    def __init__(self, telegram_client, telegram_enabled: bool = False, seedhub_client=None,
                 seedhub_enabled: bool = False, seedhub_channel: str = "seedhub_pro") -> None:
        self._telegram_client = telegram_client
        self._telegram_enabled = bool(telegram_enabled)
        self._seedhub_client = seedhub_client
        self._seedhub_enabled = bool(seedhub_enabled)
        self._seedhub_channel = str(seedhub_channel or "seedhub_pro").strip()

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

    def search_quark_resources(
        self,
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """搜索夸克分享候选（115 优先策略的兜底源）。"""
        if not self._telegram_enabled or not self._telegram_client:
            return []
        for keyword in self._build_keywords(mediainfo, media_type, season):
            logger.info(f"使用 Telegram 公开频道搜索夸克资源：{mediainfo.title}，关键词：{keyword!r}")
            results = self._telegram_client.search_quark_resources(keyword, required_title=mediainfo.title)
            if results:
                logger.info(f"Telegram 关键词 {keyword!r} 找到 {len(results)} 个夸克资源")
                return results
        return []

    def search_offline_resources(
        self,
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """搜索 Telegram 公开消息直接发布的 ED2K / 磁力候选。"""
        if not self._telegram_enabled or not self._telegram_client:
            return []
        for keyword in self._build_keywords(mediainfo, media_type, season):
            logger.info(f"使用 Telegram 公开频道搜索 115 离线资源：{mediainfo.title}，关键词：{keyword!r}")
            results = self._telegram_client.search_offline_resources(keyword, required_title=mediainfo.title)
            if results:
                logger.info(f"Telegram 关键词 {keyword!r} 找到 {len(results)} 个 ED2K/磁力候选")
                return results
        return []

    def search_seedhub_resources(
        self,
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """经指定 SeedHub Telegram 公开频道定位电影页，再读取公开磁力候选。"""
        if not self._seedhub_enabled or not self._seedhub_client or not self._telegram_enabled or not self._telegram_client:
            return []
        seen = set()
        output: List[Dict[str, Any]] = []
        for keyword in self._build_keywords(mediainfo, media_type, season):
            logger.info(f"使用 SeedHub 公开频道搜索磁力资源：{mediainfo.title}，关键词：{keyword!r}")
            pages = self._telegram_client.search_seedhub_movie_pages(
                keyword, required_title=mediainfo.title, channel=self._seedhub_channel
            )
            for page in pages:
                for resource in self._seedhub_client.list_resources(page.get("url") or ""):
                    key = str(resource.get("seed_id") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    resource["telegram_channel"] = page.get("channel") or ""
                    resource["telegram_message_id"] = page.get("message_id") or ""
                    output.append(resource)
            if output:
                return output
        return []

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
