"""The bank's ``_predicates.yaml`` is parsed once per change of the file, not once per question (2026-10-16 perf).

``GET /inbox`` asks ``predicates.cardinality`` once per conflict item; each call re-parsed the whole map, which on a
240-item synthetic inbox was ~0.6 s of a 0.64 s read. The read is now cached on the file's stat and handed out as a
copy, so a caller that edits what it read never edits what the next caller sees, and any write is seen at once.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from api.services import predicates


def _write_map(memory: Path, data: dict) -> Path:
    path = memory / predicates.RUNTIME_FILE
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_the_map_is_parsed_once_for_many_questions(tmp_path, monkeypatch):
    _write_map(tmp_path, {"single_valued": ["lives-in"], "multi_valued": ["uses"]})
    predicates._load_seed_map()   # the shipped seed is read once per process anyway
    loads = []
    real_load = yaml.load
    monkeypatch.setattr(predicates.yaml, "load", lambda *a, **k: loads.append(1) or real_load(*a, **k))

    answers = [predicates.cardinality(tmp_path, p) for p in ("uses", "lives-in", "pred-x") * 40]

    assert answers[:3] == ["multi", "single", "unknown"]
    assert len(loads) == 1


def test_a_write_is_seen_by_the_next_read(tmp_path):
    path = _write_map(tmp_path, {"single_valued": ["pred-alpha"]})
    assert predicates.cardinality(tmp_path, "pred-beta") == "unknown"

    _write_map(tmp_path, {"single_valued": ["pred-alpha", "pred-beta"]})
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))   # a coarse clock still moves the stamp
    assert predicates.cardinality(tmp_path, "pred-beta") == "single"

    path.unlink()
    assert predicates._read_runtime_map(tmp_path) == {}


def test_a_caller_editing_its_copy_never_edits_the_cache(tmp_path):
    _write_map(tmp_path, {"confirmed_folds": {"built-with": "uses"}})
    first = predicates._read_runtime_map(tmp_path)
    first["confirmed_folds"]["made-with"] = "uses"
    first["single_valued"] = ["uses"]

    again = predicates._read_runtime_map(tmp_path)
    assert again == {"confirmed_folds": {"built-with": "uses"}}


def test_a_confirmation_written_through_update_is_read_back(tmp_path):
    _write_map(tmp_path, {"confirmed_folds": {"built-with": "uses"}})
    assert predicates.confirmed_folds(tmp_path) == {"built-with": "uses"}   # cached

    def add(data: dict) -> bool:
        data.setdefault("confirmed_folds", {})["made-with"] = "uses"
        return True
    predicates.update_runtime_map(tmp_path, add)

    on_disk = yaml.safe_load((tmp_path / predicates.RUNTIME_FILE).read_text(encoding="utf-8"))
    assert on_disk["confirmed_folds"] == {"built-with": "uses", "made-with": "uses"}
    assert predicates.confirmed_folds(tmp_path) == {"built-with": "uses", "made-with": "uses"}


def test_install_reads_the_runtime_map_through_the_one_reader(tmp_path, monkeypatch):
    """``install_predicate_map``'s existence check takes the map through ``_read_runtime_map`` like every other reader:
    a populated map is kept, a placeholder, a malformed file or a non-mapping is replaced by the seed."""
    seed = predicates._load_seed_map()
    monkeypatch.setattr(predicates.yaml, "safe_load", lambda *a, **k: pytest.fail("parsed outside the one reader"))
    reads = []
    real = predicates._read_runtime_map
    monkeypatch.setattr(predicates, "_read_runtime_map", lambda m: reads.append(m) or real(m))

    populated = _write_map(tmp_path, {"canonical": ["pred-alpha"]})
    before = populated.read_bytes()
    predicates.install_predicate_map(tmp_path)
    assert populated.read_bytes() == before and reads == [tmp_path]

    for text in ("{}\n", "canonical: [unclosed\n", "- a list\n- not a map\n"):
        populated.write_text(text, encoding="utf-8")
        predicates.install_predicate_map(tmp_path)
        assert yaml.safe_load.__name__ == "<lambda>"   # still the tripwire
        assert predicates._read_runtime_map(tmp_path).get("canonical") == seed.get("canonical")
