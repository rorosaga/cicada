"""ROR-129 — the one-time class read: dry run counts and prices, apply is one commit under the model's name, the person's
word and an existing class are never replaced, a second run asks nothing, and the rule is Stage 1's own words."""
from __future__ import annotations

import json
import re
import subprocess
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.scripts import read_fact_classes
from api.services import claims as claims_mod, engine_select, entity_extractor, fact_class_pass as passes, markdown_parser, providers
from api.services.claims import Claim


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def _fact(cid, predicate="holds", obj="x", **kw):
    base = dict(id=cid, text=f"fact {cid}", subject="owner", predicate=predicate, object=obj, confidence=0.8,
                valid_from="2022-01-01", recorded_at="2026-10-08", source_episodes=["ep_2022-03-01_001"])
    base.update(kw)
    return Claim(**base)


def _page(repo, pid, fm, cs):
    markdown_parser.write(repo / "entities" / f"{pid}.md", fm, claims_mod.write_claims("# P\n", cs))


@pytest.fixture
def bank(tmp_path):
    repo = tmp_path / "bank"
    (repo / "entities").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@cicada.local")
    _git(repo, "config", "user.name", "T")
    _page(repo, "owner", {"name": "Owner", "type": "person", "status": "active", "decay_class": "evergreen"}, [
        _fact("sib", "brother-of", "alex-example"),                       # a model reads this one evergreen
        _fact("tmp", "has-balance-of", "40 EUR"),                          # and this one volatile
        _fact("plain", "likes", "tea"),                                    # active: stored too, so a rerun asks nothing
        _fact("odd", "wibbles", "z"),                                      # the model answers with no class: left classless
        _fact("kept", "brother-of", "kim-example", decay_class="evergreen", class_by="user"),   # the person's keep
        _fact("letfade", "cousin-of", "lee-example", class_by="user"),     # the person said let it fade
        _fact("done", "lives-in", "Lima", decay_class="durable", class_by="model"),   # already has a class
        _fact("closed", "brother-of", "old-example", valid_to="2024-01-01"),           # closed: not a live fact
        _fact("event", "happened", "a trip"),                              # an event, dated history
    ])
    _page(repo, "other", {"name": "Other", "type": "project", "status": "active", "decay_class": "durable"},
          [_fact("o1", "uses", "sqlite", subject="other")])                # a page that always faded by its class
    _page(repo, "a-book", {"name": "A Book", "type": "media", "status": "active", "decay_class": "evergreen"},
          [_fact("m", "highlighted", "a passage", subject="a-book")])      # media never fades
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _settings():
    return Settings(_env_file=None, llm_mode="local")


def _engine(monkeypatch, calls, *, label="local"):
    async def resolve(settings, registry=None, *, user_triggered=True):
        return settings.model_copy(update={"llm_mode": label}), "synthetic"

    monkeypatch.setattr(engine_select, "resolve_settings", resolve)

    def resolve_llm_fn(settings, **kwargs):
        async def call(**kw):
            text = kw["messages"][-1]["content"]
            calls.append(text)
            table = {}
            for number, line in re.findall(r"^(\d+)\. (.*)$", text, re.M):
                table[number] = ("evergreen" if "brother" in line else "volatile" if "balance" in line else
                                 "active" if "likes" in line else "banana")
            return SimpleNamespace(model="synthetic-model", usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
                                   choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"classes": table})))])
        return call

    monkeypatch.setattr(providers, "resolve_llm_fn", resolve_llm_fn)


def _claim(repo, pid, cid):
    page = markdown_parser.parse(repo / "entities" / f"{pid}.md")
    return next(c for c in claims_mod.parse_claims(page.body) if c.id == cid)


def test_the_dry_run_counts_and_prices_and_calls_nothing(bank, monkeypatch):
    calls = []
    _engine(monkeypatch, calls)
    head = _git(bank, "rev-parse", "HEAD")
    result = passes.run(bank, _settings(), mode="dry")
    counts = result.counts()
    assert counts["eligible_pages"] == 1                  # the owner's: evergreen and not media
    assert counts["facts_open"] == 7 and counts["to_read"] == 4
    assert counts["kept_by_person"] == 2 and counts["already_classed"] == 1   # a let-fade is the person's too
    assert counts["calls_estimated"] == 1 and counts["input_tokens_estimated"] > 0 and counts["output_tokens_estimated"] > 0
    assert counts["engine"] == "ollama" and calls == []
    assert _git(bank, "rev-parse", "HEAD") == head and _git(bank, "status", "--porcelain") == ""


def test_apply_writes_every_answer_in_one_commit_under_the_models_name(bank, monkeypatch):
    calls = []
    _engine(monkeypatch, calls)
    result = passes.run(bank, _settings(), mode="apply", sleep_running=lambda: False)
    assert result.committed and result.written == 3 and result.unanswered == 1     # "banana" is no class
    assert result.classes == {"evergreen": 1, "volatile": 1, "active": 1}
    assert (_claim(bank, "owner", "sib").decay_class, _claim(bank, "owner", "sib").class_by) == ("evergreen", "model")
    assert _claim(bank, "owner", "tmp").decay_class == "volatile"
    assert _claim(bank, "owner", "plain").decay_class == "active"                  # stored too: a rerun asks nothing
    assert _claim(bank, "owner", "odd").decay_class is None                        # unanswered: left classless
    message = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: synthetic-model" in message and "maintenance/fact-classes" in message
    assert _git(bank, "show", "--stat", "--format=", "HEAD").count("entities/") == 1   # the owner's page alone
    assert result.input_tokens == 100 and result.output_tokens == 20                # measured, when reported


def test_the_persons_word_and_an_existing_class_are_never_replaced(bank, monkeypatch):
    _engine(monkeypatch, [])
    passes.run(bank, _settings(), mode="apply", sleep_running=lambda: False)
    kept = _claim(bank, "owner", "kept")
    assert (kept.decay_class, kept.class_by) == ("evergreen", "user")
    fade = _claim(bank, "owner", "letfade")
    assert (fade.decay_class, fade.class_by) == (None, "user")                      # still "let it fade"
    done = _claim(bank, "owner", "done")
    assert (done.decay_class, done.class_by) == ("durable", "model")
    for pid, cid in (("other", "o1"), ("a-book", "m"), ("owner", "closed"), ("owner", "event")):
        assert _claim(bank, pid, cid).decay_class is None                           # not eligible: untouched


def test_a_second_run_asks_nothing_new(bank, monkeypatch):
    calls = []
    _engine(monkeypatch, calls)
    passes.run(bank, _settings(), mode="apply", sleep_running=lambda: False)
    before = len(calls)
    again = passes.run(bank, _settings(), mode="dry")
    # only the one the model could not class is left to ask about
    assert again.to_read == 1 and before == 1


def test_it_refuses_before_any_call_while_sleep_runs(bank, monkeypatch):
    calls = []
    _engine(monkeypatch, calls)
    with pytest.raises(passes.SleepRunning):
        passes.run(bank, _settings(), mode="apply", sleep_running=lambda: True)
    assert calls == []


def test_a_page_written_since_the_survey_is_skipped(bank, monkeypatch):
    _engine(monkeypatch, [])
    result = passes.survey(bank)
    asyncio_run = __import__("asyncio").run
    asyncio_run(passes.read(result, _settings()))
    (bank / "entities" / "owner.md").write_text((bank / "entities" / "owner.md").read_text() + "\nnote\n")
    passes.apply(bank, result, sleep_running=lambda: False)
    assert result.written == 0 and result.changed_since_read == 3


def test_a_metered_key_is_refused_unless_agreed(bank, monkeypatch):
    _engine(monkeypatch, [], label="litellm")
    monkeypatch.setattr("api.services.page_article_rebuild._key_present", lambda model: True)
    with pytest.raises(passes.EngineRefused):
        passes.run(bank, _settings(), mode="apply", sleep_running=lambda: False)
    passes.run(bank, _settings(), mode="dry")      # the dry run only reports it


def test_the_script_is_a_dry_run_unless_told(bank, monkeypatch, capsys):
    _engine(monkeypatch, [])
    monkeypatch.setattr(read_fact_classes, "backend_running", lambda: False)
    monkeypatch.setattr("api.config.Settings", lambda *a, **k: _settings())
    assert read_fact_classes.main(["--bank", str(bank)]) == 0
    assert json.loads(capsys.readouterr().out)["to_read"] == 4
    assert _claim(bank, "owner", "sib").decay_class is None
    assert read_fact_classes.main(["--bank", str(bank), "--apply", "--limit", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["written"] == 1


def test_the_class_rule_is_stage_ones_own_words():
    """No second rule: every line of the pass's rule is in the extractor's FACT CLASS paragraph, word for word."""
    prompt = " ".join(entity_extractor.EXTRACTION_PROMPT.split()) if hasattr(entity_extractor, "EXTRACTION_PROMPT") else ""
    if not prompt:
        source = open(entity_extractor.__file__, encoding="utf-8").read()
        prompt = " ".join(source.split())
    for line in passes.RULE.split("\n- "):
        assert " ".join(line.lstrip("- ").split()) in prompt
