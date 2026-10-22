> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #10 挖 — 一张节点图到底能装多大（AuthoringGraph 的每一条尺寸限制）

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档、未构建、未注入**。遵从任务 HARD RULES。
**读的源**：①`tools/editor-bridge/Adapter/AuthoringGraph.cs`（全文，1041 行，逐行）；②`tools/editor-bridge/Adapter/EditorAdapter.cs`（`spent`/`Spend`/`Spent` 定义）；③`tools/editor-bridge/ManagedBridge/BridgeServer.cs`（帧长/租约）；④`tools/editor-bridge/ManagedBridge/Entry.cs`（scope 生命周期）；⑤`tools/editor-bridge/elevated-runner.ps1`（pin 文件集）；⑥`tools/authoring/graph-transport.ps1`（客户端请求行闸）；⑦`tools/authoring/author.py`、`tools/gameplan/plan.py`（调用侧本地闸）；⑧`PROGRESS.md`（真机数字）。

> 按 `CLAUDE.md` §一.3：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。本文的限制**全部从源码读出（静态）**，凡真机数字都注明出处行号。**行号＝本次 checkout 实测**。
> 与姊妹文件 `BUILD-PLAN-LIMITS.md`（#8，只讲 `build-plan`）的分工：**本文覆盖 `AuthoringGraph.cs` 里会施加尺寸/容量约束的每一条规则（不只 `build-plan`）**，并把它们摆进**操作顺序**与**派发成本**两把尺子里。

---

## 0. 一句话结论

- **适配器作者面能表达的图，上界是「128 个节点」。** 这个 128 由**三条互相照应的门**共同钉死：`build-plan` 单个计划 `plan.nodes ≤ 128`（`AuthoringGraph.cs:148`）；`add-node` 声明的 `expectedNodeCount ≤ 127`（`:130`）；全图闸 `nodes.Count > 128` 即拒（`:287`）。**没有任何作者动作路径能走到 129。**
- **边与常量没有独立的条数上限**——`build-plan` 的边循环（`:782-791`）与常量循环（`:792-818`）**不数条数**，逐条只做字段/下标检查。它们的真正天花板是**一条请求行的字节数**：客户端 **16000 B**（`graph-transport.ps1:51` `REQUEST_TOO_LARGE`）、服务端 **16 KiB = 16384 B**（`BridgeServer.cs:34` `MaxLineBytes`，`:205-207` `line_too_long`）。一个「每节点带一条边 + 一个常量」的稠密图 **≈97 个节点**就撞 16000 B，**早于 128**。
- **派发成本是「每次派发固定付费、与图大小无关」**：一次派发要对**固定 2082 个文件的 pin 集**重算 SHA-256（`elevated-runner.ps1:590-620` `Get-DispatchPinFiles`）——文档口径 **≈16 s**、真机实测 **≈50 s**（`PROGRESS.md:620/679`）。scope 租约 **300 s**（`BridgeServer.cs:37`）。⇒ 逐节点路径下 **一次派发只做 1 个 op**，一个租约理论最多 **18 个 op**、真机 **≈4 个 op**（`PROGRESS.md:679` 原话「一个 lease 最多约 4 次请求」）。**这正是 `build-plan` 存在的理由**：把整张图并成 **1 次派发**，16 s 的哈希只付一次。
- **第二次 `build-plan` 扩同一张图：不能。** 两道独立闸——①图非空即拒（`:735` / 校验 `:144`，`AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH`），②attempt 已烧即拒（`:737` 读、`:756` 烧，`AUTHOR_PLAN_ALREADY_ATTEMPTED`）。第②道随租约重置，**第①道不随租约重置**（图内容活在编辑器内存里）⇒ 结论是**不能**（§3 给全证据）。
- **今天能表达的游戏规模（一句话）**：**一次 `build-plan` 派发能把一张「约 60–97 节点、每节点带边带常量」的图（或「≤128 节点、无连线」的稀图）一次性建出来并绑定到一个实体**；要表达比这更大的玩法，**当前没有任何作者原语**（不是「没挖到」，是三条上限在同一处汇合的负结论，§4）。

---

## 1. `AuthoringGraph.cs` 施加的每一条尺寸限制（file:line）

按「约束对象」分组。**「值」列是硬数字，「码」列是越界时抛出的具名拒绝。**

### 1.1 节点数量

| # | 限制 | 值 | 具名码 | file:line |
|---|---|---|---|---|
| N1 | `build-plan` 的 `plan.nodes` 长度 | `[1, 128]` | `AUTHOR_PLAN_NODES` | `:147-149`（校验）；`BuildAuthorPlan` `:739` 取长度 |
| N2 | `add-node` 声明的 `expectedNodeCount` | `≤ 127` | `AUTHOR_REQUIRED_UINT` | `:130` |
| N3 | `bind` 声明的 `expectedNodeCount` | `≤ 128` 且 `≠0` | `AUTHOR_REQUIRED_UINT` / `AUTHOR_EMPTY_BIND` | `:135` |
| N4 | `bind` 时图内实际节点数须等于声明 | 严格相等 | `AUTHOR_NODE_COUNT_CONFLICT` | `:299` |
| N5 | `add-node` 时图内节点数须等于声明 | 严格相等 | `AUTHOR_NODE_COUNT_CONFLICT` | `:321` |
| N6 | **全图闸**：任何走得到它的动作，`nodes.Count > 128` 即拒 | `128` | `AUTHOR_GRAPH_NODE_LIMIT_EXCEEDED` | `:287` |
| N7 | `countGateReady` 豁免：定义多重集恰为 13 个 `{1,1,2,2,2,14,14,71,73,79,82,83,230}` 时跳过 N6 | 13 | —（豁免，无码） | `:276-278` |
| N8 | `build-print` 要求声明空图；建成后须恰为 2 节点 `{1,71}` | `0` → `2` | `AUTHOR_PRINT_REQUIRES_EMPTY_GRAPH` / `AUTHOR_PRINT_NODE_READBACK_FAILED` | `:137` / `:531` / `:585` |
| N9 | `build-count-gate` 要求空图；建成后须恰为 13 节点 | `0` → `13` | `AUTHOR_COUNT_REQUIRES_EMPTY_GRAPH` / `AUTHOR_COUNT_NODE_READBACK_FAILED` | `:613` / `:683` |

**三条 128 如何汇合**：`build-plan` 在 `:268-271` **早退**，**走不到** `:287` 的全图闸，所以它用自己那条 `:148` 的「≤128」；`add-node` **走得到** `:287`，而它声明的 `expectedNodeCount` 被 `:130` 卡在 **127** ⇒ 加完最多 128。**`build-plan` 的 128 与 `add-node` 路径的 127+1 在同一个 128 汇合**。

### 1.2 边的数量

**没有独立条数上限。** 证据：

- 逐条 `connect`/`disconnect`（`:393-453`）只做**单条边**的字段/端口校验（§1.4），**不数已存在的边数**。
- `build-plan` 的边循环（`:782-791`）对 `edges` 数组**逐条**处理，只做字段存在性与下标范围检查（`:784-788`），**不数条数**。
- 图的 `LinkMap` 只有“存在与否”查询（`:442-443`、`:448`），**从不与阈值比较**。

⇒ 「边能到多少」的答案**不在 C# 里**，而在 §2 的**请求行字节上限**里。

### 1.3 常量（值）的数量与形状

| # | 限制 | 值 | 具名码 | file:line |
|---|---|---|---|---|
| V1 | 标量载荷必须恰好一个 tagged key | 1 个 | `AUTHOR_VALUE_SHAPE_INVALID` | `:47-49` |
| V2 | `int` 载荷须为 Int32 | Int32 | `AUTHOR_VALUE_INT_INVALID` | `:52-54` |
| V3 | `uint` 载荷须为 UInt32 | UInt32 | `AUTHOR_VALUE_UINT_INVALID` | `:55-57` |
| V4 | `bool` 载荷须为 JSON true/false | — | `AUTHOR_VALUE_BOOL_INVALID` | `:58-61` |
| V5 | `float` 载荷须有限且 `abs ≤ 1e9` | 1e9 | `AUTHOR_VALUE_FLOAT_INVALID` | `:62-65` |
| V6 | `string` 载荷长度 | `≤ 1024` 字符 | `AUTHOR_VALUE_STRING_INVALID` | `:66-69` |
| V7 | `list` 载荷元素个数 | `≤ AuthorListLimit = 64` | `AUTHOR_VALUE_LIST_INVALID` | `:44` / `:70-72` |
| V8 | `list` 元素只能是标量 `int/uint/float/string`（**entity/vector/dict 一律拒**） | — | `AUTHOR_VALUE_LIST_ELEMENT_UNSUPPORTED` | `:73-82` |
| V9 | `set-print` 文本长度 | `≤ 1024` | `AUTHOR_TEXT_TOO_LONG` | `:151` |
| V10 | `build-plan` 常量走 string 支的文本长度 | `≤ 1024` | `AUTHOR_PLAN_VALUE_TEXT_TOO_LONG` | `:812` |
| V11 | `set-value` 的 `slot` 枚举 | `∈ AuthorValueSlots` | `AUTHOR_VALUE_SLOT_UNSUPPORTED` | `:41` / `:184-186` |
| V12 | 写后**强制读回比对**（int/enum/bool/float 四支；float 按 float32 位精确） | 严格相等 | `AUTHOR_VALUE_READBACK_MISMATCH:*` | `:915` / `:927` / `:939` / `:953` |
| V13 | **`build-plan` 不支持 `list`**（无 list 分支，落到 `default` 抛） | — | `AUTHOR_VALUE_SLOT_UNSUPPORTED` | `:814-816` 只调 `AuthorWriteScalar`；list 只在 `set-value` `:1027-1031` |

`AuthorValueSlots` = `{"auto","int","uint","enum","float","bool","string"}`（`:41`）；其中 `auto` 只映射已证存储码 **2（int）/ 6（enum）**，其余**按名拒绝**（`AuthorAutoSlot` `:879-888`）。

### 1.4 逐字段校验（信封 + 端口 + 布局）

| # | 限制 | 值 | 具名码 | file:line |
|---|---|---|---|---|
| F1 | 图名 `name` 正则 | `MW_API_[A-Za-z0-9_]{1,48}` | `AUTHOR_NAME_INVALID` | `:114` |
| F2 | 打印图名正则（更严） | `MW_API_SOL_L10_([a-z0-9]{6,16})_print` | `AUTHOR_PRINT_NAME_INVALID` | `:522-524` |
| F3 | 动作白名单 + **未知/重复字段即拒** | 见 `fields` 表 | `AUTHOR_UNKNOWN_OR_DUPLICATE_FIELD` | `:95-113` |
| F4 | `graphKind` 须在记录的四种内 | `{20000,20001,20002,20007}` | `AUTHOR_GRAPH_KIND_UNSUPPORTED` | `:17` / `:116-119` |
| F5 | 非 create/lookup 时 `graphId ≠ 0` | — | `AUTHOR_GRAPH_ID_ZERO` | `:115` |
| F6 | **布局坐标界**：`add-node` 的 `x,y` 须有限且 `abs ≤ 10000` | 10000 | `AUTHOR_LAYOUT_INVALID:<key>` | `:131-133` |
| F7 | `set-value` 端口种类须 = 3（输入数据） | 3 | `AUTHOR_VALUE_PORT_KIND_UNSUPPORTED` | `:163-164` |
| F8 | `set-value` 的 `portIndex` **必填**（不默认） | — | `AUTHOR_REQUIRED_UINT:portIndex` | `:170` |
| F9 | `set-value` 的 `expect.{serverParamType,genericId}` 须 uint32 | — | `AUTHOR_EXPECT_INVALID:<part>` | `:177-181` |
| F10 | `set-value` 端口须在活注册表声明 | — | `AUTHOR_VALUE_PORT_UNKNOWN:<k>:<i>` | `:376-377` |
| F11 | `set-value` 声明类型须与 `expect` 一致 | — | `AUTHOR_VALUE_TYPE_MISMATCH:<t>:<g>!<et>:<eg>` | `:381-382` |
| F12 | `connect`/`disconnect` 端口种类 ∈ `[1,4]` | 1..4 | `AUTHOR_EDGE_PORT_KIND_UNSUPPORTED:<side>` | `:204-205` |
| F13 | 自环拒绝 | — | `AUTHOR_SELF_LINK_REFUSED` | `:397` |
| F14 | 源须输出 `{2,4}`、目标须输入 `{1,3}` | — | `AUTHOR_EDGE_SOURCE_NOT_OUTPUT` / `AUTHOR_EDGE_TARGET_NOT_INPUT` | `:398-399` |
| F15 | 执行边端口 `fromIndex ≤ 1` 且 `toIndex == 0` | — | `AUTHOR_FLOW_PORT_UNSUPPORTED` | `:402-403` |
| F16 | 边端口须在活注册表声明 | — | `AUTHOR_EDGE_PORT_UNKNOWN:<k>:<i>` | `:422-425` |
| F17 | 数据边两端声明类型须相等（**除非任一端为泛型 type 0**） | — | `AUTHOR_EDGE_TYPE_MISMATCH:<t>:<g>!<t>:<g>` | `:432-434` |
| F18 | `build-count-gate` 的 `limit` | `[1, 1_000_000]` | `AUTHOR_COUNT_LIMIT_INVALID` | `:188-191` |
| F19 | `build-count-gate` 的 `period`（秒） | `[0.1, 3600]` | `AUTHOR_COUNT_PERIOD_INVALID` | `:192-194` |
| F20 | 节点 `definitionId` 须在活注册表**唯一**存在（kind==6、类别=图自身 kind 派生、恰好一个 model） | — | `AUTHOR_PLAN_DEFINITION_NOT_UNIQUE` / `AUTHOR_DEFINITION_IDENTITY_CONFLICT` | `:322-324` / `:741-747` |
| F21 | 定义须至少声明一个 pin（否则 connect/值写会变静默空操作） | `≥1` | `AUTHOR_DEFINITION_HAS_NO_DECLARED_PINS:<id>` | `:340` |
| F22 | `build-plan` 每节点规格须是对象且带 uint32 `definitionId` | — | `AUTHOR_PLAN_NODE_SPEC:<i>` | `:751-753` |
| F23 | `build-plan` 每条边须带 6 个 int 字段 `from,to,fromKind,fromIndex,toKind,toIndex`（**缺一即拒**） | — | `AUTHOR_PLAN_EDGE_SPEC:<key>` | `:784-785` |
| F24 | `build-plan` 边下标 ∈ `[0,节点数)` 且 `from != to` | — | `AUTHOR_PLAN_EDGE_INDEX` | `:787-788` |
| F25 | `build-plan` 每常量须带 `node∈[0,节点数)` / `portIndex`(int) / `slot`(string) / `value`(object) | — | `AUTHOR_PLAN_VALUE_NODE` / `_PORT` / `_SPEC` | `:794` / `:796` / `:798-800` |

### 1.5 **`build-plan` 与逐节点路径的三处不对称**（本轮新读出）

这三条是「同一族校验，`build-plan` 更松」的**精确负面**，值得单列（都属于 §1.4 的对照）：

1. **布局坐标界 `build-plan` 不检查。** F6 的 `abs(x),abs(y) ≤ 10000` 只在 `add-node` 分支里（`:131-133`）。`build-plan` 的 `ValidateAuthorGraph` 段（`:140-150`）**不检查 x/y**，`BuildAuthorPlan` 里 x/y 也只是 `TryGetProperty("x") → GetDouble()`、缺省 0（`:777-778`），**没有有限性/幅值检查**。⇒ 逐节点 `add-node` 有布局界，`build-plan` **没有**。
2. **边端口种类 `build-plan` 不检查范围/方向。** F12-F17 全部只作用于逐条 `connect`（`:393-434`）。`build-plan` 的 `Link` 只调原生 `LapKOOcuGY1`，失败抛 `AUTHOR_PLAN_LINK_REJECTED`（`:767-772`）——**端口合法性完全交给原生**。
3. **常量 `list` `build-plan` 写不了**（V13），而逐条 `set-value` 可以（`:1027-1031`）。

> 这不改变 128 上界（N1 与 N6 仍在），但说明**两条作者路径的校验面并不重合**——排期时不能假设「`add-node` 能过的坐标，`build-plan` 也会替你挡」。

### 1.6 操作顺序（顺序本身是约束：先空图 → 先解析 → 烧 attempt → 建 → 连 → 写）

**`AuthorGraph()` 的总分派顺序（`:211-482`）**：

1. `ValidateAuthorGraph(request)`（`:213`）——所有 F1–F25 的信封/形状校验。
2. 资源查找 `matches`（`:220-221`）。
3. `create`（`:222-233`）——名字唯一 + `author-create` attempt 闸。
4. 图身份匹配（`:234-235`，`AUTHOR_GRAPH_IDENTITY_MISMATCH`）。
5. 取节点表 `nodes`（`:236`）；图 kind 类别核对（`:240-244`）。
6. **只读早退**：`inspect`/`lookup`（`:259`）、`export`（`:260`）。
7. 绑定图禁改闸（`:262-263`，`AUTHOR_BOUND_GRAPH_EDIT_REFUSED`）。
8. **批量建图早退**：`build-print`（`:264`）、`build-plan`（`:268`）、`build-count-gate`（`:272`）。
9. `countGateReady` 计算（`:276-278`）→ **N6 全图闸**（`:287`）→ 可放置闸（`:288-290`）→ print-ready（`:291-296`）。
10. `bind`（`:298-319`）→ `add-node`（`:320-346`）→ `pin-slots`/`set-value`（`:347-392`）→ `connect`/`disconnect`（`:393-454`）→ `set-print`/`set-condition`（`:455-480`）。

**`BuildAuthorPlan()` 的内部顺序（`:733-820`）**——这是「128 计划」的落点：

1. **空图检查**（`:735`，`AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH`）。
2. **重放闸读**（`:737`，`Spent("author-plan", graphId)`）。
3. **先把所有 `definitionId` 在活注册表里解析完**（`:748-755`，`Resolve()` `:741-747`）——**在任何原生变更之前**，任一解析不出则**整张图失败**，不写半张。
4. **烧 attempt**（`:756`，`Spend("author-plan")`，注释「before the first native mutation; a partial failure never replays」）。
5. **加节点**（`:774-781`）——逐节点「计数恰好 +1 且读回定义 id 一致」，否则 `AUTHOR_PLAN_NODE_READBACK_FAILED`。
6. **连线**（`:782-791`）。
7. **写常量**（`:792-818`）。
8. **标记 ready**（`:819`，`Spend("author-plan-ready")`）。

> 顺序 `nodes → edges → values` 的理由（`:729-732` 明写）：泛型数据引脚（type 0）由原生编辑器从**被连的兄弟节点**物化；往**尚未物化的泛型引脚**写值，正是要拒的「加得进去配不出效果」。顺序反了会把这类写成假成功。

---

## 2. 派发成本 → 每派发实用最大 op 数（算术）

### 2.1 两个输入数（分层标注）

| 数 | 值 | 出处 | 层次 |
|---|---|---|---|
| scope 租约 | **300 s（5 min）** | `BridgeServer.cs:37` `Lease = TimeSpan.FromMinutes(5)`；`CLAUDE.md` §三 | 源码 |
| pin 集规模 | **2082 个文件** | `elevated-runner.ps1:590-620`（`Get-DispatchPinFiles`）；`PROGRESS.md:249`「pins **2082**」 | 源码 + 真机 |
| 每派发 pin 哈希 | **≈16 s** | `CLAUDE.md` §三；`PROGRESS.md:199` | 文档口径 |
| 每派发 pin 哈希（实测更贵） | **≈50 s** | `PROGRESS.md:620`、`:679` | **真机** |
| 每派发总成本（实测） | **≈63 s**（≈50 s 哈希 + ≈10 s 图） | `PROGRESS.md:679` | **真机** |
| 单次派发回执窗 | **45 s** | `graph-transport.ps1:21-25` `Get-GraphResponseWindowMs`=45000 | 源码 |
| 请求行上限（客户端） | **16000 B** | `graph-transport.ps1:51` | 源码 |
| 请求行上限（服务端） | **16384 B** | `BridgeServer.cs:34` / `:205-207` | 源码 |

**pin 哈希是「每次派发固定付费、与图大小无关」**：`Get-DispatchPinFiles`（`elevated-runner.ps1:590` 起）枚举的是**固定集合**——6 个固定脚本 + 20 个 game-executor 脚本 + 全部 native `*.cpp/*.h` + 7 个 profile json + 整个 Python 运行时 `DLLs/`、`Lib/`（递归，`:602-617`）+ 重开验收 pin。新图**不改变这个集合**。⇒ 一次派发把整张图建完，只付一次哈希。

### 2.2 逐节点路径：**每次派发 = 1 个 op**

逐节点路径下，一个派发只能加 **1** 个节点（或连 **1** 条边、写 **1** 个常量）。所以：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


交叉验证（`PROGRESS.md:199`）：**43 条指令 ≈ 43×16 = 688 s ≈ 11.5 min > 5 min 租约**——逐节点路径**必然超租约**。这就是 `build-plan` 诞生的理由。

### 2.3 批处理路径：**每次派发 = 整张图（N 个 op）**

`build-plan` 把整张图并成 **1 个派发** ⇒ 16 s 的哈希只付一次 ⇒ 「每派发图规模」**不再由租约决定**，而由**三条更硬的、互相取小的墙**决定：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**N_字节 的算术**（用真机 demo 计划标定，`.runtime/scratch/MW_API_FARM_DEMO-plan.json` = 15 节点/17 边/13 常量，紧凑后 **2507 B**；均值复用于 `BUILD-PLAN-LIMITS.md` §2.3）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**N_回执窗 的算术**（线性外推，**非实测**）：真机数据点「≈15 节点的原生建图 ≈ 10 s」（`PROGRESS.md:679` 把 63 s 拆成 ~50 s 哈希 + ~10 s 图）。据此 `floor(45000 / (10000/15)) ≈ floor(45 / 0.667) ≈ 67 个节点` 触顶 45 s 墙。

**取小结论**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


> **两条必须一起说**：①上面的每常量字节数用于 **int/短字符串**；**一条 `string` 常量最大 1024 字符（V6/V10）≈1 KB**，几条就把预算吃到见底 ⇒ 含长文本的图，节点数**大幅低于 97**。②请求行是**整条 JSON 的压缩单行**（`ConvertTo-Json -Compress -Depth 12`，`graph-transport.ps1:50`），**没有分块续传**——一份计划就是一发不可拆的行。

### 2.4 吞吐对比


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**有效成本降低约 60–90 倍**，且整张图**原子**（要么全成、要么整图失败不写半张，§1.6 步 3-4）。

---

## 3. 第二次 `build-plan` 能不能扩同一张图？——**不能**

被**两道独立、互相冗余的闸**拒绝：

| 闸 | 语义 | file:line | 换租约/换修订后是否仍拒？ |
|---|---|---|---|
| **G-a 空图要求** | `build-plan` 只在**空图**上跑；第一次计划建完后图非空 | 校验 `:144`；实现 `:735`（`AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH`） | **是**——「图里有节点」这件事活在**编辑器内存模型**里，与适配器实例/租约无关，重注入后照样拒 |
| **G-b attempt 已烧** | `Spent("author-plan", graphId)` 命中即拒；attempt 在**首次原生变更前**烧 | 读 `:737`；烧 `:756`（`AUTHOR_PLAN_ALREADY_ATTEMPTED`） | **看租约**——marker 活在适配器实例里（见下） |

### 3.1 marker 的作用域（为什么 G-b 会随租约消失）

- `spent` 是 `EditorAdapter` 的**实例字段** `readonly HashSet<string> spent`（`EditorAdapter.cs:30-32`；`Spent`/`Spend` 见 `:31-32`）。
- 适配器随 `BridgeServer` 一起构造，`Entry.cs:208` `server=new BridgeServer(settings,facts,pipe,settingsDirectory!)`——**每次建立 scope 连接就 new 一个新 `BridgeServer`**（连带新的 `EditorAdapter`、空的 `spent`）。
- `BridgeServer.Lease = 5 min`（`BridgeServer.cs:37`），租约到期后 scope 关闭、可重新 `load` 拿新租约（`PROGRESS.md:1268` 亲证「同一 R233 在租约过期后再注入就成功」）。

⇒ **G-b 的寿命 = 一个租约**：新租约 + 新修订后 `author-plan` marker 是空的 ⇒ G-b **放行**。
但 **G-a 仍然拒绝**（图非空）——**两道闸叠加，结论是「扩不了」。**

### 3.2 换别的动作能突破 128 吗？——不能

把三条上限摆在一起：

- `build-plan` 单次计划 ≤ **128**（`:148`）；
- `add-node` 要求的 `expectedNodeCount` ≤ **127**（`:130`）——声明的**当前**计数最多 127，加一个才到 128；
- 全图闸 `nodes.Count > 128` 即拒（`:287`，`add-node` 走这条）。

⇒ **任何作者动作路径的可达上界都是 128。** 想从 128 加到 129：得先声明 `expectedNodeCount=128`，而 `:130` 在 **127** 就把它拒了；即便绕过，`:287` 也会在加之前看到 128……**两条路都堵死。**

### 3.3 判定：**不能**（附证据强度）

- **G-a 是源码级硬结论**（`:144` / `:735` 逐行读）：空图要求与租约无关。
- **G-b 随租约重置**（`EditorAdapter.cs:30-32` + `Entry.cs:208` + `BridgeServer.cs:37`）。
- **本轮未真机复现「第二次被拒」**（任务 HARD RULES 禁发报文）。但「不能」**不依赖真机**——只要 G-a 成立（图非空），第二次 `build-plan` 在任何租约下都被拒。⇒ **判定「不能」**，唯一的不确定是**别的扩图原语是否存在**（见 §5 边界）。

---

## 4. 今天能表达多大的游戏（平话）

- **一次 `build-plan` 派发能装下**：
  - **纯节点/事件图（少常量）**：可逼近 **128 节点**（≈4.2 KB，宽裕）。
  - **每节点带边带常量的稠密图**：现实上界 ≈ **60–97 节点**（字节墙 ≈97；45 s 回执窗外推 ≈67 先触顶；含长字符串常量时更低）。
- **一次派发的图能在一次租约内完成建 → 独立读回 → 导出 → 绑定**（真机已走通 15 节点的完整闭环，`PROGRESS.md:164-199`）。
- **要 >128 的图，当前没有任何作者原语**（§3.2）。这不是「没挖到」，是**三条上限在同一处汇合**的负结论。
- **列表常量不在 `build-plan` 里**（V13）。含列表的图要么拆成 `build-plan` + 后续逐条 `set-value`（**多付派发**，每派发又吃一次 16 s），要么改用写入量小的形状。

**一句话**：**今天可表达的游戏 = 「一张 ≤128 节点、派发前离线排好、一次 `build-plan` 建成」的节点图玩法**；比这更大或需要多次追加的图，**没有路**（在现有作者面内）。

---

## 5. 局限与不吹（本轮搜过什么 / 没搜什么）

- **检索范围（本次 checkout 实读）**：`AuthoringGraph.cs`（全文 1041 行）、`EditorAdapter.cs`（`:30-32` spent 定义）、`BridgeServer.cs`（`:34/:37/:205-207`）、`Entry.cs`（`:195-217`）、`elevated-runner.ps1`（`:588-647` pin 文件集）、`graph-transport.ps1`（`:21-73`）、`author.py`（`:513-628`）、`gameplan/plan.py`（`:46` `NODE_LIMIT=128`、`:167-180` validate）、`PROGRESS.md`（`:164-199`、`:249`、`:620`、`:679`、`:1268`）。**未读任何 DLL 字节，未跑构建，未连桥，未发报文，未触碰游戏/编辑器。**
- **字节预算算术（§2.3 N_字节）是外推**：以真机 demo 计划（15/17/13，2507 B 紧凑）的**均值**线性外推到上界。真实之字形布局、坐标位数、常量分布都会让它漂移 ⇒ **±10% 量级，非精确阈值**。
- **45 s 回执窗外推（§2.3 N_回执窗）是外推**：以「15 节点≈10 s 图工作」为基准，**没有实测 60+ 节点的建图耗时**。
- **N6 全图闸（`:287`）与 `:130` 的 127 是源码级结论**；`build-plan` 走 `:268-271` 早退、`add-node` 走 `:287` 的路径分叉也是逐行读出。
- **未搜的边界**：①**已编译 DLL**（`bin/Release/.../*.dll`）与 `.runtime/` 下反编译副本——若某处 DLL 里另有读取 `author-plan-ready` 的代码，§3 的「marker 只此一处」式结论不覆盖（但 §3 的「不能」**不依赖**这一点，它靠 G-a）。②**本文件之外是否有别的扩图原语**（例如某个 native op 直接追加节点）——**本次检索范围未覆盖**，按 `CLAUDE.md` §一.2 纪律，只能写「本次检索范围内未找到」，不能写「不存在」。
- **本文件只新增自己**；不改 `STRUCTURE.md`、不改 `PROGRESS*.md`、不改任何源码（遵从「只拥有任务点名的文件」）。
