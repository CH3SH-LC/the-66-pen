"""Create runtime sale and buyback rows without a hand-authored goods sample.

708 appends custom-shop goods and returns the new index; 710 appends a buyback
row. Their pin layouts come from ``data/node-contracts``. The official shop
component chapter (mho6gviqhsqs) describes both operations and explains that
the component instantiates its referenced shop template at runtime.

These functions create graph plans, not item/currency/shop templates or shop
components. Supply real configuration IDs and bind the startup plan to an
existing owner with the requested shop component/index. Prices require the
adapter's concrete type-27 dictionary writer. Prices default to uint currency
IDs and int amounts, matching the observed 704 dictionary descriptor. The
708/710 descriptors still require live verification; tags remain explicit.
Flags default to enum (uint 0/1) for their type-4 contract; ``flag_slot='bool'``
is available when a live descriptor establishes a bool storage slot.

Install once per owner creation: appending rows is NOT idempotent. Engine
trading handles the transaction; this module adds no second wallet payout.
Persist the graph through the normal native save flow. Successful compilation
alone is neither runtime trade evidence nor persistent-save evidence.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .nodes import Graph, Handle, NodeType, ON_CREATE, PRINT
from .plan import GraphPlan, NODE_LIMIT

OwnerRef = tuple[Handle, str]
INT_MAX = 2**31 - 1
UINT_MAX = 2**32 - 1

ADD_CUSTOM_SHOP_ITEM = NodeType(
    708, "向自定义商店出售表中新增商品", exec_in=0, exec_outs={"then": 0},
    ins={"shop_owner": 0, "shop_index": 1, "item": 2, "price": 3,
         "tab_index": 4, "limited": 5, "limit_count": 6,
         "sort_priority": 7, "sellable": 8},
    outs={"item_index": 0},
)
ADD_PURCHASE_ITEM = NodeType(
    710, "向物品收购表中新增物品", exec_in=0, exec_outs={"then": 0},
    ins={"shop_owner": 0, "shop_index": 1, "item": 2, "price": 3,
         "purchasable": 4},
)
CATALOG_NODE_TYPES = (ADD_CUSTOM_SHOP_ITEM, ADD_PURCHASE_ITEM)


def _integer(value: object, name: str, minimum: int = 1, maximum: int = INT_MAX) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _tag_max(tag: str) -> int:
    if tag not in ("int", "uint"):
        raise ValueError("price leaf tag must be 'int' or 'uint'")
    return INT_MAX if tag == "int" else UINT_MAX


def price_entries(
    price: Mapping[int, int], *, key_tag: str = "uint", value_tag: str = "int",
) -> list[dict]:
    """Encode 1..64 currency/amount pairs as sorted, tagged dictionary leaves."""
    key_max, value_max = _tag_max(key_tag), _tag_max(value_tag)
    if not isinstance(price, Mapping) or not 1 <= len(price) <= 64:
        raise ValueError("price must contain 1..64 currency/amount pairs")
    pairs = []
    for currency_id, amount in price.items():
        pairs.append((_integer(currency_id, "currency_id", maximum=key_max),
                      _integer(amount, "price amount", maximum=value_max)))
    return [{"key": {key_tag: key}, "value": {value_tag: value}}
            for key, value in sorted(pairs)]


@dataclass(frozen=True)
class SaleProduct:
    item_id: int
    price: Mapping[int, int]
    tab_index: int = 3
    sort_priority: int = 0
    sellable: bool = True
    limit_count: int | None = None


@dataclass(frozen=True)
class PurchaseProduct:
    item_id: int
    price: Mapping[int, int]
    purchasable: bool = True


@dataclass(frozen=True)
class CatalogInstall:
    last: Handle
    sales: tuple[Handle, ...]
    purchases: tuple[Handle, ...]


def _product_values(product, *, sale: bool, item_slot: str, key_tag: str,
                    value_tag: str, flag_slot: str) -> dict:
    expected = SaleProduct if sale else PurchaseProduct
    if not isinstance(product, expected):
        raise ValueError(f"product must be {expected.__name__}")
    if item_slot not in ("int", "uint"):
        raise ValueError("item_slot must be 'int' or 'uint'")
    if flag_slot not in ("bool", "enum"):
        raise ValueError("flag_slot must be 'bool' or 'enum'")
    values = {"item": _integer(product.item_id, "item_id", maximum=_tag_max(item_slot)),
              "price": {"dict": price_entries(product.price, key_tag=key_tag,
                                                value_tag=value_tag)}}
    if sale:
        if type(product.sellable) is not bool:
            raise ValueError("sellable must be bool")
        values.update(tab_index=_integer(product.tab_index, "tab_index"),
                      sort_priority=_integer(product.sort_priority, "sort_priority", 0),
                      limited=product.limit_count is not None,
                      limit_count=0 if product.limit_count is None else
                      _integer(product.limit_count, "limit_count"),
                      sellable=product.sellable)
    else:
        if type(product.purchasable) is not bool:
            raise ValueError("purchasable must be bool")
        values["purchasable"] = product.purchasable
    return values


def _check_refs(g: Graph, src: Handle, shop_owner: OwnerRef, from_role: str,
                aliases: Sequence[str]) -> None:
    owner, owner_role = shop_owner
    if src.graph is not g or owner.graph is not g:
        raise ValueError("source and shop owner must belong to this graph")
    if from_role not in src.ntype.exec_outs or owner_role not in owner.ntype.outs:
        raise ValueError("source execution role or shop owner data role is absent")
    if len(g.plan.nodes) + len(aliases) > NODE_LIMIT:
        raise ValueError("catalog exceeds graph node limit")
    existing = g.plan.aliases()
    if len(set(aliases)) != len(aliases) or any(a in existing or not a for a in aliases):
        raise ValueError("catalog node aliases must be non-empty and unused")


def _append(g, src, *, shop_owner, shop_index, values, sale, item_slot, flag_slot,
            alias, from_role):
    node = g.place(ADD_CUSTOM_SHOP_ITEM if sale else ADD_PURCHASE_ITEM, alias)
    src.flow_to(node, from_role)
    owner, role = shop_owner
    node.data_from(owner, role, "shop_owner")
    node.const("shop_index", shop_index, "int")
    for role, value in values.items():
        slot = "auto" if role == "price" else item_slot if role == "item" else (
            flag_slot if type(value) is bool else "int")
        if slot == "enum":
            value = int(value)
        node.const(role, value, slot)
    return node


def add_sale(g: Graph, src: Handle, *, shop_owner: OwnerRef, shop_index: int,
             product: SaleProduct, item_slot: str = "int", alias: str = "catalog_sale",
             from_role: str = "then", key_tag: str = "uint", value_tag: str = "int",
             flag_slot: str = "enum") -> Handle:
    """Append custom goods (708); returned handle exposes ``item_index``."""
    index = _integer(shop_index, "shop_index", 0)
    values = _product_values(product, sale=True, item_slot=item_slot,
                             key_tag=key_tag, value_tag=value_tag, flag_slot=flag_slot)
    _check_refs(g, src, shop_owner, from_role, [alias])
    return _append(g, src, shop_owner=shop_owner, shop_index=index, values=values,
                   sale=True, item_slot=item_slot, flag_slot=flag_slot,
                   alias=alias, from_role=from_role)


def add_purchase(g: Graph, src: Handle, *, shop_owner: OwnerRef, shop_index: int,
                 product: PurchaseProduct, item_slot: str = "int",
                 alias: str = "catalog_purchase", from_role: str = "then",
                 key_tag: str = "uint", value_tag: str = "int",
                 flag_slot: str = "enum") -> Handle:
    """Append a buyback row (710); the engine pays the configured currencies."""
    index = _integer(shop_index, "shop_index", 0)
    values = _product_values(product, sale=False, item_slot=item_slot,
                             key_tag=key_tag, value_tag=value_tag, flag_slot=flag_slot)
    _check_refs(g, src, shop_owner, from_role, [alias])
    return _append(g, src, shop_owner=shop_owner, shop_index=index, values=values,
                   sale=False, item_slot=item_slot, flag_slot=flag_slot,
                   alias=alias, from_role=from_role)


def install_catalog(
    g: Graph, src: Handle, *, shop_owner: OwnerRef, shop_index: int,
    sales: Sequence[SaleProduct] = (), purchases: Sequence[PurchaseProduct] = (),
    item_slot: str = "int", alias: str = "catalog", from_role: str = "then",
    key_tag: str = "uint", value_tag: str = "int", flag_slot: str = "enum",
) -> CatalogInstall:
    """Validate the entire catalogue, then serially append sales and buybacks.

    No mutation occurs for invalid products or duplicate item IDs on one side.
    The same item may legitimately occur on both sides with different prices.
    """
    index = _integer(shop_index, "shop_index", 0)
    sales, purchases = tuple(sales), tuple(purchases)
    if not sales and not purchases:
        raise ValueError("catalog must contain at least one product")
    prepared = []
    for sale, products in ((True, sales), (False, purchases)):
        seen = set()
        for i, product in enumerate(products):
            values = _product_values(product, sale=sale, item_slot=item_slot,
                                     key_tag=key_tag, value_tag=value_tag,
                                     flag_slot=flag_slot)
            if values["item"] in seen:
                raise ValueError("duplicate item_id on one catalog side")
            seen.add(values["item"])
            prepared.append((sale, f"{alias}_{'sale' if sale else 'purchase'}_{i}", values))
    _check_refs(g, src, shop_owner, from_role, [row[1] for row in prepared])
    sale_handles, purchase_handles = [], []
    last = src
    for sale, node_alias, values in prepared:
        last = _append(g, last, shop_owner=shop_owner, shop_index=index, values=values,
                       sale=sale, item_slot=item_slot, flag_slot=flag_slot,
                       alias=node_alias, from_role=from_role)
        (sale_handles if sale else purchase_handles).append(last)
        from_role = "then"
    return CatalogInstall(last, tuple(sale_handles), tuple(purchase_handles))


def build_catalog_plan(
    name: str, *, shop_index: int, sales: Sequence[SaleProduct] = (),
    purchases: Sequence[PurchaseProduct] = (), item_slot: str = "int",
    key_tag: str = "uint", value_tag: str = "int", flag_slot: str = "enum",
) -> GraphPlan:
    """Startup graph for an existing shop owner; supplies no invented config IDs."""
    g = Graph(name)
    created = g.place(ON_CREATE, "catalog_created")
    installed = install_catalog(g, created, shop_owner=(created, "entity"),
                                shop_index=shop_index, sales=sales, purchases=purchases,
                                item_slot=item_slot, key_tag=key_tag, value_tag=value_tag,
                                flag_slot=flag_slot)
    done = g.place(PRINT, "catalog_installed")
    done.const("text", "MW_ECONOMY_CATALOG_INSTALLED", "string")
    installed.last.flow_to(done)
    g.validate()
    return g.plan
