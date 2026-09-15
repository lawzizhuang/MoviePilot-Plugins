"""无网络批次回归。"""
import importlib.util
import sys
from pathlib import Path
import test_manual as base
sys.modules['manual_test.handlers.manual'] = base.manual
spec = importlib.util.spec_from_file_location('manual_test.handlers.manual_batch', Path(__file__).parent/'handlers/manual_batch.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)
a = 'magnet:?xt=urn:btih:' + 'a'*40
b = 'magnet:?xt=urn:btih:' + 'b'*40

def test_batch():
    assert batch.parse_batch('\n'+a+'\n'+b) == [a,b]
    assert batch.parse_batch(' '.join((a+'\n'+b).split())) == [a,b]
    for text in [a+'\ninvalid', '\n'.join([a]*11), '']:
        try: batch.parse_batch(text)
        except base.manual.ManualInputError: pass
        else: raise AssertionError('must reject')
    manager = base.Manager()
    records = {}
    save = lambda k,v: records.update({k:v})
    batch.run_batch(manager,[a,a,b],'tv','/TV',True,20,10,records.get,save)
    assert not manager.writes and not records
    batch.run_batch(manager,[a,a,b],'tv','/TV',False,20,10,records.get,save)
    assert len(manager.writes)==2 and len(records['manual_offline_submitted'])==2
    batch.run_batch(manager,[a,b],'tv','/TV',False,20,10,records.get,save)
    assert len(manager.writes)==2
    manager = base.Manager()
    manager.submit_offline_task = lambda url,path: manager.writes.append(path) or False
    batch.run_batch(manager,[a,b],'tv','/TV',False,20,10,{}.get,save)
    assert len(manager.writes)==1
    manager = base.Manager()
    def fail(k,v): raise RuntimeError('disk')
    batch.run_batch(manager,[a,b],'tv','/TV',False,20,10,{}.get,fail)
    assert len(manager.writes)==1
    manager = base.Manager()
    manager.web_query_blocked = True
    batch.run_batch(manager,[a,b],'tv','/TV',False,20,10,{}.get,save)
    assert not manager.writes

def test_shares_and_partial_failure():
    from types import SimpleNamespace
    share = 'https://115cdn.com/s/abc?password=test'
    manager = base.Manager()
    records = {}
    save = lambda k,v: records.update({k:v})
    batch.run_batch(manager,[share,a],'tv','/TV',False,20,10,records.get,save)
    assert len(manager.writes)==2 and len(records)==2
    manager = base.Manager()
    manager.check_share_status = lambda url: SimpleNamespace(is_valid=False,error_code=4100018)
    batch.run_batch(manager,[share,a],'tv','/TV',False,20,10,{}.get,lambda k,v: None)
    assert len(manager.writes)==1
    manager = base.Manager()
    manager.transfer_files_batch = lambda *args,**kwargs: ([],['12'])
    report = batch.run_batch(manager,[share,a],'tv','/TV',False,20,10,{}.get,lambda k,v: None)
    assert not manager.writes and '后续1条未执行' in report

if __name__ == '__main__':
    test_batch()
    test_shares_and_partial_failure()
    print('manual batch tests: OK')
