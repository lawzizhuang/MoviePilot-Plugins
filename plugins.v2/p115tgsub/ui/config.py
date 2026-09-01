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
                                "text": "v2.3：115 优先、夸克兜底的双网盘订阅追更。Telegram 公开频道先按订阅标题筛选候选；115 分享、Telegram 正文直链和 SeedHub 公开磁力均可进入定向 115 离线下载，均无可用资源时才尝试夸克转存；夸克转存成功后由 SmartStrm 在本地增量生成 STRM。"
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
                                "text": "SeedHub 公开磁力：通过指定 Telegram 公开频道定位 sidhub.cc 电影页，只读取公开磁力列表并提交至上方 115 目标目录。完整季磁力只创建一个云下载任务；不登录、不使用 Cookie、不抓取其他网盘标签。"
                            }
                        }]
                    }]
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "seedhub_enabled", "label": "启用 SeedHub 公开磁力资源", "hint": "需同时启用上方 115 ED2K / 磁力离线下载；仅在 Telegram 直链无可用候选时尝试。"}}]},
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
        defaults = {
            "enabled": False, "notify": True, "onlyonce": False, "cron": "30 */8 * * *",
            "cookie_source": "p115strmhelper", "cookies": "", "save_path": "/我的接收/MoviePilot-TG/TV", "movie_save_path": "/我的接收/MoviePilot-TG/Movie",
            "telegram_enabled": True, "telegram_channels": "QukanMovie\nlsp115\nvip115hot",
            "telegram_timeout": 20, "telegram_max_results": 10, "telegram_max_telegraph_pages": 3,
            "max_transfer_per_sync": 20, "batch_size": 10, "skip_other_season_dirs": True, "dry_run": True,
            "offline_enabled": False, "offline_max_per_sync": 5, "offline_max_wait_hours": 24,
            "seedhub_enabled": False, "seedhub_channel": "seedhub_pro", "seedhub_timeout": 20, "seedhub_max_candidates": 5,
            "seedhub_use_proxy": False,
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
        overview = (
            f"最近运行：{status.get('finished_at') or status.get('started_at') or '暂无'} · "
            f"{status.get('result') or '暂无记录'}\n"
            f"订阅 {status.get('subscribe_count', 0)} · 115 转存 {status.get('transferred_115', 0)} · "
            f"夸克转存 {status.get('transferred_quark', 0)}\n"
            f"Telegram 候选 {status.get('telegram_raw_candidates', 0)} · 合并重复 {status.get('telegram_duplicates_merged', 0)} · "
            f"夸克候选 {status.get('quark_candidates', 0)}\n"
            f"夸克跳过：{failure_text}\n"
            f"115 离线下载：待确认 {offline.get('pending', 0)} / 已确认 {offline.get('completed', 0)} / 超时 {offline.get('expired', 0)}\n"
            f"SmartStrm 重试：成功 {strm.get('triggered', 0)} / 失败 {strm.get('failed', 0)} / 停滞 {strm.get('stalled', 0)}"
        )
        if media_lines:
            overview += "\n最近媒体：" + "；".join(media_lines)
        if status.get("last_error"):
            overview += f"\n最近异常：{status['last_error']}"
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
                            "text": overview,
                        },
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info", "variant": "tonal",
                            "text": f"115 TG订阅追更 · 已记录 {recent_count} 条转存结果。立即运行会按“115 优先、夸克兜底”处理全部待处理订阅；夸克与 SmartStrm 连通性可独立验证。",
                        },
                    },
                    audit_header,
                    audit_details,
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "warning" if progress_audit.get("issues") else "info", "variant": "tonal", "class": "mb-3",
                            "text": (f"核验异常 {len(progress_audit['issues'])} 条，详见插件日志。" if progress_audit.get("issues") else "确认修复会重新读取当前 Emby 状态，并只补充已确认集数；不会回退订阅进度。"),
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
                                    "props": {"color": "info", "variant": "outlined", "prepend-icon": "mdi-clipboard-text-search-outline"},
                                    "text": "只读预览订阅进度差异",
                                    "events": {"click": {"api": f"/plugin/P115TGSub/preview_subscribe_progress?apikey={settings.API_TOKEN}", "method": "post"}},
                                }],
                            },
                            {
                                "component": "VCol", "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VBtn",
                                    "props": {"color": "warning", "variant": "outlined", "prepend-icon": "mdi-check-decagram-outline"},
                                    "text": "确认按当前媒体库修复订阅进度",
                                    "events": {"click": {"api": f"/plugin/P115TGSub/apply_subscribe_progress?apikey={settings.API_TOKEN}", "method": "post"}},
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info", "variant": "tonal",
                            "text": "订阅进度核验只读取 Emby 已入库季集和 MoviePilot 当前订阅；不会搜索 Telegram/SeedHub、访问115或夸克分享、创建目录、转存、提交离线任务、触发 SmartStrm 或写下载历史。确认修复只补充已入库集数，绝不回退订阅进度。",
                        },
                    },
                    {
                        "component": "VRow",
                        "props": {"class": "mt-2"},
                        "content": [
                            {
                                "component": "VCol", "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VBtn",
                                    "props": {"color": "primary", "variant": "outlined", "prepend-icon": "mdi-play-circle-outline"},
                                    "text": "立即运行一次",
                                    "events": {"click": {"api": f"/plugin/P115TGSub/run_once?apikey={settings.API_TOKEN}", "method": "post"}},
                                }],
                            },
                            {
                                "component": "VCol", "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VBtn",
                                    "props": {"color": "secondary", "variant": "outlined", "prepend-icon": "mdi-cloud-check-outline"},
                                    "text": "验证夸克连通性",
                                    "events": {"click": {"api": f"/plugin/P115TGSub/verify_quark?apikey={settings.API_TOKEN}", "method": "post"}},
                                }],
                            },
                            {
                                "component": "VCol", "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VBtn",
                                    "props": {"color": "teal", "variant": "outlined", "prepend-icon": "mdi-webhook"},
                                    "text": "测试 SmartStrm",
                                    "events": {"click": {"api": f"/plugin/P115TGSub/test_smartstrm?apikey={settings.API_TOKEN}", "method": "post"}},
                                }],
                            },
                            {
                                "component": "VCol", "props": {"cols": 12, "md": 3},
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
