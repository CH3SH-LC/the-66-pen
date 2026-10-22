> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #9 第二块拼图 —— 「建模板」在 **7.1 语料**里到底有没有（TEMPLATE CREATE, 7.1 hunt）

日期：2026-10-10。
**口径**：**纯离线、纯只读**。未连桥、未发任何 bridge/native 报文、未注入、未启动或触碰游戏/编辑器、
未重启 helper、未申请 UAC。对 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` **一个字节都没读也没写**。
未读任何图片或 PDF。**未读 `D:/games/` 下任何文件**（TextMap 的键来自 task #2 = `MENU-STRING-HOME.md` 的现解产物）。
本轮检索脚本与中间产物只落在 `.runtime/scratch/`（工程内）；本文件是本次唯一产出，未改 `tools/`、未改任何 pin、未改任何测试。

**本文件回答一个问题**（承接 `TEMPLATE-CREATE-TRACE.md` / `TEMPLATE-CREATE-VERDICT.md`，那两份的负面**全建立在 7.0 语料 + 命令表**上）：
**把「建模板」放到 7.1 的 CODE 面上重搜一遍——7.1 里有没有一条建模板的路？**

---

## 0. 一句话判决

# **No —— 7.1 没有补上这半块。**

三种抽取同向（**代码字面量层 / 字符串表层 / 服务名层**）——但见 §5 末尾「口径更正」：三者都取自**同一份 7.1 build**，是重复观测，**不是三个独立层**：

1. **代码层**：7.1 反编译语料（12,955 个类型，**2,925** 条 distinct 字面量）里，与货币 / 道具 / 背包 / 商店 /
   模板创建相关的**命令字面量一条都没有**（§2）。
2. **字符串表层**：7.1 现行 build 的**解密字符串资源**（`string-table-7.1.json`，**2,985** 条，= 该 DLL 里**全部**
   `ldstr` 字面量）里，`shop / currency / inventory / bag / mall` 为 **0**；命令名里**没有**任何 `Create*Template` /
   `CreateItem` / `CreateShopTemplate` / `NewTemplate`（§1.3）。
3. **服务名层**：7.1 全部 **13** 个服务名（`beyondEditObjService` … `wpfColEditService`）里**没有任何**
   货币 / 道具 / 背包 / 商店 / 模板服务（§2.4）。

**并且**——任务点名要查的 7.1 新增命令 `batchcreate / batchdelete / deleteSignal / modifySignal /
deleteNodeConfig / modifyNodeConfig` **没有一条是模板操作**：它们分别是**节点库（节点管理器）** 的增删改名改路径、
以及**节点配置 / 信号**的读写（§4）。

> 7.1 相对 7.0 净增的那一整块（Lua 客户端脚本子系统 + 上面那批新命令）**补的是「脚本 / 节点 / 信号」**，
> **不是「货币 / 道具 / 商店模板」**。旧负面**不被 7.1 削弱**。

---

## 1. 面板键名（任务 step 1）—— 货币 / 道具 / 商店模板面板的键 **不存在**

### 1.1 官方文案里的名字（先把「要找什么」钉死）

| 面板 / 按钮 | 官方原文（逐字） | 出处 |
|---|---|---|
| 系统菜单项 | `关卡设置、界面控件组管理、主镜头管理、试玩、多人试玩、外围系统管理、**背包与货币**和奇域礼盒管理` | `docs/official-docs/chapters/mhn4bsi5lb58.json:32` |
| 商店模板面板 | `打开系统菜单，在下图位置点击【**商店模板管理**】即可打开商店模板编辑界面` | `docs/official-docs/chapters/mhi9s7isvp50.json:50` |
| 新建按钮（道具） | `点击**新建道具**按钮，在弹窗内选择确认创建即可新建一个**道具模板**` | `docs/official-docs/chapters/mhbgx0rspbqu.json:32` |
| 新建按钮（商店） | `打开商店配置界面，点击“**新建商店模板**”即可添加并编辑模板` | `docs/official-docs/chapters/mhi9s7isvp50.json:62` |
| 新建按钮（装备） | `点击**新建道具** / 在弹出的窗口下拉【选择类型】，选择装备即可新建一个**装备模板**` | `docs/official-docs/chapters/mhkl2yin0cxo.json:30` |

「货币面板」在官方文案里没有独立页签，它是「**背包与货币**」这一项系统菜单下的货币页签；
道具是「道具页签」；商店是「**商店模板管理**」。要找的**按钮**叫「**新建道具**」「**新建商店模板**」。

### 1.2 装机 TextMap 里的键（8266 条，task #2 现解）

现解的键全量落在 `.runtime/scratch/_tm_keys_all.txt`（8,266 行；源 `…/BeyondAssistEditor/Resource/Json/TextMap/CHS/17720714722766726369.mihoyobin`，
SEE `MENU-STRING-HOME.md §1.1`）。按词搜键名：

| 词 | 命中 | 结论 |
|---|---:|---|
| `CURRENCY` / `SHOP` / `MONEY` / `MALL` / `STORE`(菜单义) | **0** | 没有货币 / 商店面板键 |
| `ITEM` | 3 | 全是 `…_CONTROL_LIST_SETTING_ITEM{SIZE,SPACE}` / `…PREVIEW_ITEMPOSITION`（UIEditor 列表控件） |
| `TEMPLATE` | **4** | 全在 `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_*`（界面控件编辑器）命名空间 |

那 **4 个 TEMPLATE 键**逐字：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**注意命名空间**：`UIEDITOR_CLIENT` = **界面控件编辑器（客户端 UI 编辑器）**，即「界面控件组管理」那一档，
指的是**界面控件模板**（UI 控件模板），**不是**游戏 B 的货币 / 道具 / 商店模板。**名字里带 TEMPLATE ≠ 货币/商店模板。**
（对照：`UI_BEYOND_EDITOR_ESP_LIGHTING_ESCNAME` = 光源管理，是系统菜单项的唯一 `ESCNAME` 键，`_tm_keys_all.txt:7462`——
用它证明「题面那 29 项系统菜单里只有极少数落进了 TextMap」。）

### 1.3 7.1 字符串表里同一问 —— 同样是 0 / 且那 4 个键**在代码里 0 引用**

`.runtime/verification/update-repair-20260925/strings/string-table-7.1.json`（2,985 条，见 §6 口径）：

- 含 `UIEDITOR_CLIENT` 的键 **48** 条，**其中没有一条**含 `TEMPLATE`（`TEMPLATE_SERVER/CLIENT/CONTROL_TEMPLATE_LIST/ADD_TEMPLATE_LIST` 四条**全部缺席**）。
- `SHOP` / `CURRENCY` / `INVENTORY` / `BAG` **0** 条。
- 键名（值）里唯一的 `Template*` 是 **WPF/XAML 模板名**：`Template_NodeGraphEditor`、`Template_ComponentEdit_*`、
  `Template_MainWindowBody` … 以及 `templateContent / templateMainWindow / givenTemplate / itemTemplate`（全是 `DataTemplate` 属性名）。
- 那 4 个出现在 TextMap 的 TEMPLATE 键，**在 7.1 代码语料里也 0 引用**（raw 与 annotated 都 0）：
  `.runtime/scratch/tc71_hits2.json` 逐条 = 0。

⇒ **结论（step 1）**：**「货币面板 / 道具面板 / 商店模板面板」的键在本机可读的三份资源里都不存在**；
TextMap 里仅存的 4 个 TEMPLATE 键属于**界面控件模板**命名空间，且**没有任何代码引用它们**。
这与 task #2 `MENU-STRING-HOME.md` 的现解结果一致（该文已证明 `背包与货币 / 商店模板管理` 在 TextMap 值里也 0）。

---

## 2. 「grep 那些键字面量」的完整结果（step 2）

### 2.1 关键前提：**7.1 的 raw 反编译是混淆态，直接 grep 必 0**

`.runtime/verification/update-repair-20260925/adapter-port/decomp-7.1/*.cs` 是 **ConfuserEx** 混淆产物：
字符串被加密成 `int ^ int` 常量（例：`OfHnbKPAfwDjrwrhrnHS.vamPAss8BQY(0x46DF9D65 ^ 0x46DEEAFF, …)`），
并叠加控制流平坦化（`switch(num2)`）与假分支（`<Module>{0501a6fa-…}` 判断）。
**直接 `grep ModifyEditObjName decomp-7.1/` = 0 命中**（本轮实测）——**这正是「7.1 语料从没人搜过」的机械原因**。

**可搜的形态在姊妹目录** `.runtime/verification/update-repair-20260925/strings/annotated-7.1/`（同样 12,955 个 `.cs`，
字符串已还原为可读字面量并附原偏移注释：`"ModifyEditObjName" /* string 77458 */`）。
**本轮全部 grep 打在 annotated-7.1 上**（Bash `grep -r`，因 Grep 工具跳过 `.runtime/`）。

### 2.2 任务点名的键 / 命令 → 逐条命中（全 0，除非另注）

| 检索字面量 | annotated-7.1 命中 | 备注 |
|---|---:|---|
| `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_TEMPLATE_SERVER` | **0** | 键在 TextMap，代码无引用 |
| `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_TEMPLATE_CLIENT` | **0** | 同上 |
| `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_TEMPLATE_LIST` | **0** | 同上 |
| `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_CONTROL_ADD_TEMPLATE_LIST` | **0** | 「ADD_TEMPLATE_LIST」最像「新建」→ 仍 0 |
| `CreateTemplate` / `createTemplate` / `NewTemplate` / `newTemplate` / `CreateShopTemplate` / `CreateItem` | **0** | 无建模板 / 建道具命令名 |
| `batchcreate` | 1 | `RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx.cs:2066` |
| `batchdelete` | **0** † | 该调用点的字面量被**表达式加密**，annotator 未能内联（见 †） |
| `deleteSignal` / `modifySignal` / `deleteNodeConfig` / `modifyNodeConfig` | 各 1 | `mtnPv7XKt2ife06AyhaF.PSy0npXKiFSuSpN6XrJ8.cs` |
| `modifyname` / `modifypath` | 2 / 1 | 同 dispatcher 文件 |

† **annotator 的一处已知缺口**：`sZGXo0LTqly`（batchdelete 的姊妹方法）那一次调用写成
`OfHnbKPAfwDjrwrhrnHS.vamPAss8BQY(--1257385385 ^ 0x4AF3386F, …)`（字符串解密表达式），
**没有被内联成可读字面量**，故 grep 为 0。**但字符串表层给了它**：`string-table-7.1.json` 里
入口 `"71110": "batchdelete"` 确实存在（`"71068": "batchcreate"` 紧随 `"71052": "create"`）。
⇒ **「命令名是否存在」以字符串表为准成立**；annotated 的漏内联只影响按字面量 grep，不影响结论。

### 2.3 **实际存在**的 NEW / CREATE 键（把「新建按钮」全集列全，供 step 3 定位）

对 annotated-7.1 建了全字面量索引（1,2955 文件 → **2,925** distinct，`tc71_literals.json`）。
其中 `UI_BEYOND*` / `BEYOND_*` 键共 **439** 条；含 `_NEW` / `_CREATE` 的**全部**如下（file:line 为键字面量出现处）：

| 键 | 文件:行 | 语义 |
|---|---|---|
| `…_DEFAULT_RIGHT_MENU_NEW_FOLDER` | `alDQGaXN6xuqGOMAqqaB.oKWD1gXNh3WjvDNoejLm.cs:1173` | 资源管理器右键「新建文件夹」 |
| `…_NODE_MANAGER_NEW_COMPOSITE_NODE` | `bdbYGlXPnjBEKi4qQ11X.hWfunLXP1LCpUbtnvrZ2.cs:7447` | 节点管理器「新建复合节点」 |
| `…_DEFAULT_RIGHT_MENU_NEW_BP` | `XTs12bjtnIIe7VCqgJoS.lmCFgRjt19Z8M8CEWyaO.cs:1245` | 右键「新建蓝图」（=节点图资产） |
| `…_DEFAULT_RIGHT_MENU_NEW_SERVER_BP` | 同上 `:1410` | 「新建服务端蓝图」 |
| `…_DEFAULT_RIGHT_MENU_NEW_FILTER_BP` | 同上 `:1381` | 「新建过滤器蓝图」 |
| `…_CLIENT_BLUEPRINT_{AVATAR_SKILL,MONSTER_SKILL,MONSTER_POSE,MONSTER_AI,CONTROL}_NEW` | 同上 `:1374/:1427/:1416/:1438/:1419` | 客户端蓝图（技能/姿势/AI/控件）新建 |
| `…_SIGNAL_ADD_NEW_SIGNAL` | `V4YT5UQPem8NWbNxpaAD.uZuJhOQPxgdZ7NY7TNkH.cs:199` | 信号面板「新建信号」 |
| `…_SIGNAL_ADD_NEW_VARIABLE` | `FQgXblQPvrIFTwFy9oxV.FC6IHKQPGygiWMpm14TZ.cs:216` | 「新建变量」 |
| `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_NEW_CLIENT_SCRIPT` | `XTs12bjtnIIe7VCqgJoS.lmCFgRjt19Z8M8CEWyaO.cs:1227` | 新建 Lua 客户端脚本 |
| `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_NEW_SCRIPT_MAPPING` | 同上 `:1034` | 新建脚本映射 |
| `…_UIEDITOR_CLIENT_SCRIPT_CREATE_FILE_TITLE` / `…_TIP_CREATE_FAIL` | `l21m0yji99dK3WjkQSac.UXE3H3jiVOGaQR1mNlEU.cs:262 / :253` | 脚本建文件 |
| `…_BLUEPRINT_SAVE_AS_NEW_NAME` / `_NEW_TAB` | `WSp63RQtHm8wOvQL4J6V.gELXE3QtrMLgwoFWIa07.cs:575 / :543` | 蓝图另存 |
| `…_WPF_HISTORY_{NEW,NODE_NEW,LINK_NEW,CV_NEW,COMPOUNDNODES_NEW,MENTION_NEW}` | `E8xv5pXu77T6046o5sVM.vUK4LLXuq7BbA0L017eJ.cs:182/153/169/181/193/213` | **撤销栈历史项**（不是按钮） |

**没有任何一条**是货币 / 道具 / 背包 / 商店模板的「新建」。**「新建」按钮的全体只服务三类对象：文件夹、蓝图/节点、
信号/变量、脚本。** 这就是 step 3 要读的 handler 范围。

### 2.4 服务名层（旁证，第十三次独立核对）

`fSX5SsLhejTgt1FiF9Mk.aJl3EGLhx8dONChlfm3o.cs` 逐字节面给出 7.1 全部服务名（`:19` 起），
全工程字面量去重后共 **13** 个：
`beyondEditObjService / beyondEffectService / beyondExportService / beyondRoleStatusService / beyondAudioService /
beyondInstructionGraphService / beyondPCGInstanceService / beyondClientScriptService / wpfAudioService /
wpfApplicationService / wpfInstructionGraphService / wpfClientScriptService / wpfColEditService`。
**没有** shop / currency / item / inventory / template 服务。（7.1 相对 7.0 新增的正是 `beyondClientScriptService` /
`wpfClientScriptService` / `wpfColEditService` / `beyondRoleStatusService` 等，**依旧与模板无关**。）

---

## 3. 读到的 NEW handler —— 它们**构造什么**（step 3）

### 3.1 「新建复合节点」——**构造的是节点，不是模板**

`bdbYGlXPnjBEKi4qQ11X.hWfunLXP1LCpUbtnvrZ2.cs:7409` 的静态方法 `C2cXojsMIKF(...)`（:7447 用 `…_NEW_COMPOSITE_NODE` 键）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


它是一个 WPF **ViewModel 工厂**：新建一个 `O6Xe5UXWOepEMsrsi0jb`（复合节点编辑器）视图，把 `templateType`
置为枚举 `(DqK44bEbfTF6mNYafdSk)6`，触发 kind `1000`。**产出物是「复合节点（节点图里的一张子图）」，不是货币 / 道具 / 商店模板。**
（同族错误串：`:7417` `"can't create compound node for " /* string 70474 */`——**compound node** 说死了对象类型。）

### 3.2 「新建信号」——信号面板按钮

`V4YT5UQPem8NWbNxpaAD.uZuJhOQPxgdZ7NY7TNkH.cs:186` 的构造函数 `:199` 建一个菜单/按钮：
`cXCc41AOP9V2q3v2Lj9u…(Ca6QPMO0wxy, "UI_BEYOND_ASSIST_EDITOR_SIGNAL_ADD_NEW_SIGNAL" /* string 158932 */, …)`。
挂到信号编辑面板，点下去是「新增一条信号」。**不是模板。**

### 3.3 「新建文件夹」——资源管理器右键项

`alDQGaXN6xuqGOMAqqaB.oKWD1gXNh3WjvDNoejLm.cs:1173`：`text = …("UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_NEW_FOLDER" /* string 86350 */, …)`。
右键菜单项，其余 10 处命中都在同类菜单构造里。**不是模板。**

### 3.4 「新建蓝图」——节点图资产，不是模板

`XTs12bjtnIIe7VCqgJoS.lmCFgRjt19Z8M8CEWyaO.cs:1245`：`…_DEFAULT_RIGHT_MENU_NEW_BP` 绑定到命令 `JQWjt59Nf2g`，
是资源管理器里「新建蓝图（=节点图 / 指令图资产）」。**不是货币 / 道具 / 商店模板。**

**step 3 判决**：**没有找到任何「新建」按钮的 handler 会 assign 一个模板 id / 建一条模板 record。**
最接近「构造一条新记录」的是**复合节点**（§3.1）与**蓝图**（§3.4）——两者都是**节点图资产**，不是模板。

---

## 4. 7.1 专有命令逐条：**没有一条**是模板操作（step 4）

### 4.1 `create / batchcreate / delete / batchdelete / modifyname / modifypath` —— **节点库（节点管理器）**

七条命令在同一文件 `RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx.cs` 里，一字排开，走同一服务选择子
（`vSVbEwtxvALseRo28ugN.eEotTngJvom`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**语义判据**：对象带 **name + path**，可**改名**（`modifyname`）、**改路径**（`modifypath`）、**批量建/删**——
这是一套**文件系统式的库**。它的键在字符串表里紧挨着（偏移有序）：
`"71052":"create" → "71110":"batchdelete" → "71136":"modifyname" → "71160":"modifypath" → "71184":"UI_BEYOND_ASSIST_EDITOR_NODE_MANAGER_IMPORT_NODE" → "71284":"UI_BEYOND_ASSIST_EDITOR_NODE_MANAGER_COMPOSITE_NODE"`
⇒ **`create/batchcreate/…` 属「节点管理器 / 节点库」**（导入节点、复合节点）。
**它建的是「节点 / 复合节点」，不是模板。**

### 4.2 `modifyNodeConfig / deleteNodeConfig / modifySignal / deleteSignal` —— **节点配置 / 信号**（且是「外部工具消息」入口）

同属一个类 `mtnPv7XKt2ife06AyhaF.PSy0npXKiFSuSpN6XrJ8`（`:20`），入口是 `:32`
`public bool Invoke(string P_0, List<…> P_1, List<…> P_2)`——**一个按字符串分派的外部指令处理器**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- `modifyNodeConfig`：收 4 个参数（2 段 protobuf + 2 个 uint），反序列化成 `fmSkxDEJPb170b7i4xjq` / `yrcsZCEf14JbP2s1OYQQ`，包装成 `xgWitTXvv0qgQsGeu5tP.IELms2PDZ73JkDLt278D` 投递给服务。
- `deleteNodeConfig` / `modifySignal` / `deleteSignal`：同形，分别是节点配置删除、信号改名/改参、信号删除。
- 参数全是 **node-config / signal 的 protobuf**，**没有任何模板字段、没有 id 分配、没有 record 落盘**。

⇒ **step 4 判决**：`batchcreate / batchdelete / deleteSignal / modifySignal / deleteNodeConfig / modifyNodeConfig`
**没有一条是模板操作。** 前两条是**节点库**的批量增删；后四条是**节点配置 / 信号**的读写（外部工具消息入口）。

---

## 5. 判决（step 5）

> ### **No —— 7.1 里没有建模板路径。**

**判定依据（三种抽取；均取自同一份 7.1 build，**不是三个独立层**，见下方「口径更正」）：**

| 层 | 强 / 中 / 弱 | 事实 | 证据 |
|---|---|---|---|
| 服务名 | **强** | 7.1 全 13 个服务名无 shop/currency/item/template | `fSX5SsLhejTgt1FiF9Mk.aJl3EGLhx8dONChlfm3o.cs:19+` |
| 字符串表 | **强** | 2,985 条（=全部 `ldstr`）里 `Shop/Currency/Inventory/Bag` 0、命令名无 `Create*Template/CreateItem/CreateShopTemplate` | `string-table-7.1.json` |
| 代码字面量 | **强** | 12,955 文件 / 2,925 distinct 字面量里，无货币/道具/商店模板命令，无相关 handler | `tc71_literals.json`、`tc71_hits2.json` |

**7.1 vs 7.0 的净差**：7.1 多出的是 **Lua 客户端脚本子系统**（`beyondClientScriptService` / `Template_ClientScriptExplorerMain` /
`UI_BEYOND_EDITOR_UIEDITOR_CLIENT_*` / `*.lua`）与**一批节点/信号新命令**——**没有一条落在货币 / 道具 / 商店模板上**。
⇒ **从 7.0 语料得出的「建模板不存在」这一负面，在 7.1 语料上重搜后仍然成立，并且从「语料层证据」升级为「代码层 + 字符串层证据」。**

> **口径更正（2026-10-11）**：上表三层（服务名 / 字符串表 / 代码字面量）**全部取自同一份 7.1 `BeyondEditor.dll`**，
> 是**重复观测**——「互不依赖」过强。本负面真正的独立轴只有**两代构建（7.0 / 7.1）**：结论 = **两个 build 同向**，
> 并带**正面控制**（`DeleteComponentForEditObj` 在两层命令面都可见，证明字面量检索确实能命中真命令）。
> 方向不变（仍是不存在），只改证据强度。

**边界（诚实声明，与 `MENU-STRING-HOME.md §4` 同一口径）**：
本语料只覆盖 **`BeyondEditor.dll`** 这一个 C# 程序集。**加密的 XAML/BAML 资源、其它程序集、游戏侧 56 GB 加密 `.blk`** 不在内。
但有一处**反向线索**值得记下：那 4 个真的带 `TEMPLATE` 的 TextMap 键，**在代码里 0 引用**（§1.3）——
说明「键存在但代码不用」是**本 build 的常态**（`UI_BEYOND_EDITOR_ESP_LIGHTING_*` 亦如此）。
即便某个界面真的只活在 BAML 里，由命名空间可知它属 **`UIEDITOR_CLIENT`（界面控件模板）**，
**与官方文档的「背包与货币 / 商店模板管理」是两套东西**——**货币 / 道具 / 商店模板面板的键名，本机六份可读来源里一份都没有。**

---

## 6. 复现（只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**数据源与哈希校准**
- 7.1 raw：`$C7/adapter-port/decomp-7.1/`（12,955 `.cs`；`.source.json`：`sourceSha256=565dda11883f0220bae050438fcf52b2288f26b61ed656e2b4cd6d69b41a678a`，`sourceDll=…BeyondEditor.dll`）。
- 7.1 annotated：`$C7/strings/annotated-7.1/`（12,955 `.cs`，`"lit" /* string N */`）。
- 7.1 字符串表：`$C7/strings/string-table-7.1.json`（2,985 条）＝ `$C7/strings/verified-table.json`＝`.runtime/scratch/editor71-string-table.json`；
  原始资源 `$C7/strings/string-resource.bin`（183,508 B）；`.source.json`：`entryCount=2985`、`tableByteLength=183508`、`profile=editor-7.1`。
- 装机 TextMap 键：`.runtime/scratch/_tm_keys_all.txt`（8,266 键）← task #2 `MENU-STRING-HOME.md` 现解。
- **本轮未读 `D:/games/` 任何文件、未读写 `C:/Users/…/miHoYo/` 任何字节。**

**未做**：未连桥、未发 bridge/native 报文、未重启 helper、未申请 UAC、未读图片/PDF、未写 `tools/` 或任何测试。
