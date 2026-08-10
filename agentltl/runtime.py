from __future__ import annotations

import os
import sys
import textwrap
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from .types import ResponseProvider


DEFAULT_API_URL = "http://127.0.0.1:11434/v1"
DEFAULT_API_KEY = "ollama"
DEFAULT_MODEL = "gemma4:e2b"
DEFAULT_MAX_TURNS = 50
DEFAULT_MAX_OUTPUT_TOKENS = 2048
DEFAULT_REQUEST_TIMEOUT_SECONDS = 180.0


@dataclass(frozen=True)
class Settings:
    api_url: str = DEFAULT_API_URL
    api_key: str = DEFAULT_API_KEY
    model: str = DEFAULT_MODEL
    proxy_url: str | None = None
    max_turns: int = DEFAULT_MAX_TURNS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    temperature: float | None = None
    hide_reasoning: bool = False
    list_tool_names: bool = True
    hide_tool_input: bool = True
    hide_tool_output: bool = True

    def __post_init__(self) -> None:
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2.")


class OpenAIResponsesProvider:
    """Thin wrapper around an OpenAI-compatible Responses API."""

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
        request: dict[str, Any] = {
            "model": self._settings.model,
            "instructions": instructions,
            "input": history,
            "tools": tools,
            "stream": False,
            "max_output_tokens": self._settings.max_output_tokens,
        }
        if self._settings.temperature is not None:
            request["temperature"] = self._settings.temperature
        return await self._client.responses.create(**request)


class Console:
    COLORS = {
        "black": "\033[1;30m",
        "red": "\033[1;31m",
        "green": "\033[1;32m",
        "yellow": "\033[1;33m",
        "blue": "\033[1;34m",
        "purple": "\033[1;35m",
        "cyan": "\033[1;36m",
        "white": "\033[1;37m",
    }
    RESET = "\033[0m"
    ROLES = {
        "User": COLORS["blue"],
        "Assistant": COLORS["green"],
        "Tool": COLORS["purple"],
        "Verifier": COLORS["red"],
        "Log": COLORS["yellow"],
    }

    def __init__(self, *, use_color: bool = True, stream: Any = None) -> None:
        self.use_color = use_color
        self.stream = stream or sys.stdout
        self.width = 70

    def _make_prefix(self, role: str, color: str) -> str:
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

    def prompt_for_user(self) -> str | None:
        prefix = self._make_prefix("User", self.ROLES["User"])
        print("-" * 90, file=self.stream, flush=True)
        try:
            return input(f"{prefix} ").strip()
        except KeyboardInterrupt:
            print(file=self.stream, flush=True)
            return None

    def print(self, message: str) -> None:
        output = "\n".join(textwrap.wrap(message))
        print(output, file=self.stream, flush=True)


@dataclass(frozen=True)
class Runtime:
    console: Console
    settings: Settings
    client: AsyncOpenAI
    provider: ResponseProvider

    async def aclose(self) -> None:
        await self.client.close()

    async def __aenter__(self) -> Runtime:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()


def make_env_settings() -> Settings:
    """Build settings from the current environment at call time."""

    return Settings(
        api_url=os.getenv("AGENT_API_URL", DEFAULT_API_URL),
        api_key=os.getenv("AGENT_API_KEY", DEFAULT_API_KEY),
        model=os.getenv("AGENT_MODEL", DEFAULT_MODEL),
        proxy_url=os.getenv("AGENT_PROXY_URL"),
        max_turns=int(os.getenv("AGENT_MAX_TURNS", str(DEFAULT_MAX_TURNS))),
        max_output_tokens=int(
            os.getenv("AGENT_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS))
        ),
        request_timeout_seconds=float(
            os.getenv(
                "AGENT_REQUEST_TIMEOUT", str(DEFAULT_REQUEST_TIMEOUT_SECONDS)
            )
        ),
        temperature=(
            float(os.environ["AGENT_TEMPERATURE"])
            if "AGENT_TEMPERATURE" in os.environ
            else None
        ),
        hide_reasoning=_env_bool("AGENT_HIDE_REASONING", False),
        list_tool_names=_env_bool("AGENT_LIST_TOOL_NAMES", True),
        hide_tool_input=_env_bool("AGENT_HIDE_TOOL_INPUT", True),
        hide_tool_output=_env_bool("AGENT_HIDE_TOOL_OUTPUT", True),
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


def create_client(settings: Settings) -> AsyncOpenAI:
    kwargs: dict[str, Any] = {
        "api_key": settings.api_key,
        "base_url": settings.api_url,
        "timeout": settings.request_timeout_seconds,
    }
    if settings.proxy_url:
        kwargs["http_client"] = DefaultAsyncHttpxClient(
            proxy=settings.proxy_url,
            timeout=settings.request_timeout_seconds,
        )
    return AsyncOpenAI(**kwargs)


def prepare_default_runtime(
    *,
    settings: Settings | None = None,
    console: Console | None = None,
) -> Runtime:
    """Create and return the scenario-independent default runtime.

    This function deliberately does not construct a verifier, an agent loop, or
    a scenario. The returned runtime owns its client and can be used as an async
    context manager to close that client.
    """

    resolved_settings = settings or make_env_settings()
    resolved_console = console or Console()
    client = create_client(resolved_settings)
    provider = OpenAIResponsesProvider(client, resolved_settings)
    return Runtime(
        console=resolved_console,
        settings=resolved_settings,
        client=client,
        provider=provider,
    )
