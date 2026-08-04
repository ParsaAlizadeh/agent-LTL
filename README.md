# Verifier-gated Responses agent

This is a small provider-configurable agent loop built on the OpenAI Python
client's Responses API. It collects every function call in a model response,
asks one batch verifier for a decision, and executes either the complete batch
or none of it.

The included placeholder policy requires `tool_a` to execute at least once and
rejects every proposed batch containing `tool_b`.

## Setup

The requested environment is already created in `.venv`. To recreate it:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

For the default local provider, start Ollama and ensure the model exists:

```bash
ollama serve
ollama pull gemma4:e2b
```

Run interactively:

```bash
.venv/bin/python agent_loop.py
```

Or provide the first message directly:

```bash
.venv/bin/python agent_loop.py \
  "Use tool_a once to record a checkpoint, then finish. Do not use tool_b."
```

The terminal prints every user/assistant message, requested tool name and
arguments, tool result, and verifier decision with color-coded role labels.

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
.venv/bin/python agent_loop.py "Complete the procedure."
```

## Customization

- Edit the global `TOOLS` list to change tool names, descriptions, and JSON
  input schemas.
- Replace `execute_placeholder_tool` with real action dispatch.
- Replace `PlaceholderVerifier.verify_tool_batch` and `verify_halt` with the
  actual verifier.

The loop deliberately manages a complete local `history` and sends it on each
request. It does not use `previous_response_id`, Conversations, or server-side
compaction, so the same control flow can work with stateless Responses-compatible
providers. A production long-running version should retain a complete audit log
while compacting the smaller context sent to the model.

## Tests

```bash
.venv/bin/python -m pytest -q
```
