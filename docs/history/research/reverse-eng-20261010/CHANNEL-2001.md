> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 通道 2001 — 组件字段消息：定义在、发送器死、接收器无

**产出日期**：2026-10-10
**口径**：**纯离线、纯只读**。全程**未连接桥、未向游戏/编辑器发任何报文、未启动或触碰任何进程、未写任何存档**
（记忆 `ayaya-ugc-tools-must-not-run`、`beyondassisteditor-read-only` 遵守）。
证据只有三处：① 仓内 `.runtime/editor-catalog/resolved/`（12375 个反编译 `.cs`，用 Bash `grep` 查——**Grep 工具会静默跳过 `.runtime/`**）
② 仓内研究文档 ③ `docs/research/beyondeditor-backend/db/backend.db`（只读 SQL）。
**本文件只新增，不改任何既有文档。**

> 按 `CLAUDE.md` §一.3 / §五：`文档写了什么` / `工具能做什么` / `真机验证过什么` 三层分开标。
> 本文结论**全部是静态**（读反编译 / 读 db / 读研究文档）；**没有任何一条是本轮真机跑出来的**。
> **"搜不到"≠"不存在"**——凡负面结论均写明检索范围。行号为本次 checkout 实测。

---

## 0. 一句话结论

**2001 的"通道定义"是活的，但它在编辑器里是「发送器被常量假分支掐死、且没有任何接收器」的通道——不是一条可用的组件写入路径。**

三句话拆开：

1. **消息格式是现役的**：入站/出站共用的编解码器里注册了 `2001 → gcxejEBKDw4nOrlXagP` 这个用户态消息类
   （`.../GWqAg83zFaJvFpOYIPy3.epbDga3zjH0G4a8XYEO8.cs:66`），帧层能对它序列化/反序列化。**这不是"废弃的号段"**。
2. **唯一的业务发送器在磁盘程序集里不可达**：`if (false)`（`.../IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:432`）
   掐死了整条"建 payload → 发 2001"的构造链；被跳过后方法直接清理返回。（与 `PROGRESS.md:6302` 的原始 IL 记录一致：
   `IL_009c ldc.i4.0 / IL_009d brtrue`。）
3. **没有任何接收器会应用这条消息**：前端唯一的分发器 `TtW15ji3IJs5A1Zve7UP.seAYooJHAHf` **没有 2001 的 case**
   （落在 `IL_0113 → return`，`.../zvgfTUi3zctGDsI4QfYX.TtW15ji3IJs5A1Zve7UP.cs:291`）；后端 `message_route` 只登记
   **1001–1024**（`backend.db`，24 行，无 2001）；后端出站表 `egress_producer` 也**没有 2001**。

**⇒ 把 `:432` 的常量翻成 true，只是让编辑器多发一个"无人接收的字段帧"。它不会变成组件写入路径，也不会解锁 M1/M4/M5——**
因为那两个需求要的是「**加**组件」，而 2001 是「给**已有**组件改字段」（且载荷里的身份是**组件 id**，不是实体 id，
见 `PROGRESS.md:6204`）。

---

## 1. 那个分支的 FULL CONTEXT（`if(false)` 前后到底在干什么）

### 1.1 现场：这是"组件详细编辑页"的提交处理器

| 事实 | file:line |
|---|---|
| 类 `YWlUeFKpEU3Lh8YnZ6Mj` = 单个**组件**的详细编辑器 VM（`vmHeader` / `vmProperties`，取 key = 组件 id） | `.runtime/editor-catalog/resolved/IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:34, :44, :56, :161-174` |
| 它持有**正在被编辑的那个组件模型** `nWiKpMFrtFD`（类型 `LudM06iCRNk4iFkwqKIW`） | 同上 `:40`；由工厂 `CIGKpvltYmS(P_0, P_1)` 灌入 `:68-80` |
| 组件 id 从 `LudM06iCRNk4iFkwqKIW.b1EiCj8P44N.Value` 取（uint） | 同上 `:173` |
| 事件 **69**（本 VM 的构造器在 `:210` 注册 73、`:303-306` 处理 69）触发 `QS2KpiuBk8S` | 同上 `:303-306` |
| `QS2KpiuBk8S(bju4fOixj9ArfNltjgDa P_0)` 就是这个处理器——**2001 的发送器在它里面** | 同上 `:315` |

⇒ 语境确定：用户点"详细编辑"改组件字段 → 事件 69 → 本处理器把**改动后的字段**打包成 2001 发出去。
**它天然是"改字段"，不是"加组件"。**

### 1.2 那个条件到底是什么


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**这个 `if(false)` 不是 CFF 状态机的普通 guard 字段读**（本文件其它 guard 一律长 `if (<Module>{…}.m_xxxx != 0)`，
反编译器会保留成字段比较），而是一颗**编译期常量**：反编译器把它解析成字面 `false`，对应原始 IL 的
`ldc.i4.0; brtrue`（`PROGRESS.md:6302` 已用 ilspy-dump 直接导出过这段 IL，本轮从源码侧复核一致）。

**它掐死的范围（这是关键）**：我用状态号逐条追了一遍——**`num2 = 10` 在整个方法里只出现在 `:435` 这一处**。
而整条"建 payload → 发 2001"的链条是单入口的：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


> 注意区分：QS2KpiuBk8S 里 `case 10` 在 `:375`（"确保载荷已建"），**不是**另一个方法
> `CCFKpKwZ3GB`（事件 73 处理器，`:511-685`）里的 `case 10 (:655) goto IL_031f (:672)`——
> 二者同号不同体，别混。

**这张链条的每一环都只能由 `:435` 引入**（`case 10` 只能靠 `num2 = 10` 到达；`case 3` 的出入口都在链条下游）。
`if(false)` 恒假 ⇒ **整条链死透，方法退化成"清个 list 就 return"**。
（`PROGRESS.md:6204` 的独立记录是同一个结论："2001 唯一业务 sender 的原始 IL 为常量假分支，且属性路径列表未构造"。）

> **诚实标注**：块体是一段**完整、自洽的业务逻辑**（设了组件 id、设了字段值、设了种类常量），
> 不像混淆器随手插的垃圾死代码。所以"当初的源码为什么是恒假"有三种可能——(a) 开发者留下 `if(false)`；
> (b) 混淆器/编译期把某个 feature 开关折叠成常量；(c) 某个 `#if` 平台分支。**本语料无法区分**。
> 但对本轮问题而言三者等价：**在这份磁盘程序集上，它永不执行**。

### 1.3 它要建的报文、装的什么、会去哪

| 项 | 值 | file:line |
|---|---|---|
| **消息号** | `2001`（BE uint16 上线） | `.../IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:475` |
| **载荷类** | `TDkCIQBu2aiStr6db9a.gcxejEBKDw4nOrlXagP`（protobuf 风格，单字段 #10） | `.../TDkCIQBu2aiStr6db9a.gcxejEBKDw4nOrlXagP.cs:14, :30, :32, :46-56` |
| **字段 #10 类型** | `jEcbTytNr1rcKPlqIj4.hlS35JtRO42rGu9MG9Q`（"字段袋"） | `.../jEcbTytNr1rcKPlqIj4.hlS35JtRO42rGu9MG9Q.cs:19, :28-34` |
| **袋里装什么** | 组件 id (`b1EiCj8P44N.Value`) + 种类常量 `3` + 一个 `vD12Hm2PObeNaaZvWDG` 子对象 | `:389` / `:355` / `:330` |
| **子对象装什么** | 编辑事件 `P_0` 的各字段：`HIhixJLOnyY` / `zyuixrsb2kw` / `deUixnV9L8T` / `dZyixVenaNJ` / `F5IixCoVVW1` + 一个 `int` 列表 | `:401` / `:481` / `:484` / `:492` / `:495` / `:460` |
| **发送原语** | `Producer.PHCi086M7o5(ushort msgId, 消息对象)` | `.../tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh.cs:453` |
| **去向** | 走 `wYxi0oLiHdJ.IvPYoLkWvv0(envelope)`，`wYxi0oLiHdJ` 是 `NZ9BZA3IM2qyEiuWoLhM` 连接 | 同上 `:34, :478-480` |
| **连接实现** | **TCP Socket**（`System.Net.Sockets.Socket`），连到配置键 `"port"` 指定的端口 | `.../WDm2373zSsiuuqgLKJqT.HLCgI93zCuLou1Z2RiaY.cs:14, :270, :292, :313` |
| **线格式** | `[BE u16 magic 0x0656][BE u16 msgId][BE u32 len][len 字节载荷, 每字节 XOR 0xEA][BE u16 tail 0x0666]` | `.../xp3xUm3Ijc4F6ZO5bV32.HAblpO3INAjJCdfp46lI.cs:57-168`（写）`:170-280`（读）；`.runtime/mvp/ipc-framing/TRACE.md` |

⇒ **一句话**：它会经**编辑器↔游戏进程的那条 TCP 通道**，把一个"某组件（组件 id=…）的一组字段值"发给对端。

---

## 2. 2001 通道定义：谁收、什么 schema、有没有"应用组件字段"的处理器

### 2.1 注册处（"这个号是被承认的"）——有

`GWqAg83zFaJvFpOYIPy3.epbDga3zjH0G4a8XYEO8` 是一张 **`Dictionary<ushort, 工厂委托>`** 消息注册表：

- 表字段 / 构造：`.../GWqAg83zFaJvFpOYIPy3.epbDga3zjH0G4a8XYEO8.cs:35` / `:42`
- **2001 注册**：`:66` `BTX3zfORc1v.Add(2001, …RJP3zgaeW1f<gcxejEBKDw4nOrlXagP>);`
  （同表还登记 1001,1002,1004,1008-1011,1015,1017-1020,1022,1025-1027, **2002,2003**, 3001-3003,3005,3006）
- 查表：`XSi3z6QuDjf(ushort)` `:163`（未知号返回 null）
- 被谁用：接收侧帧解码 `.../xp3xUm3Ijc4F6ZO5bV32.HAblpO3INAjJCdfp46lI.cs:198`（读到 msgId 后取工厂 → 建对象 → `MergeFrom`）

⇒ **通道在编解码层是活的**：对端真发了 2001，编辑器**能解**。
（旁证：`.runtime/mvp/ipc-framing/message-ids.json` 的 2001 条目 `source_line: 66` 就是这一行。）

### 2.2 schema——单字段 #10

- 载荷类 `gcxejEBKDw4nOrlXagP`：只有一颗字段 `usHB8BF1Bi : hlS35JtRO42rGu9MG9Q`（`:30, :32`），
  属性 `ynZBPqVfNf`（`:46-56`），`WriteTo` 只在字段非空时写 tag 10（`:179-180`），
  `MergeFrom` 只在 `num3 == 10` 时收（`:293-303`）。
- 字段袋 `hlS35JtRO42rGu9MG9Q`：4 颗字段 + 一个种类判别子 `h7INQR7HEO1UBfx8LKQa`（`:28-34`），
  且 `vVKtSNwmH3`(:74) / `wlltB5dAkV`(:102) 是"同槽 union + 判别值"（`RUaBifJpyb`）——与文档 §2.3 描述的组件模型一致。

⇒ schema 清楚：**`2001 = { 字段袋(组件 id + 编辑后的字段值) }`**，语义 = 「组件字段更新」。

### 2.3 接收者——**前端唯一分发器没有 2001 的 case**

编辑器侧负责"把入站消息交给业务处理器"的是 `zvgfTUi3zctGDsI4QfYX.TtW15ji3IJs5A1Zve7UP`（实现接收者基接口
`mms6AS3ILkPSiIMIK84R.a2loy23IhuQeagPQb4Bx`，见 `.../mms6AS3ILkPSiIMIK84R.a2loy23IhuQeagPQb4Bx.cs:5`；
由 Producer 帧泵遍历接收者表调用，`.../tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh.cs:548`）：

- `seAYooJHAHf(...)` `:60` 按 msgId `switch`（`:68`）。
- 分发器显式处理的号（本次实测）：2002、1010、1017、1008、1027、1002、1020、1025、1019、
  1003/1005/1006/1007/1012/1013/1014/1016/1021/1023/1024、1018、1015、1011、1009、1004、1026、1022。
  **其中没有 2001**（也没有 2003/3001/3003/3005/3006）。
- 落到 `default: goto IL_0113;`，`IL_0113` 在 `:291` → `num2 = 15` → `case 15: return`（`:260-261`）。**静默丢弃**。

**范围诚实**：语料里 `grep -rInE '\b2001\b' .runtime/editor-catalog/resolved/` 只有 **3** 行
（`:66` 注册、`:475` 发送、`XvpSBIuvoMSpMenoIqRg.C9ev3quv9MKMEBmJNJDj.cs:5182` 一处无关的枚举比较 `2000 || …2001`）。
**在 12375 个反编译类里，没有任何 `case 2001`、也没有第二个接收者。**
（反面对照：`3006` 在本分发器同样无 case，但**有真实入站流量** ⇒ "不在本类里" ≠ "没人收"。
所以 2001 的负面要再加后端的证据，见 §3。）

### 2.4 后端（游戏侧）的接收表——没有 2001

`docs/research/beyondeditor-backend/db/backend.db`：

- `message_route`（**24 行**，`min(msg_id)=1001, max=1024`，direction 全 `in`）——**只登记 1001–1024**，无 2001/2002/2003/300x。
- `egress_producer`（游戏→编辑器方向）7 行：1020 / 1019 / 1018 / 1017 / 1011 / 3006 / 0——**无 2001**。
- `dispatch_entry`（41 行）是**命令**分发表（FocusEditObj / DeleteComponentForEditObj / …），**不是消息表**，与 2001 无关。

补充（仓内研究文档的既证，非本轮新测）：`PROGRESS.md:5834` 记游戏侧消息分发器 `0xa223420` 按 ushort 类型
经 **24 项跳表**处理 1001–1024，另加 1025、3001 两个分支；**2001 走"高分支"、既非 1025 也非 3001，最终到
`0xa223993 ret`**（即未处理）。`PROGRESS.md:5874` 记在 `0xa210000–0xa240000` 的有界扫描**无 2001 接收器**
（该轮自注"此不证明无接收器"）；对全映像 32 位立即数 2001 的 245 个候选函数筛查后也**未能证明**其中任何一个是 2001 的 WPF 消息处理器。

---

## 3. 与 1001–1024 的对照：2001 是"live-but-disabled"还是"dead feature"

| 通道族 | 有工厂（能解码） | 前端有分发 case | 后端 `message_route` | 后端 `egress_producer` | 实测流量 |
|---|---|---|---|---|---|
| 1001–1024 | 部分有 | **有多数** | **有（24 行，逐条 handler RVA）** | 1011/1017/1018/1019/1020 有 | 多条实测（1011/1017/1019/1020/3006…） |
| **2001** | **有**（`:66`） | **无**（→ 静默丢弃） | **无** | **无** | **0 / 0** |
| 2002/2003 | 有 | 2002 有 / 2003 无 | 无 | 无 | 0 / 0 |

- 实测流量列来自 `docs/research/beyondeditor-frontend/05-前后端通信通道.md:90`（2001 = `0 / 0`，
  并已正确记 "前端唯一 sender 的 IL 是常量假分支"；该文档**与本文结论一致，无需改**）。
- 后端 `message_route` 的 handler RVA 逐条存在，是**游戏侧真的会处理 1001–1024 的硬证据**；
  2001 **一条都没有**。

**判决**：**2001 = 定义在（编解码层）、发送器被常量假分支掐死、两端都没有接收器的通道。**
按 `CLAUDE.md` §一 的口径，这既不是"live-but-disabled"（live 要求至少一侧有人处理），
也不是干净的"dead feature"（格式是现役的）——准确说法是 **"registered-but-unrouted"（登记未路由）**。

> **为什么不是"死特性"那么强**：因为 `message-ids.json` / 注册表说明编解码层仍承认 2001，
> 且 `:432` 的块体是完整业务逻辑。更中肯的解释是：**这是"曾经/本该有一条 组件字段→游戏 的同步"，在本构建里被关掉了**，
> 而关掉它的同时，接收侧也没有留下处理器。
> **为什么不是"live"**：前端唯一分发器无 case + 后端两张表都无 2001 + 实测 0 流量，三条独立证据同向。

---

## 4. 把 2001"打开"需要什么？能从编辑器进程外够到吗？

### 4.1 打开发送器本身

- **需要改二进制**：`if(false)` 是编译期常量（原始 IL `ldc.i4.0; brtrue`）。要让它发，必须
  **改写 BeyondEditor.dll 的 IL / 打补丁**，或改源码重编译。**这不是桥能做的**——
  桥是**反射调用已加载的程序集方法**，不改已 JIT 的 IL；本工程也**禁止注入/重编译**（用户硬规则）。
- **即使改了也没用**：§2.3/§2.4 已证**接收侧没有处理器**。发出去的 2001 帧在编辑器侧被本地分发器丢弃、
  在游戏侧 `message_route` 里无落点。**翻常量 ≠ 打开组件写入路径**。
- **且它根本不是"加组件"**：2001 载荷装的是"已有组件的字段值"（身份 = 组件 id）。
  要解锁 M1/M4/M5，缺的是「**加**组件」原语（`AddComponent` 家族，本工程已证命令面 0 命中），
  与 2001 是否可发**无关**。

### 4.2 能不能绕过 `if(false)`、直接从编辑器进程里"发一条 2001"

- **桥理论上够得着发送原语**：桥已经用同一张 `Producer` 单例发命令（`Ikci0qkvMZX`），
  而 2001 走的是同一个 `Producer.PHCi086M7o5`（`.../tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh.cs:453`）。
  所以"从桥里调 `PHCi086M7o5(2001, payload)`"在**机械上**不需要改二进制。
- **但这条路被三重门挡住，且不该走**：
  1. **载荷构造需要未采样的类型**（`gcxejEBKDw4nOrlXagP` / `hlS35JtRO42rGu9MG9Q` / `vD12Hm2PObeNaaZvWDG`）
     与其字段写法——绑定档里**一个组件/属性符号都没有**（`COMPONENT-WRITER-MINE.md` §4）。
  2. **无接收器**（§2.3/§2.4），发了也没人应用——属"猜发"，`CLAUDE.md` §四明确禁止。
  3. `05-前后端通信通道.md` 对同类号（1024）的纪律原文："**禁止猜发**"。

### 4.3 从编辑器进程外够到？

- **不能直连**：2001 的落点是**编辑器进程主动建立的那条 TCP 连接**（`HLCgI93zCuLou1Z2RiaY.Connect`
  连到配置键 `"port"`，`:270, :313`）。第三方要插话，等于要**冒充编辑器去连游戏端口并构造合法帧**
  （magic 0x0656 / XOR 0xEA / tail 0x0666）——这是**对游戏进程发未验证报文**，`CLAUDE.md` §四禁止的操作。
- **桥 ≠ 进程外**：桥是**注入 / 反射进 BeyondEditor.exe 内部**执行的（`CLAUDE.md` §二），
  所以它能调 `PHCi086M7o5`，但它调用的**结果同样经这条 TCP 出去、同样没有接收器**。
- **结论**：2001 在"通道存在"的意义上可从**编辑器进程内部**触达；但"触达"不等于"生效"——
  **在当前逆向水平下没有证据表明任何一端会应用它**，因此它不是一条可用的写入路径。

---

## 5. 证据索引

| 论断 | 证据（file:line / 表） |
|---|---|
| 组件详细编辑器 VM + 事件 69 → `QS2KpiuBk8S` | `.runtime/editor-catalog/resolved/IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:34,40,44,56,68-80,161-174,210,303-306,315` |
| **`if(false)` 位置** | 同文件 `:432`（原始 IL `ldc.i4.0/brtrue`：`PROGRESS.md:6302`） |
| payload 构造入口唯一（`num2 = 10` 仅 `:435`） | 同文件 `:412,330,355,389,446,392,471,341,475,375,352,480,481,483,484,491,492,494,495` |
| **2001 发送点** | 同文件 `:475`（`PHCi086M7o5(…, 2001, gcxejEBKDw4nOrlXagP, …)`） |
| 发送原语 | `.runtime/editor-catalog/resolved/tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh.cs:34,453,478-480` |
| 连接 = TCP + 配置端口 `"port"` | `.runtime/editor-catalog/resolved/WDm2373zSsiuuqgLKJqT.HLCgI93zCuLou1Z2RiaY.cs:14,241,270,292,313`；接口 `.../UJ5oX33I8PVUcq563icT.NZ9BZA3IM2qyEiuWoLhM.cs:26-30` |
| 线格式 / XOR 0xEA / magic 0x0656 / tail 0x0666 | `.runtime/editor-catalog/resolved/xp3xUm3Ijc4F6ZO5bV32.HAblpO3INAjJCdfp46lI.cs:57-168,170-280`；`.runtime/mvp/ipc-framing/TRACE.md` |
| **2001 注册（工厂）** | `.runtime/editor-catalog/resolved/GWqAg83zFaJvFpOYIPy3.epbDga3zjH0G4a8XYEO8.cs:35,42,66,163`；`.runtime/mvp/ipc-framing/message-ids.json` 2001 条目 |
| 载荷 schema（单字段 #10） | `.runtime/editor-catalog/resolved/TDkCIQBu2aiStr6db9a.gcxejEBKDw4nOrlXagP.cs:14,30,32,46-56,159-184,263-309` |
| 字段袋类型 | `.runtime/editor-catalog/resolved/jEcbTytNr1rcKPlqIj4.hlS35JtRO42rGu9MG9Q.cs:19,28-34,61-98` |
| 接收侧解码用工厂 | `.runtime/editor-catalog/resolved/xp3xUm3Ijc4F6ZO5bV32.HAblpO3INAjJCdfp46lI.cs:170,198,201` |
| **前端唯一分发器无 2001 case** | `.runtime/editor-catalog/resolved/zvgfTUi3zctGDsI4QfYX.TtW15ji3IJs5A1Zve7UP.cs:39,60,66-118,260-261,291`；接收者基接口 `.../mms6AS3ILkPSiIMIK84R.a2loy23IhuQeagPQb4Bx.cs:5`；帧泵 `.../tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh.cs:548` |
| **后端无 2001** | `docs/research/beyondeditor-backend/db/backend.db` → `message_route`（1001–1024, 24 行）、`egress_producer`（1020/1019/1018/1017/1011/3006/0） |
| 全语料 `\b2001\b` 仅 3 行、无 `case 2001` | Bash `grep -rInE '\b2001\b' .runtime/editor-catalog/resolved/` |
| 游戏侧分发器 24 项表 + 2001 走高分支 ret | `PROGRESS.md:5834,5874` |
| 2001 唯一 sender 常假分支（既有记录） | `PROGRESS.md:6204,6298,6302` |
| 实测 2001 = 0/0、无 case、常假分支 | `docs/research/beyondeditor-frontend/05-前后端通信通道.md:90,99` |
| 2001 候选 3 的既有描述（与本轮一致） | `docs/research/reverse-eng-20261010/COMPONENT-WRITER-MINE.md` §0 候选 3 / §7(b) |
| 组件"加"家族命令面 0 命中 | `CLAUDE.md` §五/§六；`COMPONENT-WRITER-MINE.md` §1/§5 |

---

*本文件由 2026-10-10 会话从仓内 `.runtime/editor-catalog/resolved/`（Bash `grep`，非 Grep 工具）、
仓内研究文档与 `backend.db`（只读 SQL）静态整理；**未实现、未运行、未连接桥、未触碰游戏/编辑器、未写任何存档**。
凡"有实现没跑过"的均标 `只离线` / `未验证`；凡负面结论均写明检索范围。*
