"""One person, one page (G209): an alias, a linked account or a "Name (handle)" mention is a lead that raises the
"Possible duplicate" question — never a merge on its own.

The live failure: a full-name page listing a handle among its aliases, a page titled by that handle, and a pending line
"handle (Full Name)", both pages born in one Sleep run. Stage 2 compared an in-cycle create by name only, an exact page
always won over another page's alias, and the parenthetical form parked as a literal name. Synthetic data only.
"""
import asyncio
from types import SimpleNamespace

import pytest

from api.services import entity_resolver as er
from api.services import markdown_parser, pending_store, person_leads
from api.services.vector_index import PendingEntity


# ---------- the leads themselves ----------

@pytest.mark.parametrize("name, expected", [
    ("Bob Example (bexample)", ("Bob Example", "bexample")),
    ("bexample (Bob Example)", ("Bob Example", "bexample")),
    ("@bex42 (Bob Example)", ("Bob Example", "@bex42")),
    ("Bob Example (CEO)", None),          # a capitalised word is not a handle
    ("Bob Example (mom)", None),          # a relation word is never a handle
    ("Bob Example (she/her)", None),
    ("Bob (bexample)", None),             # one word is not a full name
    ("Bob Example", None),
])
def test_a_named_handle_splits_only_when_one_side_is_a_handle_and_the_other_a_full_name(name, expected):
    assert person_leads.split_named_handle(name) == expected


@pytest.mark.parametrize("url, expected", [
    ("https://x.com/bexample", ("x", "bexample")),
    ("https://twitter.com/bexample/status/123", ("x", "bexample")),
    ("https://github.com/bexample", ("github", "bexample")),
    ("https://github.com/example-org/repo", None),       # a repository is not its owner's profile
    ("https://www.linkedin.com/in/bob-example-1/", ("linkedin", "bob-example-1")),
    ("https://www.instagram.com/bexample/", ("instagram", "bexample")),
    ("https://x.com/search?q=bob", None),
    ("https://example.com/bexample", None),
])
def test_only_a_profile_link_names_an_account(url, expected):
    assert person_leads.profile_handle(url) == expected


def _page(name, etype="person", aliases=(), body=None, sources=()):
    fm = {"name": name, "type": etype, "confidence": 0.8, **({"aliases": list(aliases)} if aliases else {}),
          **({"sources": list(sources)} if sources else {})}
    return {"id": name.lower().replace(" ", "-").lstrip("@"), "frontmatter": fm,
            "body": body if body is not None else f"## Summary\nA synthetic page about {name}."}


def test_the_index_finds_an_alias_and_a_linked_account_in_both_directions():
    pages = [_page("Bob Example", aliases=["bexample"]), _page("bexample"),
             _page("Ann Sample", body="## Links\n- [profile](https://github.com/asample)"), _page("asample"),
             _page("Example Corp", etype="company", aliases=["bexample"])]
    index = person_leads.PersonIndex(pages)
    leads = {(lead.page, lead.holder, lead.kind) for lead in index.all_leads()}
    assert leads == {("bexample", "bob-example", "alias"), ("asample", "ann-sample", "profile:github")}
    assert {(l.page, l.holder) for l in index.leads_for("bob-example")} == {("bexample", "bob-example")}
    assert {(l.page, l.holder) for l in index.leads_for("bexample")} == {("bexample", "bob-example")}


# ---------- Stage 2 ----------

def _settings(bank, concurrency=1):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           sleep_promotion_threshold=2, sleep_resolve_concurrency=concurrency)


def _mention(name, n, aliases=(), confidence=0.7):
    ep = f"ep_2026-10-01_00{n}"
    return {"episode_id": ep, "relationships": [],
            "entities": [{"name": name, "type": "person", "confidence": confidence, "summary": f"{name} in {ep}.",
                          "aliases": list(aliases), "source_episode": ep,
                          "source_episode_timestamp": f"2026-10-0{n}T12:00:00Z"}]}


class _Judge:
    def __init__(self, verdict="different"):
        self.verdict = verdict
        self.calls: list[dict] = []

    async def __call__(self, new_name, new_type, new_description, existing_name, existing_type, existing_body,
                       settings, **extra):
        self.calls.append({"new_name": new_name, "existing_name": existing_name, "existing_body": existing_body,
                           **extra})
        return self.verdict


@pytest.fixture
def bank(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-bank"
    for name in ("entities", "episodes", "inbox"):
        (root / name).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)
    return root


def _resolve(bank, monkeypatch, pages, extracted, judge, concurrency=1):
    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return [await judge(new_name, new_type, new_description, e["name"], e["type"], e["body"], settings,
                            **({"recorded_alias": True, "new_connections": new_connections} if e.get("alias") else {}))
                for e in entries]
    monkeypatch.setattr(er, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(er, "_llm_judge_batch", batch)
    return asyncio.run(er.resolve(extracted, pages, _settings(bank, concurrency)))


def _questions(bank):
    out = []
    for path in sorted((bank / "inbox").glob("inbox-*.md")):
        fm = markdown_parser.parse(path).frontmatter
        out.append((fm.get("kind"), fm.get("entity_id"), fm.get("merge_target_hint")))
    return out


def _creates(result):
    return sorted(c["id"] for c in result["changes"] if c["action"] == "create")


@pytest.mark.parametrize("concurrency", [1, 3])
def test_a_handle_meets_the_full_name_created_in_the_same_run_through_its_alias(bank, monkeypatch, concurrency):
    """The live failure: both names clear promotion in one batch. The handle used to get no candidate at all."""
    extracted = [_mention("Bob Example", 1, aliases=["bexample"]), _mention("@bexample", 2),
                 _mention("Bob Example", 3), _mention("@bexample", 4)]
    judge = _Judge("unsure")
    result = _resolve(bank, monkeypatch, [], extracted, judge, concurrency)
    assert [c["existing_name"] for c in judge.calls] == ["Bob Example"]
    assert judge.calls[0]["recorded_alias"] is True
    assert "Other names on record: bexample" in judge.calls[0]["existing_body"]
    assert _creates(result) == ["bob-example"]
    assert _questions(bank) == [("merge_suggestion", "@bexample", "bob-example")]


def test_a_same_verdict_on_the_in_cycle_alias_folds_the_handle_into_the_one_page(bank, monkeypatch):
    extracted = [_mention("Bob Example", 1, aliases=["bexample"]), _mention("bexample", 2),
                 _mention("Bob Example", 3), _mention("bexample", 4)]
    result = _resolve(bank, monkeypatch, [], extracted, _Judge("same"))
    assert _creates(result) == ["bob-example"]
    page = next(c for c in result["changes"] if c["id"] == "bob-example")
    assert sorted(page["source_episodes"]) == [f"ep_2026-10-01_00{n}" for n in (1, 2, 3, 4)]
    assert result["name_to_id"]["bexample"] == "bob-example"


def test_a_name_that_matches_its_own_page_raises_the_question_when_another_page_lists_it(bank, monkeypatch):
    """Once both pages exist the exact page always won and the alias was never read again."""
    pages = [_page("Bob Example", aliases=["bexample"]), _page("bexample")]
    judge = _Judge()
    result = _resolve(bank, monkeypatch, pages, [_mention("bexample", 1)], judge)
    assert judge.calls == []                                   # engine-free
    assert [c["id"] for c in result["changes"]] == ["bexample"]  # still credited to its own page: never a merge
    assert _questions(bank) == [("merge_suggestion", "bexample", "bob-example")]
    body = markdown_parser.parse(next((bank / "inbox").glob("inbox-*.md"))).body
    assert "already lists" in body

    # the next run asks nothing new, and a mention of the name does not delete the open question
    _resolve(bank, monkeypatch, pages, [_mention("bexample", 2, confidence=0.9)], judge)
    assert _questions(bank) == [("merge_suggestion", "bexample", "bob-example")]


def test_the_full_name_raises_the_same_question_once(bank, monkeypatch):
    pages = [_page("Bob Example", aliases=["bexample"]), _page("bexample")]
    _resolve(bank, monkeypatch, pages, [_mention("Bob Example", 1), _mention("bexample", 2)], _Judge())
    assert _questions(bank) == [("merge_suggestion", "bexample", "bob-example")]


def test_a_pair_the_person_said_were_different_is_not_asked_again(bank, monkeypatch):
    from api.services import merge_rejections

    pages = [_page("Bob Example", aliases=["bexample"]), _page("bexample")]
    merge_rejections.add_rejected(bank, "bexample", "bob-example")
    _resolve(bank, monkeypatch, pages, [_mention("bexample", 1)], _Judge())
    assert _questions(bank) == []


def test_a_new_name_another_page_links_as_its_account_is_asked_about_not_given_a_page(bank, monkeypatch):
    pages = [_page("Bob Example", body="## Summary\nSynthetic.\n\n## Links\n- [X](https://x.com/bexample)")]
    result = _resolve(bank, monkeypatch, pages, [_mention("bexample", 1), _mention("bexample", 2)], _Judge())
    assert _creates(result) == []
    assert _questions(bank) == [("merge_suggestion", "bexample", "bob-example")]
    body = markdown_parser.parse(next((bank / "inbox").glob("inbox-*.md"))).body
    assert body == "Bob Example links the x account “bexample”."


def test_a_named_handle_mention_lands_on_the_full_name_page_with_the_handle_as_alias(bank, monkeypatch):
    pages = [_page("Bob Example")]
    extracted = [_mention("bexample (Bob Example)", 1)]
    extracted[0]["relationships"] = [{"source": "bexample (Bob Example)", "target": "Bob Example", "label": "is"}]
    result = _resolve(bank, monkeypatch, pages, extracted, _Judge())
    [change] = result["changes"]
    assert change["id"] == "bob-example" and change["action"] == "update"
    assert "bexample" in change["entity"]["aliases"]
    assert result["name_to_id"]["bexample (bob example)"] == "bob-example"
    assert _creates(result) == [] and _questions(bank) == []


def test_a_parked_named_handle_line_resolves_to_the_full_name_page(bank, monkeypatch):
    pending_store.upsert(bank, PendingEntity(
        name="bexample (Bob Example)", type="person", description="", source_episode="ep_2026-09-30_001",
        confidence=0.4, tags=[], history_entries=[], key_facts=["Posts about synthetic agents."],
        heard_in=[{"episode": "ep_2026-09-30_001", "timestamp": "2026-09-30T12:00:00Z", "day": "2026-09-30"}]))
    result = _resolve(bank, monkeypatch, [_page("Bob Example")], [_mention("Bob Example", 1)], _Judge())
    [change] = result["changes"]
    assert change["id"] == "bob-example"
    assert "ep_2026-09-30_001" in change["source_episodes"]
    assert "bexample" in change["entity"]["aliases"]
    assert change["entity"]["name"] == "Bob Example"
    assert result["promoted_pending"] == ["bexample (Bob Example)"]
    assert result["name_to_id"]["bexample (bob example)"] == "bob-example"


def test_a_duplicate_question_still_closes_when_the_name_merges_into_the_page_it_proposed(bank, monkeypatch):
    from api.services.clarification_manager import ClarificationManager

    clarifier = ClarificationManager(bank)
    clarifier.create(entity_name="Bob", source_episode="ep_2026-09-30_001",
                     uncertainty_type="Possible duplicate of Bob Example", suggested_classification="person",
                     suggested_confidence=0.5, source_context="synthetic")
    (bank / "entities" / "bob-example.md").write_text("---\nname: Bob Example\ntype: person\n---\n")
    assert clarifier.check_organic_resolution("Bob", 0.9, merged_into="someone-else") is False
    assert clarifier.check_organic_resolution("Bob", 0.9, merged_into="bob-example") is True


def test_the_dry_run_lists_each_pair_and_writes_nothing(bank, capsys):
    from api.scripts import person_leads_dry_run

    for name, extra in (("Bob Example", "aliases:\n- bexample\n"), ("bexample", ""), ("Ann Sample", "")):
        slug = name.lower().replace(" ", "-")
        (bank / "entities" / f"{slug}.md").write_text(f"---\nname: {name}\ntype: person\n{extra}---\n## Summary\nx\n")
    for parked in ("asample (Ann Sample)", "bex"):
        pending_store.upsert(bank, PendingEntity(name=parked, type="person", description="",
                                                 source_episode="ep_2026-09-30_001", confidence=0.4, tags=[],
                                                 history_entries=[]))
    (bank / "entities" / "bob-example.md").write_text(
        "---\nname: Bob Example\ntype: person\naliases:\n- bexample\n---\n## Links\n- [X](https://x.com/bex)\n")
    before = sorted((p.name, p.stat().st_mtime_ns) for p in bank.rglob("*") if p.is_file())
    assert person_leads_dry_run.main(["--bank", str(bank), "--json"]) == 0
    rows = __import__("json").loads(capsys.readouterr().out)["leads"]
    assert {(r["page"], r["holder"], r["kind"]) for r in rows} == {
        ("bexample", "bob-example", "alias"), ("pending:asample (Ann Sample)", "ann-sample", "named_handle"),
        ("pending:bex", "bob-example", "profile:x")}
    assert sorted((p.name, p.stat().st_mtime_ns) for p in bank.rglob("*") if p.is_file()) == before


def test_a_duplicate_question_about_a_parked_name_stays_live_until_its_line_goes(bank):
    """Stage 2 asks "is <name> the same as <page>?" about a name it parked below the promotion bar. The inbox read and
    Sleep's tending used to read the missing page as "no longer in your memory" and retire it the same night."""
    from api.services import inbox_service, inbox_tend

    (bank / "entities" / "bob-example.md").write_text("---\nname: Bob Example\ntype: person\n---\n## Summary\nx\n")
    pending_store.upsert(bank, PendingEntity(name="bexample", type="person", description="",
                                             source_episode="ep_2026-10-01_001", confidence=0.4, tags=[],
                                             history_entries=[]))
    assert inbox_service._subject_gone(bank, "bexample", "merge_suggestion") is False
    fm = {"kind": "merge_suggestion", "status": "pending", "entity_id": "bexample", "entity_name": "bexample",
          "merge_target_hint": "bob-example", "uncertainty_type": "Possible duplicate of Bob Example"}
    path = bank / "inbox" / "inbox-001.md"
    markdown_parser.write(path, fm, "Bob Example links the x account “bexample”.")
    decision, _ = inbox_tend.policy(bank, path, fm)
    assert decision is None or decision.rule != "subject_gone"

    pending_store.save(bank, [])
    assert inbox_service._subject_gone(bank, "bexample", "merge_suggestion") is True
