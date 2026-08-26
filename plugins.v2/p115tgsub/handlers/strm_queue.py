"""SmartStrm 增量触发待重试队列。

转存成功与 STRM 后处理解耦：夸克文件确认存在后立即入队并尝试触发；
Webhook 失败只更新队列状态，绝不重新发起网盘转存。
队列只保存脱敏信息（标题、季集、目标目录、任务名），不保存任何分享链接、
提取码、Cookie 或 Webhook Token。
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Callable, Dict, List, Optional


class StrmQueue:
    """基于 MoviePilot 插件数据区的持久化待重试队列。"""

    DATA_KEY = "strm_queue"

    def __init__(
        self,
        get_data_func: Callable[[str], Any],
        save_data_func: Callable[[str, Any], None],
        max_attempts: int = 5,
    ) -> None:
        self._get_data = get_data_func
        self._save_data = save_data_func
        self._max_attempts = max(1, min(int(max_attempts or 5), 20))

    def _load(self) -> List[Dict[str, Any]]:
        items = self._get_data(self.DATA_KEY) or []
        return [item for item in items if isinstance(item, dict)]

    def _save(self, items: List[Dict[str, Any]]) -> None:
        self._save_data(self.DATA_KEY, items)

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def all(self) -> List[Dict[str, Any]]:
        return self._load()

    def pending(self) -> List[Dict[str, Any]]:
        return [item for item in self._load() if not item.get("stalled")]

    def stalled(self) -> List[Dict[str, Any]]:
        return [item for item in self._load() if item.get("stalled")]

    def enqueue(
        self,
        *,
        cloud: str,
        title: str,
        savepath: str,
        strmtask: str,
        year: str = "",
        media_type: str = "",
        season: Optional[int] = None,
        episodes: Optional[List[int]] = None,
        xlist_path_fix: str = "",
    ) -> Optional[str]:
        """入队并返回队列项 ID；同目标目录+任务+集数组合已存在时返回 None。"""
        normalized_episodes: List[int] = []
        for value in episodes or []:
            try:
                episode = int(value)
            except (TypeError, ValueError):
                continue
            if episode > 0:
                normalized_episodes.append(episode)
        episodes = sorted(set(normalized_episodes))
        items = self._load()
        episode_key = ",".join(str(value) for value in episodes)
        for item in items:
            if (
                str(item.get("savepath") or "") == str(savepath).strip()
                and str(item.get("strmtask") or "") == str(strmtask).strip()
                and ",".join(str(value) for value in (item.get("episodes") or [])) == episode_key
            ):
                return None
        item_id = uuid.uuid4().hex[:12]
        items.append({
            "id": item_id,
            "cloud": str(cloud or ""),
            "title": str(title or ""),
            "year": str(year or ""),
            "type": str(media_type or ""),
            "season": season,
            "episodes": episodes,
            "savepath": str(savepath).strip(),
            "strmtask": str(strmtask).strip(),
            "xlist_path_fix": str(xlist_path_fix or "").strip(),
            "attempts": 0,
            "stalled": False,
            "created_at": self._now(),
            "updated_at": self._now(),
            "last_error": "",
        })
        self._save(items)
        return item_id

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        return next((item for item in self._load() if item.get("id") == item_id), None)

    def trigger_one(self, item_id: str, strm_client) -> Dict[str, Any]:
        """仅触发指定队列项，避免同一同步周期把新失败项立即重复请求。"""
        item = self.get(item_id)
        if not item or item.get("stalled"):
            return {"success": False, "message": "队列项不存在或已停滞"}
        if not strm_client or not getattr(strm_client, "configured", False):
            return {"success": False, "message": "SmartStrm 未配置"}
        outcome = strm_client.trigger_incremental(
            strmtask=str(item.get("strmtask") or ""),
            savepath=str(item.get("savepath") or ""),
            xlist_path_fix=str(item.get("xlist_path_fix") or ""),
        )
        if outcome.get("success"):
            self.mark_done(item_id)
        else:
            self.mark_failed(item_id, outcome.get("message") or "")
        return outcome

    def mark_done(self, item_id: str) -> bool:
        items = [item for item in self._load() if item.get("id") != item_id]
        self._save(items)
        return True

    def mark_failed(self, item_id: str, error: str = "") -> bool:
        items = self._load()
        for item in items:
            if item.get("id") != item_id:
                continue
            item["attempts"] = int(item.get("attempts") or 0) + 1
            item["updated_at"] = self._now()
            item["last_error"] = str(error or "触发失败")[:200]
            if item["attempts"] >= self._max_attempts:
                item["stalled"] = True
            self._save(items)
            return True
        return False

    def requeue_stalled(self, item_id: str) -> bool:
        """把已停滞项重新投入重试。"""
        items = self._load()
        for item in items:
            if item.get("id") != item_id:
                continue
            item["stalled"] = False
            item["attempts"] = 0
            item["updated_at"] = self._now()
            self._save(items)
            return True
        return False

    def process_queue(self, strm_client) -> Dict[str, Any]:
        """触发所有待重试项；成功出队、失败累计次数。返回本次处理结果统计。"""
        result = {"triggered": 0, "failed": 0, "stalled": 0}
        if not strm_client or not getattr(strm_client, "configured", False):
            return result
        for item in self.pending():
            outcome = strm_client.trigger_incremental(
                strmtask=str(item.get("strmtask") or ""),
                savepath=str(item.get("savepath") or ""),
                xlist_path_fix=str(item.get("xlist_path_fix") or ""),
            )
            if outcome.get("success"):
                self.mark_done(str(item.get("id") or ""))
                result["triggered"] += 1
            else:
                self.mark_failed(str(item.get("id") or ""), outcome.get("message") or "")
                result["failed"] += 1
                if any(entry.get("id") == item.get("id") and entry.get("stalled") for entry in self.all()):
                    result["stalled"] += 1
        return result
