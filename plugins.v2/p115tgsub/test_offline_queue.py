"""115 离线下载待确认队列的最小离线测试。"""
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parent / "handlers" / "offline_queue.py"
spec = importlib.util.spec_from_file_location("offline_queue_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
OfflineQueue = module.OfflineQueue


class MemoryData:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def save(self, key, value):
        self.data[key] = value


def test_pending_episode_is_locked_then_completed():
    data = MemoryData()
    queue = OfflineQueue(data.get, data.save, max_wait_hours=24)
    assert queue.enqueue(
        subscribe_id=1, title="测试剧", year=2026, media_type="电视剧",
        savepath="/TV/测试剧 (2026)/Season 1", resource_key="hash", file_name="测试剧.S01E02.mkv",
        season=1, episode=2,
    )
    assert queue.pending_episodes(1, 1) == {2}
    assert queue.complete_tv(1, 1, {2})[0]["episode"] == 2
    assert queue.pending_episodes(1, 1) == set()
    saved = str(data.get("p115_offline_queue"))
    assert "ed2k://" not in saved and "magnet:" not in saved


if __name__ == "__main__":
    test_pending_episode_is_locked_then_completed()
    print("offline queue tests: OK")
