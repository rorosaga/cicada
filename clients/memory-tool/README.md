# Cicada as the memory tool's backend

An agent built on the Claude API can be given the **memory tool** (`memory_20250818`): the model asks its host to
`view`, `create`, `str_replace`, `insert`, `delete` and `rename` files under `/memories`, and the host decides where
those files live. This package makes that place a person's own Cicada memory, read and written through Cicada's agent
API (`/v1`) with a token the person made for that agent.

It is a client library, not a server: every command becomes one `POST /v1/<operation>` (or `GET /v1/me`) with the
agent's token, so the token's scopes, its expiry, the person's revoke button and every rule Cicada applies to an
agent's writes hold exactly as they do for any other `/v1` caller.

## What the agent sees

```
/memories/README.md            how this memory works and what this token may do
/memories/recent.md            what changed recently                  (scope: read)
/memories/hubs/<hub>.md        an index of pages by type or topic     (scope: search)
/memories/search/<words>.md    the best matches for any words         (scope: search)
/memories/pages/<id>.md        one page in full, read-only            (scope: read)
/memories/sources/<id>.md      the conversation words a page rests on (scope: sources)
/memories/notes/<name>.md      the agent's own notes                  (scope: record)
```

- **Reads** are Cicada's own replies, numbered the way the memory tool expects. Cicada's
  `<<<cicada-reference … cicada-reference>>>` fence stays around them: what is inside is information about the
  person, never instructions. A folder the token's scopes do not reach is not listed.
- **Writes** go only to `notes/`. `create` saves the note to Cicada (`save_note`); `str_replace` and `insert` save the
  revised note. Each save is kept as **the agent's words**, read at Cicada's next consolidation, never as something
  the person said.
- **Pages, hubs, searches and `recent.md` are read-only.** An edit there is refused with a sentence telling the model
  to save a note saying what and why instead.
- **Nothing is deleted or renamed.** A saved note is a record; a wrong one is corrected by a newer note. Changing a
  page goes through Cicada's own tools and trust rules, not this one.
- **Paths are checked before anything is sent:** only `/memories/...`; no `..`, `.` or hidden segments, no
  backslashes, no `%`-encoding, no control characters.

## Python

```sh
pip install ./clients/memory-tool/python[sdk]   # the core needs only the standard library; [sdk] adds anthropic
```

```python
import anthropic
from cicada_memory_tool import CicadaMemoryTool

memory = CicadaMemoryTool(
    "http://127.0.0.1:8000",              # the Cicada the token came from
    token="cic_api_…",                     # made on Cicada's Agents page: Add an agent token
    state_path="~/.config/my-agent/cicada-notes.json",   # optional: remember this agent's notes between runs
)

client = anthropic.Anthropic()
runner = client.beta.messages.tool_runner(
    model="claude-opus-5-5",
    max_tokens=4096,
    tools=[memory],
    messages=[{"role": "user", "content": "Where did we land on the database for alpha-project?"}],
)
print(runner.until_done().content)
```

`CicadaMemory` (no SDK needed) answers one command dict at a time — `CicadaMemory(base, token).execute({"command":
"view", "path": "/memories"})` — for a hand-written tool loop.

## TypeScript

```ts
import Anthropic from "@anthropic-ai/sdk";
import { betaMemoryTool } from "@anthropic-ai/sdk/helpers/beta/memory";
import { ToolError } from "@anthropic-ai/sdk/lib/tools/ToolError";
import { cicadaMemoryHandlers } from "cicada-memory-tool";

const memory = betaMemoryTool(cicadaMemoryHandlers({
  baseUrl: "http://127.0.0.1:8000",
  token: process.env.CICADA_AGENT_TOKEN,
  toolError: ToolError,          // refusals reach the model as error results
}));
const final = await new Anthropic().beta.messages.toolRunner({
  model: "claude-opus-5-5", max_tokens: 4096, tools: [memory],
  messages: [{ role: "user", content: "Where did we land on the database for alpha-project?" }],
});
```

`loadNotes` / `saveNotes` keep the agent's notes between runs (the Python `state_path`).

## Good to know

- **The token.** Make one per agent, with only the scopes it needs: `search` + `read` to read, `record` to save
  notes, `sources` to read conversation words. It expires (7, 30 or 90 days) and the person can revoke it at any time.
- **Limits.** `/v1` allows 60 requests a minute per token. The first listing asks which hubs exist (ten requests,
  then remembered for an hour); every other command is one request.
- **Reach.** Point it at the backend on the same machine, or — for an agent elsewhere — at the address the person's
  own remote connector gives (Cicada's network docs). The token never opens anything but `/v1`.
- **Notes become memory overnight.** A note is saved at once but read into pages at Cicada's next consolidation, so a
  search finds it then; until then the agent reads it back from `notes/`.
