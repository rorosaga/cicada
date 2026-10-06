# Cicada — DONE

**Code-backed scope review: 2026-10-06, merged `dev` `3efba432`.** This is a completed-scope index, not a queue. Historical design discussions and execution logs remain in git. Later enhancements live under the active G IDs linked from the backlog. A completed implementation does not claim every real-world client or fresh-machine scenario has been tested.

[Active backlog](memory-evolution.md) · [Priority and handoff](TODO.md) · [Working method](working-method.md)

**Corrections after drilling down:** [G1](memory-evolution.md#g1) is active again for its original cross-bank references; [G23](memory-evolution.md#g23) is active again for hover previews. Bank CRUD and playback/thumbnails remain shipped. [G50](memory-evolution.md#g50) is active again for the requested Cursor integration/provider adapter; the other provider connections remain shipped. [The per-ID implementation review](BACKLOG_IMPLEMENTATION_REVIEW.md) records every original address and explicit adjacent transfers.

## Completed feature scopes

### G9

Capture origin/provenance across harnesses. Remaining adjacent work: G48/G116 attribution limits.

### G12

Date-preserving ChatGPT/Claude/Gemini import queue. Remaining adjacent work: G10 hands-on trial; G170 import quality.

### G15

Contributor avatars. Remaining adjacent work: G103 observer semantics.

### G18

Directory versus physical-location typing. Remaining adjacent work: G128 location capture.

### G20

Delta re-import and visible new/grown/unchanged counts. Remaining adjacent work: G104 semantic revisions; G10 real export verification.

### G24

Markdown summary box.

### G26

Light/dark theme control. Remaining adjacent work: G137 design system.

### G28

Sleeping sprite state. Remaining adjacent work: G176 remaining room design.

### G30

Chrome/Safari bookmark ingestion. Remaining adjacent work: G119 additional browsers.

### G47

Saved-content importer family foundation. Remaining adjacent work: G71 completed save-with-reason; later platform adapters.

### G52

In-app grounded Ask. Remaining adjacent work: G93 cross-stream relevance; G10 behavioral trial.

### G57

Telegram per-request webhook secret.

### G58

Shared Store/SSE/ETag synchronization foundation and October cache/stamp fixes. Remaining adjacent work: G183 remaining write integrity.

### G59

Entity logo rendering foundation. Remaining adjacent work: G159 trusted-source picture improvements.

### G60

Time-aware question/conflict object and resolution interface. Remaining adjacent work: G115 further question design.

### G62

Connected-channel capture page. Remaining adjacent work: G126 additional integrations.

### G63

Connection state copy. Remaining adjacent work: G76 client wiring validation.

### G66

Durable/active/volatile/evergreen decay classes. Remaining adjacent work: G147 frequency-aware follow-ups.

### G67

Git commit diff UI.

### G68

Sidebar and Settings navigation foundation. Remaining adjacent work: G106/G137 current navigation/design.

### G71

Save-with-reason, Imports page and implemented connector foundation. Remaining adjacent work: Later individual adapters retain their own IDs.

### G75

Initialize handshake and schema/primer parity. Remaining adjacent work: G180 leaner CLI/MCP.

### G83

Button hit areas and disabled appearance.

### G88

Installed app build path. Remaining adjacent work: G182 downloadable release.

### G90

Demo-only README screenshots and integration refresh. Remaining adjacent work: G158/G182 actual release/download copy.

### G97

Basic claim cause/provenance display. Remaining adjacent work: G118 evidence extensions.

### G105

Deterministic Stop-hook capture, independent of model tool calls. Remaining adjacent work: G104 resumed-session semantics; G10 client validation.

### G107

Mascot states tied to Sleep stages. Remaining adjacent work: G176 count/queue design; G184 energy.

### G108

Home as default front door and themed layout. Remaining adjacent work: G106 navigation history.

### G114

Atomic episode storage, revision retirement and stage/commit hygiene fixes. Remaining adjacent work: G183 remaining page/commit gaps.

### G123

Graph node search and reveal navigation. Remaining adjacent work: G136 completed broader palette.

### G129

Live Chrome/Safari bookmark watch, catch-up and user-decided removal proposals. Remaining adjacent work: G119 additional browsers.

### G136

Derived lexical search and app find palette. Remaining adjacent work: G93 relevance; G118 provenance.

### G144

Clock-aware painted Home/Welcome scene. Remaining adjacent work: G184 energy follow-up.

### G145

Paged onboarding and integrated demo, October animation-idle fix. Remaining adjacent work: G117 residual first-run seams; G10 clean-bank acceptance.

### G149

SessionStart/UserPromptSubmit implicit recall hooks. Remaining adjacent work: G10 fresh-session behavior; G180 context overhead.

### G152

Skippable real/demo guided tour.

### G153

Ready-page memory quote.

## Completed foundations and research

These permanent addresses are retained for provenance. “Research complete” means a dossier exists; it does not mean the feature described by that research shipped.

| ID | Completed scope | Evidence / next work |
|---|---|---|
| A1 | **Per-commit diff view in node history** | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| A2 | **Contributors view** | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| A3 | **Animated bookworm on ingestion page** | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| A4 | **Enrich `skill` entity capture** | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| A5 | **Explicit gap analysis ("I don't know")** | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| R1 | [Why Honcho is good (deep)](../inspiration/research/r1-honcho-philosophy.md) | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| R2 | [SkillOpt (Microsoft)](../inspiration/research/r2-skillopt.md) | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| R3 | [Postgres+pgvector vs markdown+git+LEANN](../inspiration/research/r3-postgres-pgvector.md) | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| R4 | [Contextual / multi-dimensional entities](../inspiration/research/r4-contextual-entities.md) | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| R5 | [Cost model for reconsolidation](../inspiration/research/r5-reconsolidation-cost.md) | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| R6 | [Sync connectors](../inspiration/research/r6-sync-connectors.md) | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| R7 | [Entity promotion: keep or kill?](../inspiration/research/r7-entity-promotion.md) | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |
| R8 | [Peer / observer-observed model](../inspiration/research/r8-peer-model.md) | Original dossier/feature scope completed; current constraints and follow-ups remain in the active backlog and TODO rulings. |

- **M1:** Markdown/git source of truth plus disposable sqlite-vec storage. Current model selection is documented in `embedding_models.py`; the old M1 default is historical.
- **M2:** Grounded Ask with citations and explicit gaps; retain its documented self-reported confidence limitation.
- **M3:** Git author/session attribution, diffs and contributor view.
- **M4:** RSS/media feed, capture animation and source connector foundation.
- **M5a/M5e/M5f:** Claims, evidence/trust, temporal validity, recall integration and live Sleep claim-layer wiring.
- **M5-prep:** Provider factory and comparison harness. Earlier live-run reports are dated evidence, not a new consolidation.
- **Calendar ICS / Notes:** Connector foundation; EventKit and source-specific work stays G142/G126.
- **G176 shipped portion:** Bookworm/study-room sprite delivery and player, owner-reviewed preview, and the October Sleep-page CPU fix. Remaining art/UI work stays G176/G127/G175/G184.
- **October audits:** Closed findings and exact reported checks live in [October 2 status](audit-2026-10-02/STATUS.md) and [October 5 status](audit-2026-10-05/STATUS.md). Remaining findings are G183–G185.

- **G98 shipped portion (#196, `3efba432`):** shared subject/defer filtering and served-inbox counts for status/Home; the remaining upstream cleanup stays G98. No new test run is claimed by this documentation review.

## Closure rule

Move a whole G row here only when its remaining scope is complete. If a feature is implemented but acceptance is still open, keep the active row with that acceptance spelled out. Conditional future improvements are separate open rows; they do not re-open completed work automatically.
