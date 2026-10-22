> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #3 挖 — 用图日志把 `runtimeVerified` 从 `false` 变成 `true` 的可能路径

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档、未读任何图片**。
证据来源只有三处：① 仓内桥 C# 源码（`tools/editor-bridge/`）② `.runtime/` 里的**真实回执原件**（Bash `grep`/`find`/`cat`，**Grep 工具会静默跳过 `.runtime/`**，见 `CLAUDE.md` §一.2）③ 仓内研究文档。
**本文件只新增自身**，不改其它任何文件。

> 按 `CLAUDE.md` §一.3、§五：`文档写了什么` / `工具能做什么` / `真机验证过什么` 三层分开标。
> 姊妹文件 `GRAPH-LOG-SHAPE.md`（#4）讲**记录的字段形状**与**节点级判据**；本文件讲**这五个 op 本身、它们的真实回执、以及「这次跑的还是历史回放的」这个判别问题**。两者互补，不重复。

---

## 0. 一句话结论

- **这五个 op 是本仓唯一的「运行态观察」通道，形状完全对**：`enable-own-graph-logging`（发原生 3001，选中自有图）→ 人试玩 → `start-log-observer` 在编辑器进程内用 `DispatchProxy` 拦入站帧 → `request-debug-logs` 拉一次历史日志 → `log-observer-evidence` **回读出「哪个图打印了什么」**。它不是「另开一条连接」，而是挂在编辑器已有的包生产者上（`INTERFACE-INVENTORY.md:492-496`）。
- **真机回执确实存在**（不是我编的）：`.runtime/editor-bridge/runs/` 下 **41 份** `log-observer-evidence-response.json`、**8 份** `native-log-enable-requested`；其中有 run **确实收到了带图名与打印文本的结构化记录**（原件见 §3.3）。
- **但 `runtimeVerified` 一次都没被翻过**：全 `.runtime/editor-bridge/runs/` 检索范围内，
  `"runtimeVerified":true` / `"playtestVerified":true` / `"runtimeSemanticsVerified":true` **命中数 = 0**；
  `"acknowledged":true`（3001 被 ACK）**= 0**；`"debugLogRpcSuccess":true`（拉日志 RPC 成功）**= 0**；
  **非空的 `debugLogReply` = 0**（见 §3.4）。
- **两条硬阻塞（都有证据，都是负面成果）**：
  1. **`request-debug-logs` 这条「主动拉日志」的路从未返回任何内容** —— 19 次派发里 `debugLogReply` 恒为 `[]`、`debugLogRpcSuccess:false`。真正有内容的只有**被动观察器**接到的 **3002/3006 包**。
  2. **「按图身份把记录认回自己的图」从未成功** —— 位置图过滤要求记录名**精确等于**编辑器图名，真机保留数恒为 **0**（37 份记录）；真机记录里那个「名字」槽装的是**运行实例 id**（形如 `47504-100000001-1789563421-108742`），**不是**编辑器图名（原件见 §3.3；`GRAPH-LOG-SHAPE.md` §3.2 同结论）。
- **判定**：**当前这 5 个 op「按原样」跑，不能把「模型里有节点」变成「图确实执行了」。** 但它是**最接近闭环的一条通道**：只要补上「**一个在本会话新建、只用一次的 marker 串**」+「**负对照**」，它就能定案（§5 给出可执行、可反驳的实验；**本轮不执行**）。

---

## 1. 方法与本轮检索范围

- **源码**：`tools/editor-bridge/ManagedBridge/BridgeServer.cs`（op 标签与派发）、`tools/editor-bridge/Adapter/EditorAdapter.cs`（实现与 observability）、`Adapter/GraphLogSelection.cs`（3001 的图选择载荷）、`Adapter/RunLogSample.cs`、`Adapter/PositionLogs.cs`、`ManagedBridge/NativePacketObserverProxy.cs`、`Adapter/AdapterLease.cs`。
- **真机语料**：`.runtime/editor-bridge/runs/<RunId>/`（454 个 run 目录）。用 `find`/`grep` 定位回执，用 `cat` 引原件。**未用 Grep 工具**（它会跳过 `.runtime/`）。
- **先例台账**：`docs/editor-catalog/INTERFACE-INVENTORY.md` §4.7/§4.7.1/§5.5/§6.1、`docs/research/reverse-eng-20261010/GRAPH-LOG-SHAPE.md`、`docs/research/.../PLAYTEST-CONTROL-MINE.md` §3.1。
- **实验脚本**：`tools/editor-bridge/probe-log-observer.ps1`、`probe-runtime.ps1`、`call-bridge.ps1`、`load-bridge.ps1`。
- **负面结论的检索范围**：凡「=0」均写明是在 `.runtime/editor-bridge/runs/` 下 `grep -rl` 的结果。

---

## 2. 五个 op 逐条：做什么 / 收什么 / 返回什么（file:line）

标签注册都在 `BridgeServer.cs` 的 `case` 表；派发都在 `try` 块的 `dispatcher.InvokeAsync(...)`（`:512-513` 取 WPF dispatcher，`:630` 回写）。

### 2.1 `start-log-observer` — 在编辑器进程内挂一个包观察器（**唯一的实时观察手段**）

| 项 | 值 | file:line |
|---|---|---|
| 标签 | `case "start-log-observer":` | `BridgeServer.cs:489` |
| 派发 | `_adapter.StartLogObserver()` | `BridgeServer.cs:614` |
| 实现 | `public object StartLogObserver(int seconds=25)` | `EditorAdapter.cs:288-318` |
| 别名（120s） | `StartExternalAssetObserver()=>StartLogObserver(120)` | `EditorAdapter.cs:287`、标签 `:486`、派发 `:611` |
| 入参 | 只接受 **25 或 120** 秒，否则 `INVALID_OBSERVER_DURATION` | `EditorAdapter.cs:291` |
| 一次性 | 已起过再起 → `OBSERVER_ALREADY_ATTEMPTED` | `EditorAdapter.cs:292` |
| 前置 | 必须在 WPF dispatcher 上：`RequireInitDispatcher()` | `EditorAdapter.cs:290` |

**做了什么**（`EditorAdapter.cs:294-317`）：
1. 取活着的连接生产者单例 `ExistingSingleton(Editor(),Producer)`（`:294`），并读它的接收者列表 `Field(producer, B("EdBi0U13Ia7"))`（`:295`）。
2. **先核合同再注册**：目标接口必须是**单方法、返回 `void`**，否则 `OBSERVER_CONTRACT_CHANGED`（`:296-299`）。
3. `BeginLevelInitObservation(producer)`（`:300`）——顺带挂上包 **1022（关卡初始化）** 的观察器。
4. 用 `DispatchProxy.Create(contract, typeof(NativePacketObserverProxy))` 造一个假接收者（`:302-303`），`Receive=ObservePacket`（`:304`），经 `producer.hUBi0lBOqTW(proxy)` **注册进编辑器已有的接收链**（`:308`）。
5. 起一个 `DispatcherTimer`，租期到点自调 `StopLogObserver("observer-lease-expired")`（`:310-316`）。
6. **返回**：`LogObserverEvidence()`（`:317`）——即第一次证据体（此时计数全 0）。

**观察器收到什么**（`ObservePacket`，`EditorAdapter.cs:343-413`）：
- 只对**包号 3002/3006** 做记录扫描（`:379` `if(id!=3002 && id!=3006)return;`）；`observedLogPackets` 上限 32（`:381`）。
- 对每条 payload 做广度扫描：抽 `auditPrints`（`:393`）、`positionPrints`（`:394`）、`runLogSample`（经 `RunLogSample.cs`），并把 payload 里出现的 marker 串收进 `observedMarkers`（`:397-398`）。
- 另专收：`1017`（场景几何）、`1020`（外部资产）、`1019`（日志 RPC 答复）、`1015`（同步）、`1022`（关卡初始化，经 `ObserveLevelInitPacket`，`:346`）。

**客户端代理**（`NativePacketObserverProxy.cs:10-55`）：`DispatchProxy` 子类，`Invoke` 里计数 `CallbackInvocations`，**永不向编辑器抛异常**（`:52` catch 全吞，只 +`CallbackErrors`）；合同不符的调用计 `ContractRejectedCallbacks`（`:45-47`）。

### 2.2 `enable-own-graph-logging`（与 `enable-debug-logging`）— 发原生 3001，选中自有图

| 项 | 值 | file:line |
|---|---|---|
| 标签 | `case "enable-own-graph-logging":` / `case "enable-debug-logging":` | `BridgeServer.cs:436` / `:435` |
| 派发 | `_adapter.EnableOwnGraphLogging()` / `EnableDebugLogging()` | `BridgeServer.cs:594` / `:593` |
| 实现 | `EnableOwnGraphLogging()=>EnableDebugLoggingCore(true)`；`EnableDebugLogging()=>EnableDebugLoggingCore(false)` | `EditorAdapter.cs:473` / `:472` |
| 核心 | `EnableDebugLoggingCore(bool selectOwnGraphs)` | `EditorAdapter.cs:474-502` |
| 选择载荷 | `ConfigureOwnGraphLogSelection` / `BuildGraphLogSelection` | `GraphLogSelection.cs:43-79` / `:83-157` |

**前置与一次性**（`EditorAdapter.cs:476-484`）：
- **一次 session 只能发一次**：`logEnableAttempted`（`:476` `LOG_ENABLE_ALREADY_ATTEMPTED`）。
- **必须先起观察器**：`if(!observerActive) throw NO_ACTIVE_LOG_OBSERVER`（`:477`）。
- 连接必须就绪：`EDITOR_CONNECTION_NOT_READY`（`:479-484`）。

**做了什么**（`:486-498`）：造内层 `bNf3IEaS4GdguXca3eut`、调 `XwtaSuJH9gv(true)` 置启用（`:488-492`）；`selectOwnGraphs` 时调 `ConfigureOwnGraphLogSelection(inner)` 填 server 图列表（`:493`）；外层 `h0UaSTjlMFm(inner)`（`:490,494`）；**读回校验**（内层启用位 + 外层引用，`:495-496`）；发 `producer.PHCi086M7o5((ushort)3001, outer)`（`:498`）。

**返回体**（`:499-501`）：`status:"native-log-enable-requested"`, `messageId:3001`, `requestedEnabled:true`, `selectionSpecified`, `selectedServerGraphIds`, `selectedClientGraphIds:[]`, **`acknowledged:false`**, **`previousEnabledState:"unknown"`**, **`startsPlaytest:false`**。

**选择表**（`GraphLogSelection.cs`）：
- 常量：内层/外层/proto/枚举类型名与 getter/setter（`:22-31`）；`LogSelectionValue=1`（`:31`）、**server 上限 10**（`:32`）、**client 上限 99**（`:33`）、`LogSelectionGraphCategory=21001`（`:34`）。
- `ConfigureOwnGraphLogSelection`（`:43-79`）：**必需** calibration(7 节点)/tiled(39)（`:48-49`）；**可选** audit(13)/position(16)/finish(23)（`:50-52`）。名字不唯一 / category≠21001 / 节点数不符 → 抛（`:63-70`）。
- `BuildGraphLogSelection`（`:83-157`）：要求两列表**真空**（`:100-101`）；每条 proto = `{value:enum(1), graphId}`（`:113-119`）；**server 只放、client 必须仍空**（`:123-126`）；**逐条读回比对**（`:128-138`）。返回体自报 `status:"log-selection-payload-built-not-sent"`、`sent:false`、`enableFlagUnchanged:true`（`:140-156`）。

### 2.3 `request-debug-logs` — 主动拉一次历史日志（**这条从未返回内容**）

| 项 | 值 | file:line |
|---|---|---|
| 标签 / 派发 | `case "request-debug-logs":` / `_adapter.RequestDebugLogs()` | `BridgeServer.cs:434` / `:592` |
| 实现 | `public object RequestDebugLogs()` | `EditorAdapter.cs:503-527` |
| 前置 | 一次性 `logRequestAttempted`（`:505`）；需「已有日志模型 **或** 观察器活着」（`:506` `NO_LOG_RECEIVER_PRESENT`） |
| 动作 | `producer.Ikci0qkvMZX("beyondExportService","ImportAllDebugLog", callback, null)` | `EditorAdapter.cs:509-515` |
| 回调 | `ReceiveDebugLogReply<T>`（收包 1019） | `EditorAdapter.cs:460-470`（经 `EditorAdapter.cs:363` `CaptureDebugLogRpcReply`） |
| 请求号 | 取自回执字段 `dJVi0tPDg6E`，必须非 0 | `EditorAdapter.cs:517-518` |
| 清理 | 30 s `DispatcherTimer` 删回执 | `EditorAdapter.cs:520-525` |
| 返回 | `status:"debug-log-refresh-requested"`, `startsPlaytest:false` | `EditorAdapter.cs:526` |

`EditorAdapter.cs:508` 注明：这是**精确的原生 `XlouvVFL1Yn` 形状**——**无路径、无参数、不切换运行态**。

### 2.4 `log-observer-evidence` — 只读回读观察结果（**「哪个节点跑了」的读出口**）

| 项 | 值 | file:line |
|---|---|---|
| 标签 / 派发 | `case "log-observer-evidence":` / `_adapter.LogObserverEvidence()` | `BridgeServer.cs:490` / `:615` |
| 实现 | `public object LogObserverEvidence()` | `EditorAdapter.cs:414-433` |

**返回字段**（`:417-432`，挑关键）：
`active`、`observedPackets`、`observedLogPackets`、`ownMarkers`、`packetKinds`（**各包号计数**）、`observerScanObjects`、`observerScanLimited`、
`runLogSample`（`:421` → `RunLogSample.cs:81-92`，含**图名 + 正文类型 + 可能读出的正文文本**）、
`auditPrints`、`positionPrints`、`structuredPositionLogs`、`positionCapture`、
`levelInitialization`（包 1022 观察）、`componentGeometry`（包 1017）、`externalAssets`（包 1020）、
**`persistentSaveVerified:false`**、**`playtestVerified:false`**、`notice`（`:432`）。

### 2.5 `stop-log-observer` — 反注册（显式、租期到点、或会话收尾都会调）

| 项 | 值 | file:line |
|---|---|---|
| 标签 / 派发 | `case "stop-log-observer":` / `_adapter.StopLogObserver()` | `BridgeServer.cs:491` / `:616` |
| 实现 | `StopLogObserver()=>StopLogObserver("explicit-stop")`；`StopLogObserver(string reason)` | `EditorAdapter.cs:434` / `:435-459` |
| 反注册 | `producer.MsOi0h1OdBN(proxy)` + 从 `EdBi0U13Ia7` 摘除 + 从 deferred 列表摘除 | `EditorAdapter.cs:447-450` |
| 会话收尾也调 | `AdapterLease.cs:11` `CleanupForLease()` → `:21` `StopLogObserver("bridge-lease-cleanup")` | `AdapterLease.cs:21` |
| 返回 | 再次 `LogObserverEvidence()`（：`active:false`，但计数保留） | `EditorAdapter.cs:458` |

### 2.6 它们**不是**「试玩控制」（写死，防误读）

- 3001 只是**日志启用**，`acknowledged=false`，返回体硬写 `startsPlaytest=false`（`EditorAdapter.cs:501`、`:526`；`INTERFACE-INVENTORY.md:144,351`）。
- `PLAYTEST-CONTROL-MINE.md` §3.1 已逐条否掉 `enable-debug-logging`/`request-debug-logs`/`sync-editor-changes`/`command-probe` 是「起停试玩」。
- ⇒ **本通道只「看」，不「起」**。要人**手工**进试玩（或另找 UI 入口）才有东西可看。

---

## 3. `.runtime/` 里的**真实回执**（原件引用，有就是有、没有就是没有）

### 3.1 找到了什么

| 产物 | 数量 | 检索范围 |
|---|---:|---|
| `log-observer-evidence-response.json` | **41** | `find .runtime/editor-bridge/runs -maxdepth 2 -name log-observer-evidence-response.json` |
| `native-log-enable-requested` 回执文件 | **8** | `grep -rl 'native-log-enable-requested' .runtime/editor-bridge/runs` |
| `enable-own-graph-logging-response.json` | **5** | `find … -name "enable-own-graph-logging-response.json"`（另有 `enable-debug-logging-response.json` 5） |
| `request-debug-logs-response.json` | **23** | `find … -name "request-debug-logs-response.json"` |
| 含**非空 `ownMarkers`**（`["MW…`）的文件 | **45** | `grep -rl '"ownMarkers":\["MW' .runtime/editor-bridge/runs` |

### 3.2 引一条**完整的真实回执**（run `624057f7-7e2a-40f8-b896-470ceabb7547`）

路径前缀 `.runtime/editor-bridge/runs/624057f7-7e2a-40f8-b896-470ceabb7547/`：

- `enable-own-graph-logging-response.json`（逐字）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- `request-debug-logs-response.json`：`{"ok":true,"status":"debug-log-refresh-requested","startsPlaytest":false}`
- `observer-ten-seconds.json`（逐字，节选关键字段）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- 同 run 的 `user-playtest-feedback.json`（**人证**，非机器证）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


> **读这条原件得到的三个硬事实**：① 3001 **发了**、**没被 ACK**（`acknowledged:false`）；② 「主动拉日志」RPC 回执 `debugLogReply` **是空的**、`debugLogRpcSuccess:false`；③ 有内容的只是**被动观察器**接到的 **2 个 3006 包**，从中读到 2 个 marker。**人证说试玩里看得到平台，但机器证据里没有任何一条能把那 2 个 marker 钉在「这次试玩」上。**

### 3.3 引**真机结构化记录**（run `10f68791-3a17-4cc9-ae11-e47ed9e81633`，`log-observer-evidence-response.json` 的 `runLogSample.sample`，逐字节选）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


同 run：`observedLogPackets:5`、`packetKinds:{"0":9,"3006":5,"1018":1,"1019":1}`、`ownMarkers` 含**四个** marker（calibration / tiled / finish-monitor / finish-reached）、`recordsSeen:83`、`sampleLimited:true`。

> **读这条原件得到的硬事实**：通道**能**把「**图名** + **打印出的文本/数值**」交给观察者——**形状上正是「哪个节点跑了」所需**（`GRAPH-LOG-SHAPE.md` §4.2）。**但**：① 这里的 `graphName` 是**运行实例 id**，不是编辑器图名；② 每一行的 `runtimeSemanticsVerified` 都是 `false`；③ `runLogSample.notice` 自陈「**只证明收到、不证明这次跑了**」。

### 3.4 负样本（同一证据面里的反面原件）

| run | 场景 | 结果（逐字要点） |
|---|---|---|
| `f7d6e439-27a7-454e-8b08-ec1d5d7808c9` | 选了 3 张图（`[1073741825,1073741827,1073741828]`） | `observer-ten-seconds.json`：`observedLogPackets:0`、`ownMarkers:[]`；`root-log-selection-verification.json`：`requestAcknowledged:false, logPackets:0, runtimeVerified:false` |
| `154fa209-779d-4b87-846c-ae741e9a1e44` | **人已进试玩**（`user-playtest-feedback.json`："已进入试玩，看到新立方体"） | `observer-ten-seconds.json`：`observedLogPackets:0`、`ownMarkers:[]`、`debugLogReply:[]`；反馈文件自陈 `automatedRuntimeMarkerVerified:false` |
| `a59ea1c8-1d63-4e6f-afad-39d0d52e8505` | 图身份检查 | `probe-error.json`：`LOG_SELECTION_GRAPH_IDENTITY_NOT_UNIQUE:MW_Route_Tiled_20260916:0` |

**全 `.runtime/editor-bridge/runs/` 检索（`grep -rl`）命中数为 0 的四条**：
`"acknowledged":true`、`"debugLogRpcSuccess":true`、非空 `"debugLogReply":[{`、`"runtimeVerified":true`（及 `"playtestVerified":true`、`"runtimeSemanticsVerified":true`）。
⇒ **3001 从未被确认；主动拉日志从未成功；失败标记从未被翻过。**

---

## 4. 关键判别：这些记录是「**这次**跑出来的」还是「**历史缓存回放**」？

这是决定「能不能翻 `runtimeVerified`」的唯一关键，必须说清**知道什么、不知道什么**。

### 4.1 `graphName` 里那串数字**是图身份、不是打印时刻**（更正一个想当然的读法）

`graphName` 形如 `47504-100000001-<uint>-<n>`。取 §3.3 里出现过的后一段（Unix 秒）：

| 段值 | UTC 时刻 |
|---:|---|
| 1789551663 | 2026-09-16 09:41:03 |
| 1789552405 | 2026-09-16 09:53:25 |
| 1789563421 | 2026-09-16 12:57:01 |
| 1789569175 | 2026-09-16 14:32:55 |
| 1789570894 | 2026-09-16 15:01:34 |

捕获发生在 **2026-09-28T14:18:48–50**。**段值是 09-16、捕获是 09-28** ⇒ 段值是**稳定的图身份（含着建图时刻）**，
**不是**「这条记录是什么时候打的」。**所以「时间戳旧」本身不能证明记录是历史回放**——这是一个**必须纠正的过度解读**。
但反过来：它**同样不能证明这次跑过**。**该字段对「liveness」是中性的。**

### 4.2 跨 11 天、同一组四 marker（可疑，但不能定案）

含 **finish 两个 marker** 的 run 出现在 **09-17（`3c63e9ac`）/ 09-27（`53509573`）/ 09-28（`ea8f9136`、`10f68791`）**，
且这几次的 `packetKinds` 形状高度一致（都是 `3006:5` + `1018:1` + `1019:1`）。
「同一组固定内容、跨多会话重复出现」既可用**历史缓冲回放**解释，也可用**「关卡一加载就把同一批图重跑一遍」**解释——**两者都能让同一组 marker 反复出现**。
⇒ **本轮证据不足以二选一。**

### 4.3 代码自己**拒绝**提升（这是设计上的诚实，也是当下的天花板）

- `RunLogSample.cs:77` 每行硬写 `runtimeSemanticsVerified = false`；`:89` 整体再写一次 `false`。
- `RunLogSample.cs:90-91` 的 `notice`：*a captured row proves a record was RECEIVED … it does NOT prove … that a graph executed in this session*。
- `LogObserverEvidence` 每次返回 `playtestVerified:false`（`EditorAdapter.cs:431`）。
- `RuntimeEvidence` 每次返回 `playtestVerified:false` 且 `notice:"…existing editor log cache only."`（`EditorAdapter.cs:271`）。

⇒ **桥作者对「收到 ≠ 执行」这一点是自觉的**：`runtimeVerified` 全仓恒 `false`，**不是漏实现，是刻意的保守断言**。

### 4.4 §4 小结

**能确定的**：通道能收到「图名 + 打印文本」结构记录；`request-debug-logs` 从不返回内容；从未有记录被认回**我们自己的编辑器图名**（`positionPrints` 恒 0；`GRAPH-LOG-SHAPE.md` §3.2）。
**不能确定的**：这批记录是本次跑的还是历史缓冲。
⇒ **在补上「判据」之前，这条通道无法单独把 `runtimeVerified` 从 `false` 变 `true`。**

---

## 5. 判定 + 能定案的最小实验（**离线计划，本轮不执行**）

### 5.1 直接回答任务的问题

> **「enable 日志 → 人玩 → 拉日志 → 读哪些节点触发了」这条序列，能不能把「模型里有节点」变成「图确实执行了」？**

**按原样跑：不能。** 证据：
1. 这条序列**已经被跑了 41 次**（41 份 `log-observer-evidence-response.json`），`runtimeVerified` **一次没翻**。
2. 「拉日志」那一步（`request-debug-logs`）**19 次派发全部返回空**（§3.4）。
3. 「读哪些节点」那一步**认不回自己的图**：位置图精确名匹配**恒 0**（§3.2、§4.4）。
4. 唯一「人确实进了试玩」的 run（`154fa209`）在观察窗口里**收到 0 个日志包**（§3.4）。

**但换个判据就能定案**：不靠「图名认领」，改靠「**本会话新建、只用一次的 marker 串**」——一段唯一文本只属于一个节点，
抓到它就等价于那个节点执行了（`GRAPH-LOG-SHAPE.md` §4.2 已把这条判据写全）。再配一个**负对照**，就能把 §4.2 的「历史回放 vs 本次重跑」劈开。

### 5.2 前置（不改既有图，只读确认）

1. `gameplan live` / `discover_current_level` 取**当次**回执里的 levelId（**禁止复制上一轮**；`CLAUDE.md` §四）。
2. `inspect` 只读确认：目标图在、节点数**精确等于**选择表要求、category[2]==21001（`GraphLogSelection.cs:63-70` 会校验）。
3. **本会话新建**一张（或改用已有未被占用的）图，节点里放**一个 `def1 打印字符串`**，文本用**此前从未出现过**的唯一串
   （例：`MW_RTV_20261010_<6位随机>`）；把它**加进 `ConfigureOwnGraphLogSelection` 的必需项**（`GraphLogSelection.cs:48-53`；现有必需只有 calibration/tiled）。
4. 该图**绑到关卡实体**（`bind-*-graph`），或至少确认触发链必经它。

### 5.3 准确的命令序列（人 + 脚本，**离线计划**）

**通道约束（三条，先记住）**：① `logEnableAttempted` / `logRequestAttempted` 是**每桥实例一次性**（`EditorAdapter.cs:476,505`）⇒ **一个 scope 只能跑一轮**；② 观察器租期只接受 **25 或 120 秒**（`EditorAdapter.cs:291`）；③ scope 租约 **5 分钟**（`CLAUDE.md` §三）。

**方案 A：手工逐条（窗口=120s，够人进试玩）**

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**方案 B：现成一次性包装（窗口=25s，须在 25s 内完成试玩触发）**
`tools/editor-bridge/probe-log-observer.ps1 -RunId <GUID> -EnableOwnGraphs`
（其内部顺序即 `start-log-observer` → `enable-own-graph-logging` → `request-debug-logs` → sleep 10 → `log-observer-evidence` → sleep 17 → 再回读；见 `probe-log-observer.ps1:16-24`。**25s 对人太短，实操建议用方案 A 的 120s。**）

**产物落点**：`.runtime/editor-bridge/runs/<RunId>/log-observer-evidence-response.json`（`call-bridge.ps1` 自动写）。

### 5.4 判据（**三个都要落盘**，缺一不定案）

| 判据 | 通过标准 | 为什么 |
|---|---|---|
| **D1 唯一 marker** | 该串**只属于一个节点**、**本会话首次使用**、**编辑器图名核对无歧义** | 记录里**没有节点 id**（`GRAPH-LOG-SHAPE.md` §2），只能靠文本唯一性反推节点 |
| **D2 阳性** | `runLogSample.sample` / `ownMarkers` 里出现该串，且其 `observedUtc` **晚于试玩开始**（观察器 `observerTiming.startedUtc` 之后的窗口内） | 「收到」还须落在**本次窗口** |
| **D3 负对照** | **同一条序列**再跑一次，但**该图不绑 / 不进试玩** ⇒ 该串**必须不出现** | **这是唯一能把 §4.2「历史回放 vs 本次重跑」劈开的手段**：若「跑」与「不跑」都出串，则串来自缓冲，**不可作运行证据** |
| **D4 旁证（可选）** | `levelInitialization`（包 1022）在试玩进入时记一次 init；`observerTiming.lastCallbackUtc` 落在窗口内 | 交叉印证「试玩确实发生」 |

**只有 `D2 ∧ ¬反例（D3）` 成立，才允许把该图/该节点的 `runtimeVerified` 标 `true`。** 仅 `D2` 成立**不足以**——那正是过去 41 次里的情形。

### 5.5 若要一次做扎实，还需补的一处代码（**只写形状，不改**）

`positionPrints` 恒 0 的根因是**身份判据错**：`PositionLogs.cs:21` 要求记录名**精确等于**编辑器图名（`MW_Character_Position_20260916`），
而真机记录的名字槽装的是**运行实例 id**。**要么**先把「我们的图在记录里叫什么」探明（读 proto 58 的 `(enum, graphId)` 子消息，`GRAPH-LOG-SHAPE.md` §1.3 已定位该字段），**要么**放弃按图名认领、**一律靠 D1 的文本唯一性**。**没有这一步，D2 只能靠 `ownMarkers`（文本命中）而不能靠 `runLogSample.graphName`。**

---

## 6. 负结论（本文件真正交付的东西）

1. **这 5 个 op 不是「试玩控制」**：`startsPlaytest=false` 是源码里**刻意**写下的断言（`EditorAdapter.cs:501,526`）；3001 只启用日志。
2. **`request-debug-logs`（主动拉日志）从未返回内容**：`.runtime/editor-bridge/runs` 内 `"debugLogRpcSuccess":true` = 0、非空 `debugLogReply` = 0。**有内容的只有被动观察器接到的 3002/3006 包。**
3. **3001 从未被 ACK**：`"acknowledged":true` 全检索 = 0（`acknowledged:false` 是**回执常态**，不是本次失败）。
4. **「按图名认回自己的图」从未成功**：`positionPrints` 恒 0；真机记录名字槽是**运行实例 id**，不是编辑器图名（§3.3）。
5. **`runtimeVerified`/`playtestVerified` 全仓恒 `false`**，且**没有任何一次**真机回执把它翻过（检索命中 = 0）——这是**设计选择**，不是遗漏。
6. **唯一「人确实进试玩」的 run（`154fa209`）在观察窗口收到 0 日志包** ⇒ 该通道**未证明能捕获一次新鲜试玩的实时打印**。
7. **因此**：现有 5 op **按原样**跑**不能**关闭 GOAL 的「试玩→反馈」回路；**能**的是它的**形状**——补上「唯一 marker + 负对照」（§5）后，它**有资格**成为继 `playtest.control` 缺位后的**唯一可执行的运行验证通道**。**本轮不执行该实验。**

---

## 7. 逐条引用（file:line）

- **op 标签**：`tools/editor-bridge/ManagedBridge/BridgeServer.cs:434,435,436,489,490,491`；**派发**：`:592,593,594,614,615,616`；dispatcher：`:512-513,630`。
- **实现**：`Adapter/EditorAdapter.cs:287,288-318`（start）、`:343-413`（ObservePacket，`:379` 只认 3002/3006，`:397` marker 表）、`:414-433`（evidence）、`:434-459`（stop）、`:460-470`（reply 回调）、`:472-502`（enable，`:476,477,479-484,488-501`）、`:503-527`（request，`:505,506,509-515,517,518,520-526`）、`:221-226`（ExistingLogModel）、`:227-272`（RuntimeEvidence，`:271`）。
- **选择表**：`Adapter/GraphLogSelection.cs:19-34,43-79,83-157,160-173,176-183`。
- **记录读法**：`Adapter/RunLogSample.cs:22-93`（`:24,30-34,38-79,77,88,89,90-91`）；`Adapter/PositionLogs.cs:9-32`（`:21` 名匹配）；`ManagedBridge/NativePacketObserverProxy.cs:10-55`；`Adapter/AdapterLease.cs:11,21`。
- **真机原件**（`.runtime/editor-bridge/runs/` 下，本文件 `cat` 过）：
  `624057f7-7e2a-40f8-b896-470ceabb7547/{enable-own-graph-logging-response,request-debug-logs-response,observer-ten-seconds,log-observer-evidence-response,runtime-before-observer,user-playtest-feedback}.json`；
  `10f68791-3a17-4cc9-ae11-e47ed9e81633/{enable-debug-logging-response,start-log-observer-response,log-observer-evidence-response}.json`；
  `947ccc73-a946-413a-bfbe-d90f50d2cb10/{enable-own-graph-logging-response,position-observation,position-validation,log-observer-evidence-response}.json`；
  `6d622759-b349-423c-9f02-e1f396e367de/{enable-own-graph-logging-response,finish-observation,log-observer-evidence-response}.json`；
  `f7d6e439-27a7-454e-8b08-ec1d5d7808c9/{enable-own-graph-logging-response,observer-ten-seconds,root-log-selection-verification}.json`；
  `154fa209-779d-4b87-846c-ae741e9a1e44/{observer-ten-seconds,user-playtest-feedback}.json`；
  `a59ea1c8-1d63-4e6f-afad-39d0d52e8505/probe-error.json`。
- **台账/先例**：`docs/editor-catalog/INTERFACE-INVENTORY.md:144,347-369,492-496,591`；`docs/research/reverse-eng-20261010/GRAPH-LOG-SHAPE.md:22,23,129,144-147,152,158-166,170-251`；`docs/research/.../PLAYTEST-CONTROL-MINE.md:109-116,222-223,271-273`。
- **脚本**：`tools/editor-bridge/probe-log-observer.ps1:16-24`；`probe-runtime.ps1:14-18`；`call-bridge.ps1:1`（op 白名单含 5 个日志 op）。

---

## 8. `notClaimed`

- 本轮**什么都没跑**：没有起 bridge、没有发原生/图请求、没有开游戏或编辑器、没有读写任何存档、**没有读任何图片**。
- **没有**证明这批记录是「本次执行」的；**也没有**证明它是「历史回放」的——**§4.2 判定为「本轮证据不足以二选一」**。
- **没有**证明 `graphName` 段值就是「建图时刻」（只是数值与 Unix 秒吻合，且落在 09-16，早于捕获日 09-28）。
- **没有**证明 D1–D4 实验能通过；它是**尚未执行的**、**可反驳**的计划。
- **没有**证明 3001 一旦被启用的**副作用**可恢复——源码自陈 `previousEnabledState:"unknown"`（`EditorAdapter.cs:501`），本工程**不伪造恢复**。
- 「收到一条记录」**不等于**「图执行了」——本文件与 `RunLogSample.cs:90-91` 同口径。

---

*本文件由 2026-10-10 会话从仓内桥源码与 `.runtime/editor-bridge/runs/` 真实回执（Bash `grep`/`find`/`cat`，非 Grep 工具）只读整理；
**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档、未读任何图片**。所有行号为本次 checkout 实测；所有「=0」均为所述检索范围内的实数。
负面结论均写明检索范围；不确定处写「不确定」。*
