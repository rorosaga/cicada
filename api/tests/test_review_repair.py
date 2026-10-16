"""Review probes for the repair and Stage 3 on a past-tense synonym (synthetic only)."""
from api.services import coexist_reopen
from api.tests.test_coexist_reopen import _close, _now, _sleep as _commit_sleep, _w, bank  # noqa: F401
from api.tests.test_works_at_coexist import _bank, _places, _sleep


def test_probe_repair_reopens_a_past_internship_as_current(bank):  # noqa: F811
    intern = _w("clm_i1", "lab-example", "2026-05-01")
    intern.text = "Bob Example interned at Lab Example"     # Stage 1's text: "{source} {raw_label} {target}"
    job = _w("clm_j1", "acme-example", "2026-06-01")
    _close(intern, job)
    _commit_sleep(bank, "2026-06-01", [intern, job])
    reasons = {i.claim_id: i.reason for i in coexist_reopen.analyze(bank).items}
    assert reasons["clm_i1"] != "reopen", "its own words are past tense: when in doubt, history"


def test_probe_stage3_interned_at_is_a_current_place_forever(tmp_path):
    memory = _bank(tmp_path)
    _sleep(memory, "2026-06-01", 1, [("interned at", "Lab Example")])
    _sleep(memory, "2026-09-01", 2, [("works at", "Acme Example")])
    current, works = _places(memory)
    assert "lab-example" not in current, "a past-tense label is history, never a current place"
