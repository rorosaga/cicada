# Source refresh and video consolidation — unfinished product paths

Owner follow-up, 2026-10-06, after backlog organization. Code reviewed on `dev`
at `3efba432`; no private bank, profile, video or transcript was read. This is a
code-path review and a product proposal, not a live acceptance result.

[G61](../goals/memory-evolution.md#g61) owns refresh sources, source-node links
and their entity-card UX. [G22](../goals/memory-evolution.md#g22) and
[G162](../goals/memory-evolution.md#g162) own useful video memory and the watch
workflow; [G166](../goals/memory-evolution.md#g166) owns agent reading permissions.

## What already exists, and where it stops

| Path | Implemented | Remaining boundary |
|---|---|---|
| Entity refresh sources | `sources:` entries keyed by reference and predicate; attribution, access, acceptance, removal tombstones and optional `entity:` | No general query-driven refresh flow independent of an inbox question. |
| Agent inspection | `cicada_recall_detail` returns the full entity Markdown, including sources; add/change source tools exist | This exposes the cheat sheet but does not ensure that an agent selects a relevant fresh source before answering. `cicada_sources` is raw provenance conversations, not the refresh-source list. |
| Agent source checks | Ranked sources for pending checkable inbox items appear in the reading queue; an agent records findings in shadow | `record_check` needs an existing question/authorized target. It does not write a claim or refresh an arbitrary entity fact. |
| Sleep source work | Attach cited URLs without fetching; link existing source nodes by exact reference; verify proposed official-site identity behind the fetch gate | Official-site identity verification is not current-employment/project refresh. The general public-fetch/refresh ladder remains unfinished. |
| Entity-card sources | “Look it up at,” profile/site-aware add field, grouping by fact, access/accept/remove/edit controls and “Open page” | Adding a profile initially gives a person a general reference; assigning the correct fact is a later free-text edit. Improve discoverability and purpose selection; show fact-check freshness separately from site identity. |
| Video watch records | Agent reports a summary and timestamped excerpts; one attributed `describes` claim and one unprocessed `video-watch` episode | The agent must obtain the content through an allowed method. Saving a link or finishing a queue job does not prove useful consolidation or factual accuracy. |
| Video Sleep intake | Watch episodes are born `processed: false`, so the source-agnostic Sleep queue can consume them | Real watch → Sleep → useful relations/recall with timestamps remains an acceptance test. Repeating a record to add basis/engine preserves the processed state rather than re-consolidating it. |

Evidence:

- `api/services/fact_sources.py:352`: source-node resolution requires an existing
  non-dropped page; it never creates one.
- `api/services/source_links.py:1`: exact URL/path matching, no name-based guess,
  no page creation, no overwriting an explicit link/unlink.
- `api/services/mcp_tools.py:1498`: full-page detail read; `:1525`: raw provenance
  sources; `:2260` and the adjacent source handlers: refresh-source writes.
- `api/services/reading_queue.py:176` and `:234`: candidates come from pending
  inbox items; site permission/master switch/recheck interval gate queue entries.
- `api/services/source_check.py:248`: predicate matching, owner-source acceptance
  and locus restrictions; a person's preferences are not verified by a webpage.
- `api/services/check_record.py:1` and `:91`: checks are shadow findings,
  `processed: true`, `processed_by: agent`; Sleep does not turn them into new
  beliefs merely by rereading the observation.
- `api/services/sleep_cycle.py:1018`: official-site proposal/verification;
  `:2640`: source-agnostic unprocessed episode intake.
- `app/CicadaApp/Sources/CicadaApp/Views/Graph/LookItUpSection.swift:27`, `:92`,
  `:134`: current section, add field and predicate selection on add.
- `app/CicadaApp/Sources/CicadaApp/Models/EntitySourceEdits.swift:27`: fact labels
  are slugged, not mapped from a friendly question to a known predicate.
- `api/services/watch_record.py:159`, `:239`, `:307`: unprocessed watch episode,
  bounded excerpts and direct attributed description claim; `:139`: repeat
  behavior.
- `api/services/video_state.py:267`: record/basis and Sleep processing status are
  separate read models. A queue's completion is not Sleep completion.

## Recommended source model

A **source is a role of a link**, not an entity type. Keep three meanings clear:

- **Related node / wikilink:** this thing is connected to that thing.
- **Refresh source:** check this reference for a particular fact about this entity.
- **Evidence citation:** this observation actually supported a belief, at a time,
  with attributable text/spans. Merely adding a refresh source supplies no evidence.

A reusable profile, repository, paper or page can have its own canonical node,
and a refresh-source entry can link to it. Reuse it across facts/entities without
duplicating its content. Retain lightweight URL/file/app/note references when a
standalone node is not useful. **Do not require every source to become an entity**
or add a new `source` entity type: that would bypass promotion and produce nodes
for Contacts cards and one-line reminders. The current optional node link already
supports much of this model. Explicit save/create-and-link UX, dedup and identity
rules remain a G61 design slice; they are not implemented by the existing picker.

For example, `<person>` can have a profile source for `works-at` and another for
`works-on`. A profile source for employment is not evidence of everything the
person is currently doing, nor of a preference known only to that person. Real
values redacted; no personal profile URLs belong in public backlog examples.

The source relationship needs its purpose, access, contributor/trust and optional
node. Fact observations need their own checked time, observed/effective time when
known, finding/evidence and outcome. “Official site confirmed” verifies identity;
it must not become “current employment checked.” A page-wide successful read must
not refresh every predicate it did not actually answer.

## G61 implementation slices

1. **Make source entry practical on the entity card.** Use a recognizable Sources
   section with a short “Where to check this information” explanation. Paste a
   profile/social/site URL and add it immediately; offer an optional purpose picker
   mapped to real predicates, e.g. current employment → `works-at`, current projects
   → `works-on`, official site → `website`, or general reference. Avoid generating
   `current-work` when the checker expects `works-at`. Show purpose, access,
   who added/accepted it, last fact check and a concise outcome; open externally
   or open its node; edit/remove and reuse an existing node. Do not force a node
   creation or a maintenance wizard just to add a profile.
2. **Expose a bounded refresh cheat sheet to every agent surface.** Entity detail,
   relevant recall and future CLI discovery should share one ranked source model,
   scoped by requested predicate and caller permission. Do not put every URL into
   the handshake or turn raw provenance `cicada_sources` into a confusing second
   meaning. A current-fact query can select a stale relevant source without
   manufacturing an inbox conflict. Define the independent finding-record path,
   freshness/cooldown, unresolved/blocked results and revocation behavior.
3. **Check before answering when appropriate.** Once the person has allowed the
   site/method, their running agent may follow the selected source with its own
   permitted tools. Cicada's backend reads only public allowed content on its
   existing rail; it never opens a signed-in profile. Unavailable access is a
   visible result. Capture when/what was observed; answer with that basis and admit
   staleness/gaps. No check promises a successful read or true current information.
4. **Connect the observation to governed memory updates deliberately.** Current
   `record_check` is shadow-only. Keep that behavior until an explicit separate
   proposal/claim-write bridge is designed and approved against S3: a check does
   not silently settle, reorder or overwrite a belief. Distinguish an attributed
   external observation from the person's own statement; contradictions go to the
   person. Check episodes marked processed are not accidentally fed back into
   Sleep as if they were the person's words.
5. **Define Sleep's use of the same cheat sheet.** Preserve cited-URL attachment,
   source-node linking and site verification. Add bounded predicate-specific
   public pre-checks/agent handoffs for eligible facts, with the current network
   gates and no automatic signed-in browser spawn. Checking mutable facts should
   use relevance/freshness, not continuously poll every person or source.

These slices refine G61; they do not approve the older historical automatic
settlement proposals in its row. S3 and the source/network ownership rails remain
binding. Record exact schema/ETag/client changes together when implementing.

## G22/G162 video acceptance and remaining work

Keep video acquisition, recording and consolidation separate. The built path is:
saved link → selected watch/transcript request → person's agent obtains permitted
content → `cicada_record_watch` writes a description and timed excerpts → Sleep
consumes the new watch episode → recall can use the resulting memory. Sleep does
not watch a raw link, and adding a video URL to an imported conversation does not
run this path automatically.

Before treating it as done, test a real permitted example end to end: useful
description, transcript versus frame basis stated honestly, timestamped source
links, concepts related to the relevant project when supported, creator statements
kept separate from the owner's beliefs, retrieval by topic rather than title, and
idempotent re-recording/consolidation. Distinguish “agent recorded,” “queue
completed” and “Sleep processed.” A discussion or saved reason can establish
personal relevance; watching alone does not establish agreement or preference.

Recheck named seams against current code before building: V4b's reviewed skill
version/path, login/reading-method handoff, unknown video-host queuing, returning
to an unfinished run, and timestamp navigation. V5 optional duration metadata
and V6 direct keyed video understanding are DECIDE items, not prerequisites for
using the existing agent path. No video download/transcription by Cicada and no
stored full transcript are added by this proposal.

## Near-term acceptance

Include one source-enabled fact check and one allowed watch record in the G10
hands-on trial, separately from the initial conversation-export batch. Report
generic outcomes only; all personal examples stay private. Sources/video
understanding belong in the useful-memory priority group before new peripheral
capture channels. Do not delay the first conversation trial until every optional
source/video feature exists; use the failures to choose the next slice.
