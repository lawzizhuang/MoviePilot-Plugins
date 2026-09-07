"""目录降压与失败安全回归；直接运行，无网络、无网盘写入。"""
from test_p115_offline import module, _query_manager


def test_unknown_path_never_creates():
    class Client:
        writes = 0
        def fs_dir_getid(self, path):
            raise ValueError("unavailable")
        def fs_makedirs_app(self, *args, **kwargs):
            self.writes += 1
    client = Client()
    manager = _query_manager(client)
    manager.path_cache = module.PathCache()
    try:
        manager.get_pid_by_path('/test', mkdir=True)
    except RuntimeError:
        pass
    else:
        raise AssertionError('未知目录必须抛错')
    assert client.writes == 0


def test_incomplete_listing_rejected():
    manager = _query_manager(type('Client', (), {
        'fs_files': lambda self, payload: {'state': True, 'count': 2, 'data': [{'fid': '1', 'n': 'one.mkv'}]}
    })())
    manager.get_pid_by_path = lambda *args, **kwargs: 123
    original = getattr(module, 'check_response', None)
    module.check_response = lambda response: response
    try:
        try:
            manager.list_files('/test')
        except RuntimeError:
            pass
        else:
            raise AssertionError('不完整目录不能用于查重')
    finally:
        if original is None:
            del module.check_response
        else:
            module.check_response = original


def test_child_failure_does_not_retry_parent():
    calls = []
    def iterator(client, **kwargs):
        cid = kwargs['cid']
        calls.append(cid)
        if cid == 0:
            return iter([{'id': 1, 'name': 'Season 1', 'is_dir': True}])
        raise TimeoutError('timeout')
    manager = _query_manager(object())
    manager.recursion_delay = 0
    original_iterator = getattr(module, 'share_iterdir', None)
    original_sleep = module.time.sleep
    module.share_iterdir = iterator
    module.time.sleep = lambda seconds: None
    try:
        try:
            manager._list_share_files_recursive('share', 'code')
        except TimeoutError:
            pass
        else:
            raise AssertionError('子目录失败必须传播')
        assert calls == [0, 1, 1], calls
    finally:
        if original_iterator is None:
            del module.share_iterdir
        else:
            module.share_iterdir = original_iterator
        module.time.sleep = original_sleep


def test_paginated_listing_reads_each_page_once():
    calls = []
    class Client:
        def fs_files(self, payload):
            calls.append(payload['offset'])
            start = payload['offset']
            return {'state': True, 'count': 1001, 'offset': start,
                    'data': [{'fid': str(i + 1), 'n': f'{i}.mkv'}
                             for i in range(start, min(start + 1000, 1001))]}
    manager = _query_manager(Client())
    manager.get_pid_by_path = lambda *args, **kwargs: 123
    original = getattr(module, 'check_response', None)
    module.check_response = lambda response: response
    try:
        assert len(manager.list_files('/test')) == 1001
        assert calls == [0, 1000]
    finally:
        if original is None:
            del module.check_response
        else:
            module.check_response = original


def test_terminal_cache_survives_run_but_not_access_code_change():
    manager = _query_manager(object())
    manager._remember_terminal_share('abc', '1234', 4100018)
    manager.begin_run()
    manager.extract_share_info = lambda url: {'share_code': 'abc', 'receive_code': '1234'}
    assert manager.check_share_status('not-a-real-link').is_expired
    assert manager._terminal_share_key('abc', '5678') not in manager._terminal_shares
    manager._remember_terminal_share('transient', '', 405)
    assert len(manager._terminal_shares) == 1
    manager._remember_terminal_share('other', '', 4100010)
    assert len(manager._terminal_shares) == 2


if __name__ == '__main__':
    test_unknown_path_never_creates()
    test_incomplete_listing_rejected()
    test_child_failure_does_not_retry_parent()
    test_paginated_listing_reads_each_page_once()
    test_terminal_cache_survives_run_but_not_access_code_change()
    print('read safety tests: OK')
