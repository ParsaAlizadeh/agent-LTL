from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from ..runtime import Console
from ..spot_verifier import SpotVerifier
from ..types import (
    InputContext,
    InputPhase,
    ToolCall,
    ToolResult,
    UserAction,
    VerifierDecision,
)


SymbolMapper = Callable[[list[ToolCall]], set[str]]
ToolExecutor = Callable[[str, list[ToolCall]], Awaitable[list[ToolResult]]]
TerminalSymbolProvider = Callable[[], set[str]]


class SpotScenarioBridge:
    """Reusable bridge for the bundled scenarios.

    A scenario supplies every mapping and handler explicitly when it constructs
    this object; the agent loop never receives the verifier itself.
    """

    def __init__(
        self,
        *,
        verifier: SpotVerifier,
        console: Console,
        map_symbols: SymbolMapper,
        execute_tools: ToolExecutor,
        terminal_symbols: TerminalSymbolProvider = set,
        autonomous: bool = False,
    ) -> None:
        self.verifier = verifier
        self.console = console
        self.map_symbols = map_symbols
        self.execute_tools = execute_tools
        self.terminal_symbols = terminal_symbols
        self.autonomous = autonomous

    def verify_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> VerifierDecision:
        return self.verifier.verify_transition(batch_id, self.map_symbols(calls))

    async def execute_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> list[ToolResult]:
        return await self.execute_tools(batch_id, calls)

    def verify_halt(self) -> VerifierDecision:
        return self.verifier.verify_halt(self.terminal_symbols())

    async def next_user_action(self, context: InputContext) -> UserAction:
        if self.autonomous:
            if context.phase is InputPhase.INITIAL:
                return UserAction.continue_autonomously()
            return UserAction.request_halt()

        message = self.console.prompt_for_user()
        if message is None:
            return UserAction.abort()
        if message:
            return UserAction.user_message(message)
        return UserAction.request_halt()


def tool_names_as_symbols(calls: list[ToolCall]) -> set[str]:
    return {call.name for call in calls}


async def placeholder_results(
    batch_id: str, calls: list[ToolCall]
) -> list[ToolResult]:
    del batch_id
    results: list[ToolResult] = []
    for call in calls:
        try:
            arguments = call.parsed_arguments()
        except json.JSONDecodeError as exc:
            output = {
                "ok": False,
                "status": "invalid_arguments",
                "error": str(exc),
            }
        else:
            output = {
                "ok": True,
                "status": "executed",
                "tool": call.name,
                "arguments": arguments,
                "message": f"Placeholder implementation for {call.name} completed.",
            }
        results.append(ToolResult(call_id=call.call_id, output=output))
    return results
