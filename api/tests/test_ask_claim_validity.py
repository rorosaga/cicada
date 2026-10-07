"""G93: Ask's model context cannot present a closed claim as current."""
import json

import pytest

from api.services import ask_service, markdown_parser
from api.services.claims import Claim, parse_claims, write_claims


def _bank(bank, *, current=True, prose="A synthetic project."):
    (bank / "entities").mkdir()
    rows = [Claim(id="clm_old", text="Alpha's calibration method is amber.",
                  subject="alpha-project", predicate="uses", object="amber", object_kind="literal",
                  valid_from="2026-01-01", valid_to="2026-02-01", superseded_by="clm_new")]
    if current:
        rows.append(Claim(id="clm_new", text="Alpha's calibration method is cobalt.",
                          subject="alpha-project", predicate="uses", object="cobalt", object_kind="literal",
                          valid_from="2026-02-01"))
    markdown_parser.write(bank / "entities" / "alpha-project.md", {"name": "Alpha Project"},
                          write_claims(prose, rows))
    return {"score": 1.0, "text": rows[0].text,
            "metadata": {"entity_id": "alpha-project", "claim_id": "clm_old", "valid_from": "2026-01-01"}}


def _answer(bank, hit, query, seen):
    def model(prompt):
        seen.append(prompt)
        # A deterministic grounding seam, not a paid model behavior claim:
        # only a labeled current value may be returned as the current answer.
        present = [json.loads(line.removeprefix("claim: ")) for line in prompt.splitlines()
                   if line.startswith("claim: ")]
        values = [c["text"] for c in present if c["current"]]
        return json.dumps({"answer": " ".join(values), "confidence": 0.8,
                           "used_entities": ["alpha-project"], "gaps": []})
    return ask_service.answer_query(bank, query, retrieve_fn=lambda q, k: [hit], llm_fn=model)


@pytest.mark.parametrize("prose", ["A synthetic project.", "A synthetic project. " * 300,
                                   "Alpha's calibration method is amber."])
def test_ask_now_only_passes_current_claims_with_validity(tmp_path, prose):
    hit = _bank(tmp_path, prose=prose)
    seen = []
    answer = _answer(tmp_path, hit, "What calibration method does alpha-project use now?", seen)
    assert "cobalt" in answer["answer"] and "amber" not in answer["answer"]
    assert "amber" not in seen[0] and "```claims" not in seen[0]
    assert '"valid_from": "2026-02-01"' in seen[0] and '"valid_to": null' in seen[0]
    assert "clm_old" not in str(answer["citations"]), "stale hit must not cite the closed claim as current"


@pytest.mark.parametrize("query", ["What method did alpha-project use previously?",
                                  "What method did alpha-project use last month?",
                                  "What method did alpha-project use as of 2026-01-15?",
                                  "How did alpha-project change from amber to cobalt?",
                                  "What happened in alpha-project?"])
def test_ask_about_the_past_keeps_individually_labeled_history(tmp_path, query):
    hit = _bank(tmp_path)
    seen = []
    _answer(tmp_path, hit, query, seen)
    rows = [json.loads(line.removeprefix("claim: ")) for line in seen[0].splitlines()
            if line.startswith("claim: ")]
    old = next(c for c in rows if c["id"] == "clm_old")
    assert old["current"] is False and old["valid_from"] == "2026-01-01"
    assert old["valid_to"] == "2026-02-01" and old["superseded_by"] == "clm_new"
    assert "history" in old["validity"]
    assert "closed claims" in ask_service.ASK_SYSTEM_PROMPT.lower()


def test_ask_now_with_only_history_reports_a_gap_without_a_model_call(tmp_path):
    hit = _bank(tmp_path, current=False)
    seen = []
    result = _answer(tmp_path, hit, "alpha-project", seen)
    assert seen == [] and result["citations"] == [] and result["gaps"]


def test_missing_claim_page_never_revives_indexed_text(tmp_path):
    hit = _bank(tmp_path)
    (tmp_path / "entities" / "alpha-project.md").unlink()
    seen = []
    result = _answer(tmp_path, hit, "calibration now", seen)
    assert seen == [] and result["citations"] == []


def test_history_cannot_be_crowded_out_by_a_long_current_claim_list(tmp_path):
    hit = _bank(tmp_path)
    page = tmp_path / "entities" / "alpha-project.md"
    parsed = markdown_parser.parse(page)
    rows = parse_claims(parsed.body)
    rows += [Claim(id=f"clm_filler_{i}", text="An unrelated synthetic method " * 20,
                   subject="alpha-project", valid_from="2026-02-01") for i in range(15)]
    markdown_parser.write(page, parsed.frontmatter, write_claims("A project", rows))
    seen = []
    _answer(tmp_path, hit, "What method did alpha-project use as of 2026-01-15?", seen)
    assert '"id": "clm_old"' in seen[0] and '"id": "clm_new"' in seen[0]


def test_default_history_retrieval_finds_a_bank_with_only_closed_claims(tmp_path):
    import numpy as np
    from api.services import search_index

    _bank(tmp_path, current=False)
    search_index.rebuild(tmp_path)
    retrieve = ask_service.build_claim_first_retrieve_fn(
        tmp_path, embed_fn=lambda texts, **kw: np.ones((len(texts), 2), dtype=np.float32))
    hits = retrieve("What method did alpha-project use previously?", 6)
    assert hits and hits[0]["metadata"]["entity_id"] == "alpha-project"
    assert hits[0]["metadata"]["claim_id"] == "clm_old"
