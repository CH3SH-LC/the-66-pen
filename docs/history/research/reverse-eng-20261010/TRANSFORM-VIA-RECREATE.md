> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #5 mine — 「动不了就删了重建」这条退路，到底走不走得通

**问题（任务 #5）**：`CLAUDE.md` §六(c) 说 `entity.transform` 改不动**已有**实体（没有 setter）。
显眼的 workaround 是「删掉、按新坐标重建」。本文件核实这条路是否可行、代价多大。

**写于 2026-10-10。口径：纯离线、纯只读。** 未连桥、未向游戏/编辑器发任何 native/graph 报文、
未启动或触碰任何进程、未写任何存档。结论全部从仓内 **C# / Python / 现有回执原件**逐行读出，每条附 `file:line`。

**三层纪律**（`CLAUDE.md` §一.3）：下面每条要么是**源码（静态）**，要么是**仓内已有的真机回执记录**，
**没有一条是本轮真机跑出来的**。凡「有实现、没跑过」的，一律标 `只离线`；凡引用他轮回执的，标 `真机（他轮）`。

---

## 0. 一句话结论（先给判决）

1. **「删 + 重建」在工具面**技术上**可行，但它不是「移动」，是「销毁换新 id」**——新实体的 id 与旧的不同，
   所以**所有绑在旧 id 上的引用（节点图绑定等）会断**，要重新绑、重新落盘。
2. **能删到「上一轮 / 用户存量」实体的，只有一条没有门的裸操作** `delete-owned-entity-ids`
   （`OwnedEntityDelete.cs:8-27`：*"The boundary is the ID LIST and nothing else."*）；
   **强门只允许删「本轮新建的那一个 / 本轮有创建回执的那一批」**。⇒ 要移动一个**上一轮**摆好的实体，
   你只能走那条**没有所有权门 / 没有关卡作用域**的裸操作，风险落在自己头上。
3. **重建不便宜**：`entity.create` 一次 = **一份新鲜基線 + 一份存档恢复副本 + 一份派生复核 + 一次派发 + 一次独立读回**，
   而且 **create 本身不落盘**（`entity_server.py:1694-1695`），还要再来一次同规格的 `save`。
4. **对 demo：静态布局「第一次就按坐标建对」是充分且正确的**——因为布局在建时就定死（坐标是 create 的入参），
   **根本不需要 transform**。⇐ 这是本工程**故意选的路**，不是妥协（`placement.py:8-16`）。
5. **诚实的操作结论：把布局一次设计好，然后永远不要移动任何东西。** 要改，就改规划、在**新一轮**里重建整套，
   而不是「删一个、补一个」——后者既贵（两次 native 写周期）又危险（裸删 + id 换新 + 绑定断）。

---

## 1. 删除路径的**确切谓词**：能删「本轮建的」「上一轮建的」「永远不能」

仓内能删场景实体的路径共 3 条（脚本/UI 手删不计），谓词完全不同。逐条给「键在什么上」。

### A. crud-probe 路径 —— `delete-entity-crud-probe`（**强门：只认本 run 新增的那一个**）

- **入口**：`EntityCrudProbe.cs:217-239`（删）；`:193-215`（改名的同门）。
- **谓词**全部由 `CheckCrudTarget()`（`EntityCrudProbe.cs:102-114`）+ `CheckCrudBaseline()`（`:88-100`）裁决：

  | 检查 | 失败码 | file:line |
  |---|---|---|
  | 探针已开始（内存单槽 `crudExperiment`，`:31`） | `CRUD_PROBE_NOT_BEGUN` | `:90` |
  | 探针 180 秒窗口内（`CrudProbeSeconds=180`，`:17`） | `CRUD_PROBE_EXPIRED` | `:91` |
  | 上下文对象与状态未变 | `CRUD_CONTEXT_CHANGED` | `:93-94` |
  | 基线里每个实体仍在且身份全等 | `CRUD_BASELINE_ENTITY_REMOVED_OR_REPLACED` | `:96-98` |
  | 「当前 − 基线」**恰好 1 个** | `CRUD_TARGET_IDENTITY_OR_NEW_ENTITY_SET_CHANGED` | `:106-108` |
  | 该新实体 `EntityType==1402 && InstanceKind==0`（硬编码） | 同上 | `:107` |
  | 没有别的实体叫 `MW_CRUD_Probe` | `CRUD_PROBE_NAME_CONFLICT` | `:109-110` |
  | 新实体名 ∈ {原名, `MW_CRUD_Probe`} | `CRUD_TARGET_NAME_CHANGED_EXTERNALLY` | `:111-112` |
  | 一次性：`DeleteSpent` 在 invoke **前**置位 | `CRUD_DELETE_ALREADY_ATTEMPTED_OBSERVE_BEFORE_RETRY` | `:220,233` |

- **它键在什么上**：一个**内存里的、run 作用域的基线快照**（`BeginEntityCrudProbe()` 在 `:149-162` 拍下整表）
  + 唯一实例 `crudExperiment`（`:31`）。即「**`Begin` 之后恰好多出来的那一个**」。
- **回答本轮的三个问题**（对 A）：
  - **本轮建的**：**能**——前提是你在 `BeginEntityCrudProbe` **之后**创建，且 180 秒内、只加了这一个。
  - **上一轮建的**：**不能**——它在基线里，进不了 `added`（`:106-108`）。
  - **永远不能**：基线实体**恰恰是被保护的**：若它消失，`CheckCrudBaseline` 直接抛 `CRUD_BASELINE_ENTITY_REMOVED_OR_REPLACED`（`:96-98`）。
- 注：A 会「认领」它没建的实体（`:177-182`，只核「基线完好 + 恰好多 1 个」，**不核是本 run 建的**）；
  把它堵住的是**上一层编排**（`run_live_crud_acceptance.py:436-437,777`），不是适配器。见 `ENTITY-DELETE-SCOPE.md` §3 F3。

### B. owned-entity 路径 —— `delete-owned-entity-ids[-dry-run]`（**弱门：只有 id，无所有权/无关卡**）

- **入口**：`OwnedEntityDelete.cs:87-150`。谓词 = `BuildOwnedDeleteIndex`（`:52-83`）+ 逐 id 解析，只有三件事：
  1. 请求形状：`ids` 非空、`≤64`、互不相同（`:89-91`）；
  2. 每个 id 必须**唯一**解析成一个节点：节点类型 `oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7`（`:43,66`）、
     `resource.containerType==4 && folderKey.kind==1`（`:69-70`）、类型化访问器 `ndlKBRCbBjF` 的返回模型
     `FullName==CrudEntityType` 且 `ReadCrudKey(model).Id==id`（`:71-75`）；
  3. 解析到 0 或 >1 → **整批拒、一个不删**（`:102-108`）；`dryRun` 只回映射不调用（`:110-116`）；
     真删前逐 id 重新解析核对同一 id（`:128-137`），再调原生 `zgVKB6OS1MZ`（`:138-143`）。
- **它键在什么上**：**只有 id 列表**。头注释原文（`:8-27`）：
  > *"The boundary is the ID LIST and nothing else. There is deliberately no name form, no type form,
  > no 'everything new since X' form and no wildcard."*
  **无所有权记录、无名字门、无 run 作用域、无关卡作用域。**
- **回答本轮的三个问题**（对 B）：
  - **本轮建的**：**能**（id 在就行）。
  - **上一轮建的**：**能**（它不区分谁建的——只要当前编辑器图里该 id 唯一定位得到）。
  - **永远不能**：**能删任意存量实体**——**包括用户手摆的东西**。这不是 bug，是这条路径**设计成这样的边界**
    （`ENTITY-DELETE-SCOPE.md:18-30,115`）。对照：**图**删除有 `MW_` 名字门（`OwnedGraphDelete.cs:42,179-180`），
    **实体**删除**没有**等价物。
- **回执恒不落盘**：`:145-149` 的 `gameEffectVerified:false / persistentSaveVerified:false` 是写死的。
  桥写的是**编辑器内存**，落盘要再来一次 `save`（`CLEANUP-PLAN.md:109-110`）。
- **真机（他轮）**：`.runtime/editor-bridge/runs/1dc923b7-…/delete-owned-entity-ids-response.json`
  ——`requested:7, invokedCount:7`，逐条 `invoked:true / nativeResult:true`，**第一条 id 就是 `1077936129`**
  （demo 的地块实体）（`CLEANUP-PLAN.md:105-108`）。⇒ 这条路径**真派发过**。

### C. owned-cleanup 路径 —— `delete-owned-entity-cleanup`（**一次性、硬编码、已过期**）

- **入口**：`OwnedEntityRecovery.cs:37-88`。**唯一**能把门键在「一个具体存量实体」上的路径，但钉死到
  **单 id `1077936132`** + 编辑器 pid 9340 / 游戏 pid 47028 / 两进程 FILETIME + 正式 GIL sha256 +
  **绝对过期 `2026-09-26T14:50:59Z`**（`:23-46`）。⇒ **今（2026-10-10）已失效，且不可泛化**。

### 上层还有「真正的所有权门」（都在调用方，不在裸操作里）

| 层 | 谓词 | file:line |
|---|---|---|
| `cleanup_owned_entities.py`（操作侧） | **三腿交集** A=本轮回执携带 id、B=相对 pre-baseline 是新增、C=当前存在且模板一致 | `:455-545`（缺 → `NO_UNIQUE_ADDITION_PROOF` `:537-541`） |
| `backend/cleanup_ownership_legs.py`（业务侧） | **A..G** 七腿 | `:23-32` |
| `backend/entity_server.py mw_scene_cleanup_owned` | A..G + 关口材料 + 关卡一致 + 派发日志 | `:1981,2056-2070,2090-2098` |

**关键**：这些门都在**调用方**，B 的裸操作**不经过它们也能被直接调用**；`cleanup_service.py:8-9` 直接标注该操作
*"bounded, NOT atomic, NOT ownership-checked"*。

**⇒ 对本轮三问的一句话回答**：
- **「工具」整体**：删**本轮**实体，走 A 或上层所有权门就够；删**上一轮**实体，**只有 B 这条裸路**；
  「永远不能」不存在——B 对存量实体零保护。
- **危险点**：id **跨关卡复用**（本机 **10 个关卡**的实体表里都有 `1077936129`，模板/名字各不相同，
  只有 `1073741842` 才是模板 `20001965` 名`土田`），而**适配器里没有关卡作用域**（`ENTITY-DELETE-SCOPE.md` F2）。
  给对 id、开错关卡 ⇒ **删的是别人的实体**。关卡一致性只在上层（`entity_server.py:2090-2098`）。

---

## 2. `entity.create` 的代价：**一份基線 + 一份恢复副本 + 一份复核 + 一次派发 + 一次读回**

### 2.1 create 自带坐标（这就是「不需要 transform」的根据）

- agent 侧 `scene_cli.py`：`create` / `creature-create` **一次性收** `position` / `rotation` / `scale`
  （`:258-266`），并**强制要求 `--review`**（`:269-273` → `NATIVE_WRITE_REVIEW_REQUIRED`）；
  批量 `create-batch` 逐条规范化于 `normalize_placement`（`:170-192`）/ `normalize_placements`（`:195-199`）。
- 一次 `create-batch` 上限 **`MAX_BATCH = 256`**（`build_scene_profile.py:58`；profile `maxBatch:256`）——
  即 **3×3=9 个地块可以一次派发建完**。

### 2.2 一次 create 到底烧掉什么（业务入口逐行）

`backend/entity_server.py:1617 mw_scene_create_entity` 的顺序就是清单：

| 步骤 | 代价 | file:line |
|---|---|---|
| ① 新鲜基线 | `inspect_level(...)` 拍一份**完整**运行时基線 | `:1645` |
| ② 恢复副本 | `fresh_account_backup(...)` 拷一份正式存档 | `:1648` |
| ③ 派生复核 | `derive_review(...)` 从**原始材料**推导 `native-write-review`（**不接受判决**） | `:1649`（生产者：`orchestrate_write_review.py:273-361`） |
| ④ **一次派发** | `dispatch_write(level,'create',…)` | `:1650` |
| ⑤ 独立读回 | `inspect_level(...)` 再拍一份，判定 create | `:1661` |

- **复核与坐标强绑定**：复核里 `requestSha256 = canonical_hash(request)`（`orchestrate_write_review.py:317`），
  而 `request` **含 `position`**（`:131-133`）；`native_write_review.py:60` 反过来要求
  `review.requestSha256 == canonical_hash(request)` 才放行。
  ⇒ **换一个坐标 = 换一个 request 哈希 = 旧的复核用不了，必须重新派生一份**。
- **复核一次性**：`claim_review`（`native_write_review.py:83-85`）记 *"single-compiled-attempt; never auto-replayed"*。
- **基線每次重新绑定**：`load_baseline`（`native_write_review.py:32-51`）按哈希复核 `prepared.json`/`build-result.json`/
  `stdout.jsonl`/`exit.json`，并要求**完整且非空**的运行时快照。工程纪律：**一次写入 = 一份新鲜基线 + 一份新复核**
  （`CLAUDE.md:57`）；复用复核会报 `actionStatus 6`（工程记忆 `one-write-per-baseline-and-review`）。
- **create 本身不落盘**：返回 `persistence=_stage('not-run', reason='nothing was saved; the new entity lives in the
  editor only')`（`entity_server.py:1694-1695`）。**持久化是另一次 `save`**（`mw_scene_save_level`，`:1704-1721`，
  同样要基線 + 恢复副本 + 复核 + 派发）。

⇒ **「按新坐标建一个」的单次成本 = 一次完整 native 写周期**（①–⑤），**且不持久**；要留下就必须再来一次
同规格的 `save`（再 ①–④）。

---

## 3. 对 demo：**「第一次就按坐标建对」是充分的——是**

**答：是。**

**理由（不是「凑合能用」，而是「这条路本就被设计成不需要 transform」）**：

- 静态布局在**建之前**就完全被坐标确定：`entity.create` 自带 `position`/`rotation`/`scale`（`scene_cli.py:258-266`），
  `create-batch` 能**一次**建 N 个各自带坐标的实体（`:267-268`，上限 256）。
- `placement.py:8-16` 的头注释把这件事**当成设计前提**写下来了：
  > *"The natural tool for laying out a grid would be `entity.transform` … **This project does not have it** …
  > But `entity.create` already takes a position, so a regular layout needs no transform at all:
  > we simply create N entities, each at its own computed coordinate."*
- 真机已证：地块实体 `1077936129` 就是**按坐标 `entity-create --template-id 20001965`** 建出来的
  （`PROGRESS.md:98`；`DEMO-GAP.md:80`）。**只证了单件**；`3×3` 整批未真机（`DEMO-GAP.md:80`）。

⇒ **只要布局是静态的（只是「摆在哪」），第一次按算好的坐标 create，就没有任何东西需要 transform。**
**这一步不需要「删+重建」，因为根本没东西可动。**

### 3.1 但若某个布局**必须移动**——唯一可走的路是「删 + 重建」，代价如下

**（a）删除**（这一步只能走 B 裸操作，若目标是上一轮的实体）：
- 一次 **bridge** 派发（`delete-owned-entity-ids`，需 `.runtime/editor-bridge/runs/` 下**已存在的 bridge run**，
  即编辑器内已注入的桥；`MCP-BUSINESS-CONTRACT.md:52`）。**不需要 write-review**（不是 native 写）。
- **但**：目标是**上一轮**实体 ⇒ 没有「本轮创建回执」⇒ 上层所有权三门会以 `NO_UNIQUE_ADDITION_PROOF` **拒**
  （`cleanup_owned_entities.py:537-541`）。⇒ **只剩 B 这条无门裸路**，而它**无关卡作用域**+**id 跨关卡复用**
  ⇒ 有「删到别家同 id 实体」的真实风险（`ENTITY-DELETE-SCOPE.md` F2/CLEANUP-PLAN §2.1）。
- **不落盘**（`OwnedEntityDelete.cs:145-149` 写死 `persistentSaveVerified:false`），且「未 save 的删除会被关卡重载悄悄还原」
  （`CLEANUP-PLAN.md:109-110`）。

**（b）重建**：一次完整 native 写周期（§2.2 的 ①–⑤）+ 坐标换了 ⇒ **新的复核**。

**（c）落盘**：再一次 native `save`（再 ①–④）。**delete 不落盘，所以必须补这一步。**

**（d）最贵的隐藏账——id 变了**：删+重建**不是移动**，是**销毁换新 id**。旧 id 上的一切**引用**（节点图绑定
`boundEntityIds=[1077936129]`，`PROGRESS.md:100`）随旧实体消失而断，**必须重新绑定**（又一次 bridge 派发）
**并再落盘**。

⇒ **一次「移动」= 1 次 bridge 删（裸门）+ 1 次 native create（基線+副本+复核+派发+读回）+
1 次 native save（再 基線+副本+复核+派发）+ 1 次 bridge 重绑 + 再落盘**，且**新实体是新 id**。

### 3.2 这个代价**可接受吗**？

- **偶发、极少量（1–2 个）、且能确认当前关卡**时：**勉强可接受**，但要把 B 的裸门当已知风险写进口径
  （一错关卡就删到别家）。
- **当成常规「微调摆放」手段**：**不可接受**。理由有三：
  1. 它**不是移动**——id 换新，**绑定全断**，要重绑+重存；
  2. 它**被迫走无门裸删**，与该工程「只删自己的、按证据删」的一贯纪律相冲突；
  3. 它一次要**两个 native 写周期**（create + save），每次都要新鲜基線+恢复副本+复核+派发——**远贵于「建之前算对坐标」**。

⇒ **正确做法是回到 `placement.py` 的规划层把坐标一次算对**（`:68-145` 的 `grid`），
在**新一轮**里**按新规划重建整套**（`create-batch` 一次最多 256 个），而不是「删一个、补一个」。

---

## 4. 诚实的操作结论

> **把布局一次设计好，然后永远不要移动任何东西。**

具体化：
- **建 = 一次定型**。位置/朝向/缩放**在 create 那一刻一次给全**（`scene_cli.py:258-266`）；多件用 `create-batch`（≤256）。
- **要改布局 = 改规划、在新一轮重建**（全批是「本轮新建」，于是所有权门可用、id 干净、绑定从零建立）。
  **不要**对已落盘的**上一轮**实体做「删+重建」——那会把你逼到**无门裸删**、并**换掉 id、断掉绑定**。
- **绝对不要**建完再想调 `entity.transform`：那条路**没有 setter**（`EntityTransform.cs:139/144` 抛
  `TRANSFORM_NATIVE_SETTER_UNKNOWN`），会**具名失败，不伪造成功**。

**一句话**：`entity.transform` 的缺席**不是缺口**，是**设计要求**——**布局是 create 的入参，不是事后可调的属性**。
「删+重建」名义上能兜底，实际上**代价高、风险大、且语义不等价（换 id、断绑定）**，所以它在 demo 里的正确定位是
**「理论上的最后手段，不是工作流」**。

---

## 5. 证据索引

| 论断 | 证据 |
|---|---|
| B 裸操作「边界只有 ID 列表」 | `tools/editor-bridge/Adapter/OwnedEntityDelete.cs:8-27,87-150` |
| B 唯一解析 + 整批拒 + 删前复检 | `OwnedEntityDelete.cs:52-83,102-116,128-143` |
| B 回执恒 `gameEffectVerified:false`（不落盘） | `OwnedEntityDelete.cs:145-149`；`CLEANUP-PLAN.md:109-110` |
| B 真机派发过（含 `1077936129`） | `CLEANUP-PLAN.md:105-108`（`.runtime/editor-bridge/runs/1dc923b7-…/delete-owned-entity-ids-response.json`） |
| A crud-probe 强谓词（唯一新实体/180s/一次性/基线保护） | `tools/editor-bridge/Adapter/EntityCrudProbe.cs:17,23,31,88-114,149-162,217-239` |
| 实体删无名字门、图删有 `MW_` 门（不对称） | `ENTITY-DELETE-SCOPE.md:101-106`；`OwnedGraphDelete.cs:42,179-180` |
| 上层所有权三门（只认本轮新建） | `cleanup_owned_entities.py:455-545`；`backend/cleanup_ownership_legs.py:23-32`；`entity_server.py:1981,2056-2070` |
| 裸操作「NOT ownership-checked」自认 | `backend/cleanup_service.py:8-9` |
| 适配器无关卡作用域 + id 跨 10 关卡复用 | `ENTITY-DELETE-SCOPE.md` F2；`CLEANUP-PLAN.md:112-115` |
| create 自带坐标 + 批量规范化 | `tools/game-executor/scene_cli.py:170-199,258-268` |
| create 强制 `--review` | `scene_cli.py:269-273`；`build_scene_profile.py:210`（`NATIVE_WRITE_REVIEW_REQUIRED`） |
| 一次 create = 基線+副本+复核+派发+读回 | `backend/entity_server.py:1645,1648,1649,1650,1661` |
| 复核与坐标强绑定（换坐标=换复核） | `orchestrate_write_review.py:131-133,317`；`native_write_review.py:60` |
| 复核一次性 / 基線完整非空 | `native_write_review.py:32-51,83-85` |
| create 不落盘（persistence=not-run） | `backend/entity_server.py:1694-1695` |
| 一次写入=一份新鲜基線+一份新复核（纪律） | `CLAUDE.md:57`；工程记忆 `one-write-per-baseline-and-review` |
| create-batch 上限 256 | `tools/game-executor/build_scene_profile.py:58`；`profiles/genshin-cn-7.1.0-reviewed-write.json`（`maxBatch:256`） |
| 「布局无需 transform」是设计前提 | `tools/gameplan/placement.py:8-16,68-145` |
| 地块按坐标建出（真机，单件） | `PROGRESS.md:98`；`DEMO-GAP.md:80` |
| 图绑定到实体 id（换 id 即断绑） | `PROGRESS.md:100`（`boundEntityIds=[1077936129]`） |
| `entity.transform` 无 setter（具名抛错） | `CLAUDE.md:128-138`；`tools/editor-bridge/Adapter/EntityTransform.cs:36,139,144` |

---

*本文件由 2026-10-10 会话从仓内 C#/Python/JSON 源码与已有回执记录只读整理；未连接桥、未发任何报文、
未触碰游戏/编辑器、未写任何存档。所有引用行号为本次 checkout 实测。凡「有实现没跑过」的条目已标「只离线」。*
