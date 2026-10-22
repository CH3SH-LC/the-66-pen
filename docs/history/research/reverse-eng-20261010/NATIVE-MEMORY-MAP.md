> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 原生内存地图 — NATIVE-MEMORY-MAP

建立：2026-10-10。性质：**索引，不是新逆向**。本文把散落在
`tools/game-executor/native/*.h/.cpp`（34 个文件）与 `PROGRESS.md`（1 MB）里的
**原生探针 / 混淆地址 / 结构偏移**集中成一张可检索的地图。

**纪律**：每一条都带 `file:line` 或 `PROGRESS.md:行`；猜测一律加 `[推测]` 标记并注明依据。
本文只说**读到了什么**，不说**能做成了什么**（CLAUDE.md §一.3：文档 / 工具 / 真机三层分开）。

> 口径澄清：本工程的原生通道 = **游戏进程 `YuanShen.exe`**（`game-executor`），
> 与**编辑器进程 `BeyondEditor.exe`**（`editor-bridge`）是两条通道（CLAUDE.md §二）。
> 本文只覆盖前者；少数来自编辑器侧反汇编的地址（如 `0x1182cea0`）单独标注来源。

---

## 0. 读之前：构建身份与两套坐标

原生探针里所有地址都是**某个具体 EXE 构建**的 RVA。仓库里同时存在**两代**坐标，不能混用：

| 代号 | 全局槽 RVA | 锚点（place/save/level/context） | 载体 | 用途 |
|---|---|---|---|---|
| **L-bootstrap（旧）** | `0x555fac8` | `0xb7a1aa0` / `0xddbfe60` / `0xe920a70` | `game_context_snapshot.cpp` 的 legacy 字面量（`game_context_snapshot.cpp:33-80`）、`game_scene_action.cpp:31-48` | 无 profile 时的兜底编译；`PROGRESS.md:4039,6039,5155` 的旧反汇编 |
| **S-7.1.0（现行验证）** | `0x5783de8` | `0x106df3c0` / `0x11fe2f00` / `0x13568db0` / `0xec63ab0` | `profiles/genshin-cn-7.1.0-readonly.json`、`.runtime/**/target_config.h`、`guard_profile.generated.h` | 严格 profile 构建；真机只读回执与动作都跑在这一代 |

**现行构建指纹**（S-7.1.0）：镜像 SHA-256 `7f89938da606c1281659607d464702cddb9a09a7d4320a196630f60a811ec38e`
（`profiles/genshin-cn-7.1.0-readonly.json:6`、`guard_profile.generated.h:5`）；
`SizeOfImage=453693440`、`TimeDateStamp=1788945104`（`guard_profile.generated.h:6`、
`profiles/genshin-cn-7.1.0-readonly.json:11-12`）；只读 profile 文件自身的 SHA-256 被钉为
`ffe576f2c30d117fe11c34972a7b36c9b65e890ca4ff4017a36c72b3da2ed847`
（`native_profiles.py:18`）。

**两代偏移对照**（同一字段在两代里数值不同，是最容易埋雷的地方）：

| 宏 | L-bootstrap | S-7.1.0 | 引用 |
|---|---|---|---|
| `GS_GLOBAL_SLOT_RVA` | `0x555fac8` | `0x5783de8` | `game_context_snapshot.cpp:34` / `readonly.json:21` |
| `GS_CONTEXT_MANAGER_OFFSET` | `0xa3c0` | `0xc210` | `game_context_snapshot.cpp:37` / `readonly.json:22` |
| `GS_SAVE_MANAGER_OFFSET` | `0xac50` | `0xdb50` | `game_context_snapshot.cpp:40` / `readonly.json:23` |
| `GS_MANAGER_KEY_OFFSET` | `0x3c` | `0x38` | `game_context_snapshot.cpp:43` / `readonly.json:24` |
| `GS_MANAGER_DICTIONARY_OFFSET` | `0x18` | `0x10` | `game_context_snapshot.cpp:46` / `readonly.json:25` |
| `GS_OWNER_CONTEXT_OFFSET` | `0xb0` | `0xa0` | `game_context_snapshot.cpp:73` / `readonly.json:35` |
| `GS_OWNER_CONFIG_OFFSET` | `0xa8` | `0xb8` | `game_context_snapshot.cpp:76` / `readonly.json:36` |

---

## 1. 探针清单（PROBE INVENTORY）

「探针」= 一个 `Capture*` 入口，在**游戏进程当前回调线程里**只读地走一遍内存，产出定长 POD
快照，经文件映射 / 回执 hex 回传。所有探针都是**只读、无游戏方法调用、无堆分配**
（`game_context_snapshot.h:107`）。

| # | 探针（入口函数） | 读什么 | 源文件:行 | 结构 / ABI | 真机证据 |
|---|---|---|---|---|---|
| P1 | `CaptureGameContextSnapshot` | 全局根 → context/save manager → **context 字典**（当前 context + 原点）→ **entity 字典**（每实体 owner/id/context/config/configId） | `game_context_snapshot.cpp:362-467`；头 `game_context_snapshot.h:111` | `GameContextSnapshot`，`184 + 32*8 + 512*64 = 33208` B（`game_context_snapshot.h:102`）；实体上限 `kMaxEntities=512`（`:75`） | 14 实体全部有效、PE/主消息循环栈核对通过（`PROGRESS.md:4713`）；79/80 实体只读读回（`PROGRESS.md:665,542`）；**235 实体**（`PROGRESS.md:2290`） |
| P2 | `CaptureGameLevelCatalog` | save→archive→**关卡目录字典**（全部关卡记录 id/key/record） | `game_level_catalog_core.inc:79-126`；头 `game_level_catalog.h:50` | `LevelCatalogSnapshot` 8312 B，`kMaxLevelCatalog=512`（`game_level_catalog.h:18,6`） | 15 唯一关卡记录 1825–1839、当前/选中 1073741839、save 脏标志 0（`PROGRESS.md:2163`）；`PROGRESS-LITE.md:1495` |
| P3 | `CaptureGameLifecycleType` | class 槽 → 类型对象 → 函数槽表 + 相邻 trailing words | `game_lifecycle_type_core.inc:79-138`；头 `game_lifecycle_type.h:30` | `LifecycleTypeSnapshot` 2160 B，`kMaxLifecycleTypeSlots=128`（`game_lifecycle_type.h:14`） | 候选 class 槽 `5826620` 已初始化、9 槽中索引 6 唯一指向 `9037840`（`PROGRESS.md:2147`）；8478 B/56 读取 |
| P4 | `CaptureGameSchedulerCoroutines` | scheduler 列表 → 每个协程 handle 的 holder/iterator/state | `game_scheduler_coroutines_core.inc:139-181`；头 `game_scheduler_coroutines.h:54` | `SchedulerCoroutinesSnapshot` 13472 B，`kMaxSchedulerCoroutineHandles=128`（`game_scheduler_coroutines.h:26,5`） | 3 条有效记录、capacity1600、version104634 前后相等、target0、16270 B/154 读取（`PROGRESS.md:2123`） |
| P5 | `CaptureGameReopenGuardBundle`（+ `guarddraft::Evaluate`） | 依次跑 P1–P4，再验 mode 字典/XOR 表/confirmation 类层级 | `game_reopen_guards_capture_core.inc:36-56`、`game_reopen_guards.cpp:181-196`；头 `game_reopen_guards.h:43` | `guarddraft::Result` 208 B（`game_reopen_guards.h:35`） | 重开前置多次 `not_initialized` / `preflightPassed:false`（`PROGRESS-LITE.md:1492`、`PROGRESS.md:543`）；**未通过**（负结论） |
| A1 | `ExecuteGameSceneAction`（动作，非只读） | 在 P1 基线上校验身份/关卡/锚点/栈，再调用原生 **place / save / batch** | `game_scene_action.cpp:134-307`；头 `game_scene_action.h:34` | `GameSceneActionResult`（`game_scene_action.h:11-23`） | 创建 `1077936129`/`6130`/`6131`/`6132`、batch 6/24 件、原生 save `actionStatus 0`（`PROGRESS.md:2296,4703`） |
| A2 | `ExecuteGameReopenAction`（动作，非只读） | 校验身份/路由/新鲜证据后**单次**调用重开入口 | `reopen_action.cpp:27-44`；头 `reopen_action.h:33` | `ge::reopen::ActionResult` 104 B（`reopen_action.h:20`） | 未曾真机执行（前置 fail-closed）；`REOPEN-VERIFICATION.md` 全篇为**前置检查**，未调用重开 |

**注入骨架（把探针送进游戏回调线程）**：
`hook_receipt_probe.cpp:75-275`（宿主：`SetWindowsHookExW(WH_GETMESSAGE,…)` + `PostThreadMessageW`，
`SetWindowsHookExW` 见 `:144`，消息投递 `:147`）+ `hook_receipt.cpp:7-59`（DLL 侧 `ReceiptHook`，只认
`HR_MESSAGE_ID`/`HR_NONCE`/`lParam==1`，`:14`）。回执经文件映射 `CreateFileMappingW`（
`hook_receipt_probe.cpp:125`）。**单次性**：`attempt.used` 独占文件（`:122`），落盘前先 UAC 高完整性校验（`:56-73`）。
重开观察另有 `hook_reopen_probe.cpp` / `hook_reopen_receipt.cpp` 与 v10 回执
（`hook_reopen_protocol.h:87`，`sizeof(Receipt)==98064`）。

---

## 2. 符号 / 地址 / 偏移，按「能到达什么」分组

### 2.1 全局根与 manager 链


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- P1 里 `GS_CONTEXT_MANAGER_OFFSET=0xc210`；reopen 守卫里另有一个 `contextManagerOffset=0xf390`
  （`profiles/genshin-cn-7.1.0-reopen-guards.json` layout）。**两者同名不同源，勿混**。
- 旧代证据：`PROGRESS.md:6039`（`[*(base+0x555fac8)+0xac50]` 取得管理对象后调 `0xddbfe60`）；
  `PROGRESS.md:4465`（连接对象恒为 `[0x555fac8+0xfbf0]`）。

### 2.2 context 字典 → 当前 context + 原点

结构（`game_context_snapshot.cpp:187-196`）：`Dictionary{address,buckets,entries,bucketLength,entryLength}`，
`Entry` **24 B**（`:196`，注释标注两个函数 `1558dc90` / `16727700`）。装载见 `LoadDictionary`（`:198-210`）：
- `contextDictionary + GS_CONTEXT_BUCKETS_OFFSET (0x28) → buckets`
- `contextDictionary + GS_CONTEXT_ENTRIES_OFFSET (0x30) → entries`（`game_context_snapshot.cpp:403`，注释 `da508a0 ->1558dc90`）
- 桶头在 `buckets+0x20`（`WalkDictionary`，`:243`）；entry 在 `entries+0x20+index*24`（`:252`）
- 匹配 `entry.key == activeKey`（`activeKey` 取自 `contextManager+GS_MANAGER_KEY_OFFSET`，`:387`）者其 `entry.value` = 当前 context（`:259`）
- `currentContext + GS_CONTEXT_ORIGIN_OFFSET (0x38) → origin[3] float`（`:416`）——**关卡原点**。
  [推测] 该原点在数值上等于出生预设点 `(-547.5,-2.5,-547.5)`（依据：MEMORY 锚点
  `spawn-point-is-a-player-template-field`「落点＝关卡原点」+「预设点坐标是六个存档共有的全局常量」）；
  **本文未在 native 源码里找到把二者钉死的 file:line**，故标推测。

### 2.3 entity 字典 → 每个实体记录

- `currentContext + GS_ENTITY_DICTIONARY_OFFSET (0x18) → entityDictionary`（`game_context_snapshot.cpp:417`）
- `entityDictionary + GS_ENTITY_BUCKETS_OFFSET (0x20) → buckets`，
  `+ GS_ENTITY_ENTRIES_OFFSET (0x28) → entries`（`:422`，注释 `16727700: buckets+…`）
- 每 entry 的 `entry.value` = **owner 指针**，`entry.key` = 字典键（`SampleOwner`，`:212-236`）
- owner 字段：
  - `owner + GS_OWNER_ID_OFFSET (0x1c) → id`（`:218`）
  - `owner + GS_OWNER_CONTEXT_OFFSET (0xa0) → context`（`:223`）
  - `owner + GS_OWNER_CONFIG_OFFSET (0xb8) → config`；非空则 `config + GS_CONFIG_ID_OFFSET (0x1c) → configId`
    （`:228-231`，注释 `1156c6e0:1156c7fa..1156c823 序列化该配置ID`）
- **`GameEntitySnapshot.position[3]` 恒未填**：`GE_POSITION_READ` 从不置位
  （`game_context_snapshot.h:81`；`game_context_snapshot.cpp:234` 注释「No guessed transform/component
  offsets; position remains explicitly absent」）。位置只在 **GIL 独立解析**里核对（`native/README.md` 末段）。
- `entityVersion`（`entityDictionary + GS_ENTITY_VERSION_OFFSET (0x3c)`，`:423,436`）前后必须相等，
  否则 `GS_UNSTABLE`（`:442`）——**结构重读自校验**。

### 2.4 关卡观测（GS_READ_LEVEL_METADATA）

`ReadLevelObservation`（`game_context_snapshot.cpp:169-180`）：
- `global + GS_LEVEL_GATE_MANAGER_OFFSET (0xa430) → gate`；`gate + GS_LEVEL_GATE_OBJECT_OFFSET (0x50) → gateObject`
- `global + GS_LEVEL_MODE_MANAGER_OFFSET (0xa440) → mode`；`mode + GS_LEVEL_MODE_OFFSET (0x1cc) → mode == 0xb993`
- `global + GS_LEVEL_MANAGER_OFFSET (0xa960) → level`；`level + GS_LEVEL_EDITING_OFFSET (0xc9) → editing != 0`；
  `level + GS_LEVEL_ID_OFFSET (0x98) → levelId != 0`
- 前后两次观测须相同，否则 `GS_UNSTABLE`（`:458`）；levelId 写入 `snapshot.reserved` 并置 `GS_LEVEL_OBSERVED`（`:459-460`）
- 证据：`PROGRESS-LITE.md:1494`「关卡观测 verified, 1073741839」；`profiles/…-level-observation.json`
  指向反汇编 `LEVEL-1-13568db0.asm`

### 2.5 关卡目录（catalog 字典）

`game_level_catalog_core.inc:58-71`（`ReadRoots`）：
- `saveManager + GSL_ARCHIVE_OFFSET (0x48) → archive`；`archive + GSL_DICTIONARY_OFFSET (0x28) → dictionary`
- `archive + GSL_SELECTED_OFFSET (0x38) → selectedId`；`saveManager + GSL_DIRTY_OFFSET (0xa2) → dirty`
- dictionary 头（`game_level_catalog_core.inc:96-98`）：`+0x20 buckets`、`+0x28 entries`、`+0x30 comparer`、
  `+0x38 count`、`+0x3c version`、`+0x40 free`
- 每 record：`record + GSL_RECORD_ID_OFFSET (0x2c) → id`（`:109,121`）
- 约束：`levelId == selectedId == b.reserved == GSL_EXPECTED_LEVEL_ID`，`dirty<=1`（`:69-70`）
- 「catalog entry」与「context entry」共用同一 24 B 布局（`game_level_catalog.h:8,17`）

### 2.6 生命周期类型（class 槽）

`game_lifecycle_type_core.inc:61-73`：
- `moduleBase + GLT_CLASS_SLOT_RVA (0x5826620) → classPointer`（`:87,102`）
- `moduleBase + GLT_INITIALIZED_RVA (0x5aa8dd1) → initialized`（懒初始化标志，非全局就绪；`:91`，注释 `:92-94`）
- `classPointer + GLT_SLOT_COUNT_OFFSET (0xbe) → slotCount`（`:112`）
- `classPointer + GLT_FUNCTIONS_OFFSET (0xd0) → 函数槽数组`；相邻 `trailingWords`（`:114-115`）
- 目标函数 `moduleBase + GLT_TARGET_FUNCTION_RVA (0x9037840)`，须在槽表里**唯一命中**（`MatchLifecycleFunction`，
  `game_lifecycle_type.h:19-28`）
- 证据：`PROGRESS.md:2147,2179`（索引 6 唯一指向 `0x9037840`；8 状态跳转表、状态 3 调初始化）
- **负结论**：`initialized==0` 时只读探针仍报告诊断 `status=8 / flags=503`，**绝不能**用该证据满足写前置
  （`game_lifecycle_type_core.inc:95-98,133-134`）；`not_initialized` 是重开阻塞点之一（`PROGRESS-LITE.md:1492`）

### 2.7 调度器协程

`scheduler_core.inc:70-137`：
- `global + GSC_SCHEDULER_OFFSET (0xa040) → scheduler`；`global + GSC_OWNER_OFFSET (0xbfd0) → lifecycleOwner`
- `scheduler + GSC_LIST_OFFSET (0x20) → list`；`list + GSC_ARRAY_OFFSET (0x10) → array`
- `list + GSC_COUNT_OFFSET (0x18) → count`；`list + GSC_VERSION_OFFSET (0x1c) → version`；
  `array + GSC_ARRAY_CAPACITY_OFFSET (0x18) → capacity`；数据在 `array + GSC_ARRAY_DATA_OFFSET (0x20)`（`:159-160`）
- 协程类来源：`moduleBase + GSC_MANAGED_TYPES_ROOT_RVA (0x56cf1b8) → managedTypesRoot`；
  `+ GSC_COROUTINE_CLASS_OFFSET (0x1f0) → coroutineClass`（`:82-84`）
- 参考策略 `moduleBase + GSC_REFERENCE_POLICY_RVA (0x54c82c0)`（`:80`）
- 每个 handle（`RowRead`，`:110-136`）：`handle+0 → handleClass`；`handle + GSC_HANDLE_HOLDER_OFFSET (0x10) → holder`；
  holder 字段 `+0x10 token / +0x18 kind(须==2) / +0x20 iterator / +0x40 nativeOwner / +0x48 refcount /
  +0x4c retained(须==1) / +0x50 released`；iterator `+0x18 owner / +0x20 state / +0x10 currentYield`
- 分类枚举 `SchedulerRowDisposition`（`game_scheduler_coroutines.h:9`），分类器 `ClassifySchedulerRow`（`:39-51`）
- **只读逻辑元素**：`arrayBytes = count*8`，容量尾巴不读（`:159` 注释）
- 证据：`PROGRESS.md:2123`（3 条有效、capacity1600、version 前后相等、target0）
- **空状态根因**：`PROGRESS-LITE.md:1492,1500-1502`——scheduler 与 lifecycle 的「已加载≠已初始化」，
  建议用**真正重新进入关卡**触发填充

### 2.8 重开守卫（mode 字典 / XOR 表 / confirmation）

全部在 `game_reopen_guards.cpp`，用固定字面量（无宏）：
- **Confirmation**（类层级确认，`:150-166`）：
  `moduleBase + 0x57cc7f8 → klass`；`klass + 0xc7 → init`；
  `global + 0xf390 → manager`；`manager + 0x30 → context`；`context + 0x18 → value`；
  `moduleBase + 0x5808090 → target`；`value + 0 → actual`；
  `target + 0xc5 → targetDepth`、`actual + 0xc5 → actualDepth`；
  `actual + 0x40 → hierarchy`，取 `hierarchy[(targetDepth-1)*8]` 与 target 比对
- **Early**（mode 记录 / XOR 解码，`:167-179`）：
  `moduleBase + 0x5aab638 → metadata(须==1)`；`moduleBase + 0x57af200 → klass`；
  `global + 0x24b50 → modeDictionary`；mode 记录 `+0x84 → modeEncoded`；
  `moduleBase + 0x578bd50 → xorKey`；`global + 0xf620 → table`；`table + 0x18 → length`；
  表数据 `table + 0x420`，按字节索引 `(x>>24)&255 / 0x100|… / 0x200|… / 0x300|…`（`:176-177`）
- **LookupMode**（`:87-113`）只走目标桶及其冲突链，不枚举整字典；`+0x18 bucketsLen`、`+0x18 entriesLen`
- **根绑定**（`:118-123`）一次读完 moduleBase `0x5783de8/0x5826620/0x5aa8dd1`、global
  `0xdb50/0xa960/0xa430/0xa440/0xbfd0/0xa040` 以及 archive/dict 链
- **Recheck**（`:20-27`）：每个 span 二次读比对，任何字节变化 → `UNSTABLE`
- 生成头 `guard_profile.generated.h`：锚点 `kAnchors[]`（`:10-15`，RVA `0xcbe0220/0xcbe1000/0x85eea70/
  0xc28c780/0x173770b0/0xbb2c5e0`）、hotfix `kHotfix[]`（`:17`：`0x573c867,0x573c860,0x573c868,
  0x5734cc1,0x5730400,0x56fb406`）
- **结论**：P5 是 6 个「候选」里最未闭环的一个；`check_reopen_prerequisites.py live` 反复 `blocked`
  （`PROGRESS.md:543`），**没有真机通过记录**

### 2.9 原生调用入口（唯一被证明可调用的四个）

| 名称 | 现行 RVA | 旧 RVA | ABI | 源:行 |
|---|---|---|---|---|
| **place（放置工厂）** | `0x106df3c0` | `0xb7a1aa0`（调用者 `0x13629a10`/`0x1362a429`） | `void*(__cdecl)(context, uint32 template, uint8 builtin, Vec3* pos, Vec3* rot_deg, Vec3* scale, uint32 reqId, uint8 flag8, void* opt, uint8 f10, uint8 f11)` | `scene_calls.h:12-19`；`profiles/genshin-cn-7.1.0-readonly.json:17`（PLACE 锚点） |
| **save（原生保存）** | `0x11fe2f00`（调用者 `0x135635e4` 传 `global+db50`） | `0xddbfe60`（`global+ac50`） | `int32(__cdecl)(void* saveManager)`，成功=0 | `scene_calls.h:22-24`；`game_scene_action.cpp:37-38` |
| **level getter** | `0x13568db0` | `0xe920a70` | `uint32(__cdecl)(void* levelManager)` | `game_scene_action.cpp:31,174` |
| **reopen** | `0x13564e90` | — | `void(__cdecl)(void* levelManager, void* record, void* callback)` | `reopen_action.cpp:38`；`reopen_route.generated.h` |

- `place_builtin` 的装配：世界坐标**减** context 原点得局部坐标（`scene_calls.cpp:21-23`），
  `builtin` 标志默认 `1`，可被 `HR_PLACE_BUILTIN` 覆盖（`scene_calls.cpp:41-45`）；
  21 个调用点（7.1）的 `builtin` 取值分布见 `scene_calls.cpp:33-36`（8 个传 1、6 个传 0、3 个来自寄存器）
- reopen 路由的**全部锚点**（`reopen_route.generated.h`，逐字节比对）：
  `0x13564e90 / 0x13564fa0 / 0x135665f0 / 0x77c9d70 / 0xa9d3270 / 0x85eea70 / 0xcbe0220 / 0xcbe1000 /
  0x11c06060 / 0x11fc6fc0 / 0x11fd3fb0`；hotfix 25 项同文件
- `reopen_action_validation.cpp:59-67`（`ValidateCurrent`）= 一次完整根遍历，是**当前 build 偏移的权威清单**：
  `moduleBase+0x5783de8→global`、`global+0xa960→manager`、`global+0xdb50→save`、`save+0x48→archive`、
  `archive+0x38→selected(+0x2c recordId)`、`manager+0x98→level`、`manager+0xc9→editing`、`save+0xa2→dirty`、
  `global+0xa440→mode`、`mode+0x1cc→modeId`、`global+0xa430→gate`、`gate+0x50→gateObject`

### 2.10 判定用常量（身份门）

- `guard_profile.generated.h:6`：`kImageSize=453693440`、`kTimestamp=1788945104`、`kLevel=1073741840`、
  `kPid=78120`、`kCreation=134355975635136628`
- `profiles/genshin-cn-7.1.0-readonly.json:39`：回调栈锚 RVA `0xabaa78, 0xac18fa`；
  hotfix 字节 RVA `0x57399e8, 0x56f4a0d, 0x57372d8, 0x574f96c`
- 进程/窗口身份：`native_profiles.py:17` 目标镜像 `C:\Games\Genshin Impact Game\YuanShen.exe`；
  `:164` 窗口类名必须 `UnityWndClass`；拒绝 WOW64（`:151`）
- 单次性：动作回执要求 `HR_TARGET_PID/TID/creation` 三项同时匹配（`reopen_action.cpp:19-25`）

### 2.11 候选与已否证（不是「已到达」）

- **`0x1182cea0` 按 `entry+0x30` 查 `component+0x30` 列表** ——**编辑器侧**（`BeyondEditor.exe`）
  反汇编，出自 string-table 下游，与节点图移除吻合；**不是游戏原生路径**，也**未证明是几何写入**
  （`PROGRESS.md:5701`，gameplan `README.md:106` 引用它时也标「已见…行走」，只当线索）。
- **编辑器 38 条命令无 transform** —— `beyondEditObjService` 的 `Modify*` 家族只有 Name/Tag/Faction/Suite，
  `ApplyPrefabInstanceChange` 只吃 prefabId（`docs/PROGRESS-BY-FUNCTION.md:225-228`；gameplan `README.md:112`）。
  ⇒ `entity.transform` 负结论。
- **`0xd9646b0` 与几何提交共用** —— 曾据此猜几何能力，**已明确不能据此推断几何修改**
  （`PROGRESS.md:5701`）。
- **热补丁分支**：`0xa223420` 的 2001 走正常高分支，**仍不排除**热补丁或其它间接注册（`PROGRESS.md:5673`）
  ——即「读到的静态分支」≠「不存在其它入口」。

---

## 3. 缺口：今天**读到**什么 vs 要解锁**还须读**什么

### 今天已经能读（有真机回执）
1. 全局根 + 5 个 manager（context/save/level/gate/mode）+ owner/scheduler 指针（§2.1）
2. 当前 context 的**原点**（3 float）（§2.2）
3. 每个实体的 **owner / id / context / config / configId**（§2.3）——**但没有位置**
4. 关卡 id / 编辑态 / mode / gate（§2.4）、关卡目录记录（§2.5）
5. 生命周期类型的函数槽表（§2.6）
6. 调度器协程列表与 holder/iterator 状态（§2.7）
7. 重开守卫的 mode 字典/XOR/confirmation（§2.8，**未通过**）

### 要解锁被挡的那一半，还须读什么（与 gameplan `README.md:104-112` 的「要挖什么」一一对应）

| 被挡的能力 | 现状 | 还须读的原生状态 | 已知线索 / 部分路径 |
|---|---|---|---|
| **`entity.transform`**（改已有实体位置/朝向/缩放） | `position` 恒 null（`game_context_snapshot.h:81`） | 实体/owner 上的**变换字段偏移**，或 component 列表 | 保存侧收集链已见 `ddc7cd0→ddc09b0`（遍历 `context+0x20`）、`1156c6e0` 生成带 ID/配置/附属对象记录（`PROGRESS.md:5131`）；**位置/缩放字段映射仍未落**（`PROGRESS.md:6039`「尚无…位置/缩放字段映射」） |
| **组件 / UI / 属性**（M1 触发器、F5 反馈） | 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 ui/component/property **0 命中** | 实体 **component 列表**的字段布局 | `PROGRESS.md:5701`（`0x1182cea0` 沿 `component+0x30` 行走，编辑器侧；`component+0x30` 是**旧记号**，非游戏侧 kind——kind 在 `[comp+0x34]`，见 `COMPONENT-CONTAINER-RECONCILED.md`）；需在**游戏侧**找到同类列表 + 写入原语 |
| **货币/道具/背包/商店模板**（类型 10/8/11/15） | 工具无一能建模板 | 建模板的**原生调用**或存档里模板所在**字段号** | 存档侧：`.gil` 字段号已解一部分（`gil_container.py`，记忆锚点 `gil-level-file-is-decodable`）——但模板段是否覆盖未证 |
| **字典常量写入**（类型 27） | 构造器 `1088 建立字典`/`1788 拼装字典`/`948` 与取元素 `1158 以键查询字典值` 均存在（引脚为**泛型** spt 0）；**把字典写成常量**仍写不进（2026-10-12 复核，见 `DICT-WRITE-PROBE.md`） | 编辑器如何序列化字典 ⇒ slot/端口合同 | `docs/research/reverse-eng-20261010/DICT-CONSTRUCT-SEARCH.md`、`DICT-WRITE-PROBE.md`（同目录，本次任务外） |
| **地形编辑**（M6a） | `.gil` field 7 **全仓 0 读写者** | field 7 的编解码器 | `docs/gameplan/TERRAIN-STATUS.md:32-50`；无地形类节点（`:58`） |
| **建/开关卡**（`level.manage`） | 7.1 版本门 fail-closed | 重新基线 `version_guard` 的 `"all"` 判定 | `tools/compatibility/version_guard.py:344`；`TERRAIN-STATUS.md:72-74` |
| **后台起停试玩**（`playtest.control`） | missing | 起/停试玩的**原生调用** | 无已知入口；`docs/PROGRESS-BY-FUNCTION.md:150` |
| **重开闭环**（`verify.reopen`） | 守卫 `not_initialized` | 让 lifecycle/scheduler 真正初始化的**触发动作** | `PROGRESS-LITE.md:1500-1502`：怀疑须**真正重新进入关卡**；且代码钉死关卡常量 `1073741840`（`PROGRESS.md:413`） |

**两条判据**（照 CLAUDE.md §一）：
- 「读不到」不等于「不存在」——本表每一格都给了**要挖什么**，不是「没做」。
- **能读 ≠ 能写**：上面 7 项里前 6 项读到的都是**只读快照**，没有一项证明存在写入原语；
  唯一被证明**可写的原生动作**是 §2.9 的 4 个入口，其中：**place / save 有直接真机回执**；
  **level getter 在 create/save 动作内部被真实调用**（回执里的 `levelId` 即其返回值，`game_scene_action.cpp:174-176`）；
  **reopen 未真机执行**（前置 fail-closed，`PROGRESS.md:543`）。

---

## 4. 证据指针（原件位置，均为仓库内相对路径）

| 主题 | 证据 |
|---|---|
| 只读上下文快照 | `PROGRESS.md:4713`（14 实体+栈核对）、`:665`（79 实体）、`:542`（80 实体）、`:2290`（235 实体） |
| 关卡目录 | `PROGRESS.md:2163,2147`；`.runtime/verification/interface-experiments-20260927/p03/…` |
| 生命周期类型 | `PROGRESS.md:2147,2179`；`.runtime/verification/reopen-repair-20260929/lifecycle-lazy-diagnostic/` |
| 调度器协程 | `PROGRESS.md:2123` |
| 重开守卫（未通过） | `tools/game-executor/REOPEN-VERIFICATION.md`；`PROGRESS.md:543,563`；`.runtime/verification/verification-chain-repair-20260929/…` |
| create/save 真机 | `PROGRESS.md:4703,4713`；`.runtime/game-executor/hook-receipt-live-20260922/prepared-113740-7487b545/live-create-save-verified.json` |
| R170 六阶段 CRUD | `PROGRESS.md:2296,2305`；`.runtime/verification/update-repair-20260926/crud-r170-acceptance.json` |
| profile 定义 | `tools/game-executor/profiles/*.json`；`tools/game-executor/native_profiles.py` |
| 生成头 | `tools/game-executor/native/guard_profile.generated.h`、`…/reopen_route.generated.h` |
| 构建脚本 | `build_readonly_profile.py`、`build_scene_profile.py`（输出 `target_config.h`，`:269`）、`build_reopen_profile.py` |

---

## 附：一句话总览

原生侧今天的能力 = **4 个可调用入口（place / save / level-getter / reopen） + 5 个只读快照
（context / catalog / lifecycle-type / scheduler / guard-bundle）**。**读得最广的是「谁在场景里」
（实体身份、配置、关卡目录、调度器），读得最窄的是「东西摆在哪、由什么组成」——位置偏移与
component 列表至今是空的**，这正是 `entity.transform` 与模板/组件/UI 那一半被挡的**共同根因**。
