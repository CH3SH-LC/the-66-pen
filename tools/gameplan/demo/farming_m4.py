"""M4 demo — 让背包（689/685）真的进一次图。

背景（`docs/gameplan/README.md` 第五节 M4 行）：15 节点 demo 的节点序是
``[92,686,733,690,233,2,686,686,1,92,702,701,688,684,1]`` —— **689/685/721/722
一个都不在里面**。M4 只有离线合同校验，没有真机成图记录。这个图就是补上那一半：
一张**能被 ``build-plan`` 一次派发建出来、再独立读回**的 M4 图。

图从**一个** ``进入碰撞触发器时`` (92) 事件起，挂两条互相独立的腿
（放在同一张图里，是因为 92 的执行输出 ``then`` 可以扇出到任意多个后继——
和 :mod:`tools.gameplan.demo.farming_full` 的 ``plot_enter`` 扇出是同一手法）::

    进入碰撞触发器时 (92)
      │  then
      ├──────────────► 增加背包最大容量 (685)          # 腿二：直接扩容
      │                     └─ holder ← 进入者实体 ; delta ← grow_amount
      │
      └──► 双分支 (2) ──真(是)──► 打印字符串 (1) "背包快满了"   # 腿一
             ▲ 条件
             │
        数值小于 (230)                               # 容量 < 阈值 为真
             ▲ 左值                        ▲ 右值 = capacity_threshold
             │
        获取背包容量 (689) ── holder ← 进入者实体

腿一（容量门）组装 ``689 -> 230 -> 2 -> 真: 1``。判据是 ``容量 < threshold``
为真（这与 :func:`tools.gameplan.modules.inventory.capacity_gate` 默认 ``lt``
的语义一致：``inventory.py:82-84`` 把「容量 < 阈值」定义为"背包将满"的判据）。
**假(否)分支故意不接线**——容量够大时什么都不做，没有要打印的话。测试断言
``false_targets == []``，所以"少接一条线"这件事是被钉住的，不是忘了。

腿二（扩容）把 ``685`` **直接挂在同一个 92 的 ``then`` 上**，不经过任何分支——
任务要求的"separately 685 straight off the event"。

两条腿共享同一个 ``holder``：都是事件实体 ``enter.entrant`` (92 数据输出 ``4:0``)，
**没有一个是写死的常量**（``holder`` 只能来自运行期实体，不能是 const）。

这个图**不涉及任何模板 id**——和 M2/M3/M5 不同，685/689 只吃 ``holder`` 实体和
一个普通整数，不需要 ``货币配置ID`` / ``道具配置ID``，所以没有 configID 的
``--slot`` 未证问题（对比 ``paramtypes.CONFIG_ID_SLOT = None``）。

**721/722 仍然不进图**（诚实的缺口，不是待办）。它们（``获取背包所有基础道具``
/ ``获取背包所有货币``）输出的是**字典**（类型 ``27``）；取字典元素的原语**存在**——
``1158 以键查询字典值``（连同 ``1298``/``1368``/``1508`` 等）就在 500 条服务端定义里，
旧文案把构造与取元素节点判为「不存在」属**过度概括**（``DICT-WRITE-PROBE.md``，2026-10-10）——但
它从未上过真机。合同里确实有 10 个 dict 入参节点（297/704/706/707/708/709/710/720/725/828），
它们的字典**按名字区分 schema**——例如 ``704`` 要的是「出售货币字典」而 721/722 给的是
「基础道具字典 / 货币字典」，语义不同（``serverParamType`` 都是 27、``genericId``
都是 27，所以 ``plan.validate()`` *不会*替你拦住这种错配，正因如此更不能乱接）。
本 demo 只使用 689/685 —— 它们才是能真正"进图"的那两个。

真机那半边的机制见 ``docs/gameplan/REAL-MACHINE-RUNBOOK.md``：图的建立走**一次**
``build-plan`` 派发（逐节点路径必然超 5 分钟 scope 租约）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import BRANCH, PRINT, Graph
from ..plan import GraphPlan
from ..modules import interaction as m1
from ..modules import inventory as m4

DEFAULT_NAME = "MW_API_FARM_M4"

#: 容量门用的比较节点：``230`` 数值小于（`inventory.COMPARE_NODES["lt"]`）。
#: 语义：``容量 < threshold`` 为真 ⇒ 打印「背包快满了」。
COMPARE = "lt"

#: 真分支打印的那行文本。
WARN_TEXT = "背包快满了"


@dataclass(frozen=True)
class FarmM4Config:
    """M4 demo 的可调参数。全部是普通整数/字符串——不涉及任何模板 id。"""

    capacity_threshold: int = 20   # 容量 < 此值 ⇒ 打印 WARN_TEXT
    grow_amount: int = 10          # 每次进入给背包加的最大容量（685 delta）


def build(config: FarmM4Config, name: str = DEFAULT_NAME) -> Graph:
    """组装 M4 图。返回一个**未校验**的 :class:`Graph`（调用方负责 ``validate()``）。"""
    g = Graph(name)

    # --- 事件：进入碰撞触发器 -------------------------------------------------
    enter = m1.proximity_enter(g, "enter")                       # 92 进入碰撞触发器时

    # --- 腿一：容量门 689 -> 230 -> 2 -> 真: 打印「背包快满了」 ----------------
    # capacity_gate 放两个数据节点：689（别名 <alias>_cap）在前，230（别名 <alias>）在后，
    # 并把 689.capacity(4:0) 接到 230.左值(3:0)、threshold 写成 230.右值(3:1) 的 int 常量。
    gate = m4.capacity_gate(
        g,
        holder=(enter, "entrant"),          # holder 来自事件实体，绝不是常量
        threshold=config.capacity_threshold,
        alias="gate",
        compare=COMPARE,
    )                                       # -> 230（比较节点）；689 是它的 gate_cap 兄弟

    branch = g.place(BRANCH, "branch")      # 2 双分支
    enter.flow_to(branch)                   # 执行：92.then -> 2
    branch.data_from(gate, "result", "condition")   # 数据：230.结果 -> 2.条件

    warn = g.place(PRINT, "warn")           # 1 打印字符串
    branch.flow_to(warn, "true")            # 执行：2.是(0) -> 1
    warn.const("text", WARN_TEXT, "string")
    # 2.否(1) 故意不接线：容量够大时不做事（测试里断言 false_targets == []）。

    # --- 腿二：扩容 685 直接挂在同一个事件的 then 上 --------------------------
    m4.grow_then(
        g,
        enter,                              # 同一事件；92.then 扇出两条执行边
        holder=(enter, "entrant"),
        amount=config.grow_amount,
        alias="grow",
    )                                       # 685 增加背包最大容量

    return g


def build_plan(config: FarmM4Config, name: str = DEFAULT_NAME) -> GraphPlan:
    """组装并 ``validate()``，返回 :class:`GraphPlan`。

    任何一个节点/边/常量与 ``data/node-contracts`` 不符都会抛
    :class:`tools.gameplan.plan.PlanError` —— 在任何原生调用之前。
    """
    graph = build(config, name=name)
    graph.validate()
    return graph.plan


def main(argv=None) -> int:
    """把这张图跑一遍：默认干跑（打印它**会**发出的每条原生 argv），``--execute`` 才真发。

    这是 M4 的专用出入口；通用入口（含 ``farming`` / ``--full``）仍是
    :mod:`tools.gameplan.cli`。这里默认干跑、且 ``--execute`` 走 ``build_batch``
    （一次 ``build-plan`` 派发）——因为逐节点路径必然超 5 分钟的 scope 租约。
    """
    import argparse
    import json
    import sys
    from pathlib import Path

    from ..builder import GraphBuilder, simulated_runner, subprocess_runner

    parser = argparse.ArgumentParser(
        prog="farm-m4", description="M4 bag-capacity demo graph (689/230/2/1 + 685)"
    )
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--capacity-threshold", type=int,
                        default=FarmM4Config.capacity_threshold)
    parser.add_argument("--grow-amount", type=int, default=FarmM4Config.grow_amount)
    parser.add_argument("--run-id", default=None, help="live bridge run id (32 hex)")
    parser.add_argument("--entity-id", type=int, default=None, help="entity to bind to")
    parser.add_argument("--queue-dir", default=None)
    parser.add_argument("--python", default="python")
    parser.add_argument("--out", default=None, help="write the evidence JSON here")
    parser.add_argument("--execute", action="store_true",
                        help="actually dispatch (default: dry run)")
    parser.add_argument("--max-ops", type=int, default=None)
    args = parser.parse_args(argv)

    config = FarmM4Config(
        capacity_threshold=args.capacity_threshold, grow_amount=args.grow_amount
    )
    plan = build_plan(config, name=args.name)

    if not args.execute:
        builder = GraphBuilder(plan, simulated_runner(), run_id=args.run_id or "dry-run",
                               entity_id=args.entity_id, queue_dir=args.queue_dir)
        result = builder.build()
        calls = [{"step": s.summary()["step"], "argv": s.argv} for s in result.steps]
        print(json.dumps({
            "mode": "dry-run",
            "plan": plan.name,
            "nodes": len(plan.nodes), "edges": len(plan.edges), "consts": len(plan.consts),
            "calls": calls,
            "note": "no native call made; re-run with --execute and a live --run-id "
                    "(recommended: add --batch so the whole graph is one build-plan dispatch)",
        }, ensure_ascii=False, indent=2))
        return 0

    if not args.run_id:
        print("error: --execute requires --run-id (a live bridge scope)", file=sys.stderr)
        return 2
    builder = GraphBuilder(plan, subprocess_runner(args.python), run_id=args.run_id,
                           entity_id=args.entity_id, queue_dir=args.queue_dir,
                           python=args.python, max_ops=args.max_ops)
    result = builder.build_batch()
    evidence = result.evidence()
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if result.partial:
        return 3
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
