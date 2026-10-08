"""A name a page already lists as an alias reaches that page — as a candidate for the judge, never as a decision.

Stage 2 showed the judge only same-type pages sharing a content word with the extracted name, and never read a
page's ``aliases``. So an acronym or short form the bank had already recorded for a page ("K8s"-style, no shared
word) never met the page and became a duplicate. Settling it on the alias alone was rejected: a bare first name
recorded on one person page would absorb every later person of that name, and different things share acronyms.
So an alias hit puts its page FIRST in front of the judge, with the context Cicada already has — the page's own
summary, facts, connections and other names, and the name's connections in this batch — and a note that an alias
is a lead, not proof. ``same`` merges (every conversation credited, G118), ``unsure`` asks the person, ``different``
leaves the name to its own page or pending line. Synthetic data only.
"""
import asyncio
from types import SimpleNamespace

import pytest

from api.services import entity_resolver as er
from api.services import providers


def _settings(bank, concurrency=3):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           sleep_promotion_threshold=2, sleep_resolve_concurrency=concurrency)


def _page(name, etype, aliases=(), body=None):
    fm = {"name": name, "type": etype, "confidence": 0.8, **({"aliases": list(aliases)} if aliases else {})}
    return {"id": name.lower().replace(" ", "-"), "frontmatter": fm,
            "body": body if body is not None else f"## Summary\nA synthetic page about {name}."}


def _batch(name, etype, episodes=(1,), relationships=(), alongside=()):
    out = []
    for n in episodes:
        ep = f"ep_2026-10-01_00{n}"
        ents = [{"name": name, "type": etype, "confidence": 0.6, "description": f"{name} came up in {ep}.",
                 "source_episode": ep, "source_episode_timestamp": f"2026-10-0{n}T12:00:00Z"}]
        ents += [{"name": other, "type": "concept", "confidence": 0.3, "description": "",
                  "source_episode": ep, "source_episode_timestamp": f"2026-10-0{n}T12:00:00Z"} for other in alongside]
        out.append({"episode_id": ep, "relationships": [dict(r) for r in relationships], "entities": ents})
    return out


class _Judge:
    """A fake judge: a fixed verdict per page name, every pair and every call's arguments recorded."""

    def __init__(self, verdicts=None):
        self.verdicts = verdicts or {}
        self.pairs: list[tuple[str, str]] = []
        self.calls: list[dict] = []

    async def __call__(self, new_name, new_type, new_description, existing_name, existing_type, existing_body,
                       settings, **extra):
        self.pairs.append((new_name, existing_name))
        self.calls.append({"new_name": new_name, "existing_name": existing_name, "new_description": new_description,
                           "existing_body": existing_body, **extra})
        return self.verdicts.get(existing_name, "different")


@pytest.fixture
def bank(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-bank"
    for name in ("entities", "episodes", "inbox"):
        (root / name).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)
    return root


def _resolve(bank, monkeypatch, pages, extracted, judge, concurrency=3):
    monkeypatch.setattr(er, "_llm_judge_same_entity", judge)
    return asyncio.run(er.resolve(extracted, pages, _settings(bank, concurrency)))


@pytest.mark.parametrize("concurrency", [1, 3])
def test_an_acronym_alias_with_no_shared_word_reaches_its_page_through_the_judge(bank, monkeypatch, concurrency):
    pages = [_page("Cobalt Datastore", "tool", aliases=["CDS"])]
    judge = _Judge({"Cobalt Datastore": "same"})
    out = _resolve(bank, monkeypatch, pages, _batch("cds", "tool", episodes=(1, 2, 3)), judge, concurrency)
    assert judge.pairs == [("cds", "Cobalt Datastore")], "one call, and the page is in front of the judge"
    assert out["name_to_id"]["cds"] == "cobalt-datastore"
    (change,) = out["changes"]
    assert change["action"] == "update" and change["id"] == "cobalt-datastore"
    assert sorted(change["source_episodes"]) == [f"ep_2026-10-01_00{n}" for n in (1, 2, 3)], "G118: all credited"


def test_a_shared_acronym_the_judge_calls_different_gets_its_own_page(bank, monkeypatch):
    """A different thing with the same letters: never merged on the letters alone."""
    pages = [_page("Cobalt Datastore", "tool", aliases=["CDS"])]
    judge = _Judge({"Cobalt Datastore": "different"})
    out = _resolve(bank, monkeypatch, pages, _batch("CDS", "tool", episodes=(1, 2)), judge)
    assert judge.pairs == [("CDS", "Cobalt Datastore")]
    assert out["name_to_id"]["cds"] == "cds"
    assert [(c["id"], c["action"]) for c in out["changes"]] == [("cds", "create")]


def test_a_shared_acronym_the_judge_is_unsure_about_asks_the_person(bank, monkeypatch):
    pages = [_page("Cobalt Datastore", "tool", aliases=["CDS"])]
    judge = _Judge({"Cobalt Datastore": "unsure"})
    out = _resolve(bank, monkeypatch, pages, _batch("CDS", "tool", episodes=(1, 2)), judge)
    assert out["changes"] == [] and "cds" not in out["name_to_id"]
    filed = [p.read_text() for p in (bank / "inbox").iterdir()]
    assert len(filed) == 1 and "Possible duplicate of Cobalt Datastore" in filed[0]


def test_a_first_name_alias_on_a_person_page_is_never_settled_without_the_judge(bank, monkeypatch):
    pages = [_page("Bob Example", "person", aliases=["Bob"]), _page("Bob Sample", "person")]
    judge = _Judge()  # different, for every page
    out = _resolve(bank, monkeypatch, pages, _batch("Bob", "person", episodes=(1, 2)), judge)
    assert judge.pairs[0] == ("Bob", "Bob Example"), "the alias holder is judged first"
    assert sorted(judge.pairs) == [("Bob", "Bob Example"), ("Bob", "Bob Sample")]
    assert out["name_to_id"]["bob"] == "bob"
    assert all(c["id"] != "bob-example" for c in out["changes"])


def test_the_alias_holder_is_judged_first_so_a_same_spends_one_call(bank, monkeypatch):
    pages = [_page("Delta Ember", "project"), _page("Delta Onyx", "project"),
             _page("Delta Prism Works", "project", aliases=["Delta Prism"])]
    judge = _Judge({"Delta Prism Works": "same"})
    out = _resolve(bank, monkeypatch, pages, _batch("Delta Prism", "project", episodes=(1, 2)), judge)
    assert judge.pairs == [("Delta Prism", "Delta Prism Works")]
    assert out["name_to_id"]["delta prism"] == "delta-prism-works"


def test_an_alias_two_pages_share_puts_both_in_front_of_the_judge(bank, monkeypatch):
    pages = [_page("Garnet Lab", "project", aliases=["GL"]), _page("Harbor Line", "project", aliases=["gl"])]
    judge = _Judge({"Harbor Line": "same"})
    out = _resolve(bank, monkeypatch, pages, _batch("GL", "project", episodes=(1, 2)), judge)
    assert judge.pairs == [("GL", "Garnet Lab"), ("GL", "Harbor Line")]
    assert out["name_to_id"]["gl"] == "harbor-line"


def test_an_alias_held_by_a_page_of_another_type_is_no_candidate(bank, monkeypatch):
    pages = [_page("Garnet Harbor Inc", "company", aliases=["GHI"])]
    judge = _Judge({"Garnet Harbor Inc": "same"})
    out = _resolve(bank, monkeypatch, pages, _batch("GHI", "project", episodes=(1, 2)), judge)
    assert judge.pairs == []
    assert out["name_to_id"]["ghi"] == "ghi"


def test_the_judge_is_told_it_is_an_alias_and_gets_both_sides_context(bank, monkeypatch):
    body = ("## Summary\nA synthetic datastore.\n\n## History\n" + "- 2026-01-01: an old event\n" * 200
            + "\n## Key Facts\n- Runs on the alpha-project cluster\n\n## Related\n- uses [[Lumen Queue]]\n")
    pages = [_page("Cobalt Datastore", "tool", aliases=["CDS", "cobalt db"], body=body)]
    rels = [{"source": "CDS", "target": "Lumen Queue", "label": "feeds"}]
    judge = _Judge({"Cobalt Datastore": "same"})
    _resolve(bank, monkeypatch, pages, _batch("CDS", "tool", episodes=(1, 2), relationships=rels,
                                              alongside=["Prism Gateway"]), judge)
    (call,) = judge.calls
    assert call["recorded_alias"] is True
    assert "feeds Lumen Queue" in call["new_connections"]
    assert "Prism Gateway" in call["new_connections"]
    # The page's facts and connections lead, so a long history cannot push them past the judge's cut.
    head = call["existing_body"][:2000]
    assert "Runs on the alpha-project cluster" in head and "Lumen Queue" in head
    assert "cobalt db" in head, "its other names on record"


def test_a_plain_candidate_is_judged_exactly_as_before(bank, monkeypatch):
    pages = [_page("Delta Ember", "project")]
    judge = _Judge()
    _resolve(bank, monkeypatch, pages, _batch("Delta", "project", episodes=(1, 2)), judge)
    (call,) = judge.calls
    assert set(call) == {"new_name", "existing_name", "new_description", "existing_body"}, "no alias arguments"
    assert call["existing_body"] == pages[0]["body"]


def _capture_prompt(monkeypatch, **extra):
    prompts = []

    def resolve_async(*args, **kwargs):
        async def complete(**call):
            prompts.append(call["messages"][0]["content"])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"decision": "same"}'))])
        return complete

    monkeypatch.setattr(providers, "resolve_llm_fn", resolve_async)
    settings = SimpleNamespace(litellm_model="synthetic-model", litellm_disambiguation_model="")
    asyncio.run(er._llm_judge_same_entity("CDS", "tool", "CDS came up.", "Cobalt Datastore", "tool",
                                          "## Summary\nA datastore.", settings, **extra))
    return prompts[0]


def test_the_alias_prompt_carries_the_note_and_the_plain_prompt_does_not(monkeypatch):
    plain = _capture_prompt(monkeypatch)
    assert "alias" not in plain.lower()
    assert plain == er._DISAMBIG_PROMPT.format(
        existing_name="Cobalt Datastore", existing_type="tool", existing_body="## Summary\nA datastore.",
        new_name="CDS", new_type="tool", new_description="CDS came up.", alias_note="", new_connections="")
    hinted = _capture_prompt(monkeypatch, recorded_alias=True, new_connections="- feeds Lumen Queue")
    assert "already lists \"CDS\"" in hinted
    assert "not proof" in hinted
    assert "- feeds Lumen Queue" in hinted
