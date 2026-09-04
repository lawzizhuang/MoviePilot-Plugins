# MoviePilot-Plugins（本地适配与自定义插件）

本仓库是基于 [`mrtian2016/MoviePilot-Plugins`](https://github.com/mrtian2016/MoviePilot-Plugins) 维护的个人 MoviePilot V2 插件仓库，用于通过 MoviePilot 自定义插件市场在线安装。

当前包含两个独立的 115 订阅追更插件：

| 插件 | ID | 目录 | 定位 |
|---|---|---|---|
| 115网盘订阅追更（本地适配） | `P115StrgmSubLocal` | `plugins.v2/p115strgmsublocal/` | 原追更插件的本地适配版；支持 PanSou、Nullbr、HDHive 搜索源。 |
| 115 TG订阅追更 | `P115TGSub` | `plugins.v2/p115tgsub/` | 直接检索指定 Telegram 公开频道中的 115/夸克分享资源；夸克链路兜底转存并联动 SmartStrm；不依赖 CloudSaver。 |

> 两个插件均读取 MoviePilot 的订阅信息、检查电影或剧集缺失内容，并将通过校验的 115 分享资源转存到指定目录。请按自身资源来源选择其一进行测试，避免两个插件同时处理同一批订阅。

## 工作流

```text
MoviePilot 订阅
    ↓
P115StrgmSubLocal 或 P115TGSub
    ↓
搜索 115 分享资源 → 校验分享目录与文件 → 转存至 115
    ↓
115网盘STRM助手（DDSRem）生成 / 更新 STRM
    ↓
Emby 等媒体服务器入库与播放
```

## 插件一：115网盘订阅追更（本地适配）

```text
插件 ID：P115StrgmSubLocal
目录：plugins.v2/p115strgmsublocal/
版本：1.5.4
```

适用于已有或计划使用下列搜索服务的场景：

- PanSou；
- Nullbr；
- HDHive。

该插件已将 `p115client` 固定为：

```text
p115client==0.0.9.6.5.1
```

以保持与 DDSRem 的 `115网盘储存`、`115网盘STRM助手` 插件一致，避免上游已失效的依赖版本导致无法安装。

### 主要能力

- MoviePilot 电影、剧集订阅追更；
- 115 分享有效性、目录及文件校验；
- SxxExx、EPxx、第 xx 集等剧集匹配；
- 订阅质量、分辨率、特效过滤与洗版；
- 115 转存、历史去重、订阅完成状态更新；
- 批量限制、速率限制与重试控制。

## 插件二：115 TG订阅追更

```text
插件 ID：P115TGSub
目录：plugins.v2/p115tgsub/
版本：2.4.7
```

面向“资源直接发布在 Telegram 公开频道”及 4K Monitor 匿名免费资源的订阅追更场景。插件自行访问 Telegram 公开搜索页和按 TMDB ID 的 4K Monitor 公开资源页，不调用 CloudSaver API，也不保存 CloudSaver 的地址、JWT 或账号密码。

### v2.4.7

- **离线候选链路修复**：115 分享未命中后，Telegram 正文 ED2K / Magnet 搜索可继续按预期执行，不再因追更排序参数报错中断订阅。

### v2.4.6

- **追更候选最新优先**：连续尾集追更按 Telegram 消息发布时间从新到旧截取候选；老剧补档保留历史消息顺序，避免漏掉较早发布的资源。

### v2.4.5

- **超前点映追更**：TMDB 播出日期只作元数据参考，不再阻断 Telegram、115 和夸克的候选检索；资源仍必须通过标题、季集和分享目录文件严格校验。

### v2.4.4

- **115 查询容错**：查询遇 405 / 5xx / 网络临时错误时限次重试并区分临时失败与真实分享失效；连续 3 次 405 自动熔断 115 Web 查询，下轮恢复。
- **搜索收敛**：单集定向 Telegram 搜索仅用于不超过 3 个待补集的连载，避免整季缺失放大请求量。

### v2.4.3

- **Telegram 连载缺集优先**：对当前待补季集先执行 `片名 SxxExx` 精确检索，并在频道候选上限前优先排序命中目标集的消息，避免旧单集挤掉最新发布。

### v2.4.2

- **设置页重构**：按运行安全、115 凭据、资源来源和后处理职责分区，复杂来源设置改为可展开面板，配置项与默认值保持不变。

### v2.4.1

- **详情页重构**：运行状态改为指标卡、来源与离线队列标签、操作分区和最近转存记录表，不再堆叠纯文本摘要。

### v2.4.0

- **4K Monitor 自动排查**：每轮按 MoviePilot 已确认 TMDB ID 精确检索匿名免费候选；电影与标题明确匹配的剧集资源可进入既有 115 离线队列。
- **严格免费边界**：只接受 `free`、`credit_cost=0`、未锁定且允许访问的候选；不登录、不使用 Cookie、不消耗会员/credits、不调用解锁接口。403/429 立即熔断本轮后续请求。

### v2.3.5

- **核验结果可视化**：订阅进度核验改为统计卡片与差异表格，连续集数压缩显示；可直接对比 Emby 已入库、MoviePilot `note` 修复前后和缺失集数变化。

### v2.3.4

- **订阅进度核验 / 修复**：详情页新增只读差异预览和确认修复；仅依据 Emby 已入库季集补充 MoviePilot 的 `note` 并重算 `lack_episode`，不回退任何进度。
- **追更链路隔离**：核验与修复不搜索 Telegram/SeedHub，不访问 115/夸克分享，不转存、不提交离线任务、不触发 SmartStrm、不写下载历史。

### v2.3 支持范围

```text
MoviePilot 订阅
→ Telegram 公开频道搜索页
→ 115 分享、正文直链 ED2K/Magnet、4K Monitor 匿名免费磁力或 SeedHub 公开磁力资源
→ 定向保存至 115 电影/电视剧季目录，目标文件二次确认
→ 无可用 115 资源时转存夸克（复用 QuarkDisk Cookie）
→ 更新 MoviePilot 订阅状态
→ 夸克转存成功联动 SmartStrm 增量生成 STRM
```

已适配的资源形态：

| 频道示例 | 资源形式 | 处理方式 |
|---|---|---|
| `QukanMovie` | 115 链接直接位于 Telegram 消息内 | 直接提取消息正文和链接按钮中的 115 分享链接。 |
| `lsp115` | Telegram 消息通过“查看资源”跳转至 `telegra.ph` | 仅在消息标题匹配且没有直接 115 链接时，限额访问 Telegraph 页面并提取 115 链接。 |
| `vip115hot` | 混合发布多种网盘链接 | 仅保留 115 域名链接，其他网盘链接自动跳过。 |
| 夸克资源频道 | 消息内或 Telegraph 页含 `pan.quark.cn` 链接 | 与 115 使用同一套消息解析与标题初筛；仅当 115 无可用候选时进入夸克链路。 |

夸克链路仅接受 `pan.quark.cn` 域名分享链接。115 链路仅接受下列域名的分享链接：

```text
115.com
*.115.com
115cdn.com
*.115cdn.com
anxia.com
*.anxia.com
```

### v2.0 明确不支持

- CloudSaver API、CloudSaver JWT 或其他 CloudSaver 运行依赖；
- Telegram 私有频道、邀请链接、私有群组；
- Telegram 用户账号登录、Telethon、Pyrogram；
- 未经分享目录和缺集匹配校验的盲目转存；
- 通过 MoviePilot 向夸克远端写入 NFO、海报或图片（夸克远端仅存媒体文件）；
- 同一集同时转存到 115 与夸克（115 优先，历史记录去重）。

### 首次配置建议

1. 配置独立的 115 测试目录与有效 115 Cookie；夸克链路先安装并启用「夸克网盘存储（QuarkDisk）」；
2. 在插件中填写公开频道，每行一个，例如：

   ```text
   QukanMovie
   lsp115
   vip115hot
   ```

3. 配置夸克电影/电视剧转存目录，以及 SmartStrm Webhook 地址与任务名；
4. 保持默认的「测试模式（只验证，不转存）」开启；
5. 手动运行一次，确认日志中依次出现：

   ```text
   Telegram 搜索
   → 4K Monitor 匿名免费候选检查
   → 115 分享校验 / 夸克分享校验
   → 分享目录文件匹配
   ```

6. 用详情页「验证夸克连通性」「测试 SmartStrm」做只读验证；确认候选、季集和目标目录均正确后，再关闭测试模式进行实际转存。

### 默认安全控制

- 自动处理全部 MoviePilot 待处理订阅（状态 N、R）；
- 默认测试模式，不转存、不修改订阅、不触发 SmartStrm；
- Telegram 消息文本必须包含订阅标题；
- 4K Monitor 仅按精确 TMDB ID、低频检查匿名免费候选；不登录、不使用 Cookie、不请求会员/credits 解锁；
- 115 优先、夸克兜底，同一集不双盘重复转存；
- 夸克转存成功以目标目录二次确认为准；
- 夸克风控词触发冷却熔断，仅网络瞬态异常重试；
- Telegraph 二跳仅在需要时发生，并限制每频道请求数量；
- 限制每频道检查消息数、每轮转存文件数、转存批次大小；
- 调度周期最短为 8 小时；
- 不在常规日志和通知中输出 115/夸克 Cookie、Webhook 完整地址、访问密码或完整分享链接。

## 安装

在 MoviePilot 的插件市场 / 自定义插件仓库中添加本仓库地址：

```text
https://github.com/lawzizhuang/MoviePilot-Plugins
```

刷新插件市场后按需安装：

```text
115网盘订阅追更（本地适配）
115 TG订阅追更
```

MoviePilot V2 读取 `package.v2.json` 与 `plugins.v2/` 目录；自定义仓库应使用 `main` 分支。

## 依赖与运行边界

- `P115StrgmSubLocal` 与 `P115TGSub` 都依赖：

  ```text
  p115client==0.0.9.6.5.1
  ```

- `P115TGSub` 额外使用 `requests` 请求公开的 Telegram / Telegraph 页面；
- 插件依赖安装在 MoviePilot 的共享 Python 环境中；安装前应检查已有插件依赖是否冲突；
- 115 Cookie、MoviePilot API Token、Telegram 登录信息不应提交至仓库、日志、Issue 或聊天记录。

## 开发与验证

新插件 `P115TGSub` 的最小静态检查：

```bash
python -m compileall -q plugins.v2/p115tgsub
python plugins.v2/p115tgsub/test_telegram_web.py
python plugins.v2/p115tgsub/test_sync_handler.py
python plugins.v2/p115tgsub/test_quark_client.py
python plugins.v2/p115tgsub/test_smartstrm_client.py
python plugins.v2/p115tgsub/test_strm_queue.py
python plugins.v2/p115tgsub/test_quark_sync_handler.py
git diff --check
```

测试覆盖：

- Telegram 消息内直接 115/夸克链接、Telegraph 二跳、混合网盘链接过滤、标题初筛先于上限；
- 115 标题匹配与订阅集数回退；
- 夸克分享解析、目录读取、指定文件保存、风控熔断、二次确认；
- SmartStrm Webhook 契约（GET 校验 / POST 增量触发）与待重试队列单次触发/停滞；
- 夸克链路全流程：115 已转存集跳过、测试模式不转存、二次确认失败不更新订阅。

> 静态测试不替代真实环境验收。实际转存前必须使用测试订阅、测试目录和测试模式完成端到端核验。
