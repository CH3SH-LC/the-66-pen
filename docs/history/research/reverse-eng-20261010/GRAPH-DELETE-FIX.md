> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# GRAPH-DELETE-FIX —— `delete-owned-graph-ids` 为什么一次都没成功，以及什么能修

> 纯分析。**没有改** `tools/editor-bridge/Adapter/OwnedGraphDelete.cs`，**没有向 bridge/native 发任何请求**，
> **没有起停 helper / 不申请 UAC**，**没有触碰游戏或编辑器**，
> **对 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` 全程只读**。
> 全部结论来自静态阅读仓内 C# 源码与符号绑定 profile，以及仓内既有结论文件。
> 引用的行号均为**本次 checkout 实测**。符号约定同 `GRAPH-DELETE-PROBE.md`：
> `B("旧11位混淆串")`（`EditorAdapter.cs:87`）由 profile 解析成当代构建的实际混淆名，下文两条都给。

兄弟文件：`docs/research/reverse-eng-20261010/GRAPH-DELETE-PROBE.md`（同为只读分析，本文据其证据推进并给判决）。

---

## 0. 结论（先给判决）

1. **匹配谓词是引用相等**，两端对象**不在同一个对象图里**：`Resources()` 侧是**注册表字典里的 Kind-9 图模型**，
   节点走行侧是**场景面板里经一个实体专用代理 accessor 解出的实体模型**。谓词恒 false → `modelMatched=0`。
   （`OwnedGraphDelete.cs:103-105` 建表，`:174` 判归属。）
2. **id 1094713345 = 关卡实体（`关卡实体`）**，一个 Kind-8 实体模型（`EditorAdapter.cs:636-637`、`AuthoringGraph.cs:252`）。
   走行之所以落到它，是**结构性的**：走行根被过滤到场景面板 VM，它只会交出**场景树里的 edit-object 资源节点**，
   而每个这样的节点的代理 accessor 按**契约**返回**实体模型**（`EditorBindingProfile.Generated.cs:878`），
   图根本不在场景树里（`ArchiveModel.cs:208-215` 明确排除 `Registry.root`）。
3. **两个查找确实可以统一**——它们**本来就是同一套机制**（都走 `Resources()` + `Kind==9`，
   `AuthoringGraph.cs:220` 只是多一个精确名相等）。把删除的身份解析**完全改走这个统一查找**，是对
   `modelMatched=0` 这个**症状**的正确修法，且**零新符号**。
   **但它不充分**：节点走行**不是**身份查找，它是**唯一的 delete 句柄来源**，而那来源被契约钉死为实体类型；
   注册表侧的对象**自身不带** delete 方法（`FinishGraph.cs:214-215` 实测）。所以统一之后，
   删除会**正确地解析出图**，然后**找不到删除原语**，必须以具名码 fail-closed，而不是删成功。
4. **最小只读实验**：现有的一次 dry-run 请求（`delete-owned-graph-ids-dry-run`）**已经内置**了判定所需的诊断
   （`OwnedGraphDelete.cs:195-207`），一个回执即可分开「匹配方式错」与「走行根错」。见 §4。

---

## 1. 精确的匹配谓词，以及那条走行（file:line）

### 1.1 谓词本体

`BuildOwnedGraphIndex` 先用**引用相等**建「模型对象 → id」表：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


在节点走行的每个候选上，**用引用相等**判归属——**这就是那个谓词**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`model` 的来源链（节点侧）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


即：**「节点侧代理解出来的 model」必须与「`Resources()` 交出的 Kind-9 模型」是同一个对象引用**。
其后还有两道闸：名前缀 `MW_`（`:179`）、重复即歧义（`:181-184`），最后 `index[id]=resource`（`:182`）。

源码注释把它当成既定事实（`OwnedGraphDelete.cs:101-102`：*"the walk and the node scan hand back
the same model objects, not copies"*）。四次实测（候选 48 / 499 / 31，全部 `modelMatched=0`，
见 `OwnedGraphDelete.cs:52-60`、`test_owned_graph_delete_contract.py:6-11`、
`PROGRESS-BY-FUNCTION.md:188`）说明该断言对图**不成立**。

### 1.2 那条走行（本体与根）

- 调用点：`OwnedGraphDelete.cs:128-129`
  `WalkEditorGraph(OwnedGraphDeleteScanNodes=200000, OwnedGraphDeleteScanDepth=14, true, OwnedDeleteWalkRootType)`；
  常量在 `:40-41`（200000 / 14）。
- 实现：`ArchiveModel.cs:193-299`。根 = `Application.Current` / `Application.Resources` /
  每个 `Window` + 其 `DataContext` + `Content` / `Producer`（`:196-215`）。
  **`Registry.root` 被刻意排除**（`:208-215`，注释明说 *"Registry.root is deliberately NOT a root here"*）。
- 根类型过滤：`rootType = OwnedDeleteWalkRootType`，`:217` 把根裁剪到该类型；值见
  `OwnedEntityDelete.cs:44` = `B("gyj3OSueTNTdJeQL0yyH.tyZNMjueXM5Cae1EUsbH")`
  → `vjAJAAQ5EnQrVCtWeP5c.GUTcsNQ5DwQLe225s2f4`（`EditorBindingProfile.Generated.cs:542`，
  即场景编辑面板 `Window.DataContext`，`FrontendCommands.cs:105-117`）。
- 走行把私有基类字段也算入（`includePrivateBaseFields=true`，`:218,260-263`），
  单层进 `ICollection`（`:271-296`）。

**结论**：这条走行从 WPF 应用/窗口/Producer 出发，走到的**不是**注册表，而是**场景面板的 DataContext 子树**。

### 1.3 计数器的形状自证同一件事

`resourceRead == accessorFound == hasDeleteMethod`、`modelMatched == 0`
（`OwnedGraphDelete.cs:114` 定义，`:188-190` 汇总）——正好对应：走行里每个带 `vQPKy8Qu9ev` 的节点都持有
**同一类**代理，该类代理**同时**声明了 resolve（`ndlKBRCbBjF`）与 delete（`zgVKB6OS1MZ`），
所以前三个计数逐个相等；而它解出的实体模型永远命中不了图的引用表，所以第四个恒 0。

---

## 2. id 1094713345 是什么，以及为什么图走行会落到它

### 2.1 这个 id 是什么

它在三处被当成**关卡实体**使用：

- `AuthoringGraph.cs:252`（`State()` 里判 `boundToLevel`）：
  `entityModels.Where(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))==1094713345u)`。
- `EditorAdapter.cs:636-637`（`BindOwnGraph` 的绑定目标）：
  同 id **且** `Stored(e,B("WAAiS5WkxlA"))=="关卡实体"`，否则 `LEVEL_ENTITY_NOT_FOUND`。
- `FinishGraph.cs:183,295`：`FINISH_LEVEL_ENTITY_REQUIRED` / `FINISH_UNBIND_LEVEL_ENTITY_NOT_FOUND`。

⇒ **1094713345 = 关卡实体（存名 `关卡实体`）**，是 `entityModels` 里一个 **Kind-8 实体模型**
（类型 `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr`，`EntityCrudProbe.cs:14`、
`EditorBindingProfile.Generated.cs:473`）。**它不是图**。

### 2.2 为什么"图走行"会落到它——机制（不是巧合）

1. **走行根是场景面板 VM**（§1.2）。该面板的 `DataContext` 子树里坐着**场景文件夹树**：
   逐个 edit object 的资源节点，节点类型 `oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7`
   （`OwnedEntityDelete.cs:43` `OwnedDeleteResourceNodeType`；
   `EditorBindingProfile.Generated.cs:573`）。
2. **每个这样的节点都带字段 `vQPKy8Qu9ev`**（→ `NJvjJkLWol0`，`:916` 声明在**节点**类型上），
   其值是**资源代理**（类型 `VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf`
   → `fYiNtsjNFLpjCdRQ3Cvj.snNdG3jNcHxXOpcU0fHG`，`:477`）。
3. **该代理的 resolve 按契约返回实体模型**：`ndlKBRCbBjF`→`ABijCETHXZy`，**全 profile 只声明一次**
   （`EditorBindingProfile.Generated.cs:878`），返回类型 `LhusWLXd5NUZ7IineV1x.o6MMsvXduEaZkjEZB6yx`
   = 实体模型类型（`:473`）。**它在类型系统层面就不可能交出图模型**（图模型类型是
   `E8xv5pXu77T6046o5sVM.vUK4LLXuq7BbA0L017eJ`，`:515`）。
4. **关卡实体是场景树里永远在场的一个 edit object**，所以它的 id 1094713345 一定会作为候选 id 出现
   （由 `ProbeEntityKeyId` → `ReadCrudKey` 在实体模型上读出，`OwnedGraphDelete.cs:74-77,152`）。
5. **图不进场景树**：图是 Kind-9 注册表资源（`cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH`，`:515`），
   在 `Registry` 单例下（`EditorAdapter.cs:105-107,127`）；而走行**排除**了 `Registry.root`
   （`ArchiveModel.cs:208-215`）。所以走行里**没有一个候选 model 是图模型**。

⇒ `graphModels.TryGetValue(model, …)` 对所有候选恒 false ⇒ `modelMatched=0`；候选里能看到的实体 id
就包括关卡实体 1094713345。**四测皆 0 是结构性的，不是偶发。**

> 同一走行 + 同一根 + 同一 `vQPKy8Qu9ev`/`ndlKBRCbBjF`，在**实体删除**路径里是被证有效的
> （`EntityCrudProbe.cs:123-147` `FindCrudFrontend`：`:131` 判节点类型、`:132` 取 `vQPKy8Qu9ev`、
> `:136` 取 `ndlKBRCbBjF`、`:139` 断言 `FullName == CrudEntityType`）。
> 这正佐证：**这条走行是"实体走行"，不是"图走行"**——`OwnedGraphDelete` 借错了工具。

---

## 3. 两个查找能否统一——读两处后给判决

### 3.1 两处查找，逐条对照

**(A) `AuthoringGraph.State()` / `Author()` 的查找**（`AuthoringGraph.cs:211-235`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**(B) `OwnedGraphDelete` 的身份侧查找**（`OwnedGraphDelete.cs:100-107`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**判定：可以统一，而且几乎已经统一。** 两者是**同一套机制**：
- 同一个 `Resources()`（`EditorAdapter.cs:105-107` → `ResourcesCore`，Kind 归类在 `:160,166`，
  id 两级包装在 `:161-164`，**`REGISTRY_ID_MISMATCH` 断言「身份键 id == 注册表字典键」** `:165`）；
- 同样的 `Kind==9`；
- (A) 多一个**精确名相等**（`Stored(model,"c1pKbESgr8S")==name`），(B) 事后用**前缀** `MW_` 判（`:179`）。

所以"把 (B) 换成 (A)"**零新符号、零新机制**。

### 3.2 但"统一查找"解决的是**身份**，不是**删除原语**——这是关键

节点走行**不是**身份查找。身份早就在 `Resources()` 侧拿到了（(B) 第一步就对了，
实测 `graphModelsVisible=1`）。节点走行的**唯一用途**，是产出那个**带 delete 方法的 `resource` 句柄**
（`:182 index[id]=resource`，`:276` 在它上面取 `zgVKB6OS1MZ`）。

profile 事实（`EditorBindingProfile.Generated.cs`，逐条实测）：
- `zgVKB6OS1MZ`→`Ko2jCe0QDHc`，**全 profile 只声明一次**（`:942`），返回 `System.Boolean`；
- 它声明的**宿主类型**是代理 `fYiNtsjNFLpjCdRQ3Cvj.snNdG3jNcHxXOpcU0fHG`，**与 resolve 同一宿主**；
- 该代理的 resolve **返回实体模型**（`:878`）。

⇒ **唯一的 "resolve + delete" 代理是实体专用的**。把身份查找换成 (A) 之后，删除手里只有
`Resource.Model`（图模型）与 `Resource.Id`，**没有** `Ko2jCe0QDHc`。

再看图模型侧有没有可用的删除原语（profile 里所有声明在图模型类型上的契约）：

| 符号 (legacy→actual) | 签名 | 作用 |
|---|---|---|
| `BWmKmyL3bM7`→`A35XuAK09QD`（`:692`） | `(key,double,double,?,?):?` | 加节点 |
| `S06Xu1xAKtQ`（`:866`） | `(UInt32,key,double,double,?,?):?` | 按 id 加/改节点 |
| `zbUKmIZoGMn`→`EGOXuNqHvvx`（`:628`,`:941`） | `(UInt32,?,bool,bool,bool):bool` | **删节点**（`FinishGraph.cs:251-252` 在用） |
| `vJwKOEFj00D`→`kx7Xu5hjIbJ`（`:602`,`:915`） | `(?,?,bool):bool` | 断边 |
| `LapKOOcuGY1`→`IfyXuTjM1NU`（`:428`,`:738`） | `(?,?,Int32):bool` | 连边 |
| `K61KONg4LUT`/`n4aX5ZRwxAO`（`:730`）等 | 读 | 读节点表 |

**图模型类型上没有任何"删掉整张图"的方法；只有"删节点"。** 管理器类型
（`mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q`→`RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx`，`:563`）
在 profile 里只有三条契约：`:932` 建图（`yBnirE4YONq`→`JqQXqPc1XW0`）、`:798`、`:880`——
**没有一条是"移除图"**。

并且有一条**实测否定**：`FinishGraph.cs:214-215` 记录
*"the Resources() object itself does NOT carry `zgVKB6OS1MZ` -> `FINISH_DELETE_NATIVE_METHOD_MISSING`"*。
即**注册表侧的 Kind-9 对象自身不可删**。

### 3.3 判决与"这算不算那个 fix"

**统一 = YES，且这是对"身份恒解析不出"这个症状的正确修法。** 具体地：

- 删除应当**丢掉节点走行的身份 join**（`OwnedGraphDelete.cs:128-185`），身份**完全**取 (A) 那套查找
  （`Resources()` + `Kind==9` + 精确名相等，必要时再叠加 `MW_` 前缀闸），因为 (B) 的 `Resources()` 半已经工作。
- 这样 `modelMatched=0` 这类**静默空转**会被彻底移除：能解析的图**一定**解析得到。

**但"统一查找"本身不产生一次成功的删除**——它把故障从一个**静默的 no-op**
变成一个**具名的 fail-closed**：解析成功 → 派发 `Ko2jCe0QDHc` → 发现注册表对象/图模型**没有此方法**
→ `OWNED_GRAPH_NATIVE_METHOD_MISSING`（`OwnedGraphDelete.cs:277-280`）。

因此诚实结论分两半：

| 半边 | 现状 | 统一查找能修吗 |
|---|---|---|
| **身份解析**（id → 图，含名/ID 一致） | 恒 0（错的 join） | **能**——改走 (A)，零新符号 |
| **删除原语**（在图上调用一个"移除"） | 无（profile 无契约；`Resources()` 对象无 `Ko2jCe0QDHc`，实测） | **不能**——这是**另一个缺失**，不是查找能补的 |

所以：**统一查找是"删得掉的前置"而非"删得掉"本身**。
"这是不是那个 fix"——**是身份半边的 fix，不是删除半边的 fix**。把删除挪到统一查找之后，
必须**先**解决"图用哪个原生原语移除"（要么在管理器/图模型上继续逆向出一个 remove，要么证明不存在），
否则删除只会**更响亮地失败**，不会**成功**。这条不因统一查找而消失——**不许把统一说成"能删了"**。

> 边界（doctrine："搜不到 ≠ 不存在"）：profile 是**受控契约子集**，不是编辑器 DLL 的全量方法表。
> "管理器/图模型上没有删除契约"是**本 profile 范围内的精确负面**；真机可能还有未进 profile 的方法。
> 但 §3.2 的 `FinishGraph.cs:214-215` 是**真机实测**：注册表对象**就**不带 `zgVKB6OS1MZ`。

---

## 4. 最小只读实验（dry-run 请求形状）+ 决策表

现有代码**已经把判定所需的诊断内建**（`OwnedGraphDelete.cs:195-207`），**无需改一行**。
用**一个已知的 Kind-9 图 id**（本会话任一看得见的 `MW_...` 图，或校准图 id）发**一次 dry-run**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- op 名与 `--ids` 形状：`ManagedBridge/BridgeServer.cs:367-388`（`ReadUintArray(root,"ids")`）、
  `elevated-request.py:163-164,603-615`（`query_ops` 白名单 + `request["ids"]=ids`）。
- 该 dry-run **不调用任何删除**（`OwnedGraphDelete.cs:236-243`）；解析不中则走拒绝分支
  （`:227-234`），两者**都**带回 `diagnostics` 与 `matchDiagnostics`。

读回字段与判定：

| 观察（回执字段） | 判定 | 修法方向 |
|---|---|---|
| `diagnostics` 里 `graphModelsVisible>=1`，`matchDiagnostics.kind9Visible` 含所请求 id/名 | **统一查找（`Resources()`+Kind9）解析成功**——身份半边已可修 | §3.3 身份：改走 (A) |
| `matchDiagnostics.candidateModelTypes` 只有实体类型（`Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr`）且 `wrapperKey.readable==0` | 走行**从未**到达图模型 | 删除原语另找；身份走 (A) |
| `candidateIdExtraction.entityKey.matchesKind9 > 0` 或 `flat.matchesKind9 > 0` | 走行侧模型**携带**某 Kind-9 id | 换 id 匹配谓词即可（§GRAPH-DELETE-PROBE §4.1） |
| `candidateIdExtraction.wrapperKey.matchesKind9 > 0` | 走行**确实**解出了图模型 | 谓词换 `ProbeWrapperKeyId` 路径 |
| `candidateIdsSample` 只有实体 id（含 1094713345） | 走行侧**根本不含**图身份 | 走行根错 / 或图无前端可删节点 |

**收敛判据**：本次要确认的是"**统一查找找得到图**"——即上表第 1 行。
只要 `graphModelsVisible>=1` 且 `kind9Visible` 命中所请求的图，就**证实**：
删除可以**完全**基于 `Resources()`+Kind9+名 解析身份，节点走行对身份**零贡献**。
第 2 行同时成立则进一步说明：节点走行对**删除原语**也零贡献（它到的是实体）——
那么删除的**下一步**不是改谓词，而是**给图找一个移除原语**（不在本文件范围）。

**注（诊断盲区）**：`matchDiagnostics` 目前只记三种提取（`entityKey`=`Qi8iCzKCkTt`、
`wrapperKey`=`fLGKbbHeoYG`、`flat`=`namiwGPRyPS`，`OwnedGraphDelete.cs:152-172`），
**未**记录前端资源键 id `y30KBtqRTpg.ol3iwzG1HRm`（`EditorBindingProfile.Generated.cs:930,884`）。
若想验证"节点侧资源键 id == Kind-9 id"这条旁路（`FrontendCommands.cs:284,292,307` 已在读它），
需要在同一个 dry-run 里**增装一个只读 probe**（仍不参与删除判定）——
**该增装不在本文件范围内**（本文件只分析，不改代码，不发请求）。

> **本文件不发送、也不建议现在发送任何请求**——桥是 OFFLINE 禁项。
> 线下准备就绪、由真机会话在用户在场的条件下发一次。

---

## 5. 证据索引（file:line，本次实测）

**被诊断对象 —— `tools/editor-bridge/Adapter/OwnedGraphDelete.cs`**
- `:40-42` 常量（200000 节点 / 深度 14 / 名前缀 `MW_`）
- `:52-69` 「四次 modelMatched=0」注释与"replacement predicate 必须从证据选"的纪律
- `:74-90` 三个只读诊断 probe（`ProbeEntityKeyId`/`ProbeWrapperKeyId`/`ProbeFlatId`）
- `:103-105` 引用相等的 `graphModels` 表
- `:128-129` 走行复用 `OwnedDeleteWalkRootType`（**实体**场景树根）
- `:135-144` `vQPKy8Qu9ev` → `ndlKBRCbBjF` → model
- **`:174` 匹配谓词（引用相等）** ← 恒 0 之所在
- `:179-184` `MW_` 前缀闸 + 歧义拒绝 + `index[id]=resource`
- `:186-190` `graphModelsVisible/.../modelMatched` 串
- `:195-207` `matchDiagnostics`（kind9Visible / candidateModelTypes / candidateIdExtraction）
- `:211-243` dry-run 与拒绝分支；`:276-280` 在 resource 上取 `zgVKB6OS1MZ`、缺则 `OWNED_GRAPH_NATIVE_METHOD_MISSING`

**走行与资源两根**
- `EditorAdapter.cs:105-107` `Resources()`；`:127` 注册表根字段 `bwbixDw3yob`；`:140,171` 字典 `JkmYibSuZr`/`pIxYiE5REC8`
- `EditorAdapter.cs:144-151` `entityModels`；`:160-166` Kind 归类（6/9）；`:165` `REGISTRY_ID_MISMATCH`；`:186` 名字段
- `ArchiveModel.cs:193-299` `WalkEditorGraph`；`:196-215` 根；**`:208-215` 明确不把 `Registry.root` 当根**
- `OwnedEntityDelete.cs:43-44` `OwnedDeleteResourceNodeType` / `OwnedDeleteWalkRootType`
- `EntityCrudProbe.cs:123-147` `FindCrudFrontend`（同走行同根同字段，**断言解出的是实体模型**）；`:228-234` 实体删除调用

**关卡实体 1094713345**
- `EditorAdapter.cs:636-637`（id + 名 `关卡实体`）；`:837`；`AuthoringGraph.cs:252`；`FinishGraph.cs:183,295`

**两处查找**
- `AuthoringGraph.cs:211-235`（`:219-221` kind9+名；`:114` 名正则**要求 `MW_API_` 前缀**，比删除的 `MW_` 更窄）
- `OwnedGraphDelete.cs:100-107`（kind9）

**profile —— `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs`（legacy→actual 与契约）**
- `:473` 实体模型类型；`:477` 代理类型；`:515` 图模型类型；`:542` 场景面板 VM；`:573` 节点类型；`:563` 管理器类型
- `:878` `ndlKBRCbBjF`→`ABijCETHXZy` **唯一声明**，返回**实体模型**
- `:942` `zgVKB6OS1MZ`→`Ko2jCe0QDHc` **唯一声明**（同代理宿主，返回 bool）
- `:916` `vQPKy8Qu9ev`→`NJvjJkLWol0` 声明在**节点**类型上，值类型=代理
- `:844` `fLGKbbHeoYG`→`CWeX5frl6xa` 只声明在**图模型**类型上
- `:692,:730,:738,:744,:866,:915,:934,:941` 图模型类型上的**全部**方法契约（含删节点 `EGOXuNqHvvx`）
- `:798,:880,:932` 管理器类型上的全部契约（`:932`=建图，**无移除**）
- `:628` `zbUKmIZoGMn`→`EGOXuNqHvvx`；`:602` `vJwKOEFj00D`→`kx7Xu5hjIbJ`；`:428` `LapKOOcuGY1`→`IfyXuTjM1NU`
- `:628/:569/:603/:629` 四符号映射
- 前端资源键：`:617` `y30KBtqRTpg`→`MpTjCoCxyBO`、`:575` `ol3iwzG1HRm`→`jGhXNNcbCus`、`:622` `yKiiwIS6frK`→`X7sXNnbtoAB`；契约声明在 `:930/:884/:935`

**其它佐证**
- `FinishGraph.cs:200-215` 图删除从未成功；**`:214-215` 实测 `Resources()` 对象不带 `zgVKB6OS1MZ`**；`:251-252` 删节点原语
- `FrontendCommands.cs:105-128` 场景根 = `Window.DataContext`（`rootName`）；`:168-180,257` 同走行读 `vQPKy8Qu9ev`/`y30KBtqRTpg`/`yKiiwIS6frK`/`ol3iwzG1HRm`
- `ManagedBridge/BridgeServer.cs:367-388` op 接线；`elevated-request.py:163-164,603-615` CLI 形状
- `tools/editor-bridge/tests/test_owned_graph_delete_contract.py:6-11` 四测 `modelMatched=0`；守卫 fail-closed 不变量
- `docs/PROGRESS-BY-FUNCTION.md:188` 2026-10-10 诊断（走行到实体模型 id 1094713345）
- `docs/research/reverse-eng-20261010/GRAPH-DELETE-PROBE.md`（兄弟分析）

---

## 6. 边界与未做

- **未改一行代码**，**未发任何请求**，**未连桥 / 未碰游戏或编辑器 / 未动 helper**。
- **未跑真机**：所有"能/不能"判定均为**静态读代码 + 读 profile**，不等于真机通了。
  唯一的真机记录是**仓内既有回执**（`modelMatched=0`、`graphModelsVisible=1`）与
  `FinishGraph.cs:214-215` 的既有实测。
- **profile 是受控子集**：管理器/图模型"无删除契约"是**本 profile 范围内的负面**；
  真机 DLL 可能还有未进 profile 的方法（doctrine："搜不到 ≠ 不存在"）。
  但"注册表 Kind-9 对象不带 `zgVKB6OS1MZ`"是**真机实测**（`FinishGraph.cs:214-215`）。
- **未证**：图是否在**别的面板根**下有前端可删节点（本文只证：在**场景面板根**下没有）。
  若 §4 落在"走行不含图身份"那一行，下一步是**给图找移除原语 / 另找走行根**，两者都需进一步逆向。

---

*分析于 2026-10-10。仅静态阅读。未改码，未发请求，未触碰游戏/编辑器/存档。*
