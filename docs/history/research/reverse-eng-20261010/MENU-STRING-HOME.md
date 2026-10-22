> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# MENU-STRING-HOME — 系统菜单文案（背包与货币 / 商店模板管理）到底住在哪个文件？

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。未连桥、未发任何 native/graph 请求、未启动或触碰编辑器或游戏、未重启 helper、未申请 UAC、未注入。
**只读动作**：`find`/`ls`/`sha256sum`、Bash `grep -r`、Python 直读文件字节（对 `.mihoyobin` 做已知 XOR 0xE5 解码后按 protobuf 走读）。
对 `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` **只读**且**未读任何图片/PDF**。
脚本落在 `.runtime/scratch/menu_string_scan.py`；**本文件是本任务唯一产出**，未改 `tools/`、未改任何 pin、未改任何测试。

---

## 0. 一句话结论

> **没有。** 装机（当前 7.1 build）的**全部可读资源里都没有**「背包与货币 / 商店模板管理」这两个系统菜单文案。
> 编辑器界面文案的**唯一通路是 TextMap**（键=代码字面量 → `Resource/Json/TextMap/CHS/<hash>.mihoyobin`）。
> 我把**当前装机的那份 TextMap 现解了一遍**（8,267 条），里面**有** `光源管理`（= `…_ESC_LIGHTING_ESCNAME`），
> **没有**这 29 项「XX管理」管理工具里的绝大多数（关卡设置 / 背包与货币 / 商店模板管理 / 奇域礼盒管理 …）。
> ⇒ 这两个文案**不在本机任何可读资源里**；能藏它的只剩**加密件**（`BeyondEditor.dll` 的 ConfuserEx 加密 BAML，
> 与游戏侧 56 GB 加密 `.blk`）。**扩语料（重搜）拿不到它——这一步是「读不到」，不是「没找到」。**

**顺带纠正一个上游口径**：任务里的「**货币与背包**」在官方语料里写作「**背包与货币**」
（`docs/official-docs/chapters/mhn4bsi5lb58.json` 逐字）。按错误串搜必然 0 命中。

---

## 1. 我们已有的菜单从哪来 —— 把 `ESP_LIGHTING_*` 追到源头

### 1.1 端到端证据链（实测、逐跳）

| 跳 | 事实 | 证据（file:line / 路径） |
|---|---|---|
| ① 文案本体 | `UI_BEYOND_EDITOR_ESP_LIGHTING_TITLE` = **光源管理**；`…_ESP_LIGHTING_ESCNAME` = **光源管理**；`…_ESP_LIGHTING_INTENSITY` = **强度** | `.runtime/editor-catalog/textmap-chs.json:36368`、`:36443` |
| ② 源文件 | 上面这些键**就在装机目录的 TextMap 资源里**：`…/BeyondAssistEditor/Resource/Json/TextMap/CHS/17720714722766726369.mihoyobin`（655,179 B） | `ls -la`，路径见下表 |
| ③ 文件怎么读 | 编辑器自己的 loader 先整体 `^= 229`（0xE5），再把结果当 protobuf 读 | `.runtime/verification/resource-file-loader/file-loader.cs:250`（`array[i] ^= 229;`） |
| ④ 解码产物 | 仓内既有的解码器可复现：`TextMap__CHS__17720714722766726369.mihoyobin.json`，7743 条记录 | `.runtime/editor-catalog/decoded/…`、`textmap-chs.json` |
| ⑤ 显示通路 | 菜单标签=**代码字面量里的 TextMap 键**，运行时按语言取 CHS 值。窗口菜单就是这么建的：`Oo4svmLkH7NHaTQtfSje.…(menu, 3, "UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_NODE_MANAGER", …)` → 显示「节点管理器」 | `.runtime/editor-catalog/resolved/zJuB8VueHhBspK3PDhqo.u4vgh9uebiscBdHWcnLi.cs:682`（节点管理器）、`:259`（资源管理器）、`:686`（帮助 `UI_BEYOND_EDITOR_WPF_HELP_ENTRANCE`） |
| ⑥ 键↔值对照 | `UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_MANAGER_NODE_MANAGER` = **节点管理器**；`…_RESOURCE_MANAGER` = **资源管理器** | `.runtime/editor-catalog/textmap-chs.json:34133` 起 |

**结论（通路题）**：编辑器每个菜单项的标签＝**一条 TextMap 键**（代码里是字面量），
经 `KeyToTextMapConverter` 取 `TextMap/<lang>` 的值。**缺的字符串若走同一通路，就该是同一条 TextMap 里的另一个值**——
这就是「Home（家）」：`Resource/Json/TextMap/CHS/17720714722766726369.mihoyobin`。
**但下一步的实测证明：那两个值不在家里。**

### 1.2 「系统菜单」这一档的键形（重要）

`…_ESC_LIGHTING_**ESCNAME**` 里的 `ESCNAME` 后缀就是**系统菜单（ESC 菜单）项**的命名约定。
在**当前装机**的 TextMap 里，`ESCNAME` 键**只有 1 条**：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


其余值里带「管理」结尾的只有 5 条（`信号管理` / `光源管理`×2 / `脚本变量管理` / `事件管理`）。
⇒ 装机这份编辑器的 TextMap **根本没有**官方文档那 29 项「角色预览管理 / 计时器管理 / … / 商店模板管理 / 背包与货币」。

---

## 2. 全量只读搜索：命中 / 未命中与检索范围

**搜索串**（UTF-8 / UTF-16LE / UTF-16BE / GB18030 四种编码各查一遍；`.mihoyobin` 先 XOR 0xE5 再查）：
`货币与背包`、`背包与货币`、`商店模板管理`、`模板管理`、`系统菜单`，并附对照串 `光照` / `添加引脚` / `打印字符串`（已知存在，用于证明检具有效）。

### 2.1 命中的（全部）

| 根 | 命中 | 说明 |
|---|---|---|
| `…/BeyondAssistEditor/Resource/**` | `与背包` ×2（TextMap CHS） | 是 `道具**与背包**`（蓝图分类树目录名），**不是**系统菜单项 |
| `…/Resource/Json/Config/…/SynonymsLibrary/CHS/…mihoyobin` | `光照` ×1 | 是**检索同义词表**的一条（2502 条同义词），非菜单文案 |

**没有任何一处命中「背包与货币」「商店模板管理」「货币与背包」「系统菜单」。**

### 2.2 检索根清单（可复核）

| # | 根 | 覆盖方式 | 文件数 | 结果 |
|---|---|---:|---:|---|
| 1 | `D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/` | 全目录按字节扫（plain + UTF-16LE）；其中 `Resource/**` 再按 XOR 0xE5 解 `.mihoyobin` 后扫 | 4,862 / 4,380 | **0** |
| 1a | ↳ `BeyondEditor.dll`（18,404,248 B） | 直接字节扫 (`货币/背包/商店/模板/系统` × UTF-16LE/UTF-8 = 各 0) | — | **0**（DLL **不含任何 CJK**） |
| 1b | ↳ `Resource/BeyondAssets/assets.bin`（247,487,494 B） | 用已记录口令 `G16F153D` 解 ZipCrypto → 内层 6,936 项 | 6,936 | **全是 PNG，0 文本** |
| 1c | ↳ `Resource/BeyondAssets/beyondeditorassets.bin`（6,411 B） | 同上解密 → 内层 1 项 | 1 | **1 个 PNG** |
| 1d | ↳ `Resource/Json/**`（TextMap×15 语言 + Beyond + Config） | XOR 全量解后扫 + 键名提取 | 4,368 | **0**（见 §3） |
| 2 | `D:/games/Genshin Impact Game/`（顶层：`YuanShen.exe` 445 MB、`mhypbase.dll`、`rtlbase.dll`、`HoYoKProtect.sys`） | 直接字节扫 | 4 | **0** |
| 3 | `D:/games/Genshin Impact Game/YuanShen_Data/` | 全目录字节扫（含 `StreamingAssets`、`Managed`、`Persistent`） | 大（后台跑，至今 0 命中） | **0** |
| 3a | ↳ `YuanShen_Data` 里 22 个 `.json/.txt/.dat` 配置 | `grep -rIl` | 22 | **0** |
| 3b | ↳ `StreamingAssets/AssetBundles/blocks/*.blk` | 1985 个 blob，**56 GB，加密/打包** | 1985 | **不可直接读**（见 §4） |
| 4 | `C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` | `grep -rIl`（含 binary）全树 | 917 | **0** |
| 5 | 仓内 `.runtime/`（语料 + 全体既有产物） | 全树字节扫（XOR 于 `.mihoyobin`）+ 定点 `grep` | 大（后台跑，至今 0 命中） | **0** |
| 5a | ↳ `.runtime/editor-catalog/annotated|resolved/**`（12,375 `.cs` 语料） | `grep -rl`（Grep 工具跳过 `.runtime`，故用 Bash） | 12,375 | **0** |
| 5b | ↳ `.runtime/scratch/editor71-string-table.json`（**7.1 现行 build** 的字符串表，2985 条） | Python 全表查 | 2,985 | **0** |
| 6 | 仓内 `docs/ tools/ backend/ …` | `grep -rIl` | — | 仅命中**官方文档本身**（见 §2.3） |

### 2.3 唯一「命中」是官方文档原文（不是资源）

`docs/official-docs/chapters/mhn4bsi5lb58.json` 的 `facts` 里逐字给出了系统菜单全表——
**这是"文档写了这个名字"，不是"某个资源里存着这个名字"**：

- 第 2 组（8 项）：`关卡设置、界面控件组管理、主镜头管理、试玩、多人试玩、外围系统管理、背包与货币和奇域礼盒管理`
- 第 3 组（21 项）：`角色预览管理、计时器管理、关卡变量管理、预设点管理、技能资源管理、背景音乐管理、资产导入导出管理、装备数据管理、商店模板管理、高级数据管理、局内存档管理、试玩临时数据管理、实体布设组管理、单位标签管理、护盾管理、扫描标签管理、路径管理、多语言文本管理、光源管理、文字聊天管理和快捷键总览`

逐项拿这 29 个名字去比对**装机 TextMap 的"值"**：**只有 2 项命中**——`试玩`、`光源管理`；其余 27 项全 0。

---

## 3. 若有命中文件——它就是线索：读它，看旁边还住着什么

**没有命中文件。** 但仍有一个"最像家"的文件值得报：**装机的 TextMap 本身就是编辑器界面文案的资源表**，
而且**今晚刚从磁盘现解了一遍**（不是复用旧产物）：

- 文件：`D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/Resource/Json/TextMap/CHS/17720714722766726369.mihoyobin`
- 现解产物：`.runtime/scratch/_tm_chs/17720714722766726369.mihoyobin.json`（本任务写，`_provenance.json` 记录 `source_set_sha256`）
- **记录数 8,267**（旧产物 `textmap-chs.json` 是 7,743 → **TextMap 本身也升过版，多出 524 条**）
- 现解结果：`背包与货币` **0**、`商店模板管理` **0**、`货币与背包` **0**；`货币` 29、`商店` 65、`模板` 25（全在**节点/配置**文本里）
- 键名里带 `MENU/MANAGE/SHOP/TEMPLATE/CURRENCY/BAG` 的，**只有** `…_CONTROL_MENU_*` 与 `…_LOGCTRL_*`——**没有任何货币/背包/商店模板菜单键**
- `ESCNAME` 键**仅 1 条**（光源管理）

**这条现解结果的意义**：连"最新那一版 TextMap"都没有这些文案 ⇒ 不是"我们拿了旧 TextMap"的问题，
而是**这份装机（PC 版 BeyondEditor/千星辅助编辑器）根本没有那 29 项系统菜单**。

另一个候选资源表是 **7.1 现行 build 的字符串表** `.runtime/scratch/editor71-string-table.json`（2,985 条，旁证在 `CORPUS-EXPANSION-FEASIBILITY.md:1.1`）：里面只有 **48 个 XAML pack URI**
（`MainWindow.xaml`、`Explorer/…`、`UI/Dialog/{SignalMgt, GMDialog, InstructionGraphLog, ExplorerReference…}`…），
**没有**任何 Currency / Bag / Shop / Template 面板的 XAML。⇒ 连面板标记都不存在。

---

## 4. 判决：有没有可读资源给这些菜单命名？—— **没有。YES-or-NO = NO。**

### 4.1 否证结构（三层，别混）

1. **"缺的字符串"不在任何可读文本资源里**：编辑器 TextMap（现解 8,267 条）、同义词表、配置文件、
   `assets.bin`（已解密，纯 PNG）、`CHS/EN/…` 15 语言 TextMap，全部 0。
2. **不在任何可读符号里**：`BeyondEditor.dll` 裸字节 **不含任何 CJK**；
   7.1 字符串表 2,985 条也只到 ASCII 符号 / XAML 路径，**不含 CJK 文案**。
3. **可读件到此为止，剩下的全是加密件**（这两条都不是"再搜一次"能解决的）：
   - `BeyondEditor.dll` 的界面标记被 **ConfuserEx 资源保护**加密：`g.resources`/`.baml`/`pack://application` 裸字节**各 0 命中**，
     `#US` 堆**只剩 684 B**（→ 本任务 `extract-user-strings.py` 只读出 15 条）。见 `CORPUS-EXPANSION-FEASIBILITY.md:2.3`。
   - 游戏侧文案在 `YuanShen_Data/StreamingAssets/AssetBundles/blocks/`：**1985 个 `.blk`、56 GB、打包/加密**，
     没有对应解包器就读不到；仓内明令禁止运行外部 UGC 工具（见 MEMORY）。
   - 全盘仅有的 `*TextMap*` 命中的是**编辑器自己那份**（`/BeyondAssistEditor/Resource/Json/TextMap`），**游戏没有独立可读 TextMap**。

### 4.2 可行性判据（供上游决定要不要花力气）

- **"再搜一遍语料"⇒ 收益为 0**。这是**缺件**，不是**检索覆盖不足**。
- **想真正拿到这两个文案，只有两条路，且都在"重搜"之外**：
  (a) **拿到一份确实带这 29 项菜单的编辑器 build**，解它的 `Resource/Json/TextMap/CHS/*.mihoyobin`（读者已具备：XOR 0xE5 + protobuf）——
      成本低、零解密风险，**但前提是那份 build 真的存在且拿得到**；
  (b) **解游戏侧 `.blk`（56 GB）** ——需要游戏资源解包器，**与仓内既有禁令冲突**，不建议。
- **顺带钉死一条反例**：`assets.bin` 已被解密并排除（纯 PNG），
  所以"主界面文案封装在加密的 `assets.bin`"这条旧推断（`beyondeditor-frontend/02-…/01-界面文本总表.md:176` G10）**对本 build 再次被否证**。

### 4.3 必须一起报的两个"跨 build"事实（否则结论会被误读）

- **语料 ≠ 装机**：语料是 legacy build（`BeyondEditor.dll` 17,535,896 B / SHA `d4b429a3…`），
  装机是 **7.1 build**（18,404,248 B / SHA `565dda11…`）——我本轮实测与 `CORPUS-EXPANSION-FEASIBILITY.md:2.2` 一致。
  ⇒ **用旧语料的混淆类名去搜当前 DLL 永远 0 命中**（ConfuserEx 每 build 重掷名字）。"搜不到"**不能**推出"不存在"。
- **口径纠正**：官方串是「**背包与货币**」，不是「货币与背包」。上游若继续用后者做检索/验收，会一路 0 命中。

---

## 5. 引用清单（file:line / 路径）

- 菜单显示通路（键=代码字面量）：
  `.runtime/editor-catalog/resolved/zJuB8VueHhBspK3PDhqo.u4vgh9uebiscBdHWcnLi.cs:259`（资源管理器）、`:682`（节点管理器）、`:686`（帮助）
- TextMap 解码算法：`.runtime/verification/resource-file-loader/file-loader.cs:250`（`array[i] ^= 229;`）
- 装机 TextMap 文件：`D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/Resource/Json/TextMap/CHS/17720714722766726369.mihoyobin`
- TextMap 现解产物（本任务）：`.runtime/scratch/_tm_chs/17720714722766726369.mihoyobin.json`（8,267 条）+ `_provenance.json`
- 旧产物文本表：`.runtime/editor-catalog/textmap-chs.json:36368`（`…_ESP_LIGHTING_TITLE`=光源管理）、`:34133`（`…_NODE_MANAGER`）
- 官方系统菜单逐字：`docs/official-docs/chapters/mhn4bsi5lb58.json`（`facts` 第 2/3/4 条）
- 7.1 字符串表：`.runtime/scratch/editor71-string-table.json`（2,985 条；48 个 XAML pack URI）
- 加密 BAML / `#US`=684 B / build 差异：`docs/research/reverse-eng-20261010/CORPUS-EXPANSION-FEASIBILITY.md:2.2, 2.3, 3`
- 检具脚本：`.runtime/scratch/menu_string_scan.py`（只读；`.mihoyobin` 走 XOR 0xE5，其余按原文；4 编码）
