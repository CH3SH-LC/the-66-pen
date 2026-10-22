> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #8 判决 — `playtest.control`：试玩能不能被程序起停（收口）

**产出日期**：2026-10-10
**类型**：离线逆向，只读收口。**本轮没有起 bridge、没有发任何原生/图请求、没有接触游戏或编辑器、没有读写任何
`LocalLow` 存档、没有读任何图片或 PDF。**
**口径**：按 `CLAUDE.md` §一.3 三层分开标（① 文档写了什么 / ② 工具能做什么 / ③ 真机验证过什么）。本文件结论全是
**静态读**（resolved 反编译语料 + 桥源码 + 官方章 + 前序报告）；**没有一条是本轮真机跑出来的**。
**"搜不到" ≠ "不存在"**：凡搜过的范围都在 §2/§5 写明，负面只对写明的范围成立。

---

## 0. 一句话判决

> **未知。**

`playtest.control` 的**"把一个状态置位"这条路已经可以判死**（§2 证明：编辑器语料里根本没有可被驱动的
"编辑态/运行态"字段，桥 op 面里也没有起停模式的 op，§3）。**但整个 capability 不能就此判死**——因为
**唯一不依赖状态字段的候选通路（按下编辑器自己的「试玩」菜单按钮）从未被执行过**，而"我们搜不到某个符号"
**不能**推出"那条通路不存在"（本仓纪律）。
⇒ 剩下的**定案实验只有一个**（§4），且是**纯只读**的。**本文件把该实验的名字与判据写死，不执行。**

**逐层判决**（供 INDEX 对齐，避免继续漂移）：

| 问题 | 判决 | 依据 |
|---|---|---|
| 编辑器里存在一个 bridge 能**驱动（setter）**的模式/状态字段吗？ | **不能** | §2 全区语料零命中 |
| 桥 op 面里有起停模式/试玩的 op 吗？ | **不能** | §3 逐条看，零 |
| bridge 能**观察**到"进了运行态"吗？ | **未知（弱通道）** | 仅游戏侧 `mode+0x1cc`（只当门禁）+ 包 1022 被动观察器（§3） |
| **整个 capability：程序能否起停试玩？** | **未知** | 唯一定案实验＝§4 的 P1，未执行 |

---

## 1. 前序报告已读 + 何处漂移

**已读全部两份前序报告**：

- `OFFICIAL-PLAYTEST.md`（官方侧逐字）：(a) 触发进入 **不能**（UI-only，无命令名/API/快捷键）；(b) 读校验结果
  **不能（by design，只弹错误码）**；(c) 察觉状态 **未知**（无程序句柄）；(d) 退回编辑 **不能（官方根本没写）**。
- `PLAYTEST-CONTROL-MINE.md`（代码侧）：bridge 面**零入口**且**不是"少一个 op"**；唯一候选＝
  `open-editor-panel` 的菜单 Delegate 通路（`PanelOpen.cs:31-90`，被白名单锁死 `:36`）；候选实验 P1（只读枚举菜单项）
  / P2（`DynamicInvoke` + 回看）/ P0（跨状态读游戏侧 `mode+0x1cc`）**全部未执行**。

**漂移在哪里（本次要收口的东西）**：三处文档对同一 capability 给了不同强度的词——

| 文档 | 现措辞 | 问题 |
|---|---|---|
| `INDEX.md:42` | **不能**（bridge 面零入口，UI-only；官方亦无程序落点） | 把"bridge 面零入口"说成了整体"不能"，**过强** |
| `PLAYTEST-CONTROL-MINE.md` | **不能**（bridge 面）/ **未知**（候选 P1 未执行） | 正确，但"不能/未知"两分未给判据边界 |
| `EDITOR-STATE-MACHINE.md`（INDEX:152/214） | **不能**（不可驱动）/ **能**（有限观察） | "能观察"的措辞也偏强（观察通道全是被动的，§3） |

**收口原则**：**"bridge 面零入口"只关闭"op/状态字段驱动"这一层；它不关闭"按下 UI 按钮"这一层。**
本文件据此把整体判决定为 **未知**，并把"不能"的成立范围写死在 §2/§3。

---

## 2. 本轮**新增**的调查（前序报告没做过的那一件）

**问题**：resolved 语料里，有没有一个编辑器 **MODE/STATE 字段或枚举**（试玩/Run/Play/Preview/Simulate/EditMode），
且它**带 setter（可驱动）**，而不是只有一个**可读的 getter（可观察）**？

**方法（可复核）**：

- **对象**：`.runtime/editor-catalog/resolved/`（**12375** 个反编译 `.cs`，BeyondEditor 前端/VM 程序集；
  类型名混淆成 11 位串，但**成员名保留**——故"按标识符名扫"有效）。
- **方法 A（标识符普查，非仅 enum 声明）**：单趟 Python 扫全语料，抽出**所有**含 `Mode|State|Status|Phase` 的
  标识符，按词频排序，逐个人工判定是不是"编辑器运行态"。→ 共 **51** 个 distinct 标识符（§2.1）。
- **方法 B（点穴式全文匹配）**：对以下**精确 token** 做全 12375 文件单趟匹配，**逐个计数**：
  `PlayMode, RunMode, PreviewMode, SimulateMode, EditorMode, EditMode, EditorState, PlayState, isPlaying,
  isRunning, IsRunning, inRunState, playMode, runState, appState, levelRunning, isPlaytest, Playtest,
  enterPlay, StartPlay, StopPlay, tryPlayMode, simulate, Simulate, EnterRun, StartRun, StopRun,
  isPlayingLevel, IsPlaying, EditorState, AppState`。→ **除下述外，全部 0 命中**（§2.2）。
- **中文侧**：`grep -rIl 试玩 .runtime/editor-catalog/resolved/` → **0**；`grep -rIl 运行 …/resolved/` → **0**。
  对照：`试玩` 只在 `textmap-chs.json` 出现 **6** 次（助手编辑器**配置文本表**），在
  `string-table.json / all-recovered-strings.txt / strings-real.txt / node-names.json` 全 **0**。

### 2.1 方法 A 结果：51 个命中标识符，没有一个是"编辑态 vs 运行态"

命中的**全部**归三类，**无一类**是编辑器运行态：

| 类别 | 代表标识符 | 是不是"编辑态 vs 运行态"？ |
|---|---|---|
| WPF/基础设施 | `WindowState`(+`set_WindowState`)、`PlacementMode`、`ResizeMode`、`FileMode`、`CompressionMode`、`CryptoStreamMode`、`CipherMode`、`MouseButtonState`、`EditorBrowsableState`、`AsyncStateMachine/IteratorStateMachine/IAsyncStateMachine`、`ViewModelCore/ViewModel/ObjectModel/ComponentModel/BydeModel/Model` | **否**。`PlacementMode` 经核是 `System.Windows.Controls.Primitives.PlacementMode`（ToolTip/ContextMenu 摆放），`set_WindowState` 是窗口最小化/最大化 |
| UI 控件 VM 开关（**带 setter**） | `isDebugMode`、`deleteMode`、`vmRadioBtnViewMode`、`isEditing`、`editMode` | **能驱动，但都不是运行态**：`isDebugMode` = 调试日志开关；`deleteMode` = 资源管理器删除态；`isEditing` = 某个文本编辑 VM 的 bool；`editMode` = **单成员枚举 `{Normal}`** 的占位（setter 只在 `==Normal` 才落，等于空壳） |
| 图内/业务语义 | `beyondRoleStatusService`/`RoleStatus`/`CustomRoleStatus`/`OfficialRoleStatus`、`BeyondCompTypeStatus`、`BeyondCompTypeLevelStateMachine`、`ValidateAndModifyStateForValue`、`loadVsStatus`、`dynamicCostLoadStateList` | **否**。`LevelStateMachine` 是**图内组件**（组件种类 31），不是编辑器状态；`RoleStatus` = 队伍/角色状态 |

⇒ **语料里根本没有"编辑器运行态"这个字段。** §2.2 的精确匹配把这件事钉死。

### 2.2 方法 B 结果：点穴式匹配几乎全 0，`Preview/Editing` 是唯一的假阳性

- **全 0 命中的 token**（对 12375 文件）：`PlayMode, RunMode, PreviewMode, SimulateMode, EditorMode, EditMode,
  EditorState, PlayState, isPlaying, isRunning, IsRunning, inRunState, playMode, runState, appState,
  levelRunning, isPlaytest, Playtest, enterPlay, StartPlay, StopPlay, tryPlayMode, simulate, Simulate,
  EnterRun, StartRun, StopRun`。
  ⚠️ **注意 `Simulate` 与 `Playtest` 也全 0**——连"模拟"、"试玩"这两个英文词在反编译语料里都**不存在**。
- **唯一的两个非 0**（且都不是编辑器运行态）：
  - `Preview`（43 命中）——**全部**是 WPF 输入事件名（`PreviewMouseLeftDownCommandProperty`、
    `PreviewKeyDownCommandProperty`、`add_PreviewMouseLeftButton…`，见 `BeyondEditor.ViewModelCore.FrameworkPropertyExtension.cs`），
    是"输入预览"，不是"关卡预览模式"。
  - `Editing`（1 命中）——`O1XvBAKJpNB6IglU2s7G.MvMDsBKJfguRrUWndHFQ.cs:76` 的 `public bool isEditing`
    （带 setter `:84`），是某个**文本编辑 VM** 的编辑态标志，不在任何"关卡/试玩"上下文里。

### 2.3 §2 结论（回答"可驱动 vs 只可观察"）

> **在 resolved 语料里，编辑器侧**没有一个**可被 bridge 驱动的"编辑态/运行态"字段或枚举；也没有一个
> **可被驱动的试玩/运行态**。存在的 `Mode/State` 标识符要么是 WPF 基础设施，要么是**与本 capability 无关的
> UI 控件 VM 开关**（`isDebugMode`/`deleteMode`/`viewMode`/`isEditing`/`editMode`-空壳——它们**有 setter、
> 理论上可驱动**，但**驱动的不是试玩**）。
> ⇒ **"驱动试玩"这条路，在编辑器语料里找不到任何落点。**

---

## 3. 桥 op 面复核（只看**能力**，不重新计数）

**问题**：op 面里有没有一个 op **起或停一个模式**？

**方法**：通读 `tools/editor-bridge/call-bridge.ps1` 的 `ValidateSet`（第 1 行）与
`tools/editor-bridge/ManagedBridge/BridgeServer.cs` 的 `case` 标签，**逐一**检查每个**可能**沾"模式/导航/起停"的 op。

**逐条判定（每一个都**不是**起停模式的 op）**：

| op | 看着像什么 | 实际是什么 | 是起停模式吗 |
|---|---|---|---|
| `start-log-observer` / `stop-log-observer`（`BridgeServer.cs:528,530`） | 起停"观察器" | 起停**被动的日志收包观察器**（观察包 1022），不改变任何模式 | **否** |
| `start-external-asset-observer`（`:525`） | 起停外部资产观察 | 被动观察器 | **否** |
| `open-editor-panel`（`:542`） | 打开面板 | 对**白名单内**两个 label（`节点管理器/资源管理器`）的菜单 Action 做 `DynamicInvoke`（`PanelOpen.cs:36,90`）；**这是"按一个按钮"，不是"置一个状态"** | **否** |
| `open-resource-manager` / `open-scene-resource-folder`（`:546-547`） | 打开面板 | 同上，走 `OpenEditorPanel` | **否** |
| `sync-editor-changes`（`:536`） | 全局同步 | 触发编辑器全局同步（内部 1014），返回体自带 `playtestVerified=false`（`EditorAdapter.cs:61`） | **否** |
| `command-probe`（`:540`） | 探测命令 | 只发一个**不可能存在**的命令名，源码显式 `knownCommandsSent=0` | **否** |
| `enable-debug-logging` / `request-debug-logs`（`:473-474`） | 可能起试玩 | 返回值**硬写** `startsPlaytest=false`（`EditorAdapter.cs:501,526`）——源码**刻意**否掉 | **否**（源码否证） |
| `stop`（`:677`） | 停 | **桥自己**的 listener 关闭（`BridgeServer.cs:677-683`：`"listener-stop-requested"`、`_lease.Cancel()`），与编辑器模式无关 | **否** |

**结论**：**op 面里没有**任何起/停"模式"或"试玩"的 op。这与 `INTERFACE-INVENTORY.md:392` 的既有负结论同向。

**桥能**观察**到的"运行态"信号（都很弱，且**没有一个**是"编辑器模式字段"）**：

- **游戏侧 `mode+0x1cc == 0xb993`**（`NativeSaveCatalogEvidence.cs:124,150`）——本仓**唯一**见到的、被断言为
  "编辑态"的内存常量。它属于 **`YuanShen.exe`**（游戏进程，不是编辑器），源码里**只当门禁用**（`Require(...)`，
  不满足即 `ARCHIVE_NOT_EDITING`），**值从不回传**，**从没被枚举**。⇒ **观察**都算不上程序化（只 fail-closed）。
- **包 1022 被动观察器**（`LevelInitObservation.cs:135-136`）——只在**收到**包 1022（关卡初始化）时记一笔
  （注释：*Only a received packet 1022 can advance this sequence. Polls never do.*），返回体硬写
  `reopenVerified=false, causalReloadVerified=false`（`:199`）。**能证"有一次加载发生过"，但不能区分"试玩"
  与"普通重载"，也不触发。**

⇒ **桥能"观察"的只有游戏侧字节与被动收包；编辑器侧没有任何模式字段可读、也没有可驱动的 setter。**

---

## 4. 判决（一个字）+ 唯一定案实验

### 4.1 判决

> **未知。**

- **能判死的一层**（据此，"bridge 面零入口"是**不能**）：§2 证明编辑器语料里**没有**可驱动/可观察的
  "编辑态/运行态"字段；§3 证明 op 面里**没有**起停模式/试玩的 op。⇒ **"把状态置位"这条路 = 不能。**
- **不能判死的一层**（据此，整体=**未知**）：**唯一不依赖状态字段的候选**——按下编辑器**自己的「试玩」菜单按钮**
  （`PanelOpen.cs:31-90` 的 `(label, Action)` 通路）——**从未执行**。声明一个符号搜不到，**不能**声明那条通路不存在。
  ⇒ 若"试玩"系统菜单项与 `节点管理器/资源管理器` 用**同一个** `(label, Action)` 类构造，则这条遍历**本就能枚举到它**
  （`ArchiveModel.cs:187` 注释：该遍历 *reaches the model layer **AND the menu***）。**这是悬而未决的唯一变量。**

### 4.2 唯一定案实验（**纯只读**；本轮不执行）

**P1 — 运行时只读枚举编辑器菜单项，看「试玩」在不在。**

- **做法**：新增一个**只读** op（如 `inspect-editor-menu`），复用 `PanelOpen.cs` 的同一条
  `WalkEditorGraph`（对每个带 label 字段 `MMGKX5coQC4` 的对象输出 `{label, actionPresent, actionTarget}`），
  **不进入** `PanelOpen.cs:90` 的 `DynamicInvoke` 分支。等价于把 `PanelOpen.cs:80-85` 的 `candidates` 单独取出。
- **判据（写死）**：
  - 存在 `label == "试玩"` 且 `actionPresent == true`（带 `Te1KXhuGxBC` 回调）⇒ 拿到**新符号**（`actionTarget`
    = `类::方法`），**capability 变为可推进**（下一步才是 P2：`DynamicInvoke` + 回看 `CurrentCaptions()` / 包 1022，
    且**必须用户在场**——可能触发一次真实试玩/上传，见 `watch-game-connection.ps1:11-13`）。
  - **不存在** `label == "试玩"` ⇒ 得到**新负结论**：「系统菜单与窗口菜单不同源」，菜单通路关闭，
    capability 收口为 **不能**（bridge 面）。
- **为什么它是最小**：纯读、零副作用（对照 `PanelOpen.cs:22-25`：开面板只改屏幕，而枚举连屏幕都不改）；一次
  dispatch 内完成；不碰游戏、不碰 `LocalLow`。
- **纪律**：`DynamicInvoke` 成功 ≠ 试玩启动（`PanelOpen.cs:105-106` 源码自证）——**P2 的判据必须是回看证据，
  不是 `ok:true`，也不是任何状态字段**（§3 已证没有这样的字段）。

---

## 5. 逐条引用（file:line）

- **resolved 语料**：`.runtime/editor-catalog/resolved/`（12375 `.cs`；本轮方法 A/B 单趟全扫）。
  - 单成员枚举空壳：`.runtime/editor-catalog/resolved/AGgaX4uL7dYv3IJyTI4F.XEKCwPuLuIbFcuaSycQR.cs`（`{Normal}`）；
    `…/SEBGj6uPIYTjcxgTBeC8.H4ENZduPkaQ5CTaa2ENJ.cs:1219-1245`（`editMode` 的 setter 只在 `==Normal` 落）。
  - `isEditing`（文本 VM）：`…/O1XvBAKJpNB6IglU2s7G.MvMDsBKJfguRrUWndHFQ.cs:76,84`。
  - `isDebugMode`：`…/qTNmk2u2oQWp5cxpL3mC.vhXqqMu29Z24tpvFGVMU.cs:82,90`；`…/SEBGj6uPIYTjcxgTBeC8.H4ENZduPkaQ5CTaa2ENJ.cs:1267,1441`。
  - `deleteMode`：`…/PndJBMuSx42kyh79sKL1.DYE3yjuSYLuDuB5FIQRw.cs:348,459`；`…/IGM4phuFSEJRrGVxhflB.SDrmqkuFCEYB66g31gcj.cs:156`。
  - `vmRadioBtnViewMode`：`…/z6bJHqKCG1FwPiBJfDLJ.M2bF6wKCnSaAHlvJtY0X.cs:132,140`。
  - `PlacementMode`（WPF）：`…/PJJTgIKXVQ92U0HEtPQP.Rg6OyVKXcOo6rjtD1pBB.cs:16,52`；`…/StOLR5KTE0N6gVHTs9eW.L2LMDrKTHJNYnsUcsZKH.cs:119`。
  - `Preview`（WPF 输入事件）：`…/BeyondEditor.ViewModelCore.FrameworkPropertyExtension.cs:165,185,277,361,568-571`。
- **桥 op 面**：`tools/editor-bridge/call-bridge.ps1:1`（`ValidateSet` 全表）；
  `tools/editor-bridge/ManagedBridge/BridgeServer.cs:473,474,525,528,530,536,540,542,546,547,677-683`；`EditorAdapter.cs:61,501,526`。
- **候选通路**：`tools/editor-bridge/Adapter/PanelOpen.cs:16,17,22-25,31,32,36,80-85,90,105-115`；
  `tools/editor-bridge/Adapter/ArchiveModel.cs:187`（遍历 *reaches the model layer AND the menu*）。
- **观察通道**：`tools/editor-bridge/Adapter/NativeSaveCatalogEvidence.cs:124,150`（`mode+0x1cc==0xb993` 门禁）；
  `tools/editor-bridge/Adapter/LevelInitObservation.cs:135-136,183,199`。
- **官方**：`.runtime/research-sources/official-docs/mhie54ik9ovg.txt`（试玩全章）；
  `docs/official-docs/PLAYTEST-CONTROL.json`（`whatIsNOTDocumented` / `returnToEditMode`）。
- **前序**：`docs/research/reverse-eng-20261010/OFFICIAL-PLAYTEST.md`、`…/PLAYTEST-CONTROL-MINE.md`、`…/EDITOR-STATE-MACHINE.md`；
  `docs/research/reverse-eng-20261010/INDEX.md:42,150-152,214,244-246`；`PRIMITIVE-VERDICTS.md:41,80`；
  `docs/editor-catalog/INTERFACE-INVENTORY.md:392`。

---

## 6. 对 INDEX / 前序文档的收口建议（只此一条，避免继续漂移）

`INDEX.md:42` 与 `PRIMITIVE-VERDICTS.md:41` 现写"起停试玩 = **不能**"。**建议改为**：
**不能（bridge 面：无 op、语料无可驱动状态字段）/ 未知（候选＝按下菜单「试玩」按钮的 `PanelOpen` 通路，P1 未执行）**。
理由：§2/§3 关闭的是"状态字段/op"这一层，不关闭"按 UI 按钮"这一层；后者的定案实验（§4.2 P1）从未跑过。

---

## 7. `notClaimed`

- 本轮**什么都没跑**：没有起 bridge、没有发原生/图请求、没有开游戏或编辑器、没有读写任何存档、没有读图片/PDF。
- **没有**证明系统菜单里**没有**「试玩」项——只证明了**本仓已提取的字符串里没有**（"搜不到"≠"不存在"）。
- **没有**证明「试玩」按钮能被 `DynamicInvoke` 到、更**没有**证明按下它就能进入试玩（P1/P2 未执行）。
- **没有**证明 `mode+0x1cc==0xb993` 就是"编辑态"；**没有**证明试玩会让它变值（P0 未执行）。
- §2 的负面只对**已提取的反编译语料 + 三种字符串/文本表**这一范围成立；**不解包 `assets.bin`**（主外壳中文文本
  疑在此，`UI-TEXT-INVENTORY.md:513,574`），也不覆盖运行时反射。

---

*本文件由 2026-10-10 会话只读整理：resolved 语料（12375 `.cs`）单趟全扫 + 桥源码通读 + 官方章 + 前序三报告。
未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档。*
