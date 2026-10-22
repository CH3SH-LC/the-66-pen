"""ONE canonical map from a ``compare`` keyword to the official comparison node.

Before this module there were three private maps with three different key
vocabularies and two different failure types:

* ``modules/currency.py::_COMPARE_NODES`` — ``gte/gt/lt/lte`` (no ``eq``),
  unknown key raised ``ValueError``;
* ``modules/item.py::COMPARATORS`` — ``gte/gt/lte/lt/eq``, unknown key raised
  ``KeyError``;
* ``modules/inventory.py::COMPARE_NODES`` — ``lt/le/gt/ge`` (a *different*
  vocabulary: ``le``/``ge`` instead of ``lte``/``gte``), unknown key raised
  ``KeyError``.

So "the module that compares currency" and "the module that compares items"
disagreed: ``eq`` was reachable from one and not the other, and the same typo
raised two different exception types depending on which module you called.  That
is the trap this file closes: :data:`COMPARE_NODES` is the single source of
truth, :func:`resolve` is the single lookup, and every comparison fragment calls
it.

The five keys are the five comparison nodes the server contract actually carries
(``data/node-contracts``); each value is the matching :class:`~.nodes.NodeType`
already declared in :mod:`graphplan.nodes`, so the pins are addressed by role:
all of these take two generic operands (``left`` 3:0, ``right`` 3:1) and emit a
concrete bool ``result`` (4:0) that drives ``双分支`` (2).
"""

from __future__ import annotations

from .nodes import EQ, GE, GT, LE, LT, NodeType


class UnknownCompareError(KeyError, ValueError):
    """Raised by :func:`resolve` for a ``compare`` key that is not mapped.

    It deliberately derives from **both** ``KeyError`` and ``ValueError``.  The
    two modules this map unifies historically raised different types for the same
    mistake — ``item`` a ``KeyError``, ``currency`` a ``ValueError`` — and both of
    those contracts are asserted by committed tests
    (``tests/test_item_enough.py::test_unknown_compare_raises_keyerror``,
    ``tests/test_currency_compare.py::test_unknown_compare_raises``).  One named
    error that is a member of both keeps every historical ``assertRaises`` honest
    while making the *live* type identical no matter which module you called.
    """


#: ``compare`` keyword -> the official numeric-comparison :class:`NodeType`.
#:
#: This is the task's canonical mapping; ``tests/test_compare.py`` re-derives the
#: ``definitionId``/name pairs from the contract store and fails on any drift.
COMPARE_NODES: dict[str, NodeType] = {
    "gte": GE,  # 233 数值大于等于
    "gt": GT,   # 232 数值大于
    "lte": LE,  # 231 数值小于等于
    "lt": LT,   # 230 数值小于
    "eq": EQ,   # 14  是否相等
}


def resolve(name: str) -> NodeType:
    """The :class:`NodeType` for ``name``, or raise :class:`UnknownCompareError`.

    ``name`` is a key of :data:`COMPARE_NODES` (``gte`` / ``gt`` / ``lte`` /
    ``lt`` / ``eq``).  This is the *only* lookup the comparison fragments use, so
    currency, items (and any future caller) can never drift apart again.
    """
    node_type = COMPARE_NODES.get(name)
    if node_type is None:
        raise UnknownCompareError(
            f"unknown compare {name!r}; known: {sorted(COMPARE_NODES)}"
        )
    return node_type


__all__ = ["COMPARE_NODES", "UnknownCompareError", "resolve"]
