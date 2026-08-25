"""115 TG 订阅追更插件配置页面。"""
from typing import Any, Dict, List, Tuple

from app.db.subscribe_oper import SubscribeOper
from app.db import SessionFactory
from app.log import logger
from app.schemas.types import MediaType


class UIConfig:
    @staticmethod
    def get_subscribe_options() -> List[Dict[str, Any]]:
        try:
            with SessionFactory() as db:
                subscribes = SubscribeOper(db=db).list("N,R")
            options = []
            for item in subscribes or []:
                kind = "[剧]" if item.type == MediaType.TV.value else "[影]"
                if item.type == MediaType.TV.value:
                    label = f"{kind} {item.name} ({item.year or ''}) S{item.season or 1}".strip()
                else:
                    label = f"{kind} {item.name} ({item.year or ''})".strip()
                options.append({"title": label, "value": item.id})
            return options
        except Exception as exc:
            logger.warning(f"获取订阅列表失败：{exc}")
            return []

    @staticmethod
    def get_form() -> Tuple[List[dict], Dict[str, Any]]:
        subscribe_options = UIConfig.get_subscribe_options()
        form = [{
            "component": "VForm",
            "content": [
                {
                    "component": "VRow",
                    "content": [{
                        "component": "VCol", "props": {"cols": 12}, "content": [{
                            "component": "VAlert", "props": {
                                "type": "info", "variant": "tonal",
                                "text": "v1.0：读取 MoviePilot 订阅，直接搜索已配置的 Telegram 公开频道，提取并转存 115 分享资源。插件不依赖 CloudSaver；仅支持公开频道与 115 网盘。"
                            }
                        }]
                    }]
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "发送通知"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即运行一次"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VCronField", "props": {
                            "model": "cron", "label": "执行周期（Cron）", "placeholder": "30 */8 * * *",
                            "hint": "为降低 Telegram 与 115 风控，最短执行间隔为 8 小时。", "persistent-hint": True
                        }}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [{
                        "component": "VCol", "props": {"cols": 12}, "content": [{
                            "component": "VAlert", "props": {
                                "type": "warning", "variant": "tonal",
                                "text": "仅填写自己的 115 Cookie；Cookie、分享密码不会写入通知。首次请使用测试订阅与测试目录验证。"
                            }
                        }]
                    }]
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "save_path", "label": "电视剧转存目录", "placeholder": "/我的接收/MoviePilot-TG/TV"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "movie_save_path", "label": "电影转存目录", "placeholder": "/我的接收/MoviePilot-TG/Movie"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "cookies", "label": "115 Cookie", "type": "password", "placeholder": "UID=...; CID=...; SEID=..."}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [{
                        "component": "VCol", "props": {"cols": 12}, "content": [{
                            "component": "VAlert", "props": {
                                "type": "info", "variant": "tonal",
                                "text": "Telegram 只访问公开搜索页 https://t.me/s/<频道>?q=<片名>。每行填写一个频道用户名或公开 t.me 链接；lsp115 等“查看资源”频道会按限额访问对应 Telegraph 页面。"
                            }
                        }]
                    }]
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "telegram_enabled", "label": "启用 Telegram 公开频道搜索"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 9}, "content": [{"component": "VTextarea", "props": {
                            "model": "telegram_channels", "label": "Telegram 公开频道（每行一个）", "rows": 3,
                            "placeholder": "QukanMovie\nlsp115\nvip115hot", "hint": "仅支持公开频道；不支持私有频道、邀请链接或 Telegram 登录会话。", "persistent-hint": True
                        }}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "telegram_timeout", "label": "Telegram/Telegraph 超时（秒）", "type": "number", "placeholder": "20"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "telegram_max_results", "label": "每频道最多检查消息数", "type": "number", "placeholder": "10"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "telegram_max_telegraph_pages", "label": "每频道最多 Telegraph 二跳数", "type": "number", "placeholder": "3", "hint": "仅在消息没有直接 115 链接时触发。", "persistent-hint": True}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "dry_run", "label": "测试模式（只验证，不转存）", "hint": "首次使用必须保持开启；关闭后才会实际转存并更新订阅。"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "max_transfer_per_sync", "label": "单次同步最大转存文件数", "type": "number", "placeholder": "20"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "batch_size", "label": "批量转存大小", "type": "number", "placeholder": "10"}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "skip_other_season_dirs", "label": "跳过其他季目录", "hint": "减少 115 API 调用；搜索不到时可关闭。"}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [{
                        "component": "VCol", "props": {"cols": 12}, "content": [{
                            "component": "VSelect", "props": {
                                "model": "include_subscribes", "label": "指定订阅（仅处理勾选项目）",
                                "multiple": True, "chips": True, "clearable": True, "closable-chips": True,
                                "items": subscribe_options, "hint": "v1.0 默认指定模式；建议先只勾选一部测试剧或电影。", "persistent-hint": True
                            }
                        }]
                    }]
                },
            ],
        }]
        defaults = {
            "enabled": False, "notify": True, "onlyonce": False, "cron": "30 */8 * * *",
            "cookies": "", "save_path": "/我的接收/MoviePilot-TG/TV", "movie_save_path": "/我的接收/MoviePilot-TG/Movie",
            "telegram_enabled": True, "telegram_channels": "QukanMovie\nlsp115\nvip115hot",
            "telegram_timeout": 20, "telegram_max_results": 10, "telegram_max_telegraph_pages": 3,
            "max_transfer_per_sync": 20, "batch_size": 10, "skip_other_season_dirs": True, "dry_run": True,
            "include_subscribes": [],
        }
        return form, defaults
