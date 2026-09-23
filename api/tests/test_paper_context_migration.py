"""F1 (R-FX4, R-FX6, R-FX7) — the one-shot repair of pre-F1 folder-paper contexts."""
from __future__ import annotations

import base64
import hashlib
import subprocess
from pathlib import Path

import yaml

from api.services import bank_index, bank_migrations, folder_source as fs, markdown_parser, papers
from api.services import paper_context_migration as mig
from api.services.claims import parse_claims, write_claims

REFERENCES = """# References

## Retrieval

- [Paper Alpha](https://arxiv.org/abs/2401.00001v2) — the architecture alpha-project builds on
- [Paper Beta](https://doi.org/10.1234/Example.5678) — why we cite it
"""
ALPHA = "media-arxiv-2401-00001"
BETA = papers.PaperKey(doi="10.1234/example.5678").entity_id


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _file(rel, text, mtime=1_756_000_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(rel, mtime, hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode())


def _bank(tmp_path: Path) -> tuple[Path, dict]:
    """A git bank holding two papers in the pre-F1 shape: the folder and section
    in `saved-because`'s context, and no projected edges."""
    bank = tmp_path / "bank"
    for sub in ("episodes", "entities", "sources"):
        (bank / sub).mkdir(parents=True)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@cicada.local")
    _git(bank, "config", "user.name", "Cicada Test")
    project_id, _ = fs.ensure_project(bank, "alpha-project", path="/Users/example/alpha-project", device="mac-1")
    folder = fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1",
                         project_id=project_id)
    bank_index.invalidate()
    staged = fs.sync(bank, folder, [_file("REFERENCES.md", REFERENCES)], [])["_staged"]
    papers.reconcile(bank, fs.get_folder(bank, folder["id"]), touched=staged.touched,
                     tombstoned=staged.tombstoned_sources, renamed=staged.renamed_sources)
    for stem in (ALPHA, BETA):
        page = bank / "entities" / f"{stem}.md"
        parsed = markdown_parser.parse(page)
        claims = parse_claims(parsed.body, strict=True)
        for c in claims:
            if c.predicate == "saved-because":
                c.context = f"folder:{folder['id']}:retrieval"
        markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))
    (bank / "graph_edges.yaml").unlink(missing_ok=True)
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "seed")
    bank_index.invalidate()
    return bank, fs.get_folder(bank, folder["id"])


def _claims(bank, stem):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{stem}.md").body)


def test_the_repair_moves_only_folder_contexts_and_keeps_every_id(tmp_path):
    bank, _ = _bank(tmp_path)
    ids_before = {c.id for s in (ALPHA, BETA) for c in _claims(bank, s)}
    report = mig.repair_paper_contexts(bank)
    assert (report["pages"], report["claims"], report["edges"]) == (2, 2, True)
    for stem in (ALPHA, BETA):
        assert {c.context for c in _claims(bank, stem)} == {"general"}
    assert {c.id for s in (ALPHA, BETA) for c in _claims(bank, s)} == ids_before


def test_the_repair_projects_the_papers_edges(tmp_path):
    bank, folder = _bank(tmp_path)
    mig.repair_paper_contexts(bank)
    edges = yaml.safe_load((bank / "graph_edges.yaml").read_text(encoding="utf-8"))["edges"]
    assert (ALPHA, "cited-in", folder["project_id"]) in {(e["source"], e["label"], e["target"]) for e in edges}


def test_the_commit_is_cicada_authored_and_holds_exactly_the_rewritten_files(tmp_path):
    bank, _ = _bank(tmp_path)
    mig.repair_paper_contexts(bank)
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == sorted(
        [f"entities/{ALPHA}.md", f"entities/{BETA}.md", "graph_edges.yaml"])


def test_it_runs_once(tmp_path):
    bank, _ = _bank(tmp_path)
    mig.repair_paper_contexts(bank)
    head = _git(bank, "rev-parse", "HEAD")
    assert mig.repair_paper_contexts(bank) == {"pages": 0, "claims": 0, "edges": False}
    assert _git(bank, "rev-parse", "HEAD") == head


def test_a_second_pass_without_the_marker_changes_nothing(tmp_path):
    bank, _ = _bank(tmp_path)
    mig.repair_paper_contexts(bank)
    head = _git(bank, "rev-parse", "HEAD")
    (bank / ".paper_contexts_v1").unlink()
    assert mig.repair_paper_contexts(bank) == {"pages": 0, "claims": 0, "edges": False}
    assert _git(bank, "rev-parse", "HEAD") == head


def test_a_full_reparse_after_the_repair_changes_no_claim(tmp_path):
    """R-FX5 — the writer mints the ids the repair left, so nothing closes or reopens."""
    bank, folder = _bank(tmp_path)
    mig.repair_paper_contexts(bank)
    bank_index.invalidate()
    assert papers.reparse_folder(bank, folder)["claims_changed"] == 0


def test_a_corrupt_claims_block_is_skipped_and_never_raises(tmp_path):
    bank, _ = _bank(tmp_path)
    page = bank / "entities" / f"{BETA}.md"
    parsed = markdown_parser.parse(page)
    fence = "`" * 3
    broken = parsed.body.split(fence + "claims")[0] + f"{fence}claims\n- id: [unclosed\n{fence}\n"
    markdown_parser.write(page, parsed.frontmatter, broken)
    before = page.read_bytes()
    report = mig.repair_paper_contexts(bank)
    assert report["pages"] == 1, "Alpha is repaired; Beta's corrupt block is skipped"
    assert page.read_bytes() == before


def test_a_page_that_cannot_be_written_keeps_the_marker_off_and_the_rest_is_committed(tmp_path, monkeypatch):
    """R-FX6 — one bad page never strands the others dirty for the next `git add -A`."""
    bank, _ = _bank(tmp_path)
    real = markdown_parser.write

    def flaky(path, frontmatter, body):
        if Path(path).stem == BETA:
            raise OSError("disk full")
        return real(path, frontmatter, body)

    monkeypatch.setattr(markdown_parser, "write", flaky)
    assert mig.repair_paper_contexts(bank)["pages"] == 1
    assert not (bank / ".paper_contexts_v1").exists(), "the next start must retry Beta"
    assert _git(bank, "status", "--porcelain", "--", f"entities/{ALPHA}.md") == ""
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")


def test_bank_migrations_runs_the_repair(tmp_path):
    bank, _ = _bank(tmp_path)
    assert bank_migrations.run_bank_migrations(bank)["paper_contexts"]["pages"] == 2
