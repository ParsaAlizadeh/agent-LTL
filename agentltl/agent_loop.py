from __future__ import annotations

import copy
import json
from collections import Counter
from enum import Enum
from typing import Any

from .runtime import Console
from .types import (
    AgentLoopBridge,
    InputContext,
    InputPhase,
    ResponseProvider,
    ToolCall,
    ToolResult,
    UserAction,
    UserActionKind,
)


INSTRUCTIONS = """\
You are an agent completing a procedure with the supplied tools.
Only request tools that are listed in the request. Tool calls are proposals:
the whole proposed batch is checked before any tool executes. If the verifier
rejects a batch, no tool in that batch ran. Read the verifier feedback, choose a
valid alternative, and continue. Acknowledge tool call failures in your response.
"""


class _InputOutcome(Enum):
    PROCEED = "proceed"
    HALTED = "halted"
    ABORTED = "aborted"


class AgentLoop:
    def __init__(
        self,
        *,
        provider: ResponseProvider,
        bridge: AgentLoopBridge,
        tools: list[dict[str, Any]],
        instructions: str = INSTRUCTIONS,
        console: Console | None = None,
        max_turns: int = 50,
    ) -> None:
        self.provider = provider
        self.bridge = bridge
        self.tools = tools
        self.instructions = instructions
        self.console = console or Console()
        self.max_turns = max_turns
        self.history: list[dict[str, Any]] = []
        self._batch_number = 0

        self.opt_hide_reasoning = False
        self.opt_list_tool_names = True
        self.opt_hide_tool_output = True

    async def run(self) -> None:
        initial_action = await self.bridge.next_user_action(
            self._input_context(InputPhase.INITIAL)
        )
        initial_outcome = self._handle_user_action(initial_action)
        if initial_outcome is _InputOutcome.HALTED:
            self.console.log("Conversation complete.")
            return
        if initial_outcome is _InputOutcome.ABORTED:
            self.console.log("Interrupted. Exiting.")
            return

        turns = 0
        halted = False
        while turns < self.max_turns:
            turns += 1
            response = await self.provider.respond(
                history=copy.deepcopy(self.history),
                instructions=self.instructions,
                tools=self.tools,
            )

            output_items = [_item_to_dict(item) for item in response.output]
            self.history.extend(output_items)
            self._display_response(response, output_items)

            calls = _extract_tool_calls(output_items)
            self._display_tool_calls(calls)

            self._batch_number += 1
            batch_id = f"batch_{self._batch_number:04d}"
            decision = self.bridge.verify_tool_batch(batch_id, calls)

            if not decision.allowed:
                self._record_rejection(batch_id, calls, decision.message)
                continue

            self.console.verifier(f"{batch_id} accepted. Proceed to execute.")
            results = await self.bridge.execute_tool_batch(batch_id, calls)
            ordered_results = _validate_tool_results(calls, results)
            for call, result in zip(calls, ordered_results, strict=True):
                self._append_tool_output(call, result.output)

            action = await self.bridge.next_user_action(
                self._input_context(
                    InputPhase.AFTER_ACCEPTED_BATCH,
                    calls=calls,
                    results=ordered_results,
                )
            )
            outcome = self._handle_user_action(action)
            if outcome is _InputOutcome.HALTED:
                halted = True
                break
            if outcome is _InputOutcome.ABORTED:
                self.console.log("Interrupted. Exiting.")
                return

        if halted:
            self.console.log("Conversation complete.")
        else:
            self.console.log(
                "Maximum turns reached without a verifier-approved halt."
            )

    def _display_response(
        self, response: Any, output_items: list[dict[str, Any]]
    ) -> None:
        if not self.opt_hide_reasoning:
            reasoning_texts = [
                str(summary.text)
                for item in response.output
                if getattr(item, "type", None) == "reasoning"
                for summary in getattr(item, "summary", [])
            ]
            if reasoning_texts:
                self.console.assistant("[Reasoning]\n" + "\n".join(reasoning_texts))

        assistant_text = _response_text(response, output_items)
        self.console.assistant(assistant_text or "[no text]")

    def _display_tool_calls(self, calls: list[ToolCall]) -> None:
        if self.opt_list_tool_names:
            if calls:
                self.console.tool(" ".join(call.name for call in calls))
            else:
                self.console.tool("[no tool]")
            return

        for call in calls:
            self.console.tool(
                f"{call.name} call_id={call.call_id} "
                f"arguments={call.arguments_json}"
            )

    def _record_rejection(
        self,
        batch_id: str,
        calls: list[ToolCall],
        verifier_message: str | None,
    ) -> None:
        error = verifier_message or "The verifier rejected this tool batch."
        self.console.verifier(f"{batch_id} rejected: {error}")

        for call in calls:
            self._append_tool_output(
                call,
                {
                    "ok": False,
                    "status": "rejected_before_execution",
                    "batch_id": batch_id,
                    "tool": call.name,
                },
            )

        self._append_user_message(
            f"[Verifier decision {batch_id}]\n"
            "The complete proposed tool batch was rejected. No action in the "
            f"batch was executed.\n{error}"
        )

    def _handle_user_action(self, action: UserAction) -> _InputOutcome:
        if action.kind is UserActionKind.MESSAGE:
            if action.message is None:
                raise ValueError("A user-message action must contain a message.")
            self._append_user_message(action.message)
            return _InputOutcome.PROCEED

        if action.kind is UserActionKind.CONTINUE:
            return _InputOutcome.PROCEED

        if action.kind is UserActionKind.ABORT:
            return _InputOutcome.ABORTED

        if action.kind is UserActionKind.REQUEST_HALT:
            return (
                _InputOutcome.HALTED
                if self._request_halt()
                else _InputOutcome.PROCEED
            )

        raise ValueError(f"Unsupported user action: {action.kind!r}")

    def _request_halt(self) -> bool:
        halt_decision = self.bridge.verify_halt()
        if halt_decision.allowed:
            self.console.verifier("Halting accepted.")
            return True

        error = halt_decision.message or "The verifier rejected halting."
        self.console.verifier(f"Halting rejected: {error}")
        self._append_user_message(f"[Verifier halt rejection]\n{error}\n")
        return False

    def _input_context(
        self,
        phase: InputPhase,
        *,
        calls: list[ToolCall] | None = None,
        results: list[ToolResult] | None = None,
    ) -> InputContext:
        return InputContext(
            phase=phase,
            history=copy.deepcopy(self.history),
            calls=tuple(calls or ()),
            results=tuple(results or ()),
        )

    def _append_tool_output(self, call: ToolCall, payload: Any) -> None:
        serialized = payload if isinstance(payload, str) else json.dumps(
            payload, sort_keys=True
        )
        output = {
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": serialized,
        }
        self.history.append(output)
        if not self.opt_hide_tool_output:
            self.console.tool(
                f"Result for {call.name} call_id={call.call_id}: {serialized}"
            )

    def _append_user_message(self, message: str) -> None:
        self.history.append({"role": "user", "content": message})


def _validate_tool_results(
    calls: list[ToolCall], results: list[ToolResult]
) -> list[ToolResult]:
    expected_ids = [call.call_id for call in calls]
    result_ids = [result.call_id for result in results]
    if Counter(result_ids) != Counter(expected_ids):
        missing = list((Counter(expected_ids) - Counter(result_ids)).elements())
        unexpected = list((Counter(result_ids) - Counter(expected_ids)).elements())
        details = []
        if missing:
            details.append(f"missing call IDs: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected call IDs: {', '.join(unexpected)}")
        raise RuntimeError(
            "Scenario returned invalid tool results (" + "; ".join(details) + ")."
        )

    by_call_id = {result.call_id: result for result in results}
    return [by_call_id[call_id] for call_id in expected_ids]


def _item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return copy.deepcopy(item)
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json", exclude_none=True)
    raise TypeError(f"Unsupported response output item: {type(item)!r}")


def _response_text(response: Any, output_items: list[dict[str, Any]]) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    texts: list[str] = []
    for item in output_items:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                texts.append(str(content["text"]))
    return "\n".join(texts)


def _extract_tool_calls(output_items: list[dict[str, Any]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in output_items:
        if item.get("type") != "function_call":
            continue

        call_id = item.get("call_id")
        name = item.get("name")
        arguments = item.get("arguments", "{}")
        if not call_id or not name:
            raise RuntimeError(f"Malformed function_call item: {item!r}")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments)

        calls.append(
            ToolCall(
                call_id=str(call_id),
                name=str(name),
                arguments_json=arguments,
                item_id=str(item["id"]) if item.get("id") else None,
            )
        )
    return calls
