> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #3 挖 — 版本门绿灯的那一半：原生还能做什么

**产出日期**：2026-10-10。任务 #3。
**前提交给（来自本任务 prompt 的既定事实）**：核验者已测定 `check_compatibility("native-scene")` **今日 OK**，
而 legacy 门 **不 OK**。⇒ **SCENE 半边是活的，legacy 半边才是失败的。** 本文把这句结论**映射成后果**。

**方法（只读、离线）**：
- 读 `tools/compatibility/version_guard.py` 全文 + 其全部**活树**调用者（`grep -rIn "require_compatible("`，
  排除 `.runtime/` 副本，27 处，见 §1.5）。
- 读 `tools/game-executor/native_profiles.py`、`profiles/genshin-cn-7.1.0-readonly.json`。
- **未连桥、未发任何 native/graph 请求、未启动/触碰游戏或编辑器、未写任何存档、未读任何图片/PDF。**
- 只跑离线测试：`pytest tools/compatibility/test_version_guard.py tools/compatibility/test_native_scene_guard.py tools/authoring/test_author.py -q`
  → **45 passed, 20 subtests passed（0.44s）**。其中 `test_author.py:121-128` 正是本文 §3 的门映射断言。
- **「今日状态」的证据来源**（本人未重跑 guard 读装机镜像，以避免触碰安装目录）：
  ① 本任务 prompt 的既定事实；② `docs/gameplan/VERSION-GUARD-DRIFT.md`（2026-10-10 实测，含 `native-scene` 全过
  与 `editor.sha256` 相符）；③ `tools/authoring/author.py:677-682` 的 `liveGate` 自述文本。
  这三处一致，故引用；**任一处单独都不算**（三层口径纪律）。

三层口径（CLAUDE.md §一）：本文 §1/§3 是 **`工具能做什么`（离线，源码级）**；§2/§4 的「今日绿/红」是
**引用来的 `真机/实测`**，已逐条标源。

---

## 0. 一句话结论

**`version_guard.py` 不是一个门，是四个互不相通的门（`game` / `editor` / `all` / `native-scene`），
接在两个不同的后端上。** 今天红的是**最窄的一片**：`game` 组件（PE 身份 + 4 个代码锚点）。
它**连累到**三个东西——`all` 组件、8 条离线测试、5 个 legacy 写盘工具。**其余全部是绿的**：

- **图（graph / 桥）半边**：门是 `editor`（SHA-256），**绿**。
- **场景（scene / 原生）半边**：门是 `native-scene`（只读 profile），**绿**。⇒ **6 个原生动作全部走绿灯路径**（§3）。
- **`game` 组件没有任何独立调用者**——它只作为 `all` 的一半被触及（§1.5）。

⇒ 任务 prompt 那句「legacy 门不行」要**再切一刀**：legacy 三件套里，**`editor` 半是绿的，只有 `game` 半是红的**。
`all` 红 = `game` 红。**这一刀切完，「红」的形状就从「半个工程」缩到「一条 PE 锚点基线 + 依赖它的写盘工具」。**

---

## 1. `version_guard.py` 的组件清单：每个门 gate 什么（file:line 均为本次 checkout 实测）

文件总入口是 `check_compatibility`（`:320`）→ `require_compatible`（`:361`，抛 `IncompatibleVersion` `:72`），
CLI 在 `main`（`:377`）。组件常量：`NATIVE_SCENE = "native-scene"`（`:34`）、
`LEGACY_COMPONENTS = ("game", "editor", "all")`（`:35`）。

### 1.1 组件 `game` — 旧 PE 镜像身份 + 4 个代码锚点（**今日红**）

- 落在 `check_game`（`:195`）→ `inspect_image`（`:116`）。
- **gate 的具体字段**（全部与 `BASELINE["game"]`（`:51-63`）逐字比）：
  | 检查名 | file:line | 期望来源 |
  |---|---|---|
  | `dosSignature` (`MZ`) | `:140` | 常量 |
  | `peSignature` (`PE\0\0`) | `:144` | 常量 |
  | `machine == 0x8664` | `:146` | `BASELINE["game"]["machine"]` `:52` |
  | `timestamp == 1785321476` | `:148` | `:53` |
  | `optionalMagic == 0x20B` | `:157` | 常量 |
  | `imageSize == 439631872` | `:159` | `:54` |
  | `anchors.{CONTEXT,LEVEL,PLACE,SAVE}` 字节 | `:174-187` | `:58-61`（RVA + 期望指令字节，按 PE 节表 `:168` 映射 raw 偏移） |
- 被读的文件：`GAME_IMAGE`（`C:\Games\Genshin Impact Game\YuanShen.exe`，`:39`）、
  `GAME_CONFIG`（`config.ini`，`:41`）。
- `declared_game_version`（`:92`）读 `config.ini` 的 `game_version`，但 `:213` 明写
  **"supplemental config declaration only; not an acceptance condition"** ⇒ 版本串 `7.1.0` **不是**拒绝理由
  （拒绝的是二进制身份/锚点）。**读法：mmap `ACCESS_READ`（`:206`），从不整体载入，`runtimeCompatible:false`（`:201`）。**
- **今日红**：装机 timestamp `1788945104`（2026-09-09）≠ pin `1785321476`（2026-07-29），
  imageSize、4 个锚点全不符（`docs/gameplan/VERSION-GUARD-DRIFT.md:36-48`）。

### 1.2 组件 `editor` — 编辑器程序集 SHA-256（**今日绿**）

- 落在 `check_editor`（`:218`）→ `digest_file`（`:83`，流式 sha256，从不整读）。
- **gate 的具体字段**：`sha256(BeyondEditor.dll) == BASELINE["editor"]["sha256"]`（`:67`，
  `565dda11883f…41a678a`）。文件路径 `EDITOR_DLL`（`:40`）。
- `evidence: "read-only disk bytes; assembly not loaded"`（`:222`）——**只哈希盘上的字节，不加载程序集**。
- **今日绿**：装机 DLL 的 sha 与 pin 相符（`docs/gameplan/VERSION-GUARD-DRIFT.md:43`）。
  同一 SHA 还被**第二道桥自己的门**独立钉着：`tools/editor-bridge/compatibility-guard.ps1:30`
  （`SupportedEditorDllSha256='565DDA11…'`），调用点 `new-scope.ps1:17` / `load-bridge.ps1:7` /
  `call-bridge.ps1:16` / `graph-transport.ps1:43-45`。**两道门同一条 pin，今天同绿。**

### 1.3 组件 `all` — `game` **且** `editor`（**今日红**）

- 落在 `check_compatibility`（`:344-351`）：`if component in ("game","all")` 先跑 `check_game`，
  `if component in ("editor","all")` 再跑 `check_editor`，`reasons` 合并。
- **`:325-327` 明写**：「`'all'` deliberately stays the legacy pair -- it never includes the native-scene profile,
  so a 7.1 disk match cannot widen the legacy gate.」
- **今日红**：`all` 的 `reasons` 里**只有 `game.*` 那几条**（`editor` 今天过），所以 **`all` 红 ⟺ `game` 红**。

### 1.4 组件 `native-scene` — 只读 7.1 profile 的磁盘校验（**今日绿**）

- 落在 `check_native_scene`（`:250`）→ `native_profiles_module`（`:237`，懒加载 `tools/game-executor/native_profiles.py`
  `:46-47`）→ **只调两个函数**：`load_profile()` 与 `verify_disk()`（`:279-281`）。**文档化的「只做这两件」**在 `:10-13`。
- **gate 的具体字段**（`checks` 列表 `:298-313`）：
  | 检查名 | file:line | 期望来源 |
  |---|---|---|
  | `profileSourceHash` | `:299` | `native_profiles.PROFILE_SHA256`（`native_profiles.py:18`）—— **profile 文件自己被钉死** |
  | `imageFileBytes` | `:301` | profile `image.fileBytes` = `445006744` |
  | `imageSha256` | `:303` | profile `image.sha256` = `7f89938da606…ec38e` |
  | `imageTimestamp` | `:305` | profile `image.timestamp` = `1788945104` |
  | `imageSizeOfImage` | `:307` | profile `image.sizeOfImage` = `453693440` |
  | `anchors` | `:309` | `native_profiles.ANCHOR_NAMES`（`:19` = `CONTEXT/LEVEL/PLACE/SAVE`） |
  | `allowWrites is False` | `:311` | readonly profile 必须 `allowWrites:false`（`native_profiles.py:69`） |
- **它不做的事**（`:269-277` 逐条声明，且核验者可见）：`sessionQueried:false`、`processAccess:false`、
  `diskEvidenceOnly:true`、`writePermission:false`、`runtimeCompatible:false`、`runtimeVerified:false`。
  **「磁盘对上」≠「运行时接受」≠「允许写」。**
- `verify_disk` **raise 而非返回 mismatch**（`:289-290` 注释）⇒ 列出的每条 check 都是**真过**才出现。
- 现行 profile：`tools/game-executor/profiles/genshin-cn-7.1.0-readonly.json`
  （4 锚点 RVA `0xec63ab0 / 0x13568db0 / 0x106df3c0 / 0x11fe2f00`）。
- **今日绿**：`docs/gameplan/VERSION-GUARD-DRIFT.md:141-148`（实测逐项相符）。

### 1.5 结构事实（本文最重要的两条）

1. **`game` 组件没有任何独立调用者。** 活树 27 处 `require_compatible(...)` 里，实参只有
   `'native-scene'`、`'editor'`、`'all'`、以及变量 `guard_component(command)`；
   `author.guard_component`（`:153-155`）的返回集合是 `{'native-scene','editor','all'}`——
   **永远不返回 `'game'`**。⇒ `game` 只在 `all` 里被间接触及，**`game` 红必然、且只必然通过 `all` 外溢**。
2. **三层门接两个后端**（`author.py:677-682` 的自述与代码一致）：
   `backend:'scene' → native-scene`、`backend:'graph' → editor`、其余 `→ all`。
   **两个后端各自的门今天都是绿的**（§2）。**红只发生在 `all`。**

---

## 2. 能力 → 门 → 绿/红 → 今日状态

「门」列是**决定性组件**（file:line 见 §1）；「今日」列引 §0 的证据来源。
测试证据：`pytest tools/compatibility/test_version_guard.py tools/compatibility/test_native_scene_guard.py
tools/authoring/test_author.py -q` → **45 passed**。

| # | 能力 | 走的门 | 门今天 | 今日状态 | 决定性调用点 |
|---|---|---|---|---|---|
| 1 | **桥 / 节点图**：create / lookup / add-node / connect / set-value / build-plan / export / catalog | `editor`（SHA-256） | **绿** | **可用** | `author.py:253`（`graph_call`）、`:361`/`:708`（`guard_component`→`editor`） |
| 2 | **桥注入 / scope**：new-scope / load-bridge / call-bridge | `editor`（第二道门，同 pin） | **绿** | **可用** | `compatibility-guard.ps1:30`；`new-scope.ps1:17`、`load-bridge.ps1:7`、`call-bridge.ps1:16` |
| 3 | **原生 inspect**（含 `--reopen-prerequisites` 4 个只读读域） | `native-scene` | **绿** | **可用** | `author.py:155,234`；`scene_cli.py:598,602` |
| 4 | **原生 create**（按坐标造实体） | `native-scene` | **绿** | **可用** | `author.py:234`；`scene_cli.py:258-266` |
| 5 | **原生 creature-create** | `native-scene` | **绿** | **可用** | 同上（`scene_cli.py:618-626`） |
| 6 | **原生 create-batch**（一次回调 N 放置） | `native-scene` | **绿** | **可用** | `scene_cli.py:267-268`；`author.py:155` |
| 7 | **原生 save** | `native-scene` | **绿** | **可用** | `author.py:234`；`scene_cli.py:598`（子命令）；`author.py:139`（`SCENE_WRITE_ACTIONS` 含 `save`） |
| 8 | **原生 reopen-current**（重开关卡） | `native-scene`（经派发层） | **绿** | **可用（经派发层）** | `author.py:155,361`；**注意** `scene_cli.py:667-676` 自身不再校门（见 §3.4） |
| 9 | **写复核编排**（写前基线 + 恢复副本） | `native-scene` | **绿** | **可用** | `orchestrate_write_review.py:282` |
| 10 | **实机 CRUD 验收** | `native-scene` **且** `editor` | **双绿** | **可用** | `run_live_crud_acceptance.py:164-165`（`guard_mutation`） |
| 11 | **本地读**：`author.py capabilities` / `status` | **无门** | — | **总可用**（不碰门） | `test_author.py:154-163`（`gate.assert_not_called()`） |
| 12 | **关卡注册写入**（`register_level.py`） | `all` | **红（`game` 半）** | **被挡** | `register_level.py:243,245,284` |
| 13 | **档案保活**（`keep_registered.py`） | `all` | **红（`game` 半）** | **被挡** | `keep_registered.py:132,138,156` |
| 14 | **实机制实时实验关卡**（`create-realtime-lab.py`） | `all` | **红（`game` 半）** | **被挡** | `create-realtime-lab.py:21,31,44,66` |
| 15 | **静态存档合并**（`apply-newdemo-static-save.py`） | `all` | **红（`game` 半）** | **被挡** | `apply-newdemo-static-save.py:45,58,69,78` |
| 16 | **MVP 坐标修复**（`repair-mvp-position.py`） | `all` | **红（`game` 半）** | **被挡** | `repair-mvp-position.py:230,244,248` |

**读法**：第 1–11 行**全部绿**（= prompt 说的「SCENE 半边是活的」，且**图半边也活**）；
第 12–16 行**红，且红的原因只有一条**——它们走的 `all` 里 `game` 半红。**`all` 的 `editor` 半是绿的，不是它们红的原因。**

---

## 3. 6 个原生动作确认在绿灯路径（`native-scene`）上

### 3.1 6 个动作是哪些、在哪定义

`tools/game-executor/scene_cli.py:598`：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

（`build_readonly_profile.py` / `build_scene_profile.py` 侧的分层见同目录 `NATIVE-ACTION-SET-MINE.md` §1。）

### 3.2 门被挂在哪一层：**不是 `scene_cli` 里，是派发层 + 复核编排层**

- `author.py:153-155`：`guard_component(command)` → `{'scene':'native-scene','graph':'editor'}.get(backend,'all')`。
- `author.py:361`（程序化入口）与 `author.py:708`（CLI 入口）：`require_compatible(guard_component(command))`。
- `author.py:230-234`：`scene_call` 在**派发子进程之前**再校一次 `require_compatible('native-scene')`
  （注释 `:231-233` 明写「Gated by the separate native-scene disk component, not by the legacy fixed-offset baseline」）。
- `orchestrate_write_review.py:282`：写复核**先校盘门**，再读存档/拷副本/写证据
  （注释 `:280-281`「Disk gate first, as author.py does」）。

### 3.3 测试实证（`45 passed` 的一部分）

- `tools/authoring/test_author.py:121-128`（`test_component_selected_per_backend`）：
  先发一条 `backend:'scene'`、再发一条 `backend:'graph'`，断言 `require_compatible` 的实参序列
  **恰为 `['native-scene','editor']`**——**门映射被测试钉住。**
- `test_author.py:130-141`（`test_direct_dispatch_does_not_bypass_the_guard`）：直接调 `scene_call` / `graph_call`
  也**不能绕过**门（`process.assert_not_called()` / `lease.assert_not_called()`）。
- `test_author.py:143-152`：`author.py graph` CLI 在读 lease **之前**就因 `editor` 拒而退出，`lease` 未被触碰。

### 3.4 结论 + 一条必须说的边界

**结论**：6 个动作经 `author.py` 派发时，走的都是 `native-scene` 门；**该门今日绿** ⇒ **6 个动作全在绿灯路径上**，
唯一的额外前置是写动作各自的**运行时复核**（`NATIVE_WRITE_REVIEW_REQUIRED`，`author.py:158-165`；非版本门问题）。

**边界诚实（未见任何文档写过）**：**`scene_cli.py` 本身不 import `version_guard`**
（活树 27 处 `require_compatible` 里没有 `scene_cli.py`；文件内的 `'native-scene'` 是**请求 kind 串**，不是门调用）。
⇒ **磁盘版本门挂在 `author.py` 派发层与复核编排层，不在 `scene_cli` 内**。
直接跑 `scene_cli.py` 不经这两层时**没有这道磁盘门**（它自有另一套证据要求：`--review`/session 文件，
`scene_cli.py:269-273`）。**这是「门在哪一层」的事实，不是漏洞判定**——但要重述成一句纪律：
**要过磁盘版本门，必须经 `author.py` / `orchestrate_write_review.py`，不能只调 `scene_cli`。**

---

## 4. 只有 legacy pin 造成的红 vs 别的原因造成的红（本文的任务核心）

任务 prompt：*「这个区分在工程大多数笔记里都丢了，而它对决定下一步做什么很关键。」* 逐条切：

### 4.1 A 组 — **严格意义上**「只因为 legacy pin 而红」：8 条离线测试（**已证**）

- `tools/beyond-save/test_register_level.py` 的 **8 failed, 19 passed**，8 条 traceback **全部**落在
  `register_level.py:243 require_compatible("all")` → `version_guard.py:373`
  （`docs/gameplan/VERSION-GUARD-DRIFT.md:19,59-79`）。
- **「换掉 pin 就转绿」已实测**：进程内把 `BASELINE['game']` 换成当前镜像身份 + 4 锚点，
  **同一条命令 27 passed**（同文 `:109-112`）。
- ⇒ **这是「只因为 pin」的严格证据**：红的**唯一**成因是那条 `require_compatible("all")`，
  把 pin 对齐即全绿。**但它证的是「测试红 = 门红」，不是「写盘功能在 7.1 上正确」**（见 4.3）。

### 4.2 B 组 — 红的**形状**只因 `game` 半，但「能否工作」**未证**：5 个 legacy 写盘工具

`register_level.py` / `keep_registered.py` / `create-realtime-lab.py` /
`apply-newdemo-static-save.py` / `repair-mvp-position.py`——全部 `require_compatible("all")`（§2 行 12–16）。

**为什么说它们「红只因 `game` 半」**（三条，均可核）：
1. `all` = `game` 且 `editor`（`:344-351`）；`editor` 今天**绿**（§1.2）⇒ **`all` 红 ⟺ `game` 红**。
2. 这 5 个工具是**纯 Python 的 `.gil` / profile 文件编辑器**：`register_level.py` 头注（`:1-21`）明说
   「build the same bytes the game itself writes … only because `gil_container.py` round-trips those bytes exactly」，
   **全程不读 PE、不用定偏移**。而 `game` 门的**自身理由**（`version_guard.py:5-6`）是
   「protecting old **fixed-offset** and file writers」——**「定偏移」这一半不描述它们**。
3. 直接证据：这些工具**没有任何一处**读 `YuanShen.exe`；它们的正确性依赖 `gil_container.py` 的回环。

**但「would otherwise work」**——**未证，且有一个已知的第二阻塞**：
- `docs/gameplan/VERSION-GUARD-DRIFT.md:126-128` 明确警告：把 pin 对齐换来的绿是**「假的安心」**，
  「legacy 的硬编码偏移在新构建上还成立」**一个字都没证**。⇒ **门对齐 ≠ 功能可用。**
- `keep_registered.py:1-22` 自己记录了一个**与门无关**的阻塞：**游戏/编辑器会从内存重写 profile**
  （「at 13:32 … the writer replaced it with its own 323-byte one」）⇒ 即使门绿，单次写入也会被覆盖，
  需要「持续重贴」。**这条第二阻塞不是版本门造成的。**
- `docs/gameplan/TERRAIN-STATUS.md:29` 把「建关卡」判为「今日不能，阻塞点是版本门当前拒绝 7.1，
  不是产品没有这条路」；`M6a-level-terrain.md:3` 记历史上有过一次「用户确认看到并打开」的实机确认——
  **那是旧构建上的**，对当前 7.1 构建不构成证据。

**⇒ B 组的诚实措辞**：它们是**「门红」**（且红的形状**精确地**是 `game` 半），
**不是**「已证能工作只是被门挡」。要把它们判成「只等门绿就能用」，**必须先做一次真机写盘 + 独立读回**
（正是 `VERSION-GUARD-DRIFT.md` §五的选项 (c)）。**别把 A 组那种「换 pin 即绿」的确定性套到 B 组。**

### 4.3 C 组 — 红的原因**不是**版本门，修 pin 也没用（**别混进来**）

以下在工程里也常被写成「做不了」，但**与版本门无关**；把它们和 A/B 组混谈会**误导下一步该做什么**：

| 能力 | 真正的阻塞（file:line / 处） | 与版本门的关系 |
|---|---|---|
| `entity.transform`（改已有实体位置） | 前端无 transform 命令；`Adapter/EntityTransform.cs:144` 抛 `TRANSFORM_NATIVE_SETTER_UNKNOWN` | **无关** |
| 给实体**加组件** | 命令面无 `AddComponent` 家族（CLAUDE.md §六(a)） | **无关** |
| 地形 field-7 **持久化写** | 无写回代码（`terrain.py` 写半不吃路径） | **无关** |
| 后台起停试玩 `playtest.control` | 无接口 | **无关** |
| 写字典常量（类型 27） | 无常量槽 / 无 setter（构造器 `1088/1788` 存在，但引脚是 Generic，物化到 27 未证） | **无关** |
| 桥写 UI / 属性 / 模板 | 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）内 0 命中 | **无关** |

**⇒ 决策含义**：**A 组**是「把 pin 对齐 + 跑一次真机即解」（成本最低，但需用户重开机/一次真机）；
**B 组**是「pin 对齐是**必要不充分**，还要一次真机写盘证明 + 绕开『游戏重写 profile』」；
**C 组**是**继续逆向**（新符号 / 新原生调用 / 新字段），**修 pin 一格都不动**。
把 C 组误当 B 组，会去做「对齐 pin」这种**完全不解决问题**的动作。

### 4.4 一条对称的结构事实

- **图半边与场景半边今天都绿**（§2 行 1–10）。**没有任何读/写能力是因为 `editor` 门红而被挡的**——
  因为 `editor` 门**今天不红**。
- **`game` 组件没有独立调用者**（§1.5）⇒ 「legacy 门红」的**全部可操作内容** = `all` 红 + 上面 12–16 行。
  **不存在第 17 个被 `game` 单独挡住的能力。**

---

## 5. 未做 / 边界诚实

- **未**重跑 `version_guard.py` 读装机镜像（HARD RULE：不触碰游戏/编辑器安装目录）。「今日绿/红」引
  prompt 既定事实 + `VERSION-GUARD-DRIFT.md` 实测 + `author.py:677-682` 自述，三处一致（§0）。
- **未**连桥、**未**发任何 native/graph 请求、**未**启动游戏/编辑器、**未**写存档。
- **未**读任何图片/PDF。
- 「27 处活树调用者」= `grep -rIn "require_compatible(" --include=*.py .`（Git Bash，排除 `.runtime/` 副本，
  排除 `__pycache__`）。**该串是本文对「门有哪些调用者」的检索范围；折叠常量形式的调用不在其内**（本仓未见此类）。
- §4.2 的「5 个工具不读 PE」按各文件头注 + 无 `YuanShen.exe` 引用判定；
  **若将来有人给它们加定偏移路径，此判断即失效。**
- 本文**只读、只写本文件**，未改 `version_guard.py`、未改任何 pin、未改任何测试。
