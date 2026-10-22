> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #2 挖 — 组件"读"这一侧到底解锁什么（`inspect-entity-components` 的价值论证）

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。
证据来源：① 仓内 C# 源码 ② 仓内研究文档 ③ **`.runtime/editor-catalog/resolved/` 里 12375 个反编译 `.cs`**（**Bash `grep`**，Grep 工具会静默跳过 `.runtime/`，见记忆 `grep-tool-skips-runtime-dir`）④ `.runtime/research-sources/official-docs-expanded/` 官方章。
**本文件只读不写**，仅新增本文件本身。

> ⚠️ **2026-10-11 更正（偏移 + 地址）**：文内组件的 kind 偏移已被 `docs/research/reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md` 取代——
> 种类字段是 **`[comp+0x34]`**（**不是** `[comp+0x30]`，后者是 byte `enabled`）；组件容器是 **`[entity+0x68]`**（不是 `[entity+0x48]`）。旧 RVA 须按对账文件 §5 重导。

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 本文件全部结论是**静态**的；**没有一条是本轮真机跑出来的**。凡"搜不到"均写明检索范围（记忆 `absence-of-evidence-discipline`）。

---

## 0. 一句话结论

`inspect-entity-components`（`EntityComponentProbe.cs:124`，桥 `BridgeServer.cs:306`）把一个**此前只能靠字节盲搬的对象**变成
**四个有名字、有类型、按实体寻址的标量**：`{id:uint, enabled:bool, x:double, y:double}`。

它解锁的**不是"能配组件"**（加组件无原语，`CLAUDE.md` §五/§六(a)），而是**"能核实"**：

| 一句话 | 结论 |
|---|---|
| 四个字段是什么 | `id`＝组件类型（**强证据：就是那张 46 项枚举**（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2）），`enabled`＝启用开关；`x`/`y`＝**两个 double，源码名逐字为 `xPos`/`yPos`，语义未证**（是"坐标"还是"标量"未定，见 §1） |
| id 能不能单独识别类型 | **能**——若 `id` 的取值域就是枚举域（强证据、未真机），则 `id=8` ⇒ 碰撞触发器、`id=35` ⇒ 商店、`id=40` ⇒ 悬浮交互页…共 46 个真实类型，名字已全量点名（枚举在仓，§2） |
| 解锁哪个模块半边 | **M1 场景半边 / M4 背包 / M5 商店的"存在性核实"**：能核对"这个实体上到底挂没挂碰撞触发器/背包/商店"，即**核实一次人工在编辑器里点的"添加通用组件"真的发生了**（§3） |
| 限制 | 一次一个实体（`entityId`）；>1024 行**拒绝**不截断；**只读编辑器内存**（永不落盘、无游戏效果）；字段未物化会**整条读失败**（§4） |

**一句口号**：**读是"看得见"，不是"改得动"**。它的价值在于把"组件配置"这一步从**不可观测**变成**可对账**——
人手工在编辑器里点一步，我们用只读探针独立读回，核对 `componentCount` 与 `id` 集合是否增长。

---

## 1. 四个字段对应什么（PROVEN vs GUESSED）

### 1.1 适配器实际返回的形状（以适配器为准）

回执每行是 `{ id:<uint>, enabled:<bool>, x:<double>, y:<double> }`（`EntityComponentProbe.cs:150-156`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


> ⚠️ `COMPONENT-WRITER-MINE.md:400-404` 预测的回执行是 `{componentId, enabled}`（**没有 x/y**）。
> **适配器实际回 `{id, enabled, x, y}`**——以适配器为准。`COMPONENT-OP-PROOF-PLAN.md:68-70` 已记过这处更正。

### 1.2 每个字段的对应关系（三层分标）

| 回执字段 | 编辑器模型侧（actual 7.1 常量 / `EntityComponentProbe.cs`） | 反编译语料侧符号与类型 | 判定 |
|---|---|---|---|
| `id` (uint) | `ComponentIdField71 = "OgoXdqFmidJ"`（`:28`） | `LudM06iCRNk4iFkwqKIW::b1EiCj8P44N()` → boxed **uint**（`taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:12,27-30`） | **PROVEN 是组件类型号**（§2） |
| `enabled` (bool) | `ComponentEnabledField71 = "gKyXdGplIdw"`（`:29`） | `LudM06iCRNk4iFkwqKIW::yYJiCpvHnUp()` → boxed **bool**（同文件 `:18,33-35`） | **PROVEN 是"启用"开关**（UI 用它在行过滤/开关） |
| `x` (double) | `ComponentXField71 = "rNIXd7Mpstc"`（`:30`，legacy `d8LiCZa1gcE`） | `LudM06iCRNk4iFkwqKIW::xPos` → boxed **double**（同文件 `:14,22`） | **名字 PROVEN，语义 GUESSED**（见 §1.3） |
| `y` (double) | `ComponentYField71 = "f3VXda70g6Z"`（`:31`，legacy `so7iCroxZbp`） | `LudM06iCRNk4iFkwqKIW::yPos` → boxed **double**（同文件 `:16,24`） | **名字 PROVEN，语义 GUESSED**（见 §1.3） |

组件模型类的**全部实例字段就是这四个**（`LudM06iCRNk4iFkwqKIW.cs:12-20`，其余为 static 单例），
并且四个字段都在 `BpYYRGcZdkR`（序列化覆写，`:55-60`）里登记，说明它们是**组件被序列化的组成部分**，不是 UI 临时量：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


模型继承链：`LudM06iCRNk4iFkwqKIW : UsJT4KiCnJHM1HfZqK59 : JVhTwtKizlScEvUHNJeZ`
（`nTpNtjiCGOveJhpROkrx.UsJT4KiCnJHM1HfZqK59.cs:9`）。基类额外带一个 `name`（string）字段
（`:11,15`）与一棵**子字段树** `RU3KKBHFSHq`（`Nx9TXsKK52JgF1iQGmtH.JVhTwtKizlScEvUHNJeZ.cs`）——
即组件的**同名配置载荷**（商店模板、背包模板…）挂在**子节点树上**，不在 `x`/`y` 里。**这与"x/y 是配置标量"的假设相冲**。

### 1.3 `x`,`y` 到底是什么——**这是本文件最重要的"未证"**

**PROVEN（可逐条复核）**：
1. 源码里它们的**属性名逐字是 `xPos` / `yPos`**（`LudM06iCRNk4iFkwqKIW.cs:22,24`），**且**这两个字符串也在
   `string-table.json` 里（`"xPos"` / `"yPos"` 各 1 命中）。
2. 它们的**类型是 boxed double**（可空/带存在位），不是 float、不是 int、不是枚举、不是向量对象。
3. 它们**是序列化字段的一部分**（§1.2 的 `:55-60`）。
4. **它们不是"宽/高"**：组件模型上**没有** `width`/`height` 同级字段。对照——凡在语料里表示"矩形范围"的 VM，
   `xPos`/`yPos` 都**成对带着** `width`/`height` 出现（如 `iwWl53Kpgk3hPc9oSMIP`：`xPos/yPos/height/width/text`，
   `bT1IhRKpW4eveioABoAY.iwWl53Kpgk3hPc9oSMIP.cs:41,53,65,77`；`xYgAYUuYCJGEgY0wSEC3.Bounds`：
   `bT1IhRKpW4eveioABoAY` 同族 `QIa0QeuYSOy9i2f73ZCh.xYgAYUuYCJGEgY0wSEC3.cs:104`）。组件缺这一对 ⇒ **不像 extent**。

**未证（必须标 GUESSED）**：
- **`x`/`y` 的语义在恢复语料里读不出来。** 对 12375 个反编译 `.cs` 做穷举检索：
  - legacy 字段名 `d8LiCZa1gcE` / `so7iCroxZbp`：**除组件模型类自身外 0 命中**；
  - 符号注释 `LudM06iCRNk4iFkwqKIW::xPos` / `::yPos`：**0 命中**；
  - 组件编辑器 VM `IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj` 从组件里读的只有
    **一个标识成员**（`:91` 读 `UsJT4KiCnJHM1HfZqK59::kJaiCCpbsCj`）与**子字段树**（`:92` 枚举 `RU3KKBHFSHq`），
    **不读 x/y**；`GetKey()`（`:161-174`）只读 `b1EiCj8P44N`（=id）。
  - 组件列表 VM（`LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs:127,158`）与行 VM（`pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:77-87`）
    只读 **id**（建行标题）与 **enabled**（过滤，`yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs:285`）。
  - 视口 `kOYGbfKf8rLXL3Yn9ngl.hpN0LEKfMOFul7DFu62g.cs` 的组件矩形来自**组件编辑器 VM 的 `GetSelectionRect()`**
    （`:687-703`，由 UI 元素的 `ActualWidth/ActualHeight` 与一个 `Point` 组成），**也不来自组件的 x/y**。
  ⇒ **"读到字节"成立，"命名成坐标/尺寸/某个标量"在本轮检索范围内不成立**（记忆 `model-registry-is-not-visible` 的同一课）。
- **注意**：`xPos`/`yPos` 在**其它** VM 里是通用的 **WPF 2D 画布坐标**习惯（`iwWl53Kpgk3hPc9oSMIP`、`Rh82vNKf3hHygFeKUt28`、
  `xYgAYUuYCJGEgY0wSEC3`、`iW6ho1uxMY0uwoC1CETZ`…），且还有一个 `xPosOrder`/`yPosOrder` 兄弟习惯
  （`iw2fokuDZdTqwEn2FmNH.pC0oG3uDVUn3CT2aq7AI.cs:325,337`）。这**支持**"x/y 是某种 2D 布局坐标"的读法，
  但**不支持**它是任何**组件语义**（触发器形状、拾取范围…）；后者在官方文档里都是"长方体/球体/胶囊体 + 中心/旋转/缩放"的
  **3D** 描述（`mh8w69rzuc3i`「中心 相对实体/元件中心的偏移 / 旋转 / 缩放倍率」）。

**候选排序（全部 GUESSED）**：
1. **编辑期 2D 布局坐标**（画布/marker 位置）——名字习惯 + "有 `xPos`/`yPos` 而无 width/height" 的组合最像一个**点**；
2. **两个组件专有标量**（被起了短名）——不能排除，因为组件专有配置在语料里走的是**子字段树**，而非这两个顶层 double；
3. **范围/尺寸**——**较弱**（组件模型上没有 width/height 同伴，与所有"矩形 VM"的形状相反）。

**能结案的实验（真机，本文件不跑）**：
- 对**同一实体**、**同一组件**在编辑器里把它的可视 marker 拖动一段距离，前后各跑一次探针：若 `x`/`y` 变化 ⇒ 候选 1；
- 或对**两个不同位置、挂同一组件**的实体各跑一次：若 `x`/`y` 随实体位置变化 ⇒ 候选 1（且是场景坐标）；
- 若 `x`/`y` 与任何可视操作无关、只与组件种类绑定 ⇒ 候选 2。

---

## 2. `id` 单独能不能识别组件类型

### 2.1 强证据：`id` 就是那一张前端枚举

组件种类是**封闭枚举 `QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x`，46 项**（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2）（`:3-49`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

（值域 **0..47**，缺 **2** 与 **10**，`47 Arraysize` 是哨兵 ⇒ **46 个真实类型**。）

**"id 就是枚举" 的三条静态证据**：

1. **行标题直接由 id 强转枚举名生成**——组件行 VM 的构造函数：
   `eTxuuH9NkZV(parent, P_1, uint P_2)` 里
   
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

   调用点把组件的 `b1EiCj8P44N().Value`（=id，uint）传进来（`LyiKwiuu…:158`）。
2. **删除命令发的是同一个 uint**——同一 VM 的删除分支把 `(uint)xHRuuubNIqa` 发给
   `DeleteComponentForEditObj`（`yn34…:104-107`）。后端 `command_route` id4 的 `param_shape=(int32 实体id, int32 组件id)`
   （`COMPONENT-WRITER-MINE.md:236-238`）。⇒ **"显示成哪个枚举名"与"发给游戏的组件号"是同一个数**。
3. **线格式的类型位本身就是这张枚举**——组件 proto 消息 `LjBE4Q4wWZw6x2ypkNoY` 第一个字段
   `gAo4weiTQfk` 的类型**就是 `jaUof90C3Ncl5BAJri4x`**（`StN9Qe4wQy9Io9byCM2h.LjBE4Q4wWZw6x2ypkNoY.cs:19,21-24,28,46-56`）。

### 2.2 映射到什么程度

- **枚举本身：100% 点名**（46 个真实值，全部有 `BeyondCompType*` 名字，`QbNEoK0…:3-49`）。
- **对六模块目标的点名**（`COMPONENT-WRITER-MINE.md:94-97` 已列）：
  `Collision=8`（M1 碰撞触发器）、`ClientTrigger=5`（M1 客户端触发器）、`PopUp=40`（M1 悬浮交互页）、
  `StuffBag=33` / `EquipStuffBag=34`（M4 背包）、`Shop=35`（M5 商店）、`CursorCollision=45`、`Tag=25`、`Combat=18`。
- **未映射的三处（别混）**：
  1. **`id` 的取值域 vs 原生序号**：探针自己**拒绝断言** `componentIdSpace:"editor-enum-value-or-native-index-UNVERIFIED"`
     （`EntityComponentProbe.cs:167`）。原生侧"第 3 号组件＝节点图"（`AddInstructionGraphForEditObj` 取组件 3）
     用的是不是同一套号，**未证**（`ENTITY-PROPERTIES-MINE.md:222-224`、`COMPONENT-WRITER-MINE.md:318-320`）。
  2. **`.gil` 侧的 `(group,kind)` 号**：与前端枚举**没有任何已建立的对应**（`entity_geometry.py` 模块头明说未命名任何 kind；
     `ENTITY-PROPERTIES-MINE.md:150-153`）。
  3. **`[comp+0x34]==0x15`** 那个种类常量含义 not_found（`COMPONENT-WRITER-MINE.md:238,321`）。

### 2.3 结论

**只要 id 取值域就是枚举域（强证据、单点未真机），`id` 单独就能命名组件类型**。
但**"真机读到的 id 落在 0..46 且与枚举名对得上"这件事本身还没跑过一次**——
这正是 `inspect-entity-components` 的**第一个可交付产物**：一次实机读回，就把
`componentIdSpace` 从 `UNVERIFIED` 升级为"是/否枚举值"，从而**同时**坐实 §2.2 的三处未映射里的第 1 处。

---

## 3. 具体解锁哪个"被卡住的模块半边"——**核实**，不是**解决**

`CLAUDE.md` §五/§六(a)：**加组件无原语**（前端命令面只有 `DeleteComponentForEditObj`/`DeleteComponentForPrefab`，
`yn34…:107,152`；`AddComponent` 四处检索 0 命中）。因此"配一个碰撞触发器/背包/商店"这条**写路**依旧封死。
但是：**读路一旦通，被卡住的半边就从"完全不可观测"变成"可对账"。**

**三个具体能力（全部是"核实"，不是"实现"）**：

1. **核实一次"人工编辑器步骤"真的发生过**（最有价值）。
   官方文档的配置入口是"组件编辑页签 → **添加通用组件**"（`mh2xoxrop0la.txt:53-55`；
   `mho6gviqhsqs.txt:5-13`「添加通用组件→商店」；`mh5y5001vqd4.txt:5-13`「添加组件→背包」）。
   这正是 `COMPONENT-WRITER-MINE.md:413-416` 的**判决性变体**：同一实体，**人在编辑器里点一次「添加通用组件」**，
   探针**跑前跑后各一次**：
   - `componentCount` 增长且出现 `id=8/35/33/…` ⇒ 该组件**真的进了编辑器模型**（⇒ 加组件 = 模型改动，候选 2）；
   - `componentCount` 不变但 UI 变了 ⇒ 组件不在这个集合里（回折叠常量盲区找命名命令，`COMPONENT-WRITER-MINE.md:§1` 末）。
   **这把"人做的"和"我们做的"接到同一张对账表上**——`CLAUDE.md` §五说"六模块里能真做的只有图这一半 + 按坐标 create"，
   而读探针让**被复制的关卡/被人工补齐的关卡**变得**可验证**：人配，机核。

2. **给"删组件"（写侧唯一存在的组件原语）配一个前置/后置读回**。
   `EntityComponentDelete.cs` 的 `inspect`/`delete` 两动作**都先调 `ComponentIds(model)`**（`COMPONENT-OP-PROOF-PLAN.md:107-114`），
   而"删成功"的**权威判据**是**另发一次 `inspect-entity-components` 看该 id 消失**（同文 §2.2 第 6 条），
   不是同 turn 的非权威回读。⇒ 读探针是删组件**真机取证计划**里不可替代的一环（删本身还差 4 处代码改动 + 重编译）。

3. **坐实任何后续写法的前置输入**。
   任何"加/改组件"的候选 invoke（`COMPONENT-WRITER-MINE.md:329-352` 候选 1/2）都需要先知道
   `componentId` 到底是枚举值还是原生序号。读探针**直接产出**这个输入（§2.3）。

**模块半边对照**：

| 模块 | 被卡的半边 | 读探针能核实的 | 仍不能做的 |
|---|---|---|---|
| **M1 交互** | "碰撞触发器"组件（配在实体上，`mh8w69rzuc3i`） | 该实体上**有没有** `id=8`（及 `5`/`40`），`enabled` 真假，行数 | **加/改**触发器（形状/中心/旋转，无 Add 命令） |
| **M4 背包** | 背包组件（`mh5y5001vqd4`） | 该实体上**有没有** `id=33/34` | 配背包模板引用/初始物品 |
| **M5 商店** | 商店组件（`mho6gviqhsqs`） | 该实体上**有没有** `id=35` | 配商店模板/序号 |
| **M2/M3 货币/道具** | 走节点图这一半（已可做） | 无需组件读 | —— |

> **"可核实"不等于"可玩"**（记忆 `model-registry-is-not-visible` 的三层）：读回只能证明组件**存在于编辑器模型**，
> 回执自身逐字承认 `nativeMutationInvoked:false` / `sentToGame:false` / `persistentSaveVerified:false`
> （`EntityComponentProbe.cs:168-173`）——**不证明游戏运行时吃到了它，更不证明落盘**。

---

## 4. 限制（逐条摆明）

1. **一次一个实体**：请求字段是**闭集** `{id, op, nonce, entityId}`（`EntityComponentProbe.cs:50-59`），
   只接受一个**非零 uint32 `entityId`**；**没有**"全部实体""按名""按模板"的批量入口。
   要读 N 个实体＝N 次调用（每次都要在 scope 租约内、用当次 runId）。
   实现上是先 `ReadCrudEntities()` 在**编辑器 registry** 里按 id 解析出**唯一**实体（`:101-110`），
   0 命中或同名冲突都**具名拒绝**（`COMPONENT_ENTITY_NOT_FOUND` / `COMPONENT_ENTITY_ID_NOT_UNIQUE`）。
2. **上限 1024，且是"拒绝"不是"截断"**：`ComponentCap=1024`（`:36`），超过即抛 `COMPONENT_COLLECTION_CAP_EXCEEDED`
   （`:143-144`）。设计意图逐字："a truncated list must never read back as an authoritative component set"。
3. **只读编辑器内存**：`status:"entity-components-editor-model-read-only"`（`:161`），恒返回
   `nativeMutationInvoked:false` / `localModelWritten:false` / `sentToGame:false` /
   `gameEffectVerified:false` / `persistentSaveVerified:false`（`:168-173`）。**它不落盘、不发原生命令、不碰游戏进程。**
   读到的变更**等关卡重载会被还原**（记忆 `bridge-edits-die-on-context-reset`），但读**本身不产生变更**。
4. **读的是编辑器模型，不是游戏、不是 `.gil`**：与 `Geometry1017Fields`（收到的 1017 报文）、
   `entity_geometry.py`（`.gil` 离线解码）、`game_context_snapshot`（运行时内存）**是四个不同的对象**，
   **不能互相顶替**（`ENTITY-PROPERTIES-MINE.md:16-27`）。
5. **依赖桥与一个存活 scope**：op 已在 `BridgeServer.cs:306` 的 switch 与 `call-bridge.ps1:1` 的 `ValidateSet` 里
   （两者都已含 `inspect-entity-components`）；但**经提权 helper 跑会缺参**——helper 的 `call` 字段闭集是
   `{kind,runId,op,ids}`，**带不了 `entityId`**（`COMPONENT-OP-PROOF-PLAN.md:123-128`），
   而 `call-bridge.ps1` 对这条 op **强制要 `-EntityId`**。两条出路：直接调 `call-bridge.ps1`（路线 A），
   或补 3 处管道（路线 B，同文 §5.1）。**同一修订在一个进程只能注入一次**（`CLAUDE.md` §三）。
6. **字段未物化会整条读失败**：`ComponentValue` 对"handle 存在但 `.Value` 为 null"**具名拒绝**
   （`COMPONENT_FIELD_VALUE_NULL:<field>`，`:116-122`），**绝不返回默认 0/false**（设计正确，`CLAUDE.md` §六 纪律）。
   风险点：若真实组件**普遍不携带 x/y**（二者是可空 double），第一次真机读**可能不是"回 0"而是"整条抛错"**。
   ⇒ **首次真机读必须同时记录这个失败模式**，它直接决定 §1.3 的 x/y 语义是否"多数为空"。
7. **命名深度到此为止**：能读到 `id` 并（单点未验地）命名组件类型；能读到 `x`/`y` 但**命名不了**它们（§1.3）；
   读**不到**组件**载荷**（商店模板引用、背包模板、触发器形状——那些在 `RU3KKBHFSHq` 子字段树里，探针不遍历它）。
8. **状态诚实**：按 `COMPONENT-OP-PROOF-PLAN.md:§0`，这条 op **已编译进当前 payload DLL，但从未真机运行**；
   `CLAUDE.md:77-81` 与 `test_doctrine.py::ComponentOpCompileStatus` 现写作"已编译、未真机"。**同族的删 `delete-entity-component` 亦已于 2026-10-10 晚间接线**（csproj `<Compile>` + `BridgeServer.cs:324` + 白名单/队列字段），现同作"已编译、未真机"（读半仍卡 `COMPONENT_MODEL_READER_UNBOUND`）。**"未真机"对本文件这条读 op 仍成立；本文件的一切解锁论述都建立在"它按源码所示工作"这一假设上。**

---

## 5. 证据索引

| 论断 | 证据（file:line / 路径） |
|---|---|
| 读 op 派发与白名单 | `tools/editor-bridge/ManagedBridge/BridgeServer.cs:306-322`；`tools/editor-bridge/call-bridge.ps1:1`（`ValidateSet` 含该 op，且带 `-EntityId`） |
| 四字段回执行 | `tools/editor-bridge/Adapter/EntityComponentProbe.cs:150-156` |
| 请求闭集 / 单实体 / 非零 uint | 同文件 `:50-59`（`COMPONENT_PROBE_REQUIRED_UINT:entityId`）、`:101-110`（唯一解析） |
| 上限 1024 拒绝不截断 | 同文件 `:36`、`:143-144` |
| 未物化即具名拒绝（不返默认） | 同文件 `:116-122`（`COMPONENT_FIELD_VALUE_NULL`） |
| 只读标记 | 同文件 `:161,167-173` |
| 四个字段的 71 常量/类型 | 同文件 `:24-32,64-96` |
| 46 项组件枚举（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2） | `.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49` |
| 组件模型四字段 + xPos/yPos | `.runtime/editor-catalog/resolved/taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:12-20,22,24,27-35,55-60` |
| 模型继承链 + name 字段 | `.runtime/editor-catalog/resolved/nTpNtjiCGOveJhpROkrx.UsJT4KiCnJHM1HfZqK59.cs:9,11,15` |
| 组件 proto 消息（type=枚举） | `.runtime/editor-catalog/resolved/StN9Qe4wQy9Io9byCM2h.LjBE4Q4wWZw6x2ypkNoY.cs:19,21-24,28,46-56` |
| 实体持组件集合 + Add | `.runtime/editor-catalog/resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:43,65,204-208,587` |
| uint→枚举 行标题 + 删除命令 | `.runtime/editor-catalog/resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:82-85,104-107,152` |
| 列表 VM 只读 id | `.runtime/editor-catalog/resolved/LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs:127,158` |
| 行 VM 只读 id/enabled | `.runtime/editor-catalog/resolved/yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs:174,285,289,306` |
| 组件编辑器 VM 不读 x/y | `.runtime/editor-catalog/resolved/IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:68-159,161-174,687-703` |
| x/y 在别处是 WPF 2D 坐标情态 | `.runtime/editor-catalog/resolved/bT1IhRKpW4eveioABoAY.iwWl53Kpgk3hPc9oSMIP.cs:41,53,65,77`；`QIa0QeuYSOy9i2f73ZCh.xYgAYUuYCJGEgY0wSEC3.cs:78,90,104`；`iw2fokuDZdTqwEn2FmNH.pC0oG3uDVUn3CT2aq7AI.cs:325,337`；`string-table.json`（`"xPos"`/`"yPos"`/`"xPosOrder"`/`"yPosOrder"`） |
| 官方"添加通用组件→商店/背包" | `.runtime/research-sources/official-docs-expanded/mho6gviqhsqs.txt:5-13`；`mh5y5001vqd4.txt:5-13`；`mh2xoxrop0la.txt:53-55` |
| 碰撞触发器是实体通用组件 | `docs/official-docs/chapters/mh8w69rzuc3i.json`（引于 `COLLISION-TRIGGER-MINE.md:§1.1`） |
| 无 Add 组件命令（精确负面） | `COMPONENT-WRITER-MINE.md:§0,§2.3,§5`；`ENTITY-PROPERTIES-MINE.md:230-236` |
| 四个"组件读"通道互不顶替 | `ENTITY-PROPERTIES-MINE.md:16-27,150-163` |
| 删组件计划里的读回判据 | `docs/research/reverse-eng-20261010/COMPONENT-OP-PROOF-PLAN.md:§1.1,§2.1,§2.2` |
| 判决性变体（人点添加，读回计数） | `COMPONENT-WRITER-MINE.md:413-416` |
| op 已编译未真机 | `COMPONENT-OP-PROOF-PLAN.md:§0,§1.3` |

---

*本文件由 2026-10-10 会话从仓内源码、仓内研究文档与 `.runtime/editor-catalog/resolved/`（Bash `grep`，非 Grep 工具）
只读整理；**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档**。
所有引用行号为本次 checkout / 本次 resolved 语料实测。凡"搜不到"均写明检索范围；
凡"名字 PROVEN / 语义 GUESSED"均已分层标注。*
