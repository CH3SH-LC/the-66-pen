> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# UNBOUND-SYMBOL-AUDIT — 有多少 adapter 解析了「绑定档里没有」的符号

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未读 `LocalLow/`、未读任何图片或 PDF**。
（遵守记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only`。）
证据来源：① 仓内 C# 源码 ② `.runtime/verification/update-repair-20260925/adapter-port/metadata-7.1.json`（pinned PE 元数据）③ 同目录 `decomp-7.1/`（同一构建的反编译语料）④ `.runtime/editor-catalog/resolved/`（中间构建的反编译语料，含 `-> Type::Member` 解析注记）。第 ④ 类用 **Bash `grep`**（Grep 工具会静默跳过 `.runtime/`，见记忆 `grep-tool-skips-runtime-dir`）。

> 按 `CLAUDE.md` §一.3：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 本文件全部结论是**静态**的；**没有一条是本轮真机跑出来的**。凡「搜不到」均写明检索范围（记忆 `absence-of-evidence-discipline`）。

---

## 0. 一句话结论

**「解析了未绑定符号」这类 bug 在 Adapter 里一共 5 个符号，分布在 2 个 adapter：**

| # | adapter:file | 符号（legacy） | 所在行 | 现状 |
|---|---|---|---|---|
| 1 | `Adapter/AuthoringGraph.cs` | `RJCKKnWqvLO` | `:938` | **未绑定 → 每次 `set-value`/`build-plan` 的 `slot=bool` 抛异常（在 setter 已经写进原生对象之后）** |
| 2 | `Adapter/AuthoringGraph.cs` | `ngMKKCVBuMA` | `:950` | 同上，`slot=float` |
| 3 | `Adapter/AuthoringGraph.cs` | `ur7KK2NiYZ4` | `:964` | 同上，`slot=string` |
| 4 | `Adapter/EntityComponentDelete.cs` | `JdaiSnpkbfl` | `:63`（const）→ `:115`（`ComponentBinding`） | **未绑定 → `inspect`/`delete` 两条动作都在派发前 fail-closed** |
| 5 | `Adapter/EntityComponentDelete.cs` | `b1EiCj8P44N` | `:64`（const）→ `:116`（`ComponentBinding`） | 同上 |

**这 5 个符号在 7.1 里都还在**，且能一对一定到当代名字（§3），
所以**全部是「补绑定」的活，不是「重新挖」**——与题面给的组件修复方向一致，只是多出 3 个（AuthoringGraph 的读回 getter）。

**其余 44 个引用 resolver 的 adapter 文件里，用到的 297 个不同 legacy 符号、1140 个调用点，全部命中绑定档。** 也就是说：这个 bug 类别**已收敛到这 2 个文件 / 5 个符号**，不是散布全仓。

---

## 1. 审计方法（任何人都能重跑）

### 1.1 解析器入口与它的失败码

- `B(legacy)`（`Adapter/EditorAdapter.cs:87`：`static string B(string legacy) => EditorBindingProfile.Resolve(legacy);`）
  → `EditorBindingProfile.Resolve`（`Adapter/EditorBindingProfile.cs:96`）→ `ResolveInProfile`（`:105`）。
- `ResolveInProfile` 的三条出口（`EditorBindingProfile.cs:110-117`）：
  - 命中 `profile.Symbols` → 返回当代名；
  - 命中 `LegacySymbols` 但 `Symbols` 里没有 → `EDITOR_BINDING_PROFILE_REQUIRED_BINDING_MISSING`；
  - 两者都没有 → `EDITOR_BINDING_PROFILE_UNREGISTERED_SYMBOL`。
- **两种失败都在「任何原生调用之前」抛**（resolver 是纯查表的，见 `EditorBindingProfile.cs:103-118` 的注释「Pure」）。
  所以未绑定符号**不会**造成「调错成员」；它造成的是**具名异常 + 该 op 整体不可用**。

### 1.2 绑定档的符号域

`Adapter/EditorBindingProfile.Generated.cs`：

| 层 | 行 | 条数 |
|---|---|---|
| `LegacySymbols`（HashSet，fail-closed 名单） | `:8-317` | **307** |
| `Symbols`（legacy→actual 字典，`ResolveInProfile` 查它） | `:321-630` | **307**（与上双射） |
| `Contracts`（元数据契约，校 actual 名） | `:631-946` | **313** |

本次审计的「已绑定」判据 = **符号是否在 `Symbols` 字典的 key 里**（等价于 `LegacySymbols`，二者双射）。
`Contracts` 引用的是 **actual** 名，不是 legacy 名，所以**对 legacy 符号而言它不构成「已绑定」**；
不过仍按题面要求两层都查：§2 的 5 个符号在生成档里**两层皆 0 命中**（`grep -c` 全为 0，见 §2.2/§3.2）。

### 1.3 抽取「resolver 输入」的完整口径

只抓 `B("字面量")` 会**漏掉组件那个 bug**——组件用的是 `B(常量)`。所以本次把 **6 类转发器**的入参全部还原（转发器＝函数体里把某个形参交给 `B()`/`Resolve()` 的函数）：

| 转发器 | 定义 | 符号在第几参 | 调用点示例 |
|---|---|---|---|
| `B` | `EditorAdapter.cs:87` / 局部 `:110` | 1 | 直接字面量——绝大多数 |
| `Resolve` | `ClientScriptFolderEvidence.cs:10`、`ClientScriptReadEvidence.cs:36`、`PrefabCollectionEvidence.cs:49` | 1 | `binding.Resolve("…")` |
| `Wrap` | `AuthorEntityTag.cs:118` | 1 | `Wrap("bKliA0tj1p1", …)`（`:119`） |
| `Part` | `AuthoringGraph.cs:548,641` | 1 | `Part("pR9KY126SEr")`（`:550,643`） |
| `ComponentBinding` | `EntityComponentDelete.cs:102` | 1 | **`ComponentBinding(ComponentListField71)`（`:115`）＝ 本 bug 的载体** |
| `read`/`Read`/`ContentStored`/`Stored` | `SceneCatalog.cs:56`、`FrontendCommands.cs:118`、`ReopenContentEvidence.cs:118`、`ClientScriptReadEvidence.cs:51` | 2 | `read(model,"dmhiSVca7Ew")`、`ContentStored(node,"tLtKHleyQAZ")` |

**判定要点（这也是本题「测试不能靠附近注释」的落点）**：
- 常量入参必须**跟着常量声明走**：`ComponentListField71 = "JdaiSnpkbfl"`（`EntityComponentDelete.cs:63`）在 `:115` 被交给 `ComponentBinding`，再由 `:104` 的 `B(legacy)` 解析。只 grep `B("…")` 字面量**看不见它**。
- 「看起来像符号」的字符串要按**用途**筛：`Part("from")`/`Part("to")`/`Part("fromKind")`（`AuthoringGraph.cs:786,789`）是另一支**读 JSON**的局部 `Part`（`:784`），**不进** resolver；`read(value,"containerType")`（`FrontendCommands.cs:72`）被 `Read` 显式绕过（`:120`：`name == "containerType" ? name : B(name)`），也**不进** resolver。这 7 个是本次审计里唯一的「疑似但确认无风险」项。

### 1.4 抽取结果（原始）

- 非生成 adapter 文件 **54** 个；引用 resolver 符号的 **46** 个；完全不引用的 8 个（`AudioEvidence.cs`、`ComponentGeometryEvidence.cs`、`DynamicProxyVerifier.cs`、`EditorBindingProfile.cs`、`Geometry1017Fields.cs`、`NativeSaveCatalogEvidence.cs`、`PrefabFieldRead.cs`、`TransportEvidence.cs`）。
- resolver 转发调用点 **1145**；不同 legacy 入参 **302**（已剔除 §1.3 的 7 个「疑似但按用途排除」项与形参声明噪声）。
- **未命中 `Symbols` 的：5 个（§2）**；已绑定调用点 **1140**。

---

## 2. 逐 adapter：未绑定符号（file:line）

### 2.1 `Adapter/AuthoringGraph.cs` — 3 个（全部在 `AuthorWriteScalar` 的读回分支）

上下文：`AuthoringGraph.cs:892-900` 的注释把 5 组 setter/getter 对写成「in-repo 证明」。其中 **3 个 getter 根本不在 profile 里**：

| 符号 | 调用行（`B(...)`） | slot | setter（已绑定） | 形态 |
|---|---|---|---|---|
| `RJCKKnWqvLO` | `AuthoringGraph.cs:938` | `bool` | `CHHKK434xan`→`lZiX93JfX9h` | `scalar.GetType().GetMethod(B("RJCKKnWqvLO"),Fields)` |
| `ngMKKCVBuMA` | `AuthoringGraph.cs:950` | `float` | `SH7KKvk8cxe`→`QkpX9zVTwV4` | 同上 |
| `ur7KK2NiYZ4` | `AuthoringGraph.cs:964` | `string` | `MfLKK0bLIju`→`WpAXkDFUJSg` | 同上 |

- 这 3 行**在 profile 里 0 命中**（`Symbols` 与 `LegacySymbols` 皆无），`Resolve` 会在
  `EditorBindingProfile.cs:117` 抛 `…UNREGISTERED_SYMBOL`。
- **失败点在 setter 之后**：`:937` 先 `setter.Invoke(...)`（写已落进原生对象），`:938` 才 `B("RJCKKnWqvLO")` 抛。
  `float`/`bool`/`string` 三个 slot 都是这个形态（`:949`→`:950`，`:963`→`:964`）。
- 对照：`int`（`ilqKKrw7dhN`→`QMOXkfIqB2G`，读回在 `:914`）与 `enum`（`cPOKKedklwd`→`BdsXk9NE0ND`，读回在 `:926`）两个 getter **已绑定**，所以这两条 slot 是好的。
- 这是一条**与实体组件无关、独立存在的既有 bug**，本审计把它和组件 bug 归为同一类。

### 2.2 `Adapter/EntityComponentDelete.cs` — 2 个（就是题面那个）

- 常量声明：`ComponentListField71 = "JdaiSnpkbfl"`（`:63`）、`ComponentIdGetter71 = "b1EiCj8P44N"`（`:64`）。
- 解析点：`ComponentIds()`（`:113`）在 `:115-116` 调 `ComponentBinding(ComponentListField71)` / `ComponentBinding(ComponentIdGetter71)`；
  `ComponentBinding`（`:102`）在 `:104` 走 `B(legacy)`，失败时改写成具名码 `COMPONENT_MODEL_READER_UNBOUND`（`:106`）。
- 触发点：`EntityComponentDelete()`（`:176`）在 `action` 分支**之前**就先算 before-list（`:195 var before = ComponentIds(model);`），
  所以 **`inspect` 与 `delete` 两条动作都会在派发前抛**——和 `:39-49` 的「READER NEGATIVE」注释一致。
- **两个符号在生成档里 0 命中**（已核：`grep -c "JdaiSnpkbfl" EditorBindingProfile.Generated.cs` = 0，`b1EiCj8P44N` = 0）。

### 2.3 其余 44 个引用 resolver 的 adapter：**0 未绑定**

按解析调用点排前几名（file / sites）：
`EditorAdapter.cs` 219、`GameLoopGraph.cs` 126、`AuthoringGraph.cs` 117、`InterfaceVerification.cs` 108、
`FrontendCommands.cs` 80、`FinishGraph.cs` 63……
这些文件的每一个 resolver 输入都是 `Symbols` 的 key。**没有第 3 个 adapter 染上这类 bug。**

---

## 3. 未绑定符号的「当代等价物」：全部存在，全部可补绑定

方法（同 `COMPONENT-READ-VALUE.md` / `ASSET-MEASURE-MINE.md` 用过的口径）：在两套命名空间之间做**成员签名匹配**——
中间构建（`.runtime/editor-catalog/resolved/`）给出 legacy 符号的**声明类型 + 形态**，
7.1（`metadata-7.1.json` + `decomp-7.1/`）给出当代名的**类型 + 签名 + 方法体**，按签名（外加 getter/setter 相邻性）配对。

### 3.1 组件那 2 个（7.1 名字已坐实到方法体）

| legacy | 声明（resolved 语料） | 7.1 当代名 | 7.1 证据 |
|---|---|---|---|
| `JdaiSnpkbfl` | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:65` → `public List<LudM06iCRNk4iFkwqKIW> JdaiSnpkbfl;` | **`W8QXivS0WCh`**（entity 类型 `LhusWLXd5NUZ7IineV1x.o6MMsvXduEaZkjEZB6yx` 上的 `public List<CF9E4JXdL1Cq4xrMUnCq>`） | `decomp-7.1/LhusWLXd5NUZ7IineV1x.o6MMsvXduEaZkjEZB6yx.cs:65`；`metadata-7.1.json` 该字段签名 = ``System.Collections.Generic.List`1<tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq>`` |
| `b1EiCj8P44N` | `taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW::b1EiCj8P44N`（boxed uint getter） | **`zv4XdjBAqQE`**（component 类型 `tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq` 上唯一的 `():Boxed<UInt32>` 方法） | `decomp-7.1/tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq.cs:27-30`：`public MoivF7XZA3MetiaLJVSU<uint> zv4XdjBAqQE() { return DNLXOkiAvDI(ref OgoXdqFmidJ); }` |

- 实体类型本身**已在 profile 里**：`{"Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr", "LhusWLXd5NUZ7IineV1x.o6MMsvXduEaZkjEZB6yx"}`
  （生成档 `:473`；Type 契约 `:783`）。它上面**只有少数成员**进了 profile（`:776, :783, :827, :855, :901, :933, :943`），
  **没有 `W8QXivS0WCh`**。
- component 模型类型 `tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq` 在生成档里 **0 命中**（既不作为 legacy，也不作为契约类型）。
  也就是说 `b1EiCj8P44N` 的补绑定要**同时**加「类型别名 + 成员契约」，比实体那条多一步。
- **`EntityComponentProbe.cs` 不走这条路**：它把 7.1 裸名写成 typed const（`:26` `EntityComponentsField71="EDuXiXtiyvl"`、`:28` `ComponentIdField71="OgoXdqFmidJ"`），
  直接 `GetType/GetField`（`:66-87`），**绕开 profile**。所以「读半边」即使 profile 没绑也能跑（设计如此：错契约只炸这一个 op）；
  而「删半边」（`EntityComponentDelete.cs`）**经 `B()`**，于是被 profile 卡死。**两半走的是两套策略——这才是两者状态不一致的根因。**

### 3.2 AuthoringGraph 那 3 个（按 getter/setter 相邻性 + 回读字段坐实）

3 个 getter 的声明类型是同一个：resolved 语料注记 `-> Nx9TXsKK52JgF1iQGmtH.JVhTwtKizlScEvUHNJeZ::<符号>`
（7.1 里对应 `iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG`——setter 契约就挂在这个 actual 类型上，见生成档 `:695, :745, :764, :818, :822, :859`）。

中间语料里 getter 紧挨它的 setter（`Nx9TXsKK52JgF1iQGmtH.JVhTwtKizlScEvUHNJeZ.cs`：bool `RJCKKnWqvLO`@`:410` / `CHHKK434xan`@`:415`；
float `ngMKKCVBuMA`@`:448` / `SH7KKvk8cxe`@`:453`；string `ur7KK2NiYZ4`@`:481` / `MfLKK0bLIju`@`:486`）。
7.1 同类型里同样的相邻结构 + 回读的**boxed 字段**给出唯一解（`decomp-7.1/iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG.cs`）：

| legacy getter | 7.1 getter | 它回读的 7.1 字段 | 该字段是否已在 profile |
|---|---|---|---|
| `RJCKKnWqvLO`（bool） | **`YckXk5bQBsu`**（`:403`） | `mgbXk3PAHxj`（`decomp-7.1 …:405`） | **是**，身份映射（生成档 `:361` key、`:646` Field 契约） |
| `ngMKKCVBuMA`（float） | **`RlFXkWDa66t`**（`:445`） | `F2xXkzqKsxa`（`:447`） | **是**，身份映射（`:354` key、`:639` 契约） |
| `ur7KK2NiYZ4`（string） | **`ConXkbs8Ksk`**（`:486`） | `u0HXrD9kTAg`（`:488`） | **是**，身份映射（`:367` key、`:652` 契约） |

- **判别依据链**：① 三个 getter 都 `return DNLXOkiAvDI(ref <field>)`（`:405, :447, :488`）；
  ② 每个 getter 返回类型唯一（bool 有 3 个候选 `EpiXkCRwtDN`/`dSuXk4MMLMH`/`YckXk5bQBsu`，但只有 `YckXk5bQBsu` 紧邻已绑定的 bool setter `lZiX93JfX9h`，且回读的 `mgbXk3PAHxj` 正是 profile 里唯一登记的那个 bool 槽）；
  ③ float / string 各**只有 1 个**候选，无歧义。
- **profile 缺的正是「同一类型上、同一槽位的 getter」**：字段（`mgbXk3PAHxj`/`F2xXkzqKsxa`/`u0HXrD9kTAg`）已按**身份映射**进了档，
  但它们的装箱 getter 没进——典型的**生成档漂移**（生成器收了字段、漏了同槽 getter）。
  补法与原字段**完全同构**：在 `Symbols` 里加 `{"RJCKKnWqvLO","YckXk5bQBsu"}` 等，并加 Method 契约
  ``():sGSkeTXZnJ86i9h8AAF9.MoivF7XZA3MetiaLJVSU`1<System.Boolean|System.Single|System.String>``。

### 3.3 判决

**5 个未绑定符号，5 个都在 7.1 里有当代等价物 → 0 个「真的消失」。全部是「加绑定」。**
其中 3 个（AuthoringGraph）所需的 actual 类型**已在** profile；2 个（组件）需要动到实体/组件类型——实体的类型别名已在，组件的类型别名要新增。

---

## 4. 风险排序（每个调用都跑 > 未用分支；再有副作用顺序）

判据两条：**(a) 命中频率**（每次调用 vs 未用分支）；**(b) 失败发生在几个原生调用之后**（越晚越危险＝「半个动作」）。

| 排名 | 符号组 | 命中频率 | 失败时机 | 后果 |
|---|---|---|---|---|
| **1** | `RJCKKnWqvLO` / `ngMKKCVBuMA` / `ur7KK2NiYZ4`（`AuthoringGraph.cs:938,950,964`） | **高**：`set-value` 的 `slot=bool/float/string`、`build-plan` 的同槽写值，每次必走 | **在 setter 之后**（`:937→:938` 等）——**原生对象已被写**，才抛 `UNREGISTERED_SYMBOL` | **最坏**：不是「没做」，是「写了一半然后报错」。`float`/`bool` **没有任何绕行分支**；`string` 仅 `build-plan` 那条在上游 `:804-813` 被绕过，`set-value` 动作本身仍可达（`:159`）。 |
| **2** | `JdaiSnpkbfl` / `b1EiCj8P44N`（`EntityComponentDelete.cs:63,64 → :115,116`） | **高但范围窄**：`inspect` 与 `delete` 每次调用都在 `:195` 必走 before-list | **在任何原生调用之前**（fail-closed，`ComponentBinding` 是纯查表） | 作用被限在「新加的两条 op 全不可用」；**无副作用、无半成品**，报具名码 `COMPONENT_MODEL_READER_UNBOUND`。已经写进 doctrine（`CLAUDE.md` §五）。 |

**排序理由**：作者图那条既是「每次调用」又是「副作用之后才炸」，两项都占优；组件那条虽然也是每次调用，但**在副作用之前**就 fail-closed，且被 `COMPONENT_OWNED_UNBOUND_TARGET_REQUIRED` 之类的所有权门限层层限住，爆炸半径小得多。

**未入榜但值得记**：`Part("from")`/`to`/`fromKind`/`fromIndex`/`toKind`/`toIndex`（`AuthoringGraph.cs:786,789`）与 `read(…,"containerType")`（`FrontendCommands.cs:72`）**看着像未绑定，其实不进 resolver**（前者是读 JSON 的局部函数，后者被 `Read` 显式绕过）。列出来是为了让后来者不要按字面 grep 得出假阳性——这两处**不是 bug**。

---

## 5. 与同批报告的关系

- **反向缺口**：本审计查的是「代码用了、profile 没有」；同目录 `BINDING-SYMBOL-AUDIT.md` 查的是「profile 有、代码没用」。
  两份合起来才是绑定面的两个方向。该文件 §4.2 已独立发现 `RJCKKnWqvLO` / `ngMKKCVBuMA` / `ur7KK2NiYZ4` 这 3 个
  （当时写作「3 个未登记 getter」）；**本审计补上了组件那 2 个常量入参的符号**（该文件成稿于 01:03，`EntityComponentDelete.cs` 成稿于 04:40，故未覆盖），
  并把这 5 个的 7.1 当代名逐一定到方法体。
- **方法继承**：`COMPONENT-READ-VALUE.md` §1.2 / `ASSET-MEASURE-MINE.md` §2 给出「resolved 语料 ↔ `metadata-7.1.json` 按签名配对」的口径；
  本审计把「同一类型上同签名多候选」的歧义用 **getter/setter 相邻性 + 回读字段** 消解（§3.2）。
- **修复建议**（供后续 patch 参考，非本文件职责）：5 条都按**身份/别名映射**补进 `EditorBindingProfile.Generated.cs` 的 `Symbols`
  （`YckXk5bQBsu`/`RlFXkWDa66t`/`ConXkbs8Ksk`/`W8QXivS0WCh`/`zv4XdjBAqQE`），并为后两者补 `LhusWLXd5NUZ7IineV1x…` 与
  `tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq` 的类型证据。**默认不要改调用点**——`B()` 契约本身是对的，缺的是绑定表。**唯一例外**见 `docs/gameplan/ADR-COMPONENT-SYMBOL-RESOLUTION.md`：组件 delete 的读半（`EntityComponentDelete.cs`）改用了 probe 的类型化 71 合同——因为此处不是「缺一行绑定」，而是该绑的 legacy 公开字段（`JdaiSnpkbfl`→`W8QXivS0WCh`）在两套语料里 **0 读者、非权威集合**（权威集合是 probe 已用 `EDuXiXtiyvl` 读的那一份）。本行以及 `§0 :22-23`、`§2.2 :103-111` 所描述的 `JdaiSnpkbfl`/`b1EiCj8P44N` 调用点属 **wave18 之前**的树，此行已按该 ADR 修订。

---

## 6. 复核方法（可逐条重跑）

1. **抽 resolver 输入**：对 `tools/editor-bridge/Adapter/*.cs`（去掉 `EditorBindingProfile.Generated.cs`），
   把 §1.3 那 6 类转发器的入参抽出来，**常量入参要跟到 `const string` 声明**。只 grep `B("…")` 会漏 `JdaiSnpkbfl`/`b1EiCj8P44N`。
2. **取符号域**：`EditorBindingProfile.Generated.cs` 的 `Symbols` 字典 key（`:321-630`）。
3. **求差** → 得 §2 的 5 个；再对 7 个「疑似」按**用途**排除（§1.3 末）。
4. **配当代名**：resolved 语料取声明类型 + 形态 → `metadata-7.1.json`（同签名成员）+ `decomp-7.1/`（方法体）定位；多候选时用 getter/setter 相邻性 + 回读字段消歧（§3.2）。
5. **验证器注意**：`grep "符号" EditorBindingProfile.Generated.cs` 的命中**可能是注释里引用的短名或某个契约签名的一截**，不等于「已绑定」；判据始终是 **`Symbols` 的 key**。

**一句话判决**：绑定面的这类 bug **一共 5 个符号、2 个 adapter、0 个「符号已消失」**；最危险的不是题面点名的组件（它 fail-closed），
而是 `AuthoringGraph` 那 3 个**在原生写入之后才抛异常**的读回 getter。
