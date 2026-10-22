> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #6 — `entity.properties`：实体字段 schema 到底挖到哪一步

**产出日期**：2026-10-10
**口径**：离线只读。未起/未连 bridge，未发任何 native/graph 报文，未接触游戏或编辑器进程，
未写任何存档。全部结论来自对**已合入工作树**源码的静态阅读（`file:line` 逐条可核）。
未读 `.runtime/` 下未合入副本，故不代表暗角（本工程已知：`.runtime` 里存着未合入候选）。

**一句话结论**：实体字段的**读**已经相当深——但深的是**身份、变换、标签、阵营、图绑定、以及一棵无语义的原始字段树**；
**写**只打穿了三个标量族（名字 / 标签 / 阵营）。
真正的 `entity.properties`（通用组件：碰撞触发器、掉落物拾取规则、背包组件、商店组件）**读与写都没有一条按语义命名的通路**——
现有最深的一次读能把这些字节**原样搬出来**（`ContentFieldReader` 全字段树），但**没有任何一层把它们命名成"碰撞触发器/拾取规则/背包/商店"**。
缺的不是"再挖一个偏移"，而是**两条不同的矿脉**：编辑器模型侧的**组件集合字段符号**，与 `.gil` 侧的**组件 kind 号→组件类型**映射。下面把它拆开写。

---

## 0. 三层必须先分清（否则会把"搬得出来"当成"读得到"）

| 层 | 这是"看得见什么" | 现状 |
|---|---|---|
| **A. 编辑器内存模型读**（bridge op，只读） | registry 里每个实体模型的字段值 | 深，但**只有少数几个字段被命名**；其余靠一棵**无语义**的原始字段树兜底 |
| **B. 游戏进程内存读**（native snapshot，只读） | 运行时实体字典每条的 owner/config/context/id/configId | 浅：**显式拒绝**读 transform/component 偏移（`game_context_snapshot.cpp:234` 原文 "No guessed transform/component offsets; position remains explicitly absent."） |
| **C. `.gil` 关卡文件离线解码**（只读） | 每个实体记录的 protobuf 字段与组件 wrapper | 深到**位置**（proto 字段号），但**组件 kind 号没有任何名字**（`entity_geometry.py` 模块头 "No public name (collider, model, script, ...) is asserted for any of them"） |

**「进了模型」≠「看得见」≠「能玩」**（`.claude memory model-registry-is-not-visible-candidate`）：
A 层能把组件字节读出来，C 层能把组件字节定位到 offset，但**两层的字节至今没有被同一条命名桥接起来**，
所以"能否读到碰撞触发器"这个问题的诚实答案是——**字节在，名字不在**。

---

## 1. READ 侧：现在到底能读到哪些实体字段（逐字段 + file:line）

### 1.1 编辑器模型（bridge，op `catalog` → `SceneCatalogSnapshot`）

`tools/editor-bridge/Adapter/SceneCatalog.cs:20-48`，上限 `SceneEntityLimit=128`（`:16`）。

| 字段（我方 JSON 名） | 读到的是什么 | 证据 |
|---|---|---|
| `id` | 实体 key 的 id，去重 | `SceneCatalog.cs:24`（`Qi8iCzKCkTt` → `namiwGPRyPS`） |
| `name` | 实体显示名 | `SceneCatalog.cs:35`（`WAAiS5WkxlA`） |
| `prefabId` | 编辑器 prefab 关联缓存 id（**非**模板 id） | `SceneCatalog.cs:35-36`（`TuuiS94iUgu`，注释明写 `prefabIdIsTemplateId=false`） |
| `templateId` | 协议模板引用 id（引用对象上的字段） | `SceneCatalog.cs:37` + `:56-65`（`dmhiSVca7Ew` → `pgfitPOV3oW`，旧名经 binding profile 解析） |
| `nativeEntityType` | 原生实体类型 int（如 1402） | `SceneCatalog.cs:38`（`yEpiSj6okKa`） |
| `nativeInstanceKind` | 原生实例种类 int | `SceneCatalog.cs:39`（`d4siSoaFICf`） |
| `transform`（三向量） | 编辑器 registry 的**变换缓存**，三个原生名向量 | `SceneCatalog.cs:40` + `:71-76`（`hTjiSreIlqL` → `maSidNtJUim` / `MtbidjteDd3` / `OStidFtjJdR`） |
| 向量三分量 | x/y/z（原生名，**不重命名**为 position） | `SceneCatalog.cs:81-83`（`xYKidoTpamf` / `MDTidUcgOhj` / `LSnidRDCRwE`） |

同一 op 里的 prefab 侧（`PrefabCatalog`，op `prefab-catalog`，`SceneCatalog.cs:103-132`）：
`registryId` / `name` / `iconPath` / `nativeKind`（`:117-119`）。
**注意**：`transform.authoritative=false`、`componentPresenceVerified=false`（`SceneCatalog.cs:72`）——
这是本工程一贯的"读到了缓存 ≠ 权威几何"的纪律。

### 1.2 编辑器模型（bridge，op `inspect-entity-crud-probe` / `begin-entity-crud-probe`）

`tools/editor-bridge/Adapter/EntityCrudProbe.cs:57-62` 读同一批字段，但**不做 128 上限**（走 registry 全遍历）：

| 字段 | 证据 |
|---|---|
| name | `EntityCrudProbe.cs:58`（`WAAiS5WkxlA`） |
| prefabId | `EntityCrudProbe.cs:59`（`TuuiS94iUgu`） |
| templateId | `EntityCrudProbe.cs:60`（`ReadSceneTemplateId`） |
| nativeEntityType | `EntityCrudProbe.cs:61`（`yEpiSj6okKa`） |
| nativeInstanceKind | `EntityCrudProbe.cs:62`（`d4siSoaFICf`） |
| key（4 段 category + id） | `EntityCrudProbe.cs:40-42`（`oLyiwZX255H`/`AwbiwrjxUDX`/`UFWiwJNegmh`/`RBTiwn649Hy`/`namiwGPRyPS`） |

### 1.3 单实体变换读（bridge，op `entity-transform`，action=inspect）

`tools/editor-bridge/Adapter/EntityTransform.cs:107-137`：按 id 定位**唯一**模型（`:114-116`），
读 `SceneTransformField`（`:122`），返回 `vectorRolesVerified=false` + `roleMapping="unestablished: ..."`（`:132-133`）。
**写**分支存在但**必抛** `TRANSFORM_NATIVE_SETTER_UNKNOWN`（`:36`、`:144`）——见 §2。

### 1.4 标签读（bridge，op `author-entity-tag`，action=inspect）

`tools/editor-bridge/Adapter/AuthorEntityTag.cs:101-104`：读实体的 `List<int>` 标签集合 + 标签**定义表**（id→名）。
字段：`TagListField71="K07Xiow3cj5"`、items `"i4gXwUOgjxk"`（`:19`），标签目录 `10003/50013`（`:79`）。

### 1.5 阵营读（bridge，op `inspect-entity-faction-probe`）

`tools/editor-bridge/Adapter/EntityFactionProbe.cs:114`：读实体阵营标量 `wCGXiPk8NaS`；
阵营定义来自`10003/50011`目录（`:81`），实体可选阵营集合由 `10005/53100` 策略给出（`:82`、`:95-99`）。

### 1.6 图绑定读（bridge）

`tools/editor-bridge/Adapter/EditorAdapter.cs:120-125`：`entity.t6ViSxlgnQ3()` 取绑定集合。
被 `EntityBindings` 多处消费（`AuthoringGraph.cs:255-256`、`ReopenContentEvidence.cs:170`）。
**这正是官方命令 `AddInstructionGraphForEditObj` 里"取实体第 3 号组件"的那条组件集合读入口的邻居**
（见 §3 的缺口 1）——我们目前只从它取**图绑定**，没有取别的组件类型。

### 1.7 实体整棵原始字段树（bridge，op `inspect-reopen-content`）——**最深的一次读，但无语义**

`tools/editor-bridge/Adapter/ReopenContentEvidence.cs:169-171`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`rawFields` 用 `ContentFieldReader`（`ReopenContentEvidence.cs:14-100`）把**整个实体模型**做一次有界深走：
`MaxObjects=65536, MaxItems=16384, MaxDepth=48, MaxBytes=8MiB`（`:17`），
**跳过**公共运行时基类 `hnRX5SXOfpHoFMcisZBH.sSJI8CXOTXcMB9gP3URF`（`:91`），
逐字段输出 `{declaringType, name, value}`，并把已知的 5 个泛型存储包装解包（`:65-71`）。

⇒ **这条通路事实上已经把"通用组件列表"的字节搬出来了**（组件就在实体模型的某个字段里），
但**输出里每个字段都只有混淆名**，且**顶层硬编码了 `componentPresenceVerified=false`（`:171`）**，
末尾还有 `semanticComponentMappingVerified=false`（`:224`）。
所以现状是：**"读得到字节"成立，"能命名成碰撞触发器/背包/商店"不成立**。

### 1.8 元件标量字段树（bridge，op `prefab-fields`）

`tools/editor-bridge/Adapter/PrefabFieldRead.cs:13` 限 `MaxDepth=3, MaxCollectionItems=4, MaxScalarRows=90`；
`SceneCatalog.cs:163-193` 对固定的 11 个 prefab id 跑它。
**同样是无名标量树**，且深度只有 3，**够不到深嵌的通用组件**（M1 §3 的"未确认"点就在这里，仍未实测）。

### 1.9 原生快照（`scene_cli inspect` → 游戏进程内存，只读）

结构体 `GameEntitySnapshot`（`tools/game-executor/native/game_context_snapshot.h:78-84`）**一共只有**
`owner, config, context, dictionaryKey, id, configId, flags, position[3], reserved, reserved2`；
`position` 注释逐字写着 **"GE_POSITION_READ is never set: no proven position offset"**（`:81`）。
偏移常量（`game_context_snapshot.cpp:57-79`）：

| 宏 | 值 | 读什么 |
|---|---|---|
| `GS_OWNER_ID_OFFSET` | `0x1c` | owner 上的实体 id（`:218`） |
| `GS_OWNER_CONTEXT_OFFSET` | `0xb0` | owner 上的 context（`:223`） |
| `GS_OWNER_CONFIG_OFFSET` | `0xa8` | owner 上的 config 对象指针（`:228`） |
| `GS_CONFIG_ID_OFFSET` | `0x1c` | config 对象上的 configId（`:231`） |

解码器 `tools/game-executor/decode_context_snapshot.py:125-133` 输出与之一致；
`position` 仅在 `flags & 16` 时才输出，而该位**从未被置**（`game_context_snapshot.h:81`）。
⇒ **运行时这一侧没有组件面，且是显式拒绝，不是遗漏**（`:234`）。

### 1.10 `.gil` 离线解码（`entity_geometry.py`，只读）

`tools/beyond-save/entity_geometry.py` 的定位常量（`:124-133`，全部是**读真实字节得到的位置号，不是厂商名**）：

| 常量 | 值 | 含义（位置，非命名） |
|---|---|---|
| `ENTITY_TABLE_FIELD` | 5 | 根字段 5 = 实体表 |
| `ENTRY_ID_FIELD` | 1 | 条目字段 1 = 整数 id |
| `ENTRY_REF_FIELD` | 2 | 条目字段 2 = `{1:int,2:int}` 引用 |
| `ENTRY_TAG_FIELD` | 8 | 条目字段 8 = 整数 tag |
| `COMPONENT_GROUPS` | (5,6,7) | 这三个条目的子项是**组件 wrapper** |
| `TRANSFORM_GROUP` / `TRANSFORM_KIND` / `TRANSFORM_PAYLOAD_FIELD` | 6 / 1 / 11 | 变换的精确地址 `root5/entry6/kind1/field11` |
| `TRANSFORM_VECTOR_FIELDS` | (1,2,3) | 位置/旋转/缩放三向量 |

组件 wrapper 的形状是 `{1: kind, <P>: payload}`，其中 `<P>` 是 kind 的**固定函数**（实测）但**无单一规则**
（`entity_geometry.py:26-32`；group 6 → kind+10；group 5 kind3→field12 但 kind13→field22）。
`component(group, kind)` 可按 `(group, kind)` 取组件（`:326-330`）。
**语义全无**：模块头 `:87-106` 明确 "no public name is asserted for any of them"。
碰撞映射的实测结论一致：`docs/gameplay/COLLISION-COMPONENT-MAPPING.md:22` "尚无证据将任何号命名为碰撞触发器/源"，
`:60` "collisionMapped=false"。

### 1.11 收到的 1017 包里的几何组件（bridge 观察器，只读）

`tools/editor-bridge/Adapter/Geometry1017Fields.cs` 从**实际收到的 1017 资源增量报文**里读
proto 侧组件：组件 kind `HdDIPUkYYjM`、payload tag `iLMIPugmMtk`（`:118`），只解析 `tag==18`
（geometry）的组件（`:119`），形状 tag 11/12/13（`:131-141`）。
**历史读数 `geometryComponentCount` 恒为 0**（`ComponentGeometryEvidence.cs:40-42` 的
`captured=false` / `geometryVerified=false`，以及 `:33` 的 `readOk=false` 兜底；
`GEOMETRY-THREE-WAYS.md:280-281`）——**它从未读出过非空**。
这是**协议侧**的组件面，与实体模型侧不是同一个对象，不能互相顶替。

---

## 2. WRITE 侧：现在到底能写哪些实体字段

口径："能写" = 有一条按语义命名的写入口**且**带前置基线核对（`expected*Sha256` 之类），但**一律不宣称实机生效**。

| 字段族 | 能写? | 写入口（符号/命令） | 证据 | 边界 |
|---|---|---|---|---|
| 名字 | **能（窄）** | 直调原生 `ModifyEditObjName` | `EditorAdapter.cs:569`、`EntityCrudProbe.cs:207` | 只对**自建探针实体** `MW_CRUD_Probe`；有 rename/restore 配额 |
| 标签（`List<int>`） | **能（窄）** | `ModifyEditobjTag` | `AuthorEntityTag.cs:119-127` | 只对本次拥有的探针实体；`expectedTagsSha256` 前置（`:106`）；反操作需先读回（`:110`） |
| 阵营（1 个 int32） | **能（窄）** | `ModifyFactionForEditObj` | `EntityFactionProbe.cs:143-152` | 同上；set/restore 各一次 |
| **transform（位置/旋转/缩放）** | **不能** | 无 setter | `EntityTransform.cs:36,144` 抛 `TRANSFORM_NATIVE_SETTER_UNKNOWN` | 38 条后端命令**无一**能给已存在对象设位姿（`COMMAND-ROUTE-MAP.md:162-186`，CONFIRMED） |
| **通用组件（增/改/删）** | **不能** | 无 Add/Modify 组件；**删**组件命令存在但未用 | 见 §3 缺口 1 | 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 `component/property/trigger` **0 命中**（`INTERFACE-INVENTORY.md:18-21`） |

**一句话**：写面只有**名字 / 标签 / 阵营**三个标量，且每一处都是**白盒探针**（只对自建实体、带哈希基线）。
**没有任何一处在写组件列表**（`grep -rn "AddComponent\|SetComponent\|componentList" Adapter/*.cs` → 0）。

---

## 3. SceneCatalog.cs / Geometry1017Fields.cs 已映射的"编辑器模型字段"

两张表都不是通用组件映射，各自的映射面如下：

**`SceneCatalog.cs`**（编辑器实体模型 → JSON）：见 §1.1 表——身份 6 项 + 变换 3 向量 + 3 分量。
它**没有**触碰组件集合：文件内 `component` 字样为 0；变换字段是被当作"缓存"读的，
`TransformSnapshot` 注释（`:67-70`）明写 "This field alone cannot establish component presence"。

**`Geometry1017Fields.cs`**（收到的 1017 包 → 几何）：映射了 proto 的
`group/union/prefab/proto/components/component/geometry/shapeGroup/shape` 一串混淆类型名（`:15-26`），
以及 3 种形状的几何 payload（`:131-141`）。
这是**报文侧**的组件读，**不是**实体模型的组件读；且**从未读出非空**。
文件末尾的 `collisionKindMappingVerified=false`（`:160`）逐字承认碰撞 kind 映射未建立。

⇒ **两张表都没有"实体 → 通用组件 → 具体组件类型"这条链上的任何一个命名映射。**

---

## 4. 缺什么：六模块真正需要的组件字段，与要挖的具体符号/偏移

需求侧字段名来自官方文档（`docs/research/game-b-systems-20261009/M1-interaction.md`、
`M4M5-inventory-shop.md`，均为 218 章离线语料的 verbatim）。**这些是文档层的字段名，尚未映射到任何
编辑器模型符号或 `.gil` kind 号**——这正是缺口。

| 模块 | 组件（官方章） | 需要的字段（文档层） | 编辑器模型侧：要挖的符号 | `.gil` 侧：要挖的映射 |
|---|---|---|---|---|
| M1 交互 | **碰撞触发器** `mh8w69rzuc3i` | 触发区形状（长方体/球体/胶囊体）、初始生效、生效目标（角色/物件/造物） | 实体模型上的**组件集合字段** + 组件对象上的**类型判别字段** + 该类型的 **payload 字段符号**（三样全缺） | `(group,kind)` 中哪一个 kind = 碰撞触发器；形状枚举 0/1/2 的编号 |
| M1 交互 | **碰撞触发源** `mhn95di01j84` | 形状、中心、旋转、缩放倍率 | 同上 | 同上（触发器与源**不能混用一个 kind**） |
| M1 交互 | **掉落物拾取规则** `mhkfj1iilnck` | 拾取规则枚举（交互拾取/自动拾取/打开拾取界面/自动吸附拾取）、拾取范围形状、自动吸附距离(m) | 该组件挂**元件**上（`mhkfj1iilnck`："所有掉落物类型的元件会固定携带一个掉落物内容组件"），故先要**元件模型**的组件集合符号 | 掉落物内容组件的 kind；规则枚举 4 值的编码 |
| M4 背包 | **背包组件** `mh5y5001vqd4` | 背包模板（仅 1 个引用）、初始物品、可挂载宿主 | 组件对象上的 `模板引用 id`（对照 `templateId` 的读法 `SceneCatalog.cs:56-65`）+ 初始物品列表 | 背包组件 kind；模板引用在 wrapper 里的字段号 |
| M5 商店 | **商店组件** `mho6gviqhsqs` | 商店序号、商店名称、商店模板引用、预览样式 | 同上；一个组件可挂多个商店（按序号隔离） | 商店组件 kind；序号字段号 |

**两条各自独立的矿脉（不许互相顶替）：**

- **矿脉 ①：编辑器模型侧的组件集合。** 要挖三样：
  (a) 实体模型的**组件集合字段符号**；
  (b) 组件对象的**类型/kind 判别字段符号**；
  (c) 每种组件类型的 **payload 字段符号**。
  现有最近的落点是两处：`EditorAdapter.cs:120-125` 的 `EntityBindings`（用 `t6ViSxlgnQ3()` 取绑定集合，只取图绑定）
  与 `COMMAND-ROUTE-MAP.md:50` 记录的 `AddInstructionGraphForEditObj` 处理器语义 **"第2参查实体→取组件3→装配节点图"**
  ——即"组件的第 3 号"是那条命令的入口，**它的符号与语义是矿脉 ① 的第一个可挖点**。
- **矿脉 ②：`.gil` 侧的 kind 号 → 组件类型映射。** 需要**单变量样本**：
  同一空载体，A 空、B 只加一个默认碰撞触发器、C 仅改触发目标、D 仅改一个区域维度
  （`COLLISION-COMPONENT-MAPPING.md:54-58` 已把这条最小证据需求写死）。
  目前只有 `(group,kind)` 的位置观察（`entity_geometry.py:26-32`），**没有一条 kind 被命名**。

**已经确证的一条 NEGATIVE（有证据，可当交付）**：
后端 38 条命令里**没有 Add/Modify 通用组件**这类命令——只有 **删**组件：
`DeleteComponentForEditObj` / `DeleteComponentForPrefab`（`COMMAND-ROUTE-MAP.md:53-54`，
`user-operations/03:115`，handler `0xcb64140` 取组件→注销）。
二者 `route_status=matched` 但**本工程从未发送**（`COMMAND-ROUTE-MAP.md:111` 的 AVAILABLE-BUT-UNUSED 清单）。
⇒ **"配一个碰撞触发器"这条路在后端命令面上没有 Add 落点**；M1/M4/M5 的"配置面"在命令层是**缺一条 Add/Modify 命令**，
与 `INTERFACE-INVENTORY.md:18-21` 的"桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）零命中 component/property/trigger"是同一个方向的**两条独立证据**。

---

## 5. 优先级缺口清单（按"能解锁什么"排序，各带一个能结案的实验）

| # | 缺口 | 解锁 | 结案实验（离线可先做的部分 / 需真机的部分） |
|---|---|---|---|
| **G1** | 实体模型的**组件集合字段符号** | 所有组件类模块的读面（M1/M4/M5 的 scene 半边） | 离线：对 `inspect-reopen-content` 已有样本 `rawFields`（`ReopenContentEvidence.cs:171`）里实体模型的字段做**名字级聚类**——找那个"元素是同类 wrapper、每个 wrapper 有"类型int+payload"形状"的字段；列出候选符号。真机：对一个**已知挂了碰撞触发器的实体**跑一次 `inspect-reopen-content`，看候选字段是否随触发器出现/消失 |
| **G2** | 组件的**类型判别字段** + 各类型 **payload 字段符号** | 组件按语义命名（G1 的下一步） | 离线：把 G1 候选 wrapper 的 `type int` 全值集合与官方组件名清单（M1/M4M5 的章名）对齐。真机：**单变量**——同一实体，A 无组件 / B 只加碰撞触发器 / C 只加背包 / D 只加商店，比对 `type int` 的增量 |
| **G3** | `.gil` 的 `(group,kind)` → 组件类型映射 | 离线读写 `.gil` 时的组件识别（不依赖编辑器进程） | 离线：把 `entity_geometry.py::summarize` 的 `component` 普查（`:426-470`）跑遍**全部可读 `.gil`**，先建立 kind 出现频率基线与"哪些 kind 普遍存在/罕见"。真机：`COLLISION-COMPONENT-MAPPING.md:54-58` 的 A/B/C/D 四副本对照 |
| **G4** | 组件**模板引用字段**（背包模板/商店模板） | M4/M5 的"配表"读面 | 离线：复用 `templateId` 读法（`SceneCatalog.cs:56-65` 的"引用对象 → 引用对象上的 id"两层模式）作为候选形状。真机：对一个挂了背包/商店组件的实体，看 G2 的 payload 里是否出现"引用对象→uint id" |
| **G5** | 拾取规则**枚举 4 值的编码** | M1 掉落物语义 | 真机：同一掉落物元件，把拾取规则依次设为 4 个值，各导出一次，比对 payload 的那个 int |
| **G6** | 后端是否有 **Add/Modify 组件**命令 | M1/M4/M5 的**写**面（若不存在，则写面只能走节点图旁路） | 离线：把 `backend.db` 的 `command_route` 里所有含 `Component` 的行穷举（当前已知仅 id4/id5 两条**删**）；再对 `dispatch_table` id=1/2 的**全部比较常量**做"未命名哈希"反查（`COMMAND-ROUTE-MAP.md:203-204` 声明的边界）。真机：无（这是命令面静态问题） |

**旁路（值得先试，绕开 G1–G4）**：M1 的"操作→可见变化"可全走**节点图**——
官方节点目录里已有「界面控件组触发时」（id 316，**带出参**）、「激活控件组库内界面控件组」(383)、
「设置界面控件(组)状态」(384)、「移除控件组库内界面控件组」(521)
（`M1-interaction.md:74-76`、`NODE-CATALOG.md:839/863/864/896`）。
若 `graph.nodes` 从"71/1 固定"推广到"按 definitionKey 加任意节点"，则 M1 不需要组件写入口。
但 `graph.nodes` 状态仍为 **partial**，**尚未实测**（`M1-interaction.md:86`）。

---

## 6. 诚实边界

- 本文件**全部是静态阅读**（源码 + 已产出的离线文档），**零执行**：未起/未连 bridge，
  未发任何 native/graph 报文，未接触 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` 下任何文件，未改任何存量文件（只新增本文件）。
- "能读/不能读"的分级依据是 **bridge op 是否存在 + 是否触碰该字段**（§1 逐条 file:line），
  **不等于实机跑通**。srcD 上标注的 `componentPresenceVerified=false`、
  `semanticComponentMappingVerified=false`、`collisionKindMappingVerified=false` 等，
  在本文件里**一律照抄为 false**。
- 未读 `.runtime/` 下未合入副本（本工程已知暗角）。"未找到"永远只说"本次检索范围内未找到"。
- 需求侧字段名（碰撞触发器/背包组件/商店组件/拾取规则…）来自 **218 章官方离线语料**，
  是**文档层**证据；**文档层字段名 ≠ 编辑器模型符号 ≠ `.gil` kind 号**——三层至今未桥接，
  这正是本文件把缺口拆成"两条独立矿脉"的原因。
