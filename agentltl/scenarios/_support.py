from __future__ import annotations

from ..runtime import Console
from ..spot_verifier import SpotVerifier
from ..types import (
    InputContext,
    ToolCall,
    ToolResult,
    UserAction,
    VerifierDecision,
)


class SpotScenarioBridge:
    """Dumb default bridge for scenarios backed by ``SpotVerifier``.

    Each tool name is a verifier symbol, the terminal valuation is empty, and
    accepted calls receive dummy success outputs so the agent can observe that
    they passed the gate. Scenarios with additional behavior must override the
    corresponding bridge methods explicitly in their module.
    """

    def __init__(self, *, verifier: SpotVerifier, console: Console) -> None:
        self.verifier = verifier
        self.console = console

    def verify_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> VerifierDecision:
        symbols = {call.name for call in calls}
        return self.verifier.verify_transition(batch_id, symbols)

    async def execute_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> list[ToolResult]:
        del batch_id
        return [
            ToolResult(
                call_id=call.call_id,
                output={
                    "ok": True,
                    "status": "executed",
                    "tool": call.name,
                },
            )
            for call in calls
        ]

    def verify_halt(self) -> VerifierDecision:
        return self.verifier.verify_halt(set())

    async def next_user_action(self, context: InputContext) -> UserAction:
        del context
        message = self.console.prompt_for_user()
        if message is None:
            return UserAction.abort()
        if message:
            return UserAction.user_message(message, already_displayed=True)
        return UserAction.request_halt()
