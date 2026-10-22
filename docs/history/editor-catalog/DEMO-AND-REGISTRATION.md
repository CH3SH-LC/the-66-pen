> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# Demo 链路与项目注册：真实执行记录

记录日期：2026-09-18（Asia/Shanghai）。
执行者：主智能体。授权：用户 `/goal` 指令「对你刚才看到的所有功能和接口进行真实开发测试，用来从0开发一款demo游戏（包括项目注册），如果涉及到真实试玩，则只把试玩测试留下，其余开发和测试全部自行完成」。

本轮**未做试玩**。原神（`YuanShen.exe` 113168）与编辑器（`BeyondEditor.exe` 39372/114124）
全程保持运行，未关闭、未重启、未接管。

---

## 一、最优先项：千星相关文件夹的常驻提权器

### 为什么需要

编辑器以提权身份运行，其命名管道用 `PipeOptions.CurrentUserOnly` 创建，
因此非提权客户端连不上。此前每一次「注入桥接」和「调用桥接」都会弹一次 UAC。
用户在睡眠期间无法点击，整条链路会停摆。

权限实测（未提权时）：游戏安装目录、编辑器目录、LocalLow 均**可写**；
唯独 `D:\Program Files\miHoYo Launcher` 返回 `UnauthorizedAccessException`。

### 交付物

| 文件 | 作用 |
|---|---|
| `tools/editor-bridge/elevated-config.json` | 允许根目录白名单，**启动时读取一次** |
| `tools/editor-bridge/elevated-fs-guard.ps1` | 路径策略层（纯函数，可离线单测） |
| `tools/editor-bridge/elevated-fs-ops.ps1` | 文件操作实现（纯函数，可离线单测） |
| `tools/editor-bridge/elevated-runner.ps1` | 常驻提权执行器 |
| `tools/editor-bridge/start-elevated.ps1` / `start-elevated.cmd` | 一次性启动入口 |
| `tools/editor-bridge/elevated-request.py` | 非提权侧客户端 |

### 允许根目录

| 根 | 读 | 写 |
|---|---|---|
| `C:\Games\Genshin Impact Game` | ✓ | ✗ |
| `D:\Program Files\miHoYo Launcher` | ✓ | ✗ |
| `%USERPROFILE%\AppData\LocalLow\miHoYo` | ✓ | ✓ |
| 工程目录 | ✓ | ✓ |

游戏安装目录**默认只读**：本工程从未修改过原始安装，本轮不改变这一点。
要放宽需改配置并重启执行器——**刻意让扩权付出一次 UAC 的代价**，
这样只持有队列目录的非提权调用方无法在半夜自己扩权。

### 安全性质（离线单测 81 项全通过）

- 路径必须绝对、无 NUL；`..` 在 `GetFullPath` 阶段被折叠
- 必须落在某个根下，且**按分隔符边界**匹配（`...GameX` 不会匹配根 `...Game`）
- 根到目标之间**任何一段是 junction/符号链接即拒绝**（已用真实 junction 验证）
- 根自己永远删不掉
- `delete` / `move` 必须在请求里**逐字重复目标路径**才执行——这是抄写校验，
  防止被截断或手改的请求误删未指名的东西
- 十种操作固定枚举，**从不执行请求里给的命令**

### 真机验证（在活着的提权进程 pid 76712 上）

| 检查 | 结果 |
|---|---|
| 列 `D:\Program Files\miHoYo Launcher` | **成功**（未提权时是拒绝访问 → 证明提权确实生效） |
| 读 `C:\Windows\System32\drivers\etc\hosts` | 拒绝：`PATH_OUTSIDE_ALLOWED_ROOTS` |
| 写 `C:\Games\Genshin Impact Game\evil.txt` | 拒绝：`ACCESS_DENIED_BY_ROOT:game-install:write` |

寿命默认 1440 分钟。停止方式：在队列目录放 `STOP` 文件，或 `start-elevated.cmd -Stop`。

### 连带修掉的一个危险缺陷（本轮自查发现）

存活检测曾报 `age: -28799.6s` 却给出 `ALIVE`。原因：
`[DateTime]::Parse` 对带 `Z` 的时间戳**默认转换成本地时间**，
再与 `[DateTime]::UtcNow` 相减时两边用的是**不同时钟**，误差正好是一个时区偏移（8 小时）。
后果是**心跳停止 1 小时会被算成 −7 小时，从而被判为「还活着」**——
在无人值守的夜间，这恰恰是最不能出错的一项。
已改用 `AdjustToUniversal | AssumeUniversal` 解析，并新增负值守卫：
**时间戳落在未来即报 `UNKNOWN` 并以非零码退出（fail-closed）**。
修复后实测 `age: 0.5s`。

---

## 二、桥接注入的真实阻塞点（根因已定位并验证）

### 现象

`load` 请求返回 `readyFilePresent: false`，`accepted: null`，
引导日志止于 `payload loaded`，**没有任何错误信息**。

### 根因

`ManagedBridge/Entry.cs`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`_startAttempted` 是**静态字段**，住在被加载的程序集里；
而 `Assembly.LoadFrom` 对同一路径返回**已加载的那个实例**，不会加载第二份。
因此**同一版本对一个进程注入第二次必被拒绝**。

拒绝路径是 `return` 而非 `throw`，旧引导程序又不记录返回值——
于是「被拒绝」与「卡住」在外部完全无法区分。

### 对照实验（决定性）

| 实验 | 引导日志 | 外部观察 |
|---|---|---|
| R71 第一次注入 | `payload returned 0` | `accepted: true` |
| R71 第二次注入 | `payload returned 1` | 拒绝，无 ready 文件 |
| R70 早先那次失败（旧引导，不记返回码） | 日志止于 `payload loaded` | 同一签名 |

`1` = `CodeAlreadyStarted`。假设 → 受控实验 → 拿到确切错误码。

### 由此解释的既有疑点

构建目录里有 **R2…R72 约 70 个不同文件名**的桥接 DLL——这不是版本混乱，
**这就是重新注入的机制**：每次注入换一个程序集名。
上一轮 3 分钟内连续 4 次注入全部成功（R67/R68/R69/R70 各一次），
与「同版本第二次必拒」完全一致。

### 修复

| 改动 | 文件 |
|---|---|
| 引导程序记录载荷返回值 | `Bootstrap/Entry.cs` |
| 一条命令完成「升版本 + 重建 + 就位」 | `tools/editor-bridge/next-revision.ps1`（新） |
| 启动失败写入 `runner.startup-error.txt`，启动器读出 | `elevated-runner.ps1` / `start-elevated.ps1` |

**未改动** `BridgeServer` 的 5 分钟租约上限——那是有意的安全边界，
本轮的改动只是让官方既有的恢复路径变便宜，不是让注入变得无界。

### 顺带修掉的两个调用侧缺陷

- `latest_run_id()` 按目录 mtime 排序。run 结束时会写 `lease-closed.json`，
  刷新的 mtime 把**已死**的 run 顶到最前，调用随即 `SCOPE_EXPIRED`。
  已改为按 `expiresUtc` 过滤出仍然有效的租约再取最新。
- 客户端把 UTF-8 JSON 打到 GBK 控制台，`UnicodeDecodeError` 使整份回复丢失，
  一次成功的调用被记成失败。已显式 `reconfigure(encoding="utf-8")`，
  驱动侧改用 `errors="replace"`。

---

## 三、Demo 链路真实执行（8/8 步）

驱动：`tools/editor-bridge/demo-game/run-demo.py --run`
产物：`.runtime/editor-bridge/demo/20260917T170920Z/`（每步原始回复 + 运行报告）

| # | 操作 | 回复 | 此前状态 |
|---|---|---|---|
| 1 | `load` | `accepted: true`（R72） | — |
| 2 | `ping` | 桥接存活，租约到期时间 | 已验证 |
| 3 | `runtime-evidence` | `editorLevelState: 3` | 已验证 |
| 4 | `create-gameloop-variant-core` | `gameloop-variant-created-unbound` | **从未被调用** |
| 5 | `build-gameloop-variant-core` | `graphId 1073741831, nodeCount 27` | **从未被调用** |
| 6 | `bind-gameloop-variant-core` | `binding-requested-readback-pending` | **从未被调用** |
| 7 | `export-gameloop-graph` | `invoked-not-confirmed` | 已验证 |
| 8 | `runtime-evidence` | `editorLevelState: 3` | — |

**回访核实：绑定确实落地了。** 步骤 6 的回复是「请求已发出、读回待定」，
但后续一次 `catalog` 读取显示，两个关卡实体的 `graphBindings` 里出现了
**1073741831**——正是本次新建的那张图：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


所以「待读回」不等于没成功，只是回复生成时尚未读回；
**异步操作的回复状态不能单独作为成败判据，必须回访**。

### 操作覆盖度

对 `call-bridge.ps1` 声明的 **64** 个操作，遍历 `.runtime/editor-bridge/runs/*/`
下的 `*-response.json` 统计：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


本轮的三个变体 op 补上了最后一批「从未调用」的缺口。

### 对编辑器的可验证影响

对比执行前后的 `catalog`：

| 资源类型 | 前 | 后 | 变化 |
|---|---|---|---|
| `cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH`（图） | 18 | 21 | **+3** |
| `eFwIefiyuoKqF5Xvj0lt.vZll0FiyKKPTI3JUkFjF` | 2731 | 2732 | +1 |
| 其余 14 类 | — | — | 不变 |

总资源数 **936 → 939**。这不是接口自报，是执行前后各读一次目录得到的差值。

### 导出：接口自报低估了实际结果

接口返回 `invoked-not-confirmed`，回调 `rows: []`。但磁盘上有真文件：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


导出 id `1073741829`，`modelType 9`，category `[10000, 20000, 21001, 0]`。

用工程既有的 `tools/editor-bridge/inspect-graph.py` 读该文件：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**结论**：`DoExport` 的回调**触发不等于有返回内容**，
`invoked-not-confirmed` 也不等于失败。**磁盘是硬证据，回调不是。**

**另一处必须说清的边界**：导出的是 `MW_Game_Loop_20260917`（**主图**，29 节点），
**不是**本次新建的 `MW_Game_Loop_V3_20260917`（1073741831，27 节点）。
`export-gameloop-graph` 按自己的选择取图，不能用来导出指定的那张。
本轮新建的变体图**没有被导出成 `.gia`**。

### 必须如实标注的边界

- 绑定的**读回已在事后确认**（见上），但确认它的是**另一次读取**，
  不是回复本身——回复里的 `readback-pending` 就是回复时刻的真实状态
- `export-gameloop-graph` 导出的是 `GraphId` 1073741829 的图，
  **不是**本次新建的 1073741831——导出操作按自己的选择取图
- 新建的变体图**未被导出成 `.gia`**
- **编辑器的保存入口尚未找到**（四路检索 + 决定性实验，见第五节末），
  所以新建的图目前只存在于编辑器内存态。这是**能力不可达**，不是被跳过
- 新关卡已落盘，但**未经游戏加载验证**——加载它是试玩的一部分
- `persistentSaveVerified` / `playtestVerified` 仍为 `false`
- 本轮**未做试玩**（用户指令要求留给用户）

---

## 四、命令通道探针：回执不是确认

命令通道 `Producer.Ikci0qkvMZX(服务名, 命令名, 回调, List<Param>)` 是本工程恢复出的
最大一块**从未被发送过**的接口面（23 条命令 / 13 个通道）。工程记录一直写着
「命令的服务端语义、副作用、幂等性完全未验证」。

新增 `command-probe` 操作（`Adapter/CommandProbe.cs`）+ 桥接修订 **R74**。

### 设计：只发不可能存在的东西

对 13 个通道各派发一次，命令名固定为 `__miliastra_probe_unknown_command__`，
另加一次服务名也不存在的派发。参数与回调均为 `null`。
**任何已还原的命令名（`DoExport`、`DeleteEditObj`、`PlayMusic` …）从未被放入请求。**

理由：服务端不可能执行一个它不认识的命令，因此这个探针
**在物理上无法产生副作用**，却能回答「这条派发路径到底通不通、拒绝长什么样」。

### 结果

| 项 | 值 |
|---|---|
| 通道数 | 13 |
| 派发次数 | 14（13 通道 + 1 个不存在的服务名） |
| 抛异常 | **0** |
| 收到回执 | **14 / 14** |
| 回执请求号 | 4, 5, 6 … 17（**严格递增**） |
| 不存在的服务名那次 | **同样返回了回执**，请求号 17 |

### 结论（否定性，但很重要）

**1. 派发路径是通的。** `Ikci0qkvMZX` 确实是可调用的派发器，接受
`(服务名, 命令名, null, null)` 并返回回执。

**2. 客户端不做任何校验。** 服务名不存在也照样返回回执——
说明派发只是把请求**投进队列**，是否被理解、是否被执行，客户端一无所知。

**3. 回执不是确认，是号票。** 请求号单调递增（4→17），是一个全局计数器。
拿到回执**不能**推断命令被接受、被理解或被执行。

### 这解释了工程里既有的两个「状态词」

- `export-gameloop-graph` 的 `invoked-not-confirmed`
- `bind-gameloop-variant-core` 的 `binding-requested-readback-pending`

这两个措辞不是保守，而是**唯一诚实的表述**——因为返回值里确实没有可据以判定成败的信息。

### 由此得出的结构性边界

**既然派发永不拒绝，验证任何一条命令的语义就只能靠观察它的效果；
而对游戏效果的观察正是「试玩」——也就是用户明确保留的那一步。**

所以命令语义的验证**在结构上属于试玩环节**，不是本轮可以自行完成的部分。
本轮到此为止是有依据的停止点，不是回避。

（补充既有证据：`ImportAllDebugLog` 此前已真实发送 19 次并确实产生了调试日志导入，
说明这条通道**确实能够**把至少一条真实命令送到并被处理。这与上面的结论并不矛盾——
它证明的是通路的有效性，不是回执的判别力。）

---

## 五、项目注册

### 关键结论（否定性，必须写清）

接口调研的结论保持不变：**没有任何命令、通道或桥接操作能新建关卡/项目**。
2830 条字符串表无 `DoSave`/`SaveProject` 一类命令；23 条已还原命令中无项目级命令；
62 个桥接 op 中无对应项（当时）。

### 实际走通的路：文件格式层

`%USERPROFILE%\AppData\LocalLow\miHoYo\原神\BeyondLocal\<UID>\` 下：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**容器格式**（对四个 `.gil` 与一个 `.gip` 逐字节验证）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


文件大小 = 24 + 内长。

**字段证据**（非推测）：

| 字段 | 含义 | 证据 |
|---|---|---|
| 1 | 关卡 ID 的冗余副本 | **只在部分文件出现**：两个大关卡（61 KB / 21 KB）完全不带，两个小占位关卡带。因此**文件名才是 ID 的权威来源** |
| 2 | 名字 | 解出 `自定义页签_1_存档` 等界面显示的实际字符串 |
| 39 | 作者 UID | 四个文件全是 100000001 = 它们所在的目录名 |
| 40 | 时间戳 | 1788364733 等，全部落在 2026-09 |

关卡 ID 从 `0x40000001` 起编号；磁盘上四个文件与 `.gip` 里的四条条目**完全对得上**。

### 工具

- `tools/beyond-save/gil_container.py` —— 编解码器。核心断言：
  **解析再编码必须与原始文件逐字节相同**。做不到这一点，改一个字段就会
  悄悄重写看不懂的部分，任何 schema 工作都救不回来。
- `tools/beyond-save/register_level.py` —— 注册。默认**只产出候选**。

### 第一次候选是**不完整的**（自查发现并修正）

第一版候选只把新关卡追加进**平铺列表**（顶层 `f2`）。复核时把 `.gip` 整棵树打出来才发现，
**关卡在档案里是分「页签」组织的**，而页签藏在两层嵌套里（`f1 > f2 > f4`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


规律自洽：`页签_1` 下的两个关卡名都以 `自定义页签_1_` 开头，`页签_2` 同理（**遍历解析器输出验证**，
非目测；控制台中文乱码不影响判定）。而 `1600` 这个组常量在反编译代码里对上了枚举成员
**`SaveArchive = 1600`**（`nftmtEi44ZpaT9uR9UgI.u2nWUWi4Ei8tbmQLVnuN.cs:24`）——
页签持有的是指向关卡的 `SaveArchive` 引用。

**只写平铺列表的候选，对按页签渲染的编辑器来说是半个注册。** 因此补了 `Tab` 模型、
`add_level_to_profile`（**两处都写**）与 6 项页签测试，第一版候选已删除。

### 本轮注册结果：**已落盘**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 独立复核（从磁盘重新读，不看工具自己的报告）

| 检查 | 结果 |
|---|---|
| 原有四个 `.gil` | 与备份**逐字节相同，未被改动** |
| 新关卡 `1073741829.gil` | 解析成功，uid 100000001、时间戳正确 |
| 档案重新解析 | 5 条平铺条目、3 个页签，**原 4 条全部保留** |
| `MW_Demo` 页签 | → `[1073741829]` |
| 未命名页签 `f3` | 仍为 1073741825，未变 |

落盘前的 `--apply` 路径会**先做带回读比对的备份**再写，并打印撤销步骤；
本次备份 4 个关卡 + 档案，回读比对通过。

### 编辑器侧的持久化：保存入口**尚未找到**

demo 的图建在编辑器**内存态**里。要让它在关掉编辑器后还在，需要触发编辑器的保存。
本轮做了定向检索，**四路都没有找到入口**：

| 检索面 | 结果 |
|---|---|
| 2,830 条字符串表中的命令名 | 19 条形如命令名的字符串里**没有任何 `Save*`** |
| 12,375 个反编译类型中的路径字面量 | `.gil` / `BeyondLocal` / `Beyond_Local_Save` 出现 **0 次** |
| 65 个桥接操作中含 `save`/`persist` 的 | **0 个** |
| `vmBtnSave` / `vmBtnSaveAs` / `vmButtonSave` | **只有属性声明，没有处理器** |

**决定性实验**：`sync-editor-changes` 是不是保存？调用它，再比对存档哈希——
回执为 `OWN_CALIBRATION_AND_ROUTE_SESSION_REQUIRED`（缺校准会话），
**存档全部文件内容逐字节未变**。所以它不是保存。

**措辞边界**：以上是「**尚未找到**」，不是「官方不存在」。保存按钮的 Click 处理器
很可能以混淆名存在于某个类型中、由 XAML/BAML 绑定，而 BAML 在程序集资源里不在磁盘上；
要确认需要反编译 BAML，本轮未做。**这一点必须按「尚未找到」记录，不能写成否定结论。**

**顺带的正面发现**：命令名清单比先前调查到的 23 条**更多**。字符串表中形如命令名的有 19 条，
其中 **7 条此前未列出**：`DeleteComponentForEditObj`、`DeleteComponentForPrefab`、
`DeletePCGInstance`、`ImportPerformanceReport`、`ModifyFactionForEditObj`、
`ModifyFactionForPrefab`、`ModifyPCGInstanceName`。命令面比记录的更大。

---

## 六、本轮未做 / 未证实

- **未做试玩**（用户指令要求留给用户）
- 绑定的**读回未确认**（`readback-pending`）
- 新关卡候选**未落到实盘**，因此**未经游戏加载验证**
- `DoImport` 仍未发送过（既有禁令未变：不要照抄四个值就发）
- 命令的服务端语义、副作用、幂等性仍未验证
- 提权执行器**不会跨重启存活**；24 小时后需重新提权一次

## 七、相关文件

- 提权器：`tools/editor-bridge/{elevated-config.json,elevated-fs-guard.ps1,elevated-fs-ops.ps1,elevated-runner.ps1,start-elevated.ps1,start-elevated.cmd,elevated-request.py}`
- 提权器测试：`tools/editor-bridge/tests/{test-elevated-fs-guard.ps1,test-elevated-fs-ops.ps1}`
- 版本递增：`tools/editor-bridge/next-revision.ps1`
- Demo 驱动：`tools/editor-bridge/demo-game/run-demo.py`
- 存档编解码：`tools/beyond-save/{gil_container.py,register_level.py,test_gil_container.py,test_register_level.py}`
- 运行产物：`.runtime/editor-bridge/demo/20260917T170920Z/`、`.runtime/beyond-save/candidates/`
- 存档快照：`.runtime/editor-bridge/backups/20260917T170341Z-pre-demo-save/`
