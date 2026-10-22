> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

> **7.1版本复核（2026-09-26）**：下文保留原研究快照；旧地址、符号、统计全集和未找到结论不能直接视为7.1现状。当前接口迁移、Lua/协作等新增能力及验证边界见7.1复核报告（历史来源：`../../../7.1-revalidation/README.md`）。正文保留历史含义。

# 02-01a · UI 层文本清单 · 编辑器侧工具

> **调查的问题：** 千星编辑器界面上有哪些文本？它们各自命名了什么功能？
> **结论一句话：** 本文件覆盖 **1 个功能域 / 172 条键**（域：VFXEDITOR）。
> **最后更新：** 2026-09-22

读法、代码落点判据与全量统计见 00-总览.md（历史来源：`00-总览.md`）。

---

### `UI_BEYOND/EDITOR/VFXEDITOR`

**功能域：特效器编辑器（轨道 / 事件 / 循环节 / 预警特效 / 元素属性）** — 172 条。

| 键（省公共前缀） | 中文文本 | 命名对象 | 代码落点 |
|---|---|---|---|
| `VFXEDITOR_ASSETSICON` | 特效资产图标库 | 控件/字段显示名 | — |
| `VFXEDITOR_COMP_ASSETTITLE` | 特效器 | 控件/字段显示名 | — |
| `VFXEDITOR_CONFIRM` | 确认创建 | 确认对话框 | — |
| `VFXEDITOR_EDITOR_ASSETLIST_NONE` | 暂无内容 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_CONTINUOUS` | 持续 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_DURATION` | 持续时长 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_EDITINGPERIOD` | 当前编辑时间段 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_FILTER_BOOL` | 布尔 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_FILTER_CAMPLIST` | 可见阵营列表 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_FILTER_CHOOSEBP` | 点击选择 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_FILTER_ENEMY` | 敌方阵营 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_FILTER_FRIENDLY` | 友方阵营 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_FILTER_LOCAL` | 本地过滤器 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_FILTER_SAME` | 相同阵营 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_FILTER_TITLE` | 可见性设置 | 标题 | — |
| `VFXEDITOR_EDITOR_FILTER_TYPE` | 过滤器类型 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_HIDE3DICON` | 显示三维图标 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_LOOP_END` | 循环节终点(s) | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_LOOP_OPEN` | 启用循环节 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_LOOP_SETTINGS` | 循环节设置 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_LOOP_START` | 循环节起点(s) | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_LOOP_TIMELESS` | 无限循环 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_LOOP_TIMES` | 循环次数 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_MAINTITLE` | 特效器编辑 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_NODE_SOUND` | 音效播放 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_NODE_VFX` | 特效播放 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_COLOR` | 填充颜色 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_CONTINUOUS` | 持续播放 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_DIRECTION` | 填充方向 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_DURATION` | 填充时间(s) | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_ELEMENTS` | 附加元素属性 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_SACLE` | 缩放比例 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_SETASSETTIME` | 设为资产时长 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_SPEED` | 特效表现播放速度 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_VFXID` | 特效块ID | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_WARNNINGVFXTITLE` | 预警特效 | 警告/错误文案 | — |
| `VFXEDITOR_EDITOR_PROPERTY_XM` | X方向长度(m) | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_PROPERTY_ZM` | Z方向长度(m) | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_RIGHTKEY_ADDEVENT` | 从蓝线处添加事件 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_RIGHTKEY_ADDLOOP` | 从蓝线处开启循环节 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_RIGHTKEY_ADDSOUND` | 音效 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_RIGHTKEY_COPYEVENT` | 复制事件 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_RIGHTKEY_DELETEEVENT` | 删除事件 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_RIGHTKEY_ENDLOOP` | 从蓝线处终止循环节 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_RIGHTKEY_PASTEEVNET` | 粘贴事件 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_RIGHTKEY_VFX` | 特效 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_RIGHTKEY_WARNNINGVFX` | 预警特效 | 警告/错误文案 | — |
| `VFXEDITOR_EDITOR_TRACKSETTINGS` | 轨道设置 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_TRACK_COPYDATA` | 复制所有轨道数据 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_TRACK_EVENTLIST` | 打开事件列表 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_TRACK_PASTEDATA` | 粘贴所有轨道数据 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_TYPE` | 特效器类型 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_TYPE_CONTINUOUS` | 持续特效器 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_TYPE_FIRE` | 限时特效器 | 控件/字段显示名 | — |
| `VFXEDITOR_EDITOR_WARNNINGVFXASSET` | 预警特效库 | 警告/错误文案 | — |
| `VFXEDITOR_EX1_COLLECTION` | 更换页签 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_CONTINUOUS` | 持续播放 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_DELETE` | 删除 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_EXPORT` | 导出资产 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_ID` | ID | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_LOCATION` | 偏移 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_NUMBERS` | ×{0} | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_PREVIEW` | 预览 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_RENAME` | 重命名 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_ROTATION` | 旋转 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_SAVE` | 保存 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_SAVEAS` | 另存为 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_SCALE` | 缩放 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_SETTIME` | 设置为资产时长 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_SETTINGS` | 基础设置 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_SOUND` | 播放特效默认音效 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_STOP` | 停止预览 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_TIME` | 时长 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_VFXPARASETTINS` | 特效块基础参数设置 | 控件/字段显示名 | — |
| `VFXEDITOR_EX1_VFXSETTINGS` | 特效块设置 | 控件/字段显示名 | — |
| `VFXEDITOR_EX2_FIREEVENT` | 销毁时行为 | 控件/字段显示名 | — |
| `VFXEDITOR_EX2_FIRE_CLEAR` | 停止并清除特效 | 控件/字段显示名 | — |
| `VFXEDITOR_EX2_FIRE_TIME` | 停止并设置粒子残留时间 | 控件/字段显示名 | — |
| `VFXEDITOR_EX2_HIDE` | 隐藏时行为 | 控件/字段显示名 | — |
| `VFXEDITOR_EX2_HIDE_HIDEVFX` | 同步隐藏特效 | 控件/字段显示名 | — |
| `VFXEDITOR_EX2_HIDE_IGNORE` | 无视隐藏 | 控件/字段显示名 | — |
| `VFXEDITOR_EX2_RESIDENTTIME` | 粒子残留时间 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_BLOCK` | 屏蔽轨道 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_DEFAULTTRACK` | 普通轨道 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_DELETE` | 删除轨道 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_EXPORT_VFX` | 特效器 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_HIDE` | 隐藏轨道 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_HIERACHY` | 事件管理 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_LOOPSETTINGS` | 循环节轨道 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_NEW` | 新建轨道 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_NONE` | 暂无事件 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_RENAME` | 重命名 | 控件/字段显示名 | — |
| `VFXEDITOR_EX3_UNBLOCK` | 激活轨道 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_ADDEVENTATLINE` | 添加事件 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_ADDLOOPTRACK` | 新建循环节轨道 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_ADDTRACK` | 新建普通轨道 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_ANEMO` | 风 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_ASEET` | 特效库 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_ASSET_FIREEX` | 限时特效 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_ASSET_LOOPEX` | 循环特效 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_CAMP_ALL` | 全部 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_CAMP_ENEMY` | 敌对阵营 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_CAMP_PARTNER` | 友善阵营 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_CAMP_SAME` | 同阵营 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_CRYO` | 冰 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_DECAL` | 贴地高度 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_DENDRO` | 草 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_ELECTRO` | 雷 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_EXPARA` | 特效参数设置 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_FIREEX` | 限时特效 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_GEO` | 岩 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_HYDRO` | 水 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_INSPECTOR_FIRE` | 是否存在销毁时行为 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_LOOPEX` | 循环特效 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_LOOPTIME` | 循环节时长(s) | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_MULTIFACTOR` | X{0} | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_NONE` | 无 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_NONE2` | 无 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_ORIGINPT` | 坐标原点 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_PERIOD` | 保持时间 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_PREVIEWSETTINGS` | 仅在预览时生效 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_PROP` | 无 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_PYRO` | 火 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_SELECTASSET` | 点击选择特效资产 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_SOUNDASSET` | 音效资源 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_SOUNDTRACKSETTINGS` | 音效轨道设置 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_STOPEMIT` | 停止粒子发射 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_STOPEVENT_FIREVFX` | 销毁特效 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_TRACKDEFAULTNAME` | 新建轨道 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_TRACKSETTINGS` | 特效轨道设置 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_TRANSFORM` | 坐标变换 | 控件/字段显示名 | — |
| `VFXEDITOR_EX4_WPF_TYPE_FIREVFX` | 限时特效 | 控件/字段显示名 | 有 |
| `VFXEDITOR_EX4_WPF_TYPE_FIREVFXEDITOR` | 限时特效器 | 控件/字段显示名 | 有 |
| `VFXEDITOR_EX4_WPF_TYPE_LOOPVFX` | 循环特效 | 控件/字段显示名 | 有 |
| `VFXEDITOR_EX4_WPF_TYPE_LOOPVFXEDITOR` | 持续特效器 | 控件/字段显示名 | 有 |
| `VFXEDITOR_INSPECTOR_ASSETLIST` | 资产引用 | 控件/字段显示名 | — |
| `VFXEDITOR_INSPECTOR_CONTINUOUS` | 持续特效器 | 控件/字段显示名 | — |
| `VFXEDITOR_INSPECTOR_DURATION` | 持续时长 | 控件/字段显示名 | — |
| `VFXEDITOR_INSPECTOR_FIRE` | 限时特效器 | 控件/字段显示名 | — |
| `VFXEDITOR_INSPECTOR_JUMPTOEDITOR` | 特效器编辑 | 控件/字段显示名 | — |
| `VFXEDITOR_INSPECTOR_NOTE` | 特效器备注 | 控件/字段显示名 | — |
| `VFXEDITOR_INSPECTOR_PREVIEW` | 预览 | 控件/字段显示名 | — |
| `VFXEDITOR_INSPECTOR_SOUNDASSET` | 音效列表{0} | 控件/字段显示名 | — |
| `VFXEDITOR_INSPECTOR_TYPE` | 特效器类型 | 控件/字段显示名 | — |
| `VFXEDITOR_INSPECTOR_VFXASSET` | 特效列表{0} | 控件/字段显示名 | — |
| `VFXEDITOR_JUMPTOEDITOR` | 前往特效器编辑 | 控件/字段显示名 | — |
| `VFXEDITOR_NAME` | 特效器 | 名称/字段标签 | — |
| `VFXEDITOR_NEWVFXEDITOR` | 新建特效器 | 控件/字段显示名 | — |
| `VFXEDITOR_NEW_MTITE` | 添加特效器 | 控件/字段显示名 | — |
| `VFXEDITOR_SUBASSETSICON` | 引用特效资产图标 | 控件/字段显示名 | — |
| `VFXEDITOR_SUBTITLE1` | 新建特效器名称 | 控件/字段显示名 | — |
| `VFXEDITOR_SUBTITLE2` | 新建特效器分类 | 控件/字段显示名 | — |
| `VFXEDITOR_WARNNINGVFXTITLE1_TYPE_INSIDEOUT` | 从内向外 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE1_TYPE_LINEAR` | 线性填充 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE1_TYPE_OUTINSIDE` | 从外向内 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE2_COLOR` | 填充颜色 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE2_DIRECTION` | 填充方向 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE2_DURATION` | 填充时间(s) | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE2_INSIDEDIA` | 内径(m) | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE2_INSIDEOUT` | 从内向外 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE2_OUTDIA` | 外径(m) | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE2_OUTINSIDE` | 从外向内 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE3_ANGLE` | 扇形角度 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE3_CLOCKWISE` | 顺时针 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE3_COLOR` | 填充颜色 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE3_COUNT` | 逆时针 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE3_DIRECTION` | 填充方向 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE3_DURATION` | 填充时间(s) | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE3_INSIDEDIA` | 内径(m) | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE3_INSIDEOUT` | 由外向内 | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE3_OUTDIA` | 外径(m) | 警告/错误文案 | — |
| `VFXEDITOR_WARNNINGVFXTITLE3_OUTINSIDE` | 由内向外 | 警告/错误文案 | — |
