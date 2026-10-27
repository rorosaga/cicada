"""The 2026-10-27 misread trace: one synthetic test per class it found (G118, G209, G149, G115, G21).

Every name below is a placeholder (`alpha-lab`, `<city>`-style names); nothing comes from a bank.
"""
from __future__ import annotations

from pathlib import Path

from api.services import (bank_index, entity_resolver, everyday_names, hook_recall, inbox_ask_gate, inbox_generator,
                          markdown_parser, participation, person_leads, search_index)


# ---------- item 2: a re-raised description conflict joins the answers already open ----------

def _conflict(memory: Path, options: list[dict], predicate: str = "description") -> Path:
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / "inbox-001.md"
    markdown_parser.write(path, {
        "kind": "conflict", "required_input": "choice", "status": "pending", "priority": 0.8,
        "entity_id": "owner-a", "entity_name": "Owner A", "title": "q", "created_date": "2026-10-16",
        "predicate": predicate, "question": "Is alpha-project still in beta?", "options": options,
    }, "context")
    return path


_BOTH = {"key": "both", "label": "Both are true (different contexts)"}


def test_a_reworded_pair_bumps_the_open_answers_instead_of_appending(tmp_path):
    path = _conflict(tmp_path, [
        {"key": "a", "label": "Still in the beta", "observed_at": "2026-10-21", "last_referenced": "2026-10-21"},
        {"key": "b", "label": "Already in production", "observed_at": "2026-10-21", "last_referenced": "2026-10-21"},
        _BOTH,
    ])
    changed = inbox_generator.merge_options_into(path, [
        {"key": "a", "label": "Final beta weeks", "observed_at": "2026-10-23"},
        {"key": "b", "label": "Already shipped to production", "observed_at": "2026-10-23"},
        _BOTH,
    ], "2026-10-23")
    options = markdown_parser.parse(path).frontmatter["options"]
    assert changed is True
    assert [o["key"] for o in options] == ["a", "b", "both"]
    assert [o["label"] for o in options][:2] == ["Still in the beta", "Already in production"]   # what the person saw
    assert all(o["last_referenced"] == "2026-10-23" for o in options[:2])


def test_one_matching_side_pulls_its_counterpart_in(tmp_path):
    """Only "Phase two, planned" says what an open answer says; "Merged on the sixth" is that pair's other side."""
    path = _conflict(tmp_path, [
        {"key": "a", "label": "Shipped as release one", "observed_at": "2026-10-14"},
        {"key": "b", "label": "Planned for phase two", "observed_at": "2026-10-14"},
        _BOTH,
    ])
    inbox_generator.merge_options_into(path, [
        {"key": "a", "label": "Merged on the sixth", "observed_at": "2026-10-22"},
        {"key": "b", "label": "Phase two, planned", "observed_at": "2026-10-22"},
    ], "2026-10-22")
    keys = [o["key"] for o in markdown_parser.parse(path).frontmatter["options"]]
    assert keys == ["a", "b", "both"]


def test_a_new_contradiction_is_still_appended_as_one_pair(tmp_path):
    path = _conflict(tmp_path, [
        {"key": "a", "label": "Still in the beta", "observed_at": "2026-10-21"},
        {"key": "b", "label": "Already in production", "observed_at": "2026-10-21"},
        _BOTH,
    ])
    inbox_generator.merge_options_into(path, [
        {"key": "a", "label": "Manual start only", "observed_at": "2026-10-22"},
        {"key": "b", "label": "Nightly scheduled job", "observed_at": "2026-10-22"},
    ], "2026-10-22")
    options = markdown_parser.parse(path).frontmatter["options"]
    assert [o["key"] for o in options] == ["a", "b", "ax", "bx", "both"]
    assert options[2][inbox_generator.RAISED_WITH] == options[3][inbox_generator.RAISED_WITH] == "ax"
    # The next night re-raises it: one side in near words, the other in new ones — joined through the stored pairing.
    inbox_generator.merge_options_into(path, [
        {"key": "a", "label": "Started by a click", "observed_at": "2026-10-23"},
        {"key": "b", "label": "Nightly scheduled job runs", "observed_at": "2026-10-23"},
    ], "2026-10-23")
    assert len(markdown_parser.parse(path).frontmatter["options"]) == 5


def test_claim_values_never_join_on_resemblance(tmp_path):
    """A claim conflict's answers are values: "Alpha Labs" is not "Alpha", and a new value is a new answer."""
    path = _conflict(tmp_path, [
        {"key": "a", "label": "Alpha", "claim_id": "clm_a", "observed_at": "2026-10-01"},
        {"key": "b", "label": "Beta", "claim_id": "clm_b", "observed_at": "2026-10-01"},
        _BOTH,
    ], predicate="works-at")
    inbox_generator.merge_options_into(path, [
        {"key": "a", "label": "Alpha", "claim_id": "clm_a2", "observed_at": "2026-10-05"},
        {"key": "b", "label": "Alpha Labs", "claim_id": "clm_c", "observed_at": "2026-10-05"},
    ], "2026-10-05")
    labels = [o["label"] for o in markdown_parser.parse(path).frontmatter["options"]]
    assert labels == ["Alpha", "Beta", "Alpha Labs", "Both are true (different contexts)"]


def test_near_duplicate_needs_subject_words():
    assert inbox_generator.near_duplicate("Already in production", "Already shipped to production")
    assert inbox_generator.near_duplicate("Lock in review", "Lock review still open")
    assert not inbox_generator.near_duplicate("1,234", "about 2,000")
    assert not inbox_generator.near_duplicate("Still in the beta", "Already in production")
    # One shared word is chance; a negation on one side is the opposite answer.
    assert not inbox_generator.near_duplicate("Still in the beta", "Final beta weeks")
    assert not inbox_generator.near_duplicate("AI agent", "Agent harness")
    assert not inbox_generator.near_duplicate("The service takes the lock", "The service takes no lock")


# ---------- item 5a: the fuzzy join never takes a name with a word or number the other lacks ----------

def test_distinct_names_are_not_one_spelling():
    for a, b in [("SH Example City", "Example City"), ("Amazon EBS", "Amazon EKS"), ("Course 2", "Course 1"),
                 ("Best-first search", "Breadth-first search"), ("Acme Chrome Extension", "Chrome Extension"),
                 ("Model 5.5", "Model 4.6")]:
        assert entity_resolver.distinct_names(a.lower(), b.lower()), (a, b)
        assert not entity_resolver.fuzzy_same(a, b), (a, b)
    for a, b in [("3D Robotic Arm Project", "3D Robot Arm Project"), ("Andrew Example", "Andrej Example"),
                 ("OpenAI", "Open AI"), ("Algo Visualizer", "Algorithm Visualizer")]:
        assert entity_resolver.fuzzy_same(a, b), (a, b)


def test_an_edge_endpoint_never_lands_on_a_page_sharing_most_letters():
    table = {"example city": "example-city", "alpha robot arm": "alpha-robot-arm"}
    assert entity_resolver.endpoint_id("SH Example City", table) is None
    assert entity_resolver.endpoint_id("Alpha Robotic Arm", table) == "alpha-robot-arm"


def test_the_direct_match_sends_a_distinct_name_to_the_judge_not_the_page():
    page = {"id": "example-city", "frontmatter": {"name": "Example City", "type": "location"}, "body": ""}
    new = {"name": "SH Example City", "type": "location"}
    assert entity_resolver._find_direct_candidate_match(
        new_entity=new, existing_by_name={"example city": page}, created_by_id={}) is None
    # ... and the page it shares a word with is one of the judge's candidates.
    candidates = entity_resolver._existing_llm_candidates(new, {"example city": page})
    assert [c["id"] for c in candidates] == ["example-city"]


# ---------- item 1: taking part needs the role in the cited words ----------

def _rel(label: str, body: str, quote: str, kind: str = "assistant") -> dict:
    start = body.index(quote)
    return {"source": "Owner A", "target": "Example Olympiad", "label": label, "starts": "2026-01-01",
            "evidence": [{"episode": "ep_x", "start": start, "end": start + len(quote), "kind": kind}]}


def test_a_story_about_an_event_is_a_mention_not_taking_part():
    body = "Q4 answer: the Example Olympiad story (how the robot project began)."
    rel = _rel("competed in", body, "the Example Olympiad story")
    assert participation.hold(rel, body) == "competed in"
    assert rel["label"] == participation.MENTIONED and "starts" not in rel


def test_a_negated_or_someone_elses_role_is_no_role():
    body = "He was helping a friend at the Example Olympiad qualifiers, and did not compete himself."
    rel = _rel("competed in", body, body)
    assert participation.hold(rel, body) == "competed in", "helping is not competing; 'did not compete' is no role"


def test_the_role_in_the_words_keeps_the_relationship():
    body = "We competed in the Example Olympiad finals and placed third."
    rel = _rel("competed in", body, "We competed in the Example Olympiad finals")
    assert participation.hold(rel, body) is None and rel["label"] == "competed in"
    work = "I started my internship at Example Corp in June."
    rel = _rel("works at", work, work)
    assert participation.hold(rel, work) is None


def test_no_located_span_keeps_the_claim():
    """G118: an unlocatable quote becomes reasoning and the claim is still written — dates included."""
    rel = {"source": "Owner A", "target": "Example Hackathon", "label": "won", "starts": "2026-03-01",
           "evidence": [{"reasoning": "x"}]}
    assert participation.hold(rel, "anything") is None
    assert rel["label"] == "won" and rel["starts"] == "2026-03-01"


#: The review's cases (#491): a role said every way people say it.
REVIEW_CASES = [
    ("works at", "my new gig at Acme"),
    ("works at", "I am at Acme since June"),
    ("works at", "Acme (2023-2024)"),
    ("placed second at", "We got second at HackX"),
    ("attended", "I went to HackX last weekend"),
    ("graduated from", "Me gradué de la UPM en 2023"),
    ("attended", "Estuvimos en la conferencia X"),
]


def test_the_persons_own_words_keep_every_way_of_saying_a_role():
    for label, said in REVIEW_CASES:
        body = f"user: {said}. Anyway, more later."
        rel = _rel(label, body, said, kind="user")
        assert participation.hold(rel, body) is None, (label, said)
        assert rel["label"] == label


def test_a_summary_that_only_says_the_story_is_still_a_mention():
    for label, _said in REVIEW_CASES:
        body = "assistant: Q4 answer: the HackX story, how the robot project began."
        rel = _rel(label, body, "the HackX story")
        assert participation.hold(rel, body) == label, label
        assert rel["label"] == participation.MENTIONED


def test_the_persons_own_words_about_a_story_are_a_mention():
    body = "user: my application essay was about the HackX story."
    rel = _rel("competed in", body, "my application essay was about the HackX story", kind="user")
    assert participation.hold(rel, body) == "competed in"


def test_the_role_may_sit_in_the_next_sentence():
    body = "assistant: Notes on HackX. The team placed and the demo went well. Next steps below."
    rel = _rel("competed in", body, "Notes on HackX")
    assert participation.hold(rel, body) is None


def test_other_labels_are_not_this_rules_to_judge():
    for label in ("competes with", "planned to attend", "uses", "helped at", "mentioned", "works with"):
        assert participation.hold({"label": label, "evidence": []}, "") is None, label


def test_the_extraction_prompt_states_the_rule():
    from api.services.entity_extractor import EXTRACTION_SYSTEM_PROMPT

    assert "TAKING PART NEEDS A ROLE IN THE TEXT" in EXTRACTION_SYSTEM_PROMPT


# ---------- item 3: organisations, labs, projects and tools get the alias lead people have ----------

def _org(pid: str, name: str, etype: str, aliases=()) -> dict:
    return {"id": pid, "frontmatter": {"name": name, "type": etype, "aliases": list(aliases)}, "body": ""}


def test_one_lab_on_three_pages_is_a_lead_across_company_and_project():
    pages = [_org("alpha-life", "Alpha Life", "company", ["Alpha"]),
             _org("alpha-lab", "Alpha Lab", "company", ["alpha life", "Alpha"]),
             _org("alpha-life-group", "Alpha Life Research Group", "project", ["Alpha Life"]),
             _org("alpha-person", "Alpha Life", "person")]
    index = person_leads.PersonIndex(pages, person_leads.ORG_TYPES)
    pairs = {(lead.page, lead.holder) for lead in index.all_leads()}
    assert ("alpha-life", "alpha-lab") in pairs and ("alpha-life", "alpha-life-group") in pairs
    assert all("alpha-person" not in pair for pair in pairs), "a person never joins an organisation's lead"
    assert person_leads.PersonIndex(pages).by_id.keys() == {"alpha-person"}, "the people index is unchanged"


def test_a_shared_word_is_never_a_lead():
    pages = [_org("alpha-robotics", "Alpha Robotics", "company"), _org("alpha-tools", "Alpha Tools", "tool")]
    assert person_leads.PersonIndex(pages, person_leads.ORG_TYPES).all_leads() == []


def test_an_org_lead_is_asked_as_a_possible_duplicate_never_merged():
    pages = [_org("alpha-life", "Alpha Life", "company"), _org("alpha-lab", "Alpha Lab", "company", ["Alpha Life"])]
    index = person_leads.PersonIndex(pages, person_leads.ORG_TYPES)
    (lead,) = index.leads_for("alpha-life")
    asked: list[dict] = []

    class Clarifier:
        def create(self, **kw):
            asked.append(kw)
            return None

    entity_resolver._create_lead_clarification(Clarifier(), lead, index, {"name": "Alpha Life"})
    assert asked[0]["uncertainty_type"] == "Possible duplicate of Alpha Lab"
    assert asked[0]["suggested_classification"].startswith("company — could refer to the same thing as")
    assert "already lists" in asked[0]["source_context"]


# ---------- item 5b: the hook shows lines about the message, and a common noun names nothing ----------

def _hook_bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)

    def page(eid, name, etype, aliases=(), summary="", claims=()):
        body = f"## Summary\n{summary}\n\n"
        if claims:
            body += "```claims\n" + "".join(
                f"- id: {cid}\n  text: \"{text}\"\n  subject: {eid}\n  predicate: note\n  object: x\n"
                f"  valid_from: '{since}'\n" for cid, text, since in claims) + "```\n"
        markdown_parser.write(memory / "entities" / f"{eid}.md",
                              {"name": name, "type": etype, "status": "active", "confidence": 0.8,
                               "aliases": list(aliases)}, body)

    page("example-city", "Example City", "location", summary="The city where the owner lives.",
         claims=[("c1", "Example City associated with a supplier of another firm", "2026-04-20"),
                 ("c2", "Example City offices of the benchmark company opened in 2026", "2026-03-01"),
                 ("c3", "Example City parking permit renewed by an agency", "2025-06-15")])
    page("gamma-challenge", "Gamma Challenge", "project", aliases=["hackathon", "the hackathon"],
         summary="A model challenge.")
    for n in ("one", "two", "three"):
        page(f"other-hackathon-{n}", f"Other Hackathon {n.title()}", "project", summary="Another event.")
    bank_index.invalidate()
    search_index.reset()
    search_index.rebuild(memory)
    hook_recall.reset()
    return memory


def test_the_note_keeps_only_claims_about_the_message(tmp_path):
    memory = _hook_bank(tmp_path)
    note = hook_recall.prompt_context(memory, "this benchmark company has offices in Example City, a good fit?")
    assert note.injected == ("example-city",)
    assert "offices of the benchmark company" in note.text
    assert "supplier" not in note.text and "parking" not in note.text
    # Nothing on the page is about the message: its summary, and no claim rather than an unrelated one.
    hook_recall.reset()
    note = hook_recall.prompt_context(memory, "I know people who could introduce me to someone in Example City")
    assert "The city where the owner lives." in note.text and "  · " not in note.text
    # A message that only names the page: the page is the subject, its newest claims come.
    hook_recall.reset()
    assert "supplier" in hook_recall.prompt_context(memory, "Example City?").text


def test_a_one_word_alias_many_page_names_share_names_nothing(tmp_path):
    memory = _hook_bank(tmp_path)
    assert "gamma-challenge" not in hook_recall.prompt_context(memory, "who filled in the hackathon form?").injected
    hook_recall.reset()
    assert hook_recall.prompt_context(memory, "how did the Gamma Challenge go?").injected == ("gamma-challenge",)


# ---------- item 6: a page named in nearly every conversation puts nothing in scope on its own ----------

def test_an_everyday_page_needs_two_subject_words():
    fm = {"kind": "conflict", "entity_id": "main-project", "entity_name": "Main Project",
          "predicate": "value-of-conversations-in-import-trial",
          "options": [{"key": "a", "label": "1,234"}, {"key": "b", "label": "about 1,234"}]}
    said = "keep a log of this conversation for the main project"
    assert inbox_ask_gate.relevant(fm, said) == (True, "same_subject")       # one shared word, as before
    assert inbox_ask_gate.relevant(fm, said, everyday=True) == (False, "everyday_page")
    assert inbox_ask_gate.relevant(fm, "the main project import trial counted the conversations",
                                   everyday=True)[0]


def test_an_everyday_question_with_one_subject_word_can_still_pass():
    """A question whose only subject word is one (``min(EVERYDAY_TERMS, len(about))``) is not unaskable."""
    fm = {"kind": "conflict", "entity_id": "main-project", "entity_name": "Main Project", "predicate": "license"}
    assert inbox_ask_gate.subject_terms(fm) == {"licens"}
    assert inbox_ask_gate.relevant(fm, "which license does the main project use?", everyday=True)[0]
    assert not inbox_ask_gate.relevant(fm, "the main project needs a new logo", everyday=True)[0]


def _episodes_bank(root: Path, n_conversations: int, naming: int) -> Path:
    memory = root / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for i in range(n_conversations):
        text = ("user: working on Main Project today, then lunch" if i < naming
                else f"user: an unrelated chat number {i} about cooking")
        day = f"2026-10-{(i % 28) + 1:02d}"
        markdown_parser.write(memory / "episodes" / f"ep_{day}_{i:03d}.md",
                              {"id": f"ep_{day}_{i:03d}", "timestamp": f"{day}T10:00:00+00:00",
                               "origin": "claude-code", "harness": "claude-code", "processed": True}, text)
    markdown_parser.write(memory / "_state.md", {"type": "state", "owner_id": "owner-a"}, "")
    bank_index.invalidate()
    search_index.reset()
    search_index.rebuild(memory)
    return memory


def test_everyday_is_derived_from_the_bank(tmp_path):
    everyday_names.reset()
    memory = _episodes_bank(tmp_path, 40, 15)          # 15 of 40 conversations name it: 37.5%
    assert everyday_names.is_everyday(memory, "main-project", ["Main Project"])
    assert not everyday_names.is_everyday(memory, "side-thing", ["Side Thing"])
    assert everyday_names.is_everyday(memory, "owner-a", ["Owner A"], owner_id="owner-a")
    assert inbox_ask_gate.everyday(memory, {"entity_id": "owner-a", "entity_name": "Owner A"})
    everyday_names.reset()
    few = _episodes_bank(tmp_path / "few", 10, 10)      # too few conversations to say
    assert not everyday_names.is_everyday(few, "main-project", ["Main Project"])
    everyday_names.reset()
