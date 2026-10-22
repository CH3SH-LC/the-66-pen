> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 千星编辑器 UI 资产与界面清单（UI-ASSET-INVENTORY）

> 本文是「千星编辑器功能全量调研」工程的一份**证据支撑清单**：把编辑器自带 UI 图标的**英文功能命名**、程序集里的 **WPF XAML 面板名**，翻译并归类成可读的功能条目。
>
> **全文口径声明（先读这一段）**
> 本文绝大多数条目的证据来源是**资源文件名与 XAML 资源路径名**。资源名是人类可读的英文功能命名，因此它是编辑器功能的**可靠枚举**，但它**不等于**「已实机验证的功能」。凡属推断的条目，下文一律显式标注**推断**；凡有官方文档或反编译代码佐证的，单独标注证据等级（见第八章）。
>
> 本文**不重复** `docs/editor-catalog/UI-TEXT-INVENTORY.md`（TextMap 界面文本清单）的内容，只在其结论处做交叉引用。
>
> 采集日期：2026-09-17。采集全程只读，未运行编辑器、未修改游戏目录任何文件。

---

## 一、方法与证据

### 1.1 核心发现：`assets.bin` 是一个 ZipCrypto 加密的 ZIP，密码写在程序集里

编辑器安装目录下有资源容器 `Resource/BeyondAssets/assets.bin`。它不是自然格式，而是一个**加密 ZIP 容器**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


读法：
- 容器里**只有一个成员**，成员名也叫 `assets.bin`（自我同名的嵌套容器）；
- `compress_type = 8`（deflate）；
- `flag_bits = 1` → 置位了 ZIP 的 **加密标志位**（ZipCrypto / 传统 PKWARE 加密）。

**密码来源（关键证据）**：密码字面量 `G16F153D` 与资源路径字面量 `Resource/BeyondAssets/assets.bin` **同时出现在同一个混淆类型体内**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


即：该类型同时持有「资源路径」与「密码」两个常量，而编辑器里需要密钥的加密资源只有 `assets.bin` / `beyondeditorassets.bin` 两个。这是**强旁证**（不是百分之百的逻辑必然，但结合解密实测成功，可视为已证实）。安装目录中同时存在 `ICSharpCode.SharpZipLib.dll`，与 ZipCrypto 解密实现相吻合（**推断**：解密由 SharpZipLib 完成）。

解密后得到 `assets.bin` 内的成员字节流，它**本身又是一个普通 ZIP**，可直接用标准 zipfile 打开，内含 **6453 个 PNG**。

### 1.2 条目数与 SHA256

| 文件 | 字节数 | SHA256 |
|---|---:|---|
| `assets.bin`（原始，游戏目录） | 230,759,334 | `445986fe0a2a2815b013b432fb9897c69400474dfa0f8de2a03082b04f200a6f` |
| `assets.dec`（解密产物，工程内） | 231,505,907 | `200d9c68b53ad2f37b3c22c6fd8caee53f1cee6a612290758276b14beea4f9c5` |
| `beyondeditorassets.bin`（原始） | 6,411 | `a88a03f551a9f97bb4c7e942e1e99abbe6d71678567cc5a8ac726f51ee8b35a2` |
| `beyondeditorassets.dec`（解密产物） | 6,300 | `5ae36727f5059230cea15a75c49fd593ddda981287eb91745a37e04883bb2489` |

- `assets.bin` 外层成员声明尺寸 231,505,907 与 `assets.dec` 实测尺寸**逐字节相同**，说明解密是**无损直通**，不是重新压缩。
- `beyondeditorassets.bin` 同构：单成员 `beyondeditorassets.bin`，6300 字节，解密后 ZIP 只含 **1 个条目** `BeyondEditorAssets/UI/Icon/Image/UI_MarkPlayer_Faction.png`（阵营标记图标）。

### 1.3 复现命令（只读，不写游戏目录）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


> 注意：第 1 步全库共 6453 条目数据已落盘为 `.runtime/editor-catalog/assets-manifest.json`（字段 `name` / `size` / `enc`），本轮不必重跑解密。

### 1.4 6453 个条目的目录分布（全量，无遗漏）

| 目录 | 条目数 | 用途（推断） |
|---|---:|---|
| `ART/UI/Atlas/LS/UGC/BeydEffectIcons/` | 2,973 | 特效/表现类图标（含怪物、场景物件、角色头像等） |
| `ART/UI/Atlas/LS/UGC/BeydGadgetIcons/` | 2,424 | **可放置元件**图标 |
| `ART/UI/Atlas/LS/UGC/MainToolBar/` | **410** | **主工具栏 UI 图标** |
| `ART/UI/Atlas/MonsterIcon/` | 395 | 怪物图标 |
| `ART/UI/Atlas/AnimalIcon/` | 251 | 动物图标 |
| **合计** | **6,453** | |

`enc` 字段在 manifest 中 6453 条全部为 `true`（外层 ZIP 内所有成员均加密）。

### 1.5 图标名为什么可以当功能枚举

`MainToolBar/` 下的 410 个文件名形如 `UI_Icon_UGCMainToolBar_Brush_Path.png`。它由**前缀（图集分区）+ 功能域 + 具体语义**构成，且 `UGCMainToolBar` / `UGCToolBar` / `UGCEsc` / `UGCComponent` 等分区名与 XAML 面板（`MainWindow`、`InstructionGraph`、`NodeInspector`…）在语义上互相印证（见第七章）。因此它是编辑器功能的**可靠枚举**，但：

- 图标存在 **≠** 该功能当前对玩家开放（可能被灰度、活动期限或版本开关屏蔽）；
- 中文译名是**我根据英文语义的推断**，官方译名请以 `UI-TEXT-INVENTORY.md` 的 TextMap 条目为准；
- 无法从文件名判断交互细节（参数、上限、联动关系）。

### 1.6 文件清单

| 路径 | 内容 |
|---|---|
| `.runtime/editor-catalog/toolbar-icons.txt` | 410 个主工具栏图标名（`MainToolBar/` 全量） |
| `.runtime/editor-catalog/gadget-icons.txt` | 2424 个 `BeydGadgetIcons/` 图标名（含少量 `BeydEffectIcons` / `TileBaseBrush` 条目） |
| `.runtime/editor-catalog/assets-manifest.json` | assets.bin 全 6453 条目（name/size/enc） |
| `.runtime/editor-catalog/assets-bin/assets.dec` | 解密后的普通 ZIP（可重复解析） |
| `.runtime/editor-catalog/string-categories.txt` | 从程序集还原的字符串分类（含 XAML 路径、UI_ 键、view-model 名） |
| `.runtime/editor-catalog/literal-to-types.json` | 字符串字面量 → 持有它的混淆类型 |
| `.runtime/editor-catalog/_enums.txt` | 配置中的枚举字典（589 组，含中文枚举标题） |

---

## 二、主工具栏功能清单（410 个图标）

来源：`ART/UI/Atlas/LS/UGC/MainToolBar/`，共 **410** 个条目。按前缀分组如下（计数已核对为 410，无遗漏）。

### 2.1 `UI_Icon_UGCMainToolBar_*` —— 主编辑工具栏（61）

这是场景编辑时左侧/顶部的主工具条，集中在**变换、地形笔刷、地块、拼接地图、编组、保存**。

| 图标名（去前缀） | 中文功能（推断） |
|---|---|
| `Position` | 位置工具（移动） |
| `Rotate` | 旋转工具 |
| `Scale` | 缩放工具 |
| `Translate` | 平移 |
| `MoveStep` / `RotateStep` / `ScaleStep` | 移动/旋转/缩放步长设置 |
| `Create` | 创建（放置新物件） |
| `Delete` | 删除 |
| `Removal` | 移除 |
| `Apply` | 应用 |
| `Group` | 编组 |
| `GroupRemove` / `GroupRemove_All` | 解除编组 / 解除全部编组 |
| `All` | 全选 |
| `Local` / `World` | 局部坐标系 / 世界坐标系（**推断**：变换参照系切换） |
| `Attach` | 挂接 |
| `PinFix` / `PinFixed` | 钉住（未固定）/ 已固定 |
| `AccurateDraw` | 精确绘制 |
| `AdjustAvatar` | 调整角色 |
| `AdjustCamera` | 调整相机 |
| `AdjustFocus` | 调整焦点 |
| `AdjustObject` | 调整物件 |
| `AvatarModel` | 角色模型 |
| `SwitchGender_M` / `SwitchGender_F` | 切换性别（男/女） |
| `MaterialReplace` | 材质替换 |
| `SelectLandPlot` | 选择地块 |
| `LandPlotAscend` / `LandPlotDescend` | 地块抬升 / 下沉 |
| `WholeAscend` / `WholeDescend` / `WholeUpDown` | 整体抬升 / 整体下沉 / 整体升降 |
| `GridCreate` | 网格创建 |
| `Segmentation` | 分割 |
| `Brush_LandPlot` | 笔刷：地面地块 |
| `Brush_Path` | 笔刷：路径 |
| `Brush_Slope` | 笔刷：斜坡 |
| `Brush_WaterBody` | 笔刷：水体 |
| `TileMap_Tile_Add` / `TileMap_Tile_Remove` / `TileMap_Tile_Trowel` | 拼接地图：地块 添加 / 移除 / 抹刀（**推断**：涂抹式绘制） |
| `TileMap_Slope_Add` / `TileMap_Slope_Remove` / `TileMap_Slope_0` / `_1` / `_2` | 拼接地图：斜坡 添加 / 移除 / 三种坡度档位 |
| `TileMap_Road_Add` / `TileMap_Road_Remove` | 拼接地图：道路 添加 / 移除 |
| `TileMap_Water_Add` / `TileMap_Water_Remove` | 拼接地图：水面 添加 / 移除 |
| `Prefab` | 预设（预制体） |
| `OpenPreview` / `ClosePreview` | 打开预览 / 关闭预览 |
| `ExitEditing` | 退出编辑 |
| `Save` / `SaveAs` / `SaveCover` | 保存 / 另存为 / 保存封面 |
| `More` | 更多 |

### 2.2 `UI_Icon_UGCToolBar_*` —— 副工具条 / 资源与管理入口（60）

这一组跨越「场景编辑」与「资产、配置、诊断」两类入口，是**功能域最杂**的一组，说明编辑器把这些入口并排放在同一条工具条上。

| 图标名（去前缀） | 中文功能（推断） |
|---|---|
| `Object` / `ObjGroup` / `ObjDetails` | 物件 / 物件组 / 物件详情 |
| `Gadget` | 元件 |
| `Item` | 道具 |
| `Avatar` / `Player` / `Team` | 角色 / 玩家 / 队伍 |
| `Monster` | 怪物 |
| `Skill` / `Skill_AttributeGroup` / `Buff` | 技能 / 技能属性组 / 增益（Buff） |
| `Bullet` | 子弹（投射物） |
| `Equipment_Template` | 装备模板 |
| `Bag` | 背包 |
| `Resource` | 资源（资源管理器） |
| `PrefabGrp` | 预设组 |
| `PrefabMall` | 预设商城（**推断**：官方预设资产市场入口） |
| `TerrainManage` | 地形管理 |
| `LevelConfig` | 关卡设置 |
| `LevelPath` | 关卡路径 |
| `LevelTask` | 关卡任务 |
| `LevelAchievement` | 关卡成就 |
| `MultiTrialPlay` / `Trial` | 多人试玩 / 试玩 |
| `DLC` | DLC |
| `Lighting` | 光照 |
| `Environment_Skybox` / `Environment_Weather` | 环境：天空盒 / 天气 |
| `MusicConfig` | 音乐配置 |
| `Timeline` | 时间轴 |
| `CameraPosition` | 相机位置（机位） |
| `AttachPoint` | 挂接点 |
| `Clipboard` | 剪贴板 |
| `PlaceholderTool` | 占位工具 |
| `AuxiliaryArea` | 辅助区域（**推断**：辅助线/辅助框） |
| `CoveringInspection` | 覆盖检查（**推断**：检查物件是否被遮挡/重叠） |
| `OptimizationCheck` | 优化检查 |
| `Performance` | 性能 |
| `Load` | 负载 |
| `Load_High` / `Load_Serious` / `Load_Danger` | 负载 高 / 严重 / 危险（三档告警） |
| `Sort_AscendingOrder` / `Sort_DescendingOrder` | 排序：升序 / 降序 |
| `Sort_Valid` / `Sort_Invalid` | 排序：有效 / 无效 |
| `BatchRename` / `BatchReplace` | 批量重命名 / 批量替换 |
| `JumpTo` | 跳转至 |
| `Unfold` / `Unfold_1` | 展开 / 折叠 |
| `Visible` | 可见性 |
| `Documentation` / `Documentation_Simple` | 文档 / 简版文档 |
| `Menu` / `Settings` | 菜单 / 设置 |
| `Brush` | 笔刷 |
| `ArrayMode` | 阵列模式 |
| `TireMotion` | 轮胎运动（**推断**：对应官方「操控运动器」的装饰物轮胎运动表现） |

> 交叉印证：官方文档 `概念介绍/功能/通用组件/操控运动器`（条目 `mh1ytk9631fm`）明确提到「装饰物运动表现（轮胎）」，与 `TireMotion` 图标一致。

### 2.3 `UI_Icon_UGCEsc_*` —— ESC 菜单 / 全局管理面板（31）

| 图标名（去前缀） | 中文功能（推断） |
|---|---|
| `Save` | 保存 |
| `Exit` | 退出 |
| `Setting` | 设置 |
| `ShortcutKeys` | 快捷键 |
| `Publish` | 发布 |
| `Archive` / `Archive_Uploaded` | 存档 / 已上传存档 |
| `BatchExport` | 批量导出 |
| `Scan` | 扫描（**推断**：资源完整性/合规扫描） |
| `Expand` | 展开 |
| `Global` | 全局 |
| `Instructions` | 指令（节点指令库） |
| `Struct` | 结构体 |
| `Tag` | 标签 |
| `Timer` | 计时器 |
| `Temp` 系列 → `TemporaryData` | 临时数据 |
| `Custom_Task` | 自定义任务 |
| `LevelCustomValue` | 关卡自定义值 |
| `DummyPoint` | 占位点（虚拟点） |
| `Lighting` | 光照 |
| `LocalAssetLibrary` | 本地资产库 |
| `PrefabLibrary` | 预设库 |
| `PreviewLevelCharacters` | 预览关卡角色 |
| `FreeChipEditing` | 自由编辑（**推断**：`Chip` 可能指「芯片/模块」，疑为自由模块编辑或广告位编辑，语义存疑） |
| `SuiteManage` | 布设组管理（**推断**：对应官方「实体布设组」，见 `UI_BEYOND_EDITOR_SUITE_*`） |
| `Shop` | 商店 |
| `Shield` | 护盾（**推断**：疑为「保护/锁定」或护盾组件入口，语义存疑） |
| `SkillEnergyManager` | 技能能量管理 |
| `SkillVariable` | 技能变量 |
| `ChatSettings` | 聊天设置 |
| `BeyondEditor` | 千星编辑器（关于/入口） |

> `FreeChipEditing` 与 `Shield` 两个名字语义不明确，列为**存疑**。

### 2.4 `UI_Icon_UGCComponent_*` —— 组件图标（30）

见**第三章**（该组是组件类型清单，单独展开）。

### 2.5 `UI_Icon_UGCCustomUI_*` —— 自定义界面控件（58，其中 `Func_*` 37）

见**第四章**。

### 2.6 `UI_Icon_UGCMainCard_*` —— 主功能卡片（8）

| 图标名 | 中文功能（推断） |
|---|---|
| `Play` | 试玩 / 开始游戏 |
| `UI` | 界面（自定义界面编辑） |
| `Bag` | 背包 |
| `CameraEditing` | 镜头编辑 |
| `Levelconfig` | 关卡设置 |
| `LevelAchievement` | 关卡成就 |
| `MultiTrialPlay` | 多人试玩 |
| `DLC` | DLC |

### 2.7 `UI_Icon_UGCMainTab_*` —— 主分类页签（5）

| 图标名 | 中文功能（推断） |
|---|---|
| `Terrain` | 地形 |
| `Gadget` | 元件 |
| `Prefab` | 预设 |
| `Preset` | 预设方案（**推断**：与 `Prefab` 语义需区分——`Preset` 更可能是「预设状态/预设组」） |
| `Fight` | 战斗 |

### 2.8 `UI_Icon_UGCSubTab_*` —— 子页签（5）

| 图标名 | 中文功能（推断） |
|---|---|
| `Component` | 组件 |
| `Behavior` | 行为 |
| `Blueprint` | 节点图（蓝图） |
| `Info` | 信息 |
| `Help` | 帮助 |

### 2.9 `UI_Icon_UGCBag_Tab_*` —— 背包页签（6）

| 图标名 | 中文功能（推断） |
|---|---|
| `All` | 全部 |
| `Consume` | 消耗品 |
| `DropItem` | 掉落物 |
| `Equipment` | 装备 |
| `Material` | 材料 |
| `Valuables` | 贵重物品 |

> 与官方「背包组件」（`mh5y5001vqd4`）条目相印证：背包模板 + 初始物品 + 16 个节点。

### 2.10 `UI_Icon_UGCBoard_*` —— 物件状态标记（9）

| 图标名 | 中文功能（推断） |
|---|---|
| `NotCreate` | 不创建（不生成） |
| `Invisible` | 不可见 |
| `InvisibleAndNotCreate` | 不可见且不创建 |
| `NotSave` | 不存档 |
| `NotSave_Official` | 不存档（官方） |
| `Clone` | 克隆 |
| `Comment` | 备注 |
| `Prefab` | 预设 |
| `DropItem` | 掉落物 |

### 2.11 其余单功能前缀（合并列出）

| 前缀 | 图标（去前缀） | 中文功能（推断） |
|---|---|---|
| `UGCCollision_Type_`（6） | `Box` / `Capsule` / `Cylinder` / `Sphere` / `Combination` / `None` | 碰撞形状：长方体 / 胶囊 / 圆柱 / 球体 / 组合 / 无 |
| `UGCCamera_Type_`（8） | `ClassicView` | 经典视角 |
| | `FirstPersonView` | 第一人称视角 |
| | `ThirdPerson3D` | 第三人称 3D |
| | `ThirdPersonCustomView` | 第三人称自定义视角 |
| | `View25D` | 2.5D 视角 |
| | `Add` | 新增相机（**推断**） |
| | `PreviewOpen` / `PreviewClose` | 相机预览 开 / 关 |
| `UGCMover_Type_`（5） | `Straight` / `RelativePath` / `AbsolutePath` / `Rotation` / `TargetDirection` | 运动器：直线 / 相对路径 / 绝对路径 / 旋转 / 朝目标方向 |
| `UGCFollowMove_Type_`（3） | `FollowMoveAndTurn` / `OnlyFollowMove` / `OnlyFollowTurn` | 跟随运动器：完全跟随 / 仅跟随位置 / 仅跟随旋转 |
| `UGCBulletMove_Type_`（3） | `Straight` / `Parabola` / `Tracking` | 投射物运动：直线 / 抛物线 / 追踪 |
| `UGCPatrol_Type_`（3） | `Loop` / `Once` / `PingPong` | 巡逻模式：循环 / 单次 / 往返 |
| `UGCTimer_Type_`（2） | `CountDown` / `CountUp` | 计时器：倒计时 / 正计时 |
| `UGCLighting_Type_`（2） | `PointLight` / `SpotLight` | 光照：点光源 / 聚光灯 |
| `UGCAudio_Type_`（3） | `Decreasing` / `Decreasing_ConcaveDown` / `Decreasing_ConcaveUp` | 音效衰减：递减 / 凹形递减 / 凸形递减（3 种衰减方式） |
| `UGCAvatarDisturber_Type_`（4） | `Catapult` / `Drag` / `ForceField` / `Path` | 角色扰动装置：弹射器 / 牵引器 / 力场器 / 路径 |
| `UGCRank_`（3） | `Score` / `Time` / `Progress` | 排行榜：计分 / 计时 / 进度 |
| `UGCEnvironment_Type_`（2） | `Config` / `Fog` | 环境：配置 / 雾 |
| `UGCLevel_`（2） | `CreationPoint` / `RespawnPoint` | 关卡：创建点 / 复活点 |
| `UGCOther_Type_`（2） | `Nameplate` / `Talk` | 其它：铭牌 / 对话 |
| `UGCBasicMove_Type_`（1） | `FixedPointMove` | 基础运动：定点运动 |
| `UGCMPAction_Type_`（7） | `Buff_Add` / `Buff_Remove` / `Effect` / `FireBullet` / `SelfDestruct` / `TargetSelection` / `TargetSelection_Box` | 多人/怪物行为动作：加增益 / 移除增益 / 播特效 / 发射子弹 / 自毁 / 选择目标 / 框选目标 |
| `UGCMonster_Type_`（1） | `AI` | 怪物 AI |
| `UGCPCG_Type_`（1） | `SceneTemplate` | PCG：场景模板（程序化生成） |
| `UGCScene_Type_`（1） | `Measure` | 场景：测量 |
| `UGCTileMap_Type_`（1） | `Plots` | 拼接地图：地块 |
| `UGCEffect_`（1） | `Playing` | 特效：播放中 |
| `UGCEffectGroup`（1） | — | 特效组 |
| `UGCCornerMark_`（2） | `Component` / `Prefab` | 角标：组件 / 预设 |
| `UGCOptionMenu_`（7） | `Copy` / `Paste` / `Delete` / `Reset` / `EditTxt` / `CameraFocus` / `MergeRows` | 右键菜单：复制 / 粘贴 / 删除 / 重置 / 编辑文本 / 相机聚焦 / 合并行 |
| `UGCLoad_`（12） | `Memory` `_1` `_2` `_3`、`Performance` `_1` `_2` `_3`、`Warning_1/2/3`、`ServerArchive` | 负载指示：内存 3 档 / 性能 3 档 / 警告 3 档 / 服务器存档 |
| `UGC`（31，见下） | 见 2.11 表下 | 大厅与分享类 |
| `UGCIconSmall_`（19） | 见下 | 小图标（通用） |
| `IconSmall_UGC_Pos_Marg_*`（4） | `_B` / `_L` / `_R` / `_T` | 位置边距：下 / 左 / 右 / 上（对齐吸附） |

`UI_Icon_UGC_*`（31，大厅/分享/装扮类）：

| 图标名 | 中文功能（推断） |
|---|---|
| `Activity_BeyondWelfare` / `Activity_FashionWelfare` / `Activity_LimitedTime` / `Activity_SummerAlbum` | 活动：千星福利 / 时装福利 / 限时活动 / 夏日相册 |
| `ClassicMode` | 经典模式 |
| `Masterpiece` | 精品（佳作） |
| `History` / `List` | 历史 / 列表 |
| `Room` / `Room_Invite` | 房间 / 邀请进房 |
| `Share` / `ShareCode_Import` / `ShareCode_My` | 分享 / 分享码导入 / 我的分享码 |
| `Costume_TryOn` / `Costume_ViewAll` | 装扮试穿 / 查看全部装扮 |
| `StepUndo` / `StepRedo` | 撤销 / 重做 |
| `Reset` / `Restore` / `Clear` | 重置 / 还原 / 清空 |
| `Temp_Stash` / `Temp_Unstash` | 临时暂存 / 取消暂存 |
| `Visible_Show` / `Visible_Hide` | 显示 / 隐藏 |
| `Tab_GeniusColumn` / `Tab_PopularMW` | 页签：大神专栏 / 热门千星 |
| `Tag_Activity_Album` / `Tag_Activity_LimitedTime` / `Tag_Activity_LimitedTime_Finish` / `Tag_Favorite` / `Tag_Member` | 标签：活动相册 / 限时活动 / 限时活动已完成 / 收藏 / 成员 |

`UI_Icon_UGCIconSmall_*`（19）：

| 图标名 | 中文功能（推断） |
|---|---|
| `Avatar` | 角色 |
| `ColorBlock` / `ColorBlock_A0` / `ColorBlock_LT` | 色块（含 A0 透明度、LT 浅色变体） |
| `NotColor` | 非色块 |
| `ConfigAdd` / `PresetsAdd` | 添加配置 / 添加预设 |
| `PrefabGrp` | 预设组 |
| `Link` | 链接 |
| `FindFile` | 查找文件 |
| `Locked` | 已锁定 |
| `BeDeleted` | 将被删除 |
| `Termination` | 终止 |
| `MapMarkColor_FollowArmy` / `MapMarkColor_Relationship` | 地图标记颜色：跟随阵营 / 跟随关系 |
| `Tips` / `Help` / `Yes` / `Voice` | 提示 / 帮助 / 确认 / 语音 |

---

## 三、组件类型清单（`UI_Icon_UGCComponent_*`，30 个）

**证据等级：图标名（强）+ 官方文档（强）**。官方文档「概念介绍/功能/通用组件」共 29 条，与本组图标名可逐条对上，属**双证据**。

| # | 图标名 | 中文功能（推断） | 官方文档对应 |
|---:|---|---|---|
| 1 | `AttachPoint` | 自定义挂接点 | 自定义挂接点 `mhmshmimtegs` |
| 2 | `AutoAvoidObstacles` | 自动避障（寻路阻挡） | 寻路阻挡 `mh6c3uri84h2` |
| 3 | `AvatarDisturber` | 角色扰动装置 | `mhstl890y7xe` |
| 4 | `Bag` | 背包组件 | `mh5y5001vqd4` |
| 5 | `BulletLaunch` | 投射物发射（投射运动器） | 投射运动器 `mhaqt9rgqv4u` |
| 6 | `ClientTrigger` | 客户端触发器（本地过滤器） | 本地过滤器 / 客户端节点图 |
| 7 | `Collision` | 额外碰撞 | 额外碰撞 `mhuiob9dg1dm` |
| 8 | `CountDown` | 定时器 / 倒计时 | 定时器 `mhufb90zbnts` |
| 9 | `CursorCollider` | 光标碰撞盒 | `mhso200yz3h4` |
| 10 | `CustomBlueprint` | 自定义节点图（蓝图）挂载 | 节点图体系 |
| 11 | `CustomValue` | 自定义变量 | `mhso1b9wjica` |
| 12 | `DropItem` | 战利品（掉落） | 战利品 `mh63ox06afy8` |
| 13 | `Effect` | 特效播放 | `mh4ppo02m1o8` |
| 14 | `Equipment` | 装备 | 资产/装备体系 |
| 15 | `ExtraCamera` | 物件镜头（额外镜头） | 物件镜头 `mhx9b60or59k` |
| 16 | `FollowMove` | 跟随运动器 | `mhuts59m9gju` |
| 17 | `HitBox` | 命中判定框 | 命中检测 `mh2pir0hat1s` |
| 18 | `HitDetection` | 命中检测 | `mh2pir0hat1s` |
| 19 | `Intee` | 悬浮交互（INTERACTEE，悬浮交互页） | 悬浮交互页控件 `mh2u2e9o3jn6` |
| 20 | `Interaction` | 交互（交互按钮/选项卡） | 选项卡 `mh5jko05fzyw` |
| 21 | `Lighting` | 光源组件 | 光源 `mhgkan9wgil6` |
| 22 | `MiniMap` | 小地图标识组件 | `mh0pppib5eyc` |
| 23 | `Motion` | 基础运动器 | `mhnmcmipncrg` |
| 24 | `Nameplate` | 铭牌 | `mh5n160t2b6w` |
| 25 | `RoleStatus` | 单位状态（角色状态） | 单位状态 `mhd7nxrfa8im` |
| 26 | `Scan` | 扫描标签 | `mhfc0lr1tcke` |
| 27 | `Shop` | 商店组件 | `mho6gviqhsqs` |
| 28 | `SoundEffect` | 音效播放器 | `mhwiv89yra02` |
| 29 | `Stick` | 摇杆（**推断**：操控运动器用摇杆输入） | 操控运动器 `mh1ytk9631fm` |
| 30 | `Talk` | 文本气泡 / 对话 | 文本气泡 `mhwtz297kp6a` |

> 与官方 29 条对比：官方条目含「组件总论」（非具体组件）与「全局计时器」（`mhawd6rl5kpy`）——**图标集里没有独立的「全局计时器」图标**，`CountDown` 与 `UGCTimer_Type_CountDown/CountUp` 更可能对应「定时器」。这是**图标集粒度为 30、官方概念条目为 29（含总论）**的粒度差异，不是缺口。

---

## 四、自定义界面控件清单（`UI_Icon_UGCCustomUI_Func_*`，37 个）

`UI_Icon_UGCCustomUI_*` 共 58 个，其中 `Func_` 段 **37** 个是**可放置到自定义界面上的控件类型**；其余 21 个是编辑器操作（保存/上载/资源/平台适配/翻转）。

### 4.1 `Func_*` 控件（37）

按图标名排序（与图标集字典序一致），共 **37** 条：

| # | 图标名（去 `UI_Icon_UGCCustomUI_Func_`） | 中文功能（推断） | 官方文档对应 |
|---:|---|---|---|
| 1 | `Avatar` | 角色（头像 / 生命值条） | 队伍信息 / 角色生命值条 |
| 2 | `BuffQueue` | 增益队列（Buff 队列） | **推断**：状态显示区 `mh4ve00q4j14` |
| 3 | `Button` | 自定义按钮 | `mhtpwgitsigc` |
| 4 | `Camp` | 阵营 | 阵营展示（**推断**） |
| 5 | `CardSelector` | 卡牌选择器 | `mh2teu0bmfbc` |
| 6 | `Chat` | 聊天 | 聊天按钮 |
| 7 | `CreatorSubscribe` | 创作者订阅 | **推断**：订阅按钮 |
| 8 | `Data` | 数据（数据展示控件） | **推断**：状态显示区 |
| 9 | `Dlg` | 弹窗 | `mhen7r0djxkg` |
| 10 | `Effect` | 界面动效 | `mh2iyk9fa4gy` |
| 11 | `Effect_FullScreen` | 全屏界面动效 | `mhbn4i09l5ns` |
| 12 | `ElementalSight` | 元素视野 | 元素视野（**推断**） |
| 13 | `Exit` | 退出按钮 | 退出按钮 |
| 14 | `Handle` | 手柄 / 摇杆 | 摇杆 |
| 15 | `Image` | 图片 | 图片控件 `mh2oih9jou22` |
| 16 | `Item` | 道具展示 | `mhjja1ipq9ck` |
| 17 | `List_Item` | 列表 项 | 列表控件（**推断**） |
| 18 | `List_Scroll` | 列表 滚动条 | 列表控件（**推断**） |
| 19 | `Map` | 自定义小地图 | `mhls9miyjwjg` |
| 20 | `MessageQueue` | 消息队列 | `mhs1f7ibtc6c` |
| 21 | `Monster` | 造物（怪物）状态 | 造物生命值条 |
| 22 | `NumberTxt` | 数字文本 / 特殊数字控件 | 特殊数字控件 `mhkwucr8awfq` |
| 23 | `Option` | 选项（选项组） | 选项卡控件 |
| 24 | `Ping` | 网络延迟（Ping） | 网络状态 |
| 25 | `Progress` | 进度条 | `mhwpzpixrad0` |
| 26 | `Score` | 计分板 | `mhesro0hyn5k` |
| 27 | `ScrollTxt` | 滚动文本 | 滚动文本（**推断**） |
| 28 | `ShakeOff` | 挣扎 | 挣扎按钮 |
| 29 | `Skill` | 技能区 | 技能区 |
| 30 | `Tab_Grp` | 选项卡 组 | 选项卡 `mh5jko05fzyw` |
| 31 | `Tab_Item` | 选项卡 项 | 同上 |
| 32 | `Timer` | 计时器 | `mhnrdor7uyra` |
| 33 | `Toggle` | 自定义开关 | `mhkrafr3w6um` |
| 34 | `Txt` | 文本 | 文本框界面控件 `mhnltrr3g966` |
| 35 | `TxtImg` | 图文输入框 | 图文输入框控件 `mh496c08hooo` |
| 36 | `Voice` | 语音聊天 | 语音聊天按钮 |
| 37 | `VoiceList` | 语音列表 / 语音聊天提示队列 | 语音聊天提示队列 |

> 37 条已与图标集逐条核对（`grep -c '^UI_Icon_UGCCustomUI_Func_'` = 37），无遗漏无重复。
>
> 与官方「界面控件」条目对比：官方列出**固有 13 + 预制 18**。`Func_*` 的 37 个接近「预制控件」的超集——官方预制清单里出现的「全屏界面动效」「特殊数字控件」「图文输入框」「悬浮交互页」「状态显示区」等，在图标集里都有对应命名；而**固有能力（小地图、技能区、队伍信息、角色/造物生命值条、摇杆、退出按钮、选项卡、聊天按钮、网络状态、挣扎按钮、语音聊天按钮/提示队列）在图标集里多数没有独立 `Func_` 图标**，说明「固有控件」不是「可放置的控件类型」，与官方口径一致。

### 4.2 `Func_` 之外的 `UGCCustomUI_*`（21）

| 图标名（去前缀） | 中文功能（推断） |
|---|---|
| `MainScreen` | 主屏（界面画布首页） |
| `Library` | 素材库 |
| `Resource` / `ResourceRemove` / `ResourceRemove_All` | 资源 / 移除资源 / 移除全部资源 |
| `Save` / `SaveAs` / `SaveAsPreset` | 保存 / 另存为 / 另存为预设 |
| `Upload` | 上载 |
| `WindowFrame` / `WindowFrame_Var` | 窗口框 / 窗口框变体 |
| `NativeSize` | 原始尺寸 |
| `ColorPicker` | 取色器 |
| `Flip_H` / `Flip_V` | 水平翻转 / 垂直翻转 |
| `Sound` | 声音 |
| `Platform_PC` / `Platform_Mobile` / `Platform_Joypad` / `Platform_MobileJoypad` | 平台适配：PC / 移动端 / 手柄 / 移动端手柄 |
| `UI_Icon_UGCCustomUI`（无后缀） | 自定义界面（总入口） |

> `Platform_*` 四个图标对应官方「界面布局」条目 `mhozt0r74ng6` 中的**设备适配**能力。

---

## 五、子类型枚举

下列各组枚举均**取自图标名**（`toolbar-icons.txt`），并以 `.runtime/editor-catalog/_enums.txt`（程序集配置里的 589 组枚举字典，含中文枚举标题）交叉印证。表格中「配置枚举」列给出 `_enums.txt` 中的中文标题，作为**独立第二证据**。

### 5.1 碰撞形状（`UGCCollision_Type_`，6）

| 图标 | 中文 | 配置枚举印证 |
|---|---|---|
| `Box` | 长方体 | 官方「寻路阻挡」条目 `mh6c3uri84h2` 明确「长方体 / 圆柱体」 |
| `Capsule` | 胶囊 | — |
| `Cylinder` | 圆柱 | 同上 |
| `Sphere` | 球体 | — |
| `Combination` | 组合 | — |
| `None` | 无 | — |

> **注意**：`_enums.txt` 中的「攻击形状」（矩形/球体/扇形）是**节点图攻击判定**的枚举，与本组的**碰撞体形状**不是同一套，不可混淆。

### 5.2 相机类型（`UGCCamera_Type_`，5 种类型 + 3 个操作）

| 图标 | 中文 |
|---|---|
| `ClassicView` | 经典视角 |
| `FirstPersonView` | 第一人称视角 |
| `ThirdPerson3D` | 第三人称 3D |
| `ThirdPersonCustomView` | 第三人称自定义视角 |
| `View25D` | 2.5D 视角 |
| `Add` / `PreviewOpen` / `PreviewClose` | 新增 / 预览开 / 预览关 |

### 5.3 运动器类型

| 组 | 图标 | 中文 |
|---|---|---|
| `UGCMover_Type_`（5） | `Straight` | 直线 |
| | `RelativePath` | 相对路径 |
| | `AbsolutePath` | 绝对路径 |
| | `Rotation` | 旋转 |
| | `TargetDirection` | 朝目标方向 |
| `UGCFollowMove_Type_`（3） | `FollowMoveAndTurn` | 完全跟随（位置+旋转） |
| | `OnlyFollowMove` | 仅跟随位置 |
| | `OnlyFollowTurn` | 仅跟随旋转 |

> 官方 `概念介绍/功能/通用组件/基础运动器`（`mhnmcmipncrg`）称「**6 种运动器**、3 种状态、6×6 叠加表」；`跟随运动器`（`mhuts59m9gju`）称「完全跟随/跟随位置/跟随旋转」。图标集给出 5 种 `Mover_Type` + 3 种 `FollowMove_Type`，与官方**数量口径不完全一致**（官方 6 种可能含 `UGCBasicMove_Type_FixedPointMove` 定点运动，或本轮图标集未覆盖的一种）。此处如实标注**存疑**。

### 5.4 投射物运动（`UGCBulletMove_Type_`，3）

| 图标 | 中文 |
|---|---|
| `Straight` | 直线 |
| `Parabola` | 抛物线 |
| `Tracking` | 追踪 |

> 官方 `投射运动器`（`mhaqt9rgqv4u`）称「直线/抛物线/追踪（**含吸附追踪**）/圆周」——**官方多出「吸附追踪」与「圆周」两种，图标集只有 3 个**。差异如实标注（图标可能只覆盖常用档位，或圆周/吸附追踪为参数而非独立图标）。

### 5.5 巡逻模式（`UGCPatrol_Type_`，3）

| 图标 | 中文 |
|---|---|
| `Loop` | 循环 |
| `Once` | 单次 |
| `PingPong` | 往返（乒乓） |

> 与官方「造物巡逻」分类（`folders` 里 `造物巡逻`）及 `_enums.txt` 的「运动类型」（单向/往返/循环）语义一致，但**顺序与命名口径略有差异**，属推断。

### 5.6 光照类型（`UGCLighting_Type_`，2）

| 图标 | 中文 |
|---|---|
| `PointLight` | 点光源 |
| `SpotLight` | 聚光灯 |

> 官方「光源」组件（`mhgkan9wgil6`）：「点光源 / 聚光灯」，**完全一致**。

### 5.7 计时器类型（`UGCTimer_Type_`，2）

| 图标 | 中文 |
|---|---|
| `CountDown` | 倒计时 |
| `CountUp` | 正计时 |

### 5.8 音效衰减（`UGCAudio_Type_`，3）

| 图标 | 中文 |
|---|---|
| `Decreasing` | 递减 |
| `Decreasing_ConcaveDown` | 凹形递减（**推断**：曲线下凹） |
| `Decreasing_ConcaveUp` | 凸形递减（**推断**：曲线上凸） |

> 官方「音效播放器」（`mhwiv89yra02`）：「3D 音效、范围半径、**3 种衰减方式**」——**数量完全一致（3）**，命名方向一致。

### 5.9 背包页签（`UGCBag_Tab_`，6）

| 图标 | 中文 |
|---|---|
| `All` | 全部 |
| `Consume` | 消耗品 |
| `DropItem` | 掉落物 |
| `Equipment` | 装备 |
| `Material` | 材料 |
| `Valuables` | 贵重物品 |

### 5.10 角色扰动装置（`UGCAvatarDisturber_Type_`，4）

| 图标 | 中文 |
|---|---|
| `Catapult` | 弹射器 |
| `Drag` | 牵引器 |
| `ForceField` | 力场器 |
| `Path` | 路径（**推断**：沿路径扰动的第 4 类） |

> 官方「角色扰动装置」（`mhstl890y7xe`）：「弹射器/牵引器/力场器，**同时只生效一个**」——官方只列 3 类，图标有 4 个。**第 4 项 `Path` 存疑**。

### 5.11 排行榜类型（`UGCRank_`，3）

| 图标 | 中文 |
|---|---|
| `Score` | 计分 |
| `Time` | 计时 |
| `Progress` | 进度 |

### 5.12 环境类型（`UGCEnvironment_Type_`，2）

| 图标 | 中文 |
|---|---|
| `Config` | 配置 |
| `Fog` | 雾 |

### 5.13 关卡点位（`UGCLevel_`，2）

| 图标 | 中文 |
|---|---|
| `CreationPoint` | 创建点 |
| `RespawnPoint` | 复活点 |

### 5.14 其它类型（`UGCOther_Type_`，2）

| 图标 | 中文 |
|---|---|
| `Nameplate` | 铭牌 |
| `Talk` | 对话（文本气泡） |

### 5.15 多人/怪物行为动作（`UGCMPAction_Type_`，7）

| 图标 | 中文 |
|---|---|
| `Buff_Add` / `Buff_Remove` | 添加增益 / 移除增益 |
| `Effect` | 播放特效 |
| `FireBullet` | 发射子弹 |
| `SelfDestruct` | 自毁 |
| `TargetSelection` | 选择目标 |
| `TargetSelection_Box` | 框选目标（范围选择） |

### 5.16 配置枚举字典（`_enums.txt`，589 组，70 个去重标题）

`.runtime/editor-catalog/_enums.txt` 从程序集配置 `BeyondAssistantEditorConfigGlobal` 还原出 **589 组**枚举映射，去重后 **70 个枚举标题**（含中文名）。这是**节点图参数**层面的子类型枚举，与上面「图标子类型」是**两套独立枚举**，勿混用。全 70 个标题如下：

三角函数 / 伤害跳字类型 / 便捷数学运算 / 倒下原因 / 元素反应类型 / 元素类型 / 决策刷新方式 / 击退方向类型 / 单位状态添加失败原因 / 单位状态添加成功类型 / 单位状态添加结果 / 单位状态移除原因 / 单位状态移除策略 / 取整逻辑 / 受击等级 / 受击表现等级 / 受打断状态 / 坐标系类型 / 基础数学运算 / 填充材质 / 声音衰减方式 / 复苏点选取策略 / 定点运动器参数转化类型 / 定点运动器运动类型 / 实体类型 / 射线命中筛选类型 / 布尔值 / 战术枚举 / 扇形检测方向 / 打击类型 / 扫描状态 / 扫描积分规则 / 扰动装置朝向 / 扰动装置类型 / 技能槽位 / 排序规则 / 攻击层配置 / 攻击形状 / 攻击类型 / 数学运算 / 旋转方向 / 栈顶技能销毁类型 / 比较运算 / 游玩方式 / 溯源类型 / 生存状态 / 界面控件组状态 / 目标实体 / 目标排序规则 / 目标类型 / 目标类型(镜头朝向节点用) / 移动速度 / 类型转换 / 组件功能 / 结算状态 / 职业切换技能处理 / 触发限制 / 跟随位置类型 / 转向类型 / 输入设备类型 / 过滤器返回类型 / 运动类型 / 运动路径点位类型 / 选择完成原因 / 逻辑运算 / 道具变化原因 / 道具掉落类型 / 随机排序 / 预瞄准结束原因 / 颜色叠加类型

> 完整 589 条映射见 `.runtime/editor-catalog/_enums.txt`（含每个成员的 `textMapId`，可回查 TextMap）。

---

## 六、可放置元件统计（2424 个 `UI_Beyd_Gadget_*`）

来源：`ART/UI/Atlas/LS/UGC/BeydGadgetIcons/`。该目录共 **2424** 个条目，其中 **2399** 个是 `UI_Beyd_Gadget_*` 元件图标；另 **25** 个是非元件条目（`UI_Beyd_TileBaseBrush_*` 9 个、`UI_Beyd_UGC_JN_General_*` 5 个、`UI_Beyd_Effect_Particle01`、`UI_Icon_AddConfig` / `AvatarModel` / `DutyEdit` / `LevelEntity` / `ObjectGrp` / `ObjectNotFound` / `PlayerEdit` / `PrefabGrp` / `RemoveMaterials` / `SkilltNotFound` 共 10 个）。

> **完整清单引用路径**：`.runtime/editor-catalog/gadget-icons.txt`（2424 行，一行一个文件名）。
> 也可从 `.runtime/editor-catalog/assets-manifest.json` 过滤 `BeydGadgetIcons` 前缀得到。本文不逐条罗列 2424 个模型名（无阅读价值），只给分类统计与代表样本。

### 6.1 元件分类统计（2399 个 `UI_Beyd_Gadget_*`）

| 类别前缀 | 数量 | 占比 | 语义（推断） |
|---|---:|---:|---|
| `Prop` | 1,297 | 54.1% | 摆件/道具（家具、器物、活动道具、机关…） |
| `Build` | 656 | 27.3% | 建筑（房屋、墙体、廊柱、平台…） |
| `Grass` | 100 | 4.2% | 草类植被 |
| `Light` | 79 | 3.3% | 灯具/光源摆件 |
| `Tree` | 78 | 3.3% | 树木 |
| `Struct` | 74 | 3.1% | 结构件（标准尺寸的立方体/门/柱/栅栏，尺寸内嵌在名字里） |
| `Stone` | 50 | 2.1% | 石料 |
| `Rock` | 40 | 1.7% | 岩石 |
| `Lvy` | 23 | 1.0% | 绿植/藤蔓（`Lvy` 系 `Lvy`=绿意缩写，**推断**） |
| `WaterFall` | 2 | 0.1% | 瀑布 |
| **合计** | **2,399** | 100% | |

### 6.2 各类代表样本

| 类别 | 代表样本（`UI_Beyd_Gadget_` 后） |
|---|---|
| `Build` | `Build_House_*`（42 个房屋变体）、`Build_Ndklzujian_*`（37）、`Build_YJQiang_*`（13 墙）、`Build_ZuJian_*`（13 组件）、`Build_Minju_*`（12 民居）、`Build_ZhiWu_*`（12 植物建筑）、`Build_PengZi_*`（11 棚子）、`Build_ChangLang_*`（10 长廊）、`Build_CityHouse_*`（10）、`Build_Pingtai_*`（10 平台）、`Build_ZhanDao_*`（10 栈道）、`Build_RockRoad_*`（9）、`Build_YJDiBan_*`（9 地板）、`Build_Zhuzi_*`（9 柱子）、`Build_LouTi_*`（8 楼梯）、`Build_Window_*`（7 窗）、`Build_YiJi_*`（7 遗迹）、`Build_RotateCup_*`（7 旋转杯） |
| `Prop` | `Prop_WuQi_*`（29 武器，**本类最大子类**）、`Prop_ZhaoPai_*`（23 招牌）、`Prop_Food_*`（22 食物）、`Prop_Chair_*`（18 椅）、`Prop_Table_*`（18 桌）、`Prop_Block_*`（17 方块）、`Prop_Robot_*`（16 机器人）、`Prop_MNDaoJu_*`（12 蒙德道具）、`Prop_Primitive_*`（11 原始件）、`Prop_Chilun_*`（10 齿轮）、`Prop_Pottedplant_*`（10 盆栽）、`Prop_LeGao_*`（9 乐高式拼装）、`Prop_Bottle_*`（8）、`Prop_ClockworkToy_*`（8 发条玩具）、`Prop_Tent_*`（8 帐篷）、`Prop_ElemCoin_*`（7 元素币）、`Prop_Gift_*`（7 礼物）、`Prop_EasterEgg_*`（7 彩蛋） |
| `Grass` | `Grass_Aquatic_01`（水生）、`Grass_Coral_01/02`、`Grass_BroadLeaf_01`、`Grass_ChuJu_01/02`、`Grass_Fenlaba_*`、`Grass_BluedF_*`、`Grass_Baiwan_*` |
| `Tree` | `Tree_Arbor_01` … `_14`（乔木，14）、`Tree_QiaoMu_*`（乔木 9）、`Tree_SongShu_*`（松树 5）、`Tree_Baobab_*`（猴面包树 4）、`Tree_Bamboo_*`（竹 3）、`Tree_GaiMaoShu_*`（盖帽树 3）、另有 `Dg` / `Fs` 等缩写系列各 4 |
| `Light` | `Light_Deng_01` … `_13`（灯 13）、`Light_Lamp_*`（8）、`Light_Lantern_*`（灯笼 7）、`Light_ZhuTai_*`（烛台 5）、`Light_YewaiDeng_*`（野外灯 4）、`Light_DiaoDeng_*`（吊灯 3）、`Light_Fossillight_*`（化石光 3）、`Light_Irodori_*`（3）、`Light_Candle_01/02`、`Light_BiDeng_01`（壁灯）、`Light_Chengshiludeng_01`（城市路灯）、`Light_DasheLamp_01`（大蛇灯） |
| `Stone` | `Stone_A_01_Mi` … `Stone_A_06_Mi`、`Stone_Full_01_L` … `Stone_Full_06_S`（`_L/_S` = 大/小，`_Mi` = 中？**推断**） |
| `Rock` | `Rock_A_01_L` … `Rock_A_05_S`、`Rock_B_01_S`、`Rock_CoralRoots_01/02`、`Rock_Full_01_L/M/S` |
| `Struct` | `Struct_Stone_Cube_25_25_25`、`Struct_Stone_CellingFloor_25_5_25`（原数据拼写为 `Celling`）、`Struct_Stone_Door_25_50_5`、`Struct_Stone_Fance_25_10_5`（栅栏，原数据拼写为 `Fance`）、`Struct_Stone_Head_25_5_5`、`Struct_Stone_Pill_10_25_10` —— **命名内嵌 `长_高_宽` 三围尺寸（推断），是标准模组化建筑件** |
| `Lvy` | `Lvy_FuPing_01/02`（浮萍）、`Lvy_Huangtm_01` … `_06`、`Lvy_Sakura_01/02/03`（樱花）、`Lvy_TengWan_01/02/03`（藤蔓） |
| `WaterFall` | `WaterFall_Whole_01` / `_02`（整体瀑布） |

### 6.3 非元件但同目录的条目（25）

| 名前缀 | 数量 | 语义（推断） |
|---|---:|---|
| `UI_Beyd_TileBaseBrush_*` | 9 | 地形笔刷材质：`Drysoil` 干土 / `Grass01` `Grass02` `Grass03` 草地 / `Gravel` 砾石 / `Lava` 岩浆 / `Ruin` 废墟 / `Sand` 沙地 / `Stone` 石地 |
| `UI_Beyd_UGC_JN_General_*` | 5 | 技能/天赋通用图标（`JN` 疑为「技能」拼音缩写，**推断**） |
| `UI_Beyd_Effect_Particle01` | 1 | 特效：粒子 |
| `UI_Icon_*` | 10 | 编辑器通用小图标：`AddConfig` 添加配置 / `AvatarModel` 角色模型 / `DutyEdit` 职责编辑 / `LevelEntity` 关卡实体 / `ObjectGrp` 物件组 / `ObjectNotFound` 物件缺失 / `PlayerEdit` 玩家编辑 / `PrefabGrp` 预设组 / `RemoveMaterials` 移除材质 / `SkilltNotFound` 技能缺失（原拼写有笔误） |

### 6.4 同容器的特效图标（`BeydEffectIcons/`，2973）

虽非本次任务重点，但其分类同样可读，列出以说明容器全貌：

| 二级前缀 | 数量 | 语义（推断） |
|---|---:|---|
| `UI_Beyd_Eff_Monster_*` | 1,337 | 怪物相关表现图标 |
| `UI_Beyd_Eff_SceneObj_*` | 1,018 | 场景物件表现图标 |
| `UI_Beyd_Eff_Avatar_*` | 320 | 角色表现图标 |
| `UI_Beyd_Eff_Element_*` | 54 | 元素 |
| `UI_Beyd_Eff_Hit_*` | 42 | 命中 |
| `UI_Beyd_Eff_Weapon_*` | 34 | 武器 |
| `UI_Beyd_Eff_Property_*` | 32 | 属性 |
| `UI_Beyd_Eff_ScenObj_*` | 20 | 场景物件（异拼） |
| `UI_Beyd_Eff_Item_*` | 18 | 道具 |
| `UI_Beyd_Eff_Animal_*` | 16 | 动物 |
| `UI_Beyd_Eff_Death_*` | 10 | 死亡 |
| 其余（`Prop`/`SceneObject`/`Quest`/`Activity`/`Arrow`/`Tower`/`Balloon`） | 72 | — |

---

## 七、WPF 面板 / 对话框清单

### 7.1 证据来源与一个关键发现：编辑器有**两个** WPF 程序集

从反编译源码中用 `pack://application:,,,/` 资源 URI 检索，共得 **44 条** XAML 引用，分属两个程序集：

- `BeyondEditor;component/...` —— **25 条**（主程序集，本次已完整反编译）
- `BydeCustomControl;component/...` —— **19 条**（**自定义控件库**）

`BydeCustomControl` 在安装目录中**没有独立 DLL 文件**（`find` 无结果，`grep` 全库仅命中 1 个文件，即字符串表类型）。**推断**：它以嵌入资源形式随 `BeyondEditor.dll` 分发，运行时经 `AssemblyResolve` 加载；也可能在未反编译到的路径上。此点**待证**。

另在字符串表中还出现小写路径 `/BeyondEditor;component/app.xaml` 与 `/BeyondEditor;component/mainwindow.xaml`（见 `string-categories.txt` 的 `### PATHS` 段），与上表 `MainWindow.xaml`（大写）互为印证。

### 7.2 `BeyondEditor` 程序集（25）

| # | XAML 路径（`component/` 后） | 用途推断 | 证据等级 |
|---:|---|---|---|
| 1 | `MergedResources.xaml` | 资源字典合并总入口 | 强（资源路径） |
| 2 | `Xaml/Template/Window/MainWindow/MainWindowResource.xaml` | 主窗口（资源态） | 强 |
| 3 | `Xaml/Template/Window/MainWindow/MainWindowInhouseResource.xaml` | 主窗口（**内建资源态**，`Inhouse` = 官方内置） | 强 |
| 4 | `Xaml/Template/BeyondComponentEdit/BeyondComponentEditPanel.xaml` | 组件编辑面板 | 强 |
| 5 | `Xaml/Template/BeyondComponentEdit/BeyondComponentEditor.xaml` | 组件编辑器 | 强 |
| 6 | `Xaml/Template/BeyondComponentEdit/BeyondComponentProperty.xaml` | 组件属性面板 | 强 |
| 7 | `Xaml/Template/BeyondResourceExplorer/BeyondResourceExplorerTab.xaml` | 资源管理器页签 | 强 |
| 8 | `Xaml/Template/Explorer/MainResourceExplorer/MainResourceExplorer.xaml` | 主资源浏览器 | 强 |
| 9 | `Xaml/Template/Explorer/NodeExplorer/NodeExplorer.xaml` | 节点浏览器（节点指令库） | 强 |
| 10 | `Xaml/Template/Explorer/InstructionExplorer/InstructionExplorer.xaml` | 指令浏览器 | 强 |
| 11 | `Xaml/Template/InstructionGraph/InstructionGraph.xaml` | 指令图（节点图画布） | 强 |
| 12 | `Xaml/Template/InstructionGraph/InstructionNode.xaml` | 指令图：单个节点 | 强 |
| 13 | `Xaml/Template/InstructionGraph/InstructionParam.xaml` | 指令图：节点参数 | 强 |
| 14 | `Xaml/Template/Node/NodeInspector.xaml` | 节点检查器（属性检视面板） | 强 |
| 15 | `Xaml/Template/UI/UIPreviewTab.xaml` | 界面预览页签（自定义界面预览） | 强 |
| 16 | `Xaml/Template/UI/Panels/SearchPanel.xaml` | 搜索面板 | 强 |
| 17 | `Xaml/Template/UI/Dialog/CompoundSaveAlertDialog.xaml` | 复合节点保存提示对话框 | 强 |
| 18 | `Xaml/Template/UI/Dialog/ExplorerReferenceDialog.xaml` | 资源引用关系对话框 | 强 |
| 19 | `Xaml/Template/UI/Dialog/ExternalResourceSaveAlertDialog.xaml` | 外部资源保存提示对话框 | 强 |
| 20 | `Xaml/Template/UI/Dialog/FactionChangeAlertDialog.xaml` | 阵营变更提示对话框 | 强 |
| 21 | `Xaml/Template/UI/Dialog/GMDialog.xaml` | GM 对话框（开发者/作弊工具） | 强 |
| 22 | `Xaml/Template/UI/Dialog/InstructionGraphLogDialog.xaml` | 指令图日志对话框（调试台） | 强 |
| 23 | `Xaml/Template/UI/Dialog/SignalMgtDialog.xaml` | 信号管理对话框 | 强 |
| 24 | `Xaml/Template/UI/Widget/ExplorerCellTemplate.xaml` | 浏览器单元格模板 | 强 |
| 25 | `Xaml/Template/ControlCommon/ContextMenu/ContextMenuWithSearchBox/TreeViewItemForContextMenuWithSearchBox.xaml` | 带搜索框的右键菜单树项 | 强 |

### 7.3 `BydeCustomControl` 程序集（19）

| # | XAML 路径（`component/` 后） | 用途推断 | 证据等级 |
|---:|---|---|---|
| 1 | `Xaml/Const/Const.xaml` | 常量样式表 | 强 |
| 2 | `Xaml/Template/Dock/DockTabItem.xaml` | 停靠页签项 | 强 |
| 3 | `Xaml/Template/Dock/SimpleDock.xaml` | 简易停靠容器（面板可拖拽停靠） | 强 |
| 4 | `Xaml/Template/Node/NodeGraph.xaml` | 节点图画布（通用控件版） | 强 |
| 5 | `Xaml/Template/Node/NodeParam.xaml` | 节点参数行（通用控件版） | 强 |
| 6 | `Xaml/Template/UI/Dialog/DynamicWorkloadDialog.xaml` | 动态负载对话框 | 强 |
| 7 | `Xaml/Template/UI/Dialog/ShortCutDictionaryDialog.xaml` | 快捷键字典对话框 | 强 |
| 8 | `Xaml/Template/UI/Dialog/StructFastEditDialog.xaml` | 结构体快速编辑对话框 | 强 |
| 9 | `Xaml/Template/UI/Popup/PopupCollection.xaml` | 弹出层集合容器 | 强 |
| 10 | `Xaml/Template/UI/Widget/DragDrop/DragDropContent.xaml` | 拖拽内容控件 | 强 |
| 11 | `Xaml/Template/ControlCommon/Button/ButtonCommon.xaml` | 通用按钮样式 | 强 |
| 12 | `Xaml/Template/ControlCommon/CheckBox/CheckBoxCommon.xaml` | 通用复选框样式 | 强 |
| 13 | `Xaml/Template/ControlCommon/MenuItem/MenuItemCommon.xaml` | 通用菜单项样式 | 强 |
| 14 | `Xaml/Template/ControlCommon/Seperator/SeperatorForMenu.xaml` | 菜单分隔线 | 强 |
| 15 | `Xaml/Template/ControlCommon/TextBlock/TextBlockCommon.xaml` | 通用文本样式 | 强 |
| 16 | `Xaml/Template/ControlCommon/TextBox/TextBoxCommon.xaml` | 通用输入框样式 | 强 |
| 17 | `Xaml/Template/ControlCommon/TreeView/TreeViewCommon.xaml` | 通用树控件样式 | 强 |
| 18 | `Xaml/Template/ControlCommon/Window/DialogWindowCommon.xaml` | 通用对话框窗口样式 | 强 |
| 19 | `Xaml/Template/ControlCommon/Window/TabWindowCommon.xaml` | 通用页签窗口样式 | 强 |

> 计数核对：7.2 表 **25** 条 + 7.3 表 **19** 条 = **44** 条 `pack://application:,,,/...xaml` 引用（已用 `grep -oE 'pack://application:,,,/[A-Za-z0-9_]+;component/[A-Za-z0-9_./]+\.xaml' | sort -u | wc -l` 核实为 44）。
>
> 另有 3 条 XAML 名**不在 `pack://` 引用中**，只以「样式 / 模板键」形式出现在字符串表里，故未计入上表：
> - `Template_NodeIndexIndicator_Dragger_In` / `Template_NodeIndexIndicator_Dragger_Out`（节点序号指示器拖拽点，配 `vmIndexIndicator` 绑定）；
> - 小写路径 `/BeyondEditor;component/app.xaml` 与 `/BeyondEditor;component/mainwindow.xaml`（应用入口与主窗口，见 `string-categories.txt` 的 `### PATHS` 段）。
>
> 因此「XAML 清单」在严格 `pack://` 口径下是 44 条，在「所有可辨识 XAML 名」口径下是 47 条（含上述 3 条）。两个口径都列出，避免下游误用。

### 7.4 面板名的独立旁证：View-Model 绑定名

字符串表里还原出一批 **view-model / 绑定字段名**（`string-categories.txt`，前缀 `vm*`），与上面的 XAML 面板**一一对应**，构成**第二证据**：

| 绑定名 | 对应面板 |
|---|---|
| `vmInstructionGraphContainer` / `vmGraph` / `vmGraphList` / `vmGraphFilterExplorer` | `InstructionGraph` |
| `vmNodeExplorer` / `vmNodeList` | `NodeExplorer` |
| `vmInstructionExplorer` | `InstructionExplorer` |
| `vmResourceExplorer` / `vmResourceView` / `vmResourceCategoryList` | `MainResourceExplorer` |
| `vmNodeParamInspector` / `vmInspector` | `NodeInspector` |
| `vmSearchPanel` / `vmSearchBox` | `SearchPanel` |
| `vmCompoundNodeEditPanel` | `BeyondComponentEditPanel`（复合节点编辑） |
| `vmGraphLog` / `vmGraphLogFilter` / `vmDebugLogList` / `vmDebugInfoList` | `InstructionGraphLogDialog` |
| `vmSignalList` / `vmBtnOpenSignalEditPanel` / `vmEditableTextSignalName` | `SignalMgtDialog` |
| `vmStructItems` / `vmBtnEditStruct` / `vmCurEditableStructVar` | `StructFastEditDialog` |
| `vmVarPanel` / `vmVariables` / `vmValueVar` / `vmBtnVar` | 变量面板（`BP_VARIABLES`） |
| `vmPathPanel` | 路径面板（`LevelPath`） |
| `vmCategory` / `vmCategoryRoot` / `vmCategorySearch` | 资源分类树 |
| `vmTabs` / `vmTabItems` / `vmSelectRect` | 页签容器 |
| `vmToolBar` | 工具条 |
| `vmPopUpCollection` → `vmPopupCollection` | `PopupCollection` |
| `vmIndexIndicator` | `IndexIndicator` |
| `vmAttachGrid` / `vmHideAttachGrid` | 吸附网格 |
| `vmWrapView` / `vmWindowHeader` / `vmMainGrid` / `vmContainer` | 窗口框架 |

> 这些绑定名同时证明：**面板不是静态 XAML 展示，而是有完整 MVVM 绑定与命令**（`vmBtnSave` / `vmBtnUndo` / `vmBtnRedo` / `vmBtnConfirm` / `vmBtnCancel` …）。它们与 `UI-TEXT-INVENTORY.md` 第三章的功能域划分**一致**，此处不重复展开。

### 7.5 XAML 面板与 UI 文本键的对应（引用，不重复）

`UI-TEXT-INVENTORY.md` 已给出 TextMap 侧的功能域划分（`2.4 UI_BEYOND` 一节）。本节的 XAML 面板是**同一批界面在程序集侧的名字**。两文对应关系：

| XAML 面板 | UI-TEXT-INVENTORY 中的键族 |
|---|---|
| 主窗口 / 资源管理器 | `UI_BEYOND_ASSIST_EDITOR_DEFAULT_*`、`RESOURCE_*` |
| 节点图编辑器 | `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_*`、`COMPOSITE_*`、`NODE_*` |
| 节点图日志 / 调试台 | `UI_BEYOND_LOG_*` |
| 信号管理 | `UI_BEYOND_ASSIST_EDITOR_SIGNAL_*` |
| 结构体 / 字典 | `UI_BEYOND_ASSIST_EDITOR_ADVANCED_*` |
| 负载检测 | `UI_BEYOND_ASSIST_EDITOR_COSTLOAD_*` + `UI_BEYOND_COSTLOAD_*` |
| 快捷键字典 | `BEYOND_EDITOR_SHORTCUT_KEY_*` |
| GM 对话框 | （TextMap 中无独立键族，**说明它是开发者向界面，不做本地化**） |

> `GMDialog.xaml` 在 TextMap 的 385 条 `UI_*` 键与 934 条 `UI_BEYOND*` 键中**找不到对应键族**——这是「GM 对话框属内部工具」的**推断性旁证**（不做本地化 ⇒ 不对玩家开放）。

---

## 八、边界：证据等级与未覆盖部分

### 8.1 证据分级

| 等级 | 含义 | 本文中的例子 |
|---|---|---|
| **A. 实测双证据** | 图标名 + 官方文档/代码均可对上 | 组件清单（30 图标 vs 官方 29 条）、光源 2 类、音效 3 种衰减、背包 6 页签 |
| **B. 单强证据（文件名枚举）** | 仅来自图标/XAML 文件名，语义明确 | 主工具栏 410 个的绝大多数、44 个 XAML 面板、2399 个元件分类 |
| **C. 推断** | 由文件名语义推出中文含义或行为 | 所有中文译名、`Lvy`=绿植、`Struct` 的 `长_高_宽` 尺寸编码、`FreeChipEditing` 的含义 |
| **D. 存疑** | 存在矛盾或无法确定 | 见 8.2 |

### 8.2 明确存疑项（不得当作已证实）

1. `UI_Icon_UGCEsc_FreeChipEditing` —— `Chip` 语义不明，可能是「模块/广告位/芯片」，无官方条目对应。
2. `UI_Icon_UGCEsc_Shield` —— 是「护盾组件」入口还是「锁定保护」语义，无法判定。
3. `UGCAvatarDisturber_Type_Path` —— 官方文档只列 3 类扰动装置（弹射/牵引/力场），图标有 4 个。
4. `UGCMover_Type_`（5）vs 官方「基础运动器 6 种」—— 数量对不上，缺哪一种未定。
5. `UGCBulletMove_Type_`（3）vs 官方「直线/抛物线/追踪（含吸附追踪）/圆周」—— 官方多出 2 种。
6. `UGCMainTab_Preset` 与 `UGCMainTab_Prefab` 的语义边界（预设状态 vs 预制体）。
7. `BydeCustomControl` 程序集的分发形式与是否可独立加载（**待证**）。
8. `Struct_*` 系列元件名里的三数字编码（如 `Cube_25_25_25`）是否为尺寸，**推断**，未见代码确认。
9. `_enums.txt` 的 589 组枚举属于**节点图配置枚举**，与图标子类型枚举**不是同一套**；文中已分别标注，勿交叉引用。

### 8.3 覆盖边界（本文**没有**覆盖的）

1. **未覆盖图标数量之外的资源**：`assets.bin` 只含 5 个 UI 图集目录（效应/元件/工具栏/怪物/动物）。编辑器的**模型、贴图、音频、场景资源不在此容器内**，本文对其无任何结论。
2. **未实机验证**：本文没有运行编辑器，所有功能**未经 UI 点击验证**。所有「中文功能」是**译名推断**，不是官方译名。官方译名请查 `UI-TEXT-INVENTORY.md` 的 TextMap 条目。
3. **未解出图标与具体 UI 控件的绑定**：图标文件名与 XAML 里的控件/命令之间**没有被代码级地连起来**（例如无法证明 `Brush_Path` 图标对应哪个 Button 的哪个 Command）。`vm*` 绑定名提供了 MVVM 侧的旁证，但不是逐图标实证。
4. **未覆盖节点图节点库**：800 个节点指令的目录与分类由 `OFFICIAL-FUNCTION-INVENTORY.md` 与 `.runtime/editor-catalog/node-catalog-full.json` 承担，本文不重复。
5. **未覆盖界面文本**：由 `UI-TEXT-INVENTORY.md` 承担，本文只做交叉引用。
6. **未覆盖官方文档 207 条**：由 `OFFICIAL-FUNCTION-INVENTORY.md` 承担。
7. **反编译不完整**：本轮反编译 12375 个类型，**2555 个类型反编译失败**（`decomp-beyondeditor.log`），另有 1 个类型因文件名含 `<` `>` 且路径过长而写盘失败（`_ERR_GFifhidO9uuliUYZu5.rIrxakxYdpK4luEUmh_<FromStreamAsync>d__15`）。因此 XAML 清单**可能不完整**——特别是 `BydeCustomControl` 侧的 XAML 若只在未反编译到的类型里被引用，本文就看不到。
8. **未做网络访问**：本文全部结论来自本地文件，无任何联网校验，因此无法排除「图标存在但功能已在后续版本移除」。

### 8.4 本次操作的安全性声明

- 全程**只读**：对游戏目录只执行了 `ls` / `find` / `sha256sum` / Python `zipfile` 打开（`ZipFile` 只读模式），**未写入、未修改、未删除游戏目录任何文件**；
- **未运行**编辑器、未运行桥接脚本、未运行 PS1 脚本；
- **未关闭/终止/重启任何进程**；
- **未联网**；
- 解密产物只写入工程内 `.runtime/editor-catalog/assets-bin/`。

---

## 附：本目录相关文档索引

| 文档 | 内容 | 与本文关系 |
|---|---|---|
| `docs/editor-catalog/OFFICIAL-FUNCTION-INVENTORY.md` | 官方 207 条文档功能清单 | 本文第七章的官方侧对证来源 |
| `docs/editor-catalog/UI-TEXT-INVENTORY.md` | TextMap 界面文本（7743 键） | 本文的界面文本侧对证来源，**不重复** |
| **`docs/editor-catalog/UI-ASSET-INVENTORY.md`（本文）** | 图标名 + XAML 面板名 → 功能清单 | — |

**中间产物**（均在 `.runtime/editor-catalog/`）：`toolbar-icons.txt`、`gadget-icons.txt`、`assets-manifest.json`、`assets-bin/assets.dec`、`string-categories.txt`、`literal-to-types.json`、`_enums.txt`、`annotated/`（12375 个反编译 .cs）。
