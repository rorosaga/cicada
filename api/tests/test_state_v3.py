"""G141 §10.3 — `_state.md` v3: `next` now, `now` once PJ-3 lands; nothing today-dependent."""
from datetime import datetime, timedelta, timezone

from _demo_scenario import T, d, day_one
from api.services import handshake, state_dictionary


def test_project_rows_carry_next_and_the_file_is_idempotent_across_a_day(tmp_path, monkeypatch):
    bank = day_one(tmp_path, index=False)
    now = datetime(2026, 9, 23, 20, 0, tzinfo=timezone.utc)
    # `today=` pinned: `build` otherwise takes `now.astimezone().date()`, the MACHINE's day.
    first = state_dictionary.refresh(bank, None, force=True, today=T, now=now, probe_repos=False)
    assert first["written"]
    st = state_dictionary.read_state(bank)
    assert st["schema_version"] == 3
    rover = next(p for p in st["projects"] if p["id"] == "rover-arm-project")
    assert rover["next"] == {"slug": f"due-{d(12)}", "name": "Pick And Place Demo", "target": d(12)}
    assert "now" not in rover                        # no ongoing claim exists before PJ-3
    # `force=True` on purpose: without it `refresh` short-circuits on an unchanged `inputs_version`
    # and would pass even if `next` depended on today. Forced, it rebuilds against the next day and
    # must find the content unchanged (§10.3 — the `test_state_dictionary.py:206` idle-night shape).
    again = state_dictionary.refresh(bank, None, force=True, today=T + timedelta(days=1),
                                     now=now + timedelta(days=1), probe_repos=False)
    assert again["written"] is False and again["reason"] == "content unchanged"


def test_the_primer_shows_the_current_line_and_stays_in_budget(tmp_path, monkeypatch):
    bank = day_one(tmp_path, index=False)
    state_dictionary.refresh(bank, None, force=True, today=T, probe_repos=False)
    text = handshake.build(state_dictionary.read_state(bank), variant="claude-code", bank="demo", tz="UTC")
    assert f"`rover-arm-project` Rover Arm Project — A small arm that picks parts off a tray. · next: Pick And Place Demo, {d(12)}" in text
    assert "Ask where a project stands with `cicada_project(project)`." in text
    assert len(text) // 4 <= handshake.MAX_TOKENS


def test_seven_projects_with_now_fit_in_six_kilobytes(tmp_path):
    """§10.3: the cap is measured with 7 projects that ALL carry `now`."""
    from _synthetic_bank import _bank, _entity
    from api.services import bank_index
    from api.services.claims import Claim, write_claims

    memory = _bank(tmp_path, git=False)
    for n in range(7):
        pid = f"omega-{n}-project"
        text = f"Bob is wiring sensor rig {n} into the lab network and checking each channel"
        claims = [Claim(id=f"clm_{pid}_happened_0000000{n}_2026-09-20", text=text, subject=pid, predicate="happened",
                        object=text.lower(), object_kind="literal", valid_from="2026-09-20", status="ongoing",
                        date_basis="turn", confidence=0.8),
                  Claim(id=f"clm_{pid}_milestone_ship_2026-09-01", text="Ship the rig", subject=pid,
                        predicate="milestone", object="ship", object_kind="literal", valid_from="2026-09-01",
                        status="planned", target="2026-10-01", date_basis="person")]
        _entity(memory, pid, type="project", confidence=0.95, last_referenced="2026-09-20",
                body=write_claims(f"## Summary\n{pid} is a synthetic project with a one-line summary.\n", claims))
    bank_index.invalidate()
    state_dictionary.refresh(memory, None, force=True, probe_repos=False)
    assert len(state_dictionary.state_path(memory).read_bytes()) <= state_dictionary.MAX_BYTES
    rows = [p for p in state_dictionary.read_state(memory)["projects"] if p["id"].startswith("omega-")]
    assert len(rows) == 7 and all(p.get("now") and p.get("next") for p in rows)
