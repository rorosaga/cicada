from api.services.entity_body import summarize_for_recall
from api.services import claims


def test_key_facts_always_survive_truncation():
    body = (
        "## Summary\n" + ("summary line. " * 200) + "\n\n"
        "## Key Facts\n- His paper's results: 19% EM, 25% F1\n- Founder of Supahost\n\n"
        "## History\n- 2025-04-08: shared paper\n"
    )
    out = summarize_for_recall(body, max_chars=600)
    assert "19% EM, 25% F1" in out           # Key Facts preserved despite tiny budget
    assert "## Summary" in out


def test_returns_full_body_when_under_budget():
    body = "## Summary\nshort\n\n## Key Facts\n- a fact\n"
    out = summarize_for_recall(body, max_chars=10000).strip()
    assert out.startswith("## Summary")
    assert "- a fact" in out  # Verify Key Facts content survives under generous budget


def test_claims_block_not_leaked_into_summary():
    """Verify that claims YAML block is stripped before summarizing."""
    body = "## Summary\nEntity summary.\n\n## Key Facts\n- a fact\n"
    # Append a claims block with internal YAML metadata.
    claim = claims.Claim(
        id="clm_1",
        text="secret claim",
        source_trust="agent_extracted",
        observer="agent",
    )
    body = claims.write_claims(body, [claim])

    out = summarize_for_recall(body)

    # Key Facts must survive.
    assert "- a fact" in out
    # Claims YAML metadata must NOT appear.
    assert "clm_1" not in out
    assert "source_trust" not in out
    assert "observer:" not in out
    assert "```claims" not in out
