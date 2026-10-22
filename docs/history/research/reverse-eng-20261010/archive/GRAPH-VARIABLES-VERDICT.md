> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 节点图变量（graph.variables）写入能力 — 核实判决

调查日期：2026-10-10。**只读、离线**：未启停 helper、未提权、未连桥、未发任何 native/graph 请求，
未碰原神/编辑器进程、未读写任何存档、未读任何图片/PDF。本文件是 `GRAPH-VARIABLES-PROBE.md`
（下称"探针"）的**独立复核**，不是它的摘要——§1/§2 重跑了它的关键命令并把真数记下来，
§4 列出**探针与实测不一致的地方**（有几处），§5 才给判决。

---

## 0. 一句话判决

**未知。**

**最强单条证据**：**同一族「节点图变量」API，在我方工具层零登记，在引擎装配层的同一张图模型上确实存在，
而那张图模型正是 bridge 已经拿在手里的 `graph.Model`。**

- 工具层＝空：`EditorBindingProfile.Generated.cs` 全文对变量访问器符号
  `pSJKOe1FuCR / NQlKbxwmq6a / L3mKOiPc6Zn / IPaKOuvl7c1 / EF2KOI3tZ9E` **0 命中**（实测，§2.3），
  且 `EditorBindingProfile.cs:117` 的 fail-closed 用抛错的字面量正是 **`UNREGISTERED_SYMBOL`**——
  即使照抄快照里的名字去 `B(...)` 解析，也会在运行**之前**被拒。
- 引擎层＝有：同一批变量方法（新建/插入/删除）声明在
  `.runtime/editor-catalog/decomp/BeyondEditor/cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH.cs:2374/2402/2489`，
  且被 `resolved/` 里**至少 4 个别的编辑器类**调用（§3.4）。**这推翻了"引擎没有入口"。**

这一"一半空、一半有"的劈叉，使 **不能**（被引擎侧反例证伪）与 **能**（从未执行，且快照可能过期＝H4）
都站不住，唯一诚实的一词是 **未知**。判决的可判决部分（我方工具现状＝**不能**）与悬而未决部分
（引擎原语能否被 bridge 反射采纳并落盘）分开列在 §5，不要再合读。

---

## 1. 引脚签名重导（任务第 1 步）

**方法**：直接读 `data/node-contracts/variants/server/*.json`（8 个 bucket，逐个 `json.load`），
按 `stableKey.definitionId` 取记录，打印 `ports[]` 的 `portKey/kind/direction/index/serverParamType/
valueTypeNameRaw/name.value`。**全部 500 条服务端定义的记录字段一律同构**（`pinsTruncated:false`）。

### 1.1 defId 323「设置节点图变量」——`data/node-contracts/variants/server/bucket-05.json:3913`

| portKey | 起始行 | kind | dir | idx | serverParamType | valueTypeNameRaw | 端口名 |
|---|---|---|---|---|---|---|---|
| 1:0 | `:3956` | exec | input | 0 | 0 | `None` | `""` |
| 2:0 | `:3992` | exec | output | 0 | 0 | `None` | `""` |
| 3:0 | `:4028` | data | input | 0 | **6** | `5` | **变量名** |
| 3:1 | `:4064` | data | input | 1 | 0 | `Generics`(valueTypeValueRaw **10000**) | **变量值** |
| 3:2 | `:4100` | data | input | 2 | **4** | `6` | **是否触发事件** |

`resource.path = "Resource/Json/Beyond/Node/18273674412881068207.mihoyobin"`（`:3939`）。
逐字复核 `3:2` 的 `bucket-05.json:4100-4138`：`"serverParamType": 4`、`"name": {"state":"recorded","value":"是否触发事件"}`。

### 1.2 defId 351「节点图变量变化时」——`data/node-contracts/variants/server/bucket-04.json:6573`

| portKey | 起始行 | kind | dir | idx | serverParamType | valueTypeNameRaw | 端口名 |
|---|---|---|---|---|---|---|---|
| 2:0 | `:6616` | exec | output | 0 | 0 | `None` | `""` |
| 4:0 | `:6652` | data | output | 0 | 1 | `None` | 事件源实体 |
| 4:1 | `:6688` | data | output | 1 | 2 | `1` | 事件源GUID |
| 4:2 | `:6724` | data | output | 2 | 6 | `5` | 变量名 |
| 4:3 | `:6760` | data | output | 3 | 0 | `Generics`(10000) | 变化前值 |
| 4:4 | `:6796` | data | output | 4 | 0 | `Generics`(10000) | 变化后值 |

`resource.path = "Resource/Json/Beyond/Node/15596561218457586184.mihoyobin"`（`:6600`）。

### 1.3 附：defId 337「获取节点图变量」——`bucket-06.json:3934`

| portKey | kind | dir | idx | serverParamType | valueTypeNameRaw | 端口名 |
|---|---|---|---|---|---|---|
| 3:0 | data | input | 0 | 6 | `5` | 变量名 |
| 4:0 | data | output | 0 | 0 | `Generics` | 变量值 |

`resource.path = "Resource/Json/Beyond/Node/9277788526522933677.mihoyobin"`。

### 1.4 身份交叉核对（对探针 §1 的独立确认）

`docs/editor-catalog/NODE-CATALOG.md:846-848` 三行与上表**同一身份、逐字一致**：
`846`→`18273674412881068207 | 323 | 设置节点图变量 | ... | 变量值、是否触发事件、变量名`；
`847`→`... | 337 | 获取节点图变量`；`848`→`... | 351 | 节点图变量变化时`。

**三项结论（与探针 §1.4 同）**：
1. 获取（337）只有"按名取"1 个入参，出参是泛型；
2. 设置（323）是"按名写 + 1 个 bool"，bool 端口 `serverParamType=4`、合同名 **`是否触发事件`**；
3. **探针的纠正确实成立**：`F1F2-variables-nodes.md:135`（§8 第 5 条）把 323 的 `3:2` 记作 `is_bp_var`，
   而合同/目录/官方章节三处的名字都是 **`是否触发事件`**。合同为准。

> 说明：`portKey` 是**导出时按 (kind,index) 合成**的（每条 port 都写着
> `portKeyBasis": "derived from the recorded pin kind and index; no recording carries a port identifier"`），
> 不是引擎给的端口 id。这解释了为什么同一节点在合同里没有 `portId`——见 §5 实验的读回设计。

---

## 2. "无写入者" grep 复核（任务第 2 步）

探针的 repro 段只写了一条 grep（那 5 个符号）。本节把它**连同它依赖的两条更宽的检索**一起重跑，
并把**实测计数**列出（探针原文 §3 说"307 个 legacy 符号、313 条 contract"，这两条对；`9 条` 那条不对，见 §4.1）。

| # | 检索 | 命令（全部 Bash grep / python，已避 Grep 工具跳 `.runtime` 的坑） | 实测 |
|---|---|---|---|
| 2.1 | 探针主 grep：变量访问器符号在绑定档案里 | `grep -n "pSJKOe1FuCR\|NQlKbxwmq6a\|L3mKOiPc6Zn\|IPaKOuvl7c1\|EF2KOI3tZ9E" tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs` | **0 命中**（exit 1） |
| 2.2 | 同 5 符号在**我方全部工具源码**（Adapter+CLI） | `grep -rIn <同5符号> tools/` | **0 命中** |
| 2.3 | 同 5 符号在**引擎快照**（decomp+resolved+annotated） | `grep -rIl <同5符号> .runtime/editor-catalog/{decomp,resolved,annotated}` | **10 个文件**（引擎侧有，且分布 >1，见 §3.4） |
| 2.4 | 档案规模：legacy 符号数 / contract 数 | python 解析 `EditorBindingProfile.Generated.cs` | **LegacySymbols = 307**（`:8` 起）、**contract = 313**（`new BindingContract(`）、映射对 = **307**（`:321` 起 `new Dictionary<string,string>`） |
| 2.5 | 桥的 op 面里有没有"变量写"op | python 解析 `tools/editor-bridge/call-bridge.ps1` 的 `$Operation` `ValidateSet` + `ManagedBridge/BridgeServer.cs` 的 `case "…"` | `ValidateSet` 与 `case` 标签的条数见 tools/gameplan/tests/test_doctrine.py；含 `variable` 的 op **只有 5 个**，且**全部**是客户端脚本变量探针（`inspect/add/delete/add-int/reset-…-client-script-variable-probe`）——**没有**任何 graph-variable / 图变量写入 op |
| 2.6 | `graph.variables` 在能力清单里的状态 | `tools/authoring/interface_inventory.json`（`/capabilities[18]`） | `"status": "research"`、`"entry": null` ✓（与探针 §0 一致） |
| 2.7 | 全档案里"同时带 setter 和 getter"的类型 | python 遍历 313 条 contract，按 `(…,ctx):Void` 找 setter、按 `():…` 找 getter | 带 `(…,ctx):Void` setter 的类型**只有 2 个**：引脚值对象 `iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG` 与客户端脚本模型 `EngUDvX1xc7DWWwYrrw1.vVUju1X1mM5GsVZX9XiF`；**同时**带 getter 的**只有 1 个**（引脚值对象）——即**没有任何图级 getter/setter 对**（探针 §3.2 成立） |
| 2.8 | 三个"读回 getter 未登记"（探针 §3.4/H5） | `grep -c "ur7KK2NiYZ4\|ngMKKCVBuMA\|RJCKKnWqvLO"`（对档案） | 各 **0**（string/float/bool 读回 getter 确实不在档案） |

**"无写入者"的结论（实测口径）**：在**我方工具源码 + 桥 op 面 + 绑定档案**这三处，
**不存在**任何把"节点图变量"写到图模型的入口。这是**仓库内我方代码**范围内的精确负面结论；
它**不**排除引擎里有原语（§3 证明有），也**不**排除反编译语料里存在**折叠成常量**的命令名
（那是我方这类"明文符号检索"的盲区——同 `COMPONENT-WRITER-MINE.md` §1/§5 的边界诚实）。

---

## 3. 引擎侧复核（对探针 §4 的独立确认）

探针 §4 是本问题的重量级发现，本节逐条复核（全部只读）。

### 3.1 图模型持有变量列表（字段）

`decomp/BeyondEditor/cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH.cs`（＝绑定档案 `:515` 前向映射到
`E8xv5pXu77T6046o5sVM.vUK4LLXuq7BbA0L017eJ` 的那张 Kind 9 图）逐行核对 **全部命中**：

| 探针行 | 实测该行 | 内容 |
|---|---|---|
| `:261` | ✓ | `opVKb4A3SbP` `NN9ApKijClQeqGSyUdAe<uint, hdyYDbKbQQXSb23boi1e>`（节点表；我方经 `EditorAdapter.cs:213` 的 `K61KONg4LUT` 用） |
| `:263` | ✓ | `jOeKbv7xke0`（边表） |
| `:267` | ✓ | `OcZKbA2OAsr` `rgfCjhijuAbCoKxWU8Lu<RuygVDipeHdMkeOglACP>`（撤销栈） |
| `:277` | ✓ | `a2JKb7KDLSD`（`u4m…` 条目，疑批注） |
| `:281` | ✓ | **`NQlKbxwmq6a` `rgfCjhijuAbCoKxWU8Lu<LppcPfKAgGBUlYusKLtc>` ← 节点图变量列表** |
| `:283` | ✓ | `vl8Kbd1XFLA`（单值持有） |

### 3.2 元素类型＝「节点图变量」

`decomp/…/POEL6HKAWCtpYUVxs1RL.LppcPfKAgGBUlYusKLtc.cs`：`:40` `key<string>` ✓、
`:42` `value<JVhTwtKizlScEvUHNJeZ>` ✓、`serverParamType<uint>` ✓、`structId` / `valueStructId` ✓、
`:83` `kekKARjBrNN():<bool>` ✓。
**定性锚点**：`resourceItemTextType`（annotated `:64`）＝字面量
`"UI_BEYOND_ASSIST_EDITOR_BP_VARIABLES"`，textmap `.runtime/editor-catalog/textmap-chs.json:34313`
→ `"text": "节点图变量"` ✓（逐字复核）。
textmap 其余 4 条也逐字命中：`:35538` `"变量_{0}"`、`:35718` `"新建节点图变量"`、
`:35723` `"修改节点图变量"`、`:35728` `"删除节点图变量"`。

### 3.3 图模型上的建 / 插 / 删 / 改名（方法签名）

| 行 | 实测签名 | 判定 |
|---|---|---|
| `:420` | `public rgfCjhijuAbCoKxWU8Lu<LppcPfKAgGBUlYusKLtc> pSJKOe1FuCR()`，体 `return zkBiU2ieGW3(ref NQlKbxwmq6a);` | **读变量列表** ✓ |
| `:426` | `public qHO2mNiRnZr4WY4hDrki<LppcPfKAgGBUlYusKLtc> EF2KOI3tZ9E()`，体 `return …(ref vl8Kbd1XFLA);` | 单值持有读 ✓ |
| `:2374` | `public void zVUKO3av5Re(int P_0, uint P_1, uint P_2, ctx P_3=null)`——造元素 → 插到 index → 设 `resourceItemName(from P_0+1)` | **新建并插入** ✓ |
| `:2402` | `public void L3mKOiPc6Zn(int P_0, LppcPfKAgGBUlYusKLtc P_1, ctx P_2=null)` | **插入已有** ✓ |
| `:2489` | `public void IPaKOuvl7c1(LppcPfKAgGBUlYusKLtc P_0)`，体 `…T0lhrA5npQ7).X66ijdVvJ0k(P_0)` | **删除变量** ✓ |
| `:2517` | `public void veTKO7bErSv(int P_0, ctx P_1=null)`——`P_0<0 || P_0>=Count` 即 return | 按索引操作 ✓ |
| `:2432` | `private string BgAKOKAeuul(int P_0)`；模板字面量在 `annotated:2444`＝`"UI_BEYOND_ASSIST_EDITOR_ADVANCED_DATA_VAR_INDEX"`；越界字面量在 `annotated:2477`＝`"invalid variable name!"` | 默认名生成器 ✓ |

### 3.4 复核时**新增**的证据（探针未写、但强化其结论）

`grep -rIl pSJKOe1FuCR .runtime/editor-catalog/resolved/` 命中 **5 个文件**（不止 graph 模型那 1 个）。
其中 4 个是**调用方**；`resolved/` 里带 `/* -> cwoW1eKm…::pSJKOe1FuCR */` 注释，把"谁在对谁调"钉死：

- `dAtgmguJDM695h1j7Kq1.YERc7quJdIp9hhrBVH4N.cs:1367/1372`——遍历变量列表并比 `变量名`（列表 UI）；
- `IGM4phuFSEJRrGVxhflB.SDrmqkuFCEYB66g31gcj.cs:347`——`IEnumerator<LppcPfKAgGBUlYusKLtc>` 枚举（序列化/拷贝路径）；
- `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:13319/13331`——按下标取变量 + `Count`；
- `PndJBMuSx42kyh79sKL1.DYE3yjuSYLuDuB5FIQRw.cs:721/729/731`——读写前 `!= null` 判定。

**意义**：变量子系统是**活代码、且有多个编辑器内调用方**，不是死方法。这比探针的单文件证据更强。

### 3.5 我方适配器确实已经握着这张图模型

`EditorAdapter.cs:18` 用 legacy 名 `B("cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH")` 解析图模型；
`AuthoringGraph.cs:342/561/654/759` 在它上面调 AddNode（`BWmKmyL3bM7`）、
`:452/583/666/771` 调 Link（`LapKOOcuGY1`）；`AuthoringGraph.cs:610` 注释原文 **"No variable CRUD."**。
即：**写变量的原语长在"我方已经在反射调用其它方法的那个对象"上**——这是"未知"而非"不能"的结构原因。

---

## 4. 探针与实测不符之处（纠正清单）

核实的目的包括"把结论钉死"。以下 4 处是与探针原文不完全一致的地方，按"是否有实质影响"排序：

1. **§3.3「图模型类型在档案里的全部 contract（9 条）」——实为 10 个成员 / 11 条 contract 行。**
   实测 `grep -c 'new BindingContract("E8xv5pXu77T6046o5sVM.vUK4LLXuq7BbA0L017eJ"'` = **11**，
   其中 1 条是类型自身声明（`:825`，`BindingKind.Type`），其余 **10** 条成员：
   `:692`(AddNode)、`:730`(节点表)、`:738`(Link)、`:744`(Id)、`:817`(字段)、`:844`(字段)、
   `:866`(InsertNode)、`:915`(Disconnect)、`:934`(边表)、`:941`(RemoveNode)。
   探针正文实际**逐条列了 10 个**（最后写作"`:844`+`:817`(两个字段)"），只是抬头数字写成"9 条"。
   **实质影响：无**（10 条里同样没有一条是变量集合的 getter/Insert/Remove），但数字应改为 **10 成员**。

2. **§3「307 个 legacy 符号、313 条 contract」——对。** 实测 LegacySymbols `:8` 起 = **307**、
   `new BindingContract(` = **313**、映射对 `:321` 起 = **307**。**探针此处无误**（列出来以免与 #3 混淆）。

3. **桥 op 面计数**：探针本身未给数；它援引的 `F1F2-variables-nodes.md:137`（§8 第 7 条）写
   旧报告写「135（`ValidateSet`）/ 136（`case` 标签）」。**现值见 tools/gameplan/tests/test_doctrine.py**（`ValidateSet` 无重复值，
   `case "…"` 的标签数同源）。CLAUDE.md §五的 op 数与 **ValidateSet** 口径一致，两者均现派生自 tools/gameplan/tests/test_doctrine.py。
   **实质影响：无**（无论取哪个历史计数，含 `variable` 的 op 都只有那 5 个客户端脚本探针）。

4. **§2.2 表里 `K17XuvJmjm3` 行引 `AuthoringGraph.cs:306`——该行实际用的是另一个符号 `MexKm2jjjVm`。**
   `grep -n "K17XuvJmjm3" tools/editor-bridge/Adapter/AuthoringGraph.cs` = 0 命中；
   `:306` 是 `…GetMethod(B("MexKm2jjjVm"),…)`。`K17XuvJmjm3` 确在 `Generated.cs:744`（`():System.UInt32`）。
   **实质影响：无**（"适配器用了 graph.Id"这一点由 `:306` 自身 + `Generated.cs:744` 独立成立），
   但把两个 Id 类符号并成了一行。

**未发现的错误**：§1 引脚签名（323/351/337 全表逐字对）、§4.1/§4.2/§4.3/§4.4 的行号与字面量
（含 `invalid variable name!`、`变量_{0}`、三个 CV 撤销标签）、§3.1 的 5 条 getter/setter 行号与
"未登记 getter"（§3.4）、§0 的 `graph.variables` 状态——**全部实测通过**。

---

## 5. 判决（任务第 3 步）

### 5.1 一词判决：**未知**

分三层说清（不要把三层合读）：

| 层 | 判决 | 依据（本次实测） |
|---|---|---|
| **工具现状**（我方代码/桥 op/档案） | **不能** | §2.1/2.2 = 0 命中；`EditorBindingProfile.cs:117` fail-closed 抛 `UNREGISTERED_SYMBOL`；§2.5 无写入 op |
| **引擎装配**（静态） | **有原语** | §3.1-3.3 变量列表字段 + 建/插/删/改名方法；§3.4 有 ≥4 个编辑器内调用方 |
| **真机**（执行/落盘/导出） | **零执行、未验证** | 本轮未连桥、未发报文；仓库内无任何"写节点图变量"的运行产物 |

**为什么不是「能」。** 唯一能给"能"的证据是真机回执 + `.gil`/导出字节差分（CLAUDE.md §四：
`ok:true` 单独不证明持久化）。至今**没有任何一次执行**。且 §3 的装配快照是**legacy 代际**的
（`EditorAdapter.cs:18` 用 legacy 名解析，档案把它前向映射到现名），**现名是否仍是这些符号 = H4，未核**。

**为什么不是「不能」。** §3 已证引擎侧存在完整原语，且长在 bridge 已经反射调用的 `graph.Model` 上。
判"不能"需要一个反例不存在，而 §3.4 的 4 个调用方恰好是反例。

**所以：未知**——但这是**钉死的未知**，不是漂移：它的两个边界（工具＝不能、引擎＝有）都已静态判死，
剩下的**只有一个**可执行问题，下面就是那个实验。

> 关于文档漂移：`MODULE-PLAN-6.md` 自相矛盾——`:22` 写"F1（`graph.variables`）不再是硬前置"，
> 而 `:75-90`（§二表格）仍写"**F1+F2 是硬前置**"。判"未知"后，正确姿势是
> `:22` 的那句成立（不阻塞六模块），但**不是**因为 F1"做不到"（那会被 §3 证伪），
> 而是因为"能不能做"**尚未判**——别把"未判"当成"做不到"，也别把"引擎有"当成"我们能写"。

### 5.2 那个定生死的实验（**一条只读请求，不跑**）

**目标**：把 §3 的静态推断一次压实成真机证据，且**零 mutation**——照 `author-graph` 现有只读探针
`pin-slots`（`AuthoringGraph.cs:354-372`，返回 `:360` 起已带 `graphModified:false`）的形状做一条同构的只读 action。

**前置（纯离线、分钟级，消化 H4）**：用 `tools/editor-bridge/dump-pe-functions.py` 一类的**静态**手段
对**当前**的 `BeyondEditor.dll` 复核 §3.1-3.3 的那些成员在**当期名字**下是否仍在
（快照已是 legacy 代际，现名可能已变）。

**请求形状**（在编辑器开着、且图上「节点图变量」页签已有 N≥1 个变量的前提下）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**实现要点**（一条反射链，与 `pin-slots` 同形）：
1. 先把 §3.3 的变量列表 getter（legacy `cwoW1eKm…A8NrPMKmnpQkIiiyYetH::pSJKOe1FuCR`，现名以 5.2 前置为准）
   作为**一个**符号补进 `EditorBindingProfile.Generated.cs` 的映射表（现为 307 对）；
2. 处理体：`var list = graph.Model.GetType().GetMethod(B("<getter>"), Fields)!.Invoke(graph.Model, null);`
   再对每个元素投影它的 `key`（名字）与 `serverParamType`（类型号）；
3. 返回体照 `pin-slots` 的旗标形状：
   `{ ok:true, status:"graph-variables-read-only", graphId, count, items:[{name, serverParamType, structId, valueStructId}, …],
      nativeConstructorsInvoked:false, graphModified:false, sentToGame:false,
      persistentSaveVerified:false, runtimeVerified:false }`。

**判读规则（一次定生死）**：
- 若 `count == N` 且 `items[].name` 与页签里的变量名**逐字相等** ⇒ H1（运行时节点按名引用的就是这份列表）、
  H2 立判，且写路径（`L3mKOiPc6Zn` 插入）**已有半把握**——此时把判决从"未知"推向"能（待写验证）"；
- 若 `count` 恒为 0、或该调用抛错 ⇒ §3 的那份列表是**别的东西**，回炉重判（判决留在"未知"或转"不能"）。

**为什么是这一条**：它把"能不能写"降维成"能不能读"，**成本 = 一个符号 + 一条请求**，
不 save、不 export、不碰存档；且在只读探针通过**之前**不应先做建变量
（那会把"能不能写"和"写得对不对"两件事混在一起——探针 §5.3 同此主张）。

---

## 附：复现（全部只读、离线）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**未做**：未实现任何代码；未调用任何原生方法；未启停 helper/game/editor；未写任何存档；
未把 §5.1 表中"引擎有原语"读成"我们能写"。
