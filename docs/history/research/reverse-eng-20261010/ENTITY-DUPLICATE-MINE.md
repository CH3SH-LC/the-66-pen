> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #5 挖 — 有没有「复制 / 副本」这条带组件的路？（前端能不能 copy 一个实体）

**任务（#5）**：一个预制体或实体的 **COPY** 会产出一个**已经带着源对象组件**的新对象。
若编辑器能复制实体（Ctrl+C/V，或某条命令），那它**既是加组件的绕道、又是摆放工具**。
本文件核实：语料里到底有没有这条路。

**产出日期**：2026-10-10。位置：`docs/research/reverse-eng-20261010/ENTITY-DUPLICATE-MINE.md`。

**口径**：**纯离线、纯只读**。全程**未启动/未触碰游戏或编辑器、未连桥、未发任何报文、未注入、未提权、未重启 helper、未写任何存档字节、未读任何图片/PDF**。
证据三处：① `.runtime/editor-catalog/resolved/`（**12375** 个反编译 `.cs`，用 **Bash `grep -rI`**，**不是** Grep 工具——它会静默跳过 `.runtime/`）
② 三个已建库的 sqlite（`frontend.db` / `backend.db`）③ 仓内已抓的官方知识库与既有研究文档。
**本文件只读不写**，除本文件外未新增/修改任何东西。

> 三层分标（`CLAUDE.md` §一.3）：`文档写了什么` / `工具能做什么` / `真机验证过什么` 严格分开。
> 「搜不到」只写成本次检索范围内未找到（`CLAUDE.md` §一.2：已犯过五次）。
> 三态措辞：`disproved`（有正面反证）/ `not_found`（查不到）/ `undecidable`（判不了）。

---

## 0. 一句话结论

1. **「复制」在语料里存在，但复制的是「节点图的东西」（节点 / 变量 / 引脚参数 / 已注册的命令对象），不是实体。**
   编辑器反编译代码里**唯一的深拷贝机制**是 `DeepCopy` / `CopyValue`，它挂在**节点图的值/命令对象**接口 `VRaoFJiu2iHkZCSuRqqy` 上
   （`resolved/EUDFKoiutmqWbiO2NNDj.VRaoFJiu2iHkZCSuRqqy.cs:8,10`），实现体是**节点基类** `AQecZxiUFDr4Qp1mqL4Y`（`resolved/vNUv3diU6lqfwyK68vMI.AQecZxiUFDr4Qp1mqL4Y.cs:670,762`）。
   **它不会、也无法被用来克隆一个关卡实体的组件列表。**
2. **实体侧的「复制实体数据 / 粘贴实体数据 / 阵列生成（批量创建副本）」在官方文档里确实存在**，
   而且**按它自己的契约会搬运组件**（「除名称、GUID、归属页签外的**所有数据**」）——
   但**在 12375 个反编译类型里 0 代码落点**（详见 §1.5），也**不在任何一张命令表里**（§2）。
3. **判决**：**当前不可用**（`not_found`，不是 `disproved`）。我们**没有任何可调用的复制/副本入口**；
   唯一有代码的复制是节点图复制，**它带的是节点参数、不是实体组件**，因此**不构成加组件的绕道**。

---

## 1. 语料检索 —— copy / duplicate / paste / clone 的全部落点

### 1.1 检索命令与范围


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

**命中词元分布**（`grep -oiE … | sort | uniq -c`）：`DeepCopy` 75 · `CopyValue` 49 · `deepcopy` 14（字符串）· `copyvalue` 1 · `CopyList` 1。
**`CopyBag` / `Duplicate` / `OnNodeCopy` / `NodeCopy` / `CopyNode` / `CmdCopy` / `CmdPaste` / `PasteValue` /
`CopyComponent` / `DuplicateEntity` / `DuplicateEditObj` / `CloneEntity` / `CopyEditObj` / `CopyPrefab`：本语料 0 命中。
`MemberwiseClone` / `ICloneable` 亦 **0 文件命中**（连框架浅克隆路径都没有）。**

> ⚠️ 边界：`Clone` 单词在 2034 个文件里命中，本次抽检所见**均为 protobuf/框架生成的 `::Clone` 方法引用**
> （如 `resolved/a1hh3LilQ6iw7tDFGlS.w2XDm7i1nlcKaI7iLSr.cs:142` 的 `BKljoH0V9PSWYv8PdYY.a9p2Nh0cORBBf2gKJlK::Clone`；34728 条真实方法名里
> `Clone` 也大量落在 `System.Array` / `System.Buffer` / `ICollection` 等框架类型上），**不是编辑器命令**，已排除。
> **中文**「复制 / 粘贴 / 克隆 / 拷贝」在 `resolved/` **全部 0 命中**
> （`grep -rIl "复制|粘贴|克隆|拷贝"`，单遍 ≈100 s）。

### 1.2 唯一的深拷贝机制：**节点图的值/命令对象 copy**（这是「复制」在代码里的全部含义）

| 字面量 / 方法 | 落点 file:line | 是什么 |
|---|---|---|
| `VRaoFJiu2iHkZCSuRqqy`（接口）`DeepCopy` / `CopyValue` | `resolved/EUDFKoiutmqWbiO2NNDj.VRaoFJiu2iHkZCSuRqqy.cs:8,10` | **节点图值类型接口**（实现 `RDycu8id6Go1QlHX8Dhp`）；声明 `DeepCopy`/`CopyValue`/`SetOwner` |
| `YASnYgiRDU2UQpXUh17J`（抽象类）`DeepCopy` / `CopyValue` | `resolved/xjSFHHiRsN8n3dVt0O2b.YASnYgiRDU2UQpXUh17J.cs:86,88` | 上述接口的抽象实现（持有一个 `AQecZxiUFDr4Qp1mqL4Y` 字段） |
| `AQecZxiUFDr4Qp1mqL4Y`（节点基类）`DeepCopy` / `CopyValue` | `resolved/vNUv3diU6lqfwyK68vMI.AQecZxiUFDr4Qp1mqL4Y.cs:670,762` | **节点对象基类**的深拷贝；内部逐成员 `DeepCopy`/`CopyValue`（`:740,803`），并深拷贝 `Tag`（`:752` → `BeyondEditor.BaseUtil.Tag::DeepCopy`） |
| `BeyondEditor.BaseUtil.Tag` `DeepCopy` / `CopyValue` | `resolved/BeyondEditor.BaseUtil.Tag.cs:24,90` | 标签对象深拷贝 |
| 命令基类 `YdWfOAipIo3SrkI135dK` | `resolved/TAf0YeipzZsB9Zp1AP5N.YdWfOAipIo3SrkI135dK.cs:19,25` | **命令对象**的 `CopyValue`/`DeepCopy`——默认抛「**cmd without implement of copyvalue**」(string 67506) / 「**cmd without implement of deepcopy**」(string 67578) |
| 命令管理器 `k43jFIicEuNf3eKZVBQ8` | `resolved/N7wot0ic4JK2kY6ehCFi.k43jFIicEuNf3eKZVBQ8.cs:42,48` | `CopyValue`/`DeepCopy` 抛「**cmdmanager without implement of copy value**」(67648) / 「**cmdmanager without implement of deepcopy**」(67736)；同类实现 Redo/Undo（`:54,132`） |

**判据（为什么这是「节点图」而不是「实体」）：**
- 实现类 `AQecZxiUFDr4Qp1mqL4Y` 正是**所有节点类**的基类——
  例如节点类 `resolved/phqRksKA42OGG8FqQal1.d66G4GKAEQrt0cSAMXrC.cs:10` 写的是 `… : AQecZxiUFDr4Qp1mqL4Y`。**它不是实体类型。**
- `CopyValue`/`DeepCopy` 同时挂在**命令基类**（`YdWfOAipIo3SrkI135dK`，含 `Undo()`/`Recycle()`）与**命令管理器**上 ⇒ 这是**编辑器撤销/重做栈里的命令复制**，不是场景实体复制。
- 语料里唯一带「Copy」的命令语义字符串是 **`deserialize faild : PinCopyList item is null`**（`resolved/mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26065`）——
  **`PinCopyList` = 节点引脚拷贝表**；即复制对象是**节点/引脚**。
- **旁证（桥已经在这么用）**：桥自己的修复 op `repair-gameloop-classic-teleport`
  反射调用**节点**的 `DeepCopy` 备份一个节点、再用**引脚值**的 `CopyValue` 逐值还原
  （`tools/editor-bridge/Adapter/ClassicTeleportRepair.cs:73,92`）——
  即这套「复制」被实际用来**备份/还原节点参数**，**不是**用来复制实体。这从工程侧印证了它的层级。

### 1.3 节点图右键菜单里的「复制 / 节点复制 / 变量复制 / 粘贴」

这些是 `UI_BEYOND_ASSIST_EDITOR_*`（节点图/蓝图编辑器）的**右键菜单项注册**，**有代码落点**：

| 字面量 | 落点 file:line | 说明 |
|---|---|---|
| `UI_BEYOND_ASSIST_EDITOR_NODE_DUPLICATE`（「复制」节点） | `resolved/DHH8kdu9aeMtSh4JBBpD.bNlSoNu95jI7CWfQ4yiK.cs:1680`；`resolved/kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0.cs:1534` | 右键菜单第 6 项；处理器 `NNwa8GK28oPifmneADs0::MUVK2oiWOKs`（`:1560`）→ 转派到命令宿主 `VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf::dJPKBJM21c8` |
| `UI_BEYOND_ASSIST_EDITOR_SIGNAL_BASIC_COPY` / `_PASTE` | `resolved/Eo2idfu6bW7v3L7GKYEH.tNDJftu6OMefXggAXUWC.cs:111,93`；`resolved/FWwicLu6XKhUOb5KPO7l.llVg73u6QWQI2MqDVG80.cs:89,109`；`resolved/jLcr3BuNeTxPm9wBBhaL.fZCZQWuNyKqyX3yEp4mc.cs:246,247`；`resolved/q7tWe6uUkZXiHRd065Wy.EbkJFGuUecQJoYFqA56N.cs:161,111` | 「信号数据」复制/粘贴菜单项 |
| `UI_BEYOND_ASSIST_EDITOR_BP_VAR_DUPLICATE` / `_PASTE`（复制/粘贴变量） | `resolved/JNCTIKu6yZnbV9qIiIEs.iBdOQ0u6wndZb3fnbI5Z.cs:270,233` | 蓝图变量复制/粘贴 |
| `UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_COPY_BP_ID`（复制节点图 ID） | `resolved/kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0.cs:1221` | 右键菜单第 14 项 |
| `UI_BEYOND_ASSIST_EDITOR_SIGNAL_DATA_COPY_SUCCESSFUL`（复制信号数据成功） | `resolved/jkeH24uRQHNXdnqxy26G.Fk16xvuRWXmOs5frcF8H.cs:1744` | 提示 |
| `UI_BEYOND_EDITOR_WPF_HISTORY_PASTE`（粘贴·历史面板） | `resolved/cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH.cs:209` | 历史/记录面板的粘贴 |
| `OnNodePaste failed : other is null` | `resolved/phqRksKA42OGG8FqQal1.d66G4GKAEQrt0cSAMXrC.cs:37` | 节点粘贴事件参数基类（`B40KAv9eq3u`）的失败日志 |
| `System.Windows.Forms.Clipboard::SetText` | `resolved/kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0.cs:1658` | **全语料唯一**的剪贴板调用：把**一个 uint（ID）** 转成字符串 `SetText` 到系统剪贴板（即「复制 ID」）；**不复制任何对象数据** |

⇒ **`resolved/` 里所有「复制」都指向节点图（节点 / 引脚 / 变量 / 信号 / ID），没有一条指向实体。**

### 1.4 与实体无关的「文件/资源 copy」字符串（排除项）

`string-table.json` 里有 `copy failed : can't find parent folder ` / `copy failed : invalid file ` /
`can't copy value ` / `invalid node config copy : can't find pin ` / `node copy param value failed : different config ` ——
**全是资源文件或节点配置**的校验错误串，**不是实体复制命令**。

### 1.5 实体侧「复制」字面量：**存在，但 0 代码落点**（这是本任务最关键的一条）

实体侧复制的 UI 文案**确实在编辑器资源里**，但**在 12375 个反编译类型里 0 命中**（`grep -rIl` 全为 0）：
`PROTOTYPE` / `CREATCOPY` / `COPYENTITY` / `PASTEENTITY` / `VFXEDITOR` 在 `resolved/` **0 文件命中**
（单遍 `grep -rInE "(PROTOTYPE|CREATCOPY|COPYENTITY|PASTEENTITY|VFXEDITOR|EDITORTOOL)"` 仅 3 行，且都是无关的 `TYPE_*VFXEDITOR` 类型名）。

这些字面量**只存在于数据文件**（`index.jsonl` 的全部 4098 条资源都来自同一根
`C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\Resource\…`）：

| UI 键 | 中文 | 来源 file | 代码落点 |
|---|---|---|---|
| `UI_BEYOND_EDITOR_PROTOTYPE_EDITORTOOL_COPYENTITYDATA` | **复制实体数据** | `decoded/TextMap__CHS__17720714722766726369.mihoyobin.json`（`textmap-chs.json` 键 hash 2941235960） | **无**（`frontend.db`→`ui_text.has_code=0`） |
| `UI_BEYOND_EDITOR_PROTOTYPE_EDITORTOOL_PASTEENTITYDATA` | **粘贴实体数据** | 同上（hash 1340263368） | **无**（`has_code=0`） |
| `UI_BEYOND_EDITOR_PROTOTYPE_EDITORTOOL_COPY` / `_PASTE` | 复制 / 粘贴 | 同上（3022585712 / 2622214792） | **无**（`has_code=0`） |
| `UI_BEYOND_EDITOR_PROTOTYPE_ARRAY_*`（17 条） | 阵列 / 网格阵列 / 环形阵列 / 确认创建 … | 同上 | **无**（`has_code=0`） |
| `BEYOND_EDITOR_SHORTCUT_KEY_TOOL_CREATCOPY` | **创建副本** | `decoded/Config__JsonConfig__ShortCutKey__1074106604405081892.mihoyobin.json`；`textmap-chs.json` hash 3742249623 | **无**（`shortcut` 表 `code_types:[]`，`has_code=0`） |
| `UI_BEYOND_EDITOR_PROTOTYPE_TIPS_OVERLIMITS` | 创建失败，创建的内容不可超过100个 | 同上 | **无** |

对比：**同一份 TextMap 里**节点图的复制文案（`UI_BEYOND_ASSIST_EDITOR_NODE_DUPLICATE` 等）**有代码落点**（§1.3）。
⇒ 不是「TextMap 都不进代码」，而是**实体侧那几条确实没有进反编译代码**。

> **诚实的盲区声明**：`resolved/` 是 `BeyondEditor.dll` 的**反编译产物**，字符串取自**已还原的字符串表**；
> 「0 命中」只说明**该字面量不在已还原语料里**，**不能**推出「编辑器没有这个功能」
> （`docs/research/beyondeditor-frontend/07-能力边界与缺口.md:110-122` 记过 555 条界面文本无代码落点这一同类现象）。
> 实体侧复制**很可能是**在**未展开的字符串 blob**、或**对端（游戏进程，IL2CPP 加密）**实现的——见 §2/§5。

---

## 2. 命令表 / 操作表 / 真实方法名 —— **没有一条 copy 路由**

| 表 | 全表行数 | 有没有 copy/paste/duplicate/clone | 证据 |
|---|---:|---|---|
| 后端 `backend.db` → `command_route` | **38** | **没有**。38 行的命令名逐行核过：Add*/Apply*/Delete*/Focus*/Jump*/Modify*/Request*/Serialize*/DoExport*/DoImport*/Import*/Play*/Refresh*/EndLoad*（`docs/research/beyondeditor-backend/db/backend.db`） | 逐行 `SELECT *` |
| 前端 `frontend.db` → `operation` | **44** | **没有**。44 条操作名＝AddInstructionGraphForEditObj / Delete* / Do* / Focus* / Get* / Import* / Modify* / Play* / Request* / SerializeObject / SetFocus / ShowToolTipWhenTrimmed | `docs/research/beyondeditor-frontend/db/frontend.db` |
| 前端 `frontend.db` → `shortcut` | **62** | **没有。** 62 条（含 `…TOOL_CREATCOPY`「创建副本」）**全部** `keys=NULL / marker=NULL / code_types=[]`——**有键名无绑定、无代码落点** | 同上 |
| 代理映射 `proxy-map-full.json`（**34728** 条「槽位→真实方法名」） | **34728** | **没有实体 copy 方法。** 强行匹配 `Duplicate|Paste|Replicate|CopyValue|DeepCopy|CopyEntity|CopyPrefab|CopyEditObj|CopyNode|CopyBag|CopyItem` 后**去重只剩 7 条**，**全部落在节点图值层级**：`AQecZxiUFDr4Qp1mqL4Y::DeepCopy/CopyValue`、`YASnYgiRDU2UQpXUh17J::DeepCopy/CopyValue`、`VRaoFJiu2iHkZCSuRqqy::DeepCopy/CopyValue`、`BeyondEditor.BaseUtil.Tag::DeepCopy`。**无 `CopyEntity` / `Duplicate` / `Paste` 类方法。** | `.runtime/editor-catalog/proxy-map-full.json` |
| 桥 op 白名单 `tools/editor-bridge/call-bridge.ps1` | （`Operation` ValidateSet，即 `CLAUDE.md:77` 所指的那批 op） | **没有。** 逐项检索 `Operation` 白名单，**0 个** op 名含 copy/paste/dup/clone | `tools/editor-bridge/call-bridge.ps1:1` |

**⇒ 五张表（后端命令路由 / 前端操作表 / 前端快捷键表 / 编辑器真实方法名 / 桥 op）在「实体复制」上完全一致：都没有。**

---

## 3. 「复制」这个词在产品里到底指什么 —— 官方文档的契约

实体侧复制**确实是被官方文档写进产品的**（这也解释了 §1.5 的字面量为何存在）。两条官方章节（仓内已抓）：

### 3.1 「数据复制粘贴」— `docs/official-docs/chapters/mh6fj30p2cmo.json`

- **入口/操作**（逐字）：「**选择希望复制的实体，点击复制实体数据**」→「**选择希望粘贴的实体，点击粘贴实体数据，替换完成**」。
- **它复制什么**（逐字）：「**复制实体内数据加入剪贴板，后续可粘贴至其他同类型实体，替换目标的数据**。」
- **替换范围**（逐字，本任务最硬的一条）：粘贴时「**除名称、GUID（标识码）、归属页签外的所有数据**」被整体替换。
  即**组件的配置属于「功能数据」，会被搬运到目标实体上**。
- **最硬的契约**（逐字）：「**数据替换后标识码不发生变更，不影响节点图逻辑的引用，仅替换功能数据**」。
- **性质**：这是**「写覆盖另一实体」**（paste→replace），**不是「新建一个副本」**；剪贴板是编辑器自带的**独立剪贴板，仅最大储存一份**。

### 3.2 「编辑工具」— `docs/official-docs/chapters/mhmegu0f0cso.json`

- 自述：「编辑工具是一组辅助编辑功能的集合，包括包围盒显示、**阵列生成**、**对称编辑**、3D备注等」；
  另含「六、模型数据复制粘贴」。
- **阵列生成**（逐字）：「支持通过两种方式（**网格阵列、环形阵列**）**快速批量创建副本**。」——**这才是「批量复制出新实体」的那条**。
  适用对象三项逐字：**物件实体 / 造物实体 / 掉落物实体**。入口逐字：「**选中物件 → 右键菜单 → 阵列**」，用【确认创建】落成。

### 3.3 仓内字典对它们的登记

`frontend.db` → `feature` 表已把这两件事登记为**编辑工具**，但状态一律 `reachable='unknown'`：

| id | slug | 名称 | reachable |
|---:|---|---|---|
| 51 | `prototype-symmetry` | 对称工具（点/轴/面对称，「保留原物件」） | unknown |
| 52 | `prototype-array` | 阵列工具（网格/环形，「**复制物件**」，有确认创建） | unknown |
| 55 | `prototype-edit-tools` | 原型编辑工具（**变换 / 生成 / 复制实体数据 / 粘贴实体数据**），「一次性不超过 100 个」 | unknown |

（`feature` 表 id 51-55 与 `feature_evidence`→`evidence` 84-88 只指向 TextMap 的 `UI_BEYOND_EDITOR_PROTOTYPE_*` 键串——**没有代码证据**，故 `reachable='unknown'`。）
`docs/research/beyondeditor-frontend/02-界面功能面/01a-界面文本清单-UI层/04-编辑器侧工具-ESP.md:202-291` 把这一整组标为**代码落点＝—**。

---

## 4. `entity.create` 已经带组件（对照，避免重复劳动）

本任务的前提是「copy 能带组件」。**但 `entity.create` 这条路本来就带组件**——所以「带组件」本身不稀奇：
`create` **一个组件字段都不送**（`tools/game-executor/native/scene_calls.cpp:46-47`，`optional_data` 恒 `nullptr`），
**落盘实体却自带整套组件**，**组件集随 `template_id` 走**（同关卡 4 种模板 → 9 / 14 / 20 / 31 个组件，`ENTITY-CREATE-FIELDS.md` §4.4）。

⇒ 复制路若能用，**唯一增量**是「把某个**已带目标组件**的实体的组件集，搬到另一个实体 / 复制出更多份」——
但前提仍是**你先得有一个带该组件的实体**（而 M1 要的「碰撞触发器」组件，编辑器命令面**没有 Add 落点**，见 `CLAUDE.md` §六(a)）。

---

## 5. 判决

**(1) 有没有一条「复制实体」的路？**

**产品里有（官方文档两条：阵列生成批量创建副本 / 复制·粘贴实体数据），但我们这一侧没有可调用入口。**
- 五张入口全空：后端 `command_route`(38)、前端 `operation`(44)、前端 `shortcut`(62)、代理映射真实方法名(34728)、桥 op 白名单 —— **§2**。
- 实体侧复制的 UI 字面量（复制实体数据 / 创建副本 / 阵列…）**在 12375 个反编译类型里 0 代码落点** —— **§1.5**。
- 状态：**`not_found`**（存在可能，只是没定位到）——**不是 `disproved`**。
  正当的「存在」理由：编辑器字面量加密/折叠（`CLAUDE.md` §一.1、`07-能力边界与缺口.md` §六），且**实体编辑大概率在对端（游戏进程）执行**，
  而 `beyondEditObjService` 的 7 个服务名与命令名都**不在磁盘上**（`backend.db`→`service_route` 逐行记为「明文与哈希都不在磁盘」）。

**(2) 有代码的那条「复制」能不能当加组件的绕道？**

**不能。** 语料里唯一有实现的 `DeepCopy`/`CopyValue` 是**节点图的值/命令对象**复制
（接口 `resolved/EUDFKoiutmqWbiO2NNDj.VRaoFJiu2iHkZCSuRqqy.cs:8,10`；实现 `resolved/vNUv3diU6lqfwyK68vMI.AQecZxiUFDr4Qp1mqL4Y.cs:670,762`），
复制对象是**节点 / 引脚 / 变量 / 信号 / 标签**（`PinCopyList`，`resolved/mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26065`），
**克隆的是节点参数，不是实体组件列表**。把它接到实体上**没有证据、也没有接口**。

**(3) 若将来要做，正确姿势是什么（写给下一会话）**

- **不要**去挖「实体 Ctrl+C / CopyEditObj 命令」——命令面与真实方法名表**两面都空**，它不在命令层。
- 要碰它，只有两条：「**UI 驱动**」（按官方逐字文案定位菜单项：`复制实体数据`/`粘贴实体数据`/`阵列`，而**不是**裸词「复制」——
  见 `docs/official-docs/SWEEP-QUOTED-NAMES.json:1398` 的「写覆盖合约」提示），或**继续逆向对端（游戏进程）的实体编辑实现**。
  两者都**不是**桥能做的（桥只做节点图）。
- 在任何一步**实机动作前**，都要先按 `CLAUDE.md` §四读当次回执、确认当前关卡（关卡 id 是存档的函数）。

---

## 6. 证据索引（本次 checkout / 本次语料实测）

| 论断 | 证据 |
|---|---|
| 唯一深拷贝机制是节点图值/命令对象 | `resolved/EUDFKoiutmqWbiO2NNDj.VRaoFJiu2iHkZCSuRqqy.cs:8,10`；`resolved/xjSFHHiRsN8n3dVt0O2b.YASnYgiRDU2UQpXUh17J.cs:86,88`；`resolved/vNUv3diU6lqfwyK68vMI.AQecZxiUFDr4Qp1mqL4Y.cs:670,762`；`resolved/BeyondEditor.BaseUtil.Tag.cs:24,90` |
| 节点类是 `AQecZxiUFDr4Qp1mqL4Y` 子类 | `resolved/phqRksKA42OGG8FqQal1.d66G4GKAEQrt0cSAMXrC.cs:10` |
| 命令复制默认未实现（undo/redo 栈语义） | `resolved/TAf0YeipzZsB9Zp1AP5N.YdWfOAipIo3SrkI135dK.cs:19,25`；`resolved/N7wot0ic4JK2kY6ehCFi.k43jFIicEuNf3eKZVBQ8.cs:42,48,54,132` |
| 复制对象是节点/引脚 | `resolved/mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26065`（`PinCopyList`） |
| 节点图复制菜单项（有代码） | `resolved/DHH8kdu9aeMtSh4JBBpD.bNlSoNu95jI7CWfQ4yiK.cs:1680`；`resolved/kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0.cs:1221,1534,1560` |
| 信号/变量复制粘贴（有代码） | `resolved/JNCTIKu6yZnbV9qIiIEs.iBdOQ0u6wndZb3fnbI5Z.cs:233,270`；`resolved/Eo2idfu6bW7v3L7GKYEH.tNDJftu6OMefXggAXUWC.cs:93,111` |
| 全语料唯一剪贴板调用＝复制 ID 文本 | `resolved/kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0.cs:1658` |
| 节点粘贴基类 | `resolved/phqRksKA42OGG8FqQal1.d66G4GKAEQrt0cSAMXrC.cs:37` |
| 实体侧复制字面量 0 代码落点 | `resolved/` 全量 `grep PROTOTYPE/CREATCOPY/COPYENTITY/PASTEENTITY` = 0 文件；`frontend.db`→`ui_text` 对应行 `has_code=0`；`04-编辑器侧工具-ESP.md:202-291` 标「代码落点 —」 |
| TextMap/ShortCutKey 资源来源路径 | `decoded/TextMap__CHS__17720714722766726369.mihoyobin.json`（`path=…\BeyondAssistEditor\Resource\Json\TextMap\CHS\…`）；`decoded/Config__JsonConfig__ShortCutKey__1074106604405081892.mihoyobin.json` |
| 后端 38 行无 copy 路由 | `SELECT * FROM command_route`（`docs/research/beyondeditor-backend/db/backend.db`，实测 38 行） |
| 前端 44 行无 copy 操作 | `SELECT * FROM operation`（`docs/research/beyondeditor-frontend/db/frontend.db`，实测 44 行） |
| 前端 62 条 shortcut 全无绑定/无落点 | `SELECT * FROM shortcut`（同上，`keys`/`marker` 全 NULL，`code_types` 全 `[]`） |
| 真实方法名（34728 条）无实体 copy | `.runtime/editor-catalog/proxy-map-full.json`（强匹配去重后仅 7 条，全在节点图值层） |
| 桥 op 白名单无 copy | `tools/editor-bridge/call-bridge.ps1:1`（`Operation` ValidateSet 逐项检索，0 个含 copy/paste/dup/clone） |
| 桥用节点 `DeepCopy`/`CopyValue` 做节点参数备份/还原（旁证层级） | `tools/editor-bridge/Adapter/ClassicTeleportRepair.cs:73,92` |
| 官方：复制实体数据 / 替换范围 / ID 不变 | `docs/official-docs/chapters/mh6fj30p2cmo.json` |
| 官方：阵列生成＝批量创建副本；适用实体三类 | `docs/official-docs/chapters/mhmegu0f0cso.json` |
| 仓内 feature 登记（reachable=unknown） | `frontend.db`→`feature`(51,52,55) / `feature_evidence`(51-55↔84-88) |
| `create` 自带组件、随 template 变 | `docs/research/reverse-eng-20261010/ENTITY-CREATE-FIELDS.md` §4.3-4.4；`tools/game-executor/native/scene_calls.cpp:46-47` |
| 组件 ADD 不存在（不动摇） | `CLAUDE.md:83-89`；`docs/research/reverse-eng-20261010/COMPONENT-WRITER-MINE.md` |
| 555 条界面文本无代码落点的「搜不到≠不存在」纪律 | `docs/research/beyondeditor-frontend/07-能力边界与缺口.md:110-122` |
| 服务名/命令名不在磁盘（对端实现） | `docs/research/beyondeditor-backend/db/backend.db`→`service_route`（逐行 `string_only/inferred`） |

---

*本文件由 2026-10-10 会话从仓内已建库的 sqlite、`.runtime/editor-catalog/resolved/`（Bash `grep -rI`，非 Grep 工具）
与 `docs/official-docs/` 只读整理；**未实现、未连线、未连桥、未触碰游戏/编辑器、未写任何存档字节**。
所有行号为本次 checkout 实测；负面结论均写明检索范围与盲区。*
