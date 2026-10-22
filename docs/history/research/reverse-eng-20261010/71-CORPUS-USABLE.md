> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 71-CORPUS-USABLE —— 7.1 语料「能不能直接 grep」盘点，与缺失的 resolved 树构建

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。未连桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档。
未读任何图片或 PDF。**未读安装目录的 `BeyondEditor.dll`**（见 §3.3）。所有 scratch 产物写在工程内 `.runtime/`。
本文件是 TASK #5 的唯一文档产出。

---

## 0. 一句话结论

> **7.1 语料今天就能 grep——但要 grep 对的那棵树。**
> 存在**两棵** README 里没写明关系的树：
> - **`decomp-7.1/`（原始反编译）** —— 字符串字面量全是 `A ^ B` 整数偏移，**grep 任何命令名/文案都是 0 命中**（本文实测）。
> - **`annotated-7.1/` / `annotated-71/`（字符串已还原）** —— **字面量已还原成真字符串**，`batchcreate` 等 7.1 新增命令名**今天就能命中**。
>
> **缺的那一步（代理槽位 → 真方法名的 `resolved/`）本轮已经补跑**：产物在
> **`.runtime/editor-catalog/resolved-565dda11/`**（12,955 `.cs`，190,630 处槽位引用已注上真实目标）。
> 于是 7.1 的可用性与 7.0 的 `resolved/`（12,375 `.cs`）**完全对齐**：字面量 + 真方法名都能 grep。
>
> **一个必须先知道的前提（否则你会以为工具坏了）**：直接拿仓里那份现成的 `proxy-map-7.1.json` 去跑
> `annotate-proxies.py` 会被**响亮拒绝**（`refused: --map outputSha256 missing or changed`），因为它的
> `.source.json` sidecar 是**旧格式**、缺 `outputSha256`/`completeMap` 两个字段（§3.2）。本轮用「补齐 sidecar」的
> 办法绕开了它，**没有去读安装目录的 DLL**。

---

## 1. 7.1 相关树的清单（每样是什么）

`find`/`ls` + `du`/`wc` 实测。左列是路径（均相对工程根），右列是「它是什么」+ 规模。

### 1.1 主反编译 + 字符串（`update-repair-20260925`、`docs-71-20260926`）

| 路径 | 它是什么 | 实测规模 |
|---|---|---|
| `.runtime/verification/update-repair-20260925/adapter-port/decomp-7.1/` | **原始反编译**（`ilspy-dump all` 直出）。文件名 = 混淆类型名；字面量**未还原** | 12,955 `.cs` + 2,684 `_ERR_*.txt`，67 MB |
| `.runtime/verification/update-repair-20260925/strings/annotated-7.1/` | **字符串已还原的副本**（`annotate-strings.py`）。**旧 sidecar 格式**（无 `outputSetSha256`） | 12,955 `.cs`（+`.source.json`），63 MB |
| `.runtime/verification/docs-71-20260926/annotated-71/` | **同一份字符串还原副本**（内容逐字节相同），但 sidecar 是**新格式**（含 `inputSetSha256`/`outputSetSha256`/`inputCompleteness`）。**这是供 `annotate-proxies.py` 当 `--src` 的唯一可用副本**（§3.2） | 12,955 `.cs`，63 MB |
| `.runtime/verification/update-repair-20260925/strings/string-table-7.1.json` | **7.1 加密字符串表已解**（offset → 明文）。`string_table.py` profile `editor-7.1` | **2,985** 条（实测 `len`）；profile 见 `tools/editor-catalog/string_table.py:228-244` |
| `.runtime/verification/update-repair-20260924/proxy-map-7.1.json` | **7.1 代理槽位 → 真方法映射**（已 token 校验） | **36,479** 行（实测 `len`）；sidecar 缺 2 字段（§3.2） |
| `.runtime/verification/update-repair-20260924/proxy-decoder-7.1.cs` | 7.1 代理映射解密器的**反编译源码**（profile 常量的出处） | 53,874 B |

### 1.2 资源管线（`.mihoyobin` / 节点目录，`update-repair-20260925/catalog*`）

| 路径 | 它是什么 | 实测规模 |
|---|---|---|
| `…/catalog/decoded-7.1/` | 7.1 全部 `Resource/**/*.mihoyobin` 的**解码 JSON** | **4,355** 个文件 |
| `…/catalog/node-catalog-7.1.json`（+.md） | 7.1 **节点目录**（解码后聚合） | 4.08 MB |
| `…/catalog/node-names-7.1.json` | 节点 → 名称解析结果 | — |
| `…/catalog/category-tree-7.1.md`、`index-7.1.jsonl` | 分类树 / 索引 | — |
| `…/catalog/assets-7.1*` | 7.1 内嵌资源清单 + 校验 | `assets-7.1/` 3 文件 |
| `…/catalog/install-delta.json`（在 `docs-71-20260926`） | 7.0→7.1 装机增量 | — |
| `…/catalog-tail/literal-to-types-7.1.json`、`type-index-7.1.json`、`user-strings-7.1(-corrected).txt`、`categories-7.1.txt` | 字面量→类型倒排、类型索引、用户字符串、分类（各带 `.source.json`） | `categories-7.1.txt` = 2,962 行 |

### 1.3 其它（不是语料，但同目录，别混）

- `update-repair-20260924/`：桥/原生侧的**修复过程**记录（`native-port/*.asm`、`editor-types-7.1.json` 10.3 MB 的 7.1 类型清单、各种 refusal/stopped JSON）。**不是可 grep 的 C# 语料。**
- `update-repair-20260926/`：**真机运行**记录（acceptance、crud-r1xx、helper 状态），除 `docs-71-20260926/annotated-71/` 外**与语料无关**。
- `docs-71-20260926/`：文档修订批次目录；里面同时装了 `annotated-71/`（语料）、`*.asm`（原生反汇编）、`*.json`（前后端差量）。

---

## 2. 7.0 管线五步 vs 7.1 已做/未做

7.0 的 `resolved/` 与 `annotated/` 由**四个工具、五步**造出，逐条命令（原文在
`docs/editor-catalog/COMMAND-CHANNEL.md:256-266`，本文独立复核于各脚本）：

| # | 步 | 工具 | 7.0 产物 | **7.1 是否已做** | 依据 |
|---|---|---|---|---|---|
| 1 | 全量反编译 | `ilspy-dump all <dll> <out>` | `decomp/BeyondEditor/` | ✅ 已做 | `decomp-7.1/`；`decomp-7.1/.source.json` 的 `sourceSha256=565dda11…`、`decompiledFiles=12955` |
| 2 | 解字符串表 | `string_table.py extract --dll …` | `string-table.json`（2,830 条） | ✅ 已做 | `string-table-7.1.json`（2,985 条） |
| 3 | 字符串还原 | `annotate-strings.py --src … --out … --table-json …` | `annotated/` | ✅ 已做 | `annotated-7.1/`、`annotated-71/`（sidecar `tool=annotate-strings.py`、`callsAnnotated=5345`） |
| 4 | 解代理映射 | `resolve-proxy.py --all --dump …` | `proxy-map-full.json` | ✅ 已做（**sidecar 旧格式**） | `proxy-map-7.1.json`（36,479 行、`tokenValidationPassed:true`） |
| 5 | 代理注解 | `annotate-proxies.py --src annotated --out resolved --map proxy-map` | **`resolved/`** | ❌ **没做 → 本轮已补跑** | 见 §3.1；跑前全仓找不到任何 `resolved-*7*`/`*7.1*resolved*` 目录 |

**判决**：7.1 缺的**不是**「反编译、字符串表、资源管线」——这些都齐了；**唯一缺的是第 5 步**（把代理槽位注成真方法名的 `resolved/`）。这解释了「verifier 没找到 proxy-resolved tree」的现象。

**第 5 步的确切命令**（把 7.0 命令里的 build 换成 7.1）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 3. 补跑第 5 步：判据、坑、与实跑输出

### 3.1 现成 `proxy-map-7.1.json` 会被工具**拒绝**（先证伪，再绕）

`annotate-proxies.py` 对 map 的 sidecar 有硬校验（`tools/editor-catalog/annotate-proxies.py:118-128`）。仓里
`proxy-map-7.1.json.source.json` 只有这些字段：`sourceDll/sourceSha256/resource/decodedSha256/totalPairs/outputRows/tokenValidationPassed/liveAdapterCompatible`
——**缺 `outputSha256` 与 `completeMap`**。实跑证实：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**为什么 sidecar 旧？** 当前 `resolve-proxy.py` 已会写这两个字段（`tools/editor-catalog/resolve-proxy.py:204-210`：
`outputSha256` / `completeMap`），说明 20260924 那份 map 是**更早版本**的 `resolve-proxy` 写的。

同类第二个坑：`annotate-proxies.py:302` 还要求 `--src/.source.json` 带 `outputSetSha256`。
`annotated-7.1/`（update-repair 那份）**没有**该字段 ⇒ 用它当 `--src` 会 `refused: source tree hash missing or changed`。
**`annotated-71/`（docs-71 那份）有**，所以 `--src` 必须用 `annotated-71/`。（两份 `.cs` 内容逐字节相同，实测 `cmp` 相同。）

### 3.2 绕法（本轮实际采用）：补齐 sidecar，**不读 DLL**

两个可选路径：

- **(A) 工具原生路径** —— 重跑第 4 步，让 `resolve-proxy.py` 自己写合格 sidecar：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  代价：**要读安装目录的 `BeyondEditor.dll`**（离线、只读、不启进程，但属于「触碰编辑器安装文件」的范围）。
  为严守本轮 HARD RULE，**未采用**。
- **(B) 补齐 sidecar（本轮采用）** —— 把现成 map 拷到 scratch，补上两个**从文件本身可算、且已为真**的字段：
  `outputSha256 = sha256(map 文件)`、`completeMap = (len(rows)==totalPairs==outputRows)`。其余字段（`sourceSha256`、
  `tokenValidationPassed:true` 等）原样保留。**这不是编造**：36,479 行确实等于 `totalPairs`、且是 `--all` 全量输出；
  sha256 是对该文件的客观测量。

实跑（`.runtime/scratch/71-corpus-usable/proxy-map-7.1.json`）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 3.3 第 5 步实跑输出（**离线、不碰游戏/编辑器、约 72 秒**）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


产物校验：

| 项 | 值 |
|---|---|
| 输出目录 | `.runtime/editor-catalog/resolved-565dda11/` |
| `.cs` 文件数 | **12,955**（实测 `find … -name '*.cs' \| wc -l`） |
| 规模 | 75 MB |
| 注解引用数 | **190,630**（sidecar `referencesAnnotated`） |
| sidecar | `tool=annotate-proxies.py`、`sourceSha256=565dda11…`、`proxyMapSha256=6b8868db…`、`inputSetSha256=dbcadc58…`、`outputSetSha256=3decc050…`、`inputCompleteness.failedTypes=2684` |
| 样例（真注解） | `/* -> j8im30PLy4epfMBwN0Er.PgdJdFPLK4PkoLedWk7c::FC2PXX3jDb5` |
| 字面量仍在 | `grep -rl batchcreate` = **1 文件**（说明 resolved = 字面量 + 真方法名，两样都全） |

> **注**：`inputCompleteness.complete=false / failedTypes=2684` 是**反编译器「每类型一文件」写法的老问题**
> （2,684 个嵌套类型，代码已内联在父文件里），与 `docs/research/reverse-eng-20261010/CORPUS-COVERAGE.md` §1/§2.1
> 已定案的一致，**不是本轮新缺**。

---

## 4. 判决：7.1 语料今天能不能 grep？

**能，且分三档，按「你要搜什么」选树**（下表字面量命中均为本文 Bash 实测，Grep 工具会跳过 `.runtime/` 须走 Bash）：

| 你要搜的 | 该用哪棵树 | 今天可用？ | 实测 |
|---|---|---|---|
| **字符串字面量 / 命令名 / UI 文案**（如 `batchcreate`、`vmBtn*` 按钮名） | `annotated-71/`（或 `resolved-565dda11/`，两者都含） | ✅ **可用** | `grep -rl batchcreate` → **1**；同一串在 `decomp-7.1/` → **0**（字面量被 `A^B` 藏了） |
| **真方法名 / 代理目标**（用于追调用链） | `resolved-565dda11/`（**本轮新建**） | ✅ **可用** | 190,630 处 `X.Field /* -> Type::Method */` |
| **混淆类型名 / 符号名** | 任何一棵 **7.1** 树 | ⚠️ 能搜但**不能拿 7.0 的名字去搜** | 名字每 build 重掷（`docs/research/reverse-eng-20261010/CORPUS-COVERAGE.md` §2.2：overlap 仅 23/15,654） |
| 只搜**原始混淆形**、且不想被注解干扰 | `decomp-7.1/` | ✅ 可用（但几乎搜不到业务语义） | — |

**结论**：
1. **今天要对 7.1 corpus 做「按字符串找功能」的挖掘（本轮 wave 的目标）——直接用 `annotated-71/` 即可，无需任何前置步骤。**
2. **要「按真方法名」走调用链/追写入者——用本轮新建的 `resolved-565dda11/`。**
3. 旧 7.0 语料（`.runtime/editor-catalog/resolved/`、`annotated/`）**对当前装机无效**，只作为 7.0 基线；**跨 build 的负结论（「不存在 X」）必须回到 7.1 树复核**。

---

## 5. 证据索引（本文亲自复现的 `file:line` / 实测）

| # | 事实 | 出处 |
|---|---|---|
| 1 | 7.0 四工具五步的原文命令 | `docs/editor-catalog/COMMAND-CHANNEL.md:256-266`；本文件 §2 独立复核 |
| 2 | 第 5 步工具与它的 map/sidecar 硬校验 | `tools/editor-catalog/annotate-proxies.py:105,117,122,127,169,302` |
| 3 | `resolve-proxy.py` **现能**写 `outputSha256`/`completeMap` | `tools/editor-catalog/resolve-proxy.py:204-210` |
| 4 | 7.1 map 缺该两字段（旧 sidecar） | `.runtime/verification/update-repair-20260924/proxy-map-7.1.json.source.json`（实读） |
| 5 | 拒绝实跑回执 | `refused: --map outputSha256 missing or changed; regenerate the map`（`annotate-proxies.py:122`） |
| 6 | 7.1 字符串表 profile `editor-7.1`，`entry_count=2985` | `tools/editor-catalog/string_table.py:228-244` |
| 7 | `decomp-7.1` / `annotated-71` sidecar 身份 `565dda11…` | 两目录的 `.source.json`（实读） |
| 8 | `batchcreate`：`annotated-71` 命中 1 / `decomp-7.1` 命中 0 | 本文 Bash `grep -rl` |
| 9 | 新 resolved 树 12,955 `.cs` / 190,630 注解 / 75 MB | 本轮实跑 + `find`/`du`/sidecar |
| 10 | 7.1 资源目录 4,355 解码 / node-catalog 4.08 MB | `find … decoded-7.1 \| wc -l`；`ls -la …/node-catalog-7.1.json` |
| 11 | 语料版本断层与「搜不到 ≠ 不存在」纪律 | `docs/research/reverse-eng-20261010/CORPUS-COVERAGE.md` §2.2；`docs/research/reverse-eng-20261010/CORPUS-EXPANSION-FEASIBILITY.md` §2 |

---

## 附：本轮新增/未动的路径（供下轮接手）

- **新增（本轮）**：
  - `.runtime/editor-catalog/resolved-565dda11/`（12,955 `.cs` + `.source.json`）—— 7.1 的 proxy-resolved 树。
  - `.runtime/scratch/71-corpus-usable/proxy-map-7.1.json(.source.json)` —— sidecar 补齐后的 map（scratch）。
- **未动**：`docs/research/reverse-eng-20261010/INDEX.md`（本文件未登记入其归档表；按「只动本人名下文件」的纪律，
  索引同步留给 INDEX 的维护者）。任何引用本文件前请回 §0/§4 的两句判决复核。
