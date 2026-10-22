> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #6 挖 — 图挂上实体之后，世界怎么知道去跑它：`MW_API_FARM_DEMO` 的挂载链

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档、未读任何图片**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。
**本文件只新增自身**，不改其它任何文件。

**证据来源（全部只读）**：
- 仓内桥 C# 源码：`tools/editor-bridge/Adapter/AuthoringGraph.cs`、`EditorAdapter.cs`、`EditorBindingProfile.Generated.cs`
- 仓内官方语料：`docs/official-docs/chapters/*.json`（201 章离线语料）与 `docs/official-docs/INDEX.json`
- 仓内研究文档：`docs/research/reverse-eng-20261010/{COLLISION-TRIGGER-MINE,COMPONENT-WRITER-MINE,GRAPH-RUNTIME-VERIFY-MINE}.md`、`docs/research/game-b-systems-20261009/M1-interaction.md`、`docs/gameplan/{CLEANUP-PLAN,DEMO-GAP,VERTICAL-SLICE,REAL-MACHINE-RUNBOOK}.md`、`docs/editor-catalog/NODE-CATALOG.md`、`docs/gameplay/COLLISION-COMPONENT-MAPPING.md`

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 本文件结论**全是静态**（读源码 / 反编译 / 离线语料 / 回执）；**没有一条是本轮真机跑出来的**。
> 记忆 `absence-of-evidence-discipline`：**"搜不到"≠"不存在"**；凡"N 命中 0"均写明检索范围。

---

## 0. 一句话结论（先给判决）

**图**确实挂上了实体 `1077936129`（bind 有回执、`inspect` 独立读回 `boundEntityIds=[1077936129]`、`.gil` 字节含 graphId）——
但**挂载本身不是触发条件**。官方模型里，实体节点图是**事件驱动**的：它的逻辑由**事件节点**启动，而事件节点
"**仅在节点图所挂载的实体发生特定事件时触发**"。demo 的首节点 `92 进入碰撞触发器时` 要的那个"特定事件"，
**只发给"配置了『碰撞触发器』组件的那个实体"**——而地块实体**既没有证据显示已带**这个组件，**本工程也没有任何原语能加上它**
（`CLAUDE.md` §六(a)：同一命令面里**删存在、加不存在**；边界见 §3.4）。

> **⇒ 一句话：图是挂上去的，但没有任何东西会去跑它。**
> **缺的不是"绑定"，是"一个我们加不了的组件"。** 这是读这份 demo 的人**最需要先知道的一件事**。

---

## 1. 桥这一层：`bind` 到底记了什么（file:line）

### 1.1 `bind` 是一次**委托**，不是一次直写

`bind` 动作的**全部实现**在 `tools/editor-bridge/Adapter/AuthoringGraph.cs:298-318`：

| 步 | 行 | 逐字行为 |
|---|---|---|
| 1 | `:107` | 动作字段表：`["bind"] = new[]{"graphId","expectedNodeCount","entityId"}` |
| 2 | `:135` | 前置门：`expectedNodeCount==0` 或 `entityId==0` ⇒ `AUTHOR_EMPTY_BIND` |
| 3 | `:299` | 图内节点数必须**精确等于** `expectedNodeCount`，否则 `AUTHOR_NODE_COUNT_CONFLICT` |
| 4 | `:300-303` | 按 `entityId` 在**当前编辑器模型**里解析实体，必须**恰好一个**，否则 `AUTHOR_ENTITY_IDENTITY_NOT_UNIQUE` |
| 5 | `:304` | 若该实体的 binding 列表里已有本 `graph.Id` ⇒ 直接返回 `State("already-bound-editor-model-readback")` |
| 6 | `:305-307` | 用原生 getter 复核实体 id / 图 id 一致，否则 `AUTHOR_NATIVE_ID_MISMATCH` |
| 7 | `:309` | 一次性花销 `author-bind:<graphId>:<entityId>`，重复即 `AUTHOR_BIND_ALREADY_ATTEMPTED` |
| 8 | `:311-314` | **造参数**：`args = List<Param>`，四项依次为 `bool(true)`、`uint(entityId)`、`uint(1u)`、`uint(graph.Id)`；工厂 `Wrap` 就是 `Param` 的静态方法（`h8diA3iOGmJ`→bool、`bKliA0tj1p1`→uint、`qsriAuLLSBe`→uint） |
| 9 | `:317` | **派发**：`producer.Ikci0qkvMZX("beyondEditObjService","AddInstructionGraphForEditObj",null,args)` |
| 10 | `:318` | 返回 `status:"binding-requested-readback-pending"`，并**硬写** `persistentSaveVerified=false,runtimeVerified=false` |

- 第 8 步那四个参数的**符号映射**在 `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs`：
  `Ikci0qkvMZX`→`RyJLgKYBqhL`（`:412`）、`h8diA3iOGmJ`→`gg1Lbl0yhBM`（`:544`）、`bKliA0tj1p1`→`tZlLbuOouk5`（`:503`）、`qsriAuLLSBe`→`GIDLbbADocv`（`:582`）。
- **同一条命令还有第二个调用点**：`EditorAdapter.cs:646-654`（旧样例路径，实体号写死 `1094713345`，参数形状逐字相同）。
- **第三个参数 `1u`（`AuthoringGraph.cs:314`）是一枚未命名的常量**——桥没给它起名，也没有任何注释解释它是什么
  （图槽位？图类型？无法从本仓源码判定）。**本节不猜。**

**⇒ 桥做的事是：把"挂图"这件事原样交给编辑器自己的命令 `AddInstructionGraphForEditObj`，走 `beyondEditObjService` 通道。**
桥**没有**直接写任何实体字段——**这是机制事实，由代码本身证明**。这也是 `CLAUDE.md` §二说的"桥改的是编辑器内存"。

### 1.2 `EntityBindings` 读回来的是什么

绑完之后，"这个实体挂了哪张图"这个问题的**读出口**是 `EntityBindings`：

- **规范实现**：`tools/editor-bridge/Adapter/EditorAdapter.cs:216-220`
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  `t6ViSxlgnQ3`→`RIXXd08Ah3A`（`EditorBindingProfile.Generated.cs:591`）＝实体的**"取绑定列表"方法**；
  `VAfiNjPuW4e`→`i4gXwUOgjxk`（`:476`）＝该列表对象里那个**可枚举字段**。
- **每个绑定记录被压成什么**：`EditorAdapter.cs:176-179` 的 `KeyFields`
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  `namiwGPRyPS`→`L0kXNqYb39f`（`Generated.cs:568`）。
- **列表本身长在实体目录快照里**：`EditorAdapter.cs:145-150`，
  `graphBindings=EntityBindings(model).Select(KeyFields).ToArray()`——即 `catalog` op 的 `entities[].graphBindings`。
- **判"某实体是否绑了图 G"用的谓词**：`AuthoringGraph.cs:255-256,262,304`，
  `EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id)`——即**绑定记录的 `id` 字段 == graphId**。

### 1.3 精确陈述：绑定记录**只**记了一个指向图的引用

在本轮**读到的字段范围内**，一条 binding 记录暴露的确切内容是：

| 字段 | 符号 | 含义（桥侧读出） |
|---|---|---|
| 4 个 uint | `oLyiwZX255H/AwbiwrjxUDX/UFWiwJNegmh/RBTiwn649Hy` | 图的东西（`KeyFields` 里与图资源同一套 category） |
| 1 个 uint | `namiwGPRyPS` | **＝ graphId**（判绑谓词就比这个） |

**⇒ 绑定记录里没有组件、没有触发器、没有"生效条件"、没有"何时启动"的任何字段。**
（这是**本轮读到的读出口**——`EntityBindings`＋`KeyFields`——范围内的**精确负面**，不是"原生存了但没有"。
反编译的实体模型里组件集合是**另一条**访问器 `WlJiSPfnM3R()`，见 `COLLISION-TRIGGER-MINE.md` §4.1/§4.2，
**未采进绑定档、本文件不调用**。）

### 1.4 这张被绑的图，按官方口径是哪种图

`AuthoringGraph.cs:239-243` 对图的类别 fail-closed：必须 `category.Length==4 && category[0]==10000u &&
category[2]==21001u && category[3]==0u && AuthorGraphKinds.Contains(category[1])`，
其中 `AuthorGraphKinds = {20000u,20001u,20002u,20007u}`（`AuthoringGraph.cs:17`）。
demo 图走默认 `graphKind=20000u`（`AuthoringGraph.cs:230`）。

对照官方（`mhjwjrr5n73i.json:29,35-37`）：`20000` 这一档属于**"服务端节点图"**，而服务端节点图的四类里
第一类就是**"实体节点图"**。⇒ **demo 挂到实体上的这张图，官方的名字是"实体节点图"。** 下面第 2 节讲的正是它。

---

## 2. 官方这一层：实体节点图**住在哪**、**谁去跑它**（引章）

### 2.1 实体节点图**挂载在实体上** —— 是，官方明写

| 事实 | 逐字原文 | 出处 |
|---|---|---|
| 节点图的生效前提 | "节点图需要通过挂载在实体、单位状态等逻辑元素上时才可以生效" | `mhjwjrr5n73i.json:47`（章 `mhjwjrr5n73i`＝「节点图」，层级 `概念介绍/功能`） |
| 实体节点图**是什么** | "挂载于实体上的节点图，通常来说是实体逻辑的承载者。**生命周期跟随所挂载的实体，当实体被销毁时，节点图也同样不再生效**" | `mhjwjrr5n73i.json:167-169`（表格行名逐字 `实体节点图`） |
| 实体节点图的**挂载入口** | "入口位于：**实体或元件的详情编辑页-节点图配置页签** / (1)…切换到节点图页签 / (2)点击**新增节点图**" | `mhjwjrr5n73i.json:78-79` |
| 挂载是**两步工序** | "在挂载前，需要**先在千星沙箱中制作一张节点图**…制作完成后，对应的节点图挂载入口即可**添加**已制作的节点图" | `mhjwjrr5n73i.json:53`（制作/添加两个动词不同） |
| 节点图分七类，前四类＝服务端 | 实体节点图 / 单位状态节点图 / 职业节点图 / 道具节点图（服务端）；技能 / 造物状态 / 本地过滤器（客户端） | `mhjwjrr5n73i.json:29,35-37` |

⇒ **官方回答"实体节点图住在哪"：挂在某一个"实体或元件"上，随那个实体生死。**桥的 `AddInstructionGraphForEditObj`
（§1.1）**就是**官方的"新增节点图"这一跳（`实体或元件的详情编辑页-节点图配置页签`）。

### 2.2 谁去跑它 —— **事件节点**，且事件"来自所挂载的那个实体"

| 事实 | 逐字原文 | 出处 |
|---|---|---|
| 节点分五类；**事件节点**的定义与硬契约 | "事件节点是**服务端节点图执行流的起始节点**。每个可正常运行的执行流都一定由一个事件节点开始。" | `mhk23ora1wom.json:43-44`（章「基础概念」，层级 `概念介绍/功能/节点图`） |
| **事件从哪来** | "以【选项卡选中时】为例，**事件仅在节点图所挂载的实体发生特定事件时触发**" | `mhk23ora1wom.json:43`（同章） |
| 服务端图**全是事件驱动** | "服务端节点图**均是事件驱动的**，即服务端节点图执行流的起点**一定是事件节点**" | `mhk23ora1wom.json:102-104`（同章） |
| 事件节点的引脚形状 | "逻辑引脚：只有一个逻辑出引脚，没有逻辑入引脚；参数引脚：只有若干出参引脚，没有入参引脚" | `mhk23ora1wom.json:43-44`（同章） |

⇒ **官方回答"谁去跑它"：没有人"去跑"实体节点图——它是事件驱动的，事件节点是唯一入口；而事件**只**发生在
"图所挂载的那个实体"身上。** 换言之：**图挂在谁身上，事件就必须发生在谁身上，图才会动。**

### 2.3 那个"特定事件"是谁产生的 —— **实体上的组件**

demo 的首节点是 `92 进入碰撞触发器时`（`docs/editor-catalog/NODE-CATALOG.md:714`：
`44 | 7128596160922691222 | 92 | 进入碰撞触发器时 | 出×1 | — | 进入者实体GUID、触发器实体、触发器实体GUID、触发器序号、进入者实体 | 6`）。
它的引脚形状（出×1、无入参、5 个出参）**正是** §2.2 里"事件节点"的形状。它由**组件**供给：

| 事实 | 逐字原文 | 出处 |
|---|---|---|
| 碰撞触发器是**挂在运行时实体上的通用组件** | "碰撞触发器组件，提供关卡运行中碰撞检测的检测范围，是进行接触判定的一种工具" | `mh8w69rzuc3i.json:16,22`（章「碰撞触发器」） |
| 它怎么加 | "(1)…打开组件编辑页签 (2)点击下方的**添加通用组件**，选择并点击**碰撞触发器**，成功添加 (3)点击详细编辑" | `mh8w69rzuc3i.json:38-40` |
| **事件发给谁** | "运行中实体A的『碰撞触发源』范围进入其他运行中实体B的『碰撞触发器』范围，**会发送节点图事件给配置『碰撞触发器』的实体**" | `mh8w69rzuc3i.json:92-94` |
| 同一条契约（事件节点侧） | "会发送节点图事件给**配置『碰撞触发器』的实体B**" | `mhn7ko01v3yw.json:18`（章「事件节点」，层级 `节点介绍/服务器节点`） |
| **源侧默认自带** | "造物、角色实体，**默认包含碰撞触发源，无需额外编辑**" | `mhn95di01j84.json:102-104`（章「碰撞触发源」） |
| 源侧的反证 | "对于不包含碰撞触发源的实体，他们**无法通过接触碰撞触发器**，产生进入范围/碰撞范围事件" | `mhn95di01j84.json:108-109` |
| **组件只能编辑期增删** | "组件**仅可在编辑时被添加**到元件和实体上或…删除，**在游戏运行中无法动态添加或删除组件**，部分组件可以通过节点图来进行开启或关闭" | `mhei6orvcbkm.json:53`（章「通用组件」父页） |

**⇒ 完整的挂载/触发链（官方模型）：**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**三个要害，缺一不可**：① **组件**（必须落在**图所挂的那个实体**上）；② **源侧实体**（进入范围——角色默认自带）；
③ **图挂在持组件的那个实体上**。**任何一环缺，事件节点永不触发，图就永远是一堆死节点。**

---

## 3. 把两边接起来：demo 想触发，**今天缺什么**

### 3.1 现在**已经有的**

| 要素 | 状态 | 证据 |
|---|---|---|
| 实体 `1077936129`（名 `土田`，模板 `20001965`，关卡 `1073741842`） | **已建成并落盘** | `docs/gameplan/CLEANUP-PLAN.md:56`（create 回执 `.runtime/game-executor/scene-cli/20261010-003436-create-.../result.json`）；`.gil` `field 5` 12 条记录含它 |
| 图 `MW_API_FARM_DEMO`（`1073741829`，15 节点） | **已建成并落盘** | `CLEANUP-PLAN.md:58`（build-plan 回执）；`field 10` 5789 B |
| 图**挂**到实体 `1077936129` | **已挂上（编辑器模型读回）** | `CLEANUP-PLAN.md:62`：`graph inspect` 独立读回 `boundEntityIds=[1077936129]`；`DEMO-GAP.md:61` |
| `92 进入碰撞触发器时` 节点在图里 | **在**（nodeId 1 `plot_enter`、nodeId 10 `stall_enter`） | `DEMO-GAP.md:39,48,115`；`NODE-CATALOG.md:714` |

⇒ **§1 的绑定链是通的**：桥委托 `AddInstructionGraphForEditObj` → 实体 `1077936129` 的原生绑定列表里出现一条
`id==1073741829` 的记录 → `inspect` 读回 `boundEntityIds=[1077936129]`。**"图挂在实体上"这件事是真的。**

### 3.2 现在**缺的**——就一件，但它是致命的

**缺的是：实体 `1077936129`（地块 `土田`）上的那个「碰撞触发器」组件。**

- **官方要求**：事件"发给**配置『碰撞触发器』的实体**"（`mh8w69rzuc3i.json:92-94`、`mhn7ko01v3yw.json:18`）。
  demo 图挂在这块地块上，事件节点也在这块地块的图上——**所以这块地块必须是"配了触发器的那个实体"**。
- **本工程能加上去吗？不能。**
  - `CLAUDE.md` §六(a)：同一命令面里**删存在、加不存在**。删在
    `.runtime/editor-catalog/resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107`（`DeleteComponentForEditObj`）
    与 `backend.db command_route id4`；`AddComponent` / `CreateComponent` / `AttachComponent` / `InsertComponent`
    在 **12375 个反编译 `.cs` ＋ `string-table.json` ＋ `frontend.db→operation`(44 行) ＋ `backend.db→command_route`(38 行)**
    里**全 0 命中**（范围见 `COMPONENT-WRITER-MINE.md` §5、`COLLISION-TRIGGER-MINE.md` §2.4）。
  - 桥侧：`M1-interaction.md:72`「碰撞触发器 / 碰撞触发源 组件配置读写」＝**不能**；Adapter 无组件写入器；
    `NATIVE_ACTIONS` 只有 6 项、无一项写组件（`docs/research/game-b-systems-20261009/M1-interaction.md`，`DEMO-GAP.md` §三 第 3 行）。
  - 官方也堵死了"运行期加"：组件"**仅可在编辑时添加**"，运行中只能开关（`mhei6orvcbkm.json:53`）。
    ⇒ 连官方都**没有**"用节点图动态加一个组件"这条路——`激活/关闭碰撞触发器`（`mh8w69rzuc3i.json:92-94`）
    是"调整**已存在**的生效参数"，不是"新建组件"。

### 3.3 任务里点名的两个替代方案，逐个判

**(甲) 「把图挂到玩家身上行不行？」——不行，方向反了。**
事件"发给**配置『碰撞触发器』的实体**"（`mh8w69rzuc3i.json:92-94`）。玩家（角色）默认带的是**碰撞触发源**（源侧，`mhn95di01j84.json:102-104`），
**源侧不收这个事件**。要让事件落到玩家身上，就得给**玩家**加一个碰撞触发器——**缺的还是同一个组件写入原语**，
只是位置从地块换成玩家，**没有变好，还丢了地块的身份**。⇒ 换宿主**不解决**问题。

**(乙) 「有没有别的节点/办法凭空触发？」——本轮没找到，且官方模型不给。**
- 直接触发事件节点**不存在**：事件节点"没有逻辑入引脚"（`mhk23ora1wom.json:43-44`），**只能被事件唤醒，不能被连线叫醒**。
- `激活/关闭碰撞触发器`（id 90）**不是新建**：它是"调整**已存在**组件的生效参数"（`mh8w69rzuc3i.json:92-94`）——
  组件都还不存在，谈不上去开关它。
- `.gil` 字节侧也帮不上：`docs/gameplay/COLLISION-COMPONENT-MAPPING.md` 结论 **`collisionMapped=false`**——
  "**尚无证据将任何号命名为碰撞触发器/源**"，社区那份 `collision_configs.py` 的 `to_dict` 只是**中文键**、
  **不是 GIL/protobuf 字段**。⇒ 既**读不出**"地块上到底有没有触发器组件"，也**写不进**。

### 3.4 诚实的边界（这一节专治"绝对化"）

- **不能断言**"地块实体 100% 没有触发器组件"。反编译语料里的**折叠常量命令名**是本轮检索的盲区
  （`ApplyPrefabInstanceChange` 就是这么被漏掉的；见 `COLLISION-TRIGGER-MINE.md` §2.4 的边界注）。
  所以准确表述是：**在"明文字符串可达的命令名"＋已解出的实体模型范围内，没有"给实体加组件"的写入原语**，
  且**没有任何证据**显示地块已自带触发器。**因此这条链在当前手段下无法建成，也无法被证否。**
- **也不要说**"桥把图挂错了地方"。**挂的地方是对的**（图挂在持有/应当持有触发器的那个实体上）——
  错的/缺的是**触发器组件本身**。

---

## 4. 判决（读者只读这一段也够）

> ### 图**是挂上了**，但**没有任何东西会去跑它**——除非先有一个我们**加不上**的组件。

**完整判据链**（全部 file:line，全部静态）：

1. 桥的 `bind`＝委托 `AddInstructionGraphForEditObj`（`AuthoringGraph.cs:317`），它**只**在实体上留下一条
   "指向 graphId 的引用记录"（`EditorAdapter.cs:216-220,176-179`；判绑谓词 `AuthoringGraph.cs:262,304`）。
   **绑定记录里没有触发器、没有生效条件**（§1.3）。⇒ **"挂上"≠"会跑"。**
2. 官方：实体节点图挂在实体上、生命周期跟随实体（`mhjwjrr5n73i.json:47,167-169`）；且它是**事件驱动**的，
   事件节点是唯一起点，事件"**仅在所挂载的实体发生特定事件时触发**"（`mhk23ora1wom.json:43-44,102-104`）。
3. 官方：`92 进入碰撞触发器时` 的那个事件，**只发给"配置了『碰撞触发器』组件的实体"**
   （`mh8w69rzuc3i.json:92-94`、`mhn7ko01v3yw.json:18`）；组件**只能在编辑期加**（`mhei6orvcbkm.json:53`）。
4. 本工程：**加组件这条命令不存在**（`CLAUDE.md` §六(a)；`AddComponent` 等四名在四处检索范围全 0 命中；
   `M1-interaction.md:72`）。`.gil` 侧 `collisionMapped=false`，读也读不出、写更写不进。

**⇒ 对 demo 的那条"走进去→收菜"leg：**

- 今天**确实**会发生的：图在编辑器模型里存在、绑在地块 `1077936129` 上、随关卡落进 `.gil`。
- 今天**不会**发生的：`92 进入碰撞触发器时` 触发。因为**唯一能唤醒它的那个组件（地块上的碰撞触发器），
  本工程既没有任何证据显示它已在、也没有任何原语去加上它**。
- **解锁条件（ONE）**：一条"给实体加组件"的写入原语——最可能的落点是 `beyondEditObjService` 派发器上的
  `AddComponentForEditObj`（同族的 `DeleteComponentForEditObj` 已在同一张表里），或编辑器模型直改
  `entity.WlJiSPfnM3R().X66ijdVvJ0k(...)`（该 `Add` 在反序列化路径里**正在被调用**，
  `COLLISION-TRIGGER-MINE.md` §4.1）。**在那之前，这条 leg 只能"配一配"，不能"跑一跑"。**

**并且——就算组件加上去了，也还不是"能玩"**：demo 整条 harvest leg 的下游还压着类型 8（道具）/10（货币）/
15（商店）模板的缺失（`DEMO-GAP.md` §一/§四：REAL-MACHINE VERIFIED = 0/15）。**本文件只回答"挂载链哪里断"——
答案就一处：触发器组件。** 更远的缺口不在本文件范围，但读者不该把它们当成"已经好了"。

> 最后一条口径（`GRAPH-RUNTIME-VERIFY-MINE.md` §6）：`runtimeVerified` 全仓**恒 `false`**，是桥**刻意**写下的保守断言
> （`AuthoringGraph.cs:318`、`EditorAdapter.cs` 多处）。**"图挂上了"这句话本身，绝不能读成"图会跑"。**

---

## 5. 证据索引

| 论断 | 证据 |
|---|---|
| `bind` 动作字段/门 | `tools/editor-bridge/Adapter/AuthoringGraph.cs:107,135,298-318` |
| `bind` 派发 `AddInstructionGraphForEditObj` | `AuthoringGraph.cs:311-314,317`；`EditorAdapter.cs:646-654` |
| 参数工厂/派发器符号映射 | `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs:412,476,503,544,568,582,591` |
| `EntityBindings` 读回实现 | `tools/editor-bridge/Adapter/EditorAdapter.cs:216-220`；`KeyFields` `:176-179`；`catalog.graphBindings` `:145-150` |
| 判绑谓词 = binding.id==graphId | `AuthoringGraph.cs:255-256,262,304` |
| 图类别 fail-closed / 服务端 kind | `AuthoringGraph.cs:17,230,239-243` |
| 实体节点图挂实体、生命周期跟随 | `docs/official-docs/chapters/mhjwjrr5n73i.json:47,78-79,167-169` |
| 七类图 / 前四类服务端 | `docs/official-docs/chapters/mhjwjrr5n73i.json:29,35-37` |
| 事件节点 = 服务端图起点 / 事件来自所挂实体 | `docs/official-docs/chapters/mhk23ora1wom.json:43-44,102-104` |
| 碰撞触发器=实体通用组件 / 添加路径 / 事件发给持组件实体 | `docs/official-docs/chapters/mh8w69rzuc3i.json:16,22,38-40,92-94` |
| 事件发给"配置碰撞触发器的实体B" | `docs/official-docs/chapters/mhn7ko01v3yw.json:18` |
| 源侧默认自带 / 无源则无事件 | `docs/official-docs/chapters/mhn95di01j84.json:102-104,108-109` |
| 组件仅编辑期增删 | `docs/official-docs/chapters/mhei6orvcbkm.json:53` |
| 节点 92 形状（出×1、无入参、5 出参） | `docs/editor-catalog/NODE-CATALOG.md:714` |
| demo 实体/图/绑定/落盘 | `docs/gameplan/CLEANUP-PLAN.md:56,58,62,76-77`；`docs/gameplan/DEMO-GAP.md:39,48,61,115` |
| 无 AddComponent（四处检索全 0） | `CLAUDE.md` §六(a)；`docs/research/reverse-eng-20261010/COMPONENT-WRITER-MINE.md` §2.4/§5；`COLLISION-TRIGGER-MINE.md` §2.4 |
| 桥侧不能写组件 | `docs/research/game-b-systems-20261009/M1-interaction.md:70-72`；`DEMO-GAP.md` §三 |
| 加组件的最可能落点 | `docs/research/reverse-eng-20261010/COLLISION-TRIGGER-MINE.md` §4.1（`WlJiSPfnM3R`/`X66ijdVvJ0k`） |
| `collisionMapped=false` / 社区键非 GIL 字段 | `docs/gameplay/COLLISION-COMPONENT-MAPPING.md`（结论节） |
| `runtimeVerified` 恒 false 是刻意 | `docs/research/reverse-eng-20261010/GRAPH-RUNTIME-VERIFY-MINE.md` §4.3/§6；`AuthoringGraph.cs:318` |

---

## 6. `notClaimed`

- 本轮**什么都没跑**：没有起 bridge、没有发原生/图请求、没有开游戏或编辑器、没有读写任何存档、**没有读任何图片**。
- **没有**证明"给实体加组件"在**所有**可能的实现路径上都不存在；**只**在"明文字符串可达的命令名＋已解出的实体模型"范围内
  证明**本工程无此原语**（折叠常量命令名是已知盲区）。
- **没有**证明地块 `1077936129` 的模板 `20001965` **一定**不自带碰撞触发器——只是**没有证据**它自带，且 `.gil` 侧
  `collisionMapped=false` 使这一点**既不能证实也不能否证**。
- **没有**主张"把图挂到玩家上"之外还有第三条路被漏掉；只是在官方模型与本仓检索范围内**未找到**。
- `AuthoringGraph.cs:314` 的第三个参数 `1u` **含义未定**，本文件不猜。
- **没有**证明 demo 加上触发器后就能"玩"——下游还缺类型 8/10/15 模板（`DEMO-GAP.md`）。
- "图挂上了"**不等于**"图会跑"；"节点在图里"**不等于**"节点会执行"——与本工程既定三层口径一致。

---

*本文件由 2026-10-10 会话从仓内桥源码、官方离线语料（`docs/official-docs/chapters/`）与研究文档只读整理；
**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档、未读任何图片**。所有行号为本次 checkout 实测。
负面结论均写明检索范围；不确定处写「不确定」。*
