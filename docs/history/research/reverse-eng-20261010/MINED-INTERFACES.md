> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# MINED-INTERFACES — 逆向挖出的接口清单（可查证索引）

> 建立日期：2026-10-10。位置：`docs/research/reverse-eng-20261010/MINED-INTERFACES.md`。
> 本文件把 `CLAUDE.md` §一 的那张表升级成一份**活的、可逐行核对的索引**：
> 工程里**每一个真正能用的能力**，记录 **①怎么挖到的 ②实现 file:line ③真机证据 ④状态**。
>
> **本文件的每一条都从仓内代码/证据里读出**，不凭记忆写。凡是**找不到 file:line**、
> 或**找不到真机证据**的，**一律不写成"已验证"**——要么标注为 `只离线验证过`/`未验证`
> （如 §4 的 scheduler 行），要么收进 §11 的负结论，**不臆造 interface**。

---

## 0. 怎么读这份表

**挖出方式**（`CLAUDE.md` §一 的六种，逐行标注）：

| 代号 | 含义 | 挖出物的载体 |
|---|---|---|
| `反射` | 注入 `BeyondEditor.exe` 后反射调用（`RequireEditor`+`Resolve`） | `tools/editor-bridge/Adapter/*.cs` |
| `内存读` | 原生探针编译成 DLL、在 `YuanShen.exe` 进程里按偏移读内存 | `tools/game-executor/native/*` |
| `资源解码` | 离线 `XOR 0xE5` → protobuf，读编辑器资源包 | `tools/editor-catalog/`、`tools/cordis-plugin/` |
| `容器逆向` | 逆 `.gil`/`.gip` 的容器 framing 与字段号 | `tools/beyond-save/` |
| `静态分析` | 反编译 + 代理映射还原"混淆名 → 真名"，再生成绑定档 | `EditorBindingProfile.Generated.cs` |
| `前端资源` | 读编辑器前端命令路由/菜单 | `docs/research/beyondeditor-*` |

**状态口径**（沿用 `docs/PROGRESS-BY-FUNCTION.md`）：

- `真机验证过` — 在**运行的编辑器/游戏**上跑过，且有**独立读回**（`.gil` 字节差分、二次 inspect、独立快照）。
- `只离线验证过` — 代码/合同/单测在仓内成立，但**没有当次真机执行证据**。
- `未验证` — 有实现，找不到任何执行证据；**不等于"不存在"**（见 `CLAUDE.md` §一推论 2）。

**三条纪律**（本文件的立身之本，同 `CLAUDE.md` §一）：

1. **三层必须分开**：`文档写了什么` / `工具能做什么` / `真机验证过什么`。本表只记**后两层**。
2. **`ok:true` 不等于落盘**——只读操作尤其如此；落盘只有**原生 `save` + 独立 `.gil` 字节差**才算数。
3. **`.runtime/` 用 Bash 的 `grep`/`ls` 查**（Grep 工具会静默跳过 `.runtime/`）。

> 行内约定：`B("混淆名")` = 通过绑定档把**旧名**解析成**当代构建的真实名**
> （`EditorAdapter.cs:87`）。所有"实现"列的行号均为本 checkout 当前行号。

---

## 1. 节点图创作 / graph authoring（桥 → 反射 `BeyondEditor.exe`）

**怎么挖到的**：静态分析还原混淆符号（§8）后，反射调用编辑器程序集里的**节点图模型**
（Kind 9）与**节点定义模型**（Kind 6）。分发层是 `Producer::Ikci0qkvMZX`
（`docs/editor-catalog/INTERFACE-VERIFICATION.md` 真机实测"存在、实例方法、4 参数"）。
CLI 侧 `tools/authoring/author.py`，适配层 `tools/editor-bridge/Adapter/AuthoringGraph.cs`。

单一动作的请求形状（白名单）在 `AuthoringGraph.cs:95-108`；每个动作的实现锚点如下：

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| `graph create`（建空图） | 反射 | `AuthoringGraph.cs:222`；action 表 `:96`；CLI `author.py:57` | `graph create → ok create-requested-readback-pending`（`PROGRESS.md:41`）；R169/R175 建图 `authoring-api-20260923/` | **真机验证过** |
| `graph lookup`（异步建图后取 id） | 反射 | `AuthoringGraph.cs:234`（`lookup-pending` 分支） | `PROGRESS.md:42`；`lookup → graphId 1073741829`（`PROGRESS.md:511`） | **真机验证过** |
| `graph inspect`（模型读回） | 反射 | `AuthoringGraph.cs:259`（`State("editor-model-readback")`） | `d1-inspect.json`；`PROGRESS.md:44` 独立读回与计划逐项相同 | **真机验证过** |
| `graph export`（导出 GIA） | 反射 | `AuthoringGraph.cs:260`（`ExportResource`） | R169 独立 GIA 读回（`PROGRESS.md:489`：`exportVerified:true`、GIA sha `d1f0dfd7…`） | **真机验证过** |
| `graph add-node` | 反射 | `AuthoringGraph.cs:320`；形状校验 `:120-134` | `688`/`691` 真机加进图并读回（`VERIFICATION-R262.json`） | **真机验证过** |
| `graph pin-slots`（只读引脚发现） | 反射 | `AuthoringGraph.cs:347`、`:354-372` | 无独立真机回执；是 `set-value` 的前置读 | `只离线验证过` |
| `graph set-value`（带类型常量写+读回） | 反射 | `AuthoringGraph.cs:374-391`；`AuthorWriteScalar` | R169 中文打印串写值（`PROGRESS.md:2989`）；R262 记录字符串读回符号缺档（`PROGRESS.md:80`） | **真机验证过**（string 只写不读回） |
| `graph set-print`（print 节点文本） | 反射 | `AuthoringGraph.cs:264`→`:528` | R169/R175 print 链（`PROGRESS.md:489`） | **真机验证过** |
| `graph set-condition` | 反射 | action 表 `AuthoringGraph.cs:99` | 无独立真机回执 | `只离线验证过` |
| `graph connect`（连线） | 反射 | `AuthoringGraph.cs:393-448`（`Link`） | R169 `graph wire --from 1 --to 2 → link-accepted`（`PROGRESS.md:2991`）；R267 一次建 17 条边（`PROGRESS.md:48`） | **真机验证过**（运行时语义仍未证） |
| `graph disconnect` | 反射 | `AuthoringGraph.cs:393`/`:442-448`（`HasLink` 反查） | 无独立真机回执 | `只离线验证过` |
| `graph bind`（图挂到实体） | 反射 | `AuthoringGraph.cs:298-318`（`AddInstructionGraphForEditObj`） | 独立 inspect `boundEntityIds=[1077936129]`（`PROGRESS.md:13`、`:243`） | **真机验证过** |
| `graph build-print`（空图→固定 2 节点） | 反射 | `AuthoringGraph.cs:264`→`:528` | L15 print 链（`PROGRESS.md:489`，graphId `1073741830`） | **真机验证过** |
| `graph build-count-gate`（空图→固定 13 节点门） | 反射 | `AuthoringGraph.cs:272`→`:611` | `graph count` 于 R236 真机派发（`PROGRESS.md:502`）；DLL 内确认在（`:530`） | **真机验证过**（跨修订 spent 标记会丢） |
| **`graph build-plan`（一次派发建整图，本工程新增）** | 反射 | `AuthoringGraph.cs:268`→`:733`（`BuildAuthorPlan`）；形状校验 `:140-147`；CLI `author.py:591-601` | R266 一次建 13 节点（`PROGRESS.md:58-73`）；R267 一次建 **15 节点/17 边/13 常量**（`PROGRESS.md:38-48`） | **真机验证过** |
| `graph catalog`（资源目录读） | 反射 | `author.py:472-476`；`tools/editor-bridge/graph-transport.ps1` | R262 完整返回（`VERIFICATION-R262.json`；此前 15s 响应窗超时的根因已修） | **真机验证过** |

**组合层（离线，不碰桥）**：`tools/gameplan/` 把"一张图"声明出来 → 对照合同离线校验 → 变有序原生调用。

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| 图的声明与离线校验（引脚/方向/类型） | 反射（消费 §6 合同） | `plan.py:98`（`GraphPlan`）/`:167`（`validate`）/`:201`/`:292` | — | `只离线验证过` |
| 计划 → 原生调用（逐 op 与 `build-plan` 批处理） | 反射 | `builder.py:206`（`build`）/`:350`（`batch_plan_json`）/`:368`（`build_batch`） | 批处理真机见上表 `build-plan` 行 | `build-plan` 路径**真机验证过**；逐 op 路径**真机跑不完**（5 分钟租约 vs 每派发 ~16s pin 哈希，`PROGRESS.md:60`） |
| 请求 id ＝ 请求本身的函数 | — | `builder.py:54`（`request_id`） | `PROGRESS.md:78` 记录我曾因漏 `run-id` 误判冲突 | **真机验证过**（防重语义） |

---

## 2. 原生场景 inspect / create / save（游戏进程 → 内存读 + 原生调用 + 落盘）

**怎么挖到的**：原生探针编译进 `YuanShen.exe`。`inspect` 只读内存（§4）；
`create`/`save` 是**固定锚点上的原生调用**（`scene_calls.cpp`），落到**游戏进程/存档文件**——
**不是编辑器**。唯一的写通道是提权 helper（§10）。

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| `scene inspect`（实体表只读快照） | 内存读 | `scene_cli.py:598-613`；`game_context_snapshot.cpp` | `gameplan live` 实测 `entities 11→12`（`PROGRESS.md:12`） | **真机验证过** |
| `entity create`（单实例，按坐标/旋转/缩放） | 内存读 + 原生调用 | CLI `scene_cli.py:613`+`author.py:562`；`game_scene_action.cpp:184`（`#if HR_ACTION==1`）；`scene_calls.cpp:34-50`（`place_builtin`） | `actionStatus 0 / called 1 / entityId 1077936129`（`PROGRESS.md:11`）；`r168-created-save-verification.json` | **真机验证过** |
| `entity create-batch`（一批 ≤256，单回调） | 内存读 + 原生调用 | `game_scene_action.h:10`（`kMaxBatch=256`）；`game_scene_action.cpp:241`（`HR_ACTION==3`）/`:272`（`placedCount`） | 两实体批量落盘逐项核对（`batch-two-save-verification.json`；`PROGRESS.md:2260`） | **真机验证过** |
| `level save`（原生保存） | 内存读 + 原生调用 | `scene_cli.py:587`（读 `nativeSaveStatus`）；`game_scene_action.cpp:214-216`（`HR_ACTION==2`）；`scene_calls.cpp:56-60`（`save_current`） | `.gil` **21872→28383 B**、sha `88ad2acf…→56feb97d…`、载荷含 entityId/graphId/templateId（`PROGRESS.md:14-15`） | **真机验证过** |
| `save` 的严格复核门（新鲜基线+新复核） | — | `scene_cli.py:252-269`；`orchestrate_write_review.py` | `PROGRESS.md:17`（"本工程自己的新鲜基线 + 生产校验器通过的复核"） | **真机验证过** |
| `creature-create`（生物模板） | 内存读 + 原生调用 | `scene_cli.py:258`/`:613`；helper 动作集含之（`PROGRESS.md:109`） | 未找到真机执行回执 | `未验证`（有实现，未跑过） |
| `reopen-current`（重开） | 内存读 + 原生调用 | `native/reopen_action.cpp`；`reopen_action_validation.cpp` | 被 `lifecycleType=not_initialized` 卡住（`PROGRESS.md:1484`）⇒ `blocked` | `只离线验证过`（真机是**被拒**，不是通过） |
| 回执结构（action/levelId/entityId/nativeSaveStatus） | — | `game_scene_action.h:17-31`；`hook_receipt_probe.cpp:238-239` | 回执即上面各行的读数来源 | **真机验证过** |

> **`ok:true` 单独不证明持久化**（`CLAUDE.md` §四）：`actionStatus 0` 只是"这一调用被接受"的
> 回执（`game_scene_action.h:33` 原文）；落盘必须 `.gil` 字节差分 + 独立读回。

---

## 3. 关卡 id 发现（原生只读，绝不读磁盘记录）

**怎么挖到的**：在 `YuanShen.exe` 内存里按偏移读**关卡管理器**，同一帧**读两次并比对**，
不一致即 `GS_UNSTABLE`。id 来自**本次原生回执**，不是调用方、config 或 wire 占位符。

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| 当前关卡 id + 实体数（实时原生读） | 内存读 | `discover_current_level.py`（入口）；`game_context_snapshot.cpp:164`（`LevelObservation`）/`:169`（`ReadLevelObservation`）/`:178`（`GS_LEVEL_ID_OFFSET`）/`:179`（mode/editing 校验）/`:181`（`SameLevelObservation`）；双读比对 `:398-399` 与 `:456-459` | `.runtime/verification/live-probe-20261009-R263/LIVE-PROBE-R263.json`（`levelId 1073741842`、`entities 11`、`levelObservationVerified:true`）；`docs/PROGRESS-BY-FUNCTION.md:207-212` | **真机验证过** |
| `gameplan live`（把上面变成一等 CLI，helper 没起就拒绝） | 内存读 | `live.py:89`（`helper_status`）/`:102`（`current_level`）/`:120`（`read_live`）；`live.py:139-141`（非提权即拒） | `PROGRESS-BY-FUNCTION.md:209`（`levelId 来自本次回执 receiptSha256 208be340…`） | **真机验证过** |
| wire 占位 id 防混淆 | — | `discover_current_level.py`（`QUEUE_CLAIM_LEVEL_ID` 只能当占位，观察值等于它即拒） | `PROGRESS.md:639`（占位 `4294967295` ≠ 观察值） | **真机验证过** |

**纪律绑定**：关卡 id 是**存档的函数，永不固化**（记忆 `level-ids-are-per-save-never-pinned`）——
每次实机动作前必须用**当次回执**重新 discover（`CLAUDE.md` §四）。

---

## 4. 原生只读探针：内存读（生命周期 / 调度器 / 目录 / 重开门）

**怎么挖到的**：与 §3 同一套——固定版本 profile（偏移 + 锚点字节 + hotfix 字节）+ 独立回执解码器。
profile 在 `tools/game-executor/profiles/`，偏移宏在 `native/game_context_snapshot.cpp:33-79`。

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| 关卡目录（level catalog） | 内存读 | `native_level_catalog.py`（绑定 profile）；`native/game_level_catalog*.cpp` | `readCalls=92`（`PROGRESS.md:1350`）；`pinned-refresh-20261002/RESULT.md`（离线编译 exit 0） | **真机验证过**（只读） |
| 生命周期类型（lifecycle type） | 内存读 | `native_lifecycle_type.py`；`native/game_lifecycle_type*.cpp` | 真机读到 `status=not_initialized`、`classPointer=0x0`（`PROGRESS.md:1309`、`:1484`） | **真机验证过**（观测；值=未初始化） |
| 调度器协程（scheduler coroutines） | 内存读 | `native_scheduler_coroutines.py`；`native/game_scheduler_coroutines*.cpp` | **根本没读**：`readCalls=0`、`prerequisite_rejected_before_scheduler_reads`（`PROGRESS.md:1484`） | `未验证`（前置门先拒） |
| 重开门（reopen guards） | 内存读 | `native/game_reopen_guards*.cpp`；`native_reopen_guards.py` | `pinned-refresh-20261002/`（离线编译）；真机条件受 §3 约束 | `只离线验证过` |
| profile 源码哈希绑定（改一版就 fail-closed） | — | `native_profiles.py`（`PROFILE_SHA256`、`load_profile`） | `pinned-refresh-20261002/RESULT.md`（9 文件字节替换、5/5 sha 相符） | **真机验证过**（绑定层） |

---

## 5. `.gil` / `.gip` 容器编解码（容器逆向）

**怎么挖到的**：逆 `.gil`（每关一个）与 `.gip`（玩家档案）的**相同 framing**：
`u32be 总长 / version=1 / magic=0x326 / subtype(1=玩家,2=关卡) / 内层长 / payload / trailer=0x679`，
payload 是 protobuf。字段号从真实文件读出，未解字段一律留在 `raw` 里**不丢、不猜**。

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| 容器 framing 解码/编码（可逐字节回环） | 容器逆向 | `gil_container.py:42-44`（`VERSION/MAGIC/TRAILER`）/`:86`（`decode_container`）/`:106`（`encode_container`）/`:176`（`parse_fields`）/`:209`（`encode_fields`） | `.runtime/beyond-save/fixtures/*.gil`+`.gip`；`test_gil_container.py` 的 `test_roundtrip_is_byte_identical`（`PROGRESS.md:10847`：26 项） | **真机验证过**（读真机存档；回环证明可安全改一个字段） |
| 关卡描述符字段（id/名/创建者/时间戳） | 容器逆向 | `gil_container.py:63-66`（`LEVEL_FIELD_ID=1 / NAME=2 / CREATOR_UID=39 / TIMESTAMP=40`）/`:257`（`parse_level`）/`:540`（`read_level`）/`:549`（`read_profile`） | 四个真机关卡 + 真 `.gip`；`PROGRESS.md:15`（落盘后用 `.gil` 字节差分核对） | **真机验证过** |
| 地形段（`field 7`，只读解码） | 容器逆向 | `terrain.py:74-81`（`FIELD_TERRAIN_LIST=7`、地形 id/名/变换/400 格）；`:249`（`_decode_terrain`）；`:280`（`read_terrain_fields`） | `docs/gameplan/TERRAIN-STATUS.md:32-51`（真机文件 `1073741825..834.gil`；`f1=(x<<16)\|y`、三关 sha 相同） | **真机验证过**（**只读**；全仓无地形写入者） |
| 关卡注册写入（`register_level.py`） | 容器逆向 | `register_level.py`；`keep_registered.py` | 被 7.1 版本门 **fail-closed**（`version_guard.py`；`PROGRESS-BY-FUNCTION.md:249`） | `只离线验证过`（**被版本门拒绝**） |

---

## 6. 节点合同（资源解码 `.mihoyobin` + 真机节点读）

**怎么挖到的（资源侧）**：编辑器加载器对 `.mihoyobin` 做**单字节 `XOR 0xE5` 再 protobuf**——
变换**来自编辑器自己的加载器反编译**（`file-loader.cs:250`），不是猜。负载按 protobuf wire 通用走位，
**每个字段按号+wiring 标注，不编造语义**。
**怎么挖到的（真机侧）**：反射读生存的节点定义模型（Kind 6），作为"分母"的独立陈述。

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| `.mihoyobin` 解码器 | 资源解码 | `decode-mihoyobin.py:7`（出处）/`:58`（`XOR_KEY=0xE5`）/`:186`（应用异或） | `.runtime/editor-catalog/_paths.txt`（`files=4098`，含 799 节点）；`docs/editor-catalog/NODE-CATALOG.md` | **真机验证过**（真机资源，只读离线解码） |
| 节点合同构建（810 定义 / 929 变体 / 4637 端口） | 资源解码 + 真机节点读 | `tools/cordis-plugin/build_node_contracts.py`（见文件 docstring `:3-20`）；产物 `data/node-contracts/index.json`（`definitions:810 / variants:929 / server 500,client 429 / ports:4637`） | `data/node-contracts/index.json` 的 `denominator.statements` 引用 `.runtime/verification/interface-experiments-20260926/live-node-schema.json` 等真机读 | **真机验证过**（分母来自真机读，不来自产物自身） |
| 合同消费（引脚/方向/类型校验） | 反射 | `contracts.py:47`（`DEFAULT_CONTRACT_DIR`）/`:163`（`load_store`）/`:187`（`default_store`）；pin-kind 语义 `:22` | 由 §1 `plan.validate` 消费；`test_plan.py` 逐条回合同复核 | `只离线验证过` |
| 真机节点定义读（`node-definitions`，有界 64） | 反射 | `GameNodeCatalog.cs:12-42`；`FinishNodeCatalog.cs:13-28`（`FinishNodeIds` 固定集） | R171 实读 23 种定义（`tools/authoring/INTERFACE-INVENTORY.md` `graph.schema` 行）；`.runtime/verification/game-b-nodes-20261009/node-definitions-42.json` | **真机验证过** |

> **两套命名空间别混**（记忆 `node-ids-two-namespaces`）：桥收**小整数 `definitionId`（1~300005）**；
> 离线资源是 **64 位哈希**（＝`.mihoyobin` 文件名），**交集 0**。本地有 **929 条活快照** + **500 条端口合同**。

---

## 7. 预制 / 场景目录（反射 `Resources()` 已物化的模型）

**怎么挖到的**：反射读编辑器**已物化**的 `entityModels`/`prefabModels`，只读字段、**不调用任何原生 getter**。
`templateId` 是真实配置 ID；`prefabId` 是**独立的关联缓存**（可为 0，不能替代模板）。

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| 场景快照（实体 + kind1 预制，有界去重） | 反射 | `SceneCatalog.cs:18`（`SceneTransformField`）/`:16`（`SceneEntityLimit=128`）/`:20-40`（`SceneCatalogSnapshot`） | `PROGRESS.md:9535`（11 实体 / 2477 预制，`scene-readback-verification.json`） | **真机验证过**（只读） |
| 预制目录分页读（2722 条） | 反射 | `PrefabCollectionEvidence.cs:14`（前向只读注释）/`:30`（`PrefabPageMaxSize=128`） | `.runtime/verification/interface-experiments-20260927/p03/resource-pages/merged-summary.json`（2722 项 `readSummary.complete=true`、R195/R200/R201；`PROGRESS-LITE.md:1587`） | **真机验证过** |
| 模板名规则（`expectedName == 目录[templateId]`） | 反射 | `entity_name_rule.py:17`（规则）/`:59`（冻结目录 `prefab-name-directory.json`）/`:75`（`load_directory`） | 93,287 条名字覆盖比对（`PROGRESS.md:1902`：80,584 命中） | **真机验证过**（规则边界是量出来的） |
| 预制业务字段读（14 MB / 128 模板） | 反射 | `PrefabFieldRead.cs` | `PROGRESS-LITE.md:1555`（16678 对象；**限定范围内的负结论**：18 个 Vector3 候选类型出现 0 次） | **真机验证过**（**有范围限定的负结论**） |

---

## 8. 绑定档符号（静态分析 + PE 元数据）

**怎么挖到的**：反编译编辑器主程序集 → 还原 **34,728 条"槽位→真名"代理映射**
（`docs/editor-catalog/README.md`）→ 生成 `EditorBindingProfile.Generated.cs`。
运行时**只做元数据校验**（不动 getter/constructor），并**先验盘上 SHA256 + 模块 MVID**
才返回程序集——**改名解析错比解析不到更危险**，所以 fail-closed。

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| 旧名 → 当代真名解析（`B("混淆名")`） | 静态分析 | `EditorBindingProfile.cs:99-100`（`Resolve`）/`:104-118`（`ResolveInProfile`，未登记即 `UNREGISTERED_SYMBOL`） | 每次成功注入（R262/R268）都要求解析通过（`VERIFICATION-R262.json`） | **真机验证过** |
| 身份/哈希/MVID/合同四重校验（fail-closed） | 静态分析 + PE 元数据 | `EditorBindingProfile.cs:1-30`（文件头声明的规则）/`:121`（`RequireEditor`） | `PROGRESS-LITE.md:1754`（"Adapter 的 257 符号 / 263 合同… 已修复"——见下注） | **真机验证过** |
| 生成档数据：**307** 个 legacy 符号 / **313** 条合同 | 静态分析 | `EditorBindingProfile.Generated.cs:8-317`（`LegacySymbols`）/`:321-630`（`Symbols` 字典）/`:631-946`（`Contracts`） | 计数以本 checkout 实测为准（`BINDING-SYMBOL-AUDIT.md` 同口径 307/313） | `只离线验证过`（纯静态数据） |
| 离线自校验：313 条合同 vs 真实 `BeyondEditor.exe`（MetadataLoadContext，不加载运行） | 静态分析 | `tools/editor-bridge/tests/version-bindings/Program.cs:41`（`MetadataLoadContext` 读真 PE）/`:44`（`all 263 real PE contracts pass`） | 该 program 即自校验器；**运行结果未在本轮重跑** | `只离线验证过` |
| 登录 profile 常量 | 静态分析 | `Generated.cs:321`（`"BeyondEditor-7.1.0-static"`、sha `565DDA11…`、MVID `39031639-…`） | 同上 | `只离线验证过` |

> **注（数字陷阱）**：`PROGRESS-LITE.md:1754` 记的是当年"257 符号/263 合同"；
> `version-bindings/Program.cs:21` 仍断言这两个旧数——**与当前生成档（307/313）不符**。
> 本表以**当前文件实测**为准，并如实标注这处历史漂移，**不据旧数声称现状**。

---

## 9. 客户端脚本探针 / client-script probes（反射）

**怎么挖到的**：7.1 新增客户端脚本（Lua）是一等资源。反射读/写编辑器里**已物化**的脚本模型与脚本目录
（`const string ClientScriptModel = "EngUDvX1xc7DWWwYrrw1.vVUju1X1mM5GsVZX9XiF"`），
**不枚举文件夹、不打开磁盘路径**。创建/改名/删除都带**自有范围**保护（只动本次建的那一项）。

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| 只读目录读（脚本注册表投影） | 反射 | `ClientScriptReadEvidence.cs:13-15`（模型名/上限 4096/深度 6）/`:17`（`ClientScriptRootReadOnly`） | `.runtime/verification/interface-experiments-20260928/client-script-readonly/result.json`（R202：`nodesVisited 186`、`materializedCount 0`） | **真机验证过** |
| 脚本目录定位（类别 69） | 反射 | `ClientScriptFolderEvidence.cs:8-`（`ScriptFolderStorage` 类型/类别校验） | 同上（`folderId:2`+类别 69） | **真机验证过** |
| 单次创建 / 同 ID 改名 / 删除 | 反射 | `ClientScriptCrudProbe.cs:33`（`Begin`）/`:114`（`Create`：`B("kqaXokY6uBT")`）/`:125`（`Rename`：`B("OtFXociSjVD")`）/`:136`（`Delete`：`B("IMMXoYC9rQd")`） | `.../client-script-crud/result.json`（R208：`resourceId 1073741825`、`sameIdAfterRename:true`） | **真机验证过** |
| 批量创建 / 批量删除 / 正文读回 | 反射 | `ClientScriptBatchProbe.cs` | `.../client-script-batch/result.json`（R209） | **真机验证过** |
| 导出脚本 GIA 并独立解析 | 反射 | `ClientScriptExportProbe.cs:13-20`（自有范围门） | `.../client-script-export/result.json`（R210：289 B、`luaBytes 74`、相对路径与源码逐字节匹配） | **真机验证过** |
| 改相对路径（仅 basename，不碰磁盘） | 反射 | `ClientScriptFileProbe.cs:15-20`（`ValidateClientScriptFilePath`） | `.../client-script-crud/file-result.json`（R208） | **真机验证过** |
| 变量：整数创建 / 官方重置默认字符串 | 反射 | `ClientScriptVariableProbe.cs:11-15`（加/删/重置 spent 标记） | `.../client-script-vars/result-r214.json`（R214：47 项核验） | **真机验证过** |

> **边界**：这些是**编辑器侧资源**的读写，**不等于 Lua 在游戏里运行**（`result.json` 原件明写
> "未执行脚本、未保存/重开"）。"挂载与运行"仍未闭合（`PROGRESS-LITE.md:1572`）。

---

## 10. 写入通道：提权 helper（队列）

**怎么挖到的**：编辑器以提权运行，桥的管道 `PipeOptions.CurrentUserOnly` ⇒ 非提权客户端被拒，
于是每次 load/call 都会弹 UAC。解法是**一次提权、常驻的 helper**，只认**封闭的请求种类**，
**绝不执行请求里给的命令**。

| 能力 | 挖出方式 | 实现 file:line | 真机证据 | 状态 |
|---|---|---|---|---|
| 非提权客户端投递/取回 | — | `elevated-request.py:1-22`（只投文件，不自身执行） | `PROGRESS-LITE.md:1474`（helper 自核 `elevated=true`、`pinsDigest` 变化即独立证明） | **真机验证过** |
| 常驻 runner（六类封闭请求） | — | `elevated-runner.ps1:1-30`（`native-scene`/`author-graph`/`status`/`load`/`call`/`fs`） | `PROGRESS.md:109`（动作集 `[inspect,create,save,create-batch,reopen-current,creature-create]`） | **真机验证过** |
| 修订注入（同一修订同进程只能注入一次） | — | `next-revision.ps1`；`new-scope.ps1` | R262 一次即成功、R261 已烧掉（`VERIFICATION-R262.json`） | **真机验证过** |

---

## 11. 负结论（同样是成果，且都有 file:line）

这些是"**已确证做不到**"，不是"还没做"（`CLAUDE.md` §一推论 4、§五）。

| 负结论 | 依据 file:line | 真机证据 | 状态 |
|---|---|---|---|
| `entity.transform`（改已有实体位置/朝向）**不存在**——前端命令面没有 transform 写原语 | `docs/research/beyondeditor-user-operations/`（`Modify*` 家族只有 Name/Tag/Faction/Suite）；`AuthoringGraph.cs` 无 transform 动作 | `docs/PROGRESS-BY-FUNCTION.md:225-228` | **真机验证过**（负） |
| 建/开关卡被 7.1 **版本门** fail-closed 挡死 | `version_guard.py:344`；`beyond-save/register_level.py` | `docs/PROGRESS-BY-FUNCTION.md:249` | **真机验证过**（负） |
| 地形编辑：`.gil` `field 7` 是地形，**全仓 0 个读写者**，且**无地形类节点** | `terrain.py`（只读）；`gil_container.py:63-66`（不含 field 7）；§6 合同无地形节点 | `docs/gameplan/TERRAIN-STATUS.md:32-51` | **真机验证过**（负） |
| 桥写 UI / 组件 / 属性 / 模板：桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 **0 命中** | `tools/editor-bridge/Adapter/*.cs` 全符号检索；`docs/research/game-b-systems-20261009/` | `docs/PROGRESS-BY-FUNCTION.md:181` | **真机验证过**（负） |
| **写字典常量**（contract 类型 27）无原语——但**字典节点存在**：500 条服务端定义里有构造器 `1088 建立字典`/`1788 拼装字典`/`948`、取元素 `1158 以键查询字典值`；缺的只是「把字典写成**常量**」（`SLOT_FOR_TYPE[27]=None`、无 setter），且构造器引脚是 Generic，物化到 concrete(27) 未上机 | `tools/gameplan/paramtypes.py:30`（`DICT=27`）/`:76`（`DICT: None`）；`modules/shop.py:49`（`DictPinUnsupported`）；`docs/research/reverse-eng-20261010/DICT-WRITE-PROBE.md` | `PROGRESS.md:53` | **静态/只读**（原句「没有一条构造字典」是过度概括，2026-10-12 更正） |
| `delete-owned-graph-ids` 历史**四次全 `modelMatched=0`**，一次没成功过 | `Adapter/OwnedGraphDelete.cs`；诊断 `AuditGraph.cs:101`（走到的是实体不是图） | `VERIFICATION-R262.json`（`D2DiagnosticResult`） | **真机验证过**（负；已查明根因，仍未修） |

---

## 12. 与兄弟文档的分工

本目录另有两位智能体的产出，**本文件只做接口索引，不重复**：

- `COMMAND-ROUTE-MAP.md` — 编辑器前端 **38 条 `command_route`** 的命令路由图。
- `GRAPH-DELETE-PROBE.md` — 图删除探针的深挖。
- `BINDING-SYMBOL-AUDIT.md` — 绑定档里"**还有什么没被用上**"的逐符号审计（307/313/8 个未用符号）。

前置静态事实（非本文件新增）：
- `docs/editor-catalog/INTERFACE-VERIFICATION.md`（2026-09-18 真机）：代理映射 **21 槽 19 命中**、**13 通道全部可用**。
- `docs/editor-catalog/README.md`：4098 资源 / 799 节点 / 34,728 代理映射 / 12,375 反编译类型。

---

## 13. 汇总：真机验证过 vs 只离线验证过

| 组 | 真机验证过的能力数 | 只离线 / 未验证的 |
|---|---|---|
| §1 节点图创作 | 12 个动作（含 `build-plan`）+ 组合层批处理 | `pin-slots`／`set-condition`／`disconnect`；逐 op 路径跑不完 |
| §2 原生场景 | `inspect`/`create`/`create-batch`/`save`+复核门 | `creature-create`（未跑）；`reopen-current`（被拒） |
| §3 关卡 id 发现 | 全部 | — |
| §4 内存探针 | catalog、lifecycle（读到未初始化）、profile 绑定 | scheduler（没读）；reopen guards（离线） |
| §5 `.gil`/`.gip` 编解码 | framing/字段/地形（只读） | 关卡注册写入（被版本门拒） |
| §6 节点合同 | 资源解码 + 真机节点读 + 合同分母 | 合同消费（离线） |
| §7 预制/场景目录 | 场景快照 + 2722 目录 + 名字规则 + 字段读 | — |
| §8 绑定档符号 | 真名解析 + 身份校验（真机注入） | 生成档数据、离线自校验（纯静态） |
| §9 客户端脚本探针 | 读/创建/改名/删除/批量/导出/变量 | 挂载与运行（未闭合） |
| §10 写入通道 | 全部 | — |

> **一句话**：这张表里**几乎所有行都可追到真机证据**，但**"真机验证过"只到"落盘/读回"**；
> **图的运行时语义**（连线是否真按执行流跑）**仍未验证**——那需要一次真机试玩
> （`PROGRESS.md:21`、`PROGRESS-BY-FUNCTION.md:251`）。

---

*本文件由 2026-10-10 会话从仓内代码与 `.runtime/` 证据整理；未改动任何代码、未连接桥、未碰游戏/编辑器/存档。
所有引用行号为本次 checkout 实测。凡未能给出 file:line 或真机证据的条目，已按 §0 的口径降级或留空。*
