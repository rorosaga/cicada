"""F1 (R-FX10) — the one-shot rewrite of `agentic_write`'s placeholder pages."""
from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import bank_migrations, entity_body, markdown_parser
from api.services import placeholder_summary_migration as mig
from api.services.claims import Claim, parse_claims, strip_claims_block, write_claims

FENCE = "`" * 3
OPEN = [
    Claim(id="clm_a1", text="alpha-project depends-on sqlite-vec", subject="alpha-project",
          predicate="depends-on", object="sqlite-vec"),
    Claim(id="clm_a2", text="Alpha Project ships a macOS app", subject="alpha-project",
          predicate="ships", object="a macOS app"),
    Claim(id="clm_a3", text="alpha-project uses postgres", subject="alpha-project", predicate="uses",
          object="postgres", valid_to="2026-05-01", superseded_by="clm_a1"),
]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _page(bank, stem, *, summary, claims, type_="concept"):
    body = entity_body.compose_body_v2(summary=summary, key_facts=[], history_entries=[], related=[],
                                       links=[], open_questions=[])
    markdown_parser.write(bank / "entities" / f"{stem}.md",
                          {"name": stem.replace("-", " ").title(), "type": type_, "layout_version": 2},
                          write_claims(body, claims))


def _bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@cicada.local")
    _git(bank, "config", "user.name", "Cicada Test")
    _page(bank, "alpha-project", summary="Alpha Project — created via agentic write.", claims=OPEN)
    _page(bank, "bob-example", claims=OPEN[:1],
          summary="Bob Example — created via agentic write.\nBob Example leads a team.")
    _page(bank, "gamma-project", summary="Gamma Project — created via agentic write.", claims=OPEN[2:])
    _page(bank, "media-example", summary="Media Example — created via agentic write.", claims=OPEN[:1],
          type_="media")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "seed")
    return bank


def _body(bank, stem):
    return markdown_parser.parse(bank / "entities" / f"{stem}.md").body


def test_only_a_one_line_placeholder_with_an_open_claim_is_rewritten(tmp_path):
    bank = _bank(tmp_path)
    before = {s: _body(bank, s) for s in ("bob-example", "gamma-project", "media-example")}
    fm_before = markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter
    assert mig.rewrite_placeholder_summaries(bank) == 1
    body = _body(bank, "alpha-project")
    assert strip_claims_block(body) == \
        "## Summary\nAlpha-project depends on sqlite-vec. Alpha Project ships a macOS app."
    assert [c.to_dict() for c in parse_claims(body)] == [c.to_dict() for c in OPEN]
    assert body.rstrip().endswith(FENCE), "the fence stays where write_claims puts it (R-FX8)"
    assert markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter == fm_before
    for stem, text in before.items():
        assert _body(bank, stem) == text, stem


def test_the_commit_is_cicada_authored_and_holds_exactly_the_rewritten_page(tmp_path):
    bank = _bank(tmp_path)
    mig.rewrite_placeholder_summaries(bank)
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == ["entities/alpha-project.md"]


def test_it_runs_once_and_a_second_pass_changes_nothing(tmp_path):
    bank = _bank(tmp_path)
    mig.rewrite_placeholder_summaries(bank)
    head = _git(bank, "rev-parse", "HEAD")
    assert mig.rewrite_placeholder_summaries(bank) == 0
    (bank / ".placeholder_summaries_v1").unlink()
    assert mig.rewrite_placeholder_summaries(bank) == 0
    assert _git(bank, "rev-parse", "HEAD") == head


def test_a_page_that_cannot_be_written_keeps_the_marker_off_and_the_rest_is_committed(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    _page(bank, "delta-project", summary="Delta Project — created via agentic write.", claims=OPEN[:1])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "delta")
    real = markdown_parser.write

    def flaky(path, frontmatter, body):
        if Path(path).stem == "delta-project":
            raise OSError("disk full")
        return real(path, frontmatter, body)

    monkeypatch.setattr(markdown_parser, "write", flaky)
    assert mig.rewrite_placeholder_summaries(bank) == 1
    assert not (bank / ".placeholder_summaries_v1").exists(), "the next start must retry delta-project"
    assert _git(bank, "status", "--porcelain", "--", "entities/alpha-project.md") == ""


def test_bank_migrations_runs_it(tmp_path):
    assert bank_migrations.run_bank_migrations(_bank(tmp_path))["placeholders"] == 1
