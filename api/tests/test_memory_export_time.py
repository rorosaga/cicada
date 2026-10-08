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
