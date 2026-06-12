# Unified Inbox — v2 Design Spec

Status: implementation-ready. Owner axis: merge `nudges` + `clarifications` into ONE typed inbox.
Branch: `feat/v2-revamp`. Target: single developer, ~2-3 days.

Live data at design time: 39 nudges (`nudge-NNN.md`, all `type: decay`), 33 clarifications (`clar-NNN.md`). No data loss permitted — migration is one-time and idempotent.

---

## 1. Goals & decisions (decisive)

1. **One storage dir** `memory/inbox/` holding both kinds. Unified frontmatter with a `kind` discriminator and a `required_input` field that the UI uses to pick the action set. **We do NOT keep two dirs behind a merged endpoint** — we physically consolidate to one dir, because the duplication (two `_load_*`, two resolve plumbings, two MCP scans) is the actual cost we are paying. One dir = one read path.
2. **One API** `GET /inbox` + `POST /inbox/{id}/resolve` with kind-dispatched resolution. Plus `GET /status` aggregate (sleep state + inbox counts) for the menu-bar avatar.
3. **Backward-compat shims**: `/nudges`, `/nudges/{id}/resolve`, `/clarifications`, `/clarifications/{id}` are kept as thin deprecated wrappers that read/write the same `inbox/` dir and project the legacy response shapes. The SwiftUI app migrates to `/inbox`; the shims exist so nothing breaks mid-migration and any external caller keeps working.
4. **Sleep pipeline writes the new format** directly (no post-hoc conversion).
5. **Bug fixes folded in**: (a) nudge-ID collision (count-based → max-id+1, shared with clarifications); (b) conflict answers synthesized via LLM instead of raw-appended; (c) resolution commits surface in sleep history.
6. **One ID space**: every inbox item is `inbox-NNN`. Migration renumbers. The `kind` lives in frontmatter, not the filename.

---

## 2. Storage: `memory/inbox/` unified schema

### Directory
`memory/inbox/*.md` — created at API startup (replaces the `nudges`/`clarifications` mkdir in `main.py` lifespan; those two are still mkdir'd for the shim/migration read but no longer written to).

### Filename / ID
`inbox-NNN.md`, zero-padded 3 digits. ID == `filepath.stem`. Next-ID is **max-existing-number + 1** (see §6 helper), never a count.

### Frontmatter schema (one schema, all kinds)

```yaml
---
kind: decay            # decay | conflict | clarification | merge_suggestion
                       #   (merge_suggestion = the "possible duplicate" case that
                       #    today is a clarification with uncertainty_type "Possible duplicate of …")
required_input: choice # none | choice | freetext | merge
                       #   decay        -> choice   (keep / archive / later)
                       #   conflict     -> choice   (option A / option B / both)  +freetext fallback
                       #   clarification-> freetext (who/what is X?)
                       #   merge_suggestion -> merge (answer / dismiss / merge into target / skip)
status: pending        # pending | snoozed   (snoozed = "remind me later", carries snooze_until)
priority: 0.40         # float; sort key. decay -> the dropped confidence; conflict -> 0.8; clarification -> suggested_confidence; merge_suggestion -> suggested_confidence
entity_id: 100%-edge-cases     # slug of the entity this item is about (may be empty for a pure clarification with no entity yet)
entity_name: 100% edge cases   # display name / mention
created_date: '2026-04-16'
source_episode: ep_2026-02-01_001          # optional; provenance
source_episode_timestamp: '2026-02-01T21:55:34.845964Z'  # optional; for chronology-correct stamping
snooze_until: '2026-04-23'                 # optional; only when status == snoozed
# --- choice/conflict ---
options:                                   # optional; choice/merge inputs
  - "Uses Postgres"
  - "Uses SQLite"
  - "Both are true (different contexts)"
# --- clarification / merge_suggestion ---
uncertainty_type: "Possible duplicate of AI-powered data migration service"  # optional
suggested_classification: "project — could refer to …"                       # optional
suggested_confidence: 0.89                                                    # optional
merge_target_hint: ai-powered-data-migration-service                         # optional; pre-filled merge target slug
---

<body = the full human-readable context / question>
```

**Body** = what `full_context` (nudges) and `source_context` (clarifications) carried. Free markdown.

### Kind → required_input → action vocabulary (the resolution contract)

| kind | required_input | resolve actions (`action` field on POST) | effect |
|------|----------------|-------------------------------------------|--------|
| `decay` | `choice` | `keep_active`, `archive`, `remind_later` | keep: status=active, confidence≥0.6, last_referenced=today, delete item. archive: status=archived, delete. remind_later: status=snoozed, snooze_until=+7d, item stays. |
| `conflict` | `choice` | `resolve` (with `answer` = chosen option text or free text) | **LLM-synthesize** the answer into the entity body (§7 fix), bump version, delete item. |
| `clarification` | `freetext` | `answer` (`answer` required), `dismiss`, `skip` | answer: create/update entity (existing clarification "answer" logic), delete. dismiss: delete. skip: keep item, no-op. |
| `merge_suggestion` | `merge` | `answer`, `dismiss`, `merge` (with `merge_target`), `skip` | identical to existing clarification merge/answer/dismiss/skip logic. |

This preserves every existing behavior exactly; it just routes through one dispatcher.

---

## 3. Pydantic models — `api/models/schemas.py`

Add (keep `NudgeType`, `NudgeResponse`, `ClarificationResponse`, and their resolve requests for the shims):

```python
class InboxKind(str, Enum):
    decay = "decay"
    conflict = "conflict"
    clarification = "clarification"
    merge_suggestion = "merge_suggestion"

class RequiredInput(str, Enum):
    none = "none"
    choice = "choice"
    freetext = "freetext"
    merge = "merge"

class InboxItem(CamelModel):
    id: str
    kind: InboxKind
    required_input: RequiredInput
    status: str = "pending"                 # pending | snoozed
    priority: float = 0.0
    entity_id: str = ""
    entity_name: str = ""
    title: str                              # short one-liner (= old short_description / "<mention>")
    body: str                               # full context
    options: Optional[list[str]] = None
    created_date: str = ""
    # clarification/merge extras (optional, only populated for those kinds)
    uncertainty_type: Optional[str] = None
    suggested_classification: Optional[str] = None
    suggested_confidence: Optional[float] = None
    merge_target_hint: Optional[str] = None

class InboxResolveRequest(CamelModel):
    action: str
    answer: Optional[str] = None
    merge_target: Optional[str] = None

class StatusResponse(CamelModel):
    # menu-bar / tamagotchi aggregate
    sleep_status: str                       # idle | running | error | completed_with_warnings
    sleep_stage: int = 0
    sleep_total_stages: int = 5
    avatar_state: str                       # awake | sleeping | ingesting | confused  (computed, see §5)
    inbox_total: int
    inbox_by_kind: dict[str, int]           # {"decay": 39, "conflict": 0, ...}
    unprocessed_episodes: int
    index_warning: Optional[str] = None
```

---

## 4. New router — `api/routers/inbox.py`

A single helper builds `InboxItem` from a file; resolution dispatches on `kind`.

```
GET  /inbox                         -> list[InboxItem]   (sorted: status pending first, then priority desc, then created_date desc)
GET  /inbox?kind=decay              -> filter by kind (optional query param, comma-separated)
POST /inbox/{item_id}/resolve       -> {"status": "...", "id": item_id}   body = InboxResolveRequest
```

### Resolution dispatch (pseudostructure)

```python
@router.post("/inbox/{item_id}/resolve")
async def resolve_inbox(item_id, request: InboxResolveRequest, settings = Depends(get_settings)):
    path = settings.memory_path / "inbox" / f"{item_id}.md"
    if not path.exists(): raise HTTPException(404, ...)
    parsed = markdown_parser.parse(path)
    kind = parsed.frontmatter.get("kind", "decay")
    entity_id = parsed.frontmatter.get("entity_id", "")

    if kind == "decay":
        entity_id = await _resolve_decay(path, parsed, request, settings)      # ports nudges.py decay branch
    elif kind == "conflict":
        entity_id = await _resolve_conflict(path, parsed, request, settings)   # NEW: LLM synthesis (§7)
    elif kind in ("clarification", "merge_suggestion"):
        entity_id = await _resolve_clarification(path, parsed, request, settings)  # ports clarifications.py logic verbatim
    else:
        raise HTTPException(400, f"Unknown kind {kind}")

    if request.action == "skip":          # skip never deletes, returns early inside helper
        return {"status": "skipped", "id": item_id}
    await git_service.commit_resolution(settings.memory_path, entity_id, f"inbox/{kind}/resolved")
    return {"status": "resolved", "id": item_id}
```

`_resolve_decay`, `_resolve_clarification` are lifted directly from the current `nudges.py` / `clarifications.py` bodies (the clarification logic — answer/merge/dismiss/skip with the `source_date`/`_max_date` chronology handling — is copied unchanged; it is already correct). `_resolve_conflict` is the only new logic (§7). These three helpers move into `api/services/inbox_service.py` so the shims can call them too (see §8).

Register in `main.py`: `app.include_router(inbox.router, tags=["inbox"])`.

---

## 5. `GET /status` aggregate + avatar state

New router `api/routers/status.py` (or fold into `inbox.py`; keep it its own file for clarity):

```python
@router.get("/status", response_model=StatusResponse)
async def get_status(settings = Depends(get_settings)):
    state = get_sleep_state()
    items = _load_inbox(settings.memory_path)          # reuse inbox loader
    by_kind = Counter(i.kind.value for i in items)
    unprocessed = _count_unprocessed_episodes(settings.memory_path)
    avatar = _avatar_state(state, len(items), unprocessed)
    return StatusResponse(
        sleep_status=state.status,
        sleep_stage=state.stage,
        sleep_total_stages=state.total_stages,
        avatar_state=avatar,
        inbox_total=len(items),
        inbox_by_kind=dict(by_kind),
        unprocessed_episodes=unprocessed,
        index_warning=state.index_warning,
    )
```

`_avatar_state(state, inbox_total, unprocessed)` rules (deterministic):
1. `state.status == "running"` → `"sleeping"`.
2. `unprocessed > 0` and not running → `"ingesting"`.
3. `inbox_total >= 5` (CONFUSED_THRESHOLD const) → `"confused"`.
4. else → `"awake"`.

`_count_unprocessed_episodes` reuses `sleep_cycle._get_unprocessed_episodes` (already exists) — just `len(...)`. This is the single endpoint the menu-bar polls (replaces polling `/sleep/status` + `/nudges` + `/clarifications`).

---

## 6. Sleep pipeline writes the new format — `api/services/nudge_generator.py`

Rename intent (keep filename `nudge_generator.py` to avoid churning `sleep_cycle.py` imports, or rename to `inbox_generator.py` and update the one import in `sleep_cycle.py` line ~135). **Decision: rename to `inbox_generator.py`** and update `sleep_cycle.py`'s `from api.services.nudge_generator import generate` → `from api.services.inbox_generator import generate`. Cleaner; one import site.

### Changes inside `generate(...)`
- Write to `memory_path / "inbox"` (mkdir it).
- **Fix the ID-collision bug**: replace `_count_existing_nudges` with `_next_inbox_id(inbox_dir)` using the **max-id+1** pattern (copied from `clarification_manager._next_id`, scanning `inbox-*.md`). Compute the next id *inside the loop each time* (or seed `next_num` once from max and increment locally — both fine; the bug was deriving from `len(glob)` which resets after deletions).

```python
def _next_inbox_num(inbox_dir: Path) -> int:
    max_num = 0
    for fp in inbox_dir.glob("inbox-*.md"):
        try: max_num = max(max_num, int(fp.stem.split("-")[-1]))
        except ValueError: continue
    return max_num + 1
```

- `decay_nudge` change → write frontmatter `kind: decay, required_input: choice, status: pending, priority: <new_confidence>, options: [keep, archive, later]`-style item. `title` = `f"No recent mentions of {entity_name}"`. Body unchanged.
- `conflict_nudge` change → `kind: conflict, required_input: choice, priority: 0.8, options: change["options"]`. `title` = `f"Conflicting information about {entity_name}"`. Body = `conflict_context`.

### `clarification_manager.py`
- Point `self.dir` at `memory_path / "inbox"` (not `clarifications`).
- `_next_id()` → return `f"inbox-{n:03d}"` using the shared max-id helper over `inbox-*.md`.
- `create(...)` writes the unified frontmatter: add `kind` (`merge_suggestion` if `uncertainty_type` starts with "Possible duplicate", else `clarification`), `required_input` (`merge` vs `freetext`), `status: pending`, `priority: suggested_confidence`, `entity_id: sanitize_id(entity_name)`, `entity_name`, `title: entity_name`. Keep existing `uncertainty_type`, `suggested_classification`, `suggested_confidence`, `source_episode`, `source_episode_timestamp`, `created_date`.
- `_existing_for` / `check_organic_resolution` now scan `inbox/` but must **only match clarification/merge_suggestion kinds** (add `if fm.get("kind") not in ("clarification","merge_suggestion"): continue`) so a decay item about the same entity isn't treated as a dup clarification.

`sleep_cycle._finalize` / `_infer_trigger_for_path`: add `if path.startswith("inbox/"): return "sleep/inbox_generation"`. Keep the old `nudges/`/`clarifications/` branches for safety (they become dead once migration runs but harmless).

---

## 7. Bug fix: conflict resolution must synthesize, not raw-append

Current (`nudges.py` line ~77): `body = entity.body + f"\n\n{request.answer}"` — appends the user's answer as a disconnected paragraph.

**Fix** in `_resolve_conflict` (inbox_service): reuse the existing Stage-3 synthesizer `conflict_resolver._synthesize_entity_update`. The user's adjudication is fed in as the new authoritative description.

```python
from api.services.conflict_resolver import _synthesize_entity_update

async def _resolve_conflict(path, parsed, request, settings):
    entity_id = parsed.frontmatter.get("entity_id", "")
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    answer = (request.answer or "").strip()
    if entity_path.exists() and answer:
        entity = markdown_parser.parse(entity_path)
        fm = entity.frontmatter
        new_body = await _synthesize_entity_update(
            entity_name=fm.get("name", entity_id),
            entity_type=fm.get("type", "concept"),
            existing_body=entity.body,
            new_description=answer,          # the user's resolution becomes the authoritative fact
            new_history_entries=[],
            source_reference_date=str(date.today()),
            settings=settings,
        )
        if not new_body:                     # synthesis failed -> safe fallback (still better than raw append: dedup guard)
            new_body = entity.body.rstrip() + f"\n\n{answer}" if answer not in entity.body else entity.body
        fm["last_referenced"] = str(date.today())
        fm["version"] = int(fm.get("version", 1) or 1) + 1
        markdown_parser.write(entity_path, fm, new_body)
    path.unlink()
    return entity_id
```

This makes a conflict adjudication update the description coherently (preferring the user's choice, moving the contradicted fact into `## History`) exactly like a Sleep-cycle update, instead of accreting paragraphs. Note `_synthesize_entity_update` is currently "private"; we either drop the underscore or import it as-is (Python allows it). **Decision: import as-is** to avoid touching `conflict_resolver` signatures.

---

## 8. Backward-compat shims — `api/routers/nudges.py`, `api/routers/clarifications.py`

Rewrite both as thin projections over `inbox/`. They keep their existing route paths and response models so the SwiftUI app and any external caller keep working during migration.

- `GET /nudges` → load `inbox/`, filter `kind in (decay, conflict)`, project each to `NudgeResponse` (`type=kind`, `short_description=title`, `full_context=body`, `options`, `entity_name`, `entity_id`, `created_date`). (Note: legacy `clarification` NudgeType value is now dead — fine, no item is ever that kind in the nudge projection.)
- `POST /nudges/{id}/resolve` → look up `inbox/{id}.md`, call the shared `inbox_service` resolver, return `{"status":"resolved","nudge_id": id}`.
- `GET /clarifications` → load `inbox/`, filter `kind in (clarification, merge_suggestion)`, project to `ClarificationResponse` (`entity_mention=entity_name`, `uncertainty_type`, `source_context=body`, `suggested_classification`, `suggested_confidence`, `created_date`).
- `POST /clarifications/{id}` → shared resolver, return `{"status":"resolved","clarification_id": id}`.

Add a deprecation header (`response.headers["Deprecation"] = "true"`) or a one-line docstring `# DEPRECATED: use /inbox`. No behavior change for callers.

Because IDs are now all `inbox-NNN`, the legacy endpoints address items by their new id. The SwiftUI app fetches via `/inbox` post-migration, so it never sends old `nudge-NNN`/`clar-NNN` ids; the shims are for resilience, not for the app's happy path.

---

## 9. MCP server — `mcp/server.py`

`cicada_check_nudges` and the proactive recall path read the unified dir.

- `_relevant_nudges` + `_relevant_clarifications` → collapse into one `_relevant_inbox(memory_path, query) -> list[str]` that scans `inbox/*.md`, formats per-kind:
  - decay/conflict: `- [{kind}] **{entity_name}** — {title}`
  - clarification/merge_suggestion: `- **{entity_name}** (uncertain: {uncertainty_type}, suggested: {suggested_classification})`
- `handle_check_nudges(topic)` → scan only `inbox/`. Keep the tool name `cicada_check_nudges` (avoid breaking registered MCP clients) but update its description to "pending inbox items". Output header: `Found {n} pending inbox items:`.
- In `cicada_recall` (Pass 1), the two blurb sections (`Pending nudges…` / `Pending clarifications…`) → one `**Pending inbox items relevant to this query:**` section.
- Add a fallback: if `inbox/` doesn't exist yet (pre-migration in a stale checkout) but `nudges/`/`clarifications/` do, still scan those — keeps the MCP server correct before the API has run migration once. Small `_inbox_dirs(memory_path)` returns `[inbox]` if it exists else `[nudges, clarifications]`.

---

## 10. One-time idempotent migration at API startup

New `api/services/inbox_migration.py`, called from `main.py` lifespan **before** the entities-count log, after git-init.

```python
def migrate_to_inbox(memory_path: Path) -> int:
    inbox = memory_path / "inbox"; inbox.mkdir(parents=True, exist_ok=True)
    marker = inbox / ".migrated"
    moved = 0
    next_num = _next_inbox_num(inbox)              # continue numbering after any already-migrated items
    # nudges/*.md
    for fp in sorted((memory_path / "nudges").glob("*.md")):
        fm, body = parse(fp)
        new_fm = _nudge_to_inbox_fm(fm)            # kind from fm["type"]; required_input by kind; title=short_description; priority
        write(inbox / f"inbox-{next_num:03d}.md", new_fm, body); next_num += 1
        fp.unlink(); moved += 1
    # clarifications/*.md
    for fp in sorted((memory_path / "clarifications").glob("*.md")):
        fm, body = parse(fp)
        new_fm = _clar_to_inbox_fm(fm)             # kind merge_suggestion if uncertainty_type startswith "Possible duplicate" else clarification
        write(inbox / f"inbox-{next_num:03d}.md", new_fm, body); next_num += 1
        fp.unlink(); moved += 1
    marker.write_text("v1")
    return moved
```

**Idempotency**: guard the whole function with `if marker.exists(): return 0` AND the per-file loops only act on files still present in the legacy dirs. Running twice does nothing (legacy dirs are emptied, marker set). Safe to call every startup.

**No data loss**: items are *moved* (read → write new → unlink old) inside the same git repo; the migration itself is committed by the next resolution/sleep commit, or we can commit it explicitly: after migration, if `moved > 0`, run `git_service.commit_changes(memory_path, "Migrate nudges + clarifications into unified inbox/\n\n<manifest>")`. **Decision: commit it** so the move is captured as a provenance event and the legacy file deletions are recorded.

`main.py` lifespan: change the mkdir loop to include `"inbox"`, then:
```python
from api.services.inbox_migration import migrate_to_inbox
moved = migrate_to_inbox(settings.memory_path)
if moved: logger.info(f"Migrated {moved} legacy items into inbox/")
```

---

## 11. Bug fix: resolution commits in sleep history

`git_service.get_sleep_history` filters `subject.lower().startswith("sleep cycle")`, so `commit_resolution`'s single-line `entities/X.md: updated (trigger: …)` never shows in the Sleep dashboard.

**Fix** `git_service.commit_resolution` to emit a structured, multi-line message whose subject the history filter recognizes. Two coordinated edits:

1. `commit_resolution(memory_path, entity_id, trigger)` →
   ```python
   date_str = date.today().isoformat()
   message = (f"Inbox resolution {date_str}\n\n"
              f"entities/{entity_id}.md: updated (trigger: {trigger})")
   await commit_changes(memory_path, message)
   ```
2. `get_sleep_history` filter → accept both prefixes:
   ```python
   subj = subject.lower()
   if subj.startswith("sleep cycle") or subj.startswith("inbox resolution"):
   ```
   And in the `SleepHistoryEntry` the message is the subject line, which now reads "Inbox resolution 2026-…", clearly distinguishable in the dashboard from a full Sleep cycle. (Optionally tag `kind` into the subject: `Inbox resolution (conflict) 2026-…` — `commit_resolution` already receives `inbox/{kind}/resolved` as trigger; parse the kind for the subject.)

This makes every nudge/clarification/conflict resolution appear chronologically in `GET /sleep/history`, fixing the provenance gap.

---

## 12. SwiftUI — collapse two tabs into one Inbox

### Models — new `Models/InboxItem.swift`
```swift
enum InboxKind: String, Codable { case decay, conflict, clarification, mergeSuggestion = "merge_suggestion" }
enum RequiredInput: String, Codable { case none, choice, freetext, merge }

struct InboxItem: Identifiable, Codable {
    let id: String
    var kind: InboxKind
    var requiredInput: RequiredInput
    var status: String
    var priority: Double
    var entityId: String
    var entityName: String
    var title: String
    var body: String
    var options: [String]?
    var createdDate: String
    var uncertaintyType: String?
    var suggestedClassification: String?
    var suggestedConfidence: Double?
    var mergeTargetHint: String?
}
```
Color/icon per kind (port from `NudgeType`/`Clarification`): decay amber `0xF59E0B`, conflict red `0xEF4444`, clarification indigo `0x7C8FFF`, mergeSuggestion yellow `0xEAB308`.

Keep `Nudge.swift`/`Clarification.swift` until the views are deleted (compile safety), then remove.

### ViewModel — new `ViewModels/InboxViewModel.swift`
`@Observable` with `items: [InboxItem]`, `pendingCount`, `countByKind`, `loadInbox()` → `APIClient.fetchInbox()`, `resolve(id:action:answer:mergeTarget:)` → `APIClient.resolveInboxItem(...)` then `items.removeAll { $0.id == id }` (except `skip`, which reloads). Replaces both `NudgeViewModel` and `ClarificationViewModel`.

### APIClient additions
```swift
func fetchInbox() async throws -> [InboxItem] { try await get("/inbox") }
func resolveInboxItem(id: String, action: String, answer: String? = nil, mergeTarget: String? = nil) async throws {
    var body: [String: Any] = ["action": action]
    if let answer { body["answer"] = answer }
    if let mergeTarget { body["mergeTarget"] = mergeTarget }
    try await post("/inbox/\(id)/resolve", body: body)
}
func fetchStatus() async throws -> StatusResponse { try await get("/status") }
```
Add `StatusResponse: Codable` mirroring §3 (camelCase keys).

### Views
- New `Views/Inbox/InboxListView.swift` + `Views/Inbox/InboxCardView.swift`. One card with a `switch item.requiredInput` (or `item.kind`) action row:
  - `choice` decay → Keep / Archive / Remind later.
  - `choice` conflict → one button per `options[]`, each posts `action:"resolve", answer:<option>`; plus a freetext "Other…" fallback.
  - `freetext` clarification → TextField + Answer (posts `action:"answer", answer:`), Dismiss, Skip. **Fixes the known SwiftUI bug** where the old `NudgeCardView` `.clarification` Submit ignored `clarificationText` and sent `action:"archive"` — here Submit sends the typed answer.
  - `merge` mergeSuggestion → Answer (freetext) / Merge (with `mergeTargetHint` prefilled, posts `merge_target`) / Dismiss / Skip.
- Delete `Views/Nudges/*`, `Views/Clarifications/*` after the Inbox view compiles.

### Sidebar — `SidebarView.swift` + `ContentView.swift`
- `AppTab`: replace `.nudges` + `.clarifications` with a single `.inbox = "Inbox"` (icon `tray.full`). Badge = `inboxVM.pendingCount`.
- `ContentView` swaps the two tab destinations for one `InboxListView(viewModel: inboxVM)`.

### Menu-bar tamagotchi — `MenuBarManager.swift`
- Drive `CicadaStatus` from `GET /status` `avatarState` (poll every ~10s via a `Timer` or the existing `SleepViewModel` tick). Map `awake/sleeping/ingesting/confused` 1:1 to the existing `CicadaStatus` cases.
- Show `inbox_total` as a count in the menu header (`"Inbox: \(n) pending"`). The pixel-art sprite swap is a separate axis; this axis just wires the *state source* to `/status` so that axis has clean data.

---

## 13. Implementation step list (ordered, single dev)

1. **schemas.py**: add `InboxKind`, `RequiredInput`, `InboxItem`, `InboxResolveRequest`, `StatusResponse`. Keep legacy models.
2. **services/inbox_service.py** (new): `load_inbox()`, `next_inbox_num()`, `_resolve_decay`, `_resolve_clarification` (lifted verbatim from current routers), `_resolve_conflict` (NEW, §7 synthesis).
3. **routers/inbox.py** (new): `GET /inbox`, `POST /inbox/{id}/resolve` dispatching via inbox_service.
4. **routers/status.py** (new): `GET /status` (§5), avatar-state computation.
5. **services/inbox_migration.py** (new): `migrate_to_inbox` (§10), idempotent, commits the move.
6. **services/nudge_generator.py → inbox_generator.py** (rename): write `inbox/` with unified frontmatter; replace `_count_existing_nudges` with `_next_inbox_num` (max-id+1 fix). Update import in `sleep_cycle.py`.
7. **services/clarification_manager.py**: dir → `inbox/`, ids → `inbox-NNN`, write unified frontmatter, kind-filter in `_existing_for`/`check_organic_resolution`.
8. **services/conflict_resolver.py**: no change needed (we import `_synthesize_entity_update`); optionally rename to public `synthesize_entity_update`.
9. **services/git_service.py**: `commit_resolution` → structured "Inbox resolution" message; `get_sleep_history` filter accepts that prefix (§11).
10. **services/sleep_cycle.py**: `_infer_trigger_for_path` add `inbox/` branch.
11. **routers/nudges.py / clarifications.py**: rewrite as shims over inbox_service (§8).
12. **main.py**: add `"inbox"` to mkdir loop; call `migrate_to_inbox`; `include_router(inbox.router)` and `status.router`.
13. **mcp/server.py**: unify to `inbox/` scan with legacy fallback; keep tool name (§9).
14. **SwiftUI**: `InboxItem`/`StatusResponse` models, `InboxViewModel`, APIClient methods, `InboxListView`/`InboxCardView`, sidebar single tab, menu-bar `/status` wiring; fix the clarification-submit bug; delete old views/VMs/models last.
15. **Verify**: `python -c "import api.main"`; run uvicorn, hit `GET /inbox` (expect 72 items post-migration: 39+33), `GET /status`, resolve one of each kind, confirm `GET /sleep/history` shows the "Inbox resolution" commit; `swift build` in `app/CicadaApp`.

---

## 14. Migration math / verification expectations

- Pre: `nudges/` 39 files, `clarifications/` 33 files.
- Post first startup: `inbox/` 72 files `inbox-001.md … inbox-072.md`, `.migrated` marker, legacy dirs empty, one git commit "Migrate nudges + clarifications into unified inbox/".
- Idempotent: second startup moves 0, no commit.
- `GET /inbox` → 72 `InboxItem`s; `GET /status` → `inboxTotal: 72`, `inboxByKind` ≈ `{decay: 39, clarification: N, merge_suggestion: M}` (N+M = 33), `avatarState: "confused"` (≥5).

---

## 15. Cross-axis contracts this design assumes

- **Entity page schema** (richer-entity-pages axis): `_resolve_conflict` and `_resolve_clarification` write entity bodies via `markdown_parser.write` and reuse `conflict_resolver._synthesize_entity_update`. If that axis changes the synthesis prompt to emit structured `## Summary / ## History / ## Related` sections, conflict resolution inherits it for free — no change here. The inbox does **not** define entity body structure; it delegates to the synthesizer.
- **Hub axis**: `merge_suggestion` items reference `merge_target` entity slugs; if hubs introduce a `hub` entity type, merge targets must still be leaf entities (a hub is never a merge target). No schema collision (`entity_id` is just a slug).
- **Menu-bar / graph-viz axis**: consumes `GET /status` `avatarState` + `inboxByKind`. This spec owns `/status`; that axis owns the sprite rendering. Contract = the `StatusResponse` shape in §3.
- **Sleep-pipeline axis**: `inbox_generator.generate(changes, skills, memory_path, relationships)` keeps the exact signature `sleep_cycle` calls today (only the dir and id logic change internally).
- **Media-ingestion axis**: leaves room for a future `kind: media_suggestion` ("you saved this reel about X — link it?") with `required_input: choice`. No schema change needed — `InboxKind` enum just gains a value, the dispatcher gains a branch.
