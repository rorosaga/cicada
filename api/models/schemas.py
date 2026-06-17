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


class ContributorsResponse(CamelModel):
    contributors: list[Contributor] = []


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


class GraphLink(CamelModel):
    source: str
    target: str
    label: str


class GraphResponse(CamelModel):
    nodes: list[GraphNode]
    links: list[GraphLink]


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


class SourceListResponse(CamelModel):
    items: list[MediaSourceItem]
    total: int
