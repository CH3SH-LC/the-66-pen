> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #6 挖 — 分波生成：实体布设组 + 178 激活（M6b 的另一条路）

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。**没有读任何图片、没有读任何 PDF 页。**
证据来源：① `data/node-contracts/`（810 条 7.1 引脚合同）② `docs/official-docs/chapters/`（218 章官方文本）③ `.runtime/` 里的既有回执
（用 Bash `grep`/`find`/Python 遍历查；Grep 工具会静默跳过 `.runtime/`）。
**本文件只读不写**，仅新增本文件本身。

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。

---

## 0. 一句话结论

1. **记忆 `wave-gating-is-entity-placement-groups` 的前半段（官方机制）有真证据**：来源是 `.runtime/editor-bridge/runs/3125a994-…/node-definition-variants-response.json`（**16/16 命中**）+ 官方章 `docs/official-docs/chapters/mhqmrlr6h58e.json`。**不是空口**。
2. **记忆里的引脚名有转录错误**：`70 创建实体` 的第二入参官方名是 **`单位标签索引列表`**（不是「位置标签组列表」）；`373 实体销毁时` 是 **`朝向`/`归属者实体`**（不是「旋转」/「击杀者实体」）。
3. **记忆的后半段结论（「用创建实体节点刷一波怪这条路是断的，**必须**走布设组」）被官方文本直接证伪**：官方章
   `mhw66orrrfkm.json` **自己划了界线**——`70 创建实体` 是 **GUID 型创建**（要求实体预先布设在场景内），而**元件型创建三兄弟**
   `252 创建元件` / `757 创建元件组` / `256 创建投射物` 才是**按 `元件ID` 在运行时凭空生成实体**的那条路（三者都在 7.1 活注册表 500 条 server 定义里）。
   ⇒ **刷怪不必走布设组**。
4. **对 M6b 而言，「分波生成」这条路给不了任何 plain `entity.create` 给不了的东西**。M6b 的验收是**静态摆放**（3×3 九块地摆好、保存、读回），
   而「布设组 + 178」提供的是一个**运行期开/关闸门**（时间维度），与「摆出来」正交；且布设组本身**我们没有任何写入原语**（见 §4）。
   **Q4 直说：对 M6b，「create N entities at N coordinates」就是全部答案。**

---

## 1. defId 178 与 70 的完整引脚签名

引脚合同来自 `data/node-contracts/variants/server/`（**已归档、离线、可复核**）。kind 解码：`1`=exec 入 / `2`=exec 出 / `3`=data 入 / `4`=data 出；
valueType：`1`=实体/配置引用（GUID 类）/ `2`=整数 / `6`=布尔/枚举 / `7`=三维向量 / `10002`=List / `10000`=Generics（`data/node-contracts/shared/value-type-codes.json` §historicalInferredNames）。

### 178 `激活/关闭实体布设组`

`data/node-contracts/variants/server/bucket-01.json:4924`（定义元数据另见 `data/node-contracts/definitions/bucket-01.json:792`，
resourceNetworkId `3400721936711227169`，resource `Resource/Json/Beyond/Node/3400721936711227169.mihoyobin`，categoryVariant `[10001,20000,22000,0]`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 70 `创建实体`

`data/node-contracts/variants/server/bucket-00.json:7`（定义 `data/node-contracts/definitions/bucket-00.json:7`，
resource `Resource/Json/Beyond/Node/10786601862900603767.mihoyobin`，categoryVariant `[10001,20000,22000,0]`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


> **顺带（这条是 §5 的证据）**：`252 创建元件`（`variants/server/bucket-03.json:2642`）与 `256 创建投射物`（`variants/server/bucket-00.json:2673`）
> 的 data 入里都有 **`元件ID`**（valueType `1`，spt=21），出参分别是 `创建后实体` / `创建出的实体`；`757 创建元件组`（`variants/server/bucket-05.json`）入参
> `元件组索引`(vt2)/`位置`(vt7)/`旋转`(vt7)/…/`是否覆写等级`(vt6)，出参 `创建后实体列表`(List)。**三者都 categoryVariant `[10001,20000,22000,0]`。**

---

## 2. 记忆 claim 的证据定位 —— 有，且能逐字引

记忆文件：`C:\Users\PUBLIC_USER\.claude\projects\D--CH3SH-2-myworld-2-myideas-Genshin-Impact-Miliastra-Wonderland-Editor\memory\wave-gating-is-entity-placement-groups.md`
（`modified: 2026-10-06T04:17:37Z` = 本地 2026-10-06 12:17）。

### 2.1 引脚探测回执（记忆自称「`node-definition-variants`，16/16 命中」）——**真**

文件：`.runtime/editor-bridge/runs/3125a994-d47a-4ee2-bb1c-9841d46e331f/node-definition-variants-response.json`
（run 目录 mtime **Oct 6 12:16–12:21**）。**逐字引**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`3125a994` 号 run 里 178/70 的端口逐字（同一文件 `variants[…].definition.pins`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**这是一条 `ok:true` 的只读真机回执**：16 个 definitionId 全部返回定义，且 `graphModified:false / sentToGame:false`。
⇒ 记忆的「16/16 命中」**属实**，且**只是一次定义读取**，不是行为验证。

### 2.2 同轮的第二次独立读出 —— `catalog-r222`，178/179 在活注册表里

文件：`.runtime/verification/interface-experiments-20260928/graph-read/catalog-r222.json`。
`reply.serverNodeDefinitions` 共 **500** 条（`minId=1, maxId=300005`），其中逐字：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 2.3 **记忆没写、但盘上真有一张「分波图」** —— `MW_API_Wave1`

记忆把它一句话带过（「实机只读探测」），但盘上是一次**改动编辑器的 add-node 组图实验**，图名就叫 **`MW_API_Wave1`**
（graphId `1073741825`，server 图，graphKind 20000）。证据在 `.runtime/authoring/requests/*/`（bridge-request.json 里 `"name": "MW_API_Wave1"`）。
重建后的节点表（`4d23a499-5af4-400f-b62e-775e6afa3bd8/result.json`，`status: "editor-model-readback"`）：

| nodeId | defId | 名称 |
|---|---|---|
| 1 | 586 | 实体添加单位标签 |
| 2 | 70 | 创建实体 |
| 3 | 373 | 实体销毁时 |
| 4 | 590 | 获取单位标签的实体列表 |
| 5 | 142 | 获取列表长度 |
| 6 | 231 | 数值小于等于 |
| 7 | 2 | 双分支 |
| 8 | 14 | 是否相等 |
| 9 | **178** | **激活/关闭实体布设组** |

**连边（去重后，来自各 `connect` 请求）**：`4→5`、`5→8`、`8→7`(喂双分支条件)、`3→7`(事件 exec 入)、`7→9`。
**常量**：`9e56366d-…`（nodeId 9, portIndex 1）写 `是否激活 = {"uint": 1}` → 回执 `status:"value-set-readback-verified", readback:1`；
`d442ce56-…`（nodeId 8）写 `int 0`。**节点 1(586)、2(70)、6(231) 未连线。**

也就是一条**能读懂的「波」形状**：`实体销毁时 → 双分支(剩余标签实体数 == 0) → 178 激活下一组`——**但没有布设组索引可填**（见 §4），
而且 **`boundToLevel:false`、`persistentSaveVerified:false`、`runtimeVerified:false`**（`4d23a499` / `3d9ab7d6` / `8d37f6b2` 三个回执同）。

### 2.4 官方机制那一半 —— 真章在

`docs/official-docs/chapters/mhqmrlr6h58e.json`（title「实体布设组」，`.runtime/research-sources/official-docs-sweep-20260929/sources/mhqmrlr6h58e.txt`）。逐字引两条：

- `"实体布设组可用于批量管理布设实体，并可以通过相关节点实现实体的批量创建和销毁。"`
- `"当实体布设组或者实体本身有一个勾选了初始创建，该实体就会随关卡一同创建"`（记录详述其为 **OR**，并给出 a/b 例：组未勾选则只有自己勾选的 a 随关卡创建）
- 硬约束：`"在使用实体布设组之前，需要预先在实体布设组管理工具中对其进行全局定义"`

**结论**：记忆的**机制描述**（布设组 + 初始创建不勾选 + 178 激活）**有据**；
**记忆的探测定位**（16/16）**有据**；但记忆把**一次 mutating 的 `MW_API_Wave1` 组图**说成了「只读探测」，且**没记录「组从未被定义、图从未绑定/保存」**。

---

## 3. 记忆 vs 合同的转录错误（三条，逐条对账）

| 记忆写的 | 合同/官方写的 | 来源 |
|---|---|---|
| `70` 入参「目标GUID + **位置标签组列表**」 | 「目标GUID + **单位标签索引列表**」 | `variants/server/bucket-00.json` 端口名；`docs/editor-catalog/NODE-CATALOG.md:693`；官方 `mhw66orrrfkm.json` |
| `373` 出「位置 / **旋转** / … / **击杀者实体**」 | 「位置 / **朝向** / … / **归属者实体**」 | `.runtime/editor-bridge/runs/3125a994-…/` 178 run 的 373 定义 |
| 「实机**只读**探测」 | 178 的**定义读**是只读（§2.1），但 `MW_API_Wave1` 组图是 **add-node 写入**（§2.3） | 见上 |

记忆的两个结论性事实**仍成立**：`70 只认 GUID 型创建`；`16/16 命中`。**错的是引脚名和一处分层口径。**

---

## 4. 分波路对 M6b 到底给了什么？——**给不了 M6b 任何东西**

**M6b 是什么**：`docs/MODULE-PLAN-6.md:145-152` —— 「地图上的摆放设计」；真机验收是
**「在一个关卡里摆出 3×3 的九块地并调好朝向间距，保存后读回，九块都在、位置对」**。**这是一个静态摆放问题。**

**plain `entity.create` 已经能做它**：原生 `scene_cli create` 接受 `template_id + position + rotation + scale`
（`tools/game-executor/scene_cli.py:259-267`；`MAX_BATCH=256` 见 `tools/game-executor/build_scene_profile.py:58`），
`tools/gameplan/placement.py:96-145` 的 `grid()`/`to_scene_requests()` 就是「按坐标 create N 件」的纯几何规划器。
DEMO-GAP 已判：**M6b「不需要额外能力」（`docs/gameplan/DEMO-GAP.md:80`）。**

**分波路（布设组 + 178）提供的是**：一组**预先布设**的实体在关卡开始时不存在、由节点图在运行期**开/关**——
这是一个**时间维度闸门**（打第一波→开第二波）。它与 M6b 的静态验收**正交**：

| M6b 要的东西 | plain `entity.create` | 布设组 + 178 |
|---|---|---|
| 9 件实体在 9 个坐标存在 | ✅ 直接给（本条已是真机走通单件，`DEMO-GAP.md:80`） | ✅（但实体得先由**编辑器**放好） |
| 保存后读回都在 | ✅ | ✅ |
| 「第 2 波才出现」的时间门 | ❌（也不需要） | ✅（**这才是它唯一多出来的能力**） |

**而且这条路对我们更贵**：它多出一个**我们造不出来的前置**——
1. **布设组只能由编辑器 UI 创建**：官方章 `mhqmrlr6h58e` 写明入口是「系统菜单 →【实体布设组管理】」，硬约束「需要预先…全局定义」。
2. **桥没有布设组操作**：`tools/editor-bridge/ManagedBridge/BridgeServer.cs` 的 `switch(op)` 共 case 全表（见 tools/gameplan/tests/test_doctrine.py）**（`grep -c 'case "'`），
   逐项无 `suite`/`group`/`placement-group` 命中（只有 `import-route-placement`/`export-route-placement`，**路线(path route)**，不是布设组）。
3. **命令面里唯一的「套件/布设组」命令是改属、不是造组**：后端 `ModifySuite`，签名 `(uint, uint, bool)`，
   语义未解（`docs/research/beyondeditor-backend/02-命令分发表-主表-0x914de40.md:105`；`db/gaps.json:67` 自记「ModifySuite 三参数语义 —— 未解」）。
   它改的是**已存在实体**的套件归属，**不能新建组、不能按模板加成员**。
4. **本工程的 registry 也把它标死**：`docs/research/7.1-experiment-plan/closeout/registry.jsonl:280`
   `{"node:7.1:178", "status":"schema-read-only", "editingAccepted":false, "behaviorAccepted":false}`。

**⇒ 结论（Q3/Q4）**：**分波路不给 M6b 任何 plain repeated `entity.create` 给不了的东西**。
它换来的只有「运行期开/关一个组」——那是**战斗波次**的需求，不是**摆放设计**的需求；对 M6b 它是**纯负担**（多一条我们写不了的编辑器前置）。

---

## 5. 更重要的更正：刷怪**不必**走布设组（记忆的收尾结论被官方文本证伪）

记忆断言：`70` 只认 GUID ⇒ 「用创建实体节点刷一波怪这条路是断的，**必须走布设组**」。
**后半句错。** 官方章 `docs/official-docs/chapters/mhw66orrrfkm.json`（《执行节点》，逐节点参数字典）**自己划了这条界线**，逐字引：

- `"根据GUID创建实体。要求预先将其布设在场景内"`，其 detail 逐字：`"…这是 GUID 型创建与元件型创建的分界。"`
- `"以该方式创建的实体没有GUID"`，其 detail 逐字：`"元件型创建三兄弟的出参实体都没有 GUID：「创建元件」出参「创建后实体」…、「创建元件组」出参「创建后实体列表」…、「创建投射物」出参「创建出的实体」…。"`

另一章 `docs/official-docs/chapters/mh2xoxrop0la.json`（《单位》）给出**元件型创建的官方语义**，逐字引：

- `"特别地，动态物件元件与造物元件可以通过节点图节点【创建元件】，直接在运行时由元件创建运行时实体"`
- `"通过节点图节点【创建元件】。可以在运行时创建动态实体或敌人实体"`
- `"元件均具有全局唯一的元件ID，但仅有动态元件与敌人元件可通过节点图节点来生成运行时实体"`
- 产物定义：`"这样的实体称为临时实体，临时实体没有基于编辑时的GUID"`

**节点侧全部落地且可用**（§1 表 + `catalog-r222.json` 的活注册表）：
`252 创建元件`(入 `元件ID`/`位置`/`旋转`/…/`单位标签索引列表` → 出 `创建后实体`)、
`256 创建投射物`、`757 创建元件组`(入 `元件组索引`/`位置`/`旋转`/… → 出 `创建后实体列表`) —— **全在 category `[10001,20000,22000,0]`（server、可加进图）。**

**⇒ 校正后的结论**：
- `70 创建实体` 确实**不能凭空刷怪**（只能把**预先布设**的实体物化）——**记忆这半对**。
- 但「**必须**走布设组」是**错的**：**元件型创建**（`252`/`757`/`256`）才是「按 `元件ID` 在运行期生成实体」的那条路，
  **无需预布设、无需布设组**。要做「分波刷怪」，正确选型是 **`252 创建元件` 按 `元件ID`+坐标**，而不是「编辑器摆好 + 178 开闸」。
- **两条路对 M6b 都不需要**：M6b 要的是静态坐标摆放，native `entity.create`（或图里 `252`）都直接给。

**附带的一条不确定（诚实标注）**：官方 `mh2xoxrop0la` 自身前后不一致——一处说「仅有**动态元件与敌人元件**」，
另一处说「**动态物件元件与造物元件**」。其 `whatThisChapterDoesNotSay` 自认此点未调和。故「到底哪几类元件能被 `252` 创建」**未定**，
但这不影响「元件型创建这条路存在且可用」这条结论。

---

## 6. 附：本轮顺带核出的相关事实（供上游参考，均离线/只读）

- **原生 `creature-create` 有实现、有跑过、但未证落盘**：动作集 `tools/editor-bridge/elevated-request.py:280`
  `NATIVE_ACTIONS = ("inspect","create","save","create-batch","reopen-current","creature-create")`；与 `create` 是**同一个原生动作**，
  只由 `HR_PLACE_BUILTIN` 区分（`docs/research/reverse-eng-20261010/NATIVE-ACTION-SET-MINE.md:59,69`）。
  `.runtime/game-executor/scene-cli/` 下 **13 个 `*creature-create*` run 目录（2026-10-06）**，其中 9 个 `result.json` 为
  `ok:true / actionStatus:0`，每次分配新 `entityId`（`1082130433…1082130438`），观测 `entities` 计数 11→16 单调递增——
  **但每个 run 的 `*.gil` `beforeSha256 == afterSha256`（字节零变化）**，且 `placedCount:0`。
  ⇒ 判：**运行期真建了内存实体，但没有写盘证据**（与 `MINED-INTERFACES.md:94` 的「未验证」并不矛盾，只是那行说「未找到回执」，
  盘上其实有 13 个 run 目录——**建议上游把 MINED-INTERFACES 那行改为「有运行目录、无落盘差分」**）。
- **`MW_API_Wave1` 图从未绑定、从未保存**（`boundToLevel:false`、`persistentSaveVerified:false`，§2.3），
  导出 `.gia` 836 B、其 reply `rows:[]`（`.runtime/editor-bridge/exports/miliastra-bridge-98766553-…/…gia.reply.json`）。
  178 的**行为**在任何存档里都**没有被验证过**——registry 也记 `behaviorAccepted:false`。

---

## 7. 检索范围（「搜不到」要能被复核）

| 检索对象 | 方法 | 结果 |
|---|---|---|
| `data/node-contracts/{definitions,variants}` | Python 遍历 + grep `definitionId` | 178/70/252/256/757 全部命中，引脚逐条抄自 variants |
| 记忆的 16/16 回执 | `find .runtime/editor-bridge/runs -name node-definition-variants-response.json` | 7 个 run；`3125a994` = 16/16（其余 4/5/7/17/24/42 个 id） |
| `MW_API_Wave1` 组图 | Python 遍历 `.runtime/authoring/requests/*/bridge-request.json` grep `Wave` | 32 条请求，节点/连边/常量如 §2.3 |
| 布设组写入原语 | grep `BridgeServer.cs` 的 `case`；后端命令表 `ModifySuite` | 桥 0 命中；命令面只有 `ModifySuite`（改属、非造组） |
| 创建型节点 | 遍历官方 `chapters/*.json` grep `创建元件`/`GUID` | `mhw66orrrfkm`、`mh2xoxrop0la` 两章给出分野与语义 |
| 原生 creature-create | 遍历 `.runtime/game-executor/scene-cli/*creature*` | 13 run，9 成功，`beforeSha==afterSha` |

**本轮未检索**：任何存档 `.gil` 的布设组表（因为没有任何组被创建过，无对象可查）；任何图片/PDF。**凡「未找到」，以上表列出的范围为准。**
