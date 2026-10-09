"""A recall in a fresh process (the CLI, an MCP server's first call) reads what it needs, not the bank.

Measured on a ~3,600-page bank: the FTS freshness check parsed every file's frontmatter to learn that
nothing had moved, every name lookup read every page, the inbox block parsed every page and episode
for one item's cause, and the import pulled in litellm for a read. These tests pin the cheap paths AND
that the cheap paths still see every change: an edit that keeps the size, an add, a removal, a rename,
a git checkout. Hermetic: throwaway banks under tmp_path, placeholder names only.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from api.services import bank_index, inbox_context, markdown_parser, mcp_tools, search_index, text_fold


@pytest.fixture(autouse=True)
def _fresh_state():
    _cold()
    yield
    _cold()


def _cold():
    """What a new process starts with: no frontmatter cache, no index state, no name map."""
    bank_index.invalidate()
    search_index.reset()
    mcp_tools._NAME_LOOKUP = None


def _entity(memory, eid, *, name=None, body="## Summary\nA synthetic fixture.\n", **fm):
    base = {"name": name or eid.replace("-", " ").title(), "type": "concept", "status": "active",
            "confidence": 0.5, "tags": [], "aliases": [], "related": []}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", base, body)


def _bank(tmp_path, n=40):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox", "hubs"):
        (memory / sub).mkdir(parents=True)
    for i in range(n):
        _entity(memory, f"filler-{i:03d}", body=f"## Summary\nFiller page number {i}.\n")
    return memory


def _refs(memory, q):
    with search_index.Reader(memory) as r:
        rows = r.ranked("ent", search_index.match_expression(text_fold.query_tokens(q)), 20)
        docs = r.docs([d for d, _ in rows])
    return sorted(d.ref for d in docs.values())


@pytest.fixture
def parses(monkeypatch):
    """Every markdown parse, by file name."""
    seen: list[str] = []
    real = markdown_parser.parse

    def counting(path, *a, **k):
        seen.append(os.path.basename(str(path)))
        return real(path, *a, **k)

    monkeypatch.setattr(markdown_parser, "parse", counting)
    return seen


# --- the freshness check ------------------------------------------------------------------------


def test_a_fresh_process_learns_nothing_moved_without_parsing_a_file(tmp_path, parses):
    memory = _bank(tmp_path)
    search_index.rebuild(memory)
    _cold()
    parses.clear()
    assert search_index.ensure_fresh(memory) == "ready"
    assert parses == [], "an unchanged bank is a directory listing, never a parse"


def test_a_fresh_process_parses_only_what_moved(tmp_path, parses):
    memory = _bank(tmp_path)
    search_index.rebuild(memory)
    _entity(memory, "filler-007", body="## Summary\nRewritten with quokka.\n")
    _cold()
    parses.clear()
    assert search_index.ensure_fresh(memory) == "ready"
    assert set(parses) == {"filler-007.md"}
    assert _refs(memory, "quokka") == ["filler-007"]


def _same_size_edit(path, old: str, new: str, *, mtime_ns: int | None = None):
    assert len(old) == len(new)
    before = path.stat()
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(old, new), encoding="utf-8")
    assert path.stat().st_size == before.st_size
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    return before


def test_an_edit_that_keeps_the_size_is_caught(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project", body="## Summary\nThe walrus plan.\n")
    search_index.rebuild(memory)
    _same_size_edit(memory / "entities" / "alpha-project.md", "walrus", "toucan")
    _cold()
    assert search_index.ensure_fresh(memory) == "ready"
    assert _refs(memory, "toucan") == ["alpha-project"]
    assert _refs(memory, "walrus") == []


def test_a_same_size_edit_with_its_mtime_set_back_is_caught(tmp_path):
    """A restore that stamps a file with an OLDER time (git-restore-mtime, tar, rsync -t): the stamp
    still differs from the one the index holds, and any difference is a change."""
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project", body="## Summary\nThe walrus plan.\n")
    search_index.rebuild(memory)
    path = memory / "entities" / "alpha-project.md"
    held = path.stat().st_mtime_ns
    _same_size_edit(path, "walrus", "toucan", mtime_ns=held - 86_400 * 10**9)
    _cold()
    assert search_index.ensure_fresh(memory) == "ready"
    assert _refs(memory, "toucan") == ["alpha-project"]


def test_added_removed_and_renamed_pages_are_caught(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project", body="## Summary\nThe walrus plan.\n")
    _entity(memory, "bob-example", body="## Summary\nA heron watcher.\n")
    search_index.rebuild(memory)
    _entity(memory, "gamma-project", body="## Summary\nA quokka census.\n")
    (memory / "entities" / "bob-example.md").unlink()
    (memory / "entities" / "alpha-project.md").rename(memory / "entities" / "alpha-renamed.md")
    _cold()
    assert search_index.ensure_fresh(memory) == "ready"
    assert _refs(memory, "quokka") == ["gamma-project"]
    assert _refs(memory, "heron") == []
    assert _refs(memory, "walrus") == ["alpha-renamed"]


def test_a_git_checkout_of_an_older_version_is_caught(tmp_path):
    memory = _bank(tmp_path, n=3)
    _entity(memory, "alpha-project", body="## Summary\nThe walrus plan.\n")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "v1"]):
        subprocess.run(["git", "-C", str(memory), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                       check=True, capture_output=True)
    _same_size_edit(memory / "entities" / "alpha-project.md", "walrus", "toucan")
    search_index.rebuild(memory)
    assert _refs(memory, "toucan") == ["alpha-project"]
    subprocess.run(["git", "-C", str(memory), "checkout", "--", "entities/alpha-project.md"],
                   check=True, capture_output=True)
    _cold()
    assert search_index.ensure_fresh(memory) == "ready"
    assert _refs(memory, "walrus") == ["alpha-project"]
    assert _refs(memory, "toucan") == []


def test_a_malformed_page_is_left_out_as_before(tmp_path):
    memory = _bank(tmp_path, n=2)
    search_index.rebuild(memory)
    (memory / "entities" / "broken.md").write_text("---\nname: [unclosed\n---\nbody\n", encoding="utf-8")
    _cold()
    changed, removed = search_index._diff(memory, search_index._load_stamps(search_index.db_path(memory)))
    assert changed == {} and removed == []


# --- name lookups -------------------------------------------------------------------------------


def test_names_come_from_the_index_for_pages_that_did_not_move(tmp_path, parses):
    memory = _bank(tmp_path, n=60)
    search_index.rebuild(memory)
    _cold()
    parses.clear()
    names = search_index.entity_names(memory)
    assert names["filler-001"] == "Filler 001"
    assert parses == [], "an unchanged page's name is the one the index recorded"
    assert search_index.entity_names(memory) is names, "nothing moved: the same answer"


def test_names_are_exact_without_an_index_and_never_create_one(tmp_path):
    memory = _bank(tmp_path, n=40)
    _entity(memory, "alpha-project", name="Project Alpha")
    names = search_index.entity_names(memory)
    assert names["alpha-project"] == "Project Alpha"
    assert not search_index.db_path(memory).exists()


def test_a_renamed_name_an_added_page_and_a_removed_page_are_seen(tmp_path):
    memory = _bank(tmp_path, n=40)
    _entity(memory, "alpha-project", name="Project Alpha")
    _entity(memory, "bob-example", name="Bob Example")
    search_index.rebuild(memory)
    entities = memory / "entities"
    assert mcp_tools._entity_id_for_name(entities, "Project Alpha") == "alpha-project"
    _entity(memory, "alpha-project", name="Project Omega")          # same process, warm map
    _entity(memory, "gamma-project", name="Gamma Initiative")
    (entities / "bob-example.md").unlink()
    assert mcp_tools._entity_id_for_name(entities, "Project Alpha") is None
    assert mcp_tools._entity_id_for_name(entities, "project omega") == "alpha-project"
    assert mcp_tools._entity_id_for_name(entities, "Gamma Initiative") == "gamma-project"
    assert mcp_tools._entity_id_for_name(entities, "Bob Example") is None


def test_a_stem_match_wins_and_the_real_casing_is_returned(tmp_path):
    memory = _bank(tmp_path, n=2)
    _entity(memory, "alpha-project", name="Something Else")
    _entity(memory, "zeta-page", name="Alpha Project")
    entities = memory / "entities"
    assert mcp_tools._entity_id_for_name(entities, "Alpha Project") == "alpha-project"
    assert mcp_tools._entity_id_for_name(entities, "ALPHA-PROJECT") == "alpha-project"
    assert mcp_tools._entity_id_for_name(entities, "something else") == "alpha-project"
    assert mcp_tools._entity_id_for_name(entities, "nobody") is None


def test_each_bank_answers_for_itself(tmp_path):
    """The split-brain rule: the caller's bank, never another one's cached map."""
    one, two = _bank(tmp_path / "one", n=1), _bank(tmp_path / "two", n=1)
    _entity(one, "alpha-project", name="Shared Name")
    _entity(two, "beta-project", name="Shared Name")
    assert mcp_tools._entity_id_for_name(one / "entities", "Shared Name") == "alpha-project"
    assert mcp_tools._entity_id_for_name(two / "entities", "Shared Name") == "beta-project"
    assert mcp_tools._entity_id_for_name(one / "entities", "Shared Name") == "alpha-project"


# --- the inbox block's causes ---------------------------------------------------------------------


def test_an_inbox_cause_parses_only_the_pages_it_lands_on(tmp_path, parses):
    memory = _bank(tmp_path, n=50)
    _entity(memory, "alpha-project", source_episodes=["ep_2026-09-01_001"])
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md",
                          {"id": "ep_2026-09-01_001", "timestamp": "2026-09-01T09:00:00+00:00"},
                          "user: the alpha project plan\n")
    _cold()
    parses.clear()
    ctx = inbox_context.InboxContext(memory, today="2026-10-01")
    assert ctx.entity("alpha-project").frontmatter["name"] == "Alpha Project"
    assert ctx.entity("Alpha Project").stem == "alpha-project", "the sanitized fallback still resolves"
    assert ctx.episode("ep_2026-09-01_001").stem == "ep_2026-09-01_001"
    assert ctx.entity("nobody") is None and ctx.episode("ep_1999-01-01_001") is None
    assert sorted(set(parses)) == ["alpha-project.md", "ep_2026-09-01_001.md"]


# --- the whole recall -----------------------------------------------------------------------------


def test_a_cold_recall_reads_a_handful_of_pages_not_the_bank(tmp_path, parses, monkeypatch):
    memory = _bank(tmp_path, n=300)
    _entity(memory, "alpha-project", name="Alpha Project", related=["Filler 010", "Filler 020"])
    (memory / "hubs" / "topic-alpha.md").write_text(
        "---\ntype: hub\nname: alpha\nhub_kind: topic\n---\n- [[Filler 030]]\n- [[Alpha Project]]\n",
        encoding="utf-8")
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "title": "Still tracking Alpha Project?",
                           "created_date": "2026-08-01"}, "ctx")
    search_index.rebuild(memory)
    _cold()
    reads: list[str] = []
    real_read = mcp_tools.Path.read_text

    def counting_read(self, *a, **k):
        if self.suffix == ".md" and self.parent.name == "entities":
            reads.append(self.name)
        return real_read(self, *a, **k)

    monkeypatch.setattr(mcp_tools.Path, "read_text", counting_read)
    parses.clear()
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown")
    out = str(mcp_tools.recall(ctx, "alpha project"))
    assert "Alpha Project" in out and "Related (one hop out)" in out
    assert len(parses) + len(reads) < 40, (len(parses), len(reads))


def test_importing_the_recall_path_never_imports_litellm():
    code = ("import sys; import api.services.mcp_tools, api.cli; "
            "assert 'litellm' not in sys.modules, 'litellm imported'; "
            "from api.services import conflict_resolver; "
            "assert 'litellm' not in sys.modules; "
            "assert conflict_resolver.litellm.__name__ == 'litellm'")
    env = {**os.environ, "LITELLM_MODE": "PRODUCTION"}
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                          cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    assert proc.returncode == 0, proc.stderr[-2000:]


# --- another process writing the index mid-recall (review blocker) -------------------------------------


def _refresh_in_another_process(memory):
    code = f"from api.services import search_index; print(search_index.refresh(__import__('pathlib').Path({str(memory)!r})))"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    assert proc.returncode == 0 and "ready" in proc.stdout, proc.stderr[-2000:]


def test_a_page_indexed_by_another_process_mid_recall_is_never_deleted(tmp_path, monkeypatch):
    """Recall lists `entities/` first (a hub's members resolve by name), then the vector leg takes its
    time, then the lexical leg's freshness check loads the index's stamps. A page another process
    created AND indexed in between is in those stamps; a diff against recall's older listing read it
    as removed and deleted its rows, and no other process ever restored them."""
    memory = _bank(tmp_path, n=5)
    (memory / "hubs" / "topic-walrus.md").write_text(
        "---\ntype: hub\nname: walrus\n---\n- [[Filler 001]]\n", encoding="utf-8")
    search_index.rebuild(memory)
    _cold()

    def slow_vector_leg(memory_path, query, top_k):
        _entity(memory, "newcomer-page", body="## Summary\nA quokka census.\n")
        _refresh_in_another_process(memory)
        assert _refs(memory, "quokka") == ["newcomer-page"]
        return []

    monkeypatch.setattr(mcp_tools, "_leann_search_entities", slow_vector_leg)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown")
    mcp_tools.recall(ctx, "walrus")
    assert _refs(memory, "quokka") == ["newcomer-page"]


def test_a_removal_is_rechecked_against_the_disk_when_written(tmp_path):
    memory = _bank(tmp_path, n=2)
    _entity(memory, "alpha-project", body="## Summary\nThe walrus plan.\n")
    search_index.rebuild(memory)
    state = search_index._state(memory)
    search_index._refresh(memory, state, {}, ["entities/alpha-project.md"])   # a stale "removed"
    assert _refs(memory, "walrus") == ["alpha-project"], "a page on disk keeps its rows"
    (memory / "entities" / "alpha-project.md").unlink()
    search_index._refresh(memory, state, {}, ["entities/alpha-project.md"])
    assert _refs(memory, "walrus") == []


def test_rows_another_process_deleted_are_healed(tmp_path):
    """A warm process trusted its own stamps over the file: rows someone else deleted for a live page
    stayed missing until the page was edited. A write by anyone moves the index's generation, and a
    moved generation reloads the stamps from the file."""
    memory = _bank(tmp_path, n=2)
    _entity(memory, "alpha-project", body="## Summary\nThe walrus plan.\n")
    search_index.rebuild(memory)
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"     # warm state

    def rogue(conn):
        search_index._delete_doc(conn, "entities/alpha-project.md")
        search_index._new_generation(conn)

    search_index._write(search_index.db_path(memory), rogue)
    assert _refs(memory, "walrus") == []
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert _refs(memory, "walrus") == ["alpha-project"]


def test_warm_caches_see_a_same_size_edit(tmp_path):
    memory = _bank(tmp_path, n=40)
    _entity(memory, "alpha-project", name="Project Alpha", body="## Summary\nThe walrus plan.\n")
    search_index.rebuild(memory)
    entities = memory / "entities"
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert mcp_tools._entity_id_for_name(entities, "Project Alpha") == "alpha-project"
    bank_index.files(memory, "entities")                                 # warm frontmatter cache
    path = entities / "alpha-project.md"
    held = path.stat().st_mtime_ns
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("Project Alpha", "Project Omega").replace("walrus", "toucan"), encoding="utf-8")
    os.utime(path, ns=(held + 1, held + 1))                               # same size, 1 ns later
    assert mcp_tools._entity_id_for_name(entities, "Project Omega") == "alpha-project"
    assert mcp_tools._entity_id_for_name(entities, "Project Alpha") is None
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert _refs(memory, "toucan") == ["alpha-project"]
    assert [f.frontmatter["name"] for f in bank_index.files(memory, "entities") if f.stem == "alpha-project"] \
        == ["Project Omega"]
