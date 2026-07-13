---
name: cicada-librarian
description: >-
  Turns the user's own agent (Claude Code, Codex, Cursor — whatever runs this
  skill) into Cicada's consolidation engine, no Cicada API key required. Use
  at the end of a working session, whenever the user says "remember this" /
  "consolidate our chat", or right after watching a video with claude-video.
  Also covers capturing episodes and URLs mid-conversation.
---

# Cicada librarian skill

Cicada's Sleep cycle normally does entity/claim extraction as a nightly batch
job. This skill lets the user's own frontier-model subscription (Claude Code,
Codex, Cursor — no separate Cicada API key) do that extraction live, inside
the conversation, using the same `cicada_write_claim` write path the Sleep
cycle uses. A keyless local Ollama nightly batch remains the fallback for
whatever this skill doesn't catch.

## When to consolidate

- **End of a working session** — before the conversation closes, sweep it.
- **On request** — user says "remember this", "consolidate our chat", "save
  that", etc. — do it immediately, don't wait for session end.
- **After watching a video** — once the `claude-video` chain (below) returns
  a transcript + summary, consolidate that content the same way.

## Capture tools

- `cicada_save_episode(content, title)` — stage a raw conversation snippet.
  Use for anything worth remembering: decisions, facts, plans.
- `cicada_save_url(url, note?)` — save a link (article, repo, bookmark).
  Cicada fetches and indexes it.
- **Video**: run the `claude-video` skill's `/watch <url> <question>`
  (github.com/bradautomates/claude-video) to get transcript + frames +
  summary. Then:
  1. `cicada_save_url(url, note=<your faithful summary>)` — the transcript is
     the source of truth; the note is your summary of it, not embellishment.
  2. `cicada_write_claim(...)` for relational facts the video establishes —
     e.g. subject=`<video title>`, predicate=`is-about`, object=`<topic>`, or
     predicate=`recommends`, object=`<thing recommended>`.

## Consolidate loop

Run this to drain the backlog (end of session, on request, or after a video
save):

1. `cicada_pending(limit?)` — list unprocessed episodes (`processed: false`).
2. For each episode, read its content.
3. For each **atomic fact** in it, call
   `cicada_write_claim(subject, predicate, object, observer=...)` — one claim
   per fact, never bundle two facts into one call.
4. `cicada_mark_processed([episode_ids])` — once you've extracted everything
   worth keeping from those episodes. An unmarked episode is still a safety
   net for the next real Sleep cycle, so only mark what you actually
   consolidated.

## Observer tagging (load-bearing)

This is what gives the graph real perspective diversity — get it right:

| observer | when |
|---|---|
| `rodrigo` | the **user** stated/asserted this themselves. Trust-protected — a later `agent` claim can never silently overwrite it. |
| `agent` | **you** inferred, deduced, or noticed this — not something the user said outright. |
| `external:<name>` | a claim attributed to a **third party** (someone else's stated belief, quoted or paraphrased). Name the source when known. |

Default is `agent` if omitted — don't rely on the default when the user
clearly stated the fact themselves; tag `rodrigo` explicitly.

## Grounding

Write rich but strictly faithful content — only facts actually present in
the episode/transcript, never invented or inferred-and-passed-off-as-stated.
Prefer `[[wikilinks]]` to existing entities over prose restatement. If
something is ambiguous, write it as an `agent`-observed claim at lower
confidence rather than guessing and asserting it as fact.

## Model note

This loop runs on the user's own frontier-model subscription (whatever runs
this skill) — no Cicada API key needed. A keyless local Ollama nightly batch
is the fallback consolidation path for episodes this skill doesn't drain.

## Never hand-edit entity files

Same rule as recall: write only through `cicada_write_claim` /
`cicada_save_episode` / `cicada_save_url`. Never edit `entities/`, `hubs/`,
or `_index.md` directly — that bypasses provenance and dedup.
