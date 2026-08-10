from __future__ import annotations

import argparse
import asyncio
import io
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from agentltl.agent_loop import AgentLoop
from agentltl.cli import _parse_args, _settings_from_args
from agentltl.runtime import (
    Console,
    OpenAIResponsesProvider,
    Runtime,
    Settings,
    make_env_settings,
    prepare_default_runtime,
)
from agentltl.scenario import Scenario, scenario_class_for, scenario_names
from agentltl.scenarios import (
    AlternateRecordsScenario,
    CloseAfterOpenScenario,
    CoinScenario,
)
from agentltl.scenarios.coin_game import weight_calls_to_symbols
from agentltl.spot_verifier import SpotVerifier
from agentltl.types import (
    InputContext,
    InputPhase,
    ToolCall,
    ToolResult,
    UserAction,
    UserActionKind,
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


def test_provider_omits_default_temperature_and_sends_explicit_zero():
    class RecordingResponses:
        def __init__(self) -> None:
            self.requests = []

        async def create(self, **request):
            self.requests.append(request)
            return SimpleNamespace()

    class RecordingClient:
        def __init__(self) -> None:
            self.responses = RecordingResponses()

    async def respond(provider):
        await provider.respond(
            history=[{"role": "user", "content": "test"}],
            instructions="test instructions",
            tools=[],
        )

    default_client = RecordingClient()
    explicit_client = RecordingClient()
    asyncio.run(
        respond(
            OpenAIResponsesProvider(
                default_client,  # type: ignore[arg-type]
                Settings(),
            )
        )
    )
    asyncio.run(
        respond(
            OpenAIResponsesProvider(
                explicit_client,  # type: ignore[arg-type]
                Settings(temperature=0),
            )
        )
    )

    assert "temperature" not in default_client.responses.requests[0]
    assert explicit_client.responses.requests[0]["temperature"] == 0


def test_temperature_can_come_from_environment_or_cli(monkeypatch):
    monkeypatch.setenv("AGENT_TEMPERATURE", "0.25")
    assert make_env_settings().temperature == 0.25

    args = _parse_args(
        ["--scenario", "close_after_open", "--temperature", "0"]
    )
    assert _settings_from_args(args).temperature == 0


def test_agent_loop_display_options_come_from_global_settings():
    settings = Settings(
        max_turns=7,
        hide_reasoning=True,
        list_tool_names=False,
        hide_tool_input=False,
        hide_tool_output=False,
    )
    loop = AgentLoop(
        provider=FakeProvider(),
        bridge=RecordingBridge(decisions=[], actions=[]),
        tools=[],
        console=Console(use_color=False, stream=io.StringIO()),
        settings=settings,
    )

    assert loop.max_turns == 7
    assert loop.opt_hide_reasoning is True
    assert loop.opt_list_tool_names is False
    assert loop.opt_hide_tool_input is False
    assert loop.opt_hide_tool_output is False


def test_display_options_can_come_from_environment_or_cli(monkeypatch):
    monkeypatch.setenv("AGENT_HIDE_REASONING", "true")
    monkeypatch.setenv("AGENT_LIST_TOOL_NAMES", "false")
    monkeypatch.setenv("AGENT_HIDE_TOOL_INPUT", "false")
    monkeypatch.setenv("AGENT_HIDE_TOOL_OUTPUT", "false")
    env_settings = make_env_settings()

    assert env_settings.hide_reasoning is True
    assert env_settings.list_tool_names is False
    assert env_settings.hide_tool_input is False
    assert env_settings.hide_tool_output is False

    args = _parse_args(
        [
            "--scenario",
            "close_after_open",
            "--no-hide-reasoning",
            "--list-tool-names",
            "--hide-tool-input",
            "--hide-tool-output",
        ]
    )
    cli_settings = _settings_from_args(args)
    assert cli_settings.hide_reasoning is False
    assert cli_settings.list_tool_names is True
    assert cli_settings.hide_tool_input is True
    assert cli_settings.hide_tool_output is True


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
        [
            "--scenario",
            "coin_game",
            "--n",
            "8",
            "--true-coin",
            "3",
        ]
    )
    scenario = args.scenario_class.from_parsed_args(args)

    assert isinstance(scenario, CoinScenario)
    assert scenario.n == 8
    assert scenario.true_coin == 3


def test_cli_uses_scenario_environment(monkeypatch):
    monkeypatch.setenv("AGENT_SCENARIO", "close_after_open")
    args = _parse_args([])
    assert args.scenario_class is CloseAfterOpenScenario


def test_bundled_scenarios_are_registered():
    assert scenario_names() == ["alternate", "close_after_open", "coin_game"]
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


def test_coin_game_exposes_one_weight_tool_for_n_coins():
    loop = CoinScenario(n=8, true_coin=3).create_agent_loop(make_runtime())

    assert [tool["name"] for tool in loop.tools] == ["weight"]
    coins_schema = loop.tools[0]["parameters"]["properties"]["coins"]
    assert coins_schema["type"] == "array"
    assert coins_schema["items"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 8,
    }


def test_coin_game_configures_detailed_tool_call_display():
    scenario = CoinScenario(n=6, true_coin=3)
    settings = scenario.configure_global_settings(Settings())
    assert settings.list_tool_names is False
    assert settings.hide_tool_input is False
    stream = io.StringIO()
    runtime = Runtime(
        console=Console(use_color=False, stream=stream),
        settings=settings,
        client=FakeClient(),  # type: ignore[arg-type]
        provider=FakeProvider(),
    )
    loop = scenario.create_agent_loop(runtime)

    loop._display_tool_calls(
        [ToolCall("call_1", "weight", '{"coins": [1, 2, 3]}')]
    )

    assert "weight({ coins: [1,2,3]})" in stream.getvalue()


def test_coin_game_maps_weight_arguments_to_coin_symbols():
    call = ToolCall("call_1", "weight", '{"coins": [1, 3, 4]}')

    assert weight_calls_to_symbols([call], 6) == {
        "coin_1",
        "coin_3",
        "coin_4",
    }


def test_coin_game_supplies_its_own_weight_result():
    loop = CoinScenario(n=6, true_coin=3).create_agent_loop(make_runtime())
    call = ToolCall("call_1", "weight", '{"coins": [1, 3, 4]}')

    results = asyncio.run(loop.bridge.execute_tool_batch("batch_0001", [call]))

    assert results == [
        ToolResult(
            call_id="call_1",
            output={"ok": True, "status": "weighted", "coins": [1, 3, 4]},
        )
    ]


def test_coin_game_redacts_tool_and_halt_verifier_feedback():
    loop = CoinScenario(n=6, true_coin=3).create_agent_loop(make_runtime())
    rejected_call = ToolCall("call_1", "weight", '{"coins": [1, 2]}')

    tool_decision = loop.bridge.verify_tool_batch("batch_0001", [rejected_call])
    halt_decision = loop.bridge.verify_halt()

    assert not tool_decision.allowed
    assert tool_decision.message is None
    assert not halt_decision.allowed
    assert halt_decision.message is None


def test_coin_game_starts_with_synthetic_input_and_remains_autonomous():
    loop = CoinScenario(n=6, true_coin=3).create_agent_loop(make_runtime())
    initial = asyncio.run(
        loop.bridge.next_user_action(
            InputContext(phase=InputPhase.INITIAL, history=[])
        )
    )
    after_weight = asyncio.run(
        loop.bridge.next_user_action(
            InputContext(phase=InputPhase.AFTER_ACCEPTED_BATCH, history=[])
        )
    )

    assert initial.kind is UserActionKind.MESSAGE
    assert initial.message == "Begin the coin game."
    assert after_weight.kind is UserActionKind.REQUEST_HALT


def test_coin_game_first_provider_request_has_non_empty_input():
    provider = FakeProvider(
        [
            SimpleNamespace(
                output=[
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "weight",
                        "arguments": '{"coins": [3]}',
                    }
                ],
                output_text="",
            )
        ]
    )
    runtime = make_runtime(provider)
    loop = CoinScenario(n=6, true_coin=3).create_agent_loop(runtime)

    asyncio.run(loop.run())

    assert provider.histories[0] == [
        {"role": "user", "content": "Begin the coin game."}
    ]
    assert "Begin the coin game." in runtime.console.stream.getvalue()


def test_coin_game_only_halts_after_weighting_the_true_coin_alone():
    bridge = CoinScenario(n=6, true_coin=3).create_agent_loop(make_runtime()).bridge

    group_decision = bridge.verify_tool_batch(
        "batch_0001",
        [ToolCall("call_1", "weight", '{"coins": [1, 3, 4]}')],
    )
    premature_halt = bridge.verify_halt()
    exact_decision = bridge.verify_tool_batch(
        "batch_0002",
        [ToolCall("call_2", "weight", '{"coins": [3]}')],
    )
    final_halt = bridge.verify_halt()

    assert group_decision.allowed
    assert not premature_halt.allowed
    assert premature_halt.message is None
    assert exact_decision.allowed
    assert final_halt.allowed


def test_coin_count_controls_default_true_coin():
    scenario = CoinScenario(n=3)
    assert scenario.true_coin == 3


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


def test_default_spot_bridge_maps_tool_names_and_supplies_dummy_results():
    class RecordingVerifier:
        def __init__(self) -> None:
            self.symbols = None
            self.terminal_symbols = None

        def verify_transition(self, batch_id, symbols):
            del batch_id
            self.symbols = symbols
            return VerifierDecision(allowed=True)

        def verify_halt(self, terminal_symbols=None):
            self.terminal_symbols = terminal_symbols
            return VerifierDecision(allowed=True)

    from agentltl.scenarios._support import SpotScenarioBridge

    verifier = RecordingVerifier()
    bridge = SpotScenarioBridge(
        verifier=verifier,  # type: ignore[arg-type]
        console=make_runtime().console,
    )
    calls = [ToolCall("call_1", "open", "{}")]
    bridge.verify_tool_batch("batch_0001", calls)
    results = asyncio.run(bridge.execute_tool_batch("batch_0001", calls))
    bridge.verify_halt()

    assert verifier.symbols == {"open"}
    assert verifier.terminal_symbols == set()
    assert results == [
        ToolResult(
            call_id="call_1",
            output={"ok": True, "status": "executed", "tool": "open"},
        )
    ]
