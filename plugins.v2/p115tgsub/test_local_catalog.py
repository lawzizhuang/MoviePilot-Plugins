"""本地表只读加载及搜索集成回归；临时文件仅位于仓库内，无网络调用。"""
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace

from test_search_handler import SearchHandler, MediaType
from openpyxl import Workbook

spec = importlib.util.spec_from_file_location("catalog_test", Path(__file__).parent / "clients/local_catalog.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
LocalCatalog = module.LocalCatalog


def run():
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
        path = Path(folder) / "sample.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "分享明细"
        sheet.append(["标题", "媒体标题", "链接", "访问码", "备注", "删除时间"])
        sheet.append(["爱你 (2025)", "爱你", "https://115.com/s/testone", "test", "S01 全28集", None])
        sheet.append(["爱你的基蒂 (2025)", "爱你的基蒂", "https://115.com/s/other", "test", "S01", None])
        sheet.append(["爱你 (2025)", "爱你", "https://115.com/s/deleted", "test", "S01", "deleted"])
        sheet.append(["爱你 (2025)", "爱你", "https://115.com/s/season2", "test", "S02", None])
        sheet.append(["爱你 (2024)", "爱你", "https://115.com/s/year", "test", "S01", None])
        sheet.append(["爱你 (2025)", "爱你", "https://pan.quark.cn/s/quarktest", "test", "S01", None])
        sheet.append(["爱你 (2025)", "爱你", "https://115.com.evil/s/no", "test", "S01", None])
        sheet.append(["爱你 (2025)", "爱你", "https://115cdn.com/s/testone", "test", "S01", None])
        book.save(path)
        book.close()
        catalog = LocalCatalog(path)
        media = SimpleNamespace(title="爱你", year="2025")
        data = catalog.search(media, MediaType.TV, 1)
        assert len(data) == 1 and "password=test" in data[0]["url"]
        assert "test" not in data[0]["title"]
        before = path.read_bytes()
        index = catalog._index
        assert catalog.search(media, MediaType.TV, 1) == data
        assert catalog._index is index and path.read_bytes() == before
        assert len(catalog.search(media, MediaType.TV, 2)) == 1
        handler = SearchHandler(None, local_catalog=catalog)
        assert handler.get_enabled_sources() == ["local_catalog"]
        assert handler.search_single_source("local_catalog", media, MediaType.TV, 1) == data
        assert len(handler.search_quark_resources(media, MediaType.TV, 1)) == 1
        assert len(handler._with_catalog(data, media, MediaType.TV, 1, "115")) == 1
        class Telegram:
            channels = ["test"]
            def search_115_resources(self, *args, **kwargs):
                return data
        handler = SearchHandler(Telegram(), True, local_catalog=catalog)
        assert handler.get_enabled_sources() == ["telegram"]
        assert len(handler.search_single_source("telegram", media, MediaType.TV, 1)) == 1
        path.write_bytes(b"invalid")
        assert catalog.search(media, MediaType.TV, 1) == []
        path.unlink()
        assert catalog.search(media, MediaType.TV, 1) == []
    print("p115tgsub local catalog tests: OK")


if __name__ == "__main__":
    run()
