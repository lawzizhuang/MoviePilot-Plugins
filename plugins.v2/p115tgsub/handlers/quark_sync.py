"""夸克订阅追更处理器：115 无可用候选时的兜底链路。

职责：Telegram/Telegraph 夸克候选校验 → 指定文件转存 → 目标目录二次确认
→ 订阅状态闭环 → SmartStrm 增量触发入队。
原则：
- 夸克网盘仅保存媒体文件；NFO/海报/STRM 一律由 SmartStrm 在本地生成；
- 已由 115 链路成功转存的集数绝不重复转存到夸克（不双盘重复）；
- 转存成功与 STRM 后处理解耦，Webhook 失败只入待重试队列；
- 测试模式只校验候选，不转存、不更新订阅、不触发 SmartStrm。
"""
import datetime
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.chain.download import DownloadChain
from app.core.metainfo import MetaInfo
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.db.subscribe_oper import SubscribeOper
from app.log import logger
from app.schemas import MediaInfo
from app.schemas.types import MediaType, NotificationType
from app.utils.string import StringUtils

from ..clients import QuarkShareClient
from ..utils import FileMatcher, SubscribeFilter, resource_year_matches, sanitize_resource_text
from .search import SearchHandler
from .strm_queue import StrmQueue
from .subscribe import SubscribeHandler


class QuarkSyncHandler:
    """夸克分享订阅追更处理器。"""

    def __init__(
        self,
        quark_client,
        search_handler: SearchHandler,
        subscribe_handler: SubscribeHandler,
        chain,
        save_path: str,
        movie_save_path: str,
        max_transfer_per_sync: int = 20,
        batch_size: int = 10,
        skip_other_season_dirs: bool = True,
        notify: bool = False,
        post_message_func: Callable = None,
        get_data_func: Callable = None,
        save_data_func: Callable = None,
        dry_run: bool = True,
        strm_enabled: bool = False,
        strm_client=None,
        strm_task: str = "",
        strm_xlist_path_fix: str = "",
        strm_max_attempts: int = 5,
        status_callback: Callable[..., None] = None,
    ) -> None:
        self._quark_client = quark_client
        self._search_handler = search_handler
        self._subscribe_handler = subscribe_handler
        self._chain = chain
        self._save_path = save_path
        self._movie_save_path = movie_save_path
        self._max_transfer_per_sync = max(1, min(int(max_transfer_per_sync or 20), 50))
        self._batch_size = max(1, min(int(batch_size or 10), 20))
        self._skip_other_season_dirs = bool(skip_other_season_dirs)
        self._post_message = post_message_func
        self._dry_run = bool(dry_run)
        self._strm_enabled = bool(strm_enabled)
        self._strm_client = strm_client
        self._strm_task = str(strm_task or "").strip()
        self._strm_xlist_path_fix = str(strm_xlist_path_fix or "").strip()
        self._strm_queue = StrmQueue(
            get_data_func=get_data_func,
            save_data_func=save_data_func,
            max_attempts=strm_max_attempts,
        )
        self._status_callback = status_callback
        self._failed_candidate_keys: Set[Tuple[str, str, str, str]] = set()

    def begin_run(self) -> None:
        """开始新的同步轮次；失败候选只在本轮抑制，不跨轮持久化。"""
        self._failed_candidate_keys.clear()

    def _record_status(self, event: str, **data: Any) -> None:
        """上报本轮脱敏运行状态；状态页不保存分享链接、访问码或凭据。"""
        if not self._status_callback:
            return
        try:
            self._status_callback(event, **data)
        except Exception:
            pass

    # ---------------- SmartStrm 后处理 ----------------

    def process_strm_retry_queue(self) -> Dict[str, Any]:
        """同步开始前先重试未完成的 SmartStrm 增量触发，不涉及转存。"""
        if not self._strm_enabled or not self._strm_client:
            return {"triggered": 0, "failed": 0, "stalled": 0}
        result = self._strm_queue.process_queue(self._strm_client)
        self._record_status("strm_retry", **result)
        if result.get("triggered") or result.get("failed") or result.get("stalled"):
            logger.info(
                f"SmartStrm 待重试队列处理：触发 {result.get('triggered')}，"
                f"失败 {result.get('failed')}，停滞 {result.get('stalled')}"
            )
        return result

    def _enqueue_strm(self, savepath: str, episodes: Optional[List[int]], title: str = "", year: str = "", media_type: str = "") -> bool:
        """转存并二次确认成功后入队；SmartStrm 未启用时直接跳过。"""
        if not self._strm_enabled or not self._strm_client:
            return False
        if not self._strm_task:
            logger.warning("SmartStrm 已启用但任务名为空，跳过后处理入队")
            return False
        item_id = self._strm_queue.enqueue(
            cloud="quark",
            title=title,
            year=year,
            media_type=media_type,
            episodes=episodes or [],
            savepath=savepath,
            strmtask=self._strm_task,
            xlist_path_fix=self._strm_xlist_path_fix,
        )
        if not item_id:
            return False
        outcome = self._strm_queue.trigger_one(item_id, self._strm_client)
        self._record_status("strm_trigger", success=bool(outcome.get("success")))
        return bool(outcome.get("success"))

    # ---------------- 标题与凭据辅助 ----------------

    @staticmethod
    def _resource_title_matches(mediainfo: MediaInfo, resource_title: str) -> bool:
        """与 115 链路一致的标题匹配：消息文本必须明确包含订阅标题。"""
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
        normalized_title = unicodedata.normalize("NFKC", title).casefold()
        normalized_text = unicodedata.normalize("NFKC", text).casefold()
        return len(normalized_title) == 1 and normalized_title in normalized_text

    @staticmethod
    def _candidate_password(candidate: Dict[str, Any]) -> str:
        """提取码来源：分享链接 query 优先，其次消息文本。"""
        info = QuarkShareClient.extract_share_info(str(candidate.get("url") or ""), "")
        password = info.get("password") or ""
        if not password:
            password = QuarkShareClient.extract_password(str(candidate.get("text") or ""))
        return password

    @staticmethod
    def _candidate_share_id(candidate: Dict[str, Any]) -> str:
        info = QuarkShareClient.extract_share_info(str(candidate.get("url") or ""), "")
        return info.get("share_id") or ""

    def _candidate_key(self, candidate: Dict[str, Any], title: str = "", season: Optional[int] = None) -> Tuple[str, str, str, str]:
        """失败抑制仅作用于同一媒体/季，避免合集分享误伤其他订阅。"""
        return (
            self._candidate_share_id(candidate), self._candidate_password(candidate),
            str(title or "").casefold(), str(season or ""),
        )

    def _should_skip_failed_candidate(self, candidate: Dict[str, Any], title: str = "", season: Optional[int] = None) -> bool:
        key = self._candidate_key(candidate, title, season)
        return bool(key[0] and key in self._failed_candidate_keys)

    def _mark_candidate_failed(self, candidate: Dict[str, Any], title: str = "", season: Optional[int] = None) -> None:
        key = self._candidate_key(candidate, title, season)
        if key[0]:
            self._failed_candidate_keys.add(key)

    @staticmethod
    def _candidate_source(candidate: Dict[str, Any]) -> str:
        """返回公开来源定位信息，不包含分享 URL 或访问码。"""
        channel = str(candidate.get("channel") or "未知频道").strip()
        message_id = str(candidate.get("message_id") or "").strip()
        return f"{channel}/{message_id}" if message_id else channel

    @staticmethod
    def _fallback_missing_episodes_from_subscribe(subscribe) -> List[int]:
        """与 115 链路一致：媒体库无缺集明细时按订阅声明范围回退。"""
        try:
            total_episode = int(getattr(subscribe, "total_episode", 0) or 0)
            start_episode = max(1, int(getattr(subscribe, "start_episode", 1) or 1))
        except (TypeError, ValueError):
            return []
        if total_episode < start_episode:
            return []
        return list(range(start_episode, total_episode + 1))

    def _resolve_missing_episodes(self, subscribe, meta, mediainfo: MediaInfo, season: int) -> Tuple[bool, List[int]]:
        """返回（媒体库已完整，实际缺失集）；媒体库无明细时才按订阅范围回退。"""
        totals = {}
        if getattr(subscribe, "season", None) and getattr(subscribe, "total_episode", None):
            totals = {subscribe.season: subscribe.total_episode}
        missing_episodes: List[int] = []
        try:
            exist_flag, no_exists = DownloadChain().get_no_exists_info(
                meta=meta, mediainfo=mediainfo, totals=totals
            )
            if exist_flag:
                return True, []
            mediakey = mediainfo.tmdb_id or mediainfo.douban_id
            if no_exists and mediakey:
                not_exist_info = (no_exists.get(mediakey, {}) or {}).get(season)
                if not_exist_info:
                    missing_episodes = list(not_exist_info.episodes or [])
                    if not missing_episodes and not_exist_info.total_episode:
                        start_ep = not_exist_info.start_episode or 1
                        missing_episodes = list(range(start_ep, not_exist_info.total_episode + 1))
        except Exception as exc:
            logger.warning(f"{mediainfo.title_year} S{season} 获取媒体库缺集失败：{exc}，改用订阅范围")

        if not missing_episodes:
            missing_episodes = self._fallback_missing_episodes_from_subscribe(subscribe)
            if missing_episodes:
                logger.warning(
                    f"{mediainfo.title_year} S{season} 未获取媒体库缺集明细；"
                    f"按订阅范围回退 E{missing_episodes[0]:02d}-E{missing_episodes[-1]:02d}"
                )
        if getattr(subscribe, "start_episode", None):
            missing_episodes = [ep for ep in missing_episodes if ep >= subscribe.start_episode]

        if missing_episodes and mediainfo.tmdb_id:
            try:
                from app.chain.tmdb import TmdbChain
                tmdb_episodes = TmdbChain().tmdb_episodes(tmdbid=mediainfo.tmdb_id, season=season)
                if tmdb_episodes:
                    today = datetime.date.today().isoformat()
                    aired = {
                        ep.episode_number for ep in tmdb_episodes
                        if ep.episode_number and ep.air_date and ep.air_date <= today
                    }
                    if aired:
                        missing_episodes = [ep for ep in missing_episodes if ep in aired]
            except Exception as exc:
                logger.warning(f"{mediainfo.title_year} S{season} 查询 TMDB 播出日期失败：{exc}")
        return False, missing_episodes

    # ---------------- 电影订阅 ----------------

    def process_movie_subscribe(
        self,
        subscribe,
        history: List[dict],
        transfer_details: List[Dict[str, Any]],
        transferred_count: int,
    ) -> int:
        """处理单个电影订阅：仅当 115 链路未成功时尝试夸克。"""
        try:
            if not self._quark_client:
                logger.warning("夸克客户端未初始化，跳过夸克电影链路")
                return transferred_count
            logger.info(f"处理夸克电影订阅：{subscribe.name} ({subscribe.year})")

            meta = MetaInfo(subscribe.name)
            meta.year = subscribe.year
            meta.type = MediaType.MOVIE
            mediainfo: MediaInfo = self._chain.recognize_media(
                meta=meta, mtype=MediaType.MOVIE,
                tmdbid=subscribe.tmdbid, doubanid=subscribe.doubanid, cache=True,
            )
            if not mediainfo:
                logger.warn(f"无法识别媒体信息：{subscribe.name}")
                return transferred_count

            # 已由 115/夸克成功转存过（history），不双盘重复转存。
            # 洗版中的非完美历史不能完成订阅，也不能用夸克跨盘重复洗版。
            is_best_version = bool(getattr(subscribe, "best_version", False))
            successful_history = []
            for h in history:
                same_media = (
                    h.get("tmdb_id") and mediainfo.tmdb_id
                    and str(h.get("tmdb_id")) == str(mediainfo.tmdb_id)
                ) or (
                    h.get("title") in {subscribe.name, mediainfo.title}
                    and (not h.get("year") or not mediainfo.year or str(h.get("year")) == str(mediainfo.year))
                )
                if same_media and h.get("type") == "电影" and h.get("status") == "成功":
                    successful_history.append(h)
            if successful_history:
                if is_best_version and not any(bool(h.get("perfect_match", False)) for h in successful_history):
                    logger.info(
                        f"电影 {mediainfo.title} 存在待洗版的历史资源；"
                        "夸克链路不跨盘洗版，保持订阅待处理"
                    )
                    return transferred_count
                if not self._dry_run:
                    self._subscribe_handler.check_and_finish_subscribe(
                        subscribe=subscribe, mediainfo=mediainfo, success_episodes=[1]
                    )
                logger.info(f"电影 {mediainfo.title} 已在历史记录中（115/夸克），夸克链路跳过")
                return transferred_count

            quark_results = self._search_handler.search_quark_resources(
                mediainfo=mediainfo, media_type=MediaType.MOVIE
            )
            if not quark_results:
                logger.info(f"未找到电影 {mediainfo.title} 的夸克网盘资源")
                return transferred_count
            logger.info(f"找到 {len(quark_results)} 个夸克网盘资源")
            self._record_status("quark_candidates", count=len(quark_results), title=mediainfo.title, media_type="电影")

            subscribe_filter = SubscribeFilter(
                quality=subscribe.quality, resolution=subscribe.resolution,
                effect=subscribe.effect, strict=True,
            )
            save_dir = f"{self._movie_save_path}/{mediainfo.title} ({mediainfo.year})" if mediainfo.year else f"{self._movie_save_path}/{mediainfo.title}"

            for resource in quark_results:
                if self._should_skip_failed_candidate(resource, mediainfo.title):
                    self._record_status("quark_failure", category="suppressed_duplicate", title=mediainfo.title)
                    logger.info("夸克候选本轮已确认不可用，跳过重复校验")
                    continue
                share_url = resource.get("url", "")
                resource_title = resource.get("title", "")
                safe_resource_title = sanitize_resource_text(resource_title)
                if not self._resource_title_matches(mediainfo, resource_title):
                    logger.info(f"跳过标题未明确匹配当前订阅的夸克候选：{safe_resource_title}")
                    continue
                logger.info(f"检查夸克分享（来源 {self._candidate_source(resource)}）：{safe_resource_title}")
                try:
                    password = self._candidate_password(resource)
                    status = self._quark_client.check_share_status(share_url, password=password)
                    if not status.is_valid:
                        self._mark_candidate_failed(resource, mediainfo.title)
                        self._record_status("quark_failure", category=getattr(status, "error_category", "") or "api_error", title=mediainfo.title)
                        logger.warning(f"夸克候选跳过：{status.status_text}")
                        continue
                    if not resource_year_matches(
                        mediainfo.year,
                        resource_title,
                        title=mediainfo.title,
                        canonical_titles=(status.share_info.get("share_title", ""),),
                    ):
                        logger.info(f"跳过年份与订阅不匹配的夸克候选：{safe_resource_title}")
                        continue
                    share_files = self._quark_client.list_share_files(share_url, password=password)
                    if not share_files:
                        self._mark_candidate_failed(resource, mediainfo.title)
                        self._record_status("quark_failure", category="empty_share", title=mediainfo.title)
                        logger.info("夸克分享链接无内容")
                        continue
                    matched_file = FileMatcher.match_movie_file(
                        share_files, mediainfo.title, subscribe_filter=subscribe_filter
                    )
                    if not matched_file:
                        self._mark_candidate_failed(resource, mediainfo.title)
                        self._record_status("quark_failure", category="no_matching_episode", title=mediainfo.title)
                        continue
                    file_name = matched_file.get("name", "")
                    logger.info(f"找到夸克匹配文件：{file_name}")

                    if self._dry_run:
                        logger.info(f"测试模式：已验证夸克电影候选，不执行转存：{file_name}")
                        continue

                    # 已有同名媒体不再次转存：可覆盖“异步任务超时但稍后完成”的场景。
                    preexisting = self._quark_client.confirm_files_exist(
                        save_dir, [file_name], retries=1, interval=0.5
                    )
                    if file_name in preexisting:
                        logger.info(f"夸克目标目录已存在电影文件，跳过重复转存：{file_name}")
                        history.append({
                            "title": mediainfo.title, "year": mediainfo.year, "tmdb_id": mediainfo.tmdb_id,
                            "type": "电影", "status": "成功", "cloud": "quark",
                            "share_id": self._candidate_share_id(resource), "file_name": file_name,
                            "filter_score": 0, "perfect_match": True,
                            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })
                        self._subscribe_handler.check_and_finish_subscribe(
                            subscribe=subscribe, mediainfo=mediainfo, success_episodes=[1]
                        )
                        self._enqueue_strm(
                            savepath=save_dir, episodes=None, title=mediainfo.title,
                            year=str(mediainfo.year or ""), media_type="电影",
                        )
                        return transferred_count

                    _success_ids, _ = self._quark_client.transfer_files_batch(
                        share_url=share_url, file_ids=[matched_file.get("id")],
                        save_path=save_dir, password=password, batch_size=self._batch_size,
                    )
                    # 保存接口/任务超时不等于转存失败；一律以目标目录二次确认裁决。
                    confirmed = self._quark_client.confirm_files_exist(save_dir, [file_name])
                    success = file_name in confirmed

                    history.append({
                        "title": mediainfo.title, "year": mediainfo.year, "tmdb_id": mediainfo.tmdb_id,
                        "type": "电影",
                        "status": "成功" if success else "失败",
                        "cloud": "quark", "share_id": self._candidate_share_id(resource),
                        "file_name": file_name,
                        "filter_score": 0, "perfect_match": True,
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    if not success:
                        logger.error(f"夸克转存失败或文件未确认存在：{mediainfo.title}")
                        continue

                    transferred_count += 1
                    self._record_status("quark_transferred", count=1, title=mediainfo.title, media_type="电影", stage="夸克转存成功，SmartStrm 后处理待执行")
                    logger.info(f"成功转存夸克电影：{mediainfo.title}")
                    transfer_details.append({
                        "type": "电影", "cloud": "quark", "title": mediainfo.title,
                        "year": mediainfo.year, "image": mediainfo.get_poster_image(),
                        "file_name": file_name,
                    })
                    try:
                        DownloadHistoryOper().add(
                            path=save_dir, type=mediainfo.type.value, title=mediainfo.title,
                            year=mediainfo.year, tmdbid=mediainfo.tmdb_id,
                            imdbid=mediainfo.imdb_id, tvdbid=mediainfo.tvdb_id,
                            doubanid=mediainfo.douban_id, image=mediainfo.get_poster_image(),
                            downloader="夸克网盘", download_hash=matched_file.get("id"),
                            torrent_name=safe_resource_title, torrent_description=file_name,
                            torrent_site="夸克网盘", username="P115TGSub",
                            date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            note={"source": f"Subscribe|{subscribe.name}",
                                  "cloud": "quark", "share_id": self._candidate_share_id(resource)},
                        )
                    except Exception as e:
                        logger.warning(f"记录夸克下载历史失败：{e}")
                    self._subscribe_handler.check_and_finish_subscribe(
                        subscribe=subscribe, mediainfo=mediainfo, success_episodes=[1]
                    )
                    self._enqueue_strm(
                        savepath=save_dir, episodes=None, title=mediainfo.title,
                        year=str(mediainfo.year or ""), media_type="电影",
                    )
                    break
                except Exception as e:
                    logger.error(f"处理夸克分享链接出错：{e}")
                    continue
        except Exception as e:
            logger.error(f"处理夸克电影订阅 {subscribe.name} 出错：{e}")
        return transferred_count

    # ---------------- 电视剧订阅 ----------------

    def process_tv_subscribe(
        self,
        subscribe,
        history: List[dict],
        transfer_details: List[Dict[str, Any]],
        transferred_count: int,
        exclude_ids: Set[int],
    ) -> int:
        """处理单个电视剧订阅：仅在 115 链路遗留的缺失集上尝试夸克。"""
        try:
            if not self._quark_client:
                logger.warning("夸克客户端未初始化，跳过夸克电视剧链路")
                return transferred_count
            logger.info(f"处理夸克电视剧订阅：{subscribe.name} (S{subscribe.season or 1})")
            if subscribe.lack_episode == 0:
                logger.info(f"{subscribe.name} S{subscribe.season or 1} 订阅显示媒体库已完整，夸克链路跳过")
                return transferred_count

            meta = MetaInfo(subscribe.name)
            meta.year = subscribe.year
            meta.begin_season = subscribe.season or 1
            meta.type = MediaType.TV
            mediainfo: MediaInfo = self._chain.recognize_media(
                meta=meta, mtype=MediaType.TV,
                tmdbid=subscribe.tmdbid, doubanid=subscribe.doubanid, cache=True,
            )
            if not mediainfo:
                logger.warn(f"无法识别媒体信息：{subscribe.name}")
                return transferred_count

            season = meta.begin_season or 1

            library_complete, missing_episodes = self._resolve_missing_episodes(
                subscribe, meta, mediainfo, season
            )
            if library_complete:
                all_episodes = self._fallback_missing_episodes_from_subscribe(subscribe)
                if self._dry_run:
                    logger.info(f"{mediainfo.title_year} S{season} 媒体库中已完整存在；测试模式不修改订阅")
                    return transferred_count
                if all_episodes:
                    self._subscribe_handler.check_and_finish_subscribe(
                        subscribe=subscribe, mediainfo=mediainfo, success_episodes=all_episodes
                    )
                elif getattr(subscribe, "lack_episode", 0) != 0:
                    SubscribeOper().update(subscribe.id, {"lack_episode": 0})
                    subscribe.lack_episode = 0
                logger.info(f"{mediainfo.title_year} S{season} 媒体库中已完整存在，夸克链路跳过")
                return transferred_count
            if not missing_episodes:
                logger.info(f"{mediainfo.title_year} S{season} 无实际缺失或已播剧集，夸克链路跳过")
                return transferred_count

            # 排除订阅 note、115/夸克历史成功集（不双盘重复转存）
            transferred_episodes = set()
            for value in (getattr(subscribe, "note", None) or []):
                try:
                    transferred_episodes.add(int(value))
                except (TypeError, ValueError):
                    continue
            for h in history:
                if (
                    h.get("title") == mediainfo.title
                    and h.get("season") == season
                    and h.get("status") == "成功"
                    and h.get("episode")
                ):
                    try:
                        transferred_episodes.add(int(h.get("episode")))
                    except (TypeError, ValueError):
                        logger.warning("忽略格式异常的夸克/115剧集历史记录")

            show_folder = f"{mediainfo.title} ({mediainfo.year})" if mediainfo.year else mediainfo.title
            save_dir = f"{self._save_path}/{show_folder}/Season {season}"

            existing_in_cloud = FileMatcher.check_existing_episodes(
                self._quark_client, mediainfo, season, save_dir
            )
            all_existing = transferred_episodes | existing_in_cloud
            if all_existing:
                missing_episodes = [ep for ep in missing_episodes if ep not in all_existing]
                logger.info(
                    f"{mediainfo.title_year} S{season} 跳过已存在的 {len(all_existing)} 集 "
                    f"(历史:{len(transferred_episodes)}, 夸克网盘:{len(existing_in_cloud)})"
                )
            if not missing_episodes:
                if all_existing and not self._dry_run:
                    self._subscribe_handler.check_and_finish_subscribe(
                        subscribe=subscribe, mediainfo=mediainfo,
                        success_episodes=sorted(all_existing),
                    )
                logger.info(f"{mediainfo.title_year} S{season} 所有缺失剧集已由 115/夸克补齐，夸克链路跳过")
                return transferred_count

            logger.info(f"{mediainfo.title_year} S{season} 夸克待转存剧集：{missing_episodes}")

            quark_results = self._search_handler.search_quark_resources(
                mediainfo=mediainfo, media_type=MediaType.TV, season=season
            )
            if not quark_results:
                logger.info(f"未找到 {mediainfo.title} S{season} 的夸克网盘资源")
                return transferred_count
            logger.info(f"找到 {len(quark_results)} 个夸克网盘资源")
            self._record_status("quark_candidates", count=len(quark_results), title=mediainfo.title, season=season, media_type="电视剧")

            subscribe_filter = SubscribeFilter(
                quality=subscribe.quality, resolution=subscribe.resolution,
                effect=subscribe.effect, strict=True,
            )
            success_episodes: List[int] = []

            for resource in quark_results:
                if not missing_episodes:
                    break
                if self._should_skip_failed_candidate(resource, mediainfo.title, season):
                    self._record_status("quark_failure", category="suppressed_duplicate", title=mediainfo.title, season=season)
                    logger.info("夸克候选本轮已确认不可用，跳过重复校验")
                    continue
                if transferred_count >= self._max_transfer_per_sync:
                    logger.info(f"已达单次同步上限 {self._max_transfer_per_sync}，夸克链路停止")
                    break
                share_url = resource.get("url", "")
                resource_title = resource.get("title", "")
                safe_resource_title = sanitize_resource_text(resource_title)
                if not self._resource_title_matches(mediainfo, resource_title):
                    logger.info(f"跳过标题未明确匹配当前订阅的夸克候选：{safe_resource_title}")
                    continue
                logger.info(f"检查夸克分享（来源 {self._candidate_source(resource)}）：{safe_resource_title}")
                try:
                    password = self._candidate_password(resource)
                    status = self._quark_client.check_share_status(share_url, password=password)
                    if not status.is_valid:
                        self._mark_candidate_failed(resource, mediainfo.title, season)
                        self._record_status("quark_failure", category=getattr(status, "error_category", "") or "api_error", title=mediainfo.title, season=season)
                        logger.warning(f"夸克候选跳过：{status.status_text}")
                        continue
                    if not resource_year_matches(
                        mediainfo.year,
                        resource_title,
                        title=mediainfo.title,
                        canonical_titles=(status.share_info.get("share_title", ""),),
                    ):
                        logger.info(f"跳过年份与订阅不匹配的夸克候选：{safe_resource_title}")
                        continue
                    share_files = self._quark_client.list_share_files(
                        share_url, password=password,
                        target_season=(season if self._skip_other_season_dirs else None),
                    )
                    if not share_files:
                        self._mark_candidate_failed(resource, mediainfo.title, season)
                        self._record_status("quark_failure", category="empty_share", title=mediainfo.title, season=season)
                        logger.info("夸克分享链接无内容")
                        continue

                    matched_items = []
                    for episode in missing_episodes[:]:
                        matched_file = FileMatcher.match_episode_file(
                            share_files, mediainfo.title, season, episode,
                            subscribe_filter=subscribe_filter,
                        )
                        if matched_file:
                            file_name = matched_file.get("name", "")
                            logger.info(f"找到夸克匹配文件：{file_name} -> E{episode:02d}")
                            matched_items.append({"file": matched_file, "episode": episode})
                    if not matched_items:
                        self._mark_candidate_failed(resource, mediainfo.title, season)
                        self._record_status("quark_failure", category="no_matching_episode", title=mediainfo.title, season=season)
                        logger.info(f"该夸克分享未匹配到 S{season} 的任何缺失剧集")
                        continue

                    remaining_quota = self._max_transfer_per_sync - transferred_count
                    if len(matched_items) > remaining_quota:
                        matched_items = matched_items[:remaining_quota]

                    if self._dry_run:
                        logger.info(
                            f"测试模式：已验证夸克 {mediainfo.title} S{season:02d} "
                            f"候选集数 {[item['episode'] for item in matched_items]}，不执行转存"
                        )
                        continue

                    file_ids = [item["file"]["id"] for item in matched_items]
                    logger.info(f"准备批量转存 {len(file_ids)} 个夸克文件到: {save_dir}")
                    _success_ids, _ = self._quark_client.transfer_files_batch(
                        share_url=share_url, file_ids=file_ids, save_path=save_dir,
                        password=password, batch_size=self._batch_size,
                    )

                    confirmed_names = self._quark_client.confirm_files_exist(
                        save_dir, [item["file"]["name"] for item in matched_items]
                    )

                    batch_success_episodes: List[int] = []
                    for item in matched_items:
                        file_id = item["file"]["id"]
                        episode = item["episode"]
                        file_name = item["file"]["name"]
                        success = file_name in confirmed_names
                        history.append({
                            "title": mediainfo.title, "season": season, "episode": episode,
                            "type": "电视剧", "status": "成功" if success else "失败",
                            "cloud": "quark", "share_id": self._candidate_share_id(resource),
                            "file_name": file_name, "filter_score": 0, "perfect_match": True,
                            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })
                        if not success:
                            logger.error(f"夸克转存失败或未确认存在：{mediainfo.title} S{season:02d}E{episode:02d}")
                            continue
                        transferred_count += 1
                        self._record_status(
                            "quark_transferred", count=1, title=mediainfo.title, season=season,
                            episode=episode, media_type="电视剧", stage=f"夸克转存成功 E{episode:02d}，SmartStrm 后处理待执行",
                        )
                        missing_episodes.remove(episode)
                        success_episodes.append(episode)
                        batch_success_episodes.append(episode)
                        logger.info(f"成功转存夸克：{mediainfo.title} S{season:02d}E{episode:02d}")
                        existing_detail = next(
                            (d for d in transfer_details
                             if d.get("title") == mediainfo.title and d.get("season") == season),
                            None,
                        )
                        if existing_detail:
                            existing_detail["episodes"].append(episode)
                        else:
                            transfer_details.append({
                                "type": "电视剧", "cloud": "quark", "title": mediainfo.title,
                                "year": mediainfo.year, "season": season,
                                "episodes": [episode], "image": mediainfo.get_poster_image(),
                            })

                    if batch_success_episodes:
                        try:
                            episodes_str = StringUtils.format_ep(sorted(set(batch_success_episodes)))
                            DownloadHistoryOper().add(
                                path=save_dir, type=mediainfo.type.value, title=mediainfo.title,
                                year=mediainfo.year, tmdbid=mediainfo.tmdb_id,
                                imdbid=mediainfo.imdb_id, tvdbid=mediainfo.tvdb_id,
                                doubanid=mediainfo.douban_id, seasons=f"S{season:02d}",
                                episodes=episodes_str, image=mediainfo.get_poster_image(),
                                downloader="夸克网盘", download_hash=self._candidate_share_id(resource),
                                torrent_name=safe_resource_title, torrent_site="夸克网盘",
                                username="P115TGSub",
                                date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                note={"source": f"Subscribe|{subscribe.name}",
                                      "cloud": "quark", "share_id": self._candidate_share_id(resource)},
                            )
                        except Exception as e:
                            logger.warning(f"记录夸克下载历史失败：{e}")
                except Exception as e:
                    logger.error(f"处理夸克分享链接出错：{e}")
                    continue

            if success_episodes:
                self._subscribe_handler.check_and_finish_subscribe(
                    subscribe=subscribe, mediainfo=mediainfo,
                    success_episodes=list(set(success_episodes) | existing_in_cloud),
                )
                self._enqueue_strm(
                    savepath=save_dir, episodes=list(set(success_episodes)),
                    title=mediainfo.title, year=str(mediainfo.year or ""), media_type="电视剧",
                )
        except Exception as e:
            logger.error(f"处理夸克电视剧订阅 {subscribe.name} 出错：{e}")
        return transferred_count

    # ---------------- 通知 ----------------

    def send_transfer_notification(self, transfer_details: List[Dict[str, Any]], total_count: int) -> None:
        if not transfer_details or not self._post_message:
            return
        text_lines = []
        first_image = None
        for detail in transfer_details:
            if detail.get("type") == "电影":
                title = detail.get("title", "未知")
                year = detail.get("year", "")
                text_lines.append(f"[夸克] {title} ({year})")
                if not first_image and detail.get("image"):
                    first_image = detail.get("image")
            else:
                title = detail.get("title", "未知")
                season = detail.get("season", 1)
                episodes = sorted(detail.get("episodes", []))
                if len(episodes) <= 5:
                    ep_str = ", ".join([f"E{e:02d}" for e in episodes])
                else:
                    ep_str = f"E{episodes[0]:02d}-E{episodes[-1]:02d} 共{len(episodes)}集"
                text_lines.append(f"[夸克] {title} S{season:02d} {ep_str}")
                if not first_image and detail.get("image"):
                    first_image = detail.get("image")
        if len(text_lines) > 10:
            text_lines = text_lines[:10]
            text_lines.append(f"... 等共 {len(transfer_details)} 项")
        self._post_message(
            mtype=NotificationType.Plugin,
            title="【夸克网盘订阅追更】转存完成",
            text=f"本次共转存 {total_count} 个夸克文件\n\n" + "\n".join(text_lines),
        )
