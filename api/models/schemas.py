from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


# --- Enums ---


class EntityType(str, Enum):
    person = "person"
    project = "project"
    company = "company"
    concept = "concept"
    tool = "tool"
    deadline = "deadline"
    skill = "skill"
    location = "location"
    media = "media"
    # G18 — a filesystem folder/path, split out from `location` (a physical
    # place). Stage-1 classifies a PATH (`/Users/...`, `~/...`) as `directory`.
    directory = "directory"


# Types Stage-1 extraction may PRODUCE. This is intentionally a SUBSET of the
# full ``EntityType`` enum: the enum still ACCEPTS every legacy value so the old
# graph parses/renders unchanged, but the producible set is what the extraction
# prompt offers the model.
#
# Excluded from producible (G17): ``deadline`` — due-dates are now attached as a
# ``due`` claim/relationship on the relevant project/task instead of spawning a
# standalone deadline entity. Legacy ``deadline`` pages stay valid (still in the
# enum) and are never rewritten.
# Excluded: ``media`` is produced by the media-ingestion path, not by Stage-1
# conversation extraction.
PRODUCIBLE_ENTITY_TYPES = frozenset(
    {
        EntityType.person,
        EntityType.project,
        EntityType.company,
        EntityType.concept,
        EntityType.tool,
        EntityType.skill,
        EntityType.location,
        EntityType.directory,
    }
)


class EntityStatus(str, Enum):
    active = "active"
    decaying = "decaying"
    archived = "archived"
    dropped = "dropped"


class DecayClass(str, Enum):
    """How fast a belief about a life should fade when it stops being mentioned (G66).

    Decay models "absence of mention is a signal" for *beliefs*. A bookmark is an
    *artifact*, not a belief — it does not become less true by going unmentioned,
    so it is ``evergreen`` and never decays at all.
    """

    evergreen = "evergreen"   # never fades — artifacts (media/bookmarks) + user pins
    durable = "durable"       # fades slowly — stable preferences, skills, long-lived concepts
    active = "active"         # the default for a belief about the user's life
    volatile = "volatile"     # expected to change within weeks (role, status, current focus)


# Per-week confidence drop used by the ENTITY decay engine
# (``conflict_resolver.resolve_and_prune``).
DECAY_CLASS_RATES: dict[DecayClass, float] = {
    DecayClass.evergreen: 0.0,
    DecayClass.durable: 0.02,
    DecayClass.active: 0.05,
    DecayClass.volatile: 0.15,
}

# Multiplier applied to the CLAIM decay engine's per-epistemic x source_trust
# rate (``claim_reconciler._decay_claims``), keyed by the SUBJECT entity's class.
# An evergreen subject's claims never decay (0.0).
CLAIM_DECAY_MULTIPLIERS: dict[DecayClass, float] = {
    DecayClass.evergreen: 0.0,
    DecayClass.durable: 0.5,
    DecayClass.active: 1.0,
    DecayClass.volatile: 2.0,
}

# ANTI-POLLUTION RAIL, mirroring ``PRODUCIBLE_ENTITY_TYPES`` above: Stage-1
# extraction may PROPOSE only these three. ``evergreen`` is reserved for the
# ingest writers and for the user, so an over-eager extractor can never stop the
# graph from archiving.
AGENT_PRODUCIBLE_DECAY_CLASSES: frozenset[DecayClass] = frozenset(
    {DecayClass.durable, DecayClass.active, DecayClass.volatile}
)


class NudgeType(str, Enum):
    decay = "decay"
    conflict = "conflict"
    clarification = "clarification"


# --- Entity ---


class DiffLine(CamelModel):
    """One row of a unified diff for an entity file (G69).

    ``kind`` is one of ``context`` / ``add`` / ``remove`` / ``hunk``. Line
    numbers are 1-based and follow git's own accounting: a ``context`` row
    carries both, an ``add`` row only ``new_line``, a ``remove`` row only
    ``old_line``, and a ``hunk`` row (whose ``text`` is the raw ``@@ … @@``
    header) carries neither. Serialized camelCase (``oldLine`` / ``newLine``).
    """

    kind: str
    old_line: Optional[int] = None
    new_line: Optional[int] = None
    text: str = ""


class EntityDiff(CamelModel):
    # G69: ``lines`` is the real, ordered unified diff — additions, removals AND
    # the unchanged context around them, each with its old/new line number, so
    # the app can render a GitHub-style interleaved view instead of two blocks.
    # Capped at DIFF_MAX_CONTEXT_LINES.
    #
    # ``added`` / ``removed`` are the pre-G69 newline-joined blocks, KEPT for
    # back-compat: an older app build (and any client decoding a cached payload)
    # still renders from them. git_service caps each side at DIFF_MAX_LINES so
    # the response can't explode on a huge rewrite; when either cap is hit a
    # truncation marker is appended to the affected side and ``truncated`` is set
    # so the client can show "diff clipped".
    added: str = ""
    removed: str = ""
    # ``truncated`` is the UNION flag — true when ANY of the three sinks was
    # clipped — and keeps its exact pre-G69 meaning for the two flat blocks.
    # ``lines_truncated`` is specifically "the ORDERED list was cut", which is
    # what a client rendering ``lines`` must show its "diff clipped" banner on:
    # a 500-addition commit clips the 400-cap flat side while ``lines`` is
    # whole, and a banner driven by ``truncated`` would sit above a complete
    # diff claiming it was shortened.
    truncated: bool = False
    lines: list[DiffLine] = Field(default_factory=list)
    lines_truncated: bool = False


class EntityHistoryEntry(CamelModel):
    date: str
    change_type: str
    description: str
    # Commit-level provenance (M3 / backlog A2). ``author`` is the model id that
    # wrote this commit (e.g. "gpt-5.4-mini") or "user" for manual/companion-app
    # writes, parsed from the commit's ``Cicada-Author:`` trailer; "unknown" for
    # legacy untrailered commits. ``commit_hash`` enables an on-demand per-commit
    # diff fetch. ``diff`` is populated only when history is requested with
    # ``include_diff=true`` (kept opt-in so the default response stays small).
    author: str = "unknown"
    commit_hash: str = ""
    diff: Optional[EntityDiff] = None
    # G48: the conversation(s) that produced THIS ENTITY's change at this
    # commit. PR #20 review fix: precise when derivable — parsed from the
    # entity's own manifest line (`git_service._parse_entity_sessions`), which
    # a batched Sleep cycle (multiple conversations in one commit) stamps per
    # entity from only the episode(s) that touched it — falling back to the
    # commit-wide ``Cicada-Session:`` trailers only when no precise per-entity
    # data exists (a decay/archive change with no episode, or a pre-fix
    # commit). Empty for every pre-G48 commit and for user-action writes, so
    # the app's "from conversation" affordance simply doesn't render there.
    sessions: list[str] = []


# --- Contributors (git-trailer attribution, backlog A2) ---


class Contributor(CamelModel):
    # An authoring agent: a model id (e.g. "gpt-5.4-mini"), "user", or "unknown".
    author: str
    commit_count: int = 0
    file_count: int = 0
    entity_count: int = 0
    files: list[str] = []
    last_active: str = ""  # ISO date (YYYY-MM-DD) of the author's most recent commit
    # G15 — visual identity (all additive + defaulted, so the wire stays
    # backward-compatible with older clients that don't decode them).
    # ``kind``: "user" for the literal `user` author, "system" for the literal
    # `cicada` author (maintenance with no model and no user in the loop —
    # R-L6), "unknown" for legacy untrailered commits, "model" for every model
    # id. ``provider`` is who billed for the model, derived from the id: a
    # router when the id names one before its first slash (openrouter/ollama —
    # R9), else the model's company, else "other"; None for
    # user/system/unknown. ``avatar_url`` is the user's GitHub profile picture
    # (https://github.com/<handle>.png) for the `user` author when a handle is
    # known; None for model/system/unknown (rendered client-side).
    #
    # Both stay plain strings: R-L6 added VALUES, never a shape, so an older
    # client decodes a `system` row unchanged and renders it through its
    # `default:` branch (today's behaviour) rather than failing to decode.
    kind: str = "unknown"  # "user" | "system" | "model" | "unknown"
    # "openai" | "anthropic" | "google" | "meta" | "mistral" | "deepseek"
    # | "qwen" | "openrouter" | "ollama" | "other" | None
    provider: Optional[str] = None
    avatar_url: Optional[str] = None


class ContributorCommit(CamelModel):
    """One commit attributed to a contributor (G67 §2.2).

    ``entities`` are the entity ids (file STEMS) this commit touched, so the app
    can render a chip per entity and fetch that entity's diff at this commit
    from ``GET /entities/{id}/history/{commit}/diff``. ``files_changed`` is a
    COUNT of every changed path (entities and everything else) — the ids
    themselves are already in ``entities``.

    ``entities`` is CAPPED (``git_service.MAX_COMMIT_ENTITIES``): a real Sleep
    cycle touches hundreds of pages (895 in one live commit) and the app lays
    out one tappable chip per id, so an uncapped list is a payload and a
    render-time blow-up. ``entities_total`` is the true count, so the app can
    render "+N more" honestly instead of silently under-reporting.
    """

    commit_hash: str
    date: str  # ISO date (YYYY-MM-DD)
    subject: str
    entities: list[str] = []
    entities_total: int = 0
    files_changed: int = 0
    # G48: same trailer, same contract as EntityHistoryEntry.sessions.
    sessions: list[str] = []


class ContributorCommitsResponse(CamelModel):
    author: str
    commits: list[ContributorCommit] = []


class ContributorsResponse(CamelModel):
    contributors: list[Contributor] = []


class TopEntityWrite(CamelModel):
    entity_id: str
    commits: int = 0
    last_written: str = ""  # ISO date


class TopEntityRead(CamelModel):
    entity_id: str
    reads: int = 0
    last_read: str = ""  # ISO timestamp


class TopEntities(CamelModel):
    """Most-written (git, bounded by ``git_service.TOP_ENTITIES_LOG_WINDOW`` —
    ``commits_scanned`` says how far back) and most-read (the ids-only ``read``
    ledger kind) entity pages — G124's read/write stats, all engine-free."""

    written: list[TopEntityWrite] = []
    read: list[TopEntityRead] = []
    commits_scanned: int = 0
    range: str = "all"


class EntityReadRequest(CamelModel):
    # G124 R11: the app's card open. ``mcp``/``mcp-recall`` reads are recorded
    # by the MCP server itself, never posted through this route.
    surface: Literal["app", "mcp"] = "app"


class EntityReadResponse(CamelModel):
    recorded: bool


# --- Origins (capture-provenance aggregation) ---


class OriginStat(CamelModel):
    # Capture origin stamped in episode frontmatter (e.g. "mcp", "telegram",
    # "chrome-bookmark", "safari-bookmark", "claude-export"), or "unknown"
    # when an episode predates the origin field / never got one stamped.
    origin: str
    episode_count: int = 0
    entity_count: int = 0
    last_seen: str = ""  # ISO timestamp of the most recent episode for this origin


class OriginsResponse(CamelModel):
    origins: list[OriginStat] = []


# --- Sources overview (G124 — one card per memory source) ---


class SourceOverview(CamelModel):
    """One memory source as the Sources page shows it.

    ``id`` equals the ``GET /sources/channels`` id where the source is a
    channel (so the app joins channel state by equality), ``harness:<name>``
    for an MCP harness, ``origin:<id>`` for an origin the catalog does not
    know (see ``source_overview.CATALOG``). ``kind`` is one of
    ``source_overview.KIND_ORDER``. ``mark`` is an ``OriginIconography`` key.
    Counts are engine-free: episodes/entities from frontmatter (entities via
    ``source_episodes`` only — R3), conversations = distinct ``session_id`` /
    ``source_id``, items = the channel's own count. ``origins`` and
    ``harness`` are the filter values the app sends back (``GET /sources``
    items by origin; ``GET /conversations/recent?harness=``).
    """

    id: str
    label: str
    kind: str
    mark: str
    conversations: int = 0
    episodes: int = 0
    entities: int = 0
    items: int = 0
    last_activity_at: Optional[str] = None
    connected: bool = False
    last_error: Optional[str] = None
    actions: list[str] = []
    channel_id: Optional[str] = None
    origins: list[str] = []
    harness: Optional[str] = None
    # R-A16 — captures per UTC calendar day for the last
    # ``source_overview.ACTIVITY_DAYS`` days, SPARSE (a silent day has no
    # key). Absolute date keys rather than a rolling array so a 304'd payload
    # renders a day short instead of a day shifted. Rides the existing
    # `episodes` ETag component; no `VersionVector` change is owed.
    activity: dict[str, int] = Field(default_factory=dict)


class SourceOverviewResponse(CamelModel):
    sources: list[SourceOverview] = []


# --- Conversations (G48 conversation-level provenance) ---------------------


class ConversationSummary(CamelModel):
    """One conversation that wrote to memory — a live MCP session or an
    imported chat thread.

    ``conversation_id`` is the stamped ``session_id`` (kind ``"mcp"``) or G20's
    ``source_id`` (kind ``"import"``). ``entity_ids`` is CAPPED
    (``session_stats.MAX_CONVERSATION_ENTITIES``) with the honest total in
    ``entity_count``, so the app can say "+N more". ``project_dir`` is
    deliberately absent — it is returned only by the resume endpoint, which
    needs a cwd to launch. ``resumable`` is computed per request and never
    persisted.

    ``model`` is RESERVED and always ``None`` in this slice: nothing that
    writes memory records a model against a conversation id yet, so it would be
    a structurally-null join (see ``session_stats.project_conversation``). It
    stays on the wire — the app already decodes it — for when engine calls
    carry session refs (G49).
    """

    conversation_id: str
    kind: str = "mcp"  # "mcp" | "import"
    harness: str = ""
    origin: str = ""
    title: str = ""
    first_seen: str = ""
    last_seen: str = ""
    episode_count: int = 0
    entity_ids: list[str] = []
    entity_count: int = 0
    model: Optional[str] = None
    resumable: bool = False


class ResumeDescriptor(CamelModel):
    """How to reopen a conversation. The BACKEND validates; the APP launches.

    ``argv`` is a fixed list — never a shell string — whose head is the literal
    binary name ``claude`` (never API-configurable). ``cwd`` is present only
    when the stamped ``project_dir`` passed a conservative charset gate AND
    still exists; the app falls back to ``$HOME`` when it is null.
    """

    mode: str = "terminal"
    argv: list[str] = []
    cwd: Optional[str] = None
    display_command: str = ""


class EntityMedia(CamelModel):
    """Structured media metadata for a ``type: media`` entity (G11).

    Mirrors the nested ``media:`` frontmatter block written by
    ``media_ingestor.write_media_entity`` so the companion app's media-preview UI
    (EntityDetailCard / Feed) can render an image / video player / OG link card
    without re-parsing ``raw_markdown`` client-side. ``description`` is lifted
    from the entity body's ``## Summary`` section (not stored in frontmatter).
    Everything except ``url``/``mediaType`` is optional — a bare bookmark may
    carry no OG metadata. This block is ``None`` for every non-media entity, so
    the wire stays backward-compatible (additive + defaulted).
    """

    url: str
    media_type: str
    site: Optional[str] = None
    channel: Optional[str] = None
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    # Track V (R-V2) — the two video keys from the page's `media:` block, both
    # additive + defaulted so an older page (which carries neither) decodes
    # unchanged and no ETag INPUT moves: these only ever appear on a page
    # written after Track V, and writing that page already moves the
    # `entities` component every media ETag is computed from. `provider` is
    # redundant with what the app derives from the URL at read time (R-V1) and
    # is never trusted over it; `duration_s` is the one thing a URL cannot
    # tell you, and is absent — never estimated — when no provider stated it
    # (R17).
    provider: Optional[str] = None
    duration_s: Optional[int] = None


class EntityResponse(CamelModel):
    id: str
    name: str
    type: EntityType
    status: EntityStatus
    confidence: float
    created: str
    last_referenced: str
    decay_rate: float
    # G66 — the semantic decay class beside the numeric rate. Additive +
    # defaulted so an older client that doesn't decode it is unaffected, and a
    # legacy page with no `decay_class:` still gets a resolved value.
    decay_class: DecayClass = DecayClass.active
    source_episodes: list[str]
    tags: list[str]
    related: list[str]
    version: int
    markdown_content: str
    # Verbatim file content (frontmatter + body) for the Source view in the
    # companion app — transparency over reconstruction.
    raw_markdown: str = ""
    history: list[EntityHistoryEntry]
    # Structured media metadata for ``type: media`` entities (G11); ``None`` for
    # every other entity. Populated from the nested ``media:`` frontmatter block.
    media: Optional[EntityMedia] = None
    # G117 — mirrors GraphNode.is_owner (same `owner:` frontmatter key), so
    # the detail card can render "Name (you)" without a second lookup.
    is_owner: bool = False


class EntityDecayUpdate(CamelModel):
    """Body of ``PUT /entities/{id}/decay`` — the user's decay override (G66).

    The field is named ``decay_class`` (``class`` is a Python keyword); the
    camelCase alias ``decayClass`` is what the app sends, and
    ``populate_by_name`` means a snake_case body works too. Pydantic rejects
    anything outside the ``DecayClass`` enum with a 422.
    """

    decay_class: DecayClass


# --- Location listing (#7 — show a location entity's directory contents) ---


class LocationEntry(CamelModel):
    """One immediate child of a location entity's declared directory.

    ``size`` is ``st_size`` in bytes for files, ``0`` for directories. File
    contents are NEVER read — only stat metadata.
    """

    name: str
    is_dir: bool = False
    size: int = 0


class LocationListing(CamelModel):
    """Safe immediate-children listing for a ``type: location`` entity.

    The ``path`` is read from the entity itself (frontmatter ``path:`` if present,
    else a path detected in the body) — never from the request — so there is no
    arbitrary-path traversal. ``exists``/``accessible`` degrade gracefully:
    a missing path → ``exists=False``; a permission error → ``accessible=False``;
    both still 200 with empty ``entries``. ``truncated`` is set when the child
    count exceeds the bound and the list was clipped.
    """

    path: Optional[str] = None
    exists: bool = False
    accessible: bool = True
    truncated: bool = False
    entries: list[LocationEntry] = []


# --- Fact sources (G61 — "where to look this up") ---


class EntitySource(CamelModel):
    """One declared refresh source on an entity page's ``sources:`` key."""

    ref: str
    kind: str = "note"          # url | path | note
    predicate: Optional[str] = None
    added_by: str = "user"      # model id, or "user"
    added_at: str = ""


class EntitySourceCreate(CamelModel):
    """``POST /entities/{id}/sources`` body. ``kind`` is inferred when omitted."""

    ref: str
    kind: Optional[str] = None
    predicate: Optional[str] = None


class EntitySourceList(CamelModel):
    entity_id: str
    sources: list[EntitySource] = []


# --- Repo links (backlog G-repo) ---
#
# Deliberately plain BaseModel (NOT CamelModel) — the G-repo shared contract
# fixes this wire shape as snake_case JSON so the MCP tool, the router, and
# any other in-flight agent's work all match byte-for-byte. Don't swap in
# CamelModel here even though the rest of this file uses it.


class RepoWorktree(BaseModel):
    """One entry from ``git worktree list`` for a repo, declared-flag merged in.

    ``is_main`` is derived from ``--git-common-dir`` (git.py's source of
    truth), not from frontmatter. ``declared`` is True when this worktree's
    path also appears in the entity's declared ``repos[].worktrees`` list.
    """

    path: str
    branch: Optional[str] = None
    is_main: bool = False
    is_dirty: Optional[bool] = None
    declared: bool = False


class RepoLastCommit(BaseModel):
    hash: str
    author: str
    date: str
    subject: str


class RepoContext(BaseModel):
    """Live git snapshot for one declared ``repos:`` entry on an entity.

    ``status`` is one of ``ok`` | ``other_device`` | ``missing`` |
    ``not_a_repo`` | ``git_unavailable`` | ``timeout`` — only ``ok`` carries
    live data; every other status degrades the rest of the fields to
    ``None``/``[]`` rather than raising. ``stale_hint`` is populated only when
    a declared value contradicts what git actually observes (e.g. a declared
    ``default_branch`` that doesn't match the observed one).
    """

    path: str
    device: Optional[str] = None
    status: str
    exists: bool = False
    is_git_repo: bool = False
    remote: Optional[str] = None
    current_branch: Optional[str] = None
    default_branch_declared: Optional[str] = None
    default_branch_observed: Optional[str] = None
    ahead: Optional[int] = None
    behind: Optional[int] = None
    dirty_files: Optional[int] = None
    worktrees: list[RepoWorktree] = []
    last_commit: Optional[RepoLastCommit] = None
    stale_hint: Optional[str] = None


class RepoContextList(BaseModel):
    """``GET /entities/{id}/repos`` response — [] when the entity has no ``repos:`` key."""

    entity_id: str
    repos: list[RepoContext] = []


class RepoWorktreeInput(BaseModel):
    path: str
    branch: Optional[str] = None
    primary: bool = False


class RepoInput(BaseModel):
    """One ``repos:`` entry as submitted to ``PATCH /entities/{id}/repos``."""

    path: str = Field(..., min_length=1)
    device: Optional[str] = None
    remote: Optional[str] = None
    default_branch: Optional[str] = None
    worktrees: Optional[list[RepoWorktreeInput]] = None


class RepoUpdateRequest(BaseModel):
    """``repos: []`` removes the frontmatter key entirely (not written as an empty list)."""

    repos: list[RepoInput] = []


# --- Claims (M5b — the CPCG belief atom on the wire) ---


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


class ClaimModel(CamelModel):
    """One perspectival, bi-temporal claim, camelCase on the wire.

    Mirrors :class:`api.services.claims.Claim` (the in-page YAML dataclass) and
    the Swift ``Claim`` model in ``d2-companion-showcase.md`` §0 exactly — every
    field that doc's ``Claim`` decodes is emitted here so the macOS app decodes
    one shape across the claims / timeline / transclude surfaces. ``observer`` is
    a plain wire string (``agent`` | ``rodrigo`` | ``external:<name>``); the app
    parses it into its closed-core-plus-open-tail ``Observer`` enum.
    """

    id: str
    text: str
    subject: str = ""
    predicate: str = ""
    object: str = ""
    object_kind: str = "node"
    observer: str = "agent"
    context: str = "general"
    epistemic: str = "explicit"
    source_trust: str = "agent_extracted"
    confidence: float = 0.0
    valid_from: str = ""
    valid_to: Optional[str] = None
    superseded_by: Optional[str] = None
    supersedes: Optional[str] = None
    source_episodes: list[str] = []
    premises: list[str] = []
    authored_by: str = "unknown"
    origin: Optional[str] = None
    # G118 slice 1 — additive; an older app build ignores the key (R10).
    evidence: list[EvidenceModel] = []


class ClaimListResponse(CamelModel):
    claims: list[ClaimModel] = []


class ClaimTimeline(CamelModel):
    """One ``(subject, predicate, context)`` key's claims, newest first.

    Includes superseded claims (this is the historical/contradiction view), so
    the companion ``BeliefTimelineView`` can draw the ``superseded_by`` chain and
    the validity-bar strip.
    """

    subject: str
    predicate: str
    context: str
    claims: list[ClaimModel] = []


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


class TransclusionPayload(CamelModel):
    """Resolved ``![[…]]`` embed. ``resolved=False`` → render a soft "not found".

    ``kind`` is ``entity`` | ``facet`` | ``claim``. For an entity/facet, ``summary``
    is the generated one-liner; ``claims`` carries the facet/claim slice (``[]``
    for a bare entity).
    """

    kind: str = "entity"
    ref: str = ""
    title: str = ""
    summary: str = ""
    claims: list[ClaimModel] = []
    resolved: bool = False


# --- Graph ---


class GraphNode(CamelModel):
    id: str
    name: str
    # Plain str (not EntityType) so later waves can emit node types beyond the
    # closed entity set (e.g. hub markers) without a schema break.
    type: str
    status: EntityStatus
    confidence: float
    tags: list[str] = []
    # Server-computed render flags (camelCase on the wire via to_camel). All
    # additive + defaulted so old clients ignore them.
    degree: int = 0
    is_hub: bool = False
    has_pending: bool = False
    member_count: int = 0
    hub_kind: Optional[str] = None  # "type" | "tag" | None
    hub_id: Optional[str] = None    # member node -> its hub id, enables hub gravity
    # M5b claim-layer overlay fields (all additive/optional — old graph
    # consumers ignore them; the d3 graph lights up only when present). See
    # d2-companion-showcase.md §2: observer badges, context-colored facet
    # sub-nodes (isFacet/parentId/context). ``observers``/``contexts`` are the
    # distinct wire-strings asserting claims about this subject.
    observers: list[str] = []
    contexts: list[str] = []
    is_facet: bool = False
    parent_id: Optional[str] = None
    context: Optional[str] = None
    # Sync-engine fields (additive): a short body-derived preview and a
    # content fingerprint so the companion app can detect per-node changes
    # without diffing full entity bodies.
    summary: Optional[str] = None
    content_hash: str = ""
    # G59: does this entity have a *cached* logo right now? Filled from the
    # on-disk logo index only — `GET /graph` never fetches. Folded into
    # `content_hash` below so the app's delta repaints the node when a logo
    # lands (e.g. after a Sleep warm-up).
    has_logo: bool = False
    # G66: the entity's decay class, resolved server-side from frontmatter
    # (explicit key, else legacy type inference). Additive + defaulted, and
    # folded into `content_hash` below — the `has_logo` precedent — so the
    # companion app's delta repaints the node when the class changes.
    decay_class: DecayClass = DecayClass.active
    # G117 — set from the entity's own `owner: true` frontmatter
    # (`owner_identity.ensure_owner_entity`). Additive/optional: an older
    # client ignores it; the app renders "Name (you)" when true.
    is_owner: bool = False


class GraphLink(CamelModel):
    source: str
    target: str
    label: str
    # M5b: context-colored edges + click-through to a claim (additive/optional).
    context: Optional[str] = None
    claim_id: Optional[str] = None


class GraphResponse(CamelModel):
    nodes: list[GraphNode]
    links: list[GraphLink]
    # M5b: distinct observer roster across the graph, so the observer filter bar
    # can populate its segments without a second call. Additive/optional.
    observers: list[str] = []


# --- Search ---


class SearchHit(CamelModel):
    id: str
    name: str
    type: str
    status: str
    confidence: float
    score: float = 0.0
    snippet: str = ""


class SearchResponse(CamelModel):
    results: list[SearchHit]


# --- Ask (auditable NL synthesis over memory) ---


class AskRequest(CamelModel):
    query: str
    top_k: int = Field(default=6, ge=1, le=50)


class AskCitation(CamelModel):
    entity_id: str
    entity_name: str
    file_path: str
    snippet: str
    source_episodes: list[str] = []


class AskResponse(CamelModel):
    answer: str
    confidence: float
    citations: list[AskCitation] = []
    # The flagship gap-analysis field: explicit "what I could not answer".
    gaps: list[str] = []
    used_entities: list[str] = []


# --- Entity context (progressive disclosure) ---


class ContextNeighbor(CamelModel):
    id: str
    name: str
    type: str
    confidence: float
    summary: str
    via: str  # "leann" | "related" | "wikilink"
    score: Optional[float] = None


class ContextEpisodeExcerpt(CamelModel):
    episode_id: str
    timestamp: str
    excerpt: str


class EntityContextResponse(CamelModel):
    id: str
    name: str
    type: str
    status: str
    confidence: float
    markdown_content: str
    hubs: list[str] = []
    neighbors: list[ContextNeighbor] = []
    episodes: list[ContextEpisodeExcerpt] = []
    next_hops: list[str] = []


# --- Nudge ---


class NudgeResponse(CamelModel):
    id: str
    entity_name: str
    entity_id: str
    type: NudgeType
    short_description: str
    full_context: str
    options: Optional[list[str]] = None
    created_date: str


class NudgeResolveRequest(CamelModel):
    action: str
    answer: Optional[str] = None


# --- Clarification ---


class ClarificationResponse(CamelModel):
    id: str
    entity_mention: str
    uncertainty_type: str
    source_context: str
    suggested_classification: Optional[str] = None
    suggested_confidence: Optional[float] = None
    created_date: str


class ClarificationResolveRequest(CamelModel):
    action: str
    answer: Optional[str] = None
    merge_target: Optional[str] = None


# --- Unified Inbox ---


class InboxKind(str, Enum):
    decay = "decay"
    conflict = "conflict"
    clarification = "clarification"
    merge_suggestion = "merge_suggestion"
    # G113 slice 3: Sleep has written these two kinds for months
    # (`inbox_generator.py`'s `divergence_nudge`/`normalization_audit`
    # branches) but `InboxKind` lacked them, so `_item_from_file` raised and
    # `load_inbox` silently dropped every such item — the user never saw the
    # question and could never answer it.
    divergence = "divergence"
    normalization = "normalization"
    # G129 slice 2: a bookmark that left the browser — keep it, or archive
    # the media entity it named. The proposal comes from the browser's own
    # diff, never from the extractor, so it carries no recommendation and its
    # verdict is always `neutral` (see `inbox_service._verdict`).
    removal = "removal"


class RequiredInput(str, Enum):
    none = "none"
    choice = "choice"
    freetext = "freetext"
    merge = "merge"


class InboxOption(CamelModel):
    """One answerable option on an inbox question (AskUserQuestion shape).

    ``age_days`` is derived at read time from ``last_referenced`` (falling back
    to ``observed_at``) — it is never persisted into the item file. G115 Phase 1:
    ``recommended`` marks the ONE option Sleep proposed (the key the G113
    ``_verdict`` scores ``agreed``); ``verdict`` is what picking this option
    would be graded as (``agreed``/``overruled``/``neutral``) — on the wire for
    agents and tests, never rendered as copy. Both are derived at read.
    """

    key: str
    label: str
    description: Optional[str] = None
    claim_id: Optional[str] = None
    observed_at: Optional[str] = None
    last_referenced: Optional[str] = None
    age_days: Optional[int] = None
    recommended: bool = False
    verdict: Optional[str] = None


class InboxCause(CamelModel):
    """Why this item exists — the conversation and sentence that raised it (G97).

    Resolved at read by ``inbox_context`` through three tiers (``tier``: the
    item's own ``source_episode`` → the freshest option claim's episode → the
    subject page's last ``source_episodes`` entry → ``none``). ``excerpt`` is a
    ±240-char window of the episode body around the mention, ``mention_offsets``
    are ``[start, end]`` pairs INTO THE EXCERPT, ``start``/``end`` are the
    mention's absolute offsets into the episode body (what
    ``GET /episodes/{id}/span`` takes). Nothing here is stored: a rewritten
    episode changes the excerpt on the next read instead of mis-highlighting.
    ``span_kind`` is ``derived`` (found by name at read) or ``asserted`` (a G118
    evidence span on the claim). Tier ``none`` serves the literal
    ``[ no source recorded ]`` — a card is never hidden for lacking a cause.
    """

    episode_id: Optional[str] = None
    timestamp: Optional[str] = None
    conversation_id: Optional[str] = None
    harness: Optional[str] = None
    origin: Optional[str] = None
    conversation_title: Optional[str] = None
    excerpt: str = ""
    mention_offsets: list[list[int]] = []
    start: Optional[int] = None
    end: Optional[int] = None
    tier: str = "none"
    span_kind: str = "derived"


class InboxItem(CamelModel):
    id: str
    kind: InboxKind
    required_input: RequiredInput
    status: str = "pending"
    priority: float = 0.0
    entity_id: str = ""
    entity_name: str = ""
    title: str
    body: str
    options: list[InboxOption] = []
    created_date: str = ""
    # G60 question object
    question: Optional[str] = None
    allow_other: bool = False
    allow_defer: bool = False
    predicate: Optional[str] = None
    hint: Optional[str] = None
    # G129 slice 2 — which sync_state channel (`chrome-bookmarks`/
    # `safari-bookmarks`) proposed this item, so the app's Deletions
    # subsection can filter `GET /inbox`'s result without a new endpoint.
    # Null for every other kind.
    channel: Optional[str] = None
    remind_after: Optional[str] = None
    updated_date: Optional[str] = None
    # clarification/merge extras (only populated for those kinds)
    uncertainty_type: Optional[str] = None
    suggested_classification: Optional[str] = None
    suggested_confidence: Optional[float] = None
    merge_target_hint: Optional[str] = None
    # G115 Phase 1 — all additive so an older app build still decodes.
    entity_type: Optional[str] = None
    source_episode: Optional[str] = None
    source_episode_timestamp: Optional[str] = None
    claim_id: Optional[str] = None
    cause: Optional[InboxCause] = None
    extractor_confidence: Optional[float] = None
    extractor_model: Optional[str] = None
    recommended_key: Optional[str] = None
    # G98: a conflict on a multi-valued predicate is shown, never asked.
    informational: bool = False


class InboxResolveRequest(CamelModel):
    action: str
    answer: Optional[str] = None
    # G60: the stable key of the chosen option ("a", "b", "both", "neither").
    # ``answer`` stays the free-text channel; both may be sent together when the
    # user picks "neither" AND types what is actually true.
    option_key: Optional[str] = None
    # G60 defer: how far out to push `remind_after` (default: settings).
    remind_days: Optional[int] = None
    merge_target: Optional[str] = None
    # #1 merge direction: the id/name the user wants to KEEP as the canonical
    # survivor. When absent (or equal to ``merge_target``), the legacy behavior
    # holds — the clarified mention is absorbed INTO the existing ``merge_target``.
    # When it names the cleaner mention instead, the surviving file is renamed to
    # the survivor's slug so a merge can go either direction.
    merge_survivor: Optional[str] = None


# --- Status aggregate (menu-bar / tamagotchi) ---


class StatusSleep(CamelModel):
    status: str
    stage: int = 0
    total_stages: int = 5
    cycle_id: Optional[str] = None
    error: Optional[str] = None


class StatusInbox(CamelModel):
    total: int = 0
    by_kind: dict[str, int] = {}


class StatusEpisodes(CamelModel):
    unprocessed: int = 0
    last_ingested_at: Optional[str] = None


class StatusResponse(CamelModel):
    sleep: StatusSleep
    inbox: StatusInbox
    episodes: StatusEpisodes
    last_sleep_at: Optional[str] = None
    next_sleep_at: Optional[str] = None
    connections: Optional["StatusConnections"] = None


# --- Health (liveness probe for installer / doctor) ---


class HealthResponse(CamelModel):
    status: str = "ok"
    version: str
    entity_count: int
    episode_count: int
    # The *resolved* embedding mode after openai->local auto-degrade, so the
    # installer/doctor can confirm the offline path is actually active.
    embedding_mode: str
    memory_path: str
    # The raw *configured* root (Settings.memory_root / CICADA_MEMORY_PATH) —
    # the container of banks.yaml + banks/<name>/, distinct from memory_path
    # above (the *resolved active bank*). This is the single source of truth
    # a client should copy into a fresh `CICADA_MEMORY_PATH=...` MCP
    # registration: the app and any agent registered from this value are
    # guaranteed to resolve the same bank, because both apply
    # resolve_active_bank_path to the identical root (G88 follow-up — see
    # ConnectView.swift, which fetches this instead of re-deriving a root
    # from local heuristics that could disagree with whatever the backend
    # was actually started with).
    memory_root: str
    # True when any LEANN index sidecar (<name>.meta.json) exists on disk.
    leann_present: bool


# --- Sleep ---


class SleepTriggerResponse(CamelModel):
    status: str
    message: str
    cycle_id: Optional[str] = None


class SleepCancelResponse(CamelModel):
    """``POST /sleep/cancel`` — cooperative-cancel request for whatever cycle
    is currently running.

    Mirrors ``SleepTriggerResponse``'s own "no 404/409, just an honest 200
    body" convention (see ``/sleep/trigger``'s ``already_running`` status):
    ``status`` is ``"cancelling"`` when a cycle was found running (idempotent
    — a second call while a cancel is already pending returns the same
    shape), or ``"not_running"`` when there was nothing to cancel. ``message``
    always states the cooperative contract plainly: this stops the cycle at
    its next safe point, not instantly, and nothing already captured is lost.
    """
    status: str
    message: str
    cycle_id: Optional[str] = None


class SleepDebtResponse(CamelModel):
    """How far behind Sleep is, right now — independent of whether a cycle
    is currently running (that's `stage`/`progress` on `SleepStatusResponse`).
    See `api/services/sleep_debt.py::SleepDebt` for the formula.
    """
    unprocessed_count: int
    oldest_unprocessed_age_hours: Optional[float] = None
    hours_since_last_cycle: Optional[float] = None
    has_run_before: bool
    volume_pct: int
    age_pct: int
    # None ONLY when the queue is empty AND Sleep has never run in this bank
    # — no baseline to call "rested". Every other state gets an honest
    # number (see `sleep_debt.rested_pct_from_components`).
    rested_pct: Optional[int] = None


class SleepStatusResponse(CamelModel):
    status: str
    cycle_id: Optional[str] = None
    started_at: Optional[str] = None
    progress: Optional[str] = None
    error: Optional[str] = None
    # Non-fatal warnings raised during the cycle (e.g. LEANN episode index
    # rebuild failed). The cycle still committed the main entity writes —
    # this is for "completed with warnings" state the Sleep page can surface
    # so stale indexes don't masquerade as success.
    index_warning: Optional[str] = None
    stage: int = 0
    total_stages: int = 5
    episodes_total: int = 0
    entities_created: int = 0
    entities_updated: int = 0
    relationships_created: int = 0
    skills_detected: int = 0
    # Resumable queue: episodes this cycle consolidated vs. left queued because
    # their Stage-1 extraction failed (e.g. a credit cap hit mid-run).
    # ``episodes_requeued`` > 0 means "completed, but re-run Sleep to finish".
    episodes_processed: int = 0
    episodes_requeued: int = 0
    # G60 — open-question re-scoring outcomes for the Sleep dashboard.
    questions_refreshed: int = 0
    organic_resolutions: int = 0
    # G74(a) — which engine this cycle ran on, and one sentence about its
    # state ("Claude Code is signed out — run `claude auth login`").
    last_engine: Optional[str] = None
    engine_detail: Optional[str] = None
    # Sleep control — episode cap (settings-driven; see
    # ``Settings.sleep_max_episodes_per_cycle``). ``episodes_queued`` is the
    # FULL unprocessed count found at the top of this cycle, BEFORE capping;
    # ``episode_cap`` is the cap applied. ``episodes_total`` above is the
    # (possibly capped) count this cycle actually attempted, so
    # ``episodes_queued > episodes_total`` means the cap truncated this
    # cycle and the rest stayed queued for the next one.
    episode_cap: int = 0
    episodes_queued: int = 0
    # Sleep control — cooperative cancellation. ``cancel_requested`` is true
    # from the moment ``POST /sleep/cancel`` is accepted for the currently
    # running cycle until it reaches its next safe point (as opposed to a
    # cancel requested too late — after writes began — which the cycle
    # still finishes and commits normally). ``cancelled`` is true when a
    # cycle stopped early because of one, for a bounded time window after
    # (``sleep_cycle.CANCELLED_DISPLAY_WINDOW_SECONDS``, currently 5
    # minutes) rather than a fragile one-shot "first read only" — see
    # ``sleep_cycle.cancelled_is_visible``'s docstring for why: a true
    # read-and-clear would race across every concurrent reader of the
    # backend's shared state, each "using up" the single display for every
    # OTHER reader. A time window means every reader agrees, there is no
    # mutation-on-read, and the flag still genuinely clears rather than
    # sticking forever the way it originally did (Devin PR #27 round 1,
    # finding 3 — the field used to document one-read semantics no code
    # ever implemented).
    cancel_requested: bool = False
    cancelled: bool = False
    # Sleep debt (G106) — always present, computed fresh from the current
    # queue + git log on every response. See `api/services/sleep_debt.py`
    # for the formula and full field contract.
    debt: SleepDebtResponse
    # Sleep debt (G106) — live "episodes processed / episodes in this cycle"
    # DURING a cycle. `None` — never a fabricated 0 — whenever there's no
    # honest live number: idle, or Stage 1 has already finished and stages
    # 2-5 have no per-episode unit to report (see
    # `sleep_cycle.progress_pct`'s docstring for the full contract).
    progress_pct: Optional[int] = None
    # G125 — this cycle's selected episodes by source, and how many of each
    # Stage 1 has finished (R3). Empty when idle.
    queue_by_origin: dict[str, int] = Field(default_factory=dict)
    read_by_origin: dict[str, int] = Field(default_factory=dict)


class SleepHistoryEntry(CamelModel):
    """One consolidation, as the Sleep page's history lists it (G125 R4).

    Counts are parsed server-side from the commit's manifest lines — the body
    itself never crosses the wire (the M1 lesson: 787 B → 378 KB for eight
    commits when it did). ``duration_ms`` is joined from the ``sleep_run``
    ledger row by ``refs.commit`` and is ``None`` — never estimated — when no
    row exists (R5; G107 keeps estimates deferred).
    """
    commit_hash: str
    date: str
    message: str
    files_changed: list[str]
    # G74(a) Task 6 — which engine drove this cycle's commit, parsed from the
    # commit's optional ``Cicada-Engine:`` trailer. ``None`` for every commit
    # made before this trailer existed, and for the `cicada`-authored
    # decay-only commit (G85 split): no LLM engine ran for pure decay
    # arithmetic, so the honest answer is "no engine", never a guess.
    engine: Optional[str] = None
    # "sleep" | "decay" (the G85 split's `(decay)` commit) | "inbox"
    kind: str = "sleep"
    entities_created: int = 0
    entities_updated: int = 0
    episodes: int = 0
    sessions: int = 0
    authors: list[str] = Field(default_factory=list)
    duration_ms: Optional[int] = None


class SleepCycleEntity(CamelModel):
    id: str
    action: str
    trigger: str
    source_episode: Optional[str] = None


class SleepCycleDetail(SleepHistoryEntry):
    """``GET /sleep/history/{commit}`` — what one cycle consolidated (G125)."""
    entities: list[SleepCycleEntity] = Field(default_factory=list)
    truncated: bool = False
    episodes_by_origin: dict[str, int] = Field(default_factory=dict)
    inbox_changes: int = 0


class EpisodeQueueItem(CamelModel):
    id: str
    timestamp: str
    source: str
    # G9 origin — the harness-normalized id (`claude-code`, `chatgpt-export`,
    # `telegram`, `pinterest`, ...), derived the same way Stage 1 extraction
    # already does (`sleep_cycle._derive_origin`) so the Sleep debt
    # breakdown groups by the SAME identity the rest of the app's origin
    # iconography already keys on, not the legacy `source` string.
    origin: str = "unknown"
    title: Optional[str] = None
    preview: str
    # G125 R9 — body length in characters, for the Sleep page's book pile
    # (a log-scale spine height, R9). 0 on an older backend that predates
    # this field, and for an episode whose body genuinely is empty.
    chars: int = 0
    processed: bool
    # G114 R6: who flipped `processed` — "sleep" for a Sleep-cycle
    # consolidation, "agent" (or the harness name) for an agent's
    # `cicada_mark_processed`. Optional so an older app build keeps decoding,
    # and null for every episode processed before the stamp existed.
    processed_by: Optional[str] = None


SCHEDULE_MODES = ("manual", "daily", "interval", "after_import")


class ScheduleConfig(CamelModel):
    """When Sleep runs on its own (G125 (4)). ``mode`` is the truth; ``enabled``
    is derived (``mode != "manual"``) and always written so an older reader of
    ``/status.nextSleepAt`` keeps working (R6). An older client that PUTs only
    ``{enabled, hour, minute}`` gets ``daily``/``manual`` derived for it.
    ``after_import`` is a settle probe, not a hook (R7).
    """
    mode: Optional[str] = None
    enabled: bool = False
    # 24-hour clock, local time. Constrained so garbage input (e.g. hour=99)
    # is rejected at the API boundary instead of persisting to
    # memory/sleep_schedule.yaml or blowing up CronTrigger downstream.
    hour: int = Field(3, ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    # "interval" mode's period, hours. 1..168 (a week) — below 1 is a
    # de-facto polling loop, above a week is indistinguishable from manual.
    interval_hours: int = Field(6, ge=1, le=168)

    @model_validator(mode="after")
    def _derive(self):
        if self.mode is None:
            self.mode = "daily" if self.enabled else "manual"
        if self.mode not in SCHEDULE_MODES:
            raise ValueError(f"mode must be one of {SCHEDULE_MODES}")
        self.enabled = self.mode != "manual"
        return self


# --------------------------------------------------------------------------- #
# G122 — GET/PUT /sleep/engine: the Settings → Sleep engine & model picker.
# --------------------------------------------------------------------------- #


class SleepEngineCandidate(CamelModel):
    """One row of the picker's segmented control. Deliberately NOT a reuse of
    ``ConnectionStatus`` (that schema carries login/billing/price fields no
    candidate needs, and G124 bans price/token fields from this surface
    entirely) — a candidate only needs enough to render a segment and, once
    selected, a model list."""
    id: str
    label: str
    available: bool = False
    connected: bool = False
    models: list[str] = Field(default_factory=list)
    detail: Optional[str] = None


class SleepEnginePreview(CamelModel):
    """What the NEXT cycle would actually run on, for one trigger source.
    ``engine`` is an ``ENGINE_LABELS`` id (``claude-cli|ollama|litellm``, see
    ``engine_select.engine_label``), not the picker's ``mode`` — a resolved
    "auto" or a prefs "byok" both read as "litellm" here, matching what
    ``sleep_cycle`` itself would stamp as ``last_engine``."""
    engine: str
    model: str
    why: str


class SleepEnginePreviews(CamelModel):
    """Both previews, always both — ruling 4 (a scheduled cycle never spends
    plan quota) is made VISIBLE here rather than hidden: the picker renders
    ``manual`` and ``scheduled`` side by side so a prefs-chosen "agent" that
    silently degrades on the nightly schedule is obvious, never a surprise."""
    manual: SleepEnginePreview
    scheduled: SleepEnginePreview


class SleepEngineResponse(CamelModel):
    """The full GET/PUT /sleep/engine body. ``source`` tells the reader WHY
    ``mode`` is what it is — ``"env"`` (an explicit ``CICADA_LLM_MODE``),
    ``"prefs"`` (this endpoint's own pref, G122), or ``"default"`` (nobody
    chose, today's shipped behaviour) — mirroring ``ConnectionStatus.how``'s
    own "explain the state next to what decided it" shape. No price, no
    token count, anywhere on this schema (G124)."""
    mode: str
    model: str
    disambiguation_model: str
    source: str  # "env" | "prefs" | "default"
    candidates: list[SleepEngineCandidate]
    preview: SleepEnginePreviews


class SleepEngineChoice(CamelModel):
    """A PUT body. ``model``/``disambiguation_model`` are ``Optional`` so
    ``sleep_engine_prefs.validate_and_write`` can tell "omitted" from
    "explicitly cleared" via ``model_fields_set`` — the same idiom
    ``routers/connections.py::PrefsBody`` already uses for ``tier``."""
    mode: str
    model: Optional[str] = None
    disambiguation_model: Optional[str] = None


class OwnerUpdateRequest(CamelModel):
    """PUT /settings/owner body. `handle`/`email` are stored in owner.json
    only (never in the entity page, never sent anywhere else — CLAUDE.md's
    rail: owner.json holds a name, never a secret, and these two are opt-in
    identity, not credentials)."""

    name: str
    handle: Optional[str] = None
    email: Optional[str] = None


class OwnerSettingsResponse(CamelModel):
    name: str = ""
    handle: Optional[str] = None
    email: Optional[str] = None
    # R1's resolved value — "owner" on a fresh install/bank, the legacy
    # "rodrigo" on a pre-G117 bank until the name is set, else the
    # name-derived slug. Always non-empty.
    observer: str = "owner"
    entity_id: Optional[str] = None


# --- Conversation Upload ---


class ConversationUploadResponse(CamelModel):
    status: str
    episodes_created: int
    # G20 delta re-import: episodes rewritten in place because a re-exported
    # thread grew/changed (same source_id, new content). Wire = episodesUpdated.
    episodes_updated: int = 0
    duplicates_skipped: int
    message: str
    source: str = "unknown"


# --- Memory Banks (M6) ---


class BankInfo(CamelModel):
    name: str
    active: bool = False
    entity_count: int = 0
    episode_count: int = 0
    created_at: str = ""
    description: str = ""


class BankListResponse(CamelModel):
    banks: list[BankInfo] = []
    active: str = ""


class BankCreateRequest(CamelModel):
    name: str
    description: Optional[str] = None


class BankDuplicateRequest(CamelModel):
    new_name: str


class BankRenameRequest(CamelModel):
    new_name: str


# --- Chat-history import (M7) ---


class BankImportDateRange(CamelModel):
    # Min / max original conversation date (YYYY-MM-DD) across staged episodes.
    # Both ``None`` when nothing dated was staged (e.g. memories-only import).
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None


class BankImportResponse(CamelModel):
    episodes_staged: int = 0
    # G20 delta re-import: episodes rewritten in place for grown/changed threads
    # (same source_id, new content). Wire = episodesUpdated.
    episodes_updated: int = 0
    duplicates_skipped: int = 0
    date_range: BankImportDateRange = Field(default_factory=BankImportDateRange)
    format: str = "unknown"
    # G87 / Wave-1 1.6: whether `{name}` is the bank Sleep actually consolidates.
    # An import into a NON-active bank stages real episodes that nothing will
    # ever process — the app branches its toast on this rather than showing a
    # plain success message that silently hides the consequence.
    active: bool = False


# --- Sources (media ingestion) ---


class SourceSaveRequest(CamelModel):
    url: str
    note: Optional[str] = None
    tags: list[str] = []
    # G48: conversation provenance from a live MCP client (`cicada_save_url`).
    # Optional — the menu-bar quick action and the app's paste field send none.
    session_id: Optional[str] = None
    harness: Optional[str] = None
    project_dir: Optional[str] = None


class SourceSaveResponse(CamelModel):
    status: str
    media_entity_id: str
    episode_id: str
    title: str
    media_type: str
    thumbnail: Optional[str] = None
    message: str


class SourceUploadResponse(CamelModel):
    # Mirrors ConversationUploadResponse on the wire (status/episodesCreated/
    # duplicatesSkipped/message/source) so the shipped Swift client can decode
    # one shape for both upload flows. ``episodes_created`` is the count queued
    # after dedup; enrichment + writes finish in the background.
    status: str
    episodes_created: int
    duplicates_skipped: int
    message: str
    source: str = "unknown"


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


class SourceRssRequest(CamelModel):
    # Exactly one of feed_xml / feed_url is required. ``feed_xml`` is the
    # keyless/offline path (paste or fetched-elsewhere XML); ``feed_url`` only
    # works when the network-fetch flag is enabled server-side.
    feed_xml: Optional[str] = None
    feed_url: Optional[str] = None
    tags: list[str] = []


class MediaSourceItem(CamelModel):
    media_entity_id: str
    url: str
    title: str
    media_type: str
    site: Optional[str] = None
    channel: Optional[str] = None
    thumbnail: Optional[str] = None
    saved_at: str
    tags: list[str] = []
    status: str = "active"
    related_count: int = 0
    # §3.4 relevance: confidence x recency-decay x personal weight, in [0,1].
    relevance: float = 0.0
    personal_relevance: Optional[str] = None
    # G99d — the user's actual save/bookmark/like date, recovered from the
    # source export (see api/services/saved_at.py). Distinct from `saved_at`
    # above, which — despite its name — has always meant "when Cicada
    # ingested the item" (kept as-is rather than rewritten out from under
    # existing readers). `None` means unknown, never a guess. Recency sorts
    # (GET /sources ?sort=recent, the app's Recent toggle) should prefer this
    # and fall back to `saved_at`.
    content_saved_at: Optional[str] = None
    # G102 cheap slice (R12): the link's own description — OpenGraph at ingest
    # or the Sleep-tail backfill's summary — cut at ~280 chars on a word
    # boundary, and the ids of the entities the page is `about` (the media
    # page's `related:` list, written only by `link_recon`). Both additive and
    # defaulted so an older client is unaffected; `None`/`[]` mean the link
    # has not been described/related yet, never a guess.
    description: Optional[str] = None
    about: list[str] = []
    # G124 R6 — the media entity's own `origin:` / `folder:` frontmatter
    # (written by media_ingestor.write_media_entity) so the Sources page can
    # filter the Feed's items to one source and group them by bookmark folder,
    # Pinterest board or iCloud device without a second endpoint. Optional:
    # a page ingested before origins were stamped simply has neither.
    origin: Optional[str] = None
    folder: Optional[str] = None
    # Track V (R-V2/R15) — read back from the media page's own `media:` block,
    # exactly where `site`/`channel` above already come from, and NOT from
    # `url_index.json`: putting them in the index too would create a second
    # thing to migrate and a second thing to disagree. Additive + defaulted,
    # and no ETag input changes (`/sources` still ETags over the same
    # components), so the ship-together rule is satisfied by there being
    # nothing to ship. Wire names: `provider`, `durationS`.
    provider: Optional[str] = None
    duration_s: Optional[int] = None


class SourceListResponse(CamelModel):
    items: list[MediaSourceItem]
    total: int


class BookmarkSyncRequest(CamelModel):
    # Both optional + base64-encoded so the same endpoint works for an inline
    # hermetic test payload and (when omitted entirely) a local-file sync.
    chrome_data_b64: Optional[str] = None
    safari_data_b64: Optional[str] = None
    # R5 — exact folder-path prefixes at segment boundaries; "" = everything;
    # omitted = everything (unchanged behaviour).
    folders: Optional[list[str]] = None


class BookmarkSyncSourceSummary(CamelModel):
    origin: str
    # R4 — the `sync_state.json` key this source's sync stamped
    # (`chrome-bookmarks` / `safari-bookmarks`), so the app can refresh
    # exactly the channel row that changed.
    channel: str = ""
    found: int = 0
    new: int = 0
    skipped: int = 0


class BookmarkSyncResponse(CamelModel):
    new: int
    skipped: int
    sources: list[BookmarkSyncSourceSummary] = []
    # G129 slice 2 — how many `removal` inbox items this sync proposed, and
    # (mutually exclusive in practice, but both default absent) why none were
    # computed when the rails refused (folder-scope mismatch since the last
    # sync on some channel this pass touched).
    removals_proposed: int = 0
    removals_skipped: Optional[str] = None


class BookmarkFolderNode(CamelModel):
    """One folder in a bookmark tree: `count` includes every leaf beneath it."""

    name: str
    path: str
    count: int = 0
    children: list["BookmarkFolderNode"] = []


class BookmarkTreeSource(CamelModel):
    origin: str
    total: int = 0
    tree: BookmarkFolderNode


class BookmarkTreePreview(CamelModel):
    """`POST /sources/sync-bookmarks?preview=true` — folder trees, stages nothing."""

    sources: list[BookmarkTreeSource] = []


class SafariTabsSyncRequest(CamelModel):
    """Bytes of Safari's CloudTabs.db, read by the app (R1) — plus the WAL
    sidecar when one exists (R2) and an optional exact-name device filter."""

    safari_tabs_db_b64: str
    safari_tabs_wal_b64: Optional[str] = None
    devices: Optional[list[str]] = None


class SafariTabsDevice(CamelModel):
    """One device in a CloudTabs.db, with its importable-tab count."""

    name: str
    count: int = 0


class SafariTabsSelectedDevice(SafariTabsDevice):
    """A device on a sync RESULT — the same row plus whether the request's
    device filter included it. A separate model rather than an
    ``Optional[bool]`` on the preview row: a preview has no selection yet,
    and serializing ``selected: null`` there would make the app's decoder
    carry a field that means nothing until the user has chosen."""

    selected: bool


class SafariTabsPreview(CamelModel):
    """`POST /sources/sync-safari-tabs?preview=true` — per-device counts, stages nothing."""

    total: int = 0
    devices: list[SafariTabsDevice] = []
    warnings: list[str] = []


class SafariTabsSyncResponse(CamelModel):
    new: int
    skipped: int
    seen: int = 0
    devices: list[SafariTabsSelectedDevice] = []


# --- Maintenance (G21 dedup sweep) ------------------------------------------


class MaintenanceDedupSweepRequest(CamelModel):
    # Default True: an unguarded POST from a naive client must never write.
    dry_run: bool = True
    # Caps how many candidate pairs are judged (bounds LLM calls on a large
    # graph). None (default) means "no cap".
    limit: Optional[int] = None


class MaintenanceMergePair(CamelModel):
    loser: str
    winner: str


class MaintenanceNudgePair(CamelModel):
    a: str
    b: str


class MaintenanceDedupSweepResponse(CamelModel):
    dry_run: bool
    candidate_pairs: int = 0
    # Merges actually performed (only possible when dry_run=false).
    merged: list[MaintenanceMergePair] = []
    # Merges the judge would have performed, held back because dry_run=true.
    proposed: list[MaintenanceMergePair] = []
    # Pairs the judge was uncertain about — same shape as the Nudge Inbox.
    nudged: list[MaintenanceNudgePair] = []
    # G113 slice 3b — pairs skipped without a judge call because the user
    # already rejected them (`merge_rejections`). Distinct from `nudged`: a
    # rejected pair never re-reaches the judge at all, so it is neither
    # merged, proposed, nor nudged.
    skipped_rejected: int = 0


class MaintenanceEnrichLinksResponse(CamelModel):
    """What one `POST /maintenance/enrich-links` run did (G102 cheap slice).
    Mirrors `link_enrichment.BackfillReport.as_dict()`; `remaining` is the
    live count of media pages still owed a description, `remainingRecon` the
    pages still owed relations, `deferred` the failed fetches inside their
    30-day backoff. `engine`/`engineDetail` say which engine the run resolved
    (a $0 run reports the configured engine but makes no call)."""
    selected: int = 0
    reused: int = 0
    summarized: int = 0
    fetched: int = 0
    failed: int = 0
    skipped: int = 0
    extracted: int = 0
    related: int = 0
    remaining: int = 0
    remaining_recon: int = 0
    deferred: int = 0
    llm_calls: int = 0
    engine_aborted: Optional[str] = None
    commit: Optional[str] = None
    engine: Optional[str] = None
    engine_detail: Optional[str] = None


class NotesSyncRequest(CamelModel):
    # The raw delimited osascript dump (what tests and a future companion-app
    # path use), mirroring BookmarkSyncRequest's inline-data shape. Omitted
    # entirely -> the endpoint falls back to a real local osascript enumeration.
    notes_dump: Optional[str] = None


class NotesSyncResponse(CamelModel):
    new: int
    updated: int
    skipped: int
    total: int = 0
    # Notes dropped by CICADA_NOTES_EXCLUDE_FOLDERS before dedup/ingest.
    excluded: int = 0

# --- Capture channels (G62) --------------------------------------------------


class SourceChannel(CamelModel):
    """One capture channel as the Capture page sees it. `connected` is derived
    from persisted state only (registries, sync_state.json, env, origin counts)
    — never from the transient result of a sync/import button press."""

    id: str
    label: str
    connected: bool = False
    count: int = 0
    last_sync: Optional[str] = None
    # G71 — the last poll's failure, when there was one. Present so the Capture
    # page can say "last sync failed · <reason>" instead of silently showing a
    # stale success. Never carries a credential: connectors build this string
    # from an exception type + message only.
    last_error: Optional[str] = None
    detail: Optional[str] = None
    # R-S5 — the count no longer rides pre-formatted inside `detail`. The
    # registry baked `f"{n:,}"` into the line and the app printed it verbatim,
    # so a server-side `en_US` grouping sat beside the app's own locale-correct
    # one in a single window (critique B1). `count_noun` is the SINGULAR noun
    # ("bookmark", "saved item"); the client pluralises with `+ "s"` — every
    # noun the registry and its adapters ship is regular, pinned by
    # `test_channel_detail_numbers.py::test_every_shipped_noun_pluralises_by_adding_s`.
    # `None` means this branch has nothing to count, which is what makes
    # "0 pins · Last sync failed" unrepresentable rather than merely unlikely.
    count_noun: Optional[str] = None
    # True only for a connector's "items pulled THIS run"
    # (`channel_registry._connector_channel`), which is not a channel total —
    # the client renders it "+N nouns this sync", the words the server used to
    # bake in itself.
    count_is_delta: bool = False
    actions: list[str] = []


class SourceChannelsResponse(CamelModel):
    channels: list[SourceChannel] = []


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
    # "credentials" (a script-app-style connector needs no redirect round trip).
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
    # G71 follow-up (Task 14): pay-per-use connectors (X) report the number of
    # billed resource reads this sync incurred, distinct from `new`/`seen` —
    # every connector defaults to 0, so this is additive, not a shape change.
    resources_read: int = 0


# --- Provider connections (G50) ---


class ConnectionKind(str, Enum):
    subscription = "subscription"
    usage = "usage"
    local = "local"


class LoginHint(CamelModel):
    mode: str  # terminal | device-code | key | none
    command: Optional[str] = None


class ConnectionStatus(CamelModel):
    id: str
    label: str
    kind: ConnectionKind
    available: bool = False
    connected: bool = False
    plan: Optional[str] = None
    plan_label: Optional[str] = None
    tier: Optional[str] = None
    account: Optional[str] = None
    price_usd_month: Optional[float] = None
    price_note: Optional[str] = None
    billing: str = "usage"  # subscription | usage | free
    engine_role: Optional[str] = None
    detail: Optional[str] = None
    # G63: one sentence explaining *why this card says Connected*, authored
    # next to the probe that decided it so the copy can never drift from the
    # check. None when the connection isn't connected — there is nothing to
    # explain yet, and `detail` already carries the "here's how to connect" hint.
    how: Optional[str] = None
    # What this connection currently does for Cicada. The registry assigns
    # these across the probed set (only one adapter is the engine at a time),
    # so an adapter can't know its own answer.
    powers: list[str] = []
    # G74(a) — the user has picked this connection as the Sleep engine. Only
    # meaningful on `claude-plan`; a machine-global preference, never a probe.
    use_for_sleep: bool = False
    login: Optional[LoginHint] = None


class LoginSession(CamelModel):
    session_id: str
    connection_id: str
    mode: str
    state: str = "pending"  # pending | done | failed
    command: Optional[str] = None
    code: Optional[str] = None
    url: Optional[str] = None
    raw_output: str = ""
    detail: Optional[str] = None


class ConnectionsResponse(CamelModel):
    connections: list[ConnectionStatus]


class StatusConnections(CamelModel):
    connected: list[str] = []
    engine: Optional[str] = None


# --- Consumption / traceability (G51) ---


class ConsumptionSummary(CamelModel):
    cost_usd: float = 0.0
    equiv_cost_usd: float = 0.0
    invocations: int = 0
    tokens: int = 0
    memory_writes: int = 0
    sleep_runs: int = 0
    agentic_writes: int = 0
    streak_current: int = 0
    streak_best: int = 0
    range: str
    since: Optional[str] = None


class CalendarDay(CamelModel):
    date: str
    memory_writes: int = 0
    events: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    equiv_cost_usd: float = 0.0
    level: int = 0


class ConsumptionCalendar(CamelModel):
    days: list[CalendarDay]
    weeks: int


class ContributorCalendar(CamelModel):
    """`/consumption/calendar`'s shape for one `Cicada-Author` (G124 R14).
    ``days`` reuse ``CalendarDay`` with events/tokens/cost at zero so the app
    renders it with the same heatmap and no new cell type."""

    author: str
    days: list[CalendarDay] = []
    weeks: int = 53


class ConsumptionStats(CamelModel):
    by_model: list[dict]
    by_stage: list[dict]
    by_connection: list[dict]
    by_bank: list[dict]
    hour_histogram: list[int]
    peak_day: Optional[dict] = None
    longest_sleep_run: Optional[dict] = None
    favorite_model: Optional[str] = None
    lifetime_tokens: int = 0
    first_event: Optional[str] = None
    series: list[dict]
    range: str


class ConsumptionFeedback(CamelModel):
    """G113: the grounded-reward ledger as numbers. Ids/enums-derived counts only."""
    range: str
    since: Optional[str] = None
    resolutions: int = 0
    corrections: int = 0
    rate: Optional[float] = None
    agreement: list[dict] = []
    calibration: list[dict] = []
    by_action: list[dict] = []
    audits: dict = {}
    dedup: dict = {}


class ConnectionConsumption(CamelModel):
    id: str
    label: str
    billing: str
    connected: bool = False
    price_usd_month: Optional[float] = None
    cost_usd: Optional[float] = None
    equiv_cost_usd: Optional[float] = None
    invocations: int = 0
    tokens: int = 0
    throttle_events: int = 0
    by_model: list[dict] = []


class ConsumptionConnections(CamelModel):
    connections: list[ConnectionConsumption]
    range: str


class HarnessStats(CamelModel):
    claude_code: Optional[dict] = None
    codex: Optional[dict] = None
