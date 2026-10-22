> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 千星编辑器接口全量清单（编辑器 ↔ 游戏）

> **本文只做离线只读整理**：不启动、不连接、不探测、不发送任何报文给游戏或编辑器进程，
> 不修改 `D:\games\` 下任何文件，不改 `GOAL.md`。全部内容来自本工程已产出的反编译切片、
> 已恢复字符串表、桥接源码与 `.runtime/` 下的既有运行产物。
>
> 目标问题：「如何能直接用代码改千星编辑器的内容」。

> ## ⚠️ 2026-10-09 更正：本文记的「桥接操作 62 项」已过期，**现值是派生物，见 tools/gameplan/tests/test_doctrine.py**
>
> 实测 `tools/editor-bridge/ManagedBridge/BridgeServer.cs` 有 case 分支（见 tools/gameplan/tests/test_doctrine.py）
> （2026-10-09 由三路子智能体独立数出、主智能体复核）。另有两层更窄的门，**是不同的东西，不可互相替代**：
> `call-bridge.ps1` 的 `ValidateSet` 条数见 tools/gameplan/tests/test_doctrine.py（派生物，不在此固化）、helper 的 `NATIVE_ACTIONS` = **6** 项。
>
> 本文正文（含「结论速览」第 1 条与 §四 标题、逐项表）仍是 **2026-09-18 快照**，新增的 op 未登记；
> **逐项清单以 `BridgeServer.cs` 为准**。
>
> 另有一条 2026-10-09 新查得、且决定方向的事实：桥的 op 面（见 tools/gameplan/tests/test_doctrine.py）里
> `ui / widget / layout / hud / button / component / property / trigger / item / inventory / shop / currency / terrain`
> **全部 0 命中**，重心只有 `graph*`(37) 与 `entity*`(14)。
> ⇒ **「配置官方组件」这条路不存在，游戏 B 六模块只能走节点图**；见 `docs/PROGRESS-BY-FUNCTION.md` §八 与 `docs/MODULE-PLAN-6.md` 顶部更正。

## 结论速览（先看这五条）

1. **唯一能直接改编辑器内容的可用途径是层①（进程内反射桥接）**：`tools/editor-bridge/` 的 62 个固定操作（当时），
   其中 **59 个有真实调用留证**，3 个（`*-gameloop-variant-core`）从未调用。
2. **层②（编辑器 IPC）是编辑器作为 TCP 客户端连到原神**，可发 1018 命令（`DoExport` 已实测产出有效 `.gia`），
   但**没有已证的握手、没有 ACK 语义、编辑器不能当服务端被连**。
3. **层③（文件）能离线读写，但不自动进编辑器**：必须经 1018 的 `DoImport`（未接通）或游戏侧「加载外部资产」→ 1020。
4. **层④（原生模型 API）是层①的底座**，全是混淆名，通式是「`Lazy<T>` 静态字段取已创建单例 → 遍历 registry → 读字段/调方法」，
   全部必须在编辑器 WPF dispatcher 上执行。
5. **尚未接通的接口**：后台保存、开始试玩、删除节点/图、任意路径 GIA 导入、导出/导入 ACK、
   标签创建确认、1020 列表内容读回、按图身份读回自有打印、场景摆放、地形编辑。详见第七节。

---

## 证据分级（全文统一，不得混用）

| 等级 | 含义 |
|---|---|
| **【已实测】** | 本工程内有**真实运行留证**（`.runtime/` 下产物、真实文件字节、真实抓到的帧），且可在工程内复核。 |
| **【静态证据】** | 已定位到**具体类型 / 方法 / 字段 / 调用点**（反编译正文或 PE 元数据），但**从未运行过**。 |
| **【仅字符串】** | 只在 2830 条字符串表、消息工厂注册表或枚举里出现过，**没有调用点、没有参数形状**。 |
| **【未知】** | 未定位。 |

**三条硬规则**（本文所有条目都必须遵守）：

1. **字符串存在 ≠ 接口可用。** 字符串表里有 `DoImport` 不代表可以调用导入。
2. **有调用点 ≠ 已验证。** 找到某个方法被调用，只证明代码路径存在，不证明它跑通、更不证明游戏接受了结果。
3. **消息编号被注册 ≠ 可调用的服务。** 24 个编号是「工厂能解码这些编号」，不是「有 24 个 RPC 可以发」。
   反向也不可轻推：「某个类里没有 case」**推不出**「没有接收者」——
   3006 在 `TtW15ji3IJs5A1Zve7UP` 里没有 case，却有 **35 次真实入站流量**，说明另有接收者。
   同理，1015 在工厂里注册了、在分发器里有 case，但**从未被真实观测到**。
   单向证据只能得到单向结论。

---

# 一、接口分层总览

「用代码改编辑器内容」共有四条**互相独立**的途径。只有 ① 在进程内、能直接改编辑器内存模型；
②③④ 都必须经过某种边界（网络 / 文件 / 原生 API），边界另一侧的证据强度各不相同。

| 层 | 入口在哪 | 能做到什么 | 已知限制 | 证据来源 |
|---|---|---|---|---|
| **① 进程内反射（桥接）** | `tools/editor-bridge/`：Snoop 6.1.1 注入器 → `Miliastra.Bootstrap.Net8R66.dll` → `Miliastra.EditorBridge.Net8R66.dll` → 命名管道 `miliastra-bridge-<runId>` | **唯一能直接改编辑器内存模型**的可用途径：建图 / 加节点 / 连线 / 写常量 / 导出 / 导入 / 同步 / 绑图 / 解绑 / 观测 | 租期 5 分钟、≤32 次调用、单行 ≤16 KiB、nonce 32 字节、**固定操作枚举**（无任意反射、无任意 shell）；必须回到编辑器 WPF dispatcher 线程；只清理由本租约增加的定时器/回调 | 【已实测】`.runtime/editor-bridge/runs/` **104 个 run 目录、1154 个结果 JSON**，其中 **43 个顶层 `ok:true`**（另有大量部分结果与失败留证） |
| **② 编辑器自身 IPC / 网络协议** | 编辑器是 **TCP 客户端**：`Socket.BeginConnect(127.0.0.1, <注册表端口>)`；端口取自 `HKCU\Software\miHoYo\BeyondAssistEditor` 的 `port_h2088097884` | 1018 服务/命令 RPC（`DoExport` / `DoImport` / `AddInstructionGraphForEditObj` / `RequestPrefabInstance` …），响应 1019；出站 1014 同步、1016 性能上报 | **编辑器是客户端，不能当服务端被连**（静态发现的服务端工厂无调用者）；无已证握手；无已证 ACK；伪造服务端/伪造回执均被明令禁止 | 协议【静态证据】+ 帧编解码【已实测】+ 连接与出站发送【已实测】 |
| **③ 文件格式** | `.gia` / `.gil` / `.gip` / `.gir` 容器、`.mihoyobin` 资源文件、`assets.bin` ZIP | GIA 图资源包**离线读写往返已跑通**（29 个导出包全部通过容器校验）；4098/4098 `.mihoyobin` 已解出；assets.bin 6453 条目清单已解出 | 文件**不自动进入编辑器内存**：必须经 DoImport 命令或 1020 列表回读才生效；`.mihoyobin` 的 `OfficialPrefab` / `Struct` 泛型类型**未绑定**；GIL 字段语义大体未知 | 容器头【已实测】；XOR 0xE5 链【静态证据+已实测样本】；assets.bin 解包产物【已实测】 |
| **④ 编辑器内部原生模型 API** | 反射取单例 → 遍历资源 registry → 读字段 / 调原生方法；**本身不对外暴露**，只能通过 ① 触达 | 遍历注册表、读/写模型字段、调原生方法（建图、加节点、连线、注册标签、改名称…） | 类型名与方法名**全是混淆名**，版本一变即失效；无跨版本稳定性承诺；操作必须先通过身份/形状断言 | 源码 `tools/editor-bridge/Adapter/*.cs`【静态证据】+ 各 run 产物【已实测】 |

### ① 的启动链（真实机制）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


要点：**没有向 `YuanShen.exe` 注入代码**，不修改游戏文件或保护机制。桥接只活在编辑器进程内。

---

# 二、消息 / opcode 全表

## 2.1 编号来源与三个不同的「表」

必须区分三份**不同**的编号清单，它们回答不同问题：

| 表 | 内容 | 回答的问题 | 出处 |
|---|---|---|---|
| **入站解码工厂** | 24 个编号 → 消息类构造器 | 「收到的帧里哪些编号能被解码」 | `.runtime/mvp/ipc-framing/message-factory.cs` |
| **入站分发器 case** | 一个分发器类显式处理的编号 + **显式忽略**的编号 | 「在这个分发器里哪些编号真的被处理」 | `.runtime/mvp/gia-import-audit/TtW15ji3IJs5A1Zve7UP.cs:58–210` |
| **运行时实际观测** | 真实会话中桥接内建观察器数到的编号与次数 | 「实际跑起来究竟出现了什么」 | `.runtime/editor-bridge/runs/*/*.json` 的 `packetKinds` |

**三份表都不是「可调用服务列表」。** 下面逐条列出。

### 分发器 `TtW15ji3IJs5A1Zve7UP` 的确切范围（必须知道它只是一个接收者）

它的 `seAYooJHAHf(frame)` 是**两级**结构，**不是全量分发器**：

- **被处理**（有 case 且做实际工作）共 **18** 个：
  `0, 1002, 1004, 1008, 1009, 1010, 1011, 1015, 1017, 1018, 1019, 1020, 1022, 1025, 1026, 1027, 2002, 3002`
- **被显式忽略**（`case …: return;`，什么都不做）共 **11** 个：
  `1003, 1005, 1006, 1007, 1012, 1013, 1014, 1016, 1021, 1023, 1024`
- **根本不在这个类里**：`1001, 2001, 2003, 3001, 3003, 3005, 3006`
  → 说明**还有别的接收者**。这一点有正面对照：桥接的真实观察器在真实会话里数到
  **3006 出现 35 次**，而本类对 3006 没有任何 case —— 3006 的批量日志路径由**另一个接收者**处理。
  因此**不得**把本类的忽略列表当成「全局忽略列表」。

## 2.2 编号逐条表

「方向」按已证证据填写；`↗` = 编辑器→对端，`↘` = 对端→编辑器，`↗↘` = 双向。

| 编号 | 方向 | 已知用途 | 证据等级 | 实测/静态细节 |
|---|---|---|---|---|
| **0** | ↘ | **空控制包**（10 字节，无载荷）。ID0 的 uint32 长度域声明的是**上一个业务包的载荷长度**，不是 0 | 【已实测】 | 真实抓到 653 次（桥接观察器）；只收探针抓到 9 次。声明长度 17/33 与其前一个业务包载荷长度一致 → 解释为「复用数组后两字节未清零」。**用途（是否心跳）未命名** |
| **1001** | ↗ | 编辑器首帧；**payload 是单个 length-delimited string**（protobuf tag10） | 【已实测】 | 无原神探针收到 1 次（30 字节外层，payload 16 字节，hash `917e0765…` 与预测一致）；消息类 `GrEZk9anG8CJBLwcuEe1.Jnb0iWannhIMdFajYBbK`。**本分发器没有 1001 的 case**。**该 string 不是已证的握手/初始化/关卡数据；不得据此建立会话** |
| **1002** | ↘ | 处理链把 Blueprint RuntimeInfo 集合交给日志（文案 `Blueprint RuntimeInfo Collection Notified - `，偏移 50466） | 【静态证据】 | 有界核对**未发现**"连接成功"标志、项目加载或文件写入。**不得伪造空 1002 当初始化回执** |
| **1003 / 1005 / 1006 / 1007 / 1012 / 1013 / 1021 / 1023** | ↘ | 在分发器里**显式忽略**（`return;`，不做任何处理） | 【静态证据】 | 分发器 case 组；工厂表**未注册** |
| **1004** | ↘ | 分发器有 case（走 IL 跳转），用途未证 | 【静态证据】 | 工厂 `Vu0XDNaBGdW7g9mRfsrH.AekKCfaBnDF8aaNM1Dvt` |
| **1008 / 1009 / 1010** | ↘ | 分发器有 case，用途未证 | 【静态证据】 | `k2xbdlatjYpJW8e0w5PZ` / `yCjNHcaB5S2lKfm3V0yB` / `tmGXcXaw32XytWw1AZCH` |
| **1011** | ↘ | 分发器有 case，用途未证 | 【已实测出现 1 次】+【静态证据】 | 某次真实会话 `packetKinds` 含 `"1011":1` |
| **1014** | ↗ | **原生同步载荷**（编辑器把自己的图序列化后发出） | 【静态证据】+ 出站发送点【已实测间接】 | 在分发器里被**显式忽略**；工厂**未注册**。发送点：`Oe5aspiVGooyp47o5s0q.cs:15155` 区域 `zf2hgcpK7LU(1014, payload)`。序列化器 `oGZiJdFmLSF` 的验签结果【已实测】：9 次 `native-sync-serialization-matches` |
| **1015** | ↘ | **入站同步请求**（不是 1014 的 ACK） | 仅【静态证据】 | 工厂 `gOTkLGae2aX1iLOIhHQU.ULcU3FaeSaW8mUS8GDgi`；原生 `EyAiibCGyGJ` 调度 action 3，其 Execute 触发同步。**警告：桥接虽已埋点记录 `syncRequestPayloadType` / `syncRequestsAfterInvocation`，但全部 121 份记录中前者恒为 `null`、后者恒为 `0` —— 1015 从未被真实观测到。** 不得把「代码里有 case」当作「实际出现过」 |
| **1016** | ↗ | **性能/内存周期上报**：字段分别标注 `memory` / `heapCommittedMemory` / `heapUsedMemory`（字符串 51510/51530/51578） | 【静态证据】+【已实测】 | 只收探针收到 10 次（17/33 字节）。发送门槛是「累加的 double > 1.0 后清零」。**不把它称作心跳或服务请求** |
| **1017** | ↘ | **复制/同步分组状态分派** | 【静态证据】+【已实测出现 2 次】 | 外层 schema 已展开：field1 = repeated `hsk`（内含 uY1 key：4 个 uint32 + repeated N8 记录），field2 = 3 个 bool（tag 8/16/24）。分类常量 A=field2、B=field3；**Tag 的 B=23**。无效分组日志 `invalid replication group `（73612）。**不是文件路径，也不是完整地图资源** |
| **1018** | ↗↘ | **公共命令通道**：请求 `(服务名, 命令名, 有序参数表)` | 【已实测】 | 双向都真实出现：出站由桥接发起（见第四节），**入站还观测到 13 次** —— 即**游戏也会向编辑器发 1018 请求**，由编辑器本地那 3 个 `wpf*Service` 处理。字段布局 wire tag 8/18/26/34（uint 请求号 + string 服务名 + string 命令名 + repeated 参数）。**响应走 1019，按请求号配对** |
| **1019** | ↗↘ | **1018 的响应**；也承载原生日志请求结果 | 【已实测】 | 观测到 19 次。回复类 `U8hGWcazKO84hvpc042G.rMyEXuazimvWHMFk7awm`，`rrlazLEZM8f` = 请求号（0 表示 unset），`y9iazq3HFOv` = 成功标志。**必须按请求号配对，不能拿别的请求结果充数** |
| **1020** | ↘ | **外部资产列表通知** | 【已实测到达，但读到 0 条】 | 观测到 4 次。`MA16RWazQ9LeDPlTWK57` field1 = repeated `UD6`；`UD6` field1 = 嵌套资产元数据（name:string / kind:enum），field2 = uint（展示代码只按 ≤1 / >1 分类），field3 = string（显示文字，**不等于已证文件路径**）。桥接只白名单保留自有资产名，其余折叠为按类计数。**关键限制**：唯一留证的实测快照是 `captured:true, snapshots:3` 但 **`totalEntriesScanned:0`、`ownAssets:[]`** —— 处理器被到达 3 次，**列表内容为空**。因此「1020 能读到真实资产名/索引」目前**没有**实测支持，只是结构上可读 |
| **1022 / 1025 / 1026 / 1027** | ↘ | 分发器有 case，用途未证 | 【静态证据】 | 1025 = `lwC7wxmEU9ubYtxvA2yo.kEiO49mEo5W58p5IF0WW`；dc-handoff 记为「有载荷类型和调用点，但未建立可靠场景放置入口」 |
| **1024** | ↗ | **出站发送点存在**（`zf2hgcpK7LU(1024, payload)`，payload 类 `mLusSRmEs6Ag8QCbAaNK`） | 【静态证据】 | 工厂**未注册**，入站被**显式忽略**。**禁止猜发** |
| **2001 / 2002 / 2003** | ↘ | 工厂已注册；2002 在本分发器有 case（其余未定位接收者） | 【静态证据】 | `TDkCIQBu2aiStr6db9a` / `MS8XmABlBjVZuHiOAen` / `T0MOe1BUv2YNdBYypjf` |
| **3001** | ↗ | **日志启用 + 图选择**（出站由桥接发出） | 【静态证据】+【已实测发送 6 次】 | 外层 `uY432DaSLO9E1Pagl8Y2.SNYUqraShudVtwQSLBmO`，内层 `TCeimgaSv8HFWBZL2Emr.bNf3IEaS4GdguXca3eut`：`XwtaSuJH9gv(true)` 置启用 + server 图列表（上限 10）+ client 图列表（上限 99）。**本分发器无 3001 case**；`acknowledged=false`。**发出 ≠ ACK，也不启动试玩** |
| **3002** | ↘ | **单条调试日志记录** | 【静态证据】 | `HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD`。**这是本分发器唯一处理的 300x 编号** |
| **3003 / 3005** | ↘ | 工厂已注册，用途未证 | 【静态证据】 | `PVZwE8a22GKbfjuoZSRT` / `crySr7atxVUAyo7ZZFH6`；**本分发器无 case** |
| **3006** | ↘ | **批量调试日志**，直接列表字段 `WLlatRfEhBx` | 【已实测出现 35 次】 | 外层 `IGmDiMatq2IanW3w1IR0.YGZiiaatLoanyfGQd2hQ`，逐条为 `fRTMHcaSSKjG5j3IhYLD`。桥接按此结构读，上限 32 包 / 每包 4096 条 |

## 2.3 出站服务/命令名（1018 通道的实际词汇表）

以下命令名来自**同一通道**的调用点扫描。**服务名 + 命令名 + 参数表**是 1018 的三段式。
注意：**编辑器本地入站服务表只登记 3 个 `wpf*Service`**（`wpfAudioService` / `wpfApplicationService` / `wpfInstructionGraphService`）；
所有 `beyond*Service` **都不在**其中 —— 这是一条**正向证据**，说明 `DoExport` 等命令的处理器在**对端进程**，不是「发给自己」。

| 服务 | 命令（字符串偏移） | 证据等级 |
|---|---|---|
| `beyondExportService` | `DoExport` (119104) | 【已实测】真跑通并产出有效 `.gia` |
| `beyondExportService` | `DoImport` (114322) | 【静态证据】参数形状 `[uint index, bool, string, uint]`；**从未发送成功** |
| `beyondExportService` | `ImportDebugLog` (132630) / `ImportAllDebugLog` (132662) | 【已实测】桥接 `request-debug-logs` 实发过 |
| `beyondExportService` | `RefreshExistDebugLogReport` (136008) / `DeleteDebugLog` (136064) / `ImportPerformanceReport` (129282) | 【静态证据】仅调用点 |
| `beyondEditObjService` | `RequestPrefabInstance` (118870) | 【已实测】桥接 `request-calibration-prefab` 实发，但被 native kind 守卫跳过（`native-kind-guard-skipped`），**未真正请求** |
| `beyondEditObjService` | `AddInstructionGraphForEditObj` (119378) | 【已实测】桥接 `bind-*` 实发 12 次（`binding-requested-readback-pending`） |
| `beyondEditObjService` | `FocusPrefabInstance` (118916) / `DeletePrefab` (118986) / `DeleteEditObj` (119014) | 【静态证据】仅调用点 |
| `beyondEditObjService` | `ModifyEditObjName` (76824) / `ModifyPrefabName` (77254) | 【静态证据】 |
| `beyondAudioService` | `create` (76768) / `delete` (76784) / `modifyname` (76800) | 【静态证据】 |
| `beyondPCGInstanceService` | `ModifyPCGInstanceName` (76862) / `DeletePCGInstance` (76908) / `FocusPCGInstance` (76946) | 【静态证据】 |

**仅存在于字符串表命令名带、没有调用点**（**不得**当作已恢复入口）：
`ModifySuite`(118742)、`ModifyEditobjTag`(118768)、`ModifyPrefabTag`(118804)、
`FocusEditObj`(118958)、`ApplyPrefabInstanceChange`(119264)、`AddInstructionGraphForPrefab`(119318)。

**全表 2830 条字符串中不存在 `DoSave` / `SaveProject` / `SaveArchive` 一类命令名。**
`vmBtnSave` / `vmBtnSaveAs` / `vmButtonSave` 只是视图元素名，其处理器不在现有切片内
→ **后台「保存当前存档」接口没有已恢复入口**。

---

# 三、帧与传输

## 3.1 传输

| 项 | 已证内容 | 等级 |
|---|---|---|
| 角色 | **编辑器是 TCP 客户端**，不是服务端 | 【静态证据】`client.cs:168 Connect(int)`，:188 用作 `IPEndPoint` 端口 |
| 连接方式 | `Socket.BeginConnect(127.0.0.1, <端口>)` | 【静态证据】 |
| 服务端类存在但不可达 | `yj5YKk3zZEa0yoMqLjwb.QixYoYbYh7R` 使用 `Bind` / `Listen` / `BeginAccept` / `EndAccept`；反向搜遍 34728 个代理槽**找不到**其构造或启动调用者 | 【静态证据】。**「没有可见调用路径」不是「绝不可能」，但不得去激活这个apparently-unused 服务端来冒充游戏** |
| 端口来源 | `HKCU\Software\miHoYo\BeyondAssistEditor` 的 `port_h<hash>` (`REG_DWORD`)，读不到则回退默认值 0 | 【静态证据】`port-provider.cs:30–44`；`tpm3knc3eWl` → `Registry.GetValue` |
| 端口哈希算法 | djb2-xor：`num = 5381; num = num*33 ^ c`，截断 uint32 | 【静态证据】`port-provider.cs` `C6u3ktJr0M5`；`hash("port") = 2088097884` 已独立复算 |
| 端口实际值 | 历史 **55993**；2026-09-15 真实会话 **58988**。**端口是动态的，源码不写死** | 【已实测】注册表读取 + 内核 TCP 表核对 |
| 对端身份 | 原神 `YuanShen.exe` PID 132060 在 `127.0.0.1:58988` **Listen**，编辑器 PID 100360 从 `127.0.0.1:59309` 与之 **Established** 双向 | 【已实测】`.runtime/verification/live-session-20260915/` |
| 无监听时的表现 | 编辑器发出 SYN 后停在 `SynSent`（对端无人应答） | 【已实测】`IPC-DISCOVERY.md`：`port 55993, listenerPresent false, SynSent` |

**必须区分**：「内核里有 socket 在 Listen」≠「IPC 协议能握手」≠「能控制游戏」。
`bridge/ipc_discovery.py` 因此恒返回 `protocolVerified=false`、`gameControlAvailable="unknown"`。

## 3.2 分帧（已实测的字节级格式）

所有整数 **big-endian**：

| 偏移 | 类型 | 字段 | 说明 |
|---|---|---|---|
| 0 | ushort | magic | 固定 `0x0656` |
| 2 | ushort | message_id | 业务消息号 |
| 4 | uint32 | payload_length | **掩码后** payload 的字节数 |
| 8 | byte[] | payload | 每字节 XOR `0xEA` |
| 8+len | ushort | magic | 固定 `0x0666` |

固定开销 **10 字节**（头 8 + 尾 2），空 payload 帧正好 10 字节。XOR 对称，编解码同一密钥。

golden 基准（手写自静态证据，非模块生成）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**边界（不得当成权威协议文档）**：

- 没有真实抓包对照。线格式来自静态读码 + 手写 golden，**未做收发往返验证**。
- **不做 CRC / 校验和校验**；未知字段会被忽略而非保留。
- `1 MiB` 是**本项目**的资源上限，**不是官方协议上限**。
- 长度校验**先于**整帧完整性校验：只要有完整 8 字节头，声明 4 GiB 的畸形帧会**立刻被拒**，不会挂起等待。
- 空消息仍写 4 字节长度区域（`Marshal.SizeOf(0)`），**不是省略长度字段**。ID0 的长度域残留旧值，
  `bridge/editor_probe.py` 单列为 `empty-control-envelope`，`businessDecoded=false`、`controlMeaningVerified=false`。

## 3.3 序列化

**protobuf**（protobuf-net 风格：`MergeFrom(T)` / `WriteTo` 成对，静态 codec 常量绑定 tag ↔ 嵌套类型）。

- 消息类 → 编号的映射表见 `.runtime/mvp/ipc-framing/message-ids.json`（24 条）。
- 每个消息类的 payload 字段以 `tag = 字段号<<3 | wiretype` 编码。
  **`tag` 读法是共享假设**，在 1018 上被 4 个字段（8/18/26/34）独立吻合，但**未在所有消息上验证**。
- 1018 的参数联合 `IxtFOgiA4qhGnLhEyLFv` 是 **7 型 tagged union**：
  `1=uint, 2=int, 3=bool, 4=float, 5=string, 6=uint, 7=byte[]`。
  **判别值 ≠ protobuf 字段号**：曾把判别值 5 直接当字段号编码出 `2a0158`(field5)，
  正确应为 field15 → `7a0158`。**该编码器在修复并通过独立字节校验前不得用于真实发送。**
- 字节序：`BitConverter.ToUInt16/ToUInt32` + 手工高字节优先写入（`native-byte-writer.cs` 直接写 pinned 数组）。

## 3.4 连接保持 / 超时

- **无入站阈值有两套，不是「固定 6 秒」常量**：
  - 秒阈值 **30**；计数阈值 **180**（另一模式 **900**）→ `config-factory.cs:27–36,73,82–90`
  - **180 的单位是「更新次数」，不是秒**。若该调用约 30 次/秒，180 次约 6 秒 —— 与实测的 6.2s / 6.7s 窗口吻合，
    但**本轮未测实际频率**，这只是候选解释，不是已证运行时原因。
- 只有**取到非 null 入站帧**才刷新这两个基准（`client-controller.cs:322,334`）。
- **出站 1001 / 1016 / ID0 都不刷新「最近入站」计数** —— 只收端持续收到性能包**不保证**连接保持。
- 另有发送空 ID0 帧的 1 秒间隔分支。
- 实测断开窗口：6.219s / 6.712s / 9.828s（三次单标签实验）。第三次发送成功后窗口延长到 9.828s，
  与「入站刷新计时」的静态机制一致，但**没有直接的处理器完成或模型 ID/Name 证据**。

---

# 四、桥接操作白名单

全部 op 来自 `tools/editor-bridge/ManagedBridge/BridgeServer.cs` 的固定 switch（条数见 tools/gameplan/tests/test_doctrine.py）。

**证据判定口径（已核对到底）**：`.runtime/editor-bridge/runs/*/` 下有以 `<op>-response.json` 命名的
结果文件，直接给出「这个 op 真的被调用过」的证据。按该命名清点：

- **59 个 op 有过真实调用**（都有 `<op>-response.json`）。
- **只有 3 个 op 从未被调用**，全部是同一个 bisect 变体族：
  **`create-gameloop-variant-core` / `build-gameloop-variant-core` / `bind-gameloop-variant-core`**。

因此下表 `【跑过】` = 存在 `<op>-response.json`；`【未跑】` = 只有代码、无任何调用产物。
（另有 `export-bound-entity-response.json` 等**不是** bridge op 的辅助脚本产物，不计入 62 项（当时）。）

## 4.1 建图（create-*）— 后端：原生图管理器

| # | op | 真实后端 | 证据 |
|---|---|---|---|
| 4 | `create-calibration-graph` | `Oe5aspiVGooyp47o5s0q.yBnirE4YONq(kind=20000, name, 0u, null)` | 【跑过】`create-requested-not-verified` / `calibration-authored-unbound-export-pending` |
| 7 | `create-audit-graph` | 同上 | 【跑过】`audit-created-unbound` |
| 12 | `create-finish-graph` | 同上 | 【跑过】`finish-created-unbound` |
| 16 | `create-gameloop-graph` | 同上（含「已存在且仍为空」可续建逻辑） | 【跑过】`gameloop-created-unbound` / `gameloop-already-present-empty` |
| 23 | `create-gameloop-variant-no-scoreboard` | 同上 | 【跑过】`gameloop-variant-created-unbound` |
| 24 | `create-gameloop-variant-core` | 同上 | **【未跑】**（当时的 62 项中仅 3 项从未调用） |
| 29 | `create-position-graph` | 同上 | 【跑过】`position-created-unbound` |
| 41 | `create-test-graph` | 同上 | 【跑过】`create-requested-not-verified` ×2 |

## 4.2 建图内容（build-*）— 后端：原生图模型节点/连线 API

统一机制（每一类图共用）：

- 加节点：`graph.Model` 的 `BWmKmyL3bM7(definitionKey, x, y, null, null)`
  （`definitionKey` 取自定义模型字段 `U0oKESVcL9L`，**不是猜的 ID**）
- 连线：`new xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP(addressFrom, addressTo)` 构造 link，
  再 `graph.Model.LapKOOcuGY1(link, null, -1)` 提交（返回 bool，拒绝即抛）
- 引脚地址：`Pin(node, kind, index).SrvK5eKUmbB()`；**引脚类别 1=输入执行 / 2=输出执行 / 3=输入数据 / 4=输出数据**
- 写常量：`pin.value.Value` → 按类型选 setter（`MfLKK0bLIju` 字符串、`X8oKKHB87Ue` 枚举/uint、
  `SH7KKvk8cxe` float、`LhkKKbraAbs` uint、`CHHKK434xan` bool、`c84KKE8ihrN` int）；
  泛型引脚先经 `eUgKKLsg3Lw` 取实际值

| # | op | 备注 | 证据 |
|---|---|---|---|
| 5 | `build-calibration-graph` | 6 节点，故意不绑图 | 【跑过】 |
| 8 | `build-audit-graph` | 13 节点，含定时器 + 列表序列（元素定义来自原生定义，不是猜的枚举） | 【跑过】`audit-authored-unbound-export-required` |
| 13 | `build-finish-graph` | 23 节点，终点判定（距离 ≤2 且高度 ≥2.4） | 【跑过】`finish-authored-unbound-export-required` |
| 17 | `build-gameloop-graph` | 29 节点可玩循环 | 【跑过】`gameloop-authored-unbound-export-required` |
| 25 | `build-gameloop-variant-no-scoreboard` | 28 节点（bisect 变体） | 【跑过】`gameloop-variant-authored-unbound` |
| 26 | `build-gameloop-variant-core` | 27 节点 | **【未跑】** |
| 30 | `build-position-graph` | 16 节点，0.25s 轮询角色位置 | 【跑过】`position-authored-unbound-export-required` |
| 42 | `add-test-print` | 单节点「打印字符串」 | 【跑过】`editor-model-edited-game-save-not-verified` |
| 43 | `wire-test-event` | 事件节点 + 连线 + 写常量 | 【跑过】`editor-graph-wired-game-export-pending` |

## 4.3 绑图 / 解绑 — 后端：1018 → `beyondEditObjService`

| # | op | 真实后端 | 证据 |
|---|---|---|---|
| 44 | `bind-calibration-graph` | `Ikci0qkvMZX("beyondEditObjService","AddInstructionGraphForEditObj",null,list)`，参数 `[bool true, uint entityId, uint 1, uint graphId]` | 【跑过】`binding-requested-readback-pending` ×12 |
| 45 | `bind-test-graph` | 同上 | 【跑过】 |
| 9 | `bind-audit-graph` | 同上（前置要求 calibration+tiled 已绑） | 【跑过】 |
| 15 | `bind-finish-graph` | 同上 | 【跑过】 |
| 19 | `bind-gameloop-graph` | 同上 | 【跑过】 |
| 27 | `bind-gameloop-variant-no-scoreboard` | 同上 | 【跑过】 |
| 28 | `bind-gameloop-variant-core` | 同上 | **【未跑】** |
| 32 | `bind-position-graph` | 同上 | 【跑过】 |
| 55 | `bind-tiled-route` | 同上 | 【跑过】 |
| 21 | `unbind-gameloop-graph` | **原生模型直改**：`entity.t6ViSxlgnQ3()` 取绑定集合 → `lUBiNLoXRl5(index, true)` 删除，再读回验证 | 【跑过】`gameloop-unbound` |
| 22 | `unbind-all-gameloop-graphs` | 同上，倒序遍历删除全部自有图 | 【跑过】`gameloop-all-unbound` ×2 |

## 4.4 导出 — 后端：1018 → `beyondExportService` / `DoExport`

| # | op | 真实后端 | 证据 |
|---|---|---|---|
| 6 / 10 / 14 / 18 / 31 / 46 / 54 / 57 / 61 | `export-calibration-graph` / `-audit-` / `-finish-` / `-gameloop-` / `-position-` / `export-first` / `export-tiled-route` / `export-route-placement` / `export-imported-graph` | `Ikci0qkvMZX("beyondExportService","DoExport",callback,args)`；args = **4 个分类 uint + 1 个 id uint + 1 个路径 string**（路径来自固定导出目录 + runId）。回调经 `transport.MSgi0zbjIEA(receipt)` 在 30s 窗口后注销 | **【已实测】29 个 `.gia` 全部通过容器校验**（magic `0x326`、kind 3、尾 `0x679`、长度自洽）。限制：同类图每租约最多 2 个导出，同 id 不重试 |

**注意**：`DoExport` 的回复回调实测 `rows: []`（28 个 `.reply.json` 全是空行）——
**回调触发 ≠ 有返回内容**。但磁盘上确实出现了有效 `.gia`，所以「导出产出文件」是已实测的。

## 4.5 导入 — 后端：protobuf 解析 + 原生反序列化 + 图管理器

| # | op | 真实后端 | 证据 |
|---|---|---|---|
| 59 | `import-calibration-graph` | 读固定 `.pb`（sha256 `52CF5C27…`，786 字节）→ `f4A1VQaoFD29hLxbgRyd.rJZaopuTsYW.hGkESFcAaV(bytes)` → `Oe5aspiVGooyp47o5s0q.WnqiJxnOpxs(proto)`（静态非公开）→ 校验节点数 → `yBnirE4YONq(kind=20000, name, 0u, temporary)` → `temporary.Recycle()` | 【跑过】`file-graph-import-requested-readback-pending` ×5 |
| 60 | `import-verified-graph` | 同上（`verified-test-graph.pb`，214 字节，`9C733120…`，2 节点） | 【跑过】 |
| 53 | `import-tiled-route` | 同上（`tiled-route.pb`，9692 字节，`25A49E51…`，39 节点） | 【跑过】 |
| 56 | `import-route-placement` | 同上（`route-placement.pb`，2144 字节，`60AFAE47…`，12 节点） | 【跑过】 |

**硬约束**：载荷 SHA256 必须与代码里的常量**逐字节相等**，否则拒绝。没有「按路径加载任意 GIA」的接口。

## 4.6 同步 — 后端：原生同步管理器

| # | op | 真实后端 | 证据 |
|---|---|---|---|
| 58 | `sync-editor-changes` | `Oe5aspiVGooyp47o5s0q.wAXirPMXQCJ(false)` 就绪检查 → `fIviJCKIQSe()` 触发全编辑器同步（内部组 1014 发出） | 【跑过】`native-editor-sync-invoked` ×15。**返回体自带 `persistentSaveVerified=false`、`playtestVerified=false`** |
| 34 | `inspect-sync-graphs` | 反射调静态序列化器 `oGZiJdFmLSF(kind9, kind6, bool)`，比对模型节点 ID 与序列化节点 ID | 【跑过】`native-sync-serialization-matches` ×9 |

## 4.7 日志 — 后端：3001 出站 / 3002·3006 入站观察

| # | op | 真实后端 | 证据 |
|---|---|---|---|
| 36 | `enable-debug-logging` | 构造内层 `bNf3IEaS4GdguXca3eut`（`XwtaSuJH9gv(true)`）+ 外层 `SNYUqraShudVtwQSLBmO`（`h0UaSTjlMFm`）→ 读回校验 → `producer.PHCi086M7o5(3001, outer)` | 【跑过】`native-log-enable-requested` ×6。**`acknowledged=false`、`previousEnabledState="unknown"`、`startsPlaytest=false`** |
| 37 | `enable-own-graph-logging` | 同上 + 选择自有 server 图（calibration 7 / tiled 39 必需，audit 13 / position 16 / finish 23 可选，上限 10）；client 列表保持空 | 【跑过】 |
| 35 | `request-debug-logs` | `Ikci0qkvMZX("beyondExportService","ImportAllDebugLog", callback, null)`；请求号取自回执 `dJVi0tPDg6E`，30s 后清理 | 【跑过】`debug-log-refresh-requested` ×19 |

### 4.7.1 日志读回的实际成果（必须区分「收到记录」与「读到自己的内容」）

| 观察项 | 实测结果 | 含义 |
|---|---|---|
| 3002/3006 记录 | `recordsScanned` = **19**（7 次）、**83**（4 次）；其余 26 次为 0 | **批量日志通路是通的**：真实收到了结构化的 3002/3006 记录 |
| 自有 marker 字符串 | 30 次记录里出现 `["MW_CALIBRATION_PLATFORM_CREATED_20260916","MW_ROUTE_TILED_CREATED_20260916"]`；4 次额外出现 finish 的两个 marker；144 次为空 | 说明这些图**至少在某个时刻执行并打印过**。但 adapter 自带警告：**marker 可能来自历史调试日志，缺失不证明未执行** |
| `auditPrints` | **全部为空** | 审计图的数值打印**从未被保留** |
| `positionPrints.retainedPrints` | **全部为 0**（37 份记录） | 位置图的数值打印**从未被保留** |

结论：**「日志通路可用」已实测；「按图身份精确读回自有图的打印内容」尚未接通** ——
结构化捕获要求原生记录在三个名称字段之一里出现我们的图名，该条件从未满足过。
| 50 | `start-log-observer` | `DispatchProxy` 实现原生接口 `a2loy23IhuQeagPQb4Bx.seAYooJHAHf`（单方法、返回 void，形状不符即拒），经 `producer.hUBi0lBOqTW(proxy)` 注册 | 【跑过】 |
| 47 | `start-external-asset-observer` | 同 `start-log-observer`，租期 120s（仅接受 25 / 120） | 【跑过】 |
| 51 | `log-observer-evidence` | 只读回读观察结果 | 【跑过】 |
| 52 | `stop-log-observer` | `producer.MsOi0h1OdBN(proxy)` 反注册 + 从 `EdBi0U13Ia7` 移除 + 清理 deferred 列表 | 【跑过】 |

## 4.8 观测 / 查询（全只读）— 后端：反射读模型字段

| # | op | 真实后端 | 证据 |
|---|---|---|---|
| 1 | `ping` | `Application.Current.Dispatcher` 探针 + `AppDomain` 程序集枚举（找 `BeyondEditor*`） | 【跑过】19 次 |
| 2 | `describe` | **只读类型身份与静态元数据**，绝不枚举成员或读值；类型名必须匹配严格正则，≤16 个、≤200 字符 | 【跑过】op 回显 1 次 |
| 3 | `node-definitions` | 反射读 Kind 6 定义模型（上限 64 个 id） | 【跑过】`node-definitions-read-only` ×7 |
| 40 | `catalog` | 遍历 registry + 场景快照 + 终点节点目录 + 传输层状态 | 【跑过】`scene-catalog-snapshot-read-only` ×81 |
| 33 | `runtime-evidence` | 读日志模型记录扫描自有 marker；`editorLevelState` 取 `context.JkFiGb7j1JI` | 【跑过】`observation-recorded` ×1 |
| 49 | `external-asset-evidence` | 回读 1020 捕获的列表元数据快照 | 【跑过】但 **`captured:true, snapshots:3, totalEntriesScanned:0`** —— 到达了、列表为空 |
| 48 | `retire-runtime-spawns` | **写操作**：`graph.vJwKOEFj00D(link, null, false)` 断开执行连线（只删第一条 event→branch 执行边） | 【跑过】`runtime-spawns-retired-readback-only-export-and-game-not-run` ×2 |
| 11 | `repair-finish-booleans` | 原生枚举 bool 用 `X8oKKHB87Ue(1u,null)` 写，读回用 `cPOKKkedklwd()`（**不是 `RJCKKnWqvLO()`**） | 【跑过】`finish-enum-booleans-repaired-unbound` |
| 20 | `repair-gameloop-score-order` | 修计分行顺序 | 【跑过】`gameloop-score-order-repaired-unbound` |
| 38 | `set-calibration-origin` | 加「三维向量：零向量」节点并连线到 spawn | 【跑过】`explicit-zero-position-rotation-export-pending` |
| 39 | `request-calibration-prefab` | `Ikci0qkvMZX("beyondEditObjService","RequestPrefabInstance",null,args)` | 【跑过】但 `native-kind-guard-skipped` → **实际未请求** |
| 62 | `stop` | 只取消租约、只关监听器；`cleanupComplete=false`、`hostProcessTerminated=false` | 【跑过】50 次 |

## 4.9 不在这 62 项（当时）里的东西

- **没有** `delete-node` / `delete-graph`（原生**没有 delete 接口可用**，只能建同名新图或换绑）
- **没有** `save-project` / `save-course`（后台保存入口未找到，见第七节）
- **没有** `start-playtest`（试玩只由 UI 触发）
- **没有**任意反射 / 任意类型名 / 任意路径 / 任意 argv 的通用入口（`describe` 也只能读类型身份）

---

# 五、原生模型操作（进程内反射能做到什么）

来源：`tools/editor-bridge/Adapter/EditorAdapter.cs` 及同目录各 partial。

## 5.1 通式（这是整套机制的核心）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**「怎么找单例」的答案就是 ②**：`Lazy<T>` 持有者类的静态字段 `rZmi38av5uw`，泛型实参是目标单例类型。
**「怎么在 dispatcher 上调用」的答案就是 ⑥**：`Dispatcher.InvokeAsync` + `CheckAccess` 断言。

## 5.2 已用的混淆类型名（版本相关，换版本即可能失效）

| 角色 | 混淆名 | 用途 |
|---|---|---|
| 资源注册表单例 | `ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre` | registry 根，字段 `bwbixDw3yob` = 分类字典 |
| 编辑器同步/图管理器 | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q` | 建图 `yBnirE4YONq`、同步 `wAXirPMXQCJ` / `fIviJCKIQSe`、反序列化 `WnqiJxnOpxs`、序列化 `oGZiJdFmLSF` |
| 连接/生产者 | `tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh` | RPC `Ikci0qkvMZX`、发帧 `PHCi086M7o5`、处理器注册 `hUBi0lBOqTW`、反注册 `MsOi0h1OdBN`、接收者列表 `EdBi0U13Ia7` |
| 参数联合类型 | `yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv` | 1018 的 7 型 tagged union；静态包装器 `h8diA3iOGmJ`(bool) / `bKliA0tj1p1`(uint) / `qsriAuLLSBe`(uint) / `wNLiAK8Wcix`(string) |
| 图模型（Kind 9） | `cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH` | 用户图；名字字段 `c1pKbESgr8S` |
| 节点定义（Kind 6） | `IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C` | 定义模型；名字字段 `DsBKEwvlwAl` |
| 日志模型注册表 | `TisVe3KoM4SfmwtFXy3n.dDOKwYKoP8tIefHhgog5` | 字段 `nImKoZ6adkL` |
| 日志记录类型 | `XvpSBIuvoMSpMenoIqRg.C9ev3quv9MKMEBmJNJDj` | 记录体 `FSUuOVsfGPM` |
| 实体模型 | `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr` | 名字 `WAAiS5WkxlA`、预制 `TuuiS94iUgu`、身份 `Qi8iCzKCkTt` |
| 预制模型 | `nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp` | 标签 `PChiBEHqYMS`、身份 `atbiBHcMllT`、原生 kind `qgriBv1ZZtL` |
| 身份结构 | `FevvcZiBkS31NrEJZJIG` | 5 分量：`oLyiwZX255H` / `AwbiwrjxUDX` / `UFWiwJNegmh` / `RBTiwn649Hy` / `namiwGPRyPS`(ID) |
| Link 类型 | `xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP` | 2 参数构造器 |
| 观察者契约 | `mms6AS3ILkPSiIMIK84R.a2loy23IhuQeagPQb4Bx` | 单方法接口 `seAYooJHAHf`，返回 void |
| 日志控制内层 | `TCeimgaSv8HFWBZL2Emr.bNf3IEaS4GdguXca3eut` | `XwtaSuJH9gv`(启用) / `I0DaSPm1JQc`(读回) |
| 日志控制外层 | `uY432DaSLO9E1Pagl8Y2.SNYUqraShudVtwQSLBmO` | `h0UaSTjlMFm` / `doEaSUah24B` |
| 日志选择 proto | `uBi4l34XLv2OekpES2JT.auKUt14Xhrb73Hx3I35G` | `Y1D4XTEyyiM`(值) / `dXk4XUyFwMq`(图 id) |
| 同步序列化器 | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q.oGZiJdFmLSF` | 静态，返回 `dtCyX8ao6wX81LGIyEgY.f4A1VQaoFD29hLxbgRyd` |
| 序列化节点 | `tYcuuNaTSY3wtgYAjxgT.UP9OrIaTCK1yMYEKHVN3` | id 字段 `usLa91tD7Tp` |

**另有 4 个关键方法名**（题目点名要求覆盖）：
`wAXirPMXQCJ`（同步就绪检查）、`fIviJCKIQSe`（触发全编辑器同步）、
`K61KONg4LUT`（图 → 节点字典）、`t6ViSxlgnQ3`（实体 → 图绑定集合）。

## 5.3 遍历资源注册表（`Resources()`）


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**已实测的原生分类常量**（当前版本实证，**不是跨版本通用魔数**）：

| 名称 | Kind | category（4 元组） |
|---|---|---|
| 自有用户图 | 9 | 第 3 项 = **21001** |
| 节点定义 | 6 | `{10001, 20000, 22000, 0}` |
| 服务端节点分类 | 6 | 第 2 项 = `{10001, 20000, 22000, 0}` 的 20000 |

## 5.4 读 / 写模型字段的实例

- **读**：场景快照 `SceneCatalogSnapshot()` —— 只读字段，**不调任何原生方法**；
  变换字段 `hTjiSreIlqL` → 三个向量 `maSidNtJUim` / `MtbidjteDd3` / `OStidFtjJdR`，
  向量分量 `xYKidoTpamf` / `MDTidUcgOhj` / `LSnidRDCRwE`。非有限分量**整体报 unavailable**，不强制转换。
- **写**：`Set(node, index, setter, data)` —— 从 pin 的 `value.Value` 拿存储对象，按 setter 名写。
- **类型陷阱（已实测的重要教训）**：引脚语义是布尔，**不代表存储用 C# `bool`**。
  `CHHKK434xan(true)` 改的是另一个 bool 存储槽，导出仍是默认枚举 0；
  原生读的是 `cPOKKkedklwd().Value != 0`；**正确 setter 是 `X8oKKHB87Ue(1u, null)`**。
  → **类型核验必须覆盖「游戏语义类型 → 编辑控件 → 实例值 → 序列化值」四层。**

## 5.5 观察者（读实时入站帧，不占第二条连接）

`start-log-observer` 不是「另开一条连接」—— 它在**编辑器进程内**用 `DispatchProxy` 实现原生观察者接口，
挂到编辑器已有的连接生产者上，因此能看到编辑器真实收到/发出的每一帧。这是**当前唯一能实时看到
编号分布**的手段（第二节的 `packetKinds` 就来自它）。

---

# 六、文件格式接口

## 6.1 GI 容器（`.gip` / `.gil` / `.gia` / `.gir`）

**通用容器，只靠 `file_type` 区分**：

| 偏移 | 类型 | 字段 |
|---|---|---|
| 0 | uint32 BE | `file_size`（= 文件总长 − 4） |
| 4 | uint32 BE | `version` |
| 8 | uint32 BE | 头 magic `0x0326` |
| 12 | uint32 BE | `file_type`：**1=GIP / 2=GIL / 3=GIA / 4=GIR** |
| 16 | uint32 BE | `content_length`（= `file_size` − 20） |
| 20 | bytes | payload（protobuf） |
| 20+len | uint32 BE | 尾 magic `0x0679` |

- **入口**：`.runtime/research-sources/file-formats/auto-miliastra/src/miliastra_agent/core/gi_file.py`
  （`read_header` / `read_payload` / `wrap_payload` / `write_gia`）；
  `parsers/gil.py::parse_gi_file` → `ParsedGiFile{header, level_name, entities, node_graphs, entity_graph_bindings}`。
  **注意**：`parse_gi_file` 返回 Pydantic 模型，须用 `.model_dump()`，不是 `dataclasses.asdict()`。
- **GIA payload** = `AssetBundle`，proto 在 `core/proto/`
  （`gia.proto` / `gia_graph.proto` / `asset.proto` / `entity.proto` / `camera.proto` / `gil.proto`；
  另有社区版 `genshin-miliastra-file-format/proto/**`，**非官方 schema**）。
- **图节点/连线的读法**（`tools/editor-bridge/inspect-graph.py`）：
  `bundle.primary_resource` → `resource_class` 必须为 `ENTITY_NODE_GRAPH` →
  `resource.graph_data.inner.graph` → `nodes[].pins[].value.val_string` / `.connections`。
  **数据连线存在输入引脚上，执行连线存在输出引脚上** —— 校验器把输入侧的数据连接翻转为标准 source→target。
- **已验证范围**：
  - 【已实测】29 个桥接导出的 `.gia` **全部**通过 `magic 0x326 / kind 3 / 尾 0x679 / 长度自洽` 校验（最大 9850 字节）。
  - 【已实测】离线**构造** GIA 并写入，是桥接导入 4 个固定载荷的**上游工序**
    （`build-tiled-route.py` / `build-route-placement.py` 从已有导出包深拷贝节点再改写）。
  - 【静态证据】外层字段 3（导出标识）/4（值 1）/5（引擎版本 `7.0.0`）在早期样本里缺失，
    补齐后游戏才识别。**没有逐字段消融证明三个字段各自都是必要条件。**
  - 【注意】`build-*.py` 与 `repair-*.py` 是**两步**，不能只重跑生成器就假定得到最终可加载包。

## 6.2 `.mihoyobin` 资源文件

- **位置**：`C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\Resource\Json\`
- **变换**：**单字节 XOR `0xE5`**（`array[i] ^= 229`，源码直接常数）
  → 解出后是**完整 protobuf wire 流**。
- **链**：`File.ReadAllBytes` → 逐字节 XOR 0xE5 → `RJP3zgaeW1f<T>()`（`return new T()`，
  **不从文件名查表、不按头部选 schema**）→ `new MemoryStream(..., writable:false)` →
  `U6CEXVPIKZ(instance, stream)` → `MergeFrom`。
  **具体泛型 `T` 由调用端给出** —— 这就是为什么解出字节之后还需要「目录 → 类型」绑定。
- **已验证范围**：

| 项 | 结果 | 等级 |
|---|---|---|
| 全量解码 | **4098 / 4098，失败 0**（`.runtime/editor-catalog/decode.log`） | 【已实测】 |
| 解码产物 | `.runtime/editor-catalog/decoded/` 4098 个 JSON；索引 `index.jsonl` | 【已实测】 |
| Node 目录 → 类型 | `Resource\Json\Beyond\Node` ⇄ `O6LRvEaWgrxTsfxxxCJN.MNwHS2aWqsfoJvDAxLXt`（18 外层字段），四路独立印证 | 【静态证据】 |
| OfficialPrefab 目录 | **未绑定**（2484 文件可解成合法 wire 流，但字段语义一律 unknown） | 未决 |
| Struct 目录 | **未绑定**（140 文件同上） | 未决 |
| BeyondGlobal | 1 文件，56,029 字节，已解 | 【已实测】 |
| TextMap（15 语言） | 已解；CHS 文件 609,674 字节 → 解码后 2,212,859 字节，7743 键 | 【已实测】 |

## 6.3 `assets.bin` / `beyondeditorassets.bin`（ZipCrypto）

| 项 | 值 | 等级 |
|---|---|---|
| 外层 | 有效 ZIP 中央目录，**各 1 个同名加密成员**（`encrypted flag = 1`） | 【已实测】只读中央目录 |
| assets.bin | 磁盘 230,759,334 字节；声明解压后 **231,505,907** 字节 | 【已实测】 |
| beyondeditorassets.bin | 磁盘 6,411 字节；声明解压后 **6,300** 字节 | 【已实测】 |
| **密码** | 字面量 **`G16F153D`** | 【静态证据】该字面量与 `Resource/BeyondAssets/assets.bin`、`.bin`、`.png/.jpg/.jpeg/.gif/.bmp` 同处**同一个资源加载类** `RtdntcKoSeyQejJV6wqv.g5cstNKoCeJmiSQXEnJs` |
| 工程内解包产物 | `.runtime/editor-catalog/assets-bin/assets.dec`（**231,505,907 字节**，与声明解压长度**逐字节吻合**）与 `beyondeditorassets.dec`（6,300 字节）。两者**均为有效 ZIP** | 【已实测】 |

**BeyondAssets 资源清单**：`assets.dec` 是**嵌套 ZIP**，含 **6453 个成员**，
清单位于 `.runtime/editor-catalog/assets-manifest.json`（`{name, size, enc}`，全部为 `ART/UI/Atlas/LS/UGC/**` 下的 PNG 等）。
`beyondeditorassets.dec` 含 1 个成员：`BeyondEditorAssets/UI/Icon/Image/UI_MarkPlayer_Faction.png`。

> **诚实的缺口**：工程内**没有留下**产出 `assets.dec` / `assets-manifest.json` 的脚本
> （全库搜索无 `zipfile` + 密码的解包器）。产物本身（有效 ZIP + 长度吻合 + 6453 条目）已实测，
> 但**密码字面量 → 解包成功**这一步的因果链目前只有「同一类里的字面量 + 产物存在」两段，
> **缺一段可复现脚本**。补上它是一项明确的收尾工作。

## 6.4 格式接口的边界（一句话）

**「文件能读写」≠「编辑器会接受」。** 文件层与编辑器内存层之间**只有两条已证通路**：
① 桥接的 `import-*`（4 个固定 SHA256 载荷）；
② 游戏侧的「加载外部资产」→ 1020 列表 → 用户「转存/使用」。
**没有**「按任意路径加载 GIA」的已证命令。

---

# 七、缺口

## 7.1 明确「尚未接通」的接口清单

| 缺口 | 现状 | 已知的最后一步 |
|---|---|---|
| **后台保存 / 持久化** | **未接通**。2830 条字符串中**不存在** `DoSave` / `SaveProject` / `SaveArchive`；`vmBtnSave*` 只是视图元素名，处理器不在切片内 | 追 `vmBtnSave` 的绑定处理器；或证明「1014 同步返回成功 = 存档已写」——目前**同步返回成功不是保存证据** |
| **开始试玩** | **未接通**。没有接口，试玩只由 UI 触发 | 官方路径含**上传**步骤（有外部依赖）；`3001` 只是日志启用，**不启动试玩** |
| **删除节点 / 删除节点图** | **未接通**。原生**没有 delete 接口**；桥接只能建同名新图或换绑。图只增不减（会话里图数只升不降） | 需要另找原生 delete/recycle 路径 |
| **任意 GIA 导入（按路径）** | **未接通**。`DoImport` 有调用点、参数形状为 `[uint index, bool, string, uint]`，但**分支语义、当前活动模型、收端都未形成完整实测链** | **不要复制四个值就发送。** 中间有外来资产时索引仍是**全列表绝对索引**，不能长期硬编码 0 |
| **导出/导入的 ACK 语义** | **未接通**。`DoExport` 回调实测 `rows: []`；没有已证的自动 ACK；没有已证输出包含标签名称的日志 | 需要结构化读回（模型 ID + Name + 类型）才算验收 |
| **标签（Tag）创建确认** | **未接通读回**。第三次实验**写入完成**（89 字节 sendall 成功，收到 631 字节 / 20 帧，无剩余字节），但 `modelReadbackVerified=false`。随后只读诊断得到 `ModelObjectMatch` 但 `CategoryMatches=false`、`ScanComplete=false`、`RegistryMembershipVerified=false`，且静态证据证明诊断把枚举 23 误当分类路径（真实应为 `[10003, 50013]`） | 需从 registry singleton → `bwbixDw3yob` → 分类集合 → 模型字典验证**对象引用可达性** |
| **1017 完整 schema** | **未接通**。已收敛到 Tag（B=23）单类别；`N8` 是 **19 分支 oneof**，只展开了 Tag 一支；其余 18 类载荷未展开 | 选一个已命名资源类别的 R1mi 下游处理器，查它访问 N8 的哪个 typed getter |
| **其它资源类别的同步** | **未接通**。只跑通了 Tag 一类 | 每类都要单独展开 key/N8 分支/required 状态/增量语义 |
| **场景摆放 / 实体放置** | **未接通**。1024/1025 有载荷类型和调用点，但**未建立可靠场景放置入口** | 追具体 receiver / 服务执行者及调用前置条件，**不猜坐标参数** |
| **导入后实体 ID 重映射** | **未验证**。导入后实体 ID 会被游戏重映射，不能用旧 ID 对照 | 用名称/模板/变换/数量/引用关系核验 |
| **地形编辑 / 环境配置** | **未接通**。没有已验证的地形刷绘或完整场景离线编辑 | 当前静态平台 GIA 不能代表已实现地形编辑 |
| **1020 列表内容读回** | **未接通**。到达过 3 次但 `totalEntriesScanned:0`、`ownAssets:[]` —— **从未读到过真实条目** | 需要一次「列表非空」的会话，再核对条目 name/kind/绝对索引 |
| **按图身份读回自有图的打印内容** | **未接通**。`auditPrints` 全空、`positionPrints.retainedPrints` 恒为 0（37 份记录）。收到的 3002/3006 记录（19 / 83 条）里**没有一条满足「三个名称字段之一 == 我们的图名」** | 先确认为何图名未出现在记录中（筛选字段 vs 采集时机 vs 图身份），再谈读数 |
| **三个 bisect 变体 op** | **从未调用**：`create/build/bind-gameloop-variant-core`（当时的 62 项中仅此 3 项无调用产物） | 需要一次专门的 run；它们是为定位试玩校验失败而准备的 |

## 7.2 只有静态证据的接口

- 全部 `beyond*Service` 命令中除 `DoExport` / `ImportAllDebugLog` / `AddInstructionGraphForEditObj` 之外的条目。
- 出站 1024（有发送点、有 payload 类型，**入站被显式忽略**）。
- **24 个注册编号里只有 6 个被桥接观察器真实观测到**（`1011`×1、`1017`×2、`1018`×13、`1019`×19、`1020`×4、`3006`×35）。
  其余 18 个（`1001` / `1002` / `1004` / `1008` / `1009` / `1010` / `1015` / `1022` / `1025` / `1026` / `1027` /
  `2001` / `2002` / `2003` / `3001` / `3002` / `3003` / `3005`）**在真实会话里一次都没出现**。
  注：`1001` 由**另一个**（无原神的）只收探针观测到 1 次，不由桥接观察器。
- 服务端 socket 类 `yj5YKk3zZEa0yoMqLjwb.QixYoYbYh7R`（`Bind`/`Listen`/`BeginAccept`）——
  **找不到启动调用者**，是「没有可见调用路径」，不是「绝不可能」。**不得去激活它冒充游戏服务。**
- GIA 外层字段 3/4/5 的必要性（有修复成功，**无逐字段消融**）。

## 7.3 仅字符串 / 未命名

- `invalid level state transition `(82936)、`level state changed `(83002)、
  `can't do sync now, level state is `(82602)、`sync cost time `(82674)、
  `sync cost time too long! time=`(82752)：**已定位到具体方法与行号**（见下），
  但 `Ht8rJMinQ4sEdbVnHnwl` 这个关卡状态**枚举只有 `None` 一个可见成员**（反编译结果），
  **各状态编号的业务含义未命名**。已知：`wAXirPMXQCJ(false)` 返回 false 时抛 `EDITOR_NOT_READY_TO_SYNC`；
  同步门控在 `Oe5aspiVGooyp47o5s0q` 内按关卡状态判断，不满足时打 `can't do sync now, level state is ` 并退出。
- `net work error `(45894) → 传输类 `lXPEV83z05tlbqNAuLlZ.gRaBq03zvwCHOLycsWyA`；
  `invalid packet `(50432) → 分发器 `zvgfTUi3zctGDsI4QfYX.TtW15ji3IJs5A1Zve7UP`；
  `listen socket close error `(45984) / `connector socket close error `(46188) / `Tcp Connector fail `(46146)：
  只在字符串表内，**未定位到使用点**。
- `Send ResourceTagCategory Sync - `(49424) → `bE7VcbivnO2x42FMidg6.sNAmfXivJyOiw6vTju5b.cs:442`，**语义未证**。
- 6 个「只有命令名、无调用点」的 beyond 命令（见 2.3 末）。

## 7.4 完全未知

- **端口注册表的写入者与监听者生命周期**。已证编辑器**读**该值；谁**写**它、谁在听，**未知**。
- **对端进程身份的完整证明**。真实会话里 58988 的监听者是原神 PID 132060（【已实测】），
  但**端口是动态的**，且「原神监听」不等于「`DoExport` 处理器已注册」。
- **编辑器与游戏的初始化顺序**：`1002` / `1017` / `1020` 三个入口**不能合并命名为「初始化回复」**；
  是否存在必须遵循的顺序、哪个通知标志完整初始同步结束，**缺证据**。
- **编辑器完整性级别差异**：原神与两个编辑器 RID 12288(high)，Python 诊断 RID 8192(medium)；
  `OpenProcess(QUERY_INFORMATION|VM_READ)` 返回 error 5。**这不是需要关闭原神来解决的问题**，
  也不能靠重启游戏绕过。

## 7.5 三条禁令（总结性）

1. **不得**把「字符串存在」写成「接口可用」（例：`DoImport` 有名字 ≠ 能导入）。
2. **不得**把「有调用点」写成「已验证」（例：`RequestPrefabInstance` 有调用点，且桥接真发过，
   但被 kind 守卫跳过，**实际未请求**）。
3. **不得**把「消息编号被注册」当成「可调用服务」（例：24 个注册编号中，
   **11 个编号**（1003/1005/1006/1007/1012/1013/1014/1016/1021/1023/1024）在分发器里**显式忽略**；
   而 `1001 / 2001 / 2003 / 3001 / 3003 / 3005 / 3006` 根本不在该分发器里 ——
   不能因为「在这个类里没找到」就断定它不存在接收者）。

---

## 附：证据索引

| 主题 | 主文件 |
|---|---|
| 桥接操作白名单 | `tools/editor-bridge/ManagedBridge/BridgeServer.cs` |
| 原生模型操作 | `tools/editor-bridge/Adapter/*.cs`（16 个 partial） |
| 帧格式 | `bridge/IPC-FRAMES.md`、`.runtime/mvp/ipc-framing/TRACE.md`、`framing-slots.json` |
| 消息编号表 | `.runtime/mvp/ipc-framing/message-ids.json`、`message-factory.cs` |
| 端口与注册表 | `.runtime/mvp/ipc-research/port-provider.cs`、`TRACE.md`、`socket-role-map.json` |
| 1017 / Tag | `docs/offline-research/INITIALIZATION-DEPENDENCIES.md`、`RESOURCE-SYNC-PAYLOAD.md` |
| 1018 / 保存路径 | `docs/offline-research/SAVE-PATH-TRACE.md` |
| 1020 / 导入 | `docs/gameplay/GIA-IMPORT-PATH-AUDIT.md` |
| 标签读回 | `docs/offline-research/TAG-READBACK-PATH.md`、`TAG-DIAGNOSTIC.md` |
| 资源文件格式 | `docs/offline-research/RESOURCE-FILE-LOADER.md`、`RESOURCE-MAP.md`、`RESOURCE-TYPE-MAP.md` |
| GI 容器与 proto | `.runtime/research-sources/file-formats/auto-miliastra/src/miliastra_agent/core/` |
| 运行产物 | `.runtime/editor-bridge/runs/`（104 个 run）、`.runtime/editor-bridge/exports/`（29 个 `.gia`） |
| 实时会话 | `.runtime/verification/live-session-20260915/` |
| 字符串表 | `.runtime/editor-catalog/string-table.json`（2830 条）、`annotated/`（带偏移注释的反编译） |
