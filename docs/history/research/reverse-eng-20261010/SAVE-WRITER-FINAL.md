> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 谁在写这个 `.gil` — 定案（mine #5 / SAVE-WRITER-FINAL）

> 2026-10-10。**全程离线、只读**：没有连桥、没有发任何 native/graph 报文、没有启动/停止游戏或编辑器、
> 没有重启 helper、没有请求 UAC、**没有写任何一个 `.gil`**。`C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/` 全程
> `open(...,'rb')`；未读任何图片/PDF。
>
> 工具：`tools/beyond-save/level_directory.py`（只读声明 `level_directory.py:45`；读 API `:275-295`）。
> 本文的职责是把「页签目录段（`root field 6`）多出来的那条**无 `field 1` 条目**，是引擎写的还是我们写的」
> **一次走完 live 存档、定死**。与同目录的 `SAVE-WRITE-ATTRIBUTION.md`、`TAB-DIRECTORY-MINE.md` 结论**一致**；
> 本文新增的是**对 live 存档每一个 `.gil` 的一次性全量走查**（§1）与**一条可定案的归属证据**（§2）。

---

## 0. 一句话结论

1. **写这份存档的字节的是游戏/编辑器的存档写入方，不是本工程任何 Python。** 本工程的 `save` 只是
   **让写入方把「它自己内存里的页签目录」序化出来**；多出来的那条无 id 条目**来自写入方内存**，不是我们造的。
2. **判定依据（不依赖任何文档转述，本文实测）**：那条无 id 条目**早在 2026-09-19 20:23 就已存在于 1073741830**，
   而**当时本工程连「保存当前关卡」这个操作都还不存在**（第一处 scene-cli 原生 save 目录是 **2026-09-22 13:09**；
   09-19 当轮的复核原文记「未找到可调用的保存当前关卡/开始试玩操作」）。
   ⇒ 这条不是我们的 save 写的。**它在项目能保存 `.gil` 之前就存在**。
3. **判决 = (b) 引擎/写入方行为**，由 (a) 我们发出的 `save` **触发**（不是**作者**）。
4. **复发**：**会复发**——只要写入方内存里那份目录仍比盘上文件多两条，下一次 save 就原样补回（10-08→10-10 已重演）。

---

## 1. 全量走查：`BeyondLocal/` 下每一个 `.gil`（37 个文件）

命令（全部只读，见 §6）。三个账号目录下只有 `100000001` 有 `.gil`；`100559494` / `343269915`
只有空的 `Beyond_Local_Save_Level/` 与 `Temp/`（0 个 `.gil`）。

`Beyond_Local_Save_Level/`（19 个文件）：

| 关卡 | 路径（相对 `100000001/`） | 条目数 | defect 数 | 说明 |
|---|---|---:|---:|---|
| 1073741825 | `Beyond_Local_Save_Level/1073741825.gil` | 33 | 0 | 干净 |
| 1073741826 | `Beyond_Local_Save_Level/1073741826.gil` | 0 | 1 | `missing-root-6`（79 B 空关卡，无目录段） |
| 1073741827 | `Beyond_Local_Save_Level/1073741827.gil` | 0 | 1 | `missing-root-6`（78 B 空关卡） |
| 1073741828 | `Beyond_Local_Save_Level/1073741828.gil` | 33 | 0 | 干净 |
| 1073741829 | `Beyond_Local_Save_Level/1073741829.gil` | 33 | 0 | 干净 |
| **1073741830** | `Beyond_Local_Save_Level/1073741830.gil` | **34** | **1** | **`missing-entry-id@33`** |
| 1073741831 | `Beyond_Local_Save_Level/1073741831.gil` | 33 | 0 | 干净 |
| 1073741832 | `Beyond_Local_Save_Level/1073741832.gil` | 33 | 0 | 干净 |
| 1073741833 | `Beyond_Local_Save_Level/1073741833.gil` | 33 | 0 | 干净 |
| 1073741834 | `Beyond_Local_Save_Level/1073741834.gil` | 33 | 0 | 干净 |
| 1073741835 | `Beyond_Local_Save_Level/1073741835/1073741835.gil` | 41 | 0 | 干净（含合法 `id=36`） |
| 1073741836 | `Beyond_Local_Save_Level/1073741836/1073741836.gil` | 0 | 1 | `missing-root-6`（95 B 空关卡） |
| 1073741837 | `Beyond_Local_Save_Level/1073741837/1073741837.gil` | 0 | 1 | `missing-root-6`（95 B 空关卡） |
| 1073741838 | `Beyond_Local_Save_Level/1073741838/1073741838.gil` | 40 | 0 | 干净 |
| 1073741839 | `Beyond_Local_Save_Level/1073741839/1073741839.gil` | 41 | 0 | 干净（含合法 `id=36`） |
| **1073741840** | `Beyond_Local_Save_Level/1073741840/1073741840.gil` | **42** | **1** | **`missing-entry-id@41`** |
| **1073741841** | `Beyond_Local_Save_Level/1073741841/1073741841.gil` | **42** | **1** | **`missing-entry-id@41`** |
| **1073741842** | `Beyond_Local_Save_Level/1073741842/1073741842.gil` | **42** | **1** | **`missing-entry-id@41`** |
| 1073741835 | `Beyond_Local_Save_Level/UpgradeBackup/1073741835.gil` | 33 | 0 | 引擎升级备份，干净 |

`Temp/`（18 个文件，均为对应关卡的镜像，**逐条结论与上表相同**）：

| 关卡 | 路径（相对 `100000001/`） | 条目数 | defect 数 |
|---|---|---:|---:|
| 1073741825 | `Temp/1073741825.gil` | 33 | 0 |
| 1073741826 | `Temp/1073741826.gil` | 0 | 1（`missing-root-6`） |
| 1073741827 | `Temp/1073741827.gil` | 0 | 1（`missing-root-6`） |
| 1073741828 | `Temp/1073741828.gil` | 33 | 0 |
| 1073741829 | `Temp/1073741829.gil` | 33 | 0 |
| **1073741830** | `Temp/1073741830.gil` | **34** | **1（`missing-entry-id@33`）** |
| 1073741831 | `Temp/1073741831.gil` | 33 | 0 |
| 1073741832 | `Temp/1073741832.gil` | 33 | 0 |
| 1073741833 | `Temp/1073741833.gil` | 33 | 0 |
| 1073741834 | `Temp/1073741834.gil` | 33 | 0 |
| 1073741835 | `Temp/1073741835.gil` | 41 | 0 |
| 1073741836 | `Temp/1073741836.gil` | 0 | 1（`missing-root-6`） |
| 1073741837 | `Temp/1073741837.gil` | 0 | 1（`missing-root-6`） |
| 1073741838 | `Temp/1073741838.gil` | 40 | 0 |
| 1073741839 | `Temp/1073741839.gil` | 41 | 0 |
| **1073741840** | `Temp/1073741840.gil` | **42** | **1（`missing-entry-id@41`）** |
| **1073741841** | `Temp/1073741841.gil` | **42** | **1（`missing-entry-id@41`）** |
| **1073741842** | `Temp/1073741842.gil` | **42** | **1（`missing-entry-id@41`）** |

**`Temp/` 镜像与 `Save_Level/` 对应文件逐字节相同**（抽验 sha256）：
`1830`（`b6ed608c…`）与 `1842`（`56feb97d…`）两对的 `Save_Level` 与 `Temp` **sha 完全一致**。

> 术语注：`missing-root-6`（1826/827/836/837）不是损伤——它们是 78–95 B 的**空关卡**，从未有过目录段；
> `missing-entry-id` 才是本题追踪的那条尾条。

---

## 2. 关键问题：这条尾条出现在「本工程从未保存过的文件」里吗？

**任务给的判据是**：「出现在未碰过的文件 ⇒ 引擎做的，是正常现象，不是我们的；**只**出现在我们保存过的文件 ⇒ 是我们的。」

**答案：它出现在本工程从未 writes 的字节位置上——而且是本工程当时「物理上还不会保存关卡」的时间窗里。**

### 2.1 定案子证据：1073741830 在 **2026-09-19 20:23** 就带着这条尾条

`.runtime/verification/upload-audit-20260919/1073741830-before.gil`（**51273 B，mtime 2026-09-19 20:23**）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


它**早于** 10-08 事件**整整三周**，也**早于本工程的第一个原生 save**：

- 本工程 scene-cli（原生 `save`）最早目录 = `.runtime/game-executor/scene-cli/20260922-130605-create-493b95b4`、
  第一处 `save` = `…/20260922-130924-save-f0764f48` ⇒ **原生保存能力自 2026-09-22 起才有**。
- 09-19 当轮的专项复核原文（`docs/gameplay/UPLOAD-VALIDATION-FIX-20260919.md:63`）：
  「**未找到可调用的保存当前关卡/开始试玩操作**」。
- ⇒ **2026-09-19 20:23，本工程没有任何「保存当前关卡」的能力**。那条尾条却在盘上。
  **它不是我们的 save 写的。**

### 2.2 `Temp/` 是纯引擎产物，本工程从不写它

- 全仓检索：**没有任何工具写 `Temp/` 路径**（`grep -rIn "Temp" tools/beyond-save/*.py tools/game-executor/*.py`
  只命中 `level_settings.py:43,225` 的**读/计数**注释与 `TemporaryDirectory` 无关命中）。
- 而 `Temp/1073741830.gil`（及 `…/1840/1841/1842`）**带着与 `Save_Level/` 逐字节相同的尾条**（§1 抽验 sha）。
- 结合「写入方**不重读文件**、从自己内存序化」（§3.1）⇒ `Temp` 里这条 = **写入方内存里就有这条**。

### 2.3 尾条**逐字节相同**，跨四关卡、跨三周（本文自测）

用 `gil_container` 逐字段重编每条 entry 的 body，取 `field 6` 的**最后一条**：

| 文件 | 条目数 | 最后一条 body（hex，31 B） |
|---|---:|---|
| `Save_Level/1073741830.gil` | 34 | `12080a04726f6f7418011a130a0fe69caae58886e7b1bbe9a1b5e7adbe1802` |
| `Save_Level/1073741840/1073741840.gil` | 42 | `12080a04726f6f7418011a130a0fe69caae58886e7b1bbe9a1b5e7adbe1802` |
| `Save_Level/1073741841/1073741841.gil` | 42 | `12080a04726f6f7418011a130a0fe69caae58886e7b1bbe9a1b5e7adbe1802` |
| `Save_Level/1073741842/1073741842.gil` | 42 | `12080a04726f6f7418011a130a0fe69caae58886e7b1bbe9a1b5e7adbe1802` |
| `.runtime/verification/upload-audit-20260919/1073741830-before.gil`（**09-19**） | 34 | `12080a04726f6f7418011a130a0fe69caae58886e7b1bbe9a1b5e7adbe1802` |
| `.runtime/formal-save-backups/…-user-original-before-postsave-test/1073741842.gil`（用户原件） | 40 | `0823…1802`（**有** `field 1`，`id=35`，**非**该尾条） |

**五个文件的最后一条逐字节同一**；用户原件的尾条**不同**（它带着 `field 1=35`）。
一条跨越 **09-19 → 10-10、跨 1830/1840/1841/1842 四关卡**、字节完全一致的条目，
**不可能**由本工程某个「能写 `field 6` 的代码」在四个不同时间点各造一遍——因为**能写 `field 6` 的代码根本不存在**（§3.2）。

### 2.4 交叉样本的另一半：1840/1841 的尾条是「某一次 save 时补上的」

- 1840 的尾条**不是**它第一次被保存就有的：`20261006-100011/102553/110611` 三次 save 后都是 **40 条、0 defect**，
  直到 `20261006-114232-save-3077c9f9` 的 **after** 才变 **42 条、1 defect**。⇒ 是**某一次 save** 补上的。
- 1841 同理：`20261006-122217-save-e1606161` 的 after = 40 条 0 defect；
  `20261006-123333-save-1c190585` 的 before=40/after=42 → **这一次 save**补上了尾条。

⇒ 「补尾条」是**写入方**在**某些 save** 下的动作；**触发**是 save，**作者**是写入方（字节不是我们的）。

### 2.5 对判据的回答（直说）

- **在 live 存档的「未被本项目保存过的关卡」里**（1825/828/829/831–834/835/838/839）：**没有**这条尾条。
- **但它出现在两处「本项目没写/当时写不了」的位置**：(a) `Temp/` 的引擎镜像，(b) **2026-09-19 20:23 的
  1073741830 快照**——那一刻本工程**还没有保存关卡的能力**。
- ⇒ **结论不是「只有我们保存过的文件才有」**。判据指向 **(b) 引擎/写入方行为**，不是「我们的」。

---

## 3. 既有工具里对「写入方」已经知道了什么

### 3.1 `tools/beyond-save/keep_registered.py` —— 写入方**从内存序化、不重读文件**

模块 docstring（`keep_registered.py:5-9`）原文：

> “register_level.py writes a new archive into the player profile, and **something else
> -- the game or the editor -- rewrites that profile from its own memory**. A single
> write is therefore always lost: at 13:32 the file on disk held our 380-byte version and
> the writer replaced it with its own 323-byte one, **which proves the writer does not
> re-read the file before writing**.”

⇒ **盘上文件里是什么，不影响写入方写出什么**。把 `.gil` 恢复成 40 条，**不能**改变写入方内存里的目录。
（`keep_registered.py:19-27` 还明写：本工具**不是**替代编辑器 API，**不能**让运行中的游戏不重启就看到新档案。）

### 3.2 全仓没有一处 Python 写 `root field 6`（本文复核）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


命中里，**构造** `Field(6, …)` 的只有两个**测试**文件：
`tools/gameplan/tests/test_levels.py:78`、`tools/gameplan/tests/test_level_report.py:83`。
生产侧 `ROOT_FIELD_DIRECTORY`（`level_directory.py:66`）只被**只读**的
`level_directory.py:249` 与 `tools/gameplan/checkpoint.py:295`（读）使用。
⇒ **能写这两个字段的只有存盘写入方**，不是本工程代码。

### 3.3 `tools/beyond-save/who-holds-the-save.ps1` —— 用 Restart Manager 直接问「谁持有」

文件头（`who-holds-the-save.ps1:1-15`）说明了它为何存在与它**排除掉**的间接路线：

- 编辑器字符串被 ConfuserEx 加密 ⇒ 「文件里没有这个串」**证明不了**任何事；
- 游戏的 `global-metadata.dat` 被打包（头 `MHY\0`）⇒ 搜不了；
- **没有进程长期持有这些文件**（开→写→关）⇒ 句柄归属**答不了**。
- 它改用 Windows Restart Manager（`RmRegisterResources`/`RmGetList`）**在写入发生的那一刻**列出持有进程。
  脚本 `:95-132` 只调 `RmStartSession/RmRegisterResources/RmGetList`，**只读、不启停任何进程**。

### 3.4 实测归属留档：**YuanShen**（游戏进程）

`.runtime/beyond-save/write-attribution.log`（`attribute-save-writes.py` 的产物）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


同 log 显示两个 `BeyondEditor`（39372/114124）在窗口内对该文件的**写增量 = 0**，
唯一跳变的是 `YuanShen 113168`。⇒ **改写 `.gip`/存档的是游戏进程**，不是编辑器进程。
`attribute-save-writes.py:11-19` 也把三条间接路线（编辑器字符串加密、metadata 打包、无长期句柄）记明为走不通。

---

## 4. 判决

> **写入方 = 游戏/编辑器进程（引擎序化内存 → 落盘）；本工程的 `save` 是它发生的时机，不是它的作者。**
>
> - **作者**：引擎/写入方（§2.1 时间窗、§2.3 字节同一、§3.2 无 Python 写 `field 6`、§3.4 归因到 `YuanShen`）。
> - **时机**：一次 save，且**当且仅当**写入方内存里的页签目录比盘上文件多（§2.4 的 40→42 只在个别 save 出现；
>   `.runtime/game-executor/scene-cli/20261008-211541-save-1c99e513` 40→40、`20261010-003436-create-50c28b0f`
>   40→40 等大量 save **不动**它）。
> - **形态**：**纯尾部拼接**——已有条目不重排、不改写（`TAB-DIRECTORY-MINE.md` §1.2 的前缀属性）。
> - **10-08 事件当时把它写成「我们的两次 save」**：那是**触发**层面的对，**作者**层面应改为写入方。

---

## 5. 后果：下一次 save 会复发吗？

**会复发——但是「条件式」的；且「跨重启」这一支未决。**

- **同会话/同写入方目录状态下：会（已实测重演）。** 时间线（`scene-cli` 留档 + 归档，见
  `SAVE-WRITE-ATTRIBUTION.md` §4.1 P5）：
  
（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

  ⇒ **文件级恢复之后、第一次真正的 save 就把同样两条又补回来**。
- **不是「每次 save 都加」**：大量 save 是 `40→40` / `42→42`（§4 时机）。
  即：复发的**充分条件**是「写入方内存里的目录仍比盘上多」，不是 save 本身。
- **未决（不编）**：**编辑器/游戏重启后**写入方内存是否会重同步回 40——**无证据**。
  故「跨会话是否复发」= **unresolved**。
- **可操作含义**：任何「save 后拿关卡目录做验收/差分」的流程，**必须在 save 后重新解 `field 6`**，
  并**预期** `40→42` / `field46 1→2` 这一对变化——**不要**把它当成「我们写坏了」。
  另：`missing-entry-id` **不可当必删损伤**——它可能是 `id==0` 被 proto3 省零值而隐形（U2，见
  `TAB-DIRECTORY-MINE.md` §5.5）。

---

## 6. 复现命令（全部只读）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


工具自测：`python -m pytest test_level_directory.py -q` → **12 passed**。

---

## 7. 本文的边界（不掩饰）

- **未连桥、未发报文、未碰游戏/编辑器、未重启 helper**：所有断言来自**只读的 `.gil` 字节**、
  **仓内留档**（`scene-cli` before/after、`upload-audit-20260919`、`write-attribution.log`）与**静态源码**。
- **「写入方内存里为何多两条」未坐实**（U1）：本文只证**写入方写的**，不证**它内存里为什么多**。
- **无 id 那条 = `id==0`（合法隐形）还是「从未赋值」**：磁盘上同一串字节，**不可区分**（U2）。
- 「`Temp/` 镜像与 `Save_Level` 逐字节相同」抽验了 `1830`/`1842` 两对；其余按 `level_directory` 的条目数/defect 一致判定。
- **本范围之外**（未来的新存档、其它账号）不在本断言内。
