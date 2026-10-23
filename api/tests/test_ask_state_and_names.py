"""Ask after the 2026-10-23 live test: the newest fact on a busy page reaches the model, a claim whose object is a
whole sentence never empties retrieval, and a page the question names is retrieved.

Synthetic pages with placeholder names only. Hermetic: a fake ``embed_fn`` (never a model) and an ``llm_fn`` that
records the prompt it was given.
"""

from __future__ import annotations

import json

import numpy as np

from api.services import ask_service, markdown_parser, text_fold
from api.services.claims import Claim, write_claims
from api.services.id_utils import is_page, resolve_entity_file, resolve_entity_id
from api.services.vector_index import SqliteVecIndexer

_VOCAB = ["release", "version", "portfolio", "alpha", "tool", "design"]


def _embed(texts, *, is_query: bool = False):
    rows = []
    for text in texts:
        low = text.lower()
        vec = np.array([float(low.count(w)) for w in _VOCAB], dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        rows.append(vec / norm if norm > 0 else np.ones(len(_VOCAB), dtype=np.float32) / np.sqrt(len(_VOCAB)))
    return np.vstack(rows).astype(np.float32)


def _claim(cid, subject, text, **kw):
    kw.setdefault("observer", "agent")
    kw.setdefault("context", "general")
    kw.setdefault("valid_from", "2026-01-01")
    return Claim(id=cid, text=text, subject=subject, **kw)


def _page(bank, stem, name, claims, prose="A page.", **fm):
    (bank / "entities").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(bank / "entities" / f"{stem}.md",
                          {"name": name, "type": fm.pop("type", "project"), "status": "active", **fm},
                          write_claims(prose, claims))


def _recording_llm(seen: list[str]):
    def call(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps({"answer": "ok", "confidence": 0.5, "used_entities": [], "gaps": []})
    return call


def _busy_release_page(bank):
    """Forty older current claims that share both of the question's words, then the newest fact in other words."""
    claims = [_claim(f"clm_2026-09-{i + 1:02d}_old{i:02d}", "alpha-project",
                     f"Alpha Project latest release note {i}: build {i} of the 0.3 line was the latest release then.",
                     predicate=f"latest-release-note-{i}", object=f"0.3.{i}", object_kind="literal",
                     valid_from=f"2026-09-{(i % 28) + 1:02d}")
              for i in range(40)]
    claims.append(_claim("clm_2026-10-21_new", "alpha-project", "Alpha Project released version: 0.6.0",
                         predicate="value-of-released-version", object="0.6.0", object_kind="literal",
                         valid_from="2026-10-21"))
    _page(bank, "alpha-project", "Alpha Project", claims)


def _hit(eid):
    return {"score": 1.0, "text": "", "metadata": {"entity_id": eid, "entity_name": eid, "type": "project",
                                                   "status": "active", "file_path": ""}}


def test_a_state_question_offers_the_newest_claim_on_a_busy_page(tmp_path):
    _busy_release_page(tmp_path)
    seen: list[str] = []
    ask_service.answer_query(tmp_path, "What is the latest release of Alpha Project?", source_words=False,
                             retrieve_fn=lambda q, k: [_hit("alpha-project")], llm_fn=_recording_llm(seen),
                             search_fn=lambda *_: None)
    assert seen, "the model was asked"
    assert "0.6.0" in seen[0], "the newest release claim must reach the model past the prompt budget"


def test_a_question_without_a_past_cue_still_mixes_in_the_newest(tmp_path):
    _busy_release_page(tmp_path)
    seen: list[str] = []
    ask_service.answer_query(tmp_path, "Which release is Alpha Project on?", source_words=False,
                             retrieve_fn=lambda q, k: [_hit("alpha-project")], llm_fn=_recording_llm(seen),
                             search_fn=lambda *_: None)
    assert "0.6.0" in seen[0]


def test_rank_claims_orders_by_words_then_recency_and_never_by_confidence():
    old = _claim("a", "s", "release note", valid_from="2026-01-01", confidence=0.99)
    new = _claim("b", "s", "released version", valid_from="2026-10-01", confidence=0.01)
    off = _claim("c", "s", "unrelated", valid_from="2026-10-05")
    terms = {text_fold.stem("release"), "note"}
    # A past question keeps the word order (two shared words beat one), newest first among equals.
    assert [c.id for c in ask_service._rank_claims([old, new, off], terms, state=False, latest=False)] == \
        ["a", "b", "c"]
    # "latest": the newest claim sharing a word leads, whatever its confidence.
    assert [c.id for c in ask_service._rank_claims([old, new, off], terms, state=True, latest=True)][0] == "b"
    # A malformed valid_from is no day; the id's day stands in.
    odd = _claim("clm_2026-10-09_x", "s", "release", valid_from="ep_2026-10")
    assert ask_service._claim_day(odd) == "2026-10-09"


def test_stem_meets_release_and_released():
    forms = {text_fold.stem(w) for w in ("release", "released", "releases", "releasing")}
    assert len(forms) == 1
    assert text_fold.stem("targeted") == text_fold.stem("targets") == "target"
    assert text_fold.stem("time") == "time"


def test_a_sentence_never_resolves_as_a_page_and_never_raises(tmp_path):
    (tmp_path / "entities").mkdir()
    sentence = "A personal portfolio covering studies, research, past roles and side projects. " * 6
    assert resolve_entity_file(tmp_path, sentence) is None
    assert resolve_entity_id(tmp_path / "entities", sentence, {}) is None
    assert is_page(tmp_path / "entities" / f"{'x' * 300}.md") is False
    assert ask_service._load_entity(tmp_path, sentence) is None


def test_a_claim_object_that_is_a_sentence_never_empties_retrieval(tmp_path):
    sentence = ("Bob Example's personal portfolio, covering computer science studies, research on vision models, "
                "past roles in agentic systems and imaging, and side projects such as a design tool. " * 3)
    _page(tmp_path, "bob-example", "Bob Example",
          [_claim("clm_p", "bob-example", "Bob Example authored a portfolio design tool.", predicate="authored",
                  object=sentence, object_kind="entity")], type="person")
    indexer = SqliteVecIndexer(tmp_path, embed_fn=_embed)
    indexer.index_claims()
    indexer.index_entities()
    hits = ask_service.build_claim_first_retrieve_fn(tmp_path, embed_fn=_embed)("portfolio design tool", 6)
    assert "bob-example" in {h["metadata"]["entity_id"] for h in hits}


def test_a_page_the_question_names_is_retrieved_first(tmp_path):
    # The vectors rank the other page's claim nearest; the question names Bob Example in full.
    _page(tmp_path, "bob-example", "Bob Example", [_claim("clm_b", "bob-example", "Bob Example lives in a city.")],
          type="person", aliases=["Bobby Example"])
    _page(tmp_path, "alpha-project", "Alpha Project",
          [_claim("clm_a", "alpha-project", "Alpha Project portfolio design tool release version.")])
    indexer = SqliteVecIndexer(tmp_path, embed_fn=_embed)
    indexer.index_claims()
    indexer.index_entities()
    retrieve = ask_service.build_claim_first_retrieve_fn(tmp_path, embed_fn=_embed)
    hits = retrieve("Who is Bob-Example? portfolio design tool", 6)
    assert hits[0]["metadata"]["entity_id"] == "bob-example"
    # A word shared with a title is not a name: "Bob" alone names neither page in full.
    assert "bob-example" not in [h["metadata"]["entity_id"] for h in ask_service._named_pages(tmp_path, "Bob?")]


def test_without_a_search_model_a_named_page_still_answers(tmp_path):
    """A words-only install (the search model not downloaded yet): the vector legs raise, the name leg still finds the
    page the question names (the 2026-10-23 scratch run answered "nothing matches" before this)."""
    _page(tmp_path, "alpha-project", "alpha-project",
          [_claim("clm_a", "alpha-project", "alpha-project released version 0.6.0")])

    def no_model(texts, *, is_query: bool = False):
        raise OSError("embedder: model_missing")

    hits = ask_service.build_claim_first_retrieve_fn(tmp_path, embed_fn=no_model)(
        "What is the latest release of alpha-project?", 6)
    assert [h["metadata"]["entity_id"] for h in hits] == ["alpha-project"]
