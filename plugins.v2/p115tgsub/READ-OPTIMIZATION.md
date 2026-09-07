# 115读取降压实施记录

## 范围

当前完成A批次本地实现及B批次的明确失效分享冷却，未发布、未进行远端转存或整理验证。

- 电影、电视剧的离线确认与正常查重复用同一份目标目录结果。
- 分享递归的重试边界收缩到单个目录，不因子目录失败重试整棵树。
- 路径查询异常向上传播，不能进入创建目录分支；网盘集数核验失败不再返回空集合。
- 目标目录列表逐页读取（1000项/页，20页预算），每页单独限速与有限重试；校验总数、偏移和条目标识，出现数量变化、重复页、截断或超预算时暂缓，不能返回部分结果。
- 目录核验失败或Web熔断时，本轮汇总标记降级，不再将零转存统一说成无资源。
- 分页参数依据公开p115client.fs_files文档核对；服务端未提供快照隔离，同数量文件替换仍无法仅凭分页计数完全检测。

## 本地验证

在仓库根目录，使用禁用字节码写入的Python运行以下脚本（均不访问真实115）：

- plugins.v2/p115tgsub/test_read_safety.py
- plugins.v2/p115tgsub/test_p115_offline.py
- plugins.v2/p115tgsub/test_sync_handler.py
- plugins.v2/p115tgsub/test_file_matcher.py

15个测试脚本通过：read_safety、p115_offline、sync_handler、file_matcher、search_handler、offline_queue、ui_config、local_catalog、telegram_web、quark_sync_handler、quark_client、strm_queue、smartstrm_client、fourkmonitor_client、seedhub_client；git diff --check通过。新增1001项双页读取、失效缓存跨轮保留与访问码隔离回归。


## 后续

- 继续补充业务层端到端失败回归与完整性异常用例；目前不得称为实机验收完成。
- B批次已实现：4100010/4100018明确失效分享的客户端内存缓存（最多512项、六小时TTL、键为分享ID与访问码的SHA256）；分享查询与转存失败均可记入，跨轮保留，重建客户端后清空。405等临时错误不得记入。错误候选过滤与统一分享去重仍待实施。
- C批次：核实依赖请求回调能力后实现HTTP级限速、计数与跨轮冷却。
- 本轮优化并不证明此前405的根因，也不控制第三方插件的请求总量。
