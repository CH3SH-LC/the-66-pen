> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #4 全关卡组件扫荡 —— 计划（PLAN，**不执行**）

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。
全部结论来自三处：① 仓内源码（C# / PS / Python）② 仓内真机回执原件 ③ 仓内研究文档。所有行号＝本次 checkout 实测。

> 按 `CLAUDE.md` §一.3：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 本文件描述的是**一个待执行的计划**：其中的命令**本次一条都没跑**。凡引用真机数字，都注明回执原件与出处。

---

## 0. 一句话

`inspect-entity-components` 是**只读、一次解析一个实体**（`EntityComponentProbe.cs:124`）；它**一次调用只吃一个 `entityId`**。
所以「扫荡整个关卡」＝**对每个实体 id 各发一条命令**。这次扫荡的价值不在"再读一遍"，而在**把「一张世界里哪些实体带组件、带的什么」变成一份对照表**——
从而把**人在编辑器里手工加的组件**（我们造不出的那一半，`CLAUDE.md` §五/§六(a)）从机器造的那一半里**分离出来**。

**这条扫荡能读、"加组件"不能写**——这是 §六(a) 的不对称：**读存在、加不存在**。所以扫荡是**取证**，不是"补齐能力"。

---

## 1. 每实体命令的**精确**形状（源码原文）

### 1.1 服务端：op 名 + 请求字段闭集

**派发点**：`tools/editor-bridge/ManagedBridge/BridgeServer.cs:306`

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**请求字段（闭集，多一个/少一个/重复都拒）** —— `Adapter/EntityComponentProbe.cs:50-59`：
| 字段 | 类型 | 约束 | 出处 |
|---|---|---|---|
| `op` | string | 必须 = `"inspect-entity-components"` | `BridgeServer.cs:306` |
| `id` | string | 调用方随带的回显 id（任意） | `EntityComponentProbe.cs:52`（允许集） |
| `nonce` | string | = 本次 scope 的 `bridge-settings.json.nonce`（64-hex） | `call-bridge.ps1:25` |
| `entityId` | number | **非零 uint32** | `EntityComponentProbe.cs:57`（`COMPONENT_PROBE_REQUIRED_UINT:entityId`） |

允许集原文 = `{"id","op","nonce","entityId"}`（`EntityComponentProbe.cs:52`）；未知/重复 → `COMPONENT_PROBE_UNKNOWN_OR_DUPLICATE_FIELD:<name>`（`:56`）。
**探针不收目标、名字、路径——只收一个实体 id。** 集合上限 `ComponentCap = 1024`（`:36`），超限**拒绝**（不截断，`:143-144`）。

**一个实体**的线上报文（由 `call-bridge.ps1` 组装）：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

`call-bridge.ps1:25` 起 `{id,op,nonce}`；`:42-43` 在 `op -ceq 'inspect-entity-components'` 分支里 `$request['entityId']=$EntityId`，
且 `if($EntityId -eq 0){throw 'ENTITY_COMPONENT_ID_REQUIRED'}`（**客户端侧也拦 0**，与服务端 `:57` 对齐）。

**回执行形状**（`EntityComponentProbe.cs:150-173`）：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 1.2 客户端：两条到达路径（命令逐字）

`call-bridge.ps1` 的 `ValidateSet` 已含 `'inspect-entity-components'`（`call-bridge.ps1:1`），并已声明 `[uint32]$EntityId`（同 `:1`）。

- **路径 A —— 直连命名管道（不经 helper）**（本文件对每实体的**首推命令**）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  回执**自动落盘**到 `.runtime/editor-bridge/runs/<runId>/inspect-entity-components-response.json`（`call-bridge.ps1:55`）。
  该 op 不在 60 s 超时名单里 ⇒ 用默认 **10 s** 窗口（`call-bridge.ps1:51-52`）；超时抛 `RESPONSE_TIMEOUT_NOT_PROOF_OF_NO_EFFECT`（**≠ 没生效**）。
- **路径 B —— 经 helper 队列**（**管线已在树内**，见下更正）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  **现状（本次实测，与旧文档相反）**：`entityId` 管道**已经接好**——
  - `elevated-request.py:544-545` 的 `call` 子命令**已声明 `--entity-id`**（`type=int`），`validate_call_entity_id`（`:220-236`）只在 `op -ceq 'inspect-entity-components'` 时放行；
  - `elevated-runner.ps1:224` 的字段闭集**已为该 op 加宽 `'entityId'`**，`:285-286` 把 `$callArguments['EntityId']=[uint32]$value` 交给 `call-bridge.ps1`；
  - 验收测试 `tools/editor-bridge/tests/test_component_op_plumbing.py` **本次实测 5 tests OK**（曾"故意红"，现绿）。
  ⇒ **`docs/gameplan/PIN-COST.md` §2/§3 与 `COMPONENT-OP-PROOF-PLAN.md` §5.1 的"缺 `--entity-id`、要补 3 处"已过期**（见 §6 更正清单）。

> **两条路径的差别只在传输，不在报文**：两者都经 `call-bridge.ps1` 用同一 `-EntityId` 组装 §1.1 的那一条闭集。
> **路径 A 不碰 helper**（`call-bridge.ps1` 不在 pin 集，`elevated-runner.ps1:124` 每请求现读它）；
> **路径 B 若 helper 是在上面这几处改动落盘之前启动的，需重启一次**（改的文件在 pin 集，`elevated-runner.ps1:576`）。

### 1.3 一个**必须处理**的落盘冲突

`call-bridge.ps1:55` 把回执写到 `runs/<runId>/<Operation>-response.json`——**文件名只带 op，不带实体 id**。
⇒ **连续调用会互相覆盖**。扫荡**每读一个实体，必须立刻把该回执拷到 §4.3 的产物路径**，否则只剩最后一个。

---

## 2. 当前实体列表从哪来（**对任务假设的一处诚实更正**）

任务说「读 `tools/gameplan/live.py` 拿到当前实体列表」。**读源码后必须更正**：

`tools/gameplan/live.py` 的 `read_live()`（`:120-157`）返回的 `LiveState` 里，实体相关字段**只有一个计数**：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

`entities` 取自 discovery 回执的 `observation.get("entities")`（`live.py:150`），而该值在 discovery 侧是
`acceptance.get('entityCount')`（`discover_current_level.py:590`）——**一个整数**。

**per-entity 的 id 列表在别处**：readonly 快照里。
`build_readonly_profile.py:281` 明写 `ids=[row['id'] for row in snapshot['entities']]`，
且 `:340` 把该快照写成 `run/readonly-snapshot.json`。实体 id 的来源在原生侧
`native/game_context_snapshot.cpp:215`（`entity.id`，从 owner 的 `GS_OWNER_ID_OFFSET` 读出，`GE_ID_READ`）。

**⇒ 正确取法（两步）**：
1. `python -m tools.gameplan.live` → 拿 `level.levelId`、`level.entities`（个数）、**`level.runDir`**；
2. 打开 **`<runDir>/readonly-snapshot.json`**，读 `snapshot["entities"][*]["id"]` → **这就是要扫的 id 列表**。

`live.py` 因此是**指针**（给出当次 discovery 的 run 目录与计数自洽校验 `len(ids)==entities`），**不是 id 列表本身**。
本计划不复制上一轮的 id：**每次扫荡先 `live`，再用当次 `runDir`**（纪律：关卡 id 是存档的函数，`live.py:25-27`）。

---

## 3. 成本与分块（数字 + 出处）

### 3.1 两个硬约束

| 约束 | 值 | 出处 |
|---|---|---|
| 每次派发重算 pin 哈希 | **2082 pin ≈ 16 s** | `CLAUDE.md` §三；`docs/gameplan/REAL-MACHINE-RUNBOOK.md:106` |
| scope 租约 | **5 分钟（300 s）** | `new-scope.ps1:27`（`expiresUtc=UtcNow+5min`）；`PIN-COST.md:184`；`CLAUDE.md` §三 |

`call-bridge.ps1` 在 scope 过期后即抛 `SCOPE_EXPIRED`（`call-bridge.ps1:7`：`if([DateTimeOffset]::UtcNow -ge [DateTimeOffset]::Parse($scope.expiresUtc)){throw 'SCOPE_EXPIRED'}`）。
所以「一个 scope = 一个租约 = 一段预算」。

### 3.2 分块算术（按 16 s / 派发）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- **N = 11**（demo 建前实体数，见 §3.3）→ **1 个 scope**（11 ≤ 16）。
- **N = 12**（demo save 后实体数）→ **1 个 scope**。
- **N = 69**（当次 discovery 实测实体数，见 §3.3）→ `ceil(69/16) = 5` 个 scope。

### 3.3 **真实数字**（回执原件）

| 数字 | 含义 | 回执原件 |
|---|---|---|
| **entities 11** | demo 关卡 `1073741842` 建**前**的实体数 | `.runtime/authoring/requests/fc6dcaf74a33461d9648f94f5e2066ed/result.json` → `backend.entities`（同 `backend.actionStatus 0`、`backend.levelId 1073741842`、`backend.entityId 1077936129`）；引于 `docs/gameplan/README.md:178`、`VERTICAL-SLICE.md:44` |
| **entities 12** | 同一关卡 native `save` 后 | `.runtime/authoring/requests/24888599a15c40899207c6fb41c75604/result.json` → `backend.entities`；引于 `docs/gameplan/README.md:198` |
| **69 entities** | 一次排队 readonly inspect 的当次实体数（关卡 `1073741839`） | `tools/game-executor/discover_current_level.py:43`（「levelId 1073741839 with 69 entities from a real in-process read」，S08 live preflight MEASURED 2026-10-02） |

**扫荡要用当次数**：`live.py` 报的 `entities` 必须与 `<runDir>/readonly-snapshot.json` 的 `len(snapshot["entities"])` **逐字相等**（`build_readonly_profile.py:277` 就是这个 check），不等即停——不许用记录值。

---

## 4. 可复制的执行序列（**本文不运行**）+ 产物路径

> 前置一次 UAC（**仅路径 B 需要**）：`docs/gameplan/PIN-COST.md` §3 的九步配方；路径 A 只需已存在的 runId。

### 4.1 取当次实体 id 列表（只读）

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 4.2 （仅路径 B）entityId 管线——**已在树内，无需再改**
`elevated-request.py` 的 `call` 已有 `--entity-id`（`:544-545`）；`elevated-runner.ps1` 已为该 op 加宽字段闭集（`:224`）并把 `EntityId` 交给 `call-bridge.ps1`（`:285-286`）；
验收测试 `tools/editor-bridge/tests/test_component_op_plumbing.py` **本次实测 5 tests OK**。
**唯一前置**：若正在运行的 helper 是在上述改动**落盘之前**启动的，则因这两个文件在 pin 集（`elevated-runner.ps1:576`）**必须重启一次**（配方 `docs/gameplan/PIN-COST.md` §3）。
（旧文档 `PIN-COST.md` §2/§3、`COMPONENT-OP-PROOF-PLAN.md` §5.1 说"缺 `--entity-id`、要补 3 处"——**已过期**。）

### 4.3 逐实体扫荡并把回执**即刻**另存（每 scope ≤ 16 个）

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

**换 scope**（若 N > 16）：`python -B tools/editor-bridge/elevated-request.py load --target-pid <editorPid>` → 新 `<runId>` → 继续下一批 ≤16。
（同一编辑器进程若已注入过 R269，须先 `next-revision.ps1` 升 R270 才能再注入——`CLAUDE.md` §三、`PIN-COST.md` §5。）

### 4.4 产物路径（全部工程内）
| 产物 | 路径 | 内容 |
|---|---|---|
| 每实体回执 | `.runtime/scratch/component-sweep/<levelId>/entity-<entityId>.json` | 该实体原始回执（`ok/status/componentCount/components[]`） |
| 汇总（追加式） | `.runtime/scratch/component-sweep/<levelId>/sweep.jsonl` | 每行一实体：`{entityId, entityName, componentCount, components[], status}` |
| 扫荡摘要 | `.runtime/scratch/component-sweep/<levelId>/sweep-summary.json` | `{levelId, runDir, entityTotal, entitiesRead, scopes, componentBearing, positive[]}` |
| 桥侧原始留存 | `.runtime/editor-bridge/runs/<runId>/inspect-entity-components-response.json` | 仅**最后一个**（会被覆盖，勿依赖） |

---

## 5. 什么算**正结果**（提示：不是"跑通了"）

**一次 `ok:true` 只证明"这一读成功"**（`CLAUDE.md` §四：`ok:true` 单独不证明任何持久化）。扫荡的**正结果**是下面任一条：

1. **一个有组件的实体**：某实体 `componentCount ≥ 1` 且 `components[]` 至少一行 `{id,enabled,x,y}`——这坐实**枚举路径通、行形状对**（`COMPONENT-OP-PROOF-PLAN.md` §2.1 的"最小完整证据要至少一行"）。
2. **一个"人配的组件"**（**本扫荡的真正目标**）：`components[]` 里出现一个**不是我们造图时写进去的** `componentId`——
   判据是**交叉对照**：该实体**不在**本工程的 create 回执集合里（如 `fc6dcaf74…`），或其组件行的 `enabled/x/y` 呈**人工值**（非默认）。
   ⚠️ `componentIdSpace:"editor-enum-value-or-native-index-UNVERIFIED"`（`EntityComponentProbe.cs:167`）——**组件 id 的语义未坐实**，
   所以判"人配的"必须**同时**给：①该实体来源（我方 create 回执否）②组件 id 与已知编号的对照。**不许只凭数字下结论。**
3. **判决性变体**（最强，`COMPONENT-OP-PROOF-PLAN.md` §2.1）：扫前一次 → **人工**在编辑器点一次「添加通用组件」 → 扫后一次，
   看同一实体的 `componentCount` **增长**、多出哪一行。这条把「**人加组件**」这件事直接照出来——因为**工具加不了**（`CLAUDE.md` §六(a)），人加的才动。
4. **完整覆盖**：`entitiesRead == entityTotal`，且未知/歧义（`COMPONENT_ENTITY_NOT_FOUND`、`COMPONENT_ENTITY_ID_NOT_UNIQUE`）全部**有具名码**归零。

**反例（不算正结果）**：`componentCount == 0` 只说明"这实体没组件"或"读到了空集合"，**不足以**坐实行形状；
`gameEffectVerified/persistentSaveVerified` 恒为 `false`（`EntityComponentProbe.cs:172-173`）是**正常的**——读不是变更。

---

## 6. 证据索引 + 更正清单

**证据索引**

| 论断 | 证据（file:line / 路径） |
|---|---|
| probe 派发 case | `ManagedBridge/BridgeServer.cs:306-322` |
| probe 请求字段闭集 / 必填 uint | `Adapter/EntityComponentProbe.cs:50-59`（`:52` 允许集、`:57` 必填） |
| probe 回执行形状 | `Adapter/EntityComponentProbe.cs:150-173`（`:161` status、`:167` idSpace） |
| 集合上限 1024 / 拒绝不截断 | `Adapter/EntityComponentProbe.cs:36,143-144` |
| 客户端 `-EntityId` / 0 拦 / 落盘 / 超时 | `call-bridge.ps1:1,42-43,51-52,55` |
| 路径 B 管线**已接好** | `elevated-runner.ps1:224,285-286`；`elevated-request.py:220-236,544-545`；`tests/test_component_op_plumbing.py`（本次 **5 OK**） |
| `live.py` 只给计数不给 id | `live.py:51,150`；`discover_current_level.py:590` |
| 实体 id 列表在快照 | `build_readonly_profile.py:281,340`；`native/game_context_snapshot.cpp:215` |
| 16 s / 派发、5 min 租约 | `CLAUDE.md` §三；`REAL-MACHINE-RUNBOOK.md:106`；`new-scope.ps1:27` |
| 直连接口免重启（不在 pin 集） | `elevated-runner.ps1:124,576`；`PIN-COST.md` §2 |
| demo 实体数 11→12 | `.runtime/authoring/requests/fc6dcaf74…/result.json`、`24888599…/result.json`；`docs/gameplan/README.md:178,198` |
| 当次实体数 69 | `tools/game-executor/discover_current_level.py:43` |
| 组件「读存在、加不存在」 | `CLAUDE.md` §五、§六(a) |

**更正清单（本文件发现的、与任务假设或树内现状不一致处）**
1. **`live.py` 不给"实体列表"，只给"实体个数 + runDir 指针"**（§2）。任务里"读 live.py 拿实体列表"**不成立**；
   id 列表在 `<runDir>/readonly-snapshot.json` 的 `snapshot.entities[*].id`。**这是本计划对任务假设的正式更正。**
2. **16 s 是"带 pin 锁的派发"的成本，`call` 分支并不锁 pin**（`elevated-runner.ps1` 里 `Lock-DispatchPins` 只出现在
   `:709`（native-scene）、`:773`（author-graph）、`:899`（native-reopen-reconcile）；`kind=call` 分支 `:857-873` **不锁**）。
   ⇒ §3.2 的 **16 s/次**是**保守上界**；真机 `call` 类回执实测 **0.68–0.99 s/次**
   （`.runtime/editor-bridge/demo-game/20260918T162631Z-verify/run-report.json` 的 `seconds`）。
   **本计划按保守上界分块（16/scope）**；若确认 `call` 不付 pin 代价，实际可每 scope 远多于此——但**真正绑死的是 5 min scope 租约**，与单次耗时无关。
   这条以**代码现状为准**：任务给的"每次 16 s"是**上界预算**，不是**实测调用耗时**。
3. **回执落盘同名覆盖**（§1.3）：`call-bridge.ps1:55` 只按 op 命名，扫荡必须**即刻另存**，否则只剩最后一个。
4. **`entityId` 队列管线已在树内，旧文档过期**（§1.2/§4.2）：`elevated-request.py:544-545` 已有 `--entity-id`、
   `elevated-runner.ps1:224` 已加宽字段闭集、`:285-286` 已把 `EntityId` 传给 `call-bridge.ps1`，
   验收测试 `test_component_op_plumbing.py` **本次实测 5 tests OK**。
   ⇒ `docs/gameplan/PIN-COST.md` §2/§3（"缺 `--entity-id`、要补 3 处、改它要一次 UAC"）与
   `COMPONENT-OP-PROOF-PLAN.md` §5.1（"补 3 处管道"）**均已过期**，建议由拥有者改。

---

*本文件由 2026-10-10 会话从仓内源码与真机回执原件只读整理；**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档**。
所有引用行号为本次 checkout 实测。凡"N 命中 0"的均写明检索范围；凡"有实现没跑过"的一律标未验证。*
