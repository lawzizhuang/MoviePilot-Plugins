"""SmartStrm 待重试队列离线契约测试。"""
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parent / "handlers" / "strm_queue.py"
spec = importlib.util.spec_from_file_location("strm_queue_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
StrmQueue = module.StrmQueue


class MemoryData:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def save(self, key, value):
        self.data[key] = value


class FailedClient:
    configured = True

    def __init__(self):
        self.calls = 0

    def trigger_incremental(self, **kwargs):
        self.calls += 1
        return {"success": False, "message": "offline"}


def test_new_item_only_triggers_once():
    data = MemoryData()
    queue = StrmQueue(data.get, data.save, max_attempts=2)
    item_id = queue.enqueue(cloud="quark", title="测试", savepath="/TV/测试", strmtask="tv")
    client = FailedClient()
    queue.trigger_one(item_id, client)
    assert client.calls == 1
    assert queue.get(item_id)["attempts"] == 1
    assert not queue.get(item_id)["stalled"]


def test_second_round_marks_item_stalled():
    data = MemoryData()
    queue = StrmQueue(data.get, data.save, max_attempts=2)
    item_id = queue.enqueue(cloud="quark", title="测试", savepath="/TV/测试", strmtask="tv")
    client = FailedClient()
    queue.trigger_one(item_id, client)
    result = queue.process_queue(client)
    assert client.calls == 2
    assert result == {"triggered": 0, "failed": 1, "stalled": 1}
    assert queue.get(item_id)["stalled"]


def test_invalid_episode_values_are_ignored():
    data = MemoryData()
    queue = StrmQueue(data.get, data.save, max_attempts=2)
    item_id = queue.enqueue(
        cloud="quark", title="测试", savepath="/TV/测试", strmtask="tv",
        episodes=[1, "2", "E03", None, 0, -1],
    )
    assert queue.get(item_id)["episodes"] == [1, 2]


if __name__ == "__main__":
    test_new_item_only_triggers_once()
    test_second_round_marks_item_stalled()
    test_invalid_episode_values_are_ignored()
    print("strm queue tests: OK")
