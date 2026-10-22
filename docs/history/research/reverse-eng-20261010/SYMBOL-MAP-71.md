> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# SYMBOL-MAP-71 — 7.0 → 7.1 符号映射（离线，给定旧名 → 新名或 unknown）

> 纯离线静态工作。**没有碰游戏/编辑器，没有发任何 bridge/native 请求，没有读任何图片或 PDF。**
> 产物：`tools/editor-catalog/symbol-map-71.py`（脚本）、`tools/editor-catalog/tests/test_symbol_map_71.py`（测试）。
> 任务 #6。

符号名在两版之间被**重新随机化**：本工程记录的全部类知识用的是 7.0（legacy）名，而装机编辑器是 7.1。
本文件把"给一个 7.0 符号名，回答它的 7.1 等价名，或 `unknown`"这件事固定下来，**绝不猜测**。

---

## 0. 结论先给

1. 现成的地图是 `.runtime/verification/update-repair-20260925/adapter-port/merged-symbols-7.1.json`：
   **扁平 `{str: str}`，250 条，0 条恒等映射**。形状：204 个不带点的键（类型短名或成员叶名）+ 46 个带点的键（`命名空间.类型` 全名）。
2. **没有任何在树脚本写出这个文件**。全仓 grep（含任何扩展名）里只有 `integrate_profile.py` **读**它，
   没有脚本**写**它 —— 它是候选管线产出后**人工定稿**的合辑。见 §2。
3. 脚本 `symbol-map-71.py` 只做**精确整串匹配**：命中给新名，未命中给 `unknown` + `new=null`；
   前缀/后缀/子串相似键只在 `nearMisses` 里**列出供人看，绝不作为答案**返回。测试 28 项全过。
4. 项目关心的 5 个符号，在这张定稿地图上**全部 `unknown`**（它们不是 Adapter 的反射绑定）。
   其中「组件模型类型」在**另一条（未定稿）**结构候选管线里有配对，见 §4 —— 标注清楚，不混入地图答案。

---

## 1. 地图的形状

`merged-symbols-7.1.json` = 一个 JSON 对象，键和值都是字符串：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- 条目数：**250**；值类型全部 `str`；`old == new` 的恒等条目：**0**。
- 键分两类（对 7.0 侧语料 `.runtime/editor-catalog/resolved/` 与候选表核对得到）：
  - **204 个不带点**：145 个是成员**叶名**（方法/字段，如 `G9oiCBkSaYQ`），59 个是类型短名（多为手动绑定条目）。
  - **46 个带点**：44 个是结构候选里出现过的**类型全名**（`命名空间.类型`），另 2 个来自父级独立结构候选。
- **没有 `类型.成员` 这类成员限定键**——成员一律以**叶名**存放。这是它与"消费者"约定的形态：
  `integrate_profile.py` 拿到值后，去 7.1 的 PE 元数据里按**类型全名**或**成员叶名**反查契约。

## 2. 谁产出了它（生成器溯源）

逐个脚本查证后的管线（全部在 `adapter-port/` 内）：

| 环节 | 文件:行 | 产出 |
|---|---|---|
| 类型排序候选 | `match_decomp.py:84` | `type-ranking.json`（仅排序，`rankingOnlyNotVerified:true`） |
| 结构/成员配对 | `relate_members.py:138-147` 组装、`:148` 落盘 | `structural-binding-candidates.json`（`candidateOnly:true`），内含 `types`/`members`/`neededCandidates` |
| 人工复核类型 | `manual-bindings.json` | 21 个 `symbols` + 8 个 `types` |
| 追加候选 | `extra-binding-candidates.json` | 13 个 `matches` |
| **定稿合辑** | —— **树内无写入脚本** —— | `merged-symbols-7.1.json`（250） |
| 消费者/失败关闭 | `integrate_profile.py:5` 读地图、`:9-26` 逐值对 PE 元数据求契约并 `assert not unresolved`、`:63` 写 `binding-manifest-7.1.json`、`:62` 生成 `EditorBindingProfile.Generated.cs` | —— |

**定稿合辑的来源构成**（用集合运算核对）：
- `relate_members.py` 的 `neededCandidates` 216 条 ∪ `manual-bindings.symbols` 21 条 ∪ `extra-binding-candidates.matches` 13 条 = **246 条**，
  **全部 ⊆ 250**，缺 0；其中 **212 条**直接来自 `neededCandidates`（既不在 manual 也不在 extra）。
- 250 中另有 4 条在该并集之外（含别名类型 `gOTkLGae2aX1iLOIhHQU.ULcU3FaeSaW8mUS8GDgi`，消费者在 `integrate_profile.py:12-13` 对它做了单列的 `ULcU3FaeSaW8mUS8GDgi` 别名特判；`:6` 另补了 `AwbiwrjxUDX` 一条）。
- 至少 **10 个键的值与 `neededCandidates` 原值不同** ⇒ 定稿时被人**改过**，不是机械并集。

⇒ 一句话：**没有单一的"生成脚本"**。`merged-symbols-7.1.json` 是"候选产出 + 人工定稿"，写入脚本未保留；
树内能指到的是它的**候选来源**（`relate_members.py`）和它的**消费者**（`integrate_profile.py`）。

## 3. 脚本用法

`tools/editor-catalog/symbol-map-71.py`，离线，只读一个 JSON：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）



（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


API：`lookup(old)` 精确；`lookup_type(full)` 同义；`attempt_member_lookup(owner, member)` 依次试**精确**的
`owner.member` 与叶名 `member` 两个键（都不做模糊）；`lookup_many(list)`。
非字符串查询抛 `SymbolMapError`；地图结构非法（非 `{str:str}`）在加载期抛 `SymbolMapError`。

**测试**（`tests/test_symbol_map_71.py`，28 项，全离线合成地图）证明：
- 精确命中（类型全名 / 成员叶名 / 短类型名 / 恒等）都正确；
- `unknown` 一定 `new is None`；
- **拒绝**：键的前缀、后缀、超长串、别的 owner 限定、给叶名硬造限定，全部 `unknown`；
  `nearMisses` 只列相似键、**永不**作为答案（`test_near_misses_are_never_the_answer`）。

## 4. 应用到项目关心的符号

7.0 名与出处：

| # | 角色 | 7.0 符号 | 出处（file:line） |
|---|---|---|---|
| 1 | 组件面板（行）VM 类 | `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW` | `.runtime/editor-catalog/resolved/pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs:14`（`docs/research/reverse-eng-20261010/ADD-COMPONENT-TRACE.md:55`「组件列表行 VM」） |
| 2 | 组件模型类型 | `taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW` | `.runtime/editor-catalog/resolved/taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW.cs:9`（`COLLISION-COMPONENT-ID.md:83`「组件模型类型」） |
| 3 | 组件列表 VM #1 | `LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN` | `resolved/…UY3FwAuuVnr6w8n0v5kN.cs`（`ADD-COMPONENT-TRACE.md:83`） |
| 4 | 组件列表 VM #2 | `yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ` | `resolved/…TDKVvfuuIslakGU226IJ.cs`（`ADD-COMPONENT-TRACE.md:84`） |
| 5 | 删除处理器 | `s9puu4bEcx2`（#1 上的方法） | `resolved/…yn34VuuuO5tEgsICYDBW.cs:93`（`ADD-COMPONENT-TRACE.md:63,267`） |

**地图判决（`python tools/editor-catalog/symbol-map-71.py …` 原样输出）**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


5 个符号 `nearMisses` 均为空（连子串相似键都没有）⇒ 地图里确实**没有**它们，且工具不会瞎凑。
原因清楚：这张地图是 **Adapter 反射绑定**的定稿集，而这 5 个是**编辑器前端/授权 VM**，从不经过 Adapter 绑定。

**地图外的旁证（明确标注，不是地图答案）**：#1/#3/#4/#5 在 7.0↔7.1 结构候选里也**没有**配对；
但 **#2 组件模型类型**在**未定稿**的结构候选里有一条配对：

| 源 | 文件:行 | 结论 |
|---|---|---|
| 结构候选（`candidateOnly:true`，**非**地图） | `structural-binding-candidates.json` → `types["taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW"] = "tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq"`（`relate_members.py:100,148` 由宿主实体字段布局同序推得） | 7.1 名：`tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq` |
| 独立文档复核 | `docs/research/reverse-eng-20261010/ASSET-MEASURE-MINE.md:60`、`COLLISION-COMPONENT-ID.md:83` | 同上一致 |

⇒ 该模型类型**有**7.1 名，但它**不在这张定稿地图里**。脚本对它的地图判决仍是 `unknown`——
这是正确行为（不越权把候选当定稿），要用这条配对必须走结构候选管线并接受其 `candidateOnly` 性质。

## 5. 边界与诚实声明

- 本地图**只覆盖 Adapter 用到的反射符号**（250/307 里的 legacy 侧）。它与编辑器前端/授权 VM 无关，
  所以对上面 5 个前端符号一律 `unknown` 是**预期结果**，不是地图缺陷。
- 值的方向是 `7.0 → 7.1`。反查（7.1 → 7.0）不在本脚本内；地图值**不是**双射保证，
  唯一性由消费者 `integrate_profile.py:26` 的 `assert not unresolved` 兜底。
- 精确匹配是**刻意**的保守：宁可 `unknown`，也不给相似名。任何"最接近匹配"都必须由人复核后
  走独立证据链（如 §4 的结构候选），**不得**由本脚本自动返回。
- 一切只读。未接触游戏进程、编辑器、存档或任何二进制；未发任何 bridge/native 请求。
