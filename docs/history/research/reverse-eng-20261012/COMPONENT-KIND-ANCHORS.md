> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 组件 kind 的经验锚点 — 从 19 个真实存档反查（COMPONENT-KIND-ANCHORS）

**产出日期**：2026-10-12。
**口径**：**纯离线、纯只读**。未连桥、未发报文、未重启 helper、未请求 UAC、未执行任何 native 调用、
**未写任何存档**（`C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` 只读字节）、未触碰游戏/编辑器、未读任何图片/PDF。

**三层分标**（`CLAUDE.md` §一.3）：`文档写了什么` / `工具能做什么` / `真机验证过什么` 严格分开。
本文件的 **OBSERVED** 只指「本次从真实字节/回执直接读出并复核」；**INFERRED** 指「由已证事实推进、未直接读到」。

**命令（复现）**：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

（脚本只读；产物落 `.runtime/scratch/kind-anchors/`。）

---

## 0. 一句话判决

1. **这一波要的「目标五件的经验锚点」在用户真实数据里不存在** ——
   `Collision(8) / ClientTrigger(5) / Intee(23) / StuffBag(33) / Shop(35)` 在 **19 个真实 `.gil`、1339 条实体**里
   **一条都没有**；在 **2729 个官方预制体**里也 **一条都没有**。⇒ **用户从没在存档实体上摆过这五个组件。**
2. **但本波拿到的东西比预期强**：把「存档组件号 == `jaUof90C3Ncl5BAJri4x` 枚举」这一条**从未证变成了已证**——
   **存档实体第 7 组（entry field 7）的 kind 就是枚举值**，证据是 **1189 条可 join 实体里 1119 条** 其 field-7 集合
   **逐条全等**于该实体 `ref` id 所指**预制体独立解出的组件集**（`PREFAB-CENSUS-V2.json`，该表本身 192/192 对拍过编辑器实读）。
3. **并且发现实读里本来就有一张 16 点的 id↔名对照表**（不是只有 43/44 两点）——
   `.runtime/editor-bridge/runs/{8c515535,ce2f82fd,c980a8f9}/prefab-fields-page-response.json` 的组件块
   **同时**带 `OgoXdqFmidJ`（数值 id）与 `Sf4Xdtq9Squ`（`BeyondCompType*` 名字串）；16 条全部与枚举逐字相符。
4. **存档的组件编码是「三组」的**：`field 7` = 枚举组件空间（已证）；`field 5`、`field 6` 是**另两套号空间**
   （`field5` 有 111/110/82 等 > 枚举最大值 47 的值；`field6` 含 2，而枚举里 2 是空号）。⇒ **不能拿枚举值去 field 5/6 里查**。

---

## 1. 正控（先证明读器读得到已知的东西，再信任何 0）

| 正控项 | 期望 | 实测 |
|---|---|---|
| transform ＝ entry `field 6 > wrapper kind 1 > field 11` | 每条实体都有 | **1339 / 1339 实体**均有（`TRANSFORM_GROUP=6`/`TRANSFORM_KIND=1`，`entity_geometry.py:130-132`） |
| 关卡实体 id `1094713345` + tag `10003004` | 存在 | **存在**（`1073741831.gil` entry0，`field2={1:10003004,2:1}`） |
| transform 载荷形状 | field3 三 float ≈1.0 | `0a00 1200 1a0f 0d0000803f 150000803f 1d0000803f a81f ffffffff0f` = (1.0,1.0,1.0) ✓ |
| 读器端到端（本波新增正控） | field-7 集合 == 预制体组件集 | **1119 / 1189 逐条全等**（§3） |

---

## 2. 存档全量普查（19 个 `.gil`、1339 条实体）

范围：`.../BeyondLocal/*/Beyond_Local_Save_Level/**/*.gil` = **19 个**（18 个不同关卡 id，含 `UpgradeBackup/1073741835.gil`；
`Temp/` 18 个镜像未计入）。另两个 uid 目录 `100559494 / 343269915` 为空。
**读器复用** `tools/beyond-save/{gil_container.py,entity_geometry.py}`（未新写解析器）。

**实体数（每文件）**：`1073741825`(45) `1826`(0) `1827`(0) `1828`(11) `1829`(12) `1830`(11) `1831`(45) `1832`(22)
`1833`(17) `1834`(18) `1835`(235) `1836`(0) `1837`(0) `1838`(11) `1839`(111) `1840`(75) `1841`(479) `1842`(12) `Upgrade/1835`(235)。
（1826/1827/1836/1837 是 0 实体的占位关卡。）

### 2.1 (group, kind) → 承载实体数 全直方图


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**不同 (group,kind) 对 = 53 个。经验集合很小。**
每实体签名只有 **8 种**；主签名（1098 条）＝ `(5,1)(5,13)(5,14)(5,19)(5,38)(5,40)(5,52)(5,61)(5,62)(5,111)(6,1..22 中的 44 个)(7,1)(7,3)(7,6)(7,14)(7,18)(7,19)`。

### 2.2 「哪一组是枚举组件空间」——三条判定

| 组 | 值域 | 是否枚举空间 | 判据 |
|---|---|---|---|
| **7** | 1,3,6,14,18,19,21,22,26,32,40,42 | **是（OBSERVED）** | 全部 ∈ 枚举；且逐实体与预制体组件集全等（§3） |
| 5 | 1,3,5,13,14,19,20,30,31,32,33,34,38,40,47,52,61,62,65,80,81,82,110,111 | **否（OBSERVED）** | 含 **52/61/62/65/80/81/82/110/111**（皆 > 枚举最大值 47；实测直方图内无 `93`） |
| 6 | 1,2,3,4,5,6,7,8,11,12,15,16,17,19,20,21,22 | **否（OBSERVED）** | 含 **2**——枚举 2 是空号（`jaUof90C3Ncl5BAJri4x.cs` 值域 0..47 挖掉 2 与 10） |

**注**：`field 7` 里 `kind` 与载荷字段恒满足「载荷字段＝2」（本样本 g7 全为 `field 2`），
与 `field 6` 的「kind+10」规则不同——是另一套 schema，不是同一张表的别名。

---

## 3. 决定性 join：存档 field-7 集合 vs 预制体组件集（anchor，OBSERVED）

对每条实体取 `entry field 2 (ref).f1` 作预制体 id，查 `PREFAB-CENSUS-V2.json` 的 `prefabs[id].componentIds`，
与该实体 **field 7 的 kind 集合** 比对：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**逐条全等样本**（存档 g7 → 预制体组件名）：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

⇒ **存档第 7 组的 kind ＝ `jaUof90C3Ncl5BAJri4x` 枚举值**，且这条锚**独立于编辑器**（纯字节 vs 纯字节）。
`21` 这条尤其关键：编辑器实读会**剔掉 21（TempAttachPoint）**，而**存档字节里带着它**——
说明存档保留的是「字节层组件集」，与 `PREFAB-CENSUS-V2.md §2` 的结论一致。

---

## 4. 编辑器实读的 16 点 id↔名锚（anchor，OBSERVED）

`.runtime/editor-bridge/runs/{8c515535-…,ce2f82fd-…,c980a8f9-…}/prefab-fields-page-response.json`
（194 条带 `content` 的预制体，共 1196 个组件块）。每个组件块 `CF9E4JXdL1Cq4xrMUnCq` 同时给出
`OgoXdqFmidJ`（→ 数值 id）与 `Sf4Xdtq9Squ`（→ `BeyondCompType*` 名串）。解析结果：

| id | 名 | 次数 | | id | 名 | 次数 |
|---:|---|---:|---|---:|---|---:|
| 1 | `BeyondCompTypeCustomValue` | 194 | | 19 | `BeyondCompTypeHitbox` | 157 |
| 3 | `BeyondCompTypeTimer` | 194 | | 20 | `BeyondCompTypeBulletPattern` | 1 |
| 6 | `BeyondCompTypeEffect` | 191 | | 22 | `BeyondCompTypeCustomSkill` | 2 |
| 11 | `BeyondCompTypeBulletMove` | 1 | | 26 | `BeyondCompTypeEnmity` | 32 |
| 12 | `BeyondCompTypeHitDetection` | 1 | | 32 | `BeyondCompTypeMinimapMark` | 2 |
| 14 | `BeyondCompTypeRoleStatus` | 190 | | 40 | `BeyondCompTypePopUp` | 2 |
| 18 | `BeyondCompTypeCombat` | 191 | | 42 | `BeyondCompTypeMonsterAiComp` | 32 |
| 43 | `BeyondCompTypeWaterfallComp` | 3 | | 44 | `BeyondCompTypeWaterCubeComp` | 3 |

**16/16 与枚举文件逐字相符。** 这是本波新挖到的、比过去「只有 43/44 两点」强得多的**跨层对照表**。
（此前 `COLLISION-COMPONENT-ID.md` §1.3 记的 43↔Waterfall 只是这张表的两个点。）
目标五件的名字**在这 194 条实读里 0 次出现**——与 §5 的预制体普查一致。

---

## 5. 每个目标组件的三格表

| 组件 | (a) 前端枚举 | (b) 存档 group 记录 | (c) 原生 resolver |
|---|---|---|---|
| **Collision** | **8** — OBSERVED | **未出现** — OBSERVED(负) | **8** — INFERRED（未读） |
| **ClientTrigger** | **5** — OBSERVED | **未出现** — OBSERVED(负) | **5** — INFERRED（未读） |
| **Intee** | **23** — OBSERVED | **未出现** — OBSERVED(负) | **23** — INFERRED（未读） |
| **StuffBag** | **33**（`EquipStuffBag=34`） — OBSERVED | **未出现** — OBSERVED(负) | **33/34** — INFERRED（未读） |
| **Shop** | **35** — OBSERVED | **未出现** — OBSERVED(负) | **35** — INFERRED（未读） |

- **(a) 为 OBSERVED 的背书**：五件的枚举值**直接读自枚举文件** `.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-51`（46 成员）
  **外加** `resolved-565dda11/zn1Mv9ZOCIYgNdSVMyWb.QhNByxZONrdCQv6vIMYe.cs`（同值域、名字混淆不同）⇒ **两修订逐值一致**。
  **注意（B2）**：§4 的 16 点实读**不含这五件**——它背书的是「**存档 kind 空间 == 枚举空间**」对**确曾出现**的那些 kind 成立
  （1/3/6/11/12/14/18/19/20/22/26/32/40/42/43/44），**不**为五件的枚举号背书（五件无实读样本）。
- **(b) 为「未出现」的背书**：§2.1 全直方图 —— `field 7` 只出现 `{1,3,6,14,18,19,21,22,26,32,40,42}`，无 5/8/23/33/35；
  `field 5/6` 不是枚举空间（§2.2），在其里出现的 33/34/5 **不能**计作 StuffBag/EquipStuffBag/ClientTrigger。
  ⇒ 「用户从没在存档实体上摆过这五个」。
- **(c) 为 INFERRED 的背书**：原生侧**唯一**锚点是 `43/44`（create-loop 过滤 `lea eax,[rdx-0x2b];cmp eax,1;ja`
  `0x836364f` 配 water-prefab id + §4 的 43/44 名对照）。**其余 44 个成员的原生号从未被直接读到**；
  本波**未执行任何 native 调用**，故 (c) 对五件仍是**假设**（「原生号 == 枚举号」，由 43/44 外推）。

### 5.1 目标族在预制体侧的独立负结论（复核，OBSERVED）

`PREFAB-CENSUS-V2.json → prefabs[*].componentIds` 全扫 **2729** 条：
**窄族** `{5,8,17,23,24,28,33,34,35,41,45}`（= `ClientTrigger/Collision/Intee/StuffBag/EquipStuffBag/Shop/Obstacle/Option/MpAction/Talk/CursorCollision`）
命中数 **全部为 0**（与 `PREFAB-COMPONENT-CENSUS-V2.md §5` 一致）。

**范围澄清（B3）**：生成该表的脚本 `.runtime/scratch/prefab_component_census_v2.py:73` 的 `TARGET` 是**更宽的 14 值集**
`{5,8,17,23,24,28,33,34,35,36,37,40,41,45}`，比上列**窄族多 `36/37/40`**。这三值里 **`36`(DropGather) 与 `40`(PopUp) 确实存在**：
`10007002 → 含 36`、`1000000 → 含 40`（本表逐条实测；`40` 亦见 §4 实读）。它们**不算进目标族**，因为目标族是
`PREFAB-COMPONENT-CENSUS-V2.md §5` **逐字列出**的那一组（碰撞/客户端触发器/交互件/背包/商店/选项/额外碰撞/
MpAction/Talk/CursorCollision）——**DropGather(拾取)/PopUp(悬浮交互页)/DropStuff 不在该字面里**。
⇒ **这个「零」是「窄族」的零，不是脚本宽 `TARGET` 的零。**

同读者**能找到** 43/44：`10005103..10005106..10005108` 六个水预制体带 `WaterfallComp/WaterCubeComp` ⇒ **不是读不到**。
且这六个水预制体 id **不在任何存档的 ref 集合**里 ⇒ 存档侧也拿不到 43/44 的落地样本。

### 5.2 `inspect-entity-components` 真机回执（OBSERVED，但无锚）

`.runtime/editor-bridge/runs/33152ae3-…/inspect-entity-components-response.json`（2026-10-10 14:25）：
`entityId=1086324737`(`默认模板`)、`componentCount=0`、`components=[]`、
`componentIdSpace="editor-enum-value-or-native-index-UNVERIFIED"`。
⇒ 该 op **确实跑过一次**（`CLAUDE.md` §五原写「尚未真机运行」，本轮已按此回执就地更正），但**目标是编辑器内生空模板**，读数 0，**不构成锚点**。

---

## 6. 结论与后果

1. **对 M1 的直接后果**：靠「扫用户存档找已有碰撞/触发器实体的 id」这条路，**在本机数据上是死的**——
   用户**从没摆过**这五个组件中的任何一个。要拿它们的号，只能：
   (i) 人工在编辑器里摆一个再让编辑器自己保存（唯一合法写入路径），或
   (ii) 原生侧把 resolver 的号直接读出来（本波禁做）。
2. **但组件号空间问题已被本波证死**：存档 `field 7` 的 kind **就是枚举值**——
   这给了「人工摆完之后如何自动核对」的开关：**读回实体的 `field 7`，看有没有 8/5/23/33/35**。
3. **不要再把 `field 5 / field 6` 的 kind 当枚举**（它们含 >46 与 2 号空号）。三套号空间必须分开标。

---

## 7. 证据索引

| 论断 | 证据 |
|---|---|
| 19 个存档、1339 条实体、全直方图 | `.runtime/scratch/kind-anchors/census.py` → `census-leveldirs.json` |
| transform 正控 1339/1339；id 1094713345 tag 10003004 | 同上（`eg.read_entity_records`） |
| 存档 field-7 == 预制体组件集 1119/1189 | `.runtime/scratch/kind-anchors/join_prefab.py` + `.runtime/scratch/PREFAB-CENSUS-V2.json` |
| 枚举 46 成员 / 值域 0..47 缺 2,10 | `.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-51`；`resolved-565dda11/zn1Mv9ZOCIYgNdSVMyWb.QhNByxZONrdCQv6vIMYe.cs`（同值） |
| 16 点 id↔名实读对照（含 43/44；**不含目标五件**——只证「存档空间==枚举空间」） | `.runtime/editor-bridge/runs/{8c515535,ce2f82fd,c980a8f9}/prefab-fields-page-response.json` |
| 预制体侧**窄族** `{5,8,17,23,24,28,33,34,35,41,45}` 0 命中（脚本宽 `TARGET` 额外含 36/37/40，其中 36/40 存在）；43/44 可读到 | `PREFAB-CENSUS-V2.json → prefabs[*].componentIds`；`PREFAB-COMPONENT-CENSUS-V2.md §5`；`.runtime/scratch/prefab_component_census_v2.py:73` |
| 原生 43/44 过滤点 | `0x836364f` `lea eax,[rdx-0x2b];cmp eax,1;ja`（引 `CLAUDE.md` / 本波任务书，本轮未复验二进制） |
| 组件容器/枚举写入链（上下文） | `docs/gameplan/COMPONENT-DATA-SIDE.md`；`docs/research/reverse-eng-20261010/COMPONENT-WRITER-MINE.md` |
| `inspect-entity-components` 唯一回执（空） | `.runtime/editor-bridge/runs/33152ae3-b835-48dd-85d3-c621ba4b6659/inspect-entity-components-response.json` |

*本文件由 2026-10-12 会话从 19 个真实 `.gil`（只读字节）、编辑器实读回执与预制体普查产物只读整理；
未实现、未运行、未连桥、未触碰游戏/编辑器、未写任何存档、未读任何图片/PDF。*
