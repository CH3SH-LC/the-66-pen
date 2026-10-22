> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 双语料检索纪律 —— 一个负面必须点名它搜过哪些语料

**产出日期**：2026-10-11
**口径**：**纯离线、纯只读**。未连桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档。
未读任何图片或 PDF。产物写在工程内。

---

## 0. 一句话规则

> **一个负面结论必须点名它搜过哪些语料；只要存在兄弟语料，兄弟也必须被搜。**
> 对一份语料搜出 0 命中，**不是**对全部语料搜出 0 命中。

过去这个错误已经犯过五次（见 `docs/../CLAUDE.md` §一.2「搜不到≠不存在」与
本目录 `CORPUS-COVERAGE.md`）。它现在被机械地堵住：**语料不是调用方指定的单一路径，
而是由工具自动发现全部兄弟语料并逐一搜索**。

---

## 1. 仓内**两棵**已解析语料（不是「一棵的另一半」，是「两个 build」）

| 路径（相对工程根） | `.cs` 数 | 来自哪个 build | 证据 |
|---|---|---|---|
| `.runtime/editor-catalog/resolved/` | **12,375** | 编辑器 **7.0**（legacy） | `BeyondEditor.dll` 17,535,896 B，SHA-256 `D4B429A3…3841`；无 `.source.json` |
| `.runtime/editor-catalog/resolved-565dda11/` | **12,955** | 编辑器 **7.1**（当前安装） | `.source.json`：`sourceSha256=565dda11…678a`、`profile=editor-7.1`、`filesScanned=12955` |

**它们为什么不能只搜一棵**：两版的**混淆类型符号名逐名不重叠**。对当前 7.1 DLL 枚举出的类型名里，
只有约 **23** 个与 7.0 语料同名，且**全是未混淆的框架名**（`Google.Protobuf.*` 等）。
⇒ **同一个符号可以在一棵里有、另一棵里没有**。这不是「语料漏了代码」，是「语料是另一版」
（详见 `CORPUS-COVERAGE.md` §0.1、§0.4）。

来源与关系：`resolved/` 是 7.0 五步管线的第 5 步产物（`docs/editor-catalog/COMMAND-CHANNEL.md`）；
`resolved-565dda11/` 是**同一五步管线跑在 7.1 上**、本轮补齐的第 5 步产物（`71-CORPUS-USABLE.md` §0、§2）。

---

## 2. 机械化的办法 = `tools/editor-catalog/search-corpora.py`

不传语料目录，只传 `--pattern`；工具**自己发现** `--catalog-dir` 下所有 `resolved*`
且含 `.cs` 的目录，**逐一搜**，逐棵报计数。默认 `--require-both`：
**发现少于两棵语料就 FAIL（exit 2）**，而不是静默通过——所以兄弟语料被删/被挪会**响亮报错**，不会隐形。


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


- 退出码：`0` = 每棵发现的语料都搜过（`--require-both` 下且 ≥2 棵）；`2` = 不足两棵语料；`1` = 用法/IO 错。
- 每棵语料旁标注来自哪个 build（读 `.source.json` 的 `sourceSha256`/`profile`；没有 sidecar 就**如实报 `<no source.json>`**，绝不臆测）。
- 测试：`tools/editor-catalog/tests/test_search_corpora.py`（**合成 fixture，不依赖真语料**；
  关键回归用例 `test_pattern_only_in_second_corpus_is_found` 保证「只存在于兄弟语料的符号」仍能被找到）。

### 真机一次运行（2026-10-11，deliverable proof）

| pattern | `resolved/`（7.0） | `resolved-565dda11/`（7.1） |
|---|---|---|
| `DeleteComponentForEditObj` | 1 命中 / 1 文件 | 1 命中 / 1 文件 |
| `batchcreate`（**7.1 独有**的正对照） | **0 命中** | 1 命中 / 1 文件 |

`batchcreate` 那一行就是纪律要防的东西：只搜 `resolved/` 会得出「不存在」的**假负面**，
而兄弟语料里明明有 1 处。工具把这一对同时摆出来。

---

## 3. 结论

- **写负面时，先点名语料**。若只搜了一棵，该负面**不成立**（除非说明「本次仅搜 X 语料」）。
- **搜语料永远走 `search-corpora.py`**，它默认全搜 + 缺语料即失败；手写 `grep` 只作临时探索，
  **不能**作为负面的证据基础。
- 这套纪律与本目录 `CORPUS-COVERAGE.md`（语料覆盖边界）互为表里：一个说「语料是另一版」，
  一个说「那你得把两版都搜了」。
