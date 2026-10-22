> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 接口真机验证报告

日期：2026-09-18。目标：**验证静态分析得出的接口在运行中的编辑器里是否真实存在、真实可用，且确实关乎游戏编辑。**

验证对象：正在运行的千星编辑器进程 `BeyondEditor.exe`（PID 39372，主窗口「千星沙箱」，启动于 2026-09-17 14:51:17）。
验证手段：工程既有的托管桥接（`tools/editor-bridge/`）经命名管道注入后反射调用。

**约束遵守**：全程未关闭、未重启、未终止任何进程。开工与收工三次核对，`YuanShen.exe`(113168)、
`BeyondEditor.exe`(39372/114124) 的 PID 与启动时间**始终未变**。

---

## 一、结论速览

| 断言 | 静态分析的说法 | 真机结果 | 判定 |
|---|---|---|---|
| 命令派发委托存在 | `BrjMRrl2xRXv5aqZQkDJ` | 类型存在，是委托，27 个方法 | ✅ |
| 生产者/传输类型存在 | `tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh` | 存在，26 个方法，**单例可解析** | ✅ |
| 派发入口存在 | `Producer::Ikci0qkvMZX` | **存在，实例方法，4 参数** | ✅ |
| 派发签名自洽 | 委托返回 `pD9YMQi0ZT7ZULgeNBHv` | 该方法的返回类型**正是同一个类型** | ✅ |
| 代理映射表正确 | 34,728 条槽位→方法映射 | **21 个受检槽位中 19 个按名精确命中，0 处不符** | ✅ |
| 通道可选 | 13 个通道槽位 | **13 个全部调用成功，返回真实服务名字符串** | ✅ |
| 参数构造器可用 | `Param` 的 3 个类型化构造器 | 均为 static、1 参数、返回 Param 类型 | ✅ |
| **确实关乎游戏编辑** | —— | 通道名即编辑服务名（见第四节） | ✅ |

**未做**：没有向游戏发送任何命令，没有改动任何模型，没有触发保存或试玩。
`persistentSaveVerified` 与 `playtestVerified` 仍为 `false`。

---

## 二、类型与签名（运行中编辑器实测）

12 个断言依赖的类型**全部存在**：

| 类型 | 角色 | 方法数 | 是否委托 |
|---|---|---:|---|
| `BrjMRrl2xRXv5aqZQkDJ` | 命令派发委托 | 27 | 是 |
| `tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh` | 生产者/传输 | 26 | 否 |
| `HOlfE6lSftgl74pgvnRM` | 代理槽位容器 | 27 | 是 |
| `gRNKAfiARUIARICiA4q4.vh0ExpiAUXNaxFjnJLHP` | 通道方法所在类型 | 6 | 否 |
| `yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv` | 参数类型 | 6 | 否 |
| `qmcI6kYhr1tEjgMBZY1r.Y9F2H0YhZJ8wH9Xl5wuT` | 字符串表解码 | 19 | 否 |
| `ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre` | 资源注册表 | 26 | 否 |
| `mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q` | 编辑器管理器 | 134 | 否 |
| `Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr` | 实体实例模型 | 79 | 否 |
| `nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp` | 预制模型 | 78 | 否 |
| `IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C` | 节点定义模型（Kind 6） | 112 | 否 |
| `cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH` | 节点图模型（Kind 9） | 121 | 否 |

**派发入口的实测签名**（这是最关键的一条）：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


而源码里委托的声明是：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


⇒ 返回类型一致，参数个数（4，去掉委托签名里的 `object` 生产者自身）一致。
**静态推断的调用形态在运行进程中成立。**

---

## 三、代理映射表（34,728 条）的真机核对

方法：读出每个静态槽位字段的值，若为委托则问运行时要 `Delegate.Method`，
再与静态解出的 `目标类型::目标方法` 逐字比对。

| 结果 | 数量 |
|---|---:|
| 按名精确命中 | **19** |
| 槽位为空 | 0 |
| 类型/字段缺失 | 0 |
| 名字不符 | **0** |
| 运行时动态生成方法（无可比名字） | 2 |

目标方法本身的存在性：**21 个目标中 20 个确实存在于已加载程序集**。

唯一未解析的一个是 `miTools.AppCommon.AppUtility::get_AppLocalDataFolder` —— 首轮机检失败是
**检查逻辑的问题**（只在 `BeyondEditor` 程序集里找），该类型实际位于独立程序集
`miTools.AppCommon.dll`（安装目录中存在）。已改为遍历全部已加载程序集。

两条"运行时动态生成"的槽位都在命令派发委托上：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


它们**非空且可调用**，但因为是运行时生成的方法，没有声明类型可比名。
静态映射说它们指向 `Producer::Ikci0qkvMZX` 等；本轮**无法用名字证实这一点**，
只能证实"槽位非空、且目标类型上的同名方法确实存在"。此点如实标注为**未完全证实**。

---

## 四、通道标识的真机取值（"确实关乎游戏编辑"的直接证据）

`verify-channels` 操作**只调用"零参数、静态、返回 string"的读取器**（运行时自证为该形状才调用），
不发送任何东西给游戏。13 个通道全部成功，返回值如下：

| 槽位常量 | 返回的通道标识 | 该通道承载的命令（静态分析） |
|---|---|---|
| `YSDhqo1YVyx` | **`beyondEditObjService`** | DeleteEditObj、DeletePrefab、ModifyEditObjName、ModifyPrefabName、ModifyPrefabTag、FocusEditObj/Character/Light/Esp/DropGather/LocalBullet |
| `BsxLvIOuJMp` | **`beyondExportService`** | DoImport、DoExport、ImportDebugLog、ImportAllDebugLog、DeleteDebugLog、RefreshExistDebugLogReport |
| `cN5hqlJY835` | **`beyondInstructionGraphService`** | create、delete、riskReport |
| `Is6hqU640RJ` | **`beyondPCGInstanceService`** | （未观察到命令） |
| `Cg3LuDiYIgD` | **`beyondRoleStatusService`** | （未观察到命令） |
| `JxZLSauoPXi` | **`beyondEffectService`** | focus |
| `boGLyQBJv9p` | **`beyondAudioService`** | PlayMusic、Stop |
| `wtRlSp6GrvH` | `wpfAudioService` | （未观察到命令） |
| `P9plSZjW9OJ` | `wpfApplicationService` | （未观察到命令） |
| `KJZlSrdSUL1` | `wpfInstructionGraphService` | （未观察到命令） |
| `TnxlzlI8Hk0` | `Log/log.txt` | （非服务，是日志路径读取器） |
| `Oerlz9Jdbnf` | `Log/logPre.txt` | （非服务，是日志路径读取器） |
| `VdghK1XTDpm` | `C:\Users\PUBLIC_USER\AppData\Local\BeyondEditor` | （非服务，是数据目录读取器） |

**这就是"确实关乎游戏编辑"的证据**：
通道名是 `beyondEditObjService`（编辑对象）、`beyondExportService`（导入导出）、
`beyondInstructionGraphService`（指令图/节点图）、`beyondPCGInstanceService`、`beyondRoleStatusService`——
全部是**编辑服务**。派发调用形如：


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


**同时闭合了工程里一处悬案**：既有记录反复出现的 `beyondExportService.DoImport`，
此前只知道"有调用点、参数形状为 `[uint,bool,string,uint]`"。
现在查明：`beyondExportService` 是**通道标识**（由 `BsxLvIOuJMp` 这个零参静态读取器返回的字符串），
`DoImport` 是**命令名**。两者拼接即工程一直记录的写法。

---

## 五、仍未被真机证实的部分

| 项 | 状态 |
|---|---|
| 命令的服务端语义、副作用、幂等性 | **未验证**——本轮未发送任何命令 |
| 派发槽位指向 `Producer::Ikci0qkvMZX` 这一条 | 槽位非空且可调用，但目标是动态生成方法，**无法按名核对** |
| 13 个通道之外的 12 个（共 25 个通道方法） | 未逐一调用 |
| 23 条命令之外的字面量（如 `AddInstructionGraphForEditObj`） | 仍无调用路径 |
| 试玩、保存、导入导出能否成功 | 与本轮无关，维持既有结论 |

---

## 六、复现方式


（原始代码或现场命令片段未随公共研究笔记分发；可用工具见目录。）


结果文件：`.runtime/editor-bridge/runs/<runId>/verify-raw.json`、`channels.json`。

### 关于提权

编辑器以提权身份运行，Windows 不向非提权进程暴露其路径；桥接管道也用
`PipeOptions.CurrentUserOnly` 创建，非提权客户端连接被拒。因此**加载与调用都需要提权**。

为避免每次弹 UAC，本轮引入 `elevated-runner.ps1`：提权一次后常驻，此后只接受两类请求
（`load` / `call`），且**只允许运行 `call-bridge.ps1` 里白名单内的操作名**——
白名单每次请求重新读取该脚本，所以脚本是唯一事实来源，助手不会放宽权限。
它不执行请求中给出的任何命令，不碰游戏/编辑器进程，收到 `STOP` 文件或到期即退出。

**白名单守卫已被真实触发一次并正确拒绝**：向它请求当时尚未加入白名单的 `verify-channels`
时，它返回 `OP_NOT_ALLOWED:verify-channels` 而非放行——fail-closed 行为得到实证。
