> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #7 挖 — 桥的中断安全：超时/挂起时会留下什么

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档、未读任何图片**。
证据来源只有三处：① 仓内桥 C# / PowerShell / Python 源码；② `.runtime/` 里的**真实回执原件**（Bash `grep`/`find`/`cat`；**Grep 工具会静默跳过 `.runtime/`**，见 `CLAUDE.md` §一.2）；③ 仓内研究文档 `GRAPH-DELETE-PROBE.md`。
**本文件只新增自身**，不改其它任何文件。

> 按 `CLAUDE.md` §一.3：`文档写了什么` / `工具能做什么` / `真机验证过什么` 三层分开标。
> 本文件几乎全是静态结论 + `.runtime/` 里的**真机回执原件**；凡「= 0」均写明检索范围。
> 姊妹文件：`GRAPH-DELETE-PROBE.md`（图删除为何恒失败）、`GRAPH-LOG-SHAPE.md`。

---

## 0. 一句话结论

- **「同一次派发只能发一次」有三层闸门，都落盘、都以 `requestId` 为键、都跨 lease 有效**（§1.A）。
- **「同一次变更只能应用一次」只有一层闸门 —— adapter 的 `spent` 集合 —— 而它是「每个 lease 一个新实例」**：
  `BridgeServer._adapter=new()`（`BridgeServer.cs:59`），lease 一换就清零（§1.B）。
  **这就是保证的尽头**：`spent` 挡的是**同一 lease 内的重放**，不是**跨 lease 的重放**，也**完全不是**「半成品**回滚**」。
- **一次 build 在半个节点上死掉，编辑器内存里的半成品图必然留下，且没有任何回滚**：
  `CleanupForLease`（`AdapterLease.cs:12-31`）只做诊断复位/停表/撤导出回调，**一个字都没碰图模型**；
  adapter 的动作表（`AuthoringGraph.cs:95-108`）里**没有删节点**，只有 `disconnect` 能撤**边**（§2.1）。
- **落盘的残留**：该次派发的 journal 目录留下（含 `claim.json` / `bridge-request.json` / `elevated-attempt.used` /
  `elevated-response.json` / `result.json`），并留下「这次派发**未定**」这个判定的**原材料**（§2.2）。
- **`.gia` 不会留下**：build **不导出**；导出是**另一个 op**，且是异步的（§2.3）。
- **恢复程序今天只有「读回 + 人工决定」**；「死在 15 之 7」这件事**今天不可检** ——
  失败回执**不带任何已应用计数**（抛异常回 `adapter:...` 裸串 `BridgeServer.cs:652`；超时回 `stage=send`
  `graph-transport.ps1:73`）。能检的只有「这次派发失败/未定」，**不能**检「图里现在有 K 个节点」（§3）。
- **让它「可检」的那一处改动**：让 build 路径把 `{plannedNodes, appliedNodes}` 作为**见证**写进该次派发自己的
  journal，**从编辑器侧写、每加一个节点刷一次**（§4）。它修不了半成品 —— 只是把「7 of 15」变成**事实**。

---

## 1. 防重放的闸门，以及保证到哪里结束

### 1.A 「这次派发最多发一次」（durable，落盘，跨 lease）

| # | 闸门 | 位置 | 形状 |
|---|---|---|---|
| A1 | journal 目录 + `claim.json` 独占 | `tools/authoring/author.py:364-380` | `directory.mkdir()` 独占（:369）；重开时按 `claim` 哈希判冲突（:375 `REQUEST_ID_CONFLICT`）；**claim 在、`result.json` 不在 → `REQUEST_OUTCOME_UNKNOWN; inspect evidence; no retry`（:378）** |
| A2 | 队列提交标记（永久） | `tools/editor-bridge/elevated-request.py:105-122` | `<rid>.submission.json` 用 `open("x")` 独占（:110）；内容不同 → `QUEUE_REQUEST_ID_PAYLOAD_MISMATCH`（:114）；已存在同类文件 → 拒（:118-119）。注释明说「Reproduce a permanent exclusive submission marker」 |
| A3 | runner 侧 journal 检查 | `tools/editor-bridge/elevated-runner.ps1:639-653` | `Get-AuthorGraphDispatch`；`:651` 见到 `elevated-attempt.used` 或 `elevated-response.json` 即 `AUTHOR_GRAPH_ALREADY_ATTEMPTED` |
| A4 | 提权 helper 的独占尝试标记 | `tools/authoring/graph-elevated-once.ps1:24` | `elevated-attempt.used` 用 `CreateNew` **在第一次管道操作之前**建；注释：「Reinvocation cannot send twice, even if the first invocation has not produced its reply yet」 |
| A5 | 回执独占写 | `tools/authoring/graph-elevated-once.ps1:44` | `elevated-response.json` 用 `CreateNew`，**永不覆盖**已存在的回执 |
| A6 | 传输只写一次 | `tools/authoring/graph-transport.ps1:59` | `writer.WriteLine($line)` 之后**阶段故意不推进**（:60-64），所以「写了、没回」= `outcomeUncertain=true`（:73） |

A1–A6 的键都是 `requestId`，全部落盘，**跨 lease 有效**。

### 1.B 「这次变更最多应用一次」（in-memory，每个 lease 一份）

- **本体**：`tools/editor-bridge/Adapter/EditorAdapter.cs:30-32`
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- **形状**：`kind:target` 键。target 是「这次变更**指向谁**」（图 id、节点 id、边三元组、`graphId:nodeId:portKind:portIndex`），
  不是「哪个动作」——所以同一个会话能建多张图（注释 `EditorAdapter.cs:21-29` 讲的就是这个从单 bool 改过来的原因）。
- **关键不变量**：`Spend` **在第一次原生变更之前**调用。原话：
  - `AuthoringGraph.cs:386` `Spend("author-"+action,claim); // before the first native mutation; a partial failure never replays`
  - `AuthoringGraph.cs:451` connect 同句；`:558` build-print；`:651` count-gate；`:756` **build-plan**
  - 复用点全表：create `:224-225`；bind `:309/316`；set-value `:385-386`；connect/disconnect `:436/444/451`；
    set-print `:456/462`；set-condition `:456/477`；build-print `:533/558`；count-gate `:615/651`；build-plan `:737/756`。
- **「ready」子标记**（用于 bind 前的就绪判定，不是回滚）：`:586 author-print-ready`、`:718 author-count-ready`、`:819 author-plan-ready`；
  被 bind 处回读校验：`:276-278`、`:294-296`。
- **存活边界**：`spent` 是 `EditorAdapter` 的实例字段；`EditorAdapter` 是 `BridgeServer` 的实例字段
  （`BridgeServer.cs:59`）；`BridgeServer` **每个 lease 一个**（`BridgeServer.cs:37` `Lease=5min`；
  lease 结束写 `lease-closed.json` 并 `_completed=1`：`BridgeServer.cs:136-139`）；
  `Entry.Start` 只在**旧 server 未结束**时拒绝新 server：`Entry.cs:73` `if(_server!=null && !_server.IsCompleted)return CodeAlreadyStarted;`。
  ⇒ **新的 lease = 新的 adapter = 空的 `spent`**。

### 1.C 内容前置条件（不是防重放，但限制伤害范围）

- build-plan **要求空图**：`AuthoringGraph.cs:735` `AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH`。
- add-node **要求节点数精确**：`AuthoringGraph.cs:321` `AUTHOR_NODE_COUNT_CONFLICT`。
- bind 要求精确计数：`:299`；print/count 的 ready 判定：`:294`、`:276`。
- 这一层**只在「目标图不是空/计数不符」时拒绝**；它**既不检测也不撤销**一次已发生的半成品。

> 附带：图资源**没有可用的删除**。`delete-owned-graph-ids` 恒 `modelMatched=0`
> （`OwnedGraphDelete.cs:174` 用**引用相等**匹配，而行/根两条路给出的是两类对象；全文见 `GRAPH-DELETE-PROBE.md` §0.1、§1）。

### 1.D 保证的尽头（四条，逐条写清）

1. **换 lease → `spent` 清零**（§1.B）。因此「同一 lease 内绝不重放」这句话**不能**外推到新 lease。
2. **换 `requestId` → A1–A6 全不绑定**。只剩 §1.C 的内容条件，而它在**空图**上不拦任何东西。
3. **「kill ≠ abort」**。adapter 的工作跑在编辑器的 WPF dispatcher 上（`BridgeServer.cs:530-531`
   `Application.Current.Dispatcher.InvokeAsync(...)`）；传给它的 lease 取消令牌**只能阻止尚未开始**的排队操作，
   **停不下一个已在执行的委托**。所以helper 超时/断开**不会**让半途的 build 停手 ——
   客户端放弃之后，图**可能比放弃那一刻更完整**。
4. **A/B 两层挡的是「重放」，不是「半应用」**。`Spend` 标记的是「整个 plan 已尝试」；
   plan 中途抛出 → 半状态留下、重试被拒（对「重放」是对的，但也**正因如此它不会自愈**）。

---

## 2. 中断后到底还剩什么

### 2.1 编辑器里的图模型 —— 留下，且不可逆

- **没有任何回滚/撤销机制**。对 `tools/editor-bridge/Adapter/` + `ManagedBridge/` 全文
  `grep -rln "rollback|Rollback|undo"` **只命中一处注释**（`ReopenContentEvidence.cs:103`），没有代码。
- **lease 清理不碰图**：`AdapterLease.cs:12-31` 只做
  `RestoreFinishMinimalDiagnostic`（:15）、`RestoreFinishSettlementDiagnostic`（:16）、停 `leaseTimers`（:17-19）、
  `StopLogObserver`（:21）、逐个撤 `exportReceipts` 回调（:22-28）。**没有一句读/写图模型**。
- **adapter 动作表里没有「删节点」**：`AuthoringGraph.cs:95-108` 的字段表 = create/lookup/inspect/add-node/
  set-print/set-condition/set-value/pin-slots/build-count-gate/build-plan/build-print/connect/**disconnect**/bind/export。
  唯一的反操作是 `disconnect`（撤**边**，且有读回验证 `:448` `AUTHOR_LINK_PRESENT_AFTER_DISCONNECT`）。**节点删不掉**。
- **持久层**：所有图 State 一律 `persistentSaveVerified=false` / `runtimeVerified=false`（`AuthoringGraph.cs:232,257,318` …）。
  桥改的是**编辑器内存**（`CLAUDE.md` §二）。⇒ 半成品图的归宿只有两个：
  ① 编辑器自己保存它；② 编辑器 context/关卡重载把它（连同一切未保存的图编辑）丢掉。

### 2.2 journal —— 留下，且留下「判未定」的原材料

一次 graph 派发可能在 journal 目录（`.runtime/authoring/requests/<requestId>/`）留下：

| 文件 | 写入者 | 何时 |
|---|---|---|
| `claim.json` | `author.py:380` | 派发前，独占 |
| `bridge-request.json` | `author.py:257-258` | 派发前，独占 |
| `helper-request.json` | `author.py:277` | **仅提权队列路径**（`elevatedQueue`） |
| `elevated-attempt.used` | `graph-elevated-once.ps1:24` | 管道操作前，独占 |
| `elevated-response.json` | `graph-elevated-once.ps1:44` | helper 有回执时，独占 |
| `result.json` | `author.py:401` | **派发返回后无条件写**（含 `ok` / `outcomeUncertain` / `replayed`） |

**判据**：
- 派发**返回过**（哪怕 `ok:false`）→ `result.json` 在；`mutating` 命令失败 → `outcomeUncertain=true`（`author.py:393`）。
- 派发**在返回前被弄死** → 只有 `claim.json`、没有 `result.json`；**下一次同 id 调用**会撞 `REQUEST_OUTCOME_UNKNOWN`
  （`author.py:378`）—— 这是 journal 层面对「上次没跑完」的**唯一**显式判据。

**真机计数**（本 checkout 实测，`Bash` 遍历 `.runtime/authoring/requests/`，764 个目录）：
`result.json` 缺失 **0** 个；`elevated-attempt.used` 有而 `elevated-response.json` 缺 **0** 个；
`outcomeUncertain:true`（顶层或 backend）**72** 个，其中 `ok:false` **104** 个。
⇒ 现存语料里**没有**「跑到一半就被硬杀的派发」，但有 **72 个**「结果未定」的，形状与「死在一半」完全同类。

### 2.3 `.gia` —— 不会留下

- build（`build-plan`/`build-print`/`build-count-gate`）**不导出**；导出是**单独 op** `export`（`AuthoringGraph.cs:260`）。
- 导出落点：`.runtime/editor-bridge/exports/<pipeName>/bridge-export-<guid>.gia`（`EditorAdapter.cs:927`；目录由
  `BridgeServer.cs:549` 给出）。
- 导出是**异步**且**每 lease 每 id 只能一次**：`:919` `EXPORT_DUPLICATE_OR_LEASE_LIMIT`、`:935-936`
  （注释：「no retry after a possibly successful asynchronous send」）。回执只是 `invoked-not-confirmed`（`:950`）。
- ⇒ 一次中途死掉的 build，**没有 `.gia`**；唯一能离线读 `nodeCount` 的产物（`tools/editor-bridge/inspect-graph.py:61`）
  在那一刻**不存在**。

### 2.4 真机原件（`.runtime/` 里确凿的两类）

**(a) 半成品图的确凿原件 —— `MW_API_FARM_V2` 的 build-plan**
journal：`.runtime/authoring/requests/e513fc0df58a35f2b8aeb018abe5b0df/`

- `bridge-request.json`：`action=build-plan`，`name=MW_API_FARM_V2`，`graphId=1073741826`，
  `expectedNodeCount=0`；plan **nodes=13 / edges=15 / values=11**，node 定义序列
  `[92,686,733,690,233,2,686,686,1,92,702,684,1]`。
- `elevated-response.json`：`{"ok":false,"error":"adapter:InvalidOperationException:EDITOR_BINDING_PROFILE_UNREGISTERED_SYMBOL: BeyondEditor-7.1.0-static ur7KK2NiYZ4"}`。
- 该符号 `ur7KK2NiYZ4` **全仓只有一个使用点**：`AuthoringGraph.cs:964`（`AuthorWriteScalar` 的 **string 读回**分支），
  profile 里**没有声明**（`EditorBindingProfile.Generated.cs` 零命中）——所以它是在 **values 阶段**炸的。
- **阶段顺序**：nodes（`:775-780`）→ edges（`:782-791`）→ values（`:792-818`）。⇒ 这次失败发生时
  **13 个节点、15 条边都已落地**，values 只应用了一部分。`Spend("author-plan",claim)` 早在 `:756` 就烧掉，
  **同一 lease 内的重试被 `AUTHOR_PLAN_ALREADY_ATTEMPTED`（:737）拒绝** —— 而图**留在半成品状态**，没有任何东西撤它。
  （注：当前 `:804` 已把 string-slot 的 plan 值绕开那个缺失符号；本条记录的是**当时**的代码，但「values 段抛出 ⇒ 节点/边全在」这个结构**未变**。）

**(b) 「写了、没回」的传输原件 —— `stage=send` + `outcomeUncertain=true`**
三例（本 checkout 实测）：`38549d2e…` / `4dae5cab…` / `93e7d1b8…`，`bridge-request.json` 都是 `{"id":...,"op":"catalog"}`。
`result.json` 顶层 `outcomeUncertain:false`（因为 `catalog` **非 mutating**，`author.py:393`），
但 `backend.outcomeUncertain:true`、`backend.stage:"send"`（`graph-transport.ps1:72-73`）。
⇒ 这证明**「请求已写出、回执没到」这条不确定路径在真机上真实发生过**；对**写** op 它就会是 `mutating` 的 `true`。
（背景：这条路上真出过 `graph catalog` 被 15s 窗口切掉的事故，见 `test-graph-transport-window.ps1` 的 WHY 段；窗口现已 45s：`graph-transport.ps1:24-26`。）

---

## 3. 恢复程序（今天，逐步），以及它是否可检

设：一次 build **死在 15 之 7**（无论它是 15 次 `add-node`，还是一次 `build-plan` 只在第 7 步后崩）。

**Step 0 — 判定「失败/未定」**（三个独立记录，任一即可）：
- `result.json` 里 `ok:false`，或 `outcomeUncertain:true`（`author.py:393`）；
- 有 `claim.json`、无 `result.json` → 同 id 再调用撞 `REQUEST_OUTCOME_UNKNOWN`（`author.py:378`）；
- 有 `elevated-attempt.used`、无 `elevated-response.json` → helper 没留下回执（`graph-elevated-once.ps1:24`）。

**Step 1 — 确认不能再发同一次**：同 id 重发会撞 A1/A3/A5（`REQUEST_OUTCOME_UNKNOWN` /
`AUTHOR_GRAPH_ALREADY_ATTEMPTED` / graph-launch 的 `EXISTING_RESPONSE`，`graph-launch.ps1:15`）。**没有 retry。**

**Step 2 — 唯一能读到「图里现在有几个节点」的办法：一次 `inspect` 读回**。
需要**新 lease**（`author.py:255` 的 `lease()` 要求 run 目录的 `expiresUtc > now`；`elevated-request.py:131-157`
`latest_run_id` 也按 `expiresUtc` 过滤）。发：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

回执来自 `AuthoringGraph.State`（`:251-258`）：`nodeCount`、逐节点 `{nodeId, definitionId}`、
`boundEntityIds`、`boundToLevel`。与 `bridge-request.json` 里 plan 的 `nodes.length` 对照，**才知道差多少**。

**Step 3 — 按差额决定**（三条，全部是「人工决定」，没有自动路径）：
- **节点数 = plan 数、只是 values/edges 没写完**：值可用 `value`/`set` 单独补写（键 `author-set-value:graphId:nodeId:3:index`，
  在**新 lease** 里 `spent` 为空，故允许）；边可用 `unwire` 先撤再 `wire` 重连。**但 plan 这个抽象没了，只能逐条重敲。**
- **节点数 < plan 数**：**没有「续建」**（`build-plan` 要求空图 `:735`）。只能逐节点 `add-node`（每步给当前 `expectedNodeCount`）
  再 `wire`。同样，plan 抽象失效。
- **放弃**：**没有可用的图删除**（`GRAPH-DELETE-PROBE.md` §0.1；`OwnedGraphDelete.cs:174`）。
  剩下的只有 ① 在编辑器 UI 里手删；② 让编辑器 **context/关卡重载**把未保存的编辑丢掉（`CLAUDE.md` §二；
  记忆「bridge edits die on context reset」）——但那会连带丢掉**全部**未保存工作。

**Step 4 — 你读不到「已应用多少」**：失败回执**不带任何节点计数**。
抛异常时回的是 `adapter:<异常名>:<消息>`（`BridgeServer.cs:652`）；超时时回的是
`BRIDGE_TRANSPORT_FAILED` + `stage:"send"` + `outcomeUncertain:true`（`graph-transport.ps1:72-73`）。
两者都只告诉你**「这次成败/未定」**，**不告诉你「图现在是 7/15 还是 13/15」**。

### 可检性判决（分开说）

| 问题 | 今天可检？ | 依据 |
|---|---|---|
| 这次派发**失败**了吗？ | **可检**，且落盘、跨 lease | §1.A + `result.json` |
| 这次派发**成败未定**吗？ | **可检** | `outcomeUncertain`（`author.py:393`、`graph-transport.ps1:73`） |
| 图现在**有几个节点**？ | **不可检**（无任何回执/文件带这个数） | `BridgeServer.cs:652`、`graph-transport.ps1:73` 都不带计数 |
| 「死在 15 之 7」这件事 | **不可检** | 同上；只能靠**事后一次新 dispatch 的读回**去**重建**，且**必须有活 lease** |

一句话：**「失败了」是事实；「失败到哪一步」是未记之账。**

---

## 4. 让它「可检」的那一处改动（不是修 —— 只是可检）

**单一改动**：让 build 路径把 `{plannedNodes, appliedNodes}` 作为**见证（witness）**写进**该次派发自己的 journal**，
**从编辑器侧写**，且在**每加一个节点之后刷新一次**。

- **插入点**：`tools/editor-bridge/Adapter/AuthoringGraph.cs` 的 `BuildAuthorPlan`（`:733`）。
  它**已经有**这两个数：`count = planNodes.GetArrayLength()`（`:739`）是 planned；
  `handles`（`:774`）的 `Count` 是 applied。
  - 在 `Spend("author-plan",claim);`（`:756`）之后立即写一次 `{plannedNodes=count, appliedNodes=0, graphId, action}`；
  - 在 Add 循环 `handles.Add(Add(ids[i],x,y));`（`:779`）之后改写 `appliedNodes=handles.Count`；
  - 同样加到 `BuildAuthorCountGate`（`:651` 起，13 个固定节点）与 `BuildAuthorPrint`（`:558` 起，2 个节点）。
- **为什么不需要改协议**：request id **已经在报文里**（`author.py:256` `id=request_id`；`ValidateAuthorGraph` 允许
  `id` 字段，`AuthoringGraph.cs:110`），且 `AuthorGraph` **已经**拿到一个绝对输出目录（`exportDirectory`，
  `BridgeServer.cs:549`）。所以只需 adapter 把见证写到**该 id 自己的目录**
  （`<root>/.runtime/authoring/requests/<id>/build-witness.json`）；路径可由 `exportDirectory` 或由
  `BridgeServer` 多传一个参数得到（同属这一处改动）。
- **为什么是这一处而不是「让错误回执带计数」**：回执只在**抛异常**时用得上；而**超时/客户端断开**这条
  （§2.4(b) 的真机原件证明它真发生）**根本没有回执**。**只有编辑器侧落盘的见证同时覆盖两种死法**，
  且**在编辑器进程被硬杀时**，见证文件停在**最后一个已应用的步骤**上 —— 那正是「7 of 15」。
- **边界（必须写清）**：
  - 它是**可检**，**不是修复**：半成品图仍在，见证**不得**触发任何自动重放（否则就把 §1.B 的「绝不重放」破坏掉）。
  - 若编辑器进程被**硬杀**，最后一次写可能还在缓冲里；要每步 `Flush`/落盘（或改成 per-id 的追加式步骤日志）。
  - 它把「死在第几步」从**事后重建**降级为**当场读取**；它**不**让图可续建 —— 续建仍是人工逐节点（§3 Step 3）。

---

## 5. 证据索引（file:line）

**闸门 A（派发）**
- `tools/authoring/author.py:364-380`（journal/claim）；`:257-258`（bridge-request）；`:277`（helper-request）；`:373`（INCOMPLETE_CLAIM）；`:375`（ID_CONFLICT）；`:378`（OUTCOME_UNKNOWN）；`:393`（outcomeUncertain 传播）；`:401`（无条件写 result）
- `tools/editor-bridge/elevated-request.py:105-122`（提交标记 + pending→rename）
- `tools/editor-bridge/elevated-runner.ps1:639-653`（`Get-AuthorGraphDispatch`，`:651` 拒重放）；`:754-770`（`Invoke-FixedAuthorGraph`，`:769` finally 只放锁）
- `tools/authoring/graph-elevated-once.ps1:24`（attempt 标记）；`:40`（fallback `outcomeUncertain`）；`:44`（回执独占）
- `tools/authoring/graph-launch.ps1:15`（EXISTING_RESPONSE）；`:28`（WAIT_EXPIRED）；`:32`（fallback）
- `tools/authoring/graph-transport.ps1:24-26`（45s 窗口）；`:59`（写）；`:60-64`（阶段不推进）；`:67`（RESPONSE_TIMEOUT）；`:72-73`（catch / outcomeUncertain）

**闸门 B（变更）**
- `tools/editor-bridge/Adapter/EditorAdapter.cs:30-32`（`spent`/`Spent`/`Spend`）
- `tools/editor-bridge/Adapter/AuthoringGraph.cs:224-225, 309-316, 385-386, 436-451, 456-477, 533-558, 615-651, 737-756, 586/718/819`
- `tools/editor-bridge/ManagedBridge/BridgeServer.cs:37`（Lease=5min）；`:59`（`_adapter=new()`）；`:127`（CleanupForLease 调用）；`:136-139`（lease-closed + `_completed`）
- `tools/editor-bridge/ManagedBridge/Entry.cs:73`（新 server）；`:186-189`（scope 重放/上限）
- `tools/editor-bridge/Adapter/AdapterLease.cs:12-31`（清理不碰图）

**闸门 C（内容）**
- `tools/editor-bridge/Adapter/AuthoringGraph.cs:735`（plan 要求空图）；`:321`（add-node 计数）；`:299`（bind 计数）；`:276-278, 294-296`（ready）
- `tools/editor-bridge/Adapter/OwnedGraphDelete.cs:174`（引用相等谓词 → `modelMatched` 恒 0；全文见 `GRAPH-DELETE-PROBE.md` §0.1/§1）

**残留与产物**
- `tools/editor-bridge/Adapter/EditorAdapter.cs:914-951`（ExportResource；`:919` 每 lease 每 id 一次；`:927` .gia 路径；`:935-936` 异步不回重试）
- `tools/editor-bridge/ManagedBridge/BridgeServer.cs:530-531`（dispatcher.InvokeAsync）；`:549`（author-graph 的 export 目录）；`:650-653`（adapter 异常 → 裸串 `Error`）
- `tools/editor-bridge/inspect-graph.py:61`（.gia 的 `nodeCount`）
- `tools/editor-bridge/Adapter/AuthoringGraph.cs:964`（`ur7KK2NiYZ4` 唯一使用点）；`:95-108`（动作表，无删节点）
- `tools/authoring/author.py:472-548`（graph CLI 子命令形状）

**真机语料（`.runtime/`，Bash 遍历）**
- `.runtime/authoring/requests/`：764 目录；`result.json` 缺 **0**；`elevated-response.json` 缺 **0**；`outcomeUncertain` **72**；`ok:false` **104**
- `.runtime/authoring/requests/e513fc0df58a35f2b8aeb018abe5b0df/`（FARM_V2 build-plan，13 nodes/15 edges/11 values，values 段抛 `EDITOR_BINDING_PROFILE_UNREGISTERED_SYMBOL`）
- `.runtime/authoring/requests/{38549d2e…,4dae5cab…,93e7d1b8…}/`（`stage:send` + `backend.outcomeUncertain:true`）
- 测试佐证：`tools/authoring/test_author.py:28-60`（`replayed`/`OUTCOME_UNKNOWN`/不重试）；`tools/authoring/test-graph-transport-window.ps1`（窗口 WHY 段）

---

## 6. 边界与盲区（未证 / 没搜到的地方）

- **未连桥、未发报文、未触碰游戏/编辑器**：本文件所有结论来自源码与 `.runtime/` 语料。§4 的改动**未实现、未验证**。
- **「无回滚」的检索范围**：`grep -rln "rollback|Rollback|undo"` 只覆盖 `tools/editor-bridge/Adapter/` 与
  `ManagedBridge/`；唯一命中是 `ReopenContentEvidence.cs:103` 的一句注释。**本文件未主张「整个工程都没有」**。
- **「无删节点」的检索范围**：`AuthoringGraph.cs` 的 `ValidateAuthorGraph` 动作表（`:95-108`）与
  `tools/authoring/author.py:57-58` 的 `GRAPH_ACTIONS`。**未**穷举 profile 里是否存在某个未接线的原生删节点符号。
- **FARM_V2 的「13/15 已落地」是**由**当时**的代码路径（values 段在 nodes/edges 之后）推出，**不是**事后读回：
  现存 journal 里**没有**对该图 `MW_API_FARM_V2`（graphId 1073741826）在失败**之后**的 `inspect` 记录
  （最后一次 `lookup` 在 `fc35d5a38989ca…`，时间 `16:02:15Z`，**早于** build 的 `16:04:28Z`，`nodeCount=0`）。
  ⇒ 「它今天是不是还半成品」**本文件不下结论**；下结论需要一次真机读回。
- **`1094713345` / `1073741826` 这类 id 的跨关卡复用**（同一 id 出现在多个图名下）会影响「按 id 认回图」，
  与 HARD RULES 的 id 归属红线一致；本文件只按 `requestId` 与 journal 讲话，不靠 id 归属。

---

*分析于 2026-10-10。仅静态阅读 + `.runtime/` 只读语料。未改码，未发请求，未启停任何进程。*
