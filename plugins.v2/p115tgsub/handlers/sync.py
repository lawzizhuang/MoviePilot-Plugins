"""
同步处理模块
负责核心的同步逻辑：处理电影订阅、处理电视剧订阅
"""
import datetime
import re
import unicodedata
from urllib.parse import parse_qs, unquote, urlsplit
from typing import List, Dict, Any, Set, Optional, Callable

from app.core.config import global_vars
from app.core.metainfo import MetaInfo
from app.chain.download import DownloadChain
from app.db import SessionFactory
from app.db.subscribe_oper import SubscribeOper
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.log import logger
from app.schemas import MediaInfo
from app.schemas.types import MediaType, NotificationType
from app.utils.string import StringUtils

from ..utils import FileMatcher, SubscribeFilter, resource_year_matches, sanitize_resource_text
from .offline_queue import OfflineQueue
from .search import SearchHandler
from .subscribe import SubscribeHandler


class SyncHandler:
    """同步处理器"""

    def __init__(
        self,
        p115_manager,
        search_handler: SearchHandler,
        subscribe_handler: SubscribeHandler,
        chain,
        save_path: str,
        movie_save_path: str,
        max_transfer_per_sync: int = 50,
        batch_size: int = 20,
        skip_other_season_dirs: bool = True,
        notify: bool = False,
        post_message_func: Callable = None,
        get_data_func: Callable = None,
        save_data_func: Callable = None,
        dry_run: bool = False
    ):
        """
        初始化同步处理器

        :param p115_manager: 115 客户端管理器
        :param search_handler: 搜索处理器
        :param subscribe_handler: 订阅处理器
        :param chain: MediaChain 实例
        :param save_path: 电视剧转存目录
        :param movie_save_path: 电影转存目录
        :param max_transfer_per_sync: 单次同步最大转存数量
        :param batch_size: 批量转存每批文件数
        :param skip_other_season_dirs: 跳过其他季目录
        :param notify: 是否发送通知
        :param post_message_func: 发送消息的函数
        :param get_data_func: 获取数据的函数
        :param save_data_func: 保存数据的函数
        :param dry_run: 仅验证分享与文件匹配，不实际转存或修改订阅
        """
        self._p115_manager = p115_manager
        self._search_handler = search_handler
        self._subscribe_handler = subscribe_handler
        self._chain = chain
        self._save_path = save_path
        self._movie_save_path = movie_save_path
        self._max_transfer_per_sync = max_transfer_per_sync
        self._batch_size = batch_size
        self._skip_other_season_dirs = skip_other_season_dirs
        self._notify = notify
        self._post_message = post_message_func
        self._get_data = get_data_func
        self._save_data = save_data_func
        self._dry_run = bool(dry_run)
        self._offline_enabled = False
        self._offline_max_per_sync = 0
        self._offline_queue = None
        self._offline_submitted_this_run = 0

    def configure_offline_download(self, enabled: bool, max_per_sync: int, max_wait_hours: int) -> None:
        self._offline_enabled = bool(enabled)
        self._offline_max_per_sync = max(1, min(int(max_per_sync or 5), 20))
        if self._get_data and self._save_data:
            self._offline_queue = OfflineQueue(self._get_data, self._save_data, max_wait_hours=max_wait_hours)

    @staticmethod
    def _offline_file_name(resource: Dict[str, Any]) -> str:
        """从 ED2K 或磁力 dn 参数提取文件名；缺少文件名的磁力不提交。"""
        url = str(resource.get("url") or "")
        match = re.match(r"ed2k://\|file\|([^|]+)\|", url, re.IGNORECASE)
        if match:
            return unquote(match.group(1))
        if url.casefold().startswith("magnet:"):
            names = parse_qs(urlsplit(url).query).get("dn") or []
            return unquote(str(names[0])) if names else ""
        return ""

    def _submit_offline(self, resource: Dict[str, Any], subscribe, mediainfo: MediaInfo, save_dir: str,
                        media_type: str, season: int = 0, episode: int = 0) -> bool:
        """提交前先完成文件名/季集校验；仅提交至现有插件配置的目标目录。"""
        if not self._offline_enabled or not self._offline_queue:
            return False
        url = str(resource.get("url") or "")
        resource_title = str(resource.get("title") or "")
        file_name = self._offline_file_name(resource)
        if not url or not self._resource_title_matches(mediainfo, resource_title):
            return False
        if not resource_year_matches(mediainfo.year, resource_title, title=mediainfo.title):
            return False
        if media_type == "电视剧" and not FileMatcher.match_episode_file(
            [{"name": file_name, "is_dir": False}], mediainfo.title, season, episode
        ):
            return False
        if media_type == "电影" and not FileMatcher.match_movie_file(
            [{"name": file_name, "is_dir": False, "size": 1024 * 1024 * 1024}], mediainfo.title
        ):
            return False
        if self._offline_submitted_this_run >= self._offline_max_per_sync:
            return False
        if media_type == "电视剧" and episode in self._offline_queue.pending_episodes(subscribe.id, season):
            return False
        if media_type == "电影" and self._offline_queue.pending_movie(subscribe.id):
            return False
        if self._dry_run:
            # 测试模式严格只读：仅验证既有目标目录可见性，不创建目录、不提交云下载。
            target_cid = self._p115_manager.get_pid_by_path(save_dir, mkdir=False)
            if target_cid == -1:
                logger.warning(f"测试模式：115 离线下载目标目录尚不存在，正式模式会按插件路径创建：{save_dir}")
            else:
                logger.info(f"测试模式：115 离线下载目标目录可用：{save_dir}")
            logger.info(f"测试模式：已验证 115 离线{resource.get('kind', '资源')}候选，不提交任务：{file_name}")
            return True
        if not self._p115_manager.submit_offline_task(url, save_dir):
            return False
        queued = self._offline_queue.enqueue(
            subscribe_id=subscribe.id, title=mediainfo.title, year=mediainfo.year, media_type=media_type,
            savepath=save_dir, resource_key=self._p115_manager.offline_resource_key(url), file_name=file_name,
            season=season, episode=episode,
        )
        if queued:
            self._offline_submitted_this_run += 1
            target = f" S{season:02d}E{episode:02d}" if episode else ""
            logger.info(f"115 离线下载已进入待确认队列：{mediainfo.title}{target}")
        return queued

    def begin_run(self) -> None:
        self._offline_submitted_this_run = 0
        if self._offline_queue:
            expired = self._offline_queue.expire()
            if expired:
                logger.warning(f"115 离线下载超时并已释放夸克兜底：{expired} 项")

    def offline_pending(self, subscribe_id: Any, season: int = 0, media_type: str = "") -> Set[int] | bool:
        if not self._offline_queue:
            return set() if media_type == "电视剧" else False
        if media_type == "电视剧":
            return self._offline_queue.pending_episodes(subscribe_id, season)
        return self._offline_queue.pending_movie(subscribe_id)

    def offline_stats(self) -> Dict[str, int]:
        return self._offline_queue.stats() if self._offline_queue else {"pending": 0, "completed": 0, "expired": 0}

    def _reconcile_offline_movie(self, subscribe, mediainfo: MediaInfo, save_dir: str) -> bool:
        if not self._offline_queue or not self._offline_queue.pending_movie(subscribe.id):
            return
        existing = self._p115_manager.list_files(save_dir)
        if FileMatcher.match_movie_file(existing, mediainfo.title):
            self._offline_queue.complete_movie(subscribe.id)
            if not self._dry_run:
                self._subscribe_handler.check_and_finish_subscribe(subscribe, mediainfo, success_episodes=[1])
            logger.info(f"115 离线下载文件已确认存在：{mediainfo.title}")
            return True
        return False

    def _reconcile_offline_tv(self, subscribe, mediainfo: MediaInfo, season: int, save_dir: str) -> Set[int]:
        if not self._offline_queue:
            return set()
        pending = self._offline_queue.pending_episodes(subscribe.id, season)
        if not pending:
            return set()
        existing = FileMatcher.check_existing_episodes(self._p115_manager, mediainfo, season, save_dir)
        completed = self._offline_queue.complete_tv(subscribe.id, season, existing)
        completed_episodes = {int(item.get("episode") or 0) for item in completed}
        if completed_episodes and not self._dry_run:
            self._subscribe_handler.check_and_finish_subscribe(
                subscribe, mediainfo, success_episodes=sorted(completed_episodes)
            )
        if completed:
            logger.info(f"115 离线下载文件已确认存在：{len(completed)} 集")
        return pending - completed_episodes

    def _search_offline_resources(self, mediainfo: MediaInfo, media_type: MediaType, season: int = None,
                                  preferred_episodes: Optional[List[int]] = None,
                                  prefer_recent: bool = False) -> List[Dict[str, Any]]:
        if not self._offline_enabled:
            return []
        return self._search_handler.search_offline_resources(
            mediainfo, media_type, season, preferred_episodes=preferred_episodes,
            prefer_recent=prefer_recent,
        )

    @staticmethod
    def _seedhub_episode_range(title: str, season: int) -> Set[int]:
        """从 SeedHub 发布名识别清晰的单季集数范围；模糊条目一律不自动提交。"""
        text = str(title or "")
        if FileMatcher._contains_other_season(text, season):
            return set()
        match = re.search(r"(?:EP|E)\s*(\d{1,3})\s*[-~～至到]\s*(\d{1,3})(?!\d)", text, re.IGNORECASE)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            return set(range(start, end + 1)) if 1 <= start <= end <= 999 else set()
        match = re.search(r"(?:全|\[全)\s*(\d{1,3})\s*集", text)
        if match:
            return set(range(1, int(match.group(1)) + 1))
        return set()

    @staticmethod
    def _fourkmonitor_episode_range(title: str, season: int) -> Set[int]:
        """从 4K Monitor 发布名识别明确的单季或单集范围。"""
        text = str(title or "")
        if FileMatcher._contains_other_season(text, season):
            return set()
        match = re.search(r"(?:EP|E)\s*(\d{1,3})\s*[-~～至到]\s*(\d{1,3})(?!\d)", text, re.IGNORECASE)
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

    def _submit_fourkmonitor_offline(self, resource: Dict[str, Any], subscribe, mediainfo: MediaInfo, save_dir: str,
                                     media_type: str, season: int = 0, episodes: Optional[Set[int]] = None,
                                     subscribe_filter: Optional[SubscribeFilter] = None) -> bool:
        """提交一个 4K Monitor 匿名免费磁力；绝不处理会员或 credits 候选。"""
        if not self._offline_enabled or not self._offline_queue:
            return False
        title = str(resource.get("title") or "")
        match_titles = resource.get("match_titles") or [title]
        if not any(self._resource_title_matches(mediainfo, str(value or "")) for value in match_titles):
            return False
        resource_id = str(resource.get("resource_id") or "")
        source_name = f"4K Monitor/{resource_id}" if resource_id else "4K Monitor"
        if str(resource.get("source") or "") != "4kmonitor" or not resource_id.isdigit():
            return False
        if not resource_year_matches(mediainfo.year, title, title=mediainfo.title):
            return False
        if subscribe_filter and subscribe_filter.has_filters() and not subscribe_filter.match(title)[0]:
            return False
        targets: Set[int] = set()
        if media_type == "电视剧":
            bundle_episodes = self._fourkmonitor_episode_range(title, season)
            targets = set(episodes or set())
            if not targets or not targets.issubset(bundle_episodes):
                return False
            targets -= self._offline_queue.pending_episodes(subscribe.id, season)
            if not targets:
                return False
        elif self._offline_queue.pending_movie(subscribe.id):
            return False
        if self._offline_submitted_this_run >= self._offline_max_per_sync:
            return False
        client = getattr(self._search_handler, "_fourkmonitor_client", None)
        magnet = client.resolve_magnet(resource) if client else ""
        if not magnet:
            logger.warning(f"{source_name} 未取得有效匿名免费磁力，跳过")
            return False
        if self._dry_run:
            target_cid = self._p115_manager.get_pid_by_path(save_dir, mkdir=False)
            if target_cid == -1:
                logger.warning(f"测试模式：4K Monitor 目标目录尚不存在，正式模式会按插件路径创建：{save_dir}")
            else:
                logger.info(f"测试模式：4K Monitor 目标目录可用：{save_dir}")
            logger.info(f"测试模式：已验证 {source_name} 匿名免费磁力候选，不提交 115 云下载")
            return True
        if not self._p115_manager.submit_offline_task(magnet, save_dir):
            return False
        queued = self._offline_queue.enqueue_many(
            subscribe_id=subscribe.id, title=mediainfo.title, year=mediainfo.year, media_type=media_type,
            savepath=save_dir, resource_key=self._p115_manager.offline_resource_key(magnet), file_name=title,
            season=season, episodes=targets,
        )
        if queued:
            self._offline_submitted_this_run += 1
            target_desc = f" S{season:02d} {len(targets)} 集" if targets else ""
            logger.info(f"{source_name} 已进入 115 离线下载待确认队列：{mediainfo.title}{target_desc}")
        return queued

    def _submit_fourkmonitor_movie(self, subscribe, mediainfo: MediaInfo, save_dir: str,
                                   subscribe_filter: SubscribeFilter) -> bool:
        for resource in self._search_handler.search_fourkmonitor_resources(mediainfo, MediaType.MOVIE):
            if self._submit_fourkmonitor_offline(resource, subscribe, mediainfo, save_dir, "电影", subscribe_filter=subscribe_filter):
                return True
        return False

    def _submit_fourkmonitor_tv(self, subscribe, mediainfo: MediaInfo, save_dir: str, season: int,
                                episodes: List[int], subscribe_filter: SubscribeFilter) -> bool:
        targets = set(episodes)
        for resource in self._search_handler.search_fourkmonitor_resources(mediainfo, MediaType.TV, season):
            covered = targets & self._fourkmonitor_episode_range(str(resource.get("title") or ""), season)
            if covered and self._submit_fourkmonitor_offline(
                resource, subscribe, mediainfo, save_dir, "电视剧", season, covered, subscribe_filter
            ):
                return True
        return False

    def _submit_seedhub_offline(self, resource: Dict[str, Any], subscribe, mediainfo: MediaInfo, save_dir: str,
                                media_type: str, season: int = 0, episodes: Optional[Set[int]] = None,
                                subscribe_filter: Optional[SubscribeFilter] = None) -> bool:
        """提交一个 SeedHub 单电影或完整季磁力；一个完整季包只创建一个 115 任务。"""
        if not self._offline_enabled or not self._offline_queue:
            return False
        title = str(resource.get("title") or "")
        movie_id, seed_id = str(resource.get("movie_id") or ""), str(resource.get("seed_id") or "")
        source_name = f"SeedHub/{seed_id}" if seed_id else "SeedHub"
        if not movie_id.isdigit() or not seed_id.isdigit() or not self._resource_title_matches(mediainfo, title):
            return False
        if not resource_year_matches(mediainfo.year, title, title=mediainfo.title):
            return False
        if subscribe_filter and subscribe_filter.has_filters() and not subscribe_filter.match(title)[0]:
            return False
        targets: Set[int] = set()
        if media_type == "电视剧":
            bundle_episodes = self._seedhub_episode_range(title, season)
            targets = set(episodes or set())
            if not targets or not targets.issubset(bundle_episodes):
                return False
            pending = self._offline_queue.pending_episodes(subscribe.id, season)
            targets -= pending
            if not targets:
                return False
        elif self._offline_queue.pending_movie(subscribe.id):
            return False
        if self._offline_submitted_this_run >= self._offline_max_per_sync:
            return False
        seedhub_client = getattr(self._search_handler, "_seedhub_client", None)
        magnet = seedhub_client.resolve_magnet(resource) if seedhub_client else ""
        if not magnet:
            logger.warning(f"{source_name} 未取得有效公开磁力，跳过")
            return False
        if self._dry_run:
            target_cid = self._p115_manager.get_pid_by_path(save_dir, mkdir=False)
            if target_cid == -1:
                logger.warning(f"测试模式：SeedHub 目标目录尚不存在，正式模式会按插件路径创建：{save_dir}")
            else:
                logger.info(f"测试模式：SeedHub 目标目录可用：{save_dir}")
            logger.info(f"测试模式：已验证 {source_name} 公开磁力候选，不提交 115 云下载")
            return True
        if not self._p115_manager.submit_offline_task(magnet, save_dir):
            return False
        queued = self._offline_queue.enqueue_many(
            subscribe_id=subscribe.id, title=mediainfo.title, year=mediainfo.year, media_type=media_type,
            savepath=save_dir, resource_key=self._p115_manager.offline_resource_key(magnet), file_name=title,
            season=season, episodes=targets,
        )
        if queued:
            self._offline_submitted_this_run += 1
            target_desc = f" S{season:02d} {len(targets)} 集" if targets else ""
            logger.info(f"{source_name} 已进入 115 离线下载待确认队列：{mediainfo.title}{target_desc}")
        return queued

    def _submit_seedhub_movie(self, subscribe, mediainfo: MediaInfo, save_dir: str, subscribe_filter: SubscribeFilter) -> bool:
        for resource in self._search_handler.search_seedhub_resources(mediainfo, MediaType.MOVIE):
            if self._submit_seedhub_offline(resource, subscribe, mediainfo, save_dir, "电影", subscribe_filter=subscribe_filter):
                return True
        return False

    def _submit_seedhub_tv(self, subscribe, mediainfo: MediaInfo, save_dir: str, season: int,
                           episodes: List[int], subscribe_filter: SubscribeFilter) -> bool:
        targets = set(episodes)
        for resource in self._search_handler.search_seedhub_resources(mediainfo, MediaType.TV, season):
            bundle_episodes = self._seedhub_episode_range(str(resource.get("title") or ""), season)
            # 完整季包只要求覆盖当前需要回补的集数；避免订阅声明的未播未来集数阻止归档。
            covered = targets & bundle_episodes
            if not covered:
                continue
            if self._submit_seedhub_offline(
                resource, subscribe, mediainfo, save_dir, "电视剧", season, covered, subscribe_filter
            ):
                return True
        return False

    @staticmethod
    def _telegram_resource_matches_missing_episode(resource: Dict[str, Any], season: int,
                                                   episodes: Set[int]) -> bool:
        """根据公开消息标题判断是否明确标注当前待补季集，仅用于候选优先级。"""
        text = unicodedata.normalize("NFKC", str(resource.get("title") or resource.get("text") or ""))
        for episode in episodes:
            if re.search(rf"[Ss]\s*0*{int(season)}\s*[Ee]\s*0*{int(episode)}(?!\d)", text, re.IGNORECASE):
                return True
            if re.search(rf"第\s*0*{int(episode)}\s*[集话話](?!\d)", text, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def _telegram_resource_is_explicit_non_missing_single_episode(resource: Dict[str, Any], season: int,
                                                                   episodes: Set[int]) -> bool:
        """仅跳过标题明确为非待补旧单集的候选，全集、范围包和更新包仍须读取分享目录。"""
        text = unicodedata.normalize("NFKC", str(resource.get("title") or resource.get("text") or ""))
        if not text or re.search(r"全集|全\s*\d+\s*集|收录版本|更新至|更\s*\d+\s*集", text, re.IGNORECASE):
            return False
        matches = re.findall(r"[Ss]\s*(\d{1,2})\s*[Ee]\s*(\d{1,3})(?!\d)", text, re.IGNORECASE)
        if len(matches) != 1:
            return False
        found_season, found_episode = (int(value) for value in matches[0])
        if found_season != int(season) or found_episode in episodes:
            return False
        # S01E01-E12、S01E01~E12 等是范围包，不能按旧单集跳过。
        return not re.search(
            r"[Ss]\s*\d{1,2}\s*[Ee]\s*\d{1,3}\s*(?:[-~～至到]|至\s*[Ee]|到\s*[Ee])",
            text,
            re.IGNORECASE,
        )

    def _existing_tv_episodes(self, mediainfo: MediaInfo, season: int) -> Set[int]:
        """读取 MoviePilot 媒体库已确认的集数，作为订阅状态与补档范围的事实来源。"""
        try:
            exists = DownloadChain().media_exists(mediainfo=mediainfo)
            raw_episodes = getattr(exists, "seasons", {}).get(season, []) if exists else []
            episodes: Set[int] = set()
            for item in raw_episodes:
                try:
                    episode = int(item)
                except (TypeError, ValueError):
                    continue
                if episode > 0:
                    episodes.add(episode)
            if episodes:
                title_year = getattr(mediainfo, "title_year", getattr(mediainfo, "title", "媒体"))
                logger.info(
                    f"{title_year} S{season} 媒体库已确认 {len(episodes)} 集：{sorted(episodes)}"
                )
            return episodes
        except (TypeError, ValueError, AttributeError) as exc:
            logger.warning(f"{mediainfo.title_year} S{season} 读取媒体库已存在集数失败：{type(exc).__name__}")
            return set()
        except Exception as exc:
            logger.warning(f"{mediainfo.title_year} S{season} 查询媒体库已存在集数异常：{type(exc).__name__}")
            return set()

    def _sync_subscribe_from_library(self, subscribe, mediainfo: MediaInfo, episodes: Set[int]) -> None:
        """仅以已入库事实回写订阅；测试模式严格不写入。"""
        if episodes and not self._dry_run:
            self._subscribe_handler.check_and_finish_subscribe(
                subscribe=subscribe, mediainfo=mediainfo, success_episodes=sorted(episodes)
            )

    @staticmethod
    def _progress_from_confirmed_episodes(subscribe, confirmed_episodes: Set[int]) -> Optional[Dict[str, Any]]:
        """基于媒体库已确认集数计算只增不减的订阅进度修复方案。"""
        try:
            start_episode = max(1, int(getattr(subscribe, "start_episode", 1) or 1))
            total_episode = int(getattr(subscribe, "total_episode", 0) or 0)
            current_lack = max(0, int(getattr(subscribe, "lack_episode", 0) or 0))
        except (TypeError, ValueError):
            return None
        if total_episode < start_episode:
            return None

        expected = set(range(start_episode, total_episode + 1))
        current_note: Set[int] = set()
        for item in getattr(subscribe, "note", None) or []:
            try:
                episode = int(item)
            except (TypeError, ValueError):
                continue
            if episode > 0:
                current_note.add(episode)
        confirmed = expected.intersection(confirmed_episodes)
        proposed_note = current_note.union(confirmed)
        # 修复模式只补充媒体库已确认事实；绝不因异常 note/lack 组合扩大缺失数量。
        proposed_lack = min(current_lack, len(expected - proposed_note))
        return {
            "current_note": sorted(current_note),
            "proposed_note": sorted(proposed_note),
            "current_lack": current_lack,
            "proposed_lack": proposed_lack,
            "confirmed": sorted(confirmed),
        }

    def audit_subscribe_progress(self, subscribes: List[Any], apply: bool = False) -> Dict[str, Any]:
        """只核验 Emby 已入库事实并修复电视剧订阅进度；绝不搜索或访问网盘。"""
        report: Dict[str, Any] = {"scanned": 0, "differences": [], "updated": 0, "issues": []}
        for subscribe in subscribes or []:
            if str(getattr(subscribe, "type", "")) != MediaType.TV.value:
                continue
            report["scanned"] += 1
            season = int(getattr(subscribe, "season", 0) or 1)
            label = f"{getattr(subscribe, 'name', '未知媒体')} S{season}"
            try:
                meta = MetaInfo(subscribe.name)
                meta.year = subscribe.year
                meta.begin_season = season
                meta.type = MediaType.TV
                mediainfo: MediaInfo = self._chain.recognize_media(
                    meta=meta, mtype=MediaType.TV, tmdbid=subscribe.tmdbid,
                    doubanid=subscribe.doubanid, cache=True,
                )
                if not mediainfo:
                    report["issues"].append(f"{label}：媒体识别失败")
                    continue
                confirmed = self._existing_tv_episodes(mediainfo, season)
                # 媒体库未确认任何集数时绝不回退 note/lack_episode，避免删除、刮削延迟或库异常造成误修复。
                if not confirmed:
                    continue
                progress = self._progress_from_confirmed_episodes(subscribe, confirmed)
                if not progress:
                    report["issues"].append(f"{label}：订阅集数范围无效")
                    continue
                if (progress["proposed_note"] == progress["current_note"]
                        and progress["proposed_lack"] == progress["current_lack"]):
                    continue
                item = {
                    "id": getattr(subscribe, "id", None), "title": getattr(mediainfo, "title_year", label),
                    "season": season, "confirmed": progress["confirmed"],
                    "note_before": progress["current_note"], "note_after": progress["proposed_note"],
                    "lack_before": progress["current_lack"], "lack_after": progress["proposed_lack"],
                }
                report["differences"].append(item)
                if apply:
                    update_data: Dict[str, Any] = {}
                    if progress["proposed_note"] != progress["current_note"]:
                        update_data["note"] = progress["proposed_note"]
                    if progress["proposed_lack"] != progress["current_lack"]:
                        update_data["lack_episode"] = progress["proposed_lack"]
                    if update_data:
                        SubscribeOper().update(subscribe.id, update_data)
                        if "note" in update_data:
                            subscribe.note = update_data["note"]
                            logger.info(f"修复订阅 {subscribe.name} note：{progress['current_note']} -> {progress['proposed_note']}")
                        if "lack_episode" in update_data:
                            subscribe.lack_episode = update_data["lack_episode"]
                            logger.info(
                                f"修复订阅 {subscribe.name} 缺失集数："
                                f"{progress['current_lack']} -> {progress['proposed_lack']}"
                            )
                        # 先按预览方案写入，再调用既有完成链路；避免异常旧字段使确认修复扩大缺失数。
                        if progress["proposed_lack"] == 0:
                            self._subscribe_handler.check_and_finish_subscribe(
                                subscribe=subscribe, mediainfo=mediainfo, success_episodes=[]
                            )
                        report["updated"] += 1
            except Exception as exc:
                logger.warning(f"订阅进度核验 {label} 异常：{type(exc).__name__}")
                report["issues"].append(f"{label}：{type(exc).__name__}")
        return report

    @staticmethod
    def _fallback_missing_episodes_from_subscribe(subscribe) -> List[int]:
        """当媒体库未返回缺集明细时，使用 MoviePilot 订阅声明的季集范围继续追更。"""
        try:
            total_episode = int(getattr(subscribe, "total_episode", 0) or 0)
            start_episode = max(1, int(getattr(subscribe, "start_episode", 1) or 1))
        except (TypeError, ValueError):
            return []
        if total_episode < start_episode:
            return []
        return list(range(start_episode, total_episode + 1))

    @staticmethod
    def _resource_title_matches(mediainfo: MediaInfo, resource_title: str) -> bool:
        """仅接受消息文本明确包含当前订阅标题的候选，避免搜索页模糊命中。"""
        title = str(getattr(mediainfo, "title", "") or "").strip()
        text = str(resource_title or "").strip()
        if not title or not text:
            return False

        def compact(value: str) -> str:
            normalized = unicodedata.normalize("NFKC", value).casefold()
            return re.sub(r"[\s\W_]+", "", normalized)

        expected = compact(title)
        actual = compact(text)
        if len(expected) >= 2 and expected in actual:
            return True

        # 单字剧名不参与 compact 后“至少两字符”的快速路径，
        # 改在 NFKC 标准化原文中做字面匹配。
        normalized_title = unicodedata.normalize("NFKC", title).casefold()
        normalized_text = unicodedata.normalize("NFKC", text).casefold()
        return len(normalized_title) == 1 and normalized_title in normalized_text

    def process_movie_subscribe(
        self,
        subscribe,
        history: List[dict],
        transfer_details: List[Dict[str, Any]],
        transferred_count: int
    ) -> int:
        """
        处理单个电影订阅

        :param subscribe: 订阅对象
        :param history: 历史记录列表
        :param transfer_details: 转存详情列表
        :param transferred_count: 当前已转存数量
        :return: 更新后的转存数量
        """
        try:
            logger.info(f"处理电影订阅：{subscribe.name} ({subscribe.year})")

            # 加载该订阅的历史积分花费（用 tmdb_id 作为唯一标识）
            sub_key = f"tmdb_{subscribe.tmdbid}_movie" if subscribe.tmdbid else f"{subscribe.name}_movie"
            if hasattr(self._search_handler, 'reset_sub_spent_points'):
                self._search_handler.reset_sub_spent_points(sub_key)

            # 检查历史记录是否已成功转存
            movie_history_score = -1  # -1 表示未转存过
            movie_perfect_match = False
            for h in history:
                if (h.get("title") == subscribe.name
                        and h.get("type") == "电影"
                        and h.get("status") == "成功"):
                    score = h.get("filter_score", 0)
                    perfect = h.get("perfect_match", False)
                    if score > movie_history_score:
                        movie_history_score = score
                        movie_perfect_match = perfect

            # best_version=1 表示开启洗版（非严格模式）
            is_best_version = bool(subscribe.best_version)

            # 历史仅用于洗版的质量参考，不能代替 115 目标目录实际文件。
            # 用户删除夸克文件、重置订阅或迁移至 115 后，旧历史必须不阻止重新搜集。
            if movie_history_score >= 0:
                logger.info(
                    f"电影 {subscribe.name} 存在历史记录（洗版:{is_best_version}）；"
                    "将以 115 目标目录实际文件为准继续核验"
                )

            # 生成元数据
            meta = MetaInfo(subscribe.name)
            meta.year = subscribe.year
            meta.type = MediaType.MOVIE

            # 识别媒体信息
            mediainfo: MediaInfo = self._chain.recognize_media(
                meta=meta,
                mtype=MediaType.MOVIE,
                tmdbid=subscribe.tmdbid,
                doubanid=subscribe.doubanid,
                cache=True
            )
            if not mediainfo:
                logger.warn(f"无法识别媒体信息：{subscribe.name}")
                return transferred_count

            # 115 离线任务完成后仍须以目标目录真实文件为准，再走既有订阅闭环。
            offline_save_dir = f"{self._movie_save_path}/{mediainfo.title} ({mediainfo.year})" if mediainfo.year else f"{self._movie_save_path}/{mediainfo.title}"
            if self._reconcile_offline_movie(subscribe, mediainfo, offline_save_dir):
                return transferred_count
            try:
                existing_movie = FileMatcher.match_movie_file(
                    self._p115_manager.list_files(offline_save_dir), mediainfo.title
                )
            except Exception as exc:
                logger.warning(f"检查 115 电影目标目录失败：{type(exc).__name__}")
                existing_movie = None
            if existing_movie:
                logger.info(f"115 目标目录已确认电影文件，跳过重复转存：{mediainfo.title}")
                if not self._dry_run:
                    self._subscribe_handler.check_and_finish_subscribe(
                        subscribe, mediainfo, success_episodes=[1]
                    )
                return transferred_count
            # 目录未确认文件时，旧历史不应抑制重新搜集或阻止相同质量资源回补。
            movie_history_score = -1
            movie_perfect_match = False

            # 搜索网盘资源
            p115_results = self._search_handler.search_resources(
                mediainfo=mediainfo,
                media_type=MediaType.MOVIE
            )

            if not p115_results:
                logger.info(f"未找到电影 {mediainfo.title} 的 115 分享资源，继续检查 ED2K/磁力候选")
            else:
                logger.info(f"找到 {len(p115_results)} 个 115 网盘资源")

            # 创建订阅过滤条件
            subscribe_filter = SubscribeFilter(
                quality=subscribe.quality,
                resolution=subscribe.resolution,
                effect=subscribe.effect,
                strict=not is_best_version
            )
            if subscribe_filter.has_filters():
                mode_text = "洗版模式" if is_best_version else "严格模式"
                logger.info(f"电影 {subscribe.name} 过滤条件({mode_text}) - 质量: {subscribe.quality}, 分辨率: {subscribe.resolution}, 特效: {subscribe.effect}")

            # 遍历搜索结果，尝试找到并转存电影
            movie_transferred = False
            for resource in p115_results:
                if movie_transferred:
                    break

                share_url = resource.get("url", "")
                resource_title = resource.get("title", "")
                safe_resource_title = sanitize_resource_text(resource_title)

                if not self._resource_title_matches(mediainfo, resource_title):
                    logger.info(f"跳过标题未明确匹配当前订阅的 Telegram 候选：{safe_resource_title}")
                    continue
                if not resource_year_matches(mediainfo.year, resource_title, title=mediainfo.title):
                    logger.info(f"跳过年份与订阅不匹配的 Telegram 候选：{safe_resource_title}")
                    continue

                logger.info(f"检查 115 分享：{safe_resource_title}")

                try:
                    # 先检查分享链接是否有效
                    share_status = self._p115_manager.check_share_status(share_url)
                    if share_status.is_transient_error:
                        logger.info("115 分享状态暂时不可用，本轮不将该候选标记为失效")
                        continue
                    if not share_status.is_valid:
                        logger.warning(f"115 分享链接无效：{share_status.status_text}")
                        continue

                    share_files = self._p115_manager.list_share_files(share_url)
                    if share_files is None:
                        logger.info("115 分享目录暂时不可读取，本轮不将该候选判定为空")
                        continue
                    if not share_files:
                        logger.info("115 分享链接无内容")
                        continue

                    # 匹配电影文件
                    matched_file = FileMatcher.match_movie_file(
                        share_files, mediainfo.title,
                        subscribe_filter=subscribe_filter
                    )

                    if matched_file:
                        file_name = matched_file.get('name', '')
                        logger.info(f"找到匹配文件：{file_name}")

                        # 计算当前文件的过滤分数和是否完美匹配
                        _, current_score = subscribe_filter.match(file_name) if subscribe_filter.has_filters() else (True, 0)
                        is_perfect = subscribe_filter.is_perfect_match(file_name) if subscribe_filter.has_filters() else True

                        # 洗版模式下检查是否需要升级资源
                        if is_best_version and movie_history_score >= 0:
                            if current_score <= movie_history_score:
                                logger.info(f"电影 {mediainfo.title} 已有分数 {movie_history_score}，当前 {current_score}，跳过")
                                continue
                            else:
                                logger.info(f"电影 {mediainfo.title} 洗版：旧分数 {movie_history_score} -> 新分数 {current_score}")

                        # 构建转存路径
                        save_dir = f"{self._movie_save_path}/{mediainfo.title} ({mediainfo.year})" if mediainfo.year else f"{self._movie_save_path}/{mediainfo.title}"
                        logger.info(f"转存目标路径: {save_dir}")

                        # 执行转存（测试模式只验证到文件匹配）
                        if self._dry_run:
                            logger.info(f"测试模式：已验证电影候选，不执行转存：{file_name}")
                            continue
                        success = self._p115_manager.transfer_file(
                            share_url=share_url,
                            file_id=matched_file.get("id"),
                            save_path=save_dir
                        )

                        # 记录历史
                        history_item = {
                            "title": mediainfo.title,
                            "year": mediainfo.year,
                            "tmdb_id": mediainfo.tmdb_id,
                            "type": "电影",
                            "status": "成功" if success else "失败",
                            "share_code": str(self._p115_manager.extract_share_info(share_url).get("share_code") or ""),
                            "file_name": file_name,
                            "filter_score": current_score,
                            "perfect_match": is_perfect,
                            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        history.append(history_item)

                        if success:
                            transferred_count += 1
                            movie_transferred = True
                            movie_history_score = current_score
                            score_info = f"(分数:{current_score}, 完美匹配:{is_perfect})" if subscribe_filter.has_filters() else ""
                            logger.info(f"成功转存电影：{mediainfo.title} {score_info}")

                            # 收集转存详情用于通知
                            transfer_details.append({
                                "type": "电影",
                                "title": mediainfo.title,
                                "year": mediainfo.year,
                                "image": mediainfo.get_poster_image(),
                                "file_name": file_name
                            })

                            # 添加下载历史记录
                            try:
                                DownloadHistoryOper().add(
                                    path=save_dir,
                                    type=mediainfo.type.value,
                                    title=mediainfo.title,
                                    year=mediainfo.year,
                                    tmdbid=mediainfo.tmdb_id,
                                    imdbid=mediainfo.imdb_id,
                                    tvdbid=mediainfo.tvdb_id,
                                    doubanid=mediainfo.douban_id,
                                    image=mediainfo.get_poster_image(),
                                    downloader="115网盘",
                                    download_hash=matched_file.get("id"),
                                    torrent_name=safe_resource_title,
                                    torrent_description=file_name,
                                    torrent_site="115网盘",
                                    username="P115TGSub",
                                    date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    note={
                                        "source": f"Subscribe|{subscribe.name}",
                                        "share_code": str(self._p115_manager.extract_share_info(share_url).get("share_code") or ""),
                                    }
                                )
                                logger.debug(f"已记录电影 {mediainfo.title} 下载历史")
                            except Exception as e:
                                logger.warning(f"记录下载历史失败：{e}")

                            # 电影转存成功后完成订阅
                            self._subscribe_handler.check_and_finish_subscribe(
                                subscribe=subscribe,
                                mediainfo=mediainfo,
                                success_episodes=[1]
                            )
                            # 订阅完成，清除该订阅的历史积分记录
                            if hasattr(self._search_handler, 'clear_sub_points'):
                                self._search_handler.clear_sub_points(sub_key)
                        else:
                            logger.error(f"转存失败：{mediainfo.title}")

                except Exception as e:
                    logger.error(f"处理 115 分享链接出错：{str(e)}")
                    continue

            if not movie_transferred and not self.offline_pending(subscribe.id, media_type="电影"):
                offline_submitted = False
                for resource in self._search_offline_resources(mediainfo, MediaType.MOVIE):
                    if self._submit_offline(resource, subscribe, mediainfo, offline_save_dir, "电影"):
                        logger.info(f"电影 {mediainfo.title} 已提交 115 离线下载，等待目标目录文件确认")
                        offline_submitted = True
                        break
                if not offline_submitted:
                    offline_submitted = self._submit_fourkmonitor_movie(
                        subscribe, mediainfo, offline_save_dir, subscribe_filter
                    )
                if not offline_submitted:
                    self._submit_seedhub_movie(subscribe, mediainfo, offline_save_dir, subscribe_filter)

        except Exception as e:
            logger.error(f"处理电影订阅 {subscribe.name} 出错：{str(e)}")

        return transferred_count

    def process_tv_subscribe(
        self,
        subscribe,
        history: List[dict],
        transfer_details: List[Dict[str, Any]],
        transferred_count: int,
        exclude_ids: Set[int]
    ) -> int:
        """
        处理单个电视剧订阅

        :param subscribe: 订阅对象
        :param history: 历史记录列表
        :param transfer_details: 转存详情列表
        :param transferred_count: 当前已转存数量
        :param exclude_ids: 排除的订阅ID集合
        :return: 更新后的转存数量
        """
        try:
            logger.info(f"订阅信息：{subscribe.name}，开始集数：{subscribe.start_episode}, 总集数：{subscribe.total_episode}, 缺失集数：{subscribe.lack_episode}")
            logger.info(f"处理订阅：{subscribe.name} (S{subscribe.season or 1})")

            # 加载该订阅的历史积分花费（用 tmdb_id + 季数作为唯一标识）
            sub_key = f"tmdb_{subscribe.tmdbid}_S{subscribe.season or 1}" if subscribe.tmdbid else f"{subscribe.name}_S{subscribe.season or 1}"
            if hasattr(self._search_handler, 'reset_sub_spent_points'):
                self._search_handler.reset_sub_spent_points(sub_key)

            # 早期检查：如果订阅显示没有缺失集数，跳过处理
            if subscribe.lack_episode == 0:
                logger.info(f"{subscribe.name} S{subscribe.season or 1} 订阅显示媒体库已完整(lack_episode=0)，跳过")
                return transferred_count

            # 生成元数据
            meta = MetaInfo(subscribe.name)
            meta.year = subscribe.year
            meta.begin_season = subscribe.season or 1
            meta.type = MediaType.TV

            # 识别媒体信息
            mediainfo: MediaInfo = self._chain.recognize_media(
                meta=meta,
                mtype=MediaType.TV,
                tmdbid=subscribe.tmdbid,
                doubanid=subscribe.doubanid,
                cache=True
            )

            if not mediainfo:
                logger.warn(f"无法识别媒体信息：{subscribe.name}")
                return transferred_count

            # 构造总集数信息
            totals = {}
            if subscribe.season and subscribe.total_episode:
                totals = {subscribe.season: subscribe.total_episode}

            # 获取缺失剧集
            downloadchain = DownloadChain()
            exist_flag, no_exists = downloadchain.get_no_exists_info(
                meta=meta,
                mediainfo=mediainfo,
                totals=totals
            )

            if exist_flag:
                logger.info(f"{mediainfo.title_year} S{meta.begin_season} 媒体库中已完整存在")
                if self._dry_run:
                    logger.info("测试模式：不修改订阅完成状态")
                    return transferred_count
                # 媒体库已完整，调用完成订阅逻辑
                total_ep = subscribe.total_episode or 0
                start_ep = subscribe.start_episode or 1
                if total_ep > 0:
                    all_episodes = list(range(start_ep, total_ep + 1))
                    self._subscribe_handler.check_and_finish_subscribe(
                        subscribe=subscribe,
                        mediainfo=mediainfo,
                        success_episodes=all_episodes
                    )
                elif subscribe.lack_episode != 0:
                    SubscribeOper().update(subscribe.id, {"lack_episode": 0})
                # 订阅已完整，清除历史积分记录
                if hasattr(self._search_handler, 'clear_sub_points'):
                    self._search_handler.clear_sub_points(sub_key)
                return transferred_count

            # 获取缺失的集数列表
            season = meta.begin_season or 1
            missing_episodes = []
            mediakey = mediainfo.tmdb_id or mediainfo.douban_id

            if no_exists and mediakey:
                season_info = no_exists.get(mediakey, {})
                not_exist_info = season_info.get(season)
                if not_exist_info:
                    missing_episodes = not_exist_info.episodes or []
                    if not missing_episodes and not_exist_info.total_episode:
                        start_ep = not_exist_info.start_episode or 1
                        missing_episodes = list(range(start_ep, not_exist_info.total_episode + 1))

            # 无论 DownloadChain 是否能给出缺集明细，均以媒体库已确认的集数
            # 回写订阅并从后续补档范围剔除，避免已入库剧集被重复追更。
            library_episodes = self._existing_tv_episodes(mediainfo, season)
            subscription_start = max(1, int(getattr(subscribe, "start_episode", 1) or 1))
            subscription_total = int(getattr(subscribe, "total_episode", 0) or 0)
            if subscription_total >= subscription_start:
                library_episodes &= set(range(subscription_start, subscription_total + 1))
            self._sync_subscribe_from_library(subscribe, mediainfo, library_episodes)
            if getattr(subscribe, "lack_episode", 1) == 0:
                logger.info(f"{mediainfo.title_year} S{season} 已按媒体库事实完成订阅")
                return transferred_count

            if not missing_episodes:
                # 某些 Emby/媒体库配置下，get_no_exists_info 在“媒体库无该剧”时不会返回季集明细。
                # 订阅本身已声明待追更的起止集数，不能因此跳过 Telegram 搜索。
                fallback_episodes = self._fallback_missing_episodes_from_subscribe(subscribe)
                if fallback_episodes:
                    missing_episodes = fallback_episodes
                    logger.warning(
                        f"{mediainfo.title_year} S{season} 未从媒体库获取缺集明细；"
                        f"按 MoviePilot 订阅范围回退追更 E{missing_episodes[0]:02d}-E{missing_episodes[-1]:02d}"
                    )
                else:
                    logger.info(
                        f"{mediainfo.title_year} S{season} 没有缺失剧集信息，且订阅未提供有效总集数，跳过"
                    )
                    return transferred_count

            if library_episodes:
                before_library_filter = len(missing_episodes)
                missing_episodes = [ep for ep in missing_episodes if ep not in library_episodes]
                skipped_library = before_library_filter - len(missing_episodes)
                if skipped_library:
                    logger.info(
                        f"{mediainfo.title_year} S{season} 跳过媒体库已存在的 {skipped_library} 集："
                        f"{sorted(library_episodes.intersection(set(range(1, (subscribe.total_episode or 0) + 1))))}"
                    )

            # 过滤掉小于开始集数的剧集
            if subscribe.start_episode:
                original_count = len(missing_episodes)
                missing_episodes = [ep for ep in missing_episodes if ep >= subscribe.start_episode]
                if len(missing_episodes) < original_count:
                    logger.info(f"根据订阅设置，过滤掉小于 {subscribe.start_episode} 的剧集")

            # best_version=1 表示开启洗版
            is_best_version = bool(subscribe.best_version)

            # 历史不代表 115 目标目录文件存在：夸克迁移、人工删除或订阅重置后，
            # 必须允许 115 重新搜集；质量评分仅在实际 115 文件已确认时才有意义。
            transferred_episodes = set()
            episode_history_scores: Dict[int, int] = {}
            for h in history:
                if (h.get("title") == mediainfo.title
                        and h.get("season") == season
                        and h.get("status") == "成功"
                        and is_best_version):
                    ep = h.get("episode")
                    score = h.get("filter_score", 0)
                    perfect = h.get("perfect_match", False)
                    if not perfect and ep not in episode_history_scores:
                        episode_history_scores[ep] = score
                    elif not perfect and score > episode_history_scores[ep]:
                        episode_history_scores[ep] = score

            # 115 离线任务完成后仍须以目标目录真实文件为准，再走既有订阅闭环。
            show_folder = f"{mediainfo.title} ({mediainfo.year})" if mediainfo.year else mediainfo.title
            offline_save_dir = f"{self._save_path}/{show_folder}/Season {season}"
            offline_pending = self._reconcile_offline_tv(subscribe, mediainfo, season, offline_save_dir)

            # 构建转存路径（标题 + 年份，格式如 "权力的游戏 (2011)"）
            show_folder = f"{mediainfo.title} ({mediainfo.year})" if mediainfo.year else mediainfo.title
            save_dir = f"{self._save_path}/{show_folder}/Season {season}"

            # 检查网盘目录中已存在的剧集
            existing_episodes_in_cloud = FileMatcher.check_existing_episodes(
                self._p115_manager, mediainfo, season, save_dir
            )

            # 合并已存在的集数
            all_existing = transferred_episodes | existing_episodes_in_cloud

            # 洗版模式下，需要升级的集数不应该被排除
            if is_best_version and episode_history_scores:
                episodes_to_upgrade = set(episode_history_scores.keys())
                all_existing = all_existing - episodes_to_upgrade
                if episodes_to_upgrade:
                    logger.info(f"{mediainfo.title_year} S{season} 洗版模式：{len(episodes_to_upgrade)} 集待升级")

            if all_existing:
                missing_episodes = [ep for ep in missing_episodes if ep not in all_existing]
                logger.info(
                    f"{mediainfo.title_year} S{season} 跳过已存在的 {len(all_existing)} 集 "
                    f"(历史记录:{len(transferred_episodes)}, 网盘:{len(existing_episodes_in_cloud)})"
                )

            if not missing_episodes:
                logger.info(f"{mediainfo.title_year} S{season} 所有缺失剧集已存在于网盘")
                # 网盘中已存在所有缺失集数，更新订阅状态
                if existing_episodes_in_cloud and not self._dry_run:
                    self._subscribe_handler.check_and_finish_subscribe(
                        subscribe=subscribe,
                        mediainfo=mediainfo,
                        success_episodes=list(existing_episodes_in_cloud)
                    )
                    # 缺失集数已全部补齐，清除历史积分记录
                    if hasattr(self._search_handler, 'clear_sub_points'):
                        self._search_handler.clear_sub_points(sub_key)
                return transferred_count

            if offline_pending:
                missing_episodes = [ep for ep in missing_episodes if ep not in offline_pending]
                logger.info(f"{mediainfo.title_year} S{season} 跳过 115 离线下载中的剧集：{sorted(offline_pending)}")
            if not missing_episodes:
                return transferred_count

            # TMDB 播出日期仅作元数据参考，不能作为追更前置条件：超前点映、会员抢先看
            # 或元数据滞后时，公开频道可能已存在可严格匹配的资源。

            prefer_recent = self._search_handler.is_followup_tv(
                library_episodes | all_existing,
                missing_episodes,
                start_episode=getattr(subscribe, "start_episode", 1),
                total_episode=getattr(subscribe, "total_episode", 0),
            )
            if prefer_recent:
                logger.info(
                    f"{mediainfo.title_year} S{season} 识别为连续尾集追更，"
                    "Telegram 候选将按最新发布时间优先"
                )

            logger.info(f"{mediainfo.title_year} S{season} 待转存剧集：{missing_episodes}")

            # 创建订阅过滤条件
            subscribe_filter = SubscribeFilter(
                quality=subscribe.quality,
                resolution=subscribe.resolution,
                effect=subscribe.effect,
                strict=not is_best_version
            )
            if subscribe_filter.has_filters():
                mode_text = "洗版模式" if is_best_version else "严格模式"
                logger.info(f"{mediainfo.title} S{season} 过滤条件({mode_text}) - 质量: {subscribe.quality}, 分辨率: {subscribe.resolution}, 特效: {subscribe.effect}")

            # 成功转存的集数列表
            success_episodes = []

            # 智能回退搜索：按源迭代
            enabled_sources = self._search_handler.get_enabled_sources()

            if not enabled_sources:
                logger.warning(f"没有可用的搜索源，跳过 {mediainfo.title} S{season} 的搜索")
                return transferred_count

            for source_index, source in enumerate(enabled_sources):
                if not missing_episodes:
                    logger.info(f"{mediainfo.title_year} S{season} 所有缺失剧集已转存完成，不再查询后续源")
                    break

                if transferred_count >= self._max_transfer_per_sync:
                    logger.info(f"已达单次同步上限 {self._max_transfer_per_sync}，剩余 {len(missing_episodes)} 集将在下次同步处理")
                    break

                logger.info(f"[{source.upper()}] 开始搜索 {mediainfo.title} S{season}（当前缺失: {len(missing_episodes)} 集）")

                # 搜索当前源
                p115_results = self._search_handler.search_single_source(
                    source=source,
                    mediainfo=mediainfo,
                    media_type=MediaType.TV,
                    season=season,
                    preferred_episodes=missing_episodes,
                    prefer_recent=prefer_recent,
                )

                if not p115_results:
                    offline_results = self._search_offline_resources(
                        mediainfo, MediaType.TV, season, preferred_episodes=missing_episodes,
                        prefer_recent=prefer_recent,
                    )
                    submitted = 0
                    for resource in offline_results:
                        if self._offline_submitted_this_run >= self._offline_max_per_sync or not missing_episodes:
                            break
                        for episode in missing_episodes[:]:
                            if self._submit_offline(resource, subscribe, mediainfo, save_dir, "电视剧", season, episode):
                                submitted += 1
                                if not self._dry_run:
                                    missing_episodes.remove(episode)
                                break
                    if submitted:
                        logger.info(f"[{source.upper()}] 已提交 {submitted} 个 115 离线下载任务，等待目标目录文件确认")
                    else:
                        submitted = 1 if self._submit_fourkmonitor_tv(
                            subscribe, mediainfo, save_dir, season, missing_episodes, subscribe_filter
                        ) else 0
                        if not submitted:
                            self._submit_seedhub_tv(
                                subscribe, mediainfo, save_dir, season, missing_episodes, subscribe_filter
                            )
                    if submitted:
                        action = "已验证" if self._dry_run else "已提交"
                        logger.info(
                            f"[{source.upper()}] 未找到可直接转存的 115 分享；"
                            f"{action} {submitted} 个 ED2K/磁力离线任务，等待目标目录文件确认"
                        )
                    else:
                        remaining_sources = enabled_sources[source_index + 1:]
                        if remaining_sources:
                            logger.info(f"[{source.upper()}] 未找到资源，将尝试下一个源: {remaining_sources[0].upper()}")
                        else:
                            logger.info(f"[{source.upper()}] 未找到资源，已无更多可用源")
                    continue

                logger.info(f"[{source.upper()}] 找到 {len(p115_results)} 个 115 网盘资源")
                preferred_set = set(missing_episodes)
                preferred_resources = [
                    resource for resource in p115_results
                    if self._telegram_resource_matches_missing_episode(resource, season, preferred_set)
                ]
                if preferred_resources:
                    logger.info(
                        f"[{source.upper()}] 优先检查 {len(preferred_resources)} 个明确命中待补集的候选"
                    )
                    p115_results = preferred_resources + [
                        resource for resource in p115_results if resource not in preferred_resources
                    ]

                # 遍历搜索结果
                for resource in p115_results:
                    if transferred_count >= self._max_transfer_per_sync:
                        logger.info(f"已达单次同步上限 {self._max_transfer_per_sync}，剩余 {len(missing_episodes)} 集将在下次同步处理")
                        break

                    share_url = resource.get("url", "")
                    resource_title = resource.get("title", "")
                    safe_resource_title = sanitize_resource_text(resource_title)

                    if not self._resource_title_matches(mediainfo, resource_title):
                        logger.info(f"跳过标题未明确匹配当前订阅的 Telegram 候选：{safe_resource_title}")
                        continue
                    if not resource_year_matches(mediainfo.year, resource_title, title=mediainfo.title):
                        logger.info(f"跳过年份与订阅不匹配的 Telegram 候选：{safe_resource_title}")
                        continue
                    if self._telegram_resource_is_explicit_non_missing_single_episode(
                        resource, season, set(missing_episodes)
                    ):
                        logger.info(f"跳过明确非待补旧单集的 Telegram 候选：{safe_resource_title}")
                        continue

                    logger.info(f"检查 115 分享：{safe_resource_title}")

                    try:
                        # 检查分享链接是否有效
                        share_status = self._p115_manager.check_share_status(share_url)
                        if share_status.is_transient_error:
                            logger.info("115 分享状态暂时不可用，本轮不将该候选标记为失效")
                            continue
                        if not share_status.is_valid:
                            logger.warning(f"115 分享链接无效：{share_status.status_text}")
                            continue

                        # 列出分享内容
                        share_files = self._p115_manager.list_share_files(
                            share_url,
                            target_season=(season if self._skip_other_season_dirs else None)
                        )
                        if share_files is None:
                            logger.info("115 分享目录暂时不可读取，本轮不将该候选判定为空")
                            continue
                        if not share_files:
                            logger.info("115 分享链接无内容")
                            continue

                        logger.info(f"分享包含 {len(share_files)} 个文件/目录")

                        # 收集该分享中所有匹配的文件
                        matched_items = []

                        for episode in missing_episodes[:]:
                            matched_file = FileMatcher.match_episode_file(
                                share_files,
                                mediainfo.title,
                                season,
                                episode,
                                subscribe_filter=subscribe_filter
                            )

                            if matched_file:
                                file_name = matched_file.get('name', '')
                                logger.info(f"找到匹配文件：{file_name} -> E{episode:02d}")

                                _, current_score = subscribe_filter.match(file_name) if subscribe_filter.has_filters() else (True, 0)
                                is_perfect = subscribe_filter.is_perfect_match(file_name) if subscribe_filter.has_filters() else True

                                is_upgrade = False
                                if is_best_version and episode in episode_history_scores:
                                    old_score = episode_history_scores[episode]
                                    if current_score <= old_score:
                                        logger.info(f"E{episode:02d} 已有分数 {old_score}，当前 {current_score}，跳过")
                                        continue
                                    else:
                                        logger.info(f"E{episode:02d} 洗版：旧分数 {old_score} -> 新分数 {current_score}")
                                        is_upgrade = True

                                matched_items.append({
                                    "file": matched_file,
                                    "episode": episode,
                                    "score": current_score,
                                    "is_perfect": is_perfect,
                                    "is_upgrade": is_upgrade
                                })

                        if not matched_items:
                            logger.info(f"该分享未匹配到 S{season} 的任何缺失剧集，可能是季数不匹配或文件名无法识别")
                            continue

                        # 检查转存配额限制
                        remaining_quota = self._max_transfer_per_sync - transferred_count
                        if len(matched_items) > remaining_quota:
                            logger.info(f"匹配 {len(matched_items)} 集，但受配额限制仅转存 {remaining_quota} 集")
                            matched_items = matched_items[:remaining_quota]

                        # 批量转存（测试模式只报告已匹配的集数）
                        if self._dry_run:
                            logger.info(
                                f"测试模式：已验证 {mediainfo.title} S{season:02d} "
                                f"候选集数 {[item['episode'] for item in matched_items]}，不执行转存"
                            )
                            continue
                        file_ids = [item["file"]["id"] for item in matched_items]
                        logger.info(f"准备批量转存 {len(file_ids)} 个文件到: {save_dir}")
                        success_ids, failed_ids = self._p115_manager.transfer_files_batch(
                            share_url=share_url,
                            file_ids=file_ids,
                            save_path=save_dir,
                            batch_size=self._batch_size
                        )

                        success_id_set = set(success_ids)
                        batch_success_episodes = []

                        # 处理结果
                        for item in matched_items:
                            file_id = item["file"]["id"]
                            episode = item["episode"]
                            file_name = item["file"]["name"]
                            current_score = item["score"]
                            is_perfect = item["is_perfect"]
                            is_upgrade = item["is_upgrade"]
                            success = file_id in success_id_set

                            history_item = {
                                "title": mediainfo.title,
                                "year": mediainfo.year,
                                "tmdb_id": mediainfo.tmdb_id,
                                "season": season,
                                "episode": episode,
                                "type": "电视剧",
                                "status": "成功" if success else "失败",
                                "share_code": str(self._p115_manager.extract_share_info(share_url).get("share_code") or ""),
                                "file_name": file_name,
                                "filter_score": current_score,
                                "perfect_match": is_perfect,
                                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }
                            history.append(history_item)

                            if success:
                                transferred_count += 1
                                episode_history_scores[episode] = current_score

                                if episode in missing_episodes:
                                    missing_episodes.remove(episode)

                                if not is_upgrade:
                                    success_episodes.append(episode)

                                score_info = f"(分数:{current_score}, 完美匹配:{is_perfect})" if subscribe_filter.has_filters() else ""
                                upgrade_info = " [洗版升级]" if is_upgrade else ""
                                logger.info(f"成功转存：{mediainfo.title} S{season:02d}E{episode:02d} {score_info}{upgrade_info}")

                                # 收集转存详情
                                existing_detail = next(
                                    (d for d in transfer_details
                                     if d.get("title") == mediainfo.title and d.get("season") == season),
                                    None
                                )
                                if existing_detail:
                                    existing_detail["episodes"].append(episode)
                                else:
                                    transfer_details.append({
                                        "type": "电视剧",
                                        "title": mediainfo.title,
                                        "year": mediainfo.year,
                                        "season": season,
                                        "episodes": [episode],
                                        "image": mediainfo.get_poster_image()
                                    })

                                batch_success_episodes.append(episode)
                            else:
                                logger.error(f"转存失败：{mediainfo.title} S{season:02d}E{episode:02d}")

                        # 记录下载历史
                        if batch_success_episodes:
                            try:
                                episodes_str = StringUtils.format_ep(batch_success_episodes)
                                DownloadHistoryOper().add(
                                    path=save_dir,
                                    type=mediainfo.type.value,
                                    title=mediainfo.title,
                                    year=mediainfo.year,
                                    tmdbid=mediainfo.tmdb_id,
                                    imdbid=mediainfo.imdb_id,
                                    tvdbid=mediainfo.tvdb_id,
                                    doubanid=mediainfo.douban_id,
                                    seasons=f"S{season:02d}",
                                    episodes=episodes_str,
                                    image=mediainfo.get_poster_image(),
                                    downloader="115网盘",
                                    download_hash=str(self._p115_manager.extract_share_info(share_url).get("share_code") or ""),
                                    torrent_name=safe_resource_title,
                                    torrent_site="115网盘",
                                    username="P115TGSub",
                                    date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    note={
                                        "source": f"Subscribe|{subscribe.name}",
                                        "share_code": str(self._p115_manager.extract_share_info(share_url).get("share_code") or ""),
                                    }
                                )
                                logger.debug(f"已记录 {mediainfo.title} S{season:02d} {episodes_str} 下载历史")
                            except Exception as e:
                                logger.warning(f"记录下载历史失败：{e}")

                        if not missing_episodes:
                            break

                    except Exception as e:
                        logger.error(f"处理 115 分享链接出错：{str(e)}")
                        continue

                # 当前源处理完成；115 分享未补齐时再尝试 Telegram 正文直链 ED2K/磁力。
                if missing_episodes and self._offline_submitted_this_run < self._offline_max_per_sync:
                    submitted = 0
                    for resource in self._search_offline_resources(
                        mediainfo, MediaType.TV, season, preferred_episodes=missing_episodes,
                        prefer_recent=prefer_recent,
                    ):
                        if self._offline_submitted_this_run >= self._offline_max_per_sync or not missing_episodes:
                            break
                        for episode in missing_episodes[:]:
                            if self._submit_offline(resource, subscribe, mediainfo, save_dir, "电视剧", season, episode):
                                submitted += 1
                                if not self._dry_run:
                                    missing_episodes.remove(episode)
                                break
                    if submitted:
                        logger.info(f"[{source.upper()}] 已提交 {submitted} 个 115 离线下载任务，等待目标目录文件确认")
                    elif self._submit_fourkmonitor_tv(
                        subscribe, mediainfo, save_dir, season, missing_episodes, subscribe_filter
                    ):
                        logger.info(f"[{source.upper()}] 已提交 4K Monitor 115 离线下载任务，等待目标目录文件确认")
                    elif self._submit_seedhub_tv(
                        subscribe, mediainfo, save_dir, season, missing_episodes, subscribe_filter
                    ):
                        logger.info(f"[{source.upper()}] 已提交 SeedHub 115 离线下载任务，等待目标目录文件确认")

                if missing_episodes:
                    remaining_sources = enabled_sources[source_index + 1:]
                    if remaining_sources:
                        logger.info(f"[{source.upper()}] 处理完成，仍有 {len(missing_episodes)} 集缺失，继续查询下一个源: {remaining_sources[0].upper()}")
                    else:
                        logger.info(f"[{source.upper()}] 处理完成，仍有 {len(missing_episodes)} 集缺失，已无更多可用源")

            # 更新订阅状态
            # 将网盘已存在的集数和本次成功转存的集数合并
            all_success_episodes = list(set(success_episodes) | existing_episodes_in_cloud)
            if all_success_episodes and not self._dry_run:
                self._subscribe_handler.check_and_finish_subscribe(
                    subscribe=subscribe,
                    mediainfo=mediainfo,
                    success_episodes=all_success_episodes
                )
                # 如果订阅已完成（缺失集数归零），清除该订阅的历史积分记录
                total_ep = subscribe.total_episode or 0
                start_ep = subscribe.start_episode or 1
                if total_ep > 0:
                    expected = set(range(start_ep, total_ep + 1))
                    downloaded = set(subscribe.note or []).union(set(all_success_episodes))
                    if not (expected - downloaded):
                        if hasattr(self._search_handler, 'clear_sub_points'):
                            self._search_handler.clear_sub_points(sub_key)

        except Exception as e:
            logger.error(f"处理订阅 {subscribe.name} 出错：{str(e)}")

        return transferred_count

    def send_transfer_notification(self, transfer_details: List[Dict[str, Any]], total_count: int):
        """
        发送转存完成通知

        :param transfer_details: 转存详情列表
        :param total_count: 转存总数
        """
        if not transfer_details or not self._post_message:
            return

        text_lines = []
        first_image = None

        for detail in transfer_details:
            if detail.get("type") == "电影":
                title = detail.get("title", "未知")
                year = detail.get("year", "")
                text_lines.append(f"{title} ({year})")
                if not first_image and detail.get("image"):
                    first_image = detail.get("image")
            else:
                title = detail.get("title", "未知")
                season = detail.get("season", 1)
                episodes = detail.get("episodes", [])
                episodes.sort()
                if len(episodes) <= 5:
                    ep_str = ", ".join([f"E{e:02d}" for e in episodes])
                else:
                    ep_str = f"E{episodes[0]:02d}-E{episodes[-1]:02d} 共{len(episodes)}集"
                text_lines.append(f"{title} S{season:02d} {ep_str}")
                if not first_image and detail.get("image"):
                    first_image = detail.get("image")

        if len(text_lines) > 10:
            text_lines = text_lines[:10]
            text_lines.append(f"... 等共 {len(transfer_details)} 项")

        self._post_message(
            mtype=NotificationType.Plugin,
            title=f"【115网盘订阅追更】转存完成",
            text=f"本次共转存 {total_count} 个文件\n\n" + "\n".join(text_lines)
        )
