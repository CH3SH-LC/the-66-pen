> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #4 挖 — 实体生命周期：销毁/移除事件与 `entity.remove` 的边界

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何 native/graph 报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。**没有读任何图片、没有读任何 PDF 页。**
证据来源：① `data/node-contracts/`（810 条 7.1 引脚合同）② `docs/official-docs/chapters/`（218 章官方文本）
③ `tools/editor-bridge/Adapter/`（C# 适配器源码）④ `.runtime`/仓内既有回执与文档（用 Bash `grep` 查；**Grep 工具会静默跳过 `.runtime/`**）。
**本文件只读不写，仅新增本文件本身。**

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 凡「有实现、没跑过」一律标出。

---

## 0. 一句话结论

1. **`72 实体移除/销毁时` 与 `373 实体销毁时` 是两条「销毁类」服务器**事件**节点，都是「出×1」的**纯观察者**——没有入参、没有过滤条件、
   没有创建者门**（§1）。它们**只在关卡实体上触发**，但**范围是「关卡内任意实体」/「关卡内物件和造物」**。
2. **「只允许本次新增探针」这条删除门，落在 `EntityCrudProbe.CheckCrudTarget`（`EntityCrudProbe.cs:102-114`，决定行是 `:107`），
   键在「相对内存基线恰好多出来的那一个实体」上**。这是 `INTERFACE-INVENTORY.md:27` 那句「本次新增」的实际出处（§2）。
   同仓并存一条**没有所有权门的裸操作** `delete-owned-entity-ids`（`OwnedEntityDelete.cs:87-150`），它**只键在 id 列表**——
   「owned」是调用方意图，不是服务端属性。
3. **回答问题 2（核心）**：**能。图节点 72/373 会为该工程没创建的实体触发，运行期知道一批工具碰不到的实体。**
   而且这不是「同一个边界的两面」——**两边的范围根本不重合**：图事件的范围是**任意实体**（`官方章 mhn7ko01v3yw.json:75-88`），
   工具的 crud-probe 范围是**本次新增的那一个**；连没有所有权门的裸操作 B 也仍然被**「该 id 必须在编辑器前端资源树里唯一物化」**这条卡住（§3）。
   **运行期 ≥ 工具**，缺口方向单一：**图看得见（还能删）的实体 ⊋ 工具删得掉的实体**。
4. **对清理的意义**（§4）：`entity.remove` 的**权威原语在节点图这一侧**（`69 销毁实体` / `372 移除实体`，入参「目标实体」任意来源），
   而工具的删除**只覆盖「编辑态已物化的实体」**。**运行时生成的实体（图建的方块/怪、元件型创建、布设组激活出来的实体）不在工具的可寻址集合里**——
   它们既不能被 `delete-owned-entity-ids` 按 id 解析（没有前端资源节点），也不在 crud-probe 的基线概念里。
   **收尾清理若只依赖工具删除，会漏掉所有运行时生成物；这一半只能靠图（或让它们本就不生成）来收。**

---

## 1. `72` 与 `373` 的引脚签名（从 `data/node-contracts` 重导）

引脚合同来自 `data/node-contracts/variants/server/`（**已归档、离线、可复核**）。kind 解码：`1`=exec 入 / `2`=exec 出 / `3`=data 入 / `4`=data 出；
valueType：`1`=实体/配置引用（GUID 类）/ `2`=整数 / `6`=布尔/枚举 / `7`=三维向量 / `10002`=List / `10000`=Generics
（`data/node-contracts/shared/value-type-codes.json` §historicalInferredNames；本读码口径与同目录 `WAVE-SPAWN-PATH.md:29` 一致）。

### 72 `实体移除/销毁时`

**记录定位**：`data/node-contracts/variants/server/bucket-02.json:1165`（`stableKey.definitionId=72`，
`categoryVariant=[10001,20000,22000,0]`，`graphSide=server`，`graphKindRaw=20000`）；
定义元数据 `data/node-contracts/definitions/bucket-02.json:590`（resourceNetworkId `2772578340675051596`，
resource `Resource/Json/Beyond/Node/2772578340675051596.mihoyobin`，sha256 `3a459b85…`）。
目录对照：`docs/editor-catalog/NODE-CATALOG.md:695`。


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


⇒ **只有 2 个引脚**：1 个执行出 + 1 个数据出（`事件源GUID`）。**没有 `事件源实体` 出参**（对比 373 有）。
`definitionName`＝`实体移除/销毁时`；`description`＝`unknown`（合同未知）。
**没有入参** ⇒ **图这一侧没有任何「只对某些实体生效」的过滤旋钮**。

### 373 `实体销毁时`

**记录定位**：`data/node-contracts/variants/server/bucket-04.json:6856`（`stableKey.definitionId=373`，
`categoryVariant=[10001,20000,22000,0]`，`graphSide=server`，`graphKindRaw=20000`）；
定义元数据 `data/node-contracts/definitions/bucket-04.json:2673`（resourceNetworkId `191600144721605859`，
resource `Resource/Json/Beyond/Node/191600144721605859.mihoyobin`，sha256 `6fa8bab0…`）。
目录对照：`docs/editor-catalog/NODE-CATALOG.md:853`。


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


⇒ **10 个引脚**：1 个执行出 + 9 个数据出。同样**没有任何入参**，**没有创建者门**。

> **转录纠正**（顺带落实 `WAVE-SPAWN-PATH.md:12` 的同族纠正）：373 的 `:5` 是 `朝向`（不是「旋转」）、
> `:7` 是 `归属者实体`（不是「击杀者实体」）。以本文件 §1 的引脚表为准（＝合同原文）。

### 官方文本对照（**这条是 §3 的判决依据**）

`docs/official-docs/chapters/mhn7ko01v3yw.json`（服务器·事件节点全量清单章）：

- `:75-76` **「`实体移除/销毁时` / 节点功能 / 关卡内**任意实体**被移除或销毁时触发该事件，该事件**仅在关卡实体上**可以触发」**
  —— 范围＝**任意实体**；接收者＝**关卡实体**。
- `:87-88` **「`实体销毁时` / 节点功能 / 关卡内**物件和造物**被销毁时触发该事件，该事件**仅在关卡实体上**可以触发」**
  —— 范围＝**物件和造物**（373 比 72 窄，但仍**不限于工程创建的东西**）。
- `:80-82` **次序契约**：「实体被销毁或被移除均会触发该事件。因此实体被销毁时，会**依次触发【实体销毁时】以及【实体移除/销毁时】**」
  —— 373 先、72 后（同一件事的两条通知）。
- `:93` 373 的 9 个出参逐字（`事件源实体`／`事件源GUID`／`位置`／`朝向`／`实体类型`／`阵营`／`伤害来源`／`归属者实体`／`自定义变量组件快照`），
  与 §1 的合同完全一致。**`自定义变量组件快照`的官方用途**：「销毁时，该实体上的自定义变量组件的快照」——**实体已销毁后要读它的变量只能走快照**。

**另一本（路由差异）**：`docs/official-docs/chapters/mh3ecor1x5cm.json:50-52`
——「当**角色生命值归零**时，**角色实体上**的节点图可以收到……`实体销毁时`以及`实体移除/销毁时`事件；而**物件销毁**时，事件会被推送到**关卡实体**上」。
⇒ **接收者随实体类型而变**：角色销毁→投**角色自己的图**；物件/造物销毁→投**关卡实体**。
（该项目已把本句与 `mhn7ko01v3yw:75` 「仅在关卡实体上」的冲突登记为待裁决项；本章只负责记「接收者随类型而变」这一事实。）

---

## 2. 工具侧删除的**精确**谓词（file:line）

仓内能删场景实体的路径有 **3 条**（详尽清单见 `docs/gameplan/ENTITY-DELETE-SCOPE.md`§1–§2，此处只提炼谓词并回答边界）。逐条给**决定行**：

### A. crud-probe 路径 —— `delete-entity-crud-probe`（**这是「只允许本次新增」的实际出处**）

- **入口**：`tools/editor-bridge/Adapter/EntityCrudProbe.cs:217-239`（`DeleteEntityCrudProbe`）。
- **门**：入口第一行 `:219` 调 `CheckCrudTarget()`；**决定行 `:107`**：

  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- **键在什么上**：一个**内存里的、run 作用域的基线字典** `CrudExperiment.Baseline`（`:23`）+ 唯一实例 `crudExperiment`（`:31`），
  由 `BeginEntityCrudProbe()`（`:149-162`，拍基线于 `:153`/`:156`）建立。即
  **「`Begin` 之后相对基线恰好新出现的那一个实体」，且它必须 `EntityType==1402 && InstanceKind==0`**。
  **不是**用户传入的 id 集合、**不是**名字前缀、**不是**持久化归属记录。
- **附加门**：删前目标必须在**编辑器前端**物化——`FindCrudFrontend`（`:123-147`）走前端资源树找**唯一**匹配的资源节点，
  找不到就 `:222-224` 返回 `expand-scene-folder-to-materialize-test-entity`（**不调 native 删除**）。
- ⇒ 这就是 `tools/authoring/INTERFACE-INVENTORY.md:27`「entity.rename_delete … 仍**只允许本次新增探针**，不能用于任意存量实例」的落点。

### B. owned-entity 路径 —— `delete-owned-entity-ids[-dry-run]`（**只有 id，无所有权门**）

- **入口**：`tools/editor-bridge/Adapter/OwnedEntityDelete.cs:87-150`。
- **门**：`BuildOwnedDeleteIndex`（`:52-83`）+ 逐 id 解析；**决定行 `:89-91`（形状）、`:102-108`（解析，整批拒）、`:128-137`（删前复检）**。
  逐 id 要求：节点类型 `oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7`（`:43,66`），
  其 `resource.containerType==4 && folderKey.kind==1`（`:69-70`），类型化访问器 `ndlKBRCbBjF` 返回模型 `FullName==CrudEntityType`
  且 `ReadCrudKey(model).Id==id`（`:71-75`）；解析到 0 个或 >1 个 → **整批拒绝**（`:102-108`）；真删前重新解析并核对同一 id（`:128-137`）后调 `zgVKB6OS1MZ`（`:138-143`）。
- **键在什么上**：**只有 id 列表**。头注释直说（`:8-27`）：
  > "The boundary is the ID LIST and nothing else. There is deliberately no name form, no type form,
  > no 'everything new since X' form and no wildcard."
- **上游两道形状门（非权限门）**：`ManagedBridge/BridgeServer.cs:352`（`ReadUintArray(root,"ids")`）、
  `elevated-request.py:160-174`、`elevated-runner.ps1:278` 同 `1..64`。

### C. owned-cleanup 路径 —— `delete-owned-entity-cleanup`（一次性、硬编码、**已过期**）

- **入口**：`OwnedEntityRecovery.cs:37-88`，钉死单个 id `1077936132` + 进程 pid/FILETIME + 正式 GIL sha256 + 绝对过期 `2026-09-26T14:50:59Z`（`:23-46`）。
  ⇒ 今日（2026-10-10）**不可用**，不可泛化。

### 「本次新增」的真正所有权门在哪（**都在调用方，非线协议**）

| 层 | 谓词 | file:line | 键在什么上 |
|---|---|---|---|
| 工具侧包装 | **三腿交集** A=本次 create 回执携带 id、B=相对 pre-baseline 是新增、C=当前基线存在且模板一致；`previous is None` ⇒ 全拒 `NO_UNIQUE_ADDITION_PROOF` | `tools/game-executor/cleanup_owned_entities.py:455-545`（决定性分支 `:535-541`） | **本次回执 + 前后基线差 + 基线观测的模板** |
| 业务侧包装 | A..G 七腿 | `backend/cleanup_ownership_legs.py:23-32`；`backend/entity_server.py:1981,2056-2070` | 同族 + 时间窗/防篡改/冻结 id |

**关键**：B 的**裸操作不经过这些门也能被直接调用**（`backend/cleanup_service.py:8-9` 自认该操作 "bounded, NOT atomic, NOT ownership-checked"）。

---

## 3. 回答问题 2：图（72/373）会不会为「工程没创建的实体」触发？——**会，且这是设计而非疏漏**

### 3.1 图事件的观察范围**不受创建者约束**

- `72` 的官方范围逐字是「**关卡内任意实体**」（`mhn7ko01v3yw.json:76`）；`373` 是「**关卡内物件和造物**」（`:88`）。
  **没有「创建者 = 本工程」这样的限定词**，节点**也没有能表达这种限定的入参**（§1：两条都是纯出参）。
- `373` 的出参里有 **`伤害来源`、`归属者实体`**（`mhn7ko01v3yw.json:93`）——这两个字段的存在本身就说明：
  **被销毁的实体可能由别的实体（造物主人、攻击者、玩家）产生**，图是在为「不属于触发者的实体」做通知。
- ⇒ **运行期（游戏进程 + 关卡图）知道一批「本工程从未 create 过」的实体**：用户手摆的、游戏机制生成的、元件型创建出来的（`252/757/256`）、
  `70 创建实体`（要 GUID 预布设）出来的、布设组激活出来的（`178`）……**它们都能被 72/373 看见**。

### 3.2 图不只是「看得见」，还能**删**——`entity.remove` 的原语在图这一侧

同族目录里，**删除/销毁**是**动作节点**（有入参），而事件是**观察节点**（§1）：

| 节点 | defId | 入参 | 出参 | 目录行 |
|---|---|---|---|---|
| `销毁实体` | 69 | `目标实体` | （exec 出） | `NODE-CATALOG.md:692` |
| `移除实体` | 372 | `目标实体` | （exec 出） | `NODE-CATALOG.md:852` |
| `实体移除/销毁时` | 72 | （无） | `事件源GUID` | `NODE-CATALOG.md:695` |
| `实体销毁时` | 373 | （无） | §1 的 9 个 | `NODE-CATALOG.md:853` |

- `69`/`372` 的 `目标实体` 是 `valueType=None/0` 的**自由引用**（`variants/server/bucket-00.json` 中 69、`bucket-04.json` 中 372），
  来源可以是：`373` 的 `事件源实体`、`75 以GUID查询实体`（`NODE-CATALOG.md:698`）、`377/378/379/380 获取…实体列表`（`:857-860`）……
  **没有一条要求「目标必须是本工程创建的」**。
- `72` 只给 `事件源GUID`（**不给实体**），所以收到 72 后若想对那个实体动作，需要 `75 以GUID查询实体` 再解析一次——
  而实体**已销毁**，该查询是否命中是**图内运行期问题**，本项目无真机证据（标：**未验证**）。

### 3.3 两个世界：**编辑态物化集合** vs **运行期实体字典**

工具删的是**编辑器（`BeyondEditor.exe`）里的前端资源节点**（B 的 `BuildOwnedDeleteIndex` 走的是 `WalkEditorGraph`，§2B）；
图事件描述的是**游戏运行期**（`YuanShen.exe`）的实体。两者**不是同一个集合**，仓内有直证：

- **编辑态静态 vs 运行时生成**：`docs/ds-handoff/02-PLATFORM-AND-INTERFACES.md`§3 逐字——
  「早期校准图/路线图在实体创建事件后生成方块。因此**试玩看得到，退出试玩后的编辑画布看不到**，是创建时机带来的行为」。
  ⇒ **图在运行期生成的实体，不进编辑画布**（不进工具的 `WalkEditorGraph` 视野）。
- **同类实测**：`RetireRuntimeSpawns.cs:10-15`——两张「运行时生成图」在关卡开始后**再次生成**平台，而这些平台**另有 34 个静态实体**已烘进存档
  （「six platforms, GIL 34 static entities confirmed in editor」）。⇒ 同一物在两处各有一份：**静态（编辑态、工具可删）** 与 **运行期生成（图侧、工具不可寻址）**。
- **运行期实体字典是动态的**：原生快照读的是游戏进程内的实体字典（`tools/game-executor/native/game_context_snapshot.cpp:215-231`，
  `game_context_snapshot.h:60-70`「the game's own entity dictionary is dynamically sized」），而工具侧的**编辑器前端场景子清单本身还截断 128**
  （`tools/authoring/INTERFACE-INVENTORY.md:25`「前端场景子清单截断128，原生快照512」）。⇒ 工具连「编辑态」这一侧都对大场面有上限。

### 3.4 判决：**不是同一个边界的两面**

用户给的假设是「72/373 与 `entity.remove`『只允许本次……』可能是同一个边界的两面」。**证据不支持这个假设**，方向也不对称：

| 边界 | 范围 | 键在什么上 | file:line |
|---|---|---|---|
| **图事件 72** | **关卡内任意实体**（移除/销毁） | 运行期事实，**无创建者门** | `mhn7ko01v3yw.json:76`；合同 `variants/server/bucket-02.json:1165` |
| **图事件 373** | **关卡内物件和造物**（销毁） | 运行期事实，**无创建者门** | `mhn7ko01v3yw.json:88`；合同 `variants/server/bucket-04.json:6856` |
| **工具 A（crud-probe）** | **本次新增的恰好 1 个**（且 1402/kind0） | 内存基线字典 | `EntityCrudProbe.cs:106-108` |
| **工具 B（owned-ids）** | **编辑态物化的、id 唯一解析到的**任意实体 | id 列表（无所有权门） | `OwnedEntityDelete.cs:52-83,102-108` |
| **工具封装所有权门** | **本次回执 ∩ 新于基线 ∩ 模板一致** | 回执+前后基线 | `cleanup_owned_entities.py:455-545` |

两句话收束：

1. **工具的最强门（A / 封装所有权门）比图事件窄得多**——它连自己**上一次**建的实体都不同意删（基线里有 ⇒ 进不了 `added`）；
   图事件连**用户昨天手摆**的东西销毁都照报。
2. **工具的弱门（B）虽然不限创建者，却被「必须编辑态物化」卡住**——运行时生成物没有前端资源节点，
   B 的 `:71-75` 解析不到，出的是 `unresolved` 整批拒（`:102-108`）。所以 B 也够不到「只在运行期存在」的实体。

⇒ **运行期知道、而工具碰不到的实体，是真实存在的一层**：它们**能被 72/373 观察，也能被 69/372 删除**，
但**没有任何工具路径能按 id 触及它们**（因为工具按编辑态的 id → 前端资源节点解析）。**缺口方向单一：运行期 ⊋ 工具。**

---

## 4. 对清理的意义（把不对称讲白）

**给定约束**：`entity.remove` 的**唯一能触及运行时生成物的原语在节点图这一侧**（`69`/`372` + `75 以GUID查询实体`）；
工具侧的三条删除路径**都只作用于编辑态物化的实体**（A 更窄，只认本次新增）。

因此，收尾清理若**只走工具删除**，会漏掉两类东西：

1. **图在运行期生成的实体**（校准图/路线图建的方块、`252/757/256` 元件型创建、`178` 布设组激活出来的实体、`70` 创建实体出来的实体）。
   它们**试玩看得到、编辑画布看不到**（`ds-handoff/02 §3`），**不在任何工具删除路径的可寻址集合里**。
   ——**移除它们的正确做法是「让它不要生成」**（断开生成图的启动执行边），而不是「建完再删」。
   仓内已有这条正面先例：`RetireRuntimeSpawns.cs:26-84` 退休运行时生成，走的正是**断开 `实体创建时`(71) 的输出执行边 → 分支输入执行边**一条原生 link disconnect，
   **没有删图、没有删节点、没有碰静态实体**。
2. **用户手摆的存量实体**：B 能按 id 删（无所有权门），但**B 不是「只删自己的」**——用它做清理**不能**证明「没碰用户内容」。
   要「只删自己的」，**必须**走 `cleanup_owned_entities.py` / `backend` 的 A..G 腿（§2 尾表），且材料（本次回执 + create 前完整基线）齐全；
   缺 pre-baseline 时 `cleanup_owned_entities.py:535-541` 会 fail-closed **拒**，而不是静默放行。

**一句话纪律**：**「图能观察/能删」≠「工具能删」**。清理时先分清目标实体是**编辑态物化的**（工具可删）还是**运行期生成的**（工具不可寻址，
只能从源头——生成图——关掉）。**不要把 72/373 当成「工具删除的回执事件」**：它们是**运行期**的销毁通知，
说的是「游戏里发生了一次销毁」，**不是**「工具删成功了一次」；两者之间没有引用关系，工具的删除回执字段
（`OwnedEntityDelete.cs:145-149` / `EntityCrudProbe.cs:235-238`）也**从不携带任何图事件 id**。

---

## 5. 未证 / 精确负面（诚实边界）

- **`事件源GUID`（图）与编辑器实体 id（`dictionaryKey`）是不是同一命名空间**：**仓内未找到把两者对上的证据**。
  图的 `事件源GUID`/`以GUID查询实体`(75)/`以实体查询GUID`(76) 是**运行期身份**；工具的 id 是**编辑器前端资源节点的 `ReadCrudKey(model).Id`**
  （`EntityCrudProbe.cs:33-38`）。二者是否恒等，**本检索范围内未找到记录**（`.runtime` 已用 Bash `grep` 覆盖）。**标：未验证。**
- **图节点 72/373 的 `definitionId`（小整数 72/373）在运行期是否按此编号触发**：合同只给「编辑器/离线」的定义与引脚；
  **没有真机证据**证明某次实机销毁会按 373→72 的次序在关卡实体上投递（官方文本给了次序，但那是**文档层**，非本工程真机）。
  **标：文档写了、未真机验证。**
- **「运行时生成物确实不在前端资源树里」**：由 `ds-handoff/02 §3` 的「试玩看得到、退出后编辑画布看不到」+ `RetireRuntimeSpawns` 的静态/生成双份推断；
  **本文件未连桥、未跑 `delete-owned-entity-ids-dry-run` 去实测「给一个运行时生成物的 id 会得到 unresolved」**。**标：强推断、未真机。**
- **测试缺口**（沿用 `ENTITY-DELETE-SCOPE.md:186-198`）：**没有任何测试钉住 `OwnedEntityDelete.cs`/`EntityCrudProbe.cs` 的谓词本身**；
  引用它们的 Python 全是注释。同样地，**没有测试钉住 72/373 与工具删除之间的「无引用关系」**——本文件是该主张的**第一份静态证据整理**。
- **`EntityType==1402`（A 的硬编码）是什么实体类型**：合同/官方文本本读未建立 1402↔类型名映射。**标：未知。**
  （旁证：`RetireRuntimeSpawns.cs` 用 `71` 作事件节点，说明「实体创建时」在本工程图里确实被当作一等事件用——73/72 同族，但**不曾被本工程建过**。）

---

## 6. 证据索引

| 论断 | 证据 |
|---|---|
| 72 引脚（出×1：exec + `事件源GUID`） | `data/node-contracts/variants/server/bucket-02.json:1165`（定义 `definitions/bucket-02.json:590`）；`docs/editor-catalog/NODE-CATALOG.md:695` |
| 373 引脚（出×1：exec + 9 数据出） | `data/node-contracts/variants/server/bucket-04.json:6856`（定义 `definitions/bucket-04.json:2673`）；`docs/editor-catalog/NODE-CATALOG.md:853` |
| 72 范围＝「关卡内任意实体」，接收者＝关卡实体 | `docs/official-docs/chapters/mhn7ko01v3yw.json:75-76` |
| 373 范围＝「关卡内物件和造物」，接收者＝关卡实体 | `docs/official-docs/chapters/mhn7ko01v3yw.json:87-88` |
| 373 先、72 后（销毁次序契约） | `docs/official-docs/chapters/mhn7ko01v3yw.json:80-82` |
| 373 九出参逐字 | `docs/official-docs/chapters/mhn7ko01v3yw.json:93` |
| 接收者随实体类型变（角色→角色图；物件→关卡实体） | `docs/official-docs/chapters/mh3ecor1x5cm.json:50-52` |
| 图侧删除原语 `69 销毁实体`/`372 移除实体`（入参`目标实体`） | `docs/editor-catalog/NODE-CATALOG.md:692,852`；`variants/server/bucket-00.json`(69)、`bucket-04.json`(372) |
| crud-probe 决定行「相对基线恰好 1 个新实体 + 1402/kind0」 | `tools/editor-bridge/Adapter/EntityCrudProbe.cs:106-108`（门 `:102-114`，入口 `:217-239`） |
| crud-probe 拍基线（内存单槽/180 秒） | `EntityCrudProbe.cs:23,31,90-91,149-162` |
| 前端物化门（找不到资源节点就不删） | `EntityCrudProbe.cs:123-147,221-224` |
| owned-ids「边界只有 ID 列表」 | `tools/editor-bridge/Adapter/OwnedEntityDelete.cs:8-27,52-83,87-150` |
| owned-ids 上游形状门 1..64 | `tools/editor-bridge/ManagedBridge/BridgeServer.cs:352`；`elevated-request.py:160-174`；`elevated-runner.ps1:278` |
| 一次性存量删除（1077936132，已过期） | `OwnedEntityRecovery.cs:23-46,74-88` |
| 「NOT ownership-checked」自认 | `backend/cleanup_service.py:8-9` |
| 工具侧三腿所有权门（缺 pre-baseline 即拒） | `tools/game-executor/cleanup_owned_entities.py:455-545`（`:535-541`） |
| 业务侧 A..G 腿 | `backend/cleanup_ownership_legs.py:23-32`；`backend/entity_server.py:1981,2056-2070` |
| INTERFACE-INVENTORY「只允许本次新增探针」 | `tools/authoring/INTERFACE-INVENTORY.md:27`（另 `:25` 前端清单截断128/原生512） |
| 编辑态静态 vs 运行时生成（试玩看得到、编辑画布看不到） | `docs/ds-handoff/02-PLATFORM-AND-INTERFACES.md`§3 |
| 退休运行时生成＝断一条执行边（不删图） | `tools/editor-bridge/Adapter/RetireRuntimeSpawns.cs:10-15,26-84` |
| 运行期实体字典动态、多探针 | `tools/game-executor/native/game_context_snapshot.cpp:215-231`；`game_context_snapshot.h:60-70` |
| 分流生成的三条路（元件型创建 252/757/256；布设组 178） | `docs/research/reverse-eng-20261010/WAVE-SPAWN-PATH.md:29-56` |
| 删除范围详表（同族前作） | `docs/gameplan/ENTITY-DELETE-SCOPE.md`§1–§5 |

---

*本文件由 2026-10-10 会话从仓内合同/官方文本/C# 源码只读整理；未连接桥、未发任何报文、未触碰游戏/编辑器、未写任何存档。
所有引用行号为本次 checkout 实测。凡「有实现没跑过」或「文档写了未真机」的条目已在 §5 标出。*
