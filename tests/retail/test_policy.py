from __future__ import annotations

import json

import pytest

from agentltl.scenarios.retail.data import (
    DELIVERED_ORDER_ID,
    DUPLICATE_OPTIONS_ITEM_ID,
    LOW_BALANCE_CARD_ID,
    OTHER_USER_ORDER_ID,
    OTHER_USER_CARD_ID,
    PENDING_ORDER_ID,
    PRIMARY_USER_ID,
    PROCESSED_ORDER_ID,
    SHOE_ALTERNATIVE_ITEM_ID,
    SHIRT_PRODUCT_ID,
    TARGET_NEW_ITEM_ID,
    TARGET_OLD_ITEM_ID,
    TARGET_PAYMENT_METHOD_ID,
    UNAVAILABLE_ITEM_ID,
    make_retail_db,
)
from agentltl.scenarios.retail.policy import (
    ACTION_POLICIES,
    evaluate_batch,
    proposition,
    retail_formula,
)
from agentltl.scenarios.retail.tools import RETAIL_TOOLS, RetailState
from agentltl.spot_verifier import SpotVerifier
from agentltl.types import ToolCall


def call(name: str, arguments: dict, call_id: str = "call_1") -> ToolCall:
    return ToolCall(call_id, name, json.dumps(arguments))


def authenticated_state() -> RetailState:
    return RetailState(make_retail_db(), PRIMARY_USER_ID)


def valid_exchange(**changes) -> dict:
    arguments = {
        "order_id": DELIVERED_ORDER_ID,
        "item_ids": [TARGET_OLD_ITEM_ID],
        "new_item_ids": [TARGET_NEW_ITEM_ID],
        "payment_method_id": TARGET_PAYMENT_METHOD_ID,
    }
    arguments.update(changes)
    return arguments


def apply_accepted_call(
    verifier: SpotVerifier,
    state: RetailState,
    tool_call: ToolCall,
    batch_id: str,
) -> RetailState:
    evaluation = evaluate_batch(state, [tool_call])
    assert evaluation.errors == []
    assert evaluation.next_state is not None
    assert verifier.verify_transition(batch_id, evaluation.symbols).allowed
    return evaluation.next_state


def test_all_fixture_identifiers_are_opaque_decimal_strings():
    db = make_retail_db()

    identifiers = [*db.users, *db.orders, *db.products]
    identifiers.extend(
        method_id
        for user in db.users.values()
        for method_id in user.payment_methods
    )
    identifiers.extend(
        item_id
        for product in db.products.values()
        for item_id in product.variants
    )

    assert identifiers
    assert all(identifier.isdecimal() for identifier in identifiers)


def test_every_exposed_tool_has_a_formal_action_policy():
    assert {tool["name"] for tool in RETAIL_TOOLS} == set(ACTION_POLICIES)


def test_valid_exchange_has_every_declared_grounded_proposition():
    evaluation = evaluate_batch(
        authenticated_state(),
        [call("exchange_delivered_order_items", valid_exchange())],
    )
    conditions = ACTION_POLICIES["exchange_delivered_order_items"].conditions
    expected = {
        "call_exchange_delivered_order_items",
        "target_exchange_executed",
        *(proposition("exchange_delivered_order_items", item) for item in conditions),
    }

    assert evaluation.errors == []
    assert evaluation.next_state is not None
    assert evaluation.symbols == expected
    order = evaluation.next_state.db.orders[DELIVERED_ORDER_ID]
    assert order.status == "exchange requested"
    assert order.exchange_price_difference == 5.0


@pytest.mark.parametrize(
    ("changes", "missing_condition"),
    [
        ({"order_id": OTHER_USER_ORDER_ID}, "order_owned_by_authenticated_user"),
        ({"order_id": "#MISSING"}, "order_exists"),
        ({"item_ids": ["missing"]}, "items_in_order_with_multiplicity"),
        ({"new_item_ids": []}, "item_lists_nonempty"),
        ({"new_item_ids": [TARGET_OLD_ITEM_ID]}, "replacements_are_different"),
        (
            {"new_item_ids": [DUPLICATE_OPTIONS_ITEM_ID]},
            "replacement_options_different",
        ),
        (
            {"new_item_ids": [SHOE_ALTERNATIVE_ITEM_ID]},
            "replacements_same_product",
        ),
        ({"new_item_ids": [UNAVAILABLE_ITEM_ID]}, "replacements_available"),
        (
            {"new_item_ids": [SHOE_ALTERNATIVE_ITEM_ID, TARGET_NEW_ITEM_ID]},
            "replacement_count_matches",
        ),
        (
            {"payment_method_id": OTHER_USER_CARD_ID},
            "payment_method_exists_for_order_owner",
        ),
        (
            {
                "new_item_ids": [SHOE_ALTERNATIVE_ITEM_ID],
                "payment_method_id": LOW_BALANCE_CARD_ID,
            },
            "gift_card_balance_sufficient",
        ),
    ],
)
def test_invalid_exchange_omits_the_exact_failed_proposition(
    changes, missing_condition
):
    evaluation = evaluate_batch(
        authenticated_state(),
        [call("exchange_delivered_order_items", valid_exchange(**changes))],
    )

    assert evaluation.next_state is None
    assert proposition("exchange_delivered_order_items", missing_condition) not in (
        evaluation.symbols
    )


def test_reads_require_authentication_and_enforce_ownership():
    unauthenticated = evaluate_batch(
        RetailState(make_retail_db()),
        [call("get_order_details", {"order_id": DELIVERED_ORDER_ID})],
    )
    cross_user = evaluate_batch(
        authenticated_state(),
        [call("get_order_details", {"order_id": OTHER_USER_ORDER_ID})],
    )

    assert proposition(
        "get_order_details", "order_owned_by_authenticated_user"
    ) not in (
        unauthenticated.symbols
    )
    assert proposition(
        "get_order_details", "order_owned_by_authenticated_user"
    ) not in cross_user.symbols


@pytest.mark.parametrize(
    ("arguments", "condition"),
    [
        (
            {"order_id": PROCESSED_ORDER_ID, "reason": "no longer needed"},
            "order_status_pending",
        ),
        (
            {"order_id": "#MISSING", "reason": "no longer needed"},
            "order_exists",
        ),
        (
            {"order_id": OTHER_USER_ORDER_ID, "reason": "ordered by mistake"},
            "order_owned_by_authenticated_user",
        ),
        (
            {"order_id": DELIVERED_ORDER_ID, "reason": "changed my mind"},
            "reason_allowed",
        ),
    ],
)
def test_cancel_requires_owned_pending_order_and_allowed_reason(arguments, condition):
    evaluation = evaluate_batch(
        authenticated_state(), [call("cancel_pending_order", arguments)]
    )

    assert evaluation.next_state is None
    assert proposition("cancel_pending_order", condition) not in evaluation.symbols


def test_authentication_and_protected_read_must_use_separate_batches():
    evaluation = evaluate_batch(
        RetailState(make_retail_db()),
        [
            call(
                "find_user_id_by_email",
                {"email": "alice@example.com"},
                "call_auth",
            ),
            call(
                "get_order_details",
                {"order_id": DELIVERED_ORDER_ID},
                "call_read",
            ),
        ],
    )

    assert evaluation.errors == []
    assert evaluation.next_state is not None
    assert evaluation.next_state.authenticated_user_id == PRIMARY_USER_ID
    assert not SpotVerifier(retail_formula()).verify_transition(
        "combined", evaluation.symbols
    ).allowed


def test_successful_authentication_cannot_repeat_in_a_later_batch():
    verifier = SpotVerifier(retail_formula())
    state = apply_accepted_call(
        verifier,
        RetailState(make_retail_db()),
        call("find_user_id_by_email", {"email": "alice@example.com"}),
        "first_auth",
    )
    second = evaluate_batch(
        state,
        [call("find_user_id_by_email", {"email": "bob@example.com"})],
    )

    assert second.next_state is not None
    assert second.next_state.authenticated_user_id != state.authenticated_user_id
    assert not verifier.verify_transition("second_auth", second.symbols).allowed


def test_authentication_uses_weak_until_at_halt():
    verifier = SpotVerifier(retail_formula())
    protected_read = evaluate_batch(
        RetailState(make_retail_db()),
        [call("get_product_details", {"product_id": SHIRT_PRODUCT_ID})],
    )

    assert verifier.verify_halt().allowed
    assert not verifier.verify_transition(
        "read_before_auth", protected_read.symbols
    ).allowed


def test_malformed_and_unknown_calls_are_explicit_symbols():
    malformed = evaluate_batch(
        authenticated_state(),
        [ToolCall("call_1", "get_order_details", "not-json")],
    )
    unknown = evaluate_batch(
        authenticated_state(), [call("delete_everything", {})]
    )

    assert "malformed_arguments" in malformed.symbols
    assert "unknown_tool" in unknown.symbols


def test_generated_formula_rejects_invalid_exchange_and_accepts_valid_exchange():
    verifier = SpotVerifier(retail_formula())
    state = apply_accepted_call(
        verifier,
        RetailState(make_retail_db()),
        call("find_user_id_by_email", {"email": "alice@example.com"}),
        "auth",
    )
    state = apply_accepted_call(
        verifier,
        state,
        call("get_order_details", {"order_id": DELIVERED_ORDER_ID}),
        "inspect",
    )
    invalid = evaluate_batch(
        state,
        [
            call(
                "exchange_delivered_order_items",
                valid_exchange(new_item_ids=[SHOE_ALTERNATIVE_ITEM_ID]),
            )
        ],
    )
    valid = evaluate_batch(
        state,
        [call("exchange_delivered_order_items", valid_exchange())],
    )

    assert not verifier.verify_transition("invalid", invalid.symbols).allowed
    assert verifier.verify_transition("valid", valid.symbols).allowed


def test_write_requires_inspection_before_first_and_consecutive_writes():
    verifier = SpotVerifier(retail_formula())
    state = apply_accepted_call(
        verifier,
        RetailState(make_retail_db()),
        call("find_user_id_by_email", {"email": "alice@example.com"}),
        "auth",
    )
    cancel_call = call(
        "cancel_pending_order",
        {"order_id": PENDING_ORDER_ID, "reason": "no longer needed"},
    )
    premature_cancel = evaluate_batch(state, [cancel_call])
    assert not verifier.verify_transition(
        "cancel_without_inspection", premature_cancel.symbols
    ).allowed

    state = apply_accepted_call(
        verifier,
        state,
        call("get_order_details", {"order_id": PENDING_ORDER_ID}),
        "inspect_pending",
    )
    state = apply_accepted_call(verifier, state, cancel_call, "cancel")

    exchange = evaluate_batch(
        state,
        [call("exchange_delivered_order_items", valid_exchange())],
    )
    assert not verifier.verify_transition(
        "exchange_without_new_inspection", exchange.symbols
    ).allowed

    state = apply_accepted_call(
        verifier,
        state,
        call("get_order_details", {"order_id": DELIVERED_ORDER_ID}),
        "inspect_delivered",
    )
    apply_accepted_call(
        verifier,
        state,
        call("exchange_delivered_order_items", valid_exchange()),
        "exchange",
    )


def test_target_goal_rejects_early_halt_and_accepts_halt_after_target_exchange():
    verifier = SpotVerifier(retail_formula(require_target_exchange=True))
    state = apply_accepted_call(
        verifier,
        RetailState(make_retail_db()),
        call("find_user_id_by_email", {"email": "alice@example.com"}),
        "auth",
    )
    state = apply_accepted_call(
        verifier,
        state,
        call("get_order_details", {"order_id": DELIVERED_ORDER_ID}),
        "inspect",
    )
    evaluation = evaluate_batch(
        state,
        [call("exchange_delivered_order_items", valid_exchange())],
    )

    assert not verifier.verify_halt().allowed
    assert verifier.verify_transition("exchange", evaluation.symbols).allowed
    assert verifier.verify_halt().allowed
