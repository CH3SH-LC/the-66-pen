> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 字典常量 — contract type 27 可写性探针 (DICT-WRITE-PROBE)

日期: 2026-10-10
范围: 只读离线逆向。不连 bridge，不发图请求，不启游戏/编辑器，未写任何存档。
status: 结论 + 一条未做的实验（见 §5）

---

## 0. 结论先行 (verdict)

CLAUDE.md 的原话是:

> no node in the 500-definition server store CONSTRUCTS a dictionary,
> and paramtypes maps DICT to None, so shop 出售货币字典 (a type-27 pin) cannot be written.

**这句话的第一个分句被证伪。** 500 条 server 定义里确实存在**构造字典的节点**:

| defId | name | 输出 | 存储类型 |
|---|---|---|---|
| **1088** | **建立字典** | `字典` | Generics (10000) |
| **1788** | **拼装字典** | `字典` | Generics (10000) |
| 948 | 对字典设置或新增键值对 | (exec out, 原地改) | Generics (10000) |

client 侧镜像同样存在: 200153 / 200229 建立字典, 200152 / 200228 拼装字典。

第二个分句（`SLOT_FOR_TYPE[27] is None`）**成立**：确实不能把字典写成 **pin 常量**。

两个分句要分开判，因为"写一个字典"有两种含义:

| 含义 | 判决 | 依据 |
|---|---|---|
| (A) 把字典当成**常量字面量**写进某个 pin | **不能** | `paramtypes.SLOT_FOR_TYPE[27]=None`；`AuthorWriteScalar` 没有 dict 分支 (§2) |
| (B) 在**图里构造**一个字典值，再连线喂给 type-27 的 pin（如 704 的 `出售货币字典`） | **能** (节点存在，且 generic→concrete 的连线已被本工程真机确认接受 §1/§4) | 1088 / 1788；`AuthoringGraph.cs:426-434` |

**最终判决: 能 — 但走 (B) 路径（图内构造 + 连线），不走 (A) 路径（常量）。** CLAUDE.md 用来封死 (B) 的那条理由（"无构造节点"）是错的。
剩下的唯一未知是: **generic 字典输出喂进 concrete(27) 输入后，原生编辑器是否把它物化成真正的"字典"而不是任何类型** —— 一次实验即可定案（§5）。

---

## 1. 证据一: type-27 输出全清单（确认"无 type-27 构造器"，但推翻"无构造器"）

对 `data/node-contracts/variants/server/*.json`（8 桶 500 条定义）按 `ports[].serverParamType == 27`、
方向 = output 过滤。**共 8 条**（`valueTypeValueRaw` 一律 = 10003）:

| defId | name | 输出 pin 名 | 说明 |
|---|---|---|---|
| 717 | 查询自定义商店商品出售信息 | 出售货币字典 (out 1) | **读** |
| 718 | 查询背包商店商品出售信息 | 出售货币字典 (out 0) | **读** |
| 719 | 查询商店物品收购信息 | 收购货币字典 (out 0) | **读** |
| 721 | 获取背包所有基础道具 | 基础道具字典 (out 0) | **读** |
| 722 | 获取背包所有货币 | 货币字典 (out 0) | **读** |
| 730 | 获取掉落物组件所有道具 | 道具字典 (out 0) | **读** |
| 731 | 获取掉落物组件所有货币 | 货币字典 (out 0) | **读** |
| 705 | 商店收购道具时 | 收购物品字典 (out 4) | **事件**（运行时回执） |

(注: `tools/gameplan/modules/shop.py:35-36` 只列了 717/718/719/721/722/730/731 七条，漏了 705 —— 705 是事件节点，不是构造器，所以不影响它的结论。)

**这 8 条的共性: 全部是"向运行时状态/事件要一个字典"，没有一条是从输入构造字典。** 所以
"type-27 **输出**里没有构造器" 是对的 —— 但这是同义反复，因为构造器根本不带 type-27 输出。

**真正的构造器把输出声明成 Generics (10000)，不是 27:**


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`serverParamType` 全分布（output，500 定义）里 27 只有 8 次，10000 不作为 serverParamType 出现
（generic 的 `serverParamType == 0`，`valueTypeValueRaw == 10000`）。也就是说**字典的"类型"在契约层
是 Generics(10000)，只有在被物化到具体槽位时才显示为 27/10003。**

补充（同族只读节点，说明字典工具箱是完整的，佐证"构造器存在"不是孤例）:
1158 以键查询字典值、1298 以键对字典移除键值对、1368 查询字典是否包含特定键、
1438 查询字典是否包含特定值、1508 获取字典中键组成的列表、1578 获取字典中值组成的列表、
1648 查询字典长度、1718 清空字典、1928 对字典按键排序、1938 对字典按值排序。
全部 `categoryVariant = [10001,20000,22000,0]`、`graphKindRaw = 20000` —— **与商店节点同一个
作者类别**，因此 1088/1788 与 704/708/709 可以在同一张图里被摆放。

> 误导来源已定位: `tools/gameplan/tests/test_shop_query.py:164-180` 与 `shop.py:34-36` 只断言
> **type-27 输出全是读**，从未搜索过 generic 输出的构造器。断言本身没错，是**由它推出的
> "没有构造节点"过度概括了**（与 memory「搜不到不能推出不存在」同型）。

---

## 2. 证据二: AuthoringGraph.cs `AuthorWriteScalar` 支持的槽位 + 按名字拒绝的存储种类

文件: `tools/editor-bridge/Adapter/AuthoringGraph.cs`

### 2.1 支持的槽位（枚举）

- 声明数组 `AuthorValueSlots`（:41）: `{"auto","int","uint","enum","float","bool","string"}`。
- `ValidateAuthorScalar`（:45-84）接受的字面量 tagged key: `int` / `uint` / `bool` / `float` / `string` / `list`（:52-72）。
- `AuthorWriteScalar` 的 switch 分支（:901-972）只有 5 个 scalar 槽:
  `int`(:907) / `enum`(:919) / `bool`(:931) / `float`(:943) / `string`(:957)。
  另有 `list` 走 `AuthorWriteList`（:1004-1022），不经 `AuthorWriteScalar`。
- `AuthorWriteScalar` 各分支的 setter/getter 对（注释 :890-895）:
  int `c84KKE8ihrN`/`ilqKKrw7dhN`，string `MfLKK0bLIju`/`ur7KK2NiYZ4`，
  float `SH7KKvk8cxe`/`ngMKKCVBuMA`，enum `X8oKKHB87Ue`/`cPOKKedklwd`，
  bool `CHHKK434xan`/`RJCKKnWqvLO`。

### 2.2 按名字拒绝的存储种类（LIVE-CONFIRM 注释原文）

- **LIVE-CONFIRM-A（:864-872）**: `AuthorStorageKind` 只给三个码赋义 ——
  `2`(integer)、`6`(enum)、`10000`(Generics)。"No other code is interpreted anywhere in this patch."
- **LIVE-CONFIRM-B（:874-878）**: `AuthorAutoSlot`（:879-888）里 `auto` 只映射 `2 when int`、
  `6 when uint`；`10000`（Generics）→ 抛 **`AUTHOR_VALUE_NOT_MATERIALIZED`**（:885）；
  **其它所有码（含契约里给 float/string 的 4 和 5）一律按名字拒绝** →
  抛 **`AUTHOR_VALUE_SLOT_UNPROVEN:<storage>:<payload>`**（:886）。
- **LIVE-CONFIRM-C（:890-900）**: bool/enum 共享同一声明类型元组 `(4,4,1)` 却落在两个存储槽，
  read-back 强制校验，写错槽会很响地失败。
- **LIVE-CONFIRM-D（:999-1001）**: list 元素类型能否物化未知；`AuthorAutoSlot` 一律拒绝而非猜。
- `AuthorWriteScalar` 的 default（:969-970）: **`AUTHOR_VALUE_SLOT_UNSUPPORTED:<slot>`**。
- `AuthorWriteList`（:1004-1022）: 槽非 10002 时 → **`AUTHOR_VALUE_NOT_A_LIST:<storage>`**（:1010）。
- `ValidateAuthorScalar`（:77-80）直接点名: **"entity/vector/dict element types are NOT accepted,
  because no setter for them has an in-repo proof (see header note 3)"**（list 元素层）。

**结论: 一个 dict 形状的 pin（存储类型 27 / valueTypeValueRaw 10003）在任何路径下都会被
按名字拒绝** —— auto 路径抛 `AUTHOR_VALUE_SLOT_UNPROVEN:...`，显式 slot 路径抛
`AUTHOR_VALUE_SLOT_UNSUPPORTED:...`，list 元素路径抛 `AUTHOR_VALUE_LIST_ELEMENT_UNSUPPORTED`。
这印证了判决 (A)=不能（常量），但**它只描述"写常量"这一条路，不否决 (B) 连线之路**。

---

## 3. 证据三: binding profile 里没有 dict setter（签名不是 int/string/bool/uint/float 的候选）

文件: `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs`（249 个 `BindingContract`:
157 Field / 91 Method / 1 Property）。

先钉住 pin-value 类型: `iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG`
（`scalar`，`AuthorWriteScalar` 反射调用的那个对象）。它上面 **void 返回、双参 (值, wrapper) 的
setter 只有 5 个**（wrapper 恒为 `G97bO4XQy2ksgGIyrs78.nyfSUyXQKP5VT33Lnsry`）:

| 首个参数类型 | 方法 | Generated.cs 行 | 友好名 | 对应槽 |
|---|---|---|---|---|
| System.Int32 | `DejX9ySn3dc` | 818 | `c84KKE8ihrN` | int |
| System.UInt32 | `N6WX98qouJ0` | 739 | `LhkKKbraAbs` | uint |
| System.UInt32 | `xOeX9KT0Hcj` | 799 | `X8oKKHB87Ue` | enum |
| System.Single | `QkpX9zVTwV4` | 764 | `SH7KKvk8cxe` | float |
| System.String | `WpAXkDFUJSg` | 745 | `MfLKK0bLIju` | string |
| System.Boolean | `lZiX93JfX9h` | 695 | `CHHKK434xan` | bool |

**唯一一个"非标量"的集合 setter**（这就是 dict 若有会最像它的那个）:

- `EditorBindingProfile.Generated.cs:732` —
  `(X7NDusXHZZJUhYx2Q1n7.bX3XUOXHOHPd0fXaebqA, G97bO4XQy2ksgGIyrs78.nyfSUyXQKP5VT33Lnsry):iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG`
  方法名 `Vo1XkeKXfjj`（= 友好的 `KRQKKuygfFk`，AuthoringGraph.cs:1016 的 list append）。
  首参 `X7NDusXHZZJUhYx2Q1n7.bX3XUOXHOHPd0fXaebqA` 是 **LIST 存储类型**（`rKlXHia7SDm` 即
  `Ov2K7oYGvHi`，:1012 的 list element-definition getter），**不是 dict**。

**全 profile 里所有 `Dictionary` / `SortedDictionary` 成员都是 `BindingKind.Field`，
且都挂在别的类型上，没有一个是 setter，也没有一个在 pin-value 类型上:**

- `Generated.cs:661` `VpuuVGLgPg1T2WVOOaB3.rxEh1kLgpmbIxPxJtEbY.mHNLglmulVB` : Field
  `Dictionary<int, QMk3w3LWa1H071tYYMsy.EMWIS2LW7gimYorCSAJZ>`
- `Generated.cs:663` `QMk3w3LWa1H071tYYMsy.EMWIS2LW7gimYorCSAJZ.yJFLgBq6IsW` : Field `Dictionary<UInt64, ...>`
- `Generated.cs:728` `zsVmV4Lr1OujoGgk8Hag...+...` : Field `SortedDictionary<UInt32, QIAhH6LrRHNMkwSC7dyP.KOFwq5LrEAL8MSTGASqK>`
- `Generated.cs:820` `mMgotSXLrd3uXenrH36d.v14VncXLVn61xcWY9dpL\`2.MZXXXPVwoVh` : Field `Dictionary<E8G31RXL9Y36fMxuecmj, iNG54HXLkGq7WpMA5obt>`
- `Generated.cs:875` `BnmymZjZgvCPSOrkVEV5.F3PSl8jZWffaudZ3tqmF.MB5jweb9iwa` : Field `Dictionary<UInt64, ...>`
- `Generated.cs:885` `zsVmV4Lr1OujoGgk8Hag...+...iR6pynCDO8i` : Field `SortedDictionary<UInt32, ...>`

（另有个别首参非标量的 void setter，如 `:655` 的 `(List\`1<System.UInt32>):Void`、
`:757` 的 `(System.UInt16, ...):Void`、`:746/:856` 的 `(...):Void`，以及
`:854` 的 `(System.Byte[]):...` —— **这些既不在 pin-value 类型上，首参也不是字典**，
所以都不构成 dict setter。）

**结论: binding profile 里没有任何一个 setter 接受字典。** dict 若有，首参会是一个
`Dictionary\`2<...>` / 那两个 2 泛型 mangled 类型；实测全部都是 Field，不是 Method。这与 §2 的
`AuthorWriteScalar` 缺口互相印证。

---

## 4. 证据四: generic→concrete 连线的真机确认（(B) 判决的地基）

`AuthoringGraph.cs:426-434` 的注释是 **真机确认** 的:

> 2026-10-06: a GENERIC end (declared typeId 0) is un-materialized. **The native Link
> accepts it and the editor resolves the type from the connected concrete end** -- this is
> the shape this file's own BuildAuthorCountGate local Link already builds
> (concrete (3,3) into generic (0,0) ...). Insisting on declared-type equality here refused
> an edge the editor itself builds. Concrete-to-concrete edges are still compared exactly.

对应代码（:432-434）只在**两端都非 0** 时比较类型:


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


即 **generic(0) 端不参与相等比较** —— generic 输出（1088 的 `字典`,TypeId=0）连到 concrete(27)
输入（704 `3:4`）时,这条检查被跳过，交给原生 Link 接受、由编辑器从 concrete 端反推类型。

本工程的规划器同款规则: `tools/gameplan/plan.py:278-290`
("A generic end is filled by the native editor from the concrete one, so only compare two
concrete ends.")、`tools/gameplan/contracts.py:40-43`（generic pin 跳过精确类型检查）。

已确认的**方向**: concrete→generic（int 标量，真机）。**尚未直接观测的方向**: generic 输出→
concrete(27) 输入 —— 逻辑上受同一 `TypeId!=0` 短路保护、且注释措辞是"a generic end"（任一
端），但**字典这一类具体物化未上过机**。这就是 §5 要一次性钉死的东西。

---

## 5. 若判"未知"，唯一能定案的实验（未执行，离线禁做）

**一句话: 在当前作者图里放一个 1088 建立字典，把它的 `字典` 数据输出连到 704 的 `出售货币字典`
(3:4)，读回看编辑器是否接受并是否把它物化成 27。**

精确步骤（用既有 bridge 动作，不新增代码）:

1. `author add-node` → defId **1088** 建立字典（同作者类别 `[10001,20000,22000,0]`）；
2. `author add-node` → defId **704** 设置自定义商店商品出售信息；
3. `author connect`：from = 1088 数据输出(`fromKind=4, fromPortIndex=0`)，to = 704 数据输入
   (`toKind=3, toPortIndex=4`)；
4. `author inspect` 读回: 判据 (a) 该边是否仍在图模型里（`LapKOOcuGY1` 是否返回 true）；
   判据 (b) `pin-slots` 读 704 `3:4` 的类型 —— **generic 是否已从 10000 物化成 27/10003**；
5. `author export` + `gil_container.read_level` 解码导出物，确认该边/类型落进字节。

**判读**:
- 编辑器接受且 704 `3:4` 物化为 27 ⇒ **判决 (B)=能，封顶**，"cannot write 出售货币字典" 整句作废。
- 接受但物化成其它类型 / 拒边 ⇒ 保留 `DictPinUnsupported`，但把拒绝理由从"无构造节点"改成
  "generic 字典无法物化到 concrete(27)"（措辞必须换，因为原措辞是错的）。

**不做的**: 不发这条请求、不实现任何 writer、不改 `shop.py`（本次只读）。

---

## 6. 对既有代码/文档的更正建议（本次不改）

1. `tools/gameplan/modules/shop.py:34-36` 与 `:157-176`（`DictPinUnsupported` 文案）:
   "no server node constructs a dict either"（:171-172）**是错的**，应删或改为上述 (A)/(B) 二分。
2. `tools/gameplan/modules/inventory.py:140-141`（"本工程尚无经证明的'取字典元素'节点"）:
   **1158 以键查询字典值 就在 500 条 store 里**；措辞应改为"尚无**经真机证明**的取字典元素节点"，
   或直接补上 1158 的契约引用（它的两输入一输出都是 Generic）。
3. `CLAUDE.md` 中同句论断: 建议改为 "无 **type-27 输出的**构造器；字典构造器存在（1088/1788，
   Generic 输出），但能否物化进 concrete(27) pin 未上机"。

---

## 附录: 复现命令（只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


套件状态（未改代码，仅新增本文档）: 169 tests OK

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

