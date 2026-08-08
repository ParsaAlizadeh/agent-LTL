from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ScenarioError(ValueError):
    """Raised when a scenario file is missing required or valid data."""


@dataclass(frozen=True)
class ToolParameter:
    name: str
    description: str

    def to_api_schema(self) -> dict[str, str]:
        return {
            "type": "string",
            "description": self.description,
        }


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: tuple[ToolParameter, ...]
    required: tuple[str, ...]

    def to_api_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    parameter.name: parameter.to_api_schema()
                    for parameter in self.parameters
                },
                "required": list(self.required),
                "additionalProperties": False,
            },
            "strict": True,
        }


@dataclass(frozen=True)
class ScenarioDefinition:
    name: str
    formula: str
    instructions: str | None = None


@dataclass(frozen=True)
class ScenarioConfig:
    tools: tuple[ToolDefinition, ...]
    scenarios: tuple[ScenarioDefinition, ...]

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    def api_tools(self) -> list[dict[str, Any]]:
        return [tool.to_api_tool() for tool in self.tools]

    def scenario_for(self, name: str) -> ScenarioDefinition:
        for scenario in self.scenarios:
            if scenario.name == name:
                return scenario

        available = ", ".join(scenario.name for scenario in self.scenarios)
        suffix = f" Available scenarios: {available}." if available else ""
        raise ScenarioError(f"Scenario {name!r} is not defined.{suffix}")

    def formula_for(self, name: str) -> str:
        return self.scenario_for(name).formula


def load_scenario(path: str | Path) -> ScenarioConfig:
    """Read and validate a TOML scenario configuration."""

    scenario_path = Path(path)
    try:
        with scenario_path.open("rb") as scenario_file:
            data = tomllib.load(scenario_file)
    except OSError as exc:
        raise ScenarioError(
            f"Could not read scenario file {scenario_path}: {exc}"
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ScenarioError(
            f"Could not parse scenario file {scenario_path}: {exc}"
        ) from exc

    return ScenarioConfig(
        tools=_parse_tools(data.get("tools")),
        scenarios=_parse_scenarios(data.get("scenario")),
    )


def _parse_tools(raw_tools: Any) -> tuple[ToolDefinition, ...]:
    if not isinstance(raw_tools, dict) or not raw_tools:
        raise ScenarioError("The scenario file must define at least one [tools.NAME].")

    tools: list[ToolDefinition] = []
    for name, raw_tool in raw_tools.items():
        location = f"tools.{name}"
        if not isinstance(raw_tool, dict):
            raise ScenarioError(f"[{location}] must be a TOML table.")

        description = _required_string(raw_tool, "description", location)
        if "parameters" not in raw_tool:
            raise ScenarioError(f"[{location}] must define parameters.")
        parameters = _parse_parameters(raw_tool["parameters"], location)
        parameter_names = [parameter.name for parameter in parameters]
        required = _parse_required(raw_tool.get("required"), parameter_names, location)

        tools.append(
            ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                required=required,
            )
        )

    return tuple(tools)


def _parse_scenarios(raw_scenarios: Any) -> tuple[ScenarioDefinition, ...]:
    if raw_scenarios is None:
        return ()
    if not isinstance(raw_scenarios, dict):
        raise ScenarioError("[scenario] must contain named scenario tables.")

    scenarios: list[ScenarioDefinition] = []
    for name, raw_scenario in raw_scenarios.items():
        location = f"scenario.{name}"
        if not isinstance(raw_scenario, dict):
            raise ScenarioError(f"[{location}] must be a TOML table.")
        scenarios.append(
            ScenarioDefinition(
                name=name,
                formula=_required_string(raw_scenario, "formula", location),
                instructions=_optional_string(
                    raw_scenario, "instructions", location
                ),
            )
        )
    return tuple(scenarios)


def _required_string(table: dict[str, Any], field: str, location: str) -> str:
    value = table.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ScenarioError(f"{location}.{field} must be a non-empty string.")
    return value


def _optional_string(
    table: dict[str, Any], field: str, location: str
) -> str | None:
    if field not in table:
        return None
    value = table[field]
    if not isinstance(value, str):
        raise ScenarioError(f"{location}.{field} must be a string.")
    return value


def _parameter_description(name: Any, description: Any, location: str) -> str:
    if not isinstance(name, str) or not name:
        raise ScenarioError(f"{location}.parameters contains an invalid name.")
    if not isinstance(description, str) or not description.strip():
        raise ScenarioError(
            f"{location}.parameters.{name} must be a non-empty description string."
        )
    return description


def _parse_parameters(
    raw_parameters: Any, location: str
) -> tuple[ToolParameter, ...]:
    parameters: list[ToolParameter] = []
    if isinstance(raw_parameters, dict):
        parameters.extend(
            ToolParameter(
                name=parameter_name,
                description=_parameter_description(
                    parameter_name, parameter_description, location
                ),
            )
            for parameter_name, parameter_description in raw_parameters.items()
        )
    elif isinstance(raw_parameters, list):
        for index, raw_parameter in enumerate(raw_parameters):
            parameter_location = f"{location}.parameters[{index}]"
            if not isinstance(raw_parameter, dict):
                raise ScenarioError(f"{parameter_location} must be a TOML table.")
            name = _required_string(raw_parameter, "name", parameter_location)
            description = _required_string(
                raw_parameter, "description", parameter_location
            )
            parameters.append(ToolParameter(name=name, description=description))
    else:
        raise ScenarioError(
            f"{location}.parameters must be a TOML table or list of tables."
        )

    names = [parameter.name for parameter in parameters]
    if len(names) != len(set(names)):
        raise ScenarioError(f"{location}.parameters contains duplicate names.")
    return tuple(parameters)


def _parse_required(
    raw_required: Any, parameter_names: list[str], location: str
) -> tuple[str, ...]:
    if raw_required is None:
        return tuple(parameter_names)
    if not isinstance(raw_required, list) or not all(
        isinstance(name, str) for name in raw_required
    ):
        raise ScenarioError(f"{location}.required must be a list of parameter names.")
    if len(raw_required) != len(set(raw_required)):
        raise ScenarioError(f"{location}.required contains duplicate names.")

    unknown = [name for name in raw_required if name not in parameter_names]
    if unknown:
        raise ScenarioError(
            f"{location}.required references unknown parameters: {', '.join(unknown)}."
        )
    return tuple(raw_required)
