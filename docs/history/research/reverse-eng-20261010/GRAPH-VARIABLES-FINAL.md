> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 节点图变量（F1）— 最终判决

**调查日期**：2026-10-10。
**口径**：**只读、离线**。全程**未启停 helper、未提权、未连桥、未发任何 native/graph 请求**，未碰原神/编辑器进程，
未读写任何存档，未读任何图片/PDF（遵守本会话 HARD RULES）。证据只来自仓内文件：
①`data/node-contracts/variants/server/*.json`；②`tools/editor-bridge/Adapter/AuthoringGraph.cs`（逐行）；
③`.runtime/editor-catalog/`（反编译快照、textmap）；④仓内第三方工具快照
`.runtime/research-sources/ecosystem/Ayaya_Miliastra_Editor/`（**只读源码，未运行**）；
⑤`docs/official-docs/GRAPH-VARIABLES.json` + 官方章节原文。

> 本文件是 F1 的**终判**，不是 `GRAPH-VARIABLES-PROBE.md` / `GRAPH-VARIABLES-VERDICT.md` 的摘要。
> 它把前两者的"未知"再切一刀：**F1 是两个对象，不是一个** —— **访问器节点**（普通）与**变量定义表**（图级）。
> 三层分开标（CLAUDE.md §一.3）：**文档写了什么 / 工具能做什么 / 真机验证过什么**。本文**零真机**。

---

## 0. 判决

**一词：普通节点（ordinary）。**

任务问的是「`323/337/351` 是普通节点，还是需要图级属性」。**答案是前者**：它们就是普通节点，
`add-node` 放得下；`AuthoringGraph.cs` 的加节点闸门里**没有任何一条对"变量节点"做特判**。
**F1 的「节点层」是未建，不是做不到** —— 这是对旧「零入口 ⇒ 做不到」分类的**更正**。

**但这一句不能单独读，因为 F1 有两个对象**（这是与旧文档最大的分歧点）：

| 层 | 对象 | 判决 | 依据 |
|---|---|---|---|
| **节点层** | defId `323`(设置) / `337`(获取) / `351`(变化时) | **普通节点；`add-node` 可放置**（未建，非阻塞） | §2 |
| **定义层** | 图级变量表 `graph_variables`（引擎字段 `NQlKbxwmq6a`） | **图级属性；我方无写入口**（阻塞） | §3 |

**关键**：`323` 只是一个**访问器** —— 它按名引用一个**登记在图级表里**的变量。
一个「可用的节点图变量」＝ **访问器节点** ＋ **一条图级表记录**。**两件都要**，而且**是不同对象，不是二选一**。

⇒ 任务那句推断「既然是普通节点，那么图变量今天就能靠放 `323` 写入」—— **对了一半**：
*放得下* 为真（§2 坐实），但放完得到的是一枚**指向未登记变量的访问器节点**，不是一份可用的图变量（§3 坐实）。
所以「F1 只是未建」**不成立**；正确的切法是 **节点层未建 / 定义层阻塞**。

**旧文档漂移的根因**：`F1F2-variables-nodes.md:135 §7` 把「F2 卡点」写成「`graph.variables` 零入口」，
读者会把「零入口」读成"引擎/节点都没有" —— 那**两头都不对**：**节点有（普通节点）、引擎有（`L3mKOiPc6Zn` 等）**，
**缺的只是我方绑定 + 图级表那条**（`GRAPH-VARIABLES-PROBE.md §4` 已证引擎侧有原语）。
F1 的正确状态不是「不能」，也不是「能」，而是**两层各自判死**。

---

## 1. 引脚签名重导（任务第 1 步；逐字，含 file:line）

**方法**：逐个 `json.load` `data/node-contracts/variants/server/bucket-0{4,5,6}.json`，
按 `stableKey.definitionId` 取记录，打印 `ports[]` 的
`portKey / kind / direction / index / serverParamType / valueTypeNameRaw / valueTypeValueRaw / name.value`。
三处 `categoryVariant` 一律 `[10001,20000,22000,0]`、`pinsTruncated:false`。

### 1.1 defId **323 设置节点图变量** — `data/node-contracts/variants/server/bucket-05.json:3913`（名 `:3937`）

| portKey | 行 | kind | dir | idx | serverParamType | valueTypeNameRaw (vtv) | 端口名 |
|---|---|---|---|---|---|---|---|
| 1:0 | `:3956` | exec | input | 0 | 0 | `None` (0) | `""` |
| 2:0 | `:3992` | exec | output | 0 | 0 | `None` (0) | `""` |
| 3:0 | `:4028` | data | input | 0 | **6** | `5` (5) | **变量名** |
| 3:1 | `:4064` | data | input | 1 | **0** | `Generics` (**10000**) | **变量值** |
| 3:2 | `:4100` | data | input | 2 | **4** | `6` (6) | **是否触发事件** |

`resource.path = "Resource/Json/Beyond/Node/18273674412881068207.mihoyobin"`。
（逐字核对 `:4028-4138`：`3:0` 名 `"变量名"`、`3:1` `valueTypeValueRaw 10000`、`3:2` 名 `"是否触发事件"`。
五个引脚行号（`:3956/3992/4028/4064/4100`）均为本轮实测，窗口起点 `:3913`。）

### 1.2 defId **351 节点图变量变化时** — `data/node-contracts/variants/server/bucket-04.json:6573`（名 `:6597`）

| portKey | 行 | kind | dir | idx | serverParamType | valueTypeNameRaw (vtv) | 端口名 |
|---|---|---|---|---|---|---|---|
| 2:0 | — | exec | output | 0 | 0 | `None` (0) | `""` |
| 4:0 | `:6652` | data | output | 0 | **1** | `None` (0) | 事件源实体 |
| 4:1 | `:6688` | data | output | 1 | **2** | `1` (1) | 事件源GUID |
| 4:2 | `:6724` | data | output | 2 | **6** | `5` (5) | 变量名 |
| 4:3 | `:6760` | data | output | 3 | **0** | `Generics` (**10000**) | 变化前值 |
| 4:4 | `:6796` | data | output | 4 | **0** | `Generics` (**10000**) | 变化后值 |

`resource.path = "Resource/Json/Beyond/Node/15596561218457586184.mihoyobin"`。

### 1.3 附 defId **337 获取节点图变量**（任务要求的"getter"）— `bucket-06.json:3934`（名 `:3958`）

| portKey | 行 | kind | dir | idx | serverParamType | valueTypeNameRaw (vtv) | 端口名 |
|---|---|---|---|---|---|---|---|
| 3:0 | `:3977` | data | input | 0 | **6** | `5` (5) | 变量名 |
| 4:0 | `:4013` | data | output | 0 | **0** | `Generics` (**10000**) | 变量值 |

`resource.path = "Resource/Json/Beyond/Node/9277788526522933677.mihoyobin"`。

### 1.4 三件事（合同层可确认）
1. **获取（337）只有"按名取"一个入参**（`3:0` 变量名），出参是**泛型**（Generics/10000）。
2. **设置（323）是"按名写" + 一个 bool**（`3:2`，`serverParamType=4`，合同名 **`是否触发事件`**）。
3. **关键形态**：`323` 的 `变量值`（`3:1`）与 `337` 的 `变量值`（`4:0`）、`351` 的 `变化前/后值`（`4:3/4:4`）
   **全是 `Generics`（serverParamType=0, vtv=10000）** —— **泛型**。**具体类型不在合同里**，
   由**变量表**反推（§3.3）。这一条是本节唯一"超出引脚本身"的结论，也是 §3 的伏笔。

---

## 2. `AuthoringGraph.cs` 判定：它们是普通节点（任务第 2 步）

**结论：`323/337/351` 是普通节点。`add-node` 对它们没有任何特判；只要它们出现在活体注册表里，就能被放进图。**

### 2.1 `add-node` 的全部闸门（逐行，file:line）

`AuthoringGraph.cs:320-345`（`action=="add-node"`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`authorCategory` 由图的 kind 派生（`:32` `AuthorCategory(k) => {10001,k,22000,0}`），服务端图即
`{10001,20000,22000,0}` —— 与三处合同的 `categoryVariant` 逐元素相等。

**唯一的按 id 特判是 `definition.Id==2`**（`AuthoringGraph.cs:326` `RequireAuthorBranchDefinition`，
双分支的签名校验）。**没有任何按 id 排除变量的分支** —— `323/337/351` 走的是与
`1/2/71/79/83`（已落地那 9 个）**完全同一条**通用路径。

### 2.2 逐闸核对 `323/337/351`（数据来自 §1 的三条合同）

| 闸 | 判据 | `323` | `337` | `351` |
|---|---|---|---|---|
| G1 kind==6 | `:322` | ✓ 合同 `graphKindRaw:20000` | ✓ | ✓ |
| G2 类别精确相等 | `:322` | ✓ `[10001,20000,22000,0]` | ✓ | ✓ |
| G3 恰一个 model | `AuthoringGraph.cs:323` | ✓ 唯一 id | ✓ | ✓ |
| G4 至少 1 个 pin | `:340` | ✓ 6 pin | ✓ 2 pin | ✓ 5 pin |
| **⇒ 静态可放置** | | **✓** | **✓** | **✓** |

**⇒ 它们**（按构造）**是可放置的普通节点**；`add-node` 只需 `definitionId=323/337/351` 即可。
（G5「native 是否接受」是**运行时闸**，本轮未执行，见 §4 未证项 —— 但**它与节点是不是普通节点无关**：
G5 对任何定义都存在，不是变量节点独有的。）

### 2.3 因此**节点层**的判决

**F1 的节点层是「未建」，不是「做不到」。** 旧文档把 F1 整体记为「阻塞/零入口」，在"能不能把变量访问器
放进图"这一层上是**错的** —— 那只是**还没放**，不是**放不下**。

---

## 3. 第二层：变量**本身**是图级的（这是与"纯节点"的分野）

节点是普通节点，**但变量不是节点**。变量登记在一张**图级表**上，节点只是它的**访问器**。三条独立证据：

### 3.1 引擎侧：图模型持有一张独立的变量列表字段 + 建/插/删方法（**本轮逐行复核**）

`decomp/BeyondEditor/cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH.cs`
（＝绑定档案里映射到 `E8xv5pXu77T6046o5sVM...` 的那张 Kind 9 图模型）：

| 行 | 实测 | 内容 |
|---|---|---|
| `:281` | 逐字复核 ✓ | `private rgfCjhijuAbCoKxWU8Lu<LppcPfKAgGBUlYusKLtc> NQlKbxwmq6a;` ← **节点图变量列表**（图级字段） |
| `:420` | 逐字复核 ✓ | `public rgfCjhijuAbCoKxWU8Lu<LppcPfKAgGBUlYusKLtc> pSJKOe1FuCR()` 体 `return zkBiU2ieGW3(ref NQlKbxwmq6a);` ← **读该列表** |
| `:2489` | 逐字复核 ✓ | `public void IPaKOuvl7c1(LppcPfKAgGBUlYusKLtc P_0)` ← **删变量** |

元素类型 `LppcPfKAgGBUlYusKLtc` 的定性锚点（`GRAPH-VARIABLES-PROBE.md §4.2`，本轮采信）：
`resourceItemTextType = "UI_BEYOND_ASSIST_EDITOR_BP_VARIABLES"` →
textmap `.runtime/editor-catalog/textmap-chs.json:34313-34315` → `"text": "节点图变量"`（**本轮逐字复核**）。
同族撤销标签 `UI_BEYOND_EDITOR_WPF_HISTORY_CV_NEW/EDIT/DELETE` → textmap
`:35720/35725/35730` = **`新建节点图变量` / `修改节点图变量` / `删除节点图变量`**（**本轮逐字复核**）。

**意义**：图模型把"变量"作为一个**图级对象**持有，并有独立的**新建/修改/删除**方法 —— 这是
「变量 ≠ 节点」的**结构证据**。这条 `新建` 原语（`zVUKO3av5Re`/`L3mKOiPc6Zn`）**不在**我方绑定档案里
（`EditorBindingProfile.Generated.cs` 对 `pSJKOe1FuCR/NQlKbxwmq6a/L3mKOiPc6Zn/IPaKOuvl7c1/EF2KOI3tZ9E`
**grep 0 命中**，本轮实测），所以**我方无写入口**。

### 3.2 官方侧：**先"新增"变量，再"放/拖"节点**（官方章节原文）

`.runtime/research-sources/official-docs-expanded/mhtshailzs7w.txt`（＝ `docs/official-docs/GRAPH-VARIABLES.json` 源）：

> 「四、节点图变量的编辑 1.节点图变量页签入口 … 2.**新建节点图变量** 页签操作与自定义变量类似，可以新增、修改已配置的节点图变量
> 3.在节点图中使用节点图变量 … 此外，可以通过**拖拽节点图变量中的变量到编辑区域**来创建节点图变量的操作节点」

**读法**：官方流程是 **①在页签"新增"变量 → ②再把变量拖进画布生成设置/获取节点**。
**变量先登记，节点后引用** —— 这与 §3.1 的结构吻合。且官方明写「同节点图内**不可重名**」
（⇒ 存在一个**图级命名登记表**，否则无法判重）。

### 3.3 第三方工具侧：节点 `变量值` 的类型**由变量表反推**（我方可读源码，未运行）

`.runtime/research-sources/ecosystem/Ayaya_Miliastra_Editor/`（**只读**）：

- `engine/graph/models/graph_model.py:253`：`self.graph_variables: List[dict] = []  # 节点图变量列表`
  —— 图模型上**另外**挂着变量表；`engine/graph/models/graph_serialization.py:136` 把它序列化为 `"graph_variables"` 字段。
- `engine/graph/port_type_effective_resolver.py:347-352`：
  `def _resolve_graph_variable_type_by_name(graph_model, variable_name)` —— **"从 `GraphModel.graph_variables` 里按变量名查到变量类型"**；
  `:831-833` 注释逐字：**"`变量值` 的具体类型必须来自 `GraphModel.graph_variables`（变量定义表），否则 UI 会显示为泛型/字符串"**
  （分支条件 `title in {"获取节点图变量","设置节点图变量"}`）。
- `engine/graph/graph_code_parser.py:824`：**"`graph_variables` 未写入时，【设置节点图变量】的 `变量值` 类型无法从变量表反推"**。
- `engine/validate/rules/code_structure/graph_vars_declaration.py:30`（`rule_id …graph_vars_decl`、`default_level=error`）：
  **"【设置/获取节点图变量】的『变量名』必须在 GRAPH_VARIABLES 中声明"**。
- （反向证据，须并列）`app/runtime/engine/game_state.py:150-164` 的**本地模拟器**里，
  `set_graph_variable` / `get_graph_variable` 只对 `self.graph_variables` 这个 dict 按键读写，
  **运行时不强制声明**。⇒ **「运行时是否硬性要求该登记条目」= 未证**（见 §4）。

**读法**：`323` 的 `变量值` 是**泛型**（§1.4），它的具体类型**只在变量表里**；`Ayaya` 把"未声明却用"
判为 **error**。⇒ **节点是访问器，变量定义在图级表。**

### 3.4 §3 的净结论

**变量 = 图级表记录；节点 = 访问器。** 我方的 `add-node` 能放**访问器**，但**放不出那条表记录**
（表记录的写入口 `L3mKOiPc6Zn` 未登记；`call-bridge.ps1` 的 op 面里也没有任何 graph-variable 写 op）。
⇒ **光靠放 `323` 得不到"可用的图变量"**。

---

## 4. 判决详述 + 更正 + 未证项

### 4.1 一词判决（任务第 4 步）
**普通节点（ordinary）。** —— 直接回答任务的问题：`323/337/351` 是普通可放置节点，
`add-node` 无特判（§2，`AuthoringGraph.cs:320-345`）。**F1 的节点层是未建，不是阻塞。**
**这一句是旧分类的更正**：旧文档的「`graph.variables` 零入口 ⇒ 做不到」在"节点层"上是假的。

### 4.2 与之并列的完整判决（不是对冲，是第二个对象）
**F1 的另一半——变量定义——仍是图级属性、且无写入口**（§3）：
图模型 `:281 NQlKbxwmq6a` 持有变量表、`:420` 可读、`:2489` 可删；`Ayaya` 证明 `变量值` 泛型**由该表反推**；
官方流程是**先"新增"再引用**。⇒ 表格自洽：

| 判据 | 节点层（323/337/351） | 定义层（变量表） |
|---|---|---|
| 谁持有 | 图模型节点表（**我方已用** `BWmKmyL3bM7`） | 图模型 `NQlKbxwmq6a`（**我方未登记**） |
| 写入口 | ✅ `add-node`（`:320`） | ❌ 无（`L3mKOiPc6Zn` 未登记 + op 面无写 op） |
| 判决 | **未建** | **阻塞** |

**⇒ 对 `F1F2-variables-nodes.md:135 §7`「F2 卡点 = `graph.variables` 零入口」的更正**：
应写成 **「节点面无入口错判；真正的缺口是图级变量表的登记原语未绑定」**。
`MODULE-PLAN-6.md:22` 与 `:75-90` 的自相矛盾也随之消解：F1 对六模块**不是硬前置**，
但理由**不是**"做不到节点"，而是"**变量定义那张表还没有写入口**，而节点本身随时能放"。

### 4.3 未证项（明确标出，勿当结论）
- **H-runtime**：引擎是否**硬性要求**变量表里存在同名条目（否则 `323` 无效 / 还是按名动态建）？
  **未证**。正反证据并列于 §3.3（`Ayaya` 校验器判 error ⇆ `Ayaya` 本地模拟器不强制）。
  这条只能靠 §5 的只读探针或真机落盘来压。
- **H-live-registry**：`323/337/351` 在**活体注册表**（`EditorAdapter.Resources()`）里是否与合同一致？
  合同库是**录制的投影**，G1–G4 跑在合同库上（§2.2）；活体漂移会使"可放置"失效。
  `NODE-PLACEABILITY.md §5.1` 已标此为通用 caveat；本轮未连桥，**未证**。
- **G5 native 接受**：`add-node` 后 `AUTHOR_NODE_READBACK_FAILED` 是否触发 —— **未执行**。

---

## 5. 若要把"未证"压成"已证"（**只读，不跑**）

**一条只读请求即可**（照既有只读探针 `pin-slots`（`AuthoringGraph.cs:354-372`，返回 `graphModified:false`）的形状）：
在编辑器开着、且当前图**已有一个已声明变量**的前提下，做一次 `graph-variables` 只读反射
（读 `graph.Model` 上 `NQlKbxwmq6a` 的元素 → 打印 `key`/`serverParamType`），把 §3.1 的结构与页签内容对上。
**零 mutation、不 save、不 export**。**在只读探针通过之前不要先放 `323`** —— 那会把"能不能写"和"写得对不对"混在一起
（`GRAPH-VARIABLES-PROBE.md §5.3` 同主张，本轮沿用）。

> **本轮未做**：未实现代码；未调用任何原生方法；未启停 helper/game/editor；未写任何存档；
> 未把 §3.4「变量在图级表」读成「节点做不到」（那是两件事），也**未**把 §2「节点是普通节点」读成
> 「图变量今天就能用」（还差那张表）。

---

## 附：复现（全部只读、离线）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

