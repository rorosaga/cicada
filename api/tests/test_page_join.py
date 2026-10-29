"""G227 follow-up (owner 2026-10-29): any join can be undone — merge two pages, split one, each one commit, each undone
from the page's history; a split pair is never joined back; a merged-away id keeps resolving.

Synthetic bank only: one title (`tool-x`) shared by a code editor and an accelerator program, `alpha-project`,
`bob-example`.
"""
import subprocess
from pathlib import Path

import pytest
import yaml

from api.services import bank_index, markdown_parser, merge_rejections, page_join, page_redirects
from api.services.claims import Claim, parse_claims, write_claims
from api.services.id_utils import resolve_entity_file

EDITOR = "Tool X is a code editor with an agent built in."
PROGRAM_1 = "Tool X is also the name of an accelerator program for early teams."
PROGRAM_2 = "The person applied to the Tool X program in the spring cohort."
EDITOR_2 = "It opens large repositories quickly and runs agents in the background."


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _page(memory: Path, eid: str, fm: dict, prose: str, claims=None) -> None:
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, write_claims(prose, claims) if claims else prose)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    _page(memory, "tool-x", {"name": "Tool X", "type": "tool", "status": "active", "confidence": 0.8,
                             "source_episodes": ["ep_2026-05-01_001", "ep_2026-06-01_001"],
                             "sources": [{"ref": "https://tool-x.example/", "added_by": "user"},
                                         {"ref": "https://program.example/apply", "added_by": "user"}]},
          f"## Summary\n{EDITOR} {PROGRAM_1}\n\n## Key Facts\n- {PROGRAM_2}\n- {EDITOR_2}\n",
          [Claim(id="clm_editor", text="Tool X is a code editor", subject="tool-x", predicate="is-a",
                 object="code editor", object_kind="literal", source_episodes=["ep_2026-05-01_001"]),
           Claim(id="clm_applied", text="applied to Tool X", subject="tool-x", predicate="applied-by",
                 object="owner-example", source_episodes=["ep_2026-06-01_001"])])
    _page(memory, "alpha-project", {"name": "alpha-project", "type": "project"},
          "## Summary\nBuilt with [[tool-x]].\n",
          [Claim(id="clm_alpha_uses", text="alpha uses Tool X", subject="alpha-project", predicate="uses",
                 object="tool-x", source_episodes=["ep_2026-05-01_001"])])
    _page(memory, "bob-example", {"name": "Bob Example", "type": "person"},
          "## Summary\nBob mentors at [[Tool X]].\n",
          [Claim(id="clm_bob_mentor", text="Bob mentors at the Tool X program", subject="bob-example",
                 predicate="mentors-at", object="tool-x", source_episodes=["ep_2026-06-01_001"])])
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "seed")
    bank_index.invalidate()
    page_redirects.invalidate()
    return memory


def _fm(memory, eid):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter


def _body(memory, eid):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").body


def _clean(memory):
    return _git(memory, "status", "--porcelain").strip() == ""


def _split(memory, **kw):
    plan = page_join.split_plan(memory, "tool-x")
    picks = [s["n"] for s in plan["sentences"] if "program" in s["text"]]
    args = dict(sentences=picks, claims=["clm_applied"], sources=["https://program.example/apply"],
                episodes=["ep_2026-06-01_001"], entity_type="project")
    args.update(kw)
    return page_join.split(memory, "tool-x", **args)


def test_split_moves_what_was_picked_to_a_new_page_with_the_same_clean_title(bank):
    out = _split(bank)
    assert out["new_id"] == "tool-x-2" and out["new_name"] == "Tool X"
    old, new = _body(bank, "tool-x"), _body(bank, "tool-x-2")
    assert EDITOR in old and EDITOR_2 in old
    assert PROGRAM_1 not in old and PROGRAM_2 not in old
    assert PROGRAM_1 in new and PROGRAM_2 in new and EDITOR not in new
    assert [c.id for c in parse_claims(old)] == ["clm_editor"]
    moved = parse_claims(new)
    assert [(c.id, c.subject) for c in moved] == [("clm_applied", "tool-x-2")]
    nfm = _fm(bank, "tool-x-2")
    assert nfm["name"] == "Tool X" and nfm["type"] == "project"
    assert nfm["source_episodes"] == ["ep_2026-06-01_001"]
    assert [s["ref"] for s in nfm["sources"]] == ["https://program.example/apply"]
    assert _fm(bank, "tool-x")["source_episodes"] == ["ep_2026-05-01_001"]
    assert merge_rejections.is_split(bank, "tool-x", "tool-x-2")
    # A split pair keeps the PAGES apart, never the name from either page (the resolver's rejected pairs).
    assert ("tool-x", "tool-x-2") not in merge_rejections.load_rejected(bank)
    assert _clean(bank)
    assert _git(bank, "log", "-1", "--format=%s").startswith(page_join.SUBJECT_SPLIT)


def test_split_repoints_a_link_only_where_its_evidence_says_which_one(bank):
    out = _split(bank)
    # bob's claim rests only on the conversation that moved: it meant the program.
    assert out["repointed"] == ["bob-example"]
    bob = _body(bank, "bob-example")
    assert [c.object for c in parse_claims(bob)] == ["tool-x-2"]
    assert "[[tool-x-2|Tool X]]" in bob
    # alpha's rests on the conversation that stayed: it keeps the editor.
    alpha = _body(bank, "alpha-project")
    assert [c.object for c in parse_claims(alpha)] == ["tool-x"] and "[[tool-x]]" in alpha


def test_the_persons_word_on_a_link_outranks_the_evidence(bank):
    out = _split(bank, references={"bob-example": "stay", "alpha-project": "new"})
    assert out["repointed"] == ["alpha-project"]
    assert [c.object for c in parse_claims(_body(bank, "bob-example"))] == ["tool-x"]


def test_the_plan_numbers_sentences_and_says_what_each_link_rests_on(bank):
    plan = page_join.split_plan(bank, "tool-x")
    assert [s["text"] for s in plan["sentences"]][:2] == [EDITOR, PROGRAM_1]
    refs = {r["page_id"]: r for r in plan["references"]}
    assert refs["bob-example"]["episodes"] == ["ep_2026-06-01_001"]
    assert plan["new_id"] == "tool-x-2"


def test_reference_choice_never_guesses():
    moved, staying = {"e2"}, {"e1"}
    assert page_join.reference_choice(["e2"], moved, staying) == "new"
    assert page_join.reference_choice(["e1"], moved, staying) == "stay"
    assert page_join.reference_choice(["e1", "e2"], moved, staying) == "ask"
    assert page_join.reference_choice([], moved, staying) == "ask"
    assert page_join.reference_choice(["e9"], moved, staying) == "ask"


def test_split_refuses_with_nothing_picked_and_writes_nothing(bank):
    with pytest.raises(page_join.JoinError):
        page_join.split(bank, "tool-x")
    with pytest.raises(page_join.JoinError):
        page_join.split(bank, "tool-x", sentences=[1], claims=["clm_nope"])
    assert _clean(bank) and not (bank / "entities" / "tool-x-2.md").exists()


def test_undo_a_split_puts_everything_back(bank):
    before = {p.name: p.read_bytes() for p in (bank / "entities").glob("*.md")}
    out = _split(bank)
    undone = page_join.undo(bank, out["commit"])
    assert undone["kind"] == "split"
    after = {p.name: p.read_bytes() for p in (bank / "entities").glob("*.md")}
    assert after == before
    assert not merge_rejections.is_split(bank, "tool-x", "tool-x-2")
    assert _clean(bank)
    with pytest.raises(page_join.JoinError) as again:
        page_join.undo(bank, out["commit"])
    assert again.value.status == 409


def test_merge_folds_the_page_leaves_a_redirect_and_clears_the_split(bank):
    out = _split(bank)
    merged = page_join.merge(bank, "tool-x-2", "tool-x")
    assert merged["winner"] == "tool-x" and not (bank / "entities" / "tool-x-2.md").exists()
    body = _body(bank, "tool-x")
    assert PROGRAM_1 in body and {c.id for c in parse_claims(body)} == {"clm_editor", "clm_applied"}
    assert not merge_rejections.is_split(bank, "tool-x", "tool-x-2")
    assert page_redirects.resolve(bank, "tool-x-2") == "tool-x"
    assert resolve_entity_file(bank, "tool-x-2").stem == "tool-x"
    assert yaml.safe_load((bank / "_redirects.yaml").read_text())["redirects"] == {"tool-x-2": "tool-x"}
    assert _clean(bank)
    # Undo the merge: the split pages come back, the redirect goes, the pair is kept apart again.
    page_join.undo(bank, merged["commit"])
    assert (bank / "entities" / "tool-x-2.md").exists()
    assert page_redirects.resolve(bank, "tool-x-2") is None
    assert merge_rejections.is_split(bank, "tool-x", "tool-x-2")
    assert PROGRAM_1 not in _body(bank, "tool-x")
    assert _clean(bank)
    # And the split itself can still be undone after.
    page_join.undo(bank, out["commit"])
    assert not (bank / "entities" / "tool-x-2.md").exists()


def test_merge_lifts_a_held_mentions_another_one_between_the_two(bank):
    from api.services import pending_store

    _split(bank)
    pending_store.upsert(bank, pending_store.PendingEntity(name="Tool X", type="tool", description="",
                                                           source_episode="ep_2026-07-01_001", confidence=0.5,
                                                           tags=[], history_entries=[]))
    assert pending_store.mark_apart(bank, "Tool X", ["tool-x-2"])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "held")
    page_join.merge(bank, "tool-x", "tool-x-2")
    line = next(e for e in pending_store.load(bank) if e.name == "Tool X")
    assert "tool-x-2" not in line.apart_pages(), "the person joined them: their 'Another one' no longer holds"
    assert _clean(bank)


def test_undo_refuses_when_the_same_place_changed_since(bank):
    out = _split(bank)
    path = bank / "entities" / "tool-x-2.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body.replace(PROGRAM_1, "Rewritten since."))
    _git(bank, "commit", "-qam", "later edit")
    with pytest.raises(page_join.JoinError) as err:
        page_join.undo(bank, out["commit"])
    assert err.value.status == 409
    assert path.exists()


def test_undo_is_only_for_joins(bank):
    head = _git(bank, "rev-parse", "HEAD").strip()
    with pytest.raises(page_join.JoinError) as err:
        page_join.undo(bank, head)
    assert err.value.status == 404


def test_sleep_never_settles_a_split_pair_as_duplicates(bank):
    from api.services import inbox_tend

    _split(bank)
    fm = {"merge_target_hint": "tool-x-2", "entity_id": "tool-x", "entity_name": "Tool X"}
    decision, why = inbox_tend._merge_rule(bank, "inbox-001", fm)
    assert decision is None and why == "kept_apart"


def test_a_redirect_never_shadows_a_page_and_never_loops(bank):
    page_redirects.add(bank, "gone-a", "gone-b")
    page_redirects.add(bank, "gone-b", "gone-a")
    assert page_redirects.resolve(bank, "gone-a") is None
    page_redirects.add(bank, "alpha-project", "bob-example")
    assert page_redirects.resolve(bank, "alpha-project") is None   # a page that exists always wins


# --------------------------------------------------------------------------- the agent doors


def _ctx(memory, harness="claude-code"):
    from api.services import mcp_tools

    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s-1", harness=harness,
                                 post=lambda path, payload: {})


def test_a_trusted_agent_splits_at_once_under_its_own_name(bank):
    from api.services import mcp_tools

    plan = mcp_tools.split_page(_ctx(bank), "tool-x", preview=True)
    assert "2. [Summary] " + PROGRAM_1 in plan and "bob-example" in plan
    out = mcp_tools.split_page(_ctx(bank), "tool-x", "the person said the program is a different thing",
                               sentences=[2, 3], claims=["clm_applied"], episodes=["ep_2026-06-01_001"])
    assert "moved to `tool-x-2`" in out
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith(page_join.SUBJECT_SPLIT) and "Cicada-Author: claude-code" in log
    assert "Reason: the person said the program is a different thing" in log


def test_an_unlisted_agent_proposes_and_the_person_applies_it(bank):
    import asyncio
    from types import SimpleNamespace

    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service, mcp_tools

    out = mcp_tools.merge_pages(_ctx(bank, harness="cursor"), "bob-example", "alpha-project", "same thing")
    assert "Proposed, not applied" in out and (bank / "entities" / "bob-example.md").exists()
    item = next((bank / "inbox").glob("inbox-*.md"))
    fm = markdown_parser.parse(item).frontmatter
    assert fm["kind"] == "page_edit" and fm["join"] == {"op": "merge", "into": "alpha-project"}
    assert _clean(bank)
    asyncio.run(inbox_service.resolve(item.stem, InboxResolveRequest(action="resolve", option_key="apply"),
                                      SimpleNamespace(memory_path=bank, inbox_defer_days=30)))
    assert not (bank / "entities" / "bob-example.md").exists() and not item.exists()
    log = _git(bank, "log", "-1", "--format=%B", "--", "entities/bob-example.md")
    assert log.startswith(page_join.SUBJECT_MERGE) and f"inbox/{item.name}: removed" in log
    assert "Cicada-Author: cursor" in log and "Cicada-Author: user" in log
    assert _clean(bank)


def test_a_remote_app_cannot_merge_or_split(bank):
    from api.services import mcp_tools

    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="claude-web",
                                connector_id="ab12cd34")
    assert "remote app" in mcp_tools.merge_pages(ctx, "bob-example", "alpha-project", "same")
    assert "remote app" in mcp_tools.split_page(ctx, "tool-x", "x", sentences=[2])
    assert _clean(bank)


# --------------------------------------------------------------------------- the app's door


def test_the_routes_split_merge_undo_and_redirect(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        plan = client.get("/entities/tool-x/split-plan").json()
        picks = [s["n"] for s in plan["sentences"] if "program" in s["text"]]
        r = client.post("/entities/tool-x/split", json={"sentences": picks, "claims": ["clm_applied"],
                                                         "episodes": ["ep_2026-06-01_001"]})
        assert r.status_code == 200, r.text
        split_commit = r.json()["commit"]
        assert r.json()["otherId"] == "tool-x-2"
        rows = client.get("/entities/tool-x-2/history?summary=true").json()
        assert rows[0]["join"] == "split" and rows[0]["undoable"] is True
        r = client.post("/entities/tool-x-2/merge", json={"into": "tool-x"})
        assert r.status_code == 200 and r.json()["entityId"] == "tool-x"
        # The retired id still opens the page it became.
        card = client.get("/entities/tool-x-2")
        assert card.status_code == 200 and card.json()["id"] == "tool-x"
        assert card.headers["x-cicada-redirected-from"] == "tool-x-2"
        r = client.post(f"/entities/tool-x/history/{r.json()['commit']}/undo")
        assert r.status_code == 200 and r.json()["restored"] == ["tool-x-2"]
        rows = client.get("/entities/tool-x/history?summary=true").json()
        assert rows[0]["join"] == "undo" and rows[1]["join"] == "merge" and rows[1]["undoable"] is False
        assert client.post(f"/entities/tool-x/history/{split_commit}/undo").status_code == 200
        assert client.post(f"/entities/tool-x/history/{split_commit}/undo").status_code == 409
        assert client.post("/entities/tool-x/split", json={}).status_code == 400
        assert _clean(bank)
    finally:
        config.get_settings.cache_clear()
