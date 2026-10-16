"""One Sleep batch's page parses come from a stat-checked cache (2026-10-16 perf, owner decision 1).

Measured on the owner-scale synthetic bank (`benchmarks/scale`): every step of a batch re-reads the pages, ~212k parses
a 3-batch drain. Inside `markdown_parser.page_cache` a file unchanged since its last parse is a copy, not a parse. These
tests pin the invalidation cases above all: Sleep's own writes, a writer admitted between its steps, an outside
editor's in-place write, git putting a file back, a ledger that moved under its page — and that nothing is cached
outside the batch or for another bank.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from api.services import claims_ledger, git_service, markdown_parser, write_admission


@pytest.fixture
def counted(monkeypatch):
    """How many real parses ran (the cache's misses), by path name."""
    calls: list[str] = []
    real = markdown_parser._parse

    def spy(filepath, *, ledger=True):
        calls.append(Path(filepath).name)
        return real(filepath, ledger=ledger)

    monkeypatch.setattr(markdown_parser, "_parse", spy)
    return calls


def _bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    for eid in ("alpha-project", "beta-tool"):
        markdown_parser.write(bank / "entities" / f"{eid}.md",
                              {"name": eid.replace("-", " ").title(), "type": "project", "tags": ["synthetic"]},
                              f"## Summary\n{eid} is a synthetic page.")
    return bank


def test_an_unchanged_page_is_parsed_once_per_batch_and_each_caller_gets_its_own_copy(tmp_path, counted):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    with markdown_parser.page_cache(bank) as cache:
        first = markdown_parser.parse(page)
        first.frontmatter["tags"].append("edited-by-a-caller")
        first.frontmatter["name"] = "Changed In Memory"
        second = markdown_parser.parse(page)
        third = markdown_parser.parse(page)
    assert counted == ["alpha-project.md"]
    assert cache.hits == 2
    assert second.frontmatter == {"name": "Alpha Project", "type": "project", "tags": ["synthetic"]}
    assert second.body == first.body == "## Summary\nalpha-project is a synthetic page."
    second.frontmatter["tags"].clear()
    assert third.frontmatter["tags"] == ["synthetic"]


def test_nothing_is_cached_outside_a_batch_and_the_batch_frees_its_memory(tmp_path, counted):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    markdown_parser.parse(page)
    markdown_parser.parse(page)
    assert counted == ["alpha-project.md"] * 2
    with markdown_parser.page_cache(bank) as cache:
        markdown_parser.parse(page)
        assert cache.entries
    assert cache.entries == {}
    assert markdown_parser._open_caches == set()
    markdown_parser.parse(page)
    assert counted == ["alpha-project.md"] * 4


def test_sleeps_own_write_is_read_back_at_once(tmp_path, counted):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    with markdown_parser.page_cache(bank):
        before = markdown_parser.parse(page)
        markdown_parser.write(page, {**before.frontmatter, "name": "Alpha Renamed"}, before.body)
        assert markdown_parser.parse(page).frontmatter["name"] == "Alpha Renamed"
        markdown_parser.write_document(page, "---\nname: Alpha Again\n---\n\nbody")
        assert markdown_parser.parse(page).frontmatter["name"] == "Alpha Again"


def test_a_write_from_another_thread_reaches_the_batch(tmp_path):
    bank = _bank(tmp_path)
    page = bank / "entities" / "beta-tool.md"
    with markdown_parser.page_cache(bank):
        assert markdown_parser.parse(page).frontmatter["name"] == "Beta Tool"

        def other_writer():   # no copy of the batch's context: it never reads through the cache, but its write lands
            assert markdown_parser._page_cache_var.get() is None
            markdown_parser.write(page, {"name": "Beta From Elsewhere", "type": "tool"}, "## Summary\nx")

        t = threading.Thread(target=other_writer)
        t.start()
        t.join()
        assert markdown_parser.parse(page).frontmatter["name"] == "Beta From Elsewhere"


def test_an_outside_editors_in_place_write_is_seen_even_at_the_same_size(tmp_path):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    with markdown_parser.page_cache(bank):
        old = page.read_text(encoding="utf-8")
        markdown_parser.parse(page)
        new = old.replace("Alpha Project", "Alpha Pr0ject")
        assert len(new) == len(old)
        ino = os.stat(page).st_ino
        with open(page, "r+", encoding="utf-8") as fh:   # in place: same inode, same size
            fh.write(new)
        st = os.stat(page)
        os.utime(page, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000))   # a clock that moved, however little
        assert os.stat(page).st_ino == ino
        assert markdown_parser.parse(page).frontmatter["name"] == "Alpha Pr0ject"


def test_a_writer_admitted_between_steps_empties_the_batchs_cache_of_its_bank(tmp_path, counted):
    bank = _bank(tmp_path)
    other = _bank(tmp_path / "other")
    page = bank / "entities" / "alpha-project.md"
    with markdown_parser.page_cache(bank) as cache:
        markdown_parser.parse(page)
        assert cache.entries
        with markdown_parser.page_cache(other) as other_cache:   # registered too (only the inner one reads)
            markdown_parser.parse(other / "entities" / "alpha-project.md")
            with write_admission.shared(bank):
                pass   # whatever it wrote, however it wrote it
            assert other_cache.entries, "another bank's batch is not this writer's"
        assert cache.entries == {}
        markdown_parser.parse(page)
    assert counted.count("alpha-project.md") == 3


def test_git_putting_a_page_back_starts_the_batch_over(tmp_path, counted):
    bank = _bank(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=bank, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "add", "-A"], cwd=bank, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init"],
                   cwd=bank, check=True)
    page = bank / "entities" / "alpha-project.md"
    with markdown_parser.page_cache(bank) as cache:
        markdown_parser.parse(page)
        git_service.run_git_write_sync(bank, "add", "-A")   # touches no working-tree file: kept
        assert cache.entries
        git_service.run_git_write_sync(bank, "checkout", "--", "entities/alpha-project.md")
        assert cache.entries == {}


def test_another_banks_files_are_never_served_from_this_batch(tmp_path, counted):
    bank = _bank(tmp_path)
    other = _bank(tmp_path / "elsewhere")
    with markdown_parser.page_cache(bank) as cache:
        for _ in range(3):
            markdown_parser.parse(other / "entities" / "alpha-project.md")
        assert cache.entries == {}
    assert counted == ["alpha-project.md"] * 3


def test_a_symlinked_bank_is_one_bank(tmp_path, counted):
    bank = _bank(tmp_path)
    link = tmp_path / "bank-link"
    link.symlink_to(bank)
    with markdown_parser.page_cache(link) as cache:
        markdown_parser.parse(link / "entities" / "alpha-project.md")
        markdown_parser.parse(link / "entities" / "alpha-project.md")
        with write_admission.shared(bank):
            pass
        assert cache.entries == {}
    assert counted == ["alpha-project.md"]


def _ledger_page(bank: Path) -> Path:
    page = bank / "entities" / "owner-example.md"
    fence_line = json.dumps({"id": "clm_fence", "text": "Owner Example uses beta tool", "subject": "owner-example"})
    body = f"## Summary\nThe owner.\n\n```claims\n{fence_line}\n```"
    markdown_parser.write_document(
        page, "---\nname: Owner Example\ntype: person\nclaims_ledger:\n  lines: 1\n---\n\n" + body + "\n")
    claims_ledger.path_for(page).write_text(
        json.dumps({"id": "clm_ledger_1", "text": "Owner Example asked about alpha"}) + "\n", encoding="utf-8")
    return page


def test_a_ledger_that_moves_under_its_page_is_folded_afresh(tmp_path):
    bank = _bank(tmp_path)
    page = _ledger_page(bank)
    ledger = claims_ledger.path_for(page)
    with markdown_parser.page_cache(bank):
        assert "clm_ledger_1" in markdown_parser.parse(page).body
        assert "clm_ledger_1" in markdown_parser.parse(page).body
        ledger.write_text(json.dumps({"id": "clm_ledger_2", "text": "Owner Example asked about beta"}) + "\n",
                          encoding="utf-8")
        body = markdown_parser.parse(page).body
        assert "clm_ledger_2" in body and "clm_ledger_1" not in body
        ledger.unlink()
        assert "clm_ledger_2" not in markdown_parser.parse(page).body
        # The frontmatter-only scan never opened the ledger and is cached on its own.
        assert markdown_parser.parse(page, ledger=False).body.count("clm_") == 1


def test_a_file_that_vanished_raises_as_before(tmp_path):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    with markdown_parser.page_cache(bank):
        markdown_parser.parse(page)
        page.unlink()
        with pytest.raises(FileNotFoundError):
            markdown_parser.parse(page)


def test_each_sleep_batch_runs_inside_its_own_cache_and_frees_it(tmp_path, monkeypatch):
    from api.services import sleep_cycle

    bank = _bank(tmp_path)
    seen = []

    async def stages(settings, cycle_id, memory_path, **kwargs):
        cache = markdown_parser._page_cache_var.get()
        seen.append(cache)
        markdown_parser.parse(Path(memory_path) / "entities" / "alpha-project.md")

        def in_a_worker():   # `asyncio.to_thread` copies the context: the stage's worker threads read through it
            return markdown_parser._page_cache_var.get()

        assert await asyncio.to_thread(in_a_worker) is cache
        return sleep_cycle._StageOutcome()

    monkeypatch.setattr(sleep_cycle, "_run_stages", stages)
    asyncio.run(sleep_cycle._run_batch(None, "c1", bank, user_triggered=True))
    asyncio.run(sleep_cycle._run_batch(None, "c2", bank, user_triggered=True))
    assert len(seen) == 2 and seen[0] is not seen[1]
    assert all(c is not None and c.entries == {} for c in seen)
    assert markdown_parser._page_cache_var.get() is None
    assert markdown_parser._open_caches == set()
