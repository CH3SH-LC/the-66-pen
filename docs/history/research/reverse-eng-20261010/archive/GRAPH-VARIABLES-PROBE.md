> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# F1 节点图变量（graph.variables）逆向探针

调查日期：2026-10-10。**只读、离线**：全程未启停 helper、未提权、未连桥、未发任何 native/graph 请求、
未碰原神/编辑器进程、未读写任何存档。所有证据来自仓内文件（节点合同、适配器源码、绑定档案、
`.runtime/editor-catalog/` 下的**反编译快照与还原字符串**、textmap）。

**一句话结论**：`graph.variables` 在我方工具层（bridge 的 op 面（见 tools/gameplan/tests/test_doctrine.py）、`AuthoringGraph.cs`、绑定档案）里
**确实零入口**——这一点**成立**；但**「编辑器原生没有这个入口」不成立**。反编译快照证明
**Kind 9 节点图模型自己就持有「节点图变量」列表**，且原生提供了**建/插/删/改名**方法，
编辑器自己的撤销标签把它们叫 **「新建/修改/删除节点图变量」**。
即：缺口在**我们的绑定**，不在引擎。这与 CLAUDE.md §一「能做的事取决于我们逆向了多少」一致。

---

## 0. 三层标注总览（先说清哪层是哪层）

| 层 | 本条结论 |
|---|---|
| **文档写了什么**（官方语料） | 节点图变量仅在服务端图、图内作用域、有「对外暴露」开关、上限 100（见 `F1F2-variables-nodes.md`）。 |
| **工具现在能做什么**（我方绑定） | `graph.variables`：`status: research`、`entry: null`（`tools/authoring/interface_inventory.json` 的 `graph.variables` 行）；适配器无任何通往图级属性的路径（本文 §2）。 |
| **引擎装配里有什么**（本轮新发现，静态） | 节点图模型**持有**变量列表 + **提供**建/插/删/改名方法；撤销历史枚举含「新建/修改/删除节点图变量」（本文 §4）。 |
| **真机验证过什么** | **零执行**。§4 全部是**静态**结论（反编译 + textmap + 程序集元数据口径），**未调用、未保存、未导出**。 |

---

## 1. 节点合同里的引脚签名（任务第 1 步）

来源：`data/node-contracts/variants/server/bucket-0{4,5,6}.json`（全部 `pinsTruncated:false`、
`portSetIdenticalAcrossCategoryVariants:true`、`categoryVariant:[10001,20000,22000,0]`）。

### 1.1 defId 323 设置节点图变量 — `bucket-05.json`

| portKey | kind | dir | idx | serverParamType | valueTypeNameRaw | 端口名 |
|---|---|---|---|---|---|---|
| 1:0 | exec | input | 0 | 0 | None | `""` |
| 2:0 | exec | output | 0 | 0 | None | `""` |
| 3:0 | data | input | 0 | **6** | 5 | **变量名** |
| 3:1 | data | input | 1 | 0 | Generics(10000) | **变量值** |
| 3:2 | data | input | 2 | **4** | 6 | **是否触发事件** |

resource：`Resource/Json/Beyond/Node/18273674412881068207.mihoyobin`
（与 `docs/editor-catalog/NODE-CATALOG.md:846` 的 `18273674412881068207 / 323 / 设置节点图变量` 同一身份）。

### 1.2 defId 351 节点图变量变化时 — `bucket-04.json`

| portKey | kind | dir | idx | serverParamType | valueTypeNameRaw | 端口名 |
|---|---|---|---|---|---|---|
| 2:0 | exec | output | 0 | 0 | None | `""` |
| 4:0 | data | output | 0 | 1 | None | 事件源实体 |
| 4:1 | data | output | 1 | 2 | 1 | 事件源GUID |
| 4:2 | data | output | 2 | 6 | 5 | 变量名 |
| 4:3 | data | output | 3 | 0 | Generics(10000) | 变化前值 |
| 4:4 | data | output | 4 | 0 | Generics(10000) | 变化后值 |

resource：`Resource/Json/Beyond/Node/15596561218457586184.mihoyobin`。

### 1.3 defId 337 获取节点图变量 — `bucket-06.json`（任务要求的「任何获取节点图变量」= 337）

| portKey | kind | dir | idx | serverParamType | valueTypeNameRaw | 端口名 |
|---|---|---|---|---|---|---|
| 3:0 | data | input | 0 | 6 | 5 | 变量名 |
| 4:0 | data | output | 0 | 0 | Generics(10000) | 变量值 |

resource：`Resource/Json/Beyond/Node/9277788526522933677.mihoyobin`。

### 1.4 合同层可确认的三件事
1. **获取节点图变量只有「按名取」一个入参**（3:0 变量名），出参是**泛型**（Generics/10000）——与官方
   「服务端图、强类型、按名寻址」一致。
2. **设置节点图变量是「按名写」+ 一个 bool**（3:2），bool 端口的 `serverParamType=4` 且合同名是
   `是否触发事件`（官方 `mhw66orrrfkm` 明写：默认触发 `节点图变量变化时`，须显式选「否」才静默写）。
3. **纠正一条旧记录**：`F1F2-variables-nodes.md` §8 第 5 条把 defId 323 的 `3:2` 记作 `is_bp_var`。
   合同里 323 的 3:2 记录名是 **`是否触发事件`**（`NODE-CATALOG.md:846` 同名、官方章节同名）；
   `is_bp_var` 不是 323 的端口名（它更像是别处 live 读到的无名引脚被顺手贴的标签）。以合同为准。

> 引脚签名只说明**运行时节点**怎么引用变量；它**不**回答「变量本身在哪里被定义」。§4 才回答。

---

## 2. `AuthoringGraph.cs`：有没有「图级属性」入口？（任务第 2 步）

结论：**没有。全部写值都落在一个节点的引脚对象上；没有任何路径触碰图级属性。**

### 2.1 set-value 就是一跳「引脚对象 → setter」
`tools/editor-bridge/Adapter/AuthoringGraph.cs:347-392` 的 `set-value`：
`GraphNode` → `AuthorDeclaredPins`（按 `(kind,index)` 查活注册表）→ `AuthorWritePinValue`
（`:1024-1037`）→ `AuthorPinScalar`（`:852-862`，取 `pin.value.Value`）→ `AuthorWriteScalar`
（`:901-972`）→ 在**该值对象**上调 setter。
唯一的参数面是 `(graphId, nodeId, portKind=3, portIndex, expect(sptype,generic), value, slot)`——
**没有** `variableName` 之类的图级字段，也没有除节点引脚之外的任何寻址。

### 2.2 `graph.Model` 实际被用到的成员（穷举）
| 混淆符号 | 语义（证据） | 位置 |
|---|---|---|
| `BWmKmyL3bM7` → `A35XuAK09QD` | AddNode(defKey,x,y,ctx,·) | `Generated.cs:692`；`AuthoringGraph.cs:342/561/654/759` |
| `S06Xu1xAKtQ` | InsertNode(index,defKey,x,y,ctx,·) | `Generated.cs:866` |
| `LapKOOcuGY1` → `IfyXuTjM1NU` | Link(edge,ctx,int) | `Generated.cs:738`；`:452/583/666/771` |
| `vJwKOEFj00D` → `kx7Xu5hjIbJ` | Disconnect(edge,ctx,bool) | `Generated.cs:915`；`:445` |
| `EGOXuNqHvvx` | RemoveNode(uint,ctx,bool×3) | `Generated.cs:941` |
| `n4aX5ZRwxAO` | → `Dictionary<uint,node>`（节点表 `K61KONg4LUT`） | `Generated.cs:730`；`EditorAdapter.cs:213` |
| `JXsX5LHYcwj` | → `Dictionary<edge,·>`（边表） | `Generated.cs:934` |
| `K17XuvJmjm3` | → graph.Id | `Generated.cs:744`；`AuthoringGraph.cs:306` |

**没有一个成员返回「变量」，也没有一个字段是变量集合**（对照 §4 的真类型成员表：`graph.Model`
的真类型声明了变量集合字段，**但它不在档案里**）。

### 2.3 `set-value` 的槽位也是「引脚值的存储槽」，不是图状态
`AuthorValueSlots = {auto,int,uint,enum,float,bool,string}`（`:41`）与 `AuthorWriteScalar`
（`:901-972`）的 setter 全部作用在 `YMt9KPX9HpgYFteH6uoG`（引脚值对象）上。读回也读该对象
（`:914/926/938/950/964`）。**这是「节点引脚」这一半，与「图变量」无关。**

---

## 3. 绑定档案里有没有「图属性」getter/setter 对？（任务第 3 步）

来源：`tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs`（307 个 legacy 符号、313 条
contract；解析脚本口径见本文末「复现」）。

### 3.1 全档案里**唯一**成对出现的 getter/setter 家族 = 引脚标量
| 槽 | setter（legacy→real，声明类型） | getter | 位置 |
|---|---|---|---|
| int | `c84KKE8ihrN`→`DejX9ySn3dc` `(Int32,ctx):Void` | `ilqKKrw7dhN`→`QMOXkfIqB2G` `():Wrapper<Int32>` | `:508/:550` |
| string | `MfLKK0bLIju`→`WpAXkDFUJSg` `(String,ctx):Void` | `ur7KK2NiYZ4`→**（不在档案内）** | `:745` |
| float | `SH7KKvk8cxe`→`QkpX9zVTwV4` `(Single,ctx):Void` | `ngMKKCVBuMA`→**（不在档案内）** | `:764` |
| enum | `X8oKKHB87Ue`→`xOeX9KT0Hcj` `(UInt32,ctx):Void` | `cPOKKedklwd`→`BdsXk9NE0ND` `():Wrapper<UInt32>` | `:799/:822` |
| bool | `CHHKK434xan`→`lZiX93JfX9h` `(Boolean,ctx):Void` | `RJCKKnWqvLO`→**（不在档案内）** | `:695` |

声明类型一律是 `iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG`——**引脚值对象**，不是图模型。

### 3.2 全档案里除了引脚值对象，**没有任何类型同时带 setter 和 getter**
遍历 313 条 contract：带 `void(T,ctx)` setter 的类型只有两个——引脚值对象
`YMt9KPX9HpgYFteH6uoG` 和 `EngUDvX1xc7DWWwYrrw1.vVUju1X1mM5GsVZX9XiF`；后者是**客户端脚本模型**
（`ClientScriptVariableProbe.cs:74/112/141/146/169` 用的 `UfeX1gd57Hm`/`MAGX1QT9xWK`/`lt4X1GTI1j3`/
`DppX1qo953h`/`g4UX1bRivGH`/`g4UX1bRivIH` 全声明在它上面），**不是图模型**。
**没有任何 UNUSED 的 getter/setter 对是图级变量角色**——因为这些符号**根本不在档案里**（见 §4.6）。

### 3.3 图模型类型在档案里的全部 contract（9 条，占位证明「图级变量面没被登记」）
`Generated.cs` 中声明类型为图模型（legacy `cwoW1eKm…`→real `E8xv5pXu…`，`:515`）的成员只有：
`:692`(AddNode)、`:866`(InsertNode)、`:738`(Link)、`:915`(Disconnect)、`:941`(RemoveNode)、
`:730`(节点表)、`:934`(边表)、`:744`(Id)、`:844`+`:817`(两个字段)。
**没有一条是变量集合的 getter，也没有 Insert/Remove 变量。**（对照 §4：真类型还有 §4.1 的集合字段与
§4.3 的变量方法，档案里一条都没有。）

### 3.4 顺带发现（次要，需独立复核，非本问题结论）
`ur7KK2NiYZ4`（string getter）、`ngMKKCVBuMA`（float getter）、`RJCKKnWqvLO`（bool getter）被
`AuthoringGraph.cs:938/950/964` 通过 `B(...)` 使用，但**在 `EditorBindingProfile.Generated.cs` 里
既不在 `LegacySymbols`、也不在映射表**（grep 全文 0 命中）。按 `EditorBindingProfile.cs:96-118` 的
fail-closed 规则，这三个名字在运行时会抛 `UNREGISTERED_SYMBOL`——即 string/float/bool 的**读回**
路径当前可能根本走不到（int/enum 两条有登记，可走）。**这是猜测**：也可能存在第二份 profile 或
生成文件滞后；**未验证**，仅记录，不在本任务结论内。

---

## 4. 决定性发现：引擎的节点图变量子系统存在（静态，反编译 + textmap）

任务的三步只问「我方有没有路」。要判断「引擎有没有路」，必须看**装配本体**。仓内已有该快照：
`.runtime/editor-catalog/decomp/BeyondEditor/`（12,375 个 `.cs`，`docs/editor-catalog/CODE-SURFACE.md` §三）
与 `.runtime/editor-catalog/annotated/`（字符串已还原）。**这两处只读、离线。**

### 4.1 图模型真类型持有「节点图变量」列表
文件：`.runtime/editor-catalog/decomp/BeyondEditor/cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH.cs`
（即绑定档案 `:515` 里被映射到 `E8xv5pXu77T6046o5sVM.vUK4LLXuq7BbA0L017eJ` 的那张 Kind 9 图）。
其字段（`:255-287`）中与本问题相关者：

| 行 | 字段 | 类型 | 语义（本轮判定） |
|---|---|---|---|
| 281 | `NQlKbxwmq6a` | `rgfCjhijuAbCoKxWU8Lu<LppcPfKAgGBUlYusKLtc>` | **节点图变量列表** |
| 283 | `vl8Kbd1XFLA` | `qHO2mNiRnZr4WY4hDrki<LppcPfKAgGBUlYusKLtc>` | 变量相关的单值持有（快照/当前项） |
| 267 | `OcZKbA2OAsr` | `rgfCjhijuAbCoKxWU8Lu<RuygVDipeHdMkeOglACP>` | **撤销栈**（元素是 `Undo()` 命令接口，见 `lc9NHPipkemjf63Hl3M2.RuygVDipeHdMkeOglACP.cs`） |
| 261 | `opVKb4A3SbP` | `Dictionary<uint,node>` | 节点表（我方已用 `K61KONg4LUT`） |
| 263 | `jOeKbv7xke0` | `Dictionary<Link,edge>` | 边表 |
| 277 | `a2JKb7KDLSD` | `Dictionary<uint,u4mD42ikS1XCHtcCpFG8>` | 另一类图内条目（`u4m…` 有 id/string/两个 double/bool，疑为**批注/便签**，非变量） |

### 4.2 元素类型 `LppcPfKAgGBUlYusKLtc` 的身份 =「节点图变量」
文件：`.runtime/editor-catalog/decomp/BeyondEditor/POEL6HKAWCtpYUVxs1RL.LppcPfKAgGBUlYusKLtc.cs`

| 行 | 成员 | 类型 | 说明 |
|---|---|---|---|
| 40 | `key` | `t7…<string>` | **变量名** |
| 42 | `value` | `qHO2…<JVhTwtKizlScEvUHNJeZ>` | **变量值**（值持有器） |
| 54 | `serverParamType` | `t7…<uint>` | **类型号**（与引脚 `serverParamType` 同族：6=字符串、4=布尔…） |
| 56 | `structId` / 58 | `valueStructId` | 结构体 id（结构体/字典变量用） |
| 83 | `kekKARjBrNN()` | `t7…<bool>` | 一个 bool（**疑为「对外暴露」**，官方章节明写该开关；**未证**） |
| 64 | `resourceItemTextType` | string | 见下 |

`resourceItemTextType` 在**已还原字符串**里被还原为字面量
`"UI_BEYOND_ASSIST_EDITOR_BP_VARIABLES"`（`.runtime/editor-catalog/annotated/POEL6HKAWCtpYUVxs1RL.LppcPfKAgGBUlYusKLtc.cs:64`）。
查 textmap：`UI_BEYOND_ASSIST_EDITOR_BP_VARIABLES` → **「节点图变量」**
（`.runtime/editor-catalog/textmap-chs.json:34313`）。

**这是本轮的定性锚点**：图模型里那份列表的**元素**，其 UI 文本类型就是「节点图变量」。

### 4.3 图模型上原生的建 / 插 / 删 / 改名（可直接反射调用）
文件同上（`cwoW1eKm…A8NrPMKmnpQkIiiyYetH.cs`）：

| 行 | 方法 | 形态 | 判定 |
|---|---|---|---|
| 420 | `pSJKOe1FuCR()` | `→ rgfCjhijuAbCoKxWU8Lu<LppcPfKAgGBUlYusKLtc>` | **读变量列表**（含 Count / 索引器 / 枚举） |
| 426 | `EF2KOI3tZ9E()` | `→ qHO2…<LppcPfKAgGBUlYusKLtc>` | 单值持有读 |
| 2374 | `zVUKO3av5Re(int, uint, uint, ctx)` | `void` | **新建一个变量并插入**（内部 `DZIiUfaQJSZ<LppcPfKAgGBUlYusKLtc>()` 造元素 + `FtwimThrKtCqdYbpq3DI…` 插到 index，并设 `resourceItemName`） |
| 2402 | `L3mKOiPc6Zn(int, LppcPfKAgGBUlYusKLtc, ctx)` | `void` | **插入已有变量**（`…T0lhrA5npQ7).zUEij1ZEASP(index, element)`） |
| 2489 | `IPaKOuvl7c1(LppcPfKAgGBUlYusKLtc)` | `void` | **删除变量**（`…X66ijdVvJ0k(element)`） |
| 2517 | `veTKO7bErSv(int, ctx)` | `void` | 越界即返回的按索引操作（**疑为按索引删除/选中**，未证） |
| 2432 | `BgAKOKAeuul(int)` | `→ string` | **默认变量名生成器**：模板 `"UI_BEYOND_ASSIST_EDITOR_ADVANCED_DATA_VAR_INDEX"`（textmap:35538 → **「变量_{0}」**），并在 `count+1` 越界时报字面量 **`"invalid variable name!"`**（annotated 同文件 `:2477`） |

### 4.4 编辑器自己的撤销标签就叫「新建/修改/删除节点图变量」
同一图模型文件内的嵌套类 `kRsRrQYurbKb5udmgHHb`（`:55`）持有一个
`Dictionary<yF248gKbPCjwkVnCP41X, string>`（枚举 = 图编辑撤销操作种类）。
已还原字符串条目（annotated 文件）：

| 行 | 枚举值 | 字面量 | textmap |
|---|---|---|---|
| 181 | 8 | `UI_BEYOND_EDITOR_WPF_HISTORY_CV_NEW` | **新建节点图变量**（textmap:35718） |
| 185 | 9 | `UI_BEYOND_EDITOR_WPF_HISTORY_CV_DELETE` | **删除节点图变量**（textmap:35728） |
| 189 | 10 | `UI_BEYOND_EDITOR_WPF_HISTORY_CV_EDIT` | **修改节点图变量**（textmap:35723） |

（同枚举里还有 NODE_NEW/MOVE/DELETE、LINK_NEW/DELETE、MENTION_*、COMPOUNDNODES_*、CUT/PASTE——
一张完整图编辑撤销表。**「CV」= 节点图变量**，不是客户端变量。）

### 4.5 这一步推翻了什么、没推翻什么
- **推翻**：`F1F2-variables-nodes.md` §7「F2 卡点」把根因写成「写不进一张可用的图 …… `graph.variables`
  零入口」若被读成「引擎没有入口」——**不成立**。引擎有完整入口（§4.3），且是我方**已经拿到手**的
  图模型（`graph.Model`）上的方法。
- **没推翻**：对我方**工具现状**而言，§2/§3 仍然成立——档案里**没有绑定**这些符号，
  所以**今天通过 bridge 仍然写不了图变量**。

### 4.6 为什么此前「零入口」不是错——命名空间错位
我方适配器用一个**旧代际**的符号名去解析（`B("cwoW1eKm…")`，`EditorAdapter.cs:18`），档案把它
**前向映射**到当前代的真名（`:515` → `E8xv5pXu…`）。而 §4.1-4.3 里变量集合的字段/方法
（`NQlKbxwmq6a` / `pSJKOe1FuCR` / `L3mKOiPc6Zn` / `IPaKOuvl7c1` / `EF2KOI3tZ9E`）
**在 `LegacySymbols` 与映射表里 grep 0 命中**（本文 §3 脚本口径）。
即：**它们从来没被登记过**——不是「被拒绝」，是「没人把它们写进档案」。这与 CLAUDE.md 记忆
「节点 id 有两套命名空间」同构：**「没绑定」≠「不存在」**。

---

## 5. 结论：什么已证、什么还只是假设

### 5.1 已证（proven）
1. **合同层**：defId 323/351/337 的完整引脚签名（§1），`pinsTruncated:false`。
2. **我方工具层**：`AuthoringGraph.cs` 的所有写值都经「引脚对象 → setter」，**无任何图级属性路径**（§2）。
3. **我方档案层**：全 313 条 contract 里，成对 getter/setter **只**存在于**引脚值对象**上；
   图模型类型在档案里的 9 个成员全是节点/边/Id（§3）；图变量访问器**未登记**（§4.6）。
4. **引擎层（静态）**：Kind 9 图模型真类型**持有**一个元素为「节点图变量」的列表字段，
   并**提供**读列表 / 新建 / 插入 / 删除 / 默认名生成方法；编辑器撤销枚举含
   「新建/修改/删除节点图变量」（§4.1-4.4）。

### 5.2 只是假设（hypothesised，未证）
- H1：`LppcPfKAgGBUlYusKLtc` 就是运行时节点 323/337/351 按名引用的**同一批**变量——
  名字/类型/作用域一致是**结构推断**，尚未在同一张图上把「列表内容」与「节点按名取到的东西」对上。
- H2：`kekKARjBrNN()` 那个 bool = 官方说的**「对外暴露」**开关（未证；也可能不是）。
- H3：`zVUKO3av5Re` / `L3mKOiPc6Zn` / `IPaKOuvl7c1` 通过 bridge 反射调用会被原生**接受**，
  并且能**导出/保存**（我方从未调用；`ok:true` 单条不证明持久化，见 CLAUDE.md §四）。
- H4：§4.1-4.3 的反编译快照**早于**当前构型（档案把 `cwoW1eKm…` 判为 legacy），因此
  **当前 BeyondEditor.dll 里这些方法的现名可能与快照不同**；绑定前需对**当次**程序集重做一次静态核对。
- H5（§3.4）：string/float/bool 读回 getter 未登记，可能使对应 set-value 读回路径在运行时 fail-closed；
  也可能档案滞后——**未验证**。

### 5.3 ⭐ 单个最便宜的下一步实验（人来做，一次即可定生死）

**在开着编辑器、且图上「节点图变量」页签已有 N（≥1）个变量的前提下，做一次只读反射：
解析图模型类型 → 调它的变量列表 getter（快照名 `pSJKOe1FuCR` 对应的**当期**符号）→ 打印 `Count`
与每个元素的 `key` / `serverParamType`。**

- **为什么是它**：它把 §4 的静态推断一次性压实——
  **若 `Count == N` 且 `key` 与页签里的变量名逐字相等**，则 H1、H2 立判，且写路径（`L3mKOiPc6Zn`）
  已有一半把握；若 `Count` 恒为 0 或抛错，则 §4 的列表是别的东西，回炉。
- **成本**：往绑定档案加**一个**符号 + 发**一条只读**请求（照 `pin-slots` 这个既有只读探针形状做）；
  **零 mutation，不 save，不 export，不碰存档**。
- **前置（真·最便宜，纯离线，分钟级）**：用 `tools/editor-bridge/dump-pe-functions.py` 一类的**静态**
  分析对**当前** BeyondEditor.dll 复核一遍 §4.1-4.3 的方法在其**现名**下是否仍存在（消化 H4）。
  本文已完成**快照**一侧；只差「当次程序集」这一侧。
- **在只读探针通过之前，不要**先做建变量（那会把「能不能写」和「写进去对不对」两件事混在一起）。

---

## 附：复现（全部只读、离线）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**未做**：未实现任何代码；未调用任何原生方法；未启停 helper/game/editor；未写任何存档；
未把 §5.2 的任一条假设当作结论。
