> 历史研究快照；以本发行版 catalog/interfaces.json 与 docs/BOUNDARIES.md 为当前入口。静态候选不代表已可调用。

# MANIFEST — `archive/` 移入记录

> 本目录存放**已被顶替（superseded）**或**中心结论被证伪（REFUTED）**的旧报告。
> **移动，不删除**：每份保留原文件名。本文件记录**每次移动**与**顶替它的是谁、依据是什么**。
> 由 2026-10-10 整合会话建立（只读整理：未连桥、未发报文、未触碰游戏/编辑器/存档）。
>
> 回链：`../INDEX.md` §五（REFUTED 与归档）。

| # | 移入文件 | 原位置 | 顶替者（在 `../`） | 为何顶替（判据，引顶替者自身） |
|---:|---|---|---|---|
| 1 | `GIA-EXPORT-MINE.md` | `../GIA-EXPORT-MINE.md` | `../GIA-TRUTH.md` | `GIA-TRUTH.md` §0 逐条 settle 其四问，并**明确判 §4「这些 `.gia` 里没有边编码」为 REFUTED**（§3：真实导出的边对 plan 命中 16/16+15/15）。**§1 另证伪其前提**「工程从未分析过 `.gia`」（自 2026-09-16 起即有解码器）。 |
| 2 | `BUILD-PLAN-LIMITS.md` | `../BUILD-PLAN-LIMITS.md` | `../BUILD-PLAN-CEILING.md`（辅：`../GRAPH-SIZE-LIMITS.md`） | `BUILD-PLAN-CEILING.md` §1 明说「**核实其行号并延伸**」#8，并用真机回执时间戳量出每派发成本；同题结论由 CEILING 与 GRAPH-SIZE-LIMITS 覆盖。 |
| 3 | `GRAPH-DELETE-PROBE.md` | `../GRAPH-DELETE-PROBE.md` | `../GRAPH-DELETE-FIX.md` | `GRAPH-DELETE-FIX.md` §0/§1「**本文据其证据推进并给判决**」：确认其根因（引用相等谓词），进一步给出统一查找修法及其不充分性。 |
| 4 | `GRAPH-RUNTIME-VERIFY-MINE.md` | `../GRAPH-RUNTIME-VERIFY-MINE.md` | `../GRAPH-LOG-NEXT-STEP.md` | `GRAPH-LOG-NEXT-STEP.md` §0/§1.2「**#3 把卡点的位置放偏了**」并逐条更正其 4 处口径；记录自带 proto-58 `graphId`（桥没读）＝真正卡点。 |
| 5 | `VISIBLE-NO-ASSET.md` | `../VISIBLE-NO-ASSET.md` | `../PLAYER-VISIBLE-VERDICT.md` | `PLAYER-VISIBLE-VERDICT.md` §0/§2 为「玩家可见」问题的**终审**（「汇总、独立复核、排一次名……**不再重开这个问题**」），重排了零资产三兄弟名次。 |
| 6 | `UI-HUD-FINAL.md` | `../UI-HUD-FINAL.md` | `../PLAYER-VISIBLE-VERDICT.md` | 同为「编辑器里有没有东西能写进去让玩家看见」这一问；`PLAYER-VISIBLE-VERDICT.md` §1 将 UHF 列为先行报告并汇总复核。 |
| 7 | `BRIDGE-CRASH-SAFETY.md` | `../BRIDGE-CRASH-SAFETY.md` | `../BUILD-INTERRUPT-HAZARD.md` | `BUILD-INTERRUPT-HAZARD.md` §0 明说「把『**中断安全**』这一条**收口**」，重述（三层标记 / 无回滚 / 半成品图）并延伸其结论。 |
| 8 | `GRAPH-VARIABLES-PROBE.md` | `../GRAPH-VARIABLES-PROBE.md` | `../GRAPH-VARIABLES-FINAL.md` | `GRAPH-VARIABLES-FINAL.md` §0 自述为 F1「**终判**」，「把前两者的『未知』再切一刀」（节点层未建 / 定义层阻塞）。 |
| 9 | `GRAPH-VARIABLES-VERDICT.md` | `../GRAPH-VARIABLES-VERDICT.md` | `../GRAPH-VARIABLES-FINAL.md` | 同上：FINAL 是其独立复核结论的终局。 |
| 10 | `SAVE-WRITE-ATTRIBUTION.md` | `../SAVE-WRITE-ATTRIBUTION.md` | `../SAVE-WRITER-FINAL.md` | `SAVE-WRITER-FINAL.md` §0 自述「**一次走完 live 存档、定死**」，结论与其一致并定案。 |
| 11 | `TAB-DIRECTORY-MINE.md` | `../TAB-DIRECTORY-MINE.md` | `../SAVE-WRITER-FINAL.md` | 同上：FINAL §2 对 root field 6 追加给出**可定案的归属证据**（无 id 条目早于本工程 save 能力）。 |

## 未移动、但已被更正的报告（仍留主目录；引用时须带更正）

以下报告的**中心结论未被推翻**，仅个别数字/预测被后续报告更正，故**不归档**，只在 `../INDEX.md` §5.1 标注：

- `COMPONENT-WRITER-MINE.md`（「47 项」→ 46，见 `../COLLISION-COMPONENT-ID.md` §1.2；回执预测形状见 `../COMPONENT-READ-VALUE.md` §1.1）
- `COMPONENT-OP-PROOF-PLAN.md`（旧标题句「删连编译都没进去」已过期）
- `WAVE-SPAWN-PATH.md`（更正工程记忆，非更正另一报告）
- `DICT-CONSTRUCT-SEARCH.md` / `DICT-WRITE-PROBE.md`（推翻 `CLAUDE.md:74` 的过度概括）

## 移动操作记录

- 2026-10-10（第一轮）：将 #1–#7 从 `docs/research/reverse-eng-20261010/` 移入本目录（纯 `mv`，未删除、未改写内容）。
- 2026-10-10（第二轮）：将 #8–#11 移入本目录（同一会话内，针对此后落地的 `GRAPH-VARIABLES-FINAL.md` / `SAVE-WRITER-FINAL.md` 两份终判）。
- 移动后：主目录 **62 份报告 + INDEX.md**；本目录 **11 份**（合计 **73 份报告**；同夜其它会话仍在新增报告，
  计数以 `ls` 实测为准，见 `../INDEX.md` 顶部「活环境」提示）。
