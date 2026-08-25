"""115 Telegram 公开频道订阅追更插件。"""
import datetime
from pathlib import Path
from threading import Lock
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


class P115TGSub(_PluginBase):
    """从 Telegram 公开频道搜索 115 分享链接的 MoviePilot 订阅追更插件。"""

    plugin_name = "115 TG订阅追更"
    plugin_desc = "读取 MoviePilot 订阅，直接搜索 Telegram 公开频道中的 115 分享资源并补齐缺失内容。"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/cloud.png"
    plugin_version = "1.0.1"
    plugin_author = "lawzizhuang"
    author_url = "https://github.com/lawzizhuang/MoviePilot-Plugins"
    plugin_config_prefix = "p115tgsub_"
    plugin_order = 21
    auth_level = 1

    _enabled = False
    _notify = True
    _onlyonce = False
    _cron = "30 */8 * * *"
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
    _include_subscribes: List[int] = []

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
            raw_subscribes = config.get("include_subscribes", []) or []
            self._include_subscribes = [int(item) for item in raw_subscribes if str(item).strip().isdigit()]

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
        if self._cookies:
            self._p115_manager = P115ClientManager(cookies=self._cookies)
        else:
            self._p115_manager = None

    def _init_handlers(self) -> None:
        self._search_handler = SearchHandler(self._telegram_client, self._telegram_enabled)
        self._subscribe_handler = SubscribeHandler(is_excluded_func=self._is_subscribe_excluded)
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
            "cookies": self._cookies, "save_path": self._save_path, "movie_save_path": self._movie_save_path,
            "telegram_enabled": self._telegram_enabled, "telegram_channels": self._telegram_channels,
            "telegram_timeout": self._telegram_timeout, "telegram_max_results": self._telegram_max_results,
            "telegram_max_telegraph_pages": self._telegram_max_telegraph_pages,
            "max_transfer_per_sync": self._max_transfer_per_sync, "batch_size": self._batch_size,
            "skip_other_season_dirs": self._skip_other_season_dirs, "dry_run": self._dry_run,
            "include_subscribes": self._include_subscribes,
        }

    def _is_subscribe_excluded(self, subscribe_id: int) -> bool:
        return not self._include_subscribes or int(subscribe_id) not in set(self._include_subscribes)

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
        """返回空数据页；v1.0 的操作入口集中在配置页。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """v1.0 不对外暴露插件 API。"""
        return []

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
        selected = [item for item in subscribes if not self._is_subscribe_excluded(item.id)]
        if not selected:
            logger.warning("未选择任何订阅；v1.0 指定模式下请至少勾选一项测试订阅")
            return True

        try:
            self._telegram_client.reset_api_call_count()
            self._p115_manager.reset_api_call_count()
        except Exception:
            pass

        history = self.get_data("history") or []
        transfer_details: List[Dict[str, Any]] = []
        transferred_count = 0
        for subscribe in selected:
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

    def sync_subscribes(self) -> None:
        with lock:
            try:
                self._do_sync()
            except Exception as exc:
                logger.error(f"115 TG订阅追更任务异常：{exc}")

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event):
        if event and event.event_data and event.event_data.get("action") == "p115_tg_sub_action":
            self.sync_subscribes()
