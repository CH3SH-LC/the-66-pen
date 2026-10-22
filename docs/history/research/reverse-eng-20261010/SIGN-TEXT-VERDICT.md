> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 判决 — 牌子/气泡文本通道（#6 capability）

**产出**：2026-10-10 · `docs/research/reverse-eng-20261010/SIGN-TEXT-VERDICT.md`（本轮我唯一拥有的文件）。
**口径**：纯离线、纯只读。未连桥、未发任何报文、未启动/触碰游戏或编辑器、未注入、未提权、未重启 helper、
未读写 `C:/Users/PUBLIC_USER/AppData/LocalLow/`、未读任何图片或 PDF。
**独立复核对象**：`SIGN-TEXT-MINE.md`（wave21）、`docs/research/reverse-eng-20261010/archive/VISIBLE-NO-ASSET.md`、
`docs/research/game-b-systems-20261009/F5-visible-feedback.md`。本判决的每条证据都是本会话**重新读取源文件**得到的，
不是转述；与 MINE 一致处标注一致，新增的精确性处单独标出。

---

## 0. 判决（ONE WORD）

# **NEGATIVE**

**牌子（告示牌/提示牌/标牌）不是「零资产、玩家可见文本」通道。运行时没有任何原语能把文本写到实体上。**
缺失的资产类型见 §4：**一个挂载于宿主实体的「文本气泡组件」（`BeyondCompTypeTalk=28`，内含编辑期写好的
文本气泡列表 {@link 文本内容}）**——等价地，铭牌路线缺 **「铭牌组件」（`BeyondCompTypeNameplate=27`）**。

---

## 1. 节点面：本仓**没有** 标牌/提示/告示 节点；只有「文本气泡」与「铭牌」两族

扫 `data/node-contracts/definitions/*.json`（810 定义），关键字 `气泡/标牌/提示/铭牌/牌子/告示`
→ 命中**仅 5 条**（复现 §6 命令 1）：

| defId | 名称 | 关键入参（逐字 pin 名 · raw 类型码） | 吃资产还是吃实体？ |
|---:|---|---|---|
| **631** | 切换生效的文本气泡 | `目标实体`(data) + **`文本气泡配置ID`(raw=**1**)** | **吃配置ID** |
| 679 | 文本气泡完成时 | 纯输出事件：`气泡归属者实体`·`角色实体`·`文本气泡配置ID`(1)·`文本气泡完成次数`(2) | 继承 631 依赖 |
| 615 | 添加实体生效铭牌 | `目标实体` + **`铭牌配置ID`(raw=**1**)** | **吃配置ID** |
| 616 | 删除实体生效铭牌 | `目标实体` + **`铭牌配置ID`(raw=**1**)** | **吃配置ID** |
| 617 | 设置实体生效铭牌 | `目标实体` + **`铭牌配置ID列表`** | **吃配置ID列表** |

**没有任何叫「标牌 / 提示 / 告示 / 牌子」的节点**（这些词在 810 定义名里命中 0）。
本仓唯一「在世界内实体上显示文本」的两族就是上表的气泡族（631/679）与铭牌三连（615/616/617）。

**pin 证据（逐字、带行号）**：
- 631 定义块 `data/node-contracts/variants/server/bucket-02.json:7283`（`definitionId: 631`，`:7307` 名 `切换生效的文本气泡`）。
  其 `文本气泡配置ID` pin：`direction=input`、`kind=data`、`index=1`、**`valueTypeNameRaw="1"`、`valueTypeValueRaw=1`**
  （`bucket-02.json:7444`），pin 名 `"文本气泡配置ID"`（`:7461`／解码名 `:7465`）。端口 `provenanceLocator`
  = `live-node-schema.json#nodes[id=631,…].definition.pins[3]`——**活读来源，非推断**。
- 615 `bucket-05.json:6716`（`铭牌配置ID` pin 名 `:6870`）；616 `bucket-02.json:6777`（pin 名 `:6931`）；
  617 `bucket-03.json:7420`（`铭牌配置ID列表` pin 名 `:7574`）。

## 2. 类型码 1 是什么？——**实体/配置引用（GUID 类）**，不是自由字符串

`data/node-contracts/shared/value-type-codes.json` 的 `codesObservedInThisRead` 记 `valueTypeName "1"`（265 条 pin）。
其 `historicalInferredNames.rows` 里 code 1 的样名逐字为 `技能配置ID / 单位状态配置ID / configReference / entityReference`，
`inferredType` = **「实体/配置引用（GUID 类）」**（该表自标 `project-inference, 7.0-era`）。
⇒ 631 的 `文本气泡配置ID` 与铭牌三连的 `铭牌配置ID` **都是引用一个编辑期资产的 ID，不是要显示的那句话本身**。

**反证——没有「实体 + 字符串 → 显示」形状的节点**：枚举全部 929 个变体里 `direction=input && valueTypeNameRaw=="5"`（字符串口）
的节点，**共 69 个**（复现 §6 命令 3）。逐条看名：日志（`1 打印字符串`）、变量/定时器/运动器/挂接点**寻址键**、
模板/能力单元/数据**名称键**、图间信号（`200039`/`200117`）、AI 战术上下文——**没有一条把字符串渲染到实体上**。
（与 `SIGN-TEXT-MINE.md` §2.3 一致；本会话重跑得到同一 69 名单。）

## 3. 官方语料：文本气泡/铭牌的**文本内容是编辑期写死的配置项**

`docs/official-docs/chapters/mhwtz297kp6a.json`（title=文本气泡）逐字 fact：
- definition：`文本气泡组件…挂载于实体…在关卡运行时显示配置内容`；
- hard-restriction：`可以配置多个文本气泡但仅支持同时生效一个文本气泡`；
- button-path：`实体/元件编辑界面 → 组件编辑页签 → 添加组件 → 选择文本气泡 → 详细编辑`；
- field-name：`持续时间 / 文本内容` = `显示文本编辑，支持插入变量（选择指定实体的自定义变量，会在文本框内实时更新）`；
- node-name：`切换生效的文本气泡…通过节点输入的**文本气泡序号**，将替换为最新的生效文本气泡`。

⇒ 631 是**在一个编辑期配好的气泡列表里选生效项**（序号/配置ID），**不写任意文本**。
「牌面字随变量实时变」是官方**有**的能力，但那只对**编辑期写进组件的 `{类型:前缀.变量名}` 占位符**成立——
**写占位符这个动作没有任何原语**。

铭牌章 `docs/official-docs/chapters/mh5n160t2b6w.json` 同构：组件挂载于实体、`铭牌X`＝配置ID、`文本内容`支持变量。

**官方无牌子章节**：`grep -rc "告示牌\|提示牌\|标牌\|指示牌\|木牌" docs/official-docs/chapters/` → **全部 0 命中**；
218 章里 name 含 `牌/气泡/铭/文本` 的标题只有 `铭牌`(mh5n160t2b6w)、`文本气泡`(mhwtz297kp6a) 与
UI 控件族（`文本框界面控件`/`文本视窗控件`/`多语言文本`/`卡牌选择器界面控件`/`按键提示控件`）。
「牌子＝能显示文本/数字」是**工程侧推断，不是官方陈述**（与 `F5-visible-feedback.md:71-74` 同判）。

## 4. 牌子 prefab 默认带文本组件吗？——本次范围内**无证据**，且反向证据占多数

四个牌子逐字名（`docs/research/entity-create/prefab-name-directory.json`）：`20001487=告示牌`、`20001548=木质告示牌`、
`20002809=木质提示牌`、`20002810=木质提示牌`。回执 `prefab-catalog-response.json`（2722 条）另给图标路径，逐字：
`…/UI_Beyd_Gadget_Prop_Gaoshipai_03.png`、`…/UI_Beyd_Gadget_Prop_GaoShiPai_01.png`、
`…/UI_Beyd_Gadget_Prop_JianTou_01.png`、`…/UI_Beyd_Gadget_Prop_JianTou_02.png`——
**全是 `BeydGadgetIcons` 美术道具图标**。`木质提示牌` 的图标名是 `JianTou`（**箭头**），即它是**指示箭头牌**，不是可写字的板。

唯一能读「预制默认挂了哪些组件」的深读回执 `prefab-fields-page-response.json` 三文件合计 **128+34+32 = 194 个**预制，
其中：
- 四个牌子 ID **一个都不在**（`grep 20001487|20001548|20002809|20002810` = 0 命中）；
- **`BeyondCompTypeTalk`（文本气泡组件）计数 = 0**，`BeyondCompTypeNameplate` = 0；本批里只出现过
  1×`BeyondCompTypeMinimapMark`、1×`BeyondCompTypePopUp`（复现 §6 命令 4）。

⇒ 在「预制默认带 `Talk` 组件」这件事上，本仓 194/2722 的真实回执里**没有任何先例**，且**告示牌不在样本内**
（诚实边界：「搜不到」≠「一定不带」）。
组件类型枚举（`.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs`）
`BeyondCompTypeNameplate = 27`(`:30`)、`BeyondCompTypeTalk = 28`(`:31`)——**47 个组件类型里没有 Sign/Board/Text/Billboard**，
「牌子上的字」若存在也只能是这两个**通用**组件之一。

## 5. 即使牌子带了 Talk 组件也**不翻案**：加组件这条路本身是封死的

`CLAUDE.md` §六(a)：「给实体加组件」已证不存在（实体侧与预制体侧同）；文本内容与配置ID都只在编辑器 UI 里生成
（`mhwtz297kp6a` button-path）。`entity.create` 也不送组件/名字（`tools/game-executor/native/scene_calls.cpp:47`
`optional_data=nullptr`），实体组件集随模板走。
⇒ 缺的不是「牌子」，缺的是 §0/§4 的两件资产之一（气泡组件 或 铭牌组件），而**造资产 + 加组件两条路都没有原语**。

**若要把本判决定案翻面（本轮未做）**：H1 需真机 `prefab-fields-page` 覆盖到 `20001487` 读其默认组件集是否含 `Talk(28)`；
H2 需穷举「折叠常量命令面」找有没有能把字符串写进实体文本的原语（明文名范围已 0 命中）。**H1 成立也只给「显示一句
编辑期预置、且已配好配置ID的话」，仍非零资产、仍不接受运行时任意文本。**

---

## 6. 复现命令（纯只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 7. 引用表

| 论断 | 证据（file:line） |
|---|---|
| 631 定义 / 名 | `data/node-contracts/variants/server/bucket-02.json:7283`,`:7307` |
| 631 `文本气泡配置ID` 为 `raw=1` 的 data 入参 | `data/node-contracts/variants/server/bucket-02.json:7444`（`valueTypeNameRaw":"1"`）、`:7461`（pin 名）；pins[3] |
| 615/616/617 pin 名 | `bucket-05.json:6716`/`:6870`、`bucket-02.json:6777`/`:6931`、`bucket-03.json:7420`/`:7574` |
| 类型码 1 ＝ 实体/配置引用（GUID） | `data/node-contracts/shared/value-type-codes.json`（`historicalInferredNames.rows` code 1，样名 `技能配置ID`/`configReference`） |
| 文本气泡：手工挂组件·只生效一个·文本内容为编辑期配置·631 按序号切换 | `docs/official-docs/chapters/mhwtz297kp6a.json`（facts: definition / hard-restriction / button-path / field-name `持续时间 / 文本内容` / node-name `切换生效的文本气泡`） |
| 铭牌：挂载于实体·`铭牌X`＝配置ID·文本内容支持变量 | `docs/official-docs/chapters/mh5n160t2b6w.json` |
| 官方无牌子章节（0 命中） | `grep -rc "告示牌\|提示牌\|标牌\|指示牌\|木牌" docs/official-docs/chapters/` |
| 组件枚举 `Nameplate=27` / `Talk=28` | `.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:30-31` |
| 牌子名逐字 | `docs/research/entity-create/prefab-name-directory.json`（20001487/20001548/20002809/20002810） |
| 牌子图标＝美术道具 | `.runtime/editor-bridge/runs/…/prefab-catalog-response.json`（四 registryId 的 `iconPath`） |
| 194 预制回执 Talk=0、无牌子 | `.runtime/editor-bridge/runs/{8c515535-…,ce2f82fd-…,c980a8f9-…}/prefab-fields-page-response.json` |
| 加组件不存在 | `CLAUDE.md` §六(a)；`PREFAB-COMPONENT-PATH.md`（§4 判决） |
| create 不送组件/名字 | `tools/game-executor/native/scene_calls.cpp:47` |
| 最省零资产可见通道＝308 | `docs/research/reverse-eng-20261010/archive/VISIBLE-NO-ASSET.md`（§5） |
| 牌子/数字无官方关联 | `docs/research/game-b-systems-20261009/F5-visible-feedback.md:71-74` |

*本文件由 2026-10-10 会话离线复核整理；全程未连桥、未发任何请求、未触碰游戏/编辑器/存档、未读写 LocalLow、未读图片或 PDF。
行号为本次 checkout 实测；凡「未找到/无证据」均已标注检索范围。*
