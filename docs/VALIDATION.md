# 验证范围

## v0.2.0 · 2026-10-28

公开版从自身源码重建，未复制私人知识数据库。

| 检查 | 结果 |
|---|---|
| 无第三方包虚拟环境：`ai.py build` | 通过；179 个生产工具、27 个路由入口，无 schema 捕获失败 |
| `ai.py verify`（已安装 protobuf） | 43/43；包含两个不同关卡上下文、漂移/过期拒绝、所有权合同与真实 MCP 进程 |
| 原公开 CLI/MCP 集成测试 | 8/8 |
| `reparent-compile-check`，关卡 1073741901 | exit 0，compiled=true，launchable=false，called=false |
| `semantic-assembly-compile-check`，关卡 1073741902 | exit 0，compiled=true，launchable=false，called=false |
| 两个助手脚本的 PowerShell 语法解析 | 0 错误；没有启动助手 |

机器记录见 `catalog/workbench-validation.json`。转挂与拼接编译使用本机显式安装目录，
仅验证磁盘版本指纹和离线生成的原生卡；没有运行游戏动作。工作台测试的两个存档
是原创空容器样本，超时测试使用明确的模拟传输，不属于真实保存验收。

公开版 15 类预期素材库中 10 类有随包来源；原始图标、网格、私人参考包等 5 类明确不分发。
929 个节点变体均有配方及合同，仍有未知字段，未宣称逐节点真机验收。
无第三方包环境能构建、查询和提供 MCP；存档图解析及完整验证需要 protobuf。

## v0.1.0 历史记录

2026-10-22 在 Windows 本机进行了发布源码的离线验证。

| 命令 / 检查 | 结果 |
|---|---|
| `python -X utf8 -B -m unittest discover -s tests -v` | exit 0；8 项发行集成测试 |
| 929 个节点变体逐个生成配方 | 通过；不代表节点逐个在游戏运行 |
| 13 个公开 CLI 别名 `--help` | 全部 exit 0，未连接游戏 |
| MCP initialize / tools/list / tools/call / 未知工具拒绝 | 通过；stdio 四个只读工具 |
| 合成 GIL 容器、未知字段、差分、拒绝覆盖与损坏输入 | 通过 |
| `python -X utf8 -B scripts/build.py --native` | exit 0；Bootstrap、ManagedBridge、TestHost 与原生 executor/测试宿主编译成功 |
| `.runtime/game-executor/build/native_test_host.exe` | exit 0；独立合成宿主 566 检查，0 失败 |
| backend.server / files_server / editor_server / entity_server 导入 | 全部通过；只导入，没有运行服务或操作游戏 |
| MVP 模板目录 `mw.catalog.search` | 通过；从随包 Apache-2.0 声明表做 AST 解析 |

编译产生过 NuGet 漏洞数据源不可达的 `NU1900` 警告，以及原有 `OwnedGraphDelete.cs` 的 `CS8600` nullable 警告，编译错误为 0。Windows PowerShell 的本机脚本策略拒绝直接 `-File` 构建，本发行版的 Python 构建入口已实际成功运行，未更改系统策略。

最终文件审计、README 干净导出验证和每条命令的退出码见 `catalog/validation.json`。`MANIFEST.json` 覆盖发行文件，排除自身与构建/运行缓存。

本次没有加载桥到编辑器、没有启动或重启游戏、没有实机写入、保存、重开或试玩。版本指纹仍基于历史国服 7.1 研究；公开源码、离线测试和合成宿主均不等于当前客户端实机兼容。DSH 插件 TypeScript 源码提供了构建入口，本次未安装其可选 npm 依赖进行运行验收。
