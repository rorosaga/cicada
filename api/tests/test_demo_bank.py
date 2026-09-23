"""G117 — the demo bank is deterministic and exercises every read path a
fresh viewer's first click touches. No LLM, no network: pure file + git I/O.
"""
from __future__ import annotations

import re

from _demo_scenario import T, d, day_one, demo
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, bank_registry, claim_contexts, demo_bank, markdown_parser
from api.services.claims import parse_claims

_URL = re.compile(r"https?://[^\s)\"'>\]]+")


def _client(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    return TestClient(main.app), root


def test_populate_writes_the_expected_counts(tmp_path):
    bank_dir = tmp_path / "demo"
    bank_registry.scaffold_bank(bank_dir)
    demo_bank.populate(bank_dir)
    assert len(list((bank_dir / "entities").glob("*.md"))) >= 60
    assert len(list((bank_dir / "episodes").glob("*.md"))) >= 40
    assert len(list((bank_dir / "inbox").glob("inbox-*.md"))) == 6
    assert (bank_dir / "entities" / "bob-example.md").exists()  # placeholder owner (R7)


def test_populate_is_only_placeholder_names(tmp_path):
    bank_dir = tmp_path / "demo"
    bank_registry.scaffold_bank(bank_dir)
    demo_bank.populate(bank_dir)
    text = "\n".join(p.read_text() for p in bank_dir.rglob("*.md"))
    urls = _URL.findall(text)
    assert urls and all("://example.com" in u or ".example.com" in u for u in urls), urls  # EVERY url (spec §12)
    assert "rodrigo" not in text.lower()
    for p in (bank_dir / "entities").glob("*.md"):
        fm = markdown_parser.parse(p).frontmatter
        if fm.get("type") == "person":
            assert p.stem.endswith("-example"), p.stem   # people are placeholders by construction


def test_the_scenario_is_written_with_its_dates_and_no_facets(tmp_path):
    bank = day_one(tmp_path, index=False)
    ents = bank / "entities"
    for stem in ("rover-arm-project", "pick-and-place-demo", "lab-cluster-example", "hana-example",
                 "media-example-cluster-guide", "garden-sensor-project"):
        assert (ents / f"{stem}.md").exists(), stem
    assert markdown_parser.parse(ents / "rover-arm-project.md").frontmatter["created"] == d(-70)
    guide = markdown_parser.parse(ents / "media-example-cluster-guide.md").frontmatter
    assert guide["media"]["url"] == "https://example.com/guides/lab-cluster-onboarding.pdf"
    assert guide["decay_class"] == "evergreen"
    for p in ents.glob("*.md"):
        for c in parse_claims(markdown_parser.parse(p).body):
            assert not claim_contexts.is_facet(c.context), (p.stem, c.id)   # no satellite (R-PJ4)
    assert len(list((bank / "inbox").glob("inbox-*.md"))) == 6            # PJ-6's follow-up is off here


def test_expiry_closed_the_two_past_dues_in_its_own_commit(tmp_path):
    import subprocess
    bank = day_one(tmp_path, index=False)
    dues = [c for c in parse_claims(markdown_parser.parse(bank / "entities" / "rover-arm-project.md").body)
            if c.predicate == "due"]
    assert {c.object: c.valid_to for c in dues if c.valid_to} == {d(-42): d(-42), d(-14): d(-14)}
    log = subprocess.run(["git", "-C", str(bank), "log", "--format=%s%n%b---"], check=True,
                         capture_output=True, text=True).stdout
    assert f"Expiry {T.isoformat()}" in log and "Cicada-Author: cicada" in log


def test_a_pinned_today_is_deterministic(tmp_path):
    a, b = demo(tmp_path / "a", index=False), demo(tmp_path / "b", index=False)
    for sub in ("entities", "episodes"):
        for p in sorted((a / sub).glob("*.md")):
            if p.stem == "bob-example":
                continue   # ensure_owner_entity stamps its own created day (not the scenario's)
            assert p.read_bytes() == (b / sub / p.name).read_bytes(), p.name


def test_populate_writes_real_git_history_with_trailers(tmp_path):
    """R7's `_commit_history` groups writes the way a real Sleep cycle would
    (Sleep-cycle commits with Cicada-Author/Cicada-Engine trailers, one
    Cicada-Author: user commit for the owner page) — so a fresh demo bank's
    `GET /contributors` and entity-history views have something real to show
    rather than one big untrailered commit."""
    import subprocess

    bank_dir = tmp_path / "demo"
    bank_registry.scaffold_bank(bank_dir)
    demo_bank.populate(bank_dir)
    log = subprocess.run(
        ["git", "-C", str(bank_dir), "log", "--format=%B---END---"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "Cicada-Author:" in log
    assert "Cicada-Author: user" in log
    assert log.count("---END---") >= 2  # more than one commit


def test_endpoint_creates_and_activates(tmp_path, monkeypatch):
    client, root = _client(tmp_path, monkeypatch)
    resp = client.post("/banks/demo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] == "demo"
    assert any(b["name"] == "demo" for b in body["banks"])

    # Every read path the sheet's "try it" flow touches must answer.
    assert client.get("/graph").status_code == 200
    assert client.get("/inbox").status_code == 200
    assert client.get("/sleep/episodes").status_code == 200
    assert client.get("/sources/overview").status_code == 200


def test_endpoint_is_409_if_demo_already_exists(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.post("/banks/demo").status_code == 200
    assert client.post("/banks/demo").status_code == 409


def test_the_event_commits_are_authored_by_who_wrote_them_and_store_nothing_relative(tmp_path):
    """G141 PJ-3a (T5): the S1/S3/S5 happenings land in a Sleep-shaped commit
    and S7's two in an `Agent write` under `claude-code`; the R-PJ6 gate holds
    over every event claim in the bank — no relative word in what is stored."""
    import subprocess

    from api.services import when
    from api.services.claims import is_event

    bank = demo(tmp_path, index=False, person=False, followups=False)
    log = subprocess.run(["git", "-C", str(bank), "log", "--format=%s%n%b---END---"], check=True,
                         capture_output=True, text=True).stdout
    agent = next(c for c in log.split("---END---") if c.strip().startswith(f"Agent write {T.isoformat()}"))
    assert "Cicada-Author: claude-code" in agent and "Cicada-Session: ses_demo_rover_02" in agent
    assert "trigger: mcp/claude-code" in agent and "entities/pick-and-place-demo.md" in agent
    assert any("trigger: sleep/extraction" in c and "Cicada-Author: gpt-5.4-mini" in c
               and "entities/rover-arm-project.md" in c for c in log.split("---END---")[:2])
    events = [c for p in (bank / "entities").glob("*.md")
              for c in parse_claims(markdown_parser.parse(p).body) if is_event(c)]
    assert len(events) == 5
    for c in events:
        for value in (c.text, c.valid_from, c.target, c.status):
            assert not when.RELATIVE_GREP.search(str(value or "")), (c.id, value)
