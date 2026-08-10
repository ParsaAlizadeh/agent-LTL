from __future__ import annotations

import argparse
import os
from dataclasses import replace

from . import scenarios as _bundled_scenarios  # noqa: F401
from .runtime import Console, Settings, make_env_settings, prepare_default_runtime
from .scenario import ScenarioError, scenario_class_for, scenario_names


def _scenario_name_from_argv(argv: list[str] | None) -> str | None:
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument(
        "-s", "--scenario", default=os.getenv("AGENT_SCENARIO")
    )
    args, _ = bootstrap.parse_known_args(argv)
    return args.scenario


def _base_parser(*, add_help: bool = True) -> argparse.ArgumentParser:
    env_settings = make_env_settings()
    parser = argparse.ArgumentParser(
        description="Run a programmable verifier-gated scenario",
        add_help=add_help,
    )
    parser.add_argument(
        "-s",
        "--scenario",
        default=os.getenv("AGENT_SCENARIO"),
        metavar="NAME",
        help="registered Python scenario (default: AGENT_SCENARIO)",
    )
    parser.add_argument("--api-url", default=env_settings.api_url)
    parser.add_argument("--api-key", default=env_settings.api_key)
    parser.add_argument("--model", default=env_settings.model)
    parser.add_argument("--proxy", default=env_settings.proxy_url)
    parser.add_argument("--max-turns", type=int, default=env_settings.max_turns)
    parser.add_argument(
        "--max-output-tokens", type=int, default=env_settings.max_output_tokens
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=env_settings.request_timeout_seconds,
    )
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="list registered scenario names and exit",
    )
    return parser


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    scenario_name = _scenario_name_from_argv(argv)
    parser = _base_parser()

    if scenario_name is None:
        preliminary, _ = parser.parse_known_args(argv)
        if preliminary.list_scenarios:
            return preliminary
        parser.error(
            "a scenario is required; use --scenario NAME or AGENT_SCENARIO. "
            f"Available scenarios: {', '.join(scenario_names())}."
        )

    try:
        scenario_class = scenario_class_for(scenario_name)
    except ScenarioError as exc:
        parser.error(str(exc))

    scenario_group = parser.add_argument_group(
        f"{scenario_name} scenario arguments"
    )
    scenario_class.add_arguments(scenario_group)
    args = parser.parse_args(argv)
    args.scenario_class = scenario_class
    return args


def _settings_from_args(args: argparse.Namespace) -> Settings:
    return replace(
        make_env_settings(),
        api_url=args.api_url,
        api_key=args.api_key,
        model=args.model,
        proxy_url=args.proxy,
        max_turns=args.max_turns,
        max_output_tokens=args.max_output_tokens,
        request_timeout_seconds=args.request_timeout,
    )


async def _async_main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.list_scenarios:
        print("\n".join(scenario_names()))
        return

    scenario = args.scenario_class.from_parsed_args(args)
    settings = scenario.configure_global_settings(_settings_from_args(args))
    if not isinstance(settings, Settings):
        raise TypeError("configure_global_settings() must return Settings.")

    runtime = prepare_default_runtime(
        settings=settings,
        console=Console(use_color=not args.no_color),
    )
    async with runtime:
        await scenario.main(runtime)
