"""P115TGSub 插件详情页 UI 结构回归测试。"""
import importlib.util
import sys
import types
from pathlib import Path


settings_module = types.ModuleType("app.core.config")
settings_module.settings = types.SimpleNamespace(API_TOKEN="test-token")
sys.modules.setdefault("app", types.ModuleType("app"))
sys.modules.setdefault("app.core", types.ModuleType("app.core"))
sys.modules["app.core.config"] = settings_module

MODULE_PATH = Path(__file__).parent / "ui" / "config.py"
spec = importlib.util.spec_from_file_location("p115tgsub_ui_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
UIConfig = module.UIConfig


def _walk(nodes):
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node
        yield from _walk(node.get("content"))


def _texts(nodes):
    return [str(node.get("text") or "") for node in _walk(nodes)]


def test_page_uses_structured_cards_instead_of_text_overview():
    page = UIConfig.get_page(
        history=[{"title": "测试剧", "type": "电视剧", "season": 1, "episode": 3, "status": "成功", "time": "2026-09-01 23:00:00"}],
        run_status={
            "finished_at": "2026-09-01 23:00:00", "result": "完成（未发现可转存资源）",
            "subscribe_count": 27, "transferred_115": 0, "transferred_quark": 0,
            "telegram_raw_candidates": 10, "quark_candidates": 2,
            "offline": {"pending": 1, "completed": 3, "expired": 0},
            "strm": {"triggered": 1, "failed": 0, "stalled": 0},
            "quark_failures": {}, "media": {}, "last_error": "",
        },
        progress_audit={
            "action": "预览", "finished_at": "2026-09-01 23:00:00", "scanned": 22, "updated": 0,
            "differences": [{
                "title": "测试剧 (2026)", "season": 1, "confirmed": [1, 2, 3],
                "note_before": [1, 2], "note_after": [1, 2, 3], "lack_before": 2, "lack_after": 1,
            }],
        },
    )
    components = [node.get("component") for node in _walk(page)]
    texts = _texts(page)
    assert components.count("VCard") >= 5
    assert components.count("VTable") >= 2
    assert "订阅追更运行概览" in texts
    assert "追更操作" in texts
    assert "最近转存记录" in texts
    assert "订阅进度核验" in texts
    assert not any(text.startswith("最近运行：") for text in texts)


def test_page_keeps_all_action_endpoints():
    page = UIConfig.get_page([], {}, {})
    apis = []
    for node in _walk(page):
        event = (node.get("events") or {}).get("click") or {}
        if event.get("api"):
            apis.append(event["api"])
    for endpoint in ("run_once", "verify_quark", "test_smartstrm", "clear_plugin_log", "preview_subscribe_progress", "apply_subscribe_progress"):
        assert any(endpoint in api for api in apis)


if __name__ == "__main__":
    test_page_uses_structured_cards_instead_of_text_overview()
    test_page_keeps_all_action_endpoints()
    print("p115tgsub UI tests: OK")
