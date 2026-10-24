"""The perf harness's pure parts (``benchmarks/perf``, 2026-10-24): the ledger summary a live run is read with, the
newuser latency table, and how a recall reply and an Ask prompt split into parts. Synthetic rows only."""
from __future__ import annotations

import json

from benchmarks.perf import ledger, newuser_stats, sections


def test_the_ledger_summary_splits_tokens_by_stage_and_cache():
    rows = [
        {"kind": "llm_call", "ts": "2026-10-24T00:00:01Z", "stage": "extraction", "input_tokens": 6000,
         "output_tokens": 1300, "cache_read_tokens": 4900, "cache_write_tokens": 1098, "duration_ms": 5800},
        {"kind": "llm_call", "ts": "2026-10-24T00:00:02Z", "stage": "extraction", "input_tokens": 6200,
         "output_tokens": 1400, "cache_read_tokens": 4900, "cache_write_tokens": 1298, "duration_ms": 6000},
        {"kind": "llm_call", "ts": "2026-10-24T00:00:03Z", "stage": "ask", "input_tokens": 7000, "output_tokens": 800,
         "cache_read_tokens": 1500, "cache_write_tokens": 5500, "duration_ms": 5300},
        {"kind": "read", "ts": "2026-10-24T00:00:04Z", "stage": None},
    ]
    lines = [json.dumps(r) for r in rows] + ["not json", "[1, 2]"]
    out = ledger.summarize(lines)
    first = out["rows"][0]
    assert (first["stage"], first["calls"], first["input_tokens"], first["cache_read"]) == ("extraction", 2, 12200, 9800)
    assert first["uncached"] == 12200 - 9800 - 2396 and first["model_s"] == 11.8
    assert out["total"]["calls"] == 3 and out["total"]["output_tokens"] == 3500
    assert ledger.summarize(lines, since="2026-10-24T00:00:03Z")["total"]["calls"] == 1
    assert "TOTAL" in ledger.render(out)


def test_the_newuser_table_reads_latency_and_size_per_tool(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [
        {"tool": "cicada_ask", "seconds": 5.0, "tokens": 300, "verdict": "correct"},
        {"tool": "cicada_ask", "seconds": 7.0, "tokens": 500, "verdict": "partial"},
        {"tool": "cicada_recall", "seconds": 0.4, "tokens": 3300, "verdict": "correct"},
    ]) + "\n")
    out = newuser_stats.stats(path)
    assert out["score"] == 2.5 and out["cicada_ask"]["p50_s"] == 6.0 and out["cicada_recall"]["max_tokens"] == 3300


def test_a_recall_reply_splits_into_its_parts():
    reply = ("```cicada-hints\n{\"suggested_entities\": []}\n```\n\n### Alpha (project, last said today)\nbody\n\n"
             "### Beta (tool, last said today)\nmore\n\n**Changed recently (last 30 days):**\n- x\n\n"
             "**Related (one hop out):**\n- y\n\n**Related conversation excerpts:**\n- [ep_1] z")
    parts = sections.recall_sections(reply)
    assert set(parts) == {"hints", "entities", "changed", "related_hop", "excerpts"}
    assert sum(parts.values()) + 2 * 5 == len(reply)


def test_an_ask_prompt_splits_claims_from_the_rest():
    prompt = ("QUESTION:\nq\n\nRETRIEVED MEMORY CONTEXT (1 entities):\n\nentity: a\nclaim: {\"id\": 1}\nclaim: {\"id\": 2}\n"
              "background\n\nLINKED PEOPLE (pages linked):\n\nperson\n\nWHAT WAS SAID (word for word):\nline")
    parts = sections.ask_sections(prompt)
    assert parts["claims"] == len('claim: {"id": 1}\n') * 2
    assert set(parts) == {"claims", "entities_other", "linked_people", "what_was_said"}
    assert sum(parts.values()) == len(prompt)
