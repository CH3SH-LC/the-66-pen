> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 游戏侧能不能建模板 —— 游戏进程（`YuanShen.exe`）这条路（GAME-SIDE-TEMPLATE）

日期：2026-10-10。**全程只读**：未连桥、未发任何 bridge/native 报文、未注入、未启动/触碰游戏或编辑器、
未起 helper、未申请 UAC；对 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` **一个字节都没读也没写**；
未读任何图片或 PDF 页。本文件只在 `docs/research/reverse-eng-20261010/` 内写这一个文件；
本次检索脚本落在 `.runtime/scratch/`。

**本文件回答一个问题**（承接 `TEMPLATE-CREATE-TRACE.md` §6 与 `TEMPLATE-STORAGE.md`，不重复其推导）：
`TEMPLATE-CREATE-TRACE.md` §6 把「建模板」的可能落点排成 6 条，最后只剩两条未否：
候选 **(4) 面板存在但位于从未被逆向的编辑器前端 UI**，与候选 **(5)/(6) 由「另一个二进制」处理**
（候选 5 = 编辑器只是转发；候选 6 = 只能由「游戏内建编辑器」创建）。本轮**只看 (5)/(6)**：

> **游戏进程 `YuanShen.exe` 知不知道编辑器侧的货币/道具/背包/商店模板？如果知道，它是不是一条独立于编辑器前端的建模板路线？**

**数据来源（全部静态/离线只读）**
- 原生通道源码：`tools/game-executor/native/*.h|*.cpp`（34 文件）与 `tools/game-executor/profiles/*.json`（逐文件读）。
- 游戏进程元数据解码器：`.runtime/verification/realtime-injection-20260921/backend-reachability/metadata_slice.py`
  与 `.runtime/game-executor/host-route-20260921/method-identifiers/decoder/method_names.py`（**它们本来读的就是 `YuanShen.exe`**）。
- 游戏侧历史回执：`.runtime/game-executor/**`（Bash 逐文件 grep + 逐行 SELECT 式读 json）。
- 官方章节原文：`docs/official-docs/chapters/{mhsd6lrx3voe,mh2cr30yeak0,mhbgx0rspbqu,mhi9s7isvp50,mhogfq9bf86q,mhn4bsi5lb58}.json`。
- 承接：`NATIVE-MEMORY-MAP.md`、`TEMPLATE-STORAGE.md`、`SAVE-WRITER-FINAL.md`、
  `docs/research/beyondeditor-backend/00-总览.md`。

---

## 0. 一句话判决

**「另一个二进制」这个前提本身被否——编辑器后端就是游戏进程 `YuanShen.exe`，不存在「另一处落点」。**
`docs/research/beyondeditor-backend/00-总览.md:16-17` 逐字：「本轮的对象：**『后端』= 游戏进程内、接住这些接口的那一侧**。
具体落点：`C:\Games\Genshin Impact Game\YuanShen.exe`」；前端是独立 WPF 程序 `BeyondAssistEditor`（`00-总览.md:12`）。

⇒ 因此候选 (5)/(6) 与候选 (4) **不是两扇门**，是**同一扇门的两侧**：前端 UI 发命令（FNV-1a 哈希命令名），
后端（游戏进程）执行。**「游戏进程可能另有一条建模板路」= CLOSED**（没有另一处二进制）。

**但这一否定的副产品是正面的**：正因为游戏进程**就是**后端，它的 IL2CPP 元数据里
**已经带着编辑器侧的模板数据模型**——`ClientBeyond{Currency,Shop,StuffBag,EquipStuff*}ConfigTemplateEditData`
一族类型名，本工程**已有解码器、已枚举过、回执已落盘**，只是从未写进 `docs/`。
⇒ **「游戏语料含模板数据模型」= CONFIRMED**（§2）。

| 子命题 | 判定 | 关键证据 |
|---|---|---|
| 游戏进程**知道**编辑器侧模板（数据模型在） | **CONFIRMED** | YuanShen 元数据含 `ClientBeyondCurrencyConfigTemplateEditData` 等（§2） |
| 游戏进程是**独立**于编辑器前端的建模板路 | **REFUTED** | 游戏进程**就是**编辑器后端（`beyondeditor-backend/00-总览.md:16-17`） |
| 游戏进程里**有可调用的建模板原语** | **REFUTED（未定位）** | 原生探针零覆盖（§1）；receiver 工厂自证 `gameCreateSaveVerified:false`（§2.3） |
| 「游戏侧语料能回答建模板吗」这条**研究路线** | **OPEN** | 类型模型已在盘上、解码器已在盘上（§2、§4） |

**下一步的正确动作**（corpus 侧，不是重搜）：把 §2 的 `ClientBeyond*ConfigTemplateEditData` 一族
与 §2.3 的类型分派函数 `0x911d280` 从 `.runtime/game-executor/` 的散落回执**提升为一份正式语料**，
再以「按类型名找构造者」的方式找创建端点——这条**不依赖**命令名字符串，因而绕开了候选 (4) 的堵点。

---

## 1. 原生通道今天在游戏进程里能碰到什么

原生通道 = **游戏进程 `YuanShen.exe`**（`NATIVE-MEMORY-MAP.md:10`；目标镜像
`C:\Games\Genshin Impact Game\YuanShen.exe`，`native_profiles.py:17`）。当前构建指纹：
镜像 SHA-256 `7f89938da606…38e`、`SizeOfImage=453693440`（`profiles/genshin-cn-7.1.0-readonly.json:7,10`）。

**只读探针**（在游戏当前回调线程里只读走内存、产出定长 POD；`game_context_snapshot.h:107-112`）：

| # | 入口 | 读什么 | 源文件:行 |
|---|---|---|---|
| P1 | `CaptureGameContextSnapshot` | 全局根 → context/save manager → **context 字典**（当前 context + 原点）→ **entity 字典**（每实体 owner/id/context/**config/configId**） | `game_context_snapshot.h:78-99,111` |
| P2 | `CaptureGameLevelCatalog` | save→archive→**关卡目录字典**（全部关卡记录 id/key/record） | `game_level_catalog.h:49-50` |
| P3 | `CaptureGameLifecycleType` | class 槽 → 类型对象 → 函数槽表 | `game_lifecycle_type.h:29-30` |
| P4 | `CaptureGameSchedulerCoroutines` | scheduler 列表 → 每协程 handle 的 holder/iterator/state | `game_scheduler_coroutines.h:52-54` |
| P5 | `CaptureGameReopenGuardBundle` | 依次跑 P1–P4，再验 mode 字典 / XOR 表 / confirmation 类层级 | `game_reopen_guards.h:43` |

**动作**（非只读，白名单 `profiles/genshin-cn-7.1.0-reviewed-write.json:11`：`create / create-batch / save / creature-create`）：

| # | 入口 | 做什么 | 源文件:行 |
|---|---|---|---|
| A1 | `ExecuteGameSceneAction` | 校验身份/关卡/锚点/栈后调原生 **place / save / batch** | `game_scene_action.h:11-34`；`game_scene_action.cpp:134-307` |
| A2 | `ExecuteGameReopenAction` | 单次调重开入口 | `reopen_action.h:33`（专用构建，`reopen_action.h:5-9`） |

**能碰到的对象域**＝ **关卡目录 / context（关卡实例）/ 实体字典 / save manager / lifecycle 类槽 /
scheduler 协程**。实体记录字段逐字为 `owner, config, context, dictionaryKey, id, configId, flags, position`
（`game_context_snapshot.h:79-85`；`position` 无已证偏移，`flags` 里 `GE_POSITION_READ` 恒不置位，同文件 `:82`）。

**碰不到的对象域**：**没有任何探针读「编辑数据 / 配置模板 / edit-data 接收者」这一层**——
§2 找到的模板类型与类型分派函数（`0x911d280`）**不在 P1–P5 或 A1–A2 的读/写范围内**。
原生通道里唯一的 `template` 是 `scene_calls.h` 的**摆放**参数：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


这个 `template_id` 是**实体摆放模板（元件/造物模板）**——即 `create` 时把哪个对象实例化进关卡
（`build_scene_profile.py:205` 注「`3xxxxxxx` 的造物模板需要不同取值」；`cleanup_owned_entities.py:125`
指出它落盘写作实体记录的 **`configId`**，实例值如 `20001200`）。**它是实体ID 命名空间，不是配置ID 命名空间**
（两套命名空间见 `mhsd6lrx3voe.json` 的两张类型表，§3）。所以「原生通道有 template」**不等于**「原生通道能建货币/道具/商店模板」。

---

## 2. 游戏进程的元数据里，**有**编辑器侧模板

### 2.1 先把「这是不是游戏进程」钉死

`.runtime/verification/realtime-injection-20260921/backend-reachability/metadata_slice.py:10`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


同文件 `:15` 读 `D:/games/Genshin Impact Game/YuanShen_Data/Managed/Metadata/global-metadata.dat`，
`:16-17` 断言其 SHA-256 必须等于 `18ef2e60496c8be31d3bf64b65ef3fdeb67bd894b10c1793fde8432afdc554a5`，否则 fail closed。
解码器由 `.runtime/game-executor/host-route-20260921/method-identifiers/decoder/method_names.py:9-12` 加载。
⇒ **这一族名字出自 `YuanShen.exe` 自己的 IL2CPP 元数据**（86,932 个定义 / 713,956 个方法，
`named-editor-entry/method-search.json:4-5`），不是编辑器托管程序集。

### 2.2 模板数据模型（逐条含 slot 与引用地址）

Bash 逐文件扫 `.runtime/game-executor/**` 的 json，命中以下**类型名字符串字面量**（全部绑定同一
`metadataSha256=18ef2e60…`）：

| 类型名（UTF-8 字面量） | 落到官方配置ID 类型（§3 表） | 出处 |
|---|---|---|
| `ClientBeyondCurrencyConfigTemplateEditData` | **货币 = 10** | `.runtime/game-executor/resume-20260921-2245/nested-notification/shared-assignment/verified-assignment.json:5015`（slot `0x57f1290`，引用点 `0x911e5d0`） |
| `ClientBeyondShopConfigTemplateEditData` | **商店模板 = 15** | `…/verified-assignment.json:5295`（slot `0x57f0f40`，引用点 `0x911ed38`）；`.runtime/game-executor/receiver-factory-20260922/usage.json:5018` |
| `ClientBeyondStuffBagConfigTemplateEditData` | **道具背包 = 11** | `.runtime/game-executor/receiver-factory-20260922/usage.json:5006`（slot `0x57f0f38`） |
| `ClientBeyondEntityShopCompEditData` | 商店**组件**（挂到实体） | `.runtime/game-executor/receiver-factory-20260922/usage.json:4538` |

同一 `usage.json` / `verified-assignment.json` 里**整族**还有（Bash 去重：`ClientBeyond*` 共 **172** 个不同名，其中 **8** 个以 `ConfigTemplateEditData` 结尾）：
`ClientBeyondEquipStuffBagConfigTemplateEditData`（装备背包）、`ClientBeyondEquipStuffAffixConfigTemplateEditData`（装备词缀 = 14）、
`ClientBeyondEquipStuffTagConfigTemplateEditData`（装备标签 = 13）、`ClientBeyondEquipStuffTypeConfigTemplateEditData`（装备类型 = 12）、
`ClientBeyondShieldConfigTemplateEditData`（护盾 = 20）、`ClientBeyondScanEntitySubTagTemplateEditData`、
以及 `ClientBeyondEntity*CompEditData`（组件族）与 `ClientBeyondLevelConfig*Data`（关卡配置族）。
**这一族与官方配置ID 类型表（§3）近乎一一对应**——它们是**模板的编辑/序列化模型**。

### 2.3 游戏侧**按编辑数据类型分派**一段代码（含「无创建桥」自证）

- 函数 **`0x911d280`**（7549 B）：入参取「数据类型字符串」，**按 UTF-16 算 FNV 后分派**，命中后比指针或长度/串相等，
  再**按类型选/建一个“接收者”对象**，其默认 slot11（`+128`）方法名**统一为 `OnBeyondNotify`**，共 **29 个不同本体**
  （`.runtime/game-executor/resume-20260921-2245/nested-notification/shared-assignment/README.md` §「已闭合实际写入」与 §「默认+128槽」）。
  即：**货币/商店/背包模板确实是游戏进程按类型认识的编辑数据**。
- `receiver-factory-20260922`（7 个函数、34,027 B 已逐字节核对，`root-verified.json`）自证：
  `result.json:2` → `"Not a working create/save bridge"`；`root-verified.json` → `"semanticConclusion":
  "Known talk branch builds property-inspector objects and forwards notifications; not a proven create/save bridge"`，
  `"gameCreateSaveVerified": false`。
  ⇒ **找到了「游戏进程按类型认识模板」的证据，但没找到「游戏进程造模板」的证据。**
- 元数据里另有编辑器命令接口与 UGC 商店/货币 UI 名（`named-editor-entry/method-search.json`，行号见括号）：
  `MoleMole.IBeyondEditCommandExecuteable.{TryExecuteBeyondCommand,BeforeOpenPanel,get_panelData,get_panelType,get_jsonConfigKey}`
  （:7979–:8051）、`SetupUGCInGameShopGoods`（:6566）、`AddBeyondDataConfigHeader`、
  `UpdateUGCItem`、`GetUGCCurrencyTipsDialog`。**名字层在**——但**业务方法名 405,928/713,956 是 11 位 A–P 混淆**
  （`method-search.json:8-9`），所以**没有**任何叫 `Create*Template` 的明文方法名可抓。

### 2.4 这与「模板落在关卡 `field 15`」自洽

`TEMPLATE-STORAGE.md §0.2`：模板落盘在**关卡 `.gil` 的 `root field 15`**（带 id + 名字 + 组件块的类型化资产表），
本机真实装着一条 **type 11 背包模板**（`id=1119879169`、`name="背包模板"`，`1073741831.gil` 偏移 `37 736`）。
`SAVE-WRITER-FINAL.md §0.1-2`：写这份 `.gil` 的是**引擎/写入方自己的内存**，不是本工程 Python。
两条合起来 ⇒ **模板记录在保存时存在于游戏进程（后端）的内存模型里**——这正是 §2.2/§2.3 那些
`ClientBeyond*ConfigTemplateEditData` 类型在保存路径上被分派的原因。**游戏进程持有模板数据；但「持有」不是「创建」。**

---

## 3. 官方设计：模板是**编辑期**概念，运行期只「引用并实例化」

取自官方章节原文（全部逐字）：

**3.1 配置ID 类型表 —— 模板属于「配置ID」这套命名空间**
`docs/official-docs/chapters/mhsd6lrx3voe.json`（`facts[].kind=="type-taxonomy"`）：三列表头「配置ID / 对应类型 / 十进制ID可修改的范围」，
其中 `8 = 普通道具、装备道具`、`10 = 资源货币`、`11 = 道具背包`、`12/13/14 = 装备类型/标签/词缀`、`15 = 商店模板`、`20 = 护盾`……
同章 `kind=="definition"` 逐字：**「ID修改系统给奇匠提供了在编辑过程中，可以动态修改和重新分配ID的功能，
适用于实体GUID、元件ID、配置ID等所有包含ID引用的内容」**——**限定词「在编辑过程中」**，即这一整层是**编辑期能力**。
同章另有独立的「实体ID」表（`1 = 物件(含元件)`、`2 = 造物`、`5 = 关卡`）——**与配置ID 是两套命名空间**，
这正解释 §1 的 `template_id`（实体摆放模板）与货币/商店模板**不是同一个东西**。

**3.2 创建动作是编辑器里的按钮 + 弹窗**
- 货币 `mh2cr30yeak0`：「进入货币页签，进行货币的详细编辑」；「货币名称：由创作者(奇匠)定义的货币的命名」；「配置ID：货币数据的唯一标识」。
- 道具 `mhbgx0rspbqu`：「**点击新建道具按钮，在弹窗内选择确认创建即可新建一个道具模板**」；「配置ID：道具模板的唯一标识，**可在节点图中使用**」。
- 商店 `mhi9s7isvp50`：「**打开系统菜单**，在下图位置点击【商店模板管理】即可打开商店模板编辑界面」；「点击“新建商店模板”即可添加并编辑模板」；「**商店名称：创作者(奇匠)编辑时定义的商店名称，运行时无意义**」。
- 背包 `mhogfq9bf86q`：「**打开系统菜单**，通过点击【货币与背包】按钮进入编辑界面」「进入背包页签，进行背包模板的详细编辑」。
- 入口清单章 `mhn4bsi5lb58`（整体界面）逐字列系统菜单 29 项管理工具，含【商店模板管理】【货币与背包】。

**3.3 运行期只「引用并实例化」，不创建**
- 商店 `mhi9s7isvp50`：「四、商店的运行时实例 / **在游戏运行时，商店模板被商店组件引用并实例化**」；「自定义列表……其作为一个数据模板存在」。
- 背包 `mhogfq9bf86q`：「在实际游玩时，**背包模板定义由背包组件进行引用并实例化**」。
- 道具 `mhbgx0rspbqu`：「配置ID：道具模板的唯一标识，**可在节点图中使用**」。

⇒ **设计判决**：模板 = **编辑期**由奇匠在编辑器 UI（系统菜单 → 货币与背包 / 商店模板管理）**定义**，
序列化进关卡（`field 15`）；**运行期**由组件/节点图**引用并实例化**。
「商店名称……**运行时无意义**」是最硬的一句：模板是编辑期作者数据，运行期只消费。
**所以游戏侧（运行期那一侧）在语义上不持有「创建」这个动作**——它只持有「引用/实例化」。

---

## 4. 可行性核验与判决

`TEMPLATE-CREATE-TRACE.md` §6 的两个未决候选，本轮结论：

| # | 候选 | 本轮证据 | 判定 |
|---|---|---|---|
| 5 | 创建命令**由游戏侧处理，编辑器只转发** | 游戏进程**就是**后端（`beyondeditor-backend/00-总览.md:16-17`）⇒ 描述成立但**不构成第二条路** | **REFUTED 为独立路线**（不是另一个二进制） |
| 6 | 模板只能由「另一个二进制/游戏内建编辑器」创建 | **不存在**另一个接活的二进制；后端即 `YuanShen.exe` | **REFUTED** |

**同时得到一条正面结论**：游戏进程的元数据**确实**带着模板数据模型（§2.2）与按类型分派（§2.3），
**这是候选 (4)「编辑器前端 UI 未被逆向」之外、语料层唯一可继续推的把手**。

**可行性（明确写下能不能做）**：
- **运行时（native 探针）**：**不能**。P1–P5/A1–A2 的对象域是 关卡/context/实体/save/lifecycle/scheduler；
  §2 的编辑数据/接收者层**零覆盖**，也没有 schema。**故不应在「注入游戏内存建模板」上花力气。**
- **静态（元数据解码）**：**能（离线、无风险）**。解码器与回执已在盘上，类型名与类型分派函数已定址；
  可继续做的是「以类型名找构造者/写者」，**不依赖命令名哈希**，因而对候选 (4) 的堵点是**旁路**而非重复。
- **写盘（`field 15`）**：仍卡 `TEMPLATE-STORAGE.md §4.2`（无 type 8/10/15 实例、无 schema、`write_bytes` 无调用方）——
  与游戏侧无关，不因本轮而解。

---

## 5. 三层分开（不得混称）

| 层 | 结论 |
|---|---|
| **文档写了什么** | 模板是编辑期资产：AI 无；官方逐字有「奇匠在编辑过程中」定义配置ID、系统菜单 →【货币与背包】/【商店模板管理】、「新建道具按钮……弹窗内创建」（`mhsd6lrx3voe`/`mh2cr30yeak0`/`mhbgx0rspbqu`/`mhi9s7isvp50`/`mhogfq9bf86q`）。运行期只「引用并实例化」。**零执行。** |
| **工具/源码能做什么** | **静态**：YuanShen 元数据解码器可读出 `ClientBeyond*ConfigTemplateEditData` 一族与其类型分派函数 `0x911d280`（§2）。**运行时**：原生探针**零覆盖**模板层。**写盘**：无 `field 15` 写调用方（`TEMPLATE-STORAGE.md §4.2`）。 |
| **真机验证过什么** | **本轮零真机**（未起 helper、未连桥、未发报文、未碰游戏/编辑器、未读写存档）。§2 的证据是**磁盘元数据 + 历史只读回执**，级别 `static`；「这些类型就是货币/商店/背包模板」是由类型名与官方类型表（§3.1）**逐条对齐**得到的**推断**。 |

---

## 6. 诚实负结论（写明搜了哪里）

| 未找到 / 未证 | 搜过哪里 / 工具 |
|---|---|
| 游戏进程里任何**建模板**的明文方法名 | `.runtime/game-executor/host-route-20260921/named-editor-entry/method-search.json`（1318 宽松命中，模板/配置类过滤后 22 条，**无 `Create*Template`**）；业务名 405,928/713,956 为 11 位混淆 |
| 游戏进程里任何**可调用的建模板原语** | `receiver-factory-20260922/result.json:2` 自证 `"Not a working create/save bridge"`；`root-verified.json` → `gameCreateSaveVerified:false` |
| 原生探针对**编辑数据/配置模板**层的读/写 | 34 个 `native/*.h|*.cpp` 全读；对象域只有 关卡/context/实体/save/lifecycle/scheduler（§1） |
| 游戏侧**建模板命令名**（用于 FNV 哈希落点） | 无法从本批产物得到——需要候选 (4) 的前端面板命名空间（`TEMPLATE-CREATE-TRACE.md §8` 同结论） |
| 游戏进程**独有**的第二处落点 | 不存在：后端即 `YuanShen.exe`（`beyondeditor-backend/00-总览.md:16-17`） |

**未找到 ≠ 不存在**：以上「没有」均为**本次检索范围内**。**已知的最大缺口**是「谁构造/写入
`ClientBeyond*ConfigTemplateEditData`」——本轮的 `0x911d280` 是**接收者分派**（`OnBeyondNotify`），
**不是**已证的构造者；构造者/写者**未展开**。

---

## 7. 复现命令（全部只读；未在 `docs/` 外写任何东西）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 8. 边界与未做

- 未启动/停止/触碰游戏或编辑器；未发任何 bridge/native/UAC 请求；未起 helper；未注入。
- 未读 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` 的任何字节；未读图片/PDF。
- §2 的元数据结论是**静态**级（磁盘 `global-metadata.dat` + 历史只读回执）。**构建一致性未在本轮复验**：
  回执的 `metadataSha256=18ef2e60…` 属 2026-09-21/22 那批（`beyondeditor-backend/00-总览.md` 记当时
  `YuanShen.exe` 431,085,976 B），而当前原生 profile 记 `445,006,744 B`（`profiles/genshin-cn-7.1.0-readonly.json:8`）——
  **把任何 RVA/slot 当“现行”使用前，必须用当前构建重跑 metadata 解码器**（`method_names.py` 会 fail closed）。
- **不做的事**：不在本文件里把「找到类型模型」写成「能建模板」；不把 `receiver-factory` 的
  `OnBeyondNotify` 分派当成创建端点；不动 helper、不碰任何存档。
