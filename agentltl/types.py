from dataclasses import dataclass, field
from typing import Any, Protocol
import json


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments_json: str
    item_id: str | None = None

    def parsed_arguments(self) -> Any:
        return json.loads(self.arguments_json)


@dataclass(frozen=True)
class VerifierDecision:
    allowed: bool
    message: str | None = None


class ResponseProvider(Protocol):
    async def respond(
        self,
        *,
        history: list[dict[str, Any]],
        instructions: str,
        tools: list[dict[str, Any]],
    ) -> Any: ...


class Verifier(Protocol):
    def verify_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> VerifierDecision: ...

    def verify_halt(self) -> VerifierDecision: ...
