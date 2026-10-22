> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #3 挖 — 修订号的代价：还有多少个 R 可用

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**。
本轮只做了两件只读动作：①列出构建目录的文件名与大小（`os.listdir` + `os.path.getsize`，不读字节）；
②读仓内 C# / ps1 源码与 `docs/` 记录。

> 按 `CLAUDE.md` §一.3、§五：**`文档写了什么` / `工具能做什么` / `真机验证过什么`** 三层分开标。
> 本文件的结论**全部是静态的**（读文件名、读源码、读仓内记录）；**没有一条是本轮真机跑出来的**。
> 凡"有实现、没跑过"的，一律标 `只离线`；**"搜不到"≠"不存在"**，凡搜过的范围都写明。

---

## 0. 一句话结论

- **修订号本身不是瓶颈，注入"机会"才是。** R<N> 是一个 int，理论上还能烧二十亿个；真正稀缺的是
  **一次注入机会 = 一个 5 分钟租约**（`BridgeServer.cs:37`）。截至本文件写成，构建目录里已沉积
  **260 个修订号（R2..R269）**，磁盘合计约 **41 MB / 549 个文件** —— 钱不多，但单调增长。
- **记忆里那句"同一修订在同一进程只能注入一次"是被糊掉的过度概括，源头比它弱。**
  把关的**不是**静态标志 `_startAttempted`（它在 `finally` 里被清零，`ManagedBridge/Entry.cs:233`），
  而是 `ManagedBridge/Entry.cs:73` 的"**上一个服务器还活着**"，而它只活**一个 5 分钟租约**。
  ⇒ **租约过期后，同一个修订可以再注入**（仓内已实测，见 `PROGRESS-LITE.md:510`）。
  `next-revision.ps1` 文件头与 `Entry.cs` 的 docstring 都还写着"静态标志 = 永久烧毁"，**那两处是陈旧的**。
- **但"要一个新能力"仍然只有升修订一条路** —— 新 op 意味着新的编译产物。
- **⇒ 排期建议：修订号要按"能力批次"烧，不要按"单个 op"烧。** 一个修订可以装载 K 个新 op（payload 是
  一个 DLL，R269 里已经装着整面桥 op（见 tools/gameplan/tests/test_doctrine.py）的操作面）；把**只读探针**与**待发的写入能力**并进同一批次，
  一次注入把该做的活干完。当前 260 修订 / 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）的比价说明**烧得比收货快**，批处理能把这个比例压回来。

---

## 1. 盘点：盘里到底有多少个 R（问题 1）

**方法**：对 `tools/editor-bridge/ManagedBridge/bin/Release/net8.0-windows/` 做 `os.listdir`，
正则 `Net8R(\d+)` 取全部数字去重（**不读 DLL 字节**）。

| 指标 | 值 |
|---|---|
| **distinct `Net8R<digits>` 数** | **260** |
| **范围** | **R2 .. R269** |
| **区间内的缺口**（有号无产物） | R96、R98、R105、R197、R215、R226、R228、R243（共 8 个） |
| R1 | 从未出现（起始号就是 R2） |
| `Miliastra.Bootstrap.Net8R<n>.dll` | 260 个（每个修订一份） |
| `Miliastra.EditorBridge.Net8R<n>.dll`（payload） | 94 个（只在 R4–R66、R188–R214、**R264–R269** 三簇） |
| `...Net8R<n>.deps.json` | 64 个 |
| 目录累计体积 | 约 **40.9 MB / 549 文件**（bootstrap 每份 5,120 B；payload 每份 1,126,400 B） |

**260 个号的完整列表**：

（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

（即 2 到 269 全取，除去上面 8 个缺口。）

**两个"读数本身要说的话"**：

1. **目录是活的，不是快照。** 我第一次扫描时是 **259 个 / R2..R268**；几分钟后重扫已是
   **260 个 / R2..R269**（`Bootstrap/Entry.cs:16`、`load-bridge.ps1:29/32`、`new-scope.ps1:31/32` 同期已改写为 R269）。
   **另一路并行的会话在本轮进行中升了一次修订**。所以"还有多少 R"这个问题，答案永远是"你问的那一刻的数"。
2. **8 个缺口 = 被烧掉但没落地的号。** 缺口在区间内部，而 `next-revision.ps1` 的默认行为是 `current+1`
   （`:87`），出现缺口意味着**某个号被烧给了一次没成功/被弃用的构建**（版本串先改后构建失败，号即作废）。
   这是"失败的构建也吃一个号"的直接证据，也是批处理之所以划算的一个理由。
3. **payload 比 bootstrap 少 166 份，本轮未解释。** 每个修订应各有一份 bootstrap 与一份 payload
   （`next-revision.ps1` 先建两个工程再拷 bootstrap，见 `:150-166`）。payload 只在三簇存在。
   **静态无法判定**是"历史清理"还是"某段时期 payload 输出到了别处"。这**不是**无关紧要的整洁问题：
   `Bootstrap/Entry.cs:16` 是**按名字**去找同级目录下的 `Miliastra.EditorBridge.Net8R<n>.dll`，
   **payload 不在，那个号就再也注入不了**。值得单独查一次（本轮未查，仓内无 git 历史可追）。

---

## 2. 为什么"一次注入只能一次" —— 从源码看（问题 2）

注入到目标进程的链路（四处源，逐行）：

1. **`tools/editor-bridge/load-bridge.ps1:38-40`** —— 用 Snoop 注入器把 **bootstrap** DLL 注入目标进程，
   调 `Miliastra.Bootstrap.Entry.Start(settingsPath)`；`:38` 的 `loader.claim`（`FileMode.CreateNew`）是
   **每个 scope 只允许一次发射**。注释 `:37`：「A single launch attempt per scope. Do not remove this claim after failures.」
2. **`tools/editor-bridge/Bootstrap/Entry.cs:7`** 签名只吃一个 `settingsPath`；
   `:16` **把 payload 名硬编码**成 `Miliastra.EditorBridge.Net8R269.dll`；
   `:17` `Assembly.LoadFrom(payload)`；
   `:22` 反射调 payload 的 `Miliastra.EditorBridge.Entry.Start`。
3. **`tools/editor-bridge/ManagedBridge/Entry.cs`** —— 真正的门：
   - `:52` `private static int _startAttempted;`
   - `:62` `if (Interlocked.CompareExchange(ref _startAttempted, 1, 0) != 0) return CodeAlreadyStarted;`
   - `:73` `if(_server!=null && !_server.IsCompleted) return CodeAlreadyStarted;`
   - `:186-189` `UsedScopes`（键 `path:`/`pipe:`/`nonce:`）重放检测 + `:189` 上限 768
   - **`:233` `finally {Volatile.Write(ref _startAttempted,0);}`** ← **关键**
4. **`tools/editor-bridge/ManagedBridge/BridgeServer.cs`**
   - `:29-30` docstring：「**Nothing here ever unloads the host AppDomain**, terminates the host process, or invokes a reflected method.」
   - `:37` `internal static readonly TimeSpan Lease = TimeSpan.FromMinutes(5);`
   - `:62` `IsCompleted => Volatile.Read(ref _completed)==1`
   - `:139` `if(cleaned)Volatile.Write(ref _completed,1);` ← `IsCompleted` 只在**租约收尾且清理成功**后翻 1

**因果（为什么第二次被拒 —— 精确版）**：

- payload 是**按路径**加载的（`Entry.cs:17`）。`Assembly.LoadFrom` 对同一路径返回**已加载的那一份**，
  所以 payload 里的静态量（`_startAttempted` `:52`、`_server` `:53`、`UsedScopes` `:54`）都是
  **进程级、跨注入存活**，且**卸载不掉**（`BridgeServer.cs:29-30`；.NET 8 无 `AppDomain.Unload`，
  这条路径也不用可回收的 `AssemblyLoadContext`）。
- 于是第二次 `Start` 由两道门裁决：
  - `:62` 静态标志 —— **它在 `:233` 的 `finally` 里被清零**，因此它只挡**同一次调用期间的重入**，
    **不挡**更晚的第二次调用。**`next-revision.ps1` 文件头（约 `:5-15`）与 `Entry.cs` docstring（`:21-23`）
    把"永久烧毁"归因到这个标志 —— 这是与当前源码不符的陈旧说法。**
  - `:73` `_server != null && !IsCompleted` —— **这才是真正把人烧掉的闸**。服务器在跑（或收尾没完成）时，
    第二次注入返回 `CodeAlreadyStarted(=1)`。而服务器寿命 = **5 分钟租约**（`BridgeServer.cs:37`）。

**所以"同一修订同一进程只能注入一次"成立的范围是"那一个 5 分钟租约窗口内"，不是进程的一生。**

---

## 3. 不升修订，能不能注入两次（问题 3）

逐个回答用户点名的三条路：

- **(a) 卸载程序集 —— 不行。** `BridgeServer.cs:29-30` 明说本工程从不卸载宿主 AppDomain；payload 是
  `Assembly.LoadFrom`（`Entry.cs:17`）按路径加载的，.NET 8 没有 `AppDomain.Unload`，这条路径也没用
  可回收 `AssemblyLoadContext`。**没有卸载原语。**
- **(b) 换一个 bootstrap 旗标 —— 不行。** bootstrap 的契约只吃 `settingsPath`（`Bootstrap/Entry.cs:7`）并
  只转发它（`:22`）；没有旗标、环境变量或设置字段能去动 payload 的静态量。
  （`bridge-settings.json` 本身是**固定六成员**的严格 schema，见 `new-scope.ps1:25-26` 的注释 —— 也塞不进新字段。）
- **(c) 非静态守卫 —— 换了也没用。** 守卫确实是静态的（`:52`/`:62`），但它不是真正烧号的那道闸；
  换成实例守卫，挡路的仍是**还在跑的服务器**（`:73`）+ **5 分钟租约**，而且静态量反正照样跨注入存活。

**平话回答：能，但不是"随时能"。** 只要**上一个租约已经收尾**（`:73` 放行），**同一修订可以被再注入一次，不需要升修订**。
代价与前提：
- 等**一个租约**（≤5 分钟，`BridgeServer.cs:37`）；
- 要**换一个新 scope**（新 nonce / pipe / path），否则撞 `UsedScopes` 重放（`Entry.cs:186-189`）；
- 若那次收尾的 `CleanupForLease` **失败**（`BridgeServer.cs:134`，`cleaned=false`），`:139` 就不会把
  `_completed` 置 1 ⇒ **那个修订才真的被烧到进程重启为止**。

**证据分层**：
- **源码层（本轮，静态）**：与"租约过期后可再注入"**一致**（`:233` 清零 + `:73` 由 `IsCompleted` 放行）。
- **仓内记录层（真机）**：`PROGRESS-LITE.md:510` —— W23 明确写下「把关的是 **`Entry.cs:73` 的 5 分钟租约**，
  不是 `_startAttempted`；**实测证实同一 R233 在租约过期后可再注入 → 不需要 R234**」。
- **与记录层打架的陈旧说法**：`PROGRESS.md:110`（"同一修订在同一进程内只能注入一次"）、
  `PROGRESS.md:374`（把真因又归回 `next-revision.ps1` 文件头的静态标志）、`next-revision.ps1` 文件头本身。
  其中 `PROGRESS.md:374` 记录的"R261 第三次注入被拒"**并不矛盾** —— 那次拒绝发生在**租约窗口内**。
- **本轮局限**：我只读了源码，**没有重测**（只读、不发桥）。上面的"能"是**源码 + 仓内实测记录共同支撑**的结论，
  不是本轮新跑出来的。

**实用结论**：**升修订是"要新能力"的唯一路径，不是"再注入一次"的唯一路径。** 同一个修订再注入一次，
你买到的只是**一个新的 5 分钟租约**，没有任何新能力。

---

## 4. 代价与批处理（问题 4）

### 4.1 一次 `next-revision.ps1` 的成本（逐项，file:line）

| 步骤 | 代价 | 出处 |
|---|---|---|
| 改版本串 | **7 个文件、9 处** `Net8R<n>` 一起改；不一致就 `MIXED_REVISIONS` 抛错 | `next-revision.ps1:45` `$targets`、编辑循环 `:95-118`（`WriteAllText` 在 `:116`）、`MIXED_REVISIONS` 在 `:83`；9 处实测：`Bootstrap/Bootstrap.csproj:4`、`Bootstrap/Entry.cs:16`、`load-bridge.ps1:29,32`、`new-scope.ps1:31,32`、`ManagedBridge/Miliastra.EditorBridge.csproj:8`、`verify-fixture.ps1:8`、`verify-fixture-gameloop.ps1:8` |
| 全量重建 | **两个工程各一次 `dotnet build`**（ManagedBridge 先、Bootstrap 后，顺序不能反） | `next-revision.ps1:123-140`（`dotnet build` 在 `:125`） |
| 拷 bootstrap 到 payload 旁 | 1 次 Copy-Item（bootstrap 靠名字找 payload） | `next-revision.ps1:143` |
| 重新挂载哈希 | 新 scope 把两个新 DLL 的 SHA256 写进 `frozen.json`；loader 再逐项复核 | `new-scope.ps1:31-32`、`load-bridge.ps1:33-34` |
| 一次注入 | `loader.claim` 每 scope 一发射；**5 分钟租约**；**每次 graph 派发重算 2082 pin 哈希 ≈16 s** ⇒ 一租约放不下几十条指令 | `load-bridge.ps1:38`、`BridgeServer.cs:37`、`CLAUDE.md` §三、`PROGRESS.md:147` |
| 构建失败 | **号照样被烧**（版本串已改） | 第 1 节的 8 个缺口 |

**单份磁盘代价**：bootstrap 5,120 B + payload 1,126,400 B ≈ **1.13 MB/修订**（若 payload 保留）；
R269 payload 是 1,126,400 B 的**整份重建**（`AssemblyName` 一变即全量，无增量）。

### 4.2 能不能批量 —— **能，而且这才是省法**

**理由（来自结构，不是偏好）**：修订号是**每次注入**的资源，不是**每个 op** 的资源。

- payload 是**一个 DLL**，R269 里装着**整面桥 op（见 tools/gameplan/tests/test_doctrine.py）** 的操作面；新 op 只是往同一个 DLL 里多塞一个文件。
  ⇒ **一个修订可以承载 K 个新能力**，把"1 op 烧 1 号"变成"K op 烧 1 号"。
- 新 Adapter 文件必须写进**显式的 `<Compile Include>` 清单**（`ManagedBridge/Miliastra.EditorBridge.csproj:23`）。
  `next-revision.ps1` 的报错注释专门点名了"忘了加进去 = 恰好这样构建失败"。
  ⇒ 批处理把这份手改**摊销一次**，也把"漏加文件"的整批失败概率压到一次。
- 一次注入只给 **5 分钟租约**；把**只读探针 + 待发写入**并进同一修订、同一租约，是唯一能把稀缺窗口用满的做法
  （这正是 `build-plan` 批处理动作诞生的原因 —— `PROGRESS.md:147`：43 条指令 ≈11.5 分钟，必然超租约，只能并成 1 条）。

**代价（批处理的另一面，必须一起说）**：
- **整批共享一次编译**：任何一个新文件编译不过，**整批失败 + 烧一个号**（8 个缺口就是这种代价的化石）。
- **整批共享一个租约与一个"脏"进程状态**：写类能力放进同一批，一个跑歪就可能污染其余（`UsedScopes`、
  adapter 状态在同一进程里存活）。⇒ **只把"已单独验证过"的能力打包去发**；未验证的能力先在**一次性修订**里单独跑。

### 4.3 排期建议（面向未来能力工作）

1. **把修订号当"注入槽位"**，不当"版本号"：**一个工作会话一个槽位**，而不是一个 op 一个槽位。
2. **维护一个"待发队列"**：能力先在队列里**逐个跑通**（真机验证），再**一次性**打包进一个修订发出去。
3. **只读探针绝不为它单独烧号** —— 一律与当期写入能力并进同一批次（只读无风险，却照样吃一个号）。
4. **租约被烧不必然要升号**（第 3 节结论）：**等租约收尾**即可同号重注；只有在"不想等"或"要新代码"时才升。
5. **建一份 `修订 → 能力` 的账**：现在唯一的记录是那 260 个 DLL（外加 8 个缺口），
   而 `docs/` 里的修订清单是**按里程碑**列的、不是**按 DLL** 列的 —— 无从回答"R180 那一版装了什么"。
   这是这套机制的**真实记账缺口**，与"还有多少 R 可用"同等重要。

### 4.4 "还有多少个 R 可用" —— 直接回答

**数值上不封顶**（int，R2³¹ 级）；**运营上受限**：每个号 = 一次注入机会 = 一次 5 分钟租约 + 一次双工程重建 +
一次 7 文件改串。**可持续**（41 MB、260 个号，还远远不到任何硬上限），**但如果维持"1 op ≈ 1 号"的烧法就是浪费** ——
当前 260 修订 / 桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）（≈1.9）说明号烧得比能力收得快。**批处理是把它压回"K op / 1 号"的唯一手段。**

---

## 5. 局限与不吹（本轮搜过什么、没搜什么）

- **检索范围**：①`tools/editor-bridge/ManagedBridge/bin/Release/net8.0-windows/` 的文件名与大小；
  ②`tools/editor-bridge/` 下 `Bootstrap/Entry.cs`、`ManagedBridge/Entry.cs`、`ManagedBridge/BridgeServer.cs`、
  `next-revision.ps1`、`load-bridge.ps1`、`new-scope.ps1`、两个 `.csproj`、`verify-fixture*.ps1`；
  ③`PROGRESS.md`、`PROGRESS-LITE.md` 中与修订号相关的段落。**未读任何 DLL 字节，未跑构建，未连桥。**
- **本文件只新增自己**；不改 `STRUCTURE.md`、不改 `PROGRESS*.md`、不改任何源码（遵从"只拥有任务点名的文件"）。
- **"能同号重注"是源码 + 仓内记录共同支撑，不是本轮真机复现**；要坐实它，需要在租约收尾后对同一修订再发一次
  load —— 那需要一次真机动作，**本轮不做**（HARD RULES：不发桥/原生请求）。
- **payload/bootstrap 数量差（166）本轮只报现象、不给成因** —— 静态查不出，仓内又无 git 历史。
