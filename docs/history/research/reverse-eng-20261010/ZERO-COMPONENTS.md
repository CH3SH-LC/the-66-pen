> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 为什么「每一个实体」都读到 ZERO 个组件 —— ZERO-COMPONENTS

> **任务 #1（判定性）**。**纯源码阅读，未连桥、未发任何报文、未重启 helper、未请求 UAC、未触碰游戏/编辑器、未读任何图片或 PDF、未写 `LocalLow`。**
> 本文件是本次唯一新增/拥有的文件（`docs/research/reverse-eng-20261010/ZERO-COMPONENTS.md`）。
>
> **本轮真机事实（由上游任务给定，非本文件所跑）**：`inspect-entity-components` 真机 ok:true，实体 `1077936129`（土田）`components:[]`，
> 关卡实体 `1094713345`、两个 `默认模版` 也各为 **0**。
>
> **证据来源（全部只读）**
> ① 桥源码 `tools/editor-bridge/Adapter/EntityComponentProbe.cs`（本次逐行读完）；
> ② **7.0 语料** `.runtime/editor-catalog/resolved/`（12375 `.cs`，含 `-> 旧名::新名` 符号注释）；
> ③ **7.1 语料** `.runtime/verification/update-repair-20260925/adapter-port/decomp-7.1/`（12955 `.cs`，**符号已重随机**）；
> ④ 符号映射 `…/adapter-port/merged-symbols-7.1.json`。
> 全部检索用 **Bash `rg`/`sed`**（Grep 工具会静默跳过 `.runtime/`，见记忆 `grep-tool-skips-runtime-dir`）。
> 按 `CLAUDE.md` §一.3：**源码写了什么 / 语料证明什么 / 真机跑出什么** 三层分标。凡「搜不到」均写明检索范围。

---

## 0. 一句话判决

**读到的不是「懒加载未填充的列表」。**

`EntityComponentProbe` 枚举的是**实体实例自身、在构造函数里就 `new` 出来的**那一个组件集合
（7.1 字段 `EDuXiXtiyvl` ＝ 7.0 `mUwiSNg4POZ`，类型 `WupssAXLwY5NGCQQWk<CF9E4JXdL1Cq4xrMUnCq>`）。
这个集合：

- **没有任何懒初始化** —— 包装类 `WupssAXLwY5NGCQQWk<T>` 的内部 `List<T> o26XLglnP6U` 在包装类构造函数里 `new`（`…WupssAXLwY5NGCQQMQWk_1.cs:68`）；
- **没有「访问时创建」路径** —— 实体的 getter `epLXdKqU0OD()` 只是 `DNLXOkiAvDI(ref EDuXiXtiyvl)`，而 `DNLXOkiAvDI` 的函数体就是**原样 `return P_0`**（外加一句守卫日志），**不创建任何东西**（`hnRX5SXOfpHoCM…sSJI8CXOTXcMB9gP3URF.cs:636-646`）；
- **没有 null-vs-empty 陷阱** —— 字段在实体 ctor 里即被赋值（`:933`）；若它真是 null，探针会抛 `COMPONENT_COLLECTION_NOT_MATERIALIZED`（`EntityComponentProbe.cs:137-138`）而不是回 `[]`。

所以 **`componentCount:0` 是对「该实体实例名下确实一个组件都没有」的忠实读数，不是「集合还没被填」的假象。**

**但**（第 4 节的真正判决）—— `0` **不能**读成「该实体没有组件」。编辑器**自己**渲染一个实体组件时所依据的集合，是把
**「实体自身集合」** 与 **「该实体预制体的集合」** 合起来算的。探针只读前者。
⇒ 组件要么长在**实体实例**上、要么长在它的**预制体**上；探针**只看得到前者**。

---

## 1. 它到底枚举哪个集合、怎么拿到的（逐行）

### 1.1 探针的取字段路径（`tools/editor-bridge/Adapter/EntityComponentProbe.cs`）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`model` 的成员（同文件）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`:82  var collectionField = Exact(entity, EntityComponentsField71, collectionOfComponent);`
`:77  var field = owner.GetField(name, Fields | BindingFlags.DeclaredOnly);`  ← **只取「该类型自己声明的」字段**

### 1.2 被解析的实体类型（7.1）

`CrudEntityType`（`EntityCrudProbe.cs:14`）＝ 旧名 `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr`。
`merged-symbols-7.1.json` 明写此映射：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


而 7.1 实体文件里该字段确凿存在：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


7.0 的同一处（供旧名交叉核对）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 1.3 `EDuXiXtiyvl` 就是**权威存储**，`W8QXivS0WCh` 是死字段

- **全仓（两套语料）对 `W8QXivS0WCh` / `JdaiSnpkbfl` 的引用，只有它自己那一行声明**——
  `rg -l "W8QXivS0WCh"` 与 `rg -l "JdaiSnpkbfl"` 各只命中实体文件本身；实体文件内也**只有声明、无任何赋值/读取**。
  ⇒ 它是**从不被写的死字段**，不是组件存储。
- 反过来，`EDuXiXtiyvl` / `mUwiSNg4POZ` 除了被实体自己读写，还被**加载工厂**写、
  被**行 VM** 读（§3.2），并在序列化注册表里登记（7.1 `:272` `F02gZBtnmRfGXBetc4I0…(this, EDuXiXtiyvl, …)`）。

---

## 2. 决定性问题：是不是「访问时才填」的懒列表？—— **不是**

### 2.1 包装类 `WupssAXLwY5NGCQQMQWk<T>` 是**朴素急切列表**（7.1，全文读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


⇒ 该集合**没有任何「从别处拉取 / 惰性重建 / 首次访问才填」的代码**。它只有 Add / Insert / Remove / Clear / Sort，
全部直接作用在 `o26XLglnP6U` 上。**「列表空」就是真的空**，不存在「还没填」这个中间态。

7.0 侧结构完全相同（`resolved/QAVTZKijY59YjpE1GYC0.rgfCjhijuAbCoKxWU8Lu_1.cs`）：
`:17 private List<D7gB5Rij7xaTF2353qTs> XnBijZjw7wg;`、`:68 XnBijZjw7wg = new List<…>();`、`:92 XnBijZjw7wg.Add(…);`。

### 2.2 访问器 `DNLXOkiAvDI` / `zkBiU2ieGW3` **不是** lazy-init

任务指定要查「有没有访问时创建」。它存在，但**不是创建**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


（7.0 同名等价物 `ZKvU96gS2k0<Q>` / `zkBiU2ieGW3` 见 `resolved/vNUv3diU6lqfwyK68vMI.AQecZxiUFDr4Qp1mqL4Y.cs:658`，形制相同。）
⇒ 访问器是「**带守卫的朴素取值**」，不是 get-or-create。**且**：探针走的是 `FieldInfo.GetValue` 直读字段，
**根本不经过访问器**，所以即便访问器里有懒逻辑也帮不到它。

### 2.3 null-vs-empty 的具名区分（探针设计如此）

- 字段为 null → `COMPONENT_COLLECTION_NOT_MATERIALIZED`（`:138`）；
- 字段类型不符 → `COMPONENT_COLLECTION_TYPE_MISMATCH`（`:140`）；
- 底层 `o26XLglnP6U` 为 null 或类型不符 → `COMPONENT_ITEMS_TYPE_MISMATCH`（`:142`）；
- 任一组件行字段没被物化 → `COMPONENT_FIELD_NOT_MATERIALIZED`（`:118`）。

本次真机**返回的是 `ok:true` + `componentCount:0`**，意味着上面 4 条**全都没触发**：
集合对象在、底层 List 在、且 `Count == 0`。**「空」与「未就位」在回执里是两个不同的结果，本次是前者。**

---

## 3. 交叉核对：有没有「已知非空」的实体，谁在往里写

### 3.1 往「实体组件集合」里写的**只有反序列化器**（两套语料一致）

7.0 全语料按「Add 的目标访问器」分组（`rg -rh "X66ijdVvJ0k" resolved/ | grep -o '\-> …::…' | sort | uniq -c`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


那 2 处实体侧 Add，都在**加载期反序列化/工厂**里：

| # | 位置（7.0） | 7.1 对应 | 说明 |
|---|---|---|---|
| A | `resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:587` | `decomp-7.1/Lhus…o6MMsvXduEaZkjEZB6yx.cs:552` | 实体**自身**的反序列化：从 proto 节点建 `CF9E4JXdL1Cq4xrMUnCq` 再 `Add` |
| B | `resolved/mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26353` | `decomp-7.1/RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx.cs:28126` | 静态**工厂**：遍历组件 proto，建行再 `Add` |

（B 的 7.1 目标文件映射：`merged-symbols-7.1.json` → `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q => RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx`。）

两处都是 **proto → 运行期对象** 的装配。**没有任何一处落在用户命令 / UI 交互路径上。**
这与既有结论一致：`ADD-COMPONENT-TRACE.md:§0`。—— 对**当前安装的 7.1 程序集字符串表**（2985 条）与
legacy 语料，`AddComponent/CreateComponent/AttachComponent/InsertComponent/SetComponent` **各 0 命中**，
`ForEditObj` 家族里组件命令**只有两条、都是删**（`DeleteComponentForEditObj` / `DeleteComponentForPrefab`）。

「实体能不能带组件」本身**是**有的——否则不会有实体侧的 Add 点、也不会有实体侧删命令
`DeleteComponentForEditObj(entityId, componentId)`。**问题只是：谁把它填满。**

### 3.2 编辑器**自己**读「实体组件」时，读的是**两份合起来**

唯一在两套语料里读「实体本地组件集合」的，是那个「实体组件行 VM」：

| | 7.0 | 7.1 |
|---|---|---|
| 文件 | `resolved/yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs` | `decomp-7.1/SQtAcKjcoqUQUVuC4618.fMFC0UjcP1EEI1fM7VB3.cs` |
| 订阅实体集合 | `:109`（`…::WlJiSPfnM3R`） | `:112`（marker `iKXtY0o3lBm`） |
| 枚举实体集合 | `:136` | `:196` |
| 取该实体的**预制体** | `:152`（`…::T37KPGfFqGl`） | `:332`（`…::uJDA9Hua3RF`） |
| 枚举**预制体**集合 | `:155`（`…::YlJitG20qEt`） | `:335`（marker `XDLt0BLTCIh`） |

其逻辑（7.1 `ykXjcqDtrWv()`，`:122-345`，7.0 同构）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


⇒ **编辑器给一个实体展示的组件 id 集合 ＝ 预制体集合 ∪(按实体本地组件增删)**。
**实体本地集合可以为空，而编辑器仍展示组件**（那些来自预制体）。

诚实边界：这个 VM 类的**构造函数在语料里 0 调用者**（`rg -l` 全语料只命中它自己；
`PREFAB-COMPONENT-DEFAULTS.md` 也记过 `RqDuurAmdYi`/`EFou75eU8IC` 零调用者）。所以
「它是组件面板」还是「它是可添加组件菜单」**从语料读不出来**；但无论哪种，
**「实体组件状态由实体本地集合 + 预制体集合共同决定」这条结构事实成立**。

### 3.3 有没有「读得到组件」的先例？—— **有，但都在预制体侧**

- **预制体**的组件清单**实读非空**：`PREFAB-COMPONENT-DEFAULTS.md:§0` 记 194 条预制体记录**每条都带组件清单**，
  含 `默认模版 1086324737` 带 `PopUp=40` 等。那条走的是 `ContentFieldReader`（另一条读通道），
  读的是**预制体**的集合，**不是实体的**。
- Prefab 侧集合在 7.1 是独立字段：`decomp-7.1/zDWuCYXAIGplUjEgOhcg.xvBUjOXABeOPt0cFA00U.cs:42`
  `private WupssAXLwY5NGCQQWk<CF9E4JXdL1Cq4xrMUnCq> OT7XAkHtROh;`（访问器 `:198`，ctor `:775`）——与实体的 `EDuXiXtiyvl` **是两个对象**。
- **实体侧集合**：两套语料里**找不到任何一个「读得到非空实体组件」的静态样本**。
  检索范围＝`.runtime/editor-catalog/resolved/` 全量 + `decomp-7.1/` 全量（Bash `rg`）。这是**范围结论**，不是「全集不存在」。

---

## 4. 判决（回答 (a) 还是 (b)）

**(b) 的「懒列表」版本 —— 否定；(a) 的「真的没有」—— 只在「实体本地」这一层成立。**

| 命题 | 判决 | 依据 |
|---|---|---|
| 枚举源是不是「按需填充的每实例列表」？ | **否** | 包装类 ctor `new`（`…WupssAXLwY5NGCQQMQWk_1.cs:68`）；访问器 `DNLXOkiAvDI` 只 `return P_0`（`…sSJI8CXOTXcMB9gP3URF.cs:636-646`）；无任何「访问时创建」代码 |
| 0 是不是「未初始化默认值」？ | **否** | 实体 ctor 就 `new`（实体 `:933`）；null 会被具名抛错而不是回 0（探针 `:137-142`） |
| 0 能不能证明「该实体实例自己没有组件」？ | **能** | §1.1 + §2.3 + §3.1 |
| 0 能不能证明「该实体没有组件」？ | **不能** | 编辑器把**预制体集合**也算进去（§3.2） |
| 组件是谁加的？ | **只有加载期反序列化器**（实体侧 2 个 Add 点，预制体侧 1 个） | §3.1；`ADD-COMPONENT-TRACE.md:§5` |
| 有没有「加组件」命令？ | **没有**（两个 build 都只有「删」） | §3.1；`ADD-COMPONENT-TRACE.md:§0/§3` |

### 这条读 op 到底能不能核实一次「人的编辑器步骤」

- **能核实**：挂在**实体实例自己**身上的组件（实体侧 Add 源头＝加载数据；实体侧删命令 `DeleteComponentForEditObj` 的存在证明这条通道是实体级的）。
- **不能核实**：由**预制体**承载的组件。对「元件实例」这类实体，组件默认在它的预制体上；此时
  `EntityComponentProbe(entityId).componentCount` **恒为 0，与预制体上有没有组件无关**。
- **纪律要求**：**`0` 绝不可被提升为「该实体没有组件」**。要判断「实体有没有组件」，必须
  **同时**读该实体的预制体集合（或改用 `ContentFieldReader`/`PrefabFieldsPage` 那条已存在的通道，
  见 `PREFAB-COMPONENT-DEFAULTS.md`、`tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs`）。
- 真机四例全 0，与「这四例的组件（若有）都在预制体侧 / 它们确实没有实体本地组件」**完全相容**；
  它**证伪不了**「组件在预制体上」，也**证不出**「读者坏了」。

---

## 5. 证据索引

| 论断 | 证据（file:line） |
|---|---|
| 探针枚举 `EDuXiXtiyvl.o26XLglnP6U` | `tools/editor-bridge/Adapter/EntityComponentProbe.cs:24-26,82-83,137-146` |
| null/类型不符 → 具名抛错（不返默认） | 同文件 `:118,137-142` |
| 实体类型 7.0→7.1 映射 | `.runtime/verification/update-repair-20260925/adapter-port/merged-symbols-7.1.json`（`Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr => LhusWLXd5NUZ7IineV1x.o6MMsvXduEaZkjEZB6yx`） |
| 实体组件字段 + ctor new + 访问器 | `decomp-7.1/LhusWLXd5NUZ7IineV1x.o6MMsvXduEaZkjEZB6yx.cs:43,65,197-199,933` |
| 7.0 实体同名处 | `resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:43,65,204` |
| `W8QXivS0WCh`/`JdaiSnpkbfl` 是死字段 | `rg -l` 只命中实体文件自身；文件内仅声明（实体 `:65`） |
| 包装类＝朴素急切 List | `decomp-7.1/vkNQubXLXRds8Ypg8CDv.WupssAXLwY5NGCQQMQWk_1.cs:17,49,68,77,86-88,197,313` |
| 7.0 包装类同构 | `resolved/QAVTZKijY59YjpE1GYC0.rgfCjhijuAbCoKxWU8Lu_1.cs:17,49,68,81,92` |
| `DNLXOkiAvDI` 是守卫取值、非创建 | `decomp-7.1/hnRX5SXOfpHoCM…sSJI8CXOTXcMB9gP3URF.cs:636-646`；7.0 `resolved/vNUv3diU6lqfwyK68vMI.AQecZxiUFDr4Qp1mqL4Y.cs:658` |
| 实体侧 Add 只有 2 处、皆加载期 | 7.0 `…AooSwxiSm6Ktx99ovmnr.cs:587`、`…Oe5aspiVGooyp47o5s0q.cs:26353`；7.1 `Lhus…:552`、`RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx.cs:28126` |
| 无 Add 组件命令 | `ADD-COMPONENT-TRACE.md:§0,§3,§5` |
| 实体组件 VM＝实体∪预制体 | 7.0 `resolved/yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs:109,136,152,155`；7.1 `decomp-7.1/SQtAcKjcoqUQUVuC4618.fMFC0UjcP1EEI1fM7VB3.cs:112,196,332,335` |
| 预制体组件集合是独立对象 | `decomp-7.1/zDWuCYXAIGplUjEgOhcg.xvBUjOXABeOPt0cFA00U.cs:42,198,775` |
| 预制体组件实读非空 | `PREFAB-COMPONENT-DEFAULTS.md:§0`；`tools/editor-bridge/Adapter/PrefabCollectionEvidence.cs:34,171` |

---

*本文件由 2026-10-10 会话从仓内桥源码 + 7.0/7.1 两套反编译语料**只读**整理；
未连桥、未发报文、未重启 helper、未请求 UAC、未触碰游戏/编辑器、未读图片/PDF、未写 `LocalLow`。*
*所有行号为本次 checkout / 本次语料实测；凡「搜不到」均写明检索范围（`resolved/` 全量、`decomp-7.1/` 全量、Bash `rg`）。*
