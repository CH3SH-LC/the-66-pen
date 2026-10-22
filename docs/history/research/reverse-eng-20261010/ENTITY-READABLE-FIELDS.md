> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #9 — 实体模型上「我们能读到的字段」全量枚举 —— ENTITY-READABLE-FIELDS

**产出日期**：2026-10-10。位置：`docs/research/reverse-eng-20261010/ENTITY-READABLE-FIELDS.md`。
**本任务唯一拥有/新增的文件就是本文件。**

**口径（硬规则遵守情况）**：**纯离线、纯只读**。全程**未启动/未触碰游戏或编辑器、未连桥、未发任何报文、
未注入、未提权、未重启 helper**。读取范围＝① 仓内已合入源码（`tools/editor-bridge/Adapter/*.cs`、
`tools/game-executor/native/*`）② 仓内已产出的 7.1 元数据转储 `.runtime/verification/update-repair-20260925/adapter-port/metadata-7.1.json`
③ 仓内反编译语料 `.runtime/editor-catalog/resolved/` ④ 绑定档 `EditorBindingProfile.Generated.cs`。
**未读任何图片、未读 PDF、未触碰 `LocalLow`**。本文**没有一条是本轮新跑的真机动作**；
引用的真机结论全部来自仓内既有产物，且沿用其原文的三层标注。

> **三层分标**（`CLAUDE.md` §一.3）：本文回答的是「编辑器内存模型（A 层）里**有哪些字段**、
> 我们**读没读**」。它**不**回答「游戏进程（B 层）读得到吗」或「`.gil`（C 层）写不写得出」。
> 「有字段可读」≠「有 op 在读」≠「真机读回过」——三件事分开写。

---

## 0. 一句话结论

1. **实体模型（编辑器内存里的「实体实例模型」）在 7.1 里只有一个类型**：
   `LhusWLXd5NUZ7IineV1x.o6MMsvXduEaZkjEZB6yx`（＝旧名 `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr`，
   项目内定名 **「实体实例模型」**，`tools/editor-bridge/Adapter/InterfaceVerification.cs:69`）。
   它在 metadata-7.1.json 里**自带 16 个实例字段 + 1 个静态单例**（type token `33559606`），
   另有 **3 个字段从基类继承**（key / name / 第二个 string）。
2. 把这三处（自身 + 基类 + key 结构）合起来，实体模型**可读字段面一共 ~24 个标量槽**。
3. **项目已经在读的**是这 **11 个字段**（按 §0.2 的槽算＝ **16 槽**）：key（含 id 与四个分类，5 槽）、`name`、
   `prefabId`、`templateId`（引用两层）、`nativeEntityType`、`nativeInstanceKind`、`transform`、`faction`、`tags`、
   `graph bindings`、`component 集合`（其中 bindings / component / tags / faction 各由独立 op 读）。
   **其余 8 槽没有任何 op 读（UNREAD，见 §3）。**
4. **UNREAD 的那些，7.1 符号名**（唯一标识字段所需的混淆名）**全都已知**——都在 metadata-7.1.json + 绑定档里，
   **不需要新挖符号**。要读它们，缺的是**一个读 op / 一次读 op 的字段扩展**，不是新矿。
   其**语义名**（#4/#7/#11/#15 那几个 bool/ulong/enum 到底代表什么）才需要新挖。
5. 三套词汇**不能互相顶替**：编辑器模型的字段 ≠ `.gil` 的 `(group,kind)` ≠ 原生快照的指针字段。
   本文只讲第一套。

---

## 1. 实体模型类型与它的字段（7.1）

### 1.1 类型定位（两个来源互相印证）

| 项 | 值 | 来源 |
|---|---|---|
| 7.1 类型全名 | `LhusWLXd5NUZ7IineV1x.o6MMsvXduEaZkjEZB6yx` | `metadata-7.1.json` → `types[]`，type token **33559606** |
| 旧（源 DLL）名 | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr` | `.runtime/editor-catalog/resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:33` |
| 新旧对应 | `Uf6Gwki…AooSwxiSm6Ktx99ovmnr` → `LhusWLXd5NUZ7IineV1x.o6MMsvXduEaZkjEZB6yx` | `merged-symbols-7.1.json`（键即为旧名）；`EditorBindingProfile.Generated.cs:473` |
| 可读含义 | **「实体实例模型」** | `tools/editor-bridge/Adapter/InterfaceVerification.cs:69`；`docs/editor-catalog/COMMAND-CHANNEL.md:52` |
| 源 DLL 身份 | SHA `565DDA11883F0220BAE050438FCF52B2288F26B61ED656E2B4CD6D69B41A678A`，MVID `39031639-dfe4-4ed3-9109-b21f7d4d47d1` | `metadata-7.1.json` 头部 `sha256`/`mvid` |

> 命名空间两套（`CLAUDE.md` §一.2）：**旧名**是源 DLL / 反编译语料里那套（`EditorBindingProfile` 以它为键）；
> **7.1 名**是本次元数据转储那套。**它们是同一个类型**，下文两张都列。

### 1.2 字段表 —— 实体模型自身声明的 17 项（含 1 个静态单例）

字段顺序、类型均取自 `metadata-7.1.json`（该类型条目）。"旧名"经
`EditorBindingProfile.Generated.cs`（旧→7.1 字段映射，块见 `:449-620`）与
`merged-symbols-7.1.json` 反查；"resolved 类型"来自反编译语料同名文件 `:35-67`。
7.1 里包一层 `sGSkeTXZnJ86i9h8AAF9.MoivF7XZA3MetiaLJVSU`1<…>``（＝旧 `t7crdXiRQQTsF520oNMA`1`，
见 `EntityComponentProbe.cs:32`）的字段是**可空盒子**（内层值经成员 `VpIiRZgdEln` 取出，
`EditorAdapter.cs:114-115`）。

| # | 7.1 字段 | 7.1 字段类型（metadata 原样，省略包壳前缀） | 旧字段名 | 旧/resolved 类型 | 可读含义 | 依据 |
|---:|---|---|---|---|---|---|
| 1 | `xUtXiO7bNKM` | `<UInt32>` | `TuuiS94iUgu` | `t7…NMA<uint>` | **prefabId**（编辑器 prefab 关联缓存 id，**≠** 模板 id） | 映射 `EditorBindingProfile.Generated.cs:466`；语义 `EntityCrudProbe.cs:59`、`SceneCatalog.cs:35` |
| 2 | `KlyXiZUcowl` | `<nPpGDIkpbH0sJWonhDY>` | `d4siSoaFICf` | `t7…NMA<Yw70pXJaOxHmc6AJmx7>` | **nativeInstanceKind** | 映射 `:517`；语义 `EntityCrudProbe.cs:62`、`SceneCatalog.cs:39` |
| 3 | `a9JXiwt2BMB` | `qknVfrXwms8uvpf8GYF6`1<`GL3iQaXn10FDkUwcfAJh`> | `VWmiSUsKoHr` | `XpyJGKiNEBG3qlCFJJeg<FevvcZiBkS31NrEJZJIG>` | **图/指令绑定集合**（元素＝key 结构） | 访问器 `t6ViSxlgnQ3()`（resolved `:192`）返回同型；读方 `EditorAdapter.cs:216-219`、`AuthoringGraph.cs:255-256` |
| 4 | `NxeXiL7qDbu` | `<Boolean>` | `ieUiSRMOf8n` | `t7…NMA<bool>` | **未知**（实体级 bool） | metadata 位置对齐（第 4 位）|
| 5 | `EDuXiXtiyvl` | `WupssAXLwY5NGCQQMQWk`1<`CF9E4JXdL1Cq4xrMUnCq`> | `mUwiSNg4POZ` | `rgfCjhijuAbCoKxWU8Lu<LudM06iCRNk4iFkwqKIW>` | **组件集合**（自定义盒子；＝组件探针读的那个） | 证据 **逐字**：`EntityComponentProbe.cs:26,82`（`EntityComponentsField71="EDuXiXtiyvl"` // `mUwiSNg4POZ`）；访问器 `WlJiSPfnM3R()`（resolved `:204`） |
| 6 | `jCoXijaafFn` | `<OEMSxbZOTRB79YVvftOi>` | `yEpiSj6okKa` | `t7…NMA<H5TMMg0CxiWnygX8CxTA>` | **nativeEntityType**（原生实体类型 int，如 1402） | 映射 `:620`；语义 `EntityCrudProbe.cs:61`、`SceneCatalog.cs:38` |
| 7 | `nkOXiQRtf1u` | `<CAo8WOZZGKMTDVh419Py>` | `bERiSFg7R4x` | `t7…NMA<mQINCW0SOmRDiyoCN1P3>` | **未知**（单成员 enum `{Normal}`） | enum 定义 `resolved/cqIGF60SbUZZUlB1y3qT.mQINCW0SOmRDiyoCN1P3.cs:3-5` |
| 8 | `fWOXipCuep7` | `<Boolean>` | `XTniS6sCvat`（私有） | `t7…NMA<bool>` | **isStatic**（是否静态实例） | 属性 `isStatic => zkBiU2ieGW3(ref XTniS6sCvat)`（resolved `:69`）；语义串见 §3 |
| 9 | `wCGXiPk8NaS` | `<UInt32>` | （同名，未改） | `t7…NMA<uint>` | **faction**（阵营标量 id） | 读方 `EntityFactionProbe.cs:114`（`FactionUInt(model,"wCGXiPk8NaS")`） |
| 10 | `K07Xiow3cj5` | `qknVfrXwms8uvpf8GYF6`1<Int32> | （同名，未改） | `XpyJGKiNEBG3qlCFJJeg<int>` | **tag 列表**（`List<int>`） | 读方 `AuthorEntityTag.cs:19,52,98`（`TagListField71="K07Xiow3cj5"`） |
| 11 | `mrpXiMmBqdO` | `System.UInt64` | `BrtiSc6Q31e` | `ulong`（public） | **未知**（64 位标量，疑 guid/句柄） | metadata 位置对齐（第 11 位）+ resolved `:55` |
| 12 | `JN6Xiq5xY5w` | `Il0skBXtyrT6xmowkYLq` | `dmhiSVca7Ew` | `aFinWDitDOKnKOyy0MEx`（public） | **模板引用对象**（templateId 在它里面，见注解） | 映射 `:474`；读方 `SceneCatalog.cs:52-55` |
| 13 | `XRnXi7Pkm5q` | `<Il0skBXtyrT6xmowkYLq>` | `OeAiSZXxbE3` | `t7…NMA<aFinWDitDOKnKOyy0MEx>` | **模板引用（可空缺的兄弟槽）** | metadata 位置对齐（第 13 位） |
| 14 | `keVXiadWtLM` | `BeyondEditor.BaseUtil.Transform` | `hTjiSreIlqL` | `Transform`（public） | **transform**（编辑器 registry 的变换缓存） | 映射 `:546`；读方 `SceneCatalog.cs:18,40`、`EntityTransform.cs:35,122`、`EntityCrudProbe.cs:120` |
| 15 | `vQ5XiGe42rx` | `System.Boolean` | `CcliSJ46bRG` | `bool`（public） | **未知**（实体级 bool） | metadata 位置对齐（第 15 位）+ resolved `:63` |
| 16 | `W8QXivS0WCh` | `List`1<`CF9E4JXdL1Cq4xrMUnCq`> | `JdaiSnpkbfl` | `List<LudM06iCRNk4iFkwqKIW>`（public） | **组件 List（第二个视图）** | resolved `:65`；与 #5 同一元素类型（组件模型） |
| 17 | `u4KNPmNUr40vQF60jYYG` | 本类型（**static**） | `nY4yNLW0nNe0yheKk0t7` | 本类型（internal static） | **单例**（非 per-entity） | metadata `isStatic:true`；resolved `:67` |

**注解（#12 templateId 的两层读法）**：`SceneCatalog.cs:37` 读的是「引用对象上的字段」——
先读实体模型的引用对象（旧 `dmhiSVca7Ew`→7.1 `JN6Xiq5xY5w`），再读该对象上的 id
（旧 `pgfitPOV3oW`→7.1 `c9hXtzxPgoq`，映射 `EditorBindingProfile.Generated.cs:474-475`）。
即 **#12 是「模板引用」而非「模板 id」本身**，id 在它指向的对象里（`SceneCatalog.cs:52-55` 原文即此）。

### 1.3 继承字段（来自基类）

基类（旧 `MmGS7KiCtuJtGKBgib1k.KRXnqSiC20Pj6d7V6Cdv`，见
`resolved/MmGS7KiCtuJtGKBgib1k.KRXnqSiC20Pj6d7V6Cdv.cs:19`）在 7.1 里是
`ybERMnXd11A7wZuwCS2d.gdeT09XdALXSXo3bfTKb`（该 7.1 名由绑定档 + 字段归属确证：`xVGXdUihBZU`/`hCRXdTksET3`
都挂在该类型下，`EditorBindingProfile.Generated.cs:759,792`）。

| 7.1 字段 | 7.1 类型 | 旧字段名 | 旧类型 | 可读含义 | 依据 |
|---|---|---|---|---|---|
| `xVGXdUihBZU` | `<GL3iQaXn10FDkUwcfAJh>` | `Qi8iCzKCkTt` | `t7…NMA<FevvcZiBkS31NrEJZJIG>` | **实体 key**（身份四元组 + id） | 映射 `:449`；读方 `EntityCrudProbe.cs:35` |
| `hCRXdTksET3` | `<String>` | `WAAiS5WkxlA` | `t7…NMA<string>` | **name**（显示名） | 映射 `:484`；语义 `EntityCrudProbe.cs:58`、`SceneCatalog.cs:34`、`EntityComponentProbe.cs:163` |
| `hy6Xdfgs3dP` | `<String>` | `fgTiSaALpLs` | `t7…NMA<string>` | **未知**（第二个 string，疑路径/guid/图标） | 基类 resolved `:25`，访问器 `K9riCkxbmcs()`（`:258-261`） |

### 1.4 key 结构自身（身份字段的落点）

key 的 7.1 类型是 `DFG6S3XnnydlOvbTtokr.GL3iQaXn10FDkUwcfAJh`（旧 `GUBpyqiBIBId7w2tTBhp.FevvcZiBkS31NrEJZJIG`），
5 个 uint：

| 7.1 字段 | 旧字段名 | 可读含义 | 依据 |
|---|---|---|---|
| `zUrXNpgNbru` | `oLyiwZX255H` | category0 | 映射 `EditorBindingProfile.Generated.cs:572`；`EntityCrudProbe.cs:36` |
| `ljuXNPHDWuo` | `AwbiwrjxUDX` | category1 | `EditorBindingProfile.Generated.cs:375`（契约 `:689`）；`EntityCrudProbe.cs:36` |
| `zD5XNoXAY21` | `UFWiwJNegmh` | category2 | `EditorBindingProfile.Generated.cs:470`（契约 `:780`）；`EntityCrudProbe.cs:37` |
| `uuxXNMw0jW4` | `RBTiwn649Hy` | category3 | `EditorBindingProfile.Generated.cs:451`（契约 `:761`）；`EntityCrudProbe.cs:37` |
| `L0kXNqYb39f` | `namiwGPRyPS` | **id**（也写作 `id` 属性） | 映射 `:568`；resolved `:27,31`；`EntityCrudProbe.cs:37` |

---

## 2. 交叉表：字段 → 谁在读（file:line）→ 或 UNREAD

read 方＝**已合入树内**的 op（读半）。「真机读回」一列按仓内既有标注照抄，**不因"有读方"就写"真机通了"**。

| 字段（7.1 / 旧） | 语义 | 读方（file:line） | op | 真机读回？ |
|---|---|---|---|---|
| `xVGXdUihBZU` / `Qi8iCzKCkTt`（key） | 身份 | `EntityCrudProbe.cs:35`；`EditorAdapter.cs:118,150`；`SceneCatalog.cs:24` | `catalog` / `inspect-entity-crud-probe` | 有（`Resources()` 走通） |
| key.`L0kXNqYb39f` / `namiwGPRyPS`（id） | id | `EntityCrudProbe.cs:37`；`EditorAdapter.cs:119,150` | 同上 | 有 |
| key.cat0–cat3 | 分类四元组 | `EntityCrudProbe.cs:36-37`；`AuthorEntityTag.cs:78-80` | 同上 | 有 |
| `hCRXdTksET3` / `WAAiS5WkxlA` | name | `EntityCrudProbe.cs:58`；`SceneCatalog.cs:34`；`EntityComponentProbe.cs:163`；`EditorAdapter.cs:149` | `catalog` / `crud` / `inspect-entity-components` | `catalog`/`crud` 有；组件探针**无**（见 §5） |
| `xUtXiO7bNKM` / `TuuiS94iUgu` | prefabId | `EntityCrudProbe.cs:59`；`SceneCatalog.cs:35` | 同上 | 有 |
| `JN6Xiq5xY5w` / `dmhiSVca7Ew` + `c9hXtzxPgoq` / `pgfitPOV3oW` | templateId（两层） | `SceneCatalog.cs:37,52-55` | `catalog` | 有 |
| `jCoXijaafFn` / `yEpiSj6okKa` | nativeEntityType | `EntityCrudProbe.cs:61`；`SceneCatalog.cs:38` | 同上 | 有 |
| `KlyXiZUcowl` / `d4siSoaFICf` | nativeInstanceKind | `EntityCrudProbe.cs:62`；`SceneCatalog.cs:39` | 同上 | 有 |
| `keVXiadWtLM` / `hTjiSreIlqL` | transform | `SceneCatalog.cs:18,40`；`EntityTransform.cs:35,122`；`EntityCrudProbe.cs:120` | `catalog` / `entity-transform`(inspect) / `crud` | 有（读半） |
| `wCGXiPk8NaS` | faction | `EntityFactionProbe.cs:114` | `inspect-entity-faction-probe` | **无**（探针未真机跑） |
| `K07Xiow3cj5` | tags | `AuthorEntityTag.cs:19,52,98` | `author-entity-tag`(inspect) | **无** |
| `a9JXiwt2BMB` / `VWmiSUsKoHr` | 图绑定 | `EditorAdapter.cs:216-219`；`AuthoringGraph.cs:255-256`；`ReopenContentEvidence.cs:170` | `catalog` / `graph inspect` / `inspect-reopen-content` | 有（`graph inspect` 已读回） |
| `EDuXiXtiyvl` / `mUwiSNg4POZ` | 组件集合 | `EntityComponentProbe.cs:26,82` | `inspect-entity-components` | **无**（读半已接线、已编译，未真机跑；见 §5） |
| `W8QXivS0WCh` / `JdaiSnpkbfl` | 组件 List（第 2 视图） | **UNREAD** | — | — |
| `NxeXiL7qDbu` / `ieUiSRMOf8n` | bool | **UNREAD** | — | — |
| `nkOXiQRtf1u` / `bERiSFg7R4x` | enum{Normal} | **UNREAD** | — | — |
| `fWOXipCuep7` / `XTniS6sCvat` | isStatic | **UNREAD**（基类有 `isStatic` 属性，无 op 输出） | — | — |
| `mrpXiMmBqdO` / `BrtiSc6Q31e` | ulong | **UNREAD** | — | — |
| `XRnXi7Pkm5q` / `OeAiSZXxbE3` | 可空缺模板引用 | **UNREAD** | — | — |
| `vQ5XiGe42rx` / `CcliSJ46bRG` | bool | **UNREAD** | — | — |
| `hy6Xdfgs3dP` / `fgTiSaALpLs` | string | **UNREAD** | — | — |
| `u4KNPmNUr40vQF60jYYG` | 静态单例 | 非 per-entity，不适用 | — | — |

### 2.1 原生快照（game-executor）——**不同一层，不是这些字段**

`scene_cli inspect` 读的是**游戏进程**里实体字典的条目（B 层），结构体
`GameEntitySnapshot`（`tools/game-executor/native/game_context_snapshot.h:78-84`）：

| 快照字段 | 类型 | 读什么 | 依据 |
|---|---|---|---|
| `owner, config, context` | `uint64` ×3 | 三个运行时指针 | `:79` |
| `dictionaryKey, id, configId, flags` | `uint32` ×4 | 字典键 / 实体 id / configId / 标志位 | `:80` |
| `position[3]` | `float` ×3 | **从不置位**（无已证位置偏移） | `:81`（`GE_POSITION_READ is never set`） |
| `reserved, reserved2` | `uint32`/`uint64` | 保留 | `:82-83` |

⇒ 原生侧**只有 id / configId / 标志位**，**没有任何编辑器模型字段**（没有 name/prefab/template/faction/tag/组件）。
这是**结构性负结论**：B 层不是 A 层的替代读法。

---

## 3. UNREAD 字段各自会补上什么

| 字段 | 补上 | 置信 |
|---|---|---|
| `W8QXivS0WCh` / `JdaiSnpkbfl`（`List<组件>`） | 组件集合的**第二个视图**——一个**纯 BCL `List<>`**（无需自定义枚举器），可与 #5 的盒子视图**互校**；若两者不一致即是「模型半填/序列化在途」的证据 | 已证字段存在；"两视图一致"未验 |
| `fWOXipCuep7` / `XTniS6sCvat`（isStatic） | **静态 / 动态实例**判别——能把「场地装饰（静态）」与「运行时刷出的实例（动态）」分开。反编译里 `resourceItemTextType` 正用它分派串 `…DEFAULT_FILTER_STATIC_INSTANCE` / `…DEFAULT_FILTER_DYNAMIC_INSTANCE`（`resolved/…AooSwxiSm6Ktx99ovmnr.cs:84-94`） | 高（语义有串佐证） |
| `XRnXi7Pkm5q` / `OeAiSZXxbE3`（可空缺模板引用） | 模板引用的**有无**（`null` vs 有值）——单看 #12 的 id 只是读到 id，读这个才能判断"压根没绑模板" | 中 |
| `nkOXiQRtf1u` / `bERiSFg7R4x`（enum{Normal}） | 实体的**来源/投放类别**判别。反编译里同族字段比较值 `2` 时返回串 `…BLUEPRINT_MANAGER_DROP_OFFICIAL`（`resolved/…AooSwxiSm6Ktx99ovmnr.cs:90-92`），提示它区分「官方投放 vs 普通」 | 低（枚举只解出 `Normal`，与其他值的映射未建） |
| `mrpXiMmBqdO` / `BrtiSc6Q31e`（`ulong`） | 一个**比 uint id 更宽的标量**——疑为稳定句柄 / guid / 时间戳。若能确认是稳定 id，可补「uint id 之外的跨会话标识」 | 低（纯形状推断） |
| `NxeXiL7qDbu` / `ieUiSRMOf8n`（bool）、`vQ5XiGe42rx` / `CcliSJ46bRG`（bool） | 两个实体级布尔开关（语义未挖）。可能对应「锁定/隐藏/可用」一类；未命名前只是"多两个 bool" | 低 |
| `hy6Xdfgs3dP` / `fgTiSaALpLs`（string） | 第二个字符串——疑为**路径 / guid / 图标**，可补 name 之外的文本身份 | 低 |
| key 的 cat0–3 | **已读**（`EntityCrudProbe.cs:36-37`），无需补 | — |

---

## 4. 判定：哪些要「新探针」、哪些「现有原语今天就能读」

**关键前提**：以上**每个 UNREAD 字段的 7.1 符号名都已知道**（全部在 `metadata-7.1.json` 里，
大多数还在 `EditorBindingProfile.Generated.cs` 里有旧→7.1 映射）。所以：

- **不需要「新矿」（新符号）**：没有任何一个字段需要重新反射/再解一个偏移才能**定位**。
  定位所用的原语**已经存在**——`ReadCrudEntities()`（`EntityCrudProbe.cs:40-74`）已经在遍历注册表并解析出实体模型对象，
  读一个同型字段只是「再取一个字段名」（会走一次盒子解包 `VpIiRZgdEln`，`EditorAdapter.cs:114-115`）。
- **需要「新 op」的是**：**没有任何 op 把这些字段输出出去**。要拿到它们，得
  **新增一个读 op**，或**在既有读 op 的输出里加字段**（后者更省——例如把 `isStatic`/`ulong` 加进
  `inspect-entity-crud-probe` 的 `CrudEntityEvidence`，`EntityCrudProbe.cs:116-120`）。

| 字段 | 定位原语 | 是否需新符号 | 读它需什么 |
|---|---|---|---|
| `W8QXivS0WCh`（`List<组件>`） | **今天就有**：`ComponentModelContract` 只差换一个字段名（`EntityComponentProbe.cs:64-96` 的 `Exact(...)` 惯用法原样可用） | 否 | 扩组件探针输出一项（或新 op） |
| `fWOXipCuep7`（isStatic） | 今天就有（registry walk 已到模型） | 否 | 扩 `crud` 输出 |
| `XRnXi7Pkm5q` / `NxeXiL7qDbu` / `nkOXiQRtf1u` / `mrpXiMmBqdO` / `vQ5XiGe42rx` / `hy6Xdfgs3dP` | 今天就有 | 否（**可读**） | 扩 `crud` 输出；**但语义命名需新挖**（见 §3 低置信项） |
|（对照）`K07Xiow3cj5`（tags） | 已有专门 op `author-entity-tag` | — | 已读（未真机） |
|（对照）`wCGXiPk8NaS`（faction） | 已有专门 op `inspect-entity-faction-probe` | — | 已读（未真机） |

**一句话**：**全部 8 个 UNREAD 字段都不需要新矿，只需要把已有的「拿到实体模型对象」这一步后面
再读一个同名/同型字段，并把它接到某个 op 的输出里。** 真正要新挖的只有**其中 4 个的语义**
（`NxeXiL7qDbu` / `nkOXiQRtf1u` / `mrpXiMmBqdO` / `vQ5XiGe42rx` 各是"干什么用的"）。

> **反例校准**（防过度声称）：`isStatic` 虽然字段名已知、模型可达，**但"今天就能读"指的是"读**得**到字节"，
> 不是"已经有 op 在读、且真机读回过"**。当前**零** op 输出它——这是本文说它 UNREAD 的意思。

---

## 5. 必须分离的保留（不许写成"已一致"）

1. **组件读写两套词汇未打通**（沿用仓内既有标注，不重述结论）：`.gil` 侧的 `(group,kind)` 组件 wrapper
   （`tools/beyond-save/entity_geometry.py`，模块头「no public name is asserted」）与**编辑器模型侧**的
   组件模型 `tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq`（旧 `LudM06iCRNk4iFkwqKIW`，`EntityComponentProbe.cs:27`）
   之间**没有任何文档打通**。本文 §2 里「组件集合」读方指的是**后者**。
2. **读半已接线 ≠ 真机读回**：`inspect-entity-components` 的读半已编译进当前 payload dll 并在
   `BridgeServer` 有 dispatch，但**本任务禁发报文**，故该 op 的**真机读回在本任务内为零证据**
   （`CLAUDE.md` §五；`EntityComponentProbe.cs:14-21` 亦自述其成员名取自 7.1 转储）。
3. **`merged-symbols-7.1.json` 是子集**（250 条），只覆盖**值成员**（字段/方法），**不覆盖类型名**。
   故上文类型新旧对应用了 `EditorBindingProfile.Generated.cs`（`:473`）与字段归属双重确证；
   `DFG6S3X…` / `ybERMnXd…` 两个 7.1 类型名同样由**字段归属**（`:689,761,780,792,759`）确证，非来自 mapping 表。
4. **字段位置对齐是推断链**：第 4/7/11/13/15 号字段没有经 `merged-symbols` 的旧名映射，其"旧名"
   由 **metadata 字段顺序 + 类型形状 + resolved 语料同序字段**三者对齐得到。该链**自洽**
   （1/2/5/6/12/14 号字段已被独立确证，锚定了整个顺序），但 4/7/11/13/15 本身**未见逐字段确证**，
   标为**推断（高）**。凡确证项均在表中给了 `file:line`。
5. **未读 `.runtime` 下未合入副本**（本工程已知暗角：`.runtime` 里存着未合入候选）。"未找到/未读"
   永远只说"**本次检索范围内**"。

---

## 6. 复现（全部只读，无进程、无报文、无写入）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


同目录其它只读佐证：`tools/beyond-save/entity_geometry.py`（`.gil` 侧，另一套词汇）、
`tools/game-executor/native/game_context_snapshot.h:78-84`（原生快照，另一层）。
