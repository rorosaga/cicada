---
name: cicada
description: >-
  Personal second-brain memory for the user. Use when the user references
  something they told you before, asks "what do I know about X", shares a
  decision, fact, or link worth keeping, or when starting a session where
  prior context would help. Backed by the Cicada MCP server and a local,
  git-versioned markdown knowledge graph.
---

# Cicada memory skill

Cicada is the user's long-term memory. The MCP server gives you the tools (or,
from a shell, the `cicada` command below); the generated handshake is the
contract; this file adds the traversal notes.

## From a shell: the `cicada` command
<!-- cicada-cli:begin (generated from api/services/cli_map.py: edit the table, not this block) -->
Agents that can run shell commands can use `cicada` instead of the MCP tools: the same memory and bank,
read and written by the same code. `cicada --help` lists the commands (`--help` after any command explains
it).

- **Where it is:** `cicada` on PATH; if that is not found, "${CICADA_HOME:-$HOME/.cicada}/bin/cicada" (the Cicada app keeps that
  launcher current).
- **Start:** `cicada handshake` when no Cicada primer reached you; `cicada continue` for where the work in
  this folder stopped.

| Command | What it does |
|---|---|
| `cicada recall "<query>"` | Search memory: pages, claims and conversations, fused. |
| `cicada get <entity-id>` | One page in full (a long one in parts: --start), or a range of its lines (--from/--count, or ENTITY:START[:END]). |
| `cicada project <project>` | Where one project stands. |
| `cicada continue` | Where the work in this folder stopped. |
| `cicada save "<content>"` | Stage a note for the next Sleep (content `-` reads stdin). |
| `cicada handshake` | The contract and the current state, for an agent arriving cold. |
| `cicada status` | Which memory this command uses, and whether the app's backend agrees. |
| `cicada commands` | Every command, and the MCP tool each one mirrors. |
| `cicada import <path>` | Bring in what the person saved on a platform, from its data export (a .zip, a folder or one file). |

- **Options:** get: `--start`, `--from`, `--count`, `--line-numbers`; project: `--since`, `--tz`; continue: `--session`, `--before`; save: `--title`; import: `--preview`, `--include-history`. `get` also takes `<entity-id>:<start>[:<end>]`; `save` reads the
  text from stdin when it is `-`.
- **`--json`** (before or after the command) prints one envelope: `{schema, command, ok, code, bank, data,
  text, warnings, version}`. `text` is what the matching MCP tool says; `data` is the structured part.
- **Exit codes:** 0 ok (a duplicate save is ok too) · 1 refused (`not_found`, `empty_graph`) · 2 usage ·
  3 bank or memory-folder mismatch, nothing written · 4 demo bank · 5 this shell may not use the memory
  folder (use the MCP tools there) · 70 internal.
- **Grouping:** what you save is grouped by your harness's session id. If your harness gives none, set
  `CICADA_SESSION_ID` and `CICADA_SESSION_HARNESS`; without them a note is saved ungrouped, never under a
  made-up id.
- **Not in the command line yet:** questions, claims, sources, progress and the backlog. Use the MCP tools
  for those when they are connected.
<!-- cicada-cli:end -->

## Handshake first
The contract lives in one generated text: the `instructions` your harness received
from the Cicada MCP server on connect, or `cicada_handshake()` if it did not surface
them. Read it once per conversation — it carries what Cicada is, when to recall,
how to check nudges after a recall, how to save and write with evidence, the
bank's current projects and pending questions, and which conversations resume.
This file only adds the traversal notes below.

## Two-pass recall (small-model friendly)
1. `cicada_recall(query)` — Pass 1. Returns concise entity summaries plus any
   relevant pending inbox items. Read the summaries and the "Related" list.
2. `cicada_recall_detail(entity_id)` — Pass 2. Returns the FULL entity page for
   the most relevant hit. Use this only when you need the complete body/history,
   not a summary.
3. Follow `[[wikilinks]]` / the Related list with more `cicada_recall_detail`
   calls when you need relational depth.
4. Before answering that something is not in memory, open the top entity with
   `cicada_recall_detail`. State only facts the tools returned — never fill
   gaps with general knowledge.

## Grounding
- Before answering that something is not in memory, open the top entity with
  `cicada_recall_detail`. State only facts the tools returned — never fill
  gaps with general knowledge.
- For a direct factual question, `cicada_ask` is usually the best single call.

## Hub browsing (filesystem traversal)
For structured exploration rather than fuzzy search, walk the hub tier:
`cicada_open_hub(hub)` opens a hub page that lists its member entities.
On disk this mirrors `_index.md` -> `hubs/<hub>.md` -> `entities/<entity>.md`:
start at the index, pick a hub, then drill into entities. Use hubs to answer
"show me everything about <area>"; use recall to answer "find <specific thing>".

## Saving memories
- When useful, end a working reply with a brief `State:` (in flight / blocked /
  next); optional, not a handoff ritual. Capture keeps it as part of the reply.
- Important conversation content (a decision, a plan, a fact the user will want
  later) -> `cicada_save_episode(content, title)`. It stages a raw episode; the
  nightly Sleep cycle extracts entities and relationships from it.
- A link worth keeping (article, repo, video) -> `cicada_save_url(url, note?)`.
  Cicada fetches and indexes it as a media source.

## Never hand-edit entity files
The Sleep cycle owns all writes to `entities/`, `hubs/`, and `_index.md` — it
handles dedup, provenance (git), and decay. Do NOT edit those files directly.
If the user wants a correction, route it through the inbox (resolve the relevant
nudge/clarification) or capture it with `cicada_save_episode` and let the next
Sleep cycle consolidate it. Direct edits bypass provenance and break dedup.

## Memory directory layout (read-only orientation)
    ~/cicada/memory/
      _index.md       top-level hub-tier entry point (start traversal here)
      _state.md       the live now-view (cursor: ids + one-liners; GET /state for the object)
      hubs/           topic / type hub pages, each listing member entities
      entities/       one markdown page per entity (YAML frontmatter + body)
      episodes/       raw captured snippets (re-consolidation source of truth)
      sources/        saved media (links, videos) ingested via cicada_save_url
      inbox/          pending items the user resolves (nudges + clarifications)
      leann/          vector indexes — never edit by hand

## If the tools are missing
The MCP server isn't registered. Tell the user to run `./install.sh` (or
`make install`) from the Cicada repo, which registers the `cicada` MCP server.
