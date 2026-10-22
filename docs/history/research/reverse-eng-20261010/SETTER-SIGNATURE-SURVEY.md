> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# SETTER-SIGNATURE-SURVEY — 绑定档里每个 setter 的调用点、配对与"最便宜的下一笔写"

> 纯静态分析。**没有向 bridge 发任何请求，没有碰游戏/编辑器，没有跑任何 native 调用。**
> 结论全部来自仓内 C# 源码的逐符号检索；引用的行号均为本 checkout 当前行号。
> 前置文档：`docs/research/reverse-eng-20261010/BINDING-SYMBOL-AUDIT.md`（下称 AUDIT）。
> 被审计文件：`tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs`（生成档，**未修改**）
> 与被检索范围 `tools/editor-bridge/Adapter/*.cs`（52 个非生成 `.cs`）。
>
> 符号约定（与 AUDIT §0 一致）：本工程用 `B("旧混淆名")`（`EditorAdapter.cs:87`）把 **legacy 名**
> 交给 profile 解析成**当代构建的真实名**。下文一律写成 `legacy` → `` actual ``。

---

## 0. 结论（先给判决）

1. **profile 登记了 9 个"写形状"的 setter 方法**（签名末尾是 `(…,G97bO4XQy2ksgGIyrs78.nyfSUyXQKP5VT33Lnsry):System.Void` 的 Method 契约）。
   其中 **8 个**是标准的"值 setter"`(T, ctx):Void`，**1 个**是 3 参的
   `(枚举类型, Int32, ctx):Void`（建客户端变量）。见 §2。
2. **9 个 setter 全部被引用，0 个未使用。** 这与 AUDIT §2 的
   "Method 类 85 个符号 0 未引用" 一致 —— 这是本档要的那个**精确负面**：
   **绑定档里不存在"已登记却没人调"的 setter**。见 §4.1。
3. **真正的"未使用"不在 setter 侧，而在 setter 的读回 / 通用入口侧**：
   - `float` / `bool` / `string` 三个 setter **已被通用写口 `AuthorWriteScalar` 接线**，但它们的
     **读回 getter 不在 profile 里**（`ngMKKCVBuMA` / `RJCKKnWqvLO` / `ur7KK2NiYZ4`，生成档里出现 0 次），
     于是 `slot="float"|"bool"|"string"` 的 `set-value` **写进去了、读回抛异常**。见 §4.2。
   - 第二个 `UInt32` setter `LhkKKbraAbs` → `N6WX98qouJ0` **只出现在两处硬编码调用**，从未进通用写口；
     它是"资源 id / 资产 id"槽位的唯一写原语。见 §4.3。
4. **`vector`(7) / `guid-entity-ref`(1) / `dict`(10003) 三类 pin：profile 里根本没有对应的 setter 符号**
   （不是"没用"，是"没有"）。见 §5、§6。
5. **排名第一的"最便宜的新写入"**：把 3 个缺失的读回 getter 补进 profile —— 它让已经写好的
   `float`/`bool`/`string` 写口真正闭环，代价是**生成档补条目**而非写新代码。见 §6.1。

---

## 1. 何谓 "setter"（本档口径）

本档只处理**把值写进一个对象**的方法契约，即 `BindingKind.Method` 且签名回报 `System.Void`、
且带一个写入值参数的方法。按 owner 分三家：

| 家族 | owner（actual 全名） | 登记成员数 | 语义 |
|---|---|---|---|
| **值 setter 家族** | `iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG` | 16（含 7 个 setter/appender、5 个 Boxed 字段、4 个 getter） | **节点 pin 的 value 对象**：写一个标量/枚举/列表元素 |
| **客户端变量家族** | `EngUDvX1xc7DWWwYrrw1.vVUju1X1mM5GsVZX9XiF` | 3 setter + 若干字段 | 客户端脚本**变量表**的 建/复位/删 |
| **图/管理器家族** | `E8xv5pXu77T6046o5sVM.vUK4LLXuq7BbA0L017eJ` 等 | 若干 | 建节点 / 连线，**不是值 setter**，本档不计入 |

**关键机制（决定"选哪个 setter"）**：通用写口**按 pin 的"存储种类码"选 setter，不按类型名选**。
存储种类由 `KiPKKaQUNLS`（`AuthoringGraph.cs:872`）读回（`FAVX90STAmy`，契约 `:734`），
`AuthorAutoSlot` 把码翻成槽位名（`AuthoringGraph.cs:879-888`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


因此"某个 setter 用不用得上"＝"有没有 pin 的存储码能路由到它"，而不是"这个符号有没有出现在源码里"。

**值 setter 家族**（`iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG`，该类型名**不在 `Symbols` 映射表里、
也不在 `LegacySymbols` 里**，只作为 16 条契约的 owner 出现；它没有 legacy 别名）：

| # | legacy → actual | 契约行 | 签名 | 底层字段 |
|---|---|---|---|---|
| S1 | `c84KKE8ihrN` → `DejX9ySn3dc` | `:818` | `(System.Int32, ctx):Void` | `xhyXky634Kl: Boxed'1<Int32>` `:653` |
| S2 | `X8oKKHB87Ue` → `xOeX9KT0Hcj` | `:799` | `(System.UInt32, ctx):Void` | （无独立 Boxed 字段） |
| S3 | `CHHKK434xan` → `lZiX93JfX9h` | `:695` | `(System.Boolean, ctx):Void` | `mgbXk3PAHxj: Boxed'1<Boolean>` `:646` |
| S4 | `SH7KKvk8cxe` → `QkpX9zVTwV4` | `:764` | `(System.Single, ctx):Void` | `F2xXkzqKsxa: Boxed'1<Single>` `:639` |
| S5 | `MfLKK0bLIju` → `WpAXkDFUJSg` | `:745` | `(System.String, ctx):Void` | `u0HXrD9kTAg: Boxed'1<String>` `:652` |
| S6 | `LhkKKbraAbs` → `N6WX98qouJ0` | `:739` | `(System.UInt32, ctx):Void` | （**第二个 uint setter**，见 §4.3） |
| S7 | `KRQKKuygfFk` → `Vo1XkeKXfjj` | `:732` | `(X7NDusX…bX3XUOXHOHPd0fXaebqA, ctx):iULK…YMt9KPX9HpgYFteH6uoG` | 列表**元素追加**（写一个元素，返回自身） |

**客户端变量家族**（`EngUDvX1xc7DWWwYrrw1.vVUju1X1mM5GsVZX9XiF`）：

| # | legacy → actual | 契约行 | 签名 | 用途 |
|---|---|---|---|---|
| C1 | `lt4X1GTI1j3` → `lt4X1GTI1j3`（恒等） | `:634` | `(System.Int32, ctx):Void` | 变量表第 i 项**复位**（类型回到 String） |
| C2 | `DppX1qo953h` → `DppX1qo953h`（恒等） | `:638` | `(System.Int32, ctx):Void` | 变量表第 i 项**删除** |
| C3 | `MAGX1QT9xWK` → `MAGX1QT9xWK`（恒等） | `:642` | `(pla638…EOWvASZlCDk3Q1lb3hbD, System.Int32, ctx):Void` | 变量表**新建**一项（枚举类型 + 值） |

> 本档"未使用"一词按 AUDIT 口径：**该 legacy 名是否在 52 个非生成 `.cs` 里出现过**。C1–C3、S1–S7 全部出现过。

---

## 2. 逐个 setter：调用点 + 实参签名

调用方式分两种，实参形状不同：

- **硬编码 `Set(...)` 本地助手**（AuditGraph / EditorAdapter / FinishGraph / GameLoopGraph / PositionGraph）：
  `Set(node, index, B(setter), data)`，内部一律
  `v.GetType().GetMethod(method,Fields)!.Invoke(v, new object?[]{ data, null })`
  —— 即 **(T 值, null 当 ctx)**。定义：
  `AuditGraph.cs:63`、`EditorAdapter.cs:766-772`、`FinishGraph.cs:71`、
  `GameLoopGraph.cs:179` 与 `:687`、`PositionGraph.cs:48`。
- **通用写口 `AuthorWriteScalar`**（`AuthoringGraph.cs:901-972`）：直接
  `setter.Invoke(scalar, new object?[]{ value, null })`，且**先验签名再调用、调用后必读回**。

### S1 `c84KKE8ihrN` → `DejX9ySn3dc`（Int32）

| 调用点 | 实参签名 | 场景 |
|---|---|---|
| `AuthoringGraph.cs:711`（`:715` 读回） | `{int, null}` | 计数门阈值 |
| `AuthoringGraph.cs:908`（`:913` invoke） | `{int, null}` + 签名检查 `Length==2 && [0]==typeof(int)` `:909` | **通用写口 `slot="int"`** |
| `EditorAdapter.cs:780` | `{1, null}` | 校准图 生成节点 slot6 |
| `GameLoopGraph.cs:308` / `:775` | `{0, null}` | 计分板 slot1 |
| `GameLoopGraph.cs:441`（`:442` 读回） | `{0, null}` | 阶段复位 |

### S2 `X8oKKHB87Ue` → `xOeX9KT0Hcj`（UInt32 / enum）

| 调用点 | 实参签名 | 场景 |
|---|---|---|
| `AuthoringGraph.cs:694` | `{uint, null}` | 循环变量 |
| `AuthoringGraph.cs:920`（`:925` invoke） | `{uint, null}` + 签名检查 `[0]==typeof(uint)` `:921` | **通用写口 `slot="enum"`** |
| `FinishGraph.cs:99` / `:122` / `:145` | `{1u, null}` | 定时器 enum / 结算 stage |
| `GameLoopGraph.cs:257/303/312/403/741/771/779` | `{uint, null}` | 定时器 / 胜负 enum |

### S3 `CHHKK434xan` → `lZiX93JfX9h`（Boolean）

| 调用点 | 实参签名 | 场景 |
|---|---|---|
| `AuditGraph.cs:69` | `{false, null}` | 定时器 slot2 |
| `AuthoringGraph.cs:474`（`:478` invoke） | `{bool, null}` + 签名检查 `[0]==typeof(bool)` `:475` | `set-condition` 分支条件 |
| `AuthoringGraph.cs:932`（`:937` invoke） | `{bool, null}` + `[0]==typeof(bool)` `:933` | **通用写口 `slot="bool"`**；`:938` 读回用缺席的 `RJCKKnWqvLO` |
| `EditorAdapter.cs:779` | `{false, null}` | 校准图 生成节点 slot5 |
| `PositionGraph.cs:55` | `{false, null}` | 定时器 slot2 |

### S4 `SH7KKvk8cxe` → `QkpX9zVTwV4`（Single / float）

| 调用点 | 实参签名 | 场景 |
|---|---|---|
| `AuditGraph.cs:78` | `{1f, null}` | 定时器序列元素 |
| `AuthoringGraph.cs:704` | `{period, null}` | 循环周期 |
| `AuthoringGraph.cs:944`（`:949` invoke） | `{float, null}` + `[0]==typeof(float)` `:945` | **通用写口 `slot="float"`**；`:950` 读回用缺席的 `ngMKKCVBuMA` |
| `FinishGraph.cs:109/114/116/117` | `{float, null}` | 目标向量 X/Y/Z、距离、高 |
| `GameLoopGraph.cs:278/289/292/294/316/318-320/752/760/763/765/781/783-785` | `{float, null}` | 大量；**向量就是 3 次单分量 float 写** |
| `PositionGraph.cs:65` | `{3f, null}` | 定时器序列元素 |

### S5 `MfLKK0bLIju` → `WpAXkDFUJSg`（String）（引用热度 30）

| 调用点 | 实参签名 | 场景 |
|---|---|---|
| `AuditGraph.cs:69/79/84`、`FinishGraph.cs:98-121`、`GameLoopGraph.cs:255-776`、`PositionGraph.cs:55-73` | `{string, null}` | 打印文本 / 定时器名 / 行标签 |
| `AuthoringGraph.cs:461`（`:463` invoke） | `{string, null}` | `set-print` |
| `AuthoringGraph.cs:573`（`:578` invoke） | `{string, null}` + 签名检查 `[0]==typeof(string)` `:574` | 建打印节点 |
| `AuthoringGraph.cs:679` / `:813` | `{string, null}` | 局部 `SetText` / build-plan values 的 string 绕行路 |
| `AuthoringGraph.cs:958`（`:963` invoke） | `{string, null}` + `[0]==typeof(string)` `:959` | **通用写口 `slot="string"`**；`:964` 读回用缺席的 `ur7KK2NiYZ4` |
| `EditorAdapter.cs:680` / `:781` | `{string, null}` | WireTestEvent / 校准图打印 |

### S6 `LhkKKbraAbs` → `N6WX98qouJ0`（UInt32，**与 S2 同签名**）

| 调用点 | 实参签名 | 场景 |
|---|---|---|
| `AuditGraph.cs:82` | `{20001875u, null}` | 查询节点 def 320 slot0 —— 一个**资源/资产 id** |
| `EditorAdapter.cs:778` | `{20001875u, null}` | 生成节点 def 252 slot0 —— **同一个 id** |

只有这两处，且都写同常量 `20001875u`。**没有被任何参数化路径调用。**

### S7 `KRQKKuygfFk` → `Vo1XkeKXfjj`（列表元素追加）

| 调用点 | 实参签名 | 场景 |
|---|---|---|
| `AuthoringGraph.cs:1016` | `{elementDefinition, null}`（`elementDefinition` 由 `Ov2K7oYGvHi`→`rKlXHia7SDm` 从声明类型读回，`:1012`，契约 `:754`） | `AuthorWriteList` 逐元素 append |
| `AuditGraph.cs:77` | `{elementDef, null}` | 审计图 定时器序列 |

### C1–C3 客户端变量 setter（owner `EngUDvX1xc7DWWwYrrw1.vVUju1X1mM5GsVZX9XiF`）

| setter | 调用点 | 调用签名 |
|---|---|---|
| `MAGX1QT9xWK` (C3) | `ClientScriptVariableProbe.cs:112`（`:117` invoke） | `method.Invoke(script.Model, new object?[]{ selectedType, 1, null })` —— **(枚举, Int32, null)** |
| `lt4X1GTI1j3` (C1) | `ClientScriptVariableProbe.cs:146`（`:149` invoke） | `method.Invoke(script.Model, new object?[]{ 0, null })` —— **(Int32, null)** |
| `DppX1qo953h` (C2) | `ClientScriptVariableProbe.cs:169`（`:172` invoke） | `method.Invoke(script.Model, new object?[]{ 0, null })` —— **(Int32, null)** |

> C1/C2 的 `0` = 变量表下标；C3 的 `1` = 新建时的第二个 Int32 参数。三者都是**脚本变量表**的写，
> 与节点 pin 无关，不进通用写口。

---

## 3. setter/getter 配对表（谁被引用）

"配对"按**同一底层类型 T** 认定。值 setter 家族里形如 `():Boxed'1<T>` 的**包装 getter 只有 2 个**
（AUDIT §4.1 同一结论），其余读回 getter 在 profile 里**缺失**。

| slot / T | setter（legacy → actual） | setter 引用 | getter（legacy → actual） | getter 在 profile？ | getter 引用 |
|---|---|---|---|---|---|
| Int32 | `c84KKE8ihrN` → `DejX9ySn3dc` `:818` | 在用（6 处） | `ilqKKrw7dhN` → `QMOXkfIqB2G` `:859` | **在** | 在用（`AuthoringGraph.cs:914/715`、`GameLoopGraph.cs:442`） |
| UInt32/enum | `X8oKKHB87Ue` → `xOeX9KT0Hcj` `:799` | 在用（12 处） | `cPOKKedklwd` → `BdsXk9NE0ND` `:822` | **在** | 在用（`AuthoringGraph.cs:926`、`FinishGraph.cs:146`、`GameLoopGraph.cs:370`） |
| Boolean | `CHHKK434xan` → `lZiX93JfX9h` `:695` | 在用（5 处） | `RJCKKnWqvLO`（无 actual） | **不在**（生成档 0 次） | 代码在用（`AuthoringGraph.cs:938`）→ 抛 `UNREGISTERED_SYMBOL` |
| Single | `SH7KKvk8cxe` → `QkpX9zVTwV4` `:764` | 在用（30 处） | `ngMKKCVBuMA`（无 actual） | **不在** | 代码在用（`AuthoringGraph.cs:950`）→ 抛 |
| String | `MfLKK0bLIju` → `WpAXkDFUJSg` `:745` | 在用（30 处） | `ur7KK2NiYZ4`（无 actual） | **不在** | 代码在用（`AuthoringGraph.cs:964`）→ 抛 |
| UInt32（第二） | `LhkKKbraAbs` → `N6WX98qouJ0` `:739` | 在用（2 处硬编码） | **无独立 getter**（仅共用 `BdsXk9NE0ND`？未证） | — | — |
| List 元素 | `KRQKKuygfFk` → `Vo1XkeKXfjj` `:732` | 在用（2 处） | `Ov2K7oYGvHi` → `rKlXHia7SDm` `:754`（取元素**声明类型**，非读值） | **在** | 在用（`AuthoringGraph.cs:1012`） |

**读法**：
- **`Int32` / `UInt32` 两对是完整的**（setter + getter 都在档、都在用）——这也是"只有 2 个 `():Boxed'1<T>` getter" 的原因。
- **`Boolean` / `Single` / `String` 三对只有 setter 半边在档**：setter 在用，getter 缺席。
- `LhkKKbraAbs` 找不到配对 getter（value 对象的第二个 uint getter 未登记）——见 §4.3。

---

## 4. "未使用"的精确负面 + 真正的缺口

### 4.1 没有"已登记却没人调"的 setter（精确负面）

S1–S7、C1–C3 **全部有 ≥1 个 Adapter 调用点**（计数：S1=6、S2=12、S3=5、S4=30、S5=30、S6=2、S7=2、C1=C2=C3=1）。
与 AUDIT §2「Method 85/85 已引用」互证。**所以本档不能靠"把某个未使用的 setter 接上"来赚一笔**——
需要赚的那笔在"读回缺失"和"通用入口缺失"里。

### 4.2 反向缺口：3 个"setter 在用、getter 不在 profile"（最便宜的一笔）

`AuthorWriteScalar` 的 `float`/`bool`/`string` 分支**写已落进原生对象**（`:949` / `:937` / `:963`），
紧接着**解析读回符号**（`:950` / `:938` / `:964`），而这三个名**不在 profile**：

| 符号（legacy 名，代码里的 `B("…")` 实参） | 被谁用 | 生成档出现次数 | 抛什么 |
|---|---|---|---|
| `ngMKKCVBuMA`（float 读回） | `AuthoringGraph.cs:950` | **0** | `EDITOR_BINDING_PROFILE_UNREGISTERED_SYMBOL`（`EditorBindingProfile.cs:115-117`） |
| `RJCKKnWqvLO`（bool 读回） | `AuthoringGraph.cs:938` | **0** | 同上 |
| `ur7KK2NiYZ4`（string 读回） | `AuthoringGraph.cs:964` | **0** | 同上 |

- **上游对 string 已有一条绕行**：build-plan 的 values 段在 `AuthoringGraph.cs:804-813` 显式判断
  "string 读回不在 profile" 并改走 set-print 的 setter、**不做读回**；但 `set-value` 动作本身
  （`:957-968`）**没有这条绕行**，`:964` 仍是可达的死路。
- **float / bool 没有任何绕行**。
- 补的是 **profile**（生成档），不是代码 —— **这是本档排名第一的"最便宜的新写入"**（§6.1）。

### 4.3 已登记、已用、但**只走硬编码**的 setter：`LhkKKbraAbs` / `N6WX98qouJ0`

- 与 S2 (`xOeX9KT0Hcj`) **签名完全相同**：`(System.UInt32, ctx):Void`，同一 owner。二者区别只能是
  **写进的不同底层字段**（`KiPKKaQUNLS` 报的存储码是否不同，仓内无离线证据）。
- 今天只被 `AuditGraph.cs:82` 与 `EditorAdapter.cs:778` 以常量 `20001875u` 硬编码调用，**从未进通用写口**。
- **为什么不能直接接线**：写口按**存储码**选 setter（§1）。若该 pin 的存储码也是 6，写口会选 `xOeX9KT0Hcj`
  而写错字段——这正是它被硬编码、绕开写口的原因。要接它就**必须**先证明路由码能把它和 `xOeX9KT0Hcj` 区分开，
  且**它的读回 getter 也没有登记**（写进去也读不回来）。⇒ 排名第二，**中成本**。

### 4.4 客户端变量 setter（C1–C3）：不是 pin 写，不进本排名

C1/C2/C3 写的是 `script.Model` 上的**变量表**（`ClientScriptVariableProbe.cs:112/146/169`），
与节点 pin 值无关，且每个都已被 `…Spent` 一次性门闩锁死（`:116` / `:148` / `:171`）。
它们是"脚本变量 CRUD"能力，**不是 graph 写口**，不列入 §6。

---

## 5. 写口今天拒绝的 pin 类型 ↔ 能解锁它的 setter

存储码语义见 `data/node-contracts/shared/value-type-codes.json`（`historicalInferredNames.rows`：
`2`=整数、`4`=浮点、`5`=字符串、`6`=布尔/枚举、`7`=三维向量、`1`=GUID/实体引用、`10000`=Generics、
`10002`=List、`10003`=字典）。`AuthorAutoSlot`（`AuthoringGraph.cs:879-888`）只认 `2` 和 `6`，其余全拒。

| pin 类型（存储码） | 写口今天 | 需要的 setter | profile 里有吗 |
|---|---|---|---|
| 整数 `2` | ✅ `slot="int"` 闭环 | `DejX9ySn3dc` | 有（S1，配对完整） |
| 枚举/布尔 `6` | ⚠️ `slot="enum"`/`"bool"` **写进去、读回抛** | `xOeX9KT0Hcj` / `lZiX93JfX9h` | 有（S2 完整；S3 缺 getter） |
| 浮点 `4` | ⚠️ auto 拒；`slot="float"` **写进去、读回抛** | `QkpX9zVTwV4` | setter 有（S4），**getter 缺** |
| 字符串 `5` | ⚠️ auto 拒；`slot="string"` **写进去、读回抛** | `WpAXkDFUJSg` | setter 有（S5），**getter 缺** |
| 三维向量 `7` | ❌ auto 拒 | **无向量 setter**；现做法＝3 次单分量 float 写（`GameLoopGraph.cs:289` 等） | 无；**只能借道 S4，而 S4 被 getter 缺卡住** |
| GUID/实体引用 `1` | ❌ auto 拒 | **无对应 setter**（唯一近邻是 S6 的 uint 资源 id） | **无** |
| 字典 `10003` | ❌ auto 拒 | **无标量 setter / 无常量写**（500 条定义里构造器 `1088`/`1788`/`948` 与取元素 `1158` 均在，只是**泛型**引脚；2026-10-12 复核） | **无** |

> 向量那条值得注意：仓内**早就用 3 次 float 写拼出向量**（`FinishGraph.cs:114` 目标向量、`GameLoopGraph.cs:289` 等），
> 所以"向量写不进"其实**不是缺 setter，而是被 §4.2 的 float getter 缺失连坐**。

---

## 6. 排名：最便宜的新写入（file:line）

### 6.1 🥇 补 3 个读回 getter（`ngMKKCVBuMA` / `RJCKKnWqvLO` / `ur7KK2NiYZ4`）进 profile

- **解锁**：`float`(4) / `bool`(6) / `string`(5) 三类 pin 的 `set-value` **从"写进去但抛异常"变成闭环**，
  并顺带解锁**向量**（3 次 float 写拼装）。
- **代价**：**只改生成档**（补 `LegacySymbols` / `Symbols` / `Contracts` 三条），**不写新代码**——
  写口 `AuthorWriteScalar` 的 5 个分支早已存在。
- **证据**：`AuthoringGraph.cs:938`(bool 读回)、`:950`(float 读回)、`:964`(string 读回)；
  `EditorBindingProfile.cs:115-117`(缺席即抛)；`AuthoringGraph.cs:804-813`(string 上游已绕行，证明这条诊断正确)。
- **风险**：这 3 个名是**代码里的字面量**（`B("…")` 实参）。若它们是 legacy 名，生成档需补 **legacy→actual** 映射
  （actual 名未知，需重跑生成器）；若它们本就是当代构建的 actual 名，则只需补契约。**补前必须确认命名空间。**

### 6.2 🥈 把 `LhkKKbraAbs` / `N6WX98qouJ0` 接进写口（uint 资源/资产 id 槽）

- **解锁**：写"资源 id / 资产 id"型 pin（今天只有 `AuditGraph.cs:82`、`EditorAdapter.cs:778` 两处常量写）。
- **代价（中）**：必须先离线证明该 pin 的存储码能把它与 `xOeX9KT0Hcj` 分开（否则写口按码路由会选错 setter），
  **且**补它的读回 getter（未登记）。见 §4.3。
- **证据**：`EditorBindingProfile.Generated.cs:739`(契约)、`:799`(同签名 S2)、
  `AuditGraph.cs:82`、`EditorAdapter.cs:778`、`AuthoringGraph.cs:901-972`(写口按码路由)。

### 6.3 🥉 （无）向量 / GUID / 字典

- 三者均**缺 setter 符号**（§5）。要推进只能**继续逆向**（新 setter 符号 / 新原生调用），
  不是接现有符号 —— 这与 CLAUDE.md §5 的"继续逆向，不是找官方接口"一致。
- 其中**向量可绕过**（借道 float，见 6.1）；**GUID/字典确实无原语**，是精确负面。

### 6.4 不建议：C1–C3（客户端变量 setter）

已一次性门闩锁死、且不在 pin 写口路径上（§4.4）。

---

## 7. 复核方法（任何人都能重跑）

1. 从 `EditorBindingProfile.Generated.cs` 取三段（`LegacySymbols:8-317`、`Symbols:321-630`、`Contracts:631-946`），
   按 `BindingKind.Method` 过滤出 91 条；其中签名含 `G97bO4XQy2ksgGIyrs78.nyfSUyXQKP5VT33Lnsry` 且回报 `System.Void` 的＝**9 个 setter**（本档 §2 表）。
2. 对 9 个 legacy 名在 `tools/editor-bridge/Adapter/*.cs`（去生成档，52 个）做**精确字面量**检索 → 全部 ≥1 命中（§4.1）。
3. 对 3 个读回名（`ngMKKCVBuMA`/`RJCKKnWqvLO`/`ur7KK2NiYZ4`）在生成档全文检索 → **0 命中**（§4.2）。
   对照：`ilqKKrw7dhN`/`cPOKKkedklwd` 在生成档各 2 命中、在 Adapter 各 3 命中（§3 配对表）。
4. `AuthorAutoSlot`（`AuthoringGraph.cs:879-888`）与 `KiPKKaQUNLS`（`:872`）确认"按存储码选 setter"这一路由机制（§1）。

---

**一句话判决**：绑定档的 9 个 setter **没有一个是"登记了没人调"的**；最便宜的新写入不在"未使用的 setter"里，
而在**三个缺席的读回 getter**（`AuthoringGraph.cs:938/950/964`）——补上它们，`float`/`bool`/`string`（以及借道的
`vector`）写口当场闭环；第二便宜的是 `LhkKKbraAbs`（`:739`）这笔"uint 资源 id 写"，
但它要先把路由歧义和读回缺口补掉；`guid`/`dict` 则是**无原语**的精确负面。
