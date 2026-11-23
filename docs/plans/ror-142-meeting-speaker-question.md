# ROR-142 slice 2 — ask the person who an unnamed meeting speaker was

Stacked on PR #778 (slice 1: placeholder labels, the identification call, the note).

Rodrigo, 2026-11-23: "i guess the labeling can be a quick question from cicada, saying smth like (in the meeting
"meeting name" you were speaking with ... who was speaker 1, or the guy who said x and y"

## Global constraints

- A person's identity comes from the person's words (Sleep rail, ruling 29 "never a person's identity without their
  words"). The question is the sanctioned path; nothing settles it but their answer — no tending rule, no judge, no
  other conversation's words (like `asks: sources`).
- Ruling 52a stands: only `You`/`Me` lines are the person's. An answer naming the person themselves is refused.
- The backend never opens a watched folder; it never writes the recorder's file.
- One writer per store: `meeting_speakers` writes `meetings/speaker-names.yaml` and nothing else does.
- An answer is the person's commit (`inbox_service._commit_answer`), every path it touched in the manifest.

## Rulings

1. **On the existing `clarification` kind, `asks: speaker`.** The app already draws options plus "Other" for a
   clarification (`allow_other`); no new kind, no app change.
2. **Only a voice, never a track.** Asked for a placeholder `is_group_placeholder` is false for (`Speaker 1`, not
   `Them`), still unnamed after slice 1's identification, with at least `MIN_LINES` (5) lines. One question per
   meeting and label; never again once answered or declined.
3. **The answer is stored by source, applied by the parser.** `meetings/speaker-names.yaml` maps
   `source_id → {label: {name, at} | {declined: true, at}}`. `meeting_transcripts.draft_for_file` renames an answered
   placeholder before markers are made, so a later sync of the same file renders the same body (the stager skips it)
   and an edited file keeps the name. `meeting.named_by_person` records `{label: name}`.
4. **The stored episode is relabelled in place at once** (`episode_staging.relabel_in_place`): the label's marker
   lines change, the turn stamps' offsets move with them, the body is a revision of itself (`revised`, re-queued) —
   so Sleep re-reads only the changed lines, with the name (G104 machinery; what only the removed text said is
   superseded or withdrawn by that machinery, not here).
5. **"Someone I don't know"** records `declined`; nothing else changes; never asked again.
6. **Tending never settles it**; a question whose episode is gone is retired.

## File map

| File | Change |
|---|---|
| `api/services/meeting_speakers.py` | names store, `ask_after_read`, `answer`, `decline`, `settle_rule` |
| `api/services/meeting_transcripts.py` | `draft_for_file(..., speaker_names=)` |
| `api/services/folder_source.py` | pass the source's answered names to the drafter |
| `api/services/episode_staging.py` | `relabel_in_place` |
| `api/services/entity_extractor.py` | a meeting's result carries `meeting_unnamed` (markers still unnamed) |
| `api/services/sleep_cycle.py` | Stage 5.4c: `meeting_speakers.ask_after_read` |
| `api/services/inbox_service.py` | `asks: speaker` → `_resolve_speaker` |
| `api/services/inbox_tend.py` | `asks: speaker` is the person's alone |
| `api/tests/test_meeting_speaker_question.py` | tests |
| `docs/architecture/capture-and-sleep.md`, `storage.md` | the question and the store |
