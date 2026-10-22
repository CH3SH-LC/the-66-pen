> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

> **7.1版本复核（2026-09-26）**：下文保留原研究快照；旧地址、符号、统计全集和未找到结论不能直接视为7.1现状。当前接口迁移、Lua/协作等新增能力及验证边界见7.1复核报告（历史来源：`../../../7.1-revalidation/README.md`）。正文保留历史含义。

# 02-01a · UI 层文本清单 · 主窗口面板

> **调查的问题：** 千星编辑器界面上有哪些文本？它们各自命名了什么功能？
> **结论一句话：** 本文件覆盖 **19 个功能域 / 145 条键**（域：SIGNAL、ARMY、EXTERNAL、COSTLOAD、SCALE、SEARCH、DISCONNECT、SOUNDPLAYER、ADD、CONNECTION、EDIT、EXPAND、GENERATE、INSTRUCTION、JUMP、PCG、SERVER、STRUCT、WPF）。
> **最后更新：** 2026-09-22

读法、代码落点判据与全量统计见 00-总览.md（历史来源：`00-总览.md`）。

---

### `UI_BEYOND/ASSIST_EDITOR/SIGNAL`

**功能域：信号管理器** — 39 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `SIGNAL_ADD_NEW_SIGNAL` | 添加信号 | 控件/字段显示名 | 有 |
| `SIGNAL_ADD_NEW_VARIABLE` | 添加参数 | 控件/字段显示名 | 有 |
| `SIGNAL_APPLY_CHANGES` | 应用修改 | 控件/字段显示名 | 有 |
| `SIGNAL_BASIC_COPY` | 复制 | 控件/字段显示名 | 有 |
| `SIGNAL_BASIC_DELETE` | 删除 | 控件/字段显示名 | 有 |
| `SIGNAL_BASIC_PASTE` | 粘贴 | 控件/字段显示名 | 有 |
| `SIGNAL_BASIC_RENAME` | 重命名 | 控件/字段显示名 | 有 |
| `SIGNAL_BASIC_RESET` | 回退 | 控件/字段显示名 | 有 |
| `SIGNAL_CHARACTER_LIMIT_HINT` | 达到字数上限 | 上限提示 | 有 |
| `SIGNAL_CLICK_PLUS_BELOW_TO_CREATE_PARAMETER` | 点击加号创建参数 | 控件/字段显示名 | — |
| `SIGNAL_COMPOSITE_CURRENTLY_SELECTED` | 当前配置 | 控件/字段显示名 | — |
| `SIGNAL_COMPOSITE_SEARCH_RESOURCES` | 检索 | 搜索相关 | 有 |
| `SIGNAL_DATA_COPY_SUCCESSFUL` | 复制信号数据成功 | 控件/字段显示名 | 有 |
| `SIGNAL_DATA_OVERWRITE_SUCCESSFUL` | 覆盖信号数据成功 | 控件/字段显示名 | 有 |
| `SIGNAL_DATA_RESET_SUCCESSFUL` | 回退信号修改成功 | 控件/字段显示名 | 有 |
| `SIGNAL_DEFAULT_NAME` | 信号_{0} | 名称/字段标签 | 有 |
| `SIGNAL_DELETE_MODIFICATIONS` | 清空修改 | 控件/字段显示名 | 有 |
| `SIGNAL_EMPTY_STATE_NO_SELECTED_SIGNAL` | 请选择一个信号 | 空态文案 | — |
| `SIGNAL_EMPTY_STATE_NO_SIGNAL` | 暂无信号 | 空态文案 | — |
| `SIGNAL_ENTRY_HINT` | 信号管理 | 控件/字段显示名 | — |
| `SIGNAL_GO_TO_INTERFACE_TO_CREATE` | 前往创建信号 | 控件/字段显示名 | 有 |
| `SIGNAL_MODIFICATION_CAUSES_INTERLOCK_HINT` | 确认后所有使用位置也将被同步修改 | 控件/字段显示名 | — |
| `SIGNAL_MODIFIED_DATA_COUNT_HINT` | 个信号数据存在修改，确认保存吗？ | 控件/字段显示名 | — |
| `SIGNAL_NAME_ALREADY_EXISTS` | 名称已存在 | 名称/字段标签 | 有 |
| `SIGNAL_NAME_CANNOT_BE_EMPTY` | 名称不可为空 | 空态文案 | 有 |
| `SIGNAL_NO_MATCHING_RESULTS_FOUND` | 没有符合的信号 | 控件/字段显示名 | — |
| `SIGNAL_NO_PARAMETERS_AVAILABLE` | 暂无参数 | 控件/字段显示名 | — |
| `SIGNAL_REACHED_CREATION_LIMIT` | 超出单个关卡信号上限：{0} | 上限提示 | 有 |
| `SIGNAL_REFERENCE_COUNT_HINT` | 处节点图引用 | 控件/字段显示名 | 有 |
| `SIGNAL_REFERENCE_DATA_EMPTY_TIP` | 当前信号未被节点图引用 | 提示/说明文案 | 有 |
| `SIGNAL_SAVE_CHANGES_HINT` | 保存信号修改 | 控件/字段显示名 | — |
| `SIGNAL_SEARCH_TEXT_HINT` | 搜索信号 | 搜索相关 | — |
| `SIGNAL_SERVER_SIGNAL_MANAGEMENT` | 服务器信号管理器 | 控件/字段显示名 | 有 |
| `SIGNAL_SIGNAL_ADDITION_COUNT` | 数量 | 控件/字段显示名 | — |
| `SIGNAL_SIGNAL_MANAGEMENT_INTERFACE` | 服务器信号管理器 | 控件/字段显示名 | 有 |
| `SIGNAL_UNSAVED_CLOSE_WARNING` | 存在未保存的编辑内容，确认要关闭窗口吗？ | 警告/错误文案 | — |
| `SIGNAL_VARIABLE_DEFAULT_NAME` | 参数_{0} | 名称/字段标签 | 有 |
| `SIGNAL_VARIABLE_REACHED_CREATION_LIMIT` | 超出参数上限：{0} | 上限提示 | 有 |
| `SIGNAL_VIEW_REFERENCE_RELATIONS` | 查看节点图引用 | 控件/字段显示名 | — |

### `UI_BEYOND/ASSIST_EDITOR/ARMY`

**功能域：阵营选择** — 6 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `ARMY_CANCEL_CONCERN` | 确认 | 控件/字段显示名 | — |
| `ARMY_CANCEL_SELECT` | 取消 | 控件/字段显示名 | — |
| `ARMY_CHANGE_ARMY` | 更改阵营 | 控件/字段显示名 | 有 |
| `ARMY_FOLLOW_DEFAULT_ARMY` | 跟随默认阵营配置 | 控件/字段显示名 | 有 |
| `ARMY_SELECT_ARMY` | 在以下阵营中选择 | 控件/字段显示名 | — |
| `ARMY_TYPE` | 阵营 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/EXTERNAL`

**功能域：外部资产（转存 / 导入）** — 6 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `EXTERNAL_ASSETS_BP` | 外部资产节点图 | 控件/字段显示名 | 有 |
| `EXTERNAL_ASSETS_NAME` | 资产名称 | 名称/字段标签 | 有 |
| `EXTERNAL_ASSETS_NODE` | 外部资产节点 | 控件/字段显示名 | 有 |
| `EXTERNAL_ASSETS_PACKAGE` | 外部资产组合 | 控件/字段显示名 | 有 |
| `EXTERNAL_ASSETS_TAP` | 所属页签 | 控件/字段显示名 | 有 |
| `EXTERNAL_ASSETS_TITLE` | 转存资产 | 标题 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/COSTLOAD`

**功能域：负载检测：面板 / 归因表 / 服务端超限规则名** — 68 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `COSTLOAD_BTN_CTRL` | 开启负载测试 | 按钮 | — |
| `COSTLOAD_BTN_ENTER` | 负载检测 | 按钮 | 有 |
| `COSTLOAD_DETAILS_FUNCS_JUMPTOBP` | 打开节点图 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_SYSTEM` | 系统内容 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TITLEBAR_COST` | 负载 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TITLEBAR_ENTITY` | 所属实体 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TITLEBAR_FUNCTION` | 操作 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TITLEBAR_ID` | ID | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TITLEBAR_MAINTITLE` | 负载详情 | 控件/字段显示名 | — |
| `COSTLOAD_DETAILS_TITLEBAR_NAME` | 名称 | 名称/字段标签 | 有 |
| `COSTLOAD_DETAILS_TITLEBAR_PERCENT` | 负载占比 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TITLEBAR_TIMEDIFF` | 对比所选时刻 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TITLEBAR_TYPE` | 类型 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TYPE_AVATAR` | 角色 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TYPE_EFFECT` | 特效 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TYPE_ENTITY` | 静态实体 | 控件/字段显示名 | 有 |
| `COSTLOAD_DETAILS_TYPE_RUNTIMEENTITY` | 动态实体 | 控件/字段显示名 | — |
| `COSTLOAD_DETAILS_TYPE_TILEMAP` | 地形 | 控件/字段显示名 | 有 |
| `COSTLOAD_FILTER_AVATAR` | 角色 | 控件/字段显示名 | 有 |
| `COSTLOAD_FILTER_ENTITY` | 实体 | 控件/字段显示名 | 有 |
| `COSTLOAD_FILTER_ESP` | 环境 | 控件/字段显示名 | 有 |
| `COSTLOAD_FILTER_ESPFILE` | 环境配置 | 控件/字段显示名 | 有 |
| `COSTLOAD_FILTER_LIGHT` | 光源 | 控件/字段显示名 | 有 |
| `COSTLOAD_FILTER_TITLE` | 筛选条件 | 标题 | — |
| `COSTLOAD_LOGLIST_INPORT` | 导入日志 | 控件/字段显示名 | 有 |
| `COSTLOAD_LOGLIST_NONESELECTION` | 暂无日志 | 控件/字段显示名 | 有 |
| `COSTLOAD_LOGLIST_SELECTTIPS` | 请先选择日志 | 控件/字段显示名 | 有 |
| `COSTLOAD_LOG_HOVERTIPS_TEXT` | 该值代表节点图在本次运算过程中，所消耗的服务器处理器负载值，即：窗口期时间。单位为：毫秒； | 提示/说明文案 | 有 |
| `COSTLOAD_LOG_HOVERTIPS_TITLE` | 提示 | 提示/说明文案 | 有 |
| `COSTLOAD_LOG_TITLE` | 日志-{0} | 标题 | 有 |
| `COSTLOAD_NONEFORLOG_TEXT` | 需进行试玩以获得动态负载数据 | 控件/字段显示名 | 有 |
| `COSTLOAD_NONEFORLOG_TITLE` | 暂无日志 | 标题 | 有 |
| `COSTLOAD_NONEFOROVERCOST` | 本项指标未检测到异常 | 控件/字段显示名 | 有 |
| `COSTLOAD_NONEFORPROCESS_TEXT` | 动态负载检测需要在开启负载测试的情况下进行试玩 | 控件/字段显示名 | 有 |
| `COSTLOAD_NONEFORPROCESS_TITLE` | 负载检测未开启 | 标题 | 有 |
| `COSTLOAD_PLAYERLIST_PLAYERNAME` | 玩家{0} | 控件/字段显示名 | 有 |
| `COSTLOAD_SERVERMEMORY_OVERCOST` | 内存负载超载 | 控件/字段显示名 | — |
| `COSTLOAD_SERVERMEMORY_RECOMMODATIONS` | 建议 | 控件/字段显示名 | — |
| `COSTLOAD_SERVERMEMORY_TIME` | 时间 | 控件/字段显示名 | — |
| `COSTLOAD_SERVER_GETBYDBPPROCESSTHRESHOLDPERWINDOW` | 处理器负载消耗超过限制 | 控件/字段显示名 | 有 |
| `COSTLOAD_SERVER_GETMAXBYDBPPROCESSWORSEDELAYCNT` | 已延迟执行次数过多 | 控件/字段显示名 | 有 |
| `COSTLOAD_SERVER_GETMAXBYDCONTEXTCNTINONEPROCESS` | 节点图一次执行事件超过限制 | 控件/字段显示名 | 有 |
| `COSTLOAD_SERVER_GETMAXBYDNODEINONECONTEXT` | 节点图内运行节点数量超过限制 | 控件/字段显示名 | 有 |
| `COSTLOAD_SERVER_GETMAXBYDTIMEINONECONTEXT` | 节点图执行时间超过限制 | 控件/字段显示名 | 有 |
| `COSTLOAD_SERVER_OVERCOST` | 负载超载 | 控件/字段显示名 | 有 |
| `COSTLOAD_SERVER_RECOMMODATIONS` | 建议 | 控件/字段显示名 | — |
| `COSTLOAD_SERVER_SANDBOXCPULIMIT` | 沙盒时间超过限制 | 上限提示 | 有 |
| `COSTLOAD_TESTING_DISPLAYPERFORM` | 计算负载（客户端） | 控件/字段显示名 | 有 |
| `COSTLOAD_TESTING_MEMORY` | 内存负载（客户端） | 控件/字段显示名 | 有 |
| `COSTLOAD_TESTING_SERVERCPU` | 处理器（服务器） | 控件/字段显示名 | 有 |
| `COSTLOAD_TESTING_SERVERMEMORY` | 内存负载（服务器） | 控件/字段显示名 | 有 |
| `COSTLOAD_TESTING_SUBTITLE` | 当前负载状态 | 控件/字段显示名 | — |
| `COSTLOAD_TESTING_TITLE` | 试玩进行中 | 标题 | — |
| `COSTLOAD_TIMEDIFF_NONE` | 无对比时刻 | 控件/字段显示名 | 有 |
| `COSTLOAD_TIMEDIFF_TARGET` | 与{0}对比 | 控件/字段显示名 | 有 |
| `COSTLOAD_TIPS_OVERRENDERERLIMIT` | 当前关卡布设已达到上限，请删除部分布设再继续保存 | 提示/说明文案 | — |
| `COSTLOAD_TIPS_PERFORMCOST` | 是否开启负载测试？开启后可检测试玩过程中的负载情况\n注意：开启负载检测将会导致额外的负载消耗 | 提示/说明文案 | 有 |
| `COSTLOAD_TITLE_DISPLAYPERFORM` | 计算负载异常（客户端） | 标题 | 有 |
| `COSTLOAD_TITLE_MEMORY` | 内存负载异常（客户端） | 标题 | 有 |
| `COSTLOAD_TITLE_SERVERCPU` | 处理器异常（服务器） | 标题 | 有 |
| `COSTLOAD_TITLE_SERVERMEMORY` | 内存负载异常（服务器） | 标题 | 有 |
| `COSTLOAD_TLDETAILS_AVATAR` | 角色 | 控件/字段显示名 | 有 |
| `COSTLOAD_TLDETAILS_ENTITY` | 实体 | 控件/字段显示名 | 有 |
| `COSTLOAD_TLDETAILS_ESP` | 环境 | 控件/字段显示名 | 有 |
| `COSTLOAD_TLDETAILS_LINECHART` | 前后5秒内负载变化图 | 控件/字段显示名 | — |
| `COSTLOAD_TLDETAILS_PICS` | 异常时刻截图 | 控件/字段显示名 | — |
| `COSTLOAD_TLDETAILS_SYSTEM` | 其他 | 控件/字段显示名 | 有 |
| `COSTLOAD_TL_TITLE` | 异常时刻列表 | 标题 | — |

### `UI_BEYOND/ASSIST_EDITOR/SCALE`

**功能域：画布缩放** — 6 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `SCALE_100` | 100% | 控件/字段显示名 | 有 |
| `SCALE_150` | 150% | 控件/字段显示名 | 有 |
| `SCALE_200` | 200% | 控件/字段显示名 | 有 |
| `SCALE_50` | 50% | 控件/字段显示名 | 有 |
| `SCALE_ENLARGE` | 放大 | 控件/字段显示名 | 有 |
| `SCALE_REDUCE` | 缩小 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/SEARCH`

**功能域：搜索** — 3 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `SEARCH_NODE_TIPS` | 节点ID：{0} | 提示/说明文案 | 有 |
| `SEARCH_NONE_RESULTS_TIPS` | 当前分类下，没有符合条件的搜索结果 | 提示/说明文案 | 有 |
| `SEARCH_TIPS` | 在“{0}”中搜索 | 提示/说明文案 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/DISCONNECT`

**功能域：断开连线** — 4 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `DISCONNECT_ALL_CONNECTION` | 断开全部连线 | 控件/字段显示名 | 有 |
| `DISCONNECT_CONNECTION` | 断开此连接 | 控件/字段显示名 | 有 |
| `DISCONNECT_NODE` | 断开节点连线 | 控件/字段显示名 | 有 |
| `DISCONNECT_TO_NEXT_CONNECTION` | 断开到下个节点连线 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/SOUNDPLAYER`

**功能域：音效播放器** — 2 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `SOUNDPLAYER_OPTION_OPENSEARCH` | 打开检索栏 | 控件/字段显示名 | 有 |
| `SOUNDPLAYER_OPTION_RESET` | 重置 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/ADD`

**功能域：添加** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `ADD_PINS` | 添加引脚 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/CONNECTION`

**功能域：连线** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `CONNECTION_NUM_LIMIT` | 当前出引脚连线数量已达上限 | 上限提示 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/EDIT`

**功能域：编辑** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `EDIT_COMPOSITE_NODE` | 复合节点编辑 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/EXPAND`

**功能域：展开** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `EXPAND_COMPOSITE_NODE` | 展开复合节点 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/GENERATE`

**功能域：生成** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `GENERATE_COMPOSITE_NODE` | 生成复合节点 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/INSTRUCTION`

**功能域：帮助手册入口** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `INSTRUCTION_MANUAL` | 帮助 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/JUMP`

**功能域：跳转** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `JUMP_TO_NEXT_NODE` | 跳转到下个节点 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/PCG`

**功能域：场景生成模板** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `PCG_WPF_TYPE_NAME` | 场景生成模板 | 名称/字段标签 | — |

### `UI_BEYOND/ASSIST_EDITOR/SERVER`

**功能域：服务器节点图** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `SERVER_BP_EDITING` | 服务器节点图编辑 | 控件/字段显示名 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/STRUCT`

**功能域：结构体** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `STRUCT_ADD_WARNING` | 字典键类型为实体，无法添加 | 警告/错误文案 | 有 |

### `UI_BEYOND/ASSIST_EDITOR/WPF`

**功能域：等待/重启异常提示** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `WPF_WAITING_WARNING` | 请等待或重启千星沙箱后重试 | 警告/错误文案 | 有 |
