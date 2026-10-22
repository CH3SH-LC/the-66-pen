> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #5 挖 — 预制体能不能被「实例化」？（除 `entity.create` 之外的第二条摆放路）

**产出日期**：2026-10-10。位置：`docs/research/reverse-eng-20261010/PREFAB-INSTANTIATE-MINE.md`。

**口径**：**纯离线、纯只读**。全程**未启动/未触碰游戏或编辑器、未连桥、未发任何报文、未注入、未提权、未重启 helper、未写任何存档字节、未读任何图片/PDF**。
证据三处：① `.runtime/editor-catalog/resolved/`（12375 个反编译 `.cs`，用 **Bash `grep -rI`**，**不是** Grep 工具——它会静默跳过 `.runtime/`）② 仓内 C# 源码 `tools/editor-bridge/` ③ 仓内已存在的研究文档与真实回执。
**本文件只读不写**，除本文件外未新增/修改任何东西（**未**碰桥 op 计数，那是另一个任务）。

> 三层分标（`CLAUDE.md` §一.3 / §五）：`文档写了什么` / `工具能做什么` / `真机验证过什么` 严格分开。
> 「搜不到」只写成本次检索范围内未找到（`CLAUDE.md` §一.2：已犯过五次）。
> 用三态措辞：`disproved`（有正面反证）/ `not_found`（查不到）/ `undecidable`（判不了）。

---

## 0. 一句话结论

**没有第二条可用的「摆放」路。** 但答案比"没有"更具体，要点三条：

1. **预制体实例化在语料里作为「命令」只有一个落点**：`beyondEditObjService.RequestPrefabInstance`
   （派发点 `tools/editor-bridge/Adapter/EditorAdapter.cs:545,594,623`）。它**不是**一条能摆东西的路——
   **只吃一个 prefab id，没有任何坐标参数**；且**只对 native kind 1 放行**（`EditorAdapter.cs:537`）；
   并被**真机证伪过**（发出去只多出一个后台对象，用户确认**没有新增可见物体**，见 §2.3）。
2. **真正的"实例化"原语是 `place_builtin`**（`tools/game-executor/native/scene_calls.h:51`）——
   它按 `template_id` 实例化（`scene_calls.h:15-19`），**`entity.create` / `create-batch` 已经在驱动它**
   （`game_scene_action.cpp:188,264`）。⇒ 一个独立的 `instantiate-prefab` 动作是**已有调用的别名**
   （与 `docs/research/reverse-eng-20261010/NATIVE-ACTION-COST.md:201` 一致），**不解锁任何新的半边**。
3. **"预制体带组件可绕过 add-component"这个假设，有一半本来就是真的、且不在预制体这一侧**：
   `create` **连一个组件字段都不送**（`scene_calls.cpp:46-47`，`optional_data` 恒 `nullptr`），
   但**建出来的实体落盘后自带一整套组件**——**组件集随 `template_id` 走**
   （`ENTITY-CREATE-FIELDS.md` §4.4：同关卡 4 种模板 → 组件数 9 / 14 / 20 / 31）。
   ⇒ **`entity.create` 这条路本来就带组件**；预制体请求**没有**提供 create 提供不了的东西。
   而「自己造一个带新组件的预制体」——**命令面不存在**（`PREFAB-COMPONENT-PATH.md` §3-§4）。

**判决**：**否**。预制体实例化**不是**第二条摆放路，也**不**绕过缺失的加组件原语。

---

## 1. 语料检索 —— 预制体相关字面量的全部落点（file:line）

### 1.1 检索命令与范围


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**范围＝`.runtime/editor-catalog/resolved/` 的 12375 个 `.cs`**（本次 `ls | wc -l` = 12375，
与 `COMPONENT-WRITER-MINE.md` 口径一致）。范围外的存在不被本文排除。

### 1.2 「请求/实例」类（与"能不能被实例化"直接相关）

| 字面量 | 落点 file:line | 类别 | 说明 |
|---|---|---|---|
| `RequestPrefabInstance` | `resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:127` | **命令**（下行派发） | `Ikci0qkvMZX(beyondEditObjService, "RequestPrefabInstance", null, args)` |
| `RequestPrefabInstance` | `resolved/VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:184` | 命令 | 同上（`sM5KBF555gu` 分支） |
| `RequestPrefabInstance` | `resolved/VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:2337` | 命令 | 拖放回调链 `BlKKB2np35C`（`FRONTEND-DRAG-CREATE-LOCATION.md:47`） |
| `RequestPrefabInstance` | `resolved/zDwVnSKeJok3DNsJf1Lg.VaR86gKerBXhRbru9366.cs:526` | 命令 | |
| `RequestPrefabInstance` | `resolved/FOV9AWu5QBsMPf0Rwuiu.NQ6Rasu5Wb3lL511Sp4j.cs:796` | 命令 | |
| `FocusPrefabInstance` | `resolved/VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:171` | 命令 | 聚焦，非创建 |
| `FocusPrefabInstance` | `resolved/zDwVnSKeJok3DNsJf1Lg.VaR86gKerBXhRbru9366.cs:527` | 命令 | |
| `FocusPrefabInstance` | `resolved/FOV9AWu5QBsMPf0Rwuiu.NQ6Rasu5Wb3lL511Sp4j.cs:756` | 命令 | |
| `DeleteComponentForPrefab` | `resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:152` | 命令 | **删**组件（与 `DeleteComponentForEditObj` 共用实现） |
| `DeletePrefab` | `resolved/VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:512` | 命令 | 删预制体 |
| `ModifyPrefabName` | `resolved/VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:1106` | 命令 | |
| `ModifyPrefabName` | `resolved/mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:15039`（方法声明 `public void ModifyPrefabName(uint prefabId, string name)`）、`:15041` | 命令 | |
| `ModifyPrefabTag` | `resolved/kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0.cs:2194` | 命令 | |
| `ModifyFactionForPrefab` | `resolved/VwMawhKGHsdXfkO51YfP.HDt4hxKGbds2L9ACUaAM.cs:359` | 命令 | |

**全部 9 条命令字面量的权威清单**由 string-table 复算一致
（`grep -o '"[^"]*Prefab[^"]*"' .runtime/editor-catalog/string-table.json`）：
`AddInstructionGraphForPrefab`、`ApplyPrefabInstanceChange`、`DeleteComponentForPrefab`、`DeletePrefab`、
`FocusPrefabInstance`、`ModifyFactionForPrefab`、`ModifyPrefabName`、`ModifyPrefabTag`、`RequestPrefabInstance`。
其中 `AddInstructionGraphForPrefab` / `ApplyPrefabInstanceChange` 在 `resolved/` **0 命中**（仅存在于字符串表）。

**服务名字面量**：`beyondEditObjService` 定义于
`resolved/gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP.cs:19`（getter `yPFiAIrmqCV`），
正是 §1.2 各派发行里 `HOlfE6lSftgl74pgvnRM.…yPFiAIrmqCV` 解析出的服务名。

### 1.3 「类型/枚举」类（说明预制体在对象模型里是什么，不是摆放入口）

| 字面量 | 落点 file:line | 说明 |
|---|---|---|
| `OfficalPrefab=1` / `CustomPrefab=100` / `PrefabGroupOwner=101` / `PrefabGroupProxy=102` / `PrefabEditObj_Dynamic=400` / `PrefabEditObj_Static=500` | `resolved/nftmtEi44ZpaT9uR9UgI.u2nWUWi4Ei8tbmQLVnuN.cs:6,7,8,9,12,13` | **资源类型枚举**（`u2nWUWi4Ei8tbmQLVnuN`）。`PrefabEditObj` = 预制体编辑对象 |
| `PrefabEditObj` | `resolved/FBtBjqKVhtjhCIRZ4iSK.vmP8csKVlXGk9dUGe1iY.cs:150,250,252`；`resolved/OOZNfNKM3d3pQx6knhPM.f2VPU0KMAFsCU60ufwiU.cs:1164,1182,1282` | 类型判别分支 |
| `OfficalPrefab` | `resolved/FBtBjqKVhtjhCIRZ4iSK.vmP8csKVlXGk9dUGe1iY.cs:222`；`resolved/OOZNfNKM3d3pQx6knhPM.f2VPU0KMAFsCU60ufwiU.cs:1247` | |
| `PrefabSpaceAsset` / `CustomPrefabDynamic` / `CustomPrefabStatic` | `resolved/FpAEvvici3tvyiaTimOn.YtiODUic3KsacB0eqnrG.cs:49,50,51,59,62,63,127,128,135,138,167,171` | 空间资产/自定义预制**种类**（`n9TjVui4v9PFdo3m497f`） |
| `PrefabSpaceAsset` / `CustomPrefabDynamic` / `CustomPrefabStatic` | `resolved/lFHetii40EU81IVmn9aC.n9TjVui4v9PFdo3m497f.cs:7,11,12` | 同枚举定义 |
| `PrefabGroup` / `ProxyPrefab` | `resolved/lFHetii40EU81IVmn9aC.n9TjVui4v9PFdo3m497f.cs:46,47` | 预制体分组/代理 |
| `modelConfigPrefab` | `resolved/C7891kuZ7qNDbK7CWHQh.tC38a9uZumHDvhgFUCLl.cs:1606` | 字段名 |
| `prefabData` | `resolved/hHli8TiG66iZJ8yARru4.wki2XRiGFU1GYAtMOG6c.cs:178`；`resolved/mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:5700` | 字段名 |
| `prefabId` | `resolved/BH0hjKLKn3ubQmu3nVIs.cs:1`；`resolved/mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:15039,15041` | 字段名 |

### 1.4 明确的负面（本次检索范围内未找到）

- **`实例化`（中文）** 在 `resolved/` **0 命中**（`grep -rn -F "实例化"`）。
- **`Instantiate`（任意大小写、任意后缀）** 在 `resolved/` **0 命中**（`grep -rn -i -o -E "[A-Za-z]*nstantiate[A-Za-z]*"`）。
- **`CreatePrefab` / `InstantiatePrefab` / `MakePrefab` / `SpawnPrefab` / `PrefabCreate`** 在 `resolved/` **0 命中**。
- 结论：**语料里没有任何一个"创建预制体 / 实例化预制体"的具名命令**。唯一的"实例化动作"是
  `RequestPrefabInstance`（一个"请求"），唯一的"实例化原语"是原生 `place_builtin`（走 `template_id`）。

> ⚠️ 边界（`PREFAB-COMPONENT-PATH.md:148-149`）：`AddInstructionGraphForPrefab` / `ApplyPrefabInstanceChange`
> 是**字符串表还原名**，不在前端 44 条 operation 里 ⇒ 上列 **0 命中是"范围结论"**，
> 不等于"全集不存在"。折叠常量命令名仍是本检索的盲区（同 `COMPONENT-WRITER-MINE.md` §1/§5）。

---

## 2. 两个东西到底做了什么：**目录读取** vs **实例请求**

题面把 `PrefabCollectionEvidence.cs` 与 `RequestPrefabInstance` 放在一起问"读目录？还是请求实例？"——
**它们是两件完全不同的事，一个读、一个请求**：

### 2.1 `PrefabCollectionEvidence.cs` —— **读目录**（把已物化的预制模型分页读出来）

`tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs:36-167`（`PrefabFieldsPageCore`）：

- **做什么**：一次 registry 扫描把编辑器内存里**已物化的预制模型**按 id 去重排序
  （`:57-66`），然后**分页**读每一页，对每个模型用 `ContentFieldReader` 深读（`:118-127`）。
  它是**有状态、单向分页器**（`PrefabFieldsNext` `:171-180`），页上限 128（`:30`）、
  时间片 2000 ms（`:31`）、续跑靠 `prefab-resume.json`（`:67-92`）。**全是只读**。
- **回什么**（`:152-164`）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  即：**资源 id + 名字 + 图标 + native kind + 业务字段内容投影**。
  `sentToGame:false`、`geometryVerified:false` ⇒ **它不发游戏、不产几何、不是写原语**。

**回执里有没有组件？** 有（组件**类型集合**），但**没有值、没有几何**
（`PREFAB-FIELDS-MINE.md` §4.1-4.3，基于真实回执 `.runtime/editor-bridge/runs/{8c515535…,ce2f82fd…,c980a8f9…}/prefab-fields-page-response.json`）：
194 个预制共读到 16 种组件类型（`Combat=18 / Hitbox=19 / Timer=3 / Effect=6 / RoleStatus=14 / CustomValue=1 …`），
与离线 46 项枚举（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2）逐项互证；但**每条组件记录除类型 id 外的数值全是 0**，128 个预制的**全部 2310 个 float/double 叶子读出来都是 0.0**。
浅读版 `prefab-fields`（`SceneCatalog.cs:163-193`）上限 `MaxDepth=3`（`PrefabFieldRead.cs:13`），**连组件都到不了**。

### 2.2 `RequestPrefabInstance` 代码路径 —— **请求一个实例**（把请求发给对端，不是摆放原语）

桥里唯一真正发这条命令的地方是 `tools/editor-bridge/Adapter/EditorAdapter.cs`，三处：

| 方法 | 行 | 请求对象 | 守卫 | 派发 |
|---|---|---|---|---|
| `RequestCalibrationPrefab` | `:530-547` | 标定立方体 `通常立方体`（id `20001875`） | **`kind!=1` → `native-kind-guard-skipped`**（`:537`） | `:545` |
| `RequestRealtimeLabPrefab` | `:575-597` | 默认模版（id `1086324737`） | 空基线 11 实体 + kind 校验 | `:594` |
| `RequestRealtimeTreePrefab` | `:598-626` | `RT_Probe_Tree`（id `1077936129`） | 13 实体 + kind 校验 | `:623` |

三处派发**完全一样**（`EditorAdapter.cs:545`）：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

其中 `args` 是**长度 1 的列表**，只装一个 `param`（`:542` / `:591` / `:620`：`args.Add(param…Invoke(null, new object[]{id}))`）。

**这就是全部参数：一个 prefab id。没有坐标、没有旋转、没有缩放、没有组件。**
- **回什么**：方法自己返回
  `{ok:true, status:"lab-prefab-requested-effect-unverified", prefabId, nativeKind, receiptPresent, entityIdsBefore, reloadInvoked:false, sceneCreationVerified:false}`
  （`:595-596` / `:624-625`）。`request-calibration-prefab` 多半在 **`:537` 就被 kind 守卫挡掉**，
  回 `{ok:true, status:"native-kind-guard-skipped", requested:false}`。
  ⇒ **回执里只有一个 `receiptPresent` 布尔 + "效果未验"**——**不含任何实体/组件/几何**。

### 2.3 真机验证过什么（这是判决的另一半）

`RequestPrefabInstance` **不是纸面命令，是真发过的**：

- `docs/editor-catalog/INTERFACE-INVENTORY.md:161`：桥接 `request-calibration-prefab` **实发**，
  但被 native kind 守卫跳过（`native-kind-guard-skipped`），**未真正请求**。
- `PRIOR-WORK-REUSE-20260920.md:10` / `REALTIME-INJECTION-20260920.md:21,23`：R119/R123 **单次 RequestPrefabInstance**
  真实发出（参数 1086324737 / 1077936129），游戏回传使目录 11→12 / 13→14，多出一个 **type1402、kind1** 的后台对象，
  但**用户明确反馈「我原来有一棵树，但是没有新的树」**——**没有新增可见物体**。
  该结果已归档为**负面可见性结论**（`REALTIME-INJECTION-20260920.md:69`）。
- `CREATE-SAVE-ENTRY-20260921.md:64-68`（代码支持的推断）：`RequestPrefabInstance` **确实能进同一个低层工厂**，
  但**先固定取 context 1、走 false 分支**，而真实场景拖放取**当前 context、走 true 分支**；
  且 **RPC 没有三向量参数**。⇒ 这是它"返回了 kind1 对象却不出现在场景里"的机制解释。

⇒ **真机层面：这条路 `disproved` 于"能摆放可见实体"。** 不是"还没做"，是"做了、没有"。

---

## 3. 与 `entity.create` 对比 —— 预制体路有 create 路没有的东西吗？

### 3.1 `entity.create` 是什么（原生侧）

- **原语**：`place_builtin`（`tools/game-executor/native/scene_calls.h:51`），
  签名 `void* (__cdecl*)(context, template_id, builtin, position, rotation, scale, requested_id, flag8, optional_data, flag10, flag11)`
  （`scene_calls.h:15-19`）。
- **它就是"按 `template_id` 实例化对象"**。语料里 `place_builtin` 的注释明写它接的是
  `YuanShen 7.1 default **drag** caller d31aae6 -> 106df3c0`（`scene_calls.h:12-14`）——
  **正是真实拖放创建走的那条路**。
- `entity.create` / `create-batch` 已在驱动它（`game_scene_action.cpp:188` 单条、`:264` 批量；同一 `HR_ACTION=1`）。
- agent 侧请求体只有 4 个键：`templateId / position / rotation / scale`（`scene_cli.py:258-266`），
  **没有 component、没有 name、没有 tag**。

### 3.2 关键对比表

| 维度 | `entity.create`（template-create） | `RequestPrefabInstance`（prefab 请求） |
|---|---|---|
| 原生原语 | `place_builtin`（`scene_calls.h:51`；`game_scene_action.cpp:188,264`） | 编辑器→对端 1018 命令（`EditorAdapter.cs:545`） |
| 参数 | `template_id` + **pos/rot/scale 三向量**（`scene_calls.h:15-19`） | **仅一个 prefab id**，无坐标（`EditorAdapter.cs:542,591,620`） |
| 谁能控制落点 | **能**（建时定死，`CLAUDE.md` §六(c)） | **不能**（RPC 无三向量） |
| 门控 | 无模板白名单（任何 uint32） | **只对 native kind 1**（`EditorAdapter.cs:537`） |
| 真机结果 | 闭环走通：`.gil` 21872→28383 B、含 entityId/graphId/templateId（`CLAUDE.md` §五） | **用户确认无新增可见物体**（`REALTIME-INJECTION-20260920.md:69`） |
| 带组件？ | **带**（见 §3.3） | 未证（请求都没产生可见实体） |
| 落盘 | 由 native `save` 落盘（`ENTITY-CREATE-FIELDS.md:196`） | 无落盘证据 |

### 3.3 "预制体带组件可绕过 add-component" —— 这个前提有一半本来就是真的，但不在预制体这一侧

**`entity.create` 建出来的实体，本来就带组件**（这是本任务最关键的一条）：

- `create` **一个组件字段都不送**：唯一可放附加数据的形参 `optional_data` **恒传 `nullptr`**
  （`tools/game-executor/native/scene_calls.cpp:46-47`）。
- **但落盘实体自带一整套组件**：地块（`template=20001965`）的记录带 **31 个 `entry field 5/6/7` wrapper**
  （`ENTITY-CREATE-FIELDS.md` §4.3，实测 `.runtime/game-executor/scene-cli/20261010-004106-save-640895e1/after-1073741842.gil`）。
- **组件集随 `template_id` 走**（`ENTITY-CREATE-FIELDS.md` §4.4）：同关卡 4 种模板 →
  `10003004`→9 / `1000000`→14 / `1000001`→20 / `20001965`→31。**不是"所有实体一套固定默认组件"。**

⇒ **"实例化一个已经带组件的模板，得到带组件的实体"——`entity.create` 这条路已经做到了。**
预制体请求**在这一点上没有增益**；反而它连"产生一个可见实体"都未证。

### 3.4 预制体模型确实记录了"默认组件类型集合"，但……

- 预制模型上有组件表（`PREFAB-FIELDS-MINE.md` §4.1：字段 `OT7XAkHtROh` → `List<…>`），
  194 个预制读到 16 种组件**类型名/编号**。理论上"由某预制创建的实体应带上该预制的默认组件集"。
- **但三个硬限制**：
  1. **参数值全 0、几何全 0**（`PREFAB-FIELDS-MINE.md` §4.2-4.3）——**只有"有没有"，没有"怎么配"**。
  2. **无"造预制体"命令**：`command_route` 38 行里**没有任何建模板/建预制体**的行
     （`TEMPLATE-CREATION-MINE.md:39-59` 逐行核过）；`AddComponent/CreateComponent/AttachComponent/InsertComponent`
     在四处检索范围**全 0 命中**（`PREFAB-COMPONENT-PATH.md:143-146`）。⇒ **造不出一个带新组件的预制体。**
  3. **194 个预制的样本里 `Collision(8)` 一次都没出现**（`PREFAB-FIELDS-MINE.md` §4.1 注）——
     "本次检索范围内未见"，不能据此说不存在。
- 且 `PREFAB-COMPONENT-PATH.md` §4 已判：**实体与预制体在"组件"上完全对称**——
  同一个集合类、同一个泛型 `Add`、命令面**两边都只有删、都没有加**。
  「所谓预制体侧有 ADD/SET 组件命令 **不存在**」。

---

## 4. 判决

**(1) 有没有第二条摆放路？**

**没有可用的第二条。**
- `RequestPrefabInstance` 是语料里唯一的"预制体实例化命令"，但它**不是摆放原语**：
  无坐标参数（`EditorAdapter.cs:542`）、只对 kind 1 放行（`:537`）、**真机证伪**于可见创建
  （`REALTIME-INJECTION-20260920.md:69`）。**`disproved`**（有正面反证，非 not_found）。
- 真正的实例化原语 `place_builtin`（`scene_calls.h:51`）**已被 `entity.create` 占用**；
  一个独立的"instantiate-prefab"动作**只是它的别名**（`NATIVE-ACTION-COST.md:201`），
  **不解锁任何新半边**。**`disproved`**。

**(2) 预制体路会不会带组件？**

**带组件的"能力"存在，但既不是预制体路独有、也不足以绕过 add-component。**
- **正面**：预制模型记录了**默认组件类型集合**（`PREFAB-FIELDS-MINE.md` §4.1），
  任何由它实例化的实体**理论上应带上该集合**（同文 §5.2 亦作此注，**本轮未比对**，`undecidable`）。
- **但 `entity.create` 已经带组件**：组件集随 `template_id` 走（`ENTITY-CREATE-FIELDS.md` §4.4 实测）。
  ⇒ **预制体路在"带组件"上不给 create 添任何东西。**
- **且造不出带新组件的预制体**：无建预制体命令、无 AddComponent（`PREFAB-COMPONENT-PATH.md` §3-§4）。
  ⇒ **拿不到一个"带 Collision 触发器"的预制体来实例化**——**M1 的 add-component 缺口依旧**。

**(3) 实用规则（写给下一会话）**

- 要摆实体、要实体带默认组件：**继续用 `entity.create` 在"建时把 template/坐标一次给全"**
  （`CLAUDE.md` §六(c)）——这是唯一已验证能摆、能落盘的路。
- **不要**去挖"预制体实例化"当第二条摆放路——语料里没有具名的建/实例化预制体命令，
  唯一的一条 `RequestPrefabInstance` 已真机证伪于可见创建，且它带不动坐标。
- 「实体为什么自带组件」这个更值钱的问题，出口**不在预制体**，而在
  `PREFAB-COMPONENT-PATH.md` §5.1 已给的线索：**组件是数据、不是命令**——
  写组件要么走 `.gil` 字节面（`entry` 字段 5/6/7），要么走编辑器内存面（`ODUi…field90`），**两条都还没有写入者**。

---

## 5. 引用表（本次 checkout / 本次 resolved 语料实测）

| 论断 | 证据 |
|---|---|
| 9 条 `*Prefab*` 命令字面量清单 | `grep -o '"[^"]*Prefab[^"]*"' .runtime/editor-catalog/string-table.json`；`PREFAB-COMPONENT-PATH.md:117-121` |
| `RequestPrefabInstance` 五处落点 | `resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:127`；`resolved/VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:184,2337`；`resolved/zDwVnSKeJok3DNsJf1Lg.VaR86gKerBXhRbru9366.cs:526`；`resolved/FOV9AWu5QBsMPf0Rwuiu.NQ6Rasu5Wb3lL511Sp4j.cs:796` |
| 服务名 `beyondEditObjService` 定义 | `resolved/gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP.cs:19` |
| 桥发 `RequestPrefabInstance` 的三处 | `tools/editor-bridge/Adapter/EditorAdapter.cs:545,594,623` |
| kind 守卫（只放行 kind 1） | `tools/editor-bridge/Adapter/EditorAdapter.cs:537` |
| 请求 args 只有一个 id、无坐标 | `tools/editor-bridge/Adapter/EditorAdapter.cs:542,591,620` |
| 方法回执形状（`sceneCreationVerified:false`） | `tools/editor-bridge/Adapter/EditorAdapter.cs:595-596,624-625` |
| `PrefabCollectionEvidence` 是**读目录**分页器 | `tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs:36-167,152-164,171-180` |
| 浅读 op 的上限 | `tools/editor-bridge/Adapter/PrefabFieldRead.cs:13`；`tools/editor-bridge/Adapter/SceneCatalog.cs:163-193` |
| 深读回执含组件类型集、值全 0、几何全 0 | `docs/research/reverse-eng-20261010/PREFAB-FIELDS-MINE.md` §3.2,§4.1-4.3 |
| 预制体与实体组件路径**对称**、无 Add | `docs/research/reverse-eng-20261010/PREFAB-COMPONENT-PATH.md` §3-§4 |
| `instantiate-prefab` 是伪需求（别名 create） | `docs/research/reverse-eng-20261010/NATIVE-ACTION-COST.md:201` |
| `place_builtin` 签名＝按 template_id 实例化 | `tools/game-executor/native/scene_calls.h:12-19,51` |
| `create`/`create-batch` 驱动 `place_builtin` | `tools/game-executor/native/game_scene_action.cpp:188,264` |
| `create` 不送组件（`optional_data=nullptr`） | `tools/game-executor/native/scene_calls.cpp:46-47` |
| `create` 落盘实体自带 31 项组件、随模板变 | `docs/research/reverse-eng-20261010/ENTITY-CREATE-FIELDS.md` §4.3-4.4,§5 |
| `RequestPrefabInstance` 真机证伪可见创建 | `docs/gameplay/REALTIME-INJECTION-20260920.md:21,23,69`；`docs/gameplay/PRIOR-WORK-REUSE-20260920.md:10` |
| 它与拖放的机制差异（context1/false 分支、无三向量） | `docs/gameplay/CREATE-SAVE-ENTRY-20260921.md:64-68` |
| 桥发过但被 kind 守卫跳过 | `docs/editor-catalog/INTERFACE-INVENTORY.md:161,385` |
| `command_route` 38 行无建模板/建预制体 | `docs/research/reverse-eng-20261010/TEMPLATE-CREATION-MINE.md:39-59` |
| 四处检索 0 命中 Add/Create/Attach/InsertComponent | `docs/research/reverse-eng-20261010/PREFAB-COMPONENT-PATH.md:143-146` |

---

*本文件由 2026-10-10 会话从仓内源码、`docs/research/reverse-eng-20261010/` 与 `.runtime/editor-catalog/resolved/`
（Bash `grep -rI`，非 Grep 工具）只读整理；**未实现、未连线、未连桥、未触碰游戏/编辑器、未写任何存档字节**。
所有行号为本次 checkout 实测；负面结论均写明检索范围。*
