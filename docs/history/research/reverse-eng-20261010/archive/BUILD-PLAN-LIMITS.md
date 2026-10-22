> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #8 挖 — build-plan 的硬边界：节点 / 边 / 常量各能到多少

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**。
本文件只读三处：①`tools/editor-bridge/Adapter/AuthoringGraph.cs`（`build-plan` 的 C# 实现，逐行）；
②`tools/authoring/author.py`、`tools/authoring/graph-transport.ps1`、`tools/gameplan/plan.py`（调用侧的本地闸与传输闸）；
③`tools/editor-bridge/ManagedBridge/BridgeServer.cs`、`EditorAdapter.cs`、`elevated-runner.ps1`（租约、pin 哈希的来源）。
外加仓内记录 `PROGRESS.md` / `PROGRESS-LITE.md` / `CLAUDE.md`。

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 本文件的限制**全部从源码读出（静态）**；凡真机数字都注明出处行号。
> **"搜不到"≠"不存在"**：本轮检索范围写明在第 5 节。**行号＝本次 checkout 实测**。

---

## 0. 一句话结论

- **`build-plan` 自己强制三条硬限制**：①图必须为空（`AuthoringGraph.cs:735` / `:144`）；
  ②`plan.nodes` **非空且 ≤ 128**（`:148`）；③同一张图**只允许一次** `build-plan`（`:737`，attempt 在
  第一次原生变更前就被烧掉 `:756`）。**边与常量的条数没有独立上限**——它们的上限来自**请求行字节数**。
- **真正的"每派发能装多大图"不是 128，是 16000 字节的请求行。** 传输层客户端把整条请求压成**一行**
  （`graph-transport.ps1:50` `ConvertTo-Json -Compress` + `:59` `WriteLine`），并在 **>:16000 字节**时
  本地抛 `REQUEST_TOO_LARGE`（`:53`）；服务端在 16 KiB（`BridgeServer.cs:34` `MaxLineBytes=16*1024`）截断。
  一个"每个节点都带一条边和一个常量"的稠密图，**约 97 个节点就到 16000 字节**（算法见 §2.3），
  **先于 128 撞墙**。
- **128 是真上限，不是"每次调用的上限"。** 第二次 `build-plan` 被**两道独立的闸**拒绝（§3）：
  ①图已非空 ⇒ `AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH`；②attempt 已烧 ⇒ `AUTHOR_PLAN_ALREADY_ATTEMPTED`。
  想用别的动作把图撑过 128 也不行：`add-node` 的 `expectedNodeCount` 上限是 **127**（`:130`），
  全图闸在 **>128** 时拒（`:287`）⇒ **可达的最大图就是 128 个节点**。
- **那两条原生约束（5 分钟租约 + 每次派发 ~16 s pin 哈希）不缩小"单次 build-plan 的图"，反而正是它存在的理由**：
  逐节点路径下 **5 分钟只能放 ≈18 个派发（实测约 4 个）**，批处理把 16 s 只付一次，
  于是"每派发图规模"改由 **128 节点上限**与 **16000 字节行**共同决定（§2）。

---

## 1. `build-plan` 强制执行的每一条硬限制（file:line）

### 1.1 限制清单

| # | 限制 | 值 | 抛出的具名码 | file:line |
|---|---|---|---|---|
| L1 | 图必须是**空图** | `expectedNodeCount==0` | `AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH` | 校验 `AuthoringGraph.cs:144`；实现 `:735` |
| L2 | `plan` 必须是对象、`plan.nodes` 必须是非空数组 | `nodes` 长度 ∈ [1,128] | `AUTHOR_REQUIRED_OBJECT:plan` / `AUTHOR_PLAN_NODES` | `:145-146` / `:147-149` |
| L3 | **节点数 ≤ 128**（含 128；129 拒） | 128 | `AUTHOR_PLAN_NODES` | `:148` |
| L4 | 同一张图**只允许一次** `build-plan` | attempt 集合 | `AUTHOR_PLAN_ALREADY_ATTEMPTED` | 读 `:737`；烧 `:756`（在任何原生变更**之前**） |
| L5 | **全图节点 >128 拒**（非 build-plan 的其他动作走这条） | 128 | `AUTHOR_GRAPH_NODE_LIMIT_EXCEEDED` | `:287` |
| L6 | `add-node` 声明的 `expectedNodeCount` ≤ **127** | 127 | `AUTHOR_REQUIRED_UINT` | `:130` |
| L7 | `bind` 声明的 `expectedNodeCount` ≤ **128** 且 `entityId != 0` | 128 | `AUTHOR_REQUIRED_UINT` / `AUTHOR_EMPTY_BIND` | `:135` |
| L8 | 每个节点的 `definitionId` 必须在**活注册表**里**唯一**存在（kind==6、类别=`{10001,20000,22000,0}`、恰好一个 model） | — | `AUTHOR_PLAN_DEFINITION_NOT_UNIQUE:<id>` | `Resolve()` `:741-747` |
| L9 | 每个节点规格必须是对象且带 `definitionId`(uint32) | — | `AUTHOR_PLAN_NODE_SPEC:<i>` | `:751-753` |
| L10 | 每条边必须带 `from,to,fromKind,fromIndex,toKind,toIndex`（六字段全是 int，**任一缺失即拒**） | — | `AUTHOR_PLAN_EDGE_SPEC:<key>` | `:784-785` |
| L11 | 边的 `from/to` 必须是 `[0,节点数)` 且 `from != to` | — | `AUTHOR_PLAN_EDGE_INDEX` | `:787-788` |
| L12 | 每个常量必须带 `node`(∈[0,节点数)) / `portIndex`(int) / `slot`(string) / `value`(object) | — | `AUTHOR_PLAN_VALUE_NODE` / `AUTHOR_PLAN_VALUE_PORT` / `AUTHOR_PLAN_VALUE_SPEC` | `:794` / `:796` / `:798-800` |
| L13 | 常量走 string 支时，文本 ≤ **1024** 字符 | 1024 | `AUTHOR_PLAN_VALUE_TEXT_TOO_LONG` | `:812` |
| L14 | 非 string 常量走 `AuthorWriteScalar`：slot∈{int,enum,bool,float,string(auto 只映射 2/6)}，写后**强制读回比对** | — | `AUTHOR_VALUE_*`（见 §1.3） | `:901-971` |
| L15 | `build-plan` 的 `value` **不支持 list**（无 list 分支 ⇒ 落到 `default` 抛） | — | `AUTHOR_VALUE_SLOT_UNSUPPORTED` | `:969-970`；list 只在 set-value 路径 `:1027-1031` |
| L16 | 请求行（**整条 JSON**，含信封）UTF-8 ≤ **16000** 字节（客户端本地闸） | 16000 B | `REQUEST_TOO_LARGE` | `graph-transport.ps1:53` |
| L17 | 请求行服务端上限 **16 KiB = 16384 B**（超即 `line_too_long` 并断开） | 16384 B | `line_too_long` | `BridgeServer.cs:34` / `:205-207` |
| L18 | 单次派发**等回执**最多 **45 s**（超时后若已 send ⇒ `outcomeUncertain:true`） | 45000 ms | `RESPONSE_TIMEOUT` | `graph-transport.ps1:24-25` / `:65-67` |
| L19 | 动作白名单：`build-plan` 只收 `{id,op,nonce,action,name,graphId,expectedNodeCount,plan}`；多一个字段或重复即拒 | — | `AUTHOR_UNKNOWN_OR_DUPLICATE_FIELD` | `:103` / `:110-113` |
| L20 | 图名 `MW_API_[A-Za-z0-9_]{1,48}`；节点坐标绝对值 `abs(x),abs(y) ≤ 10000` | 见左 | `AUTHOR_NAME_INVALID` / `AUTHOR_LAYOUT_INVALID` | 名字 `:114`；坐标 `:131-133` |

**三条要单独说的：**

- **L3 与 L5/L6 一致，不矛盾。** `build-plan` 在 `:268-271` 就 `return`（早退），**走不到** `:287` 的全图闸，
  所以它用自己那条"≤128"（`:148`）。而 `add-node` 走得到 `:287`，且它声明的 `expectedNodeCount` 被卡在 127
  （`:130`）⇒ **加完最多 128**。两条路在同一个 128 汇合。
- **L4 的"烧号"发生在第一次原生变更之前**（`:756` 注释明写 "before the first native mutation; a partial failure
  never replays"）。所以**一次中途失败的 `build-plan` 在同一租约内不能重试**——这是设计，不是缺陷。
- **L15 是一条本轮新看出的能力缺口**：`AuthorListLimit = 64`（`:44`）与 `AuthorWriteList`（`:1004`）
  **只服务于 `set-value` 路径**（`AuthorWritePinValue` `:1027-1031`）。`build-plan` 的常量循环只调用
  `AuthorWriteScalar`（`:815`），而它**没有 list 分支**。⇒ **`build-plan` 写不了列表常量**；
  要写列表，只能对**已经建好的**节点单独发一条 `set-value`（又一个派发，吃一次 `~16 s`）。

### 1.2 操作顺序（`BuildAuthorPlan` `:733-820`）

1. **空图检查**——`:735`（图里已有任何节点即拒）。
2. **重放闸**——`:737` `Spent("author-plan", graphId)`。
3. **先把所有节点定义在活注册表里解析完**（`:748-755`，`Resolve()` `:741-747`），**在任何原生变更之前**
   ——任何一个定义解析不出，**整张图失败**，不写半张。
4. **烧 attempt**——`:756`。
5. **加节点**（`:774-781`）——逐节点 `Add`（`:757-766`），每个都要求"计数恰好 +1 且读回定义 id 一致"，
   否则 `AUTHOR_PLAN_NODE_READBACK_FAILED`。
6. **连线**（`:782-791`）。
7. **写常量**（`:792-818`）。
8. **标记 ready**——`:819` `Spend("author-plan-ready", graphId)`。

**为什么是 `nodes → edges → values`**（`:729-732` 明写）：泛型数据引脚（type 0）由原生编辑器从**被连的兄弟节点**
物化出来，往一个**尚未物化的泛型引脚**写常量正是要拒的"加得进去配不出效果"的情形。顺序反了就会把这类
写变成假成功。

### 1.3 `build-plan` 常量走到的 setter/读回对（`:901-971`）

| slot | 写 | 读回 | 支持 | 码 |
|---|---|---|---|---|
| `int` | `c84KKE8ihrN` | `ilqKKrw7dhN` | ✔ | `:907-918` |
| `enum` | `X8oKKHB87Ue` | `cPOKKedklwd` | ✔ | `:919-930` |
| `bool` | `CHHKK434xan` | `RJCKKnWqvLO` | ✔ | `:931-942` |
| `float` | `SH7KKvk8cxe` | `ngMKKCVBuMA` | ✔（按 float32 位精确比对 `:953`） | `:943-956` |
| `string` | `MfLKK0bLIju` | **只写不读回**（读回符号不在绑定档） | ✔ | `:804-813` |
| `list` | — | — | **✘ 拒** | `:969-970` |

> **`string` 是唯一没有读回校验的一支**（`PROGRESS.md:167` 记的就是这条：读回符号 `ur7KK2NiYZ4` 不在绑定档里，
> `build-plan` 里字符串改走 `set-print` 同款的**只写不读回**）。其余四支都**写后立刻读回、不等即拒**。

### 1.4 边/常量**没有**独立计数上限——这一点要说清

- 边循环（`:782-791`）只做**逐条**的字段/下标检查（L10/L11），**不数条数**。
- 常量循环（`:792-818`）只做**逐条**的字段/下标检查（L12/L13/L14），**不数条数**。
- ⇒ "边能到多少 / 常量能到多少"的答案**不在 C# 里**，而在 **L16/L17 的请求行字节上限**里（§2.3）。

---

## 2. 由"5 分钟租约 + 每次派发 ~16 s pin 哈希"推出的**每派发实用最大图规模**

### 2.1 两个输入数（分层标注）

| 数 | 值 | 出处 | 层次 |
|---|---|---|---|
| scope 租约 | **300 s（5 min）** | `BridgeServer.cs:37` `Lease = TimeSpan.FromMinutes(5)`；`CLAUDE.md` §三 | 源码 |
| 每次派发 **pin 哈希** ≈ **16 s** | 16 s | `CLAUDE.md` §三；`PROGRESS.md:147`（"每条 graph 派发都要重算 2082 个 pin 的哈希（≈16 秒）"） | 文档/真机 |
| （实测更贵）pin 哈希 ≈ **50 s**，整次请求 ≈ **63 s** | 50 s / 63 s | `PROGRESS.md:620`、`:627` | **真机** |
| 被哈希的 pin 文件集规模 | **2082** | `elevated-runner.ps1:574-617`（`Get-DispatchPinFiles` / `New-DispatchPins`）；`RECOVERY-RUNBOOK.md:119` | 源码+离线实测 |

**pin 哈希是"每次派发固定付费、与图大小无关"的成本**——它哈希的是一份**固定的 2082 文件集**
（`elevated-runner.ps1:574` 起的 `Get-DispatchPinFiles`：六个固定脚本 + 20 个 game-executor 脚本 + 全部 native
`*.cpp/*.h` + 7 个 profile json + 整个 Python 运行时 `DLLs/`+`Lib/` 递归）。这在算术里是关键。

### 2.2 一次租约能放几次派发


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**逐节点路径下**，一个派发只能加 1 个节点（或连 1 条边、写 1 个常量）⇒
**一个租约最多 ≈18 个操作（理论）/ ≈4 个操作（实测）**，还要扣掉 `create`/`lookup`/`export`/`bind`。
这正是 `build-plan` 诞生的理由（`CLAUDE.md` §三；`PROGRESS.md:147`：43 条指令 ≈ 11.5 分钟 > 5 分钟租约）。

### 2.3 批处理把它压成"1 次派发"后的**每派发**上限

`build-plan` 把整张图并成 **1 个派发** ⇒ **16 s 的 pin 哈希只付一次** ⇒
"每派发图规模"**不再由租约决定**，而由**两条更硬的墙**决定：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**请求行预算算术**（用真机 demo 计划标定，`.runtime/scratch/MW_API_FARM_DEMO-plan.json` =
15 节点 / 17 边 / 13 常量；紧凑序列化后 **2507 字节**）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**⇒ 结论（算术，不是猜）**：一个节点都带一条边和一个整数常量的**稠密** `build-plan`，
**约 97 个节点就撞 16000 字节行上限**，**早于** 128 个节点的适配器上限。
反过来，**纯节点、无连线**的图能装满 128 个（≈4.2 KB）。

> **两个必须一起说的边界**：①上面的每常量字节数用的是 **int / 短字符串**；**一条 `string` 常量最大 1024 字符
> （L13）≈ 1 KB**，几条就能把预算吃到见底 ⇒ 含长文本的图，节点数还要**大幅低于 97**。
> ②128 是**整条 JSON 的一行**，`ConvertTo-Json -Depth 12`（`graph-transport.ps1:50`）——**没有分块续传**，
> 一份计划就是一发不可拆的行。

### 2.4 单个派发还有一个 45 s 的墙钟窗（L18）

`graph-transport.ps1:24-25` 的 `Get-GraphResponseWindowMs` 对**所有 graph op 一律返回 45000 ms**。
一次 `build-plan` 的原生图工作若超过 45 s，客户端抛 `RESPONSE_TIMEOUT`；若请求已 send，
`outcomeUncertain:true`（`:73`）——**"超时≠没生效"**。

真机数据点：15 节点的 demo 与 13 节点的 farm 图都在**一个租约内四步全过**（`PROGRESS.md:112-130`），
说明 ~15 节点的原生建图 ≈ 10 s 量级（`PROGRESS.md:627` 把 63 s 拆成"~50 s 哈希 + ~10 s 图"）。
**据此线性外推** 45 s（≈4.5 倍"15 节点的图工作"）大约是 **60–70 个节点**时触顶——
但这是**外推，不是实测**，且与 §2.3 的 ≈97 可能同时或更早生效。**两条都要当成"未知里更保守的那条"来排期。**

---

## 3. 128 是不是真天花板？第二次 `build-plan` 能不能扩同一张图？

**答：不能扩。同一张图上的第二次 `build-plan` 被拒，而且是两道独立、互相冗余的闸。**

### 3.1 两道闸

| 闸 | 语义 | file:line | 跨租约是否仍拒？ |
|---|---|---|---|
| **G-a 空图要求** | `build-plan` 只在**空图**上跑；第一次计划建完后图非空 | 校验 `:144`；实现 `:735` | **是**——图里有节点这件事与内存状态无关，重注入后照样拒 |
| **G-b attempt 已烧** | `Spent("author-plan", graphId)` 命中即 `AUTHOR_PLAN_ALREADY_ATTEMPTED`；attempt 在**首次原生变更前**烧（`:756`） | 读 `:737`；烧 `:756` | **看租约**——marker 活在适配器实例里（见下），**同租约必拒** |

**marker 的作用域**：`spent` 是 `EditorAdapter` 的**实例字段** `HashSet<string>`（`EditorAdapter.cs:30-32`），
而适配器随 `BridgeServer` 一起 `new()`（`BridgeServer.cs:59`），`BridgeServer` 又**每个 lease 新建一个**
（`Entry.cs:208`：`server=new BridgeServer(...)`）。⇒ **`author-plan` marker 的寿命 = 一个租约**。
所以重注入拿一个新租约后 **G-b 会放行**，但 **G-a 仍然拒绝**（图非空）——**两道闸叠加，结论是"扩不了"**。

### 3.2 换别的动作能突破 128 吗？

不能。把三个上限摆在一起：

- `build-plan` 单次计划 ≤ **128**（`:148`）；
- `add-node` 要求的 `expectedNodeCount` ≤ **127**（`:130`）——声明的**当前**计数最多 127，加一个变 128；
- 全图闸 `nodes.Count > 128` 即拒（`:287`，`add-node` 走这条）。

⇒ **任何作者动作路径的可达上界都是 128。** 想从 128 加到 129，你得先声明 `expectedNodeCount=128`，
而 L6 在 **127** 就把它拒了；即便绕过，`:287` 也会在加之前看到 `128`……**两条路都堵死**。
**128 是适配器作者面的真天花板，不是"每次调用的容量"。**

### 3.3 `countGateReady` 豁免**不**惠及 `build-plan`

`:276-278` 有一条豁免：当 `Spent("author-count-ready", graphId)` 且节点定义多重集恰好等于那 13 个
`{1,1,2,2,2,14,14,71,73,79,82,83,230}` 时，**跳过** `:287` 的 >128 闸与 `:288` 的可放置闸。
它只认 **`author-count-ready`**，而这枚 marker **只由 `BuildAuthorCountGate` 烧**（`:718`）。
`build-plan` 烧的是**另一个** marker `author-plan-ready`（`:819`）。

**`author-plan-ready` 是只写不读**：在本次检索范围内（`tools/` 下全部 `.cs/.py/.ps1`，排除已编译 DLL 与 `.runtime`），
grep `author-plan-ready` 的命中**只有 `AuthoringGraph.cs:819` 一处**（即 `Spend` 调用本身，**没有任何 `Spent` 读它**）。
⇒ **`build-plan` 的图得不到任何豁免**；不过它的规模本来就被 L3 卡在 128，也无所谓。

---

## 4. 面向下一轮的实用结论

1. **排期按"128 节点上限"与"16000 字节行"取小者**：
   - **纯事件/顺序图（少常量）**：可逼近 **128 节点**（≈4.2 KB，宽裕）。
   - **每节点带边带常量的稠密图**：现实上界 ≈ **97 节点**（且含长字符串常量时更低）。
2. **一次 `build-plan` = 一次 attempt，烧了不补**（同租约内失败不可重试 ⇒ 要么成功、要么新租约，
   而新租约又因空图闸无法在同一张图上重来）。⇒ **发之前务必让 `plan.validate()`
   （`tools/gameplan/plan.py:167`，含 `NODE_LIMIT=128` 闸 `:178`）与本地字节预算都在离线跑绿。**
3. **列表常量不在 `build-plan` 里**（L15）。含列表的图要么拆成 `build-plan` + 后续逐条 `set-value`（多付派发），
   要么改用写入量小的形状。
4. **想要 >128 的图，当前没有任何作者原语**（§3.2）。这不是"没挖到"，是**三条上限在同一处汇合**的负结论。

---

## 5. 局限与不吹（本轮搜过什么 / 没搜什么）

- **检索范围**：`tools/editor-bridge/Adapter/AuthoringGraph.cs`（全文）、`EditorAdapter.cs`（Spent/Spend 定义）、
  `ManagedBridge/BridgeServer.cs`（帧/租约/op 路由）、`elevated-runner.ps1`（pin 文件集与哈希）、
  `tools/authoring/author.py`、`tools/authoring/graph-transport.ps1`、`tools/gameplan/plan.py`、
  `PROGRESS.md`、`PROGRESS-LITE.md`、`CLAUDE.md`。**未读任何 DLL 字节，未跑构建，未连桥，未发报文。**
- **`author-plan-ready` 只写不读**是**检索范围内**的结论（`tools/` 全部 `.cs/.py/.ps1`）；检索**不含**
  已编译 DLL（`bin/Release/.../*.dll`）与 `.runtime/` 下的反编译副本——若某处 DLL 里另有读取，本结论不覆盖。
- **字节预算算术（§2.3）是外推**：以真机 demo 计划（15/17/13，2507 B 紧凑）的**均值**线性外推到 128 节点。
  真实之字形布局、坐标位数、常量分布都会让它漂移 ⇒ **±10% 量级，非精确阈值**。
- **45 s 墙钟推算（§2.4）是外推**：以"15 节点≈10 s 图工作"为基准线性外推，**没有实测 60+ 节点的建图耗时**。
- **"第二次 build-plan 被拒"是源码级结论**（两道闸逐行读）；**本轮的 demo 只用过一次 `build-plan`**
  （`PROGRESS.md:112-130`），**没有真机复现过"第二次被拒"**——要坐实需一次真机动作，**本轮不做**（HARD RULES）。
- **本文件只新增自己**；不改 `STRUCTURE.md`、不改 `PROGRESS*.md`、不改任何源码（遵从"只拥有任务点名的文件"）。
