# Provider and ingestion modularity

**Owner requirement, 2026-10-06.** Adding or removing a provider such as Cursor should be a small, explicit code change across the backend and frontend. Adding a capture source such as iMessage should have a separate extension point. Optional AI-agent identification is a third, replaceable concern; initially support Instinct only. These workflows are not fully implemented.

Permanent addresses: [G50 — providers](../goals/memory-evolution.md#g50), [G188 — ingestion adapters](../goals/memory-evolution.md#g188), [G179 — iMessage](../goals/memory-evolution.md#g179). G49/G122 own engine behavior; G76/G110 own capture, recall and continuation acceptance. This brief records requirements, not a selected implementation or an installed plugin system.

## Provider modules: backend and frontend

The backend already has a `ConnectionAdapter` protocol and a registry in [connections/base.py](../../api/services/connections/base.py) and [connections/registry.py](../../api/services/connections/registry.py). However, engine dispatch/selection still names providers in [providers.py](../../api/services/providers.py) and [engine_select.py](../../api/services/engine_select.py). The app also maintains its [AgentCatalog](../../app/CicadaApp/Sources/CicadaApp/Models/AgentCatalog.swift) and provider-specific [EngineChooser](../../app/CicadaApp/Sources/CicadaApp/Views/Settings/EngineChooser.swift) branches. A connection adapter alone does not make this full path modular.

- Give each provider a stable ID, registration and explicit capabilities: agent/MCP setup, deterministic capture, startup recall, connection/auth, model discovery, engine execution, cancellation and usage/limit reporting. A client integration does not imply a usable consolidation engine or subscription API.
- Share or generate the descriptive contract consumed by the app and headless clients: availability, setup/auth method, supported operations, model/effort controls and actionable unavailable states. Keep genuinely provider-specific authentication or controls in a small local adapter/view. Avoid duplicate catalogs and scattered core switches; choose the simplest registry/contract compatible with the shipped code.
- Register implementation modules in code. No runtime package loader or third-party execution framework is required. Keep provider credentials and subprocess environment handling inside the existing governed boundaries.
- Removing a provider stops its probing and hides unavailable operations. A saved selection becomes visibly unavailable with an explicit replacement choice; never silently substitute an engine, bill an API key, delete memory or lose historical provider/session attribution. Older persisted IDs and older app/backend pairs fail intelligibly.
- Cursor is the first real extension exercise. Verify its supported interfaces at implementation time, then add only proven capabilities to frontend and backend. Preserve scheduled-plan, consent, credential and self-spawn capture-off rules.

**Acceptance:** add and remove a fixture provider by its module/registration and optional local UI adapter, without editing consolidation/capture algorithms or several unrelated views. Contract checks cover capability exposure, auth/model/cancellation/error handling, absent-provider settings and existing provider behavior. Then demonstrate the supported Cursor path through setup, capture/recall and G110 continuation; engine acceptance is separate if supported.

## Ingestion modules, separate from providers

[episode_staging.py](../../api/services/episode_staging.py) already supplies `EpisodeDraft`, scrubbing, stable source identity, revision staging and tombstones. Source readers, parsers, routes and UI remain source-specific; [local_sources.py](../../api/routers/local_sources.py) and [LocalSourceWatcher](../../app/CicadaApp/Sources/CicadaApp/Services/LocalSources/LocalSourceWatcher.swift) show the existing seams. Reuse the stager rather than making each adapter write its own episodes.

- A source declares its ID, supported platform, permission/setup requirements, selectable scope, read/sync operations, cursor/revision semantics and attachment support. Its parser converts permitted bytes/projections into attributed dated drafts; a shared coordinator stages and reports them.
- Keep acquisition distinct from parsing. The macOS app owns permission and reads `~/Library`; the backend parses posted bytes and never opens those paths. Headless installations report app-only readers as unavailable, while portable export parsers remain usable.
- The Integrations/Sources frontend renders common status, scope, sync/error and removal behavior from source capabilities. A source can supply a small custom picker or permission view. Add/remove an adapter without copying the whole watcher, router or settings screen.
- Preserve source-key dedup, continuation edits, deletions/tombstones, active-bank checks, demo guards, revocation and source/model/speaker attribution. Stopping a source stops future capture; removing a module must not erase captured history. Capture stays deterministic and has no LLM call.

**Acceptance:** a fixture source plus iMessage each use the shared staging contract; reimport is idempotent, continuation updates the same source, revisions/deletions remain traceable, and disabling/removing the adapter stops capture. Unsupported OS/permission states are visible. Implement only the small seam iMessage needs first; migrating every existing source is not a prerequisite to shipping G179.

## Optional agent identification: Instinct first

The owner explicitly wants iMessage implemented, with an optional ability to identify AI-agent correspondents automatically. Keep this identification separate from message transport and from inference/model providers: a texted agent is not necessarily a Cicada engine.

- Provide an opt-in detector registry with an Instinct-specific deterministic matcher first. Use only permitted thread/contact metadata within the selected/disclosed scope. Actual contact identifiers and matching fixtures stay private; public examples are synthetic. Verify supported recognition signals during implementation rather than inventing them.
- A result records detector ID/version, the matched signal and identified/uncertain/unknown outcome. Let the person inspect, correct or override the correspondent's actor kind and agent label. Names alone are insufficient proof; unknown participants remain unknown rather than being classified by model intuition.
- Recognition never selects additional threads, grants access, contacts an agent, raises trust or turns agent statements into the person's own words. Disabling recognition leaves normal selected-thread capture working. Persist attribution corrections with their history.
- Preserve the transport (`iMessage`), conversation/source identity, actual speaker and detected agent identity separately through capture, Sleep and evidence. No new entity type is implied.

**Acceptance:** a synthetic Instinct match is recognized when enabled; a similarly named human is not confidently classified; ambiguous cases are surfaced; an override survives the next sync; detector removal preserves conversation history and ordinary capture. Demonstrate selected iMessage conversation → continued sync → consolidation → grounded answers with correct speaker attribution.

## Sequence

G50 provider modularity is P2, developed with Cursor and headless work. G188's small staging/reader contract and detector interface support the P1 G179 iMessage slice; broader source migration is P2. Neither a universal plugin platform nor all provider integrations should block the first useful-memory trial. [G148](../goals/memory-evolution.md#g148) measures these paths as part of the complete system.

Only documentation was changed; no messages, contacts, credentials or private-bank data were read.
