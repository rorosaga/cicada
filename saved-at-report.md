# G99d — plumb `RawItem.added` end to end

## Summary

`RawItem.added` was set by five parsers and read by nothing, so every
ingested item recorded only its *ingest* timestamp. This lands the missing
other half: a small normalizer that converts each source's date format to an
ISO date, frontmatter fields on the episode and entity that persist it,
threading through the `MediaSourceItem` wire model, and recency-sort logic
(both `GET /sources` and the SwiftUI Feed's Recent toggle) that prefers it.

## Naming decision (read this before the diff)

`MediaSourceItem.saved_at` / the entity's nested `media.saved_at` /
`url_index.json`'s `saved_at` key were **already** using the name "saved_at"
— but for the *ingest* timestamp, not the user's true save date (exactly the
bug this task fixes). Renaming that field under existing readers felt like
the wrong kind of "fix," so I left every existing field's name and meaning
untouched and added a **new, distinctly-named** field everywhere a collision
would otherwise occur:

- Episode frontmatter: new top-level `saved_at:` (no collision — episodes
  never had this key).
- Entity frontmatter: new top-level `saved_at:` (no collision — only the
  *nested* `media.saved_at` existed, and it keeps its old ingest-time
  meaning unchanged).
- `url_index.json` per-entry dict: new `content_saved_at` key (the existing
  `saved_at` key stays the ingest timestamp, unchanged).
- `MediaSourceItem` wire model / Swift `MediaFeedItem`: new
  `content_saved_at` / `contentSavedAt` field (the existing `saved_at` /
  `savedAt` stays as-is). A `recencyKey` helper (Swift) and a `_recency_key`
  helper (Python) compute `content_saved_at or saved_at` wherever recency
  sorting happens.

Net effect: fully additive at every layer, zero renames, zero risk to
existing consumers (verified: old `RawItem(...)` callers with no `added`
produce byte-identical frontmatter to before — see
`test_write_media_episode_without_added_is_byte_identical_to_before` /
`test_write_media_entity_without_added_is_byte_identical_to_before`).

## What was built

1. **`api/services/saved_at.py`** (new) — five pure, hermetic functions:
   `from_netscape_epoch` (Unix epoch seconds, as a string),
   `from_webkit_micros` (Chrome's microseconds-since-1601 epoch),
   `from_iso8601` (Takeout's ISO-8601 `time`), `from_tiktok`
   (`"YYYY-MM-DD HH:MM:SS"`), `from_freeform` (LinkedIn's drifting
   column — tries ISO-8601 then a handful of concrete US/date shapes).
   Every function returns an ISO `YYYY-MM-DD` string or `None` — never a
   guess. A "sane range" check (year ≥ 2000, ≤ 1 day past now) catches
   parse/scale errors (e.g. seconds misread as microseconds) rather than
   silently emitting a bogus 1970 or 1601 date.

2. **Wired into all five call sites** named in the brief:
   `parse_netscape_bookmarks` (`add_date`), `parse_chrome_bookmarks_json`
   (`date_added`), `parse_youtube_takeout` (`time`), `parse_tiktok_export`
   (`Date`), `parse_linkedin_saved` (its date column). `RawItem.added` is now
   contractually "already normalized ISO date or None" — documented on the
   dataclass field.

3. **Persisted**:
   - `write_media_episode`: `frontmatter["saved_at"]` when `item.added` is
     truthy; episode body gets an `**Originally saved:**` line when it
     differs from the ingest date (never redundant with `**Saved:**`).
   - `write_media_entity`: top-level `frontmatter["saved_at"]` when
     `item.added` is truthy. The pre-existing nested `media.saved_at`
     (ingest time) is untouched.
   - `ingest_one`: `idx[h]["content_saved_at"]` in `url_index.json` when
     `item.added` is truthy.

4. **Wired to the wire model**: `MediaSourceItem.content_saved_at:
   Optional[str]` (near the existing 13 fields), populated in
   `GET /sources` from `url_index.json`'s new key. Swift's `MediaFeedItem`
   gained the matching `contentSavedAt: String?` + a `recencyKey` computed
   property.

5. **Sort correctness**: `GET /sources` (`sort=recent` and `sort=relevance`'s
   tiebreak) and the SwiftUI `FeedViewModel.recent` case now sort on
   `content_saved_at or saved_at` instead of `saved_at` alone.

## Backfill: what fraction is recoverable

**0%.** I checked every place a true save date could plausibly survive for
the 789 already-ingested items in the live `claude-chats` bank:

- `memory/banks/claude-chats/sources/url_index.json` — every entry's
  `saved_at` is clustered on `2026-07-13T21:40:3x…Z` (the import run), no
  other date field.
- The episode files themselves (`memory/banks/claude-chats/episodes/
  ep_2026-07-13_*.md`, 981 of them) — body only ever says `**Saved:**
  2026-07-13`, i.e. the ingest date; no raw `add_date`/`date_added` was ever
  captured to disk.
- `~/Library/Application Support/Cicada/upload_history.json` — logs
  conversation-export uploads only, no entry for the July 13 bookmark
  import, no retained filename.
- No original bookmark export file (Chrome/Safari `Bookmarks.plist`/`.html`)
  survives on disk in `~/Downloads` or `~/Desktop`.

The original `add_date`/`date_added` values were parsed transiently by the
old code and discarded at ingest time — nothing persisted them anywhere, and
the source export itself isn't retained. There is nothing left to recover;
per the brief, I did not invent a value. Every one of the 789 existing items
keeps `saved_at` absent (both at the entity/episode-frontmatter level and in
`url_index.json`'s new `content_saved_at` key) — they'll keep sorting by
their ingest timestamp, exactly as before. Only **newly ingested** items
(fresh Chrome/Safari/Takeout/TikTok/LinkedIn imports from here on) will
carry a real `saved_at` when the source format allows it.

## Did Feed ordering change?

**For the live bank today: no** — 0% of the 789 existing items have a
recoverable `saved_at`, so `content_saved_at or saved_at` collapses to the
same `saved_at` (ingest timestamp) they already sort on; the default "recent"
order is unchanged until a fresh import lands.

**Going forward: yes, and that's the point** — added
`test_get_sources_recent_sort_prefers_content_saved_at` (Python) and
`testRecentSortPrefersContentSavedAtOverIngestTimestamp` (Swift) both prove
that an item with an old true save date now sorts *after* an item with no
recoverable date but a more recent ingest time — i.e. a fresh bulk
re-import of an old bookmark export will scatter across the Feed by real
save date instead of clustering at "just now."

## Scope notes

- Only the five parsers named in the brief were touched. Instagram's export
  actually carries a per-record `timestamp` under `string_map_data["Saved
  on"]` (visible in `parse_instagram_saved`'s own docstring) that is
  similarly discarded today — a real, adjacent instance of the same bug
  class, but outside the five sites the brief scoped and verified via grep.
  Flagging it, not fixing it here.
- `GET /entities/{id}` (`EntityResponse`) was not extended with an explicit
  `saved_at` field — the brief's wiring chain stops at `MediaSourceItem` /
  `GET /sources`, and the entity's raw frontmatter (including the new
  `saved_at:` key) is already visible via `raw_markdown` on that endpoint.
- G99e (filtered-KNN / vector-index metadata columns) was explicitly not
  attempted, per the brief.

## Gate

- `api/.venv/bin/python -m pytest api/tests`: **1405 passed, 8 failed** — the
  8 failures are exactly the pre-existing `test_calendar_registry.py` baseline
  named in the brief (unrelated date-dependent ICS-polling tests; this branch
  never touches `calendar_registry.py`).
- `swift build`: clean. `swift test`: **394 passed, 0 failed** (includes 2 new
  `FeedIdentityTests` cases).
- New test files: `api/tests/test_saved_at.py` (26 tests, one-per-format plus
  edge cases for the normalizer), plus new cases added to
  `api/tests/test_sources.py` (episode/entity/url_index wiring, sort
  correctness) and `api/tests/test_export_parsers.py` (two existing
  assertions updated for the now-normalized `.added` value).

## Files touched

- `api/services/saved_at.py` (new)
- `api/tests/test_saved_at.py` (new)
- `api/services/media_ingestor.py`
- `api/models/schemas.py`
- `api/routers/sources.py`
- `api/tests/test_sources.py`
- `api/tests/test_export_parsers.py`
- `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift`
- `app/CicadaApp/Sources/CicadaApp/ViewModels/FeedViewModel.swift`
- `app/CicadaApp/Tests/CicadaAppTests/FeedIdentityTests.swift`
