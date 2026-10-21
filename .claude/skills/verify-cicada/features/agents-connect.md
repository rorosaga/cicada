# Connect agents

Settings → Agents registers Cicada's MCP server and hooks with Claude Code, Codex, Cursor, Gemini CLI and Claude Desktop, and shows live sessions.

## Sub-features

- `agents-wiring`, `agents-setup`, `agents-live`, `agent-methods`.

## How to get to it (user POV)

- Settings → Agents.
- `GET /agents/wiring`, `/agents/setup`, `/agents/live`, `GET/PUT /agent-methods`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Read.** Run `$CV api GET /agents/wiring --save api/agents-wiring.json`. What is wired where, read only.
- **App.** Open Settings → Agents and screenshot. Stop there.

## Gotchas

- Connect writes the real `~/.claude`, `~/.cursor/hooks.json` and friends, pointing them at the run's code path. Never click it in a verify run.
