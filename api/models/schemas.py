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


class EntityHistoryEntry(CamelModel):
    date: str
    change_type: str
    description: str


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


class GraphLink(CamelModel):
    source: str
    target: str
    label: str


class GraphResponse(CamelModel):
    nodes: list[GraphNode]
    links: list[GraphLink]


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
