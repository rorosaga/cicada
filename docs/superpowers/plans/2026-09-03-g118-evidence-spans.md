# G118 Slice 1 — Evidence Spans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every claim Cicada writes from now on records *where in the stored text* it came from — a span (character offsets into a stored episode or page body, plus a content hash), never a copied quote — or says honestly that it is the contributor's own inference. Slice 1 is the capture half plus the read path a viewer needs: Stage-1 extraction asks for the convincing passage and the resolver verifies it; an agent citing what the person just said records a real span through `cicada_write_claim`; link recon records the surface form it grounded on; `GET /entities/{id}/claims` / `/timeline` carry `evidence`; and `GET /episodes/{id}/span` slices a stored body back out, engine-free, with a `stale` flag.

**Architecture:** One new schema field (`Claim.evidence: list[Evidence]`) and one new engine-free module (`api/services/evidence.py`: hash, resolve-a-source-document, locate-a-quote ladder, speaker kind, verify). Three writers call `verify`: the Stage-1 extractor (offsets into the exact `content` it chunked, which IS the stored body), `agentic_write.write_claim` (agent-supplied `{episode, quote}` pairs), and `link_recon` (an entity surface form located in the media page body). Two readers grow: the claim projections (`ClaimModel.evidence`) and a new `episodes` router. Nothing here calls a model, reads `~/.claude`, or copies text into a claim or the ledger.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), YAML frontmatter + git (`memory/`), MCP server (`mcp/server.py`). No Swift changes (see R10).

**Spec:** `docs/goals/memory-evolution.md` row **G118** (layer 1, "Spans, not copies"), which absorbs **G100**. This plan is slice 1 of G118's four; slices 2–4 (viewer, trigger traces, rationale) are explicitly out of scope.

## Global Constraints

- Work ONLY in `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118` (branch `feat/provenance-spans`, based on `dev @ c6d22d0`). Every shell command is `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && <cmd>` with the absolute path. Ignore zoxide's stderr warning. No `grep --include=*.ext` (zsh globbing).
- **Never read** `/Users/rorosaga/Documents/roros_lab/cicada/memory` (any bank), `~/.cicada`, `~/Library/Safari`, or `~/.claude/projects`. Every fixture in this plan is synthetic (`alpha-project`, `bob-example`, `example.com`).
- Python tests: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`. Baseline on the full `api/tests` run: exactly 8 date-dependent failures in `test_calendar_registry.py` plus `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` (order-dependent, pre-existing). Everything else must be green after every task.
- Never `git add -A`. Stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`, `*-report.md`. No push, no new branches/worktrees, no subagents. Ignore Devin/PR comments.
- **Spans, not copies.** No claim field, no ledger event, no API response written by this plan carries a quoted copy of source text *as provenance* — offsets + hash only. (The span endpoint returns text because the viewer asks for it by offset; that is a read of the bank, not a copy stored anywhere.) The only in-flight quote is `evidence_quote` on a Stage-1 relationship dict, which `attach_relationship_evidence` pops before the dict reaches Stage 2.
- **Provenance never blocks memory.** A quote that cannot be located becomes `kind: reasoning` and the claim is still written. `verify` never raises on any input.
- **Engine-free read paths (G80/G74 ruling).** `api/services/evidence.py` imports only `markdown_parser` and `claims`; the `episodes` router imports neither `providers` nor `litellm`. A span read costs one file parse.
- **G48 rail.** The only text a span may index is text Cicada itself stored in the bank (`<bank>/episodes/*.md`, `<bank>/entities/*.md`). Nothing under `~/.claude` is ever read.
- **ETag ship-together.** No new component is added to `sync_service.components` and no ETag is added to the claim endpoints or the span endpoint (R9) — so there is nothing to ship together and no version-vector drift.
- Cicada docstrings explain WHY and cite the G-row or review that motivated a rule. Match that density in every new function.
- Read code at the cited `file:line` before editing — line numbers are from base commit `c6d22d0` and drift by a few lines as tasks land.

## Rulings (binding — do not re-derive)

- **R1 — The evidence text of a document is exactly what `markdown_parser.parse` returns, minus the machine layer.** For an episode (`ep_*`), the text is `markdown_parser.parse(path).body` — frontmatter excluded, the body `.strip()`ped exactly as `api/services/markdown_parser.py:26` already does. For an entity page (anything else), it is `claims.strip_claims_block(parse(path).body)` — the ```claims fence removed and the result `.strip()`ped (`api/services/claims.py:287-289`), the same normalisation `link_enrichment._extract_description_section` (`api/services/link_enrichment.py:71-88`) already relies on. Why the fence is excluded: writing an `about` claim onto a media page would otherwise change that page's hash and mark the claim's own span stale the instant it was written. Why this is stable: `mark_episodes_processed` (`agentic_write.py:501-504`) and Sleep's mark-processed both rewrite frontmatter and pass `parsed.body` straight back to `write`, so a re-parse yields the identical body — the G100 "episodes must be immutable" dependency is verified for the body, and `hash` catches everything else.
- **R2 — `hash` is `sha256(text.encode("utf-8")).hexdigest()[:12]` of the R1 text.** Same width as the existing episode `content_hash` (`mcp/server.py` `handle_save_episode`), computed over the R1 text rather than the raw content the agent sent (which `write` + `parse` strip). A mismatch marks the span `stale`; the span is never silently re-located in this slice.
- **R3 — `Evidence.episode` is a source-document id, not only an episode id.** `ep_*` resolves to `episodes/<id>.md`; any other id resolves to `entities/<id>.md` (link recon's `kind: page` spans point at the media entity, e.g. `media-<slug>`). One resolver (`evidence.source_path`) answers both, validates the id against `^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$` (no path traversal), and the span endpoint uses the same resolver so a viewer can open either. The field keeps the name `episode` the G118 row specified; the docstring states the widening.
- **R4 — Speaker kind comes from the last turn marker at or before the span.** Imported conversations write one line per message as `<role>: <text>` — `content_lines.append(f"{msg['role']}: {msg['text']}")` at `api/routers/conversations.py:792`, and that same `content_str` IS the episode body written at `:911`/`:934`; roles are `user`/`assistant`/`system` plus `unknown` (`:494`, an export message with no role). The fixture in `api/tests/test_mcp_sources_tool.py:13` uses the same shape. `evidence.speaker_kind` scans every line of the text up to and including the line that contains `start` (so a marker sitting exactly at `start` — a quote that begins with `assistant: …` — counts as "at") for `^(user|human|assistant|ai|system|unknown)\s*:` case-insensitively; `assistant`/`ai` → `assistant`, everything else → `user`. **No marker → `user`**: every marker-less writer (MCP `cicada_save_episode`, which writes `content` verbatim; Telegram; Notes; calendar; media episodes with `## Saved because` / `## User note`) captures the person's own input; `assistant` is asserted only where the body itself marks a turn as the model's. `system:` lines are the person's own configured context (Claude project memory), not model output → `user`; `unknown:` is a turn the exporter could not attribute → `user`, never a silent inheritance of the previous `assistant:` marker.
- **R5 — The locate ladder is exact → whitespace-normalised → case-insensitive, and stops there.** Never fuzzy, never token-subset. The quote is `.strip()`ped and clipped to `MAX_QUOTE_CHARS = 240` before the search (a clipped quote is still a verbatim substring, so the span is simply the clipped portion). When a chunk window is known (Stage 1), the first occurrence inside the window wins; otherwise the first occurrence in the document. `whole_word=True` (link recon surfaces) wraps the pattern in `(?<![A-Za-z0-9])…(?![A-Za-z0-9])` so `Go` never matches inside `Google` — the whole-token rail `link_recon._mentions` (`link_recon.py:88-98`) already applies to a single-token name (a multi-token surface may match there as a lowercase phrase; here every surface is whole-word bounded, which is strictly tighter, so a span is never wider than what `attribute()` grounded on).
- **R6 — Every claim written after this slice carries at least one evidence entry; legacy claims carry none.** An unverifiable or absent quote yields `{episode: <source doc or "">, start: -1, end: -1, kind: reasoning, hash: <doc hash if readable else "">}`. So an empty `evidence` list means "written before evidence existed" and a `reasoning` entry means "the contributor had no source text" — the two are distinguishable by a viewer and by any later backfill. No backfill of old claims in this slice.
- **R7 — `to_dict` omits `evidence` when it is empty.** `write_claims` re-renders every claim on a page it touches; emitting `evidence: []` on ~2,300 legacy claims would produce a bank-wide diff on the first Sleep after merge for a field those claims do not have. `Claim.from_dict` defaults a missing key to `[]`, so the round-trip invariant `parse_claims(write_claims(body, claims)) == claims` holds unchanged.
- **R8 — Reinforcement merges evidence.** `claim_reconciler._reinforce` (`api/services/claim_reconciler.py:143-162`) appends the incoming claim's evidence entries to the existing claim, deduplicated by value, and drops an incoming `reasoning` entry for a document the existing claim already has an entry for — a later conversation restating a fact adds its span, and a re-mention never buries a real span under a placeholder. Mirrors the `session_ids` merge in the same function.
- **R9 — No ETag on the span endpoint or the claim endpoints in this slice.** The span response is self-validating (`stale` compares the caller's hash against the current body) and is addressed by offsets, so a cached copy can never mis-highlight; the `episodes` component already exists in the version vector (`api/services/sync_service.py:152`). Adding an ETag here would create a new ship-together obligation for zero benefit.
- **R10 — No Swift edit.** Verified: the app's `Claim` decoder (`app/CicadaApp/Sources/CicadaApp/Models/Claim.swift:94-142`) is a custom `init(from:)` with an explicit `CodingKeys` enum and `decodeIfPresent` for every optional — `JSONDecoder` ignores keys not in `CodingKeys`, so an additive `evidence` key cannot fail a decode. `ClaimListResponse`/`ClaimTimeline` likewise. The viewer (slice 2) will add the Swift model.
- **R11 — The Stage-1 quote is located against the full episode body, with the chunk as a window.** `extract` chunks `episode["content"]` (`entity_extractor.py:326`), and that content is `bank_index.IndexedFile.body()` = `markdown_parser.parse(path).body` (`bank_index.py:36-37`, `sleep_cycle.py:1270`) — the R1 text. So offsets computed against `content` are offsets into the stored body and `body_hash(content)` is the stored hash, with no second disk read. `_chunk_content` becomes a thin wrapper over a new `_chunk_spans` so the window is known per chunk without changing chunk boundaries (`test_extractor_robustness.py` keeps passing).
- **R12 — Link recon cites the surface form, on the page body, or reasons.** `attribute()` grounds an entity on a card by name/alias (`link_recon.py:101-121`) against `title + description`, but the title lives in frontmatter, not the body. So the evidence search runs the entity's name then each alias through `locate(page_text, surface, whole_word=True)` over the R1 page text; the first hit is a `kind: page` span on `media_id`; a name found only in the title (or only as scattered tokens) yields `reasoning` — never a span into text that is not there.
- **R13 — The Telegram `saved-because` claim cites its own `## Saved because` section.** `telegram_capture._write_saved_because_claim` passes `evidence=[{"episode": episode_id, "quote": reason}]`; a fresh save has the section already (`media_ingestor._episode_body`), a repeat save appends it *after* the claim is written (`telegram_capture.py:445-449`), so that path yields `reasoning` honestly rather than reordering the L3 logic.

---

## File map

| File | Responsibility |
|---|---|
| `api/services/claims.py` | `EVIDENCE_KINDS`, `Evidence` dataclass, `Claim.evidence`, `to_dict` omission (R7), `from_dict` parse |
| `api/services/evidence.py` (new) | `body_hash`, `is_episode_id`, `source_path`, `source_text`, `locate`, `speaker_kind`, `reasoning`, `verify`, `verify_many`, `attach_relationship_evidence` |
| `api/services/entity_extractor.py` | prompt `evidence_quote`, `_chunk_spans`, attach in `extract`, `entities_to_claims` carries evidence + merges duplicate-id evidence |
| `api/services/claim_reconciler.py` | `_reinforce` merges evidence (R8) |
| `api/services/link_recon.py` | `_page_evidence`, `_build_about_claim(evidence=)` |
| `api/services/agentic_write.py` | `write_claim(evidence=)`, `evidence` in the result dict |
| `api/services/telegram_capture.py` | `saved-because` claim cites its section (R13) |
| `mcp/server.py` | `cicada_write_claim` `evidence` parameter, dispatch, reply line |
| `api/models/schemas.py` | `EvidenceModel`, `ClaimModel.evidence`, `EpisodeSpan` |
| `api/routers/claims.py`, `api/services/transclusion_resolver.py` | project `evidence` |
| `api/routers/episodes.py` (new), `api/main.py` | `GET /episodes/{id}/span` (`api/routers/__init__.py` is an empty package marker — nothing to register there) |
| `api/tests/test_evidence.py`, `test_claims_evidence.py`, `test_evidence_extraction.py`, `test_evidence_agent_writes.py`, `test_episode_span_endpoint.py` (new); `test_link_recon.py`, `test_claim_reconciler.py` (extended) | tests |
| `CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md` | docs |

---

### Task 1: Schema + the evidence module — spans on `Claim`, located, hashed, round-tripped

**Files:**
- Modify: `api/services/claims.py:53-154` (`Claim`), `:124-125` (`to_dict`), `:127-154` (`from_dict`)
- Create: `api/services/evidence.py`
- Test: `api/tests/test_claims_evidence.py` (new), `api/tests/test_evidence.py` (new)

**Interfaces:**
- Produces: `claims.EVIDENCE_KINDS = ("user", "assistant", "page", "reasoning")`; `claims.Evidence(episode: str = "", start: int = -1, end: int = -1, kind: str = "reasoning", hash: str = "")` with `is_span()`, `to_dict()`, `from_dict()`; `Claim.evidence: list[Evidence]`.
- Produces: `evidence.body_hash(text) -> str`; `evidence.is_episode_id(doc_id) -> bool`; `evidence.source_path(memory_path, doc_id) -> Path | None`; `evidence.source_text(memory_path, doc_id) -> str | None`; `evidence.locate(text, quote, *, window=None, whole_word=False) -> tuple[int, int] | None`; `evidence.speaker_kind(text, start) -> str`; `evidence.reasoning(doc_id="", *, hash="") -> Evidence`; `evidence.verify(memory_path, doc_id, quote, *, text=None, window=None, whole_word=False) -> Evidence`; `evidence.verify_many(memory_path, items) -> list[Evidence]`; `evidence.attach_relationship_evidence(rel, episode_id, body, *, window=None) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_claims_evidence.py
"""G118 slice 1 — `Claim.evidence`: spans (offsets + hash), never copies.

Round-trips through the in-page ```claims block; a legacy claim without the
key parses to an empty list; `to_dict` omits an empty list (R7) so a page
rewrite never touches ~2,300 legacy claims for a field they do not have.
"""
from __future__ import annotations

from api.services.claims import EVIDENCE_KINDS, Claim, Evidence, parse_claims, write_claims


def test_evidence_kinds_are_the_four_the_g118_row_names():
    assert EVIDENCE_KINDS == ("user", "assistant", "page", "reasoning")


def test_claim_defaults_to_no_evidence_and_to_dict_omits_the_key():
    c = Claim(id="clm_x", text="alpha-project uses sqlite-vec")
    assert c.evidence == []
    assert "evidence" not in c.to_dict()
    assert Claim.from_dict(c.to_dict()) == c


def test_evidence_round_trips_through_the_claims_block():
    ev = [
        Evidence(episode="ep_2026-09-01_001", start=12, end=40, kind="user", hash="0123456789ab"),
        Evidence(episode="ep_2026-09-02_003", start=-1, end=-1, kind="reasoning", hash="abcdefabcdef"),
    ]
    c = Claim(id="clm_x", text="alpha-project uses sqlite-vec", subject="alpha-project",
              predicate="uses", object="sqlite-vec", evidence=ev)
    body = write_claims("## Summary\nA project.", [c])
    back = parse_claims(body)
    assert back == [c]
    assert back[0].evidence[0].is_span() is True
    assert back[0].evidence[1].is_span() is False
    assert "start: 12" in body and "hash: 0123456789ab" in body


def test_legacy_claim_without_evidence_parses_to_empty_list():
    body = (
        "```claims\n- id: clm_old\n  text: old belief\n  subject: alpha-project\n"
        "  predicate: uses\n  object: postgres\n```\n"
    )
    (c,) = parse_claims(body)
    assert c.evidence == []


def test_evidence_from_dict_is_forgiving_never_raising():
    # Unknown kind, junk offsets, missing keys: degrade to reasoning, never raise.
    assert Evidence.from_dict({"episode": "ep_x", "start": "a", "end": 5, "kind": "user"}) == Evidence(
        episode="ep_x", start=-1, end=-1, kind="reasoning", hash="")
    assert Evidence.from_dict({"kind": "banana", "start": 1, "end": 4}) == Evidence(
        episode="", start=-1, end=-1, kind="reasoning", hash="")
    assert Evidence.from_dict({"episode": "ep_x", "start": 3, "end": 3, "kind": "user"}).kind == "reasoning"
    assert Evidence.from_dict(None) == Evidence()
    # A non-mapping entry inside a claim's list is skipped, the rest kept.
    c = Claim.from_dict({"id": "clm_x", "text": "t", "evidence": ["junk", {"episode": "ep_y", "start": 0, "end": 2, "kind": "page", "hash": "h"}]})
    assert c.evidence == [Evidence(episode="ep_y", start=0, end=2, kind="page", hash="h")]
```

```python
# api/tests/test_evidence.py
"""G118 slice 1 — `api.services.evidence`: the engine-free span module.

Every fixture is synthetic. Covers R1 (text normalisation), R2 (hash), R3
(document resolution incl. path-traversal refusal), R4 (speaker kind), R5
(the locate ladder and its refusal to go fuzzy), R6 (reasoning fallback).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from api.services import evidence, markdown_parser
from api.services.claims import Claim, Evidence, write_claims

EPISODE = (
    "user: I moved the alpha-project index to sqlite-vec last week.\n"
    "assistant: Noted — sqlite-vec replaces LEANN for alpha-project.\n"
    "user: Yes,   and bob-example   reviewed the migration."
)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md",
                          {"id": "ep_2026-09-01_001", "processed": False}, EPISODE)
    page_body = "## Summary\nSaved bookmark.\n\n## Description\nA guide to ROS and sqlite-vec for robotics."
    markdown_parser.write(memory / "entities" / "media-ros-guide.md",
                          {"name": "ROS guide", "type": "media"},
                          write_claims(page_body, [Claim(id="clm_a", text="x")]))
    return memory


def test_body_hash_is_sha256_twelve_hex():
    assert evidence.body_hash("abc") == hashlib.sha256(b"abc").hexdigest()[:12]
    assert evidence.body_hash("") == hashlib.sha256(b"").hexdigest()[:12]


def test_source_text_is_the_parsed_body_for_an_episode(tmp_path):
    memory = _bank(tmp_path)
    assert evidence.source_text(memory, "ep_2026-09-01_001") == EPISODE  # R1: parse().body, already stripped


def test_source_text_strips_the_claims_block_for_an_entity_page(tmp_path):
    memory = _bank(tmp_path)
    text = evidence.source_text(memory, "media-ros-guide")
    assert text.endswith("for robotics.")
    assert "```claims" not in text
    # R1: appending another claim must not change the evidence text.
    fp = memory / "entities" / "media-ros-guide.md"
    parsed = markdown_parser.parse(fp)
    markdown_parser.write(fp, parsed.frontmatter, write_claims(parsed.body, [Claim(id="clm_a", text="x"), Claim(id="clm_b", text="y")]))
    assert evidence.source_text(memory, "media-ros-guide") == text


def test_source_path_refuses_traversal_and_unknown_docs(tmp_path):
    memory = _bank(tmp_path)
    assert evidence.source_path(memory, "../episodes/ep_2026-09-01_001") is None
    assert evidence.source_path(memory, "ep_2026-09-01_001/../../x") is None
    assert evidence.source_path(memory, "") is None
    assert evidence.source_path(memory, "ep_2026-01-01_999") is None
    assert evidence.source_text(memory, "nope") is None


def test_locate_exact_then_normalised_then_case_insensitive_never_fuzzy():
    assert evidence.locate(EPISODE, "moved the alpha-project index") == (8, 37)
    # whitespace-normalised: the quote collapses the body's runs of spaces
    s, e = evidence.locate(EPISODE, "Yes, and bob-example reviewed")
    assert EPISODE[s:e] == "Yes,   and bob-example   reviewed"
    # case-insensitive
    s, e = evidence.locate(EPISODE, "SQLITE-VEC REPLACES leann")
    assert EPISODE[s:e] == "sqlite-vec replaces LEANN"
    # never fuzzy: one wrong word is a miss
    assert evidence.locate(EPISODE, "moved the beta-project index") is None
    assert evidence.locate(EPISODE, "") is None
    assert evidence.locate("", "x") is None


def test_locate_prefers_the_window_then_falls_back_to_first_occurrence():
    text = "user: alpha-project\nassistant: alpha-project again\nuser: alpha-project once more"
    first = text.find("alpha-project")
    third = text.rfind("alpha-project")
    assert evidence.locate(text, "alpha-project") == (first, first + 13)
    assert evidence.locate(text, "alpha-project", window=(40, len(text))) == (third, third + 13)
    # window contains no occurrence -> first overall, not None
    assert evidence.locate(text, "alpha-project", window=(0, 3)) == (first, first + 13)


def test_locate_clips_overlong_quotes_to_240_chars():
    body = "user: " + ("x" * 300) + " tail"
    quote = "x" * 300
    s, e = evidence.locate(body, quote)
    assert (s, e) == (6, 6 + evidence.MAX_QUOTE_CHARS)


def test_locate_whole_word_never_matches_inside_a_longer_token():
    text = "Google ships Go tooling"
    assert evidence.locate(text, "Go", whole_word=True) == (13, 15)
    assert evidence.locate("Google only", "Go", whole_word=True) is None
    assert evidence.locate("Google only", "Go") == (0, 2)  # the plain rung is substring


def test_speaker_kind_follows_the_last_turn_marker_and_defaults_to_user():
    assert evidence.speaker_kind(EPISODE, EPISODE.find("moved")) == "user"
    assert evidence.speaker_kind(EPISODE, EPISODE.find("replaces")) == "assistant"
    assert evidence.speaker_kind(EPISODE, EPISODE.find("reviewed")) == "user"
    assert evidence.speaker_kind("AI: done\nHuman: thanks", 4) == "assistant"
    assert evidence.speaker_kind("AI: done\nHuman: thanks", 16) == "user"
    assert evidence.speaker_kind("system: project notes", 8) == "user"  # R4
    assert evidence.speaker_kind("no markers at all here", 5) == "user"  # R4
    # R4 "at": a quote that begins ON the marker line's first character still
    # belongs to that marker, not to the previous turn.
    assert evidence.speaker_kind(EPISODE, EPISODE.find("assistant:")) == "assistant"
    # R4: `unknown:` (an export message with no role) resets to user rather
    # than inheriting the assistant marker above it.
    assert evidence.speaker_kind("assistant: a\nunknown: b", 16) == "user"


def test_verify_returns_a_span_for_an_episode_and_page_kind_for_an_entity(tmp_path):
    memory = _bank(tmp_path)
    ev = evidence.verify(memory, "ep_2026-09-01_001", "sqlite-vec replaces LEANN")
    assert ev == Evidence(episode="ep_2026-09-01_001", start=EPISODE.find("sqlite-vec replaces"),
                          end=EPISODE.find("LEANN") + 5, kind="assistant", hash=evidence.body_hash(EPISODE))
    page = evidence.verify(memory, "media-ros-guide", "ROS", whole_word=True)
    text = evidence.source_text(memory, "media-ros-guide")
    assert page.kind == "page" and text[page.start:page.end] == "ROS" and page.hash == evidence.body_hash(text)


def test_verify_falls_back_to_reasoning_never_a_faked_span(tmp_path):
    memory = _bank(tmp_path)
    miss = evidence.verify(memory, "ep_2026-09-01_001", "something nobody said")
    assert miss == Evidence(episode="ep_2026-09-01_001", start=-1, end=-1, kind="reasoning",
                            hash=evidence.body_hash(EPISODE))  # doc readable -> hash kept
    gone = evidence.verify(memory, "ep_2026-01-01_999", "anything")
    assert gone == Evidence(episode="ep_2026-01-01_999", start=-1, end=-1, kind="reasoning", hash="")
    assert evidence.verify(memory, "", "anything") == Evidence()
    assert evidence.reasoning("ep_x") == Evidence(episode="ep_x", start=-1, end=-1, kind="reasoning", hash="")


def test_verify_with_inline_text_needs_no_disk(tmp_path):
    ev = evidence.verify(None, "ep_2026-09-01_001", "bob-example reviewed", text=EPISODE)
    assert EPISODE[ev.start:ev.end] == "bob-example reviewed" and ev.kind == "user"


def test_verify_many_skips_junk_and_dedupes(tmp_path):
    memory = _bank(tmp_path)
    out = evidence.verify_many(memory, [
        {"episode": "ep_2026-09-01_001", "quote": "moved the alpha-project index"},
        {"episode": "ep_2026-09-01_001", "quote": "moved the alpha-project index"},
        {"quote": "no episode"},
        "junk",
        {"episode": "ep_2026-09-01_001", "quote": "not in there"},
    ])
    assert len(out) == 2
    assert out[0].is_span() and out[1].kind == "reasoning"
    assert evidence.verify_many(memory, None) == []
    # An optional `window` item key (internal — writers that know the section)
    # prefers an occurrence inside it: "alpha-project" first appears at 18
    # (line 1) and again at 112 (line 2); the window selects the second.
    (win,) = evidence.verify_many(memory, [
        {"episode": "ep_2026-09-01_001", "quote": "alpha-project", "window": [60, len(EPISODE)]}])
    assert win.is_span() and win.start >= 60 and EPISODE[win.start:win.end] == "alpha-project"


def test_attach_relationship_evidence_pops_the_quote_and_records_offsets():
    rel = {"source": "alpha-project", "target": "sqlite-vec", "label": "uses",
           "evidence_quote": "moved the alpha-project index to sqlite-vec"}
    evidence.attach_relationship_evidence(rel, "ep_2026-09-01_001", EPISODE, window=(0, 70))
    assert "evidence_quote" not in rel  # spans, not copies — even in the transient dict
    (ev,) = rel["evidence"]
    assert ev["kind"] == "user" and EPISODE[ev["start"]:ev["end"]] == "moved the alpha-project index to sqlite-vec"
    assert ev["hash"] == evidence.body_hash(EPISODE)
    bare = {"source": "a", "target": "b", "label": "uses"}
    evidence.attach_relationship_evidence(bare, "ep_2026-09-01_001", EPISODE)
    assert bare["evidence"] == [{"episode": "ep_2026-09-01_001", "start": -1, "end": -1,
                                 "kind": "reasoning", "hash": evidence.body_hash(EPISODE)}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_claims_evidence.py api/tests/test_evidence.py -q -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'EVIDENCE_KINDS' from 'api.services.claims'` and `ModuleNotFoundError`/`ImportError` for `api.services.evidence`.

- [ ] **Step 3: Add `Evidence` and `Claim.evidence` to `api/services/claims.py`**

Insert after the `_CLAIMS_BLOCK_RE` definition (`claims.py:50`) and before `class Claim`:

```python
# G118 slice 1 — the four evidence kinds. `user`/`assistant` are spans into a
# conversation episode, attributed by the turn marker at or before the span
# (R4); `page` is a span into an entity page's prose (a saved link's stored
# description — link recon); `reasoning` is the contributor's own inference
# and carries no offsets. The set is closed on purpose: a viewer renders each
# kind differently, and G100's derived-span class, if it ever ships, will be
# a fifth value rather than a flag on one of these.
EVIDENCE_KINDS = ("user", "assistant", "page", "reasoning")


@dataclass
class Evidence:
    """WHERE a claim came from — offsets into stored text, never a copy (G118).

    ``episode`` is a source-document id (R3): ``ep_*`` resolves to
    ``episodes/<id>.md``; anything else to ``entities/<id>.md`` (a ``page``
    span cites the media entity that holds the description). ``start``/``end``
    are character offsets into that document's evidence text — the body as
    ``markdown_parser.parse`` returns it, with the ```claims fence stripped
    for an entity page (R1) — and ``hash`` is ``sha256[:12]`` of that text
    (R2) so a rewritten source reads as ``stale`` instead of mis-highlighting.
    A ``reasoning`` entry has ``start == end == -1``: the contributor cited
    itself, and nothing in the bank says it in so many words.
    """

    episode: str = ""
    start: int = -1
    end: int = -1
    kind: str = "reasoning"
    hash: str = ""

    def is_span(self) -> bool:
        return self.kind != "reasoning" and 0 <= self.start < self.end

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "Evidence":
        """Forgiving on purpose: provenance must never make a claim unparseable
        (a bad entry degrades to ``reasoning``; strict mode is for the block,
        not for one evidence row)."""
        data = dict(data or {}) if isinstance(data, dict) else {}
        kind = str(data.get("kind") or "reasoning")
        try:
            start = int(data.get("start", -1))
            end = int(data.get("end", -1))
        except (TypeError, ValueError):
            start, end = -1, -1
        if kind not in EVIDENCE_KINDS or kind == "reasoning" or start < 0 or end <= start:
            kind, start, end = "reasoning", -1, -1
        return cls(
            episode=str(data.get("episode") or ""),
            start=start,
            end=end,
            kind=kind,
            hash=str(data.get("hash") or ""),
        )
```

In `class Claim`, after the `decayed_through` field (`claims.py:108`) add:

```python
    # G118 slice 1 — evidence spans. Empty on every claim written before the
    # field existed (no backfill, R6); at least one entry on every claim
    # written since, `reasoning` when the writer had no source text.
    evidence: list[Evidence] = field(default_factory=list)
```

Replace `to_dict` (`claims.py:124-125`):

```python
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # R7: omit an empty evidence list so `write_claims` re-rendering a page
        # never diffs ~2,300 legacy claims for a field they do not have.
        if not data.get("evidence"):
            data.pop("evidence", None)
        return data
```

In `from_dict`, after `decayed_through=_opt_str(data.get("decayed_through")),` add:

```python
            evidence=[
                Evidence.from_dict(e) for e in (data.get("evidence") or []) if isinstance(e, dict)
            ],
```

- [ ] **Step 4: Create `api/services/evidence.py`**

```python
"""G118 slice 1 — evidence spans: WHERE in the stored text a belief came from.

The G118 row's first layer, "spans, not copies": a claim records character
offsets into text Cicada already holds — an episode body, or a media page's
stored description — plus a hash of that text, and never a quoted copy. The
bank already has the words; the claim only needs to point. That keeps the
ledger ids-only (G113), keeps a claim's YAML small, and makes staleness
detectable (R2) instead of silently mis-highlighting.

Three writers call :func:`verify`: Stage-1 extraction (the quote the model
says it relied on, against the exact body it chunked — R11), the agentic
write path (an agent citing what the person just said, through
``cicada_write_claim``), and link recon (the surface form it grounded on,
against the media page's prose — R12). One reader, the ``episodes`` router,
calls :func:`source_text` to slice a span back out.

Rails this module enforces rather than documents:

* **Engine-free** (G80): imports ``markdown_parser`` and ``claims`` only. A
  verification is string search over one parsed file.
* **Never fuzzy** (R5): exact, then whitespace-normalised, then
  case-insensitive — and an unlocatable quote becomes ``reasoning``, never a
  guessed span. Provenance must never block memory, so nothing here raises.
* **Only bank text** (G48): :func:`source_path` resolves ids inside the bank
  and refuses anything that is not a bare document id. Transcripts under
  ``~/.claude`` are never opened.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

from api.services import markdown_parser
from api.services.claims import EVIDENCE_KINDS, Evidence, strip_claims_block

__all__ = [
    "EVIDENCE_KINDS", "MAX_QUOTE_CHARS", "body_hash", "is_episode_id", "source_path",
    "source_text", "locate", "speaker_kind", "reasoning", "verify", "verify_many",
    "attach_relationship_evidence",
]

# The longest quote a writer may cite. A longer one is clipped, not refused:
# the clipped head is still a verbatim substring, so the span is simply
# shorter than the writer offered. 240 chars is a sentence or two — enough to
# highlight, small enough that the prompt never asks for a paragraph.
MAX_QUOTE_CHARS = 240

# A source-document id (R3): a bare stem, no separators that could escape the
# bank. `episode_ids.EPISODE_ID_RE` is stricter for episodes; media ids are
# `media-<slug>`; both fit here.
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_EPISODE_PREFIX = "ep_"

# R4: the turn markers Cicada's own writers produce. Imported conversations
# write `<role>: <text>` per message (api/routers/conversations.py:792, the
# body at :911/:934), roles user/assistant/system and `unknown` for a message
# the export did not attribute; `human`/`ai` are accepted for hand-written or
# third-party episodes. `system` is the person's configured context and
# `unknown` is unattributed, so both count as `user` below — the only way a
# span is labelled the model's is a line that says so.
_TURN_RE = re.compile(r"^(user|human|assistant|ai|system|unknown)\s*:", re.IGNORECASE)
_ASSISTANT_ROLES = frozenset({"assistant", "ai"})


def body_hash(text: str) -> str:
    """R2: ``sha256[:12]`` of the evidence text — same width as the episode
    ``content_hash`` the MCP seam already stamps."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def is_episode_id(doc_id: str) -> bool:
    return (doc_id or "").startswith(_EPISODE_PREFIX)


def source_path(memory_path: Path | None, doc_id: str) -> Path | None:
    """Resolve a source-document id to its file inside the bank, or ``None``.

    ``ep_*`` lives under ``episodes/``; everything else under ``entities/``
    (R3). An id that is not a bare stem is refused outright — the only text a
    span may index is text Cicada stored (G48), and this is the one place
    that rule is enforced for every reader and writer.
    """
    doc_id = (doc_id or "").strip()
    if memory_path is None or not _DOC_ID_RE.match(doc_id):
        return None
    subdir = "episodes" if is_episode_id(doc_id) else "entities"
    path = Path(memory_path) / subdir / f"{doc_id}.md"
    return path if path.is_file() else None


def source_text(memory_path: Path | None, doc_id: str) -> str | None:
    """The evidence text of a document (R1): the parsed body for an episode;
    for an entity page, the body with the ```claims fence stripped — so the
    claim that cites a page never stales its own span by being written."""
    path = source_path(memory_path, doc_id)
    if path is None:
        return None
    try:
        body = markdown_parser.parse(path).body
    except Exception:
        return None
    return body if is_episode_id(doc_id) else strip_claims_block(body)


def _pattern(quote: str, *, whole_word: bool, flags: int = 0) -> re.Pattern[str]:
    core = r"\s+".join(re.escape(tok) for tok in quote.split())
    if whole_word:
        core = rf"(?<![A-Za-z0-9]){core}(?![A-Za-z0-9])"
    return re.compile(core, flags)


def _exact_matches(text: str, quote: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    i = text.find(quote)
    while i != -1:
        out.append((i, i + len(quote)))
        i = text.find(quote, i + 1)
    return out


def _first(matches: list[tuple[int, int]], window: tuple[int, int] | None) -> tuple[int, int] | None:
    if window is not None:
        lo, hi = window
        for s, e in matches:
            if s >= lo and e <= hi:
                return (s, e)
    return matches[0] if matches else None


def locate(
    text: str,
    quote: str,
    *,
    window: tuple[int, int] | None = None,
    whole_word: bool = False,
) -> tuple[int, int] | None:
    """R5: find ``quote`` in ``text`` — exact, then whitespace-normalised,
    then case-insensitive — and stop. ``window`` (a Stage-1 chunk) prefers an
    occurrence inside it over the first in the document. ``whole_word``
    refuses a hit inside a longer token ("Go" in "Google") and skips the
    plain-substring rung for the same reason. ``None`` means "not there".
    """
    quote = (quote or "").strip()
    if not quote or not text:
        return None
    if len(quote) > MAX_QUOTE_CHARS:
        quote = quote[:MAX_QUOTE_CHARS].rstrip()
    rungs: list[list[tuple[int, int]]] = []
    if not whole_word:
        rungs.append(_exact_matches(text, quote))
    rungs.append([(m.start(), m.end()) for m in _pattern(quote, whole_word=whole_word).finditer(text)])
    rungs.append([
        (m.start(), m.end())
        for m in _pattern(quote, whole_word=whole_word, flags=re.IGNORECASE).finditer(text)
    ])
    for matches in rungs:
        hit = _first(matches, window)
        if hit is not None:
            return hit
    return None


def speaker_kind(text: str, start: int) -> str:
    """R4: ``assistant`` when the last turn marker at or before ``start`` is
    the model's; ``user`` otherwise — including no marker at all, because
    every marker-less writer captures the person's own input.

    Scans through the END of the line that contains ``start`` (not just
    ``text[:start]``): a marker only ever matches at a line's first column,
    which is at or before ``start`` by construction, so this is exactly "at
    or before" — and it is what makes a quote that begins with
    ``assistant: …`` land on that marker instead of the previous turn's.
    """
    text = text or ""
    start = max(int(start), 0)
    line_end = text.find("\n", start)
    head = text if line_end == -1 else text[:line_end]
    kind = "user"
    for line in head.splitlines():
        m = _TURN_RE.match(line)
        if m:
            kind = "assistant" if m.group(1).lower() in _ASSISTANT_ROLES else "user"
    return kind


def reasoning(doc_id: str = "", *, hash: str = "") -> Evidence:  # noqa: A002 - the field's own name
    """R6: the contributor cited itself. ``hash`` is kept when the document
    was readable so a viewer can still open it."""
    return Evidence(episode=(doc_id or "").strip(), start=-1, end=-1, kind="reasoning", hash=hash)


def verify(
    memory_path: Path | None,
    doc_id: str,
    quote: str,
    *,
    text: str | None = None,
    window: tuple[int, int] | None = None,
    whole_word: bool = False,
) -> Evidence:
    """Turn a cited quote into an :class:`Evidence` — a span when the quote is
    in the document, ``reasoning`` when it is not. Never raises.

    ``text`` short-circuits the disk read when the caller already holds the
    evidence text (Stage 1 holds the body it chunked — R11). Kind is the
    speaker for an episode and ``page`` for an entity document.
    """
    doc_id = (doc_id or "").strip()
    if not doc_id:
        return reasoning("")
    if text is None:
        text = source_text(memory_path, doc_id)
    if text is None:
        return reasoning(doc_id)
    digest = body_hash(text)
    span = locate(text, quote, window=window, whole_word=whole_word)
    if span is None:
        return reasoning(doc_id, hash=digest)
    start, end = span
    kind = speaker_kind(text, start) if is_episode_id(doc_id) else "page"
    return Evidence(episode=doc_id, start=start, end=end, kind=kind, hash=digest)


def verify_many(memory_path: Path | None, items: Iterable | None) -> list[Evidence]:
    """The agent-write shape: ``[{episode, quote}, ...]`` → deduped evidence.
    Entries without an ``episode`` or that are not mappings are skipped — an
    agent's malformed citation must not fail its claim. An optional
    ``window: [start, end]`` per item is an internal hint for writers that
    know which section the words are in (the Telegram ``saved-because``
    claim, R13); the MCP schema does not advertise it and an agent passing
    it is harmless."""
    out: list[Evidence] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("episode") or "").strip()
        if not doc_id:
            continue
        raw_window = item.get("window")
        window: tuple[int, int] | None = None
        if isinstance(raw_window, (list, tuple)) and len(raw_window) == 2:
            try:
                window = (int(raw_window[0]), int(raw_window[1]))
            except (TypeError, ValueError):
                window = None
        ev = verify(memory_path, doc_id, str(item.get("quote") or ""), window=window)
        if ev not in out:
            out.append(ev)
    return out


def attach_relationship_evidence(
    rel: dict, episode_id: str, body: str, *, window: tuple[int, int] | None = None
) -> None:
    """Stage 1: consume ``rel["evidence_quote"]`` and set ``rel["evidence"]``.

    The quote is POPPED, not kept — spans, not copies, holds even for the
    transient extraction dict. ``body`` is the full episode content
    ``extract`` chunked (R11), so offsets land in the stored body and the
    hash is the stored hash without a second read. Mutates in place.
    """
    quote = rel.pop("evidence_quote", None)
    ev = verify(None, episode_id, str(quote or ""), text=body, window=window)
    rel["evidence"] = [ev.to_dict()]
```

- [ ] **Step 5: Run the new tests and the claim-layer regression set**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_claims_evidence.py api/tests/test_evidence.py api/tests/test_claims.py api/tests/test_claims_corruption_guard.py api/tests/test_claim_reconciler.py api/tests/test_claim_pipeline.py api/tests/test_decay_watermark_migration.py api/tests/test_claim_endpoints.py -q -p no:cacheprovider`
Expected: all PASS. `test_claims.py::…to_dict…` still passes because an empty `evidence` is omitted (R7) and `from_dict` restores the default.

- [ ] **Step 6: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && git add api/services/claims.py api/services/evidence.py api/tests/test_claims_evidence.py api/tests/test_evidence.py && git commit -m "feat(claims): evidence spans on Claim — offsets + hash into stored bodies, never copies (G118 slice 1)"
```

---

### Task 2: Stage-1 capture — the extractor cites, the pipeline verifies, reinforcement merges

**Files:**
- Modify: `api/services/entity_extractor.py:42-48` (prompt relationships object), `:120-122` (relationship guideline), `:188-203` (`_chunk_content`), `:326` and `:337-353` (chunk loop + rel stamping in `extract`), `:459-522` (`entities_to_claims`)
- Modify: `api/services/claim_reconciler.py:143-162` (`_reinforce`)
- Test: `api/tests/test_evidence_extraction.py` (new); extend `api/tests/test_claim_reconciler.py`

**Interfaces:**
- Produces: `entity_extractor._chunk_spans(content) -> list[tuple[int, int]]`; `_chunk_content` unchanged in behaviour (now `[content[s:e] for s, e in _chunk_spans(content)]`).
- Extraction result: each relationship dict carries `evidence: [dict]` (one verified entry) and never `evidence_quote`.
- `entities_to_claims` sets `Claim.evidence` from `rel["evidence"]`; a duplicate claim id (overlapping chunks) merges evidence into the first claim.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_evidence_extraction.py
"""G118 slice 1 — Stage-1 extraction cites the passage; the pipeline verifies.

Hermetic: `litellm.acompletion` is monkeypatched (the pattern from
test_extractor_robustness.py). The fake model returns `evidence_quote` values
that are exact, whitespace-mangled, absent, and fabricated, over a two-turn
synthetic episode, and the assertions are on offsets into the stored body.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from api.config import Settings
from api.services import entity_extractor as ex
from api.services import evidence
from api.services.claim_reconciler import _reinforce
from api.services.claims import Claim, Evidence

BODY = (
    "user: We moved alpha-project onto sqlite-vec in August.\n"
    "assistant: Understood. alpha-project depends on EmbeddingGemma for its vectors.\n"
    "user: And bob-example reviews every migration."
)


def _resp(payload: dict):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def _fake(payload: dict):
    async def fake_acompletion(**kw):
        return _resp(payload)
    return fake_acompletion


def _extract(monkeypatch, payload: dict, body: str = BODY) -> dict:
    monkeypatch.setattr(ex.litellm, "acompletion", _fake(payload))
    out = asyncio.run(ex.extract(
        [{"id": "ep_2026-09-01_001", "content": body, "timestamp": "2026-09-01T10:00:00+00:00", "origin": "claude-code"}],
        Settings(litellm_model="m"),
    ))
    assert len(out) == 1
    return out[0]


def test_prompt_asks_for_a_verbatim_evidence_quote_on_every_relationship():
    prompt = ex.EXTRACTION_SYSTEM_PROMPT
    assert '"evidence_quote"' in prompt
    assert "verbatim" in prompt.lower()
    assert "240" in prompt


def test_exact_quote_becomes_a_user_span_into_the_stored_body(monkeypatch):
    res = _extract(monkeypatch, {"entities": [], "relationships": [
        {"source": "alpha-project", "target": "sqlite-vec", "label": "uses",
         "evidence_quote": "moved alpha-project onto sqlite-vec"}]})
    (rel,) = res["relationships"]
    assert "evidence_quote" not in rel
    (ev,) = rel["evidence"]
    assert ev["episode"] == "ep_2026-09-01_001" and ev["kind"] == "user"
    assert BODY[ev["start"]:ev["end"]] == "moved alpha-project onto sqlite-vec"
    assert ev["hash"] == evidence.body_hash(BODY)


def test_assistant_turn_quote_is_labelled_assistant_and_normalised_whitespace_still_locates(monkeypatch):
    res = _extract(monkeypatch, {"entities": [], "relationships": [
        {"source": "alpha-project", "target": "EmbeddingGemma", "label": "depends on",
         "evidence_quote": "alpha-project   depends on\nEmbeddingGemma"}]})
    (ev,) = res["relationships"][0]["evidence"]
    assert ev["kind"] == "assistant"
    assert BODY[ev["start"]:ev["end"]] == "alpha-project depends on EmbeddingGemma"


def test_missing_or_fabricated_quote_records_reasoning_never_a_faked_span(monkeypatch):
    res = _extract(monkeypatch, {"entities": [], "relationships": [
        {"source": "bob-example", "target": "alpha-project", "label": "reviews"},
        {"source": "bob-example", "target": "sqlite-vec", "label": "prefers",
         "evidence_quote": "bob-example prefers sqlite-vec over everything"}]})
    kinds = [r["evidence"][0]["kind"] for r in res["relationships"]]
    assert kinds == ["reasoning", "reasoning"]
    for r in res["relationships"]:
        assert r["evidence"][0]["start"] == -1 and r["evidence"][0]["end"] == -1
        assert r["evidence"][0]["hash"] == evidence.body_hash(BODY)  # doc known -> hash kept


def test_chunked_episode_offsets_are_into_the_whole_body_not_the_chunk(monkeypatch):
    # Two chunks: the quote sits deep in chunk 2 (and also, as bait, at the very top).
    filler = ("user: filler line about nothing in particular.\n" * 400)
    body = "user: alpha-project uses sqlite-vec.\n" + filler + "assistant: Yes, alpha-project uses sqlite-vec."
    spans = ex._chunk_spans(body)
    assert len(spans) >= 2 and [body[s:e] for s, e in spans] == ex._chunk_content(body)
    calls = {"n": 0}

    async def fake(**kw):
        calls["n"] += 1
        chunk = kw["messages"][-1]["content"]
        if chunk.startswith("user: alpha-project"):
            return _resp({"entities": [], "relationships": []})
        return _resp({"entities": [], "relationships": [
            {"source": "alpha-project", "target": "sqlite-vec", "label": "uses",
             "evidence_quote": "alpha-project uses sqlite-vec"}]})

    monkeypatch.setattr(ex.litellm, "acompletion", fake)
    out = asyncio.run(ex.extract(
        [{"id": "ep_2026-09-01_002", "content": body, "timestamp": "t", "origin": "x"}], Settings(litellm_model="m")))
    rels = out[0]["relationships"]
    assert calls["n"] == len(spans) and len(rels) == len(spans) - 1
    (ev,) = rels[-1]["evidence"]
    # The window preferred the occurrence inside the LAST chunk, not the bait at offset 6.
    assert ev["start"] > spans[-1][0] and ev["kind"] == "assistant"
    assert body[ev["start"]:ev["end"]] == "alpha-project uses sqlite-vec"


def test_entities_to_claims_carries_evidence_and_merges_duplicate_ids():
    ev_a = {"episode": "ep_2026-09-01_001", "start": 9, "end": 44, "kind": "user", "hash": "h"}
    ev_b = {"episode": "ep_2026-09-01_001", "start": 80, "end": 100, "kind": "assistant", "hash": "h"}
    extracted = [{"episode_id": "ep_2026-09-01_001", "origin": "claude-code", "entities": [], "relationships": [
        {"source": "alpha-project", "target": "sqlite-vec", "label": "uses", "source_episode": "ep_2026-09-01_001",
         "source_episode_timestamp": "2026-09-01T10:00:00+00:00", "evidence": [ev_a]},
        {"source": "alpha-project", "target": "sqlite-vec", "label": "uses", "source_episode": "ep_2026-09-01_001",
         "source_episode_timestamp": "2026-09-01T10:00:00+00:00", "evidence": [ev_b]},
        {"source": "alpha-project", "target": "sqlite-vec", "label": "uses", "source_episode": "ep_2026-09-01_001",
         "source_episode_timestamp": "2026-09-01T10:00:00+00:00", "evidence": [ev_a]},
    ]}]
    (c,) = ex.entities_to_claims(extracted, memory_path=None)
    assert c.evidence == [Evidence.from_dict(ev_a), Evidence.from_dict(ev_b)]


def test_entities_to_claims_without_evidence_key_stays_legacy_shaped():
    extracted = [{"episode_id": "ep_2026-09-01_001", "origin": "claude-code", "entities": [], "relationships": [
        {"source": "alpha-project", "target": "sqlite-vec", "label": "uses", "source_episode": "ep_2026-09-01_001"}]}]
    (c,) = ex.entities_to_claims(extracted, memory_path=None)
    assert c.evidence == []


def test_reinforce_merges_spans_and_drops_a_redundant_reasoning_entry():
    span = Evidence(episode="ep_a", start=1, end=9, kind="user", hash="h1")
    existing = Claim(id="c1", text="t", subject="s", predicate="p", object="o", evidence=[span])
    incoming = Claim(id="c2", text="t", subject="s", predicate="p", object="o", evidence=[
        span,                                                              # duplicate -> once
        Evidence(episode="ep_a", start=-1, end=-1, kind="reasoning", hash="h1"),  # same doc, no span -> dropped
        Evidence(episode="ep_b", start=4, end=12, kind="assistant", hash="h2"),   # new span -> kept
        Evidence(episode="ep_c", start=-1, end=-1, kind="reasoning", hash=""),    # new doc reasoning -> kept
    ])
    _reinforce(existing, incoming)
    assert existing.evidence == [
        span,
        Evidence(episode="ep_b", start=4, end=12, kind="assistant", hash="h2"),
        Evidence(episode="ep_c", start=-1, end=-1, kind="reasoning", hash=""),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_evidence_extraction.py -q -p no:cacheprovider`
Expected: FAIL — the prompt assertion (`'"evidence_quote"' in prompt`), `AttributeError: module … has no attribute '_chunk_spans'`, and `KeyError: 'evidence'`.

- [ ] **Step 3: Extend the prompt in `api/services/entity_extractor.py`**

Replace the relationships object in `EXTRACTION_SYSTEM_PROMPT` (`:42-48`):

```python
  "relationships": [
    {
      "source": "Entity Name A",
      "target": "Entity Name B",
      "label": "specific relationship verb phrase",
      "evidence_quote": "the exact words from the transcript this relationship rests on (verbatim, at most 240 characters)"
    }
  ]
```

After the "Relationships are critical" guideline (`:120-122`, the last bullet) append one more bullet, keeping the closing `"""`:

```python
- EVIDENCE QUOTE (required on every relationship): copy the shortest passage of the transcript,
  VERBATIM and at most 240 characters, that states this relationship — the sentence the user or
  assistant actually wrote, not your paraphrase. If the relationship is your own inference across
  several passages and no single passage states it, omit evidence_quote entirely. Never invent one:
  a quote that is not in the transcript is discarded and the relationship is recorded as inference."""
```

- [ ] **Step 4: `_chunk_spans`, and verification inside `extract`**

Replace `_chunk_content` (`:188-203`) with:

```python
def _chunk_spans(content: str) -> list[tuple[int, int]]:
    """Chunk boundaries as ``(start, end)`` offsets into ``content``.

    Boundaries are unchanged from the original ``_chunk_content``; exposing
    them is what lets G118's evidence verification prefer a quote's
    occurrence inside the chunk the model actually saw (R11) while recording
    offsets into the WHOLE body — the stored text a viewer will slice.
    """
    if len(content) <= CHUNK_SIZE:
        return [(0, len(content))]
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(content):
        end = start + CHUNK_SIZE
        # Try to break at a newline near the boundary
        if end < len(content):
            newline_pos = content.rfind("\n", end - 200, end)
            if newline_pos > start:
                end = newline_pos + 1
        spans.append((start, end))
        start = end - CHUNK_OVERLAP
    return spans


def _chunk_content(content: str) -> list[str]:
    """Split long content into overlapping chunks."""
    return [content[s:e] for s, e in _chunk_spans(content)]
```

In `extract._do_process`, replace `chunks = _chunk_content(content)` (`:326`) with:

```python
        spans = _chunk_spans(content)
        chunks = [content[s:e] for s, e in spans]
```

and replace the chunk loop (`:339-342`):

```python
                for ci, chunk in enumerate(chunks):
                    parsed = await _extract_chunk(ep_id, chunk, ci, len(chunks), settings)
                    all_entities.extend(parsed.get("entities", []))
                    chunk_rels = [r for r in (parsed.get("relationships", []) or []) if isinstance(r, dict)]
                    # G118: verify the cited passage against the body this
                    # chunk came from, preferring the chunk window (R11). The
                    # quote is consumed here — nothing downstream sees it.
                    for rel in chunk_rels:
                        evidence.attach_relationship_evidence(rel, ep_id, content, window=spans[ci])
                    all_relationships.extend(chunk_rels)
```

Add `evidence` to the module's service imports (`:14`): `from api.services import decay_policy, engine_errors, evidence`. (`evidence` imports `markdown_parser` and `claims` only — no cycle with `entity_extractor`.)

- [ ] **Step 5: `entities_to_claims` carries and merges evidence**

In `entities_to_claims` (`:459-522`): import `Evidence` beside `Claim` (`from api.services.claims import Claim, Evidence`); replace `seen_ids: set[str] = set()` with `by_id: dict[str, Claim] = {}`; replace the duplicate check and append:

```python
            cid = _emit_claim_id(subject, predicate, obj, valid_from)
            rel_evidence = [
                Evidence.from_dict(e) for e in (rel.get("evidence") or []) if isinstance(e, dict)
            ]
            if cid in by_id:
                # Overlapping chunks re-emit the same triple; the first claim
                # wins and only gains the later chunk's evidence (G118).
                first = by_id[cid]
                for ev in rel_evidence:
                    if ev not in first.evidence:
                        first.evidence.append(ev)
                continue
            claim = Claim(
                id=cid,
                text=f"{source} {raw_label} {target}",
                subject=subject,
                predicate=predicate,
                object=obj,
                object_kind="node",
                observer="agent",
                context="general",
                epistemic="explicit",
                source_trust="agent_extracted",
                confidence=float(rel.get("confidence", 0.6) or 0.6),
                valid_from=valid_from or None,
                source_episodes=[ep] if ep else [],
                origin=origin,
                evidence=rel_evidence,
            )
            # The pre-normalization label (for the Stage-3 normalization audit).
            setattr(claim, "predicate_raw", raw_label)
            by_id[cid] = claim
            claims.append(claim)
```

- [ ] **Step 6: `_reinforce` merges evidence (R8)**

In `api/services/claim_reconciler.py:143-162`, after the `session_ids` merge (end of the function) append:

```python
    # G118 R8: a later conversation restating the fact adds its span; a
    # `reasoning` placeholder for a document the claim already cites is noise
    # (the earlier entry — span or not — already stands for that document).
    cited = {ev.episode for ev in existing.evidence}
    for ev in incoming.evidence or []:
        if ev in existing.evidence:
            continue
        if not ev.is_span() and ev.episode in cited:
            continue
        existing.evidence.append(ev)
        cited.add(ev.episode)
```

- [ ] **Step 7: Run the new tests and the Stage-1/claim regression set**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_evidence_extraction.py api/tests/test_extractor_robustness.py api/tests/test_claim_emission.py api/tests/test_m5_prep_consolidation.py api/tests/test_decay_writers.py api/tests/test_claim_reconciler.py api/tests/test_claim_pipeline.py api/tests/test_sleep_cycle_claims_wired.py api/tests/test_link_recon.py api/tests/test_agent_engine.py -q -p no:cacheprovider`
Expected: all PASS. `test_decay_writers.py:55` and `test_m5_prep_consolidation.py:53,95` assert on prompt substrings that this edit leaves intact.

- [ ] **Step 8: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && git add api/services/entity_extractor.py api/services/claim_reconciler.py api/tests/test_evidence_extraction.py && git commit -m "feat(extraction): Stage 1 cites a verbatim passage; the pipeline verifies it into an evidence span (G118 slice 1)"
```

---

### Task 3: Link recon cites the surface form on the page (`kind: page`)

**Files:**
- Modify: `api/services/link_recon.py:36-37` (imports), `:161-178` (`_build_about_claim`), `:331-340` (the append loop in `run_recon`)
- Test: extend `api/tests/test_link_recon.py`

**Interfaces:**
- Produces: `link_recon._page_evidence(media_id: str, page_text: str, ent: dict) -> list[Evidence]`; `_build_about_claim(..., evidence: list[Evidence] | None = None)`.

- [ ] **Step 1: Write the failing tests** — append to `api/tests/test_link_recon.py`:

```python
# --------------------------------------------------------------------------- #
# G118 slice 1 — an `about` claim cites the surface form on the page body
# --------------------------------------------------------------------------- #


def test_about_claim_carries_a_page_span_onto_the_media_entity(tmp_path):
    from api.services import evidence

    memory = _bank(tmp_path)
    _entity(memory, "ros", "ROS", "tool")
    _entity(memory, "knowledge-graphs", "Knowledge Graphs", "concept")
    _media(memory, "media-a", "Robotics Conf List", "https://a.example", saved_at="2026-01-01", description=ROBOTICS)
    _media(memory, "media-b", "Graph Intro", "https://b.example", saved_at="2026-01-02", description=GRAPHS)
    page_text_before = evidence.source_text(memory, "media-a")
    ents = [{"name": "ROS", "type": "tool", "aliases": []},
            {"name": "Knowledge Graphs", "type": "concept", "aliases": ["knowledge graph"]}]
    report = link_enrichment.BackfillReport()
    run(link_recon.run_recon(memory, _settings(memory), report, extract_fn=_extract_fixed(ents),
                             match_fn=_match_direct, indexer_factory=lambda mp: _Spy(), today=date(2026, 9, 3)))
    page_a = markdown_parser.parse(memory / "entities" / "media-a.md").body
    (about,) = [c for c in parse_claims(page_a) if c.predicate == "about"]
    (ev,) = about.evidence
    assert ev.kind == "page" and ev.episode == "media-a"
    text_now = evidence.source_text(memory, "media-a")
    assert text_now == page_text_before            # R1: writing the claim did not move the evidence text
    assert text_now[ev.start:ev.end] == "ROS" and ev.hash == evidence.body_hash(text_now)
    # media-b: the page says "knowledge graphs" in lowercase, so the name
    # "Knowledge Graphs" lands on the case-insensitive rung (R5) — the span is
    # the page's own casing, not the entity's.
    page_b = markdown_parser.parse(memory / "entities" / "media-b.md").body
    (about_b,) = [c for c in parse_claims(page_b) if c.predicate == "about"]
    (ev_b,) = about_b.evidence
    text_b = evidence.source_text(memory, "media-b")
    assert text_b[ev_b.start:ev_b.end] == "knowledge graphs"


def test_page_evidence_falls_back_to_reasoning_when_the_name_is_only_in_the_title():
    from api.services import evidence

    text = "## Summary\nSaved bookmark.\n\n## Description\nA guide to vectors."
    out = link_recon._page_evidence("media-z", text, {"name": "Vectorly", "aliases": ["Vector Ly"]})
    assert out == [evidence.reasoning("media-z", hash=evidence.body_hash(text))]
    out = link_recon._page_evidence("media-z", text, {"name": "Go", "aliases": []})
    assert out[0].kind == "reasoning"  # "Go" is not on the page as a whole word (R12)
```

Verified against the file: `link_enrichment.BackfillReport` (`link_enrichment.py:758-759`, a `@dataclass` whose every field has a default, so `BackfillReport()` is valid) is the object `run_recon(memory_path, settings, report, *, limit, extract_fn, match_fn, indexer_factory, engine, today)` (`link_recon.py:219-220`) mutates; `_bank`, `_entity`, `_media`, `_settings`, `_extract_fixed`, `_match_direct`, `_Spy`, `run`, `ROBOTICS`, `GRAPHS` and the `date` import all already exist at the top of `test_link_recon.py`. `_media` puts the description under `## Description` in the body, so `ROS` (in "ROS tutorials") and `knowledge graphs` are both on the R1 page text.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_link_recon.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'api.services.link_recon' has no attribute '_page_evidence'`; the first test fails on `about.evidence == []`.

- [ ] **Step 3: Implement**

In `api/services/link_recon.py` change the import lines (`:36-37`) to:

```python
from api.services import engine_errors, evidence, markdown_parser
from api.services.claims import Claim, Evidence
```

(`evidence` is cycle-free at module level for the same reason `markdown_parser` is: it imports only `markdown_parser` and `claims`.)

Give `_build_about_claim` (`:161-178`) a `spans` keyword (named `spans`, not `evidence`, so the module import is never shadowed) and add `_page_evidence` directly below it:

```python
def _build_about_claim(media_id: str, target_id: str, target_name: str, confidence: float,
                       episode: str, today: str, model: str,
                       spans: list[Evidence] | None = None) -> Claim:
    """R6: the claim lives on the MEDIA page, object is the target's node id.
    The id is deterministic in ``(media, target)`` so ``_append_claim``'s
    id-dedupe makes a re-run a no-op; confidence is capped at 0.7 because a
    blurb is weaker evidence than a conversation. ``about`` is not in the
    predicate seed, so the cardinality oracle treats it as multi-valued —
    many ``about`` objects on one link can never raise a conflict item.
    ``spans`` (G118 R12) is the surface-form evidence ``_page_evidence`` found."""
    return Claim(
        id=f"clm_about_{hashlib.sha1(f'{media_id}\x00{target_id}'.encode()).hexdigest()[:8]}",
        text=f"This saved page is about {target_name}.",
        subject=media_id, predicate="about", object=target_id, object_kind="node",
        observer="agent", context="general", epistemic="explicit", source_trust="agent_extracted",
        confidence=round(min(float(confidence or 0.5), 0.7), 2),
        valid_from=today, recorded_at=today,
        source_episodes=[episode] if episode else [],
        authored_by=model or "unknown", origin="sleep/link_recon",
        evidence=list(spans or []),
    )


def _page_evidence(media_id: str, page_text: str, ent: dict) -> list[Evidence]:
    """R12: the surface form recon grounded on, as a ``page`` span into the
    media page's prose — name first, then each alias, whole-word only (the
    whole-token rail ``_mentions`` applies to a single-token name; a
    multi-token surface is bounded the same way here, tighter than the
    phrase match ``attribute()`` accepts). A name present only in the
    frontmatter title, or only as scattered tokens, is ``reasoning``: a span
    must point at text that is actually there."""
    surfaces = [str(ent.get("name") or "")] + [str(a) for a in (ent.get("aliases") or [])]
    for surface in surfaces:
        span = evidence.locate(page_text, surface, whole_word=True)
        if span is not None:
            return [Evidence(episode=media_id, start=span[0], end=span[1], kind="page",
                             hash=evidence.body_hash(page_text))]
    return [evidence.reasoning(media_id, hash=evidence.body_hash(page_text))]
```

In `run_recon`, before `fp = memory_path / "entities" / f"{card.media_id}.md"` (`:331`) add:

```python
            # G118: evidence is located on the page text BEFORE any claim is
            # appended — R1 makes that text invariant to the append anyway,
            # but reading once per card keeps this one parse.
            page_text = evidence.source_text(memory_path, card.media_id) or ""
```

and change the claim construction (`:337-338`) to:

```python
                claim = _build_about_claim(card.media_id, target, name_of.get(target, target),
                                           ent.get("confidence", 0.5), card.episode, today.isoformat(), model,
                                           spans=_page_evidence(card.media_id, page_text, ent))
```

- [ ] **Step 4: Run the recon tests and the enrichment neighbours**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_link_recon.py api/tests/test_link_enrichment.py api/tests/test_link_backfill.py api/tests/test_sleep_link_backfill.py api/tests/test_maintenance_enrich_links.py api/tests/test_sources_about.py -q -p no:cacheprovider`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && git add api/services/link_recon.py api/tests/test_link_recon.py && git commit -m "feat(link-recon): about claims cite the surface form as a page span on the media entity (G118 slice 1)"
```

---

### Task 4: Agent writes — `cicada_write_claim` / `write_claim` take `{episode, quote}`; Telegram cites its reason

**Files:**
- Modify: `api/services/agentic_write.py:38` (imports), `:232-248` (signature), `:249-277` (docstring), `:336-352` (Claim build), `:405-411` (result dict)
- Modify: `mcp/server.py:311-316` (after `sources` in the tool schema), `:533-544` (dispatch), `:1086-1112` (`handle_write_claim`), `:1157-1161` (reply)
- Modify: `api/services/telegram_capture.py:296-327` (`_write_saved_because_claim`)
- Test: `api/tests/test_evidence_agent_writes.py` (new)

**Interfaces:**
- `agentic_write.write_claim(..., evidence: list[dict] | None = None)`; result dict gains `evidence: list[dict]` (the entries as written).
- MCP `cicada_write_claim` gains optional `evidence: [{episode, quote}]`; `handle_write_claim(..., evidence: list | None = None)`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_evidence_agent_writes.py
"""G118 slice 1 — an agent citing what the person said records a real span.

`write_claim(evidence=[{episode, quote}])` verifies each quote against the
stored episode body through the same `evidence.verify` Stage 1 uses; a write
without evidence is `reasoning` (R6). The MCP tool exposes the parameter and
tells the agent what happened. The Telegram `saved-because` claim cites its
own `## Saved because` section (R13).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from api.services import agentic_write, evidence, markdown_parser
from api.services.claims import Evidence, parse_claims

_REPO_ROOT = Path(__file__).resolve().parents[2]
BODY = "user: I want alpha-project on sqlite-vec from now on.\nassistant: Noted."


def _load_server():
    spec = importlib.util.spec_from_file_location("cicada_mcp_server_evidence", _REPO_ROOT / "mcp" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server_evidence"] = mod
    spec.loader.exec_module(mod)
    return mod


def _episode(memory: Path, ep_id: str = "ep_2026-09-01_001", body: str = BODY) -> None:
    (memory / "episodes").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", {"id": ep_id, "processed": False}, body)


def test_write_claim_with_a_verified_quote_records_a_user_span(tmp_path):
    _episode(tmp_path)
    result = agentic_write.write_claim(
        tmp_path, "alpha-project", "uses", "sqlite-vec", observer="rodrigo",
        source_episode="ep_2026-09-01_001",
        evidence=[{"episode": "ep_2026-09-01_001", "quote": "alpha-project on sqlite-vec from now on"}],
    )
    assert result["action"] == "written"
    (c,) = parse_claims(markdown_parser.parse(tmp_path / "entities" / "alpha-project.md").body)
    (ev,) = c.evidence
    assert ev.kind == "user" and BODY[ev.start:ev.end] == "alpha-project on sqlite-vec from now on"
    assert ev.hash == evidence.body_hash(BODY)
    assert result["evidence"] == [ev.to_dict()]


def test_write_claim_without_evidence_is_reasoning_on_the_source_episode(tmp_path):
    _episode(tmp_path)
    agentic_write.write_claim(tmp_path, "alpha-project", "uses", "sqlite-vec", observer="agent",
                              source_episode="ep_2026-09-01_001")
    (c,) = parse_claims(markdown_parser.parse(tmp_path / "entities" / "alpha-project.md").body)
    # R6: reasoning on the source episode, hash kept because the episode is readable
    assert c.evidence == [Evidence(episode="ep_2026-09-01_001", start=-1, end=-1, kind="reasoning",
                                   hash=evidence.body_hash(BODY))]
    # and with no source episode at all, an anonymous reasoning entry (R6): never an empty list
    agentic_write.write_claim(tmp_path, "bob-example", "prefers", "dark mode", observer="agent")
    (b,) = parse_claims(markdown_parser.parse(tmp_path / "entities" / "bob-example.md").body)
    assert b.evidence == [Evidence()]


def test_write_claim_with_an_unverifiable_quote_still_writes_as_reasoning(tmp_path):
    _episode(tmp_path)
    result = agentic_write.write_claim(
        tmp_path, "alpha-project", "uses", "sqlite-vec", observer="agent",
        evidence=[{"episode": "ep_2026-09-01_001", "quote": "words nobody said"}],
    )
    assert result["action"] == "written"
    assert result["evidence"][0]["kind"] == "reasoning" and result["evidence"][0]["hash"] == evidence.body_hash(BODY)


def test_reissued_write_merges_a_later_span_onto_the_existing_claim(tmp_path):
    _episode(tmp_path)
    _episode(tmp_path, "ep_2026-09-02_001", "user: still alpha-project on sqlite-vec, confirmed.")
    agentic_write.write_claim(tmp_path, "alpha-project", "uses", "sqlite-vec", observer="agent",
                              evidence=[{"episode": "ep_2026-09-01_001", "quote": "alpha-project on sqlite-vec"}])
    agentic_write.write_claim(tmp_path, "alpha-project", "uses", "sqlite-vec", observer="agent",
                              evidence=[{"episode": "ep_2026-09-02_001", "quote": "alpha-project on sqlite-vec, confirmed"}])
    (c,) = parse_claims(markdown_parser.parse(tmp_path / "entities" / "alpha-project.md").body)
    assert [ev.episode for ev in c.evidence] == ["ep_2026-09-01_001", "ep_2026-09-02_001"]
    assert all(ev.is_span() for ev in c.evidence)


def test_mcp_tool_advertises_evidence_and_dispatches_it(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    _episode(tmp_path)
    server = _load_server()
    tool = {t["name"]: t for t in server.TOOLS}["cicada_write_claim"]
    ev_schema = tool["inputSchema"]["properties"]["evidence"]
    assert ev_schema["type"] == "array"
    assert set(ev_schema["items"]["required"]) == {"episode", "quote"}
    assert "verbatim" in ev_schema["items"]["properties"]["quote"]["description"].lower()
    assert "reasoning" in ev_schema["description"]
    out = server.handle_tool("cicada_write_claim", {
        "subject": "alpha-project", "predicate": "uses", "object": "sqlite-vec", "observer": "rodrigo",
        "source_episode": "ep_2026-09-01_001",
        "evidence": [{"episode": "ep_2026-09-01_001", "quote": "alpha-project on sqlite-vec"}],
    })
    assert "Recorded" in out and "evidence: 1 span verified" in out
    (c,) = parse_claims(markdown_parser.parse(tmp_path / "entities" / "alpha-project.md").body)
    assert c.evidence[0].is_span()


def test_mcp_reply_names_an_unverified_quote_so_the_agent_can_fix_it(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    _episode(tmp_path)
    server = _load_server()
    out = server.handle_tool("cicada_write_claim", {
        "subject": "alpha-project", "predicate": "uses", "object": "sqlite-vec",
        "evidence": [{"episode": "ep_2026-09-01_001", "quote": "not what was said"}],
    })
    assert "Recorded" in out
    assert "evidence: reasoning" in out and "ep_2026-09-01_001" in out
    out2 = server.handle_tool("cicada_write_claim", {"subject": "bob-example", "predicate": "prefers", "object": "tea"})
    assert "evidence: reasoning (no quote given)" in out2


def test_telegram_saved_because_claim_cites_its_own_section(tmp_path, monkeypatch):
    import asyncio

    from api.services import media_ingestor, telegram_capture
    from api.services.media_ingestor import MediaMeta

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    # Bait: the site's own description repeats the reason's words, and
    # `media_ingestor._episode_body` writes `## Description` BEFORE
    # `## Saved because` — so without the section window the first
    # occurrence would be the site's blurb, not what the person typed.
    async def offline(url, client, from_bookmark_file=False):
        return MediaMeta(title="A Recipe", description="Readers say it is great for meal prep.",
                         site="example.com", media_type="url")

    async def no_commit(memory_path, count, paths=None):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    result = asyncio.run(telegram_capture._default_save_url(
        memory, "https://example.com/recipe", note="great for meal prep", reason="great for meal prep"))
    assert result["status"] == "created"  # `_default_save_url` returns a plain dict (telegram_capture.py:454-459)
    page = memory / "entities" / f"{result['media_entity_id']}.md"
    (claim,) = [c for c in parse_claims(markdown_parser.parse(page).body) if c.predicate == "saved-because"]
    (ev,) = claim.evidence
    body = evidence.source_text(memory, result["episode_id"])
    assert ev.kind == "user" and ev.episode == result["episode_id"]
    assert body[ev.start:ev.end] == "great for meal prep"
    section = body.rfind("## Saved because")
    assert body.find("great for meal prep") < section < ev.start  # bait above was skipped; the span is inside the section
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_evidence_agent_writes.py -q -p no:cacheprovider`
Expected: FAIL — `TypeError: write_claim() got an unexpected keyword argument 'evidence'`, `KeyError: 'evidence'` on the tool schema.

- [ ] **Step 3: `agentic_write.write_claim`**

Import: change `agentic_write.py:38` to

```python
from api.services import decay_policy, entity_body, markdown_parser, telemetry
from api.services import evidence as evidence_mod
```

The alias is deliberate: `write_claim` gains a keyword argument named `evidence` (the MCP schema, the tests and the docs all use that name), and a bare `from api.services import evidence` would be shadowed inside the function body. `evidence` imports only `markdown_parser` and `claims` — both already imported here — so there is no cycle.

Signature (`:232-248`): add `evidence: list[dict] | None = None,` after `origin: str | None = None,`.

Docstring: append a paragraph after the ``origin`` one:

```
    ``evidence`` (G118 slice 1): ``[{"episode": <id>, "quote": <verbatim words>}]``
    — the passages that state this fact. Each quote is verified against the
    stored episode body by ``evidence.verify`` (exact → whitespace-normalised
    → case-insensitive, never fuzzy) and recorded as OFFSETS, never as the
    quote; one that cannot be located is recorded as ``reasoning`` and the
    claim is still written. Omitted, the claim carries a single ``reasoning``
    entry on ``source_episode`` (R6) — an agent's own inference, said so.
```

Claim build (`:336-352`): before `new_claim = Claim(` add

```python
        spans = evidence_mod.verify_many(memory_path, evidence)
        if not spans:
            # R6: no citation → one `reasoning` entry on the source episode.
            # `verify` with an empty quote never locates, but it still reads
            # the episode so the hash is kept when the document exists.
            spans = [
                evidence_mod.verify(memory_path, source_episode, "")
                if source_episode else evidence_mod.reasoning("")
            ]
```

and add `evidence=spans,` after `session_id=(session_id or "").strip() or None,`.

Result dict (`:405-411`): add `"evidence": [e.to_dict() for e in spans],`.

- [ ] **Step 4: MCP tool schema, dispatch, reply**

In `mcp/server.py` after the `"sources"` property (`:311-316`, inside `"properties"` of `cicada_write_claim`) add:

```python
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "episode": {
                                "type": "string",
                                "description": "The episode the words are in — the id cicada_save_episode returned, or one listed by cicada_pending.",
                            },
                            "quote": {
                                "type": "string",
                                "description": "The exact words, copied verbatim from that episode (at most 240 characters). Never a paraphrase.",
                            },
                        },
                        "required": ["episode", "quote"],
                    },
                    "description": "Optional. WHERE this fact comes from: the passage(s) in a saved episode that state it. Cicada verifies each quote against the stored episode and records only its offsets (G118 — spans, not copies). Omit it when the claim is your own inference: it is then recorded as reasoning, never as an invented span. If you saved the conversation with cicada_save_episode, cite that episode.",
                },
```

Dispatch (`:533-544`): append `arguments.get("evidence"),` as the last positional argument.

`handle_write_claim` (`:1086-1096`): add `evidence: list | None = None,` after `sources: list | None = None,`; pass `evidence=evidence,` into `agentic_write.write_claim(...)` after `sources=sources,`.

Reply (`:1157-1161`): build an evidence clause and append it:

```python
    spans = result.get("evidence") or []
    verified = [e for e in spans if e.get("kind") != "reasoning"]
    if verified:
        ev_note = f"evidence: {len(verified)} span verified" + ("s" if len(verified) > 1 else "")
        if len(verified) < len(spans):
            missed = ", ".join(e.get("episode") or "?" for e in spans if e.get("kind") == "reasoning")
            ev_note += f"; quote not found in {missed}, recorded as reasoning"
    elif evidence:
        missed = ", ".join(e.get("episode") or "?" for e in spans) or "the named episode"
        ev_note = f"evidence: reasoning (quote not found in {missed} — cite the exact words, or omit evidence)"
    else:
        ev_note = "evidence: reasoning (no quote given)"

    return (
        f"{verb}: {subject} {predicate} {object_} "
        f"(entity `{result.get('entity_id')}`, claim `{result.get('claim_id')}`, "
        f"observer={result.get('observer')}, action={action}; {ev_note})."
    )
```

Note the test asserts the singular form `evidence: 1 span verified` — keep the pluralisation exactly as above.

- [ ] **Step 5: Telegram `saved-because` cites its section (R13)**

In `api/services/telegram_capture.py` `_write_saved_because_claim` (`:296-327`), add the import and the section window before the `write_claim(...)` call, and pass the citation. `media_ingestor._episode_body` (`media_ingestor.py:1322-1355`) writes the title line, the `**Source/URL/Site/Saved**` lines, then `## Description` (the site's own blurb), then `## Saved because`, then `## User note`. The title or the blurb can repeat the reason's words ABOVE the section, so the window (the `verify_many` item hint from Task 1) pins the span inside the section rather than trusting first-occurrence order:

```python
    from api.services import evidence as evidence_mod
    from api.services.agentic_write import write_claim

    # G118 R13: the reason lives in the episode's `## Saved because` section
    # (baked in by media_ingestor._episode_body on a fresh save), so the claim
    # cites it as a `user` span, windowed to that section. On the repeat-save
    # path the section is appended AFTER this call and the quote resolves to
    # `reasoning` — honest, and cheaper than reordering the L3 logic.
    window = None
    text = evidence_mod.source_text(memory_path, episode_id) if episode_id else None
    if text is not None and "## Saved because" in text:
        window = [text.index("## Saved because"), len(text)]

    result = write_claim(
        memory_path,
        media_entity_id,
        "saved-because",
        reason,
        observer="rodrigo",
        object_kind="literal",
        confidence=0.9,
        source_episode=episode_id or None,
        origin="telegram",
        evidence=(
            [{"episode": episode_id, "quote": reason, "window": window}] if episode_id else None
        ),
    )
```

Keep the existing warning branch below the call unchanged.

- [ ] **Step 6: Run the new tests and every agentic/MCP/Telegram neighbour**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_evidence_agent_writes.py api/tests/test_evidence.py api/tests/test_agentic_write.py api/tests/test_agentic_subject_resolution.py api/tests/test_mcp_tool_descriptions.py api/tests/test_mcp_sources_tool.py api/tests/test_mcp_perspective.py api/tests/test_mcp_inbox_questions.py api/tests/test_session_identity.py api/tests/test_telegram_capture.py api/tests/test_fact_sources.py api/tests/test_inbox_resolve_claims.py -q -p no:cacheprovider`
Expected: all PASS. `test_agentic_write.py::test_cicada_write_claim_dispatches_via_handle_tool` asserts `"Recorded" in out` — still true with the appended clause.

- [ ] **Step 7: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && git add api/services/agentic_write.py api/services/telegram_capture.py mcp/server.py api/tests/test_evidence_agent_writes.py && git commit -m "feat(agentic-write): cicada_write_claim cites {episode, quote} → verified span; Telegram saved-because cites its section (G118 slice 1)"
```

---

### Task 5: Read path — `evidence` on the claim projections and `GET /episodes/{id}/span`

**Files:**
- Modify: `api/models/schemas.py:520-549` (`ClaimModel`), add `EvidenceModel` above it and `EpisodeSpan` after `ClaimTimeline` (`:556-567`)
- Modify: `api/routers/claims.py:38-59` (`_claim_to_model`), `api/services/transclusion_resolver.py:45-66` (`_to_model`)
- Create: `api/routers/episodes.py`; Modify: `api/main.py:13-36` (the `from api.routers import (...)` list), `:161` (mount after `claims`). `api/routers/__init__.py` is a zero-byte package marker — leave it alone.
- Test: `api/tests/test_episode_span_endpoint.py` (new); extend `api/tests/test_claim_endpoints.py`

**Interfaces:**
- `EvidenceModel(CamelModel)`: `episode: str`, `start: int`, `end: int`, `kind: str`, `hash: str`.
- `ClaimModel.evidence: list[EvidenceModel] = []` (camelCase wire, additive).
- `GET /episodes/{episode_id}/span?start=&end=&context=240&hash=` → `EpisodeSpan(CamelModel)`: `episode: str`, `text: str`, `before: str`, `after: str`, `start: int`, `end: int`, `length: int`, `stale: bool`, `kind: str`. 404 unknown document; 422 bad range (`start < 0`, `end <= start`, `end > length`, `context` outside `0..2000`).

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_claim_endpoints.py`:

```python
# --------------------------------------------------------------------------- #
# G118 slice 1 — `evidence` rides the claim projections, camelCase, additive
# --------------------------------------------------------------------------- #


def test_claims_endpoint_projects_evidence_camelcase(tmp_path):
    from api.routers import claims as claims_router
    from api.services.claims import Evidence

    _write_page(tmp_path, "alpha-project", "Alpha Project", [
        Claim(id="clm_e", text="alpha-project uses sqlite-vec", subject="alpha-project", predicate="uses",
              object="sqlite-vec", context="engineering",
              evidence=[Evidence(episode="ep_2026-09-01_001", start=6, end=40, kind="user", hash="0123456789ab")]),
        Claim(id="clm_legacy", text="alpha-project uses git", subject="alpha-project", predicate="uses",
              object="git", context="engineering"),
    ])
    resp = run(claims_router.get_entity_claims("alpha-project", settings=_FakeSettings(tmp_path)))
    by_id = {c.id: c for c in resp.claims}
    assert by_id["clm_legacy"].evidence == []
    (ev,) = by_id["clm_e"].evidence
    assert (ev.episode, ev.start, ev.end, ev.kind, ev.hash) == ("ep_2026-09-01_001", 6, 40, "user", "0123456789ab")
    wire = {c["id"]: c for c in resp.model_dump(by_alias=True)["claims"]}
    assert wire["clm_legacy"]["evidence"] == []
    assert set(wire["clm_e"]["evidence"][0]) == {"episode", "start", "end", "kind", "hash"}
    assert "sourceEpisodes" in wire["clm_e"]  # the rest of the shape is untouched (camelCase)
    tl = run(claims_router.get_entity_timeline("alpha-project", predicate="uses", context="engineering",
                                               settings=_FakeSettings(tmp_path)))
    assert {c.id: len(c.evidence) for c in tl.claims} == {"clm_e": 1, "clm_legacy": 0}
```

```python
# api/tests/test_episode_span_endpoint.py
"""G118 slice 1 — `GET /episodes/{id}/span`: slice a stored body back out.

Engine-free, a few ms, and honest about staleness: the caller's `hash` is
compared with the current body and `stale` says whether the offsets still
mean what they meant when the claim was written. Fixtures are synthetic.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import evidence, markdown_parser
from api.services.claims import Claim, write_claims

BODY = (
    "user: I moved alpha-project onto sqlite-vec last week.\n"
    "assistant: Noted — sqlite-vec replaces LEANN for alpha-project.\n"
    "user: bob-example reviewed it."
)


@pytest.fixture
def memory(tmp_path: Path, monkeypatch) -> Path:
    """The `home` fixture pattern from test_healthz_memory_root.py / test_auth.py:
    a tmp CICADA_HOME + memory root, settings cache cleared on both sides."""
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md", {"id": "ep_2026-09-01_001"}, BODY)
    # `decay_class: evergreen` up front: app startup runs `run_bank_migrations`
    # on this bank, and the decay-class backfill would otherwise rewrite this
    # media page's FRONTMATTER (body untouched — R1 — so the hash would still
    # match; declaring it just keeps the fixture byte-stable across the test).
    markdown_parser.write(memory / "entities" / "media-ros-guide.md",
                          {"name": "ROS guide", "type": "media", "decay_class": "evergreen"},
                          write_claims("## Summary\nSaved.\n\n## Description\nA guide to ROS.", [Claim(id="c", text="t")]))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


def test_span_returns_text_and_context_for_an_episode(memory):
    start, end = BODY.find("sqlite-vec replaces"), BODY.find("LEANN") + 5
    with TestClient(main.app) as client:
        r = client.get("/episodes/ep_2026-09-01_001/span", params={"start": start, "end": end, "context": 12,
                                                                    "hash": evidence.body_hash(BODY)})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["episode"] == "ep_2026-09-01_001"
    assert data["text"] == "sqlite-vec replaces LEANN"
    assert data["before"] == BODY[start - 12:start] and data["after"] == BODY[end:end + 12]
    assert data["stale"] is False and data["kind"] == "assistant"
    assert data["start"] == start and data["end"] == end and data["length"] == len(BODY)


def test_span_defaults_context_to_240_and_clips_at_the_edges(memory):
    with TestClient(main.app) as client:
        r = client.get("/episodes/ep_2026-09-01_001/span", params={"start": 6, "end": 11})
    assert r.status_code == 200
    data = r.json()
    assert data["text"] == "I mov" and data["before"] == "user: " and data["after"] == BODY[11:251]
    assert data["stale"] is False  # no hash given -> nothing to be stale against


def test_span_marks_stale_on_hash_mismatch_but_still_slices(memory):
    with TestClient(main.app) as client:
        r = client.get("/episodes/ep_2026-09-01_001/span", params={"start": 6, "end": 11, "hash": "deadbeefcafe"})
    assert r.status_code == 200 and r.json()["stale"] is True and r.json()["text"] == "I mov"


def test_span_resolves_a_media_page_with_the_claims_block_excluded(memory):
    text = evidence.source_text(memory, "media-ros-guide")
    s = text.find("ROS")
    with TestClient(main.app) as client:
        r = client.get("/episodes/media-ros-guide/span",
                       params={"start": s, "end": s + 3, "hash": evidence.body_hash(text)})
    assert r.status_code == 200
    assert r.json()["text"] == "ROS" and r.json()["kind"] == "page" and r.json()["stale"] is False
    assert r.json()["length"] == len(text)  # the fence is not part of the addressable text


def test_span_404_on_unknown_or_traversing_ids(memory):
    with TestClient(main.app) as client:
        assert client.get("/episodes/ep_2026-01-01_999/span", params={"start": 0, "end": 1}).status_code == 404
        r = client.get("/episodes/..%2Fepisodes%2Fep_2026-09-01_001/span", params={"start": 0, "end": 1})
    assert r.status_code in (404, 422)


def test_span_422_on_bad_ranges(memory):
    with TestClient(main.app) as client:
        for params in ({"start": -1, "end": 5}, {"start": 5, "end": 5}, {"start": 5, "end": 4},
                       {"start": 0, "end": len(BODY) + 1}, {"start": 0, "end": 5, "context": 5000},
                       {"start": 0, "end": 5, "context": -1}, {"end": 5}):
            assert client.get("/episodes/ep_2026-09-01_001/span", params=params).status_code == 422, params


def test_span_endpoint_is_bearer_gated_like_every_other_route(memory, monkeypatch):
    # conftest turns auth off for the suite; flip it on the way test_auth.py does.
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_API_TOKEN", "secret-token")
    with TestClient(main.app) as client:
        denied = client.get("/episodes/ep_2026-09-01_001/span", params={"start": 0, "end": 1})
        ok = client.get("/episodes/ep_2026-09-01_001/span", params={"start": 0, "end": 1},
                        headers={"Authorization": "Bearer secret-token"})
    assert denied.status_code == 401
    assert ok.status_code == 200
```

`api/tests/test_auth.py:49` is the reference for the auth toggle (`CICADA_API_AUTH=on` + `CICADA_API_TOKEN`, read per request by `auth.get_token`, `api/services/auth.py:94-99`; a missing header is `401`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_episode_span_endpoint.py api/tests/test_claim_endpoints.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: 'ClaimModel' object has no attribute 'evidence'`; every span request returns 404 (no route).

- [ ] **Step 3: Schemas**

In `api/models/schemas.py`, immediately above `class ClaimModel` (`:520`):

```python
class EvidenceModel(CamelModel):
    """One evidence span on a claim (G118 slice 1) — offsets into a stored
    document, never a copy. ``episode`` is a source-document id: ``ep_*`` is an
    episode, anything else an entity page (a ``page`` span cites the media
    entity). ``kind`` is ``user`` | ``assistant`` | ``page`` | ``reasoning``;
    a ``reasoning`` entry has ``start == end == -1``. Resolve a span with
    ``GET /episodes/{episode}/span?start=&end=&hash=``.
    """

    episode: str = ""
    start: int = -1
    end: int = -1
    kind: str = "reasoning"
    hash: str = ""
```

In `ClaimModel`, after `origin: Optional[str] = None` add:

```python
    # G118 slice 1 — additive; an older app build ignores the key (R10).
    evidence: list[EvidenceModel] = []
```

After `class ClaimTimeline` (`:556-567`) add:

```python
class EpisodeSpan(CamelModel):
    """``GET /episodes/{id}/span`` — a slice of a stored document's evidence
    text with context on either side (G118 slice 1). ``stale`` is true when
    the caller's ``hash`` no longer matches the document, i.e. the offsets
    were minted against an earlier body and may not mean the same words.
    ``kind`` is derived at read time (speaker marker for an episode, ``page``
    for an entity document), never stored here.
    """

    episode: str
    text: str
    before: str
    after: str
    start: int
    end: int
    length: int
    stale: bool = False
    kind: str = "user"
```

- [ ] **Step 4: Project `evidence` in both claim projections**

`api/routers/claims.py`: import `EvidenceModel` beside `ClaimModel` (`:25-30`) and add to `_claim_to_model` (`:38-59`) after `origin=c.origin,`:

```python
        evidence=[EvidenceModel(**e.to_dict()) for e in (c.evidence or [])],
```

`api/services/transclusion_resolver.py`: same — import `EvidenceModel` (`:35`) and add the identical line to `_to_model` (`:45-66`).

- [ ] **Step 5: The `episodes` router**

Create `api/routers/episodes.py`:

```python
"""``GET /episodes/{id}/span`` — slice a stored document back out (G118 s1).

The read half of evidence spans: a claim points at ``(episode, start, end,
hash)``; this endpoint returns those characters with context so a viewer
(slice 2) can highlight them inside the raw source. Engine-free by
construction — one ``markdown_parser.parse`` and string slicing (G80) —
and honest about drift: ``stale`` is set when the caller's ``hash`` no
longer matches the current evidence text (R2), and the slice is still
returned so the viewer can show *something* while saying it may have moved.

``{id}`` is a source-document id (R3): ``ep_*`` resolves under ``episodes/``,
anything else under ``entities/`` — the same resolver the writers use, so a
``page`` span on a media entity opens exactly what recon cited. Bearer-gated
like every route; no ETag (R9) — the response validates itself.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.config import Settings, get_settings
from api.models.schemas import EpisodeSpan
from api.services import evidence

router = APIRouter()

# A viewer never needs more than a screen of context; 2,000 chars on each
# side keeps the response bounded regardless of the episode's size.
MAX_CONTEXT = 2000
DEFAULT_CONTEXT = 240


@router.get("/episodes/{episode_id}/span", response_model=EpisodeSpan)
async def get_episode_span(
    episode_id: str,
    start: int = Query(..., ge=0),
    end: int = Query(..., ge=1),
    context: int = Query(DEFAULT_CONTEXT, ge=0, le=MAX_CONTEXT),
    hash: str | None = Query(None, max_length=64),  # noqa: A002 - the field's own name
    settings: Settings = Depends(get_settings),
):
    """The evidence text at ``[start, end)`` with ``context`` chars either side."""
    text = evidence.source_text(settings.memory_path, episode_id)
    if text is None:
        raise HTTPException(404, f"No stored document {episode_id!r}")
    if end <= start or end > len(text):
        raise HTTPException(422, f"span [{start}, {end}) is outside the document (length {len(text)})")
    current = evidence.body_hash(text)
    return EpisodeSpan(
        episode=episode_id,
        text=text[start:end],
        before=text[max(0, start - context):start],
        after=text[end:end + context],
        start=start,
        end=end,
        length=len(text),
        stale=bool(hash) and hash != current,
        kind=evidence.speaker_kind(text, start) if evidence.is_episode_id(episode_id) else "page",
    )
```

Register it: add `episodes,` (alphabetical, between `entities,` and `graph,`) to the `from api.routers import (...)` list in `api/main.py:13-36` — that list is the only registry; `api/routers/__init__.py` is empty and stays empty — then mount after the claims router (`api/main.py:161`):

```python
app.include_router(episodes.router, tags=["episodes"])
```

- [ ] **Step 6: Run the new tests, the endpoint neighbours, and the auth suite**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_episode_span_endpoint.py api/tests/test_claim_endpoints.py api/tests/test_auth.py api/tests/test_healthz_memory_root.py api/tests/test_graph_claim_overlay.py api/tests/test_ask_claim_retrieval.py api/tests/test_sync.py -q -p no:cacheprovider`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && git add api/models/schemas.py api/routers/claims.py api/services/transclusion_resolver.py api/routers/episodes.py api/main.py api/tests/test_episode_span_endpoint.py api/tests/test_claim_endpoints.py && git commit -m "feat(api): evidence on the claim projections + GET /episodes/{id}/span, engine-free with a stale flag (G118 slice 1)"
```

---

### Task 6: Docs — CLAUDE.md, the G118/G100 rows, TODO handoff

**Files:**
- Modify: `CLAUDE.md:347-365` (insert a new `### Evidence spans (G118 slice 1)` subsection between `### Fact sources (G61)` and `### Save-with-reason (G71)` at `:366`), `:671-673` (API list)
- Modify: `docs/goals/memory-evolution.md:680` (G118 row status), `:662` (G100 row status) — targeted `python - <<'PY'` string replaces, never hand-retyped
- Modify: `docs/goals/TODO.md:7` (header date), `:131-190` (Pick up here), `:191` (last-synced line), `:195-215` (Shipped ▸ Provenance), `:337-340` (Wave C 9b), `:351-352` (item 11, G100)

**Interfaces:** none — prose only. Everything stated must be true of the branch as committed by Tasks 1–5; if a name changed, follow the code.

**Privacy rule (CLAUDE.md, standing):** nothing personal in any of these files — examples use `alpha-project`, `bob-example`, `example.com`; no episode titles, no quoted bank text.

- [ ] **Step 1: CLAUDE.md**

1. Insert before `### Save-with-reason (G71)` (`:366`):

```markdown
### Evidence spans (G118 slice 1)
Every claim written since this slice carries `evidence: [{episode, start, end, kind, hash}]` —
**spans, not copies**. `episode` is a source-document id (`ep_*` → `episodes/<id>.md`; anything
else → `entities/<id>.md`, so a `kind: page` span cites the media entity whose stored description
it points into); `start`/`end` are character offsets into that document's *evidence text* — the
body exactly as `markdown_parser.parse` returns it, with the ```claims fence stripped for an entity
page, so writing a claim never stales its own span; `hash` is `sha256[:12]` of that text, and a
mismatch reads as `stale` rather than mis-highlighting. `kind` is `user` | `assistant` (by the
last `<role>:` turn marker at or before the span — no marker means `user`, since every marker-less
writer captures the person's own input) | `page` | `reasoning` (the contributor's own inference:
`start == end == -1`, never a faked span). One module, `api/services/evidence.py`, does the work
for every writer — locate is exact → whitespace-normalised → case-insensitive and **never fuzzy**;
an unlocatable quote becomes `reasoning` and **the claim is still written** (provenance never blocks
memory). Writers: Stage-1 extraction asks for a verbatim `evidence_quote` per relationship and
`extract` verifies it against the body it chunked (chunk window preferred, offsets into the whole
body, quote consumed — nothing downstream sees it); `cicada_write_claim` / `agentic_write.write_claim`
take `evidence: [{episode, quote}]` and record `reasoning` on the source episode when omitted; link
recon cites the surface form it grounded on as a `page` span; the Telegram `saved-because` claim
cites its `## Saved because` section. `claim_reconciler._reinforce` merges a later conversation's
spans onto the existing claim. **Legacy claims carry no `evidence` and `to_dict` omits the empty
key** — an empty list means "written before evidence existed", a `reasoning` entry means "no source
text"; no backfill (G100's derived-span class, if it ever ships, is a distinct kind). Read path:
`evidence` rides `GET /entities/{id}/claims`, `/timeline` and `/transclude` (camelCase, additive —
the app's `Claim` decoder ignores unknown keys), and `GET /episodes/{id}/span?start=&end=&context=&hash=`
slices the evidence text back out, engine-free, with `stale` and the derived `kind`. No ETag on
either (the span response validates itself; no new `sync_service` component). Out of scope until
the later slices: the highlight viewer, trigger traces, rationale, backfill.
```

2. In the API list (`:671-673`), change the two claim lines to say `(+ evidence spans, G118)` and add after `/transclude`:

```
GET  /episodes/{id}/span                  → slice a stored document's evidence text at [start,end) with
                                            context (default 240, max 2000); `hash=` → `stale`; `kind`
                                            derived; 404 unknown doc, 422 bad range (G118 slice 1)
```

- [ ] **Step 2: Backlog rows** — run from the worktree root:

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python - <<'PY'
from pathlib import Path
p = Path("docs/goals/memory-evolution.md")
s = p.read_text()

old_118 = "APPLY, L (four slices, each shippable) | 🔲 |"
assert s.count(old_118) == 1, "G118 row tail not found exactly once"
new_118 = ("APPLY, L (four slices, each shippable). **Slice 1 shipped 2026-09-03 (PR #TBD, `feat/provenance-spans`):** "
           "`Claim.evidence: [{episode, start, end, kind, hash}]` (offsets into the parsed body, ```claims fence excluded for a page; "
           "`sha256[:12]` → `stale` on mismatch; kinds `user|assistant|page|reasoning`, speaker by the last `<role>:` marker, no marker = user); "
           "one engine-free module `api/services/evidence.py` (exact → whitespace → case-insensitive, never fuzzy; unlocatable = `reasoning`, claim still written); "
           "Stage-1 `evidence_quote` verified in `extract` against the chunked body with the chunk as window; `cicada_write_claim`/`write_claim` take "
           "`evidence: [{episode, quote}]`; link recon `page` spans on the media entity; Telegram `saved-because` cites its section; `_reinforce` merges spans; "
           "`evidence` on `/claims`, `/timeline`, `/transclude`; `GET /episodes/{id}/span`. Legacy claims: no evidence, no backfill, `to_dict` omits the empty key. "
           "**Open:** slice 2 viewer (entity → claim → chip → raw pane, Swift `Evidence` model), slice 3 trigger traces, slice 4 rationale, G100's derived-span class, "
           "`describes` claims on link enrichment (a whole-section span — trivial once the viewer wants it). | 🛠️ slice 1 ✅ (PR #TBD); slices 2–4 open |")
s = s.replace(old_118, new_118)

old_100 = "strengthens the thesis's provenance claim. | 🔲 |"
assert s.count(old_100) == 1, "G100 row tail not found exactly once"
new_100 = ("strengthens the thesis's provenance claim. **Absorbed into G118 (2026-09-03):** design point (i) — the contributor cites at write time — "
           "shipped as G118 slice 1 (`evidence: [{episode, quote}]` on `cicada_write_claim`, `evidence_quote` in Stage 1); (ii) is settled the other way "
           "(offsets + hash only, never the quote — the bank holds the text, `stale` replaces the repair path); the immutability dependency is verified for the body "
           "(`markdown_parser.parse` strips it identically on every rewrite; `mark_processed` never reflows it). (iii) derived spans and (iv) the viewer stay open under G118 slices 2+. "
           "| ⤴ absorbed into G118 — (i)/(ii) shipped in slice 1 (PR #TBD); (iii)/(iv) open |")
s = s.replace(old_100, new_100)
p.write_text(s)
print("ok")
PY
```

- [ ] **Step 3: TODO.md**

1. `## Where things stand (2026-09-02)` → `(2026-09-03)`; add a paragraph after the opening one: "**G118 slice 1 — evidence spans — is on `feat/provenance-spans` (worktree `.worktrees/g118`), awaiting a PR against `dev`:** every new claim carries `evidence` spans (offsets + hash into the stored body, never copies), `cicada_write_claim` cites `{episode, quote}`, and `GET /episodes/{id}/span` slices the source back out. No Swift change; legacy claims show no evidence, honestly."
2. Under `## ✅ Shipped` ▸ **Provenance**, append: "· **G118 slice 1 evidence spans (2026-09-03, PR #TBD)** — `Claim.evidence` offsets + hash, Stage-1 quote verification, agent/Telegram/link-recon writers, `/episodes/{id}/span`; absorbs G100 (i)/(ii)".
3. Wave C item `9b`: replace "Slice 1 = span capture in Stage-1 + resolver; absorbs G100 — L" with "Slice 1 shipped (spans + agent citations + span endpoint, PR #TBD); next: slice 2 viewer (Swift `Evidence` model, chips → raw pane with highlight), then triggers (needs G105), then rationale — L".
4. Item `11. **G100** …`: replace with "11. ~~G100~~ — absorbed into G118 (slice 1 shipped the write-time citation; the derived-span class and the viewer are G118 slice 2)".
5. `## Pick up here`: change the first line to name `feat/provenance-spans` as the branch awaiting a PR (keep the `feat/link-summaries` note if it is still unmerged), and in `0b.` mark G118 slice 1 as done so the order reads "**G118 slice 2 (viewer) → G105 → G93 → …**". Add `.worktrees/g118` to the **Worktrees** paragraph.
6. `_Last synced:` line: prepend "2026-09-03 (G118 slice 1 on `feat/provenance-spans`, PR pending); " to the existing text.

- [ ] **Step 4: Verify the docs say nothing personal and nothing stale**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && grep -n "evidence_quote\|/episodes/{id}/span\|Evidence spans (G118" CLAUDE.md | head; grep -c "PR #TBD" docs/goals/memory-evolution.md docs/goals/TODO.md; grep -n "G118 slice 1 → G105" docs/goals/TODO.md`
Expected: the three CLAUDE.md hits; `PR #TBD` counted ≥ 1 in each goals file (the merge step fixes the number); no hit for the old `G118 slice 1 → G105` ordering.

- [ ] **Step 5: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && git add CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md docs/superpowers/plans/2026-09-03-g118-evidence-spans.md && git commit -m "docs(G118): evidence spans slice 1 — CLAUDE.md section, G118/G100 rows, TODO handoff"
```

---

## Not in scope (do not build here)

- The highlight viewer / raw-source pane, the Swift `Evidence` model and evidence chips (G118 slice 2).
- Trigger traces (`trigger: {kind, span?, tool?, cycle?}`) — slice 3, needs G105.
- Rationale text on claims/nudges — slice 4.
- Backfilling `evidence` onto existing claims, and G100's derived (fuzzy, name/alias-matched) span class — a distinct kind, not a flag; not started.
- `describes` claims from `link_enrichment` citing the whole `## Description` section — trivial but unrequested; noted in the G118 row.
- Re-locating a stale span by searching for the original words (the words are not stored — R2 makes `stale` the honest answer).
- Any change to inbox cards, `cicada_ask` citations, `GET /entities/{id}` body, ETags, or `sync_service.components`.
- Any Swift edit (R10 verified the decoders are tolerant).

## Verification the orchestrator runs at the end

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && git log --oneline dev..HEAD
# expected: six commits, one per task, in order

cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && git status --porcelain -uall
# expected: empty apart from the untracked api/.venv symlink and any pre-existing untracked scratch — no memory/, logs/, *-report.md staged

cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests/test_claims_evidence.py api/tests/test_evidence.py api/tests/test_evidence_extraction.py api/tests/test_evidence_agent_writes.py api/tests/test_episode_span_endpoint.py api/tests/test_link_recon.py api/tests/test_claim_endpoints.py -q -p no:cacheprovider
# expected: all pass

cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -15
# expected: only the baseline — 8 failures in test_calendar_registry.py and
# test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit

# Rails, mechanically:
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && grep -n "litellm\|providers\|agent_engine" api/services/evidence.py api/routers/episodes.py
# expected: no output (engine-free)
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && grep -rn "\.claude" api/services/evidence.py api/routers/episodes.py
# expected: no output (G48 rail)
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && grep -n "quote" api/services/claims.py
# expected: no field named quote on Claim or Evidence (spans, not copies)
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && git diff dev..HEAD --stat -- app/
# expected: no output (no Swift edit, R10)
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g118 && git diff dev..HEAD -- api/tests docs CLAUDE.md | grep -n "rodrigo" | grep -vi "rorosaga\|observer\|Rodrigo 2026\|rodrigo/" 
# expected: only the pre-existing observer literal `rodrigo` (the claim vocabulary), never a person, employer or bank title
```

## Self-review notes (for the executor, not a task)

- `evidence.py` must import `Evidence` from `claims.py`, never the reverse — `claims.py` is imported by everything and must stay leaf-like.
- In `agentic_write.write_claim` the `evidence` keyword would shadow a bare module import; the module-level `from api.services import evidence as evidence_mod` is what keeps the body correct. Do not rename the keyword — the MCP schema, the tests and the docs all say `evidence` — and do not import the module unaliased anywhere in that file.
- `speaker_kind` scans through the end of the line containing `start`, not `text[:start]`; the test `speaker_kind(EPISODE, EPISODE.find("assistant:")) == "assistant"` is the one that breaks if that is "simplified".
- `Query(..., ge=1)` on `end` plus the explicit `end <= start` check together give the 422s the test enumerates; the `{"end": 5}` case (missing `start`) is FastAPI's own 422.
- `to_dict` omitting an empty `evidence` (R7) is what keeps `test_claims.py`'s round-trip and the decay-watermark migration's raw-entry path byte-identical for legacy pages; do not "simplify" it back to plain `asdict`.
- The Telegram test relies on `## User note` and `## Saved because` carrying the same text; the `window` hint is what makes the span land in the section. If `media_ingestor._episode_body` ever reorders sections, the assertion `body.rfind("## Saved because") < ev.start` is the one that fails first.
- No task touches `memory/`; every test builds its own bank under `tmp_path`.
