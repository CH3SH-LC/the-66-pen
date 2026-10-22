> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #8 挖 — 组件「加」这条路在**原生代码**里有没有落点（NATIVE-ADD-COMPONENT）

> # ⛔ 已作废 / SUPERSEDED（2026-10-11 复核）—— 容器偏移与地址**均不可据以工作**
> **唯一事实源**：`docs/research/reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`。
> - **容器偏移错**：本文件写「实体组件容器 = `[entity+0x48]`」——**错**。正确是 **`[entity+0x68]`**（指针列表，步长 8）。
>   `[entity+0x48]` 是**另一结构**（`0x10aa6800` 的按 key 映射访问器），**不是**组件容器。下文凡「**组件容器**」的**偏移**已就地改为 `+0x68`；**例外**：**逐字引用的旧汇编**（如 `0x10aa6800.asm` 的 `mov rdi,[rdi+0x48]`）**保留原字节**（它们是旧二进制的引用，改动即伪造），只在身旁标注它**不是**组件容器。（残留的 `component+0x30` 字样是**编辑器侧 `0x1182cea0` 按编号 walk 的旧记号**，**不是**游戏侧 kind 字段，已就地标注。）
> - **kind 字段错**：本文件写 `[comp+0x30]`（kind）——**错**。正确是 **`[comp+0x34]`**；`comp[+0x30]` 是 byte（enabled 0/1），永不 == 0x15。下文凡「kind / 组件种类字段」的偏移已就地改为 `+0x34`（残留的 `component+0x30` 见上条，是编辑器侧 walk 的旧记号）。
> - **地址全过期**：本文件所有 RVA 取自**更新前**的 `YuanShen.exe`（431 MB / 2026-09-22 建库）；当前映像是 **445,006,744 B / 2026-09-23**。
>   已证 `0x914de40`、`0xcb64140`、`0x10abeb40`、`0x10ac50a0`、`0x102d4750`、`0x10aa6800`、`0x914ccd0` 在**当前**二进制里**都不是 `pdata` 函数起点**。
>   **地址是 build 的函数**：一律按对账文件 §5 重新导出，**禁止照抄本文任何 RVA**。
> - 故本文「组件容器只有读 / 从未观测到写」的负结论建立在**错偏移 + 过期映像**上；与对账文件冲突处以对账文件为准（对账文件已给出 `0x867c610` 这条 attach 写点，RVA 亦须重导）。
> **下方正文保留原样，只把两个偏移就地改正、把过期地址就地标注为过期。**

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读、静态**。**未运行任何东西**——未连桥、未向游戏/编辑器发任何报文、
未启动或触碰任何进程（helper 未动、未请求 UAC）、未写任何存档、未读任何图片或 PDF。
本文件是任务 #8 的唯一产出，只新增本文件本身（不在本文件外落任何文件）。
证据来源（全部**仓内**）：`docs/research/beyondeditor-backend/`（`db/backend.db` + `raw/agents/*.json`
+ `raw/asm/*.asm` + `db/routes.json`）、`docs/gameplay/FRONTEND-BACKEND-TRACE-20260920.md`、
`.runtime/editor-catalog/resolved/`（7.0 反编译）、`.runtime/verification/update-repair-20260925/strings/annotated-7.1/`（7.1 解出串版）。

> 三层分开：**文档写了什么** / **工具能读到什么** / **真机跑过什么**。本文件**全部是静态结论，无一条真机**。
> 所有地址都是 **RVA**（相对 pe 头 `image_base = 0x140000000`，`native_image.image_base = 5368709120`），
> 且都落在 **`il2cpp` 段**（`native_section`：`il2cpp` 是最长的可执行段）——即**游戏侧托管逻辑的原生编译体**，
> 不是编辑器进程、也不是 `.text`。
>
> **⚠️ 任务前提的一处纠正（先说清楚，免得后面白找）**：任务写「the editor calls into native code somewhere」。
> 严格说，`DeleteComponentForEditObj` 的**处理器 0xcb64140 在 `YuanShen.exe`（游戏进程）的 `il2cpp` 段里**，
> 不在 `BeyondEditor.exe` 里。前端（编辑器）发的是一条**命令**（`beyondEditObjService` 服务 + 命令名 FNV-1a 哈希），
> 由**游戏侧**的分发表 `0x914de40` 接住并分发。所以「原生侧」= **游戏侧 il2cpp**，「编辑器侧反汇编」是另一条线
> （`0x1182cea0` 那类，见 `NATIVE-MEMORY-MAP.md:235`）。本文两份都列出，并分别标注。

---

## 0. 一句话结论

- **删除链**（前端字面量 → 分发表 → 处理器 → 原生实现）**逐跳都有 file:line + 地址 + size**，闭环可复核（§1）。
- **原生函数表（`native_function`，1,145,692 行）只有 `rva/end_rva/size`，没有任何名字/角色列**（§2）。
  所以「**从表里读出谁是加组件**」这个问题，**表本身回答不了**——角色只存在于**已反汇编的少量函数**里（§3）。
- **已记录的证据里，组件相关的原生函数共 21 个**（§3 全列出，带地址+size）。其中**没有一个是「新建组件对象并插进
  `[entity+0x68]` 容器」**。
- **有没有一个地址是「创建组件」的？——在现有（表 + 已反汇编证据）范围内：无法分辨，且从未观察到。**
  能被识别的原生组件动作只有：**取组件（读）**、**删组件（注销 + 收尾）**、**给已存在的组件挂节点图**（§5）。
- **唯一已观测到的原生「加」动作是 `AddInstructionGraphForEditObj`**：取实体**第 3 号组件** → 装配节点图（`0x1182d020`）
  → 通知重算（`0xd9646b0`）。它**加的是「图」，不是「组件」**（§4.3）。
- **给下一步的判据**：如果存在「加组件」的原生入口，它**要么**是分发表 `0x914de40` 里的一条命令（33 条已全部实名，**没有**，§2.3），
  **要么**走绕表逃生口（全局钩子 `0x768d80e` → `0xd4af450`，**未读**，§6）。**没有第三条静态可见的路。**

---

## 1. 删除链，逐跳（前端字面量 → 分发表 → 处理器 → 原生实现）

### 1.1 前端（编辑器）发出的是**一条命令**

| 跳 | 内容 | file:line |
|---|---|---|
| 字面量（7.0） | `"DeleteComponentForEditObj"`（`/* string 137436 */`） | `.runtime/editor-catalog/resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107` |
| 字面量（7.1，1:1 对应物） | `"DeleteComponentForEditObj"`（`/* string 146126 */`） | `.runtime/verification/update-repair-20260925/strings/annotated-7.1/HAZWycj0oGZJFaTJo8c9.XVcbBbj0Pal6i9RiXENV.cs:163` |
| 兄弟命令 `DeleteComponentForPrefab` | 7.0 `…yn34VuuuO5tEgsICYDBW.cs:152`；7.1 `…XVcbBbj0Pal6i9RiXENV.cs:124` | 同上 |
| 派发形状 | `BrjMRrl…xyVYfsr3qg0(producer, <service>, "DeleteComponentForEditObj", null, List<Param>[ uint(entityId), uint(componentId) ])` | 同上 `:107`（args 构造：`…G9oiCBkSaYQ` 取实体 id + `(uint)xHRuuubNIqa` 组件 id，两个都走 `…bKliA0tj1p1` = uint→Param） |
| service | `beyondEditObjService`（前端以「生产者生成的 service ref」传入，非字面量；DB 记为 `beyondEditObjService`） | `backend.db → command_route.service`（id4）；`COMPONENT-WRITER-MINE.md:150-152` 给同族三命令口径 |

> **7.1 与 7.0 逐行同构**（`71-ADD-COMPONENT.md:0` 已复核）：组件命令仍只有两条 Delete，**没有第三条**。

### 1.2 游戏侧：分发表 → 处理器

> ⛔ **`func_begin=0x914de40` 已过期**（2026-10-11）：该 RVA 在当前 445 MB 映像里**不是 `pdata` 函数起点**；同理下表 `0xcb64140` / `0x914ccd0` 亦过期。见文首 banner 与对账文件。

`backend.db`（表 `dispatch_table` id=1，role「主命令表」，`func_begin=0x914de40`，size **4775**，`complete=1`，33 条）：

| command | hash | cmp_at | branch_target | handler_entry（处理器） | param_shape |
|---|---|---|---|---|---|
| `DeleteComponentForEditObj` | `0x0b69f28d` | `0x914e138` | `0x914e997` | **`0xcb64140`** | (int32 实体id, int32 组件id) |
| `DeleteComponentForPrefab` | `0x5c27df0e` | `0x914e59e` | `0x914ee6d` | `0x914ccd0`（→ 尾跳 `0xcb64140`） | (int32 prefabId, int32 组件id) |

- 出处：`backend.db → command_route` id4/id5、`dispatch_entry`（`dispatch_entry` 行：`('DeleteComponentForEditObj','0x914e138','0x914e997')`）、
  `raw/agents/handlers-914-A.json:100-143`、`db/routes.json:65-66`。
- 分支入口 `0x914e997` **不是独立函数**，它在 `0x914de40`（4775 B 的分发函数体）内部：校验参数、取 2 个 int，任一失败则返回 false，
  然后 `0x914ea14 call 0x914ccd0(rcx=r14, edx=idx0, r8d=idx1)`（`handlers-914-A.json:114-115`）。

### 1.3 派发器 `0x914ccd0`（176 B）—— 两条组件删命令**共用**的实现


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

出处：`raw/asm/0x914ccd0.asm:1-32`（`call 0x12a767b0` 在 `:13`，`jmp 0xcb64140` 在 `:26`）。
（另有 `0x914cd44` 分支走向 `0xd070080`（546 B）——`[global]` 装了 hook 时的另一条路由，见 §6。）

### 1.4 删组件核心 `0xcb64140`（574 B）—— **未落成独立 `.asm`，只有子智能体的有界结论**

仓内 `raw/asm/` **没有** `0xcb64140.asm`。其内部**只记录在** `raw/agents/handlers-914-A.json:115-122`（`observed`/`notes`）：

| 记录 | 内容（原文，`handlers-914-A.json` 行号） |
|---|---|
| `:116` | `0xcb641a2 call 0x10abeb40(entity, idx1, &out) 取组件` |
| `:116` | `组件 [comp+0x34]==0x15(21) 时额外 call 0x10ac2670(entity)` |
| `:116` | `随后 call 0x102d4750(comp, 0)；call 0x10ac50a0(entity, comp)` |
| `:116` | `（后者自身也判 [comp+0x34]==0x15 并走 0x10abdf00/0x10abdfe0）` |
| `:117` | `0xcb64140 结束前用 0xd3fbe00 / 0x11221330 作用域清理（using/Dispose 代码生成形态），返回 bool` |
| `:122` | 有界结论：`实体查找 → 取出该组件 → [comp+0x34] 存在 0x15 特判分支 → 0x102d4750(comp,0) 注销 → 0x10ac50a0(entity,comp) 收尾`；`0x15 的具体含义 not_found` |

### 1.5 完整链（一图）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`DeleteComponentForPrefab` 只差前一步：`0x12a764e0(prefabId)`（Prefab 表 `[global+0xa3c0]`）→ `mov edx,[rax+0x1c]`（取内层 id）
→ `jmp 0x914ccd0`（**同一实现**）。出处 `handlers-914-A.json:126-143`、`command_route` id5。

---

## 2. 原生函数表能回答什么、回答不了什么（口径，先钉死）

### 2.1 表结构
`backend.db → native_function`：`rva INTEGER PRIMARY KEY, end_rva INTEGER, size INTEGER`，
**1,145,692 行**（`native_image.valid_function_count` 同值）。**只有三个数，没有名字、没有字符串、没有角色列。**
来源是 `.pdata` 异常表导出的**函数边界**（`db/README.md:69`、`schema.sql:90-94`）。

- ⇒ **「列表出角色为组件相关的原生函数」这个动作，表本身做不到。**
  能做到的只有：**已知地址 → 查它落在哪个函数、size 多少、邻居是谁**（本文 §3/§4 就是这么做的）。
- 角色来源**只有**已反汇编的函数（`raw/asm/*.asm`、`raw/agents/*.json`、`02-命令分发表-主表-0x914de40.md`）。
  本文凡「角色」一栏，均给**出处**；凡无出处的一律标「**未定点（表内无名）**」。

### 2.2 名称空间的边界（别指望 `native_function` 里有符号名）
`candidate_name` 表里的组件相关名字**只有 9 条**（`backend.db → candidate_name`）：
`DeleteComponentForEditObj` / `DeleteComponentForPrefab`（`bucket='editor_string_table'`）+
`Template_ComponentEdit_*`(5) / `vmComponents` / `componentName`——**没有 `AddComponent*`**。
且这些是**编辑器字符串表**的名字，不是游戏侧符号名。**游戏侧 il2cpp 无符号名可查**（除非有 global-metadata，本仓未见）。

### 2.3 关键：如果「加组件」是游戏侧命令，它应落在**同一张表**
`beyondEditObjService` 的 15 条命令**15/15 全落到 `0x914de40`**（`backend_gap` 表「服务→分发表」条：
"beyondEditObjService … 15/15 命中 0x914de40"）。而 `0x914de40` 的 **33 条 entry 全部已实名**（`dispatch_entry` 全表）。
**组件相关只有两条 Delete。** ⇒ 「加组件」**不在这张表里**（在这张表能接住的范围内）。

---

## 3. 全部「角色与组件相关」的原生函数（地址 + size + 出处）

> 口径：下表 = **仓内已反汇编/已记录、且角色被认定与「组件」有关**的全部函数。
> 「角色」列一律给**出处**；`size` 取自 `backend.db → native_function`（`rva` 精确命中表内函数起点）。
> 段：全部落在 `il2cpp`（游戏侧），除标注「编辑器侧」者。

| # | RVA | size | 角色（有界结论） | 出处 |
|---|---|---:|---|---|
| 1 | `0x10aa6800` | 214 | **按 id 取组件**：`mov rdi,[rdi+0x48]`（**不是**组件容器——`+0x48` 是 map 访问器，见 §4.4）→ `call 0x16298e90(map,key)` 求下标 → `[map+0x28]` 数组按 **24 B stride** 取元素（`lea rax,[rax+rax*2]; mov rax,[rcx+rax*8+0x30]`） | `raw/asm/0x10aa6800.asm:10,21,24,31`；`evidence` E3；`FRONTEND-BACKEND-TRACE-20260920.md:33` |
| 2 | `0x16298e90` | 1031 | **容器 IndexOf helper**（被 #1 调用；返回下标，<0 → 走默认 `0x4eb300`） | `handlers-914-B.json`（`0x10aa6800_verification`） |
| 3 | `0x10abeb40` | 485 | **取组件**（`(entity, idx, &out) -> comp`）。删除路径以 `compId` 调；`FocusLight` 以固定 `0x26` 调——**取不到返回 null**（调用点 `test rax,rax; je`） | 删除：`handlers-914-A.json:116`；`FocusLight`：`raw/asm/0x914fb80.asm:16-17`（`mov edx,0x26; call 0x10abeb40`） |
| 4 | `0x10ac2670` | 476 | `[comp+0x34]==0x15` 时的**额外处理**（删除链里被调，入参 = entity） | `handlers-914-A.json:116` |
| 5 | `0x102d4750` | 312 | **注销/执行删除动作**（`(obj, type)`）。组件链里 `(comp, 0)`；`DeleteEditObj` 链里 `(entity, global)` —— **通用对象移除**，非组件专用 | 组件：`handlers-914-A.json:116`；`DeleteEditObj`：`handlers-914-A.json:164`；`routes.json:97-98` |
| 6 | `0x10ac50a0` | 150 | **删组件收尾**；自身再判 `[comp+0x34]==0x15` → 走 #7/#8 | `handlers-914-A.json:116` |
| 7 | `0x10abdf00` | 224 | 收尾里 `kind==0x15` 分支的目标 | `handlers-914-A.json:116` |
| 8 | `0x10abdfe0` | 1218 | 同上分支的第二目标（与 #7 相邻成对） | `handlers-914-A.json:116` |
| 9 | `0xcb64140` | 574 | **删组件核心**（entity, compId）：#3 取组件 → 判 kind → #5 注销 → #6 收尾；返回 bool | `command_route` id4；`handlers-914-A.json:115-122` |
| 10 | `0x914ccd0` | 176 | 删组件**派发器**（两条删命令共用）：查实体 → 尾跳 #9 | `raw/asm/0x914ccd0.asm`；`command_route` id4 |
| 11 | `0x12a767b0` | 234 | 按 id 查 **EditObj 实体**（`[global+0xa7f0]` 字典，键 `{0,1,2,id}`） | `evidence` E3/E6；`handlers-914-A.json:170` |
| 12 | `0x12a764e0` | 333 | 按 id 查 **Prefab**（另一张表 `[global+0xa3c0]`，取 `[记录+0x1c]` 内层 id） | `command_route` id5；`handlers-914-A.json:126-143` |
| 13 | `0x102d4a60` | 423 | **挂在组件上**：`AddInstructionGraph*` 链里以 `(comp, 0, 0)` 调（与 #5 `0x102d4750` **同区、相邻**，见 §4.2） | `handlers-914-A.json:49`、`routes.json:18,65` |
| 14 | `0x1182d020` | 469 | **装配节点图到组件**（5 实参，`(comp, idx2, idx3, global, 20000)`）；**这是"加图"，不是"加组件"** | `handlers-914-A.json:50`；`02-…0x914de40.md:79` |
| 15 | `0x4e29d0` | 2384 | **is-instance 类型校验**（组件类型过滤，多处复用） | `handlers-914-A.json:48,50` |
| 16 | `0xd9646b0` | 359 | **通知 `[global+0xca20]` 管理器重算**（按类型 + `[item+0x18]` 命中 → 置 `byte[item+0x30]=1`） | `handlers-914-A.json:51` |
| 17 | `0x12f64070` | 884 | **事件派发**（组件链里以 `(0x56, 动态)` 调；`FocusLight`/`AddInstructionGraph*` 均用到） | `handlers-914-A.json:57`；`handlers-914-B.json`（`FocusLight` observed） |
| 18 | `0xcb5f330` | 1322 | **Prefab 取对象**（`FocusLight` mode=1 / `ModifyFactionForPrefab` / `RequestPrefabInstance` 共用；内部会用 `0x10aa6800`） | `handlers-914-B.json`（`prior_candidate_check`） |
| 19 | `0x1182cea0` | 374 | **沿 `entry+0x30` 编号查 `component+0x30` 列表**（`component+0x30`＝**旧记号**；**编辑器侧** walk，游戏侧 kind 在 `[comp+0x34]`），减计数/搬移/清尾/释放——与「节点图移除」吻合，**不是向量写入**（**编辑器侧**，非游戏 il2cpp） | `PROGRESS.md:5701`；`FRONTEND-BACKEND-TRACE-20260920.md:160`；`NATIVE-MEMORY-MAP.md:235` |
| 20 | `0x914cd90` | 943 | **`AddInstructionGraph*` 的处理器**：查实体 → 取**第 3 号组件**（#1，`edx=3`）→ #13(comp,0,0) → **#14 装配图** → #16 通知 | `raw/asm/0x914cd90.asm:39,59,85,120`；`02-…0x914de40.md:78-79` |
| 21 | `0x914de40` | 4775 | **主分发表/分发函数**本体（含 #10 的入口、以及所有 `0x914e***` 分支）；33 条命令实名 | `dispatch_table` id1；`02-…0x914de40.md` |

> ⛔ **本表 RVA 全部过期**（2026-10-11）：`0x10aa6800`、`0x10abeb40`、`0x102d4750`、`0x10ac50a0`、`0xcb64140`、`0x914ccd0`、`0x914de40` 在当前 445 MB 映像里**都不是 `pdata` 函数起点**（size/角色可能仍指同一函数体，**地址必须按对账文件 §5 重导，禁止照抄**）。

**这张表里，凡「写」都是「删/注销/移除」或「挂图」，凡「新建组件对象」的角色 = 0 条。**

---

## 4. SIBLING 分析 —— 删组件原生函数**旁边**有没有一个「组件操作」

### 4.1 邻居清单（`native_function` 直接相邻者，未定名）
下表是**与关键组件函数紧邻**的函数（同段、地址连续），供下一步定点反汇编；
`角色` 栏无出处者一律标「**表内无名，未定**」——**不得据此宣称能力**。

| 围绕 | 紧邻函数（RVA / size） | 备注 |
|---|---|---|
| 取组件 `0x10abeb40`(485) | 前 `0x10abeae0`(83)；**后 `0x10abed30`(495)**；再后 `0x10abef20`(44)/`0x10abef50`(44) | `0x10abed30` 紧贴其后，**未定** |
| 取组件(低层) `0x10aa6800`(214) | 前 `0x10aa6710`(236)；后 `0x10aa68e0`(124)/`0x10aa6960`(91)/`0x10aa69c0`(91)/`0x10aa6a20`(348) | 一整片未定 |
| 注销 `0x102d4750`(312) | 前 `0x102d4680`(184)；**后 `0x102d4890`(359)/`0x102d4a00`(92)/`0x102d4a60`(423)** | 见 §4.2 |
| 删核心 `0xcb64140`(574) | 前 `0xcb63e60`(677)/`0xcb64110`(48)；后 `0xcb64380`(44)/`0xcb643b0`(1864) | `0xcb643b0` 1864 B，未定 |
| 容器 helper `0x16298e90`(1031) | 前 `0x16298e00`(140)；后 `0x162992a0`(131)/`0x16299330`(1944) | 一整片 `IndexOf/Add/Remove` 家族（未逐个定名） |

### 4.2 最像「注册 ↔ 注销」的一对：`0x102d4750`(312) ↔ `0x102d4a60`(423)
- 删组件链调 **`0x102d4750(comp, 0)`**（记录为「注销」）；
- 挂图链（`AddInstructionGraph*`）调 **`0x102d4a60(comp, 0, 0)`**（`handlers-914-A.json:49`）；
- 两者**同区（`0x102d4xxx`）、中间只隔 `0x102d4890`(359) + `0x102d4a00`(92) 两个小函数**。

**这是「一对方向相反的对象操作」的最强静态线索**（一个把对象移出某注册表、一个把它挂进去）。
但注意：**`0x102d4750` 也在 `DeleteEditObj` 链里以 `(entity, 全局类型)` 被调**——它更像**通用对象注册表的移除**，
而非组件专用。**故 `0x102d4a60` 更可能是"往通用注册表挂对象"，不是"新建组件"。** 这是**推断**，不是结论。

### 4.3 唯一被观测到的原生「加」动作：`AddInstructionGraphForEditObj`（加的是图）
`0x914cd90`（`raw/asm/0x914cd90.asm`）：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

⇒ **游戏侧确实有「把东西挂到一个已存在的组件上」的原生能力**（`0x102d4a60` 挂 + `0x1182d020` 装配），
**但被挂的是「节点图」，被寻址的组件（第 3 号）是已存在的**。**没有一处是"新建组件对象"。**

### 4.4 `[entity+0x48]`（**不是组件容器**；真容器 = `[entity+0x68]`，见文首）只有**读**，没有观测到**写**
- 读：`0x10aa6800`（`raw/asm/0x10aa6800.asm:10` `mov rdi,[rdi+0x48]`）。
- 容器形态：`List`-like（`IndexOf`=`0x16298e90`，元素 24 B；`map+0x28`=entries，`+0x18`=count）。
- **全仓范围**：`tools/game-executor/native/` 里 `0x1182cea0` / `component+0x30`（**旧记号**，编辑器侧） / `[entity+0x68]`（旧记 `[entity+0x48]`）**零命中**
  （`COMPONENT-WRITER-MINE.md:262`）——**没有任何探针实现过对 `[entity+0x68]` 的写**。
- ⇒ **"插入一个组件"的原生写点，从未被观测、也从未被实现为探针。**
  （**2026-10-11 更正**：本条只对**当时那 136 个已反汇编函数 + 过期映像**成立；对账文件已在当前映像里给出 attach 写点 `0x867c610`。见文首。）

---

## 5. 有没有一个地址是「创建组件」的？（任务第 3 问）

### 5.1 直接回答
**在「原生函数表 + 仓内已反汇编证据」这个范围内：不能分辨，且从未观察到。**
- `native_function` **无名字/角色列**（§2.1）⇒ 表**本身**无法回答"哪个地址创建组件"。
  一个诚实的「**cannot tell from the table**」在这里是**正确**的答案，不是偷懒。
- 已反汇编的组件相关函数（§3，21 个）**全部**是「取 / 判类型 / 注销 / 收尾 / 挂图 / 通知」，
  **没有一个**是「new 一个组件对象 → 设 `+0x34` 类型 → 插 `[entity+0x68]`」。

### 5.2 证据**支持**的边界（把「不存在」缩到最小）
| 若「加组件」走… | 判据 | 结论 |
|---|---|---|
| 游戏侧**具名命令** | `0x914de40` 33 条 entry **全部实名**，组件只有 2 条 Delete（§2.3）；`beyondEditObjService` 15/15 落此表 | **不在此表** |
| 游戏侧**命令**（其它 service 表） | `beyondInstructionGraphService/beyondEffectService/beyondAudioService` 的 native 分发器**未定位** | **无法排除（未定位 ≠ 不存在）** |
| **绕过哈希表**的全局钩子 | `0x768d80e` 置位时整个分发委托给 `0xd4af450`（558 B）；`0x914cd44` 分支走 `0xd070080`(546) | **逃生口，未读** |
| 编辑器侧**模型直改**（无命令，随存档走） | 前端组件集合 `Add` 只在**反序列化**路径被调（`COMPONENT-WRITER-MINE.md` §5）；7.0/7.1 字面量面 `AddComponent*` 全 0 | **命令面不存在；模型面调用者未定位** |

### 5.3 判别「创建」需要看什么（给下一步的定点清单）
要在原生里认出「创建组件」，**必须**在反汇编里看到这三件事**同时**出现：
1. 一次**分配**（`operator new` 形态：`call 0x4f4440`/`0x4ed110` 等分配桩，或托管 allocator）；
2. 对 `[新对象+0x34]`（组件 kind 字段）的**写**（`mov dword ptr [rX+0x34], imm`）；
3. 对 **`[entity+0x68]`** 容器的**插入**（`List.Add` 形态：`inc [list+0x1c]` 版本号 + 追加数组，参 `ModifyEditobjTag` 的 `List<int>.Add` 形态 `02-…0x914de40.md:97`）。
**§3 的 21 个函数没有一条同时满足**。

---

## 6. 缺口 / 逃生口（诚实清单，逐条带出处）

| 缺口 | 状态 | 出处 |
|---|---|---|
| 三个 beyond*Service（InstructionGraph/Effect/Audio）的 native 分发器**未定位** | `not_found`（≠不存在） | `backend_gap`（「服务 3+ 的分发绕过 native 字符串」） |
| 全局钩子 `0x768d80e` → `0xd4af450` **未读**（绕哈希表）；删组件派发器里对应的分支 `0x914cd44 → jmp 0xd070080` 也未展开 | 未读 | `COMPONENT-WRITER-MINE.md:275`；`raw/asm/0x914ccd0.asm:38-50` |
| `0x1182d020` / `0xd9646b0` 的内部语义未展开 | `not_found` | `backend_gap`（「命令处理分支语义」条）；`gaps.json:67` |
| 组件种类常量 `[comp+0x34]==0x15`(=21) 的含义**未解析** | `not_found` | `command_route` id4 `notes`；`handlers-914-A.json:122,246` |
| 前端枚举 `jaUof90C3Ncl5BAJri4x`(46 值；原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2) 与**原生 comp 序号**是否同一编号空间 | **未证** | `COMPONENT-WRITER-MINE.md`（未证项）；MEMORY「组件 id 编号规则」 |
| `0xcb64140` 本体**没有独立 `.asm`**（只有子智能体结论） | 取证不完整 | `raw/asm/` 无此文件 |

> **[推断] 关于 `0x15`**：前端组件枚举里 `21 = TempAttachPoint`（`jaUof90C3Ncl5BAJri4x`，见 `COMPONENT-WRITER-MINE.md:80-92`）。
> 若原生 `[comp+0x34]` 与前端枚举**同一空间**，则 `0x15` 特判 = 「临时挂点」组件。**这是推断，不是结论**
> ——两套编号是否同源**未证**（上表第 5 条），本文**不据此声称任何能力**。

---

## 7. 证据索引（本文件每一条的出处）

| 论断 | 出处 |
|---|---|
| 前端字面量 7.0 / 7.1 | `.runtime/editor-catalog/resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:107,152`；`.runtime/verification/update-repair-20260925/strings/annotated-7.1/HAZWycj0oGZJFaTJo8c9.XVcbBbj0Pal6i9RiXENV.cs:124,163` |
| 分发表 / 处理器（33 条，组件 2 条） | `backend.db → dispatch_table`(id1) / `dispatch_entry` / `command_route`(id4,id5) |
| 派发器 `0x914ccd0` | `raw/asm/0x914ccd0.asm:13,26` |
| 删核心 `0xcb64140` 内部（取组件/判 kind/注销/收尾） | `raw/agents/handlers-914-A.json:115-122` |
| 取组件（低层）`0x10aa6800` + 容器 `[entity+0x68]` | `raw/asm/0x10aa6800.asm:10,21,24,31`；`evidence` E3 |
| 取组件 `0x10abeb40`（也被 FocusLight 以 `0x26` 调） | `handlers-914-A.json:116`；`raw/asm/0x914fb80.asm:16-17` |
| 挂图链 `0x914cd90`（取第 3 号组件 → `0x102d4a60` → `0x1182d020` → `0xd9646b0`） | `raw/asm/0x914cd90.asm:39,59,85,120`；`02-命令分发表-主表-0x914de40.md:78-79` |
| 全部函数 size | `backend.db → native_function`（`rva` 精确命中） |
| 无 `AddComponent*`（命令/字面量面） | `COMPONENT-WRITER-MINE.md:224-243`；`ADD-COMPONENT-TRACE.md:101-124`；`71-ADD-COMPONENT.md:0`；`backend.db → candidate_name`（组件名 9 条，无 Add） |
| 容器在原生探针里 0 命中 | `COMPONENT-WRITER-MINE.md:262`；`ASSET-MEASURE-MINE.md:164` |
| 绕表钩子 `0x768d80e` → `0xd4af450` | `COMPONENT-WRITER-MINE.md:275`；`backend_gap` |
| 编辑器侧 `0x1182cea0` 沿 `component+0x30`（**旧记号**，编辑器侧 walk；游戏侧 kind 在 `[comp+0x34]`） | `PROGRESS.md:5701`；`FRONTEND-BACKEND-TRACE-20260920.md:160`；`NATIVE-MEMORY-MAP.md:235` |
| 组件 46 值枚举（`21=TempAttachPoint`；原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2） | `COMPONENT-WRITER-MINE.md:80-92`（`QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49`） |

---

*本文件由 2026-10-10 会话**纯静态**整理：只读 `backend.db`（`native_function` / `dispatch_entry` / `command_route`）、
仓内 `raw/asm`、`raw/agents` 与 `.runtime/` 反编译语料（用 Bash `grep`，非 Grep 工具——它跳过 `.runtime/`）。
**未运行任何脚本、未连桥、未发报文、未触碰游戏/编辑器、未写存档、未读图片/PDF。**
所有地址为 RVA；所有 size 取自 `native_function` 表内该 RVA 的精确起点。
凡「表内无名、未定」的邻居函数，本文一律**不据此声称能力**；凡推断均标 `[推断]`。*
