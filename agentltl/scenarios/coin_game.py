from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace

from ..agent_loop import AgentLoop, INSTRUCTIONS
from ..runtime import Console, Runtime, Settings
from ..scenario import Scenario, register_scenario
from ..spot_verifier import SpotVerifier
from ..types import (
    InputContext,
    InputPhase,
    ToolCall,
    ToolResult,
    UserAction,
    VerifierDecision,
)
from ._support import SpotScenarioBridge


DEFAULT_COIN_COUNT = 6


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def weight_tool(n: int) -> dict:
    return {
        "type": "function",
        "name": "weight",
        "description": "Weight a selected set of numbered coins",
        "parameters": {
            "type": "object",
            "properties": {
                "coins": {
                    "type": "array",
                    "description": f"Unique coin numbers between 1 and {n}",
                    "items": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": n,
                    },
                    "minItems": 1,
                }
            },
            "required": ["coins"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def _coins_from_call(call: ToolCall, n: int) -> list[int]:
    if call.name != "weight":
        raise ValueError(f"Unknown coin-game tool: {call.name!r}.")

    arguments = call.parsed_arguments()
    if not isinstance(arguments, dict) or set(arguments) != {"coins"}:
        raise ValueError("weight arguments must contain only 'coins'.")

    coins = arguments["coins"]
    if not isinstance(coins, list) or not coins:
        raise ValueError("weight.coins must be a non-empty list.")
    if any(isinstance(coin, bool) or not isinstance(coin, int) for coin in coins):
        raise ValueError("Every weighted coin must be an integer.")
    if len(coins) != len(set(coins)):
        raise ValueError("Weighted coin numbers must be unique.")
    if any(coin < 1 or coin > n for coin in coins):
        raise ValueError(f"Weighted coin numbers must be between 1 and {n}.")
    return coins


def weight_calls_to_symbols(calls: list[ToolCall], n: int) -> set[str]:
    return {
        f"coin_{coin}"
        for call in calls
        for coin in _coins_from_call(call, n)
    }


class CoinGameBridge(SpotScenarioBridge):
    """Coin-game bridge that never exposes verifier-generated hints."""

    def __init__(
        self, *, verifier: SpotVerifier, console: Console, n: int
    ) -> None:
        super().__init__(verifier=verifier, console=console)
        self.n = n

    def verify_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> VerifierDecision:
        try:
            symbols = weight_calls_to_symbols(calls, self.n)
        except (json.JSONDecodeError, ValueError):
            return VerifierDecision(allowed=False, message=None)
        decision = self.verifier.verify_transition(batch_id, symbols)
        return VerifierDecision(allowed=decision.allowed, message=None)

    async def execute_tool_batch(
        self, batch_id: str, calls: list[ToolCall]
    ) -> list[ToolResult]:
        del batch_id
        return [
            ToolResult(
                call_id=call.call_id,
                output={
                    "ok": True,
                    "status": "weighted",
                    "coins": _coins_from_call(call, self.n),
                },
            )
            for call in calls
        ]

    def verify_halt(self) -> VerifierDecision:
        decision = self.verifier.verify_halt(set())
        return VerifierDecision(allowed=decision.allowed, message=None)

    async def next_user_action(self, context: InputContext) -> UserAction:
        if context.phase is InputPhase.INITIAL:
            return UserAction.user_message("Begin the coin game.")
        return UserAction.request_halt()


@register_scenario("coin_game")
class CoinScenario(Scenario):
    def __init__(
        self,
        *,
        n: int = DEFAULT_COIN_COUNT,
        true_coin: int | None = None,
    ) -> None:
        super().__init__()
        if n < 1:
            raise ValueError("n must be at least 1.")

        resolved_true_coin = min(5, n) if true_coin is None else true_coin
        if resolved_true_coin not in range(1, n + 1):
            raise ValueError(f"true_coin must be between 1 and {n}.")

        self.n = n
        self.true_coin = resolved_true_coin

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--n",
            type=_positive_int,
            default=int(os.getenv("AGENT_COIN_N", str(DEFAULT_COIN_COUNT))),
            help="number of coins (default: AGENT_COIN_N or 6)",
        )
        true_coin_default = os.getenv("AGENT_COIN_TRUE")
        parser.add_argument(
            "--true-coin",
            type=_positive_int,
            default=int(true_coin_default) if true_coin_default else None,
            help="hidden true coin (default: AGENT_COIN_TRUE or min(5, n))",
        )

    @classmethod
    def from_parsed_args(cls, args: argparse.Namespace) -> CoinScenario:
        return cls(n=args.n, true_coin=args.true_coin)

    def configure_global_settings(self, settings: Settings) -> Settings:
        return replace(
            settings,
            list_tool_names=False,
            hide_tool_input=False,
        )

    def _formula(self) -> str:
        names = [f"coin_{number}" for number in range(1, self.n + 1)]
        true_name = f"coin_{self.true_coin}"
        any_coin = " || ".join(names)
        exact_true_coin = " && ".join(
            name if name == true_name else f"!{name}" for name in names
        )
        return f"G ({true_name} U !({any_coin})) && F ({exact_true_coin})"

    def create_agent_loop(self, runtime: Runtime) -> AgentLoop:
        verifier = SpotVerifier(formula=self._formula())
        bridge = CoinGameBridge(
            verifier=verifier,
            console=runtime.console,
            n=self.n,
        )
        instructions = (
            f"{INSTRUCTIONS.rstrip()}\n\n"
            f"You are playing a game with {self.n} numbered coins. Exactly one is "
            "the true coin. Use the weight tool to weigh any selected subset. A "
            "rejected proposal means the true coin was not in that subset; an "
            "accepted proposal means it was. Continue until you weigh only the "
            "true coin. Minimize the number of weighings."
        )
        return AgentLoop(
            provider=runtime.provider,
            bridge=bridge,
            tools=[weight_tool(self.n)],
            instructions=instructions,
            console=runtime.console,
            settings=runtime.settings,
        )
