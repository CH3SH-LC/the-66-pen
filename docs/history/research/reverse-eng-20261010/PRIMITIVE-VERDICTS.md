> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# PRIMITIVE-VERDICTS — 每个被挡原语一张判决表

> 建立日期：2026-10-10。**本文件只做一件事**：把散在 `docs/research/reverse-eng-20261010/` 几十份报告里的
> 「某个原语到底能不能用」汇成**一张表**——一行一个原语，给出 **判决（有 / 无 / 未知）＋证据（file:line 或 grep 计数）＋下一步动作**。
>
> **口径（`CLAUDE.md` §一.2/§一.3）**：
> - **三层分开**：`文档写了什么` / `工具能做什么` / `真机验证过什么`。本表每行的「有」区分**已真机**与**仅离线/已编译未真机**。
> - **「搜不到」≠「不存在」**：凡 0 命中均写明检索范围；归不进「有/无」的进 §2 UNKNOWN 表。
> - **负结论也是成果**（`CLAUDE.md` §一.4）：`无` 不是「还没做」，是**已证做不到**（或本仓检索范围内的精确缺席）。
> - **本文件不新增事实主张**——每一行的证据都取自被引用报告本身，报告各自已给出 file:line / grep 计数。引用行号＝各证据报告里的本次 checkout 实测值。
>
> **本文件不连桥、不发报文、不触碰游戏/编辑器、不写任何存档；只读整理。**

---

## 0. 一页速查（判决汇总）

| # | 原语 | 判决 | 一句话 |
|---:|---|---|---|
| 1 | entity create（建实体） | **有**（真机） | 按坐标建单实体/批量，建时自带位姿缩放 |
| 2 | entity delete（删实体） | **有**（编辑态物化）/ **无**（运行期生成物） | 只删「编辑器前端资源树里唯一物化的」实体 |
| 3 | entity transform（改已有实体位姿） | **无** | 前端命令面没有 transform 命令（CONFIRMED） |
| 4 | component read（读组件） | **有**（已编译进 R269；**未真机**） | `inspect-entity-components` 在 DLL 里，差真机一次 |
| 5 | component add（加组件） | **无** | `Add*Component*` 四处检索全 0 命中（⚠️ 口径 2026-10-11：四处**非独立层**——同取一份 build 的不同抽取视图；独立轴＝两代构建 7.0/7.1） |
| 6 | component delete（删组件） | **无**（当前无可用 op） | 已编译+接线（R271），但读半 `ComponentIds` 未绑定 ⇒ fail-closed（`COMPONENT_MODEL_READER_UNBOUND`，`tools/editor-bridge/Adapter/EntityComponentDelete.cs:195`） |
| 7 | template create（建货币/道具/背包/商店模板） | **无** | 38 条路由无一条建模板；落点候选 `field 15` |
| 8 | dict constant write（写字典常量，type 27） | **无**（常量）／有（图内构造+连线，另路） | 常量无形状可写；1088/1788 可图内构造 |
| 9 | graph create（建图） | **有**（真机） | |
| 10 | graph add-node（加节点） | **有**（真机） | 加节点规则通用，非白名单 |
| 11 | graph wire（连线） | **有**（真机，运行时语义未证） | |
| 12 | graph bind（挂图到实体） | **有**（真机，读回确认） | 挂上 ≠ 会跑（缺组件） |
| 13 | graph export（导出 .gia） | **有**（节点表）/ **未知**（边） | 边：未找到，非「不存在」 |
| 14 | graph delete（删图） | **无** | 谓词引用相等恒 false，`modelMatched=0` |
| 15 | native save（原生保存） | **有**（真机） | `.gil` 字节差分确认 |
| 16 | level create（建关卡） | **无**（命令面不可达；文件面被版本门关闭） | fail-closed，非引擎限制 |
| 17 | level bounds read（关卡边界读） | **未知** | 见 §2 |
| 18 | terrain read（读地形） | **有**（真机，只读） | `field 7` 已解，可逐字节复核 |
| 19 | terrain persist-write（持久化写回地形） | **无** | `terrain.py` 无落盘 API；写回被写入方覆盖 |
| 20 | graph variables write（写节点图变量） | **未知** | 工具层＝不能；引擎装配层＝有原语 |
| 21 | UI control write（写 UI 控件/属性） | **无** | 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 ui/property 0 命中 |
| 22 | playtest control（起停试玩） | **无**（bridge 面）／**未知**（候选原语） | 无 op；候选＝菜单 Delegate 通路 |
| 23 | graph logging（图日志取证） | **未知**（按原样不能翻 `runtimeVerified`） | 记录自带 proto58 graphId，桥没读 |

> 一句话总览：**能真做的＝「节点图这一半 + 按坐标 create + 原生 save」；模板/组件加/UI/地形写/变换/建关卡
> 这一半没有写入原语**（`CLAUDE.md` §五/§六）。
>
> **op 计数口径**：本表的「桥 op」＝`BridgeServer.cs` 的 `case` 标签数——**现值与历史值见 tools/gameplan/tests/test_doctrine.py**（该文件对着 `BridgeServer.cs` 钉住；2026-10-10 新增 `inspect-entity-components`）；`ValidateSet` 与 `case` 标签口径一致。
> **无论具体数值，ui/property/item/shop/currency/terrain 一族全部 0 命中**，不影响任何判决。

---

## 1. 主表 — 每个原语一行

> 「证据」列优先给**底层 file:line / grep 计数**，并在方括号里给**转引来源报告**（该报告已复核过该证据）。
> 「判决」列用 **有 / 无 / 未知** 三档，`有` 后括注是否真机。

| 原语 | 判决 | 证据（file:line / grep 计数） | 下一步动作（ONE） |
|---|---|---|---|
| **entity create**（建实体，单/批量） | **有**（真机） | `tools/game-executor/scene_cli.py:613`、`tools/authoring/author.py:562`；原生 `native/game_scene_action.cpp:184`（`HR_ACTION==1`）、`scene_calls.cpp:34-50`（`place_builtin`）；建时收 `position/rotation/scale`（`scene_cli.py:258-266`）；真机 `actionStatus 0 / called 1 / entityId 1077936129`（`PROGRESS.md:11`）【`MINED-INTERFACES.md:90`、`CLAUDE.md:138-142`】 | 无。**布局在建那一刻一次给全**（transform 事后改不了，见 #3）。 |
| **entity delete**（删实体） | **有**（编辑态物化实体）／**无**（运行期生成物） | 三条路径：crud-probe 门 `Adapter/EntityCrudProbe.cs:106-108`（相对基线恰 1 个新实体 + `EntityType==1402 && InstanceKind==0`），入口 `:217-239`；裸 id 路径 `Adapter/OwnedEntityDelete.cs:8-27,87-150`（「边界只有 ID 列表」）；op 接线 `ManagedBridge/BridgeServer.cs:344-345,462,494`。**运行期生成物不可寻址**（`ENTITY-LIFECYCLE-MINE.md:186-220`：图运行期建的方块/元件型 252/757/256/布设组 178 无前端资源节点）【`ENTITY-LIFECYCLE-MINE.md:109-146,200-220`】 | 清运行时生成物：**从源头断生成图的执行边**（`RetireRuntimeSpawns.cs:26-84`），不是「建完再删」。 |
| **entity transform**（改**已有**实体位置/朝向/缩放） | **无** | 前端 38 条 `command_route` 无一条 position/rotation/scale/transform（`COMMAND-ROUTE-MAP.md:162-184`，CONFIRMED；`Modify*` 家族只有 Name/Tag/Faction/Suite）；桥写半是具名 blocker `Adapter/EntityTransform.cs:36,139-144` 抛 `TRANSFORM_NATIVE_SETTER_UNKNOWN`；`tools/gameplan/placement.py:9-14`「entity.transform is entirely missing」【`CLAUDE.md:132-142`】 | 不挖 setter：**把布局挪到 create 时定**（或在原生侧逆向新 setter，见 `NATIVE-ACTION-SET-MINE.md` §6）。 |
| **component read**（读实体上的组件） | **有**（已编译进 R269；**未真机**） | op `inspect-entity-components`：`Adapter/EntityComponentProbe.cs:124`、回执形状 `:150-156`（`{id,enabled,x,y}`）、只读标记 `:161-173`；桥派发 `ManagedBridge/BridgeServer.cs:306`；R269 DLL 字符串堆含该 op（probe UTF-16=1）【`COMPONENT-READ-VALUE.md:16-17`、`COMPONENT-OP-PROOF-PLAN.md:19-28`】 | 跑一次真机读（路线 A：`call-bridge.ps1 -Operation inspect-entity-components -EntityId <id>`），把 `componentIdSpace` 从 `UNVERIFIED` 落定。 |
| **component add**（给实体加组件） | **无** | `AddComponent`/`CreateComponent`/`AttachComponent`/`InsertComponent` 在**四处检索范围全 0 命中**：`.runtime/editor-catalog/resolved/` **12375** 个反编译 `.cs`、`string-table.json`、`frontend.db→operation`（**44** 行）、`backend.db→command_route`（**38** 行）；命令面组件只有两个**删**（`DeleteComponentForEditObj`/`DeleteComponentForPrefab`）【`CLAUDE.md:104-118`（§六 a）、`COMPONENT-WRITER-MINE.md` §0/§2.3/§5、`COLLISION-TRIGGER-MINE.md` §2.4】。**⚠️ 口径（2026-10-11）：这四处不是互相独立的层**——同取一份 legacy build 的不同抽取视图（活程序集亦≡7.1 build），是重复观测；本负面**真正的独立轴只有两代构建（7.0 / 7.1）各自为负**，7.1 串表检索带正面控制（`DeleteComponentForEditObj` / `AddInstructionGraphForEditObj` 均在 7.1 注解串里查得到） | 不找 `AddComponent`；做 M1 触发活走**图能表达的那一半**，并用只读探针把 `componentId` 编号坐实。 |
| **component delete**（删实体上的组件） | **无**（当前无可用 op） | 适配器 `Adapter/EntityComponentDelete.cs` **已进 csproj `<Compile>`、`BridgeServer.cs:324` 有 `delete-entity-component` case、`call-bridge.ps1` `ValidateSet` 有该 op**（R271）；**但当前在 `ComponentIds` 处因符号未绑定而 fail-closed**（读半两符号 `JdaiSnpkbfl`/`b1EiCj8P44N` 在 `Generated.cs` 中 =0 ⇒ `COMPONENT_MODEL_READER_UNBOUND`），**一次原生请求都发不出**；底层命令 `DeleteComponentForEditObj` 在 `resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107`、`backend.db command_route` id4 存在【`COMPONENT-OP-PROOF-PLAN.md:19-28,95-114`、`CLAUDE.md:107-111`】 | 补读半绑定（W6，解除 `COMPONENT_MODEL_READER_UNBOUND`）后再谈真机（删是写，还要新基线+新复核+`.gil` 差分）。 |
| **template create**（建货币 type10 / 道具 type8 / 背包 type11 / 商店 type15 模板） | **无** | `command_route` **38 行逐行**无线模板命令（全为 `*EditObj*/*Prefab*/Focus*/DoExport|Import/*DebugLog/PCG`）；`.gip` profile 顶层只有 `field 1/2/3`，「货币/道具/商店/背包」四词 1161 B 里 0 命中；桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）（`BridgeServer.cs:255`）+ 原生 **6** 动作（`elevated-request.py:280`）+ `scene_cli` 6 动作无一项建模板【`TEMPLATE-CREATION-MINE.md:16-36,39-59,157-171`】 | 一次「非黑即白」实验：人在 UI 建 1 个货币模板 → `save` → 重扫该关 `root field 15`（候选落点）。 |
| **dict constant write**（把字典写成 type-27 pin 常量） | **无** | `paramtypes.SLOT_FOR_TYPE[27]=None`；`AuthorWriteScalar` 无 dict 分支（`AuthoringGraph.cs:901-971`）⇒ 抛 `AUTHOR_VALUE_SLOT_UNPROVEN`/`UNSUPPORTED`；binding profile **313** 条合同里无任何 setter 接受字典（全是 `Field`）【`DICT-WRITE-PROBE.md:9-36,86-121`、`DICT-WIRE-FORMAT.md`】 | **另路**：图内构造（1088 建立字典 / 1788 拼装字典，输出 Generic）再连线喂 type-27 pin —— 需一次 `build-plan`+`inspect` 证实 generic→concrete 物化（`DICT-WRITE-PROBE.md:204-226`）。 |
| **graph create**（建空图） | **有**（真机） | `Adapter/AuthoringGraph.cs:222`（action 表 `:96`）、CLI `author.py:57`；真机 `graph create → ok create-requested-readback-pending`（`PROGRESS.md:41`）【`MINED-INTERFACES.md:54`】 | 无。 |
| **graph add-node**（加节点） | **有**（真机） | `AuthoringGraph.cs:320`（形状校验 `:120-134`）；解析规则通用（`Kind==6 && r.Id==definitionId && category`，`:322`）；真机 `688`/`691` 加进图并读回（`VERIFICATION-R262.json`）【`MINED-INTERFACES.md:58`、`UI-CONTROL-WRITE-MINE.md:131-138`】 | 无。 |
| **graph wire**（连线） | **有**（真机；运行时语义未证） | `AuthoringGraph.cs:393-448`（`Link`）；真机 `graph wire → link-accepted`（`PROGRESS.md:2991`）、R267 一次建 17 条边（`PROGRESS.md:48`）【`MINED-INTERFACES.md:63`】 | 运行时语义需一次真机试玩（`runtimeVerified` 全仓恒 false）。 |
| **graph bind**（把图挂到实体） | **有**（真机，读回确认） | `AuthoringGraph.cs:298-318`（委托 `AddInstructionGraphForEditObj`，`:317`）；绑定记录只含指向 graphId 的引用（`EditorAdapter.cs:216-220,176-179`）；真机独立读回 `boundEntityIds=[1077936129]`（`PROGRESS.md:13,243`）【`GRAPH-ATTACH-CHAIN.md:36-58`、`MINED-INTERFACES.md:65`】 | 无（挂载链本身通）；「会跑」另需组件（#5）。 |
| **graph export**（导出 `.gia`） | **有**（框架+节点表）／**未知**（边） | `AuthoringGraph.cs:260`（`ExportResource`）；真机 R169 `exportVerified:true`、GIA sha（`PROGRESS.md:489`）；`.gia` 框架＝`.gil` 容器 subtype 3，节点表可走行（含 definitionId）；**边未找到**（精确负证据：67 文件、2859 引脚无一条承载节点索引）【`GIA-EXPORT-MINE.md:19-28,128-168,172-213`】 | 一次差分实验：同图 wire 恰好一条边，导出两版做字节差（`GIA-EXPORT-MINE.md:215-227`）。 |
| **graph delete**（删整张图） | **无** | 谓词＝引用相等（`Adapter/OwnedGraphDelete.cs:103-105` 建表、`:174` 判归属），两端不在同一对象图，恒 false ⇒ `modelMatched=0`（四次实测）；图模型/管理器无删除契约（`EditorBindingProfile.Generated.cs:628,941` 只有删节点；`:798,880,932` 无移除），且 `FinishGraph.cs:214-215` 实测注册表 Kind-9 对象**不带** delete 方法【`GRAPH-DELETE-FIX.md:14-30,175-231`、`GRAPH-DELETE-PROBE.md`】 | 统一身份查找（走 `Resources()`+`Kind==9`）只修「身份半边」；删除半边须**继续逆向一个图的移除原语**。 |
| **native save**（原生保存落盘） | **有**（真机） | `scene_cli.py:587`；原生 `native/game_scene_action.cpp:214-216`（`HR_ACTION==2`）、`scene_calls.cpp:56-60`（`save_current`）；真机 `.gil` **21872→28383 B**、sha `88ad2acf…→56feb97d…`、载荷含 entityId/graphId/templateId（`PROGRESS.md:14-15`）；写入方＝游戏进程 `YuanShen`（`write-attribution.log:8-10`）【`MINED-INTERFACES.md:92`、`SAVE-WRITE-ATTRIBUTION.md:203-209`】 | 无。注意：save 会把**所有未保存内容**一起落盘，且写入方**从内存重生成整文件**（文件级恢复无效）。 |
| **level create**（建关卡） | **无**（命令面不可达；文件面被策略门关闭） | 命令面四处零命中（⚠️ 口径 2026-10-11：四处**非独立层**——同取一份 legacy build；独立轴＝两代构建 7.0/7.1，见 `CLAUDE.md` §五）：`command_route` **38** 行无建关卡动词、`frontend.db→operation` **44** 行、`string-table.json` **2830** 字符串、`resolved/` **12375** 个 `.cs`（各 0）；文件面 `register_level.py`+`gil_container.py` 字节已懂但被 `version_guard.py:372-373` fail-closed 拒（`register_level.py:243/245/284`）【`LEVEL-CREATE-MINE.md:11-27,158-207,210-224`】 | 先做 0 风险 diff（候选形状 vs 新版目录形状）；决定性一步＝一次 `--apply` + 独立读回 + 用户重开。 |
| **level bounds read**（读关卡边界 / 地图范围） | **未知** | 44 份报告内**无报告**给出一条「关卡边界读」原语（见 §2）；最接近的候选：原生 `origin[3]`（`game_context_snapshot.h:95`，本机 334 份快照**恒 `[0,0,0]`**）、`field 11 关卡设置`（`level_settings.py:81`，含阵营/出生点/预设点，**非边界**）、`field 7` 400 格地形网（`terrain.py`，属 #18 地形读）【`GEOMETRY-THREE-WAYS.md:85-86`、`GIL-FIELD-LEDGER.md:83`】 | 检索范围扩大（含 `mvp/backend/plugins`）后再判；先确认「边界」指关卡原点/可放置包络还是地形网范围。 |
| **terrain read**（读地形，`.gil` field 7） | **有**（真机，只读） | `terrain.py:74-81`（`FIELD_TERRAIN_LIST=7`、地形 id/名/变换/400 格、格坐标 `(x<<16)|y`）、读半 `:280`/`:293`；真机三关 `field 7` 逐字节相同（3642 B，sha256[:16]=`1c9d2287d86fbd98`）＝默认地形【`MINED-INTERFACES.md:144`、`GIL-FIELD-LEDGER.md:173-181`、`TERRAIN-WRITE-RISK.md`】 | 只当**只读证据源**用。 |
| **terrain persist-write**（把改过的地形写回存档） | **无** | `terrain.py` 写半 `set_cell:468`/`add_terrain:486`/`apply_terrain_fields:551`/`to_level_bytes:575` **只吃内存对象、不吃路径**；对全文 `grep -nE "write_bytes|\\.write\\(|open\\("` = **0 命中**；且写入方 save 时**从内存重生成整文件**，文件级写回会被覆盖（同 field 6 被覆盖的前例）【`CLAUDE.md:120-130`、`TERRAIN-WRITE-RISK.md:159-196,264-266`】 | 作为独立路线**不值得**；要真生效只能让写入方自己写（编辑器节点/API）——而那条**已确证不存在**（桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 `terrain` 0 命中）。 |
| **graph variables write**（写「节点图变量」） | **未知** | 工具层＝**不能**：5 个变量访问器符号 `pSJKOe1FuCR/NQlKbxwmq6a/…` 在 `EditorBindingProfile.Generated.cs` 与全部 `tools/` 源码 **0 命中**，`EditorBindingProfile.cs:117` 未登记即抛 `UNREGISTERED_SYMBOL`；桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）无 graph-variable 写 op。引擎层＝**有原语**：建/插/删/改名方法在 `.runtime/editor-catalog/decomp/BeyondEditor/cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH.cs:2374/2402/2489`，≥4 个编辑器内调用方【`GRAPH-VARIABLES-VERDICT.md:9-27,106-109,207-232`】 | 一次**只读** `graph-variables` 探针（仿 `pin-slots`），照抄 getter 进 profile，读回变量列表是否与页签逐字相符——把「未知」推向「能/不能」。 |
| **UI control write**（写界面控件/面板/控件属性） | **无** | 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 ui/控件/组件/属性 **0 命中**（`BridgeServer.cs`）；`Adapter/PanelOpen.cs:36` 只能开 `{节点管理器,资源管理器}` 两个面板；`Adapter/FrontendCommands.cs:229-230` 自述只读；前端 38 命令无一条 UI 控件写；UI 家族四节点 316/383/384/521 只操纵**已存在资产**（入参＝`界面控件组索引` 整数）【`UI-CONTROL-WRITE-MINE.md:18-43,81-107,110-139`】 | 「玩家可见 + 零 UI 资产」的旁路＝`presentation` 家族（266 屏幕震动 / 835 改色 / 308 显隐…，CANDIDATE）——需一次 `build-plan`+`inspect` 及真机试玩。 |
| **playtest control**（后台起停试玩） | **无**（bridge 面）／**未知**（候选原语） | 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）**无 `start-playtest`**（`INTERFACE-INVENTORY.md:392`）；`enable-debug-logging`/`request-debug-logs` 硬写 `startsPlaytest=false`（`EditorAdapter.cs:501,526`）；官方面入口是「系统菜单→试玩」UI 按钮，校验以弹窗错误码呈现、**无运行后可读报告**；唯一候选＝`PanelOpen.cs:31-90` 的菜单 Delegate 通路（当前被白名单锁死）【`PLAYTEST-CONTROL-MINE.md:9-25,97-118,147-158`】 | 只读探针 P1：运行时枚举编辑器菜单项，看「试玩」在不在（含 `actionTarget`）；命中再谈 P2。 |
| **graph logging**（图日志：证明某图/某节点执行） | **未知**（按原样**不能**翻 `runtimeVerified`） | 5 个日志 op 形状对，但 41 份回执里 `runtimeVerified/playtestVerified/runtimeSemanticsVerified:true` **均 = 0**；根因不是死路：记录**自带** proto58 `{value,graphId}`（`resolved/HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD.cs:54,874-876`），桥**从不读**（Adapter `grep`=0），却把整条命押在「名字精确匹配」（`PositionLogs.cs:21`）；另有正文载体 proto8 `ulong` 也未读【`GRAPH-LOG-NEXT-STEP.md:14-23,54-88,166-215`、`GRAPH-RUNTIME-VERIFY-MINE.md`】 | 加宽 `RunLogSample.cs:38-79` 的 `CaptureRunLogRecord` 读 proto58 `graphId`，跑一次只读观察，判「记录能否按 id 认领自己的图」。 |

---

## 2. UNKNOWN 表 — 归不进「有/无」的行

> 判据：**在 `docs/research/reverse-eng-20261010/` 44 份报告 + 本次复核范围内**，找不到把该原语钉成「有」或「无」的证据。
> 「未知」是成果，不是待办（`CLAUDE.md` §一.4）。每行写**已检索到哪里**与**定案需要什么**。

| 原语 | 为什么是「未知」 | 本次检索范围（搜过哪里） | 定案实验（ONE） |
|---|---|---|---|
| **level bounds read**（关卡边界/地图范围读） | 本目录内**无报告**以「关卡边界」为对象给过结论；`GEOMETRY-THREE-WAYS.md` 只覆盖**实体**几何与**关卡原点**（`origin[3]`，本机恒 `[0,0,0]`），`GIL-FIELD-LEDGER.md` 的 `field 11`＝关卡设置（阵营/出生点/预设点，**非边界**）。「边界」本身是**未在语料里定位的字段/概念** | `docs/research/reverse-eng-20261010/`（44 份，`grep -rnil "bounds\|关卡边界\|tilemap bound"` 仅命中 `ASSET-MEASURE-MINE`（预制尺寸）/`COMPONENT-READ-VALUE`/`OFFICIAL-*`，均为**模板/组件尺寸**非关卡边界）；`GEOMETRY-THREE-WAYS.md`、`GIL-FIELD-LEDGER.md` | 先澄清「边界」的所指；若是**可放置包络/关卡原点范围**，读 `origin[3]`（需一份 `origin≠0` 的会话）；若是**地形网范围**，走 #18 地形读。 |
| **graph export 里的「边」** | 负证据只到「未找到」，报告自己**明写不写成『不存在』**（`GIA-EXPORT-MINE.md:172-175,212-218`）。归「未知」而非「无」 | `GIA-EXPORT-MINE.md` §4（67 个桥导出 `.gia`、2859 条引脚全量走行） | 差分实验 §4.4（wire 一条边，导出两版做字节差）。 |

---

## 3. 三条必须一起读的不对称边界（`CLAUDE.md` §六）

本表里成对出现、方向相反的行，**不要因为一个方向通了就假设反方向通了**：

1. **组件：删存在、加不存在**（#6 vs #5）—— 命令面组件只有 `DeleteComponentForEditObj`/`DeleteComponentForPrefab`，
   `Add*Component*` 四处 0 命中（⚠️ 口径 2026-10-11：四处**非独立层**，独立轴＝两代构建 7.0/7.1）。**读存在（#4）、加不存在**——读探针只解锁「核实」，不解锁「配」。
2. **地形：读存在、持久化写不存在**（#18 vs #19）—— `terrain.py` 读半吃路径、写半只吃内存对象。
   **「能读」≠「能改」**。
3. **变换：改已有实体不行、建时能定**（#3 vs #1）—— `entity.create` 自带位姿；`entity.transform` 无 setter。
   **要摆布局，就在 create 那一刻一次给全**。

---

## 4. 引用来源（本表每条判决的出处报告）

- `CLAUDE.md` §一/§三/§五/§六（`docs` 层 doctrine；证据为 2026-10-10 静态复核）
- `MINED-INTERFACES.md`（接口总索引 + §11 负结论）
- `COMMAND-ROUTE-MAP.md`（前端 38 命令；transform CONFIRMED）
- `COMPONENT-READ-VALUE.md` / `COMPONENT-OP-PROOF-PLAN.md`（组件读／删）
- `COMPONENT-WRITER-MINE.md` / `COLLISION-TRIGGER-MINE.md` / `GRAPH-ATTACH-CHAIN.md`（组件加／挂载链）
- `TEMPLATE-CREATION-MINE.md`（建模板）
- `DICT-WRITE-PROBE.md` / `DICT-WIRE-FORMAT.md`（字典常量）
- `GIA-EXPORT-MINE.md`（导出）
- `GRAPH-DELETE-FIX.md` / `GRAPH-DELETE-PROBE.md`（图删除）
- `SAVE-WRITE-ATTRIBUTION.md` / `TAB-DIRECTORY-MINE.md`（原生 save 与写入方）
- `LEVEL-CREATE-MINE.md`（建关卡）
- `GEOMETRY-THREE-WAYS.md` / `GIL-FIELD-LEDGER.md`（几何/字段台账）
- `TERRAIN-WRITE-RISK.md`（地形写回风险）
- `GRAPH-VARIABLES-VERDICT.md`（图变量）
- `UI-CONTROL-WRITE-MINE.md`（UI 控件）
- `PLAYTEST-CONTROL-MINE.md`（试玩控制）
- `GRAPH-LOG-NEXT-STEP.md` / `GRAPH-RUNTIME-VERIFY-MINE.md`（图日志）
- `ENTITY-LIFECYCLE-MINE.md`（实体生命周期／删除边界）
- `ASSET-MEASURE-MINE.md`（模板尺寸，本表未单列，供 #7 关联）
- `NATIVE-ACTION-SET-MINE.md`（原生动作集，供 #3/#5/#7 的「新原语从哪来」）

---

*本文件由 2026-10-10 会话**只读**整理自 `docs/research/reverse-eng-20261010/` 下报告本身；
**未连桥、未发任何请求、未触碰游戏/编辑器/存档、未写任何存档字节、未读任何图片/PDF**。
每条判决均可在被引用报告的「一句话结论 / 判决 / 证据索引」段复核；本文件**不新增任何事实主张**，
只做归类、搬运与「下一步动作」的收敛。凡「未知」行**都写明已检索范围**——「搜不到」不等于「不存在」。*
