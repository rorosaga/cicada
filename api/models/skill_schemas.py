"""G138 — the wire shape of GET /skills/recommended. Its own module so this
track stays out of schemas.py's busy tail (R-O30)."""
from __future__ import annotations

from typing import Optional

from pydantic import Field

from api.models.schemas import CamelModel


class SkillKey(CamelModel):
    name: str
    optional: bool = True


class SkillNeeds(CamelModel):
    binaries: list[str] = []
    keys: list[SkillKey] = []
    accounts: list[str] = []
    network: list[str] = []
    writes: list[str] = []
    allowed_tools: Optional[str] = None
    hooks: list[str] = []
    first_run: Optional[str] = None
    limits: list[str] = []


class SkillTerms(CamelModel):
    summary: str
    url: str
    safe_uses: list[str] = []


class SkillInstallStep(CamelModel):
    argv: list[str]
    tolerate_failure: bool = False


class SkillInstallPlan(CamelModel):
    runnable: bool = True
    steps: list[SkillInstallStep] = []
    env: dict[str, str] = {}


class RecommendedSkill(CamelModel):
    id: str
    kind: str
    rank: int = 999
    title: str
    summary: str
    why: str = ""
    publisher: str = ""
    source_url: str
    licence: str
    mark: Optional[str] = None
    symbol: str = "sparkles"
    endpoint: Optional[str] = None
    needs: SkillNeeds = Field(default_factory=SkillNeeds)
    terms: Optional[SkillTerms] = None
    cicada_note: Optional[str] = None
    agents: list[str] = []
    state: dict[str, str] = {}
    install: dict[str, SkillInstallPlan] = {}


class RecommendedSkillsResponse(CamelModel):
    reviewed_at: str = ""
    max_shown: int = 5
    catalog_size: int = 0
    recommended: list[RecommendedSkill] = []
    installed: list[RecommendedSkill] = []
