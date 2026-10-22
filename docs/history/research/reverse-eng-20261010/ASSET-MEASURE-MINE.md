> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #4 挖 — 模板尺寸到底能从哪来（`asset.measure` 的路）

**产出日期**：2026-10-10。位置：`docs/research/reverse-eng-20261010/ASSET-MEASURE-MINE.md`。
**口径**：**纯离线、纯只读**。全程**未连桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。
证据来源四处：① 仓内 C# 源码 ② 仓内**真实回执 JSON**（`.runtime/editor-bridge/runs/*/`，Bash `grep` / `python`
解析，**Grep 工具会静默跳过 `.runtime/`**）③ 反编译/反注释语料 ④ **pinned PE 元数据档** `metadata-7.1.json`。
**本文件只读不写，仅新增本文件本身。**

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么`（离线源码） / `真机验证过什么`（真实回执）** 三层分开标。
> 凡"有实现没跑过"标 `只离线`/`未验证`；凡"N 命中 0"写明**检索范围**；**"搜不到"≠"不存在"**。

---

## 0. 一句话结论

**模板尺寸在本仓**没有任何现成的离线来源**——但"没有"这句话的强度分两档：**

1. **两处候选被"穷举式"关死**（不是"没搜到"，是"字段清单里根本没有"）：
   - **编辑器预制模型不带任何尺寸/包围盒字段**：`metadata-7.1.json` 里预制模型类型
     `zDWuCYXAIGplUjEgOhcg.xvBUJOxABeOPt0cFA00U` 的**全部 17 个字段里没有一个 `float`/`double`**
     （见 §2.3）；深读 194 预制、2310 个浮点叶子**全是 0.0**（`PREFAB-FIELDS-MINE.md` §4.3）。
   - **`prefab-catalog` 回执不带尺寸/包围盒/碰撞字段**：源码返回体只有
     `registryId/name/iconPath/nativeKind`（`SceneCatalog.cs:117-119`），**真实回执逐键核对一致**（§2.1）。
2. **唯一一处真正带"尺寸原语"的通道是 1017 报文里的"形状组件"**：shape 12 = **球（Center+Radius）**、
   shape 13 = **胶囊（Center+Radius+Height+Direction）**、shape 11 = **长方体（Center+两个向量）**——
   且官方文档把这三者逐字点名（"半径"/"高度"/"长方体…自定义缩放"）。但**两次真机 1017 抓包里
   `geometryComponentCount` 都是 0**（其中一次抓到 128 个 proto / 770 个组件，**依旧 0 个几何组件**），
   所以**从未取到过一个真值**，且 `rawProtoId → 编辑器 registryId` 的映射**未证**。⇒ **它是"最省的候选"，
   不是"现成的来源"。**

**另外把题目那个"两个 double"直接判死**：组件模型的 `xPos`/`yPos` 是 **2D 位置（编辑器坐标系），
不是 2D 尺寸**——`xPos`/`yPos` 是本引擎的"位置"词表，本引擎表达"大小"用 `width`/`height`
（同一份元数据里就有同时带 `xPos/yPos` 与 `width/height` 的类型）；且 1196 条真实组件记录里 `x=y=0.0`（§1）。

---

## 1. 题面第一问：组件模型的那两个 double 是"2D 尺寸"还是"位置"？

### 1.1 三个名字空间先分清（否则会拿错名字）

组件模型在语料里有**三套名字**（见 `BINDING-SYMBOL-AUDIT` 的记忆「节点 id 有两套命名空间」同款陷阱）：

| 名字空间 | 组件 id | 启用 | x | y | 出处 |
|---|---|---|---|---|---|
| **pinned 71 名**（题面给的） | `OgoXdqFmidJ` | `gKyXdGplIdw` | `rNIXd7Mpstc` | `f3VXda70g6Z` | `metadata-7.1.json`（类型 `tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq`） |
| **legacy 字段名**（resolved 语料） | `OTQiCVjSfFs` | `fydiCJQHm3O` | `d8LiCZa1gcE` | `so7iCroxZbp` | `.runtime/editor-catalog/resolved/taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:12-18` |
| **属性名（可读！）** | `b1EiCj8P44N()` | `yYJiCpvHnUp()` | **`xPos`** | **`yPos`** | 同文件 `:22-24`；`metadata-7.1.json` 的 `properties` 段 |

**关键**：`rNIXd7Mpstc` / `f3VXda70g6Z` 是**混淆名，本身不含语义**；但这两个字段各有一个**只在 getter 里暴露的
可读属性名 `xPos` / `yPos`**——而且这个名字在 **pinned PE 元数据**里就是 `properties: [{name:"xPos"},{name:"yPos"}]`，
**不是反编译器猜的**。`xPos`/`yPos` = **position（坐标），不是 extent（范围）**。

### 1.2 穷举：本引擎里"有 `xPos` 属性的类型"全是编辑器 2D 项（"大小"另用 `width`/`height`）

对 `metadata-7.1.json`（**15654 个类型**）全表扫描"属性名 == `xPos`"，**恰好 7 个类型**（这是全表，不是抽样）：

| 类型 | 属性集合 | 是不是编辑器 2D 项 |
|---|---|---|
| `tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq` | `[xPos, yPos]` | **就是本题的组件模型** |
| `tovTeVjoYiCwqmVZmTQw.B7AiwKjoH7x1X36oMIek` | `[isVisible, xPos, yPos, **height, width**, text]` | **同类型里"位置"用 xPos/yPos、"大小"用 width/height——两套词表并存** |
| `G2oK7Vj8pTg704eoB8dd.DrkZ0Hj8QyWekcvHG4Jl` | `[vmBtnEdit, vmBtnDelete, xPos, yPos, itemType, **Bounds**, ZIndex, IsVirtualShow, TreeNode]` | 编辑器树项（P03 已判 "2D editor tree/UI item rectangle"） |
| `WcUvVEQL1PHbq7XfqUH4.K0s9lwQLAsNZ1haj78nt` | `[name, desc, nodeIdStr, vmInPinList, …, xPos, yPos, zIndex, itemType, Bounds, TreeNode]` | **节点图节点（画布坐标）** |
| `h27B3oXlxcN6dvR6aQBi.yudq5KXlmuVpBrR7rVQF` | `[id, xPos, yPos]` | 编辑器 2D 项 |
| `CGKjp8jPsncRNXXCLlFd.fw91AUjP4bbQ5saLauhy` | `[isVisible, xPos, yPos]` | 编辑器 2D 项 |
| `KA2Dv4j89vrUFh4pyJ1n.dmWe0Pj8VnnAf9rZnuy0` | `[vmBtnEdit, vmBtnDelete, isExpanded, isFixed, xPos, yPos]` | 编辑器树项 |

**推理（决定性）**：

- 同一个元数据里，**"大小"有专门的词**：`tovTeVjoYiCwqmVZmTQw.B7AiwKjoH7x1X36oMIek` **同时**有 `xPos/yPos`
  **和** `width/height`。⇒ 本引擎**不会**用 `xPos/yPos` 表示尺寸；尺寸叫 `width`/`height`。
- **全部 7 个带 `xPos` 的类型都是编辑器 2D 项**（树项/节点图节点/列表行），没有一个是 3D 世界对象。
  ⇒ 组件模型的 `xPos/yPos` 是**编辑器 2D 坐标系里的位置**（组件在组件面板/画布上的落点），**不是世界的 2D 尺寸**。
- 与 P03 的独立判决一致：`size-entry.json` 把 `get_Bounds → System.Windows.Rect`、
  "exposes xPos/yPos, itemType=2, ZIndex=0" 的那个类型判为
  **"2D editor tree/UI item rectangle, not prefab 3D bounds"**。

### 1.3 真实记录值：1196 条组件记录里 `x=y=0.0`（穷举）

`prefab-fields-page` 的**三个真实回执**（194 预制 / 1196 条组件记录）里，逐条跟踪组件字段的 refId：

| 字段 | 真实值分布（1196 条） |
|---|---|
| `OgoXdqFmidJ`（组件类型 id） | `1`→194、`3`→194、`18`→191、`6`→191、`14`→190、`19`→157 … **唯一被填充的字段** |
| `gKyXdGplIdw`（启用） | `false` → **1196 / 1196** |
| **`rNIXd7Mpstc`（x）** | `System.Double, bits=0000000000000000` → **1196 / 1196** |
| **`f3VXda70g6Z`（y）** | `System.Double, bits=0000000000000000` → **1196 / 1196** |

（证据：`.runtime/editor-bridge/runs/{8c515535-66ae-4ef6-8552-fa27432f1a0c,ce2f82fd-cc34-43e1-9e8a-7e9b64cb4035,c980a8f9-f8de-462b-8b30-1f46a2a00c77}/prefab-fields-page-response.json`。
单条结构：组件对象 `{objectId:9, type:"…CF9E4JXdL1Cq4xrMUnCq", fields:[{name:"rNIXd7Mpstc", value:{refId:13}}…]}`，
refId 指向 `{…"dataField":"PIWXZgk5Tyr","value":{"scalarType":"System.Double","bits":"0000000000000000"},"scope":"stored-business-value"}`。）

**⇒ 第一问判决**：`xPos`/`yPos` 是 **2D 位置**（不是 2D 尺寸）；且它在**真实预制的组件上从不被填充**
（1196/1196 为 0.0）。**它给不出模板尺寸，两个方向都堵死**（语义不对 + 值恒 0）。

---

## 2. 题面第二问：预制目录回执带不带 size/bounds/collision 字段？

### 2.1 `prefab-catalog` —— 真实回执只有 4 个字段（逐键核对）

- **源码**（`tools/editor-bridge/Adapter/SceneCatalog.cs:117-119`）：每条 `{registryId, name, iconPath, nativeKind}`；
  返回体 `:122-131` 只有 `total/truncated/prefabs/nativeMethodsInvoked/…`。**无任何尺寸/包围盒/碰撞字段。**
- **真实回执**（`.runtime/editor-bridge/runs/25f78b1b-f00a-45b6-b9eb-c262b049e8a4/prefab-catalog-response.json`，
  以及 `5211c08b-…`）：顶层键 `[ok,status,total,truncated,prefabs,nativeMethodsInvoked,sentToGame,persistentSaveVerified,playtestVerified]`，
  `prefabs[0]` 键 `[registryId,name,iconPath,nativeKind]`。**源码与回执逐键一致。**

### 2.2 `prefab-fields` / `prefab-fields-page` —— 也不带尺寸

- 浅读 `prefab-fields`：`MaxDepth=3`（`Adapter/PrefabFieldRead.cs:13`），真实回执 `rowCount=16, depthLimitReached=true`
  —— 连组件都读不到，更无几何（`PREFAB-FIELDS-MINE.md` §3.1）。
- 深读 `prefab-fields-page`：能给**组件类型集合**（`OgoXdqFmidJ` 编号），但**组件参数全是 0**（§1.3），
  且 194 预制的 2310 个浮点叶子**全 0.0**（`PREFAB-FIELDS-MINE.md` §4.3）。

### 2.3 穷举式负面：预制模型**根本没有 float/double 字段**

这不是"读出来是 0"，而是"字段清单里没有"。pinned 元数据里预制模型类型
`zDWuCYXAIGplUjEgOhcg.xvBUJOxABeOPt0cFA00U`（由字段 `OT7XAkHtROh` 的类型 `…CF9E4JXdL1Cq4xrMUnCq`
反查得到）的**全部字段**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- **17 个字段里没有一个 `System.Single` / `System.Double`。** 唯一能看到浮点的地方，是
  `I9VXA37srDJ` 的元素 `o8mxuBXAmGK9Yy8mi5fX.swwD99XARcZ8ktwq6yoO` 里那个
  `BeyondEditor.BaseUtil.Transform`——而 `Transform` **只有 3 个向量字段**（`metadata-7.1.json`：
  `wC4LYjKf2kq/msVLYQ9sfud/fyZLYp81CQN`，即 position/rotation/scale），**没有尺寸/半长字段**。
- 反查的其余类型（`GL3iQaXn10FDkUwcfAJh`：5 个 uint + 1 个 object；`BphbcZZOuXGqS8UndAxF`、
  `OEMSxbZOTRB79YVvftOi`、`CAo8WOZZGKMTDVh419Py`：纯枚举）**也都没有浮点字段**。

**⇒ 第二问判决**：目录回执**不带**尺寸/包围盒/碰撞字段；编辑器预制模型**在字段层面**就没有尺寸字段。
（范围：pinned 元数据 + 3 页面真实回执。**不是**对"游戏侧别的接口"的否定。）

---

## 3. 题面第三问：原生侧有没有"读实体世界包围盒"的探针？

**没有。** 逐条：

| 事实 | 出处 |
|---|---|
| 原生快照结构里**有** `float position[3]` 槽位，但注释明说 **"GE_POSITION_READ is never set: no proven position offset"** | `tools/game-executor/native/game_context_snapshot.h:81` |
| `GameEntityFlags` 里 `GE_POSITION_READ = 16` **定义了但从不置位** | 同文件 `:59` |
| 快照只读**位置都没有**（没有 offset），更没有包围盒/碰撞盒 | 同文件 `:107`（"In-process, read-only…"） |
| `size`/`bounds`/`collider`/`extent`/`AABB` 在 `tools/game-executor/native/` 全目录 **0 命中** | Bash `grep -rn -i "bounds\|collider\|extent\|aabb\|GetSize" tools/game-executor/native/`（仅命中调度器 `SchedulerBounds` 与 `contextEntries` 等无关词） |
| `scene_calls.h` 的 `Vec3 position/rotation/scale` 是**建实体的入参**（`place_builtin` 的 `PlacementInput`），**不是读回**；返回只有 `local_position`（入参减 context 原点） | `tools/game-executor/native/scene_calls.h:9-19,30-41`；`scene_calls.cpp:21-25` |
| 组件容器偏移 `0x1182cea0` / `component+0x30`（**旧记号**：`0x1182cea0` 是 walk 的**函数 RVA**、非容器**偏移**；`component+0x30` 非游戏侧 kind——kind 在 `[comp+0x34]`，容器是 `[entity+0x68]`；见 `reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`）在原生 C++ 里 **0 命中**（只活在研究文档的静态分析里） | `COMPONENT-WRITER-MINE.md` §6.1 |

**⇒ 第三问判决**：**没有**任何原生探针能读实体的位置，遑论世界包围盒。原生侧**不是**候选。

---

## 4. 交付：尺寸**可能**从哪来（全部地点 + 证据 + 谁最省）

| # | 来源 | 是"尺寸"吗 | 证据 | 状态 |
|---|---|---|---|---|
| 1 | 组件模型 `xPos`/`yPos`（两个 double） | **否**（是位置） | §1.1-1.3（属性名 + 7 类型穷举 + 1196 条真值 0.0） | **关死** |
| 2 | `prefab-catalog` 回执 | 否（无此字段） | `SceneCatalog.cs:117-119` + 真实回执键 | **关死** |
| 3 | 编辑器预制模型 bounds 字段 | 否（无此字段） | §2.3（17 字段无浮点，穷举） | **关死** |
| 4 | `prefab-fields`（浅读） | 否 | `PrefabFieldRead.cs:13`（深度 3 截断） | **关死** |
| 5 | `prefab-fields-page`（深读） | 否（参数全 0） | `PREFAB-FIELDS-MINE.md` §4.2-4.3 | **关死** |
| 6 | 编辑器 registry transform 缓存 | 否（`authoritative=false`，全 0） | `SceneCatalog.cs:71-76`；`GEOMETRY-THREE-WAYS.md` §0 | **关死** |
| 7 | 原生快照 / 探针 | 否（无位置、无包围盒） | §3 | **关死** |
| 8 | UI 树项 `get_Bounds → System.Windows.Rect` | 否（编辑器 2D 矩形） | `size-entry.json`（"not prefab 3D bounds"） | **关死** |
| 9 | `.gil` 里的 per-instance `position/rotation/scale` | 否（**逐实例**变换，非模板固有尺寸） | `GEOMETRY-THREE-WAYS.md` §0；`gil_container.py` 无尺寸字段 | **不是模板尺寸** |
| 10 | 社区 `block_config.py size_units`（1.0 / 5.0） | 数字像，但**声明未测量** | `measure.py:114-145`；`mvp/calibration/README.md:24` | **未测量，不许当尺寸** |
| 11 | **1017 报文的形状组件（shape 11/12/13）** | **是（碰撞盒尺寸原语）** | 见 §4.1 | **开放但未观测到真值** |
| 12 | 真机 place-at-scale-1 读回 `.gil` | 是 | `measure.py:76` 自述 | 是**写**动作，非只读 |

### 4.1 唯一的"真尺寸原语"：1017 形状组件（**最省的候选**）

**工具能做什么**（离线源码，`Adapter/Geometry1017Fields.cs:131-143`，读的是**实际收到的 1017 资源增量报文**）：

| shapeTag | 字段（raw 名） | 语义（由 annotated-71 语料的**可读属性名**给出） |
|---|---|---|
| **11** | `g9TIvItdMaI` → **`Center`**；`nEAIvOgur3Q`/`LVOIvZgWTml` | Center + **两个仍未命名**的向量（疑长方体各轴缩放） |
| **12** | `j2oIvavAydA` → **`Center`**，`NiQIvG2oBi3` → **`Radius`** | **球：Center + Radius** |
| **13** | `U73IvWcPitT` → **`Center`**，`dM0IvbHmEi1` → **`Radius`**，`oc6IvhFZt6m` → **`Height`**，`LIoIv6HlWYi` → **`Direction`** | **胶囊：Center + Radius + Height + Direction** |

**三层互证**：

- **源码层**：`Geometry1017Fields.cs:137` 读 shape12 的 `NiQIvG2oBi3` 作 `radiusBits`；`:140` 读 shape13 的
  `dM0IvbHmEi1`（radius）+ `oc6IvhFZt6m`（height）。**字段名逐一吻合**。
- **反注释层**：`.runtime/verification/docs-71-20260926/annotated-71/wnrea0IvLljM8RmsSL1L.uAJLoKIvw3tLthqip8Tt.cs:34-57`
  该类型属性名即 **`Center` / `Radius`**；`…FaCYDUIvdFSoabpaXQkd.aFOhchIvvTlmD1qnjYVT.cs:40-102` 属性名即
  **`Center` / `Radius` / `Height` / `Direction`**（另有一个仍混淆的 `Yk1Iv4w7TBJ`）。⇒ 那两个 float 的**语义就是半径/高度**，
  不再是"裸 bit"。
- **文档层（官方知识库）**：`.runtime/research-sources/official-docs-expanded/mh1ytk9631fm.txt`
  —— `:19` "操控实体碰撞定义了操控实体的**碰撞盒大小**"；`:22` "推荐碰撞区形状使用**胶囊体或球体**"；
  `:48` "**长方体**：碰撞配置形状在不同轴向上支持自定义缩放"；`:49` "**球体**：…通过**半径**配置统一缩放"；
  `:50` "**胶囊体**：…通过**半径和高度**配置自定义缩放"。⇒ 官方文档把 shape 11/12/13 的三个形状与"半径/高度"逐字点名。

**为什么它还不是"现成来源"（三段硬约束）**：

1. **从未取到真值**。两次真机 1017 抓包——
   `.runtime/editor-bridge/runs/e117c900-0956-4ec4-8930-9ba0a179eaed/log-observer-evidence-response.json`
   （`protoCount:128, componentCount:770, geometryComponentCount:0, rows:[]`）与
   `…/0cf0e119-6a61-460c-87c8-7f54573e2167/…`（`protoCount:0`）——`geometryComponentCount` **都是 0**。
   即**抓到过含 770 个组件的真报文，但 0 个 tag-18 几何组件**，所以 `Radius`/`Height` **一个真值都没落过盘**。
   （`Geometry1017Fields.cs:37-40` 也自述 `geometryComponentCount=0` 可能是前缀 cap 截断所致——所以这既是"没观测到"，
   也**不能**反推"游戏里没有"。）
2. **没有 id 映射**。1017 报文的 `rawProtoId`（字段 `wpnIFzGZt4k`，`:114`）**没有**到编辑器 `registryId` 的转换/相等校验
   （`.runtime/verification/interface-experiments-20260927/p03/geometry-candidate/proto-resource-mapping.json`
   → `status:"mapping-and-shape-semantics-unresolved"`，`gaps:["rawProtoId-to-resourceId conversion/equality or lookup mapping"]`）。
   ⇒ 即便读到半径，也**不知道它属于哪个模板**。
3. **语义边界**。`worldBoundsVerified:false` / `geometryVerified:false` / `collisionKindMappingVerified:false`
   在**每一次**真实 observer 回执里都恒为 false（同上两文件）。而且它是**碰撞盒**尺寸，**不必然是"视觉足迹"**
   （网格间距要的可能是模型外形）。

### 4.2 最省的下一步（一句话）

**在已存在、已解码的 `Geometry1017Fields` 上，抓一次"含 tag-18 几何组件"的 1017 报文**——这是唯一
"代码已就绪、只差一份真样本"的候选（相比之下 §4 的 1-9 是"字段不存在"，10 是"未测量"）。
在拿到 `Radius/Height` 真值**之前**，`asset.measure` 的诚实答案仍是 `None`（见 `tools/gameplan/measure.py:187-206`）。

**负结论（本次检索范围内）**：**离线**不存在任何"给模板 id、返回尺寸"的现成来源；
**`asset.measure` 返回 `None` 是对的**，不是 stub。

---

## 5. 证据索引（本次 checkout / 本次语料实测）

| 论断 | 证据 |
|---|---|
| `measure.py` 唯一入口读空表、缺席即 `None` | `tools/gameplan/measure.py:105`（`MEASURED_TILE_SIZES={}`）、`:187-206`、`:209-232` |
| 组件三套名字（71/legacy/属性） | `metadata-7.1.json`（`tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq` 的 fields/properties）；`.runtime/editor-catalog/resolved/taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:12-18,22-24` |
| 桥侧组件探针读 x/y（**已编译，未真机**） | `tools/editor-bridge/Adapter/EntityComponentProbe.cs:28-31,154-155` |
| 全表只有 7 个类型带 `xPos`；"大小"另用 width/height | `metadata-7.1.json` 全表扫描（15654 类型） |
| `xPos/yPos` 是被 P03 判为 UI 2D 矩形的那一族 | `.runtime/verification/interface-experiments-20260927/p03/geometry-candidate/size-entry.json` |
| 1196 条真实组件 x/y 恒 0.0 | `.runtime/editor-bridge/runs/{8c515535…,ce2f82fd…,c980a8f9…}/prefab-fields-page-response.json` |
| `prefab-catalog` 回执字段 | `tools/editor-bridge/Adapter/SceneCatalog.cs:117-119,122-131`；`.runtime/editor-bridge/runs/25f78b1b-f00a-45b6-b9eb-c262b049e8a4/prefab-catalog-response.json` |
| 预制模型 17 字段无浮点 | `metadata-7.1.json`（`zDWuCYXAIGplUjEgOhcg.xvBUJOxABeOPt0cFA00U`） |
| `Transform` 只有 3 向量 | `metadata-7.1.json`（`BeyondEditor.BaseUtil.Transform`） |
| 深读 194 预制浮点全 0、组件参数全 0 | `PREFAB-FIELDS-MINE.md` §4.2-4.3 |
| 原生无位置偏移/无包围盒 | `tools/game-executor/native/game_context_snapshot.h:59,81,107`；`scene_calls.h:9-19,30-41` |
| 1017 形状 tag 11/12/13 字段 | `tools/editor-bridge/Adapter/Geometry1017Fields.cs:116-143` |
| 形状语义 = Center/Radius/Height/Direction | `.runtime/verification/docs-71-20260926/annotated-71/wnrea0IvLljM8RmsSL1L.uAJLoKIvw3tLthqip8Tt.cs:34-57`；`…FaCYDUIvdFSoabpaXQkd.aFOhchIvvTlmD1qnjYVT.cs:40-102` |
| 官方文档把三形状与半径/高度点名 | `.runtime/research-sources/official-docs-expanded/mh1ytk9631fm.txt:19,22,48-50` |
| 1017 真机抓包 `geometryComponentCount=0` | `.runtime/editor-bridge/runs/e117c900-0956-4ec4-8930-9ba0a179eaed/log-observer-evidence-response.json`（770 组件 / 0 几何）；`…/0cf0e119-6a61-460c-87c8-7f54573e2167/…` |
| `rawProtoId→registryId` 映射未证 | `.runtime/verification/interface-experiments-20260927/p03/geometry-candidate/proto-resource-mapping.json` |
| 社区 size_units 是未测量假设 | `tools/gameplan/measure.py:114-145`；`mvp/calibration/README.md:24` |

---

## 6. 方法 / 范围诚实声明

- **未连接桥、未发报文、未启动/触碰游戏或编辑器、未写任何存档**；只读仓内源码、仓内真实回执、反注释语料与 pinned 元数据。
- **离线测试**：`PYTHONIOENCODING=utf-8 python -B -m unittest tools.gameplan.tests.test_measure -v`
  → **13 tests, OK**（0.001s）。本文件**未改动** `measure.py` 或任何测试。
- 凡"穷举"字样（§1.2 的 7 个类型、§2.3 的 17 个字段、§1.3 的 1196 条），均指**本次 checkout 的
  `metadata-7.1.json`（15654 类型）与三份真实 page 回执**这一确定范围内，并已写明范围。
- **"搜不到"≠"不存在"**：§2.3/§3 的负面只对**编辑器程序集 / 原生探针源码**成立；
  游戏侧 `global-metadata.dat` 加密（`size-entry-lowercase.json:45`），**磁盘字符串命中 0 不能排除游戏侧符号**。
