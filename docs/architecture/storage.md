# Storage, claims, provenance and git

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

### Markdown, not a database
Wikilinked `.md` files with YAML frontmatter, git-versioned. **The filesystem is the single source
of truth** — the API reads and writes the same files the Sleep cycle does. At personal scale
(hundreds of entities) the LLM follows wikilinks; it doesn't need Cypher. Zero infrastructure,
human-readable, portable, Obsidian-compatible.

**Every page write is atomic** (audit 2026-10-02 A02): `markdown_parser.write` stages the whole
document in a hidden sibling `.<name>.<random>.tmp` (never matched by a `*.md` scan), fsyncs it and
`os.replace`s it over the page, keeping the page's permission bits and writing through a symlink to
its target. A failed write leaves the old page byte-for-byte and removes the temp file. The
directory is not fsynced: the guarantee is "never a torn or empty page", not "the rename survives a
power cut". `markdown_parser.write_new` creates a page without ever replacing one (a hard link of the
staged file, `FileExistsError` if the name is taken) — what new episodes use (K01, below).

**A bank's boundary is its directory** (audit 2026-10-02 A04): exporting (`bank_registry.export_zip`) and
duplicating (`duplicate_bank`) a bank never follow or copy a symlink, at any depth and whatever it points at, so a
link inside a bank can never pull a file from outside it into an archive or a copy.

**An episode's two dates** (TODO ruling 39, owner 2026-10-24). `timestamp` is the item's own date where its source
gives one (published, created, sent, saved, happened) and `received_at` is when Cicada received it, aware UTC, written
once when the file is created (`episode_ids.create_episode` → `stamp_received`, right after `timestamp`; `turns` stays
the last key) and kept by every later edit. Both sit in the frontmatter, outside the content hash, so no G118 span
moves. A feed item also records `published_at` (its `timestamp`'s source) and its url-index entry keeps it beside the
ingest stamp `saved_at`; a save keeps `saved_at` / `added_at` as before. Episodes from before the ruling have no
`received_at`: unknown, never inferred (`capture-and-sleep.md`, "Both dates on every episode").

### Entity schema

```yaml
---
type: person | project | company | concept | tool | deadline | skill | location | media | directory
status: active | decaying | archived | dropped
confidence: 0.85
created: 2026-01-10
last_referenced: 2026-03-22  # when it was last said (a conversation's date, not the day Cicada read it)
decayed_through: 2026-03-29  # silence charged through this day (TODO ruling 1)
learned_on: 2026-03-29     # the day Cicada read the last mention; age counts from when it was said (capture-and-sleep.md)
faded_by_age: 2026-03-29   # only when its own age took it below 0.4: fades and archives without a question
read_late: 2026-03-20      # only between a late read and the decay pass that places it on its day (read on time)
decay_rate: 0.05           # per-entity, not global
decay_class: active        # evergreen | durable | active | volatile (G66)
source_episodes: [ep_2026-01-10_001]
tags: []                   # open set, freeform; never a saved list's name (that is `folder:` / `collections:`)
related: []                # duplicates wikilinks for programmatic access
version: 3
claims_ledger: {claims: 5835, hash: 1a2b3c4d5e6f}  # only on a page whose older claims live in its ledger
---
```

**Entity types are a closed set of 10** (`api/models/schemas.py::EntityType`): `person`, `project`,
`company`, `concept`, `tool`, `deadline`, `skill` (procedural memory / preferences), `location`,
`media` (ingested item with an agent-generated summary), `directory` (a filesystem path, split out
from `location` in G18).

**The set is held where a type comes from a model (2026-10-17).** A plain-JSON engine is held only by the
extraction prompt's list, and a model's `organization`, `product` or `program` once reached a page unchanged.
`entity_types.producible` is the one coercion (`organization` → `company`, `product` → `tool`, `program` → `project`,
an unknown word → `concept`), applied at extraction (`entity_extractor.sanitize_entity_type`); where a page is born
from a model's word (the Sleep create branch, an inbox answer that creates a page) `entity_types.in_set` keeps any of
the 10 and maps only a word outside them — the decay-class rail's two places. A bank with pages from before is repaired by the person: `python -m api.scripts.repair_entity_types
--bank <path>` (dry run, counts and type words only; `--list` adds page ids for their own terminal; `--apply` one
`cicada` commit, `maintenance/entity-types`; `--as <id>=<type>` overrides the mapping for one page). Only `type`
changes; a page dirty in git is skipped; it refuses while Sleep runs.

**Two exclusions matter (G17).** `deadline` still renders for legacy pages but is **no longer
produced by Stage-1 extraction** — `PRODUCIBLE_ENTITY_TYPES` excludes it; due-dates attach as a
`due` claim on the relevant project instead of spawning a standalone entity. `media` is likewise
excluded — it comes from the ingestion path, not conversation extraction.

**A saved list is provenance, never a tag or a hub (owner 2026-10-19: "the video was taken from this playlist and that's
it … a property of the markdown").** A media page records every list it was saved from — a YouTube playlist (Watch
later included), an Instagram collection, a Pinterest board, a Reddit subreddit or saved list, an X or LinkedIn
export's list, a browser bookmark folder, a device's Safari tabs — as `collections:` (in the order it was saved from
them) with the first also its `folder:` (every older reader, the Sources page's grouping among them, knows only
`folder:`; a page from before `collections:` holds its `folder:` alone, `id_utils.page_lists`). A later save of the
same URL from another list — a second playlist in the same export, a re-import, the person's agent reading Watch
later — appends that list through `media_ingestor.add_collection` (and makes it the `folder:` of a page that had
none). A batch's repeats are appended after its new pages commit, in one admitted transaction
(`append_collections`: write admission, then the page lock, through their own `user` commit, 500 pages a commit, off
the event loop); while Sleep holds the pages nothing is appended and the next import or sync derives it again. The
agent's Watch later read appends inside its own admission and page lock. A list the page already holds changes
nothing.

**Provenance never makes a hub.** Stage 5.6 makes any tag shared by `hub_tag_min_members` (5) active pages a
`topic-<tag>` hub with a `member of` edge to each, and the media writer used to put `sanitize_id(folder)` in `tags`
(the Netscape parser the raw folder name), beside the media type and the capture door's origin — so every list,
media type and door with enough saves became a hub. `id_utils.provenance_tags` names those tags: a page's list tags
(`list_tags`: the raw name and slug of each of its lists), and on a `media` page its `media.media_type`,
`media.kind`, `origin:` and a door's stamp (`<browser>-bookmark`, `bookmark`, `safari-tab`) — each repeats a field
the page holds. `write_media_entity` no longer writes list tags; media-type and origin tags stay on the page (readers
filter by them), but the hub tier (`hub_builder._topic_tags`) gathers no page by any provenance tag, so a bank's list
and provenance hubs go at its next Sleep. A tag the person or Sleep wrote for meaning — any tag on a non-media page,
any other tag on a media one — still makes its hub. An existing bank is repaired by `python -m
api.scripts.repair_list_hubs --bank <path>` (dry run: counts only — pages to untag, tag hubs on disk, and those the
regenerated tier drops by kind, `list_hubs`, `provenance_hubs`, `other_hubs`, or adds, `hubs_to_add`; `--apply`:
strips only list tags, never `folder:`, `collections:`, the body or claims, regenerates the hub tier through
`hub_builder.regenerate_hubs_and_index`, and commits pages, hubs and `_index.md` under `cicada`,
`maintenance/list-hubs` — pages written and committed 500 at a time, the hub tier in the last part; a page dirty in
git is skipped unless its only change from HEAD is this repair's (an interrupted run's, adopted and committed); refused
while Sleep runs or when git cannot list the dirty pages; a rerun changes nothing — `list_hub_repair`).

**Status lifecycle:** `active` → `decaying` → `archived` → `dropped` (user-dismissed, never
resurfaced).

**The body (layout v2, with the article, G194 2026-10-09).** H2 sections in a fixed order (`entity_body
.CANONICAL_SECTIONS`): `## Summary`, `## Article`, `## Key Facts`, `## History`, `## Related`, `## Links`,
`## Open Questions`, then any hand-added section, then the claims fence. Above the line (conceptual — never a `---`
in the file, which after a paragraph is a setext heading) is compiled prose: the Summary is the lead (the card's
header) and `## Article` holds `### <title>` sections of paragraphs with inline `[[links]]`, both rewritten freely
by the article writer (`entity_article`, `capture-and-sleep.md` *Pages as articles*). Below it is the record — Key
Facts, History, Links, Open Questions, Related, claims — unioned deterministically and never shortened by a writer.
A page without an Article is the v2 fact sheet — a stub (one conversation, under the writer's material floor) or
a bank with articles off; a page on 2+ conversations or with enough material, new pages included, gets the Article
(2026-10-17, `capture-and-sleep.md` *Uncapped*). Nothing reads the two differently except the writers below.

`article: {v: 1, hash: <12 hex>, written: YYYY-MM-DD}` stamps the lead and Article as the writer left them
(`entity_article.stamp`). While it matches, the page is machine prose: no summary or legacy rewrite touches the lead,
`bound_summary` and the deterministic merge keep it at any length, and a renamed link restamps it
(`entity_merge`, `entity_article.carry_stamp`). When it no longer matches — a person edited the lead or Article, or
wrote an Article by hand — `entity_body.has_human_prose` is true: the page is additive-only, like any hand-edited
page, and the writer leaves it alone.

**Agent page edits (G198, owner ruling 2026-10-14) — prose is no longer Sleep's alone.** An agent changes a page's words or
aliases through `cicada_edit_page` (`mcp.md`), one writer, `page_edits`: it reads the page file's own body
(`parse(ledger=False)`), edits only the prose before the claims fence and puts the fence and everything after it back as it
was, so the fence and the claims ledger are never re-rendered (a write from a body read without the ledger leaves every ledger
line where it is). A harness on the person's trust list (`page_editors`, `$CICADA_HOME/editors.json`; until the person changes it — no
`trusted` key — `claude-code` and `codex` are on it, owner 2026-10-14; once changed, even to empty, their list is the list;
an unreadable file trusts nobody; written only by `PUT /settings/editors`) writes at once; any other agent's edit is a `page_edit` inbox item (`features.md`). What keeps
an edit through Sleep, in the frontmatter:

- `corrections: [{old, new, by, on}]` (≤ 30, newest kept) — an `old → new` fix the edit pinned (`pin`, default on with `all`;
  `old` ≤ 200 characters). Every machine prose writer — Stage 3's update (`conflict_resolver.apply_changes`, on every branch,
  before the stamp and the provenance refresh), `page_article_rebuild` and `source_rewrite` — applies them to what it is about
  to write — the article writer's payload first, lead, paragraphs and their G118 records together
  (`page_edits.correct_article`), so a corrected paragraph keeps its evidence, then the whole prose
  (`apply_corrections`: exact, whole-word at a word edge, idempotent when `new` contains `old`, never in `## Related` or
  the claims, never on a heading or code-fence line, and a fix whose result would change the text's `page_edits.shape` —
  claims openers, where the claims block starts, the `#`/`##` headings, an open fence — is skipped) — and the article writer is given them as `CORRECTIONS` with one more rule line (its prompt is
  byte-identical without them). A word-level fix restamps a stamped article (`entity_article.carry_stamp`), so the page stays
  the writer's and keeps growing with the fix in. A later edit whose `new` is a pinned `old` drops that pin.
- `aliases_removed: [{alias, by, on}]` (≤ 50) — like `sources_removed`: Sleep's alias merge (`page_edits.keep_aliases`) and a
  page merge (`page_edits.carry_marks`, which also carries both pages' corrections) never add a removed alias back; matched
  case-insensitively with accents kept. Adding the alias by an edit lifts the mark.
- `human_edited: true` — set when an edit rewrites the Summary or an Article section whole: the page is the editor's from
  then on, additive-only, as a person's edit of those halves already makes it. The record sections need no mark.

**How a link is drawn: the link-title grammar (owner rulings 2026-10-14).** A link on a page may name its *view* in its
standard markdown title, so the line stays a working link in git, GitHub, Obsidian and every other reader (research-hub's
grammar, extended): `[T](url)` is a link that names no view, drawn by context (below); `[T](url "mention")` draws site
icon · site · title inline; `"url"` the plain link, chosen (owner 2026-10-26); `"bookmark"` a card; `"embed"` a video's
own player or a PDF's card (owner 2026-10-26; on anything else research-hub's reading, a screenshot);
`"screenshot"` a picture of the page, `"screenshot 2026-10-14"` the one from that day (else the nearest earlier, said in
words); `"captures"` every capture, oldest to newest; `"look"` / `"look 2026-10-14"` a saved look (G196) of the URL.
The title is exactly `<view>` or `<view> <yyyy-mm-dd>`, lower
case, a date only with `screenshot` or `look`; any other title is a real tooltip and means a link. A block view is drawn
as a block only when the link stands alone on its line (after a list marker, before an optional ` — note`); in a sentence
it draws as a mention. A bare URL or `<URL>` reads as its address (`example.com/guide`). **One grammar, two sides:**
`api/services/link_views.py` and the app's `LinkGrammar` (`LinkView.swift`) both read
`api/tests/fixtures/link_views.json`. **Sleep writes plain links** — context decides how one is drawn
(`link_views.drawn` / `LinkGrammar.drawn`, the fixture's `drawn` cases; owner 2026-10-26, Notion's model, nothing
written): inside a sentence a mention, alone on its line (a paragraph or any bullet, before an optional note) a bookmark,
a bare URL its address, never an embed — and a view word is written only on purpose: by an agent through
`cicada_edit_page`, or by the person's choice from a link's view menu (Mention, Bookmark, Embed only for a video or a
PDF, URL, then the capture views; `POST /entities/{id}/edits`, `api.md`), which is a pinned `corrections` row (`[T](url)`
→ `[T](url "bookmark")`; always the word, even where it matches today's default), so Sleep's next rewrite writes the view
back. The three backend link readers
(`entity_body`'s `## Links` dedup, `page_sources`, `site_sources`) read a titled link by its URL
(`link_views.LINK_TAIL`); recall's quotes drop the view word (`link_views.plain`) while `cicada_recall_detail` keeps it,
since an edit copies its words from there.

**A page's link facts.** `page_links.facts` answers `GET /entities/{id}/links`: per distinct URL in the served prose (code
fences out, ≤ 200), the views it is written with, its site (`reading_hosts.site_of`), and — when the person saved it — the
saved `media` page (matched through `url_index.json` by `media_ingestor.url_hash`, the one normaliser): `pageId`, its
name, `## Description` (else Summary), `savedAt` (the person's own save date, else ingest), `readAt` and its stored
picture (`entity_picture.media_picture`); the looks saved of the same URL (`looks[]`, newest first: id, day, the
screenshot's `/design/<id>/image` path, the palette); `captures[]`, empty until site exploration lands; and `icon`, whether
the page's icon route serves the site's mark. Nothing is fetched to answer: a link Cicada never read carries only its
site (ruling 3). **`read_at`** on a media page is stamped by `link_enrichment` when it read the site's words (the in-cycle
summary of a fetched page, or the backfill's fetch-and-summarise); a page the person's agent read keeps `read.at`, which
the facts fall back to.

An edited item's G118 row goes (`section_provenance.refresh`: its exact-text guard no longer matches); the edit's own
provenance is its commit (Git, below).

### Same name, different things — the qualifier (G227, owner 2026-10-29)

When two or more pages that are not `dropped` share a title (case, width and spacing folded), each is shown as
`<name> (<qualifier>)`, Wikipedia-style — "<name-a> (IDE)" / "<name-a> (program)". **Derived on read by one function,
`same_name`, never stored:** the page's `name:` stays clean, nothing writes a file. The qualifier says only what the
record holds, never a guess, in order: the head noun of the page's own first sentence when it reads "<name> is
a/an/the …" (`described_as`; never for a saved link, whose description is the site's blurb); a person's current
`works-at`/`studies-at` claim; a saved link's site, then its site and first path segment (a real domain only); the type
as a word (`tool`, `saved link`, …); the type and the month first heard of (a saved link: the day saved); last, a number
in creation order. Each page takes its first rung; two that would read alike step down together. The map is cached per
bank on the `entities/` directory's own mtime (every write is a rename into it — the card ETag's rule); a rebuild reads
titles from `search_index.entity_names` (no bank-wide parse) and the colliding pages only; `graph_builder`'s full build
primes it from the pages it already read (`same_name.prime`, keyed on the stamp taken before the read). Measured on a copy of the
owner's bank (8,067 pages, 5,722 live): 33 live collision groups, 76 pages (38 / 86 counting archived); 18 groups are
two saved links of one title, 15 a saved link or a concept beside a tool, company or project. Held map 0.006 ms;
rebuild after a write ~35 ms p50 on a warm index.

**A tag in the app, text at the doors (owner 2026-10-29).** "If I search <name-a> I should get both results. But for
the agent there has to be distinction. I guess the parenthesis is not really needed." The stored title is the plain
name and so is every title the app draws; the qualifier is a `Tag` beside it (DESIGN_RULES §9 2026-10-29, DR-44).
Searching the bare name returns every page with it, each with its `qualifier`. Agent doors (recall, `recall_detail`,
Ask, the CLI, `/v1`, inbox lines) keep "<name> (<qualifier>)" and the id in text. A page Stage 2 makes for a mention the
person said is none of the existing pages keeps the clean title under a distinct id (`<slug>-2`), never
"<name> (another)" (`entity_resolver._another_id`); a relation-only person's role title ("<role> (another)",
`role_people`) is unchanged.

**Links resolve by id (G227).** `id_utils.build_name_index` lets a page's own id win its key over another page's name
(a saved link titled like a tool once took the tool's id by listing order) and records every name two or more pages
answer to in `NameIndex.ambiguous`; `resolve_entity_id` never resolves such a name, `link_targets` names every page it
can mean. Stage 5.5's `mentions` edge from a bare `[[<name>]]` goes to the one page the linking page already relates to
(`related:`), else nowhere — never to a page picked by listing order. An agent's link is written by id with its
qualifier (`[[<id>|<name> (<qualifier>)]]`, `cicada_ask`'s citations); the app's link to a shared name asks which.

### Any join can be undone — merge, split, undo (G227 follow-up, owner 2026-10-29; `page_join`)
The owner: two things with one name that one page had absorbed "can be merged and stuff down the line, or entities can
be separated if they were joined". One module, three moves, each **one commit** the person can take back:

- **Merge** (`page_join.merge`): the one merge primitive (`entity_merge.merge_entities` — claims with their ids,
  evidence spans and history, sources, aliases, pictures, looks, every backlink and edge), committed alone; any
  "different" pair (`_merge_rejected.yaml`) or split between the two, and a held mention's "Another one" under either
  name (`pending_store.clear_apart`, #546), is lifted — the person has now said they are one.
- **Redirects** (`page_redirects`, `<bank>/_redirects.yaml`, `{redirects: {old_id: new_id}}`): **every** merge and
  rename leaves one — `merge_entities` and `rename_references` write it, so the inbox's merges, the dedup sweep and
  `role_people`'s retitle do too, and each commits it with its change (in its footprint). A page that exists always
  wins over a redirect; a chain is followed (≤ 8 hops, never a loop). `id_utils.resolve_entity_file` falls back on it
  (so every MCP tool and the CLI resolve an old id), and `GET /entities/{old}` answers the page it became with
  `X-Cicada-Redirected-From`. Cached on the file's stat: a name miss costs one more `stat` (measured below).
- **Split** (`page_join.split_plan`, `page_join.split`): the person picks sentences (numbered exactly as
  `same_name_split.sentences` numbers them, so its judge's proposal is the starting selection, pre-ticked, never
  applied by itself), claims, sources and conversations; they move to a new page with the **same clean title** and its
  own id (`<slug>-2`, `entity_resolver._another_id`; the G227 qualifier tells them apart, derived on read) and a type
  from the producible set. Moved claims keep their ids and provenance, re-subjected. Another page's link (a claim's node
  object, a wikilink by id or title — rewritten `[[<new-id>|<title>]]` —, `related`, a source's `entity:`) moves only
  where the person said so or its own evidence says which (`reference_choice`: every conversation it rests on moved →
  the new page; every one stayed → this page; otherwise the person says, and unsaid it stays). Graph edges drawn from a
  moved claim or between the two re-pointed pages follow. **A split records the pair as two things**
  (`merge_rejections.add_split`: a `split:` list beside `rejected:` in `_merge_rejected.yaml`). It is read apart from
  `rejected` on purpose — a `rejected` pair is also read as "this NAME is not that page" (`entity_resolver`), and after
  a split the name must still reach either page through Stage 2's same-title judge. `kept_apart` (rejected ∪ split)
  keeps the PAGES apart in the dedup sweep and the person-name review; Sleep's inbox tending never settles or judges a
  split pair (`inbox_tend._merge_rule`, `judge_merge` → `kept_apart`).
- **Undo** (`page_join.undo`): the reverse of the join's commit applied onto each file as it is now — the "Settled by
  Sleep" machinery (`inbox_tend._changed`/`_reverse`/`_reverse_list`): a file unchanged since is put back, the bank's
  lists (`_merge_rejected.yaml` both keys, `_redirects.yaml`) are reversed by meaning (what the join added leaves, what it
  removed comes back), and a change since in the same place refuses the whole undo (409, nothing written, the sentence
  says to merge or split again instead). The undo commit carries `Undoes: <sha>`; the History row of a join reads
  `join` (`merge`/`split`/`undo`) and `undoable` (`page_history`).
- **Who writes.** A remote app only ever proposes (coordinator 2026-10-29). Every write holds the bank's admission and page lock (`page_joins` routes; `_join_locked` on MCP);
  an edit already on a page is committed apart first (`before`). Commits: `Merged pages <day>` / `Split a page <day>` /
  `Undid a page join <day>` under the person (`user/companion_app`) or a trusted harness (its own `Cicada-Author`);
  any other agent's proposal is a `page_edit` inbox item with a `join` payload, applied by the person under
  `[<agent>, user]` with the retired item in the same commit.

**Measured (owner-scale bank copy, 8,079 pages, read-only copy; before = #546's head, after = this branch, two runs each,
same machine):** card open p95 44–47 → 46–50 ms (noise band; the card read is unchanged when the page exists), inbox
load p95 53–60 → 55 ms, a name miss p95 18–27 → 25–26 µs (+1 `stat`), `cicada_recall_detail` p95 116–127 → 116–121 ms.
The split plan of a 32-sentence page: 0.6 s cold, 0.45 s warm — no model (the suggestion pass runs only on the
person's *Suggest what to move*). The first cut took 3.0 s cold, 2.3 s of it importing `entity_resolver` for its
`<slug>-2` rule (now spelled in `page_join._new_id`); what is left is finding the pages that link here (one `git grep`,
~0.27 s, then reading those pages). Split 0.6 s, undo 0.4 s; split → undo, and split → merge → undo → undo, left the bank
byte-identical.

### Decay classes (G66)
One resolver, `api/services/decay_policy.py`. `resolve(fm)` returns `(class, rate)`: an explicit
`decay_class:` wins; otherwise inferred from `type` (`media` → evergreen, `skill` → durable, else
active) so legacy pages keep working. An explicit numeric `decay_rate:` still wins for the three
decaying classes; `evergreen` pins its rate to `0.0` unconditionally.

| Class | Base entity rate/wk | Claim multiplier | Meaning |
|---|---|---|---|
| `evergreen` | 0.0 | 0.0 | Never fades. Artifacts (media/bookmarks) + anything the user pins. |
| `durable` | 0.02 | 0.5 | Stable preferences, skills, long-lived concepts. |
| `active` | 0.05 | 1.0 | Default for a belief about the user's life. |
| `volatile` | 0.15 | 2.0 | Expected to change within weeks (role, status, current focus). |

**Anti-pollution rail** (mirrors `PRODUCIBLE_ENTITY_TYPES`): Stage-1 may propose
`durable|active|volatile` and **never `evergreen`** (`AGENT_PRODUCIBLE_DECAY_CLASSES`, enforced at
extraction AND again in the create branch). Evergreen is reserved for ingest writers and the user,
so an over-eager extractor can never stop the graph from archiving.

**Both engines honor it.** `conflict_resolver.resolve_and_prune` skips evergreen entities outright —
no decay math, no nudge, never auto-archived, so a bookmark can't generate a "still interested?"
question. `claim_reconciler._decay_claims` multiplies its per-epistemic × source_trust rate by the
SUBJECT's class multiplier. Since G147 the class rate is the *base*: both engines multiply it by the
spacing factor and the per-type pace (see Temporal decay).

### Claims, evidence and provenance

**Claims** are the machine-legible half: typed predicates, bi-temporal validity, observer and trust.

**Whose belief (observer).** `agent` is Cicada's own reading of a conversation (every Stage-1 claim by default), the
owner's id is the person's own word (`user_stated`), and `external:<name>` is someone else's. Since G179 Stage 1 writes
`external:<name>` itself for a claim whose located evidence lies only in a message conversation's other side — a texted
AI agent's `assistant` turns or a person's `speaker` turns, named by the episode's `correspondent` — so "Instinct said
alpha-project launches next week" is Instinct's belief in its own slot (the reconciler's key includes the observer), never
the person's and never superseding theirs. A relationship the model labels with an observer has it dropped; a claim the
person's words also back stays `agent` (`capture-and-sleep.md`, Stage 1). The claims *about* that correspondent live on
their own page — a `tool` for an agent, a `person` for a person, a new one always under `<id>-agent` / `<id>-person` —
never on a same-name page of another type; below the promotion bar they are held on the pending line keyed by that id
(`correspondents`; `capture-and-sleep.md`, *Entity promotion*). The observer stays `external:<name>`, the correspondent's name, whatever id the page has.
**The same for any assistant (2026-10-27, `entity_extractor.assistant_observer`):** a claim whose located evidence lies
only in a harness session's `assistant` turns is `external:<harness>` (`external:claude-code`), only in a chat export's
assistant turns `external:chatgpt|claude|gemini`; a relayed episode (`evidence_kind`) keeps its own rail. Such an
observer — `external:<the agent the claim's own origin names>` — **shares Cicada's own `agent` slot**
(`claim_reconciler.slot_observer`, the reconciler's key `K`): it is the same extraction of the same conversation, so a
newer value closes an older whichever wrote it, a restatement reinforces, and the bank's assistant-only claims written
`agent` before 2026-10-27 stay in step without a repair. The trust table and the owner's-words rail still decide, so
neither closes the person's own claim; a texted agent's or another person's `external:<name>` keeps its own slot. Every
Stage-1 claim read from an episode with a `session_id` carries it in `session_ids` (`capture-and-sleep.md`, *Facts keep
their context*).
`external:linkedin` (2026-10-16) is what LinkedIn listed — a connections export or one profile the person's agent read —
on a page Cicada already had: `works-at`, `role`, `connected-on`, dated, `source_trust: external`, origin
`linkedin/connections|profile`; `linkedin_people` keeps that slot one dated line per predicate, newest wins, and never
touches another observer's claim (`capture-and-sleep.md`, *LinkedIn connections*; `mcp.md`).

**The fence is JSON Lines (DECIDE-1, owner 2026-10-08).** A page's claims live in one ` ```claims ` fence, one claim
per line, each line `claims._jsonl_line(Claim.to_dict())` — the one encoder every writer uses (a raw writer passes its
mapping); `[]` when the page has none. JSON escapes every character a line splitter splits on (NEL, LINE and PARAGRAPH
SEPARATOR included), so a claim is always exactly one line of the page. The reader is dual
(`claims.load_fence_payload`): a fence whose first non-blank line opens an object is JSON Lines, anything else the
legacy YAML list, read exactly as before. A writer that re-renders a fence (`write_claims`) emits JSON Lines, so a
legacy page converts on its first write; `append_claim_entries`, which must not re-render, appends in the fence's own
form. `python -m api.scripts.migrate_claims_jsonl --bank <path>` reports counts (a dry run); `--apply` converts every
remaining legacy fence in one `cicada` commit — never automatically, never while Sleep runs. Its own process cannot see
Sleep's flag, so it asks the backend and fails closed like claim recovery: only a 200 saying `writing: false` and not
`running` lets it write (no backend refuses too; a slow or absent answer is asked again, three tries of 8 s, and a
refusal says whether Sleep was running or the backend was slow, unreachable or unreadable, `backend_problem`; every
maintenance command that imports `backend_running` gets the retries); a page with uncommitted changes, or written again during the run, is
left out of the commit for its own writer. Why: PyYAML builds every
node in Python even on the C loader (~150 µs a claim: 0.5 s for a 3,500-claim page, ~3 s for a 2,000-page bank's
claims, paid by every full-bank reader); a JSON line is ~3 µs (`benchmarks/scale`). Spans are unaffected: a `page`
evidence offset points into the body with the fence stripped, which is the same text in either form.
A predicate the vocabulary marks multi-valued (`predicates.cardinality`) never opens a conflict.

**The claims ledger — a very large page's older claims, beside it (owner page, 2026-10-14).** A page's claims are
its fence **plus**, once the fence passes `claims_ledger.FENCE_MAX_CHARS` (64,000 characters — a median page holds a
few KB), `entities/<id>.claims.jsonl`: the fence's own JSON lines, oldest first, tracked by git with the page. Why: the
owner's page carried ~5,900 claims, mostly a per-conversation activity log ("<owner> asked about X"), 4.5 MB of a
4.7 MB file every reader and writer moved. The split is invisible above `markdown_parser`: `parse` of a page whose
frontmatter carries the `claims_ledger: {claims, hash}` stamp folds the ledger's lines back in at the head of the
fence (a line in both files byte for byte — a crash between the two writes — is read once), so all ~70 claim readers
and writers see one set; `parse(..., ledger=False)` (a frontmatter scan, the card) never opens it. `parse` also marks the frontmatter dict it
returns with the hash of the ledger it folded (`claims_ledger.READ`, never written to disk). `write` leaves in the
ledger every line the body carries back byte for byte. A ledger line the body does not carry leaves the ledger only
when the writer handed back that mark for the ledger as it still is — it read the whole set and wrote its change
(a rename re-subjecting every claim, a pass editing each); any other body (read without the ledger, or against a
ledger changed since) leaves every ledger line as it is. Nothing is matched by id: a withdrawn or expired claim and
its restatement share one, and both are the record (review 2026-10-14). Lines the ledger gains are written before the
page and lines it loses after it (`write_plan`), so a crash leaves a duplicate, never a loss. The rest stays in the
fence, and when the fence is over the budget lines move to the ledger until it is
under `SPILL_TO` (half), in order: closed claims, then a log's (`entity_body.is_log`: a predicate the stems positively call
activity, in a family the page holds for more than 3 objects; when unsure, a fact), then the rest, each oldest first — so what stays on the page
is what it says about its subject plus the newest activity. **A write never removes a ledger line** (a body read
without the ledger leaves it as it is); only `claims_ledger.remove` (a merged-away page, after its claims moved) and
`move` (the inbox's rename) take one away. The ledger is written before the page (a crash leaves a line in both, never
in neither) and the stamp changes with every ledger write, so every cache keyed on the page's bytes sees it. A page
and its ledger are one unit to git: `commit_paths_sync`, `commit_touched_sync` and a `checkout --` restore through
`run_git_write_sync` add the ledger of every page they name; a dedup merge snapshots every footprint page's ledger,
there or not, so a failed merge puts back (or removes) a ledger its winner write created; claim recovery reads HEAD's
ledgers as present. `write_new` and `write_document` (raw writers) never split. An existing bank
is split by `python -m api.scripts.split_hub_pages --bank <path>`, re-runnable on a split bank (dry run: counts only; `--apply`: one `cicada`
commit, refused unless Sleep is idle, each page checked to read back every claim id, evidence span and Related link
before it is written; a rerun finishes an interrupted run, committing the pages it left dirty with exactly this
migration's bytes and nothing else; a Related link that is no edge and no `related:` slug keeps its line as it was;
`hub_pages`).

**A value that changes is a claim a later value closes (stated values, 2026-10-17).** LongMemEval knowledge-update
(G148): a count said as three and later as four, and a personal-best time said twice, both stayed as two undated lines
of prose with no claim to supersede — Stage 1 emitted only entity-to-entity relationships, and an unseen predicate
coexists. Stage 1 now also returns `values[]` (`{entity, attribute, value, evidence_quote}`: a count, a time or record,
a price, a size, a version or status in use — one current value of one thing, never a list or an event date), verified
like a relationship's quote and projected as a literal claim `value-of-<attribute slug>` (`claims.value_predicate`,
`entity_extractor._value_claim`). The prefix with a literal object makes it single-valued by its own shape
(`claims.is_value_claim`; `predicates.cardinality` answers `single`), never by a bank's vocabulary, so the trust table
runs as for any single-valued key — a newer value supersedes, two values on the same day ask — under the owner's-words
rail (`inbox_tend.may_close`, review 2026-10-17): a value resting only on the assistant's or another speaker's words
never closes one resting on the person's own (an evidence span in their turn, or their answer), in either order; it is
asked about instead (`value_kept_for_persons_words` in the audit). Two Stage-1 reads name one attribute in other words, so a value adopts the predicate of
the open value on its slot whose attribute words match (`claims.same_value_attribute`: the same words after filler
such as "number of", or one set inside the other when the smaller has two or more — "age" never meets "dog age"). A
value said before the one the page holds (a drain reads conversations in any order) is kept as closed history,
`superseded_by` the first value said after it (so history never overlaps), never asked about (`superseded_on_arrival`). The value stays in key facts too.

**A person holds more than one place at once (2026-10-14).** `works-at` is multi-valued: as a single-valued key, Stage 3
closed the open place whenever another was mentioned, and one measured owner page held 26 `works-at` claims, 25 closed,
flipping between six places 1–60 days apart while two were true at once. The reconciler's oracle
(`predicates.build_cardinality_fn`) applies `cardinality`'s rule too — the committed seed's `multi_valued` wins over a
bank's stale `single_valued` (an uncertain cardinality never auto-closes), and the seed's singles are not imported, so a
bank with no map still coexists everything. The same rule reaches every predicate the seed moved: a bank seeded before
G98 still lists `uses`, `is-a`, `located-in` and `depends-on` single-valued, and in Stage 3 those coexist now too (as
the inbox already said); their values closed under the old rule are not repaired. `runs-on`, `takes-place-in` and `part-of` stay single-valued: no evidence
says they fail the same way. **A place ends only on evidence that it ended:** a stated end (`expected_end`,
`claim_expiry`), the person's own edit or answer, or an ending label (`endings` in the seed, `predicates.build_endings_fn`,
seed ∪ bank, compared slugged, a label two canonicals claim ends nothing). Stage 3 reads the label as said
(`predicate_raw`, else an agent's predicate; `claim_reconciler._place_ending`): `over` ("left", "previously worked at")
closes every open belief on that subject and object, dated when it was said and never before it opened — never the
person's own statement under an agent's word, never one last said after the ending — and keeps the ending as closed
history; with none open, a label that is a synonym ("previously worked at") is closed history and any other ("left")
keeps its own label. **An `over` label also ends its canonical's relatives (2026-10-23, benchmarks/newuser):** the
seed's `also_ends` under a canonical (for `uses`: `depends-on`, `backed-by`, `runs-on`, `hosted-on`, `deployed-on`,
`stores-data-in`, `stores-in`, `authenticates-with`, `integrates-with`) and any object-qualified label of the canonical
or of one of those (`uses-for-auth-and-data`, `stores-data-in-<x>-postgres`; the longest listed prefix decides,
`EndingFn.ended_by`) close on the same subject and object under the same guards, each keeping its own predicate — so
"dropped Supabase" ends "uses for auth and data Supabase" and "depends on Supabase" too, where it used to end only a
plain `uses`. A predicate two canonicals list ends nothing; a relative said after the ending stays current (the newest
dated statement wins, ruling 26), and one said before it, read after, is closed history like the canonical.
`past` ("worked at", "interned at") reinforces an open place and never closes it — only the canonical itself, never a
relative; with none open it is closed history, never a current place. **Order never decides:** a mention said on or before a departure already on
the page (a "left" claim, or an ending record's own words) is kept as closed history, whatever order the claims are
read in, and a re-read of a claim the page holds closed (same id, G104) only adds its sources — a page never holds one
id twice. No fold question is raised for an ending. Stage 1's prompt says "works at" means current.
**Past roles (2026-10-27, G121):** a person's whole current state has a past tense, not only a job — the seed's
endings cover `works-on` (endings only — "previously worked on", "no longer works on"…; never "worked on" as a past
tense: "I worked on alpha-project today" reports ongoing work), `lives-in` ("lived in", "lived at"; over: "moved out
of", "previously lived in"…), `studies-at` ("studied at"; over: "graduated from", "dropped out of"…) and `reports-to`
("reported to"; over: "previously reported to"…), with the past and ending spellings as synonyms, so a public figure's
earlier employer said in passing is closed history, never a current place dated the day it was said. `lives-in`, `studies-at` and `reports-to` are canonicals but in neither cardinality list: Stage 3 coexists
them, the inbox still asks. Stage 1's prompt says the same of homes, schools and managers, and that a job someone had
before — what the model knows of a public figure included — is never written in the present tense.
**A start is the belief it starts (2026-10-27):** the seed's `starts` (`predicates.build_onsets_fn`, seed ∪ bank,
slugged, a label two canonicals list starts nothing) names the labels that say a belief began — `works-at`: "started
working at", "began working at", "was hired by", "now works at"…; `lives-in`: "moved to", "relocated to"…;
`studies-at`: "enrolled at" (never "enrolled in": measured, it named courses) — each with the entity types the
subject's and the object's pages must be (a person and a company; a person and a location). **Never a bare "joined",
"joins" or "started at", nor "moved into"** (review 2026-10-27): the closed types file a club, a team, a university, a
lab and an agency all as `company` and an office as `location`, so "joined Chess Club" would have read "Works at: Chess
Club". Stage 1's prompt writes a job that began as "works at" with its `starts` day instead, and says joining a club,
a team, a course or a university is never "works at". Stage 3 writes a listed start under the canonical
(`claim_reconciler._onset_canonical`, audit `started`, no fold question); "<company> was hired by …", or a start to a
page that is not there, keeps its own label. **A start
never closes another current belief** — a person who joins a lab may keep a job (2026-10-14); whether the newer of two
current places should close the older is an open question for the owner, not a rule. A Stage 1 relationship may carry
`starts`, the absolute day it began ("as of yesterday, joined" said on 2026-05-20 is 2026-05-19), resolved by the model
and dropped unless a real ISO date, never on an ending or a past tense; it is the claim's `valid_from`.
**A switch is said about what switched (2026-10-23, owner):** an ending closes only claims on its own subject — "<person>
dropped <tool>" never closes a project's use of it. Stage 1's prompt writes a project's switch on the project
("<project> dropped <tool>", "<project> uses <new>"), in the active voice and never as "replaces" / "replaced by"; the
seed's `uses` endings also read `replaced`, `replaces` and `switched from`, which close only that subject's open use
(newuser replays of the drop conversation, haiku: 18/20 on the project before, 20/20 after); `moved from`,
`moved away from` and `migrated from` too, and the prompt names "moved from A to B" and "replaced A with B" — a
"replaced with <b>" label is no ending, so what replaced the old thing stays current (live test, 2026-10-23).
**One value, several wordings (2026-10-23, live test):** a stated value's attribute matches another by its words
(`claims.same_value_attribute`), and a one-word attribute only itself, so "latest release: 0.3.1" stayed open beside
"released version: 0.6.0". The seed's `value_attributes` declares spellings that are one attribute (`release`: release,
latest release, released version, release version, latest/current version, version;
`predicates.value_attribute_group`); under one name the newer value closes the older on the usual value rules (the
newest dated evidence wins, an older value read late is history, the person's own words never closed by an agent's).
Nothing outside the list is joined.
**A stated day (W7, 2026-10-23):** a Stage 1 relationship may carry `ends`, an absolute day the model resolves from the
conversation's day ("my last day is a week from today"); anything but a real ISO date is dropped, so nothing relative is
stored (`entity_extractor._stated_day`). On an `over` label it dates the ending (the job closes on the last day, not
the day it was said); on any other label it is the claim's `expected_end`. An ending still ahead of the day Sleep reads
it sets `expected_end` on what it would close instead of a future `valid_to`, and expiry closes it on the day.
**What rests on a job (W7):** the seed's `dependents` under `works-at` (`reports-to`, `managed-by`, `manages`,
`managed`, and their qualified labels; `EndingFn.depends_on`). Stage 1 gives such a relationship the organisation it
belongs to (`at`) and writes the person's own working relationships from their side; Stage 3 then names the subject's
job at that organisation in the claim's existing `premises` (`claim_reconciler.link_premises`, after every claim of
the pass is placed). When the job ends — an ending, or its stated end passing in `claim_expiry` — each open dependent
naming it closes on the job's last day (`close_dependents`): same subject only, never one said after the job ended,
never the person's own claim unless the job's end came from the person too (the claim that closed it, or the job's own
stated end, `is_human`; a closer missing from the page counts as not), nothing superseded. A relationship with no `at`
names no job and stays open (nothing is guessed from timing).
**Repairing a bank:** `python -m api.services.coexist_reopen --bank <path> [--plan <file>] [--said-since <day> | --all]`
is a dry run (counts by reason, and the places it would reopen — and those the window keeps closed — by when they were
last said; the plan holds ids, paths, commits and reasons, never text). **The window defaults to places said in the
last 180 days**; `--all` lifts it: a place closed once by a new job and never said again passes every check and is as
often a real job change, so read the age groups before widening; `--apply` reopens, in one `Reopen coexisting places <date>` commit as `cicada`, only a
`works-at` belief the old rule alone closed — its successor on the same page has the same slot, a different object,
`supersedes` it back and opened the day it closed; neither is the person's; the close was made by a model's `Sleep cycle`
commit (found by bisecting the page's history, its claims ledger included); no stated end has passed; its own words are
not past tense or an ending and the page does not say the person left that place; and it is the newest closed copy of a
place not already current. Everything else stays closed, counted by reason — when in doubt, history. It refuses unless
Sleep is idle (admission held, the backend must answer `writing: false`), skips a dirty page, writes through the one
claims writer and deletes nothing: the close stays in git.
**Repairing past roles (2026-10-27):** `python -m api.services.past_roles_repair --bank <path> [--plan <file>]
[--apply]` applies the two rules above to claims written before them, on every page (archived ones too: a mention
brings a page back with its claims). An open claim under one of a person's states (`STATES`: works-at, works-on,
works-with, lives-in, studies-at, reports-to) whose own words carry one of its past or ending labels (for `works-on`
only an ending) and none of its present ones ("worked at", not "works at") becomes closed history (`valid_to =
valid_from`, what Stage 3 writes for a past tense with nothing open) — **only when it rests on one conversation, or
every quote it cites says the past or an ending**: a restatement adds sources and never rewrites a claim's words, so
"worked at" in May and "works at" in two later conversations is one open claim whose words are May's (`restated`,
kept); an ending kept under its own label that is a
synonym ("formerly worked at", "studied at" in a bank seeded before) moves under the canonical, closed the same way; an
open start label between the declared types moves under its canonical, unless the page already holds that belief
current. Never the person's own claim, never a claim whose words are present tense (evidence alone is never read as
an ending), and nothing closed because a newer belief exists. Dry run by default (counts by action and reason; the plan
holds ids, paths, predicates and reasons, never text); `--apply` has `coexist_reopen`'s guards (Sleep idle, page lock,
git's write lock, dirty pages skipped) and commits the pages written alone, as `cicada` (`Close past roles <date>`).
For `works-on` and `works-with` only an ending closes a claim here (`ENDINGS_ONLY`: "worked on" and "worked with"
report ongoing work). Measured on an owner bank (dry run over a copy, 2026-10-27, after review): 17 claims to close on
11 pages (7 by their words, all `works-at` on public figures' pages; 10 ending labels), 1 start, 1 kept (already current).

**Contexts and the fence (F1).** `context` is an open vocabulary whose *shape* is pinned by
`claim_contexts` — a short lowercase slug. Any other value (G60's `as of <date>`) keeps its job as a
claim key but is never a graph satellite, a legend row or an edge colour. `general` means "no
particular context" and is never a facet: a satellite needs two real contexts. The claims fence sits
after a page's last section (`write_claims`, the one writer), so **every reader strips it before
sectioning** — `strip_claims_block` on the server, `EntityProse` in the app.
Stage-5 prose rewrites use `preserve_claims_blocks` only to re-emit closed fences
already read from disk, including unknown fields and unreadable payloads; it never
authors claims. Synthesis, contradiction detection, source-grounded rewriting,
dedup judging (both pages), entity disambiguation and pattern/skill detection
receive prose stripped by `strip_claims_block` before their input budgets are
applied, so truncation cannot expose a fragment of a closed claims fence.
MCP recall's related-page blurbs use the same strip-before-truncation rule;
explicit full-page reads still expose the structured claims for agent reasoning.

**Recovering claims a rewrite dropped (G148 follow-up) — only ever as closed history.** Before that fix a rewrite
sectioned the raw body, so the fence rode in the last section and was rebuilt or lost; the claim pipeline, which runs
after the prose writes, then kept only what it could still read. `python -m api.services.claim_recovery --bank <path>
[--plan <file>] [--apply]` finds the holes from git alone: it replays every first-parent commit that touched
`entities/`; an id in a page's fence before a commit and not after it is a removal, an id on any page at HEAD is no
loss, and the id's **last** removal decides. **A recovered entry is never a current belief:** it comes back closed —
`valid_to` the removal commit's day, or its own stated end (`claim_expiry.stated_end`) when earlier, never before
`valid_from`; an entry already closed keeps its own — and marked `recovered_from: <removing commit>`,
`recovered_by: claim_recovery` (`Claim` fields, omitted when unset). **No writer reopens it:** every writer that
clears `valid_to` asks `claims.is_recovered_history` first (a test lists them — the decay `keep_active` verdict leaves
it untouched; a paper/folder sync that re-sends the same deterministic id asserts a fresh entry beside it), and
every reader's `claims.is_current` takes it as history by its close and by `recovered_by` alone. Excluded, each needing positive evidence to pass:
the removal's writer (`person_edit`, `merged`, `inbox_resolution`, `other_writer`, and `unproven_writer` — a `Sleep
cycle` subject whose `Cicada-Author`s are not all models or `cicada`); `unreadable_fence` (the page's fence was
unterminated, repeated or unparseable at any version read — `claims.fence_state`), `unreadable_elsewhere` (an
unreadable HEAD page is read as its payload decodes (JSON Lines or legacy YAML) — `claims.loose_claim_entries`, every fence to its close or the next
opening — so an escaped or quoted id still counts as present and a `retracts` record there still excludes; a page
whose payload will not load at all makes absence unprovable and excludes every candidate); `retracted` (a `retracts` record named it at ANY version read);
`merged` (a `<id>-from-` copy), `page_gone`, `page_archived` (at the removal or now); and `not_rewrite` — the bug's
signature is required: the section that held the fence when the page is sectioned raw must have had its fence-stripped
prose rewritten. What is left is classed `replaced` (a current claim on the page shares subject and predicate — and
object unless the vocabulary marks it single-valued — or a HEAD claim `supersedes` it), `closed_history` (every
dropped copy was already closed) or `no_current_replacement` (a belief current when dropped with no successor: listed by
id and page only, **never written** — the person decides). The dry run (default) prints counts by class and reason and
writes ids, paths, commits and classes — never claim text. `--apply` writes the first two classes: each entry as the
fence held it (unknown fields kept), in the fence's own form, appended by `claims.append_claim_entries` without re-rendering any entry already in
the fence or the frontmatter (`markdown_parser.write_document`), spans checked with `evidence.span_status` (one that no
longer locates becomes `reasoning`), under admission → page lock → git's write lock. The CLI is its own process, so it
also asks the backend's `/sleep/status` and **refuses on any answer but a clear `writing: false`** (no backend, an auth
or server error, a malformed body). A dirty or unreadable page is skipped; one `Recover dropped claims <date>` commit
of only the pages written, `Cicada-Author: cicada`, put back from HEAD on failure. A re-run finds nothing.

**A merge keeps both claim sets (audit 2026-10-05 P1-1).** `entity_merge.merge_entities` — the dedup sweep's and
the inbox's one merge primitive — carries every claim the loser held into the winner's fence: re-subjected to the
winner, a node object that named the loser repointed, and its observer, trust, sessions, evidence, validity and
supersedes/superseded_by untouched (a `page` span that cited the loser keeps naming it — its offsets and hash are
into that text, which git holds). An id the winner already uses is kept as `<id>-from-<loser>` (the loser's own
supersession links follow; a re-run after a crash finds its earlier copy); a claim identical once re-subjected is kept
once; two open claims that disagree stay two — a merge never closes a belief. A corrupt fence on either page aborts
the merge (the inbox answers 409), and two ids for one file (a case-insensitive disk) are refused. **A ref resolves to
the page's own id whatever case was typed (2026-10-14):** `id_utils.resolve_entity_file` returns the path spelled as
the directory lists it (`id_utils.on_disk`; the listing is cached by the folder's mtime, trusted only once it was taken
100 ms past that mtime — git's racy-clean rule, for a filesystem with a coarse clock; its last rung, a ref matched to a
stem ignoring case, reads one index built from that listing, never a glob per call), because macOS finds
`entities/Cicada.md` when the page is `cicada.md` and a caller that took that stem as the id knew no page by it —
`cicada_note_progress(project="Cicada")` called a project "a page". The readers that join a ref onto `entities/`
themselves (`recall_detail`, `sources`, progress participants, the backlog's project page) use the same rule. Before the loser's
page is deleted, `graph_edges.yaml` and every other page's `related:`, `[[wikilinks]]` (with `|label` or `#section`),
source `entity:` links and claims whose subject or node object named it are repointed (`repoint_references`), the
loser's name joins the winner's `aliases`, and the result lists the paths it wrote. **What the person gave either page
survives (2026-10-21):** both pages' `kept_on` days are unioned (oldest first, the newest 52; G147), and the person's
picture choice travels when the winner has none of its own (G146) — an upload's file moves to
`assets/pictures/<winner>.<ext>`, "use initials" is copied, an upload mark whose file is gone does not travel, and a
loser's upload that the winner's own choice outranks is removed (git keeps it), so no file nothing names is left behind;
one plan (`entity_picture._merge_plan`) feeds the footprint and the writer. The inbox's
rename-to-the-cleaner-slug branch repoints the same references (`rename_references`), which also moves the page's
uploaded picture to its new id (`entity_picture.carry_on_rename`; the placeholder repair's `_rename_footprint` names
it), and every inbox note lands above the fence. `episodes/` is never rewritten. **The dedup sweep commits its own merges (G183(e)):** `POST
/maintenance/dedup-sweep` with `dryRun: false` runs each merge as one transaction under the page lock **and** the bank's
git write lock, from its footprint check through its commit or recovery (never across the judge's model call). The
footprint — `entity_merge.merge_footprint`: winner, loser, `graph_edges.yaml` when an edge names the loser, every page
naming the loser, found by `_repoint_page`, the same matcher `repoint_references` writes with, and the picture files the
merge moves or removes — is known before any write.
The merge is refused untouched when a footprint path is unsafe to put back (`skippedUnsafe`: unmerged index stages, a
symlink, not a regular file) or dirty (`skippedDirty`), so nothing another writer left uncommitted is ever committed as
`cicada`. Only the footprint is snapshotted (bytes, permission bits, stage-0 index entry or absence). The merge must write
only inside it; the paths it wrote whose bytes changed are committed — `Dedup sweep <date>`, `<path>: updated|removed
(merged, trigger: maintenance/dedup-sweep)`, `Cicada-Author: cicada`, `Cicada-Engine:` the judge's engine. A failed merge
or commit gets the footprint back as found, never HEAD's version, and nothing outside it is read or written (`failed`);
a write outside the footprint, a put-back that cannot be done, or a HEAD that moved inside the transaction stops the
sweep (`recoveryFailed`). `repoint_edges` leaves an untouched graph alone. A dry run writes and commits nothing.

**A merge or rename keeps every edge whole (2026-10-14).** `entity_merge.repoint_edges` — run by every door that merges
or renames a page: `merge_entities` (the dedup sweep, the inbox's merge answers, the placeholder-people name answer and
repair) and `rename_references` (the inbox's keep-the-cleaner-name rename, a placeholder's rename or retitle) — changes
only the `source`/`target` that named the moved page. Every other field (a claim-backed row's `claim_id`, `observer`,
`context`, `valid_from`, or anything else) and every other edge stays as it was, in order. A moved edge is dropped only
when it now runs from a page to itself (the claim projection never draws one) or is now identical, field for field, to an
edge already in the file. It used to dedupe the whole file by (source, target, label): one repair merge on a real bank took
45,786 edges to 31,545 and left 59 of 14,298 claim-backed rows with their fields (the bank commit was reverted). Sleep's
own writer, `inbox_generator._write_graph_edges` (Stage 5's relationships, 5.5's `mentions`, 5.55's media edges), had
the same shape — it rewrote the file as bare triples deduped by (source, target, label), and Stage 5.7 then re-added the
claim rows, so each Sleep write left a bare copy of every claim row behind. It now keeps every existing edge verbatim and
adds a new edge as `{source, target, label}` only when no bare edge of that triple is already there; an unreadable file
is never replaced by the new edges alone. The bare copies already in a bank stay (they are edges, and nothing
automatic removes them). `api/tests/test_merge_edges.py` drives every door over one file of mixed bare and claim-backed
edges. **The file is written atomically, by one function:** all four writers (`repoint_edges`, `_write_graph_edges`,
`graph_builder.regenerate_edges_from_claims`, `graph_builder.upsert_claim_edges`) call `markdown_parser.write_yaml` — a
fsynced temp file beside it, then `os.replace`, the page rule — because a `write_text` cut short left a torn ~4 MB file
that was unreadable or, cut at a line, parsed as a shorter one. **An unreadable file is never rewritten:** when the file
cannot be parsed or is not a mapping, Sleep's writer, Stage 5.7 and `upsert_claim_edges` log it and write nothing, and
`repoint_edges` raises without writing it — a merge then fails, and the dedup sweep's transaction puts the merge's page
writes back (Stage 5.7 used to read such a file as empty and write the claim rows alone, dropping every other edge).

**Evidence spans (G118) — spans, not copies.** Every claim written since that slice carries
`evidence: [{episode, start, end, kind, hash}]`. `start`/`end` are character offsets into the source
document's *evidence text* (the body as `markdown_parser.parse` returns it, with the ```claims fence
stripped for an entity page, so writing a claim never stales its own span); `hash` is
`sha256[:12]` of that text, and a mismatch reads as `stale` rather than mis-highlighting. `kind` is
one of six: `user` | `assistant` | `page` | `speaker` (a meeting participant who is not the owner,
G134) | `media` (what a video said — a watch record's timed `video [m:ss]:` line, G140; its position
in the video is derived at read, never stored) | `reasoning` (the contributor's own inference:
`start == end == -1`, never a faked span); an episode's `evidence_kind: user|assistant` (a folder's
authorship rule, R-F2; a Claude memory export is always `assistant`, its lines being `system:`) overrides the line markers.
**A saved item's words are the page's (2026-10-29).** A bookmark, saved link, saved-list post, feed item, watched
day, tab group or calendar entry — known by its own record (`media_entity_id`, `url`, or a saving door's
origin/source: `authorship.is_saved`, never by what a line says) — reads as `page` everywhere except its
`## Why it was saved`, `## Saved because` and `## User note` sections (`evidence.PERSON_SECTIONS`), which are `user`;
a turn marker inside it (an agent's `assistant:` note) still reads as a marker. It is never stored: `authorship.of(fm)`
returns the declared `evidence_kind`, else `evidence.SAVE_KIND`, and every reader passes that as `override` (Stage 1,
promotion, project birth, ruling 42, the card rule, the Reader, search hits, the inbox tend). Spans already stored keep
their kind; the repair is a dry run awaiting the owner. One marker grammar, `evidence._marker`, reads
both line families, plus the chat importer's `attachment [<file name>]:` turn — the text Claude extracted from an
upload, every line quoted (`> `) so it can open no turn — which is `page`, never the person's words. One module, `api/services/evidence.py`, does the work for every writer: locate
is exact → whitespace-normalised → case-insensitive and **never fuzzy**; an unlocatable quote
becomes `reasoning` and **the claim is still written — provenance never blocks memory**. Legacy
claims carry no `evidence` and `to_dict` omits the empty key; there is no backfill.

**Prose item links (G118 sections, 1a-i).** `section_provenance.py` stores optional
schema-1 `section_provenance` frontmatter, without changing the YAML emitter:
`sources: {s0: "<episode> <12-character source hash>"}` and
`sections: {key_facts: {<12-character item key>: "<12-character text guard> s0:-1:-1:r"}}`.
Each item/source value is one scalar; span tokens are `s0:<start>:<end>:<kind code>`.
Codes `u/a/p/r/s/m` expand to user/assistant/page/reasoning/speaker/media. Reasoning
has `-1:-1`; spans have `0 <= start < end`. No copied quotes, claim references,
writer/cycle fields or stored `derived` rows. The source table deduplicates document/hash
pairs, including multiple revisions of the same episode, and refresh prunes unused pairs.

The item key hashes `_normalize_fact(text)` for lookup; the mandatory exact text guard
prevents normalization from recertifying edited words. Summary is one item; list items
include indented continuations; in `article` (G194) each paragraph — a run of non-blank lines that are not a `### `
title — is one item, the same row the app draws. The article writer records, per paragraph and for the lead, the
evidence rows of the inputs that paragraph validly cites (spans first, at most 16), under its exact text: one click
from a line to the conversations its facts and claims came from; an edit unlinks the paragraph, never recertifies it.
History lines carry no rows (Stage 1 records summaries and facts only), so a paragraph written only from History is
unrecorded and opens the page's own Where this came from. Duplicate/ambiguous normalized bullets are not attributed.
Editing one of 120 bullets leaves 119 links; reordering preserves them. The server parses
headings outside code fences, accumulates duplicate headings and supplies Unicode code-point
body ranges. Claims never enter fingerprints. Any code fence still open at end of the body
makes its opening section and any hidden stored sections unavailable. Refresh preserves
those records with their original guards if either the original or final body cannot be
read; repairing the fence restores only exact matches, without renewing attribution.
Closed malformed or repeated claim fences do not make prose unavailable. Empty/missing
sections with stored records report zero current items and unmatched-record counts.
Unknown/malformed schemas survive writes and fail closed on read.
No backfill: absent, changed or uninstrumented prose stays unrecorded; git retains prior records.

G194's opt-in orientation writer composes facts deterministically, retaining exact surviving
guards and selected incoming fact records. Rephrased Summary and date-prefixed repair items
are unrecorded. The prose-repair dry run preserves raw claims fences and unknown metadata in
scratch candidates only; it has no bank apply phase (see `capture-and-sleep.md`).

The bounded writer selects provenance from the actual surviving Summary/facts: an exact carried
fact kept as Summary retains its source rows there, and a displaced orientation already retained
as a fact gets no duplicate History copy. Normalization alone cannot certify changed text.

The 150-bullet/80-episode plus Summary fixture measures **10,739 bytes / 238 YAML lines**;
three spans per item and three revisions per episode measure **22,518 bytes / 398 lines**
with the production emitter. Gates are 16 KiB primary, 32 KiB dense (no runtime link truncation).
Raw agent detail still includes the metadata, approximately 2,685/5,630 added tokens by
characters/4; this is an estimate, not model usage. Default detail elision remains a decision.

**Events (G141).** Two predicates, `happened` (ongoing | done | dropped) and `milestone` (planned |
done | missed | dropped), with four optional fields omitted when empty — `status` (as of
`valid_from`), `target` (a milestone's planned date; expiry never reads it), `participants`
(`[{role, surface?, entity?, url?}]`, a closed role set; `surface` is an exact substring of the plain
sentence — no wikilinks in YAML) and `date_basis` (stated | turn | episode | person | written). A
done happening is **born closed** (`valid_to == valid_from`), so every reader that treats open as
current stays right; the history readers call `claims.is_event` (a grep gate enforces it). Events are
not records: they stay in FTS and citations, where they read as dated happenings,
never 'no longer current'. A milestone's slot is `(subject, milestone, slug)` across observers — the slug is its
`object`, never its `context`. Event cardinality is multi and lives in code. **Only `progress.py`
writes an event**: `write_claim` refuses the predicates, `claim_pipeline` relabels a stray label.
Dates are decided by `when.py`'s closed table; nothing relative is stored. `companion_app` is a
human origin (G141 R-PJ18): only `routers/projects.py` sets it (and the synthetic demo, which replays
app writes), no MCP tool accepts an `origin`, and `is_human` protects the person's milestones and Log
entries — an agent's different state on them coexists with a divergence item.

**Stated ends (G140).** A claim may carry `expected_end` — the date the fact itself says it stops
being true — and a G17 `due` claim's ISO-date object is its own. An agent writes it through
`cicada_write_claim`; Stage 1 through a relationship's `ends` (W7, above). A restatement carries its end onto the
claim it restates, except an agent's onto the person's own (`is_human`; review of #459), as an agent's ending never
closes it. Never a future `valid_to`, which
every reader takes to mean *closed*. Sleep's engine-free tail closes such a claim the day after its
end (`claim_expiry`), in its own `Expiry <date>` commit (`Cicada-Author: cicada`, trigger
`sleep/expiry`); a failed commit restores the pages rather than leaving them for the next
`git add -A` writer. An agent withdraws a claim IT wrote with `cicada_retract_claim`: the claim
closes and a born-closed `retracts` record keeps the reason and any cited words; a human or Sleep
claim is never an agent's to withdraw.

**Reading provenance back (G118 slice 2, server half).** Three engine-free, bank-only reads, all
built in `api/services/provenance.py` and fetched on demand — none is a Store domain, so each ETag
serves the client's in-memory cache and there is no `VersionVector` mapping: `GET
/episodes/{id}/text` (the whole evidence text, capped at 400,000 chars, with `turns[]` from the
same marker lines `speaker_kind` reads — `speaker:<label>:` included, role `speaker`; a timed
`video [m:ss]:` line is role `media` with its `t` in seconds, as a span's `t` is — each turn's
role the `evidence.kind_for` answer, so an `evidence_kind` override relabels every turn — and an
asserted `start/end/hash` or derived `focus=<entity>`), `GET /entities/{id}/provenance` (contributors from claim `authored_by` plus one
trailer-only `git log` of the page — ETag includes `git_head` — conversations grouped by
`session_id`/`source_id`, the best quote per conversation — the 50 rows with the most claims —, coverage over current
claims, and `totals.firstSaid`/`lastSaid` with `firstConversation`/`lastConversation`: when the earliest and newest of
*every* conversation was said, an episode's `timestamp` else its id's day, G194's basis — a memory export entry
(`episode_time.counts_as_activity`, #242) still counts as a conversation but never dates one — so does an agent's
relay of an inbox answer (`source: agent_relay`, 2026-10-14; it carries its conversation's `session_id`, so it groups
with that conversation); the person card's facts read
these, never the page's `created`/`last_referenced`, which are write dates), and `GET
/episodes/{id}/citations` (every claim citing the document, by a raw-text prefilter over
`entities/` — no index dependency). `/ask` citations also carry `claimId` + `evidence`, read from
the cited page rather than the index. Every claim on the wire is built by one function,
`transclusion_resolver.claim_to_model`, and carries `authorKind`/`authorProvider` from
`git_service.author_identity`. **Freshness is one rule, `evidence.span_status`:** `current`,
`grown` (an episode that was appended to after the span was minted — the Stop hook and G20 both
rewrite that way — and a turn-boundary prefix still hashes to the stored value, so the offsets are
exact) or `stale`. A stale span travels without wash offsets; a `derived` span (found by name,
`inbox_context.locate_mention`) exists on read payloads only — never in `EVIDENCE_KINDS`, never
written. The chat importer and every Local-sources draft keep each turn's time as
`turns: [{offset, ts, speaker}]` in frontmatter, written by `episode_staging` outside
`content_hash`; the Stop hook writes the same list (G141 PJ-4), and a reader treats any non-list — an
older Stop-hook episode's count — as no times. **`bank_index` never caches the sidecar (2026-10-16 perf):** it is the
key its writers keep last, and on 3,850 synthetic episodes it was 99,844 rows — 53 MB of the header cache and 3.1 of
3.6 s of a cold scan (the slow first `/status`). `markdown_parser.header` parses every other key exactly as `parse`
does (the cut block runs to the next top-level key, so a hand-edited key after it is kept); an `IndexedFile` says
`has_turns`, and a reader that places a span in its turn reads the file's sidecar through `bank_index.with_turns` (a
small memo keyed on the file's stamp) or from a parse it already makes. First `/status` on that bank: 1.4–1.8 s →
0.5 s.

G110 A2's `reply_gaps: [{offset, omitted_chars}]` records clipped final-reply gaps outside `content_hash`.

**What made a conversation a conversation (2026-10-20, `turn_extras`).** Beside the words, never in them: two
frontmatter keys written by `episode_staging` alone (the one writer of a source-keyed episode), before the `turns`
sidecar, outside `content_hash`. `turn_extras: [{offset, reactions?, reply_to?, attachments?, edited?, forwarded_from?,
code_runs?}]` — one entry per turn that has any, keyed by its marker-line start (the sidecar's offset):
`reactions: [{by, kind, emoji?}]` with `by` a turn marker (`user` / `assistant` / `speaker:<label>`) and `kind` one of
love · like · dislike · laugh · emphasize · question · emoji · sticker; `reply_to` the target turn's offset, or `{ref}`
(a source's opaque message key) when the target is in another episode; `attachments: [{kind, name, size?, mime?,
generated?}]` (kind image · video · audio · file · sticker — a name and a size, never a path or a byte);
`edited: true`; `forwarded_from`; `code_runs`. `unsent_turns: [{at, speaker, ts?, ref?}]` — where an unsent message
was (`at` = the offset of the turn it preceded, or one past the body's end) and who sent it, never its words. A draft
carries them as `Turn.extras` (a reply's target an index into the draft's turns) and `EpisodeDraft.unsent`; the stager
renders the offsets against the scrubbed body, scrubs every string, and drops a malformed value rather than raising.
**No span can move:** the body, its hash and the sidecar are byte-identical with or without extras
(`test_turn_extras`). A draft whose words did not move but whose extras did (a reaction, an unsend, a reply's target,
a re-imported export) is written frontmatter-only (`_set_extras`, counted `extras_updated` and `skipped`): never
re-queued, so a reaction never makes Sleep read a conversation again. Reactions are never turns: no body line, so never
a person's statement, an episode or anything Sleep reads. `/episodes/{id}/text` serves them per turn as `extras`
(`reply_to` as the target turn's `index`, `reply_elsewhere` when it is not here) and the episode's `unsent: [{before,
speaker, ts}]` (`before` a turn index).
Evidence readers accept only the exact marker at that recorded offset. Reader head/gap/tail blocks keep their
block indexes; the reply fragments retain the original timestamp, model and effort. Evidence `turn_at` counts
the head and tail as one original turn; a marker or touching quote is nobody's words
and becomes `reasoning`. Offsets into retained text remain exact; see `capture-and-sleep.md` for the caps.

Round 4 (C2–C4):

- Every claim on the wire also carries `recordedTs` (stored on MCP writes only), and
  `authorModel`/`authorEffort` for a harness write. These are joined by
  `turn_authorship.TurnAuthorship`: the claim's session → its capture episode → the last person's
  turn at or before `recorded_ts` → the agent turn that answered it, with both sides floored to the
  second.
- An `assistant` span carries its turn's `model`/`effort`.
- A harness contributor lists `models: [{model, effort?, beliefs}]`.
- `/episodes/{id}/text` carries `agent` (the most recent agent turn's, null when that turn names
  neither) and per-turn `model`/`effort`.
- A watch episode's `/episodes/{id}/text` also carries `watch: {basis?, engine?, fidelity, authorModel?, authorEffort?}`
  (G162; `fidelity` is `approximate` for `video_link`, `other` and an absent engine, else `verbatim`; the model is the
  same turn join, from the `describes` claim that cites the episode) and each `media` turn its `fidelity`; `/citations`
  rows of kind `media` carry it too.
- `claim_to_model(claim, *, turns)` takes the request's join as a required keyword.
- `AUTHOR_SHAPE` also rides `/episodes/{id}/text` and both `/projects` ETags.

**Optional frontmatter keys**, each with a narrow meaning — don't conflate them:

- `lat:` / `lon:` with `coordinates_by:` (`geocoder|person|unfound|none`) and `coordinates_at:` — a place's position, stored
  once (ruling 48 part 6, 2026-10-29; `place_coordinates`). The app resolves it with the Mac's own geocoder and posts
  it; the backend never geocodes. `coordinates_by: unfound` (the geocoder found nothing; Cicada's upkeep) or `none` (the person took the pin back) stops every
  automatic resolve; only the person's click places it again. A private place (address-shaped, a home word, failing
  ruling 44's local test) is placed only on that click. The shared name rule (`org_sites.proper_name`) reads the
  particles da, do, das, dos, di, du, van, von, der and le as part of a name (owner, 2026-10-29), so "Jardim da Estrela"
  is a public place; a person with a particle still needs the encyclopedia test (the local test never says public). `page_blocks.coordinates` serves the pair; the long forms
  `latitude:`/`longitude:` are read too and dropped when a write stores `lat`/`lon`.
- `in_short:` — `{text, written_at, model, conversations, article}`: "In short", the 2–3 sentences Sleep's tail
  writes for a page with ≥ 400 words of article and ≥ 5 conversations in 30 days (ruling 48 part 5, `in_short`).
  Derived and regenerated when the article's hash (`article`) changes; never prose, never hand-edited (no editor
  offers it; `cicada_edit_page` changes only the prose). Committed alone as Sleep (`In short <day>`,
  `sleep/in-short`, the model as `Cicada-Author`).

- `repos:` — links a project/directory entity to local git checkouts. The page only ever *declares*
  which repos; **the backend never runs git, stats or resolves a declared path**. `GET
  /entities/{id}/repos` serves the declarations (path exactly as written), `this_device`, and per repo
  `on_this_device` — `local_refs.is_this_device`, the one device rule: no device or a word like `Mac` is this
  Mac, else any of its host, local host or computer names, folded (case, `.local`, punctuation); the app's
  `GitRunner` runs one fixed read-only list (`repo_context.REPO_COMMANDS`, pinned on both sides by
  `api/tests/fixtures/repo_commands.json`; CLT/Xcode/Homebrew git, never the `/usr/bin/git` shim) in the
  ones on this Mac and posts the raw outputs to `POST …/repos/observed`, which refuses any undeclared path
  and parses them with the one parser, `repo_context.parse_snapshot` (a refusal is `denied`, and the card
  names Files and Folders). Only the last observation per `(path, device)` is kept —
  branch, dirty, ahead/behind, status, when — in `$CICADA_HOME/repos/<bank>.json`, **never in a bank**.
  `_state.md` renders that cache: `repos_probed_at` is the oldest observation shown, one older than 7
  days reads `state: stale`, and no time sits inside a block (R1). The MCP tool `cicada_repo_context`
  still probes live, in the process the agent harness launched.
- `sources:` (G61) — *where to look a fact up*, distinct from `source_episodes` (where a belief came
  from) and from the body's `## Links`. Keyed on `(ref, predicate)`, so one link can serve two facts.
  A conflict card's `hint` is **derived at read** from them (`fact_sources.served_hint` — the wire,
  the MCP render and the lexical row), never stored since G61 phase 2 S0, and its voice follows
  `added_by`: "You said …" only when the person added it; "Claude Code added …", "Cicada found …",
  "An agent found …" otherwise, the ref always in the sentence. An older item whose sources no longer
  match keeps its stored hint. Each entry is `{ref, kind: url|path|note|app|repo, predicate?, access?,
  added_by, added_at, accepted?, only_me?}` (phase 2 S1): `access` (`public|signed_in|local|unknown`)
  is stored only when stated, else inferred at read (`fact_sources.effective_access`: a refused or
  login host is `signed_in`, a path or repo `local`, an app `signed_in`); `accepted` marks an
  agent-found source the person took; `only_me` is the person's "Only I know" for one predicate —
  never a hint. The person's repeat of an entry applies those three; an agent's never changes one.
  Stage 5.56 attaches a URL found verbatim in a new Stage-1 claim's cited span as a source for that
  predicate (`added_by: <model>`, zero LLM) when the predicate's `locus:` is `world` or `artifact` —
  the vocabulary's where-the-truth-lives marking (seed + bank map, the most conservative winning:
  `person` > `artifact` > `world`; unseen is `unknown`). Nothing is fetched. An `addressbook://` ref reads
  'Their card in your Contacts (…)' (R-SR16), and the entity card names it "Their card in Contacts", the id only in
  the tooltip (DR-54).
  **A living set (G61 S3-a, 2026-09-30).** A page holds MANY sources, per fact, capped (`MAX_SOURCES` 30, `MAX_PER_PREDICATE`
  8; past a cap an agent's add is refused in words, the person's never is). `fact_sources.rank` is the one function every
  reader that must pick uses (the person's, then one they took or Cicada's read confirmed, then Cicada's, then an agent's;
  the owner's own page counts only what the person added or took); `source_trusted` is the trust rule. Three more optional
  keys on an entry: `origin: remote:<id>` (a connection's own entry — what ownership compares), `entity: <page id>` (the page
  that knows more about this source — its own memory node; validated, never creates a page, a stale id reads as none) and
  PR2's `verified`. **Ownership:** an agent (`cicada_change_source`) changes or removes ONLY an entry it added
  (`fact_sources.owns_source`); never the person's, one they took (`accepted`), an `only_me`, Cicada's own or a Sleep model's,
  and the unidentified `agent` label owns nothing; a connection owns exactly its `origin`, a local agent never a remote app's
  and the reverse. **Removal is remembered:** the entry leaves `sources:` and a row joins the page's `sources_removed:` (≤ 20,
  newest kept; `{ref, predicate?, by, at, reason?}`; git keeps the history, the row is what makes it stick; a replace
  (`new_ref`/`new_predicate`) tombstones the old key too). Today the writers that respect it are `attach_cited_urls`, `cicada_write_claim(sources=)`,
  `cicada_add_source` and Cicada's own DOI/skill-page adds (a refusal there never fails the page write); and (G61 S3-b) Stage 1's site proposal (`fact_sources.propose_site`) and the website backfill (`site_sources`).
  `website` matches by site. An agent's
  add (`cicada_add_source`, `write_claim(sources=)`) is refused what the person or Cicada removed but may put back what an
  agent removed, and the reply says who removed it and why; the person's add clears the tombstone, and the person's removal
  (`POST /entities/{id}/sources/change`, or the older index DELETE) writes one too. A ref the scrub would alter is REFUSED, not
  stored redacted. `entity_merge` carries `sources` and `sources_removed` to the winner and repoints other pages' `entity:`.
  `entity:` is filled for existing sources by exact match only (`source_links`: a URL whose `url_hash` is a saved page's, a path
  equal to a directory page's own frontmatter `path:` exactly — not a path found in its body), never over a set link or one the person
  or an agent explicitly cleared (`entity_unlinked: true`, stamped by an unlink, removed by a later link or replace), on the Sleep tail and `POST /maintenance/link-sources`, one
  `cicada`-authored commit (`Source links <date>`, triggers `sleep/source-links`, `maintenance/source-links`). The graph draws a
  linked source as a read-time edge labelled by its predicate (never persisted, like `has repo`; `kind: "source"` on the link,
  which the person map and "What's happening" skip — a source is where to look, not a relationship); the card's row wears the linked
  page's picture and offers "Open page ›". The person's three source routes answer 409 while Sleep runs; `cicada_add_source`
  is refused then too (it used to write uncommitted). The card reads a page's sources with the beliefs each backs (the
  page's current claims of the source's predicate), its non-source `## Links` and its conversations by app in one
  read, `GET /entities/{id}/sources/overview` (`page_sources`, owner 2026-10-14; `api.md`). A Contacts card row offers only Remove on the card.
  **Every page's added sources in one read (G61, owner 2026-10-26).** `GET /sources/where-to-check` (`source_roster`)
  lists the sources the person (`added_by: user`) and their named agents (a `source_overview.HARNESS_LABELS` harness)
  added on live pages, newest first, capped at 500 with the total — Cicada's own, a Sleep model's citation, the
  engine-free step's `agent` proposals and Contacts cards stay on their pages. Engine-free, read from the frontmatter
  cache, ETag over `entities` plus `source_roster.SHAPE`; it writes nothing — the Sources area adds and removes through
  the page's own routes, so `fact_sources` stays the one writer.
  **Re-checked, dated, the newest evidence wins (G61, TODO ruling 26, owner 2026-10-14).** A tracked source (trusted, not
  `only_me`, a `url`) keeps its re-check state on its own entry: `refresh: {at, outcome, good, episode, hash, changed?,
  asked?, tries?, blocked?, misses?: [{at, outcome}], dead?: {since, at, outcome}}` and the person's cadence
  `recheck_days` (7–365; 30 when absent). `source_refresh.due` lists what is due (asked, changed, never, a failed read's
  retry, cadence) from the frontmatter cache — no fetch, no model; `GET /sources/due` serves it with who works each and,
  for the agent's, the switch it waits for; `GET /entities/{id}/sources` adds `refresh`, `recheckDays`, `tracked`,
  `refreshChecker`, `refreshDue`. A reading that states the fact writes a `source-refresh` episode (processed from birth,
  untimed in `episode_time`: a re-check is not a mention) and a claim `{origin: source-refresh, source_trust: external,
  observer: cicada|agent, valid_from: <capture day>, evidence: a page-kind span into that episode}` whose text says what
  changed, from where and when ("role updated <day> from <host>: …, was …"). **The fold** (`source_refresh.fold`): a
  belief is dated by the day it was last said (`said_on`: a re-check's own by its capture, a conversation's by its latest
  dated episode, a live write by `recorded_at`; a memory export entry alone is undated); a capture after that day closes it
  (`valid_to` = the capture, `superseded_by`), **the person's own words included**; a belief said after the capture stands
  and the page gains nothing; the same day or no date asks ONE `kind: divergence` question (trigger
  `sleep/source-refresh`, both sides and dates; keep / update / both). Closing an older value needs a predicate the
  vocabulary KNOWS is single-valued (Stage 3's own oracle, `predicates.build_cardinality_fn`); any other (`works-at`, and
  every unseen one such as `role` or `studied-at`) gains each value the page states beside the others, and a value
  closes only on the page's own `ended` evidence under the same dating. **Dead:** two
  visits in `MISSES` (`not_found | gone | parked | moved`) at least 7 days apart set `dead` (the first strike's day as
  `since`); `good`/`episode` keep the last good capture; a good visit clears the strikes; a dead source is due only when
  the person asks. The card's overview serves `updates` (≤ 8, newest first: value, was, day, site, current, ended;
  `SHAPE` page-sources-2). The tail's commit is `Source refresh <date>` as `cicada`; the person's click
  (`POST /entities/{id}/sources/refresh`) commits as `cicada` with trigger `user/companion_app`, its cadence change and
  a walled source's "asked" as `user`; an agent's reading as its harness.
  **A citation is not a source (owner refinement, 2026-10-16; TODO ruling 27).** A web lookup that settles a question
  about a public thing (`web_settle`, features.md) cites the page it found — the URL and a short quote — on THAT claim
  only: a `web-check` episode (`source: web-check`, `processed: true`, `checked_ref`, `checked_host`, `item_id`,
  `entity_id`, `checker_kind`; body `assistant: Looked up <name> on the web.`, then `attachment [<host>]: as <checker>
  read it at <url>` and `> <quote>`; untimed in `episode_time` — a lookup is not a mention) and the claim's `page`-kind
  span into it, so the link shows wherever the claim's
  evidence shows. It is **never** written to `sources:`: it joins no re-check set (`source_refresh.due` never sees it),
  makes no site trusted (`fact_sources.trusted`) and drives no logo (`logo_service.domain_for` reads only a trusted
  `website` source). The person may promote it with one tap ("Track this source" under "Settled by a check"), which is
  the person's own `POST /entities/{id}/sources` for the claim's predicate — never automatic. The claim is observer
  `agent`, `source_trust: external`, `origin: web-check`, `authored_by` the model or harness that looked, confidence
  0.8, its id `clm_<day>_web_<hash>`; for a conflict the other open option claims close the same day
  (`superseded_by` it) and the winning option's own claim is left as it was — a type question settled on the item's
  own `both` option writes one such claim per option and closes nothing; a name with no page is held on its pending
  line (`pending_store.hold`), never given a page. The question moves to `inbox/settled/<id>.md` (its frontmatter and
  body kept, plus `settled: {at, by, by_kind, scope, ref, host, quote, answer, predicate, entity_id, entity_name,
  claim_id, claim_ids, episode, held, closed: [{id, before, after}], option_key?, engine?}`); every inbox id allocator
  counts those numbers, so the undo can put the question back under its own (`web_settle.undo`, which takes back only
  the claims in `claim_ids` — from the pending line or the page — and the closures whose claim still reads as `after`;
  the episode stays; the question returns with `web_check: undone`, so no check settles it again).
  **Light web context (TODO ruling 44, owner 2026-10-27; G121; `web_context`).** A public page gets cited, dated
  world-tier claims, kept current. *Who:* `company`, `tool`, `location` on the local test (a public proper name, no
  person's or project's name in it, not the person's own — `org_sites.proper_name`, `_OWN_THING`, an owner claim that
  founded/built/owns it, or a claim on the page saying the owner or one of their projects leads, owns or contains it —
  `led-by`, `part-of` … pointing at them, `_OWNERSHIP`); a `concept` or a `person` only when, after the local test, Wikidata has exactly ONE item that
  IS the name, of the right kind (a human for a person, not one otherwise), with a Wikipedia article. A person's local
  test, with nothing sent: a full name, not relation-shaped or role-only (`unnamed`, `owner_roles`); no relation to the
  owner on either page that says they know each other — met, talked or messaged, friend, family, partner, colleague
  or classmate, a contact, invited by, interviewed by, taught or supervised (`_ACQUAINTANCE`; being inspired by,
  reading, watching, quoting, citing, following or admiring their public work is not acquaintance); no sentence of the
  prose naming the owner (a surname the subject shares excepted) or "the user"/"you" with such a word; no conversation
  from a personal channel (`imessage`, `email`, `linkedin` …); and a public cue on the page — a public role (founder,
  author, researcher …) or public work (a talk, a tweet, a book, a video, a role at a company). A Wikidata error body
  or a failed request is `lookup_failed`: private for now, never cached.
  Failing it, the name reaches no service. Never the owner, a `project`, `skill`, `directory`, `deadline` or `media`
  (ruling 30's saves). Wikidata's answer is cached outside every bank 90 days. *What:* one engine call per page on the
  plan's own web search (`web_lookup.engine_for`'s plan branch; a metered key is `metered_only`, skipped in words), every
  reported search one of the pinned queries — the name plus at most one category word from Cicada's own description
  (never for a person), and for a deep lookup the name plus "dates" / "deadline" — or nothing is written. Facts come back
  as `{predicate, value, as_of, url, quote}` from a closed vocabulary per type (`description`, `works-at`, `role`,
  `known-for`, `headquartered-in`, `founded`, `led-by`, `industry`, `status`, `owned-by`, `made-by`, `latest-version`,
  `license`, `pricing`, `located-in`, `part-of`; deep adds `deadline`, `starts`, `ends`, `application-opens`, `edition`,
  `takes-place-in`); a fact citing a walled or refused page (`web_settle.check_ref`) or naming a person of the bank is
  dropped. *Depth by use* (`use` = conversations + 2 per current stated relation + 2 for a mention in the last 30 days):
  a line (≤ 2 facts, one search), `standard` at use ≥ 4 (≤ 4), `deep` for a current commitment relation — applied,
  attending, registered, a deadline (≤ 8, three searches). *Write* (`apply`, one commit `Web context <date>` under the
  model, trigger `sleep/web-context`, or `person/web-context` for the click): a `web-check` episode (`check_kind:
  context`) with one `attachment` + quote per fact and each claim's `page` span into it (never `sources:`); claims
  observer `agent`, `source_trust: external`, `origin: web-context`, confidence 0.8, id `clm_<day>_ctx_<hash>`,
  `valid_from` the source's full date or today; an open world claim of the same predicate whose value the lookup does not
  name is closed today (`superseded_by`) — history stays on the page and in git — unless it points at the person (its
  object is the owner's page or a project page: protected whatever its evidence) or is the person's own words
  about their own life (it cites their words — `user`/`speaker` evidence, `user_stated`, their own origins — AND its
  object is the owner's page, its text names the owner, or its predicate is `locus: person`): then the predicate is
  `protected` and nothing is written for it. What the person said about a public thing's world fact (a public figure's
  employer) is replaced like any dated world fact. A fact on file that the results say is over with nothing in its
  place comes back `ended: true` and is closed (`valid_to` the source's date, never before the claim began) with no new
  claim — a value that only says something ended ("Left X") is dropped; an end the person takes back is remembered too.
  An unchanged value is `confirm` (memo only). One record `inbox/settled/ctx-<n>.md` (`kind: context`,
  `settled: {group: check, …, claim_ids, closed}`) lists it under "Settled by a check"; `POST
  /inbox/settled/ctx-<n>/undo` (`web_context.undo`, `Web context undone`, as `user`) withdraws the claims, reopens what
  is still as it left it, and remembers each value as a hash so no lookup writes it again. *When* (`plan`, `due`): a page
  never looked up first (`unchecked` when it holds model-knowledge world facts, else `new`), by use; then `recheck` when
  the memo's day is older than the most volatile predicate's base (role, price, deadline 30 days; description,
  headquarters 180; founding: never) ÷ (1 + log2(1 + use)); no conversation in 180 days → only on request. The memo is
  `$CICADA_HOME/web_context/<bank>.json` (page ids, days, enums, hashes). *Budget:* `web_context_per_run` (default 6)
  lookups and ≤ 20 Wikidata public tests a run, behind `CICADA_ALLOW_CONNECTOR_FETCH`; `POST /entities/{id}/web-context`
  is the person's "go deeper" (deep, one page, ungated by the connector switch, same test). Telemetry: `web_check` rows
  with `action: context | context_skip | context_undo`, ids and enums only.
  **Why it matters to you (ruling 44; `page_relevance`)** is derived on every read, never stored: a stated relation
  between the owner and the page (either page, the owner's ledger included) or a claim citing the person's own words,
  tense from the claim (closed → was, starts later or a plan/intent predicate → will be, else is; an event (G141)
  from its own status — a done happening "<what> on <day>", never "until", a planned milestone will be, only its head
  counts); else "No personal relation on the record" with the conversation count and last day. Served as `relevance`
  on `GET /entities/{id}` and as one line at the end of `cicada_recall_detail` (not on the owner's page).
  **Sleep's own settles (ruling 29)** share `inbox/settled/`: `settled: {group: sleep, at, by, by_kind: sleep, rule,
  reason, answer, entity_id, entity_name, predicate, evidence?: {episode, start, end}}` — a span into the person's words,
  never a copy — committed in the resolver's own commit, which is what `inbox_tend.undo` reverses (three-way); the
  question returns with `sleep_settle: undone`.
  **Where to check (G61, G208, ruling 36 D5, 2026-10-22).** The name sources carry in every surface: *a link where the
  current state of this thing can be checked — a profile, a personal site, a publication list, a repository or any
  page; Cicada re-checks it on a schedule and agents check it before answering about the thing.* The key stays
  `sources:`. **Proposals:** an entry inferred rather than named carries `proposed: true` and `evidence` (`{episode,
  start, end, kind?}` — a span, never a copy — or `{page: true}`); `fact_sources.is_proposed` is the one test. A
  proposal is never trusted, never the person's own account (`person_photo.is_own_account`), never tracked
  (`source_refresh.tracked`); taking it (`accepted`, from the question or the card's `sources/change`) drops `proposed`
  and keeps `evidence`. Two writers: an agent's `cicada_add_source(inferred=true, evidence=[{episode, quote}])` (`mcp.md`;
  a profile ref stored in its canonical form, the quote located or dropped) and **Sleep's tail step**
  `source_proposals.propose` (`_where_to_check_safely`, after the LinkedIn and Contacts rematches, before any poll):
  engine-free, no fetch, per active page — a **person** page's GitHub, X, Instagram, LinkedIn, Google Scholar or ORCID
  profile URL (`source_proposals.profile_of`, one canonical form each) written in the page's own text, or in a line of
  the person's OWN turn (`user`, not an agent's saved note) in one of the page's newest 40 conversations that also
  names the page; a **project/tool** page's GitHub repository whose name is the page's own; and (vision item 1,
  2026-10-28) on a **project, company, concept, tool or place** page, every **link the person saved whose read is about
  the page** (`source_proposals.saved_link_hits`): a saved-link episode (`url` + `media_entity_id`) that one of the
  page's live claims rests on, or a saved-link page whose live `about` claim (link recon) names it (`about_index`, one
  substring-gated pass over `media-*.md` a run). The saved URL as it is on the record, filed under no predicate (where
  to check the page as a whole), `entity:` the saved-link page, its evidence the person's reason when they gave one
  (`saved_why.reason_span`: `{episode, start, end}`, read "in your own words") else `{episode, kind: "save"}` ("a
  link you saved"). Its `entity:` draws no graph edge while it waits (`graph_builder` skips every proposal, ruling 36
  D5). Never on a person page, never a link `reading_hosts.classify` refuses or calls walled (a private
  workspace, a secret-bearing link, a video, a paper, an AI app's page), never a search engine's results page. Never a URL from a name,
  never a handle off a saved post's path. Skipped when the ref (in any spelling of the same profile) is already a source
  or in `sources_removed` under any fact, or past a cap; ≤ 4 a page a run; pages dirty before the run are skipped; one
  `cicada` commit `Where to check <date>` (trigger `sleep/where-to-check`), restored on a failed commit. **One grouped
  review (owner 2026-10-22, review of #422 — the dry run would have added 36 questions to an inbox of 218):** every
  waiting proposal, an agent's too, is a row of ONE item — `kind: clarification`, `asks: sources`, `review: true`,
  title "Confirm N links", `rows: [{id, page, page_name, page_type, ref, predicate, link_kind, label, added_by,
  evidence?}]` (`id` a stable hash of page + link), options `yes` / `no` (all rows), `required_input: choice`; the step
  adds and removes rows every run and removes the item when none waits, so it is idempotent. The one exception is a
  link Sleep may settle (`source_proposals.strict_quote`, below): it waits in a one-row item of its own (no `review`,
  `entity_id` its page), which Sleep's tend settles through the resolver — undoable like every settle; an undone one
  (`sleep_settle: undone`) stays the person's one-row question and is never folded into the review. **The answer**
  (`inbox_service._resolve_where_to_check`): `row: <id>` on resolve answers that row, none answers every row; `yes`
  takes the row's proposal on its page, `no` (or a dismiss) removes it with a `user` tombstone, so nothing proposes it
  again; the item keeps the rows not answered; `skip` writes nothing; committed as the person's answer (trigger
  `inbox/clarification/resolved:yes|no`). `GET /inbox` serves `rows` (camelCase) and `review` on these items.
  **Sleep settles only by ruling 29, strictly** (`inbox_tend` rule `named_account`, engine-free, `strict_quote`): the
  evidence is a located line of the person's own turn; it carries that very link; it names exactly ONE page, this one
  (no other page's name or alias is in it); and the link's account name (GitHub, X, Instagram, LinkedIn) is the page's
  name or an alias, normalised — co-occurrence is never proof ("<page-a> told me to follow <someone else's link>" goes
  to the person; so does an id-only profile such as Scholar or ORCID). Anything else is `person_only` (no engine, no
  record read, no trace row may settle it). **Wire:** `GET /entities/{id}/sources` adds `proposed`, `evidence`, and — derived for the card's chip row —
  `linkKind` (`github | x | instagram | linkedin | scholar | orcid | repo | contacts | website | app | path | note`,
  `source_proposals.link_kind`), `label` and `iconSite` (the site key `…/sources/icon/{site}` serves, null wherever that
  route 404s — always on a person's page, G159). A dry run (`scripts/where_to_check_dry_run.py --memory <bank>
  [--summary]`) lists what the step would propose, reading files only.
- `website` (G61 S3-b) — the official-site ROLE: a `sources:` entry with `predicate: website`, many allowed. Stage 1 may
  propose ONE for a `company`, `tool` or `project` (an optional `website` field on the extracted entity;
  `site_sources.sanitize_website` keeps only an https origin of a public host that is not a platform (`PLATFORM_HOSTS`:
  code hosts, encyclopedias, social, profile and article hosts) or a walled one, and drops it for every other type); the
  create branch stores it UNVERIFIED (`added_by: agent`, no network), never over a tombstone. An engine-free backfill
  (`site_sources.candidates`) proposes one for a page that has none from ONLY its own current `website` claim or a
  `## Links` URL whose host is the page's own name (or whose title says official/homepage/website) — never a domain
  guessed from a name. Cicada's own read confirms it (`link_enrichment.fetch_identity`, sharing `_stream_html` with
  `default_fetch`: 4 s, ≤ 512 KB, no cookies, `net_guard`, a block never retried; a walled or platform host is refused
  before any request): `judge` needs the page's name (or an alias, company suffix aside, every word in any order) whole-word
  in the site's title or `og:site_name` AND two distinctive words of its own summary on the page. **The destructive
  outcome needs positive evidence:** `mismatch` (removed and remembered in `sources_removed`, by `cicada`) only when the
  name IS on a substantial page but two or more of the summary's words are not (the namesake); everything merely
  unproven — no name found, a thin JS shell, a redirect to another domain (the final page is judged), a 403/bot block or a
  consent page — is `unconfirmed`: kept with `checked: {outcome: unconfirmed}` ("not confirmed", re-read after 30 days,
  one tap of "Use this site" = `accepted` trusts it). `verified` stamps `verified: {at, how}` and `access: public`. A
  network failure is `tries` up to three nights, then `checked: {outcome: unreachable}` and asked again in 30 days —
  never tombstoned. A platform host found in a `website` entry is removed without a request (reason `platform`).
  `fact_sources.trusted` (the person's, one they took, or verified) is the only trust; nothing else draws a picture (and
  only a `company` or `tool` page draws one — and, since ruling 40, a `location` that holds a trusted site, and since
  owner 2026-10-28 (E) a `project` that holds a trusted site or repository, `logo_service.draws_logo`). The
  Sleep tail step (`sleep_cycle._site_sources_safely`: propose, then verify, ≤ 25 fetches a night, one per site) runs
  behind `CICADA_ALLOW_CONNECTOR_FETCH`, in one path-scoped `cicada` commit `Site check <date>`, trigger
  `sleep/site-check`, no engine trailer, dirty pages skipped; the run's `Report` is built first and handed to both steps,
  so ANY failure restores every page written (the G85 smear), as does a failed commit. `verify` parses and writes off the
  event loop. `POST /maintenance/verify-sites` is the person's click (ungated, at most 40 fetches — the answer carries
  `budget` and `deferred` —, 409 while Sleep runs or in a demo bank, trigger `user/companion_app`), counts only.
  **An organisation's own site, found during consolidation (ruling 40, 2026-10-26, `org_sites`).** Between `propose`
  and `verify`, the same step examines up to 40 live `company`, `tool` and `location` pages with no TRUSTED `website`
  (busiest first; ≤ 20 Wikidata lookups a night, 60 on the route) — never a person, the owner, a project, a name that is
  not a public proper name (a possessive, a leading article, lowercase words, a path or handle), a name carrying a
  person's or a project's name, or a page its description calls the person's own (`skip_reason`). **The record first**
  (no network): an origin whose site label is the page's name, an alias or its acronym — from a line of the person's own
  turn that names the page, or from the page itself (an alias that is a domain, `## Links`, a key-fact line about its
  site or domain, its current `website` claim, a link or domain anywhere in its prose, and — vision item 2, 2026-10-28 —
  a `website` entry Sleep itself first proposed that no read has confirmed yet, `sleeps_own_site` — owner 2026-10-28, D:
  the backfill's unconfirmed entry, Stage 1's official site (`added_by: agent`, `propose_site`'s fields only) and
  Sleep's own proposal held only for `homepage_unconfirmed` / `not_fetched`; an identified agent's entry is not one);
  a wikilink, camelCase or a code-like ending (`.id`, `.py`) is never a
  domain; the site is the registrable domain (`careers.<org>.edu` → `<org>.edu`). **Then one structured public lookup**:
  Wikidata (`wbsearchentities` on the page's name, then at most two proper-looking aliases; `wbgetclaims` P31/P279/
  P856/P17/P625) — exactly ONE thing whose label or alias IS the page's name, whose class reaches the page type's roots
  within five P279 steps (organisation / software-website-product / geographic place; a sited organisation counts as a
  public place), never a human, a country or sovereign state, with one official site (P856, platforms dropped; several
  agreeing items listing one site are one thing); a country the page names that is not the item's P17 is a conflict. A
  search engine's hit is never used. **Trusted** (`verified: {at, how: record | record+name | wikidata+name, why, item}`,
  `added_by: cicada`, `access: public`) only when the site's homepage names the entity in its title or site name
  (`fetch_identity`, same rail) — and, for a lookup, the item matched the page's own NAME (an alias-only match is a
  proposal, `matched_by_alias`) and two distinctive words of the page's summary are in the item's description or the
  homepage's title, site name or meta description (the namesake guard, `content_agrees`; the body excerpt was measured
  too loose on a real bank copy); the person's own located line whose link is the
  page's own name stands alone when the site exists but blocks bots. **Anything less is a proposal** (`proposed: true`,
  `evidence: {lookup: wikidata, item, reason}` or the record's span, reason `ambiguous | country_conflict |
  homepage_unconfirmed | content_unconfirmed | matched_by_alias | record_names_another_site`) that joins the one "Confirm N links" review —
  the tail re-syncs the review after the commit — and `verify` never stamps a proposal behind the person. An ambiguous
  match proposes only sites whose label is the page's name; a namesake found only through an alias proposes nothing. Only
  an entry Sleep itself first proposed for the same site (`sleeps_own_site`) is upgraded in place (never duplicated;
  its evidence kept, `proposed` dropped, so it leaves the review) — the person's, an identified agent's, a remote app's,
  or a proposal held for any other doubt is never upgraded or re-marked, and an unproposed one keeps Cicada's nightly
  `verify`; a tombstone for the site (`sources_removed`,
  whoever removed it) is never re-added; a page with a trusted site is never looked up. The why travels on
  `EntitySource.verified.why` ("Found by Cicada: official site listed on Wikidata (Q…), and its homepage names …"); the
  person undoes it by removing the source. Once trusted, `logo_service` draws the mark and `source_refresh` re-checks it
  (ruling 26). Wikidata calls are spaced 0.2 s, 4 s / ≤ 512 KB each, no cookies, `net_guard`, User-Agent
  `Cicada/1 (<repo URL>) httpx`, a 429 honoured once. The "looked up on" cache (page id, day, outcome, conversation
  count) and the P279 class cache live in `$CICADA_HOME/site_lookup/` — never in a bank; a page is looked at again after
  30 days or when it gains conversations. No model runs. `api.scripts.org_sites_dry_run --bank <copy>` lists per page
  the site, basis, trusted vs proposal, reason and logo domain, writing nothing.
- `logo:` — a domain hint for `logo_service`. Logos are cached under `$CICADA_HOME/logos/<bank>/`,
  **never inside a bank** — a logo is a derived artifact of the outside world, not versioned memory. Since G61 S3-b a
  page's domain comes from a source and never a guess: `logo:` first, else the first TRUSTED `website` source
  (`logo_service.domain_for`); no `## Links` fallback, no saved link's site, no `website` claim, no `<name>.com` guess,
  no platform or walled host, and never a `person` or `media` page (G146/G159). **The ladder keeps the largest mark**
  (vision item 2, 2026-10-28, `fetch_logo`): the site's `/apple-touch-icon.png`; then the homepage's declared icons,
  largest first (`declared_icons`, ≤ 3 asked, relative hrefs against the URL the homepage's redirects landed on); then,
  only when nothing reached `GOOD_PIXELS` (64 px on the smaller side — the app's 26 pt mark is 52 px on Retina), the
  homepage's `og:image` when it is a square-ish raster (aspect ≤ 1.25: a share banner never is); then the icon service.
  The first mark ≥ 64 px stops; otherwise the largest found wins. Every candidate comes from the trusted domain's own
  homepage, through `_get_safely`'s SSRF check, 4 s / ≤ 512 KB, raster only. A hit is stamped `ladder: 2`; a hit cached
  by the older ladder whose mark is under 64 px is asked once more (kept when nothing larger answers, and stamped either
  way), a good one is stamped on its next read — so a cached logo request reads nothing more than before (measured
  p50 0.085 ms on dev and on the branch). A replaced mark in another format leaves no orphan file. `LOGO_RULE = 2`: a bank's cache written
  under the older rule is purged ONCE (`ensure_rule`, marker `logos/<bank>/.rule`; `sites/` is spared), and a page that
  no longer resolves a domain drops its cached mark and records a miss (an explicit `website` entry outranks a bare link the person typed). `GET /entities/{id}/sources/icon/{site}` serves
  the mark of a trusted site THIS page lists (icon service only, keyed on the site, never a ref; never for a `person` or `media` page).
  **A saved link's own site icon (owner ruling 2026-10-19).** A saved link's row (Sources › a saved source) shows its
  site's own icon, asked of **that site only** — never an icon service, so no one learns what the person saved:
  `GET /sources/saved/{media_entity_id}/site-icon`, asked by the app for a row of a list the person opened (never from
  the Sleep cycle, never a whole bank; listing items fetches nothing). The site is the registrable domain of THIS link's own URL
  from the url index (`channel_items.saved_link_site` → `logo_service.own_site_domain`), for a live media page a `saved`
  source owns; a walled family, a private or reserved name is never asked (the row keeps its bundled mark or monogram).
  **Everywhere (owner 2026-10-20):** every surface that draws a saved link draws this mark (`app.md`, "One mark for a
  saved link"), and a saved link Sleep has not made a page of yet — a Waiting row — asks
  `GET /sources/saved/episodes/{episode_id}/site-icon`: the site is read from THAT episode's own `url`, only for a live,
  non-conversation episode of a `saved` source (`channel_items.saved_episode_url` / `saved_episode_site`), with the same
  gate, fetch and per-site cache. Rows name the key the mark is drawn under — `siteKey` on `GET /sources` items (shape
  `site-key-1`; only on a page the media route serves, `channel_items.is_saved_link_page`), `site` on `GET /sleep/episodes` rows (`episodes-2`) and on `GET /episodes/{id}/text` (`site1`) — from
  one function, `reading_hosts.mark_key` (a walled family's name, else the registrable domain); the icon is always asked
  by an id, never by that name.
  **Discovery, amended (owner 2026-10-20: "a lot of them don't show any logo … when I open the website I can clearly
  see a favicon in the Chrome tab").** The 2026-10-19 rule asked two fixed paths and never the HTML; it missed every
  site that declares its icon at another path, on a CDN, or only behind a redirect to www. Now, like a browser
  (`logo_service.fetch_own_site_icon`): the homepage `https://<site>/` (or `https://www.<site>/` when the bare domain has
  no public address), following https redirects on the default port — on the same registrable domain, or (owner
  direction 2026-10-20, "a picture specific to the site, not a letter"; marks-2) to the public, non-walled domain a
  renamed site moved to, which then counts as the site for the rest of the discovery (its declared icons and fixed
  paths; a fixed path that redirects to a third domain is still a miss). Every hop that leaves the saved site is first
  put to the redirect-to-wall rule (`link_enrichment._redirected_to_wall`: a `consent.` host, a known sign-in host, a
  `/login`·`/signin`·`/auth`·`/oauth2`·`/sso` path) and refused before a byte is fetched — an identity provider's icon
  is never cached as a site's (security review of #387); its `<link rel>` declarations — `icon`,
  `shortcut icon`, `apple-touch-icon` — found by one linear scan of `<link>`/`<base>` tags only, off the event loop (`declared_icons`; never the
  stdlib HTML tokenizer, which is quadratic on hostile markup — security review of #371; the first 64 tags; `mask-icon` skipped,
  anything typed or named SVG kept aside for the SVG step below; an href with an explicit port or userinfo skipped), resolved against the page's final URL or its `<base href>`, ranked light-scheme
  (or scheme-less) before dark, then the largest declared raster of at least 32 px (an apple-touch icon with no `sizes`
  counts as 180), then unknown sizes, then small ones; at most three asked; then `/apple-touch-icon.png` and
  `/favicon.ico` on the host that answered. A declared URL on another host (a CDN the page names) is asked: https only,
  through the SSRF guard on every hop, its redirects kept on its own or the site's registrable domain, and kept only
  when the content-type says `image/*` **and** the bytes sniff as PNG/ICO/GIF/JPEG/WebP; on the site itself a favicon
  served as `application/octet-stream` still counts by its bytes, but anything that says HTML/XML/SVG never does (an SPA
  answering `/favicon.ico` with its page). A `data:` raster icon is decoded only when it is base64 raster, its size
  capped at 512 KB before decoding and its bytes sniffed like a download.
  **SVG is drawn, safely (owner ruling 2026-10-20: "yes, we should draw the SVG icon safely"; amends "SVG stays a miss"
  of the same day).** Only when no raster answered — declared or at the fixed paths, so a site with any raster keeps
  it — the page's declared SVG icons (typed `image/svg+xml`, a path ending `.svg`, or `data:image/svg+xml`, base64 or
  percent-encoded; never `mask-icon`; at most two, `declared_svg_icons`) are asked under the declared-icon rules (https,
  SSRF guard per hop, redirects on its own or the site's domain, a block stops discovery), kept only when the
  content-type says SVG (on the site itself also XML/octet-stream/plain) and the bytes open as SVG, ≤ 64 KB.
  `svg_raster` then: **sanitises** in pure Python — expat with every DTD, entity declaration and external entity
  refused outright (no billion laughs, no XXE), ≤ 32 deep and ≤ 1,000 elements while parsing, rebuilt from an
  allow-list (shapes, paths, groups, `defs`/`symbol`, gradients and stops, `clipPath`, `mask`, `<style>` and presentation
  attributes, transforms); `script`, `foreignObject`, `image`, `text`, filters, animation, `on*` handlers, any `href`
  but a local `#id`, any `url()` but `url(#id)`, CSS with `@`, escapes, comments or `filter` is dropped; a `<use>` only of a local element
  that held no `<use>` (≤ 64); a mask or clip path that applies another (directly, by inline style, through a `<use>`, or
  any `<style>` setting one beside a mask or clip path) refuses the icon — each level multiplies the work; a viewBox of four finite numbers within ±1e6; the output a fresh document Cicada wrote at
  64×64 — then **draws** it with resvg (Rust; no script engine, no network code) in a child `python -I` with an empty
  environment and working directory that caps its CPU seconds (and address space where the OS enforces it — Linux,
  not macOS, where the sanitiser's expansion limits and the wall clock bound memory), reads the SVG, then sets
  `RLIMIT_NOFILE` to 0 (no new descriptor at all, so no file and no socket even after closing one of its own; a limit
  of 3 only capped the number — security review of #382), and is killed at 2 s wall clock — and **checks** the
  answer is a 64×64 PNG that is not fully transparent. Only that PNG is cached (`<site>.png`) and served; SVG bytes are
  never stored or served. Any failure is a miss, the monogram. The drawing happens after the 4 s network budget, not
  inside it. A homepage that redirects to a login host, a private or reserved name is not followed (the saved
  site's fixed paths are still asked). One 4 s budget covers the whole discovery
  (`OWN_SITE_BUDGET_SECONDS`); each hop never a login host, the body streamed with `Accept-Encoding: identity` and cut at 512 KB of raw bytes (no compressed body inflates first), DNS checked off the event loop, no cookies, raster only; 401/403/407/451 stops at once and nothing is retried
  with other headers. Behind `CICADA_ALLOW_LOGO_FETCH` (off: nothing asked, nothing recorded, the monogram). Cached in
  `$CICADA_HOME/logos/<bank>/sites/own/` — hits 30 days, misses 7, each entry stamped with the discovery's version
  `v` (`OWN_SITE_DISCOVERY` = 4: 3 for the SVG ruling, 4 for the moved homepage): a miss recorded by an older discovery — a lower `v`, or none — is asked once more, hits stay — never in a bank; any failure is a 404 the row draws
  as its monogram. This is a row's mark only: it never becomes a page's picture, and `domain_for` still takes no saved
  link's site.
  **A watched or saved YouTube video's still (owner direction 2026-10-19, Sources v4).** *"For YouTube … why don't you
  render the thumbnail of the video?"* A video in a watched day the person opened (Sources › YouTube history › a day)
  may show its still: `GET /sources/watch-history/days/{episode}/videos/{video_id}/thumbnail`, asked by the app only for a row of a
  day the person opened (as the row comes on screen, at most four at a time), never from Sleep. The backend asks **YouTube's own thumbnail host for that video id only**
  (`i.ytimg.com/vi/<id>/hqdefault.jpg`, `media_preview.YOUTUBE_STILL`, the pin a saved video's preview already uses),
  and only for an id THAT day's record holds (`channel_items.day_has_video`, one file read — never an id a request
  merely names, never a walk of the bank). Behind `CICADA_ALLOW_LOGO_FETCH`, through the ToS rail (`media_preview._get`: `net_guard` on every hop, 4 s,
  ≤ 512 KB, no cookies, raster only, a wall never retried), cached outside every bank at
  `$CICADA_HOME/previews/<bank>/watched/<id>.<ext>` with its misses (`media_preview.ensure_video_still`); any failure is
  a 404 the row draws as a quiet play glyph. A picture is not a read: no model ever reads watch history (ruling 30).
  **A saved YouTube video draws the same still (marks-2, owner 2026-10-20: "none of the YouTube stuff shows
  thumbnails, just low-res YouTube logos").** A saved list's row of a media page whose own URL is a YouTube video carries
  `video: true` (`channel_items` shape `g161-6`) and asks `GET /sources/saved/{media_entity_id}/still`: the id is the
  one THAT page's own URL names (`channel_items.media_video_id` — only a page `is_saved_link_page` admits, the site-icon
  route's predicate; never an id a request names), served by the same `ensure_video_still` fetch and cache as a watched video's, so a video watched
  and saved is asked once. Same gate, same rail; 404 = no picture. Sleep › Saved/Videos and the entity card already
  draw a video page's stored preview (`/entities/{id}/preview`, the same YouTube still pin).
  A day's videos come from `GET /sources/watch-history/days/{episode}` (`channel_items.watched_day`: title, channel,
  times, the provider's watch URL, the id, and the saved page when the person also saved it — read from the day's own
  record, nothing fetched; ETag over `sources`+`episodes`+`entities`, not a Store domain).
  **A Messages chat's face (Sources v4).** The photo a ticked chat shares (above, `messages_photos`) is also that chat's
  face on its Sources row and in its list, served by conversation: `GET /sources/messages/chats/{conversation}/photo`
  (404 for an id that is not a chat hash, a chat not ticked, or no photo; nothing fetched). `messages_photos.stamp`
  (the `photos` component) hashes every stored photo, a chat with no page yet included, so its face arrives too.
- `picture:` (G146) — the person's own choice of picture for a page: `{kind: upload, sha, ext, added}` for a
  picture they uploaded, whose bytes live **in the bank** at `assets/pictures/<id>.<png|jpg>` (their record, so it
  travels with the bank; the path is derived from the id, never read from the page), or `{kind: initials, added}`
  for "Use initials instead". Written only by `POST|DELETE /entities/{id}/picture` and `…/picture/initials`, each
  committed alone as `user`, 409 while Sleep runs; never by an agent. A merge or a rename to a new id carries the
  choice and moves the file with it (2026-10-21, "A merge keeps both claim sets" above). The app shrinks a picture to ≤ 512 px before
  it leaves the Mac; the server keeps only a PNG or JPEG ≤ 512 KB (no Pillow). `entity_picture.resolve` is the one
  precedence (the person's choice → a person's Contacts photo → the photo a ticked Messages chat shares, on its
  `person`/`tool` page → a person's public-profile photo → a brand's logo → a media page's preview → a ring monogram),
  resolved at read onto `/graph` nodes and the entity; the app's
  `EntityPictureResolver` is its twin over `api/tests/fixtures/entity_picture.json`. A person never gets a logo and no
  service is sent a private person's name (G159). **A project's mark** (owner 2026-10-28, E) is the `logo` rung: its
  trusted website's logo through the ladder above, else — only from a TRUSTED repository source (role or kind `repo`;
  never a "Confirm N links" proposal) or a GitHub URL in the page's `repos:` — the repository owner's avatar, asked
  only when GitHub's public account record (`api.github.com/users/<login>`) says `type: Organization`
  (`logo_service.fetch_org_avatar`; both requests pinned to `api.github.com` and `avatars.githubusercontent.com`, the
  ToS rail, SSRF-checked every hop). A personal account's avatar is never asked: its record is a cached miss. The
  cache entry's `domain` holds `github-org:<login>` for such a mark (`logo_service.target_for`), so the twin and the
  fixture are unchanged — the `logo` input is decided server-side as before.
  **The photo a Messages chat shares** (owner, 2026-10-16; `messages_photos`) is the chat's page's picture
  everywhere — the graph, the card, every list — rung `messages`, after the Contacts photo and before the
  public-profile photo or a logo, on `person` and `tool` pages only (the types a correspondent can be). The app reads
  it ("Share Name and Photo", `NickNameCache`, ticked chats only, `app.md`), shrinks it to ≤ 128 px and posts it to
  `PUT /sources/messages/photos` (`{photos: [{conversation, photoB64 | null}]}`; 409 for a chat not ticked, 422 for
  anything but a PNG/JPEG ≤ 256 KB within the upload's pixel bounds; demo bank 409). The bytes are a cache at
  `$CICADA_HOME/pictures/<bank>/messages/<conversation>.png` with `meta.json` (`{sha, ext}` per conversation) —
  **never in a bank, never in git, never sent anywhere**; nothing is written to a page. Stored by conversation and
  drawn at its **linked page**, derived at read (`messages_photos.links`): the newest live sitting's decided
  `correspondent` record — first the page its address-book card names (`contact_identity`, below), then
  `correspondents.find_page` — the rule Stage 2 and `waiting`'s `page` use — so a page
  Sleep creates later, the person's mark or its removal moves the link with no second post; an undecided chat links
  nothing. A changed photo replaces it (new `?v=<sha>`), a post of `null` removes it, unticking removes it
  (`messages_photos.forget`, from `PUT /sources/messages/settings`). Served by `GET /entities/{id}/picture`. Its stamp
  rides `/sync/version`'s `photos` component and `graph_builder`'s cache key, so a photo or a link that moves
  re-renders the node. The person's choice and a Contacts photo outrank it; `person_photo` asks nobody while it shows.
  `POST /entities/{id}/picture/pdf` (a `media` page only; ≤ 32 MB; nothing fetched) is the same write with a PDF the
  person gave: `pdf_page` renders page 1 in the backend — the bundled PDFium wheel (`pypdfium2`) in a child process,
  encoded to PNG with `zlib`, ≤ 480 px wide and ≤ 1024 px tall — and the PNG is stored and committed as an upload
  (the PDF itself is not kept). This is how a paper (no fetched preview, G133) gets its first page as its picture.
- **A media page's preview** (`media_preview`) — the page's own picture, fetched once by the backend and served from
  `GET /entities/{id}/preview` (ETag; 404 = none), never a provider URL the app loads itself. The source, from the
  page alone (`source_for`): `media.thumbnail` (the saved page's `og:image`/`twitter:image`, made absolute against
  `media.url`, or a provider's oEmbed `thumbnail_url`) → for a YouTube video with none stored, the video's standard
  still `i.ytimg.com/vi/<id>/hqdefault.jpg` from the id `video_urls.resolve` validated (a still, not the video or a
  stream — G162) → a direct `.pdf` link the person saved (never arXiv/DOI, never a walled host), page 1 rendered by
  `pdf_page`. The wire carries `/entities/{id}/preview?v=<key>` (`key` = sha256[:12] of the source, so it moves only
  with the page) on the node's `picture`, as `pictureInputs.thumbnail`, and as `preview` on `EntityMedia` and on each
  `/sources` item (the person's own upload wins there too, `entity_picture.media_picture`). The cache is
  `$CICADA_HOME/previews/<bank>/<id>.<png|jpg|gif|webp>` plus a `<id>.json` sidecar (`{hit: {key, ext, at, kind},
  miss: {key, at, reason, transient}}`, no URL), **never in a bank**: a hit is kept for good while its source is
  unchanged and is still served when a changed source cannot be fetched (a dead link never blanks the card); a miss is
  remembered per source for 7 days, a transient one (timeout, 429, 5xx) for an hour. The fetch rules are in
  `network.md`.
- **A person's public-profile photo** (G159 amendment, owner 2026-10-09; `person_photo`) — the `profile` rung, `person`
  pages only, asked ONLY with an identifier already on the page or the person's own record, never one derived from a
  name: the owner's own email (the one typed in Settings, `owner.json`, used only on the page marked `owner: true`; the
  bank holds no one else's address — Contacts posts booleans, R-SR8, and a claim's value is a model's word), then the
  best-ranked GitHub profile link (`https://github.com/<username>`, one path segment) among the page's `sources:` that
  somebody gave as the person's OWN account (`person_photo.is_own_account`): the person's or one they took, with no
  fact attached, a profile predicate or `website`; or an identified agent's with no fact attached or a profile predicate
  (`PROFILE_PREDICATES`); or the LinkedIn link the person's connections export added on a confident match (`match:
  name|link`, owner 2026-10-17; an alias-only match waits for the person to take it) — otherwise never Cicada's own
  writers, an unidentified proposal, an "Only I know" note, or a link Stage
  5.56 attached from a claim's cited words (always under a `world`/`artifact` predicate, which no profile predicate
  is; a test pins it), and never a proposal still waiting for the person (`proposed: true`, "Where to check" below) —
  then, while `CICADA_ALLOW_PERSON_PHOTO_PROXY` is on (on by default since ruling 36 D5, 2026-10-22; off from
  2026-10-09), an X profile link, an Instagram profile link (D5) and a LinkedIn `/in/` link, asked through the avatar proxy within an
  install-wide daily budget (`network.md`). **A public figure's encyclopedia portrait** (owner 2026-10-28, C) sits
  between the GitHub avatar and the proxy: only for a page ruling 44's full public test called public — the memo outside
  every bank (`$CICADA_HOME/web_context/<bank>.json`) now keeps the ONE matched Wikidata item with the verdict
  (`web_context.public_items`; a match cached before the item was kept is asked once more) — the item's image (P18) is
  asked of Wikidata by item (`org_sites.wikidata_get`) and the file of Commons by its own name
  (`commons.wikimedia.org/wiki/Special:FilePath/<file>?width=256`, redirects only to `upload.wikimedia.org`, Wikimedia's
  User-Agent with the project's contact). The local test runs once more just before the ask, in a thread (err
  private), and every Sleep run re-runs it for each held match before any gate (`web_context.recheck_public`, sends
  nothing; review of #510 — `plan` verdicts only due pages). A match not passed within `PUBLIC_FRESH_DAYS` (14) draws
  nothing, and a page that fails leaves the memo, so its identifier set changes and the stored portrait goes. The
  person's name is never sent as a query; the Commons file name P18 holds may contain it. Never the owner's page or a demo bank. Fetched once, on demand, by `GET /entities/{id}/photo` (never by
  `/graph`, never by Sleep) and cached at `$CICADA_HOME/pictures/<bank>/people/<id>.<png|jpg>` with `meta.json`
  (`{key, fetched_at, miss, transient, ext, sha}`; `key` is a hash over the identifiers, so the email's hash is never
  stored and a changed or removed identifier re-resolves — a removed one drops the copy). A hit is kept; a miss is
  retried after 30 days, a failed connection after a day. The rung is offered while the page has an identifier and no
  fresh miss under it. Its URL is `/entities/{id}/photo?k=<key>` (the identifiers' hash) until a copy is stored and
  `?v=<sha>` after, so a changed identifier is always a new URL the app's URL-keyed cache has never seen.
  `/sync/version`'s `photos` component (the index's mtime plus the misses past their window) is in `/graph`'s ETag and
  `graph_builder`'s cache key (`VersionVector` maps it onto `.graph`). The person's
  upload outranks it and "Use initials" (kept in the bank) removes it for good. A demo bank asks nobody and never offers
  the owner's email (`demo_guard.is_demo`). The fetch's rules are in `network.md`.
- **One person across sources (owner 2026-10-28, `contact_identity`).** No second identity table: a chat's records
  carry the ONE address-book card the app found for a handle, by its Contacts id — the `correspondent` record's
  `contact` (a one-to-one chat with a person) and each `participants` row's `contact` (a group member; never an agent
  member) — and a page the Contacts sync matched carries that card's `addressbook://<id>` sources. A card id names the
  one person page whose sources carry it (never the owner's page, never a card two pages carry). The id is the opaque
  `CNContact` identifier the sync already stores; only a UUID-shaped id passes (`<UUID>` or `<UUID>:ABPerson`) —
  a phone number, an address, a `tel:` link, digits with an extension or a short code are refused (`clean_card_id`),
  so no handle ever lands in a bank. A field the app leaves out (or sends as null) keeps the stored card; `""` — the
  app read Contacts and none or several cards hold the handle now — clears it, for a one-to-one chat and a group
  member alike. The live chat sources (`chat_live`: WhatsApp, Telegram) keep the same two records the same way; a
  chat is a sitting whose origin is in `chat_live.CHAT_ORIGINS` (live Telegram chats are `telegram-chats`; plain
  `telegram` is the bot's notes, never a chat).
- `contacts_photo:` (G154, read by G146) — `{sha, ext}` on a `person` page Contacts matched (`ext` jpg|png, jpg when
  absent); the thumbnail itself is a cache at `$CICADA_HOME/pictures/<bank>/contacts/<id>.<ext>`, never in a bank.
  Written by the Contacts sync only (`contacts_local.photo_path`, the same path `entity_picture.contacts_path` reads).
- `owner: true` (G117) — marks the one `person` page as the bank's owner; `owner_identity.
  resolve_observer` is what decides which page gets it, and every user-stated claim's `observer`
  field is that resolved value. **Every new bank starts with it** (`bank_registry.create_bank` →
  `owner_identity.seed_owner_page`, its own `cicada` commit; never the demo, which writes its
  own): the machine-level name from `owner.json` when one was saved (a name and an id, never
  another bank's knowledge), else a neutral `Owner` page (`owner_placeholder: true`, id `owner`,
  the id `resolve_observer` already answers with) opening "The main person this memory belongs
  to." `name` stays the plain name — Stage 2 matches a mention to a page by `name`, so a stored
  "(you)" would stop the person's own name from resolving — and the app renders "Name (you)" from
  the flag. `PUT /settings/owner` **adopts** a placeholder (renames it, keeps its id and claims)
  instead of writing a second owner page. Beliefs accrue through chats and consolidation. The
  first-boot default bank is scaffolded by the lifespan, not `create_bank`, so the lifespan seeds it
  the same way when it is brand new (`seed_owner_if_brand_new`: no entity page, no episode). Because
  a bank now starts with one node, **the app's empty means "no node but the owner's"**
  (`hasNoContentBeyondOwner`: `FirstRunGate`'s graph input, the Graph's and Clusters' "Nothing here
  yet"); the `/banks` `entityCount` of a new bank is 1. **"The user", "me", "yo" … are this page** (G169):
  Sleep never writes a page for a speaker reference, routes every such entity, edge, claim and wikilink here
  (a non-person page holding the name, a company "Owner", keeps its own), and its prompts call the person by
  this page's `name` (`capture-and-sleep.md`, "Entity promotion").
- `owner_roles:` / `unnamed:` / `name_declined:` (placeholder people, 2026-10-14; `role_people`) — a `person` page
  known only by a relation to the owner is titled by the relation ("Partner", "Former roommate"; never "<owner>'s
  partner", and never a number — "(another)" when a second page of one relation is kept), with `unnamed: true` and the
  relation's key in `owner_roles`. A named page carries a relation in `owner_roles` only when the person's answer or a
  merge on evidence put it there; Stage 2 attaches a later role-only mention to the one named page holding a
  **singular** relation (partner, spouse, father, mother…), never to a named page on a plural one (a friend, a
  roommate). `name_declined: true` is "I'd rather not say": the page keeps its role title and is never asked again.
  `capture-and-sleep.md`, "Placeholder people", has the rules; `features.md` the question.
- `kept_on:` (G147) — the days the person answered *keep* to a decay question; each joins the page's
  mention weeks, so a kept page fades a little slower. Written only by the decay resolver, deduped,
  capped at 52, and unioned by a merge (`decay_policy.merged_keeps`). Not an episode id and never read as one.
- `paths:` (G133) — on a `project` page a watched folder anchors: `[{path, device}]`, where that
  folder lives on which Mac. For display and relink only; the backend never opens it.
- `born:` (G141, ruling 36 D4) — on a `project` page, where it came from, written once where the page is born and
  never rewritten: `{origin: repo|words, day, episode, repo?: {name, family}, span?: {start, end, hash, kind},
  via?: folder}`. `repo.family` is the hook's `family_hash` (a hash, never a path); `span` points into the episode's
  evidence text and is read back only while `evidence.span_status` says current or grown (`project_birth.quote`).
  A page without it (older than the rule) is classified on read (`project_birth.classify`: a declared `repos:` →
  repo, `paths:`/`folder` → words, then the cited conversations) and never rewritten for it (`capture-and-sleep.md`).
  A fallback page that a later birth retypes gets its `born:` then, the one time (`project_birth.retype_on_birth`).
- `proposed_type: project` (owner 2026-10-23, amends D4) — on a `concept` page Sleep wrote for a thing Stage 1 called a
  project that has no birth yet but cleared the promotion bar (the fallback page, `capture-and-sleep.md`). Read by the
  judge (a later project mention meets the page) and by Stage 5, which removes it when a birth makes the page the
  project; nothing else writes it.
- **Ruling 45 (2026-10-27): whose project it is** — keys on a `project` page (or a fallback page), written only by the
  person's doors (the app's routes, `cicada projects new`, a trusted agent on their ask) through `project_ownership`, the
  one writer of `mine` / `not_mine` and the two conversation lists; never by Sleep, which carries them through every
  rewrite (Stage 3 updates the page's own frontmatter) and every merge (`project_ownership.carry_on_merge`), and never
  moved by a correspondent split. `mine: {via: app|cli|agent|accepted|import, day, by, session?}` — in the person's list;
  a folder birth (`born.via: folder`) and a page with a claim of `origin: companion_app` read as theirs without it
  (derived on read, Q2). `not_mine: {day}` — a dismissed suggestion; the page is never archived, deleted or retyped for
  it. `description` + `description_by: {by, day, session?}` — the person's header line (Q5); Sleep's article stays the
  Overview. `conversations_added` (an id = the person's tie; `{episode, by, session?}` = an agent's, which only it may
  untie) and `conversations_removed` (the person's untie, which every automatic signal respects).
  `entities_added` / `entities_removed` (decision 10, 2026-10-28; `project_ownership.tie_page`, their one writer) —
  "Pages in this project" tied by hand: an id = the person's tie; `{entity, by, session?}` = a trusted agent's;
  `{entity, by, session?, proposed: true}` = another agent's proposal, shown for the person to take and never counted
  as part of the project until they do. `entities_removed` is the person's "Not part of it", which wins over every
  automatic tie (a claim or an event participant, `project_pages`) and that no agent re-ties; an agent removes only
  what it tied. **Frontmatter, not a claim:** a negative must beat the automatic layer, a `part-of` claim already
  makes a sub-project (`project_timeline._tree`), and membership is the person's curation, not a belief with evidence
  and decay — the conversation lists' precedent. Both carry on a merge (`carry_on_merge`, an untie on either side
  wins). `provider_projects:
  [{provider, id, name?, episode?, docs?, instructions?: {start, end, hash}}]` — the project's own id in Claude (from an
  export) or ChatGPT (a `g-p-` grouping the person named on accept); `instructions` is a span into the imported
  knowledge episode, read back only while `evidence.span_status` holds (`project_timeline._knowledge`), and `docs` are
  names only. `born.origin: created` with `via: app|cli|agent|accepted|claude-export` (and `by`, `session`, an
  `episode`/`span` for the person's ask) joins `repo|words` for a page someone made on purpose.
- `project_groupings.yaml` (ruling 45, bank root) — what has no page to carry it: `dismissed` (ChatGPT groupings the
  person said are not theirs) and `imported` (`{provider, id}` of every provider project an import has seen, so a page
  the person deleted is never re-created, recorded only after the page's commit). Each writer reads it whole and
  changes only its own key (`project_ownership.update_groupings`), committed under the person; its mtime rides the
  sync `entities` component, so `/projects` and the app's `ProjectsRefresh` move with it. A Claude export's pages are
  written inside the bank's write admission and wait for the next import while Sleep writes (`provider_projects`).
- `provider_project: {provider, id, name?}` on an episode (ruling 45 addendum) — a provider's own project grouping (a
  ChatGPT `g-p-` id read from `conversation_template_id`/`gizmo_id`), outside the body and its hash: an unchanged
  conversation that gains it is updated in its frontmatter only and never re-queued (`episode_staging`). `relay.project`
  on a relayed episode is the relaying app's word on its project (`cicada_capture_turns(project=)`), kept until the app
  says another.
- `media.kind: paper` + `paper:` (G133) — a paper page: `arxiv_id`, `doi`, `authors`, `published`,
  `venue`, `sections`, and `metadata_status` once a lookup failed. The ids are the identity
  (`media-arxiv-<id>` / `media-doi-<hash>`); the abstract is a `describes` claim from
  `external:arxiv` or `external:crossref`, a dated cache shown under the personal tier (G121).
- On an episode (G133/G134): `turns` (the G118 per-turn sidecar), `evidence_kind`,
  `source_deleted_at`, and a section's `content_sha` — see the Awake rails; on a conversation, `turn_extras` and
  `unsent_turns` (2026-10-20, above).

### Backlogs (G150)

A project's backlog is memory, not a table in some repository: **one markdown file per item** at
`<bank>/backlog/<project-id>/<item-id>.md`. Frontmatter: `id`, `title` (the brief task), `project`, `status`
(`open | doing | done | dropped`), `triage` (`apply | research | decide`, optional), `paid` (the 💸 flag), `created` /
`updated` (the machine zone's days), `added_by` (`user` | a harness label | `cicada`), `session`, `links: [{kind:
pr|commit|url|doc|entity, ref}]`, `order` (hand-set), and last a `notes: [{at, by, session}]` sidecar. Body:
`## Description` (the reasoning) then `## Notes`, append-only `### <day> · <who>` entries — a status move is itself a
signed note, and a note is edited only through git history; any heading inside a text is demoted so it can never forge
a note. **Never an entity page**: Stage 1 never extracts one, it never decays, and the writer never touches
`entities/`. Ids are `<PREFIX><n>` like G-ids — the project page's `backlog_prefix:`, else the prefix most of its items
share (an imported G-row list continues its sequence), else the name's initials (`Orchard` → `ORC`) — max+1, claimed by
an exclusive create (the backend and every stdio MCP process mint in one folder). **One writer**,
`api/services/backlog.py`, behind every door: REST (`routers/backlog.py` — `GET/POST /projects/{id}/backlog`,
`POST /projects/{id}/backlog/import`, `GET/PATCH /backlog/{project}/{item}`, `POST /backlog/{project}/{item}/notes`;
409 while Sleep runs; each write commits alone as `Backlog update <day>`, `Cicada-Author: user`, trigger
`user/companion_app`, an import as `Backlog import <day>`, `user/backlog_import`), MCP (`cicada_backlog` read;
`cicada_add_backlog_item` and `cicada_add_backlog_note` record — the harness as author and the conversation as
`Cicada-Session:`, refused while Sleep runs and in a demo bank; a remote connection without `sources` is told the
person's own words exist, never shown them), the importer (`backlog_import.py`, `scripts/import-backlog.sh`: G-row
tables and `### G<n>` sections, ids and statuses kept, an id already filed skipped) and the demo. Every text is
scrubbed (writer `backlog`), and an open item whose title matches a new one exactly refuses the new one — one row per
idea, later findings are notes. Both reads ETag over the `backlog` sync component (a stat walk) and `entities`; neither
is a Store domain (`BacklogCache` in the app, like `ProjectsCache`). A note's model and effort are joined to its turn at
read once round 4's per-turn join lands; until then a note names its harness.

### Design references — looks, on the pages of the things they show (design taste, owner 2026-10-14; 2026-10-20)

A look the person likes is memory: **one markdown file per reference** at `<bank>/design/<id>.md` plus its screenshot
at `<bank>/assets/design/<id>.<png|jpg>`, both **in the bank and committed together** — the screenshot is the person's
own capture of a page that may not look the same tomorrow, so it is an asset like an uploaded picture, not a cache.
Ids are `<UTC day>-<site slug>` (`2026-10-14-dashboard-example-com`), `-2`, `-3`… on collision, claimed by an exclusive
create (`markdown_parser.write_new`). Frontmatter: `id`, `title`, `url` (http/https only, no credentials), `site`,
`captured` (UTC `Z`), `added_by` (`user` | a harness | `agent`), `session`, `via` (`app_capture | drop | paste | agent |
explore | demo`), `image: {file, sha256, width, height, bytes}`, `region` (optional), `palette: [{hex, share, role,
declared?}]`, `look` (the palette's words: dark/light, muted/vivid, hue names), `tokens: {fonts, generic, colors,
font_sizes, spacing, radii}` (from the snippets), `computed` (the page's computed type and colour roles, below),
`note_by` (who wrote the note, written when it is not the person), `tags`, `entity` (optional; the page the look shows, never
created — below). Body: the title, the screenshot embedded as `![Screenshot](../assets/design/<id>.png)`, the link, the note —
under `## What I liked` only when it is the person's own words, under `## Noted by <agent>` ("Noted by Claude Code")
when an agent wrote it (looks v2, 2026-10-15; any heading in it demoted) — and `## Snippets` (fenced code).

**Whose words (looks v2).** `note_by` defaults to the author: an agent's note is the agent's, whatever it says the
person liked. Only a note Cicada itself read from the person's own save (an explore Look's saved reason) is theirs
(`note_by: user`). An agent door never writes as the person: `via=agent` with no author is the generic `agent`. The
REST door takes `author` (a harness id from the Sources page's table, or `agent`; free text is a 400) and commits under
it with trigger `agent/rest_api`. A reference written before looks v2 with no `note_by` is read as: `via: explore` →
the person; `added_by` an agent → that agent; `added_by: user` with `via: agent` → `agent` (the REST door stamped
agents as the person until then). **One writer**, `api/services/design_refs.py`, behind every door: REST (`routers/design.py`),
MCP (`mcp_tools.save_design`) and the demo. Every text is scrubbed (writer `design`); one screenshot (by sha256) is one
reference; PNG or JPEG only, 32–8192 px, ≤ 4 MB (the app shrinks to ≤ 2560 px first). **Never an entity page** (the 10
types stay closed): Stage 1 never reads `design/`, and a reference never decays; the one thing written under `entities/`
is a page's `## Looks` section (below). The
person's writes commit alone as `Design reference <day>` / `Cicada-Author: user` / `user/companion_app` and are refused
in a demo bank and while Sleep holds the pages; an agent's as `Agent write` with its harness and session. An agent
removes only what it added. `sync_service`'s `design` component (a stat walk of `design/`) is the board's ETag; it is
not a Store domain.

**A look lives on the page of the thing it shows (owner rulings 2026-10-20).** *"This should be ingrained in the
markdown of a specific thing."* The record stays one file in `design/` — its palette, tokens, specimens, note and
vectors are the look's, and a page's prose rewrite can never lose them — and its `entity:` is the attachment. The page's
markdown renders it: a canonical `## Looks` section (`entity_body.CANONICAL_SECTIONS`, after `## Links`), one bullet
per look, newest first — `- [<title>](../design/<id>.md) · <site> · <day>` with the screenshot embedded on the
indented line below (`![<title>](../assets/design/<id>.png)`) — so git, GitHub, Obsidian and an agent's
`cicada_recall_detail` read the page whole. **Why the record stays separate, not moved into the page:** the page is
rewritten by Sleep's writers and capped by its article budget, the 10 types stay closed, a look never decays while its
page may archive, the screenshot's hash, palette and vectors key on the record id, and moving a look between pages is
one frontmatter field. **One writer:** `design_refs.sync_page` writes the section surgically (the prose before the claims
fence edited, the fence and ledger untouched, nothing else moved) under the page lock, from the records; an empty
section is removed. Being canonical, Sleep's merges carry it as it is and it never reads as a hand edit
(`has_human_prose`); the article writer's titles refuse "Looks". **Where a look goes** (`design_refs.subject_for`,
deterministic, no model): the page a door names (`entity` on `POST /design`, `subject` on `cicada_save_design`, the
explore ask's `subject`); else exactly one page whose trusted `website` source (the one its mark is drawn from) is the
look's site — two claimants attach nothing; else the saved link's own page for exactly that URL (`url_index`); else
nowhere — never a page invented. Moves: `PUT /design/{id}/entity` (`design_refs.attach`; an agent moves only its own),
a removal re-renders the page, and a page merge moves the loser's looks to the winner (`entity_merge` →
`design_refs.repoint`, in the merge's footprint). A look whose page went reads as unattached (`GET /design` serves
`entity` only for a page that is there). The person's own words on a look (`PATCH /design/{id}`, `design_refs.update_ref`): name, link and note, scrubbed; a
note written there is theirs (`note_by` dropped, under `## What I liked`); the record's body is rendered again and the
page's line follows the new name, committed together. A page edit inside `## Looks` is refused in words
(`page_edits.REBUILT_SECTIONS`, beside `## Related`), and a pinned correction never reaches into it. The section heading
is matched as a whole line (`## Looks and feel` is the person's own section). **The one-time move** for looks saved
before: `api/scripts/attach_looks.py --bank <path>` (dry run, counts), `--list` (the looks left unattached and why, plus
the moves — for the person's terminal only), `--apply` (`cicada` commits, `Looks attached to their pages: …`, refused
while Sleep runs or when git cannot list the dirty files); idempotent (`looks_attach`). It follows `list_hub_repair`'s
rules: a record, page or claims ledger dirty in git is skipped unless its only change from HEAD is this move's own (a
record's `entity:`, a page's `## Looks` section) — what an interrupted run leaves, adopted and committed by the next;
every file is re-read before it is written and dropped if it changed since the survey; commits come
`COMMIT_STEP` paths at a time (a page with the looks moving onto it in one step). A look whose page is gone and that no
rule places has its stale `entity:` cleared there (the board already reads it as unattached).

**What is read locally, with no model:** the palette and its words, and the CSS tokens of the snippets (regular
expressions over the text as given; nothing is fetched or run). **The palette (looks v2, `design_palette`)** reads
pixels at ≤ 1600 px a side (256 averaged a 1 px rule into the ground), bins at 5 bits a channel, drops bins under
0.02 % (specks), merges greedily under an RGB distance of 28. The largest colour is the **ground**; every other is
ranked by **salience** = (0.65 · chroma + 0.35 · WCAG contrast against the ground, scaled to 0–1) × presence, where
presence saturates at 0.4 % of the picture — never by area, which turned one cobalt ink on off-white into "off-white
90 %, pale blue 4 %, grey 2 %". A colour under 1 % stays only if its salience is ≥ 0.12; a colour on the line between
a stronger one and the ground (an antialiased edge) is folded away under 1 % and is a `wash` above it. Each colour has
a role: `ground`, `accent` (chroma ≥ 0.3), `ink` (contrast ≥ 3 against the ground) or `wash`. Colours the page
declares — the computed colour roles and most-used colours, then the snippets' CSS colours — are merged: a pixel colour
within 40 of one is marked `declared`, one the pixels never show is added with `share: 0`. At most 8 colours,
deterministic.

**Computed tokens (`design_tokens`, shape `design-tokens-1`).** What a page renders is in its computed styles, not its
stylesheet text (Next.js `next/font` writes `__Newsreader_a1b2c3` for the family), and only a browser has them, so the
person's agent reads them (site-explore's `_DESIGN_JS`, one bounded script in the page; ruling 25) and Cicada keeps
them in `computed`: `type` by role — `body`, `heading`, `subheading`, `caption`, `link`, `drop_cap` — each `{family,
generic, stack, size, weight, line_height, letter_spacing, color}` (CSS px; `line_height` None for `normal`); `colors`
by role — `ground`, `ink`, `accent`, `wash`; `used`, the most-used colours (≤ 12). One module defines the shape, its
bounds (size 4–400 px, line height ≤ 800 px, letter spacing ±50 px, weight 1–1000, a family ≤ 80 characters, ≤ 16 KB
in all) and its tool schema (`JSON_SCHEMA`, which `cicada_save_design.tokens` and `cicada_record_capture.design` both
advertise); it accepts the browser's own words (`fontFamily`, `rgb(…)`, `"18px"`, `bold`, `normal`, `em`), strips a
`next/font` hash and its fallback face, folds `-apple-system` into `system-ui`, and drops transparent colours. A value
out of bounds is dropped with a problem line, never a failed save. `GET /design/{id}` serves `computed`, `typeRoles`
and `colourRoles` (the computed role, else the pixel palette's, each with its `source`); the board's `fonts` are the
computed families first, body first, then the snippets'.

**Type specimens (looks polish, owner 2026-10-15: "an Aa with the font and the name, or fonts if several").** The
specimen model (`design_tokens.specimens`) is one entry per distinct family the computed type names — `{family,
generic, roles: [{role, size, weight}]}`, role order (body first), families compared without case, at most six. The
app cannot set "Aa" in the page's real face (it loads nothing a page names from the web), so the capture draws it: the
script's `_SPECIMEN_JS` draws "Aa" at 80 px in each family's computed stack on a canvas it never adds to the page, with
the page's own loaded face (a face not loaded within 1.5 s is left out, never drawn in a fallback), and prints
`design.specimens: [{family, path}]`. `cicada_record_capture` and `cicada_save_design` read each (a file the agent
saved, by identity, stdio only; or base64) before the admission; `design_refs` keeps those whose family the computed
type names — each a PNG **with an alpha channel**, ≤ 400×120 px, ≤ 96 KB, at most six — at
`<bank>/assets/design/<id>.type-<n>.png`, listed in the frontmatter as `specimens: [{family, file, sha256, width,
height}]` (a file not at its own name is ignored), committed with the look and removed with it. `specimens` never count
against the tokens' 16 KB. `GET /design/{id}` serves `specimens` (each with `image: {url: /design/{id}/type/{n}?v=…}`
when drawn) and `GET /design/{id}/type/{n}` the PNG from the bank. Pixels come from
`image_decode`: macOS's `sips` in a child process over a temporary file the backend wrote itself (never a path a
request names), returning an uncompressed BMP parsed with numpy — no image library in the server; a decode failure
means no palette, never a failed save.

**The design index** (`design_index.py`) is derived and disposable, **a table of the one meaning index** (meaning
index 2, 2026-10-28): `look_vectors` in the bank's `vector_index.db` — git-ignored, skipped by a bank copy and an
export (`bank_registry.DERIVED_ARTIFACTS`), written only in one short transaction under the file's one write lock
after everything is embedded, never across an embed. The board's old file (`$CICADA_HOME/design-index/<bank-id>.sqlite`)
is folded in on first use — its rows with their stamps, so nothing re-embeds — and deleted (`design_index._migrate`).
**The shared file is never deleted by the board** (review of #516): reads open it with no lock (WAL readers never wait,
so the board answers while a text re-embed holds the write lock for minutes); only the one-time setup and migration
take the lock, and are skipped once `schema:looks` is set. **No board path ever waits for that lock** (follow-up to
#516): the setup and a refresh's write try it without waiting, and when a text sync holds it, a search answers from what
is stored and the next refresh writes the new rows. A lock past the wait (`OperationalError`) is busy —
`BoardIndexUnavailable`, and the board answers by words; real damage drops and recreates `look_vectors` alone, and a
file SQLite can't open is left as it is. Audit: no other code unlinks `vector_index.db` (`search_index` discards only
its own `search_index.db`, and only on a non-operational error).
One row per reference and kind (`image`: the screenshot's EmbeddingGemma 2
vector; `note`: the note plus the look's words, same model's text encoder), each stamped with the model and the hash
of what was embedded. **An image row's stamp also carries the preprocessing's fingerprint** (vision item 3,
2026-10-28, `vision_embedder.fingerprint`): one built-in reference picture is decoded through the real decoder
(`image_decode`, macOS's `sips`, whose resampling can change with an OS update) at its planned size and cut into the
vision feed; the feed's bytes and the recipe's constants are hashed (12 hex, measured once per process, 29 ms). A row is
current only while model AND fingerprint match (`<model>#pre-<fp>`), so a changed recipe or decoder re-embeds every
picture once and nothing else ever does; a row stored before the stamp (the bare model id) stays current while the
pipeline measures `LEGACY_FINGERPRINT` (pinned 2026-10-28 on this pipeline), so adding the stamp re-embedded nothing.
`test_vision_fingerprint.py` pins the recipe with a fixed decoder and, where `sips` exists, the live decoder against the
legacy pin. A damaged file is rebuilt. Search fuses up to three legs by reciprocal rank (k = 60): words
(whole word 2, prefix 1, the exact phrase +3 — DigUp's exact-word boost, credited), the query against the screenshots
(one shared text–image space) and against the notes; or an example picture against the screenshots. A meaning leg keeps only
hits within 80 % of its best cosine (a relative floor: the text–image and text–text bands differ by model), and a text
query's results are tiered — what the words found first, then what only meaning found — so a word search never returns
the whole board. Without the image
encoder the picture leg is absent (`missing: image_model`); without EmbeddingGemma 2, words only. It embeds on a search
(at most 64 pictures a call) and in the background after a save — never by Sleep, and never while a Sleep run is going
(a search then answers from the vectors already stored). The query is never logged or stored.

### Site captures — exploring saved sites (G166, owner 2026-10-14, D1 (b))

An agent the person asked explores their saved sites (`mcp.md`, *Exploring saved sites*) and records what it saw. One
writer, `api/services/site_captures.py`, turns each visit into memory; every door (the MCP tool, the demo) goes through it.

| What | Where | Why |
|---|---|---|
| The capture record: frontmatter (dates, outcome, title, outline, components, fonts, tokens, JSON-LD fields, palette, hashes, change block, `signed_in`) and a short body | `<bank>/captures/<media-entity-id>/<YYYYMMDDTHHMMSSZ>-<tok6>.md`, committed as the agent's harness | Memory: dated, 2–6 KB, legible to an agent, portable |
| One thumbnail per capture that **changed the look** (JPEG, at most 640×400) | `<bank>/assets/captures/<sha256[:16]>.jpg`, content-addressed | "How it looked then" survives a handed-over bank, at ~40 KB a changed look |
| Full-resolution images (viewport 2×, full page, mobile, dark) | `$CICADA_HOME/captures/<bank>/<sha256>.<jpg|png>`, outside every bank and git repo, never evicted | Size: ~1 GB a first pass of 1,000 sites would bloat git forever (D1) |
| The page's visible text (≤ 1,500 words, scrubbed) | `$CICADA_HOME/captures/<bank>/text/<sha256>.txt` | Change detection and recon, and no copy of someone else's page in git |
| The queue | `$CICADA_HOME/explore_queue/<bank>.json` (`explore_queue`) | An intent, not a memory (keys only, no URL) |
| **The site map** (slice 2): every page found or opened on a site, its kind, first and last seen, capture ids; robots.txt as last read; one line per visit | `<bank>/captures/_sites/<site>.md`, one writer (`site_map`), committed with the capture it came from | Memory: what existed on a site on a day cannot be fetched again, and the capture ids it names are bank paths — outside the bank it would point at nothing once handed over |

- **Append-only.** A re-visit writes a new file and never edits one (`markdown_parser.write_new`, exclusive create). The
  record id is the capture's instant plus the lease token's first six hex digits, so a retry finds its own record and
  writes nothing (`duplicate`). "Changed since" is a comparison between dated records.
- **Every date.** `captured_at` (the agent's clock, kept only inside its lease window, else the server's clock and
  `captured_at_flagged: true`), `recorded_at` (the server's), `saved_at` (the bookmark's own instant from G191's
  `added_at`, else the save day), `why_at` (when the person said why, G191) and `last_modified` (only when the page gave
  one that is not "now").
- **Settled before the shot (looks polish, 2026-10-15).** The capture script (v4) waits, before the first screenshot of
  each page, for its web fonts, the first viewport's images (complete or failed), no layout change for 500 ms, and the
  viewport's finite animations and transitions; an infinite animation, or motion no animation names (two tiny frames of
  the viewport differ, so a script-driven intro), gets a 2.5 s grace from the load; all of it inside a hard cap of 9 s,
  after which it captures anyway. The record keeps `settle: {ms, timed_out, waiting_on?, motion?, unread?}` — ids and
  enums only (`site_captures.settle_note`; `waiting_on` ⊂ fonts, images, layout, animations, motion; `motion` looping
  or moving) — on the record and on each further page, and `cicada_record_capture`'s reply says when a shot was taken
  before the page settled.
- **Computed by Cicada, never the agent's word.** The palette and its look words (`design_palette`, as for Looks), a
  64-bit dHash of the viewport (9×8 grayscale through `image_decode`'s `sips` child process), and sha256 of the
  normalized text and outline (whitespace folded, digits masked, so a footer year is not a change). The change block:
  `look` is `same` (Hamming ≤ 5), `small` or `new` (≥ 12); `words` is `same` or `changed(<outline Jaccard distance>)`;
  `moved` when the final site differs from the saved one.
- **The thumbnail.** Made by Cicada from the viewport (`sips -z`, quality 80, fit inside 640×400, never enlarged); the
  agent's own `thumb` is used only when `sips` is missing and it already fits. An unchanged look (`same`, or outcome
  `unchanged`) points at the previous thumbnail (`thumb.reused`) and adds no bytes. A page that showed the person's own
  account (`account_visible`) keeps even its thumbnail outside the bank: the scrub cannot clean pixels.
- **Signed in or not (D2 amended).** Every record carries `context: signed_in|isolated` and `signed_in`, shown on every
  surface ("taken in your signed-in browser").
- **Outcomes.** `captured`, `unchanged`, `moved`, and the dead ones — `not_found`, `gone`, `parked` — recorded with no
  images. A wall (`needs_login`, `blocked`) is **never** a capture: no screenshot of it is kept; the queue pauses the site.
- **Reading them.** `GET /explore/captures/{entity_id}` (newest first, the wire `site_captures.wire`), `…/{id}/thumb`
  (from the bank only, `assets/captures/<16 hex>.jpg`), `…/{id}/image/{kind}` (from the outside store, by the hash the
  record names; 404 "not on this Mac" when absent, and the wire says `onThisMac: false`). The `captures` sync component is
  a two-level stat walk of `captures/`. Export of the outside store with the bank is slice 3.
- **Never an entity page.** Exploring creates no page; a capture names its saved-link page (`entity`) and Stage 1 never
  reads `captures/`. Sleep's recon over the captured outline (G102) is still open.
- **Further pages (slice 2, owner 2026-10-14 evening).** A visit the person's reason makes deeper (`explore_plan`,
  `mcp.md`) keeps the further pages it opened in the same record, `pages: [{url, kind, title, loaded_at, outcome,
  chosen_by, outline, fonts, components, dhash, palette, look, change, thumb, images}]` — at most five, each with its
  own images outside the bank and a ≤ 640×400 thumbnail in it only when its look changed since the site map's last
  picture of that URL. A page behind a wall keeps its outcome and no picture. A technique's `section: {heading,
  excerpt ≤ 240 characters, text_sha256}` keeps the section's text outside the bank. `plan: {depth, max_pages, kinds,
  because, auto_look}` says why the visit went that deep; `robots: {status, sha256}` what robots.txt said.
- **The site map (slice 2).** `site_map.py` is its one reader and writer. Frontmatter `{shape: sitemap-1, site,
  first_seen, last_seen, robots, unlisted?, pages: [{url, kind, title|label, first_seen, last_seen, last_visited?,
  captures?, outcome?, robots?, dhash?, thumb?}], visits: [{at, capture, entity, pages, found, depth}]}` and a body
  with a table of pages and a list of visits. `site` is `reading_hosts.site_of` (every saved page of a site shares a
  map); URLs keep no query or fragment; sign-in, account and cart pages are never listed. **Append-only:** a visit adds
  pages and a visit line, never removes a page, never moves a `first_seen`, only moves `last_seen` forward; a page a
  later visit no longer finds keeps its row. **Bounded (review B1):** at most 300 pages are listed (`unlisted` counts
  the rest), the newest 50 visit lines (older ones roll into `earlier_visits: {count, first_at, last_at}`), and each
  page's newest 12 capture ids (`earlier_captures` counts the rest; every capture record stays). A site with 2,000
  visits stays under ~120 KB, and `cicada_site_map` lists at most 80 pages. A page found
  walled is never planned again. `_sites` starts with an underscore, so it can never be a page's capture folder
  (`explored_entities` skips it). Read with `cicada_site_map` (stdio) and `GET /explore/sites[/{site}]`; the
  `captures` sync component's stat walk covers it.
- **Looks from exploring (G196, slice 2).** When the plan's reason is the design, `cicada_record_capture` keeps the
  visit's best pictures as Looks through `design_refs.add_ref` (`via: explore`, tags `explored` and the page kind, the
  person's own words about the save as the note, `explored: {site, captured_at, capture, entity, page_kind, page_url}`
  as provenance, the capture's instant as `captured`): the saved page first, then each page whose look is new, never
  two within a dHash distance of 5, at most three a visit, never a page that showed the person's account. A Look keeps
  its full viewport in the bank (G196's rule), committed with the capture. Looks v2: each keeps the page's computed
  tokens (`design` from the capture script, per page) as `computed`, merged into its palette, and (looks polish) its
  page's type specimens (`design.specimens`).
- **"Save its look" (looks v2, 2026-10-15).** One ask on one saved link: `explore_queue.ask(…, asked="look")` queues it
  with `asked: look` on the row — joining the active run when one is going (never replacing it, unlike `start`), else a
  batch of its own; a person's ask lifts a pause, an agent's does not. The plan (`explore_plan.for_site(…, asked)`, at
  claim and again at record from the same row) adds the design reason (`because: {from: ask, signal: look}`) and
  `save_look`, so the landing picture becomes a Look even when the capture says the look is the same as last time.
  Doors: the person's click (`POST /explore/look`) and a trusted agent they asked (`cicada_explore_start(look=[…])`).

### Activity traces — sealed, outside every bank (G218, ruling 38, 2026-10-23)

What the person did on this Mac, with times, held so "the video I watched at 15:20" is findable later. **Off by
default**; on only after the consent sheet (`trace_store.CONSENT_VERSION`; an older or missing consent is refused).
The app captures (`capture-and-sleep.md`, "Activity traces"); `api/services/trace_store.py` is the **one reader and
writer** of `$CICADA_HOME/traces/`, beside `captures/`:

```
traces/settings.enc                  the person's choices, sealed
traces/timeline/<YYYY-MM-DD>.log     one sealed line per focus span, by the local day it started (ruling 34)
traces/frames/<YYYY-MM-DD>.log       one sealed line per screenshot: when, which app, its recognized text
traces/shots/<YYYY-MM-DD>/<id>.enc   the screenshot itself (downscaled JPEG), sealed
```

- **Never in a bank, never in git, never on the network, never in the telemetry ledger** (not even ids). Time Machine is
  asked to skip the folder and the key (the sticky `com_apple_backup_excludeItem` xattr, set with no subprocess). No
  index is written: search decrypts and scans in memory (`trace_store.search`), so there is nothing derived to leak.
- **Encrypted at rest** (`trace_seal`): AES-256-GCM per record, a fresh 96-bit nonce each, associated data naming the
  record's kind and day (`timeline/<day>`, `shot/<day>/<id>`, `settings`) — a flipped byte, a line moved to another
  day's file or a screenshot renamed to another id fails its tag and is skipped and counted (`unreadable`), never
  guessed. File names carry only dates and random ids.
- **The policy is applied twice** (`trace_policy`, served to the app at `GET /sources/traces/settings`): never recorded
  at all — password managers and credential sheets, the login window and screensaver, Cicada itself (`com.rorosaga.cicada*`),
  the person's excluded apps; the whole moment dropped — a private window, an excluded site; chat and mail
  (`TITLE_OFF_APPS`) keep the app and times only (no title, no screenshot) unless the person turns titles on for that
  app; a URL only from an allowed Chromium browser, scheme + host + path + content keys (`v` on YouTube), the path
  scrubbed; a browser row keeps a title, and a browser screenshot is kept, only beside such a URL (the one case the
  window is known not to be private — Safari's, Firefox's and Arc's private windows cannot be told apart); every title
  and recognized text scrubbed (`episode_scrub`). **The browser list is a floor, never the test** (B3): the app marks
  every app macOS registers to open `https:` links as a browser (`browser: true` on a row or a frame), and the store
  keeps such a row's title, or its screenshot, only beside a verified URL from a browser the person allowed. Turned off or paused, nothing is written (a span reaching into a
  pause is cut at it).
- **Retention** (a sweep on every write, at backend start and hourly — `trace_store.sweep_if_present` in the lifespan
  scheduler — so it holds while traces are off): the timeline 30 days, screenshots and their text 7 days; the person may
  shorten either, never lengthen. A store whose key is gone is cleared (sealed bytes with no key are noise); a key file
  that is refused (below) records nothing and deletes nothing on its own.
- **Forget the last N minutes** (N ≤ 15, `FORGET_MAX_MINUTES`) drops every span reaching into them — read from every
  day file a span could start in, back to `cutoff − MAX_SPAN`, so a span from 23:40 to 00:19 is reached at 00:20 — and
  every screenshot taken in them. **Nothing younger than the forget window ever leaves the store** (review of #456,
  B1): promotion offers the bank only spans that ended at least `PROMOTE_HOLD` (15 min) ago, from the store, past a
  sealed cursor (`promoted_through`), and a day summary waits until its day's last moments are that old — so a forget
  always runs before anything it covers could reach the bank or git. **Wipe** deletes
  the folder, the settings and the key (crypto-shredding: a copy taken before reads as noise) and so turns traces off.
  What was already promoted into the bank (a watched day, a day summary) stays; the sheet says so.
- **What crosses into the bank** (`trace_memory`, only what the person's switches allow, nothing for a demo bank, one
  `user` commit per sync, trigger `capture/traces`). **Redesigned 2026-10-28** (owner's answers to the redesign, Q12;
  ruling 39b amended by the owner the same day, TODO ruling 39):
  - **What you watch and read** (`watch_and_read`, on with traces; reads `youtube_to_watch_history` as its alias):
    ruling 39b generalised from YouTube to every site. A *video page* of a platform the watch history knows
    (`watch_history.watch_url`: YouTube, TikTok) in front ≥ 20 s becomes a watch in the existing watch-history writer
    (`via: traces`, `dwell_s`); *any other page* in front ≥ 30 s over the day (`MIN_READ`) joins that day's **reading
    record** — one episode per local day, `source: reading-history`, `reading-history:<day>`: the cleaned address, its
    title where the store kept one, its site, first seen and minutes in front, longest first, ≤ 300. Calls
    (`CALL_HOSTS`) are not reads. Both are **index-only** (`history_index.kind` → `history` / `reading`), never read by a
    model, never a mention. The reading record is recomputed from the store for each day new pages touched
    (idempotent; the stager skips unchanged words) and at most every 15 min for today (`READING_EVERY`; a finished day at
    once): rewriting it on every sync doubled the promoting sync's p50 (measured, see G218).
  - **Learn from my day** (`learn_from_day`, **off by default**; the old `daily_summary` + `learn_from_summary` are read
    aliases). One **counted digest** per finished local day (`source: traces-day`), written only while the switch is on
    and read by Sleep — the only model read traces get. It names **no window title, no address and no screenshot text**:
    time on the person's own projects, reading (pages and sites), watching (videos, platforms), calls, and everything
    else as app names plus app switches at the busiest hour. **Project time is attributed deterministically**
    (`trace_memory.attribute`) and only to the person's own projects (`project_ownership.is_mine`, ruling 45): a span is
    a project's when its window title names one of the project's folder or repository names as a whole word (from
    `paths:`, `repos:`, `born.repo`, trusted `path`/`repo` sources; ≥ 4 characters, generic names like `src` never),
    its address is that repository on a code host, or its address is at or under a URL the person tied to the project
    as a source (never a proposal). Two projects matching equally leave the span unattributed. The digest is
    `evidence_kind: assistant` and never a mention (`episode_time.UNTIMED_SOURCES`). **Migration:** a settings file from
    before reads `learn_from_day` on only when both old switches were on; an index-only summary (`daily_summary` alone)
    never widens into a model read — it ends, and its written days stay. A PUT of `daily_summary: true` alone changes
    nothing; `daily_summary: false` turns learning off; `learn_from_summary` maps onto `learn_from_day`.
  - **The preview** (`GET /sources/traces/preview?day=`, yesterday by default) is the same function
    (`count_day` → `render_counts`) on one day, with no model — exactly the words Sleep would read, shown before the
    switch is on (`text`, plus the structured `counts` the page draws).
  - **Remove from memory** (`POST /sources/traces/remove-from-memory`, admitted): every belief and progress note whose
    cited episodes are all `traces-day` digests and that is not already superseded or a retraction — closed or not: a
    done happening is born closed (`valid_to = valid_from`) and is exactly what a digest adds (review of #508, B2) — is
    taken back the way a withdrawal takes one back: superseded by a born-closed `retracts` record beside it (origin
    `traces-remove`), an open one closed today, a closed one keeping its dates; **one commit**. Pages are found by their
    bytes naming a digest (page or claims ledger), whichever writer wrote the claim — each file re-read only when
    its size or time moved (on a copy of the owner's 8,028 pages: ~1.5 s once, then ~50 ms). A claim another conversation also
    supports stays. The removal's `[page, record, target, valid_to before]` is kept in the sealed settings (`removals`,
    newest 20) — written **before** any page moves, and with no key (after a Wipe) the removal is **refused, 409**, so
    nothing is ever taken back that could not be undone (B3). **Undo** (`…/remove-from-memory/undo`) gives each claim
    exactly its dates again, only while it is still superseded by that record, as one commit. `GET /sources/traces/added` counts what is
    left and lists the undoable removals. The digests themselves stay: they are what was read.
- **Managing traces by day** (2026-10-28): `GET /sources/traces/day-cards` — one card per kept day, counts, the screens
  connected (`screens`), and the id of the screenshot that stands for the day (`cover`: one taken during the day's
  longest span, the main screen's; else the one nearest the day's middle — chosen, never random), cached per day by the
  files' size and time. `POST /sources/traces/delete` deletes picked spans (with the screenshots taken of them),
  picked screenshots, or a whole day (`all: true`); a deleted span takes every screenshot in its time range with it,
  on every day that range touches (a span across midnight has screenshots filed under the next day); it never touches
  the bank.
- **Every connected screen** (consent sheet 2, `ALL_SCREENS_CONSENT`): a frame may carry `display`/`displays`
  (1-based, ≤ 8, kept only when consistent); `timeline` answers `screens`. **The store refuses a whole-screen frame
  (`display` > 0) from someone on sheet 1** — policy parity with the app (review of #508). A person on sheet 1 keeps
  front-window frames until they agree to the newer sheet; agreeing while recording keeps their pause. **The sheet
  recorded is the one the app displayed:** `POST /sources/traces/on` takes `displayed_version` (the app's own
  constant, `TraceRecorder.sheetVersion`); an app from before sends none and echoes the served version, so 1 is
  recorded; a version above what the store knows is refused.
- **The one-time note** (`reading_notice`): someone upgraded with the YouTube switch on is told once, on the page beside
  the switch, that it now covers every site; only the person clears it (`reading_notice: false`).

**Key custody — interim, an owner ruling pending (G218).** `trace_keys.KeyProvider` is the one seam; `provider()`
returns **`FileKeyProvider`: `$CICADA_HOME/traces.key`, 0600 in the 0700 home, outside `traces/`**, created with
`O_EXCL` (never replaced silently), refused when another account could read it or another user owns it, overwritten
then unlinked on Wipe. It protects a copy of the store, a backup or a sync folder; it does not protect against a process
running as the person (nor does anything else that process can ask for — the sheet says so). Why not the stronger
options yet, researched 2026-10-23:
- *A Keychain item* binds its access to the reader's code signature. Every developer build re-signs the app, and the
  backend is a Python process that is not the app, so both would raise Keychain prompts (the owner's open question on
  Keychain-via-a-signed-helper, on the credentials rail, is the same problem); a prompt is never raised by a build
  agent, so it cannot be verified here either.
- *A Secure Enclave key* (CryptoKit `SecureEnclave.P256`) never leaves the chip, so a copied `~/.cicada` is useless on
  another Mac — the strongest answer. Python cannot use it: the app would unwrap a data key (ECIES) at launch and hand
  it to the backend over its token channel, the backend holding it in memory only (traces would then be readable only
  while the app runs, which is already when they are made). It needs the signed, stable app identity of G182's
  Developer ID steps.
- **Recommended for the ruling:** the Secure Enclave–wrapped data key with the in-memory hand-off once Developer ID
  signing lands; the file key until then. Only `trace_keys.provider()` changes.

**Doors.** `api/routers/traces.py`: every route 403s a device token ("Traces stay on the Mac that recorded them"); the
remote listener serves only `/mcp` and `/v1`; no MCP tool, no Ask, no CLI reads the store (a test asserts nothing but
`main.py` imports it); search is a POST (the query never reaches an access log); a screenshot is served `no-store` and
only to the app, which asks Touch ID first. `request_limits` bounds `/sources/traces/sync` and `/frames` at 4 MB. A
threat-model page (Recall's lessons → Cicada's answers) is a later slice.

### Live state + handshake (G53 / G75)

**`<bank>/_state.md` is a *cursor* into the graph, never a copy of it** — YAML frontmatter plus a
short wikilinked body, ≤ 6 KB, zero LLM, deterministic. Written only by
`state_dictionary.refresh`. A digest of the `entities`/`inbox`/`episodes`/`bank`/`backlog` sync components is
stored as `inputs_version`; unchanged inputs mean no write. **Never `git_head`** — its own
`State snapshot` commit would self-invalidate.

Every regeneration that touches disk goes through `state_dictionary.refresh_and_commit`, which
commits `_state.md` ALONE (`commit_paths`, never `git add -A`) as `State snapshot <date>` /
`Cicada-Author: cicada`. **The read path commits too, on purpose:** a projection left dirty "for
Sleep's tail" gets swept into the next `git add -A` writer's commit under the wrong author — the
G85-class smear. Outside Sleep, that refresh is one admitted transaction skipped while Sleep holds the pages
(G183), or it could ride Sleep's batch commit under Sleep's author: `GET /state` and an inbox resolution inline,
every other writer (the settled-question undos, the inbox tidy, the web sweep) through
`state_dictionary.refresh_admitted`; `test_write_admission_sites.py` lists the direct callers. `sleep.next_at` is computed per request, never persisted: in the file it advanced
every day and made every idle night commit.

**The engine it names is the one a Sleep you start would run (2026-10-26).** `engine: {mode, engine, model, connected}` is
`engine_select.expected_settings` — the same rungs as `resolve_settings` (an env pin, else the Settings picker's
`sleep-engine` pref and its model, Auto's first plan the cached connected set shows, a chosen key's Claude toggle), never
a probe: `mode` is what the person chose, `engine` the id a Sleep commit's `Cicada-Engine:` trailer carries, `model` that
engine's model, and an Auto nothing has resolved reads `auto` with no model ("decided when Sleep starts") — never the
leftover `CICADA_LITELLM_MODEL` it used to show (a picker set to the Claude plan at haiku once read "engine auto
(openrouter/…)" while every commit said `claude-cli`). The file is rewritten only when the bank moves, so every reader
overlays the engine read now (`state_dictionary.with_live_engine`, over the connected set the file recorded): the
handshake (and its cache key), `cicada handshake`, the CLI door and `GET /state` (whose ETag folds it in).

**`_state.md` schema v3 (G141):** each of the top 7 project rows gains `next: {slug, name, target}`
and, once happenings exist, `now: {claim, text ≤ 80, since, verbatim?}` — the first claim text the
file holds; `verbatim` marks the person's own Log sentence, which a remote primer shows as 'a note of
yours' without `sources`. Neither field depends on today, and `_fit` drops every `now` before it
drops a project. **v4 (G150)** adds `backlog_open` (items open or doing) to a project row that has any, and
`backlog` joins the input components; the primer's Current row says "backlog: n open" under the same gate as
`now`/`next`. Contract item 3 names the backlog tools (CONTRACT_VERSION 8 with G149's item 8; each branch alone had taken 7).

**The handshake** (`api/services/handshake.py`) turns `_state.md` + a fixed contract into ≤ 1,800
tokens of primer: what Cicada is, a per-harness prelude (the contract never varies), the contract
itself, the now-view, and capability notes. The now-view is **Standing** — the person's page and
one-liner (through G117's resolver), their timezone (per request, never in `_state.md`, part of the
cache key), *How to work with me* (standing `skill` pages by confidence alone, less any whose summary rests on a
belief that closed after it was written — `skill_staleness`, W6 2026-10-23: a claim between two pages the skill draws
on, open on the newest day its summary cites and closed after it, whose object the summary names and whose predicate an
ending closes (`skill_staleness.endable`: the seed's endings, `also_ends`, `dependents`); no model call, each page's
claims parsed once per rebuild, and the page itself is unchanged — never below three rows
(`state_dictionary.PREFERENCE_FLOOR`): the least stale fill up to it, marked "(may be out of date)"), long-standing
durable/evergreen pages — then **Current** — projects, each project with its `now`/`next` (G141),
pages in focus in the last 14 days, people, recent conversations (G140, schema v2). A test holds R12 for every argument either primer names, for
every remote scope set. Contract item 3 names `cicada_note_progress` (G141 PJ-3a; remotely only when the
connection holds it). Delivered four ways: the MCP `initialize` result's
`instructions` (which Claude Code truncates), the `cicada_handshake` tool, `GET /handshake`, and the
SessionStart hook's `additionalContext` under a "From Cicada" header (G149). Since G110 slice 1a that whole
SessionStart note — header, primer, the continuity block, the reading sentence — is measured as one string inside the
1,800 tokens (`recall_text.compose_note`); the primer is built with a 300-token reserve when a block rides beside it. Contract item 8 tells an
agent what a "From Cicada" note is. **R12: a primer naming an
argument the schema rejects is a bug** — every argument it names must exist in the tool schema.
`SKILL.md` points at the generated text rather than restating the contract — one prose source.

**A reader that finds `_state.md` stale or absent must still work:** every field has a live twin
(`/status`, `/inbox`, `/conversations/recent`, `cicada_repo_context`).

### sqlite-vec (vector index)
`api/services/vector_index.py`. Embeddings are **stored, not recomputed at query time**, so search
is one in-process ANN lookup. A release app (G182) bundles the int8 ONNX export of
`intfloat/multilingual-e5-small` (384-dim, ~100 languages, `query: ` / `passage: ` prompts from its manifest, mean
pooling, no torch; owner 2026-10-06 chose it over the English-only `bge-small-en-v1.5`; `api/services/onnx_embedder.py`,
found through `CICADA_BUNDLED_MODELS`). **A developer checkout runs the same model** (fix/dev-embeddings, 2026-10-08):
`make embedding-model` (and `install.sh` step 2b) runs `scripts/fetch-embedding-model.sh`, the one reader of the model
pins in `scripts/release/inputs.env` — the release build calls it too, so there is no second copy of the pins — into
`$CICADA_HOME/models`, where `onnx_embedder` looks when `CICADA_BUNDLED_MODELS` is unset; onnxruntime and tokenizers are
in the developer set at the release lock's versions. Without that step a checkout falls back to EmbeddingGemma-300M
(768-dim, sentence-transformers + torch, gated) with asymmetric prompts. Measured on an M4 Pro (24 GB), 2,500 synthetic
pages of 150–260 words: e5-small ONNX 39 s, 785 MB peak RSS, 2 ms a query; EmbeddingGemma-300M on torch 98 s on the CPU
(2.0 GB peak) and 53–116 s on the GPU (≈4.4 GB of GPU memory), 25–30 ms a query. The ONNX embedder runs one text at a
time (`_BATCH = 1`): as fast as 32 per run at half the peak memory.
**EmbeddingGemma 2 on the Neural Engine is the model wherever it runs (owner 2026-10-09).** `google/embeddinggemma-2:768`
— the id carries the Matryoshka width, so a table records exactly which vector space it holds — runs through Core ML
(`api/services/coreml_embedder.py`; `coremltools` is in both dependency sets) on Apple silicon with macOS 15+; the export
(`FluidInference/embeddinggemma-2-coreml`, Apache 2.0) has seven fixed-shape functions sharing one set of weights
(`embed_32`…`embed_512`, `pack_256` for eight short texts), which is what keeps it on the Neural Engine. It is never
bundled: `model_fetch` downloads one pinned revision (`api/data/embeddinggemma-2.lock.json`, sha256 per file, ≈ 585 MB)
into `$CICADA_HOME/models/embeddinggemma-2` on the person's request (Settings, `make embedding-model-gemma2`,
`install.sh` on macOS 15+), compiles it and loads every function once from that final path — macOS caches the Neural
Engine compile (≈ 90 s, once) against the `.mlmodelc` path, so the folder never moves and a new revision gets a new
folder name. `onnx_embedder` is the registry of model folders: a manifest with `"runtime": "coreml"` counts only where
`coreml_embedder.supported()` (`CICADA_COREML_DISABLED=1` turns it off), and a release reads downloaded models from the
home but ONNX ones only from its bundle. A function loads on first use in the stdio MCP server and the CLI (a short
query: `embed_32`, ≈ 1 s warm); the backend loads all seven at its start, in the background (≈ 5 s; ≈ 13 MB more than
the query ones), and the per-prompt recall hook never loads one inside its budget (`loaded_only`); a query
that would wait past 8 s for a cold compile raises `EmbedderWarming` and the leg answers on words while the load
finishes in the background (never recorded as a failure); a load failure is `EmbedderUnavailable` (`model_missing`).
`coremltools` is imported with its converter frameworks hidden (torch would cost a checkout ≈ 2 s on every process's
first search). Measured on an M4 Pro: parity with the reference model cosine ≥ 0.9998; a query 2.8 ms; a session's
first recall 1.7–2.2 s in a fresh process against e5's 0.7–0.85 s, every later one ≈ 0.1 s; ≈ 300–360 MB footprint per
process that has searched; re-embedding a 21,208-vector synthetic bank (3,000 pages, 11,500 claims, 6,708 passages)
340 s against e5's 398 s; cross-language EN↔ES page retrieval +0.11 MRR over e5 on the spike's 3k set. **The default
moves with it:** where it runs, it is the configured default, and a bank recording one of Cicada's former defaults
(`FORMER_DEFAULTS`: e5-small, or EmbeddingGemma-300M in a checkout that never chose it) moves to it; a model the person
chose or set explicitly is kept. A bank built with it on a Mac without it keeps its vectors (search reads words).
**A model change is a background re-embed, never Sleep's** (`embedding_models.start_reindex_if_needed`): after a
choice, a download, the backend's start and the end of every Sleep run — never while Sleep runs (it waits; the end of the
run starts it) — the backend re-embeds each table whose model differs (pages, claims, pending, passages), embedding first
and then swapping the table in one transaction, so recall keeps answering from the old table with the old model it
records (measured: 835 recalls during a 340 s re-embed, none with an empty leg, p50 123 ms). It embeds in chunks of 64
and gives way when Sleep starts (`IndexSyncStopped`, nothing written). **A long embed runs in a child process** (`embed_worker`, 2026-10-09): `coremltools` holds the GIL for every predict (and for a load: the ≈ 90 s first compile), so in the backend's own process a re-embed starved the event loop — on an owner-sized bank `/healthz`, `/embeddings` and the Stop hook's capture POST went past 10 s. Every document batch of 16+ texts for an on-device model (the re-embed's chunks and Sleep's own syncs alike) is embedded by one child per model, with the same model resolved the same way; the parent keeps the diff, the write lock, the stop check and the one-transaction swap, and waits on a pipe. The child exits after 90 s idle or when the backend goes away; a dead one is replaced once per call. The download's warm-up loads its functions in a child too (the compile cache is per path, for every process). Queries and short batches stay in-process; `CICADA_EMBED_WORKER=off` (the suite's setting) keeps everything in-process. Reproduced with a GIL-holding stand-in at Core ML's measured per-predict times on a synthetic 3,632-page / 14,043-claim / 7,013-passage bank (a 383–391 s re-embed): before, 7–27 % of probes timed out at 10 s and half took over 2 s; after, p99 ≤ 168 ms, max 260 ms, none failed. `/healthz` reads off the event loop. Sleep's own syncs pass
`defer_model_switch=True`: a table whose recorded model still runs here keeps it, synced incrementally, while the switch
waits for the job. **The episode passages' cut is recorded the same way** (2026-10-19): `vector_index.EPISODE_CHUNKING`
(`1600/200` — 1,600-character passages, 200 overlapping, sized to the 512 tokens both on-device models read; the old
4,000-character passages left 36 % of real chat text unread, measured with EmbeddingGemma 2's tokenizer) is stamped beside the table as `chunks:episodes`, and a table
with another cut (an index written before the stamp reads as `4000/200`) is stale for `embedding_models.pending_switch`:
the same background job re-cuts and re-embeds it, embedding first and swapping in one transaction, while Sleep's own sync
keeps the recorded cut (so a night embeds only its new conversations, never the whole table). The cut is read under the index's write lock with the diff it decides, so a Sleep sync that starts while the job commits the new cut waits for that commit and then syncs at the new cut — it can never re-embed the bank at the old one or stamp it back. At the owner's scale (8,237 episodes, ~36.9k passages at the new cut) the re-cut holds ~113 MB of vectors in memory and embeds for minutes; a Sleep that starts meanwhile stops it (nothing written) and it starts over after the run. Only a switch to an on-device model folder is the job's; one to a hosted or sentence-transformers
model still happens in Sleep's index step, and `CICADA_BACKGROUND_REINDEX=off` (the suite's setting) restores that for
every model. `GET /embeddings` carries `recommended` (the better model this Mac runs but hasn't downloaded) and `reindex`
(state, model, tables done of total). One writer per index file at a time (`vector_index._write_lock`, in-process: every
index writer is the backend's); a full table rebuild runs in one transaction from its `DROP` to its commit.
A fresh bank is built with the small model unless `CICADA_EMBEDDING_MODEL_LOCAL` names another; a bank built with it is
queried with it (the recorded model, as for every bank). **Each bank's vectors are built with its own model**
(`embedding_models.build_model`, G182 phase 3): the person's choice for that bank (Settings → Privacy & data,
kept in `$CICADA_HOME/embedding-models.json`, outside every bank), else the model its index already records when this
Mac can run it and no `CICADA_EMBEDDING_*` was set explicitly (unless it is a former default and EmbeddingGemma 2 runs
here — above), else the configured default — so a change of default never re-embeds a bank unannounced (the one
move it makes, to EmbeddingGemma 2, runs in the background and Settings says so), and an explicit setting keeps its old
meaning. A bank whose recorded model this Mac
can't run is rebuilt with the default at its next sync — except one built with a downloaded model (the larger model,
EmbeddingGemma 2), which keeps its vectors (search reads words) until the person installs it or picks another model
(Settings says so). EmbeddingGemma-300M is the optional larger model
in a release on a Mac that can't run EmbeddingGemma 2: `POST /embeddings/install` installs sentence-transformers and torch with the bundled pip into
`$CICADA_HOME/extras/site-packages` (exactly the hashed packages in `api/data/extras-requirements.lock`, at the
developer lock's versions, `--no-deps`; `sitecustomize` appends it after the bundled packages, so a shared one always
resolves to the bundled copy; a failed install leaves nothing behind) and downloads the model once with the person's own Hugging Face token, used for
that request only and never stored or logged; it then loads from its local folder (`$CICADA_HOME/models.json`). The index is **derived and disposable** — synced by Sleep from
markdown, safe to delete at any time. **The sync is incremental** (`SqliteVecIndexer._sync_kind`): each
row keeps a stable `key` and the `hash` of the text that was embedded, so a cycle embeds only new and
changed texts, removes deleted ones and refreshes a page's metadata in place without an embed; a missing
table, a pre-`hash` schema, another model (recorded per kind as `model:<kind>`) or another width rebuilds
that table in full, and an embed that fails leaves the previous index untouched. Sleep runs the blocking
sync through `asyncio.to_thread`, never on the event loop.
**A failing embedder is said, not swallowed (fix/dev-embeddings).** `api/services/embedding_health.py` classifies an
embed failure — `credits` (402, or a 429 that says the quota is spent), `rate_limited`, `auth` (401/403), `unreachable`,
`unavailable` (5xx), `model_missing` — into one provider-neutral sentence. Sleep's index step reports that sentence once
(not one raw HTTP error per kind) and records the kind per bank in `$CICADA_HOME/embedding-health.json` (the bank's
path, the model id, the kind, a time — never text; outside every bank); a failed query embed in search is recorded too
(search still answers on words, `mode: lexical`). The next sync that leaves every table up to date clears it. After a
restart `/sleep/status` shows the remembered sentence as its `indexWarning` (the Sleep page's Details render it),
`/healthz` carries `embeddingModel` and `embeddingProblem` (an enum), and `make doctor` fails on it with the fix. An
unrecognised failure (a locked index, a bug) keeps its raw per-kind warning and is not recorded.
**A query is embedded with its table's model (audit 2026-10-05 P2-4).** The kinds are re-synced one after another, so
after a model switch one table can hold the new model's vectors and another the old one's; the bank-wide `model` stamp
only names whichever kind was rebuilt last. `_query_embed_fn(kind)` reads `model:<kind>` (falling back to the bank-wide
stamp on an index written before per-kind stamps); an injected embedder is used as given unless it names a different
model than the table's. `search_kinds` embeds once per model, and a short in-process cache (≤ 16 entries, 60 s, keyed by
the model, the table's width and a hash of the query — the text is never kept; emptied whenever a table is written) lets every search of one query share that embed: MCP
recall's entity and episode legs embed once (P2-8). **Entity hits are read against the page as it is now (P2-5):**
`search_entities` drops a hit whose page is gone or `dropped` — even with `include_archived` — and decides the archived
tier on the current status, not the last sync's copy.
**What an entity's vector is made from is a setting (2026-10-16, owner decision 4):** `entity_embed_text`
(`CICADA_ENTITY_EMBED_TEXT`). `full`, the default and today's behaviour, embeds name, type, aliases and the whole body,
its claims fence included; `prose` leaves the fence out (every claim has its own vector) and caps the text at
`ENTITY_EMBED_MAX_CHARS` (8,000 — past a local model's 512-token window, inside a hosted model's 8,191-token limit). On
the owner-scale synthetic bank the fence is 82 % of what is embedded (43.7M → 7.5M characters). A change re-embeds
every page whose text moves, once. The default flips only after `benchmarks.recall_ab` — the bank's entity vectors
built both ways into throwaway indexes outside the bank, its words index too, a labeled query set run through
`/search`'s page ranking and the vectors alone — shows search no worse on the person's own queries:
`api/.venv/bin/python -m benchmarks.recall_ab --bank <bank> --queries <questions.local.yaml | queries.jsonl> --out <file>`
(exit 0 = no worse; a metered model needs `--allow-metered`; query text is printed only with `--show-queries`). On the
synthetic bank, where half the queries are claim sentences and the prose is a 30-word vocabulary, `prose` loses every
claim-sentence query (search MRR 0.927 → 0.743) and ties every name query.
**Decay's bookkeeping is not what a page says (perf 2026-10-24).** In `full` mode the embedded text leaves out the claim
keys a night's decay moves while the words stay — `confidence`, `decayed_through`, `faded_by_age` — taken out of the
claims fence's JSON lines only (`vector_index.without_decay_marks`; prose and a quoted key inside a claim's text are
kept). Before, every page decay charged (~1,500 a night on the owner's bank) hashed as changed and was re-embedded with
the same words: on the owner-scale synthetic bank one decay night re-embedded 2,001 of 2,001 pages, ~30 ms a page with
the small on-device model on all cores; now 0 (44 on a real fake-engine drain, the pages whose words moved). An entity
vector no longer carries a confidence. The first sync after the change re-embeds each page once. Search is no worse:
`benchmarks.perf.embed_ab` (e5, 600 synthetic pages, 200 labeled queries) gives every page a cosine ≥ 0.998 to its old
vector and MRR 0.629 → 0.625, inside one decay night's own movement under the old text (0.629 → 0.635); the newuser
bank's MRR is unchanged.

### Pictures in the meaning index (vision item 3, 2026-10-28; G195's first image slice)
`api/services/image_index.py`. The owner: video, images, articles, websites "in the same embedding space with the
Gemma model … all running locally". Pictures are **one more kind of `vector_index.db`**: `vec_images` / `meta_images`
beside the text kinds, plus `stats_images` (the kind's mean vector and count), stamped only with its own
`model:images` / `dim:images` / `recipe:images` — never the bank-wide `model`/`dim`, which name the text tables' build
model — and left out of the text re-embed (`embedding_models.pending_switch` counts `REINDEX_ORDER` kinds only).
EmbeddingGemma 2's image encoder puts a picture in the text model's 768-wide space, so a text query meets pictures by
one cosine; a search embeds only the query's words with the text model the table records (`model:images`, the same id
as the text tables on an EmbeddingGemma 2 bank, so recall's cached query vector is reused) and **never loads the
image encoder**.

**What is indexed** (`image_index.sources`, only what is already on this Mac — nothing is fetched for it): `look` (a
saved look's screenshot, in the bank), `capture` (the newest in-bank thumbnail of each saved site's captures; one that
showed the person's account stays outside the bank and is not indexed), `preview` (a media page's stored preview,
`$CICADA_HOME/previews/<bank>/`), `still` (a saved YouTube video's still, or a watched day's — stored only once the
person opened that day — one row per video at its latest day). A still is YouTube's own picture for the id, never a
frame: no video is downloaded and no stream derived (G162). A watched day's still is indexed like its words and never
read by a model that writes memory (ruling 30). Each row's metadata says where it came from (source, page, watched
day's episode, capture, title, day) and the API path that serves it; vectors of pictures that live outside the bank
sit in this derived file inside it, like every other vector (git-ignored, never exported).

**Diffing.** A row's hash is the picture's sha256; the table is stamped with the model and **the same preprocessing
fingerprint the design board uses** (`recipe:images` = `vision_embedder.fingerprint()`: the recipe plus a reference
picture through the real decoder, so a `sips` change re-embeds too — one stamp for both picture stores). A changed
picture re-embeds that row, a picture gone drops its row, a renamed page refreshes metadata with no embed, the same
bytes under two keys embed once. A picture that fails is counted and never stops the rest. Without the image encoder
(or a decoder that cannot run) a refresh only drops what is gone; search keeps working from the stored vectors.

**A new model or fingerprint never empties search (review of #506).** The table has two generations (`images`,
`images_alt`); `serving:images` names the one search reads. A stamp change builds the other generation — resumed
across Sleep's stops while its own stamps match, never swapped in while a `limit` left pictures out — and when it holds
every picture that can be embedded, the pointer moves and the old generation is dropped in one transaction. Until
then search answers from the old pictures (the vector rail: the old table serves until the new one commits).

**Scores.** Raw cosines are not comparable across kinds (a text query sits nearer every passage than any picture),
so a picture is scored by its **lift**, `cos − μ`, where μ is the query's exact mean cosine over every picture
(`q · mean`, from `stats_images`, no scan), and shown only at `lift ≥ LIFT_MIN` (0.06) — "nothing found" is an answer.
**Over the others' mean** (2026-10-29, found driving the app with two added files): the lift is taken against the mean
of the *other* n − 1 items (`image_index.loo_lift`), so with a handful of items the right one no longer drags the mean
up with it (two passages: the plain lift halved the gap and nothing cleared the floor); over many items it is the same
number the floors were calibrated on. On the real models at n = 2 passages and 4 frames: the topics said lift
0.14–0.19 and the red-circle frame 0.13; topics absent ≤ 0.03 and other frames ≤ 0.05. **A lone item** (n ≤ 1, or a
count the stats don't record) has no lift and is never shown for free (review of #529: the owner's one look would have
answered every recall): its cosine must reach an absolute floor measured on EmbeddingGemma 2
(`LONE_PICTURE_COSINE_MIN` 0.67, `LONE_TEXT_COSINE_MIN` 0.68 — a drawn picture's query reaches 0.74–0.81 on it, any
other query's best picture 0.53–0.60; a said topic 0.73–0.77 on its passage, an unsaid one 0.55–0.62), and on any other
model it isn't shown at all (`image_index.clears`, `calibrated`). One recording on the real model: 3 of 3 said topics
shown, 0 of 4 unsaid.
Measured: on synthetic vectors with a modality gap (`benchmarks.perf.image_fusion`, 4 geometries × 3 seeds) RRF put a
picture in the merged top 5 of 100 % of documents-only queries and raw cosine never showed one, while subtracting the
kind's mean kept pictures out (≤ 0.3 %); on the real encoder (`benchmarks.perf.image_index_build`, 400 synthetic
coloured shapes) a query describing a picture lifts it 0.10–0.15, a near miss ≈ 0.08, the best picture for a query
about nothing drawn ≤ 0.03 — 32/32 first pictures right, 0/30 shown for nothing. DigUp's z-score (G195) fails the
floor there: an unrelated query's spread over pictures is a quarter of a related one's (σ 0.011 vs 0.047), so its
best picture reaches a right one's z (2.6 vs 2.2–3.3). The 0.06 floor was
calibrated on synthetic shapes; real screenshots should re-check it (one constant).

**When it embeds — never on a search and never by Sleep.** `image_index.start_refresh` runs one refresh per bank at
a time (a trigger during a run runs it once more), only where the person's click installed the image encoder, never
while Sleep runs (it gives way between steps of 16, `RefreshStopped`, keeping what it wrote). Triggers: 30 s after the
backend starts, after a Sleep run ends, when the image encoder finishes installing, and 30 s after a preview or still
is stored, a capture records a new look or a look is saved (a burst folds into one run). The vectors are made in the
**picture child** (`embed_worker.images`; the text child is under "sqlite-vec" above): nice 10, its math libraries
held to 4 threads, and a memory ceiling of 2,048 MB checked by the child after each request (`ru_maxrss`; macOS lets a
process set no address-space limit on itself) — over it, the child answers and exits and the next request starts
another. The design board's pictures (`design_index`) are made in the same child now.

**Measured** (M-series Mac, the pinned EmbeddingGemma 2 + image encoder, 400 synthetic 640 × 400 JPEGs, cold): 59.9 s
= 6.7 pictures/s (150 ms each, the child's start and both models' load included; sips decode in its own child per
picture); the picture child peaked at 872 MB resident; the backend side grew 2 MB; the table is 4.5 MB for 400
pictures; an unchanged refresh 147 ms; the same 400 built into a copy of the owner's 8,028-page bank, 47.6 s. The
picture leg on that copy, its query vector already made by the entity leg (recall's and hybrid search's case): p50
8.7 ms, p95 17.6 ms; with no picture table, 2.2 / 3.8 ms. Each query embedding its own words first: p50 24 ms, p95
54 ms. Prefix search is unchanged (it never reaches the leg); the prompt hook never calls it.

**One store for looks (meaning index 2).** A look's picture vector the design board already holds — same bytes, a
stamp current for EmbeddingGemma 2 and this fingerprint — is copied into the `images` kind instead of embedded again
(`image_index._look_vectors`); the board keeps its own words leg, example-picture search and tiered order.

**Not yet:** files from folders the person picks (G195's app walk) and documents; a picture or recording group in the
app's find palette (a design-direction-D decision).

### Recordings and videos the person adds (meaning index 2, 2026-10-28; G195 stage 2)
`api/services/media_files.py`, `api/routers/files.py`, the app's `MediaFileIndexer`. **Decided:** the owner told the
coordinator to go with the recommendation (2026-10-28) — speech is transcribed on the Mac by Apple's own recogniser and
the words embedded in the same space (no 561 MB audio model); a video's frames are sampled from the local file the
person picks, into the picture kind.

**The app reads, the backend parses bytes.** A recording or video the person drops on the window (the intake's one
door, `IntakeRouter.accept`, after the refused-roots guard) goes to `MediaFileIndexer`, never to the import. On the Mac
it transcribes the speech (`SpeechAnalyzer` + `SpeechTranscriber`, macOS 26+, only for a locale macOS already has a
speech model for — Cicada never asks for or downloads one, it says how to add one) and, for a video, samples a frame
every 3 s (≤ 1,200) and keeps one per shot (an 8 × 8 average hash that moved > 4 bits from the last kept), each a
≤ 640 × 400, ≤ 200 KB JPEG with its time. It posts only those derivatives: `POST /files/media` (name, kind, sha256,
size, length, language, segments with start/end) and `POST /files/<id>/frames` (≤ 64 a call). The backend never sees
the path or the bytes, never downloads, never derives a stream (G162).

**Speech permission.** `SFSpeechRecognizer`'s header documents a Speech Recognition prompt;
`SpeechAnalyzer`'s interface declares no authorization API, and whether the same TCC service gates it was not tested
(a test would raise the prompt). The app treats it as gated: `authorizationStatus()` (never prompts) is read, the
request is made only inside the person's own drop, and a denial keeps the file without its words, said in words.
`NSSpeechRecognitionUsageDescription` is in the bundle. Checked with fixtures only (`MediaFileIndexerTests`).

**Stored outside every bank:** `$CICADA_HOME/files/<bank>/<file-id>/` (`meta.json`, `transcript.json` scrubbed like
every writer, `frames/<ms>.jpg` + `frames.json`); a demo bank refuses (409). `DELETE /files/<id>` removes it; its
vectors leave at the next refresh, which the delete starts at once.

**Whose words.** A transcript is **the recording's words** (`words_by: the recording`): never an episode, never the
person's own for promotion, never read by Sleep (G195), and every hit says so ("the recording's words, at 12:34"). A
file becomes memory only when the person or an agent uses it in a conversation; then that conversation is the evidence.

**In the one index.** The words are the `files` text kind (passages of ~1,600 characters that keep whole segments and
their start and end, embedded by the bank's text model through `vector_index`'s own diffing sync, so a model switch
rebuilds in one transaction; `stats_files` holds the kind's mean); the frames are `images` rows with `source: frame`,
their file and time. Only the background refresher embeds them (`image_index.start_refresh`, which now also runs for
a bank with added files and no image encoder), outside Sleep, never on a search. `/search?kinds=file` (opt-in, never
in `KINDS`) and recall's "From recordings and videos you added" (local doors only) score a passage by its lift over
the query's mean across every passage, shown at `media_files.TEXT_LIFT_MIN` (0.12): on the real text model a topic said
in a synthetic hour lifts its best passage 0.18–0.2, a topic never said ≤ 0.04 (`benchmarks.perf.media_index_build`).

**Measured** (this Mac under other sessions' load; the pinned EmbeddingGemma 2; synthetic media only): the words of
one hour of speech (9,000 words, 33 passages) embed cold in 7.6 s; the `files` leg answers in p50 10 ms, p95 15 ms.
Transcription itself runs in the app at the recogniser's speed (not run here: it would ask for Speech Recognition;
published figure for the same API ≈ 45× real time, so ≈ 80 s an hour). A video's frames, sampled in the app
(`testBenchFrameSampling`, synthetic 10-minute 1280 × 720 videos): ≈ 37–39 s of sampling per hour; a slide-like video
kept 79 frames in 10 minutes (≈ 470 an hour, ≈ 31 KB each), a mostly still one 1; at the measured ≈ 150 ms a picture
those embed in ≈ 70 s an hour (the worst case, a frame kept at every sample, 1,200 × 150 ms ≈ 3 min). On a copy of the
owner's 8,028-page bank with one hour added, interleaved: recall p50 269 → 278 ms, p95 1,629 → 1,568 ms (noise); the
`files` leg 2.1 / 3.5 ms with no table … 3.4 / 6.2 ms with the hour.

### The quick read's provisional records (G207, 2026-10-22)
`<bank>/.awake/<episode>.json`, one per conversation a quick read covered (`awake_read`, its only writer). It holds
the body revision, the read time, the engine and model, the provisional claims (each `Claim.to_dict()`, G118 spans
included, on pages that exist), and the held names (name, type, page id they would key to, claim count). It is a
**derived artifact**: listed in `bank_registry.DERIVED_ARTIFACTS`, so it is git-excluded, skipped by a bank copy and
an export, and never committed. Losing it costs only the wait until Sleep. Recall reads a record only while its
episode is `processed: false`, and Sleep's `settle` deletes it when it retires the episode. It is never a page,
never a claims fence and never a `pending_store` line: Sleep stays the authority (`capture-and-sleep.md`, "After
capture").

### SQLite FTS5 (lexical index, G136)
`api/services/search_index.py`. One `search_index.db` per bank, **beside `vector_index.db` and never
inside it**: entity names + aliases + prose, every claim (superseded ones kept as history), episode
titles + 600-character passages that tile the evidence text exactly, media/paper metadata, inbox
questions and backlog items (G150), in seven per-kind FTS5 tables (`unicode61 remove_diacritics 2`, prefix `2 3 4`; rowid
`doc_id << 16 | n`). `dropped` pages are never indexed. An episode's `docs.meta` carries what a hit shows without
reading the file — title, harness, origin, conversation id, hash, `index_only` (ruling 30, schema 6) and, for a saved
link's episode, its `site` key (schema 7, review of #372; `channel_items.saved_episode_url` → `reading_hosts.mark_key`,
the Waiting row's rule), so the palette draws the site's own mark. **Derived and disposable** (TODO ruling 3):
deleting it costs a few seconds of CPU and never a fact; a missing, corrupt or schema-mismatched file is
rebuilt, never an error. **Never tracked:** `bank_registry.ensure_derived_excluded` writes
`.git/info/exclude` before the file first exists. It follows a worktree or submodule bank's `.git` file
to the real git dir, and a new bank's `.gitignore` lists the file too. It never edits an existing
`.gitignore`, which would dirty the tree and smear into the next `git add -A` commit. **Freshness:**
Sleep brings it up to date beside the vectors (`search_index.refresh`, off the event loop — the
stamp diff `ensure_fresh` uses, so an idle night re-indexes nothing; a full build only when the file is
missing, damaged or of another schema); every read path calls `ensure_fresh`, a stamp diff over directory
listings (`bank_index.stamps`) that parses only the files whose `(mtime_ns, size)` moved — any difference counts, so a
same-size edit, an add, a removal, a rename and a checkout are all caught, and a fresh process learns "nothing moved"
without a parse (at most one check a second, inline up to 64 changed files, one background worker beyond). The
listing is always taken after the stamps it is compared with (never a `shared_scans` memo), a removal is re-checked
inside the write against the exact name, case included, in a fresh listing (a stat of the old name still succeeds
after a case-only rename on APFS; recall's existence filter applies the same rule), and every write that changes a
row stores a new random `generation` in `meta`: a process that sees another's generation reloads the stamps from the
file before diffing, so rows another process wrote or deleted are never shadowed by a stale in-memory copy. A write
that changes nothing keeps the generation, and a file that fails to index is remembered by its stamp, so one odd file
is tried once per stamp per process, never bounced between processes; the
lifespan and a bank switch warm it in the background. The caller always passes the active bank's path
— the module never resolves a bank (the split-brain rule). `search_service` ranks over it (QuickMatch
tiers 0–2), fuses it with the stored vectors in `mode=hybrid`, and **never embeds in `mode=prefix`**.
**The query is never logged**: not by loguru, and not by uvicorn's access log (`api/main.py` strips the
query string of `/search` and `/conversations/recent`, G136 R22).
**Every claim's object, per page (`claim_rows`, 2026-10-19).** G141's reverse layer (the Projects list and a
project's cluster) resolves every indexed claim's object against the page names it holds — id, name or alias, the
`resolve` rule — instead of a MATCH OR'ed over every project's id and name (~0.6 s at 700 projects). The rows
(`object`, payload JSON) are kept in process memory per page under the stamp the index holds and re-read only for a
page whose stamp moved (one range read per page, one scan past 64), in one read snapshot with the stamps they are filed
under; disposable like the file, `None` while no usable index answers. Only a page-to-page claim names a project: the
payload carries `object_kind` (added without a schema bump — a row indexed before reads by id or name only, never by
alias), a `value-of-` predicate never names one, and an alias under 3 characters names nothing (the detail's
`_tree_names` guard). The list's converted payloads are a slotted LRU (`_PAYLOAD_CLAIMS`, 40k, ~1.2 KB each with
its key; ~13k / ~16 MB on the 8k-page synthetic bank).

### Continuity index and session registry (G110 slice 1a)
`$CICADA_HOME/continuity/<bank-id>.index.json` is a **derived, disposable** map of every `ep_*.md` to `(mtime_ns, size, row)`, where a
row is the head scalars of a Stop-hook episode (`id`, `harness`, `session_id`, `cwd_hash`, `captured_at`,
`last_turn_at`, `processed`, `processed_by`) read from at most 16 KB up to the first `turns:` key — never a full parse
inside a hook. It lives **beside the registry, never inside a bank** (G110 fix round 2: proving that git ignored an
in-bank file proved unreliable, so nothing is written there and no git runs on this path). It shares the registry's
guarded home, no-follow regular-file opens and 0600 files; its lock is `<bank-id>.index.lock` beside it; with no safe
home, contention or any I/O failure it stays in process memory. Its rows keep `capture_kind`, so a persisted index
decodes after a restart. Schema 2 derives `cwd_hash = sha256(project_dir)[:16]` from episode frontmatter;
the plaintext path remains only in that episode, and no title or turn is persisted in the index. Cached rows accept
validated hashes, not paths. Selection compares the hook cwd's hash; the chosen full parse revalidates against the
actual episode path value, never a frontmatter-supplied hash. Schema-1 path caches and extra cached fields are replaced
atomically on a successful index write, even for an empty, missing or unreadable episodes directory; episodes are
unchanged. An older in-bank `continuity_index.json` is ignored, never read and never deleted. A wrong schema or
malformed row is rebuilt; it is never an error and never an authoritative absence.

The **continuity registry** (`api/services/continuity_sessions.py`, `$CICADA_HOME/continuity/<bank slug>-<hash8>.json`)
is outside every bank — `continuity_home` refuses a `CICADA_HOME` that resolves (symlinks followed) inside the memory
root or any configured bank. One row per harness session: the harness, `sha256(cwd)[:16]` (never the path),
`started_at` (earliest), `last_prompt_at` (latest), `continues` (one episode id, first write wins). Ids, a hash and
times only; monotone merges; one bounded `flock` transaction per request; 30-day expiry, ≤ 1,000 rows, files 0600.
Every registry, lock and index file is opened without following a symlink in its final component and refused unless
it is a regular file (`continuity_sessions.open_regular`), so a planted link can never redirect a read, a write or a
`chmod` into a bank.

### The catch-up cursor and the "still?" answers (vision item 10, 2026-10-28)
`$CICADA_HOME/inbox_catchup/<sha256(bank path, session id)[:20]>.json` holds the inbox ids one session's catch-up
already served (`inbox_catchup.Cursor`): ids and a time, written atomically, 0600, outside every bank and git,
forgotten after 12 hours (each read sweeps the old ones). Neither the path nor the session id is stored in clear.
`<bank>/_still_answered.yaml` (`still_questions`) is the bank's memory of the person's answers to "Are you still …?":
`answered: {<claim id>: {on: <day>, answer: still|ended|other|dismissed}}`, written by the conflict resolver and
committed with the answer as the person's (the `_merge_rejected.yaml` pattern), so a claim answered is not asked again
for 180 days (a role) or 120 (an interest). An enum and a day — never a label or the person's words.

### Telemetry ledger (`~/.cicada/telemetry/`)
Append-only JSONL, machine-global, **never in a bank or git**. `CICADA_TELEMETRY=off` disables it.
**IDs and enums only — never claim text, query text or answer text.** The `read` kind (G124) records
an entity id and a surface enum, filed in a sibling `reads-*.jsonl` that
`sync_service.components["telemetry"]` deliberately does not stat — the app maps that component onto
its consumption domain, so a card open must not move it. The `hook_recall` kind (G149) is one row per
recall-hook firing: harness, event, reason enum, the page ids and their count, token and latency buckets,
and the model id when the harness sends one. It is filed beside `read` for the same reason, and like
`capture` it is a per-turn receipt that `consumption_stats._activity` keeps out of every Usage view. The
prompt never is. The `read_agent` kind (G166) is one row per `cicada_record_read` call — entity id, an `outcome` enum, a
`host_class` enum (`walled | public`), the harness and connector id; never a URL, the tool the agent named, a note or an
excerpt — filed beside `read` and kept out of every Usage view like `capture`. The `check_agent` kind (G61 S3) is one row per `cicada_record_check` — item id, entity id, `outcome`, `host_class`, `effect` (`noted | recommended`) enums, harness, connector id; never the source, its host, a quote or a proposed value — filed beside `read_agent`. The `web_check` kind (TODO ruling 27) is one row per web lookup settled, skipped or undone —
`action` (`settle | skip | undo`), item id, entity id, `by` (`sleep | agent | person`), a `reason` enum, harness; never
the query, the link, its host, the quote or the answer — filed beside `read_agent`; the lookup's engine call itself is
an `llm_call` of stage `web_check` with its price. The `video_queue` kind (G162) is one row per claim, release or completion — `action`, `count`, a
closed fail-code enum, the harness and connector ids; never a link, a title or a reason — filed beside `read` and kept
out of every Usage view (`SIBLING_KINDS`, `NON_SPEND_KINDS`, `PER_TURN_KINDS`).

**Cycle usage (2026-09-28 ruling, Sleep page only).** Every `llm_call` a Sleep cycle makes carries `refs.cycle_id`
(from the ambient `sleep:<id>` scope, so it survives `to_thread`/`gather`; the engine-independent tail runs outside
that scope and is never counted), and the cycle's `sleep_run` gains `usage_tagged: true` plus, when observed,
`plan: {connection, windows: [{window, before, after, resets_at, before_is_first_seen}]}` — numbers and enums only.
Claude's windows come from the calls' rate-limit signals (`before` is the value after the first call); the ChatGPT
plan's from two fresh app-server snapshots bracketing the cycle. `api/services/cycle_usage.py` derives `usage` for
`GET /sleep/history/{commit}` and `usageSummary` for `GET /sleep/history` at read, joined after the git cache; every
figure carries its basis (`charged` | `list` | `plan` | `free`), and a cycle without the marker reads `null`, never zero.
The Sleep page's Details (Last cycle, Past nights, an opened cycle's Models) and the engine menu's captions read them
(2026-09-28 ruling); a `plan` block and a `cycle_id` are numbers and ids, never text.
An `llm_call` with a real cost carries `refs.cost_source` (`telemetry.COST_SOURCES`, 2026-10-16): `provider` when the figure is the charge the provider reported for that call (OpenRouter's `usage.cost`; litellm sends `usage: {include: true}` on every OpenRouter request), which wins over `table`, litellm's estimate from its bundled price table. A model the table does not list still gets OpenRouter's own charge; with neither, `cost_usd` is `null` and no source is filed — unknown, never zero.
Since Sleep page v5 a drain's calls also carry `refs.drain_id` (the run's id, ids only), so `GET /sleep/runs/{id}` sums a whole run — a paused or discarded batch's calls included — and `sleep_run` rows carry `drain_id`/`batch`/`batches`; `usage_for_drain` lists a plan window at the run level only when every batch saw the same reset time.
**Plan share (owner 2026-10-16; no new ledger field — derived at read).** A plan run's `usage.planShare` /
`usageSummary.planShare` (and the engine menu's `lastRunShare` + `lastRunEquivUsd`) say, per window, weekly first, how
much of it the run used, each with its basis: `measured` (the window's own reading moved by a point or more: after −
before, the whole plan's change), `under` (it did not move at the reading's 1-point resolution: below `under`, `share`
null — never 0) or `estimated` (the run's list-price size — the CLI's own metering, which weighs model and cache as a
plan does and raw token counts do not — times the window's pooled rate from earlier cycles that moved it by ≥ 2 points,
at least two of them, over the last 35 days machine-wide; with `samples`, and `under` too when the reading itself did not
move, which caps it). A window with neither a reading nor a rate is left out; a model's own window is never estimated
for a run that did not report it (`cycle_usage.plan_share`, `rate_samples`, `rates_of`).

**Feedback events (G113):** every inbox resolution emits a `resolution` event (`stage: feedback`,
`refs` = item id, kind, predicate, entity id, action label, `verdict: agreed|overruled|neutral`,
winner/loser claim ids, the extractor's confidence and model, and since vision item 10 the question's `asks` shape
and its page's `page_use` bucket (`high|mid|low`, so the reward can say whether the use-weighted order asks what the
person answers) — ids and enums only, never claim text), Stage-3 reconcile emits one `audit` event per supersede/reject, and the dedup sweep emits one
`dedup_verdict` per judged pair. `telemetry.FEEDBACK_KINDS` names the three (a superset,
`NON_SPEND_KINDS`, also excludes `capture`/`handshake`/`read`); `consumption_stats.stats()` excludes
them from `by_connection` so they never show as an "unknown" connection. Nothing learned from the
ledger is auto-applied — `GET /consumption/feedback` shows the rates; feeding them back into
prompts is G78.

### Git — versioning and provenance

**The commit-graph (owner via the coordinator, 2026-10-29; `git_service.write_commit_graph_sync`).** Sleep's
engine-free tail ends by rewriting git's own `.git/objects/info/commit-graph` with changed-path Bloom filters
(`git commit-graph write --reachable --changed-paths`, `_commit_graph_safely`), on every exit path, under the bank's
git write lock (`commit-graph` is a `WRITE_SUBCOMMANDS` member, not a tree writer). It is a git-internal derived file:
never tracked, never a commit, rebuilt from the history at any time, ignored by git when missing or stale, and a
failure only logs. Every path-limited history read uses it — the History tab, `entity_history`, the provenance strip.
On an owner-scale bank copy (8.0k pages, 1.6k commits; 17 pages × 6): History tab p95 224 → 128 ms (p50 137 → 48),
`entity_history` p95 203 → 105 ms, `entity_commit_authors` p95 174 → 75 ms; the first write 423 ms, a rewrite with
nothing new 24 ms.

Every Sleep cycle commits with a **machine-parseable message**:

```
Sleep cycle 2026-03-20

entities/recruiting-thread.md: updated (source: ep_2026-03-20_002, trigger: sleep/extraction)
nudges/nudge_005.md: resolved (trigger: user/companion_app)

Cicada-Author: gpt-5.4-mini
Cicada-Engine: claude-cli
Cicada-Session: <id>
```

**Git's author field is not provenance (G203, 2026-10-22).** A bank commits under whatever identity git is configured
with, and the half nobody configured is the neutral `Cicada` / `cicada@localhost` that `ensure_commit_identity_sync` sets in
the bank whenever it becomes active (never a guess from the account; `headless.md`, "Commits with no git identity"). Who wrote a change is read only from the
trailers. Every reader of a bank's history today takes the trailers and none takes `%an`/`%ae`: the page history and
blame (`git_service._parse_authors`, `page_blame`, G198), the contributors view and its calendar
(`get_contributors`, `consumption_stats`), claim recovery (`claim_recovery`, `%(trailers:key=Cicada-Author)`), the
coexist reopen and the Sleep page's history. Seen 2026-10-22 on a scratch bank where every commit's git author was the
neutral one: blame named `verify` accepted by `user`, contributors listed `cicada`, `user`, `verify` and the model, and
history named `claude-haiku-*`. The one `%an` reader, `repo_context` (and the app's `GitRunner`), reads a declared
workspace repo, never a bank.

**Triggers:** `sleep/extraction`, `sleep/promotion`, `sleep/conflict_resolution`, `sleep/decay`,
`sleep/state`, `sleep/expiry`, `sleep/followup`, `sleep/source-links`, `maintenance/source-links`, `sleep/site-check`, `capture/calendar`, `capture/tab-groups`, `capture/contacts`, `nudge/resolved`, `clarification/resolved`, `user/manual_edit`,
`user/companion_app` (also the Projects page's writes, G141 — `Project update <date>`,
`Cicada-Author: user` — and the Backlog section's, `Backlog update <date>`), `user/backlog_import` (G150's
importer),
`mcp/<harness>` (a local agent's write), `remote/<harness>` (a remote connector's write, G135),
`inbox/page_edit/resolved:apply|dismiss` (the person's answer to an agent's proposed page edit, G198), `sleep/web-check`
(the web check's settles, `Web check <date>` under the model, TODO ruling 27; an agent's is `mcp/<harness>`) and
`inbox/web-check/undone` (the person's undo, `Web check undone <date>`, `Cicada-Author: user`).

**A page edit's commit (G198).** `Page edit <date>` (or `Page edit proposed <date>` for an inbox proposal), the manifest
line `entities/<id>.md: edited (trigger: …)`, then a paragraph with the agent's `Reason: <one line>` and one
`Evidence: <episode> <start>-<end> <kind> <hash>` line per located quote (spans, never words), then the trailers. A reason is
collapsed to one line, so it can never open a trailer. An applied proposal names the agent first and `user` second
(`Cicada-Author:` twice — who wrote the words, who accepted them) and says `Accepted by the person in the inbox.`;
`_build_description` appends the reason to the history row. **Blame** (`page_blame`, `GET /entities/{id}/blame`): one
`git blame --porcelain` over the prose lines (frontmatter and claims fence left out) and one `git log --no-walk` over the
commits it names give, per `##` section (an Article's `###` sections apart), each contributor's line count, last change and
commits, and per commit its author, kind, trigger, reason and `accepted_by`; heading and blank lines count to no one, an
uncommitted line is `uncommitted`, never guessed. Blame walks the page's whole history (0.6 s at 600 commits, 1.9 s at
2,000 on a 600 KB page, review round 1), so it is kept per (bank, page, the newest commit touching the page, mtime, size)
in the process — a commit elsewhere does not empty it — with one computation in flight per key; a request waits ≤ 0.5 s
(shielded) and is otherwise answered `pending: true`, which the app never draws (it keeps its last copy and asks again,
a few times); every git call has a deadline (30 s, the process killed past it), and a failure is never cached. Never
stored.

**Three trailer families, all inert to entity-line parsing — extend them, don't break them:**

- **`Cicada-Author:`** — *which agent authored this*. A model id for agent writes, **a harness
  label** (`claude-code`, `claude-web`, `chatgpt`, …; `agent` when none was sent) for a write that
  arrived through MCP, where the model is not disclosed (G135; the trailer never names a model — since round 4 it is joined at read from the captured
  turn), the
  literal **`user`** for manual/companion-app writes, **`unknown`** for legacy untrailered commits,
  and **`cicada`** for system maintenance with no model and no user in the loop (the one-shot
  migrations, the split-out decay commit, the `State snapshot` commit, the `Expiry` and `Follow-ups` commits, the `Recover dropped claims` commit). Built by
  `git_service.build_commit_message(...)`, parsed by `_parse_authors`.
  `git_service.author_identity` buckets a harness label (and `agent`) as kind `harness`, which the app
  names and marks as that app; the pre-G135 `mcp-agentic-write` claim placeholder reads as `agent`
  through `canonical_author`, never rewritten (F2-back R-B9, R-B10). A read whose body carries an
  author kind folds `git_service.AUTHOR_SHAPE` into its ETag; bump it when the buckets move.
  Powers `GET /contributors`: one `git log --name-only --root --no-renames --no-show-signature` over the whole history (a `diff-tree` per
  commit cost ~18 s at 1,043 commits and ran again on every commit, the ETag being HEAD; 2026-10-16).
  **An agent's commit carries only the agent's change** (owner 2026-10-16, from the backend
  hunt): every door that runs a mutating tool — the stdio MCP server, the tool door (`/tools/call`), the CLI's in-process
  mirrors — snapshots the bank's dirty pages first (`agent_commits.setting_apart`, `git_service.snapshot_dirty_sync`),
  and `agent_commits.commit_write` (and the agent's web-check settle) then commits an edit that was already on a path
  it takes apart, first, as `Uncommitted edit kept apart <date>` with no author (`commit_touched_sync`, trigger
  `agent/kept-apart`), the way the inbox routes do; a path the agent did not change keeps its edit uncommitted.
- **`Cicada-Engine:`** — exactly one per main commit (`claude-cli|ollama|litellm`), **omitted
  entirely rather than guessed** when no LLM ran. Read back via git's own
  `%(trailers:key=…,valueonly)` directive, not a Python parse of `%b` — pulling the whole body to
  extract one line grew the endpoint from 787 B to 378 KB for 8 commits on the live bank.
- **`Cicada-Session:`** — one line per distinct conversation consolidated, capped at
  `MAX_SESSION_TRAILERS` (50) by the call site, not the builder. User-action commits stay
  session-less.

**Event write ownership (G183(b), checked 2026-10-06).** The follow-up resolver commits the retired inbox item,
the event page and any companion-note episode as `user`; `_state.md` follows in its own `cicada` commit.
No current event write, whether from the person or an agent, can merge into an open item:
`claim_reconciler.reconcile_events` emits only divergence nudges, which `write_claim_nudges` always writes
as new files; only conflict nudges merge. `test_followup_manifest.py` covers person answers and agent-over-person
milestone divergence, verifying owned paths, author trailers, unchanged conflicts and clean trees after commits.
The historical missing-merged-conflict report is not reproducible on any current event path. Revisit the progress
helper's created-name manifest if event reconciliation starts emitting a mergeable kind, or divergence items
start merging into open items.

**G85 — decay gets its own `cicada`-authored commit.** Temporal decay runs over entities a cycle
never referenced: no LLM, no source episode, pure arithmetic. Folding it into the main commit
stamped it with whichever model happened to run Stage 1/2, inflating that model's contributor counts
for work it never did. `_finalize` splits `sleep/decay` entity lines into their own commit —
`Sleep cycle <date> (decay)`, `Cicada-Author: cicada` — committed *before* the main commit so the
main commit's `git status` scan never sees them. A split that can't happen degrades back to the old
behavior rather than aborting the cycle. **Known asymmetry, disclosed not fixed:** the split is
path-granular, not hunk-granular, so a subject that is both decay-eligible and claim-touched in the
same cycle lands whole in the `cicada` commit. Narrow in practice; fixing it needs hunk-level
staging.

**A drain's commits.** Each batch is one `Sleep cycle <date> (batch k of n)` commit (k counts batches actually run, n is
recomputed from what is still waiting, so skipped ids shrink it; a lone batch keeps the plain subject — `_cycle_kind` reads
only a trailing `(decay)`). Its manifest lists only that batch's episodes, `Cicada-Session:` only that batch's
conversations (batch size ≤ 50 keeps every one), `Cicada-Author:` the models that batch used. The `(decay)` commit exists
once, in the last batch, before its main commit.

**One git writer per bank (F2-back R-B1 … R-B4).** Every mutating git command — `git_service`'s
commits, a `_run_git` write, the one-shot migrations, the expiry restore — runs in a worker thread
under one re-entrant lock per resolved bank path, so tasks, threads and `asyncio.run` bridges queue
instead of colliding on `index.lock`; the backend is one process, git's own lock is the cross-process
guard, and only its `File exists` refusal is retried (five tries, the lock never deleted). Reads pass
`GIT_OPTIONAL_LOCKS=0`, and `test_git_write_lock.py` refuses a git write spawned anywhere else.
A folder, paper or Wispr commit that still fails keeps its paths in `cicada-pending-commits.json`
in the bank's own git dir (a worktree's, never the shared common dir), says so on its channel, and
lands on that writer's next run — or at the start of the next Sleep cycle, before any stage writes —
under its own author (R-B5).

**One page writer at a time (audit 2026-10-05 P1-2).** A claim write is read → reconcile → write; atomic replacement
keeps one write whole but not two (both reported `written`, one survived). `page_lock.page_lock(bank)` — the same
cross-process, re-entrant `flock` as `episode_lock` (`episode_ids.dir_lock`), on the bank directory itself — is held
by `agentic_write.write_claim`/`retract_claim`, `progress`'s event writers, `fact_sources`' source writers and
`paper_metadata`'s page updates, the dedup sweep's merges (each across its commit), the app's decay-class and
repo-link rewrites, the inbox's normalization answer (its covered pages, `_predicates.yaml` — written atomically — and
the item, re-read under the lock, through its own `user` commit, inside the answer's write admission and with git's
write lock held throughout; G98/G115), and by the MCP's page-writing tools (`write_claim`, `retract_claim`, `note_progress`,
`add_source`, `change_source`, `record_check`, `record_read`, `edit_page` (G198; its inbox answers are posted after the
lock is released), and `record_watch` around its record) across the write
**and its commit**. Nothing waits on a network call under it: such a tool asks Sleep before it takes the lock and
reuses the answer, and `record_watch`'s link save and queue credit stay outside. Some holders are `async` routes and
the inbox's follow-up resolver, which wait on the event loop — one page operation is milliseconds. **Order:** the write
admission (below), then the page lock, then the git write lock (inside the commit), then `episode_lock` — never the
reverse. **Not under it yet:**
Sleep's own page writes (they run inside the write window, which every guarded writer now waits out or refuses) and
the inbox's other resolvers.
**Write admission (G183):** the window guards are an admission, not a bare check. `write_admission` is one per-bank
admission: an in-process count of holders plus an `flock` (`LOCK_SH` per holder) always on
`$CICADA_HOME/sleep/<bank>/admission.lock` (outside the bank — the bank's stable identity, so scaffolding git under a
live holder does not move admission) and also on the bank's `.git` path when it has one (nothing created, a different
inode from the page lock's; processes that do not share `CICADA_HOME` still meet on a git bank), so the stdio MCP
server, another process, is admitted too. A lock that exists but cannot be opened **fails closed**: the writer gets
`AdmissionUnavailable`, and Sleep does not open its window. A guarded writer asks `is_writing()` only once it holds
admission and keeps the hold through its page writes and its own commit: synchronous code in a worker thread uses
`admitted()` (refuses with the writer's own 409 or sentence) or `shared()` + `holding()` (a writer whose answer changes
shape: folder and Wispr Flow syncs, skill pages, the stdio MCP tools whose in-window write stays uncommitted for
Sleep); **async code uses `run_admitted()` / `route()`**, which runs the transaction on the *writer loop* — one
long-lived loop in a daemon thread, in a copy of the caller's context — with the flock taken off any loop: neither a
cancelled request nor its loop's teardown cancels the transaction, so its hold lasts until its threadpool workers and
its commit are done; a hold that lands after its waiter is gone releases itself in the worker thread (no callback on a
loop that may be closed); the backend's shutdown drains live transactions (30 s) before the process goes; and no
request loop waits on a flock (a lint keeps `shared()`/`admitted()` out of every `async def`). Sleep **sets its flag first, then waits** (`wait_for_writers`, off the loop): every writer that saw the window
shut took its hold before the flag, so it finishes its write and commit before Sleep reads a page, and every later one
sees the flag and refuses. The flip runs at the run's start, at a drain batch's Stage 2 and at the tail; closing the
window takes nothing. The wait is **bounded and honest**: logged past 5 s; past 60 s (or with an unopenable lock) it
answers False and **Sleep reads and writes nothing** — at a batch's Stage 2 the drain stops as a `busy` pause (the
batch's conversations wait, the frozen work is kept for Continue; a scheduled run's `busy` pause is the schedule's to
replace), at the run's start nothing is flushed or read, and the tail is skipped. A timed-out wait is never treated as
an open window. **No admission spans a model call or a network fetch:** the dedup sweep takes it per merge (before the
page lock, through the commit or the put-back, `may_write` asked once inside; only a stale answer before each judge
call); an inbox conflict answer synthesizes its prose before admission and, admitted, re-plans on the page as it is
then, using the prose only if every input it was made for is unchanged — the item, the pick, the entity, the
planned body, the answer sentence, the date (else the dedup-guarded fallback); a link save
(`POST /sources/save`, `cicada_save_url`, a remote `cicada_record_watch`'s save, the reading ask's save) fetches with
no hold (`media_ingestor.prepare_one`) and writes and commits inside one (`write_prepared`, the index checked again) —
refused (409, nothing written) when Sleep holds the pages, since a page written inside the window could ride the
batch commit under Sleep's author; a stdio save the backend refused is never written directly behind its back. The
remote runtime resolves the bank once per call and admits, gates, writes and commits that one bank; a backend POST it makes (an inbox answer) names that bank in
`X-Cicada-Bank`, so the backend refuses it — nothing written — if the active bank moved meanwhile. An admitted
backend transaction is admitted on the request's pinned bank (G177 `bank_binding`; `route()` pins a call made
outside a request) and its context — the pin — rides onto the writer loop, so the admission, every write and the
commit name one bank even if the person switches mid-transaction; admitting any other bank is refused
(`WrongBank`, fail closed). **Disclosed
exceptions (still probes or unadmitted):** `enrich-links` and `verify-sites` refuse up front only — once started they
keep writing and committing after a window opens, and `verify-sites` writes frontmatter it parsed before its fetch, so
it can overwrite an edit made meanwhile; the person's paper-details run checks before each request and before writing
a response and stops, but the pages it wrote before the window stay uncommitted until its end commit and can ride a
batch commit; batch intake (upload, RSS, bookmarks, Safari tabs, feed polls, connector syncs, Telegram saves) creates
new media pages between fetches without admission, so a page written inside a window can ride a batch commit; the
one-shot bank migrations at boot and activation are not admitted (activation is refused only during a person-started
drain), except the predicate-fold clean-up (`dedup_normalization_items`, G98/G115), an admitted transaction that defers
with no marker while Sleep holds the pages. Inside a
window a stdio agent's claim still writes and rides the batch commit (in-window attribution is a DECIDE); Sleep's own
stages take no page lock. `GET /state`'s refresh of `_state.md` (a cursor that commits alone) runs inside admission
and is skipped while Sleep holds the pages — the file is served as it is, and the run's tail refreshes it.
`test_write_admission_sites.py` is the inventory: every non-GET route, every GET whose code names a write, every
MCP tool and every bank migration `run_bank_migrations` runs is classified (admitted, held, per-write, probe, intake,
capture, registry, outside, sleep, banks, migration, none) with its reason, and the admitted ones are checked to take
admission in their code.

**Entity-level history is one `git log` over the page** (`git_service.entity_history`, newest first, bounded
by `MAX_PROVENANCE_COMMITS`): every commit that touched it, enriched with parsed commit metadata — the same commits
the provenance strip counts. It replaced `git blame` plus one `git log -1` per surviving commit (1.0–1.7 s on a
3,500–6,000-claim page, ~30 ms now; `benchmarks/scale`). Past the cap nothing the page still shows is lost:
every commit whose lines survive (the creation row and its conversation) is added after the window from
`git blame --incremental` and one batched `git log`, `EntityResponse.history_truncated` says older touches were
left out, and `GET /entities/{id}/history?skip=N` reads them (review round 1). That blame diffs every revision it walks
back through — 2.3 s on a synthetic owner page with 520 commits of a 5 MB file, paid by the card and its History tab on
every open — so its answer is kept per (bank, page, newest touching commit, file mtime and size) in the process, and a
request waits for it at most `_SURVIVORS_WAIT_S` (0.5 s): past that the window is served while the blame finishes in the
background for the next open (owner page, 2026-10-14). Repo-level history uses `git log`. **No changelog in frontmatter** — git handles all history, zero storage
overhead, no growing fields.

---

**Current beliefs and historical events (G118/G93, 2026-10-07).**
`claims.is_current(claim, now=day)` is the shared read predicate for claim objects
and index payloads, using the machine-local day shared by claim writers and
conditional-response caches: any `valid_to` or successor means closed, including a
born-closed happening. A future start is not current; stated ends are inclusive
and reads stop presenting them as current even before the next expiry commit.
The stated-end parser is shared with `claim_expiry`; milestone targets are not
expiry dates. History remains in markdown, FTS and provenance. Search keeps
closure metadata and sorts current claims first; closed events keep their day
and state and render as past events or earlier states. Episode citations keep
unsuperseded events visible (`current: true` means no obsolete-belief styling
on that wire contract); a successor marks an earlier event state. Vector claim reads recheck the candidate page,
so a stale vector cannot resurrect a closed claim or a deleted page. The FTS
schema version is 5 (stated-end metadata); the cache rebuilds automatically.
FTS candidate claims use a single read snapshot of payload and document stamp.
Matching `(mtime_ns, size)` stamps avoid reparsing on every keystroke; changed
or missing pages are rechecked against markdown once per request, so a rebuilding
or stale index cannot label an already closed claim as current.
The claim-list endpoint, transclusion and graph claim projections share the
same currentness predicate rather than maintaining separate open-window tests.
The paper card applies it to both personal reasons and external context too.

**Time-dependent projection lag.** Read-time claim checks and provenance ETags
use the writers' machine-local day. The persisted graph edges, graph observer
overlay cache and vector membership evaluate starts and stated ends when built:
time alone may leave them behind until the next Sleep or sync (normally at most
one Sleep). A paused Sleep delays that refresh. Read-time vector checks still
exclude expired results, but cannot add a previously future claim until sync.
The graph's Store-domain ETag remains tied to its existing version vector.
