"""An exhaustive-ish type/direction matrix over :meth:`GraphPlan.validate`.

Data-driven, not hand-written: the cases are generated from the committed
server contracts (``data/node-contracts/variants/server/*.json``) rather than
enumerated by hand, so the matrix grows with the store.

Scope of the sweep
------------------
The store holds 500 server definitions, 217 of which declare *both* a data
input and an execution output.  For every such definition the matrix asserts:

* a data edge from a matching-type concrete output "elsewhere" is accepted;
* a data edge from a concrete output of a *different* type is rejected with
  ``"data type mismatch"``;
* a data edge into a generic (``serverParamType == 0``) target pin is accepted
  from any concrete source;
* an execution edge leaves a valid output index (0/1) into a target index 0,
  and output index 2 is rejected;
* a second :class:`ConstSpec` on the same ``(alias, port_index)`` is rejected
  with ``"set twice"``.

Bounding / sampling
-------------------
The store is small enough to sweep *fully*: every qualifying definition and
every one of its pins is exercised (217 definitions; 663 data-input pins for
the data-edge and const checks; every exec-output pin for the exec checks).  The
only unbounded dimension is the cross-product "generic target pin x concrete
source type", so that sweep alone is capped at :data:`GENERIC_SOURCE_SAMPLE`
source types per generic pin, chosen by an even stride over the sorted type
list.  The stride is fully deterministic -- no RNG, no shuffling -- so the
sampled set is identical on every run and every machine.

This module only reads; it never loads or mutates a plan via the bridge.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.gameplan.contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    EXEC_INPUT,
    EXEC_OUTPUT,
    ContractStore,
    default_store,
)
from tools.gameplan.plan import GraphPlan, PlanError

STORE: ContractStore = default_store()

#: Max concrete source *types* tried against each generic target pin.
GENERIC_SOURCE_SAMPLE = 6

#: The literal plan name the matrix uses; must satisfy GRAPH_NAME_RE.
_PLAN_NAME = "MW_API_matrix"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVER_CONTRACT_DIR = _REPO_ROOT / "data" / "node-contracts" / "variants" / "server"

# The pin-kind constants contracts.py documents as *wireable* (contracts.py:22-27).
_WIREABLE_KINDS = (EXEC_INPUT, EXEC_OUTPUT, DATA_INPUT, DATA_OUTPUT)
# Kind 5 is the observed-but-unnamed "未定-106" pin (contracts.py:22-23); it is
# deliberately *not* wireable and is not addressable by plan.py.
_UNNAMED_KIND = 5


def _problems(plan: GraphPlan) -> list[str]:
    """Validate ``plan`` and return its problem list (empty == accepted)."""
    try:
        plan.validate(STORE)
    except PlanError as exc:
        return list(exc.problems)
    return []


def _two_node_plan(
    src_def: int, dst_def: int, *edges
) -> GraphPlan:
    plan = GraphPlan(name=_PLAN_NAME)
    plan.add("src", src_def)
    plan.add("dst", dst_def)
    for src_kind, src_index, dst_kind, dst_index in edges:
        plan.wire("src", src_kind, src_index, "dst", dst_kind, dst_index)
    return plan


class _Index:
    """Pre-computed lookups so the sweep stays O(pins), not O(pins x store)."""

    def __init__(self, store: ContractStore):
        self.store = store
        self.qualifying: list[int] = []
        self.outputs_by_type: dict[int, list[tuple[int, int]]] = {}
        self.defs_with_exec_out: set[int] = set()
        self.sink_def: int | None = None  # a definition with an exec input 0

        for did in store.definition_ids():
            definition = store.require(did)
            has_data_in = False
            has_exec_out = False
            for port in definition.ports:
                if port.kind == DATA_OUTPUT and not port.is_generic:
                    self.outputs_by_type.setdefault(port.server_param_type, []).append(
                        (did, port.index)
                    )
                elif port.kind == DATA_INPUT:
                    has_data_in = True
                elif port.kind == EXEC_OUTPUT:
                    has_exec_out = True
                    self.defs_with_exec_out.add(did)
                elif port.kind == EXEC_INPUT and port.index == 0:
                    if self.sink_def is None or did < self.sink_def:
                        self.sink_def = did
            if has_data_in and has_exec_out:
                self.qualifying.append(did)

    def pick_source(
        self, want_type: int, exclude_def: int
    ) -> tuple[int, int] | None:
        """A concrete output pin of ``want_type``, preferring another node."""
        options = self.outputs_by_type.get(want_type)
        if not options:
            return None
        for did, index in options:
            if did != exclude_def:
                return (did, index)
        return options[0]

    def pick_differing_source(
        self, avoid_type: int, exclude_def: int
    ) -> tuple[int, int, int] | None:
        """A concrete output pin whose type is not ``avoid_type``."""
        for want_type in sorted(self.outputs_by_type):
            if want_type == avoid_type:
                continue
            picked = self.pick_source(want_type, exclude_def)
            if picked is not None:
                return (want_type, picked[0], picked[1])
        return None

    def sample_source_types(self, k: int) -> list[int]:
        """At most ``k`` concrete source types, by an even sorted stride."""
        types = sorted(self.outputs_by_type)
        if len(types) <= k:
            return types
        step = len(types) / k
        return [types[int(i * step)] for i in range(k)]


_INDEX = _Index(STORE)


class TestContractStoreSelfConsistency(unittest.TestCase):
    """The store ``validate`` reads must itself be well-formed."""

    def test_store_is_non_trivial(self):
        self.assertGreaterEqual(len(STORE), 400)
        self.assertTrue(_INDEX.qualifying, "no definition has both data in and exec out")
        self.assertIsNotNone(_INDEX.sink_def)

    def test_every_port_has_a_kind_and_a_nonempty_portkey(self):
        # Every port must carry a kind and a ``<kind>:<index>`` key.  (Contracts
        # also permit the unnamed kind 5; see the test below for the deviation
        # from a strict "kind in 1..4" reading.)
        bad: list[str] = []
        for did in STORE.definition_ids():
            definition = STORE.require(did)
            for port in definition.ports:
                if port.kind not in (*_WIREABLE_KINDS, _UNNAMED_KIND):
                    bad.append(f"def {did} {port.key}: unexpected kind {port.kind}")
                if not port.key:
                    bad.append(f"def {did} port index {port.index}: empty portKey")
                elif port.key != f"{port.kind}:{port.index}":
                    bad.append(f"def {did} {port.key}: malformed portKey")
        self.assertEqual(bad, [])

    def test_only_unnamed_kind_five_ports_are_off_the_wireable_set(self):
        # The task asked to assert "every port has kind in 1..4".  That is
        # FALSE for this store: three signal definitions carry a kind-5
        # ("未定-106") pin -- contracts.py:22-23 names it and says it is never
        # wired.  Pin the exact exception so a new non-wireable kind cannot
        # sneak in unnoticed.
        offenders: list[tuple[int, str, str]] = []
        for did in STORE.definition_ids():
            definition = STORE.require(did)
            for port in definition.ports:
                if port.kind not in _WIREABLE_KINDS:
                    offenders.append((did, definition.name, port.key))
        self.assertEqual(
            sorted(offenders),
            [(300000, "发送信号", "5:0"), (300001, "监听信号", "5:0"),
             (300005, "发送客户端脚本信号", "5:0")],
        )

    def test_source_portkey_matches_derived_key(self):
        # ``portKey`` is not carried on the dataclass; it is derived as
        # ``<kind>:<index>``.  Confirm the derivation matches the raw contract
        # and that the raw key is never empty.
        seen = 0
        for path in sorted(_SERVER_CONTRACT_DIR.glob("bucket-*.json")):
            for rec in json.loads(path.read_text(encoding="utf-8")):
                for pin in rec.get("ports", []):
                    seen += 1
                    raw = pin.get("portKey")
                    derived = f"{int(pin['kindRaw'])}:{int(pin['index'])}"
                    if raw != derived:
                        self.fail(
                            f"def {rec['stableKey']['definitionId']}: raw portKey "
                            f"{raw!r} != derived {derived!r}"
                        )
        self.assertGreater(seen, 1000)


class TestDataEdgeTypeMatrix(unittest.TestCase):
    """Matching / mismatching / generic data edges, per qualifying definition."""

    def test_matching_type_is_accepted(self):
        checked = 0
        for did in _INDEX.qualifying:
            definition = STORE.require(did)
            for port in definition.ports:
                if port.kind != DATA_INPUT or port.is_generic:
                    continue
                source = _INDEX.pick_source(port.server_param_type, did)
                if source is None:
                    continue  # no concrete output of this type exists anywhere
                src_def, src_index = source
                with self.subTest(target=did, name=definition.name, pin=port.index):
                    problems = _problems(
                        _two_node_plan(
                            src_def, did,
                            (DATA_OUTPUT, src_index, DATA_INPUT, port.index),
                        )
                    )
                    self.assertEqual(problems, [])
                checked += 1
        # every concrete pin that has a same-typed producer somewhere is covered
        expected = sum(
            1
            for did in _INDEX.qualifying
            for p in STORE.require(did).ports
            if p.kind == DATA_INPUT
            and not p.is_generic
            and _INDEX.outputs_by_type.get(p.server_param_type)
        )
        self.assertGreater(expected, 0)
        self.assertEqual(checked, expected)

    def test_concrete_mismatch_is_rejected(self):
        checked = 0
        for did in _INDEX.qualifying:
            definition = STORE.require(did)
            for port in definition.ports:
                if port.kind != DATA_INPUT or port.is_generic:
                    continue
                other = _INDEX.pick_differing_source(port.server_param_type, did)
                if other is None:
                    continue
                _other_type, src_def, src_index = other
                with self.subTest(target=did, name=definition.name, pin=port.index):
                    problems = _problems(
                        _two_node_plan(
                            src_def, did,
                            (DATA_OUTPUT, src_index, DATA_INPUT, port.index),
                        )
                    )
                    self.assertTrue(
                        any("data type mismatch" in p for p in problems),
                        f"expected a mismatch, got {problems!r}",
                    )
                checked += 1
        # every concrete pin has some differently-typed producer available
        expected = sum(
            1
            for did in _INDEX.qualifying
            for p in STORE.require(did).ports
            if p.kind == DATA_INPUT and not p.is_generic
        )
        self.assertGreater(expected, 0)
        self.assertEqual(checked, expected)

    def test_generic_target_accepts_any_concrete_source(self):
        source_types = _INDEX.sample_source_types(GENERIC_SOURCE_SAMPLE)
        self.assertTrue(source_types, "no concrete output pins in the store")
        checked = 0
        for did in _INDEX.qualifying:
            definition = STORE.require(did)
            for port in definition.ports:
                if port.kind != DATA_INPUT or not port.is_generic:
                    continue
                for want_type in source_types:
                    source = _INDEX.pick_source(want_type, did)
                    if source is None:
                        continue
                    src_def, src_index = source
                    with self.subTest(
                        target=did, name=definition.name, pin=port.index,
                        source_type=want_type,
                    ):
                        problems = _problems(
                            _two_node_plan(
                                src_def, did,
                                (DATA_OUTPUT, src_index, DATA_INPUT, port.index),
                            )
                        )
                        self.assertEqual(problems, [])
                    checked += 1
        expected = sum(
            1
            for did in _INDEX.qualifying
            for p in STORE.require(did).ports
            if p.kind == DATA_INPUT and p.is_generic
        ) * len(source_types)
        self.assertGreater(expected, 0)
        self.assertEqual(checked, expected)


class TestExecutionEdgeMatrix(unittest.TestCase):
    """Execution edges: output index 0/1, target index 0, index 2 rejected."""

    def test_valid_output_index_flows_into_index_zero(self):
        sink = _INDEX.sink_def
        checked = 0
        for did in _INDEX.qualifying:
            definition = STORE.require(did)
            for port in definition.ports:
                if port.kind != EXEC_OUTPUT or port.index not in (0, 1):
                    continue
                with self.subTest(source=did, name=definition.name, out=port.index):
                    problems = _problems(
                        _two_node_plan(
                            did, sink,
                            (EXEC_OUTPUT, port.index, EXEC_INPUT, 0),
                        )
                    )
                    self.assertEqual(problems, [])
                checked += 1
        expected = sum(
            1
            for did in _INDEX.qualifying
            for p in STORE.require(did).ports
            if p.kind == EXEC_OUTPUT and p.index in (0, 1)
        )
        self.assertGreater(expected, 0)
        self.assertEqual(checked, expected)

    def test_execution_output_index_two_is_rejected(self):
        sink = _INDEX.sink_def
        checked = 0
        for did in _INDEX.qualifying:
            definition = STORE.require(did)
            if not any(p.kind == EXEC_OUTPUT for p in definition.ports):
                continue
            with self.subTest(source=did, name=definition.name):
                problems = _problems(
                    _two_node_plan(
                        did, sink,
                        (EXEC_OUTPUT, 2, EXEC_INPUT, 0),
                    )
                )
                self.assertTrue(
                    any("not 0 or 1" in p for p in problems),
                    f"expected index 2 to be rejected, got {problems!r}",
                )
            checked += 1
        # one case per qualifying definition (each declares an exec output)
        self.assertGreater(checked, 0)
        self.assertEqual(checked, len(_INDEX.qualifying))

    def test_execution_target_index_must_be_zero(self):
        sink = _INDEX.sink_def
        checked = 0
        for did in _INDEX.qualifying:
            definition = STORE.require(did)
            if not any(p.kind == EXEC_OUTPUT and p.index == 0 for p in definition.ports):
                continue
            with self.subTest(source=did, name=definition.name):
                problems = _problems(
                    _two_node_plan(
                        did, sink,
                        (EXEC_OUTPUT, 0, EXEC_INPUT, 1),
                    )
                )
                self.assertTrue(
                    any("must be 0" in p for p in problems),
                    f"expected target index 1 to be rejected, got {problems!r}",
                )
            checked += 1
        expected = sum(
            1
            for did in _INDEX.qualifying
            if any(
                p.kind == EXEC_OUTPUT and p.index == 0
                for p in STORE.require(did).ports
            )
        )
        self.assertGreater(expected, 0)
        self.assertEqual(checked, expected)


class TestConstMatrix(unittest.TestCase):
    """A second const on the same pin is rejected; the first is clean."""

    def _single_const_plan(self, definition_id: int, port_index: int) -> GraphPlan:
        plan = GraphPlan(name=_PLAN_NAME)
        plan.add("node", definition_id)
        plan.const("node", port_index, 0, "auto")
        return plan

    def test_first_const_is_clean_and_second_is_rejected(self):
        checked = 0
        for did in _INDEX.qualifying:
            definition = STORE.require(did)
            for port in definition.ports:
                if port.kind != DATA_INPUT:
                    continue
                with self.subTest(target=did, name=definition.name, pin=port.index):
                    plan = self._single_const_plan(did, port.index)
                    self.assertEqual(_problems(plan), [])
                    plan.consts.append(plan.consts[0])
                    problems = _problems(plan)
                    self.assertTrue(
                        any("set twice" in p for p in problems),
                        f"expected 'set twice', got {problems!r}",
                    )
                checked += 1
        expected = sum(
            1
            for did in _INDEX.qualifying
            for p in STORE.require(did).ports
            if p.kind == DATA_INPUT
        )
        self.assertGreater(expected, 0)
        self.assertEqual(checked, expected)


class TestMatrixCoverageIsReal(unittest.TestCase):
    """Guard against the matrix silently degenerating to zero cases."""

    def test_sampling_comment_matches_reality(self):
        self.assertEqual(len(STORE), 500)
        self.assertEqual(len(_INDEX.qualifying), 217)

    def test_generic_pins_exist_to_exercise(self):
        generic = sum(
            1
            for did in _INDEX.qualifying
            for p in STORE.require(did).ports
            if p.kind == DATA_INPUT and p.is_generic
        )
        self.assertGreater(generic, 0)


if __name__ == "__main__":
    unittest.main()
