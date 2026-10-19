"""The Projects list's caches answer exactly what the uncached reads answer (perf 2026-10-19).

`GET /projects` took ~5 s on an 8k-page synthetic bank: every claim's anchor re-parsed its episode's whole `turns`
sidecar, and the reverse layer ran one FTS MATCH over every project's id and name. Each shortcut that replaced them is
pinned here against the rule it stands in for. Placeholder names only."""
from __future__ import annotations

import json
import pytest

from _demo_scenario import TZ, demo
from _synthetic_bank import _entity
from api.services import bank_index, evidence, markdown_parser, predicates, project_timeline, search_index
from api.services.claims import Claim, Evidence, write_claims


def _reply_gap_episode(memory, ep="ep_2026-09-01_001"):
    lines = ["user: first question about alpha", "assistant: a long answer begins",
             evidence.REPLY_GAP_LINE, "and resumes after the gap", "user: a second question", "assistant: done"]
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    body = "\n".join(lines)
    stamps = [{"offset": offsets[i], "ts": f"2026-09-01T0{i}:00:00Z", "speaker": "user" if i in (0, 4) else "assistant"}
              for i in (0, 1, 4, 5)]
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "timestamp": "2026-09-01T09:00:00+00:00", "processed": True, "turns": stamps,
                           "reply_gaps": [{"offset": offsets[2], "omitted_chars": 120}]}, body)
    return ep, body


@pytest.fixture
def memory(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    bank_index.invalidate()
    return memory


def test_the_cached_turn_time_is_turn_at_at_every_offset(memory):
    ep, body = _reply_gap_episode(memory)
    f = bank_index.file(memory, "episodes", f"{ep}.md")
    fm = bank_index.with_turns(f)
    stamps, gaps = evidence.turn_stamps(fm), evidence.gap_ranges(fm, body)
    assert gaps, "the fixture must exercise a recorded gap"
    times = project_timeline._turn_times(f, lambda: body)
    for offset in range(len(body) + 1):
        want = (evidence.turn_at(body, offset, stamps, gaps) or {}).get("ts")
        assert project_timeline._turn_ts(times, offset) == want, offset


def test_an_episode_without_a_sidecar_has_no_turn_times(memory):
    markdown_parser.write(memory / "episodes" / "ep_2026-09-02_001.md",
                          {"id": "ep_2026-09-02_001", "timestamp": "2026-09-02T09:00:00+00:00"}, "user: hi")
    f = bank_index.file(memory, "episodes", "ep_2026-09-02_001.md")
    assert project_timeline._turn_times(f, lambda: "user: hi") is None


@pytest.mark.parametrize("tz", ["UTC", "Pacific/Auckland"])
def test_the_list_anchor_day_is_the_anchors(tmp_path, memory, tz):
    """`_anchor_day` is `_anchor(...).day` for every claim of the demo bank (turn, episode and day bases, memory
    export entries, events) and for spans at every offset of an episode with a recorded gap — in two zones."""
    ep, body = _reply_gap_episode(memory)
    markdown_parser.write(memory / "episodes" / "ep_2026-09-02_001.md",
                          {"id": "ep_2026-09-02_001", "timestamp": "2026-09-02T23:30:00+00:00",
                           "source": "claude_memory"}, "user: an export entry")
    claims = [Claim(id=f"clm_g_{i}", text="a fact", subject="alpha-project", predicate="uses", object="beta",
                    valid_from="2026-08-30", source_episodes=[ep],
                    evidence=[Evidence(episode=ep, start=i, end=min(i + 5, len(body)), kind="user")])
              for i in range(0, len(body) - 1, 3)]
    claims += [Claim(id="clm_untimed", text="x", subject="alpha-project", predicate="uses", object="gamma",
                     valid_from="2026-08-01", source_episodes=["ep_2026-09-02_001"]),
               Claim(id="clm_nowhere", text="x", subject="alpha-project", predicate="uses", object="delta",
                     valid_from="2026-08-02", source_episodes=["ep_1999-01-01_001"])]
    _entity(memory, "alpha-project", type="project", body=write_claims("## Summary\nA page.\n", claims))
    bank_index.invalidate()
    checked = 0
    for root in (demo(tmp_path), memory):
        b = project_timeline._Bank(root, tz)
        for stem in b.stems:
            for c in b.all_claims(stem):
                a = project_timeline._anchor(b, c)
                assert project_timeline._anchor_day(b, c) == (a.day if a is not None else None), (stem, c.id)
                checked += 1
    assert checked > 60


@pytest.mark.parametrize("scan_past", [64, 0])
def test_claim_rows_follow_one_page_and_match_a_fresh_read(memory, monkeypatch, scan_past):
    """Both refresh paths — a range read per moved page, and (`_CLAIM_ROWS_SCAN = 0`) one scan of every row."""
    monkeypatch.setattr(search_index, "_CLAIM_ROWS_SCAN", scan_past)
    for eid in ("alpha-project", "beta-thing", "gamma-thing"):
        _entity(memory, eid, type="project" if eid.endswith("project") else "tool",
                body=write_claims("## Summary\nA page.\n", [
                    Claim(id=f"clm_{eid}_1", text=f"{eid} uses alpha", subject=eid, predicate="uses",
                          object="alpha-project")]))
    bank_index.invalidate()
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    first = search_index.claim_rows(memory)
    assert [ref for ref, _ in first] == ["alpha-project", "beta-thing", "gamma-thing"]
    assert search_index.claim_rows(memory) is first          # nothing moved: the same answer

    _entity(memory, "beta-thing", type="tool", body=write_claims("## Summary\nA page.\n", [
        Claim(id="clm_b_2", text="beta part of alpha", subject="beta-thing", predicate="part-of",
              object="Alpha Project")]))
    (memory / "entities" / "gamma-thing.md").unlink()
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    after = dict(search_index.claim_rows(memory))
    assert set(after) == {"alpha-project", "beta-thing"}
    assert [obj for obj, _ in after["beta-thing"]] == ["Alpha Project"]

    search_index.reset(memory)                              # a fresh process reads every page
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    assert dict(search_index.claim_rows(memory)) == after


def test_claim_rows_is_none_without_a_usable_index(memory, monkeypatch):
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "building")
    assert search_index.claim_rows(memory) is None


def test_a_page_naming_a_project_by_alias_counts_in_the_list_and_the_detail(memory):
    """The reverse layer resolves every indexed object (id, name or alias) — one rule for list and detail. The
    MATCH it replaced searched ids and names only, so an alias-named claim was dropped by both."""
    ep = "ep_2026-09-03_001"
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "timestamp": "2026-09-03T09:00:00+00:00", "processed": True},
                          "user: the rig runs on the arm")
    _entity(memory, "rover-arm-project", type="project", aliases=["the-arm-rig"])
    _entity(memory, "servo-example", type="tool", body=write_claims("## Summary\nA servo.\n", [
        Claim(id="clm_servo_1", text="servo is part of the arm rig", subject="servo-example", predicate="part-of",
              object="The-Arm-Rig", valid_from="2026-09-03", source_episodes=[ep],
              evidence=[Evidence(episode=ep, start=6, end=17, kind="user")])]))
    bank_index.invalidate()
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    row = next(r for r in project_timeline.list_projects(memory, tz_name="UTC").projects if r.id == "rover-arm-project")
    assert row.last_moment_day == "2026-09-03"
    assert [a.day for a in row.activity] == ["2026-09-03"]
    tl = project_timeline.build(memory, "rover-arm-project", tz_name="UTC")
    assert "2026-09-03" in tl.moment_days
    assert "servo-example" in {m.id for g in tl.cluster.groups for m in g.members}


def test_a_list_row_carries_the_first_activity_day_only(tmp_path, monkeypatch):
    """g141-4: the row's bar starts at the window's first day — the only use the list makes of the series."""
    bank = demo(tmp_path)
    full: dict[str, list] = {}
    real = project_timeline._activity

    def keep(b, claims):
        out = real(b, claims)
        full[len(full)] = out
        return out

    monkeypatch.setattr(project_timeline, "_activity", keep)
    rows = project_timeline.list_projects(bank, tz_name=TZ).projects
    series = list(full.values())
    assert any(len(s) > 1 for s in series), "the fixture must have a project with more than one active day"
    by_order = sorted(series, key=len)
    assert all(len(r.activity) <= 1 for r in rows) and any(r.activity for r in rows)
    assert sorted(r.activity[0].day for r in rows if r.activity) == sorted(s[0].day for s in by_order if s)


def _project_with_a_neighbour(memory, *claims, aliases=("the-arm-rig", "ar")):
    ep = "ep_2026-09-03_001"
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "timestamp": "2026-09-03T09:00:00+00:00", "processed": True},
                          "user: the rig runs on the arm")
    _entity(memory, "rover-arm-project", type="project", aliases=list(aliases))
    _entity(memory, "servo-example", type="tool", body=write_claims("## Summary\nA servo.\n", [
        Claim(id=f"clm_servo_{i}", text="x", subject="servo-example", valid_from="2026-09-03", source_episodes=[ep],
              evidence=[Evidence(episode=ep, start=6, end=17, kind="user")], **kw) for i, kw in enumerate(claims)]))
    bank_index.invalidate()
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"


def _row(memory):
    return next(r for r in project_timeline.list_projects(memory, tz_name="UTC").projects if r.id == "rover-arm-project")


@pytest.mark.parametrize("claim", [
    {"predicate": "value-of-favourite-rig", "object": "The-Arm-Rig", "object_kind": "literal"},
    {"predicate": "prefers", "object": "Rover Arm Project", "object_kind": "literal"},     # an inbox answer's shape
    {"predicate": "committed-to", "object": "the-arm-rig", "object_kind": "literal"},
    {"predicate": "value-of-rig", "object": "rover-arm-project", "object_kind": "node"},   # a value predicate, always
    {"predicate": "part-of", "object": "AR"},                                              # a two-letter alias
])
def test_a_value_or_a_short_alias_never_names_a_project(memory, claim):
    _project_with_a_neighbour(memory, claim)
    row = _row(memory)
    assert row.last_moment_day is None and row.activity == []
    tl = project_timeline.build(memory, "rover-arm-project", tz_name="UTC")
    assert "servo-example" not in {m.id for g in tl.cluster.groups for m in g.members}


def test_a_row_indexed_before_payloads_carried_the_kind_names_by_id_or_name_only(memory, monkeypatch):
    real = search_index.claim_payload

    def old_shape(claim):
        payload = real(claim)
        payload.pop("object_kind")
        return payload

    monkeypatch.setattr(search_index, "claim_payload", old_shape)
    _project_with_a_neighbour(memory, {"predicate": "part-of", "object": "The-Arm-Rig"})
    assert _row(memory).last_moment_day is None                     # by alias: not without the kind
    _project_with_a_neighbour(memory, {"predicate": "part-of", "object": "Rover Arm Project"})
    assert _row(memory).last_moment_day == "2026-09-03"             # by name: as before this change


def test_the_payload_cache_is_bounded_least_recently_used_first(monkeypatch):
    monkeypatch.setattr(project_timeline, "_PAYLOAD_CLAIMS", type(project_timeline._PAYLOAD_CLAIMS)())
    monkeypatch.setattr(project_timeline, "_PAYLOAD_CLAIMS_MAX", 3)
    js = [json.dumps({"id": f"clm_{i}", "predicate": "uses", "object": "x"}) for i in range(5)]
    for j in js[:3]:
        project_timeline._cached_payload_claim(j)
    project_timeline._cached_payload_claim(js[0])                   # used again: kept
    project_timeline._cached_payload_claim(js[3])
    assert list(project_timeline._PAYLOAD_CLAIMS) == [js[2], js[0], js[3]]
