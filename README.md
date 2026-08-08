# Verifier-gated Responses agent

This is a small provider-configurable agent loop built on the OpenAI Python
client's Responses API. It collects every function call in a model response,
asks one batch verifier for a decision, and executes either the complete batch
or none of it.

Tools and LTL policies are loaded from TOML scenario files. The included
`scenarios/records.toml` example defines `open` and `close` tools and two named
policies.

## Setup

The requested environment is already created in `venv`. To recreate it:

```bash
uv venv venv
uv pip install --python venv/bin/python -r requirements.txt
```

For the default local provider, start Ollama and ensure the model exists:

```bash
ollama serve
ollama pull gemma4:e2b
```

Run interactively with a named scenario:

```bash
venv/bin/python -m agentltl scenarios/records.toml \
  --scenario close_after_open
```

Or supply an LTL formula separately while using the tools from the same file:

```bash
venv/bin/python -m agentltl scenarios/records.toml \
  --formula 'G(open -> F close)'
```

The program prompts for the first user message after startup. An empty prompt
asks the verifier for permission to halt. Ctrl-C exits cleanly.

## Scenario files

Each `[tools.NAME]` table requires a description and parameters. Parameter
values are descriptions; every parameter is translated to a JSON Schema string
property. When `required` is omitted, all parameters are required.

```toml
[tools.publish]
description = "Publish a document"
required = ["title"] # Optional; defaults to every parameter.

[tools.publish.parameters]
title = "Title shown to readers"
notes = "Optional publication notes"

[scenario.reviewed]
formula = "G(publish -> F archive)"
instructions = "Explain the publication workflow and use concise review notes."
```

Parameters can also be written as a list of tables:

```toml
[[tools.publish.parameters]]
name = "title"
description = "Title shown to readers"
```

Each `[scenario.NAME]` requires a `formula` and may include `instructions`.
Scenario instructions are appended to the built-in system instructions when
that named scenario is selected. Select it with `--scenario NAME`, or use
`--formula` to provide another formula while retaining the file's tool
definitions and only the built-in instructions.

## Provider configuration

The top-level constants in `agent_loop.py` read these environment variables:

| Variable | Default |
| --- | --- |
| `AGENT_API_URL` | `http://127.0.0.1:11434/v1` |
| `AGENT_API_KEY` | `ollama` |
| `AGENT_MODEL` | `gemma4:e2b` |
| `AGENT_PROXY_URL` | unset |
| `AGENT_MAX_TURNS` | `50` |
| `AGENT_MAX_OUTPUT_TOKENS` | `2048` |
| `AGENT_REQUEST_TIMEOUT` | `180` seconds |

Matching flags such as `--api-url`, `--api-key`, `--model`, and `--proxy` can
override them for one run. Without `AGENT_PROXY_URL`, the underlying HTTPX
client honors the standard `HTTP_PROXY`/`http_proxy`, `HTTPS_PROXY`/`https_proxy`
and `NO_PROXY` environment variables. `AGENT_PROXY_URL` is an explicit override.

Example using OpenRouter:

```bash
AGENT_API_URL=https://openrouter.ai/api/v1 \
AGENT_API_KEY="$OPENROUTER_API_KEY" \
AGENT_MODEL=provider/model-name \
venv/bin/python -m agentltl scenarios/records.toml \
  --scenario close_after_open
```

## Customization

- Add or edit a TOML scenario file to change tools and LTL policies.
- Replace `execute_placeholder_tool` with real action dispatch.

The loop deliberately manages a complete local `history` and sends it on each
request. It does not use `previous_response_id`, Conversations, or server-side
compaction, so the same control flow can work with stateless Responses-compatible
providers. A production long-running version should retain a complete audit log
while compacting the smaller context sent to the model.

## Tests

```bash
venv/bin/python -m pytest -q
```
