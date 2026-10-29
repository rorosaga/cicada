from __future__ import annotations

import os
import threading
import time

from api.services import bank_index


def _write(path, fm: str, body: str = "hello"):
    path.write_text(f"---\n{fm}\n---\n\n{body}\n", encoding="utf-8")


def test_parses_once_and_reuses(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1\nprocessed: false\ntimestamp: '2026-08-01T10:00:00'")
    _write(d / "ep2.md", "id: ep2\nprocessed: true\ntimestamp: '2026-08-02T10:00:00'")
    before = bank_index.parse_count
    files = bank_index.files(tmp_path, "episodes")
    assert [f.stem for f in files] == ["ep1", "ep2"]
    assert files[0].frontmatter["processed"] is False
    assert bank_index.parse_count == before + 2
    bank_index.files(tmp_path, "episodes")
    assert bank_index.parse_count == before + 2  # no re-parse


def test_reparses_only_changed_file(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1\nprocessed: false")
    _write(d / "ep2.md", "id: ep2\nprocessed: false")
    bank_index.files(tmp_path, "episodes")
    before = bank_index.parse_count
    time.sleep(0.01)
    _write(d / "ep2.md", "id: ep2\nprocessed: true")
    os.utime(d / "ep2.md", None)
    files = bank_index.files(tmp_path, "episodes")
    assert bank_index.parse_count == before + 1
    assert {f.stem: f.frontmatter["processed"] for f in files} == {"ep1": False, "ep2": True}


def test_deleted_file_disappears_and_body_is_lazy(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1", body="the body")
    _write(d / "ep2.md", "id: ep2")
    assert bank_index.files(tmp_path, "episodes")[0].body() == "the body"
    (d / "ep2.md").unlink()
    assert [f.stem for f in bank_index.files(tmp_path, "episodes")] == ["ep1"]


def test_missing_dir_and_malformed_file(tmp_path):
    bank_index.invalidate()
    assert bank_index.files(tmp_path, "episodes") == []
    d = tmp_path / "episodes"; d.mkdir()
    (d / "bad.md").write_text("---\n: [unclosed\n---\n")
    _write(d / "ok.md", "id: ok")
    assert [f.stem for f in bank_index.files(tmp_path, "episodes")] == ["ok"]


def test_concurrent_files_no_torn_state(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    file_count = 20
    for i in range(file_count):
        _write(d / f"ep{i}.md", f"id: ep{i}")
    before = bank_index.parse_count
    results: list = [None, None]

    def worker(idx):
        results[idx] = bank_index.files(tmp_path, "episodes")

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    expected = {f"ep{i}" for i in range(file_count)}
    assert {f.stem for f in results[0]} == expected
    assert {f.stem for f in results[1]} == expected
    assert bank_index.parse_count - before <= 2 * file_count


def test_dir_stamp_changes_on_write(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "entities"; d.mkdir()
    _write(d / "a.md", "id: a")
    s1 = bank_index.dir_stamp(tmp_path, "entities")
    time.sleep(0.01)
    _write(d / "b.md", "id: b")
    s2 = bank_index.dir_stamp(tmp_path, "entities")
    assert s1 != s2 and s2[0] == 2


def test_body_reuses_the_cached_frontmatter_and_folds_a_ledger(tmp_path, monkeypatch):
    """2026-10-16 perf: `body()` re-parsed the frontmatter YAML the cache already held. It now splits the file and
    folds a page's claims ledger exactly as `markdown_parser.parse` does, and parses whole only a file that moved."""
    from api.services import claims, claims_ledger, markdown_parser

    bank_index.invalidate()
    d = tmp_path / "entities"; d.mkdir()
    page = d / "alpha-example.md"
    many = [claims.Claim(id=f"clm_{i:04d}", text=f"Alpha Example uses tool-{i} " + "x" * 300,
                         subject="alpha-example", predicate="uses", object=f"tool-{i}", observer="agent")
            for i in range(300)]
    markdown_parser.write(page, {"id": "alpha-example", "name": "Alpha Example", "type": "tool"},
                          claims.write_claims("## Summary\n\nA synthetic tool.", many))
    assert claims_ledger.path_for(page).exists()   # the fence overflowed into the ledger
    plain = d / "beta-example.md"
    _write(plain, "id: beta-example\nname: Beta Example", body="Beta's body.")

    entries = {f.stem: f for f in bank_index.files(tmp_path, "entities")}
    loads = []
    real_load = markdown_parser.yaml.load
    monkeypatch.setattr(markdown_parser.yaml, "load", lambda *a, **k: loads.append(1) or real_load(*a, **k))

    assert entries["alpha-example"].body() == markdown_parser.parse(page).body
    assert len(claims.parse_claims(entries["alpha-example"].body())) == 300
    assert entries["beta-example"].body() == "Beta's body."
    assert claims_ledger.READ not in entries["alpha-example"].frontmatter.get(claims_ledger.STAMP, {})
    loads.clear()
    entries["alpha-example"].body()
    entries["beta-example"].body()
    assert loads == []

    time.sleep(0.01)
    _write(plain, "id: beta-example\nname: Beta Example", body="Beta's new body, longer.")
    assert entries["beta-example"].body() == "Beta's new body, longer."   # moved since listed: parsed whole
    assert loads == [1]


# --- derived indexes and the same listing (source page speed, 2026-10-29) -------------------------------------------


def test_derived_is_built_once_per_state_of_the_folder(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1\norigin: a")
    builds = []

    def build(entries):
        builds.append(1)
        return sorted(f.frontmatter.get("origin") for f in entries)

    assert bank_index.derived(tmp_path, "episodes", "t", build) == ["a"]
    assert bank_index.derived(tmp_path, "episodes", "t", build) == ["a"]
    assert len(builds) == 1   # nothing changed: the kept value

    _write(d / "ep2.md", "id: ep2\norigin: b")   # added
    assert bank_index.derived(tmp_path, "episodes", "t", build) == ["a", "b"]
    time.sleep(0.01)
    _write(d / "ep1.md", "id: ep1\norigin: c")   # changed
    os.utime(d / "ep1.md", None)
    assert bank_index.derived(tmp_path, "episodes", "t", build) == ["b", "c"]
    (d / "ep2.md").unlink()                        # removed
    assert bank_index.derived(tmp_path, "episodes", "t", build) == ["c"]
    bank_index.invalidate(tmp_path)                # dropped: rebuilt from a fresh parse
    assert bank_index.derived(tmp_path, "episodes", "t", build) == ["c"]
    assert len(builds) == 5


def test_the_same_listing_is_not_compared_twice_but_a_newer_entry_is_never_skipped(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1\nprocessed: false")
    _write(d / "ep2.md", "id: ep2\nprocessed: false")
    listing = bank_index._scan_uncached(d)
    with bank_index.shared_scans(seed={str(d): listing}):
        first = bank_index.files(tmp_path, "episodes")
        again = bank_index.files(tmp_path, "episodes")
        assert [f.stem for f in again] == ["ep1", "ep2"] and again is not first   # a copy: a caller may mutate its own
        assert all(a is b for a, b in zip(first, again))
        # `file()` stores a newer copy than the (seeded) listing knows: the generation moves, so the next read compares
        # again and keeps that newer entry rather than answering from the remembered listing.
        time.sleep(0.01)
        _write(d / "ep2.md", "id: ep2\nprocessed: true")
        os.utime(d / "ep2.md", None)
        assert bank_index.file(tmp_path, "episodes", "ep2.md").frontmatter["processed"] is True
        assert {f.stem: f.frontmatter["processed"] for f in bank_index.files(tmp_path, "episodes")} == {
            "ep1": False, "ep2": True}


def test_a_file_that_moved_while_parsed_is_compared_again_on_the_same_listing(tmp_path, monkeypatch):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1\nprocessed: false")
    listing = bank_index._scan_uncached(d)
    real = bank_index.markdown_parser.header
    calls = []

    def moving(path):
        calls.append(path)
        out = real(path)
        if len(calls) == 1:
            _write(path, "id: ep1\nprocessed: true\nnote: moved while it was parsed")
        return out

    monkeypatch.setattr(bank_index.markdown_parser, "header", moving)
    with bank_index.shared_scans(seed={str(d): listing}):
        assert bank_index.files(tmp_path, "episodes") == []   # not stored: its stamp moved under the parse
        bank_index.files(tmp_path, "episodes")
        assert len(calls) == 2   # the same listing was compared again, never remembered as reconciled
    assert [f.frontmatter["processed"] for f in bank_index.files(tmp_path, "episodes")] == [True]
