> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 模板存在哪 —— 一个货币/道具/商店模板落盘时会写进哪个容器（TEMPLATE-STORAGE）

日期：2026-10-10。**全程只读**：未连桥、未发任何 bridge/native 报文、未注入、未启动或触碰
游戏/编辑器、未起 helper、未申请 UAC、**对 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` 只
`read_bytes`，未写一个字节**。（工程纪律：`tools/beyond-save/gil_container.py:553`
`write_bytes` 是唯一的写口，本轮**未调用**。）

**数据来源（全部只读）**：
- 真实存档 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/原神/BeyondLocal/100000001/`：
  `Beyond_Local_Save_Player.gip` + `Beyond_Local_Save_Level\*.gil`（含子目录、`Temp\`、
  `UpgradeBackup\`，**全 39 个文件**）；解码器 `tools/beyond-save/gil_container.py`（逐字节）。
- 编辑器 bridge 读侧源码 `tools/editor-bridge/Adapter/EditorAdapter.cs`、
  `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs`、
  `tools/live-editor-observer/ResourceModel.cs`（静态读）。
- 真机回执 **`modelTypeCounts` 普查**：`.runtime/editor-bridge/runs/0bd72169-…/catalog-response.json`
  与 `.runtime/editor-bridge/demo/catalog-now.json`（历史回执，离线读）。
- 官方 ID 类型表逐字原文 `docs/official-docs/chapters/mhsd6lrx3voe.json:64-66`。

---

## 0. 一句话结论

1. **`.gip` 玩家档案里没有模板。** 顶层只有三个字段号 `1/2/3`，内容是「页签容器 + 18 条**关卡**
   引用 + 当前关卡 id」。18 条引用的确是一张「id + 名字」的注册表，但 **id 全是关卡 id
   （`0x40000000+`）**，不在 ID 类型表的货币(10)/道具(8)/商店(15) 任何区间里；1161 B 载荷里
   `货币/道具/商店/背包/模板` 五个词 **0 字节命中**。
2. **模板确实落盘，落在关卡 `.gil` 的 `root field 15`——而且它带名字。**
   每一个真实关卡的 `field 15` 是一条**带 id、带名字**的类型化资产记录表。本机真实装着一条
   **type 11 背包模板**：`id=1119879169`、`name="背包模板"`（`1073741831.gil` 文件偏移
   `37 736` 起，逐字节见 §4）。**这是全盘唯一一处「模板＝名字 + id」的序列化落点。**
3. **type 8/10/15（道具/货币/商店）在本机一个实例都没有**——用户从没在编辑器 UI 里建过。
   所以「它们是否也走 field 15」本机**无法仅凭现有字节断定**，只能说 **field 15 是全机唯一
   见到的「类型化资产表」，是最小、最可证伪的落点候选**。
4. **编辑器侧没有任何一个资源 Kind 装模板。** 桥的 Adapter **只观测两个 Kind：6（节点定义）和
   9（节点图）**（唯一赋值点 `EditorAdapter.cs:166`），全工程 `.Kind==N` 只出现 6/9。编辑器注册表
   里另有 ~25 个 Kind（既有台账），**没有一个**是货币/道具/商店模板；最接近的 Kind 7 是
   **实体预制/元件模板**，不是配置 ID 类模板。

---

## 1. `.gip` 玩家档案 —— 逐字段实测

命令：`gil_container.decode_container` + `parse_profile`（`gil_container.py:86,363`）。


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 1.1 「看起来像注册表」的那张表 = 18 条**关卡**引用（不是模板表）

`field 2` 每条 = `{f1:<id>, f2:<name>, f3:<timestamp>, f5:<flag>}`（`parse_profile` 读 f1/f2，
`gil_container.py:363-387`）。18 条逐条解出的 `id + name`（`profile.levels`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- 这是一张**货真价实的「id + 名字」注册表**——但它是**项目（关卡）清单**，id 全部 `0x40000000+`
  （`LEVEL_ID_BASE`，`gil_container.py:49`），**没有一条落在** ID 类型表的 8/10/15 区间。
- `field 1`（422 B）= 页签容器（`parse_tabs`，`gil_container.py:390`）：9 个页签，成员全是指向上述
  关卡 id 的 `{group, level_id}` 对。
- `field 3` = 当前关卡指针（varint `1073741842`）。

### 1.2 模板词一个没有

对整段 1185 B 直查 UTF-8 字节：`货币`/`道具`/`商店`/`背包`/`模板`/`currency`/`item` **各 0 命中**。
（`gil_container.py:11` 的模块自述亦一致：「the player profile -- the project registry」。）

**判定**：`.gip` 是「项目注册表」，**不是资产内容表**。模板不在 `.gip`。

---

## 2. 全盘扫描 `.gil` + `.gip`：有没有「entries 带名字 + 带 8/10/15 区间的 id」的表

扫描范围：`…/BeyondLocal/` 下**全部 39 个 `.gil`/`.gip`**（含 3 个 UID 目录、`Temp\`、`UpgradeBackup\`）。
方法：`decode_container` → 递归 `parse_fields`，只认 **wire type 0（真 varint）** 的 id
（踩过的坑：把 4 字节 float 当整数扫会把 `0x42000000/0x42800000/…` 读成 32.0/64.0/96.0，
全落进这几个区间，产生上千假阳性；见 `TEMPLATE-CREATION-MINE.md:194-201`）。

ID 类型表区间（`docs/official-docs/chapters/mhsd6lrx3voe.json:66` 逐字）：
`8 普通道具/装备道具 = 1107296256~1111490559`、`10 资源货币 = 1115684864~1119879167`、
`15 商店模板 = 1136656384~1140850687`（另 `11 道具背包 = 1119879168~1124073471`，作最近类比）。

### 2.1 结果 (a)：全盘落在 8/10/15/11 区间的真 varint —— 只有 1 个值，`1119879169`（type 11）

58 次命中，**全部是同一个 id `1119879169`**，只出现在**两个结构位置**（每个真实关卡各一对，
`Temp\`/`UpgradeBackup\` 是副本，占位关卡无 `field 15`）：

| 位置（字段路径） | 含义 | 类型 |
|---|---|---|
| `6.1.3.5.2`（`field 6` → 条目 → `f3` → `f5` → `f2`） | **目录指针** | type 11 背包 |
| `15.1.1`（`field 15` → 条目 → `f1`） | **对象自身的 id** | type 11 背包 |

**`type 8 / 10 / 15` 的 id：全盘 0 个实例。**（不是"没搜到"——是 39 个文件里**根本不存在**该区间的值。）

### 2.2 结果 (b)：同时含「可打印名字 + 上述区间 id」的 message —— 只有 `field 6` 的目录条目

扫描「子树里既有可打印 UTF-8 名字、又有区间内 id」的 message，命中 29 次，**路径全部是 `6.1.3`**，
即 `field 6` 目录条目的子段 `{f1:<名字>, f3:2, f5:{f1:<group>, f2:1119879169}}`。
逐字节证据（`1073741831.gil`，`field 6` 第 22 条 = 指向背包模板的那条）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- **名字在这一层是「页签/文件夹」名（`未分类页签`），而不是模板自己的名字**——`field 6` 是
  **资源树目录**（文件夹 + 叶子指针），不是模板内容表。
- 该目录里其它条目指向别的对象：`默认`→`1186988033`(env/27)、`玩家模版`→`1086324737`、
  `默认分类`→`320001/320002`、以及一批 `group 200` 的物件 id——**没有一条指向 8/10/15**。

### 2.3 结果 (c)：真正的模板内容表 `root field 15` —— **带名字**（本轮新证据）

`field 15` 的条目形状（`1073741831.gil`，条目 `id=1119879169`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


逐条目解出（全部真实关卡；占位关卡 `1073741826/1827/1836/1837` **无** `field 15`）：

| id | `id>>22-256` | `f2` | 名字 | 出现在哪些关卡 |
|---|---|---|---|---|
| `1119879169` | **11** 背包 | 12 | **背包模板** | **全部 14 个真实关卡** |
| `1186988033` | **27** 环境 | 26 | **环境配置** | **全部 14 个真实关卡** |
| `1090519041` | **4** 职业 | 4 | **自定义职业** | `1828/1830/1840/1841/1842` |
| `1094713345` | **5** 成长曲线 | 5 | **自定义成长曲线** | `1828/1830/1840/1841/1842` |

> `f2` 与 `id>>22-256` 对 type 4/5 相等，对 type 11（12≠11）、27（26≠27）差 1——本轮**不下结论**
> `f2` 的语义，只报原始值。**能确定的是：`field 15` 的条目 = 「id + 名字 + 若干组件块」**，与
> `field 6`（目录，名字在 `f3.f1`）是**两张不同的表**：`field 6` 是树/指针，`field 15` 是内容本体。

**小结（§2）**：全盘**唯一**「模板 = 名字 + id」的落点是 **`root field 15`**；它现在只装着
type 11 背包（+27/4/5 等本机自动生成项），**没有任何 type 8/10/15 实例**。
所以"表里带 8/10/15 的 id"这一问，答案是**本机不存在该表的实例**，而不是"表不存在"。

---

## 3. 编辑器侧：有没有哪个资源 Kind 装模板？

### 3.1 Adapter 观测到的 Kind —— **恰好两个：6 和 9**

- 全工程**唯一**的 Kind 赋值点：`EditorAdapter.cs:166`
  `int resourceKind = name == B(IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C) ? 6 : 9;`
- 唯一的过滤点：`EditorAdapter.cs:160`
  `if (name != <节点定义模型> && name != <节点图模型>) continue;`——**除了节点定义(6)与图(9)，
  注册表遍历里的一切模型都被跳过**（其余类型只进 `EditorAdapter.cs:143` 的 `modelTypeCounts` 计数）。
- 唯一的白名单（独立只读工具）：`tools/live-editor-observer/ResourceModel.cs:46-50`，**恰好两条**
  `(IpVb…, 6, "U0oKESVcL9L")` / `(cwoW1eKm…, 9, "fLGKbbHeoYG")`；自测 `SelfTest.cs:203` 断言
  `Kinds.Length == 2`。

**⇒ 桥采到的 `resources` 列表里只有 Kind 6 与 Kind 9，没有任何其它 Kind；模板不在其中。**
（注：实体(Kind 8)与预制(Kind 7)是**旁路**——`EditorAdapter.cs:144-158` 按**类型名字符串**收集，
**没被赋 Kind**，也不进 `resources.Where(r=>r.Kind==…)` 的任何分支。）

### 3.2 `modelTypeCounts` 真机普查（16 个模型类）—— 校正既有文档

既有 `EDITOR-REGISTRY-MINE.md:200-203` 写「`modelTypeCounts` 的完整键值对**没有任何回执落盘**」。
本轮**找到了落盘副本**：`.runtime/editor-bridge/runs/0bd72169-1a38-4f62-8f04-577133c49d0c/catalog-response.json`
（BOM，用 `utf-8-sig` 读）与 `.runtime/editor-bridge/demo/catalog-now.json`。最新一份：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- 上面 16 个 FullName 是**当前 build 的真名**（与 `EditorBindingProfile.Generated.cs:413-567`
  的 `legacy→actual` 映射一致：`aXUR…`=节点定义、`E8xv…`=图、`Lhus…`=实体、`zDWu…`=预制）。
- **`resources` 只覆盖其中 2 个**（`aXUR…`/`E8xv…`）；另外 11 个模型类**桥完全不枚举**，只留计数。
- 这 11 个未枚举类**计数里没有任何模板**——但这不构成证明：**模板实例为 0 时根本不会出现在 census 里**。
  census 只证明"当前注册表里没有模板实例"，不证明"没有模板模型类"。

### 3.3 编辑器全 Kind 台账里，哪个可能是模板？—— 没有

既有台账（`EDITOR-REGISTRY-MINE.md` §3，静态扫描 12375 个反编译 `.cs` 的 `RG6YRkRQud0()` 返回点）
列出**至少 25 个 Kind（编号 1、5–27）**。逐个对照，**没有任何一个**是货币/道具/商店模板：

- **Kind 7**（`nWLQffit…hRwGGsitgmhQZo9c1XOp`）= **实体预制/元件模板**——是"实体摆放"的模板，
  不是配置 ID（货币/道具/商店）的模板。
- **Kind 6 / 9** = 节点定义 / 节点图。
- Kind 1/10 = 文件夹；Kind 14 = 蓝图变量；Kind 15 = 外部资产；Kind 16 = 自定义角色状态；
  Kind 23 = 标签(Tag)；Kind 11 及其子类 = costload 系列；其余 12/13/17–22/24–27 字段全混淆、未识别。
- 编号 2/3/4 **没有任何模型返回**（只在比较/构造里出现）。

**⇒「货币/道具/商店模板」在编辑器注册表里没有对应的 Kind 落点**；官方 ID 类型表的
type 8/10/15 是**配置 ID 空间**，与编辑器资源 Kind 是**两套编号**（`EDITOR-REGISTRY-MINE.md` §1.1 已辨）。

---

## 4. 判决：模板「能读在哪」/「能写在哪」——带字节

### 4.1 能读吗 —— **能。`root field 15` 是可读的，且带名字。**

`1073741831.gil`（`50361 B`；容器头 20 B + 载荷 50337 B + 尾 4 B）逐字节：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


同一个 id 还有一处**目录指针**（`field 6`）出现在 文件偏移 **17 308**（路径 `6.1.3.5.2`）。

读取方式**已存在、已只读验证**：`gil_container.parse_fields` / `parse_level`（本文件所有结论都由它
现场解出）。**所以：模板（至少 type 11 背包）确实序列化在一个我们读得到的容器里——关卡 `.gil`
的 `root field 15`。**

### 4.2 能写吗 —— **没有已证路径；且缺 8/10/15 的 schema，无法凭空构造。**

- **没有现成的写原语**：桥 op 面（计数由 `tools/gameplan/tests/test_doctrine.py` 钉住）里 `item/shop/currency` 全 0 命中；原生动作集 6 项
  （`inspect/create/save/create-batch/reopen-current/creature-create`）**无一条建模板**；
  `command_route` 38 行逐行核过无建模板路由。这些都是既有负结论，本轮复核一致。
- **字节层面唯一可能的写口**是「往 `field 15` 追加一条记录」，但：(a) `gil_container.py` 的
  `encode_fields` 能字节精确重编码，`write_bytes`（`:553`）是唯一文件写口——**但没有任何调用方
  把改过的 `field 15` 写回存档**（与地形 `field 7` 同构的"能读不能持久化写"边界）；(b) 更硬的
  障碍是**没有 type 8/10/15 的实例可照抄**——它们的组件块 schema（`f4` 各 kind 的布局）在本机
  **一个样本都没有**，无法构造合法字节。**能改字段值 ≠ 能构造一个不存在的类型。**
- 唯一能把一条货币模板写进 `field 15` 的**已知合法途径**是**人在编辑器 UI 里新建**（系统菜单 →
  【货币与背包】→ 货币页签；官方入口 `mhsd6lrx3voe.json` / `mhn4bsi5lb58`），再 `scene_cli save`
  落盘。这正是 `TEMPLATE-CREATION-MINE.md:220-234` 的判别实验。

### 4.3 三层分开（不得混称）

| 层 | 结论 |
|---|---|
| **文档写了什么** | 有货币(10)/道具(8)/背包(11)/商店(15) 四类**配置 ID**（`mhsd6lrx3voe.json:66`）；入口在系统菜单。零执行。 |
| **工具/源码能做什么** | **读**：`gil_container` 能解 `field 15` 的 id 与名字（本文件现场跑通）。**写**：桥/原生/CLI **无建模板 op**；`write_bytes` 只吃路径、无调用方写 `field 15`。 |
| **真机验证过什么** | 本节零执行。`field 15` 的结构与名字是**磁盘真实字节**读出的 `static` 级证据；"这些字段就是模板表"是**推断**，靠上面那个 UI 实验裁决。 |

---

## 5. 复现命令（全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 6. 边界与未做（诚实负结论）

| 未找到 / 未能证 | 搜过哪里 / 说明 |
|---|---|
| **任何 type 8/10/15 实例** | 39 个 `.gil`/`.gip` 全盘，**只有 wire type 0 的真 varint** 扫描 → 0 个。这是**用户行为结果**（没建过），**不是**"系统不支持"。 |
| `.gip` 里任何模板表 | 顶层只有 `field 1/2/3`；`货币/道具/商店/背包/模板` 五词 0 命中。 |
| 编辑器里装货币/道具/商店模板的 Kind | 桥只观测 6/9；全 Kind 台账 25 个里无对应项；最接近的 Kind 7 是实体预制。 |
| 建模板的写原语 | 桥 op / 原生 6 动作 / `command_route` 38 行 / `scene_cli` 6 动作——全部无。 |
| 往 `field 15` 写一条的代码 | `gil_container.write_bytes:553` 无人对 `field 15` 调用；无 8/10/15 schema 样本可构造。 |

**未找到 ≠ 不存在**：以上"没有"均为**本次检索范围内**。模板**能读**的落点已定为 `root field 15`
（含名字），**能否手写**取决于 §4.2 的判别实验——本文件不越界下结论。
