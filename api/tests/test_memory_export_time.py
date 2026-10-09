"""Memory-export entries are facts, not activity (owner, 2026-10-08: "facts yes, activity no").

A `source: claude_memory` episode is the assistant's summary of the person, dated by the export entry's
`updated_at`. Its facts are kept with their sources; its date never counts as a mention or as activity.
"""
from __future__ import annotations

from _synthetic_bank import _bank, _entity
from api.services import bank_index, episode_time, markdown_parser, project_timeline
from api.services.claims import Claim, Evidence, write_claims

TZ = "UTC"
MEMORY_EP = "ep_2026-09-20_001"   # a summary exported in 2026 about a 2023-era project
CONV_EP = "ep_2023-05-10_001"     # the real conversation where the project came up


def _ep(memory, ep, ts, *, source=None, body="system: alpha-project is a rover arm"):
    fm = {"id": ep, "timestamp": ts, "processed": True}
    if source:
        fm["source"] = source
    markdown_parser.write(memory / "episodes" / f"{ep}.md", fm, body)


def _claim(cid, ep, valid_from, *, obj="rover-arm"):
    return Claim(id=cid, text=f"Alpha Project builds {obj}", subject="alpha-project", predicate="builds",
                 object=obj, object_kind="literal", valid_from=valid_from, source_episodes=[ep])


def _project(memory, claims):
    _entity(memory, "alpha-project", type="project", created="2023-05-10",
            body=write_claims("## Summary\nA fixture.\n", claims))
    bank_index.invalidate()


# --------------------------------------------------------------------------- the predicate


def test_only_a_memory_export_episode_is_untimed(tmp_path):
    memory = _bank(tmp_path, git=False)
    _ep(memory, MEMORY_EP, "2026-09-20T10:00:00Z", source="claude_memory")
    _ep(memory, CONV_EP, "2023-05-10T10:00:00Z", source="claude")
    bank_index.invalidate()
    assert episode_time.counts_as_activity({"source": "claude"})
    assert episode_time.counts_as_activity({})
    assert not episode_time.counts_as_activity({"source": "claude_memory"})
    assert episode_time.untimed_ids(memory) == frozenset({MEMORY_EP})
    assert episode_time.untimed_ids(None) == frozenset()


# --------------------------------------------------------------------------- Projects: Active / Resting


def test_a_project_known_only_from_a_memory_entry_has_no_activity_day(tmp_path):
    memory = _bank(tmp_path, git=False)
    _ep(memory, MEMORY_EP, "2026-09-20T10:00:00Z", source="claude_memory")
    _project(memory, [_claim("clm_2026-09-20_aaaa0001", MEMORY_EP, "2026-09-20")])
    row = next(r for r in project_timeline.list_projects(memory, tz_name=TZ).projects if r.id == "alpha-project")
    assert row.last_moment_day is None and row.activity == []
    tl = project_timeline.build(memory, "alpha-project", tz_name=TZ)
    assert tl.last_moment_day is None and tl.moment_days == []
    # The fact is still the project's: it is on the page with its source, only undated as activity.
    assert [c.id for c in project_timeline._Bank(memory, TZ).claims("alpha-project")] == ["clm_2026-09-20_aaaa0001"]


def test_a_memory_restatement_never_moves_the_project_to_the_export_date(tmp_path):
    memory = _bank(tmp_path, git=False)
    _ep(memory, CONV_EP, "2023-05-10T10:00:00Z", source="claude")
    _ep(memory, MEMORY_EP, "2026-09-20T10:00:00Z", source="claude_memory")
    _project(memory, [_claim("clm_2023-05-10_aaaa0001", CONV_EP, "2023-05-10"),
                      _claim("clm_2026-09-20_aaaa0002", MEMORY_EP, "2026-09-20", obj="a gripper")])
    row = next(r for r in project_timeline.list_projects(memory, tz_name=TZ).projects if r.id == "alpha-project")
    assert row.last_moment_day == "2023-05-10"
    assert [a.day for a in row.activity] == ["2023-05-10"]
    tl = project_timeline.build(memory, "alpha-project", tz_name=TZ)
    assert tl.moment_days == ["2023-05-10"]


def test_a_claim_cited_by_both_is_anchored_by_the_conversation(tmp_path):
    memory = _bank(tmp_path, git=False)
    _ep(memory, CONV_EP, "2023-05-10T10:00:00Z", source="claude")
    _ep(memory, MEMORY_EP, "2026-09-20T10:00:00Z", source="claude_memory")
    c = _claim("clm_2026-09-20_aaaa0003", MEMORY_EP, "2026-09-20")
    c.source_episodes = [MEMORY_EP, CONV_EP]
    c.evidence = [Evidence(kind="assistant", episode=MEMORY_EP, start=0, end=8, hash="0" * 16)]
    _project(memory, [c])
    tl = project_timeline.build(memory, "alpha-project", tz_name=TZ)
    assert tl.moment_days == ["2023-05-10"]


# --------------------------------------------------------------------------- decay pacing (G147 mention weeks)


def test_a_memory_entry_is_not_a_week_the_page_came_up_in():
    from api.services import decay_policy

    refs = ["ep_2023-05-10_001", "ep_2026-09-20_001"]
    assert decay_policy.mention_weeks(refs) == 2
    assert decay_policy.mention_weeks(refs, untimed={"ep_2026-09-20_001"}) == 1
    fm = {"type": "project", "source_episodes": refs}
    assert decay_policy.effective(fm, untimed={"ep_2026-09-20_001"}).mention_weeks == 1
    c = _claim("clm_x", "ep_2026-09-20_001", "2026-09-20")
    c.evidence = [Evidence(kind="assistant", episode="ep_2026-09-20_001", start=0, end=4, hash="0" * 12)]
    assert decay_policy.claim_mention_weeks(c) == 1
    assert decay_policy.claim_mention_weeks(c, untimed={"ep_2026-09-20_001"}) == 0


def test_the_entity_card_serves_the_pace_without_the_memory_week(tmp_path):
    import asyncio
    import types

    from api.routers import entities as entities_router

    memory = _bank(tmp_path, git=False)
    _ep(memory, CONV_EP, "2023-05-10T10:00:00Z", source="claude")
    _ep(memory, MEMORY_EP, "2026-09-20T10:00:00Z", source="claude_memory")
    _entity(memory, "alpha-project", type="project", source_episodes=[CONV_EP, MEMORY_EP])
    bank_index.invalidate()
    resp = asyncio.run(entities_router.get_entity("alpha-project", settings=types.SimpleNamespace(memory_path=memory)))
    assert resp.decay.mention_weeks == 1


# --------------------------------------------------------------------------- Sleep: what a memory entry writes


import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import date, datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402

from api.config import Settings  # noqa: E402
from api.services import conflict_resolver as cr, entity_extractor as ex, entity_resolver as er  # noqa: E402
from api.services import providers, source_dates  # noqa: E402

TODAY = date(2026, 10, 8)
CYCLE_NOW = datetime(2026, 10, 8, 3, 0)


class _CycleDay(date):
    """`conflict_resolver`'s today, pinned to the cycle's own day: a page's `created` falls back to `date.today()`
    while its `decayed_through` comes from the cycle's `now`, so the two agree on every day the suite runs."""

    @classmethod
    def today(cls):
        return cls(CYCLE_NOW.year, CYCLE_NOW.month, CYCLE_NOW.day)
MEMORY = {"id": MEMORY_EP, "timestamp": "2026-09-20T10:00:00Z", "origin": "claude-export", "source": "claude_memory",
          "evidence_kind": "assistant", "content": "system: The user built Alpha Project, a rover arm, in 2023."}
CONV = {"id": CONV_EP, "timestamp": "2023-05-10T10:00:00Z", "origin": "claude-export", "source": "claude",
        "content": "user: Alpha Project is the rover arm I am building."}


def _reply(_msg):
    return json.dumps({
        "entities": [{"name": "Alpha Project", "type": "project", "confidence": 0.8,
                      "summary": "Alpha Project is a rover arm.", "key_facts": ["Alpha Project is a rover arm."]}],
        "relationships": [{"source": "Alpha Project", "target": "Rover Arm", "label": "builds", "confidence": 0.8}],
    })


def _extract(episodes):
    seen: list[str] = []

    async def fake(**kw):
        seen.append(kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=_reply(seen[-1])))])

    async def no_sleep(*_a, **_k):
        return None

    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake), \
            patch.object(ex.asyncio, "sleep", no_sleep):
        out = asyncio.run(ex.extract([dict(e) for e in episodes], Settings(_env_file=None), today=TODAY))
    return out, seen


def test_stage_one_keeps_a_memory_entry_s_facts_but_not_its_date_as_a_mention():
    out, seen = _extract([MEMORY])
    (result,) = [r for r in out if r]
    (entity,) = result["entities"]
    assert entity["untimed"] is True
    assert entity["source_episode"] == MEMORY_EP                     # provenance kept
    assert entity["source_episode_timestamp"] is None and entity["source_episode_day"] is None
    (rel,) = result["relationships"]
    assert rel["source_episode_timestamp"] == MEMORY["timestamp"]    # a claim keeps its as-of date and source
    (claim,) = ex.entities_to_claims(out, None)
    assert claim.valid_from == "2026-09-20" and claim.source_episodes == [MEMORY_EP]
    # G194: the summary is not "a conversation dated 2026-09-20" to be written as of that month.
    (msg,) = seen
    assert msg.startswith(source_dates.DATE_NOTE_PREFIX)
    assert "this conversation is dated" not in msg and "as of September 2026" not in msg
    assert "not when" in msg and "today is 2026-10-08" in msg


def test_a_conversation_is_unchanged():
    out, seen = _extract([CONV])
    (entity,) = [r for r in out if r][0]["entities"]
    assert "untimed" not in entity
    assert entity["source_episode_timestamp"] == CONV["timestamp"] and entity["source_episode_day"] == "2023-05-10"
    assert "this conversation is dated 2023-05-10" in seen[0]


@pytest.fixture
def bank(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-bank"
    for name in ("entities", "episodes", "inbox"):
        (root / name).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)

    async def no_model(*a, **k):
        raise AssertionError("no model call expected")
    monkeypatch.setattr(er, "_llm_judge_same_entity", no_model)
    return root


def _settings(bank):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           sleep_promotion_threshold=1)


def _write(bank, episodes, existing=()):
    out, _ = _extract(episodes)
    resolved = asyncio.run(er.resolve([r for r in out if r], list(existing), _settings(bank)))
    real = Settings(_env_file=None, llm_mode="byok", litellm_model="synthetic-model")

    async def no_synthesis(**_k):
        return None
    with patch.object(cr, "_synthesize_entity_update", no_synthesis), patch.object(cr, "date", _CycleDay):
        changes = asyncio.run(cr.resolve_and_prune(resolved["changes"], list(existing), real, decay=False,
                                                   now=CYCLE_NOW))
        cr.apply_changes(changes, bank)
    return resolved["changes"]


def test_a_page_first_heard_in_a_memory_entry_has_no_last_mention(bank):
    (change,) = _write(bank, [MEMORY])
    assert change["untimed"] is True and change["source_episode_timestamps"] == []
    fm = markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter
    assert "last_referenced" not in fm                              # never mentioned in a conversation
    assert str(fm["created"]) == "2026-10-08" == str(fm["decayed_through"])   # learned today; an import is not silence
    assert fm["source_episodes"] == [MEMORY_EP]


def test_a_conversation_beside_it_in_the_batch_dates_the_page(bank):
    (change,) = _write(bank, [MEMORY, CONV])
    assert change["untimed"] is False
    fm = markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter
    assert str(fm["last_referenced"]) == "2023-05-10" and str(fm["created"]) == "2023-05-10"
    assert sorted(fm["source_episodes"]) == sorted([MEMORY_EP, CONV_EP])


def test_a_memory_restatement_is_no_re_mention(bank):
    _entity(bank, "alpha-project", type="project", status="decaying", confidence=0.3, created="2023-05-10",
            last_referenced="2023-05-10", decayed_through="2026-10-01", source_episodes=[CONV_EP])
    parsed = markdown_parser.parse(bank / "entities" / "alpha-project.md")
    existing = [{"id": "alpha-project", "frontmatter": parsed.frontmatter, "body": parsed.body}]
    (change,) = _write(bank, [MEMORY], existing)
    assert change["action"] == "update" and change["untimed"] is True
    fm = markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter
    assert str(fm["last_referenced"]) == "2023-05-10"                # not the export date, not today
    assert str(fm["decayed_through"]) == "2026-10-01"                # the silence clock does not restart
    assert fm["status"] == "decaying" and fm["confidence"] == 0.3    # no recovery from a summary
    assert fm["source_episodes"] == [CONV_EP, MEMORY_EP]             # the fact's source is kept
