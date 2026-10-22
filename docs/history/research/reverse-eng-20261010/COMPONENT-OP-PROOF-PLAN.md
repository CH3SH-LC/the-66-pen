> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #2 造 — 组件 op 的真机取证计划（`EntityComponentProbe` / `EntityComponentDelete`）

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。
证据来源只有三处：① 仓内 C#/PS/Python 源码 ② 仓内研究文档 ③ **已构建产物 `ManagedBridge/bin/.../Miliastra.EditorBridge.<rev>.dll` 的字符串堆**（Python 读字节，非运行；`<rev>` 由 csproj `AssemblyName` 解析，本文写作时是 `Net8R269`，接线后已升）。
本文件**只读不写**，仅新增本文件本身。

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 本文件的一切结论都是**静态**（读源码 / 读构建产物 / 读研究文档）；**没有任何一条是本节真机跑出来的**。
> 凡"有实现、没跑过"的，一律标 `未验证`；凡"N 命中 0"的，均写明**检索范围**与**盲区**。

---

## 0. 一句话结论

| | 读 `EntityComponentProbe` | 删 `EntityComponentDelete` |
|---|---|---|
| 源码存在 | ✅ `Adapter/EntityComponentProbe.cs`（175 行，`:124` 起） | ✅ `Adapter/EntityComponentDelete.cs`（250 行，`:176` 起） |
| **已编译进当前 payload DLL**（修订名由 csproj `AssemblyName` 解析，**勿硬编码**；本文写作时是 `Net8R269`） | ✅ **是**（字符串堆含 `inspect-entity-components`，见 §1.3） | ✅ **是**（**2026-10-10 晚间接线**：已在 `.csproj` 的 `<Compile>` 里，当前 DLL 字符串堆含 `delete-entity-component`） |
| 桥有派发 `case` | ✅ `BridgeServer.cs:306-322` | ✅ `BridgeServer.cs:324`（`delete-entity-component`） |
| CLI 白名单含它 | ✅ `call-bridge.ps1:1`（`ValidateSet`） | ✅ `call-bridge.ps1:1`（`ValidateSet`）+ `:41/:49` 分支；队列字段见 `elevated-runner.ps1:196-224,263-266`、`elevated-request.py:232,244-256` |
| 读组件模型可解析 | ✅ 走**类型化 71 常量**（`Editor().GetType(...)`），不走绑定档 | ❌ **读半仍未绑定**：`ComponentIds()` 抛 `COMPONENT_MODEL_READER_UNBOUND`（§1.2 gap-4）⇒ 派发前 fail-closed |
| 变成"能力"还差几步 | **1 步真机运行**（外加 §5 的 `entityId` 管道小事） | **1 步真机运行**（前提：先补上读半的 2 个未绑定符号，否则 `inspect`/`delete` 两条动作都在派发前被拒） |

**⇒ 本计划的标题句（2026-10-10 晚间更新）**：**两半现在都已"编译且接线"，都只差一次真机运行。** 早先的
「读是"编译过了、只差跑一次"；删是"连编译都没进去"」已**过期**——`EntityComponentDelete.cs`（op `delete-entity-component`）
**已进 `.csproj` 的 `<Compile>` 集、`BridgeServer.cs:324` 有 `case`、`call-bridge.ps1` 白名单与队列字段齐备、当前 payload DLL 含该字面量**。
两半**唯一的区别**只剩：删的**读半仍卡在 `COMPONENT_MODEL_READER_UNBOUND`**（`ComponentIds()`），故 `inspect`/`delete`
两条动作都在派发前 fail-closed——**这不再是"没编译"，而是"绑不上"**。旧标题句当年的错误形状是「把两半混写成同一句」，
且方向是**抬高删**；今天两半状态**确实相同**（都已编译、都未真机），由 `tools/gameplan/tests/test_doctrine.py::ComponentOpCompileStatus` 钉住。

---

## 1. 两个适配器**精确**的请求形状（file:line）

### 1.1 读 —— op 名 `inspect-entity-components`

**派发点**：`tools/editor-bridge/ManagedBridge/BridgeServer.cs:306`

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**请求字段（闭集，多一个少一个都拒）** —— `Adapter/EntityComponentProbe.cs:50-59`：
| 字段 | 类型 | 约束 | 出处 |
|---|---|---|---|
| `op` | string | 必须 = `"inspect-entity-components"` | `BridgeServer.cs:306` |
| `id` | string | 调用方自带的回显 id，任意 | `EntityComponentProbe.cs:52`（允许集） |
| `nonce` | string | = 本次 run 的 `bridge-settings.json.nonce`（64-hex） | `BridgeServer.cs:247`、`new-scope.ps1:22-25` |
| `entityId` | number | **非零 uint32** | `EntityComponentProbe.cs:57`（`COMPONENT_PROBE_REQUIRED_UINT:entityId`） |

允许集原文：`{"id","op","nonce","entityId"}`（`EntityComponentProbe.cs:52`）；未知或重复字段抛
`COMPONENT_PROBE_UNKNOWN_OR_DUPLICATE_FIELD:<name>`（`:56`）。**探针不接收目标、名字、路径。**

**回执字段**（`EntityComponentProbe.cs:150-173`）：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


> ⚠️ **不实候选的一处**：`COMPONENT-WRITER-MINE.md:400-404` 预测回执行是 `{componentId, enabled}`；
> **适配器实际回的是 `{id, enabled, x, y}`**（`:150-156`）。**以适配器为准**，本计划按 `{id,enabled,x,y}` 取证。
> 集合上限 `ComponentCap = 1024`（`:36`），超限抛 `COMPONENT_COLLECTION_CAP_EXCEEDED`（**拒绝，不截断**，`:143-144`）。
> 读半只解析**类型化 71 常量**（`ComponentCollectionType71`/`EntityComponentsField71`/`ComponentIdField71`…，`:24-32`），
> 只经 `Editor().GetType(...)`（`:64-96`），**不经绑定档**；唯一用 `B()` 的是 boxed 值成员名 `VpIiRZgdEln`（`:89,:119`），
> 已在绑定档中（本文实测 `VpIiRZgdEln` 计 2 命中）。

### 1.2 删 —— op 名 `delete-entity-component`（**2026-10-10 晚间接线**）

> **【2026-10-10 晚间更新】** 本节写作时「删」这条 op **没有名字、没有落点**（op 名尚不存在）。**当晚已接线**：
> `BridgeServer.cs:324` 有 `case "delete-entity-component"`，`call-bridge.ps1:1` 的 `ValidateSet` 收该 op、`:41/:49` 有分支，
> 队列字段（`elevated-runner.ps1:196-224,263-266`、`elevated-request.py:232,244-256`）齐备，当前 payload DLL 的字符串堆含
> `delete-entity-component`（**修订名由 csproj `AssemblyName` 解析，勿硬编码**）。下文「四个独立缺口」是**当时**的盘点，
> **gap-1/2/3 已闭合**（见各条前标注）。

**核心事实（写作时，现已改）**：`BridgeServer.cs` 的 switch 里**没有**指向 `_adapter.EntityComponentDelete(...)` 的 `case`；
对 `tools/ scripts/ docs/ backend/ bridge/` 做 `grep -rn "EntityComponentDelete\|ValidateEntityComponentDelete\|delete-entity-component"`
**除 `Adapter/EntityComponentDelete.cs` 自身外 0 命中**。⇒ 当时「删」这条 op **没有名字、没有落点**。

**若按 `EntityComponentDelete.cs` 自身实现，它期望的请求形状是**（`ValidateEntityComponentDelete`，`:79-97`）：
| 字段 | 类型 | 约束 | 出处 |
|---|---|---|---|
| `id` / `op` / `nonce` | string | 同 §1.1（`op` 值本身**未校验**） | `:87` 允许集；文件里无反查 `op` 值 |
| `action` | string | **∈ {`"inspect"`, `"delete"`}** | `:85-86`（`COMPONENT_ACTION_UNSUPPORTED`） |
| `probeId` | string | **32-hex Guid "N"** | `:93`（`COMPONENT_PROBE_ID_INVALID`） |
| `entityId` | number | **非零 uint32** | `:83-84,:94` |
| `componentId` | number | **仅 `action=="delete"` 时必填**；非零 uint32 且 **≤ int.MaxValue** | `:88,:95-96`（`COMPONENT_ID_OUTSIDE_INT32`，因后端 `param_shape` 是 int32） |

底层派发（`DispatchComponentDelete`，`:160-174`）与桥在用的 `EntityFactionProbe.cs:152` **同族同形**：
`producer.<Ikci0qkvMZX>( "beyondEditObjService", "DeleteComponentForEditObj", null, List<Param>[uint(entityId), uint(componentId)] )`
（`EntityComponentDelete.cs:169-173`；后端 `command_route` id4 `param_shape=(int32 实体id, int32 组件id)`，
`COMPONENT-WRITER-MINE.md:236-238`）。

**⇒ delete 达到"能发一条"前的四个独立缺口**：

- **gap-1（编译）【已闭合】**：`tools/editor-bridge/ManagedBridge/Miliastra.EditorBridge.csproj` 的 `<ItemGroup>` 现共 **53** 条 `<Compile Include=...>`，
  **最后一条是 `../Adapter/EntityComponentDelete.cs`**（本文写作时是 52 条、以 `../Adapter/EntityComponentProbe.cs` 收尾；2026-10-10 晚间接线补入）。
  `Adapter/*.cs` 是显式列单，**不在列单里就编译不进去**——`next-revision.ps1:127-131` 的注释原文即此意。
- **gap-2（编译产物）【已闭合】**：接线前那版 `ManagedBridge/bin/Release/net8.0-windows/Miliastra.EditorBridge.<rev>.dll`（写作时 `<rev>`=`Net8R269`，2026-10-10 03:00 构建）的字符串堆里，
  `EntityComponentDelete`（ASCII，类型名走 `#Strings`）**0 命中**、`COMPONENT_MODEL_READER_UNBOUND`（UTF-16，字面量走 `#US`）**0 命中**
  ⇒ **当时 delete 未被编译进载荷**。**接线后当前 payload DLL（`<rev>` 由 csproj `AssemblyName` 解析，勿硬编码）的字符串堆含 `delete-entity-component`**；
  inspect 侧仍含 `inspect-entity-components`（UTF-16）、`entity-components-editor-model-read-only`（UTF-16）、`COMPONENT_PROBE_UNKNOWN_OR_DUPLICATE_FIELD`（UTF-16）。
- **gap-3（路由/白名单）【已闭合】**：接线前 `BridgeServer.cs` switch 无 `case`；`call-bridge.ps1:1` 的 `ValidateSet` 无该 op；
  而 `elevated-runner.ps1:123-129` 的 `Get-AllowedOps` **正是**去读 `call-bridge.ps1` 的 `ValidateSet`——
  所以经 helper 派发会先抛 `OP_NOT_ALLOWED:<op>`（`elevated-runner.ps1:861`）。**2026-10-10 晚已补：`BridgeServer.cs:324` 有 `case "delete-entity-component"`、
  `call-bridge.ps1:1` `ValidateSet` 收该 op、`:41/:49` 有分支。**
- **gap-4（读半未绑定，即使前三个都补上也仍拒）【仍存在——这是接线后唯一挡路的缺口】**：`ComponentIds()`（`:113-142`）经
  `ComponentBinding()`（`:102-107`）向绑定档要 `ComponentListField71="JdaiSnpkbfl"` 与 `ComponentIdGetter71="b1EiCj8P44N"`。
  本文实测 `EditorBindingProfile.Generated.cs` 中 `JdaiSnpkbfl` **计 0**、`b1EiCj8P44N` **计 0**（同一文件里
  `Ikci0qkvMZX`=2、`bKliA0tj1p1`=2、`VpIiRZgdEln`=2、`PIWXZgk5Tyr`=2 都已绑定）。
  ⇒ `ComponentBinding()` 命中 `ErrorPrefix` 即抛 **`COMPONENT_MODEL_READER_UNBOUND`**（`:105-106`），
  而 `EntityComponentDelete` 的 **`inspect` 与 `delete` 两条动作都在派发前先调 `ComponentIds(model)`**（`:191`），
  ⇒ **两条动作都会 fail-closed 拒绝**——它**绝不**把"读不到"当"没有组件"。这层设计是对的（`Claude.md` §六 纪律），
  但**也意味着 delete 适配器即便接线后，在当前树里仍一次都发不出去（gap-4 读半未绑定）**。文件头（`:12-33`）自己写的 `UNVERIFIED` 与 `READER NEGATIVE` 与此完全一致。

### 1.3 三层门（谁在拦）

| 层 | 读 probe | 删 delete | 出处 |
|---|---|---|---|
| 编辑桥 switch | ✅ `case` 在 | ✅ `case "delete-entity-component"` 在（2026-10-10 晚间接线） | `BridgeServer.cs:306` / `:324` |
| call-bridge `ValidateSet` | ✅ 在 | ✅ 在 + `:41/:49` 分支 | `call-bridge.ps1:1,41,49` |
| helper `Get-AllowedOps` | ✅（它读上面的 ValidateSet） | ✅ 同上 | `elevated-runner.ps1:123-129` |
| helper `call` 字段闭集 | ✅ `{kind,runId,op,entityId}`（队列管线已在树内） | ✅ 追加 `{action,probeId,componentId}` | `elevated-runner.ps1:196-224,263-266`；`elevated-request.py:232,244-256` |

> **【2026-10-10 晚间更新】原「helper `call` 字段闭集带不了 `entityId`、经 helper 跑 probe 会缺参」已过期**：
> 队列管线现已在树内——`elevated-runner.ps1:263-266` 对 `inspect-entity-components` 放行 `{kind,runId,op,entityId}`，
> 对 `delete-entity-component` 放行 `{kind,runId,op,entityId,action,probeId,componentId}`；`call-bridge.ps1:41-44`
> 仍强制 `-EntityId`（否则抛 `ENTITY_COMPONENT_ID_REQUIRED`）。⇒ **经 helper 跑 probe 不再缺参**（`COMPONENT-SWEEP-PLAN.md` §6）。

---

## 2. 把每一侧变成"能力"的**最小证据**

> 判据沿用 `CLAUDE.md` §四与 `docs/gameplan/REAL-MACHINE-RUNBOOK.md:198-199`：**`ok:true` / `actionStatus:0` / 一次导出，
> 单独一个都不算完成。** 读侧是只读，一次**形状正确、字段齐全、且能对着一个已知有/无组件的实体复核**的回执即可；
> 删侧是写，还要加**独立读回 + `.gil` 字节差分**。

### 2.1 读：`inspect-entity-components`

- **调哪个 op**：`inspect-entity-components`（§1.1）。
- **打在哪个实体**：**`entityId = 1077936129`**。
  **它的"归属记录"在这几处**（本文只读复核）：
  - 单实例创建的**落盘回执**：`tools/game-executor/README.md:14` ——「单实体创建并保存 `1077936129`，模板 `20001034`；11→12，几何及目录登记通过」，
    原件 `.runtime/game-executor/r168-created-save-verification.json`（磁盘存在，3507 B / 2026-09-26）。
  - 同一条被 `MINED-INTERFACES.md:90` 引作真机证据：`actionStatus 0 / called 1 / entityId 1077936129`。
  - 编排层的归属判据：`tools/game-executor/run_live_crud_acceptance.py:436-437`（探针目标 id **必须等于** native create 回执的 `entityId`）
    与 `:445`（该 id **不得在探针基线**里）。
  - ⚠️ **归属是"按关卡"的、且 id 跨关卡复用**：`run_parameter_matrix.py:242-253` 把 `1077936129/130/131` 记成
    **关卡 `1073741839` 里必须保留的既有内容**（`round_materials.py:90` 同）；`ENTITY-DELETE-SCOPE.md:147` 明写 id 不是对象的属性。
    ⇒ **"我们拥有 1077936129"必须由当次 create 回执 + 当次基线差集重新证明**，不能靠数字本身。**读**因此**不依赖**归属（只读、按注册表 id 解析）；
    **写**依赖（见 §2.2）。
- **回执必须含什么才算**：
  1. `ok:true` 且 `status` **逐字** = `"entity-components-editor-model-read-only"`；
  2. `entityId` = 请求的那个；
  3. `components` 是**数组**，每行是 `{id:<uint>, enabled:<bool>, x:<double>, y:<double>}`（`EntityComponentProbe.cs:150-156`）；
  4. `nativeMutationInvoked:false`、`sentToGame:false`、`localModelWritten:false`（`:168-170`）；
  5. 原始回执**留盘**（`call-bridge.ps1:55` 已把回执写进 `.runtime/editor-bridge/runs/<runId>/inspect-entity-components-response.json`）。
- **`componentCount == 0` 算不算证据？** —— **算"枚举路径通"，但不足以坐实"行形状"**。
  组件集合对某些实体本就可能是空的。**最小完整证据**要**至少一行**：优先挑一个**已知挂过组件**的实体（例如用户侧带商店/背包的实体，
  或按 `COMPONENT-WRITER-MINE.md:413-416` 的**判决性变体**：跑前跑后各一次，中间**人工**在编辑器点一次「添加通用组件」，
  看 `componentCount` 是否增长）。**`gameEffectVerified`/`persistentSaveVerified` 为 `false` 是正常的**，
  不阻断"读是能力"——读不是变更（`Claude.md` §六(a) 的不对称：读存在、加不存在）。

### 2.2 删：`EntityComponentDelete`（2026-10-10 晚间接线；仅剩 §1.2 gap-4 读半未绑定）

- **调哪个 op**：`delete-entity-component`（**2026-10-10 晚间已命名并接线**；本文写作时它尚不存在、需新命名）。它现已被
  `BridgeServer.cs:324` 的 `case`、`call-bridge.ps1:1` 的 `ValidateSet`、`elevated-runner.ps1:263-266` 的字段闭集三处接纳。
- **打在哪个实体**：**不是**"随便一个我们拥有的 id"，而是**本次 run 的 CRUD 探针目标**。
  原因：`ComponentOwnedTarget()`（`EntityComponentDelete.cs:147-155`）**调用 `CheckCrudTarget()`**，
  而 `CheckCrudTarget()`（`EntityCrudProbe.cs:102-114`）要求：探针已开始（`:90`）、180 秒窗口内（`:91`）、
  上下文与状态未变（`:93-94`）、**基线里每个实体仍在且身份未变**（`:96-98`）、
  且「当前 − 基线」**恰好 1 个**新实体、其 **`EntityType==1402 && InstanceKind==0`**（`:106-108`）、
  无同名 `MW_CRUD_Probe` 冲突（`:109-110`）、名字 ∈ {原名,`MW_CRUD_Probe`}（`:111-112`）。
  ⇒ **要删的那个实体，必须是"`begin-entity-crud-probe` 之后才出现、且被 `inspect-entity-crud-probe` 登记成唯一新增"的实体。**
  一个**早就在关卡里**的实体（含 `1077936129` 若它先于本期探针基线存在）**永远进不了 `added`**，会被拒
  （`COMPONENT_OWNED_UNBOUND_TARGET_REQUIRED`，`:153`）。**这正是 §3 要的 review/baseline 纪律在 C# 层的样子。**
  - 归属链（编排层）：`run_live_crud_acceptance.py:436-437`（目标 id == create 回执 `entityId`）、`:445`（id 不在基线），
    `CREATE_TEMPLATE_ID=20001034`、`CRUD_ENTITY_TYPE=1402`、`CRUD_INSTANCE_KIND=0`（`:53-55`）。
- **回执必须含什么才算**：
  1. `ok:true` 且 `status` = `"entity-component-delete-requested-readback-pending"`（`EntityComponentDelete.cs:235`）；
  2. `probeId` == 本 run 探针 id；`entityId`/`componentId` 与请求一致；
  3. `beforeComponentCount ≥ 1` 且 `componentId` 在 `beforeComponentIds` 里**恰好出现一次**（`:210-211` 要求 `Count(...)==1`）；
  4. `nativeMutationInvoked:true`（`:241`）；
  5. **同一 turn 的 `afterComponentIdsSameTurn` 是"非权威"**（原生删是异步；`:239` 明写）——**不许拿它当成功**；
  6. **真正的判据**：**另发一次** `inspect-entity-components`（新调用）显示该 `componentId` **消失**，
     且**原生 `save` 后 `.gil` 字节/载荷差分**里该实体组件项的变化可复核。**这两样缺一不算。**

---

## 3. 删是写：review / baseline 要求（逐条对上 §三/§四）

**关键澄清**：**桥的 op 本身没有 `--review` 参数**（`call-bridge.ps1` 全文无 review；桥永远 `persistentSaveVerified:false`，`CLAUDE.md` §二）。
review/baseline 纪律**在把这次删除"落盘"的那一步**（原生 `save`）上生效——但**桥删完若不 save，改动只活在编辑器内存里**，
而**内存里的删除等关卡重载会被悄悄还原**（记忆 `bridge-edits-die-on-context-reset`）。所以"删组件"这条能力要真成立，**必然**要跨过 save 这道门。

**规则原文与出处**：
- `CLAUDE.md` §四（`:55`）：**「一次写入＝一份新鲜基线 + 一份新复核（复用复核报 `actionStatus 6`）」**。
- `docs/gameplan/REAL-MACHINE-RUNBOOK.md:144-145`：场景写**必须**带**新鲜 review 基线**（`orchestrate_write_review.py` 派生，
  **不是手写 `reviewed:true`**；**复用复核会报 `actionStatus 6`**）。
- 同文 `:186-199`：只有原生 `save` 落盘；`save` 会**把所有未保存的东西一起落盘**，**保存后必须重新核对 `.gil`**。

**唯一的 review 生产者**：`tools/game-executor/orchestrate_write_review.py`
- 文件头（`:1-46`）明写它是**派生**（derive）而非**接受**一个 review；**没有** `--reviewed/--state/--approve` 旗标；
  只**发布**给生产校验器 `native_write_review.validate_review` 通过后的记录（`:332-345`）。
- 有效期 ≤ 3600s，默认 900s（`:58-61`）。
- 恢复副本规则（`:231-254`）：若恢复目录里**已有**一份与正式存档**不一致**的副本 → 抛 `EXISTING_RECOVERY_COPY_DIFFERS_FROM_FORMAL_GIL`；
  **残留的 `.partial`** → 抛 `STALE_PARTIAL_RECOVERY_COPY`。⇒ **写前要挪开过期的恢复副本**（记忆 `one-write-per-baseline-and-review`）。

**对本次"删组件"的具体落地**（顺序不可省）：
1. **先跑一次已执行的完整 runtime baseline**（`--baseline-kind readonly`，`orchestrate_write_review.py:257-270` 会 re-load 并校验它）——
   **不能复用建图/建实体那一轮的基线**；
2. 用该基线**派生一份新的 save review**（`--action save`），**不得**手写、**不得**复用（复用 → `actionStatus 6`）；
3. 走 `author.py`/`scene_cli.py` 的原生 `save`（`runbook:186-189`；`--request-id --level-id <当次关卡id> --review <save-review.json>`）；
4. **保存后独立读回 `.gil` 字节**（只读 `tools/beyond-save/gil_container.py` 的 `read_level`），核对组件项差分；
5. `.gil` 差分 + 一次独立 `inspect-entity-components` 都通过，**才**能写"删组件已在真机走通"。

> **不要把桥删本身当成"一次写"来算——** 桥删是**内存写**，真正的"一次写"是随后的 `save`。
> **一份新鲜基线 + 一份新复核**对应的是**那一次 save**；**桥删后改了编辑器模型，先前任何 review 基线即已过期**。

---

## 4. 风险：删到我们没写过的实体 / 组件

**风险陈述**（`EntityComponentDelete.cs:30-33` 文件头原文）：
> *"THIS IS A MUTATION. It must NEVER be pointed at an entity this run did not create or explicitly name."*

底层前端命令 `DeleteComponentForEditObj` 是**通用命令**——对**任意** `EditObj`（任意实体）都可用；
后端 `command_route` id4 只认 `(int32 实体id, int32 组件id)`（`COMPONENT-WRITER-MINE.md:236-238`）。
**给对两个 id，就能删掉用户自己摆的实体上的一个组件**——这会**损坏用户内容**。

**守卫，以及适配器有没有它**：
- **有。** `ComponentOwnedTarget()`（`EntityComponentDelete.cs:147-155`，镜像 `EntityFactionProbe.cs:103-109`）在**派发前**要求：
  `probe.DeleteSpent == false` ∧ `current.Target.Key.Id == entityId` ∧ `EntityType == 1402` ∧ `InstanceKind == 0`
  ∧ `EntityBindings(...).Length == 0`（无图绑定）；再在 `:207-209` 要求 `request.probeId == probe.Id` ∧ `ReferenceEquals(target.Model, model)`；
  在 `:213-217` 要求 `componentId` 在 before-list 里**恰好一次**且该 op 本 run **只允许 16 次**；
  再在 `:221-223` 复用 `ComponentOwnedTarget()` 复检（baseline 纪律）。
  ⇒ **适配器有守卫，而且比裸的 `delete-owned-entity-ids` 强**：后者**没有任何所有权门**，
  `OwnedEntityDelete.cs:8-27` 头注释原文 *"The boundary is the ID LIST and nothing else."*（`ENTITY-DELETE-SCOPE.md:65-80`）。
- **守卫的边界（必须诚实标出）**：
  1. 它**键在内存里的 CRUD 探针**（`probe.Id`），不是**持久化归属记录**——所以它**只强到探针那股 180 秒作用域**
     （`EntityCrudProbe.cs:16,91`）；探针过期即全拒。
  2. 它**不核验这个实体是不是"那个 demo 实体"**，只核验"是不是本期唯一新增的 1402/kind0"；
     且 `EntityCrudProbe.cs:177-182` 是**认领**式（`added.Length==1 && Target==null` 即登记），
     **并发的人工拖入一个物件可能被认领**——这一条由**上层编排**堵（`run_live_crud_acceptance.py:436-437,445`、
     `ENTITY-DELETE-SCOPE.md:151-157` 的 F3），**适配器单独看这层不存在**。
  3. 适配器**没有关卡作用域检查**（id 跨关卡复用，`ENTITY-DELETE-SCOPE.md:147` 的 F2）——
     它删的是**当前载入关卡**里解析到的那一个。
  4. **当前它靠"读半未绑定"额外 fail-closed**（§1.2 gap-4）——一旦按 §5 绑定读半，**这条隐式保险就没了**，
     **必须**保持 `ComponentOwnedTarget` 三道门原样。
  ⇒ **结论**：适配器**有**防"删错实体"的守卫；**没有**防"删错关卡/并发认领"的守卫——后者留在**上层编排**，
  真机执行时必须走 `run_live_crud_acceptance.py` 那条带回执 id 校验的路，**不要**手搓一个 id 直接发。

---

## 5. 人类照做的命令序列（**本文不运行**）

> 每一步都是"当次观测"：**runId 5 分钟过期**（`new-scope.ps1:25`），**同一修订在每个进程只能注入一次**
> （`next-revision.ps1:4-15`），**改了源码/重编译后必须升修订**（`CLAUDE.md` §三）。

### 5.1 读 `EntityComponentProbe`（**已编译**；只需补 `entityId` 的到达路径）

**前置（一次 UAC）**：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**取 runId（载桥）**：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**发 probe**（两条路线，二选一）：

- **路线 A（不改代码，读-only，直接管道）**——`call-bridge.ps1` 已支持 `-EntityId`：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  （这是**读**操作，非写入；但仍是一次 pipe 调用。若沿用"经 helper"的惯例，走路线 B。）

- **路线 B（补 3 处管道，然后经 helper）**：
  1. `tools/editor-bridge/elevated-request.py:513-522` 的 `call` 加 `--entity-id`（type=int）并在 `:585` 处 `request['entityId']=...`；
  2. `tools/editor-bridge/elevated-runner.ps1:227` 的 `$allowedFields` 加 `'entityId'`（**仅**当 `op -ceq 'inspect-entity-components'`），
     并在 `Get-ValidatedCallArguments` 里 `$callArguments['EntityId']=[uint32]...`（`:245` 附近）；
  3. `Get-AllowedOps`（`:123-129`）自动放行（它读 `call-bridge.ps1` 的 `ValidateSet`，该 op 已在）。
  然后：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**判据**：见 §2.1（`status` 逐字、行形状 `{id,enabled,x,y}`、`nativeMutationInvoked:false`、留盘）。**至少一行**才算坐实行形状。

### 5.2 删 `EntityComponentDelete`（**先补 4 处代码 + 重编译**）

**先做代码改动**（缺一不可）：
| # | 文件 | 改什么 |
|---|---|---|
| E1 | `ManagedBridge/Miliastra.EditorBridge.csproj` | `<ItemGroup>` 里加 `<Compile Include="../Adapter/EntityComponentDelete.cs" Link="EntityComponentDelete.cs" />`（现共 52 条，缺它） |
| E2 | `ManagedBridge/BridgeServer.cs` | switch 加 `case "delete-entity-component":`，先 `EditorAdapter.ValidateEntityComponentDelete(root)` 再 `_adapter.EntityComponentDelete(root)`（照 `:306-322` 的 probe 模板） |
| E3 | `call-bridge.ps1` | `ValidateSet` 加 `'delete-entity-component'`；加参数 `-ComponentAction/-ComponentProbeId/-ComponentId`，在 `:41` 附近组装 `action/probeId/componentId` |
| E4 | `Adapter/EditorBindingProfile.Generated.cs` | 补两条符号：`JdaiSnpkbfl`（实体组件 `List<组件>`字段）、`b1EiCj8P44N`（组件 id getter）。**或**改 `ComponentIds()` 走 probe 的类型化 71 常量（`ComponentType71="tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq"` + `EntityComponentsField71="EDuXiXtiyvl"` + `ComponentIdField71="OgoXdqFmidJ"`，见 `EntityComponentProbe.cs:27-31`），免动绑定档 |

**然后重编译（升修订）**：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

（`next-revision.ps1:120-135` 会重建两个项目；**改一处硬拷贝要 grep 出全部同份**——`Net8R269` 出现在
`load-bridge.ps1:29,32`、`new-scope.ps1:31,32`、`verify-fixture*.ps1`，`next-revision.ps1` 会一起改。）

**真机序列**（UAC/载桥同 §5.1）：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

> `retryAllowed:false`、`COMPONENT_DELETE_ALREADY_ATTEMPTED`（`:214-215`）、`COMPONENT_LEASE_MUTATION_LIMIT`（16，`:216-217`）
> 意味着：**一次 scope 里删一次就是一次，不能重试**。删错了就整个 scope 作废、升修订重来。

---

## 6. 证据索引 + 更正清单

**证据索引**

| 论断 | 证据（file:line / 路径） |
|---|---|
| probe 派发 case | `ManagedBridge/BridgeServer.cs:306-322` |
| probe 请求/回执形状 | `Adapter/EntityComponentProbe.cs:50-59`（请求）、`:150-173`（回执） |
| probe 类型化 71 契约 | `Adapter/EntityComponentProbe.cs:24-36,64-96` |
| delete 请求形状 | `Adapter/EntityComponentDelete.cs:79-97` |
| delete 派发形状 | `Adapter/EntityComponentDelete.cs:160-174`；同族 `Adapter/EntityFactionProbe.cs:152` |
| delete 所有权门 | `Adapter/EntityComponentDelete.cs:147-155,207-223`；`Adapter/EntityCrudProbe.cs:102-114` |
| delete 读半未绑定 | `Adapter/EntityComponentDelete.cs:102-107,190-215`；`EditorBindingProfile.Generated.cs`（`JdaiSnpkbfl`=0、`b1EiCj8P44N`=0） |
| csproj 编译集（53 条，含 delete） | `ManagedBridge/Miliastra.EditorBridge.csproj`（末尾为 `../Adapter/EntityComponentDelete.cs`） |
| 当前 payload DLL 含/不含（修订名由 csproj `AssemblyName` 解析） | `bin/Release/net8.0-windows/Miliastra.EditorBridge.<rev>.dll`（**probe 与 delete 的 op 字面量均 UTF-16≥1**；接线前那版 delete=0） |
| 白名单/闭集三层门 | `call-bridge.ps1:1,41,49`；`elevated-runner.ps1:123-129,196-224,263-266`；`elevated-request.py:232,244-256` |
| 组件命令"只有删没有加" | `COMPONENT-WRITER-MINE.md:§0,§2.3,§5`（后端 `command_route` id4/id5；前端 44 条操作） |
| 所有权记录 | `tools/game-executor/README.md:14`；`.runtime/game-executor/r168-created-save-verification.json`；`MINED-INTERFACES.md:90`；`run_live_crud_acceptance.py:436-437,445` |
| id 跨关卡复用 / 保护集 | `run_parameter_matrix.py:242-253`；`round_materials.py:90`；`ENTITY-DELETE-SCOPE.md:147` |
| 一次性写 = 新鲜基线 + 新复核 | `CLAUDE.md:55`；`REAL-MACHINE-RUNBOOK.md:144-145,186-199`；`orchestrate_write_review.py:1-46,232-254,305-345` |
| 版本门 / 升修订 | `next-revision.ps1:4-15,120-135`；`load-bridge.ps1:29-32`；`new-scope.ps1:31-32` |

**更正清单（本节发现的既有文档/测试与磁盘现状不符，建议由拥有者改）**
1. `CLAUDE.md` §五（`:77-81`）与 `tools/gameplan/tests/test_doctrine.py::ComponentOpCompileStatus`（旧引 `:153-156`/`:183-188` 已随文件增长失效）**此前**说 `inspect-entity-components` **"候选，未编译未真机"**。
   **"未编译"已过期**：当前 payload DLL（修订名由 csproj `AssemblyName` 解析）已含该 op 的字面量与回执状态串。**"未真机"仍成立**。
   建议把 probe 改成"**已编译、未真机**"，与 delete 分开标——这正是本计划要消灭的差距。**（已于 2026-10-10 落实：`CLAUDE.md:77-81` 与 `test_doctrine.py::ComponentOpCompileStatus` 现即该分标。注：2026-10-10 晚间 delete 亦接线（R271），故读＝已编译、接线、未真机；**删＝已编译、接线、但读半 `ComponentIds` 未绑定 ⇒ fail-closed（`COMPONENT_MODEL_READER_UNBOUND`，`tools/editor-bridge/Adapter/EntityComponentDelete.cs:195`）**——两半**并非**同为「已编译、未真机」。）**
2. `docs/research/reverse-eng-20261010/COMPONENT-WRITER-MINE.md:400-404` 预测的探针回执行是 `{componentId, enabled}`；
   **适配器实际是 `{id, enabled, x, y}`**（`EntityComponentProbe.cs:150-156`）。以适配器为准。
3. ~~`EntityComponentDelete.cs` 的 op 在三个门里都不存在~~ **（已于 2026-10-10 晚间接线）**：op `delete-entity-component`
   现已在三个门里都存在（csproj `<Compile>` / `BridgeServer.cs:324` switch / `call-bridge.ps1:1` ValidateSet），
   当前 payload DLL 亦含该字面量。**但读半仍卡 2 个未绑定符号**（`ComponentIds()` 抛 `COMPONENT_MODEL_READER_UNBOUND`）⇒ 派发前 fail-closed。
   ⇒ 正确表述是"**已编译、已接线，但读半 `ComponentIds` 未绑定 ⇒ 派发前 fail-closed（`COMPONENT_MODEL_READER_UNBOUND`），一次原生请求都发不出；补上绑定后才只差一次真机运行**"，**不是**"未编译、未接线"，也不是笼统的"只差真机"。

---

*本文件由 2026-10-10 会话从仓内源码、仓内研究文档与构建产物（Python 读字符串堆，非运行；本文写作时为 `Net8R269`，现请以 csproj `AssemblyName` 解析当前修订）只读整理；
**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档**。所有引用行号为本次 checkout 实测。
凡"有实现没跑过"的条目已标 `未验证`；凡"N 命中 0"的均写明检索范围。
**2026-10-10 晚间修订**：§0 / §1.2 / §1.3 / §2.2 与本节更正清单第 1、3 条已按「`delete-entity-component` 接线」更新。*
