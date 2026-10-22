> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# TEXT-BUBBLE-VERDICT — 文本气泡通道判决（#5 capability）

**产出日期**：2026-10-10 · `docs/research/reverse-eng-20261010/TEXT-BUBBLE-VERDICT.md`（本轮我唯一拥有的文件）。
**口径**：**纯离线、纯只读**。未连桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未注入、未请求 UAC、
未重启 helper（正有一笔在挂）、未读写 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` 下任何文件、未读任何图片或 PDF。
所有「能/不能」均为**静态阅读**（`data/node-contracts` 离线合同 + 官方语料），`runtime_verified=false`。
本文件的每条证据都是本会话**重读源文件**得到，带 `file:line`。

---

## 0. 判决（一个字）

# **NEGATIVE**

**运行时节点不能靠「我们造的实体 + 常量」显示文本。** 「切换生效的文本气泡」（definitionId **631**）这个节点本身
**可摆放、目标实体 pin 可满足**，但它只在一个**编辑期已经配好的气泡列表**里选生效项（`文本气泡配置ID`，类型码 **1**
＝实体/配置引用），**既不写任意文本、也不建气泡**。缺的资产见 §5：**一个编辑期挂好「文本气泡组件」（`BeyondCompTypeTalk=28`）
且其中已写好气泡条目的实体**——等价地，那条被引用的 `文本气泡配置ID`。而「挂组件」在两个 build 的命令面上都不存在（本仓已定论），
官方又明文规定组件**只能在编辑时添加**。⇒ 不写 feedback 模块（任务第 4 步：若为负，写明缺失资产即止）。

---

## 1. id 订正（任务给的 267 / 313 是**目录行号**，不是 definitionId）

任务里写「267 (切换生效的文本气泡)」「313 (文本气泡完成时)」。**在 `data/node-contracts` 里 267/313 不是这两个节点**：

- `data/node-contracts/definitions/bucket-00.json`：**definitionId 267 = 激活基础运动器**。
- `data/node-contracts/definitions/bucket-03.json`：**definitionId 313 = 终止全局计时器**。

267/313 其实是 `docs/editor-catalog/NODE-CATALOG.md` 的**第一列行号**：
- `docs/editor-catalog/NODE-CATALOG.md:937` → `| 267 | 6649445819048896998 | 631 | 切换生效的文本气泡 | 入×1，出×1 | 文本气泡配置ID、目标实体 | — | 4 |`
- `docs/editor-catalog/NODE-CATALOG.md:983` → `| 313 | 5424134187819842724 | 679 | 文本气泡完成时 | 出×1 | — | 角色实体、文本气泡配置ID、文本气泡完成次数、气泡归属者实体 | 5 |`

⇒ **正确的 definitionId 是 631 / 679**（第三列，也是 `data/node-contracts` 的 `stableKey.definitionId`，也是桥收的小整数）。
下文一律用 631 / 679。这不是笔误可忽略处：用 267/313 去查合同会查到两个**完全无关**的节点。

---

## 2. 完整 pin 签名（逐字端口面，来源＝活读 `live-node-schema.json`）

### 2.1 `631 切换生效的文本气泡`（server 图，`graphKindRaw=20000`，`categoryVariant=[10001,20000,22000,0]`）

记录块起 `data/node-contracts/variants/server/bucket-02.json:7283`；名 `:7307`。

| portKey | 方向 | 种类(kind) | pin 名 | `valueTypeNameRaw` | `serverParamType` | 出处 |
|---|---|---|---|---|---|---|
| `1:0` | input | exec | 空串 | `None` | 0 | `bucket-02.json` pins[0] |
| `2:0` | output | exec | 空串 | `None` | 0 | pins[1] |
| `3:0` | **input** | data | **目标实体** | `unknown`（记 `None/0`） | **1** | 名 `:7425`，`provenanceLocator …pins[2]` |
| `3:1` | **input** | data | **文本气泡配置ID** | **`"1"`**（`valueTypeValueRaw=1`） | **20** | 名 `:7461`，`valueTypeNameRaw:"1"` `:7444`，`provenanceLocator …pins[3]` |

### 2.2 `679 文本气泡完成时`（server 图，`graphKindRaw=20000`）——纯输出事件

记录块起 `data/node-contracts/variants/server/bucket-03.json:10286`；名 `:10286`。

| portKey | 方向 | 种类 | pin 名 | `valueTypeNameRaw` | `serverParamType` | 出处 |
|---|---|---|---|---|---|---|
| `2:0` | output | exec | 空串 | `None` | 0 | pins[0] |
| `4:0` | output | data | **气泡归属者实体** | `unknown` | **1** | 名 `:10368` |
| `4:1` | output | data | **角色实体** | `unknown` | **1** | 名 `:10404` |
| `4:2` | output | data | **文本气泡配置ID** | **`"1"`** | **20** | 名 `:10440` |
| `4:3` | output | data | **文本气泡完成次数** | **`"2"`** | **3** | 名 `:10476` |

679 **没有任何入参**（只有 exec 出 + 四个 data 出），是事件源，不写文本。

### 2.3 同族（也是「往实体上挂文本」的全部官方节点）——铭牌三连

| defId | 名 | 记录块起 | 数据入 pin（方向/名/`valueTypeNameRaw`/`serverParamType`） |
|---|---|---|---|
| **615** | 添加实体生效铭牌 | `bucket-05.json:6692` | `目标实体`(in,unknown,1) · `铭牌配置ID`(in,**"1"**,20) |
| **616** | 删除实体生效铭牌 | `bucket-02.json:6753` | `目标实体`(in,unknown,1) · `铭牌配置ID`(in,**"1"**,20) |
| **617** | 设置实体生效铭牌 | `bucket-03.json:7396` | `目标实体`(in,unknown,1) · `铭牌配置ID列表`(in,unknown,**22**) |

（另可复跑 §7 命令 2 全部打印。）名 `:6931`/`:7574` 等见引用表。

### 2.4 类型码 `1` 是什么

`data/node-contracts/shared/value-type-codes.json` 的 `historicalInferredNames.rows`（该表自标
**project-inference, 7.0-era**）：code `1` 的样名逐字为 `技能配置ID / 单位状态配置ID / unitStatusConfigId /
configReference / entityReference`，`inferredType`＝**「实体/配置引用（GUID 类）」**。
⇒ 631 的 `文本气泡配置ID` 与铭牌三连的 `铭牌配置ID` **都是「引用一份编辑期资产」的 ID**，不是要显示的那句话本身。
`serverParamType` 20 与 22（列表）在这一族里**只出现在「配置ID」pin 上**，进一步把「配置引用」坐实。

---

## 3. 逐入参判决（任务第 2 步）

| 节点 | 入 pin | pin 类型（逐字） | 能用「我们造的实体 + 常量」满足吗？ | 理由 |
|---|---|---|---|---|
| 631 | `目标实体` | data，`valueTypeNameRaw` 记 `None/0`，**`serverParamType=1`**（实体引用） | **能** | 实体引用走**连线**：由事件节点输出口（如 `71 实体创建时` 的 `事件源实体`）或我们建的实体供给——与已真机 demo 图同形（实体引用全走 edge）。 |
| 631 | `文本气泡配置ID` | data，**`valueTypeNameRaw="1"`**，`serverParamType=20` | **不能** | 类型码 1＝**配置引用（GUID 类）**，指向**编辑期写好的一个气泡条目**。它不是一个自由字符串、也不是普通整数常量（那会是码 2）。要给它一个合法值，先得有一份被编辑期创建的气泡。 |
| 679 | （无入参） | — | — | 事件源，只输出。其 `文本气泡配置ID`(出, code 1) 反过来证明「气泡身份＝一份配置引用」。 |
| 615/616/617 | `目标实体` | `serverParamType=1` | 能（同 631） | 同实体引用。 |
| 615/616/617 | `铭牌配置ID` / `铭牌配置ID列表` | `"1"` / `22`（列表） | **不能** | 同为编辑期配置引用（`铭牌X`，见 §4.2）。 |

**反证（无「实体 + 字符串 → 显示」形状的节点）**：全仓 929 个变体里 `direction=input && valueTypeNameRaw=="5"`
（字符串入参）的节点共 **69 个**，逐条看名：打印字符串、变量/定时器/运动器寻址键、模板/能力单元/数据名称键、
图间信号、AI 战术上下文——**没有一条把字符串渲染到实体上**（现已由 `SIGN-TEXT-VERDICT.md` §2 与本轮独立重跑共同确认）。

---

## 4. 官方章节（任务第 3 步：「牌子实体默认带文本气泡组件吗？」）

### 4.1 答案：**否。** 官方把「文本气泡」定义成一份**要手工添加**的组件，不是任何实体的默认件

`docs/official-docs/chapters/mhwtz297kp6a.json`（title=**文本气泡**；url `…/mhwtz297kp6a/content.html`）：

- `headline`（逐字）：**「「文本气泡」是一个挂载于实体的组件，可配置多个但仅支持同时生效一个文本气泡，通过「初始生效文本气泡」勾选框、节点图「切换生效的文本气泡」或本地过滤器节点图三路决定哪一个可见。」**
- `facts[definition]`（逐字）：**「文本气泡组件，提供挂载于实体的文本气泡功能，可以引用自定义变量数据，在关卡运行时显示配置内容。文本气泡组件需要挂载于实体，支持物件、造物使用。」**
- `facts[button-path]`（逐字，即**添加组件**的 UI 三步）：**「(1)在实体/元件编辑界面中，打开组件编辑页签 (2)点击下方的添加组件，选择并点击文本气泡，成功添加 (3)点击详细编辑，展开编辑页」**
- `facts[node-name]`（逐字，631 的官方说明）：**「切换生效的文本气泡 / 通过节点输入的文本气泡序号，将替换为最新的生效文本气泡」**
- `facts[field-name]`（逐字）：**「持续时间 / 文本内容 … 显示文本编辑，支持插入变量（选择指定实体的自定义变量，会在文本框内实时更新）」**

⇒ 该章**没有一句**说任何实体（更别说牌子）**默认**带文本气泡组件；相反，它把组件描述成**用户在编辑器里
「添加组件 → 文本气泡」手工挂上去**的东西。**牌面文字是编辑期写进组件的 `文本内容`（或变量占位符），
631 只是「在气泡列表里按序号选生效项」——不接受运行时任意文本。**

### 4.2 更硬的约束：组件**只能编辑期增删**

`docs/official-docs/chapters/mhei6orvcbkm.json`（title=**通用组件**，`headline` 逐字）：
**「本章是「通用组件」子树的父页：它把「通用组件」定义为可自由在「元件」或「实体」上添加删除的「组件」，
并立下硬约束——组件仅可在编辑时添加或删除，游戏运行中无法动态添加或删除组件。」**
该章 28 个子章节里**包含「铭牌」「文本气泡」**（`facts[detail]` 逐字列举）。

⇒ 即使我们**真的**想「造一个带气泡的实体」，也只能在**编辑期**做；而「造资产 / 加组件」两个动作**本仓都没有桥原语**
（`CLAUDE.md` §六(a) 已定论；`ADD-COMPONENT-TRACE.md` §3/§10 两个 build 的命令面与字面量面均 0 命中）。

### 4.3 文本气泡是「可挂载在实体上的通用组件」——不是任何一种实体的默认件

- `docs/official-docs/chapters/mhufqo0c0tqw.json`（造物）：**「造物实体支持添加多种组件功能，包括」** 16 项，
  其中一项是 **「文本气泡」**（同列表还有「铭牌」）。「支持添加」＝**可加**，不是**默认带**。
- `docs/official-docs/chapters/mh3ecor1x5cm.json`（角色）：「角色实体的可用组件概览」14 项，其中一项是 **「文本气泡」**。
- 官方**没有**「告示牌 / 提示牌 / 标牌 / 指示牌 / 木牌」章节：
  `grep -rc "告示牌\|提示牌\|标牌\|指示牌\|木牌" docs/official-docs/chapters/` → **全部 0 命中**（`SIGN-TEXT-VERDICT.md` §3 已记，本轮复核同）。
  「牌子＝能显示文本」是**工程侧推断，不是官方陈述**。

### 4.4 铭牌同构（也是「编辑期配好、运行时按配置ID引用」）

`docs/official-docs/chapters/mh5n160t2b6w.json`（title=**铭牌**）：
- `headline`（逐字）：**「…其运行时唯一管理接口是节点「设置实体生效铭牌」，其输入 铭牌配置ID列表 会完整覆盖目标实体的生效铭牌。」**
- `facts[definition]`（逐字）：**「铭牌X，X为铭牌配置ID，作为节点输入项可以调整铭牌的初始生效参数。」**
- `facts[button-path]`（逐字）：**「(1)在实体/元件编辑界面中，打开组件编辑页签 (2)点击下方的"添加组件"，选择并点击"铭牌"，成功添加 (3)点击"详细编辑"…」**
- `facts[definition]`（占位符，逐字）：**「插入引用的自定义变量以富文本的形式填写，格式为 {类型:前缀.变量名}」**

⇒ 铭牌与文本气泡同一形状：**组件要手工加，文本/占位符要编辑期写，节点只引用配置ID**。
（注意：铭牌章说运行时**唯一**管理节点是「设置实体生效铭牌」＝617；合同里另有 615/616「添加/删除实体生效铭牌」，
官方章未列——这属合同与文档的**名目分歧**，不影响本判决：三者都要 `铭牌配置ID`。）

---

## 5. 新线索（组件面板 wiring 在反编译集之外）——追问过，**不翻案**

本轮被点名的新线索：组件列表 VM 的静态工厂 `RqDuurAmdYi` / `EFou75eU8IC` **全语料 0 调用者**。
**我复跑并确认**：`grep -rn "RqDuurAmdYi\|EFou75eU8IC" .runtime/editor-catalog/resolved/` → **各恰好 1 命中，
且都在定义处**：
- `.runtime/editor-catalog/resolved/LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs:33`
- `.runtime/editor-catalog/resolved/yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs`（同形）
⇒ 这两个组件列表 VM **从未在 12,375 个反编译文件里被实例化**，即**组件面板的宿主 wiring 不在反编译集里**（静态盲区）。
**但这对文本气泡通道的判决无影响**，因为：
1. 即便面板存在于那段盲区，`通用组件` 章仍把「加组件」钉在**编辑期**（§4.2），而「造资产 / 加组件」**桥无原语**；
2. 该行 VM（`…yn34VuuuO5tEgsICYDBW`）只有 `vmBtnShow`（**空实现** `{}`，`:89-91`）与 `vmBtnDelete`，**没有任何 add**
   （`ADD-COMPONENT-TRACE.md` §2/§10.1）；列表 VM 也只**逐组件建行**（`UY3FwAuuVnr6w8n0v5kN.cs:83` `YlJitG20qEt()` 遍历，
   `Qy9uuJK9OCr` `:96-195` 建行），**同样无 add**；
3. **缺的那份东西是「编辑期已配好的气泡」本身**，不是「面板按钮」——盲区里就算有按钮，也变不出一个气泡配置ID。

---

## 6. 判决与缺失资产（任务第 4 步）

**NEGATIVE**。要让玩家在关卡里看到文本，**最少**缺下面之一，而两者**桥都没有原语**能造：

| 缺什么 | 精确形状 | 证据 |
|---|---|---|
| **① 一份已挂文本气泡组件、且其中已写好气泡条目的实体** | 实体的编辑期组件集里含 `BeyondCompTypeTalk=28`，其 `*文本气泡列表` 内有 ≥1 条（每条的「文本内容」编辑期写死或含变量占位符），631 才能按 `文本气泡配置ID` 切到它 | 组件枚举 `QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:35`（`BeyondCompTypeTalk = 28`）；`mhwtz297kp6a.json` button-path / field-name；「加组件」两 build 全 0（`ADD-COMPONENT-TRACE.md` §3） |
| **② 等价地：一个被引用的 `文本气泡配置ID`** | 一份编辑期资产引用（类型码 1）。没有它，631 的 `文本气泡配置ID` 无处可填 | `data/node-contracts/variants/server/bucket-02.json:7444`（`valueTypeNameRaw:"1"`）、`:7461`（pin 名）；`shared/value-type-codes.json` code 1＝实体/配置引用 |

**为什么不写 feedback 模块**：`tools/gameplan/modules/feedback.py` 若要「用可摆放节点 + 常量把某实体气泡切到 `<text>`」，
必须给 631 的 `文本气泡配置ID` 一个合法常量——而这个常量在本仓**不存在**（无已授权气/无配置ID清单）。
写出来的模块只能是**空转的**：图上有一个永远填不上的 pin。按任务第 4 步，**负 → 写明缺失资产即止**，不造该文件。
（真机侧另需 `runtime_verified` 目视，本轮为 0。）

**唯一「接近正」的窄读法（诚实标注，不改判决）**：631 节点**可摆放**、`目标实体` pin **可满足**；
若**用户先在编辑器 UI 手工**把气泡挂到某实体、写好几条文本，则本仓可以只靠**连线 + 该配置ID 常量**去切生效项。
但这**不是**「用我们造的实体」——它依赖一份我们造不出的编辑期资产，故整体仍判 **NEGATIVE**。

---

## 7. 复现命令（全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 8. 引用表

| 论断 | 证据（file:line） |
|---|---|
| 267/313 是 NODE-CATALOG 行号；631/679 才是 definitionId | `docs/editor-catalog/NODE-CATALOG.md:937`、`:983`；`data/node-contracts/definitions/bucket-00.json`(267) / `bucket-03.json`(313) |
| 631 定义块/名 | `data/node-contracts/variants/server/bucket-02.json:7283`、`:7307` |
| 631 `目标实体`(spType 1) / `文本气泡配置ID`(`"1"`,spType 20) | `bucket-02.json:7427`、`:7444`、`:7461` |
| 679 定义块/名 + 四个输出 pin | `data/node-contracts/variants/server/bucket-03.json:10286`、`:10368`、`:10404`、`:10440`、`:10476` |
| 615/616/617 定义块 + 铭牌 pin 名 | `bucket-05.json:6692`/`:6870`(铭牌配置ID)；`bucket-02.json:6753`/`:6931`；`bucket-03.json:7396`/`:7574`(铭牌配置ID列表) |
| 类型码 1 ＝ 实体/配置引用（GUID） | `data/node-contracts/shared/value-type-codes.json`（`historicalInferredNames.rows` code 1） |
| 文本气泡章：手工加组件·只生效一个·631 按**序号**切换·文本内容编辑期写 | `docs/official-docs/chapters/mhwtz297kp6a.json`（headline / definition / button-path / node-name / field-name） |
| 组件**只能编辑期增删**（硬约束） | `docs/official-docs/chapters/mhei6orvcbkm.json`（headline；子章节含「文本气泡」「铭牌」） |
| 文本气泡是造物/角色的**可添加**通用组件（非默认件） | `docs/official-docs/chapters/mhufqo0c0tqw.json`、`mh3ecor1x5cm.json`（type-taxonomy 组件清单） |
| 铭牌：编辑期加组件·`铭牌X`＝配置ID·运行时唯一节点「设置实体生效铭牌」覆盖式 | `docs/official-docs/chapters/mh5n160t2b6w.json`（headline / definition / button-path / node-name） |
| 组件枚举 `BeyondCompTypeNameplate=27` / `BeyondCompTypeTalk=28` | `.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:34-35` |
| 组件面板两工厂 0 调用者（盲区） | `.runtime/editor-catalog/resolved/LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs:33`；`…yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs` |
| 组件行 VM 无 add（Show 空实现 + Delete） | `.runtime/editor-catalog/resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:89`；`ADD-COMPONENT-TRACE.md` §2/§10.1 |
| 「加组件」两 build 命令面/字面量面 0 命中 | `docs/research/reverse-eng-20261010/ADD-COMPONENT-TRACE.md` §3/§10.3 |
| 无「实体+字符串→显示」的节点 | `SIGN-TEXT-VERDICT.md` §2（69 条字符串入参节点）；本轮 §3 复核 |

*本文件为「文本气泡通道」判决，由 2026-10-10 会话离线复核整理；全程未连桥、未发任何请求、未触碰游戏/编辑器/存档/helper、
未请求 UAC、未读写 LocalLow、未读图片或 PDF。行号为本次 checkout 实测；凡「未找到/无证据」均已标注检索范围。*
*判决为 **NEGATIVE**：不产出 `tools/gameplan/modules/feedback.py` / `tests/test_feedback.py`（任务第 4 步：负则写明缺失资产即止）。*
