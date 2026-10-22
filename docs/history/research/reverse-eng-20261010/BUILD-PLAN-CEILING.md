> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #9 — 批处理图（`build-plan`）的真实尺寸天花板：核实与延伸

**产出日期**：2026-10-10（核对 checkout：`tools/editor-bridge/Adapter/AuthoringGraph.cs` = 1040 行）
**口径**：**纯离线、纯只读**。全程**未连桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未注入、未写任何存档、未构建**。遵从 HARD RULES。
**读的源**：①`AuthoringGraph.cs`（全文逐行）；②`EditorAdapter.cs`（`spent`/`Spend`/`Spent`/`B`）；③`ManagedBridge/BridgeServer.cs`（帧长/租约）；④`ManagedBridge/Entry.cs`（scope 生命周期）；⑤`elevated-runner.ps1`（pin 文件集与**每次派发**的重哈希闸）；⑥`authoring/graph-transport.ps1`（客户端请求行闸与超时窗）；⑦`gameplan/plan.py`（本地闸）；⑧**真机回执** `.runtime/scratch/farm-demo-build.json` 与其 journal `.runtime/authoring/requests/<requestId>/claim.json`（`startedUtc` 时间戳）；⑨`PROGRESS.md`。

> 按 `CLAUDE.md` §一.3：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。层别在每个数字旁标注：**【源码】**＝本次逐行读出；**【真机】**＝仓内回执时间戳；**【文档】**＝`PROGRESS.md` 原话。行号＝本次 checkout 实测。
> **「搜不到」≠「不存在」**（`CLAUDE.md:23`）；本轮检索范围见 §6。

**与姊妹文件的分工**（本文件**不重述**它们已给的清单，只**核实其行号**并**延伸**出真机成本）：
- `BUILD-PLAN-LIMITS.md`（#8）＝`build-plan` 单独一条动作的硬边界。
- `GRAPH-SIZE-LIMITS.md`（#10）＝`AuthoringGraph.cs` 全部尺寸约束 + 派发成本。
- **本文件（#9）＝把「每派发天花板」用一份真机回执的成本数字**（不是 `PROGRESS.md` 的散文）**核实并延伸**，回答「第二次 `build-plan` 能否扩图」与「一次派发能表达多大游戏＝几号数字」。

---

## 0. 一句话结论

1. **`build-plan` 自己的硬闸：图必须为空（`AuthoringGraph.cs:144` 校验 / `:735` 实现）；`plan.nodes ∈ [1,128]`（`:147-149`，`>128` 的判据落在 `:148`）；同一张图只允许一次 `build-plan`（`:737` 读、`:756` 烧）**。**边与常量的条数没有独立上限**（边循环 `:782-791`、常量循环 `:792-818` 都只做逐条校验），它们的真正上界是**一条请求行的字节数**。
2. **每次派发都重哈希整套 pin 集是源码事实**：`author-graph` 的每次派发都经 `Invoke-FixedAuthorGraph`（`elevated-runner.ps1:837`）→ **`:840` `Lock-DispatchPins`**（重新打开并逐文件 SHA-256 比对**全部 2082 个 pin 文件**）。**这次哈希与图大小无关**，是每派发固定付费。
3. **真机每派发成本 ≈ 12.4–13.7 s**（首次用**回执时间戳**量出，不是散文）：`farm-demo-build.json` 的 5 个 requestId 在 `.runtime/authoring/requests/<id>/claim.json` 里的 `startedUtc` 相邻差为 `12.839 / 12.384 / 12.823 / 13.680 s`（均值 **12.93 s**）。⇒ 一个 300 s 租约可容 **⌊300/12.93⌋ = 23 次**派发（**真机**）；用文档保守值 16 s 得 18 次；用最坏的旧值 63 s 得 4 次（`PROGRESS.md:706`）。
4. **第二次 `build-plan` 扩同一张图：不能。** 两道独立闸（空图闸 + attempt 闸）叠加；attempt 闸随租约重置，**空图闸不重置** ⇒ **最终判据是「不能」**（§3 全证据）。
5. **一次派发能表达的最大游戏（数字）**：适配器硬顶 **128 个节点**（`:148`）；**稠密图（每节点带 1 条边 + 1 个常量）实际 ≈ 96 个节点**——先撞 16000 字节的请求行（`graph-transport.ps1:51`）。再大，**当前没有任何作者原语**。

---

## 1. `build-plan` 与全图面强制执行的每一条限制（file:line，本次逐行核实）

### 1.1 节点数量

| # | 限制 | 值 | 具名码 | file:line |
|---|---|---|---|---|
| N1 | `build-plan` 的 `plan.nodes` 长度 ∈ `[1,128]` | 128 | `AUTHOR_PLAN_NODES` | **校验 `AuthoringGraph.cs:147-149`（`>128` 在 `:148`）** |
| N2 | `add-node` 声明的 `expectedNodeCount ≤ 127` | 127 | `AUTHOR_REQUIRED_UINT` | `:130` |
| N3 | `bind` 声明的 `expectedNodeCount ≤ 128` 且 `≠0` | 128 | `AUTHOR_REQUIRED_UINT` / `AUTHOR_EMPTY_BIND` | `:135` |
| N4 | **全图闸**：走得到它的动作，`nodes.Count > 128` 即拒 | 128 | `AUTHOR_GRAPH_NODE_LIMIT_EXCEEDED` | `:287` |
| N5 | **`countGateReady` 豁免**：仅当 `bind` 且已烧 `author-count-ready` 且节点定义多重集 = 13 个 `{1,1,2,2,2,14,14,71,73,79,82,83,230}` 时，跳过 N4 | 13 | （豁免，无码） | 读 **`:276-278`**；烧 **`:718`** |

**三条 128 为何汇合**：`build-plan` 在 **`:268-271` 早退**（`return State("plan-built-…")`），**到不了 `:287`**，用它自己那条 `:148`；`add-node` 到得了 `:287`，而它声明的计数被 `:130` 卡在 127 ⇒ 加完最多 128。**两条路在同一处 128 汇合。**

**`countGateReady` 对 `build-plan` 无用**：`countGateReady` 由 `:276` 计算，而 `build-plan`（`:268`）、`build-count-gate`（`:272`）都在此**之前 `return`**，**根本执行不到 `:276`**；且 `:276` 的首个合取项是 `action=="bind"`。⇒ **`build-plan` 得不到任何豁免**（它本就被 `:148` 卡在 128，无妨）。

### 1.2 边 / 常量：**无独立条数上限**

- `build-plan` 的边循环（`:782-791`）与常量循环（`:792-818`）**都不数条数**，逐条只做字段/下标检查（下表 L-edge / L-value）。⇒ 「边能到多少、常量能到多少」的答案**不在 C# 里**，在 §2 的**请求行字节**里。
- 逐条 `connect`（`:393-453`）与 `LinkMap` 查询（`:442-443`）同样**从不与阈值比较**。

### 1.3 逐字段校验（信封 / 节点 / 边 / 常量）

| # | 限制 | 值 | 具名码 | file:line |
|---|---|---|---|---|
| F1 | 图名正则 `MW_API_[A-Za-z0-9_]{1,48}` | — | `AUTHOR_NAME_INVALID` | `:114` |
| F2 | 动作白名单 + **未知/重复字段即拒** | 见 `fields` 表 | `AUTHOR_UNKNOWN_OR_DUPLICATE_FIELD` | `:95-108` / `:113` |
| F3 | 非 create/lookup 时 `graphId ≠ 0` | — | `AUTHOR_GRAPH_ID_ZERO` | `:115` |
| F4 | `add-node` 布局 `x,y` 有限且 `abs ≤ 10000` | 10000 | `AUTHOR_LAYOUT_INVALID:<key>` | `:131-133` |
| F5 | `build-print` 要求空图 | `expectedNodeCount==0` | `AUTHOR_PRINT_REQUIRES_EMPTY_GRAPH` | `:137` |
| F6 | **`build-plan` 要求空图** | `expectedNodeCount==0` | `AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH` | **校验 `:144`；实现 `:735`** |
| F7 | `plan` 须是对象、`nodes` 须是非空数组 | — | `AUTHOR_REQUIRED_OBJECT:plan` / `AUTHOR_PLAN_NODES` | `:145-146` / `:147-149` |
| F8 | `set-print` 文本长度 | `≤1024` | `AUTHOR_TEXT_TOO_LONG` | `:151` |
| F9 | `set-value` 端口种类须 = 3、`portIndex` 必填、`expect` 须 uint32 | — | `AUTHOR_VALUE_PORT_KIND_UNSUPPORTED` / `AUTHOR_REQUIRED_UINT` / `AUTHOR_EXPECT_INVALID` | `:163` / `:170` / `:179-181` |
| F10 | `set-value` `slot ∈ {auto,int,uint,enum,float,bool,string}` | — | `AUTHOR_VALUE_SLOT_UNSUPPORTED` | `:41` / `:184-186` |
| F11 | `build-count-gate` 的 `limit ∈ [1,1000000]`；`period ∈ [0.1,3600]` | 见左 | `AUTHOR_COUNT_LIMIT_INVALID` / `AUTHOR_COUNT_PERIOD_INVALID` | `:191` / `:193` |
| F12 | `connect`/`disconnect` 端口种类 ∈ `[1,4]` | 1..4 | `AUTHOR_EDGE_PORT_KIND_UNSUPPORTED:<side>` | `:204-205` |
| F13 | 标量载荷：`float` 有限且 `abs ≤ 1e9`；`string ≤ 1024`；`list ≤ 64`（`AuthorListLimit`） | 见左 | `AUTHOR_VALUE_FLOAT_INVALID` / `AUTHOR_VALUE_STRING_INVALID` / `AUTHOR_VALUE_LIST_INVALID` | `:64` / `:68` / `:44`+`:72` |
| F14 | `list` 元素只能是标量 `int/uint/float/string`（entity/vector/dict 拒） | — | `AUTHOR_VALUE_LIST_ELEMENT_UNSUPPORTED` | `:73-82` |
| F15 | 自环拒；源须输出 `{2,4}`、目标须输入 `{1,3}`；执行边 `fromIndex ≤ 1 && toIndex == 0` | — | `AUTHOR_SELF_LINK_REFUSED` / `AUTHOR_EDGE_SOURCE_NOT_OUTPUT` / `_TARGET_NOT_INPUT` / `AUTHOR_FLOW_PORT_UNSUPPORTED` | `:397` / `:398-399` / `:402-403` |
| F16 | 数据边两端声明类型须相等（**任一端泛型 type 0 除外**） | — | `AUTHOR_EDGE_TYPE_MISMATCH:<t>:<g>!<t>:<g>` | `:432-434` |
| F17 | 边/常量端口须在**活注册表**声明；常量声明类型须与 `expect` 一致 | — | `AUTHOR_EDGE_PORT_UNKNOWN` / `AUTHOR_VALUE_PORT_UNKNOWN` / `AUTHOR_VALUE_TYPE_MISMATCH` | `:422-425` / `:376-377` / `:381-382` |
| F18 | 写后**强制读回比对**（int/enum/bool/float 四支；float 按 float32 位精确） | 严格相等 | `AUTHOR_VALUE_READBACK_MISMATCH:*` | `:915` / `:927` / `:939` / `:953` |
| L-edge | `build-plan` 每条边须带 6 个 int 字段 `from,to,fromKind,fromIndex,toKind,toIndex`（缺一即拒）；下标 ∈ `[0,节点数)` 且 `from != to` | — | `AUTHOR_PLAN_EDGE_SPEC:<key>` / `AUTHOR_PLAN_EDGE_INDEX` | `:784-785` / `:787-788` |
| L-value | `build-plan` 每常量须带 `node∈[0,节点数)` / `portIndex`(int) / `slot`(string) / `value`(object)；string 支文本 `≤1024` | 1024 | `AUTHOR_PLAN_VALUE_NODE` / `_PORT` / `_SPEC` / `AUTHOR_PLAN_VALUE_TEXT_TOO_LONG` | `:794-795` / `:796-797` / `:798-800` / `:812` |
| L-list | **`build-plan` 的常量不支持 `list`**：`:815` 只调 `AuthorWriteScalar`，而它**没有 list 分支**（`default` 抛 `:970`）；list 只在 `set-value` 路径（`:1027-1031`） | — | `AUTHOR_VALUE_SLOT_UNSUPPORTED` | `:815` / `:970` / `:1010`+`:1027` |

### 1.4 操作顺序本身是约束（`BuildAuthorPlan :733-820`）

`空图检查 :735` → `重放闸 :737` → **先把全部节点定义在活注册表解析完**（`:748-755`，任一解析不出即**整图画废**，不写半张）→ **烧 attempt `:756`** → 加节点 `:775-781` → 连线 `:782-791` → 写常量 `:792-818` → `标记 ready :819`。

顺序 `nodes → edges → values` 是 `:729-732` 明写的**必需**：泛型数据引脚（type 0）由原生编辑器从**被连的兄弟节点**物化，往**尚未物化**的泛型引脚写常量，正是要拒的「加得进去配不出效果」。

### 1.5 本轮**核实**出的两处姊妹文件未说透的不对称

1. **`build-plan` 不检查布局坐标。** F4 的 `abs ≤ 10000` 只在 `add-node` 分支（`:131-133`）；`build-plan` 的信封校验段（`:140-150`）不查 `x/y`，`BuildAuthorPlan` 里 `x/y` 只是 `TryGetProperty → GetDouble`、缺省 `0`、**无有限性/幅值检查**（`:777-778`）。⇒ **排期不能假设「`add-node` 会替你挡坐标」，`build-plan` 不挡。**
2. **`build-plan` 的 string 常量走「只写不读回」是必需，不是风格。** `AuthorWriteScalar` 的 `string` 支（`:957-967`）在 `:964` 调 `B("ur7KK2NiYZ4")` 做读回；而本次核实 **`ur7KK2NiYZ4` 在 `EditorBindingProfile.Generated.cs` 里 0 命中**（`grep -c` = 0），`B()`（`EditorAdapter.cs:87`）对未绑定符号会抛。⇒ **该 string 支一旦走到就会抛**，因此 `build-plan`（`:804-813`）**绕开**它、直接用已证 string setter `MfLKK0bLIju`（在 profile 里 2 命中）写而不读回。`:805-806` 的注释说「共享路径会**按名拒**」**并不准确**——它实际是**未绑定符号抛异常**，效果（走不通）相同但机理不同。（此点与 #8 §1.3 的「string 是唯一没有读回校验的一支」结论**一致**，仅补正机理。）

---

## 2. 每派发的实用天花板：用**真机回执**（不是散文）量出

### 2.1 每派发的固定成本 = 一次全 pin 集重哈希 **【源码 + 真机】**

**源码事实**：`author-graph` 每次派发走 `Invoke-FixedAuthorGraph`（`elevated-runner.ps1:837`），其体内 **`:840` `Lock-DispatchPins $projectRoot $nativePython $dispatchPins`**。`Lock-DispatchPins`（`:702` 起）对 `Get-DispatchPinFiles`（**`:657` 起**）返回的**每一个**文件重新打开、`Get-StreamSha256` 并与启动时记录比对；文件集不变或哈希变化即 `DISPATCH_PIN_CHANGED`。⇒ **每次派发重哈希整套 pin 集——与图大小无关，固定付费。**（HARD-严格：`:840` 的 `Lock-…` 是**每次请求**都执行，`New-DispatchPins` 的**首次**全量哈希在 runner 启动 `:869`。）

**pin 集规模 = 2082 文件**【文档】：`PROGRESS.md:276`（`pins 2082`）、`:519`（`pinCount 仍 2082`）、`:135`（`2082 pins`）。每次派发都重哈希这 2082 个文件。

**pin 哈希耗时（三个口径，本文件并列，不合并）**：
| 值 | 口径 | 出处 |
|---|---|---|
| **≈16 s**（每派发） | 【文档】 | `PROGRESS.md:226`「每条 graph 派发都要重算 2082 个 pin 的哈希（≈16 秒）」 |
| **≈50 s**（pin）/ **≈63 s**（整次请求） | 【真机】慢的那天 | `PROGRESS.md:706`「一次图请求 ≈ 63 秒（约 50 秒对 2082 文件做 pin 哈希 + 约 10 秒图）」 |

### 2.2 真机整派发成本 ≈ **12.93 s**（**新增：首次用回执时间戳量出**）

`farm-demo-build.json` 记录 R267 一次租约内 5 步全过（`create → lookup → build-plan → inspect → export`），每步一个 `requestId`。各 `requestId` 的 journal `.runtime/authoring/requests/<id>/claim.json` 里有 `startedUtc`（客户端认领时刻）：

| 步 | requestId | claim `startedUtc`（UTC） | 与上一步差 |
|---|---|---|---|
| create | `f1b599f2…` | 16:27:38.7867 | — |
| lookup | `a8323efd…` | 16:27:51.6258 | **12.839 s** |
| build-plan | `469f7e67…` | 16:28:04.0099 | **12.384 s** |
| inspect | `0bea1e93…` | 16:28:16.8328 | **12.823 s** |
| export | `bd4e2a0a…` | 16:28:30.5125 | **13.680 s** |

**每次派发（含该次 pin 重哈希 + 原生图工作 + 客户端往返）≈ 12.4–13.7 s，均值 12.93 s**（5 步总跨度 16:27:38.787 → 16:28:30.513 = **51.73 s**）。**这是本文件相对 #8/#10 的核心延伸**：那两份用的是 `PROGRESS.md` 的 16 s/50 s 散文；这里用的是**回执里客户端认领的时间戳**。

> **关键观察（可从上表推出）**：`lookup`（纯读、无原生图工作）一步也要 **12.384 s** ⇒ **pin 重哈希 + 往返开销占了这 ~12.9 s 的绝大部分**；一个 **15 节点 / 17 边 / 13 常量**的 `build-plan` 一步是 **12.823 s**，与纯读的 lookup **几乎相同** ⇒ **这规模的原生图工作 ≲ 1 s**。⇒ **图工作便宜、pin 重哈希贵**，正是「把 N 条指令并成 1 次派发」的价值所在。

### 2.3 一次租约能放几次派发（由 2.2 重算）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

租约 = **300 s**【源码】：`BridgeServer.cs:37` `Lease = TimeSpan.FromMinutes(5)`。逐节点路径下一个派发只做 1 个 op ⇒ **一租约最多 23（真机）/ 18（文档）/ 4（旧最坏）个 op**，还要扣掉 `create/lookup/export/bind`。**43 条指令的逐节点路径在这些口径下都超租约**，这就是 `build-plan` 存在的理由（`PROGRESS.md:226`）。

### 2.4 批处理把它压成 1 次派发后的**每派发**图规模上限

`build-plan` 把整张图并成 **1 个派发** ⇒ 12.93 s 的 pin 重哈希只付一次 ⇒ 「每派发图规模」不再由租约决定，而由**三堵墙取小**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**请求行字节预算（用真机 demo 的计划实测标定）**：`.runtime/scratch/MW_API_FARM_DEMO-plan.json` = 15 节点 / 17 边 / 13 常量；紧凑序列化（`separators=(',',':')`，与 `ConvertTo-Json -Compress` 同形）**2507 B**；加信封（`id/op/nonce/action/name/graphId/expectedNodeCount/plan`，含 64 位 hex nonce 占位）**2742 B** ⇒ 信封 ≈ 235 B。**每元素实测均值**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**⇒ 稠密图 ≈ 96 节点就撞 16000 B，早于 128；纯节点图能装满 128。**

**两个必须一起说**：①一条 `string` 常量上限 **1024 字符**（`:812`）≈ 1 KB，几条长文本就把预算吃到见底 ⇒ 含长文本的图节点数**远低于 96**。②请求行是**一整行、无分块续传**：客户端 `ConvertTo-Json -Compress -Depth 12`（`graph-transport.ps1:50`）后，**`>16000 B` 本地抛 `REQUEST_TOO_LARGE`（`:51`）**，服务端 **16 KiB** 截断抛 `line_too_long`（`BridgeServer.cs:34` `MaxLineBytes=16*1024`；`:205`）。

**45 s 响应窗不是当前瓶颈**：`Get-GraphResponseWindowMs` 对所有 graph op 一律返回 **45000 ms**（`graph-transport.ps1:24-25`）。真机上 15 节点的整派发（含 pin 重哈希）≈ 12.9 s，其中图工作 ≲ 1 s ⇒ **45 s 窗在 128 节点以内不会先于 `:148` 触发**（线性外推 128 节点 ≈ 数秒图工作）。**但这是外推，非实测 100+ 节点耗时**（§6）。

---

## 3. 第二次 `build-plan` 能不能扩同一张图？—— **不能**

**答**：**不能**。同一张图上的第二次 `build-plan` 被**两道独立、互相冗余的闸**拒绝，且其中一道**不随租约重置**。

| 闸 | 语义 | file:line | 跨租约（换 scope/重注入）是否仍拒？ |
|---|---|---|---|
| **G-a 空图要求** | `build-plan` 只在**空图**上跑；第一次计划建成后图非空 | 实现 `:735`；信封 `:144` | **是**——「图里有节点」活在**编辑器内存**里，与内存里的 attempt 标记无关，重注入后图仍非空 ⇒ 照样拒 |
| **G-b attempt 已烧** | `Spent("author-plan", graphId)` 命中即 `AUTHOR_PLAN_ALREADY_ATTEMPTED`；attempt 在**首次原生变更前**烧（`:756` 注释原文「before the first native mutation; a partial failure never replays」） | 读 `:737`；烧 `:756` | **看租约**——标记活在适配器实例里，见下 |

**G-b 标记的作用域**：`spent` 是 `EditorAdapter` 的**实例字段** `HashSet<string>`（`EditorAdapter.cs:30`；`Spent :31` / `Spend :32`）；适配器随 `BridgeServer` 一起 `new`，而 `BridgeServer` 在**每次启动/租约**由 `Entry` 新建（`Entry.cs:207-208` `server=new BridgeServer(settings,facts,pipe,settingsDirectory!)`）⇒ **`author-plan` 标记的寿命 = 一个租约**。换租约拿新实例后 **G-b 放行**，但 **G-a 仍拒**（图非空）。

**⇒ 两道闸叠加的结论 = 「不能扩」**：同租约内 G-b 拒；新租约 G-a 拒。**没有第三条路**——

- 用别的动作顶穿 128？不能：`add-node` 声明计数被卡在 **127**（`:130`），全图闸 **`:287`** 在 129 之前就拒「128」；**128 是作者面真天花板**（§4）。
- 靠 `countGateReady` 豁免？不惠及 `build-plan`：豁免判据在 `:276`，`build-plan` 在 `:268` 就 `return`，够不到；且 `:276` 要求 `action=="bind"`（§1.1）。
- **`author-plan-ready` 是只写不读**：本次全检索 `tools/` 下 `.cs/.py/.ps1`，`grep "author-plan-ready"` **仅 `:819` 一处**（即 `Spend` 调用本身，**无任何 `Spent` 读它**）；对照 `author-count-ready` 有 `:276` 读 + `:718` 写两处。⇒ **`build-plan` 的图得不到任何豁免/续建语义**。

> 与 #8 §3.1 / #10 §3 的结论**一致**；本文件补的是**真机未复现过「第二次被拒」**这一前提（`PROGRESS.md:112-130` 的 demo 只用过一次 `build-plan`）——**本轮遵从 HARD RULES 不做真机动作坐实**。

---

## 4. 一次派发能表达的最大游戏 —— **数字**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- **一个含「事件 → 逻辑 → 常量」的稠密玩法图，今天一次 `build-plan` 的现实上界 ≈ 96 个节点**（每条边 68.6 B、每个 int/短串常量 63.4 B 是实测均值；含长字符串时更低）。
- **一个纯节点、少连线的稀疏图可到 128 个节点**（≈4.4 KB，宽裕）。
- **再大：当前没有任何作者原语**——不是「没挖到」，是**三条 128 上限（`:148` / `:130`+1 / `:287`）在同一处汇合**的**负结论**（§3）。
- 参照：真机 verified 的 `MW_API_FARM_DEMO` = **15 节点 / 17 边 / 13 常量**，即今天已验证玩法规模的 **~1/6**（按节点口径距 96，距 128 更远）。

**一句话数字结论**：**今天一次派发能表达的最大游戏 = 128 个节点（硬顶）/ ≈96 个节点（稠密现实）。**

---

## 5. 本文件相对 #8 / #10 的**核实**与**延伸**

**核实（逐行重读，行号一致）**：`:144` 空图、`:148` 的 128、`:130` 的 127、`:287` 的全图闸、`:276-278` 的 `countGateReady`、`:737/:756` 的 attempt 闸、`:819` 的 `author-plan-ready`、`graph-transport.ps1:51` 的 16000 B、`BridgeServer.cs:34` 的 16 KiB、`:37` 的 5 min 租约、`EditorAdapter.cs:30-32` 的 `spent/Spent/Spend`——**全部本次实读，行号与 #8/#10 相符**。

**延伸（本文件新增）**：
1. **每派发成本改用真机回执时间戳**（§2.2）：`12.4–13.7 s`（均值 12.93 s），比 doc 的 16 s 更紧、远低于旧的 63 s 最坏值。
2. **证明「图工作便宜、pin 重哈希贵」**：纯读 `lookup` 一步 12.384 s ≈ 15 节点 `build-plan` 一步 12.823 s（§2.2）——**原生图工作 ≲ 1 s**。这解释了批处理的全部收益。
3. **每元素字节均值实测**：node 32.5 / edge 68.6 / value 63.4 B（§2.4，与 #8 的 31.5/67.5/62.3 同量级），稠密上界 **≈96**（#8 说 ~97，实测取整一致）。
4. **两处不对称核实**（§1.5）：`build-plan` 不查布局坐标；`build-plan` 的 string 绕过是**必需**（共享路径的 string 读回符号 `ur7KK2NiYZ4` 未绑定，`Generated.cs` 0 命中）。
5. **`author-plan-ready` 只写不读**在 `tools/` 全域再次确认为 1 命中（仅 `:819`）。

---

## 6. 局限与不吹（本轮搜过什么 / 没搜什么）

- **检索范围**：`tools/editor-bridge/Adapter/AuthoringGraph.cs`（全文 1040 行）、`EditorAdapter.cs`（`B`/`spent`）、`EditorBindingProfile.Generated.cs`（仅 `grep -c`）、`ManagedBridge/BridgeServer.cs`（帧长/租约）、`ManagedBridge/Entry.cs`（server 生命周期）、`elevated-runner.ps1`（pin 文件集与 `Lock-DispatchPins`）、`authoring/graph-transport.ps1`、`gameplan/plan.py`、`.runtime/scratch/farm-demo-build.json` + 5 个 `journal claim.json`、`PROGRESS.md`。**未读任何 DLL 字节，未跑构建，未连桥，未发报文，未做任何真机动作。**
- **`author-plan-ready` 只写不读**是**检索范围内**（`tools/` 全部 `.cs/.py/.ps1`）的结论，**不含**已编译 DLL 与 `.runtime/` 下反编译副本；若某 DLL 另有读取，本结论不覆盖（**「搜不到」≠「不存在」**，`CLAUDE.md:23`）。
- **每派发 12.93 s 是单次回执（R267）**：字节预算与 45 s 墙钟是**外推**，以真机计划 15/17/13 的**均值**线性外推到 96/128；真实之字形布局、坐标位数、常量分布、串长都会让阈值漂移 ⇒ **±10% 量级，非精确阈值**。
- **「第二次 `build-plan` 被拒」是源码级结论**（两道闸逐行读）；真机只用过一次 `build-plan`，**未真机复现「第二次被拒」**——本轮遵从 HARD RULES **不做**该动作。
- **本文件只新增自己**；未改 `STRUCTURE.md`、未改 `PROGRESS*.md`、未改任何源码、未改任何测试（**无代码变更 ⇒ 无测试可跑**）。
