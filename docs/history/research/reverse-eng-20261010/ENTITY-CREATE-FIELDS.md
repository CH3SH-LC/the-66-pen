> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #5 挖 — `entity.create` 到底记录了什么（超出几何的部分）——ENTITY-CREATE-FIELDS

**产出日期**：2026-10-10。位置：`docs/research/reverse-eng-20261010/ENTITY-CREATE-FIELDS.md`。

**任务**：地块（demo 里 `--template-id 20001965` 建的那块）经 `create` + `save` 后，**落盘 `.gil` 的实体记录里，除了位置以外还有什么**——
有没有**组件表**、**tag 表**、任何**探针读得到**的东西？以及：**建一个实体，它默认就带组件吗**？

**口径（硬规则遵守情况）**：**纯离线、纯只读**。全程**未启动/未触碰游戏或编辑器、未连桥、未发任何报文、未注入、未提权、未重启 helper**。
读取范围＝① 仓内 C++/Python 源码 ② **仓内已保存的 `.gil` 快照**（`.runtime/game-executor/scene-cli/…`）
③ **只读** `LocalLow` 下的当次 `.gil`（仅 `open(...,'rb')`，**未写一字节**）。
未读任何图片、未读 PDF。本文件是本次唯一新增/拥有的文件。

> 三层分标（`CLAUDE.md` §一.3 / §五）：本文件结论全部是 **静态读字节 + 静态读源码**；**没有一条是本轮新跑的真机动作**。
> 引用的真机数字，全部来自**仓内已存在的产物**（2026-10-10 的 create/save run），且**当次已用 `after-context.json` / `.gil` 独立复核**。

---

## 0. 一句话结论

1. **`create` 调用本身只送 4 类东西**：`template_id`、一个模式字节 `builtin`、三个向量（position / rotation / scale），外加 5 个固定常量参数（`requested_id=0`、`flag8=1`、`optional_data=nullptr`、`flag10=0`、`flag11=0`）。
   **它不送任何组件、任何 tag、任何名字**（`tools/game-executor/native/scene_calls.cpp:46-47`）。
2. **但建出来的实体**，落盘后**带一份 31 项的组件表**（`.gil` 里 `entry field 5/6/7`，共 31 个 wrapper），**外加一个 `tag`（`entry field 8`＝模板号）**。
   ⇒ **实体不是「默认无组件」**：`create` 一个字段都没送组件，游戏却替它实例化出了一整套。
3. **组件从哪来**：同一关卡里**不同模板的组件数不同**（`10003004`→9、`1000000`→14、`1000001`→20、`20001965`→31），
   ⇒ **组件集随模板走**，不是「所有实体一套固定默认值」。**(证据充分)**
4. **重要保留**：`.gil` 里的这 31 个 `(group, kind)` wrapper，**与编辑器探针 `inspect-entity-components` 读的
   `LudM06iCRNk4iFkwqKIW {id, enabled, x, y}` 是不是同一套「组件」词汇，未证**（两级命名空间未被任何仓内文档打通）。
   ⇒ 对**读 `.gil` 的解码器**（`entity_geometry`）：**确定有东西可读**；对**编辑器只读探针**：**极可能，但无真机读回证据**。

---

## 1. `create` 调用真正送出去的参数（native 侧）

### 1.1 被调用的原生工厂签名

`tools/game-executor/native/scene_calls.h:15-19`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**11 个形参**。其中只有 `template_id` / `builtin` / `position` / `rotation` / `scale` 承载业务值；其余 6 个是调用惯例位。

### 1.2 实际传进去的 11 个实参（逐位）

`tools/game-executor/native/scene_calls.cpp:46-47`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


| # | 形参 | 实参 | 说明 | file:line |
|---:|---|---|---|---|
| 1 | `context` | `context` | 已解析的当前关卡 context 指针 | `scene_calls.cpp:46` |
| 2 | `template_id` | 输入模板号（本例 `20001965`） | | `scene_calls.cpp:46` |
| 3 | `builtin` | `1`（宏 `HR_PLACE_BUILTIN` 默认；拖动调用者 `d31aae6` 同值） | 模式位，**非常量 ABI** | `scene_calls.cpp:41-45,47` |
| 4 | `position` | `world - context_origin` | 先做减法的**局部**坐标 | `scene_calls.cpp:21-23,47` |
| 5 | `rotation` | 入参 `rotation_degrees` | 按度 | `scene_calls.cpp:47` |
| 6 | `scale` | 入参 `scale` | 要求三分量 >0 | `scene_calls.cpp:17,47` |
| 7 | `requested_id` | **`0`** | 「请求 id」恒 0（不指定） | `scene_calls.cpp:47` |
| 8 | `flag8` | **`1`** | 常量 | `scene_calls.cpp:47` |
| 9 | `optional_data` | **`nullptr`** | **就是这里——没有组件/附加数据被送进去** | `scene_calls.cpp:47` |
| 10 | `flag10` | **`0`** | 常量 | `scene_calls.cpp:47` |
| 11 | `flag11` | **`0`** | 常量 | `scene_calls.cpp:47` |

**逐点结论**：**参数里没有任何一个能携带「组件」。** 第 9 个参数（本可放附加数据的指针）**恒传 `nullptr`**。
唯一能让「组件」出现在实体上的入口，是**引擎按第 2 个参数 `template_id` 去实例化**。

> 单实体 `create` 与批量 `create-batch` 走**同一个** `place_builtin`（批量在 `game_scene_action.cpp:264-265` 内循环），
> 两者参数结构一致，**都不送组件**。

### 1.3 调用前对向量的规范化

`tools/game-executor/native/scene_calls.cpp:11-24`：
- 校验 `template_id` 在 `(0, 2^32-1]`、六个浮点全有限、`scale` 三分量 >0；
- `position := world_position - context_origin`（**同一份原生浮点减法，不二次换算**，`:20-23`）；
- 任何一项不过 → 返回 `CallCode::invalid_input`，**不调用**工厂。

---

## 2. 回执（receipt）记录了哪些字段

### 2.1 回执结构体

`tools/game-executor/native/game_scene_action.h:11-23`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**回执里没有任何「组件」字段。** 它记录的是：进程/动作元数据（`size/version/action/status`）、关卡对齐（`levelId/expectedLevelId`）、
**`called`（是否真的调了原生）**、**`entityId`（解析出来的实体 id）**、**`owner`（工厂返回的指针）**、
`callCode`（`returned / invalid_input / missing_binding / null_entity / native_save_rejected`，`scene_calls.h:26-29`）、
批量的 `placedCount/placedId[]`。

### 2.2 单实体 `create` 的回证逻辑

`tools/game-executor/native/game_scene_action.cpp:184-213`（`HR_ACTION == 1`）：
1. 组 `PlacementInput`，`origin` 取当次 `before->origin`（`:185-186`）；
2. 调 `place_builtin(...)`（`:188-190`）；`callCode`/`owner` 落回执（`:191-192`）；
3. 重新抓一份 `after` 快照（`:195`）；
4. **后置校验**：实体数必须 `+1`（`:198`），旧实体逐个 `id/owner/config/configId/context` 全保留（`:200-207`）；
5. **认领新实体**：在 `after` 里找 `owner==out->owner && configId==HR_TEMPLATE_ID && (flags&79)==79`（`:208-213`），
   **命中即取它的 `id` 写进 `out->entityId`**（`:211`）。

⇒ **回执能回读的，只有「新实体的 id / owner / configId」，没有组件清单。**

### 2.3 回执携带的 `GameContextSnapshot` 里每个实体长什么样

`tools/game-executor/native/game_context_snapshot.h:78-84`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**每个实体只有 5 个标量 + 3 个指针 + 一个从不读的 `position[3]`**（`:81` 注释明写「GE_POSITION_READ is never set: no proven position offset」）。
`flags` 是位掩码（`game_context_snapshot.h:57-61`：`GE_ID_READ / GE_CONFIG_ID_READ / GE_CONTEXT_MATCH / GE_KEY_MATCH / GE_POSITION_READ / GE_CONFIG_NULL / GE_CONTEXT_READ`）。
**这里没有组件表，也没有 tag 表。**

---

## 3. agent 侧 `create` 路径送了哪些字段

### 3.1 排队的请求体（`create` / `creature-create`）

`tools/game-executor/scene_cli.py:258-266`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


⇒ 请求体里与实体有关的键**只有 4 个**：`templateId / position / rotation / scale`。**没有 component、没有 name、没有 tag。**
（2026-10-09 起**无模板白名单**，任何 uint32 都收：`scene_cli.py:260-262`、`build_scene_profile.py:31-49`。）

### 3.2 批量请求逐条规范化

`tools/game-executor/scene_cli.py:170-192`（`normalize_placement`）：
- **闭集键**：只允许 `template_id / position / rotation / scale / label`，其余一律拒（`:178-180`）；
- **必需键**：`template_id / position / scale`（`:181-183`）；`rotation` 缺省 `(0,0,0)`（`:189`）；
- `template_id` 必须是 uint32（`:184-186`）；三个向量必须**恰好三个数值、拒 bool/字符串**（`strict_vector3`，`:155-167`），`scale` 必须 >0。
- **`label` 被显式剔除**：`normalize_placement` 返回的 dict 里**不含 label**（`:187-192`），注释 `:174-177` 说明「label 是惰性标注，故意不进闭集请求、也不进被复核的原生请求哈希」。

### 3.3 编译进 profile 的宏

`tools/game-executor/build_scene_profile.py`：
- 动作映射：`HR_ACTION={'inspect':0,'create':1,'creature-create':1,'save':2,'create-batch':3}[action]`（`:257`）——
  **`creature-create` 与 `create` 同一个原生分支（都是 1）**，家族区别只活在（已删除的）白名单里（`:252-256`）。
- 单实体：`HR_TEMPLATE_ID` + `HR_POSITION/ROTATION/SCALE`（`:259, :297-298`）。
- 批量：`HR_PLACEMENT_COUNT` + `HR_PLACEMENT_TEMPLATE[]` + `HR_PLACEMENT_TRANSFORM[]`（`:299-308`），后者是每实体 9 个 float（pos/rot/scale 展平）。
- 请求字典本身：`request={'action':…, 'levelId':…}`，create 时 `update(templateId=…, position=…, rotation=…, scale=…)`（`:226-230`）。

**全路径（`scene_cli` → 队列 → `build_scene_profile` → `target_config.h` → C++）都只搬 template + 几何，没有任何组件字段。**

### 3.4 `.gil` 快照的抓取点

`tools/game-executor/scene_cli.py:315-340`（`preserve_gils`）：在 `after` 相位，把 target/受保护 `.gil` **稳定后**读字节、按 `after-<level>.gil` 存进 run 目录（`:336-339`）。**这就是第 4 节要解码的那份快照。**

---

## 4. 落盘 `.gil` 的实体记录——除位置外还有什么（字节实证）

### 4.1 选定的实体与文件

- **实体**：`id = 1077936129`，`template = 20001965`（demo 的地块）。
  真机来源：`.runtime/game-executor/scene-cli/20261010-003436-create-50c28b0f/result.json` → `entityId=1077936129, levelId=1073741842, actionStatus=0`（**create 回执**）。
- **解码文件**：`.runtime/game-executor/scene-cli/20261010-004106-save-640895e1/after-1073741842.gil`（28383 B）。
  **与当次只读的 `LocalLow/…/1073741842/1073741842.gil` 逐字节相同**：两份 `sha256[:16] = 56feb97d916d9037`、均 28383 B。
- 对照：create run 的 `after-1073741842.gil`（21872 B，11 实体）与 save run 的 `before-1073741842.gil`（21872 B）
  **sha256 同为 `88ad2acfb3a0b8e6`** ⇒ **`create` 不动磁盘 `.gil`；只有 `save` 落盘**（与记忆 `native-save-persists-everything-unsaved`、`scene-save-writes-the-game-not-the-editor` 一致）。

### 4.2 地块记录的结构（`entity_geometry.read_entity_records`）

`tools/beyond-save/entity_geometry.py:124-134` 的常量 + `:387-423` 的读法给出记录形状：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**地块记录（index 11）实测**（对保存档跑 `read_entity_records`）：

| 项 | 值 | 字节证据 |
|---|---|---|
| `entry field 1`（id） | **1077936129** | 记录体开头 `08 81 80 80 82 04`（key_off=4436，val_off=4439，体长 564 B） |
| `entry field 2`（ref） | `{1: 20001965, 2: 1}` | `12 07 08 ad e9 c4 09 10 01` |
| `entry field 5/6/7`（**组件表**） | **31 个 wrapper**（g5=10、g6=15、g7=6） | 见下表 |
| `entry field 8`（tag） | **20001965**（＝模板号） | 与 `HR_TEMPLATE_ID 20001965` 逐位相等 |
| transform（g6/kind1/payload field 11） | pos `(0,0,0)`、rot `(0,0,0)`、scale `{1:1,2:1,3:1}`、scalar `{501: 4294967295}` | 与 `HR_POSITION 0,0,0` / `HR_SCALE 1,1,1` 一致 |

### 4.3 那 31 个组件 wrapper（`(group, kind, payload_field, payload_len)`）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- **有 payload 的**（`payload_len > 0`）只是少数；**多数 wrapper 的 payload 长度为 0**（写了但空）。
- 有意义的 payload 抽样（字节实证）：`group5/kind1/field11` = 8 B → 内含 `0a 06 e5 9c 9f e7 94 b0` = **UTF-8 串 `土田`**（地块名）。
- **`group 6 / kind 1 / field 11` 就是 transform**（`entity_geometry.py:130-133`），即「位置」所在——**位置本身也是一个组件 wrapper**。

### 4.4 「同一个关卡里，组件的数量随模板变」——否证「组件无差别默认」

同关卡 12 个实体的组件数与 tag：

| entity id | tag(field8=模板号) | 组件数 |
|---:|---:|---:|
| 1094713345 | 10003004 | 9 |
| 1086324737 | 1000000 | 14 |
| 1090519041 | 1000001 | 20 |
| 1086324738…1086324745（8 台） | 1000000 | 14 |
| **1077936129（地块，本任务）** | **20001965** | **31** |

⇒ **不同模板 → 组件数/集合不同**（9 / 14 / 20 / 31）。**不是「所有实体一套固定默认组件表」。**

---

## 5. 判决：`create` 给实体带组件吗？

### 5.1 有事实支撑的部分

- **`create` 不送组件**：唯一可放附加数据的形参 `optional_data` **恒传 `nullptr`**（`scene_calls.cpp:47`）；agent 侧请求体只有 `templateId/position/rotation/scale`（`scene_cli.py:258-266`）。
- **落盘实体却有组件**：地块记录带 **31 个 `entry field 5/6/7` wrapper**（§4.3），且**12/12 个实体都有组件组**（§4.4）。
- ⇒ **实体不是「默认无组件」**。`create` 一个组件字段都没送，游戏仍替它实例化出了一整套（含 transform 本身）。

### 5.2 判决（带置信标记）

> **`create` 建出的实体默认带组件。** —— 置信：**已证**（对「有无组件」这一是非题）。
> **组件的具体集合来自模板定义（随 `template_id` 变），不是全局固定常量。** —— 置信：**已证**（§4.4 四模板四数量）。

### 5.3 **必须分离的保留：这是哪一层「组件」？**

本任务只拥有静态证据，必须把两套「组件」词汇分开，**不得混称**（`CLAUDE.md` §一.3）：

| | `.gil` 侧「组件」 | 编辑器探针侧「组件」 |
|---|---|---|
| 形状 | `entry field 5/6/7` 的 wrapper `{1:kind, <P>:payload}` | `LudM06iCRNk4iFkwqKIW` → `{id:uint, enabled:bool, x:double, y:double}` |
| 读方 | `tools/beyond-save/entity_geometry.py`（`:128,353-372`） | 桥 op `inspect-entity-components`（`EntityComponentProbe.cs`） |
| 真机读回？ | **本次已读**（31 wrapper） | **无**（R269 已编译、`BridgeServer.cs:306` 有 dispatch，但**尚未真机运行**；见 `CLAUDE.md` §五） |
| 编号域 | `(group, kind)`；`kind` 值实测到 **111** | 闭合枚举 `jaUof90C3Ncl5BAJri4x`，**46 成员、值域 0–47**（`COLLISION-COMPONENT-ID.md:18-22`） |

**要点**：`.gil` 侧 `kind` 出现 **111 / 93 / 62 / 52** 等 >47 的值（§4.3），而编辑器枚举**最大值只到 47**（`COLLISION-COMPONENT-ID.md:18`）。
`(group, kind)` 是**位置性**的（`entity_geometry.py:27-32,89-91` 明写「no name asserted」），**没有任何仓内文档把两套编号打通**。

⇒ **精确措辞**：
- 对 **`entity_geometry` 这类读 `.gil` 的解码器**：地块**确凿有 31 项可读组件**（本任务已读）。
- 对 **编辑器 `inspect-entity-components` 只读探针**：**「有东西可读」是极可能的**（实体显然携带组件语义），
  **但「探针会返回哪些行、id 集合是什么」无任何真机证据**——**「读得到 `.gil` 的组件」≠「探针读得回」**（`CLAUDE.md` §一.3 三层纪律）。
  **要坐实，须真机跑一次 `inspect-entity-components`——本任务不做（禁发报文）。**

---

## 6. 复现（全部只读，无进程、无报文、无写入）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`tools/beyond-save` 模块自测（应绿）：`PYTHONIOENCODING=utf-8 python -m pytest test_entity_geometry.py -q`。

---

## 7. 负结论 / 未建立（不许写成「已一致」）

- **编辑器探针没跑过**：`inspect-entity-components` 的**真机读回**在本任务内**为零证据**（禁发报文）。§5.3 的两套词汇**未被任何文档/实验打通**。
- **`.gil` `kind` 无语义名**：`entry field 5/6/7` 的 `kind` 值只有**位置含义**；本文**不**宣称 `kind=8` 就是「碰撞触发器」之类（`entity_geometry.py:89-91` 明确保留）。
- **无法从本数据判定「模板定义 vs 引擎默认」**：地块模板 `20001965` 在本关卡只有 1 个实例（就是我们建的那个），
  **没有「同模板、非我们建」的对照**，故只能证「随模板变」，**不能**证「模板里写死了正好这 31 项」。
- **回执侧读不到组件**：`GameSceneActionResult` 与 `GameEntitySnapshot` **结构里根本没有组件字段**（§2.1-2.3）——这是**结构性的负结论**，不是「没挖到」。
