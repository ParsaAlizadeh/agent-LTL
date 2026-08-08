from .types import ToolCall, VerifierDecision
from dataclasses import dataclass, field

@dataclass
class PlaceholderVerifier:
    """Example policy: tool_a must run at least once and tool_b may never run."""

    known_tools: set[str]
    executed_tool_names: list[str] = field(default_factory=list)

    def verify_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> VerifierDecision:
        del batch_id  # Available for real verifier logging/correlation.
        unknown = sorted({call.name for call in calls} - self.known_tools)
        if unknown:
            return VerifierDecision(
                allowed=False,
                message=f"Unknown tools are not allowed: {', '.join(unknown)}.",
            )

        if any(call.name == "tool_b" for call in calls):
            return VerifierDecision(
                allowed=False,
                message=(
                    "The complete tool batch was rejected because tool_b is forbidden. "
                    "No tool in this batch was executed. Choose a path that does not "
                    "request tool_b."
                ),
            )

        for call in calls:
            self.executed_tool_names.append(call.name)

        return VerifierDecision(allowed=True)


    def verify_halt(self) -> VerifierDecision:
        if "tool_a" not in self.executed_tool_names:
            return VerifierDecision(
                allowed=False,
                message=(
                    "Halting is not allowed yet: tool_a must be successfully called "
                    "at least once. Continue the procedure and request tool_a."
                ),
            )
        return VerifierDecision(allowed=True)
