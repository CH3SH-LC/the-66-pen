> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

> **7.1版本复核（2026-09-26）**：下文保留原研究快照；旧地址、符号、统计全集和未找到结论不能直接视为7.1现状。当前接口迁移、Lua/协作等新增能力及验证边界见7.1复核报告（历史来源：`../../../7.1-revalidation/README.md`）。正文保留历史含义。

# 02-01a · UI 层文本清单 · 编辑器侧工具

> **调查的问题：** 千星编辑器界面上有哪些文本？它们各自命名了什么功能？
> **结论一句话：** 本文件覆盖 **3 个功能域 / 258 条键**（域：ESP、ESP2、PROTOTYPE）。
> **最后更新：** 2026-09-22

读法、代码落点判据与全量统计见 00-总览.md（历史来源：`00-总览.md`）。

---

### `UI_BEYOND/EDITOR/ESP`

**功能域：关卡环境配置（背景 / 天气 / 距离雾 / 高度雾 / 光源管理）** — 171 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `ESP_LIGHTCAMP_ACTIVATEAREA` | 生效范围 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_ADDLIGHT` | 添加光源 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_ATTCHPT_LOCATION` | 偏移 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_ATTCHPT_ROTATION` | 旋转 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_ATTCHPT_TITLE` | 挂接点 | 标题 | — |
| `ESP_LIGHTCAMP_COLOR` | 颜色 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_DETAILS` | 详细编辑 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_INILIGHTS` | 初始生效光源 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_INISWITCH` | 初始生效 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_INTENSITY` | 强度 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_LIGHTID` | 光源序号 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_LIGHTLIST` | 光源列表 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_LIGHTNAME` | 光源 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_LIGHTTITLE` | 光源 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_LIGHTTYPE` | 光源类型 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_LOCATION` | 位置 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_NONESELECTED` | 暂无 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_PREVIEWAREA` | 生效范围预览 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_PTLIGHT` | 点光源 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_RANGE` | 半径 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_ROTATION` | 旋转 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_SETLIGHTNAME` | 光源名称 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_SPOTANGLE` | 角度 | 控件/字段显示名 | — |
| `ESP_LIGHTCAMP_SPOTLIGHT` | 聚光灯 | 控件/字段显示名 | — |
| `ESP_LIGHTING_BLUE` | 蓝色 | 控件/字段显示名 | — |
| `ESP_LIGHTING_COLOR` | 颜色 | 控件/字段显示名 | — |
| `ESP_LIGHTING_CREATEOVERLIMITS` | 创建环境光源数量到达上限 | 控件/字段显示名 | — |
| `ESP_LIGHTING_ESCNAME` | 光源管理 | 控件/字段显示名 | — |
| `ESP_LIGHTING_GREEN` | 绿色 | 控件/字段显示名 | — |
| `ESP_LIGHTING_INTENSITY` | 强度 | 控件/字段显示名 | — |
| `ESP_LIGHTING_LEVELSETTING_ESP` | 背景 | 控件/字段显示名 | — |
| `ESP_LIGHTING_LEVELSETTING_LIGHTS` | 灯光列表 | 控件/字段显示名 | — |
| `ESP_LIGHTING_LEVELSETTING_NAME` | 环境设置 | 名称/字段标签 | — |
| `ESP_LIGHTING_LEVELSETTING_NONE` | 无 | 控件/字段显示名 | — |
| `ESP_LIGHTING_LEVELSETTING_PROFILE` | 读取配置文件 | 控件/字段显示名 | — |
| `ESP_LIGHTING_LEVELSETTING_WEATHER` | 天气 | 控件/字段显示名 | — |
| `ESP_LIGHTING_NAME` | 光源 | 名称/字段标签 | — |
| `ESP_LIGHTING_NEW` | 新建光源 | 控件/字段显示名 | — |
| `ESP_LIGHTING_NONEPROFILE` | 暂无内容 | 控件/字段显示名 | — |
| `ESP_LIGHTING_NONESELECTED` | 无 | 控件/字段显示名 | — |
| `ESP_LIGHTING_ORANGE` | 橙色 | 控件/字段显示名 | — |
| `ESP_LIGHTING_PTLIGHT` | 点光源 | 控件/字段显示名 | — |
| `ESP_LIGHTING_PT_INTENSITY` | 强度 | 控件/字段显示名 | — |
| `ESP_LIGHTING_PT_RANGE` | 半径 | 控件/字段显示名 | — |
| `ESP_LIGHTING_RANGE` | 范围 | 控件/字段显示名 | — |
| `ESP_LIGHTING_RED` | 红色 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SELECT_ALL` | 全选 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SELECT_NONE` | 暂无 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SORTBYNAME` | 按名称排序 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SPOTANGLE` | 角度 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SPOTLIGHT` | 聚光灯 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SUBTITLE_ACTIVATEAREA` | 生效范围 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SUBTITLE_LIGHTSETS` | 光源设置 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SUBTITLE_LIGHTTYPE` | 光源类型 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SUBTITLE_LOCATION` | 位置 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SUBTITLE_PARAMETER` | 基础属性 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SUBTITLE_PREVIEWAREA` | 生效范围预览 | 控件/字段显示名 | — |
| `ESP_LIGHTING_SUBTITLE_ROTATION` | 旋转 | 控件/字段显示名 | — |
| `ESP_LIGHTING_TITLE` | 光源管理 | 标题 | — |
| `ESP_LIGHTING_UNDERPROFILE` | 归属文件 | 控件/字段显示名 | — |
| `ESP_LIGHTING_WHITE` | 白色 | 控件/字段显示名 | — |
| `ESP_LUTNAME_BLUE` | 蓝色 | 控件/字段显示名 | — |
| `ESP_LUTNAME_CAMPOVERLIMIT` | 组件数量达到上限 | 上限提示 | — |
| `ESP_LUTNAME_CYAN` | 青色 | 控件/字段显示名 | — |
| `ESP_LUTNAME_DEFAULT` | 默认 | 控件/字段显示名 | — |
| `ESP_LUTNAME_DUPLICATION` | 名称重名 | 控件/字段显示名 | — |
| `ESP_LUTNAME_MONOCHROME` | 黑白 | 控件/字段显示名 | — |
| `ESP_LUTNAME_NONETYPE` | 名称不合法 | 控件/字段显示名 | — |
| `ESP_LUTNAME_OVERLIMIT` | 名称超出最大字数 | 上限提示 | — |
| `ESP_LUTNAME_PURPLE` | 紫色 | 控件/字段显示名 | — |
| `ESP_LUTNAME_RED` | 红色 | 控件/字段显示名 | — |
| `ESP_LUTNAME_YELLOW` | 黄色 | 控件/字段显示名 | — |
| `ESP_LUT_SELECT_ALL` | 全选 | 控件/字段显示名 | — |
| `ESP_PRESETNAME_BLUE` | 蓝色 | 控件/字段显示名 | — |
| `ESP_PRESETNAME_GREEN` | 绿色 | 控件/字段显示名 | — |
| `ESP_PRESETNAME_NORMAL` | 正常 | 控件/字段显示名 | — |
| `ESP_PRESETNAME_PURPLE` | 紫色 | 控件/字段显示名 | — |
| `ESP_PRESETNAME_RED` | 红色 | 控件/字段显示名 | — |
| `ESP_PROFILE_AMBIGUITY` | 模糊程度 | 控件/字段显示名 | — |
| `ESP_PROFILE_ANGLE` | 直射角 | 控件/字段显示名 | — |
| `ESP_PROFILE_APPLYTO` | 生效目标 | 控件/字段显示名 | — |
| `ESP_PROFILE_BYTIME` | 随时间自动切换 | 控件/字段显示名 | — |
| `ESP_PROFILE_CANCEL` | 取消 | 控件/字段显示名 | — |
| `ESP_PROFILE_CLOUD` | 云 | 控件/字段显示名 | — |
| `ESP_PROFILE_CLOUD_ALL` | 全部 | 控件/字段显示名 | — |
| `ESP_PROFILE_CLOUD_HIGH` | 高云 | 控件/字段显示名 | — |
| `ESP_PROFILE_CLOUD_LOW` | 低云 | 控件/字段显示名 | — |
| `ESP_PROFILE_CLOUD_MID` | 中云 | 控件/字段显示名 | — |
| `ESP_PROFILE_CLOUD_SELECT_NONE` | 暂无 | 控件/字段显示名 | — |
| `ESP_PROFILE_CLOUD_STRENGTH` | 强度 | 控件/字段显示名 | — |
| `ESP_PROFILE_CLOUD_TYPE` | 类型 | 控件/字段显示名 | — |
| `ESP_PROFILE_ELEMENT` | 环境要素 | 控件/字段显示名 | — |
| `ESP_PROFILE_FILTER` | 滤镜风格 | 控件/字段显示名 | — |
| `ESP_PROFILE_GALAXY` | 银河 | 控件/字段显示名 | — |
| `ESP_PROFILE_GALAXY_COLOR` | 受光颜色 | 控件/字段显示名 | — |
| `ESP_PROFILE_GALAXY_STRENGTH` | 强度 | 控件/字段显示名 | — |
| `ESP_PROFILE_INTENSITY` | 强度 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHTCOLOR` | 受光颜色 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHTCOLOR_BLUE` | 蓝色 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHTCOLOR_DEFAULT` | 默认 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHTCOLOR_GREEN` | 绿色 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHTCOLOR_ORANGE` | 橙色 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHTCOLOR_RED` | 红色 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHTCOLOR_WHITE` | 白色 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHT_ADD` | 添加光源 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHT_ADD_ADD` | 点击下方按钮前往创建 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHT_ADD_JUMPTOEDITOR` | 打开光源管理工具 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHT_ADD_NONE` | 暂无内容 | 控件/字段显示名 | — |
| `ESP_PROFILE_LIGHT_ADD_TITLE` | 添加光源 | 标题 | — |
| `ESP_PROFILE_LIGHT_LIST` | 光源列表 | 控件/字段显示名 | — |
| `ESP_PROFILE_NEWPROFILE` | 新建环境 | 控件/字段显示名 | — |
| `ESP_PROFILE_NEW_CONFIRM` | 确认 | 确认对话框 | — |
| `ESP_PROFILE_NEW_DEFAULTTYPE` | 默认 | 控件/字段显示名 | — |
| `ESP_PROFILE_NEW_NAME` | 环境配置名称 | 名称/字段标签 | — |
| `ESP_PROFILE_NEW_TITLE` | 新建环境配置 | 标题 | — |
| `ESP_PROFILE_NEW_TYPE` | 环境配置所属分类 | 控件/字段显示名 | — |
| `ESP_PROFILE_PROFILENAME` | 环境配置 | 控件/字段显示名 | — |
| `ESP_PROFILE_RIGHTKEY_RENAME` | 重命名 | 控件/字段显示名 | — |
| `ESP_PROFILE_ROTATION` | 背景旋转 | 控件/字段显示名 | — |
| `ESP_PROFILE_SAVEAS` | 另存为 | 控件/字段显示名 | — |
| `ESP_PROFILE_SELECTPLAYER` | 选择玩家 | 控件/字段显示名 | — |
| `ESP_PROFILE_SHADOWCOLOR` | 阴影颜色 | 控件/字段显示名 | — |
| `ESP_PROFILE_SKYCOLOR` | 天空背景色 | 控件/字段显示名 | — |
| `ESP_PROFILE_STAR` | 星星 | 控件/字段显示名 | — |
| `ESP_PROFILE_STAR_DENSITY` | 密度 | 控件/字段显示名 | — |
| `ESP_PROFILE_STAR_STRENGTH` | 强度 | 控件/字段显示名 | — |
| `ESP_PROFILE_STYLE` | 背景预设 | 控件/字段显示名 | — |
| `ESP_PROFILE_TAB_DEFAULTTAB` | 默认 | 页签/分类名 | 有 |
| `ESP_PROFILE_TAB_TABNAME` | 环境配置 | 页签/分类名 | — |
| `ESP_PROFILE_TIMESETTINGS` | 设定时间点 | 控件/字段显示名 | — |
| `ESP_PROFILE_TIPS_CONFIRM` | 确认删除 | 提示/说明文案 | — |
| `ESP_PROFILE_TIPS_DELETETIPS` | 是否删除{0}？\n删除后当前存档的环境配置引用将丢失 | 提示/说明文案 | — |
| `ESP_PROFILE_TIPS_TITLE` | 提示 | 提示/说明文案 | — |
| `ESP_PROFILE_TITLE_STYLE` | 背景设置 | 标题 | — |
| `ESP_PROFILE_WEATHER` | 天气配置 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_AVATARFOG_ATTENUATION` | 范围衰减 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_AVATARFOG_ATTENUATIONLOC` | 雾气衰减距离(m) | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_AVATARFOG_AVATAR` | 预览效果 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_AVATARFOG_COLOR` | 颜色 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_AVATARFOG_RANGE` | 范围 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_AVATARFOG_SETTINGS` | 高度雾设置 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_AVATARFOG_SHELD` | 雾气起始距离(m) | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_AVATARFOG_SWITCH` | 启用高度雾 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_AVATARFOG_Y` | 雾气高度(m) | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_DISFOG_COLOR` | 颜色 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_DISFOG_PT1DIS` | 近雾点距离(m) | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_DISFOG_PT1INTENSITY` | 近雾点浓度 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_DISFOG_PT2DIS` | 远雾点距离(m) | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_DISFOG_PT2INTENSITY` | 天空受雾浓度 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_DISFOG_SETTINGS` | 距离雾设置 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_DISFOG_SWITCH` | 启用距离雾 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_FOG` | 雾 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_ID` | 索引 {0} | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_INISWITCH` | 初始生效 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_INITIAL` | 初始生效 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_NAME_DUPLICATION` | 名称重名 | 名称/字段标签 | — |
| `ESP_PROFILE_WEATHEREDIT_NAME_NONETYPE` | 名称不合法 | 名称/字段标签 | — |
| `ESP_PROFILE_WEATHEREDIT_NAME_OVERLIMIT` | 名称超出最大字数 | 上限提示 | — |
| `ESP_PROFILE_WEATHEREDIT_NONE` | 暂无 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_SETNAME` | 基础设置 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHEREDIT_TITLE` | 天气配置 | 标题 | — |
| `ESP_PROFILE_WEATHEREDIT_TYPE` | 天气类型 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHER_DETAILS` | 详情编辑 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHER_INI` | 初始生效天气 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHER_LIST` | 天气列表 | 控件/字段显示名 | — |
| `ESP_PROFILE_WEATHER_NAME` | 天气 | 名称/字段标签 | — |
| `ESP_PROFILE_WEATHER_NONE` | 暂无 | 控件/字段显示名 | — |
| `ESP_TIME_INITIME` | 关卡初始时间点 | 控件/字段显示名 | — |
| `ESP_TIME_TIMERATE` | 每秒流逝时间（分钟） | 控件/字段显示名 | — |
| `ESP_TIME_TITLE` | 时间设置 | 标题 | — |
| `ESP_TIPS_ONLYFORENTITYANDENVIROEDITMODE` | 只能在实体摆放页签或地形编辑页签使用 | 提示/说明文案 | — |

### `UI_BEYOND/EDITOR/ESP2`

**功能域：环境配置补充项** — 2 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `ESP2_SHADOWCOLOR` | 环境颜色 | 控件/字段显示名 | — |
| `ESP2_TIP1` | 不影响特效默认音效的播放速度 | 提示/说明文案 | — |

### `UI_BEYOND/EDITOR/PROTOTYPE`

**功能域：编辑工具（测距线 / 阵列 / 对称 / 3D 备注 / 复制变换）** — 85 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `PROTOTYPE_ARRAY_ANGLE` | 角度 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_ARRAY` | 阵列 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_ARRAYAXISPOSITION` | 阵列轴位置 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_ARRAYAXISVECTOR` | 阵列轴向量 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_ARRAYOBJECT` | 阵列对象 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_ARRAYOBJECT({0})` | 阵列对象({0}) | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_ARRAYSETTINGS` | 阵列设置 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_CIRCULARARRAY` | 环形阵列 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_CONFIRMCREATION` | 确认创建 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_GRIDARRAY` | 网格阵列 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_GRIDDIMENSIONS` | 阵列间隔 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_NUMBEROFGRIDS` | 阵列数量 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_PREVIEW` | 预览 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_QUANTITY` | 数量 | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_X` | X | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_Y` | Y | 控件/字段显示名 | — |
| `PROTOTYPE_ARRAY_Z` | Z | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_CANCEL` | 取消 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_CENTREPOINTPOSITION` | 中心点位置 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_COPY` | 复制 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_COPYENTITYDATA` | 复制实体数据 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_DELETE` | 删除 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_GENERATE` | 生成 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_GENERATINGENTITY` | 实体生成中... | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_GENERATINGPREVIEWCONTENT` | 预览内容生成中... | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_PASTE` | 粘贴 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_PASTEENTITYDATA` | 粘贴实体数据 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_PREVIEW` | 预览 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_TRANSFORM` | 变换 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_VIEWINAUTOCAD` | 在局内查看 | 控件/字段显示名 | — |
| `PROTOTYPE_EDITORTOOL_{0}OBJECTS` | {0}个对象 | 控件/字段显示名 | — |
| `PROTOTYPE_GAMEOBJECT_BOUNDINGBOXANDDIMENSIONS` | 包围盒及尺寸 | 控件/字段显示名 | — |
| `PROTOTYPE_GAMEOBJECT_COLLISIONANDDIMENSIONS` | 碰撞及尺寸 | 控件/字段显示名 | — |
| `PROTOTYPE_GAMEOBJECT_DIMENSIONSONLY` | 仅尺寸 | 控件/字段显示名 | — |
| `PROTOTYPE_GAMEOBJECT_GRIDLINES` | 网格线 | 控件/字段显示名 | — |
| `PROTOTYPE_GAMEOBJECT_NONE` | 无 | 控件/字段显示名 | — |
| `PROTOTYPE_GAMEOBJECT_TYPE` | 显示类型 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_ADDMEASUREMENTLINES` | 添加测距线 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_CANCEL` | 取消 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_CONFIRM` | 确认 | 确认对话框 | — |
| `PROTOTYPE_LINE_COPY` | 复制测算距离 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_DELETE` | 删除测距线 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_INS_BASICPROPERTIES` | 基础属性 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_INS_LOCKTRANSFORMATION` | 锁定变换 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_INS_MEASUREMENTLINES` | 测距线 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_INS_MEASUREMENTPOINTS` | 测距点 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_INS_POSITION` | 位置 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_INS_SCALE(m)` | 刻度(m) | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_MEASUREMENTLINES` | 测距线 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_METER` | {0}m | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_METERTAG` | 长度(m) | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_OVERLIMITS` | 测距线数量已达上限 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_REMOVEALL` | 全部移除 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_SETS_ALWAYSSHOWMEASUREMENTLINES` | 测距线常驻显示 | 控件/字段显示名 | — |
| `PROTOTYPE_LINE_TIP` | 是否清除所有测距线？ | 提示/说明文案 | — |
| `PROTOTYPE_LINE_TIPS` | 点击放置测距线起点和终点 | 提示/说明文案 | — |
| `PROTOTYPE_LINE_TIPTITLE` | 提示 | 提示/说明文案 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY` | 对称 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_AXIS` | 轴 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_AXISSYMMETRY` | 轴对称 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_FACE` | 面 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_FACESYMMETRY` | 面对称 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_FACESYMMETRYPOSITION` | 对称面位置 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_FACESYMMETRYROTATION` | 对称面旋转 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_KEEPORIGINALOBJECT` | 保留原物件 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_POINT` | 点 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_POINTSYMMETRY` | 点对称 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_ROTATESYMMETRYAXIS` | 对称轴旋转 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_ROTATESYMMETRYPOSITION` | 对称轴位置 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_SYMMETRICOBJECT` | 对称对象 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_SYMMETRICOBJECT({0})` | 对称对象({0}) | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_SYMMETRYGENERATION` | 对称生成 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_SYMMETRYMODE` | 对称模式 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_SYMMETRYPOINTPOSITION` | 对称点位置 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_SYMMETRYSETTINGS` | 对称设置 | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_X` | X | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_Y` | Y | 控件/字段显示名 | — |
| `PROTOTYPE_SYMMETRY_SYMMETRY_Z` | Z | 控件/字段显示名 | — |
| `PROTOTYPE_TIPS_OVERLIMITS` | 创建失败，创建的内容不可超过100个 | 提示/说明文案 | — |
| `PROTOTYPE_TIPTOOL_3DANNOTATIONACCEPTANCE` | 3D备注颜色 | 提示/说明文案 | — |
| `PROTOTYPE_TIPTOOL_EDITTOOLS` | 编辑工具 | 提示/说明文案 | — |
| `PROTOTYPE_TIPTOOL_NOTES` | 备注 | 提示/说明文案 | — |
| `PROTOTYPE_TIPTOOL_OVERALLSETS` | 备注常驻显示 | 提示/说明文案 | — |
| `PROTOTYPE_TIPTOOL_SHOW3DNOTES` | 显示3D备注 | 提示/说明文案 | — |
| `PROTOTYPE_TIPTOOL_SHOWZ-AXISDIRECTION` | 显示Z轴朝向 | 提示/说明文案 | — |
