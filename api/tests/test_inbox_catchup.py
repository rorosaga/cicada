"""Vision item 10 — the catch-up chat, the use-weighted inbox order, the human wording and the questions Sleep raises
for it (``page_use``, ``inbox_wording``, ``inbox_catchup``, ``still_questions``). Synthetic bank, placeholder names."""
import asyncio
import json
import subprocess
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (bank_index, git_service, inbox_catchup, inbox_questions, inbox_service, inbox_tend,
                          inbox_wording, markdown_parser, mcp_tools, page_use, sleep_cycle, still_questions)
from api.services.claims import Claim, parse_claims, write_claims

TODAY = date.today()
OWNER = "owner-example"


def d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def page(bank, pid, *, name=None, type_="concept", status="active", said=-5, convs=1, related=0, body="", **extra):
    fm = {"type": type_, "name": name or pid.replace("-", " ").title(), "status": status, "confidence": 0.7,
          "created": d(-400), "last_referenced": d(said),
          "source_episodes": [f"ep_{d(-i - 1)}_001" for i in range(convs)],
          "related": [f"x-{i}" for i in range(related)], **extra}
    markdown_parser.write(bank / "entities" / f"{pid}.md", fm, body or f"# {fm['name']}\n")
    bank_index.invalidate()
    page_use.reset()


def item(bank, num, **fm):
    base = {"kind": "conflict", "status": "pending", "priority": 0.5, "created_date": d(-1),
            "required_input": "choice"}
    path = bank / "inbox" / f"inbox-{num:03d}.md"
    markdown_parser.write(path, {**base, **fm}, "body")
    bank_index.invalidate()
    return path.stem


def claim(cid, predicate, obj, *, said, kind="node", episodes=1, **kw):
    eps = [f"ep_{(date.fromisoformat(said) - timedelta(days=i)).isoformat()}_001" for i in range(episodes)]
    return Claim(id=cid, text=f"Owner {predicate} {obj}", subject=OWNER, predicate=predicate, object=obj,
                 object_kind=kind, valid_from=said, recorded_at=said, source_episodes=eps, **kw)


@pytest.fixture
def bank(tmp_path):
    b = tmp_path / "bank"
    for sub in ("entities", "inbox", "episodes"):
        (b / sub).mkdir(parents=True)
    markdown_parser.write(b / "_state.md", {"type": "state", "owner_id": OWNER}, "")
    page(b, OWNER, name="Owner Example", type_="person", convs=40)
    _git(b, "init", "-q")
    _git(b, "config", "user.email", "t@example.com")
    _git(b, "config", "user.name", "t")
    _git(b, "add", "-A")
    _git(b, "commit", "-qm", "init")
    bank_index.invalidate()
    page_use.reset()
    yield b
    page_use.reset()


def ctx(bank, session="s-1", **kw):
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id=session, harness="claude-code", **kw)


def owner_claims(bank, claims):
    path = bank / "entities" / f"{OWNER}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims))
    bank_index.invalidate()


# --------------------------------------------------------------------------- S1: page use


def test_a_page_said_more_and_lately_is_used_more_and_the_owner_is_the_most_used(bank):
    page(bank, "busy", convs=30, said=-3, related=6)
    page(bank, "quiet", convs=2, said=-300)
    use = page_use.scores(bank)
    assert use[OWNER] == 1.0
    assert use["busy"] > use["quiet"]
    assert 0.0 <= use["quiet"] < 0.15
    assert page_use.bucket(use["busy"]) == "high" and page_use.bucket(use["quiet"]) == "low"
    assert page_use.item_use(use, {"entity_id": "held-name", "merge_target_hint": "busy"}) == use["busy"]


def test_the_inbox_asks_about_the_most_used_page_first_at_equal_priority(bank):
    page(bank, "busy", convs=30, said=-2)
    page(bank, "quiet", convs=1, said=-200)
    quiet = item(bank, 1, entity_id="quiet", entity_name="Quiet", predicate="uses", question="What does Quiet use?",
                 options=[{"key": "a", "label": "x"}, {"key": "b", "label": "y"}], title="t")
    busy = item(bank, 2, entity_id="busy", entity_name="Busy", predicate="uses", question="What does Busy use?",
                options=[{"key": "a", "label": "x"}, {"key": "b", "label": "y"}], title="t", created_date=d(-30))
    order = [i.id for i in inbox_service.load_inbox(bank)]
    assert order.index(busy) < order.index(quiet)
    # Use never outweighs a real priority gap: a much higher-priority question on a quiet page still comes first.
    item(bank, 3, entity_id="quiet", entity_name="Quiet", predicate="runs-on", priority=1.2, title="t",
         options=[{"key": "a", "label": "x"}, {"key": "b", "label": "y"}])
    assert [i.id for i in inbox_service.load_inbox(bank)][0] == "inbox-003"


# --------------------------------------------------------------------------- S4: the wording


def test_decay_is_asked_by_what_the_page_is_and_a_one_off_interest_is_never_pushed(bank):
    fm = {"name": "Topic Alpha", "type": "concept", "last_referenced": d(-60), "source_episodes": ["ep_x"]}
    said = inbox_wording.spoken({"kind": "decay", "entity_id": "topic-alpha", "entity_name": "Topic Alpha"},
                                TODAY.isoformat(), page_fm=fm)
    assert said.question == "Are you still interested in Topic Alpha?"
    assert said.reason == "You mentioned it once, about 2 months ago, and I don't want to push you on it."
    tool = inbox_wording.spoken({"kind": "decay", "entity_name": "Tool Beta"}, TODAY.isoformat(),
                                page_fm={"type": "tool", "last_referenced": d(-90), "source_episodes": ["a", "b"]})
    assert tool.question == "Do you still use Tool Beta?" and "2 conversations" in tool.reason
    fresh = inbox_wording.spoken({"kind": "decay", "entity_name": "Tool Beta"}, TODAY.isoformat(),
                                 page_fm={"type": "tool", "last_referenced": d(-5), "source_episodes": ["a"]})
    assert "not since" not in fresh.reason


def test_a_stale_role_names_the_stale_profile_and_a_fresh_one_speaks_for_the_fact(bank):
    profile = {"ref": "https://www.linkedin.com/in/owner-example", "added_by": "user"}
    fm = {"kind": "conflict", "asks": "still", "predicate": "works-at", "entity_id": OWNER,
          "options": [{"key": "a", "label": "Org Gamma"}, {"key": "neither", "label": "Not anymore"}],
          "last_said": d(-220), "said_in": 3}
    said = inbox_wording.spoken(fm, TODAY.isoformat(), page_fm={"sources": [profile]}, owner_id=OWNER)
    assert said.question == "Are you still working at Org Gamma?"
    assert said.reason == ("You haven't mentioned it in 7 months, and your LinkedIn seems a bit stale, "
                           "so I wasn't sure you still are.")
    fresh = {**profile, "refresh": {"at": d(-3), "outcome": "read", "good": d(-3)}}
    assert inbox_wording.source_cue({"sources": [fresh]}, "works-at", TODAY, own=True) == (inbox_wording.FRESH, None)
    gone = {**profile, "refresh": {"dead": {"since": d(-10)}}}
    assert inbox_wording.source_cue({"sources": [gone]}, "works-at", TODAY, own=True)[1] == \
        "your LinkedIn link stopped working"
    plain = inbox_wording.spoken(fm, TODAY.isoformat(), page_fm={}, owner_id=OWNER)
    assert plain.reason == "You haven't mentioned it in 7 months, so I wasn't sure you still are."


def test_people_and_a_generic_conflict_are_said_plainly_and_every_question_keeps_the_card_rule(bank):
    group = inbox_wording.spoken({"kind": "merge_suggestion"}, TODAY.isoformat(),
                                 group=["Nick A", "Nick B", "your partner"])
    assert group.question == "Are Nick A, Nick B and your partner the same person?"
    assert "only join people on your word" in group.reason
    assert inbox_wording.speakable("Partner", {"unnamed": True, "owner_roles": ["partner"]}) == "your partner"
    assert inbox_wording.speakable("Nick C (unnamed)") == "Nick C"
    generic = inbox_wording.spoken(
        {"kind": "conflict", "entity_name": "Alpha", "predicate": "value-of-x",
         "question": "Which is true about Alpha (value-of-x)?",
         "options": [{"key": "a", "label": "one"}, {"key": "b", "label": "two"}]}, TODAY.isoformat())
    assert generic.question == "Which is right about Alpha: one or two?"
    own = inbox_wording.spoken({"kind": "conflict", "entity_id": OWNER, "predicate": "works-at",
                                "options": [{"key": "a", "label": "x"}, {"key": "b", "label": "y"}]},
                               TODAY.isoformat(), owner_id=OWNER)
    assert own.question == "Where do you work now?"
    long_name = inbox_wording.spoken({"kind": "decay", "entity_name": "N" * 300}, TODAY.isoformat(),
                                     page_fm={"type": "concept"})
    assert long_name.question.endswith("?") and len(long_name.question) <= 160


def test_the_wording_never_changes_the_stored_question_or_its_keys(bank):
    fm = {"kind": "conflict", "question": "Which is true about Alpha (p)?",
          "options": [{"key": "a", "label": "one"}, {"key": "b", "label": "two"}]}
    before = json.dumps(fm, sort_keys=True)
    inbox_wording.spoken(fm, TODAY.isoformat())
    assert json.dumps(fm, sort_keys=True) == before


# --------------------------------------------------------------------------- S5: still questions


def test_a_quiet_interest_and_a_quiet_role_are_asked_once_within_the_budget(bank):
    page(bank, "topic-alpha", name="Topic Alpha", said=-90)
    page(bank, "org-gamma", name="Org Gamma", type_="company", said=-300)
    page(bank, "topic-live", name="Topic Live", said=-2)
    owner_claims(bank, [
        claim("c-int", "is-interested-in", "topic-alpha", said=d(-90)),
        claim("c-role", "works-at", "org-gamma", said=d(-300), episodes=3),
        claim("c-live", "is-interested-in", "topic-live", said=d(-90)),     # the topic is still said: not asked
        claim("c-new", "wants-to-learn", "topic-new", said=d(-10), kind="literal"),   # said recently
        claim("c-old", "studies", "subject-old", said=d(-900), kind="literal"),       # long past
        claim("c-shut", "works-at", "org-old", said=d(-900), kind="literal", valid_to=d(-400)),  # closed
    ])
    found = still_questions.candidates(bank, TODAY)
    assert [c.claim_id for c in found] == ["c-role", "c-int"]          # a role first
    report = still_questions.propose(bank, TODAY, budget=inbox_catchup.Budget())
    assert len(report.written) == 2
    written = [markdown_parser.parse(bank / p).frontmatter for p in report.written]
    role = next(f for f in written if f["predicate"] == "works-at")
    assert role["asks"] == "still" and role["question"] == "Are you still working at Org Gamma?"
    assert [o["key"] for o in role["options"]] == ["a", "neither"]
    assert inbox_questions.validate_question(role["question"], role["options"]) == []
    assert role["said_in"] == 3 and role["last_said"] == d(-300)
    # The next drain asks nothing new: one per (page, predicate), and nothing it already asked.
    again = still_questions.propose(bank, TODAY, budget=inbox_catchup.Budget())
    assert again.written == [] and again.skipped.get("question_open_on_predicate") == 2


def test_a_fresh_source_an_answer_and_the_budget_each_hold_a_still_question_back(bank):
    page(bank, "org-gamma", name="Org Gamma", type_="company", said=-300)
    owner_claims(bank, [claim("c-role", "works-at", "org-gamma", said=d(-300))])
    path = bank / "entities" / f"{OWNER}.md"
    parsed = markdown_parser.parse(path)
    fresh = {"ref": "https://www.linkedin.com/in/owner-example", "added_by": "user",
             "refresh": {"at": d(-2), "outcome": "read", "good": d(-2)}}
    markdown_parser.write(path, {**parsed.frontmatter, "sources": [fresh]}, parsed.body)
    bank_index.invalidate()
    assert still_questions.candidates(bank, TODAY) == []                      # the re-check keeps it current
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    bank_index.invalidate()
    still_questions.record_answer(bank, "c-role", "still", d(-30))
    assert still_questions.candidates(bank, TODAY) == []                      # answered a month ago
    (bank / still_questions.FILE).unlink()
    assert still_questions.propose(bank, TODAY, budget=inbox_catchup.Budget(0)).written == []
    assert still_questions.propose(bank, TODAY, budget=inbox_catchup.Budget(), dry_run=True).written
    assert not list((bank / "inbox").glob("inbox-*.md"))                     # a dry run writes nothing


def test_a_still_question_is_never_settled_by_rule_or_judge_and_is_not_informational(bank):
    page(bank, "org-gamma", name="Org Gamma", type_="company", said=-300)
    owner_claims(bank, [claim("c-role", "works-at", "org-gamma", said=d(-300))])
    report = still_questions.propose(bank, TODAY, budget=inbox_catchup.Budget())
    path = bank / report.written[0]
    fm = markdown_parser.parse(path).frontmatter
    assert inbox_tend.policy(bank, path, fm) == (None, "needs_person")
    served = next(i for i in inbox_service.load_inbox(bank) if i.id == path.stem)
    assert served.asks == "still" and served.informational is False


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()

    async def no_prose(*_a, **_k):
        return None

    monkeypatch.setattr(inbox_service, "_conflict_synthesis", no_prose)
    yield TestClient(main.app)
    config.get_settings.cache_clear()


@pytest.mark.parametrize("key,open_after,answer", [("a", True, "still"), ("neither", False, "ended")])
def test_the_persons_answer_keeps_or_closes_the_claim_and_is_remembered(bank, client, key, open_after, answer):
    page(bank, "org-gamma", name="Org Gamma", type_="company", said=-300)
    owner_claims(bank, [claim("c-role", "works-at", "org-gamma", said=d(-300))])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "setup")
    report = still_questions.propose(bank, TODAY, budget=inbox_catchup.Budget())
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "asked")
    stem = (bank / report.written[0]).stem
    r = client.post(f"/inbox/{stem}/resolve", json={"action": "resolve", "optionKey": key})
    assert r.status_code == 200, r.text
    role = next(c for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{OWNER}.md").body)
                if c.id == "c-role")
    assert (role.valid_to is None) is open_after
    assert still_questions.load_answers(bank)["c-role"]["answer"] == answer
    answer_commit = _git(bank, "log", "-2", "--name-only", "--format=%s").split()
    assert still_questions.FILE in answer_commit                    # committed with the answer, as the person's
    assert still_questions.candidates(bank, TODAY) == []


def test_not_anymore_on_one_interest_ends_only_that_value_in_the_prose(bank, monkeypatch):
    """Review B1: "Not anymore" used to send the rewrite "None of the previously recorded values for '<predicate>' are
    current", which on a multi-valued interest could drop every interest from the page's prose. The rewrite's real
    input is captured here (the model call itself is stubbed, its argument is not)."""
    from api.services import conflict_resolver

    page(bank, "topic-alpha", name="Topic Alpha", said=-100)
    page(bank, "topic-beta", name="Topic Beta", said=-2)
    owner_claims(bank, [claim("c-a", "is-interested-in", "topic-alpha", said=d(-100)),
                        claim("c-b", "is-interested-in", "topic-beta", said=d(-2))])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "setup")
    report = still_questions.propose(bank, TODAY, budget=inbox_catchup.Budget())
    assert len(report.written) == 1
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "asked")
    seen: list[str] = []

    async def rewrite(**kw):
        seen.append(kw["new_description"])
        return None                       # the safe fallback writes the same sentence into the page

    monkeypatch.setattr(conflict_resolver, "_synthesize_entity_update", rewrite)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    try:
        r = TestClient(main.app).post(f"/inbox/{(bank / report.written[0]).stem}/resolve",
                                      json={"action": "resolve", "optionKey": "neither"})
    finally:
        config.get_settings.cache_clear()
    assert r.status_code == 200, r.text
    assert seen and "no longer interested in Topic Alpha" in seen[0]
    assert "Topic Beta" not in seen[0] and "None of the previously" not in seen[0]
    owner = markdown_parser.parse(bank / "entities" / f"{OWNER}.md")
    assert "None of the previously" not in owner.body
    by_id = {c.id: c for c in parse_claims(owner.body)}
    assert by_id["c-a"].valid_to is not None and by_id["c-b"].valid_to is None


# --------------------------------------------------------------------------- S7: one person, several names


@pytest.mark.parametrize("a,b,expected", [
    ("Sam", "Samantha Example", True), ("Ben", "Benjamin", True), ("Kat", "Katarina Example", True),
    ("Ana", "Ana", False), ("Paula", "Paulina", False), ("Lena", "Lenara", False),
    ("Ben Example", "Benjamin", False), ("Al", "Albert", False), ("Bob", "Robert", False),
])
def test_a_nickname_is_a_short_single_word_form_of_the_long_name(a, b, expected):
    assert inbox_catchup.nickname_pair(a, b) is expected


def test_spelling_proposes_a_same_person_question_once_and_never_over_a_rejection(bank):
    page(bank, "sam", name="Sam", type_="person", convs=2, said=-20)
    page(bank, "samantha-example", name="Samantha Example", type_="person", convs=9, said=-3)
    page(bank, "ben", name="Ben", type_="person")
    page(bank, "benjamin", name="Benjamin", type_="person")
    from api.services import merge_rejections

    merge_rejections.add_rejected(bank, "ben", "benjamin")
    report = inbox_catchup.propose_nicknames(bank, TODAY, budget=inbox_catchup.Budget())
    assert len(report.written) == 1 and report.skipped == {"person_said_two_people": 1}
    fm = markdown_parser.parse(bank / report.written[0]).frontmatter
    assert fm["kind"] == "merge_suggestion" and fm["detected"] == "spelling"
    assert (fm["entity_id"], fm["merge_target_hint"]) == ("sam", "samantha-example")   # the less-used one is asked
    assert inbox_catchup.propose_nicknames(bank, TODAY, budget=inbox_catchup.Budget()).written == []


def test_chained_same_person_questions_are_asked_once_and_other_kinds_never_group(bank):
    for pid in ("nick-a", "nick-b", "nick-c", "tool-a", "tool-b", "tool-c"):
        page(bank, pid, name=pid.replace("-", " ").title(), type_="person" if pid.startswith("nick") else "tool")
    item(bank, 1, kind="merge_suggestion", entity_id="nick-a", merge_target_hint="nick-b", entity_name="Nick A",
         required_input="merge")
    item(bank, 2, kind="merge_suggestion", entity_id="nick-c", merge_target_hint="nick-b", entity_name="Nick C",
         required_input="merge")
    item(bank, 3, kind="merge_suggestion", entity_id="tool-a", merge_target_hint="tool-b", required_input="merge")
    item(bank, 4, kind="merge_suggestion", entity_id="tool-c", merge_target_hint="tool-b", required_input="merge")
    entries, _ = inbox_catchup.select(bank, limit=10)
    grouped = [e for e in entries if e.group_names]
    assert len(grouped) == 1 and grouped[0].ids == ["inbox-001", "inbox-002"]
    assert sorted(grouped[0].group_names) == ["Nick A", "Nick B", "Nick C"]
    assert sum(1 for e in entries if not e.group_names) == 2


# --------------------------------------------------------------------------- S2: the catch-up read


def _three_questions(bank):
    for n, pid in enumerate(("alpha", "beta", "gamma", "delta"), start=1):
        page(bank, pid, convs=n * 5, said=-n)
        item(bank, n, entity_id=pid, entity_name=pid.title(), predicate="runs-on", title="t",
             question=f"What does {pid.title()} run on now?",
             options=[{"key": "a", "label": "one"}, {"key": "b", "label": "two"}])


def test_catch_up_serves_a_few_most_used_first_and_never_repeats_in_a_session(bank):
    _three_questions(bank)
    first = mcp_tools.check_nudges(ctx(bank), None, None, "catchup")
    assert first.count("Ask: ") == inbox_catchup.LIMIT and "1 more after these" in first
    assert first.index("`inbox-004`") < first.index("`inbox-003`")       # the most-used page first
    assert "Why you are asking" in first and "option_key=a" in first
    second = mcp_tools.check_nudges(ctx(bank), None, None, "catchup")
    assert second.count("Ask: ") == 1 and "`inbox-001`" in second and "These are the last ones" in second
    assert "Nothing left to catch up on" in mcp_tools.check_nudges(ctx(bank), None, None, "catchup")
    assert mcp_tools.check_nudges(ctx(bank, session="s-2"), None, None, "catchup").count("Ask: ") == 3


def test_catch_up_leaves_out_what_was_skipped_and_is_local_only(bank):
    _three_questions(bank)
    c = ctx(bank)
    c.skipped_inbox_ids.add("inbox-004")
    assert "`inbox-004`" not in mcp_tools.check_nudges(c, None, None, "catchup")
    remote = mcp_tools.check_nudges(ctx(bank, session="r", connector_id="conn-1"), None, None, "catchup")
    assert getattr(remote, "code", None) == "refused"


def test_catch_up_on_the_command_line_spells_commands_that_run(bank):
    _three_questions(bank)
    out = mcp_tools.check_nudges(ctx(bank, read_surface="cli"), None, None, "catchup")
    assert "`cicada inbox resolve inbox-004 --skip`" in out
    assert "cicada_resolve_inbox" not in out


def test_a_same_person_yes_is_never_joined_by_the_agent(bank):
    for pid in ("nick-a", "nick-b"):
        page(bank, pid, type_="person")
    item(bank, 1, kind="merge_suggestion", entity_id="nick-a", merge_target_hint="nick-b", entity_name="Nick A",
         required_input="merge")
    out = mcp_tools.check_nudges(ctx(bank), None, None, "catchup")
    assert "Are Nick A and Nick B the same person?" in out
    assert "never from yours" in out and "reject=true" in out
    assert "option_key or answer" not in out


def test_ask_mode_says_the_question_in_plain_words_too(bank):
    page(bank, "alpha", convs=5, said=-1)
    item(bank, 1, entity_id="alpha", entity_name="Alpha", predicate="value-of-x", title="t",
         question="Which is true about Alpha (value-of-x)?",
         options=[{"key": "a", "label": "red"}, {"key": "b", "label": "blue"}])
    out = mcp_tools.check_nudges(ctx(bank), "is alpha red or blue", ["alpha"], "ask")
    assert "Ask it like: Which is right about Alpha: red or blue?" in out


# --------------------------------------------------------------------------- S10 + Sleep's tail


def test_the_tail_raises_catch_up_questions_in_their_own_commits_under_one_budget(bank, monkeypatch):
    page(bank, "topic-alpha", name="Topic Alpha", said=-90)
    page(bank, "kat", name="Kat", type_="person")
    page(bank, "katarina", name="Katarina", type_="person")
    owner_claims(bank, [claim("c-int", "is-interested-in", "topic-alpha", said=d(-90))])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "setup")
    monkeypatch.setattr(inbox_catchup, "NEW_PER_DRAIN", 1)
    asyncio.run(sleep_cycle._catchup_questions_safely(bank))
    log = _git(bank, "log", "--format=%s", "-3").splitlines()
    assert log[0].startswith("Questions to check in")
    assert len(list((bank / "inbox").glob("inbox-*.md"))) == 1            # the budget held the nickname back
    assert _git(bank, "status", "--porcelain") == ""
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")


def test_a_failed_commit_takes_back_the_questions_it_wrote(bank, monkeypatch):
    page(bank, "topic-alpha", name="Topic Alpha", said=-90)
    owner_claims(bank, [claim("c-int", "is-interested-in", "topic-alpha", said=d(-90))])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "setup")

    async def boom(*_a, **_k):
        raise git_service.GitError("index.lock is held")

    monkeypatch.setattr(git_service, "commit_paths", boom)
    asyncio.run(sleep_cycle._catchup_questions_safely(bank))
    assert not list((bank / "inbox").glob("inbox-*.md"))
    assert _git(bank, "status", "--porcelain") == ""


def test_the_cursor_is_outside_the_bank_and_holds_only_ids(bank, tmp_path):
    cur = inbox_catchup.Cursor(bank, "s-9")
    cur.add(["inbox-001", "inbox-002"])
    assert not str(cur.path).startswith(str(bank))
    data = json.loads(cur.path.read_text())
    assert set(data) == {"ids", "at"} and data["ids"] == ["inbox-001", "inbox-002"]
    assert "s-9" not in cur.path.name and str(bank) not in cur.path.read_text()


# --------------------------------------------------------------------------- S3: the prompt, the schema, the CLI


def _server():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("cicada_mcp_server_catchup", root / "mcp" / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    return server


def test_the_catch_up_prompt_is_listed_and_names_only_real_arguments():
    import re

    server = _server()
    assert server.initialize_result({})["capabilities"]["prompts"] == {}
    assert [p["name"] for p in server.PROMPTS] == ["catch_up"]
    got = server.prompt_get("catch_up")
    text = got["messages"][0]["content"]["text"]
    assert got["messages"][0]["role"] == "user" and 'mode="catchup"' in text
    schemas = {t["name"]: t["inputSchema"]["properties"] for t in server.TOOLS}
    assert "catchup" in schemas["cicada_check_nudges"]["mode"]["enum"]
    for tool in re.findall(r"\b(cicada_[a-z_]+)\b", text):           # R12: every tool it names exists
        assert tool in schemas
    assert {"quote", "skip"} <= set(schemas["cicada_resolve_inbox"])
    assert server.prompt_get("nope") is None


def test_the_remote_schema_does_not_offer_catch_up():
    from api.remote import tools as remote_tools

    tool = remote_tools.REMOTE_TOOLS["cicada_check_nudges"]
    assert tool["inputSchema"]["properties"]["mode"]["enum"] == ["ask", "list"]


def test_a_bool_flag_is_spelled_bare_so_the_line_runs():
    from api.services import cli_map

    assert cli_map.spell("cicada_resolve_inbox", id="inbox-001", skip=True) == "cicada inbox resolve inbox-001 --skip"
    assert cli_map.spell("cicada_resolve_inbox", id="inbox-001", skip=False) == "cicada inbox resolve inbox-001"
