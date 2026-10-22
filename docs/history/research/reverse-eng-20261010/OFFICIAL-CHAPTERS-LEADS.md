> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #9 挖 — 官方 218 章里我们还没用上的能力（能力线索清单）

**产出日期**：2026-10-10。**任务 #9**。
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。**未读任何图片、未读任何 PDF 页**。
**本文件只读不写**：除新增本文件外，未修改仓内任何文件。

**证据来源（全部只读）**：
- `docs/official-docs/chapters/*.json`（**201** 条 graded 章节记录，`kind=official-chapter-finding`）——本轮主证据；
- `docs/official-docs/*.json`（**17** 条顶层单章记录，形状不同：无 `facts[]`/`pageNature`/`usability`，只有 `headline`/`theFinding` 之类）；
- 交叉引用 `docs/research/reverse-eng-20261010/`（28 份同批挖掘报告）+ `docs/research/game-b-systems-20261009/`（六份）+ `docs/MODULE-PLAN-6.md`；
- 能力侧静态复核：`tools/editor-bridge/ManagedBridge/BridgeServer.cs`（case 全表（见 tools/gameplan/tests/test_doctrine.py）、`docs/research/beyondeditor-backend/db/backend.db`→`command_route`（38 行）、`tools/authoring/INTERFACE-INVENTORY.md`。

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> **本文件是第 ① 层（文档写了什么）+ 对第 ② 层的静态复核**；**没有一条是本轮真机跑出来的**。
> 凡"搜不到"的均写明**检索范围**；记忆 `absence-of-evidence-discipline`：**"搜不到"≠"不存在"**。
> 标记约定：**【文档】**＝官方章节原文；**【复核】**＝本次对仓内源码/证据的只读复核；**【本文件口径】**＝本文件自己的**推导框架**
> （不是官方数、也不是既有结论）；**【未验证】**＝无真机证据。

---

## 0. 一句话结论

官方 218 章里，有一个**成建制的能力面**本工程**一条原语都不具备**：它由三类章节族构成——
**通用组件 28 章**（`hierarchy` 含「通用组件」）、**界面控件（资产）27 章**（含「界面控件」）、**资源系统模板 6 章**（含「资源系统」）——
再加关卡/地形两族（`关卡`、`地形编辑`、`关卡设置`、`场景生成模板`、`元件组`、`元件库`、`水物件`、`编辑工具`）。

把这些章节的 FEATURE 按「它们各自缺的那条**原语**」归并，收缩成 **5 个缺失原语**：

| 原语 | 是什么 | 一键解锁的被卡半边数（**【本文件口径】** 见 §1.2） | 有无同批挖矿线索 |
|---|---|---:|---|
| **P1 组件写入**（给实体/元件加通用组件） | 官方有「添加通用组件」按钮（多章 `button-path` 逐字），命令面**无 `Add*Component*`** | **4** | 有：`COMPONENT-WRITER-MINE.md` + `COLLISION-TRIGGER-MINE.md` |
| **P2 模板创建**（建编辑器资产模板：货币/道具/背包/商店） | 系统菜单【货币与背包】【商店模板管理】在建模板，命令面**一条都没有** | **4** | 有：`TEMPLATE-CREATION-MINE.md` + `CONFIG-ID-RESOLUTION-MINE.md` |
| **P3 UI 资产写入**（建/改「界面控件组」） | 27 章界面控件都要一个「编辑器手工创建、运行前存在」的资产，**磁盘格式与保存 API 未知** | **3** | 部分：`UI-CONTROL-WRITE-MINE.md`（有旁路 + 三条挖法） |
| **P4 关卡操作**（建/打开/另存关卡） | `level.manage`＝`research`「尚无完整入口」 | **2** | 弱：`M6a` 提到 `register_level.py`（被 7.1 版本门挡） |
| **P5 地形持久化写回** | 地形能**读**了（`terrain.py`），**没有任何代码写回** | **1** | 有：`M6a-level-terrain.md` §5 |

**Top 5 = 上表 5 行**（每行取一章为 canonical 章节，见 §3）。**M1 场景半边**（靠近交互）唯一的卡点是
**`mh8w69rzuc3i` 碰撞触发器**——它是 **P1 的样板章**，其 9 个字段构成「未来 add-component 原语必须写什么」的
**唯一字段级 spec**（§4 逐条列出）。

---

## 1. 方法与口径

### 1.1 三层（严格分开）

| 层 | 本文件给了什么 | 关键空白 |
|---|---|---|
| **① 文档写了什么** | 201 graded + 17 顶层记录里的 FEATURE、入口路径、字段名、枚举、硬契约 | **不给**任何写盘格式、API、序列化字段号；3329 张配图**一张没读**（`README.md` 第 1 条） |
| **② 工具能做什么（离线）** | 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）、38 条 `command_route`、`INTERFACE-INVENTORY` 的状态列 —— 用来判「有没有能力」 | 只到静态阅读；**命令名折叠常量**是盲区（`COMPONENT-WRITER-MINE.md` §1） |
| **③ 真机验证过什么** | **本文件为零执行**，无 | 全部标 **【未验证】** |

### 1.2 「模块半边」的清单（**【本文件口径】·推导框架**）

`CLAUDE.md` §五/§六 给的是「六模块其中**能用工具真做的**＝节点图这一半 + 按坐标 create」。
本文件把它展开成一个**可数的清单**，用来给章节打分。**这是本文件自己的框架，不是任何文档里的数**：

六模块 M1–M6，每个有两条半边：
- **引擎图半边**：**现在通**（桥能按 `definitionId` 往图里加节点——`PROGRESS-BY-FUNCTION.md` §八，R262 真机）。
- **编辑器资产半边**：需要一条**写入原语**（模板 / 组件 / UI 资产 / 关卡操作），**本项目一条都没有**。

把每条被卡的「编辑器资产半边」编号（共 12 条）：

| # | 半边 id | 是什么 | 卡在 |
|---|---|---|---|
| 1 | `M1-scene` | 靠近交互（实体空间） | 组件：碰撞触发器 |
| 2 | `M1-ui` | 按键交互（界面） | UI 资产：界面控件组 |
| 3 | `M2-tpl` | 货币模板（加钱的 config-id 指向谁） | 模板 |
| 4 | `M3-tpl` | 道具模板 | 模板 |
| 5 | `M4-tpl` | 背包模板 | 模板 |
| 6 | `M4-comp` | 背包组件（把背包挂到实体上） | 组件 |
| 7 | `M5-tpl` | 商店模板 | 模板 |
| 8 | `M5-comp` | 商店组件（把商店挂到实体上） | 组件 |
| 9 | `M6a-lvl` | 建/打开关卡（"一个世界要创建不同的地图"） | 关卡操作 |
| 10 | `M6a-ter` | 地形持久化（地块/高度/水面） | 关卡操作（地形） |
| 11 | `M6b-adj` | 改**已有**实体的变换（布局微调） | 变换写入 |
| 12 | `F5-feed` | 玩家可见反馈（横切，组件支 + UI 支） | 组件 **或** UI 资产 |

### 1.3 打分口径与它的局限（**【本文件口径】**）

- **分数 = 该章所需原语能解锁的「被卡半边」条数**（同一原语下所有章节同分）。**不**是「该章独占几条半边」。
- **局限（诚实声明）**：12 条半边清单纯属本文件的**展开**；换一种展开（例如把 M6 拆成 a/b 而不是 M6a-lvl/M6a-ter），
  分数会变。**分数的用途是给线索排序，不是断言官方有 12 个半边。**
- **判定「没有能力」的依据（【复核】）**：
  - 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）（`tools/editor-bridge/ManagedBridge/BridgeServer.cs`，`grep -c 'case "'`= 现值（见 tools/gameplan/tests/test_doctrine.py）中
    `ui/widget/layout/hud/button/component/property/item/shop/currency/terrain` **全 0 命中**（`M1-interaction.md` §3 逐条核过）；
  - `command_route` **38 行**（`backend.db`）里**没有**任何建模板 / 加组件 / 关卡级命令（`TEMPLATE-CREATION-MINE.md` §1 逐行）；
  - `Adapter/` 里**没有组件写入器**（`ENTITY-PROPERTIES-MINE.md` §2）。
- **不重复计数**：一个章节若同时可归两个原语（如 `mhsd6lrx3voe` ID修改 同时服务 P2 与 P7），只按其**主原语**排一次。

---

## 2. 全量线索清单（按解锁半边数排名）

> 列含义：**原语**＝该章 FEATURE 缺的那条写入口；**解锁**＝该原语的半边集合；**数**＝集合大小。
> 「该原语下的章节」列只给**canonical + 有代表性的**几章（全族计数见括号）。全部 201 章的标题/组归属可由
> `docs/official-docs/chapters/*.json` 逐条复核。

### 第 1 名 —— P1 组件写入（解锁 4：`M1-scene` `M4-comp` `M5-comp` `F5-feed`）

| 章节 id | 标题 | hierarchy | 为什么是「无能力」 | 挖矿线索 |
|---|---|---|---|---|
| **`mh8w69rzuc3i`** | 碰撞触发器 | 概念介绍/功能/通用组件 | 组件只能**读/删**；`Add*Component*` 四处 0 命中 | `COLLISION-TRIGGER-MINE.md`（专属）+ `COMPONENT-WRITER-MINE.md`（总账） |
| `mhn95di01j84` | 碰撞触发源 | 概念介绍/功能/通用组件 | 同上（成对章） | 同上 |
| `mh5y5001vqd4` | 背包组件 | 概念介绍/功能/通用组件 | 「添加组件」按钮存在于文档，命令面没有 | `COMPONENT-WRITER-MINE.md` §2.1 |
| `mho6gviqhsqs` | 商店组件 | 概念介绍/功能/通用组件 | 同上 | 同上 |
| `mh2xoxrop0la` | 单位（「通用组件面板」定义） | 概念介绍 | 「部分类型的实体会默认在通用组件面板挂载一些组件，你可以自由的添加、删除与编辑它们」（`:154`）——**加**那一跳无落点 | 同上 §0 |
| `mh3ecor1x5cm` | 角色（14 项组件总目） | 概念介绍/单位 | 列清单，组件仍挂不上 | 同上 |
| `mh5n160t2b6w` / `mhwtz297kp6a` / `mh0pppib5eyc` | 铭牌 / 文本气泡 / 小地图标识 | 概念介绍/功能/通用组件 | 都是**组件型反馈**，都要 P1 | `UI-CONTROL-WRITE-MINE.md` §5 第 7/8 名 |

**该原语下的全族：`hierarchy` 含「通用组件」的章 = 28 章**（`PYTHONIOENCODING=utf-8 python` 遍历 `docs/official-docs/chapters/*.json` 实测）。
其中**超出六模块的**还有：寻路阻挡 `mh6c3uri84h2`、命中检测 `mh2pir0hat1s`、战利品 `mh63ox06afy8`、扫描标签 `mhfc0lr1tcke`、
单位状态 `mhd7nxrfa8im`、选项卡 `mh5jko05fzyw`、光源 `mhgkan9wgil6`、特效播放 `mh4ppo02m1o8`、
四个运动器（`mhnmcmipncrg`/`mhuts59m9gju`/`mhaqt9rgqv4u`/`mh1ytk9631fm`）、音效播放器 `mhwiv89yra02`、
全局计时器 `mhawd6rl5kpy`、定时器 `mhufb90zbnts`、自定义变量 `mhso1b9wjica`、自定义挂接点 `mhmshmimtegs`、
额外碰撞 `mhuiob9dg1dm`、光标碰撞盒 `mhso200yz3h4`、角色扰动装置 `mhstl890y7xe`、物件镜头 `mhx9b60or59k`。

### 第 2 名 —— P2 模板创建（解锁 4：`M2-tpl` `M3-tpl` `M4-tpl` `M5-tpl`）

| 章节 id | 标题 | hierarchy | 为什么是「无能力」 | 挖矿线索 |
|---|---|---|---|---|
| **`mh2cr30yeak0`** | 货币 | 概念介绍/高级概念/资源系统 | 模板要在【货币与背包】里建；命令面 38 行无建模板 | `TEMPLATE-CREATION-MINE.md` + `CONFIG-ID-RESOLUTION-MINE.md` |
| `mhbgx0rspbqu` | 道具 | 概念介绍/高级概念/资源系统 | 「点击新建道具按钮…即可新建一个道具模板」——无命令 | 同上 |
| `mhi9s7isvp50` | 商店 | 概念介绍/高级概念/资源系统 | 【商店模板管理】是**整块未逆向的前端 UI** | 同上 §1 边界 |
| `mhogfq9bf86q` | 背包 | 概念介绍/高级概念/资源系统 | 背包模板 type 11 磁盘上是**默认自带**的，仍不可写 | 同上 §2.2（`root field 15`） |
| `mhsd6lrx3voe` | ID修改 | 界面介绍 | 给 29 行「配置ID 类型→十进制区间」白名单，**但不给实例登记表、不给写盘格式** | `CONFIG-ID-RESOLUTION-MINE.md`（判决：**不能**回答「配置ID X 是否存在」） |

**该原语的相邻章（同一「资源系统」族）**：掉落物 `mhkfj1iilnck`、装备 `mhkl2yin0cxo`（装备是道具子类型）。
**全族计数：`hierarchy` 含「资源系统」= 6 章。**

### 第 3 名 —— P3 UI 资产写入（解锁 3：`M1-ui` `F5-feed`(UI 支) `M2/M4/M5` 显示子件）

| 章节 id | 标题 | hierarchy | 为什么是「无能力」 | 挖矿线索 |
|---|---|---|---|---|
| **`mhwkfsitckrw`** | 交互按钮界面控件 | 概念介绍/资产/界面控件 | 交互后发的事件在，**控件本身建不了** | `UI-CONTROL-WRITE-MINE.md` §5.1 挖法 1/2/3 |
| `mh2u2e9o3jn6` | 悬浮交互页控件 | 概念介绍/资产/界面控件 | 四条节点接口在，控件资产无写入原语 | 同上 |
| `mhnapxrumtzy` | 界面控件（族总索引） | 概念介绍/资产 | 列全族，无一可写 | 同上 |

**该原语下的全族：`hierarchy` 含「界面控件」= 27 章**（实测）。含 `mhjja1ipq9ck` 道具展示、`mhfkrr0i7gds` 网格视窗、
`mhkwucr8awfq` 特殊数字、`mhesro0hyn5k` 计分板、`mhwpzpixrad0` 进度条、`mhnltrr3g966` 文本框、
`mhnrdor7uyra` 计时器、`mhen7r0djxkg` 弹窗、`mhs1f7ibtc6c` 消息队列、`mh4ve00q4j14` 状态显示区、
`mh2teu0bmfbc` 卡牌选择器、`mh2oih9jou22` 图片、`mh496c08hooo` 图文输入框、`mhucb6reudwm` 模板引用、
`mhv38jig94kk` 文本视窗、`mh3qqq9xc102` 容器节点、`mhdbkf04v6y8` 预设按钮、`mhd4fxr5v6la` 光标检测区域、
`mhls9miyjwjg` 自定义小地图、`mh2iyk9fa4gy` 界面动效、`mhbn4i09l5ns` 全屏界面动效、`mh265urgupye` 按键提示、
`mhkrafr3w6um` 自定义开关、`mhtpwgitsigc` 自定义按钮、`mhlz2lrly3dq` 客户端控件容器。

### 第 4 名 —— P4 关卡操作（解锁 2：`M6a-lvl` + 关卡设置里的 `level.bounds`）

| 章节 id | 标题 | 为什么是「无能力」 | 挖矿线索 |
|---|---|---|---|
| **`mh3pgiraqkiu`** | 关卡（graded 章） | 只讲「新建后自动生成关卡实体」的**后果**，不含新建流程；`level.manage`=`research` | `M6a-level-terrain.md` §1/§3 |
| `mhn9vpia00qc` | 关卡设置（**顶层记录** `LEVEL-SETTINGS-AND-BOUNDS.json`） | 给出字段名「运行后场景生效范围」，**不给形状/数值**；桥无写入口 | 同上 |

### 第 5 名 —— P5 地形持久化写回（解锁 1：`M6a-ter`）

| 章节 id | 标题 | 为什么是「无能力」 | 挖矿线索 |
|---|---|---|---|
| **`mhwe1n94b1x6`** | 地形编辑（**顶层记录** `TERRAIN-EDITING.json`） | 官方一等功能；工具能**读**（`tools/beyond-save/terrain.py`），**无任何持久化写回** | `M6a-level-terrain.md` §5；`CLAUDE.md` §六(b) |

### 第 6 名（并列，解锁 1）—— P6 变换写入（`M6b-adj`）

| 章节 id | 标题 | 为什么是「无能力」 | 挖矿线索 |
|---|---|---|---|
| `mhnffmieeqbg` | 实体摆放 | 建时给坐标可以（`entity.create` 带 `position`），**改已有实体不行** | `CLAUDE.md` §六(c)；`EntityTransform.cs:36,144`（`TRANSFORM_NATIVE_SETTER_UNKNOWN`） |
| `mhmegu0f0cso` | 编辑工具（阵列/对称） | 阵列 = 批量摆放，**依赖改已有实体或在建时批量算**；桥无阵列原语 | 同上 |

### 特殊行 —— 跨原语「入口章」（**【本文件口径】·不参与 Top 5 排名**）

| 章节 id | 标题 | 覆盖的被卡半边 | 说明 |
|---|---|---|---|
| `mhn4bsi5lb58` | 整体界面 | 最多（**6**：`M2-tpl` `M3-tpl` `M4-tpl` `M5-tpl` `M1-ui` `M6a-lvl`） | 逐字列出系统菜单 **29 项管理工具**，含【商店模板管理】【货币与背包】【界面控件组管理】【关卡设置】。**它是入口清单，不是字段级 spec**，所以只列不排。 |

---

## 3. Top 5 详述

> 每行＝一个缺失原语 + 它的 canonical 章节。**引用均为 `docs/official-docs/chapters/<id>.json` 的逐字 `verbatim`/`evidence` 字段**，
> 行号＝本 checkout 实测。**全部为【文档】层；无一条【未验证】以外的能力断言。**

### Top 1 —— P1 组件写入 / 章 `mh8w69rzuc3i` 碰撞触发器（解锁 4）

**引文（逐字）**：
> 「(1)在实体/元件编辑界面中，打开组件编辑页签 (2)点击下方的"添加通用组件"，选择并点击"碰撞触发器"，成功添加 (3)点击"详细编辑"，展开编辑页」
> —— `docs/official-docs/chapters/mh8w69rzuc3i.json:40`（`button-path`）

**需要的原语**：**给实体/元件加一个通用组件 + 写该组件的字段**。
**为什么是「无能力」（【复核】）**：`Add*Component*` 命令名在**四处**检索范围内全 0 命中——
前端 44 条操作名、后端 38 条 `command_route`、`string-table.json`、12,375 个反编译 `.cs`
（`COMPONENT-WRITER-MINE.md` §1 表逐行、`CLAUDE.md` §六(a)）。组件是**读得懂、删得掉、加不了**的不对称边界。
**同批挖矿线索**：**有**。`COLLISION-TRIGGER-MINE.md` §4.1 给出**最接近的现成原语**：
实体组件集合只读访问器 `WlJiSPfnM3R()`（`resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:204`）+
通用派发器 `Ikci0qkvMZX`（`EditorBindingProfile.Generated.cs:412`）；§4.3 给出**最小只读探针**
（`inspect-entity-components`，op 已在 `BridgeServer.cs:306` 注册、已编译进当前 payload DLL，**状态：已编译、未真机**；同族的**删** `delete-entity-component`（`BridgeServer.cs:324`）**亦已编译且接线**，但**当前在 `ComponentIds` 处因符号未绑定而 fail-closed（`COMPONENT_MODEL_READER_UNBOUND`），一次原生请求都发不出**（`tools/editor-bridge/Adapter/EntityComponentDelete.cs:195`）——故两者**并非**同为「已编译、未真机」：**读**＝已编译、接线、未真机；**删**＝已编译、接线、fail-closed、未真机；由 `test_doctrine.py::ComponentOpCompileStatus` 守住）。

### Top 2 —— P2 模板创建 / 章 `mh2cr30yeak0` 货币（解锁 4）

**引文（逐字）**：
> 「配置ID：货币数据的唯一标识」—— `docs/official-docs/chapters/mh2cr30yeak0.json:44`
> 「货币名称：由创作者(奇匠)定义的货币的命名」—— `:38`

**需要的原语**：**在编辑器里创建一个「货币模板」（配置ID type 10）并让它落盘**。
**为什么是「无能力」（【复核】）**：38 条 `command_route` 逐行核过，**无一条**是建模板（`TEMPLATE-CREATION-MINE.md` §1）；
`.gip` 档案里 `货币/道具/商店/背包` 四词 **0 字节命中**（同文 §2.1）。
**同批挖矿线索**：**有，且是本批最接近判别的一次实验**。`TEMPLATE-CREATION-MINE.md` §2.2 发现
**`level .gil` 的 `root field 15` 是一张按「类型化 ID」编号的资产记录表**，磁盘上已有 type 11 `道具背包`（默认背包模板）；
§0.4 给出「非黑即白」的实验：UI 里建 1 个货币模板 → `save` → 扫 field 15 是否出现 type-10 新条目。
**交叉**：`CONFIG-ID-RESOLUTION-MINE.md` §0 判决——**今天没有任何离线产物能回答「配置ID X 是否存在」**，
类型区间表在 `docs/official-docs/chapters/mhsd6lrx3voe.json:64`（10 = 资源货币 = `1115684864~1119879167`）。

### Top 3 —— P3 UI 资产写入 / 章 `mhwkfsitckrw` 交互按钮界面控件（解锁 3）

**引文（逐字）**：
> 「支持玩家进行交互，在选择类型为"交互事件"时，交互后会向节点图发送界面控件组触发时事件」
> —— `docs/official-docs/chapters/mhwkfsitckrw.json:32`

**需要的原语**：**建/改一个「界面控件组」UI 资产（磁盘格式 + 保存 API）**。
**为什么是「无能力」（【复核】）**：桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 ui/控件 **0 命中**；前端 38 条命令里**没有一条**是 UI 控件写
（`UI-CONTROL-WRITE-MINE.md` §0.1/§2.4）。运行期那四个「界面控件组」节点（316/383/384/521）**只能操纵已存在的资产**（同文 §0.2）。
**同批挖矿线索**：**部分**。`UI-CONTROL-WRITE-MINE.md` §5.1 给出三条挖法：①资源类目「界面控件组」的建资源原语
（**首选**，因为同类「客户端脚本」资源的建/改/删已被反射打通，`ClientScriptCrudProbe.cs:114/125/136` 真机）；
②组件写入口（P1）；③未解码的 `beyond*Service`（`beyondEffectService`/`beyondAudioService` 等）。
**旁路（重要）**：§0.3 指出**不需要任何 UI 资产**的玩家可见通道存在——`presentation` 家族 server 节点
（屏幕震动 266 / 模型变色 835 / 模型显隐 308 / 镜头 261-264 / 2D 音效 598），**全部 CANDIDATE、未真机**。

### Top 4 —— P4 关卡操作 / 章 `mh3pgiraqkiu` 关卡（解锁 2）

**引文（逐字）**：
> 「关卡实体在新建一个关卡后会自动创建在场景当中，并且在场景中会用一个特殊图标进行表示」
> —— `docs/official-docs/chapters/mh3pgiraqkiu.json:29`（`verbatim`）

**需要的原语**：**建/打开/另存一个关卡**（`level.manage`）。
**为什么是「无能力」（【复核】）**：`tools/authoring/INTERFACE-INVENTORY.md:19` 记 `level.manage`=`research`「尚无完整入口」；
`scene_cli.py` 的子命令（`inspect/create/creature-create/create-batch/save/reopen-current`）**全部要求 `--level-id`**（在已有关卡内操作）。
**同批挖矿线索**：**弱**。`M6a-level-terrain.md` §3 记：唯一路径是「直接改 `.gil`」——`tools/beyond-save/register_level.py`
曾有「用户确认看到并打开」的实机确认，但**在当前 7.1 上被版本门挡住，且会被游戏进程重写**。
**配套**：`mhn9vpia00qc` 关卡设置（顶层记录 `LEVEL-SETTINGS-AND-BOUNDS.json`）给出 `level.bounds` 的**字段名**
「运行后场景生效范围」，但原文自陈「**NO NUMBERS**」——**形状未知**。

### Top 5 —— P5 地形持久化写回 / 章 `mhwe1n94b1x6` 地形编辑（解锁 1）

**说明**：这一章的 graded 记录**不在** `chapters/*.json` 里（218 覆盖面里它是**顶层单章记录**）——
见 `docs/official-docs/TERRAIN-EDITING.json` → `source.pathId = "mhwe1n94b1x6"`。
**引文（顶层记录，非 `verbatim` 字段）**：
> 「地形编辑 is a COMPLETE, first-class editor feature reached from 顶部页签栏第一个按钮. It is NOT missing - it is simply not exposed as outbound command names」
> —— `docs/official-docs/TERRAIN-EDITING.json` → `forTerrainPcg.whyTheDistinctionMatters`

**需要的原语**：**把内存里的地形字段（`.gil` `root field 7`）持久化写回存档**。
**为什么是「无能力」（【复核】）**：`tools/beyond-save/terrain.py` 的写半（`set_cell:468` / `add_terrain:486` /
`apply_terrain_fields:551` / `to_level_bytes:575`）**只吃内存对象、不吃路径**；全文
`grep -nE "write_bytes|\.write\(|open\("` = **0 命中**（`CLAUDE.md` §六(b)）。**「能读」和「能改」是两件事。**
**同批挖矿线索**：**有**。`M6a-level-terrain.md` §5 + `TAB-DIRECTORY-MINE.md` 已把 `.gil` 的 root field 6/7/11/15/46 解码到可逐字节复核。

---

## 4. 碰撞触发器专项 —— M1 场景半边的唯一卡点，也是未来 add-component 原语必须写的 spec

> **本节是任务 #9 第 3 条的正面回答。** 所有引文来自 `docs/official-docs/chapters/mh8w69rzuc3i.json`（主章）与
> `mhn95di01j84.json`（成对章），行号为本 checkout 实测。**这一族字段是「文档层」的写入规格；本工程对它的读/写能力为零**
> （`docs/gameplay/COLLISION-COMPONENT-MAPPING.md` 记 `collisionMapped=false`；`CLAUDE.md` §六(a)）。

### 4.1 是什么、配在哪

| 事实 | 逐字原文 | 位置 |
|---|---|---|
| 全称/职责 | 「碰撞触发器组件，提供关卡运行中碰撞检测的检测范围，是进行接触判定的一种工具。」 | `mh8w69rzuc3i.json:22` |
| 不是物理碰撞 | 「这种碰撞并不会带来物理层的碰撞阻碍。」 | `:28` |
| 配在哪（三步按钮路径） | 「(1)在实体/元件编辑界面中，打开组件编辑页签 (2)点击下方的"添加通用组件"，选择并点击"碰撞触发器"，成功添加 (3)点击"详细编辑"，展开编辑页」 | `:40` |
| 层级 | `hierarchy = ["概念介绍","功能","通用组件"]` | `:6` |

### 4.2 字段清单（＝未来 add-component 原语要写的 9 个字段，分 3 层）

| 层 | 字段（逐字） | 语义（逐字） | 行号 |
|---|---|---|---|
| **组件级** | `初始生效触发器` | 「枚举实体运行时默认生效的碰撞触发器」 | `:44`（`verbatim`）/`:46` |
| **组件级** | `*触发器列表` | 「枚举实体配置的所有碰撞触发器」（**页面里就带 `*` 前缀**，逐字如此） | `:44`（`verbatim`）/`:46` |
| **单触发器级** | `序号:X`（X=触发器序号） | 「作为节点输入项，可以调整碰撞触发器的参数」——**把节点图里的序号映射回 UI 那行触发器的唯一依据** | `:58` |
| **单触发器级** | `初始生效` | 「若开启，则该碰撞触发器随实体创建立即生效」 | `:64` |
| **单触发器级** | `生效目标` | 「仅对配置的实体类型，进行碰撞触发源的检测」，枚举**角色、物件、造物** | `:70` |
| **触发区级** | `触发区形状` | 「支持长方体、球体、胶囊体，根据选择的不同形状会展开具体的大小配置参数」（**大小参数名本章未列**） | `:76` |
| **触发区级** | `中心` | 「相对实体/元件中心的偏移」 | `:82` |
| **触发区级** | `旋转` | 「以中心位置为基准，在不同轴向上支持调整朝向」 | `:82` |
| **触发区级** | `缩放倍率` | 「触发区配置形状在不同轴向上支持定义缩放」 | `:82` |
| （按钮） | `添加触发区` | 「同一碰撞触发器下的范围会取并集范围生效」 | `:75` |

**编辑期可视化契约（可当写入后的核对手段）**：「关卡编辑窗口中，实体会显示当前选中的碰撞触发器范围」——`:88`。

### 4.3 成对章 `mhn95di01j84` 碰撞触发源——**一侧我们不用写**

| 事实 | 逐字原文 | 位置 |
|---|---|---|
| 方向单向 | 「关卡运行中，"碰撞触发器"持续监测其他携带"碰撞触发源组件"的实体」 | `mhn95di01j84.json:38` |
| **默认值契约** | 「造物、角色实体，默认包含碰撞触发源，无需额外编辑」 | `:104` |
| 反证契约 | 「对于不包含碰撞触发源的实体，他们无法通过接触碰撞触发器，产生进入范围/碰撞范围事件」 | `:110` |
| 组件级硬契约 | 「碰撞触发源组件仅可同时生效一个碰撞触发源」（写入侧**不可假设多区域并列**） | `:30`（`verbatim`） |

**⇒ M1 的两侧账（**【本文件口径】·推导**）**：**源侧**在造物/角色上**出厂自带，不用写**；**检测侧**（碰撞触发器）
在本轮语料里**没有任何「默认自带」声明** ⇒ **必须被写上去**——而「写组件」正是本仓缺的那条通路。

### 4.4 与「命中检测」的边界（不要拿它替代）

`mh2pir0hat1s`（命中检测）逐字：「命中检测区域与碰撞触发器的配置类似」——配置**同构**但事件**不同**，
它给的是「命中某个受击盒」的语义，**不能顶替 M1 的「进入/离开碰撞触发器」**（`COLLISION-TRIGGER-MINE.md` §1.4）。

### 4.5 图半边**已经齐了**（这一条很重要）

三个节点名在离线目录里都在（`COLLISION-TRIGGER-MINE.md` §0.2）：
`进入碰撞触发器时`（`.mihoyobin` 哈希 `7128596160922691222`）/ `离开碰撞触发器时` / `激活/关闭碰撞触发器`
（原文：`mh8w69rzuc3i.json:92`：「进入碰撞触发器时 …会发送节点图事件给配置"碰撞触发器"的实体 / 离开碰撞触发器时 / 激活/关闭碰撞触发器」）。
**⇒ 图能建；没有组件则事件永不触发**（`COLLISION-TRIGGER-MINE.md` §0.2 原话）。这就是为什么 M1 卡在「组件」而不是卡在「节点图」。
**【未验证】**：节点 92/91/90 是否**真的**过得了桥的加节点闸门（`AuthoringGraph.cs` 的 `kind==6` + 类目 + 恰好一个 model）
**本轮没有真机证据**——离线路由只证「目录里有这三个节点名」。

---

## 5. 已覆盖 / 已排除（防止过度概括）

| 章节 | 标题 | 状态 | 依据 |
|---|---|---|---|
| `mhnffmieeqbg` | 实体摆放 | **半边已通** | `entity.create` 建时带 `position/rotation/scale`（`scene_cli.py:258-266`）；「改已有」才卡（§2 第 6 名） |
| `mh2xoxrop0la` | 单位（重建/临时实体） | 半边已通 | 运行期 `创建元件`（252/757/256）在 500 条 server 定义里（`WAVE-SPAWN-PATH.md` §0.3） |
| `mhqmrlr6h58e` | 实体布设组 | **不是 M6b 的答案** | `WAVE-SPAWN-PATH.md` §0.4：布设组是**运行期开关闸门**（时间维度），与「摆出来」正交；且布设组本身无写入原语 |
| `mhso1b9wjica` / `mhubgk9yy8gy` | 自定义变量 / 字典 | **地基（非六模块半边）** | `GRAPH-VARIABLES-VERDICT.md` §0：判决=**未知**（引擎侧有变量方法 `…A8NrPMKmnpQkIiiyYetH.cs:2374/2402/2489`，工具层 0 登记）；`DICT-CONSTRUCT-SEARCH.md` §0：字典构造器在两个 id 命名空间里都**不是 0 个**，但写入原语缺失 |
| `mhs2w008wf14` | 更新日志 | **版本天花板** | 7.1 只存在于 `live-refetch/`，不在快照、不在任何记录 `source` 哈希内（`README.md` 第 4 条） |
| （全部 218 章） | —— | **零执行** | 本文件与语料**都未执行**；「文档写了」≠「游戏里能做」≠「项目已验证读写」 |

**明确排除在 Top 5 之外的两类**（**【本文件口径】·判断**）：
1. **「入口章」**（如 `mhn4bsi5lb58` 整体界面）：覆盖面最大，但**只给入口名、不给字段 spec**，排它会把「菜单里有什么」误当「能力规格」。
2. **纯 AI / 战斗 / 技能 / 剧情章**（`mhuf56rvxhgm` 角色技能节点图、`mhchx59g4u96` 造物状态节点图、`mh4imrrhzdzi` 经典模式角色编号…）：
   它们主要服务**节点图半边**（已通）或玩法选型，**不构成六模块的编辑器资产半边**。

---

## 6. 证据索引

| 论断 | 证据 |
|---|---|
| 「添加通用组件」按钮存在于文档（多章） | `chapters/mh8w69rzuc3i.json:40`；`chapters/mho6gviqhsqs.json:36`；`chapters/mh5y5001vqd4.json:38`；`chapters/mh2xoxrop0la.json:154`（通用组件面板） |
| 碰撞触发器 9 字段 | `chapters/mh8w69rzuc3i.json:44,46,58,64,68,70,75,76,82,86,88,92` |
| 碰撞触发源成对 / 默认自带 / 无源不触发 | `chapters/mhn95di01j84.json:38,102,104,108,110,137` |
| 命中检测同构不可替代 | `chapters/mh2pir0hat1s.json`（`COLLISION-TRIGGER-MINE.md` §1.4 引 `:122-123`） |
| 货币模板字段 | `chapters/mh2cr30yeak0.json:38,44` |
| 道具模板字段 / 新建按钮 | `chapters/mhbgx0rspbqu.json:32`（「点击新建道具按钮，在弹窗内选择确认创建即可新建一个道具模板」） |
| 商店模板入口【商店模板管理】 | `chapters/mhi9s7isvp50.json:16,50,52,56` |
| 背包模板字段 | `chapters/mhogfq9bf86q.json:38`（`field-name` 背包模板名称/背包格数量…） |
| 背包组件三步路径 | `chapters/mh5y5001vqd4.json:20,22,38,40` |
| 商店组件三步路径 | `chapters/mho6gviqhsqs.json:30,32,36,37` |
| 配置ID 类型表（29 行） | `chapters/mhsd6lrx3voe.json:64,65,66` |
| 交互按钮发事件 / 键位枚举 | `chapters/mhwkfsitckrw.json:32,34` |
| 悬浮交互页编辑入口 | `chapters/mh2u2e9o3jn6.json:20` |
| 关卡实体「新建后自动创建」 | `chapters/mh3pgiraqkiu.json:29`（`behaviour-contract`） |
| 系统菜单 29 项管理工具 | `chapters/mhn4bsi5lb58.json:32,34,38,40` |
| `level.bounds` 字段名 | `docs/official-docs/LEVEL-SETTINGS-AND-BOUNDS.json`（`theFinding.fieldName = 运行后场景生效范围`，`NO NUMBERS`） |
| 地形编辑是一等功能 | `docs/official-docs/TERRAIN-EDITING.json`（`forTerrainPcg.whyTheDistinctionMatters`） |
| 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）无 ui/component | `tools/editor-bridge/ManagedBridge/BridgeServer.cs`（`grep -c 'case "'`= 现值（见 tools/gameplan/tests/test_doctrine.py）；`M1-interaction.md` §3 |
| 组件命令只有 2 条且都是删 | `docs/research/beyondeditor-backend/db/backend.db`→`command_route` id4/id5；`docs/research/beyondeditor-frontend/db/frontend.db`→`operation` |
| 无 AddComponent（四处 0 命中） | `COMPONENT-WRITER-MINE.md` §1 表；`CLAUDE.md` §六(a) |
| 38 条命令无建模板 | `TEMPLATE-CREATION-MINE.md` §1 |
| `root field 15` 资产记录表 | `TEMPLATE-CREATION-MINE.md` §2.2 |
| 配置ID 不可判定 | `CONFIG-ID-RESOLUTION-MINE.md` §0 |
| UI 资产磁盘格式未知 | `UI-CONTROL-WRITE-MINE.md` §0.5/§5.1 |
| presentation 旁路（无 UI 资产） | `UI-CONTROL-WRITE-MINE.md` §0.3/§5 |
| 地形写半无写盘 | `tools/beyond-save/terrain.py:468,486,551,575`；`CLAUDE.md` §六(b) |
| 变换写被挡 | `tools/editor-bridge/Adapter/EntityTransform.cs:36,144` |
| 能力状态表 | `tools/authoring/INTERFACE-INVENTORY.md:19,29,42,45,51` |
| 图半边已通（按 definitionId 加节点） | `docs/PROGRESS-BY-FUNCTION.md` §八（R262 真机，688/691） |

---

## 7. 本次未做的（写明范围）

- **未读 3329 张配图**（`README.md` 第 1 条：「3329 张图一张没读」）——**凡只能从图里看出的参数排布，本文件答不了**。
- **未跑任何真机**：`inspect-entity-components`（`BridgeServer.cs:306`）、P2 的 field-15 判别实验、P3 的 E1–E4
  全部**只写形状、未执行**——**本轮零执行**。
- **未重算 README 里的绝对数**：本文件的「201 / 17 / 28 章 / 27 章 / 6 章」是本次 `glob` + `json.load` 实测；
  与 `SWEEP-GAPS.md` 的旧数冲突时**以本次实测为准**（`README.md` 已声明 GUIDE §0/§8 优先）。
- **未穷举全部 218 章**：§2 的族是按 `hierarchy` 字段机械筛的；**用标题/正文关键词的另一次筛会得到别的族**（例如
  「机关/拉杆/按钮」类预制、「寻路」「镜头」「音效」等），本文件只做**已点名六模块 + 其直接前置**这一层。

---

*本文件由 2026-10-10 会话从 `docs/official-docs/`（201 graded + 17 顶层）与 `docs/research/reverse-eng-20261010/` 只读整理；
**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档、未读任何图片/PDF**。
所有引用行号为本次 checkout 实测。凡「有实现没跑过」的条目已标 **【未验证】**；凡「N 命中 0」均写明**检索范围**与**折叠常量盲区**。*
