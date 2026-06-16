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

Cicada is the user's long-term memory. The MCP server gives you the tools; this
file is the policy: when to recall, how to traverse, and what never to touch.

## When to recall
- Start of a session on a recurring topic, person, or project -> `cicada_recall` first.
- User asks what you know about something -> `cicada_recall`, then `cicada_recall_detail`.
- Conversation touches a known topic -> `cicada_check_nudges(topic)` to surface
  pending decay/conflict/clarification items, and raise them naturally in-flow.

## Two-pass recall (small-model friendly)
1. `cicada_recall(query)` — Pass 1. Returns concise entity summaries plus any
   relevant pending inbox items. Read the summaries and the "Related" list.
2. `cicada_recall_detail(entity_id)` — Pass 2. Returns the FULL entity page for
   the most relevant hit. Use this only when you need the complete body/history,
   not a summary.
3. Follow `[[wikilinks]]` / the Related list with more `cicada_recall_detail`
   calls when you need relational depth.

## Hub browsing (filesystem traversal)
For structured exploration rather than fuzzy search, walk the hub tier:
`cicada_open_hub(hub_id)` opens a hub page that lists its member entities.
On disk this mirrors `_index.md` -> `hubs/<hub>.md` -> `entities/<entity>.md`:
start at the index, pick a hub, then drill into entities. Use hubs to answer
"show me everything about <area>"; use recall to answer "find <specific thing>".

## Saving memories
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
      hubs/           topic / type hub pages, each listing member entities
      entities/       one markdown page per entity (YAML frontmatter + body)
      episodes/       raw captured snippets (re-consolidation source of truth)
      sources/        saved media (links, videos) ingested via cicada_save_url
      inbox/          pending items the user resolves (nudges + clarifications)
      leann/          vector indexes — never edit by hand

## If the tools are missing
The MCP server isn't registered. Tell the user to run `./install.sh` (or
`make install`) from the Cicada repo, which registers the `cicada` MCP server.
