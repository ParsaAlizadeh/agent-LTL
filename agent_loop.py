from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Protocol
import textwrap

from openai import AsyncOpenAI, DefaultAsyncHttpxClient


# Provider configuration. Environment variables and matching CLI flags can
# override these defaults without changing the loop.
API_URL = os.getenv("AGENT_API_URL", "http://127.0.0.1:11434/v1")
API_KEY = os.getenv("AGENT_API_KEY", "ollama")
MODEL = os.getenv("AGENT_MODEL", "gemma4:e2b")
PROXY_URL = os.getenv("AGENT_PROXY_URL")
MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "50"))
MAX_OUTPUT_TOKENS = int(os.getenv("AGENT_MAX_OUTPUT_TOKENS", "2048"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("AGENT_REQUEST_TIMEOUT", "180"))


# Edit this list to define the only tools visible to the model. Each
# ``parameters`` value is a JSON Schema describing that tool's input.
ABSTRACT_TOOL_PARAMETER = {
    "type": "object",
    "properties": {
        "reason": {
            "type": "string",
            "description": "short description of why you called this tool.",
        }
    },
    "required": ["reason"],
    "additionalProperties": False,
}

def _make_tool(name, description):
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": copy.deepcopy(ABSTRACT_TOOL_PARAMETER),
        "strict": True
    }

TOOLS: list[dict[str, Any]] = [
    _make_tool("tool_a", "record A type checkpoint"),
    _make_tool("tool_b", "record B type checkpoint")
]

INSTRUCTIONS = """\
You are an agent completing a procedure with the supplied tools.
Only request tools that are listed in the request. Tool calls are proposals:
the whole proposed batch is checked before any tool executes. If the verifier
rejects a batch, no tool in that batch ran. Read the verifier feedback, choose a
valid alternative, and continue. Acknowledge tool call failures in your response.
"""


@dataclass(frozen=True)
class Settings:
    api_url: str = API_URL
    api_key: str = API_KEY
    model: str = MODEL
    proxy_url: str | None = PROXY_URL
    max_turns: int = MAX_TURNS
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS


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

    def record_tool_execution(self, call: ToolCall) -> None: ...

    def verify_halt(self) -> VerifierDecision: ...


class OpenAIResponsesProvider:
    """Thin wrapper around the provider's OpenAI-compatible Responses API."""

    def __init__(self, client: AsyncOpenAI, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def respond(
        self,
        *,
        history: list[dict[str, Any]],
        instructions: str,
        tools: list[dict[str, Any]],
    ) -> Any:
        return await self._client.responses.create(
            model=self._settings.model,
            instructions=instructions,
            input=history,
            tools=tools,
            stream=False,
            max_output_tokens=self._settings.max_output_tokens,
        )


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

        return VerifierDecision(allowed=True)

    def record_tool_execution(self, call: ToolCall) -> None:
        self.executed_tool_names.append(call.name)

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


class Console:
    COLORS = {
        "black":    "\033[1;30m",
        "red":      "\033[1;31m",
        "green":    "\033[1;32m",
        "yellow":   "\033[1;33m",
        "blue":     "\033[1;34m",
        "purple":   "\033[1;35m",
        "cyan":     "\033[1;36m",
        "white":    "\033[1;37m"
    }
    RESET = "\033[0m"
    ROLES = {
        "User":         COLORS["blue"],
        "Assistant":    COLORS["green"],
        "Tool":         COLORS["purple"],
        "Verifier":     COLORS["red"],
        "Log":          COLORS["yellow"]
    }

    def __init__(self, *, use_color: bool = True, stream: Any = None) -> None:
        self.use_color = use_color
        self.stream = stream or sys.stdout
        self.width = 70

    def _make_prefix(self, role, color):
        prefix = f"[{role:^12}]:"
        if self.use_color:
            prefix = f"{color}{prefix}{self.RESET}"
        return prefix

    def _write(self, role: str, message: str) -> None:
        prefix = self._make_prefix(role, self.ROLES[role])
        self.print(f"{prefix} {message}")

    def user(self, message: str) -> None:
        self._write("User", message)

    def assistant(self, message: str) -> None:
        self._write("Assistant", message)

    def tool(self, message: str) -> None:
        self._write("Tool", message)

    def verifier(self, message: str) -> None:
        self._write("Verifier", message)

    def log(self, message: str) -> None:
        self._write("Log", message)

    def prompt_for_user(self) -> str:
        prefix = self._make_prefix('User', self.ROLES['User'])
        print('-' * 90)
        return input(f"{prefix} ").strip()

    def print(self, message):
        output = '\n'.join(textwrap.wrap(message))
        print(output, file=self.stream, flush=True)


async def execute_placeholder_tool(call: ToolCall) -> dict[str, Any]:
    """Replace this function with the actual abstract action implementation."""

    try:
        arguments = call.parsed_arguments()
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "status": "invalid_arguments",
            "error": str(exc),
        }

    return {
        "ok": True,
        "status": "executed",
        "tool": call.name,
        "arguments": arguments,
        "message": f"Placeholder implementation for {call.name} completed.",
    }


class AgentLoop:
    def __init__(
        self,
        *,
        provider: ResponseProvider,
        verifier: Verifier,
        tools: list[dict[str, Any]],
        instructions: str = INSTRUCTIONS,
        console: Console | None = None,
        max_turns: int = MAX_TURNS,
    ) -> None:
        self.provider = provider
        self.verifier = verifier
        self.tools = tools
        self.instructions = instructions
        self.console = console or Console()
        self.max_turns = max_turns
        self.history: list[dict[str, Any]] = []
        self._batch_number = 0

    async def run(self) -> str:
        turns = 0

        initial_user_message = self.console.prompt_for_user()
        self._append_user_message(initial_user_message)

        while turns < self.max_turns:
            turns += 1

            response = await self.provider.respond(
                history=copy.deepcopy(self.history),
                instructions=self.instructions,
                tools=self.tools,
            )

            output_items = [_item_to_dict(item) for item in response.output]
            self.history.extend(output_items)

            reasoning_texts = [
                summary.text
                for item in response.output
                if item.type == "reasoning"
                for summary in item.summary
            ]
            self.console.assistant('[Reasoning]\n' + '\n'.join(reasoning_texts))

            assistant_text = _response_text(response, output_items)
            self.console.assistant(assistant_text or "[no text]")

            calls = _extract_tool_calls(output_items)

            for call in calls:
                self.console.tool(
                    f"{call.name} call_id={call.call_id} arguments={call.arguments_json}"
                )

            self._batch_number += 1
            batch_id = f"batch_{self._batch_number:04d}"
            decision = self.verifier.verify_tool_batch(batch_id, calls)

            if not decision.allowed:
                error = decision.message or "The verifier rejected this tool batch."
                self.console.verifier(f"{batch_id} rejected: {error}")

                for call in calls:
                    payload = {
                        "ok": False,
                        "status": "rejected_before_execution",
                        "batch_id": batch_id,
                        "tool": call.name,
                    }
                    self._append_tool_output(call, payload)

                feedback = (
                    f"[Verifier decision {batch_id}]\n"
                    "The complete proposed tool batch was rejected. No action in the "
                    f"batch was executed.\n{error}"
                )
                self._append_user_message(feedback)
                continue

            self.console.verifier(f"{batch_id} accepted. Proceed to execute.")
            for call in calls:
                payload = await execute_placeholder_tool(call)
                payload["batch_id"] = batch_id
                self._append_tool_output(call, payload)

            user_message = self.console.prompt_for_user()
            if user_message.strip():
                self._append_user_message(user_message)
                continue

            halt_decision = self.verifier.verify_halt()
            if halt_decision.allowed:
                self.console.verifier("Halting accepted.")
                break

            error = halt_decision.message or "The verifier rejected halting."
            self.console.verifier(f"Halting rejected: {error}")
            feedback = (
                "[Verifier halt rejection]\n"
                f"{error}\n"
            )
            self._append_user_message(feedback)

        self.console.log(f'Conversation complete.')

    def _append_tool_output(self, call: ToolCall, payload: dict[str, Any]) -> None:
        output = {
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": json.dumps(payload, sort_keys=True),
        }
        self.history.append(output)
        self.console.tool(
            f"Result for {call.name} call_id={call.call_id}: {output['output']}"
        )

    def _append_user_message(self, message: str) -> None:
        self.history.append({"role": "user", "content": message})


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


def create_client(settings: Settings) -> AsyncOpenAI:
    kwargs: dict[str, Any] = {
        "api_key": settings.api_key,
        "base_url": settings.api_url,
        "timeout": settings.request_timeout_seconds,
    }
    if settings.proxy_url:
        # Explicit override for environments where proxy discovery is undesirable
        # or unavailable. Without this override, OpenAI's HTTPX client reads the
        # standard HTTP_PROXY/http_proxy, HTTPS_PROXY/https_proxy and NO_PROXY vars.
        kwargs["http_client"] = DefaultAsyncHttpxClient(
            proxy=settings.proxy_url,
            timeout=settings.request_timeout_seconds,
        )
    return AsyncOpenAI(**kwargs)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the agent"
    )
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--api-key", default=API_KEY)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--proxy", default=PROXY_URL)
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS)
    parser.add_argument("--max-output-tokens", type=int, default=MAX_OUTPUT_TOKENS)
    parser.add_argument("--request-timeout", type=float, default=REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--no-color", action="store_true")
    return parser.parse_args()


def make_env_settings() -> Settings:
    return Settings(
        api_url=API_URL,
        api_key=API_KEY,
        model=MODEL,
        proxy_url=PROXY_URL,
        max_turns=MAX_TURNS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        request_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
    )


async def _async_main() -> None:
    args = _parse_args()
    console = Console(use_color=not args.no_color)

    settings = Settings(
        api_url=args.api_url,
        api_key=args.api_key,
        model=args.model,
        proxy_url=args.proxy,
        max_turns=args.max_turns,
        max_output_tokens=args.max_output_tokens,
        request_timeout_seconds=args.request_timeout,
    )

    client = create_client(settings)
    try:
        provider = OpenAIResponsesProvider(client, settings)
        verifier = PlaceholderVerifier(
            known_tools={tool["name"] for tool in TOOLS}
        )
        loop = AgentLoop(
            provider=provider,
            verifier=verifier,
            tools=TOOLS,
            console=console,
            max_turns=settings.max_turns,
        )
        await loop.run()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(_async_main())
