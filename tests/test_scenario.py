from __future__ import annotations

from pathlib import Path

import pytest

from agentltl.agent_loop import INSTRUCTIONS, _parse_args
from agentltl.scenario import ScenarioError, load_scenario
from agentltl.spot_verifier import SpotVerifier


def _write_scenario(tmp_path, text: str):
    path = tmp_path / "scenario.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_scenario_builds_api_tools_and_defaults_required(tmp_path):
    path = _write_scenario(
        tmp_path,
        """
[tools.publish]
description = "Publish a document"

[tools.publish.parameters]
title = "Title shown to readers"
body = "Document contents"

[scenario.reviewed]
formula = "G(publish -> F archive)"
instructions = "Keep the publication notes concise."
""",
    )

    config = load_scenario(path)

    assert config.tool_names == ["publish"]
    assert config.formula_for("reviewed") == "G(publish -> F archive)"
    assert config.scenario_for("reviewed").instructions == (
        "Keep the publication notes concise."
    )
    assert config.api_tools() == [
        {
            "type": "function",
            "name": "publish",
            "description": "Publish a document",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title shown to readers",
                    },
                    "body": {
                        "type": "string",
                        "description": "Document contents",
                    },
                },
                "required": ["title", "body"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]


def test_load_scenario_accepts_parameter_list_and_explicit_required(tmp_path):
    path = _write_scenario(
        tmp_path,
        """
[tools.publish]
description = "Publish a document"
required = ["title"]

[[tools.publish.parameters]]
name = "title"
description = "Title shown to readers"

[[tools.publish.parameters]]
name = "notes"
description = "Optional publication notes"
""",
    )

    tool = load_scenario(path).api_tools()[0]

    assert tool["parameters"]["required"] == ["title"]
    assert list(tool["parameters"]["properties"]) == ["title", "notes"]


def test_load_scenario_rejects_unknown_required_parameter(tmp_path):
    path = _write_scenario(
        tmp_path,
        """
[tools.publish]
description = "Publish a document"
parameters = { title = "Title shown to readers" }
required = ["missing"]
""",
    )

    with pytest.raises(ScenarioError, match="unknown parameters: missing"):
        load_scenario(path)


def test_formula_for_reports_available_scenarios(tmp_path):
    path = _write_scenario(
        tmp_path,
        """
[tools.open]
description = "Open a record"
parameters = {}

[scenario.safe]
formula = "G(open)"
""",
    )

    with pytest.raises(ScenarioError, match="Available scenarios: safe"):
        load_scenario(path).formula_for("missing")


def test_load_scenario_rejects_non_string_instructions(tmp_path):
    path = _write_scenario(
        tmp_path,
        """
[tools.open]
description = "Open a record"
parameters = {}

[scenario.safe]
formula = "G(open)"
instructions = 42
""",
    )

    with pytest.raises(ScenarioError, match="instructions must be a string"):
        load_scenario(path)


def test_cli_selects_named_scenario(tmp_path):
    path = _write_scenario(
        tmp_path,
        """
[tools.open]
description = "Open a record"
parameters = {}

[scenario.safe]
formula = "G(open)"
instructions = "Only open records relevant to the request."
""",
    )

    args = _parse_args([str(path), "--scenario", "safe"])

    assert args.formula == "G(open)"
    assert args.scenario_config.tool_names == ["open"]
    assert args.instructions == (
        f"{INSTRUCTIONS.rstrip()}\n\n"
        "Only open records relevant to the request."
    )


def test_cli_accepts_explicit_formula(tmp_path):
    path = _write_scenario(
        tmp_path,
        """
[tools.open]
description = "Open a record"
parameters = {}
""",
    )

    args = _parse_args([str(path), "--formula", "F(open)"])

    assert args.formula == "F(open)"
    assert args.instructions == INSTRUCTIONS


def test_bundled_scenario_formulas_compile_with_spot():
    path = Path(__file__).parents[1] / "scenarios" / "records.toml"
    config = load_scenario(path)

    for scenario in config.scenarios:
        SpotVerifier(tool_names=config.tool_names, formula=scenario.formula)
