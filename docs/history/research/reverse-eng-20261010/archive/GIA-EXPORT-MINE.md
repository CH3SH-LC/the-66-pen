> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# GIA-EXPORT-MINE — 导出的 `.gia` 到底是什么（框架判定 / 节点表 / 边）

> 建立日期：2026-10-10。位置：`docs/research/reverse-eng-20261010/GIA-EXPORT-MINE.md`。
> 任务：#9 —— 「graph export 产出 `.gia`（status `invoked-not-confirmed`），但工程从未分析过一个」。
> 本文把**仓内真实存在的 `.gia` 逐字节拆开**，回答三件事：
> (1) 它的**框架**是否等于 `.gil` 容器；(2) 里面**有没有可走行的节点表**；(3) **边**在哪里。
>
> **全程只读**：没有连桥、没有发任何 native/graph 请求、没有启动游戏或编辑器、没有写
> `C:\Users\PUBLIC_USER\AppData\LocalLow\miHoYo\` 下的任何文件。所有字节来自本仓 `.runtime/` 内**已有的**导出产物。
> 本文是本次唯一写入。
>
> 口径（沿用 `docs/PROGRESS-BY-FUNCTION.md`）：**真机验证过** / **只离线验证过** / **未验证**。
> 本文每条结论都带字节或 `文件:行`。**没有证明的地方写"未解决"，不写成"有"**。

---

## 0. 一句话判决

| 问题 | 判决 | 依据 |
|---|---|---|
| `.gia` 用的是 `.gil` 容器框架吗？ | **分两类，答案相反。桥导出类=是；调试日志类=否** | §1 |
| 桥导出 `.gia` 里有可走行的节点表吗？ | **有，确定**（重复 field 3，索引连续，含 definitionId） | §3 |
| 桥导出 `.gia` 里有边（from-node → to-node）吗？ | **未找到，且有一条精确负证据**（§4.3）。不写成"有" | §4 |
| 调试日志 `.gia` 是什么？ | **另一种东西**：8 字节头 + 一层 level 记录列表，`parse_fields` 能走但**不是图** | §5 |
| 生成一条 `.gia` 的命令 | `python tools/authoring/author.py graph export --request-id … --run-id … --name … --graph-id …` | §6 |

**对 #9 任务假设的修正**：任务说"工程从未分析过一个 `.gia`"。实际上 **仓内有 1297 个 `.gia`**，分两类；
其中 **67 个是桥导出的、且框架与 `.gil` 完全一致**。所以结论是**证实 + 细化**，不是"没有样本"。

---

## 1. 框架判定：`decode_container` 在你没料到的地方成功了

### 1.1 两类 `.gia`，同一后缀，两个框架

对 `.runtime/` 下按模式命中的 **1297 个 `.gia`** 逐个跑 `gil_container.decode_container`（`tools/beyond-save/gil_container.py:86-103`）：

| 类 | 数量 | 位置 | `decode_container` | 头 |
|---|---|---|---|---|
| **A. 桥导出** | **67** | `.runtime/editor-bridge/exports/*/*.gia` | **成功** | `.gil` 容器，**subtype=3**，trailer `0x679` |
| **B. 调试日志** | **1230** | `Beyond_Debug_Log/`、`beyond-save/pre-empty-control/`、`pre-playtest/`，文件名形如 `2026-09-16_23-01-34_6_100000001.gia` | **失败**（`unexpected version`） | 8 字节长度头，**无 version/magic/subtype/trailer** |

> 计数方式：5 条 glob（`exports/*/*.gia`、`beyond-save/*/*.gia`、`pre-*/*.gia`、`backups/*/[template]/Beyond_Debug_Log/*.gia`）
> 去重后 1297；A=67，B=1230。B 的父目录分布：`Beyond_Debug_Log` 1220、`pre-empty-control` 5、`pre-playtest` 5。

### 1.2 桥导出 `.gia` —— **证实等于 `.gil` 容器**

`.runtime/editor-bridge/exports/miliastra-bridge-d4d9057e-…/bridge-export-1d323a731dd546d283f488fdd08ba399.gia`，len=9850：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


* **subtype 分布**：67 个 A 类文件**全部 subtype=3**，没有例外。
* `gil_container.decode_container` 的**校验里没有 subtype 这一项**——它只查 version/magic/长度/trailer。
  所以这两句的结论同时成立：**(a) 框架确实一致，(b) 现有解码器无需改一行就能解它**。
* 39 节点的那份同样成立（`…/0d006e52-…/bridge-export-9748…gia`，len 9828：`00 00 26 60 | 00 00 00 01 | 00 00 03 26 | 00 00 00 03 | 00 00 26 4c`，尾 `00 00 06 79`）。

> **缺口（建议，未改）**：`gil_container.py:1-35` 的模块 docstring 说"两种文件：`.gip` 玩家档案 / `.gil` 关卡描述"，
> 且说 subtype "1 = player profile, 2 = level"。今天起这句话**不完整**（漏了 subtype 3 = 导出的节点图）。
> 它不是**假**（subtype 1/2 的断言仍对），所以本次只记录、不动工具（本文只允许写这一个 `.md`）。

### 1.3 调试日志 `.gia` —— **证伪等于 `.gil` 容器**

`.runtime/beyond-save/pre-empty-control/2026-09-16_23-01-34_6_100000001.gia`，len=96253：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


* 第二条 u32 是 **96245 = inner_len**，不是 version(1)。对 717 字节的小文件同样是 `0000 02c9 | 0000 02c5`（713/709）。
* 结构恒等式（对所有 1230 个 B 类文件成立，0 例外）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

* 也就是说：**它是同一个"长度前缀家族"，但砍掉了 version/magic/subtype/trailer 四个字段**（20+4 字节的 `.gil` 外框 → 8 字节）。
  可以直接这样描述：`.gia(debug) = u32 total + u32 inner + protobuf`，**没有** `.gil` 的 20 字节头与尾部 `0x679`。
* `decode_container` 对它报错是**正确行为**（`unexpected version 852/96245`），不是 bug。

---

## 2. 桥导出 `.gia` 的两层：外框与图

`container.payload`（A 类）的顶层字段（`gil_container.parse_fields` 直接可解）：

| field | wire | 内容 | 证据 |
|---|---|---|---|
| **1** | LEN | **图记录**（graph record），见 §3 | 全部 67 个都有 |
| **3** | LEN | 身份串，形如 `100000001-1789546963-1073741827-\bridge-export-<32hex>.gia` | 单文件实测 |
| **4** | varint | `1` | 单文件实测 |
| **5** | LEN | 客户端版本串 `"7.0.0"` | 单文件实测 |

> 注意：`field 3`（LEN 83）**不是消息**——把它当嵌套消息解析会在 field 12 撞上 wire type 6
> （`ContainerError: field 12 has reserved wire type 6`）。它是**纯字符串**。这也是一处"别猜 schema"的实证。

### 2.1 图记录（payload.field 1）

| field | wire | 内容 | 例 |
|---|---|---|---|
| **1** | LEN(8) | 图头 `{f2:5, f4:<levelId>}` | `f4 = 1073741827` |
| **3** | LEN | 图名（UTF-8） | `MW_Route_Tiled_20260916` |
| **5** | varint | **图模型类别**：`9` = 节点图，`69` = Lua 图 | 见 §3.3 |
| **13** | LEN | 图体（body），见 §2.2 | |

### 2.2 图体（图记录.field 13）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 3. 节点列表 —— **可走行，确定**

### 3.1 节点记录（图体.…field 3 的每一份）

| field | wire | 含义 | 例 / 证据 |
|---|---|---|---|
| **1** | varint | **节点索引**，1..N 连续，且等于出现次序 | 39 节点图里 1..39 一个不缺 |
| **2** | LEN(13) | 类别+定义 `{f1:10001, f2:20000, f3:22000, f5:<definitionId>}` | 全样本 988 个节点里 **987 个**是这个三元组；**1 个**（`MW_Bridge_Test` 的某个节点）缺 f3 |
| **3** | LEN(13) | 同形状；`f5` 为（另一个）definitionId | 多数与 f2 相同；**少数不同**：`(14,16)`、`(509,510)` |
| **4** | LEN | **引脚记录**（pin），重复 0..7 个 | 全样本 2859 条，见 §3.2 |
| **5** | varint | 编辑器坐标 x：**float32 位型当 varint 存** | `1133903872 = 0x43980000 = 304.0f` |
| **6** | varint | 编辑器坐标 y：同上 | `1132068864`；为 0 时缺省（proto3 省零值） |

* definitionId 是**小整数集合**（不是 64 位哈希）：全 67 个文件里 49 种配对；最常见的
  `252`(215 次)、`2`(105)、`1`(86)、`71`(55)、`73`(43)、`225`、`79`、`83`、`509`…与
  `docs/.../node-ids-two-namespaces` 记的「桥收小整数 definitionId」一致。
* **节点数直方图**（67 个文件）：`0×7, 1×1, 2×12, 6×1, 7×10, 9×1, 12×1, 13×6, 15×2, 16×2, 23×5, 29×13, 39×6`。
* **7 个 0 节点文件**：6 个是 `MW_Lua_*`（kind 69，body 为空），1 个是 `MW_Bridge_Test_20260916`（kind 9）。

### 3.2 引脚记录（节点.field 4）

| field | wire | 内容 |
|---|---|---|
| **1** | LEN | `{f1:<pinKind>, f2:<idx>?}`，pinKind ∈ {2,3,4} |
| **2** | LEN | `{f1:<同一个 pinKind>, f2:<idx2>?}` |
| **3** | LEN | 引脚的配置（随 kind/类型变；含 f1=typeCode、f4=值槽、f101/f102/f105/f106/f107/f110 等） |
| **4** | varint | 一个引用号；**与 field 3→f4→f100→f1 的值相同**（实测恒相等） |
| **5** | LEN | `{f1:<序号>, f2:{f1:<侧>}, f3:{f1:<侧>}}`，侧 ∈ {1,4} |

**实证（2859 条引脚）**：
* `pinKind` 只出现 **2 / 3 / 4**：`(2,2)` 540 次、`(3,3)` 2292 次、`(4,4)` 27 次。**kind 1（输入执行）一次都没出现**。
* field1 与 field2 的 `f1`（kind）**永远相等**（2859/2859）。也就是它**不是** `源kind→目标kind` 的边对——
  若真是边，按 `tools/authoring/author.py:60-66` 的配对律应是 `(2,1)` 或 `(4,3)`。
* 因此：**节点.field 4 是"引脚（端口）声明"，不是边**。
* 与 CLI 合同对照：`author.py:60-66` 定义 `1=输入执行 2=输出执行 3=输入数据 4=输出数据`、配对律 `EDGE_PAIRING={(2,1),(4,3)}`，
  在 `.gia` 里果然只看到 2/3/4 三种。

### 3.3 kind 69（Lua 图）的 body 是空的

6 个 `MW_Lua_*`（level 1073741829/1831..1835）的 `field 13` 存在但**其子字段为空** → 0 节点。
即：Lua 脚本地图**不携带节点表**。这是"不是所有 `.gia` 都有图"的精确负证据。

---

## 4. 边：**未找到**，并给出一条精确负证据

> 这一节是本文最重要的**负结论**。按工程纪律，"精确的否定 + 证据"就是交付物。

### 4.1 已知的边模型（用于对照）

CLI 侧的边模型是显式的三元组：
* `author.py:490-501`：`wire/unwire` 收 `--from-node-id/--to-node-id`、`--from-port-kind/--to-port-kind`、`--from-port-index/--to-port-index`。
* `author.py:511-518`：`build-plan` 的 plan 文件 schema 就是
  `{nodes:[{definitionId,x,y}], edges:[{from,to,fromKind,fromIndex,toKind,toIndex}], values:[…]}`，**`from`/`to` 是 `nodes` 的下标**。

### 4.2 拿一个**真有边**的图来验

`.runtime/scratch/MW_API_FARM_DEMO-plan.json`：**15 节点 / 17 边 / 13 值**。

它的导出产物 `.runtime/editor-bridge/exports/miliastra-bridge-9b9a2e09-…/bridge-export-3575…gia`
（graph `MW_API_FARM_DEMO`，kind 9）实测：

* **节点数与顺序与 plan 完全一致**（15 个，definitionId 序列 `92,686,733,690,233,2,686,686,1,92,702,701,688,684,1` 逐位相同）。
  → 这证明 **`.gia` 里的节点表确实是"编辑器侧的真实图"**，不是请求的回声（请求里只有 graphId + name，
  见 `.runtime/authoring/requests/311d2f54-…/bridge-request.json` 只有 `{action:export, graphId, name}`）。
* 但：**plan 的 17 条边，在 `.gia` 里找不到对应字段**。

### 4.3 精确负证据

plan 的 17 条边 = **8 条执行边 (2→1)** + **9 条数据边 (4→3)**。
而 `.gia` 里：

| 该有 | plan 期望 | `.gia` 实测 | 差 |
|---|---|---|---|
| 输出执行脚 (kind 2) | 8 | **9** | 多 1 |
| 输入执行脚 (kind 1) | 8 | **0** | 少 8 |
| 数据脚 (kind 3/4) | 9+ | 若干 | 无法一一对上 |

而且**全 67 个文件、2859 条引脚里，没有任何一条承载"另一个节点的索引"**：
引脚的 `f1.f2`/`f2.f2` 取值 ≤7（明显是**本节点内的端口槽号**，不是节点号 1..39）；
`f4`/`f100` 值 ≤21；`f101` 是**批次/分组号**，在相邻成组的若干节点间重复
（39 节点图里：`20001875` 覆盖 node5/8-14，`20001224` 覆盖 15-18/27-30，`20001876` 覆盖 19-22，`20001877` 覆盖 23-26，`20001878` 覆盖 31-39）。
分组边界与节点坐标的"行"（fx 每 4 个相同）**不严格对齐**，故只记"是分组号"，不推断分组规则。

**结论（写成否定）**：**在这些 `.gia` 里找不到"边"的显式编码**；`from-node → to-node` 那条信息
要么不存在于本导出里，要么以我尚未识别的形式存在。**不写成"边在 field X"。**

### 4.4 唯一的实验（给下一轮）

不需要连桥也能做，但需要一次真机导出（**本轮离线，不做**）：

1. 取一个已知图 `G`，**导出两次**：`G0`（无此线）与 `G1`（用 `wire` 加**恰好一条**已知边：
   `--from-node-id A --from-port-kind 2 --from-port-index 0 --to-node-id B --to-port-kind 1 --to-port-index 0`）。
2. 两份 `.gia` 做**字节差**（同长段逐字节 xor）：
   * 若只有引脚内某个 varint 变了 → 边就在**引脚记录**里（把该字段与端口号对齐即得解码规则）；
   * 若出现一段**新消息**（新 field 号）→ 边是**图体里的新字段**；
   * 若**完全无差** → **导出不含边**（则 `.gia` 只能用于核节点，不能核接线）——这也是一个可交付的否定。
3. 判据：**A、B 的索引**必须出现在差里，否则该字段不是边。

> 三条分支都能一次定论。这比继续猜字段更快、更硬。

---

## 5. 调试日志 `.gia` 是什么（B 类）

`.runtime/beyond-save/pre-empty-control/2026-09-16_23-01-34_6_100000001.gia`（len 96253，64 条记录）：

* 顶层 = **64 个重复的 `field 1`（wire 2）**，每条记录字段固定为
  `1,2,4,5,6,7,8,9,10,21`（wire 混合）。
* 抽一条（第 0 条）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

* 它是**一份关卡/资源的调试日志**，**不是节点图**：没有 definitionId、没有引脚、没有类别三元组。
* 但它的**外层框架与 `.gil` 不同**（§1.3），所以放进同一个后缀是**厂商侧的命名重合**，不是同一格式。

**可解码性**：`gil_container.parse_fields` 能干净走完它的 8 字节头之后的部分（对全部 1230 个 B 类文件，
长度恒等式 0 例外）。要解它只需先把 §1.3 的 8 字节头切掉。

---

## 6. 生成一条 `.gia` 的命令（当仓里没有时）

仓里**有**（67 个 A 类），所以本节是补充；但要再产一条：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


* 命令 → 动作映射：`GRAPH_ACTIONS['export'] = 'export'`（`tools/authoring/author.py:57-58`）；
  子命令参数：`--request-id/--run-id/--name` 必备，非 create/lookup 还要 `--graph-id`（`author.py:476-484`）。
* **落点**：`.runtime/editor-bridge/exports/miliastra-bridge-<guid>/bridge-export-<32hex>.gia`，
  同目录另有 `<同名>.gia.reply.json`，内容形如 `{"receivedUtc":…,"rows":[]}`。
* **回执状态**：`.runtime/authoring/requests/<requestId>/result.json` 里
  `"status": "invoked-not-confirmed"`、`"officialPlaytestVerified": false`、`"persistenceVerified": false`
  ——**回执不确认，但文件内容是真的**（§4.2 已用 plan ↔ `.gia` 逐位对照证明节点表来自编辑器）。这就是
  "回执 ≠ 产物"的那层分野。

**文件落地后要看的三件事**：
1. 头 20 字节是不是 `…|00 00 00 01|00 00 03 26|00 00 00 03|…`，尾 4 字节是不是 `00 00 06 79`（`decode_container` 一跑即知）。
2. `payload.field 1 → field 13 → field 1 → field 1 → field 3` 的条数 = 节点数，且应与你的 plan 的 `nodes` 数目一致。
3. `payload.field 1 → field 5`：9 = 节点图（有节点表），69 = Lua 图（节点表为空）。

---

## 7. 给解码器作者的最小实现（照抄即可）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

> 调试日志 `.gia` 走另一条：先 `inner = u32be@4`，再 `parse_fields(b[8:8+inner])`。

---

## 8. 本轮没做的事（边界）

* 没有连桥、没有发 `export`，所以**§4.4 的差分实验未做**——"边"因此仍是**未解决**，而非"没有"。
* 没有枚举**全仓**（`find . -name '*.gia'`）的完整清单：只按 5 条 `.runtime/` 内模式扫到 1297 个；
  仓内其他目录（`mvp/`、`plugins/` 等）未扫（工具链的 recursive glob 在整仓上超时，故**收敛到 `.runtime/`**）。
* 没动 `tools/beyond-save/gil_container.py`（§1.2 的 docstring 缺口只记录，不改）。
* 所有 `.gia` 字节均来自仓内既有产物；**未**触碰 `AppData\LocalLow\miHoYo\`。

---

## 附：复现命令


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

