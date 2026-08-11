from __future__ import annotations

import argparse
from dataclasses import replace

from ...agent_loop import AgentLoop
from ...runtime import Runtime, Settings
from ...scenario import Scenario, register_scenario
from ...spot_verifier import SpotVerifier
from .bridge import RetailBridge
from .data import make_retail_db
from .instructions import RETAIL_INSTRUCTIONS
from .policy import retail_formula
from .tools import RETAIL_TOOLS, RetailState


@register_scenario("retail")
class RetailScenario(Scenario):
    def __init__(self, *, require_target_exchange: bool = False) -> None:
        super().__init__()
        self.require_target_exchange = require_target_exchange

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--require-target-exchange",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="reject halt until the fixture's designated exchange executes",
        )

    @classmethod
    def from_parsed_args(cls, args: argparse.Namespace) -> RetailScenario:
        return cls(require_target_exchange=args.require_target_exchange)

    def configure_global_settings(self, settings: Settings) -> Settings:
        return replace(
            settings,
            list_tool_names=False,
            hide_tool_input=False,
            hide_tool_output=False,
        )

    def create_agent_loop(self, runtime: Runtime) -> AgentLoop:
        verifier = SpotVerifier(
            retail_formula(require_target_exchange=self.require_target_exchange)
        )
        bridge = RetailBridge(
            verifier=verifier,
            console=runtime.console,
            state=RetailState(make_retail_db()),
        )
        return AgentLoop(
            provider=runtime.provider,
            bridge=bridge,
            tools=RETAIL_TOOLS,
            instructions=RETAIL_INSTRUCTIONS,
            console=runtime.console,
            settings=runtime.settings,
        )


__all__ = ["RetailBridge", "RetailScenario"]
