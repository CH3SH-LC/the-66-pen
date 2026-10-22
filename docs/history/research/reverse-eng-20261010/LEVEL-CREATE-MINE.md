> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# M6a 第一坎 — 「建关卡到底有没有一条路」挖矿报告（LEVEL-CREATE-MINE）

> 产出日期：2026-10-10。位置：`docs/research/reverse-eng-20261010/LEVEL-CREATE-MINE.md`。任务 `#3`。
> **做法：只读、离线**——未起/停/连 helper，未发任何 bridge/native 请求，未触碰游戏或编辑器，
> 未编译/注入，未读 LocalLow 下任何文件的内容以外的东西（本报告里对活存档只做了**目录列举**与**只读解析**），
> 未写任何存档。本文件是唯一产出；未改 `version_guard.py`、未改任何 pin、未改任何测试、未改任何源码。
>
> **一句话结论：**「建关卡」在**命令/桥这一面根本不存在**（38 条路由、44 条前端操作、2830 字符串全零命中，
> 这是**引擎接口面**的事实）；在**文件这一面存在且字节已被读懂**（`register_level.py` + `gil_container.py`），
> 但今天被一道**项目策略门**（legacy `game` pin）挡住，并且这道门**守的是一处真实存在的格式漂移**
> ——只是漂移的正好是**关卡目录布局**（2026-09-23 起 `Lua` 关卡从平铺文件变成目录），
> 而写盘器**还没跟着改**。所以「能不能建关卡」的准确答案是：
> **原理上可达；命令面不可达；今天被策略 + 一处真实未适配挡住；不是引擎限制。**

---

## 0. 先把「三条路」与「三层事实」分开

同一个问题「能不能建关卡」，在三个**互不相同**的面里答案不同，混起来就一定出错：

| 面 | 问题 | 本次结论 | 证据在哪 |
|---|---|---|---|
| **命令/桥面** | 编辑器有没有一条「建关卡」的命令可以派发？ | **没有**（零命中，见 §3） | `backend.db` / `frontend.db` / `string-table.json` |
| **文件面** | 有没有代码能造出游戏认识的那份字节？ | **有**，且字节语义已解 | `register_level.py` / `gil_container.py`（§1） |
| **策略面** | 造出来之后许不许落盘？ | **今天不许**（fail-closed），且**守的是真漂移** | `version_guard.py` / `VERSION-GUARD-DRIFT.md`（§2） |

`文档写了什么` / `工具能做什么` / `真机验证过什么` 三层在 §5 单独列。
本报告行号 = **本次 checkout 实测**。

---

## 1. `register_level.py` 拆成两件事：字节操作 vs 版本拒绝

`tools/beyond-save/register_level.py`（全 325 行）的**头注释自己就写明**它是干什么、不是什么
（`:1-18`）：它**不是**编辑器 API 调用（"the interface survey found no command, channel or bridge operation
that creates a level"），它做的是**造出游戏自己会写的同一份字节**，因为 `gil_container.py` 能逐字节回环。
模块 docstring 明确两条纪律：**没备份不写**（`:12-13`）、**`--plan` 是默认、`--apply` 才写**（`:14`）。

### 1.(a) BYTE 操作 —— 它到底写哪些字段、怎么回环

链条（全部 read-only 解析真实文件 + 内存内重编码）：

| 步骤 | 函数（file:line） | 干了什么 |
|---|---|---|
| 读档案（`.gip`） | `plan_registration :125-126` → `gil_container.decode_container` + `parse_profile` | 解玩家档案 = **项目注册表（关卡清单）** |
| 选模板 | `:137` `template = min(levels, key=…st_size)` | 取目录里**最小的** `.gil` 当模板（占位关卡形状） |
| **造关卡字节** | `build_new_level :90-103` | 见下 |
| 登记进档案（两处） | `add_level_to_profile`（`gil_container.py:494-523`） | 见下 |
| 重编码档案 | `build_profile`（`gil_container.py:449-476`） | 只替换关卡清单 + 页签 + 尾字段，其余逐字节带过 |
| 落盘（写半） | `apply_registration :243-246` | **先写 `<id>.gil`，再写 `.gip`**（顺序有理由：`:235-242`） |
| 读回（复核） | `verify_registration :252-264` | 用**真解析器**重读两个文件，不用刚写的字节 |

**`build_new_level` 精确写什么**（`:90-103`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- **只改 4 个号**（1/2/39/40），模板里其余字段**原样保留**（含未知字段）——这就是「改一个字段、
  不动看不懂的部分」。升序理由写在 `:94-96`（游戏自己的写入顺序是 `1,2,34,39,40,41,42`）。
- 模板常量 `TEMPLATE_FIELDS = ((34,1),(41,1),(42,1))`（`:59`）来自「占位关卡自带」——
  **但该注释已被证不准**：`GIL-FIELD-LEDGER.md §6.5` 实测 `34` 只在 4 个占位 id 出现、
  `41` 全 18 id 出现、`42` 在 12 id 出现，原文「34 … in every file」与实测不符。
- **登记是「两处都写」**：`add_level_to_profile` 既追加**平铺列表**（`gil_container.py:508`），
  又挂进**页签**（`:510-523`，页签不存在就新建）。只写平铺列表 = **半个注册**（`:502-507` 注释）。
  页签成员是 `(group, level_id)` 对，`group` 默认 `TAB_GROUP_DEFAULT`（=1600，对应反编译枚举
  `SaveArchive`，见 `DEMO-AND-REGISTRATION.md`）。
- **回环保证**在 `gil_container.py` 头注释 `:12-15`：「`encode_fields` reproduces `parse_fields`'s
  input byte for byte」；容器框架在 `:20-31`（`u32be total_len==20+inner`、`version==1`、`magic==0x326`、
  `subtype` 1=档案/2=关卡、`trailer==0x679`）。唯一写盘原语是 `write_bytes :553-555`（注释要求调用者已有备份）。

> **结论 1(a)：** `register_level.py` 的字节操作本身是一段**与 PE 镜像毫无关系**的、
> 只吃 `.gil`/`.gip` 容器的 protobuf 重编码器。它**不读任何 RVA、不读任何 PE 锚点**。

### 1.(b) 版本门 —— 它在哪里、怎么拒绝

同一个文件里有 **4 处** `require_compatible`：

| 位置 | 语境 | 说明 |
|---|---|---|
| `register_level.py:31` | `from version_guard import IncompatibleVersion, require_compatible` | 导入 |
| `:243` | `apply_registration` 写**关卡文件前** | 第一道 |
| `:245` | 写 **profile 前**（注释 "Recheck immediately before each formal-file write"） | 第二道 |
| `:284` | `--apply` 的 CLI 入口，**在做暂存/备份/触碰正式档之前** | 第三道 |

`require_compatible("all")`（`version_guard.py:361-374`）→ `check_compatibility("all")`（`:320-358`）
→ `check_game()`（`:195-215`，读 `GAME_IMAGE` 的 PE 身份 + 4 锚点）+ `check_editor()`（`:218-234`，
读 `EDITOR_DLL` 的 sha256）。**任一半不符即 `reasons` 非空 → `:372-373` 抛 `IncompatibleVersion`**。

**关键事实（本次亲自复跑，§5 有数）：**
今天 `editor` 半**相符**（装机 `BeyondEditor.dll` 就是被 pin 的 7.1 sha `565dda11…`），
**只有 legacy `game` 半不符**（pin timestamp `1785321476`=2026-07-29 vs 装机 `1788945104`=2026-09-09）。
所以「`all` 被挡」= **只有 game 半拖着**，与 `M6a-level-terrain.md:62` / `VERSION-GUARD-DRIFT.md §六` 一致。

**默认 `--plan`（暂存）路径不调门**：`_main()` 只在 `args.apply` 时调 `:284`；
`plan_registration` / `stage_registration` 里**没有任何** `require_compatible`。
⇒ **今天跑 `register_level.py`（不带 `--apply`）不会被门拦**；它只把候选字节写进
`.runtime/beyond-save/candidates/…`（`:293-298`）并读回（`stage_registration :187-226`），**不碰活动存档**。

---

## 2. 这道门守的是「真危险」还是「可重基线的策略」？

**两者都成立，而且必须分开说：它是一道「代理式 tripwire」（策略形态），但它代理的那件事今天确实发生了（真危险）。**

### 2.(a) 策略形态：它是一道 fail-closed、无 override、按镜像身份代理的门

- `version_guard.py` 头注释 `:15-16`：**"There is no override or runtime allowlist from audit output."**
- `:37-38`：**"Editing this file is the only way to change what is accepted; nothing reads an allowlist from
  disk at run time."**
- `require_compatible` docstring `:368-369`：**"There is deliberately no environment, CLI or audit-file
  allowlist: the refusal can only be changed by editing the versioned constants in this file."**
- `check_compatibility` 注释 `:325-330`：`'all'` **只由 legacy `game`+`editor` 组成**，
  **绝不含** `native-scene`——「a 7.1 disk match cannot widen the legacy gate」。

⇒ 就机制而言：这是**项目策略**，不是引擎能力。`VERSION-GUARD-DRIFT.md §六` 还实测证明
`BASELINE` 只是一个**进程内可变 dict**（`:195-201`），一次 in-process 替换就能让它「转绿」——
**所以「红」不等于「路断」，「绿」也不等于「安全」**。

### 2.(b) 但它代理的真危险：**格式确实在 7.1 时代变了**

门 pin 的是**游戏 PE 身份**；而这 5 个 legacy 写盘器**根本不读 PE/RVA**——
`VERSION-GUARD-DRIFT.md §五` 末条：对这 5 个文件 grep `anchors?|rva|GAME_IMAGE|native_profiles`
**只有三处 `rva` 子串假命中，无实质引用**。所以「legacy game pin」是一个**代理式 tripwire**：
用镜像身份代理「存档格式可能变了」。而**它代理的那件事，本次独立复核为真**：

| 真漂移 | 证据（file:line / 实测） |
|---|---|
| **关卡目录布局变了**（2026-09-23 起） | `test_register_level.py:66-83` 明文：「The game changed this layout on 2026-09-23 … a level with no external script is still a flat `<id>.gil` file, but a level that carries external Lua is now a directory `<id>/` holding `<id>.gil` (plus `external_lua_file/`)」；`test_gil_container.py:62-66` 同结论 |
| **实测活目录两种形态并存** | 本次只读列举：`1073741825..834` 是**平铺 `.gil`**；`1073741835..842` 是**目录**（各含 `<id>.gil` + `external_lua_file/`，如 `1073741842/1073741842.gil` 28383 B + `external_lua_file/`） |
| **`.gil` 字段按「写入器版本」分代** | `GIL-FIELD-LEDGER.md §6.1`：老关卡（1825/828–834）**不带 field 1**，新关卡（1835–1842）**带 field 1**；原文「field 1 只在小占位关卡」已过时 |
| **`.gil` 里已出现 7.1 版本串** | 同台账 §2.9 / 字段 43：`field 29` 子串 `CNRELWin7.1.0`（1842）/ `CNRELWin7.0.0`（1831）；`field 43` = `7.1.0`（第三方表里没有该号） |
| **门被触发的时间点合理** | 装机 PE 时间戳 `1788945104` = **2026-09-09**；本次审计（`UPDATE-AUDIT-20260924.md:20`）记录 `game_version=7.1.0` |

### 2.(c) 一个必须点名的**具体未适配**（不是抽象担心）

`register_level.py` **还没跟着新布局改**：
- `plan_registration :121` 用 `level_dir.glob("*.gil")` —— **只看见平铺文件**（今天是 10 个），
  **看不见** 1835–1842 那 8 个目录形态的关卡。
- 存在性检查 `:131` `if (level_dir / f"{level_id}.gil").exists()` —— 对**目录形态**的 id **不设防**。
- 后果：它仍会造出一个**平铺 `<id>.gil`**（占位关卡形状），而游戏当前世代的新关卡是**目录**形状。
  **平铺形态对「无外部脚本的关卡」是否仍被游戏接受——无任何证据。**

> **结论 2：** 这道门**不是**「拍脑袋的官僚策略」——它代理的真危险（存档格式漂移）**已被独立复核为真**，
> 漂移点正好是**关卡目录布局**，且**写盘器还没适配）。同时它**确实是**一道**项目策略**（fail-closed、
> 无 override、可被一次 in-process dict 替换「转绿」）。**最优解不是「放宽或移除门」**，
> 而是 `VERSION-GUARD-DRIFT.md §五(c)` 那条：**先真机写盘 + 独立读回证明新构建仍接受**，
> **再**去谈重基线；**单独重基线不可辩护**（`§五(b)`）。

---

## 3. 编辑器前端 38 条路由里有没有「建关卡」命令？—— 本次亲自复跑

**方法**：直接对 `docs/research/beyondeditor-backend/db/backend.db` 跑 SQL（Bash + Python）。


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**对 38 条命令名做语义扫描**（`create|new|open|add|save|level|scene|map|register|archive|存档|关卡`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


三条命中**逐一核对，都不是建关卡**：
- `AddInstructionGraphForEditObj` / `AddInstructionGraphForPrefab` —— 给**实体/Prefab 挂一张节点图**
  （`command_route` id1/id2，分类「节点图类」）。
- `FocusBeyondTileMap` —— **聚焦**某个 tile map（id8，分类「聚焦类」），是视图动作。

**38 条全表分类**（`command_route.classification`）：
`节点图类 ×2、变更应用类 ×1、删除类 ×4、聚焦类 ×9、改名类 ×2、标签类 ×2、阵营类 ×2、
请求类 ×1、调试日志类 ×5、导入导出类 ×2、无游戏侧落点 ×6、面板转发/真实业务 ×2`。
**没有一个「创建/打开/保存关卡」的动词**——与 `08-能力边界与缺口.md:75`「后端 25 条主表里**确实没有
`Create*` 动词**——只有 Add/Apply/Delete/Modify/Focus/Request」完全一致（该文当时统计 25 条主表，
本次全表 38 条含导出/调试/无落点族，结论不变）。

**旁证（同一次扫描，全部零命中）：**
- `docs/research/beyondeditor-frontend/db/frontend.db → operation`（全表 **44** 行）：
  无 `CreateLevel` / `NewLevel` / `OpenLevel`（该表另有 `GetCursorPos` / `SerializeObject` 等非关卡操作）。
- `.runtime/editor-catalog/string-table.json`（**2830** 条还原字符串）：`CreateLevel`/`NewLevel`/`AddLevel`/
  `CreateScene`/`NewScene`/`CreateMap` **各 0 命中**；含「Level」的 17 条全是 `OnLevelInit` / `IdempotencyLevel` /
  `UI_BEYOND_LOG_LEVELBEGIN` 之类，无一为建关卡。
- `.runtime/editor-catalog/resolved/`（**12375** 个反编译 `.cs`，Bash `grep -rIl`）：
  `CreateLevel`/`NewLevel`/`AddLevel`/`CreateNewLevel`/`CreateScene`/`NewScene`/`CreateNewScene`/
  `AddLevelToProfile`/`LevelCreate`/`CreateNewMap`/`CreateMap` **各 0 文件命中**。
- `frontend.db → capability_gap` **#1**：存档注册（文件级）**disproved**——「写入者不重读文件，380 字节的
  写入被 323 字节覆盖。**编辑器侧不存在可编程建档的靶子**」；**#2**：编辑器「新建存档」方法**disproved**——
  「窗口菜单被完整枚举为 6 个面板，打开节点管理器后 266 条界面文字中 **0 条**含『存档/页签』」。

> **结论 3：** 在**命令/桥这一面**，编辑器**没有**「建关卡」命令——38 条路由、44 条前端操作、
> 2830 字符串、12375 反编译类型**四处零命中**。建关卡**不是走命令派发**的，
> 前端侧更早的结论甚至是**「编辑器界面根本没有『新建存档』面板」**（`capability_gap#2`）。
> **⚠️ 口径更正（2026-10-11）**：这四处**不是互相独立的层**——`backend.db` / `frontend.db` / 串表 /
> 反编译 `.cs` **同取一份 legacy build**，是**同一构建的四种抽取视图（重复观测）**；本负面**真正的
> 独立轴只有两代构建（7.0 / 7.1）**（`CLAUDE.md` §五）。原「四处独立零命中」的说法过强，已改。
> **注意口径**：这是「在**这四个检索范围内**没有可派发的建关卡命令」——
> 前端枚举是不可靠的（`07-无落点命令的诚实结论.md §四` 已正面证伪过一次「前端没有」），
> 故**四次同源检索一致为零**只提置信，**不构成四份独立证据**。

---

## 4. 判决：原理上可达吗？最小一步是什么？

### 4.1 判决

| 命题 | 判决 | 依据 |
|---|---|---|
| **命令/桥面能建关卡** | **否**（否定性·较强） | §3 四处零命中 |
| **引擎/程序本身能建关卡** | **是** | ① 游戏自己会写占位关卡（`register_level.py` docstring / `TEMPLATE_FIELDS :59`）；② 活目录里 1835–1842 是**用户/编辑器后来造出来**的新形态关卡；③ `.gil`+`.gip` 是**明文可解、可逐字节回环**的容器（`gil_container.py:12-31`） |
| **文件面可达（字节已懂）** | **是** | §1(a)；历史上有一次**真机落盘 + 磁盘重读复核**（`DEMO-AND-REGISTRATION.md:375-396`，1073741829「MW_Demo_存档」）与一次**用户确认「看到并打开」**（`REALTIME-INJECTION-20260920.md`，1073741832） |
| **今天能不能落地** | **不能**（被策略门 fail-closed） | `register_level.py:243/245/284` → `version_guard.py:372-373`（§1(b)/§2） |
| **是引擎限制吗** | **不是** | `version_guard.py:15-16,37-38,368-369` 明写「改本文件常量是唯一途径 / 无 override」；`VERSION-GUARD-DRIFT.md §六` 实测 `BASELINE` 是可变 dict |

**所以**：「建关卡被列为 blocked」这条，拆开是两句话——
**（i）命令面本来就没有这条命令（引擎接口事实，不是被谁挡住的）；**
**（ii）文件面有路、字节已懂，但今天被一道项目策略门挡住，且这道门守着一处真实的、尚未适配的漂移。**

### 4.2 最小的测试步（按「风险从 0 到必须用户在场」排序）

**步 0 — 零风险、今天就能跑、但只证字节不证接受（不是决定性的）**
跑 `register_level.py`（**默认 `--plan`，不加 `--apply`**）。它**不经门**（§1(b)），
只把候选字节写进 `.runtime/beyond-save/candidates/<stamp>-level-<id>/`（`:293-298`）并**读回校验**
（`stage_registration:206-225`：用 `read_level`/`read_profile` 重读，报 `profileListsLevel`/`filedUnderTabs`）。
**它回答**：整条字节操作在本机活存档上是否跑得通、产出形状对不对。
**它不回答**：游戏接不接受、门能不能过、新布局适不适配。

**步 1 — 零风险、且能直接坐实 §2(c) 那处未适配（本轮最该做的下一步）**
把**步 0 的候选形状**与**当前世代的真关卡形状**对照：候选是**平铺 `<id>.gil`**，
而活目录 1835–1842 是**目录 `<id>/` + `external_lua_file/`**。
**一次 diff 就能证明「写盘器落后一个世代」**——这比任何抽象担心都硬，且**不写任何活动存档**。

**步 2 — 决定性的那一步（必须用户在场 + 允许写存档的会话）**
即 `VERSION-GUARD-DRIFT.md §五(c)`：**一次真机 `register_level.py --apply` + 独立 `.gil`/`.gip` 字节差分读回
+ 用户重开游戏看到并打开新关卡**。这是**唯一**能挣到「新构建仍接受这套写盘」的绿灯的动作；
拿到它**之后**才谈重基线（`§五(b)` 单独重基线不可辩护）。
**前提**：需在允许写活动存档的会话里做；且要处理**游戏进程会按内存重写 profile** 的既有事实
（`register_level.py` 的 `stage_registration` 注释 `:190-196`：a running game rewrites its profile when it
next saves；`M6a-level-terrain.md:63`；`keep_registered.py` 就是为此写的重放器）。

> **最小一步的准确表述**：**先做步 1（0 风险 diff，证明写盘器落后一代），
> 真正的「能不能建」由步 2 的一次写盘 + 独立读回 + 用户重开来裁决。**
> 在步 2 完成前，任何「建关卡通了」都是**未证**。

---

## 5. 三层标注（严格分开，`CLAUDE.md` 铁律）

**文档写了什么（静态语料）**
- 官方**没有**「新建关卡」专章；`mh3pgiraqkiu` 只从**后果**倒着讲（新建关卡后自动生成关卡实体）。
  系统菜单含「保存当前存档、**打开存档界面**、上传关卡…」（`M6a-level-terrain.md §1`）。
- 官方**不给**任何地形/关卡序列化格式。

**工具/源码能做什么（静态 + 本次只读实测）**
- **命令面**：38 条路由 / 44 条操作 / 2830 字符串 / 12375 反编译类型，**均无建关卡命令**（§3，本次亲跑）。
- **文件面**：`register_level.py` + `gil_container.py` 能用**逐字节回环**造出 `<id>.gil` 并双写 `.gip`
  （§1(a)）；今天被 legacy `game` pin 挡住（§1(b)）。
- **漂移**：关卡目录布局 2026-09-23 起「平铺 → 目录（含 Lua）」，活目录两形态并存（§2(b) 实测）。

**真机验证过什么（运行时）**
- **本次为零执行**——本路未启/停/连、未发报文、未写盘。§3 的 DB 查询与 §2 的目录列举均为只读。
- 历史记录（**非本次**，来自仓内文档，可信度以该文档自述为准）：
  `DEMO-AND-REGISTRATION.md:375-396` 记 1073741829 落盘并**从磁盘重读复核**；
  `REALTIME-INJECTION-20260920.md` 记 1073741832 **经用户确认看到并打开**。
  **这两次都发生在 2026-09-23 布局变更之前**，**不能**用来代表当前世代可用。

**本次亲自跑过的测试（命令 + 结果，file:line）**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- **8 条红全部是门 fail-closed**：traceback 一致落在 `version_guard.py:373`，
  由 `register_level.py:243 require_compatible("all")` 触发；`reasons` = 只有 game 半
  （timestamp / imageSize / CONTEXT / LEVEL / PLACE / SAVE 全不符），**editor 半相符**。
  这与 `VERSION-GUARD-DRIFT.md §三`（8 red，`:297 :311 :350 :362 :377 :389 :401 :416`）逐条一致。
- **`test_update_guard.py` 全绿**（8 项）：每个用例 `patch.object(reg/lab/keeper, 'require_compatible', …)`
  验的是**门的行为**（拒绝发生在任何正式写/连接之前），不是门后的真实镜像
  （`test_update_guard.py:27-114`，例：`:33 :44 :65 :73 :86 :101`）。

---

## 6. 与本报告相关的、必须一起读的既有文件（避免重复造轮子）

| 文件 | 与本报告的关系 |
|---|---|
| `docs/gameplan/VERSION-GUARD-DRIFT.md` | §2 的权威来源；§五决策矩阵 (a)–(d)、§六「BASELINE 是可变 dict」 |
| `docs/research/game-b-systems-20261009/M6a-level-terrain.md` | M6a 总览；§3 建关卡三条候选中「直接改 .gil」是唯一找到的一条 |
| `docs/research/reverse-eng-20261010/GIL-FIELD-LEDGER.md` | §6.1/§6.5 字段分代；§1 field 29/43 版本串 |
| `docs/research/beyondeditor-backend/07-无落点命令的诚实结论.md` / `08-能力边界与缺口.md` | §3 的「命令面没有 Create*」；以及「前端枚举不可靠」的纪律 |
| `docs/editor-catalog/DEMO-AND-REGISTRATION.md` | 1073741829 落盘与磁盘重读复核（历史真机证据） |
| `docs/research/beyondeditor-frontend/db/frontend.db`（`capability_gap` #1/#2） | 「编辑器侧不存在可编程建档靶子 / 没有新建存档面板」的旧结论（**与本报告并行存在，口径冲突见 §3 结论框**） |

**本报告未做**：未启动/连接/关闭原神或千星编辑器；未提权；未发任何 bridge/native 报文；
未读写游戏进程内存；未写任何 `LocalLow` 存档（只做了目录列举与只读解析）；未改任何源码/pin/测试。
