> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 编辑器功能在代码上的体现

调查日期：2026-09-17。工作目录：工程根目录。本文件回答"编辑器每一项功能，在代码里对应什么"。

**本文件只写已经取得证据的内容**，并对每条标注证据等级：

| 等级 | 含义 |
|---|---|
| **实测** | 本轮或既有轮次在本机真实执行并读回 |
| **静态** | 从程序集元数据/IL/数据文件直接读出，未执行 |
| **推断** | 由命名、结构或上下文推出，未独立验证 |

---

## 一、程序集清单

安装位置在本轮更正为 `C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\`
（工程旧记录的 `D:\Program Files\miHoYo Launcher\games\...` 已失效）。

| 文件 | 字节 | SHA-256 | 作用 | 等级 |
|---|---:|---|---|---|
| `BeyondEditor.dll` | 17,535,896 | `D4B429A371505FF5252E5A869A8FC250CD0924440A648FDB844A0EEBED083841` | **编辑器全部逻辑**（托管 .NET / WPF） | 实测 |
| `BeyondEditor.exe` | 364,952 | `73B66CC6333B8E1E507304848C6AF92E08999C1BEBBF948BF75004D4A0C04DC2` | 启动器（同样混淆） | 实测 |
| `Astrolabe/Astrolabe.dll` | 2,474,392 | `D19F8C85834B31A7621E2414DB37318CF9E576839CA54C0BAB6806EBC111FB07` | 遥测/崩溃上报 | 静态 |
| `0Harmony.dll` | 2,074,520 | — | 运行时补丁库（编辑器自带） | 静态 |
| `Newtonsoft.Json.dll` | 712,464 | — | JSON | 静态 |
| `ICSharpCode.SharpZipLib.dll` | 267,672 | — | ZIP（`assets.bin` 用的就是它） | 静态 |
| `NLog.dll` | 941,464 | — | 日志 | 静态 |
| `Resource/BeyondAssets/assets.bin` | 230,759,334 | — | 加密 ZIP，231,505,907 字节载荷 | 实测 |

本轮实测：三个主程序集的 SHA-256 与工程 2026-09-14 记录**逐位一致** ⇒ 编辑器本体未变，
用户所说的"更新窗口"是重新打开，不是升级。既有反编译产物仍然有效。

**BeyondEditor 是 WPF(.NET) 而非 Unity**：程序集引用 `System.Windows.*`、`PresentationFramework`。
这决定了接口形态——所有编辑操作都是托管方法调用，不是游戏内脚本。

等级：实测。

---

## 二、保护机制与破解

### 2.1 保护是什么

`BeyondEditor.dll` 同时使用了以下保护（全部有直接证据）：

| 机制 | 证据 | 等级 |
|---|---|---|
| **名称混淆** | 14,945 个类型全部为随机名，如 `eOTRkZuGt4EBfuskhM.vVD2PHKAAodb6hF67y` | 静态 |
| **字符串删除** | `#US` 堆只剩 **684 字节**；全程序集只找到 **14 条 `ldstr`** | 静态 |
| **常量隐藏** | 字符串改为 `A ^ B` 两个 32 位字面量，运行时异或得到字符串表偏移 | 静态 |
| **防篡改** | 字面量 `{11111-22222-40001-00001}`、` is tampered.`、`SHA1` | 静态 |
| **反调试** | 字面量 `Debugger Detected` | 静态 |
| **VM 虚拟化** | 密钥恢复需要折叠 VM 字节码（见 `.runtime/mvp/string-loader-followup/DATAFLOW.md`） | 静态 |

### 2.2 字符串表与还原

字符串以 **加密 blob** 形式内嵌在程序集里（不是独立的资源文件）。
用 `dnfile` 读元数据资源表，程序集**恰好只有 5 个内嵌资源**，与本轮在元数据之后
按 `[uint32 长度][blob]` 扫描到的 5 个 blob 逐一对应：

| # | 偏移 | 长度 | 资源名 | 内容 | 状态 |
|---:|---:|---:|---|---|---|
| 0 | 16,743,096 | 13,648 | `QFvsZ60tcw0SumyexC.Ph1NcBAMGGrkSrnV0V` | **ConfuserEx VM 字节码**（既有 `vm-index.json` 记 `resource_length: 13648` 佐证） | 已定性，未使用 |
| 1 | 16,756,748 | 256 | `GGmUdkHOZ21bDc0D90.jCTtquEifH9QkSoPoy` | 防篡改校验数据（与 `SHA1` / ` is tampered.` 同处一个方法） | 已定性 |
| 2 | 16,757,008 | 99,774 | `ChD8pmO6OJlhN6BUxW.FPVPwCbD7pmqUXHc0e` | **未解** | **缺口** |
| 3 | 16,856,786 | 277,824 | `lPRYCw3VuDtuyqlGC3.EF0pHfiGVFAML29fxc` | **方法代理映射表**（34,728 条 × 8 字节 = 277,824） | **已解出** |
| 4 | 17,134,614 | 172,730 | `k0NMjJaUgmhZWiMRob.DuimXPmvaoLIiHCe8B` | **字符串表** | **已解出** |

两个已解出的资源用的是**两种不同的保护**：
代理表用一段**无密钥的 4 字节分组流密码**（工程既有 `decode_proxy_map.py` 已验证）；
字符串表用 `transform(key)`（工程既有 `string-transform/transform.py` 已验证）。
blob2 对两种算法**都解不出**（也排除了 zlib/gzip/raw-deflate/brotli），密钥与算法均未定。

加载这两个资源的类已定位：`qmcI6kYhr1tEjgMBZY1r.Y9F2H0YhZJ8wH9Xl5wuT`——
其第 413 行加载代理表、第 1682 行加载字符串表，且该类型的 `cBVYLdhAhVY`
正是字符串表的解码方法（见 `COMMAND-CHANNEL.md` §5.1）。

### 关于 blob2（99,774 字节）的定性

它**不是编辑器内容**。证据链：

1. 它的名字 `ChD8pmO6OJlhN6BUxW.FPVPwCbD7pmqUXHc0e` 只出现在**字符串表偏移 172626**，
   即代码是用字符串表解码器取到这个名字的（不是字面量）。
2. 唯一引用点在**混淆器的 VM 解释器** `kDZ3DqYLBhDOOMDtWrYM.l4AXtBYLt0KceElwYVgB`
   （3,140 行的扁平化分发器）第 2289 行：
   `new Y9F2H0YhZJ8wH9Xl5wuT.DlGlXDYLFM8S5MYoGIYr(Assembly.GetManifestResourceStream(<该名>))`
3. `DlGlXDYLFM8S5MYoGIYr` 经反编译确认只是 **BinaryReader 包装**（`ReadBytes`/`Read`/`ReadInt32`/`Close`），
   **不含任何解密**。

⇒ 它是 **ConfuserEx VM 自身的数据段**，与编辑器功能无关。这一条**不再是功能调研的缺口**；
它仍然解不开，但不需要解开。

blob 4 的密钥由既有轮次常量折叠 VM 字节码得到（`local1-key.bin`），解密例程的纯 Python
转写见 `.runtime/mvp/string-transform/transform.py`。

明文格式是 `[int32 字节长度][UTF-16LE 文本]` 的重复序列。**共 2830 条**，
锚点验证：偏移 **61834 → `Resource\Json\Beyond\Node`**，偏移 61888 → `Resource\Json\Beyond\BeyondGlobal`。

本轮工具 `tools/editor-catalog/annotate-strings.py` 把这套还原**自动化**并应用到全部
12,375 个反编译文件：**恢复 4,971 处字符串字面量，216 处未解**（属于尚未取到密钥的其它表）。
还原结果与既有轮次手工注解的文件**逐字一致**（`resource-directories.cs` 第 86 行），
说明这条链路可复现。

等级：实测。

---

## 三、反编译产物

| 项 | 数量 | 位置 |
|---|---:|---|
| 元数据类型总数 | 14,945 | — |
| 成功写出独立 `.cs` 的类型 | 12,375 | `.runtime/editor-catalog/decomp/BeyondEditor/` (64 MB) |
| 未写出独立文件者 | 2,555 | 同名目录下 `_ERR_*.txt` |
| 已还原字符串 | 4,971 处 / 2,830 条去重 | `.runtime/editor-catalog/string-table.json` |
| 带字符串的类型 | 735 | `.runtime/editor-catalog/type-index.json` |
| 字面量→类型 反查 | 2,734 条 | `.runtime/editor-catalog/literal-to-types.json` |

> **那 2,555 个不是"反编译失败"，代码没有缺失。** 全部是同一个原因：
> `Could not find type definition X/Y in type system` —— 它们是**嵌套类型**，
> ILSpy 按 `外层/内层` 全名单独取用时解析不到。分类：
> **2,159 个**是编译器生成的闭包（`<>c`、`<>c__DisplayClass`、`d__` 异步状态机），
> **396 个**是普通嵌套类。抽查证实它们的内容**已经包含在父类型的输出文件里**
> （例：注册表 `ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre` 的两个嵌套类型，
> 在该父文件的 2,913 行输出中分别出现 11 次与 93 次）。
> 因此**反编译是完整的**；`_ERR_*.txt` 只是本工具"每类型一文件"写法的副产品，
> 不代表任何一段代码没被读到。

工具链（本轮新建，全部只读、离线）：

- `tools/editor-catalog/ilspy-dump/` — 反编译与字符串提取（C#，离线 NuGet）
- `tools/editor-catalog/annotate-strings.py` — 字符串还原
- `tools/editor-catalog/index-types.py` — 类型→字面量索引
- `tools/editor-catalog/categorize-strings.py` — 字符串分类
- `tools/editor-catalog/extract-user-strings.py` — `#US` 堆提取

等级：实测。

---

## 四、编辑器真实架构（保留下来的命名）

混淆抹掉了绝大多数符号，但**显式接口实现的名字无法被改名**，因此保留了真实命名空间骨架：

| 真实命名空间 / 类型 | 说明 | 等级 |
|---|---|---|
| `BeyondEditor.Model.IResourceItem` | 资源项接口；`get_resourceItemName`、`get_resourceItemViewType`、`get_resourceItemTextType`、`get_resourceItemTextGuid`、`get_resourceItemEntityTypeUint`、`get_resourceItemFactionId`、`get_resourceItemIconPath`、`get_resourceItemIsInvisible`、`get_resourceItemIsMarked`、`get_resourceItemTextModifyTime`、`get_resourceItemModelType` | 静态 |
| `BeyondEditor.Model.BMInstructionPin` / `BMInstructionPinConfig` | 节点图引脚与引脚配置 | 静态 |
| `BeyondEditor.Model.BMFolder` | 资源目录 | 静态 |
| `BeyondEditor.ViewModel.QuadNode`、`IVirtualItem`、`VMInstructionConnectorBase` | 视图模型层 | 静态 |
| `BeyondEditor.ViewModelCore.*Converter` | 12 个值转换器（Bool/Int/Float/Double/Key→TextMap/Progress…） | 静态 |
| `BeyondEditor.ViewModelCore.FrameworkPropertyExtension` | WPF 附加属性（57 个，含全部 `*Command` 输入绑定） | 静态 |
| `BeyondEditor.CustomControl.TreeListView` | 自定义控件 | 静态 |
| `BeyondEditor.BaseUtil.Transform` / `.Tag` / `.ITagOwner` | 基础工具 | 静态 |

⇒ 编辑器是 **Model / ViewModel / ViewModelCore / CustomControl / BaseUtil** 五层结构。

等级：静态（名字来自元数据，非推断）。

---

## 五、核心对象模型（接口可作用的对象）

工程桥接已在用下列类型，它们就是"改内容"的作用对象：

| 角色 | 混淆类型名 | 成员数 | 桥接中的用途 | 等级 |
|---|---|---:|---|---|
| 资源注册表 | `ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre` | 33 | 遍历全部资源（字段 `bwbixDw3yob` = 根节点） | 实测 |
| **编辑器管理器** | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q` | 235 | 同步（`wAXirPMXQCJ` 就绪检查、`fIviJCKIQSe` 同步）、关卡状态 | 实测 |
| 节点定义（Kind 6） | `IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C` | 111 | 节点定义；`GetPin` ×2；字段 `DsBKEwvlwAl` = 名称、`HM9KEypghgm` = 描述 | 实测 |
| 节点图（Kind 9） | `cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH` | 109 | 图本体；`K61KONg4LUT` 取节点表；`GetPin` ×3；字段 `c1pKbESgr8S` = 名称 | 实测 |
| 实体实例 | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr` | 55 | 关卡实体；`t6ViSxlgnQ3` 取图绑定；字段 `WAAiS5WkxlA`=名称、`TuuiS94iUgu`=预制 ID | 实测 |
| 预制 | `nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp` | 62 | 元件/预制；字段 `PChiBEHqYMS`=名称 | 实测 |
| 单例容器 | `yT2GjCi3sEnq3X39OnMH.vSwq2Ui3deULA6AUjQxt<T>` | — | 懒加载单例（字段 `rZmi38av5uw`） | 实测 |
| 生产者/传输 | `tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh` | — | 与游戏通信；字段 `xu7i0pEkGOC` | 静态 |

**通式（已实测可行）**：`Assembly("BeyondEditor")` → `ExistingSingleton(类型名)` → 读/写字段 → 调原生方法。
所有调用必须回到 WPF dispatcher（桥接用 `Application.Current.Dispatcher.CheckAccess()` 自检）。

等级：实测（桥接代码即证据，且已有实机运行记录）。

---

## 六、编辑器原子操作名（从字符串表还原）

字符串表里保留了一批 **camelCase 操作名**。它们出现在管理器的字面量里，形态与撤销/事务步骤名一致。

**编辑对象（EditObj）与预制（Prefab）两条平行线**：

| 操作 | 推测语义 | 等级 |
|---|---|---|
| `AddInstructionGraphForEditObj` / `...ForPrefab` | 为对象/预制添加节点图 | 推断 |
| `DeleteComponentForEditObj` / `...ForPrefab` | 删除组件 | 推断 |
| `DeleteEditObj` / `DeletePrefab` | **删除对象 / 删除预制** | 推断 |
| `DeletePCGInstance` | 删除 PCG 实例 | 推断 |
| `ModifyEditObjName` / `ModifyPrefabName` | 改名 | 推断 |
| `ModifyEditobjTag` / `ModifyPrefabTag` | 改标签 | 推断 |
| `ModifyFactionForEditObj` / `...ForPrefab` | 改阵营 | 推断 |
| `ModifySuite` | 改套件 | 推断 |
| `ApplyPrefabInstanceChange` | 应用预制实例变更 | 推断 |
| `RequestPrefabInstance` | 请求预制实例 | 推断 |
| `FocusEditObj` / `FocusPrefabInstance` / `FocusCharacter` / `FocusEsp` / `FocusLight` / `FocusLocalBullet` / `FocusDropGather` / `FocusBeyondTileMap` / `FocusScreenshot` | 定位/聚焦到各类对象 | 推断 |

**资源与调试**：`DoImport`、`DoExport`、`SerializeObject`、`ImportDebugLog`、`ImportAllDebugLog`、
`DeleteDebugLog`、`EndLoadAllDebugLog`、`RefreshExistDebugLogReport`、`ImportPerformanceReport`、
`AutoTestClearCache`、`OpenResourceExplorerMainWithTag`、`PlayMusic`、`PlaySoundEffect`、`JumpCombatSetting`。

**生命周期/连接事件**：`OnLevelInit`、`OnConnectSuccess`、`OnConnectFail`、`OnInterrupted`、`OnFinished`、`OnProgress`。

**版本标记**：`GenshinBeyondWonderlandPlatform20250823`。

> **与既有记录的冲突（须如实标注）**：`PROGRESS.md` 2026-09-17 15:15 一节写"工程桥接**没有删除节点图的能力**"。
> 本轮在字符串表里发现 `DeleteEditObj` / `DeletePrefab` / `DeletePCGInstance` 等删除类操作名。
> 这**不等于**已经存在可调用的删除节点图接口——操作名是字符串，既未定位到承载它的方法，
> 也未实机调用。但它**削弱**了"编辑器根本没有删除能力"这一更强的主张，值得后续有界验证。
> 注意 `DeletePCGInstance` 明确指向 PCG 实例，`DeleteEditObj`/`DeletePrefab` 才可能覆盖节点图/预制。
> 等级：推断（仅字符串证据）。

等级：全部为**推断**——只有字符串，没有方法绑定，没有实机调用。

---

## 七、既有能力的边界（哪些代码面仍未打开）

| 缺口 | 说明 |
|---|---|
| blob 0/1/2/3 的密钥 | 4 个内嵌字符串表未解，216 处字面量因此未还原；blob 3（277,824 B）体量与 4098 条资源清单相当，价值最高 |
| 2,555 个类型反编译失败 | `_ERR_*.txt` 只有异常，未进一步处理 |
| VM 虚拟化方法体 | 密钥恢复用的常量折叠只做了 `instruction 1956–4037` 一段，未做全量 |
| 操作名 → 方法绑定 | 上述 camelCase 操作名尚未定位到具体混淆方法 |
| 类别元组语义 | 节点 `category` 元组（如 `{1:10001,2:20000,3:22000,5:N}`）的字段含义未解 |
| `assets.bin` 内层条目 | 6,453 条全为加密项，密码已知 `G16F153D`，但未全量解包 |

---

## 八、可复现命令


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


全部命令**只读**：不启动编辑器与游戏、不连接其会话、不写入游戏安装目录。

`GOAL.md` 未改动。
