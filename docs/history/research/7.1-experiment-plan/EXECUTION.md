> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# 全接口实验执行记录

## 2026-09-27 02:18 并行整合与调度列表真实只读验收

三个Codex子智能体并行负责实现、静态合同和独立复核，主助手执行实机并对账。新增可选`--scheduler-coroutines`（必须同时`--lifecycle-type`），回执v6与旧ABI兼容；源码/profile/decoder及helper pin完整绑定。首读因把预留容量也限制为128而拒绝；第二次失败诊断读取count=3/capacity=1600。依据已核原生List追加语义，修正为最多128个有效条目、只双读有效前缀，不读闲置尾部，不扩大遍历上限。两个拒绝及修改前原件保留。

第三次新鲜实读通过：3条有效记录、capacity1600、version104634前后相等；两条released holder、一条other_class，target0；16270字节/154次读取。完整逻辑列表可读，但释放项不能用于认领旧任务正常完成，也不声称全引擎无任务或关卡已重开。14个完整原生实体记录与旧/新inspect完全一致，15关目录与生命周期类型仍通过。

全账户38文件/1,254,877字节已备份并逐文件核验保持；其中15关卡文件包含10份平铺旧布局与5份嵌套新布局，此前“五文件”仅是嵌套布局，不表示其余缺失。新helper19732/1842指纹已通过真实旧inspect，旧38032和全部本轮一次性包装器正常退出；截止05:13:07，未延长。游戏47028、编辑器9340及64150→57088连接保持，GOAL未改。88项Python、41项C++与新旧构建/ABI验证通过；主助手26项组合核验通过。

重开前置guard离线草稿及独立复核已完成（52项C++/12项Python），尚未整合或实读；动作必须区分同步返回、hook清理与异步业务完成，不沿用保存动作的立即清锁。P02仍待1839真实加载及完整实体/图/绑定/正式文件对账；新建/另存/通用undo等留各自未验，不增加为本次重开的先决接口。下一步整合并实读guard，再实现单次重开。当前桥R187已关闭，下次使用R188或更高。

最新额度94%，本轮按当前目标的60%停止线执行；AGENT持久化修改此前被自动审批拒绝、仍待确认，未修改规范文件。详见实测结果（历史来源：`../../../.runtime/verification/interface-experiments-20260927/p02/scheduler-observation/RESULT.md`）、26项核验（历史来源：`../../../.runtime/verification/interface-experiments-20260927/p02/scheduler-observation/verification.json`）、下一步guard草稿（历史来源：`../../../.runtime/verification/interface-experiments-20260927/p02/reopen-preflight/parallel-guards/REPORT.md`）。

## 2026-09-27 01:39 R187真实回调验收通过，日志业务失败单列

R187已部署。新增被动1022初始化观察：实际收包递增序号/单调时间、16事件上限、精确类型字段、缓存强引用、内置接收器顺序与自有清理前后保持；25项真实WPF Dispatcher/DispatchProxy隔离测试通过。现场在原接收器之后登记1个自有观察器，当前缓存1839；只发一次已核对的ImportAllDebugLog读取RPC，收到1019且requestId17精确匹配1次。44个回调、callbackErrors/contractRejected均0，确认旧回调名修复在7.1实机有效。**debugLogRpcSuccess=false，日志业务未通过；没有1022事件、缓存引用保持，不声称重开。**

观察器从原列表和deferred仅移除自身，非自有顺序/集合保持；桥53509573于01:36:01自然到期，cleanupSucceeded=true。原生完整14实体记录、编辑器28实体行/14唯一ID与9图行/3唯一图、五正式存档、进程身份及64150→57088连接保持；22项独立核验通过。R187构建0错误、27项MSB3061警告来自旧桥DLL被现有编辑器锁定，未强行删除或终止编辑器；Bootstrap 0警告0错误。

helper38032/1838项指纹已通过新鲜inspect，旧55764正常退出，新截止05:14:20早于旧05:15:22。当前桥R187已关闭，下次须R188或更高。最新额度观测99%；工程规范修改仍等待明确确认，未改AGENT/GOAL。证据：结果（历史来源：`../../../.runtime/verification/interface-experiments-20260927/p02/fresh-init-observer/RESULT.md`）、独立核验（历史来源：`../../../.runtime/verification/interface-experiments-20260927/p02/fresh-init-observer/verification.json`）。

下一步：只读scheduler→handle→holder→iterator阶段观察及一次性重开合同正在独立草稿/交叉审查；尚未采纳或实测。P02按原计划需要业务实际重新加载及完整一致性，不额外要求内部UI协程形式终态；但须排除入口早退/仅通知，1022不能单独作加载后屏障。全部接口目标继续。

下方额度与会话说明均属对应历史轮记录，不能代替当前用户目标和新鲜查询。

## 2026-09-27 01:17 类型真实读回与观察器修复（01:25据原始证据补录）

三个Codex子智能体完成独立静态/实现/观察器复核，由主助手整合与实测。候选class槽5826620已初始化，9个函数槽中索引6唯一指向9037840；前后代码、11个hotfix门槛、类型表保持，8478字节/56次读取。同期15关卡目录、14实体与另一轮旧inspect一致。未调用加载或业务写入；23项组合核验通过，五正式存档、GOAL、游戏/编辑器身份和64150→57088连接保持。

已修复NativePacketObserverProxy硬编码7.0回调名导致7.1回调被静默丢弃的问题：传入已验证MethodInfo并报告调用/拒绝计数。旧问题在真实DispatchProxy隔离复现，修复12项测试及完整生产目标构建通过；尚未部署到编辑器。50项Python、11项C++、旧写ABI v3/67560字节和新旧只读构建通过。实读后更正后段语义为不透明trailingWords，未验证MethodInfo，原回执不改。失败原件与更正原因均保留。

helper55764/1838项指纹已通过真实inspect，旧34716正常退出；截止05:15:22早于旧05:17:12，未延长授权。编辑器桥R186已关闭，下次需R187或更高。P02重开仍未验收；1022初始化通知、state=-1、列表增长均不独立证明终结。结果与边界（历史来源：`../../../.runtime/verification/interface-experiments-20260927/p02/level-lifecycle/RESULT.md`）、23项核验（历史来源：`../../../.runtime/verification/interface-experiments-20260927/p02/level-lifecycle/verification.json`）。

最新：进程内原生关卡目录读取通过，15唯一记录，当前/选中1839且未保存标记0；旧inspect真实回归通过。P02新建/打开/另存/重开仍待验，下方旧失败记录保留。

更新：2026-09-27。全接口目标仍在进行中，本页不代表全部完成。用户已明确允许提权与真实实验；剩余适用Codex订阅额度低于10%停止。最近查询剩余57%。当前助手执行，未调用CC。

## 已完成的真实进展

- 标准UAC建立8小时受限helper，核验elevated=true、身份、期限及源指纹。只替换本次自有helper，未关闭/重启游戏或编辑器。
- P00建立1726条来源记录：56规划组、810节点资源、51命令候选、92操作、49模板、395控件、80功能、49通道、44前端操作、62快捷键、10服务路由、24消息路由、4个实际节点分类。仍需逐条归并为业务接口与实验合同；1726不是API总数。
- P01真实编辑器目录与独立原生只读观察对账：当前关卡1073741839，完整14实体ID一致；原生called=0、mutationAttempted=false、cleanupVerified=true。
- 新增 `node-definition-variants`，保留category/id，拒绝身份冲突，支持1..64 ID及最多256变体；旧服务器 `node-definitions` 行为保留。
- 分13批真实查询810个节点ID，得到929个分类变体：服务器500，客户端分类20001有122、20002有197、20007有110。不能将变体数量误报为新增节点数。
- 全量核验发现5个102端口变体被旧64上限截断；新查询改为每定义最多256端口，R178复测169、1788、200152、200228四ID对应5变体成功，前64端口与原件一致。合并快照全部929变体无截断，名称与资源完全一致。
- 303输入8、304/305输出7、200252输出2四项7.1参数变化真实读回；零基端口序号不是任意协议参数序号。节点执行/类型语义仍需后续实验。
- 只读目录/两类节点查询等待60秒；其他操作保持10秒。真实首次超时原件保留，确认桥已结束后才开展修复验证，无自动重试。
- 17项Python客户端测试、55项PS5参数校验、10项实际离线命名管道检查通过；R176/R177/R178构建成功。R177/R178旧7定义返回与修复前成功回执完全一致。
- 4个本次自有桥范围均有lease-closed清理成功；正式目标和旧三库保持。

## P02真实创建/保存与同步故障

当前R179。helper19056已通过标准UAC重新建立，8小时期限至2026-09-27 05:19（本地时间）；此时间不代替下次身份/期限/源指纹检查。游戏47028、编辑器9340保留。

| 项目 | 实际结果 |
|---|---|
| 新鲜原生基线与单次create审阅 | 关卡1073741839，14实体；恢复副本及唯一审阅已存档 |
| 原生创建 | called=1，actionStatus=0，cleanupVerified=true；仅新增1077936132，14→15 |
| 编辑器CRUD start | 失败：探针无新增实体，仍14；保留failed/uncertain原件，后续五阶段未执行 |
| 场景资源目录打开/模型读取 | 调用成功，但目录仍旧14，不能算同步成功 |
| 独立原生保存 | 重新取得15实体基线、唯一save审阅后called=1/nativeStatus=0/cleanupVerified=true |
| 正式文件独立核验 | 14→15仅新增6132；模板、中文名称、位置旋转缩放准确；旧实体、旧目录和图字节保持；四旁观存档保持 |
| 恢复与重开 | R182已完成6132清理并保存；重开未验收 |
| 自有桥清理 | fe5da49c-2aaf-4a45-9627-7310dd455e82的lease-closed确认cleanupSucceeded=true |

保存后的目标SHA为`2fedfd8b30bca0cc0203799ad56c9b356114622716a7ad127056dfb087b5be3b`。磁盘差分检查只证明文件内容；原生身份/回调及快照来源由相应原生回执单独支撑，不将文件检查中的false范围标记改成true。

两次仅本机TCP观察均未发现编辑器9340与游戏47028的对应双向连接；编辑器有59214→59214自连接。当前7.1传输类`Wip0uQLbGqaQ1IuhHxns`中初始化只设布尔值、登记发送回调并清空回调字典，不能证明实际连接。尚未定位自连接形成原因，不将TCP缺失推广为所有传输均断开。

新增`connection-evidence.py`将OS连接证据与协议握手、关卡状态明确分开；7项测试通过。它只读取已有快照，不连接/修复任何进程；未擅自断开已有IPC。

## 未完成与下一步

1. 继续只读追踪底层传输，确认保留现有会话的同步恢复路径。不能用初始化标记或历史相同实体数放行跨端写入。
2. 当前正式测试关恢复14实体，本轮6132已清理保存。需建立新的六阶段实验及重开验收；失败CRUD与历史review/claim不得重放。
3. P02完整CRUD与恢复尚未验收。独立创建/保存成功不覆盖六阶段失败，不等于重开、试玩成功。
4. 将真实schema接入后续逐节点实验卡，核验类型/枚举/泛型和编辑合同，再做节点运行行为；929定义读回不是运行功能通过。
5. P00官方目录刷新、源集合归并、完整服务/消息合同及其余阶段仍待完成；整体目标不缩减为本次成果。当前版本/进程/指纹/额度每次重新核验。

## 证据入口

- 本轮完整证据（历史来源：`../../../.runtime/verification/interface-experiments-20260926/`）
- 来源台账汇总（历史来源：`../../../.runtime/verification/interface-experiments-20260926/source-registry-summary.json`）
- 全量节点独立核验（历史来源：`../../../.runtime/verification/interface-experiments-20260926/all-nodes-verification.json`）
- 真实节点schema（历史来源：`../../../.runtime/verification/interface-experiments-20260926/live-node-schema.json`）
- 14实体及变化端口核验（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p01-independent-verification.json`）
- 正式文件基线核验（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02-readonly-baseline/verification.json`）
- 总计划（历史来源：`README.md`）

- P02严格文件差分（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/save-created-independent.json`）
- P02创建后保存回执（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/save-created.json`）
- P02六阶段失败原件（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/start.json`）
- 连接分类证据（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/connection-classification.json`）

## 2026-09-26 P02同步故障：真实业务Socket确认自连接

R180新增`Adapter/TransportEvidence.cs`并接入catalog：仅沿7.1已核实的producer→connection→client→Socket字段读取，不调用连接、关闭、发送或接收。实际编辑器9340读回observed=true、connectedFlag=true、localPort=remotePort=59214、selfConnection=true，实体仍14。当前游戏监听/注册表port_h2088097884均为57088。已证实异常属于业务Socket，不能再将Connected或transportInitialized当成功连接依据；自连接形成原因尚未证实。

源码确认工厂默认端口0，Connect从HKCU Software/miHoYo/BeyondAssistEditor读取哈希化port键，通过Socket.BeginConnect/EndConnect连接。底层关闭方法会清空回调，不能直接关闭后对同一对象调用Connect充当恢复；需先完成生产者官方生命周期/握手追踪。既有IPC禁止断开/接管规则仍有效，尚未重连或修改注册表。实体6132仍在正式测试关待清理。

R180最终构建成功（首次遗漏编译项已补齐，未加载失败构建；旧已加载DLL锁定警告未通过关闭编辑器处理）。真实catalog读取成功、中文源码保持、独立诊断范围913c7f7e的lease-closed清理通过。额度剩余62%，helper19056及游戏/编辑器仍存活。后续native写入须重新核对helper pin；不可据helper存活认定新版本指纹有效。

证据：`.runtime/verification/interface-experiments-20260926/p02/transport-trace/`，重点`catalog-r180.json`、`verification.json`和当前7.1源码。下一步追踪生产者重建回调/握手路径并形成可审核恢复步骤；保持其余只读接口探索，不重放失败CRUD。

R180实机独立核验（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/transport-trace/verification.json`）

## 2026-09-26 22:20 P02连接恢复实测通过，继续清理与接口实验

用户明确允许仅修复编辑器9340的异常自连接。R181固定进程创建身份、旧59214自连接、注册表57088、25分钟期限及不可重放claim；预检pendingRpc=0、pendingReceiverRemovals=0、receiverCount=1，保留原null回调与300000失败计数阈值。按官方producer关闭/初始化序列仅执行一次，未重启进程或改注册表/存档。

恢复后真实Socket64150→57088，OS确认编辑器9340与游戏47028互反Established；编辑器完整15唯一ID与新鲜原生基线完全一致，6132出现，旧14实体目录记录及三图目录内容保持。五正式文件及一份UpgradeBackup哈希保持（备份用manifest-unique.json，避免同名冲突）。未直接抓握手帧，不据源码把握手包捕获写成通过。scope f0fba86c租期清理通过，新游戏连接保留。

run_live_crud_acceptance.py新增创建前连接检查，缺失诊断/未连接/自连接在原生创建前拒绝；32项六阶段隔离回归通过，真实修复前回执拒绝、修复后回执通过。此检查不等于协议握手证明。修复前失败CRUD仍不可重放。测试实体6132尚未删除、重开与完整CRUD尚未完成。

下一步为6132建立基于本次创建证据的新鲜受限清理流程，删除/保存/严格差分后继续计划；native操作前重新核对源pin与helper状态，不把存活当兼容。当前R181，额度62%，停止线<10%。证据恢复独立验收（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/transport-trace/recovery-verification.json`）。


## 2026-09-26 22:33 P02自有实体清理/保存严格验收通过

R182新增独立OwnedEntityRecovery：固定本轮6132创建回执SHA、15实体集合、目标模板/身份/名称、当前存档SHA及进程创建身份，180秒观察期与不可重放删除claim；没有复活过期CRUD探针或放宽通用删除。真实删除原生菜单路径返回true，编辑器和完整原生读回均14实体且仅移除6132。新鲜单次审阅后原生保存called=1/actionStatus=0/cleanupVerified=true；四旁观存档未变。

三份正式快照严格核对14→15→14通过：旧实体结构、节点图保持，root5只移除目标原始记录，目录目标ID消失。最终SHA为91b6dd078713a87feafda66102fc67bcd5ebd9aaf62075678194e2e81c4e3276。复用了三快照验证器，输出renamedName字段仅表示中间实体名称，本轮未改名；不得将该工具成功报告为完整六阶段CRUD。scope e464810e正常到期，lease-closed确认清理成功；保留新游戏连接和所有失败/恢复证据。

**测试实体已清理并持久保存，不再是残留项。** 尚需新运行完成改名/保存/删除六阶段及重开验证，再按P03之后计划推进全部接口。历史失败运行、删除claim和review禁止重放，即使后续游戏复用6132也不赋予旧清理入口新权限。当前R182，额度最新已知62%，停止线<10%。见清理验收（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/cleanup/verification.json`）。


## 2026-09-26 22:50 R183完整实体CRUD及保存实测通过

新对象1077936133完成创建→改名MW_CRUD_Probe→原生保存→删除→原生再保存→严格差分，六个phase结果均ok=true/outcomeUncertain=false且历史hash绑定有效。14→15→14；目标配置、中文原名/新名、位置旋转缩放、旧实体原始记录、旧图字节、删除单记录差分和目录目标ID消失分别通过。最终正式SHA为dfb0c97f1b5df6b654baae2e7cbf674ed1c59d3d2b3156138fa5c2fc11dbd89e，四旁观存档保持，无本轮实体残留。

中断时save-deleted在claim前因180秒探针过期拒绝，未写入。真实调用已完成删除，但原流程错误要求末次保存/离线验证继续访问已删除目标的过期探针。修正终结阶段：仍核历史完整绑定/进程/queue；必须确认delete成功及目标缺失，新审阅/完整原生基线必须在delete之后，完整ID集合严格等于原始基线。只对已确认删除后的保存与快照核验不要求活跃探针；改名/删除及save-renamed仍按原租期拒绝。没有延长期限、重启桥、重放删除或复用旧review。34项隔离回归通过，之后取得中断后新鲜14实体基线，使用新review首次执行末次保存。原拒绝回执保留。

桥d4b55e32早已正常到期，lease-closed确认cleanupSucceeded=true；verify尝试清理前检查到关闭而未发送stop，游戏和新连接保持。读取三份正式快照的验证器不独立证明动作来源，真实执行由各phase及原生回执分别支撑。

下一步P02重新加载/重开、专用关卡选择/另存等尚未完成；完整接口目标不等于本次CRUD完成。继续按计划先确认可恢复的加载合同，再扩大P03/P04。当前桥R183，额度61%，停止线<10%，当前助手执行且不调用CC。证据独立验收（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/full-crud-r183/verification.json`）。


## 2026-09-26 23:26 R184/R185只读关卡身份与模板实验通过，P02重开仍待验

初始化缓存中的关卡1073741839与新鲜原生只读基线一致，完整14实体ID、3图33节点，无本轮临时实体残留。新增`Adapter/LevelLifecycleEvidence.cs`仅按精确类型/字段读取，明确缓存不能证明加载发生。已排除蓝图SaveAs、入站OnLevelInit和资源目录刷新作为关卡重开入口；游戏侧主动新建/打开/另存合同仍未建立。

真实模板目录返回2722唯一记录和图标路径；11模板各读到16标量，但全都触及深度/集合上限。修复`SceneCatalog.cs`只报行数截断的问题，R185如实标为truncated=true并返回深度3/集合4/行90及读错误数；修复前后标量行一致。不能报告为完整模型、几何或碰撞通过。两个模板查询首次10秒超时；保留回执，仅这两个只读操作改为60秒等待，真实重查成功。12项离线管道回归与100操作期限选择核对通过，写操作仍10秒，无自动重试。

独立19项验收通过；5正式存档哈希、GOAL、游戏/编辑器创建身份和64150→57088原连接保持。R184/R185两个自有桥清理均通过，当前R185；额度59%，停止线<10%，当前助手执行未调用CC。证据本轮验收（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/reopen-audit/verification.json`）与调查记录（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/reopen-audit/RESULT.md`）。

下一步继续游戏侧加载合同；P02重开通过前不扩大写入，可继续独立只读实验。完整接口目标仍在进行中。


## 2026-09-27 00:07 R186加载链调查：外部关卡目录读取失败，重开待验

已完成固定只读查询及一次性正常UAC复测。R186外层catalog正常，28注册行/14唯一实体和3图目录保持；nativeLevels失败。普通/管理员独立查询均在main-module阶段返回Windows错误码5，未取得关卡目录。辅助程序53804已退出，常驻helper19056保持原05:19截止期限；R186自有桥清理通过，下次须R187或更高，不能重载R186。

7.1静态链已区分ID选择、目录元数据持久化、异步初始化和主要/后备读取。更正初步判断：0x135665f0回调可为空，回调返回不证明异步完成。0x9037840的8状态跳转表已分离核验，状态3调用初始化函数；分配类型绑定及加载终态仍待证实，未调用候选加载RVA。

失败实验已从日常catalog和Bridge编译项移除，独立诊断保留；隔离构建0警告/0错误，12解析测试和18项证据/保持检查通过。初次核验误把唯一实体数当原始行数，保留失败并在完整28行相等前提下修正。5正式存档、GOAL、进程创建身份及64150→57088连接保持；这些检查不是level.list或重开通过。额度58%，当前助手执行未调用CC。

证据：本轮结果（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/reload-native/RESULT.md`）、核验（历史来源：`../../../.runtime/verification/interface-experiments-20260926/p02/reload-native/verification.json`）。下一步在已验证进程内只读快照通道补目录，再完成加载合同；P02重开门槛不放宽，全接口目标继续。


## 2026-09-27 00:31 P02原生关卡目录真实读取通过，重开继续调查

在已有进程内只读快照通道新增目录扩展，实际返回15唯一关卡记录（1825–1839），当前/选中关卡1073741839，save-manager未保存标记0。17容量、15占用、版本前后15；目录扩展3262字节/92次，根对象/数组/记录/hotfix复核通过。当前账号标准路径只有1835–1839五个正式GIL存在；其余10条目录记录不等于可打开，不推断其它位置没有副本。

新目录和独立旧入口inspect均完整读到14实体，回调一次、正常卸载、无业务写入。17 C++解析、11目录解码、10原配置、13审核测试及旧写回执ABI检查通过；21项独立核验通过。五存档、GOAL、游戏/编辑器身份及64150→57088连接保持。目录读取已通过；新建/打开/另存/重开未通过，全部接口目标仍在进行中。

自有helper已刷新为34716/1834项指纹，新helper真实inspect通过后才正常停止旧19056并切换指针；截止时间05:17:12，早于原05:19:04。新队列尾名elevated-interfaces-catalog-cdf8b598579a4a26adb1780d91c82550。编辑器桥仍停在已清理的R186，下次须新版本，不重复加载。当前助手执行，未调用CC，额度57%。

证据：结果与后续（历史来源：`../../../.runtime/verification/interface-experiments-20260927/p02/native-catalog/RESULT.md`）、独立核验（历史来源：`../../../.runtime/verification/interface-experiments-20260927/p02/native-catalog/verification.json`）。下一步补协程类型绑定、异步终态与连接保持合同，再开展一次性重开；不复用已过期指针/探针作为写入凭证。

