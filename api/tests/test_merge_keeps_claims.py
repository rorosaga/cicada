"""Audit 2026-10-05 P1-1: a merge must keep the loser's claims.

Before the fix, `merge_entities` kept only the winner's ```claims block and
deleted the loser's page, so every belief recorded about the loser — its
provenance, its supersession history — was lost. The inbox's "merge into an
existing survivor" branch did the same with a note and an episode list.
Synthetic banks only (`alpha-project`, `bob-example`).
"""
import asyncio
import subprocess
from pathlib import Path

import yaml

from api.models.schemas import InboxResolveRequest
from api.services import inbox_service, markdown_parser
from api.services.claims import Claim, Evidence, parse_claims, write_claims
from api.services.entity_merge import merge_entities


def _page(ents: Path, eid: str, fm: dict, prose: str, claims: list[Claim] | None = None) -> None:
    body = write_claims(prose, claims) if claims else prose
    markdown_parser.write(ents / f"{eid}.md", fm, body)


def _claims(path: Path) -> dict[str, Claim]:
    return {c.id: c for c in parse_claims(markdown_parser.parse(path).body, strict=True)}


def _bank(tmp_path: Path) -> Path:
    ents = tmp_path / "entities"
    ents.mkdir()
    _page(ents, "bob-example", {"name": "Bob Example", "type": "person", "confidence": 0.8,
                                "source_episodes": ["ep_2026-09-01_001"], "last_referenced": "2026-09-01"},
          "## Summary\nA person.\n",
          [Claim(id="clm_w_role", text="Bob works on alpha", subject="bob-example", predicate="works-on",
                 object="alpha-project", source_episodes=["ep_2026-09-01_001"], authored_by="model-a")])
    _page(ents, "bob-ex", {"name": "Bob Ex", "type": "person", "confidence": 0.6,
                           "source_episodes": ["ep_2026-09-20_002"], "last_referenced": "2026-09-20"},
          "## Summary\nSame person, short name. See [[Bob Ex]].\n",
          [Claim(id="clm_l_old", text="Bob lives in town A", subject="bob-ex", predicate="lives-in",
                 object="town-a", valid_from="2026-01-01", valid_to="2026-09-20",
                 superseded_by="clm_l_new", source_episodes=["ep_2026-01-01_001"], authored_by="model-a",
                 session_ids=["s-1"], evidence=[Evidence(episode="ep_2026-01-01_001", start=0, end=4,
                                                          kind="user", hash="abc")]),
           Claim(id="clm_l_new", text="Bob lives in town B", subject="bob-ex", predicate="lives-in",
                 object="town-b", valid_from="2026-09-20", supersedes="clm_l_old",
                 source_episodes=["ep_2026-09-20_002"], authored_by="claude-code", origin="mcp"),
           Claim(id="clm_l_self", text="Bob Ex is Bob", subject="bob-ex", predicate="same-as",
                 object="bob-ex")])
    _page(ents, "alpha-project", {"name": "alpha-project", "type": "project", "related": ["Bob Ex"]},
          "## Summary\nRun by [[bob-ex]].\n",
          [Claim(id="clm_a_lead", text="alpha is led by Bob", subject="alpha-project", predicate="led-by",
                 object="bob-ex")])
    return ents


def test_merge_keeps_the_losers_claims_with_their_history(tmp_path):
    ents = _bank(tmp_path)
    out = merge_entities(tmp_path, loser_id="bob-ex", winner_id="bob-example")

    assert not (ents / "bob-ex.md").exists()
    got = _claims(ents / "bob-example.md")
    assert set(got) == {"clm_w_role", "clm_l_old", "clm_l_new", "clm_l_self"}
    # Every carried claim now speaks about the winner.
    assert {c.subject for c in got.values()} == {"bob-example"}
    # The supersession chain and provenance travel unchanged.
    old, new = got["clm_l_old"], got["clm_l_new"]
    assert old.valid_to == "2026-09-20" and old.superseded_by == "clm_l_new"
    assert new.supersedes == "clm_l_old" and new.valid_to is None
    assert old.authored_by == "model-a" and old.session_ids == ["s-1"]
    assert old.evidence and old.evidence[0].kind == "user" and old.evidence[0].hash == "abc"
    assert new.origin == "mcp" and new.authored_by == "claude-code"
    # A node object that named the loser names the winner.
    assert got["clm_l_self"].object == "bob-example"
    assert "entities/bob-example.md" in out["paths"] and "entities/bob-ex.md" in out["paths"]


def test_merge_repoints_claim_objects_related_and_wikilinks_elsewhere(tmp_path):
    ents = _bank(tmp_path)
    out = merge_entities(tmp_path, loser_id="bob-ex", winner_id="bob-example")

    third = markdown_parser.parse(ents / "alpha-project.md")
    assert third.frontmatter["related"] == ["Bob Example"]
    assert "[[bob-ex]]" not in third.body
    assert _claims(ents / "alpha-project.md")["clm_a_lead"].object == "bob-example"
    assert "entities/alpha-project.md" in out["paths"]
    # The winner's own body: a wikilink to the loser is repointed, and the
    # loser's name is kept as an alias so later mentions still resolve.
    win = markdown_parser.parse(ents / "bob-example.md")
    assert "[[Bob Ex]]" not in win.body
    assert "Bob Ex" in win.frontmatter["aliases"]
    assert win.frontmatter["last_referenced"] == "2026-09-20"


def test_a_colliding_claim_id_is_kept_under_a_new_id(tmp_path):
    ents = tmp_path / "entities"
    ents.mkdir()
    _page(ents, "w", {"name": "w", "type": "tool"}, "## Summary\nw\n",
          [Claim(id="clm_same", text="winner says x", subject="w", predicate="is", object="x")])
    _page(ents, "l", {"name": "l", "type": "tool"}, "## Summary\nl\n",
          [Claim(id="clm_same", text="loser says y", subject="l", predicate="is", object="y"),
           Claim(id="clm_next", text="y became z", subject="l", predicate="is", object="z",
                 supersedes="clm_same")])
    merge_entities(tmp_path, loser_id="l", winner_id="w")
    got = list(parse_claims(markdown_parser.parse(ents / "w.md").body, strict=True))
    texts = {c.text for c in got}
    assert texts == {"winner says x", "loser says y", "y became z"}
    renamed = next(c for c in got if c.text == "loser says y")
    assert renamed.id != "clm_same"
    assert next(c for c in got if c.text == "y became z").supersedes == renamed.id


def test_an_identical_claim_on_both_pages_is_kept_once(tmp_path):
    ents = tmp_path / "entities"
    ents.mkdir()
    same = dict(id="clm_dup", text="x is y", predicate="is", object="y")
    _page(ents, "w", {"name": "w", "type": "tool"}, "## Summary\nw\n", [Claim(subject="w", **same)])
    _page(ents, "l", {"name": "l", "type": "tool"}, "## Summary\nl\n", [Claim(subject="l", **same)])
    merge_entities(tmp_path, loser_id="l", winner_id="w")
    assert [c.id for c in parse_claims(markdown_parser.parse(ents / "w.md").body)] == ["clm_dup"]


def test_a_corrupt_loser_block_aborts_the_merge(tmp_path):
    ents = tmp_path / "entities"
    ents.mkdir()
    _page(ents, "w", {"name": "w", "type": "tool"}, "## Summary\nw\n")
    (ents / "l.md").write_text("---\nname: l\n---\n\n```claims\n- id: [unclosed\n```\n")
    try:
        merge_entities(tmp_path, loser_id="l", winner_id="w")
    except Exception:
        pass
    else:
        raise AssertionError("a corrupt loser block must abort the merge")
    assert (ents / "l.md").exists()


# --- the inbox's "merge into an existing survivor" branch ----------------------


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def test_inbox_merge_into_an_existing_survivor_keeps_the_targets_claims(tmp_path):
    repo = tmp_path / "bank"
    ents = repo / "entities"
    ents.mkdir(parents=True)
    (repo / "inbox").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _page(ents, "alpha-tool-build", {"name": "alpha tool build", "type": "tool", "version": 1,
                                     "source_episodes": ["ep_old"]},
          "## Summary\nThe build.\n",
          [Claim(id="clm_t1", text="the build uses x", subject="alpha-tool-build", predicate="uses",
                 object="x", authored_by="model-a")])
    _page(ents, "alpha-tool", {"name": "alpha tool", "type": "tool", "version": 5,
                               "source_episodes": ["ep_keep"]},
          "## Summary\nThe tool.\n",
          [Claim(id="clm_s1", text="the tool is fast", subject="alpha-tool", predicate="is", object="fast")])
    _page(ents, "beta", {"name": "beta", "type": "project", "related": ["alpha-tool-build"]},
          "Uses [[alpha-tool-build]].\n")
    markdown_parser.write(repo / "inbox" / "inbox-001.md", {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending",
        "entity_name": "alpha tool", "entity_id": "alpha-tool", "merge_target_hint": "alpha-tool-build",
        "source_episode": "ep_2026-06-17_001", "created_date": "2026-06-17"}, "Possible duplicate.")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    res = asyncio.run(inbox_service.resolve(
        "inbox-001",
        InboxResolveRequest(action="merge", merge_target="alpha-tool-build", merge_survivor="alpha tool"),
        _Settings(repo)))

    assert res["status"] == "resolved"
    assert not (ents / "alpha-tool-build.md").exists()
    got = _claims(ents / "alpha-tool.md")
    assert set(got) == {"clm_s1", "clm_t1"}
    assert got["clm_t1"].subject == "alpha-tool" and got["clm_t1"].authored_by == "model-a"
    beta = markdown_parser.parse(ents / "beta.md")
    assert "[[alpha-tool-build]]" not in beta.body
    assert beta.frontmatter["related"] == ["alpha tool"]
    assert not _git(repo, "status", "--porcelain").strip()


def test_inbox_merge_renaming_to_the_cleaner_slug_repoints_its_claims_and_references(tmp_path):
    repo = tmp_path / "bank"
    ents = repo / "entities"
    ents.mkdir(parents=True)
    (repo / "inbox").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _page(ents, "alpha-tool-build", {"name": "alpha tool build", "type": "tool", "version": 1},
          "## Summary\nThe build.\n",
          [Claim(id="clm_t1", text="the build uses x", subject="alpha-tool-build", predicate="uses", object="x")])
    _page(ents, "beta", {"name": "beta", "type": "project", "related": ["alpha-tool-build"]},
          "Uses [[alpha-tool-build]].\n",
          [Claim(id="clm_b1", text="beta uses the build", subject="beta", predicate="uses",
                 object="alpha-tool-build")])
    markdown_parser.write(repo / "inbox" / "inbox-002.md", {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending",
        "entity_name": "alpha tool", "entity_id": "alpha-tool", "merge_target_hint": "alpha-tool-build",
        "source_episode": "ep_2026-06-17_001", "created_date": "2026-06-17"}, "Possible duplicate.")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    asyncio.run(inbox_service.resolve(
        "inbox-002",
        InboxResolveRequest(action="merge", merge_target="alpha-tool-build", merge_survivor="alpha tool"),
        _Settings(repo)))

    assert _claims(ents / "alpha-tool.md")["clm_t1"].subject == "alpha-tool"
    beta = markdown_parser.parse(ents / "beta.md")
    assert "[[alpha-tool-build]]" not in beta.body
    assert beta.frontmatter["related"] == ["alpha tool"]
    assert _claims(ents / "beta.md")["clm_b1"].object == "alpha-tool"


def test_a_labelled_wikilink_is_repointed_and_two_ids_for_one_file_are_refused(tmp_path):
    ents = _bank(tmp_path)
    page = ents / "alpha-project.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body.replace("[[bob-ex]]", "[[bob-ex|Bob]] and [[Bob Ex#Work]]"))
    merge_entities(tmp_path, loser_id="bob-ex", winner_id="bob-example")
    body = markdown_parser.parse(page).body
    assert "[[Bob Example|Bob]]" in body and "[[Bob Example#Work]]" in body

    import os
    other = tmp_path / "other"
    (other / "entities").mkdir(parents=True)
    _page(other / "entities", "w", {"name": "w", "type": "tool"}, "## Summary\nw\n")
    os.link(other / "entities" / "w.md", other / "entities" / "w-twin.md")
    try:
        merge_entities(other, loser_id="w-twin", winner_id="w")
    except ValueError:
        pass
    else:
        raise AssertionError("one file under two ids must not be merged")
    assert (other / "entities" / "w.md").exists()


def test_a_merge_rerun_after_a_crash_keeps_a_renamed_claim_once(tmp_path):
    ents = tmp_path / "entities"
    ents.mkdir()
    _page(ents, "w", {"name": "w", "type": "tool"}, "## Summary\nw\n",
          [Claim(id="clm_same", text="winner says x", subject="w", predicate="is", object="x")])
    loser = [Claim(id="clm_same", text="loser says y", subject="l", predicate="is", object="y")]
    _page(ents, "l", {"name": "l", "type": "tool"}, "## Summary\nl\n", loser)
    snapshot = (ents / "l.md").read_text()
    merge_entities(tmp_path, loser_id="l", winner_id="w")
    (ents / "l.md").write_text(snapshot)          # the delete never happened
    merge_entities(tmp_path, loser_id="l", winner_id="w")
    texts = [c.text for c in parse_claims(markdown_parser.parse(ents / "w.md").body)]
    assert sorted(texts) == ["loser says y", "winner says x"]


def test_a_merge_note_lands_above_the_claims_fence(tmp_path):
    repo = tmp_path / "bank"
    ents = repo / "entities"
    ents.mkdir(parents=True)
    (repo / "inbox").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _page(ents, "alpha-tool-build", {"name": "alpha tool build", "type": "tool"}, "## Summary\nThe build.\n",
          [Claim(id="clm_t1", text="the build uses x", subject="alpha-tool-build", predicate="uses", object="x")])
    markdown_parser.write(repo / "inbox" / "inbox-003.md", {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending",
        "entity_name": "alpha tool", "entity_id": "alpha-tool", "merge_target_hint": "alpha-tool-build",
        "created_date": "2026-06-17"}, "Possible duplicate.")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    asyncio.run(inbox_service.resolve(
        "inbox-003", InboxResolveRequest(action="merge", merge_target="alpha-tool-build",
                                         merge_survivor="alpha tool"), _Settings(repo)))
    text = (ents / "alpha-tool.md").read_text()
    assert text.index("_Merged") < text.index("```claims")
    assert text.rstrip().endswith("```")
