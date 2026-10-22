> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 预制体组件路径 — PREFAB-COMPONENT-PATH

> 任务：#4「组件能不能加在 **预制体** 上，而实体加不了？」— 只读逆向，未连桥、未发报文、未触碰游戏/编辑器。
> 全部证据＝本次 checkout 静态复核（`resolved/` 用 Bash `grep -rI`，非 Grep 工具）+ 三个真实 `.gil` 的**只读**解码 + 两个 sqlite 库的**只读**查询。
> 相关前作：`COMPONENT-WRITER-MINE.md`、`COLLISION-COMPONENT-ID.md`、`COLLISION-TRIGGER-MINE.md`、`PREFAB-FIELDS-MINE.md`。
>
> ⚠️ **2026-10-11 更正（偏移 + 地址）**：本文件引用的组件模型结论已被 `docs/research/reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md` 取代——组件容器是 **`[entity+0x68]`**（**不是** `[entity+0x48]`）、kind 是 **`[comp+0x34]`**（**不是** `[comp+0x30]`）；文内旧 RVA（如 `0x914ccd0`、`0xcb64140`）在当前映像里**已过期**，须按对账文件 §5 重导。

---

## 0. 一句话结论

**预制体不是新路。** 预制体（`hRwGGsitgmhQZo9c1XOp`，模型类型 7）与实体（`AooSwxiSm6Ktx99ovmnr`，模型类型 8）
在**组件这件事上完全对称**：同一个集合类、同一个泛型 `Add`、同一个「从序列化节点工厂装配」的加载路径，
命令面**两边都只有删、都没有加**。所谓「预制体侧有 ADD/SET 组件命令」**不存在**（§3 证据）。

**但 LEADS 的直觉是对的一半**，而且比预制体这条更值钱：**组件是「数据」，不是「命令」**——
它随加载对象一起到达（§1 已逐点坐实）。顺这条线挖下去，唯一可走的方向是**写组件数据**，不是找 `AddComponent`。

---

## 1. `X66ijdVvJ0k` 是什么，谁在调用，喂的是什么

### 1.1 它不是「加组件」，是**泛型可观察列表的 Add**

- 定义：`QAVTZKijY59YjpE1GYC0.rgfCjhijuAbCoKxWU8Lu_1.cs:81`
  `public void X66ijdVvJ0k(D7gB5Rij7xaTF2353qTs item, bool notify = true)`
- 它转调私有 `PFDijPKoc4S`（同文件 `:97`），后者就一行核心动作 **`XnBijZjw7wg.Add(item)`（`:99`）** + `SetOwner` + 通知。
- 类形参约束 `where T : class, VRaoFJiu2iHkZCSuRqqy` ⇒ 这个 `Add` **被约 20 个不同集合复用**（组件只是其中之一）。

### 1.2 全部调用点按「喂给哪个集合」分组（定义处除外，共 **121** 处）

`grep -rh "X66ijdVvJ0k" resolved/ | grep -o '\-> [A-Za-z0-9_.]*::[A-Za-z0-9_]*' | sort | uniq -c`：

| 次数 | 集合访问器（delegate 目标） | 是否组件集合 |
|---:|---|---|
| 47 | `Nx9TXsKK52JgF1iQGmtH.JVhTwtKizlScEvUHNJeZ::RU3KKBHFSHq` | 否 |
| 19 | `s0gCx5K7DdTgRPKNulO5.t19rKpK7dET0ExODuUkx::h7RKYmhWFuV` | 否 |
| 8 | `XIWfCxifBq7ZsOB6l7jb.BPJF3Qiftf6vSiTCBDvP::GL7ifwIKSTH` | 否 |
| 7 / 4 / 4 / 3 / 2 / 1 / 1 | `IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C::{QaBKEDwK65V, vyQKELdhJSm, cBPKEP6lYtm, FX1KElYva8D, pQSKE85urm1, fOSKEFCajGG}` | 否（6 个不同访问器） |
| 4 | `eFXMNAKYenvXvJUHIPks.QYEfwuKYyL4ajuDQ0mUq::P3TKxxSEchm` | 否 |
| 3 | `p79lZFKxQlIQ1LYdUvKL.EGFgbSKxW7MtKMOH1yVe::JoxKxBg36KZ` | 否 |
| 2 | `eFwIefiyuoKqF5Xvj0lt.vZll0FiyKKPTI3JUkFjF::zD5ieOCCneq` | 否 |
| 2 | `Vp6KURKAIOnPmkaYQW46.uvKHMgKAkmLAIGV0AeoZ::dqsK34EoGqJ` | 否 |
| **2** | **`Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr::WlJiSPfnM3R`** | **是 — 实体组件** |
| **1** | **`nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp::YlJitG20qEt`** | **是 — 预制体组件** |
| 1 / 1 / 1 / 1 / 1 | `xbRyH8EjCIh1ehbMI6x3.Q…::DPpEjyy38Gb`、`cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH::pSJKOe1FuCR`、`R0hYCriIomYmuTUWixks.DUEQQAiI98SiYdZu0a1F::YOriIUBVHaO`、`Ede0efKaNi3LAXjeVLc4.B6XVDdKaRjyLF53GQ4fZ::lCEKmEjdkAg`、`BcxVcSKYG8sGLuEWSS7w.SflukeKYn5beMgfLAOIj::k22KY2KRs1N` | 否 |

⇒ **只有 3 个调用点在写「组件集合」**：实体 2 处、预制体 1 处。

### 1.3 三个组件 Add 点，逐个看「谁喂它」

| # | 调用点 | 所在方法（同一文件向上找最近的方法声明） | 喂给它的东西 |
|---|---|---|---|
| A | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:587` | `internal void ynEiSE9hUrh(ODUiR8vROJUfpkA4NTYP P_0, hBss0OnM1Xt6VxBD93o P_1)`（声明 `:371`） | 枚举 `fIyfirhNlkBOSTKNMhJr(P_0, ODUi::avWvR710hyW)`（＝节点 `ODUi…` 的**字段 90** 重复字段，`:563`/`:581`），逐条 `d5t5h9vUZHeCSba2oH5p` → 加成 `LudM06iCRNk4iFkwqKIW` |
| B | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26353` | `internal static AooSwxiSm6Ktx99ovmnr FYqiJ6iSLaF(ODUiR8vROJUfpkA4NTYP P_0, hBss0OnM1Xt6VxBD93o P_1)`（声明 `:26105`） | 同一个 `d5t5h9vUZHeCSba2oH5p` 枚举（`:26341` `current`），字段 8/16 直接落到组件 id/enabled |
| C | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26788` | `internal static hRwGGsitgmhQZo9c1XOp fAoiJf7HfZ1(vPeYZtvUQsPdvj80hG4R P_0, hLtKhbJZ2oT5NIdgfNI P_1, bool P_2)`（声明 `:26539`） | 枚举 `P_0` 上的 `P6C0t14wz3id5usWm0Uu` 项（`:26760` 一带），逐条建 `LudM06iCRNk4iFkwqKIW` 再 Add |

**三点全部是「反序列化 / 工厂装配」路径**（把已存在的节点对象变成运行期对象）。
**没有任何一个组件 Add 点位于用户命令处理函数**（对照：命令处理函数都是 `public void ModifyPrefabName(...)` 那种 `BrjMRrl2xRXv5aqZQkDJ.…Ikci0qkvMZX` 下行派发壳，见 §3）。

> 同文件里还有 `pdhpSOW0BMLsF7uY24hU(collection, true)`（实体 `:644`，helper `:977`）＝**清空**同一集合（`Clear`），不是加。

---

## 2. 顺带坐实的：组件的**线格式**（这是 LEADS 真正的收获）

`d5t5h9vUZHeCSba2oH5p` 是一条**完整 protobuf 消息**（`wFyeWxvUrZ4ClLJlFKGm.d5t5h9vUZHeCSba2oH5p.cs`，含 `WriteTo`/`CalculateSize`/`MergeFrom`），字段：

| 字段号 | 类型 | 语义（证据） |
|---:|---|---|
| 8 | bool | enabled。`WriteTo` 写 tag 8；`MergeFrom` 读 8（`:2765` 一带） |
| 16 | enum `jaUof90C3Ncl5BAJri4x` | **组件类型**。`WriteTo` 写 tag 16；`MergeFrom` 读 16 |
| 26 | msg `P6C0t14wz3id5usWm0Uu` | 组件**载荷**。`WriteTo` 写 tag 26 |

组件类型枚举已命名：`QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-51`，46 值（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2），含
`ClientTrigger=5`(`:9`)、**`Collision=8`(`:12`)**、`Intee=23`、`Option=17`、`StuffBag=33`、`EquipStuffBag=34`、**`Shop=35`(`:38`)**
（详见 `COLLISION-COMPONENT-ID.md`）。

承载它的节点：`xAhJuPvRbkvTxdwyetBb.ODUiR8vROJUfpkA4NTYP.cs`
— 字段 8(uint) / 18(msg) / **90 = repeated `d5…`**（注册于 `:536` `b4LODY5X4O(90u, …)`，getter `FYivRYq3Ifk` `:73`）/ 98(repeated)。
`ODUi…` 本身又被三个上层重复字段承载：`…HVkZTa0yGF0CODX6XWqN.cs:558`（字段 26）、
`…J4NoWT0d9Ywne2MhiRgf.cs:2142`（字段 34）、`…ThV5EpatzB958vsYkFLK.cs:640`（字段 18）。

**这就是「预制体也能带组件」的机制来源**：预制体工厂 `fAoiJf7HfZ1` 从 `vPeYZtvUQsPdvj80hG4R` 节点取组件载荷，
实体工厂从 `ODUiR8vROJUfpkA4NTYP` 节点取组件记录 —— **两个节点类型、同一套组件概念、同为 protobuf、同为加载期装配**。

### 2.1 一个必须标清的**负结论**：这套 protobuf **不是 `.gil` 的 schema**

我用 `tools/beyond-save/gil_container.py` 的 schema-free walker 对**三个真实 `.gil`**（`1073741825 / 1073741830 / 1073741831`，只读副本）
做了**递归到 6 层**的扫描，找「字段 16 是 varint 且字段 26 是 message」的 `d5` 签名：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


⇒ **`.gil` 里不存在 `d5` 的 `{8,16,26}` 布局**。`.gil` 用的是**另一套编码**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

（实测 `1073741825.gil`：entry0 field5 kinds={1,111,19}、field6 kinds={1,3,4,7}、field7 kinds={1,3}；
此结构本就记录在 `tools/beyond-save/entity_geometry.py:123-135`（`COMPONENT_GROUPS=(5,6,7)`），
且该文件 `:104` 自认「只解出了 transform（group 6 / kind 1 / field 11），其余 30 余 `(group,kind)` 只按位置记录」。）

**所以要诚实地说：现在有「两套组件编码」，尚未打通**：
- 编辑器 protobuf 家族（`ODUi` / `d5`）：`{type-enum, payload}`
- `.gil` 实体记录（`entry` 字段 5/6/7）：`{kind, payloadField}`

---

## 3. 前端/后端命令面：`*Prefab*` 全清单 + 有没有写组件

### 3.1 字符串表里的 9 条 `*Prefab*`

`grep -o '"[A-Za-z0-9_]*[Pp]refab[A-Za-z0-9_]*"' .runtime/editor-catalog/string-table.json`：
`AddInstructionGraphForPrefab`、`ApplyPrefabInstanceChange`、`DeleteComponentForPrefab`、`DeletePrefab`、
`FocusPrefabInstance`、`ModifyFactionForPrefab`、`ModifyPrefabName`、`ModifyPrefabTag`、`RequestPrefabInstance`。

### 3.2 每条在反编译语料里的落点（file:line）＋「是否写组件」

| 命令 | `resolved/` 落点（file:line） | 语义 | 写组件？ |
|---|---|---|---|
| `DeleteComponentForEditObj` | `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107` | 实体删组件 | **删**（id4） |
| `DeleteComponentForPrefab` | `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:152` | 预制体删组件 | **删**（id5，与 id4 共用实现 `0x914ccd0`） |
| `RequestPrefabInstance` | `pmZ1POuub8FEemimgKKq…:127`；`VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:184, :2337`；`zDwVnSKeJok3DNsJf1Lg.VaR86gKerBXhRbru9366.cs:526`；`FOV9AWu5QBsMPf0Rwuiu.NQ6Rasu5Wb3lL511Sp4j.cs:796` | 请求预制实例 | 否（id25） |
| `DeletePrefab` | `VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:512` | 删预制体 | 否（id7） |
| `FocusPrefabInstance` | `VJ8TQEKBWBew1bEgiZHx…:171`；`zDwVnSKeJok3DNsJf1Lg…:527`；`FOV9AWu5QBsMPf0Rwuiu…:756` | 聚焦 | 否（id15） |
| `ModifyFactionForPrefab` | `VwMawhKGHsdXfkO51YfP.HDt4hxKGbds2L9ACUaAM.cs:359` | 改阵营 | 否（id21） |
| `ModifyPrefabName` | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:15041`（方法 `public void ModifyPrefabName(uint prefabId, string name)`，声明 `:15039`） | 改名 | 否（id22） |
| `ModifyPrefabTag` | `kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0.cs:2194` | 改标签（增/删同命令） | 否（id23） |
| `AddInstructionGraphForPrefab` | **`resolved/` 里 0 命中**（仅存在于字符串表） | 挂**节点图**（非组件） | 否（id2） |
| `ApplyPrefabInstanceChange` | **`resolved/` 里 0 命中**（仅存在于字符串表） | 应用实例变更（语义未定） | 否（id3） |

（id 号＝`docs/research/beyondeditor-backend/db/backend.db` → `command_route`，本次只读逐行读出，
全表 38 行；上面 id 与表内 id 一一对应。）

### 3.3 三处「0 命中」复核（Bash `grep -rI`，非 Grep 工具）

- `.runtime/editor-catalog/resolved/`（**12375** 个 `.cs`）：`AddComponent` / `CreateComponent` / `AttachComponent` / `InsertComponent` / `SetComponent` / `AddComponentForPrefab` **全部 0 命中**。
- `string-table.json`：`*Component*` 只有 `DeleteComponentForEditObj` / `DeleteComponentForPrefab` / 5 个 `Template_ComponentEdit_*` / `vmComponents` —— **无任何 Add/Set**。
- `docs/research/beyondeditor-frontend/db/frontend.db` → `operation`（全表 **44** 行）：含 Prefab/Component 的仅 8 行，**无一条 `Add*Component`**。
- `docs/research/beyondeditor-backend/db/backend.db` → `command_route`（全表 **38** 行）：无 `Add*Component`。

**边界诚实**：`AddInstructionGraphForPrefab` / `ApplyPrefabInstanceChange` 是**字符串表还原名**，不在前端 44 条里
⇒ 「44 条 / 38 条里没有 AddComponent」是**范围结论**，不是「全集不存在」（同 `COMPONENT-WRITER-MINE.md:243`）。
且 `AddInstructionGraphForEditObj`（id1）的处理器描述明确写着「**取实体第 3 号组件**（读 `[entity+0x48]`——**非组件容器**；真容器 = `entity+0x68`）→ 装配节点图」
⇒ **节点图是「挂在某个组件上的」**；这解释了为什么「加组件」卡住会连带影响图那半边（留作线索，本文不展开）。

---

## 4. 判决：预制体不是新路（附不对称核对）

**答：否。** 预制体加组件**并非可能**，而实体加组件不可能 —— 两边**同样不可能**：

| 维度 | 实体 `AooSwxiSm6Ktx99ovmnr`（类型 8） | 预制体 `hRwGGsitgmhQZo9c1XOp`（类型 7） |
|---|---|---|
| 组件集合字段 | `mUwiSNg4POZ : rgfCjhijuAbCoKxWU8Lu<LudM06iCRNk4iFkwqKIW>`（`:43`） | `sTwiBAJuFW2 : rgfCjhijuAbCoKxWU8Lu<LudM06iCRNk4iFkwqKIW>`（`:42`） |
| 集合访问器 | `WlJiSPfnM3R()`（`:204`） | `YlJitG20qEt()`（`:205`） |
| 集合类 / Add | 同一 `rgfCjhijuAbCoKxWU8Lu` / 同一 `X66ijdVvJ0k` | 同左 |
| 加载期装配 | `ynEiSE9hUrh(ODUi…, …)`（`:371`）＋静态工厂 `FYqiJ6iSLaF`（`mguq…:26105`） | 静态工厂 `fAoiJf7HfZ1(vPeYZ…, …)`（`mguq…:26539`） |
| 命令面 | 删：`DeleteComponentForEditObj`(id4) | 删：`DeleteComponentForPrefab`(id5)，与 id4 **共用实现** `0x914ccd0` |
| 加命令 | **无** | **无** |

两边的**唯一**区别是**查找入口不同**（实体表 `0x12a767b0` / 预制体表 `0x12a764e0`），
而删除**汇到同一实现** —— 这是「对称」的硬证据，不是「预制体多一条路」。

这条判决与 CLAUDE.md §六(a) 的既有结论一致：**组件边界的不对称方向是「读得懂 / 删得掉 / 加不了」**，
**不**是「实体加不了但预制体能加」。**LEADS 提出的预制体假设，证据不支持。**

---

## 5. 真正该带走的 lead ＋ 最小可判定实验

### 5.1 Lead（比预制体更值钱）

**组件是数据，不是命令。** 已坐实链条：
`saved node (ODUi… field 90 repeated)` → `d5t5h9vUZHeCSba2oH5p {f8 enabled, f16 type, f26 payload}` → `LudM06iCRNk4iFkwqKIW`（运行期组件）。
组件类型是**有名字的 46 值枚举**（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2）（Collision=8 / ClientTrigger=5 / StuffBag=33 / Shop=35 / Intee=23 …）。

⇒ 通往 M1/M4/M5「加组件」的路**不是命令面**，而是：**把一条组件记录写进承载它的数据里**。
有两条候选写入面，**都还没有写入者**：
1. **`.gil` 字节面**：`entry` 字段 5/6/7（`{1:kind, N:payload}`）。这是本工程已有 `gil_container.py` 逐字节回环能力的自然延伸。
2. **编辑器内存面**：`ODUi…field90` 的 `repeated d5…`（但需要找到「谁把 ODUi 写回」）。

### 5.2 最小可判定实验（先做 A，只读；B 需用户手动开编辑器一次）

**A（只读，无风险）：`.gil` 的 (group,kind) 与命名枚举**是否构成固定映射。**
- 输入：任一带实体组件的真实 `.gil` 副本（`.runtime/beyond-save/backups/**/*.gil`）。
- 动作：`gil_container.parse_fields` → root field 5 → 每个 entry 的字段 5/6/7 → 打印全部 `(group, kind, payloadField)` 去重集合。
- 判定：若 `kind` 集合能与 `jaUof90C3Ncl5BAJri4x` 的 46 值（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2）（或其子集）建立**固定**对应，则 `.gil` 的 kind 就是组件类型 id，
  M1/M4/M5 的「加组件」可走 §5.1 路线 1；若**无固定对应**（如出现 111 这种枚举里没有的值），则 kind 是另一套 id 空间，
  必须先解出 `kind → type` 表，本文的字节路线才成立。
- 我已有的实测反例样本：`entry0` field5 kinds 含 **111**（枚举 46 值里没有 111；原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2）⇒ **倾向「另一套 id 空间」**，
  故实验 A 大概率给出「需要再挖一张 kind 表」的结论 —— 这本身就是有价值的下一步地图。

**B（需用户手动开一次编辑器，判定「.gil 是不是组件权威存储」）：**
- 在一个副本上，向某 entry 的字段 5 追加一个包装 `{1: <A 得到的候选 kind>, <kind+10>: <payload>}`，
  用 `gil_container.encode_fields` 重编码，**字节差分**确认只动了预期区域。
- 让编辑器加载该副本，看组件面板（`Template_ComponentEdit_ComponentPanel`）是否多出一行。
- 判定：多出一行 ⇒ `.gil` 是权威存储，字节路线成立；不多 ⇒ 组件权威存储是编辑器模型（§5.1 路线 2），
  `.gil` 只是镜像。**这一步是分岔点，必须做了才能继续。**

> 两条都**不碰游戏进程、不发 bridge 报文**；B 的「加载」由用户手动执行，且只在**副本**上做。

---

## 6. 复现命令（本次全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**边界复核（本报告相关的全部绝对声明，均已实测）**
- 「预制体侧没有加组件命令」→ 由 §3.2 九条逐条 + §3.3 四处 0 命中支持；**不**由「搜不到」单独支持（§3.3 明标范围）。
- 「`d5` 的 `{8,16,26}` 不在 `.gil` 里」→ 由三文件递归扫描（§2.1）**实测**，非推断。
- 「实体与预制体组件路径对称」→ 由 §4 表逐格 file:line 支持。
