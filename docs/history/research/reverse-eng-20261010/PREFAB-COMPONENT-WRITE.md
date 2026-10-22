> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #5 挖 — 能不能给**预制体**加组件（prefab 命令族）

**产出日期**：2026-10-10。位置：`docs/research/reverse-eng-20261010/PREFAB-COMPONENT-WRITE.md`。
**口径**：静态语料为主（纯只读），**外加一次经工程认可的桥反射探测**（`reflection-probe`，只读）。
未改任何既有文档/代码数据、未写存档、未读任何图片或 PDF、未触碰游戏进程。helper **未重启**、**未请求 UAC**。

> 三层分开标：**语料写了什么**（静态）/ **工具能做什么**（离线源码）/ **真机跑出什么**（桥回执）。
> 本文件里「语料」结论全部标注 file:line；「真机」部分给出原始回执。

---

## 0. 一句话结论

**NO —— 预制体侧没有「加组件」这条路，和实体侧完全对称。**

- 预制体与实体**共用同一个组件行 VM**（7.0 `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW` / 7.1
  `HAZWycj0oGZJFaTJo8c9.XVcbBbj0Pal6i9RiXENV`）。这个 VM **只有两个按钮**：`vmBtnShow`（handler 空 `{}`）与
  `vmBtnDelete`（派发 3 条命令：`RequestPrefabInstance` / `DeleteComponentForPrefab` / `DeleteComponentForEditObj`）。
  **预制体那一路，组件命令只有「删」，没有「加」。**
- 整个 prefab 命令字面量表（7.0 与 7.1 **逐条相同**，7.1 仅多 2 条与组件无关的）里**没有一条 add-component**：
  `RequestPrefabInstance` / `FocusPrefabInstance` / `DeletePrefab` / `DeleteEditObj` / `FocusEditObj` /
  `ModifyPrefabName` / `ModifyPrefabTag` / `ModifyEditobjTag` / `ModifyEditObjName` / `ModifyFactionForPrefab` /
  `ModifyFactionForEditObj` / `DeleteComponentForPrefab` / `DeleteComponentForEditObj` / `ModifySuite` /
  `AddInstructionGraphForEditObj`（7.1 另有 `AddInstructionGraphForPrefab`、`ApplyPrefabInstanceChange`、`DoExportClientScript`）。
- 组件随对象**加载期装配**（工厂路径），不是命令。要「给预制的某条已有记录加组件」＝**写序列化组件记录**
  （`d5t5h9vUZHeCSba2oH5p` protobuf：f8=enabled / f16=类型枚举 / f26=载荷），不是找命令。**这一点预制与实体同构。**

> ⚠️ **真机那条腿（任务第 2 步）本轮没跑成**：`reflection-probe` op 存在（源码 + 已构建 payload 里都有），
> 桥也成功加载并对活体编辑器反射成功（`verify-interfaces` ok、`ping` ok），**但常驻 helper（pid 188156，起于
> 2026-10-10T06:19Z）早于 `elevated-runner.ps1` 的 reflection-probe 字段管道（mtime 07:24Z）**，因此它在
> **runner 层**就以 `CALL_FIELD_NOT_ALLOWED:nameContains` 拒绝了 `nameContains` 字段。**该拒绝在 08:25–08:28 之间被多个
> 并发智能体反复触发（runner.log 8 条）**，不是本文件作者的操作失误。详见 §4。

---

## 1. 起点：先把「组件面板 VM」和它的兄弟钉死

### 1.1 「组件面板」的字面名与它的实现边界

`Template_ComponentEdit_ComponentPanel` 是组件面板的模板名，它只在**模板注册表**里以字面量出现：

| 字面量 | 落点（7.0） |
|---|---|
| `Template_ComponentEdit_ComponentPanel` | `.runtime/editor-catalog/resolved/RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs.cs:258` |
| `Template_ComponentEdit_Editor` / `_EditableValue` / `_EditableStruct` / `_EditableValueList` | 同文件 `:264/:270/:276/:282` |
| `…/Xaml/Template/BeyondComponentEdit/BeyondComponentEditPanel.xaml` | 同文件 `:414`（另有 `BeyondComponentProperty.xaml:408`、`BeyondComponentEditor.xaml:420`） |

`RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs` 是**XAML 模板/样式注册表**（`Dictionary<string,ResourceDictionary>`，
见该类 `:1146` 附近的构造），不是面板 VM。**面板本身的 code-behind 不在语料里**——它随 `assets.bin`（加密 ZIP）
里的 XAML 走。这正是先前验证者说的「组件面板 VM 在语料里缺」的落实：缺的是**面板外壳**，不是组件命令。

### 1.2 「组件行 VM」＝组件面板里一行组件，预制/实体共用

| 构建 | 文件 | class | 命令字面量（file:line） |
|---|---|---|---|
| 7.0 | `.runtime/editor-catalog/resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs`（174 行） | `:14` | `DeleteComponentForEditObj` `:107`；`RequestPrefabInstance` `:127`；`DeleteComponentForPrefab` `:152` |
| 7.1 | `.runtime/editor-catalog/resolved-565dda11/HAZWycj0oGZJFaTJo8c9.XVcbBbj0Pal6i9RiXENV.cs`（187 行） | `:14` | `RequestPrefabInstance` `:123`；`DeleteComponentForPrefab` `:124`；`DeleteComponentForEditObj` `:163` |

- 两个按钮：`vmBtnShow`（7.0 `:34` / 7.1 `:34`）、`vmBtnDelete`（7.0 `:46` / 7.1 `:46`）。
  **`vmBtnShow` 的 handler 是空实现 `{}`**（7.0 `:89-91` / 7.1 `:91-93`，见 `71-ADD-COMPONENT.md` §3）。
- **同一个行 VM 同时处理预制与实体**：`DeleteComponentForPrefab` 的实参是预制模型
  (`nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp`)，`DeleteComponentForEditObj` 的实参是实体模型
  (`AooSwxiSm6Ktx99ovmnr`)——见 7.0 `:107` 与 `:152` 两行的 delegate 目标（`…::UcshNnnRJIT` vs `…::L57hfkikeB7`）。
- **这一整族（行 + 两个列表宿主 + 字段编辑器）内没有第三个按钮，也没有任何 add 命令**（`ADD-COMPONENT-TRACE.md`
  §2/§10.1 的 7.0 版 + `71-ADD-COMPONENT.md` §3 的 7.1 版）。

### 1.3 「兄弟」——预制侧的组件列表宿主

组件列表有两个宿主 VM，分别逐行枚举**预制组件集合**与**实体组件集合**（集合访问器不同）：

| 构建 | 列表 VM | 枚举的集合访问器 | 命令字面量 |
|---|---|---|---|
| 7.0 预制侧 | `resolved/LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs` | `nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp::YlJitG20qEt` | **无**（该文件 0 条 `"[A-Za-z_]{6,}"` 字面量） |
| 7.0 实体侧 | `resolved/yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs` | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr::WlJiSPfnM3R` | **无** |

⇒ **预制侧并没有一个「和组件面板并列的预制编辑面板 VM」独立类**。预制编辑复用的是：
资源项 VM（改名/改标签/改套装）、派系弹窗 VM、行 VM，以及承载命令的模型结构。下面把它们全部列出。

---

## 2. 预制命令族全清单（每个 VM 的每条命令，file:line，两构建逐条对照）

### 2.1 资源项/编辑 VM（改名、标签、套装；含右键菜单）—— 最接近「预制编辑面板」

| 构建 | 文件 | class | 命令字面量（file:line） |
|---|---|---|---|
| 7.0 | `resolved/kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0.cs`（2787 行） | `:77` | `ModifySuite` `:2030`；`ModifyPrefabTag` `:2194`；`ModifyEditobjTag` `:2255` |
| 7.1 | `resolved-565dda11/gjU5WAj1vdH3jqAWfPih.LSvKfCj1GPYOMCWEswVK.cs`（3420 行） | `:81` | `ModifySuite` `:2669`；`ModifyPrefabTag` `:2773`；`ModifyEditobjTag` `:2779` |

其右键菜单字面量（两构建同为这 9 条，**纯 UI 文案键，非命令**）：
`UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_{RENAME,DELETE,EXPORT,IMPORT,OPEN,APPLY,CHECK_REFERENCE,CHECK_FOCUS,COPY_BP_ID}`。
另有 `UI_BEYOND_ASSIST_EDITOR_ARMY_CHANGE_ARMY`、`UI_BEYOND_ASSIST_EDITOR_NODE_(DUPLICATE|MANAGER_TOP_UP|MANAGER_CANCEL_TOP_UP)`。
**这个 VM 里没有 `vmBtnAdd*`，也没有任何 add-component 字面量。**

### 2.2 派系弹窗 VM（改阵营）

| 构建 | 文件 | class | 命令字面量（file:line） |
|---|---|---|---|
| 7.0 | `resolved/VwMawhKGHsdXfkO51YfP.HDt4hxKGbds2L9ACUaAM.cs`（496 行） | `:24` | `ModifyFactionForPrefab` `:359`；`ModifyFactionForEditObj` `:408` |
| 7.1 | `resolved-565dda11/VDnlB7jdAUwlJ8C0TNie.TBajrWjdtd3FR10FJYwD.cs`（519 行） | `:25` | `ModifyFactionForPrefab` `:377`；`ModifyFactionForEditObj` `:415` |

（该 VM 全部字符串字面量：`vmItems`、`"can't set faction id for "` + 上述 2 条。）

### 2.3 编辑对象/预制实例的**模型结构**（不是面板，是命令下行壳）

7.0 `resolved/VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs`（`:44 public struct`）与
7.1 `resolved-565dda11/fYiNtsjNFLpjCdRQ3Cvj.snNdG3jNcHxXOpcU0fHG.cs`（`:45 public struct`）：

| 命令字面量 | 7.0 file:line | 7.1 file:line |
|---|---|---|
| `FocusPrefabInstance` | `:171` | `:254` |
| `RequestPrefabInstance` | `:184`、`:2337` | `:253`、`:2365` |
| `FocusEditObj` | `:231` | `:218` |
| `DeletePrefab` | `:512` | `:526` |
| `DeleteEditObj` | `:784` | `:628` |
| `DoExport` | `:1348` | `:1490` |
| `DoExportClientScript` | —（7.0 无） | `:1505` |
| `ApplyPrefabInstanceChange` | —（7.0 无） | `:1854` |
| `AddInstructionGraphForPrefab` | —（7.0 无） | `:2310` |
| `AddInstructionGraphForEditObj` | `:2118` | `:2320` |
| `attachInstructionGraph` | `:2094` | `:2555` |
| `UI_BEYOND_ASSIST_EDITOR_ARMY_CHANGE_ARMY` | `:1648` | —（在 2.1 的资源项 VM 里） |

### 2.4 原生命令 API 类（可读方法名 —— 关键）

原生编辑器命令面在一个巨大的类里以**可读公有方法 + 命令字面量**下行派发：

| 构建 | 文件 | 可读方法（声明行 / 派发字面量行） |
|---|---|---|
| 7.0 | `resolved/mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs`（28045 行） | `ModifyEditObjName` `:12589`/`:12591`；`ModifyPCGInstanceName` `:12594`/`:12596`；`DeletePCGInstance` `:12599`/`:12601`；`ModifyPrefabName` `:15039`/`:15041` |
| 7.1 | `resolved-565dda11/RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx.cs`（30221 行） | `ModifyEditObjName` `:14096`/`:14098`；`ModifyPCGInstanceName` `:14101`/`:14103`；`DeletePCGInstance` `:14106`/`:14108`；`ModifyPrefabName` `:16698`/`:16700` |

**该类的可读公有方法全表（7.1 = 25 条，7.0 = 18 条）里没有任何 `AddComponent*` / `CreateComponent*` /
`AttachComponent*` / `InsertComponent*`。** 预制相关只有 `ModifyPrefabName`（改名）。

---

## 3. 任务问题 3/4 的判决：预制侧到底有没有 ADD COMPONENT？

**NO。** 三条同向证据（注意：第 2 条是**静态侧论证**、不是活体观测；第 1、3 条取自语料；三者**不是三个独立层**——见下方「口径更正」）：

1. **命令字面量全集**（两个构建的 `resolved/` 与 `resolved-565dda11/` 全量扫）：
   `grep -rhoE '"[A-Za-z_]+(Component|Prefab)[A-Za-z_]*"'` → 组件相关字面量只有
   `DeleteComponentForPrefab` / `DeleteComponentForEditObj`（都是删）+ 模板名 + `vmComponents` + `componentName`。
   **`AddComponent`/`CreateComponent`/`Attach`/`Insert`/`ComponentForAdd` 各 0**（与 `71-ADD-COMPONENT.md` §4 一致）。
2. **reflection-probe 的源码级对照**：`tools/editor-bridge/Adapter/ReflectionProbe.cs` 的 needle 语义正是「按类型/方法名
   在活体程序集里找」。任务给的题眼是「问活体程序集」，但**静态侧已把可能的命名空间穷尽**（见 §4 的阻塞说明）。
3. **命令不是机制**：预制工厂 `mguq…Oe5aspiVGooyp47o5s0q.cs:26788 fAoiJf7HfZ1(...)` 从 protobuf 节点
   `vPeYZtvUQsPdvj80hG4R` 枚举组件载荷、逐条建 `LudM06iCRNk4iFkwqKIW` 再 `Add`（`PREFAB-COMPONENT-PATH.md` §1.3-C）。
   实体工厂走同一套（`d5t5h9vUZHeCSba2oH5p`：f8 enabled / f16 类型枚举 / f26 载荷）。

⇒ **「加组件到预制体」与「加组件到实体」是同一个问题**：要在**序列化数据**里补一条组件记录，而不是发命令。
预制的「实例化」(`RequestPrefabInstance`) 只是把已有预制搬进场景，**不新增组件定义**。

> **口径更正（2026-10-11）**：上面「三条独立」过强。第 1 条本身是**两个构建**（7.0 / 7.1）的同向扫描——这才是独立轴；
> 第 2 条是**静态命名空间穷尽**论证，不是活体观测（活程序集 == 这份 7.1 build，是重复观测）；第 3 条是机制论证。
> 故「不存在」的证据 = **两个 build 命令面同向 + 正面控制**（`DeleteComponentForEditObj` 两层都可见）。方向不变。

### 3.1 唯一可走的正路（非命令）

写「实体→组件」的序列化记录 `wFyeWxvUrZ4ClLJlFKGm.d5t5h9vUZHeCSba2oH5p`（f8/f16/f26），
或写预制工厂读的那个节点（字段 90 repeated `d5…`）。这条路对预制与实体**同一份 schema**。**未在本轮验证**。

---

## 4. 任务第 2 步：向活体编辑器要 prefab 类型/方法（本轮的实际结果）

### 4.1 桥/探测器的存在性与可用性（已实测）

| 事实 | 证据 |
|---|---|
| `reflection-probe` op 存在 | `tools/editor-bridge/ManagedBridge/BridgeServer.cs:345`（case）；`tools/editor-bridge/Adapter/ReflectionProbe.cs`（整文件，只读：`GetTypes`+`GetMethods`，不调任何方法、不读 getter，`nameContains` 必填 4..200 字符，最多 64 类型 × 40 方法） |
| 该 op 在当前 payload 里**已编译** | `.runtime/editor-bridge/ManagedBridge/bin/Release/net8.0-windows/Miliastra.EditorBridge.Net8R276.dll` 含 UTF-16 字面量 `reflection-probe` / `REFLECTION_PROBE_UNKNOWN_OR_DUPLICATE_FIELD` / `methodsTruncated`（Python 逐字节核对） |
| 活体编辑器 DLL 就是 7.1 语料源 | `<run>/compatibility.json`：`supportedDllSha256 = dllSha256 = 565DDA11…678A` = `resolved-565dda11/` 的源 DLL（`565dda11`） |
| 桥能成功注入并对活体编辑器反射 | 本轮 **R276** 注入成功（run `484cbe64-b542-4947-96a6-f8a8ef459574`，`bridge-ready.json accepted:true`）；`ping` → `ok:true,pid:120204`；`verify-interfaces` → **`ok:true`，21/21 slot 命中、0 缺失类型**（活体反射） |

### 4.2 原始回执（reflection-probe 被拒）

命令：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

原始回执（stderr，逐字）：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

落盘证据：`.runtime/editor-bridge/elevated-queue/2ac0e99c3c4c4f26a07403bbd0a8aa06.error.txt`
（以及同一模式在 `08:25–08:28` 之间的 `deabb7ec…`、`19c851e1…`、`d1cb3454…`、`e41c8d2f…` 等共 8 条，
见 `.runtime/editor-bridge/elevated-queue/runner.log:1785,1796-1807`）。

### 4.3 根因（已钉死）

- `CALL_FIELD_NOT_ALLOWED:nameContains` 只由 **runner** 抛出：`tools/editor-bridge/elevated-runner.ps1:285`。
- 该字段的放行规则在**同一脚本** `:279`：`if(op … -ceq 'reflection-probe'){$allowedFields=@('kind','runId','op','nameContains','memberContains')}`。
- 但**常驻 helper 是内存态、启动即固化脚本**（`elevated-runner.ps1` 的常驻 `while` 主循环在 `:921`，函数在进程内定义一次）：
  helper 起于 **2026-10-10T06:19:07Z**（`tools/editor-bridge/elevated-request.py status` 的 `startedUtc`），
  而 `elevated-runner.ps1` 的 mtime 是 **2026-10-10T07:24:44+08:00 = 07:24Z**（晚 1 小时）。
  ⇒ 运行的 helper 里 `Get-ValidatedCallArguments` **没有** reflection-probe 那两行，故拒绝。
- 佐证（**同一次运行内的两次 `status` 对不上**）：`status` 报 `bridgeOpCount` **07:33Z = 137** → **08:32Z = 138**
  （含 `reflection-probe`）。op 白名单由 `Get-AllowedOps` 在**每个请求**重读 `call-bridge.ps1`（现 138 条），
  而字段白名单 `Get-ValidatedCallArguments` 是**进程启动时**读入的（06:19 版，无 reflection-probe）。**两次读取
  卡在反射探测新增的那一处**——op 放行、字段拒绝，正是实测到的 `CALL_FIELD_NOT_ALLOWED:nameContains`。

### 4.4 结论（对第 2 步）

- **探测器存在、payload 有、桥可用、活体反射成功**；**唯一缺口是常驻 helper 的 runner 脚本滞后**。
- 本轮**无法**从活体程序集取到 prefab 类型/方法清单——被拦在 runner 的字段校验，**未到 bridge/adapter**。
- **不重启 helper 就无法自愈**（脚本只在启动时读一次）。任务明令「NEVER restart the helper / NEVER request a UAC」，
  故**本轮就此止步并如实上报**。修复动作＝重启 helper（需 UAC，本轮禁止）。
- **替代性的活体证据**：`compatibility.json` 已证**活体 DLL 字节 == 565dda11 == 本文件 §2/§3 所用的 7.1 语料源**。
  即：反射与读语料问的是**同一批字节**。§3 的负面因此**不依赖语料是否完整**——只要反编译对该 build 完整
  （`CORPUS-COVERAGE.md` §0.1 已证：12,375 个顶层类型全有 `.cs`，`_ERR_` 全是嵌套类型伪影）。

---

## 5. 残余不确定性（写明范围）

1. **`_ERR_*` 反编译失败文件**：7.1 有 2,684 个 `_ERR_*.txt` 不在 `resolved-565dda11/`/`annotated-7.1/` 里。
   先前的 `71-ADD-COMPONENT.md` §4.3 已核「没有任何 `_ERR_` 提及 `Component`」，且 7.1 明文稀少，故判断
   「add 藏在解不出的文件里」不成立。**本文件沿用该结论，未重复扫描**（范围声明）。
2. **XAML 内联 `Click→collection.Add(...)`**：组件面板外壳的 code-behind 在加密 `assets.bin`（未反编译）。
   若一条「加组件」路径完全内联在 XAML 事件里、且不经过任何命令字面量，则静态不可见。**两构建同等不可见**，
   且 `.gil`/protobuf 侧的组件装配机制（§3.1）表明命令面本就不是加组件的入口。**未验证**。
3. **真机反射**：本轮**未取得** prefab 类型/方法清单（§4）。要闭环此项，需一个**晚于 07:24Z 启动的 helper**。

---

## 6. 本次新增/触碰的文件

- **新增**：本文件 `docs/research/reverse-eng-20261010/PREFAB-COMPONENT-WRITE.md`。
- **构建**（任务许可的编译通道）：`pwsh -NoProfile -File tools/editor-bridge/next-revision.ps1` → 由 R275 升到 **R276**
  （该脚本改写了 `Net8R<数字>` 的 7 个文件；见其自身 §WHY THIS EXISTS）。
- **注入**（任务许可的加载通道）：`python tools/editor-bridge/elevated-request.py load --target-pid 120204` → run
  `484cbe64-b542-4947-96a6-f8a8ef459574`（`accepted:true`）。
- 只读引用的语料：`.runtime/editor-catalog/resolved/`、`.runtime/editor-catalog/resolved-565dda11/`、
  `.runtime/editor-bridge/runs/<run>/compatibility.json`、`.runtime/editor-bridge/elevated-queue/runner.log` 与
  `*.error.txt`、`tools/editor-bridge/{ManagedBridge/Adapter/Bootstrap}/**`。
- **未改动**任何既有文档/代码数据；**未写存档、未触碰游戏、未读图片或 PDF、未重启 helper、未请求 UAC**。
