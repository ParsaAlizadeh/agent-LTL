from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from .models import Order, RetailDB


class RetailToolError(ValueError):
    pass


@dataclass
class RetailState:
    db: RetailDB
    authenticated_user_id: str | None = None

    def clone(self) -> RetailState:
        return RetailState(
            db=self.db.clone(),
            authenticated_user_id=self.authenticated_user_id,
        )


def _object_schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _string(description: str) -> dict:
    return {"type": "string", "description": description}


def _string_list(description: str) -> dict:
    return {
        "type": "array",
        "description": description,
        "items": {"type": "string"},
        "minItems": 1,
    }


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": _object_schema(properties, required),
        "strict": True,
    }


RETAIL_TOOLS = [
    _tool(
        "find_user_id_by_email",
        "Authenticate a customer by finding their user ID from their email.",
        {"email": _string("Customer email address")},
        ["email"],
    ),
    _tool(
        "find_user_id_by_name_zip",
        "Authenticate a customer by finding their user ID from name and ZIP code.",
        {
            "first_name": _string("Customer first name"),
            "last_name": _string("Customer last name"),
            "zip": _string("Customer ZIP code"),
        },
        ["first_name", "last_name", "zip"],
    ),
    _tool(
        "get_user_details",
        "Get the authenticated customer's profile and order IDs.",
        {"user_id": _string("User ID")},
        ["user_id"],
    ),
    _tool(
        "get_order_details",
        "Get an order belonging to the authenticated customer.",
        {"order_id": _string("Numeric order ID")},
        ["order_id"],
    ),
    _tool(
        "get_product_details",
        "Get a product and its variants.",
        {"product_id": _string("Product ID")},
        ["product_id"],
    ),
    _tool(
        "get_item_details",
        "Get one product variant by item ID.",
        {"item_id": _string("Variant item ID")},
        ["item_id"],
    ),
    _tool(
        "cancel_pending_order",
        "Cancel and refund an authenticated customer's pending order.",
        {
            "order_id": _string("Pending order ID"),
            "reason": {
                "type": "string",
                "enum": ["no longer needed", "ordered by mistake"],
            },
        },
        ["order_id", "reason"],
    ),
    _tool(
        "exchange_delivered_order_items",
        "Exchange delivered-order items for available variants of the same products.",
        {
            "order_id": _string("Delivered order ID"),
            "item_ids": _string_list("Item IDs to exchange; duplicates are meaningful"),
            "new_item_ids": _string_list(
                "Replacement item IDs, positionally paired with item_ids"
            ),
            "payment_method_id": _string(
                "Customer payment method for the price difference"
            ),
        },
        ["order_id", "item_ids", "new_item_ids", "payment_method_id"],
    ),
]

TOOL_NAMES = frozenset(tool["name"] for tool in RETAIL_TOOLS)


def execute_retail_tool(
    state: RetailState, name: str, arguments: dict[str, Any]
) -> dict[str, Any] | str:
    if name == "find_user_id_by_email":
        user_id = _find_by_email(state.db, arguments["email"])
        _authenticate(state, user_id)
        return user_id

    if name == "find_user_id_by_name_zip":
        user_id = _find_by_name_zip(
            state.db,
            arguments["first_name"],
            arguments["last_name"],
            arguments["zip"],
        )
        _authenticate(state, user_id)
        return user_id

    if name == "get_user_details":
        return asdict(state.db.users[arguments["user_id"]])
    if name == "get_order_details":
        return asdict(state.db.orders[arguments["order_id"]])
    if name == "get_product_details":
        return asdict(state.db.products[arguments["product_id"]])
    if name == "get_item_details":
        item = state.db.item(arguments["item_id"])
        if item is None:
            raise RetailToolError("Item not found.")
        return asdict(item)
    if name == "cancel_pending_order":
        return _cancel_order(state, arguments["order_id"], arguments["reason"])
    if name == "exchange_delivered_order_items":
        return _exchange_items(state, arguments)
    raise RetailToolError(f"Unknown retail tool: {name!r}.")


def _find_by_email(db: RetailDB, email: str) -> str:
    for user in db.users.values():
        if user.email.casefold() == email.casefold():
            return user.user_id
    raise RetailToolError("User not found.")


def _find_by_name_zip(
    db: RetailDB, first_name: str, last_name: str, zip_code: str
) -> str:
    for user in db.users.values():
        if (
            user.first_name.casefold() == first_name.casefold()
            and user.last_name.casefold() == last_name.casefold()
            and user.address.zip == zip_code
        ):
            return user.user_id
    raise RetailToolError("User not found.")


def _authenticate(state: RetailState, user_id: str) -> None:
    state.authenticated_user_id = user_id


def _cancel_order(state: RetailState, order_id: str, reason: str) -> dict[str, Any]:
    order = state.db.orders[order_id]
    refunds: list = []
    for payment in list(order.payment_history):
        if payment.transaction_type != "payment":
            continue
        refund = type(payment)("refund", payment.amount, payment.payment_method_id)
        refunds.append(refund)
        method = state.db.users[order.user_id].payment_methods[
            payment.payment_method_id
        ]
        if method.kind == "gift_card":
            method.balance = round((method.balance or 0) + payment.amount, 2)
    order.payment_history.extend(refunds)
    order.status = "cancelled"
    order.cancel_reason = reason
    return asdict(order)


def _exchange_items(
    state: RetailState, arguments: dict[str, Any]
) -> dict[str, Any]:
    order = state.db.orders[arguments["order_id"]]
    item_ids = arguments["item_ids"]
    new_item_ids = arguments["new_item_ids"]
    difference = 0.0

    remaining = list(order.items)
    for old_id, new_id in zip(item_ids, new_item_ids, strict=True):
        old_index = next(
            index for index, item in enumerate(remaining) if item.item_id == old_id
        )
        old_item = remaining.pop(old_index)
        new_item = state.db.item(new_id)
        if new_item is None:
            raise RetailToolError("Replacement item not found.")
        difference += new_item.price - old_item.price

    order.status = "exchange requested"
    order.exchange_items = sorted(item_ids)
    order.exchange_new_items = sorted(new_item_ids)
    order.exchange_payment_method_id = arguments["payment_method_id"]
    order.exchange_price_difference = round(difference, 2)
    return asdict(order)


def order_contains_items(order: Order, item_ids: list[str]) -> bool:
    available = Counter(item.item_id for item in order.items)
    requested = Counter(item_ids)
    return all(count <= available[item_id] for item_id, count in requested.items())
