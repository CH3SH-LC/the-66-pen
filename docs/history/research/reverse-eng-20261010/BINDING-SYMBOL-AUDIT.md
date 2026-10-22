> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# BINDING-SYMBOL-AUDIT — 绑定档里还有什么没被用上

> 纯静态分析。**没有向 bridge 发任何请求，没有碰游戏/编辑器，没有跑任何 native 调用。**
> 结论全部来自仓内 C# 源码的逐符号字符串检索；引用的行号均为本 checkout 当前行号。
> 被审计文件：`tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs`（生成档，**未修改**）、
> `tools/editor-bridge/Adapter/AuthoringGraph.cs`、`tools/authoring/INTERFACE-INVENTORY.md`。
> 被检索范围：`tools/editor-bridge/Adapter/*.cs` 全部 **53 个 .cs（扣掉生成档本身后 52 个）**。

符号约定（与 `GRAPH-DELETE-PROBE.md` 一致）：本工程到处用 `B("旧混淆名")`
（`EditorAdapter.cs:87`）把 **legacy 名**交给 profile 解析成**当代构建的真实混淆名**。
下文一律写成 `legacy` → `` actual ``。

---

## 0. 结论（先给判决）

1. **绑定档一共 307 个 legacy 符号，不是 300 也不是 313**。307 = `LegacySymbols` 集合
   （`EditorBindingProfile.Generated.cs:8-317`）= `Symbols` 字典的 key
   （`:321-630`），两者是**双射**（`ValidateContracts` 逐条要求 `profile.Symbols` 含每个
   `LegacySymbols` 元素，`EditorBindingProfile.cs:318-320`）。另外单列 **313 条 contract**
   （Field 157 / Method 91 / Type 64 / Property 1）做元数据校验，contract 引用的是 **actual 名**。
   257/307 是**改名**的（legacy ≠ actual），只有 50 个是恒等映射。
2. **307 个符号里，299 个在 Adapter 里被引用，8 个一次都没出现。**
   （52 个非生成 .cs 中 44 个至少引用 1 个符号。）
3. **8 个未使用符号收敛成 5 组**，其中两组是「一个类型 + 它的一半字段」，一组是「类型名没用上、
   但它的字段被另一条路径用了」。逐条假设见 §3。
4. **Method 类 0 个未使用**。也就是说，就 profile 已登记的符号而言，
   **不存在「getter 在用、setter 没用」的 value 写回配对** —— 这是一个精确的负面结果（§4.1）。
5. 反而更值钱的是**反向缺口**：`AuthorWriteScalar` 为 float / bool / string 声明的 3 个
   **读回 getter（`ngMKKCVBuMA` / `RJCKKnWqvLO` / `ur7KK2NiYZ4`）根本不在 profile 里**
   （生成档里出现 0 次），但代码在 `AuthoringGraph.cs:950 / :938 / :964` 用 `B(...)` 调它们。
   走 `Resolve` 会抛 `EDITOR_BINDING_PROFILE_UNREGISTERED_SYMBOL`
   （`EditorBindingProfile.cs:115-117`）。见 §4.2。

---

## 1. profile 的结构：三层，别把它们混成一个「符号表」

| 层 | 位置 | 条目数 | 作用 |
|---|---|---|---|
| `LegacySymbols`（HashSet） | `:8-317` | **307** | fail-closed 名单：本构建**必须**能映射的旧名 |
| `Symbols`（legacy→actual 字典） | `:321-630` | **307** | 真正的解析表，`ResolveInProfile` 查它（`EditorBindingProfile.cs:110-114`） |
| `Contracts`（元数据契约） | `:631-946` | **313** | 校验「解析出来的 actual 名」在编辑器程序集里**真的存在且签名一致** |

- 关系：**每个 legacy 符号（307/307）都至少压中一条 contract**，没有「有映射、无契约」的悬空条目。
  按 actual 名归类到 contract 后：Field 157、Method 85、Type 63、Property 1、嵌套名别名 1
  （`ULcU3FaeSaW8mUS8GDgi`，见 §3.4）。contract 覆盖 **242 个不同的成员名 + 64 个不同的类型全名**。
- 注意 contract 的 **Type 行**（`MemberName == null`）引用的是 **actual 类型名**；
  有些 actual 类型名（如 `alDQGaXN6xuqGOMAqqaB.oKWD1gXNh3WjvDNoejLm`）在 legacy 侧对应的是一个
  **完全不同的旧名**（`eFwIefiyuoKqF5Xvj0lt.vZll0FiyKKPTI3JUkFjF`）。查「有没有被用」必须查 **legacy 名**，
  查 contract 签名才用 actual 名。
- 格式层面的一个盲点：`BindingKind.Property` 的契约校验**只取 get accessor**
  （`EditorBindingProfile.cs:376` `properties[0].GetGetMethod(true)`），
  因此**属性 setter 永远不进校验**。构造器也显式不在范围内（`:412-413`）。

---

## 2. 按 kind 分组 + 引用统计

检索方法：把 307 个 legacy 名当作**精确字符串字面量**在 52 个非生成 .cs 里逐一搜。
**带注释与剥注释各跑一遍，结果完全一致**（没有任何符号只出现在注释里），所以下面的数字不靠注释撑。

| kind | 符号数 | 已引用 | 未引用 |
|---|---:|---:|---:|
| Field | 157 | 153 | **4** |
| Method | 85 | 85 | **0** |
| Type | 63 | 59 | **4** |
| Property | 1 | 1 | 0 |
| 嵌套名别名（`ULcU3FaeSaW8mUS8GDgi`） | 1 | 1 | 0 |
| **合计** | **307** | **299** | **8** |

引用路径分两种，都算「被引用」：

- **278 个**直接出现在 `B("…")` 实参里（正则 `\bB\("[^"]*"\)`，全 Adapter 共 281 个不同的字面量实参，
  其中 3 个不在 profile 里 → §4.2）。
- **21 个**走间接路径，最终仍进 `B()`/`Resolve()`：如 `SceneCatalog.cs:60-61` 的
  `read(model,"dmhiSVca7Ew")`、`FrontendCommands.cs:120` 的 `Read()`（`string mapped = name=="containerType" ? name : B(name);`）、
  `ClientScriptFolderEvidence.cs:11-18` 的 `Resolve("…")`。

引用热度 Top 10（全 Adapter 计数）：`namiwGPRyPS`→`L0kXNqYb39f` 74 次、`c1pKbESgr8S`→`asgX55hmmsj` 67、
`MfLKK0bLIju`→`WpAXkDFUJSg` 30、`SH7KKvk8cxe`→`QkpX9zVTwV4` 30、
`mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q`→`RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx` 28、
`hWTK5MSRidQ`→`c5tXUcCFkyy` 23、`TqBK5Pk3Cw2`→`dFAXU0HNnHG` 22、`Qi8iCzKCkTt`→`xVGXdUihBZU` 22、
`U0oKESVcL9L`→`TW7XgvMJClD` 17、`tLtKHleyQAZ`→`IY7Xlyd5O4s` 17。

---

## 3. 未使用的 8 个符号（逐条：是什么 + 一行假设能解锁什么）

按「归属类型」聚类列，因为 8 个里有 6 个其实是 2 个完整小簇。

### 3.1 簇 A — 一个「(记录, 序号)」二元组类型，整簇没用（3 个符号）

| 符号 | 行 | 形态 |
|---|---|---|
| `tmaHwGXJRhWVDA3pLtso.RaTgnVXJEupvAag1ZkpU` | `:21`（同名 key）、`:334`、Type contract `:675` | 类型本身 |
| `OjHXJOmuWgf` | `:18`、`:331`、Field contract `:672` | 字段 `Boxed'1<tkvOndLluGfYKDDusXdN.k8YsY8LlfZTdUYkZusUJ>`（实例） |
| `rjFXJZrecZW` | `:19`、`:332`、Field contract `:673` | 字段 `Boxed'1<System.UInt32>`（实例） |

**假设**：这是一个**键值行/表项**类型 —— 一个 `k8YsY8LlfZTdUYkZusUJ` 记录配一个 `uint` 序号。
整簇 3 个符号 0 引用，说明我们现在只会**单值装箱读**，不会**按行读一张表**。
读它会解锁「枚举/定位 `k8YsY8…` 表里的行」，是 mihoyobin 资源表按行反查的最短路径。

### 3.2 簇 B — 目录节点：第三个字段在用，另两个字段没人读（2 个符号）

归属类型 `alDQGaXN6xuqGOMAqqaB.oKWD1gXNh3WjvDNoejLm`（**该类型在用**，legacy 名
`eFwIefiyuoKqF5Xvj0lt.vZll0FiyKKPTI3JUkFjF`，`FrontendCommands.cs:128`）。

| 符号 | 行 | 形态 |
|---|---|---|
| `sBxXChE1LlH` | `:24`、`:337`、Field contract `:667` | `List<alDQGaXN6xuqGOMAqqaB.oKWD1gXNh3WjvDNoejLm>`（**自引用子列表**） |
| `WFOXC67MHI8` | `:20`、`:333`、Field contract `:674` | `v14VncXLVn61xcWY9dpL'2<…KvJgwuXNlxF6PjfJpNu8, …moE38SXC9pf6uO1iE4fY>`（**二元映射**） |

同一类型里第三个字段 `gvkXCbkuajF`（`Boxed'1<yPrXBaXNJsDmAEiZ2EbU.nQOk3jXNCZCg75K429aF>`）
**在用**（legacy `q5nie3xqPAT`，`FrontendCommands.cs:214`）。

**假设**：这是一个**目录/分类节点**，我们已经会读它的一个装箱子元素，但不会**整列/整表遍历**。
`List<自身>` = 子目录数组、`v14VncXLVn61xcWY9dpL'2<K,V>` = 键索引子表。
读它们解锁「一次走完一整层分类树」，而不是逐个 box 抠 —— 与
`FrontendCommands.cs:83-99` 里那条 `List<>` 队列遍历互补（那条走的是另一条子链）。

### 3.3 簇 C/D/E — 三个「类型名没人用、但成员被别的路径用着」的类型（3 个符号）

| 符号（legacy → actual） | 行 | 它唯一的成员 | 成员是否在用 |
|---|---|---|---|
| `bU5PYgKXi54pAxENt7nn.M9xFPCKX3nwCN5mCtXPs` → `FBtVWWjBJ7BhVZQHEumj.NcN2KhjBCdKqRhwHYqVl` | `:189`、`:504`；Type contract `:814` | `YnajBSt2s98`：`System.Action` | 在用（legacy `Te1KXhuGxBC`，`PanelOpen.cs:32`） |
| `gOTkLGae2aX1iLOIhHQU.ULcU3FaeSaW8mUS8GDgi` → `w3KlhlRmEir4QG7UZjeB.oPbtvQRmD4pZT1DITGxA` | `:224`、`:538`；Type contract `:782` | **无任何成员契约** | — |
| `laL2vUinUKJcfsweoR3y.gAmEoVino3be16ZmfJel` → `jA6O9UXGmC0qDnRsc0Lk.Rr6npIXGRG9Hrrctj9Fe` | `:246`、`:560`；Type contract `:869` | `VDRXGJnPdBD`：`b4TTIkXazQTiJWMOSL1s.m571ZbXa3WO1Va1SOsq3` | 在用（legacy `JkFiGb7j1JI`，`EditorAdapter.cs:266`、`EntityCrudProbe.cs:80`） |

**假设（逐条）**：
- `…NcN2KhjBCdKqRhwHYqVl`：**事件/回调宿主类型**。代码只经单例拿到那个 `Action` 字段，从没**按类型名**
  去找它的兄弟事件 —— 解析类型名能解锁「同类型上还有哪些事件钩子」（`Action` 只有一个被登记）。
- `oPbtvQRmD4pZT1DITGxA`：**零成员契约的类型**，`Resolve` 它只为了 `GetType(fullName)`
  （`FrontendCommands.cs` 那类 `assembly.GetType(B(...))`）。它是一把**还没配锁的钥匙** ——
  可以当「该类型还存在」的存在性证明，但要新写 capability 得先补契约。
- `…Rr6npIXGRG9Hrrctj9Fe`：**图/选择的某一记录类型**，它的字段能从别的对象抓到，但类型名本身没人解析。
  解析类型名解锁「按类型拿到同类记录」，例如把实体表里的一行升级成强类型句柄。

### 3.4 附带发现 — 嵌套类型被「提升」出外层（不是未使用，但值得记一笔）

`ULcU3FaeSaW8mUS8GDgi`（`:159`）→ actual `oPbtvQRmD4pZT1DITGxA`（`:472`）**在用**
（`EditorAdapter.cs:372`：`reply?.GetType().Name == B("ULcU3FaeSaW8mUS8GDgi")`）；
而它的**旧全名** `gOTkLGae2aX1iLOIhHQU.ULcU3FaeSaW8mUS8GDgi`（`:224`）**没用**。
同一 actual 名在新构建里是 `w3KlhlRmEir4QG7UZjeB.oPbtvQRmD4pZT1DITGxA`（**提升为外层类型**的嵌套名）。
即：**新旧构建里这个类型的嵌套层级变了**，profile 用两条 legacy 名分别指旧全名与旧短名。
这正是「legacy/actual 两套命名空间」的活样本 —— 反查时**短名与全名要分别查**。

---

## 4. setter/getter 配对

### 4.1 value 写回配对（5 个 slot）：无「getter 在用、setter 没用」的配对

`AuthoringGraph.cs:890-900` 自己列了这 5 对。逐对查 profile 登记情况 + Adapter 引用情况：

| slot | setter（legacy → actual） | setter 状态 | getter（legacy → actual） | getter 状态 |
|---|---|---|---|---|
| int | `c84KKE8ihrN`→`DejX9ySn3dc` | 已登记，在用 | `ilqKKrw7dhN`→`QMOXkfIqB2G` | 已登记，在用 |
| enum | `X8oKKHB87Ue`→`xOeX9KT0Hcj` | 已登记，在用 | `cPOKKedklwd`→`BdsXk9NE0ND` | 已登记，在用 |
| string | `MfLKK0bLIju`→`WpAXkDFUJSg` | 已登记，在用 | `ur7KK2NiYZ4` | **不在 profile**（见 §4.2） |
| float | `SH7KKvk8cxe`→`QkpX9zVTwV4` | 已登记，在用 | `ngMKKCVBuMA` | **不在 profile** |
| bool | `CHHKK434xan`→`lZiX93JfX9h` | 已登记，在用 | `RJCKKnWqvLO` | **不在 profile** |

- §2 已经证明 **Method 类 85 个符号 0 未引用**，因此**不存在任何已登记的配对是「getter 在用、setter 没用」**。
  这是本次审计要的那个精确负面结论：**没有现成的、零成本的「只加写回」配对**。
- 结构性补充：全 profile 里**形如包装 getter 的方法只有 2 个**（`():Boxed'1<T>`），都在
  `iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG` 上（int 的 `QMOXkfIqB2G`、uint 的 `BdsXk9NE0ND`）；
  形如 value setter 的（`(T, ctx):Void`）有 8 个。**getter 面比 setter 面窄得多**。

### 4.2 反而是反向缺口：3 个「getter 在用、profile 里没有」

| 符号 | 被谁用 | profile 里出现次数 |
|---|---|---|
| `RJCKKnWqvLO`（bool 读回） | `AuthoringGraph.cs:938` | **0** |
| `ngMKKCVBuMA`（float 读回） | `AuthoringGraph.cs:950` | **0** |
| `ur7KK2NiYZ4`（string 读回） | `AuthoringGraph.cs:964` | **0** |

这三处都在 `AuthorWriteScalar` 的读回分支里，写成 `scalar.GetType().GetMethod(B("…"),Fields)`
——**先跑 setter、再解析读回符号**。`Resolve` 对未登记名抛
`EDITOR_BINDING_PROFILE_UNREGISTERED_SYMBOL`（`EditorBindingProfile.cs:115-117`），
所以 `set-value` 走 `slot="float"` / `"bool"` / `"string"` 时，**写已经落进原生对象、读回却抛异常**。

- string 这条路**上游已被绕过**：`AuthoringGraph.cs:804-813`（build-plan 的 values 段）显式判断
  「string 读回符号不在 profile」并改走 set-print 的 prove 过的 setter、不做读回。
  但 `set-value` 动作本身没有这条绕行，`:964` 仍是可达的死路。
- float / bool **没有任何绕行**。也就是说 `INTERFACE-INVENTORY.md:33`
  （`graph.values` 状态 partial，「待支持 bool/int/float/…」）里 float/bool 的**写**其实也不成立，
  不只是「待支持」。
- 这三个名在 `AuthoringGraph.cs:892-895` 的注释里被当成「有 in-repo 证明」的配对写下来，
  说明这是**生成档与代码的漂移**（生成器漏收，或这对 getter 从未真机验证过）。
  **要补的是 profile，不是代码** —— 这是本次审计指出的最便宜的一笔「新写入能力」。

### 4.3 其它零参方法（已登记、已用，供对照）

把 profile 里所有签名以 `():` 开头的 Method 契约按返回类型归拢（左为**去重后的 legacy 符号数**）：

- `():System.String` × **12**（`LsmiDw1hrGh`/`SiKi359WufY`/`YrFi3A6H2I8`/`d3di3bdsTUl`/`d7RiDt3rWyw`/
  `eQHi3vwxAyn`/`jtXi3msT74g`/`qFQi3il61x5`/`w5vi3EMKm7u`/`wyni3ubhjqm`/`yPFiAIrmqCV`/`zSti3Yyn65w`）
- `():System.Boolean` × **3**（`SyTKwRXfIBP`/`XnxYo1tjrX0`/`zgVKB6OS1MZ`；`XnxYo1tjrX0` 的 actual `tAQP7flBjqi`
  在 3 个类型上各有一条契约，但只占 **1** 个 legacy 符号）
- `():System.UInt32` × **3**（`G9oiCBkSaYQ`/`MexKm2jjjVm`/`VKeiBaSKFxp`）；`():System.UInt16` × 1（`oAb3IcMu6on`）
- `():System.Void` × 1（`fIviJCKIQSe`，即 `SyncEditorChanges` 调的那条 editor-wide sync，`EditorAdapter.cs:59`）
- 其余为「返回包装/句柄类」的零参方法（`Boxed'1<T>`、`qknVfrXwms8uvpf8GYF6'1<T>`、`Lazy` 类等）

以上**全部在用**，无未使用项。结论仍然只有 §4.1 的那一句：**没有「getter 在用、setter 没用」的已登记配对**。

---

## 5. 复核方法（任何人都能重跑）

1. 从 `EditorBindingProfile.Generated.cs` 取三段：`LegacySymbols`（`:8-317`）、`Symbols` 字典（`:321-630`）、
   `Contracts`（`:631-946`）。
2. 对 307 个 legacy 名做**精确字面量**检索，范围 `tools/editor-bridge/Adapter/*.cs` 去掉生成档本身（52 个）。
   建议**剥注释再跑一遍**做对照（本次两遍同结果）。
3. 未命中的 8 个再对**全 Adapter 原文**做**子串**检索（不限定字面量），确认 0 命中 ——
   排除「被字符串拼接造出来」的可能。
4. `B("…")` 实参集合与 profile key 集合求差 → 3 个未登记 getter（§4.2）。

**一句话判决**：profile 里 307 个绑定符号，299 个已经在用；没用上的 8 个里没有一个能靠「只加读回」
变成廉价新写入口；真正廉价的那笔写着不在「未使用」里，而在**缺失**里 ——
`ngMKKCVBuMA` / `RJCKKnWqvLO` / `ur7KK2NiYZ4` 这 3 个 float/bool/string 读回 getter 还没进 profile。
