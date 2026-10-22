> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 建模板（货币 / 道具 / 商店）的创建路径追踪 —— 编辑器 UI 里那个「新建」按钮走到哪

日期：2026-10-10。**全程只读**：未连桥、未发任何 bridge/native 报文、未注入、未启动或触碰
游戏/编辑器、未起 helper、未申请 UAC。对 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` **一个字节都没读也没写**（本文件未触碰存档）。
产物只写在 `.runtime/scratch/`（本次检索脚本）与 `docs/research/reverse-eng-20261010/`（本文件）。

**本文件回答一个问题**：官方 UI 的【背包与货币】/【商店模板管理】里有「新建货币 / 新建道具 / 新建商店模板」
按钮（逐字见 `docs/official-docs/chapters/mhbgx0rspbqu.json` / `mhi9s7isvp50.json` / `mhn4bsi5lb58.json`）。
**这个「新建」按钮点下去，编辑器进程里执行到哪一行代码、发到哪条后端命令？**
—— 答：**在已被逆向的编辑器语料里，这条路径根本不存在**。下面是把它挖空的过程与边界。

**数据来源（全部只读）**
- 反编译语料 `.runtime/editor-catalog/resolved/` —— **12375** 个 `.cs`（`BeyondEditor.dll` 反编译成功集；
  失败集见 `.runtime/editor-catalog/decomp/BeyondEditor/_ERR_*.txt`，**2555** 个，全是 `Could not find type definition <X>/<>c`
  这类**编译器生成的嵌套闭包类**，不是业务类，见 §5）。
- 字符串堆 `.runtime/editor-catalog/string-table.json`（**2830** 条 `偏移→字面量`）、
  `.runtime/editor-catalog/textmap-chs.json`（**7743** 条 `key/hash/text` 本地化）。
- 前端命令面 `docs/research/beyondeditor-frontend/db/frontend.db`（`operation` 44 行 / `feature` 80 行 /
  `ui_text` / `capability_gap` 28 行）与 `docs/research/beyondeditor-user-operations/db/userops.db`
  （`user_operation` 92 行 / `ui_element` 395 行 / `ui_template` 49 行）。
- 后端落点 `docs/research/beyondeditor-backend/db/backend.db` → `command_route`（**38** 行，本轮 `sqlite3` 只读逐行读过）。
- 官方 ID 类型表 `docs/official-docs/chapters/mhsd6lrx3voe.json:64-66`；面板入口章
  `mh2cr30yeak0`（货币）/ `mhbgx0rspbqu`（道具）/ `mhi9s7isvp50`（商店）/ `mhn4bsi5lb58`（整体界面）。

---

## 0. 一句话结论

**在「编辑器 = `BeyondEditor.dll`」这个反编译语料里，没有任何一条路径建模板。** 三条独立证据链同向：

1. **没有视图模型**：货币 / 道具 / 商店三类模板的 UI 文本键命名空间**一条都没有**（§2），
   命令字面量里**没有**任何 `新建货币 / NewItem / CreateItem / CreateShopTemplate` 之类（§1）。
   被逆向出来的编辑器模块是「助手编辑器」：节点图、环境(ESP)、特效器(VFX)、原型工具、日志、负载测试——
   **不含货币与背包 / 商店模板管理这一整块系统菜单面板**。
2. **没有后端路由**：`command_route` 38 行逐行核过，`Add*` 只对**节点图**，`Modify*` 只有 Name/Tag/Faction/Suite，
   **没有一条**建模板/货币/道具/商店（§3）。这与 `TEMPLATE-CREATION-MINE.md` 的第一手 SQL 复核一致。
3. **没东西可填**：即便想在 `.gil root field 15` 手写一条模板，本机**没有 type 8/10/15 的任何实例可照抄**，
   组件块 schema 无样本（`TEMPLATE-STORAGE.md §4.2`）。

**因此「模板创建」在编辑器侧是——**「**不是藏起来的按钮，而是这个面板从没被逆向**」。
要补，只有一条路：**继续逆向「系统菜单」这一整块前端 UI**（本工程唯一未覆盖的编辑器面板），
读出「新建货币」按钮真正派发的命令名，再回游戏映像做哈希落点扫描。
**这与「操作面里没有」是两回事**——见 §6 的边界声明。

> **口径更正（2026-10-11）**：上面「三条独立」的说法偏强。第 1、2 条**量的是同一个命令命名空间**
> （第 1 条＝反编译语料里的字面量，第 2 条＝后端 `command_route` 路由表，两条是**同一份 7.0 build 命令面的两个采集通道**），
> 第 3 条是数据样本可用性。本工程对「建模板不存在」真正的独立轴是**两代构建（7.0 / 7.1）**
> （7.1 侧见 `71-TEMPLATE-CREATE.md`）。结论方向不变（仍是不存在），只改证据强度。

---

## 1. 在 `resolved/*.cs` 里逐条检索「创建」——全部 0 命中

### 1.1 本轮方法（一次遍历建索引，避免十几次昂贵的 `grep -r`）

`resolved/` 有 **12375** 个文件、**72 MB**。为避免「每个关键词各扫一遍」耗掉十几分钟，本文件用一个
**单遍读取器**（`.runtime/scratch/lit_index.py`）把 12375 个文件里**所有 C# 字符串字面量**
（含反编译器内联的 `/* string N */` 注释）抽成 `字面量 → [file:line,…]` 索引
（`.runtime/scratch/literals_index.json`，**2805** 条 distinct）。此后所有关键词检索都是**离线查表**，
不再重复扫盘（全程只读）。

> 为什么用「字面量」而不是「文本」：编辑器发出的**命令名就是字符串字面量**
> （例：`DeleteComponentForEditObj` 在 `.runtime/editor-catalog/resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107`
> 逐字可见）。所以「有没有创建命令」＝「有没有这个字面量」。
> **正面证据佐证该索引可信**：它命中并定位到 file:line 的命令字面量（§1.4）与 `command_route` 的 38 行**对得上**，
> 且能定位到具体文件行号。

### 1.2 任务点名的字符串 —— 逐条结果

用 `.runtime/scratch/lit_query.py` 与 Bash `grep -rIl` 双跑（结果一致）：

| 检索串 | `resolved/*.cs` 命中 | 说明 |
|---|---|---|
| `货币与背包` | **0** | 中文根本没进 `.cs`（见下注） |
| `新建货币` / `新建道具` / `新建商店` / `新建背包` | **0** | 同上 |
| `货币` / `道具` / `商店` / `背包` | **0** | 同上 |
| `新建` | **0** | 同上 |
| `NewItem` / `CreateItem` / `AddItem` | **0** | ASCII 命令名，确实不存在 |
| `NewCurrency` / `CreateCurrency` / `CreateShop` / `CreateTemplate` / `NewTemplate` / `TemplateCreate` | **0** | 同上 |
| `Currency` / `ShopTemplate` / `StuffBag`（**字符串字面量**） | **0** | 见下注 |

> **两点必须点破的口径**：
> (a) **中文不在 `.cs` 里**——编辑器把界面文字放在**本地化表**（`textmap-chs.json` 的 `key/hash/text`），
> `.cs` 里只有**键名**（如 `UI_BEYOND_ASSIST_EDITOR_ESP_LIGHTING_NEW`）和一串 `/* string N */` 偏移。
> 所以中文 0 命中**不能**直接推出「没有面板」，必须转去查**键名**与**文本表**（§2 做了）。
> Bash `grep -rIn -e 货币 -e 道具 … .runtime/editor-catalog/resolved/` 亦为 **0 行**（已在后台复核到 A 段全 0）。
> (b) `Currency` 作为**枚举成员名**（非引号字面量）确实存在——见 §4 的三张枚举表；
> 但**命令名是字面量**，字面量检索才有意义。`Currency` 的字面量 = 0。

### 1.3 「创建」类的字面量到底有什么 —— 全是**别的**东西

在 2805 条 distinct 字面量里，大小写不敏感地含 `New`（22 条）或 `Create`（15 条）的**共 37 条**，
逐条看**没有一条建模板**：

- **新建文件夹 / 节点图 / 节点变量 / 注释 / 复合节点 / 信号变量**：
  `UI_BEYOND_ASSIST_EDITOR_DEFAULT_RIGHT_MENU_NEW_FOLDER`、
  `…_NEW_SERVER_BP` / `…_NEW_FILTER_BP` / `…_NEW_SKILL_BP`、
  `UI_BEYOND_EDITOR_WPF_HISTORY_NODE_NEW` / `…_CV_NEW` / `…_MENTION_NEW`、
  `…_NODE_MANAGER_NEW_COMPOSITE_NODE`、`…_SIGNAL_ADD_NEW_VARIABLE`。
- **新建造物/角色技能节点图**：`…_CLIENT_BLUEPRINT_{MONSTER_SKILL,MONSTER_POSE,MONSTER_AI,AVATAR_SKILL,CONTROL}_NEW`。
- **新建光源 / 新建环境**（ESP 面板）：`UI_BEYOND_EDITOR_ESP_LIGHTING_NEW` / `…_ESP_PROFILE_NEWPROFILE`。
- **新建特效器 / 新建轨道**（VFX 面板）：`UI_BEYOND_EDITOR_VFXEDITOR_NEW*`。
- **错误串 / 内部调用**：`can't find new node`、`failed to create node`、`create dock window failed`、
  字面量 `"create"`（见 §4 的**唯一创建机制**）。

**即：被逆向出来的编辑器里，「新建」按钮覆盖了文件夹/节点图/注释/光源/环境/特效器/轨道——
唯独没有货币/道具/商店模板。**

### 1.4 命令字面量 → 文件（视图模型邻居表）

命令字面量各落在哪个 VM 类（用于看清「命令面由哪些 VM 分摊」；下表按服务族分组，非穷举每一行）：

| 服务 / 命令族 | 承载 VM（`resolved/<ns>.<class>.cs`） | 代表命令:行 |
|---|---|---|
| 实体增删聚焦改名 | `VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs` | `AddInstructionGraphForEditObj:2118`、`DeleteEditObj:784`、`DeletePrefab:512`、`DoExport:1348` |
| 组件删除（**只有删**） | `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs` | `DeleteComponentForEditObj:107`、`DeleteComponentForPrefab:152` |
| 聚焦族 | `FOV9AWu5QBsMPf0Rwuiu.NQ6Rasu5Wb3lL511Sp4j.cs` | `FocusEditObj:733`、`FocusLight:784`、`FocusScreenshot`(另一文件)… |
| 标签 / 套组 | `kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0.cs` | `ModifyEditobjTag:2255`、`ModifyPrefabTag:2194`、`ModifySuite:2030` |
| 阵营 | `VwMawhKGHsdXfkO51YfP.HDt4hxKGbds2L9ACUaAM.cs` | `ModifyFactionForEditObj:408`、`…ForPrefab:359` |
| **节点图 / PCG / 实体改名** | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs` | `create("create"):12463`、`ModifyEditObjName:12591`、`ModifyPrefabName:15041`、`DeletePCGInstance:12601` |
| 调试日志 | `XvpSBIuvoMSpMenoIqRg.C9ev3quv9MKMEBmJNJDj.cs` | `ImportDebugLog:1312`、`DeleteDebugLog:10548` |
| 导入 / 导出 | `XTIMALKC7WrrvhklkdIs.EC9LaXKCud5dn7MZnrgl.cs` | `DoImport:486` |
| 音频 | `EF8cLvuBwl2IuhblDnsW.JVFa9yuBBE11Zhdy7ce5.cs` | `PlaySoundEffect:165`、`PlayMusic:224` |

**没有**「模板 VM」这一行，也没有服务名叫 `beyondTemplateService` / `beyondShopService` / `beyondStuffService`（§4）。

> **诚实边界（与组件「加」那条同构）**：以上是「**明文字符串可达的命令名**」范围内的精确负面。
> 反编译语料里**折叠/加密常量**命令名是本检索的盲区（`COMPONENT-WRITER-MINE.md §1/§5`）。
> 但本轮的**额外**证据（§2 的 UI 键命名空间普查）**不依赖命令名**——它直接查**面板本身在不在语料里**，结论一致。

---

## 2. 关键一步：UI 文本键的**命名空间普查** —— 哪些面板被逆向、哪些没有

中文不在 `.cs` 里（§1.2 注 a），所以改查**编辑器本地化表的 key 命名空间**。
`.runtime/scratch/ns_scan.py` 把 `textmap-chs.json` 的 7743 条 key 按前缀分组：

| 命名空间 | 条数 | 是什么 |
|---|---|---|
| `BeyondEditorInstructionNodeConfig_*` | 5667 | 节点名/端口名（图契约） |
| `BeyondAssistantEditorConfigGlobal_*` | 1082 | 全局配置（节点文件夹树、枚举字典） |
| `UI_BEYOND_ASSIST_EDITOR_*` | ~330 | 助手编辑器界面（节点图/蓝图/资源/信号/变量/负载/PCG/结构…） |
| `UI_BEYOND_EDITOR_ESP_*` / `_PROTOTYPE_*` / `_VFXEDITOR_*` / `_WPF_*` / `_COSTLOAD_*` | ~300 | 环境(ESP) / 原型工具 / 特效器 / 历史记录 / 负载 |
| `UI_BEYOND_EDITOR_UI_*` / `_SUITE_*` / `_TAG_*` / `_ATTACKTAG_*` | ~20 | 界面控件组 / 套件 / 标签 |

**命名空间清单里没有任何 `CURRENCY` / `ITEM` / `STUFF` / `SHOP` / `BAG` / `PROP` 段。**
（对照：`UI_BEYOND_EDITOR_ESP_LIGHTING_NEW` = 「新建光源」确实存在 ⇒ 若货币面板在同级，应有
`…_CURRENCY_…` 之类的键，而它**没有**。）

### 2.1 反查文本：文本里出现「货币/道具/商店/背包/新建」的条目属于哪个命名空间

`.runtime/scratch/tm_text_scan.py` / `ui_noun_scan.py` 的结果：

- 含「新建」文本的 **14** 条，全部落在：`ASSIST_EDITOR_DEFAULT_RIGHT_MENU_*`（文件夹/节点图）、
  `WPF_HISTORY_*`（节点/变量/注释）、`CLIENT_BLUEPRINT_*`（造物/角色技能图）、`ESP_LIGHTING_NEW`、
  `ESP_PROFILE_NEWPROFILE`。**没有一条是「新建货币/道具/商店/背包」。**
- 含「货币/道具/商店/背包」文本的条目，**全部**是——
  1. **节点端口名**（`BeyondEditorInstructionNodeConfig_*`，节点 681-709/710-731 的道具/背包/商店节点，M2-M5 用的那批）；
  2. **节点文件夹名**（`BeyondAssistantEditorConfigGlobal_folders_*…_name` = 「道具与背包」「商店」「道具」——
     这是**节点面板的分类文件夹**，不是模板管理面板）；
  3. 一条 UI 键 `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_STUFF_BP` = 「**道具节点图**」（蓝图管理器的一种图，仍非模板面板）。

**⇒ 「模板出现在编辑器里」的所有痕迹，都是「节点」维度的；「面板」维度 0 条。**

### 2.2 前端功能表佐证（`frontend.db → feature`，80 行）

该表是编辑器前端**功能面**的权威枚举。货币/道具/商店/背包相关的只有**节点图**条目
（如 #30「节点图资源管理器…含 `道具节点图`」）；**没有**「货币与背包」「商店模板管理」这样的面板条目。
`operation`（44 行）也**没有**建模板命令（§3 交叉印证）。
`userops.db → user_operation`（92 行）里「新建」类操作只有：
`resource.new_folder`（= `beyondInstructionGraphService.create`）与 `bp.new_bp`（= 同一条 `create`）——
**这是编辑器里「新建」的通用机制**（§4），**没有**模板版本。

---

## 3. 后端命令表 `command_route`（38 行逐行）—— 没有任何建模板路由

`sqlite3` 只读读全表（`SELECT * FROM command_route`）。按语义分族：

| 族 | 行数 | 命令 |
|---|---|---|
| 节点图挂载 | 2 | `AddInstructionGraphForEditObj`、`AddInstructionGraphForPrefab` |
| 删除 | 4 | `DeleteComponentForEditObj`、`DeleteComponentForPrefab`、`DeleteEditObj`、`DeletePrefab` |
| 聚焦 | 9 | `Focus*`（Character/Light/LocalBullet/DropGather/BeyondTileMap/Screenshot/Esp/PrefabInstance/EditObj） |
| 改名/标签/阵营/套组/请求 | 8 | `ModifyEditObjName`、`ModifyEditobjTag`、`ModifyFactionForEditObj/Prefab`、`ModifyPrefabName`、`ModifyPrefabTag`、`ModifySuite`、`RequestPrefabInstance` |
| 变更应用 | 1 | `ApplyPrefabInstanceChange` |
| 面板转发 | 1 | `JumpCombatSetting` |
| 导入导出 / 调试日志 | 7 | `DoExport`、`DoImport`、`DeleteDebugLog`、`ImportAllDebugLog`、`ImportDebugLog`、`ImportPerformanceReport`、`RefreshExistDebugLogReport` |
| 无落点（音频/PCG/上行） | 6 | `EndLoadAllDebugLog`、`PlayMusic`、`PlaySoundEffect`、`ModifyPCGInstanceName`、`DeletePCGInstance`、`FocusPCGInstance` |

**判定**：`Add*` 只对**节点图**；`Modify*` 家族**只有** Name/Tag/Faction/Suite；
导入导出是 `.gia` 文件；其余是焦点/删除/调试/音频/PCG。
**没有任何一条**的名字、服务（`service` 列）或分类与「模板 / 货币 / 道具 / 背包 / 商店 / 新建」相关。

> **⚠️ 这条负结论的边界（同 `TEMPLATE-CREATION-MINE.md §1`，不重复展开）**：
> 38 行的命令名来自**前端反编译语料**，而该语料的面（§2）= 节点图/场景实体/导入导出/调试/音频/PCG，
> **本身不含系统菜单的模板面板**。所以严格表述是「**已枚举的命令面里没有**」，
> 而**这个面不含那个面板** ⇒「面板从没被逆向」。二者不可混为「系统不支持」。

---

## 4. 「创建」在编辑器里的**通用机制**（最接近的类比，用于知道「若有会是什么样」）

虽然模板没有创建路径，但编辑器**别的**东西确实会「新建」，其机制可作模板：

### 4.1 机制：1018 命令通道 + `beyondInstructionGraphService.create`

`userops.db → user_operation` 逐字：`resource.new_folder`=「新建文件夹」**会发**
`beyondInstructionGraphService.create`。反编译侧可定位这条派发：

- **命令字面量**：`"create" /* string 76768 */` —— `.runtime/editor-catalog/resolved/mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:12463`
  （构造 1018 报文：服务名 + 命令名 + null 回调 + 参数列表）。
- **服务名解析**：`"beyondInstructionGraphService" /* string 49720 */` ——
  `.runtime/editor-catalog/resolved/gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP.cs:49`。

### 4.2 全部 10 个编辑器服务名（语料里**没有**模板类服务）

`gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP.cs` 是**唯一的服务名槽位表**（另 5 条 `*Services` 字样是 protobuf 生成物，非编辑器服务），逐行：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**7 个 `beyond*` + 3 个 `wpf*` = 10 个服务，没有 `beyondTemplateService` / `beyondShopService` /
`beyondStuffService` / `beyondCurrencyService`。** 这从**通道侧**独立印证：即便有创建命令，也没有服务承载它。

### 4.3 三张枚举表：模板**类型号**确实存在于「数据模型」，但**只读/被引用**

| 文件:行 | 枚举 | 关键项 |
|---|---|---|
| `resolved/lFHetii40EU81IVmn9aC.n9TjVui4v9PFdo3m497f.cs:24,27,28,33` | 资产类型（**编辑器侧**） | `Stuff=19`、`StuffBag=22`、`Currency=23`、`ShopTemplate=28` |
| `resolved/nftmtEi44ZpaT9uR9UgI.u2nWUWi4Ei8tbmQLVnuN.cs:45-48` | 资源组号（**= `.gil field 6` 的 `group`**） | `Currency=3700`、`StuffBag=3800`、`EquipStuffBag=3900`、`ShopTemplate=4000` |
| `resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:36-38` | 实体组件类型 | `BeyondCompTypeStuffBag=33`、`…EquipStuffBag=34`、`…Shop=35` |

- 第二张表与磁盘证据**精确吻合并交叉印证**：`TEMPLATE-STORAGE.md §2.3` 里 `.gil field 6` 的目录条目
  `f3.f5 = {f1:3800, f2:1119879169}`（默认背包）——`3800` 正是这里的 `StuffBag`。
  **⇒ 编译器知道「背包」组号 3800，且磁盘上确有该组的实例。**
- **但「有类型号」≠「有创建路径」**：这三张表都是**比较/映射表**（类型号 ↔ 名字），
  不是**构造器**。语料里没有任何代码从这些类型号「造」出一个新模板。
- **⚠️ 口径陷阱（务必别混）**：官方 ID 类型表（`mhsd6lrx3voe.json:66`）里
  **8=普通道具、10=资源货币、11=道具背包、15=商店模板** 是**另一套编号**（`id>>22` 的高位类型号），
  与上面三张表**都不是同一套**（编辑器的 `Currency=23/3700`、磁盘 `id>>22-256`）。
  「新建一个货币模板」会落在 **`id ∈ 1115684864~1119879167`（type 10）**——
  这正是 `TEMPLATE-STORAGE.md §2.1` 全盘扫描**未找到任何实例**的区间。

---

## 5. 反编译失败集不是藏身之处（排除一个「会不会漏了」的怀疑）

`decomp.log` 尾行：`decompiled: 12375, errors: 2555`。这 **2555** 个失败会不会就是货币面板？
**不会**。逐个看 `.runtime/editor-catalog/decomp/BeyondEditor/_ERR_*.txt`（2555 个），
**唯一**的错误模板是：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


且 `<X>` 一律形如 `A2Vt2U3XJDnhH1ynxVic.UAkrD53XrpAqrDOXUuHf/<>c`、
`GFifhidO9uuliUYZu5.rIrxakxYdpK4luEUmh__FromStreamAsync_d__15`——
即**编译器生成的嵌套闭包类 / 异步状态机**（`<>c`、`__d__15`）。这些是**附属类型**，
其**外层业务类**已成功落在 `resolved/`（例：`A2Vt2U3XJDnhH1ynxVic.UAkrD53XrpAqrDOXUuHf.cs` 在 `resolved/` 里就是成功的）。
**⇒ 2555 个失败里没有独立业务类；货币面板不是被反编译失败吞掉的。**
（`_ERR_*.txt` 里对 `货币|背包|Shop|Currency|StuffBag` 检索 = 0；它们只含异常栈文本。）

**⇒ 结论**：`BeyondEditor.dll`（安装目录里**唯一**的 UGC 托管程序集，17.5 MB；见
`.runtime/editor-catalog/install-inventory.json` 与 `frontend.db → assembly`）**整体被覆盖**，
其中**不含**货币/道具/商店模板面板。

---

## 6. 判决（ranked）

| # | 候选路径 | 证据 | 判定 |
|---|---|---|---|
| 1 | **编辑器 UI 里存在「新建货币/道具/商店」视图模型与命令（在本工程语料内）** | 2805 条字面量 0 命中（§1）；UI 键命名空间无 CURRENCY/ITEM/STUFF/SHOP/BAG（§2）；10 个服务名无模板服务（§4.2）；`feature` 80 行无该面板（§2.2） | **REFUTED（语料内不存在）** |
| 2 | **后端 `command_route` 有建模板路由** | 38 行逐行 `SELECT`，无一条相关（§3） | **REFUTED** |
| 3 | **反编译失败集里藏着该面板** | 2555 个 `_ERR_*.txt` 全是嵌套闭包/状态机，非业务类（§5） | **REFUTED** |
| 4 | **面板与创建命令存在，但位于「系统菜单」这块从未被逆向的前端 UI 中** | 官方逐字有入口（`mhi9s7isvp50.json:50,62` 商店模板管理/新建商店模板；`mh2cr30yeak0`【货币与背包】；`mhbgx0rspbqu` 新建道具按钮）；本工程语料的面**不含**该面板（§2）；`TEMPLATE-CREATION-MINE.md §1` 独立得同向结论 | **PLAUSIBLE — 最可能（唯一未排除的正面路径）** |
| 5 | **创建命令由游戏侧（`YuanShen.exe`）处理，编辑器只是转发** | 编辑器服务名表里**无**模板服务（§4.2）；`command_route`（引擎/游戏侧分发表）里**无**模板命令（§3） | **UNSUPPORTED（两边都无落点）** |
| 6 | **模板只能由「游戏内建编辑器」而非 `BeyondEditor.exe` 创建** | 无直接证据；仅因 `BeyondEditor.dll` 全量覆盖仍无该面板而**不能排除** | **UNDECIDABLE** |

**一句话排序**：**(4) 面板存在但从未被逆向 > (6) 在另一个二进制里 > (5) 编辑器转发 > (1)(2)(3) 已被否**。

---

## 7. 三层分开（不得混称）

| 层 | 结论 |
|---|---|
| **文档写了什么** | 官方有货币(10)/道具(8)/背包(11)/商店(15) 四类**配置 ID**（`mhsd6lrx3voe.json:66`）；入口在**系统菜单**：【背包与货币】/【商店模板管理】，按钮逐字「新建道具」（`mhbgx0rspbqu.json`）/「新建商店模板」（`mhi9s7isvp50.json:62`）。**零执行。** |
| **工具/源码能做什么** | 桥 op 面（计数由 `tools/gameplan/tests/test_doctrine.py` 钉住）无模板；原生 6 动作无模板；`scene_cli` 6 动作无模板；`command_route` 38 行无模板（本轮 SQL 复核）；语料里**无**模板面板/VM/服务（本轮**新增**证据）。**这层是静态枚举。** |
| **真机验证过什么** | **本轮零执行**（除只读查表）。未起助手、未连桥、未发报文、未碰游戏/编辑器、未读写任何存档。 |

---

## 8. 诚实负结论（写明搜了哪里、用什么工具）

| 未找到 | 搜过哪里 / 工具 |
|---|---|
| `resolved/*.cs` 中任何「货币/道具/商店/背包/新建」**中文字面量** | Bash `grep -rIl`（A 段全 0）+ 自建字面量索引（0/2805） |
| 任何 `New*Item/Create*Item/Add*Item/Create*Shop*` 命令字面量 | 同上，0 |
| UI 键命名空间中的货币/道具/商店/背包段 | `textmap-chs.json` 7743 键按前缀分组（`ns_scan.py`），无 |
| 文本含「新建」的货币/道具/商店条目 | 全部含「新建」的 14 条已逐条列出，无一相关 |
| `command_route` 建模板路由 | `sqlite3` 只读读 38 行（§3） |
| 编辑器 10 个服务名里的模板服务 | `gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP.cs:19-78` 逐行 |
| 2555 个反编译失败里的业务类 | `decomp/BeyondEditor/_ERR_*.txt` 逐个（错误模板唯一：`Could not find type definition …/<>c`） |
| 另一个 UGC 程序集 | `install-inventory.json`：UGC 托管程序集**只有** `BeyondEditor.dll`；`Astrolabe.dll` 是原生 PE（`.runtime/verification/native-plugin-interface-audit/strings/Astrolabe.dll.json` 中 `货币/道具/商店/背包/Currency/Shop` 全 0），非编辑器 UI |

**未找到 ≠ 不存在**：以上「没有」均为**本次检索范围内**（编辑器 `BeyondEditor.dll` 反编译语料 + 三张本地化/命令/功能表）。
**「系统菜单（背包与货币 / 商店模板管理）这块前端 UI 从未被逆向」是本轮再次坐实的、唯一可继续推进的洞**
（`TEMPLATE-CREATION-MINE.md §1` 独立得同结论）。
**下一步的正确动作不是再搜命令名**（会继续 0 命中），而是**给这块面板建一份逆向覆盖**
（反射枚举菜单项 / 找它的 XAML 与 VM），读出「新建货币」按钮真正派发的命令名与服务——
再回到 `command_route` / 游戏映像做落点扫描。

---

## 9. 复现命令（全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


> 本轮新增/使用的脚本（均在 `.runtime/scratch/`）：`lit_index.py`、`lit_query.py`、`ns_scan.py`、
> `tm_key_scan.py`、`tm_text_scan.py`、`ui_noun_scan.py`、`tm_menu_scan.py`、`db_scan.py`、`cat_find.py`。
