> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #8 预制体默认组件 — 哪些「模板」自带组件（PREFAB-COMPONENT-DEFAULTS）

**产出日期**：2026-10-10。**任务 #8**：推进「组件面板 wiring 在反编译集之外（RqDuurAmdYi / EFou75eU8IC 零调用者）」这条挖点 —— 换问法：**不去加组件，去选一个已经带组件的模板**。
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（遵守记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only`、`level-ids-are-per-save-never-pinned`）。
**未读任何图片、未读任何 PDF 页**。**本文件只读不写**：除新增本文件外，未修改仓内任何文件。

**证据来源（全部只读）**：
- 桥源码 `tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs`（深读路径）、`SceneCatalog.cs`（目录/校准路径）、`ReopenContentEvidence.cs`（`ContentFieldReader`）。
- **真实目录回执**（`.runtime/`，用 Bash 读 —— Grep 工具会静默跳过 `.runtime/`）：
  - `.runtime/editor-bridge/runs/8c515535-66ae-4ef6-8552-fa27432f1a0c/prefab-catalog-response.json`（**2722** 条目录）
  - `.runtime/editor-bridge/runs/8c515535-66ae-4ef6-8552-fa27432f1a0c/prefab-fields-page-response.json`（offset 0→128）
  - `.runtime/editor-bridge/runs/ce2f82fd-cc34-43e1-9e8a-7e9b64cb4035/prefab-fields-page-response.json`（offset 992→1024）
  - `.runtime/editor-bridge/runs/c980a8f9-f8de-462b-8b30-1f46a2a00c77/prefab-fields-page-response.json`（offset 1664→1698，`done=true`）
  - `.runtime/asset-inventory/prefabs-all.tsv`（2722 行目录快照）
- 组件类型枚举 `.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-51`（46 成员）。
- **官方语料** `docs/official-docs/chapters/*.json`（201 条 graded 章节），原始文本 `.runtime/research-sources/official-docs-sweep-20260929/sources/*.txt`。
- 同批前作：`PREFAB-COMPONENT-PATH.md`、`PREFAB-FIELDS-MINE.md`、`COLLISION-COMPONENT-ID.md`、`OFFICIAL-CHAPTERS-LEADS.md`。

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> **【文档】**＝官方章节原文；**【实读】**＝本次对 `.runtime/` 真实回执的只读解析；**【静态】**＝本次对桥源码的只读复核；
> **【未验证】**＝无真机证据（本轮零执行）。记忆 `absence-of-evidence-discipline`：**"搜不到"≠"不存在"**，凡否定均写明检索范围。

---

## 0. 一句话结论

**「选模板」能免费拿到组件，但只拿到「基线 6 件套」，拿不到我们 M1/M4/M5 要的那几件。**

- **实读** 194 个预制体记录（覆盖 page 0 全部 128 条 **gadget 元件区** ＝ 1000000…10005124，含宝箱/按钮/拉杆/机关，＋两个尾部特例）：
  **每一条都带一份组件清单**（不是计数，是完整描述符列表），组件类型用同一张 46 值枚举
  `jaUof90C3Ncl5BAJri4x`。分布见 §2。
- **基线 6 件套**（覆盖 ~190/194）：`Combat=18`、`CustomValue=1`、`Timer=3`、`Effect=6`、`RoleStatus=14`、`Hitbox=19`。
  **150** 条恰好＝基线的 6 件；其余为「基线 + 本例特有」。
- **关键否定**：**没有任何一条预制体的组件清单里出现 `Collision=8` / `ClientTrigger=5` / `StuffBag=33` / `Shop=35`**
  （Bash `grep -o` 在全部 3 个 fields-page 回执上检索这 4 个类型名，**均 0 命中**，§2.3）。
  ⇒ 「宝箱自带背包」「按钮自带碰撞触发器」**在本文覆盖范围内不成立**。
- **唯一带「我们要的组件」的模板**：`1086324737 默认模版`（`nativeKind=1`）带 **`PopUp=40`**（＝ M1「悬浮交互页」组件）；
  另 `1090519041 默认模版(角色编辑)` 带 `CustomSkill=22`+`MinimapMark=32`。均为**【实读】、未做实例化验证【未验证】**。

**判决（Q4）**：**没有**「实例化后直接得到 碰撞触发器 / 背包 / 商店 组件」的模板；`Collision/StuffBag/Shop`
在全部实读预制体里**一次都没出现**。唯一可能有用的模板默认组件是 `PopUp=40`（默认模版 `1086324737`），
它对应 M1 三入口之一的「悬浮交互页」，**值得作为一条候选 demo 路线**，但不是 `Collision`。

---

## 1. Q1 — 预制体记录**是否**暴露组件清单 / 计数？（【静态】+【实读】）

**分两层答：浅层目录**不暴露**，深层字段读**暴露**。**

### 1.1 浅层：`prefab-catalog` **不**带组件

`tools/editor-bridge/Adapter/SceneCatalog.cs:103` `PrefabCatalog()` 对每个 materialized 预制体模型只取四样：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


真实回执印证：`.runtime/editor-bridge/runs/8c515535-.../prefab-catalog-response.json` 只有一个扁平数组，
每条恰好 `{registryId, name, iconPath, nativeKind}`，**无组件字段**（`total=2722`）。

### 1.2 深层：`prefab-fields-page` **带**组件清单（完整描述符列表）

深读入口 `tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs:34` `PrefabFieldsPage` →
`:171` `PrefabFieldsNext` → `:36` `PrefabFieldsPageCore`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`ContentFieldReader`（`tools/editor-bridge/Adapter/ReopenContentEvidence.cs:17`）的预算
`MaxObjects=65536, MaxItems=16384, MaxDepth=48, MaxBytes=8 MiB`（`:20`）**远大于**这些预制体模型，
且回执里每个 item 的 `readSummary.complete=true, truncated=false, errorCount=0`
（例如宝箱 `10005006`：`visitedValues=315`）—— **这是一次完整读，不是截断样本**。

`content` 的形状（以 `10005006 珍贵的宝箱` 为例，**【实读】**）：
`{root:{refId:1}, objects:[…130 项…]}`。其中有 **一个 `List` 组件清单**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


清单的 6 个 `refId` 各指向一个 `CF9E4JXdL1Cq4xrMUnCq` 描述符块；**每个块的第一枚整数就是组件枚举值，
块内某字段是类型字符串 `BeyondCompType…`**。宝箱逐块解析（**【实读】**）：

| 块 refId | 块首整数 | 类型字符串 |
|---:|---:|---|
| 9 | **18** | `BeyondCompTypeCombat` |
| 28 | **1** | `BeyondCompTypeCustomValue` |
| 47 | **3** | `BeyondCompTypeTimer` |
| 66 | **19** | `BeyondCompTypeHitbox` |
| 85 | **6** | `BeyondCompTypeEffect` |
| 104 | **14** | `BeyondCompTypeRoleStatus` |

块首整数与枚举表**逐值吻合**（见 §4.1）⇒ **块首整数就是 `jaUof90C3Ncl5BAJri4x` 组件类型值**。

> **答 Q1**：是的 —— **深读回执（`prefab-fields-page`）里的预制体记录暴露完整组件清单**：
> 一个 `List<CF9E4JXdL1Cq4xrMUnCq>`，长度即「组件数」，每项携带 `{组件类型枚举值, 类型名, 载荷字段}`。
> 浅层目录回执（`prefab-catalog`）**不**暴露组件，只有 `{id,name,icon,nativeKind}`。

---

## 2. 实读统计：194 个预制体的默认组件分布（【实读】）

解析全部 3 个 `prefab-fields-page-response.json`，共 **194** 条带 `content` 的预制体（128+32+34）。
覆盖：**page 0 全部 128 条**（id 1000000…10005124 —— **gadget/元件 区，含宝箱/按钮/拉杆/机关/水体**）
＋ 一段怪物区（30006019…30008011，34 条）＋ 一段 id 992…1024 区间（32 条）＋ 尾部两条特例。
**覆盖边界**：目录共 **2722** 条，本文件实读 **194 / 2722 ≈ 7.1%**（**但含最相关的整个 gadget 区**）。

### 2.1 精确组件集合直方图

| 集合大小 | 条数 | 「额外成员」＝集合 − 基线6（**注意：额外成员非空 ≠ 含全基线**，见 2.2） |
|---:|---:|---|
| 2 | 1 | （基线子集，见 2.2） |
| 3 | 2 | `[PopUp]` |
| 6 | 150 | （就是基线，无额外） |
| 7 | 32 | `[Enmity, MonsterAiComp]` |
| 7 | 3 | `[WaterfallComp]` |
| 7 | 3 | `[WaterCubeComp]` |
| 7 | 2 | `[CustomSkill, MinimapMark]` |
| 8 | 1 | `[BulletMove, BulletPattern, HitDetection]` |

### 2.2 非基线（也非怪物）的预制体逐条 —— 给**完整集合**，不给推导

| resourceId | name | 完整组件集合（【实读】） |
|---|---|---|
| 1000000 | *(无名)* | `{CustomValue, Timer, PopUp}`（**≠ 基线+PopUp**：缺 Combat/Hitbox/Effect/RoleStatus） |
| 1086324737 | **默认模版**（`nativeKind=1`） | `{CustomValue, Timer, PopUp}`（同上，对象图与 1000000 一致，73 项） |
| 1000001 | *(无名)* | `{Combat, CustomValue, Effect, RoleStatus, Timer, CustomSkill, MinimapMark}`（＝基线**减 Hitbox** 加 2） |
| 1090519041 | **默认模版(角色编辑)**（`nativeKind=1`） | 同 1000001 |
| 10003001 | *(无名)* | `{Combat, CustomValue, Effect, Timer, BulletMove, BulletPattern, HitDetection, Hitbox}`（8 件） |
| 10003004 | 关卡实体 | `{CustomValue, Timer}`（**只有 2 件**） |
| 10005103–10005105 | 瀑布 / 瀑布顶端 | 基线 6 件 + `WaterfallComp` |
| 10005106–10005108 | 立方形/圆柱形/圆形水体 | 基线 6 件 + `WaterCubeComp` |
| 30006019…30008011（32 条） | 各类怪物/动物 | 基线 6 件 **减 Hitbox** + `Enmity, MonsterAiComp`（7 件） |

### 2.3 关键否定：`Collision / ClientTrigger / StuffBag / Shop` 一次都没出现

在全部 3 个 fields-page 回执上检索类型名（Bash，非 Grep 工具）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**范围内结论**：本文实读的 194 条预制体（含**整个 gadget 区 128 条**：3 种宝箱 10005006/07/08、
积木按钮 10005016、木质/石质拉杆机关 10005030/33、石质拉杆开关 10005034、石质尖刺平台 10005001 …）
**没有一条**携带 `Collision=8` / `ClientTrigger=5` / `StuffBag=33` / `Shop=35`。
宝箱、按钮、拉杆的组件集合**全部等于基线 6 件套**（`{Combat, CustomValue, Timer, Hitbox, Effect, RoleStatus}`，**【实读】**逐条核对）。
**范围**：194/2722；未实读的 2528 条不能外推，但最可能藏「交互组件」的 gadget 区已整段覆盖。

---

## 3. Q2 — 官方语料：哪些「单位/元件」被**文档**写成自带组件？（【文档】）

**先给最重要的一条否定**：官方 201 章里**没有**任何一章文档化「按钮会响应 / 拉杆会触发 / 宝箱会装道具 / 告示牌会显示文字」
这类**行为**作为「模板自带」。相反，**物件章明确写：物件不会自主反应**：

- `mhlh4n9m4i56`（物件，`概念介绍 > 单位`）——**【文档】**：
  > 「**物件无法对角色做出自主反应**」
  > 「**部分物件会默认携带一些自身常用的组件。**」
  > 「静态物件……**不支持组件、节点图等任何功能**」

⇒ 「放一个宝箱模板 → 它会装道具」**在文档层没有依据**；行为要靠**节点图**挂上去。官方文档化的只有**「默认携带某些组件」**，
不含「默认具备某交互行为」。以下逐条列出**文档化的默认组件**（每条给 chapter id + 逐字引用）：

| # | chapter id | title | 逐字引用（【文档】原文） | 对应枚举（§4 核） |
|---|---|---|---|---|
| 1 | `mhei6orvcbkm` | 通用组件 | 「组件是可以添加给实体的一项功能。」「通用组件可以自由的在元件或实体上添加和删除。」「**部分单位会默认携带一些自身常用的组件。**」 | （父页，泛指） |
| 2 | `mhlh4n9m4i56` | 物件 | 「**部分物件会默认携带一些自身常用的组件。**」；编辑面固定为「基础信息 / 特化配置 / **通用组件** / 节点图」四部分 | （泛指引到通用组件） |
| 3 | `mhso1b9wjica` | 自定义变量 | 「**自定义变量组件是所有单位的默认挂载组件（即单位创建时会默认挂载）**」；入口「在实体或元件的**组件页签**找到或新增自定义变量组件」 | **`CustomValue=1`** |
| 4 | `mhd7nxrfa8im` | 单位状态 | 「单位状态组件是一个用于配置**实体创建时，默认携带单位状态**的组件」 | **`RoleStatus=14`** |
| 5 | `mhvg40rc5w9i` | 受击盒设置 | 「在实体/元件的特化配置页签 **默认具有一个不可删除的受击盒组件**」 | **`Hitbox=19`** |
| 6 | `mhufqo0c0tqw` | 造物 | 「造物实体运行时，**默认携带和自身模型相等大小的受击盒**，可以正确接收战斗信息。」 | **`Hitbox=19`** |
| 7 | `mhn95di01j84` | 碰撞触发源 | 「**造物、角色实体，默认包含碰撞触发源，无需额外编辑**」；「对于不包含碰撞触发源的实体，他们无法通过接触碰撞触发器，产生进入范围/碰撞范围事件」 | 见 §4.2（注意：是**触发源**，不是**触发器**） |
| 8 | `mhuiob9dg1dm` | 额外碰撞 | 「**原生碰撞是预制元件默认携带的碰撞。**」；入口「在实体或元件编辑界面中，打开**组件编辑页签**」 | 见 §4.2 |
| 9 | `mh2u2e9o3jn6` | 悬浮交互页控件 | 「**交互页关闭按钮是悬浮交互页默认携带的界面控件**」（这是**界面控件**默认项，≠ 实体 `PopUp` 组件） | 界面控件，非 `PopUp=40` |
| 10 | `mhwp5h9d4h3e` | 元件库 | 「点击需要编辑的元件，右侧打开元件详情页，在详情页内可编辑元件相关的**属性、组件、节点图**及战斗内容」 | （文档确认**元件确有「组件」**这一编辑面） |

**文档层面的净结论**：官方语料**只**文档化「单位创建时默认挂载 `CustomValue` / `RoleStatus` / `Hitbox`，
造物·角色默认带碰撞触发源，预制元件默认带原生碰撞」这几件；**没有**文档化「按钮/拉杆/宝箱/告示牌」的默认行为组件。

---

## 4. Q3 — 文档行为 ↔ 组件枚举值 对照（【静态】枚举 +【实读】核）

### 4.1 枚举值 = 块首整数，逐值吻合

组件类型枚举**唯一定义处**：`.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-51`（46 成员）。
§1.2 从宝箱块首读出的整数 `{18,1,3,19,6,14}` 与该表**逐项吻合**
（`Combat=18`:21、`CustomValue=1`:6、`Timer=3`:7、`Hitbox=19`:22、`Effect=6`:10、`RoleStatus=14`:17）。
另 §2 的额外成员也吻合：`PopUp=40`:43、`CustomSkill=22`:25、`MinimapMark=32`:35、
`BulletMove=11`:14、`BulletPattern=20`:23、`HitDetection=12`:15、`Enmity=26`:29、`MonsterAiComp=42`:45、
`WaterfallComp=43`:46、`WaterCubeComp=44`:47。
⇒ **预制体组件清单用的就是这张同一枚举**，非第二套 id 空间（这一点与 `PREFAB-COMPONENT-PATH.md` §2.1 里
`.gil` 的 `kind` 是「另一套 id 空间」形成对照：**编辑器侧清单 = 枚举本身；`.gil` 侧 ≠ 枚举**）。

### 4.2 文档行为 → 组件枚举值

| 文档化的「行为」/机制 | chapter id | 对应组件枚举 |
|---|---|---|
| 碰撞触发器（接触判定→节点图事件）——**M1 的目标件** | `mh8w69rzuc3i` | **`BeyondCompTypeCollision = 8`** |
| 碰撞触发源（触发源侧；造物/角色默认带） | `mhn95di01j84` | （触发源/触发器是同一组件的两侧；命名枚举里只有 `Collision=8`，未单列 Source。**标【未定】**，不臆断） |
| 原生碰撞（预制元件默认携带） | `mhuiob9dg1dm` | （属「基础信息·原生碰撞」，非通用组件枚举项，**不映射**） |
| 额外碰撞（可配形状的碰撞范围） | `mhuiob9dg1dm` | **【未定】**（候选 `Obstacle=41` 或与 `Collision=8` 同族；本文不臆断） |
| 光标碰撞盒（光标射线碰撞检测） | `mhso200yz3h4` | **`BeyondCompTypeCursorCollision = 45`** |
| 自定义变量（所有单位默认挂载） | `mhso1b9wjica` | **`CustomValue = 1`** |
| 单位状态（创建时默认携带） | `mhd7nxrfa8im` | **`RoleStatus = 14`** |
| 受击盒（默认不可删） | `mhvg40rc5w9i` / `mhufqo0c0tqw` | **`Hitbox = 19`** |
| 背包组件（挂到实体上，M4 目标件） | `mh5y5001vqd4` | **`StuffBag = 33`**（＋`EquipStuffBag=34`） |
| 商店组件（M5 目标件） | `mho6gviqhsqs` | **`Shop = 35`** |
| 悬浮交互页（M1 的「悬浮页」入口） | `mh2u2e9o3jn6` | **`PopUp = 40`** |
| 客户端触发器 | （同族章） | **`ClientTrigger = 5`** |

⇒ **Q3 答**：文档化的默认组件里，**`CustomValue=1` / `RoleStatus=14` / `Hitbox=19` 是「人人自带」**（与 §2 实读 194 条吻合）；
而**我们真正要的 `Collision=8`（按钮/机关的碰撞触发器）、`StuffBag=33`（宝箱背包）、`Shop=35`（商店）**，
**在文档里都是「需要手动『添加通用组件』」的**（三章都给了「组件编辑页签 → 添加通用组件 → …」的按钮路径），
**不是**任何模板的默认项 —— 这与 §2.3 的实读否定**互相印证**。

---

## 5. Q4 — 判决：有没有「一实例化就得到我们要的组件」的模板？

**没有。** 逐条收口：

1. **`Collision=8`（按钮/机关的碰撞触发器）—— 否。** 实读的 gadget 区没有任何模板带它（§2.3）；
   文档把它列为需**手动添加**的通用组件（`mh8w69rzuc3i`）。**按钮/拉杆模板本身不带碰撞触发器。**
2. **`StuffBag=33`（宝箱装道具）—— 否。** 三种宝箱模板（10005006/07/08）的组件＝基线 6 件套，**无背包组件**（§2）；
   文档把背包组件列为需**手动添加**且「仅可挂角色/造物/动态物件」（`mh5y5001vqd4`）。
3. **`Shop=35`（商店）—— 否。** 同上，无任何模板带它。
4. **`ClientTrigger=5` —— 否。** 全文 0 命中。
5. **唯一「免费送」到点上的模板**：**`1086324737 默认模版`**（`nativeKind=1`，目录尾条目，
   见 `.runtime/asset-inventory/prefabs-all.tsv` 最后两行行号 2721/2722）带 **`PopUp=40`**
   —— 对应 **M1 三入口之一的「悬浮交互页」**。**这是唯一可命名的候选 demo 路线**（模板 id = `1086324737`）。
   - 但**必须标【未验证】**：本轮零执行，**没有**验证「用该模板建出的实体其组件面板真会多出一行 PopUp」，
     也**没有**验证 `1086324737` 是「实体模板」还是「关卡/场景模板」（`nativeKind=1` 与全部元件 `nativeKind=0` 不同）。
   - 同理 `1090519041 默认模版(角色编辑)` 带 `CustomSkill=22`+`MinimapMark=32`，判为「角色编辑」专用，与 M1–M6 目标无关。

**为什么这条路整体走不通（机制原因，【静态】）**：模板组件集合是**加法受限**的——
实读显示所有模板共享同一「基线 6 件套」，加上极少数按类别固定的特化件（怪物 `Enmity/MonsterAiComp`、
水体 `Waterfall/WaterCubeComp`、默认模版 `PopUp`）。**没有任何模板**携带「交互类」组件，
因为那些组件是**用户在编辑器里手动挂**的（文档三处「添加通用组件」路径），而不是**出厂默认**。
换言之：**模板选择只能复现「出厂基线」，复现不了「用户添加」**——所以它**不是** add-component 原语的替代品，
唯一例外是默认模版那条 `PopUp=40`。

---

## 6. 复现命令（本次全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


（脚本落 `.runtime/scratch/prefab_comp_scan.py`、`prefab_comp_probe.py`、`prefab_comp_map.py`、`prefab_seq.py`；
本文件全部数字由它们从真实回执算出。）

---

## 7. 边界复核（本文件的绝对声明逐条）

- 「深读回执带完整组件清单」→ 由 `PrefabCollectionEvidence.cs:122` 的 `ContentFieldReader.Read`（预算 `ReopenContentEvidence.cs:20`）
  ＋ 194 条回执均 `readSummary.complete=true` 支持；浅层目录不带由 `SceneCatalog.cs:117-119` ＋ 回执字段形状支持。
- 「块首整数＝枚举值」→ 由宝箱 6 值 `{18,1,3,19,6,14}` 与枚举表逐项吻合支持（§4.1）。
- 「宝箱/按钮/拉杆不带 Collision/StuffBag/Shop」→ 由 §2.3 的 Bash 0 命中 ＋ 逐条集合核对支持；**范围** 194/2722（**含整段 gadget 区**），不外推未读的 2528 条。
- 「官方文档化了 `CustomValue/RoleStatus/Hitbox` 默认挂载、无文档化按钮/宝箱默认行为」→ 由 §3 表逐章引用支持；**"没有某章"是范围内结论**（201 章 + 202 源 txt）。
- 「默认模版 `1086324737` 带 `PopUp=40`」→ **【实读】**（该 id 在目录尾，`prefabs-all.tsv:2721`）；**其可实例化性与行为未验证【未验证】**。
