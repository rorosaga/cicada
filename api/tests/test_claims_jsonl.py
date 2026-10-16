"""The ```claims fence is JSON Lines: one claim per line (DECIDE-1, owner 2026-10-08; benchmarks/scale).

PyYAML builds every node in Python even on the C loader: ~150 µs a claim, 0.5 s for a 3,500-claim page and ~3 s for
a 2,000-page bank's claims — paid by every reader, several times a Sleep batch. A JSON line is ~3 µs. These tests
pin what the switch must not change: a legacy YAML fence reads exactly as before (dual reader), a claim survives
YAML → JSON Lines → re-render byte for byte (no re-diff), every line of a page stays one line, and the prose an
evidence span points into is the same text.
"""
from __future__ import annotations

import json
import random
import string

import pytest
import yaml

from api.services import claims, evidence
from api.services.claims import Claim, Evidence


def legacy_fence(rows: list[Claim]) -> str:
    """The YAML fence `write_claims` wrote before the switch (ef4d571c `_render_claims_block`)."""
    payload = yaml.dump([c.to_dict() for c in rows], default_flow_style=False, sort_keys=False,
                        allow_unicode=True).strip()
    return f"```claims\n{payload if payload and payload != '[]' else '[]'}\n```"


PROSE = "## Summary\nAlpha-project is a synthetic fixture.\n\n## Key Facts\n- It uses sqlite-vec.\n"


def _rich() -> list[Claim]:
    return [
        Claim(id="clm_2026-10-08_001", text="Alpha-project uses sqlite-vec.", subject="alpha-project",
              predicate="uses", object="sqlite-vec", valid_from="2026-10-01", recorded_at="2026-10-08",
              source_episodes=["ep_2026-10-01_001"], authored_by="model-a", origin="claude-code",
              session_id="ses_a", session_ids=["ses_a", "ses_b"], decayed_through="2026-10-08",
              evidence=[Evidence(episode="ep_2026-10-01_001", start=12, end=40, kind="user", hash="abcdef012345"),
                        Evidence()]),
        Claim(id="clm_2", text="Ünïcødé — “quotes” 'single' \\ backslash\ttab\nnewline ``` fence", subject="alpha-project",
              predicate="notes", object="free text: a: b # not a comment", object_kind="literal", confidence=0.25,
              valid_to="2026-10-05", superseded_by="clm_3", expected_end="2026-12-31"),
        Claim(id="clm_3", text="line separator para\x85nel\x0bvt\x0cff\x1cfs", subject="alpha-project",
              predicate="happened", status="done", date_basis="stated", recorded_ts="2026-10-08T10:00:00Z",
              participants=[{"role": "with", "surface": "Bob Example", "entity": "bob-example"}]),
        Claim(id="clm_4", text="", subject="alpha-project", predicate="milestone", target="2026-11-01",
              status="planned", recovered_from="0" * 40, recovered_by="cicada"),
    ]


def test_write_claims_emits_one_json_line_per_claim_and_reads_back_equal():
    rows = _rich()
    page = claims.write_claims(PROSE, rows)
    fence = page[page.index("```claims"):]
    lines = fence.split("\n")
    assert lines[0] == "```claims" and lines[len(rows) + 1] == "```"
    for line, row in zip(lines[1:len(rows) + 1], rows):
        assert json.loads(line) == row.to_dict()
    assert claims.parse_claims(page, strict=True) == rows
    # Every line of the page is one line, whatever splits lines (the CLI's `get --from`, editors, git).
    assert len(page.splitlines()) == len(page.split("\n")) - (1 if page.endswith("\n") else 0)


def test_an_empty_fence_is_unchanged():
    assert claims._render_claims_block([]) == "```claims\n[]\n```"
    assert claims.parse_claims(claims.write_claims(PROSE, []), strict=True) == []


def test_a_legacy_yaml_fence_reads_exactly_as_before():
    rows = _rich()
    legacy = f"{PROSE}\n{legacy_fence(rows)}\n"
    assert claims.parse_claims(legacy, strict=True) == rows
    assert claims.fence_state(legacy) == claims.FENCE_OK
    assert claims.raw_claim_entries(legacy) == [r.to_dict() for r in rows]


def test_yaml_to_jsonl_to_rerender_never_rediffs_a_claim():
    legacy = f"{PROSE}\n{legacy_fence(_rich())}\n"
    once = claims.write_claims(legacy, claims.parse_claims(legacy, strict=True))
    assert claims.strip_claims_block(once) == claims.strip_claims_block(legacy)
    twice = claims.write_claims(once, claims.parse_claims(once, strict=True))
    assert twice == once
    assert claims.parse_claims(once, strict=True) == claims.parse_claims(legacy, strict=True)


def test_evidence_spans_point_into_the_same_prose():
    rows = _rich()
    yaml_page = f"{PROSE}\n{legacy_fence(rows)}\n"
    json_page = claims.write_claims(PROSE, rows)
    assert claims.strip_claims_block(yaml_page) == claims.strip_claims_block(json_page)
    assert evidence.body_hash(claims.strip_claims_block(yaml_page)) == evidence.body_hash(
        claims.strip_claims_block(json_page))


def test_malformed_and_mixed_fences_are_refused_by_strict_readers():
    good = claims.write_claims(PROSE, _rich()[:2])
    broken = good.replace('"id": "clm_2"', '"id": "clm_2', 1)
    mixed = good.replace("\n```\n", "\n- id: yaml-entry\n```\n", 1)
    not_mapping = good.replace("\n```\n", "\n[1, 2]\n```\n", 1)
    for page in (broken, mixed, not_mapping):
        with pytest.raises(claims.MalformedClaimsBlockError):
            claims.parse_claims(page, strict=True)
        assert claims.fence_state(page) == claims.FENCE_UNREADABLE
    assert claims.loose_claim_entries(broken) is None
    assert claims.parse_claims(not_mapping) == _rich()[:2]          # lenient: the bad entry is skipped, logged


def test_append_keeps_every_existing_byte_and_writes_json_lines():
    page = claims.write_claims(PROSE, _rich()[:2])
    new = {"id": "clm_new", "text": "Recovered.", "subject": "alpha-project", "valid_to": "2026-10-08",
           "future_field": {"kept": True}}
    out = claims.append_claim_entries(page, [new])
    assert out.startswith(page[:page.rindex("```")])
    assert out.split("\n")[-3] == claims._jsonl_line(new)
    assert claims.raw_claim_entries(out)[-1] == new
    fresh = claims.append_claim_entries(PROSE, [new])
    assert claims.raw_claim_entries(fresh) == [new] and claims._jsonl_line(new) in fresh


def test_append_to_a_legacy_yaml_fence_keeps_its_form_until_migration():
    legacy = f"{PROSE}\n{legacy_fence(_rich()[:1])}\n"
    out = claims.append_claim_entries(legacy, [{"id": "clm_new", "text": "Recovered."}])
    assert out.startswith(legacy[:legacy.rindex("```")])
    assert [e["id"] for e in claims.raw_claim_entries(out)] == ["clm_2026-10-08_001", "clm_new"]


def _fuzz_text(rng: random.Random) -> str:
    alphabet = string.printable + "éñ漢字🙂—…“”‘’   \u0085﻿:#-?&*!|>'\"%@`{}[],"
    specials = ["", " ", "null", "~", "yes", "no", "true", "1e3", "0x1F", "2026-10-08", "12:30", "- x", "a: b",
                "#c", "x" * 300, " lead", "trail ", "multi\nline", "```claims", "```", "\\back", "*a", "&a", "!t"]
    if rng.random() < 0.3:
        return rng.choice(specials)
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 200)))


def test_fuzz_yaml_and_jsonl_read_the_same_claims_and_jsonl_never_rediffs():
    rng = random.Random(20261008)
    for case in range(400):
        rows = [Claim(id=f"clm_{case}_{i}", text=_fuzz_text(rng), subject=_fuzz_text(rng)[:40],
                      predicate=_fuzz_text(rng)[:30], object=_fuzz_text(rng), context=_fuzz_text(rng)[:20],
                      confidence=rng.choice([0.0, 0.5, 1.0, 0.123456789, 1e-7]),
                      valid_from=rng.choice([None, "2026-10-08", _fuzz_text(rng)[:12]]),
                      source_episodes=[_fuzz_text(rng)[:20] for _ in range(rng.randint(0, 3))],
                      session_ids=[s for s in (_fuzz_text(rng)[:12] for _ in range(rng.randint(0, 2))) if s.strip()],
                      evidence=[Evidence(episode=_fuzz_text(rng)[:20], start=1, end=9, kind="user",
                                         hash=_fuzz_text(rng)[:12])] if rng.random() < 0.5 else [])
                for i in range(rng.randint(0, 4))]
        legacy = f"{PROSE}\n{legacy_fence(rows)}\n"
        from_yaml = claims.parse_claims(legacy, strict=True)
        page = claims.write_claims(legacy, from_yaml)
        assert claims.parse_claims(page, strict=True) == from_yaml, case
        assert claims.write_claims(page, claims.parse_claims(page, strict=True)) == page, case
        assert claims.strip_claims_block(page) == claims.strip_claims_block(legacy), case
        fence = page[page.index("```claims"):]
        assert len(fence.splitlines()) == max(len(rows), 1) + 2, case
