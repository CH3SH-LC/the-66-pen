# 千星制作 AI 工作台

本入口把已有工具、素材、节点配方、历史方法和本次跨存档改造接在一起。
先读当前用户指令及本仓库 `docs/BOUNDARIES.md`；历史制作授权不自动延续。

```powershell
python -B -X utf8 ai.py build  # 首次克隆或更新源码后执行一次
python -B -X utf8 ai.py status
python -B -X utf8 ai.py route 拼接
python -B -X utf8 ai.py search 喷泉
python -B -X utf8 ai.py describe context.open
```

首次调用返回不认识的字段时，执行 `describe`，按 schema 原样构造 JSON 文件，
再用 `ai.py call 工具名 --file 参数文件.json`；不要自己拼 PowerShell 命令字符串。

| 需要什么 | 入口 |
|---|---|
| 其他 AI 接手、MCP 配置、最短路径 | [快速开始](docs/ai-workbench/QUICKSTART.md) |
| 素材库、来源、尺寸和重名处理 | [素材指南](docs/ai-workbench/ASSETS.md) |
| 全部已录制节点、端口、泛型与缺项 | [节点指南](docs/ai-workbench/NODES.md) |
| 原生操作、保存、读回、单写者 | [操作手册](docs/ai-workbench/OPERATIONS.md) |
| 跨存档整栋/道路/城墙拼接 | [拼接手册](docs/ai-workbench/ASSEMBLY.md) |
| 后台截图与参考资料 | [视觉手册](docs/ai-workbench/VISUAL.md) |
| 错误码、停止条件和恢复 | [错误处理](docs/ai-workbench/ERRORS.md) |
| 完整覆盖与未解决项 | `data/ai-workbench/coverage.json`、`node-coverage.json`、`script-coverage.json` |
| 真实历史经验与依据 | [研究索引](docs/RESEARCH.md)、`knowledge.search kind=method` |
| 验证和移交 | [维护与移交](docs/ai-workbench/MAINTENANCE.md) |

`ai.py serve` 提供精简 MCP 入口；`tool.describe` 和 `tool.call` 保留完整工具集。
数据查询只读索引；不会扫描整个仓库，不会启动 helper，不会触发游戏操作。

本次整理没有恢复已结束的蒙德制作。真机制作、保存、试玩、视觉确认是不同证据；
任何工具的计划或离线检查都不能冒充它们。

这是公开发行版。原始图标、几何、个人场景与账号存档未分发；`status` 会列出实际缺少的库。
