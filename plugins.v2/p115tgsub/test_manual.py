"""手动接收模拟回归：无MoviePilot媒体识别依赖，无网络与真实写入。"""
import ast
import hashlib
import importlib.util
import sys
import types
from pathlib import Path
from threading import Lock

spec = importlib.util.spec_from_file_location('manual_test.handlers.manual', Path(__file__).parent/'handlers/manual.py')
manual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual)

class Manager:
    def __init__(self):
        self.writes = []
        self.items = [{'id': '12', 'name': 'English title {tmdb-123}', 'is_dir': True}]
        self.depth = None
        self.fail = False
    def offline_resource_key(self, text):
        return hashlib.sha256(text.encode()).hexdigest()
    def extract_share_info(self, url):
        return {'share_code': 'abc', 'receive_code': 'test'}
    def check_share_status(self, url):
        return types.SimpleNamespace(is_valid=True)
    def list_share_files(self, url, **kwargs):
        self.depth = kwargs['max_depth']
        return self.items
    def get_pid_by_path(self, path, mkdir=False):
        assert not mkdir
        if self.fail:
            raise RuntimeError('unknown')
        return -1
    def transfer_files_batch(self, url, ids, path, **kwargs):
        self.writes.append((ids, path))
        return ids, []
    def submit_offline_task(self, url, path):
        self.writes.append(path)
        return True


def test_manual():
    url = manual.parse_link('https://115cdn.com/s/abc?password=test')
    for kind, root in [('tv', '/TV'), ('movie', '/Movies')]:
        manager = Manager()
        records = []
        save = lambda values: records.extend(values)
        manual.run_manual(manager, url, kind, root, True, 20, 10, records, save)
        assert not manager.writes and not records and manager.depth == 1
        manual.run_manual(manager, url, kind, root, False, 20, 10, records, save)
        assert manager.writes == [(['12'], root)]
        assert len(records) == 1 and 'test' not in records[0]
        try:
            manual.run_manual(manager, url, kind, root, False, 20, 10, records, save)
        except manual.ManualInputError:
            pass
        else:
            raise AssertionError('重复任务未拦截')
        assert len(manager.writes) == 1
    manager = Manager()
    manager.fail = True
    try:
        manual.run_manual(manager, url, 'movie', '/Movies', False, 20, 10, [], lambda data: None)
    except RuntimeError:
        pass
    else:
        raise AssertionError('未知目录不得写入')
    assert not manager.writes


def test_offline():
    links = ['ed2k://|file|01.mkv|123|'+'a'*32+'|/', 'magnet:?xt=urn:btih:'+'a'*40]
    for link in links:
        assert manual.parse_link(link) == link
        manager = Manager()
        records = []
        manual.run_offline(manager, link, 'tv', '/TV', True, records, lambda data: records.extend(data))
        assert not manager.writes and not records
        manual.run_offline(manager, link, 'tv', '/TV', False, records, lambda data: records.extend(data))
        assert manager.writes == ['/TV'] and len(records) == 1
    for bad in ['https://115.com.evil.test/s/abc', 'file:///x', 'magnet:?xt=urn:btih:bad', 'https://115.com/s/abc extra']:
        try:
            manual.parse_link(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)


def test_authorization():
    source = ast.parse((Path(__file__).parent/'__init__.py').read_text(encoding='utf-8-sig'))
    cls = next(node for node in source.body if isinstance(node, ast.ClassDef))
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'remote_manual')
    method.decorator_list = []
    method.args.args[1].annotation = None
    replies = []
    scope = {'run_state_lock': Lock(), '__name__': 'manual_test.plugin', '__package__': 'manual_test'}
    for name in ['manual_test', 'manual_test.handlers']:
        sys.modules[name] = types.ModuleType(name)
    sys.modules['manual_test.handlers.manual'] = manual
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<remote_manual>', 'exec'), scope)
    plugin = types.SimpleNamespace(_bot_transfer_users='123', _enabled=True,
                                  _bot_transfer_enabled=True, _sync_running=True,
                                  _progress_repair_running=False,
                                  post_message=lambda **kw: replies.append(kw))
    def event(user):
        return types.SimpleNamespace(event_data={'action': 'p115_manual_tv', 'user': user,
                                    'channel': 'Telegram', 'arg_str': 'https://115.com/s/abc'})
    scope['remote_manual'](plugin, event('other'))
    assert not replies
    scope['remote_manual'](plugin, event('123'))
    assert '运行' in replies[-1]['text']
    plugin._bot_transfer_enabled = False
    scope['remote_manual'](plugin, event('123'))
    assert '启用' in replies[-1]['text']

if __name__ == '__main__':
    test_manual()
    test_offline()
    test_authorization()
    print('manual receive tests: OK')
