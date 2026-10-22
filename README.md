# the-66-pen

原神「千星奇域／千星沙箱」的社区接口研究与工具集。整理已有人工、Codex 与 DeepSeek 调研，提供真实源码、节点目录、存档解析和本机桥接工具。**这些是非官方适配接口，不是官方公开 API。**

## 马上使用

安装 Python 3.11+，克隆后执行（离线，不需要游戏）：

```powershell
git clone https://github.com/CH3SH-LC/the-66-pen.git
cd the-66-pen
python -X utf8 -B pen.py doctor
python -X utf8 -B pen.py catalog entity --limit 10
python -X utf8 -B pen.py nodes groups
python -X utf8 -B pen.py nodes explain 307 --graph-kind 20000
python -X utf8 -B pen.py nodes recipe 307 --graph-kind 20000
python -X utf8 -B pen.py demo --out .runtime/example
python -X utf8 -B pen.py inspect .runtime/example/before.gil
python -X utf8 -B pen.py diff .runtime/example/before.gil .runtime/example/after.gil
```

示例生成原创的合成容器，用于演示解析和字段差分；它不是可导入游戏的关卡。重复运行 demo 请换输出目录，程序不会覆盖已有文件。

## 有什么

- **接口目录**：当前桥操作、CLI、Python 库、734 条历史原生命令记录和 92 个 UI 操作候选，逐项附工具与证据级别。
- **节点工作台**：810 个定义、929 个图类别变体、4637 个端口、103 个枚举表；支持搜索、解释、配方和连线类型检查。
- **文件工具**：GIL/GIP/GIA 容器、实体、组件、地形、模板字段解析与差分；保留未知字段。
- **本机执行源码**：图创作、原生实体、地形、变换、材质、模板属性、试玩观测、坐标转换，以及 C#/C++ 桥、提权 helper 和构建脚本。
- **调研资料**：符号映射、消息/命令分发、组件、地形、坐标、模板、错误与能力缺口。

```powershell
python -X utf8 -B pen.py tools
python -X utf8 -B pen.py tool author --help
python -X utf8 -B pen.py catalog --static --limit 10
```

本机执行工具需要 Windows、匹配版本的合法游戏安装及自行构建/配置的桥接环境。当前适配指纹源于 **国服 7.1** 历史研究，版本不符会拒绝；没有在本次发布中连接游戏或验证当前版本兼容。详见 [构建与接入](docs/BUILD.md)、[使用方式](docs/USAGE.md)、[能力边界](docs/BOUNDARIES.md)。

## 给 AI 使用

内置 MCP stdio 服务（无额外 Python 包）：`python -X utf8 -B /你的路径/the-66-pen/pen.py mcp`。
提供 `pen_catalog`、`pen_nodes`、`pen_inspect`、`pen_doctor`。本机写入仍使用独立受控 CLI；见 [MCP 与工具调用](docs/USAGE.md)。

[完整接口目录](docs/INTERFACES.md) · [调研索引](docs/RESEARCH.md) · [来源与许可](NOTICE.md) · [验证记录](docs/VALIDATION.md)

MIT 仅覆盖自有代码与文档；不含游戏、存档、账号信息或官方资源。
