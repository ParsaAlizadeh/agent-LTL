# Repository Guidelines

## Project Structure & Module Organization

`agentltl/` contains the Python package. The command-line entry points live in
`__main__.py` and `cli.py`; `agent_loop.py`, `runtime.py`, and `types.py` provide
the orchestration core; and `spot_verifier.py` implements LTL enforcement.
Scenario definitions belong in `agentltl/scenarios/` and should be registered
and imported through that package. Tests currently live in
`tests/test_scenario.py`. Design notes and benchmark instructions are under
`docs/`; keep user-facing setup and usage in `README.md`.

## Build, Test, and Development Commands

- `uv venv venv` creates the local virtual environment.
- `uv pip install --python venv/bin/python -r requirements.txt` installs pinned
  runtime and test dependencies.
- `venv/bin/python -m pytest -q` runs the complete test suite.
- `venv/bin/python -m agentltl --list-scenarios` verifies scenario discovery.
- `venv/bin/python -m agentltl -s coin_game --n 8 --true-coin 3` runs the
  bundled coin scenario. The default provider also requires a running Ollama
  server and the configured model.

There is no compile step; setuptools packaging is configured in
`pyproject.toml`.

## Coding Style & Naming Conventions

Target Python 3.11 or newer. Follow the existing PEP 8 style: four-space
indentation, `snake_case` for modules/functions/variables, `PascalCase` for
classes, and uppercase names for constants. Keep type annotations on public
interfaces. Scenario classes should end in `Scenario`; registered scenario
names use lowercase snake case, such as `coin_game`. No formatter or linter is
configured, so keep changes consistent with neighboring code.

## Testing Guidelines

Tests use pytest and follow `test_<behavior>` naming. Add focused regression
tests to `tests/`, using fakes and `monkeypatch` for providers, clients, and
environment variables rather than making network calls. Run the full suite
before submitting. The project does not specify a coverage threshold; cover
new branches and verifier edge cases proportionally.

## Commit & Pull Request Guidelines

Recent commits use concise, imperative subjects with a scope, for example
`scenario/coin: Implement auto coin game simulation` or `chore: Add minimal
pyproject.toml`. Follow that pattern and keep each commit focused. Pull requests
should explain the behavior change, identify affected scenarios or policies,
link relevant issues, and include test results.

## Configuration & Security

Use `AGENT_*` environment variables documented in `README.md`; do not commit
API keys or `.env` files. Keep rejected tool calls side-effect free: all
real-world actions must pass through the scenario bridge and verifier.

## Documentation Changes

Treat `README.md`, `docs/`, and other Markdown guides as documentation. Before
editing them, describe the proposed change and obtain explicit user approval.
Approval for a code change does not include documentation approval.
