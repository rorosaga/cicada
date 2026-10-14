"""A hub's Related by meaning, not by exact verb, and a fast first card open (hub rollup, 2026-10-14).

Measured on the real bank after the first split (real values redacted): the owner's Related kept 1,676 of 2,024 lines,
because its labels are free-form ("asked how to use", "planned to use", "received recommendation for": hundreds of
verbs, the commonest three times each) and the rollup grouped by exact verb; and the first card open after a restart
took 4.85 s, most of it a YAML parse of every episode for one page's decay pace. Synthetic data only: labels are built
combinatorially from placeholder stems, names are `alpha-0001`-style.
"""
from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from api import config, main
from api.services import (
    bank_index, claims, claims_ledger, entity_body, episode_time, hub_pages, markdown_parser,
)
from api.services.claims import Claim

OWNER = "owner-example"
LEADS = ["asked how to", "asked about", "asked for help to", "wanted to", "planned to", "considered how to", "tried to",
         "learned how to", "received advice on how to", "decided to", "compared ways to", "researched how to"]
VERBS = ["use", "install", "configure", "deploy", "build", "write", "read", "apply for", "debug", "test", "upgrade",
         "migrate", "compare", "explain", "document", "review", "host", "visit", "benchmark", "design", "set up",
         "learn", "fix", "share", "publish", "record", "track", "teach", "join", "follow"]
FACTS = [("synthetic-university", "Synthetic University", "studies at", "location"),
         ("example-city", "Example City", "lives in", "location"),
         ("bob-example", "Bob Example", "sibling of", "person")]


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _page(memory: Path, eid: str, name: str, kind: str = "project") -> None:
    fm = {"name": name, "type": kind, "status": "active", "created": "2026-01-01", "related": []}
    (memory / "entities" / f"{eid}.md").write_bytes(markdown_parser._render(fm, f"## Summary\n{name}."))


def _labels(n: int) -> list[str]:
    combos = [f"{lead} {verb}" for lead in LEADS for verb in VERBS]
    random.Random(7).shuffle(combos)
    return [combos[i % len(combos)] for i in range(n)]


def _hub_bank(tmp_path: Path, *, n_pages=900, people=40, git=True, related_lines=None) -> tuple[Path, list[str]]:
    """An owner page whose Related is one line per linked page, each with a free-form label (every label used at most
    three times), its links all edges in `graph_edges.yaml` — the shape the first split left on the real bank."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    pages = [f"alpha-{i:04d}" for i in range(n_pages)]
    for i, eid in enumerate(pages):
        _page(memory, eid, eid.replace("-", " ").title(), "person" if i < people else "project")
    for eid, name, _label, kind in FACTS:
        _page(memory, eid, name, kind)
    labels = _labels(n_pages)
    edges = [{"source": OWNER, "target": eid, "label": labels[i]} for i, eid in enumerate(pages)]
    edges += [{"source": OWNER, "target": eid, "label": label} for eid, _n, label, _k in FACTS]
    (memory / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": edges}, sort_keys=False))
    lines = related_lines if related_lines is not None else (
        [f"- [[{eid.replace('-', ' ').title()}]] — {labels[i]}" for i, eid in enumerate(pages)]
        + [f"- [[{name}]] — {label}" for _e, name, label, _k in FACTS])
    rows = [Claim(id=f"clm_{i:05d}", text=f"Owner Example {labels[i]} {eid}", subject=OWNER,
                  predicate=labels[i].replace(" ", "-"), object=eid, valid_from="2026-01-01",
                  recorded_at="2026-01-01") for i, eid in enumerate(pages)]
    body = claims.write_claims("## Summary\nOwner Example.\n\n## Related\n" + "\n".join(lines), rows)
    fm = {"name": "Owner Example", "type": "person", "status": "active", "owner": True, "created": "2026-01-01",
          "source_episodes": [], "related": pages + [eid for eid, *_ in FACTS]}
    path = memory / "entities" / f"{OWNER}.md"
    path.write_bytes(markdown_parser._render(fm, body))
    if git:
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                     ["add", "."], ["commit", "-q", "-m", "Seed\n\nCicada-Author: cicada"]):
            _git(memory, *args)
    return memory, pages


def _related(memory: Path) -> str:
    return hub_pages._related_block(markdown_parser.parse(memory / "entities" / f"{OWNER}.md").body)


# --------------------------------------------------------------------------- families


@pytest.mark.parametrize("label, family", [
    ("asked how to use", "asked"), ("asked for explanation of", "asked"), ("received recommendation for", "asked"),
    ("asked about using", "asked"), ("asked-how-to-use", "asked"), ("researched how to fix", "asked"),
    ("talked about", "asked"),
    ("planned to use", "planned"), ("considered applying for", "planned"), ("wanted to install", "planned"),
    ("developed", "built"), ("wrote", "built"), ("built", "built"),
    ("worked on", "used"), ("working on", "used"), ("uses", "used"), ("tried to deploy", "used"),
    # Facts, in every inflection (review 2026-10-14): progressive and participle forms included.
    ("studies at", "relation"), ("studying at", "relation"), ("studied at", "relation"), ("enrolled in", "relation"),
    ("lives in", "relation"), ("living in", "relation"), ("lived in", "relation"), ("moved to", "relation"),
    ("works at", "relation"), ("working at", "relation"), ("worked for", "relation"), ("working for", "relation"),
    ("interning at", "relation"), ("teaching at", "relation"), ("started at", "relation"),
    ("got a job at", "relation"), ("landed a role at", "relation"), ("received degree from", "relation"),
    ("earned a master's from", "relation"), ("graduate of", "relation"), ("graduated from", "relation"),
    ("employee of", "relation"), ("founder of", "relation"), ("joined", "relation"), ("sibling of", "relation"),
    ("relates to", "other"), ("prefers", "other"), ("attended", "other"),
])
def test_a_free_form_label_falls_in_its_family_of_meaning(label, family):
    assert entity_body.relation_family(label) == family


def test_only_positive_activity_held_for_many_objects_is_a_log():
    assert entity_body.is_log("asked how to use", entity_body.RELATION_FAMILY_MAX + 1)
    assert not entity_body.is_log("asked how to use", 1)              # a single conversation: when unsure, a fact
    assert not entity_body.is_log("studies at", 500)                  # a relation never is
    assert not entity_body.is_log("prefers", 500)                     # a label no family claims never is


# The reviewer's reproductions (review 2026-10-14), kept.
@pytest.mark.parametrize("label", ["working at", "studying at", "got a job at", "received degree from"])
def test_review_an_employment_or_education_fact_is_never_a_log(label):
    assert not entity_body.is_log(label, 1), (label, entity_body.relation_family(label))
    assert not entity_body.is_log(label, 500), (label, entity_body.relation_family(label))


def test_review_a_hubs_rare_facts_keep_their_own_line_beside_many_people():
    pairs = [(f"Person {i:03d}", "talked about") for i in range(70)]
    pairs += [(f"Topic {i:03d}", "asked about") for i in range(200)]
    facts = [("Synthetic University", "graduate of"), ("Example Corp", "working at"),
             ("Example Lab", "studying at"), ("Example City", "moved to")]
    pairs += facts
    types = {f"person {i:03d}": "person" for i in range(70)}
    block = entity_body._rolled_up(pairs, types)
    missing = [f"- [[{n}]] — {v}" for n, v in facts if f"- [[{n}]] — {v}" not in block]
    assert not missing, missing
    bullets = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(bullets) <= entity_body.RELATED_MAX + len(entity_body.FAMILIES) + 3
    assert any(line.startswith("- people: ") for line in bullets)   # the people who did not fit


def test_a_rare_label_no_family_claims_outranks_people():
    pairs = [(f"Person {i:03d}", "talked about") for i in range(90)]
    pairs += [("Example Club", "prefers"), ("Example Region", "attended")]
    block = entity_body._rolled_up(pairs, {f"person {i:03d}": "person" for i in range(90)})
    assert "- [[Example Club]] — prefers" in block and "- [[Example Region]] — attended" in block


def test_a_broad_relation_family_cannot_take_every_line():
    pairs = [(f"Alpha {i:03d}", "member of") for i in range(200)]
    pairs += [(f"Beta {i:03d}", "prefers") for i in range(30)]
    block = entity_body._rolled_up(pairs, {})
    lines = [line for line in block.splitlines() if line.startswith("- [[")]
    assert sum("member of" in line for line in lines) == entity_body.RELATION_LINES_MAX
    assert sum("prefers" in line for line in lines) == entity_body.RELATED_MAX - entity_body.RELATION_LINES_MAX
    assert "- relations: " in block and "- other links: " in block


def test_a_hub_with_hundreds_of_distinct_labels_rolls_up_near_the_target():
    pairs = [(f"Alpha {i:04d}", label) for i, label in enumerate(_labels(900))]
    pairs += [(name, label) for _e, name, label, _k in FACTS]
    types = {f"alpha {i:04d}": "person" for i in range(40)} | {"bob example": "person"}
    block = entity_body._rolled_up(pairs, types)
    bullets = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(bullets) <= entity_body.RELATED_MAX + len(entity_body.FAMILIES) + 2
    for _e, name, label, _k in FACTS:
        assert f"- [[{name}]] — {label}" in block            # facts keep their own line
    assert "- [[Alpha 0039]]" in block                        # so do people
    assert any(line.startswith("- asked or learned about: ") for line in bullets)


# --------------------------------------------------------------------------- the migration, on an already-split bank


def test_a_rerun_on_an_already_split_bank_rolls_up_by_meaning_in_one_commit(tmp_path):
    memory, pages = _hub_bank(tmp_path)
    page = memory / "entities" / f"{OWNER}.md"
    ids = {c.id for c in claims.parse_claims(markdown_parser.parse(page).body)}
    before = _related(memory)
    assert before.count("\n- ") + 1 >= 900                   # one line per link, as the exact-verb rollup left it
    dry = hub_pages.survey(memory)
    assert dry.selected >= 1 and dry.failed_check == 0 and dry.related_lines_after <= 80
    assert _git(memory, "status", "--porcelain") == ""
    head = _git(memory, "rev-parse", "HEAD").strip()
    result = hub_pages.apply(memory, sleep_running=lambda: False)
    assert result.committed and result.failed_check == 0
    assert _git(memory, "rev-list", "--count", f"{head}..HEAD").strip() == "1"
    assert _git(memory, "status", "--porcelain", "--untracked-files=all") == ""
    after = _related(memory)
    assert after.count("\n- ") + 1 <= entity_body.RELATED_MAX + len(entity_body.FAMILIES) + 2
    assert "[[Synthetic University]] — studies at" in after and "[[Bob Example]] — sibling of" in after
    assert {c.id for c in claims.parse_claims(markdown_parser.parse(page).body)} == ids
    again = hub_pages.apply(memory, sleep_running=lambda: False)
    assert again.selected == 0 and not again.committed


def test_a_link_with_no_edge_and_no_slug_keeps_its_line_and_the_page_still_rolls_up(tmp_path):
    """The real bank's skipped tool page: one Related link (a name with no page) is in neither the edges nor
    `related:`. The run keeps that line as it was instead of refusing the page."""
    memory, _pages = _hub_bank(tmp_path, n_pages=100, people=0)
    page = memory / "entities" / f"{OWNER}.md"
    text = page.read_text()
    page.write_text(text.replace("## Related\n", "## Related\n- [[Qwertyuio]] — asked how to use\n", 1))
    _git(memory, "commit", "-qam", "A hand-added line\n\nCicada-Author: user")
    result = hub_pages.apply(memory, sleep_running=lambda: False)
    assert result.failed_check == 0 and result.lines_kept_as_were == 1 and result.written == 1
    assert "- [[Qwertyuio]] — asked how to use" in _related(memory)
    assert hub_pages.apply(memory, sleep_running=lambda: False).selected == 0


# --------------------------------------------------------------------------- the first card open


def _episode(memory: Path, eid: str, source: str, turns: int = 40) -> None:
    fm = {"id": eid, "timestamp": "2026-01-01T10:00:00+00:00", "source": source, "processed": True,
          "turns": [{"offset": 40 * t, "ts": "2026-01-01T10:00:00+00:00", "speaker": "user"} for t in range(turns)]}
    markdown_parser.write(memory / "episodes" / f"{eid}.md", fm, "user: synthetic")


def test_untimed_among_matches_the_full_scan_for_a_pages_conversations(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    ids = [f"ep_2026-01-{1 + i % 28:02d}_{i:03d}" for i in range(60)]
    for i, eid in enumerate(ids):
        _episode(memory, eid, "claude_memory" if i % 7 == 0 else "import")
    (memory / "episodes" / "ep_odd.md").write_text("---\nid: ep_2026-02-01_001\nsource: \"claude_memory\"\n---\nx\n")
    asked = ids[:30] + ["ep_odd"]
    assert episode_time.untimed_among(memory, asked) == episode_time.untimed_ids(memory) & set(asked)
    assert episode_time.untimed_among(memory, ["ep_missing"] + asked[:3]) == \
        episode_time.untimed_ids(memory) & {"ep_missing", *asked[:3]}       # no file of its name: the full scan


def test_a_scalar_source_episodes_reads_as_one_id_on_the_card_as_in_sleep(tmp_path):
    """A hand-edited `source_episodes: ep_x` is one id (`decay_policy._as_list`): the card's pace matches Sleep's."""
    from api.services import decay_policy

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    _episode(memory, "ep_2026-01-01_001", "claude_memory")
    fm = {"type": "concept", "source_episodes": "ep_2026-01-01_001", "last_referenced": "2026-01-01"}
    card = decay_policy.effective(fm, untimed=episode_time.untimed_among(
        memory, decay_policy._as_list(fm["source_episodes"])))
    sleep = decay_policy.effective(fm, untimed=episode_time.untimed_ids(memory))
    assert card.mention_weeks == sleep.mention_weeks


def test_a_rerun_keeps_no_stale_rollup_count(tmp_path):
    """An earlier rollup's family line whose name is no longer covered keeps that name only, never its old count."""
    memory, _pages = _hub_bank(tmp_path, n_pages=100, people=0)
    page = memory / "entities" / f"{OWNER}.md"
    text = page.read_text()
    page.write_text(text.replace("## Related\n", "## Related\n- asked or learned about: 1,203 pages — latest "
                                 "[[Qwertyuio]], [[Alpha 0001]] and 1,201 more\n", 1))
    _git(memory, "commit", "-qam", "An old rollup line\n\nCicada-Author: cicada")
    result = hub_pages.apply(memory, sleep_running=lambda: False)
    assert result.failed_check == 0 and result.written == 1
    related = _related(memory)
    assert "1,203 pages" not in related and "- [[Qwertyuio]]" in related


def _client(memory: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def test_the_hub_card_never_scans_every_episode_and_sends_no_claims(tmp_path, monkeypatch):
    memory, _pages = _hub_bank(tmp_path, n_pages=600)
    (memory / "episodes").mkdir()
    page = memory / "entities" / f"{OWNER}.md"
    eps = [f"ep_2026-01-{1 + i % 28:02d}_{i:03d}" for i in range(40)]
    for i, eid in enumerate(eps):
        _episode(memory, eid, "claude_memory" if i == 3 else "import")
    hub_pages.apply(memory, sleep_running=lambda: False)
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "source_episodes": eps}, parsed.body)
    assert claims_ledger.path_for(page).exists()

    real = bank_index.files

    def files(memory_path, subdir):
        assert subdir != "episodes", "the card parsed every episode"
        return real(memory_path, subdir)

    monkeypatch.setattr(bank_index, "files", files)
    data = _client(memory, monkeypatch).get(f"/entities/{OWNER}").json()
    assert data["rawOmitted"] and data["rawMarkdown"].startswith("---\n") and "```claims" not in data["rawMarkdown"]
    assert "## Summary" not in data["rawMarkdown"]            # the prose is markdownContent; Source reads /raw
    assert "## Summary" in data["markdownContent"]


def test_a_small_pages_card_is_unchanged(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    page = memory / "entities" / "alpha-project.md"
    body = claims.write_claims("## Summary\nAlpha.", [Claim(id="c1", text="Alpha uses Beta", subject="alpha-project",
                                                            predicate="uses", object="beta")])
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project"}, body)
    data = _client(memory, monkeypatch).get("/entities/alpha-project").json()
    assert not data["rawOmitted"] and data["rawMarkdown"] == page.read_text()


def test_a_big_fence_without_a_ledger_is_withheld_from_the_card(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    page = memory / "entities" / "alpha-project.md"
    rows = [Claim(id=f"c{i}", text=f"Alpha uses tool {i} " + "x" * 200, subject="alpha-project", predicate="uses",
                  object=f"tool-{i}") for i in range(80)]
    page.write_bytes(markdown_parser._render({"name": "Alpha Project", "type": "project"},
                                             claims.write_claims("## Summary\nAlpha.", rows)))
    data = _client(memory, monkeypatch).get("/entities/alpha-project").json()
    assert data["rawOmitted"] and "```claims" not in data["rawMarkdown"] and "## Summary" in data["rawMarkdown"]
    assert re.search(r"^---\n", data["rawMarkdown"])
