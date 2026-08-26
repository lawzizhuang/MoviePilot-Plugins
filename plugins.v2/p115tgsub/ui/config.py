"""115 TG 订阅追更插件配置与操作页面。"""
from typing import Any, Dict, List, Tuple

from app.core.config import settings


class UIConfig:
    @staticmethod
    def get_form() -> Tuple[List[dict], Dict[str, Any]]:
        form = [{
            "component": "VForm",
            "content": [
                {
                    "component": "VRow",
                    "content": [{
                        "component": "VCol", "props": {"cols": 12}, "content": [{
                            "component": "VAlert", "props": {
                                "type": "info", "variant": "tonal",
                                "text": "v1.1：自动处理全部 MoviePilot 待处理订阅，直接搜索已配置的 Telegram 公开频道，提取并转存 115 分享资源。插件不依赖 CloudSaver；仅支持公开频道与 115 网盘。"
                            }
                        }]
                    }]
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "发送通知"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "onlyonce", "label": "保存后立即运行一次"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 5}, "content": [{"component": "VCronField", "props": {
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
                                "text": "默认复用“115网盘STRM助手（P115StrmHelper）”已保存的 Cookie，与现有 STRM/转存链路保持一致；无需重复录入。也可按需改为复用115网盘储存（P115Disk），或使用本插件独立 Cookie。Cookie、分享密码不会写入通知。首次请使用测试订阅与测试目录验证。"
                            }
                        }]
                    }]
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSelect", "props": {
                            "model": "cookie_source", "label": "115 凭据来源", "items": [
                                {"title": "复用 115网盘STRM助手（推荐）", "value": "p115strmhelper"},
                                {"title": "复用 115网盘储存", "value": "p115disk"},
                                {"title": "本插件独立 Cookie", "value": "local"},
                            ],
                            "hint": "默认读取 P115StrmHelper 配置中的 cookies；P115Disk 使用 cookie 字段。两种复用模式均不复制、不展示凭据。", "persistent-hint": True,
                        }}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "save_path", "label": "电视剧转存目录", "placeholder": "/我的接收/MoviePilot-TG/TV"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "movie_save_path", "label": "电影转存目录", "placeholder": "/我的接收/MoviePilot-TG/Movie"}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextField", "props": {
                            "model": "cookies", "label": "115 Cookie（仅独立模式使用）", "type": "password",
                            "placeholder": "UID=...; CID=...; SEID=...", "hint": "凭据来源为任一“复用”模式时，此项会被忽略。", "persistent-hint": True,
                        }}]},
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
                            "component": "VAlert", "props": {
                                "type": "info", "variant": "tonal",
                                "text": "订阅范围：自动读取并处理全部 MoviePilot 待处理订阅（状态 N、R），无需在本插件重复勾选。首次请保持测试模式开启，并使用独立测试转存目录。"
                            }
                        }]
                    }]
                },
            ],
        }]
        defaults = {
            "enabled": False, "notify": True, "onlyonce": False, "cron": "30 */8 * * *",
            "cookie_source": "p115strmhelper", "cookies": "", "save_path": "/我的接收/MoviePilot-TG/TV", "movie_save_path": "/我的接收/MoviePilot-TG/Movie",
            "telegram_enabled": True, "telegram_channels": "QukanMovie\nlsp115\nvip115hot",
            "telegram_timeout": 20, "telegram_max_results": 10, "telegram_max_telegraph_pages": 3,
            "max_transfer_per_sync": 20, "batch_size": 10, "skip_other_season_dirs": True, "dry_run": True,
        }
        return form, defaults

    @staticmethod
    def get_page(history: List[Dict[str, Any]]) -> List[dict]:
        """插件详情页：提供无需保存配置的即时操作入口。"""
        history = history or []
        recent_count = len(history)
        return [{
            "component": "VCard",
            "props": {"class": "mb-4"},
            "content": [{
                "component": "VCardText",
                "content": [
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info", "variant": "tonal",
                            "text": f"115 TG订阅追更 · 已记录 {recent_count} 条转存结果。立即运行会处理全部 MoviePilot 待处理订阅；请先确认测试模式与转存目录。",
                        },
                    },
                    {
                        "component": "VRow",
                        "props": {"class": "mt-2"},
                        "content": [
                            {
                                "component": "VCol", "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VBtn",
                                    "props": {"color": "primary", "variant": "outlined", "prepend-icon": "mdi-play-circle-outline"},
                                    "text": "立即运行一次",
                                    "events": {"click": {"api": f"/plugin/P115TGSub/run_once?apikey={settings.API_TOKEN}", "method": "post"}},
                                }],
                            },
                            {
                                "component": "VCol", "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VBtn",
                                    "props": {"color": "error", "variant": "outlined", "prepend-icon": "mdi-delete-sweep"},
                                    "text": "清理插件日志",
                                    "events": {"click": {"api": f"/plugin/P115TGSub/clear_plugin_log?apikey={settings.API_TOKEN}", "method": "post"}},
                                }],
                            },
                        ],
                    },
                ],
            }],
        }]
