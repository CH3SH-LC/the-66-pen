> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# GRAPH-DELETE-PROBE — 为什么 `delete-owned-graph-ids` 永远是 `modelMatched=0`

> 纯分析。**没有编辑** `tools/editor-bridge/Adapter/OwnedGraphDelete.cs`，**没有向 bridge 发任何请求**。
> 全部结论来自静态阅读仓内 C# 源码与符号绑定 profile；引用的行号均为本 checkout 的当前行号。
> 相关离线契约测试 `tools/editor-bridge/tests/test_owned_graph_delete_contract.py` 已随本次改动被引用（未修改）。
> 离线套件基线：169 tests OK（`tools.gameplan.tests.*` 九件套）。

符号约定：本工程到处用 `B("旧的11位混淆串")`（`EditorAdapter.cs:87`），
profile（`EditorBindingProfile.Generated.cs`）把它解析成**当代构建的真实混淆名**。
下文两条都给：`legacy` → `` actual ``。

---

## 0. 结论（先给判决）

1. **匹配谓词**是**引用相等**（reference identity），不是 id 相等。
   它只能返回 0，因为要匹配的两个对象**根本不在同一个对象图里**：`Resources()` 交出的
   Kind-9 模型是**注册表字典里的图模型**；`WalkEditorGraph` 交出的模型是**前端场景树里
   经一个 entity 专用代理 accessor 解出来的实体模型**。四测皆 0 是结构性的，不是偶发。
2. **决定性旁证在 profile 里**：全 profile 只有 **一个**「资源代理」类型同时带
   resolve（`ndlKBRCbBjF`）和 delete（`zgVKB6OS1MZ`），而它的 resolve **按契约返回实体模型类型**
   （`EditorBindingProfile.Generated.cs:878`）。所以无论走多深、走多少节点，`model` 都不可能是图模型。
3. **候选修法**：把 `OwnedGraphDelete.cs:174` 的引用比较换成**前端资源键 id 比较**，读
   字段 `vQPKy8Qu9ev`（→ `NJvjJkLWol0`） → `y30KBtqRTpg`（→ `MpTjCoCxyBO`） → `ol3iwzG1HRm`（→ `jGhXNNcbCus`），
   并用 `yKiiwIS6frK`（→ `X7sXNnbtoAB`）做对象类别闸。这些符号 **profile 里都有，且别的 op 已经在读**
   （`FrontendCommands.cs:284/292/307`）。**但**它只在「走行确实能走到 id 等于 Kind-9 id 的节点」时才成立，
   所以还需要最小实验把「匹配方式错」与「走行根错」分开（§5）。
4. **最小只读实验**：**一次**现有 dry-run —— `delete-owned-graph-ids-dry-run`，ids 给一个已知的
   Kind-9 图 id —— 读回**已经内置**的 `matchDiagnostics`（`OwnedGraphDelete.cs:195-207`），
   看 `candidateModelTypes` 与三个 `candidateIdExtraction.*.matchesKind9`。一张回执即可判定（§5 决策表）。

---

## 1. 精确的匹配谓词，以及为什么它只能得 0

### 1.1 谓词本体

`BuildOwnedGraphIndex` 先用 **`ReferenceEqualityComparer`** 建「模型对象 → id」表：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


然后在节点走行的每个候选上，**用引用相等**判归属（这就是那个 predicate）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


`model` 的来源是：
`resource = Field(node, B("vQPKy8Qu9ev"))`（:136）→
`resolve = resource.GetType().GetMethod(B("ndlKBRCbBjF"))`（:137）→
`model = resolve.Invoke(resource, null)`（:144）。

即：**「节点侧代理解出来的模型」必须与「`Resources()` 交出的 Kind-9 模型」是同一个对象引用**。
源码注释把它当成既定事实（`OwnedGraphDelete.cs:101-102`：*"the walk and the node scan hand back
the same model objects, not copies"*）；四次实测（48 / 499 / 31 个候选，全部 `modelMatched=0`，
见 `OwnedGraphDelete.cs:52-60` 与 `test_owned_graph_delete_contract.py:6-11`）说明这条断言对图不成立。

### 1.2 为什么引用永远不相等——不是「拷贝」，是**两类不同对象**

`Resources()`（`EditorAdapter.cs:107-175`）与节点走行（`ArchiveModel.cs:193-299`）从**两个不同的根**
出发，抵达**两个不同的容器**：

| | `Resources()`（Kind-9） | 节点走行 `WalkEditorGraph` |
|---|---|---|
| 根 | `Registry` 单例（`ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre` → `zsVmV4Lr1OujoGgk8Hag.k1GFMnLrARA1QdRW7ITw`）的字段 `bwbixDw3yob`（→ `DB6Lr86YC4o`）；`EditorAdapter.cs:127` | `Application.Current` / 每个 `Window` / `Producer`；**`Registry.root` 被刻意排除**（`ArchiveModel.cs:208-215`）。`OwnedGraphDelete.cs:128-129` 又把它过滤到单一 `rootType = OwnedDeleteWalkRootType` |
| 容器字段 | 模型字典 `JkmYibSuDZr`（→ `RCApyAMerv2`）+ 子节点 `pIxYiE5REC8`（→ `iR6pynCDO8i`）；`EditorAdapter.cs:140,171` | 任意对象字段 + WPF 可视树 + 菜单；`ArchiveModel.cs:236-297` |
| 拿到的「模型」 | **注册表条目值**，类型 `cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH`（→ `E8xv5pXu77T6046o5sVM.vUK4LLXuq7BbA0L017eJ`）= 图模型；`EditorAdapter.cs:160,166` | 前端**节点**（类型 `oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7`，→ `cxH9SFjCgqJqBexqED9I.OHad5KjCWJC4aw0J66v4`），再经 `vQPKy8Qu9ev` 代理 → `ndlKBRCbBjF()` 解出**实体模型** |
| id 读法 | `Field(Field(Field(model,B("fLGKbbHeoYG")),B("VpIiRZgdEln")),B("namiwGPRyPS"))`；`EditorAdapter.cs:161-164` | 代理键 `Field(Field(resource,B("y30KBtqRTpg")),B("ol3iwzG1HRm"))`；`FrontendCommands.cs:284,307` |

**这两个根彼此不可达**，两条访问路径也没有交点：`Resources()` 的 Kind-9 模型是注册表条目值；
节点走行到达的是 `Window.DataContext`（场景编辑器面板 VM，类型 `gyj3OSueTNTdJeQL0yyH.tyZNMjueXM5Cae1EUsbH`
→ `vjAJAAQ5EnQrVCtWeP5c.GUTcsNQ5DwQLe225s2f4`，见 `FrontendCommands.cs:110-117`）下的前端节点。
所以 `graphModels.TryGetValue(model, …)` 恒 false。

> 2026-10-10 实测（记录于 `docs/PROGRESS-BY-FUNCTION.md:188`）与此一致：`Resources()` 侧正常
> （看得见图、id 名都对），但节点走行到的模型是**实体**（id 1094713345，即关卡实体），不是图。

### 1.3 计数器的形状也自证同一件事

`resourceRead == accessorFound == hasDeleteMethod`、`modelMatched == 0`（`OwnedGraphDelete.cs:114,188-190`）
正好对应：走行里每个带 `vQPKy8Qu9ev` 的节点都持有**同一类**代理，该类代理**同时**声明了
`ndlKBRCbBjF`（resolve）与 `zgVKB6OS1MZ`（delete）——所以前三个计数逐个相等；
而 resolve 返回的实体模型永远命中不了图的引用表——所以第四个恒 0。

---

## 2. profile 里的决定性事实：唯一的「resolve+delete 代理」是实体专用的

在整份 `EditorBindingProfile.Generated.cs` 里搜索这两个成员的实际混淆名：

- `ndlKBRCbBjF` → `` ABijCETHXZy ``，**全 profile 只声明一次**：
  `EditorBindingProfile.Generated.cs:878`
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  返回类型 `LhusWLXd5NUZ7IineV1x.o6MMsvXduEaZkjEZB6yx` = `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr`
  = `CrudEntityType`（实体模型，`EntityCrudProbe.cs:14`，`EditorBindingProfile.Generated.cs:473,783`）。
- `zgVKB6OS1MZ` → `` Ko2jCe0QDHc ``，**也只在同一个类型上声明一次**：
  `EditorBindingProfile.Generated.cs:942`（`():System.Boolean`）。

承载两者的类型 `fYiNtsjNFLpjCdRQ3Cvj.snNdG3jNcHxXOpcU0fHG`
= `VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf`（`EditorBindingProfile.Generated.cs:477`）。
而它就是前端节点字段 `vQPKy8Qu9ev` → `NJvjJkLWol0` 的值类型（`EditorBindingProfile.Generated.cs:916`），
被 `FrontendCommands.cs:296-307` 当作「资源路径」对象读取。

**推论**：resolve 的返回类型是**契约写死的实体模型**。图模型是另一个类型
（`E8xv5pXu77T6046o5sVM.vUK4LLXuq7BbA0L017eJ`）。因此 OwnedGraphDelete 用的这条 accessor
**在类型系统层面就不可能交出图模型**——这比「引用不相等」更根本，是「类型就不对」。

同时这也解释了 `FinishGraph.cs:207-215` 的备注：`Resources()` 的 Kind-9 对象自身**不带**
`zgVKB6OS1MZ` → `FINISH_DELETE_NATIVE_METHOD_MISSING`（图模型类型上没有 delete 契约）。

---

## 3. `Resources()`（Kind 9）与节点走行注册表：从代码本身对照

（§1.2 的表是结论，这里给出可核对的源码语义。）

- **Kind 归类的唯一权威**是 `ResourcesCore` 用**模型运行时类型全名**做的判定：
  `IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C` → 6，`cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH` → 9
  （`EditorAdapter.cs:160,166`）。Kind-9 的 id 走**两级包装**：
  模型字段 `fLGKbbHeoYG`（图键包装）→ 包装字段 `VpIiRZgdEln`（值）→ 键字段 `namiwGPRyPS`（id）
  （`EditorAdapter.cs:161-164`）。图名同形：`Stored(model, "c1pKbESgr8S")` = 字段 `c1pKbESgr8S` → `VpIiRZgdEln`
  （`EditorAdapter.cs:81-85,186`）。
- **注册表 id 与条目键必须一致**：`if (id != (uint)entry.Key) throw REGISTRY_ID_MISMATCH;`
  （`EditorAdapter.cs:165`）。**这一行是候选修法能成立的根据**：注册表字典的键 = 模型身份键 id = 同一 id 空间。
- **节点走行不是资源走行**：`WalkEditorGraph` 的根是 WPF 应用/窗口/Producer，注释明说
  *"Registry.root is deliberately NOT a root here … it was spending everything inside the registry"*
  （`ArchiveModel.cs:208-215`）。所以节点走行**天生看不见 Kind-9 注册表模型**。
- 节点走行与注册表**唯一**的会合点是 id，不是对象：前端节点/代理携带的资源键
  `y30KBtqRTpg`（→ `MpTjCoCxyBO`，`EditorBindingProfile.Generated.cs:930`）里有
  `ol3iwzG1HRm`（→ `jGhXNNcbCus`，UInt32，:884）= 对象 id，和 `yKiiwIS6frK`（→ `X7sXNnbtoAB`，:935）= 对象类别。
  `FrontendCommands.cs:284,292,307` 已经在读这两个字段来识别资源（例如场景文件夹 id 313584）。

> 注意有**两个不同的「键」类型**，不要把它们的字段名互换：
> - 身份键 `DFG6S3XnnydlOvbTtokr.GL3iQaXn10FDkUwcfAJh`（id 字段 `namiwGPRyPS`/`L0kXNqYb39f` + 四个 category）：注册表、图/实体模型侧使用。
> - 前端资源键 `WlnLLYXNvJcllydMtSw9.LWt2TSXNGEdQWP0CHtgr`（id 字段 `ol3iwzG1HRm`/`jGhXNNcbCus` + `yKiiwIS6frK`/`X7sXNnbtoAB`）：前端节点/代理侧使用。

---

## 4. 具体候选修法（点名混淆符号）

### 4.1 主候选：把「引用比较」换成「**前端资源键 id 比较**」

把 `OwnedGraphDelete.cs:174` 的


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


换成按 **id 数值**匹配，而 id 从**节点侧代理自身携带的资源键**读：

- 字段 `vQPKy8Qu9ev`（→ `NJvjJkLWol0`） → 字段 `y30KBtqRTpg`（→ `MpTjCoCxyBO`） → 字段 `ol3iwzG1HRm`（→ `jGhXNNcbCus`）
  = 前端节点的资源 id；同一对象的 `yKiiwIS6frK`（→ `X7sXNnbtoAB`）给出对象类别，用作附加闸
  （只接受「图」这一类，拒绝实体/文件夹）。
- 拿这个 id 去查 Kind-9 的 id 集合（`kind9Ids`，`OwnedGraphDelete.cs:117`）。

**为什么它能成立**：`ol3iwzG1HRm` 与注册表字典键同空间（`EditorAdapter.cs:165` 已经断言
`模型身份键 id == entry.Key`），所以数值相等是**语义上的同一身份**，不依赖「两条走行给出同一个对象」——
而后者被四测证伪。
**为什么它已经可读**：`resource`（即 `vQPKy8Qu9ev` 代理）在 `OwnedGraphDelete.cs:136` 就已经在手上；
再读两级字段即可，**零新符号发明**；且这些符号 profile 全有、别的 op 已在读（`FrontendCommands.cs:284,307`）。

**残留不确定性（必须由实验判定，见 §5）**：这条修法只在「节点走行确实能走到一个
`ol3iwzG1HRm` 等于某个 Kind-9 id 的节点」时才有效。若节点走行只到场景树里的**实体**节点，
则 `ol3iwzG1HRm` 只会是实体 id，仍匹配不上图 id —— 那问题就**不是匹配方式**，而是**走行根**（§4.3）。

### 4.2 备选（仅当 walk 其实能到达图模型时）：按**图身份键**匹配

若走行确实能解出图模型，则应当读图模型自己的身份键，路径与 `ResourcesCore` 完全一致：

- 字段 `fLGKbbHeoYG`（`CWeX5frl6xa`，`EditorBindingProfile.Generated.cs:844`，**只声明在图模型类型上**）
  → `VpIiRZgdEln`（`PIWXZgk5Tyr`，:789）→ `namiwGPRyPS`（`L0kXNqYb39f`，:877）。
- 这**正是** `OwnedGraphDelete.cs:78-82` 的 `ProbeWrapperKeyId`。它现在是纯诊断。
  若一次 dry-run 显示 `wrapperKey.matchesKind9 > 0`，则把谓词换成它就够了。

**反面证据**：`CWeX5frl6xa` 只声明在**图模型**类型（:844），实体模型类型上**没有**该字段，
所以只要走行交出的是实体模型，`ProbeWrapperKeyId` 必抛异常 → `readable=0`。故 §4.2 不能单独作为修法。

### 4.3 若 walk 根错：需要换/加一个走行根（profile 中**没有**现成符号）

若实验显示走行只产实体模型，那么图没有前端「可删资源节点」（或它在别的面板根下）。
此时修法必须改根，而不是改谓词；需要的符号是**图编辑器面板的根类型**（或图所在容器）。
**已知** `WalkEditorGraph` 的根过滤用的是 `OwnedDeleteWalkRootType`
（`OwnedEntityDelete.cs:44`，实体场景树根），profile 里**没有**对应的「图面板根」符号——
这是一个**精确的负面结果**：候选修法 4.3 现在无从点名，必须由 §5 的实验先确认它是否是真正的方向。

---

## 5. 最小只读实验（一个 dry-run 请求形状）+ 决策表

现有代码**已经内置**了回答所需的诊断（`OwnedGraphDelete.cs:195-207`），**无需改一行**。
用**一个已知的 Kind-9 图 id**（例如本会话可见的任一 `MW_` 图，或校准图的 id）发**一次 dry-run**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


（op 名与 `--ids` 形状见 `ManagedBridge/BridgeServer.cs:349-364` 与 `elevated-request.py:162,513`。
桥侧 `ReadUintArray(root,"ids")`。**本文件不发送、也不建议现在发送**——桥是 OFFLINE 禁项；
线下准备就绪、用户在真机会话里发。）

回执里读 `matchDiagnostics`（拒绝分支 `OwnedGraphDelete.cs:231` 带回；dry-run 分支 :240 也带回）：

| 观察 | 判定 | 对应修法 |
|---|---|---|
| `candidateModelTypes` 只有实体类型（`Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr`）且 `candidateIdExtraction.wrapperKey.readable == 0` | 走行**从未**到达图模型 | §4.3：改走行根（profile 无现成符号，需另行逆向） |
| `candidateIdExtraction.entityKey.matchesKind9 > 0` 或 `flat.matchesKind9 > 0` | 走行侧模型**携带**某个 Kind-9 id |= §4.1/§4.2 的匹配方式错，可用 id 匹配修复 |
| `candidateIdExtraction.wrapperKey.matchesKind9 > 0` | 走行**确实**解出了图模型 | §4.2：把谓词换成 `ProbeWrapperKeyId` 路径即可 |
| `candidateIdsSample` 里出现所请求的图 id | 走行侧**读得到**该图身份，只是比较方式错 | §4.1/§4.2 |
| `candidateIdsSample` 只有实体 id（如 1094713345） | 走行侧根本不含图身份 | §4.3 |

**注**：`matchDiagnostics` 目前只记录三种提取
（`entityKey`=`Qi8iCzKCkTt`、`wrapperKey`=`fLGKbbHeoYG`、`flat`=`namiwGPRyPS`，`OwnedGraphDelete.cs:152-172`），
**未**记录前端资源键 id `y30KBtqRTpg.ol3iwzG1HRm`(§4.1 的关键字段)。
因此上表**尚不能**直接验证 §4.1 那条通路——若 dry-run 落在「走行不含图身份」那一行，
下一步的最小增量是**加一个只读诊断 probe**（仍不参与删除判定）去读 `ol3iwzG1HRm`/`yKiiwIS6frK`，
再发同一次 dry-run 读回。该 probe 的加装**不在本文件范围内**（本文件只做分析，不改代码）。

---

## 6. 为什么这是「分析」而不是「修复」——以及本文件的边界

- **未改** `OwnedGraphDelete.cs`；`index[id] = resource` 仍只由引用匹配写入（
  `test_owned_graph_delete_contract.py:91-104` 守卫这条不变量，仍绿）。
- 本文档只**点名**要读的符号并给出**回执驱动**的实验形状。替换谓词必须从一次真机回执里读出，
  不能凭本文件的推断直接改行为——这是工程 doctrine（"the replacement predicate has to be chosen from evidence"，
  `OwnedGraphDelete.cs:62-69`）。
- §4.1 是**最可能的**候选（因为符号已在 profile、已被别的 op 使用、且语义上就是同一个 id 空间），
  但它的成立条件（walk 到得到 id 匹配的节点）是**未证**的，必须靠 §5 分开验证。

---

## 7. 证据索引（file:line）

**被诊断对象**
- `tools/editor-bridge/Adapter/OwnedGraphDelete.cs`
  - `:40-42` 常量（200000 节点 / 深度 14 / 名前缀 `MW_`）
  - `:74-90` 三个诊断 probe（`ProbeEntityKeyId` / `ProbeWrapperKeyId` / `ProbeFlatId`）
  - `:103-105` 引用相等的 `graphModels` 表
  - `:128-129` 走行复用 `OwnedDeleteWalkRootType`（实体根）
  - `:136-144` `vQPKy8Qu9ev` → `ndlKBRCbBjF` → 模型
  - `:152-172` 三个 probe 的计数器（纯诊断）
  - **`:174` 匹配谓词（引用相等）** ← 恒 0 之所在
  - `:186-190` `graphModelsVisible/nodes/.../modelMatched` 诊断串
  - `:195-207` `matchDiagnostics`（kind9Visible / candidateModelTypes / candidateIdExtraction）
  - `:211-243` `DeleteOwnedGraphIds` dry-run 与拒绝分支

**走行与资源两根**
- `tools/editor-bridge/Adapter/EditorAdapter.cs:105-175` `Resources()/ResourcesCore`（Kind 归类 :160/:166，id :161-164，REGISTRY_ID_MISMATCH :165）
- `tools/editor-bridge/Adapter/EditorAdapter.cs:81-85` `Stored`（两级包装）
- `tools/editor-bridge/Adapter/ArchiveModel.cs:193-299` `WalkEditorGraph`；`:208-215` 明确**不**把 Registry.root 当根
- `tools/editor-bridge/Adapter/OwnedEntityDelete.cs:43-44` `OwnedDeleteResourceNodeType` / `OwnedDeleteWalkRootType`
- `tools/editor-bridge/Adapter/FrontendCommands.cs:110-117` 场景根 = `Window.DataContext`；`:284,292,307` 已读 `ol3iwzG1HRm`/`yKiiwIS6frK`

**profile（legacy → actual 与契约）**
- `tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs`
  - `:878` `ndlKBRCbBjF`→`ABijCETHXZy` 返回**实体模型**（唯一声明）
  - `:942` `zgVKB6OS1MZ`→`Ko2jCe0QDHc` 唯一声明（同一代理类型）
  - `:916` `vQPKy8Qu9ev`→`NJvjJkLWol0` 是**节点**字段，值为代理类型
  - `:844` `fLGKbbHeoYG`→`CWeX5frl6xa` 声明在**图模型**类型上
  - `:930 / :884 / :935` `y30KBtqRTpg`→`MpTjCoCxyBO`，`ol3iwzG1HRm`→`jGhXNNcbCus`，`yKiiwIS6frK`→`X7sXNnbtoAB`
  - `:877` `namiwGPRyPS`→`L0kXNqYb39f`
  - `:477 / :573 / :515 / :473 / :542` 代理 / 节点 / 图模型 / 实体模型 / 场景根 的类型映射
  - `:932` `yBnirE4YONq`→`JqQXqPc1XW0`（图**创建**走 manager，不是走前端节点）

**其它佐证**
- `tools/editor-bridge/Adapter/FinishGraph.cs:200-215,275-280` 图删除从未成功、`Resources()` 对象不带 delete
- `tools/editor-bridge/ManagedBridge/BridgeServer.cs:349-364` op 接线；`tools/editor-bridge/elevated-request.py:162,513` CLI 形状
- `tools/editor-bridge/tests/test_owned_graph_delete_contract.py` 离线不变量守卫
- `docs/PROGRESS-BY-FUNCTION.md:188` 2026-10-10 诊断记录（走行到实体模型 id 1094713345）

---

*分析于 2026-10-10。仅静态阅读 + 离线套件（169 OK）。未改码，未发请求。*
