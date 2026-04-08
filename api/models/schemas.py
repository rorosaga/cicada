from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict
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
    type: EntityType
    status: EntityStatus
    confidence: float


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


class SleepHistoryEntry(CamelModel):
    commit_hash: str
    date: str
    message: str
    files_changed: list[str]


# --- Conversation Upload ---


class ConversationUploadResponse(CamelModel):
    status: str
    episodes_created: int
    duplicates_skipped: int
    message: str
