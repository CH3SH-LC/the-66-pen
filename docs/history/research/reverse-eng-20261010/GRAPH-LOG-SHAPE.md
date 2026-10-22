> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #4 挖 — 节点图日志的形状：能不能对上「哪个节点跑了」

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档、未读任何图片**。
证据来源只有三处：① 仓内桥 C# 源码（`tools/editor-bridge/`）② `.runtime/` 里反编译/夹具语料（Bash `grep`，**Grep 工具会静默跳过 `.runtime/`**）③ 仓内研究文档与 `PROGRESS.md`。
**本文件只新增自身**，不改其它任何文件。

> 按 `CLAUDE.md` §一.3、§五：`文档写了什么` / `工具能做什么` / `真机验证过什么` 三层分开标。
> **本文件的结论几乎全是静态（读源码/读反编译）；真机那一层的正面证据是 0 条被保留的「自有图」日志行**（见 §3）。
> **「搜不到」≠「不存在」**：凡负面结论都写明检索范围。

---

## 0. 一句话结论

- **一条结构化日志记录（native record）的真实形状，桥是这样读的**：**三个候选「名字」字符串字段** + **一个 `object` 正文体**；正文体只有落在**唯一已知的文本载体类型**上时，才从它的**一个字符串字段**取出「打印文本」。
  出处：`tools/editor-bridge/Adapter/RunLogSample.cs:30-34`（字段名）、`:38-79`（读法）。
- **记录里没有任何「节点 id / 定义 id / 执行标记」被读出**。桥只读出 **（一个图名字符串, 正文文本）**。⇒ **「哪个节点跑了」在当前可读字段里没有直接答案**，只能靠**该节点打印的常量文本**去反推（因为一段唯一的文本只属于一个节点）。
- **但记录的原型（proto）远不止这四个字段**：反编译显示它有 **3 个字符串（proto 号 18/34/50）+ 5 个数值（8/24/40/64/72）+ 5 个子消息（58/82/90/170/178）+ 1 个 kind 枚举**。
  `HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD`：字段声明 `.runtime/editor-catalog/resolved/HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD.cs:42-66`，字段号 `WriteTo` `:723-920`。
  ⇒ **「数值字段里有没有一个就是节点/定义 id」是未证问题**（桥一个都没读，见 §2）。
- **真机层只证到「记录收得到、解析不畸形」**：一次真实观察 **5 个日志包 / 83 条记录 / 0 畸形**（`PROGRESS.md:9934`）。**「名字槽＝图名」这个映射在真机上从未被一条正样本确认**（自有图匹配数一直是 **0**）。
- **最小实验**：用**已经建好、已绑定、已落盘**的 `MW_API_FARM_DEMO`（graphId **1073741829**，15 节点），把它**加进原生日志选择表**，试玩触发**打印字符串节点 id15（文本 `"货币发生变化"`）**，再从 `runLogSample` 里找 **graphName==图名 且 bodyText=="货币发生变化"** 的那一行。**那段文本只属于那一个节点** ⇒ 那一行就是「这个节点跑了」的判据。

---

## 1. 记录的确切形状（从源码，附 file:line）

### 1.1 两种报文：3002 单条、3006 批量

| 事实 | 值 | 出处 |
|---|---|---|
| 入站报文 **3002 = 单条记录** | `case 3002:` → `(fRTMHcaSSKjG5j3IhYLD)…` | `.runtime/editor-bridge/control-research/cc-type0.cs:131-136` |
| 入站报文 **3006 = 批量记录** | `case 3006:` → `(YGZiiaatLoanyfGQd2hQ)…` | `cc-type0.cs:271-276` |
| 桥观察器只认这两个号 | `if(id!=3002 && id!=3006)return;` | `tools/editor-bridge/Adapter/EditorAdapter.cs:379` |
| **记录类型** | `HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD` | `Adapter/PositionLogs.cs:10`、`Adapter/StructuredPositionLogs.cs:10`（`RunLogSample` 不显式引用类型名，只按字段名读，见 `:30-34`） |
| **批量类型** | `IGmDiMatq2IanW3w1IR0.YGZiiaatLoanyfGQd2hQ` | `Adapter/StructuredPositionLogs.cs:11` |
| 批量体里只有**一个 repeated 记录字段** | 字段号 **10**、元素类型 `fRTMHcaSSKjG5j3IhYLD` | `.runtime/editor-bridge/scene-context/batch-log-proto.cs:37`（`WLlatRfEhBx`）、`:220`（`b4LODY5X4O(10u, …)`） |
| 批量体里那个 repeated 字段的**读法** | `Field(payload, B("WLlatRfEhBx"))` | `Adapter/StructuredPositionLogs.cs:33` |

> **记录被路由到一个「图日志」服务**：`cc-type0.cs:463-464` 用 `d8IlVlKoKF7qLuIOSR6g.GraphLog` 这个枚举槽把单条记录派发出去。**这只是服务分类名**，不是字段。

### 1.2 桥读的那四个成员（**唯一被读的形状**）

`tools/editor-bridge/Adapter/RunLogSample.cs:30-34`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


读法（`RunLogSample.cs:44-78`，逐条）：

| 步骤 | 行为 | 行 |
|---|---|---|
| 名字 | 依次取 `evca2Fc2YBM` / `Dsva2frS2bQ` / `IZYa2chZI6A` 三个**字段**的值，**第一个非空 string** 即认作 `name` | `:46-53`（`:48` 要求 `is string value && value.Length != 0`） |
| 无名字 | 三个都空/非 string ⇒ `runLogRecordsWithNoName++`，丢弃 | `:57` |
| 正文 | 取字段 `vqqa2GmktMW` 的对象，**只记它的类型全名** | `:54`、`:59` |
| 文本 | **仅当** `body` 的类型全名 == `L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB`，才读它的字段 `wmmat7vdE8l` 当字符串 | `:62-66` |
| 其余 | 正文类型不认识 ⇒ `bodyTextReadable=false`，正文**当作不透明** | `:59`、`:75` |
| 截断 | 文本 >512 字符则截断，**不丢**（"unexpected string is evidence too"） | `:69` |
| 样本上限 | **64 行**（`RunLogSampleLimit`），超了置 `runLogSampleLimited` | `:24`、`:58` |

同形状的另外两个**更窄**的读者（同一记录、同一字段，只是名字过滤更严）：
- `Adapter/PositionLogs.cs:21-31`——名字必须**精确等于** `PositionGraphName`(`PositionGraph.cs:10` = `MW_Character_Position_20260916`)。
- `Adapter/AuditGraph.cs:18-27`——名字必须精确等于 `AuditGraphName`(`AuditGraph.cs:11` = `MW_Runtime_Count_Audit_20260916`)。

⇒ **桥对这条记录的认识停在「3 个候选名字 + 1 个正文」**。三个名字槽里**哪个**是图名，桥不知道——它对**任意一个**匹配图名即接受（`PositionLogs.cs:21` 的 `Any(...)`）。

### 1.3 记录 / 正文的**真实** proto 形状（反编译，**比桥读的多得多**）

记录类型 `HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD` 的字段声明
（`.runtime/editor-catalog/resolved/HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD.cs:42-66`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`WriteTo`（同文件 `:723-920`）给出的**文件号 → 载荷**（本次 build 实测）：

| proto 号 | 载荷（getter） | 形状 | 出处行 |
|---:|---|---|---|
| **8** | `rr7aSk3tYOX` | 数值 | `:787-788` |
| **18** | `d6ba25XwDys` | 字符串 | `:734-735`、`:903` |
| **24** | `QMBa2OYZ7cM` | 数值 | `:831-833` |
| **34** | `fK5a2ESLkSi` | 字符串 | `:820-822`、`:837` |
| **40** | `pMka209lx4X` | 数值 | `:790-793`、`:896-898` |
| **50** | `Sn8a2itC6pv` | 字符串 | `:738-739`、`:883-886` |
| **58** | `ujOa27JlDqn` | 子消息 `uBi4l34XLv2OekpES2JT.auKUt14Xhrb73Hx3I35G` | `:874-876` |
| **64** | `teFa2daHKhJ` | 数值 | `:781-783` |
| **72** | `xX6a2P7knNr` | 数值 | `:807-810`、`:851-852` |
| **82** | `CZKa21UN52p` | 子消息 `gAqlPYvXySiCOGumHioL` | `:802-804` |
| **90** | `fjsa2LEAPGR` | 子消息 `GZhy8TaSRRmSDoLljexK` | `:773-775` |
| **170.1** | `BdJa2WJ68M1`（**kind 枚举==21 时**） | 子消息 `kCswUgaCop5DwnSlppqK` | `:755-760` |
| **178.1** | `oWXa2TZld59`（**kind 枚举==22 时**） | **子消息 `L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB`（= 文本载体）** | `:761-765` |

> **关键一行**：`:365` 明写 `oWXa2TZld59 → L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB::Clone`。
> ⇒ **桥当作「正文文本」的那个载体，正是 proto 号 178（在 kind==22 分支下发）**；protobuf 的 oneof/判别语义说明**正文是「按 kind 选一种」的多态体**，不是固定字段。

**子消息 `auKUt14Xhrb73Hx3I35G`（proto 号 58）** 正是**日志选择表**里用的那个 `{value:enum(1), graphId:uint}`（见 §4.3）。
⇒ **记录里自带一个「(enum, 图 id)」结构**，但桥**没读它**。

### 1.4 名称 vs 正文 —— 桥认为的语义（**假设**，非实测）

- `name` = 三个字符串字段里第一个非空的；被当作**图名**。
- `body` = `vqqa2GmktMW`；只有落在文本载体类型上才有 `bodyText`。

`RunLogSample.cs:88-91` 的 `scope` / `notice` 原文（**这是本文件要引的那段 notice**）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 2. 记录里有没有「节点 id / 定义 id / 执行标记」？

**精确回答（分三层）**：

1. **桥读出来的字段里，没有任何节点 id / 定义 id / 执行标记。** 桥读的四个成员（§1.2）里只有**字符串名字**和**正文体**；`:44-78` 全程不取任何数值字段，也不取 proto 号 58 的 `(enum, graphId)` 子消息。**执行证据完全来自「记录存在」本身**，`notice` 还明确说**它不证明 graph 执行**（`RunLogSample.cs:90-91`）。
2. **但记录里客观存在候选者**：5 个数值字段（proto 8/24/40/64/72）+ 一个 `(enum(1), uint graphId)` 子消息（proto 58）。
   **「其中哪一个（如果有）是节点/定义 id」本轮无法回答** —— 桥没读、反编译里字段名全是混淆串、没有一条真机记录被交叉核对过。**这是一个未证问题，不是负结论**。
3. **编号命名空间提醒**（记忆 `node-ids-two-namespaces`）：即使某个数值字段是「id」，它也可能是**桥侧小整数 `definitionId`（1~300005）**或**离线资源 64 位哈希**，二者**交集为 0**。本轮没有证据区分。

**⇒ 一句话：能对上的只有「图名 + 打印文本」；「哪个节点」在当前被读的字段里没有独立标识，只能靠打印文本的**唯一性**反推。**

---

## 3. 真机证了什么、没证什么

### 3.1 证到的（有原件口径）

| 事实 | 原件 / 出处 |
|---|---|
| **记录能收到、能解析、不畸形**：一次真实 observe 收到 **32 包 / 5 个日志包**，**结构化位置日志 5 批 83 条记录 0 畸形未触限** | `PROGRESS.md:9934`（run `3c63e9ac-74e4-47fd-b18d-8555a96aca32`） |
| 另一真实 run（R49）`bed97e42`：**4 个 3006 包 / 19 条记录 / 0 异常**，直接读取未触限；但**位置图名称匹配 0、正文过滤 0、位置打印 0** —— 明确写「**不能据此断言位置图未执行**」 | `PROGRESS.md:9816-9820` |
| R42 实机**选择两图成功**，从 3006 里**读回校准/路线两个「创建标记」** | `PROGRESS.md:9492` |
| **事件节点是否真的执行，从未被验证**（"图里有「实体创建时 → 打印字符串」，**无人跑过**"） | `PROGRESS.md:3146` |

### 3.2 没证到的（必须写明的空白）

- **「名字槽＝图名」这个映射在真机上从未被一条自有图的**正样本**确认**：所有提及的匹配数都是 **0**（`PROGRESS.md:9820` 位置图匹配 0）。**唯一把它当真的方式是桥代码自己的断言 + 一个合成夹具**（见 3.3）。
- **本工程自有图（校准/路线/位置/结算/demo）从未出现任何一行被保留的 run-log 记录** ⇒ **「哪个节点打印了什么」在真机上零观测**。
- 数值字段是不是节点/定义 id：**未证**（§2）。
- 「一条记录对应一次事件」：**未证**；`notice` 明确只证「收到」。

### 3.3 一个必须点破的口径事实（对任务前提的更正）

- 任务描述「`PROGRESS.md` 提到 `received-structured-log-records` 且带样本上限」——**在 `PROGRESS.md` 与 `PROGRESS-LITE.md` 里都搜不到该串**（Bash `grep -n "received-structured-log-records\|across-all-graphs\|RunLogSample\|RunLogSampleLimit" PROGRESS.md PROGRESS-LITE.md` ⇒ **0 命中**）。
  该**字面串只存在于源码**：`Adapter/RunLogSample.cs:88`（`scope`）与 `:24`（`RunLogSampleLimit = 64`）。
- 那段 **notice**（"A captured row proves a record was RECEIVED…"）同样**只在源码**：`RunLogSample.cs:90-91`。
  **`PROGRESS.md` 里提到 `RunLogSample` 的地方，本轮检索范围内 0 处**；唯一在文档里点名 `RunLogSample` 的是
  `docs/retrospectives/2026-10-03-future-development-followup.md:84`（且是"标明 `runtimeSemanticsVerified=false`、日志文本不足以闭合运行用例"的**限制性**表述）。
- **结论**：这段 notice **仍然有效（它就是树里现役代码的返回字段）**，但它**没有被 `PROGRESS.md` 复述**；「记录 names a graph」这句是**桥作者的断言**，其真机支撑只有 §3.1 的「收到 83 条」+ 合成夹具，**没有一条「自有图名匹配成功」的真样本**。
- 「名字槽＝图名」在**合成夹具**里被建模为真：`.runtime/editor-bridge/log-packet-fixture/Program.cs` 构造
  `new HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD { Dsva2frS2bQ = graph, vqqa2GmktMW = new L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB{ wmmat7vdE8l = value } }`
  并断言「本图标记收、别的图拒」。**夹具不是真机**（`CLAUDE.md` §五：夹具通过不计业务验收）。

---

## 4. 最小实验：让**一个已知节点**跑起来的唯一可判据

### 4.1 目标图（已建成，不重建）

| 项 | 值 | 出处 |
|---|---|---|
| 图名 | **`MW_API_FARM_DEMO`** | `tools/gameplan/run_demo.py:95`（默认名）、`:336` |
| graphId | **1073741829** | `PROGRESS.md:80`、`:109` |
| 规模 | 15 节点 / 17 边 / 13 常量 | `PROGRESS.md:109` |
| 绑定 | 绑在自建地块实体 `1077936129`（`boundToLevel:false`） | `PROGRESS.md:80` |
| 落盘 | save 后 `.gil` 21872→28383 B，载荷含 entityId/graphId(×8)/templateId | `PROGRESS.md:76` |
| 节点表原件 | `.runtime/scratch/farm-demo-build.json`（`nodeIds`: node1..node15 ⇒ 内部 id 1..15） | 本文件读自该文件 |
| 定义/连线/常量原件 | `.runtime/scratch/MW_API_FARM_DEMO-plan.json` | 本文件读自该文件 |

**节点清单**（`farm-demo-build.json` 的 id × `MW_API_FARM_DEMO-plan.json` 的定义 id/常量，按建图顺序 **plan 下标 i ↔ 节点 id i+1** 对齐；
对齐依据：`plan.values` 里 `"node": k` 的常量落点是 `id=k+1`，且语义逐项自洽）：

| 节点 id | 定义 id | 节点名（`data/node-contracts` 实测） | 该节点上的常量 |
|---:|---:|---|---|
| 1 | 92 | 进入碰撞触发器时 | — |
| 2 | 686 | 增加背包道具数量 | item `1120000001` ×1 |
| 3 | 733 | 背包内道具被使用时 | — |
| 4 | 690 | 获取背包道具数量 | item `1120000001` |
| 5 | 233 | 数值大于等于 | 阈值 `2` |
| 6 | 2 | 双分支 | — |
| 7 | 686 | 增加背包道具数量 | item `1120000001` ×(-2) |
| 8 | 686 | 增加背包道具数量 | item `1120000002` ×1 |
| **9** | **1** | **打印字符串** | **`"材料不足"`** |
| 10 | 92 | 进入碰撞触发器时 | — |
| 11 | 702 | 打开商店 | — |
| 12 | 701 | 商店出售背包物品时 | — |
| 13 | 688 | 增加背包货币数量 | currency `1115684864` ×10 |
| 14 | 684 | 背包货币数量变化时 | — |
| **15** | **1** | **打印字符串** | **`"货币发生变化"`** |

> 定义 id → 名字由 `data/node-contracts/definitions/bucket-*.json` 实测（`definitionId/name`）。`PROGRESS.md:136` 用自然语言复述了同一条链："货币变化→打印"。
> **两个「打印字符串」节点是天然的节点级探针**：`id9`（`材料不足`）与 `id15`（`货币发生变化`），**各自带一段唯一常量文本**。

### 4.2 为什么「打印文本」就是节点级判据

因为记录里**没有节点 id**（§2）。**唯一能把「是哪个节点」钉死的，就是「那段常量文本只属于那一个节点」**。
⇒ 抓到 `graphName==MW_API_FARM_DEMO 且 bodyText=="货币发生变化"`，就等价于「**id15 这个 `def1 打印字符串` 节点执行了**」。这是当前可读字段下能从记录里挤出的**最强节点级信号**。

### 4.3 最小实验（一次，串行；**本文不执行，只写形状**）

**前置（不改图、不重建，只读回确认）**
1. `discover_current_level` 取**当次**原生回执的 levelId（记忆 `level-ids-are-per-save-never-pinned`：**禁止复制上一轮的关卡 id**）。
2. 只读 `inspect`：确认图 `MW_API_FARM_DEMO` / graphId **1073741829** 仍在、**恰好 15 节点**、且绑在实体 `1077936129` 上。（节点数必须精确 15，因为选择表会**按节点数校验**，见 `GraphLogSelection.cs:69-70`。）

**第一步：把 demo 图加进原生日志选择表（这是当前唯一的缺项）**

- 现状：`ConfigureOwnGraphLogSelection`（`GraphLogSelection.cs:43-79`）的**必选**只有**校准(7) / 路线(39)**，**可选**是审计(13) / 位置(16) / 结算(23)；**demo 图不在表里**。
  ⇒ 必须**新增一行**：`{Name="MW_API_FARM_DEMO", Nodes=15, Optional=false}`（`:48-53` 的匿名数组里加一项），并让它的 `Category[2]==21001`（`:34`、`:66` 会校验）。
- 选择表容量：服务器图 ≤ **10**、客户端图 ≤ **99**（`GraphLogSelection.cs:32-33`，原生上限）。
- 发送：`EnableOwnGraphLogging()` → `EnableDebugLoggingCore(true)`（`EditorAdapter.cs:473`、`:493-498`），
  原生报文 **3001**，载荷是外层 `SNYUqraShudVtwQSLBmO` 内嵌 `bNf3IEaS4GdguXca3eut`，服务器列表里每条 = `{value:enum(1), graphId}`（`:488-498`；形状来源 `cc-type0.cs` 的反编译：`log-selection-annotated.cs:298-301`、`:342`）。
- **读回门**（发送前已内建）：`server.Count==ids.Length`、id 唯一非零、client 列表必须空（`GraphLogSelection.cs:91-94`、`:96-101`、`:125-138`）。
- **纪律**：`EnableDebugLoggingCore` 一条 session 只能发一次（`:476` `LOG_ENABLE_ALREADY_ATTEMPTED`）；且**原生日志开关的「旧状态未知」**，本实验**不伪造恢复关闭**（与 `PROGRESS.md:9330` 口径一致）。

**第二步：起观察器 → 试玩 → 触发 id15**
3. `start-log-observer`（`BridgeServer.cs:489`，适配 `Adapter`），窗口内**保持**观察。
4. 进入试玩，触发**货币变化链**：`id12 商店出售背包物品时(def701)` → `id13 增加背包货币数量(def688)` → `id14 背包货币数量变化时(def684)` → **`id15 打印字符串(def1)="货币发生变化"`**。
   - **依赖诚实标注**：M2 货币走**节点图事件** `688/691/722/684`（`PROGRESS.md:312` 判定表 M2 行），但**这些事件节点在 7.1 是否真的会触发，从未跑过**——这正是 `PROGRESS.md:3146` 挂着的同一问题。所以本实验的**前置不确定**在「事件节点真的会触发吗」，而不在记录读法。
   - **更弱依赖的备选**：走**碰撞触发**那一侧（`id1 进入碰撞触发器时` → … → `id9 打印字符串="材料不足"`），只依赖碰撞触发节点；同样未验证。两条路**选一条**即可，不必都跑。
5. `log-observer-evidence`（`BridgeServer.cs:490`）→ 读 `runLogSample`（`EditorAdapter.cs:421`、`RunLogSample.cs:81-92`）。

**判据（三种结果都要落盘）**

| 观察 | 结论 |
|---|---|
| `sample` 里存在 `graphName=="MW_API_FARM_DEMO"` **且** `bodyText=="货币发生变化"` | **id15 这个节点执行了**（当前可得的最强节点级证据）。仍**不**等于坐标/结算/玩法正确。 |
| `recordsSeen>0` 有行、但无该文本 | 记录到了，但**demo 图没被选中/没触发/文本落在别的正文类型** —— 需要看 `bodyType` 是否 = 文本载体、`recordsWithNoGraphName` 是否为 0（判名字槽是否读空）。 |
| `recordsSeen==0` 或 `sampleLimited==true` | **不可判**（不是"没执行"）。要按 `StructuredPositionLogs`/`RunLogSample` 的上限诊断（`:22-23`、`:58`）。 |

**这不是「最小」里最小的那个**：真正的更小选项是**一张 2 节点 print 图**——`PROGRESS.md:550` 记录过 `MW_API_SOL_L10_soll15safe1_print`（graphId **1073741830**，`build-print` **2 节点 71+1**，已 export/bind 成功）。**若它此刻仍在**，用它的打印文本做同一判据，**依赖比 demo 图少**。但该图是 2026-10-06 的历史状态，**本轮未核实是否仍存在**（不确定就写不确定）。

### 4.4 这个实验**不能**证明什么（写死，防误读）

- 不能证明「记录的数值字段是节点 id」（本文没读它们；要把它们读出来是另一个探针）。
- 不能证明「图运行正确」——只证明**一个节点的打印走到了观察者**。
- 不能把 `runLogSample` 的行当"运行语义"：`runtimeSemanticsVerified=false`（`RunLogSample.cs:77`）。
- 桥侧只改**编辑器内存**、且 `persistentSaveVerified:false`（`CLAUDE.md` §二）；**本实验若要落盘须另走原生 save + `.gil` 字节差分**（记忆 `one-write-per-baseline-and-review`、`scene-save-writes-the-game-not-the-editor`）。

---

## 5. 交付清单（本文件新增的判据）

1. **记录形状（唯一被读的四个成员）**：`RunLogSample.cs:30-34`；读法 `:44-78`。三候选名字 + 一正文体 + 文本载体类型 + 其内文本字段。
2. **报文号**：3002 单条 / 3006 批量（`cc-type0.cs:131-136`、`:271-276`；过滤 `EditorAdapter.cs:379`）；批量 repeated 字段号 10（`batch-log-proto.cs:220`）。
3. **原型真形状**：字段声明 `resolved/…fRTMHcaSSKjG5j3IhYLD.cs:42-66`；字段号 `WriteTo :723-920`；文本载体 = proto 178（kind==22），见 `:365`、`:761-765`。
4. **节点 id 问题**：桥**不读**任何节点/定义/执行标记（§2）；有 5 个数值字段 + 一个 `(enum,graphId)` 子消息（proto 58）**未读**，是否含节点 id **未证**。
5. **真机层**：**收到 83 条记录 0 畸形**（`PROGRESS.md:9934`）；**自有图匹配一直是 0**，**没有任何一条被保留的自有图日志行**；事件节点是否执行**从未验证**（`PROGRESS.md:3146`）。
6. **notice 更正**：`received-structured-log-records` / 样本上限 64 / 那段 notice **只在 `RunLogSample.cs:24/88/90-92`**，**`PROGRESS.md`/`PROGRESS-LITE.md` 检索范围内 0 命中**；文档里唯一点名 `RunLogSample` 的是 `docs/retrospectives/2026-10-03-future-development-followup.md:84`（限制性表述）。
7. **最小实验**：`MW_API_FARM_DEMO` / graphId 1073741829 / 15 节点（节点表见 §4.1），把 demo 图**加进选择表**（`GraphLogSelection.cs:48-53`）→ `enable-own-graph-logging` → 试玩触发 → 在 `runLogSample` 找 **`graphName==图名 且 bodyText=="货币发生变化"`** ⇒ **id15 执行**。

---

## 6. 证据索引

| 论断 | 证据 |
|---|---|
| 记录类型 / 批量类型 | `Adapter/PositionLogs.cs:10`；`Adapter/StructuredPositionLogs.cs:10-11` |
| 3002 单条 / 3006 批量 | `.runtime/editor-bridge/control-research/cc-type0.cs:131-136`、`:271-276` |
| 桥只认 3002/3006 | `Adapter/EditorAdapter.cs:379` |
| 四个被读成员 | `Adapter/RunLogSample.cs:30-34`；读法 `:44-78` |
| 精确图名过滤（位置/审计） | `Adapter/PositionLogs.cs:21-31`、`Adapter/AuditGraph.cs:18-27`；常量 `PositionGraph.cs:10,12`、`AuditGraph.cs:11-13` |
| notice / scope / 上限 64 | `Adapter/RunLogSample.cs:24,88,90-92` |
| 记录字段声明（真形状） | `.runtime/editor-catalog/resolved/HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD.cs:42-66` |
| 记录字段号（WriteTo 8/18/24/34/40/50/58/64/72/82/90/170/178） | 同文件 `:723-920`；文本载体=178 见 `:365`、`:761-765` |
| 批量 repeated 字段号 10 | `.runtime/editor-bridge/scene-context/batch-log-proto.cs:37,220` |
| 记录路由到 GraphLog 服务 | `cc-type0.cs:463-464` |
| 选择表形状 / 3001 发送 | `Adapter/GraphLogSelection.cs:31-34,43-79,83-157`；`Adapter/EditorAdapter.cs:473,488-498` |
| 选择表原生上限 10/99 | `GraphLogSelection.cs:32-33` |
| 合成夹具把「名字槽=图名」建模为真 | `.runtime/editor-bridge/log-packet-fixture/Program.cs`（构造 `fRTMHcaSSKjG5j3IhYLD{Dsva2frS2bQ=graph, vqqa2GmktMW=…wihQ1xataDGHleutr4mB{wmmat7vdE8l=value}}`） |
| 真机：83 条记录 0 畸形 | `PROGRESS.md:9934` |
| 真机：R49 19 条记录、位置匹配 0、不可断定未执行 | `PROGRESS.md:9816-9820` |
| 真机：R42 选择两图读回标记 | `PROGRESS.md:9492` |
| 事件节点执行从未验证 | `PROGRESS.md:3146` |
| demo 图 graphId/规模/绑定/落盘 | `PROGRESS.md:80,109,76`；`tools/gameplan/run_demo.py:95` |
| demo 图节点/连线/常量 | `.runtime/scratch/farm-demo-build.json`、`.runtime/scratch/MW_API_FARM_DEMO-plan.json` |
| 定义 id → 节点名 | `data/node-contracts/definitions/bucket-*.json`（`definitionId`/`name`） |
| 2 节点 print 图（更小备选） | `PROGRESS.md:550`（graphId 1073741830，节点 71+1；历史状态，未核实仍在） |
| 文档里唯一点名 RunLogSample | `docs/retrospectives/2026-10-03-future-development-followup.md:84` |
| debug.events 功能态 | `docs/PROGRESS-BY-FUNCTION.md:59`（`partial`：缺每次运行的关联与游标） |

---

*本文件由 2026-10-10 会话从仓内桥源码、仓内反编译/夹具语料（Bash `grep`，非 Grep 工具）与 `PROGRESS.md` 只读整理；
**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档、未读任何图片**。所有行号为本次 checkout / 本次语料实测。
凡「有实现没跑过」的条目标 `只离线` / `未验证`；负面结论均写明检索范围。*
