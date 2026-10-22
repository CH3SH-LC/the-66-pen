> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #7 挖 — `.gil` 顶层字段台账（GIL-FIELD-LEDGER）

> 产出日期：2026-10-10。位置：`docs/research/reverse-eng-20261010/GIL-FIELD-LEDGER.md`。
> 任务：把散落在 `gil_container.py` docstring、`terrain.py`、`level_settings.py`、
> `level_directory.py`、`entity_geometry.py`、`field_diff.py`、`backend/*`、记忆与第三方语料里的
> **`.gil` 顶层字段号知识**，集中成一张**经证据**的表。
>
> **只读**：本文件只读`read_bytes`真实存档；未起 helper、未连 bridge、未发任何报文、未写任何字节。
> 全部数字由一次性脚本机械产出，脚本在 `.runtime/scratch/`（**不在 `tools/`**）。

---

## 0. 方法与口径

### 0.1 机械来源（可复现）

| 脚本 | 作用 |
|---|---|
| `.runtime/scratch/gil_field_ledger_scan.py` | 走遍 `LocalLow` 下**每一个** `.gil`，按顶层字段号统计「命中文件数 / wire 类型 / 值字节大小区间」；输出 `.runtime/scratch/gil_field_ledger_scan.json` |
| `.runtime/scratch/gil_field_detail_dump.py` | 对代表性 `.gil`（`1073741842` / `1073741831` / `1073741826`）逐字段打印 hex 预览、能否当嵌套消息解（子字段号）、UTF-8/ASCII 串 |


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**扫描范围**：`C:\Users\PUBLIC_USER\AppData\LocalLow\miHoYo\原神\BeyondLocal\` 下 **37 个 `.gil`**
（`Beyond_Local_Save_Level\` 18 个 + 其 `Temp\` 镜像 18 个 + `UpgradeBackup\1073741835.gil` 1 个），
**18 个不同的关卡 id**（`1073741825`…`1073741842`）+ 2 个 `.gip`。
另两个 uid 目录（`100559494` / `343269915`）**是空的**（`find` 无任何文件）。

> ⚠️ `#files` 一列按**文件**计数，因此 `Temp/` 镜像会把每个 id 数两遍。要按 id 去重看第三列
> `#ids`（满分 18）。

### 0.2 三层必须分开（`CLAUDE.md` 铁律）

本台账每一行都标了 **confidence**，三个值严格对应三层，不得混称：

- **实证 `proven`** — 本仓代码点了名（有 `file:line`）**且**本机真实字节与之一致。
- **推断 `inferred`** — 有来源点了名（本仓散文 / 第三方语料 / 记忆），但**本机字节只做到「不矛盾」**，
  没有独立证成。
- **未知 `unknown`** — 没有任何来源点名。

`文档写了什么` / `工具能做什么` / `真机验证过什么` 的区别，在 §4 的「读方」与 §6 的「冲突」里逐条落实。

### 0.3 容器框架（不是字段，是字段的外壳）

`.gil` 与 `.gip` 同一种封装，payload 前 **20 字节**头 + 尾 4 字节 trailer
（`tools/beyond-save/gil_container.py:20-34,86-113`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


下面的「字段号」全部指 **payload 顶层**的 protobuf 字段号（`parse_fields(payload)` 的直接子字段）。

---

## 1. 顶层字段总表（37 个真实 `.gil`，18 个 id）

`size` 是**值字节**的观测区间（length-delimited = `len(data)`；varint = 它的编码长度；
fixed32/64 = 4/8）。**空 size=0** 表示「该字段存在，但值是一条 0 字节的子消息」——proto3 里这是
「写了但为空」，**不等于字段缺席**。

| 字段 | #files | #ids | wire | size | 它是什么 | confidence | 读方（今天） |
|---:|---:|---:|---|---:|---|---|---|
| 1 | 20 | 10 | varint | 5 | 关卡 id 的**冗余副本**（= 文件名） | **proven** | `gil_container.py:63`（`parse_level` 交叉校验 `:268-275`） |
| 2 | 37 | 18 | len | 14..26 | 关卡名（UTF-8） | **proven** | `gil_container.py:64` |
| 3 | 29 | 14 | len | 0 | **空**；两第三方说法冲突（`未知` vs `export_info`） | unknown | 无 |
| 4 | 29 | 14 | len | 877..1195 | 元件/控件定义表（子消息 2×`field1`） | inferred | 无（记忆曾误记「level_id 之类」） |
| 5 | 29 | 14 | len | 2821..274776 | **实体表** | **proven** | `entity_geometry.py:124` |
| 6 | 29 | 14 | len | 1205..6679 | **页签/目录树**（root field 6） | **proven** | `level_directory.py:66` |
| 7 | 29 | 14 | len | 3642..3642 | **地形表**（也带出生点/原点三元组） | **proven**(结构) | `terrain.py:85` |
| 8 | 29 | 14 | len | 0..210 | 未知；第三方猜「也是元件数据」 | unknown | 无（根级） |
| 9 | 29 | 14 | len | 2738..3415 | UI 控件组层级（子 `501/502/503`，名字含 `*Hierarchy`） | inferred | `verify_graph_on_disk.py`（仅归因） |
| 10 | 29 | 14 | len | 2..24431 | **节点图** | **proven** | `field_diff.py:64`；`verify-created-save.py:187` |
| 11 | 29 | 14 | len | 336..449 | **关卡设置**（阵营/预设点…） | **proven** | `level_settings.py:81` |
| 12 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 14 | 29 | 14 | len | 78..78 | 未知（8×`{1:int,2:varint}`） | unknown | 无 |
| 15 | 29 | 14 | len | 2708..8336 | **类型化资产记录表**（背包模板 type11 等） | inferred | 无代码（仅 `TEMPLATE-CREATION-MINE.md`） |
| 16 | 29 | 14 | len | 0 | 未知；第三方称「技能动画/事件轨道」 | unknown | 无 |
| 17 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 18 | 29 | 14 | len | 83..83 | 第三方称「镜头模板」；值含「…镜头」串 | inferred | 无 |
| 19 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 20 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 21 | 29 | 14 | len | 0..3 | 未知（多为空） | unknown | 无 |
| 22 | 29 | 14 | len | 0..83 | 第三方称 `LevelFlags` | inferred | 无 |
| 23 | 29 | 14 | len | 7..7 | 未知（`{6:100, 7:1.0f}`） | unknown | 无 |
| 25 | 29 | 14 | len | 131..131 | 第三方称「外围系统（计分/成就/排行榜）」 | inferred | 无 |
| 27 | 29 | 14 | len | 0 | 第三方 & 本仓脚本称「装饰物/placements」，**本机全为空** | inferred(名)/空(实) | `verify-created-save.py:154`（守恒检查） |
| 29 | 29 | 14 | len | 55..55 | 编辑器信息（含版本串 `CNRELWin7.1.0`） | **proven** | `field_diff.py:68`（散文） |
| 30 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 31 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 32 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 33 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 34 | 8 | 4 | varint | 1 | 常量 1；**只在占位关卡**出现 | inferred(常量) | `register_level.py:59`（建关卡模板） |
| 35 | 29 | 14 | len | 6..772 | 未知 | unknown | 无 |
| 36 | 29 | 14 | len | 62..62 | 第三方称「多语言文本配置」（值含「全局/你好！」） | inferred | 无 |
| 37 | 29 | 14 | len | 0..13010 | 未知 | unknown | 无 |
| 38 | 29 | 14 | len | 4..4 | 未知（`{1:1,2:1}`） | unknown | 无 |
| 39 | 37 | 18 | varint | 5 | **创建者 uid**（= 目录名 `100000001`） | **proven** | `gil_container.py:65` |
| 40 | 37 | 18 | varint | 5 | **时间戳**（与文件 mtime 同月） | **proven** | `gil_container.py:66` |
| 41 | 37 | 18 | varint | 1 | 常量 1 | inferred(常量) | `register_level.py:59` |
| 42 | 25 | 12 | varint | 1 | 常量 1 | inferred(常量) | `register_level.py:59` |
| 43 | 29 | 14 | len | 5 | 版本串 `7.1.0`（**第三方表里没有**） | unknown(名)/实证(值) | 无 |
| 44 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 45 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 46 | 29 | 14 | len | 22..110 | **存档历史头**（save-history head），**有名无解** | inferred | `save_delta_attribution.py:64` |
| 48 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 49 | 29 | 14 | len | 0 | 未知 | unknown | 无 |
| 50 | 12 | 6 | len | 2 | 未知（`{2:1}`） | unknown | 无 |
| 52 | 14 | 7 | varint | 5 | **= 关卡 id**（逐位等于文件名） | inferred(强) | `save_delta_attribution.py:60` |
| 53 | 14 | 7 | varint | 5 | **= field 40 时间戳**（逐位相等） | inferred(强) | `save_delta_attribution.py:60` |

**未观测到的号**（本机 0 文件命中，非「不存在」）：`13, 24, 26, 28, 47, 51` 及 54+。
`.gil` 顶层号不是连续小整数，**缺号是正常的**（proto3 里没写的字段就不出现）。

### 1.1 `.gip`（玩家档案，subtype=1）——**不是** `.gil`

架构不同，顶层**只有 3 个号**（`TEMPLATE-CREATION-MINE.md:22-24,85-101`，本人只读复核一致）：

| 字段 | 类型 | 含义 | 读方 |
|---:|---|---|---|
| 1 | len | 页签容器（`1>2>4`，见 `gil_container.py:390-416`） | `parse_tabs` |
| 2 | len（repeated ×18） | 关卡引用表（每条 `{1:id, 2:name, 3:ts, 5:flag}`） | `parse_profile :363-387` |
| 3 | varint | 当前关卡 id | `parse_profile :381-386` |

`read_profile` 在保存档容器上会撞 `field 14246604 has reserved wire type 7`
（`.claude memory gil-level-file-is-decodable`）——那是另一种封装，**别拿 `read_profile` 读关卡 `.gil`**。

---

## 2. 实证（proven）字段——逐条证据

### 2.1 field 1 — 关卡 id 的冗余副本
- **代码**：`LEVEL_FIELD_ID = 1`（`gil_container.py:63`）。
- **字节**：20 个文件里 varint 值**恒等于文件名 stem**（脚本逐文件核对：
  `1073741826→1073741826`…）。`parse_level` 拿它跟文件名交叉校验，冲突就抛
  （`gil_container.py:268-275`）。
- **缺口**：默认「大关卡省略 field 1」的说法**已过时**——见 §6.1。

### 2.2 field 2 — 关卡名
- **代码**：`LEVEL_FIELD_NAME = 2`（`gil_container.py:64`）。
- **字节**：UTF-8，如 `1073741842` = `自定义页签_5_存档`（dump 实证），`1073741831` = `newdemo_存档`。

### 2.3 field 39 / 40 — 创建者 uid / 时间戳
- **代码**：`LEVEL_FIELD_CREATOR_UID = 39`、`LEVEL_FIELD_TIMESTAMP = 40`（`gil_container.py:65-66`）。
- **字节**：field 39 = `100000001`（**等于所在目录名**，`gil_container.py:55-56`）；
  field 40 落在 **2026-09-02 … 2026-10-07**（与各文件 mtime 同期；`gil_container.py:57-58` 的
  「all in September 2026」是按最初 4 文件写的，现已跨到 10 月）。
- 这两号在**全部 37 文件**都出现（`#files=37`）。同为「每文件都有」的还有 field 2（len）与 field 41（varint=1）。

### 2.4 field 5 — 实体表
- **代码**：`ENTITY_TABLE_FIELD = 5`（`entity_geometry.py:124`），模块文档 `:19-24`。
- **字节**：repeated `field 1` 包起来的实体记录；`1073741841.gil` 有 **479** 条（最大 274776 B），
  `1073741842.gil` 12 条（3748 B）。每条 **entry field 1 = 实体 id、field 8 = 模板号**
  （`entity_geometry.py:125,127`，模板号对应关系由 `GEOMETRY-THREE-WAYS.md:172,200` 与真机 `HR_TEMPLATE_ID` 逐位对齐）。

### 2.5 field 6 — 页签 / 目录树
- **代码**：`ROOT_FIELD_DIRECTORY = 6`（`level_directory.py:66`）；子结构
  `entry{1:id, 2:owner{1:name,3:tag}, 3:body{1:name,3:type,5:member{1:group,2:id}}}`
  （`level_directory.py:20-29,68-81`）。
- **字节**：`1073741831` 33 条、`1073741842` 42 条（其中 42 条里最后一条**缺 field 1** = 已知损坏形态，
  `level_directory.py:31-40`）。
- `entity_geometry.py:92-97` 独立复核同结论（「root field 6 不是实体几何」）。

### 2.6 field 7 — 地形表
- **代码**：`FIELD_TERRAIN_LIST = 7`（`terrain.py:85`）；结构
  `7 > 1(地形) > {1:id, 2:name, 3:transform{1:{1,2,3}=X,Y,Z}, 4×400 格}`
  （`terrain.py:19-34,86-92`）。
- **字节**：`1073741825/828/829` 三关的 field 7 **逐字节相同（3642 B，sha256[:16]=1c9d2287d86fbd98）**
  ⇒ 都还是默认地形（`TERRAIN-STATUS.md:47-52`）；`1073741826/827` **无 field 7**（占位关卡）。
- **同名冲突**：本字段第一条的 `2` 解出名字 **`地形01`**（byte 实证，`terrain.py:28`），但
  `.claude memory gil-level-file-is-decodable` 把 field 7 记作「**预设点表**」，`level_settings.py:40-42,459-461`
  又把 `field7>1>3>1 = (-547.5,-2.5,-547.5)` 记作**出生点坐标**。三种读法指同一个字节区（见 §6.3）。

### 2.7 field 10 — 节点图
- **代码（散文）**：`field_diff.py:64-67` 记「field 10 len 2→5789，值是**图本身**，新载荷含 `MW_API_`
  与节点图结构」；`verify-created-save.py:187` 把它当「Old node graph section」守恒检查。
- **字节**：`1073741842.gil` field 10 = 5789 B，ASCII 串 `MW_API_FARM_V0/V2/V3/FULL/…`；
  `1073741831.gil` = 12604 B，ASCII 串 `MW_Platform_Calibration_20260916`。**两处独立指向「节点图」。**

### 2.8 field 11 — 关卡设置
- **代码**：`LEVEL_FIELD_SETTINGS = 11`（`level_settings.py:81`）；子消息 `1..10`
  （`level_settings.py:34,496-548`）。
- **字节**：值含中文串 `初始玩家阵营`/`出生点1`/`新建预设点` 与 `UI_MarkPlayer_Faction_N`
  （`level_settings.py:20-22,175-179`）。子结构 `1=基础/生效范围候选`、`2=阵营`、`3=出生点`、`5=预设点`、`6=人数`
  （`level_settings.py:90-94`）。

### 2.9 field 29 — 编辑器信息
- **代码（散文）**：`field_diff.py:68-71` 记「field 29 是版本 `7.1.0` 串 + 尾随时间戳重写」。
- **字节**：值 = 子消息 `{1..5}`，`1` = `CNRELWin7.1.0`（1842）/ `CNRELWin7.0.0`（1831），后随 4 个数字串。

---

## 3. 推断（inferred）字段

| 字段 | 谁点的名 | 本机字节反证 / 旁证 |
|---:|---|---|
| 4 | 第三方 `GIL.md:17-18` = `Components`（玩家和元件模板） | 子消息 2×`field1`，串含 `GI_MoveHead/MoveHead/GI_FootR/RFoot/LFoot/…`（像骨骼/控件名，与「元件模板」不矛盾） |
| 9 | 第三方 `GIL.md:32-33` = `UIControlGroup` | 子 `501/502/503`，串含 `HierarchyRoot`/`ExclusiveEleGroupHierarchyRoot`/`ClientUIRootHierarchy` ⇒ 形状像 UI 层级；**与本仓 `verify_graph_on_disk.py:38` 的「sibling level ids」说法冲突**（§6.2） |
| 15 | 本仓 `TEMPLATE-CREATION-MINE.md:104-133`（typed asset table）；第三方 `GIL.md:47-48` | 子 `{1:{1:id,2:cnt,4:组件块}}`；id 类型号 = `(id>>22)-256`，本机只见 type 11/27/4/5（`TEMPLATE-CREATION-MINE.md:120-128`） |
| 18 | 第三方 `GIL.md:56-57` = `CameraTemplates` | 子 `[1]`，串含「…镜头」 |
| 22 | 第三方 `GIL.md:62-63` = `LevelFlags` | `1831` 值 = `{1:"PropertyTransform",2:1}`（更像功能旗帜/开关） |
| 25 | 第三方 `GIL.md:68-69` = `PeripheralSystem`（计分/成就/排行榜） | 子 `[2,3,4]`；无法在字节层证成 |
| 27 | 第三方 `gil.proto` = `placements`；本仓 `verify-created-save.py:154`、`build-static-level-draft.py:4` | **本机 29 个真实 `.gil` 的 field 27 全是空**（size 0）——见 §6.4 |
| 34 / 41 / 42 | 本仓 `register_level.py:59`（`TEMPLATE_FIELDS`），注释称「占位关卡自带」 | 值恒 `1`；**34 只在 4 个占位 id 出现**，41 全 18 id 出现，42 在 12 个 id 出现（§6.5） |
| 46 | 本仓 `save_delta_attribution.py:31-36,64`；`save_verification.py:32,565` | 「存档历史头」，32 位字 `R` **有名无义**；子 `field1 ×N`，`22..110 B`；更新规则未定 |
| 52 / 53 | `.claude memory gil-level-file-is-decodable`；`save_delta_attribution.py:60` 列为稳定根 | **逐位实证**：14 个文件里 `f52 == 文件名 id` 且 `f53 == field 40`（§1 表脚注） |

> `29` 同时被「散文（`field_diff.py`）」与「字节」证成，故放在 §2.9 而非本节。

---

## 4. UNKNOWN 区——**没人点名**的字段

每个号给**字节证据**（`1073741842.gil`，除非另注），**绝不从 size 猜含义**。

| 字段 | wire | size | 字节证据 | 备注 |
|---:|---|---:|---|---|
| 3 | len | 0 | `EMPTY` | protobuf「写了但空」。**两个第三方来源互相矛盾**：`genshin-miliastra-file-format/…/GIL.md:14-15` 写「id=3 // 未知字段」，而 `auto-miliastra …/gil.proto` 写 `string export_info = 3`。值恒空 ⇒ **本机无法裁决**，按纪律归未知 |
| 8 | len | 0 / 210 | 全空；**仅 `1073741832.gil` = 210 B** | 根级无读方（注意 `entry field 8` 是**另一回事**：实体模板号，`entity_geometry.py:127`） |
| 12 | len | 0 | `EMPTY` | |
| 14 | len | 78 | `0a06108280808604…` → 8×`{1:int,2:varint}` | |
| 16 | len | 0 | `EMPTY` | 第三方猜「技能动画/事件轨道」，未证成 ⇒ 仍列未知 |
| 17 | len | 0 | `EMPTY` | |
| 19 | len | 0 | `EMPTY` | |
| 20 | len | 0 | `EMPTY` | |
| 21 | len | 0..3 | 多为空；`1831` = `{1:23}` | |
| 23 | len | 7 | `30643d0000803f` = `{6:100, 7:1.0f}` | |
| 30 | len | 0 | `EMPTY` | |
| 31 | len | 0 | `EMPTY` | |
| 32 | len | 0 | `EMPTY` | |
| 33 | len | 0 | `EMPTY` | |
| 35 | len | 6..772 | 子 `[1]`；`1842` = 10 B | |
| 37 | len | 0..13010 | `1831` = 9240 B 近随机字节（ASCII 无意义串） | 疑似压缩/二进制块 |
| 38 | len | 4 | `08011001` = `{1:1,2:1}` | |
| 43 | len | 5 | UTF-8 `7.1.0` | **第三方表里没有此号**；值像版本串但无人命名 |
| 44 | len | 0 | `EMPTY` | |
| 45 | len | 0 | `EMPTY` | |
| 48 | len | 0 | `EMPTY` | |
| 49 | len | 0 | `EMPTY` | |
| 50 | len | 2 | `1001` = `{2:1}` | |
| 34/41/42 | varint | — | 恒 `1` | 见 §3（有「常量 1」的来源，但**无含义**，故亦可归此区） |

---

## 5. 「今天谁在读」（工具能做什么 = 全静态读源码）

| 字段 | 读者 | 读法 |
|---:|---|---|
| 1, 2, 39, 40 | `tools/beyond-save/gil_container.py` | `parse_level`，只读 |
| 5 | `tools/beyond-save/entity_geometry.py` | `read_entity_records`，只读 |
| 6 | `tools/beyond-save/level_directory.py` | `read_directory`/`check_directory`，只读 |
| 6 | `tools/game-executor/verify-created-save.py:90-92` | 找 `kind==3` 的那条目录，只读 |
| 7 | `tools/beyond-save/terrain.py` | 读 + **仅内存**写（不落盘 API） |
| 10 | `tools/game-executor/verify-created-save.py:187` | 守恒检查（旧图段不许变） |
| 10, 27 | `tools/game-executor/verify-created-save.py:154,187` | 守恒检查 |
| 11 | `tools/beyond-save/level_settings.py` | `read_level_settings`，只读 |
| 1..53（任意号） | `tools/beyond-save/field_diff.py` | 按号逐字段差分，**不给名字** |
| 5, 6, 9, 10 | `tools/gameplan/verify_graph_on_disk.py` | 把 id 命中**归因到 root 字段 span**，只读 |
| 1, 2, 10, 27, 39, 40, 41, 52, 53 | `backend/save_delta_attribution.py:60` | 列为 `ALWAYS_STABLE_ROOTS`（除非 intent 声明，否则必须不变） |
| 5, 6 | `backend/save_delta_attribution.py:62` | `SOURCE_BEARING_ROOTS`（只允许在「有证语义源」下变） |
| 46 | `backend/save_delta_attribution.py:64`、`backend/save_verification.py:32,565`、`tools/game-executor/vendor/g02_savediff_gate.py` | 存档历史头，**移动即判 blocked**（无一 `pass`） |
| 3（`.gip`） | `backend/save_delta_attribution.py:68` | `GIP_CLOCK_FIELD=3`，存档墙钟 |
| 34, 41, 42 | `tools/beyond-save/register_level.py:59` | 建新关卡时写入模板常量 |
| 1, 2, 39, 40 | `tools/beyond-save/register_level.py:87` | `IDENTITY_FIELDS`，建关卡时改写 |

**没有代码读的号**：`3, 4, 8(根级), 9(仅归因), 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 25, 30, 31, 32, 33, 35, 36, 37, 38, 43, 44, 45, 48, 49, 50`。
其中 **field 15 是本机唯一「编辑器资产序列化到磁盘」的落点候选**（`TEMPLATE-CREATION-MINE.md`），
但**尚无一字节的读/写代码**——这是最值得补的缺口。

---

## 6. 台账的副产品：发现的**冲突**与**过时注释**（记录，不擅自改本任务外的文件）

> 按 `CLAUDE.md`「注释写了假事实也是缺陷」，以下逐条列出，供后续单独修复。**本任务只拥有
> `GIL-FIELD-LEDGER.md`，故不改 `gil_container.py` 等文件。**

### 6.1 `gil_container.py:59-62` 的「field 1 只在小占位关卡」**已过时**
原文：「field 1 … PRESENT ONLY IN SOME FILES. The two large levels (61 KB and 21 KB) omit it
entirely; the two small placeholder levels carry it.」
**本机现状**：`#files=20`，其中**大关卡**（如 `1073741835` 148 KB、`1838`–`1842`）**也带 field 1**；
不带 field 1 的是**较老的** `1073741825/828/829/830/831/832/833/834`。这句是按最初 4 个文件写的，
**必须重写为「按写入器版本分代」**，否则会误导反查。

### 6.2 field 9 的两种读法冲突
`verify_graph_on_disk.py:38,78` 称 root field 9「lists sibling level ids」（把命中的
`graph_id` 归因到它）；第三方 `GIL.md:33` 与字节形状（`*Hierarchy` 名字、`501/502/503` 层级）
都指向 **`UIControlGroup` 层级树**。二者**未解决**——引用时须写明「冲突」，不得单采一方。

### 6.3 field 7 的三种读法（同一个字节区）
- 本仓代码 + 字节：**地形**（名字 `地形01`、`4×400` 格网）——`terrain.py:19-34,85`。
- 本仓记忆：**预设点表**（`.claude memory gil-level-file-is-decodable`）。
- 本仓散文：**出生点坐标**（`level_settings.py:459-461` / 记忆 `spawn-point-is-a-player-template-field`）。
字节只能证成「field7>1 的 `1/2/3/4` 子结构」；**「地形」与「预设点/出生点」谁对，本机无法裁决**
（三关 field 7 逐字节相同、坐标恒 `(-547.5,-2.5,-547.5)`，样本不动）。

### 6.4 field 27「placements/装饰物」**在本机恒为空**
`verify-created-save.py:154`、`build-static-level-draft.py:4`、第三方 `gil.proto` 都说 field 27 装放置物，
但**本机 29 个真实 `.gil` 的 field 27 全是 0 字节**。⇒ 本机这些关卡**没有 placements**，
那两条守恒检查因此是**恒真**的，不能拿来当「写过 placements」的证据。

### 6.5 `register_level.py:56-59` 的注释不精确
原文：「34 and 41 are constant 1 in every file seen, and 42 appears in the two oldest ones.」
**实测**：field 41 在**全 18 个 id** 出现（=1）；field **34 只在 4 个占位 id**（`1826/827/836/837`）出现；
field 42 在 **12 个 id** 出现。「34 … in every file」与实测不符，应改为「34 只在占位关卡」。

### 6.6 记忆 `gil-level-file-is-decodable` 的一处旧猜
记忆把 field 4 记作「小（1195 字节），`level_id` 之类」。字节显示 field 4 是**元件/控件定义表**
（子 `2×field1`，串含 `GI_MoveHead/…`），**不是 level_id**。建议下次维护记忆时更正。

### 6.7 `gil_container.py:57-58` 的「field 40 all in September 2026」**已过时**
原文按最初 4 文件写「values … all land in September 2026」。**实测**：field 40 覆盖
**2026-09-02 … 2026-10-07**（`1073741842` = `1791417068` = 2026-10-07），因为后来新增的关卡
（`1835`–`1842`）是 9 月末/10 月初存的。**这不影响 field 40 的身份**（仍是「时间戳」），但
「all in September」这句当作证据会误导。建议改为「落在文件 mtime 同期的 2026-09/10」。

### 6.8 `CLAUDE.md:17` 的「field 5/6/46＝实体几何相关」不准确
`CLAUDE.md` §一表把逆向存档容器挖到的字段概括为「field 2 名称、field 39 创建者、**field 7＝地形、
field 5/6/46＝实体几何相关**」。但本仓自己的负结论是：
- field **5** = 实体表（对）；
- field **6** = 页签/目录树，**不是**实体几何（`entity_geometry.py:92-97`）；
- field **46** = 存档历史头，**也不是**实体几何（`entity_geometry.py:98-99`、`save_delta_attribution.py:31-36`）。

建议改为「field 5＝实体表；field 6＝目录；field 46＝存档历史头（均非几何，唯 field 5 含几何）」。

---

## 7. 复现命令（全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


本轮实跑：**`1 failed, 90 passed, 186 subtests passed`**。
**已知仓内非本任务失败（记录，不修）**：`test_gil_container.py::test_profile_lists_every_level_file_present`
（断言在 `test_gil_container.py:259`）当前 FAIL——`fixtures` 用**非递归** `LEVEL_DIR.glob("*.gil")`
收集，而 8 个关卡已改存到同名子目录（`.../1073741835/1073741835.gil`），于是 profile 列出的 id
比 fixtures 多 8 个（首个多出 `1073741835`）。`GEOMETRY-THREE-WAYS.md:304-307` 已记录同一失败。

---

## 8. 一句话

`.gil` 顶层**已观测 47 个字段号**（`1..12,14..23,25,27,29..46,48,49,50,52,53`），其中
**10 个实证**（`1,2,5,6,7,10,11,29,39,40`）、**约 14 个有来源点名但仅推断**、
**约 23 个无人命名**（§3/§4 的边界含「似乎…」级猜测，故后两者为约数）。**最大的洞是 field 15**（类型化资产表：本机唯一「编辑器资产落盘」证据，
但零读零写代码）。三条**必须写进引用口径**的冲突：field 7（地形/预设点/出生点）、field 9
（UI 层级 vs 兄弟关卡表）、field 27（本机恒空）。**本文件不是「schema」**——它是一个**只读、
可复现、每个号都带 `file:line` 或字节证据**的台账；**「未知」是成果，不是待办。**
