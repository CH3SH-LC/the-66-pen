> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# M6a 建关卡 & 改地形：官方能力 & 我们的可编程路径

**一句话结论**：**建关卡 = 能做**（走"直接改存档文件"路线，工程里已有可执行脚本 `register_level.py`，且历史上有一次"用户确认看到并打开"的实机确认；但它在当前 7.1 上被**版本门的 legacy `game` 半**挡住（`native-scene`/`editor` 今天都 ok:true——**2026-10-10 更正**，见 `docs/gameplan/VERSION-GUARD-DRIFT.md` §六），且会被游戏进程重写）。**改地形 = 未知**（本次新发现地形**就在 `.gil` 字段 7 里、可解码**，但**没有任何现有工具**读写它，也没有任何实机证据表明游戏会接受我们的写回）。两件事都**不是**"产品没有"。

---

## 1. 官方文档怎么说"新建关卡"

**没有"新建关卡"专章。** 218 章语料（201 graded + 17 顶层）里，`新建关卡`/`创建关卡` 只在**一章**出现：

- `docs/official-docs/chapters/mh3pgiraqkiu.json`（标题「关卡」）facts[1]：
  `"关卡实体在新建一个关卡后会自动创建在场景当中，并且在场景中会用一个特殊图标进行表示"`
  → 官方是从**后果**（新关卡会自动生成一个"关卡实体"）倒着讲的，**没有描述新建关卡本身的 UI 流程**。
  同一章给出关卡实体合同：纯逻辑实体、只有位置信息（无旋转/缩放）、生命周期随关卡初始化创建/关卡销毁而销毁、可接收物件/造物移除销毁事件的转发。

**能确定的相关 UI 事实**（均为 button-path / enum 类）：

| 事实 | 依据 |
|---|---|
| 系统菜单含「保存当前存档、**打开存档界面**、上传关卡、打开千星沙箱、退出存档」 | `EDITOR-SAVE-PLAYTEST.md:11`（转述 `mhn4bsi5lb58`） |
| 四个编辑模式枚举，**地形编辑是第一个**：地形编辑 / 实体摆放 / 元件库 / 战斗预设 | `chapters/mhn4bsi5lb58.json` facts[26][27] |
| 「另存为」**只用于资产，从不用于关卡**：单位（另存为元件）、节点图、界面控件组模板、战斗预设（另存为新内容）、元件库、实体摆放（覆盖保存元件） | 全语料 `另存为` 命中 6 章，逐条核对后**无一章把它用于关卡/存档** |

**官方在"关卡"粒度上唯一写明生命周期的是"发布"，不是"新建"**：`chapters/mh8clk9nmkua.json`（先行体验）——首次发布可勾选"先行体验"，再次发布转正式版本，正式版本不可回退。它是**发布状态机**，不含创建步骤。另一条组归属命中 `chapters/mhlb1vivioys.json`（负载优化）讲的是关卡内运行时优化，同样无关创建。

**边界（写清检索范围）**：以上是「在 218 章语料里搜 `新建关卡|创建关卡|关卡列表|另存为` 的全部命中」；官方是否在**未读的 3329 张配图**里画了新建关卡按钮，语料答不了（`SWEEP-READING-GUIDE.md §6`：图片一张没读）。

---

## 2. 官方文档怎么说"地形编辑"（确认 TERRAIN-EDITING.json，只写修正点）

`docs/official-docs/TERRAIN-EDITING.json` 的结论**全部确认成立**：地形编辑是官方**一等功能**（顶部页签第一个按钮 / 编辑模式枚举第 1 项），工具面完整（创建/笔刷四模式/高度标尺/分割/精准编辑/环境配置），默认 100x100 地形在 (0,-1.25,0)、单层地块 5x5、层高 2.5、7 种材质。

**本次新增/修正的 5 点**（TERRAIN-EDITING.json 里没有的）：

1. **「资产导出」线索追到了下一环**：`chapters/mhxbd59urbfu.json`（资产导入导出）facts[1] 原文：
   `"地形编辑 - 地形实体，物件实体，造物实体。"`
   → 地形**被官方明确列为可导出资产类型**；导出产物是 `.gia`（facts[3]），入口「系统菜单 - 资产导入导出工具」/「功能资产导出」，关内实体资产的用法是「将实体资产添加至关卡内」（facts[16]）。
2. **地形可入实体布设组**：`chapters/mhqmrlr6h58e.json` facts[3]
   `"在地形编辑页签，右键点击地形可在弹出菜单中将其添加至实体布设组。"`
3. **环境配置与地形同一个页签**：`chapters/mhdznsie9up8.json` facts[1]
   `"切换至地形编辑页签，可在左侧选择环境配置。点击【新建环境】并【确认创建】"`
4. **地形进入节点图语义只有"被读"**：`chapters/mh2pir0hat1s.json`（命中检测）facts[1] —— 命中区域可与**场景地形/水面**碰撞并发事件。本次全语料检索**未找到**任何"创建/修改地形"的节点或 API 名（见 §7 检索范围）。
5. **地形在关卡设置里有两项全局开关**：`mhn9vpia00qc`（关卡设置）——「减少地块缝隙概率」（7.0 新增，`mhs2w008wf14` facts[8]）与「寻路网格体烘焙」（建议改地形/摆静态物件后重新烘焙）。

官方**仍然不给**任何地形序列化字段（`CONTRACT-V08-TERRAIN.md §5.1` 结论不变）。但**我们在磁盘上找到了它**——见 §5。

---

## 3. 我们的工具能不能建关卡

| 候选路径 | 结果 | 证据（文件:行 或 命令输出） | 能否可编程完成 |
|---|---|---|---|
| **桥原生能力** | **未找到** | `docs/editor-catalog/COMMAND-CHANNEL.md:115-150`：已还原的 **23 条**命令名，无一条是关卡级。`docs/editor-catalog/INTERFACE-INVENTORY.md:155`：「全表 **2830** 条字符串中不存在 `DoSave`/`SaveProject`/`SaveArchive`」。`docs/gameplay/BACKEND-CREATE-SAVE-REACHABILITY-20260921.md`：7 个服务分发器全部解码，`beyondInstructionGraphService.create` 处理的是**图对象**，不是关卡 | ✗ |
| **CLI / MCP 入口** | **未找到** | `tools/authoring/INTERFACE-INVENTORY.md:19`：`level.manage`=**research**「尚无完整入口」。工程的 7.1 收口把 `level.manage` 的**验收面**定死为四项「**新建；打开指定关卡；另存为；空/无效关卡拒绝**」，而 `docs/research/7.1-experiment-plan/COVERAGE.md:13` 自记这一行是「**新建/打开/另存/重开待验**」——即**验收面有名字、实现没有**。`tools/game-executor/scene_cli.py:597` 子命令只有 `inspect / create / creature-create / create-batch / save / reopen-current`，**全部要求 `--level-id`（在已有关卡内操作）**。`build_readonly_profile.py --level-catalog` **只读**当前关卡目录（实测 15 条记录）。`plugins/miliastra`（MCP/Cordis 插件）自述 skeleton、backend `unavailable`、**发布 0 个工具** | ✗ |
| **直接改 .gil / 存档** | **找到** ✅ | `tools/beyond-save/register_level.py`（标题：*Register a new Miliastra level by editing the local save, reversibly*）+ `tools/beyond-save/gil_container.py`。已落盘证据：`docs/editor-catalog/DEMO-AND-REGISTRATION.md:375-396`（1073741829「MW_Demo_存档」写盘后**从磁盘重读复核通过**）；`docs/gameplay/REALTIME-INJECTION-20260920.md:7`（1073741832 实验档「**用户确认看到并打开**」） | **曾是**（见下方封禁） |
| **关卡模板复制** | **找到** ✅ | `register_level.py:135` —— 取目录里**最小的** `.gil` 作模板，`TEMPLATE_FIELDS = ((34,1),(41,1),(42,1))`，只覆盖 `IDENTITY_FIELDS = (1,2,39,40)` | ✓（同上封禁） |
| **GIA 导入导出** | **部分** | 官方侧：`.gia` 是官方导出格式（`mhxbd59urbfu`）。工具侧：`beyond-save` 不产 `.gia`；桥的 `import-verified-graph`/`import-tiled-route` **只导图**；`DoImport` **从未成功发送**（`INTERFACE-INVENTORY.md` §2.3） | ✗ |

**该路径的两个硬限制（必须一起读）**：

1. **被版本门挡住**：`register_level.py:40` 导入 `require_compatible`，`apply_registration()` 里 `require_compatible("all")`；`tools/compatibility/version_guard.py` 的 `"all"` **只由 legacy `game` 半拖红**——它的 `editor` 半（编辑器 DLL sha）**今天相符**，装机 DLL 就是被 pin 的那个 7.1 sha（**2026-10-10 更正**：旧文写 `"all"`「要求旧编辑器 DLL」是错的；且另有 `native-scene` 组件今天也 ok:true——见 `docs/gameplan/VERSION-GUARD-DRIFT.md` §六）（`docs/UPDATE-AUDIT-20260924.md:14`：beyond-save 三个写入口「**新版兼容未证明，真实写入应暂缓**」）。⇒ **当前状态下脚本会 fail-closed 拒绝写。**
2. **会被游戏重写**：`tools/beyond-save/.runtime` 证据（`.runtime/beyond-save/keep-registered.log`、`write-attribution.log`）显示 writer 是 **YuanShen**（`=> ATTRIBUTED to pid 113168 (YuanShen)`），它按自己的内存重写 profile，把我们的注册**抹掉**；`keep_registered.py` 就是为此写的循环重放器，其自述口径是「**注册在磁盘上活到下一次启动**（下次启动生效）」，**不是**"运行中的游戏即时看到"。

---

## 4. 我们的工具能不能改地形

| 候选路径 | 结果 | 证据 | 能否可编程完成 |
|---|---|---|---|
| **桥原生能力** | **未找到** | `grep -rn -i 'terrain\|PCG\|地形' tools/editor-bridge/Adapter/*.cs tools/game-executor/*.py` → **零命中**（49 个 Adapter `.cs` + 45 个 executor `.py` 全在检索范围内）| ✗（此范围） |
| **PCG 服务命令** | **部分（只有改名/删除/聚焦）** | `INTERFACE-INVENTORY.md:152`：`beyondPCGInstanceService` = `ModifyPCGInstanceName` / `DeletePCGInstance` / `FocusPCGInstance`。`docs/research/beyondeditor-user-operations/07-后端能力反查-界面上没有的.md:30-42`：三条**派发点确证存在**，但**编辑器界面入口本轮没找到**（`undecidable`）。`terrain.pcg` 组在 `tools/authoring/build_closeout_inventory.py:362-365` 被标 `'unused so far'` | ✗ |
| **直接改 .gil（本次新发现）** | **结构找到，工具没有** | 本次实测：`1073741828.gil` 的**字段 7** 解出 = 地形列表（见 §5）。同一字段在三个真实关卡里**逐字节相同**（sha256 `1c9d2287d86fbd98…`，3642 字节）⇒ 它就是**默认地形**。**但全仓检索 `.runtime` 之外的 `tools/`+`docs/` 无任何代码读写字段 7**（唯一提到 `id=7 → List<Terrain> Terrains` 的是第三方逆向文档 `CONTRACT-V08-TERRAIN.md:314`，自述"无实现"） | **未知**（无工具、无 7.1 语义复核、无实机） |
| **节点图 / 官方节点** | **本次检索范围内未找到** | 全 218 章搜 `地形` 命中 20 条事实，**全部是属性引用**（贴地摆放、基于地形生成、命中检测、环境配置），**没有**一条是"创建/修改地形"的节点名（见 §7） | ✗（此范围） |
| ↑ **一处无法归因的反证线索（不采信、也不丢弃）** | **存疑** | `.runtime/_terrain_index.txt` 把 `mhaqt9rgqv4u`（投射运动器）、`mhf9gq9ssw9e`/`mhb09x012qu8`（执行节点）**打成「[地形]」「[地形、高度]」**。但**我无法从这三章的 `facts[]`、`.txt` 或 `.html` 里复现这个标签**（`grep -o '地形[^<]\{0,20\}'` 三份 html 全部零命中），其来源不明。`mhb09x012qu8` 自称有 **19 张节点参数表**（本工程只转录了选样，`SWEEP-READING-GUIDE.md §5`）⇒ **既不能据此说"有地形节点"，也不能说"没有"** | 未知 |
| **GIA / 资产导出** | **官方有，工具侧未接** | 官方：`mhxbd59urbfu` facts[1] 地形实体可导出为 `.gia`。工具侧：GIA 路径目前**只导图**（`DEMO-AND-REGISTRATION.md:197-226`，导出的是 29 节点的图）；地形 GIA 从未跑过 | ✗ |
| **场景生成模板** | **官方工具，但不是地形** | `mhjk3t996oiy` facts[15]：`"是否基于地形生成：只有岩石层拥有。控制岩石层是否基于场景地形生成。"` → 它**读**地形，生成的是**实体** | ✗ |

---

## 5. 关卡在磁盘上的形态（新建关卡等价于造出什么）

路径：`%USERPROFILE%\AppData\LocalLow\miHoYo\原神\BeyondLocal\<UID>\`


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**容器框架**（`gil_container.py` 头部注释，对 4 个 `.gil` + 1 个 `.gip` 逐字节验证）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


关卡 id 从 `0x40000000` 起编号；**文件名才是 id 的权威来源**（字段 1 只在部分文件出现）。档案关卡**按「页签」组织**，藏在 `f1 > f2 > f4` 两层嵌套里，页签持有 `(group=1600, level_id)` 对——`1600` 在反编译里对上枚举成员 **`SaveArchive = 1600`**（`DEMO-AND-REGISTRATION.md:367-370`）。

**一个新建的关卡 = 造出两样东西**：
1. 一个 `<newId>.gil`。**占位/空关卡只有 66-79 字节**，字段号恰为 `1,2,34,39,40,41,42`（id / 名称 / 常量 1 / 作者 uid / 时间戳 / 常量 1 / 常量 1）。
2. 在 `.gip` 里加**两条**entry：**平铺列表（顶层 f2）*和* 页签（f1>f2>f4）**。只写平铺列表对按页签渲染的编辑器来说是**半个注册**（`DEMO-AND-REGISTRATION.md:352-373`）。

**真实关卡 `.gil` 里有什么**（本次实测 `1073741825/826/827/828/829/830`，只读 fixtures）：

| 文件 | 大小 | 顶层字段 |
|---|---|---|
| 1073741826/827/830（空占位） | 79/78/66 B | 1,2,34,39,40,41,(42) |
| 1073741825 / 828 / 829（真实关卡） | 61KB / 21KB / 16KB | 2..49（含 3,4,5,6,**7**,8,9,10,**11**,12,14…46,48,49） |

**地形就在字段 7 里（本次新解出）**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- 400 = **20×20**，地块坐标 `f1 = (x<<16) | y`，**x/y 各取遍 100..119**。
- 这与官方口径**完全吻合**：默认地形 100×100、单层地块 5×5、层高 2.5 ⇒ 20×20 格；且这解释了 `CONTRACT-V08-TERRAIN.md:210` 当年只能**推导**的「约 400 格」——**它是对的**。
- 三个真实关卡该字段**逐字节相同**：它们都还是**默认地形，没人改过**。
- **独立复核（另一批文件）**：对 `.runtime/formal-save-backups/`（9 个 `.gil`，关卡 1073741842，2026-10-08，含被最近实体创建/参数实验改过的快照）重跑同一解码，**8 个的字段 7 仍是同一个默认 sha `1c9d2287d86fbd98…`**（第 9 个是 90 字节占位、根本没有字段 7）。⇒ 即便经过一整轮实体创建实验，**地形从未被任何工具改动过**，与 §4 的"无工具读写字段 7"互相印证。

字段 11 随关卡变化（336B vs 444B），内含中文串（`初始玩家阵…` 等），是第三方文档推测的 `LevelSettings`（`CONTRACT-V08-TERRAIN.md:315`）。

---

## 6. 结论 + 代价估计

| 目标 | 判定 | 推荐路径 | 代价档 |
|---|---|---|---|
| **建关卡** | **能做**（路线已存在并曾落盘，但当前被封） | 文件注册路线：`register_level.py` 的 `.gil` + `.gip`（平铺+页签）双写；用 `keep_registered.py` 对抗游戏重写 | **中改**：① **先真机写盘 + 独立读回，再**重新基线 7.1 / 或以磁盘版本身份重做 version_guard 的 `"all"` 判定（**单独重基线不可辩护**，`VERSION-GUARD-DRIFT.md` §五）；② 7.1 字段语义复核（占位 `.gil` 的 66-79 字节形状是否仍是 7.1 形状）；③ 持久化编排（重放 + 重启生效）；④ 需要一次实机确认（用户重开游戏后能看到/打开新关卡） |
| **改地形** | **未知** | 原理路线已看到：`gil_container` 的**逐字节回环**解析器 + **字段 7**。但**工具不存在** | **新开工具**：① 写一个 field-7 地形读写器（编码器已具备，`encode_fields` 逐字节回环）；② 解决坐标系/材质/层高的语义（材质编号、`f3` 含义未知）；③ 与关卡保存链配合（游戏会重写）；④ 必须实机验证游戏是否接受 |

**一句话**：M6a 的**第一坎（能不能建关卡）答案是"能做"**，只是当前实现落后一个版本；**第二坎（能不能改地形）仍未知**，但从"完全没有路径"升级为"**路径在磁盘格式里已看到、缺工具与验证**"。

---

## 7. 本次未找到的（写明搜过哪里、用什么命令）

| 声称 | 检索范围（**都不是"不存在"**） |
|---|---|
| 「没有任何关卡级命令」 | 范围 = `COMMAND-CHANNEL.md` 的 **23 条**已还原命令名 + `INTERFACE-INVENTORY.md` 的 **2830 条**字符串表 + `BACKEND-CREATE-SAVE-REACHABILITY-20260921.md` 的 **7 个**服务分发器。**不是**"2830 条是全程序字符串"；`DEMO-AND-REGISTRATION.md:418-421` 已记录**命令面比 23 条更大**（又列出 7 条），说明"枚举不全"是已知事实 |
| 「桥/executor 里没有地形能力」 | 范围 = `tools/editor-bridge/Adapter/*.cs`（49 文件）+ `tools/game-executor/*.py`（45 文件）全文 `-i 'terrain\|PCG\|地形'`。**未**覆盖 `tools/editor-catalog/` 反编译产物与 `.runtime` 内的历史转储 |
| 「官方没有地形创建节点」 | 范围 = `docs/official-docs/chapters/*.json` 全部 facts 的 `地形` 命中（20 条）。**未**覆盖 17 个顶层单章记录以外的图（3329 张图零读）、**未**覆盖 `SWEEP-NUMERIC-AND-NODES.json` 的 1292 个节点块（只转录了 796 条选样）。**另有一条未解线索**：`.runtime/_terrain_index.txt` 给 3 个**节点章**打了 `[地形]` 标签，但我**从这三章的 facts/txt/html 里都复现不出该标签**（provenance 不明）；按本工程「目录是索引，不是被索引物的状态」的纪律（`SWEEP-READING-GUIDE.md §4`）**不采信**，同时因节点参数表只有选样而**不排除** |
| 「`.runtime` 里没有地形调查」 | 本次对 `.runtime/verification`、`beyond-save`、`research-sources`、`editor-catalog`、`mvp`、`authoring`、`game-executor`、`backend`、`bridge` 九个子树做了有界文本扫描，但 `.runtime` 全树过大，**两次全树扫描均超时（exit 124）**——所以这条**没有完成**，不能下"没有"的结论。已知根目录另有 `.runtime/_terrain_index.txt`（官方章节目录，非新证据）与 `.runtime/formal-save-backups/`（未展开） |
| 「`另存为` 不用于关卡」 | 范围 = 218 章语料，命中 6 章，逐条读 facts 确认均为资产。**不是**"UI 上没有关卡另存" |
| 「没有工具读写 field 7」 | 范围 = `tools/`+`docs/`（`grep -rn '地形01\|field 7\|field7\|Terrains\|地形列表'`）。补充：`.runtime/research-sources/file-formats/` 的第三方 proto 只到 `// id = 7, type = LENGTH`（`CONTRACT-V08-TERRAIN.md:314`），**无 message Terrain 实现**（同文 §5.2 实测零命中） |
| **本次未做的** | 未启动/连接原神或编辑器；未提权；未读镜像内存；未写任何存档。§5 的 `.gil` 解码读的是**仓内 fixtures 副本**（`.runtime/beyond-save/fixtures/`），非活存档 |

**特别声明**：「在某个枚举范围里未找到」**不等于**"产品没有"——本工程已在此类断言上栽过多次（`SWEEP-READING-GUIDE.md §7.1` 的 `combat.ports`/`graph.import` 就是"打标失败被误读成无覆盖"）。本节所有"未找到"均已写明范围。

---

## 8. 三层标注（严格分开）

**文档写了什么（官方语料，静态）**
- 「新建关卡」无专章；只有 `mh3pgiraqkiu` 一句"新建关卡后自动创建关卡实体"，以及系统菜单里的「打开存档界面」。
- 地形编辑是**一等功能**，工具面完整（`TERRAIN-EDITING.json` 确认）；地形是**可导出资产**（`mhxbd59urbfu`）；地形可入实体布设组；环境配置同页签。
- 官方**不给**任何地形序列化格式；也不给"如何新建关卡"的操作步骤（`whatThisChapterDoesNotSay` 明写列不出字段清单，只在配图里）。

**工具/源码能做什么（静态 + 工程产物）**
- 桥有 **23 条**具名命令 + 7 个服务分发器，**无一声称建关卡**；PCG 只有改名/删除/聚焦三条且界面入口未找到。
- `scene_cli.py` 只能在**已有关卡内**增删实体/保存；`--level-catalog` **只读**。
- **能做**：`register_level.py` + `gil_container.py` 用**逐字节回环**的 protobuf 读写，造出 `<id>.gil` 并双写 `.gip`；`keep_registered.py` 对抗游戏重写。**当前被 7.1 version_guard 的 legacy `game` 半挡住（`editor`/`native-scene` 今天绿）。**
- **本次新解出**：`.gil` **字段 7 = 地形**（地形 id/名称/400 个 20×20 地块，坐标 `(x<<16)|y`，x/y=100..119），且三个真实关卡该字段逐字节相同 = 默认地形。**无任何工具读写它。**

**真机验证过什么（运行时）**
- **本次为零执行——一律「未验证」。** 本路未启动、未连接、未提权、未写盘。
- 历史记录（**非本次**，来自仓内文档，其可信度以该文档自述为准）：`DEMO-AND-REGISTRATION.md` 记 1073741829 落盘并**从磁盘重读复核**；`REALTIME-INJECTION-20260920.md` 记 1073741832 **经用户确认看到并打开**。**地形侧：无任何实机记录，历史与本次都是零。**
