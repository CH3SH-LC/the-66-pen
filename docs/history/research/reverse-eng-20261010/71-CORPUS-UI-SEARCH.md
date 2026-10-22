> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 71-CORPUS-UI-SEARCH — 把「背包与货币 / 商店模板管理」的键名拿去 7.1 语料里搜

**产出日期**：2026-10-10
**任务编号**：#3 THE SEARCH
**口径**：**纯离线、纯只读**。未连桥、未发任何 native/graph 报文、未重启 helper、未申请 UAC、未触碰游戏/编辑器进程。
对 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` **一个字节都没读**；未读任何图片/PDF。
**只读动作**：`ls`、Python 直读文件字节、内存遍历语料（不落盘到语料外）。
**写盘**：只写本文件 + `.runtime/scratch/71-*.json/py`（检索脚本与中间索引）。
**本文件是本任务唯一交付物**；未改 `tools/`、未改任何 pin、未改任何测试。

**上游输入**
- 任务 #2 的键单 `.runtime/scratch/installed-ui-keys.json` —— **不存在**（`ls` 实测）。故按任务允许的兜底路径，
  我从**装机 TextMap**自行派生键单，落在 `.runtime/scratch/71-corpus-keys.json`（**8267** 键，等于装机 TextMap 全量）。
- 装机 TextMap 原件：`D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/Resource/Json/TextMap/CHS/17720714722766726369.mihoyobin`
  （655179 B），既有解码产物 `.runtime/scratch/_tm_chs/17720714722766726369.mihoyobin.json`（`fields` 8268 条）。
- 7.1 语料：`.runtime/verification/update-repair-20260925/adapter-port/decomp-7.1/`（**12955** 个 `.cs`，含 2684 个 `_ERR_*.txt`）。

---

## 0. 一句话结论

> **7.1 语料里没有「新建货币 / 新建道具 / 新建商店模板」这条创建路径——而且这次能给出比 7.0 更强的否证。**
>
> 理由不是「7.1 语料没搜过」：搜了，**是 0 命中**。原因是 **7.1 语料的 `.cs` 里根本没有明文字符串**
> （ConfuserEx 字符串加密，见 §2），所以「拿键名去 grep」这条路在 7.1 上**结构性地搜不动**。
>
> 但本仓**已存在一份 7.1 的「解密后字符串表」** `.runtime/scratch/editor71-string-table.json`（2985 条，
> 源 = 装机 `BeyondEditor.dll`，见 §3）。把这张表也搜了：**440 条 `UI_BEYOND_*` 键里，0 条涉及
> 商店 / 货币 / 背包 / 模板**。把 7.1 语料里的 **XAML 面板清单**（47 条，§5）也看了：**没有该面板**。
> 把 7.1 语料里的 **资源类型枚举**（§4）也看了：`Currency / StuffBag / ShopTemplate` **成员在表里，
> 但全语料没有任何一处按名使用它们**（`X.Currency` 等 0 命中）；连「哪些类型可被创建」的过滤表
> （§4.3）也**只列 8 种类型，不含 Currency/StuffBag/ShopTemplate**。
>
> ⇒ **对任务的核心问句：「7.1 里存在 create handler 吗？」——不存在。** 不是藏着的按钮，
> 是**这一整块系统菜单面板不在装机 `BeyondEditor.dll` 的可读面里**（装机唯一一方程序集就是
> `BeyondEditor.dll` 18.4 MB + `BeyondEditor.exe` 365 KB，见 §6）。这一结论与 7.0 侧
> `TEMPLATE-CREATE-TRACE.md` 同向，且**新增了两条独立 7.1 证据（解密字符串表 + 枚举使用面）**。

**对上游口径的一处修正**：本任务前提「符号在 7.0→7.1 之间被重新随机化」**只对类型名/方法名成立**；
**枚举成员名与少数框架类名并未重新随机化**——`Currency`、`ShopTemplate`、`StuffBag`、
`BeyondComponentEditPanel`、`BeyondEditor.ViewModelCore.KeyToTextMapConverter` 等**原样保留**（§4、§5）。
所以「按名搜索」在 7.1 上仍**有落脚点**，只是这些落脚点全部指向**已被覆盖的模块**，不指向本面板。

---

## 1. 键单与派生方法

任务 #2 未产出键单（`ls .runtime/scratch/installed-ui-keys.json` → 无此文件）。故从装机 TextMap 现解：

| 项 | 值 | 来源 |
|---|---|---|
| 装机 TextMap 键总数 | **8267** | `.runtime/scratch/71-corpus-keys.json`（本任务派生） |
| 其中 `UI_*` 键 | **1278** | 同上 |
| 其中 `UI_BEYOND*` 键 | **1277** | 同上 |
| `UI_BEYOND` 家族分布 | EDITOR 827 / ASSIST 358 / LOG 66 / GENERAL 12 / COSTLOAD 12 / CONTROL 2 | 同上 |

**关键：目标面板的键，在装机 TextMap 里就是 0。**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


带中文值的键里，`新建*` 24 条全是节点图/光源/环境/特效器/脚本（`.runtime/scratch/71-corpus-keys.json` 检索）；
**没有 `新建货币 / 新建道具 / 新建商店模板`**。这与 `MENU-STRING-HOME.md §1.2` 一致
（该文已证：装机 TextMap 里 `ESCNAME` 后缀的「系统菜单」键**只有 1 条** = `UI_BEYOND_EDITOR_ESP_LIGHTING_ESCNAME = 光源管理`）。

---

## 2. 决定性事实：7.1 语料的 `.cs` 里 **没有明文串**

先把两边的「可读性」摆平，否则「grep 0 命中」会被误读成「不存在」。

| 指标 | **7.0** `.runtime/editor-catalog/resolved/` | **7.1** `.runtime/verification/.../decomp-7.1/` |
|---|---|---|
| `.cs` 文件数 | 12375 | 12955 |
| 全语料引号字符总数 | **11463** | **1473**（47 MB 里！） |
| 含 `UI_BEYOND` 明文字面量的文件 | **91** | **0** |
| 含 ConfuserEx 反篡改标记 `<Module>{0501a6fa-…}` 的文件 | **0** | **2871** |
| 含字符串解密调用 `X.vamPAss8BQY(0x… ^ 0x…)` 的文件 | **0** | **576** |

**7.0 是「已解密」反编译**，明文字面量直接可见，还带 `/* string NNNNNN */` 注解：

- `.runtime/editor-catalog/resolved/zJuB8VueHhBspK3PDhqo.u4vgh9uebiscBdHWcnLi.cs:683`
  `YlKu2QYfNaDsptndNkxX.xyVYfsr3qg0("UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_DEBUG_LOG" /* string 160978 */, …)`
- `:682` 同形 → `"UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_NODE_MANAGER" /* string 159462 */`（=显示「节点管理器」）

**7.1 是「未解密」反编译**，同样的调用点长这样：

- `.runtime/verification/update-repair-20260925/adapter-port/decomp-7.1/A0CpxAQMx0mFZCojoXrh.kWURUTQMmb3jmJ4pIAgT.cs:20`
  `… OfHnbKPAfwDjrwrhrnHS.vamPAss8BQY(0x46DF9D65 ^ 0x46DEEAFF, OfHnbKPAfwDjrwrhrnHS.UuIPAuUcgRX)`
- 同文件 `:29`：`if (<Module>{0501a6fa-55c3-4a08-8b59-fa2eff76993a}.m_48c3b06f… != 0)` ← 反篡改

**一次性把 7.1 全部 12955 文件抽出的引号字面量只有 73 条**（`.runtime/scratch/71-literals.json`），
逐条核过，**全部**是框架/协议/反篡改常量：`Google.Protobuf` 枚举（`TYPE_STRING`/`CARDINALITY_REPEATED`/…）、
`user32.dll` 的 P/Invoke（`SetWindowLongPtr`/`GetForegroundWindow`/…）、Astrolabe 崩溃上报（`Astrolabe_Init`/…）、
`" is tampered."`、`"Debugger Detected"`、`{11111-22222-…}`（ConfuserEx 模块 id）。
**与 73 条求交装机 8267 键 → 交集 0**。逐键 grep 的答案因此是：**没有任何文件携带这些键**（步骤 2 → 0 命中）。

> **结论**：在 7.1 语料上「拿键名 grep」**不可能有正结果**——不是因为面板不在，而是因为 **7.1 语料的串是密文**。
> 任务给的前提（「7.1 语料从没搜过」）在这一层上是**工具不可用**，不是「语料未覆盖」。

---

## 3. 换个入口：本仓已有 7.1 的**解密字符串表** —— 搜它

`.runtime/scratch/editor71-string-table.json`（126 KB，**2985** 条 `偏移→字面量`），
其 `.source.json` 指明它解的就是**装机 7.1**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


对照：`extract-user-strings.py` 抽 7.1 的 `#US` 堆只有 **15 条 / 684 字节**（`.runtime/scratch/_be_strings.json.source.json`）——
即**装机 DLL 的 `#US` 堆被清空**，全部 UI 串都在**加密资源** `7ObTTdEd…` 里。上面这张 2985 条表就是把该资源解出来的。

**注**：`.runtime/scratch/editor71-string-table.json` 与仓内**规范位置**的
`.runtime/verification/update-repair-20260925/strings/string-table-7.1.json`、`…/strings/verified-table.json`
**逐字节同一份**（2985 条，`a==b==c` 实测相等）；同目录 `fold-key-7.1.py` / `constant-fold-trace.json`
即把 ConfuserEx 的 XOR 常量折叠回明文串的过程，`resources.json` 列出该 DLL 的加密资源包
（含 `7ObTTdEd8bVVgdZyVy.SA0dOcRiWY2ZDNyWjq` = 本表来源）。

**在这张 7.1 解密表里搜目标词 —— 全部 0：**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**表里确实有 440 条 `UI_BEYOND_*` 键**（节点图/资源管理器/costload/信号相关），
但**没有一条**属于本面板。且把 7.0 / 7.1 两张串表做差：

| | 7.0 `string-table.json` | 7.1 `editor71-string-table.json` |
|---|---|---|
| 条目 | 2830 | 2985 |
| `UI_BEYOND_*` 键 | 385 | **440** |
| **7.1 新增键** | — | **55** 条 = **48** 条 `UI_BEYOND_EDITOR_UIEDITOR_CLIENT_*`（**客户端脚本编辑器**，7.1 新模块）+ 2 条 `COOP_*` + 1 条 `ASSIST_EDITOR_LOG_OPEN_PATH` + 4 条 `LOG_*`（过滤/提示） |
| 7.0 独有/被删键 | — | **0** |

⇒ **7.0→7.1 的 UI 增量 = 客户端脚本面板（48 键）+ COOP/LOG 杂项（7 键）**，**与「背包与货币 / 商店模板管理」无关**。
该新增面板我没有误判：其键名逐条列于下（节选，全部 55 条见附录 A），如
`UI_BEYOND_EDITOR_UIEDITOR_CLIENT_NEW_CLIENT_SCRIPT`、`…_SCRIPT_CREATE_FILE_TITLE`、`…_SCRIPT_ASSET_MANAGER`。

---

## 4. 7.1 语料里的**结构性**落脚点：枚举成员没被随机化

明文串搜不动，但 7.1 语料里**有一类符号没被混淆**：**枚举成员名**。本面板相关的两类枚举**原样在**：

### 4.1 资源类型枚举（assetType）—— 7.1 与 7.0 逐字节同一份

| 成员 | **7.1** `decomp-7.1/tkvOndLluGfYKDDusXdN.k8YsY8LlfZTdUYkZusUJ.cs` | **7.0** `resolved/lFHetii40EU81IVmn9aC.n9TjVui4v9PFdo3m497f.cs` |
|---|---|---|
| `StuffBag = 22` | `:27` | （同表 22） |
| `Currency = 23` | `:28` | `:28` |
| `EquipStuffBag = 27` | `:32` | （同表 27） |
| `ShopTemplate = 28` | `:33` | `:33` |
| `StructTemplate = 29` | `:34` | （同表 29） |

### 4.2 资源 ID 类型枚举（idType）

| 成员 | **7.1** `decomp-7.1/tLIOVGLlTI5r6KnITHpN.hWLVN0LlULfNtpkRxSR1.cs` | **7.0** `resolved/nftmtEi44ZpaT9uR9UgI.u2nWUWi4Ei8tbmQLVnuN.cs` |
|---|---|---|
| `Currency = 3700` | `:45` | `:45` |
| `StuffBag = 3800` | `:46` | （同表 3800） |
| `EquipStuffBag = 3900` | `:47` | （同表 3900） |
| `ShopTemplate = 4000` | `:48` | `:48` |
| `StructTemplate = 4100` | `:49` | （同表 4100） |

⇒ **跨 build 映射（步骤 4 答案）**：`n9TjVui4v9PFdo3m497f ⇄ k8YsY8LlfZTdUYkZusUJ`、
`u2nWUWi4Ei8tbmQLVnuN ⇄ hWLVN0LlULfNtpkRxSR1`（成员表逐项相等，**按结构判定**，非按名）。
`merged-symbols-7.1.json` **并不含**这对（它只有 250 条，是本轮适配器绑定的精选表），故未采用之。

### 4.3 —— 但枚举成员**全语料无人按名使用**（create handler 落空的硬证据）

- 7.1 全语料搜 `k8YsY8LlfZTdUYkZusUJ.Currency` / `.StuffBag` / `.ShopTemplate` → **0**；
  同法 `hWLVN0LlULfNtpkRxSR1.Currency` / `.ShopTemplate` / `.StuffBag` → **0**。
- 7.0 同法（`n9TjVui4v9PFdo3m497f.*` / `u2nWUWi4Ei8tbmQLVnuN.*`）→ **0**。
  （该三成员只在枚举声明文件里出现，别处无人引用。）
- 唯一引用 assetType 枚举的「**可创建类型过滤表**」在 7.1 里是
  `decomp-7.1/N7kvaYXPOmtNuKfm3IR2.rfAkmxXPIA6RBpFQ7E3v.cs`（该枚举 28 个引用文件里引用最密者，38 处）。
  其 switch 把「父类目 id」映射到**允许创建的类型**，但**用到的成员只有 8 个**：
  `LevelSpaceAsset, PrefabSpaceAsset, CustomPrefabDynamic, CustomPrefabStatic, CustomMonsterDynamic,
  CustomDropGather, PlayerCustom, RoleStatus`（首例 `:49` `list.Add(k8YsY8LlfZTdUYkZusUJ.LevelSpaceAsset);`），
  **不含 `Currency` / `StuffBag` / `ShopTemplate`**。

> 即：**连「什么类型能被创建」的代码面都不覆盖货币/背包/商店模板**——这不是「按钮被藏」，是**该分支不在语料里**。

### 4.4 组件类型枚举（顺带，与今晚 Component READ=0 相关）

7.1 `decomp-7.1/zn1Mv9ZOCIYgNdSVMyWb.QhNByxZONrdCQv6vIMYe.cs`（7.0 对应
`resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs`，两边 `BeyondCompType` 各 46 条）含：
`:36 BeyondCompTypeStuffBag = 33`、`:37 BeyondCompTypeEquipStuffBag = 34`、`:38 BeyondCompTypeShop = 35`、
`:40 BeyondCompTypeDropStuff = 37`。**注意缺口：无 `=2`**（枚举里 `CustomValue=1` 后直接跳 `Timer=3`）。
该枚举在两 build 相同，说明**编辑器侧认识「商店/背包组件」这个类型**——但与本面板的**创建路径**是两回事。

---

## 5. 7.1 全量 **XAML 面板清单**：没有本面板

从 7.1 解密串表里抽出全部 `*.xaml` 路径（**47** 条）。目录形如下（节选）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**没有** Shop / Currency / Bag / TemplateManagement / SystemMenu 任何一项。
`UI_BEYOND_EDITOR_ESP_LIGHTING_*`（光源管理）也**不在这张 7.1 串表里**（`ESP_LIGHTING` 0 命中）——
说明该串表**并非 UI 全量**（ESP 菜单在装机 TextMap 里确有键、在 7.0 语料里有明文引用），
**但它是「已覆盖模块」的下界**：连已覆盖的 ESP 都可能缺条，**不能凭它单独下「不存在」的死判**。
故本报告的否证**不单靠它**，而是 §3（串表 0）+ §4.3（枚举使用面 0）+ §5（XAML 0）+ §6（装机程序集清单）**四条同向**。

---

## 6. 边界：面板只可能在哪个文件里

装机 `BeyondAssistEditor/` 下**唯一的一方程序集**（`ls` 实测，只读）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`metadata-7.1.json` 与 `editor71-string-table.json.source.json` 的 `sha256` 都是
`565dda11…`，即**反编译语料与解密串表都来自同一枚装机 `BeyondEditor.dll`**。
所以结论是闭合的：**面板若在，就在这枚 DLL 里；而它在这枚 DLL 的两条可读面（12955 个 `.cs` + 2985 条解密串）
都没有**。剩下的可能只有**未解密的 BAML/XAML 资源**与**游戏侧加密 `.blk`**——
这正与 `MENU-STRING-HOME.md §0` 的边界声明一致（那一步是「读不到」，不是「没找到」）。

---

## 7. 对任务逐条的正面回答

| 任务步骤 | 结果 |
|---|---|
| **1. 读 #2 键单 / 自行派生** | #2 未产出 → 自行派生 **8267** 键 → `.runtime/scratch/71-corpus-keys.json` |
| **2. grep 7.1 语料找键字面量** | **0 文件命中**（7.1 `.cs` 无明文串；见 §2）。附：7.0 侧同轮为 **91 文件 / 379 键**命中 |
| **3. 读 top hits 找 VIEW MODEL / 新建按钮** | **无命中可读**。转而对 7.1 的**结构落脚点**取证：枚举 (§4)、XAML (§5)、创建过滤表 (§4.3) —— **无 create handler** |
| **4. 与 7.0 比对（重随机化）** | 类型/方法名确被重随机化；**枚举成员名未随机化**，据此建立两枚举的 7.0⇄7.1 映射（§4.1/4.2）。7.1 相对 7.0 **无新面板**，UI 增量 = 客户端脚本面板 48 键 + COOP/LOG 7 键（§3） |
| **5. 报告：找到了吗** | **没找到**。**7.1 侧不存在该模板创建路径**（也不是「被藏起来的按钮」）。与 7.0 侧 `TEMPLATE-CREATE-TRACE.md` 同向，**否证强度增加** |

**同类否证已在册**：`tools/gameplan/tests/test_add_component_absent.py` 用**同一批只读材料**（两张串表 + 两份命令表 SQLite + 12375 个 `.cs`）
把「加组件命令缺失」钉成 drift alarm；本轮实测该测试 **9 passed / OK**，且其结果与本报告同向
（组件面板的 list view model 在 7.0 语料里**存在**，但其静态工厂**全语料零调用者**——**面板接线在语料之外**，与 §6 边界一致）。

**若上游要「下一步」**：搜索键名这条路在装机 DLL 上**已穷尽（0）**。要推进只剩两条，且都**不属本任务、且都有代价**：
(i) 解 7.1 的**加密 BAML/XAML 资源**（需 ConfuserEx/BAML 解密器，风险高）；
(ii) 转**游戏侧**：面板真正落盘的动作靠后端命令，去游戏映像（加密 `.blk`）做命令名哈希落点扫描。
**两条都不该在「无 UAC、只读」口径下贸然做**——建议作为独立任务另立。

---

## 附录 A — 7.1 相对 7.0 新增的 55 条 UI 键

杂项 7 条：`UI_BEYOND_ASSIST_EDITOR_LOG_OPEN_PATH`、`UI_BEYOND_EDITOR_COOP_COLLABORATIVESECTION`、
`UI_BEYOND_EDITOR_COOP_WPF_SECTION`、`UI_BEYOND_LOG_FILTER_STATUS_SCRIPT_{ERROR,NORMAL,WARNING}`、
`UI_BEYOND_LOG_TIPS_DEBUG`。

客户端脚本 48 条：`UI_BEYOND_EDITOR_UIEDITOR_CLIENT_*` —— `ADD_VARIABLE / APPLY_CHANGES / CLEAR_CHANGES /
CONTROL_BLANK_COPY_LOG / CONTROL_BLANK_SCRIPT_ALLFILE / CONTROL_BLANK_SCRIPT_DELETE_CONFIG /
CONTROL_BLANK_SCRIPT_DELETE_INVALID_FILE / COPY_SCRIPT_MAPPING_ID / COPY_SUCCESS / DELETE / DELETE_VARIABLE /
EDIT_SCRIPT_VARIABLE / EXISTING_SCRIPT_AND_MAPPING / EXPORT / EXTERNAL_SCRIPT / FILE_PATH /
LOG_LOCAL_{ERROR,NORMAL,WARN} / MODIFY_REFERENCE_PATH / NEW_CLIENT_SCRIPT / NEW_SCRIPT_MAPPING / OPEN /
OPEN_MAPPING_FILE_LOCATION / RENAME / SCRIPT / SCRIPT_ADD_FILE / SCRIPT_ADD_FOLDER / SCRIPT_ASSET_MANAGER /
SCRIPT_CREATE_FILE_TITLE / SCRIPT_DEBUG_TYPE / SCRIPT_EXTERNAL_ASSET / SCRIPT_LAYER_ID / SCRIPT_LAYER_ID_LIST /
SCRIPT_PATH_EMPTY / SCRIPT_TIP_CREATE_FAIL / SCRIPT_TIP_FILE_NONE / SCRIPT_TIP_OPEN_FAIL / SCRIPT_TIP_SAME_NAME /
SCRIPT_TIP_SAME_ROOT / SCRIPT_TIP_WRONG_ROOT / SCRIPT_VARIABLE_MANAGER / SCRIPT_WINDOW_TIP_FILE_TYPE /
SCRIPT_WINDOW_TIP_FOLDER_TYPE / SCRIPT_WINDOW_TIP_ROOT_NONE / SCRIPT_WINDOW_TITLE_FILE / SCRIPT_WINDOW_TITLE_FOLDER /
SCRIPT_WINDOW_TYPE`。
**与「背包与货币 / 商店模板管理」0 相关。**

## 附录 B — 复现脚本（`.runtime/scratch/`，均只读）

| 脚本 | 作用 |
|---|---|
| `71_lit_index.py` | 抽 7.1 全语料引号字面量 → `71-literals.json`（73 条） |
| `71_token_scan.py` | 7.1 全语料 token 计数（UI_BEYOND=0、Currency/Shop 等=0、ConfuserEx 标记统计） |
| `71_refs.py` | 枚举引用面扫描（7.1 / 7.0 两侧） |
| `71_members.py` | 枚举成员逐名引用计数（全 0） |
| `71_corpus_stats.py` | 两 build 引号/反篡改/明文键三项对照 |
