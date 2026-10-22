> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 建模板原语 · 命令表 / 消息层侧判决 —— 「建模板」在可读的命令面上到底有没有

日期：2026-10-10。
**全程只读**：未连桥、未发任何 bridge/native 报文、未注入、未启动或触碰游戏/编辑器、未起 helper、未申请 UAC。
对 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` **一个字节都没读也没写**（本文件未触碰存档）。
本文件只在 `docs/research/reverse-eng-20261010/` 内写这一个文件；本次检索脚本落在 `.runtime/scratch/`。

**本文件回答一个问题**（承接同题已落地的 `TEMPLATE-CREATE-TRACE.md`，但**换一面进攻**）：
前面一轮从**前端 UI 侧**（反编译语料 / UI 键 / 服务名槽位表）追「新建货币/道具/商店模板」按钮，撞在语料缺口上。
本轮**不碰 UI 语料**，只从**后端命令表**（`backend.db`）与**消息层**（`message_route` / `channel`）这一面核：
**「建模板」这条原语在「本工程能完整读到的」命令/消息面里，是在、是缺但可能在未读集、还是两边都没有？**

**数据来源（全部只读，`sqlite3` 逐行 SELECT）**
- `docs/research/beyondeditor-backend/db/backend.db` —— `command_route`(38) / `dispatch_entry`(41) / `dispatch_table`(2) /
  `service_route`(10) / `message_route`(24) / `egress_producer`(7) / `backend_gap`(17) / `candidate_name`(2090)。
- `docs/research/beyondeditor-frontend/db/frontend.db` —— `operation`(44) / `feature`(80) / `channel`(49) /
  `capability_gap`(28) / `ui_text`(7743)。
- 承接：`TEMPLATE-CREATE-TRACE.md`、`TEMPLATE-CREATION-MINE.md`、`SKILL-ASSET-VERDICT.md`（不重复展开其推导）。

---

## 0. 一句话判决

# **(b) —— 缺席可读命令面，但**很可能**在未读集。**

**没有一个字**把「建模板」放进「可读命令/消息面」（即 **(a) 不成立**）；
**也没有一个字**能把「建模板」钉死在「两边都没有」（即 **(c) 不成立**）——
因为**可读命令面本身可证是不完整的**：7 个已注册服务通道只定位了 **2 个**的分发表，
服务→分发表的选择机制走**托管虚 `GetHashCode`**（静态不可见），且已发现一条**绕过哈希表的全局钩子**。
⇒ **场景区块的后半（模板部分）判为「继续挖（mine harder）」，不是「硬堵死（hard blocked）」**；
但这挖法**不是重查命令名**（会继续 0 命中），而是补完**未读集**（见 §5 的下一步）。

---

## 1. 后端命令表逐行（`backend.db`）—— 没有任何建模板路由

### 1.1 `command_route`（38 行，全表逐行读过）

按语义分族（原文见各行的 `classification` / `handler_summary`）：

| 族 | 行数 | 命令 |
|---|---|---|
| 节点图挂载 | 2 | `AddInstructionGraphForEditObj`(id1)、`AddInstructionGraphForPrefab`(id2) |
| 删除 | 4 | `DeleteComponentForEditObj`(4)、`DeleteComponentForPrefab`(5)、`DeleteEditObj`(6)、`DeletePrefab`(7) |
| 聚焦 | 9 | `FocusBeyondTileMap`(8) … `FocusPrefabInstance`(15)、`FocusScreenshot`(16) |
| 改名/标签/阵营/套组/请求 | 8 | `ModifyEditObjName`(18)、`ModifyEditobjTag`(19)、`ModifyFactionForEditObj`(20)、`ModifyFactionForPrefab`(21)、`ModifyPrefabName`(22)、`ModifyPrefabTag`(23)、`ModifySuite`(24)、`RequestPrefabInstance`(25) |
| 变更应用 | 1 | `ApplyPrefabInstanceChange`(3) |
| 面板转发 | 1 | `JumpCombatSetting`(17) |
| 导入导出 / 调试日志 | 7 | `DoExport`(27)、`DoImport`(28)、`DeleteDebugLog`(26)、`ImportAllDebugLog`(29)、`ImportDebugLog`(30)、`ImportPerformanceReport`(31)、`RefreshExistDebugLogReport`(32) |
| 无游戏侧落点 | 6 | `EndLoadAllDebugLog`(33,disproved)、`PlayMusic`(34)、`PlaySoundEffect`(35)、`ModifyPCGInstanceName`(36)、`DeletePCGInstance`(37)、`FocusPCGInstance`(38)（后 5 条 `undecidable`） |

**判定**：`Add*` 只对**节点图**（挂图 ≠ 建实体）；`Modify*` 家族**只有** Name/Tag/Faction/Suite；
导入导出是 `.gia` 文件（`capability_gap` #10 明确「DoImport 是**入库**，不是场景放置」）；
其余是焦点/删除/调试/音频/PCG。
**没有一条**的名字（`command` 列）、服务（`service` 列）或分类（`classification` 列）与
「模板 / 货币 / 道具 / 背包 / 商店 / 新建 / create / template」相关。

### 1.2 `dispatch_entry`（41 行）—— 分发表里连一个 `Create*` 都没有

两张分发表（`dispatch_table`）：
- **表 1**（`role='主命令表（实体/预制体/节点图/聚焦）'`，4775 B，33 条 entry）——`beyondEditObjService`
- **表 2**（`role='导出与调试日志表'`，1803 B，8 条 entry）——`beyondExportService`

41 条 entry 的**全部**命中名（去重后 32 个）逐条列出：
`FocusEditObj / AddInstructionGraphForPrefab / DeleteComponentForEditObj / FocusLocalBullet /
AddInstructionGraphForEditObj / JumpCombatSetting / DeletePrefab / FocusBeyondTileMap / FocusCharacter /
ModifyPrefabTag / ModifyEditobjTag / FocusPrefabInstance / ModifyPrefabName / ModifyFactionForPrefab /
ModifyFactionForEditObj / ModifyEditObjName / RequestPrefabInstance / ApplyPrefabInstanceChange /
DeleteComponentForPrefab / FocusScreenshot / FocusDropGather / FocusEsp / DeleteEditObj / ModifySuite /
FocusLight / DeleteDebugLog / ImportDebugLog / ImportAllDebugLog / DoImport / RefreshExistDebugLogReport /
ImportPerformanceReport / DoExport`。
（32 + 6 条无落点命令 = `command_route` 的 38 行，两表自洽。）

**没有** `Create*` / `New*` / `Add*`（除两处挂节点图）/ `Template*` / `Save*` 的 entry。
`dispatch_entry.name` 为空者不算（本表 41 行**全部**有名字，没有「未匹配到候选名」的空行）。

### 1.3 `candidate_name`（2090 行）—— 「Template_*」是 **UI 控件模板**，不是游戏模板

数据库把「前端候选命令名 + 编辑器字符串表名」一起哈希后扫映像。
名字里含 `Template` 的候选（`editor_string_table` / `corpus_identifier` 桶）全部是——
`Template_NodeGraphEditor`、`Template_TextBlockCommon`、`Template_ComponentEdit_ComponentPanel`、
`Template_VMVMGeneralConfirmDialog_*`… ——即**列表框/对话框/画布的 UI 控件模板名**，
与「货币/道具/商店模板」**同名不同物**。另有一条 `PCG_Template`（corpus_identifier），属 PCG 实例范畴。
**这些 Template_* 没有一条在 `dispatch_entry` 里出现**（分发表无 UI 模板名，符合预期）。

### 1.4 `service_route`（10 行）—— 10 个服务名里**没有模板服务**

7 个 `beyond*` + 3 个 `wpf*`，逐条：`beyondEditObjService`(表1)、`beyondExportService`(表2)、
`beyondInstructionGraphService`(**无表**)、`beyondPCGInstanceService`(**无表**)、`beyondRoleStatusService`(**无表**)、
`beyondEffectService`(**无表**)、`beyondAudioService`(**无表**)、`wpfAudioService`、`wpfApplicationService`、
`wpfInstructionGraphService`（3 个 wpf 均 `side='editor_local'`，无表）。
**没有** `beyondTemplateService` / `beyondShopService` / `beyondStuffService` / `beyondCurrencyService`。

> ⚠️ **但这一列的负面是「软」的**，这正是 (c) 不成立的关键：
> `selection_mechanism` 一律记 **`Dictionary<string,ServiceEntry>.TryGetValue + 接口虚调用`**，
> 且 `name_encodings_found.found = 否（在磁盘上任何可读位置均未找到）`——**服务名是托管字符串字面量，
> 运行时才在加密的 `global-metadata.dat` 里解密**，静态哈希与三种明文编码**全 0 命中**。
> 即：**本表列出的 10 个服务名，其来源是「前端反编译语料里的字符串」，不是「后端映像里查到的」**。
> 语料没覆盖的服务名，本表**根本无从列**。

### 1.5 `backend_gap`（17 行）—— 库自己承认命令面是**部分**的

逐条过滤与本题有关的：

| row | topic | status | 对本判决的意义 |
|---|---|---|---|
| **#3** | 另外 3+ 个服务通道的 native 分发器 | `not_found` | 7 个服务注册点（0xa224da0）**本轮只对上 2 个**。5 个服务的原生分发器**未定位** ⇒ **命令面确为部分**。 |
| **#6** | `0x914de40`/`0x768d170` 的静态调用者 | `not_found` | 两个分发函数**各有 0 个 E8 直接调用者**，只经 `0x918dd40` 的**运行时接口虚调用**到达 ⇒ 谁进表**静态证不出**。 |
| **#7** | 全局可插拔钩子 `0x768d80e` | `pending` | 标志置位时**整个命令分发被委托给 `0xd4af450`，跳过哈希表** ⇒「哈希表里没有」**≠**「运行时不走它」。 |
| **#17** | 哈希扫描方法本身的边界 | `undecidable` | 本方法只发现**字面 imm32 比较**；间接方式（先算表索引再跳转 / 运行期构造的哈希）**看不见**。 |
| #4 | 6 条前端命令在后端无落点 | `not_found` | 其中 `ModifyPCGInstanceName`/`DeletePCGInstance`/`FocusPCGInstance` 属 PCG 服务（#3 的未定位者之一）。 |

**⇒ 库自身写明**：「未找到 ≠ 不存在」，且**命令面是「在候选名集合 / 编码 / 扫描段 / 已检查分发形式之内」的部分枚举**。

---

## 2. 前端功能表（`frontend.db`）—— 没有 create/save/new 操作

### 2.1 `operation`（44 行，全表逐行读过）

44 条操作名逐条：`AddInstructionGraphForEditObj`、`DeleteComponentForEditObj/Prefab`、`DeleteDebugLog`、
`DeleteEditObj`、`DeletePCGInstance`、`DeletePrefab`、`DoExport`、`DoImport`、`EndLoadAllDebugLog`、
`Focus*`（9 条）、`GetCursorPos`、`GetForegroundWindow`、`GetKeyboardLayout`、`GetWindowThreadProcessId`、
`ImportAllDebugLog`、`ImportDebugLog`、`ImportPerformanceReport`、`JumpCombatSetting`、`Modify*`（7 条）、
`PlayMusic`、`PlaySoundEffect`、`RefreshExistDebugLogReport`、`RequestPrefabInstance`、`RequestTypeUrl`、
`SerializeObject`、`SetFocus`、`ShowToolTipWhenTrimmed`。

**含 `Create` / `New` / `Save` / `Template` 的操作名：0 条。**
（`AddInstructionGraphForEditObj` 是**挂图**不是建图；`SerializeObject` 经 `capability_gap` #7 证为
**本地 Newtonsoft JSON**，非游戏 RPC。）

### 2.2 `feature`（80 行）—— 建模板相关的只有**节点图维度**

与「新建/保存」沾边的条目只有：
- **#14 `graph-create`「新建节点图」= `beyondInstructionGraphService.create`**，`reachable='yes'`。
  这是**节点图**的创建，**不是**货币/道具/商店模板。
- **#26 `graph-save`「节点图保存/另存为」= blueprint save/save as**，`reachable='unknown'`。
  这是**节点图**保存，**不是**模板保存。
- **#33 `prefab-library`「元件（预制）库」**，`reachable='yes'` —— 资源**库浏览**，非建模板。
- **#76 `scene-placement`「场景摆放 / 实体放置」**，`reachable='no'`（`capability_gap` #16 同判 `not_found`）。

**没有任何一条 `feature` 的 `slug` / `name_zh` / `name_en` 是**
「建模板 / 新建货币 / 新建道具 / 新建商店 / NewCurrency / CreateItem / CreateShopTemplate」之类。

### 2.3 `ui_text`（7743 行）—— 「新建/创建/保存」**全部**不属于模板面板

按 key 检索 `_NEW` / `create` / `_SAVE` / `template`，**49 条**命中，逐条归族**无一建模板**：

| 族 | 代表 key（= 界面文字） |
|---|---|
| 节点图/文件夹/变量/注释/复合节点 | `..._DEFAULT_RIGHT_MENU_NEW_FOLDER`(新建文件夹)、`..._NEW_SERVER_BP`(新建节点图)、`..._BP_VAR_CREATE`(新增变量)、`..._NODE_MANAGER_NEW_COMPOSITE_NODE`(创建复合节点)、`..._WPF_HISTORY_MENTION_NEW`(新建注释) |
| 造物/角色技能节点图 | `..._CLIENT_BLUEPRINT_{MONSTER_SKILL,MONSTER_POSE,MONSTER_AI,AVATAR_SKILL,CONTROL}_NEW` |
| 节点图保存 | `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_SAVE`(保存) / `_SAVE_AS`(另存为) / `_SAVE_SUCCESS`(保存成功) ——**均 `has_code=1`，均指节点图** |
| 环境(ESP) | `UI_BEYOND_EDITOR_ESP_LIGHTING_NEW`(新建光源)、`..._ESP_PROFILE_NEWPROFILE`(新建环境) |
| 特效器(VFX) | `..._VFXEDITOR_NEWVFXEDITOR`(新建特效器)、`..._VFXEDITOR_EX3_NEW`(新建轨道) |
| 信号 | `..._SIGNAL_ADD_NEW_SIGNAL`(添加信号)、`..._SIGNAL_ADD_NEW_VARIABLE`(添加参数) |

**⇒ 被逆向出来的编辑器里，「新建」覆盖了文件夹 / 节点图 / 变量 / 注释 / 复合节点 / 光源 / 环境 / 特效器 / 轨道 ——
唯独没有货币 / 道具 / 商店 / 背包模板**（与 `TEMPLATE-CREATE-TRACE.md §2` 的命名空间普查**独立同结论**）。

### 2.4 `capability_gap`（28 行）—— 两条直接相关的既有判决

- **#12「后台保存 / 原生持久化入口」`not_found`**：「字符串表 19 条命令名中**无 `Save*`**；
  12,375 个反编译类型里 `.gil`/`BeyondLocal` 字面量 **0 次**；65 个桥接 op 中含 save/persist 的 **0 个**；
  `vmBtnSave` 等只有属性声明无处理器。**这是「尚未找到」，不是「不存在」**」。
- **#16「场景摆放 / 实体放置」`not_found`**：「1024/1025 有载荷类型和调用点，**但未建立可靠的场景放置入口**」。

---

## 3. 消息层：哪条通道承载「持久对象写入」

### 3.1 后端 `message_route`（24 行，入站 1001–1024 的原生处理器）

对 1001–1024 逐号给 handler RVA：

| msg | handler | 说明 |
|---|---|---|
| 1001 | `0xa22347c` | handler（编辑器首帧） |
| 1002–1009 | `0xa223993` | **未处理 / 共用尾声**（`add rsp,0x28; pop rdi; pop rsi; ret`）|
| 1010 | `0xa223665` | handler |
| 1011 | `0xa2236b4` | handler（载荷 5×uint32；语义未定，见 `backend_gap` #16）|
| 1012 | `0xa223993` | 未处理 |
| 1013 | `0xa223703` | handler |
| 1014 | `0xa223752` | handler（图同步载荷）|
| 1015 | `0xa223993` | 未处理 |
| 1016 | `0xa2237c4` | handler（性能/内存周期上报）|
| 1017 | `0xa223993` | 未处理（回传的**资源分组 dirty 提交**；`egress_producer` #4 记其 `Tag(B=23)` 单类别）|
| **1018** | **`0xa223810`** | **handler —— 公共命令通道** |
| 1019 | `0xa223993` | 未处理（1018 的响应，出站侧由 `egress_producer` #2 记）|
| 1020 | `0xa223993` | 未处理（出站侧 = 外部资产列表通知，`egress_producer` #1）|
| 1021–1023 | `0xa223993` | 未处理 |
| 1024 | `0xa22383b` | handler（出站侧 = 同步请求）|

> **关键**：**1018 是唯一**把「带服务名 + 命令名 + 参数表」的语义命令送进后端**分发表**的通道。
> `egress_producer` #2 记 1018 入站处理器 `0xa223e00`：「walks the request's arg list …, calls
> `0x918dd40(conn+0x10, req+0x20, req+0x18, argsList, resultList)` → **`0x914de40`（FNV1a command dispatch）**」。
> 即：**凡有语义、要落地的命令（DeleteEditObj / ModifyEditObjName / Focus* / DoImport …）全走 1018**
> —— 一把建模板的命令**必须**也走 1018。而 1018 的可读命令词汇表（`command_route` 38 行）里**没有建模板**（§1）。

### 3.2 前端 `channel`（49 行）—— 逐条判「是否承载持久对象写入」

| channel 行 | msg | 方向 | 是否持久对象写入 | 依据 |
|---|---|---|---|---|
| **#32** | **1018** | **双向** | **是——唯一具名写入通道**（请求 = uint 请求号 + string 服务名 + string 命令名 + repeated 参数表，wire tag 8/18/26/34） | measured；`SAVE-PATH-TRACE.md`。**建模板必经此**；本通道词汇表里无建模板。|
| #42 | 2001 | 编辑器→对端 | **否（被常量假分支跳过）** | `capability_gap` #6：唯一业务 sender 原始 IL 是**常量假分支**，目标硬置 null ⇒ 不得改分支盲发。|
| #31 | 1017 | 对端→编辑器 | **否** | `egress_producer` #4：commit/dirty 家族，只承载 `Tag(B=23)` 单类别，非对象创建。|
| #28 | 1014 | 编辑器→对端 | 否（**图同步**）| `inferred`；编辑器把自己的图序列化后发出。|
| #38 | 1024 | 编辑器→对端 | 未证（**场景摆放候选**）| `capability_gap` #16：有载荷类型与调用点，**未建立可靠场景放置入口**。|
| #34 | 1020 | 对端→编辑器 | 否（**入站**通知）| 外部资产列表通知。|
| #45–49 | 3001/3002/3006 | 双向/入站 | 否（日志）| 调试日志通道。|
| 其余 1–10 | 1018 | 双向 | 是（**服务载体**）| 10 个服务通道挂在 1018 上；已知均为场景实体/导入导出/调试/音频/PCG/图，**无模板服务**。|

**⇒ 结论**：**要写一个持久对象（模板就是这个东西），唯一入口是 1018 命令通道**。
2001 那条（组件字段写）**已被常量假分支关死**；1017 只同步 Tag 分组；1024 未接通场景放置。
**1018 的可读命令集里没有建模板** ⇒ 命令/消息面**没有**这条原语（(a) 不成立）。

---

## 4. 判决（三态，逐条给证据）

| 候选 | 证据 | 判定 |
|---|---|---|
| **(a) 建模板存在于可读命令/消息面** | `command_route` 38 行无建模板（§1.1）；`dispatch_entry` 41 行 32 名里无 `Create*/New*/Template*/Save*`（§1.2）；`operation` 44 行无 create/new/save（§2.1）；`feature` 80 行无模板条目（§2.2）；`ui_text` 全部「新建/创建/保存」键均属节点图/环境/特效（§2.3）；10 个服务名无模板服务（§1.4）；1018 是唯一写入通道而其中无建模板（§3） | **REFUTED —— 可读面里没有** |
| **(b) 缺席可读面，但**很可能**在未读集** | **未读集 = (i) 5/7 服务通道的原生分发器未定位**（`backend_gap` #3：7 注册点只对上 2）；**(ii) 服务→表选择走托管虚 `GetHashCode`，静态不可见**（`service_route` 全 10 行 `name_encodings_found=否`）；**(iii) 一条绕过哈希表的全局钩子 `0x768d80e`**（`backend_gap` #7）；**(iv) 哈希扫描只发现字面 imm32**（`backend_gap` #17）；**(v) 前端**：发出建模板命令的「系统菜单」面板**不在** 12,375 文件语料里（`TEMPLATE-CREATE-TRACE.md §2/§5`）⇒ 其命令字面量也不在候选名集合里 ⇒ 就算后端有处理器，本轮**没有候选名去哈希、自然 0 命中** | **PLAUSIBLE —— 唯一未排除的正面路径** |
| **(c) 两边都没有** | 要断言 (c)，须证「可读命令面**完整**」或「1018 命令词汇表**完整**」。**二者均被否**：`backend_gap` #3/#6/#7/#17 + `service_route` 的托管哈希 + 前端语料缺口（(b) 的 (i)–(v)）。库自身写明「未找到 ≠ 不存在」「本方法只发现字面 imm32」 | **UNSUPPORTED —— 证不出** |

**一句话排序**：**(b) 缺席但很可能在未读集 ≫ (c) 两边都没有 ≫ (a) 现在就有**。

---

## 5. 这对「场景区块后半」意味着什么

**判为「继续挖（mine harder）」，不是「硬堵死（hard blocked）」。**

- **为什么不是硬堵死**：可读命令面**可证是部分的**（7 服务只对上 2；选择机制走托管哈希；有绕过哈希的钩子）。
  「命令面里没有」**推不出**「能力不存在」——本项目已把这条纪律写成 `CLAUDE.md:23`
  「『搜不到』≠『不存在』」。
- **为什么不是「已有门」**：**没有一个字**把建模板放进可读面 ⇒ 现在**没有**任何可调用的建模板入口。
- **正确的下一步（不是再搜命令名）**：
  1. **补完后端未读集**：定位剩下 5 个服务通道的原生分发器（`backend_gap` #3）——尤其
     `beyondInstructionGraphService`（已证有 `create`，其分发器未定位），它是「创建类命令长什么样」的现成样本。
  2. **补完前端语料缺口**：给「系统菜单（背包与货币 / 商店模板管理）」这块**从未被逆向**的 UI 建一份逆向覆盖
     （`TEMPLATE-CREATE-TRACE.md §7` 已指此路），读出「新建货币/道具/商店」按钮真正派发的**服务名 + 命令名**。
  3. 拿到**真实命令名**后，才回到 `command_route` / 游戏映像做落点扫描（现在扫只会继续 0 命中，因为无候选名）。
- **可复用的现成机制**：编辑器「新建」的**通用机制**已证 = 1018 命令通道 + `beyondInstructionGraphService.create`
  （`TEMPLATE-CREATE-TRACE.md §4.1`：字面量 `"create"` @ `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:12463`）。
  模板若存在，大概率是**同一机制换一个服务名**——这既是挖掘线索，也说明「结构上并非做不到」。

---

## 6. 三层口径（不得混称）

| 层 | 结论 |
|---|---|
| **文档写了什么** | 官方有货币(10)/道具(8)/背包(11)/商店(15) 四类配置 ID 与「新建商店模板」按钮（`TEMPLATE-CREATE-TRACE.md §7`）。**零执行。** |
| **工具/源码能做什么** | **本文件新增的一面**：后端 `command_route`(38) / `dispatch_entry`(41) / `service_route`(10) / `message_route`(24) 与前端 `operation`(44) / `feature`(80) / `channel`(49) / `ui_text` **逐行核过，0 条建模板**。命令/消息面**不存在**该原语；该面**本身不完整**（5/7 分发器未定位）。**这层是静态枚举。** |
| **真机验证过什么** | **本轮零执行**：未连桥、未发报文、未碰游戏/编辑器、未读写任何存档（本文件与本次检索脚本只写工程内）。|

## 7. 诚实负结论（写明搜了哪里、用什么工具）

| 未找到 | 搜过哪里 / 工具 |
|---|---|
| `command_route` 建模板路由 | `sqlite3` 只读 `SELECT * FROM command_route`（38 行，§1.1） |
| `dispatch_entry` 里任何 `Create*/New*/Template*/Save*` | `SELECT * FROM dispatch_entry`（41 行，§1.2） |
| `operation` 里 create/new/save | `SELECT * FROM operation`（44 行，§2.1） |
| `feature` 里建模板条目 | `SELECT * FROM feature`（80 行，§2.2） |
| `ui_text` 里模板面板的「新建」键 | `ui_text` 按 `_NEW/create/_SAVE/template` 检索（49 命中，全属他面板，§2.3） |
| 10 个服务名里的模板服务 | `SELECT * FROM service_route`（10 行，§1.4） |
| 消息层里承载建模板的通道 | `message_route`（24 行）+ `channel`（49 行）逐条判（§3） |
| 「命令面里没有」的反面（面本身完整） | `backend_gap` #3/#6/#7/#17 + `service_route` 的托管虚 `GetHashCode` 声明（§1.5）——**面不完整，故不成立** |

**未找到 ≠ 不存在**：以上「没有」均为**可读命令/消息面范围内**（`backend.db` + `frontend.db` 的上述诸表）。
**「另外 5 个服务通道的分发器未定位」+「系统菜单面板未逆向」是本轮认定 (b) 而非 (c) 的全部依据，
也是唯一可继续推进的洞**。

---

## 8. 复现命令（全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


> 本轮使用的检索脚本（均在 `.runtime/scratch/`）：`db_scan.py`（两库上述诸表逐行 dump）。
