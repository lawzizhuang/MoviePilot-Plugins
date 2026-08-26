"""SmartStrm Webhook 增量任务触发客户端。

Webhook URL 属于敏感凭据：本客户端不持久化、不打印完整 URL，
日志仅记录任务名、目标目录与结果状态。
"""
from __future__ import annotations

from typing import Any, Dict
from urllib.parse import urlsplit

import requests

from app.log import logger


class SmartStrmClient:
    """调用 SmartStrm 系统设置中的 Webhook 触发增量 STRM 生成。"""

    def __init__(self, webhook_url: str, timeout: int = 10) -> None:
        self._webhook_url = str(webhook_url or "").strip()
        self._timeout = max(5, min(int(timeout or 10), 60))
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "MoviePilot-P115TGSub/2.0",
            "Accept": "application/json",
        })

    @property
    def configured(self) -> bool:
        return bool(self._webhook_url and self._webhook_url.startswith("http"))

    def _describe(self) -> str:
        """返回不包含 token/路径敏感信息的描述，用于日志。"""
        try:
            host = urlsplit(self._webhook_url).hostname or ""
            return f"SmartStrm Webhook（{host}）"
        except Exception:
            return "SmartStrm Webhook（已配置）"

    def check_connection(self) -> Dict[str, Any]:
        """GET Webhook 端点，验证连通性；不输出响应中的敏感信息。"""
        if not self.configured:
            return {"success": False, "message": "SmartStrm Webhook 未配置"}
        try:
            response = self._session.get(self._webhook_url, timeout=self._timeout)
            data = response.json() if response.text else {}
        except requests.RequestException as exc:
            logger.warning(f"{self._describe()} 连接失败：{type(exc).__name__}")
            return {"success": False, "message": f"连接失败：{type(exc).__name__}"}
        except ValueError:
            return {"success": False, "message": f"响应非 JSON（HTTP {response.status_code}）"}
        if response.status_code != 200 or not data.get("success"):
            return {"success": False, "message": str(data.get("message") or f"HTTP {response.status_code}")}
        version = str(data.get("version") or "")
        logger.info(f"{self._describe()} 连接成功，版本 {version}")
        return {"success": True, "message": f"连接成功（版本 {version}）"}

    def trigger_incremental(
        self, strmtask: str, savepath: str, xlist_path_fix: str = "", event: str = "qas_strm"
    ) -> Dict[str, Any]:
        """触发 SmartStrm 增量任务，仅针对转存目标目录。

        :param strmtask: SmartStrm 任务名，支持逗号分隔多个
        :param savepath: 转存成功的目标目录（SmartStrm 据此只增量生成该目录）
        :param xlist_path_fix: OpenList 驱动时的路径映射；夸克网盘驱动时留空
        :param event: 触发事件标识
        :return: {"success": bool, "message": str, "task": dict}
        """
        if not self.configured:
            return {"success": False, "message": "SmartStrm Webhook 未配置"}
        task_names = ",".join(str(value).strip() for value in str(strmtask or "").split(",") if str(value).strip())
        if not task_names:
            return {"success": False, "message": "SmartStrm 任务名为空"}
        if not str(savepath or "").strip():
            return {"success": False, "message": "SmartStrm 转存目标目录为空"}

        payload: Dict[str, Any] = {
            "event": event,
            "data": {
                "strmtask": task_names,
                "savepath": str(savepath).strip(),
                "xlist_path_fix": str(xlist_path_fix or "").strip(),
            },
        }
        try:
            response = self._session.post(
                self._webhook_url, json=payload, timeout=self._timeout
            )
            data = response.json() if response.text else {}
        except requests.RequestException as exc:
            logger.warning(f"{self._describe()} 触发增量任务失败：{type(exc).__name__}")
            return {"success": False, "message": f"请求失败：{type(exc).__name__}"}
        except ValueError:
            return {"success": False, "message": f"响应非 JSON（HTTP {response.status_code}）"}

        if response.status_code != 200 or not data.get("success"):
            message = str(data.get("message") or f"HTTP {response.status_code}")
            logger.warning(f"{self._describe()} 触发增量任务失败：{message}")
            return {"success": False, "message": message}
        task = data.get("task") if isinstance(data.get("task"), dict) else {}
        logger.info(
            f"{self._describe()} 已触发增量任务 [{task.get('name', '')}] "
            f"路径 {task.get('storage_path', savepath)}"
        )
        return {"success": True, "message": "增量任务已触发", "task": task}
