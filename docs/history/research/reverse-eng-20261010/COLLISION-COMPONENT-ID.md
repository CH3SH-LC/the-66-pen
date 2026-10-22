> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #3 挖 — 碰撞触发器组件的 **id 到底是哪个数**：从 `jaUof90C3Ncl5BAJri4x` 枚举到探针行

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。
**本文件只读不写**：除新增本文件外，未修改仓内任何文件。

> ⚠️ **2026-10-11 更正（偏移 + 地址）**：文内组件的 kind 偏移已被 `docs/research/reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md` 取代——
> **`[comp+0x34]`** 才是种类字段（旧记 `[comp+0x30]` 是 byte `enabled`）；组件容器是 **`[entity+0x68]`**（不是 `[entity+0x48]`）。
> 涉及的旧 RVA（`0xcb64140` / `0x10abeb40` / `0x102d4750` / `0x10ac50a0` 等）在当前映像里**已过期**，须按对账文件 §5 重导。

**证据来源**：`.runtime/editor-catalog/resolved/`（12,375 个反编译 `.cs`，用 **Bash `grep`** / `Read`，**Grep 工具会静默跳过 `.runtime/`**，见记忆 `grep-tool-skips-runtime-dir`）+ 仓内桥源码 `tools/editor-bridge/Adapter/`。

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 本文件结论**全部是静态**（读反编译/读桥源码）；**没有一条是本轮真机跑出来的**。
> 凡"N 命中 0"均写明**检索范围**；记忆 `absence-of-evidence-discipline`：**"搜不到"≠"不存在"**。

---

## 0. 一句话结论

1. **组件类型是一张封闭枚举，46 个成员，值域 0–47（缺 2、10），文件只有一处**：
   `resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-51`。
   `BeyondCompTypeClientTrigger=5`（`:9`）、**`BeyondCompTypeCollision=8`（`:12`）**、`StuffBag=33`（`:36`）、`Shop=35`（`:38`）、`PopUp=40`（`:43`）、`CursorCollision=45`（`:48`）。
   > **更正**：同目录 `COMPONENT-WRITER-MINE.md:19,77` 记的是「**47 项**」。**实测是 46 个成员**
   > （45 个带尾逗号 + `Arraysize=47` 无尾逗号；值域 0..47 挖掉 2 与 10）。见 §1.2。
2. **探针行里的 `id` 是「枚举值（以 uint 承载）」，不是「按实例递增的序号」。**
   证明链是**赋值方向**：实体/预制体反序列化时，组件的 id 字段被**赋成 `(uint)` 的一个 `jaUof90C3Ncl5BAJri4x` 值**
   （`Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:400`、`mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26375,26796`）——见 §2。
3. **假设（待真机读回证实/证伪）**：一个挂了「碰撞触发器」组件的实体，其该行会读回 **`id = 8`**（`BeyondCompTypeCollision`）。
   给出该假设的**可证伪判据**（§3.3）：若真机读回的是一个**从 0 起的连号**（0/1/2…），则 2 号结论**被证伪**，id 是实例序号。

---

## 1. 组件类型全枚举（逐成员，file:line）

### 1.1 唯一定义处

- **文件**：`.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs`
- **声明**：`internal enum jaUof90C3Ncl5BAJri4x`（`:3`），命名空间 `QbNEoK0CioqD9L4tX6TA`（`:1`），枚举体 `:4`–`:51`。
- **唯一性核验**：`grep -rln "enum jaUof90C3Ncl5BAJri4x" resolved/` → **恰好 1 个文件**（就是它）。无第二份同份定义。

**全 46 成员（值 → 成员，行号为实测）**：

| 值 | 成员 | 行 |   | 值 | 成员 | 行 |
|---:|---|---|---|---:|---|---|
| 0 | `BeyondCompTypeNone` | `:5` |  | 24 | `BeyondCompTypeMpAction` | `:27` |
| 1 | `BeyondCompTypeCustomValue` | `:6` |  | 25 | `BeyondCompTypeTag` | `:28` |
| 3 | `BeyondCompTypeTimer` | `:7` |  | 26 | `BeyondCompTypeEnmity` | `:29` |
| 4 | `BeyondCompTypeMover` | `:8` |  | 27 | `BeyondCompTypeNameplate` | `:30` |
| **5** | **`BeyondCompTypeClientTrigger`** | **`:9`** |  | 28 | `BeyondCompTypeTalk` | `:31` |
| 6 | `BeyondCompTypeEffect` | `:10` |  | 29 | `BeyondCompTypeSoundEffect` | `:32` |
| 7 | `BeyondCompTypeBornPoint` | `:11` |  | 30 | `BeyondCompTypeMonsterPatrol` | `:33` |
| **8** | **`BeyondCompTypeCollision`** | **`:12`** |  | 31 | `BeyondCompTypeLevelStateMachine` | `:34` |
| 9 | `BeyondCompTypeFollowMove` | `:13` |  | 32 | `BeyondCompTypeMinimapMark` | `:35` |
| 11 | `BeyondCompTypeBulletMove` | `:14` |  | **33** | **`BeyondCompTypeStuffBag`** | **`:36`** |
| 12 | `BeyondCompTypeHitDetection` | `:15` |  | 34 | `BeyondCompTypeEquipStuffBag` | `:37` |
| 13 | `BeyondCompTypeCamera` | `:16` |  | **35** | **`BeyondCompTypeShop`** | **`:38`** |
| 14 | `BeyondCompTypeRoleStatus` | `:17` |  | 36 | `BeyondCompTypeDropGather` | `:39` |
| 15 | `BeyondCompTypeAvatarDisturber` | `:18` |  | 37 | `BeyondCompTypeDropStuff` | `:40` |
| 16 | `BeyondCompTypeCountDown` | `:19` |  | 38 | `BeyondCompTypeLightGroup` | `:41` |
| 17 | `BeyondCompTypeOption` | `:20` |  | 39 | `BeyondCompTypeScanEntity` | `:42` |
| 18 | `BeyondCompTypeCombat` | `:21` |  | **40** | **`BeyondCompTypePopUp`** | **`:43`** |
| 19 | `BeyondCompTypeHitbox` | `:22` |  | 41 | `BeyondCompTypeObstacle` | `:44` |
| 20 | `BeyondCompTypeBulletPattern` | `:23` |  | 42 | `BeyondCompTypeMonsterAiComp` | `:45` |
| 21 | `BeyondCompTypeTempAttachPoint` | `:24` |  | 43 | `BeyondCompTypeWaterfallComp` | `:46` |
| 22 | `BeyondCompTypeCustomSkill` | `:25` |  | 44 | `BeyondCompTypeWaterCubeComp` | `:47` |
| 23 | `BeyondCompTypeIntee` | `:26` |  | **45** | **`BeyondCompTypeCursorCollision`** | **`:48`** |
|  |  |  |  | 46 | `BeyondCompTypeVehicle` | `:49` |
|  |  |  |  | 47 | `BeyondCompTypeArraysize`（哨兵，无尾逗号） | `:50` |

### 1.2 值域的形状（两条必须一起读的观察）

- **空号**：值 **2** 与 **10** 没有成员。⇒ 这是「历史上有过、后来删掉」的编号留下的洞，**不是**从 0 起的稠密序列。
  一条**直接推论**：说「id 是第 N 个组件」会立刻撞上这两个洞——序号不需要留洞，**枚举才需要留洞**。
- **哨兵**：`BeyondCompTypeArraysize = 47`（`:50`）不是真组件，是「枚举尺寸/上界」标记（名即 `Array`+`size`）。
  出现 **46 个成员而最大值为 47** 不矛盾：0..47 共 48 个槽，挖掉 2/10 共两个洞 = 46。
- **计数更正**：`COMPONENT-WRITER-MINE.md:19,77` 写「47 项」；**实测 46 个成员**（`grep -cE '^\s*BeyondCompType[A-Za-z]+ = [0-9]+,'` = 45，再加无尾逗号的 `Arraysize=47`）。**以本文件为准**。

### 1.3 命名空间的双轨（别把两套名字当两件事）

反编译语料（`resolved/`）用的是**一套名字**；桥探针里钉的是**另一套**（7.1 PE metadata 的 actual 名）。
二者是**同一批成员的两套名**，探针文件自己写明了对应关系：

| actual（探针常量 71） | legacy（resolved 语料） | 作用 | 出处 |
|---|---|---|---|
| `tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq` | `LudM06iCRNk4iFkwqKIW` | 组件模型类型 | `EntityComponentProbe.cs:27`（注释 `// LudM06iCRNk4iFkwqKIW`） |
| `OgoXdqFmidJ` | `OTQiCVjSfFs` | 组件 id 字段（boxed uint） | `EntityComponentProbe.cs:28` |
| `gKyXdGplIdw` | `fydiCJQHm3O` | 组件 enabled（boxed bool） | `EntityComponentProbe.cs:29` |
| `EDuXiXtiyvl` | `mUwiSNg4POZ` | 实体→组件集合字段 | `EntityComponentProbe.cs:26` |

> 这套映射**本身**是探针文件注释里的**断言**（`EntityComponentProbe.cs:14-21` 自述：来自 pinned PE metadata dump
> `metadata-7.1.json`，sha256 `565DDA…`）。**本轮无法离线复核那份 metadata dump**（不在检索范围内），
> 故 §2 的实证链以 **resolved 语料**（legacy 名）为主体；两套名的**对齐**是 §3 真机读回要顺带证实的第一件事。

---

## 2. 判定：探针行的 `id` 是枚举值，不是实例序号

### 2.1 判定结论（先说，再说证据）

**是枚举值。** 组件行里的 `id:uint` ＝ 该组件的 `jaUof90C3Ncl5BAJri4x` 种类值，**以 uint 承载**。
它不是「该实体第几个组件」的序号。**判定依据不是"一个数字看起来像枚举"，而是一条严格的赋值方向的证据链**（§2.2）。

### 2.2 证明链（四个环节，全部 file:line）

**环节 ① 组件模型里，id 的底层存储就是那个 uint 字段**
`resolved/taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs`：
- `:12` `private t7crdXiRQQTsF520oNMA<uint> OTQiCVjSfFs;`（id，boxed uint）
- `:27-30` `[SpecialName] public t7crdXiRQQTsF520oNMA<uint> b1EiCj8P44N() { return zkBiU2ieGW3(ref OTQiCVjSfFs); }`（getter 直接返回同一字段）
- `:22/:24` `xPos`/`yPos`（boxed double）、`:33` `yYJiCpvHnUp()`（boxed bool）——一个组件＝(id:uint, enabled:bool, x:double, y:double)

**环节 ② 反序列化时，这个 uint 字段被赋成「一个 enum 值的 `(uint)` 强转」**
`resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:400`：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

- 该 `Jm6vUBlSm21` 是 **enum 型访问器**，铁证三条：
  - `wFyeWxvUrZ4ClLJlFKGm.d5t5h9vUZHeCSba2oH5p.cs:21` `private jaUof90C3Ncl5BAJri4x jsfvRa9DTEO;`（字段就是该枚举）
  - `:50-60` `public jaUof90C3Ncl5BAJri4x teJvUy0dZuF { get/set }`（属性就是该枚举）
  - `:202,266,320` 把 `Jm6vUBlSm21` 与 `jaUof90C3Ncl5BAJri4x.BeyondCompTypeNone` **直接比较**、`:451` `jsfvRa9DTEO = (jaUof90C3Ncl5BAJri4x) <wire 读入>;`（从线上读入即强转成该枚举）
- **同一处偏旁铁证**：`mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26376` 紧接着把**同一个** `Jm6vUBlSm21`
  用 `.ToString()` 写进组件的**另一个（字符串）字段**——只有 enum 才会 `.ToString()` 出成员名；一个实例序号 `.ToString()` 只会是 "0"/"1"。
- 同形赋值另见 `:26796`（来源换成另一个 payload 类型 `G9Sy1e4y5uCfXaHpH7ca.P6C0t14wz3id5usWm0Uu`，
  其 `LBD4yEvirsM` 同样是 enum 型访问器：该文件 `:67` `private jaUof90C3Ncl5BAJri4x KsT4k8ALLxr;`、`:87` `public jaUof90C3Ncl5BAJri4x giS4yvEviLK`）。

**环节 ③ 前端读行时，把这个 uint **直接强转回该枚举**当行标题**
`resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs`（组件行 VM）：
- `:77-87` `public static … eTxuuH9NkZV(n7s… P_0, … P_1, uint P_2)`：`:82` `xHRuuubNIqa = (int)P_2;`，
  `:84` `jaUof90C3Ncl5BAJri4x x = (jaUof90C3Ncl5BAJri4x)P_2;`，`:85` `… .ToString()` 作标题。
- 上溯：`resolved/yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs`（组件列表 VM）`:136` 枚举实体组件集合 `WlJiSPfnM3R()`、
  `:174/:289/:306` `list.Add(<component>.b1EiCj8P44N().Value)` 收集 id、`:238` 用该 uint 建行（调 `eTxuuH9NkZV`）。
  预制体侧同形：`resolved/LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs:158`。
- 组件编辑器自己的 key 也取自**同一字段**：`resolved/IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:161-174`
  `GetKey()`→`MJMKpdLxpLQ()`→`return <component>.b1EiCj8P44N().Value;`。

**环节 ④ 删除命令把**同一个 uint**当 `componentId` 发出**（前后端一致）
- 前端：`pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107` 发 `DeleteComponentForEditObj`，
  参数 `[ param(entityRef), param((uint)xHRuuubNIqa) ]`——`xHRuuubNIqa` 正是 `:82` 那个由 `P_2` 得来的行 id。
- 后端：`command_route` id4 `param_shape = (int32 实体id, int32 组件id)`（`COMPONENT-WRITER-MINE.md:236-238`）。
- 桥侧同一条命令的适配器：`tools/editor-bridge/Adapter/EntityComponentDelete.cs:56-57`（命令字面量）、
  `:160-174`（`List<Param>[uint(entityId), uint(componentId)]`）。

### 2.3 探针读的是不是同一字段？（闭合第 2.2 与「探针」之间的一跳）

- 探针 `EntityComponentProbe.cs:28` `ComponentIdField71 = "OgoXdqFmidJ"`（actual），注释 `// OTQiCVjSfFs`（legacy）。
- `:84` `Exact(component, ComponentIdField71, boxed.MakeGenericType(typeof(uint)))` → **直读该字段、契约是 boxed uint**。
- `:152` `id = (uint)ComponentValue(item, model.Id)`。
- ⇒ 探针行 `id` ＝ §2.2 那个 uint 字段的**原值**。**因此：探针行的 `id` ＝ 前端当枚举用的值 ＝ 删组件命令的 `componentId`**（三者同一个数）。
  > 这一条「同一字段」的闭合**依赖 §1.3 的那张 actual↔legacy 映射断言**（`OgoXdqFmidJ` ≡ `OTQiCVjSfFs`，`EntityComponentProbe.cs:28`）。**该断言离线无法独立复核**，由真机读回一并证实（§3.3）。

### 2.4 「不是实例序号」的**反证**（为什么不能是序号）

1. **赋值方向**（§2.2 环节②）：字段的值**来自一个 enum 型 wire 字段**，且另有一个字符串字段收同一值的 `.ToString()`（成员名）。序号不会有 enum 型来源，也不会 `.ToString()` 成成员名。
2. **值域的洞**（§1.2）：2 与 10 空号 + 哨兵 47。序号不需要洞，枚举才需要。
3. **同一个数被删组件命令当 key**（§2.2 环节④）：一条 `DeleteComponentForEditObj` 要能对**任意**实体稳定删掉指定**种类**的组件；若 id 是"第几个"，同实体上"第 0 个"会随增删漂移，语义不稳。
   （注：第 3 条是**设计推断**，强度低于 1、2 两条硬赋值证据；标为**弱证据**。）

### 2.5 边界（诚实标）

- 以上**全部是前端（编辑器进程）侧**的静态证据。**原生侧**把 `8` 解释成"碰撞触发器"这件事，**本轮未证**
  （`comp+0x34` 那个 `0x15` 的含义 `not_found`，与 `8` 不是同一个数，**不构成旁证**；`COMPONENT-WRITER-MINE.md:269`）。
- 「前端枚举值 ＝ 原生 `componentId` 编号空间」这一跨层等同，**唯一支点是 §2.2 环节④**（删组件命令**同时**吃前端枚举值、
  又由后端 id4 实现）。**该支点未真机验证**。若真机删组件对 `componentId=8` 无效果，则跨层等同被证伪。

---

## 3. 碰撞触发器的 id：`8`（**假设**，待真机读回）

### 3.1 假设陈述

**若** §2 成立（id 是枚举值），**则**一个挂了「碰撞触发器」组件的实体，探针读回该行的 `id` ＝ **`8`**。

- **值的来源**：`resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:12` `BeyondCompTypeCollision = 8,`。
- **标为假设的理由**：枚举成员名 `Collision` 与中文组件名「碰撞触发器」的**对齐**，本轮**没有在仓内找到一张实际的映射表**（§3.2），
  只能由**命名 + 语义**推断。**这是本假设唯一的软肋。**

### 3.2 为什么"对齐"只能靠推断（检索范围 + 负面）

- 全语料里 `BeyondCompTypeCollision` **只出现 1 次**，就是枚举定义那一行（`grep -rho 'BeyondCompType[A-Za-z]*'` 统计：`None` 25 次，**其余每个成员恰好 1 次**）。
  ⇒ **没有任何代码分支按成员名分派**（除 `None` 外），没有 `.cs` 里的「名称↔枚举」switch 可读。
- 编辑器 textmap `textmap-chs.json`（7743 条）里**没有** `BeyondCompType*` 键；`configEnum_maps` 里 `mapTitle='组件功能'` 的 **map 98 只有标题、没有条目**
  （全 textmap 内 `configEnum_maps_98_map_*` = 0 条）。组件树只有文件夹显示名（`…_folders_…_name = 碰撞触发器`，见 `_folders.txt:13` 等），**不带枚举值**。
- ⇒ **"名称→枚举值"的绑定表不在本仓的这两份语料里**（可能在游戏侧 textmap 或编辑器配置资源，未在本轮检索范围内）。
  **"搜不到"≠"不存在"**——但本文件只能到此为止。

### 3.3 可证伪判据（§3 与 §2 共用一次真机读回即可判定）

用桥已编译的只读探针 `inspect-entity-components`（`BridgeServer.cs:306`，回执行 `{id,enabled,x,y}`，`EntityComponentProbe.cs:150-156`），
对**同一个实体**在**人工点「添加通用组件 → 碰撞触发器」前 / 后**各读一次：

| 观测 | 判决 |
|---|---|
| 新增行 `id == 8` | §3 **证实**，且顺带证实 §2（id 是枚举值）与 §1.3（actual↔legacy 映射） |
| `count` **不增长**（UI 却变了） | 加组件**不落这个集合**——回头去折叠常量盲区找"加组件命令"（`COMPONENT-WRITER-MINE.md` §2.4） |
| 新增行 `id` 是**从 0 起的连号**（0/1/2…） | §2 **被证伪**——id 是**实例序号**，本文件 §2/§3 的结论作废 |
| 新增行 `id` 是**另一个合法枚举值**（≠8 但 ∈ 本表） | §2 成立、§3 证伪——成员「`Collision`」被映射到了别的东西，重查 §3.2 的绑定表 |

> 真机口径遵循 `CLAUDE.md` §四：**`ok:true` 单独不算**；本探针是**只读**，判"证"只需一次**形状正确、字段齐全**的回执，
> 不涉及落盘（`.gil` 差分是**写**侧才要的，见 `COMPONENT-OP-PROOF-PLAN.md:§2.1`）。**本文件不运行它。**

### 3.4 与 M1 的关系（一句）

M1 场景半边缺的仍是**「加组件」那条命令**（`Add*Component*` 在本轮命令面 0 命中）。本文件**不解决"加"**——
它解决的是**"读"**：一旦真机读回坐实 `8`，就等于拿到了 **"人工加完之后如何自动核对"** 的开关，
以及后续任何写法的**前置输入**（`componentId` 该传什么）。

---

## 4. 证据索引

| 论断 | 证据（file:line，均在 `.runtime/editor-catalog/resolved/` 或仓内源码） |
|---|---|
| **组件枚举 46 成员 / 值域 0..47（缺 2,10）** | `QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3,4-51` |
| `ClientTrigger=5` / **`Collision=8`** / `StuffBag=33` / `Shop=35` / `PopUp=40` / `CursorCollision=45` | 同文 `:9` / `:12` / `:36` / `:38` / `:43` / `:48` |
| 枚举**唯一定义**（无第二份） | `grep -rln "enum jaUof90C3Ncl5BAJri4x"` = 1 文件 |
| 每个成员名**仅出现 1 次**（=定义处；`None` 除外） | `grep -rho 'BeyondCompType[A-Za-z]*'` 全语料统计 |
| 组件模型：(id:uint, enabled:bool, x/y:double) | `taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:12,22,24,27,33` |
| **id 字段被赋成 `(uint)(enum 值)`**（实体侧） | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:400` |
| 同上（预制体侧 + `.ToString()` 进另一字段） | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26375,26376,26796` |
| 来源字段确为 **enum 型** | `wFyeWxvUrZ4ClLJlFKGm.d5t5h9vUZHeCSba2oH5p.cs:21,50,202,451`；`G9Sy1e4y5uCfXaHpH7ca.P6C0t14wz3id5usWm0Uu.cs:67,87` |
| 读行时 uint **强转回枚举**当标题 | `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:77-87`（`:82,:84,:85`） |
| 列表 VM 收集 id / 建行 | `yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs:136,174,238,289,306`；`LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs:158` |
| 组件编辑器 key ＝ 同一字段 | `IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:161-174` |
| 删组件把同一 uint 当 `componentId` | `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107`；后端 `command_route` id4（`COMPONENT-WRITER-MINE.md:236-238`） |
| 实体持有组件集合 / Add | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:43,65,204,587`；集合 `QAVTZKijY59YjpE1GYC0.rgfCjhijuAbCoKxWU8Lu_1.cs:17,49,81` |
| 探针读的字段与行形状 | `tools/editor-bridge/Adapter/EntityComponentProbe.cs:26-31,84,150-156` |
| 探针 actual↔legacy 映射断言（软肋） | `EntityComponentProbe.cs:14-21,24-32` |
| 桥删组件适配器（命令/参数形状） | `tools/editor-bridge/Adapter/EntityComponentDelete.cs:56-57,160-174` |
| **无"名称→枚举"绑定表**（负面 + 范围） | `textmap-chs.json`（无 `BeyondCompType*`；`configEnum_maps_98` 仅标题）；`_folders.txt`（仅显示名） |
| 原生 `comp+0x34` 常量 `0x15` 含义 not_found | `COMPONENT-WRITER-MINE.md:269` |

### 与同目录两份文件的关系

- `COMPONENT-WRITER-MINE.md`（#1）：组件写入总账（枚举、集合、删链路、三候选）。本文件是它在 **"id 是哪个数"** 这一条上的**纵深**，
  并**更正**其对枚举成员数的计数（47→46，`COMPONENT-WRITER-MINE.md:19,77`）。
- `COMPONENT-OP-PROOF-PLAN.md`（#2）：读/删探针的**真机取证计划**。本文件 §3.3 的判据就是给它那支 `inspect-entity-components`
  加了一条**判决性读数预期**（新行应为 `id=8`）。

---

*本文件由 2026-10-10 会话从 `.runtime/editor-catalog/resolved/`（Bash `grep` / `Read`，非 Grep 工具）与
`tools/editor-bridge/Adapter/` 只读整理；**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档**。
所有引用行号为本次语料实测。§2 的"id 是枚举值"是本轮**静态已证**（赋值方向 + 强转回枚举 + 同值当 commandId）；
§3 的"碰撞触发器 = 8"是**假设**，其唯一软肋是"名称↔枚举"绑定表不在本轮语料内（§3.2），
标为**待真机读回证实/证伪**（§3.3 给出四路判据）。*
