> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #1 挖 — 给实体加组件的写入原语（M1 场景半边 + `entity.properties` 的总闸）

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。
证据来源只有三处：① 仓内 C# 源码 ② 仓内研究文档 ③ **`.runtime/editor-catalog/resolved/` 里 12375 个反编译 `.cs`**（用 Bash `grep` 查，Grep 工具会静默跳过 `.runtime/`）。
**本文件只读不写**，仅新增本文件本身。

> ⚠️ **2026-10-11 更正（偏移 + 地址）**：本文件的组件模型结论已被 **`docs/research/reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`** 取代——
> 组件容器是 **`[entity+0x68]`**（**不是** `[entity+0x48]`，后者是 `0x10aa6800` 的 map 访问器）；kind 字段是 **`[comp+0x34]`**（**不是** `[comp+0x30]`，后者是 byte `enabled`）。
> 文内所有 RVA（`0x914de40` / `0xcb64140` / `0x10abeb40` / `0x10ac2670` / `0x102d4750` / `0x10ac50a0` / `0x102d4a60` / `0x914ccd0`）在当前映像里**已过期**，须按对账文件 §5 重导，**禁止照抄**。

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 本文件的结论几乎全是 **静态**（读源码/读反编译/读 db）；**没有任何一条是本轮真机跑出来的**。
> 凡"有实现、没跑过"的，一律标 `只离线` 或 `未验证`；**"搜不到"≠"不存在"**，凡搜过的范围都写明。

---

## 0. 一句话结论

- **组件（Component）在这个引擎里是一等公民，而且我们**已经**能读它、删它——但"加"的那条命令，在两个已恢复的命令集里**都不存在**。**
  前端有一个 **46 项的组件类型枚举**（原记 47——**已更正**，数法：`grep -c BeyondCompType` = 46；见 `COLLISION-COMPONENT-ID.md` §1.2）（`BeyondCompTypeCollision=8` / `StuffBag=33` / `Shop=35` …）；
  实体模型有一张**组件集合**；编辑器**删组件**的完整链路（前端 VM → `beyondEditObjService` → 游戏侧
  `0xcb64140` → `[comp+0x34]` → 注销 → 收尾）**两侧都已还原**；官方文档明确写了 UI 上「添加通用组件」这个按钮。
- **`Add*Component*` 这个命令名，在本轮检索范围内不存在**：前端 44 条操作名、后端 38 条 `command_route`、
  BeyondEditor.dll 全字符串表、12375 个反编译类型——**只有 `DeleteComponentForEditObj` / `DeleteComponentForPrefab` 两条组件命令**
  （精确负面，证据见 §5）。**"加组件"在 UI 上存在、在命令面上没有落点**。
  **⚠️ 口径（2026-10-11）**：上面这几个检索面**不是互相独立的层**——同取一份 build 的不同抽取视图
  （被当作独立佐证的「活程序集」亦≡ 7.1 build）；本负面**真正的独立轴只有两代构建（7.0 / 7.1）各自为负**，
  且 7.1 串表检索带**正面控制**（`CLAUDE.md` §五）。「加不加得了」的定论见此，措辞按此放宽。
- **最可能的三条写入路径**（按可信度排序）见 §6：
  1. **`beyondEditObjService` 派发器**（`producer.Ikci0qkvMZX(service,command,null,List<Param>)`）——
     桥**已经在用**它发 tag / faction / 挂图 / 删图；组件命令就在同一张表里（`DeleteComponentForEditObj` 是同族）。
  2. **编辑器模型直改**：`entity.WlJiSPfnM3R()`（组件集合）有一个 `Add` 方法 `X66ijdVvJ0k`，
     反编译里**正在被反序列化路径调用**（`.runtime/.../Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:587`）。
  3. **2001 组件字段消息**：`producer.PHCi086M7o5(2001, payload)`，由组件编辑器 `YWlUeFKpEU3Lh8YnZ6Mj.QS2KpiuBk8S` 发出，
     但**该分支在磁盘程序集里是常量假分支**（`:432` 的 `if (false)`）——已被 PROGRESS 记录过一次，本轮从源码**再次确认**。
- **JSON 一句**：**`AddComponentForEditObj` 是一个"结构上必然存在、但本轮未在任何集合里找到"的命令名；**
  最省的第一刀不是猜命令名，而是 **只读读回实体的组件集合**（§7 的探针），把 `componentId` 的编号坐实，
  再决定往哪条路走。

---

## 1. 方法与本轮检索范围（"搜不到"要能被复核）

| 检索对象 | 位置 | 方法 | 命中组件命令？ |
|---|---|---|---|
| 前端操作名（44 条） | `docs/research/beyondeditor-frontend/db/frontend.db`（表 `operation`） | SQL 全表打印 | **只有 2 条 DeleteComponent** |
| 前端界面文本 | 同库表 `ui_text`；`db/raw/_ui_keys.txt` | `like '%组件%'` | 组件**类型名**多条；**无"添加组件"命令** |
| 后端命令路由（38 条） | `docs/research/beyondeditor-backend/db/backend.db`（表 `command_route`） | SQL 全表 + 全表 LIKE `%omponent%` | **只有 id4/id5 两条 DeleteComponent** |
| 后端消息路由 | 同库表 `message_route` | 全表（只登记 1001–1024） | 2001 不在登记集内 |
| 游戏/编辑器字符串表 | `.runtime/editor-catalog/string-table.json`、`all-recovered-strings.txt` | `grep -io '[A-Za-z]*omponent[A-Za-z]*'` | **只有 2 条 DeleteComponent + 一批 XAML 模板名** |
| 反编译前端（12,375 `.cs`） | `.runtime/editor-catalog/resolved/` | `grep -rI '[A-Za-z]*Component[A-Za-z]*'`、命令字面量抽取 | 同前；`AddComponent` **0 命中** |
| 桥接操作白名单（计数由 `test_doctrine.py` 派生） | `tools/editor-bridge/ManagedBridge/BridgeServer.cs` | `grep -c 'case "'`= 现值（见 tools/gameplan/tests/test_doctrine.py）；`grep -niE 'component\|property\|ui-'` | **0 命中**（只有 JSON `TryGetProperty`） |
| 绑定档符号（307） | `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs` | 逐符号 + `grep -i component\|property\|prop` | **0 命中**（§4） |

> **口径诚实声明**：反编译语料是**反编译器输出**，折叠常量（`--1347725427 ^ 0x50557993` 这类）**不会**以明文字符串出现，
> 所以"逐字符串 grep 命中 0"**不等于**"前端从不发这个命令"——`ApplyPrefabInstanceChange` 就是这么被漏掉的
> （前端就发它，但命令名是折叠常量；见 `entity-menu.json` 的 `_corrections_to_prior_rounds`）。
> 因此 §0 的负面结论**只对"明文字符串可达的命令名"成立**，对"折叠常量命令名"**不成立**。

---

## 2. 编辑器前端：用户"加组件"时 UI 到底做了什么

### 2.1 官方文档层（① 文档写了什么）

官方语料里**组件是实体/元件的一等配置面**，且**有专门的"添加"按钮**：

| 文档 | 章节 | 原文（节选） |
|---|---|---|
| `mh2xoxrop0la`（单位） | 「6.通用组件面板」 | "通用组件是为实体添加功能的**重要方法**，你可以在此对实体**添加、删除与编辑组件**来使运行中的实体具有更多功能。部分类型的实体会**默认在通用组件面板挂载一些组件**，你可以自由的添加、删除与编辑它们" |
| `mho6gviqhsqs`（商店组件） | 「二、商店组件的编辑 1.添加组件」 | "(1)在实体或元件编辑界面中，打开**组件编辑页签** (2)点击下方的「**添加通用组件**」，选择并点击「**商店**」，成功添加 (3)点击「详细编辑」，展开编辑页" |
| `mh5y5001vqd4`（背包组件） | 「二、背包组件的编辑 1.添加组件」 | "(1)…打开组件编辑页签 (2)点击下方的「**添加组件**」，选择并点击「**背包**」，成功添加" |

⇒ **UI 形状确定**：实体/元件编辑页 → **组件编辑页签** → 底部按钮「**添加通用组件 / 添加组件**」→ 从列表里选一个组件种类。
文件位：`.runtime/research-sources/official-docs-expanded/mh2xoxrop0la.txt`、`mho6gviqhsqs.txt`、`mh5y5001vqd4.txt`。

### 2.2 反编译层（② 工具/源码能做什么）——组件类型枚举（**本轮最重要的新发现**）

组件种类是一张**封闭枚举**，就在前端程序集里：

**`.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49`**
（`internal enum jaUof90C3Ncl5BAJri4x`，共 **47** 项）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**这张表把 M1/M4/M5 的目标组件一次点名**：
M1 碰撞触发器 = `BeyondCompTypeCollision(8)` / 客户端触发器 = `ClientTrigger(5)` / 悬浮交互页 = `PopUp(40)`；
M4 背包 = `StuffBag(33)` / `EquipStuffBag(34)`；M5 商店 = `Shop(35)`；
另有 `CursorCollision(45)`（"光标碰撞盒"，UI 文本 `UI_BEYOND_EDITOR_UI_COMPONENT_CONFIG_CURSOR_COLLISION`）。

### 2.3 反编译层——组件在这三处被读/被删/被"编辑"

| 环节 | 文件:行（`.runtime/editor-catalog/resolved/…`） | 做了什么 |
|---|---|---|
| **实体模型持有组件集合** | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:43`（`private rgfCjhijuAbCoKxWU8Lu<LudM06iCRNk4iFkwqKIW> mUwiSNg4POZ`）、`:65`（`public List<LudM06iCRNk4iFkwqKIW> JdaiSnpkbfl`）、`:204`（`public … WlJiSPfnM3R()` 访问器） | **实体有组件集合**（两种视图：一个自定义盒 `rgfCjhijuAbCoKxWU8Lu<>` + 一个公开 `List<>`） |
| **组件模型字段** | `taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:24`（`b1EiCj8P44N()` → `uint`）、`:30`（`yYJiCpvHnUp()` → `bool`）、`:20-22`（`xPos`/`yPos` → `double`） | 一个组件 = **（组件ID:uint, 启用:bool, x/y:double）** |
| **组件行 VM（列表行）** | `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:38`（`vmBtnDelete`）、`:77-87`（`eTxuuH9NkZV(ctx, item, uint)`——把 `uint` 强转成 `jaUof90C3Ncl5BAJri4x` 当行标题）、`:93-107`（`s9puu4bEcx2`：`DeleteComponentForEditObj`）、`:152`（`DeleteComponentForPrefab`） | 每行一个组件，**唯一的动作按钮是"删"**（`vmBtnShow` 是空实现 `:89-91`） |
| **列表 VM（谁生成行）** | `LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs:96-158`、`yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs:121-238` | 二者都：取实体 → 枚举 `…YlJitG20qEt`（=组件集合）→ 过滤 → 用 `b1EiCj8P44N` 建行 |
| **组件编辑器（详细编辑页）** | `IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:24`（`vmHeader`）、`:36`（`vmProperties`）、`:161-174`（`GetKey()` = 组件ID）、`:301-306`（**事件 69 → `QS2KpiuBk8S`**）、`:315`（`QS2KpiuBk8S`）、`:475`（**发 2001**） | 点"详细编辑"展开的**字段编辑器**，提交走**事件 69** |
| **视口里的组件（可拖矩形）** | `kOYGbfKf8rLXL3Yn9ngl.hpN0LEKfMOFul7DFu62g.cs:68`（`vmComponents: dx88KiiT7yWNuX0Y4AQi<uint, YWlUeFKpEU3Lh8YnZ6Mj>`） | 场景视口把每个组件画成一个矩形（有 select/hint rect、拖动回调） |

**删除的完整 invoke 形状**（前端侧，`yn34VuuuO5tEgsICYDBW.cs:107`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


—— 与桥侧 `Ikci0qkvMZX(service,command,callback,args)` 是**同一个派发器、同一个参数形状**（§3）。

### 2.4 前端层结论

- **"读组件""删组件"的代码路径完整**：读来自 `entity.WlJiSPfnM3R()`，删走 `DeleteComponentForEditObj`。
- **"加组件"按钮的处置代码，本轮在恢复语料里没有定位到任何命令名**。
  官方文档说按钮存在（§2.1），前端有组件编辑页签与模板（`Template_ComponentEdit_ComponentPanel` 等，见
  `.runtime/editor-catalog/resolved/RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs.cs:258-282`），
  **但从"按钮"到"命令"的那一跳，在明文字符串里断了**。
- **两种可能，本轮无法区分**：
  ① 加组件是**纯编辑器模型改动**（`entity.WlJiSPfnM3R().X66ijdVvJ0k(row)`），随后由**编辑器自己的保存/同步**带走——
  根本没有"加组件命令"；
  ② 存在一条**折叠常量**的 `AddComponentForEditObj`，正好落在 §1 的盲区里。
  **§7 的探针就是为区分这两者设计的。**

---

## 3. 桥侧"写入原语"的真实形状（tag / faction / 挂图 都是它）

桥今天能"挂"到实体上的东西只有三样：**标签（tag）、阵营（faction）、节点图（graph）**。
三者走的是**同一个派发器**，形状完全一致：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


| 能力 | 实现 file:line | service | command | args（`List<Param>`） |
|---|---|---|---|---|
| 挂节点图 | `tools/editor-bridge/Adapter/EditorAdapter.cs:653-654`（`BindOwnGraph`） | `beyondEditObjService` | `AddInstructionGraphForEditObj` | `[bool, uint(entityId), uint(1), uint(graphId)]`（构造见 `:646-650` 的 `Wrap`） |
| 实体标签 | `tools/editor-bridge/Adapter/AuthorEntityTag.cs:127`（`AuthorEntityTag`） | `beyondEditObjService` | `ModifyEditobjTag`（小写 o 是原样） | `[int(entityId), int(tagId), bool(selected)]`（构造见 `:119`） |
| 实体阵营 | `tools/editor-bridge/Adapter/EntityFactionProbe.cs:152`（`EntityFactionProbe`） | `beyondEditObjService` | `ModifyFactionForEditObj` | `[uint(entityId), uint(factionId)]`（构造见 `:143`） |
| 请求预制实例 | `EditorAdapter.cs:545`、`:594`、`:623` | `beyondEditObjService` | `RequestPrefabInstance` | `[uint(prefabId)]` |
| 导出 | `EditorAdapter.cs:937`（`ExportResource`） | `beyondExportService` | `DoExport` | `[uint×4(类别), uint(id), string(path)]` |
| 调试日志 | `EditorAdapter.cs:514-515` | `beyondExportService` | `ImportAllDebugLog` | `[]`（只带回调） |

**参数工厂**（`Param` 类型 = `EditorBindingProfile.Generated.cs:16` 的 `yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv`，
其静态工厂在绑定档里的映射）：

| legacy | actual（`EditorBindingProfile.Generated.cs`） | 作用 |
|---|---|---|
| `bKliA0tj1p1` | `tZlLbuOouk5`（`:503`） | `uint` → Param |
| `qsriAuLLSBe` | `GIDLbbADocv`（`:582`） | `uint` → Param（另一条） |
| `h8diA3iOGmJ` | `gg1Lbl0yhBM`（`:544`） | `bool` → Param |
| `wNLiAK8Wcix` | `WB6LbgE34u3`（`:609`） | `string` → Param |
| `G9oiCBkSaYQ` | `YwIXdnjaMpN`（`:401`） | 取实体**自己的** uint id（方法，不是工厂） |
| `Ikci0qkvMZX` | `RyJLgKYBqhL`（`:412`） | **派发器**（`Producer` 的实例方法） |
| `PHCi086M7o5` | `l8KLgYI54xQ`（`:447`） | **发指定消息号**（3001 与 2001 都走它） |

**删组件的桥侧形状（本轮新解出的、与 tag/faction 同族）**：把 `command` 换成 `DeleteComponentForEditObj`、
args 换成 `[uint(entityId), uint(componentId)]` 即可——**它和桥已在用的 `ModifyFactionForEditObj` 是同一个 service、
同一个派发器、同一个参数类型**。（本文件**不实现、不运行**它；`§7` 只描述更小的只读探针。）

### 3.1 「标签是类组件挂件」这个类比：到哪为止，在哪断

**成立的部分（可以把 tag 当"迷你组件"学的）**：

1. 都是**挂在实体上的、按 id 寻址的附件**；
2. 都经 `beyondEditObjService` 的 `?EditObj` 命令族写；
3. 参数形状都是 `(entityId, id, [bool])` 这种"谁 + 哪一种 + 开关"；
4. 都有**一张注册表**（tag 的注册表在 `AuthorEntityTag.cs:68-88` 枚举，`key.Category0==10003 && key.Category1==50013`）。

**断裂的部分（不能把 tag 的写法照搬到组件上）**：

| 维度 | 标签 tag | 组件 component | 证据 |
|---|---|---|---|
| **载体** | 实体上**一个扁平 `List<int>` 字段** | 实体上**一个独立对象**（自己的 proto 消息，带类型枚举 + 载荷） | tag：`AuthorEntityTag.cs:19`（`TagListField71`→`List<int>`）/ `:55-57`；component：`StN9Qe4wQy9Io9byCM2h.LjBE4Q4wWZw6x2ypkNoY.cs:15-40`（proto 消息，字段 `gAo4weiTQfk` 就是 `jaUof90C3Ncl5BAJri4x`） |
| **有无载荷** | **无**——`bool` 只是增/删开关 | **有**——组件携带配置（商店引用商店模板、背包引用背包模板） | tag：`AuthorEntityTag.cs:119`（`[id, tagId, bool]`）；component：`mho6gviqhsqs`「商店模板：引用一个全局定义的商店模板」 |
| **原生侧的容器** | 直写 List 字段 | **map 访问器**在 `[entity+0x48]`（**非组件容器**；真容器 = `entity+0x68`，见 `reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`）；删除要**减计数、搬移、清尾、释放** | §6 原生证据 |
| **UI 里的动作** | 增 + 删 | **只有删**（`vmBtnDelete`）；增按钮的处置**未在命令面出现** | `yn34VuuuO5tEgsICYDBW.cs:38`；§2.4 |
| **前端命令** | `ModifyEditobjTag`（增删**同一命令**，bool 开关） | `DeleteComponentForEditObj` / `DeleteComponentForPrefab`，**无 Add** | `COMMAND-ROUTE-MAP.md` id19/id23 vs id4/id5 |

⇒ **结论**：tag 的写法**可以当"派发形状"的模板**（`service + command + List<Param>`），
但**不能当"数据形状"的模板**——组件是**子对象 + 载荷**，不是 List 里的一个 int。
**这解释了为什么"加一个 int"（tag）有命令，"加一个子对象带载荷"（component）在本轮命令面里找不到**：
它更可能走的是"改模型 + 保存"，而不是"一条即时命令"。

---

## 4. 绑定档里的符号：组件 / 属性 **零命中**（精确负面）

**被审计文件**：`tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs`（307 legacy 符号 / 313 合同；
计数口径同 `BINDING-SYMBOL-AUDIT.md:16-22`，本仓实测）。

**方法**：对全档做 `grep -i 'component'`、`grep -i 'property'`、`grep -i 'prop'`、`grep -i 'attr'`，
并逐行看 `LegacySymbols` / `Symbols` / `Contracts` 三段。

**结果**：

- **没有任何一个符号的 legacy 名或 actual 名里含 `component` / `property` / `attr`**。
  唯一出现 "Property" 的地方是 `BindingKind.Property`（一个枚举值，用于**校验 getter 存在**，
  且全档只有 **1 条** Property 合同——`BINDING-SYMBOL-AUDIT.md:52`）。
- 含 "Field" 的行全是 `BindingKind.Field`（类型标签），不是字段名。
- **与"组件/属性写入"沾边的、唯一可用的符号，是参数工厂与派发器本身**：
  `Ikci0qkvMZX`（派发器）、`PHCi086M7o5`（发消息号）、`bKliA0tj1p1`/`qsriAuLLSBe`/`h8diA3iOGmJ`/`wNLiACO…`（Param 工厂）。
  **它们不含"组件"语义，只是"发一条命令"所需的通用零件。**

**⇒ 精确负面**：**绑定档里没有一条现成的"组件/属性访问符号"可以零成本接上**。
要新增一条组件读/写，**必须新采 2–3 个符号**（§7 列了具体是哪几个）。
这与 `BINDING-SYMBOL-AUDIT` §4.1 的结论方向一致：**没有"现成零成本写回"。**

---

## 5. 组件相关命令的**全量清点**：只有"删"，没有"加"

| 集合 | 条数 | 组件相关命令 | 出处 |
|---|---:|---|---|
| 前端操作名（反编译还原） | 44 | `DeleteComponentForEditObj`、`DeleteComponentForPrefab` | `docs/research/beyondeditor-frontend/db/frontend.db` → `operation` |
| 后端 `command_route` | 38 | `DeleteComponentForEditObj`（id4）、`DeleteComponentForPrefab`（id5） | `docs/research/beyondeditor-backend/db/backend.db` → `command_route` |
| 后端 `candidate_name`（字符串表） | — | 仅 `DeleteComponentForPrefab`(1154)、`DeleteComponentForEditObj`(1155) | 同库 `candidate_name`；`bucket='editor_string_table'` |
| 官方 UI 操作表 | 92 | 「删除组件」（op 54，`ui_entry: "组件行 vmBtnDelete"`） | `docs/research/beyondeditor-user-operations/db/userops.db` → `user_operation` |
| 桥接白名单 | 计数见 `test_doctrine.py` | **0** | `tools/editor-bridge/ManagedBridge/BridgeServer.cs`（`grep -c 'case "'`= 现值（见 tools/gameplan/tests/test_doctrine.py） |

**两条命令的语义（后端 db 原文，`command_route.handler_summary`）**：

- **id4 `DeleteComponentForEditObj`** `param_shape=(int32 实体id, int32 组件id)`：
  "`0x12a767b0` 查实体 → `0xcb64140(entity, 组件id)`：`0x10abeb40` 取组件 → `[comp+0x34]==0x15` 时额外 `0x10ac2670`
  → `0x102d4750(comp,0)` 注销 → `0x10ac50a0(entity,comp)` 收尾"。注：**组件种类常量 `0x15` 的含义 not_found**。
- **id5 `DeleteComponentForPrefab`** `param_shape=(int32 prefabId, int32 组件id)`：查 Prefab 表 → **尾跳 `0x914ccd0`**，与 id4 同一实现。

> **边界**：`command_route` 的 38 条是"**已定位落点的命令数**"，**不是全集**——
> 桥自己发的 `DoExportClientScript` 就不在表内（`COMMAND-ROUTE-MAP.md` §3 注1），
> `AddInstructionGraphForPrefab` 来自字符串表还原。**所以"38 里没有 AddComponent"是范围结论，不是全集结论。**

---

## 6. 原生侧：组件列表到底长什么样（游戏进程）

### 6.1 已记录的原生证据（逐条 file:line）

| 事实 | 值 | 出处 |
|---|---|---|
| 实体有**组件容器**，位于 **`[entity+0x68]`**（**旧记 `[entity+0x48]` 已证误**） | `[entity+0x68]` 是**指针列表**（步长 8，元素=组件对象）；`[entity+0x48]` 才是那张**映射**，按编号取组件 | `docs/gameplay/FRONTEND-BACKEND-TRACE-20260920.md:33`（"`0x10aa6800` 的正常分支从对象 `+0x48` 的映射查键1，再从条目数组取对应对象"）+ backend `evidence` E3；更正见 `reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md` |
| **取组件**函数 | `0x10aa6800(entity, id)` | E3；native `rva=0x10aa6800`（size 214，`native_function` 表） |
| **挂图** = 取**第 3 号组件** | `0x12a767b0` 查实体 → `0x10aa6800(entity,3)` → `0x1182d020` 装配 → `0xd9646b0` 通知重算 | `command_route` id1 `handler_summary`；E3 |
| **删组件** = 取组件 → 判 `[comp+0x34]==0x15` → 注销 → 收尾 | `0xcb64140` → `0x10abeb40` → `0x102d4750(comp,0)` → `0x10ac50a0(entity,comp)` | E6；`command_route` id4 |
| **`0x1182cea0` 的走法** | "按 **entry+0x30 编号**查 **component+0x30 列表**，减计数、搬移、清尾和释放，与**节点图移除**吻合，**不是向量写入**"（**旧记号**：`component+0x30` 是编辑器侧 walk 的旧记号，非游戏侧 kind——kind 在 `[comp+0x34]`，`+0x30` 是 byte `enabled`；见 `reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`） | `docs/gameplay/FRONTEND-BACKEND-TRACE-20260920.md:160`；`PROGRESS.md:5701`（gameplan 引用的是 `:5665`，行号已漂移） |
| `0x1182cea0` 的函数体 | native `rva=0x1182cea0`，size **374**（`native_function` 表） | `backend.db` → `native_function` |
| `0x1182d020`（装配节点图） | native `rva=0x1182d020`，size **469** | 同上 |
| **阵营**写 `[entity+0x30]` | `0x914c900` 内联 `mov dword ptr [rdi+0x30], esi`（**写的是实体对象，不是组件**） | E22；`command_route` id20 |

> **`tools/game-executor/native/` 里 `0x1182cea0` / `component+0x30`（**旧记号**，非游戏侧 kind；见 `reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`）零命中**（`Grep` 工具对 `tools/` 全目录 = No matches）。
> 也就是说：**原生探针的 C++ 代码里没有一条"读/写组件列表"的实现**——上面这些偏移**只存在于研究文档的静态分析里**，
> 还没有落成可跑的探针。这本身就是"要怎么挖"的答案：先把 `[entity+0x68]` 容器的**只读**走法定下来。
> （**2026-10-11 更正**：旧文写 `[entity+0x48]`——那是 **map 访问器**，**不是**组件容器；见 `reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`。）

### 6.2 三个 `+0x30`/`+0x34` 是**几件不同的事**（别混，这是踩过的坑）

1. **`[entity+0x30]` = 阵营值**（一个 int32，`mov [rdi+0x30], esi`）——实体级标量。
2. **`[comp+0x34]` = 组件种类**（删组件路径里 `== 0x15` 的那个比较）——组件级类型标签，含义 not_found。
   （**2026-10-11 更正**：旧记 `[comp+0x30]`——`+0x30` 现在是 byte `enabled`，永不 `== 0x15`；见 `reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`。）
3. **参数表元素 stride = `0x30`**（`(参数表,下标,out*) -> bool`，类型标签在 `+0x20`）——**那是命令参数访问器家族**，
   与组件列表**无关**（`PROGRESS.md:4443`）。

> 本轮**没有**读到任何"**插入/新增组件**"的原生函数。已恢复的两张分发表（`0x914de40` / `0x768d170`，均 `complete=1`）
> **能接住的范围内没有 AddComponent**（`COMMAND-ROUTE-MAP.md` §4.4 的口径同样适用）。
> 已知的理论逃生口：全局钩子 `0x768d80e`（置位时整个分发委托给 `0xd4af450`，**绕过哈希表**）——**未读**。

### 6.3 桥上已存在的**组件只读**能力（别忽略）

桥**已经能读组件**，只是没人这么用它：

- `tools/editor-bridge/Adapter/Geometry1017Fields.cs:21-22` 命名了 1017 报文里的
  **`Components` 集合类型**（`AP32clIYuRqdZ7fJTlyS.N0pggoIYfL6RdrGHIETq`）与
  **`Component` 类型**（`ma6nNbIQXIHUxeIZVpiN.mUxYM5IQLwhJJKtEVfj9`）；
  `:116-119` 逐个读组件，取出 **`componentKind`（`HdDIPUkYYjM`）** 与 **`componentPayloadTag`（`iLMIPugmMtk`）**，
  `tag==18` 才算几何组件。
- 观测记录：**1117 报文里的实体组件列表曾读成 `[0,0,0,…,0]`**——不是"没有组件"，是**遍历预算/前缀上限先截断**
  （`Geometry1017Fields.cs:37-40` 的注释原文明说 "the observed geometryComponentCount=0" 是 cap 造成的）。
- 前端侧同一条读数：`docs/research/beyondeditor-frontend/07-能力边界与缺口.md:41-42`（D5/D6）——
  "辅助编辑器回传的 1017 中实体组件列表为空"。

⇒ **一个可用的只读组件通道已经在仓里**（`log-observer-evidence` → `componentGeometry`，`EditorAdapter.cs:424`），
只是它读的是**收到的 1017**、而不是**编辑器自己模型里的组件集合**。

---

## 7. 交付

### (a) 关于"给实体加组件"，**已证**的是什么

**已证（静态、可复核）**：

1. **组件是一等公民、封闭 47 类**：`jaUof90C3Ncl5BAJri4x`（`QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49`）。
   M1/M4/M5 的目标组件全在表里（`Collision=8` / `StuffBag=33` / `Shop=35` / `PopUp=40` / `CursorCollision=45`）。
2. **实体模型持有组件集合**：`entity.WlJiSPfnM3R()`（`Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:204`），
   集合类型带一个 **`Add` 方法 `X66ijdVvJ0k`**（`:587` 反序列化时在用）。
3. **一个组件 =（组件ID:uint, 启用:bool, x/y:double）**（`taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:24/30/20-22`），
   线格式上是**独立 proto 消息**（`StN9Qe4wQy9Io9byCM2h.LjBE4Q4wWZw6x2ypkNoY.cs:15-40`）。
4. **删组件两侧完整**：前端 `DeleteComponentForEditObj(entityId, componentId)`（`yn34VuuuO5tEgsICYDBW.cs:107`）
   ↔ 后端 `0xcb64140` / `[comp+0x34]` / 注销 / 收尾（E6）。
5. **官方 UI 有"添加通用组件"按钮**（`mho6gviqhsqs`/`mh5y5001vqd4`）。
6. **"加组件"的命令名在本轮检索范围内不存在**（§1/§5，范围已写明）。
7. **2001 是"组件字段消息"**，由组件编辑器 `YWlUeFKpEU3Lh8YnZ6Mj.QS2KpiuBk8S`（`:315`）发出（`:475`），
   但该分支在磁盘程序集里是 **`if (false)`**（`:432`）——**死分支**（与 `PROGRESS.md:6141` 的
   `IL_009c ldc.i4.0 / br9…` 记录一致，本轮从源码再确认一次）。

**未证 / 未知（诚实列出）**：

- **组件 ID 编号规则**：`jaUof90C3Ncl5BAJri4x` 的枚举值**是否**就是发给游戏的 `componentId`？
  前端把枚举值直接转 `uint` 当行标题（`yn34VuuuO5tEgsICYDBW.cs:84`），删除时把同一个 `uint` 发出（`:107`）——
  **强证据但非实测**。**原生侧的组件编号（"第 3 号组件"）与这张前端枚举是否同一套编号，未证。**
- `[comp+0x34]==0x15` 的 `0x15` 是什么种类，not_found。
- 明文字符串检索的盲区（折叠常量命令名）——§1 末尾。
- **"加组件到底走命令还是走模型"**——见 §0 的两种可能。

### (b) 最可能的 invoke 站点（附符号名）

按可信度降序，**三个候选**：

**候选 1（首选，复用已证机械）— `beyondEditObjService` 派发器**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- 符号：`Ikci0qkvMZX`→`RyJLgKYBqhL`（`EditorBindingProfile.Generated.cs:412`）、参数工厂 `bKliA0tj1p1`→`tZlLbuOouk5`（`:503`）。
- 依据：删组件就在这张表里（id4），且桥**已在用同一形状**发 tag/faction（`AuthorEntityTag.cs:127`、`EntityFactionProbe.cs:152`）。
- **风险**：命令名未知；盲发违反 `CLAUDE.md`（"不猜"）。⇒ 先做 §7 探针坐实命名空间。

**候选 2（若"加"是模型改动）— 编辑器模型直改**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- 符号：`WlJiSPfnM3R`（实体上的组件集合访问器）、`X66ijdVvJ0k`（集合的 Add）、
  `LudM06iCRNk4iFkwqKIW.b1EiCj8P44N`/`yYJiCpvHnUp`——**四个符号都不在绑定档里，需新采**（§4）。
- 依据：实体反序列化时正是这么把组件塞进集合的（`AooSwxiSm6Ktx99ovmnr.cs:587`）。
- **风险**：模型改了**不落盘**（桥 op 永远 `persistentSaveVerified:false`）；要靠编辑器/游戏自己保存。

**候选 3（组件**字段**，不是加组件）— 2001 消息**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- payload 含组件ID（`LudM06iCRNk4iFkwqKIW.b1EiCj8P44N`）+ 一组字段值（`hlS35JtRO42rGu9MG9Q`）。
- 出处：`IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:475`；消息号语义见 `05-前后端通信通道.md:90`。
- **风险**：**死分支**（`:432` `if(false)`）；且游戏侧 `message_route` **无 2001 的 case**（只登记 1001–1024）。

### (c) THE SINGLE SMALLEST PROBE（**只读**、一次、零副作用）——**不运行，只写形状**

**目的**：区分 §0 的两种可能（"加组件 = 模型改动" vs "存在一条没被明文检索到的加组件命令"），
并**坐实 `componentId` 编号空间的输入**——这是任何后续写法的**前置输入**，而删组件命令已经证明这个输入是 `(entityId, componentId)`。

**探针 = 在桥已有的 CRUD 探针目标上，加一条"只读读回实体组件集合"的动作。**

- **复用**：`EntityCrudProbe` 的自有目标（`tools/editor-bridge/Adapter/EntityCrudProbe.cs:14` 的
  `CrudEntityType = "Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr"`；`:102-113` 的 `CheckCrudTarget()`
  把目标锁死在"本次新建的、`EntityType==1402 && InstanceKind==0`、名字未被外部改过"的那**一个**实体上；
  若要更严，可照 `EntityFactionProbe.cs:106` 再加一条"无图绑定"门）。
- **新增符号（2 个，`EditorBindingProfile.Generated.cs` 里目前没有）**：
  1. `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr::WlJiSPfnM3R`（组件集合访问器，`:204`）
  2. `taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW::b1EiCj8P44N`（组件ID，`:24`）
     —（可选第 3 个：`yYJiCpvHnUp`，`:30`）
- **做法**：完全仿 `AuthorEntityTag.EntityTagValues`（`AuthorEntityTag.cs:60-66`）——
  只读字段、只走已登记的 BCL 集合、**不调任何自定义枚举器/属性 getter**、带上限（≤1024 行、去重）。

**请求形状（不运行）**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**期望读回（形状）**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**为什么这是**最小的**那个**：

- **零副作用**：只读编辑器内存里**它自己建的**那一个实体（`EntityCrudProbe` 的隔离门），不发任何 native/game 报文。
- **零新机制**：复用 `EntityCrudProbe` 的目标锁 + `AuthorEntityTag` 的"只读 BCL 集合"范式；只需补 2 个符号进绑定档。
- **直接产出写法的前置输入**：`componentId` 的值（是枚举值还是原生序号）**必须**先知道，才能构造候选 1/2 的 `args`。
- **一次点击就能升级成"判决性探针"**（可选第二步，不是本探针的一部分）：
  同一动作**跑前跑后各一次**，中间**人工**在编辑器里点一次「添加通用组件 → 商店」：
  - 若 `componentCount` **增长** ⇒ "加组件 = 编辑器模型改动"（候选 2），**没有即时命令**；
  - 若 `componentCount` **不变但 UI 变了** ⇒ 加组件**不在这个集合里**，回头去 §1 的折叠常量盲区挖候选 1。

> **本探针只读、只描述形状，本轮未实现、未运行、未连接任何进程**（`CLAUDE.md` §四：`ok:true` 单独不证明持久化；
> 本探针连 `ok:true` 都不声称落盘）。

---

## 8. 证据索引

| 论断 | 证据 |
|---|---|
| 组件 47 类枚举 | `.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49` |
| 实体持有组件集合 + Add | `.../Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:43,65,204,587` |
| 组件模型字段 | `.../taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:20-22,24,30` |
| 组件行 VM + 删组件 | `.../pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:38,77-87,93-107,152` |
| 组件列表 VM | `.../LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs:96-158`；`.../yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs:121-238` |
| 组件编辑器 + 2001 + 死分支 | `.../IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:24,36,161-174,301-306,315,432,475` |
| 组件 XAML 模板 | `.../RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs.cs:258-282,408-420` |
| 组件 proto 消息 | `.../StN9Qe4wQy9Io9byCM2h.LjBE4Q4wWZw6x2ypkNoY.cs:15-40` |
| 桥派发形状（tag/faction/挂图） | `tools/editor-bridge/Adapter/AuthorEntityTag.cs:119,127`；`EntityFactionProbe.cs:143,152`；`EditorAdapter.cs:646-654` |
| 派发器 + 消息号 + 参数工厂符号 | `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs:412,447,503,544,582,609,401` |
| 桥 CRUD 目标隔离门 | `tools/editor-bridge/Adapter/EntityCrudProbe.cs:14,102-113` |
| 桥已有 1017 组件只读 | `tools/editor-bridge/Adapter/Geometry1017Fields.cs:21-22,37-40,116-119`；`EditorAdapter.cs:424` |
| 删组件两条命令 | `backend.db` → `command_route` id4/id5；`frontend.db` → `operation`；`userops.db` → `user_operation` op54 |
| 原生组件容器 / 取组件 / 删组件链路 | `backend.db` → `evidence` E3/E6；`command_route` id1/id4 `handler_summary` |
| `0x1182cea0` 沿 component+0x30（**旧记号**，非游戏侧 kind；见 `reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`）行走 | `docs/gameplay/FRONTEND-BACKEND-TRACE-20260920.md:160`；`PROGRESS.md:5701`；`docs/gameplan/README.md:106`；`docs/gameplan/DEMO-GAP.md:150` |
| 组件字段消息 2001（前端常量假分支） | `docs/research/beyondeditor-frontend/05-前后端通信通道.md:90`；`docs/research/beyondeditor-frontend/07-能力边界与缺口.md:41-42`；`PROGRESS.md:6137-6145` |
| 几个 `+0x30`/`+0x34` 不是一回事 | `evidence` E22（entity+0x30=阵营）；`command_route` id4（comp+0x34=种类）；`PROGRESS.md:4443`（参数表 stride） |
| 官方 UI「添加通用组件 / 添加组件」 | `.runtime/research-sources/official-docs-expanded/mho6gviqhsqs.txt`、`mh5y5001vqd4.txt`、`mh2xoxrop0la.txt`（「6.通用组件面板」） |
| 桥 op 面零**读写**组件 op | `tools/editor-bridge/ManagedBridge/BridgeServer.cs`：2026-10-10 本会话实测 `grep -niE 'component'` 只命中 `TryGetProperty`（无组件读写 op）。op 计数**不在此固化**——它是**派生物**，由 `tools/gameplan/tests/test_doctrine.py`（`BridgeOpCount`）每次从 `case` 标签重新导出并与 `CLAUDE.md` 对齐（照抄一个 grep 数字进文档会随新增 op 过期）。旁证 `docs/research/game-b-systems-20261009/M1-interaction.md:70` |
| 38 条 ⊂ 全集（命令面边界） | `docs/research/reverse-eng-20261010/COMMAND-ROUTE-MAP.md` §3 注1 / §4.4 |

---

*本文件由 2026-10-10 会话从仓内源码、仓内研究文档与 `.runtime/editor-catalog/resolved/`（Bash `grep`，非 Grep 工具）
只读整理；**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档**。
所有引用行号为本次 checkout / 本次 resolved 语料实测。凡"有实现没跑过"的条目已标 `只离线` / `未验证`，
凡"N 命中 0"的均写明**检索范围**与**折叠常量盲区**。*
