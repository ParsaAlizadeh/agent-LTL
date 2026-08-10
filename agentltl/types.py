from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, TypeAlias


JSONValue: TypeAlias = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments_json: str
    item_id: str | None = None

    def parsed_arguments(self) -> Any:
        return json.loads(self.arguments_json)


@dataclass(frozen=True)
class ToolResult:
    """The scenario-supplied output for one accepted tool call."""

    call_id: str
    output: str | JSONValue


@dataclass(frozen=True)
class VerifierDecision:
    allowed: bool
    message: str | None = None


class InputPhase(str, Enum):
    INITIAL = "initial"
    AFTER_ACCEPTED_BATCH = "after_accepted_batch"


@dataclass(frozen=True)
class InputContext:
    phase: InputPhase
    history: list[dict[str, Any]]
    calls: tuple[ToolCall, ...] = ()
    results: tuple[ToolResult, ...] = ()


class UserActionKind(str, Enum):
    MESSAGE = "message"
    CONTINUE = "continue"
    REQUEST_HALT = "request_halt"
    ABORT = "abort"


@dataclass(frozen=True)
class UserAction:
    kind: UserActionKind
    message: str | None = None
    already_displayed: bool = False

    @classmethod
    def user_message(
        cls, message: str, *, already_displayed: bool = False
    ) -> UserAction:
        return cls(UserActionKind.MESSAGE, message, already_displayed)

    @classmethod
    def continue_autonomously(cls) -> UserAction:
        return cls(UserActionKind.CONTINUE)

    @classmethod
    def request_halt(cls) -> UserAction:
        return cls(UserActionKind.REQUEST_HALT)

    @classmethod
    def abort(cls) -> UserAction:
        return cls(UserActionKind.ABORT)


class ResponseProvider(Protocol):
    async def respond(
        self,
        *,
        history: list[dict[str, Any]],
        instructions: str,
        tools: list[dict[str, Any]],
    ) -> Any: ...


class AgentLoopBridge(Protocol):
    """Scenario-controlled boundary between an agent loop and its environment."""

    def verify_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> VerifierDecision: ...

    async def execute_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> list[ToolResult]: ...

    def verify_halt(self) -> VerifierDecision: ...

    async def next_user_action(self, context: InputContext) -> UserAction: ...


class Verifier(Protocol):
    def verify_transition(
        self, batch_id: str, symbols: set[str]
    ) -> VerifierDecision: ...

    def verify_halt(
        self, terminal_symbols: set[str] | None = None
    ) -> VerifierDecision: ...
