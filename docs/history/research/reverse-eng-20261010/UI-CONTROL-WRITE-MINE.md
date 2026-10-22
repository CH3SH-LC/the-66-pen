> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #4 挖 — `ui.hud`：写路径在哪？（UI 控件写入挖掘）

> 建立日期：2026-10-10。位置：`docs/research/reverse-eng-20261010/UI-CONTROL-WRITE-MINE.md`。
> **本轮零执行**：全程离线，未连接 bridge、未发送任何 native/graph 请求、未启动/触碰游戏或编辑器、
> 未读写下 `AppData/LocalLow/miHoYo/`。本文所有"能/不能"均为**静态阅读（仓内源码 + 离线语料 + 离线合同）**，
> `runtime_verified=false`。凡未能给出 `file:line` 或离线证据的，一律降级标注。
>
> 前置阅读：`docs/research/game-b-systems-20261009/F5-visible-feedback.md`（下称 **F5**）、
> `docs/research/game-b-systems-20261009/M1-interaction.md`（下称 **M1**）、
> `docs/offline-research/CONTRACT-V18-UI.md`（下称 **V18**）、
> `docs/offline-research/UI-DATA-WORKFLOWS.md`（下称 **UIDW**）、
> `docs/research/reverse-eng-20261010/COMMAND-ROUTE-MAP.md`（下称 **CRM**）、
> `docs/research/reverse-eng-20261010/SETTER-SIGNATURE-SURVEY.md`（下称 **SSS**）、
> `docs/research/reverse-eng-20261010/MINED-INTERFACES.md`（下称 **MI**）。

---

## 0. 一句话结论

1. **编辑器侧：没有任何 UI/面板/控件的写入口。** 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 **0** 条命中 ui/控件/组件/属性
   （复跑见 §6.1）；`Adapter/` 里与 UI 沾边的只有两个文件，**都只"打开/导航"，不能改一个控件的属性**——
   `PanelOpen.cs` 只能 invoke「节点管理器」「资源管理器」两个菜单项（`PanelOpen.cs:36`），
   `FrontendCommands.cs` 只能走资源树并**只读**回字段（`FrontendCommands.cs:229-230` 自述
   "Observation only: no delegate invocation, command execution, … or model field writes."）。
   前端 38 条命令里**没有一条**是 UI 控件写（CRM §2）；能改已存在对象的只有 Name/Tag/Faction/Suite
   （CRM:178-184），组件侧只有 `DeleteComponentFor*`（CRM:53-54），**没有 AddComponent**。
2. **运行期节点侧：`界面控件组` 四节点（316/383/384/521）只能操纵"已存在的资产"，不能创造 UI。**
   四者都是 **server** 节点（`graphKindRaw=20000`，category `[10001,20000,22000,0]`），
   入参一律是 **`界面控件组索引`（整数）**——这个索引由编辑器「界面控件组详情窗口 → 保存/创建组合」
   生成（V18 MC-S3/S4）。它们能显示什么，取决于运行时**已经存在**一个由编辑器手工配好的控件组。
3. **但"玩家可见 + 不需要任何 UI 资产"的运行期写路径是存在的——不在 UI 家族，而在 `presentation` 家族**
   （`激活屏幕震动 266`、`修改模型颜色和材质 835`、`激活/关闭模型显示 308`、`镜头 261/262/264`、
   `玩家播放单次2D音效 598`、`特效 93/94`）。这些是 **server 节点**，入参是**标量**（float/bool/int/string）
   或**实体引用（用连线供给，不用写字面量）**，**不需要任何界面控件组 / 文本气泡组件 / 小地图标识组件**。
   这是"让玩家看见/听见"最省事的一条路，也是本文要挖出来的东西。**状态 = CANDIDATE（未真机验证）。**
4. **`打印字符串`（节点 1）不是玩家可见渠道。** 它只写进**编辑器的「节点图日志」窗口**
   （`窗口——日志`），是给作者调试用的（§2.3）。"日志打印 ≠ 玩家可见反馈"在仓内已有正式判决
   （`tools/authoring/INTERFACE-INVENTORY.md:42`、`docs/PROGRESS-BY-FUNCTION.md:54`）。
5. **若把问题限定在"UI/HUD 那条线"**（文本框、计分板、消息队列、悬浮交互页、文本气泡、小地图标识），
   答案就是 **"没有 UI 资产，玩家什么都看不见"**——每一条都要一个**编辑器手工创建、并在运行前存在的资产**
   （控件组 / 组件 / 素材组），且这个资产的**磁盘格式与保存 API 至今未知**（V18 UN-10/UN-12、UIDW:9）。

---

## 1. 方法与口径

- **三层分离**（遵循 `CLAUDE.md` §一.3）：① 官方文档写了什么；② 工具/源码能做什么（离线已证）；
  ③ 真机验证过什么。本文只到 ①/②；③ **一律"未验证"**（本轮零执行）。
- **UI 家族的定义（本文口径）**：需要"编辑器里手工配出来的 UI 资产"才能生效的玩家可见面。包含
  界面控件组及其全部控件、文本气泡组件、小地图标识组件、素材组、悬浮交互页、消息队列。判定来源：V18、UIDW。
- **presentation 家族**：不依赖 UI 资产、直接作用于世界/镜头/音频的 server 节点（`INTERFACE-INVENTORY.md:41`
  的 `game.presentation` 行，状态 `research`）。这是第 3 点的"旁路"。
- 证据层标注：`[文档]` = 官方语料；`[源码]` = 仓内源码/离线合同；`[负结论]` = 已证做不到。

---

## 2. 编辑器侧：`Adapter/` 里到底有什么（逐条，带 file:line）

### 2.1 `Adapter/PanelOpen.cs` — 只能"开面板"，不能"改控件"

| 事实 | 证据 |
|---|---|
| 目标面板是一个**写死的 2 元素白名单**：`{ "节点管理器", "资源管理器" }` | `tools/editor-bridge/Adapter/PanelOpen.cs:36` |
| 做法：遍历编辑器对象图，找带 `MMGKX5coQC4`（label）字段的对象，**精确等值匹配**后 `DynamicInvoke` 它自己的 `Te1KXhuGxBC`（Action） | `PanelOpen.cs:31-32`、`:57-96` |
| **没有**「界面控件组管理」这个面板（白名单里没有）；也**没有**任何"设置某控件某属性"的代码 | `PanelOpen.cs:36` 全数组；全文无 setter 调用 |
| 打开后只能**读回窗口标题**（`CurrentCaptions()`）证明"面板开了"，不证明面板内容 | `PanelOpen.cs:105-120` |

**结论**：`OpenEditorPanel` 能做的最多是"把资源管理器/节点管理器显示出来"，**它不是写入口**。

### 2.2 `Adapter/FrontendCommands.cs` — 只走资源树 + 只读

| 方法 | 能做什么 | 不能做什么 | 证据 |
|---|---|---|---|
| `OpenSceneResourceFolder()` | 对**场景资源文件夹**（tag 路径 `[40000,40003,41101,40004]`）调一次原生**导航**方法 `SyTKwRXfIBP`，产生"前端选中" | 不改任何字段；自带 `notice = "Invocation only; requires independent frontend readback."` | `FrontendCommands.cs:38`、`:137-151` |
| `LoadSceneResourceModel()` | 对场景文件夹调一次原生**加载**方法 `vF1Yj4iJnve`（`native-resource-model-load-invoked`） | 只处理 `containerType==3` 的场景文件夹（或历史 lab-cube `313584`）；不改字段 | `FrontendCommands.cs:153-197` |
| `FocusLabCubeFromFrontend()` | 对固定 lab-cube 资源调一次原生**聚焦**方法 | 聚焦是"看"，不是"改" | `FrontendCommands.cs:199-227` |
| `InspectFrontendCommands()` | **纯只读**：反射读前端命令元数据（delegate / ICommand），**显式不 invoke、不写** | 方法头注释：`Observation only: no delegate invocation, command execution, CanExecute, application property getters, RPC, or model field writes.` | `FrontendCommands.cs:229-231`、返回值 `:431-438` |

**结论**：`FrontendCommands.cs` 是"资源树导航 + 只读回显"，**不是写入口**；它对 UI 资产既不会建、也不会改。

### 2.3 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）：一个 UI 写都没有

- 实测：`grep -oE 'case "[a-z0-9-]+"' tools/editor-bridge/ManagedBridge/BridgeServer.cs | sort -u` → 现值见 tools/gameplan/tests/test_doctrine.py。
  与 UI/组件/属性沾边的只有 6 条**导航/只读** op：`open-editor-panel`、`open-resource-manager`、
  `open-scene-resource-folder`、`load-scene-resource-model`、`focus-lab-cube-from-frontend`、
  `inspect-frontend-commands`（op 全表见 §6.1 复跑脚本）。
- 一致的既有负结论：`MI.md:247`「桥写 UI / 组件 / 属性 / 模板：桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 **0 命中**」；`M1.md:70` 同。
- `ui.hud` 的注册表行仍是 `research / 尚无完整入口`：`tools/authoring/INTERFACE-INVENTORY.md:42`
  （原文「日志打印不等于玩家可见反馈；固定结算节点不等于自定义UI」）。

### 2.4 前端命令面：能改的已存在对象只有 4 类，且没有 UI

- CRM 逐条清点 38 条 `command_route`：语义只有 建图 / 删除 / 聚焦面板 / 改名 / 标签 / 阵营 / Suite /
  请求-应用 / 导入导出 / 调试日志 / 音频-PCG（CRM:167-174）。**没有任何一条是 UI 控件写。**
- 能"写已存在对象字段"的只有三处：`ModifyFactionForEditObj`（int32 → 对象 `+0x30`）、
  `ModifyEditobjTag`（标签数组增删）、`ModifyEditObjName`（一个字符串）（CRM:178-184）。
- 组件侧：命令表里只有 `DeleteComponentForEditObj` / `DeleteComponentForPrefab`（CRM:53-54），
  **没有对应的 AddComponent**。(`AddInstructionGraphForEditObj` 是"把节点图挂到实体"，不是加组件。)
- 编辑器资源树里**确实有一个叫「界面控件组」的分支**（`docs/research/beyondeditor-frontend/db/raw/menu-tree.json:1276`
  等 6 处 `…subFolders_*_name = 界面控件组`；另有枚举 `…_maps_24_mapTitle = 界面控件组状态`，`:246`/`:736`）——
  说明 UI 控件组在编辑器里是**资源树里的一个类目**。但截至本轮，**没有任何反射符号或命令指向这个类目**
  （`docs/research/beyondeditor-frontend/`、`…user-operations/`、`…backend/` 全目录搜
  `Widget/UIControl/ControlGroup/HudElement` 命中 0 个"控件组类"）。

> **为什么"搜不到"不能当"不存在"**：编辑器资源树里有这个类目（menu-tree.json），说明它作为资源**是被编辑器加载的**；
> 缺的是"能走到它的反射符号"。见 §5「要挖什么」。

---

## 3. 运行期节点侧：`界面控件组` 四节点（316/383/384/521）

四节点在离线合同里的定义与端口（全部 `graphSide=server`、`categoryVariant=[10001,20000,22000,0]`）：

| defId | 名称 | 定义 | 端口（方向 · 名 · 类型码） | 语义 |
|---:|---|---|---|---|
| **316** | 界面控件组触发时 | `definitions/bucket-04.json:2378`；`variants/server/bucket-04.json:6151` | out 事件源实体/事件源GUID/界面控件组组合索引/**界面控件组索引** | **事件**（控件被点 → 触发玩家节点图） |
| **383** | 激活控件组库内界面控件组 | `definitions/bucket-04.json:2868`；`variants/server/bucket-04.json:7674` | in 目标玩家 · **界面控件组索引**(2) | 让已存在的控件组生效 |
| **384** | 设置界面控件(组)状态 | `definitions/bucket-00.json:1888`；`variants/server/bucket-00.json:3980` | in 目标玩家 · **界面控件(组)索引**(2) · **显示状态**(6) | 改已存在控件组的表现状态 |
| **521** | 移除控件组库内界面控件组 | `definitions/bucket-03.json:2765`；`variants/server/bucket-03.json:5734` | in 目标玩家 · **界面控件组索引**(2) | 移除已存在的控件组 |

**读法（这是本节的关键）**：

- 四个节点**没有一个是"创建/配置控件"的**。383/384/521 的 `界面控件组索引` 是**整数**——它寻址的是
  编辑器「界面控件组详情窗口」里"保存为模板 / 创建组合"后**生成的索引**（V18 MC-S3/S4、RB-10；
  `docs/official-docs/chapters/mhewyi0fjfvs.txt` 语料）。
- 316 是**接收端**：它只在**已经存在**一个可交互控件（交互按钮/自定义按钮/道具展示/自定义开关）被点时才触发
  （V18 IE-01/IE-02）。
- 因此：**"跑一条运行期节点就能让玩家看见"在 UI 家族里不成立**——前提是那个 UI 资产**先由人手工建好**。
  这与 F5 §4/§5 的结论一致（F5:46、:67）。

**能否把这些节点加进图？** —— 是 **CANDIDATE**，离线判定为"应当可以"：
桥加节点的规则是**通用**的，不是写死白名单——`AuthoringGraph.cs:322` 按 `r.Kind==6 && r.Id==definitionId &&
r.Category.SequenceEqual(authorCategory)` 解析，`AuthorGraphKinds={20000,20001,20002,20007}`
（`AuthoringGraph.cs:17`），`AuthorCategory(graphKind) = {10001, graphKind, 22000, 0}`（`AuthoringGraph.cs:32`）。
316/383/384/521 的 category 正是 `[10001,20000,22000,0]`，**落在受理集内**。且同类通用加节点已真机
（`92`/`688`/`691` 进过图，`docs/gameplan/README.md:106`、`MI.md:58`）。**但**涉及"加这些节点并读回"
本轮**未真机**，且 M1:74-75 的旧口径"仅 71/1 可加"与现行通用规则冲突——以通用规则为准（R249 已修分类硬编码，
见记忆 `client-nodes-blocked-by-hardcoded-category`）。**结论：CANDIDATE，需一次 `build-plan` + 独立 `inspect` 落定。**

---

## 4. 核心问题：有没有"不需要 UI 资产"就能让玩家看见的写路径？

### 4.1 先否掉两个常见候选

**(a) `打印字符串`（节点 1）——不是玩家可见。** `[文档]`
- 官方「节点图日志」章：日志的**唯一入口**是「从**窗口**——日志，打开节点图日志窗口」，内容是
  「节点图事件」与「打印信息」两类，后者「通过【打印字符串】节点打印的信息」
  （`docs/official-docs/chapters/mhu951iz7wz8.json` headline + facts）。这是**编辑器的窗口**，属作者工具。
- 官方「执行节点」章：打印「无论是否勾选了该节点图，逻辑成功运行时该字符串都会打印」——即**日志**行为
  （`docs/official-docs/chapters/mhw66orrrfkm.json` facts）。
- 仓内判决：`tools/authoring/INTERFACE-INVENTORY.md:42`、`docs/PROGRESS-BY-FUNCTION.md:54`、
  `MI.md:247` 均把"日志打印 ≠ 玩家可见反馈"写死。
- **⇒ 节点 1 是"作者可见"，不是"玩家可见"。** demo 里那条 `打印 材料不足`（`.runtime/scratch/MW_API_FARM_DEMO-plan.json:283-289`）
  只有开编辑器日志的人看得见。

**(b) `文本气泡` / `小地图标识`——需要实体上先挂组件，且那个组件工具建不了。** `[文档]`
- 文本气泡组件：必须"在**实体/元件编辑界面** → 组件编辑页签 → 添加组件 → 文本气泡 → 详细编辑"手工挂载；
  节点 `631 切换生效的文本气泡` 只按 **`文本气泡配置ID`** 在**已配好的气泡列表**里切换生效项
  （`docs/official-docs/chapters/mhwtz297kp6a.json`；端口见 `variants/server/bucket-02.json:7283`：
  `目标实体` + `文本气泡配置ID(1)`）。
- 小地图标识组件：同样要"添加组件 → 小地图标识"手工挂载；节点 `640 设置小地图标识的玩家标记`
  按 `小地图标识序号` 寻址（`docs/official-docs/chapters/mh0pppib5eyc.json`；端口 `variants/server/bucket-00.json:5750`）。
- **牌子 = 显示数字是工程侧推断，不是官方陈述**（F5:74-75 已判："牌子 = 显示数字"是推断；
  「告示牌/提示牌」在官方语料里 0 命中）。
- 工具能不能挂组件？**不能**——命令面只有 `DeleteComponent*`（CRM:53-54），**无 AddComponent**；
  桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）亦无组件写（MI:247）。
- **⇒ 文本气泡与小地图标识，在没有编辑器手工挂载组件的前提下，写不了。**

### 4.2 真正可行的旁路：`presentation` 家族（不需要任何 UI 资产）

以下节点**全部是 server 节点**（`graphKindRaw=20000`，category `[10001,20000,22000,0]`），
**入参是标量或实体引用（实体引用用连线供给）**，**不涉及任何 UI 资产 / 组件 / 素材组**：

| defId | 名称 | 端口（关键入参） | 玩家可见形态 | 合同位置 |
|---:|---|---|---|---|
| **266** | 激活屏幕震动 | 玩家实体列表(List) · 震幅(4) · 震动时长(4) · 震源距离(4) | **屏幕震动**（视觉+tactile） | `variants/server/bucket-05.json:2230` |
| **835** | 修改模型颜色和材质 | 目标实体 · 是否覆写颜色(bool) · 是否启用自定义颜色(bool) · 填充颜色(2) · 颜色透明度(4) · 颜色叠加类型(6) · … | **改一个实体的可见颜色/材质** | `variants/server/bucket-03.json:14173` |
| **308** | 激活/关闭模型显示 | 目标实体 · 是否激活(6) | **显示/隐藏一个模型** | `variants/server/bucket-06.json:3126` |
| **261** | 切换主镜头模板 | 目标玩家列表(List) · 镜头模板名称(5, **字符串**) | **切镜头**（画面变化） | `variants/server/bucket-06.json:2354` |
| **262/263** | 激活/停用实体镜头 | 玩家实体列表 · 目标实体 | 镜头跟随/停止 | `variants/server/*`（ids 262/263） |
| **264/265** | 激活/停止注目镜头 | 玩家实体列表 · 目标实体 | 运镜 | ids 264/265 |
| **598** | 玩家播放单次2D音效 | 目标实体 · 音效资产索引(2) · 音量(2) · 播放速度(4) | **听得见**（2D 音效） | `variants/server/bucket-01.json:9319` |
| **594** | 添加音效播放器 | 目标实体 · 音效资产索引 · 音量 · … · 是否3D · 挂接点 | **运行时给实体挂一个发声体** | `variants/server/bucket-03.json:6511` |
| **93/94/95/473** | 播放/挂载/清除限时-循环特效 | 特效资产(1) · 目标实体 · 挂接点 · … | **世界内特效** | `variants/server/bucket-04.json:1314`（94） |

**关键点（为什么这条不需要 UI 资产）**：

1. 这些节点的入参**没有索引到"界面控件组库"**——不需要 UI 资产。
2. **实体引用怎么给**：**不靠写字面量，靠连线**。已真机的 demo 图里所有实体/玩家引用都是边
   （`.runtime/scratch/MW_API_FARM_DEMO-plan.json:79-215` 的 `edges`，例如 `92 进入碰撞触发器时` 的出端口
   `fromKind:4` → `686` 的 `toKind:3`），**没有任何一个 entity-ref 字面量**（同文件 `values` 段只有
   `slot:"int"` 与 `slot:"string"`）。所以 `266` 的 `玩家实体列表` 可由 `248 获取在场玩家实体列表`
   （`variants/server/bucket-04.json:2199`，输出 `玩家实体列表(List)`）连线供给；`835/308` 的 `目标实体`
   可由事件节点输出连线供给。
3. **标量写入的现状**（这是本路线的缺口，见 §5）：写口 `AuthorWriteScalar` 有 `int/enum/bool/float/string`
   五个分支（SSS §2），其中 `int`/`enum` 的读回 getter 在档（闭环），`bool/float/string` **写进去但读回抛**
   （SSS §4.2，`AuthoringGraph.cs:938/950/964`）；`vector(7)` 用"3 次 float 写"绕（SSS §5 注）。
   `266` 的三个参数全是 float → **借道 S4**（受 bool/float 读回缺失连坐）；`835` 全 bool/int/enum → 可用。

**⇒ 结论**：**"玩家可见 + 零 UI 资产"的写路径存在（presentation 家族）**，但它是
**CANDIDATE**：① "这些 server 节点能被桥加进图"需一次真机 `build-plan`+`inspect`；
② 其**运行时语义**（屏幕震动/改色是否真在试玩里发生）**本轮无法离线判定**（`docs/gameplan/README.md:98-99`
   明写 runtimeVerified:false 一直保留）。

### 4.3 "UI/HUD 那条线"的完整依赖图（要资产 → 现在建不了）

| 渠道 | 需要的**编辑器手工资产** | 运行期节点 | 工具能否建该资产 |
|---|---|---|---|
| 文本框 / 计分板 / 进度条 / 道具展示 | 界面控件组 + 控件模板 + **客户端控件容器**（全称硬约束） | 383/384 激活/设状态；文本框变量自更新无需推 | ❌（桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）0 命中；无 AddComponent；V18 UN-10） |
| 消息队列 | 消息队列控件（素材/排列/对齐） | **833 更新消息队列**（结构体整体推） | ❌ |
| 悬浮交互页 | 悬浮交互页控件（容器/页签/列表） | 824/825/828 | ❌ |
| 选项卡 / 礼盒 / 排行榜 | 选项卡控件 / 礼盒 / 排行榜控件 | 306-307 / 856 / 762 | ❌ |
| 文本气泡 | 实体上的**文本气泡组件**（含配置条目） | 631 切换生效的文本气泡 | ❌（组件无写入口） |
| 小地图标识 | 实体上的**小地图标识组件**（≤50，LM-05） | 640 / 636 / 637 | ❌（同上） |

> 硬前置：`客户端控件容器`——「界面布局中不存在客户端控件容器时，所有客户端控件和挂载在控件上的脚本将无法
> 正常运行和显示」（`docs/official-docs/chapters/mhlz2lrly3dq.json`）。没有它，**连点都不显示**。

---

## 5. 排序：玩家可见渠道 by 可行性（含缺失原语）

**排序口径**：1) 是否**不需要**任何编辑器手工资产；2) 用现有写口（`build-plan` + `set-value`）能否落地；
3) 是否已有同类真机先例。**所有 CANDIDATE 都只到"离线可行"这一层，运行时语义一律未证。**

| 名次 | 渠道 | 需要的手工资产 | 用什么写 | 缺失原语 | 证据 | 状态 |
|---:|---|---|---|---|---|---|
| 🥇 1 | **激活屏幕震动（266）** | **无** | server 节点；3×float + 玩家列表（248 连线） | float pin 的**读回 getter**（写进去、读回抛，SSS §4.2）；"266 能否加进图"待证 | `variants/server/bucket-05.json:2230`；`AuthoringGraph.cs:322`；`SSS:207-222` | CANDIDATE |
| 🥈 2 | **修改模型颜色和材质（835）** | **无** | server 节点；bool/int/enum + 目标实体（连线） | bool 读回 getter（同上）；目标实体连线可用 | `variants/server/bucket-03.json:14173` | CANDIDATE |
| 🥉 3 | **激活/关闭模型显示（308）** | **无** | server 节点；bool + 目标实体（连线） | 同上 | `variants/server/bucket-06.json:3126` | CANDIDATE |
| 4 | 镜头（261/262/264/818） | **无** | server 节点；string/list | string/镜头模板语义（261 用"模板名称"字符串，是否自由文本未知）；string 读回 getter | `variants/server/bucket-06.json:2354` | CANDIDATE |
| 5 | 单次2D音效（598）/ 添加音效播放器（594） | **无 UI**，但要一个**音效资产索引** | server 节点；int + float | "音效资产索引从哪来"（目录里是否有可引用 id 未证） | `variants/server/bucket-01.json:9319`、`bucket-03.json:6511` | CANDIDATE |
| 6 | 特效（93/94/95/473） | **无 UI**，但要**特效资产** id | server 节点；特效资产(1) | **实体引用/资产 pin（类型 1）无 setter**（SSS §5）——只能靠连线或已被证明的槽位 | `variants/server/bucket-04.json:1314` | CANDIDATE（弱） |
| 7 | 文本气泡（631） | **文本气泡组件**（手工挂） | server 节点；目标实体 + 配置ID | **组件写入口**（AddComponent / 组件字段写） | `chapters/mhwtz297kp6a.json`；`variants/server/bucket-02.json:7283` | ❌ 缺资产 |
| 8 | 小地图标识（640/636/637） | **小地图标识组件**（手工挂） | server 节点；序号 | 同上 | `chapters/mh0pppib5eyc.json`；`variants/server/bucket-00.json:5750` | ❌ 缺资产 |
| 9 | 界面控件组（383/384/521 + 316 事件） | **界面控件组 + 布局 + 客户端控件容器** | server 节点；**索引** | **UI 资产的建/改原语**（见 §5.1） | `definitions/bucket-04.json:2378/2868`、`bucket-00.json:1888`、`bucket-03.json:2765` | ❌ 缺资产 |
| 10 | 消息队列（833）/ 悬浮交互页（824/825/828）/ 选项卡（306-307）/ 礼盒（856）/ 排行榜（762） | 对应 UI 控件资产 | server 节点；索引 / 结构体 | 同上 + **字典/结构体常量写原语**（833 要"一份结构体"，SSS:255 记"字典无 setter"） | `variants/server/*`（ids 833/824/825/828/306/856/762） | ❌ 缺资产 |
| — | **打印字符串（1）** | **无** | server 节点；string（已真机） | —— | `chapters/mhu951iz7wz8.json`；`.runtime/scratch/MW_API_FARM_DEMO-plan.json:283` | ❌**非玩家可见**（只进编辑器日志） |

### 5.1 要挖什么（缺失原语 = 下一笔逆向的目标）

“**UI 资产写入口**”这一笔不在运行期侧，而在**编辑器资源侧**。三条候选挖法（都还没做）：

1. **资源类目「界面控件组」的建资源原语（首选）。** 编辑器资源树里确有该类目
   （`docs/research/beyondeditor-frontend/db/raw/menu-tree.json:1276/1726/2036/3756/4126/4396`），
   而客户端脚本（同类"编辑器侧资源"）的建/改/删已被反射打通——`ClientScriptCrudProbe.cs:114/125/136`
   用 `B("kqaXokY6uBT")/OtFXociSjVD/IMMXoYC9rQd` 建/改名/删（MI §9 真机）。**要挖的是**
   「界面控件组」资源的同类符号（create/rename/save-as-template），以及它所在的**注册表 tag 路径**
   （场景文件夹是 `[40000,40003,41101,40004]`，`FrontendCommands.cs:38`——UI 控件组的路径未知）。
2. **组件写入口（AddComponent）。** 命令面只有 `DeleteComponentFor*`（CRM:53-54）；要解锁文本气泡/小地图标识，
   得挖 `beyondEditObjService` 里"加组件/写组件字段"的**反射符号**（gameplan §五 M1 行同结论：`docs/gameplan/README.md:106`）。
3. **未解码的后端服务。** `backend.db` 的 `service_route` 里除已解两张表的 `beyondEditObjService`/
   `beyondExportService` 外，还有 `beyondInstructionGraphService`、`beyondEffectService`、
   `beyondRoleStatusService`、`beyondAudioService`、`beyondPCGInstanceService`
   （`docs/research/beyondeditor-backend/db/backend.db` → `service_route` 1-10 行）——
   **这些服务的命令表尚未解码**，是"UI/组件写命令"可能藏身的地方（CRM:200-204 已注明"38 条不是全集"）。

### 5.2 逐条 CANDIDATE 的判定实验（能一次说的清）

> 纪律：这些实验都需要**真机**（本工程禁止在本轮做）。写出它们，是为了让下一次有真机窗口时直接照做，
> **并明确判据**（而不是"编个图看看"）。

| 实验 | 请求（形状） | 判据（怎么算成/败） |
|---|---|---|
| **E1：266/835/308 能被桥加进图** | 一次 `author-graph … build-plan`，plan 含 `[{definitionId:266},{definitionId:248},{definitionId:835},{definitionId:308}]` + 连线（248→266 列表；事件→835/308 目标实体）；随后**独立** `inspect` | `inspect` 读回节点 id/边与 plan 逐项相同，且 `AuthorDeclaredPins>0` 未触发 `AUTHOR_DEFINITION_HAS_NO_DECLARED_PINS`（`AuthoringGraph.cs:340`）。**只证"进图"，不证触发。** |
| **E2：float/bool 标量写入口闭环** | 对 266 的 `震幅/时长/距离`、835 的 bool 槽 `set-value` | 需先补 `ngMKKCVBuMA`/`RJCKKnWqvLO`/`ur7KK2NiYZ4` 三个读回 getter 进 profile（SSS §6.1）；补前 `set-value` 会抛 `EDITOR_BINDING_PROFILE_UNREGISTERED_SYMBOL`（SSS:216）。 |
| **E3：运行时语义（真正的判据）** | 发布/试玩该图，触发一次 | **屏幕是否真的震动 / 模型是否真的变色/隐藏**。这一步是"未验证"的正身；在此之前 266/835/308 一律只能写 CANDIDATE。 |
| **E4：UI 资产写入口是否可挖** | 离线：在 `EditorBindingProfile.Generated.cs` 与 `menu-tree.json` 之间找「界面控件组」类目的反射符号；或解 `beyond*Service` 的下一张命令表 | 找到"建 UI 控件组资源"的符号/命令 ⇒ 从"缺资产"升级为"可建资产"。 |

---

## 6. 复跑命令（任何人可核）

### 6.1 桥 op 全表 + UI 命中（0）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 6.2 节点合同里四节点与 presentation 家族的端口


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 6.3 加节点规则是通用的（不是白名单）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 6.4 demo 的实体引用全部走连线（无 entity-ref 字面量）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 7. 三层标注（严格分开，不得混称）

- **① 文档写了什么**（`docs/official-docs/chapters/*.json`，离线语料，零执行）：
  文本框/计分板/进度条/消息队列/悬浮交互页/特殊数字等控件的字段与前置（V18 §1-§5）；
  「客户端控件容器」全称硬约束（`mhlz2lrly3dq`）；「节点图日志」窗口是**编辑器**入口、打印信息来自【打印字符串】
  （`mhu951iz7wz8`）；文本气泡/小地图标识都是**手工挂载的组件**（`mhwtz297kp6a` / `mh0pppib5eyc`）；
  界面控件组索引由「保存/创建组合」生成（`mhewyi0fjfvs`，V18 MC-S3/S4）。**UI 配置的磁盘格式/保存 API/保存进程
  官方未给**（V18 UN-10/UN-12；UIDW:9）。
- **② 工具/源码能做什么**（`tools/`、`data/node-contracts/`，静态阅读，零执行）：
  桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）**0** 命中 UI/组件/属性（§6.1）；`PanelOpen.cs:36` 只能开 2 个面板；`FrontendCommands.cs:229-230`
  自述只读；命令面组件只有 Delete（CRM:53-54）；加节点规则**通用**（`AuthoringGraph.cs:322`）；
  写口覆盖 `int/enum/bool/float/string`，其中 `bool/float/string` 读回缺 getter（SSS §4.2）。
- **③ 真机验证过什么**：**本轮为零执行，一律「未验证」**。§5 的 1-6 名全是 **CANDIDATE**；
  7-10 名的「缺资产」结论基于**离线**的"无写入口"证据，同样未在真机复跑。

---

## 8. 本轮未找到的（写明搜过哪里、用什么命令）

1. **编辑器「界面控件组」类目的反射符号 / 注册表 tag 路径 / 建资源命令**：未找到。搜过
   `tools/editor-bridge/Adapter/*.cs`（无 UI setter）、`EditorBindingProfile.Generated.cs`（307 legacy 符号里
   无"控件组"可辨符号——符号全混淆，只能按 owner 类判，未发现 UI 类 owner）、
   `docs/research/beyondeditor-{frontend,backend,user-operations}/`（`Widget/UIControl/ControlGroup/HudElement` 命中 0 个控件组类，
   仅 menu-tree.json 有类目名）。
2. **AddComponent 命令**：未找到。命令表逐条清点（CRM §2）组件侧只有 Delete。
3. **"音效资产索引 / 特效资产"的可引用目录**：未找到"哪张表能列出可用的音效/特效 id"。
   （`prefab-catalog`/`catalog` 是实体/元件目录，未见音效/特效资产目录。）
4. **任何"文本直投玩家"的节点**：不存在。全 810 定义名按 `字幕/旁白/对话/飘字/弹窗/公告/广播/通知/文字…`
   搜 → 只有 `801 设置玩家聊天文字权限`（权限开关，非显示）与 `200039 通知服务器节点图`（图间信号）。
5. **`gameplan/README.md:132` 的措辞**：写"玩家可见的反馈仍只有日志打印"——**与 F5 §4:54 及本文冲突**。
   按证据取 **F5 §4 的口径**（日志打印 ≠ 玩家可见反馈），`README.md:132` 视为**松写法**，不据它下结论。

---

*本文件由 2026-10-10 会话离线整理；全程未连接桥、未发送任何请求、未触碰游戏/编辑器/存档。
所有引用行号为本次 checkout 实测。凡只到"离线可行"的条目一律标 CANDIDATE，未写"已验证"。*
