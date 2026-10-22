> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

> **7.1版本复核（2026-09-26）**：下文保留原研究快照；旧地址、符号、统计全集和未找到结论不能直接视为7.1现状。当前接口迁移、Lua/协作等新增能力及验证边界见7.1复核报告（历史来源：`../../../7.1-revalidation/README.md`）。正文保留历史含义。

# 02-01a · UI 层文本清单 · 编辑器侧工具

> **调查的问题：** 千星编辑器界面上有哪些文本？它们各自命名了什么功能？
> **结论一句话：** 本文件覆盖 **8 个功能域 / 60 条键**（域：WPF、UI、CURSOR、SUITE、COSTLOAD、TAG、ATTACKTAG、COMPOMENT）。
> **最后更新：** 2026-09-22

读法、代码落点判据与全量统计见 00-总览.md（历史来源：`00-总览.md`）。

---

### `UI_BEYOND/EDITOR/WPF`

**功能域：历史记录（可撤销操作类型）+ 帮助入口** — 26 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `WPF_HELP_ENTRANCE` | 帮助 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_COMPOUNDNODES_DELETE` | 删除复合节点 | 控件/字段显示名 | — |
| `WPF_HISTORY_COMPOUNDNODES_EDIT` | 编辑复合节点 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_COMPOUNDNODES_NEW` | 生成复合节点 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_COMPOUNDNODES_OPEN` | 展开复合节点 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_CUT` | 剪切 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_CV_DELETE` | 删除节点图变量 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_CV_EDIT` | 修改节点图变量 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_CV_NEW` | 新建节点图变量 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_LINK_DELETE` | 断开引脚连线 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_LINK_DELETEALL` | 断开节点连线: {0} | 控件/字段显示名 | 有 |
| `WPF_HISTORY_LINK_NEW` | 连接引脚 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_MENTION_DELETE` | 删除注释 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_MENTION_EDIT` | 修改注释 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_MENTION_NEW` | 新建注释 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_NEW` | 起始 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_NODE_DELETE` | 删除节点: {0} | 控件/字段显示名 | 有 |
| `WPF_HISTORY_NODE_DELETE_PLURAL` | 批量删除节点 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_NODE_EDIT` | 修改节点: {0} | 控件/字段显示名 | 有 |
| `WPF_HISTORY_NODE_EDIT_PLURAL` | 批量编辑节点 | 控件/字段显示名 | — |
| `WPF_HISTORY_NODE_MOVE` | 移动节点: {0} | 控件/字段显示名 | 有 |
| `WPF_HISTORY_NODE_MOVE_PLURAL` | 批量移动节点 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_NODE_NEW` | 新建节点: {0} | 控件/字段显示名 | — |
| `WPF_HISTORY_PASTE` | 粘贴 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_SUBTITLE` | 历史记录 | 控件/字段显示名 | 有 |
| `WPF_HISTORY_TITLE` | 历史记录({0}/{1}) | 标题 | 有 |

### `UI_BEYOND/EDITOR/UI`

**功能域：玩家光标配置 / 造物状态蓝图调试日志 / 组件配置** — 21 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `UI_COMPONENT_CONFIG_CURSOR_COLLISION` | 光标碰撞盒 | 控件/字段显示名 | — |
| `UI_MONSTER_V2_BLUEPRINT_DEBUG_LOG_CHANGE_SKILL` | ;行为切换为尝试施放技能序号:{0} | 控件/字段显示名 | — |
| `UI_MONSTER_V2_BLUEPRINT_DEBUG_LOG_CHANGE_STATE` | ;状态蓝图ID切换为{0};AI参数模板序号为{1} | 控件/字段显示名 | — |
| `UI_MONSTER_V2_BLUEPRINT_DEBUG_LOG_CHANGE_TACTIC` | ;行为切换为尝试施放战术名称:{0} | 控件/字段显示名 | — |
| `UI_MONSTER_V2_BLUEPRINT_INSERT_DOWN` | 向下插入 | 控件/字段显示名 | 有 |
| `UI_MONSTER_V2_BLUEPRINT_INSERT_UP` | 向上插入 | 控件/字段显示名 | 有 |
| `UI_PLAYER_CURSOR_CLICKABLE_LAYER` | 可点击层级 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_LAYER_ALL` | 全部 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_LAYER_CURSORCOLLIDER` | 光标碰撞 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_LAYER_HITBOX` | 受击盒 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_LAYER_NONE` | 暂无 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_LAYER_OBJECTCOLLIDER` | 物件碰撞 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_LAYER_SCENE` | 场景 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_LAYER_SELECTALL` | 全选 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_MAX_SELECTABLE` | 光标最多可选取目标数 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_PENETRATE_UI` | 点击可穿透UI控件 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_PENETRATE_UI_TIPS` | 关闭时，光标点击穿过UI控件后不再打到场景物体 | 提示/说明文案 | — |
| `UI_PLAYER_CURSOR_PERSIST` | 光标常驻 | 控件/字段显示名 | — |
| `UI_PLAYER_CURSOR_PERSIST_TIPS` | 光标常驻关闭时, 光标相关的功能也无法生效 | 提示/说明文案 | — |
| `UI_PLAYER_CURSOR_TIPS_MOBILE` | 移动端点击屏幕时，响应此处配置的技能(仅支持瞬发技能)。 | 提示/说明文案 | — |
| `UI_PLAYER_CURSOR_TITLE` | 光标配置 | 标题 | — |

### `UI_BEYOND/EDITOR/CURSOR`

**功能域：光标碰撞盒** — 5 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `CURSOR_COLLISION_ADD` | 添加光标碰撞 | 控件/字段显示名 | — |
| `CURSOR_COLLISION_COMPOMENT_NAME` | 光标碰撞盒 | 名称/字段标签 | — |
| `CURSOR_COLLISION_COMPOMENT_NAME_LIST` | 光标碰撞{0} | 名称/字段标签 | — |
| `CURSOR_COLLISION_INITIAL_EFFECT_CURSOR_COLLISION_LIST` | 初始生效光标碰撞 | 控件/字段显示名 | — |
| `CURSOR_COLLISION_STRUCTURE_LIST` | 光标碰撞体列表 | 控件/字段显示名 | — |

### `UI_BEYOND/EDITOR/SUITE`

**功能域：实体布设组** — 3 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `SUITE_WPF_FILTER_NONE` | 暂无 | 控件/字段显示名 | 有 |
| `SUITE_WPF_FILTER_RESET` | 重置 | 控件/字段显示名 | — |
| `SUITE_WPF_TITLE` | 实体布设组 | 标题 | 有 |

### `UI_BEYOND/EDITOR/COSTLOAD`

**功能域：编辑器侧负载悬浮提示** — 2 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `COSTLOAD_STATIC_HOVER_TIPS_MEMORYPERFORM` | 内存负载为区域内的内存相关的负载指标，如贴图，模型，动画，特效等\n<color=#FDD990>临近负载上限：{0}处</color>\n<color=#FF8787>超负荷：{1}处</color>\n<color=#FF558D>严重超负荷：{2}处</color> | 提示/说明文案 | — |
| `COSTLOAD_STATIC_POPWINDOW_OVERALL_TOTALARCHIVE` | 存档 | 控件/字段显示名 | — |

### `UI_BEYOND/EDITOR/TAG`

**功能域：单位标签** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `TAG_WPF_TITLE` | 单位标签 | 标题 | 有 |

### `UI_BEYOND/EDITOR/ATTACKTAG`

**功能域：标签数量上限** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `ATTACKTAG_STRINGLIST_LIMIT` | 可添加数量达到上限 | 上限提示 | 有 |

### `UI_BEYOND/EDITOR/COMPOMENT`

**功能域：光标碰撞体数量上限** — 1 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `COMPOMENT_GENERAL_CURSOR_COLLISION_LIMIT_TIP` | 光标碰撞体数量已达上限 | 提示/说明文案 | — |
