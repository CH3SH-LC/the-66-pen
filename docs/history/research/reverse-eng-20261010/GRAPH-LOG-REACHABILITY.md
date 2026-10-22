> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 图日志 op 到不到得了队列（GRAPH-LOG-REACHABILITY）— 一次类级复核

写于 2026-10-10。**全部为静态/只读复核**：未连桥、未发任何报文、未触碰游戏/编辑器、未编译、未注入、
未重启 helper、未请求 UAC、未读任何图片。所有行号都是**本次 checkout 实测**（`file:line`），
凡与旧文档行号不符处已在 §6 写明漂移。

**为什么写这份**：姊妹文件 `GRAPH-LOG-NEXT-STEP.md` / `GRAPH-LOG-SHAPE.md` 把 `start-log-observer` 等
一族 op 当成**运行态验证的唯一通道**。但 wave11/13 的教训是：**op 被编译进去 ≠ op 到得了**——
队列（client + runner）用**闭集**清洗字段，一个 op 需要某个请求字段而队列载不动它，它就在结构上跑不了
（`inspect-entity-components` 的 `entityId` 是第一个样本，见 `docs/gameplan/UNREACHABLE-OPS.md`）。
本文件按**同一套三关检查法**（client → runner → 桥）逐个复核**日志族 5 个 op**是否需要字段、
字段到不到得了，并给判决。

**与既有文档的关系**：`UNREACHABLE-OPS.md` 算的是**全 op 面**里卡在字段断链上的有几个；本文件只算
**日志这一族**，回答「运行态验证这条路，从队列出发，今天开不开」。

---

## 0. 结论摘要

| 事实 | 值 |
|---|---|
| 日志族 op（本次复核） | **5 个**：`request-debug-logs` / `enable-own-graph-logging` / `start-log-observer` / `log-observer-evidence` / `stop-log-observer` |
| 同族旁观 op（顺带核对） | **3 个**：`enable-debug-logging` / `start-external-asset-observer` / `external-asset-evidence` |
| 这 5+3 个 op **需要 `id`/`op`/`nonce` 以外字段**的 | **0 个**（桥全部零参调用，§2） |
| client 构造不出的字段 | **0 个**（无 op 需要额外 flag，§3.1） |
| runner 闭集拒掉的字段 | **0 个**（无额外字段可拒，§3.2） |
| 桥缺 `case` 的 op | **0 个**（§3.3） |
| **到得了队列的日志 op** | **5 / 5 全部** |
| **需要 `entityId` 那种「plumbing surgery」的** | **0 个** |
| 真机上跑过的凭据（回执份数，`.runtime/editor-bridge/runs/`） | `log-observer-evidence` ×41、`start-log-observer` ×30、`stop-log-observer` ×26、`request-debug-logs` ×23、`start-external-asset-observer` ×16、`enable-own-graph-logging` ×5 |

一句纪律：**「到得了队列」只证明**「请求能送到桥面前」，**不证明**「送回来的证据够用」。
本文件判的是**前者**（贯穿 `UNREACHABLE-OPS.md` 的口径）；后者（证据载荷够不够）是**读侧代码**问题，
**不是队列问题**——见 §4.3，两者别混。

---

## 1. 三条通路（沿用 `UNREACHABLE-OPS.md` §1）

日志族 op **全部**是 `call-bridge.ps1` 的 `ValidateSet` 成员（`call-bridge.ps1:1`），因此它们**只走 call 通路**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


author-graph 通路只放行 `author-graph`/`catalog`（`graph-transport.ps1:48` 的 `OP_NOT_ALLOWED`），
native-scene 通路不碰桥管道。**日志族不在那两条路上**，也不需要。

---

## 2. 每个 op 需要什么字段（任务问题 1）

### 2.1 桥侧：派发点与调用点

`BridgeServer.cs` 用 `var op = ReadString(root, "op")`（`:254`）取 op，先校验 `nonce`（`:250`），
再按 `switch(op)`（`:255`）分派。日志族落在**同一个大 case 组**（组内 case 列于 `:440-527`），
其**共享执行体**在 `:528-654`。**该执行体对日志 op 不读任何请求体字段**——组内唯一读请求体的是
两个 client-script-file op 的 `relativePath`（`:532` 里 `EditorAdapter.ReadClientScriptRelativePath(root)`）。
日志 op 的调用点**零参**：

| op | `BridgeServer.cs` case | 调用点（同文件） | 传给 adapter 的实参 |
|---|---|---|---|
| `request-debug-logs` | `:452` | `:610` `_adapter.RequestDebugLogs()` | 无 |
| `enable-own-graph-logging` | `:454` | `:612` `_adapter.EnableOwnGraphLogging()` | 无 |
| `start-log-observer` | `:507` | `:632` `_adapter.StartLogObserver()` | 无（adapter 默认 `seconds=25`） |
| `log-observer-evidence` | `:508` | `:633` `_adapter.LogObserverEvidence()` | 无 |
| `stop-log-observer` | `:509` | `:634` `_adapter.StopLogObserver()` | 无 |
| *(旁观)* `enable-debug-logging` | `:453` | `:611` | 无 |
| *(旁观)* `start-external-asset-observer` | `:504` | `:629` `_adapter.StartExternalAssetObserver()` | 无（→ 内部 `StartLogObserver(120)`） |
| *(旁观)* `external-asset-evidence` | `:506` | `:631` | 无 |

### 2.2 adapter 侧：方法签名（全部零 request-body 依赖）

| op | `EditorAdapter.cs` 签名 | 备注（运行时前置，非队列字段） |
|---|---|---|
| `enable-own-graph-logging` | `:473` `EnableOwnGraphLogging() => EnableDebugLoggingCore(true)`；体在 `:474-502` | `:477` 无活动观察器即抛 `NO_ACTIVE_LOG_OBSERVER`；`:476` 一次性 `LOG_ENABLE_ALREADY_ATTEMPTED` |
| `request-debug-logs` | `:503-527` `RequestDebugLogs()` | `:506` 无日志接收者且无观察器即抛 `NO_LOG_RECEIVER_PRESENT`；`:505` 一次性 `LOG_REQUEST_ALREADY_ATTEMPTED` |
| `start-log-observer` | `:288` `StartLogObserver(int seconds=25)` | `:291` 只收 25/120（队列恒传 25）；`:292` 一次性 `OBSERVER_ALREADY_ATTEMPTED` |
| `log-observer-evidence` | `:414` `LogObserverEvidence()` | 纯读，无闸 |
| `stop-log-observer` | `:434` `StopLogObserver() => StopLogObserver("explicit-stop")` | 纯读/清理，无闸 |

> **关键**：这 5 个方法**没有一个是「吃请求字段」的**。对比 `EntityComponentProbe(root)`（吃 `entityId`，
> `BridgeServer.cs:311-314`）——日志族**结构上没有可被队列掐断的字段**。
> （§2.2 的运行时前置——「先开观察器」「每次修订一次性」——是**执行顺序/修订**约束，**不是**队列能否送达的约束，见 §4.2。）

---

## 3. 三关逐 op 判决（任务问题 2）

`client` = `elevated-request.py call`；`runner` = `elevated-runner.ps1` 的 `Get-ValidatedCallArguments`（`:221`）+ op 白名单（`:902-903`）。

### 3.1 client 关

`call` 子命令参数块在 `elevated-request.py:510-546`；`--op` 在 `:511`（**必填，无 `ValidateSet`**）。
op 专属 flag 只有四个，且**日志族一个都不需要**：
`--ids`（`:533`）、`--relative-path`（`:536`）、`--tag-*`（`:537-542`）、`--entity-id`（`:545`）。
四个校验函数在**缺 flag 时全部早返回 `{}`**：`validate_call_ids`（`:161-175`）、
`validate_call_relative_path`（`:178-189`）、`validate_call_tags`（`:192-217`）、
`validate_call_entity_id`（`:220-236`）。请求体在 `:610` 组装成 `{"kind":"call","runId":…,"op":…}`。

⇒ 日志族**构造得出**，且**不夹带任何额外字段**。

### 3.2 runner 关

闭集默认允许字段 `@('kind','runId','op','ids')`（`elevated-runner.ps1:234`）；
未知字段在 `:249` 抛 `CALL_FIELD_NOT_ALLOWED:<name>`。
`ids` 只给 6 个 node-query op，其余带 `ids` 在 `:319` 抛 `IDS_NOT_ALLOWED`。
op 白名单**每请求现读** `call-bridge.ps1` 的 `ValidateSet`（`:902`，读取器 `Get-AllowedOps` `:123-129`），
不在即 `:903` 抛 `OP_NOT_ALLOWED`；通过则 `:907` `& $callScript @callArguments`。

⇒ 日志族**不带额外字段**（不触发 `:249`），且**都在 `ValidateSet` 里**（不触发 `:903`）。

### 3.3 桥关

见 §2.1：每个日志 op **都有 `case`**（`:452/454/507/508/509`）。**0 个死 op。**

### 3.4 判决表（op → 需要的字段 → client 能发? → runner 放行? → 判决）

行号均为本次 checkout 实测。

| op | 需要的字段（除 `id`/`op`/`nonce`） | client 能发? | runner 放行? | 判决 | 断点 |
|---|---|---|---|---|---|
| `request-debug-logs` | 无 | ✅（`--op` 即可，`:511`） | ✅ 默认闭集即够（`:234`），op 在 `ValidateSet`（`call-bridge.ps1:1`） | **REACHABLE** | — |
| `enable-own-graph-logging` | 无 | ✅（`:511`） | ✅（`:234` + `:903`） | **REACHABLE** | — |
| `start-log-observer` | 无 | ✅（`:511`） | ✅（`:234` + `:903`） | **REACHABLE**（**时长恒 25s**，见 §3.5） | — |
| `log-observer-evidence` | 无 | ✅（`:511`） | ✅（`:234` + `:903`） | **REACHABLE** | — |
| `stop-log-observer` | 无 | ✅（`:511`） | ✅（`:234` + `:903`） | **REACHABLE** | — |
| *(旁观)* `enable-debug-logging` | 无 | ✅ | ✅ | REACHABLE | — |
| *(旁观)* `start-external-asset-observer` | 无 | ✅ | ✅ | REACHABLE（**120s 形态**在此 op 下） | — |
| *(旁观)* `external-asset-evidence` | 无 | ✅ | ✅ | REACHABLE | — |

### 3.5 一个「形态」级限制（不构成 UNREACHABLE）

`start-log-observer` 的 adapter 方法签名 `StartLogObserver(int seconds=25)`（`EditorAdapter.cs:288`）
可收 25 或 120（`:291`），但**桥的调用点是零参**（`BridgeServer.cs:632`）⇒ 经队列的
`start-log-observer` **永远 25s**。要 120s **不是**「加 `--seconds`」——而是**换用另一个已在白名单的 op**
`start-external-asset-observer`（`:504` → `StartExternalAssetObserver()=>StartLogObserver(120)`，`EditorAdapter.cs:287`）。
⇒ **能力存在，只是挂在另一个 op 名下**；这不是 `describe --types` 那种「形态彻底不可达」，而是**「形态换 op 可达」**。
（`GRAPH-LOG-NEXT-STEP.md` §4.3 选 `start-external-asset-observer` 正是为此，且它会**避开** `logEnableAttempted` 一次闸。）

---

## 4. 判决与第一个动作（任务问题 3、4）

### 4.1 哪些到得了 TODAY、哪些要 plumbing

- **到得了 TODAY**：**全部 5 个**日志 op（+ 3 个旁观 op）。**无需任何 `entityId` 式改造。**
- **要 plumbing 的**：**0 个**。日志族的桥侧调用点**零参**，队列两端（client/runner）**本来就够用**——
  闭集 `@('kind','runId','op','ids')` 已覆盖它们所需的一切（它们什么都不额外需要）。
- **根因对照**：`inspect-entity-components` 卡住，是因为**桥要读一个字段（`entityId`）而队列载不动它**；
  日志族**没有任何这样一个字段**，所以**结构上不可能卡同一条链**。

### 4.2 别把「到得了」读成「够用」——三层分开标（`CLAUDE.md` §一.3）

| 层 | 日志族的状态 | 证据 |
|---|---|---|
| **文档写了什么** | 姊妹文件把日志族当作运行态验证的唯一通道 | `GRAPH-LOG-NEXT-STEP.md` §3 |
| **工具能做什么（队列可达）** | **5/5 到得了**；请求能送到桥面前并执行 | 本文件 §3.4 |
| **真机跑过什么** | 6 个 op **都留下过回执**（§0 表末行）；**但没有一次**把 `runtimeVerified` 翻 `true` | `.runtime/editor-bridge/runs/` 计数；`GRAPH-LOG-NEXT-STEP.md` §1.1 P4/P5 |

⇒ **队列这层是开的**。运行态验证这层**仍关着**，但**关口不在队列**，而在**读侧代码**：
`RunLogSample.cs` 的 `CaptureRunLogRecord`（`:38-79`）**不读记录自带的 proto-58 `graphId`**
（`GRAPH-LOG-NEXT-STEP.md` §2.2）。那是一次**改代码 → 编译 → `next-revision` → 重跑**的动作，
**不是**队列加字段的动作。**两条是不同车道，别混**。

运行时前置（会挡住「重跑」但挡不住「送达」）：
- `enable-own-graph-logging` 需先有活动观察器（`EditorAdapter.cs:477`），且每修订**一次性**（`:476`）；
- `request-debug-logs` 同理（`:505`/`:506`）；
- `start-log-observer` 每修订**一次性**（`:292`）。
⇒ 这三个**想在同一修订里第二次触发**都做不到——**要重来就得升级修订**（`next-revision.ps1`，`CLAUDE.md` §三）。

### 4.3 第一个具体命令

**队列形态**（与姊妹文件 §4.3 一致：只读观察、不碰一次性闸、120s 窗口）。**本会话不执行**（helper 有挂起的重启，见硬规则）。
`<RunId>` 必须是本会话 `load` 现取的，**不得复用旧轮**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- 第一条落点：`.runtime/editor-bridge/runs/<RunId>/start-external-asset-observer-response.json`；
  第二条落点：同名目录 `log-observer-evidence-response.json`（`call-bridge.ps1:55` 自动写）。
- 若坚持用任务点名的 5 个 op，等价序列是
  `start-log-observer`（25s）→ `log-observer-evidence` → `stop-log-observer`，**同样全部可达**，
  只是窗口短于一局试玩。
- **它今天能回答**：观察器是否挂上、收到哪些包种类、`ownMarkers` 里有没有我们自有的 marker 文本
  （=`LogObserverEvidence()` 现有字段，`EditorAdapter.cs:414-433`）。
- **它今天回答不了**：「这条记录是哪张图发的」——**要等 `RunLogSample.cs` 加宽读 proto-58 `graphId` 并过修订**（§4.2）。

**所以，对「运行态验证这条路开不开」的准确回答**：
**队列侧：开**（5/5 可达，本文件证明）。**证据侧：未开**（读侧缺字段，需另走编译/修订车道）。

---

## 5. 类级检查配方（下次改了日志族 op 面就跑这个）

1. **取 op 名单**：5 个日志 op 是否都在 `call-bridge.ps1:1` 的 `ValidateSet`？——不在即 `OP_NOT_ALLOWED`（`elevated-runner.ps1:903`）。
2. **对每个 op 问「除 `id`/`op`/`nonce` 外桥读不读字段」**：读 `BridgeServer.cs` 该 op 的 **调用点实参**
   （`:610-634` 一带）。**零参**即无队列断链候选；**有参**（如 `EntityComponentProbe(root)` `:314`）
   就去查 `EditorAdapter.cs` 里该参数从请求体哪个键来，再走三关。
3. **过三关**：client（`elevated-request.py:510-546` 有无对应 flag + 校验函数，`validate_call_*`）→
   runner（闭集 `:234` 含不含该键；`:249` 会不会抛 `CALL_FIELD_NOT_ALLOWED`）→ 桥（有无 `case`）。
4. **别忘换名可达**：某形态（如 120s）可能挂在**另一个已白名单的 op** 下（§3.5），**不必加 flag**。

---

## 6. 与既有文档的差异（漂移说明，仅供对齐，不改任何文件）

- **行号漂移**：`UNREACHABLE-OPS.md` 引的 `elevated-runner.ps1:221`（默认闭集）/`:228`（`CALL_FIELD_NOT_ALLOWED`）/
  `:278-285`（`ids`）/`:866-867`（op 现读），**在本次 checkout 分别是 `:234`/`:249`/`:319`/`:902-903`**——
  该文件之后被编辑过（约 +13 行）。**本文件一律引本次实测行号。**
- **`entityId` surgery 已落地**：`UNREACHABLE-OPS.md` §6.1 称 `inspect-entity-components` 是「唯一完全不可达」，
  但**本次 checkout 里 client 已有 `--entity-id`**（`elevated-request.py:545`，校验 `:220-236`），
  **runner 已为它窄化闭集**（`elevated-runner.ps1:243`、`:300-308`）。即该 doc 描述的**断链已被修**，
  且有回归测试 `tools/editor-bridge/tests/test_component_op_plumbing.py` 把三点都钉住。
  ⇒ 这也正是「plumbing surgery」的**模板**；**日志族不需要做这件事**。
- **本文件不主张**：不主张日志族能翻 `runtimeVerified`（不能，见 §4.2）；不主张 proto-58 语义（未证，见姊妹文件）。
  只主张**队列可达性**。

---

## 7. `notClaimed`

- 本轮**什么都没跑**：没有起 bridge、没有发任何原生/图/日志请求、没有开游戏或编辑器、
  没有读写任何存档、没有注入、**没有读任何图片**、**没有改任何代码或文件（只新增本文件）**。
- **没有**跑真机验证；§0 表末行的回执份数来自**既有** `.runtime/editor-bridge/runs/`（只读 `find`）。
  注：该类回执由 `call-bridge.ps1:55` 落盘，**无论**调用者是队列（`elevated-request.py call` 经 runner）
  还是**直接** `pwsh call-bridge.ps1`——故**回执份数只证明该 op 已编译且真机执行过，不单独证明它走过队列**。
  「到得了队列」这条结论的**承重证据是 §3 的三关静态复核**，回执只是旁证。
- **没有**主张「到得了队列」=「验证通过」=「够用」——三者三层分开标（§4.2）。
- **没有**声称 §4.3 的命令会成功或会翻任何 `*Verified` 标志。
- 未因本文件放宽任何拒绝：日志族**本来**不需字段，本文件**没有**主张给任何 op 加字段或放宽闭集。

---

## 8. 逐条引用（file:line）

**桥源码（`tools/editor-bridge/`）**
- `ManagedBridge/BridgeServer.cs:250`（`nonce` 校验）、`:254`（`op` 读取）、`:255`（`switch(op)`）、
  `:452`/`:454`/`:507`/`:508`/`:509`（日志族 `case`）、`:453`/`:504`/`:506`（旁观 `case`）、
  `:610`/`:612`/`:632`/`:633`/`:634`（调用点，零参）、`:611`/`:629`/`:631`（旁观调用点）、
  `:528-654`（共享执行体；`:532` 唯一读请求体的分支 = `relativePath`）、`:306-314`（对照：吃 `entityId` 的 op）
- `Adapter/EditorAdapter.cs:287`（`StartExternalAssetObserver()=>StartLogObserver(120)`）、
  `:288`（`StartLogObserver(int seconds=25)`）、`:291`（`INVALID_OBSERVER_DURATION`）、`:292`（`OBSERVER_ALREADY_ATTEMPTED`）、
  `:414-433`（`LogObserverEvidence`）、`:434`（`StopLogObserver`）、
  `:471`/`:476`/`:477`（enable 的一次闸/前置）、`:473-474`（`EnableOwnGraphLogging`/Core）、
  `:503-527`（`RequestDebugLogs`；`:505`/`:506` 闸/前置）、`:16`（`Param`）
- `call-bridge.ps1:1`（`ValidateSet` 含全部日志 op）、`:1-2`（参数块；`$EntityId` 仅服务 `inspect-entity-components`）、
  `:41-44`（`inspect-entity-components` 填 `entityId`；日志族**无任何**此类分支）

**队列（`tools/editor-bridge/`）**
- `elevated-runner.ps1:123-129`（`Get-AllowedOps` 现读 `call-bridge.ps1`）、`:129`（`$allowedOps = Get-AllowedOps`）、
  `:218`（`IDS_NOT_ALLOWED`）、`:221`（`Get-ValidatedCallArguments`）、`:234`（默认闭集）、`:235`（`relativePath` 加宽）、
  `:243`（`inspect-entity-components` 窄化）、`:249`（`CALL_FIELD_NOT_ALLOWED`）、`:319`（非 query op 带 `ids` 拒）、
  `:893`（`kind -eq 'call'`）、`:897`（校验）、`:902`（现读白名单）、`:903`（`OP_NOT_ALLOWED`）、`:907`（`& $callScript @callArguments`）
- `elevated-request.py:510-546`（`call` 参数块）、`:511`（`--op` 必填无白名单）、`:533`（`--ids`）、
  `:536`（`--relative-path`）、`:537-542`（tag 族）、`:545`（`--entity-id`）、
  `:161-175`/`:178-189`/`:192-217`/`:220-236`（四个 `validate_call_*`，缺 flag 早返回 `{}`）、`:610`（请求体组装）
- `tests/test_component_op_plumbing.py`（`entityId` plumbing 的回归模板，全套断言见其 docstring）

**真机回执计数（`.runtime/editor-bridge/runs/`，本文件只读 `find`）**
- `log-observer-evidence-response.json` ×41、`start-log-observer-response.json` ×30、
  `stop-log-observer-response.json` ×26、`request-debug-logs-response.json` ×23、
  `start-external-asset-observer-response.json` ×16、`enable-own-graph-logging-response.json` ×5

**姊妹 / 上游文件**
- `docs/gameplan/UNREACHABLE-OPS.md`（三关检查法 §1-§5；§6.1 `entityId` 断链——现已修，见本文件 §6）
- `docs/research/reverse-eng-20261010/GRAPH-LOG-NEXT-STEP.md`（§2.2 proto-58 未读、§4.1-4.3 下一步与命令、§1.1 P4/P5）
- `docs/research/reverse-eng-20261010/GRAPH-LOG-SHAPE.md`
- `CLAUDE.md` §一.3（三层分开标）、§三（一次性、修订、helper）

---

*本文件由 2026-10-10 会话从仓内桥源码、队列脚本与既有真机回执（Bash `grep`/`find`/`sed`/`wc`，非 Grep 工具）只读整理；
**未实现、未编译、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档、未读任何图片**。所有行号为本次 checkout 实测。
凡「到得了」均只指**队列可达**，不指**真机验证通过**；凡语义未证均写「未证/假设」。*
