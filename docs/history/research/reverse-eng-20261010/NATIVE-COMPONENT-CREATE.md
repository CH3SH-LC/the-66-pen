> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #6 挖 — 原生侧：删除链旁边有没有一个「组件创建」函数（NATIVE-COMPONENT-CREATE）

> # ⛔ 已作废 / SUPERSEDED（2026-10-11 复核）—— 容器偏移与地址**均不可据以工作**
> **唯一事实源**：`docs/research/reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`。
> - **容器偏移错**：本文件写「组件容器 = `[entity+0x48]`」——**错**。正确是 **`[entity+0x68]`**（指针列表，步长 8）。
>   `[entity+0x48]` 是**另一结构**（`0x10aa6800` 的按 key 映射访问器），**不是**组件容器。下文凡「**组件容器**」的**偏移**已就地改为 `+0x68`；**例外**：**逐字引用的旧汇编**（如 `0x10aa6800.asm` 的 `mov rdi,[rdi+0x48]`）**保留原字节**（它们是旧二进制的引用，改动即伪造），只在身旁标注它**不是**组件容器。（残留的 `component+0x30` 字样是**编辑器侧 `0x1182cea0` 按编号 walk 的旧记号**，**不是**游戏侧 kind 字段，已就地标注。）
> - **kind 字段错**：本文件写 `[comp+0x30]`（kind）——**错**。正确是 **`[comp+0x34]`**；`comp[+0x30]` 是 byte（enabled 0/1），永不 == 0x15。下文凡「kind / 组件种类字段」的偏移已就地改为 `+0x34`（残留的 `component+0x30` 见上条，是编辑器侧 walk 的旧记号，已就地标注）。
> - **地址全过期**：本文件所有 RVA 来自**更新前**的 `YuanShen.exe`（431 MB / 2026-09-22 建库）；当前映像是 **445,006,744 B / 2026-09-23**。
>   已证 `0x914de40`、`0xcb64140`、`0x10abeb40`、`0x10ac50a0`、`0x102d4750`、`0x10aa6800`、`0x914ccd0` 在**当前**二进制里**都不是 `pdata` 函数起点**。**地址是 build 的函数：一律按对账文件 §5 重导，禁止照抄本文任何 RVA。**
> - 故本文件「add 与 get/delete 在表里无法区分」的判决，其**偏移与地址两半都已过期**；对账文件已在当前映像给出 attach 写点 `0x867c610`（RVA 亦须重导）。

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读、静态**。**未运行任何东西**——未连桥、未向游戏/编辑器发任何报文、
未启动或触碰任何进程（helper `pid 188156` 未动、未请求 UAC）、未写任何存档、**未读任何图片或 PDF**。
本文件是任务 #6 的唯一产出（只新增本文件本身）。
证据来源（全部**仓内**）：`docs/research/beyondeditor-backend/db/backend.db`（表
`command_route` / `native_function` / `dispatch_table` / `dispatch_entry` / `candidate_name` / `backend_gap`）、
`docs/research/beyondeditor-backend/raw/asm/*.asm`（136 个已反汇编函数）、
`docs/research/beyondeditor-backend/raw/agents/handlers-914-*.json`、
以及同目录兄弟文档（`NATIVE-ADD-COMPONENT.md`、`COMPONENT-READ-VALUE.md`、`COMPONENT-WRITER-MINE.md`）。

> **三层分开**：文档写了什么 / 表能读到什么 / 真机跑过什么。
> 本文件**全部是静态结论，无一条真机**。所有地址都是 **RVA**（`image_base = 0x140000000`，
> `backend.db → native_image.image_base = 5368709120`），且都落在 **`il2cpp` 段**（游戏侧托管逻辑的原生编译体）。

> **⚠️ 与兄弟文档 `NATIVE-ADD-COMPONENT.md` 的关系（先说清楚）**：那份文件问的是「**加组件**在原生里有没有落点」，
> 结论是「**没有观测到，且表里读不出**」。本文件是同一族问题的**换角度复问**，新增三样它没有的东西：
> (a) 把 `command_route` **逐行**点全（38 行，含派生命令的 handler chain 与全部原生地址）；
> (b) 把**每个**组件相关地址的 `native_function` **邻居块**机械列出（谁在它前面、谁在后面、size 多少、表里有无引用）；
> (c) 直接拿**组件类型枚举**去比对「**有没有一个函数收 (entity, 组件类型 id)**」这个 ADD 形状，并纠正兄弟文档 §5.3 里
> 一处**判据统计失准**（`0x4f4440`/`0x4ed110` **不是**分配桩，见 §6.3）。

---

## 0. 一句话结论

- `command_route` 全表 **38 行**，与**组件**直接相关的**只有 2 行，且两条都是删除**
  （`DeleteComponentForEditObj`、`DeleteComponentForPrefab`，§1）。**没有任何 `AddComponent*` / `CreateComponent*` 行。**
- `native_function` 表 **1,145,692 行**，**只有 `rva / end_rva / size` 三列，没有名字、没有角色、没有调用关系**（§2）。
  ⇒ 「从表里读出哪个地址是创建组件」这个问题，**表本身回答不了**——这不是「没找到」，是**该方法在这里不可用**。
- 已认得出角色的组件相关原生函数共 **21 个**（§3）。其中**写动作**只有两种形态：
  **注销/移除**（`0x102d4750`、`0x10ac50a0`、`0xcb64140`）与 **挂节点图**（`0x102d4a60` + `0x1182d020`）。
  **没有一个是「新建组件对象」。**
- **任务第 3 问的答案：是——ADD 的形状在表里存在，但被 GET 占了。**
  有**三个**原生函数收 `(entity, <组件选择子>)`：`0x10aa6800(entity, idx)`、`0x10abeb40(entity, idx, &out)`、
  `0xcb64140(entity, compId)`。前两个是**取**（读），第三个是**删**。**一个「加」函数会有完全相同的签名。**
  ⇒ **形状无法区分 add 与 get。**（§5）
- **判决：原生函数表 + 现证据，不能区分 add 与 delete。**缺的具体是四样，逐条在 §6.1。

---

## 1. `command_route` —— **每一行**与组件相关的记录（任务第 1 问）

`command_route` 全表 **38 行**（`backend.db`）。按「是否触碰组件」分类：

### 1.1 组件**专属**命令（唯一的两条，**都是删除**）

> ⛔ **本表 handler chain 里的 RVA 已过期**（2026-10-11）：`0x914ccd0`、`0xcb64140`、`0x10abeb40`、`0x102d4750`、`0x10ac50a0` 在当前 445 MB 映像里**都不是函数起点**。见文首 banner 与对账文件。

| id | command | service | hash | handler_entry | handler chain（原生地址） | param_shape |
|---|---|---|---|---|---|---|
| **4** | `DeleteComponentForEditObj` | `beyondEditObjService` | `0x0b69f28d` | `0xcb64140` | `0x914ccd0`(派发器) → `0x12a767b0`(查实体) → `0xcb64140`(删核心) → `0x10abeb40`(取组件) → `0x10ac2670`(kind==0x15) → `0x102d4750(comp,0)`(注销) → `0x10ac50a0(entity,comp)`(收尾) | `(int32 实体id, int32 组件id)` |
| **5** | `DeleteComponentForPrefab` | `beyondEditObjService` | `0x5c27df0e` | `0x914ccd0` | `0x12a764e0`(查Prefab) → `mov edx,[rax+0x1c]` → `0x914ccd0` → `jmp 0xcb64140`（**同一实现**） | `(int32 prefabId, int32 组件id)` |

出处：`backend.db → command_route` id4/id5（`calls` 列给出上述地址全集）；
`raw/asm/0x914ccd0.asm:13`（`call 0x12a767b0`）、`:26`（`jmp 0xcb64140`）；
`raw/agents/handlers-914-A.json:116`（`0xcb64140` 内部四跳）。
⇒ **组件的命令面 = 两条 Delete，没有第三条。**（7.0/7.1 语料面亦无 `AddComponent*`，
`candidate_name` 里组件相关 9 条名字**无 Add**，§2.2。）

### 1.2 触碰组件但**不专属**的命令（4 条）

| id | command | handler_entry | 与组件的关系 |
|---|---|---|---|
| 1 | `AddInstructionGraphForEditObj` | `0x914cd90` | 取实体**第 3 号组件**（`0x10aa6800`，`edx=3`）→ 挂（`0x102d4a60`）→ 装配图（`0x1182d020`）→ 通知（`0xd9646b0`）。**加的是"图"，组件是已存在的** |
| 2 | `AddInstructionGraphForPrefab` | `0x914cd90` | 经 Prefab 表取内层 id 后**完全复用** `0x914cd90` |
| 6 | `DeleteEditObj` | `0x914d6a0` | 调**同一个** `0x102d4750`（`raw/asm/0x914d6a0.asm:110`）——但它传的是 `(entity, 全局类型)`，说明 `0x102d4750` 是**通用对象移除**，非组件专用 |
| 7 | `DeletePrefab` | `0xcb55300` | 不碰组件容器；与 `DeleteEditObj` 共用尾声 `0x1389bfc0`/`0xee06a70` |

⇒ **命令面里凡「组件 + 写」= 删。**「加组件」在这 38 行里**不存在**。

---

## 2. `native_function` 能回答什么、回答不了什么（钉口径）

### 2.1 表结构（决定了一切）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- **1,145,692 行**（= `native_image.valid_function_count`）。来源是 `.pdata` 异常表导出的**函数边界**。
- **只有三个数**：没有名字、没有字符串、没有 `calls`、没有段、没有角色列（`db/schema.sql`）。
- ⇒ **任何「列出角色为组件相关的原生函数」的动作，表本身做不到。**能做的只有
  **「已知地址 → 查它落在哪个函数 / size / 邻居是谁 / 是否被某条 command_route 引用」**。
  凡本文件写「角色」的地方，一律给**已反汇编的出处**；无出处者一律标「**表内无名，未定**」。

### 2.2 名字空间边界（别指望表里有符号名）

`candidate_name` 里组件相关名字**只有 9 条**，全是**编辑器字符串表**（`bucket='editor_string_table'`），
且**没有一条是 Add**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


（其余的 `ClientTrigger` / `StuffBag` / `Shop` 等**只在已反编译的枚举定义里**，不在 `candidate_name`。）
⇒ **游戏侧 il2cpp 无符号名可查**，表里也**没有**「创建组件」这类名字可供匹配。

---

## 3. 全部「角色与组件相关」的原生地址（地址 + size + 表里怎么说）

> ⛔ **本表 RVA 全部过期**（2026-10-11）：`0x10aa6800`、`0x10abeb40`、`0x102d4750`、`0x10ac50a0`、`0xcb64140`、`0x914ccd0`、`0x914de40` 在当前 445 MB 映像里**都不是 `pdata` 函数起点**（size/角色可能仍指同一函数体）；**地址必须按对账文件 §5 重导，禁止照抄**。

> `size` 取自 `native_function` 在**该 RVA 精确命中**函数起点；「表内引用」= 有没有出现在任何
> `command_route.calls` 里（**表能提供的唯一"关系"就是这个**）。
> 段：全部 `il2cpp`（游戏侧），除 #19 标「编辑器侧」。

| # | RVA | size | 角色（有界结论，带出处） | 被 command_route 引用 |
|---|---|---:|---|---|
| 1 | `0x10aa6800` | 214 | **按选择子取组件（低层）**：`mov rdi,[rdi+0x48]`（**非组件容器**——是 map 访问器）→ `call 0x16298e90(map,key)` → `[map+0x28]` 按 **24 B stride** 取元素 | id1（AddInstructionGraph） |
| 2 | `0x16298e90` | 1031 | **容器 IndexOf helper**（被 #1 调用；返回下标） | — |
| 3 | `0x10abeb40` | 485 | **取组件** `(entity, idx, &out)→comp`；取不到返回 null | id4（DeleteComponent） |
| 4 | `0x10ac2670` | 476 | `[comp+0x34]==0x15` 时的**额外处理**（入参 = entity） | id4 |
| 5 | `0x102d4750` | 312 | **注销/移除（通用对象）** `(obj, type)`；组件链传 `(comp,0)`，EditObj 链传 `(entity,全局)` | id4, id6 |
| 6 | `0x10ac50a0` | 150 | **删组件收尾**；自身再判 `[comp+0x34]==0x15` → 走 #7/#8 | id4 |
| 7 | `0x10abdf00` | 224 | 收尾里 `kind==0x15` 分支目标 1 | — |
| 8 | `0x10abdfe0` | 1218 | 同上分支目标 2（与 #7 相邻成对） | — |
| 9 | `0xcb64140` | 574 | **删组件核心** `(entity, compId)`：#3 → 判 kind → #5 → #6；返回 bool | id4, id5 |
| 10 | `0x914ccd0` | 176 | **删组件派发器**（两条删命令共用）：查实体 → 尾跳 #9 | id4, id5 |
| 11 | `0x12a767b0` | 234 | 按 id 查 **EditObj 实体**（`[global+0xa7f0]` 字典） | id1, id4, id11, id13 |
| 12 | `0x12a764e0` | 333 | 按 id 查 **Prefab**（`[global+0xa3c0]`，取 `[记录+0x1c]` 内层 id） | id2, id3, id5, id15, id21 |
| 13 | `0x102d4a60` | 423 | **挂到一个已存在对象上**：挂图链以 `(comp,0,0)` 调；与其**相邻的 #5 是同区反向操作**（§4.2） | id1 |
| 14 | `0x1182d020` | 469 | **装配节点图到组件**（`(comp, idx2, idx3, global, 20000)`，5 实参） | id1 |
| 15 | `0x4e29d0` | 2384 | **is-instance 类型校验**（组件类型过滤，多处复用） | id1 |
| 16 | `0xd9646b0` | 359 | **通知 `[global+0xca20]` 管理器重算** | id1 |
| 17 | `0x12f64070` | 884 | **事件派发**（组件链里以 `(0x56, 动态)` 调） | id3 |
| 18 | `0xcb5f330` | 1322 | **Prefab 取对象**（内部用 #1，`edx=1`） | id13, id21, id25 |
| 19 | `0x1182cea0` | 374 | **沿 `entry+0x30` 编号查 `component+0x30` 列表**（`component+0x30`＝**旧记号**；**编辑器侧** walk，游戏侧 kind 在 `[comp+0x34]`），减计数/搬移/清尾/释放 =「移除」形态；**编辑器侧**，非游戏 il2cpp | — |
| 20 | `0x914cd90` | 943 | **`AddInstructionGraph*` 处理器**：查实体 → 取第 3 号组件(#1) → #13 → #14 → #16 | id1, id2 |
| 21 | `0x914de40` | 4775 | **主分发表/分发函数本体**（33 条命令实名，含 #10 入口） | — |

**这 21 个里，「写」只有「移除/注销」与「挂图」；「新建组件对象」的角色 = 0 条。**

---

## 4. 邻居块 —— 与组件操作**紧邻**的原生函数（任务第 2 问）

`native_function` 里没有角色，但它**有排序**。下表把每个组件相关地址所在的函数、以及**紧前/紧后**的
函数（地址 + size）机械列出。**凡角色栏无出处者，一律「表内无名，未定」——不得据此宣称任何能力。**
（数据来自 `backend.db → native_function`，按 `rva ORDER BY` 取邻居。）

### 4.1 邻居清单

| 围绕（组件角色） | 紧前 | **本体（组件角色）** | 紧后 ×2 | 备注 |
|---|---|---|---|---|
| 取组件（低层） | `0x10aa6710`(236) | **`0x10aa6800`(214)** | `0x10aa68e0`(124), `0x10aa6960`(91) | 后接 `0x10aa69c0`(91), `0x10aa6a20`(348)… 一整片未定 |
| 取组件 | `0x10abeae0`(83) | **`0x10abeb40`(485)** | **`0x10abed30`(495)**, `0x10abef20`(44) | `0x10abed30` 紧贴其后 **未定**（第一大候选） |
| kind==0x15 处理 | `0x10ac2610`(65) | **`0x10ac2670`(476)** | `0x10ac2850`(89), `0x10ac28b0`(467) | 后两个未定 |
| 注销 | `0x102d4680`(184) | **`0x102d4750`(312)** | `0x102d4890`(359), `0x102d4a00`(92) | 见 §4.2 |
| 删收尾 | `0x10ac5050`(65) | **`0x10ac50a0`(150)** | `0x10ac5140`(94), `0x10ac51a0`(156) | 后两个未定 |
| kind==0x15 分支 | `0x10abde90`(110) | **`0x10abdf00`(224)** | **`0x10abdfe0`(1218)**, `0x10abe4b0`(264) | `0x10abdfe0` 1218 B，未定 |
| 删核心 | `0x10cb64110`(48) | **`0x10cb64140`(574)** | `0xcb64380`(44), **`0xcb643b0`(1864)** | `0xcb643b0` 1864 B，未定 |
| 删派发器 | `0x914cc50`(114) | **`0x914ccd0`(176)** | **`0x914cd90`(943)**, `0x914d140`(52) | 紧后就是 #20 处理器 |
| 挂到组件上 | `0x102d4a00`(92) | **`0x102d4a60`(423)** | `0x102d4c20`(620), `0x102d4ea0`(323) | 见 §4.2 |
| 容器 helper | `0x16298e00`(140) | **`0x16298e90`(1031)** | `0x162992a0`(131), `0x16299330`(1944) | 一整片 `IndexOf/Add/Remove` 家族，未逐个定名 |

### 4.2 最像「注册 ↔ 注销」的一对：`0x102d4750`(312) ↔ `0x102d4a60`(423)

- 删组件链调 **`0x102d4750(comp, 0)`**（注销）；挂图链调 **`0x102d4a60(comp, 0, 0)`**（挂上）。
- 两者**同区（`0x102d4xxx`）**，中间只隔 `0x102d4890`(359) + `0x102d4a00`(92)。
- **`0x102d4750` 也在 `DeleteEditObj` 链里以 `(entity, 全局类型)` 被调**（`raw/asm/0x914d6a0.asm:110`）
  ⇒ 它更像**通用对象注册表的移除**，而非组件专用。故 `0x102d4a60` 更可能是「往通用注册表挂对象」，**不是新建组件**。
  **这是推断，不是结论。**

### 4.3 各集群的规模（供下一步定点反汇编）

| 集群 | 函数数 | 总字节 | 跨度 |
|---|---:|---:|---|
| `0x10aa6xxx`（组件容器低层） | 16 | 3,983 | `0x10aa6130`..`0x10aa717e` |
| `0x10abd/0x10abe`（kind 判别族） | 38 | 12,629 | `0x10abd000`..`0x10ac0259` |
| `0x10ac0/0x10ac5`（组件方法族） | 78 | 19,954 | `0x10ac0260`..`0x10ac531b` |
| `0x102d4xxx`（注册/注销族） | 12 | 2,926 | `0x102d4420`..`0x102d5014` |
| `0xcb63/0xcb64`（删核心族） | 16 | 6,936 | `0xcb636b0`..`0xcb65216` |
| `0x1629`（容器 IndexOf 族） | 26 | 8,098 | `0x16298220`..`0x1629a29c` |

**这 ~186 个邻居函数里，落到 `native_function` 的"角色"只有「表内无名，未定」。**
要判谁是不是「创建组件」，**必须逐个反汇编**——见 §6.2。

---

## 5. 有没有一个函数收「(entity, 组件类型 id)」= ADD 的形状？（任务第 3 问）

### 5.1 答案：**有，而且不止一个——但全是 GET/DELETE，没有 ADD**

| RVA | size | 签名（有界） | 语义 | 出处 |
|---|---|---:|---|---|
| `0x10aa6800` | 214 | `(entity, idx) → comp` | **取**（读），容器查表 | `raw/asm/0x10aa6800.asm:10,21,31` |
| `0x10abeb40` | 485 | `(entity, idx, &out) → comp` | **取**（读），取不到返回 null | `raw/asm/0x914fb80.asm:18`；`handlers-914-A.json:116` |
| `0xcb64140` | 574 | `(entity, compId)` | **删**（写，但方向是移除） | `command_route` id4 |

⇒ **三类函数共享同一个「实体 + 一个组件选择子」形状。**一个「加组件」函数——「给我 entity + 组件类型，
造一个新组件插进 `[entity+0x68]`」——**签名会与上表前两行逐字相同**。
**形状不能区分 add 与 get。** 这就是第 4 问判决的核心（§6）。
能区分二者的**只有体内行为**：是否**分配**、是否**写 `[新对象+0x34]`**、是否**插 `[entity+0x68]`**。

### 5.2 与组件枚举值的比对（ClientTrigger=5 / Collision=8 / StuffBag=33 / Shop=35 / PopUp=40）

组件种类是编辑器侧**封闭枚举 46 项**（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2）（`QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x`，值域 0..47，缺 2 与 10，
`47 Arraysize` 是哨兵 ⇒ **46 个真实类型**）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


把**所有已反汇编的 136 个函数**里传给「组件取用函数」的**选择子立即数**全扫一遍（Bash `grep`）：

| 选择子 | 调用点 | 落到枚举 |
|---|---|---|
| `edx=3` | `0x914cd90.asm:38,64,90`（`AddInstructionGraph*` 取"第 3 号组件"） | `3 Timer`？（**存疑**，见下） |
| `edx=1` | `0xcb5f330.asm:127,154`（Prefab 取对象） | `1 CustomValue` |
| `edx=0x26`(38) | `0x914fb80.asm:17`（`FocusLight`） | **`38 LightGroup`**——**与命令名 `FocusLight` 吻合**（支持性推断） |
| `[comp+0x34]==0x15`(21) | `handlers-914-A.json:116,122`（删除链 kind 特判） | `21 TempAttachPoint` |

**关键否定**：六个模块目标的类型 id（**5 / 8 / 33 / 35 / 40**）在**全部已反汇编函数的调用点立即数里 0 命中**。
（`mov edx, 0x15` 出现过一次，但在 `0x714c130.asm:368`，紧接 `call 0x4eb300`（**il2cpp 字符串字面量加载**），
`0x15` 是**metadata 串索引**，**与组件无关**——典型反例，说明「edx 立即数」不都是组件类型。）
⇒ **没有任何已观测的调用点向组件函数传过 5/8/33/35/40。**

> **[推断]** `FocusLight` 传 `0x26=38=LightGroup`、删除链特判 `0x15=21=TempAttachPoint`，两处都**恰好**与枚举对上，
> 支持「**选择子 = 前端枚举值**」这一假设。但仍**未证**（`COMPONENT-READ-VALUE.md:§2.2` 明标 `componentIdSpace` 未验）。
> 本文件**不据此声称能力**。

### 5.3 任务本意的那条判据（写全）

若存在「加组件」的原生入口，它在反汇编里**必须**同时满足三件事（这是可判定的充分条件）：

1. **一次分配**（`operator new` 形态）；
2. 对 **`[新对象+0x34]`**（组件 kind 字段）的**写**（`mov dword ptr [rX+0x34], imm`）；
3. 对 **`[entity+0x68]`** 容器的**插入**（`List.Add` 形态：`inc [list+0x1c]` 版本号 + 追加数组）。

**§3 的 21 个函数、§4 与 §5.1 涉及的全部地址，没有一条同时满足。**
且全仓 `tools/game-executor/native/` 对 `[entity+0x68]`（旧记 `[entity+0x48]`）**零命中**（`COMPONENT-WRITER-MINE.md:262`）——
**没有任何探针实现过对组件容器的写**。

---

## 6. 判决（任务第 4 问）

### 6.1 原生表能不能区分 add 与 delete？——**不能。**

理由链（逐条可复核）：

1. `native_function` **无名字/无角色列**（§2.1）⇒ 表**结构上**无法说「这个地址是 add」。
2. 命令面**只有两条 Delete**（§1.1）⇒ 即便退一步用「命令 → 处理器」，也**没有 add 可供对照**。
3. ADD 的**形状**在表里**已被 GET 占用**（§5.1）⇒ 靠「收 (entity, typeId) 且返回 comp」**无法区分**新增与读取。
4. 能区分二者的**体内特征**（分配 / 写 kind / 插容器，§5.3）**在已反汇编范围内一条都没观察到**。

### 6.2 精确地说，**缺什么**（缺的不是「证据不足」，是四样具体的东西）

| # | 缺什么 | 为什么这个必须有 | 补它的动作（下一步定点清单） |
|---|---|---|---|
| A | **邻居函数的反汇编** | §4 的 ~186 个邻居全是「表内无名」，**没有一个**被反汇编过 | 反汇编 §4.1 的高概率候选：`0x10abed30`(495)、`0x10abdfe0`(1218)、`0xcb643b0`(1864)、`0x10ac28b0`(467)，以及整个 `0x10ac0/0x10ac5` 族的短函数 |
| B | **组件容器的写点** | 判 ADD 的必要条件之一（`List.Add` 到 `[entity+0x68]`）从未被观测 | 在 `0x10aa6xxx` / `0x1629` 两族里找**写入** `[list+0x28]`+`inc [list+0x1c]` 的函数（对照 `ModifyEditobjTag` 的 `List<int>.Add` 形态） |
| C | **comp 选择子编号空间之证** | 「(entity, 组件类型 id)」里的 id 究竟是**枚举值**还是**容器下标**未证；若是后者，「按类型查找的 ADD」这条路本身不成立 | 真机读回一次（`inspect-entity-components`），把 `componentIdSpace` 从 `UNVERIFIED` 定死（`COMPONENT-READ-VALUE.md:§2.3`） |
| D | **`0x768d80e` 逃生口未读** | 若存在「绕哈希表」的 add 命令，它不在这 33 条实名 entry 里 | 反汇编 `0x768d80e → 0xd4af450`（`backend_gap` 第 7 条）以及 `0x914cd44 → 0xd070080`（删派发器的绕表分支，`raw/asm/0x914ccd0.asm:38-50`） |

### 6.3 **一处纠正**：`0x4f4440`/`0x4ed110` **不是**「分配桩」

兄弟文档 `NATIVE-ADD-COMPONENT.md:§5.3` 把 `0x4f4440` / `0x4ed110` 列作「分配桩（`operator new` 形态）」。
**逐字节读反汇编后要更正**（本文件新增，属实测证据）：

- `0x4f4440`（1164 B，`raw/asm/0x4f4440.asm`）：**il2cpp metadata/类型初始化**。入参是 **metadata 索引**
  （调用点如 `mov ecx, 0x2008a` / `mov ecx, 0x120cf`），体内做 hash 计算 + 元数据表查找 + **按类写静态数组**。
  它在 `FocusLight` 等处的出现形态是 `mov ecx,<idx>; call 0x4f4440; mov byte ptr[...],1`——**典型 `.cctor` 守卫**。
- `0x4ed110`（`raw/asm/0x4ed110.asm`）：**il2cpp 类初始化**，体内是 `lock cmpxchg` 在 `[rcx+0xc7]`/`[rcx+0xc6]`
  的**双检锁**——`Class::Init`，**不是 `new`**。

⇒ **「分配」这条判据（§5.3 第 1 条）目前没有已知的原生落点地址**。
这**加强**了 §6.1 的判决：连「找一个 `new` 长什么样」这一步都还没做，add 自然无从分辨。
**下一步必须先钉死 il2cpp 分配器（`operator new` / `il2cpp_object_new`）在本映像的实际地址与形态。**

---

## 7. 证据索引（本文件每一条的出处）

| 论断 | 出处 |
|---|---|
| `command_route` 38 行 / 组件 2 条（id4,id5） | `backend.db → command_route`（`SELECT * ORDER BY id`） |
| 两条组件命令的 handler chain 与地址 | `command_route.calls`(id4,id5)；`raw/agents/handlers-914-A.json:115-143` |
| 派发器 `0x914ccd0`（`call 0x12a767b0`/`jmp 0xcb64140`） | `raw/asm/0x914ccd0.asm:13,26` |
| 删核心 `0xcb64140` 内部四跳 | `raw/agents/handlers-914-A.json:116,122` |
| `0x10aa6800` 读 `[entity+0x48]`（**非组件容器**）+ 24 B stride | `raw/asm/0x10aa6800.asm:10,21,31` |
| `0x10abeb40` 被 `FocusLight` 以 `edx=0x26` 调 | `raw/asm/0x914fb80.asm:17-18` |
| `0x10aa6800` 被 `AddInstructionGraph` 以 `edx=3` 调 | `raw/asm/0x914cd90.asm:38,64,90` |
| `0x10aa6800` 被 `0xcb5f330` 以 `edx=1` 调 | `raw/asm/0xcb5f330.asm:127,154` |
| 挂图链 `0x914cd90`：取组件→`0x102d4a60`→`0x1182d020`→`0xd9646b0` | `raw/asm/0x914cd90.asm:19,59,85,120` |
| `0x102d4750` 也在 `DeleteEditObj` 里被调 | `raw/asm/0x914d6a0.asm:110` |
| `native_function` 三列 / 1,145,692 行 | `backend.db → native_function`；`db/schema.sql` |
| 组件名 9 条、**无 Add** | `backend.db → candidate_name`（`name LIKE '%omponent%'`） |
| 46 项组件枚举（原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2） + 目标 id 映射 | `COMPONENT-READ-VALUE.md:124-129,154-155`；`COMPONENT-WRITER-MINE.md:80-96` |
| `[comp+0x34]==0x15` 含义 not_found | `command_route` id4 `notes`；`handlers-914-A.json:122,246` |
| 容器写点在探针里 0 命中 | `COMPONENT-WRITER-MINE.md:262` |
| 绕表钩子 `0x768d80e → 0xd4af450` | `backend_gap` 第 7 条；`backend_gap` 第 8 条（`0x1182d020`/`0xd9646b0` 语义 not_found） |
| `0x4f4440` = 类初始化（非分配） | `raw/asm/0x4f4440.asm:1-...`（`mov ecx,<metadata idx>` 调用形态） |
| `0x4ed110` = `Class::Init` 双检锁（非 `new`） | `raw/asm/0x4ed110.asm:125,149,16b`（`lock cmpxchg [rcx+0xc7]`） |
| 集群函数数/字节 | `backend.db → native_function` 按区间计数 |

---

*本文件由 2026-10-10 会话**纯静态**整理：只读 `backend.db`（`command_route`/`native_function`/`candidate_name`/
`backend_gap`）、仓内 `raw/asm`（136 个 `.asm`）与 `raw/agents`（用 Bash `grep`，非 Grep 工具——它跳过 `.runtime/`）。
**未运行任何脚本、未连桥、未发报文、未触碰游戏/编辑器、未写存档、未读图片/PDF。**
所有地址为 RVA；所有 size 取自 `native_function` 表内该 RVA 的精确起点。
凡「表内无名、未定」的邻居函数，本文一律**不据此声称能力**；凡推断均标 `[推断]`。*
