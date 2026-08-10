from __future__ import annotations

import argparse
import os

from ..agent_loop import AgentLoop, INSTRUCTIONS
from ..runtime import Runtime
from ..scenario import Scenario, register_scenario
from ..spot_verifier import SpotVerifier
from ._support import SpotScenarioBridge, placeholder_results, tool_names_as_symbols


COIN_COUNT = 6
COIN_TOOLS = [
    {
        "type": "function",
        "name": f"coin_{number}",
        "description": f"Select coin {number} for weighting",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    }
    for number in range(1, COIN_COUNT + 1)
]


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@register_scenario("coin_game")
class CoinScenario(Scenario):
    def __init__(self, *, true_coin: int = 5, autonomous: bool = False) -> None:
        super().__init__()
        if true_coin not in range(1, COIN_COUNT + 1):
            raise ValueError(f"true_coin must be between 1 and {COIN_COUNT}.")
        self.true_coin = true_coin
        self.autonomous = autonomous

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--true-coin",
            type=int,
            default=int(os.getenv("AGENT_COIN_TRUE", "5")),
            choices=range(1, COIN_COUNT + 1),
            help="coin accepted by the verifier (default: AGENT_COIN_TRUE or 5)",
        )
        parser.add_argument(
            "--autonomous",
            action="store_true",
            default=_env_bool("AGENT_COIN_AUTONOMOUS"),
            help="run without prompting for user input",
        )

    @classmethod
    def from_parsed_args(cls, args: argparse.Namespace) -> CoinScenario:
        return cls(true_coin=args.true_coin, autonomous=args.autonomous)

    def create_agent_loop(self, runtime: Runtime) -> AgentLoop:
        names = [f"coin_{number}" for number in range(1, COIN_COUNT + 1)]
        true_name = f"coin_{self.true_coin}"
        any_coin = " || ".join(names)
        exact_true_coin = " && ".join(
            name if name == true_name else f"!{name}" for name in names
        )
        verifier = SpotVerifier(
            formula=f"G ({true_name} U !({any_coin})) && F ({exact_true_coin})"
        )
        bridge = SpotScenarioBridge(
            verifier=verifier,
            console=runtime.console,
            map_symbols=tool_names_as_symbols,
            execute_tools=placeholder_results,
            autonomous=self.autonomous,
        )
        instructions = (
            f"{INSTRUCTIONS.rstrip()}\n\n"
            "You are within a game. Each available tool represents a coin. When "
            "you use a set of tools, all coins in that set are weighed. The verifier "
            "accepts only proposals consistent with the one true coin. Continue "
            "weighing until you identify and weigh only the true coin. Minimize the "
            "number of steps."
        )
        return AgentLoop(
            provider=runtime.provider,
            bridge=bridge,
            tools=COIN_TOOLS,
            instructions=instructions,
            console=runtime.console,
            max_turns=runtime.settings.max_turns,
        )
