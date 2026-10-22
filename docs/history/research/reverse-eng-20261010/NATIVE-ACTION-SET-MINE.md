> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #8 挖 — 原生 helper 的 6 个动作：封闭的设计，还是尚未填满的发现

**产出日期**：2026-10-10
**问题**：常驻 helper 暴露的恰好 6 个原生动作（`inspect / create / save / create-batch /
reopen-current / creature-create`）——这个集合是**被设计封死的**，还是**被选择/渐进发现卡住的**？
加第 7 个是机械的（一个 enum + 一个 case + 一个字符串）还是有硬边界（固定 ABI 的预编译探针、钉死的
profile 等）？原生探针是**每个动作各编译一份**，还是**一份二进制里跑 switch**？

**数据来源（全部只读）**：
- `tools/game-executor/scene_cli.py`、`build_scene_profile.py`、`build_readonly_profile.py`、
  `build_reopen_profile.py`、`native_profiles.py`、`native_write_review.py`、`reopen_dispatch.py`
- `tools/editor-bridge/elevated-runner.ps1`、`elevated-request.py`、`sync-elevated-pointer.py`
- `tools/game-executor/native/`（`game_scene_action.{h,cpp}`、`scene_calls.{h,cpp}`、
  `hook_receipt_probe.cpp`、`hook_receipt_protocol.h`、`reopen_action.{h,cpp}`、`reopen_call.h`）
- `tools/gameplan/tests/test_doctrine.py`；`tools/authoring/author.py`；
  `tools/game-executor/orchestrate_write_review.py`、`profiles/genshin-cn-7.1.0-reviewed-write.json`
- 同目录兄弟文档：`MINED-INTERFACES.md`（§2/§10）、`NATIVE-MEMORY-MAP.md`（§2.9）

**本文件只读不写**：除本文件外未修改任何东西；**未起 helper、未连桥、未发任何报文、未碰游戏/编辑器/存档**。
所有行号为本次 checkout 实测。三层口径：本文只记 **`工具能做什么`（离线，源码级）**；
凡涉及"真机验证过"的，一律引用 `MINED-INTERFACES.md` / `NATIVE-MEMORY-MAP.md` 已有的真机证据，不另行声称。

---

## 0. 一句话结论

**这 6 个动作不是「6 个原生动作」，而是「5 个 `HR_ACTION` 数值（0..4）」+ 1 个只读选择器，
落到「4 个已被证明可调用的原生入口」上。** 集合是**被选择/渐进发现卡住的（by choice / discovery），
不是被设计封死的（by design）**：

- **注册**第 7 个动作 → **机械但分散**：不是"一个 enum + 一个 case + 一个字符串"，而是要在
  **6 份请求动作注册表 + 4 份"可写动作"白名单 + 1 份被 sha 钉死的 write-profile + 1 个原生门**里各改一处。
  全部是**加一行**，无 ABI 破坏（新动作复用 `GameSceneActionResult`）。
- **实现**第 7 个动作 → **卡在发现**：每个真正新的动作都需要一个**新逆向出来的原生调用**（签名 + RVA +
  锚点字节）。今天只有 4 个可调用入口存在（`NATIVE-MEMORY-MAP.md:203-210`）。**没有任何动作能在
  "未被逆向出的原生调用"之上被加出来。**

⇒ **场景这一半被挡，根因是 MISSING DISCOVERY，不是 HARD BOUNDARY。** 挡住 6 以外的不是 6 这个数字，
而是"我们还没逆向出第 5 个原生调用"。反过来也对：**即使你有第 5 个原生调用，把它登记成第 7 个动作
的成本，全在 11 处加一行的注册面上（见 §5）。**

---

## 1. 6 个请求动作 ≠ 6 个原生动作：三层映射

### 1.1 请求动作 → 原生编号（`HR_ACTION` 宏）

`HR_ACTION` 是一个**预处理宏**，值在每次构建时由生成的 `target_config.h` 定义。映射表在
`build_scene_profile.py:257`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


| 请求动作 | `HR_ACTION` | 原生分支 / 入口 | 由哪个构建器/探针承载 |
|---|---|---|---|
| `inspect` | **0** | 无原生调用（纯只读快照） | `build_readonly_profile.py:58`（`'HR_ACTION':0`）→ `hook_receipt_probe.exe` |
| `create` | **1** | `place_builtin`（`game_scene_action.cpp:184`） | `build_scene_profile.py` → `hook_receipt_probe.exe` |
| `creature-create` | **1** | **同 `create`，同一分支**；只靠 `HR_PLACE_BUILTIN` 区分 | 同上 |
| `save` | **2** | `save_current`（`game_scene_action.cpp:214`） | 同上 |
| `create-batch` | **3** | `place_builtin` ×N（`game_scene_action.cpp:241`） | 同上 |
| `reopen-current` | **4** | `ExecuteGameReopenAction`（`reopen_action.cpp:27`） | **另一个探针**：`build_reopen_profile.py:129` → `hook_reopen_probe.exe` |

要点（都可逐行核对）：

1. **`inspect` 不是 `HR_ACTION` 的"动作"**，`HR_ACTION=0` 是"无动作"哨兵。它走的是**只读 bootstrap**
   （`build_readonly_profile.py:62` 注释原文：`// Generated readonly bootstrap. HR_ACTION=0; no scene action is linked.`），
   源码里根本没有 `case 0`——`game_scene_action.cpp:184/214/241` 只有 `==1/2/3`，末尾 `#else #error`（`:304-306`）。
2. **`creature-create` 与 `create` 是同一个原生动作**。`build_scene_profile.py:252-256` 明说：native 侧
   **没有 entity-category 参数、没有模板白名单**，二者区别**只**在 `HR_PLACE_BUILTIN`（`scene_calls.cpp:41-45`）。
   所以 6 个请求动作 = **5 个 `HR_ACTION` 数值**。
3. **`reopen-current` 不在 `hook_receipt_probe.exe` 里**，它有自己的探针（`hook_reopen_probe.cpp` /
   `hook_reopen_receipt.dll`，`build_reopen_profile.py:118-119`）和自己的动作号 4。`hook_receipt_probe.cpp:47-49`
   对 `GS_REVIEWED_ACTION_PROFILE` 的门是 `HR_ACTION < 1 || HR_ACTION > 3`，把 4 明确排除在外——
   **4 被 reopen 独占**。

### 1.2 原生动作 → 真正被证明可调用的原生入口

`NATIVE-MEMORY-MAP.md:203-210`（§2.9「唯一被证明可调用的四个」）已给出权威清单，与上面的映射一一对上：

| 原生入口 | 现行 RVA | 谁在用 |
|---|---|---|
| `place`（放置工厂） | `0x106df3c0` | `create` / `creature-create` / `create-batch`（`HR_ACTION` 1、3） |
| `save`（原生保存） | `0x11fe2f00` | `save`（`HR_ACTION` 2） |
| `level getter` | `0x13568db0` | **不是独立动作**，在 `create`/`save` 动作内部被调用（`game_scene_action.cpp:174`） |
| `reopen` | `0x13564e90` | `reopen-current`（`HR_ACTION` 4） |

**⇒ 6 个请求动作 = 4 个原生入口（其中 3 个是写、1 个是重开）+ 1 个零调用的只读 inspect。**
"6 个动作"这个数字里，真正"新增一个原生能力"的位置只有 4 个。

### 1.3 顺带：只读侧其实已经被"多路复用"了

`inspect` 还带 `--reopen-prerequisites`（`scene_cli.py:602`），一个开关同时翻转**4 个只读读域**：
`HR_READ_LEVEL_CATALOG / HR_READ_LIFECYCLE_TYPE / HR_READ_SCHEDULER_COROUTINES / HR_READ_REOPEN_GUARDS`
（`build_readonly_profile.py:80-113` 的 `compile_probe(level_catalog=…, lifecycle_type=…, scheduler_coroutines=…, reopen_guards=…)`）。
`hook_receipt_protocol.h:14-41` 用 `#if HR_READ_*` 把它们堆进同一个 `Receipt`。
**⇒ "6 个动作"这个计数会低估能力**：读侧本来就在**一个动作名下挂 N 个读域**。第 7 个"读动作"在
请求面上根本不必新开一个名字——加一个 `HR_READ_*` 宏即可。

---

## 2. 6 个动作在哪里被声明、在哪里被强制（file:line）

动作集在仓库里**是硬拷贝的**（记忆 `identical-copies-must-be-grepped` 的典型场景）。分两类：

### 2.1 请求动作注册表（"这 6 个名字合法"）

| # | 文件:行 | 内容 | 作用 |
|---|---|---|---|
| 1 | `tools/game-executor/scene_cli.py:598` | `('inspect','create','creature-create','create-batch','save','reopen-current')` | argparse 子命令；**大小写敏感**（子解析器按精确串匹配） |
| 2 | `tools/editor-bridge/elevated-request.py:280` | `NATIVE_ACTIONS = (…)` | 队列客户端；强制在 `:315`；字段表在 `:317-320` |
| 3 | `tools/editor-bridge/elevated-runner.ps1:486` | `-cin @('inspect','create','save','create-batch','reopen-current','creature-create')` | 常驻 runner 的封闭校验；字段表 `:459-466`；能力数组 `:790` |
| 4 | `tools/editor-bridge/sync-elevated-pointer.py:80` | `NATIVE_ACTIONS = (…)` | 指针同步器；强制在 `:273` |
| 5 | `tools/gameplan/tests/test_doctrine.py:371` | `_EXPECTED = [ … ]` | **教条测试**：断言"恰好 6 个"（`:385`）且字段表键与之一致（`:388-392`） |
| — | `tools/editor-bridge/tests/test-native-helper-client.py:24`、`tests/test-sync-elevated-pointer.py:25` | 同串 | 测试夹具 |

### 2.2 "可写动作"白名单（`NATIVE_WRITE_REVIEW_REQUIRED` 家族）

写动作还有一个**更小的集合**（4 个），它决定"哪个动作必须先过复核门"：

| # | 文件:行 | 内容 |
|---|---|---|
| 1 | `tools/game-executor/profiles/genshin-cn-7.1.0-reviewed-write.json:11` | `"allowedActions": ["create","create-batch","save","creature-create"]` |
| 2 | `tools/game-executor/native_write_review.py:19` + `:60` | **该 JSON 被 sha256 钉死**（`WRITE_PROFILE_SHA256=…`），`validate_review` 强制 `request['action'] in wp['allowedActions']` |
| 3 | `tools/game-executor/orchestrate_write_review.py:126` + `:370` | 复核编排器读同一 `allowedActions`；CLI `choices=('create','create-batch','save','creature-create')` |
| 4 | `tools/authoring/author.py:139` | `SCENE_WRITE_ACTIONS = frozenset({'create','save','create-batch','creature-create'})`（`:553` 处映射） |
| 5 | `tools/game-executor/build_scene_profile.py:201` | `if action not in ('inspect','create','creature-create','create-batch','save')`（**注意不含 `reopen-current`**，它走 `build_reopen_profile.py`） |

### 2.3 原生侧的"门"（编译期 `#if`，不是运行期 switch）

| 文件:行 | 门 |
|---|---|
| `hook_receipt_probe.cpp:47-49` | `#if HR_ACTION < 1 \|\| HR_ACTION > 3 → #error "GS_REVIEWED_ACTION_PROFILE requires HR_ACTION in 1..3"` ——**这是写动作集的硬枚举** |
| `hook_receipt_probe.cpp:30-32` | `GS_BOOTSTRAP_READONLY` 与 `GS_REVIEWED_ACTION_PROFILE` 互斥 |
| `hook_receipt_probe.cpp:36-38` | `GS_BOOTSTRAP_READONLY && HR_ACTION != 0 → #error` |
| `reopen_action.h:5` | `#if HR_ACTION != 4 \|\| GS_BOOTSTRAP_READONLY \|\| !GS_REVIEWED_ACTION_PROFILE … → #error` ——**4 被 reopen 独占** |
| `reopen_action.h:8` | `#if HR_REOPEN_EXPECTED_LEVEL_ID != 1073741840 … → #error` ——重开被钉死在**一个固定关卡** |
| `game_scene_action.cpp:304-306` | `#else #error Unsupported fixed action` ——**这就是那个"加 case 的地方"** |

**⇒ 结论**：动作集的"封闭"是**多处、分散、且都写在源码里**的。没有一处是二进制 ABI、签名校验或
加密封印。所有门都是**可编辑的 `#if` / 字符串表 / JSON**。

---

## 3. 原生探针：每动作各编译一份，还是单二进制跑 switch？

**两者都对，但决定性的是"每动作各编译一份"。**

### 3.1 每次派发都从源码**新编译**一个探针（per-run, per-action）

- **写动作**：`build_scene_profile.py:312` 列出源文件（含 `game_scene_action.cpp/h`、`scene_calls.cpp/h`），
  `:325-334` 生成一份 `build.cmd`，用 `cl /LD … /Fe:hook_receipt.dll` + `/Fe:hook_receipt_probe.exe`
  现场编译到**本次 run 的目录**。`HR_ACTION` 是**这次构建**定义的（`:257` 写进 `target_config.h`）。
- **只读**：`build_readonly_profile.py:80-123` 同样现场编译 `hook_receipt.dll` + `hook_receipt_probe.exe`。
- **重开**：`build_reopen_profile.py:118-119` 现场编译 `hook_reopen_receipt.dll` + `hook_reopen_probe.exe`
  （`HR_ACTION` 在 `:129-131` 被改成 4）。

### 3.2 `game_scene_action.cpp` 里的"switch"是**预处理器 switch**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`HR_ACTION` 是 `#define`，所以**每一份编译出来的探针里只有一个分支存在**（`#if`/`#elif` 在**编译期**求值）。
`hook_receipt_probe.cpp:27-29` 给 `HR_ACTION` 的默认值是 0（只读兜底）。

**⇒ 精确表述**：源码是"一个文件里带编译期 switch"，产物是"每个动作一份独立二进制"。
**没有随身携带的、ABI 固定的预编译探针。** 仓库里唯一预编译式的构建是**离线合成测试核**
（`native/build.ps1` → `.runtime/game-executor/build/game_executor.dll` + `native_test_host.exe`，
`native/README.md:20,53`），那是 `GE_*`/ABI-1 的合成宿主，**不是**跑真动作的那条链（`scene_calls`）。

---

## 4. 集合是「设计封闭」还是「选择/发现卡住」？

**证据指向 by choice / incremental discovery：**

1. **编号是序列，不是枚举。** `HR_ACTION` 取 0、1、2、3、4。**4 是后来加的**——`reopen_action.h:5` 明确要求
   "dedicated reopen requires action 4"，`build_reopen_profile.py:129` 把只读基底 `HR_ACTION 0` 改写成 `4`。
   **"加一个新号 + 一个专属 build + 一道专属门"这套模式已经被走过一次。** 没有迹象表明 5 不可加。
2. **扩展点明文写着。** `game_scene_action.cpp:304-306` 的 `#else #error Unsupported fixed action`
   就是留给"下一个 `#elif`"的位置。
3. **读侧已经在多路复用**（§1.3）：`inspect --reopen-prerequisites` 一个动作名挂 4 个读域——
   证明这套架构**拥抱"同名字下挂更多能力"**，不是"动作数封顶"。
4. **没有任何东西是"编译好的、ABI 固定的"**（§3）：探针每次重编，`HR_ACTION` 每次重定。
5. **所谓的"封闭"都是互相约定/棘轮，全部可编辑**：
   - `hook_receipt_probe.cpp:47-49` 的 `1..3` 是**写动作白名单**（源码）。
   - `elevated-request.py:417` 强制 `set(helper.actions) == set(NATIVE_ACTIONS)`——**客户端与服务端
     必须报出同一个集合**。这是防"半升级"的**一致性守卫**，不是原生上限，改 3 行即可放宽。
   - `test_doctrine.py:385` 断言 `len(actions)==6`——**棘轮测试**，改动作必须同时改它（这是好事，是"记得登记"的机制）。
   - write-profile JSON 的 sha 钉死（`native_write_review.py:19`）——**写动作**的完整运行时证据门，
     加写动作要改它并更新那个 sha。

**唯一真正的边界不在这套注册面里，而在下面这层：**

6. **每个新动作背后必须有一个"已被逆向出的原生调用"。** 今天被证明可调用的只有 4 个
   （`NATIVE-MEMORY-MAP.md:203-210`）。`MINED-INTERFACES.md:244-248` 的负结论（`entity.transform` 不存在、
   桥无 UI/组件/属性/模板写原语、无字典构造）说的都是**"发现不足"**，不是"动作数已满"。

---

## 5. 加第 7 个动作，具体要动哪些文件

分两档，成本天差地别。**A 档是"给已有原生调用起个新名字/包一层"；B 档是"要一个新原生能力"。**

### A 档 — 复用已有原生调用（机械、约 11 处加一行）

假设要加一个 `move-batch`，它**只是再一次调用同一个 `place_builtin`**（比如"相对上一次位置的批量摆放"），
那它和一个 `HR_ACTION` 新号的关系，就像 `create-batch` 之于 `create`：

| 类别 | 文件:行 | 改什么 |
|---|---|---|
| 请求注册表 | `scene_cli.py:598` | 元组加一名 |
| | `elevated-request.py:280` + `:317` | `NATIVE_ACTIONS` 加一名；字段表加一行 |
| | `elevated-runner.ps1:459` + `:486` + `:790` | `$actionFields` 加一项；`-cin` 列表加一名；能力数组加一名 |
| | `sync-elevated-pointer.py:80` | `NATIVE_ACTIONS` 加一名 |
| 教条/测试 | `test_doctrine.py:371,385`；`tests/test-native-helper-client.py:24`；`tests/test-sync-elevated-pointer.py:25` | 同步串；`len==6` 改 7 |
| 构建映射 | `build_scene_profile.py:201`（白名单）+ `:257`（`HR_ACTION` 表） | 各加一项 |
| 原生分支 | `game_scene_action.cpp:241` 之后 | 加一个 `#elif HR_ACTION == 5` |
| 原生门 | `hook_receipt_probe.cpp:47-49` | `> 3` 改 `> 5`（若它是写动作） |
| 写动作白名单 | `profiles/genshin-cn-7.1.0-reviewed-write.json:11` + `native_write_review.py:19` | 加一名 + **更新 `WRITE_PROFILE_SHA256`** |
| 复核面 | `orchestrate_write_review.py:126,370`；`author.py:139` | 同步 |

**ABI 影响：零**——新动作复用同一个 `GameSceneActionResult`（`game_scene_action.h:11-23`）和同一个
`Receipt`（`hook_receipt_protocol.h:47-70`），`kReceiptVersion`（`:74`）不变（它只随 `HR_READ_*` 读域变）。
**唯一的"顺手要做的"**：`GameSceneActionResult.placedId[kMaxBatch]`（`game_scene_action.h:21`）容得下批结果；
单点动作沿用 `entityId`。

**若第 7 个是纯读动作**（更便宜）：不必进 `HR_ACTION` 表，只要加一个 `HR_READ_*` 宏
（`hook_receipt_protocol.h:14-41` 的模式）+ 在 `Receipt` 里加一个字段 + **`kReceiptVersion` 加 1**（`:74`）
+ 写一个解码器。

### B 档 — 需要一个新原生能力（被**发现**卡住）

这才是真正的成本。要加"改已有实体位置"（`set-transform`）或"加组件"（`add-component`），
**首先得逆向出那个原生调用**，然后：

1. 找到函数的 **RVA + 调用约定 + 参数/返回 ABI**（像 `scene_calls.h:15-24` 那样写下来）；
2. 取它的**锚点字节**做构建身份校验（`ANCHORS`，`build_scene_profile.py:64`；profile 侧的锚点集合与
   长度校验在 `native_profiles.py:65-79`；运行期比对在 `game_scene_action.cpp:150-156` 的 `Anchor`）；
3. 写一个 `#elif HR_ACTION == 5` 分支，含**前置校验**（身份/关卡/锚点/栈）与**后置不变量**
   （`CompletePostSnapshot`，`game_scene_action.cpp:86-94`）;
4. 生成写 profile 的新条目（新 `allowedActions` + 新 sha）；
5. 在 `NATIVE-MEMORY-MAP.md:263-268` 那张"还须读什么"表里勾掉一格。

**这一步没有任何"注册表"能替代。** 注册面只是把**已经存在**的原生能力接出来；B 档的成本 100% 在发现。

### B 档的一个隐藏先决条件：**位置根本没被读出来**

`GameEntitySnapshot.position[3]` **恒未填**（`game_context_snapshot.h:81`；
`game_context_snapshot.cpp:234` 注释原文"No guessed transform/component offsets; position remains explicitly
absent"）。所以哪怕你把 `set-transform` 的原生调用挖出来，**你还没有一个能读出"改前位置"的探针**去
做后置校验。第 7 个写动作往往还得配一个第 8 个**读动作**（读变换字段 / component 列表）。

---

## 6. 哪个被挡的能力，由哪个假设动作解锁

把 §5-B 的"发现成本"对到 `NATIVE-MEMORY-MAP.md:263-268` 的缺口表：

| 假设的第 7 个动作 | 要新逆向什么 | 解锁哪个今天被挡的能力 | 依据 |
|---|---|---|---|
| `set-transform`（改已有实体位姿/缩放） | 实体/owner 上的**变换字段偏移**，或 component 列表 | `entity.transform`（前端无 transform 命令，全链路负结论） | `NATIVE-MEMORY-MAP.md:263`；`MINED-INTERFACES.md:244` |
| `add-component` / `set-component` | 实体 **component 列表**的**游戏侧**字段布局 + 写原语 | M1 触发器 / F5 反馈那一半（桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 ui/component/property 0 命中） | `NATIVE-MEMORY-MAP.md:264`；`MINED-INTERFACES.md:247` |
| `create-template`（建货币/道具/背包/商店模板） | 建模板的**原生调用**，或存档里模板所在**字段号**（候选 `root field 15`） | 六模块里"模板"那一半 | `TEMPLATE-CREATION-MINE.md:25-35`；`NATIVE-MEMORY-MAP.md:265` |
| `read-entity-positions`（纯读第 7 个） | 位置字段偏移（或直接用已有的 `.gil` 几何解析） | 让"改前位置"可用于校验；把 §5-B 的前置补齐 | `game_context_snapshot.h:81` |
| `write-terrain-field` | `.gil` `field 7` 的**编解码器**（今天全仓 0 读写者） | 地形编辑（M6a） | `MINED-INTERFACES.md:246`；`NATIVE-MEMORY-MAP.md:267` |

**注意最后一列的"依据"全部指向同一句话**：`NATIVE-MEMORY-MAP.md:300-303` 的总览——
「读得最广的是『谁在场景里』，读得最窄的是『东西摆在哪、由什么组成』；
**位置偏移与 component 列表至今是空的，这正是 `entity.transform` 与模板/组件/UI 那一半被挡的共同根因**。」

---

## 7. 战略答案：MISSING DISCOVERY 还是 HARD BOUNDARY

**答：MISSING DISCOVERY。** 逐条给证据：

**像边界、其实只是棘轮（都能改）：**
- `hook_receipt_probe.cpp:47-49` 把写动作枚举成 `1..3`——**源码级白名单**，改 `> 3` 即可；4 已经这么加过。
- `elevated-request.py:417` 要求 `set(helper.actions) == set(NATIVE_ACTIONS)`——防半升级的**一致性守卫**。
- `test_doctrine.py:385` 断言"恰好 6"——**棘轮测试**，加动作必须同时改它（是"记得登记"的机制，不是墙）。
- `native_write_review.py:19` 的 write-profile sha——**证据门的完整性锁**，加写动作要按流程更新。
- 这些没有一处是**二进制 ABI、签名验证、加密封印 or 远程开关**。全部是"本次 checkout 的源码"。

**真正决定能力的是发现：**
- 只有 **4 个已被证明可调用的原生入口**（`NATIVE-MEMORY-MAP.md:203-210`）。
- 6 个请求动作 = 5 个 `HR_ACTION` 数值（0..4）= 4 个原生入口 + 1 个零调用只读。
- 每一格"被挡的能力"（§6）都对应一个"**还须读**的原生状态"，不是"还须加一个动作号"。
- 负结论（`MINED-INTERFACES.md:244-248`）措辞都是"**前端命令面没有**/*全仓 0 读写者*"之类——
  即**发现范围内的不存在**，与"动作集封闭"无关。（同段旧列里"字典不可构造"一说实为**过度概括**：
  构造器 `1088`/`1788`/`948` 与取元素 `1158` 均在 500 条定义里，只是**泛型**引脚；2026-10-12 复核，见 `DICT-WRITE-PROBE.md`。）

**一句话**：**第 7 个动作的位置一直空着；空着的是它背后要调的那个原生函数。**
把这套 11 处注册面全改完，只要那个原生调用还不存在，探针就仍然编译不过（`#else #error`）或调不动。
**要推进场景这一半，唯一的路是继续逆向（新原生调用 / 新字段偏移 / 新 RVA），不是去改动作注册表，
更不是去找"官方接口"（不存在）。**

---

## 8. 附：本次核对的锚点清单（可逐行复查）

- 动作注册表 6 份：`scene_cli.py:598`、`elevated-request.py:280`、`elevated-runner.ps1:486`、
  `sync-elevated-pointer.py:80`、`test_doctrine.py:371`、`tests/test-*.py`（夹具）。
- 写动作白名单 4 份 + 1 份被 sha 钉死的 JSON：`profiles/genshin-cn-7.1.0-reviewed-write.json:11`、
  `native_write_review.py:19,60`、`orchestrate_write_review.py:126,370`、`author.py:139`、`build_scene_profile.py:201`。
- 原生编号与分支：`build_scene_profile.py:257`、`build_readonly_profile.py:58`、`build_reopen_profile.py:129`、
  `game_scene_action.cpp:184/214/241/304`、`hook_receipt_probe.cpp:27-49`、`reopen_action.h:5,8`。
- 每动作各编译一份：`build_scene_profile.py:312,325-334`；`build_readonly_profile.py:80-123`；
  `build_reopen_profile.py:115-119`。
- 无固定 ABI 预编译探针：`native/build.ps1`（→ 合成测试核）、`native/README.md:20,53`。
- 4 个可调用原生入口：`NATIVE-MEMORY-MAP.md:203-210`；`scene_calls.h:15-24`。
- 缺口表：`NATIVE-MEMORY-MAP.md:259-270`、`:300-303`。

*本文件由 2026-10-10 会话从仓内源码只读整理；未改动除本文件外的任何东西，未起 helper、未连桥、
未发报文、未碰游戏/编辑器/存档。所有行号为本次 checkout 实测。*
