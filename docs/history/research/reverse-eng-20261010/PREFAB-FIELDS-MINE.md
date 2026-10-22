> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #5 挖 — prefab-fields：桥已有的那个 op 能读到什么

**产出日期**：2026-10-10。位置：`docs/research/reverse-eng-20261010/PREFAB-FIELDS-MINE.md`。
**口径**：**纯离线、纯只读**。全程**未连桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。证据只有三处：
① 仓内 C# 源码 ② 仓内**真实回执 JSON**（`.runtime/editor-bridge/runs/*/`，用 Bash `grep`/`python` 查，
**Grep 工具会静默跳过 `.runtime/`**）③ 反编译语料 `.runtime/editor-catalog/resolved/`。
**本文件只读不写**，仅新增本文件本身。

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么`（离线源码）/ `真机验证过什么`（真实回执）**
> 三层分开标。本文的"工具能做什么"来自源码，"真实回执"来自 `.runtime` 里抓下来的 JSON。
> 凡"搜不到"的地方都写明**检索范围**；**"搜不到"≠"不存在"**。

---

## 0. 一句话结论

**三个 prefab op 里，只有 `prefab-fields-page` 那一个"深读版"能读出预制（prefab）的组件清单——
以组件类型枚举名（`BeyondCompTypeCombat` / `BeyondCompTypeHitbox` / …）返回；但它给出的组件参数值
全是 0、而且没有任何几何/碰撞尺寸数字。浅读版 `prefab-fields` 连组件都看不到（深度 3 就截断）。
两个 op 都只是"读"，都不构成写原语。**

- 与"组件工作"的关系：**`prefab-fields-page` 就是组件读的"预制一侧"**——
  它把若干预制的**组件类型集合**读出来了（正是 `COMPONENT-WRITER-MINE.md` §7 想要的
  `componentId` 编号坐实）。但它是**读预制**，不是**读实体**；且只给"有哪些组件"、不给"组件怎么配"。
- 与"几何"的关系：**没有**。深读对 128 个预制的**全部 2310 个 float/double 叶子读出的都是 0.0**，
  读回 `readSummary.complete=true, errorCount=0`（不是被截断、不是跳过子树）⇒ 预制模型里**根本不带几何数字**。

---

## 1. op 在源码里的位置与接线（工具能做什么）

三个 op 的标签与派发都在 `tools/editor-bridge/ManagedBridge/BridgeServer.cs`：

| op | case 标签 | 派发 |
|---|---|---|
| `prefab-fields-page` | `BridgeServer.cs:469` | `_adapter.PrefabFieldsNext(Path.Combine(_directory,"prefab-resume.json"))`（`:519`） |
| `prefab-fields` | `BridgeServer.cs:470` | `_adapter.PrefabFields()`（`:521`） |
| `prefab-catalog` | `BridgeServer.cs:471` | `_adapter.PrefabCatalog()`（`:523`） |

三者都走同一个 `_adapter`、同一个 WPF dispatcher 分支（`BridgeServer.cs:510-523`）。

**op 取什么参数？——不取。** 请求信封只有 `{id, op, nonce}`（`tools/editor-bridge/call-bridge.ps1:25`），
这三个 op **既不吃 `ids` 也不吃自由参数**（对比 `node-definitions` 用 `ReadUintArray(root,"ids")`，
`BridgeServer.cs:311`）。`prefab-fields-page` 是**有状态、单向分页器**：每调一次前进一页，
续跑靠 `prefab-resume.json`（`BridgeServer.cs:519`）。三个 op 的响应超时都放宽到 60 s（`call-bridge.ps1:47`），
响应写盘为 `<runDir>/<op>-response.json`（`call-bridge.ps1:51`）——这正是证据文件名的由来。

---

## 2. 三个 op 各自"取什么、回什么"（源码字段形状）

### 2.1 `prefab-fields` —— 浅读版（**读不到组件**）

实现：`tools/editor-bridge/Adapter/SceneCatalog.cs:163-193`（`PrefabFields()`），走
`Adapter/PrefabFieldRead.cs` 的有界投影。

- **取什么**：不取参数。硬编码一张**11 个 id 的标定表** `PrefabFieldCalibration`
  （`SceneCatalog.cs:148-160`，注释说明 20001875=通常立方体 1.0 单位、20001034=石质元素立方体 5.0 单位、
  外加乔木/灌木/路灯/石柱/岩石/地板/围栏/火炬）。对这些 id 在 `prefabModels` 里逐个找模型。
- **怎么读**：`new PrefabFieldRead().Read(model)`（`SceneCatalog.cs:171-172`），
  **只读字段、绝不调原生 getter/枚举器**（`PrefabFieldRead.cs:10`）。
- **有界投影的硬上限**：`MaxDepth=3, MaxCollectionItems=4, MaxScalarRows=90`
  （`Adapter/PrefabFieldRead.cs:13`）。
  叶子的白名单是**运行时标量**：`IsPrimitive / string / IsEnum / decimal`（`PrefabFieldRead.cs:37-42`）；
  集合只认**精确的** `T[] / List<> / Dictionary<,> / HashSet<>`（`PrefabFieldRead.cs:23-29,44-60`）；
  其它 `IEnumerable` **不枚举逻辑元素**、只走实例字段，并记 `UnknownEnumerableFieldWalkCount`
  （`PrefabFieldRead.cs:61-71`）。深度到 3 就 `DepthLimitReached=true`（`PrefabFieldRead.cs:43`）。
- **回什么**：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  （`SceneCatalog.cs:173-192`）。行 `path` 以 `"m."` 开头（`PrefabFieldRead.cs:31` 的根 path 常量 `"m"`）。

### 2.2 `prefab-fields-page` —— 深读版（**能读到组件清单**）

实现：`tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs:36-167`（`PrefabFieldsPageCore`），
内部用 `Adapter/ReopenContentEvidence.cs:17-115` 的 `ContentFieldReader`。

- **取什么**：`{offset, size}`，`size∈[1,128]`（`PrefabCollectionEvidence.cs:39-43`，
  `PrefabPageMaxSize=128` 见 `:30`）；**桥 op 入口不暴露这两个参数**，入口
  `PrefabFieldsNext`（`:171-180`）自己推进 offset，用缓存保证重复页幂等（`:50`），
  并要求**必须从 offset 0 起**（`:53`）。首次调用做一次全注册表扫描（按 id 去重、排序，`:57-66`），
  之后每页最多跑 2000 ms 就让位给 WPF（`PrefabPageTimeSliceMs`，`:31,144`）。
- **续跑**：读 `prefab-resume.json`（schema 1 / `catalogIdsSha256` / `completedIds`，`:67-92`），
  校验该文件里登记过的 id 与本快照目录 hash 一致才允许跳过。字段 `reusedFieldsRevalidated` 恒为 `false`（`:157`）。
- **怎么读**：对每个模型取 `name/iconPath/nativeKind`，再用
  `new ContentFieldReader(editor).Read(model)` 深走一遍（`PrefabCollectionEvidence.cs:118-127`）。
  `ContentFieldReader` 的上限：`MaxObjects=65536, MaxItems=16384, MaxDepth=48, MaxBytes=8MB`
  （`ReopenContentEvidence.cs:20`）。标量规则（`:45-52`）：`string` 原样、`byte[]`→base64、
  `float`→`{scalarType,bits:x8}`、`double`→`{scalarType,bits:x16}`、枚举→底层值。
  **关键**：有 5 个 `MoivF7XZA3MetiaLJVSU<T>` 之类的"存值包装"泛型被映射到各自 data 字段，
  读成 `{objectId,type,dataField,value,scope:"stored-business-value"}`（`ReopenContentEvidence.cs:60-66`）；
  只枚举精确的 `List<>/HashSet<>/Dictionary<,>`（`:75-88`）；**其它 `IEnumerable` 一律
  `Fail("UNVERIFIED_ENUMERABLE:…")`**（`:97-98`）；并且**在公共模型基类
  `hnRX5SXOfpHoFMcisZBH.sSJI8CXOTXcMB9gP3URF` 处停**（`:104`，排除通知/订阅者/undo 记账）。
- **回什么**：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  （`PrefabCollectionEvidence.cs:152-164`）。

### 2.3 `prefab-catalog` —— 目录（只有名字/图标）

`SceneCatalog.cs:103-132`（`PrefabCatalog()`）：返回 `{registryId, name, iconPath, nativeKind}`，
上限 4000 条（`PrefabCatalogLimit`，`:101`）。**不含任何组件/几何字段。**

---

## 3. 真实回执（真机验证过什么）

### 3.1 `prefab-fields` 的真实回执（存在，已引用）

文件（都在 `.runtime/editor-bridge/runs/` 下）：

| 路径 | 字节 | 备注 |
|---|---|---|
| `dfce87d6-3ba5-49e5-a556-6b8c7ba33da0/prefab-fields-response.json` | 19 023 | **最新**，带 `limits`，11 个标定预制，`truncated:true` |
| `3c8bb767-b994-42d9-89f2-e4292ed6a681/prefab-fields-response.json` | 16 850 | 带 `limits`/`truncated:true` |
| `25f78b1b-f00a-45b6-b9eb-c262b049e8a4/prefab-fields-response.json` | 15 607 | **旧版**：无 `limits`，`truncated:false` |
| `3472b1eb-c56e-4353-bffd-8c43234bb615/prefab-fields-response.json` | 15 607 | 同旧版 |

`dfce87d6` 的顶层（原文摘录，`\uXXXX` 是原始转义）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**读出来的只有 16 行，全是模型顶层的标量**（资源键 `zUrXNpgNbru=10007`、自身 id `L0kXNqYb39f`、
名字 `FgdXA6xO0YB`、图标 `e2gXAHxV6lu`/`MtaXAyf9PbV`、两个枚举 `wyIXArmnb7j=1402` / `q1JXA0enyOS=Normal`
等）。`depthLimitReached:true` 且 `collectionLimitReached:true` ⇒ **组件清单在更深一层，根本没走到**。

> ⚠️ **三层对齐提醒**：`docs/ds-handoff/06-INTERFACE-VERIFICATION-QUEUE.json` 把
> `project:bridge:prefab-fields` 标成 `source-route-only` / `priorEvidenceIds:[]`（该文件 :2899-2914），
> 把 `prefab-fields-page` 标成 `related-bounded-evidence`。**那是"队列作者当时没挂上证据"，不是"没有回执"**——
> 回执就在上面那些 `runs/*/…-response.json` 里。这正是 `CLAUDE.md` §一.2「搜不到≠不存在」的一个实例。

### 3.2 `prefab-fields-page` 的真实回执（存在，已引用）

| 路径 | 字节 | offset | nextOffset | items | catalogTotal | done |
|---|---|---|---|---|---|---|
| `8c515535-66ae-4ef6-8552-fa27432f1a0c/prefab-fields-page-response.json` | 7 603 537 | 0 | 128 | 128 | 2722 | false |
| `ce2f82fd-cc34-43e1-9e8a-7e9b64cb4035/prefab-fields-page-response.json` | 1 896 618 | 992 | 1024 | 32 | 2722 | false |
| `c980a8f9-f8de-462b-8b30-1f46a2a00c77/prefab-fields-page-response.json` | 2 278 274 | 1664 | 1698 | 34 | 2722 | **true** |

`c980a8f9` 还带续跑文件 `prefab-resume.json`（schema 1、`catalogIdsSha256=4525841d…`、
`completedIds` 一长串），回执里 `resumeApplied:true, reusedResourceCount:1024`。
**这三个文件一共覆盖 194 个预制**（按 item 去重）。

实测 `prefab-fields-page` 的 `readSummary`：**194 个 item 全部 `complete:true`、`truncated:false`、
`errorCount:0`**（`visitedValues` 最大 409）。也就是说深读**没有被截断、没有碰到
`UNVERIFIED_ENUMERABLE`**——下面"参数全是 0"的结论不是"某子树被跳过"造成的。

`8c515535` 的 item 形状（首个 item 实读）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 4. 返回字段里到底有没有 COMPONENTS / 几何 / 碰撞 / 交互配置

### 4.1 COMPONENTS —— **有**（只在深读版 `prefab-fields-page`）

预制模型 `zDWuCYXAIGplUjEgOhcg.xvBUjOXABeOPt0cFA00U` 上有一个字段 `OT7XAkHtROh`，指向
`List<tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq>` —— **这就是组件表**。
每条组件记录的字段 `Sf4Xdtq9Squ`（string）= **组件类型枚举名**，字段 `OgoXdqFmidJ`（UInt32）= **同一个类型的数值 id**。

数值 id 与反编译里的 46 项枚举（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2）**逐项吻合**
（`.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49`：
`BeyondCompTypeCustomValue=1`、`Timer=3`、`Effect=6`、`Collision=8`、`RoleStatus=14`、`Combat=18`、
`Hitbox=19`、`Shop=35`、`StuffBag=33` …）。以 `石质尖刺平台`（registryId 10005001）为例，实读到的
6 条组件记录 `OgoXdqFmidJ` = `18,1,3,19,6,14`，与 `Sf4Xdtq9Squ` = `Combat,CustomValue,Timer,Hitbox,Effect,RoleStatus` **一一对应**。

**三个 page 文件里 194 个预制，共读到 16 种组件类型**（次数）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


（注意：这些是**预制**的组件，不是某个实体实例的组件。`Collision(8)`/`Obstacle(41)`/`Shop(35)`
等在**这批 194 个预制里一次都没出现**——不能据此说它们不存在，只能说**本次检索范围（3 页 / 194 预制）内未见**。）

### 4.2 组件参数 —— **没有值**（全是 0/None/False）

在上述 `石质尖刺平台` 的组件记录里，除 `OgoXdqFmidJ`（类型 id）与 `Sf4Xdtq9Squ`（类型名）外，
其余字段读出来全是 `0 / False / None`，例如 `f3VXda70g6Z(System.Double)=0`、`gKyXdGplIdw(Bool)=False`、
`F2xXkzqKsxa(Single)=0`、`gAcXkKtSVTJ(UInt32)=0`、`xhyXky634Kl(Int32)=0`。

**量化验证**：把全部 3 个 page 文件里 **1196 条组件记录**展开，
其**非零数值叶子只有组件类型 id 一个字段**（计数：1→194、3→194、18→191、6→191、14→190、19→157、
26→32、42→32、43→3、44→3、11/12/20/22/32/40 各 1~2），**其它数值全是 0**。

### 4.3 几何 / 碰撞尺寸 —— **没有**

- 深读对 128 个预制的**全部 2310 个 float/double 叶子，读出的都是 `0.0`**
  （float 以 `bits` 十六进制给出，解出来全零；`readSummary.complete=true` 已排除"被跳过"）。
- 顶层没有 `Vector3` 之类的三分量字段被读出值。`K8VXAFBM2vy`(`List<int32>`) 与
  `QHVXA9w88lF`(`List<GL3iQaXn10FDkUwcfAJh>`) 在样本里是 `count:0` 空表。
- 组件里虽含 `Hitbox(19)`（碰撞体近亲）与潜在 `Collision(8)`，但**它们的尺寸/形状数字一个都没落进预制模型**。

### 4.4 交互配置 —— **只有"有没有"，没有"怎么配"**

`PopUp(40)`、`MinimapMark(32)`、`CustomSkill(22)`、`BulletMove/Pattern/Detection(11/20/12)`、
`CustomValue(1)`、`Timer(3)` 这些本身就是交互/逻辑组件。深读能告诉你**某预制挂了哪个交互组件**，
但和 4.2 一样，**参数值读不到**。

### 4.5 与"1017 几何读"的区别（别混）

`Adapter/Geometry1017Fields.cs:9-24` 是**另一条**读几何的路：它读的是**实际收到的 1017 资源增量报文**
（tag-18 = geometry 组件），取 shape/vector 字段（`:116-143`）。它是 **DRAFT、需要调用方喂一个真实 1017 报文、
本轮未跑**（`ComponentGeometryEvidence` 里 `geometryComponentCount:0` 是历史观测）。
**`prefab-fields` 与这条 1017 路无关**：前者读的是编辑器内存里**已物化的预制模型**，后者读的是**报文**。

---

## 5. "读"能不能驱动模块半边（读能带来验证，这是真实一步）

**能，但只到"成员/编号"这一层，到不了"参数/几何"。** 具体：

1. **组件类型编号坐实（最直接的一条）**。`COMPONENT-WRITER-MINE.md` §0 把
   "最省的第一刀"定为：**只读读回组件集合、把 `componentId` 的编号坐实**。
   `prefab-fields-page` **已经**用真机数据给出了"**名字 ↔ 数值 id**"的对应
   （`Combat↔18`、`Hitbox↔19`、`Timer↔3`、`Effect↔6`、`RoleStatus↔14`、`CustomValue↔1`…），
   且与离线反编译的 46 项枚举（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2）**互证**。这直接服务 M1（碰撞/控件）、以及六模块里**组件配置那一半**的编号前提。
2. **预制的默认组件集 = 实体组件的验证基线**。任何由某预制创建的实体，理论上应带上该预制的默认组件集
   （`prefab-fields-page` 已经把每个预制的默认组件集读出来）。**读 enables verification**：
   建实体后可以拿"预制默认组件集"当期望值去比对实体侧读回值——本轮**没有**做这个比对（无真机动作）。
3. **预制选材**。`prefab-catalog`（2722 条，`name/iconPath`）已经用于选材（见
   `docs/ASSET-INVENTORY-FARMING.md`）。`prefab-fields` 的标定行（`10007` 资源键样板 + 名字 + 图标）
   可作为"这个预制是不是地块/道具"的判据之一。
4. **到不了的地方（明确负面）**：
   - **组件参数值**读不到 ⇒ 无法用读去核 M2 货币/M3 道具/M4 背包/M5 商店的**配置数值**。
   - **几何/碰撞尺寸**读不到 ⇒ 无法用读去核 transform/碰撞体；几何只能走 `.gil`（field 1/2/3）或 1017 报文。
   - **没有写原语**：这三个 op 全是只读，`sentToGame:false`（`SceneCatalog.cs:192`、
     `PrefabCollectionEvidence.cs:159`）——读再多也不会变成"能加/能改组件"。

---

## 6. 负面结论 & 若要一份更全回执，那一条命令

**负面（本次检索范围内确证）**：

- `prefab-fields`（浅读）**不可能**给出组件或几何：`MaxDepth=3`（`PrefabFieldRead.cs:13`），
  组件表在 `List<…>` 里位于深度 ≥3 且被 `MaxScalarRows=90`/`MaxCollectionItems=4` 夹住，
  实读 `rowCount=16, depthLimitReached=true`。
- `prefab-fields-page`（深读）**给出组件类型集合、但不给参数与几何**：194 个 item 全 `complete:true`、
  `errorCount:0`，组件记录非零数值只有类型 id，全部 float/double 叶子 = 0。
- 两 op 均**不落盘、不发游戏**（`sentToGame:false`），也不构成写入原语。
- `prefab-fields-page` 的桥入口**不吃参数**（`BridgeServer.cs:519` 不读 `root` 的任何字段）；
  想换 offset 只能靠它的内部游标 + `prefab-resume.json`。

**要产出新回执的那一条命令**（本轮**不执行**，仅记录；沿用已有 run 目录的 scope）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


要拿"全部 2722 个预制"的组件清单，就是反复调上一条直到 `done:true`（参考 `c980a8f9` 的
`resumeApplied:true` 续跑路径）。要拿浅读标定表，把 `Operation` 换成 `prefab-fields`。

---

## 7. 引用表（本次 checkout / 本次 resolved 语料实测行号）

| 论断 | 证据 |
|---|---|
| 三 op 的 case 标签 | `tools/editor-bridge/ManagedBridge/BridgeServer.cs:469-471` |
| 三 op 的派发与 resume 路径 | `tools/editor-bridge/ManagedBridge/BridgeServer.cs:518-523` |
| 请求信封只有 id/op/nonce（op 不吃参数） | `tools/editor-bridge/call-bridge.ps1:25` |
| prefab 三 op 超时 60s | `tools/editor-bridge/call-bridge.ps1:47` |
| 响应写盘 = `<op>-response.json` | `tools/editor-bridge/call-bridge.ps1:51` |
| 标定表 11 个 id | `tools/editor-bridge/Adapter/SceneCatalog.cs:148-160` |
| `PrefabFields()` 返回形状 | `tools/editor-bridge/Adapter/SceneCatalog.cs:163-193` |
| `PrefabCatalog()` 返回形状 / 上限 4000 | `tools/editor-bridge/Adapter/SceneCatalog.cs:101-132` |
| 浅读上限 `MaxDepth=3/MaxCollectionItems=4/MaxScalarRows=90` | `tools/editor-bridge/Adapter/PrefabFieldRead.cs:13` |
| 浅读标量白名单 / 集合白名单 / 未知 IEnumerable 不枚举 | `tools/editor-bridge/Adapter/PrefabFieldRead.cs:37-42,23-29,44-71` |
| 深读分页参数 `{offset,size}` / 页上限 128 / 时间片 2000ms | `tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs:39-43,30-31` |
| 深读 item 形状（含 `content`+`readSummary`） | `tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs:118-127` |
| 深读返回体 / `geometryVerified:false` / `sentToGame:false` | `tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs:152-164` |
| `PrefabFieldsNext` 单页游标 + 幂等缓存 | `tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs:171-180` |
| `ContentFieldReader` 上限 65536/16384/48/8MB | `tools/editor-bridge/Adapter/ReopenContentEvidence.cs:20` |
| 标量规则（float→bits:x8 / double→bits:x16） | `tools/editor-bridge/Adapter/ReopenContentEvidence.cs:45-52` |
| 5 个"存值包装"泛型 → dataField 映射 | `tools/editor-bridge/Adapter/ReopenContentEvidence.cs:60-66` |
| `UNVERIFIED_ENUMERABLE` 拒枚举 | `tools/editor-bridge/Adapter/ReopenContentEvidence.cs:97-98` |
| 公共模型基类处停 | `tools/editor-bridge/Adapter/ReopenContentEvidence.cs:104` |
| `Summary()` 形状 | `tools/editor-bridge/Adapter/ReopenContentEvidence.cs:114` |
| 46 项组件类型枚举（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2；含`Combat=18/Hitbox=19/Shop=35/StuffBag=33`） | `.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49` |
| 1017 是一条**不同**的几何读路（DRAFT） | `tools/editor-bridge/Adapter/Geometry1017Fields.cs:9-24,116-143` |
| 队列把 prefab-fields 记为 `source-route-only`（≠没有回执） | `docs/ds-handoff/06-INTERFACE-VERIFICATION-QUEUE.json:2899-2929` |
| `prefab-fields` 真实回执 | `.runtime/editor-bridge/runs/dfce87d6-3ba5-49e5-a556-6b8c7ba33da0/prefab-fields-response.json`（+ 25f78b1b / 3472b1eb / 3c8bb767） |
| `prefab-fields-page` 真实回执（194 预制 / 3 页 / 含 resume） | `.runtime/editor-bridge/runs/{8c515535-66ae-4ef6-8552-fa27432f1a0c,ce2f82fd-cc34-43e1-9e8a-7e9b64cb4035,c980a8f9-f8de-462b-8b30-1f46a2a00c77}/prefab-fields-page-response.json`（后者带 `prefab-resume.json`） |
| `prefab-catalog` 真实回执（2722 条） | `.runtime/editor-bridge/runs/25f78b1b-f00a-45b6-b9eb-c262b049e8a4/prefab-catalog-response.json` |

---

*本文件由 2026-10-10 会话从仓内源码、`.runtime/editor-bridge/runs/*/`（Bash `python` 解析，非 Grep 工具）
与 `.runtime/editor-catalog/resolved/` 只读整理；**未实现、未连线、未连接桥、未触碰游戏/编辑器、未写任何存档**。
所有行号为本次 checkout 实测；组件类型统计与 float 全零结论附真实回执路径与口径。*
