> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 编辑器的具名命令通道（本轮最重要的接口发现）

调查日期：2026-09-17。**全静态证据链，无任何实机调用。**

本文件记录一条此前工程未记录的接口：编辑器内部有一个**通用具名命令派发通道**，
它把"删除对象""导出资产""聚焦镜头"等编辑操作以**字符串命令名 + 参数列表**的形式
发给生产者/传输层。这直接对应任务目标中的"如何能直接通过代码的方式修改千星编辑器的内容"。

---

## 一、通道的形态

### 1.1 派发委托


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


元数据成员（`ilspy-dump find/members` 直接读出）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


> **一处必须澄清的边界**：`xyVYfsr3qg0` 这个注入的静态代理**不是本通道独有**。
> 全程序集共有 **9,289 个委托类型**带这个成员——它是 ConfuserEx 的**方法代代理**保护
> （把普通调用改写成 `委托类型.xyVYfsr3qg0(实参…, 槽位字段)`）。
> 因此本节的可靠读法是：**存在一个签名恰为 `(object, string, string, Action<List<Param>>, List<Param>)`
> 的被调用方法，其代理槽位是 `BrjMRrl2xRXv5aqZQkDJ.snthqqZ3HCR`**；
> 调用语义为「(生产者, 通道, 命令名, 回调, 参数)」。
> 工程既有的代理映射表（`.runtime/mvp/ipc-research/proxy-map-result.json` 记 34,728 条映射）
> 是把该槽位还原成真实方法的下一个工具，**本轮未执行它**。

### 1.2 调用点实样

`VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:784`（删除实体对象分支，原文照录，
仅把已还原的字符串标出）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


⇒ 派发通式（**这是本文件的核心结论**）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


### 1.3 三个参与类型

| 角色 | 混淆类型名 | 说明 |
|---|---|---|
| 生产者单例 | `vSwq2Ui3deULA6AUjQxt<tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh>.pZgi3PiTIE8()` | **与工程桥接已在用的 `Producer` 同一类型** |
| 通道常量 | `HOlfE6lSftgl74pgvnRM` | 本身也是委托类型，含 13 个静态字段常量 |
| 参数单元 | `yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv` | **与桥接 `EditorAdapter.cs` 中的 `Param` 同一类型** |

桥接已经持有生产者与参数类型——**缺的只是这个派发委托**。

---

## 二、通道标识（13 个）—— **已真机验证**

`HOlfE6lSftgl74pgvnRM` 的静态字段共 13 个：
`wtRlSp6GrvH`、`P9plSZjW9OJ`、`KJZlSrdSUL1`、`TnxlzlI8Hk0`、`Oerlz9Jdbnf`、`VdghK1XTDpm`、
`cN5hqlJY835`、`YSDhqo1YVyx`、`Is6hqU640RJ`、`BsxLvIOuJMp`、`Cg3LuDiYIgD`、`JxZLSauoPXi`、`boGLyQBJv9p`

它们**不是常量，而是零参静态读取器**；在运行中的编辑器里调用后返回**真实的编辑服务名**：

| 槽位 | 返回的通道标识 | 承载的命令 |
|---|---|---|
| `YSDhqo1YVyx` | **`beyondEditObjService`** | DeleteEditObj、DeletePrefab、ModifyEditObjName、ModifyPrefabName、ModifyPrefabTag、Focus* 系列 |
| `BsxLvIOuJMp` | **`beyondExportService`** | DoImport、DoExport、Import/Delete/Refresh DebugLog |
| `cN5hqlJY835` | `beyondInstructionGraphService` | create、delete、riskReport |
| `Is6hqU640RJ` | `beyondPCGInstanceService` | （未观察到命令） |
| `Cg3LuDiYIgD` | `beyondRoleStatusService` | （未观察到命令） |
| `JxZLSauoPXi` | `beyondEffectService` | focus |
| `boGLyQBJv9p` | `beyondAudioService` | PlayMusic、Stop |
| `wtRlSp6GrvH` | `wpfAudioService` | （未观察到命令） |
| `P9plSZjW9OJ` | `wpfApplicationService` | （未观察到命令） |
| `KJZlSrdSUL1` | `wpfInstructionGraphService` | （未观察到命令） |
| `TnxlzlI8Hk0` | `Log/log.txt` | 非服务，日志路径读取器 |
| `Oerlz9Jdbnf` | `Log/logPre.txt` | 非服务，日志路径读取器 |
| `VdghK1XTDpm` | `C:\Users\PUBLIC_USER\AppData\Local\BeyondEditor` | 非服务，数据目录读取器 |

⇒ 第二实参是**服务名**，第三实参是**命令名**。
这同时解释了工程既有记录里的写法 `beyondExportService.DoImport`。

**验证方式与证据**见 INTERFACE-VERIFICATION.md（历史来源：`INTERFACE-VERIFICATION.md`） 第四节。
验证操作只调用"零参静态返回 string"的读取器，未向游戏发送任何内容。

---

## 三、已还原的命令词表（23 条，含所属通道）

提取方式：扫描全部 12,375 个反编译文件，定位 `BrjMRrl2xRXv5aqZQkDJ.xyVYfsr3qg0(` 调用，
按括号配平截取实参区间，取其中的字符串字面量与 `HOlfE6lSftgl74pgvnRM.<常量>`。

| 通道常量 | 命令名 | 调用点类型 |
|---|---|---|
| `YSDhqo1YVyx` | `DeleteEditObj` | `VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf` |
| `YSDhqo1YVyx` | `DeletePrefab` | 同上 |
| `YSDhqo1YVyx` | `ModifyEditObjName` | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q` |
| `YSDhqo1YVyx` | `ModifyPrefabName` | 同上 |
| `YSDhqo1YVyx` | `ModifyPrefabTag` | `kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0` |
| `YSDhqo1YVyx` | `FocusEditObj` | `FOV9AWu5QBsMPf0Rwuiu.NQ6Rasu5Wb3lL511Sp4j`（另有 1 处） |
| `YSDhqo1YVyx` | `FocusCharacter` | 同上 |
| `YSDhqo1YVyx` | `FocusDropGather` | 同上 |
| `YSDhqo1YVyx` | `FocusEsp` | 同上 |
| `YSDhqo1YVyx` | `FocusLight` | 同上 |
| `YSDhqo1YVyx` | `FocusLocalBullet` | 同上 |
| `BsxLvIOuJMp` | `DoImport` | `XTIMALKC7WrrvhklkdIs.EC9LaXKCud5dn7MZnrgl` |
| `BsxLvIOuJMp` | `DoExport` | `VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf` |
| `BsxLvIOuJMp` | `ImportDebugLog` | `XvpSBIuvoMSpMenoIqRg.C9ev3quv9MKMEBmJNJDj` |
| `BsxLvIOuJMp` | `ImportAllDebugLog` | 同上 |
| `BsxLvIOuJMp` | `DeleteDebugLog` | 同上 |
| `BsxLvIOuJMp` | `RefreshExistDebugLogReport` | 同上 |
| `boGLyQBJv9p` | `PlayMusic` | `EF8cLvuBwl2IuhblDnsW.JVFa9yuBBE11Zhdy7ce5` |
| `boGLyQBJv9p` | `Stop` | 同上 |
| `cN5hqlJY835` | `create` | `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q` |
| `cN5hqlJY835` | `delete` | 同上 |
| `cN5hqlJY835` | `riskReport` | `s2HZmTKPhcL6PgOLa9qf.tKA5s0KPlwTMZD6OVhNI` |
| `JxZLSauoPXi` | `focus` | `C7891kuZ7qDbbK7CWHQh.tC38a9uZumHDvhgFUCLl` |

> 注意大小写并存：`FocusEditObj`（通道 `YSDhqo1YVyx`）与 `focus`（通道 `JxZLSauoPXi`）
> 是**两条不同的命令**，不是同一条的两种写法。
> 另：`AddInstructionGraphForEditObj`、`RequestPrefabInstance`、`ApplyPrefabInstanceChange`、
> `SerializeObject`、`OnLevelInit` 等字面量存在于字符串表中，**但未出现在本轮的派发调用点扫描结果里**，
> 说明它们走的是别的路径（或调用点在反编译失败的 2,555 个类型中）。**不得当作已接通命令。**

---

## 四、参数构造（以 `DoImport` 为例）

`XTIMALKC7WrrvhklkdIs.EC9LaXKCud5dn7MZnrgl.cs:486` 与 `:490` 两处，参数按位置包装：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


⇒ 参数形状 **`[uint, bool, string, uint]`**，与 `PROGRESS.md` 早前记录的
「`beyondExportService.DoImport` 参数形状为 `[uint index, bool, string, uint]`」**一致**，
而本轮把它的**构造方式、通道常量与派发委托**都定位到了具体类型。

两处调用的差异仅在 bool 与第 4 个 uint：一处为 `true` + `flag?1:0`，另一处为 `false` + `num2`，
第 3 个参数一处是 `string.Empty`、一处是文件路径 —— 与「试探是否存在 / 按路径导入」的分支形态相符（**推断**）。

> 既有记录明确写过「**不要复制四个值就发送**」。本轮**没有**发送、没有连接、没有调用。
> 上述仅为静态读出的构造方式，**不足以证明服务端会接受**。

---

## 五、代理槽位已解析到真实方法（`tools/editor-catalog/resolve-proxy.py`）

工程既有的代理映射资源（34,728 条）本轮已完整解出。与本通道相关的槽位解析如下。

### 5.1 派发与参数

| 槽位 | 真实目标 | 作用 |
|---|---|---|
| `BrjMRrl2xRXv5aqZQkDJ.snthqqZ3HCR` | **`tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh::Ikci0qkvMZX`** | **命令派发入口**（该类型即桥接的 `Producer`） |
| `BrjMRrl2xRXv5aqZQkDJ.BQel2dOESVB` | `kJebiGi0wckPoYphgKNO.TC9Tn2i0BNsxu8MM0XOF::Daxi0kkneV1` | 同类型的另一槽位，用途未定 |
| `EOHYfjqMv7P`（对照） | `qmcI6kYhr1tEjgMBZY1r.Y9F2H0YhZJ8wH9Xl5wuT::cBVYLdhAhVY` | 字符串表解码器——**解析管线的正确性佐证** |

### 5.2 通道常量 → 真实方法

`HOlfE6lSftgl74pgvnRM` 的 13 个常量全部是 `gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP` 上的方法：

| 通道常量 | 真实方法 | 该通道承载的命令 |
|---|---|---|
| `YSDhqo1YVyx` | `yPFiAIrmqCV` | DeleteEditObj / DeletePrefab / Focus* / Modify* |
| `BsxLvIOuJMp` | `jtXi3msT74g` | DoImport / DoExport / *DebugLog |
| `boGLyQBJv9p` | `w5vi3EMKm7u` | PlayMusic / Stop |
| `cN5hqlJY835` | `eQHi3vwxAyn` | create / delete / riskReport |
| `JxZLSauoPXi` | `SiKi359WufY` | focus |
| `wtRlSp6GrvH` | `qFQi3il61x5` | 未观察到命令 |
| `P9plSZjW9OJ` | `wyni3ubhjqm` | 未观察到命令 |
| `KJZlSrdSUL1` | `zSti3Yyn65w` | 未观察到命令 |
| `Is6hqU640RJ` | `YrFi3A6H2I8` | 未观察到命令 |
| `Cg3LuDiYIgD` | `d3di3bdsTUl` | 未观察到命令 |
| `TnxlzlI8Hk0` / `Oerlz9Jdbnf` / `VdghK1XTDpm` | 未在本轮解析出的槽位中出现 | — |

同类型上另解析出 `L8IiACRvPVs`（槽位 `w7uAqULvzhHRAFYTbySr.CXBL05s2Aiw`），
在 `DoImport` 调用点用作**参数列表构造器**。

### 5.3 参数构造器（`Param` 类型 `yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv`）

该类型共 7 个可调用构造槽位，其中三个的类型可由 `DoImport` 调用点直接确定：

| 槽位 | 真实方法 | 类型 |
|---|---|---|
| `Yko1Gll2ZJdSIZmJQ0Vn.W88l2rgbNcI` | `bKliA0tj1p1` | **uint** |
| `Yko1Gll2ZJdSIZmJQ0Vn.yFAl2wGFsdy` | `qsriAuLLSBe` | 未定（另一整数变体） |
| `JYlR8al2G1g7yXucJnaB.FIbl2Ce3f4N` | `h8diA3iOGmJ` | **bool** |
| `U7lOPGl2tdSf63xl7lBN.WYQl2BdTD7C` | `wNLiAK8Wcix` | **string** |
| `hIXACZl2JN2eXGWNjHMH.RxOl2nbqOVT` | `Q3yiAAj51IC` | 未定 |
| `nEbGKIl2SmxapJ6k2kUZ.kiql22ja1Pg` | `cbIiAiaXtaZ` | 未定 |
| `tsajCrl2yww3QE9Q1LbA.PlVl2efVioT` | `ekPiA7Fhp46` | 未定 |

另在 `DeleteEditObj` 调用点解析出 `YdqubEhqRh94bTsZgI9h.fWIhqNuB4sF` →
`gdQiAJcF6Eg`，其入参是实体模型，应为**实体/GUID 型参数构造器**。

⇒ 完整的命令调用形态（**静态读出，未执行**）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


---

## 六、证据等级与边界

| 结论 | 等级 |
|---|---|
| 存在具名命令派发通道，通式如上 | **静态**（IL 与反编译正文） |
| 23 条命令名与其通道常量的对应 | **静态** |
| `DoImport` 参数形状与构造方式 | **静态** |
| 命令的服务端语义、副作用、幂等性 | **未知** |
| 通道常量各自代表什么 | **未知**（只有名字，没有语义证据） |
| 能否从桥接实际发出并被游戏接受 | **未验证**——本轮未连接、未调用 |

**未做的事**：未启动/连接/操作编辑器与游戏；未调用任何命令；未修改 `GOAL.md`。

---

## 七、可复现命令


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）

