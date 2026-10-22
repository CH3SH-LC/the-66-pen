> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #10 挖 — reopen verification：存档之后「重开」到底能证明什么（离线复核）

**产出日期**：2026-10-10
**类型**：离线代码复核 + 只读磁盘读取。**本轮没有起 bridge、没有发任何原生/图请求、没有接触游戏或编辑器、
没有写任何 `LocalLow` 存档。** 唯一跑过的可执行体是 `tools/game-executor/current-save.py`（其自身 docstring
声明「Nothing but files, and only for reading. No game contact, no helper, no UAC, no writes anywhere.」）。
**结论性质**：判定**当前 checkout 里这条链的状态**，并区分「机制可不可用」与「现状能不能跑」。**不声称任何能力可用。**

---

## 0. 一句话结论

**reopen 是本仓唯一一条真正把「存档产物」送回游戏自己的关卡加载器去回放的通道，机制价值高；
但这份 checkout 里它被一个常量关卡 id `1073741840` 钉死在约八个闸门上，其中一处还是编译期 `#error`。
「去常量」只改造了派发之后两个模块（`assemble_reopen_inputs.py`、`reopen_preflight_binding.py`），
派发之前的所有把关模块仍用常量，而且这次半截改造已经把自己的消费者测试搞红（12 条 fail/error）。
所以：机制方向是活的（唯一通往运行时验证的路），但现状是一条「发不出去、且门禁已红」的半成品。
在完成去常量之前，不要发射。**

---

## 1. reopen 链的现状，以及常量关卡 id 到底修没修

### 1.1 这条链是什么（谁在链上）

六个原生动作里的 `reopen-current`（`tools/editor-bridge/elevated-request.py:280`，
`NATIVE_ACTIONS = ("inspect","create","save","create-batch","reopen-current","creature-create")`）
在游戏进程里做的，是对**一个固定函数指针**的调用：

- `tools/game-executor/native/reopen_action.cpp:38` — `a.entry=base+0x13564e90ULL;`（模块基址 + 硬编码 RVA）
- `tools/game-executor/native/reopen_call.h:7` — `using ReopenCurrent = void (__cdecl *)(void* levelManager, void* record, void* callback);`
- `tools/game-executor/native/reopen_call.cpp:12` — `__try {fn(levelManager,record,nullptr); ...}`
- 字节级路由校验：`tools/game-executor/native/reopen_route.generated.h:6`（`{0x13564e90,258,{0x41,0x56,...}}`）

调用前的 `Identity()`/`ValidateRoute()`/`CaptureGameReopenGuardBundle()`（`reopen_action.cpp:30-40`）要求：
当前是**编辑态**（`modeId==0xb993`，`native/reopen_action_validation.cpp:66`、`native/game_reopen_guards.cpp:124`）、
无未保存改动（`dirty` 为假）、且当前选中/记录里那一关就是被许可的那一关。

链上模块（自内向外）：

| 层 | 文件 | 职责 |
|---|---|---|
| 只读前置 | `check_reopen_prerequisites.py`（`live`/`poll`/`analyze`） | 只提交一次只读 `inspect`，不重开、不保存 |
| 审核准备 | `prepare_reopen_review.py` | 生成一次性 `review.json`，只备证据不派发 |
| 基线解码 | `native_reopen_baseline.py` | 解码新鲜完整的前置（levelCatalog/lifecycle/scheduler/guards） |
| 原生 profile | `build_reopen_profile.py` + `native/reopen_*.cpp` | 生成并**编译**一次性探针（`allowWrites:True`） |
| 派发 | `reopen_dispatch.py` | 对齐 lease/claim/review 后只发一次 |
| 结果分类 | `native_reopen_result.py` | 只给「派发状态」，永不给业务成功 |
| 派生索引 | `assemble_reopen_inputs.py` | 组装验收索引（**已去常量**） |
| 前置绑定 | `reopen_preflight_binding.py` | 派发前绑定指针/租约/索引（**已去常量**） |
| 业务验收 | `native_reopen_acceptance.py` | 前后证据独立重算 + `reopenRoundtripVerified`（**仍钉常量**） |
| 存储闸门 | `tools/editor-bridge/reopen-lifecycle.ps1` | 离线草拟的 store gate（dot-source 定义函数，不启动任何东西） |

### 1.2 常量关卡 id 的「去常量」是**半截**——派发前全没改

**已改（好的一侧）**：`assemble_reopen_inputs.py` 与 `reopen_preflight_binding.py` 用 `LEVEL_PLACEHOLDER = 0xFFFFFFFF` + 从 lease 取关卡：

- `tools/game-executor/assemble_reopen_inputs.py:42-49` — 注释「NO FIXED LEVEL (2026-10-08) ... The level is now the LEASE's own」；
  `LEVEL_PLACEHOLDER = 0xFFFFFFFF`
- `tools/game-executor/assemble_reopen_inputs.py:52-58` — `formal_relative(level_id)` **派生**正式 GIL 路径，不再用字面量
- `tools/game-executor/assemble_reopen_inputs.py:139` — `require(claim["levelId"] != LEVEL_PLACEHOLDER, ...)`
- `tools/game-executor/assemble_reopen_inputs.py:189` — `require(review.get("levelId") == claim["levelId"], ...)`（两个**文档**互证，而非各自对常量）
- `tools/game-executor/reopen_preflight_binding.py:64-75` — 注释「This replaces the old `FIXED_LEVEL = 1073741840` ... MEASURED 2026-10-08, when the open level was 1073741842 and every reopen entry point refused it」

**仍钉常量（坏的一侧，逐处 file:line）**：

- 基线：`tools/game-executor/native_reopen_baseline.py:12` — `LEVEL = 1073741840`；用于 `:51` `context['levelObservation']['levelId']==LEVEL`
- 验收器：`tools/game-executor/native_reopen_acceptance.py:26` — `LEVEL = 1073741840`；`:27` `FORMAL_RELATIVE = f".../{LEVEL}/{LEVEL}.gil"`
  - `:197` `require(reader.scalar(payload, 1) == LEVEL, "FORMAL_LEVEL")`
  - `:254` `require(FORMAL_RELATIVE.casefold() in result and "beyond_local_save_player.gip" in result, "ACCOUNT_REQUIRED_FILES")`
  - `:271` `require((level, preflight, route_before, route_after) == (LEVEL, 1, 1, 1), "ACTION_PREFLIGHT_ROUTE")`
  - `:444` `... x.get("currentLevelId") == LEVEL and x.get("baselineLevelId") == LEVEL, "INIT_LEVEL"`
  - `:453` 新鲜事件 `fresh[0]["levelId"] == LEVEL`
  - `:546` `... lease.get("levelId") == LEVEL, "LEASE_IDENTITY"`
  - `:558` `... reviewed.get("levelId") == LEVEL, "REVIEW_CONTRACT"`
- 审核准备：`tools/game-executor/prepare_reopen_review.py:179` — `levelId=baseline_api.LEVEL`；`:138` 观察器 `currentLevelId==baseline_api.LEVEL`
- 原生 profile：`tools/game-executor/build_reopen_profile.py:131` — `#define HR_REOPEN_EXPECTED_LEVEL_ID 1073741840`；`:23`、`:43` 也用 `baseline_api.LEVEL`
- **编译期**：`tools/game-executor/native/reopen_action.h:8` —
  `#if HR_REOPEN_EXPECTED_LEVEL_ID != 1073741840 ... #error "Reopen profile must bind one reviewed invocation to the dedicated current level"`
  **⇒ 想为非 1073741840 的关卡编译一个 reopen 探针，源码都不让过。**
- 派发：`tools/game-executor/reopen_dispatch.py:24` — `require(... a['levelId']==1073741840 ...)`；`:62` — `lease.get('levelId')==1073741840`
- 助手/队列侧：`tools/editor-bridge/elevated-request.py:425` — `if canonical['levelId']!=1073741840:raise ValueError('REOPEN_FIXED_LEVEL_REQUIRED')`
- CLI：`tools/game-executor/scene_cli.py:670` — `if resolve_level(args.level_id) != 1073741840 or args.review is None: raise SceneFailure('REOPEN_REVIEW_AND_FIXED_LEVEL_REQUIRED')`
- 客户端预检：`tools/game-executor/native_reopen_result.py:33,35` — `canonical['levelId']==1073741840`、`pending.get('levelId')==1073741840`

**判定**：常量关卡 id 问题 **没有修完**。它是「派发后两个模块已去常量、派发前六个模块（含原生编译期）仍钉常量」的状态。
这与本仓自己的纪律直接冲突：`HANDOFF-20261009.md:82`「绝不复制粘贴上一轮的关卡 id——它是所加载存档的函数」，
以及 `assemble_reopen_inputs.py:42-48` 记录的那次事故（2026-10-08 开着 `1073741842`，每个入口都拒，把一个 2026-09-28 还能用的能力弄没了）。

### 1.3 这份 checkout 的「真值」与常量的差

用只读的 `current-save.py --json`（磁盘真值，2026-10-10T03:37 实测）：

- 最近一次写入的关卡 = **`1073741842`**（`自定义页签_5_存档`，28383 B——正是本轮闭环 save 的产物）。
  次新 `1073741841`(301520 B)、再 `1073741840`(62227 B)、再 `1073741839`(80185 B)。
- `lastNativeObservation = {run:"20261008-212842-fd8bc70039", levelId:1073741842, entities:11, action:"inspect", ageSeconds:≈108507}`（约 30 小时前）。
- 无待决重开：`.runtime/editor-bridge/native-dispatch/native-active.json` **不存在**。
- helper 存活：`helperPid=176324`，`nativeScene.blocked=false`，`actions` 含 `reopen-current`（`.runtime/editor-bridge/current-elevated-session.json`）。

**⇒ 常量 `1073741840` 既不是磁盘上最新写的关卡，也不是最近一次原生观测到的关卡。** 只要用户当前开着的不是
`1073741840`，整条链在 `active-1`（profile 编译）或 `active-2`（guards 的 `modeId/levelId` 校验）就会拒。

### 1.4 测试实测（证明「半截改造把门禁搞红了」）

本轮实跑（`python -m pytest`，离线）：

| 测试文件 | 结果 |
|---|---|
| `tools/game-executor/tests/test_build_reopen_profile.py` | **17 passed** |
| `tools/game-executor/tests/test_check_reopen_prerequisites.py` | **16 passed** |
| `tools/game-executor/tests/test_prepare_reopen_review.py` | **29 passed** |
| `tools/game-executor/test_assemble_reopen_inputs.py` | **1 failed**, 27 passed |
| `tools/game-executor/tests/test_native_reopen_acceptance.py` | **1 failed + 11 errors**, 19 passed |

失败**全部**指向同一个根因——`native_reopen_acceptance.py` 的 `LEVEL=1073741840` 与真实/fixture 关卡不符：

- `test_native_reopen_acceptance.py::AccountTests::test_actual_immutable_backup_is_complete`
  → `native_reopen_acceptance.py:254` `ACCOUNT_REQUIRED_FILES`（fixture 清单里只有 `.../1073741839/1073741839.gil`，
  没有 `.../1073741840/1073741840.gil`；见 `.runtime/verification/interface-experiments-20260927/p02/scheduler-observation/account-baseline-manifest.json`）。
- `ContentTests.setUpClass`（11 个 error）→ `native_reopen_acceptance.py:197` `FORMAL_LEVEL`
  （fixture `FORMAL` = `.../1073741839/1073741839.gil`，`scalar(payload,1)` 是 1839 ≠ 1840）。
- `test_assemble_reopen_inputs.py::ConsumerShapeTests::test_emitted_index_passes_structural_prelude`
  → `native_reopen_acceptance.py:546` `LEASE_IDENTITY`（沙箱 lease 的关卡 ≠ 常量）。

**这正是任务里说的「code pins a constant level id, being fixed」的实测证据**：改到一半，
用真关卡（1839/1842）做 fixture 的测试与钉常量的验收器已经对不上。

---

## 2. reopen 能证明什么，是「save + 读 .gil」证明不了的

先说三层分工（`CLAUDE.md` §一.3 的「文档 / 工具 / 真机」）：

| 动作 | 走的路 | 它能证明的最强命题 |
|---|---|---|
| 桥建图 + 绑定 | `BeyondEditor.exe` 内存 | 编辑器内存里有这张图/绑定 |
| `scene_cli save` | 写**游戏进程**的存档 | 磁盘 `.gil` 字节变了 |
| 读 `.gil`（离线解码） | 静态解析字节 | **文件里**有这些实体/图/绑定记录 |
| **`reopen-current`** | 调游戏自己的加载函数 `base+0x13564e90` | **运行中的游戏进程，能把这些字节重新加载成一个关卡** |

**save + 读 .gil 只能证明「字节里写了什么」。** 它证明不了游戏自己的反序列化器会接受这些字节、
能不能重建关卡模型、实体 id/config 引用在加载后是否还是那些值。reopen 才是把产物送回**生产它的那个加载器**。

reopen 的验收（`native_reopen_acceptance.validate`，`native_reopen_acceptance.py:525-603`）在**同一个进程、一次调用**里同时扣住：

1. **加载确实发生了**：调用后调度器出现一个**全新的、唯一的 target iterator**，
   且 handle/holder/iterator 都**不在**调用前集合里（`load_progress`，`native_reopen_acceptance.py:282-304`；
   硬门 `:553` `ACTION_LOAD_NOT_PROVEN`）。**文件 diff 给不出「新迭代器」这种东西。**
2. **关卡初始化路径确实重跑了**：被动观察器（1022 包）在前后两次快照里，
   `currentPayloadSameReference` 由 **true 变 false**（`observer_evidence`，`:450`），
   且多出**恰好一条**针对该关卡的、`parsed:true` 的新初始化事件（`:452-453`）。
   **即：游戏自己重建并替换了当前关卡载荷。**
3. **加载后的实体/图/绑定 == 磁盘上的那些**：`compare_content`（`:420-434`）把**编辑器前后内容**、
   **原生前后 config 引用**、**磁盘正式 GIL** 三方对齐——`NATIVE_FORMAL_ENTITY_SET`、
   `NATIVE_FORMAL_CONFIGURATION_REFERENCE`、`FORMAL_NODES/EDGES/BINDINGS`。
4. **调用只发生一次、清理干净**：`dispatchExactlyOnce`、`hookCleanupVerified`（`:549,556`）。

**逐字对照**：

> - **save + 读 .gil 证明**：磁盘文件 `28383 B` 里含 `entityId/graphId/templateId`。
> - **reopen 证明**：一个**活着的游戏进程**，以该文件为当前关卡，**重建出一个实体集合、config 引用、
>   节点图结构与绑定都与文件一致的关卡，并且这一关的初始化路径恰好只触发一次、把旧载荷换掉**。
>   这是「它能被游戏加载」——最接近「能玩」的一步。

**它仍然证明不了**（必须说清）：渲染、玩家移动/交互、节点图的**运行语义**（余额+1、购买成功等）、
参数/几何的独立 tag 映射（`:433-434` 明确把 `formalParameterMappingVerified`/`formalGeometryMappingVerified` 置 false）。
所以 reopen 是**「运行时验证」**，不是**「试玩」**（对照 `PLAYTEST-CONTROL-MINE.md`：试玩要离开编辑态、编辑器侧校验上传；
reopen 要求**留在编辑态**，两者方向相反）。

---

## 3. 重开当前关卡的确切命令序列，以及要查哪个回执字段

### 3.1 先做只读前置（不重开、不保存）

按 `tools/game-executor/REOPEN-VERIFICATION.md:9-17`（此处 corrected：把文档里过期的 `1073741839` 换成**当次真值**）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


结果看 `report.json` 的 `status`：`ready` 才继续（`blocked`/`pending`/`unavailable` 的含义见 `REOPEN-VERIFICATION.md:21-26`）。
**注意：`ready` 时 `reopenVerified` 仍为 `false`**（`REOPEN-VERIFICATION.md:34`，`check_reopen_prerequisites.py:100-102`）。

### 3.2 再准备一次性审核


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


成功只需看输出里的 `reviewPath`（`prepare_reopen_review.py:199-203`）。

### 3.3 派发单次重开

文档给的形式（`REOPEN-VERIFICATION.md:53`）是：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**但这份 checkout 里这行会当场被拒**：`scene_cli.py:670` 与 `elevated-request.py:425` 都要求
`--level-id == 1073741840`；`REOPEN-VERIFICATION.md:53` 里写的 `--level-id 1073741839` 是**过期值，会被拒**。
（这与 §1.3 的真值 `1073741842` 也不符。）**这就是「现状发不出去」的直接证据。**

### 3.4 要查的回执字段（分清「派发」与「成功」）

- **派发级（不是成功）**：`reopen_dispatch.run` 返回的 `result`。看
  - `result['nativeCallReturned']`（布尔）与 `result['status']`：
    `dispatch-returned-business-pending`（`native_reopen_result.py:19-27`）。
  - `result['reopenVerified']` 与 `result['persistenceVerified']` **在这层永远是 `false`**
    （`native_reopen_result.py:25`，`reopen_dispatch.py:29` 硬性 `require(...==0)`）——**别把它当成成功**。
  - 原始回执 `run/stdout.jsonl` 的 `reopenActionHex`（104 B，`reopen_dispatch.py:17-25`）：`status` 7=`RETURNED_PENDING`、8=`EXCEPTION_PENDING`
    （`native/reopen_action.h:12`）。**7/8 也只代表「调用返回了」**，不代表加载发生。
- **业务成功级（这才是「重开真的发生了」）**：由**独立**的 `native_reopen_acceptance.py` 重算。
  - 加载发生的字段：`validate(index)['checks']['loadOccurredAfterDispatch']` 与 `loadProgress['loadOccurred']`
    （`native_reopen_acceptance.py:553` 硬门 `ACTION_LOAD_NOT_PROVEN`；`:303` 产出）。
  - 全链验收字段：**`reopenRoundtripVerified`（`native_reopen_acceptance.py:597`）**，以及 `businessVerified`（同处）。
    这正是 §2 那四条（新迭代器 + 观察器 fresh 初始化 + 三方内容一致 + 单次调用）都通过才会置真的字段。

**一句话**：派发后查 `result['reopenVerified']` 会永远看到 `false`；**要查的是验收产物里的 `reopenRoundtripVerified`**。

---

## 4. 这算不算通往运行时验证的一条可行路径？

**机制上是唯一的一条活路；现状上是一条「半成品 + 门禁已红」的死胡同，必须先把去常量做完。**

**为什么机制值得留（可行的一侧）**

- 它是本仓**唯一**把产物交给**游戏自己的加载器**回放的通道（`reopen_action.cpp:38` 调真函数指针），
  证据强度高于 `.gil` 字节差分：能证明「游戏能把这些字节装回成关卡」（§2）。
- 前置是**只读**的，且**失败即拒**（`check_reopen_prerequisites.py`、`native_reopen_baseline.py:35-68` 一长串 `require`）。
- 它**不落盘**成持久改动的前提被写进设计（`allowWrites:True` 是为**该一次性探针**，`build_reopen_profile.py:156`，
  且验收器要求 `beforeAccount.rows == afterAccount.rows`、`protectedFilesAndMetadataUnchanged`，`native_reopen_acceptance.py:577,587`）。
- 有一个**独立**验收器（不与派发器共享代码）交叉核对（`native_reopen_acceptance.py`），符合「自己验自己不算数」。

**为什么现状是死胡同（不可行的一侧）**

1. **常量没去干净**：§1.2 列的派发前六模块（含 `native/reopen_action.h:8` 的编译期 `#error`）仍钉 `1073741840`。
   真值 `1073741842`/`1839` 都过不去；`REOPEN-VERIFICATION.md:53` 的示例命令在 `scene_cli.py:670` 就会被拒。
2. **半截改造已把门禁搞红**：`native_reopen_acceptance.py` 的 12 条测试红的（§1.4），
   说明「用真关卡做 fixture」这条本来该保护 lane 的防线现在是断的。
3. **它触碰游戏进程**且分类为写动作（`allowWrites:True`），并要**恰好**正开着被许可的那一关的编辑态
   （`modeId==0xb993`、`selected==levelId==id`、`dirty==0`）。任何一项不满足就是 `CURRENT_CHANGED/WRONG_IDENTITY`。
4. 成本高：要 live bridge scope + 新注册观察器 + 账号备份 + 编译探针（`prepare_reopen_review.py`、`build_reopen_profile.py:109-123`），
   一次派发 ≈ 一条完整流水线。**它不该被当成日常验收的自动步骤。**

**要让它可行的最小工作（不是本任务范围，仅列出）**

- 把关卡 id 从**当次观测/lease**取，而不是字面量：改 `native_reopen_baseline.py:12`、`native_reopen_acceptance.py:26`、
  `reopen_dispatch.py:24,62`、`prepare_reopen_review.py:179`、`scene_cli.py:670`、`elevated-request.py:425`、`native_reopen_result.py:33`；
- 去掉/参数化 `native/reopen_action.h:8` 的编译期 `#error`，让 profile 携带**观测到的**关卡；
- 把 `native_reopen_acceptance.py` 的 fixture/校验从常量切到「lease 的关卡」（像 `assemble_reopen_inputs.py` 那样），
  并让 §1.4 的 12 条测试转绿；
- 发射前**先跑 `current-save.py` + 当次原生回执**确认「游戏现在开的正是要重开的那一关」。

**结论**：**不要现在发射。** 在完成去常量 + 让验收器与其测试重新一致之前，reopen 是一条**看起来能证明
「加载得回去」、实际却被常量卡死**的路径。把这条链当作**已识别机制 + 待修复状态**，而不是可用能力。

---

## 附：本文件引用的关键 file:line 一览

- 六动作集合：`tools/editor-bridge/elevated-request.py:280`
- 原生入口：`tools/game-executor/native/reopen_action.cpp:38`；`native/reopen_call.h:7`；`native/reopen_call.cpp:12`；`native/reopen_route.generated.h:6`
- 编辑态门：`tools/game-executor/native/reopen_action_validation.cpp:66`；`native/game_reopen_guards.cpp:124`
- 编译期常量：`tools/game-executor/native/reopen_action.h:8`
- 未去常量的闸门：`native_reopen_baseline.py:12`；`native_reopen_acceptance.py:26,27,197,254,271,444,453,546,558`；
  `reopen_dispatch.py:24,62`；`prepare_reopen_review.py:138,179`；`build_reopen_profile.py:23,43,131`；
  `scene_cli.py:670`；`elevated-request.py:425`；`native_reopen_result.py:33,35`
- 已去常量：`assemble_reopen_inputs.py:42-58,139,189,277`；`reopen_preflight_binding.py:64-75`
- 验收硬门与成功字段：`native_reopen_acceptance.py:303,553,597`；观察器：`:444,450-453`
- 派发级边界：`native_reopen_result.py:19-27`；`reopen_dispatch.py:29`
- 文档：`tools/game-executor/REOPEN-VERIFICATION.md:9-17,21-26,34,53`
- 纪律：`HANDOFF-20261009.md:82`；`CLAUDE.md` §一.3、§六
