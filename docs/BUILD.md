# 构建与本机接入

离线查询只需 Python 3.11+。本页的运行时操作由使用者在自己的测试环境显式执行；发布过程没有执行注入、提权 helper、保存或试玩。

## 构建自有桥

安装 .NET 8 SDK、Windows Desktop targeting pack；原生代码另需 Visual Studio Build Tools 的 x64 C++ 工具与 Windows SDK。

```powershell
python -X utf8 -B scripts/build.py
python -X utf8 -B scripts/build.py --native
```

输出位于各 `csproj` 的 `bin/Release` 与 `.runtime/game-executor/build`。构建脚本只编译自己的代码，不启动游戏。`--research` 额外编译 ILSpy 元数据工具，需要 .NET 9 SDK 及 NuGet 依赖。

原生场景 snapshot/scene 各动作使用 `build_readonly_profile.py`、`build_scene_profile.py` 生成一次性 profile 并编译，其 `compile-check` 使用不可启动的离线样本。模板、地形、变换等各目录 `build.py` 是对应构建入口。地址与类型签名必须匹配具体版本；不要改指纹来假装兼容。

## 配置路径与解释器

运行时依赖：

```powershell
python -m pip install -r requirements-runtime.txt
python scripts/configure.py --game-dir "C:\Games\Genshin Impact Game" --powershell-host "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
. .runtime/environment.local.ps1
python tools/game-executor/record-content-interpreter-pin.py --python $env:MILIASTRA_PYTHON
python -X utf8 -B pen.py tool version --component native-scene
```

`configure.py` 只重定位本 checkout 的安装路径、生成本地环境文件与最小 helper 配置；不改游戏。默认路径是普通示例，改为自己的实际安装目录。源码路径配置会使发行 manifest 与本地源码有差异，配置后不要提交个人路径。二进制 SHA、签名、版本与 review 逻辑不会被放宽。

解释器 pin 记录在 git-ignored 的 `config/save-content-interpreter.lock.json`，由本机重新生成，不包含在发行包。helper 的运行时依赖布局面向 Windows 正常安装的 Python（`python.exe` 同目录包含 `Lib`、`DLLs`），不承诺 venv 的 `Scripts/python.exe` 布局；离线工具不受此限制。helper 在启动时冻结解释器、依赖和源码，修改后需要使用者处理自己的 helper 生命周期，不应在已有任务中擅自重启。

## 编辑器加载依赖

从 [Snoop 官方仓库](https://github.com/snoopwpf/snoopwpf/releases/tag/v6.1.1) 取得 6.1.1 的签名发行包，将 `Snoop.InjectorLauncher.x64.exe` 和 `Snoop.GenericInjector.x64.dll`（以及发行包所需的相邻依赖）放入：

```text
.runtime/editor-bridge/vendor/snoop-6.1.1/
```

本项目没有附带这些二进制。源码会校验签名、目标进程身份、编辑器 DLL 指纹及加载产物哈希。构建源码并配置依赖后，操作顺序是：

1. 使用者启动自己的游戏和编辑器，进入独立测试关卡，明确当前会话与保护范围。
2. 在允许脚本执行的 PowerShell 主机中运行 `tools/editor-bridge/start-elevated.ps1`，处理系统 UAC。helper 的泛用文件写权限只限本 checkout，游戏安装只读。
3. 通过 `elevated-request.py --queue-dir <队列> load --target-pid <编辑器PID>` 建立租约。PID、runId、nonce、requestId 都应新鲜取得，不能复制研究笔记里的值。
4. 用 `pen.py tool author --help`、`pen.py tool scene --help` 按实际命令提供参数。写入需要新鲜基线、协调 review、会话身份与独立读回。

`source-implemented` 不等于任何机器即装即用。部分历史 native-card 动作还固定了测试关卡/组件合同，需理解与适配其合同后才能使用；当前发布保留拒绝行为。完整的创造、保存、重开、试玩仍需要本机验收。

## 可选 DSH 插件

`plugins/miliastra` 为真实 Cordis 适配器源码，依赖声明在 `package.json`：

```powershell
cd plugins/miliastra
npm install
npm run build
```

构建后按使用者 DSH 版本安装，并在插件配置中指向本仓库 backend。该插件和 `backend/*_server.py` 依赖 Python MCP SDK；最简 `pen.py mcp` 无此依赖。DSH 主程序、已有配置、账号和会话不在仓库内，也不会被安装脚本修改。
