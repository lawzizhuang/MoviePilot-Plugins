"""115 Telegram 公开频道订阅追更插件。"""
import datetime
from threading import Lock, Thread
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import Event, eventmanager
from app.db import SessionFactory
from app.db.subscribe_oper import SubscribeOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaType, NotificationType

from .clients import FourKMonitorClient, P115ClientManager, QuarkShareClient, SeedHubClient, SmartStrmClient, TelegramWebClient
from .handlers import QuarkSyncHandler, SearchHandler, SubscribeHandler, SyncHandler
from .ui import UIConfig

lock = Lock()
run_state_lock = Lock()


class P115TGSub(_PluginBase):
    """从 Telegram 公开频道搜索 115/夸克分享资源的 MoviePilot 订阅追更插件。"""

    plugin_name = "115 TG订阅追更"
    plugin_desc = "读取 MoviePilot 订阅，直接搜索 Telegram 公开频道中的 115/夸克分享资源并补齐缺失内容。"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/cloud.png"
    plugin_version = "2.4.7"
    plugin_author = "lawzizhuang"
    author_url = "https://github.com/lawzizhuang/MoviePilot-Plugins"
    plugin_config_prefix = "p115tgsub_"
    plugin_order = 21
    auth_level = 1

    _enabled = False
    _notify = True
    _onlyonce = False
    _cron = "30 */8 * * *"
    _cookie_source = "p115strmhelper"
    _cookies = ""
    _save_path = "/我的接收/MoviePilot-TG/TV"
    _movie_save_path = "/我的接收/MoviePilot-TG/Movie"
    _telegram_enabled = True
    _telegram_channels = "QukanMovie\nlsp115\nvip115hot"
    _telegram_timeout = 20
    _telegram_max_results = 10
    _telegram_max_telegraph_pages = 3
    _max_transfer_per_sync = 20
    _batch_size = 10
    _skip_other_season_dirs = True
    _quark_enabled = False
    _quark_timeout = 30
    _quark_risk_cooldown = 1800
    _quark_save_path = "/夸克接收/MoviePilot-TG/TV"
    _quark_movie_save_path = "/夸克接收/MoviePilot-TG/Movie"
    _strm_enabled = False
    _smartstrm_webhook_url = ""
    _smartstrm_task = "tv,movie"
    _smartstrm_xlist_path_fix = ""
    _strm_retry_max = 5
    _offline_enabled = False
    _offline_max_per_sync = 5
    _offline_max_wait_hours = 24
    _seedhub_enabled = False
    _seedhub_channel = "seedhub_pro"
    _seedhub_timeout = 20
    _seedhub_max_candidates = 5
    _seedhub_use_proxy = False
    _fourkmonitor_enabled = True
    _fourkmonitor_timeout = 20
    _fourkmonitor_max_candidates = 3
    _fourkmonitor_interval_seconds = 2
    _fourkmonitor_use_proxy = False
    _quark_client = None
    _seedhub_client = None
    _fourkmonitor_client = None
    _strm_client = None
    _sync_running = False
    _progress_repair_running = False
    _run_requested = False
    _run_status: Dict[str, Any] = {}

    _scheduler: Optional[BackgroundScheduler] = None
    _telegram_client: Optional[TelegramWebClient] = None
    _p115_manager: Optional[P115ClientManager] = None
    _search_handler: Optional[SearchHandler] = None
    _subscribe_handler: Optional[SubscribeHandler] = None
    _sync_handler: Optional[SyncHandler] = None
    _quark_handler: Optional[QuarkSyncHandler] = None

    _MIN_INTERVAL_HOURS = 8

    @staticmethod
    def _int_config(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(int(value), maximum))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _cron_interval_ge_min_hours(cls, cron_expr: str) -> bool:
        cron_expr = str(cron_expr or "").strip()
        if not cron_expr:
            return False
        try:
            tz = pytz.timezone(settings.TZ)
            trigger = CronTrigger.from_crontab(cron_expr, timezone=tz)
        except Exception:
            return False

        now = datetime.datetime.now(tz=pytz.timezone(settings.TZ))
        times = []
        previous = None
        current = now
        for _ in range(12):
            next_time = trigger.get_next_fire_time(previous, current)
            if not next_time:
                break
            times.append(next_time)
            previous = next_time
            current = next_time + datetime.timedelta(seconds=1)
        if len(times) < 2:
            return True
        return min(times[i + 1] - times[i] for i in range(len(times) - 1)) >= datetime.timedelta(hours=cls._MIN_INTERVAL_HOURS)

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._notify = bool(config.get("notify", True))
        self._onlyonce = bool(config.get("onlyonce", False))
        self._cron = str(config.get("cron", self._cron) or "").strip()
        if self._cron and not self._cron_interval_ge_min_hours(self._cron):
            logger.warning(f"Cron 间隔必须不少于 {self._MIN_INTERVAL_HOURS} 小时，已使用默认值 30 */8 * * *")
            self._cron = "30 */8 * * *"

        self._cookie_source = str(config.get("cookie_source", "p115strmhelper") or "p115strmhelper").strip().lower()
        if self._cookie_source not in {"p115strmhelper", "p115disk", "local"}:
            self._cookie_source = "p115strmhelper"
        self._cookies = str(config.get("cookies", "") or "").strip()
        self._save_path = str(config.get("save_path", self._save_path) or self._save_path).strip()
        self._movie_save_path = str(config.get("movie_save_path", self._movie_save_path) or self._movie_save_path).strip()
        self._telegram_enabled = bool(config.get("telegram_enabled", True))
        self._telegram_channels = str(config.get("telegram_channels", self._telegram_channels) or "")
        self._telegram_timeout = self._int_config(config.get("telegram_timeout", 20), 20, 5, 60)
        self._telegram_max_results = self._int_config(config.get("telegram_max_results", 10), 10, 1, 20)
        self._telegram_max_telegraph_pages = self._int_config(config.get("telegram_max_telegraph_pages", 3), 3, 0, 10)
        self._max_transfer_per_sync = self._int_config(config.get("max_transfer_per_sync", 20), 20, 1, 50)
        self._batch_size = self._int_config(config.get("batch_size", 10), 10, 1, 20)
        self._skip_other_season_dirs = bool(config.get("skip_other_season_dirs", True))
        self._dry_run = bool(config.get("dry_run", True))
        # 夸克：115 无可用候选时兜底；SmartStrm 负责本地 STRM 后处理。
        self._quark_enabled = bool(config.get("quark_enabled", False))
        self._quark_timeout = self._int_config(config.get("quark_timeout", 30), 30, 5, 60)
        self._quark_risk_cooldown = self._int_config(
            config.get("quark_risk_cooldown", 1800), 1800, 300, 86400
        )
        self._quark_save_path = str(config.get("quark_save_path", self._quark_save_path) or self._quark_save_path).strip()
        self._quark_movie_save_path = str(config.get("quark_movie_save_path", self._quark_movie_save_path) or self._quark_movie_save_path).strip()
        self._strm_enabled = bool(config.get("strm_enabled", False))
        self._smartstrm_webhook_url = str(config.get("smartstrm_webhook_url", "") or "").strip()
        self._smartstrm_task = str(config.get("smartstrm_task", "tv,movie") or "tv,movie").strip()
        self._smartstrm_xlist_path_fix = str(config.get("smartstrm_xlist_path_fix", "") or "").strip()
        self._strm_retry_max = self._int_config(config.get("strm_retry_max", 5), 5, 1, 20)
        self._offline_enabled = bool(config.get("offline_enabled", False))
        self._offline_max_per_sync = self._int_config(config.get("offline_max_per_sync", 5), 5, 1, 20)
        self._offline_max_wait_hours = self._int_config(config.get("offline_max_wait_hours", 24), 24, 1, 168)
        self._seedhub_enabled = bool(config.get("seedhub_enabled", False))
        self._seedhub_channel = str(config.get("seedhub_channel", "seedhub_pro") or "seedhub_pro").strip()
        self._seedhub_timeout = self._int_config(config.get("seedhub_timeout", 20), 20, 5, 60)
        self._seedhub_max_candidates = self._int_config(config.get("seedhub_max_candidates", 5), 5, 1, 20)
        # SeedHub 公开页通常无需 Telegram 代理；默认直连可避免代理出口触发站点访问限制。
        self._seedhub_use_proxy = bool(config.get("seedhub_use_proxy", False))
        self._fourkmonitor_enabled = bool(config.get("fourkmonitor_enabled", True))
        self._fourkmonitor_timeout = self._int_config(config.get("fourkmonitor_timeout", 20), 20, 5, 60)
        self._fourkmonitor_max_candidates = self._int_config(config.get("fourkmonitor_max_candidates", 3), 3, 1, 10)
        self._fourkmonitor_interval_seconds = self._int_config(
            config.get("fourkmonitor_interval_seconds", 2), 2, 1, 10
        )
        self._fourkmonitor_use_proxy = bool(config.get("fourkmonitor_use_proxy", False))
        try:
            self._init_clients()
            self._init_handlers()
        except Exception as exc:
            logger.error(f"115 TG订阅追更初始化失败：{exc}")
            self._telegram_client = None
            self._p115_manager = None
            self._search_handler = None
            self._subscribe_handler = None
            self._sync_handler = None
            self._quark_handler = None
            self._quark_client = None
            self._seedhub_client = None
            self._fourkmonitor_client = None
            self._strm_client = None
            return

        if self._onlyonce:
            self._onlyonce = False
            self.update_config(self._config_snapshot())
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(
                self.sync_subscribes,
                trigger="date",
                run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3),
                name="115 TG订阅追更立即运行",
            )
            self._scheduler.start()

    def _resolve_p115_cookie(self) -> str:
        """按配置获取 115 Cookie；优先复用 115网盘STRM助手的实际运行凭据。"""
        if self._cookie_source == "local":
            return self._cookies

        source = {
            "p115strmhelper": ("P115StrmHelper", "cookies", "115网盘STRM助手（P115StrmHelper）"),
            "p115disk": ("P115Disk", "cookie", "115网盘储存（P115Disk）"),
        }
        plugin_id, cookie_key, display_name = source[self._cookie_source]
        plugin_config = self.get_config(plugin_id) or {}
        if not isinstance(plugin_config, dict):
            logger.error(f"读取 {display_name} 配置失败")
            return ""
        cookie = str(plugin_config.get(cookie_key, "") or "").strip()
        if not cookie:
            logger.error(
                f"未在 {display_name} 中找到有效 Cookie；请先完成其配置，"
                "或将凭据来源切换为“本插件独立 Cookie”"
            )
            return ""
        logger.info(f"115 TG订阅追更已复用 {display_name} 的 Cookie 配置")
        return cookie

    def _resolve_quark_cookie(self) -> str:
        """仅在运行时读取 QuarkDisk Cookie，绝不复制到本插件配置或日志。"""
        quark_config = self.get_config("QuarkDisk") or {}
        if not isinstance(quark_config, dict):
            logger.error("读取夸克网盘存储（QuarkDisk）配置失败")
            return ""
        cookie = str(quark_config.get("cookie", "") or "").strip()
        if not cookie:
            logger.error("未在夸克网盘存储（QuarkDisk）中找到有效 Cookie")
            return ""
        logger.info("115 TG订阅追更已复用夸克网盘存储（QuarkDisk）的 Cookie 配置")
        return cookie

    def _init_clients(self) -> None:
        proxy = settings.PROXY
        self._telegram_client = TelegramWebClient(
            channels=self._telegram_channels,
            proxy=proxy,
            timeout=self._telegram_timeout,
            max_results_per_channel=self._telegram_max_results,
            max_telegraph_pages=self._telegram_max_telegraph_pages,
        )
        if self._telegram_enabled:
            channel_count = len(self._telegram_client.channels)
            if channel_count:
                logger.info(
                    f"115 TG订阅追更已加载 {channel_count} 个 Telegram 公开频道："
                    f"{', '.join(self._telegram_client.channels)}"
                )
            else:
                logger.warning("Telegram 搜索已启用但未配置有效公开频道")
        self._seedhub_client = SeedHubClient(
            proxy=proxy if self._seedhub_use_proxy else None,
            timeout=self._seedhub_timeout,
            max_candidates=self._seedhub_max_candidates,
        ) if self._seedhub_enabled else None
        self._fourkmonitor_client = FourKMonitorClient(
            proxy=proxy if self._fourkmonitor_use_proxy else None,
            timeout=self._fourkmonitor_timeout,
            max_candidates=self._fourkmonitor_max_candidates,
            min_interval_seconds=self._fourkmonitor_interval_seconds,
        ) if self._fourkmonitor_enabled else None
        cookies = self._resolve_p115_cookie()
        if cookies:
            self._p115_manager = P115ClientManager(cookies=cookies)
        else:
            self._p115_manager = None
        if self._quark_enabled:
            quark_cookie = self._resolve_quark_cookie()
            if quark_cookie:
                from .clients import QuarkShareClient
                self._quark_client = QuarkShareClient(
                    cookie=quark_cookie,
                    proxy=proxy,
                    timeout=self._quark_timeout,
                    risk_cooldown=self._quark_risk_cooldown,
                )
            else:
                self._quark_client = None
        else:
            self._quark_client = None
        if self._strm_enabled:
            self._strm_client = SmartStrmClient(
                webhook_url=self._smartstrm_webhook_url,
                timeout=self._quark_timeout,
            )
        else:
            self._strm_client = None

    def _init_handlers(self) -> None:
        self._search_handler = SearchHandler(
            self._telegram_client, self._telegram_enabled, self._seedhub_client,
            self._seedhub_enabled, self._seedhub_channel,
            self._fourkmonitor_client, self._fourkmonitor_enabled,
        )
        self._subscribe_handler = SubscribeHandler()
        self._sync_handler = SyncHandler(
            p115_manager=self._p115_manager,
            search_handler=self._search_handler,
            subscribe_handler=self._subscribe_handler,
            chain=self.chain,
            save_path=self._save_path,
            movie_save_path=self._movie_save_path,
            max_transfer_per_sync=self._max_transfer_per_sync,
            batch_size=self._batch_size,
            skip_other_season_dirs=self._skip_other_season_dirs,
            notify=self._notify,
            post_message_func=self.post_message,
            get_data_func=self.get_data,
            save_data_func=self.save_data,
            dry_run=self._dry_run,
        )
        self._sync_handler.configure_offline_download(
            enabled=self._offline_enabled,
            max_per_sync=self._offline_max_per_sync,
            max_wait_hours=self._offline_max_wait_hours,
        )
        self._quark_handler = QuarkSyncHandler(
            quark_client=self._quark_client,
            search_handler=self._search_handler,
            subscribe_handler=self._subscribe_handler,
            chain=self.chain,
            save_path=self._quark_save_path,
            movie_save_path=self._quark_movie_save_path,
            max_transfer_per_sync=self._max_transfer_per_sync,
            batch_size=self._batch_size,
            skip_other_season_dirs=self._skip_other_season_dirs,
            notify=self._notify,
            post_message_func=self.post_message,
            get_data_func=self.get_data,
            save_data_func=self.save_data,
            dry_run=self._dry_run,
            strm_enabled=self._strm_enabled,
            strm_client=self._strm_client,
            strm_task=self._smartstrm_task,
            strm_xlist_path_fix=self._smartstrm_xlist_path_fix,
            strm_max_attempts=self._strm_retry_max,
            status_callback=self._record_quark_status,
        )

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _start_run_status(self, subscribe_count: int = 0) -> None:
        if self._run_status:
            self._run_status["subscribe_count"] = subscribe_count
            return
        self._run_status = {
            "started_at": self._now(), "finished_at": "", "result": "运行中",
            "subscribe_count": subscribe_count, "transferred_115": 0, "transferred_quark": 0,
            "telegram_raw_candidates": 0, "telegram_duplicates_merged": 0,
            "quark_candidates": 0, "quark_failures": {}, "strm": {"triggered": 0, "failed": 0, "stalled": 0},
            "offline": {"pending": 0, "completed": 0, "expired": 0},
            "media": {}, "last_error": "",
        }

    def _record_quark_status(self, event: str, **data: Any) -> None:
        """记录当前同步轮的脱敏夸克/SmartStrm 状态。"""
        if not self._run_status:
            return
        if event == "quark_candidates":
            self._run_status["quark_candidates"] += int(data.get("count") or 0)
        elif event == "quark_failure":
            category = str(data.get("category") or "api_error")
            failures = self._run_status["quark_failures"]
            failures[category] = int(failures.get(category) or 0) + 1
        elif event == "quark_transferred":
            title = str(data.get("title") or "未知媒体")
            season = data.get("season")
            key = f"{title} S{int(season):02d}" if season else title
            self._run_status["media"][key] = str(data.get("stage") or "夸克转存成功，已触发 SmartStrm")
        elif event == "strm_trigger":
            key = "triggered" if data.get("success") else "failed"
            self._run_status["strm"][key] += 1
        elif event == "strm_retry":
            for key in ("triggered", "failed", "stalled"):
                self._run_status["strm"][key] += int(data.get(key) or 0)

    def _finish_run_status(self, *, result: str, transferred_115: int = 0, transferred_quark: int = 0, error: str = "") -> None:
        if not self._run_status:
            return
        telegram_stats = self._telegram_client.get_search_stats() if self._telegram_client else {}
        self._run_status.update({
            "finished_at": self._now(), "result": result,
            "offline": self._sync_handler.offline_stats() if self._sync_handler else {"pending": 0, "completed": 0, "expired": 0},
            "transferred_115": transferred_115, "transferred_quark": transferred_quark,
            "telegram_raw_candidates": int(telegram_stats.get("raw_candidates") or 0),
            "telegram_duplicates_merged": int(telegram_stats.get("duplicates_merged") or 0),
            "last_error": str(error or "")[:160],
        })
        self.save_data("run_status", self._run_status)

    def _config_snapshot(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled, "notify": self._notify, "onlyonce": self._onlyonce, "cron": self._cron,
            "cookie_source": self._cookie_source, "cookies": self._cookies, "save_path": self._save_path, "movie_save_path": self._movie_save_path,
            "telegram_enabled": self._telegram_enabled, "telegram_channels": self._telegram_channels,
            "telegram_timeout": self._telegram_timeout, "telegram_max_results": self._telegram_max_results,
            "telegram_max_telegraph_pages": self._telegram_max_telegraph_pages,
            "max_transfer_per_sync": self._max_transfer_per_sync, "batch_size": self._batch_size,
            "skip_other_season_dirs": self._skip_other_season_dirs, "dry_run": self._dry_run,
            "quark_enabled": self._quark_enabled, "quark_timeout": self._quark_timeout,
            "quark_risk_cooldown": self._quark_risk_cooldown,
            "quark_save_path": self._quark_save_path, "quark_movie_save_path": self._quark_movie_save_path,
            "strm_enabled": self._strm_enabled, "smartstrm_webhook_url": self._smartstrm_webhook_url,
            "smartstrm_task": self._smartstrm_task, "smartstrm_xlist_path_fix": self._smartstrm_xlist_path_fix,
            "strm_retry_max": self._strm_retry_max,
            "offline_enabled": self._offline_enabled, "offline_max_per_sync": self._offline_max_per_sync,
            "offline_max_wait_hours": self._offline_max_wait_hours,
            "seedhub_enabled": self._seedhub_enabled, "seedhub_channel": self._seedhub_channel,
            "seedhub_timeout": self._seedhub_timeout, "seedhub_max_candidates": self._seedhub_max_candidates,
            "seedhub_use_proxy": self._seedhub_use_proxy,
            "fourkmonitor_enabled": self._fourkmonitor_enabled,
            "fourkmonitor_timeout": self._fourkmonitor_timeout,
            "fourkmonitor_max_candidates": self._fourkmonitor_max_candidates,
            "fourkmonitor_interval_seconds": self._fourkmonitor_interval_seconds,
            "fourkmonitor_use_proxy": self._fourkmonitor_use_proxy,
        }

    def stop_service(self) -> None:
        """停止插件自建的一次性调度器，避免重载后残留任务。"""
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception as exc:
                logger.warning(f"停止 115 TG订阅追更调度器失败：{exc}")
            finally:
                self._scheduler = None

    def get_state(self) -> bool:
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return UIConfig.get_form()

    def get_page(self) -> List[dict]:
        """提供插件详情页操作入口、最近转存记录和运行概览。"""
        return UIConfig.get_page(
            self.get_data("history") or [], self.get_data("run_status") or {},
            self.get_data("subscribe_progress_audit") or {},
        )

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/preview_subscribe_progress",
                "endpoint": self.api_preview_subscribe_progress,
                "methods": ["POST"],
                "summary": "只读预览 Emby 媒体库与 MoviePilot 订阅进度差异",
            },
            {
                "path": "/apply_subscribe_progress",
                "endpoint": self.api_apply_subscribe_progress,
                "methods": ["POST"],
                "summary": "按 Emby 已入库事实修复 MoviePilot 订阅进度",
            },
            {
                "path": "/run_once",
                "endpoint": self.api_run_once,
                "methods": ["POST"],
                "summary": "立即执行一次 115 TG订阅追更",
            },
            {
                "path": "/verify_quark",
                "endpoint": self.api_verify_quark,
                "methods": ["POST"],
                "summary": "验证 QuarkDisk 夸克账号连通性",
            },
            {
                "path": "/test_smartstrm",
                "endpoint": self.api_test_smartstrm,
                "methods": ["POST"],
                "summary": "测试 SmartStrm Webhook 连通性",
            },
            {
                "path": "/clear_plugin_log",
                "endpoint": self.api_clear_plugin_log,
                "methods": ["POST"],
                "summary": "清理 115 TG订阅追更插件日志",
            },
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        if self._cron and self._cron_interval_ge_min_hours(self._cron):
            trigger: Any = CronTrigger.from_crontab(self._cron)
        else:
            trigger = "interval"
        return [{
            "id": "P115TGSub",
            "name": "115 TG订阅追更服务",
            "trigger": trigger,
            "func": self.sync_subscribes,
            "kwargs": {} if trigger != "interval" else {"hours": self._MIN_INTERVAL_HOURS},
        }]

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [{
            "cmd": "/p115_tg_sub_action", "event": EventType.PluginAction,
            "desc": "115 TG订阅追更", "category": "订阅", "data": {"action": "p115_tg_sub_action"},
        }]

    @staticmethod
    def _sanitize_history(history: Any) -> List[Dict[str, Any]]:
        """移除旧版本历史中遗留的完整分享 URL；保留去重所需字段。"""
        output: List[Dict[str, Any]] = []
        for raw in history or []:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item.pop("share_url", None)
            item.pop("url", None)
            output.append(item)
        return output

    def _do_sync(self) -> bool:
        self._start_run_status()
        if self._telegram_client:
            logger.info(
                f"本轮 Telegram 搜索将使用 {len(self._telegram_client.channels)} 个频道："
                f"{', '.join(self._telegram_client.channels)}"
            )
        if self._seedhub_client:
            self._seedhub_client.begin_run()
        if self._fourkmonitor_client:
            self._fourkmonitor_client.begin_run()
        if self._p115_manager:
            self._p115_manager.begin_run()
        if self._sync_handler:
            self._sync_handler.begin_run()
        if self._quark_handler:
            self._quark_handler.begin_run()
        # SmartStrm 队列独立于本轮搜索/网盘状态；测试模式不触发任何后处理。
        if self._quark_handler and not self._dry_run:
            try:
                self._quark_handler.process_strm_retry_queue()
            except Exception as exc:
                logger.warning(f"SmartStrm 待重试队列处理异常：{exc}")

        telegram_ready = bool(self._telegram_enabled and self._telegram_client and self._telegram_client.channels)
        fourkmonitor_ready = bool(self._fourkmonitor_enabled and self._fourkmonitor_client)
        if not telegram_ready and not fourkmonitor_ready:
            logger.error("Telegram 公开频道与 4K Monitor 均未正确配置，无法执行订阅追更")
            self._finish_run_status(result="失败", error="未配置 Telegram 公开频道或 4K Monitor")
            return False
        p115_ready = bool(self._p115_manager)
        if p115_ready:
            try:
                p115_ready = bool(self._p115_manager.check_login())
            except Exception as exc:
                logger.warning(f"115 登录验证异常：{exc}")
                p115_ready = False
        if not p115_ready:
            logger.warning("115 客户端不可用，本轮跳过 115 并直接尝试夸克兜底")

        quark_ready = bool(self._quark_enabled and self._quark_handler and self._quark_client)
        if quark_ready:
            try:
                quark_ready = bool(self._quark_client.check_login())
            except Exception as exc:
                logger.warning(f"夸克登录验证异常：{exc}")
                quark_ready = False
        if not p115_ready and not quark_ready:
            logger.error("115 与夸克客户端均不可用，无法执行订阅追更")
            self._finish_run_status(result="失败", error="115 与夸克客户端均不可用")
            return False

        with SessionFactory() as db:
            subscribes = SubscribeOper(db=db).list("N,R") or []
        if not subscribes:
            logger.warning("当前没有待处理的 MoviePilot 订阅")
            self._start_run_status(0)
            self._finish_run_status(result="完成")
            return True

        logger.info(f"开始处理 {len(subscribes)} 个 MoviePilot 待处理订阅")
        self._start_run_status(len(subscribes))

        try:
            self._telegram_client.reset_api_call_count()
            if self._p115_manager:
                self._p115_manager.reset_api_call_count()
            if self._quark_client:
                self._quark_client.reset_api_call_count()
        except Exception:
            pass

        # SmartStrm 待重试队列已在任务入口处理；此处仅开始本轮搜索转存。
        history = self._sanitize_history(self.get_data("history") or [])
        transfer_details_115: List[Dict[str, Any]] = []
        transfer_details_quark: List[Dict[str, Any]] = []
        transferred_total = 0
        transferred_115 = 0
        transferred_quark = 0
        for subscribe in subscribes:
            before_115 = transferred_total
            if p115_ready and subscribe.type == MediaType.MOVIE.value:
                transferred_total = self._sync_handler.process_movie_subscribe(
                    subscribe, history, transfer_details_115, transferred_total
                )
            elif p115_ready and subscribe.type == MediaType.TV.value:
                transferred_total = self._sync_handler.process_tv_subscribe(
                    subscribe, history, transfer_details_115, transferred_total, set()
                )
            transferred_115 += transferred_total - before_115

            # 夸克兜底：115 未补齐且双盘合计未达本轮上限时才尝试。
            if (
                quark_ready
                and transferred_total < self._max_transfer_per_sync
                and not self._quark_client.transfer_risk_blocked
                and (
                    subscribe.type == MediaType.TV.value
                    or not self._sync_handler.offline_pending(subscribe.id, media_type="电影")
                )
            ):
                before_quark = transferred_total
                if subscribe.type == MediaType.MOVIE.value:
                    transferred_total = self._quark_handler.process_movie_subscribe(
                        subscribe, history, transfer_details_quark, transferred_total
                    )
                elif subscribe.type == MediaType.TV.value:
                    transferred_total = self._quark_handler.process_tv_subscribe(
                        subscribe, history, transfer_details_quark, transferred_total,
                        self._sync_handler.offline_pending(
                            subscribe.id, season=getattr(subscribe, "season", 0) or 0, media_type="电视剧"
                        ),
                    )
                transferred_quark += transferred_total - before_quark
            if (
                quark_ready
                and subscribe.type != MediaType.TV.value
                and self._sync_handler.offline_pending(subscribe.id, media_type="电影")
            ):
                logger.info(f"{subscribe.name} 存在 115 离线下载中的媒体，夸克兜底暂不处理")
            if transferred_total >= self._max_transfer_per_sync:
                break

        self.save_data("history", history)
        logger.info(
            f"115 TG订阅追更完成：115 转存 {transferred_115} 个，夸克转存 {transferred_quark} 个"
        )
        self._finish_run_status(
            result="完成" if transferred_total else "完成（未发现可转存资源）",
            transferred_115=transferred_115, transferred_quark=transferred_quark,
        )
        if self._notify:
            if transferred_115:
                self._sync_handler.send_transfer_notification(transfer_details_115, transferred_115)
            if transferred_quark:
                self._quark_handler.send_transfer_notification(transfer_details_quark, transferred_quark)
            if not transferred_total:
                self.post_message(mtype=NotificationType.Plugin, title="【115 TG订阅追更】执行完成", text="本次未发现可转存的匹配资源。")
        return True

    def _run_sync_exclusive(self) -> bool:
        """串行执行同步，避免定时、远程命令和页面操作并发转存。"""
        with run_state_lock:
            if self._sync_running:
                logger.warning("115 TG订阅追更任务正在执行，忽略重复触发")
                return False
            if self._progress_repair_running:
                logger.warning("订阅进度核验/修复正在执行，本次订阅追更不启动")
                return False
            self._sync_running = True
        try:
            with lock:
                return self._do_sync()
        except Exception as exc:
            logger.error(f"115 TG订阅追更任务异常：{exc}")
            return False
        finally:
            with run_state_lock:
                self._sync_running = False

    def sync_subscribes(self) -> bool:
        return self._run_sync_exclusive()

    def _run_queued_once(self) -> None:
        with run_state_lock:
            self._run_requested = False
        self._run_sync_exclusive()

    def _run_subscribe_progress_audit(self, apply: bool) -> None:
        """订阅进度核验后台任务：只读取 Emby 与订阅表，绝不进入任何搜索/网盘链路。"""
        action = "修复" if apply else "预览"
        with run_state_lock:
            if self._sync_running:
                logger.warning(f"订阅进度{action}任务被跳过：订阅追更任务正在运行")
                self._progress_repair_running = False
                return
            # API 入口已预占标记；直接执行，避免两个请求并发启动。
            self._progress_repair_running = True
        try:
            with lock:
                with SessionFactory() as db:
                    # 不限 N/R：修复历史双网盘流程留下的其他当前订阅状态，但不读取订阅历史表。
                    subscribes = SubscribeOper(db=db).list() or []
                report = self._sync_handler.audit_subscribe_progress(subscribes, apply=apply)
            report.update({"action": action, "finished_at": self._now()})
            self.save_data("subscribe_progress_audit", report)
            if report["differences"]:
                logger.info(
                    f"订阅进度{action}完成：扫描 {report['scanned']} 条电视剧订阅，"
                    f"发现 {len(report['differences'])} 条差异，已更新 {report['updated']} 条"
                )
            else:
                logger.info(f"订阅进度{action}完成：扫描 {report['scanned']} 条电视剧订阅，未发现差异")
        except Exception as exc:
            logger.error(f"订阅进度{action}任务异常：{type(exc).__name__}")
            self.save_data("subscribe_progress_audit", {
                "action": action, "finished_at": self._now(), "error": type(exc).__name__,
                "scanned": 0, "differences": [], "updated": 0, "issues": [],
            })
        finally:
            with run_state_lock:
                self._progress_repair_running = False

    def _start_subscribe_progress_audit(self, apikey: str, apply: bool) -> Dict[str, Any]:
        if apikey != settings.API_TOKEN:
            return {"success": False, "message": "API密钥错误"}
        with run_state_lock:
            if self._sync_running or self._progress_repair_running:
                return {"success": False, "message": "订阅追更或进度核验任务正在执行，请稍后重试"}
            self._progress_repair_running = True
        action = "修复" if apply else "只读预览"
        Thread(
            target=self._run_subscribe_progress_audit, args=(apply,),
            name="P115TGSubProgressRepair", daemon=True,
        ).start()
        return {"success": True, "message": f"订阅进度{action}已开始；不会搜索、转存、提交离线任务或触发 SmartStrm，请稍后刷新本页查看结果"}

    def api_preview_subscribe_progress(self, apikey: str) -> Dict[str, Any]:
        """只读预览：不写订阅、不访问 Telegram/115/夸克/SeedHub。"""
        return self._start_subscribe_progress_audit(apikey, apply=False)

    def api_apply_subscribe_progress(self, apikey: str) -> Dict[str, Any]:
        """显式确认后的写入：仅按当前 Emby 已确认集数补充订阅进度。"""
        return self._start_subscribe_progress_audit(apikey, apply=True)

    def api_run_once(self, apikey: str) -> Dict[str, Any]:
        """页面按钮入口：异步排队，避免 HTTP 请求等待完整同步任务。"""
        if apikey != settings.API_TOKEN:
            return {"success": False, "message": "API密钥错误"}
        with run_state_lock:
            if self._sync_running or self._run_requested:
                return {"success": False, "message": "任务正在执行或已排队，请稍后查看插件日志"}
            self._run_requested = True
        Thread(target=self._run_queued_once, name="P115TGSubRunOnce", daemon=True).start()
        return {"success": True, "message": "任务已开始执行，请查看插件日志"}

    def api_verify_quark(self, apikey: str) -> Dict[str, Any]:
        """只读验证 QuarkDisk 复用凭据，不读取分享、不创建目录、不保存文件。"""
        if apikey != settings.API_TOKEN:
            return {"success": False, "message": "API密钥错误"}
        quark_client = self._quark_client
        if not quark_client:
            try:
                quark_cookie = self._resolve_quark_cookie()
                if not quark_cookie:
                    return {"success": False, "message": "未在夸克网盘存储（QuarkDisk）中找到有效 Cookie"}
                quark_client = QuarkShareClient(
                    cookie=quark_cookie,
                    proxy=settings.PROXY,
                    timeout=self._quark_timeout,
                    risk_cooldown=self._quark_risk_cooldown,
                )
            except Exception as exc:
                return {"success": False, "message": f"夸克客户端初始化失败：{exc}"}
        if quark_client.check_login():
            return {"success": True, "message": "夸克连通性验证成功：已复用 QuarkDisk Cookie"}
        return {"success": False, "message": "夸克连通性验证失败，请检查 QuarkDisk Cookie"}

    def api_test_smartstrm(self, apikey: str) -> Dict[str, Any]:
        """只读测试 SmartStrm Webhook 连通性，不触发任何 STRM 任务。"""
        if apikey != settings.API_TOKEN:
            return {"success": False, "message": "API密钥错误"}
        if not self._strm_enabled:
            return {"success": False, "message": "请先启用“SmartStrm 增量 STRM 后处理”并保存配置"}
        if not self._strm_client or not self._strm_client.configured:
            return {"success": False, "message": "SmartStrm Webhook 未配置"}
        return self._strm_client.check_connection()

    def api_clear_plugin_log(self, apikey: str) -> Dict[str, Any]:
        """仅清理本插件当前及滚动日志，不影响 MoviePilot 主日志或其他插件。"""
        if apikey != settings.API_TOKEN:
            return {"success": False, "message": "API密钥错误"}
        log_dir = settings.LOG_PATH / "plugins"
        try:
            removed = 0
            current_log = log_dir / "p115tgsub.log"
            if current_log.is_file():
                # 当前日志可能仍由 MoviePilot 的异步处理器持有；截断而不删除，避免后续日志写入已删除的文件描述符。
                current_log.write_text("", encoding="utf-8")
                removed += 1
            for path in log_dir.glob("p115tgsub.log.*"):
                if path.is_file():
                    path.unlink()
                    removed += 1
            return {"success": True, "message": f"已清理 {removed} 个插件日志文件"}
        except OSError as exc:
            logger.error(f"清理 115 TG订阅追更插件日志失败：{exc}")
            return {"success": False, "message": f"清理失败：{exc}"}

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event):
        if event and event.event_data and event.event_data.get("action") == "p115_tg_sub_action":
            self.sync_subscribes()
