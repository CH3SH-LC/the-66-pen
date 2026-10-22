> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 千星编辑器全量功能与接口调研

调查日期：2026-09-17 / 18。任务来源：用户当日指令——
「真实调研千星编辑器的**所有功能**，然后强制找出所有编辑器功能在代码上或别的地方的体现，
找到**所有接口**，也就是如何能直接通过代码的方式修改千星编辑器的内容。」
并明确「禁止任何形式的关闭」原神与编辑器。

**本轮全程离线只读**：未启动、未连接、未操作、未关闭、未重启原神与编辑器；
未运行任何桥接/探测脚本；未修改游戏安装目录；未改动 `GOAL.md`。
所有结论标注证据等级：**实测**（本机真实执行并读回）/ **静态**（从文件或 IL 直接读出）/ **推断**。

---

## 一句话结论

编辑器的功能面与接口面都已被**完整枚举**：4098 个资源文件（799 个官方节点、
2484 个预制、656 个复合节点、140 个数据结构、589 个分类枚举）全量解码，
17.5 MB 的编辑器主程序集反编译为 12,375 个源文件并还原出全部字符串，
**34,728 条方法代理映射**把混淆调用还原为真实方法名，
并定位到编辑器向游戏派发**具名命令**的通用通道。

---

## 文档索引

| 文档 | 内容 | 关键数量 |
|---|---|---|
| OFFICIAL-FUNCTION-INVENTORY.md（历史来源：`OFFICIAL-FUNCTION-INVENTORY.md`） | 官方 207 条教程目录的**全量功能总表**，按 12 个功能域归并 | 207 条，正文缺口 0 |
| UI-TEXT-INVENTORY.md（历史来源：`UI-TEXT-INVENTORY.md`） | 编辑器**界面文本**清单（TextMap 键 → 中文） | 7,743 键 |
| UI-ASSET-INVENTORY.md（历史来源：`UI-ASSET-INVENTORY.md`） | 从 `assets.bin` 解出的**界面图标**反推功能面 | 6,453 条目 |
| NODE-CATEGORY-TREE.md（历史来源：`NODE-CATEGORY-TREE.md`） | 编辑器**节点分类树**（BeyondGlobal 还原） | 589 个分类节点，全部具名 |
| NODE-CATALOG.md（历史来源：`NODE-CATALOG.md`） | **官方节点全目录**（id / 中文名 / 引脚） | 799 节点，4,075 引脚 |
| CODE-SURFACE.md（历史来源：`CODE-SURFACE.md`） | 功能在**代码上的体现**：程序集、保护与破解、类型索引、核心对象模型 | 12,375 类型 |
| COMMAND-CHANNEL.md（历史来源：`COMMAND-CHANNEL.md`） | **具名命令通道**：编辑器如何用代码改内容 | 23 条命令 / 13 个通道 |
| INTERFACE-INVENTORY.md（历史来源：`INTERFACE-INVENTORY.md`） | 接口分层总览、消息编号全表、桥接操作白名单、**尚未接通的接口** | 62 个桥接操作（当时） |
| INTERFACE-VERIFICATION.md（历史来源：`INTERFACE-VERIFICATION.md`） | **真机验证**：把上述静态接口拿到运行中的编辑器里逐条核对 | 19/21 槽位按名命中；13 个通道全部可用 |

---

## 支撑材料（`.runtime/editor-catalog/`，多为 Git 忽略项）

| 文件 | 说明 |
|---|---|
| `decoded/` | 4,098 份解码后的 `.mihoyobin`（115 MB） |
| `decomp/BeyondEditor/` | 全量反编译源码，12,375 个 `.cs`（64 MB） |
| `annotated/` | 还原字符串字面量后的副本 |
| `resolved/` | **再还原方法代理**后的副本（按真实方法名可搜索） |
| `string-table.json` | 2,830 条已还原字符串（偏移 → 文本） |
| `proxy-map-full.json` | **34,728 条槽位 → 真实方法**映射 |
| `node-catalog-full.json` | 799 节点结构化目录 |
| `node-names.json` | 节点名解析结果 |
| `type-index.json` / `literal-to-types.json` | 混淆类型 → 字面量，及其反查 |
| `assets-bin/assets.dec` | `assets.bin` 解出的 231 MB 载荷 |
| `assets-manifest.json` | 6,453 条界面资源清单 |
| `toolbar-icons.txt` / `gadget-icons.txt` | 410 个工具栏图标 / 2,424 个元件图标名 |
| `command-channels.tsv` / `command-sites.txt` | 命令 ↔ 通道映射及全部调用点 |
| `_*.py` / `_*.txt` | 各研究员留下的**临时脚本与中间结果**，可安全删除 |

## 工具链（`tools/editor-catalog/`，全部只读离线）

| 工具 | 用途 |
|---|---|
| `extract-user-strings.py` | 读 PE 元数据 `#US` 堆（用于证明字面量被删除） |
| `ilspy-dump/` | C# 反编译器（离线 NuGet）：`strings`/`all`/`decomp`/`findstr`/`types` |
| `decode-mihoyobin.py` | `.mihoyobin` → protobuf 树（XOR `0xE5`） |
| `extract-assets-bin.py` | 解 `assets.bin`（ZipCrypto，密码 `G16F153D`） |
| `annotate-strings.py` | 把混淆常量还原为字符串 |
| `resolve-proxy.py` | 解出槽位 → 真实方法映射（34,728 条） |
| `annotate-proxies.py` | 把代理调用注解上真实方法名 |
| `index-types.py` | 类型 → 字面量索引 |
| `categorize-strings.py` | 字符串分类（路径/常量/消息/UI 键） |
| `resolve-node-names.py` / `build-node-catalog.py` | 节点名解析与全量目录 |
| `build-category-tree.py` | 节点分类树还原 |
| `summarize-catalog.py` | 资源目录汇总 |

---

## 三条可复现的解码链（本轮建立）

1. **`.mihoyobin`**：单字节 XOR `0xE5`（来自 `file-loader.cs:250`）→ protobuf wire。
   **4098/4098 解码成功**。
2. **程序集字符串表**：内嵌资源 blob（`[uint32 长度][blob]` 排列）用既有
   `local1-key.bin` 解密 → 2,830 条。锚点：偏移 **61834 = `Resource\Json\Beyond\Node`**。
3. **`assets.bin`**：ZipCrypto，密码 **`G16F153D`**（`RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs.cs:859–861`）。

## 解码规则（本轮确立）

| 对象 | 规则 |
|---|---|
| 节点名 | `Node` 文件字段 `206` = TextMap 哈希 → **799/799 可解析** |
| 引脚名 | 引脚记录字段 `7` = TextMap 哈希；字段 `208` 是引脚名明文列表/搜索关键词 |
| 引脚分组 | 字段 `100` 输入执行、`101` 输出执行、`102` 输入数据、`103` 输出数据（`106` 未定） |
| 引脚类别 | 引脚记录字段 `3` 子字段 `1`；组内序号为子字段 `2` |
| 分类树 | `BeyondGlobal`；分支名字段 `4`，叶名字段 `3` |
| 资源清单 | 799 + 2484 + 656 + 140 + 1 + 1 + 2 + 15 = **4098**（闭合） |

---

## 已知缺口

- 程序集共 **5 个内嵌资源，5 个已全部定性**：VM 字节码、防篡改数据、
  `ChD8pmO6OJlhN6BUxW.FPVPwCbD7pmqUXHc0e`（99,774 字节，经引用点证实是 **ConfuserEx VM 的数据段**，
  非编辑器内容，不需要解开）、代理映射表、字符串表。
  仍有 216 处字面量未还原（属 blob2 内的 VM 数据）。
- **反编译没有缺失**：2,555 个 `_ERR_*.txt` 全是嵌套类型，内容已含在父类型输出中（见 `CODE-SURFACE.md` 第三节）。
- 预制（2484）、复合节点（656）、数据结构（140）的**名称不在编辑器资源内**（在游戏客户端数据中），
  离线无法得到。
- 从字符串表还原的操作名（`DeleteEditObj` 等）中，**只有 23 条找到了派发调用点**；
  其余（如 `AddInstructionGraphForEditObj`、`RequestPrefabInstance`）未定位到调用路径。
- 命令的服务端语义、副作用、幂等性**未知**；本轮**未调用任何命令**。
- 「试玩取内存态还是已保存关卡」这一既有分歧，本轮未触及。

---

## 与既有结论的冲突与更正

| 既有记录 | 本轮 |
|---|---|
| 游戏在 `D:\Program Files\miHoYo Launcher\games\...` | 实际在 **`C:\Games\Genshin Impact Game`**；旧路径已不存在 |
| 「工程桥接没有删除节点图的能力」 | 发现 `DeleteEditObj`/`DeletePrefab` 命令及其派发点，**削弱**该主张，但不等同于已有可调用接口 |
| 1015 / 1020 曾被记为已观测 | `INTERFACE-INVENTORY.md` 核实：**从未真正观测到**（1015 记录恒为 null/0；1020 到达 3 次但条目数为 0） |
| `node-catalog-full.json` 的 `category` 字段 | 多剥了一层嵌套、**不可用**；`NODE-CATALOG.md` 已重新解析 |

`GOAL.md` 未改动。
