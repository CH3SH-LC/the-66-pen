> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #4 挖 — 编辑器状态机（编辑态 / 运行态 / run）

**产出日期**：2026-10-10
**类型**：离线逆向，只读。**本轮没有起 bridge、没有发任何原生/图请求、没有接触游戏或编辑器、没有读写任何
`LocalLow` 存档。** 唯一新增文件＝本文件。
**口径**：按 `CLAUDE.md` §一.3 三层分开标（① 文档写了什么 / ② 工具能做什么 / ③ 真机验证过什么）。
本文件的结论几乎全是 **静态读**（反编译语料 + UI 文本表 + 桥源码 + 官方章）；**没有任何一条是本轮真机跑出来的**。
凡"有成分、没跑过"的，标 `只离线` / `未验证`。"搜不到"≠"不存在"，凡搜过的范围都写明（§1 表、§6）。

---

## 0. 一句话结论

**编辑器的"编辑态 vs 运行态"这个状态机确实存在（UI 文本自己证明它会被强制），但它在本仓能触达的范围内
只有"被动观察"，没有"可驱动的 setter"。**

1. **有状态机吗？有——但只以 UI 文案的形式被我们看见。** 编辑器自己的字符串表里写着
   「关卡运行状态下无法修改数据」（`.runtime/editor-catalog/textmap-chs.json:37305`）与
   「关卡运行状态下无法修改节点图，仅可查看」（同文件 `:37300`）。能被显示的文案 ⇒ 编辑器模型里必然有一个
   "运行中"的判断位在拦编辑动作。**但这两条是 `UI_BEYOND_LOG_*` 前缀**（调试日志/回放视图），**不是试玩**——
   见 §2 的区分。
2. **有可读的枚举/字段吗？在 resolved 语料里没有。** 本轮把 12375 个反编译 `.cs` 里**全部 427 个 `enum` 声明**
   抽出来逐个看成员名，与 edit/run/play/mode/state 沾边者**没有一个是编辑器状态机**（§1）。唯一的 `enum *Mode`
   是控件布局 `{ Normal, Mini }`；唯一的 `editMode` 字段类型是一个**单成员枚举 `{ Normal }`**（等于空壳）。
3. **桥能驱动吗？不能。** 桥的 op 面里零个起停试玩（`docs/editor-catalog/INTERFACE-INVENTORY.md:392`），
   桥对"进入运行态"**零写入口**；`startsPlaytest=false` 是源码里**刻意**写下的断言
   （`tools/editor-bridge/Adapter/EditorAdapter.cs:501,526`）。**唯一带副作用的通路是 `open-editor-panel`
   对菜单项 Action 的 `DynamicInvoke`**（`Adapter/PanelOpen.cs:90`）——那是"按下一个按钮"，**不是"把一个状态置位"**，
   且被硬白名单锁死在两个 label（`:36`）。
4. **能观察吗？能，但都很弱。** 编辑器侧只有**被动收包观察器**——只在收到**包类型 1022** 时记一笔
   （`Adapter/LevelInitObservation.cs:135-136`），**它不触发、也不区分"这次 1022 是试玩还是普通关卡加载"**；
   游戏侧有一个**真正是"编辑 vs 运行"判别位**的内存常量 `mode+0x1cc == 0xb993`
   （`Adapter/NativeSaveCatalogEvidence.cs:122-124`），但它属于 `YuanShen.exe`、当前只被当断言用，**没有枚举过**。

**一句话**：**试玩不是"把一个状态置位"能到达的**；它只能靠**调用编辑器自己的菜单 Action**（UI 触发），
且成败只能靠**回看证据**（包 1022 / 界面文案）判定，而不是靠任何一个我们拥有的状态标志。**这决定了
`playtest.control` 在本仓当前逆向水平下"只可观察、不可驱动"。**

---

## 1. 语料检索：resolved 里有没有一个"编辑器模式/状态"的枚举或字段？

### 1.1 检索方法（可复核）

- **对象**：`.runtime/editor-catalog/resolved/` 下 **12375** 个反编译 `.cs`（BeyondEditor 前端/VM 程序集；
  类型名混淆成 11 位串，但**枚举成员名是保留的**——例如组件类型枚举成员是 `BeyondCompTypeCollision` 而不是乱码，
  见 `QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49`。所以"按成员名 grep"对枚举**有效**）。
- **方法 A**：`grep -rIl -E "EditorMode|EditMode|PlayMode|PreviewMode|SimulateMode|EditorState|PlayState"` → **0 命中**。
- **方法 B**：用 Python 扫描全语料，抽出**全部 `enum` 块**（正则 `\benum\s+(\w+)\s*\{`，逐字符配平花括号），
  再按成员名过滤 `edit|run|play|simulat|preview|test|mode|state|status|phase|live|stop|pause|idle|ready|boot|init`。
  → **共 427 个 enum**；过滤后只命中下列几类，**没有一个是编辑器状态机**（结果见 1.2）。
- **口径**：`enum` 成员名可见，但**折叠常量命令名**（`--1347725427 ^ 0x50557993` 这类）不在盲区内。
  ⇒ 本节负面只对"**明文的枚举/字段名**"成立；"前端从不用某个折叠常量表示模式"**不能**由此否定。

### 1.2 命中清单（都不构成编辑器状态机）

| 命中 | 位置 | 成员 / 形状 | 是不是编辑器状态机？ |
|---|---|---|---|
| `enum XEKCwPuLuIbFcuaSycQR` | `resolved/AGgaX4uL7dYv3IJyTI4F.XEKCwPuLuIbFcuaSycQR.cs:3` | **只有 `Normal` 一个成员** | **否**，空壳 |
| 字段 `editMode` | `resolved/SEBGj6uPIYTjcxgTBeC8.H4ENZduPkaQ5CTaa2ENJ.cs:1219`（property；`set` 在 `:1225`，`case 1` 在 `:1233`） | 类型即上面的单成员枚举 | **否**。它在**文本框/模板编辑 VM**里（同文件同级字段：`vmVarPanel` `:1183`、`vmMenuContainer` `:1195`、`textEditDesc` `:1207`）——是"文本编辑模式"占位，且 setter 只在 `x==Normal` 时往下走（`:1233`） |
| `enum Mode` | `resolved/hmUgNruik7KRI4cXs0Tm.y2Mww8uieuUu6UHVBjuZ.cs:43` | `{ Normal, Mini }` | **否**，控件/集合视图的排布形态 |
| `enum u2nWUWi4Ei8tbmQLVnuN` | `resolved/nftmtEi44ZpaT9uR9UgI.u2nWUWi4Ei8tbmQLVnuN.cs:3` | `LevelEditObj_Dynamic=200 / LevelEditObj_Static=300 / PrefabEditObj_* / Tilemap=600 …` | **否**，**资源种类**枚举（内容分类，非编辑器状态） |
| `enum jaUof90C3Ncl5BAJri4x` | `resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3` | 46 项组件类型（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2），含 `BeyondCompTypeLevelStateMachine=31` | **否**，组件种类（`LevelStateMachine` 是**图内**组件，不是编辑器状态） |
| `\b(terrainedit\|entityplace\|prefablibrary\|battlepreset)\w*` | 全语料 | **0 命中** | 官方"模式切换"那 4 个**编辑期模式**在语料里**没有对应的可读标识符** |

### 1.3 小结（① 文档 / ② 工具交界）

**在 resolved 语料里，编辑器"编辑态 vs 运行态"没有被命名。** 这与 §2 的 UI 文本并不矛盾——文本证明"有那个位"，
但不给出符号名。⇒ 想读它，要么靠 UI 文案（不可程序化读），要么靠运行时对象走查（本仓未做）。

---

## 2. UI 文本层：运行态以"被强制的文案"形式暴露（本轮真正的发现）

`docs/editor-catalog/UI-TEXT-INVENTORY.md` 之前只记到 `试玩进行中`（`COSTLOAD_TESTING_TITLE`）。本轮把
`.runtime/editor-catalog/textmap-chs.json` 全表按"模式/状态/试玩/运行"重扫，拿到三条**有承载能力**的原文：

| 键 | 行 | 原文 | 说明了什么 |
|---|---|---|---|
| `UI_BEYOND_LOG_TIPS_DEBUG` | `.runtime/editor-catalog/textmap-chs.json:37305` | **关卡运行状态下无法修改数据** | 编辑器有"运行状态"，且**在该状态下拒绝编辑** |
| `UI_BEYOND_LOG_TIPS_BPDEBUGONLYFORREVIEW` | 同文件 `:37300` | **关卡运行状态下无法修改节点图，仅可查看** | 同上，且**节点图也进只读** |
| `UI_BEYOND_ASSIST_EDITOR_COSTLOAD_TESTING_TITLE` | 同文件 `:35150` | 试玩进行中 | 有一个"试玩进行中"的**状态面板** |
| `...configEnum_maps_41_mapTitle` / `_map_0` | 同文件 `:29640` / `:29645` | **游玩方式** ＝ `试玩 / 房间游玩 / 匹配游玩`（`:29650 / :29656` 后两项） | 存在一个**"游玩方式"枚举**，但它枚举的是**这次 run 的种类**（单人试玩 / 房间 / 匹配），**不是编辑态 vs 运行态** |

**关键区分（别把两个"运行"混成一个）**：

- `UI_BEYOND_LOG_*` 的"运行状态"是**编辑器内的调试日志/回放**：回放一段录下来的 run 时，编辑器进"运行状态"、
  禁止改数据。**这是编辑器自持的一个状态**（所以 `playtest.control` 之外还存在第二条"运行"语义）。
- `试玩`（§3）是**编辑器离开自己**、把同一关卡交给游戏去跑。方向相反。
- `游玩方式` 枚举是**关卡属性**，可在图内用节点 `766「查询对局游玩方式及人数」`
  （`textmap-chs.json:13070`，出参 `游玩人数` / `游玩方式`）在**运行中**读出来——**这是"当前 run 是哪种"的
  唯一现成读取口径，但只在关卡已经跑起来之后可用**。

**纪律提醒**：这些是"**编辑器会显示什么**"的证据（① 层），**不是"我们能读到什么"**（② 层）。
`UI-TEXT-INVENTORY.md:513,574` 已判：主编辑器外壳的中文界面文本**整体不在已提取字符串内**（疑在未解包的加密
`assets.bin`）。所以 §2 这几条来自**助手编辑器配置文本表**，能背书"存在"，**不能**背书"可 grep 到试玩按钮文案"。

---

## 3. 桥侧：编辑器暴露了什么状态；桥是否已经在观察模式变化？

### 3.1 桥目前只读"两个东西"，都不是状态机

**(a) `LevelLifecycleSnapshot()`——读一个缓存的关卡 id，不是状态。**
`tools/editor-bridge/Adapter/LevelLifecycleEvidence.cs:12-38`：读编辑器自己保留的 7.1 初始化载荷头
（字段路径 `YwCXahy5RIN.RmVRLESORxj.yoJRBJp4HeU`，`:36`），返回 `levelIdCandidate`。同文件 `:37-38` 自报
`nativeMethodsInvoked=false, sentToGame=false, freshnessVerified=false, reloadInvoked=false, reopenVerified=false`；
`:11` 注释明写 *"Reading this cache neither initiates a level load nor proves a fresh load."*
经 `EditorAdapter.cs:208`（`levelLifecycle=LevelLifecycleSnapshot()`）暴露。**这是读缓存，没有模式语义，也不发起加载。**

**(b) `LevelInitObservation`——被动的收包观察器，能看到"一次初始化发生过"，但不区分模式、也不触发。**
`tools/editor-bridge/Adapter/LevelInitObservation.cs`：
- `:135` 只有 `(ushort)initKindField.GetValue(packet) != 1022` 时 return；
- `:136` 注释 *"Only a received packet 1022 can advance this sequence. Polls never do."*；
- `:183` 返回值 `source="received-1022-packet-observer"`；
- `:199` / `:207` 硬写 `reopenVerified=false, causalReloadVerified=false`。

经 `EditorAdapter.cs:423`（`levelInitialization=LevelInitObservationEvidence()`）暴露，op 名走
`start-log-observer` / `log-observer-evidence` / `stop-log-observer`
（`tools/editor-bridge/ManagedBridge/BridgeServer.cs:528-530`）。
⇒ **若试玩会引发一次关卡初始化，这个观察器是"试玩确实发生了"的最佳被动证据通道——但它只能记"有一次 1022"，
分不清"试玩"与"普通重载"。**（未证：从未在试玩场景下跑过。）

### 3.2 桥有一个"带副作用"的通路，但它是 UI 触发、不是状态 setter

`tools/editor-bridge/Adapter/PanelOpen.cs` 读活的菜单项对象（label 字段 `MMGKX5coQC4`、callback 字段
`Te1KXhuGxBC`，`:31-32`），对**白名单内**的 label 取 `Delegate` 并 `DynamicInvoke()`（`:36` 白名单
`{ "节点管理器", "资源管理器" }`；`:90` 调用点）。
**它做的是"按下编辑器自己的一个菜单按钮"，不是"把一个编辑器状态置位"**；且源码自己划线
（`:106` *"success proves only that a delegate ran; it does not prove the panel opened"*）。
⇒ 这是候选 P1/P2 实验的落点（见 `PLAYTEST-CONTROL-MINE.md` §6），**但不是状态 setter**——调用它**不改变任何
我们拥有的状态**，也无从证明"编辑器进入了运行态"。

### 3.3 游戏侧：唯一一个真正的"编辑 vs 运行"判别位

`tools/editor-bridge/Adapter/NativeSaveCatalogEvidence.cs:122-124`：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

`:150` 在快照末尾再核一次 `mode+0x1cc==0xb993`（否则 `ARCHIVE_ROOTS_CHANGED`）。
- **这是本仓唯一见过的、被断言为"编辑态"的常量（`0xb993`）**，且它属于 **`YuanShen.exe`（游戏进程）**，
  不在编辑器里；它源码里**只被当门禁用**（要求"此刻是编辑态"），**从没被枚举**。
- `PLAYTEST-CONTROL-MINE.md` §5.3 已把它列为"候选的编辑态/运行态判别位"。**本轮没有改变这个判断**：
  `0xb993` 到底是不是"编辑态"、试玩期间会变成什么——**未证**。

### 3.4 桥里没有第三处

对 `tools/editor-bridge/Adapter/` 全目录检索 `mode|state|reopen|lifecycle`：除上面三处外，其余命中都是
`model`（模型）误匹配或"模式节点 652/647"这种**图内节点**语义（`FinishGraph.cs:84-85,209`、
`GameLoopGraph.cs:521`），**没有一个编辑器模式字段**。`EditorAdapter.cs:501,526` 的 `startsPlaytest=false`
是刻意断言，非观测。

---

## 4. 官方口径：`试玩` 到底转换了什么？

**唯一主源**：`.runtime/research-sources/official-docs/mhie54ik9ovg.txt`（试玩，997 字，全章逐字）+
distil `docs/official-docs/PLAYTEST-CONTROL.json`。

### 4.1 逐字事实（`mhie54ik9ovg.txt`）

| 面 | 原文 |
|---|---|
| 入口 | 「二、功能入口 **系统菜单——试玩**」 |
| 校验/上传 | 「点击【试玩】按钮后，会执行试玩**必要的校验和上传流程**，当检测到未满足条件时，将**弹出对应的错误码**供创作者(奇匠)检查。当所有检测条件都通过时，试玩流程将继续进行，**弹出【试玩设置】窗口**。」 |
| 流程 | 「试玩流程分为：**试玩前准备（上传，校验流程）——装扮展示——加载界面——进入关卡——结算关卡**」 |
| 局内控制 | 「处于试玩中时，可通过左上角退出按钮或 Esc 快捷键打开【试玩控制】面板」；三选项＝**继续挑战 / 重新挑战 / 中断挑战** |
| 其它开关 | 【试用奇偶】、【试玩时语言】、【启用试玩结算】关闭结算、【试玩临时数据】引用 |

### 4.2 官方**没有**写的东西（决定验收判据）

- **校验结果不可后读**：错误码以**弹窗**形式给创作者看，官方页**没有**"运行结束后可读的校验报告"
  （`PLAYTEST-CONTROL.json` 的 `forPlaytestControl.officialCheck.whatIsNOTDocumented`）。
- **返回编辑态 = NOT COVERED**：官方从未写"退出试玩后如何回到编辑器"
  （`PLAYTEST-CONTROL.json` 的 `forPlaytestControl.returnToEditMode`）。

### 4.3 官方也没有一个"编辑态 vs 运行态"的状态名

官方语料里"模式"这个词，指的**要么是编辑期内部的 4 个模式，要么是试玩这个流程**：

- `mhn4bsi5lb58`「五、模式切换」逐字：「通过顶部的按钮…可切换当前所属**编辑模式**，共分为以下 **4 个模式**：
  **地形编辑 / 实体摆放 / 元件库 / 战斗预设**」（`.runtime/research-sources/official-docs-sweep-20260929/sources/mhn4bsi5lb58.txt`，与 `docs/official-docs/chapters/mhn4bsi5lb58.json` 一致）。
  ⇒ **这是"编辑态内部"的工具模式，不是"编辑态 vs 运行态"。**
- 「运行态」在官方语料里只以**节点可用性条件**出现（`PLAYTEST-CONTROL-MINE.md` §2.2 引 `mhkirfrna1fy`：
  「节点保持泛型状态**进入试玩**会导致节点不合法」）——即官方用"进入试玩 = 进入运行时"。

### 4.4 小结（③ 层）

**官方把"试玩"描述成一个从菜单**发起**的**流程**，不是对一个具名状态的**开关**。** 官方既没命名编辑/运行态，
也没给返回路径，更没给可后读的校验报告。⇒ 即便找到入口，**验收判据也应是"校验跑过了 / 发生了一次关卡初始化"
而不是"读到了某个状态值"**（与 `PLAYTEST-CONTROL-MINE.md` §7.2 一致）。

---

## 5. 判决：能"驱动"的状态，还是只能"观察"的状态？

**结论：只有"观察"，而且很弱；没有任何"可驱动的 setter"。**

### 5.1 没有 setter 的证据（逐条）

1. **op 面零入口**：桥的 op 白名单（`tools/editor-bridge/call-bridge.ps1` 的 `ValidateSet`）里**没有
   `start-playtest` / `stop-playtest` / `enter-runtime` 一类**；`docs/editor-catalog/INTERFACE-INVENTORY.md:392`
   的既有负结论成立（"没有 `start-playtest`（试玩只由 UI 触发）"）。`EditorAdapter.cs:501,526` 两处
   `startsPlaytest=false` 是**刻意**断言。
2. **命令面零入口**：`docs/research/beyondeditor-backend/db/backend.db → command_route` **全 38 行**逐条看过，
   **没有一条**是起停试玩或切模式（38 条全是 Focus*/Modify*/Delete*/DoImport|DoExport/音频/PCG）；
   `docs/research/beyondeditor-frontend/db/frontend.db → operation` **全 44 行**同样零命中。
3. **语料零符号**：§1 的 427 个 enum 全部枚举过——**没有任何**编辑/运行态枚举或带 setter 的字段。
4. **编辑器 UI 侧唯一带副作用的通路**是 `PanelOpen` 的菜单 Action `DynamicInvoke`（`PanelOpen.cs:90`）；
   它是**UI 触发**，被白名单锁死（`:36`），且**调用成功 ≠ 状态改变**（`:106` 源码自证）。

### 5.2 "能观察到的"清单（按强弱）

| 观察对象 | 位置 | 能看到什么 | 强弱 |
|---|---|---|---|
| 包 1022 被动观察器 | `Adapter/LevelInitObservation.cs:135-136,183` | 收到过一次**关卡初始化** | **中**：能证"有一次加载发生过"，**不能**区分试玩 vs 普通重载，也**不触发** |
| 编辑器缓存关卡 id | `Adapter/LevelLifecycleEvidence.cs:12-38` | 编辑器保留的 `levelIdCandidate` | 弱：是缓存，无模式语义，不发起加载 |
| UI 文案"关卡运行状态下…" | `textmap-chs.json:37300,37305` | **证明编辑器有运行态判断位** | 弱：**不可程序化读**（且是调试日志/回放那条，非试玩） |
| `试玩进行中` 面板文案 | `textmap-chs.json:35150` | 存在试玩中的状态面板 | 弱：仅供"存在性"背书 |
| 游戏侧 `mode+0x1cc==0xb993` | `Adapter/NativeSaveCatalogEvidence.cs:122-124,150` | 被断言为"编辑态"的游戏内存字节 | 中：**唯一真正"编辑 vs 运行"的判别位**，但属 `YuanShen.exe`、当前只当门禁、**未枚举** |
| 图内节点 766 | `textmap-chs.json:13070` | 运行中读"游玩方式/游玩人数" | 只在**关卡已跑起来之后**可用 |

### 5.3 后果（决定 `playtest.control` 可达性）

- **试玩不是"把一个状态置位"能到达的。** 桥没有任何 setter，语料里没有任何编辑器状态符号。
- **唯一可能真正"按下试玩按钮"的机制**是 `open-editor-panel` 那条菜单 Action 通路（`PanelOpen.cs:31-90`）——
  它已是候选 P1（只读枚举菜单项）/ P2（`DynamicInvoke` + 回看）实验的落点（`PLAYTEST-CONTROL-MINE.md` §6）。
  **本轮没有推翻也没有推进它**：本文件只额外证明**"即便按钮被按到，也不存在任何状态标志能证明编辑器变了态"**——
  所以 **P2 的判定标准必须仍是回看证据**（包 1022 / `CurrentCaptions()`），**不是 `ok:true`，也不是某个状态字段**。
- **真正能把"编辑态 vs 运行态"做成可读量的是 `mode+0x1cc`（游戏侧）**，它对应 `PLAYTEST-CONTROL-MINE.md` §6.3
  的 P0 探针（用户手工点一次试玩的前/后各读一次）。**本文件给这条探针补的是一条纪律**：它读的是
  **游戏进程**的字节，**编辑器**侧的运行态**目前无符号可读**——不要把"游戏侧读到 0xb993"当成"读到了编辑器状态机"。

### 5.4 什么会改变这个判决

- 在 resolved 语料里找到**新的、带多成员的**编辑/运行枚举（本轮已穷举 427 个 enum，未见）；或
- 反射到一个**编辑器侧的**模式 setter/getter（需连桥，本轮不跑）；或
- `mode+0x1cc` 被**枚举**（不再只当断言）并证明它随试玩变化（P0 探针，需在场）；或
- `open-editor-panel` 的运行时枚举（P1）命中外壳系统菜单的 `试玩` 项且带 `Te1KXhuGxBC` 回调——**那只给出一个
  UI 触发点，仍不给出状态**。

---

## 6. 本轮检索范围（"搜不到"要能被复核）

| 检索对象 | 位置 | 方法 | 结果 |
|---|---|---|---|
| 反编译语料（12375 `.cs`） | `.runtime/editor-catalog/resolved/` | Bash `grep -rIl`（Grep 工具会跳过 `.runtime/`）+ Python 抽全部 **427** 个 enum | **零**编辑/运行态枚举（§1） |
| 助手配置文本表 | `.runtime/editor-catalog/textmap-chs.json`（7743 条） | Python 全表按 模式/状态/试玩/运行 过滤 | 命中运行态**文案** 2 条 + `试玩进行中` 1 条 + `游玩方式` 枚举 1 组（§2） |
| 字符串表 | `.runtime/editor-catalog/{string-table.json,all-recovered-strings.txt,strings-real.txt}` | `grep -c 试玩` | **0 / 0 / 0**（"试玩"按钮文案不在已提取字符串内，与 `UI-TEXT-INVENTORY.md:513,574` 一致） |
| 后端命令路由 | `docs/research/beyondeditor-backend/db/backend.db → command_route` | SQL 全表 38 行 | 零起停试玩/切模式（§5.1） |
| 前端操作名 | `docs/research/beyondeditor-frontend/db/frontend.db → operation` | SQL 全表 44 行 | 零命中 |
| 桥 op 白名单 | `tools/editor-bridge/call-bridge.ps1`（`ValidateSet`）、`ManagedBridge/BridgeServer.cs` | 通读 | 零 `start-playtest`；观察器 op = `start-log-observer`/`log-observer-evidence`/`stop-log-observer`（`:528-530`） |
| 桥 Adapter | `tools/editor-bridge/Adapter/` | `grep -rInE "mode\|state\|reopen\|lifecycle"` | 只有 §3 三处，无状态机（§3.4） |
| 官方章 | `.runtime/research-sources/official-docs/mhie54ik9ovg.txt`、`.../official-docs-sweep-20260929/sources/mhn4bsi5lb58.txt`、`docs/official-docs/PLAYTEST-CONTROL.json`、`.../chapters/mhn4bsi5lb58.json` | 逐字 | §4 |

---

## 7. 逐条引用（file:line）

- 语料：`.runtime/editor-catalog/resolved/AGgaX4uL7dYv3IJyTI4F.XEKCwPuLuIbFcuaSycQR.cs:3`；
  `.../SEBGj6uPIYTjcxgTBeC8.H4ENZduPkaQ5CTaa2ENJ.cs:1185,1197,1213,1219,1224`；
  `.../hmUgNruik7KRI4cXs0Tm.y2Mww8uieuUu6UHVBjuZ.cs:43`；
  `.../nftmtEi44ZpaT9uR9UgI.u2nWUWi4Ei8tbmQLVnuN.cs:3`；
  `.../QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49`。
- UI 文本：`.runtime/editor-catalog/textmap-chs.json:13070,29640,29645,29649,29653,35150,37300,37305`；
  `docs/editor-catalog/UI-TEXT-INVENTORY.md:256-258,513,574`。
- 桥：`tools/editor-bridge/Adapter/LevelLifecycleEvidence.cs:11,12,36,37,38`；
  `tools/editor-bridge/Adapter/LevelInitObservation.cs:135,136,183,199,207`；
  `tools/editor-bridge/Adapter/EditorAdapter.cs:208,423,501,526`；
  `tools/editor-bridge/Adapter/PanelOpen.cs:31,32,36,90,106`；
  `tools/editor-bridge/Adapter/NativeSaveCatalogEvidence.cs:122,124,150`；
  `tools/editor-bridge/ManagedBridge/BridgeServer.cs:528,529,530`；
  `tools/editor-bridge/call-bridge.ps1`（`ValidateSet`）。
- 台账/研究：`docs/editor-catalog/INTERFACE-INVENTORY.md:392`；
  `docs/research/reverse-eng-20261010/PLAYTEST-CONTROL-MINE.md` §2.2,§3.1-3.3,§5,§6.1-6.3,§7。
- 官方：`.runtime/research-sources/official-docs/mhie54ik9ovg.txt`（试玩全章）；
  `.runtime/research-sources/official-docs-sweep-20260929/sources/mhn4bsi5lb58.txt`（整体界面·五、模式切换）；
  `docs/official-docs/PLAYTEST-CONTROL.json`（`returnToEditMode`/`whatIsNOTDocumented`）；
  `docs/official-docs/chapters/mhn4bsi5lb58.json`（`headline`/`correctsOrRefines`）。

---

## 8. `notClaimed`

- 本轮**什么都没跑**：没有起 bridge、没有发原生/图请求、没有开游戏或编辑器、没有读写任何存档。
- **没有**证明编辑器里存在一个具名的"编辑态/运行态"枚举——恰恰相反，**427 个 enum 里一个都没有**（明文范围）。
- **没有**证明 `mode+0x1cc==0xb993` 就是"编辑态"；**没有**证明试玩会让它变值——那是 P0 探针，未执行。
- **没有**证明包 1022 会在试玩时出现；**没有**证明 `open-editor-panel` 能到达"试玩"——那是 P1/P2，未执行。
- **没有**断言 `UI_BEYOND_LOG_*` 的"运行状态"就是试玩——本文件明确把二者区分为**两条不同的"运行"语义**。
- `试玩进行中` / `关卡运行状态下…` 来自**助手编辑器配置文本表**，不等于"试玩按钮文案可被 grep 到"
  （后者据 `UI-TEXT-INVENTORY.md:513,574` 不在已提取字符串内）。
