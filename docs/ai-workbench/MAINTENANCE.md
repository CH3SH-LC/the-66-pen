# 维护、验证与移交

日常查询：`ai.py status/search/route/describe/call`。不必运行 build 或 verify。

源数据变化后：

```powershell
python -B -X utf8 tools/miliastra-toolkit/build.py --refresh-prefix transform
python -B -X utf8 tools/miliastra-toolkit/build_knowledge.py
```

新增工具族或首次构建用 `ai.py build`。源捕获失败保留旧 registry；
索引构建写临时数据库再替换。增量缓存复用相同 size/mtime 的文件元信息；
严格重查用 `build_knowledge.py --force`，不要每次查询重做。

覆盖表是自动从源集合生成的清单，不是人工写“100%”：

- `coverage.json`：集合分母、期望库、节点配方/合同/未知项、脚本登记、排除范围。
- `node-coverage.json`：每个已录制变体的缺项。
- `script-coverage.json`：全部盘点到的 Python 入口、参数、固定关卡引用、登记情况。
- `inventory-cache.json`：文件路径/时间/大小/已取哈希/摘要；大文件元数据与内容验证分开。
- `knowledge.sqlite`：素材、节点完整配方、方法、错误码、脚本、来源统一查询。
- `validation.json`：本次真实离线验证、失败、命令与退出码；不冒充真机验证。

`ai.py verify` 统一运行工作台检查；不要开发一个函数就重复跑整个历史测试矩阵。
改动原生 ABI 或合同后再做对应 compile-check，编译仅验证生成卡和本地 harness。
本轮没有派发游戏动作，不能将旧真实回执写成新工具当前已验证。

`ai.py package` 产生本地移交 ZIP，包含代码、索引、节点资料、手册与机器清单；
不包含账号存档、会话凭据、活跃队列或原版大资源文件。目录外资源写到
`external-resources.json`；使用者需放回相应资源，不能静默跳过。包内
`PACKAGE-MANIFEST.json` 可逐文件验哈希。迁移后运行 configure 生成新绝对路径。

公开历史研究见 `docs/RESEARCH.md`。`AI-START-HERE.md` 是任务路由层，不把历史方案当作当前授权。

公开包的生成索引仅基于本仓库；本地再次打包不等于适合公开上传。增加私人数据后须重新筛选。
