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
