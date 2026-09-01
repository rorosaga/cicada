from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
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
    # ``kind``: "user" for the literal `user` author, "unknown" for legacy
    # untrailered commits, "model" for every model id. ``provider`` is the
    # model's company (openai/anthropic/google/other) derived from the id, or
    # None for user/unknown. ``avatar_url`` is the user's GitHub profile picture
    # (https://github.com/<handle>.png) for the `user` author when a handle is
    # known; None for model/unknown (their identity is rendered client-side).
    kind: str = "unknown"  # "user" | "model" | "unknown"
    provider: Optional[str] = None  # "openai" | "anthropic" | "google" | "other" | None
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


class RequiredInput(str, Enum):
    none = "none"
    choice = "choice"
    freetext = "freetext"
    merge = "merge"


class InboxOption(CamelModel):
    """One answerable option on an inbox question (AskUserQuestion shape).

    ``age_days`` is derived at read time from ``last_referenced`` (falling back
    to ``observed_at``) — it is never persisted into the item file.
    """

    key: str
    label: str
    description: Optional[str] = None
    claim_id: Optional[str] = None
    observed_at: Optional[str] = None
    last_referenced: Optional[str] = None
    age_days: Optional[int] = None


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
    remind_after: Optional[str] = None
    updated_date: Optional[str] = None
    # clarification/merge extras (only populated for those kinds)
    uncertainty_type: Optional[str] = None
    suggested_classification: Optional[str] = None
    suggested_confidence: Optional[float] = None
    merge_target_hint: Optional[str] = None


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
    # True when any LEANN index sidecar (<name>.meta.json) exists on disk.
    leann_present: bool


# --- Sleep ---


class SleepTriggerResponse(CamelModel):
    status: str
    message: str
    cycle_id: Optional[str] = None


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


class SleepHistoryEntry(CamelModel):
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


class EpisodeQueueItem(CamelModel):
    id: str
    timestamp: str
    source: str
    title: Optional[str] = None
    preview: str
    processed: bool


class ScheduleConfig(CamelModel):
    enabled: bool
    # 24-hour clock, local time. Constrained so garbage input (e.g. hour=99)
    # is rejected at the API boundary instead of persisting to
    # memory/sleep_schedule.yaml or blowing up CronTrigger downstream.
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)


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


class SourceListResponse(CamelModel):
    items: list[MediaSourceItem]
    total: int


class BookmarkSyncRequest(CamelModel):
    # Both optional + base64-encoded so the same endpoint works for an inline
    # hermetic test payload and (when omitted entirely) a local-file sync.
    chrome_data_b64: Optional[str] = None
    safari_data_b64: Optional[str] = None


class BookmarkSyncSourceSummary(CamelModel):
    origin: str
    found: int = 0
    new: int = 0
    skipped: int = 0


class BookmarkSyncResponse(CamelModel):
    new: int
    skipped: int
    sources: list[BookmarkSyncSourceSummary] = []


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
