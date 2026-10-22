> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #4 挖 — 碰撞触发器组件：M1 场景半边唯一的候选

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。
**本文件只读不写**：除新增本文件外，未修改仓内任何文件。

> ⚠️ **2026-10-11 更正（偏移 + 地址）**：文内引用的删组件链判据已被 `docs/research/reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md` 取代——
> 种类字段是 **`[comp+0x34]`**（**不是** `[comp+0x30]`，后者是 byte `enabled`）；组件容器是 **`[entity+0x68]`**（不是 `[entity+0x48]`）。
> 旧 RVA（`0xcb64140` / `0x10abeb40` / `0x102d4750` / `0x10ac50a0` / `0x914ccd0` 等）在当前映像里**已过期**，须按对账文件 §5 重导。

**证据来源（全部只读）**：
- `docs/official-docs/chapters/`（214 章离线语料；本轮逐字读 `mh8w69rzuc3i` / `mhn95di01j84` / `mh3ecor1x5cm` / `mh2pir0hat1s`）
- `docs/research/beyondeditor-frontend/`、`beyondeditor-user-operations/`、`beyondeditor-backend/db/backend.db`
- `.runtime/editor-catalog/`（`annotated/` 12,375 `.cs`、`resolved/`、`string-table.json`、`textmap-chs.json`、`node-catalog-full.json`、`node-names.json`、`command-channels.tsv`）——用 **Bash `grep`**（Grep 工具会静默跳过 `.runtime/`，见记忆 `grep-tool-skips-runtime-dir`）
- `docs/gameplay/COLLISION-COMPONENT-MAPPING.md`、`docs/research/game-b-systems-20261009/M1-interaction.md`
- `tools/editor-bridge/Adapter/*.cs`（`AuthorEntityTag.cs`、`EditorAdapter.cs`、`AuthoringGraph.cs`、`EntityTransform.cs`、`EntityCrudProbe.cs`）

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 本文件结论**几乎全是静态**（读源码/反编译/db）；**没有一条是本轮真机跑出来的**。凡"有实现、没跑过"标 `只离线`；
> 凡"N 命中 0"均写明检索范围。记忆 `absence-of-evidence-discipline`：**"搜不到"≠"不存在"**。

---

## 0. 一句话结论

1. **碰撞触发器是"挂在运行中实体上的通用组件"，不是摆在关卡里的对象。** 官方章 `mh8w69rzuc3i` 逐字：
   组件全称"碰撞触发器组件"，属**通用组件**，配置入口是 `组件编辑页签 → 添加通用组件 → 碰撞触发器 → 详细编辑`。
   因此 M1 场景半边的落点**只能是实体**（见 §1）。
2. **M1 的图半边已经齐了，缺的只有这一个组件。** 节点 `进入碰撞触发器时` 在离线 799 节点目录里
   （`node-catalog-full.json`，节点行 **92**，`.mihoyobin` 哈希 `7128596160922691222`），
   `离开碰撞触发器时`（91）/`激活/关闭碰撞触发器`（90）同在。**图能建；没有组件则事件永不触发。**
3. **最接近的现成原语不是"加组件命令"（不存在），而是"实体组件集合 + 通用派发器 `Ikci0qkvMZX`"。**
   桥今天挂在实体上的 tag / faction / 节点图**三者共用同一个派发器**（`AuthorEntityTag.cs:127`、
   `EntityFactionProbe.cs:152`、`AuthoringGraph.cs:317`）——**派发站点是命令无关的**，
   且 `DeleteComponentForEditObj` 就躺在这张表里（同 service `beyondEditObjService`）。
4. **`Add*Component*` 这个命令名，在本轮检索范围内不存在**（前端 44 操作名 / 后端 38 `command_route` /
   `string-table.json` / 12,375 `.cs` 全命中 0，只有 2 条 `DeleteComponent`）。**这是精确负面，范围见 §2.4。**
5. **tag 与 component 只在"派发形状"上像，在"数据形状"上不像**：tag 是实体上一个扁平 `List<int>` + 一个 bool 开关；
   component 是实体组件集合里的一个**子对象**（`(组件ID:uint, 启用:bool, x:double, y:double)`）。
   ⇒ **同一个 invoke 站点换一个 command/arg 在机械上可行；但"能把 tag 写成 component"这个推论不成立**（§3）。

---

## 1. 官方语料层——碰撞触发器**是什么**、有哪些字段、配在哪

### 1.1 主章：`docs/official-docs/chapters/mh8w69rzuc3i.json`（标题逐字 =「碰撞触发器」）

| 事实 | 逐字原文 | 位置 |
|---|---|---|
| **它是什么** | "碰撞触发器组件，提供关卡运行中碰撞检测的检测范围，是进行接触判定的一种工具。" | `mh8w69rzuc3i.json:22`（`evidence`） |
| **是不是物理碰撞** | "这种碰撞并不会带来物理层的碰撞阻碍。" | `:28` |
| **配在哪** | "(1)在实体/元件编辑界面中，打开组件编辑页签 (2)点击下方的"添加通用组件"，选择并点击"碰撞触发器"，成功添加 (3)点击"详细编辑"，展开编辑页" | `:40` |
| **组件级字段** | "初始生效触发器 枚举实体运行时默认生效的碰撞触发器 / \*触发器列表 枚举实体配置的所有碰撞触发器" | `:46` |
| **单触发器级字段** | "序号:X"，X 为"触发器序号"，作为节点输入项 | `:58` |
| **单触发器开关** | "初始生效 若开启，则该碰撞触发器随实体创建立即生效" | `:64` |
| **生效目标枚举** | "生效目标 仅对配置的实体类型，进行碰撞触发源的检测 提供角色、物件、造物枚举" | `:70` |
| **触发区形状枚举** | "触发区形状 支持长方体、球体、胶囊体，根据选择的不同形状会展开具体的大小配置参数" | `:76` |
| **触发区变换字段** | "中心 相对实体/元件中心的偏移 / 旋转 以中心位置为基准… / 缩放倍率 触发区配置形状在不同轴向上支持定义缩放" | `:82` |
| **范围按钮** | "通过'添加触发区'可新增触发区域，同一碰撞触发器下的范围会取并集范围生效" | `:75` |
| **编辑期可视化** | "关卡编辑窗口中，实体会显示当前选中的碰撞触发器范围" | `:88` |
| **节点名** | "进入碰撞触发器时 …会发送节点图事件给配置"碰撞触发器"的实体 / 离开碰撞触发器时 / 激活/关闭碰撞触发器" | `:94` |

**章号**：`pathId=mh8w69rzuc3i`，层级 `["概念介绍","功能","通用组件"]`，URL 见 `:7`。

### 1.2 配套章「碰撞触发源」= `mhn95di01j84`（**成对**，缺一不可）

| 事实 | 逐字原文 | 位置 |
|---|---|---|
| 方向是单向的 | "关卡运行中，"碰撞触发器"持续监测其他携带"碰撞触发源组件"的实体" | `mhn95di01j84.json:38` |
| 事件发给谁 | "会发送节点图事件给配置"碰撞触发器"的实体"（**触发器侧收事件，源侧不收**） | `:44` |
| **默认值契约** | "造物、角色实体，默认包含碰撞触发源，无需额外编辑" | `:104` |
| **反证契约** | "对于不包含碰撞触发源的实体，他们无法通过接触碰撞触发器，产生进入范围/碰撞范围事件" | `:110` |
| 源侧形状枚举 | "触发区形状 支持长方体、球体、胶囊体" | `:74` |

**⇒ M1 的两侧账**：**源侧**（`碰撞触发源`）在造物/角色上是**出厂自带**，不用写；
**检测侧**（`碰撞触发器`）在本轮语料里**没有任何"默认自带"的声明** ⇒ 它大概率**必须被写上去**，
而"写组件"正是本仓缺的那条通路。这解释了为什么 M1 卡在"组件"。

### 1.3 组件总目：`mh3ecor1x5cm`（角色实体的可用组件概览）

逐字列出 14 个组件名，**碰撞触发器排第一**，且每个名字在 HTML 里链到独立章节：
"碰撞触发器→mh8w69rzuc3i、…、碰撞触发源→mhn95di01j84、…"（`mh3ecor1x5cm.json:38-39`）。
⇒ 与"通用组件"这一层的定位一致：**组件是实体/元件的一等配置面**。

### 1.4 一个**同构但不同**的旁证（别拿它替代碰撞触发器）

`mh2pir0hat1s`（命中检测）逐字："命中检测区域与碰撞触发器的配置类似"（`mh2pir0hat1s.json:122-123`）——
命中检测（`BeyondCompTypeHitDetection`）与碰撞触发器**配置同构但事件不同**，
它给的是"命中某个受击盒"的语义，**不能顶替 M1 的"进入/离开碰撞触发器"**。

---

## 2. 编辑器前端层——"加组件"到底有没有一条命令？

### 2.1 组件在前端**确实是一等公民**（读/删都有代码路径）

| 环节 | 文件:行 | 做了什么 |
|---|---|---|
| 组件类型**封闭枚举 46 项**（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2） | `.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49` | `enum jaUof90C3Ncl5BAJri4x`；**`BeyondCompTypeCollision = 8`（`:12`）**、`HitDetection=12`（`:15`）、`Tag=25`（`:28`）、`PopUp=40`（`:43`） |
| 实体**持有组件集合** | `resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:43,65,204` | `mUwiSNg4POZ`（自定义盒）/ `JdaiSnpkbfl`（`List<>`）/ `WlJiSPfnM3R()`（访问器） |
| 组件**模型形状** | `resolved/taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:12,14,16,18,22,24,27,33` | 4 个字段：uint(组件ID) / bool / double(xPos) / double(yPos)——**无独立 payload** |
| **删组件**命令（前端侧） | `resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107,152` | 见 §2.2 |
| 组件列表 VM 的反应式来源 | `resolved/yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs:109,136` | 订阅 `entity.WlJiSPfnM3R()`（组件集合）建行；读 `b1EiCj8P44N().Value`（组件ID）`:174,289,306` |
| 视口里的组件矩形 | `resolved/kOYGbfKf8rLXL3Yn9ngl.hpN0LEKfMOFul7DFu62g.cs:68` | `vmComponents: dx88KiiT7yWNuX0Y4AQi<uint, …>` |
| 组件编辑 XAML 模板 | `resolved/RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs.cs:408,414,420` | `BeyondComponentProperty.xaml` / `BeyondComponentEditPanel.xaml` / `BeyondComponentEditor.xaml` |

### 2.2 前端**删组件**的 invoke 形状（逐字，`…yn34VuuuO5tEgsICYDBW.cs:107`）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`DeleteComponentForPrefab` 逐字同形（`:152`，`string 137384`），参数换成 `param(Ref(prefab)), param((uint)组件id)`。
⇒ **组件命令确实走"实体 + 组件id"两个参数、走 `beyondEditObjService`**——与 §3 的 tag/faction 同族。

### 2.3 后端**删组件**的落点（`backend.db` → `command_route` id4）

`param_shape = "(int32 实体id, int32 组件id)"`，`handler_summary`：
"`0x12a767b0` 查实体 → `0xcb64140(entity, 组件id)`：`0x10abeb40` 取组件 → `[comp+0x34]==0x15` 时额外
`0x10ac2670` → `0x102d4750(comp,0)` 注销 → `0x10ac50a0(entity,comp)` 收尾"；`notes` = "组件种类常量 `0x15` 的含义 not_found"。
（id5 `DeleteComponentForPrefab` 尾跳 `0x914ccd0`，与 id4 同一实现。）
**⇒ 后端有"删"的完整实现，没有"加"的分支**（§2.4）。

### 2.4 「添加组件」命令：**本轮检索范围内 0 命中**（精确负面 + 范围）

| 集合 | 条数 | 组件相关命令 | 出处 |
|---|---:|---|---|
| 前端操作名（反编译还原） | 44 | `DeleteComponentForEditObj`、`DeleteComponentForPrefab` | `docs/research/beyondeditor-frontend/db/raw/operations.json` |
| 后端 `command_route`（已定位落点） | 38 | id4 `DeleteComponentForEditObj`、id5 `DeleteComponentForPrefab` | `backend.db` → `command_route`（SQL 全表 + `LIKE '%omponent%'`） |
| 后端通道名（13 个） | 13 | **无 component service** | `db/raw/channels.json`（`beyondEditObjService` 等 7 个出站 + 3 个入站） |
| **全字符串表** | `string-table.json`/`table4.json` | 仅 `DeleteComponentForEditObj`、`DeleteComponentForPrefab` + XAML 名（`BeyondComponentEdit*`、`ComponentModel`、`vmComponents`、`componentName`） | `grep -io '[A-Za-z]*omponent[A-Za-z]*'`，**`Add/Create/New` 前缀 0 命中** |
| **UI textmap** | `textmap-chs.json` | 有"组件类型""组件功能""组件数量达到上限"；**无"添加组件"/"添加通用组件"/"添加触发区"/"初始生效触发器"/"*触发器列表"/"触发区形状"** | `grep -o '"[^"]*组件[^"]*"'` 去重逐条已核；`生效目标`/`详细编辑` 存在，其余触发区字段串 0 命中 |
| **反编译语料** | 12,375 `.cs` | `grep -rl "ComponentFor"` → **1 个文件**（就是 §2.2 那个删组件的） | `.runtime/editor-catalog/annotated/` |

**⇒ 严格表述**：「44 条前端操作名 + 38 条后端路由 + 已还原的全字符串表 + 12,375 个反编译类型里，
**没有一条**加组件的命令」。**官方文档说按钮存在（§1.1 `mh8w69rzuc3i:40`），前端有面板与组件集合，
但"按钮→命令"那一跳在明文字符串里断了。**

> **⚠️ 边界（必须一起读）**：反编译语料里**折叠常量**（如 `--1347725427 ^ 0x50557993`）不以明文出现——
> `ApplyPrefabInstanceChange` 就是这么被漏掉的（`docs/research/beyondeditor-user-operations/03-用户操作-场景实体与资源.md:35-38`）。
> 因此上面这条负面**只对"明文字符串可达的命令名"成立**，对"折叠常量命令名"**不成立**。

---

## 3. 现有探针：`AuthorEntityTag.cs` 的 invoke 形状，以及 tag 能不能当组件

### 3.1 **确切的 invoke 形状**（`tools/editor-bridge/Adapter/AuthorEntityTag.cs`）

**常量**（同名符号经绑定档解析，见 `EditorAdapter.cs:15-16,87`）：
- `Producer = B("tbLtNPi0Ktj7XmlZMWvt.CglXsi0ijgrwvs0SPGh")` → `EditorAdapter.cs:15`
- `Param    = B("yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv")` → `EditorAdapter.cs:16`
- 派发器方法名 `B("Ikci0qkvMZX")` → actual `RyJLgKYBqhL`（`EditorBindingProfile.Generated.cs:412`）

**三步 invoke（逐字行号）**：

| 步 | 行 | 代码 |
|---|---|---|
| 建参数列表 | `:117` | `var args=(IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(param))!;` |
| 参数工厂 `Wrap` | `:118` | `object Wrap(string method,object data)=>param.GetMethod(B(method),…).Invoke(null,new[]{data})!;` |
| 填 3 个参数 | `:119` | `args.Add(Wrap("bKliA0tj1p1",entityId)); args.Add(members.IntParam.Invoke(null,new[]{(int)tagId})); args.Add(Wrap("h8diA3iOGmJ",selected));` |
| **派发** | `:127` | `producer.GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!.Invoke(producer, new object?[]{"beyondEditObjService","ModifyEditobjTag",null,args});` |

**⇒ 方法签名 = `Producer.Ikci0qkvMZX(string service, string command, object callback, IList<List<Param>> args)`。**
参数顺序：`[uint(entityId), int(tagId), bool(selected)]`。

**同一个 invoke 站点已经在服务 ≥4 条不同命令**（同一 service `beyondEditObjService`）：

| 能力 | file:line | command | args |
|---|---|---|---|
| 实体标签 | `AuthorEntityTag.cs:127` | `ModifyEditobjTag` | `[uint(entity), int(tagId), bool]` |
| 实体阵营 | `EntityFactionProbe.cs:152` | `ModifyFactionForEditObj` | `[uint(entity), uint(faction)]` |
| 挂节点图（A） | `EditorAdapter.cs:651-654` | `AddInstructionGraphForEditObj` | `[bool, uint(entity), uint(1), uint(graphId)]` |
| 挂节点图（B） | `AuthoringGraph.cs:315-317` | `AddInstructionGraphForEditObj` | `[bool, uint(entity), uint(1), uint(graphId)]` |
| 导出 | `EditorAdapter.cs:937` | `DoExport`（service `beyondExportService`） | `[uint×4, uint, string]` |
| 请求预制 | `EditorAdapter.cs:545` | `RequestPrefabInstance` | `[uint(prefab)]` |

⇒ **派发站点是"命令无关"的**：它只认 `(service, command, callback, args)`。**这是机制事实，已由代码本身证明。**

### 3.2 判断：tag **够近到能复用 invoke 站点**，但**不够近到能当组件的数据形状**

**"够近"的部分（可以照抄的东西）**：

1. 都是**挂在实体上、按 id 寻址的附件**；
2. 都走 `beyondEditObjService` 的 `?EditObj` 命令族；
3. 参数形状都是 `(entityId, id, [bool])`——"谁 + 哪一种 + 开关"；
4. **删组件命令就在这张表里**（§2.2/2.3），且删组件的参数形状 `(实体id, 组件id)` 与 tag 的 `(entityId, tagId)` 同构。

**"断"的部分（不能照搬的地方）**：

| 维度 | tag（`AuthorEntityTag.cs`） | component（`LudM06iCRNk4iFkwqKIW`） |
|---|---|---|
| 载体 | 实体上一个**扁平 `List<int>` 字段**（`TagListField71`→`List<int>`，`AuthorEntityTag.cs:19,51-64`） | 实体**组件集合**里一个**独立对象**（`Uf6GwkiSOYHgqiqgQlC5.…:65,204`） |
| 有无载荷 | **无**——`bool` 只是增/删开关 | **有**——组件携带配置（`LjBE4Q4wWZw6x2ypkNoY` 有 `object BCo4wk5mUni` payload） |
| UI 里的动作 | 增 + 删 | **只有删**（`vmBtnDelete`）；增的处置**未在命令面出现** |
| 命令 | `ModifyEditobjTag`（**一条命令管增删**，bool 开关） | `DeleteComponentForEditObj`，**无 Add** |

### 3.3 **"我怎么知道同站点能不能换参数加组件"** —— 要同时成立两件事

**(甲) 命令必须存在**：需要 `beyondEditObjService` 上有一条"加组件"命令。**本轮 = 未找到**（§2.4）。
**这是无法靠"照抄 tag 写法"绕过的**——桥能发 tag 是因为 `ModifyEditobjTag` 这条命令**真实存在于分发链上**
（`backend.db command_route` 有它、`frontend.db operation` 有它）。
组件缺的**不是 invoke 代码，是那条命令本身**。

**(乙) 参数类型必须能被工厂造出来**：`Param` 有个静态工厂家族（`bKliA0tj1p1`→uint、`qsriAuLLSBe`→uint、
`h8diA3iOGmJ`→bool、`wNLiAK8Wcix`→string，见 `EditorBindingProfile.Generated.cs:503,544,582,609`）。
加组件至少需要 `(entityRef, 组件类型/ID)`——**这两类参数桥都造得出来**（实体引用已用于挂图/删组件；uint 已用于 faction）。
**⇒ 参数构造不是瓶颈；命令名才是瓶颈。**

**判决一句话**：
> **同一个 invoke 站点（`Ikci0qkvMZX`）换一个 command/arg，在机械上完全可行——它已经在服务 4 条不同命令；
> 但"把 tag 的写法照搬到组件上"这个推论不成立，因为组件是"子对象 + 载荷"而非"List 里的一个 int"，
> 且"加组件"的命令名在本轮任何命令集里都不存在。**

**怎么验证判决（判别实验，本文件不运行）**：见 §4 的最小探针——**读回实体组件集合**，
再用**人工一次 UI 点击**（编辑器里"添加通用组件"）看集合是否增长，即可区分：
① 加组件是**纯模型改动**（集合增长、无法令） vs ② 存在**折叠常量的加组件命令**（集合不变、UI 却变了）。

---

## 4. 交付

### 4.1 最接近的现有原语（按可用度排序）

| # | 原语 | 精确符号 / file:line | 能做什么 | 卡在哪 |
|---|---|---|---|---|
| **1** | **实体组件集合的只读访问器** | `WlJiSPfnM3R()`（`resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:204`）+ 组件元素 `LudM06iCRNk4iFkwqKIW`（`…:12-33`） | 读回"实体上有哪些组件（组件ID:uint）" | **符号未采进绑定档**（`EditorBindingProfile.Generated.cs` 无 `WlJiSPfnM3R`/`LudM06iCRNk4iFkwqKIW`）；只读探针需新增 2 个符号 |
| **2** | **通用派发器** | `Producer.Ikci0qkvMZX(service, command, callback, List<Param>)`（`AuthorEntityTag.cs:127`） | 发任意 `beyondEditObjService` 命令 | **没有"加组件"命令名可用**（§2.4） |
| **3** | **编辑期模型 Add** | `WlJiSPfnM3R().X66ijdVvJ0k(<component>)`（`resolved/…AooSwxiSm6Ktx99ovmnr.cs:587`——**反序列化路径正在这么用**） | 把组件对象塞进实体集合 | **四个符号未采**（`WlJiSPfnM3R`/`X66ijdVvJ0k`/`LudM06iCRNk4iFkwqKIW`/`b1EiCj8P44N`）；**模型改了不落盘**（桥 op 永远 `persistentSaveVerified:false`） |
| **4** | **删组件命令**（同族参照，不实现） | `DeleteComponentForEditObj`，`backend.db command_route` id4 + `resolved/…yn34VuuuO5tEgsICYDBW.cs:107` | 证明"组件命令 = (实体id, 组件id)"的 arg 形状 | 只能删，不能加 |
| — | **1017 报文侧的组件读**（协议侧，**不是**实体模型侧） | `Geometry1017Fields.cs:21-22,116-119`；`EditorAdapter.cs:424` | 读**收到的** 1017 里的组件 kind/payload | 历史读数恒 0（cap 截断，`:37-40`）；且**未建立碰撞 kind 映射**（`:160` `collisionKindMappingVerified=false`） |

**⇒ 碰撞触发器在本仓的"落点候选只有一个"：实体组件集合 `entity.WlJiSPfnM3R()`（4.1 #1/#3），
而不是"再挖一个 `.gil` 字段"**——`.gil` 侧已实测"尚无证据将任何号命名为碰撞触发器/源"
（`docs/gameplay/COLLISION-COMPONENT-MAPPING.md:22,60`，`collisionMapped=false`）。

### 4.2 精确符号清单（要新采进绑定档的）

| legacy（待采） | 出处 | 作用 |
|---|---|---|
| `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr::WlJiSPfnM3R` | `resolved/…AooSwxiSm6Ktx99ovmnr.cs:204` | 实体 **→ 组件集合** |
| `rgfCjhijuAbCoKxWU8Lu<>::X66ijdVvJ0k`（集合的 Add） | 同文 `:587`（`WlJiSPfnM3R().X66ijdVvJ0k(component)`） | 集合 **→ 加一个组件** |
| `taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW::b1EiCj8P44N` | `resolved/…LudM06iCRNk4iFkwqKIW.cs:27` | 组件 **→ 组件ID（uint）** |
| （可选）`…::yYJiCpvHnUp` | 同文 `:33` | 组件 **→ 启用（bool）** |

已登记、**无需新采**的：`Ikci0qkvMZX`（`EditorBindingProfile.Generated.cs:412`）、
`Param` 工厂 `bKliA0tj1p1`/`qsriAuLLSBe`/`h8diA3iOGmJ`（`:503,582,544`）。

### 4.3 THE SINGLE SMALLEST PROBE（**只读、一次、零副作用**；只写形状，不实现、不运行）

**目的**：坐实"组件ID 编号空间"（`jaUof90C3Ncl5BAJri4x` 的枚举值 `8` **是否就是**发给游戏的 `componentId`），
并**顺带判别** §3.3 的两条路径——这是任何后续组件写法的**前置输入**。

**做法**：在桥已有的 CRUD 探针目标上，加一条**只读读回实体组件集合**的动作。

- **复用门**：`EntityCrudProbe.cs:14`（`CrudEntityType = "Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr"`——**与组件集合访问器同一个类型**）+ `:102-113` 的 `CheckCrudTarget()`（把目标锁死在本次自建的那一个实体上）。
- **新增符号**：§4.2 的 2 个（`WlJiSPfnM3R` + `b1EiCj8P44N`）。
- **读法**：完全仿 `AuthorEntityTag.EntityTagValues`（`AuthorEntityTag.cs:60-66`）——**只读字段、只走已登记的 BCL 集合、
  不调任何自定义枚举器/属性 getter、带上限（≤1024 行、去重）**；数值一律按 `uint` 原样返回，**不翻译成组件名**。

**请求形状（不运行）**：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**期望读回（形状，不声称数值）**：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**为什么这是最小的那个**：
1. **零副作用**：只读编辑器内存里**它自己建的**那一个实体（`EntityCrudProbe` 的隔离门），不发任何 native/game 报文。
2. **零新机制**：复用 `EntityCrudProbe` 的目标锁 + `AuthorEntityTag` 的"只读 BCL 集合"范式；只补 2 个符号。
3. **一次点击即可升级成判决性探针**（可选第二步，**不属于本探针**）：同一动作跑前跑后各一次，
   中间**人工**在编辑器里点一次「添加通用组件 → 碰撞触发器」：
   - `count` **增长** ⇒ "加组件 = 编辑器模型改动"（§4.1 #3 路），**没有即时命令**；
   - `count` **不变、UI 变了** ⇒ 加组件**不落这个集合**，回头去 §2.4 的折叠常量盲区找命令。

> 记忆 `native-save-persists-everything-unsaved`、`scene-save-writes-the-game-not-the-editor`：
> 即使走到 §4.1 #3，**模型改了也不落盘**——桥 op 永远 `persistentSaveVerified:false`，
> 必须让编辑器/游戏自己保存后才谈得上 `.gil` 变化。**本探针连 `ok:true` 都不声称落盘。**

---

## 5. 证据索引

| 论断 | 证据 |
|---|---|
| 碰撞触发器 = 实体通用组件 / 字段 / 按钮路径 | `docs/official-docs/chapters/mh8w69rzuc3i.json:16,22,40,46,58,64,70,76,82,88,94` |
| 碰撞触发源成对 / 造物·角色默认含源 / 无源则不触发 | `docs/official-docs/chapters/mhn95di01j84.json:38,44,104,110` |
| 组件总目（碰撞触发器排第一） | `docs/official-docs/chapters/mh3ecor1x5cm.json:38-39` |
| 命中检测与触发器同构（旁证，不可替代） | `docs/official-docs/chapters/mh2pir0hat1s.json:122-123` |
| 节点 92 = 进入碰撞触发器时（+ 5 个出参端口） | `.runtime/editor-catalog/node-catalog-full.json`（`name_hash=160146290`）；`.runtime/editor-catalog/node-names.json`（hash `7128596160922691222`）；`docs/research/beyondeditor-frontend/02-界面功能面/01b-节点与配置层清单/04-全部 800 条节点显示名索引.md:58-60` |
| 组件类型枚举 46 项（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2） + `Collision=8` | `.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3,5,12,15,28,43,50` |
| 实体持有组件集合 / Add 在反序列化路径 | `.runtime/editor-catalog/resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:43,65,204,587` |
| 组件模型形状（uint/bool/double/double） | `.runtime/editor-catalog/resolved/taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:12,14,16,18,22,24,27,33` |
| 前端删组件 invoke（含 command 字面量） | `.runtime/editor-catalog/resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107,152` |
| 组件列表 VM 订阅组件集合 | `.runtime/editor-catalog/resolved/yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs:109,136,174,289,306` |
| 组件编辑 XAML 三件套 | `.runtime/editor-catalog/resolved/RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs.cs:408,414,420` |
| **无 AddComponent**（4 集合全表 + 字符串表 + textmap） | `docs/research/beyondeditor-frontend/db/raw/operations.json`；`docs/research/beyondeditor-backend/db/backend.db`→`command_route`；`.runtime/editor-catalog/string-table.json`；`.runtime/editor-catalog/textmap-chs.json`；`.runtime/editor-catalog/annotated/`（`grep -rl "ComponentFor"` → 1 文件） |
| 通道名（无 component service） | `docs/research/beyondeditor-frontend/db/raw/channels.json`（7 出站 + 3 入站） |
| 折叠常量盲区（`ApplyPrefabInstanceChange` 教训） | `docs/research/beyondeditor-user-operations/03-用户操作-场景实体与资源.md:35-38` |
| 后端删组件落点 / 挂图取"第 3 号组件" | `backend.db`→`command_route` id4 / id1（`handler_summary`） |
| 桥派发形状（tag / faction / 挂图） | `tools/editor-bridge/Adapter/AuthorEntityTag.cs:19,117-119,127`；`EntityFactionProbe.cs:152`；`AuthoringGraph.cs:315-317`；`EditorAdapter.cs:15-16,87,545,651-654,937` |
| 派发器 / 参数工厂符号映射 | `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs:412,447,503,544,582,609` |
| CRUD 目标隔离门 | `tools/editor-bridge/Adapter/EntityCrudProbe.cs:14,102-113` |
| `.gil` 侧碰撞号未命名 | `docs/gameplay/COLLISION-COMPONENT-MAPPING.md:22,60`（`collisionMapped=false`） |
| 1017 协议侧组件读（未建立碰撞映射） | `tools/editor-bridge/Adapter/Geometry1017Fields.cs:21-22,37-40,116-119,160`；`EditorAdapter.cs:424` |
| M1 缺口框架（三族交互面 · 组件写入为唯一前置） | `docs/research/game-b-systems-20261009/M1-interaction.md:10,37,58-59,70-72,85,91` |
| entity.transform **写**被挡（同形状的教训） | `tools/editor-bridge/Adapter/EntityTransform.cs:20-28`（`TRANSFORM_NATIVE_SETTER_UNKNOWN`） |

### 与同目录 `COMPONENT-WRITER-MINE.md`（#1）的关系

`COMPONENT-WRITER-MINE.md` 已把"组件写入原语"的**总账**（47 类枚举、实体组件集合、删组件全链路、
三候选路径、一个只读探针）做全。**本文件是它在"碰撞触发器"这一条上的收敛**：
补上该组件**专属**的官方字段清单与章号（§1）、M1 的节点账（§0.2）、以及 §3.3 对"tag 能否当组件"的**判决口径**。
两文件结论一致：**加组件的命令不存在；最近的原语是实体组件集合 + 通用派发器；最小一刀是只读读回组件集合。**

---

*本文件由 2026-10-10 会话从仓内官方语料、研究文档与 `.runtime/editor-catalog/`（Bash `grep`，非 Grep 工具）
只读整理；**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档**。
所有引用行号为本次 checkout / 本次语料实测。凡"有实现没跑过"的条目已标 `只离线`；
凡"N 命中 0"均写明**检索范围**与**折叠常量盲区**。*
