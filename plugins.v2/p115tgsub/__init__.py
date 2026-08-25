"""115 Telegram 公开频道订阅追更插件。"""
import datetime
from pathlib import Path
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

from .clients import P115ClientManager, TelegramWebClient
from .handlers import SearchHandler, SubscribeHandler, SyncHandler
from .ui import UIConfig

lock = Lock()
run_state_lock = Lock()


class P115TGSub(_PluginBase):
    """从 Telegram 公开频道搜索 115 分享链接的 MoviePilot 订阅追更插件。"""

    plugin_name = "115 TG订阅追更"
    plugin_desc = "读取 MoviePilot 订阅，直接搜索 Telegram 公开频道中的 115 分享资源并补齐缺失内容。"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/cloud.png"
    plugin_version = "1.1.2"
    plugin_author = "lawzizhuang"
    author_url = "https://github.com/lawzizhuang/MoviePilot-Plugins"
    plugin_config_prefix = "p115tgsub_"
    plugin_order = 21
    auth_level = 1

    _enabled = False
    _notify = True
    _onlyonce = False
    _cron = "30 */8 * * *"
    _cookie_source = "p115disk"
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
    _dry_run = True
    _sync_running = False
    _run_requested = False

    _scheduler: Optional[BackgroundScheduler] = None
    _telegram_client: Optional[TelegramWebClient] = None
    _p115_manager: Optional[P115ClientManager] = None
    _search_handler: Optional[SearchHandler] = None
    _subscribe_handler: Optional[SubscribeHandler] = None
    _sync_handler: Optional[SyncHandler] = None

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

        self._cookie_source = str(config.get("cookie_source", "p115disk") or "p115disk").strip().lower()
        if self._cookie_source not in {"p115disk", "local"}:
            self._cookie_source = "p115disk"
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
        """按配置获取 115 Cookie；默认只复用 P115Disk 的持久化配置。"""
        if self._cookie_source == "local":
            return self._cookies

        p115disk_config = self.get_config("P115Disk") or {}
        if not isinstance(p115disk_config, dict):
            logger.error("读取 115网盘储存（P115Disk）配置失败")
            return ""
        cookie = str(p115disk_config.get("cookie", "") or "").strip()
        if not cookie:
            logger.error("未在 115网盘储存（P115Disk）中找到有效 Cookie；请先完成其配置，或将凭据来源切换为“本插件独立 Cookie”")
            return ""
        logger.info("115 TG订阅追更已复用 115网盘储存（P115Disk）的 Cookie 配置")
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
        if self._telegram_enabled and not self._telegram_client.channels:
            logger.warning("Telegram 搜索已启用但未配置有效公开频道")
        cookies = self._resolve_p115_cookie()
        if cookies:
            self._p115_manager = P115ClientManager(cookies=cookies)
        else:
            self._p115_manager = None

    def _init_handlers(self) -> None:
        self._search_handler = SearchHandler(self._telegram_client, self._telegram_enabled)
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

    def _config_snapshot(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled, "notify": self._notify, "onlyonce": self._onlyonce, "cron": self._cron,
            "cookie_source": self._cookie_source, "cookies": self._cookies, "save_path": self._save_path, "movie_save_path": self._movie_save_path,
            "telegram_enabled": self._telegram_enabled, "telegram_channels": self._telegram_channels,
            "telegram_timeout": self._telegram_timeout, "telegram_max_results": self._telegram_max_results,
            "telegram_max_telegraph_pages": self._telegram_max_telegraph_pages,
            "max_transfer_per_sync": self._max_transfer_per_sync, "batch_size": self._batch_size,
            "skip_other_season_dirs": self._skip_other_season_dirs, "dry_run": self._dry_run,
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
        """提供插件详情页操作入口与最近转存记录。"""
        return UIConfig.get_page(self.get_data("history") or [])

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/run_once",
                "endpoint": self.api_run_once,
                "methods": ["POST"],
                "summary": "立即执行一次 115 TG订阅追更",
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

    def _do_sync(self) -> bool:
        if not self._telegram_enabled or not self._telegram_client or not self._telegram_client.channels:
            logger.error("Telegram 公开频道搜索未正确配置，无法执行")
            return False
        if not self._p115_manager:
            logger.error("115 客户端未初始化，请检查 Cookie 配置")
            return False
        if not self._p115_manager.check_login():
            logger.error("115 登录失败，Cookie 可能已过期")
            return False

        with SessionFactory() as db:
            subscribes = SubscribeOper(db=db).list("N,R") or []
        if not subscribes:
            logger.warning("当前没有待处理的 MoviePilot 订阅")
            return True

        logger.info(f"开始处理 {len(subscribes)} 个 MoviePilot 待处理订阅")

        try:
            self._telegram_client.reset_api_call_count()
            self._p115_manager.reset_api_call_count()
        except Exception:
            pass

        history = self.get_data("history") or []
        transfer_details: List[Dict[str, Any]] = []
        transferred_count = 0
        for subscribe in subscribes:
            if subscribe.type == MediaType.MOVIE.value:
                transferred_count = self._sync_handler.process_movie_subscribe(subscribe, history, transfer_details, transferred_count)
            elif subscribe.type == MediaType.TV.value:
                transferred_count = self._sync_handler.process_tv_subscribe(subscribe, history, transfer_details, transferred_count, set())
            if transferred_count >= self._max_transfer_per_sync:
                break

        self.save_data("history", history)
        logger.info(f"115 TG订阅追更完成，共转存 {transferred_count} 个文件")
        if self._notify:
            if transferred_count:
                self._sync_handler.send_transfer_notification(transfer_details, transferred_count)
            else:
                self.post_message(mtype=NotificationType.Plugin, title="【115 TG订阅追更】执行完成", text="本次未发现可转存的匹配资源。")
        return True

    def _run_sync_exclusive(self) -> bool:
        """串行执行同步，避免定时、远程命令和页面操作并发转存。"""
        with run_state_lock:
            if self._sync_running:
                logger.warning("115 TG订阅追更任务正在执行，忽略重复触发")
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
