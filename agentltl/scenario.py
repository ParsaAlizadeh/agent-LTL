from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import ClassVar

from .agent_loop import AgentLoop
from .runtime import Runtime, Settings


class ScenarioError(ValueError):
    pass


class Scenario(ABC):
    """Base class for a programmatic agent scenario.

    The base class only owns orchestration. A subclass has complete control over
    verifier and agent-loop construction through ``create_agent_loop``.
    """

    registered_name: ClassVar[str | None] = None

    def __init__(self) -> None:
        self.loop: AgentLoop | None = None

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add scenario-specific CLI arguments, if any."""

    @classmethod
    def from_parsed_args(cls, args: argparse.Namespace) -> Scenario:
        """Translate CLI arguments into the subclass's normal constructor."""

        del args
        return cls()

    def configure_global_settings(self, settings: Settings) -> Settings:
        """Optionally return adjusted global settings before runtime creation."""

        return settings

    @abstractmethod
    def create_agent_loop(self, runtime: Runtime) -> AgentLoop:
        """Construct the verifier, bridge, and agent loop for this scenario."""

    async def main(self, runtime: Runtime) -> None:
        self.loop = self.create_agent_loop(runtime)
        await self.loop.run()


_SCENARIOS: dict[str, type[Scenario]] = {}


def register_scenario(name: str) -> Callable[[type[Scenario]], type[Scenario]]:
    if not name or not name.strip():
        raise ScenarioError("A scenario name must be a non-empty string.")

    normalized_name = name.strip()

    def register(scenario_class: type[Scenario]) -> type[Scenario]:
        existing = _SCENARIOS.get(normalized_name)
        if existing is not None and existing is not scenario_class:
            raise ScenarioError(f"Scenario {normalized_name!r} is already registered.")
        scenario_class.registered_name = normalized_name
        _SCENARIOS[normalized_name] = scenario_class
        return scenario_class

    return register


def scenario_class_for(name: str) -> type[Scenario]:
    try:
        return _SCENARIOS[name]
    except KeyError as exc:
        available = ", ".join(scenario_names())
        suffix = f" Available scenarios: {available}." if available else ""
        raise ScenarioError(f"Scenario {name!r} is not registered.{suffix}") from exc


def scenario_names() -> list[str]:
    return sorted(_SCENARIOS)
