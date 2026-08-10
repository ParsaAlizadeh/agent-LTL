from __future__ import annotations

import argparse
import asyncio
import io
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from agentltl.agent_loop import AgentLoop
from agentltl.cli import _parse_args
from agentltl.runtime import Console, Runtime, Settings, prepare_default_runtime
from agentltl.scenario import Scenario, scenario_class_for, scenario_names
from agentltl.scenarios import (
    AlternateRecordsScenario,
    CloseAfterOpenScenario,
    CoinScenario,
)
from agentltl.spot_verifier import SpotVerifier
from agentltl.types import (
    InputContext,
    ToolCall,
    ToolResult,
    UserAction,
    VerifierDecision,
)


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeProvider:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = list(responses or [])
        self.histories: list[list[dict[str, Any]]] = []

    async def respond(self, *, history, instructions, tools):
        del instructions, tools
        self.histories.append(history)
        return self.responses.pop(0)


def make_runtime(provider: Any | None = None) -> Runtime:
    return Runtime(
        console=Console(use_color=False, stream=io.StringIO()),
        settings=Settings(max_turns=5),
        client=FakeClient(),  # type: ignore[arg-type]
        provider=provider or FakeProvider(),
    )


def response_with_call(call_id: str = "call_1", name: str = "work") -> Any:
    return SimpleNamespace(
        output=[
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": '{"value": 1}',
            }
        ],
        output_text="",
    )


def response_without_calls() -> Any:
    return SimpleNamespace(output=[], output_text="done")


def test_prepare_default_runtime_only_returns_runtime(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr("agentltl.runtime.create_client", lambda settings: client)

    settings = Settings(model="development-model")
    console = Console(use_color=False, stream=io.StringIO())
    runtime = prepare_default_runtime(settings=settings, console=console)

    assert runtime.settings is settings
    assert runtime.console is console
    assert runtime.client is client
    assert runtime.provider is not None
    assert not hasattr(runtime, "loop")
    assert not hasattr(runtime, "verifier")

    asyncio.run(runtime.aclose())
    assert client.closed


def test_scenario_base_main_delegates_all_loop_initialization():
    class FakeLoop:
        def __init__(self) -> None:
            self.ran = False

        async def run(self) -> None:
            self.ran = True

    class CompleteControlScenario(Scenario):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value
            self.created_with = None

        def create_agent_loop(self, runtime: Runtime) -> AgentLoop:
            self.created_with = runtime
            return FakeLoop()  # type: ignore[return-value]

    runtime = make_runtime()
    scenario = CompleteControlScenario("from-init")
    asyncio.run(scenario.main(runtime))

    assert scenario.value == "from-init"
    assert scenario.created_with is runtime
    assert scenario.loop is not None
    assert scenario.loop.ran  # type: ignore[attr-defined]


def test_scenario_can_replace_global_settings():
    class ConfiguringScenario(Scenario):
        def configure_global_settings(self, settings: Settings) -> Settings:
            return replace(settings, max_turns=7)

        def create_agent_loop(self, runtime: Runtime) -> AgentLoop:
            raise AssertionError("not needed")

    updated = ConfiguringScenario().configure_global_settings(Settings())
    assert updated.max_turns == 7


def test_cli_selects_python_scenario_and_supplies_its_arguments():
    args = _parse_args(
        ["--scenario", "coin_5", "--true-coin", "3", "--autonomous"]
    )
    scenario = args.scenario_class.from_parsed_args(args)

    assert isinstance(scenario, CoinScenario)
    assert scenario.true_coin == 3
    assert scenario.autonomous is True


def test_cli_uses_scenario_environment(monkeypatch):
    monkeypatch.setenv("AGENT_SCENARIO", "close_after_open")
    args = _parse_args([])
    assert args.scenario_class is CloseAfterOpenScenario


def test_bundled_scenarios_are_registered():
    assert scenario_names() == ["alternate", "close_after_open", "coin_5"]
    assert scenario_class_for("alternate") is AlternateRecordsScenario


def test_spot_verifier_accepts_scenario_defined_state_symbols():
    verifier = SpotVerifier("F ready")
    decision = verifier.verify_transition(
        "batch_0001", {"renamed_tool", "environment_ready", "ready"}
    )
    assert decision.allowed


def test_spot_verifier_supports_terminal_symbols():
    with_terminal = SpotVerifier("G terminal").verify_halt({"terminal"})
    without_terminal = SpotVerifier("G terminal").verify_halt(set())

    assert with_terminal.allowed
    assert not without_terminal.allowed


def test_bundled_scenarios_construct_their_verifier_and_loop():
    runtime = make_runtime()
    for scenario in (
        CloseAfterOpenScenario(),
        AlternateRecordsScenario(),
        CoinScenario(),
    ):
        loop = scenario.create_agent_loop(runtime)
        assert isinstance(loop, AgentLoop)
        assert hasattr(loop.bridge, "verifier")


class RecordingBridge:
    def __init__(
        self,
        *,
        decisions: list[VerifierDecision],
        actions: list[UserAction],
        result_output: Any = "normal tool output",
    ) -> None:
        self.decisions = list(decisions)
        self.actions = list(actions)
        self.result_output = result_output
        self.verified_calls: list[list[ToolCall]] = []
        self.executed_calls: list[list[ToolCall]] = []
        self.input_contexts: list[InputContext] = []

    def verify_tool_batch(self, batch_id, calls):
        del batch_id
        self.verified_calls.append(calls)
        return self.decisions.pop(0)

    async def execute_tool_batch(self, batch_id, calls):
        del batch_id
        self.executed_calls.append(calls)
        return [
            ToolResult(call_id=call.call_id, output=self.result_output)
            for call in calls
        ]

    def verify_halt(self):
        return VerifierDecision(allowed=True)

    async def next_user_action(self, context):
        self.input_contexts.append(context)
        return self.actions.pop(0)


def test_accepted_results_are_supplied_by_scenario_without_mutation():
    provider = FakeProvider([response_with_call()])
    bridge = RecordingBridge(
        decisions=[VerifierDecision(allowed=True)],
        actions=[UserAction.continue_autonomously(), UserAction.request_halt()],
        result_output="plain provider-compatible output",
    )
    loop = AgentLoop(
        provider=provider,
        bridge=bridge,
        tools=[],
        console=make_runtime().console,
        max_turns=2,
    )

    asyncio.run(loop.run())

    tool_outputs = [
        item for item in loop.history if item.get("type") == "function_call_output"
    ]
    assert tool_outputs == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "plain provider-compatible output",
        }
    ]


def test_rejected_batch_uses_fixed_loop_response_and_is_not_executed():
    provider = FakeProvider([response_with_call(), response_without_calls()])
    bridge = RecordingBridge(
        decisions=[
            VerifierDecision(allowed=False, message="symbol policy rejected it"),
            VerifierDecision(allowed=True),
        ],
        actions=[UserAction.continue_autonomously(), UserAction.request_halt()],
    )
    loop = AgentLoop(
        provider=provider,
        bridge=bridge,
        tools=[],
        console=make_runtime().console,
        max_turns=3,
    )

    asyncio.run(loop.run())

    assert len(bridge.executed_calls) == 1
    assert bridge.executed_calls[0] == []
    assert len(bridge.input_contexts) == 2
    rejected_output = next(
        item
        for item in loop.history
        if item.get("type") == "function_call_output"
    )
    assert "rejected_before_execution" in rejected_output["output"]
    assert "symbol policy rejected it" not in rejected_output["output"]
    assert any(
        "symbol policy rejected it" in item.get("content", "")
        for item in loop.history
        if item.get("role") == "user"
    )


def test_bridge_maps_tool_calls_before_the_verifier():
    class RecordingVerifier:
        def __init__(self) -> None:
            self.symbols = None

        def verify_transition(self, batch_id, symbols):
            del batch_id
            self.symbols = symbols
            return VerifierDecision(allowed=True)

        def verify_halt(self, terminal_symbols=None):
            return VerifierDecision(allowed=True)

    from agentltl.scenarios._support import SpotScenarioBridge

    verifier = RecordingVerifier()
    bridge = SpotScenarioBridge(
        verifier=verifier,  # type: ignore[arg-type]
        console=make_runtime().console,
        map_symbols=lambda calls: {"state_ready", f"action_{calls[0].name}"},
        execute_tools=lambda batch_id, calls: None,  # type: ignore[arg-type]
    )
    bridge.verify_tool_batch(
        "batch_0001", [ToolCall("call_1", "open", "{}")]
    )

    assert verifier.symbols == {"state_ready", "action_open"}
