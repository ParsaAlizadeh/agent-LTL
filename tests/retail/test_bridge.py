from __future__ import annotations

import asyncio
import io
import json

from agentltl.runtime import Console
from agentltl.scenarios.retail.bridge import RetailBridge
from agentltl.scenarios.retail.data import (
    PENDING_ORDER_ID,
    PRIMARY_USER_ID,
    human_user_card_lines,
    make_retail_db,
)
from agentltl.scenarios.retail.policy import retail_formula
from agentltl.scenarios.retail.tools import RetailState
from agentltl.spot_verifier import SpotVerifier
from agentltl.types import (
    InputContext,
    InputPhase,
    ToolCall,
    UserActionKind,
)


def call(name: str, arguments: dict, call_id: str) -> ToolCall:
    return ToolCall(call_id, name, json.dumps(arguments))


def make_bridge() -> RetailBridge:
    return RetailBridge(
        verifier=SpotVerifier(retail_formula()),
        console=Console(use_color=False, stream=io.StringIO()),
        state=RetailState(make_retail_db()),
    )


def authenticate(bridge: RetailBridge) -> None:
    calls = [
        call(
            "find_user_id_by_email",
            {"email": "alice@example.com"},
            "call_auth",
        )
    ]
    assert bridge.verify_tool_batch("auth", calls).allowed
    asyncio.run(bridge.execute_tool_batch("auth", calls))


def inspect_order(bridge: RetailBridge, order_id: str, batch_id: str) -> None:
    calls = [
        call(
            "get_order_details",
            {"order_id": order_id},
            f"call_{batch_id}",
        )
    ]
    assert bridge.verify_tool_batch(batch_id, calls).allowed
    asyncio.run(bridge.execute_tool_batch(batch_id, calls))


def test_rejected_multi_write_batch_does_not_partially_mutate_live_database():
    bridge = make_bridge()
    authenticate(bridge)
    inspect_order(bridge, PENDING_ORDER_ID, "inspect")
    calls = [
        call(
            "cancel_pending_order",
            {"order_id": PENDING_ORDER_ID, "reason": "no longer needed"},
            "call_cancel_1",
        ),
        call(
            "cancel_pending_order",
            {"order_id": PENDING_ORDER_ID, "reason": "ordered by mistake"},
            "call_cancel_2",
        ),
    ]

    decision = bridge.verify_tool_batch("double_cancel", calls)

    assert not decision.allowed
    assert bridge.db.orders[PENDING_ORDER_ID].status == "pending"
    assert bridge.db.orders[PENDING_ORDER_ID].cancel_reason is None


def test_accepted_write_commits_only_during_execution():
    bridge = make_bridge()
    authenticate(bridge)
    inspect_order(bridge, PENDING_ORDER_ID, "inspect")
    calls = [
        call(
            "cancel_pending_order",
            {"order_id": PENDING_ORDER_ID, "reason": "no longer needed"},
            "call_cancel",
        )
    ]

    assert bridge.verify_tool_batch("cancel", calls).allowed
    assert bridge.db.orders[PENDING_ORDER_ID].status == "pending"
    results = asyncio.run(bridge.execute_tool_batch("cancel", calls))

    assert bridge.db.orders[PENDING_ORDER_ID].status == "cancelled"
    assert results[0].output["status"] == "cancelled"


def test_tool_batch_continues_without_prompting_the_user():
    def fail_prompt():
        raise AssertionError("the user should not be prompted after a tool batch")

    bridge = make_bridge()
    bridge.console.prompt_for_user = fail_prompt
    context = InputContext(
        phase=InputPhase.AFTER_ACCEPTED_BATCH,
        history=[],
        calls=(
            call(
                "get_user_details",
                {"user_id": PRIMARY_USER_ID},
                "call_1",
            ),
        ),
    )

    action = asyncio.run(bridge.next_user_action(context))

    assert action.kind is UserActionKind.CONTINUE


def test_text_only_response_prompts_the_user():
    bridge = make_bridge()
    bridge.console.prompt_for_user = lambda: "Please continue."
    context = InputContext(
        phase=InputPhase.AFTER_ACCEPTED_BATCH,
        history=[],
    )

    action = asyncio.run(bridge.next_user_action(context))

    assert action.kind is UserActionKind.MESSAGE
    assert action.message == "Please continue."


def test_initial_private_data_is_rendered_as_separate_log_entries():
    bridge = make_bridge()
    bridge.console.prompt_for_user = lambda: "Start."

    action = asyncio.run(
        bridge.next_user_action(
            InputContext(phase=InputPhase.INITIAL, history=[])
        )
    )

    output = bridge.console.stream.getvalue()
    assert action.kind is UserActionKind.MESSAGE
    assert output.count("[    Log     ]:") == len(human_user_card_lines())
    for line in human_user_card_lines():
        assert line in output
