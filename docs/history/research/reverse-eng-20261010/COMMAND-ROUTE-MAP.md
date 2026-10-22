> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #10 — 编辑器前端命令路由全表（前端命令 → 游戏侧落点 → 本工程是否调用）

**产出日期**：2026-10-10
**数据来源（只读）**：`docs/research/beyondeditor-backend/db/backend.db`，表 `command_route`（38 行），
辅以 `dispatch_table` / `dispatch_entry` / `service_route` / `backend_gap` / `evidence` / `source`。
**调用面扫描**：`tools/` 全目录（`grep -rI`，含 `tools/editor-bridge`、`tools/game-executor`）。
**本文件只读不写：** 除本文件外未修改任何东西；未接触 bridge / 游戏 / 编辑器；未发任何报文。

---

## 0. 一句话结论

- 表里是 **38 条**前端命令。其中 **32 条**在游戏侧有确定落点（`route_status='matched'`，
  且这 32 条的哈希与 `dispatch_entry` 的 32 个不同哈希一一对应），落在两个**完整解码**的分发表里；
  **6 条**无游戏侧落点（`disproved` × 1 / `undecidable` × 5）。
- 本工程 `tools/` 里**真正发出**命令的调用点共 **10 处**，覆盖 **7 条**命令（外加 1 条不在 38 表内的
  `DoExportClientScript`）。其余命令本工程从未发送。
- **transform 问题：CONFIRMED。** 表里**没有任何一条命令**能给一个**已存在**的对象设置
  位置 / 旋转 / 缩放。见 §4。

---

## 1. 方法与口径

| 项 | 值 |
|---|---|
| 读的表 | `command_route`（38 行，`id` 1–38） |
| db 里 `command_route` 的物理位置 | `docs/research/beyondeditor-backend/db/backend.db`（20,058,112 B，只读打开 `mode=ro`） |
| 命令哈希来源 | 命令名的 **FNV-1a 32**；32 条 matched 命令的哈希全部在 `dispatch_entry` 的 32 个不同哈希中出现 |
| 分发表 | `dispatch_table` id=1 `0x914de40`（4775 B，33 条比较，`complete=1`，evidence E1）；id=2 `0x768d170`（1803 B，8 条比较，`complete=1`，evidence E2） |
| 调用面扫描命令 | `grep -rIl --exclude-dir=.git --exclude-dir=__pycache__ "<命令名>" tools/`（38 个名字各跑一次） |
| "是否调用"的判定 | **只要把该命令名送进 Producer 的派发方法 `Ikci0qkvMZX(service, command, callback, params)`，或直接反射调用实现该命令的原生方法，就算"调用"**；仅在注释 / 文档 / 清单数据里出现不算 |

> **重要区分（否则会高估使用面）**：`tools/authoring/build_closeout_inventory.py` 命中了**全部 38 个名字**，
> 但它是"证据清单生成器"（文件头 docstring：`Never imports or calls live tools.`，
> `build_closeout_inventory.py:1`），那些名字是**归属表数据**（`OPERATION_DISPATCH` /
> `USER_OP_BACKEND_COMMAND`，`build_closeout_inventory.py:292`、`:156`），不是调用。本表一律**不计**。

---

## 2. 全表：38 条命令

字段含义：`service` = 前端声明的服务名（`None` = 表里未记）；`status` = `route_status`；
`class` = db 里的 `classification`；"本工程调用?"一列按 §1 口径。

### 2.1 主命令表（`dispatch_table` id=1，`0x914de40`，33 条比较 / 25 个不同命令）

| id | command | service | status | class | 做什么（handler_summary 压缩） | 本工程调用? |
|---:|---|---|---|---|---|---|
| 1 | `AddInstructionGraphForEditObj` | beyondEditObjService | matched | 节点图类 | 第2参查实体→取组件3→装配节点图→通知管理器重算 | **USED** → `EditorAdapter.cs:654`、`AuthoringGraph.cs:317` |
| 2 | `AddInstructionGraphForPrefab` | None | matched | 节点图类 | 另一套注册表 `[global+0xa3c0]` 取内层 id，复用 0x914cd90 | 否（前端 44 条操作名里也没有） |
| 3 | `ApplyPrefabInstanceChange` | None | matched | 变更应用类（语义未定） | 1 个 int → 查 Prefab 实例 → `0xcb5cad0(实例,1,1)`（9605 B **未展开**）→ 后处理 | 否 |
| 4 | `DeleteComponentForEditObj` | beyondEditObjService | matched | 删除类 | 查实体→取组件→注销→收尾 | 否 |
| 5 | `DeleteComponentForPrefab` | beyondEditObjService | matched | 删除类 | 查 Prefab→尾跳 0x914ccd0（与 id4 同实现） | 否 |
| 6 | `DeleteEditObj` | beyondEditObjService | matched | 删除类 | 0x914d6a0 取记录→类型过滤→虚调用前置条件→执行删除→通知 | 否（**能力**经前端方法另路触达，见 §3 注） |
| 7 | `DeletePrefab` | beyondEditObjService | matched | 删除类 | 容器取记录→从列表移除（引用计数清零）→与 id6 同收尾 | 否 |
| 8 | `FocusBeyondTileMap` | beyondEditObjService | matched | 聚焦类 | 单例容器取目标→包委托→通用面板调度 0x6f408c0(面板0,页签-1) | 否 |
| 9 | `FocusCharacter` | beyondEditObjService | matched | 聚焦类（**参数被丢弃**） | 79 B；常态**丢弃传入 id**，只调 0x6f408c0(3,0,0)；另一路径进 async 状态机 | 否 |
| 10 | `FocusDropGather` | beyondEditObjService | matched | 聚焦类·闭包异步 | 存 id→造闭包→jmp 0x6f408c0(面板3,子页签4,闭包) | 否 |
| 11 | `FocusEditObj` | beyondEditObjService | matched | 聚焦类 | id→查实体字典→交给会话（服务定位器→0xc0414e0） | 否（唯一有实测旁证的一条，见 `docs/gameplay/FRONTEND-BACKEND-TRACE-20260920.md`） |
| 12 | `FocusEsp` | beyondEditObjService | matched | 聚焦类·闭包异步 | 与 id10 同模板，面板常量 (3,3) | 否 |
| 13 | `FocusLight` | beyondEditObjService | matched | 聚焦类·双模式 | mode==0 复用 FocusEditObj 路；mode==1 调 FocusPrefabInstance 处理器；其他切面板 | 否 |
| 14 | `FocusLocalBullet` | beyondEditObjService | matched | 聚焦类·闭包异步 | 与 id10 同模板，面板常量 (0,1) | 否 |
| 15 | `FocusPrefabInstance` | beyondEditObjService | matched | 聚焦类 | 与 FocusEditObj 完全同路，只换查 Prefab 表 | 否 |
| 16 | `FocusScreenshot` | beyondEditObjService | matched | 聚焦类·**6 float** | `float3 a, float3 b`（6 个 float→2 个 Vector3）；**处理器只切面板 1** | 否 |
| 17 | `JumpCombatSetting` | None | matched | 面板转发类 | 77 B 转发到 0x914cb10(this,3) 只切面板 3；参数语义 not_found | 否 |
| 18 | `ModifyEditObjName` | beyondEditObjService | matched | 改名类 | 查对象→校验→落地写入 | **USED** → `EditorAdapter.cs:569`、`EntityCrudProbe.cs:207`（直调原生方法） |
| 19 | `ModifyEditobjTag` | beyondEditObjService | matched | 标签类 | 共用 0x914dbc0：bool==0 增 / !=0 删（名字小写 o 是原样） | **USED** → `AuthorEntityTag.cs:127` |
| 20 | `ModifyFactionForEditObj` | beyondEditObjService | matched | 阵营类 | 共用 0x914c900：`mov dword ptr [rdi+0x30], esi` 直接写对象 **+0x30** | **USED** → `EntityFactionProbe.cs:152` |
| 21 | `ModifyFactionForPrefab` | beyondEditObjService | matched | 阵营类 | 查 Prefab→同一个 0x914c900 | 否 |
| 22 | `ModifyPrefabName` | beyondEditObjService | matched | 改名类 | 0x914d9c0→0x9b306d0 落地写入 | 否 |
| 23 | `ModifyPrefabTag` | beyondEditObjService | matched | 标签类 | 与 id19 共用 0x914dbc0 | 否 |
| 24 | `ModifySuite` | beyondEditObjService | matched | 真实业务处理器 | 1207 B：按 id 查 suite→构造→泛型虚方法解析→遍历成员逐项调用 | 否 |
| 25 | `RequestPrefabInstance` | beyondEditObjService | matched | 请求类 | 只读 idx0 → 0xcb5f330（Prefab 查找入口）；回执内容 not_found | **USED** → `EditorAdapter.cs:545`、`:594`、`:623` |

### 2.2 导出与调试表（`dispatch_table` id=2，`0x768d170`，8 条比较 / 7 个不同命令）

| id | command | service | status | class | 做什么 | 本工程调用? |
|---:|---|---|---|---|---|---|
| 26 | `DeleteDebugLog` | beyondExportService | matched | 调试日志类 | 取单例→尾跳 0x90a0910；**后两个 int 在两跳间被交换** | 否 |
| 27 | `DoExport` | beyondExportService | matched | 导入导出类 | 组 20 B 结构体→单例按 struct[0] switch（0x2710/0x2711）；公共尾 0xc436670 | **USED** → `EditorAdapter.cs:937` |
| 28 | `DoImport` | beyondExportService | matched | 导入导出类 | index 是**列表零基序号**（非场景 ID）→注册异步完成回调 | 否 |
| 29 | `ImportAllDebugLog` | beyondExportService | matched | 调试日志类 | **无参数**；执行完落共用失败尾声→**恒返回 false** | **USED** → `EditorAdapter.cs:515` |
| 30 | `ImportDebugLog` | beyondExportService | matched | 调试日志类 | 取单例→尾跳 0x90a2060→比较字符来自运行期赋值静态字段（字面值 not_found） | 否 |
| 31 | `ImportPerformanceReport` | beyondExportService | matched | 调试日志类 | 取单例→尾跳 0x85992d0 | 否 |
| 32 | `RefreshExistDebugLogReport` | beyondExportService | matched | 调试日志类 | **5 个参数（本表最多）**；执行完落共用失败尾声→**恒返回 false** | 否 |

### 2.3 无游戏侧落点（6 条）

| id | command | service | status | 结论 | 本工程调用? |
|---:|---|---|---|---|---|
| 33 | `EndLoadAllDebugLog` | **wpfAudioService** | **disproved** | 是**编辑器本地**入站命令（`resolved/…zll1ASKPPG90rdIZ1Ymn.cs:85`），不是下行派发；无游戏侧落点 | 否（**IRRELEVANT**） |
| 34 | `PlayMusic` | beyondAudioService (`boGLyQBJv9p`) | undecidable | 下行事实已确证（编辑器发 1018），但游戏侧是否有处理器无法判定 | 否（**IRRELEVANT**） |
| 35 | `PlaySoundEffect` | beyondAudioService (`boGLyQBJv9p`) | undecidable | 同上 | 否（**IRRELEVANT**） |
| 36 | `ModifyPCGInstanceName` | beyondPCGInstanceService (`Is6hqU640RJ`) | undecidable | 下行已确证，游戏侧处理器无法判定 | 否（**IRRELEVANT**） |
| 37 | `DeletePCGInstance` | beyondPCGInstanceService (`Is6hqU640RJ`) | undecidable | 同上 | 否（**IRRELEVANT**） |
| 38 | `FocusPCGInstance` | beyondPCGInstanceService (`Is6hqU640RJ`) | undecidable | 同上 | 否（**IRRELEVANT**） |

---

## 3. 分类汇总（USED / AVAILABLE-BUT-UNUSED / IRRELEVANT）

口径：
- **USED**：`tools/` 里至少有一处调用点把该命令名送进派发器 `Ikci0qkvMZX`，或直接调用了实现该命令的原生方法。
- **AVAILABLE-BUT-UNUSED**：游戏侧落点确凿（`matched`），能力可用，但本工程代码从未发送过它。
- **IRRELEVANT**：无游戏侧落点（`disproved` / `undecidable`），或属于本工程不驱动的服务通道。

| 分类 | 数量 | 命令 |
|---|---:|---|
| **USED** | **7** | `AddInstructionGraphForEditObj`、`ModifyEditObjName`、`ModifyEditobjTag`、`ModifyFactionForEditObj`、`RequestPrefabInstance`、`DoExport`、`ImportAllDebugLog` |
| **AVAILABLE-BUT-UNUSED** | **25** | `AddInstructionGraphForPrefab`、`ApplyPrefabInstanceChange`、`DeleteComponentForEditObj`、`DeleteComponentForPrefab`、`DeleteEditObj`、`DeletePrefab`、`FocusBeyondTileMap`、`FocusCharacter`、`FocusDropGather`、`FocusEditObj`、`FocusEsp`、`FocusLight`、`FocusLocalBullet`、`FocusPrefabInstance`、`FocusScreenshot`、`JumpCombatSetting`、`ModifyFactionForPrefab`、`ModifyPrefabName`、`ModifyPrefabTag`、`ModifySuite`、`DeleteDebugLog`、`DoImport`、`ImportDebugLog`、`ImportPerformanceReport`、`RefreshExistDebugLogReport` |
| **IRRELEVANT** | **6** | `EndLoadAllDebugLog`、`PlayMusic`、`PlaySoundEffect`、`ModifyPCGInstanceName`、`DeletePCGInstance`、`FocusPCGInstance` |
| 合计 | **38** | |

### 完整的调用点清单（`tools/` 内唯一权威，共 10 处）

派发器口径：`producer.GetType().GetMethod(B("Ikci0qkvMZX"), …).Invoke(producer, new object?[]{ service, command, callback, params })`。
`B(...)` 是把混淆名按绑定表还原（`EditorBindingProfile.Generated.cs:412` 记 `"Ikci0qkvMZX" → "RyJLgKYBqhL"`）。

| # | 文件:行 | service | command | 所在方法 |
|---:|---|---|---|---|
| 1 | `tools/editor-bridge/Adapter/AuthorEntityTag.cs:127` | beyondEditObjService | `ModifyEditobjTag` | 实体标签探针 |
| 2 | `tools/editor-bridge/Adapter/AuthoringGraph.cs:317` | beyondEditObjService | `AddInstructionGraphForEditObj` | 参数化建图 |
| 3 | `tools/editor-bridge/Adapter/ClientScriptExportProbe.cs:51` | beyondExportService | **`DoExportClientScript`**（**不在 38 表内**，见注） | `ExportClientScriptProbe` |
| 4 | `tools/editor-bridge/Adapter/EditorAdapter.cs:515` | beyondExportService | `ImportAllDebugLog` | `RequestDebugLogs()` |
| 5 | `tools/editor-bridge/Adapter/EditorAdapter.cs:545` | beyondEditObjService | `RequestPrefabInstance` | `RequestCalibrationPrefab()` |
| 6 | `tools/editor-bridge/Adapter/EditorAdapter.cs:594` | beyondEditObjService | `RequestPrefabInstance` | `RequestRealtimeLabPrefab()` |
| 7 | `tools/editor-bridge/Adapter/EditorAdapter.cs:623` | beyondEditObjService | `RequestPrefabInstance` | `RequestRealtimeTreePrefab()` |
| 8 | `tools/editor-bridge/Adapter/EditorAdapter.cs:654` | beyondEditObjService | `AddInstructionGraphForEditObj` | `BindOwnGraph()` |
| 9 | `tools/editor-bridge/Adapter/EditorAdapter.cs:937` | beyondExportService | `DoExport` | `ExportResource()` |
| 10 | `tools/editor-bridge/Adapter/EntityFactionProbe.cs:152` | beyondEditObjService | `ModifyFactionForEditObj` | 阵营探针 |

**另有 2 处"直接反射调用原生方法"（不走命令字符串派发，但调的是同一条命令的实现）：**
- `tools/editor-bridge/Adapter/EditorAdapter.cs:569` — `manager.GetType().GetMethod("ModifyEditObjName", …).Invoke(...)`（源注释：`Native implementation sends the RPC. Never set the local name field.`）→ 计入 USED。
- `tools/editor-bridge/Adapter/EntityCrudProbe.cs:207` — 同一原生方法，注释：`Same fixed native method as RenameRealtimeLabTree`。

**三条重要边界注：**
1. **`DoExportClientScript` 不在 38 表内。** 桥在 `ClientScriptExportProbe.cs:51` 把它当作
   `beyondExportService` 的命令名发出；`build_closeout_inventory.py:520-525` 也把它列为
   `native-candidate:beyondExportService:DoExportClientScript`。它在 `command_route` 里**没有行**
   （`OPERATION_DISPATCH` 里它的 hash 与 status 都是 `None`）。**⇒ 桥发出的命令名 ⊄ 已恢复的 38 条命令集**，
   与 id2 的 `AddInstructionGraphForPrefab` 是同一个方向的证据：**游戏侧接受的命令集 ⊋ 本表**。
   换句话说，"38"是**已定位落点的命令数**，不是"后端命令全集"。这给 transform 结论加了一条边界（见 §4.4）。
2. **`DeleteEditObj`（id6）未被按名调用**，但**删除能力**已由 `EntityCrudProbe.DeleteEntityCrudProbe()`
   经**前端 Resource 的混淆方法** `zgVKB6OS1MZ`（`EntityCrudProbe.cs:231`，方法 `DeleteEntityCrudProbe()` 见 `:217`）触达。
   命令名本身在 `tools/` 里只出现在 `CommandProbe.cs:22` 的**注释**里（原文："No recovered command name
   -- not DoExport, not DeleteEditObj, not PlayMusic -- is ever placed in a request by this code."）。
   ⇒ 按"是否发送该命令名"的口径它算 AVAILABLE-BUT-UNUSED；按"能力是否被用过"它算已触达。**两条都要记。**
3. **`CommandProbe.cs` 不发送任何已知命令。** 它只发一个不可能存在的名字 `__miliastra_probe_unknown_command__`
   （`CommandProbe.cs:38`），用来测"派发路径通不通"，源码显式声明 `knownCommandsSent = 0`（`:142`）。
   ⇒ 该文件里的 `DoExport` / `DeleteEditObj` / `PlayMusic` / `ImportAllDebugLog` 全是**注释**，不是调用。

**`tools/game-executor/`：零命中。** 38 个命令名、7 个服务名、派发器 `Ikci0qkvMZX` 在该目录下
**一条都不出现**。game-executor 走的是另一条传输（原生 / pipe / scene_cli），不经过编辑器的命令通道。

**`tools/` 之外的旁证（不计入调用面，仅登记）：** `scripts/research/export_request_codec.py:56-57`
把 `beyondExportService` / `DoExport` 当作**自建 1018 报文编码器**的约定（模块 docstring N1 明说
"不是已证协议"，且 N6 明说"不得用于真实发送"）；它是纯离线编解码，不发报文。

---

## 4. transform 问题：**CONFIRMED**

> 命题（本工程既有信念）：**没有任何一条命令能给一个已存在的对象设置位置 / 旋转 / 缩放。**
> 结论：**CONFIRMED（确认）**。以下是读表得到的证据，而不是重复信念。

### 4.1 正面清点：38 条里没有一条是 transform 类

按 `command_route.classification` 与 `handler_summary` 逐条清点，语义只有这几类：
**节点图装配**（id1、2）、**删除**（id4–7）、**聚焦/相机/面板**（id8–17）、
**改名**（id18、22）、**标签**（id19、23）、**阵营**（id20、21）、**Suite**（id24）、
**请求/应用**（id25、3）、**导入导出**（id27、28）、**调试日志**（id26、29–32）、
**音频/PCG（无落点）**（id33–38）。
**没有任何一类的名字或语义是 position / rotation / scale / transform / move / place。**

### 4.2 唯一的"写回已存在对象"的三处，写的都不是几何

全表里能"改一个已存在对象字段"的命令只有三条，且都读到了确切的写入偏移：

| 命令 | 写入证据 | 写的是什么 |
|---|---|---|
| `ModifyFactionForEditObj` / `ModifyFactionForPrefab`（id20/21） | `mov dword ptr [rdi+0x30], esi`（evidence E22；两条共用 0x914c900） | **1 个 int32**，阵营值 → 对象 `+0x30` |
| `ModifyEditobjTag` / `ModifyPrefabTag`（id19/23） | 共用 0x914dbc0：`List<int>.Add`（含 `inc [r14+0x1c]` 版本号）/ 移除路径 | **标签数组**的增删 |
| `ModifyEditObjName` / `ModifyPrefabName`（id18/22） | 落到写入函数（0xe945c30 / 0x9b306d0） | **一个字符串** |

三处都没有 float、没有 Vector3、没有 6/9 个标量的参数形状；写回偏移 `+0x30` 是标量 int。

### 4.3 唯二带几何形状的参数，都不是"改对象变换"

- `FocusScreenshot`（id16）是全表**唯一**收 float 的命令：`param_shape=(float × 6，重组成两个 Vector3)`。
  但它的处理器 `0x914d560(this, float3 a, float3 b)` **只做** `0x914cb10(this,1)` 切面板 +
  `0x6f408c0(面板1, 子页签-1)`（evidence E18）——这是**截图相机构图**，不写任何对象的变换。
  并且 db 特意标注：**"参数形状与其余 `Focus*` 完全不同，不能套用『Focus 都是单个 int』的说法"**（id16 notes）。
- `ApplyPrefabInstanceChange`（id3）是全表**语义最不确定**的一条：`param_shape=(int32)`，
  处理器调 `0xcb5cad0(实例,1,1)`（9605 B，**未展开**）。但它**只带 1 个 int**（一个 id，没有任何几何载荷），
  且 `backend_gap` G8 明确把它列为"下游语义 not_found"。**一个 int 装不下位置/旋转/缩放。**

### 4.4 边界与反证检查（诚实列出，均不推翻结论）

1. **"38"不是全集。**（§3 注1）桥自己发的 `DoExportClientScript` 就不在表内，id2
   `AddInstructionGraphForPrefab` 也来自被混淆字符串表的还原而非前端 44 条操作名。
   所以严格陈述应为：**在"已定位落点的 38 条命令"范围内，无 transform**；
   "后端命令全集"未闭合。**但**：这两张分发表是**完整解码**的（`complete=1`，4775 B + 1803 B，
   E1/E2），32 个不同的命令哈希就是这两张表的**全部比较常量**；也就是说**在这两张表能接住的范围内，没有 transform**。
2. **全局钩子旁路。** `backend_gap` G7：`0x768d80e` 是前置全局钩子，标志位置位时整个命令分发被
   委托给 `0xd4af450`，**跳过哈希表**；置位条件未知。⇒ "哈希表里没有"**不严格等于**"运行时一定走不到"。
   `0xd4af450` 的内容本轮未读，是唯一的理论逃生口。要做实它需要读到那个函数体。
3. **hash-scan 方法边界。** G17：本方法只能发现**字面 imm32 比较**。若后端对某条命令改用间接方式
   （运行期构造表索引），看不见。目前无任何证据表明存在这种命令，也不能证明不存在。
4. **这不是"不能摆东西"。** 本工程确实能定位实体——但走的是**另外两条路**，与命令表无关：
   `tools/gameplan/placement.py:9-14` 记 `entity.transform is entirely missing`，所以布局靠
   **在 create 时给坐标**（`entity.create` 自带位置）；关卡内的既有实体位置则落在
   **`.gil` 关卡文件的字段**里。命令表里没有 transform，与"项目仍能摆布局"并不矛盾——
   两者是**不同的机制**。

### 4.5 反证尝试（找过、没找到）

- 在整个 db 的**所有**文本列里搜过 `Position / Transform / Rotat / Scale / Move / Place / Location / Vector / Offset / Translate / Matrix / Euler`：
  - `command_route` 里只命中 4 行：id16（`param_shape` 里的 `Vector3`，见 §4.3）、id9（`handler_summary`
    里的 `MoveNext`，是 async 状态机方法名，不是几何）、id19/id23（`param_shape` 里的 `isRemove`——
    `...isReMove` 是**子串巧合**，它是"删除标签"的 bool 开关，与位移无关）。**没有一处是几何语义。**
  - `candidate_name` 里的 `Position / Scale / Location / Placement` 等 83 个命中**全部**是
    `bucket='corpus_identifier'` 或 `'editor_string_table'`，形态是 **.NET 属性访问器**（`get_Position`、
    `set_ScaleX`、`set_Placement`）或 **WPF / UI 标签**（`UI_BEYOND_ASSIST_EDITOR_SCALE_100`、
    `mouseMoveCommand`、`ToolTipsAutoFollowHorizontalOffset`）——**没有一个是命令形状，也没有一个落进两张分发表**。
- `dispatch_entry`（全部 41 条，含 9 条重复比较）逐条核对：**41 条的 `name` 全是已知命令名**，
  没有一条是 transform 形状；无未匹配的"可疑几何名"。

---

## 5. 证据索引

| 论断 | 证据 |
|---|---|
| 38 条命令、各字段 | `backend.db` → `command_route`（id 1–38） |
| 两张分发表完整解码 | `dispatch_table` id=1/2；`evidence` E1 `0x914de40` 4775 B complete、E2 `0x768d170` 1803 B complete |
| 32 个不同命令哈希 | `dispatch_entry`（41 行，32 个不同 hash）；与 `command_route` 的 32 条 matched 一一对应 |
| 阵营写 +0x30 | evidence E22（id20），E23（id21） |
| FocusScreenshot 参数形状 | evidence E18（id16）；id16 `notes` |
| ApplyPrefabInstanceChange 未展开 | evidence E5（id3）；`backend_gap` G8 |
| 无落点 6 条 | `command_route` id33–38；`backend_gap` G4 |
| 全局钩子旁路 | `backend_gap` G7 |
| 方法边界 | `backend_gap` G17 |
| 派发调用点 | `tools/editor-bridge/Adapter/*.cs`（§3 表 10 行 + 2 行直调） |
| `DoExportClientScript` 不在表内 | `ClientScriptExportProbe.cs:51`、`build_closeout_inventory.py:520-525`、`OPERATION_DISPATCH['DoExportClientScript']=(None,None,None,2)` |
| game-executor 零命中 | `tools/game-executor/` 全目录 grep（38 名 / 7 服务名 / `Ikci0qkvMZX` 均 0 命中） |
| 项目确实"没有 entity.transform" | `tools/gameplan/placement.py:9-14` |

---

## 6. 本轮的诚实边界

- 本文件全部为 **static（静态读表 + 静态 grep）**，无任何实测：未运行 bridge、未接触游戏/编辑器、未发报文。
  db 的 `backend_gap` G12 已声明"本轮证据全部是 static"，本文件继承该边界。
- "调用面"扫的是 **`tools/` 目录的工作树**（`grep -rI`）。若某调用点只在 `.runtime/` 下的未合入副本里，
  本文件看不见（本工程已知暗角：`.runtime` 里存着未合入的候选）。§1 的口径已写死为"`tools/` 内"。
- 分类使用三档口径，已在 §3 写死定义；`DeleteEditObj` 这类"命令名未发但能力已用"的边界情形，
  两条事实都记在 §3 注2，不替读者做单边结论。
