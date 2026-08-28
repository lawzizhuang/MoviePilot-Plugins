"""115 ED2K/磁力离线下载待确认队列。

不保存 ED2K/磁力原文、Cookie 或任务响应原文。115 接收任务不等于成功；
仅当目标目录实际发现对应媒体文件时才标记完成。
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Callable, Dict, Iterable, List, Set


class OfflineQueue:
    DATA_KEY = "p115_offline_queue"

    def __init__(self, get_data_func: Callable[[str], Any], save_data_func: Callable[[str, Any], None], max_wait_hours: int = 24):
        self._get_data = get_data_func
        self._save_data = save_data_func
        self._max_wait_hours = max(1, min(int(max_wait_hours or 24), 168))

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.now()

    @classmethod
    def _now_text(cls) -> str:
        return cls._now().strftime("%Y-%m-%d %H:%M:%S")

    def _load(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in (self._get_data(self.DATA_KEY) or []) if isinstance(item, dict)]

    def _save(self, items: List[Dict[str, Any]]) -> None:
        self._save_data(self.DATA_KEY, items)

    def expire(self) -> int:
        """超时任务标记失败并释放后续夸克兜底，不删除审计状态。"""
        changed = 0
        deadline = self._now() - datetime.timedelta(hours=self._max_wait_hours)
        items = self._load()
        for item in items:
            if item.get("status") != "pending":
                continue
            try:
                created = datetime.datetime.strptime(str(item.get("created_at") or ""), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                created = deadline
            if created <= deadline:
                item["status"] = "expired"
                item["updated_at"] = self._now_text()
                changed += 1
        if changed:
            self._save(items)
        return changed

    def pending_episodes(self, subscribe_id: Any, season: int) -> Set[int]:
        self.expire()
        result: Set[int] = set()
        for item in self._load():
            if item.get("status") != "pending" or str(item.get("subscribe_id")) != str(subscribe_id):
                continue
            if int(item.get("season") or 0) != int(season or 0):
                continue
            try:
                result.add(int(item.get("episode")))
            except (TypeError, ValueError):
                continue
        return result

    def pending_movie(self, subscribe_id: Any) -> bool:
        self.expire()
        return any(
            item.get("status") == "pending" and str(item.get("subscribe_id")) == str(subscribe_id)
            and item.get("media_type") == "电影"
            for item in self._load()
        )

    def enqueue(self, *, subscribe_id: Any, title: str, year: Any, media_type: str, savepath: str,
                resource_key: str, file_name: str, season: int = 0, episode: int = 0, task_id: str = "") -> bool:
        items = self._load()
        for item in items:
            if item.get("status") == "pending" and str(item.get("resource_key")) == str(resource_key):
                return False
            if (item.get("status") == "pending" and str(item.get("subscribe_id")) == str(subscribe_id)
                    and int(item.get("season") or 0) == int(season or 0)
                    and int(item.get("episode") or 0) == int(episode or 0)
                    and item.get("media_type") == media_type):
                return False
        items.append({
            "id": uuid.uuid4().hex[:12], "subscribe_id": str(subscribe_id), "title": str(title or ""),
            "year": str(year or ""), "media_type": str(media_type or ""), "savepath": str(savepath or ""),
            "resource_key": str(resource_key or ""), "file_name": str(file_name or ""),
            "season": int(season or 0), "episode": int(episode or 0), "task_id": str(task_id or "")[:100],
            "status": "pending", "created_at": self._now_text(), "updated_at": self._now_text(),
        })
        self._save(items)
        return True

    def complete_tv(self, subscribe_id: Any, season: int, episodes: Iterable[int]) -> List[Dict[str, Any]]:
        available = {int(value) for value in episodes}
        completed: List[Dict[str, Any]] = []
        items = self._load()
        for item in items:
            if item.get("status") != "pending" or str(item.get("subscribe_id")) != str(subscribe_id):
                continue
            if int(item.get("season") or 0) != int(season or 0):
                continue
            if int(item.get("episode") or 0) not in available:
                continue
            item["status"] = "completed"
            item["updated_at"] = self._now_text()
            completed.append(dict(item))
        if completed:
            self._save(items)
        return completed

    def complete_movie(self, subscribe_id: Any) -> List[Dict[str, Any]]:
        completed: List[Dict[str, Any]] = []
        items = self._load()
        for item in items:
            if item.get("status") == "pending" and str(item.get("subscribe_id")) == str(subscribe_id) and item.get("media_type") == "电影":
                item["status"] = "completed"
                item["updated_at"] = self._now_text()
                completed.append(dict(item))
        if completed:
            self._save(items)
        return completed

    def stats(self) -> Dict[str, int]:
        self.expire()
        result = {"pending": 0, "completed": 0, "expired": 0}
        for item in self._load():
            status = str(item.get("status") or "")
            if status in result:
                result[status] += 1
        return result
