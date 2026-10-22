> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #3 挖 — `playtest.control`：后台起停试玩（离线逆向）

**产出日期**：2026-10-10
**类型**：离线逆向，只读。**本轮没有起 bridge、没有发任何原生/图请求、没有接触游戏或编辑器、没有读写任何 `LocalLow` 存档。**
**结论性质**：给出 **candidate + 能定案的实验**，**不声称任何能力可用**。

---

## 0. 一句话结论

`playtest.control`（`docs/NEW-FEATURE-PLAN.md:35,76` 的 C1）在本仓的当前逆向水平下**没有已证入口**，
且**不是**缺失一个「op」那么简单——它是**编辑器侧发起 + 编辑器侧校验/上传 + 游戏侧加载关卡**的三段组合：

1. **编辑器侧是 UI Action**：官方路径是「系统菜单 →【试玩】」这一个按钮（`mhie54ik9ovg` 逐字）。
   仓内的 op 面（见 tools/gameplan/tests/test_doctrine.py）里**没有 `start-playtest`**（`docs/editor-catalog/INTERFACE-INVENTORY.md:392`，
   本文件 §3 复核确认），bridge 对「进入运行态」**零写入口**。
2. **唯一的候选原语**是 `open-editor-panel` 用的那条**「读菜单项 (label, Action) 并 in-process 调用其
   Delegate」**的通路（`tools/editor-bridge/Adapter/PanelOpen.cs:31-90`）。它目前被**白名单**锁死在
   两个 label（`{"节点管理器","资源管理器"}`，`:36`）。**「试玩」是不是同一个 (label, Action) 形状的菜单项，
   从未被观测**——这是本任务最值得做的、成本最低的一个实验。
3. **游戏侧不是同一条机制**：`reopen-current` 是游戏进程内对一个固定函数指针的调用
   （`ReopenCurrent(levelManager, record, callback)`，`tools/game-executor/native/reopen_call.h:7`），
   **不经过编辑器、不做校验/上传**，且**前置要求就是「正处于编辑模式」**（`mode+0x1cc == 0xb993`，
   `tools/editor-bridge/Adapter/NativeSaveCatalogEvidence.cs:124`）——即 reopen 要求**留在编辑态**，
   而试玩要求**离开编辑态**。**两者方向相反，不是同一机制**（§4）。

---

## 1. 方法与口径

- **官方原文**：`.runtime/research-sources/official-docs/mhie54ik9ovg.txt`（试玩，8,352 字，与
  `docs/official-docs/PLAYTEST-CONTROL.json` 的同名 distil 一致）+ `mh9fj3rudd9q`（多人试玩）+
  `mhn4bsi5lb58`（整体界面，系统菜单命名）+ `mh0xm3ryh9hq`（风险检查，试玩校验的对照类别）。
- **编辑器侧**：`tools/editor-bridge/`（Adapter 的 op 实现；`ManagedBridge/BridgeServer.cs` 的
  case 标签（见 tools/gameplan/tests/test_doctrine.py），本文件逐条数过）。
- **游戏侧**：`tools/game-executor/`（`scene_cli.py` 的 `reopen-current`、`native/reopen_*.h`、
  `native_lifecycle_type.py`、`REOPEN-VERIFICATION.md`）。
- **先前台账**：`docs/editor-catalog/INTERFACE-INVENTORY.md`、`docs/NEW-FEATURE-PLAN.md`、
  `docs/gameplan/README.md` §五、`docs/research/reverse-eng-20261010/COMMAND-ROUTE-MAP.md`、
  `docs/ds-handoff/06-INTERFACE-VERIFICATION-QUEUE.json`（`playtest.control` 组合约）。
- **证据分级**沿用 `docs/editor-catalog/INTERFACE-INVENTORY.md:38-45`：`【已实测】`/`【静态证据】`/`【仅字符串】`/`【未知】`。

**三层口径（CLAUDE.md §一.3）**：本文件谈的几乎全是 ① 文档写了什么 与 ② 工具能做什么；
**③ 真机验证过什么 = 无**（试玩至今只有**人工**反馈，见 §2 末）。

---

## 2. `playtest` 机制上是什么（来自证据）

### 2.1 官方原文（`mhie54ik9ovg`，逐字）

| 面 | 逐字事实 |
|---|---|
| 入口 | 「功能入口 系统菜单——试玩」 |
| 硬限制 | 「多人试玩房间未解散时，无法进行试玩功能。」 |
| 校验 | 「点击【试玩】按钮后，会执行试玩**必要的校验和上传流程**，当检测到未满足条件时，将弹出**对应的错误码**供创作者(奇匠)检查。当所有检测条件都通过时，试玩流程将继续进行，弹出【试玩设置】窗口。」 |
| 流程 | 「试玩流程分为：**试玩前准备（上传，校验流程）——装扮展示——加载界面——进入关卡——结算关卡**」 |
| 局内控制 | 「处于试玩中时，可通过左上角退出按钮或 Esc 快捷键打开【试玩控制】面板」；三个选项 = **继续挑战 / 重新挑战 / 中断挑战** |
| 其它开关 | 试用奇偶、试玩时语言、**【启用试玩结算】关闭结算流程**、试玩数据引用「试玩临时数据」 |

**读完的可操作推论**：
- 试玩 = **编辑器主动离开编辑态**，流程含**外部依赖（上传）**，然后在**游戏里**加载同一关卡运行。
- 引擎侧的「校验」**只以弹窗错误码的形式出现**，官方页**没有**给出「运行结束后可读的校验报告」
  （`PLAYTEST-CONTROL.json` 的 `whatIsNOTDocumented`）。⇒ **别指望「试玩校验结果」是一份文件**；
  它更像一次**同步的门禁**。
- 官方页**从未**描述「退出试玩后如何回到编辑器」——`PLAYTEST-CONTROL.json:returnToEditMode` 明写
  **NOT COVERED**。⇒ 返回编辑态这一步，**连官方口径都是空的**。

### 2.2 编辑器进入的是什么态？（`编辑态 vs 运行态`）

- 官方对**编辑器**模式的命名：`mhn4bsi5lb58`「五、模式切换」列的是**编辑期的 4 个模式**
  （地形编辑 / 实体摆放 / 元件库 / 战斗预设）——**这是编辑态内部的模式，不是「编辑态 vs 运行态」**。
- 「运行态」这个词在官方语料里只以**节点可用性条件**的形式出现：`mhkirfrna1fy`
  「节点保持泛型状态**进入试玩**会导致节点不合法，在运行时不会正常执行」——即官方用「进入试玩 = 进入运行时」。
- **本仓 UI 文本表**有「试玩进行中」这一**状态面板**的证据：
  `docs/editor-catalog/UI-TEXT-INVENTORY.md:258,513` 记 `COSTLOAD_TESTING_TITLE → 试玩进行中`、
  `_NONEFORPROCESS_TEXT → …需要在开启负载测试的情况下进行试玩`。但同一文件 `:513` 明确
  **「试玩启动器 UI 文本不在本批资源」**，`:574` 更说明**主编辑器外壳的中文界面文本整体不在已提取字符串内**
  （二进制已混淆，很可能在**未解包的加密 `assets.bin`** 里）。
  ⇒ **「试玩」按钮的 label/文案，本仓静态资源里查不到**。这不影响 §3 的运行时枚举方案（那条路读的是内存对象，不是字符串）。

### 2.3 「真机验证过什么」= 无

本仓关于试玩的**唯一**业务证据全是**人工**：
`tools/game-executor/README.md:20`——「用户确认测试关卡官方检查未出错，并确认旧MVP开始/计时/掉落返回/通关结算
四项正常」；`docs/ds-handoff/06-INTERFACE-VERIFICATION-QUEUE.json` 的 `playtest.control` 组：
`priorEvidenceScopeNotRevalidated: "已有人工试玩反馈，自动控制未通过"`，
`priorRemainingNotRevalidated: ["官方校验结果读取","自动开始/停止","当前run标识","错误分支"]`。
另有旁证表明试玩**确实落到游戏进程 + 网络**：`tools/editor-bridge/watch-game-connection.ps1:11-13,34`
的注释直接写「the playtest upload step cannot reach the server」「the playtest is reported to fail during
its upload step」，并去 tail 游戏日志 `…/miHoYo/原神/LocalLog.log`（`:9`）。

---

## 3. 编辑器侧：有没有一个 bridge 能驱动的状态机？

### 3.1 op 面复核：桥的 op 面里，**零个**起停试玩

- 复核法（2026-10-10 本会话）：`grep -cE '^\s*case "' tools/editor-bridge/ManagedBridge/BridgeServer.cs` 数出 op 面大小。
  **此数不在此固化**——它是**派生物**，`tools/gameplan/tests/test_doctrine.py`（`BridgeOpCount`）每次从 `case` 标签
  重新导出并与 `CLAUDE.md` 对齐（照抄一个 grep 数字进文档会随新增 op 过期）。**本节结论（零个起停试玩）不依赖这个数字。**
- 其中与「面板 / 模式 / 导航」沾边的**全部** case（逐条看过）：
  `sync-editor-changes`（`:497`，派发 `:622`）、`command-probe`（`:501/:579`）、`open-editor-panel`
  （`:503/:581`）、`open-resource-manager`（`:507/:585`）、`open-scene-resource-folder`（`:508/:586`）、
  `focus-lab-cube-from-frontend`、`load-lab-cube-resource-model`、`load-scene-resource-model`、
  `inspect-frontend-commands`。
- **修正一条台账措辞**：`open-editor-panel` **不是**唯一的「面板 op」——`open-resource-manager`、
  `open-scene-resource-folder` 也是面板/资源树导航 op，且 `open-resource-manager` **走的是同一个方法**
  `OpenEditorPanel(resourceManager: true)`（`BridgeServer.cs:585`）。三者**都不是**「起停运行态」。
- **不是**入口的三个易误认项（都已在源码里显式否掉）：
  - `enable-debug-logging` / `request-debug-logs`：返回值硬写 `startsPlaytest=false`
    （`tools/editor-bridge/Adapter/EditorAdapter.cs:501` 与 `:526`），只构造日志报文 `3001`
    （`INTERFACE-INVENTORY.md:144,351`：「发出 ≠ ACK，**也不启动试玩**」）。
  - `sync-editor-changes`：触发编辑器**全局同步**（内部 1014），返回体自带
    `persistentSaveVerified=false, playtestVerified=false`（`EditorAdapter.cs:61`；`INTERFACE-INVENTORY.md:344`）。
  - `command-probe`：只发一个**不可能存在**的命令名 `__miliastra_probe_unknown_command__`
    （`COMMAND-ROUTE-MAP.md` §3 注 3；`CommandProbe.cs:144` 附近 `playtestVerified=false`），
    源码显式 `knownCommandsSent = 0`。
- **结论**：和 `INTERFACE-INVENTORY.md:392` 的既有负结论一致——**没有 `start-playtest`**；
  试玩**目前只由 UI 触发**。

### 3.2 唯一的候选原语：`open-editor-panel` 的「读菜单项 Delegate 并调用」

`tools/editor-bridge/Adapter/PanelOpen.cs` 做的是：
- 沿 `WalkEditorGraph(200000, 14)`（`PanelOpen.cs:51`）遍历**活的编辑器对象图**；
- 找任意**带 label 字段** `MMGKX5coQC4` 的对象（`PanelOpen.cs:31,58`）——编辑器把菜单项造成一个
  自定义类 `M9xFPCKX3nwCN5mCtXPs`（**不继承 `MenuItem`**），label 在 `MMGKX5coQC4`、callback 在
  `Te1KXhuGxBC`（`PanelOpen.cs:16,32`）；
- 对匹配 label 者取 `Te1KXhuGxBC` 的 `Delegate` 并 `DynamicInvoke()`（`PanelOpen.cs:89-90`）；
- 顺带把**遍历到的每个菜单项**记进 `candidates`，含 `label / actionPresent / actionTarget`
  （`PanelOpen.cs:80-85`）。

**为什么这条路可能通到「试玩」**：`WalkEditorGraph` 的 root 集**包含 `Application.Current` 与各
`Window`/`DataContext`/`Content`**（`ArchiveModel.cs:196-203`），且注释明写这条遍历
**「reaches the model layer AND the menu」**（`ArchiveModel.cs:187`）、菜单树靠 `mi.Items` 下钻
（`ArchiveModel.cs:236`）。而系统菜单与窗口菜单**同属编辑器外壳**。⇒ **若系统菜单项与
`节点管理器/资源管理器` 用同一个 `(label, Action)` 类构造，则同一条遍历本就能枚举到「试玩」**。

**为什么这仍只是 candidate**：
- `PanelOpenTargets` 是**硬白名单**（`PanelOpen.cs:36`），当前**只允许**两个 label；要触及「试玩」
  必须改白名单——但**在动手改之前，应先只读枚举**（§6）。
- 本仓**从未观测**系统菜单里「试玩」这一项的类身份 / 是否带 `Te1KXhuGxBC` 回调。
  `UI-TEXT-INVENTORY.md:513` 已判「试玩启动器 UI 文本不在本批资源」，所以**静态字符串侧无证据**；
  **唯一能定案的是运行时枚举**。
- 即便「试玩」被枚举到且能 `DynamicInvoke`，**那也只证明「一个 Delegate 被调用了」**——
  `PanelOpen.cs:105-115` 的注释自己就说：*invoking an action and reporting success proves only that a
  delegate ran; it does not prove the panel opened*。**调用 ≠ 进入试玩。**

### 3.3 有没有「编辑器状态机」可驱动？——只有一个**被动**观测器

- `Adapter/LevelLifecycleEvidence.cs` 的 `LevelLifecycleSnapshot()`（经 `EditorAdapter.cs:208` 暴露为
  `levelLifecycle`）只是**读编辑器保留的 7.1 初始化载荷头**里的 `levelIdCandidate`
  （`LevelLifecycleEvidence.cs` 内 `fieldPath = "YwCXahy5RIN.RmVRLESORxj.yoJRBJp4HeU"`），
  自报 `nativeMethodsInvoked=false, sentToGame=false, freshnessVerified=false, reloadInvoked=false,
  reopenVerified=false`。**这是读缓存，不是状态机，也不发起加载。**
- `Adapter/LevelInitObservation.cs` 是**被动的收包观察器**：只在收到**包类型 1022**（关卡初始化）时
  推进 `initSequence`（`LevelInitObservation.cs:135-136`，注释：*Only a received packet 1022 can advance this
  sequence. Polls never do.*），返回体默认 `reopenVerified=false, causalReloadVerified=false`
  （`:199`）。**它能「看见一次关卡初始化发生过」，但不触发它。**
  ⇒ 若试玩会引发一次关卡加载，**这个观察器可能是「试玩确实发生了」的最佳被动证据通道**——candidate，未证。
- **没有任何一处**在编辑器侧表示 `编辑态 / 运行态` 的枚举、模式字段或状态机（全 Adapter 只读检索，
  除以下几处 game 侧内存常量外，无 `mode/state/running` 语义字段，见 §4.2）。

---

## 4. 游戏侧：`playtest` 与 `reopen-current` 是不是同一条机制？

**答：不是。证据如下。**

### 4.1 `reopen-current` 是什么（游戏进程内的一次固定函数调用）

- 调用形状：`using ReopenCurrent = void (__cdecl *)(void* levelManager, void* record, void* callback);`
  （`tools/game-executor/native/reopen_call.h:7`）。
- 路由是一组**钉死的 YuanShen.exe 代码锚点**（`native/reopen_route.generated.h`，11 个 Anchor RVA，
  例：`0x13564e90 / 0x13564fa0 / 0x135665f0 / 0x77c9d70 / 0xcbe0220 / 0x11c06060 …`，外加 24 个 hotfix 字节位）。
- 它**不经过编辑器**：`docs/research/reverse-eng-20261010/COMMAND-ROUTE-MAP.md` §3 末明写
  「`tools/game-executor/`：**零命中**。38 个命令名、7 个服务名、派发器 `Ikci0qkvMZX` 在该目录下
  一条都不出现。game-executor 走的是**另一条传输**（原生 / pipe / scene_cli），不经过编辑器的命令通道」。
- 前置条件即「**留在编辑态**」：`grep 81 ba cc 01 00 00 93 b9 00 00`（`cmp dword [rdx+0x1cc], 0xb993`）
  出现在 `reopen_route.generated.h` 的第 3 个锚点里；同一常量在
  `NativeSaveCatalogEvidence.cs:124` 被写作门禁：
  `Require(reader.U32(mode+0x1cc)==0xb993 && reader.Read(level+0xc9,1)[0]==1, "ARCHIVE_NOT_EDITING");`
  ——**reopen 只在「编辑态」下允许**。
- 它自报不做试玩：`REOPEN-VERIFICATION.md`「2026-09-29 本次实测边界」段——
  「**本次没有执行初始化或重开**」；`scene_cli.py:711` 的收口固定 `reopenVerified=False`。

### 4.2 因此两者的关系

| | `playtest` | `reopen-current` |
|---|---|---|
| 发起方 | **编辑器**（系统菜单按钮，官方原文） | **本工程原生助手**（游戏进程内调用） |
| 经过编辑器命令通道 | 是（编辑器 UI 驱动） | **否**（`COMMAND-ROUTE-MAP.md` §3 末） |
| 校验 / 上传 | **有**（官方：「必要的校验和上传流程」；旁证 `watch-game-connection.ps1:11-13`） | **无** |
| 目标状态 | **离开编辑态**，进入运行态（加载界面→进入关卡） | **留在编辑态**（门禁 `mode+0x1cc==0xb993`） |
| 是否可被本仓自动触发 | **否**（无 op、无符号、UI-only） | 有既定受限入口，但**尚未闭环成功**（`REOPEN-VERIFICATION.md` 末段） |

**`reopen-current` 最多算「把当前关卡重新加载一遍」，它是「试玩」的**可能子步骤**（加载关卡那一段），
**但不是「试玩」本身**：它不做校验/上传、不切换编辑态→运行态，且方向相反。**
`docs/research/.../COMMAND-ROUTE-MAP.md` §2.2 另有一条**名字相关但非控制面**的命令：
`ImportPerformanceReport`（id 31，`beyondExportService`，matched）——那是**导入游戏侧性能报告**的下行命令
（对应多元试玩结束生成的 `Beyond_Performance_Report`，`docs/official-docs/MULTIPLAYER-PLAYTEST.json`），
**不是起停试玩**。

---

## 5. (b) 有没有现成原语是「朝它走的一步」？

按「离可用有多近」排序：

1. **`open-editor-panel` 的菜单 Action 调用通路**（`PanelOpen.cs:31-90`）——**最近的一步，且是唯一
   可能真正「按下试玩按钮」的机制**。它已在真机上跑通过（它能打开 `节点管理器`/`资源管理器`）。
   **缺口 = 一次运行时枚举**（§6.1）。风险：系统菜单项未必用同一 `(label, Action)` 类；即便同源，
   `DynamicInvoke` 成功 ≠ 进入试玩。
2. **包 1022 被动观察器**（`LevelInitObservation.cs:135-136,183`）——**「试玩是否发生了」的候选证据通道**。
   若试玩会引发一次关卡初始化，它可能记下一次 1022。**未证**：目前从未在试玩场景下跑过。
3. **游戏侧 `mode+0x1cc` 字段**（`NativeSaveCatalogEvidence.cs:122,124,150`）——**候选的「编辑态 vs 运行态」
   判别位**。它是本仓**唯一**见过的、被断言为「编辑态」的游戏内存常量（`0xb993`）。
   `NativeSaveCatalogEvidence` 把 `mode` 与 `level+0xc9`（值 1）**在快照期间要求保持不变**
   （`:150` ARCHIVE_ROOTS_CHANGED）——说明这**是个会变的运行态字段**，值得跨状态读一次。
   **未证**：`0xb993` 到底对应「编辑态」还是别的（源码只把它当断言用，没有枚举它）。
4. **`LevelLifecycleSnapshot()`**（`LevelLifecycleEvidence.cs`）——只读**编辑器保留的 levelId**，
   不发起加载，不算「一步」。

**明确不是一步的**：`enable-debug-logging` / `request-debug-logs` / `sync-editor-changes` /
`command-probe`（§3.1 已逐条否掉）。

---

## 6. (c) 最小的探针（candidate + 能定案的实验）

**按「只读 → 有界写」阶梯排列。全部未执行。**

### 6.1 探针 P1（**只读，优先做**）：运行时枚举编辑器菜单项，看「试玩」在不在

- **做法**：新增一个**只读** bridge op（例如 `inspect-editor-menu`），复用 `PanelOpen.cs:51` 的同一条
  `WalkEditorGraph(200000, 14)`，但**只收集 label**：对每个带 `MMGKX5coQC4` 的对象输出
  `{label, actionPresent, actionTarget}`——**不 `DynamicInvoke`**。（等价于把 `PanelOpen.cs:80-85` 的
  `candidates` 单独取出来，而不进入 `:89` 的调用分支。）
- **能定案的问题**：
  - 系统菜单里有没有 label == `试玩`（以及 `多人试玩`）的项？
  - 若有，它带不带 `Te1KXhuGxBC` 回调（`actionPresent`）？`actionTarget` 指向哪个
    `类::方法`（这本身就是一个**新的、可用的绑定符号**）？
- **为什么它是最小**：纯读，零副作用（对照 `PanelOpen.cs:22-25`「Opening a panel changes what is on screen.
  Nothing else.」——而枚举连屏幕都不改）；一次 dispatch 内完成；不碰游戏、不碰 `LocalLow`。
- **产物**：`label === "试玩"` 的候选清单 + `actionTarget` 字符串。**这决定 P2 是否值得做。**

### 6.2 探针 P2（**有界写，仅在 P1 命中后**）：`DynamicInvoke` 那个 Action，然后**只读回看**

- **做法**：把 `试玩` 加进 `PanelOpenTargets`（或走一个新的 `invoke-editor-menu(label)` op），调用其
  Delegate；随后**只读**回看两样东西：
  (a) `CurrentCaptions()`（`PanelOpen.cs:109`）里是否出现「试玩设置」「试玩校验」「错误码」等字；
  (b) **包 1022 观察器**（`LevelInitObservation`）是否记下一次 init；必要时加读游戏侧
  `mode+0x1cc` / `level+0xc9`（§5.3）。
- **必须写成 candidate**：`PanelOpen.cs:105-107` 的注释已经定性——*调用一个 Delegate，只证明一个
  delegate 跑了*。⇒ 判定标准**必须**是「回看证据」，不是 `ok:true`。
- **风险**：这可能真的把编辑器推进试玩（含**上传**，外部依赖，见 `watch-game-connection.ps1`）。
  ⇒ P2 需要用户在场、且明确知晓「可能触发一次真实试玩/上传」。**本轮不执行。**

### 6.3 探针 P0（**纯只读、与上面解耦、可独立做**）：跨状态读游戏侧 `mode+0x1cc`

- **做法**：复用 `NativeSaveCatalogEvidence` 的 read-only `Reader`，在**用户手工点一次试玩**的前/后，
  各读一次 `global+0xa440 → +0x1cc`（以及 `level+0xc9`、`level+0x98`），记录值。
- **能定案**：`0xb993` 是否是「编辑态」；试玩期间它是否变成别的值。若是，则本仓**第一次**有了一个
  **可读的「进入了运行态」判别位**——这本身就补上 `playtest.control` 的「当前 run 标识」一类缺口。
- **【纪律提醒】** 该探针在 `NativeSaveCatalogEvidence.cs:22-23` 的会话常量
  （`PID 9340/47028`、镜像哈希）**全部过期**，直接复用会 fail-closed。新会话必须先 discover，
  **不要复用本文里的任何 PID / 哈希 / 关卡号**（CLAUDE.md §四）。

---

## 7. 负结论（本文件真正交付的东西）

1. **bridge 面：`playtest.control` 没有入口，且不是「少一个 op」**——桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）零命中，
   `startsPlaytest=false` 是源码里**刻意**写下的断言（`EditorAdapter.cs:501,526`）。
   任何「3001 报文能起试玩」的说法都是**已被源码否掉的**。
2. **官方面：试玩校验结果**以**弹窗错误码**呈现，**官方从不提供运行后可读的报告**
   （`PLAYTEST-CONTROL.json`）；**返回编辑态**这一步官方**根本没写**。
   ⇒ 这个 capability 的验收判据可能需要接受「**校验跑过了**」而不是「**校验被读到了**」。
3. **游戏面：`reopen-current` ≠ `playtest`**——前者要求**留在编辑态**（`mode+0x1cc==0xb993`），
   后者要求**离开编辑态**；前者无校验/上传，后者有；两者走**不同传输**。
4. **静态资源面：「试玩」按钮文案在本仓查不到**（`UI-TEXT-INVENTORY.md:513,574`：主外壳中文文本不在
   已提取字符串内，疑在**未解包的加密 `assets.bin`**）。⇒ 静态字符串枚举这条路**不可用**；
   **只能走运行时对象枚举**（P1）。
5. **唯一的新挖点**是**运行时枚举菜单项**（P1）——它要么拿到一个新符号（`试玩` 的 `actionTarget`），
   要么给出「系统菜单与窗口菜单不同源」这个**新的负结论**。两种结果都是进展。

---

## 8. 逐条引用（file:line）

- 官方：`.runtime/research-sources/official-docs/mhie54ik9ovg.txt`（试玩全文）；
  `docs/official-docs/PLAYTEST-CONTROL.json`（distil，含 `whatIsNOTDocumented` / `returnToEditMode`）；
  `docs/official-docs/MULTIPLAYER-PLAYTEST.json`（`Beyond_Performance_Report` / 邀请制）；
  `docs/official-docs/INDEX.json`（`mhie54ik9ovg` = playtest.control 主源）。
- 编辑器 op 面：`tools/editor-bridge/ManagedBridge/BridgeServer.cs:497,501,503,507,508,622,581,585,586`
  + `case` 现值（见 tools/gameplan/tests/test_doctrine.py）；`tools/editor-bridge/Adapter/EditorAdapter.cs:61,208,501,526`；
  `tools/editor-bridge/Adapter/PanelOpen.cs:16,31,32,36,51,58,80-90,105-115`；
  `tools/editor-bridge/Adapter/ArchiveModel.cs:187,196-203,236`；
  `tools/editor-bridge/Adapter/LevelLifecycleEvidence.cs`（`LevelLifecycleSnapshot`）；
  `tools/editor-bridge/Adapter/LevelInitObservation.cs:135-136,183,199`；
  `tools/editor-bridge/Adapter/CommandProbe.cs:144`。
- 台账：`docs/editor-catalog/INTERFACE-INVENTORY.md:32,38-45,144,344,351,392,591,603`；
  `docs/editor-catalog/UI-TEXT-INVENTORY.md:256-258,513,514,574`；
  `docs/editor-catalog/OFFICIAL-FUNCTION-INVENTORY.md:120,355,588`；
  `docs/NEW-FEATURE-PLAN.md:35,76`；`docs/gameplan/README.md:93-131`；`docs/PROGRESS-BY-FUNCTION.md:58`；
  `docs/research/reverse-eng-20261010/COMMAND-ROUTE-MAP.md` §2.2 id31、§3 末段；
  `docs/ds-handoff/06-INTERFACE-VERIFICATION-QUEUE.json`（`playtest.control` 组）。
- 游戏侧：`tools/game-executor/native/reopen_call.h:7`；
  `tools/game-executor/native/reopen_route.generated.h`（Anchor 3 的 `b9 93` 比较）；
  `tools/editor-bridge/Adapter/NativeSaveCatalogEvidence.cs:122,124,150`；
  `tools/game-executor/REOPEN-VERIFICATION.md`（2026-09-29 边界）；
  `tools/game-executor/README.md:20`；`tools/editor-bridge/watch-game-connection.ps1:9,11-13,34`。

---

## 9. `notClaimed`

- 本轮**什么都没跑**：没有起 bridge、没有发原生/图请求、没有开游戏或编辑器、没有读写任何存档。
- 没有证明 `open-editor-panel` 的通路能到达「试玩」；P1 是**尚未执行的**实验。
- 没有证明包 1022 会在试玩时出现；没有证明 `mode+0x1cc==0xb993` 就是「编辑态」。
- 「一个 Delegate 被调用」**不等于**「试玩启动了」——判定必须靠回看证据（P2）。
