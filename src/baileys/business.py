from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .defaults import S_WHATSAPP_NET
from .jid import jid_normalized_user
from .socket_nodes import find_child, node_content_bytes
from .wabinary import BinaryNode


@dataclass(frozen=True)
class Product:
    id: str | None = None
    name: str | None = None
    description: str | None = None
    currency: str | None = None
    price: int | None = None
    hidden: bool | None = None
    raw: BinaryNode | None = None


@dataclass(frozen=True)
class CatalogResult:
    products: list[Product] = field(default_factory=list)
    next_cursor: str | None = None
    raw: BinaryNode | None = None


def update_business_profile_node(args: dict[str, Any], tag_id: str) -> BinaryNode:
    children: list[BinaryNode] = []
    for key in ("address", "email", "description"):
        if args.get(key) is not None:
            children.append(BinaryNode(key, {}, str(args[key]).encode("utf-8")))
    for website in args.get("websites") or []:
        children.append(BinaryNode("website", {}, str(website).encode("utf-8")))
    hours = args.get("hours")
    if isinstance(hours, dict):
        day_nodes = []
        for item in hours.get("days") or []:
            attrs = {"day_of_week": str(item["day"]), "mode": str(item["mode"])}
            if item.get("mode") == "specific_hours":
                attrs["open_time"] = str(item.get("open_time") or item.get("openTimeInMinutes") or 0)
                attrs["close_time"] = str(item.get("close_time") or item.get("closeTimeInMinutes") or 0)
            day_nodes.append(BinaryNode("business_hours_config", attrs))
        children.append(BinaryNode("business_hours", {"timezone": str(hours.get("timezone") or "")}, day_nodes))
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "set", "xmlns": "w:biz"},
        [BinaryNode("business_profile", {"v": "3", "mutation_type": "delta"}, children)],
    )


def catalog_node(jid: str, tag_id: str, *, limit: int = 10, cursor: str | None = None) -> BinaryNode:
    query = [
        BinaryNode("limit", {}, str(limit).encode("utf-8")),
        BinaryNode("width", {}, b"100"),
        BinaryNode("height", {}, b"100"),
    ]
    if cursor:
        query.append(BinaryNode("after", {}, cursor.encode("utf-8")))
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "get", "xmlns": "w:biz:catalog"},
        [BinaryNode("product_catalog", {"jid": jid_normalized_user(jid), "allow_shop_source": "true"}, query)],
    )


def collections_node(jid: str, tag_id: str, *, limit: int = 51) -> BinaryNode:
    content = [
        BinaryNode("collection_limit", {}, str(limit).encode("utf-8")),
        BinaryNode("item_limit", {}, str(limit).encode("utf-8")),
        BinaryNode("width", {}, b"100"),
        BinaryNode("height", {}, b"100"),
    ]
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "get", "xmlns": "w:biz:catalog", "smax_id": "35"},
        [BinaryNode("collections", {"biz_jid": jid_normalized_user(jid)}, content)],
    )


def order_details_node(order_id: str, token_base64: str, tag_id: str) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "get", "xmlns": "fb:thrift_iq", "smax_id": "5"},
        [
            BinaryNode(
                "order",
                {"op": "get", "id": order_id},
                [
                    BinaryNode("image_dimensions", {}, [BinaryNode("width", {}, b"100"), BinaryNode("height", {}, b"100")]),
                    BinaryNode("token", {}, token_base64.encode("utf-8")),
                ],
            )
        ],
    )


def product_delete_node(product_ids: list[str], tag_id: str) -> BinaryNode:
    products = [BinaryNode("product", {}, [BinaryNode("id", {}, item.encode("utf-8"))]) for item in product_ids]
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "set", "xmlns": "w:biz:catalog"},
        [BinaryNode("product_catalog_delete", {"v": "1"}, products)],
    )


def product_create_node(product: dict[str, Any], tag_id: str) -> BinaryNode:
    return _product_mutation_node("product_catalog_add", None, product, tag_id)


def product_update_node(product_id: str, product: dict[str, Any], tag_id: str) -> BinaryNode:
    return _product_mutation_node("product_catalog_edit", product_id, product, tag_id)


def parse_product_mutation(node: BinaryNode, container_tag: str) -> Product | None:
    container = find_child(node, container_tag)
    product = find_child(container, "product") if container is not None else None
    return parse_product(product) if product is not None else None


def parse_catalog(node: BinaryNode) -> CatalogResult:
    catalog = find_child(node, "product_catalog") or find_child(node, "catalog")
    if catalog is None:
        return CatalogResult(raw=node)
    products = [parse_product(child) for child in _children(catalog, "product")]
    return CatalogResult(products=products, next_cursor=catalog.attrs.get("after") or catalog.attrs.get("next"), raw=node)


def parse_product(node: BinaryNode) -> Product:
    return Product(
        id=_child_text(node, "id") or node.attrs.get("id"),
        name=_child_text(node, "name") or node.attrs.get("name"),
        description=_child_text(node, "description"),
        currency=_child_text(node, "currency"),
        price=_optional_int(_child_text(node, "price")),
        hidden=_optional_bool(_child_text(node, "is_hidden") or node.attrs.get("is_hidden")),
        raw=node,
    )


def parse_product_delete(node: BinaryNode) -> int:
    deleted = find_child(node, "product_catalog_delete")
    return int(deleted.attrs.get("deleted_count") or 0) if deleted is not None else 0


def _children(node: BinaryNode, tag: str) -> list[BinaryNode]:
    return [child for child in node.content or [] if isinstance(child, BinaryNode) and child.tag == tag] if isinstance(node.content, list) else []


def _child_text(node: BinaryNode, tag: str) -> str | None:
    child = find_child(node, tag)
    content = node_content_bytes(child)
    return content.decode("utf-8", errors="replace") if content is not None else None


def _optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return str(value).lower() in {"1", "true", "yes"}


def _product_mutation_node(container_tag: str, product_id: str | None, product: dict[str, Any], tag_id: str) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "set", "xmlns": "w:biz:catalog"},
        [
            BinaryNode(
                container_tag,
                {"v": "1"},
                [
                    _product_node(product_id, product),
                    BinaryNode("width", {}, b"100"),
                    BinaryNode("height", {}, b"100"),
                ],
            )
        ],
    )


def _product_node(product_id: str | None, product: dict[str, Any]) -> BinaryNode:
    children: list[BinaryNode] = []
    if product_id:
        children.append(BinaryNode("id", {}, product_id.encode("utf-8")))
    field_names = {
        "name": "name",
        "description": "description",
        "currency": "currency",
        "price": "price",
        "url": "url",
        "retailer_id": "retailer_id",
        "is_hidden": "is_hidden",
    }
    for source, tag in field_names.items():
        if source in product and product[source] is not None:
            value = product[source]
            if isinstance(value, bool):
                value = "true" if value else "false"
            children.append(BinaryNode(tag, {}, str(value).encode("utf-8")))
    return BinaryNode("product", {}, children)
