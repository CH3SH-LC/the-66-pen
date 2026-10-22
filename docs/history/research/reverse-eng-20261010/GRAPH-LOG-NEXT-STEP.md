> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #7 挖 — 图日志那条路：从 #3/#4 再往前一步，下一步该做哪个动作

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档、未读任何图片**。
证据来源三处：① 仓内桥 C# 源码（`tools/editor-bridge/`）② `.runtime/` 下的**反编译语料**（`editor-catalog/resolved`、`editor-bridge/control-research`、`editor-bridge/scene-context`）与**真实回执原件**（`editor-bridge/runs/`；用 Bash `grep`/`find`/`sed`，**Grep 工具会静默跳过 `.runtime/`**，见 `CLAUDE.md` §一.2）③ 姊妹文件 `GRAPH-RUNTIME-VERIFY-MINE.md`（#3）、`GRAPH-LOG-SHAPE.md`（#4）。
**本文件只新增自身**，不改其它任何文件、不改任何代码。

> 按 `CLAUDE.md` §一.3、§五：`文档写了什么` / `工具能做什么` / `真机验证过什么` 三层分开标。
> **本文件新增的核心事实全部来自反编译源码**（对象是 `resolved/*.cs` 的字段号），**真机层未新增任何实验**。
> **「搜不到」≠「不存在」**：凡负面结论都写明检索范围。

---

## 0. 一句话结论

- 姊妹 #3 的判定（**这 5 个 op 按原样跑翻不动 `runtimeVerified`**）**我复核后同意**，且它列出的四条「`=0`」我**独立复算全部成立**（§1.1）。
- 但 #3 把**卡点的位置放偏了**。真正卡住闭环的不是「记录认不回自己的图」，而是**桥从来没有去读记录里那两个能认出图的字段**：
  - 记录**自带**一个 `{value:enum, graphId:uint}` 子消息（proto 58，字段 `eNLa2VJUc8d`），其类型 `uBi4l34XLv2OekpES2JT.auKUt14Xhrb73Hx3I35G` **与 3001 选择表里每一条用的类型是同一个**（§2.2）。桥**一个字节都没读它**（§2.2，全 Adapter `grep` = 0）。
  - 「正文文本」的载体（`L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB`）除了那个被读的 `string`（proto 18），**自己还带一个 `ulong`（proto 8）**。桥同样没读（§2.1）。
  - ⇒ #3 §5.5 说「要么先探明我们的图在记录里叫什么」——**答案是：记录里本来就写着图 id，只是桥没伸手去拿**。
- 另有 **4 处口径更正**：#3 把「RPC 没回」与「RPC 回了但内容为空」混为一谈（真机上有 **45 次 matched**，§2.4）；把 `acknowledged:false` 当信号检索（它其实是**返回体里的硬编码字面量**，天然 `=0`，§2.5）；漏了 `debugLogReply` 读者**按 `IsPrimitive||IsEnum` 过滤**这条潜在盲点（§2.3）；漏了观察窗的两道截断（§2.6）。
- **下一个动作（本文件的正面交付，§4）**：把**记录自带的 proto 58 `graphId`**读出来——具体是**加宽 `RunLogSample.cs:38-79` 的 `CaptureRunLogRecord`**，再跑**一次** `start-external-asset-observer` →（试玩可选）→ `log-observer-evidence`，看**任何一条被捕获记录的 proto-58 `graphId` 是否等于桥自己选过的图 id（`1073741825`/`1073741826`…）**。这一读**不需要超时窗口、不需要唯一 marker、不需要负对照**，且**能解释已有数据**：#4 §3.3 里那条 `bodyText=="MW_CALIBRATION_PLATFORM_CREATED_20260916"` 的记录，**它的 proto-58 graphId 是不是 `1073741825`**——这个问题今天就能问，答案只差一次代码加宽。
- **路没关，但胜负手不在「多跑几次」，而在「多读两个字段」。**

---

## 1. 姊妹任务：证到了什么 vs 只是假设

### 1.1 #3 已**证明**的（我逐条独立复算，**全部成立**）

| # | 论断 | 我的复核（范围：`.runtime/editor-bridge/runs/`） |
|---|---|---|
| P1 | 5 个 op 的标签/派发/实现位置 | 源码直读，`BridgeServer.cs:434,435,436,489,490,491` / `592,593,594,614,615,616`；`EditorAdapter.cs` 各段——**同意** |
| P2 | `log-observer-evidence-response.json` 有 41 份 | `find … -name log-observer-evidence-response.json \| wc -l` = **41**（run 目录 **454** 个）——**同意** |
| P3 | 有真实「图名 + 打印文本」结构化记录 | #3 §3.3 原件（run `10f68791`）——**同意**（本文件 §4 依赖它） |
| P4 | `runtimeVerified`/`playtestVerified`/`runtimeSemanticsVerified` `:true` = **0** | 我用 `grep -rl … \| wc -l` 独立复算，三者**均为 0**——**同意** |
| P5 | `"acknowledged":true` = 0；`"debugLogRpcSuccess":true` = 0；非空 `debugLogReply` = 0 | 独立复算，**三者均为 0**——**同意** |
| P6 | `positionPrints` 恒 0、「按图名认领」从未成功 | #3 §3.2/§3.4 + #4 §3.2——**同意** |

### 1.2 #3/#4 **只是假设**、**尚未证**的（不得当事实引用）

| # | 假设 | 状态 |
|---|---|---|
| H1 | `graphName` 段值（`47504-100000001-<uint>-<n>`）是「建图时刻」 | #3 §4.1 **自陈**为「与 Unix 秒吻合」的**中性**推断，未证；本文件不采用 |
| H2 | 这批记录是**历史缓存回放**（而非本次重跑） | #3 §4.2 **明确写「本轮证据不足以二选一」**——**未决** |
| H3 | `positionPrints` 恒 0 的根因是「身份判据错」 | #3 §5.5 说法合理，但「记录的名字槽装的是什么」**未证**（§2.2 给出一个可证路径） |
| H4 | 「唯一 marker + 负对照」能定案 | #3 §5 / #4 §4.3 是**未执行、可反驳的计划**；本身未证 |
| H5 | 这 5 个 op 能关闭「试玩→反馈」回路 | #3 §5.1 结论是**条件式**（「补上判据后**有资格**」），非既成事实 |

> ⇒ 结论：**姊妹文件把「通道形状」证清楚了，把「卡点在哪」判断偏了。** 下面 §2 是偏移量。

---

## 2. 我读源码新增的「一条记录里到底有什么」（#3/#4 未提）

### 2.1 正文文本的载体**自己还带一个 `ulong`**，桥只读其中的 `string`

桥把「打印文本」定义为一个**已知文本载体类型**（`RunLogSample.cs:33` `RunLogTextBodyType => B("L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB")`），并只读它**一个**字符串字段（`RunLogSample.cs:34` `RunLogTextField => B("wmmat7vdE8l")`；读法 `:62-66`）。

反编译该载体本体（`.runtime/editor-bridge/scene-context/printed-log-proto.cs`，类名即 `L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- 字段声明：`printed-log-proto.cs:18,20`；`WriteTo` 里 **`…(P_0, 8, …)`**（`ulong` 分支）与 **`…(P_0, 18, …)`**（`string` 分支）：`:209-224` 与 `:236-256`。
- ⇒ **一条「打印」记录的正文 = `{8: ulong, 18: string}`**。桥读走了 `string`，**`ulong`（proto 8）原封不动丢掉**。
- **全 Adapter `grep`（`fesatummSfZ`/`Pmqat087ZgS`/`RDcati8XHI9`）= 0 命中** ⇒ 桥从不读它。
- 这是「记录里有没有节点 id」的一个**新的、具体**的候选位（记忆 `node-ids-two-namespaces`：离线资源 id 正是 **64 位**，与 `ulong` 同宽）。**是否 = 打印点/节点 id：未证**（不排除是打印序号、时间戳或别的）。

### 2.2 记录**自带**一个 `{value:enum, graphId:uint}` 子消息，且类型与 3001 选择表**同源**

- 记录类型 `HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD` 的字段声明（`resolved/HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD.cs:42-66`）里有一行：
  `private auKUt14Xhrb73Hx3I35G eNLa2VJUc8d;`（`:54`）。
- 该字段对应 **proto 号 58**：`WriteTo` 的 `zl7BAmYcpc3BceR7oifv.xyVYfsr3qg0(P_0, 58, …)` + 取值器 `ujOa27JlDqn`（同文件 `:874-876`）。
- `auKUt14Xhrb73Hx3I35G` 的**本体**（`.runtime/editor-bridge/control-research/log-selector-proto.cs:14-20`）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- 而 **3001 选择表里每一条就是这个类型**：`GraphLogSelection.cs:23` `LogSelectionProtoType => B("uBi4l34XLv2OekpES2JT.auKUt14Xhrb73Hx3I35G")`，字段访问器 `:29-30`（`mQ44XjcStXy`=value、`SK14XFvgrVC`=graphId）。原生写侧同型：`log-selection-annotated.cs:298-301`（`(O64cM60CDshW0fYqf34D)1` + `current` + `Add`）。
- ⇒ **记录里的 proto 58 和桥发出去的「我要选哪张图」用的是同一个 proto 类型**：`{value:enum(1), graphId:uint}`。**最省事的解释是：proto 58 = 这条记录由哪张图（graphId）发出。**
  - **这是假设，不是事实**（语义未证）。但它**可在一次真机观察里被证伪**（§4：把 `graphId` 读出来，与桥选过的 id 对照）。
- **全 Adapter `grep`（`eNLa2VJUc8d`/`ujOa27JnDqn` 段 → 见 §8 引用）= 0 命中** ⇒ 桥**从不读 proto 58**。

> **这一条直接回答 #3 §5.5 悬着的问题**：「我们的图在记录里叫什么」——**记录里不只有名字，还有一个 `graphId`**。桥过去把整条命押在「名字精确匹配」上（`PositionLogs.cs:21`），而名字槽里装的恰恰是**运行实例 id**（#3 §3.3）——**却把旁边那个真正的 id 字段放着没读**。

### 2.3 `debugLogReply` 的读者**按 `IsPrimitive||IsEnum` 过滤**——潜在盲点（会丢 string / byte[]）

`RequestDebugLogs` 的回调类型是 `Action<List<Param>>`（`EditorAdapter.cs:510-515`），其中 `Param` = `EditorAdapter.cs:16` `B("yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv")`。

而 `Param` 是一个**带 tag 的变体结构体**（`resolved/yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv.cs:9-24`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


静态工厂给出 tag 语义（`resolved/…IxtFOgiA4qhGnLhEyLFv.cs:27-165`）：
`1→uint`、`2→int`、`3→bool`、`4→float`、**`5→string`（写 `utWiAPiKWGv`）**、`6→uint`、**`7→byte[]`（写 `WWfiA8389CN`）**。

回调读者（`EditorAdapter.cs:460-470`）只留下：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- `string` **不是** `IsPrimitive`；`byte[]` 也不是。⇒ **若某次回复里带的是字符串或字节（一个「导出日志」最可能的载荷形态），读者会把内容整个丢掉，只留下 tag=5/7 的壳**。
- **口径纠正**：这不是 #3 那条「`debugLogReply` 为空」的成因（当前是**空列表 `[]`**，即上游根本没产出元素，§2.4）。这是**潜在**盲点——**一旦上游开始返回文本，它就会咬人**。#3 没提，应当在改读者时一并处理。

### 2.4 口径更正：`request-debug-logs` 的 RPC **被答过 45 次**，不是「没回」

#3 §3.4/§6.2 写「主动拉日志从未返回内容 / never succeeded」。精确事实（我独立 `grep`，范围 `.runtime/editor-bridge/runs/`）：

| 字段 | 取值分布 | 含义 |
|---|---|---|
| `"debugLogRpcMatchedResponses"` | **1 × 45 份**；0 × 368 份 | **reply id 匹配上了我们的 request id**（匹配逻辑 `NativeRpcEvidence.cs:29-37`，要求 `replyId==requestId`） |
| `"debugLogRpcSuccess"` | **false × 45**；null × 368 | 匹配上的那 45 次，回复里那个 **bool 字段 = false** |
| `"debugLogReply"` | `null` × 386；`[]` × 66（+ 带空格 2） | 回调**要么没被调用**（null）、**要么被调用但列表为空**（`[]`） |

- ⇒ 准确表述是：**RPC 往返是通的（45 次 matched），但那 45 次里回复带 `false`；载荷列表为空/未回调**。
- **那个 bool 到底是不是「成功」——未证**：`NativeRpcEvidence.cs:8` 自陈原生字段名是 `y9iazq3HFOv`、无注释；桥给它起了 `debugLogRpcSuccess` 这个名字，**命名是桥的假设，不是原生语义**。
- **对下一步的意义**：`ImportAllDebugLog` 这条路**不是「无回执」的死路，而是「有回执、但产出空」**——判别这两者决定了「该修读者还是该换 op」。

### 2.5 口径更正：`acknowledged:false` 是**硬编码字面量**，检索它天然 `=0`

`enable-own-graph-logging` 的返回体（`EditorAdapter.cs:499-501`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- `acknowledged` **从来没被读过任何原生 ACK**，它是**写死的 `false`**（`startsPlaytest=false` 同理）。
- ⇒ #3 §3.4/§6.3 用「`"acknowledged":true` 全检索 = 0」当负证据，**是空证据**（该串物理上不可能出现）。同理 3001 的外层 payload 本体 `uY432DaSLO9E1Pagl8Y2.SNYUqraShudVtwQSLBmO` **只有内层一个字段**（`log-control-proto.cs:22` `private bNf3IEaS4GdguXca3eut doEaSUah24B;`），**压根没有 ack 槽**——「3001 未被 ACK」这句话在**消息形状层面**就无从谈起。
- **修正后的结论**：#3 该条的**结论（3001 不能当试玩控制）仍成立**（因为 `startsPlaytest=false` 是设计断言），但**论据（`acknowledged` 检索）无效**。

### 2.6 观察窗的两道截断（会把「新鲜的那些」挤掉）

- 观察器**只扫前 32 个日志包**：`EditorAdapter.cs:380-381`（`observedLogPackets++` 之后 `if(observedLogPackets>32){observerScanLimited=true;return;}`）——**第 33 个包起只计数、不扫描**。
- 记录样本**只留前 64 行**：`RunLogSample.cs:24,58`（`RunLogSampleLimit=64`，满了置 `sampleLimited`）。
- ⇒ 若一次试玩开头的 32 个日志包/64 行**是历史回放**，**本次新鲜的打印会被这两道门挡在外面**。#3 提到过 64 上限的**存在**（§1.2 引 `RunLogSample.cs:24`），但没把它接到「H2 历史回放 vs 本次重跑」这个判据上——**这正好是一个「即使不补 marker 也可能误判」的陷阱**（细节：先到先得，不回填）。

---

## 3. 判定：路没关，但卡点要重新定位

| 命题 | 判定 | 依据 |
|---|---|---|
| 这 5 个 op 是唯一的「运行态观察」通道 | **成立**（源码 + 41 份回执） | §1.1 |
| 按原样跑能翻 `runtimeVerified` | **不能** | #3 §5.1 + §1.1 P4/P5 |
| 「图身份」问题是死结 | **不是**：记录自带 proto 58 `graphId`（未读） | §2.2 |
| 「历史回放 vs 本次」不可判 | **待判**：但有一道**未读的 id**（§2.2）与两道**未计入判据的截断**（§2.6） | §2.2/§2.6 |
| `request-debug-logs` 是死路 | **不是「没回」，是「回而空」** | §2.4 |

⇒ **闭环的唯一未解问题不是「有没有记录」，而是「这条记录属于谁、属于哪一次」。** 这两个问题都指向**同一处还没伸的手**：把记录自己带的 id 读出来。

---

## 4. 单一下一步动作（本文件的正面交付）

### 4.1 动作一句话

> **加宽 `CaptureRunLogRecord` 只读**，让它把**记录自带的 proto 58 `graphId`**（必要时连同**正文载体的 proto-8 `ulong`**）落到样本行里；然后跑**一次** `start-external-asset-observer`（120s）→（**试玩可选**）→ `log-observer-evidence`，回答一句是非题：
> **「那些被打出来的自有图文本（例如 `#4 §3.3` 的 `MW_CALIBRATION_PLATFORM_CREATED_20260916`）所在记录，其 proto-58 `graphId` 是否等于桥选过的图 id（`1073741825` / `1073741826`）？」**

### 4.2 为什么是**这一个**（而不是 #3 的唯一-marker 实验）

1. **它不需要「本次试玩」就有答案**：`#3 §3.3` 已经收到过带**我们自有 marker 文本**的记录——那条记录的 proto 58 **今天就能读**（历史回放记录同样带字段）。**先回答「认领」问题，再谈「新鲜度」问题**，顺序更省。
2. **它一次性消掉 #3 的两大前置**：若 `graphId` 命中，则「按图名认领」（`PositionLogs.cs:21`）**根本不必要**——不需要唯一 marker（#3 §5.2 前置 3）、不需要负对照（#3 §5.4 D3）。判据从「文本唯一性反推节点」升级为「id 直接认领图」。
3. **它无需另起 scope**：`start-external-asset-observer` + `log-observer-evidence` 是**只读**观察 op，不触发 `logEnableAttempted`/`logRequestAttempted` 的一次性闸（`EditorAdapter.cs:476,505`），**可重复**（每个 scope 一次租约 120s）。
4. **失败也可判**：若 `graphId` 恒 0、或恒不等于所选 id、或字段根本不在 payload 里出现，则 **proto 58 ≠ 归属键 被证伪**，此时才退回 #3 的「唯一 marker + 负对照」——**路径收敛而非打转**。

### 4.3 具体到「哪个 op、什么参数、期望回复形状」

**代码侧（唯一改动，离线可规划）**
- 文件：`tools/editor-bridge/Adapter/RunLogSample.cs`，方法 `CaptureRunLogRecord`（`:38-79`）。
- 在 `:70` 那个匿名对象里**新增两个字段**（读法沿用既有反射风格，`Field(obj, B("…"))`）：
  - `recordGraphId` ← 取记录字段 `B("eNLa2VJUc8d")`（proto 58，`resolved/…fRTMHcaSSKjG5j3IhYLD.cs:54,874-876`）；再取它的 `B("SK14XFvgrVC")`（graphId，`log-selector-proto.cs:20`，访问器名与 `GraphLogSelection.cs:30` 同）。
  - `bodyPayloadId` ← **仅当** `bodyTextReadable` 时，取正文载体的 `B("fesatummSfZ")`（proto 8 `ulong`，`printed-log-proto.cs:18`）。
  - 两者都**只读、不解析语义**，读不到就写 `null`（`Claude.md` §五：读不出就写读不出，别猜）。
- **同时**（顺手，成本几乎为零）：放宽 `EditorAdapter.cs:464-466` 的过滤，把 `string`/`byte[]` 也带进 `debugLogReply`（§2.3）——这只影响**另一条 op**，不改变本动作的判据。
- **纪律**：改动**未编译前一律标 `只离线`**；不声称任何新能力（`CLAUDE.md` §提示：未编译的适配器是候选）。

**运行侧（离线写死，执行与否由人决定）**

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- 落点：`.runtime/editor-bridge/runs/<RunId>/log-observer-evidence-response.json`（`call-bridge.ps1` 自动写）。
- **注意**：`start-external-asset-observer` 同样会挂 1022/1017 观察器，但**不**发 3001（§2.5 的 enable 闸不受影响）。

### 4.4 判据：**回复形状 → 结论**（三种都落盘）

看 `log-observer-evidence-response.json` 的 `runLogSample.sample[*]`：

| 观察到的形状 | 结论（才有资格说） |
|---|---|
| 存在某行 `bodyTextReadable==true` **且** `graphName=="MW_Calibration…"/"MW_Route_Tiled…"`（旧字段） **或** `recordGraphId ∈ {1073741825,1073741826}` | **proto 58 = 归属键 成立** ⇒ 「哪个图跑了」可**按 id 直接认领**，**不再需要唯一 marker/负对照**。→ 下一步：一次人工试玩 + 在同 `recordGraphId` 下找目标节点的打印文本 = **节点级运行证据** |
| `recordGraphId` 恒 0 / 恒同一非所选值 / 字段读成 `null`（名字槽对不上、`recordsWithNoGraphName>0`） | **proto 58 不是归属键**（证伪）⇒ **退回 #3 的「唯一 marker + 负对照」**；同时报告 `bodyPayloadId` 是否为非零稳定值（是否像打印点 id） |
| `recordsSeen==0` 或 `sampleLimited==true` 或 `observedLogPackets` 撞上 32（§2.6） | **不可判**（不是「没执行」）。先按 `RunLogSample.cs:24,58` 与 `EditorAdapter.cs:381` 的上限诊断，**加长窗口/换更早的观察起点**再判 |

**只有第一格命中，才允许把该图的 `runtimeVerified` 标 `true`**（仍仅限「这个节点/这张图被观察到执行」；坐标/结算/玩法正确**不在内**，`RunLogSample.cs:77,89-91` 同口径）。第二、三格**都不构成「图没执行」的证据**。

### 4.5 这个动作**不能**证明什么（写死，防误读）

- 不能证明 proto 58 的语义就是「发出图」——只证明**它是否等于我们选的 id**（相关性，非语义）。
- 不能证明记录是**本次**产生（新鲜度仍归 H2；本动作只解**归属**）。
- 不能证明 `bodyPayloadId`（proto-8 ulong）= 节点 id——只是**候选位**（记忆 `node-ids-two-namespaces`：也可能是 64 位哈希或别的东西）。
- 不能替代负对照解决「历史回放」——若 §4.4 第一格命中**但**你还需要「本次」的证据，**仍要补一次负对照**（#3 §5.4 D3）。

---

## 5. 若 §4 第一格不命中：回退路径（写清，免得反复）

1. **换 op**：修 §2.3 的读者，重发一次 `request-debug-logs`（每 scope 一次），看回复里 tag=5/7 是否出现 → 判别 `ImportAllDebugLog` 是「回而空」还是「回而带文本被读者丢了」（§2.4）。
2. **回到 #3 的实验**：唯一 marker（本会话新建、仅用一次）+ 负对照（#3 §5.2-5.4），窗口用 **120s**（25s 对人太短）。
3. **两条都不成** ⇒ 本通道**只能**提供「收到了来自某图的打印」这一**弱证据**，`runtimeVerified` 继续留 `false`——**如实上报，不拔高**。

---

## 6. 交付清单（本文件相对 #3/#4 新增的内容）

1. **正文载体自带 `ulong`（proto 8）**：`printed-log-proto.cs:18,20`（+ `WriteTo :209-224`/`:236-256`）；桥只读 proto 18 `string`（`RunLogSample.cs:33-34,62-66`）；Adapter 全 `grep` = 0（§2.1）。
2. **记录自带 `{value:enum, graphId:uint}`（proto 58）且类型与 3001 选择表同源**：字段 `eNLa2VJUc8d`（`resolved/…fRTMHcaSSKjG5j3IhYLD.cs:54`、`:874-876`）；类型 `auKUt14Xhrb73Hx3I35G`（`control-research/log-selector-proto.cs:18,20`）；与 `GraphLogSelection.cs:23,29-30` 同型；Adapter 全 `grep` = 0（§2.2）。
3. **`debugLogReply` 读者 `IsPrimitive||IsEnum` 盲点**：`EditorAdapter.cs:464-466`；`Param` 变体（`resolved/…IxtFOgiA4qhGnLhEyLFv.cs:9-24,27-165`）+ tag 枚举 `kZKsh5iAE1K9Hwej0qRY.gPNwHPiAH8Xlc3P3Vc9h.cs:3`（§2.3）。
4. **真机计数更正**：`debugLogRpcMatchedResponses:1` × **45**、`debugLogRpcSuccess:false` × **45**、`debugLogReply` `null`×386/`[]`×66——「回而空」而非「没回」（§2.4）。
5. **`acknowledged:false` 是硬编码字面量**（`EditorAdapter.cs:501`）+ 3001 外层无 ack 槽（`log-control-proto.cs:22`）——#3 该条论据无效（§2.5）。
6. **观察窗两道截断**：32 包（`EditorAdapter.cs:381`）、64 行（`RunLogSample.cs:24,58`）——会把新鲜行挤掉（§2.6）。
7. **单一下一步动作**：读 proto-58 `graphId`（+ 正文 proto-8 `ulong`）→ 一次只读观察 → 判「记录能否按 id 认领自己的图」（§4）。
8. **姊妹四条 `=0` 我独立复算全部成立**（§1.1 P4/P5）。

---

## 7. `notClaimed`

- 本轮**什么都没跑**：没有起 bridge、没有发原生/图/日志请求、没有开游戏或编辑器、没有读写任何存档、**没有读任何图片**、**没有改任何代码或文件（只新增本文件）**。
- **没有**证明 proto 58 的语义是「发出图」；**没有**证明 proto-8 `ulong` 是节点 id。二者都只是**未读字段**与**可反驳假设**。
- **没有**证明 §4 的实验会通过；它是**尚未执行的、可反驳的**计划。**未编译**（该加宽尚未写、未 build）——按 `CLAUDE.md`：**未编译的适配器是候选，不是能力**。
- **没有**把 #3 的 H1/H2（时间戳语义、历史回放）判死；本文件对它们**不采用、不加码**。
- **没有**主张「收到一条记录 = 图执行了」——与 `RunLogSample.cs:90-91` 同口径。
- 3001 的**副作用不可恢复**（`previousEnabledState:"unknown"`，`EditorAdapter.cs:501`）；本文件**不伪造恢复**。

---

## 8. 逐条引用（file:line）

**桥源码**
- `tools/editor-bridge/Adapter/RunLogSample.cs:24,30-34,38-79,58,62-66,77,88,89,90-91`（记录读者；样本上限）
- `tools/editor-bridge/Adapter/EditorAdapter.cs:16`（`Param`）、`:65`（`logRequestAttempted`）、`:343-413`（`ObservePacket`；`:379` 3002/3006、`:380-381` 32 包门、`:397` marker 表）、`:414-433`（evidence）、`:460-470`（`ReceiveDebugLogReply`，`:464-466` primitive/enum 过滤）、`:471`（`logEnableAttempted`）、`:474-502`（enable，`:501` `acknowledged=false` 字面量）、`:503-527`（request；`:509-515` RPC 调用、`:517-518` 请求号）
- `tools/editor-bridge/Adapter/NativeRpcEvidence.cs:8,17-19,29-37`（RPC 回复类型/请求号/匹配）
- `tools/editor-bridge/Adapter/GraphLogSelection.cs:22-34,43-79,83-157`（选择表；`:23` proto 类型、`:29-30` value/graphId 访问器）
- `tools/editor-bridge/Adapter/PositionLogs.cs:21`（精确图名匹配）
- `tools/editor-bridge/ManagedBridge/BridgeServer.cs:59`（`_adapter=new()` 单实例）、`:434-436,489-491,592-594,614-616`
- `tools/editor-bridge/ManagedBridge/NativePacketObserverProxy.cs:10-55`

**反编译语料（`.runtime/`）**
- `editor-catalog/resolved/HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD.cs:42-66`（字段声明）、`:874-876`（proto 58）
- `editor-catalog/resolved/yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv.cs:9-24,27-165`（`Param` 变体 + tag 工厂）
- `editor-catalog/annotated/kZKsh5iAE1K9Hwej0qRY.gPNwHPiAH8Xlc3P3Vc9h.cs:3`（tag 是 enum）
- `editor-catalog/resolved/gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP.cs:87-98`（tag 分派）
- `editor-bridge/scene-context/printed-log-proto.cs:18,20,209-256`（正文载体 `L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB`：proto 8 `ulong` / proto 18 `string`）
- `editor-bridge/control-research/log-selector-proto.cs:14-20`（`auKUt14Xhrb73Hx3I35G`：value enum / graphId uint）
- `editor-bridge/scene-context/log-control-proto.cs:22`（3001 外层只有内层一字段）
- `editor-bridge/control-research/log-selection-annotated.cs:298-301`（原生写侧同型）

**真机回执（`.runtime/editor-bridge/runs/`，本文件 `grep`/`wc` 过）**
- 41 份 `log-observer-evidence-response.json`；454 个 run 目录
- `"runtimeVerified":true`/`"playtestVerified":true`/`"runtimeSemanticsVerified":true`/`"acknowledged":true`/`"debugLogRpcSuccess":true`/非空 `"debugLogReply":[{` ⇒ **均 = 0**
- `"debugLogRpcMatchedResponses"`：**1×45** / 0×368；`"debugLogReply"`：`null`×386 / `[]`×66(+2 空格)
- #3 §3.3 原件（run `10f68791-…`）——本文件 §4 依赖其「自有 marker 文本曾到达」这一事实

**姊妹文件**
- `docs/research/reverse-eng-20261010/GRAPH-RUNTIME-VERIFY-MINE.md`（§3.2/§3.3/§4.2/§5.2-5.4/§5.5）
- `docs/research/reverse-eng-20261010/GRAPH-LOG-SHAPE.md`（§1.3/§2/§3.2/§4.1-4.3）

---

*本文件由 2026-10-10 会话从仓内桥源码、`.runtime/` 反编译语料与真机回执（Bash `grep`/`find`/`sed`/`wc`，非 Grep 工具）只读整理；
**未实现、未编译、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档、未读任何图片**。所有行号为本次 checkout / 本次语料实测；
所有「=0」均写明检索范围。凡「有字段但没读」均写「未读」；凡语义未证均写「未证/假设」；不确定处写「不确定」。*
