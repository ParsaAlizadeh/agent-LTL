from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

from ...types import ToolCall, ToolResult
from .data import (
    DELIVERED_ORDER_ID,
    TARGET_NEW_ITEM_ID,
    TARGET_OLD_ITEM_ID,
    TARGET_PAYMENT_METHOD_ID,
)
from .models import Order, RetailDB, User
from .tools import (
    TOOL_NAMES,
    RetailState,
    RetailToolError,
    execute_retail_tool,
    order_contains_items,
)


PredicateMap = dict[str, bool]
Validator = Callable[[RetailState, dict[str, Any]], PredicateMap]


@dataclass(frozen=True)
class ActionPolicy:
    fields: dict[str, type]
    validator: Validator

    @property
    def conditions(self) -> tuple[str, ...]:
        return tuple(self.validator(RetailState(_empty_db()), {}).keys())


@dataclass
class BatchEvaluation:
    symbols: set[str]
    next_state: RetailState | None
    results: list[ToolResult]
    errors: list[str]


def _empty_db() -> RetailDB:
    return RetailDB(users={}, products={}, orders={})


def _user(state: RetailState, user_id: Any) -> User | None:
    return state.db.users.get(user_id) if isinstance(user_id, str) else None


def _order(state: RetailState, order_id: Any) -> Order | None:
    return state.db.orders.get(order_id) if isinstance(order_id, str) else None


def _find_email_user(state: RetailState, email: Any) -> User | None:
    if not isinstance(email, str):
        return None
    return next(
        (
            user
            for user in state.db.users.values()
            if user.email.casefold() == email.casefold()
        ),
        None,
    )


def _find_name_zip_user(state: RetailState, args: dict[str, Any]) -> User | None:
    first_name = args.get("first_name")
    last_name = args.get("last_name")
    zip_code = args.get("zip")
    if not all(isinstance(value, str) for value in (first_name, last_name, zip_code)):
        return None
    return next(
        (
            user
            for user in state.db.users.values()
            if user.first_name.casefold() == first_name.casefold()
            and user.last_name.casefold() == last_name.casefold()
            and user.address.zip == zip_code
        ),
        None,
    )


def _auth_conditions(matched: User | None) -> PredicateMap:
    return {"lookup_matches_user": matched is not None}


def _validate_email(state: RetailState, args: dict[str, Any]) -> PredicateMap:
    return _auth_conditions(_find_email_user(state, args.get("email")))


def _validate_name_zip(state: RetailState, args: dict[str, Any]) -> PredicateMap:
    return _auth_conditions(_find_name_zip_user(state, args))


def _validate_user_read(state: RetailState, args: dict[str, Any]) -> PredicateMap:
    target = _user(state, args.get("user_id"))
    return {
        "user_exists": target is not None,
        "target_is_authenticated_user": target is not None
        and target.user_id == state.authenticated_user_id,
    }


def _order_access(state: RetailState, args: dict[str, Any]) -> PredicateMap:
    target = _order(state, args.get("order_id"))
    return {
        "order_exists": target is not None,
        "order_owned_by_authenticated_user": target is not None
        and target.user_id == state.authenticated_user_id,
    }


def _validate_order_read(state: RetailState, args: dict[str, Any]) -> PredicateMap:
    return _order_access(state, args)


def _validate_product_read(state: RetailState, args: dict[str, Any]) -> PredicateMap:
    product_id = args.get("product_id")
    return {
        "product_exists": isinstance(product_id, str)
        and product_id in state.db.products,
    }


def _validate_item_read(state: RetailState, args: dict[str, Any]) -> PredicateMap:
    item_id = args.get("item_id")
    return {
        "item_exists": isinstance(item_id, str) and state.db.item(item_id) is not None,
    }


def _validate_cancel(state: RetailState, args: dict[str, Any]) -> PredicateMap:
    conditions = _order_access(state, args)
    target = _order(state, args.get("order_id"))
    conditions.update(
        {
            "order_status_pending": target is not None and target.status == "pending",
            "reason_allowed": args.get("reason")
            in {"no longer needed", "ordered by mistake"},
        }
    )
    return conditions


def _paired_order_items(
    order: Order | None, item_ids: Any, new_item_ids: Any, db: RetailDB
) -> list[tuple[Any, Any]] | None:
    if (
        order is None
        or not isinstance(item_ids, list)
        or not isinstance(new_item_ids, list)
        or len(item_ids) != len(new_item_ids)
        or not order_contains_items(order, item_ids)
    ):
        return None

    remaining = list(order.items)
    pairs = []
    for old_id, new_id in zip(item_ids, new_item_ids, strict=True):
        old_index = next(
            (index for index, item in enumerate(remaining) if item.item_id == old_id),
            None,
        )
        replacement = db.item(new_id) if isinstance(new_id, str) else None
        if old_index is None or replacement is None:
            return None
        pairs.append((remaining.pop(old_index), replacement))
    return pairs


def _validate_exchange(state: RetailState, args: dict[str, Any]) -> PredicateMap:
    conditions = _order_access(state, args)
    target = _order(state, args.get("order_id"))
    item_ids = args.get("item_ids")
    new_item_ids = args.get("new_item_ids")
    lists = isinstance(item_ids, list) and isinstance(new_item_ids, list)
    strings = lists and all(
        isinstance(value, str) for value in [*item_ids, *new_item_ids]
    )
    nonempty = strings and bool(item_ids) and bool(new_item_ids)
    same_count = strings and len(item_ids) == len(new_item_ids)
    contained = (
        strings and target is not None and order_contains_items(target, item_ids)
    )
    replacements = (
        [state.db.item(item_id) for item_id in new_item_ids] if strings else []
    )
    replacements_exist = strings and all(item is not None for item in replacements)
    pairs = _paired_order_items(target, item_ids, new_item_ids, state.db)

    payment_id = args.get("payment_method_id")
    owner = _user(state, target.user_id) if target is not None else None
    payment = (
        owner.payment_methods.get(payment_id)
        if owner is not None and isinstance(payment_id, str)
        else None
    )
    difference = (
        round(sum(new.price - old.price for old, new in pairs), 2)
        if pairs is not None
        else None
    )

    conditions.update(
        {
            "order_status_delivered": target is not None
            and target.status == "delivered",
            "item_lists_nonempty": nonempty,
            "replacement_count_matches": same_count,
            "items_in_order_with_multiplicity": bool(contained),
            "replacements_exist": bool(replacements_exist),
            "replacements_are_different": strings
            and same_count
            and all(old != new for old, new in zip(item_ids, new_item_ids)),
            "replacements_same_product": pairs is not None
            and all(old.product_id == new.product_id for old, new in pairs),
            "replacement_options_different": pairs is not None
            and all(old.options != new.options for old, new in pairs),
            "replacements_available": replacements_exist
            and all(item is not None and item.available for item in replacements),
            "payment_method_exists_for_order_owner": payment is not None,
            "gift_card_balance_sufficient": payment is not None
            and (
                payment.kind != "gift_card"
                or (payment.balance or 0) >= max(difference or 0, 0)
            ),
        }
    )
    return conditions


ACTION_POLICIES: dict[str, ActionPolicy] = {
    "find_user_id_by_email": ActionPolicy({"email": str}, _validate_email),
    "find_user_id_by_name_zip": ActionPolicy(
        {"first_name": str, "last_name": str, "zip": str}, _validate_name_zip
    ),
    "get_user_details": ActionPolicy({"user_id": str}, _validate_user_read),
    "get_order_details": ActionPolicy({"order_id": str}, _validate_order_read),
    "get_product_details": ActionPolicy(
        {"product_id": str}, _validate_product_read
    ),
    "get_item_details": ActionPolicy({"item_id": str}, _validate_item_read),
    "cancel_pending_order": ActionPolicy(
        {"order_id": str, "reason": str}, _validate_cancel
    ),
    "exchange_delivered_order_items": ActionPolicy(
        {
            "order_id": str,
            "item_ids": list,
            "new_item_ids": list,
            "payment_method_id": str,
        },
        _validate_exchange,
    ),
}

AUTHENTICATION_ACTIONS = (
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
)
PROTECTED_ACTIONS = (
    "get_user_details",
    "get_order_details",
    "get_product_details",
    "get_item_details",
    "cancel_pending_order",
    "exchange_delivered_order_items",
)
WRITE_ACTIONS = (
    "cancel_pending_order",
    "exchange_delivered_order_items",
)


def proposition(action: str, condition: str) -> str:
    return f"{action}__{condition}"


def retail_formula(*, require_target_exchange: bool = False) -> str:
    clauses = ["G(!unknown_tool)", "G(!malformed_arguments)", "G(!preflight_failed)"]
    for action, policy in ACTION_POLICIES.items():
        required = " && ".join(
            proposition(action, condition) for condition in policy.conditions
        )
        clauses.append(f"G(call_{action} -> ({required}))")
    protected = _action_disjunction(PROTECTED_ACTIONS)
    write = _action_disjunction(WRITE_ACTIONS)
    inspect = "call_get_order_details"
    clauses.extend(
        [
            f"(!({protected}) W (authentication_succeeded && !({protected})))",
            "G(authentication_succeeded -> X(G(!authentication_succeeded)))",
            f"(!({write}) W ({inspect} && !({write})))",
            f"G(({write}) -> X(!({write}) W ({inspect} && !({write}))))",
        ]
    )
    if require_target_exchange:
        clauses.append("F(target_exchange_executed)")
    return " && ".join(clauses)


def _action_disjunction(actions: tuple[str, ...]) -> str:
    return " || ".join(f"call_{action}" for action in actions)


def evaluate_batch(state: RetailState, calls: list[ToolCall]) -> BatchEvaluation:
    candidate = state.clone()
    symbols: set[str] = set()
    errors: list[str] = []
    results: list[ToolResult] = []
    aggregate: dict[str, dict[str, bool]] = defaultdict(dict)

    for call in calls:
        if call.name not in TOOL_NAMES:
            symbols.add("unknown_tool")
            errors.append(f"{call.name}: unknown tool")
            continue

        symbols.add(f"call_{call.name}")
        policy = ACTION_POLICIES[call.name]
        try:
            arguments = call.parsed_arguments()
        except json.JSONDecodeError:
            symbols.add("malformed_arguments")
            errors.append(f"{call.name}: arguments are not valid JSON")
            continue

        argument_error = _argument_error(arguments, policy.fields)
        if argument_error:
            symbols.add("malformed_arguments")
            errors.append(f"{call.name}: {argument_error}")
            continue

        conditions = policy.validator(candidate, arguments)
        action_aggregate = aggregate[call.name]
        for condition, value in conditions.items():
            action_aggregate[condition] = (
                action_aggregate.get(condition, True) and value
            )

        failed = [condition for condition, value in conditions.items() if not value]
        if failed:
            errors.append(f"{call.name}: failed {', '.join(failed)}")
            continue

        try:
            output = execute_retail_tool(candidate, call.name, arguments)
        except (KeyError, RetailToolError, StopIteration, ValueError) as exc:
            symbols.add("preflight_failed")
            errors.append(f"{call.name}: preflight failed: {exc}")
            continue
        results.append(ToolResult(call.call_id, output))
        if call.name in AUTHENTICATION_ACTIONS:
            symbols.add("authentication_succeeded")
        if _is_target_exchange(call.name, arguments):
            symbols.add("target_exchange_executed")

    for action, conditions in aggregate.items():
        for condition, value in conditions.items():
            if value:
                symbols.add(proposition(action, condition))

    if errors:
        return BatchEvaluation(symbols, None, [], errors)
    return BatchEvaluation(symbols, candidate, results, [])


def _argument_error(arguments: Any, fields: dict[str, type]) -> str | None:
    if not isinstance(arguments, dict):
        return "arguments must be an object"
    if set(arguments) != set(fields):
        return "arguments must contain exactly: " + ", ".join(fields)
    for name, expected_type in fields.items():
        value = arguments[name]
        if not isinstance(value, expected_type):
            return f"{name} must be {expected_type.__name__}"
        if expected_type is list and any(not isinstance(item, str) for item in value):
            return f"every item in {name} must be a string"
    return None


def _is_target_exchange(name: str, arguments: dict[str, Any]) -> bool:
    return name == "exchange_delivered_order_items" and arguments == {
        "order_id": DELIVERED_ORDER_ID,
        "item_ids": [TARGET_OLD_ITEM_ID],
        "new_item_ids": [TARGET_NEW_ITEM_ID],
        "payment_method_id": TARGET_PAYMENT_METHOD_ID,
    }
