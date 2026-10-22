> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #7 挖 — 一张「挂上了的图」在运行时**是凭什么被找到并跑起来的**（GRAPH-BINDING-RUNTIME）

**产出日期**：2026-10-10。位置：`docs/research/reverse-eng-20261010/GRAPH-BINDING-RUNTIME.md`。
**任务（#7）**：(1) 读桥 `AuthoringGraph.cs` 的 `bind`（`AddInstructionGraphForEditObj`）与 `State()` 的
`boundToLevel`/`boundEntityIds`，逐条报**记了什么、记在哪**（file:line）；(2) 从**官方语料**回答：引擎对一张
挂到实体上的图在运行时**做什么**、**哪些事件节点能在实体上触发**、**触发需要什么**（引章）；(3) 合起来给
**我们这张 demo 图**（挂在本轮建的地块实体上）列出「要真跑起来必须成立什么」；(4) 判决：**UAC 之后那批活
能不能证到 RUNTIME，还是只能证到 model。**

**口径（HARD RULES 遵守情况）**：**纯离线、纯只读**。全程**未启动/触碰游戏或编辑器、未连桥、未发任何报文、
未注入、未提权、未重启 helper、未写任何存档、未读任何图片**。读取范围＝① 仓内桥 C# 源码
② **仓内反编译语料** `.runtime/editor-catalog/resolved/*.cs`（12375 份，用 Bash `grep`/`sed`——**Grep 工具会
静默跳过 `.runtime/`**，见 `CLAUDE.md` §一.2）③ 官方离线语料 `docs/official-docs/chapters/*.json`（含
`docs/official-docs/INDEX.json`）④ 姊妹研究报告与 `docs/gameplan/*`。**本文件只新增自身**，不改任何其它文件、
不改任何代码。
> 三层分标（`CLAUDE.md` §一.3 / §五）：`文档写了什么` / `工具能做什么` / `真机验证过什么` 分开标。
> 反编译语料用「`文件:行`（反编译原件）」标注，与「`桥源码:行`」分开。不确定处写「未证 / 不猜」。
> **「搜不到」≠「不存在」**（`CLAUDE.md` §一.5）：凡「0 命中」均写明检索范围。

---

## 0. 一句话结论（先给判决）

1. **桥的 `bind` 自己什么都不记。** 它是**一次委托**：把「挂图」原样交给编辑器自己的命令
   `AddInstructionGraphForEditObj`（`AuthoringGraph.cs:317`）。**这条命令的调用点，本轮在反编译语料里找到了官方原件**
   ——`VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:2118`（反编译原件）里，编辑器**自己**用**逐字相同**的四参
   `(bool true, entityId, uint 1, graphId)` 调同一条命令。⇒ **桥复刻的就是编辑器「实体/元件详情页-节点图配置页签」
   上那个「新增节点图」按钮**（`mhjwjrr5n73i.json` §三.1）。
2. **"记了什么"是可读回、且可持久化的**：实体原生绑定列表里多一条「指向 graphId 的引用记录」（`EditorAdapter.cs:216-220,176-179`）；
   `State()` 的 `boundEntityIds` / `boundToLevel` 就是这条记录的**两个读出口**（`AuthoringGraph.cs:251-258`）。
   绑定记录里**没有组件、没有触发条件、没有生效时机**——这一点与 `GRAPH-ATTACH-CHAIN.md` §1.3 一致。
3. **运行时侧**：官方语料把实体节点图定义为**事件驱动**的（`mhk23ora1wom.json` §fact3/§fact13）。引擎**不"遍历"图**——
   它把**事件**投递给「**图所挂载的那个实体**」，该实体的图里**事件节点**（服务的唯一执行流起点）被唤醒，再顺执行流往下跑。
   **哪些事件能在实体上触发由官方 `mhn7ko01v3yw`（事件节点章）逐条给出：28 类 / 65 个具名事件节点**，每一类都能读出
   「它必须有什么才触发」（见 §2.3）。
4. **最锋利的一句**：**事件节点不是被连线叫醒的**——事件节点"没有逻辑入引脚"（`mhk23ora1wom.json` §fact3），
   **只能被事件唤醒**。而多数事件又"**只发给配置了对应组件的那个实体**"。⇒ 「图被找到」和「图被执行」是两件事：
   **找到一个绑定记录 ≠ 图会跑**。
5. **对我们 demo 的判决**：图**挂对了地方**，但**首节点 `92 进入碰撞触发器时` 的那个事件，只发给"配置『碰撞触发器』组件的实体"**，
   而 `DEMO-GAP.md` §三 第 3 行 / `GRAPH-ATTACH-CHAIN.md` §3.2 已证：**本工程无"加组件"原语**，且**无证据**地块自带该组件。
   ⇒ **今天这张图在运行时不会动**（`GRAPH-ATTACH-CHAIN.md` §4 同判）。
6. **对「UAC 之后能证到什么」的判决**：`POST-UAC-PACKET.md` 里排的六步（helper 起、指针、`load`、`live`、
   **`inspect-entity-components`**、`graph inspect`）**没有一步会让图跑**。它们能把 **model 层**（E1）焊死——
   尤其 §5 那一次组件读**能首次回答**「地块上到底有没有那个触发器组件」；**但 Runtime（E3/E4）一行也证不到**。
   见 §4 的判决表。

---

## 1. 桥这一层：`bind` 到底记了什么、记在哪（file:line）

### 1.1 `bind` 是一条**委托**，不是一次直写

`bind` 动作的全部实现在 `tools/editor-bridge/Adapter/AuthoringGraph.cs:298-318`：

| 步 | 行 | 逐字行为 |
|---|---|---|
| 1 | `:107` | 动作字段表：`["bind"] = new[]{"graphId","expectedNodeCount","entityId"}` |
| 2 | `:135` | 前置门：`expectedNodeCount==0` 或 `entityId==0` ⇒ `AUTHOR_EMPTY_BIND` |
| 3 | `:299` | 图内节点数必须**精确等于** `expectedNodeCount`，否则 `AUTHOR_NODE_COUNT_CONFLICT` |
| 4 | `:300-302` | 按 `entityId` 在**当前编辑器模型**里解析实体，必须**恰好一个**，否则 `AUTHOR_ENTITY_IDENTITY_NOT_UNIQUE` |
| 5 | `:304` | 若该实体的绑定列表里已有本 `graph.Id` ⇒ 直接返回 `State("already-bound-editor-model-readback")`（**幂等**） |
| 6 | `:305-307` | 用**原生 getter** 复核：实体 id（`G9oiCBkSaYQ`）== `entityId`、图 id（`MexKm2jjjVm`）== `graph.Id`，否则 `AUTHOR_NATIVE_ID_MISMATCH` |
| 7 | `:308-309` | 一次性花销键 `author-bind:<graphId>:<entityId>`，重复即 `AUTHOR_BIND_ALREADY_ATTEMPTED` |
| 8 | `:310-314` | **造参数**：`args = List<Param>`，四项依次 `bool(true)`、`uint(entityId)`、`uint(1u)`、`uint(graph.Id)` |
| 9 | `:315-317` | **派发**：`producer.Ikci0qkvMZX("beyondEditObjService","AddInstructionGraphForEditObj",null,args)` |
| 10 | `:318` | 返回 `status:"binding-requested-readback-pending"`，并**硬写** `persistentSaveVerified:false,runtimeVerified:false` |

**⇒ 桥做的事**：把"挂图"这件事原样交给编辑器**自己的**命令 `AddInstructionGraphForEditObj`（走 `beyondEditObjService` 通道）。
**桥没有直接写任何实体字段**——这是机制事实，由代码本身证明。

符号映射（`tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs`）：
`Ikci0qkvMZX`→`RyJLgKYBqhL`（`:412`）、`h8diA3iOGmJ`→`gg1Lbl0yhBM`（`:544`）、`bKliA0tj1p1`→`tZlLbuOouk5`（`:503`）、
`qsriAuLLSBe`→`GIDLbbADocv`（`:582`）；实体 id getter `G9oiCBkSaYQ`→`YwIXdnjaMpN`（`:401`）、图 id getter
`MexKm2jjjVm`→`K17XuvJmjm3`（`:434`）。**同一条命令还有第二个调用点**：`EditorAdapter.cs:646-654`（旧样例路径，
实体号写死，参数形状逐字相同）。

### 1.2 **新证据（本轮首见）**：官方原件里，编辑器**自己**就是这么调的

反编译语料 `.runtime/editor-catalog/resolved/VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:2118`（反编译原件），
在方法 `public bool BlKKB2np35C(kg9jHSKBgsfObR2IXdPf P_0)`（`:2035`，类 = `fYiNtsjNFLpjCdRQ3Cvj.snNdG3jNcHxXOpcU0fHG`，
`Generated.cs:477`）里，编辑器**自己**派发：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**逐字与桥的四参相同**（`AuthoringGraph.cs:313-314`）。同一方法里还有**另外两个**挂图调用点，共同画出编辑器的挂载族：

| 反编译原件行 | 命令 | 参数形状 | 说明（本文判读） |
|---|---|---|---|
| `:2118` | `AddInstructionGraphForEditObj` | `(true, entityId, 1u, graphId)` | **挂到实体**——桥复刻的就是这条 |
| `:2085` | 服务 `gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP::yPFiAIrmqCV` | `(prefabId.VKeiBaSKFxp, 1u, graphId.MexKm2jjjVm)` | **挂到元件**（少一个前导 bool，仍在同一 `1u`） |
| `:2094-2095` | `"attachInstructionGraph"`（string 119440） | `(uint value)` 单参 | 另一条挂载入口（**参数形状不同，本文件不展开**） |

**三条硬事实**：
- 官方挂图**用的是桥在 `:305-306` 复核的那两个 getter**（`G9oiCBkSaYQ` 实体 id、`MexKm2jjjVm` 图 id）——桥的复核不是自创。
- 出现的方法名**既有** `AddInstructionGraphForEditObj`（实体位）**又有** `attachInstructionGraph`（另一入口）——即**桥用对了实体那一条**。
- **第三个参数 `1u` 在两处挂载（实体位、元件位）里都是同一个字面量 `1u`**。这是对 `GRAPH-ATTACH-CHAIN.md:54`「`1u` 含义未定」
  的一处**有限推进**：它是**挂载这一动作的共用常量**（实体/元件两形共用），**不是实体专有值**。**但仍无人命名它**——反编译原件与官方语料都**没有**给出它的语义名，**本文件不猜。**

> 边界：这条方法**属于编辑器进程**（它先查 `Oe5aspiVGooyp47o5s0q::wAXirPMXQCJ`（`:2037`）——**正是桥 `EditorAdapter.cs:55`
> 用的同一个"编辑器可同步"谓词**）。所以它证明的是**编辑器侧**的挂载怎么写，**不是游戏运行时的加载**。见 §2.4。

### 1.3 `State()` 的 `boundEntityIds` / `boundToLevel`：读出口与精确语义

`State()` 是 `AuthorGraph()` 的局部函数，`tools/editor-bridge/Adapter/AuthoringGraph.cs:251-258`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**逐字语义**（`namiwGPRyPS`→`L0kXNqYb39f`＝绑定记录里的 id 字段；`Qi8iCzKCkTt`→`xVGXdUihBZU`＝实体的身份 key；
`Stored(model, field)`＝取 `model.field.VpIiRZgdEln`，`EditorAdapter.cs:81-85`）：

| 字段 | 定义（逐字） | 一句话 |
|---|---|---|
| `boundEntityIds` | 全部**实体模型**里，「其 `EntityBindings(e)` 里存在一条 `id==graph.Id`」的那些实体 → 取它们**自身的 id** → 去重 | **"哪些实体挂了这张图"**（含地块这类普通实体） |
| `boundToLevel` | `level` 数组（**自身 id == `1094713345u`** 的实体，即**关卡实体**）里，是否有实体挂了这张图 | **"这张图是不是挂在关卡实体上"** |

- `level` 的判定**写死一个常量 `1094713345u`**（`:252`）＝ `0x41400001`——它是**关卡实体**在当前存档里的 id
  （同值另见 `EditorAdapter.cs:636,837`、`FinishGraph.cs:295`、`GameLoopGraph.cs:476`；`OwnedEntityRecovery.cs:42`
  把它列在自有实体表里）。**注意 `CLAUDE.md` §三：关卡 id 是存档的函数、永不固化**——这里固化的不是关卡 id 而是
  **关卡实体 id**，两者在这套存档里恰好都随存档变；`boundToLevel` 因此**只对"图挂在关卡实体上"这一种情形有意义**，
  对**用户实体**（我们的地块）恒 `false`。
- **本轮 demo 的真机读回**（`docs/STATE-CARD.md:33`）：`boundEntityIds [1077936129]`、**`boundToLevel:false`**
  ——**图挂在地块实体上，不在关卡实体上**，与 §1.1 第 8 步 `entityId=1077936129` 一致。
- `boundEntityIds` 的读出口是 `EntityBindings`（`EditorAdapter.cs:216-220`）：调实体原生方法 `t6ViSxlgnQ3`（→`RIXXd08Ah3A`，
  `Generated.cs:591`）拿绑定列表，再取字段 `VAfiNjPuW4e`（→`i4gXwUOgjxk`，`:476`）那个可枚举。每条绑定被 `KeyFields`
  （`EditorAdapter.cs:176-179`）压成 `{category:[4 uint], id:uint}`。

### 1.4 一条绑定记录**只**记了一个指向图的引用（精确负面）

在本轮读到的读出口（`EntityBindings` + `KeyFields`）范围内，一条 binding 暴露的确切内容是：
**4 个 uint（图那套 category）+ 1 个 uint（`namiwGPRyPS` == graphId）**。
**没有组件、没有触发器、没有"生效条件"、没有"何时启动"的任何字段。** ⇒ **绑定记录 = 一条引用，不是一个计划。**
（这是**读出口范围内的精确负面**，不是"原生存了但没读"；实体模型的组件集合是**另一条**访问器，见 `COLLISION-TRIGGER-MINE.md` §4。）
与 `GRAPH-ATTACH-CHAIN.md` §1.3 结论一致。

### 1.5 这条绑定是**可持久化、随实体走**的

官方：**元件导出时，挂载节点图跟随文件同步导出；实体导出时，归属元件（如有），挂载节点图同步导出**
（`mhxbd59urbfu.json` §fact4，章「资产导入导出」）。⇒ **挂图是实体资产的持久属性**，不是编辑器内存里的临时态。
这正是「`bind` 之后要落盘必须 save」的官方依据（桥侧见 `docs/STATE-CARD.md:33`：绑定只在编辑器模型里、靠随后原生 `save` 落盘）。

---

## 2. 官方这一层：引擎对一张"挂到实体上的图"在运行时**做什么**（引章）

> **本章所有引用来自 `docs/official-docs/chapters/*.json`**（derived corpus，`INDEX.json` 记 201 章）。
> 引用格式：`章节 <pathId>` + `§fact<n>`（`facts[]` 数组下标，可逐条核对）+ 逐字原文。

### 2.1 「挂上」是**生效前提**——官方明写

| 事实 | 逐字原文 | 出处 |
|---|---|---|
| 生效前提 | "节点图需要通过挂载在实体、单位状态等逻辑元素上时才可以生效" | 章节 `mhjwjrr5n73i`（节点图）§fact4 |
| 实体节点图**是什么** | "挂载于实体上的节点图，通常来说是实体逻辑的承载者。**生命周期跟随所挂载的实体，当实体被销毁时，节点图也同样不再生效**" | `mhjwjrr5n73i` §fact24（表格行名逐字 `实体节点图`） |
| 挂载是**两步工序** | "在挂载前，需要**先在千星沙箱中制作一张节点图**…制作完成后，对应的节点图挂载入口即可**添加**已制作的节点图" | `mhjwjrr5n73i` §fact5 |
| 实体节点图的**挂载入口** | "入口位于：**实体或元件的详情编辑页-节点图配置页签** / (1)…切换到节点图页签 / (2)点击**新增节点图**" | `mhjwjrr5n73i` §fact9 |

⇒ **桥的 `AddInstructionGraphForEditObj`（§1.1）就是官方的「新增节点图」这一跳**；官方挂载入口的宿主是
「**实体或元件**」（`mhjwjrr5n73i` §fact9），与 §1.2 反编译原件里的实体位/元件位两条调用**一一对应**。

### 2.2 引擎**不"遍历图"**：服务端图是**事件驱动**，事件节点是唯一起点

| 事实 | 逐字原文 | 出处 |
|---|---|---|
| 事件节点的**硬契约** | "**事件节点是服务端节点图执行流的起始节点。每个可正常运行的执行流都一定由一个事件节点开始。**" | `mhk23ora1wom`（基础概念）§fact3 |
| 事件**从哪来** | "以【选项卡选中时】为例，**事件仅在节点图所挂载的实体发生特定事件时触发**" | `mhk23ora1wom` §fact3 |
| 服务端图**全是事件驱动** | "**服务端节点图均是事件驱动的**，即服务端节点图执行流的起点**一定是事件节点**" | `mhk23ora1wom` §fact13 |
| 三类图的**起点**不同 | 服务端图起点＝事件节点；技能图起点＝固定的「节点图开始节点」；本地过滤器图**无起点**，只有「节点图结束节点」 | `mhk23ora1wom` §fact13 |
| 事件节点**引脚形状** | "逻辑引脚：**只有一个逻辑出引脚，没有逻辑入引脚**；参数引脚：只有若干出参引脚，没有入参引脚" | `mhk23ora1wom` §fact3 |

⇒ **官方回答"谁去跑它"**：没有人"去跑"实体节点图。**它是事件驱动的；事件节点是唯一入口，而事件只发生在
"图所挂载的那个实体"身上。** 换言之：**图挂在谁身上，事件就必须发生在谁身上，图才会动。**
**（这条直接判死"有没有别的办法凭空叫醒图"——事件节点没有入引脚，连线叫不醒它。）**

### 2.3 哪些事件节点能在**实体**上触发、各需什么（`mhn7ko01v3yw` 事件节点章）

该章以 **28 个中文分类 / 65 个具名事件节点**逐条列出（`mhn7ko01v3yw` §fact0），每节点只给「节点功能」+「节点参数」两段，
**参数表里只有「出参」、没有一行「入参」**（§fact1）——再次佐证 §2.2 的"事件节点只能被事件唤醒"。
**触发所需的"必须有什么"**，逐类摘录如下（逐字原文取自同章 facts）：

| 类 | 代表事件节点 | **触发必须有什么**（逐字/直引） | 出处(fact) |
|---|---|---|---|
| 一 自定义变量 | 自定义变量变化时 / 节点图变量变化时 | 事件只发给"**当前节点图所关联实体**"；**泛型必须已确定类型**否则收不到；容器变量**没有**变化前/后值出参 | f3,f4,f5,f6 |
| 二 预设状态 | 预设状态变化时 | 实体**预设状态发生变化**（出参为整数，非泛型） | f7 |
| 三 实体相关 | **实体创建时** | "**所有类型的实体均可以触发该事件**。关卡实体、角色实体和玩家实体**会在进入关卡时**触发" | f8 |
| 三 实体相关 | 实体移除/销毁时、实体销毁时 | 范围"关卡内任意实体/物件和造物"；**"仅在关卡实体上可以触发"**（实体本身收不到） | f9,f11；另见章节 `mh3pgiraqkiu`（关卡）§fact6 |
| 四 阵营相关 | 实体阵营变化时 | 实体**阵营变化** | f14 |
| 五 玩家与角色 | 角色倒下时 / 复苏时 | "**角色实体上的节点图**可以触发"（接收者是角色实体，非玩家实体） | f16 |
| 五 玩家与角色 | 前台角色变化时 | **仅经典模式**；在**玩家实体**上触发 | f17 |
| **六 碰撞触发器** | **进入/离开碰撞触发器时** | **A 侧必须配「碰撞触发源」（角色/造物默认自带）；B 侧必须配「碰撞触发器」；事件只发给"配置『碰撞触发器』的实体B"** | **f18** |
| 七 战斗 | 受到攻击时 / 攻击命中时 / 被恢复生命值时 / 发起恢复生命值时 | 实体**受到攻击/造成命中/被治疗/发起治疗**（经典模式有免责句） | f19,f20,f22 |
| 七 战斗 | 进入易受打断状态时 | **仅超限模式** | f23 |
| 八 运动器 | 基础运动器停止时 / 路径到达路点时 | 接收者＝**基础运动器组件的持有者**；路径事件**需在路点配置中勾选"到达路点发送事件"** | f24,f25 |
| 九 命中判定 | 命中检测触发时 | **命中检测组件**的持有者；须**先配本地过滤器节点图**判"合法目标" | f26 |
| 十 定时器 | 定时器触发时 | 定时器运行到指定时间节点——**须图内先跑【启动定时器】** | f27 |
| 十一 全局计时器 | 全局计时器触发时 | **只有倒计时的全局计时器**到点触发；正计时**不触发** | f28 |
| 十二 界面控件组 | 界面控件组触发时 | 控件白名单仅 4 种（交互按钮/道具展示/自定义按钮/自定义开关）；**只有触发交互的那名玩家**能收到 | f29,f30 |
| 十三 单位状态 | 单位状态结束时 / 变更时 | "单位状态因为各种原因被移除或因时长结束时触发"；变更以"**层数发生变化**"为条件（施加与移除都触发） | f31,f32 |
| 十四 选项卡 | 选项卡选中时 | 接收者＝"**配置选项卡组件的实体节点图**" | f35 |
| 十五 造物 | 造物入战时 / 脱战时 | **仅经典仇恨模式** | f36 |
| 十七 技能 | 技能节点调用时 | 由**技能节点图的【通知服务器节点图】节点**触发 | f38 |
| 十九 信号 | 监听信号 | 信号**须已在信号管理器中定义**，且监听前**选择信号名** | f40 |
| 二十一 文本气泡 | 文本气泡完成时 | 实体**既挂载文本气泡组件、又完成对话** | f43 |
| 二十二 商店 | 商店出售…/收购道具时 | 接收者＝**商店组件的持有者** | f44 |
| 二十三 装备 | 装备词条…/初始化/穿脱 | "**需要配置在道具节点图里**" | f45,f46 |
| 二十四 道具 | 背包道具新增/失去/数量变化/被使用时 | 接收者＝"**该道具关联的道具节点图**"；纯数量变化**不触发**"新增" | f48 |
| 二十五 造物巡逻 | 造物抵达巡逻路点时 | 需在**巡逻模板里勾选该路点的"到达发送节点图事件"**；只能造物的节点图收到 | f50 |
| 二十七 悬浮交互页 | 悬浮交互页操作触发时 | 页签/单选项视窗**须启用【返回服务器事件】开关** | f52 |

**⇒ 归纳出的三条"触发前必须为真"**（贯穿全章）：
1. **图挂在该实体上**（§2.1 前提）；
2. **该实体真的发生了对应的事件**——而绝大多数实体事件的**产生者是一个组件**（碰撞触发器/选项卡/商店/文本气泡/命中检测/计时器/…）
   或一个**编辑器资产**（道具/装备/技能/商店模板）；
3. 少数事件有**额外开关/白名单/模式门**（路点开关、返回服务器事件开关、控件白名单、仅超限/仅经典/仅自定义仇恨）。

### 2.4 「引擎怎么**发现**这张图」——官方语料**没有**这一章（精确负）

- 本章检索**官方 201 章全部 `.json`**（`grep`-等价于对每章 `json.dumps` 后搜关键词），
  关键词含 `加载 / 生效 / 激活 / 初始化 / 装载 / 挂载 / 卸载 / 进入关卡 / 动态创建 / 首次 / 节点图不存在`。
  **没有一章**描述"引擎在关卡加载时如何枚举/装配实体上的图"。官方只给**可观测契约**（挂载→事件→执行），
  **不给引擎内部的发现过程**。⇒ 这是**文档层的"未见"**，与 `absence-of-evidence-discipline` 一致：
  **不能断言"引擎没有发现机制"，只能说"这份语料没写它"。**
- **语料最接近运行期发现的一处**在日志章：日志记录里有一项
  "**节点图事件：显示当前生效的节点图以及生效时间点**"（`mhu951iz7wz8` §fact5）。
  ⇒ **运行期确实存在"当前生效的节点图"这一概念并被记录**（含生效时间点），但**语料的措辞到此为止**，
  它**不说明**这个"当前生效"是由谁、在哪一步、以什么键算出来的。
- **日志本身有前置**："日志只在**关卡运行过程中**、并且该图已被『**节点图筛选页签**』筛选之后才会返回"（`mhu951iz7wz8` §fact4）；
  且**必须在发起试玩前**于筛选面板勾选目标图（`mhrnuz9izfne`，客户端节点图日志章）。⇒ **要观测"图跑没跑"，
  得先有一个"跑起来"的关卡**——观察通道本身依赖运行，不是离线可读的。

### 2.5 即便"挂上了 + 事件发生了"，运行期还有几道能把它**静默**掉的条件

| 条件 | 逐字原文 | 出处 | 后果 |
|---|---|---|---|
| **动态实体 / 静态实体** | "动态实体会有 GUID，可以通过节点图进行操作，静态实体无 GUID"；"静态实体，**不可添加组件和节点图，不可被节点图控制**" | `mhnffmieeqbg`（实体摆放）§fact5,fact3 | 挂在一张**静态实体**上的图，**原理上不受节点图控制** |
| **负载优化"本地销毁"** | "上述的『本地销毁』状态**区别于实体的销毁**，可以理解为仅仅是在客户端『不显示』了，**但实体的逻辑依然存在**"；"**依然可以通过节点图节点进行索引，并控制其逻辑**" | `mhlb1vivioys`（负载优化）§fact12,fact13 | 视野外实体被"本地销毁"**但逻辑仍在**——**不会**因此静默掉图；靠玩家靠近会"**在本地会重新被创建**"（§fact14） |
| **创建设置-初始创建** | "关闭初始创建后，实体不会初始创建，可通过节点图动态创建" | `mhnffmieeqbg` §fact21 | 若实体"初始创建"关，则它**不在关卡初始出现**，其**实体创建时**便不会在开局触发 |

**注意方向**：负载优化**不是**"让图停下"的条件（它明说逻辑仍在）；真正会让"事件永不发生"的是**缺组件 / 实体是静态 / 实体根本没被创建**。

---

## 3. 合起来：**我们这张 demo 图**要真跑起来，必须成立什么

### 3.1 今天**已经有的**（结构性 / model 层）

| 要素 | 状态 | 证据 |
|---|---|---|
| 地块实体 `1077936129`（模板 `20001965`，tag `土田`） | **已建成并落盘** | `.runtime/game-executor/scene-cli/20261010-003436-create-…/result.json`（`ENTITY-CREATE-FIELDS.md` §4.1）；`.gil` `field 5` 含它 |
| 图 `MW_API_FARM_DEMO`（`1073741829`，15 节点） | **已建成并通过 `inspect` 读回** | `.runtime/scratch/farm-demo-build.json`；`DEMO-GAP.md` §一 |
| 图**挂**到实体 `1077936129` | **已挂上（编辑器模型读回，`boundEntityIds=[1077936129]`、`boundToLevel:false`）** | `docs/STATE-CARD.md:33`；`AuthoringGraph.cs:253-256` |
| 首节点 `92 进入碰撞触发器时` ×2 | **在**（nodeId 1 / 10） | `DEMO-GAP.md` §一节点清单 |

### 3.2 **每一道必要条件的现状**（把 §2 的三条"必须为真"套到 demo 上）

| # | 必须为真（依据） | 今天成立吗 | 证据 / 缺口 |
|---|---|---|---|
| 1 | 图挂在该实体上（`mhjwjrr5n73i` §fact4；§1.1） | **✔ 成立** | `boundEntityIds=[1077936129]`（`STATE-CARD.md:33`） |
| 2 | 实体是**动态实体**（有 GUID，可被节点图控制）（`mhnffmieeqbg` §fact5） | **? 未证** | 桥的 `create` 只送 `templateId/position/rotation/scale`（`ENTITY-CREATE-FIELDS.md` §1）；**没有任何仓内证据**把地块判成"动态"或"静态"。bind 成功**不等于**动态——bind 是**编辑器模型**操作，不校验动态/静态。**这是一处真正的未证缺口。** |
| 3 | 实体**初始创建**（`mhnffmieeqbg` §fact21） | **大概率 ✔ 未证** | 地块已由 `create` 建出并落盘（`DEMO-GAP.md` §一），故开局应在；但"初始创建"开关的值**未读**。 |
| 4 | **`92` 的那个事件真的会发生**：地块上须有**「碰撞触发器」组件**（`mhn7ko01v3yw` §fact18；章节 `mh8w69rzuc3i`「碰撞触发器」） | **✘ 被证不可能（本工程范围内）** | 本工程**无"加组件"原语**（`AddComponent*` 四处检索全 0，`STATE-CARD.md:47`；`DEMO-GAP.md` §三第 3 行）；且**无证据**地块自带触发器组件（`GRAPH-ATTACH-CHAIN.md` §3.4）；`.gil` 侧 `collisionMapped=false`——**读不出也写不进**。⇒ **首节点永不触发，图永远是一堆死节点。** |
| 5 | 下游 leg（走入摊位→打开商店→售出→货币变化）所需的**类型 8/10/15 模板实例**（`mhn7ko01v3yw` §fact44,f48；`DEMO-GAP.md` §三） | **✘ 被证不可能（现成命令面）** | `TEMPLATE-CREATION-MINE.md`：38 路由无一条建模板。 |
| 6 | 一次**试玩**把图真的放进去跑（观察通道的前提，`mhu951iz7wz8` §fact4） | **✘ 不能自动化** | `EditorAdapter.cs:501` 硬写 `startsPlaytest=false`；工程内无键鼠注入（`DEMO-GAP.md` §三第 6 行）。 |
| 7 | 落盘（绑定随实体存档）（`mhxbd59urbfu` §fact4） | **✔ 成立** | 原生 `save` 后 `.gil` 21872→28383 B，载荷含 entityId×2/graphId×8（`STATE-CARD.md:35`） |

**⇒ demo 的"跑起来"卡在第 4 行这一件上，且它是致命件**（与 `GRAPH-ATTACH-CHAIN.md` §4、`DEMO-GAP.md` §四同判：
`REAL-MACHINE VERIFIED = 0/15`）。**第 2 行是本文件新点出的第二处未证**——即便组件能加上，**"地块是不是动态实体"
也还没读**；它决定"挂在它上面的图是否**原理上**可被节点图控制"。

### 3.3 §3.2 里**可以被后 UAC 读一次就杀掉**的未知

第 2 行（动态/静态）与第 4 行（组件在不在）**都是 model 层的读**：
- 第 4 行可用 `inspect-entity-components`（`BridgeServer.cs:306`）**首次读到**地块的组件表——见 §4。
- 第 2 行需要另一个读出口（实体模型里判动态/静态的字段），**本文件未找到已编译的 op**，属 GAP。

---

## 4. 判决：UAC 之后那批活，能证到 **RUNTIME** 还是只能证到 **model**？

### 4.1 后 UAC 包逐条对照（`docs/gameplan/POST-UAC-PACKET.md`）

| 步 | op / 命令 | 它读/写什么 | 推到哪一层 |
|---|---|---|---|
| §1–§3 | `start-elevated -Status`、`sync-elevated-pointer`、`load` | helper/指针/scope | 基建（与图无关） |
| §4 | `live`（`tools/gameplan/live.py`） | **原生只读**当前关卡 id + 实体**数**（非 id 表） | **数据（model 层）** |
| §5 | **`inspect-entity-components --entity-id`** | **编辑器模型**里该实体的组件表 `{id,enabled,x,y}` | **model 层（E1）**——`sentToGame:false`（`EntityComponentProbe.cs:168-173`） |
| §6 | `component_sweep` | 整关组件只读扫荡 | **model 层（E1）** |
| §7 | `graph inspect` | `nodeCount` / `boundEntityIds`（`AuthoringGraph.cs:253-256`） | **model 层（E1）**——`runtimeVerified:false` |

**⇒ 六步里没有一步让图跑。** `POST-UAC-PACKET.md` 自己也写死了：
"What NONE of this proves — Graph RUNTIME semantics … whether the graph executes in playtest is **UNVERIFIED**
(`runtimeVerified:false`, `AuthoringGraph.cs:257`)"。

### 4.2 那么后 UAC 能**证到什么**（正面，别浪费）

1. **能首次回答一件"决定 demo 生死"的 model 事实**：**地块 `1077936129` 上到底有没有那个『碰撞触发器』组件。**
   `GRAPH-ATTACH-CHAIN.md` §3.4 只能诚实地说"**没有证据**它自带"；`inspect-entity-components` 一旦真机跑通，
   **它就能把这条从"没有证据"升级成"有/没有的确定读回"**——若答"有"，则 §3.2 第 4 行**当场翻转**，demo 的第一道门开了；
   若答"没有"，则把 §3.2 第 4 行的"被证不可能"**从静态推论证成**真机证。**两种结果都可交付。**
   ⚠️ 但见 `ENTITY-CREATE-FIELDS.md` §5.3 的保留：`.gil` 侧 31 个 `(group,kind)` wrapper 与探针侧
   `LudM06iCRNk4iFkwqKIW {id,…}` **是不是同一套组件词汇，未证**（两级命名空间未被任何文档打通）。
2. **能把"绑定在模型里"再焊一次**（§7 的 `boundEntityIds=[1077936129]`）——但 `STATE-CARD.md:33` 已有这份回执，
   **增量信息≈0**。
3. **`live` 的实体数是原生读数**——可用于确认地块仍在**当前**关卡里（id 是"存档的函数"，见 §1.3 边界）。

### 4.3 **但 RUNTIME（E3/E4）一行也证不到**

- **E3（游戏加载器重建运行时模型）**：唯一通道是 `reopen`，**被常量关卡 id 钉死、验收器测试已红**
  （`GRAPH-RUNTIME-EVIDENCE.md` §2d/§ 五；`REOPEN-VERIFICATION-MINE.md`）。后 UAC 包里**没有** reopen 步。
- **E4（执行流被真正遍历）**：只有两条弱通道——
  (a) **图日志**：需**先改 `RunLogSample.cs` 读 proto-58 `graphId`**（`GRAPH-LOG-NEXT-STEP.md` §4）
  **且**要先有一次**试玩**；后 UAC 包里**两者都没有**。
  (b) **人证试玩**：需先**手工配碰撞触发器组件 + 建模板 + 点试玩**（`DEMO-GAP.md` §三），
  而"配组件"正是 §3.2 第 4 行那条**本工程做不到**的步。
- **本文件的一句判决**：
  > **后 UAC 的那批活只能把 model 层（E1）焊死，其中最有价值的一焊是"读一次地块的组件表"——
  > 它能把 demo 的第一道门从"没有证据"变成"确定的有/没有"。但它给不出任何 RUNTIME 证据：
  > 要 RUNTIME，仍必须先有"一次手工试玩"（`GRAPH-RUNTIME-EVIDENCE.md` §2f），而那一步又被"加组件原语缺失"挡着。**
  > ⇒ **"后 UAC 能否证 RUNTIME"的答案是：不能。** 它能做的是**排雷**（组件在不在），不是**点火**（图跑不跑）。

---

## 5. 证据索引

| 论断 | 证据（file:line） |
|---|---|
| `bind` 字段/门/实现 | `tools/editor-bridge/Adapter/AuthoringGraph.cs:107,135,298-318` |
| `bind` 四参造形 + 派发 | `AuthoringGraph.cs:310-314,317`；第二调用点 `EditorAdapter.cs:646-654` |
| 符号映射（命令/工厂/getter） | `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs:401,412,434,503,544,582` |
| **官方挂图原件（实体位四参）** | `.runtime/editor-catalog/resolved/VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:2118`（反编译原件）；元件位 `:2085`；`attachInstructionGraph` `:2094-2095`；宿主方法 `:2035`；类映射 `Generated.cs:477` |
| `State()` = `boundEntityIds`/`boundToLevel` | `AuthoringGraph.cs:251-258`（`:252` 关卡实体常量 `1094713345u`；`:255` boundEntityIds；`:256` boundToLevel） |
| 绑定记录的读出口 | `EditorAdapter.cs:216-220`（`t6ViSxlgnQ3`→`RIXXd08Ah3A` `Generated.cs:591`、`VAfiNjPuW4e`→`i4gXwUOgjxk` `:476`）、`KeyFields` `:176-179` |
| 判绑谓词 = binding.id==graphId | `AuthoringGraph.cs:255-256,262,304` |
| 绑定随资产导出（持久） | 章节 `mhxbd59urbfu`（资产导入导出）§fact4 |
| 挂载是生效前提 / 实体图生命周期 | 章节 `mhjwjrr5n73i`（节点图）§fact4,§fact5,§fact9,§fact24 |
| 事件节点＝唯一起点 / 事件驱动 / 无入引脚 | 章节 `mhk23ora1wom`（基础概念）§fact3,§fact13 |
| 65 事件节点 / 28 类 / 全出参 | 章节 `mhn7ko01v3yw`（事件节点）§fact0,§fact1；逐类 §fact3–§fact53 |
| 碰撞触发器事件只发给持组件实体 | 章节 `mhn7ko01v3yw` §fact18；章节 `mh8w69rzuc3i`（碰撞触发器）与 `mhn95di01j84`（碰撞触发源）（后两章的逐字原文行号见 `GRAPH-ATTACH-CHAIN.md` §2.3/§5） |
| 组件仅编辑时增删 | 章节 `mhei6orvcbkm`（通用组件） |
| 动态/静态实体二分 | 章节 `mhnffmieeqbg`（实体摆放）§fact2,§fact3,§fact5,§fact21 |
| 本地销毁≠销毁 / 逻辑仍在 | 章节 `mhlb1vivioys`（负载优化）§fact12,§fact13,§fact14 |
| 日志只在运行中、筛选后返回；含"当前生效的节点图+生效时间点" | 章节 `mhu951iz7wz8`（节点图日志）§fact4,§fact5；`mhrnuz9izfne`（客户端节点图日志） |
| demo 图/实体/绑定/落盘 现状 | `docs/STATE-CARD.md:31-35`；`docs/gameplan/DEMO-GAP.md` §一/§三/§四；`docs/research/reverse-eng-20261010/ENTITY-CREATE-FIELDS.md` §4.1,§5.3 |
| 加组件原语缺失（四处检索 0） | `docs/STATE-CARD.md:47`；`docs/gameplan/DEMO-GAP.md` §三第 3 行；`COMPONENT-WRITER-MINE.md` |
| 后 UAC 包六步（无一步让图跑） | `docs/gameplan/POST-UAC-PACKET.md` §1–§7、尾节 "What NONE of this proves" |
| E1–E4 分层与各层证据 | `docs/research/reverse-eng-20261010/GRAPH-RUNTIME-EVIDENCE.md` §1,§2,§5 |
| reopen 闸门 / 图日志读者未改 | `GRAPH-RUNTIME-EVIDENCE.md` §2d,§2e；`GRAPH-LOG-NEXT-STEP.md` §4；`REOPEN-VERIFICATION-MINE.md` |
| 绑定记录无组件/无生效条件 | `docs/research/reverse-eng-20261010/GRAPH-ATTACH-CHAIN.md` §1.3,§3,§4 |

---

## 6. `notClaimed`

- 本轮**什么都没跑**：没有起 bridge、没有发原生/图/日志请求、没有开游戏或编辑器、没有读写任何存档、**没有读任何图片**、
  **没有改任何代码或文件（只新增本文件）**。
- **没有**证明引擎**在所有实现路径上**都没有"发现并装载绑定图"的机制；**只**证明**这份 201 章官方语料与本次检索范围内
  （关键词见 §2.4）**没有**描述它。这是"文档层的未见"，**不是"引擎没有"**。
- **没有**读 `LocalLow` 下任何存档，**没有**解码任何 `.gil`；§3 的落盘数字全部**转引自** `docs/STATE-CARD.md` 与姊妹报告。
- **没有**证明地块 `1077936129` **是动态实体或静态实体**（§3.2 第 2 行标 `? 未证`，这是**本轮点出的未证**，不是结论）。
- **没有**证明地块**一定没有**碰撞触发器组件（`GRAPH-ATTACH-CHAIN.md` §3.4 同保留）：本文件只主张"**无证据**它自带 +
  本工程**无原语**加上"，且 `.gil` 侧 `collisionMapped=false` 使这一点**既不能证实也不能否证**；判"确定有/没有"须**真机跑一次**
  `inspect-entity-components`（§4.2），**本文件不做**。
- **没有**主张 `1u` 的语义（§1.2 只推进到"它是实体位/元件位**共用**的挂载常量"，**未命名**）。
- **没有**主张 demo 加上触发器就能"玩"：下游仍缺类型 8/10/15 模板（`DEMO-GAP.md` §四）。
- 「图挂上了」**不等于**「图会跑」；「绑定记录在有」**不等于**「图被引擎装载」；「后 UAC 读到组件表」**不等于**「图被执行」
  ——三层口径（`CLAUDE.md` §一.3）贯穿全文。

---

*本文件由 2026-10-10 会话从仓内桥源码、`.runtime/editor-catalog/resolved/` 反编译语料、官方离线语料
（`docs/official-docs/chapters/*.json`）与姊妹研究报告只读整理（Bash `grep`/`sed`/`python`，**非 Grep 工具**）；
**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档、未读任何图片**。反编译引用的行号为本次 checkout 实测；
官方引用以 `章节 pathId` + `facts[]` 下标给出，可逐条核对。凡「0 命中」均写明检索范围；语义未证处均写「未证 / 不猜」。*
