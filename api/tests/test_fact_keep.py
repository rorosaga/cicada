"""ROR-129 — "keep this fact": one fact evergreen as the person's word, undoable; faded facts fold, never close."""
from __future__ import annotations

import subprocess

import pytest

from api.services import claims as claims_mod, fact_keep, markdown_parser
from api.services.claims import Claim


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path):
    repo = tmp_path / "bank"
    (repo / "entities").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@cicada.local")
    _git(repo, "config", "user.name", "T")
    cs = [Claim(id="c1", text="Owner holds a degree", subject="owner", predicate="holds", object="degree",
                confidence=0.1, valid_from="2020-01-01", recorded_at="2026-01-01", faded_by_age="2026-02-01",
                decay_class="durable", class_by="model"),
          Claim(id="c2", text="Owner asked about x", subject="owner", predicate="asked", object="x", confidence=0.5)]
    body = claims_mod.write_claims("# Owner\n", cs)
    markdown_parser.write(repo / "entities" / "owner.md", {"name": "Owner", "type": "person", "status": "active"}, body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _claim(bank, cid):
    return next(c for c in claims_mod.parse_claims(markdown_parser.parse(bank / "entities" / "owner.md").body) if c.id == cid)


def test_keep_marks_the_fact_evergreen_as_the_persons_word_and_commits_alone(bank):
    assert claims_mod.is_faded(_claim(bank, "c1"))
    fact_keep.set_keep(bank, "owner", "c1", True, today="2026-11-06")
    kept = _claim(bank, "c1")
    assert (kept.decay_class, kept.class_by, kept.faded_by_age) == ("evergreen", "user", None)
    assert kept.confidence >= fact_keep.KEPT_CONFIDENCE and not claims_mod.is_faded(kept)
    assert _claim(bank, "c2").decay_class is None                      # nothing else touched
    assert "Cicada-Author: user" in _git(bank, "log", "-1", "--format=%B")


def test_unkeep_lets_it_fade_again_and_a_model_cannot_argue(bank):
    from api.services.claim_reconciler import _merge_fact_class
    fact_keep.set_keep(bank, "owner", "c1", True)
    fact_keep.set_keep(bank, "owner", "c1", False)
    c = _claim(bank, "c1")
    assert (c.decay_class, c.class_by) == (None, "user")
    _merge_fact_class(c, Claim(id="c1", text="", decay_class="evergreen", class_by="model"))
    assert c.decay_class is None                                         # the person's word outranks the model's


def test_a_missing_fact_or_page_is_not_found(bank):
    with pytest.raises(fact_keep.FactNotFound):
        fact_keep.set_keep(bank, "owner", "nope", True)
    with pytest.raises(fact_keep.FactNotFound):
        fact_keep.set_keep(bank, "nobody", "c1", True)


def test_the_models_class_replaces_the_models_but_a_blank_one_leaves_it():
    from api.services.claim_reconciler import _merge_fact_class
    c = Claim(id="a", text="", decay_class="active", class_by="model")
    _merge_fact_class(c, Claim(id="a", text="", decay_class="durable", class_by="model"))
    assert c.decay_class == "durable"
    _merge_fact_class(c, Claim(id="a", text=""))
    assert c.decay_class == "durable"


def test_fact_class_resolution_for_every_page_kind():
    from api.models.schemas import DecayClass as D
    from api.services.decay_policy import fact_class, fact_multiplier
    assert fact_class(None, None, D.evergreen, "media") is None              # a media page's facts never fade
    assert fact_class("volatile", "model", D.evergreen, "media") is None
    assert fact_class(None, None, D.evergreen, "person") is D.active         # an evergreen page lends active
    assert fact_class("evergreen", "model", D.active, "person") is None      # a fact's own evergreen, any page
    assert fact_class("durable", "model", D.evergreen, "person") is D.durable
    assert fact_class(None, None, D.volatile, "project") is D.volatile       # no class of its own: the page's
    assert fact_multiplier("bogus", None, D.durable, "concept") == 0.5       # a bad class is dropped
