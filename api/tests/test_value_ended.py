"""A value that names what a conversation dropped is read with that drop (G148, 2026-11-23): the matching logic, no model.

Synthetic names only. The judge is a fake that records its prompts and answers with a fixed JSON object.
"""
from __future__ import annotations

from api.services import claim_pipeline, predicates, value_ended
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, value_predicate

OLD_DAY, NEW_DAY = "2026-09-24", "2026-11-08"
OLD_EP, NEW_EP = f"ep_{OLD_DAY}_001", f"ep_{NEW_DAY}_001"
YES, NO = {"out_of_date": True, "why": "test"}, {"out_of_date": False, "why": "test"}


def _value(attribute, literal, day=OLD_DAY, episode=OLD_EP, cid=None, subject="alpha-project", **kw):
    kw = {"source_trust": "agent_extracted", "origin": "benchmark", **kw}
    return Claim(id=cid or f"v_{value_predicate(attribute)}", text=f"{subject} {attribute}: {literal}", subject=subject,
                 predicate=value_predicate(attribute), object=literal, object_kind="literal", valid_from=day,
                 source_episodes=[episode], **kw)


def _ending(thing="python", label="dropped", day=NEW_DAY, episode=NEW_EP, subject="alpha-project", **kw):
    claim = Claim(id="c_end", text=f"{subject} {label} {thing}", subject=subject, predicate=label, object=thing,
                  object_kind="node", valid_from=day, source_episodes=[episode], source_trust="agent_extracted",
                  origin="benchmark", **kw)
    claim.predicate_raw = label
    return claim


class _Judge:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else {}


class _Settings:
    def __init__(self, memory_path):
        self.memory_path = memory_path
        self.litellm_model = "test-model"
        self.archive_threshold = 0.2
        self.decay_nudge_threshold = 0.4


# ---- what counts as naming a thing --------------------------------------------------------------------------------

def test_a_literal_names_a_thing_by_its_whole_words_never_inside_a_longer_word_nor_as_the_whole_literal():
    names = value_ended.names
    assert names("Python with Pillow", "python") and names("Python con Pillow", "python")
    assert names("TypeScript and Python 3.12", "python") and names("the Node.js runtime", "node-js")
    assert not names("Python", "python")                  # the whole literal is `_place_ending`'s own rule
    assert not names("Pythonic style", "python") and not names("Jython", "python")
    assert not names("Rust with Tokio", "python") and not names("", "python") and not names("Python", "")


# ---- which values are asked about ---------------------------------------------------------------------------------

def _pairs(existing, ending=None):
    return value_ended.candidates([ending or _ending()], {"alpha-project": existing}, predicates.build_endings_fn(None))


def test_an_open_older_value_naming_the_dropped_thing_is_a_candidate():
    value = _value("implementation language", "Python with Pillow")
    assert _pairs([value]) == [(_pairs([value])[0][0], value)]
    other = _value("license", "MIT")
    assert [v.id for _e, v in _pairs([value, other])] == [value.id]       # a value naming something else is not


def test_nothing_is_a_candidate_unless_the_ending_really_ends_something_and_the_value_is_older_and_open():
    value = _value("implementation language", "Python with Pillow")
    kinds = predicates.build_endings_fn(None)
    assert value_ended.candidates([_ending(label="uses")], {"alpha-project": [value]}, kinds) == []   # no ending label
    assert value_ended.candidates([_ending(label="used")], {"alpha-project": [value]}, kinds) == []   # a "past" label
    literal = _ending()
    literal.object_kind = "literal"
    assert value_ended.candidates([literal], {"alpha-project": [value]}, kinds) == []
    assert _pairs([_value("implementation language", "Python with Pillow", day="2026-12-01")]) == []   # said after it
    closed = _value("implementation language", "Python with Pillow", valid_to="2026-10-01")
    assert _pairs([closed]) == []
    assert _pairs([_value("implementation language", "Python with Pillow", episode=NEW_EP)]) == []     # said together
    assert value_ended.candidates([_ending(subject="beta-project")], {"alpha-project": [value]}, kinds) == []


def test_an_agents_ending_is_never_asked_about_the_persons_own_value():
    mine = _value("implementation language", "Python with Pillow", source_trust="user_stated", origin="manual_edit")
    assert _pairs([mine]) == []


# ---- the judge ---------------------------------------------------------------------------------------------------

def test_one_call_per_candidate_and_only_a_plain_yes_closes():
    a = _value("implementation language", "Python with Pillow")
    b = _value("test tooling", "pytest on Python 3.12")
    judge = _Judge(YES, {"out_of_date": "yes"})
    closes, audit = value_ended.plan([_ending()], {"alpha-project": [a, b]}, judge)
    assert len(judge.prompts) == 2
    assert closes == {"c_end": {a.id}} and audit == [{"action": "value_ended_by", "claim": a.id, "by": "c_end"}]
    assert "VALUE: alpha-project implementation language: Python with Pillow (2026-09-24)" in judge.prompts[0]
    assert "LATER: alpha-project dropped python (2026-11-08)" in judge.prompts[0]
    assert "When unsure, it can still be true" in judge.prompts[0]


def test_a_no_an_empty_reply_a_failed_call_and_no_judge_close_nothing():
    value = _value("implementation language", "Python with Pillow")
    for judge in (_Judge(NO), _Judge({}), _Judge("not an object")):
        assert value_ended.plan([_ending()], {"alpha-project": [value]}, judge) == ({}, [])

    def failing(_prompt):
        raise RuntimeError("engine down")
    assert value_ended.plan([_ending()], {"alpha-project": [value]}, failing) == ({}, [])
    assert value_ended.plan([_ending()], {"alpha-project": [value]}, None) == ({}, [])


def test_no_candidate_no_call_and_the_calls_are_bounded():
    judge = _Judge()
    assert value_ended.plan([_ending()], {"alpha-project": [_value("license", "MIT")]}, judge) == ({}, [])
    assert judge.prompts == []
    many = [_value(f"part {i}", f"Python for part {i}") for i in range(value_ended.MAX_ASKS + 10)]
    judge = _Judge(*[NO] * 100)
    value_ended.plan([_ending()], {"alpha-project": many}, judge)
    assert len(judge.prompts) == value_ended.MAX_ASKS


def test_a_refused_pair_is_not_asked_again_once_the_ending_is_no_longer_incoming():
    value = _value("implementation language", "Python with Pillow")
    judge = _Judge(NO)
    value_ended.plan([_ending()], {"alpha-project": [value]}, judge)
    assert len(judge.prompts) == 1
    later = _value("beta users", "120", day="2026-11-20", episode="ep_2026-11-20_001")          # a later batch, no ending
    assert value_ended.plan([later], {"alpha-project": [value]}, judge) == ({}, [])
    assert len(judge.prompts) == 1


def test_the_persons_own_words_behind_the_value_and_the_ending_are_in_the_prompt(tmp_path):
    from api.services import evidence

    (tmp_path / "episodes").mkdir()
    lines = {OLD_EP: "I write it in Python with Pillow for now.", NEW_EP: "I rewrote the core and dropped the Python version."}
    for ep, line in lines.items():
        (tmp_path / "episodes" / f"{ep}.md").write_text(
            f"---\nid: {ep}\ntimestamp: '{ep[3:13]}T10:00:00+00:00'\nsource: import\nprocessed: true\n---\n\nuser: {line}\n",
            encoding="utf-8")
    value, ending = _value("implementation language", "Python with Pillow"), _ending()
    value.evidence = [evidence.verify(tmp_path, OLD_EP, lines[OLD_EP])]
    ending.evidence = [evidence.verify(tmp_path, NEW_EP, lines[NEW_EP])]
    judge = _Judge(YES)
    value_ended.plan([ending], {"alpha-project": [value]}, judge, tmp_path)
    assert f'they said: "{lines[OLD_EP]}"' in judge.prompts[0] and f'they said: "{lines[NEW_EP]}"' in judge.prompts[0]
    bare = _Judge(YES)
    value_ended.plan([_ending()], {"alpha-project": [_value("implementation language", "Python with Pillow")]}, bare)
    assert "they said" not in bare.prompts[0]


# ---- Stage 3 closes it like the link ----------------------------------------------------------------------------

def _reconcile(tmp_path, existing, ended_values):
    predicates.install_predicate_map(tmp_path)
    return reconcile_stage3([_ending()], {"alpha-project": existing}, _Settings(tmp_path), cardinality_fn=lambda _p: False,
                            now_date="2026-11-23", decay=False, ended_values=ended_values)[0]["alpha-project"]


def test_a_value_the_judge_ended_closes_with_the_link_and_nothing_is_deleted(tmp_path):
    link = Claim(id="c_link", text="alpha-project uses python", subject="alpha-project", predicate="uses", object="python",
                 object_kind="node", valid_from=OLD_DAY, source_episodes=[OLD_EP], source_trust="agent_extracted",
                 origin="benchmark")
    value = _value("implementation language", "Python with Pillow")
    kept = _value("license", "MIT")
    by_id = {c.id: c for c in _reconcile(tmp_path, [link, value, kept], {"c_end": {value.id}})}
    assert by_id[value.id].valid_to == NEW_DAY and by_id[value.id].superseded_by == "c_end"
    assert by_id["c_link"].valid_to == NEW_DAY
    assert by_id[kept.id].valid_to is None and len(by_id) == 4


def test_a_value_the_judge_did_not_end_stays_open_and_the_persons_own_value_is_never_closed(tmp_path):
    value = _value("implementation language", "Python with Pillow")
    assert {c.id: c.valid_to for c in _reconcile(tmp_path, [value], {})}[value.id] is None
    mine = _value("implementation language", "Python with Pillow", source_trust="user_stated", origin="manual_edit")
    assert {c.id: c.valid_to for c in _reconcile(tmp_path, [mine], {"c_end": {mine.id}})}[mine.id] is None


def test_through_the_pipeline_the_judge_decides_which_value_a_drop_ends(tmp_path):
    """U3 on 4 of 12 key runs: "implementation language: Python with Pillow" outlived "dropped Python". The counter-case:
    "tooling: Python scripts" about something that stays."""
    from api.tests.test_new_user_endings import PROJECT, _bank, _claims, _settings

    memory = _bank(tmp_path)

    def read(day, relationships=(), values=()):
        return [{"episode_id": f"ep_{day}_001", "episode_timestamp": f"{day}T10:00:00", "origin": "chatgpt",
                 "entities": [], "relationships": [
                     {"source": "alpha-project", "target": t, "label": label, "source_episode": f"ep_{day}_001",
                      "source_episode_timestamp": f"{day}T10:00:00"} for t, label in relationships],
                 "values": [{"entity": "alpha-project", "attribute": a, "value": v, "source_episode": f"ep_{day}_001",
                             "source_episode_timestamp": f"{day}T10:00:00"} for a, v in values]}]

    first = read(OLD_DAY, [("Python", "uses")], [("implementation language", "Python with Pillow"),
                                                   ("scripting", "Python with Click"), ("license", "MIT")])
    claim_pipeline.run_claim_pipeline(first, [], memory, _settings(memory), now_date=OLD_DAY)

    def judge(prompt):                       # the app's page is the whole project; the scripts are another purpose
        return YES if "implementation language" in prompt else NO
    claim_pipeline.run_claim_pipeline(read(NEW_DAY, [("Python", "dropped")]), [], memory, _settings(memory),
                                      now_date=NEW_DAY, value_judge=judge)
    language = _claims(memory, PROJECT, "value-of-implementation-language")
    scripting = _claims(memory, PROJECT, "value-of-scripting")
    licence = _claims(memory, PROJECT, "value-of-license")
    assert language and all(c.valid_to == NEW_DAY and c.superseded_by for c in language)
    assert scripting and not scripting[0].valid_to and licence and not licence[0].valid_to


# ---- 2026-11-24: what rested on the thing that ended (a job title at an employer, a project of it) ------------------

LEFT = "left"


def _leave(subject="ines-varga", thing="halvard", day=NEW_DAY, episode=NEW_EP):
    claim = Claim(id="c_left", text=f"{subject} left {thing}", subject=subject, predicate=LEFT, object=thing,
                  object_kind="node", valid_from=day, source_episodes=[episode], source_trust="agent_extracted",
                  origin="benchmark")
    claim.predicate_raw = LEFT
    return claim


def _link(subject, predicate, obj, cid, text=None, day=OLD_DAY, episode=OLD_EP, **kw):
    kw = {"source_trust": "agent_extracted", "origin": "benchmark", **kw}
    return Claim(id=cid, text=text or f"{subject} {predicate.replace('-', ' ')} {obj}", subject=subject,
                 predicate=predicate, object=obj, object_kind="node", valid_from=day, source_episodes=[episode], **kw)


def _scope(existing, ending=None):
    return value_ended.scope_candidates([ending or _leave()], existing, predicates.build_endings_fn(None))


def _kinds(existing, ending=None):
    return {c.id: kind for _e, c, kind, _tie in _scope(existing, ending)}


def test_a_value_whose_attribute_names_the_employer_left_is_a_candidate_though_its_literal_does_not():
    title = _value("job title at Halvard Analytics", "data engineer", subject="ines-varga", cid="v_title")
    other = _value("job title", "data engineer", subject="ines-varga", cid="v_other")
    assert _kinds({"ines-varga": [title, other]}) == {"v_title": "attribute"}


def test_what_names_the_thing_or_hangs_on_a_page_tied_to_it_is_a_candidate_what_does_not_is_not():
    leads = _link("ines-varga", "leads", "halvard-warehouse-migration", "n_leads")
    works_on = _link("ines-varga", "works-on", "snowflake-migration", "n_works")
    tie = _link("snowflake-migration", "belongs-to", "halvard", "t_tie", text="Snowflake migration belongs to Halvard")
    friend = _link("ines-varga", "trains-with", "sam-okafor", "n_friend")
    sam = _link("sam-okafor", "lives-in", "porto", "s_porto")
    same = _link("ines-varga", "interviewed-with", "halvard", "n_same")
    existing = {"ines-varga": [leads, works_on, friend, same], "snowflake-migration": [tie], "sam-okafor": [sam]}
    assert _kinds(existing) == {"n_leads": "names-it", "n_works": "on-a-thing-of", "n_same": "same-object"}
    assert [t.id for *_x, t in _scope(existing) if t][:1] == ["t_tie"]


def test_a_claim_said_after_the_leaving_with_the_leaving_or_closed_or_a_persons_own_is_never_a_candidate():
    after = _link("ines-varga", "leads", "halvard-warehouse-migration", "n_after", day="2026-12-01")
    together = _link("ines-varga", "leads", "halvard-warehouse-migration", "n_together", episode=NEW_EP)
    closed = _link("ines-varga", "leads", "halvard-warehouse-migration", "n_closed", valid_to="2026-10-01")
    mine = _link("ines-varga", "leads", "halvard-warehouse-migration", "n_mine", source_trust="user_stated",
                 origin="manual_edit")
    assert _kinds({"ines-varga": [after, together, closed, mine]}) == {}


def test_the_belief_the_ending_closes_itself_is_not_asked_and_an_ending_of_nothing_asks_nothing():
    job = _link("ines-varga", "works-at", "halvard", "n_job")
    assert _kinds({"ines-varga": [job]}) == {}                       # Stage 3's own target, no call
    plain = _leave()
    plain.predicate_raw = "met"                                      # not an ending label
    leads = _link("ines-varga", "leads", "halvard-warehouse-migration", "n_leads")
    assert _kinds({"ines-varga": [leads]}, ending=plain) == {}


def test_another_pages_line_naming_the_person_on_a_page_tied_to_the_employer_is_a_candidate():
    tie = _link("snowflake-migration", "belongs-to", "halvard", "t_tie")
    lead = _value("migration lead", "Ines Varga", subject="snowflake-migration", cid="v_lead")
    other = _value("migration status", "in progress", subject="snowflake-migration", cid="v_status")
    unrelated = _value("migration lead", "Ines Varga", subject="other-migration", cid="v_unrelated")
    existing = {"snowflake-migration": [tie, lead, other], "other-migration": [unrelated]}
    assert _kinds(existing) == {"v_lead": "other-page"}


def test_a_scope_ask_shows_the_fact_the_tie_and_the_leaving_and_only_a_plain_yes_closes():
    leads = _link("ines-varga", "leads", "halvard-warehouse-migration", "n_leads", text="Ines Varga leads Halvard migration")
    works_on = _link("ines-varga", "works-on", "snowflake-migration", "n_works", text="Ines Varga works on Snowflake migration")
    tie = _link("snowflake-migration", "belongs-to", "halvard", "t_tie", text="Snowflake migration belongs to Halvard")
    judge = _Judge(YES, NO)
    closes, audit = value_ended.plan([_leave()], {"ines-varga": [leads, works_on], "snowflake-migration": [tie]}, judge)
    assert closes == {"c_left": {"n_leads"}}
    assert audit == [{"action": "value_ended_by", "claim": "n_leads", "by": "c_left"}]
    assert len(judge.prompts) == 2
    assert "FACT: Ines Varga leads Halvard migration (2026-09-24)" in judge.prompts[0]
    assert "LATER: ines-varga left halvard (2026-11-08)" in judge.prompts[0]
    assert "Snowflake migration belongs to Halvard" in judge.prompts[1]               # the tie, so the judge knows
    assert "When unsure, it can still be true" in judge.prompts[0]


def test_scope_asks_follow_the_value_asks_and_share_one_bound():
    values = [_value(f"part {i}", f"Python for part {i}") for i in range(value_ended.MAX_ASKS)]
    judge = _Judge(*[NO] * 100)
    scope = [_link("alpha-project", "uses-for", "python-tooling", f"n{i}", text=f"alpha-project uses python tooling {i}")
             for i in range(5)]
    value_ended.plan([_ending()], {"alpha-project": values + scope}, judge)
    assert len(judge.prompts) == value_ended.MAX_ASKS
    assert all("VALUE:" in p for p in judge.prompts)                              # the value asks came first


def test_a_closed_claim_on_the_persons_page_and_on_another_page_both_close_with_the_leaving(tmp_path):
    predicates.install_predicate_map(tmp_path)
    job = _link("ines-varga", "works-at", "halvard", "n_job")
    leads = _link("ines-varga", "leads", "halvard-warehouse-migration", "n_leads")
    lead = _value("migration lead", "Ines Varga", subject="snowflake-migration", cid="v_lead")
    kept = _link("ines-varga", "trains-with", "sam-okafor", "n_kept")
    out = reconcile_stage3([_leave()], {"ines-varga": [job, leads, kept], "snowflake-migration": [lead]},
                           _Settings(tmp_path), cardinality_fn=lambda _p: False, now_date="2026-11-23", decay=False,
                           ended_values={"c_left": {"n_leads", "v_lead"}})[0]
    by_id = {c.id: c for s in out.values() for c in s}
    assert by_id["n_job"].valid_to == NEW_DAY
    assert by_id["n_leads"].valid_to == NEW_DAY and by_id["n_leads"].superseded_by == "c_left"
    assert by_id["v_lead"].valid_to == NEW_DAY and by_id["v_lead"].superseded_by == "c_left"
    assert by_id["n_kept"].valid_to is None


def test_through_the_pipeline_leaving_an_employer_closes_what_rested_on_it_and_keeps_what_did_not(tmp_path):
    """The Ines scan: "leads the <employer> migration" stayed current in 145 of 145 stored runs after "left <employer>",
    and a title at the employer whenever no new title came with it. The counter-cases: a friend who still works there, a
    skill learned there, a fact about the employer, and a claim said after the leaving."""
    from api.tests.test_new_user_endings import _bank, _claims, _settings

    memory = _bank(tmp_path)
    person = "bob-example"

    def read(day, rels=(), values=()):
        ep = f"ep_{day}_001"
        return [{"episode_id": ep, "episode_timestamp": f"{day}T10:00:00", "origin": "chatgpt", "entities": [],
                 "relationships": [{"source": s, "target": t, "label": label, "source_episode": ep,
                                    "source_episode_timestamp": f"{day}T10:00:00"} for s, t, label in rels],
                 "values": [{"entity": person, "attribute": a, "value": v, "source_episode": ep,
                             "source_episode_timestamp": f"{day}T10:00:00"} for a, v in values]}]

    first = read(OLD_DAY, [("Bob Example", "Acme", "works at"),
                           ("Bob Example", "Acme billing migration", "leads"),
                           ("Bob Example", "Carol Example", "friends with"),
                           ("Carol Example", "Acme", "works at")],
                 [("job title at Acme", "data analyst"), ("Airflow skill learned at Acme", "intermediate")])
    claim_pipeline.run_claim_pipeline(first, [], memory, _settings(memory), now_date=OLD_DAY)

    asked: list[str] = []

    def judge(prompt):
        asked.append(prompt)
        fact = prompt.split("FACT:")[1].split("\n")[0] if "FACT:" in prompt else ""
        return YES if ("job title" in fact or "leads" in fact) else NO
    later = read(NEW_DAY, [("Bob Example", "Acme", "left")])
    later += read("2026-11-20", values=[("favourite food", "soup acme corp style")])      # said after: never asked
    claim_pipeline.run_claim_pipeline(later[:1], [], memory, _settings(memory), now_date=NEW_DAY, value_judge=judge)

    title = _claims(memory, person, "value-of-job-title-at-acme")
    skill = _claims(memory, person, "value-of-airflow-skill-learned-at-acme")
    leads = _claims(memory, person, "leads")
    friend = _claims(memory, person, "friends-with")
    assert title and all(c.valid_to == NEW_DAY and c.superseded_by for c in title)
    assert leads and all(c.valid_to == NEW_DAY and c.superseded_by for c in leads)
    assert skill and not skill[0].valid_to and friend and not friend[0].valid_to
    assert len(asked) == 3 and all("Acme" in p or "acme" in p for p in asked)     # the title, the skill, the project


def test_an_edge_written_under_a_pages_alias_still_finds_the_ties_of_that_page(tmp_path):
    """The benchmark bank: "leads warehouse-migration" while the page is `snowflake-migration`, alias "Warehouse
    migration" — the page, not the spelling, holds the line that ties it to the employer."""
    from api.services import markdown_parser

    (tmp_path / "entities").mkdir()
    markdown_parser.write(tmp_path / "entities" / "snowflake-migration.md",
                          {"name": "Snowflake migration", "type": "concept", "aliases": ["Warehouse migration"]}, "## Summary\nx")
    leads = _link("ines-varga", "leads", "warehouse-migration", "n_leads")
    tie = _link("snowflake-migration", "is-for", "halvard", "t_tie", text="Warehouse migration is for Halvard")
    existing = {"ines-varga": [leads], "snowflake-migration": [tie]}
    kinds = predicates.build_endings_fn(None)
    assert value_ended.scope_candidates([_leave()], existing, kinds) == []
    found = value_ended.scope_candidates([_leave()], existing, kinds, tmp_path)
    assert [(c.id, kind, t.id) for _e, c, kind, t in found] == [("n_leads", "on-a-thing-of", "t_tie")]


def test_a_value_whose_attribute_or_literal_names_a_page_tied_to_the_employer_is_a_candidate():
    tie = _link("snowflake-migration", "is-for", "halvard", "t_tie", text="Snowflake migration is for Halvard")
    role = _value("role in snowflake migration", "leading", subject="ines-varga", cid="v_role")
    current = _value("current project", "Snowflake migration", subject="ines-varga", cid="v_current")
    other = _value("role in book club", "organiser", subject="ines-varga", cid="v_other")
    existing = {"ines-varga": [role, current, other], "snowflake-migration": [tie]}
    assert _kinds(existing) == {"v_role": "on-a-thing-of", "v_current": "on-a-thing-of"}
