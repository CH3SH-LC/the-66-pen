> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# CORPUS-EXPANSION-FEASIBILITY — 语料能不能扩、拿什么扩、扩到哪一步就停

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。未连桥、未发任何 native/graph 请求、未启动或触碰编辑器或游戏、未写任何存档。
**只读动作**：`sha256sum`、`find`/`ls`、Python 直读 DLL 字节与仓内 JSON/SQLite、跑仓内既有的两个只读脚本
（`.runtime/scratch/overlap.py`、`.runtime/scratch/corpus_gap.py`）。**未运行任何反编译器**（`ilspy-dump` 未执行）。
**本文件是唯一产出**；未改 `tools/`、未改任何 pin、未改任何测试。

---

## 0. 一句话结论

> **能扩，而且是「(a) 用现有工具直接扩」——不是新建工具、更不是被封死。**
> 反编译语料（12,375 `.cs`）是 **legacy build**（`BeyondEditor.dll` 17,535,896 B / SHA `d4b429a3…`），
> 而**当前安装的是 7.1 build**（18,404,248 B / SHA `565dda11…`）——**两者不是同一份程序集**。
> 三个工具的 profile 表里 **7.1 的常量已经全部在位**（`string_table.py:228`、`resolve-proxy.py:46`），
> 当前 build 的字符串表**今晚已被离线解出**（2,985 条，`.runtime/scratch/editor71-string-table.json`）。
> **唯一没做的一步，就是在当前 DLL 上跑一次 `ilspy-dump all`。** 这是「取证空洞」，不是「能力墙」。
>
> **但必须同一条结论里说清反面**：扩语料**拿不到 XAML/BAML 的界面标记内容**——那是 ConfuserEx 资源保护
> 加密掉的（原始字节 `g.resources`/`.baml`/`pack://application` **各 0 命中**），任何反编译器都读不到。
> 好在这条**不是**当前缺口的成因：本轮核过，`AddComponent` 家族在 **7.1 的完整字符串表里也是 0 命中**
> （`ADD-COMPONENT-TRACE.md:38`），加组件的行为**不在界面标记里**，所以「拿不到 BAML」不影响这条路。

---

## 1. 12,375 个文件是怎么来的（工具 + 输入 + 命令，`file:line`）

### 1.1 工具

| 项 | 值 | 证据 |
|---|---|---|
| 工具源码 | `tools/editor-catalog/ilspy-dump/Program.cs`（C#，net9.0） | 逐行读 |
| 二进制 | `tools/editor-catalog/ilspy-dump/bin/Release/net9.0/ilspy-dump.exe`（156,160 B，2026-09-20 构建） | `ls` |
| 反编译引擎 | `ICSharpCode.Decompiler` **9.1.0.7988**（离线 NuGet，`NuGet.config` 指向仓内包缓存） | `ilspy-dump.csproj`、`ilspy-dump.deps.json` |
| 关键命令 | `all <asm> <outDir>` —— 遍历全部 `TypeDefinition`，逐个 `DecompileTypeAsString` | `Program.cs:202-233` |
| 「每类型一文件」写法 | 成功写 `SafeName(full)+".cs"`（`:217,222`）；异常写 `"_ERR_"+SafeName(full)+".txt"`（`:227`） | `Program.cs:213-231` |
| 跳过的类型 | `if (full.StartsWith("<")) continue;` —— 只跳**全名以 `<` 开头**的（顶层编译器类型） | `Program.cs:216` |

> 仓内另有**同源的第二份拷贝** `.runtime/research-sources/local-editor/tools/ilspy-local/Program.cs`（多一个 `find`/`members` 命令）。
> `_ERR_*.txt` 里的堆栈指向 `tools/editor-catalog/ilspy-dump/Program.cs:197`，**证明实际生产语料的是这一份**。

### 1.2 输入程序集

| 项 | 值 | 证据 |
|---|---|---|
| 输入路径 | `C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\BeyondEditor.dll` | 安装目录 = `docs/research/beyondeditor-frontend/01-前端架构与程序集.md:19` |
| 输入大小 | **17,535,896 B** | `docs/editor-catalog/CODE-SURFACE.md:22`；`.runtime/editor-catalog/install-inventory.json`（`BeyondEditor.dll` 条目） |
| 输入 SHA-256 | `D4B429A371505FF5252E5A869A8FC250CD0924440A648FDB844A0EEBED083841` | `CODE-SURFACE.md:22`；`string_table.py:247`（label `editor-legacy`） |

### 1.3 命令（原文在 `docs/editor-catalog/COMMAND-CHANNEL.md:256-266`）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**产物实测**：`.runtime/editor-catalog/decomp/BeyondEditor/` = **14,930 个文件** = 12,375 `.cs` + **2,555** `_ERR_*.txt`
（`ls | wc -l` 实测 + `ls | grep -c '^_ERR_'` 实测）。`annotated/`、`resolved/` 各 **12,375** 个 `.cs`（`ls | wc -l` 实测）。

---

## 2. 到底缺什么（三层，别混）

### 2.1 第一层：「2,555 个反编译失败」——**不是缺代码**，是本工具写法的副产品（已定案）

`corpus_gap.py` 实测分类（`.runtime/scratch/corpus_gap.py`，本轮跑过）：

| 类别 | 条数 | 首行异常 |
|---|---:|---|
| 编译器闭包 `<>c` | **2,069** | `System.InvalidOperationException: Could not find type definition X/<>c in type system.` |
| 普通嵌套类（含 `` `1 ``/`` `2 `` 泛型嵌套） | **396** | 同上 |
| 其它编译器生成 `<...>` | 75 | 同上 |
| 异步状态机 `<X>d__N` | 15 | 同上 |
| **合计** | **2,555** | —— |

原因：工具用 `new FullTypeName("外层/内层")`（`Program.cs:221`）按**名字**取嵌套类型，ILSpy 9.1 解析不到 `外层/内层` 形式 ⇒ 抛 `Could not find type definition`。
**这些嵌套类型的代码已内联在父类型输出里**（`CODE-SURFACE.md:120-128` 抽查：某父文件 2,913 行里，两个嵌套类型分别出现 11 次 / 93 次）。
⇒ **反编译没有缺**；`_ERR_*.txt` 只影响「按嵌套类型名单独成文件」，不影响代码可读性。

### 2.2 第二层：语料是**旧 build**——这是「当前最大的缺口」

| 事实 | legacy（语料来源） | 7.1（当前装机） | 证据 |
|---|---|---|---|
| `BeyondEditor.dll` 大小 | **17,535,896 B** | **18,404,248 B** | `CODE-SURFACE.md:22` / `sha256sum` 本轮实测 |
| SHA-256 | `d4b429a3…` | `565dda11…` | `string_table.py:247,228`；`version_guard.py:67`；`ADD-COMPONENT-TRACE.md:38` |
| `Resource/**/*.mihoyobin` 条数 | **4,098** | **4,354** | `beyondeditor-frontend/01-前端架构与程序集.md:124` / 本轮 `find -name '*.mihoyobin'` 计数实测 4,354 |
| DLL 内 `.mihoyobin` 裸字节出现次数 | **4,098** | **4,354** | `beyondeditor-frontend/01-前端架构与程序集.md:145`（§6.1「出现次数 4,098」）/ 本轮 Python `data.count` 实测 4,354 |
| `assets.bin` 大小 | 230,759,334 B | **247,487,494 B** | `install-inventory.json` / 本轮 `ls` 实测 |
| 安装目录文件总数 | 4,606 | **4,862** | `install-inventory.json`（len=4606）/ 本轮 `find -type f` 计数实测 4,862 |
| 元数据类型定义数 | **14,945** | **15,654** | `CODE-SURFACE.md:112` / `.runtime/scratch/current-types.txt`（本轮 `wc -l` 实测） |

**结论：语料与装机不是同一份程序集，装机更新（类型 +709，资源 +256）。** 语料、`string-table.json`、
`install-inventory.json`、`assets-manifest.json` **全部是旧 build 的快照**。

> **且这不是「名字对不上」那么简单**：ConfuserEx **每次构建重新随机化类型名**。本轮用仓内 `overlap.py`
> 实测：当前 DLL 的 15,654 个类型里，只有 **23 个**能在语料里找到同名文件（`overlap.py` 跑出
> `current types that map to a corpus file: 23`）。**能跨 build 存活的只有不可改名的符号**——
> 19 个 `BeyondEditor.*`（`BaseUtil.Transform`、12 个 `ViewModelCore.*Converter`、`TreeListView`、
> `FrameworkPropertyExtension`…），实测 14 个与语料精确同名。
> ⇒ **用旧语料的混淆符号名去搜当前 DLL，永远 0 命中**——搜不到不等于不存在，是名字被重掷了。

### 2.3 第三层：XAML/BAML 的界面标记内容——**确实读不到**（加密）

原始字节探针（本轮对当前 DLL 实跑）：

| 探针 | 命中 |
|---|---:|
| `g.resources` | **0** |
| `.baml` | **0** |
| `pack://application` | **0** |
| `BydeCustomControl` | **0** |
| CJK（`货币与背包`/`商店模板管理`/`系统菜单`/`编辑器`… × UTF-16LE / UTF-8 / GB18030） | **0** |

⇒ 界面标记被 **ConfuserEx 资源保护加密/搬走**；字符串被折叠成 `A ^ B` 常量（`#US` 堆只剩 684 B，`CODE-SURFACE.md:50`）。
**任何反编译器都读不到 BAML 内容。** 这条**扩语料也解决不了**，见 §5。

---

## 3. 「主界面 UI」在哪个程序集？（install-inventory.json 候选清单）

安装目录 **473 个 `.dll` + 4 个 `.exe`**（`install-inventory.json` 实测统计），其中**绝大多数是 .NET 自带运行时/框架**。
**非框架的、可能装编辑器逻辑的候选**（`install-inventory.json`，`file:line` = 该 json 的 `path`/`size`）：

| 候选文件 | 大小 (B) | 判定 |
|---|---:|---|
| **`BeyondEditor.dll`** | **17,535,896（旧）/ 18,404,248（现行磁盘）** | **编辑器全部逻辑**；唯一的 WPF `Application` + 唯一的 `Window:IComponentConnector` 都在这里 |
| `BeyondEditor.exe` | 364,952 | 启动器（同样混淆）；`CODE-SURFACE.md:23` |
| `0Harmony.dll` | 2,074,520 | 运行时补丁库（编辑器自带，非 UI） |
| `miTools.AppCommon.dll` | 37,784 | miHoYo 内部公共库（太小，装不下 UI） |
| `miTools.CrashMonitor.dll` | 35,736 | miHoYo 崩溃监控（自身是 WPF 程序，但只上报） |
| `Astrolabe/Astrolabe.dll` | 2,474,392 | 遥测/崩溃上报（`BeyondEditor.dll` 不引用它） |
| `NLog.dll` / `Newtonsoft.Json.dll` / `ICSharpCode.SharpZipLib.dll` | 941,464 / 712,464 / 267,672 | 第三方，与 UI 无关 |
| **`BydeCustomControl.dll`** | **不存在** | **不在安装目录**（`install-inventory.json` 里 0 条）——XAML 里引用的自研控件库被**并入 `BeyondEditor.dll` 或作为嵌入资源**（`beyondeditor-user-operations/01-方法论-界面怎么重建.md:106-109`） |

**判据（静态）**：`BeyondEditor.dll` 是唯一的托管 WPF 应用本体——引用 `PresentationFramework`/`PresentationCore`/`WindowsBase`/`System.Xaml`，
含唯一入口 `Application` 子类与唯一 `Window` 子类（`beyondeditor-frontend/01-…:104-116,164`）。
**主界面 UI 就在 `BeyondEditor.dll` 里**，不在别的程序集、也不在 XAML 独立文件里。

---

## 4. XAML 检查：有没有 `.xaml`/`.baml`？界面是代码还是标记？

| 检查 | 结果 | 证据 |
|---|---|---|
| `install-inventory.json` 里的 `.xaml` / `.baml` / `.resources` / `g.resources` 文件 | **各 0 条** | 本轮 Python 全表过滤（`.resources`/`.xaml`/`.baml` 后缀 = `[]`） |
| `BydeCustomControl` 目录/文件 | 0 | 同 §3 |
| 当前 DLL 裸字节 `g.resources`/`.baml`/`pack://application` | **各 0** | §2.3 探针 |
| 已恢复的 XAML pack URI 路径 | **48 个**（BeyondEditor 28 + BydeCustomControl 19 + 1） | `beyondeditor-user-operations/01-方法论-界面怎么重建.md:33-42,48-104`（从**已解密的字符串表**里读到的） |

**结论（静态，确定）**：
**界面是 XAML 定义的**（48 个 `.xaml` 的 pack URI 完整保留在字符串表里），
**但 XAML 的编译产物（BAML）连同 `g.resources` 一起被 ConfuserEx 加密/搬走了**——
**磁盘字节读不到标记内容，反编译器也读不到**。能恢复的只有**目录结构 / 面板名 / 对话框名**，不是每个面板里的按钮布局。

> **对「加组件逻辑在不在标记绑定里」的直接影响**：**不在**。本轮核到，`AddComponent` 家族
> 在 **7.1 的完整字符串表（2,985 条）里也是 0 命中**，`ForEditObj` 家族只有删（`ADD-COMPONENT-TRACE.md:38,93-101`；
> `tools/gameplan/tests/test_add_component_absent.py` 已把该负面钉成回归）。
> ⇒ **即使解开 BAML，也换不到「加组件」这条路**——它不是标记里的东西。

---

## 5. 判决：(a) / (b) / (c)

### (a) **用现有工具就能扩** —— ✅ 成立，这就是本案的判决

**证据链**：三个工具**都已经带了 7.1 profile**，不需要新工具、不需要新 key：

| 环节 | 工具 | 7.1 就绪证据 |
|---|---|---|
| 反编译 | `ilspy-dump all`（ILSpy 9.1） | 与 build 无关；对任意托管程序集可用（`Program.cs:202-233`） |
| 字符串表 | `string_table.py extract --dll …` | `string_table.py:228-244` 的 profile `editor-7.1`（`entry_count=2985`、`key_hex`、`resource`、`plaintext_sha256` **全在位**） |
| 代理映射 | `resolve-proxy.py` | `resolve-proxy.py:46-49` 的 7.1 profile（`"VuZ211wIp9Ev5FRdaD.jO4p2aLMyHPvFLPR2C"` + 5 个 seeds **全在位**） |
| 字符串还原 | `annotate-strings.py` | `annotate-strings.py:423-424` 支持 `--table-json` / `--dll`（可直接喂 7.1 表） |

**当前 build 的字符串表今晚已经解出来**（`.runtime/scratch/editor71-string-table.json`，**2,985 条**，
`plaintext_sha256` 与 profile 吻合——见 `ADD-COMPONENT-TRACE.md:99`）。**唯一没做的一步就是反编译。**

**要跑的确切命令**（先确认 SHA，再反编译到**新目录**，勿覆盖旧语料）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**代价**：纯离线、只读、无新依赖；旧语料 64 MB，新语料同量级（约 +5%）。**不触碰游戏/编辑器/桥。**

### (b) **需要新工具？** —— 只有一处，且价值接近 0

若想消掉那 2,555 个 `_ERR_*.txt`，只需把 `Program.cs` 的按名取类型改成**按元数据句柄取**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

**但那 2,555 个是嵌套类型、内容已在父文件里**（§2.1）⇒ 改了几乎不增加任何可读代码。**不建议为此单开工具。**

### (c) **被封死？** —— 「扩语料」这条路**没被封死**（(a) 就够）

被 ConfuserEx 封死的只有 **BAML 的界面标记内容**（§2.3/§4）——但（i）它**不是**当前缺口的成因（§4 末），
（ii）要拿它只有两条路：**在运行中的编辑器进程里 dump 内存**（**用户硬规则禁止触碰编辑器**）或
**逆向 ConfuserEx 的资源解密例程**（该例程与 VM 字节码绑定，`CODE-SURFACE.md:64-73` blob0/blob2 至今未解）。
**两条都不在本轮允许范围，且都不是必要路径。**

---

## 6. 扩语料**不会**买到什么（写下来，免得下一轮误判）

1. **不会**买到 XAML/BAML 的界面布局与菜单文案（加密，§2.3/§4）。
2. **不会**买到「加组件」命令——它在**两个** build 的完整字符串表里都 0 命中（`ADD-COMPONENT-TRACE.md:38`）。
3. **不会**让旧语料的符号名重新可用——名字每 build 重掷（§2.2，overlap 仅 23/15,654）。
4. **会**买到：**(i)** 与当前装机一致、不再受「你搜的是旧 build」质疑的语料；
   **(ii)** 15,654 个类型（比旧语料 **+709**）里**新增**的那部分代码；
   **(iii)** 一份与 7.1 字符串表/代理表对齐的 `resolved-565dda11/`（可按真实方法名 grep）。
5. **风险（未证，须实测）**：`annotate-strings.py` 走 `--dll` 时按 DLL 的 SHA 选 profile（`:454-456`），
   `resolve-proxy.py` 亦按 SHA（`:99`）——若 7.1 的 `entry_count`/解密结果与 profile 不符会**报错而非静默出错**
   （`string_table.py:433-436`），所以**失败是响亮的**，这降低误判风险。

---

## 7. 证据索引（本轮亲自复现的 `file:line`）

| # | 事实 | 出处 |
|---|---|---|
| 1 | 工具/命令：`ilspy-dump all` + 后续 3 步 | `docs/editor-catalog/COMMAND-CHANNEL.md:256-266` |
| 2 | `all` 的实现（跳过 `<`、写 `_ERR_`） | `tools/editor-catalog/ilspy-dump/Program.cs:202-233`（跳 `<` 在 `:216`，写 ERR 在 `:227`） |
| 3 | 输入 = 17,535,896 B / `d4b429a3…` | `docs/editor-catalog/CODE-SURFACE.md:22`；`tools/editor-catalog/string_table.py:247` |
| 4 | 现行装机 = 18,404,248 B / `565dda11…` | 本轮 `sha256sum`；`tools/compatibility/version_guard.py:67`；`ADD-COMPONENT-TRACE.md:38` |
| 5 | 语料 = 12,375 `.cs` + 2,555 `_ERR_*.txt`（共 14,930） | 本轮 `ls` 计数 + `grep -c '^_ERR_'`；`CODE-SURFACE.md:112-115` |
| 6 | 2,555 全是嵌套类型（2,069 `<>c` / 396 嵌套 / 75 `<>` / 15 状态机） | 本轮跑 `.runtime/scratch/corpus_gap.py`；`CODE-SURFACE.md:120-128` |
| 7 | 类型名每 build 重掷（overlap 仅 23） | 本轮跑 `.runtime/scratch/overlap.py` |
| 8 | 当前类型数 15,654 vs 元数据 14,945 | 本轮 `wc -l .runtime/scratch/current-types.txt`；`CODE-SURFACE.md:112` |
| 9 | 7.1 字符串表已解（2,985 条） | `.runtime/scratch/editor71-string-table.json`（本轮 `len` 实测）；`ADD-COMPONENT-TRACE.md:99` |
| 10 | 7.1 profile（字符串表 + 代理表）全在位 | `tools/editor-catalog/string_table.py:228-244`；`tools/editor-catalog/resolve-proxy.py:46-49` |
| 11 | 候选程序集清单与大小 | `.runtime/editor-catalog/install-inventory.json`（本轮 Python 汇总） |
| 12 | 无 `.xaml`/`.baml`/`BydeCustomControl` | 本轮 Python 过滤 inventory；`beyondeditor-user-operations/01-…:106-109` |
| 13 | XAML 存在但被加密（48 个 pack URI） | `beyondeditor-user-operations/01-方法论-界面怎么重建.md:33-42,48-104` |
| 14 | 加组件在两 build 皆 0 命中 | `docs/research/reverse-eng-20261010/ADD-COMPONENT-TRACE.md:38,93-101` |
| 15 | 语料是旧 build = 当前最大取证空洞 | `docs/research/reverse-eng-20261010/ADD-COMPONENT-TRACE.md:222-224` |
