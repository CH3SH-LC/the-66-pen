> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #2 挖 — 建编辑器资产模板的原生调用（货币类型10 / 道具类型8 / 背包11 / 商店15）

**产出日期**：2026-10-10
**数据来源（全部只读）**：
- `docs/research/beyondeditor-backend/db/backend.db` 表 `command_route`（38 行，逐行读过）；
- 真实存档 `C:\Users\PUBLIC_USER\AppData\LocalLow\miHoYo\原神\BeyondLocal\100000001\`
  的 `Beyond_Local_Save_Player.gip` 与 14 个真实关卡的 `Beyond_Local_Save_Level\*.gil`（19 个文件，含副本）
  （用 `tools/beyond-save/gil_container.py` 逐字节解，**只 `read_bytes`，未写任何字节**）；
- `tools/editor-bridge/`、`tools/game-executor/`（命令面扫描）；
- `docs/official-docs/chapters/mhsd6lrx3voe.json`（ID 类型表的逐字原文）。

**本文件只读不写**：除本文件外未修改任何东西；未起 helper、未连 bridge、未发任何报文、未碰游戏/编辑器。

---

## 0. 一句话结论

1. **没有一条路由能建模板。** `command_route` 38 行逐行读过：全部是 `*EditObj* / *Prefab* / Focus* /
   DoExport|DoImport / *DebugLog / PlayMusic|PlaySoundEffect / 3 条 PCG`——**没有任何一行**是「新建货币 /
   新建道具 / 新建背包 / 新建商店 / 建模板」。这条与既有负结论（`M2M3-currency-item.md:130,181`、
   `M4M5-inventory-shop.md:79`）一致，本轮用 SQL 复核。
2. **模板不在 `.gip` 玩家档案里。** 真实 profile 顶层只有 3 个字段号（`field 1`/`2`/`3`），
   全部内容是「页签表 + 18 条关卡引用 + 当前关卡 id」；整个 1161 B 载荷里
   `货币 / 道具 / 商店 / 背包` 四个词 **0 字节命中**。**⇒ 模板不可能存在 profile。**
3. **新证据（本轮最大收获）：模板最可能在关卡 `.gil` 里，落点候选是 `root field 15`。**
   每一个真实关卡的 `.gil` 在 `root field 15` 都带一张**按「类型化 ID」编号的资产记录表**，
   目前装着：**默认背包模板（type 11 `道具背包`，id `1119879169`）** 与 **环境对象（type 27，id `1186988033`）**，
   有的关卡还带 type 4 `职业`、type 5「关卡」区间对象。
   **⇒ 至少「背包」这一类模板（type 11）是确实被序列化到磁盘的**，就在 field 15。
   而 type 8/10/15（道具/货币/商店）在本机**一个都没有**——因为用户从没在编辑器 UI 里建过。
4. **最小下一步实验**：*人在编辑器 UI 里新建 **1 个货币模板**（系统菜单 →【货币与背包】→ 货币页签）→
   `scene_cli save` 落盘 → 重扫该关卡 field 15 / field 6*。
   若出现一条 id 落在 type-10 区间（`1115684864~1119879167`）的新 field-15 条目 ⇒ **模板确实序列化在 field 15**，
   「建模板」这一能力就有一个**可写的字节落点**；若 field 15 纹丝不动 ⇒
   **模板只活在编辑器进程内存 / 服务端，本地不落**，负结论成立。这是一次「非黑即白」的判别实验，成本 ≈ 一次 UI 点击 + 一次 save。

---

## 1. `command_route` —— 38 行逐行核过，没有任何一条建模板

`command_route` 共 **38 行**（`sqlite3`：`SELECT count(*) FROM command_route` = 38）。按语义分族：

| 族 | 行数 | 命令 |
|---|---|---|
| 节点图类 | 2 | `AddInstructionGraphForEditObj`、`AddInstructionGraphForPrefab` |
| 删除类 | 4 | `DeleteComponentForEditObj`、`DeleteComponentForPrefab`、`DeleteEditObj`、`DeletePrefab` |
| 聚焦类 | 9 | `FocusBeyondTileMap`、`FocusCharacter`、`FocusDropGather`、`FocusEditObj`、`FocusEsp`、`FocusLight`、`FocusLocalBullet`、`FocusPrefabInstance`、`FocusScreenshot` |
| 改名/标签/阵营/套组/请求 | 8 | `ModifyEditObjName`、`ModifyEditobjTag`、`ModifyFactionForEditObj`、`ModifyFactionForPrefab`、`ModifyPrefabName`、`ModifyPrefabTag`、`ModifySuite`、`RequestPrefabInstance` |
| 变更应用 | 1 | `ApplyPrefabInstanceChange` |
| 面板转发 | 1 | `JumpCombatSetting` |
| 导入导出 / 调试日志 | 7 | `DoExport`、`DoImport`、`DeleteDebugLog`、`ImportAllDebugLog`、`ImportDebugLog`、`ImportPerformanceReport`、`RefreshExistDebugLogReport` |
| 无落点 | 6 | `EndLoadAllDebugLog`、`PlayMusic`、`PlaySoundEffect`、`ModifyPCGInstanceName`、`DeletePCGInstance`、`FocusPCGInstance` |

（逐行取自 `SELECT id,command,service,route_status,classification,confidence FROM command_route`；
命令全集与 `docs/research/reverse-eng-20261010/COMMAND-ROUTE-MAP.md` 一致。）

**判定**：38 行里，`Modify*` 家族只有 `Name/Tag/Faction/Suite`（无 transform、无模板）；`Add*` 只对
**节点图**；导入导出是 `.gia` 文件；其余是焦点/删除/调试/音频/PCG。
**没有任何一条的名字、服务或分类与「模板 / 货币 / 道具 / 背包 / 商店 / 新建」相关。** 这是本轮的第一手 SQL 复核。

### ⚠️ 这条负结论的**边界**（必须写明，否则会过度概括）

- `command_route` 的 36 条业务候选名，来自**前端编辑器反编译语料**；而这批语料的界面面
  **是「节点图编辑器 + 场景实体 + 导入导出 + 调试 + 音频 + PCG」**——见
  `docs/research/beyondeditor-user-operations/db/userops.db` 表 `user_operation`（92 条）与
  `ui_template`（49 条，**全是 WPF `Template_*` 控件模板**，不是货币/道具模板）。
- 而官方文档说模板入口在**系统菜单**（`mhn4bsi5lb58`：29 项管理工具，含「商店模板管理」）与
  【货币与背包】。**该「系统菜单」在前端逆向语料里 0 命中**：
  `grep -rn "系统菜单" docs/research/beyondeditor-user-operations docs/research/beyondeditor-frontend` → **0 行**。
- **⇒ 严格表述**：「38 条后端路由 + 已枚举的前端命令/操作面里没有建模板的任何一条」，
  而**这个面本身不含系统菜单的模板面板**。所以这既证明了「现成的命令面没有」，也指明了
  **要补的洞**：**系统菜单（货币与背包 / 商店模板管理）这一整块前端 UI 从未被逆向**。
  这与 `docs/editor-catalog/UI-TEXT-INVENTORY.md:519-528` 的自述一致——它断言「背包/商店的证据全是节点名、
  不是编辑器面板」，`M4M5-inventory-shop.md:114` 已把该断言判为**漏检**（官方原文有 `新建商店模板` 按钮）。

---

## 2. 存档文件：模板住在 `.gip` 还是 `.gil`？

### 2.1 `.gip` 玩家档案 —— **模板不在这里**（实测）

用 `tools/beyond-save/gil_container.py`（`decode_container` + `parse_fields`，`gil_container.py:86,176`）
读真实 `Beyond_Local_Save_Player.gip`（1185 B，容器 subtype=1＝player profile，`gil_container.py:46`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- 18 条 `field 2` 逐条解出 `{level_id, name, timestamp}`（`parse_profile` `gil_container.py:363`），
  例：`1073741825 自定义页签_1_存档`、`1073741831 newdemo_存档`、`1073741842 自定义页签_5_存档`。
- `field 1`（422 B）是页签容器：子项 `#1 varint=8`、`#2 len=396`（10 条 `field 4` 页签）、`#3`＝字符串 `未分类页签`。
- **整段 1161 B 载荷里 `货币`/`道具`/`商店`/`背包` 四个 UTF-8 词全部 0 命中**（Python `in` 直查）。

**⇒ profile 的顶层字段号只有 `1/2/3` 三种，没有任何字段像是模板表。**
profile 是「项目注册表」（页签 + 关卡清单 + 当前关卡指针），**不是**资产内容表。
这与 `gil_container.py:11-12` 的模块文档自述一致（「the player profile -- the project registry」）。

### 2.2 `.gil` 关卡文件 —— **有一个类型化资产表 `root field 15`（本轮新证据）**

全部真实关卡 `.gil`（14 个不同关卡 id，19 个文件含 `1073741835` 的副本）的**顶层字段号 41~46 个**（占位关卡只有 6~9 个）。
逐字段逐字节走一遍后，定位到一张**按类型化 ID 编号的资产记录表**：`root field 15`。

**结构**（`1073741831.gil`，`root15` len 2708）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**每条目的 id 与其类型**（类型＝`(id >> 22) - 256`，与官方 ID 表区间吻合，
区间出处 `docs/official-docs/chapters/mhsd6lrx3voe.json:66`）：

| id | 类型号 | 官方类型名 | 出现在哪些关卡 |
|---|---|---|---|
| `1119879169` | **11** | `道具背包` | **每一个真实关卡**（默认背包模板） |
| `1186988033` | 27 | `环境` | **每一个真实关卡** |
| `1090519041` | 4 | `职业` | `1828/1830/1840/1841/1842` |
| `1094713345` | 5 | （实体表 `5 = 关卡` 区间首+1） | `1828/1830/1840/1841/1842` |

- 覆盖：`root field 15` 在**全部 14 个真实关卡都存在**；4 个占位关卡（`1073741826/1827/1836/1837`，
  79~95 B）**没有** field 15（与 `entity_geometry.py:100-103` 的「占位关卡只带 1,2,34,39,40,41,42」一致）。
- **type 8/10/15（道具/货币/商店）在** 全部真实关卡 + profile 里 **一个都没有**——本机的 `root field 15`
  只装着自动生成的默认资产（背包 + 环境），因为用户从没建过道具/货币/商店模板。

### 2.3 与 field 15 配套的 `root field 6`＝**项目资源树目录**（指向 field 15 的 id）

`root field 6`（`1073741831.gil`：33 条；`1073741841.gil`：42 条）是一张**目录表**，
每条 `{1:<条目 id>, 2:{...}, 3:{1:<名字>, 3:2, 5:{1:<group>, 2:<被引用对象 id>}}}`：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**⇒ 一个对象要能被编辑器引用，会在两处出现：`root field 6`（目录条目 + 指向 id）与
`root field 15`（对象内容）。** 这是本轮能找到的、**唯一一处「编辑器资产被序列化到磁盘」**的证据链。

---

## 3. 全仓 grep：ID 类型号（10/8/11/15）与模板术语

### 3.1 `tools/editor-bridge` + `tools/game-executor`（本工程真正的写入面）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- **桥派发操作**（`grep -c 'case "' tools/editor-bridge/ManagedBridge/BridgeServer.cs` 的条数见 tools/gameplan/tests/test_doctrine.py，
  `switch (op)` 在 `BridgeServer.cs:255`）；逐族核对 `case` 名：`create-*` 全是**建节点图**（`create-calibration-graph`
  `create-audit-graph` … `create-test-graph`），**无一条建模板/货币/道具/商店**。
- **原生动作集 6 项**：`NATIVE_ACTIONS = ("inspect","create","save","create-batch","reopen-current","creature-create")`
  （`tools/editor-bridge/elevated-request.py:280`）——**没有任何模板动作**。
- **`scene_cli.py` 动作面**：`inspect/create/creature-create/create-batch/save/reopen-current`（`M2M3-currency-item.md:107`）——同样没有。

### 3.2 ID 类型号区间常量（全仓）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


命中的**只有两类**，都不是「建模板的代码」：

1. **文档/语料**：`docs/official-docs/chapters/mhsd6lrx3voe.json:64-66` 等（ID 类型表逐字原文）。
2. **demo 常量**：`tools/gameplan/golden.py:435`、`cli.py:4`、`tests/*`——把 `currency_id=1115684864`、
   `crop_id/food_id=1120000001/1120000002` 当**占位配置ID**写进图的 `int` 常量。

**⚠️ 两个必须点破的口径陷阱**（写了会误导后来人）：

- `tools/gameplan/paramtypes.py:29` 的 `CONFIG_ID = 20` 是**节点端口的数据类型码 20**（图契约里的参数类型），
  **不是** ID 类型表里的「10 = 资源货币」。二者是两套编号，勿混。
- `golden.py:435` 的 `currency_id = 1115684864` **恰好等于 type-10 区间的下界**（`资源货币` 区间
  `1115684864~1119879167` 的首值），而 `crop_id/food_id = 1120000001/2` 落在 **type-11 `道具背包`** 区间
  （`1119879168~1124073471`）——**不是** type-8 道具区间（`1107296256~1111490559`）。
  ⇒ demo 里这些「配置ID」是**照区间首值取的占位符**，磁盘上**不存在**对应模板实例。
  **这正是「图里的 货币配置ID / 道具配置ID 是悬空引用」的字节级佐证。**

### 3.3 一条「会骗人」的扫描（记录下来省得下次踩）

第一版我写了个递归扫描：把 `.gil` 里**所有 4 字节值**当成整数，看是否落在 type 8/10/11/15 区间。
结果 `1073741841.gil` 报出 **1079 个「命中」**——**全是假阳性**。原因：
四个区间下界 `0x42000000/0x42800000/0x42C00000/0x43C00000` 作为 IEEE754 float 分别是
**32.0 / 64.0 / 96.0 / 384.0**——**任意坐标浮点都会落进去**。
**⇒ 只有 `wire type 0`（真 varint）的扫描才可信**。收窄后，全机只剩 **2 个真命中**：
`1119879169`（默认背包），见 §2.2。这条必须写进方法学，否则后来人会拿浮点当 ID 用。

---

## 4. 模板到底存哪 —— 判决 + 最小下一步实验

### 4.1 判决

| 位置 | 结论 | 证据 |
|---|---|---|
| `.gip` 玩家档案 | **不在**（实测） | 顶层只有 `field 1/2/3`；1161 B 里 `货币/道具/商店/背包` 0 命中 |
| `.gil` `root field 15` | **最强候选**（部分证实） | 默认**背包模板 type 11**（`1119879169`）+ 环境 type 27 **在全部 14 个真实关卡序列化在此**；type 8/10/15 因「无人建过」而缺席 |
| `.gil` `root field 6` | 配套**目录** | 条目 17 以 `group 3800` 指向 field 15 的背包 id |
| 编辑器进程内存 / 服务端 | 未能排除 | 桥改编辑器、native save 写游戏进程（`CLAUDE.md §二`）；本地只有这四类文件（`Beyond_Debug_Log/`、`Beyond_Local_Save_Level/`、`Beyond_Local_Save_Player.gip`、`Temp/`），无独立模板文件 |

**一句话**：**「背包」这类模板确实被序列化到了磁盘的 `root field 15`**（不是「从不落盘」）；
而「货币/道具/商店」模板在本机**尚不存在实例**，所以**无法仅凭现有字节断定它们也走 field 15**——
只能说 **field 15 是本机唯一见到的「类型化编辑器资产表」，是最小、最可证伪的落点候选。**

### 4.2 最小下一步实验（非黑即白，一次 UI 点击 + 一次 save）

1. **人在编辑器 UI 里新建 1 个货币模板**：系统菜单 →【货币与背包】→ 货币页签 →「新建货币」
   （入口逐字见 `docs/official-docs/chapters/mh2cr30yeak0` / `mhn4bsi5lb58`；这是**唯一**已知的合法建模板途径）。
2. `scene_cli save` 让它落盘（native save 会把未保存的一切落盘，见工程记忆 `native-save-persists-everything-unsaved`）。
3. **离线重扫两个落点**（脚本即 §2 的 field-15 / field-6 walker）：
   - 该关卡 `root field 15` 是否**新增**一条 id ∈ `1115684864~1119879167`（type 10）的条目？
   - `root field 6` 是否**新增**一条目录条目、`f3.5.2` 指向那个新 id？
4. **判别**：
   - **出现新条目** ⇒ 模板序列化在 `.gil root field 15`。随后「建模板原生调用」的目标就具体化为
     **「谁在 field 15 追加一条记录」**——可继续挖桥/原生写的反射符号或 native 写调用。
   - **field 15 纹丝不动** ⇒ 模板只在编辑器内存/服务端，本地不落；
     「只经由编辑器 UI 创建、在我们能看到的地方从不序列化」这句**可以照写**（这条是干净负结论）。

> **更省的一次**：若用户手上**已有**任何建过货币/道具/商店模板的存档，第 1、2 步可省，直接跑第 3 步。

### 4.3 若要继续挖「原生调用」（判别实验为「落点存在」时）

- 目标符号：前端 `beyondEditObj*`/`beyondData*` 服务里处理「新建模板」的那条命令（**当前语料里 0 命中**，
  但 `docs/research/beyondeditor-backend/db/backend.db` 的 `backend_gap` #3 明写
  「服务表有 7 个注册点（`0xa224da0`），本轮只对上 2 个」——**另外 5 个分发器未定位**）。
- 最可能的入口：**重新逆向「系统菜单」这一整块前端 UI**（本工程唯一未覆盖的前端面板），
  从中读出「新建货币」按钮真正派发的命令名，再回到 `commands` 哈希扫描里查落点。

---

## 5. 三层标注（严格分开，不得混称）

- **文档写了什么**：官方有货币（type 10）、道具（type 8）、背包（type 11）、商店（type 15）四类**配置ID**，
  区间见 `mhsd6lrx3voe.json:66`；入口都在系统菜单的【货币与背包】/【商店模板管理】；
  商店有逐字按钮「新建商店模板」（`mhi9s7isvp50.json:62`）。**这层零执行。**
- **工具/源码能做什么**：桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）（`BridgeServer.cs:255`，逐族核对无模板）、原生 **6** 动作
  （`elevated-request.py:280`）、`scene_cli` 6 动作——**没有一项建模板**。
  能做的：`entity.create`（按坐标 + 任意 uint32 templateId）、节点图 `add/wire/set`。**这层是读源码 + 静态枚举。**
- **真机验证过什么**：**本轮为零执行**（除只读读盘）。**未**启动/连接游戏或编辑器、**未**发报文、
  **未**写任何存档字节。§2 的 field-15/field-6 结构是**从磁盘真实字节读出的 `static` 级证据**，
  但「这些字段真的就是模板表」是**推断**，靠 §4.2 的实验裁决。

---

## 6. 本轮未找到的 / 诚实的负结论（写明搜过哪里、用什么命令）

| 未找到 | 搜过哪里 / 命令 |
|---|---|
| `command_route` 里任何建模板/货币/道具/商店的路由 | `sqlite3` 读全部 38 行（`SELECT id,command,service,route_status,classification FROM command_route`）→ 无 |
| profile 里任何模板表 | `gil_container.parse_fields` 顶层只有 `field 1/2/3`；`货币|道具|商店|背包` 四词 0 命中 |
| 本机任何 type 8/10/15 的已建实例 | 全部真实 `.gil` + profile 的**真 varint**递归扫描（`wire type 0`）→ 只有 `1119879169`(11)/`1186988033`(27)/`1090519041`(4)/`1094713345`(5) |
| 桥/CLI/原生里任何模板写入 op | `grep` 中文词（源码 0 命中）+ 逐族核对 case 全表（见 tools/gameplan/tests/test_doctrine.py）+ `NATIVE_ACTIONS` 6 项 |
| 「系统菜单 / 货币与背包 / 商店模板管理」的前端入口 | `grep -rn "系统菜单" docs/research/beyondeditor-user-operations docs/research/beyondeditor-frontend` → **0**（**该面板从未被逆向**） |
| 官方文档里「货币/道具模板**存哪**」 | 官方 218 章只讲 UI 里怎么点，**不给本地字段/格式**（`mhsd6lrx3voe.json:99` 自述「不给写盘格式」） |

**未找到 ≠ 不存在**：以上「没有」均为**本次检索范围内**。
「type 8/10/15 本机缺席」是**真实的用户行为结果**（没建过），**不是**「系统不支持」。
**「系统菜单面板未被逆向」是本轮唯一新暴露的、可继续推进的洞**——它同时解释了
「为什么命令面里没有建模板的入口」：**因为那一整块 UI 根本不在已逆向的语料里。**
