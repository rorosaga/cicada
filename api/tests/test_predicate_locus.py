"""G61 phase 2 S1 — where the truth lives: the predicate `locus` (spec R-AC8,
plan R-AC29). The seed and a bank's map, the most conservative value winning."""
from __future__ import annotations

import yaml

from api.services import predicates

SEVEN = {"takes-place-in", "located-in", "works-at", "runs-on", "depends-on", "part-of", "considering"}


def test_the_seed_marks_where_the_truth_lives():
    locus = predicates.build_locus_fn(None)
    assert [locus(p) for p in ("works-at", "takes-place-in", "located-in", "Works-At")] == ["world"] * 4
    assert [locus(p) for p in ("runs-on", "depends-on", "part-of")] == ["artifact"] * 3
    assert locus("considering") == "person"
    assert locus("relates-to") == locus("wears-hat-of") == locus("") == "unknown"


def test_the_seed_lists_only_predicates_it_has():
    seed = predicates._load_seed_map()
    listed = {p for group in seed["locus"].values() for p in group}
    assert listed == SEVEN and listed <= set(seed["canonical"])


def test_a_bank_map_can_only_make_a_predicate_more_conservative(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / predicates.RUNTIME_FILE).write_text(yaml.safe_dump({"locus": {
        "person": ["works-at"], "artifact": ["takes-place-in"], "world": ["considering", "hosts"]}}))
    locus = predicates.build_locus_fn(memory)
    assert locus("works-at") == "person"
    assert locus("takes-place-in") == "artifact"
    assert locus("considering") == "person", "the seed's person outranks a bank's world"
    assert locus("hosts") == "world", "a bank may mark a slug the seed leaves unknown"
    assert predicates.locus(memory, "works-at") == "person"


def test_a_new_bank_is_seeded_with_the_locus_block(tmp_path):
    memory = tmp_path / "memory"
    predicates.install_predicate_map(memory)
    data = yaml.safe_load((memory / predicates.RUNTIME_FILE).read_text())
    assert data["locus"]["person"] == ["considering"]
