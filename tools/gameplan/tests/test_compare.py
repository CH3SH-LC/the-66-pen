"""Offline tests for the ONE canonical comparison map (``graphplan.compare``).

Task #7 ("一致性 — 比较器在两个模块里必须同一套"): currency and items must compare
through the *same* set of comparison nodes, and the same bad key must fail the
same way from either.  Before :mod:`tools.gameplan.compare` they did not:

* ``currency._COMPARE_NODES`` had no ``eq`` and raised ``ValueError`` on a bad key;
* ``item.COMPARATORS`` had ``eq`` and raised ``KeyError``.

These tests pin the unified behaviour: the map is the task's exact
``gte/gt/lte/lt/eq -> 233/232/231/230/14`` mapping, every entry names the same
node the contract store does, both modules resolve *through* it, both raise the
identical error type for an unknown key, and the two modules agree for every key.

Every assertion here is a pure read (or a graph built in memory) — no bridge, no
native call, no file written.

Run::

    python -B -m unittest tools.gameplan.tests.test_compare
"""

import unittest

from tools.gameplan import Graph
from tools.gameplan import nodes as N
from tools.gameplan.compare import COMPARE_NODES, UnknownCompareError, resolve
from tools.gameplan.contracts import default_store
from tools.gameplan.modules import currency, item


def _source(g: Graph, alias: str = "src"):
    """A concrete execution source whose data output 0 is an entity."""
    return g.place(N.ON_CREATE, alias)


def _build_currency(compare_key: str):
    g = Graph("MW_API_test_compare_currency")
    src = _source(g)
    return currency.read_and_compare(
        g,
        holder=(src, "entity"),
        currency_id=1,
        threshold=1,
        currency_slot="int",
        alias="m2_cmp",
        compare=compare_key,
    )


def _build_item(compare_key: str):
    g = Graph("MW_API_test_compare_item")
    src = _source(g)
    return item.has_enough(
        g,
        holder=(src, "entity"),
        item_id=1,
        threshold=1,
        item_slot="int",
        alias="m3_cmp",
        compare=compare_key,
    )


class TestCanonicalMap(unittest.TestCase):
    def test_map_is_the_task_specified_mapping(self):
        self.assertEqual(
            {key: ntype.definition_id for key, ntype in COMPARE_NODES.items()},
            {"gte": 233, "gt": 232, "lte": 231, "lt": 230, "eq": 14},
        )

    def test_every_entry_matches_the_contract_name(self):
        # "The map matches data/node-contracts names": each NodeType's declared
        # label must equal the name the contract store carries for its id.
        store = default_store()
        for key, ntype in COMPARE_NODES.items():
            with self.subTest(compare=key):
                definition = store.require(ntype.definition_id)
                self.assertEqual(definition.name, ntype.label)

    def test_every_entry_is_the_declared_node_type_object(self):
        # The map must point at graphplan.nodes' own NodeType objects, not copies.
        for key, ntype in COMPARE_NODES.items():
            with self.subTest(compare=key):
                self.assertIn(ntype, N.ALL_NODE_TYPES)
                self.assertIs(resolve(key), ntype)

    def test_resolve_returns_the_mapped_node_type(self):
        for key, ntype in COMPARE_NODES.items():
            with self.subTest(compare=key):
                self.assertIs(resolve(key), ntype)


class TestUnknownError(unittest.TestCase):
    def test_resolve_raises_the_named_error(self):
        with self.assertRaises(UnknownCompareError) as ctx:
            resolve("approximately")
        self.assertIn("approximately", str(ctx.exception))

    def test_the_named_error_is_one_type(self):
        # A single named error, not two: it is a member of both historical types
        # so the *live* type is identical from every caller.
        self.assertTrue(issubclass(UnknownCompareError, KeyError))
        self.assertTrue(issubclass(UnknownCompareError, ValueError))

    def test_both_modules_raise_the_same_error_type(self):
        with self.assertRaises(UnknownCompareError) as currency_ctx:
            _build_currency("approximately")
        with self.assertRaises(UnknownCompareError) as item_ctx:
            _build_item("approximately")

        self.assertIs(type(currency_ctx.exception), type(item_ctx.exception))
        self.assertIs(type(currency_ctx.exception), UnknownCompareError)


class TestBothModulesUseTheMap(unittest.TestCase):
    def test_both_modules_place_the_canonical_definition_for_every_key(self):
        for key, ntype in COMPARE_NODES.items():
            with self.subTest(compare=key):
                self.assertIs(_build_currency(key).ntype, ntype)
                self.assertIs(_build_item(key).ntype, ntype)

    def test_currency_and_item_agree_for_every_key(self):
        for key in COMPARE_NODES:
            with self.subTest(compare=key):
                self.assertEqual(
                    _build_currency(key).ntype.definition_id,
                    _build_item(key).ntype.definition_id,
                )

    def test_currency_now_reaches_eq_like_item(self):
        # The old divergence: item had "eq", currency did not.  Both do now.
        self.assertEqual(_build_currency("eq").ntype.definition_id, 14)
        self.assertEqual(_build_item("eq").ntype.definition_id, 14)

    def test_defaults_are_still_gte_and_agree(self):
        g_cur = Graph("MW_API_test_compare_cur_default")
        src_cur = _source(g_cur)
        cur = currency.read_and_compare(
            g_cur,
            holder=(src_cur, "entity"),
            currency_id=1,
            threshold=1,
            currency_slot="int",
            alias="m2_cmp",
        )
        g_it = Graph("MW_API_test_compare_item_default")
        src_it = _source(g_it)
        it = item.has_enough(
            g_it, holder=(src_it, "entity"), item_id=1, threshold=1, item_slot="int"
        )
        self.assertEqual(cur.ntype.definition_id, 233)
        self.assertEqual(it.ntype.definition_id, 233)


if __name__ == "__main__":
    unittest.main()
