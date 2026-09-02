# Save-with-reason + the Imports page (G71) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every saved link carry *why* it was saved, add the two sanctioned direct connectors (Pinterest, Reddit) plus three new export parsers (LinkedIn, TikTok, Reddit-GDPR), and grow the `+` sheet into an Imports catalog whose export overlay shows a live, staging-free parse preview before the user commits to an import.

**Architecture:** Backend first, in dependency order. Tasks 1–5 are pure/near-pure additions to existing modules (`telegram_capture`, `agentic_write`, `media_ingestor`) plus one new endpoint mode (`?preview=true`). Tasks 6–8 add a new `api/services/connectors/` package (two adapters over one injectable-transport base), a new `api/routers/connectors.py`, and the Sleep-tail poll — every one of them credential-gated, network-gated, and non-fatal. Tasks 9–11 are app-side: the one-level `AddSourceTile` grid becomes a route-badged catalog, `WalkthroughPanel` grows a breadcrumb step-path and a live preview stage, and a new connector-setup panel handles guided credential entry. Task 12 is docs. Nothing new is invented for consolidation — every connector and parser emits `RawItem`s into the existing `media_ingestor.ingest_batch` path, and Sleep absorbs them unchanged (G69 §"Graph derivation").

**Tech Stack:** Python 3.11 / FastAPI / pydantic v2 (`CamelModel`), pytest (`api/.venv/bin/python -m pytest api/tests -q`); SwiftUI on macOS 14, SwiftPM package at `app/CicadaApp` (`swift-tools-version: 5.10`), XCTest (`cd app/CicadaApp && swift test`).

**Spec:** `docs/superpowers/specs/2026-08-31-saves-and-imports-design.md`
**Binding route matrix:** `docs/goals/saved-content-integrations.md` (G69 research — aggregators ruled out; Pinterest/Reddit = direct API; IG/YT/TikTok/LinkedIn = export files; YT Watch Later = out of slice).

**Branch:** fork from `dev` at `09b52f2`.

---

## Spec Ambiguities Resolved

The spec is the authority; these twelve points had more than one reading and the plan commits to one. Each is restated at the task that implements it.

1. **Where connector credentials live, and which HTTP surface exposes them.** The spec says "both follow the G50 BYOK pattern — credentials in `~/.cicada/secrets.env` (0600)". That names the *storage*, not the registry. `api/services/connections/registry.py` is LLM-engine-specific (`engine_role`, `billing`, `plan_label`, `ENGINE_POWERS`; `api/routers/status.py` picks the *first connected `engine_role`* as the engine) — registering Pinterest there would corrupt engine selection. Resolution: reuse `api/services/connections/secrets.py` for storage only, and expose a **new** `api/routers/connectors.py` at prefix `/sources/connectors`. (Tasks 6–8.)
2. **The `saved-because` claim's `origin`.** `agentic_write.write_claim` hard-codes `origin` (`"manual_edit"` when `observer == "rodrigo"`, else `"mcp"`) and derives `source_trust` from `observer`. The spec wants `user_stated` *and* `origin: telegram`. Resolution: `write_claim` gains an optional keyword `origin: str | None = None` (omitted ⇒ byte-identical to today), called with `observer="rodrigo", origin="telegram"`. Note the consequence and keep it: `"telegram"` is **not** in `claim_reconciler._HUMAN_ORIGINS`, so the claim is `user_stated` but **not** overwrite-protected — correct, because a bot webhook is not an authenticated manual-assertion channel. (Task 1.)
3. **`saved-because` object kind.** A reason is free text, so the claim is written with `object_kind="literal"`. `regenerate_edges_from_claims` projects only `object_kind == "node"` claims, so the reason never becomes a graph edge — it stays prose Stage 1 can extract concepts from. (Task 1.)
4. **"Saved because: …" on the episode body.** The existing `_episode_body` mixes bold field lines (`**Folder:**`) with `##` sections (`## Description`, `## User note`). The reason is prose meant for Stage-1 extraction, so it is written as a `## Saved because` section, not a field line. (Task 1.)
5. **"Bot ACK gains the reason echo."** There is no outgoing Telegram messaging anywhere in the repo (`grep sendMessage` → only a docstring). Adding an HTTP client + token handling for one ACK is unjustified. Resolution: use Telegram's **webhook-response method** form — `POST /capture/telegram` answers with `{"method": "sendMessage", "chat_id": …, "text": …}`, which Telegram executes. Zero new network code, fully testable. ACK strings: created-with-reason → `Saved with note: <reason>`; created without → `Saved.`; duplicate → `Already saved.`; text-only note → `Noted.`; skipped → no ACK. (Task 1.)
6. **The preview response shape.** Exactly the five keys the spec names — `{recognized, platform, total, collections, warnings}`. `collections` is derived by grouping `RawItem.folder`; `kind` comes from a per-platform constant. No `sourceLabel`: `platform` is a stable lowercase id and the app owns every display name in `Copy`. (Task 2.)
7. **`recognized` when a known format yields nothing.** A `.zip` that is not a Google Takeout parses to zero items today. Reporting `recognized: true, total: 0` would be a lie to the user. Resolution: `recognized = total > 0`, plus an honest warning naming what to drop instead. (Task 2.)
8. **"Confirm import … reusing the parse."** There is no server-side upload session, and a preview that "stages NOTHING" must not stage bytes either — a cache would need a token, a memory budget and an eviction policy. Resolution: Confirm re-posts the same file to the same endpoint with `preview=false`. Parsing is pure CPU over already-read bytes and runs in the threadpool; nothing is cached server-side. (Tasks 2, 10.)
9. **TikTok browsing-history opt-in.** `parse_upload` has no options parameter. Resolution: `parse_tiktok_export(data, *, include_history: bool = False)`, threaded through a new keyword-only `parse_upload(..., include_history: bool = False)` and the query param `?include_history=true` (query params in this API use the raw Python name — cf. `?include_diff=true`). Default off everywhere. (Task 4.)
10. **TikTok / Reddit origin strings.** The spec says `origin: tiktok`; the G69 backlog row says `tiktok-export`. Neither distinguishes intentional saves from ambient exhaust, which G69 §"Graph derivation" (b) says must stay distinguishable. Resolution: `tiktok-saved` for Favourites/Likes and `tiktok-history` for Browsing History; `reddit-saved` for both the API pull and the GDPR export; `pinterest` for the API pull; `linkedin-saved` for the LinkedIn export. `/origins` derives its rows from these strings with no registry to update.
11. **Reddit export hydration.** G69 says export rows (id + permalink) "must be hydrated via the Reddit API (`/api/info`)". They do not need a Reddit-specific call: `ingest_one` already runs every URL through `_enrich_opengraph`, and reddit.com serves OpenGraph tags. Resolution: no hydration code; an offline install degrades to the permalink-slug title exactly like every other save.
12. **Multi-platform export zips.** The `.zip` branch stays the Google Takeout walk. IG/TikTok/LinkedIn/Reddit archives must be unzipped and the individual file dropped — the step-path copy says so, and a non-Takeout zip returns `recognized: false` with a warning that says exactly that. Generalising the zip walk is explicitly out of this slice.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Never touch `.claude/settings.json`.** It is already modified in the working tree and is not part of this work.
- **Never run `git add -A`.** Stage only the exact files each commit step names.
- **Nothing under `memory/` may be created, modified, or staged by any task.** Every test builds its own `tmp_path` workspace.
- **Credentials live only in `~/.cicada/secrets.env` (0600)**, written through `api/services/connections/secrets.py`. Never in a bank, never in `api/.env`, never in git, **never logged** — no log line, error string, HTTP response, or exception message may contain a credential value. `GET /sources/connectors` returns `present: true/false` per field and never a value.
- **Zero network in tests.** Every connector HTTP call goes through an injected `http_fn`; every enrichment call is monkeypatched to the offline fallback. Production network is additionally gated by `CICADA_ALLOW_CONNECTOR_FETCH=1` (mirroring `CICADA_ALLOW_FEED_FETCH` / `CICADA_ALLOW_LOGO_FETCH`), with an autouse conftest fixture that deletes the variable for the whole suite.
- **Synthetic fixtures only.** No real personal export, no real saved URL, no real board/subreddit/collection name, no real credential may appear in any test file or fixture — the same rule `CLAUDE.md` states for `benchmarks/`. Use `example.com`, `Recipes`, `r/example`, `client-id-placeholder`.
- **Offline-safe by construction.** A connector sync never raises past `sync()`; a failed poll is recorded and surfaced, never fatal to a Sleep cycle.
- **Every commit message ends with these two trailer lines**, after a blank line:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
  ```
- **Verification commands:** backend `api/.venv/bin/python -m pytest api/tests -q`; app `cd app/CicadaApp && swift test`.

---

## File Structure

**New backend files**

| Path | Responsibility |
|---|---|
| `api/services/connectors/__init__.py` | Package docstring stating the house rules both adapters obey. |
| `api/services/connectors/base.py` | Injectable-transport seam + the network gate, shared by both adapters. |
| `api/services/connectors/pinterest.py` | Pinterest v5: authorize URL, code→token exchange, boards+pins pull, `sync()`. |
| `api/services/connectors/reddit.py` | Reddit script-app: token, `/user/{me}/saved` pagination to a seen id, `sync()`. |
| `api/routers/connectors.py` | `/sources/connectors` — status, credentials, authorize, OAuth callback, sync-now. |

**Modified backend files**

| Path | Change |
|---|---|
| `api/services/agentic_write.py` | `write_claim(..., origin=None)`. |
| `api/services/telegram_capture.py` | Reason extraction, ACK, `saved-because` claim. |
| `api/services/media_ingestor.py` | `RawItem.reason`; `preview_upload`; three new parsers; `parse_upload` sniffs + `include_history` + `warnings`. |
| `api/services/sync_state.py` | `record_sync(..., extra=)`, `record_error`. |
| `api/services/channel_registry.py` | `pinterest` / `reddit` rows, `last_error` surfacing. |
| `api/services/sleep_cycle.py` | `_poll_connectors_safely` tail step. |
| `api/routers/sources.py` | `?preview=true`, `?include_history=true`, connector connectedness in the channels ETag. |
| `api/routers/capture.py` | Webhook-response ACK. |
| `api/models/schemas.py` | `SourceUploadCollection`, `SourceUploadPreview`, `SourceChannel.last_error`, connector models. |
| `api/services/auth.py` | `/sources/connectors/pinterest/callback` open path. |
| `api/main.py` | Mount the connectors router. |
| `api/tests/conftest.py` | Autouse `CICADA_ALLOW_CONNECTOR_FETCH` scrub. |

**New backend tests:** `test_upload_preview.py`, `test_export_parsers.py`, `test_connector_pinterest.py`, `test_connector_reddit.py`, `test_connectors_api.py`, `test_sleep_connector_poll.py`.

**New app files**

| Path | Responsibility |
|---|---|
| `Sources/CicadaApp/Models/UploadPreview.swift` | `UploadPreview` + `UploadCollection` wire models. |
| `Sources/CicadaApp/Models/Connector.swift` | `ConnectorStatus` + `ConnectorField` + `ConnectorSyncResult`. |
| `Sources/CicadaApp/Views/Capture/Sheets/ImportCatalog.swift` | Route badges + the pure tile-state function. |
| `Sources/CicadaApp/Views/Capture/Sheets/ImportOverlay.swift` | The export overlay: stage machine + preview list. |
| `Sources/CicadaApp/Views/Capture/Sheets/ConnectorSetupPanel.swift` | Guided credential entry + status for Pinterest/Reddit. |

**New app tests:** `ImportCatalogTests.swift`, `ImportOverlayTests.swift`, `ConnectorSetupTests.swift`.

---

## Task Dependency Order

1 → 2 → (3, 4, 5 in any order) → 6 → 7 → 8 → 9 → 10 → 11 → 12.
Tasks 3/4/5 each register one entry in the `PLATFORM_BY_LABEL` map Task 2 creates.

---

### Task 1: Telegram save-with-reason + the `saved-because` claim

**Files:**
- Modify: `api/services/agentic_write.py:232-341` (`write_claim` signature + origin)
- Modify: `api/services/media_ingestor.py:50-78` (`RawItem`), `:937-957` (`_episode_body`), `:970-1003` (`write_media_episode`)
- Modify: `api/services/telegram_capture.py`
- Modify: `api/routers/capture.py`
- Test: `api/tests/test_telegram_capture.py`

**Interfaces:**
- Produces: `media_ingestor.RawItem(..., reason: str | None = None)`; `telegram_capture.extract_reason(text: str, urls: list[str]) -> str | None`; `parse_telegram_update` now also returns `"reason"` and `"chat_id"`; `ingest_telegram_update` returns an extra `"ack": str | None` and `"chat_id": int | None`; `agentic_write.write_claim(..., origin: str | None = None)`.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing reason-extraction tests**

Append to `api/tests/test_telegram_capture.py`:

```python
# --- reason extraction (G71 §1) ---------------------------------------------


def test_parse_extracts_reason_after_the_url():
    update = _text_update("/save https://example.com/recipe great for meal prep")
    parsed = parse_telegram_update(update)
    assert parsed["urls"] == ["https://example.com/recipe"]
    assert parsed["reason"] == "great for meal prep"


def test_parse_extracts_reason_written_before_the_url():
    update = _text_update("great for meal prep https://example.com/recipe")
    assert parse_telegram_update(update)["reason"] == "great for meal prep"


def test_parse_strips_the_bot_command_and_its_at_suffix():
    update = _text_update("/save@cicada_bot https://example.com/x — worth rereading")
    assert parse_telegram_update(update)["reason"] == "worth rereading"


def test_parse_reason_is_none_when_only_a_url_was_sent():
    update = _text_update("https://example.com/bare")
    assert parse_telegram_update(update)["reason"] is None


def test_parse_reason_is_none_for_a_text_only_message():
    update = _text_update("remember to buy milk")
    assert parse_telegram_update(update)["reason"] is None


def test_parse_returns_the_chat_id():
    assert parse_telegram_update(_text_update("hello"))["chat_id"] == 111
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_telegram_capture.py -q -k reason or chat_id`
Expected: FAIL with `KeyError: 'reason'`.

- [ ] **Step 3: Implement reason extraction**

In `api/services/telegram_capture.py`, add below `_URL_RE` (line 43):

```python
# `/save`, `/note`, `/remind` — with or without the `@botname` suffix Telegram
# appends in group chats. Stripped before the reason is read so the command
# token never becomes part of the reason.
_COMMAND_RE = re.compile(r"^/(save|note|remind)(?:@\w+)?\b\s*", re.IGNORECASE)


def extract_reason(text: str, urls: list[str]) -> str | None:
    """Everything the user typed *around* the URL — the reason they saved it.

    The bot command and every URL are removed, whitespace is collapsed, and a
    leading separator ("— ", ": ", "- ") is trimmed so "https://x — worth
    rereading" yields "worth rereading". Returns ``None`` when nothing is left,
    and always ``None`` for a message with no URL at all (there the whole text
    IS the note, staged as an episode, and calling it a "reason" would double
    it into a claim about nothing).
    """
    if not urls:
        return None
    body = _COMMAND_RE.sub("", text or "", count=1)
    for url in urls:
        body = body.replace(url, " ")
    body = re.sub(r"\s+", " ", body).strip()
    body = body.lstrip("-–—:;,. ").strip()
    return body or None
```

In `parse_telegram_update`, replace the return block (lines 121-126) with:

```python
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}

    return {
        "text": text,
        "urls": urls,
        "date": date_iso,
        "from_self": from_self,
        "reason": extract_reason(text, urls),
        "chat_id": chat.get("id"),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_telegram_capture.py -q`
Expected: PASS (all, including the pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add api/services/telegram_capture.py api/tests/test_telegram_capture.py
git commit -m "$(cat <<'EOF'
feat(telegram): extract the save reason from /save messages

G71 §1 — everything typed around the URL is the reason, with the bot
command and the URL itself stripped. Pure, so it is testable without a bot.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

- [ ] **Step 6: Write the failing episode-body test**

Append to `api/tests/test_sources.py`:

```python
# --- G71 §1: the reason on the episode body ---------------------------------


def test_write_media_episode_renders_the_saved_because_section(tmp_path):
    episodes = tmp_path / "episodes"
    item = media_ingestor.RawItem(
        url="https://example.com/recipe", reason="great for meal prep"
    )
    meta = MediaMeta(title="A Recipe", site="example.com", media_type="url")
    episode_id = media_ingestor.write_media_episode(episodes, item, meta, "media-a-recipe")

    body = (episodes / f"{episode_id}.md").read_text(encoding="utf-8")
    assert "## Saved because" in body
    assert "great for meal prep" in body


def test_write_media_episode_omits_the_section_without_a_reason(tmp_path):
    episodes = tmp_path / "episodes"
    item = media_ingestor.RawItem(url="https://example.com/plain")
    meta = MediaMeta(title="Plain", site="example.com", media_type="url")
    episode_id = media_ingestor.write_media_episode(episodes, item, meta, "media-plain")
    assert "Saved because" not in (episodes / f"{episode_id}.md").read_text(encoding="utf-8")
```

- [ ] **Step 7: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_sources.py -q -k saved_because`
Expected: FAIL with `TypeError: RawItem.__init__() got an unexpected keyword argument 'reason'`.

- [ ] **Step 8: Add `RawItem.reason` and render it**

In `api/services/media_ingestor.py`, after `RawItem.origin` (line 69) add:

```python
    # G71 §1 — why the user saved this, in their own words (the text around the
    # URL in a Telegram `/save`). Rendered verbatim on the episode body as a
    # `## Saved because` section so Stage 1 extraction can pull concepts out of
    # it exactly as it would from conversation text, and written separately as a
    # `saved-because` claim by the caller that has one.
    reason: str | None = None
```

Change `_episode_body` (line 937) to:

```python
def _episode_body(
    meta: MediaMeta,
    url: str,
    saved_date: str,
    note: str | None,
    folder: str | None = None,
    reason: str | None = None,
) -> str:
```

and, immediately before the `if note:` block, add:

```python
    if reason:
        lines += ["", "## Saved because", reason]
```

In `write_media_episode` (line 980) change the body call to:

```python
    body = _episode_body(
        meta, item.url, saved_date, item.note, folder=item.folder, reason=item.reason
    )
```

- [ ] **Step 9: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_sources.py -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add api/services/media_ingestor.py api/tests/test_sources.py
git commit -m "$(cat <<'EOF'
feat(sources): RawItem.reason renders a `## Saved because` episode section

G71 §1 — the reason is prose Stage 1 extracts from, so it is a section
alongside `## User note`, not a bold field line.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

- [ ] **Step 11: Write the failing `write_claim(origin=...)` test**

Append to `api/tests/test_agentic_write.py`:

```python
def test_write_claim_accepts_an_explicit_origin(tmp_path):
    """G71 §1: a Telegram save is `user_stated` but is NOT a manual-assertion
    channel, so its claim must carry `origin: telegram` — which is deliberately
    outside claim_reconciler._HUMAN_ORIGINS, i.e. not overwrite-protected."""
    from api.services import markdown_parser
    from api.services.agentic_write import write_claim
    from api.services.claims import parse_claims

    entities = tmp_path / "entities"
    entities.mkdir(parents=True)
    markdown_parser.write(
        entities / "media-a-recipe.md",
        {"name": "A Recipe", "type": "media", "status": "active", "confidence": 0.7},
        "## Summary\nSaved url — A Recipe.",
    )

    result = write_claim(
        tmp_path,
        "media-a-recipe",
        "saved-because",
        "great for meal prep",
        observer="rodrigo",
        object_kind="literal",
        origin="telegram",
    )
    assert result["action"] != "error", result

    claims = parse_claims(markdown_parser.parse(entities / "media-a-recipe.md").body)
    written = [c for c in claims if c.predicate == "saved-because"]
    assert len(written) == 1
    assert written[0].origin == "telegram"
    assert written[0].source_trust == "user_stated"
    assert written[0].object_kind == "literal"


def test_write_claim_without_origin_is_unchanged(tmp_path):
    from api.services import markdown_parser
    from api.services.agentic_write import write_claim
    from api.services.claims import parse_claims

    entities = tmp_path / "entities"
    entities.mkdir(parents=True)
    markdown_parser.write(
        entities / "media-a-recipe.md",
        {"name": "A Recipe", "type": "media", "status": "active", "confidence": 0.7},
        "## Summary\nSaved url — A Recipe.",
    )
    write_claim(tmp_path, "media-a-recipe", "relates-to", "cooking", observer="rodrigo")
    claims = parse_claims(markdown_parser.parse(entities / "media-a-recipe.md").body)
    assert [c.origin for c in claims if c.predicate == "relates-to"] == ["manual_edit"]
```

- [ ] **Step 12: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_agentic_write.py -q -k origin`
Expected: FAIL with `TypeError: write_claim() got an unexpected keyword argument 'origin'`.

- [ ] **Step 13: Add the `origin` parameter**

In `api/services/agentic_write.py`, add to `write_claim`'s keyword-only block (after `session_id`, line 246):

```python
    origin: str | None = None,
```

and extend the docstring with:

```
    ``origin`` (G71) overrides the derived G9 provenance tag. Omitted, behavior
    is byte-identical to before it existed: ``manual_edit`` for
    ``observer="rodrigo"`` (the manual-assertion channel, and the only one that
    earns ``claim_reconciler.is_human`` overwrite protection), else ``mcp``.
    A connector/webhook write passes its own tag (``"telegram"``) so the claim
    reads as user-stated without claiming manual-assertion immunity.
```

Replace lines 317-322 with:

```python
        source_trust = "user_stated" if observer == "rodrigo" else "agent_extracted"
        # Origin-gated human protection (claim_reconciler.is_human): only a
        # manual/clarification origin makes a user_stated claim overwrite-
        # protected. An explicit observer=rodrigo write through this tool IS
        # that manual-assertion channel — unless the caller names a different
        # origin (a webhook, a connector), which by construction is not.
        claim_origin = (origin or "").strip() or (
            "manual_edit" if observer == "rodrigo" else "mcp"
        )
```

and in the `Claim(...)` constructor (line 339) change `origin=origin,` to `origin=claim_origin,`.

- [ ] **Step 14: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_agentic_write.py api/tests/test_claim_reconciler.py -q`
Expected: PASS.

- [ ] **Step 15: Commit**

```bash
git add api/services/agentic_write.py api/tests/test_agentic_write.py
git commit -m "$(cat <<'EOF'
feat(claims): write_claim accepts an explicit origin

G71 §1 — a Telegram save is user_stated but is not the manual-assertion
channel, so it needs `origin: telegram` (outside _HUMAN_ORIGINS) rather than
borrowing manual_edit's overwrite protection. Omitting it is unchanged.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

- [ ] **Step 16: Write the failing routing + claim + ACK tests**

In `api/tests/test_telegram_capture.py`, first update the three existing doubles so they accept the new keyword — `fake_save_url` in `test_ingest_url_message_calls_save_url_fn`, `test_ingest_url_message_save_url_fn_may_be_async` and `test_ingest_prefers_url_path_when_both_text_and_url_present` all become `def fake_save_url(memory_path, url, *, note=None, reason=None):`. Then append:

```python
# --- reason routing + ACK (G71 §1) ------------------------------------------


def test_ingest_passes_the_reason_to_the_url_writer(tmp_path):
    seen = {}

    def fake_save_url(memory_path, url, *, note=None, reason=None):
        seen["reason"] = reason
        return {"status": "created", "media_entity_id": "media-x", "episode_id": "ep_x"}

    update = _text_update("/save https://example.com/recipe great for meal prep")
    result = run(ingest_telegram_update(tmp_path, update, save_url_fn=fake_save_url))
    assert seen["reason"] == "great for meal prep"
    assert result["ack"] == "Saved with note: great for meal prep"
    assert result["chat_id"] == 111


def test_ingest_acks_a_plain_save_and_a_duplicate(tmp_path):
    def created(memory_path, url, *, note=None, reason=None):
        return {"status": "created", "media_entity_id": "m", "episode_id": "e"}

    def duplicate(memory_path, url, *, note=None, reason=None):
        return {"status": "duplicate", "media_entity_id": "m", "episode_id": "e"}

    plain = _text_update("https://example.com/bare")
    assert run(ingest_telegram_update(tmp_path, plain, save_url_fn=created))["ack"] == "Saved."
    assert run(ingest_telegram_update(tmp_path, plain, save_url_fn=duplicate))["ack"] == "Already saved."


def test_ingest_acks_a_text_only_note(tmp_path):
    def fake_save_episode(memory_path, text, *, title=None):
        return {"status": "created", "episode_id": "ep_1"}

    result = run(ingest_telegram_update(
        tmp_path, _text_update("call the dentist"), save_episode_fn=fake_save_episode))
    assert result["ack"] == "Noted."


def test_skipped_update_has_no_ack(tmp_path):
    result = run(ingest_telegram_update(tmp_path, {"update_id": 9, "poll_answer": {}}))
    assert result["kind"] == "skipped"
    assert result.get("ack") is None
```

- [ ] **Step 17: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_telegram_capture.py -q -k "reason or ack"`
Expected: FAIL with `KeyError: 'ack'`.

- [ ] **Step 18: Route the reason and build the ACK**

Replace the body of `ingest_telegram_update` from `text = parsed["text"]` (line 164) to the end of the function with:

```python
    text = parsed["text"]
    urls = parsed["urls"]
    reason = parsed["reason"]
    chat_id = parsed["chat_id"]

    try:
        if urls:
            fn = save_url_fn or _default_save_url
            result = await _maybe_await(
                fn(memory_path, urls[0], note=text or None, reason=reason)
            )
            status = (result or {}).get("status") if isinstance(result, dict) else None
            if status == "duplicate":
                ack = "Already saved."
            elif reason:
                ack = f"Saved with note: {reason}"
            else:
                ack = "Saved."
            return {"kind": "url", "url": urls[0], "result": result,
                    "ack": ack, "chat_id": chat_id}

        fn = save_episode_fn or _default_save_episode
        result = await _maybe_await(fn(memory_path, text, title=None))
        return {"kind": "note", "result": result, "ack": "Noted.", "chat_id": chat_id}
    except Exception as e:
        logger.warning(f"telegram ingest failed: {type(e).__name__}: {e}")
        return {"kind": "skipped", "reason": f"{type(e).__name__}: {e}",
                "ack": None, "chat_id": chat_id}
```

and in the two earlier `return {"kind": "skipped", ...}` branches (lines 159 and 162) add `"ack": None, "chat_id": None`.

Update the docstring's writer contract line to:

```
    ``save_url_fn(memory_path, url, note=..., reason=...)`` / ``save_episode_fn(
    memory_path, text, title=...)`` may be sync or async.
```

- [ ] **Step 19: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_telegram_capture.py -q`
Expected: PASS.

- [ ] **Step 20: Write the failing default-writer claim test**

Append to `api/tests/test_telegram_capture.py`:

```python
def test_default_save_url_writes_a_saved_because_claim(tmp_path, monkeypatch):
    """The real writer, hermetic: enrichment offline, git commit stubbed."""
    import asyncio

    from api.services import claims, markdown_parser, media_ingestor
    from api.services.media_ingestor import MediaMeta

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    async def offline(url, client, from_bookmark_file=False):
        return MediaMeta(title="A Recipe", description="", site="example.com",
                         media_type="url")

    async def no_commit(memory_path, count):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)

    result = asyncio.run(telegram_capture._default_save_url(
        memory, "https://example.com/recipe", note="great for meal prep",
        reason="great for meal prep",
    ))
    assert result["status"] == "created"

    page = memory / "entities" / f"{result['media_entity_id']}.md"
    written = [c for c in claims.parse_claims(markdown_parser.parse(page).body)
               if c.predicate == "saved-because"]
    assert len(written) == 1
    assert written[0].object == "great for meal prep"
    assert written[0].origin == "telegram"
    assert written[0].object_kind == "literal"
```

- [ ] **Step 21: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_telegram_capture.py -q -k saved_because`
Expected: FAIL with `TypeError: _default_save_url() got an unexpected keyword argument 'reason'`.

- [ ] **Step 22: Write the claim from the default writer**

In `api/services/telegram_capture.py`, add before `_default_save_url`:

```python
def _write_saved_because_claim(
    memory_path: Path, media_entity_id: str, reason: str, episode_id: str
) -> None:
    """The reason, as a first-class ``saved-because`` claim on the media page.

    ``object_kind="literal"`` on purpose: Stage 5.7's
    ``regenerate_edges_from_claims`` projects only node-object claims, so a
    free-text reason must never become a graph edge — it stays prose the Feed
    card can show and Stage 1 can mine for concepts. ``origin="telegram"`` keeps
    the claim honest: user-stated, but not the manual-assertion channel, so it
    does not inherit ``claim_reconciler.is_human`` overwrite protection.

    Never raises — ``write_claim`` returns an error dict rather than throwing,
    and a failed claim must never lose the save that already succeeded.
    """
    from api.services.agentic_write import write_claim

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
    )
    if result.get("action") in {"error", "ambiguous_subject", "corrupt_claims_block"}:
        logger.warning(
            f"saved-because claim not written for {media_entity_id}: "
            f"{result.get('action')} — {result.get('error')}"
        )
```

Change `_default_save_url`'s signature and body (lines 205-229) to:

```python
async def _default_save_url(
    memory_path: Path, url: str, *, note: str | None = None, reason: str | None = None
) -> dict:
    """Real default for ``save_url_fn`` — the same path as ``POST /sources/save``."""
    import httpx

    from api.services import media_ingestor

    item = media_ingestor.RawItem(url=url, note=note, reason=reason)
    idx = media_ingestor.load_url_index(memory_path)
    async with httpx.AsyncClient() as client:
        result = await media_ingestor.ingest_one(item, memory_path, client, idx)
    media_ingestor.save_url_index(memory_path, idx)

    if result.status == "created":
        _tag_episode_origin(memory_path, result.episode_id, "telegram")
        if reason:
            _write_saved_because_claim(
                memory_path, result.media_entity_id, reason, result.episode_id
            )
        try:
            await media_ingestor._commit_media(memory_path, 1)
        except Exception as e:
            logger.warning(f"Telegram media commit failed: {type(e).__name__}: {e}")

    return {
        "status": result.status,
        "media_entity_id": result.media_entity_id,
        "episode_id": result.episode_id,
        "title": result.title,
    }
```

- [ ] **Step 23: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_telegram_capture.py -q`
Expected: PASS.

- [ ] **Step 24: Write the failing webhook-ACK test**

Append to `api/tests/test_telegram_capture.py`:

```python
def _webhook_client(tmp_path, monkeypatch):
    from api import config, main

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_TELEGRAM_BOT_TOKEN", "123:abc")
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_webhook_answers_with_a_send_message_ack(tmp_path, monkeypatch):
    """Telegram executes a `method` returned in the webhook RESPONSE, so the
    ACK needs no outgoing HTTP client and no token in this process."""
    from api import config

    client, _ = _webhook_client(tmp_path, monkeypatch)

    async def fake_ingest(memory_path, update):
        return {"kind": "url", "url": "https://example.com/x", "result": {},
                "ack": "Saved with note: worth rereading", "chat_id": 111}

    monkeypatch.setattr("api.routers.capture.ingest_telegram_update", fake_ingest)
    resp = client.post("/capture/telegram", json=_text_update("x"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["method"] == "sendMessage"
    assert body["chat_id"] == 111
    assert body["text"] == "Saved with note: worth rereading"
    config.get_settings.cache_clear()


def test_webhook_omits_the_method_when_there_is_nothing_to_ack(tmp_path, monkeypatch):
    from api import config

    client, _ = _webhook_client(tmp_path, monkeypatch)

    async def fake_ingest(memory_path, update):
        return {"kind": "skipped", "reason": "nope", "ack": None, "chat_id": None}

    monkeypatch.setattr("api.routers.capture.ingest_telegram_update", fake_ingest)
    body = client.post("/capture/telegram", json={}).json()
    assert "method" not in body
    config.get_settings.cache_clear()
```

- [ ] **Step 25: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_telegram_capture.py -q -k webhook`
Expected: FAIL with `KeyError: 'method'`.

- [ ] **Step 26: Return the ACK from the webhook**

In `api/routers/capture.py`, replace the last line of `capture_telegram` with:

```python
    result = await ingest_telegram_update(settings.memory_path, update)

    # Telegram executes a `method` returned in the webhook RESPONSE body, so the
    # bot can answer without an outgoing HTTP call and without the bot token
    # ever entering this process's request path (G71 §1).
    ack = result.get("ack")
    chat_id = result.get("chat_id")
    if ack and chat_id is not None:
        return {**result, "method": "sendMessage", "chat_id": chat_id, "text": ack}
    return result
```

and extend the docstring's last paragraph with:

```
    The response doubles as the bot's reply: when there is something to
    acknowledge it carries ``method: sendMessage`` so Telegram echoes
    "Saved with note: …" back into the chat.
```

- [ ] **Step 27: Run the full suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 28: Commit**

```bash
git add api/services/telegram_capture.py api/routers/capture.py api/tests/test_telegram_capture.py
git commit -m "$(cat <<'EOF'
feat(telegram): save-with-reason writes a saved-because claim and acks it

G71 §1 — the reason lands verbatim on the episode body and as a
`saved-because` user_stated/literal claim (origin: telegram) on the media
entity. The bot ACK rides the webhook response's `method: sendMessage`, so
no outgoing HTTP client or token handling is added.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 2: Staging-free parse preview (`POST /sources/upload?preview=true`)

**Files:**
- Modify: `api/services/media_ingestor.py:605-645` (`parse_youtube_takeout_zip`), `:793-849` (`parse_upload`)
- Modify: `api/models/schemas.py` (after `SourceUploadResponse`, line 1014)
- Modify: `api/routers/sources.py:104-169`
- Test: `api/tests/test_upload_preview.py` (new)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `media_ingestor.UploadPreview` dataclass (`recognized: bool`, `platform: str`, `total: int`, `collections: list[dict]`, `warnings: list[str]`); `media_ingestor.preview_upload(content: bytes, filename: str, *, include_history: bool = False) -> UploadPreview`; `media_ingestor.PLATFORM_BY_LABEL: dict[str, str]` and `COLLECTION_KIND_BY_PLATFORM: dict[str, str]` (Tasks 3–5 each add one entry); `parse_upload(content, filename, *, include_history: bool = False, warnings: list[str] | None = None)`; schemas `SourceUploadCollection` / `SourceUploadPreview`; endpoint `POST /sources/upload?preview=true[&include_history=true]`.

- [ ] **Step 1: Write the failing preview-grouping tests**

Create `api/tests/test_upload_preview.py`:

```python
"""Hermetic tests for the staging-free import preview (G71 §4.3).

`preview_upload` must be pure: no episode, no entity, no url_index write, no
commit, no network. Every fixture here is synthetic — never a real personal
export (CLAUDE.md's benchmark privacy rule applies to test data too).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import media_ingestor

IG_EXPORT = {
    "saved_saved_media": [
        {"name": "Recipes", "media": [
            {"title": "cook_account", "string_map_data": {
                "Saved on": {"href": "https://example.com/p/aaa", "timestamp": 1}}},
            {"title": "cook_account", "string_map_data": {
                "Saved on": {"href": "https://example.com/p/bbb", "timestamp": 2}}},
        ]},
        {"name": "Type inspo", "media": [
            {"title": "type_account", "string_map_data": {
                "Saved on": {"href": "https://example.com/p/ccc", "timestamp": 3}}},
        ]},
    ]
}


def test_preview_groups_instagram_collections_with_counts():
    preview = media_ingestor.preview_upload(
        json.dumps(IG_EXPORT).encode(), "saved_posts.json"
    )
    assert preview.recognized is True
    assert preview.platform == "instagram"
    assert preview.total == 3
    assert preview.collections == [
        {"name": "Recipes", "kind": "collection", "count": 2},
        {"name": "Type inspo", "kind": "collection", "count": 1},
    ]
    assert preview.warnings == []


def test_preview_stages_absolutely_nothing(tmp_path):
    """The whole point: a preview writes no file anywhere."""
    before = sorted(p.name for p in tmp_path.iterdir())
    media_ingestor.preview_upload(json.dumps(IG_EXPORT).encode(), "saved_posts.json")
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_preview_of_an_unsupported_extension_is_not_recognized():
    preview = media_ingestor.preview_upload(b"binary", "photo.heic")
    assert preview.recognized is False
    assert preview.platform == "unknown"
    assert preview.total == 0
    assert preview.collections == []
    assert preview.warnings and "Unsupported file format" in preview.warnings[0]


def test_preview_of_malformed_json_is_not_recognized_and_says_why():
    preview = media_ingestor.preview_upload(b"{not json", "saved.json")
    assert preview.recognized is False
    assert preview.warnings and "saved.json" in preview.warnings[0]


def test_preview_of_a_recognized_but_empty_file_warns_honestly():
    preview = media_ingestor.preview_upload(b"# nothing here\n", "links.txt")
    assert preview.recognized is False
    assert preview.total == 0
    assert any("no saved links" in w for w in preview.warnings)


def test_preview_ungrouped_items_fall_into_one_bucket():
    preview = media_ingestor.preview_upload(
        b"https://example.com/a\nhttps://example.com/b\n", "links.txt"
    )
    assert preview.recognized is True
    assert preview.platform == "urls"
    assert preview.collections == [{"name": "Ungrouped", "kind": "list", "count": 2}]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_upload_preview.py -q`
Expected: FAIL with `AttributeError: module 'api.services.media_ingestor' has no attribute 'preview_upload'`.

- [ ] **Step 3: Implement `preview_upload`**

In `api/services/media_ingestor.py`, change `parse_youtube_takeout_zip`'s signature (line 608) to:

```python
def parse_youtube_takeout_zip(content: bytes, warnings: list[str] | None = None) -> list[RawItem]:
```

and inside it, replace the `except Exception as e: logger.debug(...); continue` block's body with:

```python
            except Exception as e:
                logger.debug(f"Skipping unreadable zip member {name}: {type(e).__name__}: {e}")
                skipped += 1
                continue
```

initialising `skipped = 0` next to `items: list[RawItem] = []`, and just before `return items` add:

```python
    if warnings is not None and skipped:
        warnings.append(f"Skipped {skipped} unreadable file(s) inside the archive.")

    return items
```

Also change the two `except Exception: return []` early exits to append a warning first:

```python
    try:
        zf = zipfile.ZipFile(BytesIO(content))
    except Exception:
        if warnings is not None:
            warnings.append("This file is not a readable zip archive.")
        return []
```

Change `parse_upload`'s signature and the two branches it touches:

```python
def parse_upload(
    content: bytes,
    filename: str,
    *,
    include_history: bool = False,
    warnings: list[str] | None = None,
) -> tuple[list[RawItem], str, bool]:
    """Route an uploaded file to the right parser by extension + sniff.

    Returns ``(items, source_label, from_bookmark_file)``.

    ``include_history`` (G71 §3) opts a TikTok export's Browsing History in —
    default off, because ambient watch/browse exhaust is noise, not a save.
    ``warnings`` is an optional sink a caller (the preview endpoint) passes so
    partial-parse detail reaches the user instead of only the debug log; every
    existing positional caller is unaffected.
    """
```

and the zip branch:

```python
    if name.endswith(".zip"):
        return parse_youtube_takeout_zip(content, warnings), "YouTube Takeout (zip)", False
```

Then, immediately after `parse_upload`, add:

```python
# --- Import preview (G71 §4.3) ----------------------------------------------

# `parse_upload` source label -> stable lowercase platform id. The id is never
# user-facing: the companion app owns every display name (Copy.swift). Tasks
# that add a parser add their label here.
PLATFORM_BY_LABEL = {
    "Instagram Saved": "instagram",
    "YouTube Takeout": "youtube",
    "YouTube Takeout (zip)": "youtube",
    "YouTube Playlist": "youtube",
    "Bookmarks": "bookmarks",
    "Safari Bookmarks": "bookmarks",
    "Chrome Bookmarks": "bookmarks",
    "RSS Feed": "rss",
    "URL List": "urls",
}

# What ONE grouping is called on each platform, so the overlay can say
# "6 collections" / "6 boards" instead of a generic word.
COLLECTION_KIND_BY_PLATFORM = {
    "instagram": "collection",
    "youtube": "playlist",
    "pinterest": "board",
    "bookmarks": "folder",
    "rss": "feed",
    "urls": "list",
    "unknown": "list",
}

DEFAULT_COLLECTION_NAME = "Ungrouped"


@dataclass
class UploadPreview:
    """What a dropped export CONTAINS — computed without staging any of it."""

    recognized: bool
    platform: str
    total: int
    collections: list[dict]  # [{"name": str, "kind": str, "count": int}]
    warnings: list[str]


def preview_upload(
    content: bytes, filename: str, *, include_history: bool = False
) -> UploadPreview:
    """Parse an upload WITHOUT staging anything (G71 §4.3).

    Pure and side-effect free: no episode, no entity, no ``url_index`` write,
    no commit, no network — it runs the same sniff/parse ``parse_upload`` does
    and then only *counts*. ``recognized`` is ``total > 0``: a format we can
    name but from which nothing parses is not a usable export, and saying
    "recognized" about it would be a lie the overlay then repeats.
    """
    warnings: list[str] = []
    try:
        items, label, _ = parse_upload(
            content, filename, include_history=include_history, warnings=warnings
        )
    except ValueError as e:
        return UploadPreview(False, "unknown", 0, [], [str(e)])
    except Exception as e:
        return UploadPreview(
            False, "unknown", 0, [],
            [f"Could not parse {filename or 'this file'}: {type(e).__name__}: {e}"],
        )

    platform = PLATFORM_BY_LABEL.get(label, "unknown")
    kind = COLLECTION_KIND_BY_PLATFORM.get(platform, "list")

    counts: dict[str, int] = {}
    for item in items:
        if not item.url:
            continue
        name = (item.folder or "").strip() or DEFAULT_COLLECTION_NAME
        counts[name] = counts.get(name, 0) + 1

    total = sum(counts.values())
    if total == 0:
        warnings.append(
            f"Read this as {label} but found no saved links in it — if you dropped "
            "an archive, unzip it and drop the individual export file instead."
        )

    collections = [
        {"name": n, "kind": kind, "count": counts[n]}
        for n in sorted(counts, key=lambda n: (-counts[n], n))
    ]
    return UploadPreview(total > 0, platform, total, collections, warnings)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_upload_preview.py api/tests/test_sources.py api/tests/test_bookmarks_safari.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/services/media_ingestor.py api/tests/test_upload_preview.py
git commit -m "$(cat <<'EOF'
feat(sources): preview_upload — parse an export without staging any of it

G71 §4.3 — groups parsed items by collection with per-collection counts and
honest warnings. Pure: no writes, no network, no commit. parse_upload gains
an optional warnings sink and an include_history flag; both default to
today's behaviour for every existing caller.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

- [ ] **Step 6: Write the failing endpoint tests**

Append to `api/tests/test_upload_preview.py`:

```python
# --- endpoint: POST /sources/upload?preview=true -----------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _post_preview(c, filename, payload, query="?preview=true"):
    return c.post(
        "/sources/upload" + query,
        files={"file": (filename, payload, "application/octet-stream")},
    )


def test_preview_endpoint_returns_camel_cased_collections(client):
    c, memory = client
    resp = _post_preview(c, "saved_posts.json", json.dumps(IG_EXPORT).encode())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recognized"] is True
    assert body["platform"] == "instagram"
    assert body["total"] == 3
    assert body["collections"][0] == {"name": "Recipes", "kind": "collection", "count": 2}
    assert body["warnings"] == []


def test_preview_endpoint_writes_nothing_to_the_bank(client):
    c, memory = client
    _post_preview(c, "saved_posts.json", json.dumps(IG_EXPORT).encode())
    assert list((memory / "episodes").glob("*.md")) == []
    assert list((memory / "entities").glob("*.md")) == []
    assert not (memory / "sources" / "url_index.json").exists()


def test_preview_endpoint_reports_an_unsupported_file_as_200_not_422(client):
    """The overlay renders `recognized: false` + warnings; it must not have to
    parse an error status to do so."""
    c, _ = client
    resp = _post_preview(c, "photo.heic", b"binary")
    assert resp.status_code == 200, resp.text
    assert resp.json()["recognized"] is False


def test_real_upload_path_is_unchanged_without_the_flag(client):
    c, memory = client
    resp = c.post(
        "/sources/upload",
        files={"file": ("links.txt", b"https://example.com/a\n", "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["episodesCreated"] == 1
    assert len(list((memory / "episodes").glob("*.md"))) == 1
```

- [ ] **Step 7: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_upload_preview.py -q -k endpoint`
Expected: FAIL — the response is a `SourceUploadResponse`, so `body["recognized"]` raises `KeyError`.

- [ ] **Step 8: Add the schemas**

In `api/models/schemas.py`, immediately after `SourceUploadResponse` (line 1014), add:

```python
class SourceUploadCollection(CamelModel):
    """One grouping inside an export — an IG collection, a YT playlist, a
    Pinterest board, a bookmark folder — with how many items it holds."""

    name: str
    kind: str = "list"
    count: int = 0


class SourceUploadPreview(CamelModel):
    """`POST /sources/upload?preview=true` — what a dropped export CONTAINS.

    Staging-free by contract: answering this request writes no episode, no
    entity, no url_index entry and no commit, and touches no network.
    ``recognized`` is false both for a file we cannot parse at all and for one
    whose format we recognize but which yields nothing — ``warnings`` says which.
    """

    recognized: bool = False
    platform: str = "unknown"
    total: int = 0
    collections: list[SourceUploadCollection] = []
    warnings: list[str] = []
```

- [ ] **Step 9: Add the endpoint mode**

In `api/routers/sources.py`, add `SourceUploadCollection` and `SourceUploadPreview` to the `api.models.schemas` import block, then change `upload_sources` (line 104) to:

```python
@router.post("/sources/upload", response_model=None)
async def upload_sources(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    preview: bool = Query(False),
    include_history: bool = Query(False),
    settings: Settings = Depends(get_settings),
) -> SourceUploadResponse | SourceUploadPreview:
    """Ingest — or, with ``?preview=true``, merely *describe* — a saved-content export.

    Parses and dedups synchronously so counts come back immediately; enrichment
    and the episode/entity writes run in the background for large batches.

    ``?preview=true`` (G71 §4.3) STAGES NOTHING: it runs the identical sniff and
    parse, then returns the collection/board/playlist breakdown with per-item
    counts so the import overlay can show the user what they are about to import
    before they commit to it. Nothing is cached server-side — Confirm re-posts
    the same file without the flag.

    ``?include_history=true`` opts a TikTok export's Browsing History in (default
    off: ambient exhaust, not saves — G69).
    """
    content = await file.read()
    filename = file.filename or ""

    if preview:
        # Off the event loop: parsing a large export (a Takeout zip) is CPU-bound
        # and would otherwise stall the SSE stream, same reason /sources/channels
        # threadpools its origin scan.
        result = await run_in_threadpool(
            media_ingestor.preview_upload,
            content,
            filename,
            include_history=include_history,
        )
        logger.info(
            f"Sources preview: {filename} ({len(content)} bytes) -> "
            f"{result.platform}, {result.total} item(s)"
        )
        return SourceUploadPreview(
            recognized=result.recognized,
            platform=result.platform,
            total=result.total,
            collections=[SourceUploadCollection(**c) for c in result.collections],
            warnings=result.warnings,
        )

    logger.info(f"Sources upload: {filename} ({len(content)} bytes)")

    try:
        items, source_label, from_bookmark_file = media_ingestor.parse_upload(
            content, filename, include_history=include_history
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse {filename}: {e}")
```

(The rest of the function body — the `MAX_BATCH` guard onward — is unchanged.)

- [ ] **Step 10: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add api/models/schemas.py api/routers/sources.py api/tests/test_upload_preview.py
git commit -m "$(cat <<'EOF'
feat(api): POST /sources/upload?preview=true describes an export, stages none of it

G71 §4.3 — returns {recognized, platform, total, collections[], warnings[]},
threadpooled so a large archive never stalls the event loop. An unparseable
file is a 200 with recognized:false, so the overlay renders warnings instead
of decoding an error status. ?include_history=true threads the TikTok flag.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 3: LinkedIn saved-items parser

**Files:**
- Modify: `api/services/media_ingestor.py` (new parser next to `parse_youtube_playlist_csv`; `.csv` branch of `parse_upload`; `PLATFORM_BY_LABEL`; `COLLECTION_KIND_BY_PLATFORM`)
- Test: `api/tests/test_export_parsers.py` (new)

**Interfaces:**
- Consumes: `media_ingestor.PLATFORM_BY_LABEL`, `COLLECTION_KIND_BY_PLATFORM`, `preview_upload` (Task 2).
- Produces: `media_ingestor._norm_header(name: str | None) -> str`; `media_ingestor._pick_column(fieldnames: list[str] | None, candidates: tuple[str, ...]) -> str | None`; `media_ingestor.parse_linkedin_saved(content: bytes, filename: str) -> list[RawItem]`; source label `"LinkedIn Saved"`; platform id `"linkedin"`; origin `"linkedin-saved"`; folder `"Saved Items"`.

- [ ] **Step 1: Write the failing parser tests**

Create `api/tests/test_export_parsers.py`:

```python
"""Hermetic tests for the G47-family export parsers added by G71 §3.

Every fixture is SYNTHETIC. No real personal export, no real saved URL, no
real account name may enter this file — CLAUDE.md's benchmark privacy rule
applies to test data exactly as it does to benchmarks/questions.example.yaml.
"""

from __future__ import annotations

import json

from api.services import media_ingestor

# --- LinkedIn saved items ----------------------------------------------------

LINKEDIN_CSV = (
    b"savedItem,savedAt\n"
    b"https://example.com/posts/aaa,2026-01-02 10:00:00\n"
    b"https://example.com/posts/bbb,2026-01-03 11:00:00\n"
)


def test_parse_linkedin_saved_reads_url_and_date():
    items = media_ingestor.parse_linkedin_saved(LINKEDIN_CSV, "Saved Items.csv")
    assert [i.url for i in items] == [
        "https://example.com/posts/aaa",
        "https://example.com/posts/bbb",
    ]
    assert items[0].added == "2026-01-02 10:00:00"
    assert items[0].folder == "Saved Items"
    assert items[0].origin == "linkedin-saved"
    assert items[0].title is None, "the export carries no title — never invent one"


def test_parse_linkedin_saved_accepts_a_generic_url_column_when_the_filename_says_so():
    csv_bytes = b"url,date\nhttps://example.com/posts/ccc,2026-01-04\n"
    items = media_ingestor.parse_linkedin_saved(csv_bytes, "Saved_Items.csv")
    assert [i.url for i in items] == ["https://example.com/posts/ccc"]


def test_parse_linkedin_saved_ignores_a_generic_csv_with_an_unrelated_name():
    """A plain URL CSV must NOT be claimed by the LinkedIn parser."""
    csv_bytes = b"url,date\nhttps://example.com/x,2026-01-04\n"
    assert media_ingestor.parse_linkedin_saved(csv_bytes, "my-links.csv") == []


def test_parse_linkedin_saved_skips_non_http_rows_and_never_raises():
    csv_bytes = b"savedItem,savedAt\n,2026-01-02\nnot-a-url,2026-01-03\n"
    assert media_ingestor.parse_linkedin_saved(csv_bytes, "Saved Items.csv") == []
    assert media_ingestor.parse_linkedin_saved(b"\x00\x01binary", "Saved Items.csv") == []


def test_parse_upload_routes_linkedin_saved_csv():
    items, label, from_bookmark = media_ingestor.parse_upload(LINKEDIN_CSV, "Saved Items.csv")
    assert label == "LinkedIn Saved"
    assert from_bookmark is False
    assert len(items) == 2


def test_preview_reports_linkedin_as_one_saved_collection():
    preview = media_ingestor.preview_upload(LINKEDIN_CSV, "Saved Items.csv")
    assert preview.recognized is True
    assert preview.platform == "linkedin"
    assert preview.collections == [{"name": "Saved Items", "kind": "saved", "count": 2}]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_export_parsers.py -q`
Expected: FAIL with `AttributeError: module 'api.services.media_ingestor' has no attribute 'parse_linkedin_saved'`.

- [ ] **Step 3: Implement the parser**

In `api/services/media_ingestor.py`, immediately after `parse_youtube_playlist_csv` (line 599), add:

```python
# --- Shared CSV header sniffing (LinkedIn + Reddit exports) ------------------


def _norm_header(name: str | None) -> str:
    """Lowercased, BOM- and whitespace-stripped column name for comparison."""
    return (name or "").strip().lstrip("﻿").lower()


def _pick_column(fieldnames: list[str] | None, candidates: tuple[str, ...]) -> str | None:
    """The first real column name whose normalized form is in ``candidates``."""
    for name in fieldnames or []:
        if _norm_header(name) in candidates:
            return name
    return None


# LinkedIn has renamed this column across export generations, so match a set
# rather than one string. The SPECIFIC names are safe to match anywhere; the
# GENERIC ones (``url``, ``link``) are only trusted when the filename already
# says LinkedIn, or every plain URL CSV in the world would be claimed here.
_LINKEDIN_SPECIFIC_URL_FIELDS = ("saveditem", "saved item", "saveditemurl", "saved item url")
_LINKEDIN_GENERIC_URL_FIELDS = ("url", "link", "itemurl", "item url")
_LINKEDIN_DATE_FIELDS = (
    "savedat", "saved at", "saveddate", "saved date", "createdtime", "created time", "date",
)


def _is_linkedin_saved_filename(filename: str) -> bool:
    stem = Path(filename or "").stem.lower().replace("_", " ").replace("-", " ")
    return "saved item" in stem


def parse_linkedin_saved(content: bytes, filename: str) -> list[RawItem]:
    """LinkedIn "Get a copy of your data" — the Saved Items file.

    Thin by design (G69): the export carries a URL and a saved date and nothing
    else — no post text, no author. LinkedIn §8.2 bans fetching the post body,
    so these stay thin nodes whose only edges come from the folder tag, and the
    UI says so. Never invents a title.

    An unrecognized CSV yields ``[]`` — never raises.
    """
    import csv
    import io

    try:
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames
    except Exception:
        return []

    url_col = _pick_column(fieldnames, _LINKEDIN_SPECIFIC_URL_FIELDS)
    if url_col is None and _is_linkedin_saved_filename(filename):
        url_col = _pick_column(fieldnames, _LINKEDIN_GENERIC_URL_FIELDS)
    if url_col is None:
        return []
    date_col = _pick_column(fieldnames, _LINKEDIN_DATE_FIELDS)

    items: list[RawItem] = []
    for row in reader:
        url = (row.get(url_col) or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        added = None
        if date_col:
            added = (row.get(date_col) or "").strip() or None
        items.append(RawItem(
            url=url,
            added=added,
            folder="Saved Items",
            origin="linkedin-saved",
        ))
    return items
```

In `parse_upload`'s `.csv` branch, insert between the playlist attempt and the URL-list fallback:

```python
        linkedin_items = parse_linkedin_saved(content, filename or name)
        if linkedin_items:
            return linkedin_items, "LinkedIn Saved", False
```

Add to `PLATFORM_BY_LABEL`: `"LinkedIn Saved": "linkedin",`
Add to `COLLECTION_KIND_BY_PLATFORM`: `"linkedin": "saved",`

- [ ] **Step 4: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_export_parsers.py api/tests/test_sources.py -q`
Expected: PASS (including `test_parse_upload_random_csv_still_falls_through_to_url_list` and `test_parse_upload_csv_with_url_column_still_works_unaffected`, which prove the generic-CSV guard holds).

- [ ] **Step 5: Commit**

```bash
git add api/services/media_ingestor.py api/tests/test_export_parsers.py
git commit -m "$(cat <<'EOF'
feat(sources): LinkedIn saved-items export parser

G71 §3 / G69 — URL + saved date only; no enrichment fetch (§8.2 bans it), no
invented titles. Column names are sniffed from a candidate set because the
export has renamed them; the generic url/link columns are trusted only when
the filename already says LinkedIn, so plain URL CSVs are untouched.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 4: TikTok favourites/likes parser (+ opt-in browsing history)

**Files:**
- Modify: `api/services/media_ingestor.py` (new parser after `parse_instagram_saved`; `.json` branch of `parse_upload`; both platform maps)
- Test: `api/tests/test_export_parsers.py`

**Interfaces:**
- Consumes: `PLATFORM_BY_LABEL`, `COLLECTION_KIND_BY_PLATFORM`, `parse_upload(..., include_history=)` (Task 2).
- Produces: `media_ingestor._TIKTOK_SECTIONS`; `media_ingestor._tiktok_activity(data) -> dict | None`; `media_ingestor._is_tiktok_export_json(data) -> bool`; `media_ingestor.parse_tiktok_export(data, *, include_history: bool = False) -> list[RawItem]`; source label `"TikTok Export"`; platform id `"tiktok"`; origins `"tiktok-saved"` / `"tiktok-history"`; folders `"Favorites"` / `"Likes"` / `"Browsing History"`.

- [ ] **Step 1: Write the failing parser tests**

Append to `api/tests/test_export_parsers.py`:

```python
# --- TikTok user_data.json ---------------------------------------------------

TIKTOK_EXPORT = {
    "Activity": {
        "Favorite Videos": {"FavoriteVideoList": [
            {"Date": "2026-01-02 10:00:00", "Link": "https://example.com/video/1"},
            {"Date": "2026-01-03 10:00:00", "Link": "https://example.com/video/2"},
        ]},
        "Like List": {"ItemFavoriteList": [
            {"Date": "2026-01-04 10:00:00", "link": "https://example.com/video/3"},
        ]},
        "Video Browsing History": {"VideoList": [
            {"Date": "2026-01-05 10:00:00", "Link": "https://example.com/video/4"},
        ]},
    }
}


def test_parse_tiktok_export_reads_favorites_and_likes_but_not_history():
    items = media_ingestor.parse_tiktok_export(TIKTOK_EXPORT)
    assert [i.url for i in items] == [
        "https://example.com/video/1",
        "https://example.com/video/2",
        "https://example.com/video/3",
    ]
    assert [i.folder for i in items] == ["Favorites", "Favorites", "Likes"]
    assert {i.origin for i in items} == {"tiktok-saved"}
    assert items[0].added == "2026-01-02 10:00:00"


def test_parse_tiktok_export_includes_history_only_when_opted_in():
    items = media_ingestor.parse_tiktok_export(TIKTOK_EXPORT, include_history=True)
    assert len(items) == 4
    history = [i for i in items if i.folder == "Browsing History"]
    assert [i.origin for i in history] == ["tiktok-history"], (
        "history is ambient exhaust and must stay distinguishable from a save"
    )


def test_parse_tiktok_export_tolerates_the_your_activity_wrapper():
    items = media_ingestor.parse_tiktok_export({"Your Activity": TIKTOK_EXPORT["Activity"]})
    assert len(items) == 3


def test_parse_tiktok_export_degrades_to_empty_on_junk():
    assert media_ingestor.parse_tiktok_export({}) == []
    assert media_ingestor.parse_tiktok_export({"Activity": {"Like List": "nope"}}) == []
    assert media_ingestor.parse_tiktok_export("not a dict") == []


def test_parse_upload_routes_tiktok_json_and_honours_the_flag():
    payload = json.dumps(TIKTOK_EXPORT).encode()
    items, label, from_bookmark = media_ingestor.parse_upload(payload, "user_data.json")
    assert label == "TikTok Export"
    assert from_bookmark is False
    assert len(items) == 3

    with_history, _, _ = media_ingestor.parse_upload(
        payload, "user_data.json", include_history=True
    )
    assert len(with_history) == 4


def test_preview_reports_tiktok_lists_with_counts():
    preview = media_ingestor.preview_upload(json.dumps(TIKTOK_EXPORT).encode(), "user_data.json")
    assert preview.platform == "tiktok"
    assert preview.collections == [
        {"name": "Favorites", "kind": "list", "count": 2},
        {"name": "Likes", "kind": "list", "count": 1},
    ]


def test_preview_of_a_generic_json_url_list_is_unaffected_by_the_tiktok_sniff():
    preview = media_ingestor.preview_upload(
        b'["https://example.com/a", "https://example.com/b"]', "links.json"
    )
    assert preview.platform == "urls"
    assert preview.total == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_export_parsers.py -q -k tiktok`
Expected: FAIL with `AttributeError: module 'api.services.media_ingestor' has no attribute 'parse_tiktok_export'`.

- [ ] **Step 3: Implement the parser**

In `api/services/media_ingestor.py`, immediately after `_is_instagram_saved_json` (line 541), add:

```python
# TikTok's "Download your data" JSON, one row per section:
# (activity-section key, the list key inside it, the folder name, is_history).
_TIKTOK_SECTIONS = (
    ("Favorite Videos", "FavoriteVideoList", "Favorites", False),
    ("Like List", "ItemFavoriteList", "Likes", False),
    ("Video Browsing History", "VideoList", "Browsing History", True),
)


def _tiktok_activity(data) -> dict | None:
    """The activity dict, under either the old ``Activity`` key or the newer
    ``Your Activity`` one."""
    if not isinstance(data, dict):
        return None
    for key in ("Activity", "Your Activity"):
        section = data.get(key)
        if isinstance(section, dict):
            return section
    return None


def _is_tiktok_export_json(data) -> bool:
    """Sniff rule: an activity wrapper holding at least one known section."""
    activity = _tiktok_activity(data)
    return isinstance(activity, dict) and any(
        name in activity for name, _list_key, _folder, _hist in _TIKTOK_SECTIONS
    )


def parse_tiktok_export(data, *, include_history: bool = False) -> list[RawItem]:
    """TikTok "Download your data" ``user_data.json`` (G71 §3).

    Favourites and Likes are intentional saves and are always parsed.
    Browsing History is ambient exhaust (G69: high noise) and is parsed only
    when the caller opts in; even then it keeps a distinct ``tiktok-history``
    origin so ``/origins`` — and anyone reading the graph later — can tell a
    save from a scroll.

    Entry shape is ``{"Date": "...", "Link": "https://..."}``; older exports
    lowercase ``link``. Malformed input degrades to ``[]`` rather than raising.
    """
    activity = _tiktok_activity(data)
    if not isinstance(activity, dict):
        return []

    items: list[RawItem] = []
    for section_name, list_key, folder, is_history in _TIKTOK_SECTIONS:
        if is_history and not include_history:
            continue
        section = activity.get(section_name)
        if not isinstance(section, dict):
            continue
        rows = section.get(list_key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = row.get("Link") or row.get("link") or row.get("URL") or row.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            date = row.get("Date") or row.get("date")
            items.append(RawItem(
                url=url.strip(),
                added=date if isinstance(date, str) else None,
                folder=folder,
                origin="tiktok-history" if is_history else "tiktok-saved",
            ))
    return items
```

In `parse_upload`'s `.json` branch, immediately after the Instagram sniff, add:

```python
        # TikTok's export nests everything under an activity wrapper, so it can
        # never collide with the Instagram (`saved_*`) or Takeout (list) sniffs.
        if _is_tiktok_export_json(data):
            return parse_tiktok_export(data, include_history=include_history), "TikTok Export", False
```

Add to `PLATFORM_BY_LABEL`: `"TikTok Export": "tiktok",`
Add to `COLLECTION_KIND_BY_PLATFORM`: `"tiktok": "list",`

- [ ] **Step 4: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_export_parsers.py api/tests/test_sources.py api/tests/test_upload_preview.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/services/media_ingestor.py api/tests/test_export_parsers.py
git commit -m "$(cat <<'EOF'
feat(sources): TikTok favourites/likes export parser, history opt-in

G71 §3 — Favourites and Likes always parse (origin tiktok-saved); Browsing
History only with include_history=true and keeps a distinct tiktok-history
origin, so ambient scrolling never masquerades as an intentional save (G69).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 5: Reddit GDPR-export parser (`saved_posts.csv`)

**Files:**
- Modify: `api/services/media_ingestor.py` (new parser after `parse_linkedin_saved`; `.csv` branch; both platform maps)
- Test: `api/tests/test_export_parsers.py`

**Interfaces:**
- Consumes: `_pick_column`, `_norm_header`, `PLATFORM_BY_LABEL`, `COLLECTION_KIND_BY_PLATFORM` (Tasks 2–3).
- Produces: `media_ingestor.parse_reddit_saved_csv(content: bytes, filename: str) -> list[RawItem]`; source label `"Reddit Saved Export"`; platform id `"reddit"`; origin `"reddit-saved"`; folders `"Saved posts"` / `"Saved comments"`.

- [ ] **Step 1: Write the failing parser tests**

Append to `api/tests/test_export_parsers.py`:

```python
# --- Reddit GDPR export ------------------------------------------------------

REDDIT_CSV = (
    b"id,permalink\n"
    b"abc123,https://www.reddit.com/r/example/comments/abc123/a_title/\n"
    b"def456,/r/example/comments/def456/another_title/\n"
)


def test_parse_reddit_saved_csv_absolutizes_relative_permalinks():
    items = media_ingestor.parse_reddit_saved_csv(REDDIT_CSV, "saved_posts.csv")
    assert [i.url for i in items] == [
        "https://www.reddit.com/r/example/comments/abc123/a_title/",
        "https://www.reddit.com/r/example/comments/def456/another_title/",
    ]
    assert {i.origin for i in items} == {"reddit-saved"}
    assert {i.folder for i in items} == {"Saved posts"}


def test_parse_reddit_saved_comments_get_their_own_folder():
    items = media_ingestor.parse_reddit_saved_csv(REDDIT_CSV, "saved_comments.csv")
    assert {i.folder for i in items} == {"Saved comments"}


def test_parse_reddit_saved_csv_ignores_an_unrelated_csv():
    assert media_ingestor.parse_reddit_saved_csv(b"name,age\nAda,36\n", "people.csv") == []
    assert media_ingestor.parse_reddit_saved_csv(b"\x00binary", "saved_posts.csv") == []


def test_parse_upload_routes_the_reddit_export():
    items, label, from_bookmark = media_ingestor.parse_upload(REDDIT_CSV, "saved_posts.csv")
    assert label == "Reddit Saved Export"
    assert from_bookmark is False
    assert len(items) == 2


def test_preview_reports_the_reddit_export_as_saved_posts():
    preview = media_ingestor.preview_upload(REDDIT_CSV, "saved_posts.csv")
    assert preview.platform == "reddit"
    assert preview.collections == [{"name": "Saved posts", "kind": "saved", "count": 2}]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_export_parsers.py -q -k reddit`
Expected: FAIL with `AttributeError: module 'api.services.media_ingestor' has no attribute 'parse_reddit_saved_csv'`.

- [ ] **Step 3: Implement the parser**

In `api/services/media_ingestor.py`, immediately after `parse_linkedin_saved`, add:

```python
_REDDIT_PERMALINK_FIELDS = ("permalink",)
_REDDIT_FALLBACK_URL_FIELDS = ("permalink url", "url", "link")
REDDIT_BASE_URL = "https://www.reddit.com"


def _is_reddit_saved_filename(filename: str) -> bool:
    stem = Path(filename or "").stem.lower().replace("-", "_")
    return stem.startswith("saved_posts") or stem.startswith("saved_comments")


def parse_reddit_saved_csv(content: bytes, filename: str) -> list[RawItem]:
    """Reddit GDPR export ``saved_posts.csv`` / ``saved_comments.csv`` (G71 §2).

    Rows are ``id,permalink`` and nothing else. The export exists to backfill
    past the API's ~1,000-item listing cap (G69) — it is not the primary route.
    No Reddit-specific hydration call is needed: ``ingest_one`` already runs
    every URL through the OpenGraph enrichment path and reddit.com serves OG
    tags, so an online install gets a real title and an offline one degrades to
    the permalink slug, exactly like every other save.

    Permalinks may be relative (``/r/x/comments/...``); they are absolutized
    against ``https://www.reddit.com`` so ``normalize_url``/``url_hash`` dedup
    them against the same items pulled by the API connector.

    An unrecognized CSV yields ``[]`` — never raises.
    """
    import csv
    import io

    try:
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames
    except Exception:
        return []

    url_col = _pick_column(fieldnames, _REDDIT_PERMALINK_FIELDS)
    if url_col is None and _is_reddit_saved_filename(filename):
        url_col = _pick_column(fieldnames, _REDDIT_FALLBACK_URL_FIELDS)
    if url_col is None:
        return []

    stem = Path(filename or "").stem.lower()
    folder = "Saved comments" if "comment" in stem else "Saved posts"

    items: list[RawItem] = []
    for row in reader:
        raw = (row.get(url_col) or "").strip()
        if not raw:
            continue
        if raw.startswith("/"):
            raw = REDDIT_BASE_URL + raw
        if not raw.startswith(("http://", "https://")):
            continue
        items.append(RawItem(url=raw, folder=folder, origin="reddit-saved"))
    return items
```

In `parse_upload`'s `.csv` branch, insert the Reddit attempt between the playlist attempt and the LinkedIn attempt:

```python
        reddit_items = parse_reddit_saved_csv(content, filename or name)
        if reddit_items:
            return reddit_items, "Reddit Saved Export", False
```

Add to `PLATFORM_BY_LABEL`: `"Reddit Saved Export": "reddit",`
Add to `COLLECTION_KIND_BY_PLATFORM`: `"reddit": "saved",`

- [ ] **Step 4: Run the full suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/services/media_ingestor.py api/tests/test_export_parsers.py
git commit -m "$(cat <<'EOF'
feat(sources): Reddit GDPR saved-export parser

G71 §2 — backfills past the API's ~1,000-item listing cap. Relative
permalinks are absolutized so they dedup against the same items the API
connector pulls; titles come from the existing OG enrichment path, so no
Reddit-specific hydration call is added.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 6: Pinterest connector (BYO OAuth app → boards + pins)

**Files:**
- Create: `api/services/connectors/__init__.py`, `api/services/connectors/base.py`, `api/services/connectors/pinterest.py`
- Modify: `api/services/sync_state.py` (`record_sync(..., extra=)`, `record_error`)
- Modify: `api/tests/conftest.py` (autouse network-gate scrub)
- Test: `api/tests/test_connector_pinterest.py` (new), `api/tests/test_source_channels.py` (sync-state additions)

**Interfaces:**
- Consumes: `media_ingestor.RawItem`, `media_ingestor.ingest_batch`, `media_ingestor.MAX_BATCH`, `connections.secrets`.
- Produces:
  - `connectors.base.HttpFn = Callable[..., Any]` — called as `http_fn(method: str, url: str, *, headers=None, params=None, data=None, auth=None) -> dict`
  - `connectors.base.network_allowed(allow_fetch: bool | None = None) -> bool`
  - `connectors.base.default_http(...) -> dict`, `connectors.base.call_http(http_fn, method, url, **kwargs) -> dict`
  - `connectors.pinterest.CHANNEL_ID = "pinterest"`, `LABEL = "Pinterest"`, `FIELDS: tuple[dict, ...]`, `APP_ID_ENV`, `APP_SECRET_ENV`, `TOKEN_ENV`, `REDIRECT_PATH`
  - `pinterest.is_connected() -> bool`, `pinterest.credential_fields() -> list[dict]`
  - `pinterest.authorize_url(state: str, *, base_url: str = DEFAULT_BASE_URL) -> str`
  - `async pinterest.exchange_code(code, *, http_fn=None, base_url=DEFAULT_BASE_URL) -> None`
  - `async pinterest.fetch_boards(*, http_fn=None) -> list[dict]`, `async pinterest.fetch_pins(board_id, *, http_fn=None) -> list[dict]`
  - `pinterest.pins_to_items(board_name: str, pins: list[dict]) -> list[RawItem]`
  - `async pinterest.sync(memory_path, *, http_fn=None, allow_fetch=None) -> dict` → `{"status", "new", "seen", "boards", "error"}`
  - `sync_state.record_sync(memory_path, channel, *, count, at=None, extra=None)`, `sync_state.record_error(memory_path, channel, error, *, at=None)`

- [ ] **Step 1: Write the failing sync-state tests**

Append to `api/tests/test_source_channels.py`:

```python
def test_record_sync_accepts_extra_state_and_clears_a_previous_error(tmp_path):
    sync_state.record_error(tmp_path, "reddit", "HTTPStatusError: 401")
    sync_state.record_sync(tmp_path, "reddit", count=12, at="2026-08-31T10:00:00Z",
                           extra={"last_seen": "t3_abc"})
    entry = sync_state.read_sync_state(tmp_path)["reddit"]
    assert entry["count"] == 12
    assert entry["last_seen"] == "t3_abc"
    assert "last_error" not in entry, "a successful sync must clear the failure"


def test_record_error_keeps_the_last_successful_sync(tmp_path):
    sync_state.record_sync(tmp_path, "pinterest", count=40, at="2026-08-30T10:00:00Z")
    sync_state.record_error(tmp_path, "pinterest", "ConnectorError: token expired",
                            at="2026-08-31T10:00:00Z")
    entry = sync_state.read_sync_state(tmp_path)["pinterest"]
    assert entry["last_sync"] == "2026-08-30T10:00:00Z"
    assert entry["count"] == 40
    assert entry["last_error"] == "ConnectorError: token expired"
    assert entry["last_error_at"] == "2026-08-31T10:00:00Z"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_channels.py -q -k "extra or record_error"`
Expected: FAIL with `AttributeError: module 'api.services.sync_state' has no attribute 'record_error'`.

- [ ] **Step 3: Extend `sync_state`**

Replace `record_sync` in `api/services/sync_state.py` and add `record_error`:

```python
def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_state(memory_path: Path, state: dict) -> None:
    path = sync_state_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:  # a read-only bank must never fail the sync itself
        logger.warning(f"Could not write {SYNC_STATE_FILENAME}: {type(exc).__name__}: {exc}")


def record_sync(
    memory_path: Path,
    channel: str,
    *,
    count: int,
    at: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Stamp ``channel``'s last successful sync. Returns the full new state.

    A success REPLACES the entry, which deliberately clears any recorded
    ``last_error`` — the channel is working again and the Capture page must
    stop saying otherwise. ``extra`` (G71) carries per-connector cursor state,
    e.g. Reddit's newest-seen fullname.
    """
    state = read_sync_state(memory_path)
    entry = {"last_sync": at or _now_iso(), "count": int(count)}
    if extra:
        entry.update(extra)
    state[channel] = entry
    _write_state(memory_path, state)
    return state


def record_error(
    memory_path: Path, channel: str, error: str, *, at: str | None = None
) -> dict:
    """Record that ``channel``'s last poll FAILED, preserving its last success.

    G71: a connector sync never raises past ``sync()``; this is how the failure
    still reaches the user, as a per-channel line on ``GET /sources/channels``.
    ``error`` is a type+message string built by the caller — never a credential,
    never a raw response body.
    """
    state = read_sync_state(memory_path)
    entry = dict(state.get(channel) or {})
    entry["last_error"] = str(error)[:400]
    entry["last_error_at"] = at or _now_iso()
    state[channel] = entry
    _write_state(memory_path, state)
    return state
```

- [ ] **Step 4: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_channels.py -q`
Expected: PASS.

- [ ] **Step 5: Add the suite-wide network gate scrub**

Append to `api/tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _disable_connector_fetch(monkeypatch):
    """G71: no test may reach Pinterest or Reddit.

    Connector transports are injected in tests, but the default transport is
    additionally gated on this variable so a developer who has real credentials
    in ``~/.cicada/secrets.env`` — which `cicada_home()` resolves to by default
    — cannot have a shell export turn a test run into live API traffic.
    """
    monkeypatch.delenv("CICADA_ALLOW_CONNECTOR_FETCH", raising=False)
```

- [ ] **Step 6: Commit**

```bash
git add api/services/sync_state.py api/tests/conftest.py api/tests/test_source_channels.py
git commit -m "$(cat <<'EOF'
feat(sync-state): per-channel failure record + connector cursor state

G71 — record_error preserves the last success so a failing poll shows as
"last sync failed" rather than as "never connected"; record_sync clears it
again on recovery and can carry connector cursor state. conftest scrubs the
connector network gate for the whole suite.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

- [ ] **Step 7: Write the failing Pinterest tests**

Create `api/tests/test_connector_pinterest.py`:

```python
"""Hermetic tests for the Pinterest v5 connector (G71 §2).

ZERO NETWORK: every HTTP call goes through an injected `http_fn`, and the
default transport is gated on CICADA_ALLOW_CONNECTOR_FETCH (scrubbed by the
autouse conftest fixture). Every fixture is synthetic — no real board name,
no real pin, no real credential.
"""

from __future__ import annotations

import asyncio

import pytest

from api.services import media_ingestor, sync_state
from api.services.connections import secrets
from api.services.connectors import pinterest


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Credentials go to a throwaway $CICADA_HOME — never the real ~/.cicada."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    for name in (pinterest.APP_ID_ENV, pinterest.APP_SECRET_ENV, pinterest.TOKEN_ENV):
        monkeypatch.delenv(name, raising=False)


BOARDS = {"items": [
    {"id": "b1", "name": "Recipes"},
    {"id": "b2", "name": "Type inspo"},
], "bookmark": None}

PINS_B1 = {"items": [
    {"id": "p1", "link": "https://example.com/recipe-one", "title": "Recipe one",
     "description": "A soup", "created_at": "2026-01-02T10:00:00"},
    {"id": "p2", "link": "", "title": "Pin with no outbound link"},
], "bookmark": None}

PINS_B2 = {"items": [
    {"id": "p3", "link": "https://example.com/type-sample", "title": "Type sample"},
], "bookmark": None}


def _fake_http(recorder=None):
    async def http(method, url, *, headers=None, params=None, data=None, auth=None):
        if recorder is not None:
            recorder.append((method, url, dict(params or {})))
        if url.endswith("/boards"):
            return BOARDS
        if url.endswith("/boards/b1/pins"):
            return PINS_B1
        if url.endswith("/boards/b2/pins"):
            return PINS_B2
        if url.endswith("/oauth/token"):
            return {"access_token": "tok-abc", "refresh_token": "ref-abc"}
        raise AssertionError(f"unexpected request: {method} {url}")
    return http


# --- pure helpers ------------------------------------------------------------


def test_authorize_url_carries_scopes_state_and_the_backend_redirect():
    secrets.set_secret(pinterest.APP_ID_ENV, "client-id-placeholder")
    url = pinterest.authorize_url("state-xyz")
    assert url.startswith(pinterest.AUTH_URL)
    assert "client_id=client-id-placeholder" in url
    assert "response_type=code" in url
    assert "state=state-xyz" in url
    assert "boards%3Aread" in url and "pins%3Aread" in url
    assert "%2Fsources%2Fconnectors%2Fpinterest%2Fcallback" in url


def test_pins_to_items_uses_the_outbound_link_and_the_board_as_folder():
    items = pinterest.pins_to_items("Recipes", PINS_B1["items"])
    assert [i.url for i in items] == [
        "https://example.com/recipe-one",
        "https://www.pinterest.com/pin/p2/",
    ]
    assert {i.folder for i in items} == {"Recipes"}
    assert {i.origin for i in items} == {"pinterest"}
    assert items[0].title == "Recipe one"
    assert items[0].note == "A soup"


def test_pins_to_items_skips_junk_rows():
    assert pinterest.pins_to_items("Recipes", [None, {}, "nope"]) == []


# --- sync --------------------------------------------------------------------


def _memory(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="",
            site=media_ingestor._site_of(url), media_type="url")

    async def no_commit(memory_path, count):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    return memory


def test_sync_is_skipped_without_a_token(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    result = run(pinterest.sync(memory, http_fn=_fake_http()))
    assert result["status"] == "skipped"
    assert result["reason"] == "not connected"
    assert list((memory / "episodes").glob("*.md")) == []


def test_sync_ingests_every_board_and_records_the_sync(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")
    calls: list = []

    result = run(pinterest.sync(memory, http_fn=_fake_http(calls)))
    assert result["status"] == "ok"
    assert result["boards"] == 2
    assert result["seen"] == 3
    assert result["new"] == 3
    assert len(list((memory / "episodes").glob("*.md"))) == 3
    assert sync_state.read_sync_state(memory)["pinterest"]["count"] == 3
    assert all("Bearer" not in str(c) for c in calls), "no credential in the recorder"


def test_sync_is_idempotent_via_the_url_index(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")
    run(pinterest.sync(memory, http_fn=_fake_http()))
    second = run(pinterest.sync(memory, http_fn=_fake_http()))
    assert second["new"] == 0
    assert len(list((memory / "episodes").glob("*.md"))) == 3


def test_sync_records_a_failure_instead_of_raising(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")

    async def boom(method, url, **kwargs):
        raise RuntimeError("token expired")

    result = run(pinterest.sync(memory, http_fn=boom))
    assert result["status"] == "error"
    assert "token expired" in result["error"]
    entry = sync_state.read_sync_state(memory)["pinterest"]
    assert "token expired" in entry["last_error"]


def test_sync_refuses_the_default_transport_when_the_gate_is_closed(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")
    result = run(pinterest.sync(memory))  # no http_fn, gate scrubbed by conftest
    assert result["status"] == "skipped"
    assert result["reason"] == "network disabled"


def test_exchange_code_stores_only_the_token(tmp_path, monkeypatch):
    secrets.set_secret(pinterest.APP_ID_ENV, "client-id-placeholder")
    secrets.set_secret(pinterest.APP_SECRET_ENV, "client-secret-placeholder")
    run(pinterest.exchange_code("code-123", http_fn=_fake_http()))
    assert secrets.has_secret(pinterest.TOKEN_ENV)
    assert pinterest.is_connected() is True


def test_credential_fields_never_leak_a_value(tmp_path, monkeypatch):
    secrets.set_secret(pinterest.APP_SECRET_ENV, "client-secret-placeholder")
    fields = pinterest.credential_fields()
    names = {f["name"]: f for f in fields}
    assert names[pinterest.APP_SECRET_ENV]["present"] is True
    assert names[pinterest.APP_SECRET_ENV]["secret"] is True
    assert names[pinterest.APP_ID_ENV]["present"] is False
    for field in fields:
        assert "client-secret-placeholder" not in str(field)
```

- [ ] **Step 8: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_connector_pinterest.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.connectors'`.

- [ ] **Step 9: Create the connector package + transport base**

Create `api/services/connectors/__init__.py`:

```python
"""Direct saved-content API connectors (G71 §2).

Exactly two, because exactly two platforms expose a *personal saved index*
through a sanctioned API (G69's route matrix): Pinterest v5 and Reddit.
Everything else in Cicada's import story is an export-file parser living in
``media_ingestor`` — aggregators were evaluated and rejected (they cannot reach
these surfaces, and every hosted one proxies tokens through its own cloud).

House rules, identical for both adapters:

* credentials live ONLY in ``$CICADA_HOME/secrets.env`` (0600) via
  ``connections.secrets`` — never in a bank, never in git, never in a log line,
  an error string, or an HTTP response;
* every HTTP call goes through an injected ``http_fn``, so the test suite has
  zero network and the default transport is the only code path that does;
* the default transport is additionally gated on ``CICADA_ALLOW_CONNECTOR_FETCH=1``
  (mirroring ``CICADA_ALLOW_FEED_FETCH`` / ``CICADA_ALLOW_LOGO_FETCH``);
* ``sync()`` never raises: a failure is recorded through
  ``sync_state.record_error`` and surfaces per-channel on ``GET /sources/channels``;
* nothing new is invented downstream — a connector emits ``RawItem``s into
  ``media_ingestor.ingest_batch`` and the Sleep pipeline absorbs them unchanged.
"""
```

Create `api/services/connectors/base.py`:

```python
"""Injectable HTTP seam + network gate shared by both connectors."""

from __future__ import annotations

import inspect
import os
from typing import Any, Callable

# Called as ``http_fn(method, url, *, headers=None, params=None, data=None,
# auth=None) -> dict``. May be sync or async: tests inject plain functions, the
# real default is async.
HttpFn = Callable[..., Any]

GATE_ENV = "CICADA_ALLOW_CONNECTOR_FETCH"
TIMEOUT_SECONDS = 15.0


class ConnectorError(RuntimeError):
    """A sync could not complete — recorded, never raised past ``sync()``."""


def network_allowed(allow_fetch: bool | None = None) -> bool:
    """Whether the DEFAULT transport may run. An injected ``http_fn`` bypasses
    this entirely — the caller has supplied the mechanism, so there is nothing
    left to gate."""
    if allow_fetch is not None:
        return bool(allow_fetch)
    return os.environ.get(GATE_ENV) == "1"


async def default_http(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    data: dict | None = None,
    auth: tuple[str, str] | None = None,
) -> dict:
    """The gated live-HTTP transport. Only ever invoked when the gate is open."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.request(
            method, url, headers=headers, params=params, data=data,
            auth=auth, timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()


async def call_http(http_fn: HttpFn, method: str, url: str, **kwargs) -> dict:
    """Call ``http_fn`` and await it if it returned a coroutine."""
    result = http_fn(method, url, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result
```

- [ ] **Step 10: Implement the Pinterest adapter**

Create `api/services/connectors/pinterest.py`:

```python
"""Pinterest v5 — the one platform whose sanctioned API covers saved content.

A save on Pinterest IS a pin on a board, and ``boards:read``/``pins:read`` read
exactly that (G69). The user brings their own OAuth app (Trial tier reads real
user data); Cicada never ships a client secret and never proxies a token.

The redirect target is the local backend itself — it already listens on
127.0.0.1:8000 — so there is no second HTTP server to spawn and nothing binds a
new port. ``GET /sources/connectors/pinterest/callback`` (Task 8) is the only
auth-exempt route added, and it is nonce-gated.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from loguru import logger

from api.services import media_ingestor, sync_state
from api.services.connections import secrets
from api.services.connectors import base
from api.services.media_ingestor import RawItem

CHANNEL_ID = "pinterest"
LABEL = "Pinterest"

APP_ID_ENV = "PINTEREST_APP_ID"
APP_SECRET_ENV = "PINTEREST_APP_SECRET"
TOKEN_ENV = "PINTEREST_ACCESS_TOKEN"

# What the setup panel asks for, in order. `secret: True` renders a SecureField
# and — like every field here — the VALUE is never read back out to any caller.
FIELDS: tuple[dict, ...] = (
    {"name": APP_ID_ENV, "label": "App ID", "secret": False},
    {"name": APP_SECRET_ENV, "label": "App secret", "secret": True},
)

SCOPES = "boards:read,pins:read"
API_BASE = "https://api.pinterest.com/v5"
AUTH_URL = "https://www.pinterest.com/oauth/"
TOKEN_URL = f"{API_BASE}/oauth/token"
REDIRECT_PATH = "/sources/connectors/pinterest/callback"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"

PAGE_SIZE = 100
MAX_PAGES = 20  # 100 x 20 = 2 000 pins per board — well past MAX_BATCH


# --- credentials -------------------------------------------------------------


def is_connected() -> bool:
    """Connected == a usable access token is stored. App id/secret alone only
    means the user got as far as the consent screen."""
    return secrets.has_secret(TOKEN_ENV)


def credential_fields() -> list[dict]:
    """The setup panel's field list — presence only, NEVER a value."""
    return [{**f, "present": secrets.has_secret(f["name"])} for f in FIELDS]


def forget() -> None:
    """Remove every stored Pinterest credential."""
    for name in (APP_ID_ENV, APP_SECRET_ENV, TOKEN_ENV):
        secrets.remove_secret(name)


# --- OAuth -------------------------------------------------------------------


def redirect_uri(base_url: str = DEFAULT_BASE_URL) -> str:
    return base_url.rstrip("/") + REDIRECT_PATH


def authorize_url(state: str, *, base_url: str = DEFAULT_BASE_URL) -> str:
    """The consent URL the companion app opens in the user's own browser."""
    query = urlencode({
        "client_id": (secrets.load_secrets().get(APP_ID_ENV) or "").strip(),
        "redirect_uri": redirect_uri(base_url),
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    })
    return f"{AUTH_URL}?{query}"


async def exchange_code(
    code: str, *, http_fn: base.HttpFn | None = None, base_url: str = DEFAULT_BASE_URL
) -> None:
    """Trade the authorization code for an access token and store it (0600).

    Raises ``ConnectorError`` on a response with no token — the callback route
    turns that into a plain "couldn't complete sign-in" page, never echoing the
    response body (it can contain the app secret's error context).
    """
    values = secrets.load_secrets()
    client_id = (values.get(APP_ID_ENV) or "").strip()
    client_secret = (values.get(APP_SECRET_ENV) or "").strip()
    if not client_id or not client_secret:
        raise base.ConnectorError("Pinterest app id and secret must be saved first")

    fn = http_fn or base.default_http
    payload = await base.call_http(
        fn, "POST", TOKEN_URL,
        auth=(client_id, client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(base_url),
        },
    )
    token = (payload or {}).get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise base.ConnectorError("Pinterest returned no access token")
    secrets.set_secret(TOKEN_ENV, token.strip())


# --- reads -------------------------------------------------------------------


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {(secrets.load_secrets().get(TOKEN_ENV) or '').strip()}"}


async def _paged(url: str, http_fn: base.HttpFn) -> list[dict]:
    """Walk Pinterest's ``bookmark`` cursor, bounded by ``MAX_PAGES``."""
    out: list[dict] = []
    bookmark: str | None = None
    for _ in range(MAX_PAGES):
        params: dict = {"page_size": PAGE_SIZE}
        if bookmark:
            params["bookmark"] = bookmark
        payload = await base.call_http(
            http_fn, "GET", url, headers=_auth_headers(), params=params
        )
        items = (payload or {}).get("items")
        if isinstance(items, list):
            out.extend(i for i in items if isinstance(i, dict))
        bookmark = (payload or {}).get("bookmark") or None
        if not bookmark:
            break
    return out


async def fetch_boards(*, http_fn: base.HttpFn | None = None) -> list[dict]:
    return await _paged(f"{API_BASE}/boards", http_fn or base.default_http)


async def fetch_pins(board_id: str, *, http_fn: base.HttpFn | None = None) -> list[dict]:
    return await _paged(f"{API_BASE}/boards/{board_id}/pins", http_fn or base.default_http)


def pins_to_items(board_name: str, pins: list) -> list[RawItem]:
    """One ``RawItem`` per pin.

    The pin's outbound ``link`` is what the user actually saved; a pin without
    one (an uploaded image) falls back to its own Pinterest permalink so it is
    still addressable and still dedups. ``folder`` is the board name — G69 names
    board/collection names the strongest unused signal in the whole corpus.
    """
    items: list[RawItem] = []
    for pin in pins or []:
        if not isinstance(pin, dict):
            continue
        url = str(pin.get("link") or "").strip()
        pin_id = str(pin.get("id") or "").strip()
        if not url and pin_id:
            url = f"https://www.pinterest.com/pin/{pin_id}/"
        if not url:
            continue
        items.append(RawItem(
            url=url,
            title=(str(pin.get("title") or "").strip() or None),
            note=(str(pin.get("description") or "").strip() or None),
            added=(str(pin.get("created_at") or "").strip() or None),
            folder=board_name or "Pinterest",
            origin="pinterest",
        ))
    return items


# --- sync --------------------------------------------------------------------


async def sync(
    memory_path: Path,
    *,
    http_fn: base.HttpFn | None = None,
    allow_fetch: bool | None = None,
) -> dict:
    """Pull every board's pins and ingest the new ones. NEVER raises.

    Returns ``{"status": "ok"|"skipped"|"error", "new", "seen", "boards",
    "error", "reason"}``. Idempotent: ``ingest_batch`` dedups on
    ``url_index.json``, so re-running costs nothing but the reads.
    """
    empty = {"new": 0, "seen": 0, "boards": 0, "error": None}
    if not is_connected():
        return {"status": "skipped", "reason": "not connected", **empty}
    if http_fn is None and not base.network_allowed(allow_fetch):
        return {"status": "skipped", "reason": "network disabled", **empty}

    fn = http_fn or base.default_http
    try:
        boards = await fetch_boards(http_fn=fn)
        items: list[RawItem] = []
        for board in boards:
            board_id = str(board.get("id") or "").strip()
            if not board_id:
                continue
            pins = await fetch_pins(board_id, http_fn=fn)
            items.extend(pins_to_items(str(board.get("name") or "Pinterest"), pins))
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        logger.warning(f"Pinterest sync failed: {message}")
        sync_state.record_error(memory_path, CHANNEL_ID, message)
        return {"status": "error", "reason": None, **empty, "error": message}

    created, _ = await media_ingestor.ingest_batch(
        items[: media_ingestor.MAX_BATCH], memory_path, from_bookmark_file=False
    )
    sync_state.record_sync(memory_path, CHANNEL_ID, count=len(items))
    return {"status": "ok", "reason": None, "new": created, "seen": len(items),
            "boards": len(boards), "error": None}
```

- [ ] **Step 11: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_connector_pinterest.py -q`
Expected: PASS.

- [ ] **Step 12: Run the full suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add api/services/connectors api/tests/test_connector_pinterest.py
git commit -m "$(cat <<'EOF'
feat(connectors): Pinterest v5 boards + pins, BYO OAuth app

G71 §2 / G69 — the one platform whose sanctioned API covers a personal saved
index. Credentials only in ~/.cicada/secrets.env (0600) and never read back
out; every request through an injected transport, the default one gated on
CICADA_ALLOW_CONNECTOR_FETCH; sync() records failures instead of raising and
is idempotent via url_index. Board name becomes the item folder.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 7: Reddit connector (script app → `/user/{me}/saved`)

**Files:**
- Create: `api/services/connectors/reddit.py`
- Test: `api/tests/test_connector_reddit.py` (new)

**Interfaces:**
- Consumes: `connectors.base` (Task 6), `sync_state.record_sync(..., extra=)` / `record_error` (Task 6), `media_ingestor.ingest_batch`, `connections.secrets`.
- Produces:
  - `reddit.CHANNEL_ID = "reddit"`, `LABEL = "Reddit"`, `FIELDS: tuple[dict, ...]`, `CLIENT_ID_ENV`, `CLIENT_SECRET_ENV`, `USERNAME_ENV`, `PASSWORD_ENV`
  - `reddit.is_connected() -> bool`, `reddit.credential_fields() -> list[dict]`, `reddit.forget() -> None`
  - `async reddit.fetch_token(*, http_fn=None) -> str`
  - `async reddit.fetch_saved(token, username, *, http_fn=None, stop_at=None) -> tuple[list[dict], str | None]` — returns `(children, newest_fullname)`
  - `reddit.children_to_items(children: list) -> list[RawItem]`
  - `async reddit.sync(memory_path, *, http_fn=None, allow_fetch=None) -> dict` → `{"status", "new", "seen", "pages", "error", "reason"}`

- [ ] **Step 1: Write the failing Reddit tests**

Create `api/tests/test_connector_reddit.py`:

```python
"""Hermetic tests for the Reddit saved connector (G71 §2).

ZERO NETWORK: injected `http_fn` throughout, default transport gated. Every
subreddit, title and credential below is invented.
"""

from __future__ import annotations

import asyncio

import pytest

from api.services import media_ingestor, sync_state
from api.services.connections import secrets
from api.services.connectors import reddit


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    for name in (reddit.CLIENT_ID_ENV, reddit.CLIENT_SECRET_ENV,
                 reddit.USERNAME_ENV, reddit.PASSWORD_ENV):
        monkeypatch.delenv(name, raising=False)


def _credentials():
    secrets.set_secret(reddit.CLIENT_ID_ENV, "client-id-placeholder")
    secrets.set_secret(reddit.CLIENT_SECRET_ENV, "client-secret-placeholder")
    secrets.set_secret(reddit.USERNAME_ENV, "example_user")
    secrets.set_secret(reddit.PASSWORD_ENV, "password-placeholder")


def _child(name, *, title, url=None, permalink=None, subreddit="example", is_self=False):
    return {"kind": "t3", "data": {
        "name": name, "title": title, "subreddit": subreddit, "is_self": is_self,
        "url": url or "", "permalink": permalink or f"/r/{subreddit}/comments/{name[3:]}/x/",
    }}


PAGE_1 = {"kind": "Listing", "data": {"after": "t3_002", "children": [
    _child("t3_001", title="An external article", url="https://example.com/article"),
    _child("t3_002", title="A self post", is_self=True),
]}}

PAGE_2 = {"kind": "Listing", "data": {"after": None, "children": [
    _child("t3_003", title="Another article", url="https://example.com/other"),
]}}


def _fake_http(pages=(PAGE_1, PAGE_2), recorder=None):
    seen = {"n": 0}

    async def http(method, url, *, headers=None, params=None, data=None, auth=None):
        if recorder is not None:
            recorder.append((method, url, dict(params or {})))
        if url.endswith("/api/v1/access_token"):
            return {"access_token": "tok-abc", "token_type": "bearer"}
        page = pages[min(seen["n"], len(pages) - 1)]
        seen["n"] += 1
        return page

    return http


def _memory(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="",
            site=media_ingestor._site_of(url), media_type="url")

    async def no_commit(memory_path, count):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    return memory


# --- pure helpers ------------------------------------------------------------


def test_children_to_items_prefers_the_outbound_url_and_falls_back_to_the_permalink():
    items = reddit.children_to_items(PAGE_1["data"]["children"])
    assert [i.url for i in items] == [
        "https://example.com/article",
        "https://www.reddit.com/r/example/comments/002/x/",
    ]
    assert [i.title for i in items] == ["An external article", "A self post"]
    assert {i.folder for i in items} == {"r/example"}
    assert {i.origin for i in items} == {"reddit-saved"}


def test_children_to_items_skips_junk():
    assert reddit.children_to_items([None, {}, {"data": "nope"}]) == []


# --- pagination --------------------------------------------------------------


def test_fetch_saved_pages_until_after_runs_out():
    children, newest = run(reddit.fetch_saved("tok", "example_user", http_fn=_fake_http()))
    assert [c["data"]["name"] for c in children] == ["t3_001", "t3_002", "t3_003"]
    assert newest == "t3_001", "the newest fullname is the cursor for the next run"


def test_fetch_saved_stops_at_the_previously_seen_id():
    children, newest = run(reddit.fetch_saved(
        "tok", "example_user", http_fn=_fake_http(), stop_at="t3_002"))
    assert [c["data"]["name"] for c in children] == ["t3_001"]
    assert newest == "t3_001"


def test_fetch_saved_sends_a_user_agent_and_never_the_password():
    calls: list = []
    run(reddit.fetch_saved("tok", "example_user", http_fn=_fake_http(recorder=calls)))
    assert calls, "at least one listing request"
    assert all("password-placeholder" not in str(c) for c in calls)


# --- sync --------------------------------------------------------------------


def test_sync_is_skipped_without_credentials(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    result = run(reddit.sync(memory, http_fn=_fake_http()))
    assert result["status"] == "skipped"
    assert result["reason"] == "not connected"


def test_sync_ingests_and_stores_the_cursor(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    _credentials()
    result = run(reddit.sync(memory, http_fn=_fake_http()))
    assert result["status"] == "ok"
    assert result["seen"] == 3
    assert result["new"] == 3
    entry = sync_state.read_sync_state(memory)["reddit"]
    assert entry["count"] == 3
    assert entry["last_seen"] == "t3_001"


def test_sync_second_run_stops_at_the_cursor(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    _credentials()
    run(reddit.sync(memory, http_fn=_fake_http()))
    second = run(reddit.sync(memory, http_fn=_fake_http()))
    assert second["seen"] == 0
    assert second["new"] == 0


def test_sync_records_a_failure_instead_of_raising(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    _credentials()

    async def boom(method, url, **kwargs):
        raise RuntimeError("429 rate limited")

    result = run(reddit.sync(memory, http_fn=boom))
    assert result["status"] == "error"
    assert "429" in result["error"]
    assert "429" in sync_state.read_sync_state(memory)["reddit"]["last_error"]


def test_sync_refuses_the_default_transport_when_the_gate_is_closed(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    _credentials()
    result = run(reddit.sync(memory))
    assert result["status"] == "skipped"
    assert result["reason"] == "network disabled"


def test_credential_fields_never_leak_a_value(tmp_path, monkeypatch):
    _credentials()
    fields = reddit.credential_fields()
    assert all(f["present"] for f in fields)
    assert all("password-placeholder" not in str(f) for f in fields)
    assert {f["name"] for f in fields if f["secret"]} == {
        reddit.CLIENT_SECRET_ENV, reddit.PASSWORD_ENV}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_connector_reddit.py -q`
Expected: FAIL with `ImportError: cannot import name 'reddit' from 'api.services.connectors'`.

- [ ] **Step 3: Implement the Reddit adapter**

Create `api/services/connectors/reddit.py`:

```python
"""Reddit saved items — the second sanctioned direct API (G69).

``GET /user/{name}/saved`` with the ``history`` scope is official, free for
non-commercial personal use, and pollable at any cadence (100 QPM; nightly is
far under). Its one documented limit is the ~1,000-item listing cap, which the
one-shot GDPR export parser (``media_ingestor.parse_reddit_saved_csv``) exists
to backfill past — the two paths dedup against each other because both end up
as absolute ``reddit.com`` permalinks through ``url_hash``.

A *script* app is used deliberately: it is the only Reddit app type a single
user can create for their own account without a redirect URI, so there is no
OAuth round trip and no callback route for this connector.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from api.services import media_ingestor, sync_state
from api.services.connections import secrets
from api.services.connectors import base
from api.services.media_ingestor import RawItem

CHANNEL_ID = "reddit"
LABEL = "Reddit"

CLIENT_ID_ENV = "REDDIT_CLIENT_ID"
CLIENT_SECRET_ENV = "REDDIT_CLIENT_SECRET"
USERNAME_ENV = "REDDIT_USERNAME"
PASSWORD_ENV = "REDDIT_PASSWORD"

FIELDS: tuple[dict, ...] = (
    {"name": CLIENT_ID_ENV, "label": "Client ID", "secret": False},
    {"name": CLIENT_SECRET_ENV, "label": "Client secret", "secret": True},
    {"name": USERNAME_ENV, "label": "Reddit username", "secret": False},
    {"name": PASSWORD_ENV, "label": "Reddit password", "secret": True},
)

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
BASE_URL = "https://www.reddit.com"
# Reddit requires a descriptive, non-browser User-Agent and rate-limits
# anonymous-looking clients hard.
USER_AGENT = "macos:cicada:0.1 (personal memory system)"

PAGE_SIZE = 100
MAX_PAGES = 10  # 100 x 10 = the documented ~1,000-item listing cap
SEEN_KEY = "last_seen"


# --- credentials -------------------------------------------------------------


def is_connected() -> bool:
    return all(secrets.has_secret(f["name"]) for f in FIELDS)


def credential_fields() -> list[dict]:
    """The setup panel's field list — presence only, NEVER a value."""
    return [{**f, "present": secrets.has_secret(f["name"])} for f in FIELDS]


def forget() -> None:
    for field in FIELDS:
        secrets.remove_secret(field["name"])


# --- reads -------------------------------------------------------------------


async def fetch_token(*, http_fn: base.HttpFn | None = None) -> str:
    """Password grant against the user's own script app.

    Raises ``ConnectorError`` with no response body attached — a token error
    can echo back credential context and must never reach a log or the app.
    """
    values = secrets.load_secrets()
    payload = await base.call_http(
        http_fn or base.default_http, "POST", TOKEN_URL,
        headers={"User-Agent": USER_AGENT},
        auth=((values.get(CLIENT_ID_ENV) or "").strip(),
              (values.get(CLIENT_SECRET_ENV) or "").strip()),
        data={
            "grant_type": "password",
            "username": (values.get(USERNAME_ENV) or "").strip(),
            "password": (values.get(PASSWORD_ENV) or "").strip(),
        },
    )
    token = (payload or {}).get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise base.ConnectorError("Reddit returned no access token")
    return token.strip()


async def fetch_saved(
    token: str,
    username: str,
    *,
    http_fn: base.HttpFn | None = None,
    stop_at: str | None = None,
) -> tuple[list[dict], str | None]:
    """Newest-first pages of saved things, stopping at ``stop_at``.

    Returns ``(children, newest_fullname)``. ``newest_fullname`` is the first
    item of the FIRST page — the cursor to pass as ``stop_at`` next run, which
    is what keeps a nightly poll O(new items) instead of O(everything).
    """
    fn = http_fn or base.default_http
    url = f"{API_BASE}/user/{username}/saved"
    children: list[dict] = []
    newest: str | None = None
    after: str | None = None

    for _ in range(MAX_PAGES):
        params: dict = {"limit": PAGE_SIZE, "raw_json": 1}
        if after:
            params["after"] = after
        payload = await base.call_http(
            fn, "GET", url, headers={"User-Agent": USER_AGENT,
                                     "Authorization": f"Bearer {token}"},
            params=params,
        )
        data = (payload or {}).get("data") or {}
        page = [c for c in (data.get("children") or []) if isinstance(c, dict)]
        if newest is None and page:
            newest = str((page[0].get("data") or {}).get("name") or "") or None

        hit_cursor = False
        for child in page:
            name = str((child.get("data") or {}).get("name") or "")
            if stop_at and name == stop_at:
                hit_cursor = True
                break
            children.append(child)
        if hit_cursor:
            break

        after = data.get("after") or None
        if not after:
            break

    return children, newest


def children_to_items(children: list) -> list[RawItem]:
    """One ``RawItem`` per saved thing.

    A link post keeps its outbound ``url``; a self post or a saved comment uses
    the reddit permalink. Titles come straight off the listing, so an offline
    install still gets a real title with no hydration call (G69's ``/api/info``
    suggestion is unnecessary here). ``folder`` is the subreddit — the same
    user-authored topic label the board/collection paths use.
    """
    items: list[RawItem] = []
    for child in children or []:
        data = child.get("data") if isinstance(child, dict) else None
        if not isinstance(data, dict):
            continue
        url = str(data.get("url") or "").strip()
        if data.get("is_self") or url.startswith("/"):
            url = ""
        if not url:
            permalink = str(data.get("permalink") or "").strip()
            url = (BASE_URL + permalink) if permalink.startswith("/") else permalink
        if not url.startswith(("http://", "https://")):
            continue
        subreddit = str(data.get("subreddit") or "").strip()
        items.append(RawItem(
            url=url,
            title=(str(data.get("title") or data.get("link_title") or "").strip() or None),
            folder=f"r/{subreddit}" if subreddit else "Reddit saved",
            origin="reddit-saved",
        ))
    return items


# --- sync --------------------------------------------------------------------


async def sync(
    memory_path: Path,
    *,
    http_fn: base.HttpFn | None = None,
    allow_fetch: bool | None = None,
) -> dict:
    """Pull saved items newer than the stored cursor and ingest them. NEVER raises."""
    empty = {"new": 0, "seen": 0, "pages": 0, "error": None}
    if not is_connected():
        return {"status": "skipped", "reason": "not connected", **empty}
    if http_fn is None and not base.network_allowed(allow_fetch):
        return {"status": "skipped", "reason": "network disabled", **empty}

    username = (secrets.load_secrets().get(USERNAME_ENV) or "").strip()
    stop_at = (sync_state.read_sync_state(memory_path).get(CHANNEL_ID) or {}).get(SEEN_KEY)

    try:
        token = await fetch_token(http_fn=http_fn)
        children, newest = await fetch_saved(
            token, username, http_fn=http_fn, stop_at=stop_at
        )
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        logger.warning(f"Reddit sync failed: {message}")
        sync_state.record_error(memory_path, CHANNEL_ID, message)
        return {"status": "error", "reason": None, **empty, "error": message}

    items = children_to_items(children)
    created, _ = await media_ingestor.ingest_batch(
        items[: media_ingestor.MAX_BATCH], memory_path, from_bookmark_file=False
    )
    sync_state.record_sync(
        memory_path, CHANNEL_ID, count=len(items),
        extra={SEEN_KEY: newest} if newest else None,
    )
    return {"status": "ok", "reason": None, "new": created, "seen": len(items),
            "pages": 0, "error": None}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_connector_reddit.py -q`
Expected: PASS.

> Note on `test_sync_second_run_stops_at_the_cursor`: the fake serves `PAGE_1`
> first on every call, whose first child is `t3_001` — the stored cursor — so
> the second run stops immediately with zero children. That is exactly the
> nightly-poll behaviour being pinned.

- [ ] **Step 5: Run the full suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/services/connectors/reddit.py api/tests/test_connector_reddit.py
git commit -m "$(cat <<'EOF'
feat(connectors): Reddit /user/{me}/saved via a script app

G71 §2 / G69 — newest-first pagination that stops at the previously seen
fullname, so a nightly poll costs O(new). Titles come off the listing (no
/api/info hydration needed); the subreddit becomes the item folder. The
~1,000-item cap is documented in the module and backfilled by the GDPR
export parser. Credentials never leave secrets.env and never enter a log.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 8: Connector HTTP surface, channel rows, and the Sleep-tail poll

**Files:**
- Create: `api/routers/connectors.py`
- Modify: `api/models/schemas.py` (connector models; `SourceChannel.last_error`)
- Modify: `api/main.py:168` (mount), `api/services/auth.py:28` (open path)
- Modify: `api/services/channel_registry.py` (two new rows + failure surfacing)
- Modify: `api/routers/sources.py` (connector state in `/sources/channels` + its ETag)
- Modify: `api/services/sleep_cycle.py` (`_poll_connectors_safely`)
- Test: `api/tests/test_connectors_api.py` (new), `api/tests/test_sleep_connector_poll.py` (new), `api/tests/test_source_channels.py`

**Interfaces:**
- Consumes: `connectors.pinterest` / `connectors.reddit` (Tasks 6–7), `sync_state.record_error` (Task 6).
- Produces:
  - Schemas `ConnectorField`, `ConnectorStatus`, `ConnectorsResponse`, `ConnectorSyncResult`, `ConnectorAuthorizeResponse`; `SourceChannel.last_error: Optional[str] = None`
  - Routes `GET /sources/connectors`, `PUT /sources/connectors/{id}/credentials`, `DELETE /sources/connectors/{id}/credentials`, `POST /sources/connectors/{id}/authorize`, `GET /sources/connectors/pinterest/callback`, `POST /sources/connectors/{id}/sync`
  - `channel_registry.build_channels(memory_path, *, telegram_enabled: bool, connectors_connected: dict[str, bool] | None = None)`
  - `sleep_cycle._poll_connectors_safely(memory_path: Path) -> None`

- [ ] **Step 1: Write the failing channel-row tests**

Append to `api/tests/test_source_channels.py`:

```python
# --- G71: the two direct connectors as capture channels ----------------------


def _channels_with(memory_path, **kwargs):
    from api.services import channel_registry

    bank_index.invalidate()
    return {c["id"]: c for c in channel_registry.build_channels(
        memory_path, telegram_enabled=False, **kwargs)}


def test_connector_channels_are_disconnected_without_credentials(tmp_path):
    channels = _channels_with(tmp_path)
    assert channels["pinterest"]["connected"] is False
    assert channels["pinterest"]["actions"] == ["connect"]
    assert channels["pinterest"]["detail"] is None
    assert channels["reddit"]["label"] == "Reddit"


def test_connector_channel_reports_connected_but_never_synced(tmp_path):
    ch = _channels_with(tmp_path, connectors_connected={"pinterest": True})["pinterest"]
    assert ch["connected"] is True
    assert ch["detail"] == "Connected · not synced yet"
    assert ch["actions"] == ["sync", "disconnect"]


def test_connector_channel_reports_a_successful_sync(tmp_path):
    sync_state.record_sync(tmp_path, "reddit", count=42, at="2026-08-30T10:00:00Z")
    ch = _channels_with(tmp_path, connectors_connected={"reddit": True})["reddit"]
    assert ch["count"] == 42
    assert "42 saved items" in ch["detail"]
    assert "2026-08-30" in ch["detail"]
    assert ch["last_error"] is None


def test_connector_channel_surfaces_the_last_failure(tmp_path):
    sync_state.record_sync(tmp_path, "reddit", count=42, at="2026-08-30T10:00:00Z")
    sync_state.record_error(tmp_path, "reddit", "RuntimeError: 429 rate limited")
    ch = _channels_with(tmp_path, connectors_connected={"reddit": True})["reddit"]
    assert ch["last_error"] == "RuntimeError: 429 rate limited"
    assert ch["detail"].startswith("Last sync failed")


def test_channel_ids_now_include_the_connectors(client):
    c, _ = client
    ids = [ch["id"] for ch in c.get("/sources/channels").json()["channels"]]
    assert ids == [
        "chat-export:claude", "chat-export:chatgpt", "bookmarks", "notes",
        "rss", "calendar", "pinterest", "reddit", "telegram", "files",
    ]


def test_channels_etag_covers_connector_connectedness(client, monkeypatch):
    """Saving a credential flips a channel to connected without touching any
    file the ETag already hashes, so it must ride the ETag explicitly."""
    from api.services.connectors import pinterest

    c, _ = client
    etag = c.get("/sources/channels").headers["etag"]
    assert c.get("/sources/channels", headers={"If-None-Match": etag}).status_code == 304

    monkeypatch.setattr(pinterest, "is_connected", lambda: True)
    resp = c.get("/sources/channels", headers={"If-None-Match": etag})
    assert resp.status_code == 200, "connecting Pinterest must break the ETag"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_channels.py -q -k connector`
Expected: FAIL with `KeyError: 'pinterest'`.

- [ ] **Step 3: Add the channel rows**

In `api/services/channel_registry.py`, extend `CHANNEL_IDS`:

```python
CHANNEL_IDS = (
    "chat-export:claude",
    "chat-export:chatgpt",
    "bookmarks",
    "notes",
    "rss",
    "calendar",
    "pinterest",
    "reddit",
    "telegram",
    "files",
)
```

Add a builder next to `_sync_channel`:

```python
def _connector_channel(
    channel_id: str, label: str, state: dict, noun: str, *, connected: bool
) -> dict:
    """A direct-API connector row (G71 §2).

    ``connected`` is credential presence, passed in by the router — it lives in
    ``$CICADA_HOME/secrets.env``, outside the bank, so this module stays pure
    filesystem-over-the-bank. A recorded failure wins the detail line: a channel
    whose last poll 401'd must not keep advertising a week-old success.
    """
    entry = state.get(channel_id) or {}
    last = entry.get("last_sync") or None
    count = int(entry.get("count") or 0)
    error = entry.get("last_error") or None

    if error:
        detail = f"Last sync failed · {error}"
    elif connected and last:
        detail = f"{_plural(count, noun)} · synced {_short_date(last)}"
    elif connected:
        detail = "Connected · not synced yet"
    else:
        detail = None

    return {
        "id": channel_id,
        "label": label,
        "connected": connected,
        "count": count,
        "last_sync": last,
        "last_error": error,
        "detail": detail,
        "actions": ["sync", "disconnect"] if connected else ["connect"],
    }
```

Change `build_channels`'s signature and add the two entries:

```python
def build_channels(
    memory_path: Path,
    *,
    telegram_enabled: bool,
    connectors_connected: dict[str, bool] | None = None,
) -> list[dict]:
```

```python
    connected_map = connectors_connected or {}
```

```python
        "pinterest": _connector_channel(
            "pinterest", "Pinterest", state, "pin",
            connected=bool(connected_map.get("pinterest"))),
        "reddit": _connector_channel(
            "reddit", "Reddit", state, "saved item",
            connected=bool(connected_map.get("reddit"))),
```

- [ ] **Step 4: Add `last_error` to the wire schema and wire the router**

In `api/models/schemas.py`, add to `SourceChannel` after `detail`:

```python
    # G71 — the last poll's failure, when there was one. Present so the Capture
    # page can say "last sync failed · <reason>" instead of silently showing a
    # stale success. Never carries a credential: connectors build this string
    # from an exception type + message only.
    last_error: Optional[str] = None
```

In `api/routers/sources.py`, import the connectors and thread their state:

```python
from api.services.connectors import pinterest, reddit
```

and inside `list_source_channels`, replace the etag + call:

```python
    connectors_connected = {
        "pinterest": pinterest.is_connected(),
        "reddit": reddit.is_connected(),
    }
    # `telegram_enabled` and connector credentials are config/secrets facts, not
    # filesystem-in-the-bank ones: connecting an account flips a channel to
    # "connected" without touching any component below, so without them in the
    # ETag a warm client 304s and keeps showing "not connected" forever.
    connector_tag = ",".join(f"{k}:{v}" for k, v in sorted(connectors_connected.items()))
    etag = sync_service.etag_for(
        memory_path, "sources", "episodes", "entities",
        extra=f"telegram:{settings.telegram_enabled}|connectors:{connector_tag}",
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    channels = await run_in_threadpool(
        channel_registry.build_channels,
        memory_path,
        telegram_enabled=settings.telegram_enabled,
        connectors_connected=connectors_connected,
    )
```

- [ ] **Step 5: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_channels.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/services/channel_registry.py api/models/schemas.py api/routers/sources.py api/tests/test_source_channels.py
git commit -m "$(cat <<'EOF'
feat(channels): pinterest + reddit rows with per-channel failure surfacing

G71 §2 — connected state comes from credential presence (passed in by the
router so channel_registry stays a pure read over the bank) and rides the
/sources/channels ETag, and a recorded last_error beats a stale success in
the detail line.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

- [ ] **Step 7: Write the failing connector-API tests**

Create `api/tests/test_connectors_api.py`:

```python
"""Hermetic tests for /sources/connectors (G71 §2).

No network: the OAuth exchange is monkeypatched. No real credential: every
value below is a placeholder, and the suite asserts that no value is ever
readable back through the API.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import connectors as connectors_router
from api.services.connections import secrets
from api.services.connectors import pinterest, reddit


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    for name in (pinterest.APP_ID_ENV, pinterest.APP_SECRET_ENV, pinterest.TOKEN_ENV,
                 reddit.CLIENT_ID_ENV, reddit.CLIENT_SECRET_ENV,
                 reddit.USERNAME_ENV, reddit.PASSWORD_ENV):
        monkeypatch.delenv(name, raising=False)
    connectors_router._pending_states.clear()
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    connectors_router._pending_states.clear()
    config.get_settings.cache_clear()


def test_list_connectors_reports_fields_without_values(client):
    c, _ = client
    body = c.get("/sources/connectors").json()
    ids = [x["id"] for x in body["connectors"]]
    assert ids == ["pinterest", "reddit"]
    pin = body["connectors"][0]
    assert pin["connected"] is False
    assert [f["name"] for f in pin["fields"]] == [pinterest.APP_ID_ENV, pinterest.APP_SECRET_ENV]
    assert all("value" not in f for f in pin["fields"])


def test_saving_credentials_marks_fields_present_but_never_echoes_them(client):
    c, _ = client
    resp = c.put(
        f"/sources/connectors/reddit/credentials",
        json={"fields": {
            reddit.CLIENT_ID_ENV: "client-id-placeholder",
            reddit.CLIENT_SECRET_ENV: "client-secret-placeholder",
            reddit.USERNAME_ENV: "example_user",
            reddit.PASSWORD_ENV: "password-placeholder",
        }},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected"] is True
    assert all(f["present"] for f in body["fields"])
    assert "password-placeholder" not in resp.text


def test_credentials_land_in_secrets_env_with_0600(client):
    c, _ = client
    c.put(f"/sources/connectors/pinterest/credentials",
          json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder"}})
    path = secrets.secrets_path()
    assert path.exists()
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_unknown_field_names_are_rejected(client):
    c, _ = client
    resp = c.put("/sources/connectors/pinterest/credentials",
                 json={"fields": {"OPENAI_API_KEY": "nope"}})
    assert resp.status_code == 422
    assert not secrets.has_secret("OPENAI_API_KEY")


def test_unknown_connector_is_404(client):
    c, _ = client
    assert c.get("/sources/connectors/spotify").status_code == 404
    assert c.post("/sources/connectors/spotify/sync").status_code == 404


def test_authorize_returns_a_url_and_arms_a_single_use_state(client):
    c, _ = client
    c.put("/sources/connectors/pinterest/credentials",
          json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder",
                           pinterest.APP_SECRET_ENV: "client-secret-placeholder"}})
    body = c.post("/sources/connectors/pinterest/authorize").json()
    assert body["authorizeUrl"].startswith(pinterest.AUTH_URL)
    assert len(connectors_router._pending_states) == 1


def test_callback_rejects_an_unknown_state_without_exchanging(client, monkeypatch):
    c, _ = client
    called = []

    async def fake_exchange(code, **kwargs):
        called.append(code)

    monkeypatch.setattr(pinterest, "exchange_code", fake_exchange)
    resp = c.get("/sources/connectors/pinterest/callback?code=abc&state=forged")
    assert resp.status_code == 400
    assert called == []


def test_callback_exchanges_once_and_burns_the_state(client, monkeypatch):
    c, _ = client
    c.put("/sources/connectors/pinterest/credentials",
          json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder",
                           pinterest.APP_SECRET_ENV: "client-secret-placeholder"}})
    state = c.post("/sources/connectors/pinterest/authorize").json()["state"]

    called = []

    async def fake_exchange(code, **kwargs):
        called.append(code)
        secrets.set_secret(pinterest.TOKEN_ENV, "tok-abc")

    monkeypatch.setattr(pinterest, "exchange_code", fake_exchange)
    first = c.get(f"/sources/connectors/pinterest/callback?code=abc&state={state}")
    assert first.status_code == 200
    assert "close this tab" in first.text.lower()
    assert called == ["abc"]

    replay = c.get(f"/sources/connectors/pinterest/callback?code=abc&state={state}")
    assert replay.status_code == 400, "a state is single-use"
    assert called == ["abc"]


def test_callback_is_reachable_without_a_bearer_token():
    """The browser cannot send the API token, so this one route is open —
    which is exactly why it is nonce-gated."""
    from api.services import auth

    assert "/sources/connectors/pinterest/callback" in auth._OPEN_PATHS


def test_sync_now_runs_the_adapter_and_reports_counts(client, monkeypatch):
    c, _ = client

    async def fake_sync(memory_path, **kwargs):
        return {"status": "ok", "reason": None, "new": 3, "seen": 5,
                "boards": 2, "error": None}

    monkeypatch.setattr(pinterest, "sync", fake_sync)
    body = c.post("/sources/connectors/pinterest/sync").json()
    assert body["status"] == "ok"
    assert body["new"] == 3
    assert body["seen"] == 5


def test_disconnect_removes_every_credential(client):
    c, _ = client
    c.put("/sources/connectors/pinterest/credentials",
          json={"fields": {pinterest.APP_ID_ENV: "client-id-placeholder"}})
    body = c.delete("/sources/connectors/pinterest/credentials").json()
    assert body["connected"] is False
    assert all(f["present"] is False for f in body["fields"])
```

- [ ] **Step 8: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_connectors_api.py -q`
Expected: FAIL with `ImportError: cannot import name 'connectors' from 'api.routers'`.

- [ ] **Step 9: Add the connector schemas**

In `api/models/schemas.py`, after `SourceChannelsResponse` (line 1132), add:

```python
# --- Saved-content connectors (G71 §2) ---


class ConnectorField(CamelModel):
    """One credential the connector needs. ``present`` says whether it is
    stored; the VALUE is never returned by any endpoint, ever."""

    name: str
    label: str
    secret: bool = False
    present: bool = False


class ConnectorStatus(CamelModel):
    id: str
    label: str
    connected: bool = False
    fields: list[ConnectorField] = []
    last_sync: Optional[str] = None
    last_error: Optional[str] = None
    detail: Optional[str] = None
    # "oauth" (Pinterest: save app id/secret, then authorize in a browser) or
    # "credentials" (Reddit: a script app needs no redirect round trip).
    login_mode: str = "credentials"


class ConnectorsResponse(CamelModel):
    connectors: list[ConnectorStatus] = []


class ConnectorAuthorizeResponse(CamelModel):
    authorize_url: str
    state: str


class ConnectorSyncResult(CamelModel):
    status: str            # ok | skipped | error
    reason: Optional[str] = None
    new: int = 0
    seen: int = 0
    error: Optional[str] = None
```

- [ ] **Step 10: Write the router**

Create `api/routers/connectors.py`:

```python
"""Saved-content connectors (G71 §2): status, credentials, OAuth, sync-now.

Deliberately NOT part of ``/connections`` (G50): that registry describes LLM
engines — ``engine_role``, ``billing``, ``plan_label`` — and ``/status`` picks
the first connected ``engine_role`` as the engine. A Pinterest account is not
an engine, and registering it there would corrupt engine selection.

Credential values enter through ``PUT .../credentials`` and are written to
``$CICADA_HOME/secrets.env`` (0600). They are never returned, never logged, and
never included in an error message.
"""

from __future__ import annotations

import secrets as pysecrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.models.schemas import (
    ConnectorAuthorizeResponse,
    ConnectorField,
    ConnectorStatus,
    ConnectorSyncResult,
    ConnectorsResponse,
)
from api.services import sync_state
from api.services.connections import secrets as secret_store
from api.services.connectors import base, pinterest, reddit

router = APIRouter(prefix="/sources/connectors")

ADAPTERS = {
    pinterest.CHANNEL_ID: pinterest,
    reddit.CHANNEL_ID: reddit,
}

LOGIN_MODES = {pinterest.CHANNEL_ID: "oauth", reddit.CHANNEL_ID: "credentials"}

# Single-use OAuth nonces: {state: expires_at}. In-process and deliberately not
# persisted — an interrupted sign-in is retried, not resumed.
_pending_states: dict[str, float] = {}
_STATE_TTL_SECONDS = 600


class CredentialsBody(BaseModel):
    fields: dict[str, str]


def _adapter(connector_id: str):
    adapter = ADAPTERS.get(connector_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"unknown connector '{connector_id}'")
    return adapter


def _status(connector_id: str, memory_path) -> ConnectorStatus:
    adapter = _adapter(connector_id)
    entry = sync_state.read_sync_state(memory_path).get(connector_id) or {}
    return ConnectorStatus(
        id=connector_id,
        label=adapter.LABEL,
        connected=adapter.is_connected(),
        fields=[ConnectorField(**f) for f in adapter.credential_fields()],
        last_sync=entry.get("last_sync") or None,
        last_error=entry.get("last_error") or None,
        detail=None,
        login_mode=LOGIN_MODES[connector_id],
    )


@router.get("", response_model=ConnectorsResponse)
async def list_connectors(settings: Settings = Depends(get_settings)):
    return ConnectorsResponse(
        connectors=[_status(cid, settings.memory_path) for cid in ADAPTERS]
    )


@router.get("/{connector_id}", response_model=ConnectorStatus)
async def get_connector(connector_id: str, settings: Settings = Depends(get_settings)):
    return _status(connector_id, settings.memory_path)


@router.put("/{connector_id}/credentials", response_model=ConnectorStatus)
async def set_credentials(
    connector_id: str, body: CredentialsBody, settings: Settings = Depends(get_settings)
):
    """Store this connector's credentials in ``secrets.env`` (0600).

    Only field names the adapter declares are accepted — an unknown name is a
    422, not a silent write, so this endpoint can never be used to set an
    arbitrary environment variable (an LLM API key, say) by name.
    """
    adapter = _adapter(connector_id)
    allowed = {f["name"] for f in adapter.FIELDS}
    unknown = sorted(set(body.fields) - allowed)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown field(s) for {connector_id}: {', '.join(unknown)}",
        )
    for name, value in body.fields.items():
        try:
            secret_store.set_secret(name, value)
        except ValueError as exc:
            # `exc` describes the shape, never the value.
            raise HTTPException(status_code=422, detail=str(exc))
    logger.info(f"{connector_id}: stored {len(body.fields)} credential field(s)")
    return _status(connector_id, settings.memory_path)


@router.delete("/{connector_id}/credentials", response_model=ConnectorStatus)
async def forget_credentials(connector_id: str, settings: Settings = Depends(get_settings)):
    _adapter(connector_id).forget()
    return _status(connector_id, settings.memory_path)


@router.post("/{connector_id}/authorize", response_model=ConnectorAuthorizeResponse)
async def authorize(connector_id: str, settings: Settings = Depends(get_settings)):
    """Mint the vendor consent URL the app opens in the user's own browser."""
    adapter = _adapter(connector_id)
    if adapter is not pinterest:
        raise HTTPException(
            status_code=400,
            detail=f"{connector_id} uses credentials, not an authorization flow",
        )
    if not secret_store.has_secret(pinterest.APP_ID_ENV) or not secret_store.has_secret(
        pinterest.APP_SECRET_ENV
    ):
        raise HTTPException(status_code=422, detail="Save the app ID and secret first")

    now = time.time()
    for state, expires in list(_pending_states.items()):
        if expires < now:
            _pending_states.pop(state, None)

    state = pysecrets.token_urlsafe(24)
    _pending_states[state] = now + _STATE_TTL_SECONDS
    base_url = f"http://{settings.host}:{settings.port}"
    return ConnectorAuthorizeResponse(
        authorize_url=pinterest.authorize_url(state, base_url=base_url), state=state
    )


@router.get("/pinterest/callback", response_class=HTMLResponse)
async def pinterest_callback(
    code: str = Query(""),
    state: str = Query(""),
    settings: Settings = Depends(get_settings),
):
    """Pinterest's OAuth redirect target.

    This is the one route in the API with no bearer token (the browser cannot
    send one), so it is gated by the single-use ``state`` nonce minted above:
    an unknown, expired or replayed state exchanges nothing.
    """
    expires = _pending_states.pop(state, None)
    if not state or expires is None or expires < time.time():
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in state")
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code returned")

    base_url = f"http://{settings.host}:{settings.port}"
    try:
        await pinterest.exchange_code(code, base_url=base_url)
    except base.ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        # Never echo the response body: a token error can carry app-secret context.
        logger.warning(f"Pinterest code exchange failed: {type(exc).__name__}")
        raise HTTPException(status_code=502, detail="Could not complete Pinterest sign-in")

    return HTMLResponse(
        "<html><body style='font:14px -apple-system;padding:40px'>"
        "<h2>Pinterest connected</h2>"
        "<p>You can close this tab and go back to Cicada.</p>"
        "</body></html>"
    )


@router.post("/{connector_id}/sync", response_model=ConnectorSyncResult)
async def sync_now(connector_id: str, settings: Settings = Depends(get_settings)):
    """Run one poll immediately. Mirrors the nightly Sleep-tail poll exactly."""
    adapter = _adapter(connector_id)
    result = await adapter.sync(settings.memory_path, allow_fetch=True)
    return ConnectorSyncResult(
        status=result.get("status", "error"),
        reason=result.get("reason"),
        new=int(result.get("new") or 0),
        seen=int(result.get("seen") or 0),
        error=result.get("error"),
    )
```

Note `sync_now` passes `allow_fetch=True`: a user pressing "Sync now" *is* the consent the env gate stands in for on an unattended nightly run.

- [ ] **Step 11: Mount the router and open the callback path**

In `api/main.py`, add `connectors` to the `from api.routers import (...)` block and, after line 168 (`capture.router`), add:

```python
app.include_router(connectors.router, tags=["connectors"])
```

In `api/services/auth.py`, change line 28 to:

```python
_OPEN_PATHS = frozenset({
    "/healthz",
    "/capture/telegram",
    # G71: Pinterest's OAuth redirect lands in the user's browser, which cannot
    # send the bearer token. Gated instead by a single-use, 10-minute `state`
    # nonce minted by POST /sources/connectors/pinterest/authorize.
    "/sources/connectors/pinterest/callback",
})
```

and extend the module docstring's open-paths sentence to name it.

- [ ] **Step 12: Run it to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_connectors_api.py api/tests/test_auth.py -q`
Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add api/routers/connectors.py api/main.py api/services/auth.py api/models/schemas.py api/tests/test_connectors_api.py
git commit -m "$(cat <<'EOF'
feat(api): /sources/connectors — status, credentials, OAuth, sync now

G71 §2 — a surface of its own rather than /connections, which describes LLM
engines and feeds engine selection. Only declared field names are writable,
values are never returned or logged, and the one auth-exempt route (the
Pinterest redirect the browser follows) is gated by a single-use state nonce.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

- [ ] **Step 14: Write the failing Sleep-tail tests**

Create `api/tests/test_sleep_connector_poll.py`:

```python
"""The nightly connector poll rides the Sleep cycle's tail (G71 §2).

Mirrors test_sleep_cycle_logo_warmup.py: hermetic, no network, no real model,
no real git.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.services import predicates, sleep_cycle


def _empty_memory(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _settings(memory):
    return SimpleNamespace(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        archive_threshold=0.2,
        decay_nudge_threshold=0.4,
        link_enrich_enabled=False,
        inbox_stale_after_days=90,
    )


def test_connectors_are_polled_on_the_idle_early_return(tmp_path, monkeypatch):
    """A quiet night still has to pull new pins and saves."""
    memory = _empty_memory(tmp_path)
    calls = []

    async def fake_sync(memory_path, **kwargs):
        calls.append(memory_path)
        return {"status": "ok", "new": 0, "seen": 0, "error": None}

    monkeypatch.setattr("api.services.connectors.pinterest.sync", fake_sync)
    monkeypatch.setattr("api.services.connectors.reddit.sync", fake_sync)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-empty"))

    assert calls == [memory, memory]
    assert sleep_cycle.get_sleep_state().status == "idle"


def test_a_failing_connector_never_fails_the_cycle(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)

    async def boom(memory_path, **kwargs):
        raise RuntimeError("token expired")

    async def ok(memory_path, **kwargs):
        return {"status": "ok", "new": 0, "seen": 0, "error": None}

    monkeypatch.setattr("api.services.connectors.pinterest.sync", boom)
    monkeypatch.setattr("api.services.connectors.reddit.sync", ok)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-boom"))
    assert sleep_cycle.get_sleep_state().status == "idle"
    assert sleep_cycle.get_sleep_state().error is None
```

- [ ] **Step 15: Run it to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_sleep_connector_poll.py -q`
Expected: FAIL with `assert [] == [memory, memory]`.

- [ ] **Step 16: Add the Sleep tail step**

In `api/services/sleep_cycle.py`, immediately after `_warm_logos_safely` (line 81), add:

```python
async def _poll_connectors_safely(memory_path: Path) -> None:
    """G71 §2: pull new Pinterest pins and Reddit saves on the nightly cycle.

    Same contract as ``_warm_logos_safely``: bounded, credential-gated,
    network-gated (``CICADA_ALLOW_CONNECTOR_FETCH``), and never fatal — an
    expired token or a rate limit must not fail a Sleep cycle. Each adapter
    already records its own failure through ``sync_state.record_error``, which
    is what surfaces it per-channel on the Capture page; this wrapper only
    guarantees that a raise inside one adapter cannot stop the other or the
    cycle.

    Runs at the TAIL (and on the idle early return), so anything pulled tonight
    is consolidated by tomorrow's cycle — the same "it joins the graph after the
    next Sleep cycle" contract every other capture path already states.
    """
    from api.services.connectors import pinterest, reddit

    for adapter in (pinterest, reddit):
        try:
            result = await adapter.sync(memory_path)
            if result.get("status") == "ok" and result.get("new"):
                logger.info(f"{adapter.LABEL}: pulled {result['new']} new saved item(s)")
        except Exception as e:
            logger.warning(
                f"{adapter.LABEL} poll failed: {type(e).__name__}: {e}"
            )
```

Add the call in both places, immediately before each `await _warm_logos_safely(memory_path)` — at line 185 (idle early return) and at line 432 (full-run tail):

```python
            await _poll_connectors_safely(memory_path)
            await _warm_logos_safely(memory_path)
```

```python
        await _poll_connectors_safely(memory_path)
        await _warm_logos_safely(memory_path)
```

- [ ] **Step 17: Run the full suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS.

- [ ] **Step 18: Commit**

```bash
git add api/services/sleep_cycle.py api/tests/test_sleep_connector_poll.py
git commit -m "$(cat <<'EOF'
feat(sleep): nightly connector poll at the cycle tail

G71 §2 — runs on the idle early return too, so a quiet night still pulls.
Credential- and network-gated, and a raise in one adapter can neither stop
the other nor fail the cycle; each adapter records its own failure for the
Capture page to surface.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 9: App — the Imports catalog (route badges per platform)

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/ImportCatalog.swift`
- Modify: `Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift` (`AddSourceTile` cases + `flow(for:)` + `tileButton`)
- Modify: `Sources/CicadaApp/Views/Capture/Sheets/WalkthroughPanel.swift` (`WalkthroughVendor` cases)
- Modify: `Sources/CicadaApp/Models/SourceChannel.swift` (`lastError`)
- Modify: `Sources/CicadaApp/Theme/Copy.swift`
- Test: `Tests/CicadaAppTests/ImportCatalogTests.swift` (new); update `AddSourceTileTests.swift`, `SourceChannelTests.swift`

**Interfaces:**
- Consumes: `GET /sources/channels` now returns `pinterest` / `reddit` rows with `lastError` (Task 8).
- Produces:
  - `enum ImportRoute: String { case connect, importFile, sync, subscribe, paste }` with `var badge: String`
  - `struct ImportTileState: Equatable { let badge: String; let connected: Bool; let detail: String? }`
  - `AddSourceTile.route: ImportRoute`
  - `static func AddSourceTile.tileState(_ tile: AddSourceTile, channels: [SourceChannel]) -> ImportTileState`
  - new `AddSourceTile` cases `instagram`, `youtube`, `pinterest`, `reddit`, `tiktok`, `linkedin` (replacing `savedContent`)
  - new `WalkthroughVendor` cases `tiktok`, `linkedin`, `redditExport`
  - `SourceChannel.lastError: String?`

- [ ] **Step 1: Write the failing catalog tests**

Create `app/CicadaApp/Tests/CicadaAppTests/ImportCatalogTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G71 §4.1 — the `+` sheet is a platform catalog: one tile per platform, each
/// carrying the route it takes (Connect vs Import file vs Sync vs Subscribe)
/// and the live connected state from `GET /sources/channels`.
final class ImportCatalogTests: XCTestCase {

    // MARK: - Routes

    func testTheTwoDirectApiPlatformsTakeTheConnectRoute() {
        XCTAssertEqual(AddSourceTile.pinterest.route, .connect)
        XCTAssertEqual(AddSourceTile.reddit.route, .connect)
        XCTAssertEqual(ImportRoute.connect.badge, "Connect")
    }

    func testEveryExportPlatformTakesTheImportFileRoute() {
        for tile in [AddSourceTile.instagram, .youtube, .tiktok, .linkedin,
                     .chatExport, .bookmarksFile] {
            XCTAssertEqual(tile.route, .importFile, "\(tile.rawValue)")
        }
        XCTAssertEqual(ImportRoute.importFile.badge, "Import file")
    }

    func testLocalAndSubscriptionRoutesKeepTheirOwnVerbs() {
        XCTAssertEqual(AddSourceTile.browserBookmarks.route, .sync)
        XCTAssertEqual(AddSourceTile.appleNotes.route, .sync)
        XCTAssertEqual(AddSourceTile.rssFeed.route, .subscribe)
        XCTAssertEqual(AddSourceTile.calendar.route, .subscribe)
        XCTAssertEqual(AddSourceTile.pasteLink.route, .paste)
        XCTAssertEqual(ImportRoute.sync.badge, "Sync")
        XCTAssertEqual(ImportRoute.subscribe.badge, "Subscribe")
        XCTAssertEqual(ImportRoute.paste.badge, "Save")
    }

    // MARK: - Tile state from channels

    private func channel(_ id: String, connected: Bool, detail: String? = nil,
                         lastError: String? = nil) -> SourceChannel {
        SourceChannel(id: id, label: id, connected: connected, count: 1,
                      lastSync: "2026-08-30T10:00:00Z", detail: detail,
                      lastError: lastError, actions: [])
    }

    func testAnUnconnectedTileShowsItsRouteBadgeAndNoDetail() {
        let state = AddSourceTile.tileState(.pinterest, channels: [])
        XCTAssertEqual(state.badge, "Connect")
        XCTAssertFalse(state.connected)
        XCTAssertNil(state.detail)
    }

    func testAConnectedTileShowsTheChannelDetail() {
        let state = AddSourceTile.tileState(
            .pinterest,
            channels: [channel("pinterest", connected: true, detail: "40 pins · synced 2026-08-30")]
        )
        XCTAssertTrue(state.connected)
        XCTAssertEqual(state.detail, "40 pins · synced 2026-08-30")
    }

    func testAFailingChannelIsNotAdvertisedAsHealthy() {
        let state = AddSourceTile.tileState(
            .reddit,
            channels: [channel("reddit", connected: true,
                               detail: "Last sync failed · RuntimeError: 429",
                               lastError: "RuntimeError: 429")]
        )
        XCTAssertEqual(state.badge, "Needs attention")
        XCTAssertEqual(state.detail, "Last sync failed · RuntimeError: 429")
    }

    func testATileSpanningTwoChannelsIsConnectedWhenEitherIs() {
        let state = AddSourceTile.tileState(
            .chatExport,
            channels: [channel("chat-export:claude", connected: false),
                       channel("chat-export:chatgpt", connected: true, detail: "3 conversations")]
        )
        XCTAssertTrue(state.connected)
        XCTAssertEqual(state.detail, "3 conversations")
    }

    // MARK: - Coverage

    func testEveryPlatformInTheSpecHasATile() {
        let ids = Set(AddSourceTile.allCases.map(\.rawValue))
        for expected in ["instagram", "youtube", "pinterest", "reddit", "tiktok",
                         "linkedin", "browserBookmarks", "appleNotes", "rssFeed",
                         "calendar", "telegram", "pasteLink", "bookmarksFile"] {
            XCTAssertTrue(ids.contains(expected), "missing tile: \(expected)")
        }
    }

    func testTheRetiredCombinedTileIsGone() {
        XCTAssertNil(AddSourceTile(rawValue: "savedContent"))
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd app/CicadaApp && swift test --filter ImportCatalogTests`
Expected: FAIL to compile — `cannot find 'ImportRoute' in scope`.

- [ ] **Step 3: Add `lastError` to the channel model**

In `Sources/CicadaApp/Models/SourceChannel.swift`, add the stored property after `detail`, extend `CodingKeys`, the memberwise `init`, and the tolerant `init(from:)`:

```swift
    /// G71 — the last poll's failure, when there was one. Present so a tile can
    /// say "needs attention" instead of showing a stale success.
    let lastError: String?
```

```swift
    enum CodingKeys: String, CodingKey {
        case id, label, connected, count, lastSync, detail, lastError, actions
    }
```

```swift
    init(id: String, label: String, connected: Bool = false, count: Int = 0,
         lastSync: String? = nil, detail: String? = nil, lastError: String? = nil,
         actions: [String] = []) {
```

(assigning `self.lastError = lastError` alongside the others), and in `init(from:)`:

```swift
        lastError = try container.decodeIfPresent(String.self, forKey: .lastError)
```

- [ ] **Step 4: Add the route model**

Create `Sources/CicadaApp/Views/Capture/Sheets/ImportCatalog.swift`:

```swift
import Foundation

/// How a platform actually gets into memory (G71 §4.1). The badge on each tile
/// is this, and nothing else — the user should be able to tell "I sign in here"
/// from "I drop a file here" without opening the tile.
enum ImportRoute: String {
    /// A direct API with credentials — Pinterest, Reddit.
    case connect
    /// A vendor data export the user downloads and drops.
    case importFile
    /// Read straight off this Mac — bookmarks, Apple Notes.
    case sync
    /// A URL Cicada re-checks — RSS, calendars.
    case subscribe
    /// One link, right now.
    case paste

    var badge: String {
        switch self {
        case .connect: return "Connect"
        case .importFile: return "Import file"
        case .sync: return "Sync"
        case .subscribe: return "Subscribe"
        case .paste: return "Save"
        }
    }
}

/// What one catalog tile renders, derived purely from the tile plus the current
/// channel snapshot — no view state, so it is unit-testable on its own.
struct ImportTileState: Equatable {
    let badge: String
    let connected: Bool
    let detail: String?
}

extension AddSourceTile {
    /// The channels this tile manages, resolved against a snapshot.
    private func channels(in channels: [SourceChannel]) -> [SourceChannel] {
        let ids = Set(channelIds)
        return channels.filter { ids.contains($0.id) }
    }

    /// The badge/connected/detail triple for one tile.
    ///
    /// A channel with a recorded `lastError` overrides the route badge with
    /// "Needs attention": a tile that still says "Connect" — or worse, shows a
    /// week-old success — while its nightly poll is 401-ing is the exact kind of
    /// quiet lie the transparency principle rules out.
    static func tileState(_ tile: AddSourceTile, channels: [SourceChannel]) -> ImportTileState {
        let mine = tile.channels(in: channels)
        if let failing = mine.first(where: { ($0.lastError ?? "").isEmpty == false }) {
            return ImportTileState(badge: "Needs attention", connected: failing.connected,
                                   detail: failing.detail)
        }
        guard let live = mine.first(where: { $0.connected }) else {
            return ImportTileState(badge: tile.route.badge, connected: false, detail: nil)
        }
        return ImportTileState(badge: tile.route.badge, connected: true, detail: live.detail)
    }
}
```

- [ ] **Step 5: Split the platform tiles**

In `AddSourceSheet.swift`, replace the `AddSourceTile` case list and add `route`:

```swift
enum AddSourceTile: String, CaseIterable, Identifiable {
    case chatExport, bookmarksFile, pasteLink, rssFeed, calendar
    case browserBookmarks, appleNotes, telegram
    // G71 §4.1 — one tile per platform, replacing the combined `savedContent`
    // tile: the routes differ (two are Connect, four are Import file) and a
    // single "Instagram & YouTube" tile could not carry a route badge.
    case instagram, youtube, pinterest, reddit, tiktok, linkedin

    var id: String { rawValue }

    var route: ImportRoute {
        switch self {
        case .pinterest, .reddit: return .connect
        case .browserBookmarks, .appleNotes: return .sync
        case .rssFeed, .calendar: return .subscribe
        case .pasteLink: return .paste
        case .telegram: return .connect
        case .chatExport, .bookmarksFile, .instagram, .youtube, .tiktok, .linkedin:
            return .importFile
        }
    }
```

Extend `title` / `blurb` / `icon` / `channelIds` / `vendors` with the six new cases (and delete every `savedContent` arm):

```swift
        case .instagram: return "Instagram"
        case .youtube: return "YouTube"
        case .pinterest: return "Pinterest"
        case .reddit: return "Reddit"
        case .tiktok: return "TikTok"
        case .linkedin: return "LinkedIn"
```

```swift
        case .instagram: return "Your saved posts, from a data export."
        case .youtube: return "Playlists and watch history, from Takeout."
        case .pinterest: return "Boards and pins, pulled straight from your account."
        case .reddit: return "Saved posts and comments, pulled every night."
        case .tiktok: return "Favourites and likes, from a data export."
        case .linkedin: return "Saved items — links and dates, nothing more."
```

```swift
        case .instagram: return "camera.fill"
        case .youtube: return "play.rectangle.fill"
        case .pinterest: return "pin.fill"
        case .reddit: return "bubble.left.and.text.bubble.right.fill"
        case .tiktok: return "music.note"
        case .linkedin: return "briefcase.fill"
```

```swift
        case .pinterest: return ["pinterest"]
        case .reddit: return ["reddit"]
        case .instagram, .youtube, .tiktok, .linkedin: return []
```

```swift
        case .instagram: return [.instagram]
        case .youtube: return [.takeout]
        case .tiktok: return [.tiktok]
        case .linkedin: return [.linkedin]
        // The Reddit tile is Connect-first, but the GDPR export is the only way
        // past the API's ~1,000-item listing cap, so the walkthrough rides along.
        case .reddit: return [.redditExport]
        case .pinterest: return []
```

- [ ] **Step 6: Add the three new walkthrough vendors**

In `WalkthroughPanel.swift`, extend `WalkthroughVendor`:

```swift
enum WalkthroughVendor: String, CaseIterable, Identifiable {
    case claude, chatgpt, takeout, instagram, tiktok, linkedin, redditExport
```

with, in each existing switch:

```swift
        case .tiktok: return "TikTok"
        case .linkedin: return "LinkedIn"
        case .redditExport: return "Reddit"
```

```swift
        case .tiktok: return URL(string: "https://www.tiktok.com/setting/download-your-data")!
        case .linkedin: return URL(string: "https://www.linkedin.com/mypreferences/d/download-my-data")!
        case .redditExport: return URL(string: "https://www.reddit.com/settings/data-request")!
```

```swift
        case .tiktok: return "Your TikTok favourites and likes as saved links."
        case .linkedin: return "Your saved LinkedIn items — links and dates only."
        case .redditExport: return "A one-off backfill past Reddit's 1,000-item API cap."
```

```swift
        case .tiktok:
            return ["Open Settings and privacy → Account → Download your data",
                    "Choose JSON as the file format",
                    "Request the data and wait for the email (1–4 days)",
                    "Unzip it and drop user_data.json below"]
        case .linkedin:
            return ["Open Settings → Data privacy → Get a copy of your data",
                    "Pick \"Want something in particular\" → Saved items",
                    "Request the archive (arrives in minutes; the link lasts 72 h)",
                    "Unzip it and drop Saved Items.csv below"]
        case .redditExport:
            return ["Open Settings → Privacy → Request a copy of your data",
                    "Choose the full date range and request it",
                    "Download the archive from the email",
                    "Unzip it and drop saved_posts.csv below"]
```

- [ ] **Step 7: Render the badge on each tile and route the new flows**

In `AddSourceSheet`, add `@Environment(Store.self)`-backed state to `tileButton(_:)` — it already has `store` in scope — showing the badge and detail under the title:

```swift
    private func tileButton(_ tile: AddSourceTile) -> some View {
        let state = AddSourceTile.tileState(tile, channels: store.channels.value ?? [])
        return Button { open(tile) } label: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Image(systemName: tile.icon)
                    .font(.system(size: 18))
                    .foregroundStyle(CicadaTheme.accent)
                Text(tile.title)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(state.detail ?? tile.blurb)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text(state.badge)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(state.connected ? CicadaTheme.success : CicadaTheme.textTertiary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(CicadaTheme.spacingMD)
            .glassCard()
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(tile.title). \(state.badge). \(state.detail ?? tile.blurb)")
    }
```

In `flow(for:)`, delete the `.savedContent` arm and add:

```swift
        case .instagram, .youtube, .tiktok, .linkedin:
            WalkthroughPanel(vendors: tile.vendors, vendor: $vendor) { pickSavedContent() }
        case .pinterest, .reddit:
            ConnectorSetupPanel(connectorId: tile.rawValue, vendors: tile.vendors, vendor: $vendor)
```

> `ConnectorSetupPanel` lands in Task 11. Until then, keep the tree building by
> using a temporary placeholder for the two connect tiles:
> `WalkthroughPanel(vendors: tile.vendors, vendor: $vendor) { pickSavedContent() }`
> for `.reddit` and `Text(tile.blurb)` for `.pinterest`, and swap both in Task 11.

In `open(_:)`, set the initial vendor when a tile has one:

```swift
    private func open(_ tile: AddSourceTile) {
        if let first = tile.vendors.first { vendor = first }
        expanded = tile
    }
```

- [ ] **Step 8: Update the two coverage tests**

In `Tests/CicadaAppTests/SourceChannelTests.swift`, extend `AddSourceCatalogTests.backendChannelIds`:

```swift
    private static let backendChannelIds: Set<String> = [
        "chat-export:claude", "chat-export:chatgpt", "bookmarks", "notes",
        "rss", "calendar", "pinterest", "reddit", "telegram", "files",
    ]
```

In `Tests/CicadaAppTests/AddSourceTileTests.swift`, `testTheVendorsPartitionCleanlyAcrossTiles` needs no edit (the new vendors are all attached), but any test naming `.savedContent` must be repointed at `.instagram`.

- [ ] **Step 9: Run the app tests**

Run: `cd app/CicadaApp && swift test`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/ImportCatalog.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/WalkthroughPanel.swift \
        app/CicadaApp/Sources/CicadaApp/Models/SourceChannel.swift \
        app/CicadaApp/Tests/CicadaAppTests/ImportCatalogTests.swift \
        app/CicadaApp/Tests/CicadaAppTests/AddSourceTileTests.swift \
        app/CicadaApp/Tests/CicadaAppTests/SourceChannelTests.swift
git commit -m "$(cat <<'EOF'
feat(app): Imports catalog — one tile per platform with a route badge

G71 §4.1 — splits the combined "Instagram & YouTube" tile into six platform
tiles and gives every tile a Connect / Import file / Sync / Subscribe / Save
badge plus live state from /sources/channels. A channel with a recorded
lastError reads "Needs attention" rather than advertising a stale success.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 10: App — the export overlay (step path → drop → live preview → confirm → summary)

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/UploadPreview.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/ImportOverlay.swift`
- Modify: `Sources/CicadaApp/Theme/Copy.swift` (step paths)
- Modify: `Sources/CicadaApp/Views/Capture/Sheets/WalkthroughPanel.swift` (`stepPath` + its line)
- Modify: `Sources/CicadaApp/Services/APIClient.swift:1281-1311` (generic multipart + `previewSource`)
- Modify: `Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift` (drive the stage machine)
- Test: `Tests/CicadaAppTests/ImportOverlayTests.swift` (new); update `CopyConstantsTests.swift`

**Interfaces:**
- Consumes: `POST /sources/upload?preview=true` returning `{recognized, platform, total, collections:[{name,kind,count}], warnings}` (Task 2); `WalkthroughVendor` incl. `.tiktok`, `.linkedin`, `.redditExport` (Task 9).
- Produces:
  - `struct UploadCollection: Codable, Equatable, Identifiable, Hashable { let name: String; let kind: String; let count: Int; var id: String }`
  - `struct UploadPreview: Codable, Equatable { let recognized: Bool; let platform: String; let total: Int; let collections: [UploadCollection]; let warnings: [String] }`
  - `enum ImportStage: Equatable { case idle, parsing(String), preview(UploadPreview, URL), importing, done(String), failed(String) }`
  - `enum ImportOverlayState { static func pluralKind(_: String) -> String; static func totalLine(_: UploadPreview) -> String; static func summary(_: UploadResponse) -> String; static func afterPreview(_: UploadPreview, file: URL) -> ImportStage }`
  - `struct ImportPreviewSection: View { let stage: ImportStage; let onConfirm: (URL) -> Void; let onCancel: () -> Void }`
  - `Copy.exportStepPath(_ vendor: WalkthroughVendor) -> String`, `WalkthroughVendor.stepPath: String`
  - `APIClient.previewSource(fileURL: URL, includeHistory: Bool = false) async throws -> UploadPreview`

- [ ] **Step 1: Write the failing model + reducer tests**

Create `app/CicadaApp/Tests/CicadaAppTests/ImportOverlayTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G71 §4.2–4.3 — the export overlay: a written step path per platform, and a
/// drop → live preview → confirm → summary machine over the staging-free
/// preview endpoint.
final class ImportOverlayTests: XCTestCase {

    // MARK: - Wire decoding

    func testPreviewDecodesTheBackendEnvelope() throws {
        let json = """
        {"recognized": true, "platform": "instagram", "total": 214,
         "collections": [{"name": "Recipes", "kind": "collection", "count": 182},
                         {"name": "Type inspo", "kind": "collection", "count": 32}],
         "warnings": []}
        """.data(using: .utf8)!
        let preview = try JSONDecoder().decode(UploadPreview.self, from: json)
        XCTAssertTrue(preview.recognized)
        XCTAssertEqual(preview.platform, "instagram")
        XCTAssertEqual(preview.total, 214)
        XCTAssertEqual(preview.collections.count, 2)
        XCTAssertEqual(preview.collections[0].name, "Recipes")
        XCTAssertEqual(preview.collections[0].count, 182)
    }

    func testPreviewToleratesAMissingFieldFromAnOlderBackend() throws {
        let json = #"{"recognized": false}"#.data(using: .utf8)!
        let preview = try JSONDecoder().decode(UploadPreview.self, from: json)
        XCTAssertFalse(preview.recognized)
        XCTAssertEqual(preview.platform, "unknown")
        XCTAssertEqual(preview.total, 0)
        XCTAssertTrue(preview.collections.isEmpty)
        XCTAssertTrue(preview.warnings.isEmpty)
    }

    func testCollectionIdsAreUniqueSoTheListDoesNotCollapseRows() {
        let a = UploadCollection(name: "Recipes", kind: "collection", count: 1)
        let b = UploadCollection(name: "Recipes", kind: "board", count: 1)
        XCTAssertNotEqual(a.id, b.id)
    }

    // MARK: - Copy

    func testTheTotalLineNamesBothNumbers() {
        let preview = UploadPreview(
            recognized: true, platform: "instagram", total: 214,
            collections: [UploadCollection(name: "Recipes", kind: "collection", count: 182),
                          UploadCollection(name: "Type inspo", kind: "collection", count: 32)],
            warnings: [])
        XCTAssertEqual(ImportOverlayState.totalLine(preview), "214 items across 2 collections")
    }

    func testTheTotalLineIsSingularForOneCollection() {
        let preview = UploadPreview(
            recognized: true, platform: "linkedin", total: 1,
            collections: [UploadCollection(name: "Saved Items", kind: "saved", count: 1)],
            warnings: [])
        XCTAssertEqual(ImportOverlayState.totalLine(preview), "1 item in 1 saved")
    }

    func testTheTotalLinePluralisesAwkwardKindsWithoutInventingWords() {
        let preview = UploadPreview(
            recognized: true, platform: "reddit", total: 5,
            collections: [UploadCollection(name: "Saved posts", kind: "saved", count: 3),
                          UploadCollection(name: "Saved comments", kind: "saved", count: 2)],
            warnings: [])
        XCTAssertEqual(ImportOverlayState.totalLine(preview), "5 items across 2 saved sets")
    }

    func testTheSummaryShowsNewAndAlreadySaved() {
        let response = UploadResponse(status: "ok", episodesCreated: 182, episodesUpdated: 0,
                                      duplicatesSkipped: 32, message: "", source: "Instagram Saved")
        XCTAssertEqual(ImportOverlayState.summary(response), "182 new · 32 already saved")
    }

    func testTheSummarySaysSoWhenNothingIsNew() {
        let response = UploadResponse(status: "ok", episodesCreated: 0, episodesUpdated: 0,
                                      duplicatesSkipped: 32, message: "", source: "Instagram Saved")
        XCTAssertEqual(ImportOverlayState.summary(response), "Nothing new · 32 already saved")
    }

    // MARK: - Stage machine

    func testAnUnrecognizedFileFailsWithItsWarningRatherThanOfferingConfirm() {
        let preview = UploadPreview(recognized: false, platform: "unknown", total: 0,
                                    collections: [], warnings: ["Unsupported file format."])
        let url = URL(fileURLWithPath: "/tmp/photo.heic")
        XCTAssertEqual(ImportOverlayState.afterPreview(preview, file: url),
                       .failed("Unsupported file format."))
    }

    func testAnUnrecognizedFileWithNoWarningStillFailsHonestly() {
        let preview = UploadPreview(recognized: false, platform: "unknown", total: 0,
                                    collections: [], warnings: [])
        let url = URL(fileURLWithPath: "/tmp/x.bin")
        XCTAssertEqual(ImportOverlayState.afterPreview(preview, file: url),
                       .failed("Cicada could not read this file as a saved-content export."))
    }

    func testARecognizedFileMovesToPreviewCarryingTheFile() {
        let preview = UploadPreview(
            recognized: true, platform: "instagram", total: 3,
            collections: [UploadCollection(name: "Recipes", kind: "collection", count: 3)],
            warnings: [])
        let url = URL(fileURLWithPath: "/tmp/saved_posts.json")
        XCTAssertEqual(ImportOverlayState.afterPreview(preview, file: url), .preview(preview, url))
    }

    // MARK: - Step paths

    func testEveryExportVendorHasABreadcrumbStepPath() {
        for vendor in WalkthroughVendor.allCases {
            let path = vendor.stepPath
            XCTAssertFalse(path.isEmpty, "\(vendor.rawValue) has no step path")
            XCTAssertTrue(path.contains(">"),
                          "\(vendor.rawValue) step path is not a breadcrumb: \(path)")
        }
    }

    func testTheInstagramStepPathIsTheOneFromTheSpec() {
        XCTAssertEqual(
            WalkthroughVendor.instagram.stepPath,
            "Settings > Accounts Center > Your information and permissions > "
            + "Download your information > Download or transfer > "
            + "Some of your information > Saved > JSON")
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd app/CicadaApp && swift test --filter ImportOverlayTests`
Expected: FAIL to compile — `cannot find 'UploadPreview' in scope`.

- [ ] **Step 3: Add the wire models**

Create `Sources/CicadaApp/Models/UploadPreview.swift`:

```swift
import Foundation

/// One grouping inside a dropped export — an Instagram collection, a YouTube
/// playlist, a Pinterest board, a bookmark folder — and how many items it holds.
struct UploadCollection: Codable, Equatable, Hashable, Identifiable {
    let name: String
    let kind: String
    let count: Int

    /// Name alone is not unique across kinds, and a colliding `ForEach` id
    /// silently collapses rows (the same bug the heatmap weekday column had).
    var id: String { "\(kind):\(name)" }

    init(name: String, kind: String, count: Int) {
        self.name = name
        self.kind = kind
        self.count = count
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decode(String.self, forKey: .name)) ?? ""
        kind = (try? c.decode(String.self, forKey: .kind)) ?? "list"
        count = (try? c.decode(Int.self, forKey: .count)) ?? 0
    }
}

/// `POST /sources/upload?preview=true` — what a dropped export CONTAINS.
/// Answering it stages nothing, so this is safe to request on every drop.
struct UploadPreview: Codable, Equatable {
    let recognized: Bool
    let platform: String
    let total: Int
    let collections: [UploadCollection]
    let warnings: [String]

    init(recognized: Bool, platform: String, total: Int,
         collections: [UploadCollection], warnings: [String]) {
        self.recognized = recognized
        self.platform = platform
        self.total = total
        self.collections = collections
        self.warnings = warnings
    }

    /// Tolerant on purpose: a backend older than G71 answers the same endpoint
    /// with an upload response, and a partially-populated body must render as
    /// "not recognized" rather than throwing inside the overlay.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        recognized = (try? c.decode(Bool.self, forKey: .recognized)) ?? false
        platform = (try? c.decode(String.self, forKey: .platform)) ?? "unknown"
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
        collections = (try? c.decode([UploadCollection].self, forKey: .collections)) ?? []
        warnings = (try? c.decode([String].self, forKey: .warnings)) ?? []
    }
}
```

- [ ] **Step 4: Add the step-path copy**

In `Sources/CicadaApp/Theme/Copy.swift`, add a new `// MARK: - Export step paths (G71 §4.2)` section:

```swift
    /// One breadcrumb line per export platform: exactly the clicks, in the
    /// vendor's own words, so the user never has to guess which of five
    /// "Download your data" screens is the right one. `>` is the separator
    /// because that is how the spec writes it and how the vendors' own
    /// breadcrumbs read.
    static let instagramStepPath =
        "Settings > Accounts Center > Your information and permissions > "
        + "Download your information > Download or transfer > "
        + "Some of your information > Saved > JSON"

    static let takeoutStepPath =
        "Google Takeout > Deselect all > YouTube and YouTube Music > "
        + "All YouTube data included > playlists + history > Next step > Create export"

    static let tiktokStepPath =
        "Profile > Menu > Settings and privacy > Account > Download your data > "
        + "File format: JSON > Request data"

    static let linkedinStepPath =
        "Settings & Privacy > Data privacy > Get a copy of your data > "
        + "Want something in particular > Saved items > Request archive"

    static let redditExportStepPath =
        "Settings > Privacy > Request a copy of your data > Full date range > Request data"

    static let claudeStepPath =
        "Settings > Privacy > Export data > check your email > download the .zip"

    static let chatgptStepPath =
        "Settings > Data controls > Export data > Export > "
        + "check your email > download the .zip"

    static func exportStepPath(_ vendor: WalkthroughVendor) -> String {
        switch vendor {
        case .claude: return claudeStepPath
        case .chatgpt: return chatgptStepPath
        case .takeout: return takeoutStepPath
        case .instagram: return instagramStepPath
        case .tiktok: return tiktokStepPath
        case .linkedin: return linkedinStepPath
        case .redditExport: return redditExportStepPath
        }
    }
```

In `WalkthroughPanel.swift`, add to `WalkthroughVendor`:

```swift
    /// The one-line breadcrumb of exactly where to click (G71 §4.2). Lives in
    /// `Copy` so every user-facing string stays in one file.
    var stepPath: String { Copy.exportStepPath(self) }
```

and render it in `WalkthroughPanel`'s body, between `Text(vendor.summary)` and `stage`:

```swift
            Text(vendor.stepPath)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityLabel("Where to click in \(vendor.title): \(vendor.stepPath)")
```

- [ ] **Step 5: Add the stage machine**

Create `Sources/CicadaApp/Views/Capture/Sheets/ImportOverlay.swift`:

```swift
import SwiftUI

/// Where an import is, from drop to summary (G71 §4.3).
enum ImportStage: Equatable {
    case idle
    /// Parsing the dropped file server-side. Nothing has been staged.
    case parsing(String)
    /// The parse came back: this is what the file contains, and the file to
    /// re-post if the user confirms.
    case preview(UploadPreview, URL)
    case importing
    case done(String)
    case failed(String)
}

/// Pure decisions the overlay makes, hoisted out of the view so they are
/// testable without SwiftUI.
enum ImportOverlayState {

    /// Plural of a collection kind. "saved" and "list" would otherwise become
    /// "saveds"; every other kind pluralises by adding an s.
    static func pluralKind(_ kind: String) -> String {
        switch kind {
        case "saved": return "saved sets"
        default: return kind + "s"
        }
    }

    /// "214 items across 6 collections" / "1 item in 1 saved".
    static func totalLine(_ preview: UploadPreview) -> String {
        let itemWord = preview.total == 1 ? "item" : "items"
        let kind = preview.collections.first?.kind ?? "collection"
        if preview.collections.count == 1 {
            return "\(preview.total) \(itemWord) in 1 \(kind)"
        }
        return "\(preview.total) \(itemWord) across \(preview.collections.count) \(pluralKind(kind))"
    }

    /// "182 new · 32 already saved" — the dedup counts the spec asks for.
    static func summary(_ response: UploadResponse) -> String {
        let newPart = response.episodesCreated == 0
            ? "Nothing new"
            : "\(response.episodesCreated) new"
        return "\(newPart) · \(response.duplicatesSkipped) already saved"
    }

    /// A preview only earns a Confirm button if it actually found something;
    /// otherwise the overlay says why, in the backend's own words.
    static func afterPreview(_ preview: UploadPreview, file: URL) -> ImportStage {
        guard preview.recognized, preview.total > 0 else {
            return .failed(preview.warnings.first
                ?? "Cicada could not read this file as a saved-content export.")
        }
        return .preview(preview, file)
    }
}

/// The live collection list plus its confirm/cancel controls.
struct ImportPreviewSection: View {
    let stage: ImportStage
    let onConfirm: (URL) -> Void
    let onCancel: () -> Void

    var body: some View {
        switch stage {
        case .idle:
            EmptyView()
        case .parsing(let filename):
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Reading \(filename)…")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        case .preview(let preview, let file):
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(ImportOverlayState.totalLine(preview))
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                ScrollView {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(preview.collections) { collection in
                            HStack {
                                Text(collection.name)
                                    .font(CicadaTheme.captionFont)
                                    .foregroundStyle(CicadaTheme.textPrimary)
                                Spacer()
                                Text("\(collection.count)")
                                    .font(CicadaTheme.captionFont)
                                    .foregroundStyle(CicadaTheme.textSecondary)
                            }
                            .accessibilityElement(children: .combine)
                            .accessibilityLabel("\(collection.name), \(collection.count) items")
                        }
                    }
                }
                .frame(maxHeight: 140)
                ForEach(preview.warnings, id: \.self) { warning in
                    Text(warning)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.warning)
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    Button("Import these") { onConfirm(file) }
                        .buttonStyle(.borderedProminent)
                        .accessibilityLabel("Import \(preview.total) items")
                    Button("Cancel", action: onCancel).buttonStyle(.bordered)
                }
            }
        case .importing:
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Importing…").font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        case .done(let summary):
            VStack(alignment: .leading, spacing: 2) {
                Text(summary)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.success)
                Text("Processed on the next Sleep cycle.")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        case .failed(let message):
            Text(message)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.danger)
        }
    }
}
```

- [ ] **Step 6: Add the preview call to `APIClient`**

In `Services/APIClient.swift`, make `uploadMultipart` generic and add the preview method:

```swift
    private func uploadMultipart<T: Decodable>(path: String, fileURL: URL) async throws -> T {
```

(the body is unchanged except the final line, which becomes `return try decoder.decode(T.self, from: data)`), then:

```swift
    /// `POST /sources/upload?preview=true` — describe a file without importing
    /// any of it. Safe to call on every drop: the backend stages nothing.
    func previewSource(fileURL: URL, includeHistory: Bool = false) async throws -> UploadPreview {
        let query = includeHistory ? "?preview=true&include_history=true" : "?preview=true"
        return try await uploadMultipart(path: "/sources/upload" + query, fileURL: fileURL)
    }
```

`uploadSource(fileURL:)` needs no change — its declared return type drives the generic.

- [ ] **Step 7: Drive the machine from the sheet**

In `AddSourceSheet.swift`, add state and handlers:

```swift
    @State private var stage: ImportStage = .idle
    @State private var includeHistory = false
```

```swift
    /// Pick a file and immediately preview it — nothing is imported until the
    /// user confirms what the preview showed them (G71 §4.3).
    private func pickForPreview() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json, .html, .commaSeparatedText, .zip]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "Select the export file to import"
        guard panel.runModal() == .OK, let url = panel.urls.first else { return }
        preview(url)
    }

    private func preview(_ url: URL) {
        stage = .parsing(url.lastPathComponent)
        Task {
            do {
                let result = try await APIClient.shared.previewSource(
                    fileURL: url, includeHistory: includeHistory)
                stage = ImportOverlayState.afterPreview(result, file: url)
            } catch {
                stage = .failed(Self.friendlyError(error))
            }
        }
    }

    /// Confirm re-posts the SAME file without the preview flag. Nothing is
    /// cached server-side: a preview that stages nothing must not stage bytes.
    private func confirmImport(_ url: URL) {
        stage = .importing
        Task {
            do {
                let response = try await APIClient.shared.uploadSource(fileURL: url)
                stage = .done(ImportOverlayState.summary(response))
                await store.refresh([.channels, .status, .sources])
            } catch {
                stage = .failed(Self.friendlyError(error))
            }
        }
    }
```

In `flow(for:)`, the four export-platform tiles become:

```swift
        case .instagram, .youtube, .tiktok, .linkedin:
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                WalkthroughPanel(vendors: tile.vendors, vendor: $vendor) { pickForPreview() }
                if tile == .tiktok {
                    Toggle("Also import browsing history (noisy)", isOn: $includeHistory)
                        .font(CicadaTheme.captionFont)
                        .accessibilityLabel("Also import TikTok browsing history")
                }
                ImportPreviewSection(stage: stage,
                                     onConfirm: { confirmImport($0) },
                                     onCancel: { stage = .idle })
            }
            .onDrop(of: [.fileURL], isTargeted: nil) { providers in
                guard let provider = providers.first else { return false }
                _ = provider.loadObject(ofClass: URL.self) { url, _ in
                    if let url { Task { @MainActor in preview(url) } }
                }
                return true
            }
```

and `collapse()` resets the machine:

```swift
    private func collapse() {
        expanded = nil
        stage = .idle
    }
```

- [ ] **Step 8: Cover the new copy in the copy test**

In `Tests/CicadaAppTests/CopyConstantsTests.swift`, append:

```swift
    /// G71 §4.2 — every export platform gets a written step path, and it lives
    /// in Copy so no view retypes it.
    func testEveryExportStepPathIsRoutedThroughCopy() {
        for vendor in WalkthroughVendor.allCases {
            XCTAssertEqual(vendor.stepPath, Copy.exportStepPath(vendor))
            XCTAssertFalse(Copy.exportStepPath(vendor).isEmpty)
        }
    }
```

- [ ] **Step 9: Run the app tests**

Run: `cd app/CicadaApp && swift test`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/UploadPreview.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/ImportOverlay.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/WalkthroughPanel.swift \
        app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift \
        app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift \
        app/CicadaApp/Tests/CicadaAppTests/ImportOverlayTests.swift \
        app/CicadaApp/Tests/CicadaAppTests/CopyConstantsTests.swift
git commit -m "$(cat <<'EOF'
feat(app): export overlay — step path, live parse preview, confirm, summary

G71 §4.2–4.3 — every export platform gets a one-line breadcrumb of exactly
where to click; a dropped file is parsed immediately by the staging-free
preview endpoint and rendered as a scrollable collection list with counts and
honest warnings; Confirm re-posts the same file and ends on "182 new · 32
already saved". An unrecognized file never offers a Confirm button.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 11: App — connect flows for Pinterest and Reddit

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/Connector.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/ConnectorSetupPanel.swift`
- Modify: `Sources/CicadaApp/Services/APIClient.swift` (connector methods)
- Modify: `Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift` (swap in the real panel)
- Modify: `Sources/CicadaApp/Theme/Copy.swift` (connector copy)
- Test: `Tests/CicadaAppTests/ConnectorSetupTests.swift` (new)

**Interfaces:**
- Consumes: `GET /sources/connectors`, `PUT|DELETE /sources/connectors/{id}/credentials`, `POST /sources/connectors/{id}/authorize`, `POST /sources/connectors/{id}/sync` (Task 8); `ImportPreviewSection`-free — this panel is independent of Task 10; `MockURLProtocol` (existing, `EntitySourceTests.swift`).
- Produces:
  - `struct ConnectorField: Codable, Hashable, Identifiable { let name, label: String; let secret, present: Bool; var id: String { name } }`
  - `struct ConnectorStatus: Codable, Identifiable, Hashable { let id, label: String; let connected: Bool; let fields: [ConnectorField]; let lastSync, lastError, detail: String?; let loginMode: String }` plus `var needsAuthorization: Bool` and `var isOAuth: Bool`
  - `struct ConnectorsResponse: Codable { let connectors: [ConnectorStatus] }`
  - `struct ConnectorAuthorizeResponse: Codable { let authorizeUrl: String; let state: String }`
  - `struct ConnectorSyncResult: Codable { let status: String; let reason: String?; let new: Int; let seen: Int; let error: String? }`
  - `enum ConnectorSetupState { static func stepLabel(_:) -> String; static func syncSummary(_:) -> String }`
  - `APIClient.fetchConnectors()`, `.saveConnectorCredentials(_:fields:)`, `.forgetConnector(_:)`, `.authorizeConnector(_:)`, `.syncConnector(_:)`

- [ ] **Step 1: Write the failing connector tests**

Create `app/CicadaApp/Tests/CicadaAppTests/ConnectorSetupTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G71 §2 — guided credential entry for the two direct-API connectors. The
/// panel never sees a credential value coming back: the backend reports only
/// whether each field is present.
final class ConnectorSetupTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Decoding

    func testConnectorStatusDecodesFieldsWithoutValues() throws {
        let json = """
        {"id": "pinterest", "label": "Pinterest", "connected": false,
         "fields": [{"name": "PINTEREST_APP_ID", "label": "App ID",
                     "secret": false, "present": true},
                    {"name": "PINTEREST_APP_SECRET", "label": "App secret",
                     "secret": true, "present": false}],
         "lastSync": null, "lastError": null, "detail": null,
         "loginMode": "oauth"}
        """.data(using: .utf8)!
        let status = try JSONDecoder().decode(ConnectorStatus.self, from: json)
        XCTAssertEqual(status.fields.count, 2)
        XCTAssertTrue(status.fields[0].present)
        XCTAssertTrue(status.fields[1].secret)
        XCTAssertTrue(status.isOAuth)
    }

    func testOAuthConnectorWithSavedAppButNoTokenStillNeedsAuthorization() throws {
        let status = ConnectorStatus(
            id: "pinterest", label: "Pinterest", connected: false,
            fields: [ConnectorField(name: "PINTEREST_APP_ID", label: "App ID",
                                    secret: false, present: true),
                     ConnectorField(name: "PINTEREST_APP_SECRET", label: "App secret",
                                    secret: true, present: true)],
            lastSync: nil, lastError: nil, detail: nil, loginMode: "oauth")
        XCTAssertTrue(status.needsAuthorization)
    }

    func testCredentialConnectorNeverNeedsAuthorization() {
        let status = ConnectorStatus(
            id: "reddit", label: "Reddit", connected: false, fields: [],
            lastSync: nil, lastError: nil, detail: nil, loginMode: "credentials")
        XCTAssertFalse(status.needsAuthorization)
        XCTAssertFalse(status.isOAuth)
    }

    // MARK: - Copy

    func testStepLabelWalksTheUserThroughTheOAuthFlow() {
        let unsaved = ConnectorStatus(
            id: "pinterest", label: "Pinterest", connected: false,
            fields: [ConnectorField(name: "PINTEREST_APP_ID", label: "App ID",
                                    secret: false, present: false)],
            lastSync: nil, lastError: nil, detail: nil, loginMode: "oauth")
        XCTAssertEqual(ConnectorSetupState.stepLabel(unsaved), "Step 1 of 2 — save your app keys")

        let saved = ConnectorStatus(
            id: "pinterest", label: "Pinterest", connected: false,
            fields: [ConnectorField(name: "PINTEREST_APP_ID", label: "App ID",
                                    secret: false, present: true)],
            lastSync: nil, lastError: nil, detail: nil, loginMode: "oauth")
        XCTAssertEqual(ConnectorSetupState.stepLabel(saved),
                       "Step 2 of 2 — authorize in your browser")

        let connected = ConnectorStatus(
            id: "pinterest", label: "Pinterest", connected: true, fields: [],
            lastSync: "2026-08-30T10:00:00Z", lastError: nil, detail: nil, loginMode: "oauth")
        XCTAssertEqual(ConnectorSetupState.stepLabel(connected), "Connected")
    }

    func testSyncSummaryReportsEachOutcomeHonestly() {
        XCTAssertEqual(
            ConnectorSetupState.syncSummary(
                ConnectorSyncResult(status: "ok", reason: nil, new: 12, seen: 40, error: nil)),
            "12 new · 40 seen")
        XCTAssertEqual(
            ConnectorSetupState.syncSummary(
                ConnectorSyncResult(status: "ok", reason: nil, new: 0, seen: 40, error: nil)),
            "Nothing new · 40 seen")
        XCTAssertEqual(
            ConnectorSetupState.syncSummary(
                ConnectorSyncResult(status: "skipped", reason: "not connected",
                                    new: 0, seen: 0, error: nil)),
            "Skipped — not connected")
        XCTAssertEqual(
            ConnectorSetupState.syncSummary(
                ConnectorSyncResult(status: "error", reason: nil, new: 0, seen: 0,
                                    error: "RuntimeError: 429 rate limited")),
            "Sync failed — RuntimeError: 429 rate limited")
    }

    // MARK: - Transport

    func testSaveCredentialsPutsTheFieldsAndDecodesTheStatus() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "PUT")
            XCTAssertEqual(request.url?.path, "/sources/connectors/reddit/credentials")
            let body = """
            {"id": "reddit", "label": "Reddit", "connected": true, "fields": [],
             "lastSync": null, "lastError": null, "detail": null,
             "loginMode": "credentials"}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let api = APIClient(session: MockURLProtocol.makeSession())
        let status = try await api.saveConnectorCredentials(
            "reddit", fields: ["REDDIT_CLIENT_ID": "client-id-placeholder"])
        XCTAssertTrue(status.connected)
    }

    func testAuthorizeReturnsTheVendorUrl() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/sources/connectors/pinterest/authorize")
            let body = #"{"authorizeUrl": "https://www.pinterest.com/oauth/?x=1", "state": "s"}"#
                .data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let api = APIClient(session: MockURLProtocol.makeSession())
        let result = try await api.authorizeConnector("pinterest")
        XCTAssertEqual(result.authorizeUrl, "https://www.pinterest.com/oauth/?x=1")
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd app/CicadaApp && swift test --filter ConnectorSetupTests`
Expected: FAIL to compile — `cannot find 'ConnectorStatus' in scope`.

- [ ] **Step 3: Add the models**

Create `Sources/CicadaApp/Models/Connector.swift`:

```swift
import Foundation

/// One credential a saved-content connector needs. `present` says whether it is
/// stored; the VALUE never crosses the wire in this direction — the backend has
/// no endpoint that returns it.
struct ConnectorField: Codable, Hashable, Identifiable {
    let name: String
    let label: String
    let secret: Bool
    let present: Bool

    var id: String { name }
}

/// A direct-API saved-content connector (G71 §2). Deliberately NOT a
/// `ConnectionStatus`: that type describes an LLM engine and feeds engine
/// selection, and a Pinterest account is not an engine.
struct ConnectorStatus: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let connected: Bool
    let fields: [ConnectorField]
    let lastSync: String?
    let lastError: String?
    let detail: String?
    /// "oauth" (save app keys, then authorize in a browser) or "credentials".
    let loginMode: String

    var isOAuth: Bool { loginMode == "oauth" }

    /// Keys are saved but no token has been granted yet — the state where the
    /// panel must show "Authorize in your browser", not "Save".
    var needsAuthorization: Bool {
        isOAuth && !connected && !fields.isEmpty && fields.allSatisfy(\.present)
    }
}

struct ConnectorsResponse: Codable {
    let connectors: [ConnectorStatus]
}

struct ConnectorAuthorizeResponse: Codable {
    let authorizeUrl: String
    let state: String
}

struct ConnectorSyncResult: Codable {
    let status: String
    let reason: String?
    let new: Int
    let seen: Int
    let error: String?
}
```

- [ ] **Step 4: Add the APIClient methods**

In `Services/APIClient.swift`, add a `// MARK: - Saved-content connectors (G71)` section:

```swift
    func fetchConnectors() async throws -> [ConnectorStatus] {
        let response: ConnectorsResponse = try await get("/sources/connectors")
        return response.connectors
    }

    func saveConnectorCredentials(
        _ id: String, fields: [String: String]
    ) async throws -> ConnectorStatus {
        try await put("/sources/connectors/\(id)/credentials", body: ["fields": fields])
    }

    func forgetConnector(_ id: String) async throws -> ConnectorStatus {
        try await delete("/sources/connectors/\(id)/credentials")
    }

    func authorizeConnector(_ id: String) async throws -> ConnectorAuthorizeResponse {
        try await post("/sources/connectors/\(id)/authorize")
    }

    func syncConnector(_ id: String) async throws -> ConnectorSyncResult {
        try await post("/sources/connectors/\(id)/sync")
    }
```

Use whichever private `get`/`put`/`post`/`delete` helpers the actor already exposes for the `/connections` methods (`setKey` uses `put(_:body:)`); if a JSON-body `put` with a nested dictionary is not available, encode `["fields": fields]` with the existing encoder the same way `setKey` does for `["key": key]`.

- [ ] **Step 5: Add the setup panel**

Create `Sources/CicadaApp/Views/Capture/Sheets/ConnectorSetupPanel.swift`:

```swift
import AppKit
import SwiftUI

/// The pure copy decisions, hoisted so they are testable without SwiftUI.
enum ConnectorSetupState {

    /// Where the user is in a two-step OAuth setup, or "Connected".
    static func stepLabel(_ status: ConnectorStatus) -> String {
        if status.connected { return "Connected" }
        guard status.isOAuth else { return "Enter your app credentials" }
        let allPresent = !status.fields.isEmpty && status.fields.allSatisfy(\.present)
        return allPresent
            ? "Step 2 of 2 — authorize in your browser"
            : "Step 1 of 2 — save your app keys"
    }

    /// What a "Sync now" press actually did — never a bare "done".
    static func syncSummary(_ result: ConnectorSyncResult) -> String {
        switch result.status {
        case "ok":
            let newPart = result.new == 0 ? "Nothing new" : "\(result.new) new"
            return "\(newPart) · \(result.seen) seen"
        case "skipped":
            return "Skipped — \(result.reason ?? "nothing to do")"
        default:
            return "Sync failed — \(result.error ?? "unknown error")"
        }
    }
}

/// Guided credential entry + status for one direct-API connector (G71 §2).
struct ConnectorSetupPanel: View {
    let connectorId: String
    /// Non-empty for Reddit, whose GDPR export backfills past the API's
    /// ~1,000-item listing cap; empty for Pinterest.
    let vendors: [WalkthroughVendor]
    @Binding var vendor: WalkthroughVendor

    @State private var status: ConnectorStatus?
    @State private var drafts: [String: String] = [:]
    @State private var busy = false
    @State private var message: String?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if let status {
                Text(ConnectorSetupState.stepLabel(status))
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)

                if let detail = status.detail ?? status.lastError {
                    Text(detail)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(status.lastError == nil
                                         ? CicadaTheme.textSecondary : CicadaTheme.danger)
                }

                if status.connected {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Button("Sync now") { Task { await syncNow() } }
                            .buttonStyle(.borderedProminent)
                            .disabled(busy)
                        Button("Disconnect", role: .destructive) { Task { await disconnect() } }
                            .buttonStyle(.bordered)
                            .disabled(busy)
                    }
                } else {
                    ForEach(status.fields) { field in
                        credentialRow(field)
                    }
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Button("Save") { Task { await save() } }
                            .buttonStyle(.bordered)
                            .disabled(busy || drafts.values.allSatisfy { $0.isEmpty })
                        if status.needsAuthorization {
                            Button("Authorize in your browser") { Task { await authorize() } }
                                .buttonStyle(.borderedProminent)
                                .disabled(busy)
                                .accessibilityLabel("Authorize Cicada with \(status.label)")
                        }
                    }
                }
            } else {
                ProgressView().controlSize(.small)
            }

            if !vendors.isEmpty {
                Divider().background(CicadaTheme.border)
                Text(Copy.connectorExportBackfill)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                WalkthroughPanel(vendors: vendors, vendor: $vendor) {}
            }

            if let message {
                Text(message).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.success)
            }
            if let error {
                Text(error).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
            }
        }
        .task { await load() }
    }

    @ViewBuilder
    private func credentialRow(_ field: ConnectorField) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(field.label)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: 120, alignment: .leading)
            if field.secret {
                SecureField(field.present ? "Saved — paste to replace" : "Paste value",
                            text: binding(for: field))
                    .textFieldStyle(.roundedBorder)
            } else {
                TextField(field.present ? "Saved — type to replace" : "Paste value",
                          text: binding(for: field))
                    .textFieldStyle(.roundedBorder)
            }
        }
        .accessibilityLabel("\(field.label), \(field.present ? "saved" : "not saved")")
    }

    private func binding(for field: ConnectorField) -> Binding<String> {
        Binding(get: { drafts[field.name] ?? "" },
                set: { drafts[field.name] = $0 })
    }

    private func load() async {
        do {
            let all = try await APIClient.shared.fetchConnectors()
            status = all.first { $0.id == connectorId }
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }

    private func save() async {
        busy = true
        defer { busy = false }
        let filled = drafts.filter { !$0.value.trimmingCharacters(in: .whitespaces).isEmpty }
        guard !filled.isEmpty else { return }
        do {
            status = try await APIClient.shared.saveConnectorCredentials(connectorId, fields: filled)
            drafts = [:]
            message = "Saved."
            error = nil
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }

    private func authorize() async {
        busy = true
        defer { busy = false }
        do {
            let result = try await APIClient.shared.authorizeConnector(connectorId)
            if let url = URL(string: result.authorizeUrl) { NSWorkspace.shared.open(url) }
            message = Copy.connectorAuthorizeHint
            error = nil
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }

    private func syncNow() async {
        busy = true
        defer { busy = false }
        do {
            message = ConnectorSetupState.syncSummary(
                try await APIClient.shared.syncConnector(connectorId))
            error = nil
            await load()
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }

    private func disconnect() async {
        busy = true
        defer { busy = false }
        do {
            status = try await APIClient.shared.forgetConnector(connectorId)
            message = "Disconnected."
            error = nil
        } catch {
            self.error = AddSourceSheet.friendlyError(error)
        }
    }
}
```

- [ ] **Step 6: Add the connector copy**

In `Theme/Copy.swift`, add under a `// MARK: - Connectors (G71 §2)` heading:

```swift
    /// Shown after the browser is handed the consent URL — the callback lands
    /// back on the local backend, so there is nothing to paste back.
    static let connectorAuthorizeHint =
        "Approve it in the browser tab, then come back — Cicada finishes on its own."

    /// Why a Connect-route tile still offers an export walkthrough.
    static let connectorExportBackfill =
        "The API only reaches your most recent ~1,000 saves. A one-off data "
        + "export backfills everything older."
```

- [ ] **Step 7: Swap the real panel into the sheet**

In `AddSourceSheet.flow(for:)`, replace the Task-9 placeholder arm with:

```swift
        case .pinterest, .reddit:
            ConnectorSetupPanel(connectorId: tile.rawValue, vendors: tile.vendors, vendor: $vendor)
```

- [ ] **Step 8: Run the app tests**

Run: `cd app/CicadaApp && swift test`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/Connector.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/ConnectorSetupPanel.swift \
        app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/AddSourceSheet.swift \
        app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift \
        app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift \
        app/CicadaApp/Tests/CicadaAppTests/ConnectorSetupTests.swift
git commit -m "$(cat <<'EOF'
feat(app): guided connect flows for Pinterest and Reddit

G71 §2 — a two-step OAuth panel for Pinterest (save app keys, then authorize
in the user's own browser; the callback lands on the local backend so there
is nothing to paste back) and one-step credential entry for Reddit's script
app. Field values are write-only: the panel only ever learns whether each is
present. Sync now reports what it actually did, failures included.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 12: Docs — CLAUDE.md endpoints/channels + the G71 backlog row

**Files:**
- Modify: `CLAUDE.md` (API Design endpoint list; Storage Layer secrets note; MVP §5 conversation upload)
- Modify: `docs/goals/memory-evolution.md:591` (G71 status)

**Interfaces:**
- Consumes: everything Tasks 1–11 produced.
- Produces: no code.

- [ ] **Step 1: Document the new endpoints**

In `CLAUDE.md`'s API Design code block, add after the `POST /sources/save, ...` group:

```
POST /sources/upload?preview=true         → parse an export WITHOUT staging anything:
                                            {recognized, platform, total,
                                             collections:[{name,kind,count}], warnings}
                                            (+ ?include_history=true opts TikTok browsing history in)
GET  /sources/connectors                  → Pinterest/Reddit status (fields present, never values)
PUT/DELETE /sources/connectors/{id}/credentials → store/forget creds in ~/.cicada/secrets.env (0600)
POST /sources/connectors/{id}/authorize   → mint the vendor consent URL (Pinterest; single-use state)
GET  /sources/connectors/pinterest/callback → OAuth redirect target (the only new auth-exempt route)
POST /sources/connectors/{id}/sync        → run one poll now
```

and update the router count sentence from "19 routers currently mounted" to "20 routers currently mounted", adding `connectors` to the parenthesised list.

Update the auth paragraph's exemption sentence to:

> Every endpoint except `GET /healthz`, `POST /capture/telegram` and
> `GET /sources/connectors/pinterest/callback` requires `Authorization: Bearer <token>`
> … The Pinterest callback is exempt because the user's browser follows the redirect
> and cannot send the header; it is gated instead by a single-use, ten-minute `state`
> nonce minted by `POST /sources/connectors/{id}/authorize`.

- [ ] **Step 2: Document the capture channels and connectors**

In `CLAUDE.md`'s Awake Cycle "Input sources" list, extend the `Ingested sources` bullet and add:

```markdown
- **Direct saved-content connectors** (G71): **Pinterest** (v5, BYO OAuth app, `boards:read`/`pins:read`
  — board name becomes the item folder) and **Reddit** (script app, `/user/{me}/saved`, newest-first to
  the previously-seen fullname; the GDPR `saved_posts.csv` export backfills past the ~1,000-item listing
  cap). Credentials live in `~/.cicada/secrets.env` (0600), never in a bank. Polled at the tail of every
  Sleep cycle (including an idle one) and on demand via `POST /sources/connectors/{id}/sync`; both are
  gated by `CICADA_ALLOW_CONNECTOR_FETCH=1` so the test suite and an unconfigured install never reach
  the network. A failed poll is recorded per-channel (`sync_state.record_error`) and surfaces on
  `GET /sources/channels` as `lastError` — never as a stale success.
- **Export parsers** (`media_ingestor.parse_upload`): Instagram saved, Google Takeout (JSON/CSV/zip),
  Chrome/Safari bookmarks, **LinkedIn saved items** (URL + date only — §8.2 bans fetching post bodies,
  so these stay thin), **TikTok favourites/likes** (`origin: tiktok-saved`; Browsing History is opt-in
  and keeps a distinct `tiktok-history` origin), and the **Reddit GDPR export**. Non-Takeout archives
  must be unzipped first — the app's step-path copy says so and the preview reports it.
```

In the `GET /sources/channels` description, note that `CHANNEL_IDS` is now
`chat-export:claude, chat-export:chatgpt, bookmarks, notes, rss, calendar, pinterest, reddit, telegram, files`.

- [ ] **Step 3: Document the `saved-because` claim**

In `CLAUDE.md`'s "Fact sources (G61)" section, add a short sibling paragraph:

```markdown
### Save-with-reason (G71)
A Telegram `/save <url> <reason…>` writes the reason twice: verbatim as a
`## Saved because` section on the media episode (so Stage-1 extraction mines its
concepts exactly as it would conversation text), and as a `saved-because` claim on
the media entity — `observer: rodrigo`, `source_trust: user_stated`,
`object_kind: literal`, `origin: telegram`. `literal` keeps it out of the graph:
Stage 5.7 projects only node-object claims into edges. `telegram` is deliberately
**not** in `claim_reconciler._HUMAN_ORIGINS`, so the claim reads as user-stated
without inheriting manual-edit overwrite protection — a bot webhook is not an
authenticated manual-assertion channel. `agentic_write.write_claim` gained an
optional `origin=` for exactly this; omitting it is unchanged.
```

- [ ] **Step 4: Update the backlog row honestly**

In `docs/goals/memory-evolution.md`, change the G71 row's status cell from `🔲 spec ready` to:

```
✅ shipped 2026-08-31 — Telegram save-with-reason + `saved-because` claim; staging-free `?preview=true`
with per-collection counts; LinkedIn/TikTok/Reddit-GDPR parsers; Pinterest + Reddit connectors (channels
rows, per-channel failure surfacing, Sleep-tail poll); Imports catalog with route badges; export overlay
with breadcrumb step paths and live preview→confirm→dedup summary; guided connect flows. **Partial /
deferred:** walkthrough VIDEOS are still absent (`Resources/walkthroughs/` is empty — every vendor renders
the "coming soon" placeholder; G64); non-Takeout export ZIPs are not walked, so IG/TikTok/LinkedIn/Reddit
archives must be unzipped first; Pinterest scope strings and Trial-tier read-of-existing-boards are still
**unverified against the live API** (G69 flagged this — the official scopes page 404'd during research),
as are Reddit's rate limits, which came from secondary sources; TikTok oEmbed title fill is not attempted,
so TikTok items land with slug titles; the Reddit GDPR export is not hydrated via `/api/info` (the existing
OpenGraph enrichment covers it online and degrades to the permalink slug offline). YouTube Watch Later
browser read and Google Data Portability stay out of scope, as specified.
```

- [ ] **Step 5: Verify both suites one last time**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Run: `cd app/CicadaApp && swift test`
Expected: PASS on both.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/goals/memory-evolution.md
git commit -m "$(cat <<'EOF'
docs: G71 saves-and-imports — endpoints, channels, saved-because; row shipped

Records the new /sources/connectors surface and the preview mode, the two
direct connectors and three export parsers, and the saved-because claim's
deliberate origin choice. The backlog row lists what actually shipped and
what stayed partial (no walkthrough videos, no multi-platform zips,
unverified Pinterest scopes / Reddit limits).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Self-Review

**Spec coverage.** §1 save-with-reason → Task 1 (episode body, `saved-because` claim, ACK echo).
§2 Pinterest → Task 6; Reddit API → Task 7; both in `/sources/channels` with credentials in
`secrets.env` and per-channel failure surfacing → Task 8; the Reddit GDPR-export backfill parser
→ Task 5. §3 LinkedIn → Task 3; TikTok (+ history checkbox, default off) → Task 4; both registered
in `parse_upload`'s sniffing → Tasks 3–4. §4.1 platform catalog with Connect/Import-file badges and
channel-derived state → Task 9. §4.2 walkthrough overlay: video slot + deep-link button survive
unchanged, breadcrumb step path per platform added in `Copy`, drop target reused → Tasks 9–10.
§4.3 real-time preview endpoint, live collection list, Confirm, dedup summary → Tasks 2 and 10.
§5 relationship derivation → no task by design: every connector and parser emits `RawItem`s into
the existing `ingest_batch` path, and the only addition (§1's claim) is Task 1. §6 out-of-scope
items are built by no task and are named in Task 12's honest-partials list. §7 testing → each task
carries its own pytest/XCTest steps; zero-network and synthetic-fixture rules are Global Constraints.

**Placeholder scan.** One forward reference is deliberate and bounded: Task 9 Step 7 names
`ConnectorSetupPanel` (Task 11) and gives the exact two-line stand-in that keeps the tree building
until Task 11 swaps it. Every other step carries real code. No "TBD", no "add error handling",
no "similar to Task N".

**Type consistency.** `RawItem.reason` (Task 1) is read by `_episode_body`/`write_media_episode`
(Task 1) and written only by `telegram_capture._default_save_url` (Task 1). The connectors
deliberately set `note`, not `reason`: a Pinterest pin description is the platform's text, not the
user's stated reason for saving, and conflating them would put a stranger's words into a
`saved-because` claim. `write_claim(..., origin=)` (Task 1)
is called only by `telegram_capture._write_saved_because_claim` (Task 1). `PLATFORM_BY_LABEL` /
`COLLECTION_KIND_BY_PLATFORM` are created in Task 2 and each of Tasks 3–5 adds exactly one entry,
matching the source labels those tasks return (`"LinkedIn Saved"`, `"TikTok Export"`,
`"Reddit Saved Export"`). `sync_state.record_sync(..., extra=)` / `record_error` (Task 6) are
consumed by `reddit.sync` (Task 7), `channel_registry._connector_channel` (Task 8) and
`connectors_router._status` (Task 8). `build_channels(..., connectors_connected=)` (Task 8) is
called only from `sources.list_source_channels` (Task 8). `SourceChannel.last_error` (Task 8,
Python) decodes to `SourceChannel.lastError` (Task 9, Swift) and is read by
`AddSourceTile.tileState` (Task 9). `UploadPreview`/`UploadCollection` (Task 10, Swift) mirror
`SourceUploadPreview`/`SourceUploadCollection` (Task 2, Python) field for field.
`ConnectorStatus.loginMode` (Task 11, Swift) mirrors `ConnectorStatus.login_mode` (Task 8, Python)
and takes only the two values `LOGIN_MODES` assigns.
