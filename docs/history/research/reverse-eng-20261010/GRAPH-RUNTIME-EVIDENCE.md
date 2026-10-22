> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #7 挖 — 什么证据才能证明「一条图的**边**在运行时被接受」

> 建立日期：2026-10-10。位置：`docs/research/reverse-eng-20261010/GRAPH-RUNTIME-EVIDENCE.md`。
> 任务：#7 —— 全工程所有图的断言都停在「节点在模型里存在」。**边是建出来的，但从未被证明被接受**，且什么都没跑过。本文要
> (1) 按强度列出本工程可得的六类证据；(2) 逐类说清**对「边」**能证什么 / 不能证什么，并指出**是哪份文件产出的**；
> (3) 把姊妹图日志任务的裁决折进排名；(4) 给出**单一下一步**与它产出的确切 artefact。

**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档、未注入、未编译、未读任何图片**（遵守本轮 HARD RULES 与记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only`）。
> 证据来源三处：① 仓内桥 C# 源码（`tools/editor-bridge/`）② `.runtime/` 下的**真实回执原件**与反编译语料（用 Bash `grep`/`sed`/`find`，**Grep 工具会静默跳过 `.runtime/`**，见 `CLAUDE.md` §一.2）③ 姊妹文件（`GRAPH-RUNTIME-VERIFY-MINE.md` #3、`GRAPH-LOG-SHAPE.md` #4、`GRAPH-LOG-NEXT-STEP.md` #5、`GIA-EXPORT-MINE.md` #9、`REOPEN-VERIFICATION-MINE.md` #10）。
> **本文件只新增自身**，不改其它任何文件、不改任何代码。
> 按 `CLAUDE.md` §一.3、§五：`文档写了什么` / `工具能做什么` / `真机验证过什么` 三层分开标。凡「=0」均写明检索范围；凡语义未证均写「未证」。

---

## 0. 一句话结论

- **「边被接受」这句话是四件不同的事**，混在一起谈就会把「编辑器的接受」错当成「游戏运行时的接受」：
  **E1 边在编辑器模型里存在** / **E2 边被序列化到磁盘** / **E3 边被游戏加载器重建进运行时模型** / **E4 边被执行流真正遍历过**。
  **四层各有各的证据，强度递增；本工程今天只把 E1 握稳，E2 有现成解码器却没人对 demo 图跑过，E3 被关卡常量闸门卡死，E4 只有一条弱通道。**
- **对任务前提的一处精修（不是更正）**：任务说「边从未被证明被接受」。更精确的现状是——
  **边在编辑器模型里是能被读回来的**，且**真机已经读回来过**：不是靠 `graph inspect`（它**只返回节点、一条边都不返**，`AuthoringGraph.cs:253-257`），而是靠**另一个已装好的 op** `inspect-reopen-content`（`ReopenContentEvidence.cs:183-188`）。
  真机原件 `.runtime/editor-bridge/runs/1a89dbae-…/inspect-reopen-content-response.json` 里 `content.linkCount=40`、`graphs[2]=MW_MVP_Course_20260922`（29 节点 / **38 条边**），每条边带 `from/to = {nodeId, kind, index}`。**⇒ E1 对「边」成立，且是既成事实，不是待办。**
- **通向「运行时接受」的路只有两条**：
  **(d) reopen**（唯一能把产品送回**游戏自己的加载器**回放的通道；它会**逐条比对三方的边集**，`native_reopen_acceptance.py:216-229,428-429`）—— 但目前**被常量关卡 id 钉死、且验收器测试已红**（#10）；
  **(e) 图日志**（唯一能观测「跑没跑」的通道）—— 但它**只能证节点、证不了边**（记录里没有边的身份，#4 §2），而且**要把通道打通还得先改一处读者**（#5 §4）。
- **单一下一步（本文件正面交付，§4）**：**别再猜——把磁盘上的 `.gil` 的边解出来**。仓内**已有** `.gil` 节点图解码器（`tools/editor-bridge/audit-native-enums.py:74` `load_graphs`，它读 `pb.NodeGraph` 的 `pins.connections`），但**从没有人把它指向 demo 图**，也没有人拿它与 `.runtime/scratch/MW_API_FARM_DEMO-plan.json` 的 17 条边对过。
  这一步**零接触、零风险**（不连桥、不开游戏、不写档），一次运行就能把「`field 10` 有 5789 B 字节」升级成「**这 17 条边以正确的 from/to/方向写在盘上**」——或者把它证否。
  产物：`.runtime/scratch/MW_API_FARM_DEMO-edges-on-disk.json`。

---

## 1. 先把「边被接受」拆成四层（否则排名无坐标）

任务问的是「边在**运行时**被接受」。但本工程把「接受」这个词用在四个不同的主体身上，强度完全不同：

| 层 | 命题 | 主语（谁在「接受」） | 本工程现状 |
|---|---|---|---|
| **E1** | 边存在于**编辑器进程内存**的图模型里 | `BeyondEditor.exe` 的原生图模型 | **有**（`inspect-reopen-content`，12 份真机回执） |
| **E2** | 边被**序列化进磁盘文件**（`.gil` field 10） | 编辑器/游戏的存档写入器 | **可解但未对 demo 跑过**（解码器在树里，`audit-native-enums.py:74`） |
| **E3** | 边被**游戏自己的加载器**重建进运行时关卡模型 | `YuanShen.exe` 的关卡加载函数 | **机制在**（reopen），**闸门卡死**（关卡常量，§2d） |
| **E4** | 边被**执行流真正遍历**（逻辑从 from 走到 to） | 游戏运行时的事件/求值引擎 | **弱通道**（图日志），**只能间接、只能证节点**（§2e） |

> **这就是本文件的骨架**：§2 的六类证据，本质是在回答「它能把命题推到 E1/E2/E3/E4 的哪一层」。
> **节点 ≠ 边**：节点只要「在模型里」就基本等于「入档了」（`.gil` 的 `field 10` 里节点表可走行，`GIA-EXPORT-MINE.md` §3）；**边却会在「编辑器 → `.gia`」这一跳凭空消失**（同文件 §4 的精确负证据）。**所以边必须逐层重新证，不能从节点的结论里外推。**

---

## 2. 六类证据，逐类：**对边**能证什么 / 不能证什么

> 排序按**强度递增**（对「边」这一命题）。每类都给出**产出它的文件**。

### (a) 编辑器模型读回（editor model readback）——**已有的东西**

- **产出文件**：`tools/editor-bridge/Adapter/ReopenContentEvidence.cs`（op `inspect-reopen-content`，派发 `ManagedBridge/BridgeServer.cs:449-450,607`）→ 落盘 `.runtime/editor-bridge/runs/<RunId>/inspect-reopen-content-response.json`。
  - 边在这里：`ReopenContentEvidence.cs:183-188`——`map = graph.Model.yKHKOFfNm2M()`（链接表方法，符号表 `EditorBindingProfile.Generated.cs:621`），取字段 `cHuiFsU5V56`（链接字典），每条转成 `linkRows = {from: ContentEndpoint(fH0izeMOw73), to: ContentEndpoint(ABfizkqh4mD)}`；`ContentEndpoint` 在 `:131`。**这就是「边」的读出口。**
  - **对照（关键）**：`graph inspect` **不返回边**——`AuthoringGraph.cs:253-257` 的返回体只有 `nodeCount` + `nodes[{nodeId,definitionId}]` + `boundEntityIds` + `boundToLevel`。**想读边只能用 `inspect-reopen-content`。** 另一条「单条边可核」的路径是 `wire`/`unwire` 里的 `HasLink(LinkMap(model), link)`（`AuthoringGraph.cs:442-453`、`RetireRuntimeSpawns.cs:104-110`），但它**只核一条、只在动作那一刻、不落边集**。
- **真机原件（本文件 `cat` 过，非推测）**：`.runtime/editor-bridge/runs/1a89dbae-5c60-402e-8d4a-5ee5eb2c9219/inspect-reopen-content-response.json`：`levelId=1073741839`、`content.graphCount=3`、`content.nodeCount=33`、`content.linkCount=40`；逐图 `MW_API_Update71_20260926`(2 节点/1 边)、`MW_Bridge_Import_20260916`(2/1)、`MW_MVP_Course_20260922`(**29 节点 / 38 边**)；样例边 `{from:{nodeId:1,kind:2,index:0},to:{nodeId:4,kind:1,index:0}}`、`{from:{nodeId:1,kind:4,index:0},to:{nodeId:3,kind:3,index:0}}`。同形状回执共 **12 份**（`find .runtime/editor-bridge/runs -name inspect-reopen-content-response.json`）。
- **对「边」能证（E1）**：**编辑器的原生图模型确实持有这些边**，且**边集能被完整枚举**（含端点 `nodeId/kind/index`、含方向）。这比你想象的多——它证明 **`wire` / `build-plan` 的连线调用被编辑器接受了**（否则模型的链接表里不会有它）。
- **对「边」不能证**：
  - **不能证 E2**：这是**编辑器进程内存**的读回（`CLAUDE.md` §二：桥改的是编辑器内存）。内存里有 ≠ 磁盘上有。同一份 op 自陈 `persistentSaveVerified:false`（`ReopenContentEvidence.cs:212`）。
  - **不能证 E3/E4**：它没让游戏加载过任何东西，也没让任何逻辑跑过。
  - **不能证 demo 图**：回执里的边属于 `MW_MVP_Course_20260922` 等，**不是** `MW_API_FARM_DEMO`；demo 的边在此 op 下**未被单独留证**（这是「未见」，不是「不存在」）。

### (b) 导出的 `.gia`（exported `.gia`）——**已解码，对边是精确负结果**

- **产出文件**：`tools/editor-bridge/Adapter/AuthoringGraph.cs` 的 `ExportResource`（`:260`，op 路径 `author.py graph export`）→ `.runtime/editor-bridge/exports/*/bridge-export-*.gia`（+ `.gia.reply.json`）。分析见 `GIA-EXPORT-MINE.md`（#9）。
- **对「边」能证**：**几乎什么都不能**。`GIA-EXPORT-MINE.md` §3 证明 `.gia` 有**可走行的节点表**（重复 field 3、索引连续、含 definitionId，且与 plan 的 15 个节点逐位一致）；但 §4 给出**精确负证据**：plan 的 **17 条边**（8 执行 2→1、9 数据 4→3）在 `.gia` 里**找不到对应字段**——2859 条引脚里**没有任何一条承载「另一个节点的索引」**（`GIA-EXPORT-MINE.md` §4.3）。
- **对「边」不能证（当前）**：**不能证 E2 更谈不上 E3/E4**——`.gia` 这一导出**把边丢掉了**，所以它**根本不是**核边的产物。**注意**：这条负结论的边界是明确的——§4.4 的「导出两次做字节差」实验**尚未做**，所以严格表述是「**在已识别的字段里找不到边**」，不是「`.gia` 在原理上不含边」。

### (c) 磁盘上的 `.gil`（on-disk `.gil`）——**边在盘上，且仓内已有解码器**

这里必须分成**两条完全不同的读法**，很多文档把它们混为一谈：

- **读法 1：字节子串计数** —— 产出文件 `tools/gameplan/verify_graph_on_disk.py`。
  - 它做的只是：把 `graph_id` / `entity_id` 的 **canonical varint 编码**在 payload 里数**出现次数**，并按根字段归属（docstring：「`root 5 x1, root 6 x1, root 9 x5, root 10 x1`」）。
  - **对「边」能证**：**零**。它自己的 `DOES_NOT_PROVE` 明写「a byte run matching an id is **not** proof that a well-formed, loadable graph definition is present… It is a substring count over opaque bytes」，且**逐字**说「Nothing here says the graph is well-formed, **bound**, or **executed**」。**拿它的绿判读「边入档了」是误读。**
- **读法 2：`.gil` 节点图解码** —— 产出文件 `tools/editor-bridge/audit-native-enums.py`（`load_graphs`，`:74`）。
  - **它真的解边**：`kind==2`（`.gil` 关卡）分支走 `get_bytes_fields(data[20:-4], 10)` → wrapper field 1 → raw field 1 → **`pb.NodeGraph.ParseFromString`**（`audit-native-enums.py:88-95`）。`NodeGraph` 的每个 node 带 `pins`，每个 pin 带 `connections`（即指向 `target_node_index` + `target_pin_shell.{kind,index}` 的边）。
  - **消费方证据**：`tools/game-executor/native_reopen_acceptance.py` 的 `formal_content`（`:185-234`）正是用它把**磁盘 `.gil` 里的边**解成 `edges` 集合：`:216-229` 逐节点遍历 `n.pins → p.connections → normalized_edge(...)`，并 `:227` 用 `FORMAL_DANGLING_EDGE` 要求每条边的两端都落在节点表里；`normalized_edge`（`:176-182`）还**校验方向**（仅 `(2,1)` 执行 / `(4,3)` 数据合法）。
- **对「边」能证（E2）**：**能证「边被写进了磁盘文件」，且带端点与方向**。这是把 E1（内存）推到 E2（磁盘）的唯一静态手段，而且是**离线**的。
- **对「边」不能证**：
  - **不能证 E3**：字节里在 → **不等于**游戏加载器会接受它。`verify_graph_on_disk.py` 的 docstring 与 `native_reopen_acceptance.py:433-434` 都把「parameter/geometry 的独立映射」显式置 `false`；静态解码器只忠实读出「文件里有什么」，不证明「加载器怎么想」。
  - **对 demo 是「未做」，不是「做过」**：`GIL-FIELD-LEDGER.md` §2.7 对 `1073741842.gil` 的 `field 10` **只量了字节数（5789 B）和 ASCII 串（`MW_API_FARM_*`）**，**没有一次把它的边解出来**。所以「demo 的 17 条边在盘上是否完整、方向是否正确」这个问题**今天还没有答案**——这正是 §4 推荐的第一步。

### (d) 一次 reopen（a reopen）——**唯一能证 E3 的通道**

- **产出文件**：原生探针 `tools/game-executor/native/reopen_action.cpp`（调 `base+0x13564e90`）+ 独立验收器 `tools/game-executor/native_reopen_acceptance.py` → 产物字段 `reopenRoundtripVerified`（`:597`）。分析见 `REOPEN-VERIFICATION-MINE.md`（#10）。
- **对「边」能证（E3，最强）**：reopen 在**一个活着的游戏进程、一次调用**里同时扣住三件事，其中**第二、三件直接涉及边**：
  1. **加载确实发生了**：调用后出现**全新的、唯一的 target iterator**（`load_progress`，`:282-304`；硬门 `:553` `ACTION_LOAD_NOT_PROVEN`）。
  2. **关卡初始化路径重跑**：包 1022 观察器在前后快照里 `currentPayloadSameReference` 由 true 变 false，且多出**恰好一条**新的 `parsed:true` 初始化事件（`:444-453`）。
  3. **加载后的边 == 磁盘上的边 == 编辑器内存里的边**：`compare_content` 把**编辑器 links**（`:397-402`，来自 `inspect-reopen-content`）与**磁盘 `.gil` 的 formal edges**（`:216-229`）逐条对齐，硬门 **`:429` `FORMAL_EDGES:<gid>`**；绑定对齐 `:430` `FORMAL_BINDINGS_MISMATCH`。
  ⇒ **一句话**：reopen 证明的是——**游戏自己的加载器，把文件里的这些边，重建进了运行时关卡模型**。**这是「边被运行时接受（E3）」的唯一定义与唯一证据。**
- **对「边」不能证**：
  - **不能证 E4**：加载 ≠ 执行。`native_reopen_acceptance.py:433-434` 明确把 `formalParameterMappingVerified` / `formalGeometryMappingVerified` 置 false；运行语义（余额 +1、购买成功）不在内（#10 §2）。
  - **【现状】发不出去**：整条链**被常量关卡 id `1073741840` 钉死**——`native_reopen_acceptance.py:26`、`native/reopen_action.h:8` 编译期 `#error`、`scene_cli.py:670`、`elevated-request.py:425` 等（#10 §1.2）；且**半截去常量改造已把验收器 12 条测试搞红**（#10 §1.4）。**所以 E3 今天拿不到**，除非先完成去常量。
  - 代价高：要 live bridge scope + 新观察器 + 账号备份 + 编译探针（#10 §4）。**不是日常验收步骤。**

### (e) 运行期图日志（graph logging at runtime）——**最便宜，但对边最弱**

- **产出文件**：`tools/editor-bridge/Adapter/RunLogSample.cs`（记录读者）+ `Adapter/EditorAdapter.cs`（观察器/闸门）→ `.runtime/editor-bridge/runs/<RunId>/log-observer-evidence-response.json`。分析见 #3/#4/#5。
- **对「边」能证（E4，且只是间接）**：
  - 记录的**唯一**可读身份是「**图名槽（实为运行实例 id）+ 一段打印文本**」（`RunLogSample.cs:30-34,44-78`；#4 §1.2）。**记录里没有边的身份**：#4 §2 逐条说明——桥读的四个成员里没有任何节点 id / 定义 id / 执行标记；反编译里 5 个数值字段 + proto 58 的 `{enum,graphId}` 子消息**桥一个都没读**。
  - **所以它只能这样间接触及边**：某节点 `N` 打印了一段**只属于 `N`** 的常量文本 ⇒ 「`N` 这个节点执行了」⇒ **至少有一条流入 `N` 的边被遍历过**（`N` 若是事件节点则无入边，测试无意义；所以要选**非事件节点**）。这正是 `GRAPH-LOG-SHAPE.md` §4.2 的判据（`MW_API_FARM_DEMO` 的 `id15 def1 打印字符串="货币发生变化"`）。
- **对「边」不能证**：
  - **不能定位是哪一条边**：若 `N` 有多条入边，日志分不出是哪条（或哪几条）承载了这次流。**没有边身份，就没有边的判据。**
  - **不能证 E4 的否定**：`RunLogSample.cs:88-91` 的 `notice` 逐字：「A captured row proves a record was RECEIVED… It does **not** prove… that a graph executed in this session.」#3 §4.2 判定「本次重跑 vs 历史回放」**本轮证据不足以二选一**。
  - **不能证 E1/E2/E3**：它观测的是运行期，不观测模型/文件/加载。
- **【现状】通道要打通得先改代码**：见 §3 的姊妹裁决。

### (f) 一次试玩（a playtest）——**人证，覆盖不到的仍是边**

- **产出文件**：人（`user-playtest-feedback.json`，例如 `.runtime/editor-bridge/runs/624057f7-…/user-playtest-feedback.json`：「已经通了，试玩的时候能看到 6 个平台…」）。
- **对「边」能证**：**任意强度的运行事实，但粒度是「玩法级」**。若「走进去 → 收菜」整条链**人眼可见地完成了**，那就**蕴含**了链上每条边都被遍历（否则走不到终点）——这是**唯一能一次性覆盖 E4 全链**的证据来源。
- **对「边」不能证**：
  - **不能定位是哪条边**：人看到的是**结果**，不是**接线**。同一可见结果可以由**另一套接线**产生；所以它**不能给单条边定向**。
  - **不能替代机器证**：`user-playtest-feedback.json` 自陈 `automatedRuntimeMarkerVerified:false`；`collisionVerified/goalReachedVerified/durableSaveVerified` 全 `false`（#3 §3.2）。同一 run 的观察窗里 `observedLogPackets:0`（#3 §3.4）。
  - **今天跑不了**：demo 的触发链**断在一个加不上的组件上**（`GRAPH-ATTACH-CHAIN.md` §3：地块缺「碰撞触发器」组件，而 `AddComponent` 在四处检索范围 0 命中，`CLAUDE.md` §六(a)）⇒ **首节点 `92 进入碰撞触发器时` 根本不会触发**，试玩看不到任何 harvest leg。

---

## 3. 排名 + 折叠姊妹图日志的裁决

### 3.1 排名（对「边」的强度，从弱到强）

| 排名 | 证据 | 推到的层 | 产出文件 | 今天的状态 |
|---:|---|---|---|---|
| 1 | **(f) 试玩（人证）** | E4（整体） | `user-playtest-feedback.json` | 触发链断（缺组件） |
| 2 | **(e) 图日志** | E4（单节点间接） | `log-observer-evidence-response.json` | 通道要改读者才通；只证节点不证边 |
| 3 | **(b) `.gia` 导出** | —（对边：无） | `bridge-export-*.gia` | 已解码：**边找不到**（精确负） |
| 4 | **(c) `.gil` 子串计数** | —（对边：无） | `verify_graph_on_disk.py` | 自陈不证 well-formed/bound/executed |
| 5 | **(a) 编辑器模型读回** | **E1** | `inspect-reopen-content-response.json` | **有**（12 份真机回执，边集完整） |
| 6 | **(c) `.gil` 边解码** | **E2** | `audit-native-enums.py:74` `load_graphs` | **解码器在，未对 demo 跑** |
| 7 | **(d) reopen** | **E3**（最强） | `native_reopen_acceptance.py` `reopenRoundtripVerified` | 机制在，**闸门卡死** |

> **读法**：这张表把任务里「六类证据」重新钉在 E1–E4 上。**E1 已是既成事实**（不是待办）；**E2 是「差一次运行」**；**E3 是「差一次去常量 + 绿灯」**；**E4 是「差一个组件 + 一条能认领节点的日志」**。

### 3.2 姊妹图日志任务的裁决（#5 `GRAPH-LOG-NEXT-STEP.md`）与 #4（`GRAPH-LOG-SHAPE.md`）

- **#4 的裁决（形状）**：一条记录的可读身份只有「图名 + 打印文本」；**记录里没有节点 id、没有边 id、没有执行标记**（§2）。所以「哪个节点跑了」**只能靠打印文本的唯一性反推**（§4.2）。⇒ **对边，这就宣判了：日志在原理上给不出边的身份。**
- **#5 的裁决（卡点重定位）**：姊妹 #3 判定这 5 个 op「按原样翻不动 `runtimeVerified`」，#5 **同意且独立复算**；但把卡点从「记录认不回自己的图」改成「**桥从来没去读记录自带的那两个能认出图的字段**」——
  - 记录**自带** `{value:enum, graphId:uint}` 子消息（proto 58，字段 `eNLa2VJUc8d`），与「我要选哪张图」用的是**同一个 proto 类型**（§2.2）；
  - 正文载体还自带一个 proto-8 `ulong`（§2.1）；
  - **桥一个字节都没读**（Adapter 全 `grep` = 0）。
- **#5 的单一下一步**：**加宽 `RunLogSample.cs:38-79` 的 `CaptureRunLogRecord`，读 proto-58 `graphId`**，跑**一次** `start-external-asset-observer` →（试玩可选）→ `log-observer-evidence`，回答：「**那条自有 marker 文本所在记录，其 proto-58 `graphId` 是否等于桥选过的图 id（`1073741825`…）**」。

### 3.3 把裁决折进排名后，对「边」意味着什么

- **图日志是最便宜、最值得先做的「节点」证据**——#5 那个动作**不需要超时窗口、不需要唯一 marker、不需要负对照**，成本极低（一次只读观察）。**但它解决的是「归属」（哪张图），不是「边」**：即便 proto-58 命中、`graphId` 认领成功，它证的仍是「**这张图里某个节点打印了**」——**记录里依然没有边**。要把这条证据升级到边，你只能靠「**选一个非事件节点、其入边唯一或可枚举**」的图设计，把「节点执行」**间接**翻译成「**某条边被遍历**」。
- **⇒ 折进来的净结论**：**图日志（e）是「最便宜未开采的**节点**证据」，但它是「对**边**最弱的可用证据」。** 对边，真正便宜且未开采的，是 **E2 的 `.gil` 边解码（§2c 读法 2）**——它同样零接触，却直接产出**边集本身**。
- **因此**：任务说「cheapest unexploited one: a sibling studied graph logging」——**同意「最便宜未开采」，但要在排名里标清它属第 2 档（对边）**；**边的最便宜未开采证据是 E2**。

---

## 4. 单一下一步 + 确切产物

### 4.1 动作一句话

> **用仓内已有的 `.gil` 节点图解码器，把 demo 图 `MW_API_FARM_DEMO`（graphId `1073741829`，level `1073741842`）落在盘上的边解出来，逐条对照 `.runtime/scratch/MW_API_FARM_DEMO-plan.json` 的 17 条边**，回答一句是非题：
> **「`.gil` `field 10` 里那张图，是否包含 plan 的全部 17 条边，且每条 `from/to` 端点与方向都正确？」**

**为什么是它（而不是 #5 的图日志 / #10 的 reopen）**：

1. **它直接产出「边」，不是「节点」。** 这是本任务的核心命题；图日志给不出边（§3.3）。
2. **它是零接触的，且解码器已在树里。** 只有 `Path.read_bytes`（`audit-native-enums.py` docstring：Reads GIA/GIL only；`verify_graph_on_disk.py` docstring：The only I/O is `Path.read_bytes`）。**不连桥、不开游戏、不写档、不编译、不接触 `LocalLow` 以外的任何东西**——完全在本轮 HARD RULES 之内。
3. **它把一条「精确负」翻成「精确正或精确负」。** 今天 `.gia` 不含边（#9 §4），`.gil` 的边**从没被解过**（§2c）；一次运行就把「有字节」变成「有边集」，或证明「`.gil` 也不含边」——**两个结果都可交付**。
4. **它是 E3 的前置基线。** reopen 的比对（`:428-429` `FORMAL_EDGES`）**必须**先有一份可信的「磁盘边集」；本步产出的正是它。**先 E2、后 E3** 是最省的顺序。

**它明确不是终点**：解出磁盘边集**只到 E2**。要 E3 仍须 reopen（§2d，当前闸门卡死）；要 E4 仍须试玩 + 组件（§2f）。**本步只负责把「边在盘上是什么样」这件事，从「从未解过」变成「已解、已对、已落证」。**

### 4.2 具体到「哪个文件、哪几行、期望产物形状」

**代码侧（只调用既有函数，不新增/不改任何代码）**
- 解码器：`tools/editor-bridge/audit-native-enums.py:74` `load_graphs(path)` → 返回 `pb.NodeGraph` 列表（`:88-95` 的 `kind==2` 分支即 `.gil` 的 `field 10`）。
  - 边在 `graph.nodes[*].pins[*].connections[*]`，字段 `target_node_index` + `target_pin_shell.{kind,index}`（同 `native_reopen_acceptance.py:222-226` 的用法）。
  - 方向归一：复用 `native_reopen_acceptance.py:176-182` 的 `normalized_edge`（仅 `(2,1)`/`(4,3)` 合法）。
- 基线：`.runtime/scratch/MW_API_FARM_DEMO-plan.json`（15 节点 / **17 边** / 13 值；来源 `GIA-EXPORT-MINE.md` §4.2）。
- 目标文件：当前 demo 落盘的那份 `.gil`（`1073741842.gil`，`GIL-FIELD-LEDGER.md` §2.7：`field 10 = 5789 B`）；**注意 `CLAUDE.md` §四——关卡 id 是存档的函数，运行前应用 `current-save.py` / 当次回执核对，禁止复制上一轮的 id**。

**运行侧（离线写死；是否执行由人决定）**

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

（脚本形状；**本文件不执行、不新增代码**。实现细节照抄 §4.3 的判据即可。）

**产物**：`.runtime/scratch/MW_API_FARM_DEMO-edges-on-disk.json`，形如

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

（产物**一律写工程内** `.runtime/scratch/`，用 `Path(__file__).resolve().parents[N]` 定根，**禁用 `cwd`**——`CLAUDE.md` §四。）

### 4.3 判据：**回复形状 → 结论**（三种都落盘）

| 观察到的形状 | 结论（才有资格说） |
|---|---|
| `edgeCountOnDisk == 17` **且** `matched==true`（无 `missing`、无 `directionViolations`、无 `dangling`） | **E2 成立**：`field 10` 完整携带 plan 的 17 条边、端点与方向都对 ⇒ **「边被序列化到磁盘」从「未证」变「已证」**。→ 下一步（E3）：修完 reopen 去常量后，用这份边集当 `FORMAL_EDGES` 基线跑一次 reopen |
| 边数**少于** 17 / 有 `missing` / 有 `directionViolations` | **E2 被局部证否**：盘上边集不完整或方向错 ⇒ 与 `.gia`（#9 §4）同类，是**真实缺陷**，应转成 bug（说明写入侧或字段归属需重查）。**这本身是可交付的精确负。** |
| `audit-native-enums.load_graphs` 对目标 `.gil` 抛错（`Invalid container`/`Expected graph GIA`/`ResourceEntry` 不符） | **不可判**（不是「没边」）：说明该解析器对**这份** `.gil` 的容器/字段假设不成立（注意 `load_graphs` 的 `kind==3` 分支是给 `.gia` 的，`.gil` 走 `kind==2`；若 demo 的存档容器 kind 不符，须先定位字段 10 的真实归属，见 `GIL-FIELD-LEDGER.md` §2.7 与 §6.3 的读法冲突）。**先诊断容器，再判边。** |

**只有第一格命中，才允许把「E2：边入档」标为真。** 第二、三格都不构成「边没被建」的证据。

### 4.4 这一步**不能**证明什么（写死，防误读）

- **不能证 E3**：磁盘里有边 **不等于** 游戏加载器接受它。那要求 reopen（§2d），而 reopen 今天被常量关卡 id 闸门卡死（#10）。
- **不能证 E4**：边在盘上 ≠ 边被遍历。遍历要运行期证据（§2e/§2f）。
- **不能证 `.gia` 含边**：本步只看 `.gil`；`.gia` 的边界仍由 `GIA-EXPORT-MINE.md` §4.4 的差分实验负责。
- **不能证 demo「能玩」**：即便 17 条边都在盘上，触发链仍断在「碰撞触发器组件」（`GRAPH-ATTACH-CHAIN.md` §3–4）。
- **不能证坐标/参数映射**：`native_reopen_acceptance.py:433-434` 把 `formalParameterMappingVerified`/`formalGeometryMappingVerified` 置 false；本步同样到不了那一层。
- **未执行**：本步是**尚未执行的、可反驳的**计划。**未跑、未改码**——按 `CLAUDE.md`：未编译/未运行的适配器是候选，不是能力。

---

## 5. 六类证据 × 边的四层：一张总表

| 证据 | 产出文件 | E1 模型 | E2 磁盘 | E3 加载器 | E4 遍历 | 今天可做 |
|---|---|:--:|:--:|:--:|:--:|---|
| (a) 编辑器读回 | `ReopenContentEvidence.cs:183-188` | **✔** | ✘ | ✘ | ✘ | 已做（12 回执） |
| (b) `.gia` 导出 | `AuthoringGraph.cs:260` ExportResource | — | **✘**（#9 §4 精确负） | ✘ | ✘ | 已解码 |
| (c) `.gil` 子串 | `verify_graph_on_disk.py` | ✘ | ✘ | ✘ | ✘ | 已做（只证 id 字节） |
| (c') `.gil` 边解码 | `audit-native-enums.py:74` | ✘ | **▲** | ✘ | ✘ | **未做（§4 推荐）** |
| (d) reopen | `native_reopen_acceptance.py:429,597` | ✘ | ✔ | **▲** | ✘ | 闸门卡死（#10） |
| (e) 图日志 | `RunLogSample.cs:30-34` | ✘ | ✘ | ✘ | **▲**（仅单节点间接） | 需先改读者（#5 §4） |
| (f) 试玩 | `user-playtest-feedback.json` | ✘ | ✘ | ✘ | **▲**（整体人证） | 触发链断（缺组件） |

**✔** = 已证/可直接获得；**▲** = 机制在但未打通或未跑；**✘** = 原理上不能证；**—** = 不适用。

---

## 6. `notClaimed`

- 本轮**什么都没跑**：没有起 bridge、没有发原生/图/日志请求、没有开游戏或编辑器、没有读写任何存档、**没有读任何图片**、**没有改任何代码或文件（只新增本文件）**。
- **没有**证明 `.gil` `field 10` 里 demo 图的边是完整的——那是 §4 的**未执行**计划。
- **没有**证明 reopen 现在能跑通——它被常量关卡 id 卡死且验收器测试已红（#10）。
- **没有**证明图日志能认领自己的图——#5 的 proto-58 动作**尚未执行、尚未编译**。
- **没有**证明 demo 能「玩」——触发链断在加不上的组件上（`GRAPH-ATTACH-CHAIN.md`）。
- **没有**把「E2 成立」写成「E3/E4 成立」——三层分开（`CLAUDE.md` §一.3）。
- **没有**主张 `inspect-reopen-content` 覆盖全部图/实体——回执里 `graphRows` 上界 `CONTENT_GRAPH_LIMIT=128`、`nodes` 上界 4096、`links` 上界 16384（`ReopenContentEvidence.cs:166-184`），**超限即抛，不是静默截断**（这是好设计，但仍是边界）。
- 「软」分歧自陈：本文件对 #5 的唯一异议是**排名归属**（图日志是「最便宜未开采的**节点**证据」，不是「最便宜未开采的**边**证据」），**不是**对其动作本身的否证。

---

## 7. 逐条引用（file:line）

**桥源码**
- `tools/editor-bridge/Adapter/ReopenContentEvidence.cs:131`（`ContentEndpoint`）、`:166-184`（上限 + 链接表）、`:183-188`（**边的读出口**：`map=yKHKOFfNm2M`、字段 `cHuiFsU5V56`、`linkRows` from `fH0izeMOw73`/to `ABfizkqh4mD`）、`:200-212`（`linkCount` 汇总 + `persistentSaveVerified:false`）
- `tools/editor-bridge/ManagedBridge/BridgeServer.cs:449-450,607-608`（op `inspect-reopen-content` 标签与派发）
- `tools/editor-bridge/Adapter/AuthoringGraph.cs:253-257`（`graph inspect` **只返节点、不返边**）、`:260`（`ExportResource`）、`:442-453`（`wire` 后 `HasLink(LinkMap)` 单边核）
- `tools/editor-bridge/Adapter/RetireRuntimeSpawns.cs:104-110`（`LinkMap`/`HasLink` 定义；`yKHKOFfNm2M` 链接表方法、`FZXiF0RdqqB` 存在性谓词）
- `tools/editor-bridge/Adapter/RunLogSample.cs:24,30-34,38-79,88-91`（记录读者；`notice`「收到 ≠ 执行」）
- `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs:399,621`（符号→明文映射：`FZXiF0RdqqB`→`Wx2XX2DJdY5`、`yKHKOFfNm2M`→`JXsX5LHYcwj`）

**离线解码器 / 验收器**
- `tools/editor-bridge/audit-native-enums.py:74` `load_graphs`（`:80-95` 容器校验 + `kind==2` 走 `field 10 → pb.NodeGraph`）
- `tools/game-executor/native_reopen_acceptance.py:176-182`（`normalized_edge` + 方向律）、`:185-234`（`formal_content`：磁盘 `.gil` 的 nodes/edges/bindings）、`:216-229`（逐 `pins.connections` 解边 + `FORMAL_DANGLING_EDGE`）、`:388-402`（编辑器 links 归一 + `EDITOR_EDGE_SET`）、`:428-430`（`FORMAL_NODES`/`FORMAL_EDGES`/`FORMAL_BINDINGS_MISMATCH`）、`:26`（常量 `LEVEL=1073741840`）、`:553`（`ACTION_LOAD_NOT_PROVEN`）、`:597`（`reopenRoundtripVerified`）
- `tools/game-executor/native/reopen_action.h:8`（编译期 `#error`，钉关卡常量）
- `tools/gameplan/verify_graph_on_disk.py`（docstring：只做 varint **子串计数**；`DOES_NOT_PROVE` 明写不证 well-formed/bound/executed）

**真机原件（`.runtime/editor-bridge/runs/`，本文件 `cat`/`find`/`wc` 过）**
- `1a89dbae-5c60-402e-8d4a-5ee5eb2c9219/inspect-reopen-content-response.json`：`levelId=1073741839`、`content.graphCount=3`、`content.nodeCount=33`、`content.linkCount=40`；`graphs[0]=MW_API_Update71_20260926`(2/1)、`graphs[1]=MW_Bridge_Import_20260916`(2/1)、`graphs[2]=MW_MVP_Course_20260922`(**29/38**)；样例边见 §2a
- `5c9906fd-c5eb-454f-b128-29b271814689/…`、`bb676912-66e6-493e-b92d-a9e7e59ed70c/…`：同形（节点/边计数一致）
- `inspect-reopen-content-response.json` 共 **12** 份（`find .runtime/editor-bridge/runs -name inspect-reopen-content-response.json | wc -l`）
- `624057f7-7e2a-40f8-b896-470ceabb7547/user-playtest-feedback.json`（人证原件，本文件引用自 #3 §3.2）

**研究与计划**
- `.runtime/scratch/MW_API_FARM_DEMO-plan.json`（15 节点 / 17 边 / 13 值；经 `GIA-EXPORT-MINE.md` §4.2 引用）
- `docs/research/reverse-eng-20261010/GIA-EXPORT-MINE.md`（§3 节点表可走行；**§4 边找不到**；§4.4 差分实验）
- `docs/research/reverse-eng-20261010/GRAPH-LOG-SHAPE.md`（§1.2 记录被读的四个成员；§1.3 proto 58；**§2 无节点/边身份**；§4.2 文本唯一性判据）
- `docs/research/reverse-eng-20261010/GRAPH-LOG-NEXT-STEP.md`（§2.2 记录自带 proto-58 `graphId`；§3 卡点重定位；**§4 单一下一步=读 proto-58**）
- `docs/research/reverse-eng-20261010/GRAPH-RUNTIME-VERIFY-MINE.md`（§3 真机回执；§4.2 历史回放未决；§5 判定）
- `docs/research/reverse-eng-20261010/REOPEN-VERIFICATION-MINE.md`（§1.2 常量闸门；§2 reopen 能证什么；§4 死胡同判定）
- `docs/research/reverse-eng-20261010/GRAPH-ATTACH-CHAIN.md`（§3 触发链断在组件；§4 判决）
- `docs/research/reverse-eng-20261010/GIL-FIELD-LEDGER.md`（§2.7 `field 10` 只量字节/ASCII）、`docs/editor-catalog/INTERFACE-INVENTORY.md:286`（`LapKOOcuGY1` 连边）
- `CLAUDE.md` §一.3、§二、§四、§五、§六

---

*本文件由 2026-10-10 会话从仓内桥源码、`.runtime/` 反编译语料与真机回执（Bash `grep`/`sed`/`find`/`wc`，**非 Grep 工具**）只读整理；
**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档、未读任何图片**。所有行号为本次 checkout 实测；
所有「=0」均写明检索范围。凡「有字段但没读」均写「未读」；凡语义未证均写「未证/假设」；不确定处写「不确定」。*
