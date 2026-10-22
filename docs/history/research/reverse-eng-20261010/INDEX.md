> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# INDEX — `docs/research/reverse-eng-20261010/` 报告总索引

> 建立/重编于 2026-10-10（本轮重编，取代旧的 44 行版）。**本文件只读整理**：未连桥、未发报文、
> 未触碰游戏/编辑器、未写任何存档。**每一行的内容都取自被索引报告本身**（一句话结论 / 判决段 / 标题），
> 本文件**不新增任何事实主张**。行号凡引用均来自被索引报告的本次 checkout 实测。
>
> **三层口径**（`CLAUDE.md:25`）：`文档写了什么` / `工具能做什么` / `真机验证过什么`——各报告已分层标注，
> 本索引只做搬运。**「搜不到」≠「不存在」**（`CLAUDE.md:23`）。
>
> **目录规模**：本目录 **73 份报告 + 本文件**（`ls` 实测）。另有 **11 份已被顶替**，移入
> `archive/`（见 §五，移动不删除）。
> ⚠️ **本目录是活环境**：同一夜有多个会话在写。本索引是**某一时刻的快照**，**新落地的报告可能尚未收录**——
> 若 `ls` 出未见于此 `FULL LIST` 的文件，请按 §二/§四 的格式补一行（并检查是否与既有报告同题而构成顶替）。
>
> **先读**：`CLAUDE.md`（尤其 **§五 能力边界** 与 **§六 边界是不对称的**）→ `docs/STATE-CARD.md`
> （一页接续卡）→ 本索引。

---

## 〇、一页速查：**「X 可能吗？」在一处找到答案**

> 主表在 **`PRIMITIVE-VERDICTS.md`**（23 条原语逐条 有/无/未知 + 证据 + 下一步）。下表是它的入口：

| 问「……能不能？」 | 判决 | 依据报告 |
|---|---|---|
| 建实体（按坐标，单/批量） | **能**（真机） | `PRIMITIVE-VERDICTS.md` #1 |
| 删实体（编辑态物化） | **能**；运行期生成物 **不能** | `PRIMITIVE-VERDICTS.md` #2、`ENTITY-LIFECYCLE-MINE.md` |
| 改已有实体位姿（`entity.transform`） | **不能**（无 transform 命令，CONFIRMED） | `COMMAND-ROUTE-MAP.md`、`TRANSFORM-VIA-RECREATE.md` |
| **读**实体组件 | **能**（已编译进 R269，**未真机**） | `COMPONENT-READ-VALUE.md`、`COMPONENT-OP-PROOF-PLAN.md` |
| **加**实体组件 | **不能**（`Add*Component*` 四处 0 命中；⚠️ 口径 2026-10-11：四处**非独立层**，独立轴＝两代构建 7.0/7.1——见 `CLAUDE.md` §五） | `COMPONENT-WRITER-MINE.md`、`COLLISION-TRIGGER-MINE.md` |
| **删**实体组件 | **不能**（当前 op 未绑定读半，fail-closed） | `COMPONENT-OP-PROOF-PLAN.md` |
| 建图 / 加节点 / 连线 / 挂图 | **能**（真机；「挂上≠会跑」） | `PRIMITIVE-VERDICTS.md` #9–12、`GRAPH-ATTACH-CHAIN.md` |
| 删图 | **不能**（谓词引用相等恒 false） | `GRAPH-DELETE-FIX.md` |
| 建模板（货币/道具/背包/商店/技能） | **不能**（38 路由无一条建模板） | `TEMPLATE-CREATION-MINE.md`、`SKILL-ASSET-VERDICT.md` |
| 写字典常量（type 27） | **不能**（常量）；图内构造+连线 **能** | `DICT-WRITE-PROBE.md`、`DICT-WIRE-FORMAT.md` |
| 图变量节点（`323/337/351`）放不放得进图 | **能**（是普通节点，`add-node` 可放置，**未建**非做不到） | `GRAPH-VARIABLES-FINAL.md` |
| 写图级变量定义表（`graph_variables`） | **不能**（图级属性，我方无写入口；缺绑定） | `GRAPH-VARIABLES-FINAL.md` |
| 写 UI 控件 / HUD | **不能**（无 UI 资产 Kind/op） | `UI-CONTROL-WRITE-MINE.md` |
| 让玩家「看见」（零新资产） | **能**——仅几何层 3 条（`308`/`266`/`835`）；文字/UI **不能** | `PLAYER-VISIBLE-VERDICT.md` |
| 建/开关卡 | **不能**（命令面不可达 + 版本门 fail-closed） | `LEVEL-CREATE-MINE.md` |
| 读地形 | **能**（真机只读）；持久化写回 **不能** | `TERRAIN-WRITE-RISK.md`、`TERRAIN-WRITEBACK-EXPERIMENT.md` |
| 起停试玩 | **不能**（bridge 面零入口，UI-only；官方亦无程序落点） | `PLAYTEST-CONTROL-MINE.md`、`OFFICIAL-PLAYTEST.md` |
| 原生保存（落盘） | **能**（真机，`.gil` 字节差分确认） | `PRIMITIVE-VERDICTS.md` #15 |

---

## 一、START HERE —— 回答「这工程能做什么、卡在哪」的 5 份（按此顺序读）

1. **`PRIMITIVE-VERDICTS.md`** —— **一页判决表**：23 条原语逐条 `有/无/未知` + 证据 file:line + 下一步动作。
   这是「能不能」问题的第一落点；§0 是速查，§1 是主表，§2 是 UNKNOWN 表。
2. **`MINED-INTERFACES.md`** —— 把 `CLAUDE.md` §一 升级成**活的、可逐行核对的接口索引**（怎么挖到 / 实现在哪 /
   真机证据 / 状态），**§11 是负结论表**。这是「能做什么」的正面清单。
3. **`COMPONENT-WRITER-MINE.md`** —— **本夜的核心不对称**：组件是**一等公民、封闭 46 类**，**读得出、删得掉、
   加不了**（`Add*Component*` 在四处检索 0 命中）。M1/M4/M5 场景半边全卡在这条原语上。
4. **`OFFICIAL-CHAPTERS-LEADS.md`** —— 官方 218 章收缩成 **5 个缺失原语**（P1 组件写 / P2 模板建 / P3 UI 资产写 /
   P4 关卡操作 / P5 地形写回）。这是「下一步该挖什么」的路线图。
5. **`PLAYER-VISIBLE-VERDICT.md`** —— **玩家可见**问题的终审：零新资产只有 3 条几何通道（`308`/`266`/`835`），
   **文字/UI 一条都没有**；冠军 `308 激活/关闭模型显示`。

> 前置（本目录之外）：`CLAUDE.md` §一/§五/§六；`docs/STATE-CARD.md`（真机验证过 / 已确证做不到 / 会变的活环境 / 接续命令）；
> `docs/gameplan/`（执行面 runbook、DEMO-GAP、USABLE-NOW）。

---

## 二、按模块分组（M1..M6 + 两组横切）

模块编号取自 `docs/MODULE-PLAN-6.md`：**M1 交互点 / M2 货币 / M3 道具 / M4 背包 / M5 商店 /
M6 地形与地块（a 关卡地形、b 摆放设计）**。**判决列＝该报告自己给出的结论**（能 / 不能 / 未知；多值即报告内部本分档）。
**负**＝含**已证的不可能 / 已证的缺席**（`CLAUDE.md:26`）。**记**＝`挖` 掘一条原语 / `审` 审计既有主张 / `勘` 勘察清点。

### M1 交互点

| 文件 | 一句话 | 判决 | 负 | 记 |
|---|---|---|---|---|
| `COLLISION-TRIGGER-MINE.md` | 碰撞触发器是挂在**实体**上的通用组件；图半边（节点 92/91/90）已齐，缺的唯一原语是「加组件」 | **不能**（无 `Add*Component*`） | ✓ | 挖 |
| `COLLISION-COMPONENT-ID.md` | 组件类型枚举**实测 46 个成员**（值域 0–47 缺 2、10）；探针行 `id`＝枚举值（强证据、未真机） | **未知**（编号空间未真机坐实） | | 挖 |
| `COMPONENT-WRITER-MINE.md` | 组件能读能删；**「加」的命令在两个已恢复命令集里都不存在** | **不能** | ✓ | 挖 |
| `CHANNEL-2001.md` | 通道 2001（组件字段消息）：**定义在、发送器被 `if(false)` 掐死、无接收器**；翻常量只会多发一个无人接收的帧，**不构成加组件的写入路径** | **不能**（不是可用的组件写入路径） | ✓ | 勘 |
| `COMPONENT-READ-VALUE.md` | `inspect-entity-components` 解锁的是**「能核实」**（人配、机核），不是「能配组件」 | **能**（读，一次真机即闭环）；**不能**（加） | | 挖 |
| `COMPONENT-OP-PROOF-PLAN.md` | 组件 op 真机取证计划：**读已编译（未真机）；删已接线但读半未绑定⇒fail-closed** | **未知**（读）/ **不能**（删，现无可用 op） | ✓ | 勘 |
| `COMPONENT-SWEEP-PLAN.md` | 一次一实体的只读扫荡计划（把「人配的组件」与「机器造的」分开） | **未知**（PLAN，一条都没跑） | | 勘 |
| `GRAPH-ATTACH-CHAIN.md` | 图**挂上了**实体 1077936129，但**没有任何东西会去跑它**——事件节点只在「配了碰撞触发器组件的实体」上触发 | **不能**（缺一个加不上的组件） | ✓ | 审 |
| `PREFAB-COMPONENT-PATH.md` | 预制体与实体在**组件这件事上完全对称**：同集合、同 `Add`、命令面**两边都只有删** | **不能**（预制体侧也无加组件） | ✓ | 挖 |
| `OFFICIAL-COMPONENT-CATALOG.md` | 官方「组件」家族整族枚举（父章 1+子章 28+特化 1）；含三个 demo 组件的**字段级 spec** | **不能**（文档给了按钮，工具无写入原语） | | 勘 |
| `ENTITY-LIFECYCLE-MINE.md` | 销毁事件 72/373 范围是**任意实体**，无创建者门；**运行期知道而工具碰不到的实体真实存在** | **能**（图侧观察/删）；**不能**（工具删不到运行时生成物） | ✓ | 挖 |
| `UI-CONTROL-WRITE-MINE.md` | 编辑器侧**没有**任何 UI/面板/控件写入口；旁路是 `presentation` 家族（266 等，零 UI 资产） | **不能**（UI 写）；**能**（presentation 旁路，CANDIDATE 未真机） | ✓ | 挖 |

### M2 货币 / M3 道具 / M4 背包 / M5 商店（模板与状态族）

| 文件 | 一句话 | 判决 | 负 | 记 |
|---|---|---|---|---|
| `CONFIG-ID-RESOLUTION-MINE.md` | 今天**没有任何离线产物**能回答「配置ID X 是否存在」 | **不能** | ✓ | 挖 |
| `TEMPLATE-CREATION-MINE.md` | `command_route` 38 行**无一条建模板**；模板不在 `.gip`；落点候选＝`.gil root field 15` | **不能**（现成命令面没有） | ✓ | 挖 |
| `SKILL-ASSET-MINE.md` | 技能是「编辑器资产模板」的同一类东西（配置ID 类型 6/28/37，与货币 10 同表） | **不能**（技能创建卡同一条缺失原语「无写入面建带配置ID 的编辑资产模板」） | ✓ | 挖 |
| `SKILL-ASSET-VERDICT.md` | 判决：技能与货币/道具模板**同一 KIND**（CONFIRMED）；建模板这一条原语一并解锁两处 | **能**（分类 CONFIRMED 同类）/ **不能**（建模板原语仍缺）；**不解**加组件 | | 审 |
| `DICT-CONSTRUCT-SEARCH.md` | 两个 id 命名空间**完全对称**：`建立字典`(1088)/`拼装字典`(1788) 两边都有，差集为空 | **能**（构造器存在；refutes `CLAUDE.md:74` 的过度概括） | | 挖 |
| `DICT-WRITE-PROBE.md` | 字典**常量**(type 27) 不能写；但可**在图里构造**再连线喂 27 的 pin | **能**（图内构造）/ **不能**（常量） | | 挖 |
| `DICT-WIRE-FORMAT.md` | 一个 dict 常量今天**不是「写起来慢」，是「根本没有形状可写」**；缺的是 setter | **不能**（not writable-by-shape） | ✓ | 挖 |
| `NODE-PLACEABILITY.md` | 500/500 条服务端定义**按构造都可放置**（0 条声明零 pin）；六模块域≈67 条 | **能**（过静态闸）/ 可放置≠可连≠可配≠可运行 | | 勘 |
| `PREFAB-FIELDS-MINE.md` | `prefab-fields-page` 深读给出**组件类型集合**（与 46 项枚举互证），但参数全 0、几何全无 | **能**（组件类型号坐实）；**不能**（参数/几何） | ✓ | 勘 |
| `OFFICIAL-CHAPTERS-LEADS.md` | 官方 218 章收缩成 **5 个缺失原语**（P1 组件写 / P2 模板建 / P3 UI 资产写 / P4 关卡操作 / P5 地形写回） | **不能**（5 个原语一条都没有） | ✓ | 勘 |

### M6 地形与地块（a 关卡地形、b 摆放设计）

| 文件 | 一句话 | 判决 | 负 | 记 |
|---|---|---|---|---|
| `GIL-FIELD-LEDGER.md` | `.gil` 顶层**已观测 47 个字段号**（10 实证 / ~14 推断 / ~23 无人命名）；最大洞是 field 15 | **未知**（未知是成果；多条读法冲突未决） | ✓ | 勘 |
| `LEVEL-CREATE-MINE.md` | 建关卡：**命令面不可达、文件面字节已读懂、策略面被版本门挡住**（守的是真漂移） | **不能**（命令面）；原理上可达 | ✓ | 挖 |
| `TERRAIN-WRITE-RISK.md` | 写入方是**游戏进程**、save 时**从内存重生成整文件**；文件级地形写回会被下一次 save 覆盖（持有态） | **不能**（作为独立路线）；**未知**（关闭态跨会话） | ✓ | 审 |
| `TERRAIN-WRITEBACK-EXPERIMENT.md` | 地形写回安全实验设计（**未执行**）：单格改动＝**恰好 1 字节**；建议推迟 | **未知**（设计文档） | ✓ | 勘 |
| `SAVE-WRITER-FINAL.md` | **定案**：写这份 `.gil` 的是**游戏/编辑器写入方**，不是本工程 Python；页签目录段多出的无 `field 1` 条目**来自写入方内存**（早在 2026-09-19 就存在，早于本工程的 save 能力），会复发 | **能**（写入方＝游戏进程；§2 归属证据） | | 审 |
| `TRANSFORM-VIA-RECREATE.md` | 「删了重建」技术可行但**不是移动**（换 id、断绑定、两次 native 写周期） | **不能**（作为工作流） | ✓ | 审 |
| `GEOMETRY-THREE-WAYS.md` | 三条读几何的路：B 读＝null；C（编辑器缓存）实测与 A **矛盾**（全零 vs z≈2.911） | **不能**（C 不可用作权威坐标） | ✓ | 审 |
| `ASSET-MEASURE-MINE.md` | 离线**不存在**任何「给模板 id、返回尺寸」的现成来源；`asset.measure` 返回 `None` 是对的 | **不能**（9 候选来源关死；唯一开放＝1017 形状组件） | ✓ | 挖 |
| `ENTITY-CREATE-FIELDS.md` | `create` 只送 4 类东西（模板/模式/三向量），**不送组件**；但建出的实体落盘**自带 31 项组件表**（随模板走） | **能**（组件集随 template_id 实例化，证据充分） | | 挖 |
| `PREFAB-INSTANTIATE-MINE.md` | 预制体实例化**不是**第二条摆放路（只吃 prefab id、无坐标、真机证伪）；`place_builtin` 已是 create 的别称 | **不能**（不绕过缺失的加组件原语） | ✓ | 挖 |
| `WAVE-SPAWN-PATH.md` | 分波生成＝布设组+178，对 M6b **给不了任何** plain `entity.create` 给不了的东西；刷怪**不必**走布设组 | **能**（元件型创建 252/757/256 存在）；**不能**（布设组无写入原语） | | 挖 |

### M6b 摆放（与 create/布局同族）

| 文件 | 一句话 | 判决 | 负 | 记 |
|---|---|---|---|---|
| `ENTITY-READABLE-FIELDS.md` | 实体模型可读字段面 ~24 个槽，项目只读 8 个（11 语义）；**UNREAD 字段的 7.1 符号名全已知**，缺的是读 op | **未知**（其余 ~12 字段 UNREAD；符号已知） | | 勘 |
| `ENTITY-PROPERTIES-MINE.md` | 实体字段**读得深**（身份/变换/标签/阵营/图绑定+原始字段树），**写只打穿三个标量族** | **不能**（组件读写无按语义命名的通路） | ✓ | 勘 |

### 横切 A —— 节点图 / 运行时验证 / 桥与原生基建

| 文件 | 一句话 | 判决 | 负 | 记 |
|---|---|---|---|---|
| `COMMAND-ROUTE-MAP.md` | 38 条前端命令全表 + 本工程 10 个调用点；**transform 问题 CONFIRMED**（无一条命令能给已存在对象设位姿） | **不能**（无 transform 命令） | ✓ | 审 |
| `GRAPH-SIZE-LIMITS.md` | 作者面能表达的图上界**128 节点**（三门票汇合）；边/常量无独立上限，真正天花板是请求行字节 | **能**（≤128）/ **不能**（>128 无任何作者原语） | ✓ | 挖 |
| `BUILD-PLAN-CEILING.md` | 核实并延伸 `build-plan` 尺寸天花板；**真机每派发 ≈12.9 s**；稠密图 ≈96 节点撞 16000 B；**第二次 build-plan 不能** | **能**（≤128 节点/≤16000 B）/ **不能**（扩同图） | ✓ | 挖 |
| `BUILD-INTERRUPT-HAZARD.md` | build 中途死掉：编辑器留下 6–7 节点、0 边、不可逆；三层标记寿命不同；重跑＝重放不重执行 | **能**（跨租约防重放）/ **不能**（无回滚、失败到第几步不可检） | ✓ | 审 |
| `REVISION-ECONOMY.md` | 260 个修订号（R2..R269，8 缺口）；约束是「注入机会」不是号；**同号在租约收尾后可再注入** | **能**（同号可再注入）/ **不能**（新能力必须升修订） | ✓ | 勘 |
| `BINDING-SYMBOL-AUDIT.md` | 307 legacy 符号里 299 已用；**没有「getter 在用、setter 没用」的零成本配对**；缺 3 个读回 getter | **不能**（无现成零成本写回） | ✓ | 审 |
| `SETTER-SIGNATURE-SURVEY.md` | 9 个 setter 全部被引用；最便宜的新写入＝**补 3 个缺席的读回 getter**（闭环 float/bool/string） | **不能**（无未使用 setter）/ **能**（补 getter 即闭环） | ✓ | 审 |
| `UNBOUND-SYMBOL-AUDIT.md` | 「解析了未绑定符号」bug 收敛到 **2 文件 / 5 符号**（3 个是 AuthoringGraph 读回 getter，2 个是组件删）；**全是补绑定、不是重挖** | **能**（已收敛；5 符号 7.1 里都在） | | 审 |
| `NATIVE-MEMORY-MAP.md` | 原生探针地址/偏移集中成一张可检索地图；**读得最窄的是「东西摆在哪、由什么组成」** | **能**（谁在场景里）/ **不能**（位置偏移与 component 列表为空） | ✓ | 勘 |
| `NATIVE-ACTION-SET-MINE.md` | 6 个原生动作＝5 个 `HR_ACTION`(0..4)＋1 只读选择器；集合是 **MISSING DISCOVERY 不是 HARD BOUNDARY** | **能**（注册机械）/ **不能**（每个新动作须先逆向一个新原生调用） | ✓ | 审 |
| `NATIVE-ACTION-COST.md` | 加第 7 个原生动作：注册面机械（约 11 处加一行），能力面卡在发现；最便宜＝纯读动作（走 `HR_READ_*`，不占新号） | **能**（加第 7 个机械）/ **不能**（须先逆向新原生调用） | ✓ | 挖 |
| `NATIVE-HALF-CAPABILITIES.md` | `version_guard` 是**四道互不相通的门**；今天红的是最窄的 `game` 半，图/场景两半**都绿** | **能**（第 1–11 行全绿）/ **不能**（第 12–16 行 5 个 legacy 写盘工具被挡） | | 勘 |
| `EDITOR-REGISTRY-MINE.md` | 资源 Kind 至少 25 个；工程只认 6/9；**没有 UI 资源 Kind**；组件不是注册表资源 | **不能**（无 UI Kind） | ✓ | 勘 |
| `GIA-TRUTH.md` | `.gia` 框架**＝`.gil` 容器**（subtype 3）；节点表可走行，且**边也可走行**（16/16+15/15 对 ground-truth plan） | **能**（节点+边都可解，字节级） | | 审 |
| `GRAPH-RUNTIME-EVIDENCE.md` | 把「边被接受」拆四层：E1 编辑器模型（有）／E2 落盘（可解未对 demo）／E3 游戏加载器（闸死）／E4 执行遍历（弱通道） | **未知**（E1 成立；E2/E3/E4 未证） | ✓ | 审 |
| `GRAPH-RUNTIME-VERIFY-MINE.md` **(已归档)** | 5 个日志 op 形状对，但**按原样跑翻不动 `runtimeVerified`**（41 次无一次） | **不能**（按原样）；**未知**（补判据后「有资格」） | ✓ | 审 |
| `GRAPH-LOG-NEXT-STEP.md` | **更正 #3 的卡点定位**：记录**自带** proto 58 `graphId`（桥没读）；下一步＝加宽 `CaptureRunLogRecord` 读它 | **未知**（改一处读取即可定案） | ✓ | 审 |
| `GRAPH-LOG-SHAPE.md` | 记录里**没有任何被读出的节点 id**；名字槽在真机是运行实例 id | **未知**（节点 id 字段未证）；**不能**（不能靠名字认图） | ✓ | 勘 |
| `GRAPH-LOG-REACHABILITY.md` | 日志族 5 个 op **全部到得了队列**（0 个需要额外字段）；真机回执份数已列 | **能**（5/5 到队列）/ 到队列≠证据够用 | | 审 |
| `GRAPH-DELETE-FIX.md` | `delete-owned-graph-ids` 恒 `modelMatched=0` 的根因＝**引用相等谓词 + 两个对象图**；统一查找是正确修法但**不充分**（仍无删除原语） | **不能**（删除仍做不到） | ✓ | 审 |
| `PLAYTEST-CONTROL-MINE.md` | `playtest.control` 无已证入口，且不是「少一个 op」；唯一候选＝`open-editor-panel` 菜单 Delegate 通路 | **不能**（bridge 面零入口）/ **未知**（候选 P1 未执行） | ✓ | 挖 |
| `OFFICIAL-PLAYTEST.md` | 官方「试玩」章逐字还原（代码侧的互补件）：程序**不能**触发进入、**by design 读不到**校验结果、**不能**退回编辑态；察觉状态改变 **未知** | **不能**（进入/读校验/退回）/ **未知**（察觉状态） | ✓ | 勘 |
| `EDITOR-STATE-MACHINE.md` | 编辑器「编辑态 vs 运行态」状态机存在（UI 文案自证），但本仓只有**被动观察**、无**可驱动 setter**；试玩靠调用菜单 Action（UI 触发） | **不能**（不可驱动）/ **能**（有限观察） | ✓ | 挖 |
| `REOPEN-VERIFICATION-MINE.md` | reopen 是唯一把存档送回游戏加载器的通道，但被常量关卡 id `1073741840` 钉死、去常量只做一半、**门禁已红** | **未知**（机制活、现状死）/ **不能**（不要现在发射） | ✓ | 审 |

### 横切 B —— 地基 F1/F2（变量与节点）与「玩家可见 / 文档线索」

| 文件 | 一句话 | 判决 | 负 | 记 |
|---|---|---|---|---|
| `GRAPH-VARIABLES-FINAL.md` | **F1 终判**：`323/337/351` 是**普通节点**（`add-node` 可放置，**未建**非做不到）；但「可用的图变量」＝访问器节点＋**一条图级表记录**，图级变量表 `graph_variables` **我方无写入口** | **能**（节点层可放置）/ **不能**（定义层阻塞） | ✓ | 审 |
| `PLAYER-VISIBLE-VERDICT.md` | 零新资产**只有 3 条几何通道**（`308`/`266`/`835`，弱候选 `846–848`）；**文字/UI 一个都没有**；冠军 `308` | **能**（几何层 3 条 CANDIDATE）/ **不能**（文字/UI） | ✓ | 审 |
| `UI-HUD-FINAL.md` **(已归档)** | `ui.hud` 收口：编辑器侧没有任何 op 能把值写进 UI 元素；注册表侧不存在 UI 资产 Kind | **不能**（UI 写） | ✓ | 审 |
| `VISIBLE-NO-ASSET.md` **(已归档)** | 21+2 命中里「零资产且自身产生可见效果」的只有 `308`；所有文字通道都要资产 | **能**（308/266/835 零资产）/ **不能**（文字通道） | ✓ | 挖 |

---

## 三、按主题分组（`挖` / `审` / `勘`，主主题各置一处）

- **挖一条原语（24）**：`COLLISION-TRIGGER-MINE` · `COLLISION-COMPONENT-ID` · `COMPONENT-WRITER-MINE` ·
  `COMPONENT-READ-VALUE` · `CONFIG-ID-RESOLUTION-MINE` · `TEMPLATE-CREATION-MINE` · `SKILL-ASSET-MINE` ·
  `DICT-CONSTRUCT-SEARCH` · `DICT-WRITE-PROBE` · `DICT-WIRE-FORMAT` · `ASSET-MEASURE-MINE` · `WAVE-SPAWN-PATH` ·
  `LEVEL-CREATE-MINE` · `ENTITY-CREATE-FIELDS` · `PREFAB-INSTANTIATE-MINE` · `PREFAB-COMPONENT-PATH` ·
  `PLAYTEST-CONTROL-MINE` · `GRAPH-VARIABLES-PROBE`(归档) · `ENTITY-LIFECYCLE-MINE` · `TAB-DIRECTORY-MINE`(归档) ·
  `UI-CONTROL-WRITE-MINE` · `VISIBLE-NO-ASSET`(归档) · `NATIVE-ACTION-COST` · `BUILD-PLAN-LIMITS`(归档)
- **审计既有主张（24）**：`GRAPH-ATTACH-CHAIN` · `BUILD-INTERRUPT-HAZARD` · `BRIDGE-CRASH-SAFETY`(归档) ·
  `BINDING-SYMBOL-AUDIT` · `SETTER-SIGNATURE-SURVEY` · `UNBOUND-SYMBOL-AUDIT` · `NATIVE-ACTION-SET-MINE` ·
  `REOPEN-VERIFICATION-MINE` · `GRAPH-DELETE-FIX` · `GRAPH-DELETE-PROBE`(归档) · `GRAPH-RUNTIME-VERIFY-MINE`(归档) ·
  `GRAPH-LOG-NEXT-STEP` · `GRAPH-LOG-REACHABILITY` · `GRAPH-VARIABLES-VERDICT`(归档) · `GRAPH-VARIABLES-FINAL` · `TERRAIN-WRITE-RISK` ·
  `TRANSFORM-VIA-RECREATE` · `GEOMETRY-THREE-WAYS` · `COMMAND-ROUTE-MAP` · `REVISION-ECONOMY` ·
  `SAVE-WRITE-ATTRIBUTION`(归档) · `SAVE-WRITER-FINAL` · `GIA-TRUTH` · `GRAPH-RUNTIME-EVIDENCE`
- **勘察清点（23）**：`OFFICIAL-CHAPTERS-LEADS` · `OFFICIAL-COMPONENT-CATALOG` · `SKILL-ASSET-VERDICT` · `OFFICIAL-PLAYTEST` ·
  `COMPONENT-SWEEP-PLAN` · `COMPONENT-OP-PROOF-PLAN` · `PREFAB-FIELDS-MINE` · `GIL-FIELD-LEDGER` ·
  `MINED-INTERFACES` · `NATIVE-MEMORY-MAP` · `NATIVE-HALF-CAPABILITIES` · `EDITOR-REGISTRY-MINE` ·
  `GIA-EXPORT-MINE`(归档) · `GRAPH-LOG-SHAPE` · `ENTITY-PROPERTIES-MINE` · `ENTITY-READABLE-FIELDS` ·
  `GRAPH-SIZE-LIMITS` · `BUILD-PLAN-CEILING` · `NODE-PLACEABILITY` · `PRIMITIVE-VERDICTS` · `TERRAIN-WRITEBACK-EXPERIMENT` ·
  `UI-HUD-FINAL`(归档) · `PLAYER-VISIBLE-VERDICT`

---

## 四、FULL LIST —— 每份报告一行 + 判决（取自报告本身）

> 判决用语：**能**＝报告自己结论为能做到（含「只离线/已编译未真机」，另注）；**不能**＝已证做不到或本仓检索范围内精确缺席；
> **未知**＝报告自己判未决。括号注＝该报告自己给的强度/边界词。**(归档)** ＝已移入 `archive/`（见 §五）。

| 文件 | 判决 | 一句话（取自报告自身结论） |
|---|---|---|
| `ASSET-MEASURE-MINE.md` | **不能** | 模板尺寸无任何离线来源；9 候选关死，唯一开放＝1017 形状组件（两次抓包 geometryComponentCount 均 0） |
| `BINDING-SYMBOL-AUDIT.md` | **不能** | 307 legacy 符号 299 已用；无「零成本写回」配对；缺 3 个读回 getter（`ngMKKCVBuMA`/`RJCKKnWqvLO`/`ur7KK2NiYZ4`） |
| `BUILD-INTERRUPT-HAZARD.md` | **能**/不能 | build 中途死掉留 6–7 节点、0 边、不可逆；三层标记寿命不同；重跑＝重放不重执行（防重放＝能，回滚＝不能） |
| `BUILD-PLAN-CEILING.md` | **能**/不能 | `build-plan` ≤128 节点、稠密图≈96 撞 16000 B；真机每派发≈12.9 s；第二次 build-plan 不能 |
| `CHANNEL-2001.md` | **不能** | 通道 2001 定义在、发送器被 `if(false)` 掐死、无接收器；翻常量≠加组件路径（且 2001 是改已有组件的字段） |
| `BUILD-PLAN-LIMITS.md` **(归档)** | **能**/不能 | `build-plan` 硬限制（空图 / ≤128 节点 / 同图一次）；真正瓶颈是 16000 字节请求行 —— 被 #9/#10 顶替 |
| `COLLISION-COMPONENT-ID.md` | **未知** | 组件枚举实测 **46 成员**（值域 0–47 缺 2、10）；探针 id＝枚举值（强证据、未真机）；更正「47 项」 |
| `COLLISION-TRIGGER-MINE.md` | **不能** | 碰撞触发器是实体通用组件；图半边已齐，缺的唯一原语是「加组件」（无 `Add*Component*`） |
| `COMMAND-ROUTE-MAP.md` | **不能** | 38 条前端命令全表 + 10 调用点；无 transform 命令（CONFIRMED） |
| `COMPONENT-OP-PROOF-PLAN.md` | **未知**/不能 | 组件 op 取证计划：读已编译未真机；删已接线但读半未绑定⇒fail-closed；两半均未真机 |
| `COMPONENT-READ-VALUE.md` | **能**/不能 | 读 op 解锁「能核实」（人配、机核）；加组件仍无原语。回执形状以适配器为准 `{id,enabled,x,y}` |
| `COMPONENT-SWEEP-PLAN.md` | **未知** | 全关卡组件只读扫荡计划（PLAN，不执行；一条都没跑） |
| `COMPONENT-WRITER-MINE.md` | **不能** | 组件一等公民、封闭枚举；读得出删得掉，**加不了**（`Add*Component*` 四处 0 命中，含折叠常量盲区声明） |
| `CONFIG-ID-RESOLUTION-MINE.md` | **不能** | 今天无任何离线产物能答「配置ID X 是否存在」；demo 写的整数在整机 `.gil` 查无登记 |
| `DICT-CONSTRUCT-SEARCH.md` | **能** | 两个 id 命名空间完全对称；`建立字典`(1088)/`拼装字典`(1788) 都存在（refutes `CLAUDE.md:74`） |
| `DICT-WIRE-FORMAT.md` | **不能** | dict 常量今天「没有形状可写」（不是慢）；缺的是吃字典的 setter；not writable-by-shape |
| `DICT-WRITE-PROBE.md` | **能**/不能 | (A) 常量 **不能**；(B) 图内构造+连线 **能**（generic→concrete 未被原生物化＝唯一未知） |
| `EDITOR-REGISTRY-MINE.md` | **不能** | 资源 Kind ≥25（工程只认 6/9）；无 UI 资源 Kind；组件不是注册表资源；档案是 `.gip` subtype |
| `EDITOR-STATE-MACHINE.md` | **不能**/能 | 「编辑态 vs 运行态」状态机存在（UI 文案自证）；本仓只有被动观察、无可驱动 setter（试玩靠菜单 Action） |
| `ENTITY-CREATE-FIELDS.md` | **能** | `create` 不送组件；但实体落盘自带 31 项组件表（随 template_id 走）；与探针组件词汇是否同套≠未证 |
| `ENTITY-LIFECYCLE-MINE.md` | **能**/不能 | 销毁事件 72/373 范围为任意实体、无创建者门；工具删不到运行期生成物（缺口方向单一） |
| `ENTITY-PROPERTIES-MINE.md` | **不能** | 实体字段读得深；写只打穿 name/tag/faction 三标量族；组件读写无按语义命名的通路 |
| `ENTITY-READABLE-FIELDS.md` | **未知** | 实体模型 ~24 可读槽、项目只读 8 个；其余 ~12 UNREAD 但 7.1 符号名全已知（缺读 op，不是缺符号） |
| `GEOMETRY-THREE-WAYS.md` | **不能** | B 读＝null；C（编辑器缓存）与 A 矛盾（全零 vs z≈2.911）；唯一对得上的是 B(建参)×A(落盘) |
| `GIA-EXPORT-MINE.md` **(归档，REFUTED)** | **不能** | 框架判定+节点表可走行，但§4「无边编码」**已被 GIA-TRUTH 证伪**；结论须以 GIA-TRUTH 为准 |
| `GIA-TRUTH.md` | **能** | `.gia` 框架＝`.gil` subtype 3；节点表与**边都可走行**（对 plan 16/16+15/15）；导出回执本身不带内容 |
| `GIL-FIELD-LEDGER.md` | **未知** | `.gil` 顶层已观测 47 字段号（10 实证/~14 推断/~23 无名）；最大洞 field 15；三条读法冲突未决 |
| `GRAPH-ATTACH-CHAIN.md` | **不能** | 图挂上了实体但**没有任何东西会去跑它**（事件节点只在配了碰撞触发器的实体上触发） |
| `GRAPH-DELETE-FIX.md` | **不能** | 根因＝引用相等谓词+两对象图；统一查找是正确修法但不充分（注册表侧无 delete 原语⇒须 fail-closed） |
| `GRAPH-DELETE-PROBE.md` **(归档)** | **不能** | 匹配谓词引用相等恒 false（四测皆 0，结构性）；被 GRAPH-DELETE-FIX 推进并给判决顶替 |
| `GRAPH-LOG-NEXT-STEP.md` | **未知** | 更正 #3 卡点定位：记录自带 proto-58 `graphId`（桥没读）；下一步＝加宽 `CaptureRunLogRecord` |
| `GRAPH-LOG-REACHABILITY.md` | **能** | 日志族 5 op 全部到得了队列（0 个需要额外字段）；「到队列」≠「证据够用」 |
| `GRAPH-LOG-SHAPE.md` | **未知** | 记录里没有任何被读出的节点 id；名字槽在真机是运行实例 id；节点 id 字段（proto 数值）未证 |
| `GRAPH-RUNTIME-EVIDENCE.md` | **未知** | 边分四层：E1 有；E2 可解未对 demo；E3 闸死；E4 弱通道只能证节点。下一步＝解 `.gil` 的边 |
| `GRAPH-RUNTIME-VERIFY-MINE.md` **(归档，REFUTED)** | **不能** | 5 日志 op 按原样翻不动 `runtimeVerified`（41 次 0）；卡点定位已被 GRAPH-LOG-NEXT-STEP 更正 |
| `GRAPH-SIZE-LIMITS.md` | **能**/不能 | `AuthoringGraph` 尺寸全表：三门票汇合于 128 节点；边/常量无独立上限；天花板是请求行字节 |
| `GRAPH-VARIABLES-FINAL.md` | **能**/不能 | F1 终判：`323/337/351` 是普通节点（`add-node` 可放置，**未建**非做不到）；图级变量表 `graph_variables` 我方无写入口（定义层阻塞） |
| `GRAPH-VARIABLES-PROBE.md` **(归档)** | **不能**/能 | 工具层零入口成立；引擎装配层有建/插/删/改名原语 —— 其「未知」已被 GRAPH-VARIABLES-FINAL 切分定案 |
| `GRAPH-VARIABLES-VERDICT.md` **(归档)** | **未知** | 对探针的独立复核（判未知）—— 被 GRAPH-VARIABLES-FINAL 终判取代 |
| `LEVEL-CREATE-MINE.md` | **不能** | 建关卡：命令面不可达（0 命中）、文件面字节已解、策略面 fail-closed（守真漂移）；非引擎限制 |
| `MINED-INTERFACES.md` | **能/只离线/未验证** | 逐行接口索引（挖法/实现/真机证据/状态）；§11 为负结论表 |
| `NATIVE-ACTION-COST.md` | **能**/不能 | 加第 7 个原生动作：注册机械（≈11 处加一行）；能力面须先逆向新原生调用；最便宜＝纯读动作 |
| `NATIVE-ACTION-SET-MINE.md` | **能**/不能 | 6 动作＝5 个 HR_ACTION(0..4)+1 只读选择器；MISSING DISCOVERY not HARD BOUNDARY |
| `NATIVE-HALF-CAPABILITIES.md` | **能**/不能 | version_guard＝四道互不相通的门；图/场景两半全绿；红的只有最窄的 `game` 半（连累 5 个 legacy 写盘器） |
| `NATIVE-MEMORY-MAP.md` | **能**/不能 | 原生地址/偏移可检索地图；读得最窄的是位置偏移与 component 列表（至今为空） |
| `NODE-PLACEABILITY.md` | **能** | 500/500 服务端定义按构造可放置（0 声明零 pin）；六模块域≈67/500；可放置≠可连≠可配≠可运行 |
| `OFFICIAL-CHAPTERS-LEADS.md` | **不能** | 官方 218 章收缩为 5 个缺失原语 P1–P5；本工程一条都没有 |
| `OFFICIAL-COMPONENT-CATALOG.md` | **不能** | 组件家族 30 章枚举 + 三个 demo 组件字段级 spec；文档给按钮，工具无写入原语 |
| `OFFICIAL-PLAYTEST.md` | **不能**/未知 | 官方「试玩」章逐字还原（代码侧互补件）：不能触发进入、by design 读不到校验结果、不能退回编辑；察觉状态未知 |
| `PLAYER-VISIBLE-VERDICT.md` | **能**/不能 | 零资产可见通道仅 `308`/`266`/`835`（+弱 `846–848`）；文字/UI 一条都没有；③真机层＝0 |
| `PLAYTEST-CONTROL-MINE.md` | **不能**/未知 | bridge 面零 `start-playtest` 入口；唯一候选＝`open-editor-panel` 菜单 Delegate 通路（未执行） |
| `PREFAB-COMPONENT-PATH.md` | **不能** | 预制体与实体组件对称：同集合/同 Add/命令面都只有删；组件是「数据」随加载到达，不是命令 |
| `PREFAB-FIELDS-MINE.md` | **能**/不能 | `prefab-fields-page` 深读给出组件类型集合（与 46 枚举互证）；参数全 0、几何全无 |
| `PREFAB-INSTANTIATE-MINE.md` | **不能** | 预制体实例化不是第二条摆放路（只吃 prefab id、无坐标、真机证伪）；`place_builtin`＝create 别称 |
| `PRIMITIVE-VERDICTS.md` | **能/不能/未知** | 23 条原语一页判决表（有/无/未知 + 证据 + 下一步）；本目录的「能不能」总表 |
| `REOPEN-VERIFICATION-MINE.md` | **未知**/不能 | reopen 是唯一送回游戏加载器的通道，但被常量关卡 id 钉死、门禁已红；机制活、现状死，不要现在发射 |
| `REVISION-ECONOMY.md` | **能**/不能 | 260 个修订号（R2..R269，8 缺口）；同号在租约收尾后可再注入；新能力必须升修订 |
| `SAVE-WRITE-ATTRIBUTION.md` **(归档)** | **能** | 写入方＝游戏进程（非本工程）；追加发生在 save 事件 —— 被 SAVE-WRITER-FINAL 定案取代 |
| `SAVE-WRITER-FINAL.md` | **能** | 定案：写 `.gil` 的是游戏/编辑器写入方；无 `field 1` 条目来自写入方内存（早于本工程 save 能力），会复发 |
| `SETTER-SIGNATURE-SURVEY.md` | **不能**/能 | 9 个 setter 全被引用（无未使用 setter）；vector/guid/dict 无 setter；最便宜新写＝补 3 个读回 getter |
| `SKILL-ASSET-MINE.md` | **不能** | 技能＝编辑器资产模板同类（配置ID 类型 6/28/37，与货币 10 同表）；技能创建卡同一条缺失原语（无写入面建带配置ID 的编辑资产） |
| `SKILL-ASSET-VERDICT.md` | **能**/不能 | 判决（CONFIRMED）：技能与货币/道具模板同一 KIND；建模板原语一并解锁两处（**不含**加组件）；零真机 |
| `TAB-DIRECTORY-MINE.md` **(归档)** | **能**/未知 | root field 6 的追加是写入方干的纯尾部追加 —— 被 SAVE-WRITER-FINAL 定案取代 |
| `TEMPLATE-CREATION-MINE.md` | **不能** | 38 路由无一条建模板；模板不在 `.gip`；落点候选＝`.gil root field 15`（type 11 背包已确在） |
| `TERRAIN-WRITE-RISK.md` | **不能**/未知 | 写入方＝游戏进程、从内存重生成整文件；持有态写回必被覆盖；关闭态跨会话未定 |
| `TERRAIN-WRITEBACK-EXPERIMENT.md` | **未知** | 写回安全实验设计（未执行）：单格改动＝恰好 1 字节；两个前置未决，建议推迟 |
| `TRANSFORM-VIA-RECREATE.md` | **不能** | 「删+重建」技术可行但不是移动（换 id、断绑定、两次 native 写周期）；结论：布局一次设计好、永不移动 |
| `UI-CONTROL-WRITE-MINE.md` | **不能**/能 | 编辑器侧无任何 UI 写入口；`presentation` 家族（266/835/308…）是零 UI 资产的旁路（CANDIDATE 未真机） |
| `UI-HUD-FINAL.md` **(归档)** | **不能** | `ui.hud` 收口：桥 7 个面板 op 只开面板/导航/只读；注册表无 UI 资产 Kind —— 被 PLAYER-VISIBLE-VERDICT 汇总 |
| `UNBOUND-SYMBOL-AUDIT.md` | **能** | 「未绑定符号」bug 收敛到 2 文件 5 符号；7.1 里全在，全是补绑定不是重挖 |
| `VISIBLE-NO-ASSET.md` **(归档)** | **能**/不能 | 零资产且自身产生可见效果的只有 `308`；所有文字通道都要资产 —— 被 PLAYER-VISIBLE-VERDICT 终审取代 |
| `WAVE-SPAWN-PATH.md` | **能**/不能 | 元件型创建 252/757/256 存在（刷新记忆：刷怪不必走布设组）；布设组无写入原语；对 M6b 无新增 |

---

## 五、REFUTED / 更正 与 归档（archive/）

### 5.1 中心结论被**证伪（REFUTED）** 的报告

| 报告 | 被谁证伪 | 被证伪的那一条 | 指针 |
|---|---|---|---|
| `archive/GIA-EXPORT-MINE.md` | `GIA-TRUTH.md` | §4「这些 `.gia` 里没有边编码」 | `GIA-TRUTH.md` §0（"REFUTED"）、§3（真实导出的边对 plan 16/16+15/15 命中）；其前提「工程从未分析过 `.gia`」亦被 §1 证伪（自 2026-09-16 起即有解码器） |
| `archive/GRAPH-RUNTIME-VERIFY-MINE.md` | `GRAPH-LOG-NEXT-STEP.md` | 「卡点＝记录认不回自己的图」 | `GRAPH-LOG-NEXT-STEP.md` §0/§1.2：真正卡点是桥没读记录自带的 proto-58 `graphId`；#3 把「RPC 没回」与「回而空」混谈、把 `acknowledged:false` 当信号（实为硬编码字面量） |

> 其余「已被更正」但**中心结论未变**的（仍留主目录，引用时须带更正）：
> - `COMPONENT-WRITER-MINE.md` §0/§2.2 记组件枚举「**47 项**」，**实测 46 成员**（`COLLISION-COMPONENT-ID.md` §1.2 更正；`COMPONENT-READ-VALUE.md` §0 亦用 46）。
> - `COMPONENT-WRITER-MINE.md:400-404` 预测探针回执 `{componentId, enabled}`，**适配器实际回 `{id, enabled, x, y}`**（`COMPONENT-READ-VALUE.md` §1.1、`COMPONENT-OP-PROOF-PLAN.md` §1.1 更正；**以适配器为准**）。
> - `COMPONENT-OP-PROOF-PLAN.md` 旧标题句「读已编译、删连编译都没进去」**已过期**：删 `delete-entity-component` 当晚已接线（`COMPONENT-OP-PROOF-PLAN.md` §0、`CLAUDE.md:77-82`）。
> - `WAVE-SPAWN-PATH.md` 更正工程记忆 `wave-gating-is-entity-placement-groups`（「刷怪必须走布设组」被官方 `mhw66orrrfkm` 证伪）。
> - `DICT-CONSTRUCT-SEARCH.md`/`DICT-WRITE-PROBE.md` 推翻 `CLAUDE.md:74`「500 条定义里没有一条构造字典」的过度概括（判决应改为「无 type-27 **输出**的构造器」）。
> - `GRAPH-VARIABLES-FINAL.md` 是 F1 的**终判**，它把 `GRAPH-VARIABLES-PROBE/VERDICT` 的「未知」切成**节点层（可放置）/定义层（阻塞）**两判（三者中以前者为准，旧两篇已归档）。
> - `SAVE-WRITER-FINAL.md` 是「谁写这份 `.gil`」的**定案**（与 `SAVE-WRITE-ATTRIBUTION.md`、`TAB-DIRECTORY-MINE.md` 结论一致并定死；旧两篇已归档）。
> - **组件偏移 / 地址（2026-10-11）**：`COMPONENT-WRITER-MINE.md`、`COLLISION-COMPONENT-ID.md`、`COLLISION-TRIGGER-MINE.md`、`COMPONENT-READ-VALUE.md`（连同 sibling 的 `NATIVE-ADD-COMPONENT.md` / `NATIVE-COMPONENT-CREATE.md` / `docs/gameplan/ADD-COMPONENT-MODEL-PATH.md`）旧记 **容器 `[entity+0x48]`、kind 字段 `[comp+0x30]`** —— **两处均已证误**：容器是 **`[entity+0x68]`**、kind 是 **`[comp+0x34]`**（`+0x30` 现为 byte `enabled`）；且这批报告里的 RVA（`0x914de40` / `0xcb64140` / `0x10abeb40` / `0x10ac2670` / `0x102d4750` / `0x10ac50a0` / `0x102d4a60` / `0x914ccd0`）**在当前映像里都已过期，须重导**。**以 `docs/research/reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md` 为准。**
> - **（补记，2026-10-11 复核）** 另有两份文件**同批更正但上一版汇总漏列**，本次补入：`docs/research/beyondeditor-user-operations/db/operations.json:290`（`notes` 已改注「取第 3 号组件（`0x10aa6800`，读 `[entity+0x48]`——**非组件容器**）」）与 `docs/gameplan/ADD-COMPONENT-OP-DESIGN.md:345`（已改注「编辑器原生 store（`[entity+0x68]`；旧记 `[entity+0x48]`，**已证误**——`+0x48` 是 map 访问器）」）。两处均已现场读回复核。

### 5.2 已顶替（SUPERSEDED）→ 移入 `archive/`（移动，未删除）

被移走的 11 份与顶替它们的新报告，逐条记于 **`archive/MANIFEST.md`**。摘要：

| 归档文件 | 顶替者 | 判据 |
|---|---|---|
| `GIA-EXPORT-MINE.md` | `GIA-TRUTH.md` | GIA-TRUTH §0 逐条 settle 其四问并判 §4 REFUTED |
| `BUILD-PLAN-LIMITS.md` | `BUILD-PLAN-CEILING.md`（＋`GRAPH-SIZE-LIMITS.md`） | CEILING §1 明说「核实其行号并延伸」#8 |
| `GRAPH-DELETE-PROBE.md` | `GRAPH-DELETE-FIX.md` | FIX §0/§1「据其证据推进并给判决」 |
| `GRAPH-RUNTIME-VERIFY-MINE.md` | `GRAPH-LOG-NEXT-STEP.md` | NEXT-STEP §0 推翻 #3 的卡点定位 |
| `VISIBLE-NO-ASSET.md` | `PLAYER-VISIBLE-VERDICT.md` | PVV「终审…不再重开这个问题」，重排三兄弟名次 |
| `UI-HUD-FINAL.md` | `PLAYER-VISIBLE-VERDICT.md` | PVV 把 UHF 列为先行报告并汇总复核 |
| `BRIDGE-CRASH-SAFETY.md` | `BUILD-INTERRUPT-HAZARD.md` | HAZARD §0「把『中断安全』这一条**收口**」，重述并延伸其结论 |
| `GRAPH-VARIABLES-PROBE.md` | `GRAPH-VARIABLES-FINAL.md` | FINAL §0 自述为 F1「终判」，「把前两者的『未知』再切一刀」 |
| `GRAPH-VARIABLES-VERDICT.md` | `GRAPH-VARIABLES-FINAL.md` | 同上（FINAL 是其复核结论的终局） |
| `SAVE-WRITE-ATTRIBUTION.md` | `SAVE-WRITER-FINAL.md` | FINAL §0 自述「一次走完 live 存档、**定死**」，结论与其一致并定案 |
| `TAB-DIRECTORY-MINE.md` | `SAVE-WRITER-FINAL.md` | 同上（FINAL §0 对 root field 6 追加给出定案归属证据） |

> **归档不删除**：`archive/` 内文件保留原文件名，任何引用仍可按 `archive/<原文件名>` 找到。

---

## 六、口径与维护

- 本索引**只搬运**被索引报告的判决，不新增事实主张；引用某条前请回原报告的「一句话结论 / 判决」段复核。
- **三层不合并**：报告各自的 `文档写了什么` / `工具能做什么` / `真机验证过什么` 分标被保留；凡见「能」请确认是
  真机（有独立读回/字节差分）还是**只离线/已编译未真机**。
- **op 计数等派生物不固化**：桥 op 数、修订号等随源码变动，**唯一权威**是 `tools/gameplan/tests/test_doctrine.py`；
  本索引引用它们时只指向该检查，不给死数。
- 新增/移动报告后须同步本文件与 `archive/MANIFEST.md`。

*本文件由 2026-10-10 会话只读整理自 `docs/research/reverse-eng-20261010/` 下 73 份报告本身；
未连接桥、未发送任何请求、未触碰游戏/编辑器/存档。*
