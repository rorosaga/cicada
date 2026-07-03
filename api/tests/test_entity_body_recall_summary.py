from api.services.entity_body import summarize_for_recall


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
