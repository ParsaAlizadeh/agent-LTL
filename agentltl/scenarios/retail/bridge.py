from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ...runtime import Console
from ...spot_verifier import SpotVerifier
from ...types import (
    InputContext,
    InputPhase,
    ToolCall,
    ToolResult,
    UserAction,
    VerifierDecision,
)
from .data import human_user_card_lines
from .models import RetailDB
from .policy import BatchEvaluation, evaluate_batch
from .tools import RetailState


@dataclass
class _PreparedBatch:
    state: RetailState
    results: list[ToolResult]


class RetailBridge:
    def __init__(
        self,
        *,
        verifier: SpotVerifier,
        console: Console,
        state: RetailState,
    ) -> None:
        self.verifier = verifier
        self.console = console
        self.state = state
        self._prepared: dict[str, _PreparedBatch] = {}
        self._show_user_card = True

    @property
    def db(self) -> RetailDB:
        return self.state.db

    @property
    def authenticated_user_id(self) -> str | None:
        return self.state.authenticated_user_id

    def verify_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> VerifierDecision:
        self.console.verifier(
            f"{batch_id} pre-state: {_state_fingerprint(self.state)}"
        )
        evaluation = evaluate_batch(self.state, calls)
        self.console.verifier(
            f"{batch_id} valuation: "
            + (", ".join(sorted(evaluation.symbols)) or "[empty]")
        )
        decision = self.verifier.verify_transition(batch_id, evaluation.symbols)
        if not decision.allowed:
            return VerifierDecision(
                allowed=False,
                message=_rejection_message(evaluation, decision),
            )
        if evaluation.next_state is None:
            raise RuntimeError(
                "The retail formula accepted a batch that failed preflight validation."
            )
        self._prepared[batch_id] = _PreparedBatch(
            evaluation.next_state, evaluation.results
        )
        return decision

    async def execute_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> list[ToolResult]:
        del calls
        try:
            prepared = self._prepared.pop(batch_id)
        except KeyError as exc:
            raise RuntimeError(f"Batch {batch_id!r} was not prepared.") from exc
        previous = self.state
        self.state = prepared.state
        self.console.verifier(
            f"{batch_id} post-state: {_state_fingerprint(self.state)}; "
            f"changes: {_state_changes(previous, self.state)}"
        )
        return prepared.results

    def verify_halt(self) -> VerifierDecision:
        return self.verifier.verify_halt(set())

    async def next_user_action(self, context: InputContext) -> UserAction:
        if context.phase is InputPhase.INITIAL and self._show_user_card:
            for line in human_user_card_lines():
                self.console.log(line)
            self._show_user_card = False
        if (
            context.phase is InputPhase.AFTER_ACCEPTED_BATCH
            and context.calls
        ):
            return UserAction.continue_autonomously()
        message = self.console.prompt_for_user()
        if message is None:
            return UserAction.abort()
        if message:
            return UserAction.user_message(message, already_displayed=True)
        return UserAction.request_halt()


def _rejection_message(
    evaluation: BatchEvaluation, decision: VerifierDecision
) -> str | None:
    if evaluation.errors:
        return "Retail policy rejected the batch: " + "; ".join(evaluation.errors)
    return decision.message


def _state_fingerprint(state: RetailState) -> str:
    serialized = json.dumps(
        {
            "authenticated_user_id": state.authenticated_user_id,
            "db": state.db.as_dict(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()[:12]


def _state_changes(before: RetailState, after: RetailState) -> str:
    changes = []
    if before.authenticated_user_id != after.authenticated_user_id:
        changes.append(
            "authenticated_user_id=" + str(after.authenticated_user_id)
        )
    for order_id, order in after.db.orders.items():
        old_order = before.db.orders.get(order_id)
        if old_order != order:
            old_status = old_order.status if old_order is not None else "missing"
            changes.append(f"{order_id}.status={old_status}->{order.status}")
    return ", ".join(changes) or "none"
