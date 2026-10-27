"""A held name's claims land when the person answers its question (G209, 2026-10-27; the gap #483's review found).

Sleep holds a name it could not place ("Alex", with several people answering to it) on its pending line, its claims
with it — as its subject, or as another page's claim with it as the object — and releases them only when Stage 2 joins
the name to a page. So when the person answered "Is Alex the same as Alex Kim?" and the name was never mentioned again,
those claims never reached a page. Now the person's own resolver releases them in the same write:

- "same as B": the claims land on B (an object-side claim stays on its subject's page and points at B);
- "someone else" (reject) / dismiss / skip: nothing is released — the line keeps its claims and Stage 2 decides later;
- the release rides in the answer's commit, so Sleep's undo takes it back, byte for byte;
- a claim is released at most once, and never onto a page the person did not name.

Synthetic banks only (alex, alex-kim, alex-lee, mira-quell); git is real; nothing reaches a network or an engine.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.services import bank_index, claim_pipeline, inbox_tend, markdown_parser, merge_rejections, pending_store
from api.services.claims import Claim, parse_claims
from api.services.pending_store import PendingEntity

EP1, EP2 = "ep_2026-10-01_001", "ep_2026-10-02_001"


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True, text=True).stdout


def _commit(bank: Path, msg: str = "seed") -> None:
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", msg)
    bank_index.invalidate()


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90
        self.llm_mode = "byok"


def _page(bank: Path, eid: str, name: str, etype: str) -> None:
    markdown_parser.write(bank / "entities" / f"{eid}.md",
                          {"name": name, "type": etype, "status": "active", "confidence": 0.8,
                           "created": "2026-09-01", "last_referenced": "2026-09-01", "source_episodes": [],
                           "tags": [], "related": [], "version": 1},
                          f"## Summary\nA synthetic page about {name}.\n")


def _held(subject: str, predicate: str, obj: str, n: int, episode: str) -> dict:
    return Claim(id=f"clm_held_{n}", text=f"{subject} {predicate} {obj}", subject=subject, predicate=predicate,
                 object=obj, valid_from="2026-10-01", recorded_at="2026-10-01", source_episodes=[episode]).to_dict()


def _line(bank: Path, name: str, against: str, claims: list[dict]) -> None:
    pending_store.upsert(bank, PendingEntity(
        name=name, type="person", description=f"{name}, said once.", source_episode=EP1, confidence=0.7, tags=[],
        history_entries=[], held_claims=claims, held_against=against,
        heard_in=[{"episode": EP1}, {"episode": EP2}]))


def _question(bank: Path, item_id: str, name: str, target_id: str, target_name: str, *, held: bool = True,
              entity_id: str = "", fold_page: bool = False, created: str = "2026-10-02") -> None:
    """A "Possible duplicate" question as Stage 2 writes it about a mention it held (``held_mention``), or — with
    ``held=False`` — a question about a page (``fold_page`` for #483's exclusive-relation one)."""
    markdown_parser.write(bank / "inbox" / f"{item_id}.md", {
        **({"held_mention": True} if held else {}), **({"fold_page": True} if fold_page else {}),
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.7,
        "entity_id": entity_id or name.lower().replace(" ", "-"), "entity_name": name,
        "title": f"Is {name} the same as {target_name}?", "uncertainty_type": f"Possible duplicate of {target_name}",
        "suggested_classification": f"person — could refer to the same person as {target_name}",
        "suggested_confidence": 0.7, "created_date": created, "source_episode": EP1,
        "merge_target_hint": target_id}, "Could not safely decide.")


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(inbox_tend, "_RECORD_READ", {})
    from api.services import predicates

    root = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (root / sub).mkdir(parents=True)
    predicates.install_predicate_map(root)
    for eid, name in (("alex", "Alex"), ("alex-kim", "Alex Kim"), ("alex-lee", "Alex Lee"),
                      ("mira-quell", "Mira Quell")):
        _page(root, eid, name, "person")
    # "Alex" held against the page called Alex: one claim about Alex, one of Mira's naming Alex as its object.
    _line(root, "Alex", "alex", [_held("alex", "mentors", "mira-quell", 1, EP1),
                                 _held("mira-quell", "works-with", "alex", 2, EP2)])
    _question(root, "inbox-001", "Alex", "alex-kim", "Alex Kim")
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        _git(root, *args)
    _commit(root)
    return root


def _answer(bank: Path, item_id: str, **request):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service

    return asyncio.run(inbox_service.resolve(item_id, InboxResolveRequest(**request), _Settings(bank)))


def _claims(bank: Path, eid: str) -> list[tuple[str, str, str]]:
    return [(c.subject, c.predicate, c.object)
            for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{eid}.md").body)]


def _line_claims(bank: Path, name: str) -> list[str]:
    return [d["id"] for e in pending_store.load(bank) if e.name == name for d in e.held_claims]


def _answer_commit(bank: Path) -> tuple[str, list[str]]:
    sha = _git(bank, "log", "-1", "--fixed-strings", "--grep=Inbox resolution", "--format=%H").strip()
    return _git(bank, "show", "-s", "--format=%B", sha), _git(bank, "show", "--name-only", "--format=", sha).split()


# --------------------------------------------------------------------------- "same as B"


def test_same_as_b_lands_the_held_claims_on_b_both_ways_in_the_answers_own_commit(bank):
    _answer(bank, "inbox-001", action="merge", merge_target="alex-kim")

    assert ("alex-kim", "mentors", "mira-quell") in _claims(bank, "alex-kim")
    assert ("mira-quell", "works-with", "alex-kim") in _claims(bank, "mira-quell"), "object-side: re-pointed at B"
    assert _claims(bank, "alex") == [], "never the page that only shares the name"
    assert _line_claims(bank, "Alex") == [], "released: nothing left held"
    fm = markdown_parser.parse(bank / "entities" / "alex-kim.md").frontmatter
    assert EP1 in fm["source_episodes"], "the conversation a released claim was heard in credits B"
    assert EP2 in markdown_parser.parse(bank / "entities" / "mira-quell.md").frontmatter["source_episodes"]

    message, files = _answer_commit(bank)
    assert {"entities/alex-kim.md", "entities/mira-quell.md", "pending_entities.jsonl"} <= set(files)
    assert "Cicada-Author: user" in message
    assert not _git(bank, "status", "--porcelain").strip()


def test_same_as_b_on_a_name_with_no_page_releases_and_retires_its_line(bank):
    _line(bank, "Alexa Quill", "", [_held("alexa-quill", "lives-in", "mira-quell", 3, EP1)])
    _question(bank, "inbox-002", "Alexa Quill", "alex-kim", "Alex Kim")
    _commit(bank, "a second question")

    _answer(bank, "inbox-002", action="merge", merge_target="alex-kim")

    assert ("alex-kim", "lives-in", "mira-quell") in _claims(bank, "alex-kim")
    assert not [e for e in pending_store.load(bank) if e.name == "Alexa Quill"], "nothing held: the line leaves"
    assert "Alexa Quill" in markdown_parser.parse(bank / "entities" / "alex-kim.md").frontmatter["aliases"]
    assert _line_claims(bank, "Alex") == ["clm_held_1", "clm_held_2"], "another name's line is untouched"


def test_an_object_side_claim_whose_page_is_gone_stays_held(bank):
    _line(bank, "Alex", "alex", [_held("ghost-page", "knows", "alex", 4, EP1)])   # carried onto the same line
    _commit(bank, "a claim of a page that no longer exists")

    _answer(bank, "inbox-001", action="merge", merge_target="alex-kim")

    assert _line_claims(bank, "Alex") == ["clm_held_4"], "only what could not land is still held"
    assert ("alex-kim", "mentors", "mira-quell") in _claims(bank, "alex-kim")


# --------------------------------------------------------------------------- nothing released


@pytest.mark.parametrize("request_", [
    {"action": "reject", "merge_target": "alex-kim"},   # "someone else"
    {"action": "dismiss"},                              # "stop asking"
    {"action": "skip"},
], ids=["someone-else", "dismiss", "skip"])
def test_someone_else_dismiss_and_skip_release_nothing(bank, request_):
    pages = {p.name: p.read_bytes() for p in (bank / "entities").glob("*.md")}

    _answer(bank, "inbox-001", **request_)

    assert {p.name: p.read_bytes() for p in (bank / "entities").glob("*.md")} == pages
    line = next(e for e in pending_store.load(bank) if e.name == "Alex")
    assert [d["id"] for d in line.held_claims] == ["clm_held_1", "clm_held_2"] and line.held_against == "alex"
    if request_["action"] != "skip":
        assert merge_rejections.is_rejected(bank, "alex", "alex-kim")


def test_someone_else_keeps_the_claims_held_until_stage_2_gives_the_name_its_own_page(bank):
    """The promotion rail decides "someone new": the resolver never mints a page. A later cycle that does not decide
    the name releases nothing onto the page that shares it; Stage 2's own "<name> (another)" page takes them."""
    _answer(bank, "inbox-001", action="reject", merge_target="alex-kim")
    settings = type("S", (), {"memory_path": bank, "litellm_model": "m", "archive_threshold": 0.2,
                              "decay_nudge_threshold": 0.4})()

    later = claim_pipeline.run_claim_pipeline([], [], bank, settings, now_date="2026-10-05",
                                              name_to_id={"alex": "alex"}, decided_names=[])
    assert later["claims_released"] == 0 and _claims(bank, "alex") == []

    _page(bank, "alex-another", "Alex (another)", "person")   # what Stage 2 creates once the name qualifies
    born = claim_pipeline.run_claim_pipeline([], [], bank, settings, now_date="2026-10-06",
                                             name_to_id={"alex": "alex-another"}, decided_names=["alex"])
    assert born["claims_released"] == 2
    assert ("alex-another", "mentors", "mira-quell") in _claims(bank, "alex-another")


# --------------------------------------------------------------------------- undo


def test_sleeps_undo_of_a_same_answer_takes_the_released_claims_back_off(bank):
    # A name with no page (so the settle folds no page): one claim of its own, one of Mira's naming it.
    _line(bank, "Alexa Quill", "", [_held("alexa-quill", "lives-in", "mira-quell", 3, EP1),
                                    _held("mira-quell", "knows", "alexa-quill", 5, EP2)])
    _question(bank, "inbox-002", "Alexa Quill", "alex-kim", "Alex Kim")
    _commit(bank, "a held name with no page")
    files = ("entities/alex-kim.md", "entities/mira-quell.md", "pending_entities.jsonl")
    before = {p: (bank / p).read_bytes() for p in files}
    d = inbox_tend.Decision("inbox-002", "merge_suggestion", "judged_same",
                            {"action": "merge", "merge_target": "alex-kim"}, answer="Same as Alex Kim")
    d.fingerprint = (bank / "inbox" / "inbox-002.md").read_bytes()

    assert asyncio.run(inbox_tend.apply(bank, _Settings(bank), d))
    assert ("alex-kim", "lives-in", "mira-quell") in _claims(bank, "alex-kim")
    assert ("mira-quell", "knows", "alex-kim") in _claims(bank, "mira-quell")
    assert not [e for e in pending_store.load(bank) if e.name == "Alexa Quill"]
    message = _git(bank, "log", "-1", "--fixed-strings", "--grep=Inbox settled by Sleep", "--format=%B")
    assert "pending_entities.jsonl" in message and "Cicada-Author: user" not in message, "Sleep's commit, not the person's"

    from api.services import web_settle

    _r, paths, lines, _rec = inbox_tend.undo(bank, "inbox-002")
    web_settle.commit_sync(bank, web_settle.commit_message("Sleep's settle undone", lines, authors=["user"]), paths)
    assert {p: (bank / p).read_bytes() for p in files} == before, "the pages and the held line, byte for byte"
    assert (bank / "inbox" / "inbox-002.md").exists(), "the question is back"
    assert not _git(bank, "status", "--porcelain").strip()


def test_reverting_the_persons_answer_commit_takes_the_release_back(bank):
    files = ("entities/alex-kim.md", "entities/mira-quell.md", "pending_entities.jsonl")
    before = {p: (bank / p).read_bytes() for p in files}
    _answer(bank, "inbox-001", action="merge", merge_target="alex-kim")
    sha = _git(bank, "log", "-1", "--fixed-strings", "--grep=Inbox resolution", "--format=%H").strip()

    _git(bank, "revert", "--no-edit", sha)

    assert {p: (bank / p).read_bytes() for p in files} == before


# --------------------------------------------------------------------------- once, and never the wrong page


def test_a_held_line_is_released_once_never_again_onto_another_page(bank):
    _question(bank, "inbox-002", "Alex", "alex-lee", "Alex Lee")
    _commit(bank, "a second question about the same name")

    _answer(bank, "inbox-001", action="merge", merge_target="alex-kim")
    _answer(bank, "inbox-002", action="merge", merge_target="alex-lee")

    assert _claims(bank, "alex-lee") == [], "the line was already released onto the page first named"
    kim = _claims(bank, "alex-kim")
    assert kim.count(("alex-kim", "mentors", "mira-quell")) == 1
    assert _claims(bank, "mira-quell").count(("mira-quell", "works-with", "alex-kim")) == 1

    # Nor does a later Stage 2 verdict on the name release it a second time.
    settings = type("S", (), {"memory_path": bank, "litellm_model": "m", "archive_threshold": 0.2,
                              "decay_nudge_threshold": 0.4})()
    later = claim_pipeline.run_claim_pipeline([], [], bank, settings, now_date="2026-10-05",
                                              name_to_id={"alex": "alex-lee"}, decided_names=["alex"])
    assert later["claims_released"] == 0 and _claims(bank, "alex-lee") == []


# --------------------------------------------------------------------------- review of #484


def _open(bank: Path, eid: str) -> list[tuple[str, str, str]]:
    return sorted((c.subject, c.predicate, c.object)
                  for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{eid}.md").body)
                  if c.valid_to is None and not c.superseded_by)


def _reconcile_fixture(bank: Path) -> None:
    """``alex-kim`` already holds ``mentors mira-quell`` and ``part-of alpha-team`` (single-valued); the held line
    restates the first and says ``part-of beta-team``."""
    from api.services.claims import write_claims

    page = bank / "entities" / "alex-kim.md"
    parsed = markdown_parser.parse(page)
    direct = [Claim(id=f"clm_direct_{n}", text=f"alex-kim {p} {o}", subject="alex-kim", predicate=p, object=o,
                    valid_from="2026-09-01", recorded_at="2026-09-01", source_episodes=["ep_2026-09-01_001"])
              for n, (p, o) in enumerate((("mentors", "mira-quell"), ("part-of", "alpha-team")), 1)]
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, direct))
    _line(bank, "Alex", "alex", [_held("alex", "part-of", "beta-team", 6, EP2)])   # carried onto the line
    _commit(bank, "a page that already says things")


def test_released_claims_meet_stage_3_like_stage_2s_release(bank, tmp_path):
    import shutil

    _reconcile_fixture(bank)
    copy = tmp_path / "stage2-copy"
    shutil.copytree(bank, copy)

    _answer(bank, "inbox-001", action="merge", merge_target="alex-kim")
    answered = _open(bank, "alex-kim")
    assert answered.count(("alex-kim", "mentors", "mira-quell")) == 1, "a restatement is reinforced, not doubled"
    assert [o for _s, p, o in answered if p == "part-of"] == ["beta-team"], "single-valued: one open part-of"

    # The same line released by Stage 2 on the same bank leaves the same open claims.
    settings = type("S", (), {"memory_path": copy, "litellm_model": "m", "archive_threshold": 0.2,
                              "decay_nudge_threshold": 0.4})()
    claim_pipeline.run_claim_pipeline([], [], copy, settings, now_date=None,
                                      name_to_id={"alex": "alex-kim"}, decided_names=["alex"], decay=False)
    assert _open(copy, "alex-kim") == answered


def test_an_answer_about_the_page_never_releases_a_line_held_against_it(bank):
    _page(bank, "kesa-lin", "Kesa Lin", "person")
    # #483's exclusive-relation question: about PAGE alex, folding it into kesa-lin on "same".
    _question(bank, "inbox-003", "Alex", "kesa-lin", "Kesa Lin", held=False, entity_id="alex", fold_page=True)
    _commit(bank, "an exclusive-relation question")

    _answer(bank, "inbox-003", action="merge", merge_target="kesa-lin")

    assert ("kesa-lin", "mentors", "mira-quell") not in _claims(bank, "kesa-lin")
    assert ("mira-quell", "works-with", "kesa-lin") not in _claims(bank, "mira-quell")
    assert _line_claims(bank, "Alex") == ["clm_held_1", "clm_held_2"], "refused for alex: still held"


def test_an_unmarked_question_on_the_page_a_line_was_held_against_releases_nothing(bank):
    """A page-pair question (a dedup sweep's, or one from before the mark) whose subject is the page the line was
    held against says nothing about the mention."""
    _question(bank, "inbox-003", "Alex", "alex-lee", "Alex Lee", held=False)
    _commit(bank, "a page question")

    _answer(bank, "inbox-003", action="merge", merge_target="alex-lee")

    assert _claims(bank, "alex-lee") == [] and _line_claims(bank, "Alex") == ["clm_held_1", "clm_held_2"]


@pytest.mark.parametrize("held", [True, False], ids=["marked", "unmarked-but-held-against"])
def test_sleeps_same_settle_on_a_held_mention_never_folds_the_page_sharing_its_id(bank, held):
    if not held:
        _question(bank, "inbox-001", "Alex", "alex-kim", "Alex Kim", held=False)
        _commit(bank, "an older question with no mark")
    alex = (bank / "entities" / "alex.md").read_bytes()
    d = inbox_tend.Decision("inbox-001", "merge_suggestion", "judged_same",
                            {"action": "merge", "merge_target": "alex-kim"}, answer="Same as Alex Kim")
    d.fingerprint = (bank / "inbox" / "inbox-001.md").read_bytes()

    assert asyncio.run(inbox_tend.apply(bank, _Settings(bank), d))

    assert (bank / "entities" / "alex.md").read_bytes() == alex, "the page the mention was held against is untouched"
    if held:   # asked about the mention: its claims land on the page Sleep judged it to be
        assert ("alex-kim", "mentors", "mira-quell") in _claims(bank, "alex-kim")
    else:      # unmarked, so possibly about the page: nothing released, nothing folded
        assert _line_claims(bank, "Alex") == ["clm_held_1", "clm_held_2"]


def test_stage_2_marks_the_questions_it_raises_about_a_held_mention(tmp_path):
    from api.services import entity_resolver as er
    from api.services.clarification_manager import ClarificationManager

    root = tmp_path / "memory"
    (root / "inbox").mkdir(parents=True)
    clarifier = ClarificationManager(root)
    page = {"id": "alex", "frontmatter": {"name": "Alex", "type": "person"}, "body": ""}
    er._create_duplicate_clarification(clarifier, {"name": "Alex", "type": "person", "source_episode": EP1},
                                       {"source": "existing", "id": "alex", "data": page})
    [item] = (root / "inbox").glob("inbox-*.md")
    assert markdown_parser.parse(item).frontmatter.get(er.HELD_MENTION_KEY) is True


@pytest.mark.parametrize("created, folds", [("2026-10-27", False), ("2026-11-03", False), ("2026-10-26", True)])
def test_sleep_never_folds_an_unflagged_question_from_483_on_once_its_line_is_gone(bank, created, folds):
    """#483 held names before Stage 2 marked its questions: an unflagged "Is Alex the same as Alex Kim?" raised from its
    merge day on may be about a held mention whose id is page alex's. Stage 2 later joins "Alex" elsewhere and its line
    leaves the store; the question stays open (`check_organic_resolution`). Sleep's "same" must not fold page alex then.
    An older unflagged page-pair question keeps ruling 29's fold."""
    from api.services import inbox_service

    assert inbox_service.UNFLAGGED_FOLD_CUTOFF == "2026-10-27"
    _question(bank, "inbox-001", "Alex", "alex-kim", "Alex Kim", held=False, created=created)
    pending_store.release(bank, ["Alex"])   # Stage 2 joined "Alex" to alex-lee; its line is gone
    _commit(bank, "an unflagged question whose line has left")
    d = inbox_tend.Decision("inbox-001", "merge_suggestion", "judged_same",
                            {"action": "merge", "merge_target": "alex-kim"}, answer="Same as Alex Kim")
    d.fingerprint = (bank / "inbox" / "inbox-001.md").read_bytes()

    assert asyncio.run(inbox_tend.apply(bank, _Settings(bank), d))

    assert (bank / "entities" / "alex.md").exists() is not folds
