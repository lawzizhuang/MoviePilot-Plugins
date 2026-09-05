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
                                "text": "v2.4：115 优先、夸克兜底的双网盘订阅追更。Telegram 公开频道先按订阅标题筛选候选；115 分享、Telegram 正文直链、4K Monitor 匿名免费磁力和 SeedHub 公开磁力均可进入定向 115 离线下载，均无可用资源时才尝试夸克转存；夸克转存成功后由 SmartStrm 在本地增量生成 STRM。"
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
                                "text": "115 离线下载：仅处理 Telegram 公开消息正文直接包含的 ED2K 或磁力链接，并显式保存至上方电视剧/电影转存目录；提交任务不算成功，只有目标目录确认出现媒体文件才更新订阅。"
                            }
                        }]
                    }]
                },
                {
                    "component": "VRow",
                    "content": [{
                        "component": "VCol", "props": {"cols": 12}, "content": [{
                            "component": "VAlert", "props": {
                                "type": "info", "variant": "tonal",
                                "text": "4K Monitor：仅以 MoviePilot 已确认的 TMDB ID 精确查询站内资源，仅接受匿名免费、未锁定候选；不登录、不使用 Cookie、不消耗会员或 credits、不调用解锁接口。电影可处理单资源；电视剧仅处理标题明确匹配当前待补季集的资源。遇到 403/429 本轮立即停止。"
                            }
                        }]
                    }]
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "fourkmonitor_enabled", "label": "启用 4K Monitor 匿名免费磁力", "hint": "每轮按 TMDB ID 自动检查；仅免费未锁定候选，位于 Telegram 直链之后、SeedHub 之前。"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "fourkmonitor_timeout", "label": "4K Monitor 请求超时（秒）", "type": "number", "placeholder": "20"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "fourkmonitor_max_candidates", "label": "单次最多免费候选数", "type": "number", "placeholder": "3"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "fourkmonitor_interval_seconds", "label": "请求最小间隔（秒）", "type": "number", "placeholder": "2"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 12}, "content": [{"component": "VSwitch", "props": {"model": "fourkmonitor_use_proxy", "label": "4K Monitor 使用 MoviePilot HTTP 代理", "hint": "默认关闭并直连；仅在容器直连失败时开启。403/429 或无效响应会停止本轮后续检查。", "persistent-hint": True}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "seedhub_enabled", "label": "启用 SeedHub 公开磁力资源", "hint": "需同时启用上方 115 ED2K / 磁力离线下载；仅在 Telegram、4K Monitor 均无可用候选时尝试。"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "seedhub_channel", "label": "SeedHub Telegram 公开频道", "placeholder": "seedhub_pro"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "seedhub_timeout", "label": "SeedHub 请求超时（秒）", "type": "number", "placeholder": "20"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "seedhub_max_candidates", "label": "单次最多检查磁力候选数", "type": "number", "placeholder": "5"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 12}, "content": [{"component": "VSwitch", "props": {"model": "seedhub_use_proxy", "label": "SeedHub 使用 MoviePilot HTTP 代理", "hint": "默认关闭并直连；仅在容器直连 SeedHub 失败时启用。Telegram 公开搜索仍使用 MoviePilot HTTP 代理。", "persistent-hint": True}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "offline_enabled", "label": "启用 115 ED2K / 磁力离线下载", "hint": "115 分享无可用资源时尝试；默认关闭。"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "offline_max_per_sync", "label": "单次最大新建离线任务数", "type": "number", "placeholder": "5"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "offline_max_wait_hours", "label": "离线任务最长等待（小时）", "type": "number", "placeholder": "24", "hint": "超时后释放夸克兜底。"}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "quark_enabled", "label": "启用夸克资源追更", "hint": "115 无可用候选时兜底转存夸克；仅验证连通性可随时单独使用详情页按钮。"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "quark_timeout", "label": "夸克请求超时（秒）", "type": "number", "placeholder": "30"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "quark_risk_cooldown", "label": "夸克风控冷却（秒）", "type": "number", "placeholder": "1800", "hint": "遇到“频繁/风控/限制/封禁”时停止转存的时长。"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "batch_size", "label": "批量转存大小", "type": "number", "placeholder": "10"}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "quark_save_path", "label": "夸克电视剧转存目录", "placeholder": "/夸克接收/MoviePilot-TG/TV", "hint": "SmartStrm 夸克驱动任务应能扫描到该目录。", "persistent-hint": True}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "quark_movie_save_path", "label": "夸克电影转存目录", "placeholder": "/夸克接收/MoviePilot-TG/Movie"}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [{
                        "component": "VCol", "props": {"cols": 12}, "content": [{
                            "component": "VAlert", "props": {
                                "type": "info", "variant": "tonal",
                                "text": "SmartStrm 后处理：夸克文件转存并二次确认存在后，本插件调用 SmartStrm Webhook 增量生成目标目录的 STRM。Webhook 地址从 SmartStrm“系统设置-Webhook”获取；只读测试不会触发任务。失败仅进入待重试队列，绝不重复网盘转存。"
                            }
                        }]
                    }]
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "strm_enabled", "label": "启用 SmartStrm 增量 STRM 后处理", "hint": "需要夸克转存目录与 SmartStrm 任务可访问。"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "smartstrm_task", "label": "SmartStrm 任务名", "placeholder": "tv,movie", "hint": "逗号分隔多个任务名。", "persistent-hint": True}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "strm_retry_max", "label": "Webhook 最大重试次数", "type": "number", "placeholder": "5"}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "smartstrm_webhook_url", "label": "SmartStrm Webhook 地址", "type": "password", "placeholder": "https://smartstrm:8024/api/webhook/...", "hint": "敏感凭据：仅保存在 MoviePilot 配置中，不写入日志、通知或仓库。", "persistent-hint": True}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "smartstrm_xlist_path_fix", "label": "OpenList 路径映射（可选）", "placeholder": "/quark:/", "hint": "SmartStrm 使用夸克网盘驱动时留空；使用 OpenList 驱动时填“挂载路径:夸克根目录”。"}}]},
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "local_catalog_enabled", "label": "启用本地资源表（115／夸克）"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 9}, "content": [{"component": "VTextField", "props": {"model": "local_catalog_path", "label": "私有 Excel 容器内路径", "placeholder": "/config/resource_catalogs/影巢资源分享备份-20260905.xlsx", "hint": "只读分享明细表，自动排除删除记录；每种网盘最多10个本地候选，真实文件仍须校验。文件变化后自动刷新；首版不导入ED2K或其他网盘。", "persistent-hint": True}}]},
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
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "dry_run", "label": "测试模式（只验证，不转存）", "hint": "首次使用必须保持开启；关闭后才会实际转存并更新订阅、触发 SmartStrm。"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "max_transfer_per_sync", "label": "单次同步最大转存文件数", "type": "number", "placeholder": "20"}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "skip_other_season_dirs", "label": "跳过其他季目录", "hint": "减少网盘 API 调用；搜索不到时可关闭。"}}]},
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

        def settings_card(title: str, icon: str, content: List[dict], color: str = "primary") -> dict:
            return {
                "component": "VCard", "props": {"class": "mb-4", "variant": "outlined"},
                "content": [
                    {"component": "VCardTitle", "props": {"class": "d-flex align-center py-3"}, "content": [
                        {"component": "VIcon", "props": {"color": color, "class": "mr-2"}, "text": icon},
                        {"component": "span", "props": {"class": "text-subtitle-1 font-weight-bold"}, "text": title},
                    ]},
                    {"component": "VCardText", "props": {"class": "pt-0"}, "content": content},
                ],
            }

        def source_panel(title: str, icon: str, description: str, content: List[dict], color: str) -> dict:
            return {
                "component": "VExpansionPanel",
                "content": [
                    {"component": "VExpansionPanelTitle", "content": [
                        {"component": "VIcon", "props": {"color": color, "class": "mr-3"}, "text": icon},
                        {"component": "div", "content": [
                            {"component": "div", "props": {"class": "font-weight-bold"}, "text": title},
                            {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": description},
                        ]},
                    ]},
                    {"component": "VExpansionPanelText", "content": content},
                ],
            }

        blocks = form[0]["content"]
        form = [{
            "component": "VForm",
            "content": [
                settings_card("订阅追更设置", "mdi-tune-variant", [
                    {"component": "div", "props": {"class": "text-body-2 text-medium-emphasis mb-3"}, "text": "按“115 分享 → Telegram 正文离线 → 4K Monitor 免费磁力 → SeedHub 公开磁力 → 夸克兜底”依次补全 MoviePilot 待处理订阅。夸克成功后由 SmartStrm 增量生成 STRM。"},
                    {"component": "div", "content": [
                        {"component": "VChip", "props": {"size": "small", "color": "primary", "variant": "tonal", "class": "mr-2 mb-2"}, "text": "115 优先"},
                        {"component": "VChip", "props": {"size": "small", "color": "secondary", "variant": "tonal", "class": "mr-2 mb-2"}, "text": "夸克兜底"},
                        {"component": "VChip", "props": {"size": "small", "color": "warning", "variant": "tonal", "class": "mr-2 mb-2"}, "text": "首次保持测试模式"},
                        {"component": "VChip", "props": {"size": "small", "color": "info", "variant": "tonal", "class": "mb-2"}, "text": "仅公开资源"},
                    ]},
                ]),
                settings_card("运行与安全", "mdi-shield-play-outline", [
                    blocks[1], blocks[18], blocks[19],
                ], "warning"),
                settings_card("115 凭据与目标目录", "mdi-cloud-key-outline", [
                    blocks[2], blocks[3], blocks[4],
                ], "success"),
                {
                    "component": "VExpansionPanels", "props": {"variant": "accordion", "class": "mb-4"},
                    "content": [
                        source_panel("Telegram 公开频道", "mdi-send-outline", "公开搜索、候选数量与 Telegraph 二跳限制", [blocks[15], blocks[16], blocks[17]], "info"),
                        source_panel("115 离线与公开磁力补充", "mdi-download-network-outline", "Telegram 正文、4K Monitor 与 SeedHub 的受控离线下载", [blocks[5], blocks[9], blocks[6], blocks[7], blocks[8]], "warning"),
                        source_panel("夸克兜底转存", "mdi-cloud-sync-outline", "仅在 115 与公开磁力来源无可用候选时使用", [blocks[10], blocks[11]], "secondary"),
                        source_panel("SmartStrm 后处理", "mdi-file-link-outline", "夸克转存确认后生成本地 STRM，失败仅进入重试队列", [blocks[12], blocks[13], blocks[14]], "teal"),
                    ],
                },
            ],
        }]
        defaults = {
            "enabled": False, "notify": True, "onlyonce": False, "cron": "30 */8 * * *",
            "cookie_source": "p115strmhelper", "cookies": "", "save_path": "/我的接收/MoviePilot-TG/TV", "movie_save_path": "/我的接收/MoviePilot-TG/Movie",
            "local_catalog_enabled": False, "local_catalog_path": "",
            "telegram_enabled": True, "telegram_channels": "QukanMovie\nlsp115\nvip115hot",
            "telegram_timeout": 20, "telegram_max_results": 10, "telegram_max_telegraph_pages": 3,
            "max_transfer_per_sync": 20, "batch_size": 10, "skip_other_season_dirs": True, "dry_run": True,
            "offline_enabled": False, "offline_max_per_sync": 5, "offline_max_wait_hours": 24,
            "seedhub_enabled": False, "seedhub_channel": "seedhub_pro", "seedhub_timeout": 20, "seedhub_max_candidates": 5,
            "seedhub_use_proxy": False,
            "fourkmonitor_enabled": True, "fourkmonitor_timeout": 20, "fourkmonitor_max_candidates": 3,
            "fourkmonitor_interval_seconds": 2, "fourkmonitor_use_proxy": False,
            "quark_enabled": False, "quark_timeout": 30, "quark_risk_cooldown": 1800,
            "quark_save_path": "/夸克接收/MoviePilot-TG/TV", "quark_movie_save_path": "/夸克接收/MoviePilot-TG/Movie",
            "strm_enabled": False, "smartstrm_webhook_url": "", "smartstrm_task": "tv,movie",
            "smartstrm_xlist_path_fix": "", "strm_retry_max": 5,
        }
        return form, defaults

    @staticmethod
    def get_page(
        history: List[Dict[str, Any]], run_status: Dict[str, Any] = None,
        progress_audit: Dict[str, Any] = None,
    ) -> List[dict]:
        """插件详情页：提供即时操作入口与最近一轮脱敏运行概览。"""
        history = history or []
        status = run_status or {}
        progress_audit = progress_audit or {}
        failures = status.get("quark_failures") or {}
        failure_names = {
            "share_expired": "分享失效", "password_invalid": "访问码异常", "access_denied": "访问受限",
            "risk_limited": "风控限制", "network_error": "网络异常", "api_error": "接口异常",
            "empty_share": "空分享", "no_matching_episode": "无目标集", "suppressed_duplicate": "本轮重复抑制",
        }
        failure_text = "、".join(
            f"{failure_names.get(key, key)} {value}" for key, value in failures.items() if value
        ) or "无"
        strm = status.get("strm") or {}
        offline = status.get("offline") or {}
        media = status.get("media") or {}
        media_lines = [f"{title}：{stage}" for title, stage in list(media.items())[-5:]]
        recent_count = len(history)
        run_result = str(status.get("result") or "尚未运行")
        run_color = "success" if run_result == "完成" else "warning" if "未发现" in run_result else "error" if "失败" in run_result else "info"
        run_time = status.get("finished_at") or status.get("started_at") or "暂无运行记录"
        transferred_total = int(status.get("transferred_115") or 0) + int(status.get("transferred_quark") or 0)
        telegram_candidates = int(status.get("telegram_raw_candidates") or 0)
        quark_candidates = int(status.get("quark_candidates") or 0)

        def metric_card(label: str, value: str, icon: str, color: str, hint: str = "") -> dict:
            return {
                "component": "VCol", "props": {"cols": 6, "sm": 3},
                "content": [{
                    "component": "VCard", "props": {"variant": "tonal", "color": color, "class": "h-100"},
                    "content": [{
                        "component": "VCardText", "props": {"class": "pa-3"},
                        "content": [
                            {"component": "VIcon", "props": {"size": "small", "class": "mb-2"}, "text": icon},
                            {"component": "div", "props": {"class": "text-h6 font-weight-bold"}, "text": value},
                            {"component": "div", "props": {"class": "text-caption"}, "text": label},
                            *([{ "component": "div", "props": {"class": "text-caption text-medium-emphasis mt-1"}, "text": hint}] if hint else []),
                        ],
                    }],
                }],
            }

        source_chips = [
            {"component": "VChip", "props": {"size": "small", "variant": "tonal", "color": "info", "class": "mr-2 mb-2"}, "text": f"Telegram {telegram_candidates} 候选"},
            {"component": "VChip", "props": {"size": "small", "variant": "tonal", "color": "secondary", "class": "mr-2 mb-2"}, "text": f"夸克 {quark_candidates} 候选"},
            {"component": "VChip", "props": {"size": "small", "variant": "tonal", "color": "warning", "class": "mr-2 mb-2"}, "text": f"离线待确认 {offline.get('pending', 0)}"},
            {"component": "VChip", "props": {"size": "small", "variant": "tonal", "color": "success", "class": "mr-2 mb-2"}, "text": f"离线已确认 {offline.get('completed', 0)}"},
        ]
        run_dashboard = {
            "component": "VCard", "props": {"class": "mb-3", "variant": "outlined"},
            "content": [
                {"component": "VCardTitle", "props": {"class": "d-flex align-center py-3"}, "content": [
                    {"component": "VIcon", "props": {"color": "primary", "class": "mr-2"}, "text": "mdi-view-dashboard-outline"},
                    {"component": "span", "props": {"class": "text-subtitle-1 font-weight-bold"}, "text": "订阅追更运行概览"},
                    {"component": "VSpacer"},
                    {"component": "VChip", "props": {"color": run_color, "size": "small", "variant": "tonal"}, "text": run_result},
                ]},
                {"component": "VCardText", "props": {"class": "pt-0"}, "content": [
                    {"component": "div", "props": {"class": "text-caption text-medium-emphasis mb-3"}, "text": f"最近完成：{run_time}"},
                    {"component": "VRow", "content": [
                        metric_card("待处理订阅", f"{status.get('subscribe_count', 0)}", "mdi-playlist-check", "primary"),
                        metric_card("本轮转存", f"{transferred_total}", "mdi-cloud-check-outline", "success", f"115 {status.get('transferred_115', 0)} · 夸克 {status.get('transferred_quark', 0)}"),
                        metric_card("离线待确认", f"{offline.get('pending', 0)}", "mdi-cloud-clock-outline", "warning", f"已确认 {offline.get('completed', 0)}"),
                        metric_card("历史记录", f"{recent_count}", "mdi-history", "secondary", f"SmartStrm 成功 {strm.get('triggered', 0)}"),
                    ]},
                    {"component": "VDivider", "props": {"class": "my-3"}},
                    {"component": "VRow", "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 7}, "content": [
                            {"component": "div", "props": {"class": "text-caption text-medium-emphasis mb-2"}, "text": "来源与队列"},
                            {"component": "div", "content": source_chips},
                            {"component": "div", "props": {"class": "text-caption text-medium-emphasis mt-1"}, "text": f"夸克跳过：{failure_text} · SmartStrm 失败 {strm.get('failed', 0)} / 停滞 {strm.get('stalled', 0)}"},
                        ]},
                        {"component": "VCol", "props": {"cols": 12, "md": 5}, "content": [
                            {"component": "div", "props": {"class": "text-caption text-medium-emphasis mb-2"}, "text": "最近媒体状态"},
                            {"component": "div", "props": {"class": "text-body-2"}, "text": "；".join(media_lines) if media_lines else "本轮没有新增转存记录"},
                            *([{ "component": "div", "props": {"class": "text-caption text-error mt-2"}, "text": f"最近异常：{status['last_error']}"}] if status.get("last_error") else []),
                        ]},
                    ]},
                ]},
            ],
        }
        recent_history_rows = []
        for item in reversed(history[-8:]):
            media_label = str(item.get("title") or "未知媒体")
            if item.get("season"):
                media_label += f" · S{int(item.get('season') or 0):02d}"
            if item.get("episode"):
                media_label += f"E{int(item.get('episode') or 0):02d}"
            success = str(item.get("status") or "") == "成功"
            recent_history_rows.append({
                "component": "tr", "content": [
                    {"component": "td", "props": {"class": "py-3"}, "content": [{"component": "div", "props": {"class": "font-weight-medium"}, "text": media_label}, {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": str(item.get("type") or "媒体")}]},
                    {"component": "td", "props": {"class": "py-3 text-no-wrap"}, "content": [{"component": "VChip", "props": {"size": "small", "color": "success" if success else "error", "variant": "tonal"}, "text": "成功" if success else "失败"}]},
                    {"component": "td", "props": {"class": "py-3 text-no-wrap text-caption text-medium-emphasis"}, "text": str(item.get("time") or "—")},
                ],
            })
        history_card = {
            "component": "VCard", "props": {"class": "mb-3", "variant": "outlined"},
            "content": [
                {"component": "VCardTitle", "props": {"class": "d-flex align-center py-3"}, "content": [
                    {"component": "VIcon", "props": {"color": "secondary", "class": "mr-2"}, "text": "mdi-history"},
                    {"component": "span", "props": {"class": "text-subtitle-1 font-weight-bold"}, "text": "最近转存记录"},
                    {"component": "VSpacer"},
                    {"component": "VChip", "props": {"size": "small", "variant": "tonal"}, "text": f"共 {recent_count} 条"},
                ]},
                ({"component": "VTable", "props": {"density": "comfortable", "class": "text-body-2"}, "content": [{"component": "thead", "content": [{"component": "tr", "content": [{"component": "th", "text": "媒体"}, {"component": "th", "text": "结果"}, {"component": "th", "text": "时间"}]}]}, {"component": "tbody", "content": recent_history_rows}]}
                 if recent_history_rows else {"component": "VCardText", "props": {"class": "text-medium-emphasis"}, "text": "暂无转存记录；测试模式不会写入转存历史。"}),
            ],
        }
        audit_differences = progress_audit.get("differences") or []

        def format_episodes(episodes: List[Any]) -> str:
            """将连续集数压缩为 E01–E03，供窄屏表格快速阅读。"""
            values = sorted({int(episode) for episode in episodes or [] if str(episode).isdigit() and int(episode) > 0})
            if not values:
                return "—"
            ranges = []
            start = previous = values[0]
            for episode in values[1:]:
                if episode == previous + 1:
                    previous = episode
                    continue
                ranges.append(f"E{start:02d}" if start == previous else f"E{start:02d}–E{previous:02d}")
                start = previous = episode
            ranges.append(f"E{start:02d}" if start == previous else f"E{start:02d}–E{previous:02d}")
            return "、".join(ranges)

        audit_action = progress_audit.get("action") or "尚未运行"
        audit_color = "warning" if audit_differences else "success" if progress_audit else "info"
        audit_header = {
            "component": "VCard",
            "props": {"class": "mb-3", "variant": "outlined"},
            "content": [
                {
                    "component": "VCardTitle",
                    "props": {"class": "d-flex align-center py-3"},
                    "content": [
                        {"component": "VIcon", "props": {"color": "info", "class": "mr-2"}, "text": "mdi-clipboard-text-search-outline"},
                        {"component": "span", "props": {"class": "text-subtitle-1 font-weight-bold"}, "text": "订阅进度核验"},
                        {"component": "VSpacer"},
                        {"component": "VChip", "props": {"color": audit_color, "size": "small", "variant": "tonal"}, "text": audit_action},
                    ],
                },
                {
                    "component": "VCardText",
                    "props": {"class": "pt-0"},
                    "content": [
                        {
                            "component": "div", "props": {"class": "text-caption text-medium-emphasis mb-3"},
                            "text": f"完成时间：{progress_audit.get('finished_at') or '尚未运行'}",
                        },
                        {
                            "component": "VRow",
                            "content": [
                                {"component": "VCol", "props": {"cols": 4}, "content": [{"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": "已扫描"}, {"component": "div", "props": {"class": "text-h6"}, "text": f"{progress_audit.get('scanned', 0)} 条"}]},
                                {"component": "VCol", "props": {"cols": 4}, "content": [{"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": "发现差异"}, {"component": "div", "props": {"class": "text-h6"}, "text": f"{len(audit_differences)} 条"}]},
                                {"component": "VCol", "props": {"cols": 4}, "content": [{"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": "已修复"}, {"component": "div", "props": {"class": "text-h6"}, "text": f"{progress_audit.get('updated', 0)} 条"}]},
                            ],
                        },
                    ],
                },
            ],
        }
        audit_rows = []
        for item in audit_differences:
            before_note = format_episodes(item.get("note_before"))
            after_note = format_episodes(item.get("note_after"))
            confirmed = format_episodes(item.get("confirmed"))
            audit_rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "props": {"class": "py-3"}, "content": [{"component": "div", "props": {"class": "font-weight-medium"}, "text": item.get("title", "未知媒体")}, {"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": f"第 {item.get('season', 1)} 季"}]},
                    {"component": "td", "props": {"class": "py-3 text-no-wrap"}, "content": [{"component": "VChip", "props": {"color": "success", "size": "small", "variant": "tonal"}, "text": confirmed}]},
                    {"component": "td", "props": {"class": "py-3 text-no-wrap"}, "content": [{"component": "div", "props": {"class": "text-caption text-medium-emphasis"}, "text": before_note}, {"component": "div", "props": {"class": "d-flex align-center mt-1"}, "content": [{"component": "VIcon", "props": {"size": "x-small", "color": "warning", "class": "mr-1"}, "text": "mdi-arrow-right"}, {"component": "span", "props": {"class": "font-weight-medium"}, "text": after_note}]}]},
                    {"component": "td", "props": {"class": "py-3 text-no-wrap"}, "content": [{"component": "VChip", "props": {"color": "warning", "size": "small", "variant": "tonal"}, "text": f"{item.get('lack_before', 0)} → {item.get('lack_after', 0)}"}]},
                ],
            })
        audit_details = (
            {
                "component": "VCard",
                "props": {"class": "mb-3", "variant": "outlined"},
                "content": [
                    {"component": "VCardText", "props": {"class": "pb-0"}, "content": [{"component": "div", "props": {"class": "text-subtitle-2 font-weight-bold"}, "text": "待修复差异"}, {"component": "div", "props": {"class": "text-caption text-medium-emphasis mt-1"}, "text": "绿色为 Emby 已确认入库集数；中间列展示 MoviePilot note 的修复前后变化。"}]},
                    {"component": "VTable", "props": {"density": "comfortable", "class": "text-body-2"}, "content": [{"component": "thead", "content": [{"component": "tr", "content": [{"component": "th", "text": "订阅"}, {"component": "th", "text": "Emby 已入库"}, {"component": "th", "text": "订阅 note"}, {"component": "th", "text": "缺失集数"}]}]}, {"component": "tbody", "content": audit_rows}]},
                ],
            }
            if audit_rows else {
                "component": "VAlert", "props": {"type": "success" if progress_audit else "info", "variant": "tonal", "class": "mb-3", "text": "最近一次核验未发现需要修复的订阅进度。" if progress_audit else "尚未运行订阅进度核验；请先执行只读预览。"},
            }
        )
        run_actions = {
            "component": "VCard", "props": {"class": "mb-3", "variant": "outlined"},
            "content": [
                {"component": "VCardTitle", "props": {"class": "d-flex align-center py-3"}, "content": [
                    {"component": "VIcon", "props": {"color": "primary", "class": "mr-2"}, "text": "mdi-rocket-launch-outline"},
                    {"component": "span", "props": {"class": "text-subtitle-1 font-weight-bold"}, "text": "追更操作"},
                    {"component": "VSpacer"},
                    {"component": "VChip", "props": {"size": "small", "color": "info", "variant": "tonal"}, "text": "115 优先 · 夸克兜底"},
                ]},
                {"component": "VCardText", "props": {"class": "pt-0"}, "content": [
                    {"component": "div", "props": {"class": "text-caption text-medium-emphasis mb-3"}, "text": "立即运行会处理全部 MoviePilot 待处理订阅；测试模式下只验证候选，不转存、不提交离线任务。"},
                    {"component": "VRow", "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 5}, "content": [{"component": "VBtn", "props": {"block": True, "color": "primary", "prepend-icon": "mdi-play-circle-outline"}, "text": "立即运行一次", "events": {"click": {"api": f"/plugin/P115TGSub/run_once?apikey={settings.API_TOKEN}", "method": "post"}}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VBtn", "props": {"block": True, "color": "secondary", "variant": "outlined", "prepend-icon": "mdi-cloud-check-outline"}, "text": "验证夸克", "events": {"click": {"api": f"/plugin/P115TGSub/verify_quark?apikey={settings.API_TOKEN}", "method": "post"}}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [{"component": "VBtn", "props": {"block": True, "color": "teal", "variant": "outlined", "prepend-icon": "mdi-webhook"}, "text": "测试 STRM", "events": {"click": {"api": f"/plugin/P115TGSub/test_smartstrm?apikey={settings.API_TOKEN}", "method": "post"}}}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [{"component": "VBtn", "props": {"block": True, "color": "error", "variant": "text", "prepend-icon": "mdi-delete-sweep"}, "text": "清理日志", "events": {"click": {"api": f"/plugin/P115TGSub/clear_plugin_log?apikey={settings.API_TOKEN}", "method": "post"}}}]},
                    ]},
                ]},
            ],
        }
        progress_actions = {
            "component": "VCard", "props": {"class": "mb-3", "variant": "outlined"},
            "content": [
                {"component": "VCardText", "content": [
                    {"component": "div", "props": {"class": "d-flex align-center mb-2"}, "content": [{"component": "VIcon", "props": {"color": "info", "class": "mr-2"}, "text": "mdi-shield-check-outline"}, {"component": "span", "props": {"class": "text-subtitle-2 font-weight-bold"}, "text": "安全边界"}]},
                    {"component": "div", "props": {"class": "text-body-2 text-medium-emphasis"}, "text": "订阅进度核验只读取 Emby 已入库季集和当前订阅；不会搜索 Telegram / SeedHub，不访问 115 或夸克分享，不创建目录、不转存、不提交离线任务、不触发 SmartStrm 或写下载历史。确认修复只补充已确认集数，绝不回退订阅进度。"},
                ]},
                {"component": "VCardActions", "props": {"class": "px-4 pb-4 pt-0"}, "content": [
                    {"component": "VBtn", "props": {"color": "info", "variant": "outlined", "prepend-icon": "mdi-clipboard-text-search-outline"}, "text": "只读预览差异", "events": {"click": {"api": f"/plugin/P115TGSub/preview_subscribe_progress?apikey={settings.API_TOKEN}", "method": "post"}}},
                    {"component": "VBtn", "props": {"color": "warning", "variant": "outlined", "prepend-icon": "mdi-check-decagram-outline", "class": "ml-2"}, "text": "确认修复进度", "events": {"click": {"api": f"/plugin/P115TGSub/apply_subscribe_progress?apikey={settings.API_TOKEN}", "method": "post"}}},
                ]},
            ],
        }
        return [
            run_dashboard,
            run_actions,
            history_card,
            audit_header,
            audit_details,
            {
                "component": "VAlert",
                "props": {
                    "type": "warning" if progress_audit.get("issues") else "info", "variant": "tonal", "class": "mb-3",
                    "text": (f"核验异常 {len(progress_audit['issues'])} 条，详见插件日志。" if progress_audit.get("issues") else "核验完成后会在上方展示逐条差异和修复结果。"),
                },
            },
            progress_actions,
        ]
