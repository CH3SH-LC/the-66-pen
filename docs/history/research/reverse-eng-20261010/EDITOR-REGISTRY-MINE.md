> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 编辑器注册表：节点之外还有什么可读（EDITOR-REGISTRY-MINE）

日期：2026-10-10。**全程只读**：未连桥、未发原生/图请求、未启动或触碰游戏/编辑器，
未触碰 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` 下任何文件。
本次证据来源＝仓内**已反编译静态语料**（`.runtime/editor-catalog/resolved/`，12375 个 `.cs`）
＋**工程自己的读取器代码**（`tools/editor-bridge/Adapter/`、`tools/live-editor-observer/`、
`tools/tag-readback/`）＋两份既有结论文件。**没有一次真机执行。**

> 口径纪律：本文把三层分开写 ——「**文档/静态写了什么**」 vs 「**工具能读/能写**」 vs
> 「**真机验证过**」。注册表里的 Kind 编号**没有任何一处是猜的**：每个编号都对应一个
> 具体模型的 override 返回点，行号在表里。

---

## 0. 结论摘要（先给答案）

1. **Kind 的来源只有一个**：每个资源模型类 override `RG6YRkRQud0()`，返回枚举
   `jEloOliwSIY7VK1XV9gX.QD5e7QiwC7ij9WZWqtx3` 的一个常量。编号**不在枚举里**（枚举只剩
   `None`），只能从每个模型的 `return (QD5e7QiwC7ij9WZWqtx3)N;` 逐个读出来。
2. **工程代码今天只认两个 Kind：6 和 9**。唯一的 Kind 赋值点在
   `Adapter/EditorAdapter.cs:166`（`resourceKind = … ? 6 : 9`）；唯一的白名单在
   `tools/live-editor-observer/ResourceModel.cs:46-50`（**恰好两条**，且有自测断言
   `SelfTest.cs:203` 钉死「exactly-two-types」）。**Adaper 里全部 `.Kind==N` 只出现 6 和 9**
   （17 个文件，完整清单见 §2）。
3. **静态语料里至少存在 25 个 Kind**（编号 1、5–27），25 个不同模型类各自 override 返回。
   编号 2、3、4 **从未见到任何模型返回它**，只在比较/构造里出现（见 §5 UNKNOWN）。
4. **问题三的直接回答**：
   - **没有**发现任何 Kind 表示「界面/UI 控件资源」。25 个编号里没有 UI 标签、没有控件模板。
   - **组件模板**：预制 Kind＝**7**（元件/预制）；但**真正的「组件」模型
     `LudM06iCRNk4iFkwqKIW` 不是注册表资源**（不 override Kind，是挂在实体/预制/关卡上的字段，
     见 §6）。
   - **玩家档案**：**不是 Kind**。它是存档容器 `.gip` 的一个 subtype
     （`tools/beyond-save/gil_container.py:26,46` `subtype 1 = player profile`），是**另一层**。
   - ui.hud 的「读半边」，在当前逆向水平下**没有**一个注册表 Kind 能对上。

---

## 1. Kind 是怎么来的（机制）

- 资源注册表类：`ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre`（真名；
  `tools/tag-readback/Program.cs:35`、`tools/live-editor-observer/ResourceRegistry.cs:229`）。
- 遍历根字段 `bwbixDw3yob`，子字典 `pIxYiE5REC8`，叶子 `JkmYibSuDZr[id]`
  （`ResourceRegistry.cs:231-235`，来源 `registry-annotated.cs:1589/393/397/514-521/720-733`）。
- 每个模型类实现接口 `l0eaxcKshZAU0GXoJ3Nx`（＝编辑器内部 `IResourceItem`），抽象基类
  `vNUv3diU6lqfwyK68vMI.AQecZxiUFDr4Qp1mqL4Y`
  （`.runtime/editor-catalog/resolved/vNUv3diU6lqfwyK68vMI.AQecZxiUFDr4Qp1mqL4Y.cs:27`）。
- 抽象基类**没有**单点 Kind 表：`Ztp6och7pQfpiWWyqK7t…RG6YRkRQud0` 是虚分派，
  每个具体资源类型**各自 override 返回一个常量**。所以「Kind 全集」只能**收集全部 override**，
  不能从一个枚举读完。
- 枚举 `QD5e7QiwC7ij9WZWqtx3`
  （`.runtime/editor-catalog/resolved/jEloOliwSIY7VK1XV9gX.QD5e7QiwC7ij9WZWqtx3.cs`）
  **只有 `None` 一个成员** —— 混淆器抹掉了成员名。**据数字编官方类别名是禁止的**
  （既有结论同此：`.runtime/verification/export-context-identity/RESULT.md` 末段）。

### 1.1 别把「资源 Kind」和「引脚 Kind」混为一谈

`AuthoringGraph.cs` 里另有 `pin.Kind`（1/2/3/4）与 `fromKind/toKind`：
- `AuthoringGraph.cs:362,364,368`（`pin.Kind==3` 判标量；`OrderBy(p=>p.Kind)`）
- `AuthoringGraph.cs:398-400`（`fromKind!=2&&fromKind!=4` / `toKind!=1&&toKind!=3`；
  `2→1=execution`、`4→3=data`）
- `tools/editor-bridge/verify-runtime-audit.py:31`（`PinSignature.Kind`，来自 `gia_graph.proto`）

这些是**节点图的引脚类型**，与注册表资源 Kind 是**两套命名空间**，数值重叠纯属巧合。
本文只谈资源 Kind。

---

## 2. 工程代码里「按 Kind 枚举资源」的全部位置

搜索范围：`tools/editor-bridge/Adapter/*.cs`、`tools/editor-bridge/ManagedBridge/*.cs`、
`tools/live-editor-observer/*.cs`、`tools/tag-readback/*.cs`、`tools/edge-*` 及
`tools/`/`scripts/` 下的 `.py`（Bash `grep -rn`，非 Grep 工具）。
**结论：资源 Kind 数值在工程代码里只出现 6 和 9。**

### 2.1 Kind 赋值点（唯一）

| 位置 | 作用 |
|---|---|
| `Adapter/EditorAdapter.cs:166` | `int resourceKind = name==Model6 ? 6 : 9;` —— **全工程唯一的 Kind 赋值** |
| `Adapter/EditorAdapter.cs:168` | `result.Add(new Resource(model, category, id, resourceKind));` —— **唯一构造 Resource 处** |
| `Adapter/EditorAdapter.cs:186` | 按 `r.Kind==6 ? 取字段A : 取字段B` 读名字（两种模型的 name 字段名不同） |
| `tools/live-editor-observer/ResourceModel.cs:46-50` | 堆读白名单：**恰好两条** `(type, 6, wrapper)`、`(type, 9, wrapper)` |
| `tools/live-editor-observer/SelfTest.cs:203-207` | 断言「白名单 exactly-two-types」且 modelType 分别为 6 / 9 |

### 2.2 消费点（读 Kind 的分支）——17 个文件，全部只判 6 / 9

`AuditGraph.cs:31,43,90,99`(9) `:50,71`(6) ·
`AuthoringGraph.cs:220`(9) `:322,412,468,492,502,540,632,743,979`(6) ·
`ClassicTeleportRepair.cs:15`(9) `:33,34`(6) ·
`EditorAdapter.cs:43,193,269,553,580,603,631,667,704,723,735,747,786,799,828,835,846,856,886,910,918`(9)
`+ :186,194,195,681,709,754,806`(6) ·
`FinishGraph.cs:39,51,134,152,172,177,187,227,290`(9) `:58,102`(6) ·
`FinishMinimalDiagnostic.cs:90`(9) `:112`(6) ·
`FinishNodeCatalog.cs:23`(6) · `FinishSettlementDiagnostic.cs:84`(9) `:101`(6) ·
`GameLoopGraph.cs`(9/6 各若干) · `GameNodeCatalog.cs:27,72,101`(6) ·
`GraphLogSelection.cs:58`(9) · `InterfaceVerification.cs:321`(9) ·
`OwnedGraphDelete.cs:105`(9) · `PositionGraph.cs`(9/6) · `ReopenContentEvidence.cs:167`(9) ·
`RetireRuntimeSpawns.cs:30,34,38`(9) · `SyncInspection.cs:27`(9)

> 一个纯读用点：`tools/cordis-plugin/build_node_contracts.py:139`
> 里**引用了**字符串 `serverNodeDefinitions=resources.Where(r=>r.Kind==6 && r.Category[1]==20000)`，
> 那只是把桥的语句抄进 node-contract 证据，不是新枚举点。
> 其它 `tools/*.cs`（`BridgeServer.cs`、`Live.cs`、`tag-readback/Program.cs`、
> `level-init-observer/Program.cs`）里的 `Kind==` 命中都是 `JsonValueKind`，不是资源 Kind。

### 2.3 Kind 与 Category 是两回事

同一个 Kind 下还有**四元 Category**（`EditorAdapter.cs:163` 读 4 个字段
`oLyiwZX255H/AwbiwrjxUDX/UFWiwJNegmh/RBTiwn649Hy`）。`Category[1]` 是子类目：
节点定义用 `{10001,20000,22000,0}`（`AuthoringGraph.cs:540` 等），可建图子类目
`AuthorGraphKinds={20000,20001,20002,20007}`（`AuthoringGraph.cs:17`）。
**不要把 `Category[1]==20000` 当成 Kind。**

---

## 3. Kind 台账（静态语料全量扫描）

来源：Bash `grep -rn "return (QD5e7QiwC7ij9WZWqtx3)" .runtime/editor-catalog/resolved/`。
每行 = 一个模型类的 override 返回点。

| Kind | 模型类（混淆名） | 证据 file:line | 判定 | 读？ | 写？ |
|---:|---|---|---|---|---|
| 1 | `eFwIefiyuoKqF5Xvj0lt.vZll0FiyKKPTI3JUkFjF` | …resolved/eFwIefiyuoKqF5Xvj0lt.vZll0FiyKKPTI3JUkFjF.cs:312 | **文件夹**（新建文件夹；自身 `IEnumerable<self>`；标签 `..._NEW_FOLDER`） | 否 | 否 |
| 5 | `aomjwdKbXpPlrC10ABGF.hdyYDbKbQQXSb23boi1e` | …/aomjwdKbXpPlrC10ABGF.hdyYDbKbQQXSb23boi1e.cs:716 | 引脚/泛型容器（字面量 `pin : can't get pin list`、`泛型未定义, graphId=`；`IEnumerable<bSsCJ1K5VKAgW0JtiDWd>`） | 否 | 否 |
| 6 | `IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C` | …/IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C.cs:1105 | **节点定义**（真机已证） | **是** | 否 |
| 7 | `nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp` | …/nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp.cs:256 | **预制/元件** | 是* | 否 |
| 8 | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr` | …/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:242 | **关卡实体实例** | 是* | 删**是**/建否 |
| 9 | `cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH` | …/cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH.cs:434 | **节点图**（真机已证） | **是** | **建+删** |
| 10 | `KddsJBie8lIPpTCXKxPZ.diq0onieMTpG0MB8aw98` | …/KddsJBie8lIPpTCXKxPZ.diq0onieMTpG0MB8aw98.cs:165 | **筛选-文件夹**（标签 `..._FILTER_FOLDER`；基类 `ToKAUIieY8lHJ0JEXS9n`，非 AQec 系） | 否 | 否 |
| 11 | `MmGS7KiCtuJtGKBgib1k.KRXnqSiC20Pj6d7V6Cdv` | …/MmGS7KiCtuJtGKBgib1k.KRXnqSiC20Pj6d7V6Cdv.cs:314 | **costload 基类**（标签 `..._COSTLOAD_DETAILS_TYPE_EFFECT`、`..._COSTLOAD_TLDETAILS_ENTITY`；多个号的父类） | 否 | 否 |
| 12 | `BDjblLiSCbMaE8BSBvLR.vB8dgNiSG9x1GKQc8Hb8` | …/BDjblLiSCbMaE8BSBvLR.vB8dgNiSG9x1GKQc8Hb8.cs:63 | 未知（继承 11；成员含 `time`、`"#0.00"`） | 否 | 否 |
| 13 | `ftmDB1i2aiMRKAtNWckr.IlPKHZi25xZ0J6OxCaRM` | …/ftmDB1i2aiMRKAtNWckr.IlPKHZi25xZ0J6OxCaRM.cs:163 | 未知（继承 11） | 否 | 否 |
| 14 | `POEL6HKAWCtpYUVxs1RL.LppcPfKAgGBUlYusKLtc` | …/POEL6HKAWCtpYUVxs1RL.LppcPfKAgGBUlYusKLtc.cs:179 | **蓝图变量**（标签 `UI_BEYOND_ASSIST_EDITOR_BP_VARIABLES`；成员 `key/value/serverParamType/structId`） | 否 | 否 |
| 15 | `j6TdHcKsbueiEjwxIuIh.XyJDNjKsOwEHhOe9s362` | …/j6TdHcKsbueiEjwxIuIh.XyJDNjKsOwEHhOe9s362.cs:174 | **外部资产**（标签 `..._EXTERNAL_ASSETS_BP/NODE/PACKAGE`） | 否 | 否 |
| 16 | `rGmbDUi2VxIyinwEpo8b.uf9RHui2cZlJtbAA8Ae3` | …/rGmbDUi2VxIyinwEpo8b.uf9RHui2cZlJtbAA8Ae3.cs:23 | **自定义角色状态**（标签 `..._DEFAULT_CUSTOM_ROLESTATUS`） | 否 | 否 |
| 17 | `RKx6ROi2DDOn2ehT0qgM.tGDNlCi2dUZRmkrMoRQq` | …/RKx6ROi2DDOn2ehT0qgM.tGDNlCi2dUZRmkrMoRQq.cs:26 | 未知（继承 11；成员 `int`） | 否 | 否 |
| 18 | `RXxUHgiBjTmjHS8TiysI.vbNNKuiBN7oZOVdq3c7S` | …/RXxUHgiBjTmjHS8TiysI.vbNNKuiBN7oZOVdq3c7S.cs:19 | 未知（继承 `aEfqOeiBlk6ufuiPo4km`） | 否 | 否 |
| 19 | `lVcfFtiBfwPNudRJmmMP.aXcC8HiB6QIDJDE32Pk4` | …/lVcfFtiBfwPNudRJmmMP.aXcC8HiB6QIDJDE32Pk4.cs:19 | 未知（继承 `aEfqOeiBlk6ufuiPo4km`） | 否 | 否 |
| 20 | `G7uylNiBSKbWmMjDgB9R.XhyS8QiBC1CuQdHqsk9a` | …/G7uylNiBSKbWmMjDgB9R.XhyS8QiBC1CuQdHqsk9a.cs:19 | 未知（继承 `EsbhgBiBcQFLbmPVnaaK`） | 否 | 否 |
| 21 | `outFvhiBBayfJig7phb3.SxPJxbiBt2Rj8khsI9uk` | …/outFvhiBBayfJig7phb3.SxPJxbiBt2Rj8khsI9uk.cs:19 | 未知（继承 `EsbhgBiBcQFLbmPVnaaK`） | 否 | 否 |
| 22 | `VwW411i21ZR9a5lWgtKb.EfFhlQi28rLc3VsDLxZ1` | …/VwW411i21ZR9a5lWgtKb.EfFhlQi28rLc3VsDLxZ1.cs:52 | 未知（继承 11；成员 `bool`） | 否 | 否 |
| 23 | `nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA` | …/nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA.cs:17 | **标签(Tag)**（真机读取器用的就是它） | **是** | 否 |
| 24 | `YUkM03i26jjC6kW4kfcD.PedQEwi2FXjUjvFJ3NAF` | …/YUkM03i26jjC6kW4kfcD.PedQEwi2FXjUjvFJ3NAF.cs:17 | 未知（继承 11；成员 `string`） | 否 | 否 |
| 25 | `buQlvBi2r6q0Agl3eHbm.DYRfB7i2Z6e5yVssSnCK` | …/buQlvBi2r6q0Agl3eHbm.DYRfB7i2Z6e5yVssSnCK.cs:28 | 未知（继承 11） | 否 | 否 |
| 26 | `hK5F9Ci22MCPb13k0x0d.H8HkVpi2SIQ8VKKqVPW8` | …/hK5F9Ci22MCPb13k0x0d.H8HkVpi2SIQ8VKKqVPW8.cs:34 | 未知（继承 25） | 否 | 否 |
| 27 | `YyrfAlit5qPFpmIDPNl3.JG0X37i2zxAH0lwVgBoG` | …/YyrfAlit5qPFpmIDPNl3.JG0X37i2zxAH0lwVgBoG.cs:17 | 未知（继承 11） | 否 | 否 |

\* 「读是」但**不在 Kind 台账里**：请见 §4 —— 7 与 8 的模型**能按类型名读到**，
但**工程没有给它们赋 Kind**（`EditorAdapter.cs:144-158` 走的是「按类型名分支」而非 Kind 分支）。
表里打 * 表示「模型可读、Kind 号未被工程使用」。

**核对**：编号 **2、3、4 未出现在任何 `return (QD5e7QiwC7ij9WZWqtx3)N;` 里**
（Bash `grep -rn "return (QD5e7QiwC7ij9WZWqtx3)[234];" …resolved/` = 0 命中）。
它们在**比较/构造**里出现过，见 §5。

### 3.1 Kind → 读取器对照（读半的覆盖面）

| Kind | 工程里有读取器吗 | 证据 |
|---:|---|---|
| 6 | **有** | `EditorAdapter.cs:194`（`serverNodeDefinitions`）、`:681/709/754/806`；`AuthoringGraph.cs:322` 等 |
| 7 | 有（**按类型名**，未赋 Kind） | `EditorAdapter.cs:152-158`（`prefabModels`/`prefabCandidates`，`nWLQffit…hRwGGsitgmhQZo9c1XOp`）；`PrefabFieldRead.cs` |
| 8 | 有（**按类型名**，未赋 Kind） | `EditorAdapter.cs:144-151`（`entityModels`，`Uf6Gwki…AooSwxiSm6Ktx99ovmnr`）；`EntityCrudProbe.cs:14` |
| 9 | **有** | `EditorAdapter.cs:43/193`；`live-editor-observer/ResourceModel.cs:49`；`AuditGraph.cs:31` 等 |
| 23 | 有（堆读，独立工具） | `tag-readback/Program.cs:9`（`TagType`）、`live-editor-observer/TagScan.cs:294` |
| 1,5,10–22,24–27 | **无**（工程没有任何代码按这些编号或类型名取模型） | 上表 25 个编号中除 6/7/8/9/23 外全部 |

> 注：**6/9 是唯一两条被「Kind 分支」覆盖的**。7 与 8 走的是**类型名字符串**分支，
> 所以严格说「工程按 Kind 枚举资源」只覆盖 6 与 9；实体/预制是**旁路读取**。

### 3.2 Kind → 写入器对照（写半）

| Kind | 写能力 | 证据 |
|---:|---|---|
| 9 图 | **建 + 删** | 建：`AuthoringGraph.cs:231` `create.Invoke(manager,…)`（需过 `:117` 的 `AuthorGraphKinds` 校验）；删：`OwnedGraphDelete.cs:105`（只删 Kind-9，`:98` 用模型自身 delete 方法） |
| 8 实体 | **删**（编辑器侧）；**建走原生侧** | 删：`OwnedEntityDelete.cs:138` `GetMethod(deleteName).Invoke(resource)`（deleteName＝`B("zgVKB6OS1MZ")`，`resource` 是实体模型）；建：不走编辑器注册表，走 `tools/game-executor/scene_cli.py`（写**游戏进程/存档**） |
| 6 节点定义 | **无** | 定义由服务端下发；桥只**读**它来搭图，不创建/删除定义资源 |
| 7 预制 | 无 | — |
| 23 标签 | 无（见 §6 的辨析） | — |
| 其余 | 无 | — |

> `AuthorEntityTag.cs` 里的 `set` 用的是**另一条出站 tag 命令**
> （`TagDefinitionType71 = Jt1m77XtPYMbFDIUFpJy.jDg3YOXtpW5eRF0HnQkO`，`:13-16`），
> 与注册表 tag 模型 `nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA`（Kind 23）**不是同一个符号**。
> 是不是同一种「标签」，**本次未证**，不并入本表。

---

## 4. 旁路：能读到但没进 Kind 台账的模型

`EditorAdapter.ResourcesCore`（`EditorAdapter.cs:137-174`）在遍历时**认得 4 种模型类型**，
但只有 2 种被赋 Kind：

| 模型类型 | 收集到 | 赋 Kind？ | file:line |
|---|---|---|---|
| `IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C` | `Resource` 列表 | 是（6） | `EditorAdapter.cs:160,166` |
| `cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH` | `Resource` 列表 | 是（9） | 同上 |
| `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr` | `entityModels` / `entities` | **否** | `EditorAdapter.cs:144-151` |
| `nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp` | `prefabModels` / `prefabCandidates` | **否** | `EditorAdapter.cs:152-158` |

其余类型的模型名只进 `modelTypeCounts`（`:143` 按 FullName 计数）——这是**普查**而非 Kind 台账。
`modelTypeCounts` 在真机回执里出现过（`PROGRESS.md:11270` 讨论「21 = 7 张图 × 3」的重复计数），
但**没有任何回执把它的键值对完整落盘**，所以「真机注册表里到底有哪些模型类型」这一问
**本次没有真机数据**（`.runtime` 下 `grep modelTypeCounts` 只见 `PROGRESS.md` 与 `EditorAdapter.cs` 两处）。

---

## 5. UNKNOWN 表（不猜）

| 编号/符号 | 见到它的位置 | 见到了什么 | 为什么不判 |
|---|---|---|---|
| **2** | `ad29AUubIcBRGWfDQ31A.b3byWjubk3T2cm4JmgGt.cs:615`、`kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0.cs:1824`、`oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7.cs:737,2015,2105`、`z6bJHqKCG1FwPiBJfDLJ.M2bF6wKCnSaAHlvJtY0X.cs:1045` | 只在 `== / !=` **比较**与 `new Ve95LLiw2unLOvPx3Tqi((QD5e7QiwC7ij9WZWqtx3)2, 0u)` **构造**里 | **没有任何模型类的 override 返回 2**；据数字编类型＝猜 |
| **3** | 本仓 `.cs` 未见 | — | 同上 |
| **4** | 本仓 `.cs` 未见 | — | 同上 |
| Kind 12/13/17 | §3 表内对应 file:line | 仅知继承 11、有成员 (`time`/`"#0.00"`/`int`) | 字段名全部混淆，无 UI 标签、无方法名字面量；**不足以判定业务含义** |
| Kind 18/19/20/21 | §3 表内对应 file:line | 仅知继承 `aEfqOeiBlk6ufuiPo4km` / `EsbhgBiBcQFLbmPVnaaK` | 同上 |
| Kind 22/24/25/26/27 | §3 表内对应 file:line | 仅知继承 11、个别有 `string`/`bool`/`uint` 成员 | 同上 |
| `LudM06iCRNk4iFkwqKIW`（组件模型） | 定义 `taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:10` | 类声明 `: UsJT4KiCnJHM1HfZqK59`，**不 override `RG6YRkRQud0`** | 它是字段/成员模型，不是注册表资源 Kind（见 §6） |

---

## 6. 问题三：UI / 组件模板 / 玩家档案

### 6.1 UI / 界面控件资源 —— **没有 Kind**

- 25 个编号里，`resourceItemTextType` 是**界面标签**（`UI_BEYOND_ASSIST_EDITOR_*`）的只有
  编号 1（NEW_FOLDER）、10（FILTER_FOLDER）、11（COSTLOAD_*）、14（BP_VARIABLES）、
  15（EXTERNAL_ASSETS_*）、16（CUSTOM_ROLESTATUS）——**全是「文件夹/变量/外部资产/角色状态」，
  没有一个是「界面控件/布局/HUD」。**
- Bash 在 `…resolved/`（12375 个 `.cs`）里搜 `界面`、`控件组`、`HUD`、`UI_BEYOND_ASSIST_EDITOR_HUD`
  均无「控件资源模型」命中（`界面`/`控件组` 0 命中；`HUD` 仅出现在一个委托名 `hXLoMRxgtHUDvEwEjwSn.cs:3` 里）。
- 编外证据：编辑器的**界面资源清单**是构建期生成的一段字符串表（
  `docs/research/beyondeditor-frontend/01-前端架构与程序集.md:152`：4098 条 = `Resource/` 文件数），
  其中 UI 图标等在 `Icon/` 与加密的 `assets.bin`（230MB，ZIP 加密成员，
  `docs/offline-research/RESOURCE-MAP.md:11`）——**那是文件系统层，不是注册表 Kind**。

⇒ **ui.hud 的「读半边」在当前逆向水平下不存在一个「UI 资源 Kind」可对接。**
（此为本检索范围内的负面结论，范围＝上述文件与目录；**不代表官方内部没有**。）

### 6.2 组件模板 —— 预制是 Kind 7，**「组件」本身不是资源**

- **元件/预制模板** = Kind **7**（`nWLQffit…hRwGGsitgmhQZo9c1XOp`，§3 表）。
- 但真正的「**组件**」模型是 `LudM06iCRNk4iFkwqKIW`
  （`…resolved/taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:10`），
  被 `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr`（实体，Kind 8）、
  `nWLQffit…hRwGGsitgmhQZo9c1XOp`（预制，Kind 7）、`mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q`（编辑器管理器）
  等引用——它是**这些模型上的字段**，**不 override Kind**，**不在注册表里单独成项**。
- 与既有结论一致：组件「读得懂、删得掉、加不了」（`CLAUDE.md` §六(a)）。

### 6.3 玩家档案 —— **不是 Kind，是存档 subtype**

- `tools/beyond-save/gil_container.py:6,26,46`：`Beyond_Local_Save_Player.gip` 是
  **player profile**，容器 `subtype 1 = player profile`、`2 = level`；`:345` 注释
  「The player profile -- what the editor shows as the list of projects.」
- 即：**玩家档案 = `.gip` 存档容器的一层**，由 `gil_container.py` 解析，
  **与编辑器内存注册表的 Kind 体系无关**。
- Bash 在 `…resolved/` 里搜 `PlayerTemplate`/`玩家模板` = 0 命中；
  `player`（不分大小写）只命中若干编辑器管理器/命令宿主类，**没有 player-profile 资源模型**。
  （与既有记忆一致：出生点是**玩家模板上的字段**，不是注册表实体。）

---

## 7. 复现命令（全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 8. 边界与未做

- **没有连桥/发报文/真机执行**：本文是纯静态。任何「读/写」判定都是**读代码**得出的，
  不等于真机通了。
- **没跑真机注册表普查**：`modelTypeCounts` 的完整键值对**没有落盘**，
  所以「真机里实际存在哪几种模型类型」缺一手数据。
- **编号 2/3/4 与若干继承 11 的编号未识别**：字段名与方法名全部混淆，
  只能进 §5 UNKNOWN，**不从数字猜业务名**。
- 「**没有 UI Kind**」是**本检索范围内的精确负面**（范围＝`…resolved/` 12375 个 `.cs`
  与 §2.2 列出的工程 `.cs`）；按 doctrine，**「搜不到」不等于「不存在」**。
