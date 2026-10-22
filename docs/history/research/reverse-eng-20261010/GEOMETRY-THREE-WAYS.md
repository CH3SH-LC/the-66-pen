> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 实体几何三路对照：`.gil` 离线 / 原生探针 / 编辑器模型

> 建立日期：2026-10-10。位置：`docs/research/reverse-eng-20261010/GEOMETRY-THREE-WAYS.md`。
> 任务：把**三条读几何的路**摆在一起，各自**到底能给出什么**（position? rotation? scale?
> 还是只是一个不透明的三元组），编辑器侧那套混淆符号的**确切名单**，以及**有没有任意两路
> 在同一个实体上对得上**。
>
> 口径沿用 `docs/PROGRESS-BY-FUNCTION.md`：`真机验证过` / `只离线验证过` / `未验证`。
> **本文所有"同意/不同意"都附真实数字**；**没有真实比较的地方一律写"无法比较"**，不写成一致。
>
> 全程只读：没有连桥、没有发 native/graph 请求、没有启动游戏或编辑器、没有写任何
> `C:\Users\PUBLIC_USER\AppData\LocalLow\miHoYo\` 下的文件。

---

## 0. 一句话结论

| 路 | 载体 | position | rotation | scale | 形态 |
|---|---|---|---|---|---|
| **A. 离线 `.gil`** | `tools/beyond-save/entity_geometry.py` | ✅ 有（field 1） | ⚠️ 有（field 2，只见过单值） | ✅ 有（field 3） | **三个 float32 分量，显式可解** |
| **B. 原生探针** | `tools/game-executor/native/*` | ❌ **读=null** / 写=有 | ❌ 读=null / 写=有 | ❌ 读=null / 写=有 | **读：无几何；写：不透明入参三元组** |
| **C. 编辑器模型** | `Adapter/SceneCatalog.cs` | ⚠️ 三个向量，**角色未证明** | ⚠️ 同上 | ⚠️ 同上 | **不透明三元组 + 分量，且是真机读到全零的缓存** |

**能对上的一对：B（建实体的入参）× A（落盘读回）。** 已两次实测一致（本文 §5.1、§5.2）。
**已经证明对不上的一对：C（编辑器缓存）× A（`.gil`）——同一个实体，C 报全零、A 报 z≈2.911。**（§5.3）
**B（读）× 任何**：无法比较——原生快照根本不读几何（§5.4）。

---

## 1. A 路：离线 `.gil`（`tools/beyond-save/entity_geometry.py`）

**它读什么**：一个关卡 `.gil` 的 protobuf 载荷，逐字节解，**不猜 schema**。

- 实体表 = 根 field 5；每条记录是 `field 1` 包起来的消息（`entity_geometry.py:14-24`）。
- 变换固定在一个地址上：
  `root field 5 > entry field 6 > wrapper kind 1 > wrapper field 11`（`entity_geometry.py:34-38`）。
  常量写在 `entity_geometry.py:130-133`（`TRANSFORM_GROUP=6 / TRANSFORM_KIND=1 / TRANSFORM_PAYLOAD_FIELD=11`）。
- 该载荷是**三个 length-delimited 子消息（field 1/2/3）+ 一个尾随 varint field 501**（`entity_geometry.py:40-45`）。
  解码器 `_make_transform` 见 `entity_geometry.py:375-384`；子消息按 float32 读见 `_make_vec` `:342-350`。

**三个向量的角色是"解释"，不是"实证"**（`entity_geometry.py:46-52`）：

| 子字段 | 读作 | 依据（作者自述） |
|---|---|---|
| field 1 → `position` | 自由 3-float 向量 | 无更强的；未触碰实体也会带 |
| field 2 → `rotation` | **只见过单个** degree 样值（20.0 / 45.0） | 出现在"像被旋转过"的记录上 |
| field 3 → `scale` | 3-float，未触碰实体恒 `(1,1,1)` | 恒等缩放 |

代码**刻意保留位置形态**（`vectors[1/2/3]`）当唯一真相，`position/rotation/scale` 只是
**文档化别名**（`entity_geometry.py:262-273`）。proto3 省略零值 ⇒ 分量缺省按 0 补，
`Vec.triple()` 补 0（`entity_geometry.py:228-250`，与 `.claude` memory `gil-level-file-is-decodable` 一致）。

**A 路能给**：每个实体的 `(x,y,z)` 位置、`(x,y,z)` 缩放、以及一个**常常只含单分量**的旋转。
**A 路不能给**：任何 `kind`/payload 字段号的**名字**（`entity_geometry.py:87-107` 明确列为负结论）；
旋转的**单位/约定**（"degree 样"是猜的）；除 group6/kind1 之外 30 余个 `(group,kind)` 的**含义**。
**A 路已证**：`test_entity_geometry.py` 通过；真实字节偏移写在模块 doc `:59-71`（文件 `1073741842.gil`，
size 28383，field 5 键字节在 file 0x04E4）。

---

## 2. B 路：原生探针（`tools/game-executor/native/*`）

**B 路是唯一摸过**运行中 `YuanShen.exe` **进程的路**。它分两半，**两半能力完全不同**：

### 2.1 读：**不读几何**（这是负结论，不是待办）

实体快照结构 `GameEntitySnapshot` 里确实有 `float position[3]`，但紧跟着的注释是硬话：

> `tools/game-executor/native/game_context_snapshot.h:81`
> `float position[3]; // GE_POSITION_READ is never set: no proven position offset.`

`GE_POSITION_READ = 16`（`game_context_snapshot.h:59`），**从不置位**。真机快照证实：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`79 = 1|2|4|8|64`——**没有 16**。所以 B 路读取只能给 `owner/config/context` 指针、
`dictionaryKey/id/configId`。**它给不出位置的任何一个分量**（rotation/scale 更没有独立字段）。
`HANDOFF-CREATE-SAVE-20260922.md` §4.2 原话："快照不读取实体变换，不能把保留的零值当位置证据"。

> 唯一被 B 路**读到**的几何是**关卡原点** `GameContextSnapshot.origin[3]`（`game_context_snapshot.h:95`），
> 由 `GS_ORIGIN_READ` 置位（真机 flags 含 `origin_read`）。本机 334 份快照的 `origin` **全部是 `[0,0,0]`**。

### 2.2 写：几何是**建实体的入参**

原生创建走 `place_builtin`（`tools/game-executor/native/scene_calls.cpp:11-50`），入参结构
`PlacementInput{ template_id, world_position, context_origin, rotation_degrees, scale }`
（`scene_calls.h:30-36`）。原生侧**唯一**的几何动作在这里，且是**输入**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**角色顺序在 B 路是实证过的**：`scene_calls.h:14` 写明"the vectors are indirect 12-byte values,
**in position/rotation/scale order**"（来自 7.1 真实拖放调用方 `d31aae6`）。校验：三个向量必须
有限、scale 三分量 > 0（`scene_calls.cpp:14-18`；`game_executor.cpp:47-49`）。

**B 路能给（写）**：`world_position`(3) / `context_origin`(3) / `rotation_degrees`(3) / `scale`(3)，
外加 `local_position = world − origin` 这个被观测到的原生减法。**B 路不能给（读）**：现存实体的任何几何。

---

## 3. C 路：编辑器模型（`tools/editor-bridge/Adapter/SceneCatalog.cs`）

**C 路读的是** `BeyondEditor.exe` **进程内已 materialize 的注册表模型**，**纯字段读**——不调任何原生
方法、不发消息、不序列化（`SceneCatalog.cs:7-13`）。

### 3.1 确切混淆符号（"previous work" 说的 `SceneCatalog.cs:18,71-90`）

| 角色（代码里的名字） | 混淆符号 | 位置 |
|---|---|---|
| 变换字段 | **`hTjiSreIlqL`** | `SceneCatalog.cs:18`（`SceneTransformField`） |
| 向量 1 | **`maSidNtJUim`** | `SceneCatalog.cs:74` |
| 向量 2 | **`MtbidjteDd3`** | `SceneCatalog.cs:75` |
| 向量 3 | **`OStidFtjJdR`** | `SceneCatalog.cs:76` |
| 分量 x | **`xYKidoTpamf`** | `SceneCatalog.cs:81` |
| 分量 y | **`MDTidUcgOhj`** | `SceneCatalog.cs:82` |
| 分量 z | **`LSnidRDCRwE`** | `SceneCatalog.cs:83` |

同名映射另见 `docs/editor-catalog/INTERFACE-INVENTORY.md:484-485`，符号→绑定在
`Adapter/EditorBindingProfile.Generated.cs`（逐行如 `"hTjiSreIlqL","keVXiadWtLM"` `:546`、
`"maSidNtJUim","wC4LYjKf2kq"` `:562`）。

### 3.2 C 路自己声明的不确定性（很关键）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`source` 直接叫 **"editor-registry-transform-cache"**，`authoritative=false`。
`EntityTransform.cs:132-133` 把角色问题写成明文：
`vectorRolesVerified=false`，`roleMapping="unestablished: maSidNtJUim/MtbidjteDd3/OStidFtjJdR
order is not proven to be position/rotation/scale"`。非有限分量整体 `available=false`（`SceneCatalog.cs:86-89`）。

即：**C 路给的是三个不透明三元组**（每个 3 个 float32），**角色顺序 C 路自己都不认**。
与 B 路"写侧角色顺序是实证的"正好相反。

### 3.3 三条 C 路实现（都已读）

1. `Adapter/SceneCatalog.cs`——批量快照，经 **`op:"catalog"`** 的 `scene=` 字段下发
   （`EditorAdapter.cs:192`，`BridgeServer.cs:477`）。
2. `Adapter/EntityTransform.cs`——单实体 `inspect`（`:107-137`）。**注意：没有 `case "entity-transform"`
   注册在 `BridgeServer.cs`**，所以这个单实体 op **当前不可派发**；能派发的只有 `catalog`。
   其写侧是**命名阻塞** `TRANSFORM_NATIVE_SETTER_UNKNOWN`（`:36`、`:144`）——与 `CLAUDE.md` §五
   "前端 38 命令里没有 transform 命令"一致。
3. `Adapter/Geometry1017Fields.cs`——从一条**真实收到的 1017 资源增量包**里读**形状**（不是实体变换）：
   球/圆柱/盒的 `center/radius/height/direction`（`:131-142`），分量符号
   `h87BWJq8gBf/c4CBW4649Dt/OjvBWsJZe3l`（`:84`）。历次真机观察到的 tag-18 几何组件数为 0
   （`ComponentGeometryEvidence.cs:42`），所以这条目前**没给出过任何真实中心点**。

---

## 4. `.gil` 侧的字段名（A 路）——纯位置，无名字

对照用（本文对比只用到位置/缩放/模板号）：

| 代码常量 | 值 | 文件:行 |
|---|---|---|
| `ENTITY_TABLE_FIELD` | 5 | `entity_geometry.py:124` |
| `ENTRY_ID_FIELD` | 1 | `:125` |
| `ENTRY_TAG_FIELD` | 8 | `:127`（实测＝模板号，见 §5） |
| `TRANSFORM_GROUP/KIND/PAYLOAD_FIELD` | 6 / 1 / 11 | `:130-132` |
| `TRANSFORM_VECTOR_FIELDS` | `(1,2,3)` | `:133` |

---

## 5. 真实比较（附原始文件与数字）

> 复现脚本：`.runtime/scratch/geom-three-ways-dump.py`（只读；`python .runtime/scratch/geom-three-ways-dump.py`）。

### 5.1 **同意**：B 写侧入参 × A 落盘读回（非平凡值）

关卡 **1073741832**，实体 **1077936135**。

- **B（请求）** `.runtime/game-executor/scene-cli/20260922-190649-create-1a8a7cfc/target_config.h`：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  同 run 的 `after-context.json`：`origin = [0.0, 0.0, 0.0]`（⇒ `local == world`，无坐标系歧义）。
- **A（读回）** 当前 `…/1073741832/1073741832.gil`，`entity_geometry` 解出：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- **逐字段比值**：位置三轴、缩放三轴、模板号（`HR_TEMPLATE_ID=20001034` ↔ `tag=20001034`）
  **全部相等**（`1.7999999523162842` 就是 float32(1.79999995)）。
- 同表其余 5 台（`1077936136..140`）与 `docs/gameplay/MVP-LIVE-RUN-20260922.md:33-40` 的
  "设计 vs GIL 读回"逐项一致，起止于 `(9.5,0.4,-50)…(43,2.0,-50)`。

### 5.2 **同意**：B × A，当前会话（2026-10-10）

关卡 **1073741842**，实体 **1077936129**。

- **B（请求）** `.runtime/game-executor/scene-cli/20261010-003436-create-50c28b0f/target_config.h`：
  `HR_TEMPLATE_ID 20001965` / `HR_POSITION 0,0,0` / `HR_SCALE 1,1,1` / `HR_ROTATION 0,0,0`。
  该 run `result.json`：`"entityId": 1077936129, "actionStatus": 0`；
  `after-context.json`：`origin=[0,0,0]`，实体 11→12。
- **A（读回）** `…/20261010-004106-save-640895e1/after-1073741842.gil`
  （与当前 LocalLow 的 `1073741842.gil` 同为 28383 B / 12 实体）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- **一致**，但值平凡（全 0 / 全 1）。有力的是 §5.1。

### 5.3 **不同意**：C 编辑器缓存 × A `.gil`（同一实体）

关卡 1073741832，用户手放的那棵树（当次）：
- **C**：`docs/gameplay/REALTIME-INJECTION-20260920.md:25`——"树在此缓存中**三个变换全零**"；`:94`——"辅助目录几何仍为 0"。
- **A**：同 `:25`——"保存文件实际位置 **z=2.9114434719085693**、缩放 **(1,1,1)**"。
- 归因（同项目已写死）：`docs/gameplay/ENTITY-CRUD-LIVE-20260921.md:42`——
  "**Aoo 修改同步不更新 `hTjiSreIlqL`，不能把该缓存全零误认为游戏位置为零**"。
- ⇒ 这是本文**唯一一次两路同读一个实体**，结果是**互相矛盾**。C 路因此**不能**当权威坐标。

### 5.4 **无法比较**：B 读侧 × 任何

`after-context.json` 里每个实体的 `position` 都是 `null`，`flags=79` 无 16（§2.1）。
**没有数字可对**，所以谈不上一致，也谈不上不一致。

---

## 6. 让两路在同一个实体上对上：最便宜的那个实验

**已经达成**的是 **B 写侧 × A**（§5.1，非平凡值）。要**重新**复现它，最便宜的做
法**连进程都不用起**——两份产物都躺在仓里：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


若要**取一个当次、非平凡**的一致，最便宜的一次真机动作是**一条 create + 一次 save**：

- **关卡**：`1073741842`（当次已加载、已保存；`HR_EXPECTED_LEVEL` 用它）。
- **请求**：`scene_cli.py create` 一次，字段取
  `HR_TEMPLATE_ID = 20001965`、`HR_POSITION = 1.0, 0.0, 0.0`、`HR_ROTATION = 0,0,0`、
  `HR_SCALE = 1.0, 1.0, 1.0`；随后 `scene_cli.py save`。
- **回读**：`entity_geometry.read_entity_records("…/1073741842/1073741842.gil")`，
  取 `result.json` 里 `entityId` 指向的那条，比 `position.triple()` 与 `scale.triple()`。
- **要对的字段**：`HR_POSITION ↔ .gil 的 transform field 1`；`HR_SCALE ↔ transform field 3`；
  `HR_TEMPLATE_ID ↔ entry field 8`。预期逐位（float32）相等——因为 §5.1/§5.2 两次都相等。

> ⚠️ 这是**写**（会 UAC + 落盘）。本文**没有**执行它，只把它写清楚。
> ⚠️ `origin` 本机 334 份快照恒 `[0,0,0]`，所以 `world==local` 在本机成立，比较无坐标系歧义——
> **但这不是跨关卡/跨存档的保证**（`.claude` memory `spawn-point-is-a-player-template-field`）。

**如果目标是让 C 也加入一致**（顺带把 `maSidNtJUim/MtbidjteDd3/OStidFtjJdR` 的角色钉死），
最便宜的是**只读**的 `op:"catalog"`：读 `scene.entities[].transform`，对同一实体比 §3.1 的七个符号。
**但预期结果是"再次不同意"**：§5.3 已实测 C 返回全零，`ENTITY-CRUD-LIVE-20260921.md:42` 已把
"Aoo 同步不更新 `hTjiSreIlqL`"写成结论。所以这条实验的价值是**把"C 不可用"钉成当次实证**，
不是期待它这次会一致。

---

## 7. 负结论 / 尚未建立（不许写成"已一致"）

- **B 读侧不读几何**（`game_context_snapshot.h:81`），负结论，不是待办。
- **`.gil` 里位置的世界/本地坐标系未定**：本机所有会话 `origin=[0,0,0]`，`world` 与 `local` 数值恒等，
  **无法区分** `.gil` 存的是哪一个。要分辨需要一份 `origin ≠ 0` 的会话。
- **旋转从未被两路比对过**：A 侧旋转常见**只含单分量**（field 2，degree 样，`entity_geometry.py:47-49`），
  B/C 侧都是**三分量**；且 A 侧已存的实体旋转**全是 (0,0,0)**（本文 dump，1832/1833/1842）。
  `HANDOFF-CREATE-SAVE-20260922.md` §4.1 同款保留："已完成实测主要为零旋转，不能据参数存在就
  报告任意非零旋转全面验收"。
- **C 的三个向量角色顺序未证明**（`EntityTransform.cs:133`），且当次实测值为全零（§5.3）。
- **`Geometry1017Fields`（形状/碰撞几何）从未读出过非空**：`geometryComponentCount` 历史为 0
  （`Geometry1017Fields.cs:156`、`ComponentGeometryEvidence.cs:42`）。
- **B 写侧不能改已有实体**：`place_builtin` 只**实例化模板**（`CLAUDE.md` §五；`MVP-LIVE-RUN-20260922.md` §3.2）；
  C 写的 `TRANSFORM_NATIVE_SETTER_UNKNOWN`（`EntityTransform.cs:36`）同向。

---

## 8. 复现命令（全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**已知仓内非本任务失败（记录，不修）**：`tools/beyond-save/test_gil_container.py::test_profile_lists_every_level_file_present`
当前 FAIL——`fixtures` 用非递归 `LEVEL_DIR.glob("*.gil")`（`test_gil_container.py:66`）收集磁盘关卡，
而 8 个关卡已改存到**同名子目录**（`.../1073741835/1073741835.gil`），于是 profile 列出的 id 比
fixtures 多 8 个。与几何无关；`test_entity_geometry.py` **单独跑全绿**（`24 passed, 178 subtests passed`）。
