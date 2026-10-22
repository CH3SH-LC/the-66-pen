> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

> **7.1版本复核（2026-09-26）**：下文保留原研究快照；旧地址、符号、统计全集和未找到结论不能直接视为7.1现状。当前接口迁移、Lua/协作等新增能力及验证边界见7.1复核报告（历史来源：`../../../7.1-revalidation/README.md`）。正文保留历史含义。

# 02-01a · UI 层文本清单 · 主窗口面板

> **调查的问题：** 千星编辑器界面上有哪些文本？它们各自命名了什么功能？
> **结论一句话：** 本文件覆盖 **9 个功能域 / 212 条键**（域：DEFAULT、RESOURCE、BLUEPRINT、CLIENT、NODE、COMPOSITE、BP、VAR、ADVANCED）。
> **最后更新：** 2026-09-22

读法、代码落点判据与全量统计见 00-总览.md（历史来源：`00-总览.md`）。

---

### `UI_BEYOND/ASSIST_EDITOR/DEFAULT`

**功能域：资源管理器：默认页签 / 筛选条件 / 右键菜单 / 列表列头** — 60 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `DEFAULT_CONNECTABLE_NODE` | 可连接节点 | 控件/字段显示名 | 有 |
| `DEFAULT_CURRENT_CATALOG_EMPTY` | 当前目录为空 | 空态文案 | 有 |
| `DEFAULT_CUSTOM_ROLESTATUS` | 自定义状态 | 控件/字段显示名 | 有 |
| `DEFAULT_DISCONNECT_TO` | 断开至：{0} | 控件/字段显示名 | — |
| `DEFAULT_DISCONNECT_TO_2` | 断开至：{0} {1} | 控件/字段显示名 | — |
| `DEFAULT_FILTER_BP_TYPE` | 节点图 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_DYNAMIC_INSTANCE` | 动态单位 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_DYNAMIC_PREFAB` | 动态元件 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_EXECUTABLE_NODE` | 筛选-可执行节点 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_FOLDER` | 文件夹 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_MONSTER` | 造物 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_NODES_BY_RULES` | 按照规则筛选节点列表 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_NODE_TYPE` | 节点 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_OPTIONS` | 筛选条件 | 控件/字段显示名 | — |
| `DEFAULT_FILTER_PROVIDED_NODE` | 筛选-提供{0}的节点 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_REFERENCED_NODE` | 筛选-引用{0}的节点 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_STATIC_INSTANCE` | 静态单位 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_STATIC_PREFAB` | 静态元件 | 控件/字段显示名 | 有 |
| `DEFAULT_FILTER_SUITE` | 地形 | 控件/字段显示名 | 有 |
| `DEFAULT_IMPORT_ASSET_TAB` | 导入资产页签 | 页签/分类名 | 有 |
| `DEFAULT_JUDGMENT_PARAMETER` | 判断参数 | 控件/字段显示名 | — |
| `DEFAULT_JUMP_TO` | 跳转至：{0} | 控件/字段显示名 | — |
| `DEFAULT_MOVE_TO` | 移动到：{0} | 控件/字段显示名 | 有 |
| `DEFAULT_NO_SEARCH_RESULTS` | 没有符合条件的搜索结果 | 搜索相关 | 有 |
| `DEFAULT_RIGHT_MENU_APPLY` | 应用 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_CHECK_FOCUS` | 在局内查看 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_CHECK_REFERENCE` | 查看引用关系 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_COPY_BP_ID` | 复制节点图ID | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_CUT_FOLDER` | 剪切文件夹 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_DECREASE` | 递减 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_DELETE` | 删除 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_DELETE_FOLDER` | 删除文件夹 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_EXPORT` | 导出 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_FACTION` | 阵营 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_FOLD` | 折叠 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_IMPORT` | 导入 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_INCREASE` | 递增 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_MOUNTED_BP` | 已挂载节点图 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_NAME` | 名称 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_NEW_BP` | 创建节点图 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_NEW_FILTER_BP` | 新建过滤器节点图 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_NEW_FOLDER` | 新建文件夹 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_NEW_SERVER_BP` | 新建节点图 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_NEW_SKILL_BP` | 新建技能节点图 | 菜单项 | — |
| `DEFAULT_RIGHT_MENU_OPEN` | 打开 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_ORDER` | 排序 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_REFERENCE` | 引用关系 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_REFERENCE_DETAILS` | 引用关系详情 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_RENAME` | 重命名 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_TYPE` | 类型 | 菜单项 | 有 |
| `DEFAULT_RIGHT_MENU_UNFOLD` | 展开 | 菜单项 | 有 |
| `DEFAULT_TABS` | 默认页签 | 页签/分类名 | 有 |
| `DEFAULT_TITLE_CAMP` | 阵营 | 标题 | — |
| `DEFAULT_TITLE_CATAGORY` | 类型 | 标题 | 有 |
| `DEFAULT_TITLE_EDIT_TIME` | 修改时间 | 标题 | 有 |
| `DEFAULT_TITLE_LOAD` | 负载 | 标题 | 有 |
| `DEFAULT_TITLE_NAME` | 名称 | 标题 | 有 |
| `DEFAULT_TITLE_QUOTE` | 引用 | 标题 | 有 |
| `DEFAULT_UNCLASSIFIED_TAB` | 未分类页签 | 页签/分类名 | 有 |
| `DEFAULT_UNDIFINED` | 未定义 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/RESOURCE`

**功能域：资源管理器：面板标题、编辑空间、资产栏** — 9 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `RESOURCE_MANAGER_CUSTOM_MONSTER` | 自定义造物 | 控件/字段显示名 | 有 |
| `RESOURCE_MANAGER_CUSTOM_PREFAB` | 自定义元件 | 控件/字段显示名 | 有 |
| `RESOURCE_MANAGER_CUSTOM_TAB` | 自定义分类 | 页签/分类名 | 有 |
| `RESOURCE_MANAGER_INSTANCE` | 实体 | 控件/字段显示名 | — |
| `RESOURCE_MANAGER_INSTANCE_EDIT_SCENE` | 场景编辑空间 | 控件/字段显示名 | 有 |
| `RESOURCE_MANAGER_OFFICIAL_TAB` | 预制分类 | 页签/分类名 | 有 |
| `RESOURCE_MANAGER_PREFAB_EDIT_SCENE` | 元件库编辑场景 | 控件/字段显示名 | 有 |
| `RESOURCE_MANAGER_PREFAB_RESOURCE` | 元件库资产栏 | 控件/字段显示名 | 有 |
| `RESOURCE_MANAGER_WINDOW_TITLE` | 资源管理器 | 标题 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/BLUEPRINT`

**功能域：节点图管理器：服务器/客户端节点图分型与增删改** — 26 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `BLUEPRINT_MANAGER_CLIENT_BP_MANAGER` | 客户端节点图资源管理器 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_DEBUG_LOG` | 日志 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_DROP_CUSTOM` | 自定义掉落物 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_DROP_OFFICIAL` | 掉落物 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_DUTY_BP` | 职业节点图 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_EDIT_SCENE_OBJECTS` | 场景编辑空间实体 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_IMPORT_BP` | 节点图外部资产 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_INSTANCE_BP` | 实体节点图 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_MENU_TITLE` | 服务器节点图 | 菜单项 | 有 |
| `BLUEPRINT_MANAGER_MOUNT_OBJECTS` | 节点图挂载对象 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_NODE_MANAGER` | 节点管理器 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_PREFAB_SCENE_OBJECTS` | 元件编辑空间实体 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_RESOURCE_MANAGER` | 资源管理器 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_ROLESTATUS_BP` | 状态节点图 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_SERVER_BP_MANAGER` | 服务器节点图资源管理器 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_STUFF_BP` | 道具节点图 | 控件/字段显示名 | 有 |
| `BLUEPRINT_MANAGER_TITLE_MENU` | 窗口 | 菜单项 | 有 |
| `BLUEPRINT_MANAGER_WINDOW_TITLE` | 千星沙箱 | 标题 | 有 |
| `BLUEPRINT_REDO` | 还原 | 控件/字段显示名 | 有 |
| `BLUEPRINT_SAVE` | 保存 | 控件/字段显示名 | 有 |
| `BLUEPRINT_SAVE_AS` | 另存为 | 控件/字段显示名 | 有 |
| `BLUEPRINT_SAVE_AS_NEW_NAME` | 新节点图名称 | 名称/字段标签 | 有 |
| `BLUEPRINT_SAVE_AS_NEW_TAB` | 新节点图页签 | 页签/分类名 | 有 |
| `BLUEPRINT_SAVE_AS_TITLE` | 节点图另存为 | 标题 | 有 |
| `BLUEPRINT_SAVE_SUCCESS` | 保存成功 | 控件/字段显示名 | 有 |
| `BLUEPRINT_UNDO` | 撤销 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/CLIENT`

**功能域：客户端节点图：技能 / 过滤器 / 操控 / 造物状态分型** — 21 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `CLIENT_BLUEPRINT_AVATAR_SKILL` | 角色技能节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_AVATAR_SKILL_NEW` | 新建角色技能节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_CONTROL` | 角色操控技能节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_CONTROL_NEW` | 新建角色操控技能节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_FILTER_TICK` | 秒 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_FILTER_TICK_TIPS` | 执行时间间隔 | 提示/说明文案 | 有 |
| `CLIENT_BLUEPRINT_IMPORT` | 客户端节点图外部资产 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_MANAGER_BOOL_FILTER_BP` | 布尔过滤器节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_MANAGER_FILTER_BP` | 本地过滤器节点图 | 控件/字段显示名 | — |
| `CLIENT_BLUEPRINT_MANAGER_IMPORT_FILTER` | 本地过滤器节点图外部资产 | 控件/字段显示名 | — |
| `CLIENT_BLUEPRINT_MANAGER_IMPORT_SKILL` | 技能节点图外部资产 | 控件/字段显示名 | — |
| `CLIENT_BLUEPRINT_MANAGER_INT_FILTER_BP` | 整数过滤器节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_MANAGER_MENU_TITLE` | 客户端节点图 | 菜单项 | 有 |
| `CLIENT_BLUEPRINT_MANAGER_SKILL_BP` | 技能节点图 | 控件/字段显示名 | — |
| `CLIENT_BLUEPRINT_MONSTER_AI` | 造物状态决策节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_MONSTER_AI_NEW` | 新建造物状态决策节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_MONSTER_POSE` | 造物状态节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_MONSTER_POSE_NEW` | 新建造物状态节点图 | 控件/字段显示名 | — |
| `CLIENT_BLUEPRINT_MONSTER_SKILL` | 造物技能节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BLUEPRINT_MONSTER_SKILL_NEW` | 新建造物技能节点图 | 控件/字段显示名 | 有 |
| `CLIENT_BP_EDITING` | 客户端节点图编辑 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/NODE`

**功能域：节点库与节点管理器** — 9 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `NODE_CUT` | 剪切 | 控件/字段显示名 | 有 |
| `NODE_DUPLICATE` | 复制 | 控件/字段显示名 | 有 |
| `NODE_LIBRARY` | 节点库 | 控件/字段显示名 | — |
| `NODE_MANAGER_CANCEL_TOP_UP` | 取消置顶 | 控件/字段显示名 | 有 |
| `NODE_MANAGER_COMPOSITE_NODE` | 复合节点 | 控件/字段显示名 | 有 |
| `NODE_MANAGER_IMPORT_NODE` | 节点外部资产 | 控件/字段显示名 | 有 |
| `NODE_MANAGER_NEW_COMPOSITE_NODE` | 创建复合节点 | 控件/字段显示名 | 有 |
| `NODE_MANAGER_TOP_UP` | 置顶 | 控件/字段显示名 | 有 |
| `NODE_SEARCHING` | 节点搜索 | 搜索相关 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/COMPOSITE`

**功能域：复合节点** — 21 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `COMPOSITE_CANCEL` | 取消 | 控件/字段显示名 | 有 |
| `COMPOSITE_CANCEL_PIN` | 取消在复合节点上显示 | 控件/字段显示名 | 有 |
| `COMPOSITE_CONFIRM` | 确认 | 确认对话框 | 有 |
| `COMPOSITE_CUSTOM_PIN_NAME` | 自定义引脚名 | 名称/字段标签 | 有 |
| `COMPOSITE_ENTER_PIN` | 入引脚 | 控件/字段显示名 | 有 |
| `COMPOSITE_FOCUS_IN_BP` | 在节点图中查看 | 控件/字段显示名 | 有 |
| `COMPOSITE_MERGED_PINS` | 已合并引脚 | 控件/字段显示名 | — |
| `COMPOSITE_MOVE_DOWN` | 向下移动 | 控件/字段显示名 | 有 |
| `COMPOSITE_MOVE_UP` | 向上移动 | 控件/字段显示名 | 有 |
| `COMPOSITE_NONE_SELECTED_PIN` | 未选中引脚 | 控件/字段显示名 | 有 |
| `COMPOSITE_ORIGIN_NAME` | 原引脚名 | 名称/字段标签 | 有 |
| `COMPOSITE_ORIGIN_NODE` | 来源于 | 控件/字段显示名 | 有 |
| `COMPOSITE_OUT_PIN` | 出引脚 | 控件/字段显示名 | 有 |
| `COMPOSITE_PIN_MERGE` | 合并引脚 | 控件/字段显示名 | 有 |
| `COMPOSITE_RELATED_BP` | 张节点图内使用 | 控件/字段显示名 | 有 |
| `COMPOSITE_SAVE_CHECK_A` | 是否确认修改复合节点数据 | 控件/字段显示名 | 有 |
| `COMPOSITE_SAVE_CHECK_B` | 确认后所有的引用也将被修改 | 控件/字段显示名 | 有 |
| `COMPOSITE_SAVE_NODE` | 保存复合节点修改 | 控件/字段显示名 | 有 |
| `COMPOSITE_SELECT_PIN_MERGE` | 选择引脚合并至{0} | 控件/字段显示名 | 有 |
| `COMPOSITE_SET_AS_PIN` | 设为复合节点引脚 | 控件/字段显示名 | 有 |
| `COMPOSITE_VAR_BOX_TIPS` | 参数框提示 | 提示/说明文案 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/BP`

**功能域：节点图变量与注释** — 16 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `BP_ANNOTATION` | 注释 | 控件/字段显示名 | 有 |
| `BP_CHECK_IN` | 在节点图变量中查看 | 控件/字段显示名 | 有 |
| `BP_ENTER_ANNOTATION` | 输入注释 | 控件/字段显示名 | — |
| `BP_VARIABLES` | 节点图变量 | 控件/字段显示名 | 有 |
| `BP_VAR_BATCH_DELETE` | 批量删除 | 控件/字段显示名 | 有 |
| `BP_VAR_BATCH_DELETE_OPEN` | 批量删除已开启 | 控件/字段显示名 | 有 |
| `BP_VAR_BATCH_DELETE_QUIT` | 退出 | 控件/字段显示名 | 有 |
| `BP_VAR_CREATE` | 新增变量 | 控件/字段显示名 | — |
| `BP_VAR_DELETE` | 删除变量 | 控件/字段显示名 | 有 |
| `BP_VAR_DUPLICATE` | 复制变量 | 控件/字段显示名 | 有 |
| `BP_VAR_MAX_WARNING` | 节点图变量数量已达上限 | 警告/错误文案 | 有 |
| `BP_VAR_NUM` | {0}个变量 | 控件/字段显示名 | 有 |
| `BP_VAR_PASTE` | 粘贴变量 | 控件/字段显示名 | 有 |
| `BP_VAR_RESET` | 重置变量 | 控件/字段显示名 | 有 |
| `BP_VAR_SET_PRIVATE` | 将{0}设置为私有，不可在局内编辑 | 控件/字段显示名 | 有 |
| `BP_VAR_SET_PUBLIC` | 将{0}设置为公开，可在局内编辑 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/VAR`

**功能域：节点图变量数据类型（26 种）** — 30 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `VAR_ENUM_NULL` | 空枚举 | 控件/字段显示名 | 有 |
| `VAR_TYPE_ARMY` | 阵营 | 控件/字段显示名 | 有 |
| `VAR_TYPE_ARMY_LIST` | 阵营列表 | 控件/字段显示名 | 有 |
| `VAR_TYPE_BOOL` | 布尔值 | 控件/字段显示名 | 有 |
| `VAR_TYPE_BOOLLIST` | 布尔值列表 | 控件/字段显示名 | 有 |
| `VAR_TYPE_CATEGORYTYPE` | 目录类型 | 控件/字段显示名 | 有 |
| `VAR_TYPE_COMPTYPE` | 组件类型 | 控件/字段显示名 | — |
| `VAR_TYPE_CONFIGREF` | 配置ID | 控件/字段显示名 | 有 |
| `VAR_TYPE_CONFIGREFLIST` | 配置ID列表 | 控件/字段显示名 | 有 |
| `VAR_TYPE_DEFINED_AS` | 数据类型定义为 | 控件/字段显示名 | 有 |
| `VAR_TYPE_ENTITY` | 实体 | 控件/字段显示名 | 有 |
| `VAR_TYPE_ENTITYLIST` | 实体列表 | 控件/字段显示名 | 有 |
| `VAR_TYPE_ENTITYREF` | 元件ID | 控件/字段显示名 | 有 |
| `VAR_TYPE_ENTITYREFLIST` | 元件ID列表 | 控件/字段显示名 | 有 |
| `VAR_TYPE_ENUM` | 枚举 | 控件/字段显示名 | 有 |
| `VAR_TYPE_ENUMLIST` | 枚举列表 | 控件/字段显示名 | 有 |
| `VAR_TYPE_FLOAT` | 浮点数 | 控件/字段显示名 | 有 |
| `VAR_TYPE_FLOATLIST` | 浮点数列表 | 控件/字段显示名 | 有 |
| `VAR_TYPE_GENERIC` | 泛型 | 控件/字段显示名 | 有 |
| `VAR_TYPE_GUID` | GUID | 控件/字段显示名 | 有 |
| `VAR_TYPE_GUIDLIST` | GUID列表 | 控件/字段显示名 | 有 |
| `VAR_TYPE_INT` | 整数 | 控件/字段显示名 | 有 |
| `VAR_TYPE_INTLIST` | 整数列表 | 控件/字段显示名 | 有 |
| `VAR_TYPE_STINGLIST` | 字符串列表 | 控件/字段显示名 | 有 |
| `VAR_TYPE_STRING` | 字符串 | 控件/字段显示名 | 有 |
| `VAR_TYPE_TYPE_LIMITED` | 类型受限 | 控件/字段显示名 | 有 |
| `VAR_TYPE_TYPE_LIMITED_BY` | 数据类型受到{0}限制 | 控件/字段显示名 | 有 |
| `VAR_TYPE_VARIABLE` | 局部变量 | 控件/字段显示名 | 有 |
| `VAR_TYPE_VECTOR3` | 三维向量 | 控件/字段显示名 | 有 |
| `VAR_TYPE_VECTOR3LIST` | 三维向量列表 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/ADVANCED`

**功能域：高级数据结构：结构体 / 字典 / 类型校验** — 20 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `ADVANCED_DATA_DICT` | 字典 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_DICT_KEY` | 键：{0} | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_DICT_KEY_PREVIEW` | 键 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_DICT_KEY_TYPE` | 键类型 | 控件/字段显示名 | — |
| `ADVANCED_DATA_DICT_RESET` | 还原为泛型 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_DICT_VALUE` | 值：{0} | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_DICT_VALUE_PREVIEW` | 值 | 控件/字段显示名 | — |
| `ADVANCED_DATA_DICT_VALUE_TYPE` | 值类型 | 控件/字段显示名 | — |
| `ADVANCED_DATA_ILLEGAL_WORDS` | 名称中包含非法单词 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_KEY_WARNING` | 字典键重复 | 警告/错误文案 | 有 |
| `ADVANCED_DATA_NONE_DEFAULT` | 无初始值 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_PASTE_WARNING` | 数据结构不匹配，不可粘贴 | 警告/错误文案 | 有 |
| `ADVANCED_DATA_QUICK_EDIT` | 快捷编辑 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_RESET_DEFAULT` | 还原为默认数据 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_STRUCT` | 结构体 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_STRUCT_EDIT_TARGET` | 修改对象 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_STRUCT_LIST` | 结构体列表 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_STRUCT_LIST_STATE` | {0} 列表 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_STRUCT_SELECT` | 请选择结构体变量 | 控件/字段显示名 | 有 |
| `ADVANCED_DATA_VAR_INDEX` | 变量_{0} | 控件/字段显示名 | 有 |
