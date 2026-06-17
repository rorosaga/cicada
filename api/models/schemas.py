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


class EntityStatus(str, Enum):
    active = "active"
    decaying = "decaying"
    archived = "archived"
    dropped = "dropped"


class NudgeType(str, Enum):
    decay = "decay"
    conflict = "conflict"
    clarification = "clarification"


# --- Entity ---


class EntityDiff(CamelModel):
    # Added / removed line blocks for one entity file at one commit, newline-joined.
    # git_service caps each side at DIFF_MAX_LINES so the response can't explode on
    # a huge rewrite; when the cap is hit a truncation marker is appended to the
    # affected side and ``truncated`` is set so the client can show "diff clipped".
    added: str = ""
    removed: str = ""
    truncated: bool = False


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


class ContributorsResponse(CamelModel):
    contributors: list[Contributor] = []


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
    options: Optional[list[str]] = None
    created_date: str = ""
    # clarification/merge extras (only populated for those kinds)
    uncertainty_type: Optional[str] = None
    suggested_classification: Optional[str] = None
    suggested_confidence: Optional[float] = None
    merge_target_hint: Optional[str] = None


class InboxResolveRequest(CamelModel):
    action: str
    answer: Optional[str] = None
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


class SleepHistoryEntry(CamelModel):
    commit_hash: str
    date: str
    message: str
    files_changed: list[str]


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


# --- Chat-history import (M7) ---


class BankImportDateRange(CamelModel):
    # Min / max original conversation date (YYYY-MM-DD) across staged episodes.
    # Both ``None`` when nothing dated was staged (e.g. memories-only import).
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None


class BankImportResponse(CamelModel):
    episodes_staged: int = 0
    duplicates_skipped: int = 0
    date_range: BankImportDateRange = Field(default_factory=BankImportDateRange)
    format: str = "unknown"


# --- Sources (media ingestion) ---


class SourceSaveRequest(CamelModel):
    url: str
    note: Optional[str] = None
    tags: list[str] = []


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
