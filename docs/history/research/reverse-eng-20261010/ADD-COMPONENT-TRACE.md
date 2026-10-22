> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# #1 追 — 编辑器 UI「添加通用组件」那条路到底走不走得通

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。未连桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档。
证据来源：仓内反编译语料 `.runtime/editor-catalog/resolved/`（12,375 个 `.cs`）+ 仓内目录库
（`frontend.db` / `backend.db`）+ **当前安装的 7.1 编辑器程序集** `C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\BeyondEditor.dll`
（只读解出字符串表，见 §0）。
> `文档写了什么` / `工具能做什么` / `真机验证过什么` 三层分开。**本文件全部是静态结论，无一条真机**。
> **⚠️ 口径（2026-10-11）**：本文列出的多个检索面（前端操作 / 后端 `command_route` / 串表 / 反编译 `.cs`）
> **不是互相独立的层**——它们同取一份 legacy build 的不同抽取视图；本负面**真正的独立轴只有两代构建
> （7.0 / 7.1）**，7.1 串表检索带**正面控制**（见 `CLAUDE.md` §五）。下文原「独立」措辞据此放宽。

---

## 0. 一句话结论

- **「添加通用组件」在命令面上不存在——这一条现在同时被 legacy 与 7.1 两个 build 证伪。**
  我把当前安装的 7.1 编辑器程序集（SHA-256 `565dda11…678a`，正是 `tools/editor-catalog/string_table.py:228` 的
  pinned profile `editor-7.1`）的混淆字符串表**离线解出**（2,985 条，plaintext SHA 与 profile 完全吻合），
  在里面查：`AddComponent` / `CreateComponent` / `AttachComponent` / `InsertComponent` = **各 0 命中**；
  `ForEditObj` 家族只有 `AddInstructionGraphForEditObj` / `DeleteComponentForEditObj` / `ModifyFactionForEditObj`。
  **7.1 的命令面与 legacy 一模一样，组件命令仍然只有两条，都是删**（证据 §3）。
- **「加组件」也不是一条消息**：唯一承载组件写入的消息通道是 **2001**，全仓**只有一个发送点**
  （组件字段编辑器 `…YWlUeFKpEU3Lh8YnZ6Mj.cs:475`），载荷是一条 **属性值 set**（target = 已存在的组件），
  语义是**改**不是**加**（证据 §4）。
- **组件集合的两个 appender 只有反序列化器**：全程序集里往 `entity.WlJiSPfnM3R()` /
  `obj.YlJitG20qEt()` 里 `Add` 组件的地方，只有「从 proto 读实体」这一条路（证据 §5）。UI 侧**没有**调用者。
- **新结构事实（可直接用于落盘写组件）**：一个组件在实体序列化里就是
  `wFyeWxvUrZ4ClLJlFKGm.d5t5h9vUZHeCSba2oH5p { bool enabled, BeyondCompType type, P6C0t14… config }`（§6）。
  ⇒ 想让 M1/M4/M5 出现，「加组件」最现实的落点是**写存档侧那条 proto 记录**，不是桥命令。

**排序结论（§7）**：① 本地模型改动 + 存档持久化（结构性位置存在、但 UI 调用者未定位）——**最可能**；
② 2001 消息带 create 变体——**证据反对**；③ 折叠常量命令——**已被 7.1 完善字符串表证伪**。

---

## 1. 本轮检索范围（"搜不到"要能被复核）

| 检索对象 | 位置 | 方法 | Add 组件命中？ |
|---|---|---|---|
| **7.1 编辑器程序集字符串表** | `D:\games\…\BeyondAssistEditor\BeyondEditor.dll`（18,404,248 B，SHA `565dda11…`） | `python tools/editor-catalog/string_table.py extract` 离线解表（2,985 条）→ `.runtime/scratch/editor71-string-table.json` | **0**（只有 2 条 Delete） |
| 7.1 程序集 `#Strings` 堆（类型/方法/枚举名） | 同上 DLL | 只读 ASCII 扫描 | 组件类型枚举 `BeyondCompType*` 46 名齐全；无 Add* |
| legacy 反编译前端 | `.runtime/editor-catalog/resolved/`（12,375 `.cs`） | Bash `grep -rI` | 0（只有 2 条 Delete；见 §3） |
| legacy 混淆字符串表 | `.runtime/editor-catalog/string-table.json`（2,830 条） | JSON 全表 | 0 |
| 字面量→类索引 | `.runtime/editor-catalog/literal-to-types.json`（2,734 字面量） | 反查 | 组件相关字面量只落在 4 个类（§5），无 Add |
| 前端操作名 | `frontend.db → operation`（44 行） | SQL 全表 | 0 |
| 后端命令路由 | `backend.db → command_route`（38 行）/ `dispatch_entry`（41 行） | SQL 全表 | 0 |
| 编辑器 UI 文案 | `textmap-chs.json`（7,743 条，含 935 条 `UI_`） | 全表搜 `组件` / `添加` | `添加通用组件` **不存在**（§8 重要旁证） |

**关键升级**：legacy 语料（resolved/ + string-table.json）来自**另一个 build**（`string_table.py:247` 的
`editor-legacy` profile，2,830 条）。**本轮第一次把当前 7.1 build 的表也解出来**（2,985 条），
所以下面的负面结论**不再受"语料是旧 build"的怀疑**。

---

## 2. 起点文件：删组件的那个 VM，逐行

`pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW`（组件列表**行** VM，`:14` 继承 `zXb1MsuKy4a1oLegx8Lr`）。
**这就是一行组件，从头到尾只有两个动作按钮：**

| 成员 | file:line | 行为 |
|---|---|---|
| `vmBtnDelete`（按钮） | `…yn34VuuuO5tEgsICYDBW.cs:38` | 绑定到 `s9puu4bEcx2` |
| `vmBtnShow`（按钮） | `…yn34VuuuO5tEgsICYDBW.cs:26` | 绑定到 `etruuExZdxU` —— **空实现**（`:89-91`，方法体只有 `{}`） |
| `etruuExZdxU()` | `:89` | 空 |
| `s9puu4bEcx2()` | `:93-158` | 删除派发器；按宿主类型分三条 |
| `eTxuuH9NkZV(vm, obj, uint componentId)` | `:77-87` | 工厂：行标题 = `((jaUof90C3Ncl5BAJri4x)componentId).ToString()` |

`s9puu4bEcx2` 里的**三条命令字面量**（这是该文件及其邻域**全部**命令调用）：

| file:line | 命令 | service | 触发条件 |
|---|---|---|---|
| `…yn34VuuuO5tEgsICYDBW.cs:107` | **`DeleteComponentForEditObj`** | `beyondEditObjService` | 宿主是实体（`AooSwxiSm6Ktx99ovmnr`）时 |
| `…yn34VuuuO5tEgsICYDBW.cs:127` | `RequestPrefabInstance` | `beyondEditObjService` | 宿主是 prefab 视图（`QD5e7QiwC7ij9WZWqtx3==7`）时 |
| `…yn34VuuuO5tEgsICYDBW.cs:152` | **`DeleteComponentForPrefab`** | `beyondEditObjService` | prefab 分支 |

三者的派发形状与桥已在用的 `ModifyFactionForEditObj` 完全同族：
`BrjMRrl2xRXv5aqZQkDJ.xyVYfsr3qg0(producer, service, "命令名", null, List<Param>)`（`:107`），
args = `[uint(entityId), uint(componentId)]`。**这一行里没有任何 Add。**

### 2.1 邻域（siblings）——谁会生成这些行、谁持有组件集合

| 文件 | 做什么 | 命令字面量 |
|---|---|---|
| `wBtNTpLgF5ypQBEO16Cw.cs` | 一行 VM 的工厂**委托类型**（`delegate yn34VuuuO5tEgsICYDBW f(vm, obj, uint)`）；`:5` | 无 |
| `LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs` | 列表 VM：`EY3uujy9Ayc.YlJitG20qEt()` 逐组件建行（`:83,:127,:155,:158`） | 无 |
| `yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs` | 列表 VM：`WlJiSPfnM3R()` 逐组件建行（`:109,:136,:238`） | 无 |
| `GyCglBuuW1FDG96axBEc.b2O1FruugQB8cNXIxANQ.cs` | 列表基类：`text` + `vmItems`（`:15,:27`） | 无 |
| `y5e8iEuuN3HInfNSwGBo.cRuNQ5uuRMPpkdj2v1sp.cs` | 列表基类：持 `hRwGGsitgmhQZo9c1XOp EY3uujy9Ayc`（`:10`） | 无 |
| `IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs` | 组件**字段**编辑器（点"详细编辑"展开）；非加 | 2001（§4） |

⇒ **这一整族 VM（行 + 列表 + 基类 + 字段编辑器）里没有任何 add 命令。**

---

## 3. 「Add 组件」命令名：两个 build 都精确负面

### 3.1 当前 7.1 build（本轮新证据，决定性）
- 程序集：`C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\BeyondEditor.dll`
  - 18,404,248 B，SHA-256 `565dda11883f0220bae050438fcf52b2288f26b61ed656e2b4cd6d69b41a678a`
  - 正是 `tools/editor-catalog/string_table.py:228` 的 pinned profile **`editor-7.1`**（`entry_count=2985`）。
- 离线解表（`python tools/editor-catalog/string_table.py extract …`）→ **2,985 条**，
  `tableSha256` 与 profile 的 `plaintext_sha256` **完全一致**（`ec077606…a74`）。
- 在该表中搜命令名：

  | 字面量 | 命中 |
  |---|---|
  | `AddComponent` / `CreateComponent` / `AttachComponent` / `InsertComponent` | **0 / 0 / 0 / 0** |
  | `DeleteComponentForEditObj` / `DeleteComponentForPrefab` | 1 / 1 |
  | `AddInstructionGraphForEditObj` / `AddInstructionGraphForPrefab` | 1 / 1 |
  | `ForEditObj` 全部 | 3 条（= AddInstructionGraph + DeleteComponent + ModifyFaction） |
  | `ForPrefab` 全部 | 3 条（= AddInstructionGraph + DeleteComponent + ModifyFaction） |

- **为什么这条负面比以前硬**：`tools/editor-catalog/string_table.py` 的 docstring 说明——编辑器程序集
  **几乎不把字符串字面量放在 `#US` 堆里**，字面量以「(加密 manifest 资源里的) 字节偏移」形式存在，
  这个被解出的偏移表**就是**字面量全集（profile 用 `entry_count` 与 plaintext SHA 双重钉死）。
  ⇒ **"折叠常量" 这个老盲区对 7.1 build 不成立**：任何命令名，只要作为一个字面量存在，就会在这 2,985 条里。
  `AddComponent` 不在 ⇒ 它不作为字面量存在于 7.1 编辑器程序集。

### 3.2 legacy build（复核）
- `string-table.json`（2,830 条）= `string_table.py:247` 的 `editor-legacy` profile；同样只有 2 条 Delete。
- `.runtime/editor-catalog/resolved/` 12,375 `.cs`（Bash `grep -rI`）同样 0 命中。
- `frontend.db → operation`（44 行）、`backend.db → command_route`（38 行）、`dispatch_entry`（41 行）
  全表 0 命中 —— 与既有 `COMPONENT-WRITER-MINE.md` §5、`CLAUDE.md` §六(a) 一致。

**⇒ 结论：组件命令在**两个 build**的命令面上都只有 `DeleteComponentForEditObj` / `DeleteComponentForPrefab`。
"加组件"没有命令名落点。**

### 3.3 `.NET` 用户串旁证（为什么不能只看 `#US`）
用 `tools/editor-catalog/extract-user-strings.py` 扫安装 DLL 的 `#US` 堆只得 **15 条**
（`" is tampered."`、`"Debugger Detected"`、`{11111-22222-30001-00001}` …），
而同一 DLL 的 `#Strings` 堆（类型/方法名）可读、含 `vmBtnDelete` / `vmComponents` / 46 个 `BeyondCompType*`。
⇒ 该程序集**字面量走加密 manifest 资源**，`#US` + `#Strings` 明文扫描都会漏。**必须走 `string_table.py`。**

---

## 4. 「加组件」是不是一条消息？——不是，2001 是「改」

前端全部出站消息号（Bash 抽 `PHCi086M7o5` 发送点）：
`1001/1010/1011/1013/1014/1016/1018/1019/1024/1025/2001/3001`。
其中 **2001 只有一个发送点**，来自组件字段编辑器：

- `IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:475`
  `…xyVYfsr3qg0(vSwq2Ui3deULA6AUjQxt<mCglXsi0ijgrwvs0SPGh>.pZgi3PiTIE8(), 2001, gcxejEBKDw4nOrlXagP, …PHCi086M7o5)`。
- 触发：该 VM 收到事件 `69`（`:303` `case 69u:`）→ 调 `QS2KpiuBk8S`（`:315`）→ 组包 → 发 2001。
- 该 VM 持有的是**一个已存在的组件**：字段 `LudM06iCRNk4iFkwqKIW nWiKpMFrtFD`（`:40`），
  `GetKey()` 返回该组件的 id（`:161-174`）。
- 载荷 proto `gcxejEBKDw4nOrlXagP`（`TDkCIQBu2aiStr6db9a`）只有一个字段
  `hlS35JtRO42rGu9MG9Q jsuBDFvMyV = 1`（`：46`；`WriteTo` `:159-187`）；
  再往下 `hlS35JtRO42rGu9MG9Q` 是「keyPath(field1/field2) + uint + uint + value oneof(11..16)」结构
  （`jEcbTytNr1rcKPlqIj4.hlS35JtRO42rGu9MG9Q.cs:604-720` 的 `WriteTo` tag 序列 10/16/88/96/106/114/122/130）。
  value oneof 的具体类型在 `w1dlm22McSktPJ0Cct4.vD12Hm2PObeNaaZvWDG.cs`（int/bool/float/string/List<int>）。

⇒ **2001 = 给"已存在的组件"的某个属性 set 值。它是"改"，不是"加"，也不是"建"。**
（这与既有 `COMPONENT-WRITER-MINE.md` 的判断一致；本轮补上了「全前端只有这一个 2001 发送点」。）

---

## 5. 组件集合的写入者：全程序集只有反序列化器

组件集合有两处：
- 实体：`Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.WlJiSPfnM3R()`（`…AooSwxiSm6Ktx99ovmnr.cs:204`，字段 `:43`）
- 可编辑对象基类：`nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp.YlJitG20qEt()`（`:205`，字段 `:42`）

用 `literal-to-types.json` + `grep -rln X66ijdVvJ0k`（集合的 `Add`）反查，**写 `WlJiSPfnM3R()`/`YlJitG20qEt()` 的
调用点全在反序列化路径里**：

| file:line | 场景 |
|---|---|
| `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:587` | 实体从 proto `ODUiR8vROJUfpkA4NTYP` 反序列化时建组件 |
| `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26353` | 同上（大文件的实体反序列化） |
| `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.cs:26788` | 同上（`hRwGGsitgmhQZo9c1XOp` 分支） |

其余 `X66ijdVvJ0k` 命中都属于**别的集合**（节点图 `JVhTwtKizlScEvUHNJeZ`、`s0gCx5K7DdTgRPKNulO5` 等）。

**⇒ UI 侧没有任何一处"新建一个组件对象 → 追加到实体组件集合"。加组件的 UI 调用者在托管代码里没定位到。**

### 5.1 组件相关的全部字面量落点（反查索引）
`literal-to-types.json` 里与组件有关的字面量，只落在这些类：

| 类 | 相关字面量 |
|---|---|
| `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW` | `DeleteComponentForEditObj` / `DeleteComponentForPrefab`（行 VM） |
| `RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs` | `Template_ComponentEdit_*`、`…/BeyondComponentEditPanel.xaml` 等 URI（**资源定位器**，非面板） |
| `kOYGbfKf8rLXL3Yn9ngl.hpN0LEKfMOFul7DFu62g` | `vmComponents`（视口把组件画成矩形） |
| `V1PDtpKpmi2LIfJEp4lQ.hl1UqcKpaCyX3lKnXP7L` | `componentName`（字段编辑器头部） |

**没有**任何类的字面量集合里出现组件 + Add。三个带 `vmBtnAdd` 的类分别是
引脚列表（`VUTADHugiCOt9llqLfEe.…`）、属性值列表（`NOU2oMKf5p2hDc7bv3WW.…`，`:79` 拼 `"添加"+name`）、
攻击标签/音效选项（`JAumjSKZeqeEADH9HWaA.…`）——**都不是组件面板**。

---

## 6. 新结构事实：一个组件在序列化里长什么样（可直接落盘）

实体 proto `ODUiR8vROJUfpkA4NTYP` 里的组件项 = `wFyeWxvUrZ4ClLJlFKGm.d5t5h9vUZHeCSba2oH5p`：

| 字段 | 类型 | 含义 | file:line |
|---|---|---|---|
| `m3svUtjaRs9` | `bool` | enabled | `wFyeWxvUrZ4ClLJlFKGm.d5t5h9vUZHeCSba2oH5p.cs:19` |
| `teJvUy0dZuF` | `jaUof90C3Ncl5BAJri4x` | **组件类型** | `:21` |
| `FUcvUIGS5Mw` | `P6C0t14wz3id5usWm0Uu` | 组件配置载荷（229 KB 的 oneof 大消息） | `:23` |

组件类型枚举 `jaUof90C3Ncl5BAJri4x`（`QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-49`，带**非混淆常量名**）：
`BeyondCompTypeCollision=8`、`BeyondCompTypeClientTrigger=5`、`BeyondCompTypePopUp=40`、
`BeyondCompTypeStuffBag=33`、`BeyondCompTypeEquipStuffBag=34`、`BeyondCompTypeShop=35`、
`BeyondCompTypeCursorCollision=45` … 共 46 值 + `Arraysize=47` 哨兵。
**该枚举在当前 7.1 DLL 的 `#Strings` 堆里 46 名齐全**（只读 ASCII 扫描），与 legacy 完全一致。

---

## 7. 排序判决

| 排名 | 候选路径 | 证据 | 判决 |
|---|---|---|---|
| **1** | **本地模型改动 + 存档持久化**（把组件追加进实体组件集合 → 随关卡存档走） | 组件是实体序列化的一部分（§6）；组件集合的 `Add` 存在（§5）；命令面/消息面都没有 add（§3/§4） | **最可能**。但**托管代码里没找到 UI 调用者** —— 要么它是 XAML 内联调用（无字面量、无法归因），要么该按钮只在更新的 build 里 |
| **2** | 2001 消息带 create 变体 | 2001 全仓只有 1 个发送点（组件字段编辑器），target 是**已存在**的组件（§4） | **证据反对**。它是"改属性" |
| **3** | 折叠常量命令 `AddComponentForEditObj` | 7.1 的字符串表就是字面量全集（2,985 条、plaintext SHA 钉死）；`AddComponent` 不在（§3.1） | **已被证伪**（至少对 7.1 build） |

**实用结论（给 M1/M4/M5）**：
- **别在桥的命令面上找"加组件"** —— 两个 build 都没有。
- 想真做出组件，现实的第一刀是**写存档 side 的组件记录**（§6 的 `d5t5h9vUZHeCSba2oH5p`：
  enabled + 类型枚举 + 配置载荷），把 `.gil` 里的实体补上这条；或先做「只读读回实体组件集合」把 componentId 编号坐实
  （与 `COMPONENT-WRITER-MINE.md` §7 的探针方向一致）。
- **下一步最值钱的验证**：把 **7.1 的 `BeyondEditor.dll` 反编译**（仓内已有 `tools/editor-catalog/ilspy-dump/`，
  且 7.1 的字符串表已经能解），然后按 §2 的形状找**面板级 VM**（列表 VM 的宿主）有没有 handler。
  legacy 的反编译语料（本文件 §2/§5 所用）**不是** 7.1，这是当前最大的取证空洞。

---

## 8. 重要旁证：连"添加通用组件"这条 UI 文案都取不到

`UI_` 文案来自 `Resource/Json/TextMap/CHS/*.mihoyobin`，已解为 `textmap-chs.json`（7,743 条，其中 `UI_` 935 条）。
全表搜 `添加通用组件` / `添加组件` / `通用组件` = **0 命中**；`组件` 仅 29 条，绝大多数是**节点名**，
组件相关的 UI 键只有 `UI_BEYOND_EDITOR_UI_COMPONENT_CONFIG_CURSOR_COLLISION`（"光标碰撞盒"）与
`UI_BEYOND_EDITOR_ESP_LUTNAME_CAMPOVERLIMIT`（"组件数量达到上限" = 有上限 ⇒ 暗示能加，但只是**暗示**）。
程序集字符串表（7.1，2,985 条）里也没有任何中文"组件/添加"组合，只有一个孤字 `'添加'`（`:79` 的 `"添加"+name` 拼接）。

⇒ 官方文档引用的按钮文案「添加通用组件」**在本机可读的文案源里不存在**（文档层与可读资源层的分歧），
说明该面板的 UI 文案在**我们没解到的资源**里（或文档描述的是另一版本 UI）。这条**削弱**了"按钮就在当前 build 里"的前提。

---

## 9. 本次新增/触碰的文件

- **新增**：本文件 `docs/research/reverse-eng-20261010/ADD-COMPONENT-TRACE.md`
- **新增（scratch 产物，工程内）**：`.runtime/scratch/editor71-string-table.json`（7.1 字符串表，2,985 条）
  与 `.runtime/scratch/installed-editor-userstrings.txt`（安装 DLL 的 `#US` 堆，15 条）
- **未改动**任何既有文档/代码；未连桥、未发报文、未碰游戏或编辑器、未写存档。

---

## 10. 复核轮（#1 任务，2026-10-10 追加，append-only）

**口径**：纯离线只读。未连桥、未发报文、未碰游戏或编辑器、未写存档。**未读任何图片或 PDF**。

### 10.0 判决（一个字）

**SURVIVES** —— §0/§3/§4/§5 的负面结论**全部复核通过**：**编辑器 UI 命令面上不存在「加组件」这条路。**

### 10.1 起点文件 + 邻域：逐个 sibling 按钮（任务第 3 步，全部亲自复读）

`pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW` = **一行组件**（不是面板）。它**只有两个按钮**，无第三个：

| file:line | 成员 | 行为 |
|---|---|---|
| `…yn34VuuuO5tEgsICYDBW.cs:26-36` | `vmBtnShow` | 绑定 `etruuExZdxU` |
| `…yn34VuuuO5tEgsICYDBW.cs:89-91` | `etruuExZdxU()` | **空实现**（方法体 `{}`，无任何调用） |
| `…yn34VuuuO5tEgsICYDBW.cs:38-48` | `vmBtnDelete` | 绑定 `s9puu4bEcx2` |
| `…yn34VuuuO5tEgsICYDBW.cs:93-158` | `s9puu4bEcx2()` | 删除派发器，三条命令 |
| `…yn34VuuuO5tEgsICYDBW.cs:107` | 派发 `"DeleteComponentForEditObj"` | 宿主=实体（`AooSwxiSm6Ktx99ovmnr`） |
| `…yn34VuuuO5tEgsICYDBW.cs:127` | 派发 `"RequestPrefabInstance"` | 宿主=prefab 视图（`==7`） |
| `…yn34VuuuO5tEgsICYDBW.cs:152` | 派发 `"DeleteComponentForPrefab"` | prefab 分支 |
| `…yn34VuuuO5tEgsICYDBW.cs:77-87` | 工厂 `eTxuuH9NkZV(vm, obj, uint)` | 行标题 `((jaUof90C3Ncl5BAJri4x)id).ToString()` |

邻域（**整族 VM 里都没有 add**）：

| 文件 | 角色 | 按钮/命令 | file:line |
|---|---|---|---|
| `…pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs` | 行 VM | 仅 Show(空)/Delete | 见上 |
| `wBtNTpLgF5ypQBEO16Cw.cs` | 行工厂**委托包装** | 无 | `:5` |
| `…LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs` | 列表 VM（`YlJitG20qEt()` 逐组件建行） | 无按钮、无命令 | `:83,:127,:155,:158` |
| `…yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs` | 列表 VM（`WlJiSPfnM3R()` 逐组件建行） | 无按钮、无命令 | `:109,:136,:238` |
| `…GyCglBuuW1FDG96axBEc.b2O1FruugQB8cNXIxANQ.cs` | 列表基类 | 只有 `text`+`vmItems`，**零按钮** | `:15,:27` |
| `…y5e8iEuuN3HInfNSwGBo.cRuNQ5uuRMPpkdj2v1sp.cs` | 列表基类 | 只持 `EY3uujy9Ayc`（实体），**零按钮** | `:10` |
| `…IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs` | 组件**字段**编辑器 | 2001（改值，非加） | `:475` |

⇒ 结论与 §2 一致：**该行 VM 及其整族邻居里没有任何 add 按钮或 add 命令。**

### 10.2 全按钮词表：没有 `vmBtnAddComponent`（任务第 3 步加码）

对 `resolved/` 全语料抽 `"vmBtn*"` 字面量，共 **70 个按钮名**。含 `vmBtnAdd`(3 处)、`vmBtnAddListItem`、`vmBtnAddParam`、`vmBtnAddSignal`、`vmBtnRemove`、`vmBtnDeleteItem`、`vmBtnEditStruct`…
**`vmBtnAddComponent` / `vmBtnCreateComponent` 不存在。** 三个带 `vmBtnAdd` 的类逐个人肉确认**都跟组件无关**：

- `NOU2oMKf5p2hDc7bv3WW.xtkujkK6zWqExfD35wGn.cs`：**节点图 List 值编辑器**（`vmValueList` of list 类型）。
  - `:25` `vmBtnAdd` 绑定到 `hwCKfOGU6KP` —— **`:219-221` 又是空实现 `{}`**；
  - 真正的"加"发生在**集合变更回调** `bpcKfm33bGq`（`:95-163`，`:144` 新建 `dOU8RoK6skKVyihI4ffy` 并 Add 到值列表）——是"给 List 值加一项"，**不是给实体加组件**。
  - 工厂 `wLHKfam23Sb`（`:49`）在 `P_1.KiPKKaQUNLS() != List` 时返回 null ⇒ 只服务 List 型节点变量。
- `JAumjSKZeqeEADH9HWaA.eUb5JpKZyhXaWRtAiThB.cs`：攻击标签/音效选项（§5.1 已记）。
- `VUTADHugiCOt9llqLfEe.XLpHI4ug3Wc5YW1khSFy.cs`：引脚列表。

### 10.3 字面量面复核（任务第 2 步：确认"是加不是改/删/拷"）

对 `resolved/`（12,375 `.cs`）Bash 独立复核：

| 查询 | 命中 |
|---|---|
| `AddComponent` | **0** |
| `CreateComponent` | **0** |
| `AttachComponent` / `InsertComponent` | **0 / 0** |
| `DeleteComponentForEditObj` | 1（仅 `pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW.cs`） |
| `DeleteComponentForPrefab` | 1（同上） |
| `AddInstructionGraphForEditObj` | 1（`VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs`，= 节点图绑定，非组件） |

全语料 PascalCase 命令式字面量共 **212 条**，组件相关的只有两栖 Delete；`Add*` 家族只有 `AddInstructionGraphForEditObj`（图）。

### 10.4 后端/前端命令面复核（任务第 4 步：generic channel 里有没有"设实体属性=组件"）

- `docs/research/beyondeditor-backend/db/backend.db → command_route`（38 行）里组件命令**只有** `DeleteComponentForEditObj` `(int32 实体id, int32 组件id)` 与 `DeleteComponentForPrefab` `(int32 prefabId, int32 组件id)`。**无 AddComponent。**
- 同库 `dispatch_entry`（41 行）同样只有这两条组件命令；`AddInstructionGraphFor*` 是图。
- `docs/research/beyondeditor-frontend/db/frontend.db → operation`（**44 行 = 前端全命令表**）里没有 `AddComponent`/`CreateComponent`。
- **generic 通道**：`frontend.db → channel` 的 `1001-1024` 逐行读过——
  - `1001` = **编辑器首帧**，payload = 单个 length-delimited string（16 B），**不是"设实体属性"**（row 15）。
  - `1018` = 公共命令通道（editor->peer），但载荷是 **(req#, 服务名, 命令名, 参数表)** —— 走**具名命令哈希分派**，而"加组件"这个命令名在两 build 都不存在。
  - `1013/1015/1021/1023` = 分发器**显式忽略**；其余 `1004/1008/1009/1010/1022/1025` = "有 case，用途未证"。
  - ⇒ **不存在一条"泛化 set-entity-property，其 property 可以是组件"的通道。**
- `2001`（组件字段编辑器出站）：复读 `…YWlUeFKpEU3Lh8YnZ6Mj.cs:475` 确认 `PHCi086M7o5(2001, gcxejEBKDw4nOrlXagP, …)` 是**唯一发送点**（另一处 `GWqAg83zFaJvFpOYIPy3.epbDga3zjH0G4a8XYEO8.cs:66` 是 `Add(2001, 类型注册)`，注册≠发送；`XvpSBIuvo…` 的 2000/2001 是无关枚举）。**2001 = 改已存在组件的某个属性值，是"改"不是"加"。** 与 §4 一致。

### 10.5 残余不确定性（不改变判决，但要写明）

1. **静态不可见路径**：若"加组件"是 XAML 内联 `Click` → code-behind 直接 `collection.Add(...)`，字符串面/命令面**都看不见**（本仓正是按钮 handler 常为空 `{}`、真正工作在集合变更回调里的风格，见 §10.2）。这条**无法用静态字符串法证伪**，是本判决唯一的软肋。
2. **分发表非穷尽**：`backend.db → backend_gap` 记 —— `beyondInstructionGraphService/beyondEffectService/beyondAudioService` 的 native 分发器**未定位**；且存在全局可插拔钩子 `0x768d80e` 可**绕过哈希表**。所以"不在 command_route"是很强、但非绝对的不存在证明。
   （缓解：组件命令属 `beyondEditObjService`，该服务 15/15 命令**已对上** `0x914de40`，组件 add 若走后端**本应**落在同一张表。）

### 10.6 结论（对 §7 的补充）

**判决 SURVIVES：命令面 / 消息面 / 字面量面三处，「加组件」均不存在（两个 build、前后端一致）。**
⚠️ **口径（2026-10-11）**：这三处**不是三个独立层**——同取一份 build 的不同抽取视图；本负面**真正的
独立轴只有两代构建（7.0 / 7.1）**（`CLAUDE.md` §五）。原「三处独立」的完整本正面，已放宽为「两个 build 同向」。
最现实的落点仍是 §7 排第 1 的 **写存档侧实体组件记录**（`wFyeWxvUrZ4ClLJlFKGm.d5t5h9vUZHeCSba2oH5p`：enabled + `jaUof90C3Ncl5BAJri4x` 类型 + 配置载荷），
而非桥命令。**M1/M4/M5 的 scene 半边，不要指望在命令面上找到"加组件"。**

