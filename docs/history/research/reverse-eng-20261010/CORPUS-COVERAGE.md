> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 反编译语料的覆盖边界 —— 它是「部分」还是「另一版」？

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。未连桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档。
未读任何图片或 PDF。所有 scratch 产物写在 `.runtime/scratch/`（工程内）。

**本文件回答一个问题**：仓内那套 12,375 个 `.cs` 的反编译语料（`docs/research/reverse-eng-20261010/ADD-COMPONENT-TRACE.md`
§2/§5 与 `TEMPLATE-CREATE-TRACE.md` §1 的证据基础）到底覆盖了什么、漏了什么，以及——**由「加组件」那次零调用者
观察推出「语料不完整」这一步，成不成立**。

> 三层口径分开写：`工具读到了什么` / `磁盘上有什么` / `真机跑过什么`。**本文件全部是静态结论，无一条真机。**

---

## 0. 一句话结论

1. **语料的病不是「缺代码」，是「另一版」。** 反编译本身对它所针对的那个 build 是**代码完整**的：
   12,375 个顶层类型**全部**有 `.cs` 文件；2,555 个 `_ERR_*.txt` 全是**嵌套类型**，其代码以嵌套声明形式
   **内联在父类型的输出文件里**（实测：396 个真嵌套里 386 个的内层名能在父文件里找到，其余 10 个是泛型
   arity 反引号造成的命名伪影）。⇒ **`_ERR_*` 不是「没读到」，只是本工具「每类型一文件」写法的副产品**
   （与 `docs/editor-catalog/CODE-SURFACE.md:120-128` 一致，本文件独立复核）。
2. **真正致命的缺口是版本**：主语料反编译自 **7.0 build**（`BeyondEditor.dll` 17,535,896 B，
   SHA-256 `D4B429A3…3841`），而**当前安装的是 7.1 build**（18,404,248 B，SHA-256 `565dda11…678a`）。
   两版的**混淆类型名逐名不重叠**：对当前 DLL 枚举出 15,654 个类型名，只有 **23** 个与语料同名，
   且这 23 个**全是未混淆的框架名**（`Google.Protobuf.WellKnownTypes.*`、`BeyondEditor.ViewModelCore.*Converter`、
   `BeyondEditor.CustomControl.TreeListView` 等）。
3. **7.1 的完整反编译其实已经在仓里了**，只是主 pipeline 不知道它：
   `.runtime/verification/update-repair-20260925/adapter-port/decomp-7.1/`（12,955 `.cs`，**同一工具、同一形状**），
   另有字符串已还原的 `…/strings/annotated-7.1/` 与 `…/strings/string-table-7.1.json`。
   `ADD-COMPONENT-TRACE.md:224` 把「反编译 7.1」当作*尚未做*的最大空洞——**它已经做过了**，这是本次的 actionable 发现。
4. **7.1 相对 7.0 新增了 158 条字面量**，其中包含一整套 **Lua 客户端脚本子系统**（`beyondClientScriptService` /
   `wpfClientScriptService` / `Template_ClientScriptExplorerMain` / `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_*` / `*.lua`）
   与**新的建删改命令名**（`batchcreate`、`batchdelete`、`deleteSignal`、`modifySignal`、`deleteNodeConfig`、`modifyNodeConfig`）。
   ⇒ **凡是从 7.0 语料推出的「不存在某某命令 / 不存在某某调用点」的负面，都先天漏掉了这一整块。**
5. **对全工程负结论的净影响**：把证据按强度分三层——
   **强 = 命令/字面量表**（两个 build 的加密字符串表 + `backend.db.command_route` + `dispatch_entry` + `frontend.db.operation`）；
   **中 = 语料符号**（`resolved/`，代码完整但只覆盖 7.0，且看不见非符号路径）；
   **弱 = 官方文案**。
   「加组件」的负面**主要站在强层**（两个 build 字符串表都 0），故**不被语料问题削弱**；
   「建模板」的负面过去被当成语料层证据，**本轮复核发现它也站在强层**（7.1 字符串表里 `Shop`/`Currency`/`Inventory` 命令名同为 0）——
   它的真软肋是**该 UI 面板可能整块在加密 XAML / 未逆向模块里**，而不是「语料漏了」。详见 §5。

---

## 1. 语料是怎么造出来的（工具 / 输入 / 产物 / 有没有 manifest）

| 项 | 事实 | 证据 |
|---|---|---|
| 反编译器 | 自研 ILSpy 封装 `tools/editor-catalog/ilspy-dump/`（C#，`ICSharpCode.Decompiler` 9.1.0.7988，离线 NuGet） | `tools/editor-catalog/ilspy-dump/ilspy-dump.csproj`；`Program.cs:202-233` 的 `all <asm> <outDir>` |
| 遍历方式 | 枚举 `md.TypeDefinitions`，逐类型 `DecompileTypeAsString(new FullTypeName(full))` 写一个 `.cs` | `Program.cs:213-231`；跳过 `full.StartsWith("<")`（顶层 `<Module>`/`<X>d__N`）见 `Program.cs:216` |
| 文件名清洗 | `SafeName`：非字母数字/`.`/`_`/`-` 一律替换成 `_`，截断 180 字符 | `Program.cs:95-102`、`:217` |
| 全名拼法 | 嵌套类型用 `外层/内层`（递归） | `Program.cs:86-93`（`:91-92` 递归拼 `decl + "/" + nm`） |
| 输入程序集 | **唯一一个**：`C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\BeyondEditor.dll` | `CODE-SURFACE.md:239-246` 可复现命令 |
| 输入版本（关键） | **7.0**：17,535,896 B，SHA-256 `D4B429A371505FF5252E5A869A8FC250CD0924440A648FDB844A0EEBED083841` | `docs/editor-catalog/CODE-SURFACE.md:22`；`docs/research/beyondeditor-frontend/01-前端架构与程序集.md:55`；字符串表里的 `7.0_rel` / `7.0.0.47194594`（§3.1） |
| 运行日志 | `.runtime/editor-catalog/decomp.log`：只有一行 `decompiled: 12375, errors: 2555` | 该文件 |
| 前身工具 | `.runtime/research-sources/local-editor/tools/ilspy-local/Program.cs`（2026-09-14，早期版本，非递归全名）——因路径含 `<…>` 在 Windows 上非法而中止，见 `decomp-beyondeditor.log` | 两文件 |
| **manifest / provenance** | **没有。** 反编译这一步不写 `_provenance.json`，也不记入参 SHA；输入 DLL 的哈希只散落在 `CODE-SURFACE.md` 的正文里。⇒ **无法用 provenance 检出「语料是旧版」（这正是它以后会再次骗人的原因）** | 对照资源管线：`tools/editor-catalog/catalog_inputs.py:121-151` 的 `validate_provenance`（`select_decoded_entries` 的 `verify_source` 会在源文件哈希变化时**报 stale**） |
| 下游产物 | `annotate-strings.py` → `annotated/`；`resolved/` 与 `annotated/`、`decomp/BeyondEditor/` 的非 `_ERR_` 文件**名字集合完全相同**（12,375） | 实测（三目录逐一比对） |

**本步排除了什么（未反编译的东西）**：
- `BeyondEditor.exe`（364,952 B，同样混淆——`CODE-SURFACE.md:23`）、`Astrolabe/Astrolabe.dll`、全部 BCL/第三方 DLL；
- 5 个内嵌资源 blob（含 ConfuserEx VM 字节码、代理映射表、字符串表——这些**另行**用 Python 解，不在 `.cs` 语料里）；
- **加密 XAML 内容**（语料里没有任何 `.xaml` 文件，见 §3.3）；
- **没有第二套业务 DLL** 被反编译（安装目录根下与编辑器功能有关的托管程序集只有 `BeyondEditor.dll`、`BeyondEditor.exe`、`Astrolabe/Astrolabe.dll`）。

---

## 2. 量化缺口（类型层面）

| 指标 | 7.0 语料（`resolved/` + `decomp/BeyondEditor/`） | 7.1 语料（`adapter-port/decomp-7.1/`） |
|---|---:|---:|
| 程序集类型定义总数 | 14,945（`CODE-SURFACE.md:113`） | **15,654**（`.runtime/verification/update-repair-20260925/adapter-port/metadata-7.1.json` 的 `types` 长度；本轮用 `ilspy-dump types` 对当前 DLL 现场枚举，**同为 15,654**，逐条吻合） |
| 顶层、名不以 `<` 开头 | 12,375 | 12,955 |
| **有独立 `.cs` 文件** | **12,375（82.8%）** | **12,955（82.8%）** |
| 无独立文件（`_ERR_*.txt`） | 2,555（17.1%） | 2,684（17.2%） |
| ↳ 其中编译器生成（`<>c` / `<>c__DisplayClass` / `<X>d__N`） | **2,159** | 未逐条分类（同形状） |
| ↳ 其中**真嵌套类/接口/枚举** | **396** | 未逐条分类 |
| ↳ 「内层名能在其顶层祖先文件里找到」的真嵌套 | **386 / 396 = 97.5%** | 同工具、同形状 |
| 顶层、名以 `<` 开头（被跳过） | 15 | 15 |

**关于「386/396」那 10 个差额**：全部是名字带泛型 arity 反引号的嵌套类型
（例：`aA5cL3iuwrgWKH706aTX.WgJPbViuBf9F2U6oySHO/Abb3grYAn5UYH89835gx\`2`）。ILSpy 渲染泛型类型时**不写 `\`N` 后缀**，
所以「按字面名找」必然落空——是命名伪影，不是缺代码（`SafeName` 也会把 `` ` `` 变成 `_`，加剧这一伪影，见 `Program.cs:99`）。

**「被引用但无定义」**：以 `old-declarations.json` 的 **3,470** 条声明为样本，对语料全部 **12,795** 个已声明短名做基类解析，
15,124 个基类 token 里只剩 **44** 个未命中，且逐条核对后**全部是泛型类型参数或框架接口**
（`IEquatable`、`IEnumerable`、`ICollection`、`IValueConverter`、`IMultiValueConverter`、`DefaultContractResolver`…）。
⇒ **未发现「被引用却无任何定义」的用户类型**。反编译产物**没有悬空引用**。

**结论**：从「一个类型 = 一个文件、且文件=该类型的全部代码」这个口径看，
**语料对 7.0 build 是代码完整的**。ADD-COMPONENT-TRACE 里「12,375 个文件」这个数字**不构成覆盖缺口**。

---

## 3. 缺口的真实性质：四条，都不在「文件数」上

### 3.1 版本错位（最致命）
- 字符串表里躺着版本自证：**7.0 表独有** `7.0_rel` / `7.0.0.47194594`；**7.1 表独有** `7.1_rel` / `7.1.0.48145775`。
  ⇒ 主语料 = **7.0**，当前安装 = **7.1**。证据等级：**静态（字面量直读）**。
- 名字层面：对当前 DLL 枚举的 15,654 个类型名，只有 23 个与语料同名（`§0.2`），且全是未混淆的框架名。
  **混淆名是逐 build 重新随机化的**，所以「用 7.0 语料的名字去谈 7.1 的某个类」在方法上不成立。
- 时间线：`CODE-SURFACE.md:31-32`（2026-09-17）记 DLL `D4B429A3…` / 17,535,896 B 且 09-14 起未变；
  `01-前端架构与程序集.md:55`（2026-09-22 复核）仍是 17,535,896 B；
  `metadata-7.1.json`（2026-09-25）的 `source` 已是 SHA `565DDA11…`。
  ⇒ **更新发生在 2026-09-22 与 2026-09-25 之间**。

### 3.2 嵌套类型没有独立文件（对「按文件枚举」的工具有盲区）
- `type-index.json` / `literal-to-types.json` / 任何「遍历 `resolved/*.cs` 建索引」的脚本，**看不到**嵌套类型的独立条目
  （因为它们没有独立文件）。但**代码本身在父文件里**，所以「整体 grep 一个符号名」**不受影响**。
- 实用判据：**要 grep 一个符号的所有出现 → 用 `resolved/` 全集 grep，可靠**；
  **要「列出所有类型」→ 不能用 `ls resolved/`**（会少 2,555 个嵌套名；且顶层 `<…>` 15 个本来就没写）。

### 3.3 加密 XAML 内容不在语料里
- 语料里**没有 `.xaml` 文件**；只有 **47 个不同的 xaml 文件名**作为字面量出现
  （`BeyondComponentEditPanel.xaml`、`BeyondComponentEditor.xaml`、`BeyondComponentProperty.xaml`…）。
- 字符串表里能看到 XAML 的 pack URI 形如
  `pack://application:,,,/BydeCustomControl;component/Xaml/Template/ControlCommon/TextBox/TextBoxCommon.xaml`
  ——即 XAML 编译进的是 **`BydeCustomControl`** 这个程序集资源，**内容加密、磁盘字节读不到**
  （见 `docs/research/beyondeditor-frontend/01-前端架构与程序集.md` §6.2 及其 2026-09-22 更正）。
- **⇒ 任何「面板靠 XAML `DataTemplate`/`x:Type` 挂载视图模型」的接线，在语料里天然隐形。** 这是 §4 零调用者最可能的去处之一。

### 3.4 非符号路径：ConfuserEx VM / Harmony detour / 字符串表反射派发
- 编辑器**自带** `0Harmony.dll`（运行期 Detour 库，`01-前端架构与程序集.md:64-66`）——被 detour 的方法静态看不见。
- 命令字面量以「加密表里的字节偏移」形式存在，**不落地成 symbol**（`ADD-COMPONENT-TRACE.md:111-115`）。
  ⇒ 一条「按字符串名反射派发」的调用，在 `.cs` 里**不留调用点符号**——这类路径对语料 grep 永久隐形，只有查**字面量表**才能覆盖。

---

## 4. 零调用者工厂：命名空间 / 族 / UI 层是否被覆盖

**两个零调用者工厂**（`ADD-COMPONENT-TRACE.md` 的核心观察）：

| 工厂 | file:line | 所在类 | 类角色 |
|---|---|---|---|
| `RqDuurAmdYi(n7sVVSiqWIIk9pSX0G7q, kg9jHSKBgsfObR2IXdPf)` | `.runtime/editor-catalog/resolved/LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs:33` | `LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN` | 组件面板**列表** VM（继承 `y5e8iEuuN3HInfNSwGBo.cRuNQ5uuRMPpkdj2v1sp`，持 `hRwGGsitgmhQZo9c1XOp`） |
| `EFou75eU8IC(n7sVVSiqWIIk9pSX0G7q, kg9jHSKBgsfObR2IXdPf)` | `.runtime/editor-catalog/resolved/yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs:83` | `yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ` | 组件面板**列表** VM（同上族） |

- **两者都是顶层类，文件都在语料里**（不是那 2,555 个缺文件之一）。
- 命名空间是**混淆随机串**（`LyiKwiuuZOXPIU5ItQge` / `yOsfpwuuzUC3h2nZXoV9`）——**没有语义**，不能按族名归类；
  只能按**结构**归类：都继承同一个列表基类、都以 `hRwGGsitgmhQZo9c1XOp` 为实体源、都逐组件建行。
- 在 `resolved/` 与 `annotated/` **两处** grep：`RqDuurAmdYi` / `EFou75eU8IC` 各只出现 **1 次**（＝定义本身），
  VM 类名也无任何外部引用。⇒ **0 调用者，是 7.0 语料的真实空白，不是「文件被漏写」。**

**UI 层是否被覆盖：是（顶层层面完整）。**
- 语料含 **12 个真名 UI 文件**：`BeyondEditor.ViewModelCore.FrameworkPropertyExtension`（WPF 附加属性，含 `*Command` 输入绑定）
  + 10 个 `BeyondEditor.ViewModelCore.*Converter` + `BeyondEditor.CustomControl.TreeListView`。
- 另有大量混淆化的 VM 类型，字面量面含 **66 个不同的 `vmBtn*` 按钮名**、47 个 xaml 文件名、`vmComponents`/`componentName` 等。
  ⇒ **UI/视图模型层是被反编译进来的**，不是「UI 层整块缺失」。

**那为什么 0 调用者？** 四种可能，按可能性排序：
1. **接线在 7.1 里**（7.0 语料没有）——**最可能**。7.1 相对 7.0 新增了 158 条字面量、一整块 UI（§3.1、§5）；面板级 VM 的宿主完全可能是 7.1 新增/改写。
2. 接线经 **XAML DataTemplate**（§3.3）——无符号痕迹。
3. 接线经**反射/VM 字节码**（§3.4）——无符号痕迹。
4. 工厂在 7.0 里确为死代码——可能性最低但不排除。

**判别手段（按成本递增，全部离线）**：
- **先做**：在**已有的** `decomp-7.1/` + `string-table-7.1.json` 里做同样的反查（成本低，语料已在仓；注意 7.1 的代理注解在 `strings/annotated-7.1/` 里也没有，需先跑 `annotate-proxies.py` 那条链）。
- 再做：把 XAML 资源当目标（需要先解出 `BydeCustomControl` 的加密资源）。

---

## 5. 对工程负结论的影响：语料负面 vs 命令表负面

**证据强度阶梯（本文档的判决依据）**：

| 层 | 载体 | 覆盖 | 强度 |
|---|---|---|---|
| **强** | 加密字符串表（`string-table.json` legacy 2,830 / `editor71-string-table.json` 2,985）+ `backend.db.command_route`(38) / `dispatch_entry`(41) + `frontend.db.operation`(44) | 该 build 的**字面量全集**（profile 用 `entry_count` + plaintext SHA 双钉） | **硬**：任何「命令名是否存在」在此层是决定性的；且**覆盖反射派发**（§3.4） |
| **中** | 反编译语料 `resolved/`（12,375 `.cs`） | 7.0 build 的**全部符号**（代码完整，§2） | **中**：完整但不跨版本；看不见 XAML/VM/Harmony 路径 |
| **弱** | 官方文档文案 | —— | 参考 |

**逐条负结论**：

| 负结论 | 主要证据落在哪层 | 强度判决 | 说明 |
|---|---|---|---|
| **加组件不存在**（`ADD-COMPONENT-TRACE.md`） | **强**：两个 build 的字符串表均 0（`AddComponent`/`CreateComponent`…）、`command_route`/`dispatch_entry`/`operation` 全表 0；语料层（appender 只有反序列化器、面板族 0 add 按钮）是**中**层 | **强（成立）** | 语料是 7.0 这一点**不削弱**它：7.1 字符串表（同一强层）也 0。残余软肋是文档自述的「XAML 内联 / 反射」两条（`ADD-COMPONENT-TRACE.md:326-330`），与语料覆盖无关。 |
| **建模板不存在**（`TEMPLATE-CREATION-MINE.md` / `TEMPLATE-CREATE-TRACE.md`） | 过去以「语料 grep 0 命中」为主（**中**层）+ `command_route` 38 行（**强**层） | **中→强（基本成立，但软肋不同）** | 本轮复核：7.1 字符串表里 `Shop`/`Currency`/`Inventory` **命令名同样 0**，所以它也站在强层。**真软肋是「该整块 UI 面板可能根本不在被逆向的模块里」**——`TEMPLATE-CREATE-TRACE.md §0` 已自述「不是藏起来的按钮，而是这个面板从没被逆向」。 |
| 「语料推出的一切负面」（泛化） | **中** | **被 7.0→7.1 削弱** | 凡是「在某 7.0 语料里没找到某调用点」的论断，都必须先问：**该功能是不是 7.1 才有的？** 见下。 |

**这次版本错位有多要命——7.1 独有的 158 条字面量（实测全列）**：
- **一整套 Lua 客户端脚本子系统**（66 条含 `script`）：`beyondClientScriptService`、`wpfClientScriptService`、
  `Template_ClientScriptExplorerMain`、`UI_BEYOND_EDITOR_UIEDITOR_CLIENT_*`（55 条 `UI_`）、`*.lua`、`.lua`、
  `[ClientScript] … failed …`、`vmScriptVarSidebar`、`isVarPanelExpanded`…
- **新增/变动的命令名**：`batchcreate`、`batchdelete`、`deleteSignal`、`modifySignal`、`deleteNodeConfig`、`modifyNodeConfig`、`modify`、`modifypath`。
- **协作用户界面**：`UI_BEYOND_EDITOR_COOP_COLLABORATIVESECTION`、`UI_BEYOND_EDITOR_COOP_WPF_SECTION`、`isVmCoopPartVisible`。
- 反向（7.0 独有）只有 3 条：`7.0_rel`、`7.0.0.47194594`、`ChD8pmO6OJlhN6BUxW.FPVPwCbD7pmqUXHc0e`（后者是 ConfuserEx VM blob 名）。

⇒ **注意 `batchcreate` / `batchdelete` 是 7.1 才有的「批创建 / 批删」命令**：
「没有 create 命令」这类从 7.0 语料得出的概括，**在 7.1 上不成立**。这正是「语料负面偏弱」的活例子——
**不是文件漏了，是版本换了。**

---

## 6. 边界与残余不确定性

1. **本文只治「覆盖」，不治「语义」**：反编译代码完整 ≠ 读懂了混淆代码；`_ERR_` 里那 2,159 个编译器生成类型
   的代码确实内联，但**不代表**它们承载的业务被解释清楚了。
2. **7.1 语料未做本文同口径的独立复核**：`decomp-7.1/` 我只做了「同工具、同形状、文件数吻合（12,955 + 2,684 = 15,654 − 15）」
   三项核对；**没有**在它上面重跑 `§2` 的内联命中率与 `§4` 的零调用者反查。**这是本文 max 的剩余工作量，也是下一步最便宜的一刀。**
3. **混淆名逐 build 随机**是本文由「23/15,654 同名，且全是框架名」推出的**强推断**（不是从混淆器源码读到的）；
   若将来发现存在稳定的 legacy→7.1 映射表（仓内 `merged-symbols-7.1.json` 只有 **250** 条，且不含本文两个 VM 类），以那张表为准。
4. **`_ERR_` 的 2,159/396 分类用的是「名字里有没有 `<`」这一启发式**，个别边界可能归类不当；但这不影响任何结论
   （结论只依赖「386/396 真嵌套内联命中」与「名字 23/15,654 重叠」两处硬数）。

---

## 7. 本次触碰的文件

- **新增**：本文件 `docs/research/reverse-eng-20261010/CORPUS-COVERAGE.md`
- **新增（scratch 产物，工程内）**：`.runtime/scratch/corpus_gap.py`、`corpus_gap2.py`、`overlap.py`、
  `inline_test.py`、`inline_test2.py`、`basecheck.py`、`ui_cover.py`、`st_scan.py`、`table_delta.py`、
  以及 `.runtime/scratch/current-types.txt`（用仓内**已编译**的 `ilspy-dump.exe types` 对当前 DLL 现场枚举，只读）
- **未改动**任何既有文档/代码；未连桥、未发报文、未碰游戏或编辑器、未写存档；未读任何图片或 PDF。

---

## 8. 检索纪律（2026-10-11 追加）：一个负面必须同时搜**两棵**语料

本文 §0 的结论（「语料是**另一版**，不是缺代码」）有一个直接纪律后果，已单独成文并机械化：

> **一个负面结论必须点名它搜过哪些语料；只要存在兄弟语料，兄弟也必须被搜。**
> 详见 **`docs/research/reverse-eng-20261010/SEARCH-BOTH-CORPORA.md`**。

实现：`tools/editor-catalog/search-corpora.py` —— 不传语料目录，只传 `--pattern`，工具**自动发现全部
`resolved*` 兄弟语料并逐一搜**，默认 `--require-both`（发现不足两棵即 exit 2 失败）。
测试 `tools/editor-catalog/tests/test_search_corpora.py`（合成 fixture）。
⇒ 手写 `grep` 只作临时探索，**不能**作为负面的证据基础；搜语料一律走该工具。
