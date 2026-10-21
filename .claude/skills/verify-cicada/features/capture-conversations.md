# Capture conversations

A conversation with an agent becomes one episode in the bank, with no model involved, as soon as the harness's hook fires. Each later turn of the same session extends that episode instead of starting a new one.

## Sub-features

- `capture-turn` stores a Cursor or Gemini CLI turn posted by its hook.
- `capture-session-extend` appends a later turn of the same session to the same episode.
- `capture-transcript` stores a Claude Code or Codex session from its Stop hook (backend reads the transcript).
- `capture-session-post` stores a session read on another machine (device token).
- `capture-agent-save` stores a note an agent saves with `cicada_save_episode` or `cicada save`.
- `capture-demo-guard` refuses or redirects capture while the demo bank is open.

## How to get to it (user POV)

- A Cursor or Gemini CLI hook posts `POST /capture/turn` after each turn.
- A Claude Code or Codex Stop hook posts `POST /capture/transcript` (`api/hooks/capture.py`).
- An agent calls `cicada_save_episode`; a terminal runs `cicada save`.
- Home shows `N captured today` once an episode lands.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- No episode exists for session `s1`.

- **Turn.** Post one exchange. Run `$CV capture --session s1 --turn t1 --user "I am starting alpha-project, a birdsong classifier in Rust." --assistant "Noted."`. The answer is `status: created`, an `episodeId`, `turnsUser: 1`.
- **Extend.** Post the next turn of the same session. Run `$CV capture --session s1 --turn t2 --user "alpha-project will use rustfft."`. The answer names the same `episodeId` with status `updated`.
- **Stored.** Read the file. Run `$CV bank ls` and `$CV bank cat episodes/<episodeId>.md`. Frontmatter has `processed: false`, `session_id: s1`, `harness: cursor`, and the body has both `user:` turns.
- **Agent save.** Run `$CV mcp call cicada_save_episode '{"content": "Decided to ship alpha-project v0 on Friday.", "title": "alpha-project ship date"}'`. The reply names a new episode; `$CV bank ls` lists it.
- **Proof.** `evidence/capture/s1-t1.json` and `s1-t2.json` hold request and answer; the episode file is the second view.

## Gotchas

- The episode date is the UTC date; late evening local time can land on the next or previous day.
- `/capture/transcript` only reads a transcript under the harness root as `<session_id>.jsonl`; a verify run has no such file, so drive Claude Code capture through a real session only on the person's say-so.
- Turn text over the cap is trimmed; assert on the head, not the full text.
