> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

> **7.1版本复核（2026-09-26）**：下文保留原研究快照；旧地址、符号、统计全集和未找到结论不能直接视为7.1现状。当前接口迁移、Lua/协作等新增能力及验证边界见7.1复核报告（历史来源：`../7.1-revalidation/README.md`）。正文保留历史含义。

# 06 · WPF 代码可实现功能面

> **调查的问题：** 从代码层看，这个前端能对内容做哪些操作？有多少可被程序调用？
> **结论一句话：** 12,300 个非重复类型里，**9,218 个（75%）是「方法引用被提升成的 delegate 类型」**——
> 混淆器把方法引用做成了独立类型，是这份程序集最鲜明的结构特征；真正承载业务的是
> **2,941 个 class**，界面层 **136 个 class**（含唯一保留真名的 `FrameworkPropertyExtension`，390 成员）。
> 可被程序调用的面 = **层①进程内反射桥（62 个固定 op，59 个有调用留证；当时）** + **层②命令通道（13 通道，实测可用）**。
> （可信度：高，静态全量 + 本工程实测留证）
> **最后更新：** 2026-09-22

数据版：`db/raw/code-surface.json` → 表 `type_surface`（12,300 行）。
查询：`SELECT layer, count(*) FROM type_surface GROUP BY 1;`

---

## 一、先解释一个数字差：12,375 vs 12,300

| 目录 | 文件数 | 是什么 |
|---|---:|---|
| `.runtime/editor-catalog/decomp/BeyondEditor/` | **14,930** | 全量反编译**产出**（含 `_ERR_*.txt`） |
| `.runtime/editor-catalog/annotated/` | **12,375** | 成功写出的 `.cs`（字符串已还原） |
| 本轮扫描识别出**顶层声明**者 | **12,300** | 有 class / interface / struct / enum / delegate 声明 |
| 差 75 | — | 少数文件只有多个嵌套声明或格式特殊，未匹配到顶层声明 |

**14,930 − 12,375 = 2,555 个 `_ERR_*` 不是「反编译失败」**（沿用 `CODE-SURFACE.md` §3 的结论）：
它们是**嵌套类型**，ILSpy 按 `外层/内层` 全名单独取用时解析不到，
内容**已包含在父类型的输出文件里**。因此**代码没有缺失**。

---

## 二、代码分层（12,300 个类型）

| 层 | 类型数 | 占比 | 判据 |
|---|---:|---:|---|
| **delegate** | **9,218** | **74.9%** | 文件里有 `delegate <返回类型> <名字>(...)` 声明 |
| **business** | 2,941 | 23.9% | 其余（既非界面命名空间，也非第三方，也非编译器生成） |
| **ui** | 136 | 1.1% | `using` 里有 `System.Windows` / `System.Windows.Controls` / `.Markup` / `.Input` / `.Media` |
| **thirdparty** | 5 | 0.04% | `using` 以 `Newtonsoft` / `ICSharpCode` / `NLog` / `Harmony` 开头 |
| **compiler** | 0 | — | 匹配 `<Xxx>d__` / `<>c` / `DisplayClass` 者 |

### 2.1 「75% 是 delegate」这一条值得展开

编辑器有 **14,945 个元数据类型**，其中约 **9,218 个是 delegate 类型**。
这不是编辑器的设计风格，而是**混淆器的产物**：它把方法引用（method group）
提升成了独立的 delegate 类型，每个 type 只包一行 `internal delegate ... (...)`。

**实际影响（对后续排查很重要）：**

1. **按类型数统计「代码规模」会严重失真**——75% 的类型不含任何逻辑。
2. `CODE-SURFACE.md` §3 记的「2,159 个是 `<>c` / `<>c__DisplayClass` / `d__` 闭包」
   与本轮 0 个 compiler 层的差异，原因见 §4。
3. 想找业务逻辑，**应该直接看那 2,941 个 business class**。

---

## 三、可被程序调用的两面

### 3.1 层①：进程内反射桥（62 个固定 op，当时）

| 项 | 值 | 证据 |
|---|---|---|
| 操作数 | **62**（当时） | `tools/editor-bridge/` 白名单 |
| 有真实调用留证 | **59** | `.runtime/editor-bridge/runs/*/*-response.json`（104 个 run） |
| 从未调用 | **3** | `create/build/bind-gameloop-variant-core` |
| 执行要求 | 必须在编辑器 WPF dispatcher 上 | 桥接用 `Application.Current.Dispatcher.CheckAccess()` 自检 |
| 通式 | `Assembly("BeyondEditor")` → `ExistingSingleton(类型名)` → 读/写字段 → 调原生方法 | 实测 |

按功能域归类（详见 `docs/editor-catalog/INTERFACE-INVENTORY.md` §4）：

| 域 | op 数 | 后端 |
|---|---:|---|
| 建图（create-*） | — | 原生图管理器 |
| 建图内容（build-*） | — | 原生图模型节点/连线 API |
| 绑图 / 解绑 | — | 1018 → `beyondEditObjService` |
| 导出 | — | 1018 → `beyondExportService` / `DoExport` |
| 导入 | — | protobuf 解析 + 原生反序列化 + 图管理器 |
| 同步 | — | 原生同步管理器 |
| 日志 | — | 3001 出站 / 3002·3006 入站观察 |
| 观测 / 查询（全只读） | — | 反射读模型字段 |

> **桥的能力边界（必须一起读）**：
> 桥是**进程内**的，所以它能读到编辑器内存里的模型对象；
> 但**写**的落点受限于编辑器自己有没有那个方法。
> 「改名/删除」有（实机通过），「创建/几何变换/原生保存」没有（未找到）。
> **桥强，不等于编辑器强。**

### 3.2 层②：命令通道（13 通道，实测可用）

详见 `05-前后端通信通道.md`。要点：
- 编辑器是 **TCP 客户端**，连到 127.0.0.1 的注册表端口；
- 1018 承载 `(请求号, 服务名, 命令名, 参数表)`，响应 1019；
- **派发永不抛错、客户端不做校验、回执不是确认**；
- 本地只登记 **3 个 `wpf*Service`**，7 个 `beyond*Service` 的处理器**在对端进程**。

### 3.3 层③④：文件格式与原生模型 API

- 文件格式：`.gip/.gil/.gia/.gir`、`.mihoyobin`、`assets.bin` 均可离线解析（实测容器往返）。
- 原生模型 API：见 §五的核心对象模型。

---

## 四、与 `CODE-SURFACE.md` 的差异（口径说明）

| 项 | `CODE-SURFACE.md`（旧） | 本轮 | 说明 |
|---|---|---|---|
| 元数据类型总数 | 14,945 | 未重算 | 沿用 |
| 写出 `.cs` | 12,375 | 12,375 | 一致 |
| `_ERR_*.txt` | 2,555（全嵌套类型） | 未重扫 | 沿用旧结论 |
| 2,159 个闭包 / 396 个普通嵌套类 | 有 | **本轮 compiler 层 0** | **不是矛盾**：本轮扫描对象是 `annotated/` 的**顶层声明**，闭包类作为**嵌套类型**写在父文件里；旧结论说的是 `_ERR_*` 那批未单独写出的类型。两个口径的对象不同 |
| 命名空间骨架 | 五层（Model/ViewModel/ViewModelCore/CustomControl/BaseUtil） | 复核一致 | 见 §六 |

---

## 五、核心对象模型（可被程序作用的对象）

`CODE-SURFACE.md` §5 已列 8 个角色。本轮**逐个补充成员数与可做的操作**，
并给出**新增的第 9–14 个**。

| # | 角色 | 混淆类型名 | 成员数 | 能做什么 | 证据 |
|---:|---|---|---:|---|---|
| 1 | 资源注册表 | `ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre` | 33 | 遍历全部资源（字段 `bwbixDw3yob` = 根节点） | 实测 |
| 2 | **编辑器管理器** | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q` | **236** | 同步（`wAXirPMXQCJ` 就绪检查、`fIviJCKIQSe` 同步）、关卡状态、改名/删 PCG/聚焦 PCG | 实测 |
| 3 | 节点定义（Kind 6） | `IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C` | 111 | 节点定义；`GetPin` ×2 | 实测 |
| 4 | 节点图（Kind 9） | `cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH` | 109 | 图本体；`K61KONg4LUT` 取节点表 | 实测 |
| 5 | 实体实例 | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr` | 55 | 关卡实体；`t6ViSxlgnQ3` 取图绑定 | 实测 |
| 6 | 预制 | `nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp` | 62 | 元件/预制 | 实测 |
| 7 | 单例容器 | `yT2GjCi3sEnq3X39OnMH.vSwq2Ui3deULA6AUjQxt<T>` | — | 懒加载单例（字段 `rZmi38av5uw`） | 实测 |
| 8 | 生产者/传输 | `tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh` | — | 与游戏通信；字段 `xu7i0pEkGOC` | 静态 |
| **9** | **命令宿主 A** | `VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf` | 30 | **导出 / 挂图 / 删实体 / 删预制 / 聚焦 / 请求实例（7 条操作名）** | 静态+实测 |
| **10** | **聚焦分派器** | `FOV9AWu5QBsMPf0Rwuiu.NQ6Rasu5Wb3lL511Sp4j` | 72 | **9 条按目标类别分流的聚焦命令** | 静态 |
| **11** | **日志宿主** | `XvpSBIuvoMSpMenoIqRg.C9ev3quv9MKMEBmJNJDj` | 164 | 4 条日志导入/删除/刷新 | 静态 |
| **12** | **标签/套件宿主** | `kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0` | 107 | 改标签、改套件 | 静态 |
| **13** | **导入宿主** | `XTIMALKC7WrrvhklkdIs.EC9LaXKCud5dn7MZnrgl` | 15 | `DoImport` | 静态 |
| **14** | **WPF 附加属性表** | `BeyondEditor.ViewModelCore.FrameworkPropertyExtension` | **390** | **唯一保留真名的类型**；57 个附加属性、全部 `*Command` 输入绑定 | 静态 |

> **#9–#14 是本轮新增的核心角色**，其中 #9 与 #10 是**命令层**的关键——
> 它们是「前端把动作发给谁」的答案。详见 `04-操作名与命令绑定.md`。

### 5.1 保留真名的类型（14 个）

混淆抹掉了绝大多数符号，但**显式接口实现与 WPF 附加属性无法被改名**，因此保留了真实命名空间骨架：

| 命名空间 | 类型 |
|---|---|
| `BeyondEditor.BaseUtil` | `Tag` · `Transform` |
| `BeyondEditor.CustomControl` | `TreeListView` |
| `BeyondEditor.ViewModelCore` | `BoolInverterConverter` · `BoolReverseToVisibilityConverter` · `BoolToVisibilityConverter` · `DoubleToStringConverter` · `FloatToStringConverter` · `FrameworkPropertyExtension` · `IntReverseToVisibilityConverter` · `IntToStringConverter` · `IntToVisibilityConverter` · `KeyToTextMapConverter` · `ProgressConverter` |

⇒ 编辑器是 **Model / ViewModel / ViewModelCore / CustomControl / BaseUtil** 五层结构（沿用既有结论，复核一致）。
另有 `BeyondEditor.Model.*`（`IResourceItem` / `BMInstructionPin` / `BMFolder` 等）与
`BeyondEditor.ViewModel.*`（`QuadNode` / `IVirtualItem` / `VMInstructionConnectorBase`）出现在元数据里。

### 5.2 最大的业务类型（按成员数）

| 成员数 | 类型 | 说明 |
|---:|---|---|
| 236 | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q` | 编辑器管理器（#2） |
| 164 | `XvpSBIuvoMSpMenoIqRg.C9ev3quv9MKMEBmJNJDj` | 日志宿主（#11） |
| 145 | `mlHWVMHLMFusujv6IU5J` | 未识别 |
| 143 | `f2VPU0KMAFsCU60ufwiU` | 未识别 |
| 138 | `Q5nDFOAiFr6rFRgU63Zo` | 未识别 |
| 117 | `CVODXIArE2kpCl3MwqZP` / `A2P8lfOc8LJtSxsTpfLW` | 未识别 |
| 111 | `jxqH4eKHRgIc1AAI2M9C` | 节点定义（#3） |

> **前 10 大业务类型里有 6 个完全未识别**。这是本调研最实在的缺口：
> 成员数越大，越可能是核心子系统。它们没有任何操作名字面量，只能靠逐个反编译正文判定。

---

## 六、WPF 界面层（136 个类型）

### 6.1 界面代码在这里，但 XAML 不在

| 观察 | 值 | 证据 |
|---|---:|---|
| `using System.Windows...` 的类型 | **136** | 静态 |
| `DependencyProperty` 出现文件数 | 24 | 静态 |
| `Dispatcher` | 17 | 静态 |
| `DataTemplate` | 42 | 静态 |
| `TreeView` | 14 | 静态 |
| `TextBox` | 13 | 静态 |
| `ListBox` | 6 | 静态 |
| `: Window` 子类 | **1** | 静态 |
| `: UserControl` / `: Control` / `: FrameworkElement` 子类 | **0 / 0 / 0** | 静态 |
| 程序集内 `g.resources` / `.baml` / `pack://application` | **0 / 0 / 0** | 静态（原始字节） |

**唯一那个 Window 类：** `V6ZX1hiulU8aSgCqEGxx.zcSMA4iu1RDnZ3546OLf : Window, IComponentConnector`
- 窗口标题键 `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_WINDOW_TITLE`（「千星沙箱」）
- 字面量含 `"/BeyondEditor;component/mainwindow.xaml"`、`"Load Exception! "`、`"Init Exception! "`
- 13 个成员：构造函数（含大量控件属性设置）、`InitializeComponent`、`OnClosing`、两个 `EventHandler` 注册方法

**结论（推断，已标注）：** 发布版**没有任何可加载的 XAML 资源**，
但代码里保留了 `LoadComponent("...mainwindow.xaml")` 调用与加载/初始化两条异常文案
——最合理的解释是**构建产物与源码不一致，XAML 加载失败被 catch，界面改由代码构造**。

> ⚠️ **2026-09-22 更正（由下一轮 `../beyondeditor-user-operations/` 作出）：**
> **XAML 确实存在**，共 **48 个 `.xaml`**（`BeyondEditor` 28 + 自研控件库 `BydeCustomControl` 19 + 1），
> 组织在 `Xaml/Template/…` 树里，名字全部可从字符串表与反编译注释恢复。
> 本节「原始字节 0 命中」的观测是**对的**，但由它推出的「界面由代码构造 /
> XAML 加载失败回退」是**错的** —— 真正的原因是**编译产物被混淆器加密**。
> ⇒ 「**原始字节搜不到**」**不能**推出「**这个东西不存在**」。
> 这正是本项目反复出现的那类错误，这次错在本节。
> 更正后的结论更有用：**界面结构是可恢复的**（见该目录 `01-` 与 `02-`）。
→ **「找 XAML 读界面结构」这条路不存在文件**；界面结构只能从构造函数里的控件对象图读。
→ 反过来说，**界面是纯对象图，理论上可被程序构造/驱动**，不需要解析标记语言。
**这一步是推断，未获运行期证实，不得当已证使用。**

### 6.2 界面层里带操作名的类型（10 个）

| 成员数 | 类型 | 操作名 |
|---:|---|---|
| 390 | `FrameworkPropertyExtension` | `ShowToolTipWhenTrimmed` |
| 164 | `C9ev3quv9MKMEBmJNJDj` | 4 条日志 |
| 107 | `NNwa8GK28oPifmneADs0` | 标签/套件 |
| 101 | `B0gUrpKkSiTGJr81KypF` | 截图 |
| 72 | `NQ6Rasu5Wb3lL511Sp4j` | 9 条聚焦 |
| 60 | `tC38a9uZumHDvhgFUCLl` | 聚焦 |
| 56 | `DDfsTbumioP8OeS9Kv6f` | 性能报告 |
| 30 | `kg9jHSKBgsfObR2IXdPf` | 7 条命令 |
| 25 | `VFhmmli8t3V65hVoY5K0` | Win32（非界面） |
| 15 | `EC9LaXKCud5dn7MZnrgl` | `DoImport` |

> **只有 10 个界面层类型持有操作名**。界面层共 136 个，其余 126 个是纯布局/转换器/绑定。

---

## 七、真实方法名（代理映射）

| 项 | 值 |
|---|---|
| 代理映射条数 | **34,728**（槽位 → 真实方法名） |
| 产物 | `.runtime/editor-catalog/proxy-map-full.json`（8.0 MB） |
| 应用后语料 | `.runtime/editor-catalog/resolved/`（12,375 个 `.cs`，按真实方法名可搜索） |

**代理映射是混淆器自己的表**（内嵌资源 blob 3，277,824 字节 = 34,728 × 8），
是本工程最有价值的解码成果之一：它把「混淆调用」还原成**真实方法名**。

**本轮的使用方式**：`resolved/` 与 `annotated/` 在**字面量维度完全一致**
（各 2,803 个唯一字面量、各命中 382 个 TextMap 键）——所以本轮的字面量分析
只跑 `annotated/` 一遍，结论对两者都成立。

**尚未做的事**：34,728 条映射里**去重后有多少个独立真实方法名**、这些名字揭示了哪些功能域，
**本轮未统计**。这是一块已知的、高价值但未开采的矿——登记为缺口。

---

## 八、代码里存在但从未被调用过的功能

| 项 | 证据 |
|---|---|
| `create/build/bind-gameloop-variant-core`（3 个桥接 op） | 该批 op 中唯三无 `<op>-response.json` |
| `AutoTestClearCache` / `OpenResourceExplorerMainWithTag` | 仅字符串表，本轮 44 条操作名里不含它们 |
| `beyondPCGInstanceService` 的命令名 | 仅在字符串表，无派发调用点 |
| 六条只有命令名无调用点的 beyond 命令 | `INTERFACE-INVENTORY.md` §2.3 末 |
| 11 个在分发器被**显式忽略**的消息编号 | 1003/1005/1006/1007/1012/1013/1014/1016/1021/1023/**1024** |

---

## 九、缺口

| 缺口 | 说明 |
|---|---|
| **前 10 大业务类型中 6 个未识别** | `mlHWVMHLMFusujv6IU5J`(145) / `f2VPU0KMAFsCU60ufwiU`(143) / `Q5nDFOAiFr6rFRgU63Zo`(138) / `CVODXIArE2kpCl3MwqZP`(117) / `A2P8lfOc8LJtSxsTpfLW`(117) / `YPp5TX6REt8ZEklv9CS`(113) |
| 34,728 条代理映射的**去重方法名统计** | 未做 |
| 界面构造的真实性 | 「XAML 加载失败 → 代码构造」是推断，未获运行期证实 |
| `0Harmony` 补丁的目标方法 | 未查明。动态替换过的路径静态 IL 里看不到 |
| 代码里 216 处未还原字面量 | 属尚未取到密钥的表 |

---

## 十、可复现


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


本文件所有结论为**静态**（除非明确标注实测）；未执行编辑器、未连接游戏、未改 `GOAL.md`。
