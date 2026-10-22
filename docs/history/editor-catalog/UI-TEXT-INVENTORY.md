> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 千星编辑器（BeyondAssistEditor）用户可见功能面清单

> 本文只做**离线只读分析**。全部结论来自已解码的 `.mihoyobin` 资源，不含任何对游戏/编辑器进程的操作。
> 证据标记约定：
> - **【键名】** — 有明确键名 + 中文文本直接支持，证据强度最高。
> - **【推断】** — 由文本语义推断出的功能，键名本身不直接命名该功能。
> - **【无证据】** — 在本批资源中找不到任何支持，明确标注为不存在，而非"应该有"。

---

## 一、数据来源与解码方法

### 1.1 源文件

| 项 | 值 |
|---|---|
| 资源根目录 | `C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\Resource`（只读访问） |
| 编码方式 | 单字节 XOR `0xE5`，解出后为 protobuf wire 流 |
| 解码产物 | `.runtime/editor-catalog/decoded/` 共 **4098** 个 JSON（`.runtime/editor-catalog/decode.log`：`files=4098 ok=4098 failed=0`） |
| 索引 | `.runtime/editor-catalog/index.jsonl`（每行一个文件的 `{path,size,ok,strings,top_fields}`） |

目录分布（4098 个文件）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 1.2 本次实际使用的文件与 SHA256

| 文件（相对资源根） | 原始字节 | 原始 SHA256 | 解码后 SHA256 |
|---|---|---|---|
| `Json/TextMap/CHS/17720714722766726369.mihoyobin` | 609,674 | `8e645356af66cc8bd5b57ea874cc4e29717ad48ca34e9a013a14510cdf001518` | `4c2f8f5f426830b9e7c17c802456e1e2c5b162037633464d6638c7f533f969b1` |
| `Json/TextMap/EN/6246370240741975437.mihoyobin` | 621,898 | `33c22e2020059ac2723267be40eee286613dd07ea3f2437bd7f94c247853a882` | `517f8de954f8a7ae19b8af5678b2dab3b23a6c3a77714de141dce84b91ceab14` |
| `Json/Config/JsonConfig/SynonymsLibrary/CHS/2499002102405513862.mihoyobin` | 25,020 | `d6ab0e9ff12a1455d94dfe69b61a9335fef745b6cc3d635d42790404f2ad60a2` | `db45278dbe41c07440451789c2a6efb1ab46fcd1b474892bdd853f5a5f9d4066` |
| `Json/Config/JsonConfig/SynonymsLibrary/EN/10067476053637198150.mihoyobin` | 25,481 | `010120fbe1cd5a859c90764e0e13086daf72db3473ab44adc8a827d73e7f90e` | `a40a2d9fa241a633f5314da134631851358905438c361ec3b476f4374d650c79` |
| `Json/Config/JsonConfig/ShortCutKey/1074106604405081892.mihoyobin` | 4,578 | `161d19ccdebebf2e6c892268e39d8195b35282bbc5f16faa0397a38e51c47f78` | `2d74a0f2f23309fb337ad612e798f30e55cae132a9838511f626d0665faa04ac7e` |

### 1.3 复现命令（只读，不写游戏目录）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 1.4 键值数量（**重要口径更正**）

任务书中的「CHS 10693 条」「同义词 1660 条」是 **index.jsonl 中 `strings` 数组去重后的字符串值个数**，不是条目数。两种口径都列在下面，本文后续一律使用**条目数**：

| 口径 | TextMap CHS | SynonymsLibrary CHS |
|---|---|---|
| protobuf map 条目数（= 键数，键唯一） | **7743** | **372** |
| 其中文本非空的条目 | **6170** | 372 |
| 文本为空的条目 | **1573** | 0 |
| `index.jsonl` 中 `strings` 出现次数 | 13913（= 7743 键 + 6170 文本） | 2506 |
| `index.jsonl` 中 `strings` **去重**后 | 10693 ← 任务书口径 | 1660 ← 任务书口径 |

**TextMap CHS 与 EN 的键集合完全相同**（EN-only = 0，CHS-only = 0），即 15 种语言的 TextMap 是同一套 7743 个键的平行翻译。

**1573 条空文本的构成**（说明"空"不是解码失败，而是该字段在本版本中未填）：

| 来源字段 | 空文本条数 |
|---|---|
| `BeyondEditorInstructionNodeConfig_desc_*` | 798 |
| `..._outPinList_*` | 340 |
| `..._inPinList_*` | 295 |
| `..._inParamList_*` | 70 |
| `..._extraParamList_*` | 61 |
| `BeyondAssistantEditorConfigGlobal_folders_*`（空文件夹名） | 6 |
| `..._outParamList_*` | 1 |
| 其他（2 个占位） | 2 |
| **合计** | **1573** |

> 解码数据结构（供复核）：顶层 `fields` 是 protobuf wire 项列表；TextMap 的每条词条为
> `{"f":2,"w":2,"m":[{"f":1,"s":"<键名>"},{"f":2,"v":<uint32 哈希>},{"f":3,"s":"<文本>"}]}`。
> `f:3` 缺失即文本为空。同义词库为 `{"f":2,...,"m":[{"f":1,"m":[{"f":1,"s":"<官方术语>"}]},{"f":2,"s":"<别名>"}...]}`。

### 1.5 本文档与既有文档的关系

`docs/offline-research/RESOURCE-MAP.md` 第 18 行记有「`Json/TextMap` … 内容封装未解码，**不能当明文词典**」。该判断在解码完成后**已失效**——本批 15 个 TextMap 已全部解出为明文键值。本文档为 TextMap / SynonymsLibrary / ShortCutKey 三个配置的**逐键清点**，与 `RESOURCE-MAP.md` 的资产级盘点互补，不替代它。

---

## 二、按前缀分组的键值统计表

### 2.1 一级前缀（合计数 = 7743，无遗漏）

| 前缀（首个 `_` 前） | 条数 | 占比 | 性质 |
|---|---|---|---|
| `BeyondEditorInstructionNodeConfig` | **5667** | 73.2% | 节点图**指令库**（节点/引脚/参数的显示名） |
| `BeyondAssistantEditorConfigGlobal` | **1082** | 14.0% | 编辑器全局配置：枚举字典、蓝图分类目录、标签搜索、类型提示 |
| `UI_BEYOND` | **934** | 12.1% | 面向用户的**界面文本**（面板/按钮/菜单/提示） |
| `BEYOND_EDITOR` | **59** | 0.8% | 快捷键条目名 |
| `UI_SETTING` | **1** | 0.0% | 手柄光标灵敏度 |
| **合计** | **7743** | 100% | |

### 2.2 `BeyondEditorInstructionNodeConfig` 内部字段分布（5667）

| 字段 | 条数 | 非空 | 说明 |
|---|---|---|---|
| `inParamList_*` | 2409 | 2339 | 节点**入参**显示名 |
| `outParamList_*` | 886 | 885 | 节点**出参**显示名 |
| `name_*` | 800 | **800** | **节点显示名（全部有效）** |
| `desc_*` | 800 | **2** | 节点描述（本版本几乎全空，仅 `desc_946`/`desc_947` = 「需要角色挂载【监听移动速率】单位状态效果」） |
| `outPinList_*` | 410 | 70 | 出引脚显示名 |
| `inPinList_*` | 298 | 3 | 入引脚显示名 |
| `extraParamList_*` | 64 | 3 | 额外参数显示名 |

### 2.3 `BeyondAssistantEditorConfigGlobal` 内部（1082）

| 字段 | 条数 | 说明 |
|---|---|---|
| `configEnum_maps_*` | 589 | **102 个枚举类型**（`_mapTitle`）+ 487 个枚举成员显示名 |
| `folders_*` | 478 | **13 个顶层蓝图分类**（`folders_0`–`folders_12`）及其多级子目录名 |
| `configTagSearchList_*` | 12 | 标签检索词条（已见：物件、EffNonLoop、EffLoop、UICustomLayout、CameraTemplate、DummyPoint、CountDownTimer、UIModule、UIWidget、UIMW） |
| `typeHints_*` | 3 | 输入整数 / 输入浮点数 / 输入字符串 |

### 2.4 `UI_BEYOND` 内部（934）

| 二级 | 条数 | 对应界面 |
|---|---|---|
| `UI_BEYOND_ASSIST_EDITOR_*` | **357** | 千星沙箱主窗口（资源管理器/节点图/信号/日志等） |
| `UI_BEYOND_EDITOR_*` | **490** | 编辑器侧工具（特效器/环境/编辑工具/历史/光标…） |
| `UI_BEYOND_LOG_*` | 63 | 日志面板 + 节点图调试工具 + 负载检测 |
| `UI_BEYOND_GENERAL_*` | 12 | 通用原子词（元件ID/配置ID/序号/GUID/字数上限…） |
| `UI_BEYOND_COSTLOAD_*` | 12 | 服务端性能超限**整改建议**长文案 |

`UI_BEYOND_EDITOR_*`（490）细分：

| 三级 | 条数 | 界面 |
|---|---|---|
| `VFXEDITOR_*` | 172 | 特效器编辑器 |
| `ESP_*` / `ESP2_*` | 171 + 2 | 环境配置（含光源管理、天气、背景） |
| `PROTOTYPE_*` | 85 | 编辑工具（阵列/对称/测距线/备注/复制粘贴） |
| `WPF_*` | 26 | 历史记录（25）+ 帮助（1） |
| `UI_*` | 21 | 玩家光标配置（15）、造物状态蓝图调试日志（5）、光标碰撞盒（1） |
| `CURSOR_*` | 5 | 光标碰撞盒组件 |
| `SUITE_*` | 3 | 实体布设组 |
| `COSTLOAD_*` | 2 | 负载悬浮提示 |
| `TAG_*` / `COMPOMENT_*` / `ATTACKTAG_*` | 1+1+1 | 单位标签 / 光标碰撞体 / 标签数量上限 |

`UI_BEYOND_ASSIST_EDITOR_*`（357）细分（前 17 组）：

| 子域 | 条数 | 子域 | 条数 |
|---|---|---|---|
| `COSTLOAD_*` | 68 | `BP_*` | 16 |
| `DEFAULT_*`（资源管理器默认页签） | 60 | `RESOURCE_*` | 9 |
| `SIGNAL_*`（信号管理器） | 39 | `NODE_*` | 9 |
| `VAR_*`（变量类型名） | 30 | `SCALE_*` | 6 |
| `BLUEPRINT_*` | 26 | `EXTERNAL_*` | 6 |
| `CLIENT_*` | 21 | `ARMY_*`（阵营） | 6 |
| `COMPOSITE_*`（复合节点） | 21 | `DISCONNECT_*` | 4 |
| `ADVANCED_*`（结构体/字典） | 20 | `SEARCH_*` | 3 |

`BEYOND_EDITOR_*`（59）：全部为 `BEYOND_EDITOR_SHORTCUT_KEY_*`，即**快捷键条目的名称与按键显示名**（含 `TOOL_Ctrl`/`TOOL_Z`/`TOOL_Y` 等按键字面量、以及 `Home`/`End`/`←`/`→` 等键帽文本）。

---

## 三、按功能域的功能清单（每项附原始键名证据）

### 3.1 编辑器外壳与窗口

| 功能 | 证据键名 → 中文 |
|---|---|
| 主窗口「千星沙箱」 | **【键名】** `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_WINDOW_TITLE` → 千星沙箱 |
| 窗口菜单 | **【键名】** `..._BLUEPRINT_MANAGER_TITLE_MENU` → 窗口 |
| 帮助 / 快捷键入口 / 帮助手册 | **【键名】** `UI_BEYOND_EDITOR_WPF_HELP_ENTRANCE` → 帮助；`..._INSTRUCTION_MANUAL` → 帮助；`BEYOND_EDITOR_SHORTCUT_KEY_TOOL_ENTRANCE` → 查看快捷键 |
| 保存 / 撤销 / 还原 / 另存为 | **【键名】** `..._BLUEPRINT_SAVE` → 保存；`..._BLUEPRINT_UNDO` → 撤销；`..._BLUEPRINT_REDO` → 还原；`..._BLUEPRINT_SAVE_AS` → 另存为 |
| 另存为对话框 | **【键名】** `..._BLUEPRINT_SAVE_AS_TITLE` → 节点图另存为；`..._SAVE_AS_NEW_NAME` → 新节点图名称；`..._SAVE_AS_NEW_TAB` → 新节点图页签；`..._BLUEPRINT_SAVE_SUCCESS` → 保存成功 |
| 卸载/重启异常提示 | **【键名】** `..._WPF_WAITING_WARNING` → 请等待或重启千星沙箱后重试 |

### 3.2 资源管理器（资产库）

这是文本量最大的可见面板（`UI_BEYOND_ASSIST_EDITOR_DEFAULT_*` 60 条 + `RESOURCE_*` 9 条）。

| 功能 | 证据键名 → 中文 |
|---|---|
| 面板本体 | **【键名】** `..._RESOURCE_MANAGER_WINDOW_TITLE` → 资源管理器 |
| 页签 | **【键名】** `..._RESOURCE_MANAGER_OFFICIAL_TAB` → 预制分类；`..._CUSTOM_TAB` → 自定义分类；`..._DEFAULT_TABS` → 默认页签；`..._DEFAULT_UNCLASSIFIED_TAB` → 未分类页签；`..._DEFAULT_IMPORT_ASSET_TAB` → 导入资产页签 |
| 编辑空间 | **【键名】** `..._RESOURCE_MANAGER_INSTANCE_EDIT_SCENE` → 场景编辑空间；`..._PREFAB_EDIT_SCENE` → 元件库编辑场景 |
| 资产栏 | **【键名】** `..._RESOURCE_MANAGER_PREFAB_RESOURCE` → 元件库资产栏 |
| 资产种类 | **【键名】** `..._RESOURCE_MANAGER_INSTANCE` → 实体；`..._CUSTOM_PREFAB` → 自定义元件；`..._CUSTOM_MONSTER` → 自定义造物 |
| 筛选条件（8 类） | **【键名】** `..._DEFAULT_FILTER_FOLDER` → 文件夹；`_DYNAMIC_INSTANCE` → 动态单位；`_STATIC_INSTANCE` → 静态单位；`_DYNAMIC_PREFAB` → 动态元件；`_STATIC_PREFAB` → 静态元件；`_SUITE` → **地形**；`_MONSTER` → 造物；`_BP_TYPE` → 节点图；`_NODE_TYPE` → 节点 |
| 列表列头 | **【键名】** `..._DEFAULT_TITLE_NAME` → 名称；`_CATAGORY` → 类型；`_QUOTE` → 引用；`_LOAD` → 负载；`_CAMP` → 阵营；`_EDIT_TIME` → 修改时间 |
| 右键菜单 | **【键名】** 新建文件夹 / 展开 / 折叠 / 打开 / 在局内查看 / 重命名 / 删除 / 查看引用关系 / 应用 / 剪切文件夹 / 删除文件夹 / 排序 / 名称 / 类型 / 阵营 / 引用关系 / 递增 / 递减 / 引用关系详情 / 已挂载节点图（`..._DEFAULT_RIGHT_MENU_*`） |
| 新建节点图（含分型） | **【键名】** `..._RIGHT_MENU_NEW_BP` → 创建节点图；`_NEW_SERVER_BP` → 新建节点图；`_NEW_FILTER_BP` → 新建过滤器节点图；`_NEW_SKILL_BP` → 新建技能节点图 |
| 导入 / 导出 | **【键名】** `..._RIGHT_MENU_EXPORT` → 导出；`..._RIGHT_MENU_IMPORT` → 导入；`..._RIGHT_MENU_COPY_BP_ID` → 复制节点图ID |
| 空态与搜索 | **【键名】** `..._DEFAULT_CURRENT_CATALOG_EMPTY` → 当前目录为空；`..._DEFAULT_NO_SEARCH_RESULTS` → 没有符合条件的搜索结果；`..._SEARCH_TIPS` → 在“{0}”中搜索 |
| 批量/移动操作 | **【键名】** `..._DEFAULT_MOVE_TO` → 移动到：{0}；`_JUMP_TO` → 跳转至：{0}；`_DISCONNECT_TO` → 断开至：{0} |

> **【推断】** 「地形」以 `DEFAULT_FILTER_SUITE` → 地形 的形式出现在**筛选条件**中，说明资源管理器可按地形类资产筛选；但地形编辑面板本身的文本不在本 TextMap 内（见 3.10）。

### 3.3 节点图编辑器

| 功能 | 证据键名 → 中文 |
|---|---|
| 节点图管理（两大类） | **【键名】** `..._BLUEPRINT_MANAGER_SERVER_BP_MANAGER` → 服务器节点图资源管理器；`..._CLIENT_BP_MANAGER` → 客户端节点图资源管理器 |
| 节点图分型 | **【键名】** `..._BLUEPRINT_MANAGER_INSTANCE_BP` → 实体节点图；`_ROLESTATUS_BP` → 状态节点图；`_DUTY_BP` → 职业节点图；`_STUFF_BP` → 道具节点图；`..._BLUEPRINT_MANAGER_DROP_OFFICIAL` → 掉落物；`_DROP_CUSTOM` → 自定义掉落物 |
| 客户端节点图分型 | **【键名】** `..._CLIENT_BLUEPRINT_MANAGER_FILTER_BP` → 本地过滤器节点图；`_SKILL_BP` → 技能节点图；`..._CLIENT_BLUEPRINT_AVATAR_SKILL` → 角色技能节点图；`..._MONSTER_SKILL` → 造物技能节点图；`..._MONSTER_POSE` → 造物状态节点图；`..._MONSTER_AI` → 造物状态决策节点图；`..._CLIENT_BLUEPRINT_CONTROL` → 角色操控技能节点图；`..._BOOL_FILTER_BP` → 布尔过滤器节点图；`..._INT_FILTER_BP` → 整数过滤器节点图 |
| 新建各分型（`_NEW` 后缀成对存在） | **【键名】** `..._MONSTER_SKILL_NEW` → 新建造物技能节点图；`_MONSTER_POSE_NEW`；`_MONSTER_AI_NEW`；`_AVATAR_SKILL_NEW`；`_CONTROL_NEW` |
| 编辑器模式标识 | **【键名】** `..._SERVER_BP_EDITING` → 服务器节点图编辑；`..._CLIENT_BP_EDITING` → 客户端节点图编辑 |
| 节点库 | **【键名】** `..._NODE_LIBRARY` → 节点库；`..._NODE_SEARCHING` → 节点搜索；`..._SEARCH_NODE_TIPS` → 节点ID：{0} |
| 节点管理器 | **【键名】** `..._BLUEPRINT_MANAGER_NODE_MANAGER` → 节点管理器；`..._NODE_MANAGER_COMPOSITE_NODE` → 复合节点；`_NEW_COMPOSITE_NODE` → 创建复合节点；`_TOP_UP` → 置顶；`_CANCEL_TOP_UP` → 取消置顶；`_IMPORT_NODE` → 节点外部资产 |
| 节点操作 | **【键名】** `..._NODE_CUT` → 剪切；`..._NODE_DUPLICATE` → 复制；`..._ADD_PINS` → 添加引脚；`..._DISCONNECT_NODE` → 断开节点连线；`..._DISCONNECT_ALL_CONNECTION` → 断开全部连线；`..._DISCONNECT_TO_NEXT_CONNECTION` → 断开到下个节点连线 |
| 注释 | **【键名】** `..._BP_ANNOTATION` → 注释；`..._BP_ENTER_ANNOTATION` → 输入注释 |
| 复合节点 | **【键名】** `..._GENERATE_COMPOSITE_NODE` → 生成复合节点；`..._EXPAND_COMPOSITE_NODE` → 展开复合节点；`..._EDIT_COMPOSITE_NODE` → 复合节点编辑；`_COMPOSITE_SAVE_NODE` → 保存复合节点修改；`_COMPOSITE_SAVE_CHECK_A` → 是否确认修改复合节点数据；`_COMPOSITE_SAVE_CHECK_B` → 确认后所有的引用也将被修改；`_COMPOSITE_PIN_MERGE` → 合并引脚；`_COMPOSITE_SET_AS_PIN` → 设为复合节点引脚；`_COMPOSITE_CANCEL_PIN` → 取消在复合节点上显示 |
| 节点图变量 | **【键名】** `..._BP_VARIABLES` → 节点图变量；`_BP_VAR_NUM` → {0}个变量；`_BP_VAR_CREATE` → 新增变量；`_BP_VAR_DELETE` → 删除变量；`_BP_VAR_DUPLICATE` → 复制变量；`_BP_VAR_PASTE` → 粘贴变量；`_BP_VAR_RESET` → 重置变量；`_BP_VAR_BATCH_DELETE` → 批量删除；`_BP_VAR_SET_PUBLIC` → 将{0}设置为公开，可在局内编辑；`_BP_VAR_SET_PRIVATE` → 将{0}设置为私有，不可在局内编辑；`_BP_VAR_MAX_WARNING` → 节点图变量数量已达上限 |
| **变量/数据类型（20 种）** | **【键名】** `..._VAR_TYPE_*` → 字符串 / 字符串列表 / 整数 / 整数列表 / 浮点数 / 浮点数列表 / 布尔值 / 布尔值列表 / 三维向量 / 三维向量列表 / 实体 / 实体列表 / GUID / GUID列表 / 元件ID / 配置ID / 元件ID列表 / 配置ID列表 / 枚举 / 枚举列表 / 局部变量 / 阵营 / 阵营列表 / 泛型 / 组件类型 / 目录类型 |
| 高级数据结构 | **【键名】** `..._ADVANCED_DATA_STRUCT` → 结构体；`_DICT` → 字典；`_DICT_KEY_TYPE` → 键类型；`_DICT_VALUE_TYPE` → 值类型；`_DICT_RESET` → 还原为泛型；`_STRUCT_EDIT_TARGET` → 修改对象；`_PASTE_WARNING` → 数据结构不匹配，不可粘贴；`_ILLEGAL_WORDS` → 名称中包含非法单词；`_QUICK_EDIT` → 快捷编辑；`_RESET_DEFAULT` → 还原为默认数据；`_STRUCT_ADD_WARNING` → 字典键类型为实体，无法添加；`_KEY_WARNING` → 字典键重复 |
| 画布缩放 | **【键名】** `..._SCALE_200/150/100/50` → 200%/150%/100%/50%；`_SCALE_ENLARGE` → 放大；`_SCALE_REDUCE` → 缩小 |
| 跳转与筛选 | **【键名】** `..._JUMP_TO_NEXT_NODE` → 跳转到下个节点；`..._DEFAULT_CONNECTABLE_NODE` → 可连接节点；`_FILTER_EXECUTABLE_NODE` → 筛选-可执行节点；`_FILTER_PROVIDED_NODE` → 筛选-提供{0}的节点；`_FILTER_REFERENCED_NODE` → 筛选-引用{0}的节点；`_FILTER_NODES_BY_RULES` → 按照规则筛选节点列表 |
| 阵营选择 | **【键名】** `..._ARMY_CHANGE_ARMY` → 更改阵营；`_ARMY_SELECT_ARMY` → 在以下阵营中选择；`_ARMY_FOLLOW_DEFAULT_ARMY` → 跟随默认阵营配置 |

### 3.4 历史记录（撤销/还原的可见载体）

**【键名】** `UI_BEYOND_EDITOR_WPF_HISTORY_*`（25 条）逐条给出可撤销的操作类型：

`_TITLE` → 历史记录({0}/{1})；`_SUBTITLE` → 历史记录；`_NEW` → 起始；
`NODE_NEW` → 新建节点: {0}；`NODE_EDIT` → 修改节点: {0}；`NODE_MOVE` → 移动节点: {0}；`NODE_DELETE` → 删除节点: {0}；
`NODE_DELETE_PLURAL` → 批量删除节点；`NODE_MOVE_PLURAL` → 批量移动节点；`NODE_EDIT_PLURAL` → 批量编辑节点；
`LINK_NEW` → 连接引脚；`LINK_DELETE` → 断开引脚连线；`LINK_DELETEALL` → 断开节点连线: {0}；
`CV_NEW/CV_EDIT/CV_DELETE` → 新建/修改/删除节点图变量；
`COMPOUNDNODES_NEW/DELETE/OPEN/EDIT` → 生成/删除/展开/编辑复合节点；
`MENTION_NEW/EDIT/DELETE` → 新建/修改/删除注释；
`PASTE` → 粘贴；`CUT` → 剪切。

### 3.5 日志与节点图调试工具

| 功能 | 证据键名 → 中文 |
|---|---|
| 日志面板 | **【键名】** `UI_BEYOND_LOG_TITLE` → 日志；`_LOGTITLE` → 日志信息；`_TIME` → 时间；`_NOLOG` → 暂无日志；`_CLEAR` → 清空；`_ACTIVE` → 生效；`_LOGLIST` → 日志列表{0}/{1} |
| 日志文件管理 | **【键名】** `_NAME_LOGNAME` → 日志_{0}_玩家_{1}；`_NAME_MULTILOG` → 多个日志文件；`_LOGCTRL_DISPLAY` → 显示日志；`_LOGCTRL_DELETE` → 删除日志；`_LOGCTRL_UNDISPLAY` → 关闭显示；`_BPDEBUG_IMPORTLOG` → 导入日志 |
| 日志筛选器 | **【键名】** `_FILTER_SELECTOBJECTS` → 选择单位；`_FILTER_SEARCH` → 搜索；`_FILTER_SELECTED` → 已选择{0}/10项；`_FILTER_CONFIRMSELECTION` → 确认选择；`_FILTER_NORESULT` → 无相关搜索结果；`_FILTER_BYTIME` → 按时间范围筛选；`_FILTER_BYTIME_ALL` → 全部时间；`_FILTER_STATUS_NORMAL/WARNING/ERROR` → 正常节点图 / 包含警告的节点图 / 包含错误的节点图；`_FILTER_SELECTALLSTATUS` → 警告状态 |
| 日志事件语义 | **【键名】** `_LEVELBEGIN` → 关卡开始；`_LEVELEND` → 关卡结束；`_SEVERALACTIONS` → 发生{0}个事件；`_SEVERALENTITYS` → 多个物件 |
| **节点图调试工具** | **【键名】** `_BLUEPRINT_DEBUGTITLE` → 节点图调试工具；`_BLUEPRINT_DEBUGNAME` → 调试台；`_BLUEPRINT_ACTIVATEDMETHOD` / `_BPDEBUG_MAINTITLENAME` → 生效逻辑树{0}；`_BLUEPRINT_DATAINFOS` → 数据详情；`_BLUEPRINT_INPUT` → 输入；`_BLUEPRINT_OUTPUT` → 输出；`_BLUEPRINT_SEVERALINPUT` → 第{0}次输入；`_BLUEPRINT_SEVERALOUTPUT` → 第{0}输出；`_BLUEPRINT_CHECKALLDATA` → 点击查看全部数据信息；`_BLUEPRINT_EXIT` → 退出 |
| 调试模式只读限制 | **【键名】** `_BLUEPRINT_DEBUGTIPS` → 当前调试模式下无法修改节点图，仅可查看运行中传输的数据；`_TIPS_BPDEBUGONLYFORREVIEW` → 关卡运行状态下无法修改节点图，仅可查看；`_TIPS_DEBUG` → 关卡运行状态下无法修改数据 |
| 调试台警告/错误分级 | **【键名】** `_BPDEBUG_TITLE_WARNING` → 警告；`_BPDEBUG_TITLE_ERROR` → 错误 |
| 蓝图类型区分 | **【键名】** `_TITLE_SERVERBP` → 服务器节点图；`_TITLE_CLIENTBP` → 客户端节点图；`_TITLE_CLIENTBPTITLE` → 客户端节点图生效；`_BPDEBUG_SUBTITLENAME` → 服务器节点图编辑 |
| 上限提示 | **【键名】** `_TIPS_SERVERBPOVERLIMITS` → 可添加服务端节点图达到上限；`_TIPS_CLIENTBPOVERLIMITS` → 可添加客户端节点图达到上限；`_TIPS_DISPLAYLOGOVERLIMITS` → 可添加数量达到上限；`_TIPS_UNMATCHLOG` → 日志文件与当前存档不符 |

### 3.6 负载检测与性能诊断（`COSTLOAD`，共 68+12+7 条）

| 功能 | 证据键名 → 中文 |
|---|---|
| 面板入口 | **【键名】** `UI_BEYOND_ASSIST_EDITOR_COSTLOAD_BTN_ENTER` → 负载检测；`_BTN_CTRL` → 开启负载测试 |
| 开关确认对话框 | **【键名】** `_TIPS_PERFORMCOST` → 是否开启负载测试？开启后可检测试玩过程中的负载情况\n注意：开启负载检测将会导致额外的负载消耗 |
| 未开启时的空态 | **【键名】** `_NONEFORPROCESS_TITLE` → 负载检测未开启；`_NONEFORPROCESS_TEXT` → 动态负载检测需要在开启负载测试的情况下进行试玩；`_NONEFORLOG_TITLE` → 暂无日志；`_NONEFORLOG_TEXT` → 需进行试玩以获得动态负载数据 |
| **试玩中**面板 | **【键名】** `_TESTING_TITLE` → 试玩进行中；`_TESTING_SUBTITLE` → 当前负载状态 |
| 四项被监测指标 | **【键名】** 计算负载（客户端）/ 内存负载（客户端）/ 处理器（服务器）/ 内存负载（服务器） —— `_TESTING_DISPLAYPERFORM`/`_MEMORY`/`_SERVERCPU`/`_SERVERMEMORY` |
| 异常清单 | **【键名】** 计算负载异常（客户端）/ 内存负载异常（客户端）/ 处理器异常（服务器）/ 内存负载异常（服务器） —— `_TITLE_*`；`_TL_TITLE` → 异常时刻列表；`_TLDETAILS_LINECHART` → 前后5秒内负载变化图；`_TLDETAILS_PICS` → 异常时刻截图 |
| 按内容归因分类 | **【键名】** `_TLDETAILS_ENTITY` → 实体；`_ESP` → 环境；`_AVATAR` → 角色；`_SYSTEM` → 其他；`_FILTER_TITLE` → 筛选条件；`_DETAILS_TYPE_RUNTIMEENTITY` → 动态实体；`_TYPE_ENTITY` → 静态实体；`_TYPE_EFFECT` → 特效；`_TYPE_TILEMAP` → **地形**；`_TYPE_AVATAR` → 角色 |
| 详情表列头 | **【键名】** 名称/类型/ID/负载/负载占比/操作/负载详情/所属实体（`_DETAILS_TITLEBAR_*`） |
| 时刻对比 | **【键名】** `_TIMEDIFF_NONE` → 无对比时刻；`_TIMEDIFF_TARGET` → 与{0}对比 |
| **服务端超限规则名（14 条）** | **【键名】** 负载超载；节点图内运行节点数量超过限制；节点图执行时间超过限制；节点图一次执行事件超过限制；处理器负载消耗超过限制；已延迟执行次数过多；沙盒时间超过限制；内存负载超载（`_SERVER_*` / `_SERVERMEMORY_*`） |
| 每条规则的整改建议 | **【键名】** `_SERVER_RECOMMODATIONS` → 建议；`UI_BEYOND_COSTLOAD_SERVERMEMORY_PERFORMANCE_LIMIT_*`（12 条长文案，例：`_LIMIT_ENTITY_COUNT` → 「关卡运行时，实体的上限为1000，当前关卡已经超过限制。请合理调整节点图创建和移除实体的节奏…」） |
| 指标释义悬浮提示 | **【键名】** `_LOG_HOVERTIPS_TITLE` → 提示；`_LOG_HOVERTIPS_TEXT` → 该值代表节点图在本次运算过程中，所消耗的服务器处理器负载值，即：窗口期时间。单位为：毫秒； |
| 悬浮提示（编辑器侧） | **【键名】** `UI_BEYOND_EDITOR_COSTLOAD_STATIC_HOVER_TIPS_MEMORYPERFORM` → 内存负载为区域内的内存相关的负载指标，如贴图，模型，动画，特效等…临近负载上限：{0}处 |
| 存档维度 | **【键名】** `UI_BEYOND_EDITOR_COSTLOAD_STATIC_POPWINDOW_OVERALL_TOTALARCHIVE` → 存档 |
| 健康态 | **【键名】** `UI_BEYOND_COSTLOAD_SERVERMEMORY_PERFORMANCE_LIMIT_NONE` → 关卡运行状态良好，请继续保持 |

### 3.7 关卡环境配置（ESP，共 173 条）

| 功能 | 证据键名 → 中文 |
|---|---|
| 面板与页签 | **【键名】** `UI_BEYOND_EDITOR_ESP_PROFILE_TAB_TABNAME` → 环境配置；`_TAB_DEFAULTTAB` → 默认 |
| 环境配置管理 | **【键名】** `_NEWPROFILE` → 新建环境；`_NEW_TITLE` → 新建环境配置；`_NEW_NAME` → 环境配置名称；`_NEW_TYPE` → 环境配置所属分类；`_NEW_CONFIRM` → 确认；`_SAVEAS` → 另存为；`_RIGHTKEY_RENAME` → 重命名；`_TIPS_DELETETIPS` → 是否删除{0}？\n删除后当前存档的环境配置引用将丢失；`_APPLYTO` → 生效目标；`_SELECTPLAYER` → 选择玩家 |
| 背景/天空 | **【键名】** `_TITLE_STYLE` → 背景设置；`_STYLE` → 背景预设；`_BYTIME` → 随时间自动切换；`_TIMESETTINGS` → 设定时间点；`_ROTATION` → 背景旋转；`_ANGLE` → 直射角；`_INTENSITY` → 强度；`_AMBIGUITY` → 模糊程度；`_LIGHTCOLOR` → 受光颜色；`_SHADOWCOLOR` → 阴影颜色；`_FILTER` → 滤镜风格；`_SKYCOLOR` → 天空背景色 |
| 环境要素 | **【键名】** `_ELEMENT` → 环境要素；`_STAR` → 星星（`_DENSITY` 密度 / `_STRENGTH` 强度）；`_GALAXY` → 银河（`_STRENGTH` / `_COLOR`）；`_CLOUD` → 云（`_STRENGTH` / `_TYPE` / `_HIGH` 高云 / `_MID` 中云 / `_LOW` 低云 / `_ALL` 全部） |
| 滤镜预设名 | **【键名】** `_LUTNAME_*` → 黑白 / 紫色 / 黄色 / 蓝色 / 青色 / 红色 / 默认；`_PRESETNAME_*` → 正常 / 紫色 / 绿色 / 红色 / 蓝色 |
| 时间设置 | **【键名】** `UI_BEYOND_EDITOR_ESP_TIME_TITLE` → 时间设置；`_INITIME` → 关卡初始时间点；`_TIMERATE` → 每秒流逝时间（分钟） |
| 天气配置 | **【键名】** `_WEATHER` → 天气配置；`_WEATHER_INI` → 初始生效天气；`_WEATHER_LIST` → 天气列表；`_WEATHER_DETAILS` → 详情编辑；`_WEATHEREDIT_TITLE` → 天气配置；`_WEATHEREDIT_TYPE` → 天气类型；`_WEATHEREDIT_INISWITCH` → 初始生效 |
| 距离雾 | **【键名】** `_WEATHEREDIT_DISFOG_SETTINGS` → 距离雾设置；`_SWITCH` → 启用距离雾；`_COLOR` → 颜色；`_PT1DIS` → 近雾点距离(m)；`_PT1INTENSITY` → 近雾点浓度；`_PT2DIS` → 远雾点距离(m)；`_PT2INTENSITY` → 天空受雾浓度 |
| 高度雾 | **【键名】** `_WEATHEREDIT_AVATARFOG_SETTINGS` → 高度雾设置；`_SWITCH` → 启用高度雾；`_Y` → 雾气高度(m)；`_RANGE` → 范围；`_ATTENUATION` → 范围衰减；`_ATTENUATIONLOC` → 雾气衰减距离(m)；`_SHELD` → 雾气起始距离(m)；`_AVATAR` → 预览效果 |
| 名称校验 | **【键名】** `_WEATHEREDIT_NAME_NONETYPE` → 名称不合法；`_DUPLICATION` → 名称重名；`_OVERLIMIT` → 名称超出最大字数 |
| 光源管理 | **【键名】** `_LIGHTING_TITLE` / `_ESCNAME` → 光源管理；`_LIGHTING_NAME` → 光源；`_NEW` → 新建光源；`_UNDERPROFILE` → 归属文件；`_PTLIGHT` → 点光源；`_SPOTLIGHT` → 聚光灯；`_RANGE` → 范围/半径；`_SPOTANGLE` → 角度；`_INTENSITY` → 强度；`_CREATEOVERLIMITS` → 创建环境光源数量到达上限；`_SORTBYNAME` → 按名称排序 |
| 光源属性分组 | **【键名】** `_SUBTITLE_PARAMETER` → 基础属性；`_LOCATION` → 位置；`_ROTATION` → 旋转；`_LIGHTSETS` → 光源设置；`_LIGHTTYPE` → 光源类型；`_ACTIVATEAREA` → 生效范围；`_PREVIEWAREA` → 生效范围预览 |
| 挂接点 | **【键名】** `_LIGHTCAMP_ATTCHPT_TITLE` → 挂接点；`_ATTCHPT_LOCATION` → 偏移；`_ATTCHPT_ROTATION` → 旋转 |
| 光源初始态 | **【键名】** `_LIGHTCAMP_INILIGHTS` → 初始生效光源；`_LIGHTCAMP_INISWITCH` → 初始生效；`_LIGHTCAMP_ADDLIGHT` → 添加光源 |
| 环境设置入口 | **【键名】** `_LIGHTING_LEVELSETTING_NAME` → 环境设置；`_PROFILE` → 读取配置文件；`_ESP` → 背景；`_LIGHTS` → 灯光列表；`_WEATHER` → 天气 |
| 使用范围限制 | **【键名】** `UI_BEYOND_EDITOR_ESP_TIPS_ONLYFORENTITYANDENVIROEDITMODE` → **只能在实体摆放页签或地形编辑页签使用** |
| 其它 | **【键名】** `UI_BEYOND_EDITOR_ESP2_SHADOWCOLOR` → 环境颜色；`UI_BEYOND_EDITOR_ESP2_TIP1` → 不影响特效默认音效的播放速度 |

### 3.8 特效器编辑器（VFXEDITOR，共 172 条）

| 功能 | 证据键名 → 中文 |
|---|---|
| 特效器资产 | **【键名】** `_COMP_ASSETTITLE` → 特效器；`_JUMPTOEDITOR` → 前往特效器编辑；`_NEWVFXEDITOR` / `_NEWVFXEDITOR` → 新建特效器；`_NEW_MTITE` → 添加特效器；`_SUBTITLE1` → 新建特效器名称；`_SUBTITLE2` → 新建特效器分类；`_CONFIRM` → 确认创建 |
| 特效器类型 | **【键名】** `_INSPECTOR_TYPE` → 特效器类型；`_INSPECTOR_FIRE` / `_EDITOR_TYPE_FIRE` → **限时特效器**；`_INSPECTOR_CONTINUOUS` / `_EDITOR_TYPE_CONTINUOUS` → **持续特效器**；`_INSPECTOR_DURATION` → 持续时长；`_INSPECTOR_NOTE` → 特效器备注 |
| 资产引用 | **【键名】** `_INSPECTOR_ASSETLIST` → 资产引用；`_INSPECTOR_VFXASSET` → 特效列表{0}；`_INSPECTOR_SOUNDASSET` → 音效列表{0}；`_SUBASSETSICON` → 引用特效资产图标；`_ASSETSICON` → 特效资产图标库；`_EDITOR_WARNNINGVFXASSET` → 预警特效库；`_EX4_ASEET` → 特效库 |
| 轨道编辑 | **【键名】** `_EDITOR_MAINTITLE` → 特效器编辑；`_EDITOR_TRACKSETTINGS` → 轨道设置；`_EDITOR_EDITINGPERIOD` → 当前编辑时间段；`_EX3_NEW` → 新建轨道；`_EX3_DELETE` → 删除轨道；`_EX3_BLOCK` → 屏蔽轨道；`_EX3_UNBLOCK` → 激活轨道；`_EX3_HIDE` → 隐藏轨道；`_EX4_ADDTRACK` → 新建普通轨道；`_EX4_ADDLOOPTRACK` → 新建循环节轨道；`_EX3_DEFAULTTRACK` → 普通轨道；`_EX3_LOOPSETTINGS` → 循环节轨道 |
| 事件与右键菜单 | **【键名】** `_EDITOR_TRACK_EVENTLIST` → 打开事件列表；`_EX3_HIERACHY` → 事件管理；`_EX3_NONE` → 暂无事件；`_RIGHTKEY_ADDEVENT` → 从蓝线处添加事件；`_ADDSOUND` → 音效；`_COPYEVENT` → 复制事件；`_PASTEEVNET` → 粘贴事件；`_DELETEEVENT` → 删除事件；`_ADDLOOP` → 从蓝线处开启循环节；`_ENDLOOP` → 从蓝线处终止循环节；`_EDITOR_TRACK_COPYDATA` → 复制所有轨道数据；`_PASTEDATA` → 粘贴所有轨道数据 |
| 节点类型 | **【键名】** `_EDITOR_NODE_VFX` → 特效播放；`_EDITOR_NODE_SOUND` → 音效播放 |
| 视觉过滤（可见性） | **【键名】** `_EDITOR_FILTER_TITLE` → 可见性设置；`_FILTER_CAMPLIST` → 可见阵营列表；`_FILTER_TYPE` → 过滤器类型；`_FILTER_BOOL` → 布尔；`_FILTER_LOCAL` → 本地过滤器；`_FILTER_CHOOSEBP` → 点击选择；`_FILTER_SAME` → 相同阵营；`_FILTER_FRIENDLY` → 友方阵营；`_FILTER_ENEMY` → 敌方阵营 |
| 循环节 | **【键名】** `_EDITOR_LOOP_SETTINGS` → 循环节设置；`_OPEN` → 启用循环节；`_START` → 循环节起点(s)；`_END` → 循环节终点(s)；`_TIMELESS` → 无限循环；`_TIMES` → 循环次数；`_EX4_LOOPTIME` → 循环节时长(s) |
| 特效块属性 | **【键名】** `_EDITOR_PROPERTY_VFXID` → 特效块ID；`_CONTINUOUS` → 持续播放；`_DURATION` → 填充时间(s)；`_SETASSETTIME` → 设为资产时长；`_SPEED` → 特效表现播放速度；`_ELEMENTS` → 附加元素属性；`_SACLE` → 缩放比例 |
| 元素属性（7 元素） | **【键名】** `_EX4_PROP` → 无；`_PYRO` → 火；`_HYDRO` → 水；`_ANEMO` → 风；`_ELECTRO` → 雷；`_DENDRO` → 草；`_CRYO` → 冰；`_GEO` → 岩 |
| 销毁/隐藏行为 | **【键名】** `_EX2_FIREEVENT` → 销毁时行为；`_FIRE_CLEAR` → 停止并清除特效；`_FIRE_TIME` → 停止并设置粒子残留时间；`_RESIDENTTIME` → 粒子残留时间；`_EX2_HIDE` → 隐藏时行为；`_HIDE_IGNORE` → 无视隐藏；`_HIDE_HIDEVFX` → 同步隐藏特效 |
| 三种预警特效形状 | **【键名】** `_WARNNINGVFXTITLE1_*` → 线性填充 / 从内向外 / 从外向内；`_WARNNINGVFXTITLE2_*` → 外径(m) / 内径(m) / 填充方向 / 填充时间(s) / 填充颜色（**圆形/环形**）；`_WARNNINGVFXTITLE3_*` → 外径 / 内径 / **扇形角度** / 顺时针 / 逆时针 / 由内向外 / 由外向内（**扇形**） |
| 资源操作 | **【键名】** `_EX1_RENAME` → 重命名；`_EX1_DELETE` → 删除；`_EX1_EXPORT` → 导出资产；`_EX1_SETTINGS` → 基础设置；`_EX1_SAVE` → 保存；`_EX1_SAVEAS` → 另存为；`_EX1_PREVIEW` → 预览；`_EX1_STOP` → 停止预览；`_EX3_EXPORT_VFX` → 特效器 |
| 音效轨道 | **【键名】** `_EX4_SOUNDTRACKSETTINGS` → 音效轨道设置；`_EX4_SOUNDASSET` → 音效资源；`_EX1_SOUND` → 播放特效默认音效 |
| 其它参数 | **【键名】** `_EX4_ORIGINPT` → 坐标原点；`_EX4_TRANSFORM` → 坐标变换；`_EX4_PERIOD` → 保持时间；`_EX4_DECAL` → 贴地高度；`_EX4_STOPEMIT` → 停止粒子发射；`_EX4_STOPEVENT_FIREVFX` → 销毁特效；`_EX4_CAMP_ALL/SAME/PARTNER/ENEMY` → 全部/同阵营/友善阵营/敌对阵营；`_EX4_INSPECTOR_FIRE` → 是否存在销毁时行为；`_EDITOR_HIDE3DICON` → 显示三维图标；`_EX4_PREVIEWSETTINGS` → 仅在预览时生效 |

### 3.9 编辑工具（PROTOTYPE，共 85 条）

| 工具 | 证据键名 → 中文 |
|---|---|
| **测距线** | **【键名】** `_LINE_MEASUREMENTLINES` → 测距线；`_ADDMEASUREMENTLINES` → 添加测距线；`_TIPS` → 点击放置测距线起点和终点；`_INS_BASICPROPERTIES` → 基础属性；`_INS_LOCKTRANSFORMATION` → 锁定变换；`_INS_SCALE(m)` → 刻度(m)；`_INS_MEASUREMENTPOINTS` → 测距点；`_SETS_ALWAYSSHOWMEASUREMENTLINES` → 测距线常驻显示；`_TIPTITLE` → 提示；`_TIP` → 是否清除所有测距线？；`_METER` → {0}m；`_METERTAG` → 长度(m)；`_COPY` → 复制测算距离；`_DELETE` → 删除测距线；`_OVERLIMITS` → 测距线数量已达上限；`_REMOVEALL` → 全部移除 |
| **阵列** | **【键名】** `_ARRAY_ARRAY` → 阵列；`_GRIDARRAY` → 网格阵列；`_GRIDDIMENSIONS` → 阵列间隔；`_NUMBEROFGRIDS` → 阵列数量；`_CIRCULARARRAY` → 环形阵列；`_ARRAYOBJECT` → 阵列对象；`_ARRAYSETTINGS` → 阵列设置；`_ARRAYAXISPOSITION` → 阵列轴位置；`_ARRAYAXISVECTOR` → 阵列轴向量；`_ANGLE` → 角度；`_QUANTITY` → 数量；`_PREVIEW` → 预览；`_CONFIRMCREATION` → 确认创建 |
| **对称** | **【键名】** `_SYMMETRY_SYMMETRY` → 对称；`_POINTSYMMETRY` → 点对称；`_AXISSYMMETRY` → 轴对称；`_FACESYMMETRY` → 面对称；`_SYMMETRYGENERATION` → 对称生成；`_SYMMETRICOBJECT` → 对称对象；`_SYMMETRYSETTINGS` → 对称设置；`_SYMMETRYMODE` → 对称模式；`_POINT` → 点；`_AXIS` → 轴；`_FACE` → 面；`_SYMMETRYPOINTPOSITION` → 对称点位置；`_ROTATESYMMETRYAXIS` → 对称轴旋转；`_ROTATESYMMETRYPOSITION` → 对称轴位置；`_FACESYMMETRYPOSITION` → 对称面位置；`_FACESYMMETRYROTATION` → 对称面旋转；`_KEEPORIGINALOBJECT` → 保留原物件 |
| **备注 / 3D 标注** | **【键名】** `_TIPTOOL_NOTES` → 备注；`_SHOW3DNOTES` → 显示3D备注；`_3DANNOTATIONACCEPTANCE` → 3D备注颜色；`_OVERALLSETS` → 备注常驻显示；`_SHOWZ-AXISDIRECTION` → 显示Z轴朝向；`_EDITTOOLS` → 编辑工具 |
| **复制/粘贴/变换** | **【键名】** `_EDITORTOOL_COPY` → 复制；`_PASTE` → 粘贴；`_TRANSFORM` → 变换；`_CENTREPOINTPOSITION` → 中心点位置；`_COPYENTITYDATA` → 复制实体数据；`_PASTEENTITYDATA` → 粘贴实体数据；`_PREVIEW` → 预览；`_GENERATINGPREVIEWCONTENT` → 预览内容生成中...；`_GENERATE` → 生成；`_GENERATINGENTITY` → 实体生成中...；`_VIEWINAUTOCAD` → 在局内查看；`_DELETE` → 删除；`_{0}OBJECTS` → {0}个对象 |
| **显示类型** | **【键名】** `_GAMEOBJECT_TYPE` → 显示类型；`_NONE` → 无；`_DIMENSIONSONLY` → 仅尺寸；`_BOUNDINGBOXANDDIMENSIONS` → 包围盒及尺寸；`_COLLISIONANDDIMENSIONS` → 碰撞及尺寸；`_GRIDLINES` → 网格线 |
| 数量上限 | **【键名】** `_TIPS_OVERLIMITS` → 创建失败，创建的内容不可超过100个 |

### 3.10 实体布设组、单位标签、光标

| 功能 | 证据键名 → 中文 |
|---|---|
| 实体布设组 | **【键名】** `UI_BEYOND_EDITOR_SUITE_WPF_TITLE` → 实体布设组；`_FILTER_RESET` → 重置；`_FILTER_NONE` → 暂无 |
| 单位标签 | **【键名】** `UI_BEYOND_EDITOR_TAG_WPF_TITLE` → 单位标签；`UI_BEYOND_EDITOR_ATTACKTAG_STRINGLIST_LIMIT` → 可添加数量达到上限 |
| 玩家光标配置 | **【键名】** `UI_BEYOND_EDITOR_UI_PLAYER_CURSOR_TITLE` → 光标配置；`_PERSIST` → 光标常驻；`_PERSIST_TIPS` → 光标常驻关闭时, 光标相关的功能也无法生效；`_CLICKABLE_LAYER` → 可点击层级；`_MAX_SELECTABLE` → 光标最多可选取目标数；`_PENETRATE_UI` → 点击可穿透UI控件；`_PENETRATE_UI_TIPS` → 关闭时，光标点击穿过UI控件后不再打到场景物体 |
| 光标可点击层级（4 层） | **【键名】** `_LAYER_SCENE` → 场景；`_LAYER_HITBOX` → 受击盒；`_LAYER_OBJECTCOLLIDER` → 物件碰撞；`_LAYER_CURSORCOLLIDER` → 光标碰撞；`_LAYER_SELECTALL` → 全选；`_LAYER_ALL` → 全部；`_LAYER_NONE` → 暂无 |
| 移动端提示 | **【键名】** `_CURSOR_TIPS_MOBILE` → 移动端点击屏幕时，响应此处配置的技能(仅支持瞬发技能)。 |
| 光标碰撞盒 | **【键名】** `UI_BEYOND_EDITOR_CURSOR_COLLISION_COMPOMENT_NAME` → 光标碰撞盒；`_NAME_LIST` → 光标碰撞{0}；`_INITIAL_EFFECT_CURSOR_COLLISION_LIST` → 初始生效光标碰撞；`_STRUCTURE_LIST` → 光标碰撞体列表；`_ADD` → 添加光标碰撞；`UI_BEYOND_EDITOR_COMPOMENT_GENERAL_CURSOR_COLLISION_LIMIT_TIP` → 光标碰撞体数量已达上限；`UI_BEYOND_EDITOR_UI_COMPONENT_CONFIG_CURSOR_COLLISION` → 光标碰撞盒 |
| 造物状态蓝图调试日志 | **【键名】** `UI_BEYOND_EDITOR_UI_MONSTER_V2_BLUEPRINT_INSERT_UP` → 向上插入；`_INSERT_DOWN` → 向下插入；`_DEBUG_LOG_CHANGE_STATE` → ;状态蓝图ID切换为{0};AI参数模板序号为{1}；`_DEBUG_LOG_CHANGE_SKILL` → ;行为切换为尝试施放技能序号:{0}；`_DEBUG_LOG_CHANGE_TACTIC` → ;行为切换为尝试施放战术名称:{0} |

### 3.11 信号管理器（`SIGNAL_*`，39 条）

| 功能 | 证据键名 → 中文 |
|---|---|
| 面板 | **【键名】** `..._SIGNAL_SERVER_SIGNAL_MANAGEMENT` → 服务器信号管理器；`..._SIGNAL_ENTRY_HINT` → 信号管理；`..._SIGNAL_SIGNAL_MANAGEMENT_INTERFACE` → 服务器信号管理器 |
| 增删改 | **【键名】** `_ADD_NEW_SIGNAL` → 添加信号；`_ADD_NEW_VARIABLE` → 添加参数；`_APPLY_CHANGES` → 应用修改；`_BASIC_RENAME` → 重命名；`_BASIC_COPY` → 复制；`_BASIC_PASTE` → 粘贴；`_BASIC_RESET` → 回退；`_BASIC_DELETE` → 删除 |
| 默认名 | **【键名】** `_DEFAULT_NAME` → 信号_{0}；`_VARIABLE_DEFAULT_NAME` → 参数_{0} |
| 空态 | **【键名】** `_EMPTY_STATE_NO_SIGNAL` → 暂无信号；`_EMPTY_STATE_NO_SELECTED_SIGNAL` → 请选择一个信号；`_NO_PARAMETERS_AVAILABLE` → 暂无参数；`_CLICK_PLUS_BELOW_TO_CREATE_PARAMETER` → 点击加号创建参数；`_NO_MATCHING_RESULTS_FOUND` → 没有符合的信号；`_REFERENCE_DATA_EMPTY_TIP` → 当前信号未被节点图引用 |
| 搜索 | **【键名】** `_SEARCH_TEXT_HINT` → 搜索信号；`_COMPOSITE_SEARCH_RESOURCES` → 检索 |
| 校验与上限 | **【键名】** `_NAME_ALREADY_EXISTS` → 名称已存在；`_NAME_CANNOT_BE_EMPTY` → 名称不可为空；`_CHARACTER_LIMIT_HINT` → 达到字数上限；`_REACHED_CREATION_LIMIT` → 超出单个关卡信号上限：{0}；`_VARIABLE_REACHED_CREATION_LIMIT` → 超出参数上限：{0} |
| 引用关系 | **【键名】** `_VIEW_REFERENCE_RELATIONS` → 查看节点图引用；`_REFERENCE_COUNT_HINT` → 处节点图引用；`_SIGNAL_ADDITION_COUNT` → 数量 |
| 未保存拦截 | **【键名】** `_UNSAVED_CLOSE_WARNING` → 存在未保存的编辑内容，确认要关闭窗口吗？；`_MODIFIED_DATA_COUNT_HINT` → 个信号数据存在修改，确认保存吗？；`_MODIFICATION_CAUSES_INTERLOCK_HINT` → 确认后所有使用位置也将被同步修改 |
| 操作反馈 | **【键名】** `_DATA_COPY_SUCCESSFUL` → 复制信号数据成功；`_DATA_OVERWRITE_SUCCESSFUL` → 覆盖信号数据成功；`_DATA_RESET_SUCCESSFUL` → 回退信号修改成功；`_GO_TO_INTERFACE_TO_CREATE` → 前往创建信号 |
| 当前配置 | **【键名】** `_COMPOSITE_CURRENTLY_SELECTED` → 当前配置 |

### 3.12 外部资产（导入/导出/转存）

| 功能 | 证据键名 → 中文 |
|---|---|
| 外部资产三类 | **【键名】** `..._EXTERNAL_ASSETS_BP` → 外部资产节点图；`_NODE` → 外部资产节点；`_PACKAGE` → 外部资产组合 |
| 转存对话框 | **【键名】** `..._EXTERNAL_ASSETS_TITLE` → **转存资产**；`_NAME` → 资产名称；`_TAP` → 所属页签 |
| 各分型的导入项 | **【键名】** `..._BLUEPRINT_MANAGER_IMPORT_BP` → 节点图外部资产；`..._CLIENT_BLUEPRINT_MANAGER_IMPORT_FILTER` → 本地过滤器节点图外部资产；`..._IMPORT_SKILL` → 技能节点图外部资产；`..._CLIENT_BLUEPRINT_IMPORT` → 客户端节点图外部资产 |

### 3.13 枚举字典（102 个类型，487 个成员）

**【键名】** `BeyondAssistantEditorConfigGlobal_configEnum_maps_*`。每个类型有 `_mapTitle`（类型名）+ `_map_N_textMapId_K`（成员名）。102 个类型全名单：

布尔值、比较运算、逻辑运算、数学运算、攻击形状、生存状态、排序规则、取整逻辑、类型转换、运动路径点位类型、运动类型、跟随位置类型、坐标系类型、元素类型、实体类型、单位状态添加失败原因、单位状态添加结果、单位状态移除原因、单位状态移除策略、复苏点选取策略、倒下原因、三角函数、扰动装置类型、扰动装置朝向、界面控件组状态、目标类型、触发限制、打击类型、攻击类型、受击表现等级、技能槽位、声音衰减方式、选择完成原因、结算状态、道具变化原因、道具掉落类型、决策刷新方式、元素反应类型、扫描积分规则、随机排序、游玩方式、输入设备类型、定点运动器运动类型、定点运动器参数转化类型、栈顶技能销毁类型、职业切换技能处理、颜色叠加类型、填充材质、基础数学运算、便捷数学运算、目标排序规则、攻击层配置、击退方向类型、转向类型、扇形检测方向、溯源类型、受击等级、过滤器返回类型、目标类型(镜头朝向节点用)、射线命中筛选类型、受打断状态、扫描状态、伤害跳字类型、移动速度、目标实体、组件功能、旋转方向、战术枚举、预瞄准结束原因

（注：`_maps_0`–`_maps_48` 与 `_maps_49`–`_maps_101` 是两组同名/近名的类型，推测分别服务于**服务端蓝图**与**客户端蓝图**两套上下文——见 3.14 的【超限】/【经典】双轨。）

代表性成员证据：
- 技能槽位：`普通攻击 / 技能1-E / 技能2-Q / 技能3-R / 技能4-T / 自定义技能槽位1–5`
- 元素类型：`火元素 / 水元素 / 风元素 / 雷元素 / 草元素 / 冰元素 / 岩元素 / 无`
- 实体类型：`关卡 / 物件 / 玩家 / 角色 / 造物`
- 游玩方式、输入设备类型、结算状态、单位状态添加结果（`成功，施加新状态 / 成功，槽位叠层`）等

### 3.14 蓝图分类目录体系（13 个顶层分类 + 多级子目录）

**【键名】** `BeyondAssistantEditorConfigGlobal_folders_N_data_name` / `..._data_subFolders_M_name`。顶层 13 个：

| 索引 | 名称 |
|---|---|
| folders_0 | **【超限】服务端蓝图** |
| folders_1 | **【超限】Filter** |
| folders_2 | **【超限】角色技能蓝图** |
| folders_3 | **【超限】AI决策蓝图** |
| folders_4 | **【超限】AI状态蓝图** |
| folders_5 | **【超限】造物技能蓝图** |
| folders_6 | **【经典】服务端蓝图** |
| folders_7 | **【经典】Filter** |
| folders_8 | **【XXX】【经典】角色技能** |
| folders_9 | **【经典】AI决策蓝图** |
| folders_10 | **【经典】造物技能蓝图** |
| folders_11 | **【经典】AI状态蓝图** |
| folders_12 | **【超限】操控运动器蓝图（操控技能）** |

**服务端蓝图**的一级分类（folders_0 / folders_6 一致）：执行节点 / 事件节点 / 流程控制节点 / 查询节点 / 运算节点。
二级则是**游戏能力域的完整清单**（以下为 folders_0 执行节点的 55 个子目录，即编辑器节点库的领域索引）：

通用、列表相关、自定义变量、预设状态、实体相关、关卡相关、阵营相关、玩家与角色相关、碰撞、碰撞触发器、战斗、运动器、跟随运动器、投射物、特效、定时器、全局计时器、镜头、角色扰动装置、单位状态、选项卡、碰撞触发源、职业、界面控件组、技能、音效、单位标签、自定义仇恨、信号、铭牌、文本气泡、卡牌选择器、关卡结算、光源组件、字典、结构体、商店、装备、道具与背包、小地图标识组件、造物巡逻、排行榜、成就、扫描标签、段位、实体布设组、聊天频道、奇域礼盒相关、寻路阻挡、光标碰撞盒组件、造物预设状态、悬浮交互页、关卡任务、操控运动器、光标。

> 这 55 项是**节点库分类**而非独立面板——即它们是"编辑器里节点图能做什么"的证据，不是"编辑器有哪些面板"的证据。二者必须区分（见第五节）。

**【超限】与【经典】的分类粒度确有差异**（可量化）：`folders_0`（超限服务端）的「执行节点」有 **55** 个子目录，而 `folders_6`（经典服务端）的「执行节点」只有 **44** 个；「事件节点」分别为 **29** / **24** 个。即**【超限】体系的节点分类更细**，多出的类别集中在较新的能力域。这支持"两套并行蓝图体系"的判断，但仍不足以确定二者差异的全部含义。

### 3.15 其它全局提示与校验

| 功能 | 证据键名 → 中文 |
|---|---|
| 元件/实例/ID 词 | **【键名】** `UI_BEYOND_GENERAL_PREFAB` → 元件；`_PREFAB_ID` → 元件ID {0}；`_INSTANCE` → 实例；`_CONFIG_ID` → 配置ID {0}；`_GUID` → GUID {0}；`_INDEX` → 序号 {0}；`_REFERENCE` → 索引 {0} |
| 通用校验 | **【键名】** `_ERROR_TIP_NAME_LENGTH_MAX` → 字数达到上限；`_ERROR_TIP_NAME_EMPTY` → 名称不可为空；`_CONTENT_NONE` → 暂无内容；`_TIPS_NOMORETODAY` → 今日不再提示；`_TIPS_CONFIRM_AUTO` → {0}秒后自动确认 |
| 手柄 | **【键名】** `UI_SETTING_BEYOND_CURSOR_SENSITIVITY` → 奇域游玩时手柄控制常驻光标灵敏度（唯一一条 `UI_SETTING_*`） |
| 场景生成模板 | **【键名】** `..._PCG_WPF_TYPE_NAME` → 场景生成模板 |

### 3.16 快捷键体系（ShortCutKey 配置 + 59 条键名）

`Json/Config/JsonConfig/ShortCutKey/1074106604405081892.mihoyobin`（146 条字符串）把快捷键按**上下文 → 分组 → 动作**三级组织，动作项直接引用上一节的 UI 键名。8 个上下文：

| 上下文键名 → 中文 | 该上下文下的动作 |
|---|---|
| `BEYOND_EDITOR_SHORTCUT_KEY_CATALOG` → 目录 | 选择上一个/下一个、展开/收起、返回顶部、返回底部 |
| `BEYOND_EDITOR_SHORTCUT_KEY_EDIT_FLODER` → 文件/文件夹 | 创建副本、打开选中文件/文件夹 |
| `UI_BEYOND_LOG_FILTER_SEARCH` → 搜索 | 左/右移动光标、全选输入内容、光标移至最左、光标移至最右、删除 |
| `BEYOND_EDITOR_SHORTCUT_KEY_ASSIST_COMMON` → 通用 | **保存**、**撤销**、**还原**、注释、节点搜索 |
| `BEYOND_EDITOR_SHORTCUT_KEY_CANVAS` → 画布 | 平移画布、放大/缩小画布、打开节点库（鼠标位于画布空白处） |
| `UI_BEYOND_ASSIST_EDITOR_DEFAULT_FILTER_NODE_TYPE` → 节点 | 复制、粘贴、多选节点、全选节点、移动选中的节点、删除选中的节点、生成复合节点、解散复合节点、断开所选连线 |
| `UI_BEYOND_ASSIST_EDITOR_NODE_LIBRARY` → 节点库 | 选择上一个/下一个、页签展开/收起、创建所选节点 |
| （未命名包装项 ×2） | — |

键帽文本键名：`BEYOND_EDITOR_SHORTCUT_KEY_TOOL_{Ctrl,Shift,Alt,A,C,D,F,G,S,V,Y,Z,Home,End,Delete,ENTER,LEFT_ARROW,RIGHT_ARROW,UP_ARROW,DOWN_ARROW,CREATCOPY}`，值为 `Ctrl`/`Shift`/`Alt`/`Home`/`End`/`←`/`→`/`↑`/`↓`/`创建副本` 等。配置文件另含鼠标绑定（`MouseRight` 平移画布 / `MouseScroll` 缩放画布 / `MouseRight` 打开节点库）与 **FR / DE 等语言的键帽本地化表**（如 FR 的 `Entrée`/`Maj.`/`Début`，DE 的 `Eingabe`/`Umschalt`/`Pos1`，且 DE 把 Z/Y 互换以适配 QWERTZ 键盘）。

---

## 四、同义词库结构说明

### 4.1 它是什么

`Json/Config/JsonConfig/SynonymsLibrary/CHS`（372 条目 / 2134 个别名串）是**编辑器内检索用的同义词扩展表**。

**方向是「口语/别名 → 官方术语」的查询扩展**，而不是一张扁平的字符串替换表：每条记录以**官方术语**为键（`f:1`），附一组用户可能输入的口语说法（`f:2` 重复字段）。检索时用户输入任一同义词，都能命中同一条官方术语。

### 4.2 字段格式


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


原始 wire 示例（已解码 JSON）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

= 官方术语「仇恨」← 别名 敌意、仇、仇恨值、威胁值、敌对度、嘲讽值、仇恨。

### 4.3 统计与两条硬性规律

| 项 | CHS | EN |
|---|---|---|
| 官方术语条目数 | 372 | 373 |
| 别名串总数 | 2134 | 1980 |
| 别名表**末位恒等于官方术语本身**的条目 | **372 / 372（100%）** | 同 |
| 官方术语出现在自己别名表内的条目 | **372 / 372（100%）** | 同 |
| `index.jsonl` strings 去重数 | 1660 | — |

**规律：每条别名表的最后一个元素就是官方术语本身。** 也就是说这张表在结构上是"自我包含的闭包"——查询时不需要额外把官方术语合并进别名集，它已经在里面了。这也解释了去重口径 1660 与 2506（372 + 2134）的关系。

### 4.4 典型条目与语义

| 官方术语 | 别名（口语说法） |
|---|---|
| 仇恨 | 敌意、仇、仇恨值、威胁值、敌对度、嘲讽值、仇恨 |
| 界面控件组 | 面板组、UI 控件组、UI组件组、控件容器、控件面板、界面控件组 |
| 节点图 | 蓝图、逻辑图、逻辑、节点网络、流程图、节点图 |
| 背包道具 | 行囊物品、装备品、物品栏道具、携带物品、随身道具、库存道具、背包道具 |
| 生命值 | 生命、血量、血、命、健康值、体力值、生命值 |
| 计分板 | 记分牌、分数面板、成绩榜、得分界面、当前积分、排名、计分板 |
| 圆周率 | π、派、圆周率 |
| 复苏点 | 复活点、重生点、存档点、苏醒点、检查点、安全点、复苏点 |
| 平方根 | 根号、√、开方、平方根 |
| 可攀爬性 | 可否攀爬、可否攀登、可爬、悬崖、纵向、位移、可攀爬性 |

条目还覆盖**动词类**检索词：`获取`（取得/收集/访问/拿到/获得/获取）、`删除`（移除/剔除/去除/清除/摧毁/清空/抹除/删除）、`激活/关闭`（启用/禁用、开启/关闭、触发/停用、生效/失效、开/关、激活/关闭）、`是否`（可否/能否/是否）。

### 4.5 一处解码存疑

`界面控件组` 条目的别名 `UI组` 解出为
`{"f":2,"w":2,"m":[{"f":10,"w":5,"v":2226906953}],"s_alt":"UI组"}`
——该别名项同时含一个**未知嵌套字段 `f:10`（定长 64 位，值 2226906953）**，解码器把字符串降级放入 `s_alt`。同类结构在 ShortCutKey 的键名项中也出现（`{"f":3,...,"s_alt":"\n+BEYOND_EDITOR_SHORTCUT_KEY_TOOL_DOWN_ARROW"}`）。含义未定：可能是**别名唯一 ID** 或**指向 TextMap 哈希的引用**，也可能是解码器对"同一 field 同时含子消息与字符串"的降级表示。**不做结论。**

---

## 五、未解、存疑、依赖推断的部分

### 5.1 覆盖边界：本 TextMap 只覆盖「千星沙箱」（BeyondAssistEditor）

这是**最重要的边界声明**。全部 4098 个文件都在
`BeyondAssets\BeyondAssistEditor\Resource\` 之下，TextMap 亦不例外。因此本文清点的是**千星沙箱及其附属工具**的界面文本。

任务书点名的若干功能域，在本批资源中**只能找到间接痕迹，找不到面板自身的文本**：

| 功能域 | 本批资源中的证据 | 判定 |
|---|---|---|
| 地形编辑 | 1 条提示 `UI_BEYOND_EDITOR_ESP_TIPS_ONLYFORENTITYANDENVIROEDITMODE` → 「**只能在实体摆放页签或地形编辑页签使用**」；另有 `COSTLOAD_DETAILS_TYPE_TILEMAP` → 地形、`DEFAULT_FILTER_SUITE` → 地形 | **【推断】** 存在"地形编辑页签"与"实体摆放页签"，但**其面板文案不在本 TextMap 内** |
| 实体摆放 | 同上一条提示 | **【推断】** 同上有页签，无自身文案 |
| 元件库 | `RESOURCE_MANAGER_PREFAB_RESOURCE` → 元件库资产栏；`RESOURCE_MANAGER_PREFAB_EDIT_SCENE` → 元件库编辑场景；`GENERAL_PREFAB_ID` → 元件ID | **【键名】** 明确存在 |
| 试玩 | `COSTLOAD_TESTING_TITLE` → 试玩进行中；`_NONEFORPROCESS_TEXT` → 动态负载检测需要在开启负载测试的情况下进行试玩；`UI_BEYOND_LOG_TIPS_DEBUG` → 关卡运行状态下无法修改数据 | **【推断】** 存在试玩流程与"试玩中"状态面板；**试玩启动器 UI 文本不在本批资源** |
| **多人试玩** | 全库检索 `多人` = **0 命中**；仅有节点级证据（`获取在场玩家实体列表`、`UI_BEYOND_LOG_NAME_LOGNAME` → 日志_{0}_**玩家**_{1}、`COSTLOAD_PLAYERLIST_PLAYERNAME` → 玩家{0}） | **【无证据】** 不能断言存在"多人试玩"入口；只能确认逻辑层支持多玩家 |
| 战斗预设 | 全库检索 `战斗预设` = **0 命中**；`关卡设置` = **0 命中** | **【无证据】** 不存在该命名的面板 |
| 撤销 / 还原 | `BLUEPRINT_UNDO` → 撤销、`BLUEPRINT_REDO` → 还原、快捷键 `通用` 组、25 条历史记录文本 | **【键名】** 明确存在 |
| 导入 / 导出 | `RIGHT_MENU_IMPORT/EXPORT`、`EXTERNAL_ASSETS_TITLE` → 转存资产、`EX1_EXPORT` → 导出资产 | **【键名】** 明确存在 |
| 计分板 | `设置玩家结算计分板展示数据`（节点名）+ 同义词库「计分板」 | **【键名】** 但属**节点图能力**，非编辑器面板 |
| 背包 / 商店 / 技能 / 造物 | 大量节点名（见 5.3）与同义词条目 | **【键名】** 但均属**节点图能力域**，非编辑器面板 |

### 5.2 「面板」与「节点图能力域」必须区分

任务书列出的功能域里，背包、商店、技能、造物、计分板、成就、段位、排行榜、卡牌选择器、小地图标识、聊天频道、悬浮交互页、关卡任务等，在本批资源中的证据**全部**是：

1. `BeyondEditorInstructionNodeConfig_*` 里的**节点名**（例：`name_702` → 打开商店、`name_685` → 增加背包最大容量、`name_395` → 添加角色技能、`name_647` → 设置玩家结算计分板展示数据）；
2. `folders_*` 里的**节点库分类名**（例：`folders_0_data_subFolders_0_subFolders_36_name` → 商店）。

它们证明的是**「用节点图可以制作商店/背包/技能系统」**，**不是**「编辑器里有一个商店面板」。本节按此区分撰写，未将其计入"面板"。

### 5.3 节点指令库（800 个节点，本文只做归类，不逐条展开）

800 个节点名**全部非空**，已按名称归类出以下能力域（每域举 2–4 例，均可在 `BeyondEditorInstructionNodeConfig_name_N` 中查到）：

| 能力域 | 节点名示例 |
|---|---|
| 流程控制 | 双分支、多分支、有限循环、跳出循环、列表迭代循环、按顺序唯一执行、节点图开始/结束 |
| 数学与向量 | 加法/减法/乘法/除法/模/幂/对数运算、三维向量加法/减法/缩放/夹角/内积/外积/旋转/归一化、三角函数、弧度转角度 |
| 位运算 | 左移运算、右移运算、按位与/或/异或/取补/写入/读出 |
| 实体与查询 | 创建实体、销毁实体、获取自身实体、以GUID查询实体、获取实体位置与旋转、获取场上所有实体、获取指定范围的实体列表 |
| 运动器 | 添加匀速直线型/匀速旋转型/朝向目标旋转型基础运动器、停止并删除基础运动器、操控运动器（速度/接地/转向） |
| 战斗与仇恨 | 发起攻击、受到攻击时、攻击命中时、设置/查询指定实体的仇恨值、嘲讽目标、查询阵营是否敌对、依序仇恨列表相关 |
| 命中判定 | 特定位置打攻击盒、打球形/矩形/扇形攻击盒、指定挂接点打攻击盒、获取射线检测结果 |
| 单位状态与标签 | 添加/移除单位状态、单位状态变更时、根据槽位序号查询单位状态层数、实体添加/移除/清空单位标签 |
| 造物与 AI | 战术：地面闲逛/地面追击/地面逃跑/执行巡逻/对峙、切换造物巡逻模板、获取造物当前目标、造物入战/脱战时、设置攻击权重 |
| 镜头与屏幕 | 切换主镜头模板、激活实体镜头、激活注目镜头、激活屏幕震动、屏幕坐标↔世界坐标互转 |
| 特效与音效 | 播放限时特效、挂载循环特效、清除循环特效、添加音效播放器、设置玩家背景音乐、玩家播放单次2D音效 |
| 背包与道具 | 背包道具新增/失去/数量变化时、增加背包最大容量、获取背包容量、获取背包所有装备、掉落物组件相关 |
| 商店 | 打开商店、关闭商店、设置自定义商店商品出售信息、向背包商店出售表中新增商品、查询商店收购物品列表 |
| 装备 | 装备添加/移除/设置词条、装备被穿戴/卸下时、替换装备到指定栏位、根据装备索引查询装备配置ID |
| 技能 | 添加/删除/查询角色技能、初始化角色技能、创建/销毁自定义技能实例、绑定技能实例到指定槽位、查询技能属性组值 |
| 职业与段位 | 查询玩家职业、更改玩家职业、提升玩家当前职业经验、获取/设置玩家段位变化分数、切换玩家竞技段位生效的计分组 |
| 结算与计分 | 结算关卡、设置玩家结算计分板展示数据、设置/获取玩家结算排名数值、设置玩家结算成功状态、更新玩家排行榜分数 |
| 成就与任务 | 查询成就是否完成、增加成就进度计数、设置/增加任务计数、查询指定任务是否完成 |
| 卡牌与礼盒 | 唤起卡牌选择器、卡牌选择器完成时、关闭卡牌选择器、随机卡牌选择器选择列表、消耗礼盒、查询对应礼盒数量 |
| 小地图与标记 | 设置小地图缩放、设置小地图标识生效状态、设置追踪小地图标识的玩家列表、查询指定小地图标识信息 |
| UI 与界面控件 | 激活/关闭选项卡、切换当前界面布局、激活控件组库内界面控件组、设置界面控件(组)状态、播放界面动效控件、悬浮交互页相关、更新消息队列 |
| 聊天与社交 | 设置聊天频道开关、设置玩家频道权限、设置玩家当前频道、设置玩家聊天语音范围、查询玩家是否正在语音聊天 |
| 扫描与寻路 | 设置扫描标签的规则、获取实体扫描状态、激活/关闭寻路阻挡功能、查询目标点是否寻路可达 |
| 数据结构 | 建立/拼装/清空字典、以键查询字典值、拼装/拆分/修改结构体、查询自定义变量快照 |
| 预瞄与光标 | 获取预瞄结果、获取预瞄射线命中信息、获取光标命中结果、获取光标屏幕坐标、设置玩家光标是否常驻 |
| 时间与计时 | 启动/暂停/恢复/终止全局计时器、查询游戏已进行时间、根据时间戳计算格式化时间、查询服务器时区 |
| 信号与事件 | 发送信号、监听信号、向服务器节点图发送信号、通知服务器节点图、转发事件 |
| 环境与光源 | 查询/设置当前环境时间、设置环境时间流逝速度、开关实体光源、设置环境配置 |
| 复杂造物 | 获取复杂造物当前施放的技能、设置造物技能的冷却时间、复杂造物瞬移、查询复杂造物的预设状态值 |

**注意**：另有 200 余个 `name_200xxx` 系列节点是**同名的服务端/AI 侧镜像实现**（例：`name_200001` 逻辑与运算、`name_200104` 节点图结束、`name_200130`–`name_200141` 战术系列），与本表能力域重叠，未重复计入。

本工程另有兄弟任务产出的 `.runtime/editor-catalog/node-names.json`（799 条，把 `Beyond/Node/*.mihoyobin` 文件映射到节点名）与 `.runtime/editor-catalog/node-catalog-full.json`，可作为本节的下钻入口，本文不重复其工作。

### 5.4 明确未解 / 无法从文本确定的项

1. **节点描述几乎全空** —— `desc_*` 800 条中仅 **2 条**有文本（`desc_946`/`desc_947` = 「需要角色挂载【监听移动速率】单位状态效果」）。因此**节点功能的权威解释无法从本 TextMap 获得**，本文 5.3 的节点归类是**按节点名语义推断**，不是文档级确认。
2. **入/出引脚名大量缺失** —— `inPinList_*` 298 条中仅 3 条非空，`outPinList_*` 410 条中 70 条非空。引脚级接口细节需从 `Beyond/Node/*.mihoyobin` 另行解析。
3. **主编辑器外壳的中文界面文本不在本批资源内** —— `.runtime/editor-catalog/strings-BeyondEditor.dll.tsv`（14 行）与 `strings-real.txt` 是二进制字符串转储，实测对「地形编辑 / 实体摆放 / 试玩 / 元件库 / 战斗预设 / 关卡设置 / 节点图」**全部 0 命中**（该二进制已混淆，中文串不可直接提取）。主编辑器的界面文本很可能封装在 **`assets.bin`**（ZIP，内含 1 个加密成员，声明解压后 231,505,907 字节）与 `beyondeditorassets.bin`（声明 6,300 字节）之中，两者 encrypted flag 均为 1，**本工程尚未解包**。→ 这是"编辑器全量功能面"目前最大的已知缺口。
4. **`folders_8` = 「【XXX】【经典】角色技能」** —— 名称含未替换的占位符 `【XXX】`，说明该条目在本次构建中是**半成品/待填**，不应作为正式分类名引用。
5. **【超限】/【经典】双轨的含义未定** —— 13 个顶层分类里 6 个标【超限】、6 个标【经典】、1 个标【XXX】【经典】。枚举字典也是两组（`maps_0–48` / `maps_49–101`）。可推断为**两套并行蓝图体系/两种关卡模式**，但本批资源**没有**说明二者差异的文案，**不做结论**。
6. **`configTagSearchList`** 仅 12 条，已见 10 条为英文标签（`EffNonLoop`/`EffLoop`/`UICustomLayout`/`CameraTemplate`/`DummyPoint`/`CountDownTimer`/`UIModule`/`UIWidget`/`UIMW`/`物件`）。其用途（编辑器内标签检索候选？）**未在文本中得到说明**。
7. **`Beyond/Node/*.mihoyobin` 799 个文件 vs TextMap 中 800 个节点名** —— 数量差 1，本文未逐一对账，不排除个别节点无独立资源文件或存在一对多。
8. **`s_alt` 降级字段**（同义词库 1 例、快捷键表若干例，见 4.5）含义未定。

### 5.5 本次未触碰的范围

- 未运行任何桥接/探测/PS1 脚本，未连接运行中的编辑器进程。
- 未修改 `C:\Games\Genshin Impact Game\` 下任何文件（仅以只读方式计算 SHA256）。
- 未修改 `GOAL.md`。
- 未解包 `assets.bin` / `beyondeditorassets.bin`（加密，超范围）。
- 未对 4098 个文件中的 `Beyond/Official`（3280 个，实测**不含任何字符串**，纯数值资产定义）与 `Beyond/Node`（799 个）做逐文件语义解析。

---

## 附：本次分析使用的中间产物（均位于 `.runtime/editor-catalog/`）

| 文件 | 内容 | 支撑本文何处 |
|---|---|---|
| `_textmap_chs.tsv` / `_textmap_en.tsv` | TextMap CHS/EN 全量 `键 \t 哈希 \t 文本`（各 7743 行） | 第一、二节全部数字 |
| `_nodes.txt` | 800 个节点显示名 | §5.3 |
| `_nodedesc.txt` | 800 条节点描述（仅 2 条非空） | §2.2、§5.4-1 |
| `_enums.txt` / `_enumtitles.txt` | 589 条枚举条目 / 102 个枚举类型名 | §3.13 |
| `_folders.txt` | 478 条蓝图分类目录名 | §3.14 |
| `_synfull.txt` | 372 条同义词条目（官方术语 → 别名） | §四 |
| `_shortcut_out.txt` | 快捷键表（上下文 → 分组 → 动作 → 键位 → 中文） | §3.16 |
| `_uigroups.txt` / `_analyze_out3.txt` | UI_*、LOG、ESP、VFXEDITOR、PROTOTYPE 各组的逐键清单 | §三全部 |
| `_paths.txt` | 4098 个文件的路径前缀直方图 + 关键词全局命中统计 | §1.1、§5.1 |
| `_officialcats.txt` | `Beyond/Official` 三个子类的文件数 | §1.1 |
| `_beyond_out.txt` | BeyondGlobal / Node / Official 样本的 wire 结构；Official 无字符串的验证 | §5.4-3、§5.5 |
| `_typehints.txt` | 3 条类型提示 | §2.3 |
| `_hashes.txt` | 5 个关键文件的原始/解码 SHA256 及尺寸 | §1.2 |
| `_verify.txt` | 关键键名的存在性复核记录 | 全文键名校对 |
| `_doc_verify.py` / `_doc_verify.txt` | 从本文中抽出 807 个键样 token，逐个回查 TextMap | 全文档键名存在性 |
| `_verify_pairs.py` / `_pair_verify.txt` | 抽出本文全部 632 处 `键 → 中文` 配对，逐条比对 TextMap 实际值 | 全文档文本正确性 |
| `_verify2.txt` | 对上述比对中因前缀省略而歧义的 22 个键做全名精确复核 | 歧义消除 |
| `_analyze2.py`–`_analyze6.py` | 以上产物的生成脚本（可重跑） | 复现 |

### 自动化交叉核对结果

对本文做了一次**自动化回查**，结论如下：

- 键名存在性：本文引用的 807 个键样 token 中，**32 个精确命中、599 个后缀命中**（因文中使用 `..._XXX` 省略公共前缀），**176 个不命中**——逐个人工复核后确认这 176 个**全部不是 TextMap 键**，而是通配模式（`UI_BEYOND_EDITOR_*`）、文件路径（`assets.bin`）、SHA256、protobuf 字段名（`f:1`/`s_alt`）、快捷键键帽文本（`MouseRight`/`Eingabe`）、配置项标签（`EffNonLoop`）与中间产物文件名。**无一处伪造键名。**
- 文本正确性：本文 632 处 `键 → 中文` 配对，**563 处一次通过**；45 处被脚本标记，逐条人工复核后确认**全部是脚本的正则滑动或文中有意省略前缀所致**（例：`_STYLE` → 背景预设 被判到 `..._TITLE_STYLE` → 背景设置；`_TITLE` → 历史记录({0}/{1}) 被判到 `..._WINDOW_TITLE` → 千星沙箱），**对 22 个歧义键做了全名精确复核后全部一致**。**无一处文本张冠李戴。**

**变更记录**：2026-09-17 首次建立。全部数字由上述脚本从解码产物直接统计，未手工估算；键名与文本已通过上述两轮回查。
