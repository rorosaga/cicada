"""G136 — the derived FTS5 index (`api/services/search_index.py`).

Hermetic: throwaway banks under tmp_path, synthetic names only
(alpha-project, bob-example, example.com). Nothing reads a real bank,
`~/.cicada` or the network.
"""
from __future__ import annotations

import subprocess

import pytest

from api.services import bank_index, bank_registry, evidence, markdown_parser, search_index, text_fold


@pytest.fixture(autouse=True)
def _fresh_state():
    bank_index.invalidate()
    search_index.reset()
    yield
    search_index.reset()
    bank_index.invalidate()


def _entity(memory, eid, *, name=None, body="## Summary\nA synthetic fixture.\n", **fm):
    base = {"name": name or eid.replace("-", " ").title(), "type": "concept", "status": "active",
            "confidence": 0.5, "tags": [], "aliases": []}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", base, body)


def _episode(memory, eid, body, **fm):
    base = {"id": eid, "title": "Untitled", "timestamp": "2026-09-01T09:00:00+00:00",
            "harness": "claude-code", "session_id": "ses_2026-09-01_abcd1234", "processed": True}
    base.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", base, body)


def _bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    return memory


def _ids(reader, table, q):
    return [d for d, _ in reader.ranked(table, search_index.match_expression(text_fold.query_tokens(q)), 20)]


def _refs(memory, table, q):
    with search_index.Reader(memory) as r:
        docs = r.docs(_ids(r, table, q))
    return sorted(d.ref for d in docs.values())


def test_passage_spans_tile_the_body_exactly():
    body = "\n".join(f"user: line {i} " + "word " * (i % 40) for i in range(120))
    spans = search_index.passage_spans(body)
    assert "".join(body[s:e] for s, e in spans) == body
    assert all(e - s <= search_index.PASSAGE_CHARS for s, e in spans)
    assert all(body[e - 1] == "\n" for s, e in spans[:-1]), "a window ends on a turn boundary when one is near"
    assert search_index.passage_spans("") == []


def test_names_aliases_diacritics_and_prefixes_are_found(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "zurich-office", name="Zürich Office", aliases=["HQ", "headquarters"])
    _entity(memory, "alpha-project", type="project")
    _entity(memory, "alpha-dropped", status="dropped")
    search_index.rebuild(memory)
    assert _refs(memory, "ent", "zur") == ["zurich-office"]
    assert _refs(memory, "ent", "Zurich") == ["zurich-office"]
    assert _refs(memory, "ent", "headq") == ["zurich-office"], "aliases are indexed (R3 P1)"
    assert _refs(memory, "ent", "alpha proj") == ["alpha-project"], "every token is a word-start prefix, ANDed"
    assert _refs(memory, "ent", "alpha zurich") == []
    assert _refs(memory, "ent", "alpha") == ["alpha-project"], "a dropped page is never indexed (R7)"


def test_a_sharp_s_or_ligature_name_is_found_by_its_exact_spelling(tmp_path):
    """S-back final review: the query fold was NFKD + casefold, so
    "hauptstraße" became "hauptstrasse" and missed the index, which keeps
    "ß" as written; the bank_index fallback found it — two tiers disagreeing."""
    memory = _bank(tmp_path)
    _entity(memory, "street-a", name="Hauptstraße Office")
    _entity(memory, "file-a", name="ﬁle Cabinet")
    search_index.rebuild(memory)
    assert _refs(memory, "ent", "hauptstraße") == ["street-a"]
    assert _refs(memory, "ent", "Hauptstraße") == ["street-a"]
    assert _refs(memory, "ent", "ﬁle") == ["file-a"]


def test_episode_passages_carry_exact_offsets_into_the_evidence_text(tmp_path):
    memory = _bank(tmp_path)
    filler = "\n".join(f"user: unrelated line {i}" for i in range(80))
    body = f"{filler}\nassistant: we moved the index to sqlite-vec so search is fast\n{filler}"
    _episode(memory, "ep_2026-09-01_001", body, title="Index choice")
    search_index.rebuild(memory)
    text = evidence.source_text(memory, "ep_2026-09-01_001")
    with search_index.Reader(memory) as r:
        rows = r.passages(search_index.match_expression(["sqlite"]), 5, recent_first=False)
        assert len(rows) == 1
        rowid, doc_id, start, end, _ = rows[0]
        assert "sqlite-vec" in text[start:end]
        assert r.passage_text([rowid])[rowid] == text[start:end]
        doc = r.docs([doc_id])[doc_id]
    assert doc.ref == "ep_2026-09-01_001"
    assert doc.meta["hash"] == evidence.body_hash(text)
    assert doc.meta["conversation_id"] == "ses_2026-09-01_abcd1234"


def test_superseded_claims_are_indexed_as_history(tmp_path):
    memory = _bank(tmp_path)
    body = (
        "## Summary\nA person.\n\n```claims\n"
        "- id: clm_old\n  text: \"bob-example lives in Lisbon\"\n  subject: bob-example\n"
        "  predicate: lives_in\n  object: Lisbon\n  valid_to: '2026-05-01'\n  superseded_by: clm_new\n"
        "- id: clm_new\n  text: \"bob-example lives in Porto\"\n  subject: bob-example\n"
        "  predicate: lives_in\n  object: Porto\n"
        "  evidence:\n  - {episode: ep_2026-09-01_001, start: 0, end: 5, kind: user, hash: abcdef123456}\n"
        "```\n"
    )
    _entity(memory, "bob-example", type="person", body=body)
    search_index.rebuild(memory)
    with search_index.Reader(memory) as r:
        old = r.claims(search_index.match_expression(["lisbon"]), 5)
        new = r.claims(search_index.match_expression(["porto"]), 5)
        by_id = r.claims_by_id(["clm_new"])
    assert [p["id"] for *_, p in old] == ["clm_old"]
    assert old[0][4]["valid_to"] == "2026-05-01" and old[0][4]["superseded_by"] == "clm_new"
    assert new[0][4]["evidence"]["episode"] == "ep_2026-09-01_001"
    assert by_id["clm_new"][1] == "bob-example lives in Porto"
    # The subject's name is a claim column: a claim is reachable by who it is about.
    with search_index.Reader(memory) as r:
        assert len(r.claims(search_index.match_expression(["bob", "porto"]), 5)) == 1


def test_claims_citing_an_episode_come_back_with_that_episodes_span(tmp_path):
    memory = _bank(tmp_path)
    body = (
        "## Summary\nA person.\n\n```claims\n"
        "- id: clm_two\n  text: \"bob-example likes tea\"\n  subject: bob-example\n"
        "  evidence:\n"
        "  - {episode: ep_2026-09-01_001, start: 0, end: 4, kind: user, hash: aaaaaaaaaaaa}\n"
        "  - {episode: ep_2026-09-02_001, start: 10, end: 20, kind: assistant, hash: bbbbbbbbbbbb}\n"
        "- id: clm_none\n  text: \"bob-example is kind\"\n  subject: bob-example\n"
        "  evidence:\n  - {kind: reasoning}\n"
        "```\n"
    )
    _entity(memory, "bob-example", type="person", body=body)
    search_index.rebuild(memory)
    with search_index.Reader(memory) as r:
        cited = r.claims_citing("ep_2026-09-02_001")
        assert r.claims_citing("ep_2026-09-03_001") == []
    assert [(p["id"], span) for _d, _t, p, span in cited] == [
        ("clm_two", {"episode": "ep_2026-09-02_001", "start": 10, "end": 20, "kind": "assistant", "hash": "bbbbbbbbbbbb"})]
    (memory / "entities" / "bob-example.md").unlink()
    search_index.ensure_fresh(memory, max_age_s=0)
    with search_index.Reader(memory) as r:
        assert r.claims_citing("ep_2026-09-02_001") == [], "a deleted page takes its citations with it"


def test_media_pages_index_paper_authors_and_ids_and_stay_out_of_ent(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "media-wikiskill", name="WikiSkill", type="media",
            media={"url": "https://example.com/abs/2608.27454", "site": "example.com", "media_type": "url"},
            paper={"authors": ["Ada Example", "Bo Sample"], "arxiv_id": "2608.27454",
                   "doi": "10.1234/example.5678"})
    search_index.rebuild(memory)
    assert _refs(memory, "med", "2608.27454") == ["media-wikiskill"]
    assert _refs(memory, "med", "sample") == ["media-wikiskill"]
    assert _refs(memory, "med", "10.1234/example") == ["media-wikiskill"]
    assert _refs(memory, "ent", "wikiskill") == [], "a media page lives in `med` only"


def test_inbox_decay_items_index_the_question_they_are_served_as(tmp_path):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "beta-project",
                           "entity_name": "Beta Project", "created_date": "2026-08-01"}, "ctx")
    search_index.rebuild(memory)
    with search_index.Reader(memory) as r:
        doc = next(iter(r.docs(_ids(r, "inb", "still track")).values()))
    assert doc.ref == "inbox-001"
    assert doc.meta["question"] == "Still tracking Beta Project?"


def test_ensure_fresh_picks_up_new_and_deleted_files_without_a_rebuild(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    search_index.rebuild(memory)
    monkeypatch.setattr(search_index, "_full_build", lambda *a, **k: pytest.fail("incremental, not a rebuild"))
    _entity(memory, "bob-example", type="person")
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert _refs(memory, "ent", "bob") == ["bob-example"]
    (memory / "entities" / "bob-example.md").unlink()
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert _refs(memory, "ent", "bob") == []


def test_ensure_fresh_throttles_the_staleness_scan(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    search_index.rebuild(memory)
    scans = []
    real = search_index._diff
    monkeypatch.setattr(search_index, "_diff", lambda *a: scans.append(1) or real(*a))
    assert search_index.ensure_fresh(memory) == "ready"   # within the TTL of the build
    assert scans == []
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert scans == [1]


def test_a_bulk_change_is_caught_up_in_the_background(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    search_index.rebuild(memory)
    monkeypatch.setattr(search_index, "INLINE_REFRESH_LIMIT", 2)
    for i in range(3):
        _entity(memory, f"bulk-{i}")
    assert search_index.ensure_fresh(memory, max_age_s=0) == "stale"
    assert search_index.wait_idle(memory, timeout=10)
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert _refs(memory, "ent", "bulk") == ["bulk-0", "bulk-1", "bulk-2"]


def test_deleting_the_file_triggers_a_rebuild_never_an_error(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    search_index.rebuild(memory)
    for suffix in ("", "-wal", "-shm"):
        path = memory / f"{search_index.DB_FILE}{suffix}"
        if path.exists():
            path.unlink()
    assert search_index.ensure_fresh(memory) == "building"
    assert search_index.wait_idle(memory, timeout=10)
    assert search_index.ensure_fresh(memory) == "ready"
    assert _refs(memory, "ent", "alpha") == ["alpha-project"]


def test_a_corrupt_file_is_discarded_and_rebuilt(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    (memory / search_index.DB_FILE).write_bytes(b"this is not a sqlite database" * 100)
    assert search_index.ensure_fresh(memory, wait=True) == "ready"
    assert _refs(memory, "ent", "alpha") == ["alpha-project"]


def test_a_schema_change_rebuilds(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    search_index.rebuild(memory)
    search_index.reset()
    monkeypatch.setattr(search_index, "SCHEMA_VERSION", "999")
    built = []
    real = search_index._full_build
    monkeypatch.setattr(search_index, "_full_build", lambda *a: built.append(1) or real(*a))
    assert search_index.ensure_fresh(memory, wait=True) == "ready"
    assert built == [1]


def test_two_refreshes_of_one_file_never_duplicate_rows(tmp_path):
    """Two processes (the API now, the MCP server later) can both see a file
    as changed; deleting by doc_key inside the transaction keeps one copy."""
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    search_index.rebuild(memory)
    _entity(memory, "alpha-project", body="## Summary\nRewritten.\n")
    state = search_index._state(memory)
    stale = dict(state.stamps)
    changed, removed = search_index._diff(memory, stale)
    search_index._refresh(memory, state, changed, removed)
    search_index._refresh(memory, state, changed, removed)
    with search_index.Reader(memory) as r:
        assert r.count("ent", search_index.match_expression(["alpha"])) == 1


def test_one_odd_page_never_costs_the_build(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project", confidence="high")  # hand-edited, not a number
    _entity(memory, "bob-example", body="## Summary\nEXPLODE\n")
    _entity(memory, "zurich-office")
    real = search_index.summarize
    monkeypatch.setattr(search_index, "summarize", lambda text: 1 / 0 if "EXPLODE" in text else real(text))
    search_index.rebuild(memory)
    assert _refs(memory, "ent", "alpha") == ["alpha-project"], "a bad number reads as 0.0, the page stays"
    assert _refs(memory, "ent", "zurich") == ["zurich-office"]
    assert _refs(memory, "ent", "bob") == [], "the page that raised is skipped, its rows rolled back"


def test_a_reader_never_creates_the_file(tmp_path):
    import sqlite3

    memory = _bank(tmp_path)
    with pytest.raises(sqlite3.OperationalError):
        search_index.Reader(memory)
    assert not (memory / search_index.DB_FILE).exists()


def test_ensure_fresh_is_unavailable_for_a_directory_that_is_not_a_bank(tmp_path):
    assert search_index.ensure_fresh(tmp_path / "nope", wait=True) == "unavailable"
    assert not (tmp_path / "nope" / search_index.DB_FILE).exists()


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True)


def test_the_index_is_never_tracked_by_git(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                 ["add", "-A"], ["commit", "-q", "-m", "seed"]):
        _git(memory, *args)
    search_index.rebuild(memory)
    assert (memory / search_index.DB_FILE).exists()
    assert _git(memory, "status", "--porcelain").stdout == "", "never tracked, never dirties the tree"
    _git(memory, "add", "-A")
    assert _git(memory, "diff", "--cached", "--name-only").stdout == ""
    assert _git(memory, "check-ignore", "-q", search_index.DB_FILE).returncode == 0


def test_ensure_derived_excluded_is_idempotent_and_needs_a_git_dir(tmp_path):
    memory = _bank(tmp_path)
    assert bank_registry.ensure_derived_excluded(memory) is False, "no .git: nothing to protect"
    _git(memory, "init", "-q")
    assert bank_registry.ensure_derived_excluded(memory) is True
    first = (memory / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert bank_registry.ensure_derived_excluded(memory) is False
    assert (memory / ".git" / "info" / "exclude").read_text(encoding="utf-8") == first
    assert all(name in first.splitlines() for name in bank_registry.DERIVED_ARTIFACTS)


def test_a_worktree_bank_is_excluded_through_its_common_git_dir(tmp_path):
    """A bank checked out as a git worktree has a `.git` FILE; git reads the
    exclude file from the common git dir, and so must we (G136 R2)."""
    main = tmp_path / "main"
    main.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                 ["commit", "-q", "--allow-empty", "-m", "seed"],
                 ["worktree", "add", "-q", str(tmp_path / "bank")]):
        _git(main, *args)
    bank = tmp_path / "bank"
    assert (bank / ".git").is_file()
    assert bank_registry.ensure_derived_excluded(bank) is True
    assert _git(bank, "check-ignore", "-q", search_index.DB_FILE).returncode == 0


def test_a_new_bank_gitignore_lists_the_search_index(tmp_path):
    bank_registry.scaffold_bank(tmp_path / "fresh", git_init=False)
    lines = (tmp_path / "fresh" / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {"search_index.db", "search_index.db-wal", "search_index.db-shm"} <= set(lines)


def test_an_odd_byte_in_the_exclude_file_never_blocks_boot_or_the_exclusion(tmp_path):
    """S-back final review: a Latin-1 byte in a hand-edited
    `.git/info/exclude` raised UnicodeDecodeError (a ValueError) past the
    OSError guard, out of `scaffold_bank` — the lifespan's unguarded call —
    and out of every index build. It must neither raise nor lose the byte."""
    memory = _bank(tmp_path)
    _git(memory, "init", "-q")
    exclude = memory / ".git" / "info" / "exclude"
    exclude.write_bytes(b"# caf\xe9 notes\nscratch/")
    bank_registry.scaffold_bank(memory, git_init=False)
    raw = exclude.read_bytes()
    assert raw.startswith(b"# caf\xe9 notes\nscratch/\n"), "the bytes already there are untouched"
    assert _git(memory, "check-ignore", "-q", search_index.DB_FILE).returncode == 0
    assert bank_registry.ensure_derived_excluded(memory) is False, "idempotent over an odd byte"


def test_an_odd_byte_in_a_git_file_is_not_an_error(tmp_path):
    memory = _bank(tmp_path)
    (memory / ".git").write_bytes(b"gitdir: /nowhere/caf\xe9\n")
    assert bank_registry.ensure_derived_excluded(memory) is False
