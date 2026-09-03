"""订阅资源搜索处理器。"""
from typing import Any, Dict, List, Optional

from app.log import logger
from app.schemas import MediaInfo
from app.schemas.types import MediaType


class SearchHandler:
    """使用 Telegram 公开频道搜索 115 与夸克分享链接。"""

    def __init__(self, telegram_client, telegram_enabled: bool = False, seedhub_client=None,
                 seedhub_enabled: bool = False, seedhub_channel: str = "seedhub_pro",
                 fourkmonitor_client=None, fourkmonitor_enabled: bool = False) -> None:
        self._telegram_client = telegram_client
        self._telegram_enabled = bool(telegram_enabled)
        self._seedhub_client = seedhub_client
        self._seedhub_enabled = bool(seedhub_enabled)
        self._seedhub_channel = str(seedhub_channel or "seedhub_pro").strip()
        self._fourkmonitor_client = fourkmonitor_client
        self._fourkmonitor_enabled = bool(fourkmonitor_enabled)

    def get_enabled_sources(self) -> List[str]:
        if self._telegram_enabled and self._telegram_client and self._telegram_client.channels:
            return ["telegram"]
        if self._fourkmonitor_enabled and self._fourkmonitor_client:
            return ["4kmonitor"]
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
        prefer_recent: bool = False,
    ) -> List[Dict[str, Any]]:
        """搜索夸克分享候选（115 优先策略的兜底源）。"""
        if not self._telegram_enabled or not self._telegram_client:
            return []
        for keyword in self._build_keywords(mediainfo, media_type, season):
            logger.info(f"使用 Telegram 公开频道搜索夸克资源：{mediainfo.title}，关键词：{keyword!r}")
            results = self._telegram_client.search_quark_resources(
                keyword, required_title=mediainfo.title, prefer_recent=prefer_recent
            )
            if results:
                logger.info(f"Telegram 关键词 {keyword!r} 找到 {len(results)} 个夸克资源")
                return results
        return []

    def search_offline_resources(
        self,
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int] = None,
        preferred_episodes: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """搜索 Telegram 公开消息直接发布的 ED2K / 磁力候选。"""
        if not self._telegram_enabled or not self._telegram_client:
            return []
        for keyword in self._build_keywords(mediainfo, media_type, season, preferred_episodes):
            logger.info(f"使用 Telegram 公开频道搜索 115 离线资源：{mediainfo.title}，关键词：{keyword!r}")
            results = self._telegram_client.search_offline_resources(
                keyword, required_title=mediainfo.title, preferred_season=int(season or 1),
                preferred_episodes=preferred_episodes or (),
            )
            if results:
                logger.info(f"Telegram 关键词 {keyword!r} 找到 {len(results)} 个 ED2K/磁力候选")
                return results
        return []

    def search_seedhub_resources(
        self,
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int] = None,
        prefer_recent: bool = False,
    ) -> List[Dict[str, Any]]:
        """经指定 SeedHub Telegram 公开频道定位电影页，再读取公开磁力候选。"""
        if not self._seedhub_enabled or not self._seedhub_client or not self._telegram_enabled or not self._telegram_client:
            return []
        seen = set()
        output: List[Dict[str, Any]] = []
        for keyword in self._build_keywords(mediainfo, media_type, season):
            if getattr(self._seedhub_client, "blocked", False):
                break
            logger.info(f"使用 SeedHub 公开频道搜索磁力资源：{mediainfo.title}，关键词：{keyword!r}")
            pages = self._telegram_client.search_seedhub_movie_pages(
                keyword, required_title=mediainfo.title, channel=self._seedhub_channel,
                prefer_recent=prefer_recent,
            )
            for page in pages:
                if getattr(self._seedhub_client, "blocked", False):
                    break
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

    def search_fourkmonitor_resources(
        self,
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """按 TMDB ID 检索 4K Monitor 匿名免费候选；剧集仅返回明确匹配目标季集的资源。"""
        if not self._fourkmonitor_enabled or not self._fourkmonitor_client:
            return []
        if getattr(self._fourkmonitor_client, "blocked", False):
            return []
        logger.info(f"使用 4K Monitor 精确 TMDB 检查免费磁力资源：{mediainfo.title}")
        resources = self._fourkmonitor_client.list_resources(mediainfo, media_type)
        if media_type == MediaType.TV:
            resources = [
                resource for resource in resources
                if self._fourkmonitor_episode_range(str(resource.get("title") or ""), int(season or 1))
            ]
        if resources:
            logger.info(f"4K Monitor/TMDB 免费候选：{len(resources)} 条")
        return resources

    @staticmethod
    def _fourkmonitor_episode_range(title: str, season: int) -> set[int]:
        """仅识别明确的目标季集数范围，剧集资源一律以离线队列逐集确认。"""
        import re
        from ..utils import FileMatcher

        text = str(title or "")
        if FileMatcher._contains_other_season(text, season):
            return set()
        match = re.search(r"(?:E|EP)\s*(\d{1,3})\s*[-~～至到]\s*(\d{1,3})(?!\d)", text, re.IGNORECASE)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            return set(range(start, end + 1)) if 1 <= start <= end <= 999 else set()
        match = re.search(r"[Ss](\d{1,2})[Ee](\d{1,3})(?!\d)", text)
        if match:
            return {int(match.group(2))} if int(match.group(1)) == season else set()
        match = re.search(r"(?:^|[^A-Za-z0-9])(?:EP|E)\s*(\d{1,3})(?!\d)", text, re.IGNORECASE)
        if match and season == 1:
            return {int(match.group(1))}
        match = re.search(r"(?:全|\[全)\s*(\d{1,3})\s*集", text)
        return set(range(1, int(match.group(1)) + 1)) if match else set()

    def search_single_source(
        self,
        source: str,
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int] = None,
        preferred_episodes: Optional[List[int]] = None,
        prefer_recent: bool = False,
    ) -> List[Dict[str, Any]]:
        if source == "4kmonitor":
            return []
        if source != "telegram":
            logger.warning(f"未知的搜索源：{source}")
            return []
        if not self._telegram_enabled or not self._telegram_client:
            return []

        for keyword in self._build_keywords(mediainfo, media_type, season, preferred_episodes):
            logger.info(f"使用 Telegram 公开频道搜索：{mediainfo.title}，关键词：{keyword!r}")
            results = self._telegram_client.search_115_resources(
                keyword, required_title=mediainfo.title, preferred_season=int(season or 1),
                preferred_episodes=preferred_episodes or (), prefer_recent=prefer_recent,
            )
            if results:
                logger.info(f"Telegram 关键词 {keyword!r} 找到 {len(results)} 个 115 资源")
                return results
        return []

    @staticmethod
    def is_followup_tv(
        existing_episodes, missing_episodes, start_episode: int = 1, total_episode: int = 0,
    ) -> bool:
        """仅将“已完整拥有前序集、连续缺少季末集”的场景视为追更。"""
        try:
            existing = {int(episode) for episode in existing_episodes if int(episode) > 0}
            missing = sorted({int(episode) for episode in missing_episodes if int(episode) > 0})
            start = max(1, int(start_episode or 1))
            total = int(total_episode or 0)
        except (TypeError, ValueError):
            return False
        if not existing or not missing or missing != list(range(missing[0], missing[-1] + 1)):
            return False
        if total and missing[-1] != total:
            return False
        return missing[0] > start and set(range(start, missing[0])).issubset(existing)

    @staticmethod
    def _build_keywords(
        mediainfo: MediaInfo,
        media_type: MediaType,
        season: Optional[int],
        preferred_episodes: Optional[List[int]] = None,
    ) -> List[str]:
        title = str(getattr(mediainfo, "title", "") or "").strip()
        year = str(getattr(mediainfo, "year", "") or "").strip()
        if not title:
            return []

        candidates: List[str] = []
        # 仅对少量连续待补集启用精确检索；整季缺失仍保留泛搜索，避免放大
        # Telegram 公开请求及后续 115 分享校验压力。
        target_episodes = sorted({int(item) for item in preferred_episodes or [] if int(item) > 0})
        if media_type == MediaType.TV and season and 0 < len(target_episodes) <= 3:
            for episode in target_episodes:
                candidates.append(f"{title} S{int(season):02d}E{episode:02d}")
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
