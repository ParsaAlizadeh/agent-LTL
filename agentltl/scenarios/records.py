from __future__ import annotations

from ..agent_loop import AgentLoop, INSTRUCTIONS
from ..runtime import Runtime
from ..scenario import Scenario, register_scenario
from ..spot_verifier import SpotVerifier
from ._support import SpotScenarioBridge


RECORD_TOOLS = [
    {
        "type": "function",
        "name": "open",
        "description": "Open the record's file",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Short description of why the record must be opened",
                }
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "close",
        "description": "Close the record's file",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Short description of why the record can be closed",
                }
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


@register_scenario("close_after_open")
class CloseAfterOpenScenario(Scenario):
    def create_agent_loop(self, runtime: Runtime) -> AgentLoop:
        verifier = SpotVerifier(
            formula="G(!(open & close)) & G(open -> X(!open U close))"
        )
        bridge = SpotScenarioBridge(
            verifier=verifier,
            console=runtime.console,
        )
        return AgentLoop(
            provider=runtime.provider,
            bridge=bridge,
            tools=RECORD_TOOLS,
            instructions=(
                f"{INSTRUCTIONS.rstrip()}\n\n"
                "When you open the record, close it before ending the procedure."
            ),
            console=runtime.console,
            settings=runtime.settings,
        )


@register_scenario("alternate")
class AlternateRecordsScenario(Scenario):
    def create_agent_loop(self, runtime: Runtime) -> AgentLoop:
        verifier = SpotVerifier(
            formula=(
                "(!close U open) & G(open -> X(!open U close)) "
                "& G(close -> X(!close W open))"
            )
        )
        bridge = SpotScenarioBridge(
            verifier=verifier,
            console=runtime.console,
        )
        return AgentLoop(
            provider=runtime.provider,
            bridge=bridge,
            tools=RECORD_TOOLS,
            instructions=INSTRUCTIONS,
            console=runtime.console,
            settings=runtime.settings,
        )
