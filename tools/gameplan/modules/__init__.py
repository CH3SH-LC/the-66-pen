"""The six gameplay modules, expressed as node-graph fragments.

Each module is a small function that takes a :class:`graphplan.Graph` that has
already been wired up to an execution source, adds the official nodes for that
capability, and returns the handle(s) it created so the caller can chain on.

Design rules (all three are load-bearing):

* **Only official nodes.** Every node is a real ``definitionId`` from
  ``data/node-contracts``; nothing is invented and nothing is a placeholder.
* **Never index a pin by hand.** Roles come from :mod:`graphplan.nodes`, which
  ``tests/test_plan.py`` re-checks against the contracts.
* **A blocked capability is a documented absence, not a stub.** Where the tool
  genuinely cannot do something (creating currency/item templates, configuring a
  collision-trigger component), the module says so in its docstring instead of
  pretending.
"""

from . import currency, interaction, inventory, item, player_abilities, shop

__all__ = ["currency", "interaction", "inventory", "item", "shop", "player_abilities", "MODULES"]

#: Module registry, keyed by the identifier used in docs and the demo plan.
MODULES = {
    "M1-interaction": interaction,
    "M2-currency": currency,
    "M3-item": item,
    "M4-inventory": inventory,
    "M5-shop": shop,
}
