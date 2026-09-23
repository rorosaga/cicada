"""F2-back R-B12, R-B13 — paper why-claims never carry in-document anchors or
footnote markers; the episode keeps them, ids never move, and existing banks
are repaired once."""
from __future__ import annotations

import base64
import hashlib
import subprocess
from pathlib import Path

import pytest

from api.services import bank_index, bank_migrations, folder_source as fs, markdown_parser, papers
from api.services import paper_claim_text_migration as mig
from api.services.claims import parse_claims, write_claims

NOISY = "the architecture alpha-project builds on [N50](#note-n50)."
CLEAN = "the architecture alpha-project builds on."
REFS = f"# References\n\n## Retrieval\n\n- [Paper Alpha](https://arxiv.org/abs/2401.00001) — {NOISY}\n"
ALPHA = "media-arxiv-2401-00001"


@pytest.mark.parametrize("raw, want", [
    ("Great baseline for retrieval [N50](#note-n50).", "Great baseline for retrieval."),
    ("Great baseline for retrieval ([N50](#note-n50)).", "Great baseline for retrieval."),
    ("Compare with [the method section](#method) here", "Compare with the method section here"),
    ("Strong results[^3] on long context", "Strong results on long context"),
    ("Anchors [N1](#n1), [N2](#n2), and more", "Anchors, and more"),
    ("Why it matters [N50](#note-n50), [N51](#note-n51)", "Why it matters"),
    ("Retrieval [↩](#top)", "Retrieval"),
    ("Cited twice [^a][^b].", "Cited twice."),
    ("[N50](#note-n50)", ""),
    # Untouched: no in-document link and no footnote marker.
    ("Uses [a public link](https://example.com/a) too", "Uses [a public link](https://example.com/a) too"),
    ("Two  spaces stay when nothing was stripped", "Two  spaces stay when nothing was stripped"),
])
def test_clean_claim_text(raw, want):
    assert papers.clean_claim_text(raw) == want


def _file(rel, text, mtime=1_756_000_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(rel, mtime, hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode())


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _bank(tmp_path: Path, *, git: bool = False) -> tuple[Path, dict]:
    bank = tmp_path / "bank"
    for sub in ("episodes", "entities", "sources"):
        (bank / sub).mkdir(parents=True)
    if git:
        _git(bank, "init", "-q")
        _git(bank, "config", "user.email", "test@example.com")
        _git(bank, "config", "user.name", "Cicada Test")
    project_id, _ = fs.ensure_project(bank, "alpha-project", path="/Users/example/alpha-project", device="mac-1")
    folder = fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1",
                         project_id=project_id)
    return bank, folder


def _sync(bank, folder, files):
    bank_index.invalidate()
    staged = fs.sync(bank, folder, files, [])["_staged"]
    return papers.reconcile(bank, fs.get_folder(bank, folder["id"]), touched=staged.touched,
                            tombstoned=staged.tombstoned_sources, renamed=staged.renamed_sources)


def _saved(bank):
    return [c for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{ALPHA}.md").body)
            if c.predicate == "saved-because"]


# --- R-B12: the writer -------------------------------------------------------


def test_a_noisy_note_is_written_clean_and_its_span_still_points_at_the_raw_words(tmp_path):
    bank, folder = _bank(tmp_path)
    _sync(bank, folder, [_file("REFERENCES.md", REFS)])
    (claim,) = _saved(bank)
    assert (claim.text, claim.object) == (CLEAN, CLEAN)
    body = markdown_parser.parse(next((bank / "episodes").glob("ep_*.md"))).body
    assert "[N50](#note-n50)" in body, "the episode keeps its anchors (G118: spans, not copies)"
    (ev,) = claim.evidence
    assert body[ev.start:ev.end] == NOISY
    assert claim.id == papers.claim_id(ALPHA, "saved-because", NOISY, "owner", f"folder:{folder['id']}:retrieval")


def test_a_note_of_only_anchors_writes_no_reason(tmp_path):
    bank, folder = _bank(tmp_path)
    only = "## Retrieval\n\n- [Paper Alpha](https://arxiv.org/abs/2401.00001) — [N50](#note-n50)\n"
    _sync(bank, folder, [_file("REFERENCES.md", only)])
    assert _saved(bank) == []


def test_an_agent_files_paper_claims_are_the_agents(tmp_path):
    """R-B11's paper half: `authored_by` was None — "Before provenance" in the app."""
    bank, folder = _bank(tmp_path)
    _sync(bank, folder, [_file("archive/sweep.md", "See arXiv:2401.00009 for more.")])
    (cited,) = [c for c in parse_claims(markdown_parser.parse(bank / "entities" / "media-arxiv-2401-00009.md").body)
                if c.predicate == "cited-in"]
    assert cited.authored_by == "agent"


def _make_noisy(bank):
    """The pre-fix shape: the anchor inside the stored text and object."""
    page = bank / "entities" / f"{ALPHA}.md"
    parsed = markdown_parser.parse(page)
    claims = parse_claims(parsed.body, strict=True)
    for c in claims:
        if c.predicate == "saved-because":
            c.text = c.object = NOISY
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))


def test_a_sync_repairs_noisy_words_on_a_claim_it_re_reads(tmp_path):
    bank, folder = _bank(tmp_path)
    _sync(bank, folder, [_file("REFERENCES.md", REFS)])
    ids = {c.id for c in _saved(bank)}
    _make_noisy(bank)
    _sync(bank, folder, [_file("REFERENCES.md", "Intro.\n\n" + REFS, mtime=1_756_100_000.0)])
    (claim,) = _saved(bank)
    assert (claim.text, claim.object, claim.valid_to) == (CLEAN, CLEAN, None)
    assert {claim.id} == ids


# --- R-B13: the one-shot repair ----------------------------------------------


def _seeded(tmp_path):
    bank, folder = _bank(tmp_path, git=True)
    _sync(bank, folder, [_file("REFERENCES.md", REFS)])
    _make_noisy(bank)
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "seed")
    bank_index.invalidate()
    return bank, folder


def test_the_repair_cleans_the_words_and_keeps_every_id(tmp_path):
    bank, _ = _seeded(tmp_path)
    ids = {c.id for c in _saved(bank)}
    assert mig.repair_paper_claim_text(bank) == {"pages": 1, "claims": 1}
    (claim,) = _saved(bank)
    assert (claim.text, claim.object) == (CLEAN, CLEAN) and {claim.id} == ids


def test_the_commit_is_cicada_authored_and_holds_exactly_the_rewritten_page(tmp_path):
    bank, _ = _seeded(tmp_path)
    mig.repair_paper_claim_text(bank)
    body = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in body and "trigger: maintenance/paper_claim_text" in body
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == [f"entities/{ALPHA}.md"]


def test_it_runs_once_and_a_second_pass_changes_nothing(tmp_path):
    bank, _ = _seeded(tmp_path)
    mig.repair_paper_claim_text(bank)
    head = _git(bank, "rev-parse", "HEAD")
    assert mig.repair_paper_claim_text(bank) == {"pages": 0, "claims": 0}
    (bank / ".paper_claim_text_v1").unlink()
    assert mig.repair_paper_claim_text(bank) == {"pages": 0, "claims": 0}
    assert _git(bank, "rev-parse", "HEAD") == head


def test_a_full_reparse_after_the_repair_changes_no_claim(tmp_path):
    bank, folder = _seeded(tmp_path)
    mig.repair_paper_claim_text(bank)
    bank_index.invalidate()
    assert papers.reparse_folder(bank, fs.get_folder(bank, folder["id"]))["claims_changed"] == 0


def test_a_page_that_cannot_be_written_keeps_the_marker_off(tmp_path, monkeypatch):
    bank, _ = _seeded(tmp_path)
    real = markdown_parser.write

    def flaky(path, frontmatter, body):
        if Path(path).stem == ALPHA:
            raise OSError("disk full")
        return real(path, frontmatter, body)

    monkeypatch.setattr(markdown_parser, "write", flaky)
    assert mig.repair_paper_claim_text(bank) == {"pages": 0, "claims": 0}
    assert not (bank / ".paper_claim_text_v1").exists(), "the next start retries"


def test_a_corrupt_claims_block_is_skipped_and_never_raises(tmp_path):
    bank, _ = _seeded(tmp_path)
    page = bank / "entities" / f"{ALPHA}.md"
    parsed = markdown_parser.parse(page)
    fence = "`" * 3
    markdown_parser.write(page, parsed.frontmatter,
                          parsed.body.split(fence + "claims")[0] + f"{fence}claims\n- id: [unclosed\n{fence}\n")
    before = page.read_bytes()
    assert mig.repair_paper_claim_text(bank) == {"pages": 0, "claims": 0}
    assert page.read_bytes() == before


def test_bank_migrations_runs_the_repair(tmp_path):
    bank, _ = _seeded(tmp_path)
    assert bank_migrations.run_bank_migrations(bank)["paper_claim_text"] == {"pages": 1, "claims": 1}
