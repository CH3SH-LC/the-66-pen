> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #7 挖 — 加第 7 个原生动作要付什么代价，能解锁哪半边

**产出日期**：2026-10-10
**问题（任务 #7）**：原生 helper 恰好暴露 6 个动作。已有人问过它们**怎么被强制**；没人问过**新增一个动作要花什么**。
本文件按四问作答：(1) 一个动作在**哪三层**被声明与校验（enum / wrapper / args builder）；(2) 加第 7 个是**机械的**
（一个 enum + 一个 case + 一个字符串）还是**有硬边界**（固定 ABI 的预编译探针 / 钉死的 profile / 哈希校验）；
(3) demo 里最便宜又有用的第 7 个动作是哪个（候选：transform setter / 加组件 / 实例化预制体 / 区域查询）；
(4) 场景半边到底卡在 **MISSING DISCOVERY** 还是 **HARD BOUNDARY**。

**口径（CLAUDE.md §一.3 三层分开）**：本文**只记「工具能做什么」（离线、源码级）**。凡「真机验证过什么」一律
引用仓内既有回执记录，不另行声称。本文**只读**：未起 helper、未连桥、未发任何报文、未碰游戏/编辑器/存档、未读图片/PDF。

**行号说明（重要，诚实）**：本文写于一次**并发编辑**期间——`tools/editor-bridge/elevated-runner.ps1`
与 `tools/editor-bridge/elevated-request.py` 的 mtime 在本轮读取中从 `04:33:38` 跳到 `04:34:14`（本机时间），
行号会漂移。**凡涉这两个文件，以「符号名 + 该符号当行的原文」为准，行号只作本次 checkout 的读数**；其余文件 mtime 稳定。

**只读证据源**：`tools/game-executor/native/{game_scene_action.h,game_scene_action.cpp,scene_calls.h,scene_calls.cpp,
hook_receipt_probe.cpp,hook_receipt_protocol.h,hook_receipt.cpp,reopen_action.h,reopen_action.cpp,reopen_call.h,
game_context_snapshot.h,game_context_snapshot.cpp}`；`tools/game-executor/{scene_cli.py,build_scene_profile.py,
build_readonly_profile.py,build_reopen_profile.py,native_write_review.py,orchestrate_write_review.py,
profiles/genshin-cn-7.1.0-reviewed-write.json}`；`tools/editor-bridge/{elevated-request.py,elevated-runner.ps1,
sync-elevated-pointer.py}`；`tools/authoring/author.py`；`tools/gameplan/tests/test_doctrine.py`；
`plugins/miliastra/contracts/contract.json`；同目录兄弟文档 `NATIVE-ACTION-SET-MINE.md`、`NATIVE-MEMORY-MAP.md`、
`MINED-INTERFACES.md`、`TRANSFORM-VIA-RECREATE.md`。
检索工具：**Bash `grep -rI`**（非 Grep 工具——它会静默跳过 `.runtime/`，见记忆 `grep-tool-skips-runtime-dir`）。

---

## 0. 一句话结论

1. **动作的「声明」不是一个 C++ enum，是一个构建期宏 `HR_ACTION`**，值域今天用到 `0..4`；
   **`5` 是空的**。原生侧的分派是**编译期 `#if/#elif`**，不是运行期 switch。
2. **加第 7 个：注册面是机械的（约十余处「加一行」），能力面是被发现卡住的。** 所有位于源码里的「门」
   （`1..3` 白名单、`==4` 独占、`#else #error`、write-profile sha 自校验、客户端/服务端集合一致性守卫、
   教条测试 `len==6`）**没有一处是二进制 ABI 封印、签名验证或远程开关**——全部可编辑。
   **但没有第 5 个「已被逆向出的原生入口」，就写不出第 7 个分支能编译通过、能调动的实现。**
3. **最便宜又有用的第 7 个动作 =「纯读动作」（读实体位置 / 读组件列表），而且它不必占用一个新的 `HR_ACTION` 号**——
   走已有的 `HR_READ_*` 宏模式（`hook_receipt_protocol.h:14-41`）即可。它是 transform / 加组件两个写半边的
   **共同前置**（严格档的后置快照需要「改前值」做校验，而位置与组件列表**至今没有被读出**）。
4. **判决：MISSING DISCOVERY，不是 HARD BOUNDARY。** 挡住 6 以外的不是「6」这个数字，是「我们还没逆向出第 5 个
   原生调用 / 位置与组件列表的字段偏移」。

---

## 1. 一个动作在哪三层被声明与校验（enum / wrapper / args builder，逐层 file:line）

### 1.1 第一层 —「enum」：不是 enum，是构建期宏 `HR_ACTION`

仓内**没有** `enum class Action`。动作编号是**每次构建由生成的 `target_config.h` 定义的预处理宏**，
默认值在 `hook_receipt_probe.cpp:28`（`#define HR_ACTION 0`）。

**谁给它赋值**（三个构建器，各自写进本次 run 的 `target_config.h`）：

| 构建器 | file:line | 赋值 |
|---|---|---|
| 写动作 profile（create / creature-create / save / create-batch） | `tools/game-executor/build_scene_profile.py:257` | `HR_ACTION={'inspect':0,'create':1,'creature-create':1,'save':2,'create-batch':3}[action]` |
| 只读 bootstrap | `tools/game-executor/build_readonly_profile.py:58` | `'HR_ACTION':0`（`// Generated readonly bootstrap. HR_ACTION=0; no scene action is linked.` `:62`） |
| 重开 profile | `tools/game-executor/build_reopen_profile.py:129,140` | 把只读基底的 `#define HR_ACTION 0ULL` 改写成 `#define HR_ACTION 4ULL` |

**谁消费它**（编译期分派，不是运行期 switch）：

| 位置 | file:line | 内容 |
|---|---|---|
| 写动作分支 | `tools/game-executor/native/game_scene_action.cpp:184` | `#if HR_ACTION == 1`（create / creature-create，同一分支） |
| | `:214` | `#elif HR_ACTION == 2`（save） |
| | `:241` | `#elif HR_ACTION == 3`（create-batch） |
| | `:305` | `#else` → `#error Unsupported fixed action`（**这就是「下一个 `#elif`」的位置**） |
| reopen 分支 | `tools/game-executor/native/reopen_action.h:5` | `#if HR_ACTION != 4 \|\| GS_BOOTSTRAP_READONLY \|\| !GS_REVIEWED_ACTION_PROFILE \|\| … → #error` |
| reopen 动作号回填 | `tools/game-executor/native/reopen_action.cpp:29` | `a.action=4;`（回执里的 `action` 字段） |
| 编译期写白名单 | `tools/game-executor/native/hook_receipt_probe.cpp:47` | `#if HR_ACTION < 1 \|\| HR_ACTION > 3 → #error "…requires HR_ACTION in 1..3"` |
| 模式互斥 | `hook_receipt_probe.cpp:30-38` | `GS_BOOTSTRAP_READONLY` 与 `GS_REVIEWED_ACTION_PROFILE` 互斥；只读档强制 `HR_ACTION==0` |

**⇒ 计数（本次 checkout 实测）**：被用到的 `HR_ACTION` 值是 **0、1、2、3、4 共 5 个**；
6 个**请求动作**（见 §2.1）= 5 个数值 + 1 个复用（`creature-create` 与 `create` 同值 1）。
**`5` 未被占用——这就是空着的第 7 个编号位。**

### 1.2 第二层 —「wrapper」：回执 DLL + 探针 exe + 生成的 PS 包装器

一个动作的**宿主侧执行**分三段，三者都是**每次派发现编译/现生成**的：

1. **回调 → 动作入口**（DLL，挂在线程消息钩子上）：
   - `tools/game-executor/native/hook_receipt.cpp:40`：`ExecuteGameSceneAction(&receipt->context, &receipt->action);`
   - 重开走另一个 DLL：`tools/game-executor/native/hook_reopen_receipt.cpp:19`：`ExecuteGameReopenAction(&receipt->reopen);`
2. **动作入口本身**（`ExecuteGameSceneAction`，`game_scene_action.cpp:134`）：它负责**全套前置校验**
   （快照完整/栈锚/三个代码锚点/关卡 id/基线身份/hotfix 字节），再进 §1.1 的 `#if` 分支，再做**后置不变量**
   （`CompletePostSnapshot` `:86-94`）。**回执 ABI 由 `GameSceneActionResult` 定死**（`game_scene_action.h:11-26`，
   含 `static_assert` 两条），**并集进 `Receipt`**（`hook_receipt_protocol.h:47-70`）。
3. **探针 exe 的回执打印 + 严格档成功判定**：
   - `hook_receipt_probe.cpp:237-249`：打印 `"action":{...}`（含 `status/levelId/called/entityId/owner/callCode/placedCount/placedIds`）。
   - `hook_receipt_probe.cpp:190-193`：`#if HR_ACTION reportedOk = … && receipt->action.status==0 && …called==1 …`。
   - `hook_receipt_probe.cpp:197-200`：`"scope": HR_ACTION ? "FIXED_SCENE_ACTION" : …`。
4. **生成的 PS 包装器**（提权后跑探针，做哈希/hash 校验）：`build_scene_profile.py:148-192`（`emit_wrapper`）
   → `invoke-fixed-probe.ps1`（校验 wrapper 自身 sha、`BeyondEditor`/游戏镜像 sha、review sha、正式 `.gil` sha、恢复副本 sha）。
5. **Python 侧编排**：`tools/game-executor/scene_cli.py:414`（`execute_profile`）/ `:523`（`run_profile`）。

### 1.3 第三层 —「args builder」：CLI → 规范化 → 宏 / 队列请求

动作的**入参**从命令行到原生宏，走两条路（本地提权 / 队列提权），各自一层 builder：

**（a）CLI 定义**：`tools/game-executor/scene_cli.py:595-634`（`build_parser`）。
子命令集在 `:598`（`for name in ('inspect','create','creature-create','create-batch','save','reopen-current')`）；
逐动作参数在 `:613-626`（`--template-id/--position/--rotation/--scale`；`creature-create` 另加 `--place-builtin`；`create-batch` 收 `--plan`）。

**（b）规范化（agent 侧，先于任何构建/排队）**：
`scene_cli.py:155-167`（`strict_vector3`）、`:170-192`（`normalize_placement`，拒绝布尔/字符串、限 key 集）、
`:195-199`（`normalize_placements`，1..256）；数值侧 `build_scene_profile.py:79-85`（`vector`，float32 + 有限性 + 正缩放）。

**（c）本地提权路**：`scene_cli.py:677-690`（`inputs` dict）→ `build_scene_profile.py:195`（`build_profile`）
→ 生成 `target_config.h` 的宏：`build_scene_profile.py:297-298`（`HR_POSITION/ROTATION/SCALE`）、
`:299-308`（`HR_PLACEMENT_COUNT/TEMPLATE/TRANSFORM`）→ `build.cmd`（`:325-334`，`cl /LD … /Fe:hook_receipt.dll` + `/Fe:hook_receipt_probe.exe`）。

**（d）队列提权路**：`scene_cli.py:240-275`（`queue_request`，拼闭合数据请求）→
`tools/editor-bridge/elevated-request.py`（客户端）：`validate_native_scene_request` 逐动作字段集（`:371-381`）；
`tools/editor-bridge/elevated-runner.ps1`（服务端）：`$actionFields` 闭合字段表（`$actionFields = @{`，
`'inspect'/'create'/…/'creature-create'`）、`-cin` 代码串（注 `-cin @('inspect','create',…)` 那行）、
`Get-NativeSceneArguments`（函数名 ``function Get-NativeSceneArguments``）把请求翻译回 `scene_cli` 参数。
**（这两个文件行号在本次并发编辑中漂移，以符号为准。）**

**⇒ 三层的「加一个动作」改动量**：enum 层 1 处（新宏值或新 TU）+ wrapper 层 1 处（新 `#elif`）+
args builder 层 3..4 处（CLI 子命令 / 规范化分支 / 宏生成 / 队列字段表和参数翻译）。

---

## 2. 集合在哪里被硬拷贝、哪里被强制（这些就是 §3 要读的「门」）

### 2.1 请求动作注册表：「这 6 个名字合法」

**6 个闭集名字的整份硬拷贝，实测出现在 6 个文件、7 个站点**（Bash `grep -rIl "creature-create"`，
排除 `.git/.runtime/vendor/node_modules/__pycache__`；本次 grep 命中全树 **33** 个文件，其中 **13** 个为
代码/测试/数据文件，其余为散文/文档——**散文那部分会随并发新增文档上移**，本文件自身即为一例。
**稳定的部分是那 13 个代码/测试/数据文件**）：

| # | file:line（本次读） | 符号 | 作用 |
|---|---|---|---|
| 1 | `tools/game-executor/scene_cli.py:598` | argparse 子命令循环 | **大小写敏感**，子解析器按精确串匹配 |
| 2 | `tools/editor-bridge/elevated-request.py:339` | `NATIVE_ACTIONS = (…)` | 队列客户端；强制在 `:374`（`action not in NATIVE_ACTIONS`） |
| 3 | `tools/editor-bridge/elevated-runner.ps1`（`-cin @('inspect',…)` 行） | 常驻 runner | 封闭校验 `NATIVE_SCENE_ACTION_INVALID`；字段表 `$actionFields` |
| 4 | `tools/editor-bridge/elevated-runner.ps1`（`actions=@(…)` 行） | `$nativeCapability` | 能力数组（启动时定死，非请求供给） |
| 5 | `tools/editor-bridge/sync-elevated-pointer.py:80` | `NATIVE_ACTIONS = (…)` | 指针同步器；强制在 `:273` |
| 6 | `tools/gameplan/tests/test_doctrine.py:371` | `_EXPECTED = […]` | **教条测试**：断言恰好 6（`:385` `len(actions)==6`）且字段表键一致（`:389-391`） |
| 7 | `tools/editor-bridge/tests/test-sync-elevated-pointer.py:25` | `NATIVE_ACTIONS = […]` | 测试夹具 |

另有一个**契约文件把这 2 条串钉成「必须存在」**：`plugins/miliastra/contracts/contract.json:604,614`
（`"mustContain": ["NATIVE_ACTIONS = (…)", …]` / `["actions=@(…)"]`）。

### 2.2 「可写动作」白名单（更小的 4 元集：`create/create-batch/save/creature-create`）

| file:line | 内容 |
|---|---|
| `tools/game-executor/profiles/genshin-cn-7.1.0-reviewed-write.json:11` | `"allowedActions": ["create","create-batch","save","creature-create"]` |
| `tools/game-executor/native_write_review.py:19` | `WRITE_PROFILE_SHA256='c35acad511c75e6bc61fceab319a463c222ffa79dc4685900843f401e5a04fd4'`（**该 JSON 被 sha 自校验**，`:29`） |
| `tools/game-executor/native_write_review.py:60` | `require(request['action'] in wp['allowedActions'] and …)` |
| `tools/game-executor/orchestrate_write_review.py:125,370` | 复核编排器读同一 `allowedActions`；CLI `choices=('create','create-batch','save','creature-create')` |
| `tools/authoring/author.py:139` | `SCENE_WRITE_ACTIONS = frozenset({'create','save','create-batch','creature-create'})` |
| `tools/game-executor/build_scene_profile.py:201` | `if action not in ('inspect','create','creature-create','create-batch','save')`（**不含 reopen-current**，它走 `build_reopen_profile.py`） |

### 2.3 原生侧的门（编译期 `#if`，不是运行期 switch）

| file:line | 门 |
|---|---|
| `hook_receipt_probe.cpp:47-49` | `#if HR_ACTION < 1 \|\| HR_ACTION > 3 → #error`——**写动作集的硬枚举** |
| `hook_receipt_probe.cpp:30-38` | 只读/写档互斥；只读档强制 `HR_ACTION==0` |
| `reopen_action.h:5` | `#if HR_ACTION != 4 \|\| … → #error`——**4 被 reopen 独占** |
| `reopen_action.h:8` | `#if HR_REOPEN_EXPECTED_LEVEL_ID != 1073741840 \|\| … → #error`——重开钉死在**一个固定关卡** |
| `game_scene_action.cpp:305-306` | `#else #error Unsupported fixed action`——**留好的扩展点** |

---

## 3. 加第 7 个：机械的，还是有硬边界？（读门，逐条判「是/否封锁」）

**结论先给：注册面 = 机械（可编辑的棘轮，非封印）；能力面 = 被「发现」卡住。**

| 候选「硬边界」 | 实测 | 判 |
|---|---|---|
| **固定 ABI 的预编译探针？** | **否。** 探针**每次派发现编译**：`build_scene_profile.py:325-334` 现场生成 `build.cmd` 用 `cl /LD … /Fe:hook_receipt.dll` + `/Fe:hook_receipt_probe.exe`，`HR_ACTION` 由本次 `target_config.h` 定义。重开侧 `build_reopen_profile.py:109-119` 另编一份 `hook_reopen_receipt.dll` + `hook_reopen_probe.exe`。`game_scene_action.cpp` 里的 `#if/#elif` 只在**其中一份**里存在一个分支。**没有随身携带的、ABI 固定的预编译探针。** | **不是边界** |
| **被钉死的 profile（哈希校验）？** | **有一处，但可编辑。** `native_write_review.py:19` 把 write-profile JSON 的 sha 常量写死在源码里，`:29` 自校验；`:60` 又要求请求动作 ∈ `allowedActions`。**加一个写动作 ⇒ 改 `allowedActions`（json:11）并同步那个 sha 常量。** 这是「**仓内文件对仓内常量**」的完整性锁，**不是签名/加密封印**。 | **棘轮，非封印** |
| **客户端/服务端集合一致性守卫？** | **有一道，可编辑。** `elevated-request.py:476` 要求 `set(capability.actions)==set(NATIVE_ACTIONS)`；`sync-elevated-pointer.py:273` 同。防「半升级」（客户端加了、常驻 helper 没加）。**改 3 处即可放宽。** | **一致性守卫，非上限** |
| **教条测试钉死「恰好 6」？** | **是，但这是好事。** `test_doctrine.py:385` `assertEqual(len(actions), 6)`；`contract.json:604,614` 把两条串列为 mustContain。加动作必须**同时**改它们——这是「记得登记」的机制。 | **棘轮，非墙** |
| **ABI 会被第 7 个动作破坏？** | **不会（若复用同一回执结构）。** 新动作复用 `GameSceneActionResult`（`game_scene_action.h:11-23`）与 `Receipt`（`hook_receipt_protocol.h:47-70`），`kReceiptVersion`（`:74`）**不随动作数变**（它只随 `HR_READ_*` 读域变）。**唯一**：单点动作沿用 `entityId`；批动作才用 `placedId[kMaxBatch]`（`game_scene_action.h:21`）。 | **不封锁** |
| **有编译期硬枚举要改？** | **是。** `hook_receipt_probe.cpp:47` 的 `1..3` 只对**写动作**有效；`reopen_action.h:5` 的 `==4` 只对 reopen 有效。**注意：reopen（=4）当年并没有去放宽 `1..3`，而是另开了一个专属 TU。** 这说明「第 7 个」有两条实现路：**(i) 拓宽 `game_scene_action.cpp` 的 `#elif`**（若复用 place/save 入口），或 **(ii) 另起一个专属探针 TU**（若语义独立，如 reopen 那样）。 | **要改，但机械** |

**⇒ 一句话**：把第 7 个动作「登记出来」（enum 号、CLI 子命令、字段表、白名单、宏生成、回执解码）
**约十余处「加一行」**（清单见 §5），**无 ABI 破坏、无二进制封印**。但**登记 ≠ 能实现**：见 §4。

---

## 4. 最便宜又有用的第 7 个动作：候选排序（成本 × 解锁的半边）

**先立两条判据（来自本仓已证事实）**：
- 原生侧今天**只有 4 个被证明可调用的入口**：`place`（`0x106df3c0`）、`save`（`0x11fe2f00`）、
  `level getter`（`0x13568db0`，在动作内部被调用）、`reopen`（`0x13564e90`）（`NATIVE-MEMORY-MAP.md:203-210`）。
- **位置与组件列表至今没有被读出**：`GameEntitySnapshot.position[3]` 恒未填
  （`game_context_snapshot.h:81`；`game_context_snapshot.cpp:234` 原文 "No guessed transform/component offsets;
  position remains explicitly absent."）。**这不是「没做」，是「没挖到偏移」。**

| 候选 | 实现成本（要逆向什么） | 解锁哪半边 | demo 相关度 | 判 |
|---|---|---|---|---|
| **`read-positions` / `read-components`（纯读）** | **最低**。**且不必占新的 `HR_ACTION` 号**——走已有 `HR_READ_*` 宏模式（`hook_receipt_protocol.h:14-41`）+ 在 `Receipt` 加一字段 + `kReceiptVersion` 加 1（`:74`）+ 写一个解码器。**仍需一个字段偏移**（位置偏移或组件列表布局）。 | **它是 transform 与 加组件两个写半边的共同前置**：严格档的后置校验需要「改前值」（今天位置恒空，`game_context_snapshot.h:81`）。同时可在**只读**里证实 `COLLISION-COMPONENT-ID.md:3` 的假设（碰撞组件 id=8）。 | **中**（不解 M1 本身，但让写半边**可校验**） | **最便宜** |
| **`set-transform`（改已有实体位姿/缩放）** | **中高**。要 (i) 找到 transform 字段偏移或 setter 调用，(ii) 先有一个能读「改前位置」的探针做后置校验（**往往还得配上面那个读动作**，`NATIVE-ACTION-SET-MINE.md:253-258`），(iii) 若就地改，还要动严格档的基线身份（`game_scene_action.cpp:109-121`）。 | `entity.transform`。**但 demo 不需要它**：布局是 create 的入参（`scene_cli.py:258-266`；`placement.py:8-16` 明写设计前提），`TRANSFORM-VIA-RECREATE.md:151-167` 已证「第一次按坐标建对」对静态布局充分。 | **低**（demo 已绕开） | 贵而**低值** |
| **`add-component`（加组件）** | **最高**。要 (i) 游戏侧**组件列表的字段布局**（`NATIVE-MEMORY-MAP.md:264`），(ii) **一个「加」写入原语**——而「加」在**所有层**都不存在：前端命令面只有 2 个组件命令、**都是删**（`DeleteComponentForEditObj`/`DeleteComponentForPrefab`），`AddComponent/CreateComponent/AttachComponent/InsertComponent` 在 12,375 反编译 `.cs` / string-table / 前端 44 操作 / 后端 38 command_route **全 0 命中**（CLAUDE.md §六(a)；`COLLISION-TRIGGER-MINE.md:0-4`）。 | **M1 碰撞触发器**——demo 场景半边**唯一的真 blocker**（节点 `进入碰撞触发器时` 在目录里，但没有组件则事件永不触发，`COLLISION-TRIGGER-MINE.md:0-2`）。 | **高** | **最贵而最高值** |
| **`instantiate-prefab`（实例化预制体）** | **伪需求**。原生 `place_builtin`（`scene_calls.h:15-19`）**本身就是「按 template_id 实例化对象」**，`create` / `create-batch` 已在驱动它（`game_scene_action.cpp:184,241`）。一个「实例化」动作是**已有调用的别名**（A 档，最便宜），**但不解锁任何新半边的能力**。 | 无新增（已在 create 里）。 | 无 | 便宜但**无增益** |
| **`region-query`（区域查询）** | **最高（且无线索）**。原生代码里的 `region` 全是 `VirtualQuery` 的**内存区**（`game_context_snapshot.cpp:139-148`、`game_scene_action.cpp:74-78`），**不是游戏世界区域**；全仓无世界区域查询原语。 | 空间查询（**不对应任何具名 demo blocker**）。 | 低 | 最贵且**无已知锚点** |

**排序（成本低→高）**：纯读(位置/组件) < `set-transform` < 侧路：`instantiate-prefab`（伪）< `region-query` ≈ `add-component`。
**按「解锁的 demo 半边」排序（高→低）**：`add-component`（M1）> 纯读（让写半边可校验）> `set-transform`（demo 已绕开）> `region-query` > 伪需求。

**⇒ 「最便宜又有用」的答案**：**一个纯读动作（读实体位置；能顺带读组件行就更好）**。
理由三条：(1) 它是**唯一不占新 `HR_ACTION` 号**的一档（`HR_READ_*` 模式已在只读档用过 4 次，`hook_receipt_protocol.h:14-41`）；
(2) 它是 `TRANSFORM-VIA-RECREATE.md:188-189` 与 §4 表里所有写动作的**共同前置**（后置校验要「改前值」）；
(3) 它能**在纯只读下**把「组件 id 假设」（`COLLISION-COMPONENT-ID.md:3`：碰撞组件行应读回 `id=8`）从假设变成事实。
**诚实边界**：它**不解锁 M1 本身**——M1 要的是 `add-component`，那是**最贵**的一档。

---

## 5. 真加第 7 个要动哪些文件（清单，供将来核对）

**A 档（复用已有原生入口，约十余处加一行，零 ABI 破坏）**，以「加 `move-batch`，只再调一次 `place_builtin`」为例：

| 层 | file:line（本次读） | 改什么 |
|---|---|---|
| CLI | `scene_cli.py:598` | 子命令元组加一名；`:613-626` 加分支持参数 |
| 队列客户端 | `elevated-request.py:339`（`NATIVE_ACTIONS`）+ `:371-381`（字段集） | 各加一名/一行 |
| 队列服务端 | `elevated-runner.ps1`（`$actionFields`、`-cin` 串、`$nativeCapability.actions`、`Get-NativeSceneArguments`） | 四处各加一名/一支 |
| 同步器 | `sync-elevated-pointer.py:80` | 加一名 |
| 教条/测试 | `test_doctrine.py:371,385`；`tests/test-sync-elevated-pointer.py:25`；`contract.json:604,614` | 同步串；`len==6` → 7 |
| 构建映射 | `build_scene_profile.py:201`（白名单）+ `:257`（`HR_ACTION` 表） | 各加一项 |
| 原生分支 | `game_scene_action.cpp:241` 之后 | 加 `#elif HR_ACTION == 5` |
| 原生门 | `hook_receipt_probe.cpp:47` | 若为写动作：`> 3` → `> 5` |
| 写白名单 | `profiles/genshin-cn-7.1.0-reviewed-write.json:11` + `native_write_review.py:19` | 加一名 + **更新 `WRITE_PROFILE_SHA256`** |
| 复核面 | `orchestrate_write_review.py:125,370`；`author.py:139` | 同步 |

**B 档（要一个新原生能力，被「发现」卡住）**：先逆向出那个原生调用（RVA + 调用约定 + 参数/返回 ABI，
写成 `scene_calls.h:15-24` 那样）+ 取**锚点字节**（`ANCHORS`，`build_scene_profile.py:64`；运行期比对
`game_scene_action.cpp:150-156` 的 `Anchor`）+ 写分支含前置校验（`game_scene_action.cpp:140-168`）与
后置不变量（`CompletePostSnapshot`，`:86-94`）+ 生成新写 profile 条目（新 `allowedActions` + 新 sha）。
**注册面只是把「已经存在」的原生能力接出来；B 档的成本 100% 在发现。**

---

## 6. 诚实回答第 4 问：MISSING DISCOVERY 还是 HARD BOUNDARY？

**答：MISSING DISCOVERY。** 逐条：

**像边界、其实是棘轮（都能改，均已逐行核）**：
- `hook_receipt_probe.cpp:47` 把写动作枚举成 `1..3`——**源码级白名单**；改 `> 3` 即可。**4 已经这么加过**
  （`build_reopen_profile.py:129`）。
- `native_write_review.py:19` 的 write-profile sha——**完整性自校验**，加写动作按流程更新即可（`:29,:60`）。
- `elevated-request.py:476` / `sync-elevated-pointer.py:273` 的集合一致性守卫——**防半升级**，改 3 处放宽。
- `test_doctrine.py:385` / `contract.json:604,614` 的「恰好 6」——**棘轮测试**，加动作必须同时改。
- 探针**每次重编**（`build_scene_profile.py:325-334`），**没有 ABI 固定的预编译件**可被「封印」。

**真正决定能力的是发现**：
- **只有 4 个已被证明可调用的原生入口**（`NATIVE-MEMORY-MAP.md:203-210`）。
- 6 个请求动作 = 5 个 `HR_ACTION` 数值（0..4）= 4 个原生入口 + 1 个零调用只读。
- 每一格「被挡的能力」（§4）都对应一个「**还须读**的原生状态」（`NATIVE-MEMORY-MAP.md:259-270`）：
  位置偏移、组件列表布局、建模板调用/字段号、地形 field-7 编解码、起停试玩调用——**没有一格是「再加一个动作号」**。

**最后一条边界诚实（近乎硬、但不是「动作数」的边界）**：整条动作路径**拒绝在不匹配的构建上运行**——
锚点字节（`game_scene_action.cpp:154-156`）、hotfix 字节默认（`:124-130,165-168`）、基线身份（`:109-121`）
任一不符即在**任何游戏调用之前**退回。这约束的是「**只能在 exact pinned 构建上动作**」，
**不是「不能加第 7 个动作」**。（今日 `version_guard` 的 `game` 组件红，是这条 pin 漂了；见 `NATIVE-HALF-CAPABILITIES.md` §1.1。）

**一句话**：**第 7 个动作的位置（`HR_ACTION == 5`）一直空着；空着的是它背后要调的那个还没被逆向出来的原生函数**
（或那个还没被挖出的字段偏移）。把这套注册面全改完，只要那个原生调用/偏移不存在，探针仍然编译不过
（`#else #error`，`game_scene_action.cpp:305`）或调不动。**要推进场景半边，唯一的路是继续逆向
（新原生调用 / 新字段偏移 / 新 RVA），不是去改动作注册表，更不是去找「官方接口」（CLAUDE.md §一：它不存在）。**

---

## 7. 附：本次核对锚点清单（可逐行复查）

- **enum/宏**：`build_scene_profile.py:257`、`build_readonly_profile.py:58,62`、`build_reopen_profile.py:129,140`、
  `hook_receipt_probe.cpp:28,47,30-38`、`game_scene_action.cpp:184,214,241,305`、`reopen_action.h:5,8`、`reopen_action.cpp:29`。
- **wrapper**：`hook_receipt.cpp:40`、`hook_reopen_receipt.cpp:19`、`game_scene_action.cpp:134,86-94`、
  `game_scene_action.h:11-26`、`hook_receipt_protocol.h:47-70,74`、`hook_receipt_probe.cpp:190-200,237-249`、
  `build_scene_profile.py:148-192`、`scene_cli.py:414,523`。
- **args builder**：`scene_cli.py:595-598,613-626,155-167,170-199,677-690`、`build_scene_profile.py:79-85,195,297-308,325-334`、
  `elevated-request.py:339,371-381`、`elevated-runner.ps1`（`$actionFields`/`-cin`/`$nativeCapability`/`Get-NativeSceneArguments`）。
- **注册面**：`scene_cli.py:598`；`elevated-request.py:339`；`elevated-runner.ps1`（两站点）；`sync-elevated-pointer.py:80`；
  `test_doctrine.py:371,385`；`tests/test-sync-elevated-pointer.py:25`；`contract.json:604,614`。
- **写白名单**：`profiles/genshin-cn-7.1.0-reviewed-write.json:11`；`native_write_review.py:19,29,60`；
  `orchestrate_write_review.py:125,370`；`author.py:139`；`build_scene_profile.py:201`。
- **4 个可调用原生入口**：`NATIVE-MEMORY-MAP.md:203-210`；`scene_calls.h:15-24`。
- **缺口表**：`NATIVE-MEMORY-MAP.md:259-270`、`:298-303`（位置与组件列表是空的）。
- **候选证据**：`game_context_snapshot.h:81`（位置恒空）；`TRANSFORM-VIA-RECREATE.md:151-167,188-189`（demo 不需要 transform）；
  `COLLISION-TRIGGER-MINE.md:0-4`（组件只删不加）；`COLLISION-COMPONENT-ID.md:3`（碰撞 id=8 假设，可只读证伪）。

*本文件由 2026-10-10 会话从仓内源码只读整理；除本文件外未改动任何东西，未起 helper、未连桥、未发报文、
未碰游戏/编辑器/存档、未读图片/PDF。行号为本次 checkout 读数——`elevated-runner.ps1`/`elevated-request.py`
在本轮处于并发编辑中（mtime 漂移），凡涉二者以「符号名 + 原文字串」为准。*
