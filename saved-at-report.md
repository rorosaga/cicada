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
  `savedAt` stays as-is). A `recencyDate` computed property (Swift) and a
  `_recency_key` helper (Python) compute `content_saved_at or saved_at`,
  parsed to a real instant via `saved_at.sort_instant` (Python) /
  `MediaFeedItem.parseRecencyInstant` (Swift) — see "Review round" below —
  wherever recency sorting happens.

A single doc anchor enumerating all four things named `saved_at` (the two
pre-existing ingest-time fields plus these two new ones) lives at the top of
`api/services/saved_at.py`.

Net effect: fully additive at every layer, zero renames, zero risk to
existing consumers (verified: old `RawItem(...)` callers with no `added`
produce no new key/line — see
`test_write_media_episode_without_added_omits_the_new_saved_at_field` /
`test_write_media_entity_without_added_omits_the_new_top_level_saved_at_field`).

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
   gained the matching `contentSavedAt: String?` + a `recencyDate` computed
   property.

5. **Sort correctness**: `GET /sources` (`sort=recent` and `sort=relevance`'s
   tiebreak) and the SwiftUI `FeedViewModel.recent` case now sort on
   `content_saved_at or saved_at` instead of `saved_at` alone, both parsed to
   a real instant (`saved_at.sort_instant` / `recencyDate`) rather than
   compared as raw strings — see "Review round" below.

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

## Review round (Spec ✅ / Ready, 3 Low findings — all closed)

1. **Same-day sort tie-break was string-length-accidental, not deterministic.**
   `_recency_key` (Python) / `recencyKey` (Swift) compared `content_saved_at`
   (bare `YYYY-MM-DD`) against `saved_at` (full `…T…Z`) as raw strings; on the
   same calendar day the bare date sorts as "less than" the full timestamp
   purely because it's a shorter, equal-prefix string. Fixed by adding
   `saved_at.sort_instant` (Python) and `MediaFeedItem.recencyDate` /
   `parseRecencyInstant` (Swift, mirroring the existing
   `SourceChannel.lastSyncDate` three-shape parser) — both parse to a real,
   timezone-aware instant, anchoring a bare date to 00:00:00 UTC (documented
   as the deliberate rule: "start of that day," so same-day ties still land
   the same way, now on purpose rather than by string-length accident). New
   tests with one bare-date item and one full-timestamp item on the SAME
   day: `test_sort_instant_bare_date_and_same_day_full_timestamp_are_deterministic`
   + `test_get_sources_recent_sort_same_day_bare_date_vs_full_timestamp_is_deterministic`
   (Python), `testRecencyDateBareDateAndFullTimestampOnTheSameDaySortDeterministically`
   (Swift).
2. **Overstated test name.** Renamed
   `test_write_media_episode_without_added_is_byte_identical_to_before` →
   `test_write_media_episode_without_added_omits_the_new_saved_at_field`, and
   the entity equivalent → `..._omits_the_new_top_level_saved_at_field`.
   Docstrings now say plainly that these prove key/line absence, not a
   byte-for-byte comparison against a pre-branch fixture (none exists).
3. **Backlog row not marked shipped.** Updated the G99 row's G99d clause in
   `docs/goals/memory-evolution.md` to "shipped," including the 0%-recoverable
   finding, so a future reader doesn't re-open a fixed problem.

Also added, per the reviewer's request: a single doc anchor at the top of
`api/services/saved_at.py` enumerating the four things named `saved_at`
side by side (the two pre-existing ingest-time fields — `url_index.json`'s
`saved_at` key and the entity's nested `media.saved_at` — versus the two new
recovered-true-date fields — episode/entity top-level `saved_at`), so the
naming asymmetry is discoverable at the one place already referenced by
every per-site comment, instead of scattered.

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

- `api/.venv/bin/python -m pytest api/tests`: **1411 passed, 8 failed** — the
  8 failures are exactly the pre-existing `test_calendar_registry.py` baseline
  named in the brief (unrelated date-dependent ICS-polling tests; this branch
  never touches `calendar_registry.py`).
- `swift build`: clean. `swift test`: **395 passed, 0 failed**.
- New test files: `api/tests/test_saved_at.py` (31 tests: one-per-format
  normalizer coverage plus `sort_instant`'s same-day determinism), plus new
  cases in `api/tests/test_sources.py` (episode/entity/url_index wiring, sort
  correctness incl. the same-day mixed-format case) and
  `api/tests/test_export_parsers.py` (two existing assertions updated for the
  now-normalized `.added` value). Swift: `FeedIdentityTests.swift` gained the
  `recencyDate` + same-day determinism cases.

## Files touched

- `api/services/saved_at.py` (new)
- `api/tests/test_saved_at.py` (new)
- `api/services/media_ingestor.py`
- `api/models/schemas.py`
- `api/routers/sources.py`
- `api/tests/test_sources.py`
- `api/tests/test_export_parsers.py`
- `docs/goals/memory-evolution.md`
- `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift`
- `app/CicadaApp/Sources/CicadaApp/ViewModels/FeedViewModel.swift`
- `app/CicadaApp/Tests/CicadaAppTests/FeedIdentityTests.swift`
