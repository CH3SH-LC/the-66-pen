> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #6 挖 — build 中途死掉会留下什么：Spend/attempt 标记、派发闸、request-id 重放（终章）

**产出日期**：2026-10-10（核对 checkout：`AuthoringGraph.cs` = 1040 行、`BridgeServer.cs` = 1039 行、`author.py` = 722 行）
**口径**：**纯离线、纯只读**。全程**未连桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未注注入、未编译、未写任何存档、未读任何图片/PDF**。遵从 HARD RULES。
**读的源**：①`tools/editor-bridge/Adapter/AuthoringGraph.cs`（全文逐行）；②`Adapter/EditorAdapter.cs`（`spent`/`Spent`/`Spend`/`ExportResource`）；③`Adapter/AdapterLease.cs`（`CleanupForLease`）；④`ManagedBridge/BridgeServer.cs`（租约、dispatcher、异常回执）；⑤`ManagedBridge/Entry.cs`（server 生命周期）；⑥`tools/authoring/author.py`（journal/claim/replay）；⑦`tools/authoring/graph-launch.ps1`、`graph-transport.ps1`、`graph-elevated-once.ps1`；⑧`tools/editor-bridge/elevated-runner.ps1`、`elevated-request.py`；⑨真机回执原件 `.runtime/authoring/requests/`（`Bash` 遍历，764 个目录）。

> 按 `CLAUDE.md` §一.3：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。行号＝本次 checkout 实测。
> **「搜不到」≠「不存在」**（`CLAUDE.md:23`）；本轮检索范围见 §6。
> **姊妹文件**（本文件不重述它们的清单，只把「中断安全」这一条**收口**）：`BRIDGE-CRASH-SAFETY.md`（#7，桥的中断安全）、`BUILD-PLAN-LIMITS.md`（#8）、`BUILD-PLAN-CEILING.md`（#9，批处理的尺寸天花板）、`GRAPH-DELETE-PROBE.md`（图删除恒失败）。

---

## 0. 一句话结论

1. **「每个 op 的成败标记」有三层，寿命完全不同**：
   - **durable（跨租约、跨进程）**：`author.py` 的 journal —— `claim.json` 在**派发之前**（`:380`）、`result.json` 在**派发返回之后无条件**（`:401`）；runner 侧 `elevated-attempt.used` 在**第一次管道操作之前**（`graph-elevated-once.ps1:24`）、`elevated-response.json` 在 helper 拿到回执后（`:44`）。键全是 `requestId`。
   - **in-memory（一个租约）**：适配器 `spent` 集合（`EditorAdapter.cs:30-32`）——`Spend(...)` 一律在**第一次原生变更之前**调用；`BridgeServer` 每次租约 `new` 一个 adapter（`BridgeServer.cs:59`），**租约一换即清零**。
   - ⇒ 「不重放」的保证**落盘、跨租约**；「不重应用」的保证**只在内存、只在一个租约内**（§1）。
2. **build-plan 死在 15 之 7：编辑器里留下 6–7 个节点、0 条边、0 个常量，且不可逆**（无回滚、动作表里没有删节点，`AuthoringGraph.cs:95-108`；租约清理不碰图，`AdapterLease.cs:12-31`）。**journal 留下 `claim.json` / `bridge-request.json`（含那份 15 节点的 plan）/ `result.json`**（`ok:false` + `outcomeUncertain:true`）。**`.gia` 不会留下**——build 不导出（§2）。
3. **同一请求重跑 = 重放回执（安全），不是重执行**：`author.py:367-379`。同 id + 同 command 字节 → 命中 `claim.json` 哈希、`result.json` 已存在 → `return dict(read_json(receipt), replayed=True)`（`:379`）——**根本不发第二次派发**。同 id 但 command 变了 → `REQUEST_ID_CONFLICT`（`:375`）；有 `claim` 无 `result` → `REQUEST_OUTCOME_UNKNOWN; inspect evidence; no retry`（`:378`）（§3）。
4. **让它「可检」的最便宜的一处改动**：让 build 路径把 `{plannedNodes, appliedNodes}` 作为**见证**写进**该次派发自己的 journal**、**从编辑器侧每加一个节点刷一次**（插入点 `AuthoringGraph.cs:756` 与 `:779`）。**值得做，但优先级低**——它只把「未知」降级为「事实」，**修不了半成品**，且要**改 C# 并重新编译**（本工程最重的一步）（§4）。

---

## 1. 每个 op：第一次原生变更「之前」与「之后」各记了什么（file:line）

### 1.1 三层记录，与它们的寿命

| 层 | 记什么 | 何时写 | 何时读 | 寿命 | 键 |
|---|---|---|---|---|---|
| **D1 journal claim** | `claim.json`（含 command 与 `sha256`） | **派发之前**，`author.py:380`（`exclusive_json`，`open('x')` 独占，`:188-192`）；目录先独占建于 `:369` | 同 id 重跑时 `:371-379` | **跨租约、跨进程**（磁盘） | `requestId`（目录名） |
| **D2 journal result** | `result.json`（`ok` / `outcomeUncertain` / `replayed`） | **派发返回之后无条件**，`author.py:401` | `:377-379` | **跨租约、跨进程** | 同上 |
| **D3 runner attempt/response** | `elevated-attempt.used`（空文件） | **第一次管道操作之前**，`graph-elevated-once.ps1:24`（`CreateNew`） | runner 预检 `elevated-runner.ps1:734` | **跨租约、跨进程** | `requestId` |
| **D4 runner response** | `elevated-response.json` | helper 有回执时，`graph-elevated-once.ps1:44`（`CreateNew`，**永不覆盖**） | `graph-launch.ps1:15`（`EXISTING_RESPONSE`）、runner `:734` | **跨租约、跨进程** | `requestId` |
| **M1 adapter spent** | `spent.Add(kind+":"+target)` | **第一次原生变更之前**（见 §1.2） | 每 op 入口 `Spent(...)` | **一个租约**（`BridgeServer.cs:59` 每次 `new`） | `kind:target` |

### 1.2 适配器层：每个 op 的 `Spend` 标记（读/写全表）

`Spent(kind,target)` 命中 → 抛 `*_ALREADY_ATTEMPTED`；`Spend(kind,target)` 记下。**不变量：`Spend` 在第一次原生变更之前**（源码注释原话「before the first native mutation」，见下）。

| op | 变更前「读」 | 变更前「烧」 | 第一次原生变更 | 变更后（成功才写） |
|---|---|---|---|---|
| `create` | `:224` `Spent("author-create",name)` | `:225` | `:231` `create.Invoke(...)` | 无独立标记（回执即 `create-requested-readback-pending` `:232`） |
| `lookup` / `inspect` | 无（只读） | — | — | — |
| `export` | `:919` `attemptedExports.Contains` 且 `Count>=2` 即拒 | `:935`（在异步 send 之前：`attemptedExports.Add`） | `:937` `producer...DoExport` | `:950` `invoked-not-confirmed`（异步，不回重试） |
| `add-node` | **无 `Spent`/`Spend`** | — | `:342` 原生 Add | `:344` 读回校验（`AUTHOR_NODE_READBACK_FAILED`） |
| `set-print` | `:456` `Spent("author-"+action,target)`（`target=graphId:nodeId`） | `:462` | `:463` `setter.Invoke` | —（回执 `print-value-set-...`） |
| `set-condition` | `:456` | `:477` | `:478` `setter.Invoke` | — |
| `set-value` | `:385`（`claim=graphId:nodeId:3:portIndex`） | `:386`（注释「before the first native mutation; a partial failure never replays」） | `:387` `AuthorWritePinValue` | 无独立标记（写后强制读回，`AuthorWriteScalar` `:901-972`） |
| `connect` / `disconnect` | `:436`（`edgeTarget=graphId:from:…:to:…`） | `:444`（disconnect）/ `:451`（connect，同句注释） | `:446` 原生 disconnect / `:452` 原生 link | `:443` `edge-already-absent` / `:449` 断开后读回 |
| `bind` | `:309` `Spent("author-bind",graphId:entityId)` | `:316` | `:317` `producer...AddInstructionGraphForEditObj` | `:304` `already-bound-editor-model-readback`（提前回读） |
| `build-print` | `:533` `Spent("author-print",claim)` | `:558`（注释「consumes attempt before first native mutation」） | `:559` `Add(...)` | `:586` `Spend("author-print-ready",claim)`（且 `:577` set-print、`:582` connect 各自烧过） |
| `build-count-gate` | `:615` `Spent("author-count",claim)` | `:651`（同句注释） | `:652` `Add(...)` | `:718` `Spend("author-count-ready",claim)` |
| **`build-plan`** | `:737` `Spent("author-plan",claim)` | **`:756`**（注释「before the first native mutation; a partial failure never replays」） | `:757` `Add(...)`（循环 `:775-780`） | **`:819` `Spend("author-plan-ready",claim)`（只在全图建成后）** |

**三条必须一起说清**：

1. **「ready」子标记是只写不读的（build-plan）**。`:819` 的 `author-plan-ready` 在全仓 `tools/` 下**只有这一处**（无任何 `Spent` 读它）。对照 `author-count-ready` 有读 `:276`、`author-print-ready` 有读 `:294`。
2. **`add-node` 没有 attempt 标记**。它的幂等来自**内容前置条件** `AUTHOR_NODE_COUNT_CONFLICT`（`:321`，声明计数必须精确匹配）。⇒ 逐节点路径的「不重放」只能在 journal 层（D1/D2）拿到，**适配器层不拦重放**。
3. **`build-plan` 的 `Spend` 早于任何原生变更**（`:756`），因此**一次中途失败后，同一租约内重试被 `:737` 拒**（`AUTHOR_PLAN_ALREADY_ATTEMPTED`）。

### 1.3 runner 侧：派发闸（跨租约，落盘）

- **runner 预检**：`elevated-runner.ps1:722-735` `Get-AuthorGraphDispatch`；`:731` 定位 journal；`:734` 只要 `elevated-attempt.used` **或** `elevated-response.json` 存在 → `AUTHOR_GRAPH_ALREADY_ATTEMPTED`。**在 runner 动手之前**。
- **helper 独占尝试**：`graph-elevated-once.ps1:24` 用 `CreateNew` 建 `elevated-attempt.used`，注释「Reinvocation cannot send twice, even if the first invocation has not produced its reply yet」。
- **传输只写一次**：`graph-transport.ps1:59` `writer.WriteLine($line)` 之后 **`:60-64` 故意不推进 stage**；所以「写了、没回」在 `:73` 报 `outcomeUncertain=($stage -eq 'send')`。
- **回执独占**：`graph-elevated-once.ps1:44` `CreateNew` 写 `elevated-response.json`，**永不覆盖**。
- **队列提交标记（提权路径）**：`elevated-request.py:106-115`，`:111` 用 `open("x")` 独占；内容不同 → `QUEUE_REQUEST_ID_PAYLOAD_MISMATCH`（`:115`）。

### 1.4 `author.py` 侧：派发前 / 派发后

- **派发前**：`:364-380`（journal mkdir 独占 `:369`；`bridge-request.json` 独占写 `:257-258`（走 `graph_call`）；提权路径另写 `helper-request.json` `:277`）。
- **派发后**：`:389-405` 组装 result（`mutating` 失败 → `outcomeUncertain=True` `:392-393`）→ **无条件**写 `result.json` `:401` → 尽力写 run receipt `:402`（`emit_run_receipt` 失败只上报、不抛，`:343-346`）。

---

## 2. 死在 15 之 7：编辑器模型 / journal / .gia / 能否续建

### 2.1 编辑器模型 —— **留下 6–7 个节点、0 条边、0 个常量，且不可逆**

`BuildAuthorPlan` 的阶段顺序是**明写的必需**（`:729-732` 注释）：**nodes（`:775-780`）→ edges（`:782-791`）→ values（`:792-818`）**。所以「死在第 7 个节点」意味着：

- `handles` 里**已有 6 个**（第 7 次 `Add` 抛了）**或 7 个**（第 7 次 `Add` 成功、随后的读回 `:762-764` 抛了）。**无论哪种，edges 与 values 都是 0**——它们在整个 nodes 循环之后才跑。
- **没有任何回滚**：`AdapterLease.CleanupForLease`（`AdapterLease.cs:12-31`）只做 `RestoreFinishMinimalDiagnostic` / `RestoreFinishSettlementDiagnostic`、停 `leaseTimers`、`StopLogObserver`、撤 `exportReceipts` 回调——**没有一句读/写图模型**。
- **删不掉**：`ValidateAuthorGraph` 的动作表（`AuthoringGraph.cs:95-108`）里**没有删节点**；唯一的反操作是 `disconnect`（只撤**边**，`:441-449`）。
- **State 恒 `persistentSaveVerified=false` / `runtimeVerified=false`**（`:232,257,318` …）⇒ 半成品图**在编辑器内存里**，归宿只有「编辑器自己保存」或「context/关卡重载丢掉」两个。

### 2.2 journal —— **留下，且留下「判未定」的原材料**

该次派发在 `.runtime/authoring/requests/<requestId>/` 留下（真机原件 `.runtime/authoring/requests/e513fc0df58a35f2b8aeb018abe5b0df/`，一份 `build-plan`）：

| 文件 | 写入者 | 本场景是否存在 |
|---|---|---|
| `claim.json` | `author.py:380`（派发前） | **在** |
| `bridge-request.json` | `author.py:257-258`（派发前） | **在**（含 `plan.nodes` = 15 个节点定义、`plan.edges`、`plan.values`） |
| `helper-request.json` | `author.py:277`（提权路径） | **在** |
| `elevated-attempt.used` | `graph-elevated-once.ps1:24` | **在** |
| `elevated-response.json` | `graph-elevated-once.ps1:44` | **在**（异常回执）或**缺**（helper 被硬杀/超时未回） |
| `result.json` | `author.py:401`（派发返回后） | **在**（`ok:false` + `outcomeUncertain:true`）；**若 python 被判发返回前硬杀则缺** |

真机原件（`e513fc0d…`，`Bash` 读）：`elevated-response.json` = `{"ok":false,"error":"adapter:InvalidOperationException:EDITOR_BINDING_PROFILE_UNREGISTERED_SYMBOL: BeyondEditor-7.1.0-static ur7KK2NiYZ4"}`；`result.json` 顶层 `ok:false`、`outcomeUncertain:true`、`replayed:false`。该失败发生在 **values 阶段**（13 个节点、15 条边已落地）——与 §2.1 的阶段顺序一致。

**判据（唯一显式的「上次没跑完」信号）**：**有 `claim.json`、无 `result.json`** → 下一次同 id 调用撞 `REQUEST_OUTCOME_UNKNOWN; inspect evidence; no retry`（`author.py:378`）。

### 2.3 `.gia` —— **不会留下**

- **build 不导出**：`build-plan` / `build-print` / `build-count-gate` 只写图模型，不调 `ExportResource`；导出是**另一个 op**（`AuthoringGraph.cs:260`）。
- 导出落点 `.runtime/editor-bridge/exports/<pipeName>/bridge-export-<guid>.gia`（`EditorAdapter.cs:927`），且**每租约每 id 只能一次**（`:919` `EXPORT_DUPLICATE_OR_LEASE_LIMIT`）、**异步且不回重试**（`:935-936`）。
- ⇒ 一次中途死掉的 build，**离线能读 `nodeCount` 的产物不存在**。

### 2.4 判决：**续建不能、重建不能、只能放弃（或逐节点人工补）**

| 路径 | 能否 | 依据 |
|---|---|---|
| **投同一请求（同 id）** | **不能，且不会重执行** | `author.py:377-379`：有 `result.json` → 重放回执；无 → `:378` `REQUEST_OUTCOME_UNKNOWN` |
| **投同一请求（新 id）即「重建」** | **不能** | `AuthoringGraph.cs:735` `AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH`（图非空）+ 同租约内 `:737` `AUTHOR_PLAN_ALREADY_ATTEMPTED`（attempt 已烧 `:756`）。换新租约 → `:737` 放行，但 `:735` **仍拒**（「图里有节点」活在编辑器内存，与内存标记无关） |
| **「续建」剩下 8 个节点** | **没有这个原语** | `build-plan` 只吃空图（`:735`）；只能逐节点 `add-node`（每步给当前 `expectedNodeCount`）+ `wire`，**plan 这个抽象没了** |
| **放弃 / 清场** | **无可用图删除** | `delete-owned-graph-ids` 恒 `modelMatched=0`（`OwnedGraphDelete.cs:174`，引用相等谓词；全文见 `GRAPH-DELETE-PROBE.md`）。只剩 ① 编辑器 UI 手删；② context/关卡重载丢掉**全部**未保存编辑 |

**一句话**：**半成品图会留下，且今天没有任何一条自动路径能续、能清、能判「到了第几步」。**

---

## 3. request-id / journal：同一次请求重跑 = **重放回执（安全）**，不是重执行

`author.py` 的 `execute()`（`:349-405`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**三条分支，三种命运**：

1. **同 id + 同 command 字节 + `result.json` 在** → **重放回执**（`:379`，`replayed=True`）。**绝不再发派发**——连 `graph_call`（`:252`）都到不了。**这是安全的**。
2. **同 id + command 变了**（含 `build-plan` 的 plan 文件改了）→ `REQUEST_ID_CONFLICT`（`:375`）。因为 **id 是「请求本身」的函数**：command 进 `sha256`（`:367`），plan 又被读进 command（`_command_from_args` `:591-602`，注释明写「a plan that changed on disk between two runs is a NEW request, and the request id … makes that a conflict, not a replay」）。
3. **有 `claim.json`、无 `result.json`** → `REQUEST_OUTCOME_UNKNOWN`（`:378`）——**这正是「上次派发没跑完就死了」在 journal 层的唯一显式判据**，且**明令 no retry**。

**因此**：对同一请求重跑，**只要 `result.json` 在，就是读盘、零风险**；`result.json` 不在（进程被杀）时**它拒你，而不是替你重发**。**永远不存在「同一 requestId 把整张图重建一遍」这条路径。** 适配器层的 `spent`（§1.2）只是**第二道、只在一个租约内**的冗余保险。

---

## 4. 让它「可检」的最便宜的一处改动（不是修 —— 只是可检）

**单一改动**：让 build 路径把 **`{plannedNodes, appliedNodes}` 作为见证（witness）写进该次派发自己的 journal**，**从编辑器侧写、每加一个节点刷一次**。

- **插入点**：`AuthoringGraph.cs` 的 `BuildAuthorPlan`（`:733`）。
  - **两个数它都已经有**：`count = planNodes.GetArrayLength()`（`:739`）是 planned；`handles`（`:774`）的 `Count` 是 applied。
  - 在 `Spend("author-plan",claim);`（`:756`）之后立即写一次 `{plannedNodes=count, appliedNodes=0, graphId, action}`；
  - 在 `handles.Add(Add(ids[i],x,y));`（`:779`）之后改写 `appliedNodes=handles.Count`；
  - 同样加到 `BuildAuthorCountGate`（`:651` 起，13 个固定节点）与 `BuildAuthorPrint`（`:558` 起，2 个节点）。
- **为什么不用改协议**：request id **已在报文里**（`author.py:256` `id=request_id`；`ValidateAuthorGraph` 允许 `id` 字段，`AuthoringGraph.cs:110`），且 `AuthorGraph` **已经**拿到一个绝对输出目录（`exportDirectory`，`BridgeServer.cs:570` 传 `…\exports\<pipeName>`）。把见证落到**该 id 自己的目录**只需该目录路径——同属这一处改动（`BridgeServer` 多传一个参数，或从 `exportDirectory` 反推）。
- **为什么是这一处、而不是「让异常回执带计数」（那个更便宜但不够）**：把计数塞进异常消息（走 `BridgeServer.cs:673` 的 `adapter:<Type>:<Message>`）**只在「抛异常 → 有回执」这条死法上有效**；而 **「请求已写出、回执没到」这条**（`graph-transport.ps1:73` `stage=send` + `outcomeUncertain`，真机有 3 例原件）**根本没有回执**，硬杀客户端同理。**只有编辑器侧落盘的见证同时覆盖两种死法**，且在编辑器进程被硬杀时，见证文件**停在最后一个已应用的步骤**上——那正是「7 of 15」。
- **成本与边界（写清）**：
  - **要改 C# 并重新编译**（本工程最重的一步，须走 revision 流程）——这是它相对「纯 Python/PS 改动」贵的地方，也是它排**低优先**的原因。
  - 它是**可检**、**不是修复**：见证**不得**触发任何自动重放（否则就破坏了 §1.2/§3 的「绝不重放」）。
  - 若编辑器被硬杀，最后一次写可能在缓冲里；要么每步 `Flush`/落盘，要么改成 per-id 的**追加式步骤日志**。

**值不值得做**：**值得，但优先级低**。理由：它把「死在第几步」从**事后重建**降为**当场读取**，且是今天唯一能让「部分 build」**自动**可检的办法；但它**不修半成品、不让图可续建**，且需要一次编译。**在「图删除」与「续建原语」缺失的前提下，先把命运判清比先把进度判清更值**——而命运今天已经可判（`claim`/`result` 二元组，§2.2）。故：**列为备选，不排在做删除/重置原语之前。**

---

## 5. 证据索引（file:line）

**adapter 标记（内存，一租约）**
- `tools/editor-bridge/Adapter/EditorAdapter.cs:30-32`（`spent` / `Spent` / `Spend`）；`:914-951`（`ExportResource`；`:919` 每租约每 id 一次；`:927` `.gia` 路径；`:935-936` 异步不回重试）
- `tools/editor-bridge/Adapter/AuthoringGraph.cs`：create `:224-225`；bind `:309/316`；add-node **无标记**（内容闸 `:321`）；set-value `:385-386`；connect/disconnect `:436/444/451`；set-print/set-condition `:456/462/477`；build-print `:533/558/577/582/586`；build-count-gate `:615/651/718`；**build-plan `:737/756/819`**；阶段顺序 `:729-732`、nodes `:775-780`、edges `:782-791`、values `:792-818`；空图闸 `:735`；动作表 `:95-108`
- `tools/editor-bridge/Adapter/AdapterLease.cs:12-31`（`CleanupForLease`，不碰图）
- `tools/editor-bridge/Adapter/OwnedGraphDelete.cs:174`（引用相等谓词 → `modelMatched` 恒 0）

**派发闸（落盘，跨租约）**
- `tools/authoring/author.py`：`:256`（request id 进报文）；`:257-258`（bridge-request）；`:277`（helper-request）；`:364-380`（journal/claim/replay）；`:369`（目录独占）；`:373`（INCOMPLETE_CLAIM）；`:374`（ID_CONFLICT）；`:378`（OUTCOME_UNKNOWN）；`:379`（`replayed=True`）；`:380`（claim 独占）；`:392-393`（`outcomeUncertain` 传播）；`:401`（无条件写 result）；`:402/343-346`（run receipt 尽力）；`:591-602`（build-plan 的 plan 进 fingerprint）
- `tools/authoring/graph-launch.ps1:15`（`EXISTING_RESPONSE`）；`:28`（`WAIT_EXPIRED`）；`:32`（fallback `outcomeUncertain`）
- `tools/authoring/graph-transport.ps1:24-26`（45 s 窗）；`:51`（`REQUEST_TOO_LARGE` / 16000 B）；`:59`（写）；`:60-64`（stage 不推进）；`:67`（`RESPONSE_TIMEOUT`）；`:72-73`（catch → `outcomeUncertain=($stage -eq 'send')`）
- `tools/authoring/graph-elevated-once.ps1:24`（attempt 标记）；`:40`（fallback）；`:44`（回执独占）
- `tools/editor-bridge/elevated-runner.ps1:722-735`（`Get-AuthorGraphDispatch`）；`:734`（`AUTHOR_GRAPH_ALREADY_ATTEMPTED`）；`:837`（`Invoke-FixedAuthorGraph`）
- `tools/editor-bridge/elevated-request.py:105-123`（submission 标记；`:115` `QUEUE_REQUEST_ID_PAYLOAD_MISMATCH`）

**租约 / dispatcher / 回执**
- `tools/editor-bridge/ManagedBridge/BridgeServer.cs:34`（`MaxLineBytes=16*1024`）；`:37`（`Lease=5min`）；`:59`（`_adapter=new()`）；`:71-76`（租约 deadline）；`:121-139`（cleanup；`:127` 在 dispatcher 上跑 `CleanupForLease`；`:136` `lease-closed.json`；`:139` `_completed`）；`:205-213`（`line_too_long`）；`:551`（`Dispatcher.InvokeAsync`）；`:570`（`AuthorGraph(root, …\exports\<pipe>)`）；`:673`（`adapter:<Type>:<Message>`）；`:966-974`（`Error()` 形状）
- `tools/editor-bridge/ManagedBridge/Entry.cs:73`（旧 server 未结束则拒新 server）

**真机语料（`.runtime/`，Bash 遍历）**
- `.runtime/authoring/requests/`：764 个目录；`result.json` 缺 **0**；`elevated-response.json` 缺 **0**；`outcomeUncertain` **72**；`ok:false` **104**（与 `BRIDGE-CRASH-SAFETY.md` §2.2 一致）
- `.runtime/authoring/requests/e513fc0df58a35f2b8aeb018abe5b0df/`（`build-plan`，13 节点 / 15 边 / 11 常量；values 段抛 `EDITOR_BINDING_PROFILE_UNREGISTERED_SYMBOL`；`ok:false` + `outcomeUncertain:true`）

---

## 6. 边界与盲区（本轮搜过什么 / 没搜什么）

- **未连桥、未发报文、未触碰游戏/编辑器、未编译、未做任何真机动作**：所有结论来自源码与 `.runtime/` 只读语料。§4 的改动**未实现、未验证**。
- **「无回滚 / 无删节点」的检索范围**：`AuthoringGraph.cs` 动作表（`:95-108`）、`author.py:57-59` 的 `GRAPH_ACTIONS`、`AdapterLease.cs`。**未**穷举已编译 DLL 或 profile 里是否存在某个未接线的原生删节点/撤销符号（**「搜不到」≠「不存在」**）。
- **「6–7 个节点」是源码阶段顺序（nodes→edges→values）推出的**，**不是**事后读回：现存 journal 里没有对该图失败**之后**的 `inspect` 记录。要下「它今天到底剩几个节点」的结论，需要一次真机读回（本轮遵从 HARD RULES **不做**）。
- **「kill ≠ abort」是 token 语义的强推论**：`Dispatcher.InvokeAsync(..., token)`（`BridgeServer.cs:551`）的 lease token **只取消尚未开始**的排队项，**停不下一个已在执行的委托**。⇒ 客户端超时/断开**不会**让半途的 build 停手；放弃那一刻之后图可能**更完整**。此点与 `BRIDGE-CRASH-SAFETY.md` §1.D3 一致，本轮**未真机复现**。
- **`.runtime/authoring/requests/` 的计数是一次 `Bash` 快照**；`outcomeUncertain`/`ok:false` 的计数**未逐条去重到 requestId**（同一 id 只会有一个目录，故按目录计）。
- **本文件只新增自己**；未改 `STRUCTURE.md`、未改 `PROGRESS*.md`、未改 `INDEX.md`、未改任何源码或测试（**无代码变更 ⇒ 无新测试**；本轮实跑文档守卫基线：`tools.gameplan.tests.test_no_stale_op_count` / `test_repo_consistency` / `test_doctrine` / `test_evidence_discipline` / `test_verification_claims` 共 46 项，全过）。

---

*分析于 2026-10-10。仅静态阅读 + `.runtime/` 只读语料。未改码，未发请求，未启停任何进程。*
