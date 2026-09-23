# G141: project timelines — dated happenings, "you are here", and the knowledge around a project

Status: design, 2026-09-23. It will be committed as `docs/superpowers/specs/2026-09-23-g141-project-timelines-design.md`,
and the backlog row is **G141** in `docs/goals/memory-evolution.md`.

How it was made: six readers wrote reports on claims and time, extraction, surfaces and the demo bank. Three
architects wrote competing designs: *claims-native* (happenings are claims), *derived-first* (assemble what
exists, write last) and *page-journal* (a `## Journal` prose section per project). Two judges scored them.
One judge looked at owner value and agent legibility, the other at rails, cost and risk. This spec takes
**claims-native's storage**, **derived-first's order and spend gate**, and page-journal's best details. Where
the judges disagreed, the ruling is in §3 with its reason.

Code was read at `dev` @ `6eea9ee`, and every file:line below was re-checked there. App paths are relative to
`app/CicadaApp/Sources/CicadaApp/`. Nothing was read from `memory/`, `~/.cicada` or `~/.claude/projects`.

**Privacy.** Every name is demo-generator fiction:
- `bob-example` is the owner;
- `hana-example` stands in for `<person-a>`;
- `rover-arm-project` stands in for the robotics project;
- `pick-and-place-demo` stands in for `<demo-x>`;
- `lab-cluster-example` is the lab cluster;
- `media-example-cluster-guide` is the PDF guide.

URLs are on `example.com`. The owner's real people and projects never appear in this file, in a plan, a
commit or a PR.

---

## 1. Problem

The owner, 2026-09-23 (other people's names and project names redacted):

> "in cicada i need a good way to track 'projects' with clusters of knowledge and ongoing things being
> dated. So for example if i'm working on a robotics project, i may or mayb not have a timeline setup for
> it. I'd like to see graphically me today and progress throughout the timeline, and also have stuff like
> 'yesterday, Rodrigo [user], got a pdf guide [url pdf], provided to him by <person-a> [person], that walk
> him through connecting to the lab cluster [specs of lab cluster in the cluster entity maybe], and is
> connecting to run the <demo-x> demo'. Stuff like this would be awesome."

He asks for four things.

1. **Projects are first-class things to track, whether or not a timeline was ever set up.** A project with
   planned dates and one with none must both look truthful.
2. **A graphical timeline per project.** It shows "me today" (a you-are-here marker, and where the project
   stands now) and progress across time (what happened and what is planned).
3. **Dated happenings, narrated, with every participant linked.** In his example:
   - the owner is `[user]`;
   - a person is `[person]`;
   - a document has its URL, `[url pdf]`;
   - a piece of infrastructure has its specs on its own page;
   - a sub-goal (the demo) is also linked;
   - there are two statuses: *done* ("got the guide", yesterday) and *ongoing* ("is connecting").
4. **A cluster of knowledge around a project:** the people, tools, documents, ideas and sub-projects that
   belong to it.

Today none of this exists as one thing:
- There is no per-project timeline.
- There is no milestone concept (`grep -ri milestone api/` finds only comments).
- There is no "you are here", and nothing records a happening with more than two participants.
- Nothing reads "an ongoing thing nobody mentioned for three weeks".
- The data that does carry dates (G17 `due` claims, G140 `expected_end`, supersede chains, G118 spans with
  turn times, conversation timestamps) is never drawn together.

## 2. What already exists

| capability | where (dev @ 6eea9ee) | what G141 does with it |
|---|---|---|
| The claim dataclass: bi-temporal `valid_from`/`valid_to`/`recorded_at`, observer, trust, `evidence` spans (`:176`), `expected_end` (`:184`) | `api/services/claims.py:117-184` | Adds four optional fields that are omitted when empty, plus two event predicates (§4). |
| Records: `RETRACT_PREDICATE`, `is_record` (born-closed bookkeeping, dropped by every claim surface) | `claims.py:250-263`; call sites `routers/claims.py:76`, `search_index.py:390`, `provenance.py:439`, `mcp_tools.py:1108,1309-1375` | The precedent for born-closed claims. Events are **not** records: they stay searchable and citable (R-PJ3). |
| G17 `due` claims: the extractor turns a deadline into a `due` claim, never an entity | `entity_extractor.py:113-117` | Read as milestones on a project (read-compat, R-PJ4). |
| Stated ends: `stated_end` reads `expected_end` or a date-valued `due`; `expire` closes the claim the day after | `claim_expiry.py:41,56,83`; `_expire_claims_safely` is `sleep_cycle.py:772-815`, called first in the tail's clean-tree-guarded branch (`:866-876`), before the polls' `git add -A` | `target` is a new field that expiry **never** reads. A met `due` and a missed `due` close the same way, so G141 never shows an expired `due` as done. |
| Human protection is origin-gated: `is_human` needs `user_stated` **and** an origin in `_HUMAN_ORIGINS = {"manual_edit", "clarification"}` | `claim_reconciler.py:62,77-86`; the MCP owner write sets `manual_edit` at `agentic_write.py:429-430` | The app's writes use `origin: companion_app`, so PJ-3 adds it to `_HUMAN_ORIGINS` (R-PJ18); without that, nothing the person sets in the app is protected. |
| The belief-slot key `K` is `(subject, predicate, context, observer)` | `claim_reconciler.py:93-95` | A milestone slot deliberately ignores `observer` and keys on `object` (R-PJ4), so it lives in `reconcile_events`, not in `K`. |
| A claim `context` that is a valid slug other than `general` becomes a graph **facet satellite** once a subject has two (the F1 bug class: a location in the context field) | `claim_contexts.py` (`is_facet`); `graph_builder.py:141-200, 336-360` | Event claims, `spec` claims and the demo's `due` claims keep `context: general`. A milestone's slug lives in `object`, never in `context`. |
| Reconcile: a multi-valued key coexists or reinforces an exact duplicate, and reinforce never moves `valid_from` | `claim_reconciler.py:436-445`; `_close` `:138`; `_reinforce` `:144` | So Monday's and Thursday's "connects to the cluster" fold into Monday. Events get their own branch with date-aware ids (§5.1). |
| Trust table: a human over a human on the same date gives `CONFLICT_NUDGE`, and an agent can never close a human claim | `claim_reconciler.py:186-217` | Milestone slots break same-date ties by lifecycle rank, not by date (§5.1). |
| Claim decay: skips closed claims and evergreen subjects, and lowers confidence on open ones, which can raise a decay nudge | `claim_reconciler.py:493-566` (skips at `:510`, `:513`) | Skips `is_event` claims, the same way (R-PJ12). |
| Cardinality comes only from the bank's runtime `_predicates.yaml`; an unseen predicate is multi-valued; `due` is in neither seed list | `predicates.py:159-189`; `docs/goals/m5-prep/predicates-seed.yaml:193-230` | Event cardinality lives in code (R-PJ5). |
| Claim ids: Sleep's `_emit_claim_id` includes `valid_from` (`clm_<valid_from>_<hash>`); the agent `_claim_id` does not | `entity_extractor.py:492`; `agentic_write.py:212`; `write_claim` `:262`; `_date_from_episode_id` `:86` | Every event writer uses one new dated form (§5.1). |
| Stage 1 writes a `due` as a relationship claim: `text` "<source> due <target>", `context: general`, `object_kind: node` | `entity_extractor.py:552-566` | Read-compat derives a milestone's name and slug from that shape (R-PJ4). |
| **Page-less claim loss.** A claim whose subject has no page is skipped, under a false comment ("re-emitted next cycle"; the episode is already marked processed). The subject key is `sanitize_id(raw name)`, not Stage 2's id. | `claim_pipeline.py:139-146`; `entity_extractor.py:530-531`; `sleep_cycle.py:1657` | Fixed first, at $0 (PJ-0). |
| Promotion counters | `entity_resolver.py:86-112, 216` | Happenings never touch them (R-PJ9). |
| Evidence: `turn_stamps`, `turn_at`, `span_status`, `verify` | `evidence.py:399,431,460,512` | The date anchor and the freshness rule. |
| The Stop hook writes `turns:` as an **integer count**, so its episodes have no per-turn times | `transcript_capture.py:261,284` | PJ-4 writes the list shape (R-PJ16). |
| Stage 1: the prompt is 6,695 chars (~1.7k tokens), a chunk is ≤ 12,000 chars; the strict (codex) schema is pinned | `entity_extractor.py:17,138,223`; `engine_schemas.py:53`; `tests/test_engine_schemas.py:56`; `sleep_cycle.py:1522` | PJ-7's prompt, schema and anchor header. |
| Provenance: best span, entity provenance, the candidate-page prefilter, derived quotes | `provenance.py:220,251,373`; `inbox_context.py:73`; `ProvenanceSpan` `schemas.py:868` | The timeline's quotes, its conversations, and the reverse-claim fallback. |
| The wire: `ClaimModel` (no `expectedEnd`), `GraphNode` (no `created`/`lastReferenced`), `InboxKind` | `schemas.py:710, 1018, 1261` | Additive camelCase fields, and a `followup` kind. |
| One key's bi-temporal chain | `GET /entities/{id}/timeline`, `routers/claims.py:92-117`; `Views/Graph/BeliefTimelineView.swift` | A moved milestone's history, for free. |
| FTS claim rows (subject, object, payload) | `search_index.py:390-408` | `claims_about(object_id)` for reverse lookups (§6.4). |
| Closed claims read as "no longer current" in two history surfaces: episode citations set `current: _current(claim)`, and `/search` ranks any hit with `valid_to` as history | `provenance.py:441-444`; `search_service.py:418,444` | A born-closed done happening would render struck through as "No longer current". Both learn `is_event` (R-PJ3). |
| `_state.md` project rows (top 7); the machine's timezone | `state_dictionary.py:97, 483-490`; `handshake.py:240` | Schema v3 `now`/`next`; the zone `when.py` resolves dates in. |
| Telemetry: feedback kinds, non-spend kinds, `record_read(surface=…)` | `telemetry.py:33,43,213` | A `followup` resolution, the `happenings` counts, the surface `project`. |
| Graph shape tag, folded into the `/graph` ETag | `routers/graph.py:32,47` | Bumped once, when `GraphNode` gains its dates (PJ-5). |
| The owner resolver; commits that stage only their own paths | `owner_identity.py:62`; `git_service.py:1165` | Every person write. |
| A 409 while a Sleep cycle runs: `sleep_cycle.get_sleep_state().status == "running"` | `routers/maintenance.py:102-106` (`enrich-links`), `:164` (index rebuild) | User writes during a Sleep cycle. |
| `## History` bullets and their date key | `entity_body.py:22-29,128` | Read as grey legacy rows, never written. |
| App seams: `AppTab` (`Views/Sidebar/SidebarView.swift:13`), the card's `DetailTab` (`Views/Graph/EntityDetailCard.swift:125`), `ProvenanceRouter.open` (`Views/Provenance/ProvenanceRouter.swift:122`), `weekDots`/`sparklinePath` (`Views/Sources/ActivitySeries.swift:63,84`), `AppRouter.routeToEntity` (`Support/AppRouter.swift:148`), `Sync/VersionVector.swift` | — | The Projects page is built on them. |
| The demo generator: deterministic, dates relative to `date.today()`, no `today=` seam, inbox pinned `== 6` | `api/services/demo_bank.py`; `api/tests/test_demo_bank.py:29` | Extended with the scenario (§12). |

**Flag carried from the demo reader.** The on-disk `memory/banks/demo/` is not the generator's output. It holds
one non-synthetic Stop-hook capture, because `demo` was the active bank when a session ended. Every screenshot
and fixture for this feature comes from a **freshly generated** demo bank.

---

## 3. Rulings

Each ruling is binding for G141's slices. Revisit one only on the trigger it names.

**R-PJ1. Happenings and milestones are claims.** They are not prose sections, not a new file type and not
entities.
- *Why:* CLAUDE.md names claims as the machine-legible half, carrying observer, trust, G118 spans, sessions,
  supersede and retraction, the FTS claim index, recall's claim leg and the remote scopes. A new file type
  would have to regrow each of those.
- A `## Journal` section (page-journal) loses roles and status to prose. Its safety also depends on every
  present and future LLM body writer preserving that section: `conflict_resolver`'s synthesis replaces a
  whole agent-only body, and `entity_merge` drops unknown sections today.
- An event entity would be G17's "July 8th" mistake again.
- *Revisit:* only if M11 (§17) shows the owner reads the page in Obsidian more than in the app.

**R-PJ2. Derive first, write second, spend last.** The judges disagreed on the base: judge 1 picked
claims-native, judge 2 picked derived-first. This spec takes claims-native's storage and derived-first's order.
- **First, PJ-1 and PJ-2:** a $0 read model over what every bank already holds.
- **Second, PJ-3:** event claims with their $0 writers, the person in the app and agents over MCP. An agent
  in the conversation can narrate the owner's own sentence the same day, with no Sleep and no spend. On a
  bank that has never consolidated, this is the fastest route to what he described.
- **Last, PJ-7:** Sleep extraction 💸, built only after the owner-graded measurements M1–M3 say derived
  moments plus agent writes fall short.
- *Why:* judge 2's risk lens holds for spend and schema. Judge 1's owner-value lens holds for the agent write
  path, which costs nothing and so does not need to wait.
- **G105 holds.** An agent's `cicada_note_progress` call is an enrichment, never the only path to a
  timeline: capture stays the Stop hook's, and PJ-1's derived moments (and PJ-7, if built) read the captured
  episode whether or not any model chose to call a tool.

**R-PJ3. A done happening is born closed; an ongoing one stays open.** A `happened` claim with
`status: done` or `dropped` is written with `valid_to == valid_from`. One with `status: ongoing` has
`valid_to: null` until a successor settles it.
- *Why:* the dangerous claim readers are the ones that treat "open" as "currently believed": recall's current
  view, graph edges, conflict generation, decay, expiry, the handshake, and the current half of `/search`.
  Born-closed makes all of them correct with no change, and it removes most of the 17-reader churn both judges
  flagged.
- The few *history* readers learn one test, `claims.is_event`:
  - `mcp_tools._recent_changes` and `_history_line`;
  - `cicada_get_perspective(history=true)`;
  - `/claims`;
  - the card's contested-keys Timeline tab;
  - **episode citations** (`provenance.episode_citations`, `:443`): an event row carries its `status` and day
    and is never `current: false`, so the app never strikes a done happening through as "No longer current";
  - **`/search` claim hits** (`search_service.py:418,444`): an event hit is ranked and rendered as a dated
    happening, never in the superseded-history tail;
  - the app's belief rows (palette, entity card, citation list), which render an event as
    `day · status · sentence` (PJ-5).
- A grep-gate test fails for any module that iterates closed claims without calling `is_record` or `is_event`.
- **Events are not records.** `is_record` stays retracts-only, so events remain in FTS (`search_index.py:390`)
  and in episode citations (`provenance.py:439`). "When did I get the cluster guide" still finds the claim.
- Recall's claim leg (`claim_subject_hits`) admits `is_event` claims whatever their validity. That is one
  branch, in the gated list, so a born-closed happening still maps to its project.

**R-PJ4. A milestone is its own belief slot.**
- The predicate is `milestone`, and the slot is `(subject, milestone, object = <slug>)`: the `object` is the
  stable slug and `text` is the display name, so a rename never moves the slot. `context` stays `general`.
  - *Why not `context`:* a valid non-`general` context becomes a graph facet satellite once a subject has two
    (`claim_contexts.is_facet`, `graph_builder.py:336-360`), so two milestones would split the project's node
    into "First grasp" and "Lab showcase" satellites, the F1 bug class. Context is "which part of a life", not
    a slot id.
  - The slot **ignores `observer`**, unlike `K` (`claim_reconciler.py:93-95`), so an agent's "done" and the
    person's "planned" meet in one slot and the trust table can arbitrate (§5.1).
- The `target` field is one `claim_expiry` never reads.
- Moving a target or marking it done is an ordinary supersede, so the chain *is* the history. The read model
  serves it as `milestones[].chain`, following `supersedes` across the `due` → `milestone` hop. The existing
  `GET /entities/{id}/timeline` keys on `(predicate, context)` and would show only the `milestone` half, so the
  Plan's "moved ›" feeds `BeliefTimelineView` from `milestones[].chain` instead.
- A G17 `due` claim whose subject is a `project` **reads** as a milestone (read-compat).
  - **Name:** the claim's `text` with the `due` label and the date literal removed ("First grasp due
    2026-09-09" → "First grasp"); when nothing is left, the subject's name. Stage 1 writes
    "<source> due <target>" (`entity_extractor.py:552-566`), so an extracted `due` on the project itself is
    named after the project.
  - **Slug:** `due-<YYYY-MM-DD>` from the object (`-2` on a same-date collision), since every extracted `due`
    has `context: general` and so carries no name of its own to key on.
  - The first time the person touches it (done, move, drop), a real `milestone` claim is written with
    `supersedes: <due id>`, and the `due` gets `superseded_by`. After that the milestone is the one source.
  - **A `due` expiry already closed** (its date passed first, the usual case) keeps its expiry `valid_to`; the
    touch only adds `superseded_by`. That and `withdraw` (§5.1) are the only mutations of a closed claim.
- **A `due` closed by expiry reads "passed, no word on how it went".** It never reads "done" and never reads
  "missed".
- `missed` is stored only when a person says so. "Overdue" is always derived at read.
- G17's `due` keeps its meaning everywhere else: on non-project subjects, in the extractor, and in expiry.

**R-PJ5. Event cardinality lives in code.** `claims.event_cardinality(predicate)` answers for `happened` and
`milestone` before `build_cardinality_fn` is asked, and both answers are **multi-valued** for the general
`K`-keyed table: two milestones of one project share `K` (context `general`), so a single-valued answer would
turn every second milestone into a conflict. The one-head-per-slug rule lives in `reconcile_events` (§5.1),
which the general table never reaches for an event.
- *Why in code:* an existing bank keeps a stale `_predicates.yaml`, and `build_cardinality_fn` reads only that
  file, so the answer cannot depend on it.
- `happened` and `milestone` are added to the seed's `multi_valued` list, and `spec` too (the three spec claims
  in §4.2 coexist), for new banks.

**R-PJ6. Python decides every date, and nothing relative is ever stored.**
- One pure resolver, `api/services/when.py`, turns words into a date against an anchor. The anchor is the
  turn's `ts`, or else the episode's timestamp, in the machine's zone. The resolver always beats a model's date.
- `date_basis` (`stated | turn | episode | person | written`) records how a date was decided. `written` is an
  agent write with no evidence to anchor on: the date is the write's own day (or its `when` resolved against
  the write instant), and the Reader says "dated when it was recorded".
- **Both HTTP wires carry absolute dates and instants only.**
- The app derives "Yesterday", "overdue", "quiet" and "in 8 days" at render time.
- `cicada_project` derives them for each call and prints both forms, "yesterday (2026-09-22)", so an agent
  never has to trust a relative word alone.
- A test greps every **event claim's** `text`, `valid_from`, `target` and `status` after every write path for
  `yesterday|today|tomorrow|ago`. Episodes are raw words and are out of its scope (the person's Log text and
  the demo's templates legitimately say "today"); §5.3 says how a Log entry's own time phrase leaves `text`.

**R-PJ7. Neither ETag carries today or a viewer timezone, and `/projects` is not a Store domain.** This
resolves a judge disagreement. Claims-native and page-journal made `/projects` a Store domain whose ETag
includes the date, and judge 2 found that no sync component ticks at midnight, so it would go stale.
- Both endpoints follow the provenance precedent: fetched on demand, ETag over `entities`, `episodes` and
  `inbox`, held in an in-memory `ProjectsCache` that is emptied on a bank switch.
- There is **no `VersionVector` mapping**, so the ship-together rule has nothing to pair.
- The list still paints cold from the Store's cached `/graph` snapshot. `GraphNode` gains `created` and
  `lastReferenced`, and `graph.NODE_SHAPE` is bumped. That is a server-only ETag change.
- Moments are grouped by the local day in the **machine's** zone, the same zone `when.py` uses. That zone's
  name is part of the ETag `extra`. It changes when the Mac's zone changes, never at midnight.

**R-PJ8. Extracted happenings are anchored or dropped.** This is a stated exception to "provenance never
blocks memory".
- A Sleep-narrated happening whose quote cannot be located is dropped. A relationship without a quote is
  still a belief the model can defend; a narrated story without its words is the model's own story. Nothing
  is lost: the episode stays and stays searchable.
- An *agent* writing through MCP may omit the quote. Its happening lands with `reasoning` evidence (chip
  "Inferred"), because the agent chose to write it, the same rule `cicada_write_claim` follows.

**R-PJ9. Happenings never feed promotion, never create pages and never become graph edges.**
- Their names never enter `all_relationships`, `in_episode_relationship_count`, `episode_cooccurrences` or
  `linked_to_existing`.
- An unmatched name stays text on the participant. It is relinked **at read** when exactly one page matches
  the name or an alias. That link is marked `derived` and is never written.
- A literal object already emits no edge (`graph_builder.regenerate_edges_from_claims`, `:472`). A test pins
  that participants do not either.

**R-PJ10. A happening lives on the most specific project it names.**
- The parent's timeline rolls up its `part-of` children, current or closed, to depth 2.
- A happening with no project page is filed on the owner page with `{role: project, surface: <raw>}`, but only
  if it touches at least one existing page. Otherwise it is dropped with reason `no_home`.
- The project's timeline finds these owner-page happenings by name or alias once the page exists.

**R-PJ11. There is never a percentage.** Progress is "N of M milestones done" (M counts planned + done +
missed, and excludes dropped), plus activity density over time. Cicada cannot know how far along a project is.
It can only count what it was told. (DR-59 already bans a bare "%".)

**R-PJ12. For events, a follow-up question replaces decay.**
- `_decay_claims` skips `is_event` claims: a done happening is history, and a plan months out is not stale.
- A quiet ongoing thread, or an overdue milestone, raises one engine-free `followup` inbox item instead. This
  is G4's "how did it end up going?", finally with a producer (§9).
- Entity decay of the project page is untouched. Every event write bumps the subject's and participants'
  `last_referenced` to `max(existing, valid_from)`, so a moving project never decays and a silent one decays
  exactly as today.

**R-PJ13. "Quiet" adapts to the project's own rhythm.**
- Q = `max(14 days, 2 × median gap)` between the project's distinct moment days in the last 180 days.
- A follow-up becomes eligible at `max(21 days, Q)`.
- *Why:* CLAUDE.md's decay is "proportional to how frequently it used to be referenced". A project discussed
  monthly is not quiet after two weeks.
- Derived-first proposed 3×. That made the demo's 24-day-quiet thread not quiet at all (median gap 10 → 30),
  a sign that 3× hides the case the owner described. 2× gives 20.
- *Revisit:* on M9 (the follow-up answer rate).

**R-PJ14. The derived underlay never infers "ongoing" from a predicate list.**
- Derived-first's `ONGOING_PREDICATES` (`uses`, `runs-on`, `part-of`, …) made durable facts read as activity in
  motion, and both judges flagged it.
- A derived moment is "said on D", "changed" (superseded) or "ended" (closed at its stated end). Nothing else.
- "In motion" comes only from `ongoing` event claims and from the next milestone. On day one, the owner's own
  washed words ("Connecting to Lab Cluster Example now so I can run the demo") say what is in motion, at the
  top of the story.

**R-PJ15. No wikilinks inside claim YAML.**
- The sentence is plain text. Each participant carries `surface`, the exact substring of the sentence it links,
  and the writer checks that `surface` occurs in `text`. If it does not, the participant shows as a chip only.
- *Why:* a wikilink inside a fenced YAML block does not render in Obsidian anyway. A sentence with wikilinks
  plus a participants list can drift apart (judge 2), and `[[…]]` would pollute FTS.

**R-PJ16. The Stop hook writes the one per-turn sidecar shape.** This amends G118 R-PB4 on evidence; it is not
a relitigation.
- `transcript_capture` writes `turns: [{offset, ts, speaker}, …]` from the transcript JSONL's own message times,
  through the `episode_staging` sidecar writer. The sidecar is outside `content_hash`, the last key, capped
  head-stable at 500.
- The count becomes `len(turns)`.
- *Why:*
  - R-PB4's reason was that a reader must check the type, and that survives.
  - Nothing reads the integer today: the only `turns` hits in `api/` and `mcp/` are its two writers plus the
    list readers.
  - Without per-turn times, every Claude Code and Codex happening is dated "around" the session's first day,
    and a session resumed over three days anchors to day 1.
- **Offsets come from the Stop hook's own body.** `transcript_capture` renders `"{role}: {text}"` lines
  (`transcript_capture.py:137`), not `episode_staging`'s line renderer, so `episode_staging._stamps` cannot be
  reused as is. PJ-4 zips `conv.turns[].ts` (already kept by `transcript_extract.Turn`) with
  `evidence.turn_starts(body)`, and shares only the sidecar's shape, cap and placement with the stager.
- **The cap is head-stable, so it keeps the oldest 500 turns.** In a session past 500 turns the newest turns
  carry no stamp and fall back to the episode timestamp (basis `episode`), which is day 1 of a resumed
  session. This is disclosed, not fixed here; M5 counts Stop-hook episodes over the cap.
- The slice's plan re-greps. If a count reader has appeared, the count moves to `turn_count:`.

**R-PJ17. The page-less fix is split.**
- PJ-0 keys Sleep's relationship claims through Stage 2's `name_to_id`, maps "the user" to the `owner: true`
  page, replaces the false comment with a drop counter, and logs dropped subjects as counts. It costs $0 and
  needs no pending-store change.
  - `name_to_id` is a local of the resolver today (`entity_resolver.py:116-247`, used for edges at `:319`),
    and `run_claim_pipeline` (`claim_pipeline.py:76-107`, called at `sleep_cycle.py:1298`) sees only the raw
    extraction. PJ-0 returns the map from Stage 2 and threads it into `entities_to_claims`, including the
    resolver's fuzzy endpoint match (`:322-330`) so a claim and its edge land on the same page.
- "Hold an unpromoted subject's claims with the pending entity, and write them on promotion" changes the pending
  store. It is its own **DECIDE** on the G141 row, and is not built here (judge 2).

**R-PJ18. The person's log is a span, not a copy.**
- The in-app Log field writes a small companion episode through `episode_staging` and `episode_scrub`
  (`origin: companion_app`, `processed: true`, `processed_by: user`). The happening cites it as a `user` span.
- *Why:* the Reader then opens the person's own words, search finds them, and Sleep never re-extracts them.
- `processed_by: user` is one more value in an already open field: it holds `sleep`, `agent`, `parser` and
  harness names today (`agentic_write.py:745`, `episode_staging.py:69`), and the `processed` flag, not this
  field, is what the G114 readers test. It needs no ruling. `test_episode_writers_scrub.py` covers the new
  writer.
- Milestone set, move and done writes carry no episode. Their evidence is `reasoning` with
  `origin: companion_app`, and the chip reads "Set by you in Cicada".
- **`companion_app` joins `_HUMAN_ORIGINS`** (`claim_reconciler.py:62`) in PJ-3. Today the set is
  `{manual_edit, clarification}`, so an app-written `user_stated` claim would not be `is_human` and an agent or
  Sleep claim could supersede the person's milestone. Only `routers/projects.py` sets this origin: the MCP
  tools never take an `origin` argument, and a test pins that no stdio or remote path can produce one in
  `_HUMAN_ORIGINS` except the existing `manual_edit` owner write.

**R-PJ19. One sentence can yield two happenings, and Sleep settles only conservatively.**
- The owner's sentence becomes a done happening dated T-1 and an ongoing one dated T-0.
- Sleep's engine-free settle rule: a `done` happening closes an open `ongoing` one on the same subject only
  when they share at least 2 linked non-owner participants and the ongoing one is older.
- In every other case the thread stays open, and the follow-up asks (R-PJ12).

**R-PJ20. A commons guard keeps hub pages out of the cluster.** A member linked to more than 12 project pages
across the bank (an editor, a language) goes on one "Also uses" line, and its moments are not pulled into
this project's timeline. *Revisit:* on M4.

**R-PJ21. The band spends no colour.**
- The Today marker is `textPrimary`, not accent. DR-5 limits the accent to six uses, and a marker is not one of
  them. DESIGN_RULES §10 already says so.
- Status is encoded by shape (●, ◐ and a bar, ◇), in the neutral text ladder.
- The one hue on the page is the type dot on participants and cluster members (DR-7 and DR-8: once per item).
- DESIGN_RULES §10 says the band's "dots use data hues". A happening has several participant types, so any one
  hue would be arbitrary. This departs from §10's literal text, and §9 holds only dated owner rulings with his
  words, so it is an **owner DECIDE**: PJ-5 shows him both bands (neutral shapes vs a hue per dot) on the demo
  bank and records his answer as a §9 line. Neutral ships only if he picks it.

**R-PJ22. Navigation.** A **Projects rail cell** is recommended: the owner asked for "a good way to track
projects", which is a destination.
- **Where and which number.** The default is the seventh page cell, after Sources, as ⌘7: the rail's order is
  its ⌘ order (DR-22's tooltips, DR-68's ⌘1–6), so a cell anywhere earlier renumbers pages the owner already
  knows. "Right after Home" is the alternative if G108 renumbers the rail for Home anyway (Home does not exist
  yet; §10 of DESIGN_RULES plans it as ⌘1).
- This spends a rail slot and a ⌘ number, so it needs the owner's **G108 ruling** before PJ-5 merges. It is
  not assumed. PJ-5 then updates DR-60's and DR-68's "⌘1–6" in the same PR.
- *Fallback:* "Open project ›" on a project's entity card, opening the same project and Reader columns from the
  card's column; a Home "In motion" section joins it only once Home ships (G108).
- The card's existing "Timeline" tab (contested beliefs) keeps its meaning. The project page calls its band
  "Timeline", and a test pins that the two never appear on one surface.

**R-PJ23. Remote.**
- `cicada_project` is in scope `read`. `cicada_note_progress` is in scope `record`.
- A quote (the person's verbatim words) reaches a remote connection only with `sources`, the G135 rule already
  applied to recall excerpts and the inbox `Cause:`.
- **The person's own Log text is his verbatim words too.** A happening with `origin: companion_app` (§5.3)
  carries his sentence as `text`, so without `sources` a remote `cicada_project` and the remote primer's
  Current line show it as participants and status only ("a note of yours on Pick And Place Demo, 2026-09-23"),
  never the sentence. Agent- and Sleep-composed sentences are Cicada's words and are shown.
- A remote happening is never `observer: owner`.
- The catalog gains both tools in `TOOL_SCOPE` (`cicada_project: "read"`, `cicada_note_progress: "record"`),
  `READ_TOOLS` gains `cicada_project` and `WRITE_TOOLS` gains `cicada_note_progress`
  (`api/remote/catalog.py:29-50`). A remote write is refused while Sleep runs, as every remote write is
  (R-R27).

---

## 4. Data model

### 4.1 Two predicates, four fields, one test

In `api/services/claims.py`, beside `RETRACT_PREDICATE`:

```python
HAPPENED = "happened"      # something occurred (done), is under way (ongoing), or was stopped (dropped)
MILESTONE = "milestone"    # something planned, with or without a target date
EVENT_PREDICATES = frozenset({HAPPENED, MILESTONE})
EVENT_STATUSES = {HAPPENED: ("ongoing", "done", "dropped"),
                  MILESTONE: ("planned", "done", "missed", "dropped")}
PARTICIPANT_ROLES = ("owner", "from", "with", "for", "about", "used", "document", "project")
DATE_BASES = ("stated", "turn", "episode", "person", "written")

def is_event(claim: Claim) -> bool:        # the one test, like is_record
    return claim.predicate in EVENT_PREDICATES
```

The new optional `Claim` fields go after `expected_end`. Each is omitted from YAML when empty, like `evidence`
and `expected_end` (R7). A legacy fence therefore re-renders byte-identical, and a fixture test pins that.

| field | type | written on | meaning |
|---|---|---|---|
| `status` | enum per predicate | event claims | The state **as of `valid_from`**. It never changes after write; a new state is a new claim that supersedes the old one. |
| `target` | `YYYY-MM-DD` | `milestone` | The planned date. It is never `expected_end` and never `due`, so expiry never reads it. |
| `participants` | `[{role, surface?, entity?, url?}]` | event claims | `surface` is the exact substring of `text`, dropped when it is not one (§5.1). `entity` is a page id when one resolved at write; one that no longer resolves (merged, archived, dropped) is relinked at read by `surface`, like an unmatched name. `url` is set for a `document`. |
| `date_basis` | `stated \| turn \| episode \| person \| written` | event claims | How `valid_from` was decided. The Reader header says it in words. |

The existing fields, as event claims use them:
- **`valid_from`:** when it happened, or when the plan was stated. It is never in the future.
- **`valid_to`:** equal to `valid_from` for `done`/`dropped` (born closed, R-PJ3); null for `ongoing` and for
  the head of a milestone slot.
- **`text`:** the plain sentence. It is what FTS indexes and what is rendered.
- **`object`:** `object_kind: literal`. For `happened`, the dedup key: the sentence case-folded and
  whitespace-collapsed, ≤ 120 characters. For `milestone`, the slot's stable slug (R-PJ4).
- **`context`:** `general` for both. It is never a slot id, because a non-`general` context becomes a graph
  facet (R-PJ4).

`ClaimModel` (`schemas.py:710`) and `transclusion_resolver.claim_to_model` gain `status`, `target`,
`participants`, `dateBasis` and, finally, `expectedEnd`, which G140 left off the wire. All are additive
camelCase, and the Swift decoder ignores unknown keys.

### 4.2 The owner's scenario, literally (demo fiction, T = 2026-09-23)

The episode `ep_2026-09-23_003` (Telegram, with a `turns:` sidecar) has this body:

```
user: Yesterday Hana Example sent me the lab cluster onboarding guide (https://example.com/guides/lab-cluster-onboarding.pdf). It walks me through connecting to Lab Cluster Example, and I'm connecting now so I can run the Pick And Place Demo.
```

It yields two happenings. Both are filed on the most specific project named, `pick-and-place-demo`, and the
parent `rover-arm-project` rolls them up through `part-of`. An excerpt of
`entities/pick-and-place-demo.md`'s fence follows. Offsets are illustrative, and unchanged defaults are
omitted.

````yaml
```claims
- id: clm_pick-and-place-demo_happened_4e1a09c2_2026-09-22
  text: Bob got the lab cluster onboarding guide from Hana Example; it walks through connecting to Lab Cluster Example
  subject: pick-and-place-demo
  predicate: happened
  object: bob got the lab cluster onboarding guide from hana example; it walks through connecting to lab cluster example
  object_kind: literal
  observer: agent
  source_trust: agent_extracted
  confidence: 0.8
  valid_from: '2026-09-22'          # "Yesterday", resolved against the turn's ts in the machine's zone
  valid_to: '2026-09-22'            # born closed: a done happening (R-PJ3)
  recorded_at: '2026-09-23'
  source_episodes: [ep_2026-09-23_003]
  authored_by: claude-code          # an agent wrote it live over MCP (PJ-3), before any Sleep
  origin: mcp
  session_ids: [ses_demo_rover_02]
  evidence:
  - {episode: ep_2026-09-23_003, start: 6, end: 131, kind: user, hash: 3f9c0a1b22de}
  status: done
  date_basis: stated
  participants:
  - {role: owner, surface: Bob, entity: bob-example}
  - {role: document, surface: lab cluster onboarding guide, entity: media-example-cluster-guide, url: 'https://example.com/guides/lab-cluster-onboarding.pdf'}
  - {role: from, surface: Hana Example, entity: hana-example}
  - {role: about, surface: Lab Cluster Example, entity: lab-cluster-example}
- id: clm_pick-and-place-demo_happened_9b07d311_2026-09-23
  text: Bob is connecting to Lab Cluster Example to run the Pick And Place Demo
  subject: pick-and-place-demo
  predicate: happened
  object: bob is connecting to lab cluster example to run the pick and place demo
  object_kind: literal
  observer: agent
  source_trust: agent_extracted
  valid_from: '2026-09-23'
  valid_to: null                    # ongoing: open until a successor settles it
  source_episodes: [ep_2026-09-23_003]
  evidence:
  - {episode: ep_2026-09-23_003, start: 132, end: 245, kind: user, hash: 3f9c0a1b22de}
  status: ongoing
  date_basis: turn
  participants:
  - {role: owner, surface: Bob, entity: bob-example}
  - {role: used, surface: Lab Cluster Example, entity: lab-cluster-example}
  - {role: for, surface: Pick And Place Demo, entity: pick-and-place-demo}
```
````

The cluster's specs are ordinary claims on its own page, which is where the owner guessed they would be. They
are not part of the happening.

```yaml
# entities/lab-cluster-example.md (type: tool), claims fence excerpt
- {id: clm_lab-cluster-example_spec_…, subject: lab-cluster-example, predicate: spec, object: 4 GPU nodes, object_kind: literal, …}
- {id: clm_lab-cluster-example_spec_…, subject: lab-cluster-example, predicate: spec, object: Slurm-example scheduler, object_kind: literal, …}
- {id: clm_lab-cluster-example_spec_…, subject: lab-cluster-example, predicate: spec, object: login.example.com, object_kind: literal, …}
```

All three keep `context: general` and coexist because `spec` is multi-valued (R-PJ5). Three aspect contexts
(`compute`, `scheduler`, `access`) would split the tool's graph node into three facet satellites.

The durable binary facts keep living as ordinary claims: `hana-example provides media-example-cluster-guide`
(person as subject, which avoids the seed's `provided by → provides` inversion) and
`pick-and-place-demo runs-on lab-cluster-example`. **Why a sentence plus participants, and not N triples:** a
happening is n-ary. Split into triples it loses the fact that these things were one occurrence, and it
collapses under the reinforce rule (§2).

### 4.3 Milestones, including a moved one

This is `entities/rover-arm-project.md`, fence excerpt. The G17 `due` from July was read as a milestone until
the person moved it on 2026-09-10. Expiry had already closed it the night its date passed; the move wrote the
real `milestone` chain and set the `due`'s `superseded_by` (R-PJ4).

````yaml
```claims
- id: clm_2026-07-22_1b2c3d4e                     # legacy G17 claim (Stage 1's id form), read-compat slug due-2026-09-09
  text: First grasp due 2026-09-09
  subject: rover-arm-project
  predicate: due
  object: '2026-09-09'
  context: general                # as Stage 1 writes it; never a slot id
  observer: owner
  source_trust: user_stated
  valid_from: '2026-07-22'
  valid_to: '2026-09-09'          # closed by expiry at its stated end, before the person touched it
  superseded_by: clm_rover-arm-project_milestone_first-grasp_2026-09-10   # added by the touch
  evidence: [{episode: ep_2026-07-22_003, start: 96, end: 131, kind: user, hash: 0be1c2d3e4f5}]
- id: clm_rover-arm-project_milestone_first-grasp_2026-09-10
  text: First grasp               # the display name; a rename edits only this
  subject: rover-arm-project
  predicate: milestone
  object: first-grasp             # the slot's stable slug (R-PJ4)
  object_kind: literal
  context: general
  observer: owner
  source_trust: user_stated
  origin: companion_app
  authored_by: user
  valid_from: '2026-09-10'        # when the plan was restated
  valid_to: null                  # head of the slot
  supersedes: clm_2026-07-22_1b2c3d4e
  status: planned
  target: '2026-10-01'            # moved from 2026-09-09: the chain shows the slip
  date_basis: person
  evidence: [{episode: '', start: -1, end: -1, kind: reasoning, hash: ''}]
- id: clm_rover-arm-project_milestone_arm-assembled_2026-08-09
  text: Arm assembled
  subject: rover-arm-project
  predicate: milestone
  object: arm-assembled
  context: general
  status: done
  valid_from: '2026-08-09'        # done on; target 2026-08-12, so "3 days early", derived at read
  target: '2026-08-12'
  date_basis: stated
  # …
```
````

The legacy `due` above is exactly what a demo-generated bank holds: its generator writes the `due` claims, runs
expiry, and only then writes the person's moves (§12).

A done milestone stays the **open** head of its slot. "Arm assembled, done on Aug 9" is a current truth about
the project, and recall renders it as `milestone · done 2026-08-09 · Arm assembled`.

These are derived at read and **never stored**: yesterday, overdue, quiet N days, early or late, "N of M", the
cluster, and the moments.

### 4.4 A derived moment (the $0 underlay, wire only)

On a bank with no event claims (day one, PJ-1), claims that share an anchor episode and a local day become a
**moment**. This is how `GET /projects/rover-arm-project/timeline` serves one:

```json
{
  "kind": "moment",
  "id": "m:ep_2026-09-23_003:2026-09-23",
  "day": "2026-09-23",
  "at": "2026-09-23T16:04:00Z",
  "dateBasis": "turn",
  "state": "said",
  "via": "pick-and-place-demo",
  "facts": [
    {"claimId": "clm_hana-example_provides_…", "subject": "hana-example", "predicate": "provides",
     "object": "media-example-cluster-guide", "phrase": "Hana Example provides Lab Cluster Onboarding Guide"},
    {"claimId": "clm_bob-example_connects-to_…", "subject": "bob-example", "predicate": "connects-to",
     "object": "lab-cluster-example", "phrase": "Bob Example connects to Lab Cluster Example"}
  ],
  "participants": [
    {"id": "bob-example", "name": "Bob Example", "type": "person", "isOwner": true},
    {"id": "hana-example", "name": "Hana Example", "type": "person"},
    {"id": "media-example-cluster-guide", "name": "Lab Cluster Onboarding Guide", "type": "media",
     "url": "https://example.com/guides/lab-cluster-onboarding.pdf"},
    {"id": "lab-cluster-example", "name": "Lab Cluster Example", "type": "tool"}
  ],
  "quote": {"episode": "ep_2026-09-23_003", "start": 6, "end": 245, "kind": "user", "status": "current"},
  "conversation": {"id": null, "episodeId": "ep_2026-09-23_003", "title": "Notes on the lab cluster",
                   "origin": "telegram", "harness": null, "resumable": false}
}
```

A moment's `dateBasis` may also be `day` (a claim with only `valid_from` to go on). `day` exists on this wire
only; it is never written to a claim and is not in `DATE_BASES`.

The moment carries the owner's own washed sentence plus fact chips. It does not compose his grammar. The
composed, role-typed sentence arrives with PJ-3 (agents and the person) and PJ-7 (Sleep). **A derived moment
is suppressed when an event claim cites the same episode**, so a day never shows the same thing twice.

---

## 5. Write paths

### 5.1 The shared core: `api/services/progress.py` and `api/services/when.py`

All three writers call one module. `agentic_write.write_claim` stays the general fact tool, and its signature
does not grow event-only arguments.

- `record_happening(memory_path, *, subject, text, status, participants, when, anchor, evidence, observer, origin, authored_by, session_id, settles=None) -> dict`
- `set_milestone(memory_path, *, subject, name, target=None, status="planned", slug=None, …) -> dict`
- `advance(memory_path, *, subject, claim_id, status, on=None, target=None, …) -> dict`: the explicit
  supersede.
- `withdraw(memory_path, *, subject, claim_id, by, reason) -> dict`: writes the G140 `retracts` record. An
  open claim closes. A born-closed one gets `superseded_by` set to the record, and that is the one mutation a
  closed event ever receives. `_how_closed` already reads that shape as "withdrawn".

The callers pass the active bank's path, and the module never resolves a bank (the split-brain rule). Every
write runs `reconcile_stage3` over the subject's existing claims, as `agentic_write.write_claim` does
(`agentic_write.py:485`), so the event branch below applies to the app and MCP writers as well as to Sleep. It
then renders through `claims.write_claims`, and each commit carries only its own pages (`commit_paths`, never
`git add -A`).

**Only `progress.py` writes an event predicate.** `agentic_write.write_claim` refuses `happened` and `milestone`
with a one-line reply naming `cicada_note_progress`, and `claim_pipeline` relabels a Stage-1 relationship whose
label normalizes to either as `relates-to` (counted, no text). Without this, `cicada_write_claim(subject,
"happened", …)` or a model's "milestone" label would write an event with no `status` and no born-closed rule.

**Ids** use one new dated form for events: `clm_<subject>_<predicate>_<sha1(subject, predicate, object)[:8]>_<valid_from>`,
and for a milestone the slug replaces the hash: `clm_<subject>_milestone_<slug>_<valid_from>`.
The same words on two days give two done claims. This also sidesteps G140's known gap (withdraw → restate reusing a
closed id) for events restated on another day. The same-day case (a milestone created and marked done on one
day) mints a `-2` suffix.

**Dedup: `claim_reconciler.reconcile_events`,** called by `reconcile_stage3` whenever `is_event` is true. The
general table is untouched. Rules, in order:

1. **Span identity.** A new happening whose span overlaps an existing event claim's span on the same episode,
   **with the same `status`**, reinforces that claim; it never adds one. When it overlaps several, the largest
   overlap wins, and one existing claim absorbs at most one incoming claim per write. Reinforce merges sessions
   and evidence (`_reinforce`) and never moves `valid_from`.
   - *Why:* a G104 Stop-hook rewrite flips `processed: false`, Sleep re-reads the whole session, and a
     non-deterministic model rewords the same happening. An agent's live write and that night's Sleep cite the
     same span and fold into one.
   - *Why the status test:* the owner's one sentence yields a done and an ongoing happening (R-PJ19). A
     re-extraction that quotes the whole sentence for both must not fold the ongoing one into the done one.
2. **Exact date plus text.** The same `(subject, predicate, valid_from, object)` reinforces.
   - **An ongoing restatement reinforces whatever its date.** An incoming `ongoing` whose `object` equals an
     open `ongoing` claim's on the same subject reinforces it: `recorded_at` moves to the new day and the new
     evidence is added. "Still connecting" on Thursday is the same thread as Monday's, never a second open one.
3. **Milestone slots.** The slot is `(subject, milestone, object)`, across observers (R-PJ4).
   - An equal-date tie is broken by lifecycle rank (`planned` < `done`/`missed`/`dropped`), not by
     `trust_decision`'s date test. That test would turn a same-day human "create, then mark done" into a
     `CONFLICT_NUDGE` (`claim_reconciler.py:214-217`).
   - Trust still holds. An agent cannot close a human's milestone: that case becomes `COEXIST_FLAG` plus a
     divergence item ("Keep my statement / Update to done"), which is a G113 verdict for free.
4. **`settles`.** A done or dropped happening that names an open ongoing claim closes it via `_close` (it gets
   `valid_to` and `superseded_by`). Agents pass `settles` explicitly, and Sleep uses R-PJ19's rule.

**Last referenced.** The subject and every participant with a page get `last_referenced = max(existing, valid_from)`.

**Surface check.** Every `participants[].surface` must occur in `text`. If one does not, the writer drops the
`surface` so the participant renders as a chip only. It never rewrites the sentence.

**`when.resolve(when_text, anchor_instant, tz) -> (date | None, basis)`** is pure and engine-free.
- **The anchor.** `evidence.turn_at(body, span.start, turn_stamps(fm))` gives the turn's `ts`, and the basis is
  `turn`. Without it, the episode `timestamp` is used and the basis is `episode`. With no evidence at all (an
  agent write that cites nothing), the anchor is the write instant and the basis is `written`.
- **The zone** is `handshake.local_timezone()`, read per run and never stored. Travel is a disclosed error:
  the Mac's zone is the owner's best-known zone.
- **A closed table:** today, tonight, this morning, this afternoon, this evening, earlier today, yesterday, last
  night, tomorrow, N days ago, a week ago, last `<weekday>`, on `<weekday>` (past for done, next for planned),
  last week and next week (anchor ∓ 7). Absolute forms are ISO, "Oct 5" and "5 October". A missing year
  resolves to the nearest date in the status's direction.
- **Anything else** means the anchor day with the anchor's basis (`turn`, `episode` or `written`). It never
  guesses.
- **The window.** A done or ongoing date must lie in [anchor − 365 d, anchor], and a target in
  [anchor, anchor + 2 y]. Otherwise it is null.

### 5.2 Agents via MCP (PJ-3; $0)

`cicada_note_progress` is a write, in scope `record`, both locally and remotely (`api/remote/catalog.py`:
`TOOL_SCOPE` and `WRITE_TOOLS`, R-PJ23). It is declared in `mcp/server.py` and `api/remote/tools.py`,
dispatched in `mcp_tools` and `api/remote/runtime.py`, and lands in one commit.

```json
{
  "name": "cicada_note_progress",
  "description": "Record something that happened in one of the person's projects, something under way, or a milestone they planned — dated, with who and what took part. Quote the person's words in evidence. For a standing fact (a spec, who works where) use cicada_write_claim instead.",
  "inputSchema": {"type": "object", "required": ["project", "kind", "summary", "status"], "properties": {
    "project":   {"type": "string", "description": "The project page (id or name). Use the person's own page for something outside any project."},
    "kind":      {"type": "string", "enum": ["happened", "milestone"]},
    "summary":   {"type": "string", "description": "One sentence, third person, naming each participant exactly as the person did. No relative time words."},
    "status":    {"type": "string", "enum": ["ongoing", "done", "dropped", "planned", "missed"]},
    "when":      {"type": "string", "description": "Optional: YYYY-MM-DD, or the person's own words ('yesterday'), resolved against the cited episode."},
    "target":    {"type": "string", "description": "Milestone only: the planned date, YYYY-MM-DD."},
    "milestone": {"type": "string", "description": "Milestone only: an existing milestone's name or slug, to move it or mark it done."},
    "settles":   {"type": "string", "description": "Optional: the claim id of an ongoing item this finishes or stops."},
    "participants": {"type": "array", "items": {"type": "object", "required": ["name", "role"], "properties": {
        "name": {"type": "string"},
        "role": {"type": "string", "enum": ["owner", "from", "with", "for", "about", "used", "document", "project"]},
        "url":  {"type": "string"}}}},
    "evidence":  {"type": "array", "items": {"type": "object", "required": ["episode", "quote"], "properties": {
        "episode": {"type": "string"}, "quote": {"type": "string"}}}}
  }}
}
```

- **Observer and origin.** The observer is `agent`, never the owner, and a remote write is never the owner
  either. The origin is `mcp` or `remote:<id>`. The commit carries `Cicada-Author: <harness>` and the trigger
  `mcp/<harness>` or `remote/<harness>`.
- **Refusals**, each a one-line reply:
  - a `(kind, status)` pair outside `EVENT_STATUSES`;
  - a future `when` on `happened`;
  - a relative word in `summary`.
- **A project that does not resolve** gets the existing ambiguous-subject reply. The tool **never creates a
  page**. A page that resolves but is neither a `project` nor the owner's page is refused in one line naming
  its type ("Lab Cluster Example is a tool; name the project it belongs to"), so R-PJ10's homes hold for agents.
- **No evidence** is allowed (R-PJ8): the span is `reasoning` and the date basis is `written` unless `when`
  names a date.
- **Stdio races.** A stdio call checks `_backend_sleep_running` and leaves the page dirty rather than race a
  cycle, the G135 behaviour.
- **The reply echoes** the resolution, for example "filed on Pick And Place Demo, dated 2026-09-22 from
  'yesterday'", so the agent can correct it.
- **Withdrawal** is the existing `cicada_retract_claim`, which calls `progress.withdraw` for an event claim.

### 5.3 The person in the app (PJ-3 server, PJ-5 UI; $0)

These live in a new router, `api/routers/projects.py`. Every write is committed like this:
- author and trigger: `Cicada-Author: user`, `user/companion_app`;
- claim fields: `observer = owner_identity.resolve_observer`, `source_trust: user_stated`,
  `origin: companion_app`, so `is_human` protects every one of them once `companion_app` is in
  `_HUMAN_ORIGINS` (R-PJ18; it is not today);
- commits: `commit_paths` over its own pages;
- timing: **409 while a Sleep cycle runs**, with the copy "Sleep is writing this project, try again in a
  moment" (the `enrich-links` precedent).

| action | endpoint | effect |
|---|---|---|
| Add a milestone | `POST /projects/{id}/milestones {name, target?}` | A new slot. The slug is `sanitize_id(name)`, with `-2` on a collision. `date_basis: person`. |
| Move, rename, mark done/missed/dropped | `PATCH /projects/{id}/milestones/{slug} {target?, status?, on?, name?}` | `advance`. A rename changes `text` in place and is the one in-place edit, allowed for the person only (git keeps the history). Touching a read-compat `due` writes the first `milestone` claim and closes the `due`. |
| Log something | `POST /projects/{id}/happenings {text, status: done\|ongoing, when?}` | A companion episode holding the person's words exactly (R-PJ18), then `record_happening` citing it as a `user` span. A leading or trailing time phrase from `when.py`'s closed table ("yesterday", "on Tuesday") dates the claim (basis `stated`) and is cut from the claim's `text` only; the episode keeps it. Otherwise the date chip (or today) dates it, basis `person`. Participants are linked by exact name or alias only. |
| Settle a thread | `POST /projects/{id}/threads/{claimId} {status: done\|ongoing\|dropped, on?}` | Done or dropped writes a born-closed successor that `settles` the thread. "Still going" reinforces the thread in place (`recorded_at` = the day, §5.1 rule 2): no second open claim, and the quiet clock resets. |
| Not right | `POST /projects/{id}/withdraw {claimId}` | `progress.withdraw`. On an agent- or Sleep-authored claim it emits a G113 `resolution` with `kind: happening`, `verdict: overruled`. |

`on` defaults to today in the app's zone, may be backdated, and is never in the future.

### 5.4 Sleep, Stage-1 extraction (PJ-7; 💸; gated on M1–M3)

The work is folded into the existing call. A separate pass would double Stage-1 calls.

- **The anchor header,** about 60 tokens. `_get_unprocessed_episodes` also carries `turns`, and
  `_extract_chunk`'s user message gets one line:
  `Conversation date: Wednesday 2026-09-23. Known projects: Rover Arm Project (the rover arm); Pick And Place Demo; Garden Sensor Project.`
  The project list is `_state.md`'s top 7 names and aliases, so the model files happenings under consistent
  homes. The date exists only for `target` years. Python decides every date.
- **The prompt delta,** about 450 tokens, appended to `EXTRACTION_SYSTEM_PROMPT`:

```
HAPPENINGS (optional): things THE USER did, received, started, finished or planned in a project —
"got the guide from Hana", "started calibrating the camera", "arm assembled", "demo by Oct 5".
- One per occurrence. summary: one plain sentence, third person, naming the user as {owner} and each
  participant exactly as written; never a pronoun for the user; no time words. when_text: the words that say
  when ("yesterday", "last Tuesday", "on Oct 5") or null — copy them, do not compute a date. status: done |
  ongoing | planned. target: for planned only, the date words as written, or null. project: the project or
  goal it belongs to, from the Known projects when it is one of them, as named otherwise, or null.
  participants: [{name, role}], role one of owner|from|with|for|about|used|document|project; the user is
  always role owner. urls: any link or file named. evidence_quote: the user's own words, verbatim,
  ≤ 240 chars — REQUIRED; a happening without one is discarded.
- Skip routine assistant work (reading files, running commands, fixing lint), small talk, and anything the
  user did not do, receive, decide or plan. At most 3 per transcript chunk.
- A happening is NOT an entity and NOT a relationship: never duplicate it as either.
```

- **The schema delta.** `engine_schemas.extraction_schema` declares `happenings` in both dialects. In strict
  mode every key is required, with nullable `when_text`, `target`, `project` and `evidence_quote`, and enums
  for `status` and `role`.
  - `test_engine_schemas.py:56` fails **on purpose**. The strict shape must be re-verified live on the ChatGPT
    plan (`codex exec`) before merge, or codex silently returns no happenings.
  - `claude -p`, litellm and ollama carry the change through the prompt alone.
- **The rails,** in Python beside `attach_relationship_evidence`. The schema is only a first filter. Each drop
  is counted by reason, with no text.

| reason | rule |
|---|---|
| `no_quote` | The quote does not locate with `evidence.verify` inside the chunk window (R-PJ8). |
| `assistant_only` | The span kind is `assistant`. `user`, `speaker` and a folder's `evidence_kind: user` pass. |
| `not_owner` | There is no `owner` participant (v1). |
| `denylist` | A closed verb list over the summary (`read`, `ran`, `opened`, `listed`, `fixed lint`, `searched`, …), in the `promote_targets._COMMON_WORDS` style. |
| `undated_plan` | `planned` with no resolvable target. That is G13's capture, not a milestone. |
| `no_home` | R-PJ10. |
| `bad_date` | Outside the window. |
| `cap` | More than 3 per chunk or 6 per episode, highest confidence first. |

- **Participants** map through Stage 2's `name_to_id`, then an exact case-folded alias match over the
  `bank_index` frontmatter. The owner maps through `owner_identity`, never by fuzzy name. A URL links to a
  `media` page only when one exists for its `url_hash`. Otherwise it stays on the participant, and the app
  offers "Save to memory" (the save-url path, user-triggered). Extraction never mints a media page (G17).
- **Planned → milestone.** A planned item with a target becomes a `milestone` claim, trusted as agent. The slug
  is `sanitize_id(summary)` and dedups against existing slots by normalized name.
- **Writes** go through `claim_pipeline` into `reconcile_events`, with manifest lines
  `trigger: sleep/extraction` in the main commit under the Stage-1 model's `Cicada-Author:`.
- **The switch** is Settings → Memory, "Track what happens in projects" (`sleep_extract_happenings`, on by
  default once PJ-7 ships). Turning it off drops the prompt block. No price is shown anywhere.
- **Telemetry** is a new non-spend kind, `happenings`: `{kept, dropped: {reason: n}}`, ids and enums only. It
  joins `NON_SPEND_KINDS`, so it never shows as a connection.

### 5.5 Consented per-project re-read (PJ-8; 💸, user-triggered only)

- **The trigger** is "Read this project's past conversations" in the project's `…` menu.
- **Scope.** It re-reads only the tree's `source_episodes` plus episodes whose FTS passages match the project's
  name or aliases, capped at 50. It uses a happenings-only prompt (about 1/3 of Stage 1's) behind the same
  rails.
- **The consent sheet** states counts only: the number of conversations and calls, and the engine it will use,
  as Consolidate's subtitle names it. No price, no tokens.
- **Plans and ruling 4.** It runs as `user_triggered=True`, so a plan engine is allowed, and it is **never
  scheduled**.
- **Idempotent.** Span identity makes a second run a no-op.
- **The commit** is `Backfill <project> <date>`, with trigger `user/backfill`, `Cicada-Author: <model>` and
  `Cicada-Engine: <engine>`, as one revertable commit. It is refused with 409 while Sleep runs.

---

## 6. Read model: `api/services/project_timeline.py`

This module is pure, engine-free and thread-pool safe, like `provenance.entity_provenance`.
`build(memory_path, project_id, *, tz_name, since=None) -> ProjectTimeline` and
`list_projects(memory_path, *, tz_name) -> list[ProjectRow]`. The router passes the active bank's path and
the machine zone. The module writes nothing and imports no engine. A test asserts that `git status
--porcelain` is empty and page mtimes are unchanged after both GETs, with every LLM provider monkeypatched to
raise.

### 6.1 The tree and its layers

1. **Tree.** The project plus pages with a `part-of <tree member>` claim, current or closed, to depth 2.
2. **Event claims (PJ-3+),** from:
   - the tree's pages;
   - owner-page event claims whose participants name a tree page by id, or by a name or alias (the read-time
     relink).
3. **Derived moments (the $0 underlay).**
   - **Candidates:** claims on tree pages; claims that touch a tree page from a member or the owner page; and
     member-page claims inside the tree's live window (labelled `via: <member>`, commons excluded). Records
     and `dropped` pages are never used.
   - **The anchor:** the earliest evidence episode, else `source_episodes[0]`, else `valid_from` alone. That
     gives an instant with basis `turn`, `episode` or `day`.
   - **A moment** = the claims sharing (anchor episode, local day in the machine zone). Later evidence on the
     same claim reinforces it. It feeds "last heard" and never makes a new moment.
   - **The lead:** a `user` span first, then a subject that is the owner or a tree page, then the widest span.
     The lead's span is the quote. A legacy claim with no evidence gets a **derived** quote from
     `inbox_context.locate_mention`, labelled `derived` and never written.
   - **State** (R-PJ14): `said`; `changed` (superseded, rendered "was X → now Y" from the chain); or `ended`
     (closed at its stated end).
   - **The facts list** shows at most 3 facts, then "+N facts". This keeps a long coding session from becoming
     a grab-bag.
   - **Suppression:** a moment is dropped when an event claim cites its episode.
4. **Milestones:**
   - `milestone` slots, with the whole chain for "moved";
   - project-subject `due` claims (read-compat);
   - `expected_end` claims, drawn as a "stated end" tick.
5. **Legacy `## History` bullets** (`_history_sort_key` grammar). These rows are grey, with no chip, and sit
   below every claim row of the same day. A date outside [`created` − 1 y, today + 2 y] reads as undated.
6. **Activity density:** per local day, the count of conversations touching the tree. It comes from the tree's
   claims' `session_ids` and `source_episodes`, grouped as `/entities/{id}/provenance` groups conversations,
   with **no `git log`** (that endpoint's contributor half shells out per page, which the §6.6 budget cannot
   afford across a tree). Counts only.
7. **Pending:** unprocessed episodes whose FTS passages match a tree name or alias, with no model. Shown as "1
   conversation from today is waiting for Sleep", so "me today" is honest about what is not in the timeline
   yet.
8. **Created:** the project page's `created` date, labelled "Cicada started tracking this", never "the project
   started".

### 6.2 Derived state: one function, two languages

`timeline_state(items, today) -> State` is pure and lives in Python (`project_timeline.py`, for
`cicada_project`) and in Swift (`ProjectState.swift`). Both run one shared JSON fixture
(`api/tests/fixtures/timeline_state.json`), the `QuickMatch`/`text_fold` precedent. It outputs:

- **The milestone state,** from the slot head:

| state | rule |
|---|---|
| `upcoming` | planned, target ≥ today |
| `overdue` | planned, target < today |
| `someday` | planned, no target |
| `done` | done; `valid_from` against `target` gives early / on time / late by N days |
| `missed` | stated by a person only |
| `dropped` | dropped |
| `passed-no-word` | a read-compat `due` closed by expiry |
| `moved` | a flag, set when the chain holds an earlier target |

- **Q:** R-PJ13's quiet threshold, for the project.
- **Per open thread:** `quietDays` = today − last heard, where last heard = max(`valid_from`, `recorded_at`, the
  reinforce episodes, `session_ids`' episodes). `recorded_at` is what a "Still going" with no episode moves
  (§5.3). Plus `followupEligible`.
- **The list section:** In motion (last moment ≤ Q ago) · Quiet (≤ 90 days) · Resting (> 90 days, or the page
  is `decaying`/`archived`). `dropped` pages are never listed.
- **Progress:** `{done, total}` (R-PJ11). A `passed-no-word` milestone counts in `total` and never in `done`:
  nobody said it happened.

### 6.3 "Me today"

The Now block is at most three sentence rungs, in this order. A missing fact omits its rung and never shows a
guess (the Sleep page's `SentenceLine` rule).
1. **Now:** the newest open `ongoing` happening in the tree. "Today · Bob (you) is connecting to Lab Cluster
   Example to run the Pick And Place Demo."
2. **Next:** the open `planned` milestone with the earliest target (undated ones last), which is the upcoming
   or overdue one without reading today. "Next · First grasp, Oct 1 — in 8 days · moved once."
3. **Last:** the newest done happening, or on day one the newest moment. "Yesterday · Bob (you) got the lab
   cluster onboarding guide ↗ from Hana Example."

Under the rungs sit the **pending** line and a **quiet** line ("Calibrating the gripper camera · quiet 24
days").

**Planned vs unplanned.** A project is *planned* when its tree holds any milestone, project `due` or
`expected_end`, open or closed. Otherwise it is *unplanned*. Both are first-class. An unplanned project is never
nagged to add a plan (§11.3 draws both).

### 6.4 The knowledge cluster ("Around this project")

**Members** are the union of:
- linked participants of the tree's event claims, weighted by count and recency, each carrying its most
  frequent role ("gave you the guide", "used", "with");
- current graph neighbours: open node claims with a tree page as subject, plus reverse claims, which come from
  a new `search_index.claims_about(object_id)` over the stored claim payload (`search_index.py:397-408`),
  falling back to `provenance._candidate_pages`'s raw prefilter while the index builds;
- `part-of` children;
- **pending names:** unlinked participant surfaces, shown greyed as "mentioned once, not a page yet". This makes
  the promotion rule visible instead of hiding it.

**Rules:**
- The owner is excluded: he is "You", not a member.
- The commons guard applies (R-PJ20).
- Each group holds at most 8 members; the rest are counted.

**Groups**, from the member's type in the closed set of 10:

| group | types |
|---|---|
| People | `person` |
| Tools & infrastructure | `tool`, `directory` |
| Documents | `media`, including papers |
| Ideas | `concept`, `skill` |
| Sub-projects | `project` in the tree |
| Places & organisations | `location`, `company` |

**One fact per member, chosen by rule,** never by a model:
- a tool: up to 3 of its open literal claims, which is how "4 GPU nodes · Slurm-example scheduler ·
  login.example.com" appears on hover;
- a person: `works-at`;
- a media item: its site;
- a paper: its venue and year.

### 6.5 The list

`list_projects` reads only each project page plus `bank_index` frontmatter: one parse per project and no member
scan. It emits absolute data only. The client runs `timeline_state` over it.

### 6.6 Budgets

The detail's p95 is **≤ 150 ms warm** on a 2,500-page synthetic bank, and the list's is **≤ 80 ms**. There is
a per-request memo and ETag 304s. The route answers from `bank_index` and the FTS claim table first. Raw scans
are capped at 200 pages; hitting the cap sets `partial: true`.

---

## 7. Provenance

- **Every row has a way back to its source.** A happening, milestone or moment carries a G118 span, a derived
  span, or the honest line "From the page's history — no source sentence" (the G115 `[ no source recorded ]`
  voice, at meta weight, DR-55).
- **Chips** are the existing `EvidenceChip` (DR-57): "You said", "<agent> replied", "From the page", "Inferred"
  and "Mentioned here". There is one new label, "Set by you in Cicada", derived from `origin: companion_app`
  together with `reasoning` evidence. DR-57 names exactly five labels and carries a `[test]`, so PJ-5 adds the
  sixth to DR-57 and its test in the same PR.
- **A click** calls `ProvenanceRouter.open` (`:122`). The Reader opens as the third progressive column, with the
  span washed.
- **The date is provenance too.** For `date_basis: stated`, the Reader header adds "dated from 'Yesterday'
  (sent 2026-09-23 18:04)", computed from `evidence.turn_at` at read. For `episode` it says "around Sep 23". For
  `person` it says "Set by you". For `written` it says "dated when it was recorded".
- **Resume** appears when the conversation is resumable: the G124 descriptor, `POST /conversations/{id}/resume`,
  which calls `isfile()` only. The timeline payload's `resumable` is computed per request but rides an ETag
  that does not see transcripts, so a 304 can carry a stale `true`; the click's `POST …/resume` re-validates
  and a gone transcript reads "This conversation can no longer be resumed", never an error.
- **Prev and next** in the Reader walk every span that fed a thread: the original plus the reinforce evidence.
- **Episode citations** (`GET /episodes/{id}/citations`) list event claims, because they are not records. From a
  conversation you see "Logged on Pick And Place Demo · <sentence>" (the G106 direction).
- **"Where this came from"** at the foot of the project detail is the unchanged `WhereThisCameFromSection` over
  `/entities/{id}/provenance`.
- **Telemetry.** Opening a project records `read` with `surface: project` (`telemetry.record_read`). Ids only.

---

## 8. Relative dates at read

- **The server** stores and serves `YYYY-MM-DD` days and UTC instants. It serves `tzName` (the machine zone
  used for day bucketing) once per payload.
- **The app:** one pure function, `RelativeDay.phrase(day:now:calendar:)`, gives Today · Yesterday · a weekday
  within 6 days · "Sep 9" · "Sep 9, 2025". The Store's day-change notification re-derives every visible state
  with no network. A lint rejects a "Yesterday" or "Today" string literal outside that function (DR-58).
- **`cicada_project`** formats for each call in its `tz` argument, falling back to the machine zone, and prints
  both forms.
- **The handshake and `_state.md`** hold absolute dates only.

---

## 9. Follow-ups and rewards (G4, G113)

**The writer.** `followups.propose(memory_path, today)` runs in Sleep's engine-free tail, in the
clean-tree-guarded slot **immediately after** `_expire_claims_safely` and **before** `_poll_connectors_safely`
(`sleep_cycle.py:866-873`), so the night's expiries are visible and no poll's `git add -A` can sweep its files.
- It needs no engine, so it runs on idle nights and on scheduled cycles under ruling 4 without touching a plan.
- It commits alone through `commit_paths`: `Follow-ups <date>`, `Cicada-Author: cicada`, trigger
  `sleep/followup` (a new trigger, added to CLAUDE.md and `_infer_change_type`). Like expiry it skips pages
  already dirty before it ran, and a failed commit removes the inbox files it wrote.
- **What is written and what is derived.** It writes one inbox file per item: `kind: followup`, `entity_id`,
  `predicate`, `claim_id`. The question, its options and its age are synthesised at read (below), like decay's.

**Who gets asked:**
- an open `ongoing` happening on an `active` project, quiet for at least `max(21, Q)` days;
- a planned milestone overdue by at least 3 days;
- a project-subject read-compat `due` that expiry closed in the last 14 days ("passed, no word"), asked once.

**Rate limits** (UX principle 4, non-intrusive):
- at most one open follow-up per project;
- at most 3 open across the bank;
- a "Remind me later" is never re-asked within 30 days. Today `remind_later` is a 7-day defer routed for
  `decay` only (`inbox_service.py:737`), and DR-68's copy says "ask again in 7 days". So the defer length
  becomes per kind (30 for `followup`), and the followup card's copy reads "Not now — ask again in 30 days".

**Dedup** uses the key `(entity_id, predicate, claim_id)`, the inbox's merge rule.

**The question** is a G60 object, synthesised at read like decay, in `inbox_questions.followup_question`, with
its cause resolved through `inbox_context`'s claim tier (G115).

| item | question | options |
|---|---|---|
| quiet thread | "You were connecting to Lab Cluster Example to run the demo — 24 days ago. How did it go?" | **Done** (today) · **Still going** · **Stopped** · **That didn't happen** · Other… (another day, or in your words) · Remind me later |
| overdue milestone | "First grasp was planned for Oct 1. Did it happen?" | **Done** (today) · **Missed** · **Dropped** · Other… ("done Oct 3", "move it to Oct 20") · Remind me later |
| passed `due` | "The arm was due Aug 12. Did it happen?" | **Done** (on its date) · **Missed** · **It never mattered** (writes `dropped`) · Other… ("done Aug 9") · Remind me later |

- **Dates without a date picker.** The Inbox has no date input today. Every one-tap option dates itself on the
  day it is answered. Another day goes through Other…, whose text `when.resolve` reads against the answer's
  instant ("done last Friday", "move it to Oct 12"); an unresolvable date is refused in one line. So every
  question sets `allow_other: true`, and a date picker on the option is a later refinement, not PJ-6.
- Free text becomes a person-stated done or ongoing happening citing a companion episode. "We solved it by
  doing X" is G4's problem-log line, landing where it belongs.
- **Every resolution goes through `progress.advance` or `withdraw`,** the same code as the app buttons.

**Verdicts (G113),** ids and enums only:
- **On an extractor- or agent-authored claim:**
  - Done or Still going → `agreed` (the "ongoing" was right);
  - That didn't happen → `overruled`;
  - Stopped, Missed or Moved → `neutral`.
- **On a person-authored claim, or a read-compat `due`:** always `neutral`, because nothing is graded.
- The event is `resolution` with `kind: followup` and refs `claim_id`, `predicate`, `authored_by`,
  `date_basis`, `verdict`.
- The kept rate per `authored_by` becomes a number in `GET /consumption/feedback`. Nothing is auto-applied
  (G78).

**Ship-together.** `InboxKind.followup`, the loader, the resolver and the Swift decoder land in **one commit**.
G113 found that a kind the model lacks is silently dropped by `load_inbox`.

**Agents** get follow-ups through `cicada_check_nudges(entity_ids=…)` when a conversation touches the project.
The contract's rules hold: one question per turn, and a resolve only with the person's own answer.

---

## 10. API, MCP, handshake

### 10.1 HTTP

**`GET /projects`** returns `{projects: [ProjectRow], tzName}`. Here is one `ProjectRow` from the demo, at
T = 2026-09-23:

```json
{"id": "rover-arm-project", "name": "Rover Arm Project", "oneLiner": "A small arm that picks parts off a tray.",
 "parent": null, "children": ["pick-and-place-demo"], "status": "active", "created": "2026-07-15",
 "planned": true, "lastMomentDay": "2026-09-23", "medianGapDays": 10,
 "openThreads": [{"claimId": "clm_pick-and-place-demo_happened_9b07d311_2026-09-23", "text": "Bob is connecting to Lab Cluster Example to run the Pick And Place Demo", "since": "2026-09-23", "lastHeard": "2026-09-23"},
                 {"claimId": "clm_rover-arm-project_happened_c2e915aa_2026-08-30", "text": "Bob started calibrating the gripper camera", "since": "2026-08-30", "lastHeard": "2026-08-30"}],
 "milestones": [{"slug": "first-grasp", "name": "First grasp", "target": "2026-10-01", "status": "planned", "moved": true},
                {"slug": "due-2026-10-05", "name": "Pick And Place Demo", "target": "2026-10-05", "status": "planned", "source": "due", "on": "pick-and-place-demo"},
                {"slug": "due-2026-11-02", "name": "Lab showcase", "target": "2026-11-02", "status": "planned", "source": "due"}],
 "progress": {"done": 1, "total": 4},
 "activity": [{"day": "2026-09-22", "n": 1}, {"day": "2026-09-23", "n": 2}],
 "followups": 1}
```

- `activity` covers the 120 days ending at `lastMomentDay`, never "the last 120 days": the ETag does not move
  at midnight (R-PJ7), so the window is anchored to data and the client trims it to its own today.
- A read-compat `due` gets the slug `due-<date>` and the name from its text (R-PJ4), which is why the demo
  row's child `due` reads "Pick And Place Demo".
- `milestones` holds at most 5, open ones first.
- `openThreads` holds at most 3.
- Everything is absolute. The client derives "Moving", "Quiet 24 d", "in 8 days" and "overdue".

**`GET /projects/{id}/timeline?since=`** returns:

```
{project, tzName, window: {start, end}, now: {threads[], next?, last?}, pending: {unconsolidated},
 milestones: [{slug, name, chain: [ClaimModel], source: milestone|due|expectedEnd, on}],
 items: [Happening(ClaimModel + participants resolved) | Moment | HistoryRow | CreatedTick],
 activity: [{day, n}], cluster: {groups: [{label, members: [{id, type, name, rolePhrase, fact, lastSeen, count, pending}]}], alsoUses: []},
 conversations: [ConversationRow], partial}
```

- `window.end` = the later of the last activity day and the last target. The client adds today and pads.
- A 404 means there is no page, or the page's type is not `project`. The id is resolved with
  `resolve_entity_file`.

**Writes** are listed in §5.3.

**ETags:**

```
GET /projects                  etag_for(mp, "entities", "episodes", "inbox", extra=f"projects|{PROJECT_SHAPE}|{tz_name}")
GET /projects/{id}/timeline    etag_for(mp, "entities", "episodes", "inbox", extra=f"project|{stem}|{since}|{PROJECT_SHAPE}|{tz_name}")
```

- Both answer `If-None-Match` with a 304.
- Neither is a Store domain (R-PJ7). The app's `ProjectsCache` revalidates when the Projects page is visible and
  a sync `version` event names `entities`, `episodes` or `inbox`. A 304 costs nothing.
- `GraphNode` gains `created` and `lastReferenced`, and `graph.NODE_SHAPE` becomes
  `"aliases+f1-facets+dates"`, which gives the list its cold first paint.
- `ClaimModel` gains its fields (§4.1).

### 10.2 MCP

**`cicada_project`** is a read, in scope `read`. It is declared in `mcp/server.py` and `api/remote/tools.py`,
dispatched in `mcp_tools.project(...)` and `api/remote/runtime.py`, and lands in one commit.

```json
{"name": "cicada_project",
 "description": "Where one of the person's projects stands: what is under way, what is next, what went quiet, what happened (dated, from whose words), and the people, tools, documents and sub-projects around it. Read-only. Use when the person asks how a project is going, what happened on it, or what's next.",
 "inputSchema": {"type": "object", "required": ["project"], "properties": {
   "project": {"type": "string", "description": "A project's id or name."},
   "since":   {"type": "string", "description": "Optional: YYYY-MM-DD, or a number of days back. Default 90."},
   "tz":      {"type": "string", "description": "Optional: the person's IANA timezone, for relative dates."}}}}
```

Its output for the demo scenario (PJ-3 or later; quotes shown only locally, or with the `sources` scope):

```
Rover Arm Project — planned · 1 of 4 milestones done · last activity today (2026-09-23)
Now: Bob is connecting to Lab Cluster Example to run the Pick And Place Demo — since today (2026-09-23) [on Pick And Place Demo; clm_pick-and-place-demo_happened_9b07d311_2026-09-23]
Next: First grasp — 2026-10-01, in 8 days (moved from 2026-09-09) · Pick And Place Demo — 2026-10-05 · Lab showcase — 2026-11-02
Quiet: Bob started calibrating the gripper camera — quiet 24 days (last 2026-08-30); asked in Inbox [clm_rover-arm-project_happened_c2e915aa_2026-08-30]
Waiting for Sleep: 1 conversation from today
Happened (newest first):
- yesterday (2026-09-22) · done · Bob got the lab cluster onboarding guide from Hana Example; it walks through connecting to Lab Cluster Example <https://example.com/guides/lab-cluster-onboarding.pdf> · "Yesterday Hana Example sent me the lab cluster onboarding guide (…)" [clm_…, ep_2026-09-23_003]
- 2026-08-09 · done · The arm is fully assembled (milestone "Arm assembled", 3 days early)
…
Around it: People — Hana Example · Tools & infrastructure — Lab Cluster Example (4 GPU nodes · Slurm-example scheduler · login.example.com) · Documents — Lab Cluster Onboarding Guide · Sub-projects — Pick And Place Demo · Not a page yet — (none)
Open a page with cicada_recall_detail(entity_id); record progress with cicada_note_progress (settles=<claim id> to finish a thread above).
```

The Now and Quiet lines print the thread's claim id because `cicada_note_progress`'s `settles` needs it, and
this output is the only place an agent can learn it. The last line names `cicada_recall_detail`'s real argument,
`entity_id` (R12 holds for tool output as for the primer), and its second clause appears only when
`cicada_note_progress` is in the connection's tool set. **`cicada_note_progress`** is specified in §5.2.

**The readers that learn `is_event`** (in PJ-3, all listed in the grep-gate test):
- `mcp_tools._recent_changes` and `_history_line` exclude events.
- Recall renders an event as `D · status · text`, never as `happened: <sentence>`.
- `claim_subject_hits` admits events.
- `get_perspective(history=true)` lists events under "Happened", never as "was X until D".
- `routers/claims.py`'s contested-keys list excludes milestone slots.
- `inbox_questions` conflict generation skips events. They are multi-valued or slot-keyed, so this is
  belt-and-braces.
- `EntityDetailCard`'s Timeline tab (contested keys, `:1306-1330`) skips milestone slots.
- `provenance.episode_citations` and `search_service`'s claim ranking render an event as a dated happening,
  never as superseded history (R-PJ3); the app's citation and palette rows follow in PJ-5.
- `agentic_write.write_claim` and `claim_pipeline` refuse or relabel event predicates (§5.1).

### 10.3 Handshake and `_state.md` (G53, G75)

- **`_state.md` schema v3.** Each of the top 7 project rows gains:
  - `now: {claim, text ≤ 80, since}` (the newest open `ongoing` happening);
  - `next: {slug, name, target}` (the open `planned` milestone with the earliest target, §6.3).
- **No quiet count.** A count "as of the write" depends on today while `inputs_version` does not, so the file
  would go stale without a write, the class `sleep.next_at` was removed for (CLAUDE.md, G53). "Quiet" is
  derived per request by `cicada_project` and the app. Both fields above are pure functions of the claims.
- The file stays absolute and deterministic. `inputs_version` already covers `entities`, and folding the schema
  in rebuilds it once, as one `State snapshot` commit. The ≤ 6 KB cap is measured with 7 projects that all
  have `now`.
- **In PJ-2, before PJ-3,** no bank holds an `ongoing` claim, so `now` is always absent and `next` comes from
  read-compat `due` claims only. The slice still ships whole; `now` fills in once PJ-3 lands.
- **The primer's Current section** renders one line per project, absolute only, so the cache key is unchanged:
  `- Rover Arm Project — now: connecting to Lab Cluster Example (since 2026-09-23) · next: First grasp, 2026-10-01`.
  The slim path drops `now:` before it drops a project. The ≤ 1,800-token budget is re-asserted.
- **Contract sentences, each landing only in the slice where its tool exists (R12):**
  - PJ-2: "Ask where a project stands with `cicada_project(project)`." Locally it joins item 1 of the fixed
    `_CONTRACT` (`handshake.py:191`); remotely `_remote_contract(tools)` (`:89`) adds it only when
    `cicada_project` is in the connection's tool set.
  - PJ-3: "When the person says what they did, got, started or finished in a project, record it with
    `cicada_note_progress(project, kind, summary, status, evidence)`." Locally it joins item 3 of `_CONTRACT`;
    remotely it appears only when `cicada_note_progress` is in the tool set. Every argument it names is in
    the §5.2 schema.
- **The remote Current line** follows R-PJ23: a `now:` whose claim is the person's own Log text shows as
  "a note of yours" without the `sources` scope.
- The existing test that holds R12 for every argument either primer names, across every remote scope set,
  covers both.
- **The live twin** of the new `_state.md` fields is `GET /projects`, which satisfies "a reader that finds
  `_state.md` stale must still work".

---

## 11. The app (PJ-5)

This is the owner's chosen grammar, Direction D (`docs/design/DESIGN_RULES.md`, binding from 2026-09-23):
- an icon rail;
- a centred command bar that holds the one bank selector and ⌘K;
- progressive columns: list → project → Reader;
- graphite neutrals with the Mac's system accent;
- cited spans washed.

Projects is the first page designed for D from the start (DESIGN_RULES §10). No painted art and no nature
tokens appear on it, because it is a data surface (DR-13).

### 11.1 Navigation

- **The rail cell** (R-PJ22, pending G108): glyph `point.topleft.down.to.point.bottomright.curvepath`, tooltip
  "Projects ⌘7". By default it is the seventh page cell, after Sources, so its place matches its number and no
  existing shortcut moves; G108 may place it elsewhere and renumber.
- `AppTab.projects` is a new raw value, so `restored(from:)` needs no mapping.
- **Entry points:**
  - `AppRouter.routeToEntity` sends `type == project` to the Projects detail, and so do ⌘K rows, graph clicks
    and wikilinks;
  - a project's entity card gains "Open project ›";
  - once Home exists (G108), it gains "In motion" after "Needs you": the top 3 rows in STATE 0 styling.

### 11.2 STATE 0: the list, alone (nothing selected)

The layout is the rail, then one column at full content width (text capped at 760 pt). Following DR-25 there
is no title band.

- **The eyebrow row** reads "Projects · 7", with text tabs and counts on the right: In motion 3 · Quiet 1 ·
  Planned 4 · All 7.
- **"All projects" band,** above the rows. One 20 pt lane per in-motion project (at most 5), sharing one axis
  that runs from 90 days ago to 30 days ahead:
  - one Today line across every lane;
  - activity density per lane;
  - each lane's next milestone as a hollow ◇.

  This is the owner's "me today" across his life, drawn from `/projects` alone with no extra request.
- **Rows** are one line, 36 pt tall (DR §5.3), left to right:
  - the type dot;
  - the name (13 regular, `textPrimary`);
  - the Now line (13, `textSecondary`, truncated): "Bob (you) is connecting to Lab Cluster Example";
  - the next item (12, `textTertiary`): "First grasp · Oct 1", or "<milestone> · overdue since Sep 9". It is
    never red (DR-7);
  - a 40 pt sparkline of 8 weeks of activity (`sparklinePath`);
  - the age of the last activity, right-aligned and tabular;
  - a neutral pending badge when a follow-up is open.
- **Sub-projects** sit indented under their parent. A quiet project reads "quiet 24 days" in its Now slot.
- ⌘F focuses the page's `CicadaSearchField` (DR-68), which filters the rows.
- **Empty state:** "Projects appear once Cicada has heard about one in two conversations." That is the
  promotion rule, stated plainly, on `EmptyStateView`.
- **Cold paint** comes from the Store's `/graph` snapshot: project nodes by `lastReferenced`, sectioned by that
  proxy until `/projects` answers. Never blank.

### 11.3 STATE 1: list + project (a row selected)

The list collapses to the triage column: 328 pt at 1440, 280 pt at 1200, with 56 pt two-line rows. The
selected row uses `bgSelected` (never the accent). The project detail takes the rest of the width, with text
capped at 720 pt. From top to bottom:

**1. Header.**
- The name (`displayFont(22)`), a "Project" `Tag`, and the breadcrumb "part of Rover Arm Project ›" for a
  sub-project.
- The one-liner.
- A `…` menu: Add milestone · Log something · Open card · Read this project's past conversations (PJ-8).

**2. Now.** The rungs from §6.3, in the Direction D sentence voice: the lead in `textPrimary` 15 and the others
in `textSecondary` 13. Each rung carries one evidence chip (DESIGN_RULES §10's entity-card rule: at most two chips, speaker and age;
the chip itself is a `Tag`, DR-44). Under
them sit the pending line and the quiet line in `textTertiary`.

**3. The timeline band.** It spans the full detail width and is **96 pt** tall. It is drawn with SwiftUI
`Canvas` and has no art. From the top:

| y (pt) | layer | encoding |
|---|---|---|
| 0–12 | labels | Only the next milestone's name, and whatever is hovered or focused (11 pt `textTertiary`). Never every label. |
| 14–28 | **milestone lane** | ◇ 9 pt diamonds at the target: **hollow** = upcoming; **hollow + "overdue" label** = planned with target < today; **filled** = done, placed at its done date, with a hairline to its target when early or late; a **dotted ghost ◇** at each earlier target, joined to the current one by a dotted hairline (moved); a **slashed ◇** = "passed, no word" (an expired `due`); a short dash = dropped. |
| 32–64 | **event lane** | **Done happening:** filled ● 6 pt. **Derived moment:** hollow ○ 6 pt ("said here", not yet narrated). **Ongoing happening:** a 4 pt capsule from `valid_from` to today, open-ended at Today; its part after "last heard" is **dashed** once the thread is quiet. **Settled ongoing:** a capsule that ends in its successor's ●. **Legacy history row:** a 4 pt grey tick. Same-day items stack up to 3, then "+n". Sub-project items share the lane and name their project on hover. |
| 66–70 | **density strip** | One cell per day: conversations touching the tree, in 3 opacity steps of `textTertiary`. Empty days are blank. |
| 72 | **axis** | A 1 pt hairline (the border token), with 4 pt month ticks. |
| 76–92 | month labels | 11 pt `textTertiary`, tabular: "Jul", "Aug", "Sep", "Oct". |
| 8–72 | **Today** | A 1 pt vertical line in `textPrimary` with a 10 pt "You, today" label at its head. A small hollow ring at its foot marks "waiting for Sleep" when `pending > 0`. |

- **The window, planned:** from min(`created`, first item) to max(last target, today), plus 10% padding on the
  right. Future targets sit to the right of Today, so the eye reads "where I am" against "where I said I'd be".
- **The window, unplanned:** from the first item to today + 7 days. The axis past Today is drawn without ticks,
  fading out: an open end. Nothing is invented to fill the right side. A quiet `NeutralButton` "+ Milestone"
  sits at that end.
  - **Progress on an unplanned project is the rhythm itself:** the density strip, the done dots and the open
    capsules. That is the truthful band for a project nobody planned.
- **A long window.** Past 18 months, everything older than 12 months compresses into one "earlier" stub at the
  left, with a break mark.
- **Interaction:**
  - Hovering an item gives a one-line popover: the sentence plus its relative date.
  - Clicking selects that row in the story below and scrolls to it (DR-30), with no animation from the keyboard
    (DR-60).
  - The band is one focus stop: ←/→ step through items, and ⏎ opens the item's source in the Reader.
  - Every item is an accessibility element whose label is its sentence plus its relative date, and "You are
    here, today, September 23" for the marker.
  - The Now block and the story are the band's text twin.

**4. Open threads.** Above the list sits the **Log field**, one line with the placeholder "Log something on this
project…":
- ⏎ saves it as done today;
- ⌘⏎ saves it as ongoing;
- a date chip changes the day.

Each thread row holds its sentence, then "since Aug 30 · quiet 24 days" in `textTertiary`, then three neutral
buttons: **Done** · **Still going** · **Stopped** (DR-40, never the accent). Each is an optimistic `Mutation`
that rolls back with a toast on 409 or failure.

**5. What happened** (the story). Newest first, under day headers derived at read: Today · Yesterday · Earlier
this week · September · August.
- **A happening row** is its sentence with every participant rendered inline as a link in `textPrimary` with a
  small type dot. The owner shows as his name with a **you** `Tag`, which is the owner's own "[user]" annotation
  made visual, and the G117 "Name (you)" convention. A document shows its site mark and ↗ to the URL, or "Save"
  when it has no media page. Hovering Lab Cluster Example shows a card with its three `spec` facts.
  - Trailing the row: the status glyph (● done, ◐ ongoing, ◌ dropped), one evidence chip and the age.
  - A roll-up row carries "· Pick And Place Demo" in `textTertiary`.
- **A moment row** (day one, derived) is the washed quote in the quote style (DR-18, SF 15), with the fact
  phrases as chips beneath, "+N facts", and `via Lab Cluster Example` when it came through a member.
- **History rows** render in meta style: "From the page's history".
- The last row is "Cicada started tracking this · Jul 15".
- There are no ids at body weight (DR-54).

**6. Plan.** Milestone rows: name, target, a state word ("in 8 days", "done 3 days early", "overdue since
Aug 12", "passed, no word"), and "moved twice ›", which opens `milestones[].chain` in `BeliefTimelineView` (the chain crosses the
`due` → `milestone` hop, which the per-key `/entities/{id}/timeline` cannot, R-PJ4). Then
"+ Add milestone".

**7. Around this project.** The §6.4 groups as compact rows: name, type dot, role phrase, one fact, "last Sep
22". Pending names are greyed, "mentioned once, not a page yet". Clicking a member opens its entity card **in
the third column** (one slot shared with the Reader), with ⌘[ to go back. The commons go on one "Also uses:"
line.

**8. Conversations.** G124 `ConversationRow`s, newest first, each with Resume.

**9. Where this came from.** The existing section, collapsed by default and remembered per viewer.

### 11.4 STATE 2: list + project + Reader

This opens when an evidence chip, a quote, "Show in conversation" or a band item's ⏎ is used.
- **The Reader** (DR-31) opens as the rightmost column: 420 pt at 1440, 360 pt at 1200, on `bgPane`. The list
  narrows to titles (260 pt, 36 pt rows), and the project keeps at least 440 pt.
- **The Reader holds:**
  - the origin mark, the title, and the meta line "You said · Telegram · Sep 23, 18:04 · dated from
    'Yesterday'";
  - Resume when resumable;
  - "↑ 1 of 3 cited here ↓" across the thread's spans;
  - the speaker blocks with the current span in `wash` and the others in `washSoft`;
  - "Noted from this conversation (n)".
- **Column priority** is project, then Reader, then list (DR-27). The list hides first.
- **Esc** closes the Reader, then the project (DR-28), and never animates.
- **Selecting another project** swaps the detail in place (DR-29). The Reader closes unless the new project
  cites the same conversation.

### 11.5 Keyboard and VoiceOver

- `↑`/`↓` move through the list, `→` or `⏎` open, `⌘[` goes back.
- `m` adds a milestone, `l` focuses the Log field, `d` marks the focused thread done. These join DR-68's
  keyboard map, scoped to the Projects page, in the PJ-5 PR (DR-68 gives `L` another meaning on an Inbox
  question, so the scope is stated there).
- Every shortcut goes through `FindCommands`-style menu commands, never a hidden shortcut
  (`HiddenShortcutLintTests`).
- Numbers go through `UsageFormat.count`, fonts through `CicadaTheme.font`, and motion through `CicadaMotion`.
- The PR body cites DR-5, DR-7, DR-8, DR-13, DR-22, DR-25 to DR-31, DR-40, DR-44, DR-54 to DR-60, the owner's
  §9 line on the band's hues (R-PJ21), and the DESIGN_RULES edits it makes: DR-57's sixth chip label (§7),
  DR-60's and DR-68's ⌘1–7 and Projects keys (R-PJ22).

---

## 12. Demo-bank additions

The generator (`api/services/demo_bank.py`) is extended. The on-disk bank is never touched.

- **`populate(bank_dir, today: date | None = None)`**: every date is an offset from `today`.
- **Scenario entities,** written after the existing 60 so their ids and sentences stay byte-identical. `created`
  and `last_referenced` are backdated:

| id | type | created | notes |
|---|---|---|---|
| `rover-arm-project` | project | T-70 | the robotics stand-in, planned |
| `pick-and-place-demo` | project | T-35 | stands in for `<demo-x>`, `part-of rover-arm-project` |
| `lab-cluster-example` | tool | T-1 | three `spec` claims |
| `hana-example` | person | T-1 | stands in for `<person-a>`, kept out of `_PEOPLE` |
| `media-example-cluster-guide` | media | T-1 | evergreen; `media.url` is `https://example.com/guides/lab-cluster-onboarding.pdf` |
| `garden-sensor-project` | project | T-52 | **no milestones**: the unplanned case, reusing `carol-example` and `tool-example-c` |

- **Scenario episodes,** written after `_write_episodes`, so ids are computed and never hard-coded. Each has a
  `user:` line and an `assistant:` line, and S1, S2, S7 and S9 carry a `turns:` sidecar in the
  `episode_staging` shape:
  - S1 (T-70): started the project.
  - S2 (T-63, same session as S1): the plan. Arm assembled by T-42, first grasp by T-14, the demo by T+12, the
    lab showcase by T+40, all as ISO literals.
  - S3 (T-45): the arm is assembled.
  - S4 (T-35): scoped the demo.
  - S5 (T-24): started calibrating the gripper camera. **Ongoing, then silent.**
  - S6 (T-14): first grasp slipped.
  - S8 (T-1): the cluster specs.
  - **S7 (T-0, Telegram):** the owner's combined sentence (§4.2).
  - **S9 (T-0, Claude Code, left unprocessed):** "Still connecting to Lab Cluster Example; the login node asks
    for a key." This drives the pending line and keeps the Sleep queue non-empty.
  - G1–G3 (T-52, T-30, T-9): the garden project.
- **Claims:**
  - **PJ-1** writes the ordinary claims through `write_claim`: `works-on`, the four G17 `due` claims in
    Stage 1's shape (`context: general`; text "Arm assembled due <T-42>", "First grasp due <T-14>", "Lab
    showcase due <T+40>" on the rover, "Pick And Place Demo due <T+12>" on the demo), `part-of`, `provides`,
    `references`, the `spec` claims (context `general`), `connects-to` and `runs-on`. No demo claim carries a
    non-`general` context, so the graph grows no facet satellites. It then runs `claim_expiry.expire(today)` and
    commits `Expiry <T>` as `cicada`. After that, arm-assembled and first-grasp read "passed, no word".
  - **PJ-3** adds event claims through `progress.py` in three commits:
    - a Sleep-authored commit (model `gpt-5.4-mini`, engine litellm) for the S1, S3 and S5 happenings;
    - an `mcp/claude-code` commit for S7's two happenings;
    - a `user` commit for the person's moves: arm assembled marked done on T-45, and first grasp moved to T+8
      on T-13.
- **Inbox:** PJ-6 runs `followups.propose` once. The quiet camera thread gives one `followup`, so the pinned
  inbox count moves from `== 6` to `== 7`, deliberately and with a comment.
- **Expected derived values at T after PJ-1 alone** (no event claims yet), pinned in the shared fixture:
  - Rover's Q = 20 (median gap 10 over the moment days of S1–S8: T-70, -63, -45, -35, -24, -14, -1, 0). A derived
    moment needs a claim that cites its episode, so the generator gives each of S1–S8 at least one ordinary
    claim with a `user` span in it (S3 `rover-arm-project uses tool-example-d`, S5 and S6 likewise); otherwise
    those days have no moment and Q is not 20;
  - arm-assembled and first-grasp are `passed-no-word`, so progress is 0 of 4;
  - the next milestone is the demo's `due-<T+12>`;
  - no open thread, so the Now rung is absent and the Last rung is S7's moment.
- **Expected derived values at T after PJ-3,** pinned in the same fixture:
  - Rover's Q = 20 (median gap 10);
  - the camera thread is quiet for 24 days and eligible for a follow-up;
  - progress is 1 of 4;
  - the next milestone is first grasp at T+8, moved;
  - the garden project is unplanned and in motion (Q = 43, last activity 9 days ago).
- **Every URL** is on `example.com`, and the test tightens from "any example.com" to "every URL". A text test
  asserts that none of the redacted real names appear.

---

## 13. Cost

| slice | spend |
|---|---|
| PJ-0 to PJ-6 | **$0.** No LLM call is added. Date resolution, matching, the rails, follow-ups and assembly are all Python. |
| PJ-7, Stage-1 extraction | **💸 on BYOK only, per cycle.** |
| PJ-8, consented re-read | **💸 on BYOK only, user-triggered.** |

**PJ-7 per call.**
- **Measured baseline:** the system prompt is 6,695 characters (≈ 1.7k tokens, `len/4`). A chunk is ≤ 12,000
  characters (≈ 3k tokens). The completion is ≈ 284 tokens (measured on GLM with reasoning off,
  `entity_extractor.py:144-151`).
- **Delta:** about +510 input tokens (a 450-token block plus a 60-token header) and +100–300 output tokens.
  - On a full chunk that is about +11% input and +35–105% output.
  - On a short 300-token episode, input rises by about 25%.
- **Cost:** with output priced at 4–8× input per token, the Stage-1 bill rises by roughly **+15–30%** per cycle
  on BYOK. Stage-2 judge and Stage-3 merge calls are unchanged, so the whole-cycle increase is smaller.
- **A worked cycle:** 20 episodes averaging 1.3 chunks is 26 calls, so +13k input and +5k output tokens. The
  money is those counts at the engine's rates, as the ledger records them (`/consumption`, never shown in the
  app).
- **Plans:** $0 on the Claude and ChatGPT plans (quota only). By ruling 4, happenings are extracted on a plan
  only in a cycle the person started.
- **Codex:** its per-call harness overhead is ≈ 7.7k tokens, and signed-in Stage-1 input is still unmeasured
  (G122). PJ-7 measures it and reports it in the PR.

**PJ-8 per project.** The number of calls is ⌈(total characters of the selected episodes) / 11,500⌉. The prompt
is ≈ 1/3 of Stage 1's. The consent sheet shows the count of calls.

**The method,** recorded in the PJ-7 PR:
- the ledger's `input_tokens` and `output_tokens` per Stage-1 call, for 20 demo-bank episodes, before and after,
  per engine;
- `happenings` kept and dropped per cycle.

---

## 14. Tests

**PJ-0 (`test_claim_pipeline_subjects.py`):**
- An owner-subject relationship ("the user" → X) lands on the `owner: true` page.
- A claim on a Stage-2-matched name lands on the matched id.
- A page-less subject increments the drop counter and logs a count, with no text.
- The false comment is gone. A source grep asserts that the phrase "re-emitted next cycle" is absent.

**PJ-1 (`test_project_timeline.py`, `test_projects_router.py`), on the generated demo bank with `today`
pinned:**
- the S7 moment (participants, a `user` quote, the example.com URL, `via`);
- unplanned garden;
- milestone read-compat after expiry, with "passed-no-word" and no `missed` anywhere;
- Q and quiet from `timeline_state` against the shared fixture;
- the commons guard (a tool linked from 13 projects is listed, its moments excluded);
- history bullets, including an out-of-window date read as undated;
- a derived quote for a legacy claim, and a stale span with no offsets;
- the 200-page cap setting `partial`;
- read purity (clean `git status`, unchanged mtimes, providers raising);
- ETag: a 304 on repeat; it changes on an entity, episode or inbox write and on a machine-zone change; it is
  **identical across a pinned midnight**;
- split-brain: a second bank holding the same id is never read;
- the bench at p95 ≤ 150 ms (detail) and ≤ 80 ms (list) on 2,500 pages and 1,500 episodes.

**PJ-2:**
- R12 for `cicada_project` in both primers, across every remote scope set.
- Remote without `sources` shows no quote text and no Log-entry sentence (R-PJ23). Remote without
  `cicada_project` has no tool and no contract line.
- The output's closing line names `cicada_recall_detail(entity_id)`, and the Now and Quiet lines carry claim ids.
- The output prints both date forms.
- `_state.md` v3 stays ≤ 6 KB with 7 projects, and the primer stays ≤ 1,800 tokens. Regenerating it a day later
  with no input change writes nothing and would produce the same bytes (no today-dependent field).
- `read` telemetry is ids and enums only (the ledger is grepped for the quote).

**PJ-3 (`test_claims_event_fields.py`, `test_event_reconcile.py`, `test_when.py`, `test_progress_writes.py`):**
- **Fields:** omit-when-empty round-trips; a legacy fence is byte-identical; `is_event`; status and predicate
  validation; the surface check.
- **Born-closed:** a done happening never appears in recall's current view, the graph edges or conflict
  generation, and does appear in FTS and citations, where it is never `current: false` or ranked as history.
- **No facets:** a project with three milestones and a tool with three `spec` claims each render as one graph
  node (no `claim_contexts.is_facet` context on any event, `spec` or demo claim).
- **Only `progress.py` writes events:** `cicada_write_claim` with `happened`/`milestone` is refused; a Stage-1
  relationship labelled either is relabelled `relates-to`.
- **Human origin:** an app-written milestone is `is_human`; an agent's `done` on it gives `COEXIST_FLAG` plus a
  divergence item; no MCP path (stdio or remote) can produce an origin in `_HUMAN_ORIGINS` beyond the existing
  `manual_edit` owner write.
- **The grep gate:** every module that iterates closed claims calls `is_record` or `is_event`.
- **Reconcile:**
  - a reworded re-extraction of the same span gives one claim;
  - a re-extraction quoting the owner's whole combined sentence for both happenings still gives one done and
    one ongoing claim (the status test);
  - an ongoing restatement on a later day reinforces the open thread and moves `recorded_at`;
  - the same words on two dates give two claims;
  - a same-day create then done gives no conflict item;
  - an agent against a human milestone gives `COEXIST_FLAG` plus divergence;
  - `settles` closes;
  - the Sleep settle rule (2 shared participants close, 1 shared leaves it open).
- **Decay and expiry:** `_decay_claims` skips events; `claim_expiry.expire` never closes a past-`target`
  milestone; `due` behaves as before.
- **`when`:** the closed table against a fixed anchor and zone; DST edges; a UTC `ts` near midnight becoming the
  local date; a missing year; a future `when` on `happened` refused; unknown words falling back to the anchor
  with the right basis.
- **Writes:**
  - each REST action commits `Cicada-Author: user` over its own pages only, and returns 409 during a cycle;
  - a Log entry "got the guide yesterday" is dated T-1 (`stated`), its claim `text` has no "yesterday", and its
    companion episode keeps the words;
  - touching an expiry-closed `due` keeps its `valid_to` and adds only `superseded_by`;
  - the MCP tool, local and remote: the remote observer is never the owner, the scope is `record`, no page is
    ever created, and the reply echoes date and basis;
  - the companion-episode writer scrubs (`test_episode_writers_scrub.py`);
  - no relative word is stored anywhere (a bank grep);
  - `withdraw` on a born-closed claim sets `superseded_by` to the record, and `_how_closed` reads "withdrawn".

**PJ-4 (`test_transcript_turn_stamps.py`):**
- A Stop-hook capture writes `turns` as the list shape, outside `content_hash`, as the last key, capped at 500.
- A rewrite of a grown session keeps a head-stable list.
- A resumed session's day-3 turn anchors to day 3.
- Offsets are `evidence.turn_starts` over the Stop hook's own `"{role}: {text}"` body.
- A turn past the 500 cap has no stamp and anchors with basis `episode`.
- The old integer-count episodes still read as "no stamps".

**PJ-5 (Swift):**
- `timeline_state` against the shared fixture;
- `RelativeDay` with a fixed calendar and locale, including midnight rollover;
- the lint banning "Yesterday"/"Today" literals;
- `ProjectsViewModel` never blanks;
- the column state machine at 1440 × 900 and 1200 × 800, rail and labelled (`ColumnLayoutTests`);
- the Esc order;
- band layout snapshots (planned, unplanned, overdue, moved, quiet) in light and dark at 1440 and 1200;
- the Log field's ⏎ vs ⌘⏎;
- optimistic rollback on 409;
- `routeToEntity` for a project;
- the card's Timeline tab and the Projects band never shown on one surface;
- the existing lints pass with no new allowlist entries.

**PJ-6 (`test_followups.py`):**
- the thresholds and rate limits (1 per project, 3 in the bank, the 30-day re-ask, while decay keeps 7);
- it runs after expiry and before the connector poll, skips dirty pages, and its commit carries only its inbox
  files;
- an Other… answer "done last Friday" dates the successor through `when.resolve`;
- dedup;
- its own `cicada` commit after expiry;
- each option's write through `advance`/`withdraw`;
- verdict grading by author;
- the `InboxKind` parse, and Swift decoding `followup`;
- `cicada_check_nudges` returning it for a recalled project.

**PJ-7 (`test_happening_extraction.py`):**
- the prompt block and header;
- the strict schema re-verified live, and the pin updated deliberately;
- a dropping fixture for each rail reason;
- promotion counters unchanged;
- owner-page filing then read-time relink;
- the switch off → no block;
- telemetry carries no text;
- the combined sentence → a done happening at T-1 (`stated`) and an ongoing one at T-0 (`turn`).

**PJ-8:** the consent count equals the calls made; a second run is a no-op; 409 during Sleep; never scheduled
(a scheduled cycle cannot reach it).

---

## 15. Slices

Each slice is ordered and PR-sized. **Backend** slices can start now. **App** slices need the Direction D shell
track (DS: rail + command bar + progressive columns) merged first.

| # | slice | ships | 💸 | kind | depends on |
|---|---|---|---|---|---|
| **PJ-0** | **Sleep keeps what it hears.** Subject keying through Stage-2 ids; "the user" → the `owner: true` page; a drop counter replaces the false comment. The pending-store hold is a DECIDE, not built. | Richer derived moments from the next cycle; M3 becomes measurable | $0 | backend | — (**start now**) |
| **PJ-1** | **Read model + HTTP.** `project_timeline.py` (tree, derived moments, milestone read-compat, history, activity, pending, cluster with the commons guard), `timeline_state` + the shared fixture, `GET /projects`, `GET /projects/{id}/timeline`, `search_index.claims_about`, the demo scenario with the `today=` seam, the bench. | A truthful timeline for every existing bank, curl-able | $0 | backend | — (**start now**) |
| **PJ-2** | **Agents read it.** `cicada_project` (stdio + remote `read`, `sources`-gated quotes), `_state.md` v3, handshake Current lines, the contract sentence (R12), `read` telemetry surface `project`. | "How's the robotics project going?" answered by any agent | $0 | backend | PJ-1 |
| **PJ-3** | **Happenings and milestones as claims + their $0 writers.** Claim fields, `is_event`, event cardinality in code, born-closed done, `reconcile_events`, the decay skip, the grep-gated readers (citations and `/search` included), the event-predicate refusal in `write_claim`/`claim_pipeline`, `companion_app` in `_HUMAN_ORIGINS`, `ClaimModel` fields + `expectedEnd`, `when.py`, `progress.py`, the REST writes (409 during Sleep), `cicada_note_progress` (stdio + remote `record`), the contract sentence, the event layer in the read model, the demo's event commits. | The owner's sentence recorded live by an agent, and by the person, the same day | $0 | backend | PJ-1 |
| **PJ-4** | **Stop-hook turn stamps** (R-PJ16): `transcript_capture` writes the `turns` list from the JSONL times. | Turn-precision dates for Claude Code and Codex sessions | $0 | backend (capture) | — (**start now**, independent) |
| **PJ-5** | **App: the Projects page.** The rail cell (after the G108 ruling), STATE 0/1/2, the band, All projects, Now, the Log field and thread buttons, Plan, Around this project, Conversations, `ProjectsCache`, `RelativeDay`, `ProjectState.swift`, `GraphNode` dates + the `NODE_SHAPE` bump, Home "In motion", "Open project ›", the DESIGN_RULES §9 line. | What the owner asked to *see* | $0 | **app (needs DS)** | PJ-1, PJ-3; the DS shell; G108 |
| **PJ-6** | **Follow-ups.** `InboxKind.followup` + writer + loader + resolver + Swift decode in one commit, the Sleep-tail proposer, the question objects, verdict grading, `cicada_check_nudges`. | "How did it end up going?", at most 3 open, never nagging | $0 | backend + a small app decode | PJ-3 |
| **PJ-7** | **Sleep happening extraction**, gated on M1–M3: the anchor header with known projects, the prompt, the strict schema with the live codex re-verify, the rails, participant mapping, planned → milestone, `happenings` telemetry, the Settings → Memory switch. | Sleep narrates what agents did not | 💸 +15–30% Stage-1 on BYOK; plan quota on a user trigger only | backend | PJ-0, PJ-3, PJ-4; M1–M3 |
| **PJ-8** | **Consented per-project re-read.** | Old projects get narrated history on a click | 💸 user-triggered | backend + the app's `…` menu item | PJ-7, PJ-5 |

**PJ-3 is the largest slice.** If its plan runs past one reviewable PR, it splits along one seam without
renumbering: **PJ-3a** is the claim layer and the agent path (fields, `is_event` and its readers, cardinality,
`reconcile_events`, `when.py`, `progress.py`, `cicada_note_progress`, the refusal, the contract sentence);
**PJ-3b** is the person's path (`routers/projects.py`, the companion episode, `_HUMAN_ORIGINS`, the demo's event
commits). 3a merges first; each is shippable alone.

**Start now, in parallel:** PJ-0, PJ-1 and PJ-4. Then PJ-2 and PJ-3, which touch different files and so can
run as two tracks. PJ-6 follows PJ-3. PJ-5 starts once DS merges and G108 is ruled. PJ-7 is planned only after
M1–M3 are read. If they show derived moments plus agent writes suffice, PJ-7 and PJ-8 are dropped without
undoing anything.

**Docs per slice.** Update CLAUDE.md (claim fields, `is_event`, the `written` date basis, `companion_app` as a
human origin, triggers `sleep/followup` and `user/backfill`, the `followup` inbox kind and its 30-day defer,
`processed_by: user`, the Stop-hook `turns` shape, which replaces the rail sentence "the Stop hook's `turns:`
stays its integer count", the `/projects` ETags in the ETag list, the Projects page paragraph). PJ-5 also edits
DESIGN_RULES (DR-57, DR-60, DR-68, the owner's §9 line).
Update the G141 row's status line and TODO.md. Each slice cites `G141` in its commits and PR body.

---

## 16. Not in scope

- **G13's app-wide tasks and ideas board,** and Sleep capture of undated "we should…" items. Planned items
  without a date stay G13's (`undated_plan`).
- **Holding an unpromoted subject's claims in the pending store** (R-PJ17): a DECIDE on the row.
- **A sibling events file per project,** opened only on the fence-growth trigger (§17 M6).
- **Calendar events (ICS) as milestones.** They are a natural follow-up, since ICS is already polled, but they
  need their own row.
- **Dependencies between milestones, Gantt bars and critical paths.** Cicada records what it was told and does
  not plan projects.
- **Any percentage, any LLM-written project summary or status digest** (the G53 and G140 rejection of written
  profiles), **any price.**
- **Editing a happening's words in place.** Withdraw and log again. Only a milestone rename is edited in place,
  and only by the person.
- **Multi-bank project views.** Projects live in the active bank.

---

## 17. Risks and what to measure

All live-bank measurements are count-only scripts the owner runs. They print numbers, never text, and nothing
leaves the machine.

| # | risk | measure | threshold → action |
|---|---|---|---|
| M1 | Derived moments don't *tell* what happened | The owner grades 20 moments across his top 5 projects: tells me / partly / no | "no" > 30%, or "tells me" < 50% → build PJ-7 |
| M2 | Coverage: project conversations yield no moment and no happening | % of tree `source_episodes` with ≥ 1 moment or happening, before and after PJ-0 | < 60% after PJ-0 and two weeks of PJ-3 → PJ-7 |
| M3 | The owner is missing from moments (page-less and owner-mapping loss) | % of moments with an owner participant; page-less drops per cycle (the PJ-0 counter) | Should rise sharply after PJ-0; if not, the mapping is wrong |
| M4 | Hub flooding | Degree distribution of member → project links; p95 members per project | Tune `COMMONS_DEGREE`; p95 ≤ 40 |
| M5 | Wrong dates | The `date_basis` mix; the share of Stop-hook sessions spanning more than one local day; the count of Stop-hook episodes past the 500-turn cap (R-PJ16); resolver-vs-model disagreement (an enum in `happenings`) | `episode` basis > 20% after PJ-4 → look at the sidecar writer; many sessions past the cap → a RESEARCH row on a tail-keeping cap |
| M6 | Fence growth on busy project pages | Bytes and event claims per project page after 30 days | Any page > 150 event claims or > 120 KB → open a RESEARCH row for `entities/<id>.events.md` (still claims, one module) |
| M7 | Trivia from extraction | `happenings` kept/dropped by reason; after 2 weeks the owner marks the first 50 ("That didn't happen" rate) | Kept-worthy < 60% → switch off by default and revisit the prompt; target ≥ 80% |
| M8 | Latency | p95 of both endpoints on the live bank | > 150 ms detail → move remaining raw scans to FTS |
| M9 | Follow-ups become maintenance (UX principle 1) | Asked vs answered vs deferred (the G113 ledger) | Answer rate < 30% → raise Q's multiplier, or cap at 1 bank-wide |
| M10 | Budgets | `_state.md` bytes; primer tokens | ≤ 6 KB; ≤ 1,800 |
| M11 | The owner reads projects in Obsidian more than in the app | His own verdict after two weeks | A DECIDE row reconsidering a rendered `## Timeline` section (derived, never authoritative) |
| M12 | Missed readers show a past event as a current belief | The grep gate; recall snapshots on the demo bank | The gate is the merge bar for PJ-3 |

**Named risks, not measured:**
- **Travel.** Dates resolve in the Mac's zone. That is disclosed; it is not fixed.
- **Hand edits.** An Obsidian edit mid-cycle can collide with a fence write. That is the standing G85 class;
  the 409 gate covers the app's own writes.
- **The first weeks.** The conservative settle rule leaves many open threads. Follow-ups close them, and M9
  watches the cost.
