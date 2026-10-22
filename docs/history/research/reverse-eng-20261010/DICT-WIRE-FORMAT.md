> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 字典在线上长什么样 — M5 出售货币字典的线格式 (DICT-WIRE-FORMAT)

日期: 2026-10-10 · 任务 #7
范围: **纯离线、纯只读**。未连桥、未向游戏/编辑器发任何报文、未启停任何进程、未编译/未注入、未写任何存档或 `.gil`。
证据只有三处: ① 仓内 C# 源码 ② 仓内研究文档 ③ `.runtime/editor-catalog/resolved/` 里 12375 个反编译 `.cs`（用 **Bash `grep -rI`** 查，Grep 工具会静默跳过 `.runtime/`）。
**本文件只读不写**，仅新增本文件本身。

按 `CLAUDE.md` §一.3、§五: `文档写了什么` / `工具能做什么` / `真机验证过什么` 三层分开标（见附录 B）。

---

## 0. 结论先行 (verdict)

**M5 里那个拒绝是对的。一个 dict 常量（contract 类型 27 / `valueTypeValueRaw` 10003）今天不是"写起来慢"，是"根本没有形状可写"。**

| 问 | 答 | 依据 |
|---|---|---|
| 桥能写哪些槽？ | 只有 `auto / int / enum / bool / float / string` 五个标量 + 一个 `list`（10002） | `AuthoringGraph.cs:41`、`:901-972`、`:1004-1022` |
| dict 常量走哪条路都会怎样？ | **两条路都按名字拒绝**：`auto` 路抛 `AUTHOR_VALUE_SLOT_UNPROVEN`，显式路抛 `AUTHOR_VALUE_SLOT_UNSUPPORTED` | `:879-888`、`:969-970` |
| 组件模型里有容器字段吗？ | **没有**——四个字段全是标量（uint/bool/double/double） | `taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:12-35`；7.1 名字见 `EntityComponentProbe.cs:24-31,82-87` |
| 语料里有"字典字段"吗？ | **没有**。整个 resolved 语料 **0** 处中文 `字典`；`Dictionary<...>` 全部是 BCL 缓存/方法参数，**没有一个是消息/序列化字段** | §2.2、§3.2 |
| 最接近"字典序列化"的东西是什么？ | 节点图的 **serverParamDictionary**：`keyParamType`+`valueParamType`(uint) + kv 列表 | `NXXlkoibwEPCmEK7rwpH.cKP1Y2ibBlYiRhYw2PZ4.cs:48-50`；`JxwbT6Ku2gFg1GkFYZ0U.oTqkY0KuSgsVkgfGANcX.cs:510,741` |

**判决: 不是"writable-by-shape"——今天没有丝毫形状可写，且未知的不是"格式怎么拼"，而是"pin-value 类型上有没有一个吃字典的 setter"。**
下一步要挖的**符号**（见 §4）: pin-value 类型 `iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG` 上，**首参是 2-泛型 mangled 字典类型的 setter（方法，不是字段）**——
现有 6 个 `Dictionary` 成员**全是 Field，且都不在这个类型上**（`EditorBindingProfile.Generated.cs:661,663,728,820,875,885`）。

> 姊妹文 `DICT-WRITE-PROBE.md`（判决 (A)/(B) 二分）与 `DICT-CONSTRUCT-SEARCH.md`（两个 id 命名空间）已覆盖"有没有构造器"。
> **本文的增量是"线上格式"这一个维度**: 一个 dict 在 ① 引脚常量槽、② 节点图 serverParamDictionary、③ 编辑器消息里**各长什么样**。

---

## 1. `AuthorWriteScalar`：支持的槽位 + 按名字拒绝的存储种类

文件: `tools/editor-bridge/Adapter/AuthoringGraph.cs`（本仓 checkout 实测行号）。

### 1.1 支持的槽位（穷举）

- **声明数组** `AuthorValueSlots`（`:41`）:
  `{"auto","int","uint","enum","float","bool","string"}`。
- **`AuthorWriteScalar` 的 switch**（`:901-972`）只有 5 个标量分支:
  `int`(`:907`) / `enum`(`:919`) / `bool`(`:931`) / `float`(`:943`) / `string`(`:957`)。
- **`list`** 不走 `AuthorWriteScalar`，走 `AuthorWriteList`（`:1004-1022`），逐元素 append。
- **`auto`** 不是"自动识别任意类型"——它只映射两个存储码（见 1.2）。
- **`ValidateAuthorScalar`**（`:45-87`）接受的字面量 tagged key:
  `int`(`:52`) / `uint`(`:55`) / `bool`(`:58`) / `float`(`:62`) / `string`(`:66`) / `list`(`:70`)。
  **没有 `dict` / `map` / `object` 分支**；落到 `default:` → `AUTHOR_VALUE_TYPE_UNSUPPORTED:<tag>`（`:84-85`）。

**一句话: 支持且仅有 `{int, uint→enum, enum, bool, float, string, list<scalar>}`。**

### 1.2 按名字拒绝的存储种类（LIVE-CONFIRM 注释原文引用）

**LIVE-CONFIRM-A**（`:864-872`，`AuthorStorageKind`）——只有三个码被赋义:

> `// The storage-kind code, read from the object itself. LIVE-CONFIRM-A: only three codes are`
> `// given a meaning here, and all three are already relied on in this repo --`
> `//   2 (integer)  AuthoringGraph.cs:479  KiPKKaQUNLS(...)!=2 -> AUTHOR_COUNT_INT_TYPE_NOT_MATERIALIZED`
> `//   6 (enum)     FinishGraph.cs:114     KiPKKaQUNLS(...)!=6 -> FINISH_REPAIR_EXPECTED_ENUM`
> `//   10000 (Generics) AuthoringGraph.cs:446 and pin-config.cs:390,403,704,735`
> `// No other code is interpreted anywhere in this patch.`

**LIVE-CONFIRM-B**（`:874-878`，`AuthorAutoSlot` 头部）——4 和 5 明确点名拒:

> `// "auto" is deliberately narrow: it maps only the two storage kinds whose meaning this repo`
> `// already relies on. Every other code -- including the codes the contract artifact names for`
> `// float and string (4 and 5 in data/node-contracts/shared/value-type-codes.json), which NO`
> `// code in this repo has ever read back through KiPKKaQUNLS -- is refused BY NAME, so the`
> `// caller must state the slot explicitly and accept the read-back check. LIVE-CONFIRM-B.`

对应代码 `:879-888`:

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**LIVE-CONFIRM-C**（`:890-900`）——bool/enum 同元组两槽，read-back 强制:

> `// LIVE-CONFIRM-C: the bool/enum pair shares one declared type tuple (4,4,1) and`
> `// lives in two slots; the read-back is what makes the wrong choice loud instead of silent.`

**LIVE-CONFIRM-D**（`:999-1001`）——list 元素类型不猜:

> `// LIVE-CONFIRM-D: for defId 79 3:3 the proven element is a float; whether an int element`
> `// (defId 70 3:1, whose contract records elementType "unknown") materialises as an int`
> `// slot is NOT known offline, and AuthorAutoSlot will refuse rather than guess.`

### 1.3 全部具名拒绝码（dict 会撞哪些）

| 触发 | 拒绝码（常量原文） | 行 |
|---|---|---|
| `auto` 遇到非 {2,6,10000} 的存储码（**含 dict 27/10003**、含契约命名的 float 4 / string 5、entity 1、vector3 7） | `AUTHOR_VALUE_SLOT_UNPROVEN:<storage>:<payload>` | `:886` |
| `auto` 遇到 Generics(10000) | `AUTHOR_VALUE_NOT_MATERIALIZED` | `:885` |
| 显式 slot 不在 {int,enum,bool,float,string} | `AUTHOR_VALUE_SLOT_UNSUPPORTED:<slot>` | `:969-970` |
| list 槽存储码 ≠ 10002 | `AUTHOR_VALUE_NOT_A_LIST:<storage>` | `:1010` |
| list 元素 tagged key 不是 int/uint/float/string | `AUTHOR_VALUE_LIST_ELEMENT_UNSUPPORTED` | `:80` |
| 标量 tagged key 不认识（如 `{"dict":...}`） | `AUTHOR_VALUE_TYPE_UNSUPPORTED:<tag>` | `:85` |

**注释里"按名字点名 dict"的唯一一处**（`:76-80`，list 元素层）:

> `// A list element is a scalar of a shape the scalar path can already write.`
> `// entity/vector/dict element types are NOT accepted, because no setter for`
> `// them has an in-repo proof (see header note 3).`

**结论**: 一个 dict 形状的引脚（`serverParamType==27` / `valueTypeValueRaw==10003`）**在任何一条标量/list 路径下都被按名字拒绝**；
`auto` 路 → `AUTHOR_VALUE_SLOT_UNPROVEN`，显式路 → `AUTHOR_VALUE_SLOT_UNSUPPORTED`，list 元素路 → `AUTHOR_VALUE_LIST_ELEMENT_UNSUPPORTED`。
游戏侧同一处封锁: `tools/gameplan/paramtypes.py:30 DICT = 27`、`:76 DICT: None`（`SLOT_FOR_TYPE` 不给 dict 槽）、`:62 CONFIG_ID_SLOT = None`。

### 1.4 M5 目标引脚坐实（type 27 确实在 704 上）

`data/node-contracts/variants/server/*.json` 里 `defId 704 设置自定义商店商品出售信息` 的端口记录（实测）:

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

即 **`出售货币字典` = 输入 `3:4`，`serverParamType 27`，`valueTypeValueRaw 10003`**。
`data/node-contracts/shared/value-type-codes.json` 里 `10003` 的实测 pin 名样本正是 `道具字典 / 货币字典 / 道具掉落字典 / 收购物品字典 / 单位状态参数字典`（18 条 pin），`inferredType: "字典"`。

---

## 2. 组件模型：有容器字段吗？

### 2.1 编辑器模型的一等组件（7.1 探针正在读的那个）

`EntityComponentProbe.cs`（R269 编译进去了，`BridgeServer.cs:306` 派发 `inspect-entity-components`）锁定的组件类型是
`tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq`（`EntityComponentProbe.cs:27`，legacy resolved 名 `LudM06iCRNk4iFkwqKIW`），
其字段契约（`EntityComponentProbe.cs:82-87`）:

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

在反编译源码里（`.runtime/editor-catalog/resolved/taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:12-18`）这四个字段的声明是:

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

`t7crdXiRQQTsF520oNMA<T>` 是标量装箱句柄（`EntityComponentProbe.cs:32` 钉住 `BoxedValueType71`，`ComponentValue` `:116-122` 只读它自己的 value 成员）。

**答: 组件模型的四个字段全部是标量装箱句柄（uint/bool/double/double），没有一个容器类型。** 所以"把 dict 塞进组件载荷"这条路**在组件模型这一层就不存在**。

### 2.2 组件线消息也没有容器字段

组件字段变更的 proto 消息 `StN9Qe4wQy9Io9byCM2h.LjBE4Q4wWZw6x2ypkNoY.cs`（legacy），字段（`:28-34`）:

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

载荷是**一组 typed 子消息**（`Rl8QkH4BRjllC26hgrU5` / `rtSCfh4BJTrLNMnpL6H8` / `JLrs0K4Bk5tttLjt2Kb9` / `sPYIA94wvICMC609OFbc` / `in8HJm4wDcP7k4nUjgON`，见 `MergeFrom` `:833-1032` 的分支），
**没有一个字段是字典**。

### 2.3 语料里"某个字段是字典"的声明

对 `.runtime/editor-catalog/resolved/`（12375 个 `.cs`）做 Bash `grep -rI`:

- 中文 `字典` → **0 处命中**（`grep -rlI "字典" .` 返回空；同命令对 `.runtime/editor-catalog/decoded/*.json`、`node-catalog-full.json`、`node-names.json` **有**命中，说明是语料本身没有，不是编码问题）。
- BCL `Dictionary<`/`SortedDictionary<` 的**字段声明**（`grep -rnI`）——全部是**别的类型上的缓存字段/方法参数**，没有一个在组件模型上，**没有一个是消息/proto 字段**。代表样本:
  - `LAyFQgKPQPrUGfinutHp.YI9MtlKPWsxfSCyecHQU.cs:1911` — 泛型工具方法，参 `Dictionary<T,HashSet<T>>`
  - `rURqcAi9hRrcX70F76tM.ObcRoOi9lDgr7M9wQcW4.cs:98` — 方法参 `Dictionary<string, ...>`
  - `X94j8TioZIuN3ZNtOLU7.eIeNq7ioVH2G8Cau2X8C.cs:24` — 静态方法参 `Dictionary<uint, ...>`
  - `XvpSBIuvoMSpMenoIqRg.C9ev3quv9MKMEBmJNJDj.cs:8387` — 方法参 `Dictionary<KeyValuePair<string,uint>, uint>`
  - 缓存字段形式（`private static Dictionary<Type,...>` / `<MethodBase,...>`）散落多处，都是反射缓存。

**答: 组件模型本身、以及整个 resolved 语料，都没有一个"值类型是字典"的字段声明。** "dict 作为一个字段被序列化"这件事，
在本轮检索范围内**在反编译语料里看不到**（范围: `.runtime/editor-catalog/resolved/` 全部 12375 个 `.cs`；盲区: 折叠常量、原生侧、`.mihoyobin` 二进制语义，见 §2.4）。

### 2.4 边界诚实

反编译语料是**反编译器输出**——`--1347725427 ^ 0x50557993` 这类**折叠常量**不会以明文出现（同 `COMPONENT-WRITER-MINE.md:50-53`）。
所以"语料里 0 处 dict 字段"**只对"反编译文本可达的声明"成立**。真正的 dict 物化可能在**原生侧**（`[entity+0x48]` 那类 map 容器——**注：`[entity+0x48]` 不是组件容器**，见 `reverse-eng-20261011/COMPONENT-CONTAINER-RECONCILED.md`；见 `COMPONENT-WRITER-MINE.md` §6）
或**二进制消息**里——本轮两者**均未读**。

---

## 3. 最接近"字典序列化"的东西：节点图 serverParamDictionary

### 3.1 两个候选文件

| 文件（`.runtime/editor-catalog/resolved/`） | 关键词命中 | 角色 |
|---|---|---|
| `NXXlkoibwEPCmEK7rwpH.cKP1Y2ibBlYiRhYw2PZ4.cs` | `infoServerParamDictionary is null`(`:891`)、`failed to serialize nodeConfig`(`:666`)、`failed to serialize subGraph`(`:725`)、`unhandle param type`(`:400`)、`invalid official kv param type`(`:1373`) | **节点配置**的序列化/反序列化 |
| `JxwbT6Ku2gFg1GkFYZ0U.oTqkY0KuSgsVkgfGANcX.cs` | `kvpair config is invalid`(`:741`)、`can't find GenericsServerParamDictionaryOptionalTypes tag`(`:510`) | **参数类型**的读取/装配 |

### 3.2 字典的"线形状"= (keyParamType, valueParamType) + kv 列表

`NXXlkoibwEPCmEK7rwpH.cKP1Y2ibBlYiRhYw2PZ4.cs` 里，一个参数条目的 struct 字段**明写 key/value 双类型**（`:42-50`）:

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

同文件里的参数条目类 `ewMPmIYviHdYFXRVpe2W`（`:124-134`）:

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

**这就是本轮所见"最像字典序列化"的形状**: 一个 dict 参数不是被当成一个不透明 blob 写，
而是被拆成 **`(keyParamType, valueParamType, [kv 对])`**——`keyParamType`/`valueParamType` 是 `uint`（或枚举 `cwrPI70C7gicn9EJ1xlo`），kv 列表由 `JxwbT6Ku2gFg1GkFYZ0U` 逐条装配
（`:671-687` 读 `keyParamType`/`valueParamType` 两字段再 `Bv9gbChSOucJd0D19WLH.xyVYfsr3qg0(...)` 组装）。

### 3.3 但这不是"引脚常量"

**关键区分**: 上面这套 **serverParamDictionary** 是**节点图 nodeConfig 的参数物化路径**（`failed to serialize nodeConfig`），
**不是**"往一个 `serverParamType==27` 的输入引脚写 `--slot` 常量"那条路（§1）。
桥侧对节点图的写入面是 `author.py graph set-value --slot ...`（`AuthoringGraph.cs:100`），而那条命令**只有 5 个标量槽 + list**（§1.1），
**没有任何 op 触达 `infoServerParamDictionary` / `kvpair`**。所以"看到了 dict 的节点配置形状"**不等于**"能写 dict 引脚常量"——
这正是 `CLAUDE.md` §六那条不对称纪律的同型。

---

## 4. 判决 + 下一步要挖的符号

### 4.1 判决

**一个 dict 常量今天不是 writable-by-shape。** 这不是"拼格式"的问题，是**缺原语**:
- 标量/列表写入面（`AuthorWriteScalar` / `AuthorWriteList`）**按名字拒绝**字典（§1.3）；
- 组件模型（也许是想绕道的容器）**没有容器字段**（§2）；
- 反编译语料里**没有**一个 dict 值类型的字段声明（§2.3）；
- 绑定档（`EditorBindingProfile.Generated.cs`）里**没有一个 setter 吃字典**——所有 `Dictionary` 成员都是 `BindingKind.Field`
  且挂在别的类型上（`:661,663,728,820,875,885`；其中 `:732` 唯一一个"集合 setter" 是 **list append** `KRQKKuygfFk`，首参是 list 存储类型，**不是 dict**）。

**所以"格式"不是待解项，"setter 存不存在"才是。**

### 4.2 下一个要挖的符号 / 类型（精确未知 = 交付物）

**主候选（首选，直接决定 const 路 (A) 通不通）**:
> 在 **pin-value 类型 `iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG`**（`AuthorWriteScalar` 反射调用 `scalar` 的那个对象）上，
> 找一个 **Method（不是 Field）**，其 **首参是 2-泛型 mangled 字典类型**（`Dictionary`2<...>` / `IDictionary<...>` / 那两个 2-泛型 mangled 名），
> 且返回 `void`、第二参是 wrapper `G97bO4XQy2ksgGIyrs78.nyfSUyXQKP5VT33Lnsry`——即 `KRQKKuygfFk`（list append）的**字典对偶**。
> 若有 ⇒ dict 变成 writable-by-shape（补一个 `dict` 分支即可）；若无 ⇒ const 路 (A) **在 7.1 反编译面上封死**，坐实。
> 检索位置: `EditorBindingProfile.Generated.cs` 全表 + 7.1 元数据 `metadata-7.1.json`（`EntityComponentProbe.cs:15-16` 引用的那版 SHA/MVID）。

**次候选（若 const 路封死，改走图构造路 (B)）**:
> 节点图的 **serverParamDictionary 写入原语**: 符号 `NXXlkoibwEPCmEK7rwpH.cKP1Y2ibBlYiRhYw2PZ4`
> 与其参数类型枚举 `cwrPI70C7gicn9EJ1xlo`（键/值类型 `keyParamType`/`valueParamType`），
> 以及字符串 `infoServerParamDictionary` / `kvpair config is invalid` / `GenericsServerParamDictionaryOptionalTypes tag` 的**写者**。
> 目标: 找到"把一个 dict 参数物化进 nodeConfig"的调用点，看它是否能由 `build-plan` 的 values 面触达。
> （注意: `DICT-CONSTRUCT-SEARCH.md` 已证构造器 **1088 建立字典 / 1788 拼装字典** 存在，输出声明为 **Generics(10000)**；
> 走图构造 + 连线进 704 的 `3:4` 是 (B) 路，**generic→concrete(27) 的物化未上机**——见 `DICT-WRITE-PROBE.md` §5 的定案实验。）

**明确的"不要去找"**: 别再猜一个 `AddDict*` / `SetDict*` 的**桥 op 名**——桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里 `ui/property/item/shop/currency/terrain` 全 0 命中（`CLAUDE.md:76-77`），写字典常量**没有现成 op**。

---

## 附录 A: 复现命令（全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 附录 B: 三层标注

| 层 | 内容 |
|---|---|
| **文档/资源写了什么** | `data/node-contracts/...` 记 704 `3:4` 是 `serverParamType 27`/`valueTypeValueRaw 10003`；`value-type-codes.json` 把 10003 命名为"字典"（18 条 pin）；`paramtypes.py` 把 27 命名为 `dict` |
| **工具能做什么** | 桥的写入面**只有** `{int,uint→enum,enum,bool,float,string,list<scalar>}`（`AuthorWriteScalar`/`AuthorWriteList`）；dict 在任何路径下**按名字拒绝**。绑定档**无 dict setter**。本文**全部是静态/只读结论** |
| **真机验证过什么** | **无**。本轮**未连桥、未发报文、未编译、未注入、未触碰游戏/编辑器、未写存档**。凡"generic→concrete(27) 物化""原生 map 容器""折叠常量"等，**均未上机**，标未知 |

---

## 附录 C: 证据索引

| 论断 | 出处 |
|---|---|
| 槽位声明 `{auto,int,uint,enum,float,bool,string}` | `tools/editor-bridge/Adapter/AuthoringGraph.cs:41` |
| `AuthorWriteScalar` 5 标量分支 + default 拒绝 | 同上 `:901-972`（`:969-970`） |
| `AuthorAutoSlot` 只映 2/6、Generics→未物化、其余按名拒 | 同上 `:879-888` |
| LIVE-CONFIRM-A/B/C/D 原文 | 同上 `:864-872 / :874-878 / :890-900 / :999-1001` |
| list 元素层点名拒 entity/vector/**dict** | 同上 `:76-80` |
| `ValidateAuthorScalar` 的 tag 集 + 未知 tag 码 | 同上 `:45-87` |
| `AuthorWriteList` 首行 list 码校验 | 同上 `:1004-1022`（`:1010`） |
| M5 目标引脚 `704 3:4` = 27/10003 | `data/node-contracts/variants/server/*.json`（defId 704 端口记录） |
| 27→`DICT`；`SLOT_FOR_TYPE[27]=None` | `tools/gameplan/paramtypes.py:30,76` |
| 10003↔"字典"、18 条 pin、pin 名样本 | `data/node-contracts/shared/value-type-codes.json` |
| 组件模型四字段（uint/bool/double×2），无容器 | `.runtime/editor-catalog/resolved/taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:12-35` |
| 组件模型 7.1 名 + 事件探针契约 | `tools/editor-bridge/Adapter/EntityComponentProbe.cs:24-32,82-87,116-122` |
| 组件线消息 oneof，无容器字段 | `.runtime/editor-catalog/resolved/StN9Qe4wQy9Io9byCM2h.LjBE4Q4wWZw6x2ypkNoY.cs:28-34` |
| 绑定档无 dict setter（Dictionary 全是 Field） | `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs:661,663,728,820,875,885`（list append `:732`） |
| serverParamDictionary `(keyParamType,valueParamType)` | `.runtime/editor-catalog/resolved/NXXlkoibwEPCmEK7rwpH.cKP1Y2ibBlYiRhYw2PZ4.cs:48-50,124-134,666,891` |
| kvpair / GenericsServerParamDictionaryOptionalTypes | `.runtime/editor-catalog/resolved/JxwbT6Ku2gFg1GkFYZ0U.oTqkY0KuSgsVkgfGANcX.cs:510,741` |
| 构造器 1088/1788（Generic 输出） | `DICT-CONSTRUCT-SEARCH.md` §3；`.runtime/editor-catalog/decoded/Beyond__Node__17565864354288959679.mihoyobin.json`（1088）、`.../6904706201337544219.mihoyobin.json`（1788） |

---

*本文件由 2026-10-10 会话从仓内 C# 源码、`data/node-contracts`、`tools/gameplan` 与 `.runtime/editor-catalog/resolved/`（Bash `grep -rI`，非 Grep 工具）
只读整理；**未实现、未运行、未连接桥、未触碰游戏/编辑器、未编译/未注入、未写任何存档**。所有引用行号为本次 checkout / 本次 resolved 语料实测。
凡"N 命中 0"的均写明**检索范围**；凡"有实现没跑过 / 未上机"的已标未知，不外推为"能玩/能写"。*
