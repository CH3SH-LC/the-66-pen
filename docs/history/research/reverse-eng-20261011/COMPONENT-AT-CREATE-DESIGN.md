> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 组件随创建一起长出来 —— 安全设计（建时装配一个组件）

**产出日期**：2026-10-11。位置：`docs/research/reverse-eng-20261011/COMPONENT-AT-CREATE-DESIGN.md`。
**口径**：**纯离线、纯只读、纯设计**。**未运行任何东西**——helper 未动、未请求 UAC、未写存档、
未向游戏/编辑器发报文、**未执行任何 native 调用**、未读任何图片/PDF。
证据来源＝仓内 C++/Python 源码（逐行读）＋ `COMPONENT-CONTAINER-RECONCILED.md`（2026-10-11，从**当前**
`YuanShen.exe` 445,006,744 B 重新导出，本文件直接引用其已复算的地址与偏移）。

> **三层分标（`CLAUDE.md` §一.3）**：本文所有「容器事实」是**已复算的静态结论**（引 reconciliation）；
> 所有「设计」是 **PROPOSED / 未实现 / 未编译 / 未真机**。凡未证处一律标 `[ASSUMED]`，并给**单一观察**。

> **本文要修的两处（上一稿被 REFUTED 的原因）**：
> 1. **安全**：上一稿的守卫写反（「拒绝非空 owner」），实际只在 `owner==NULL` 时触发 ⇒ 会调
>    `0x867c610(nullptr, KIND)` ⇒ 命中 `[rsi+0x30]` 解引用 ⇒ **崩游戏**。**fail-open，必须重建。**
> 2. **未对账的矛盾**：早期文档（`NATIVE-ADD-COMPONENT.md` / `NATIVE-COMPONENT-CREATE.md`）说容器是
>    `[entity+0x48]`；本稿采用 **reconciliation 的判决**：容器是 **`[entity+0x68]`**（指针列表，步长 8），
>    早期文档的整片地址来自**更新前的 `YuanShen.exe`**，已过期。

> **【2026-10-11 二次修复 pass】** 对手方对上一稿提出四处缺陷，本轮**逐条反汇编复核后修掉**（口径：**纯离线、
> 只读、未连桥、未发报文、未执行任何 native 调用**，证据＝对**当前** `YuanShen.exe`（445,006,744 B）的
> `.pdata` 有界反汇编，脚本 `.runtime/scratch/comp-create/func.py`）：
> - **D1（G7/§7 自相矛盾）**：`§3.2/§7` 把 attach 放进 `HR_ACTION==1/3`，`§0/G7` 又说「永不搭普通 create 的车」。
>   **判决：`0x867d2c0` 本来就出现在普通 create 路径上**——`place_builtin`→`0x106df3c0`→`0x8364ab0`→
>   `jmp 0x8363030`，而 `0x8363030` 在 `0x836365b` 与 `0x83637d3` **两次**调 `0x867d2c0`。⇒ **G7 必须重写**
>   （改为 §4 的 `G7′`：按 **owner/kind/动作** 分域，不再「禁普通 create」）。
> - **D2（G1 不可求值）**：`G1` 的「= `after` 中 `+1` 那个实体的 owner」需要 `after`，但 `after` 在第 4 步才抓，
>   `G1` 写在第 3 步 ⇒ 顺序不可实现。**修法**：拆成可即时求值的 `G1a`（`code==returned && owner!=nullptr`）与
>   快照后求值的 `G1b`（身份匹配），见 §3.2 修正后的步序。
> - **D3（重复插入是否真被排除）**：谓词是**共享的** `0x16a68fe0`，`get`/`get-or-create`/**裸 attach 三处都调**；
>   `attach` 自己在 `0x867c654` 判真即**返回 NULL、不插入**，插入后 `0x867c770` 调 `0x16a6b330` 把 kind 写进**同一字典**。
>   ⇒ **重复插入被排除**（机制见 §1.5 / §2）。**不是**上一稿说的「因为用的是 get-or-create 而非裸 attach」——
>   那条理由**错**（裸 attach 也自防重）。
> - **D4（kind 表张冠李戴）**：`§2` 把 `[0..20,22..60,66,67,68,69,74,78]`（66 种）归给 `RECONCILED.md`——
>   该文件**没有这张表**；全仓检索该字面量**只命中本文件自身**。改归到真正的枚举出处，见 §2 / §4 G4。

> **【2026-10-12 Q-B 结案 —— D3 的判决被推翻，重复插入并未被排除】**（口径同上：纯离线、只读、未执行任何
> native 调用；仪器＝对**当前** `YuanShen.exe`（445,006,744 B）的 `.pdata` 有界反汇编；**正向控制已过**，见 §1.6）。
> **D3 原文写「重复插入被排除」——错。** 真相是：**判重读的是另一个结构**。`0x16a68fe0` 不是「组件字典的成员谓词」，
> 而是**通用 `HashSet<int>.Contains`**（`0x16a6b330` 是配对的 `HashSet<int>.Add`，同一 [`+0x10`] buckets / [`+0x20`]
> entries / [`+0x18`] comparer 布局，同调 `0x16a6d440` 求 hash）。它读的对象是 **`entity[+0x30]`＝一个 `HashSet<int>`
> （int kind 的成员索引）**，**不是** `entity[+0x68]`（组件对象指针列表，真正的存储）。⇒ **guard 看的是索引，读回走的
> 是存储**；两者是不同的集合。**当二者不一致（LIST 有 kind、SET 没有）时，attach 会往 LIST 插进第二条同 kind 组件
> ——重复成立。** 且这不是假想态：引擎自己的取函数 `0x867cc80` 在「SET 说有、LIST 里找不到」时**显式抛异常**
> （`0x867cd30`/`0x867cd4a` → `0x7037f70` il2cpp raise）⇒ 分裂是被当作**必须检出的错误态**写的，不是不可能。
> **⇒ §1.5 结论 1、§0 的「不可能造出重复组件」、§2 的「同一集合」措辞全部作废，改见 §1.6。**
> **⇒ patch 必须在调用前加 LIST 侧检查**（§1.6 给出精确检查；**本轮不产出 patch**）。
> **⇒ 本设计仍为 NOT READY**（多了一条必修的 guard；且 Q-A kind 编号、A3 可调用性仍开放）。

---

## 0. 一句话结论

- **今天的 `create` 一个组件字段都不送**：唯一可承载附加数据的形参 `optional_data` **恒传 `nullptr`**
  （`scene_calls.cpp:47`）；agent 侧请求体只有 `templateId/position/rotation/scale`（`scene_cli.py:258-266`）。
- **但引擎自己的创建例程 `0x8363030` 就在「建时装配组件」**：它取源对象的组件表 `[src+0x68]`，逐件调
  **get-or-create `0x867d2c0`**（**第一条**循环先按 `kind∈{0x2b,0x2c}` 过滤，**第二条**循环不过滤），
  并跑载荷转移 `[rax+0x320]` / `[rax+0x178]`，末尾置 `[new+0x9c]=1`。**它就是 `place_builtin` 的实际落点**：
  `place_builtin`→工厂 `0x106df3c0`（`HR_PLACE_ANCHOR_RVA`）→`0x8364ab0`→`jmp 0x8363030`（本波反汇编复核）。
  ⇒ **「建时装配」不是新能力，是引擎既有路径**；缺的只是**调用者的入口**。
- **【修复 D3】`0x867d2c0` 的「取 vs 建」判据不是未记录的黑盒**：它是一个**共享成员谓词**
  `0x16a68fe0(entity[+0x30], kind)`——**`get`（`0x867cc80`）、`get-or-create`、裸 attach（`0x867c610`）三处都先调它**。
  谓词读的是 **`entity[+0x30]` 内的每实体字典**（buckets `[+0x10]`、entries `[+0x20]`，键=`hash(kind)`，
  hash 由 `0x16a6d440` 算）。⇒ **attach 不是「无条件插入」**：它自己在 `0x867c654` 判谓词为真就**返回 NULL、不插入**；
  插入后又在 `0x867c770` 调 `0x16a6b330(entity[+0x30], kind)` 把 kind 写进**同一字典**。
  所以**组件列表 `entity[+0x68]` 与谓词字典由 attach 一并维护、彼此同步**，`0x867d2c0` **不可能**造出重复组件。
  （上一稿「裸 attach 是无条件插入、必须拒」的论断**被本轮反汇编证伪**；用 `0x867d2c0` 仍是对的，但理由要换成这条。）
  > **⚠️【2026-10-12 推翻】** 加粗那句**错**：`entity[+0x30]` 的**不是**「组件字典」，是**通用 `HashSet<int>.Contains`**
  > 读的**独立**索引集合；guard（读 `entity[+0x30]`）与存储/读回（走 `entity[+0x68]`）**是两个不同结构**，
  > **重复在结构上没有被排除**。**以 §1.6 为准。**
- **本文主设计 = 「一次回调内 create-then-attach」**：在**同一个已复核 context** 里，`place_builtin` 返回、
  `after` 快照复核通过、owner 绑定坐实后，对**恰好一个**请求 kind 调 **`0x867d2c0(owner, kind)`**。
  **全链 9 道守卫**（`G1a/G1b/G2/G3/G4/G5/G6a/G6b/G7′`），**全部 fail-CLOSED**（§4 逐条附反演自查）。
  > **【2026-10-12】改为 10 道**：新增 **`G6-pre`（`COMPONENT_ATTACH_DUPLICATE`）**——第 12 步调用**之前**，
  > 纯内存遍历 `owner[+0x68]` 判重（§1.6.6）。**原 9 道全是 fail-closed 但仍不够**：它们中没有一道读「存储」，
  > 所以分裂态下会放行重复（§1.6.5）。
- **`0x867c610` / `0x867d2c0` 的「可安全调用性」仍是 OPEN**（reconciliation §7）。**处置（修复 D1，改到与 §7 一致）**：
  第一次真机走**专用、单发、已复核的探针动作**以取得 A3 证据；**A3 一旦到手，就按 §7 落到普通 create 路径**——
  **不再宣称「永不搭普通 create 的车」**（该禁令被 `0x8363030` 的引擎既有行为证伪；见 §4 `G7′`）。

---

## 1. 今天的 `create` payload（逐层写全，含结构体）

### 1.1 线序层（队列请求，`scene_cli.py:240-275`）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


闭集键（`normalize_placement` `scene_cli.py:178`）：`{template_id, position, rotation, scale, label}`；
`label` 被显式剔除（`:187-192`）。**没有** `component`/`name`/`tag` 任何一个。

### 1.2 编译层（`build_scene_profile.py`）

`values[]` 宏（`:259` 行 `HR_TEMPLATE_ID`）＋ `HR_POSITION/ROTATION/SCALE`（`:299-308` 区段 emit）
＋ 批量 `HR_PLACEMENT_COUNT/HR_PLACEMENT_TEMPLATE[]/HR_PLACEMENT_TRANSFORM[]`（`:299-308`）
＋ `HR_ACTION={'create':1,'creature-create':1,'save':2,'create-batch':3}`（`:257`）
＋ `HR_PLACE_BUILTIN`（模式字节，默认 1）。请求字典 `request.update(templateId, position, rotation, scale)`
（`:228`）**逐字进 `requestSha256`**——即被复核绑定的字节。

### 1.3 C++ 结构体（`scene_calls.h:30-36`）——**今天的 payload**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**实际工厂调用（`scene_calls.cpp:46-47`）**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


工厂签名（`scene_calls.h:15-19`，11 形参，`__cdecl`）：`(void* context, uint32 template_id, uint8 builtin,
const Vec3* pos, const Vec3* rot, const Vec3* scale, uint32 requested_id, uint8 flag8,
void* optional_data, uint8 flag10, uint8 flag11) -> void* owner`。

**⇒ 结论（结构性、非「没挖到」）**：**今天的 create 不携带任何组件信息，也没有一条字段能携带。** 唯一
「预留但恒空」的位置是 `optional_data`（第 9 形参）。

### 1.4 回执层

`GameSceneActionResult`（`game_scene_action.h:11-23`）**结构里没有组件字段**；`GameEntitySnapshot`
（`game_context_snapshot.h:78-84`）每个实体只有 5 标量 + 3 指针 + 一个不读的 `position[3]`。**回执读不到组件**。

### 1.5 【本波新增，**2026-10-12 已被 §1.6 推翻**】「取/建」的共享判据 `0x16a68fe0`——原稿称「它就是成员谓词」（修复 D3 的全部证据）

> 口径：**当前** `YuanShen.exe`，`.pdata` 有界反汇编（`.runtime/scratch/comp-create/func.py`）。
> `0x16a68fe0` 是干净的函数起点，size **539 B**（`0x16a68fe0..0x16a691fb`）。

**谁调它（四处，全部同一形态：`rcx = entity[+0x30]`，`edx = kind`，`r8 = 一个静态字段`）**：

| 调用点 | 函数 | 作用 |
|---|---|---|
| `0x867ccd7` | **取** `0x867cc80` | 谓词真 → 继续走 `[entity+0x68]` 找回元素；谓词假 → 返回 `null`（`0x867cddc`） |
| `0x867d2ef` | **建或取** `0x867d2c0` | 谓词真 → `call 0x867cc80`（取）；谓词假 → `jmp 0x867c610`（建） |
| `0x867c64d` | **裸 attach** `0x867c610` | 谓词真 → `jne 0x867c717` ⇒ `xor ebx,ebx` ⇒ **返回 NULL，不插入**；谓词假 → 才继续分配/插入 |
| （同族）`0x867d2dd`/`0x867c637` | 两者 | 先 `mov rcx,[entity+0x30]; test rcx,rcx; je 0x4b9c60` —— **`entity[+0x30]` 为空即崩点** |

**谓词体（`0x16a68fe0`，摘要）**：`rsi = entity[+0x30]` ⇒ 取 `[rsi+0x10]`（buckets 对象：`[+0x18]`=count、
`[+0x20]`=int32 数组）、`[rsi+0x20]`（entries 对象：`[+0x18]`=count、`[+0x20]`=**12 B/项** 的 `{key,next,value}`）、
`[rsi+0x18]`；先 `call 0x16a6d440` 得 **`hash = hash(kind)`**，再 `hash % bucketCount` 定位链（`dec` 表头 ⇒ 存的是 idx+1），
逐项比 `entry.key == hash`，命中后解析一个虚方法槽并 `call` 之，**返回其 bool**；未命中返回 0。⇒ **这是「该实体是否已有该 kind」的成员谓词**。

**attach 的双写（所以两套结构同步）**：`0x867c610` 先把新组件指针插进 `entity[+0x68]` 列表（`0x867c710:
mov [rax+rdx*8+0x20], rbx`），**随后**在 `0x867c770` 调 `0x16a6b330(entity[+0x30], kind)`。
`0x16a6b330`（1253 B）读写的正是 `[obj+0x10]/[+0x18]/[+0x20]`，并 `inc dword ptr [rbx+0x28]`（版本号）+
调同一个 hash `0x16a6d440` ⇒ **它就是往谓词字典里 Add(kind)**。

**⇒ 结论【2026-10-12 订正 —— 原 D3 结论 1/2 作废】**：
1. **`0x867d2c0` 会（在结构层面）产生重复组件。** guard 判真只说明 **`entity[+0x30]` 那个 `HashSet<int>` 含 kind**，
   它**从不读** `entity[+0x68]`。⇒ 若两 store 已分裂（LIST 有 kind、SET 无），guard 判假 ⇒ 走 `jmp 0x867c610`
   ⇒ insert（`0x867c710`）⇒ **LIST 里出现第二条同 kind 组件**。**重复没有被函数层排除。**（原结论 1 是把
   「SET 自洽」误当成「LIST 无重」。）
2. 「读回走 `entity[+0x68]`」**仍是有效证据，但它证的是 LIST**——恰恰**不是** guard 读的那个结构。
   原结论 2「上一稿的担心不成立」**不成立**；上一稿的担心**成立**。两 store 由 attach 双写 ⇒ **只保证**
   「从一致态出发、经 attach 后仍一致」，**不保证**「任何写入者都不制造分裂」。
3. **两套结构确实是两个独立 store**（详 §1.6）：`entity[+0x30]`＝`HashSet<int>`（kind 的**成员索引**，int only），
   `entity[+0x68]`＝**组件对象指针列表**（**存储**，comp 对象在 `[+0x20]` 起、步长 8）。**读回主证据取 LIST**，正确且不变；
   `G6b` 的「可选交叉证」应升级为**必查**（见 §1.6）。

### 1.6 【2026-10-12 Q-B 结案】`0x16a68fe0` 究竟是什么 —— 两个结构的权威判定

> 仪器：`.runtime/scratch/comp-create/func.py`（`.pdata` 有界反汇编，**当前** `YuanShen.exe`）。
> **正向控制先过**（§1.6.4）后才采信本节的地址。

#### 1.6.1 地址复核（全部＝`.pdata` 函数起点，size 与 reconciliation 一致）

| 符号 | RVA | size | `.pdata` 起点 |
|---|---|---|---|
| 取 / get | `0x867cc80` | 485 B | ✔ |
| 建 / attach | `0x867c610` | 631 B | ✔ |
| **建或取** / get-or-attach | `0x867d2c0` | 215 B | ✔ |
| **谓词** / `0x16a68fe0` | `0x16a68fe0` | 539 B | ✔ |
| 集合 Add | `0x16a6b330` | 1253 B | ✔ |
| 集合 hash | `0x16a6d440` | 273 B | ✔ |
| 建图例程 | `0x8363030` | 2517 B | ✔ |

#### 1.6.2 `0x16a68fe0(obj, kind, static)` 逐句语义

1. `if (obj[+0x10] == 0) return 0;`（buckets 为空 ⇒ 非成员）。
2. `hash = obj[+0x18].GetHashCode(kind) & 0x7fffffff;`——`0x16a6d440` 对 **`obj[+0x18]`（一个 `IEqualityComparer<int>`）**
   发起**虚调用**（方法经 `[+0xc2]/[+0x88]/[+0xd0]` 方法槽解析）。
3. `idx = hash % buckets.len; e = buckets[idx] - 1;`（表头存 idx+1）。`e < 0` ⇒ **return 0**。
4. 沿链走 entries：**entry = 3×int32**（`[0]`=hashCode，`[1]`=next，`[2]`=**value＝存进去的那个 int**）。
   `entry[0] != hash` ⇒ 沿 `entry[1]` 走；走空 ⇒ **return 0**。
5. `entry[0] == hash` ⇒ **虚调用 `obj[+0x18].Equals(entry[2], kind)`，返回它的 bool**。

⇒ **`0x16a68fe0(obj, kind) ≡ obj.Contains(kind)`，obj 是一个 `HashSet<int>`**（entry 12 B ⟹ `HashSet<int>.Entry`
＝`{int hashCode, int next, T value}`，T=int；若是 `Dictionary<int,X>` 则 entry 为 16 B，**不符**）。
**key 类型＝int（就是 kind 本身，存在 entry[2]）**；hash（由 `0x16a6d440` 算）只是桶选择器。
**⟹ 原文 §1.5「键=hash(kind)」不精确：hash 是桶索引，存的键就是 int kind。**

**旁证（仪器同款）**：`0x16a68fe0` 全局 **153** 个 call site，`0x16a6b330`（同布局的 `HashSet.Add`）**555** 个
——**它们是通用集合方法**，不是组件专用谓词。组件路径只占其中 3 处（`0x867c64d` / `0x867ccd7` / `0x867d2ef`）。

#### 1.6.3 `0x867d2c0` 怎么用它（逐句）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

attach 内：`0x867c64d call 0x16a68fe0`；`0x867c654 jne 0x867c717`（真 ⇒ `xor ebx,ebx; ret`，**不插入**）；
假 ⇒ 分配 comp、写 `comp[+0x20]=entity`/`[+0x28]=type`/`[+0x34]=kind`/`[+0x30]=0`，
**插进 `entity[+0x68]`（`0x867c710`）**，再 `0x867c770 call 0x16a6b330(entity[+0x30], kind)` **写集合**。

**⇒ 判重只读 SET；存储/读回/删链/g（`0x867cc80`）读 LIST。** 删链的对应点：`0xcba3428 cmp ecx,0xb69f28d`
（FNV-1a-UTF16("DeleteComponentForEditObj")，**全库唯一**）→ 该分支 → `0x97e97d0`：`0x97e982d call 0x867cc80`
（经 LIST 取组件）→ `0x97e98bf cmp dword ptr [rdi+0x34], 0x15`（kind 特判）→ `0x867b170` 收尾。

**两个 store 的名与实**：
- `entity[+0x30]`＝**`HashSet<int>` 成员索引**（kind；`[+0x10]` buckets / `[+0x20]` entries / `[+0x18]` comparer）。**派生**。
- `entity[+0x68]`＝**组件对象指针列表**（`[+0x10]` array / `[+0x18]` count / `[+0x1c]` version；元素 8 B 指针，
  `comp[+0x34]`=kind）。**存储 of record**。

#### 1.6.4 【正向控制】删链入口从零重找（先证仪器可信，再信 1.6.1 的地址）

`.runtime/scratch/qb-settle/positive_control.py`（自写，不引旧矿）：
- FNV-1a-32 over UTF-16 **code units**（seed `0x811c9dc5` / prime `0x1000193`）of `DeleteComponentForEditObj`
  ＝ **`0x0b69f28d`**（对照：对 UTF-16**字节**做则得 `0x0b2d255b`，**证明必须按 code unit**）。
- 该 32-bit 常量作为 **LE dword 全库出现恰 1 次**，file offset `0xc35902a` → RVA `0xcba342a`
  → **落在 `.pdata` 函数 `0xcba3130..0xcba43d7`**（＝主 dispatcher）。
- 该函数内 `mov ecx,0x811c9dc5`（`0xcba337e`）、`imul ecx,esi,0x1000193`（`0xcba33a6`）、
  `cmp ecx,0xb69f28d`（`0xcba3428` → `je 0xcba3c87`）——三者齐备。
⇒ **「恰好一次 + 落在 dispatcher + 含 seed/prime」**＝仪器在这份二进制上确实能重现已知真值。1.6.1 的地址由同一仪器读出。

#### 1.6.5 直接回答设计的问题

- **能否重复？** **能**——但**仅当两 store 已分裂**（LIST 含 kind、SET 不含 kind）时。一致态下 attach 双写 ⇒ 不重复。
  **结构上重复没有被排除**：guard 读索引，不看存储。
- **分裂是否只是假想？** **不**——引擎自己的 `0x867cc80` 在「SET 判真、LIST 找不到该 kind」时**显式抛异常**
  （`0x867cd30` / `0x867cd4a` → 组对象 → `0x7037f70`＝il2cpp raise）。**这是被写进代码的错误态**，
  不是「不可能」。（另一向：SET 判假、LIST 有 kind ⇒ 走 attach ⇒ **正是重复的产生点**。）
- **分裂从哪来？** **本轮未穷举写入者**（§8 旧条目仍未清）。已证：**attach 双写**；**create 例程 `0x8363030`
  读源 LIST、经 `0x867d2c0` 写目标两 store**（两次 call 点 `0x836365b`/`0x83637d3`）。**未证**：删/其它路径
  是否只动一处。**因此分裂在「未排除」而非「已证存在」——但对 fail-closed 而言这就够（见下）。**
- **哪个权威？** 对「该实体是否有一个 kind=K 的组件」——**LIST（`entity[+0x68]`）权威**：它持有对象、
  get/删链/创建例程都读它；SET 是**派生的 int 成员索引**，**结构上根本无法表示重复**（int 只会有一个）。
  两者不一致时**没有一方可信**（引擎自身当错误抛异常）⇒ **唯一安全动作＝拒绝**（fail-closed）。

#### 1.6.6 patch 必须做的检查（**本轮不产出 patch**）

在 §3.2 步 12（`0x867d2c0` 之前）**新增 G6-pre（LIST 侧判重，纯内存、无 call）**：
1. 读 `owner[+0x68]`；若为 `null` ⇒ **拒**（fail-closed）。
2. 记 `n = list[+0x18]`、`arr = list[+0x10]`；`0 ≤ n ≤ 上限`；`arr != null`；`n ≤ arr[+0x18]`（越界即拒）。
3. 遍历 `i<n`：`comp = arr[+0x20 + i*8]`；`comp != null`；**若 `comp[+0x34] == kind` ⇒ 拒**
   （码 `COMPONENT_ATTACH_DUPLICATE`）。**这一步读的就是读回读的那个结构**——guard 与 read-back 从此同源。
4. **（强制，非可选——见 §1.7.3(ii)：这是唯一读第二写目标的分支）** 再读 SET：`0x16a68fe0(owner[+0x30], kind)`；
   **若 SET 判假而 LIST 命中（或反之）⇒ 记 `COMPONENT_STORE_DIVERGENT` 并拒**——因为引擎自己把分裂当错误（§1.6.5）。
   `owner[+0x30]==null` 亦 ⇒ 拒（`COMPONENT_ATTACH_SET_NULL`；attach 在 `:637` 即 NRE）。
   **精确分支表见 §1.7.2**。
- **必须读的结构**：**LIST `entity[+0x68]`**（存储/权威）。**只读 SET 不够**（那正是当前缺陷）。
- `G6b` 的「可选交叉证」**升级为必查**（同一理由：两 store 不一致要被拒，不是被忽略）。

### 1.7 【M1 任务，2026-10-12】真正有效的 guard：规格 + 反演/偏覆自查 + kind 锚定关系

> **口径**：纯离线、只读、**未执行任何 native 调用**、未连桥、未发报文、未写存档、未读图片/PDF。
> 仪器＝`.runtime/scratch/comp-create/func.py`（`.pdata` 有界反汇编，**当前** `YuanShen.exe` 445,006,744 B）。
> **前提（本任务给定的判决，本节不重开）**：重复插入**在结构上没有被排除**（§1.6）。

#### 1.7.1 地址在**当前**二进制重新导出（全部＝`.pdata` 函数起点，size 与 §1.6.1 一致）

| 符号 | RVA | size | 起点 | 关键内点（本波逐条核对） |
|---|---|---|---|---|
| **attach** | `0x867c610` | **631 B** | ✔ | `:637` 读 `[rsi+0x30]`（null→`0x4b9c60` NRE）；`:64d` `call 0x16a68fe0`；`:654` `jne 0x867c717`（→`xor ebx,ebx`）**不插入**；`:710` `mov [rax+rdx*8+0x20], rbx` **插 LIST**；`:770` `call 0x16a6b330` **写 SET**；`:775` `cmp byte [rsi+0x9c],0` |
| **get** | `0x867cc80` | **485 B** | ✔ | `:cd7` `call 0x16a68fe0`；`:cddc` 假→`xor ebx,ebx`；`:ce4` 读 `[rbx+0x68]`；`:cf1` count；`:d12` `mov rbx,[rax+rdx*8+0x20]`；`:d20` `cmp [rbx+0x34],edi`；**raise `0x867cd30`**（count≤0 或走空）/ **`0x867cd4a`**（SET 或 LIST 为 null）→ 二者经 `:d5b..:dd5` `call 0x7037f70` |
| **get-or-create** | `0x867d2c0` | **215 B** | ✔ | `:2ef` `call 0x16a68fe0`；`:2f6` 假→`:318` tail-jmp `0x867c610`；`:301` 真→`call 0x867cc80` |
| **谓词 `HashSet<int>.Contains`** | `0x16a68fe0` | **539 B** | ✔ | `[+0x10]` buckets（count `[+0x18]`、int 数组 `[+0x20]`，存 idx+1）；`[+0x20]` entries（12 B/项，`{hashCode,next,value}`）；`[+0x18]` comparer |
| **`HashSet<int>.Add`** | `0x16a6b330` | **1253 B** | ✔ | 同布局 |
| **raise 入口** | `0x7037f70` | **517 B** | ✔ | `0x867cd30`/`0x867cd4a` 两条都汇到它的 `call` |
| NRE thunk | `0x4b9c60` | **10 B** | ✔ | → `0x51b9b0` |
| index raise | `0x1972ff30` | **64 B** | ✔ | get `:ce5f` 用（找到的 index ≥ count） |

**仪器说明**：以上均为 `.pdata` 边界内的**有界反汇编**；`.pdata` 表本身即 `PE` 异常目录，起点/size 由表读出，
**不靠人工猜长度**。四处函数起点冲突＝0。

#### 1.7.2 guard 规格（**顺序即依赖**；每一分支的动作写死）

> guard ＝ **`G6-pre`**，位置：`G1a/G1b/G2/G3` 之后、`0x867d2c0` 调用**之前**（即 §3.2 步 12）。
> **owner 不重求**：直接用 `G1b` 身份坐实过的那个 `owner`（guard 自身**不生产** owner）。

**必须读的结构（顺序）**：

| # | 读 | 失败（FALSE / 结构不自洽）时 | 码 |
|---|---|---|---|
| 0 | `owner`（前置，已由 `G1a`+`G1b`+`G2` 绑定非空） | —（guard 只消费，不产出） | — |
| 1 | `L = owner[+0x68]` | `L == null` ⇒ **拒** | `COMPONENT_ATTACH_LIST_NULL` |
| 2 | `arr = L[+0x10]`；`n = L[+0x18]`；`cap = arr[+0x18]` | `arr == null` 或 `n < 0` 或 `n > cap` ⇒ **拒** | `COMPONENT_ATTACH_LIST_INCOHERENT` |
| 3 | 遍历 `i ∈ [0,n)`：`c = arr[+0x20 + i*8]` | `c == null` ⇒ **拒**（结构不自洽） | `COMPONENT_ATTACH_LIST_INCOHERENT` |
| 3′ | 同一次遍历：`c[+0x34]` | `c[+0x34] == kind` ⇒ **拒** | **`COMPONENT_ATTACH_DUPLICATE`** |
| 4 | `s = owner[+0x30]`；`hit = 0x16a68fe0(s, kind, static)`（只读） | `s == null` ⇒ **拒**；或 `hit == true` 而第 3 步**无命中** ⇒ **拒** | `COMPONENT_ATTACH_SET_NULL` / **`COMPONENT_STORE_DIVERGENT`** |
| — | 仅当 1–4 全过（`L` 自洽、LIST 无该 kind、SET 亦判无）⇒ **放行**，同一 `owner` 交给 `0x867d2c0` | — | — |

**为什么是这些偏移**：第 1–3 步读的 `owner[+0x68] → [+0x10] array → 元素基址 +0x20 / 步长 8 → comp[+0x34]`
与 **attach 的写点 `:710`（`mov [rax+rdx*8+0x20], rbx`）**和 **get 的读点 `:d12`（`mov rbx,[rax+rdx*8+0x20]`）逐字同源**——
guard、写、读回三者从此读**同一个对象、同一组偏移**。

#### 1.7.3 两类失败模式自查

**(i) 反演（inversion）**——**无**。guard 的**每一条 FALSE / 不自洽分支都汇入「拒＝不调用」**；
guard **不构造** owner、不把 null 或未验证 owner 交给 `0x867d2c0`。与上一稿被 REFUTED 的形态
（「owner 非空则拒」⇒ 反演后以 null owner 调用）**正相反**：本条的正确方向就是「**LIST 命中 ⇒ 拒**」，
它的**反面**（LIST 无该 kind）**才是**放行分支，而放行所依赖的 owner 非空由 `G1a/G2` **先**坐实。
⇒ **guard 必须排在 `G1a/G1b/G2` 之后**（否则其放行分支会依赖未坐实的 owner）——**本规格已如此排序**。
**负控制**：离线把步骤 0 的 owner 置 `null` ⇒ 必须由 `G1a`（而非 guard）翻红 ⇒ 证明 guard 不承担 owner 校验。

**(ii) 偏覆（partial coverage）**——**已闭合，但留一条必须补的残余**。
当前设计的缺陷**正是**「guard 读 `entity[+0x30]`（SET），代码写 `entity[+0x68]`（LIST）」。
本 guard 的第 1–3′ 步读 **LIST**＝**attach 的写目标**，覆盖闭合。
**残余**：attach **双写**（LIST `:710` + SET `:770`）；**只读 LIST 的 guard 看不见「SET 有、LIST 无」那一向**。
该向**不会**造重复（attach 自己的 `SET.Contains` 为真即 `:654→:717` 空手而归），
但会让 `get` 的 `:867cd30` raise 命中（引擎当错误态）——故第 4 步的 **SET 交叉证必须是「必查」而非「可选」**：
它是唯一读**第二写目标**的分支。**⇒ 本条把 §1.6.6 第 4 步由「可选、强化」升为「强制」。**

#### 1.7.4 kind 仍未锚定（A1/A2）时，guard 能否使该路线 SAFE？

**不能单独成立；两者都必须先结案。** 理由分三层：

1. **规格层**：guard 是**自足**的——它比较的是 `comp[+0x34]` 与你**即将传给 attach 的同一个 int**（`kind`），
   **不需要**知道哪个 int 代表 M1 的碰撞触发器。就此而言 guard **现在就能写、能离线测**（纯两结构的内存函数）。
2. **效力层**：guard 的「防重」结论**预设**「你传的 `kind` 与 `comp[+0x34]` 在**同一编号空间**」——这正是 **A1**。
   若 A1 假，guard 会**静默不命中**（永不翻红）：既阻止不了语义上同一组件的重复，你还会挂上**错映射**的组件。
   **⇒ 未锚定的 guard，其「放行」分支证明不了任何事。**
3. **可调用层**：即便 A1 成立、guard 完美，**A3**（`0x867d2c0`/`0x867c610` 在活进程可安全调用）**仍未被证**——
   guard 管的是「要不要调」，管不了「调了会不会崩/会不会破坏别的字段」（§3.4 的载荷转移、`[rax+0x1d0]`）。

**⇒ 判决**：guard **是必要条件，不是充分条件**。任何 patch 若要**声称安全**，**必须同时**结清
(a) **A1/A2（kind 编号锚定）**、(b) **A3（可安全调用）**、(c) 第 4 步 **`COMPONENT_STORE_DIVERGENT` 必查**是否落地。
**在 (a)(b) 未结案前，patch 不适用**——但 guard 本身可**先行离线实现并负控制测试**（不依赖真机）。
**本轮不产出 patch。**

---

## 2. 要对账的容器事实（引 reconciliation，已复算）

| 项 | 值 | 出处 |
|---|---|---|
| 容器 | `entity[+0x68]`，**指针列表**：`+0x10`=array、`+0x18`=count、`+0x1c`=version，步长 **8** | `RECONCILED.md §2/§6` |
| 组件对象 | `comp[+0x20]`=owner entity、`comp[+0x28]`=type/config、`comp[+0x30]`=**byte** enabled、`comp[+0x34]`=**int32 kind** | 同上 |
| 取 | `0x867cc80`（485 B）— **先调谓词 `0x16a68fe0`（`0x867ccd7`）**，真才走 `[entity+0x68]`，假返回 null | 同上 §2 + 本波 §1.5 |
| **建或取** | **`0x867d2c0`**（215 B）— 先调谓词（`0x867d2ef`）：真→ `call 0x867cc80`（取）；假→ `jmp 0x867c610`（建） | 同上 + 本波 §1.5 |
| **attach** | `0x867c610`（631 B）— **先调谓词 `0x16a68fe0`（`0x867c64d`），真则返回 NULL 不插入**；否则 分配 + 写字段 + **插入 `entity[+0x68]`** + **`call 0x16a6b330(entity[+0x30],kind)` 写谓词字典（`0x867c770`）** + `call [rax+0x1d0]` | 同上 + 本波 §1.5 |
| 收尾 | `0x867b170`（150 B）| 同上 |
| **成员谓词** | **`0x16a68fe0`（539 B）＝通用 `HashSet<int>.Contains`**：`(set, kind, static) → bool`。读 `set[+0x10]` buckets / `set[+0x20]` entries（**12 B/项＝`{hashCode,next,value=int kind}`**），hash 由 `0x16a6d440` 算（＝`set[+0x18]` 那个 `IEqualityComparer<int>` 的虚调用），末了虚调 `Equals(entry.value, kind)` 决定返回。**组件路径只占 3/153 个 call site** | **§1.6（2026-10-12，当前二进制）** |
| 字典 Add | `0x16a6b330`（1253 B）＝**同布局的 `HashSet<int>.Add`**：读写 `[+0x10]/[+0x18]/[+0x20]`，同调 `0x16a6d440`，虚调 comparer。**全库 555 个 call site（通用方法）** | **§1.6** |
| **两 store 判据** | `entity[+0x30]`＝`HashSet<int>`（**派生成员索引**，int only）；`entity[+0x68]`＝**组件对象指针列表**（**存储 of record**）。**guard 读前者、读回/删链/get 读后者 ⇒ 二者是不同集合，会分裂** | **§1.6** |
| 创建例程 | `0x8363030`（2517 B）：遍历源对象组件表 `[src+0x68]`；**第 1 环** `lea eax,[rdx-0x2b]; cmp eax,1` ⇒ 仅 `{0x2b,0x2c}` → `call 0x867d2c0`（`0x836365b`）；**第 2 环不过滤** → `call 0x867d2c0`（`0x83637d3`）；各跑 `[rax+0x320]`/`[rax+0x178]`；末尾 `[r14+0x9c]=1` | 同上 §3（本波复核两处 call 点） |
| **创建例程的落点** | `place_builtin` 的工厂 = `HR_PLACE_ANCHOR_RVA` = **`0x106df3c0`**（`profiles/genshin-cn-7.1.0-readonly.json`）→ `call 0x8364ab0` → `jmp 0x8363030` | 本波复核 |
| **attach 的首访问** | `mov rcx,[rsi+0x30]; test rcx,rcx; je 0x4b9c60` —— **null entity/sub-object 是崩点** | 同上 §6.5 |
| **kind 表** | 唯一**封闭枚举**：前端 `QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x`（`.runtime/editor-catalog/resolved/…jaUof90C3Ncl5BAJri4x.cs:3-51`），**46 项**（**原记 47，已更正**；数法：`grep -c BeyondCompType` = 46 行成员，值域 `0..47` 去 `{2,10}` 亦得 46；见 `COLLISION-COMPONENT-ID.md` §1.2），值域 `0..47` 去掉 `{2,10}`（含哨兵 `None=0`、`Arraysize=47`） | **`COMPONENT-WRITER-MINE.md:80-92`**（引上面那份 `.cs`）——**不是** `RECONCILED.md` |

---

## 3. 设计：组件随创建一起长出来

### 3.1 为什么必须「建时 / 同回调」而不是「建后另发一次」

`scene_cli save` 写的是**游戏进程**，桥改的是**编辑器内存**（`CLAUDE.md §二`）。**建后另起一个 UAC 回调**去补组件，
会把「已建实体」与「加组件」放进**两个不同的已复核 context**——基线必然漂移，且第二次回调拿不到第一次的
owner 指针。所以组件必须**在创建那一次回调内**种下，正如 transform 只能在 create 那一刻给坐标。

### 3.2 主设计（PROPOSED）：一次回调内 `create → guarded get-or-create`

**payload 扩展**（在被复核的 profile 里，成为 `requestSha256` 的一部分）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


C++ 侧 `PlacementInput` **不改**；新增一个**并列**的 `ComponentAttachment { uint32 kind; }` 数组与计数宏
`HR_ATTACH_KIND[] / HR_ATTACH_COUNT`（默认 0 = 今天的行为，逐字节不变）。

**执行序（`ExecuteGameSceneAction`，HR_ACTION==1 与 ==3 共用子过程）——【修复 D2：每一步的守卫都在它写的那个位置可求值】**

> **改动摘要**：`G1` **拆成 `G1a`/`G1b`**（原先要 `after` 的条款被放在抓 `after` 之前 ⇒ 不可实现）；
> `G4`/`G5`/`G7′` 前移到**派发前与任何 native call 之前**（它们只吃请求/动作，不吃快照）。

**A. 派发前（agent 侧，编译期/队列前；无 UAC、无 native call）**
1. **G4** kind 合法（闭合枚举内、非哨兵、非 delete 特判值）。
2. **G5** `HR_ATTACH_COUNT ≤ 1` 且该 kind 已编译进**被复核 profile**（字节进 `requestSha256`）。
3. **G7′** 动作分域（见 §4）：本 kind 有 create 期先例，或本动作就是专用探针。

**B. 回调内（既有前置先跑，全部 fail-closed）**
4. 既有前置全部保留（snapshot 完整、strict baseline identity、anchors、PID/TID/deadline）——**不过即拒，先于任何 call**。
5. `place_builtin(...)`（不变）。
6. **G1a**：`placed.code == returned` **且** `placed.owner != nullptr`（两者 `place_builtin` 一返回即可读，**不需要 `after`**）。
   不过 → `status=7`，**不进 B7**、不回滚已建实体。
7. 抓 `after` 快照（不变）。
8. **G6a**：`after` 完整、`entityValidEntries == before+1`、旧实体全保留（既有后置）——不过即拒 attach。
9. **G1b**：`placed.owner` == `after` 中**新增那个**实体的 `owner`（身份匹配；**这一步才需要 `after`**）。
   不过 → 拒 attach（实体保留）。
10. **G2**：`VirtualQuery` 守卫读 `[owner+0x30]` 成功**且** `!=0`（这正是 attach/get 的首访问崩点）。
11. **G3**：守卫读 `[owner+0x9c]` 成功**且** `==1`。
12. **【2026-10-12 新增】** `G6-pre`：**纯内存遍历 `owner[+0x68]`** 判重（无任一 `comp[+0x34]==kind`，
    且 list 结构自洽）——命中/不自洽即拒。**必须在下一步之前**（guard 必须读存储，§1.6.6）。
13. 对**恰好一个**请求 kind：`get_or_create = (void*(*)(void*,uint32))(moduleBase + 0x867d2c0)`；
    `get_or_create(owner, kind)`。**（本回调内对 native 的唯一一次调用。）**
14. **G6b**：**主证据 = 纯内存遍历** `owner[+0x68]`（`+0x10` array、`+0x18` count，步长 8）找 `comp[+0x34]==kind`
    —— **不发起任何 native call**。**【2026-10-12 升级为必查】** 调**只读谓词** `0x16a68fe0(owner[+0x30], kind)`
    （`get` 用的同一个），确认两 store **一致**；**不一致 ⇒ 拒**（见 §1.6.5/§1.6.6）。
15. 结果写入回执新字段（`attachedKind`, `attachReadback`, `ownerState9c`, `subObjectNonZero`）。

**为什么仍用 `0x867d2c0`（建或取）**：**理由【修复 D3】不是**「裸 attach 无条件插入」——**那句话是错的**，
裸 attach 也自判同一谓词、已有则空手而归（§1.5）。**真正的理由**：`0x867d2c0` 是**引擎在建时用的那个入口**
（`0x8363030` 两处都调它），走它与引擎行为同构；它「有则取」的语义让**重复调用幂等**，从而即使本回调被重放也不叠加。
**结论不变（用 `0x867d2c0`），论据换成这两条。**

### 3.3 备选（明确**拒绝**作为第一步）：`optional_data` 承载

把组件 spec 结构塞进第 9 形参 `optional_data`（今天恒 `nullptr`）。**拒绝理由**：
`0x106df3c0`/`0x8363030` 对 arg9 的**消费方式未知**（`[ASSUMED]`）。把**未经证实的结构体指针**交给工厂，
正是本波 hard rule 禁止的「以未验证的实参发起 native 调用」。**不是「做不到」，是「不许不走探针就做」。**
→ 若日后静态反出 arg9 的读法，可再评估。

### 3.4 两条 caveat 的处置（前一位对手方指出）

- **(a) 载荷转移 `[rax+0x320]` / `[rax+0x178]`**：创建例程**对每个源组件**在 `0x867d2c0` 之后跑这两次虚调用
  （`0x8363671`/`0x8363690`，第二环 `0x83637e9`/`0x8363808`）。我们的 `0x867d2c0` **不跑**它们 ⇒
  新建组件**极可能是 default/unconfigured**（`[ASSUMED]`）。**处置**：设计**不声称**组件被正确配置；
  §4 `G6b` 的读回只证「kind 存在」，**不证** payload 正确；是否补跑这两个虚调用（签名未知）列为**下一步静态任务**，
  **不在本设计内实现**。
- **(b) `[entity+0x9c]` 状态（本波反汇编坐实分支差异）**：attach **自己**读它——`0x867c775:
  cmp byte ptr [rsi+0x9c], 0; je 0x867c7a8`：**`==0` 则跳过末尾的 `call [rax+0x1d0]`；`!=0` 则执行之**。
  创建例程**期间** `==0`（末尾 `0x8363926: mov byte [r14+0x9c],1` 才置 1），故引擎建时那几次 attach **不跑 `[rax+0x1d0]`**；
  我们的调用在 `place_builtin` **返回后**（`==1`）⇒ **会**跑 `[rax+0x1d0]`。**这是一条真实、可观测的分支差异**。
  **处置**：`G3` 只接受 `==1`；不接受就拒并记录**观测值**。首个真机把 0/1 与 `[rax+0x1d0]` 的后果一并定死（新 A8）。

---

## 4. 安全闸门（逐条：条件 / 假分支 / 为何是安全方向）——**反演自查**

> **反演自查规则（写进实现注释）**：任何形如「**owner 非空则拒**」的谓词 = **INVERTED = 禁止**。
> 正确的方向只有一种：**owner == NULL ⇒ 拒（不调用）**。每个守卫必须能在离线测试里被**负控制**翻红。

**守卫的求值阶段**：A = 派发前（无 native call）；B = 回调内、任何 native call 之前；C = `place_builtin` 之后。

| 码 | 阶段 | 条件（TRUE = 允许继续） | FALSE 时做什么 | 为何这是安全方向 |
|---|---|---|---|---|
| **G1a** `COMPONENT_ATTACH_OWNER_UNBOUND` | C | `placed.code==returned` **且** `placed.owner!=nullptr` | **不进 attach**；`status=7`；**不回滚已建实体** | 假分支**恰是**上一稿崩游戏的输入（null → `[rsi+0x30]` 解引用）。**拒在 null，调在非 null**，与反演相反 |
| **G1b** `COMPONENT_ATTACH_OWNER_MISMATCH` | C（需 `after`） | `placed.owner` == `after` 中**新增实体**的 `owner` | 拒 attach；实体保留 | 只对**本次 `place_builtin` 亲自建的**实体动手；身份对不上就不是我们的实体 ⇒ 拒 |
| **G2** `COMPONENT_ATTACH_SUBOBJECT_NULL` | C | `VirtualQuery` 守卫读 `[owner+0x30]` 成功**且**值 `!=0` | 拒 attach；实体保留 | get/get-or-create/attach **三处首访问**即 `test rcx,rcx; je 0x4b9c60`；sub-object 空是我们无法推理的分支，**读不到=拒** |
| **G3** `COMPONENT_ATTACH_STATE_UNEXPECTED` | C | 守卫读 `[owner+0x9c]` 成功**且** `==1` | 拒 attach；记录**观测字节** | 创建期是 0、末尾置 1（`0x8363926`）；**只接受我们预期的那个值**，其余一律拒（fail-closed） |
| **G4** `COMPONENT_ATTACH_KIND_ILLEGAL` | A | `kind` ∈ **前端封闭枚举 `jaUof90C3Ncl5BAJri4x`** 的成员值（`0..47` 去 `{2,10}`），**且** `kind ∉ {0, 47}`（哨兵 `None`/`Arraysize`） | agent 侧**派发前**即拒（编译前）；C++ 侧再拒一次 | 这是**唯一有出处的**封闭枚举（`COMPONENT-WRITER-MINE.md:80-92`）。**上一稿的 `[0..20,22..60,66,67,68,69,74,78]`（66 种）全仓无出处、且与枚举冲突，已弃用**（见下「G4 更正」） |
| **G5** `COMPONENT_ATTACH_UNREVIEWED` | A | `HR_ATTACH_COUNT ≤ 1` **且** kind 已编译进被复核 profile（在 `requestSha256` 内） | 派发前拒（无 UAC） | 复核门把字节级身份钉死；**未复核的 kind 不得进回调** |
| **G6a** `COMPONENT_ATTACH_POSTCONDITION` | C | `after` 完整、`entityValidEntries == before+1`、旧实体全保留（既有后置） | 拒 attach；实体保留 | 建实体这条后置**与组件无关也必须过**；不过是既有质量的失败，不该被组件路径掩盖 |
| **G6-pre** `COMPONENT_ATTACH_DUPLICATE` 【**2026-10-12 新增，补 D3**】 | B（**call 之前**） | 纯内存遍历 `owner[+0x68]`（array `[+0x10]`、count `[+0x18]`、步长 8）：**无任一 `comp[+0x34]==kind`**；且 `owner[+0x68]!=null`、`n≤arr[+0x18]` | 拒 attach；实体保留 | **guard 必须读「存储」**——原设计只读 `entity[+0x30]`（派生索引）⇒ 分裂时会插重复。**此门让 guard 与 read-back 同源**（§1.6.6） |
| **G6b** `COMPONENT_ATTACH_READBACK_MISSING` | C（call 后） | **主**：纯内存遍历 `owner[+0x68]` 找到 `comp[+0x34]==kind`；**交叉证升级为必查**：只读谓词 `0x16a68fe0(owner[+0x30],kind)` 为真；**两 store 不一致 ⇒ 拒** | 报失败；**不重试、不回滚** | 读回**主证据不发起 native call**；交叉证只读（同款 `HashSet.Contains`）；读回失败**绝不**触发第二次变更（§1.6.5/§1.6.6） |
| **G7′** `COMPONENT_ATTACH_SCOPE` | A | 本次动作 = 专用探针，**或**（kind 有 create 期先例**且**走 `§7` 的普通 create 子过程） | 拒整个请求（派发前） | 见下「G7 更正」 |

**「失败模式必须是 null/未验证 owner 的 native 调用」= 本文显式拒绝的形态。** 全文**没有**任何路径会在
owner 为空、未绑定或身份未坐实时调用 `0x867c610` / `0x867d2c0`。

### 4.1 反演自查逐条（(i) 条件 /(ii) 假分支 /(iii) 为何安全）

> 规则：**任何守卫的 FALSE 分支若导致「以 null 或未验证 owner 发起 native call」＝ 缺陷，必须大声报出。**
> 下表逐条核对：**没有一条**的 FALSE 分支会走到 native call——**FALSE 一律等于「不调用」**。

| 码 | (i) 精确条件 | (ii) FALSE 干什么 | (iii) 安全方向 |
|---|---|---|---|
| G1a | `code==returned && owner!=nullptr` | 不调 attach；`status=7` | FALSE = owner 为 null 或调用未成功 ⇒ **不调用**，正在于拒绝崩点输入 |
| G1b | `owner == 新增实体的 owner` | 拒 attach | FALSE = 不是我们的实体 ⇒ **不调用** |
| G2 | `[owner+0x30] != 0`（守卫读） | 拒 attach | FALSE = 空 ⇒ **不调用**（`je 0x4b9c60` 崩点） |
| G3 | `[owner+0x9c] == 1` | 拒 attach；记录观测 | FALSE = 非预期态 ⇒ **不调用** |
| G4 | kind 合法（枚举内、非哨兵） | 派发前拒 | FALSE = 越界 kind ⇒ **不调用** |
| G5 | `count<=1 && kind 已复核` | 派发前拒 | FALSE = 未复核 ⇒ **不调用** |
| G6a | after 完整/`+1`/保留 | 拒 attach | FALSE = 后置失败 ⇒ **不调用** |
| G6b | 列表命中（主）；可选：谓词真 | 报失败，不重试/不回滚 | FALSE = 读回没证据 ⇒ **不再调用**（读回主证据是纯读；可选交叉证也只读） |
| G7′ | 动作/kind 分域通过 | 派发前拒 | FALSE = 越域 ⇒ **不调用** |

**结论**：**没有发现「FALSE 分支导致 native 调用」的守卫**——即上一稿那种「owner 非空则拒」的反演**已不存在**。
每个守卫的 FALSE 分支都汇入「不调用」。

### 4.2 G4 更正（修复 D4：张冠李戴 + 无出处）

- **旧写**：`kind ∈ {0..20,22..60,66,67,68,69,74,78}`（66 种），出处标 `RECONCILED.md`。
- **事实**：`RECONCILED.md` **不含任何 kind 表**（它只说 `comp[+0x34]==0x15` 是「某个 kind」）。
  全仓（含 `.runtime/`，`grep -rI` 复核）检索该字面量 **只命中本文件自身** ⇒ **该 66 种集合在本仓没有任何出处**。
- **真正的出处**：前端**封闭枚举** `QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x`
  （`.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-51`，**46 项**；原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2），
  被 `docs/research/reverse-eng-20261010/COMPONENT-WRITER-MINE.md:80-92` 列成表；
  该 doc 用的是**这份 `.cs` 的逐行枚举**（其 §2.2 明写页/行号）。
- **新 G4 集合**：枚举成员值 `0..47` 去掉枚举里**缺席的** `{2,10}`，再去哨兵 `None=0`/`Arraysize=47`。
- **前置假设**：native `comp[+0x34]` 值 == 前端枚举值（A1）。**A1 未证**，但本波多了**两条**吻合值支持它
  （见 §5 A1），故 G4 在 A1 下车。

### 4.3 G7 更正（修复 D1：`§7` 与 `G7` 不能同时成立）

- **冲突**：`§3.2/§7` 把 attach 放进普通 create 子过程（`HR_ACTION==1/==3`）；`§0/G7` 又说「永不搭普通 create 的车」。
- **反汇编判决（不凭偏好）**：`0x867d2c0` **本来就在普通 create 路径上**——`place_builtin` 的工厂
  `HR_PLACE_ANCHOR_RVA = 0x106df3c0` → `call 0x8364ab0` → `jmp 0x8363030`，而 `0x8363030` 在
  **`0x836365b`** 与 **`0x83637d3`** **两次** `call 0x867d2c0`。⇒ **「禁普通 create」是伪命题**。
- **因此 `G7` 必须重写**（不是重写 `§7`）。新 `G7′` 保留**原本的安全意图**，但落在一个**真的可判定**的域上：
  - 与**专用探针动作**：始终允许（首次真机取证）。
  - 与**普通 create**：允许，但（a）owner 必须是**同回调内 `place_builtin` 亲自建的**实体（`G1b` 管），
    （b）**每回调至多一个 kind**（`G5` 管），（c）**必须已取得 A3 证据**——即「先跑探针拿到 `0x867d2c0`
    不崩 + 读回见 kind + save 后关卡一致」，再放开到普通 create。
- **它不再是「永不」，而是「先探针、后放开」**：这条把 `§0` 的谨慎与 `§7` 的落点**同时满足**，矛盾消解。

---

## 5. PROVEN vs ASSUMED（不把假设当已证）

**PROVEN（reconciliation 在当前二进制已复算）**：
1. 容器 `entity[+0x68]`；`comp[+0x34]`=int32 kind；`comp[+0x30]`=byte；取/建/建或取/收尾 = `0x867cc80`/`0x867c610`/`0x867d2c0`/`0x867b170`，size 485/631/215/150。
2. attach 首访问 `[rsi+0x30]` test-je ⇒ **null 是崩点**。
3. 创建例程 `0x8363030` 对 {`0x2b`,`0x2c`} 调 `0x867d2c0`，每组件 `[rax+0x178]`。
4. 今天的 create **不送组件**（`optional_data=nullptr`，源码直读）。
5. 回执/快照结构**无组件字段**（结构性负结论）。

**PROVEN（本波 2026-10-11 新增，`.pdata` 有界反汇编复核当前二进制）**：
6. **落点链**：`place_builtin` 工厂 = `HR_PLACE_ANCHOR_RVA = 0x106df3c0`（`profiles/genshin-cn-7.1.0-readonly.json`）→ `call 0x8364ab0` → `jmp 0x8363030`；`0x8363030` 于 `0x836365b`、`0x83637d3` **两次** `call 0x867d2c0`（第 1 环按 `{0x2b,0x2c}` 过滤，第 2 环不过滤），末尾 `0x8363926` 置 `[r14+0x9c]=1`。⇒ **get-or-create 在普通 create 路径上**（D1 的判决依据）。
7. **共享谓词** `0x16a68fe0`（539 B）被 **get（`0x867ccd7`）/ get-or-create（`0x867d2ef`）/ attach（`0x867c64d`）三处共用**；它读 `entity[+0x30]` 的字典（`[+0x10]` buckets、`[+0x20]` entries 12 B/项）。attach 在 `0x867c654` 判真即 `xor ebx,ebx` **返回 NULL 不插入**（D3 的判决依据）。
8. **双层同步**：attach 插 `entity[+0x68]`（`0x867c710`）**后**在 `0x867c770` 调 `0x16a6b330(entity[+0x30],kind)` 写同一字典（该函数读写 `[+0x10]/[+0x18]/[+0x20]` 并 `inc [obj+0x28]`）。
9. **`[owner+0x9c]` 的分支**：attach 自读它（`0x867c775`），`==0` 跳过 `call [rax+0x1d0]`、`!=0` 执行之。
10. **kind 表的唯一出处**是前端封闭枚举 `.rstrip/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-51`（46 项；原记 47，见 `COLLISION-COMPONENT-ID.md` §1.2），由 `COMPONENT-WRITER-MINE.md:80-92` 列表；上一稿的 66 种集合**全仓 0 出处**（D4 的判决依据）。

**PROVEN（2026-10-12 Q-B 结案，同仪器；正向控制见 §1.6.4）**：
11. **`0x16a68fe0`＝通用 `HashSet<int>.Contains`**（`0x16a6b330`＝配对 `Add`）；读的是 `entity[+0x30]` 那个
    **独立集合**，**不是** `entity[+0x68]`。key＝int kind（entry 12 B：`{hashCode,next,value}`），
    comparer 在 `set[+0x18]`（`IEqualityComparer<int>`），hash 由 `0x16a6d440` 虚调算。**153 / 555 个 call site ＝通用方法**。
12. **guard 只读 SET（`entity[+0x30]`）；存储/读回/删链/get（`0x867cc80`）读 LIST（`entity[+0x68]`）**——两结构不同。
13. **分裂是被写进代码的错误态**：`0x867cc80` 在「SET 判真、LIST 无该 kind」时**抛异常**（`0x867cd30`→`0x7037f70`）。
    ⇒ **重复（LIST 有 kind、SET 无 ⇒ attach 插第二条）在结构上未被排除**；**原 D3 结论作废**（§1.6.5）。

**ASSUMED（并给「单一观察」以转正）**：

| # | 假设 | 单一观察 |
|---|---|---|
| A1 | 原生 `comp[+0x34]` 值 == 前端枚举 `jaUof90C3Ncl5BAJri4x` | **（本波加强）静态二值吻合**：`0x2b=43`(WaterfallComp)、`0x2c=44`(WaterCubeComp) 两个 native 常量都落在枚举内的**具体成员**上；`{43,44}` 恰是普查里两个稀有「水」组件的编号（`PREFAB-COMPONENT-CENSUS-V2.md` §4：各 3 条预制体）。**⚠️ 上一稿把 `0x15=21`(TempAttachPoint) 也列为「吻合值」——已删**：kind **21 缺席**于原生 kind 表 `[0..20,22..60,66,67,68,69,74,78]`，故它**不能**作吻合证据（`0x15` 仅作为删组件链里的特判常量出现，与原生 kind 表是否同源**未证**，见 `COMPONENT-CONTAINER-RECONCILED.md` §6.4）。真机对拍仍取「删一条已知组件看其 `[+0x34]`」 |
| A2 | `kind 8 == Collision` | 同上仪器，取 8 复算（本仓文档自标为假设） |
| A3 | `0x867d2c0` / `0x867c610` **可安全调用** | **专用探针的首个真机**（`G7′` 规定：A3 到手才放开到普通 create）：不崩 + 读回见 kind + 此后 save/读回关卡一致 |
| A4 | `[entity+0x9c]` 的 0→1 语义 & 分支差异 | 真机 create 前后各读该字节一次 |
| A5 | 跳过载荷转移 `[rax+0x320]`/`[rax+0x178]` ⇒ 组件 default | `0x867d2c0` 后读 comp 字段，看是否 disabled/空配置 |
| A6 | `optional_data`(arg9) 语义 | **静态**：反汇编 `0x106df3c0`/`0x8363030` 看 arg9 读法（不需真机） |
| A7 | attach 的 `comp[+0x28]`=type 从何而来 | **静态**：读 `0x867c610` 里 `0x13dddca0(kind)`→type 与 `[rax+0x398]`→kind 的来源 |
| **A8** | `[owner+0x9c]==1` 时跑 `[rax+0x1d0]` 的后果可接受 | **真机**：`G3` 通过（`==1`）的那次 attach 后，关卡仍可读、save 后实体集不变 |

---

## 6. 离线测试计划（**全部不碰机器**）

### 6.1 `tools/game-executor/tests/test_component_at_create_safety.py`（新）
- **源保真**：把 §4 十条守卫（`G1a/G1b/G2/G3/G4/G5/G6a/**G6-pre**/G6b/G7′`）的**精确拼写**与**行号区**绑进断言（弱化/删子句即红）。
- **【2026-10-12 新增】分裂红测**：合成 `(listHasKind=True, setHasKind=False)` ⇒ 必 `COMPONENT_ATTACH_DUPLICATE`（`G6-pre`）；
  `(listHasKind=False, setHasKind=True)` ⇒ 必 `COMPONENT_STORE_DIVERGENT`（`G6b`）——并断言两 case 的 **`attachCalls == 0`**。
  **负控制**：把 `G6-pre` 的子句删掉 ⇒ 上面 `listHasKind=True` 的 case **必须翻红**（证它不能靠 SET 蒙混）。
- **决策模型**：把 `G1a–G7′` 转录成可跑 Python 谓词，用合成 (code, owner, newEntityOwner, subObject, state9c, kind, count) 驱动；
  每个 case 断言**精确命名码**，并断言 **`attachCalls == 0`**（拒绝时**一次调用都没发生**）。
- **反演红测（关键）**：`owner==NULL` ⇒ 必 `COMPONENT_ATTACH_OWNER_UNBOUND`（`G1a`）；并断言源码**不含**「非空则拒」的形态。
- **步序测（新，防 D2 回归）**：断言 `G1b` 在**抓 `after` 之后**求值、`G4/G5/G7′` 在**任何 `place_builtin` 之前**求值——即每个 guard 的**求值序**与其**数据依赖**一致。
- **负控制**：逐条删一个子句 → 其 pinned case 必翻。

### 6.2 `tools/game-executor/tests/test_component_at_create_payload.py`（新）
- 断言编译出的 `target_config.h` 含 `HR_ATTACH_KIND/HR_ATTACH_COUNT`；`HR_ATTACH_COUNT==0` 时**逐字节等于今天**。
- 断言请求字典含 `components` 且进 `requestSha256`；缺 `--review` ⇒ 派发前拒。
- 断言（纯 Python 转录）`HR_ATTACH_COUNT>1` 或 `kind ∉ 枚举` 或 `kind ∈ {0,47}`（`G4` 新集）⇒ 拒。

### 6.3 `tests/scene_calls_test.cpp` 扩展（同风格 fake 符号）
- fake `get_or_create(entity, kind)` **捕获实参**：断言**恰好一次**、`entity == fake factory 返回的 owner`、
  **绝不为 `nullptr`**、`kind` 与输入一致；fake factory 返回 `nullptr` ⇒ 断言 `attachCalls==0`。
- 保留既有 106 行全部断言（`HR_ATTACH_COUNT` 缺省 = 不改变今天行为）。

### 6.4 纯 C++ 守卫测试（照 `reviewed_action_guard_test.cpp`）
- 驱动 `ExecuteGameSceneAction`：owner=null / 状态字节不可读 / count=2 / kind=99（越界）四种输入 ⇒ 断言 **`status != 0` 且未调用 attach**。

**离线做不到**（本设计不声称）：`G7′` 的探针真在活进程里跑；`0x867d2c0` 真不崩；kind 真进容器。

---

## 7. 要改的 pinned 文件（**本设计若不实现即零改动；实现必须改这些**）

> 下面的 `.cpp/.h/.py` **全部在 hard safety rules 的 pinned 清单里**。**本波不实现**；此处**只列行**，
> 供后续在「helper 不在飞行中」时**分阶段落地**。

| 文件 | 行 | 改什么 |
|---|---|---|
| `tools/game-executor/native/game_scene_action.cpp` | **:184-213**（HR_ACTION==1）、**:241-305**（==3） | 按 §3.2 修正后的步序插入 `G1a/G1b/G2/G3/G6a/G6b` 子过程（`G4/G5/G7′` 在更前的回调前置区，不在此两段） |
| `tools/game-executor/native/game_scene_action.h` | **:11-23** | 回执加 `attachedKind/attachReadback/ownerState9c`（或复用 `callCode` 语义位） |
| `tools/game-executor/native/scene_calls.h` | **:15-19**（仅若走 3.3 备选）、**:30-36** | 加 `ComponentAttachment` 并列结构（主设计**不改** `PlacementInput`） |
| `tools/game-executor/scene_cli.py` | **:178-180**（闭集键）、**:187-192**、**:258-268**（queue_request）、**:613-630**（argparse） | 新增 `--component-kind` / 闭集键 `component_kind` |
| `tools/game-executor/build_scene_profile.py` | **:221-232**、**:259-266**、**:299-308** | 生成 `HR_ATTACH_KIND/HR_ATTACH_COUNT`；请求体带 `components` |
| `tools/editor-bridge/elevated-request.py`、`elevated-runner.ps1` | 字段允许集 | 让新字段经队列送达（**pinned：改了打断 helper dispatch**） |

**不改**：`EditorBindingProfile.Generated.cs`、`tools/authoring/author.py`（组件走 call/native，非节点图动作）。
**Adapter/*.cs、ManagedBridge/*.cs、tests、docs 安全**——§6 的测试文件都在安全区。

---

## 8. 边界 / 未决（不许写成「已通」）

- **未运行**：本文全部静态/只读；**未连桥、未发报文、未触碰游戏/编辑器、未写存档、未执行 native 调用、未读图片/PDF**。
- **本波修掉的（D1–D4）**：见文首【2026-10-11 二次修复 pass】与 §4.1–4.3。**判决均为反汇编/检索复核，非偏好。**
- **未证**：`0x867d2c0`/`0x867c610` **可安全调用**（A3）；`[entity+0x9c]` 状态语义与 `[rax+0x1d0]` 后果（A4/A8）；
  载荷转移 `[rax+0x320]`/`[rax+0x178]` 的必要性（A5）；kind 编号空间 A1/A2。
- **本波新增的开放问题**：两套组件 store（`entity[+0x68]` 列表 **与** `entity[+0x30]` 谓词字典）**除 attach 外还有谁写**？
  本轮只证 attach 双写；**没有**遍历全部写入者。`G6b` 因此**要求两 store 同证**（§1.5 结论 3）。
- **【2026-10-12 Q-B 结案】** 上面那条**已部分定案**：两 store 是**不同结构**（`entity[+0x30]`＝`HashSet<int>` 索引；
  `entity[+0x68]`＝组件对象列表＝存储），guard 只读索引 ⇒ **重复未被排除**（§1.6.5）。**新增 `G6-pre` 必读 LIST**（§1.6.6）。
  **仍开放**：**分裂从哪条真实路径产生**（写入者仍未穷举）——但这**不阻塞**加 guard：fail-closed 对「未排除」即足够。
- **READY？＝ NO（本设计仍 NOT READY）**：Q-B 由「设计错」降为「设计需补一道 guard」，但 **(a) Q-A kind 编号（native `comp[+0x34]` 值 ≡ 前端枚举值）仍未证**，
  **(b) A3（`0x867d2c0`/`0x867c610` 可安全调用）仍要真机探针**，**(c) `G6-pre`/`G6b 必查` 尚未写进测试**。
  三者都解决后才可判 READY。**本轮不产出 patch**（该决定属 orchestrator）。
- **【2026-10-12 M1 任务进展，§1.7】**：guard 的**规格已定案**（顺序 + 偏移 + 逐分支动作，§1.7.2），
  且**地址已在当前二进制重新导出**（四处函数起点 + size 全部对上，§1.7.1）。**两类失败模式自查通过**
  （无反转；偏覆已由「读 LIST＝写目标」闭合，SET 交叉证升为强制）。**kind 未锚定 ⇒ guard 是必要而非充分**：
  patch 若以 guard 为安全论据，**必须同时**结清 A1/A2 与 A3（§1.7.4）。guard 本身可**先离线实现 + 负控制**。
- **仍假定**：`comp[+0x34]` 的语义确为「组件 kind」且与前端枚举同空间（A1/A2）；`[entity+0x30]` 确为「本实体已挂 kind 的
  `HashSet<int>`」（由 attach 双写 + get 交叉使用推得，**无类型名**——`obj[+0x18]` 的 comparer 类型名未取）。
- **本设计的能力上限**：即便真机成功，**这仍是「建时种下」**——它**不**给出「改已有实体的组件」（与
  transform 的不对称边界同构：**改已有=没有 setter，建时=可以**）。
- **唯一可信地址来源**：**当前** `YuanShen.exe`（445,006,744 B）。任何引用 `backend.db`/`raw/asm` 的地址先当过期。

*设计，2026-10-11；二次修复 pass，2026-10-11（D1–D4，见文首）；**Q-B 结案 2026-10-12（推翻 D3，§1.6；新增 `G6-pre`）**；
**M1 任务 2026-10-12（§1.7：guard 规格定案 + 当前二进制地址复导 + 反演/偏覆自查；未产出 patch）**。行号 = 本次 checkout 实测。
证据＝对当前 `YuanShen.exe`（445,006,744 B）的 `.pdata` 有界反汇编（`.runtime/scratch/comp-create/func.py`）
＋ 仓内检索（`grep -rI`，非 Grep 工具）。**未实现、未编译、未连桥、未发报文、未触碰游戏/编辑器、未写存档、
未执行任何 native 调用、未读图片/PDF。***
