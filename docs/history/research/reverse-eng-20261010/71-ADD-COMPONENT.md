> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #4 再研 — 7.1 CODE 里到底有没有「加组件」这条路（add-component in the 7.1 corpus）

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。未连桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程（helper 未动、未请求 UAC）、未写存档、未读任何图片或 PDF。所有产物写在工程内（本文件）。
**证据来源**：仓内 7.1 反编译语料 `.runtime/verification/update-repair-20260925/`：
- `adapter-port/decomp-7.1/`（15,639 `.cs`，其中 2,684 个 `_ERR_`）——**原始 7.1 反编译**（字符串**加密**）
- `strings/annotated-7.1/`（12,955 `.cs`，= 15,639 − 2,684 个成功解析者）——**同一份 7.1 代码的「字符串解出」版**（仅把加密字面量替换为明文）
对照：7.0 语料 `.runtime/editor-catalog/resolved/`（12,375 `.cs`）+ 7.1 字符串表 `.runtime/scratch/editor71-string-table.json`（2,985 条）+ TextMap `docs/research/beyondeditor-frontend/db/raw/textmap.json`。

> 三层分开：**7.0 文档写了什么** / **7.1 CODE 真是什么** / **两份字符串表证了什么**。本文件全部静态结论，无一条真机。

---

## 0. 一句话结论

**NO —— 7.1 的 CODE 里没有任何「加组件」路径，与 7.0 逐行同构。**

组件面板这一支的 VM 在 7.1 里仍是**两个按钮**（`vmBtnShow` + `vmBtnDelete`），`vmBtnShow` 的 handler **仍然是空实现 `{}`**，`vmBtnDelete` 的 handler **仍然是那三条命令**（`RequestPrefabInstance` / `DeleteComponentForPrefab` / `DeleteComponentForEditObj`）。**7.1 没有加第三个按钮，也没有把那个空按钮填上。** 命令字面量集合 7.0 与 7.1 完全一致（组件命令仍只有两条，都是删）。

**⚠️ 关键方法学修正（本轮最重要的一条操作事实）**：任务的探测管（「把 KEY 名当字面量 grep 7.1 语料」）**对 `decomp-7.1/` 会静默失败**——因为 **7.1 反编译里编辑器字符串是加密的**（以 `OfHnbKPAfwDjrwrhrnHS.vamPAss8BQY(<常量1 ^ 常量2>, …)` 形式存在），`grep "DeleteComponentForEditObj" decomp-7.1/` = **0 命中（假阴性）**。必须改用 **`strings/annotated-7.1/`**（字符串解出版）才看得到字面量。§1 给出量化证据。

---

## 1. 为什么直接在 `decomp-7.1/` 里 grep 字面量会骗人

| 探测 | 命中 |
|---|---|
| `grep -rl "DeleteComponentForEditObj" decomp-7.1/` | **0** |
| `grep -rl "DeleteComponentForEditObj" strings/annotated-7.1/` | **1**（`HAZWycj0oGZJFaTJo8c9.XVcbBbj0Pal6i9RiXENV.cs`） |
| `grep -rl '"DeleteComponentForEditObj"' 7.0 resolved/` | **1**（`pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs`） |
| `decomp-7.1/` 里含**普通明文字符串**（`"[A-Za-z][A-Za-z0-9_]{3,}"`）的文件数 | **15 / 15,639**（且全是框架串：`TYPE_UINT64`、`PresentationBuildTasks`、`SYNTAX_PROTO3` …） |
| 7.0 `resolved/` 里含普通明文字符串的文件数 | **617 / 12,375**（含全部 UI/命令字面量） |

**⇒ `decomp-7.1/` 的 15 个明文文件里根本没有编辑器自己的字符串**：7.1 反编译保留了 .NET Reactor 的字符串加密调用点，字面量以「两常量异或」入参藏在 `OfHnbKPA...vamPAss8BQY(...)` 里。`strings/annotated-7.1/` 是同一份代码的**字符串解出**版（行号与 `decomp-7.1/` **逐一对应**），是本任务唯一可用的字面量面。

（这解释了任务背景里「NOBODY has searched that 7.1 corpus for the component-add」为什么之前会「搜不到」——语料选错了一份。）

---

## 2. 起点文件：7.1 的**组件行 VM**，逐行（任务第 1、2 步）

**组件行的按钮 VM，7.1 = `HAZWycj0oGZJFaTJo8c9.XVcbBbj0Pal6i9RiXENV`（`:14` 继承 `sjnB6Bj0OBEKVSS4H0eZ`）。它是 7.0 `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW` 的 1:1 对应物。**

> 术语修正（沿用 `ADD-COMPONENT-TRACE.md` §2/§10.1）：这是**一行组件**的 VM，不是整块「组件面板」；但它正是全部组件按钮和命令的所在。

四个组件字面量在 7.1 语料的**全部命中**（任务第 1 步要求逐个 file:line）：

| 字面量 | 7.1 命中 | 7.0 命中 |
|---|---|---|
| `DeleteComponentForEditObj` | `strings/annotated-7.1/HAZWycj0oGZJFaTJo8c9.XVcbBbj0Pal6i9RiXENV.cs:163` | `resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107` |
| `DeleteComponentForPrefab` | 同上文件 `:124` | 同上文件 `:152` |
| `ComponentForEdit` | **无独立命中**（只是 `DeleteComponentForEditObj` 的子串） | 同左 |
| `ComponentForPrefab` | **无独立命中**（只是 `DeleteComponentForPrefab` 的子串） | 同左 |

**那个 VM 的全部按钮 + handler + 命令（7.1，file:line 均指 `strings/annotated-7.1/…XVcbBbj0Pal6i9RiXENV.cs`；括号内为 `decomp-7.1/` 同行的加密形态）**：

| 成员 | file:line | 行为 |
|---|---|---|
| `vmBtnShow`（属性） | `:26-36` | getter 返回 `grDj0iECmfA` |
| `vmBtnDelete`（属性） | `:38-48` | getter 返回 `MW7j0tH5G22` |
| 构造器绑定 | `:65` / `:68` | `MW7j0tH5G22 = new …(this, Kv2j07tkCpw)`；`grDj0iECmfA = new …(this, jY3j0qgcejY)` |
| `jY3j0qgcejY()` | `:91-93` | **空实现 `{}`** —— 这就是 `vmBtnShow` 的 handler |
| `Kv2j07tkCpw()` | `:95-171` | 删除派发器（下面三条命令） |
| 派发 `"RequestPrefabInstance"` | `:123`（`decomp-7.1` 同行作 `OfHnbKPAfwDjrwrhrnHS.vamPAss8BQY(-1556460351 ^ -1556372383, …)`） | 宿主 = prefab 视图（`X7sXNnbtoAB == 7`） |
| 派发 `"DeleteComponentForPrefab"` | `:124`（`decomp-7.1` 同行 `…vamPAss8BQY(-62477419 ^ -62615281, …)`） | prefab 分支 |
| 派发 `"DeleteComponentForEditObj"` | `:163`（`decomp-7.1` 同行 `…vamPAss8BQY(-300504669 ^ -300641427, …)`） | 宿主 = 实体（`o6MMsvXduEaZkjEZB6yx`） |
| 工厂 `jcrj0MbyAWC(vm,obj,uint)` | `:79-89` | 行标题 = `((QhNByxZONrdCQv6vIMYe)componentId).ToString()` |
| 委托类型 | `strings/annotated-7.1/gQ7HWKA9blSrX3H3g78q.cs:5` | `delegate XVcbBbj0Pal6i9RiXENV f(tom…, LWt2TSXNGEdQWP0CHtgr, uint)` |

**这三条命令字面量是该文件及其整族的全部命令调用**，形状与 7.0 完全一致：
`p3RFThteEkrUwNW48plh.vamPAss8BQY(producer, service, "命令名", null, List<Param>)`，args = `[uint(entityId), uint(componentId)]`。**这一行里没有 Add。**（7.0 对应：`BrjMRrl2xRXv5aqZQkDJ.xyVYfsr3qg0(...)`，`:107/:127/:152`。）

### 2.1 邻域（siblings）——7.1 逐个复读

| 7.1 文件 | 角色 | 按钮 / 命令字面量 |
|---|---|---|
| `…HAZWycj0oGZJFaTJo8c9.XVcbBbj0Pal6i9RiXENV.cs` | 组件**行** VM | 仅 `vmBtnShow`(空) / `vmBtnDelete`(三命令) |
| `…gQ7HWKA9blSrX3H3g78q.cs` | 行工厂**委托包装** | 无 |
| `…aYdaApjcmEZqempaIQCY.USyDInjcRS3p1gvJBUBU.cs` | 列表 VM（`YlJitG20qEt` 族） | **零按钮、零字面量**（`grep '"[^"]{4,}"'` = 空） |
| `…SQtAcKjcoqUQUVuC4618.fMFC0UjcP1EEI1fM7VB3.cs` | 列表 VM（`WlJiSPfnM3R` 族） | **零按钮、零字面量** |
| 7.0 对应：`…LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs` / `…yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs` / `…wBtNTpLgF5ypQBEO16Cw.cs` | 同族 | 同：无按钮、无命令 |

**⇒ 7.1 的整个组件-VM 族（行 + 列表 + 委托）里没有任何 add 按钮，也没有任何 add 命令。**

### 2.2 第二块「vmBtnShow / vmBtnDelete」面板（viewType 203）

7.1 另有一个类同时带这两个按钮属性：`pcCfnqj0NxpryeeyZ6aZ.Y1FgNJj0nBlSOrrtFc03`（`:13`），`viewType => 203`（`:47`）。
- 它**不含任何 Component 字面量，也不派发任何命令**（`Pl2j04mDC4v` 只做 21000/21001 整数的视图开关，`:127-185`；`lcSj0sAyTDO` 空，`:187-189`）。
- 7.0 里有 1:1 对应物：`resolved/qxwK0TuuxQCqjtQowIWO.R0GWViuuYuET1HOZ3jVv.cs`（`viewType => 203`，`:47`）。
⇒ 这不是组件面板（无组件字面量）；且与 7.0 同构，无 add。

---

## 3. 「第三个按钮 / 填上空的按钮」——逐条举证（任务第 3 步）

| 检查 | 7.0 | 7.1 | 结论 |
|---|---|---|---|
| 按钮属性数 | 2（`vmBtnShow`,`vmBtnDelete`） | 2（同名） | **没加第三个** |
| `vmBtnShow` handler | `etruuExZdxU()` 空 `{}`（`:89-91`） | `jY3j0qgcejY()` 空 `{}`（`:91-93`） | **空按钮仍是空的，没被填上** |
| `vmBtnDelete` handler | `s9puu4bEcx2()`（`:93-158`） | `Kv2j07tkCpw()`（`:95-171`） | 逐命令同构 |
| 派发的命令 | 3 条（Delete×2 + RequestPrefabInstance） | 3 条（同名同序） | **无新增命令** |
| 该文件全部字符串字面量 | — | `vmBtnShow`、`vmBtnDelete`、`RequestPrefabInstance`、`DeleteComponentForPrefab`、`DeleteComponentForEditObj` = **仅此 5 条** | 无 Add 字面量 |

**引用空 handler（7.1，原文）**：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

对照 7.0（`pmZ1…yn34VuuuO5tEgsICYDBW.cs`）：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**没有第三个按钮，也没有把空按钮填上**——7.1 与 7.0 在这两点上**逐字相同**。

---

## 4. 全字面量面复核（任务第 1 步加码：不靠单个起点）

对 **`strings/annotated-7.1/` 全语料**独立扫（Bash，非 Grep 工具）：

| 查询 | 7.1 命中 | 7.0 命中 |
|---|---|---|
| `AddComponent` / `CreateComponent` / `AttachComponent` / `InsertComponent` / `ComponentForAdd` / `ComponentAdd` / `AddEditObjComponent` | **各 0** | **各 0** |
| 含 `Component` 的字符串字面量（去重） | 8 条：`vmComponents`、`Template_ComponentEdit_{Editor,EditableValueList,EditableValue,EditableStruct,ComponentPanel}`、`DeleteComponentForPrefab`、`DeleteComponentForEditObj` | **逐条相同**（同 8 条） |
| `Add*` / `Create*` 字面量（去重） | `AddInstructionGraphForEditObj`、`AddInstructionGraphForPrefab` | `AddInstructionGraphForEditObj`（7.1 多的是 **`…ForPrefab`，属节点图，非组件**） |
| `Delete*` 字面量（去重） | 13 条（`BEYOND_EDITOR_SHORTCUT_KEY_TOOL_Delete`、`DeleteComponentFor*`、`DeleteDebugLog`、`DeleteEditObj`、`DeletePCGInstance`、`DeletePrefab`、`textDeleteModeOnHint`、`vmBtnDelete`、`vmBtnDeleteItem`、`vmBtnDeleteVar`、`vmBtnExitDeleteMode`、`vmDeleteButton`） | **逐条相同** |
| `vmBtn*` 属性名（去重） | 70+ 个，含 `vmBtnAdd`；**无 `vmBtnAddComponent` / `vmBtnCreateComponent`** | 同（含 `vmBtnAdd`，无组件版） |

**三个带 `vmBtnAdd` 的 7.1 类逐个人肉确认都不是组件面板**（与 7.0 同名判定，`ADD-COMPONENT-TRACE.md` §10.2 已列 7.0 侧）：
- `strings/annotated-7.1/dAIhbWQB5RWmwy3pxTo6.bfaasEQBu2mxka4h2b0I.cs`：引脚列表（`"UI_BEYOND_ASSIST_EDITOR_ADD_PINS"`、`pinList`、`showBtnAdd`）。
- `strings/annotated-7.1/lJo9sYjPGcQMDmQkgB7f.iSDTAkjPaj0VlAtseWpW.cs`：属性值 List 编辑器（`vmValueList`）。
- `strings/annotated-7.1/wxbmRmjaMTpMhNpKGTNl.SuAFfDjao3TpieCdiEeA.cs`：音效/攻击标签/下拉项（一串 `UI_BEYOND_ASSIST_EDITOR_*` + `vmComboBoxItems`）。

### 4.1 字符串表（7.1 安装版，2985 条 = 字面量全集）交叉证

`.runtime/scratch/editor71-string-table.json`（安装的 7.1 `BeyondEditor.dll` 解出的偏移字面量表）内：
- 含 `component` 的键：`DeleteComponentForEditObj`、`DeleteComponentForPrefab`、`Template_ComponentEdit_*`、`componentName`、`vmComponents` —— **只有这些**。
- 含 `Add` 的键：`AddInstructionGraphForEditObj/ForPrefab`、`UI_BEYOND_*_ADD_*`（pins/signal/variable/file/folder）、`vmBtnAdd*`、`showBtnAdd`、`textAddVarCount` —— **没有一条是「加组件」**。

### 4.2 TextMap（安装版 CHS）交叉证

`docs/research/beyondeditor-frontend/db/raw/textmap.json` 内 `component` 相关 UI 键**只有 1 条**：`UI_BEYOND_EDITOR_UI_COMPONENT_CONFIG_CURSOR_COLLISION`（光标碰撞盒）。**没有**「添加通用组件」类文案键（与 `ADD-COMPONENT-TRACE.md` §8 一致）。

### 4.3 `_ERR_` 文件的残余盲区（写明）

`decomp-7.1/` 有 **2,684 个 `_ERR_*.txt`**（反编译失败）不在 `annotated-7.1/` 里。已核：**没有任何 `_ERR_` 文件提及 `Component`**（原始加密体也不会含明文 `Component`，因为 7.1 明文稀少）。故「add 组件藏在解不出的文件里」**不成立**——它若存在，必须是字面量，而字面量在解出的 12,955 个文件 + 2,985 条字符串表里都没有。

---

## 5. 判决（任务第 4 步）

**NO。7.1 没有 7.0 所缺的 add-component 路径。**

代码级证据链（三条**同向**——注意：它们是**同一份 7.1 build** 的三种抽取视图，**不是三个独立层**，见下方「口径更正」）：
1. **7.1 CODE**：组件行 VM `HAZWycj0oGZJFaTJo8c9.XVcbBbj0Pal6i9RiXENV.cs` 与 7.0 `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs` **逐行同构**——两个按钮、`vmBtnShow` handler 仍空 `{}`（`:91-93`）、`vmBtnDelete` 仍派发 `RequestPrefabInstance`/`DeleteComponentForPrefab`/`DeleteComponentForEditObj` 三条（`:123/:124/:163`）。**没有第三个按钮，空按钮没被填。**
2. **7.1 全语料字面量**：`AddComponent`/`CreateComponent`/`Attach/Insert/ComponentForAdd` **各 0**；组件相关字面量集 = 8 条，与 7.0 **逐条相同**。
3. **7.1 安装版字符串表（2,985 条 = 字面量全集，plaintext SHA 钉死）**：组件命令仍**只有两条，都是删**；`Add*` 家族无一与组件相关。

> **口径更正（2026-10-11）**：上面三条**不是三个独立层**——它们全部取自**同一份 7.1 `BeyondEditor.dll`**
> （反编译 `.cs` / 由该 `.cs` 抽出的字面量 / 由同一 DLL 解出的字符串表），是**重复观测**。
> 「活程序集」同样**不是**第三层：它**就是这份 7.1 build**。本工程对「加组件不存在」的独立证据轴只有
> **两代构建（7.0 / 7.1）**，并带**正面控制**（已知存在的 `DeleteComponentForEditObj` 在两个 build 的命令面都可见）。
> 结论方向不变（仍是不存在），只是证据强度改为「两个 build 同向 + 正面控制」。

**⇒ M1/M4/M5 的 scene 半边，7.1 的命令面同样没有「加组件」；这份 7.1 CODE 没有带来任何新落点。**

**下一步（与 `ADD-COMPONENT-TRACE.md` §7 排第 1 一致，且本轮把「7.1 CODE 空洞」补上了）**：唯一未被证伪的落点仍是**写存档侧的实体组件记录**（`wFyeWxvUrZ4ClLJlFKGm.d5t5h9vUZHeCSba2oH5p`：`enabled` + `jaUof90C3Ncl5BAJri4x` 类型 + 配置载荷），而非桥命令。残余不确定性见 §4.3 与 `ADD-COMPONENT-TRACE.md` §10.5（XAML 内联 Click→`collection.Add(...)` 这条静态不可见路径，两 build 都同样不可见）。

---

## 6. 本次新增/触碰的文件

- **新增**：本文件 `docs/research/reverse-eng-20261010/71-ADD-COMPONENT.md`
- **未改动**任何既有文档/代码；**未连桥、未发报文、未碰游戏或编辑器、未写存档、未读任何图片或 PDF**。
- 只读引用的语料：`.runtime/verification/update-repair-20260925/{adapter-port/decomp-7.1, strings/annotated-7.1}/`、`.runtime/editor-catalog/resolved/`、`.runtime/scratch/editor71-string-table.json`、`docs/research/beyondeditor-frontend/db/raw/textmap.json`。
