"""`cicada_recall_detail` reads an over-budget page in parts, never losing any of it (F5, fix round 1).

A 3,500-claim owner page returned 3.1 M characters — past any client's tool-output limit (24,000 on the remote
connector), so the tool failed on the page agents ask about most. Eliding the claims fence (F5's first form) fixed
the size but left an agent no way to a claim's id (needed to withdraw it), its evidence, or older history (review
round 1). Now a page over the caller's budget comes back as consecutive line ranges, each ending with the exact call
for the next one: every byte stays reachable through the same tool, under the default remote scopes.
"""
from __future__ import annotations

import re

from _cli import envelope, run_cli
from _synthetic_bank import _bank
from api.remote import catalog
from api.services import agentic_write, claims, markdown_parser, mcp_tools
from api.services.claims import Claim, Evidence
from test_cli_unit2 import _env, _work

TARGET = "clm_withdraw_target"
ANCIENT = "Alpha project formerly supported the garnet protocol."


def _ctx(memory, **kw):
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown", **kw)


def _remote_ctx(memory):
    return _ctx(memory, connector_id="synthetic", available=catalog.tool_names_for(catalog.DEFAULT_SCOPES),
                raw_excerpts=False)


def _big_page(memory, n=400):
    rows = [Claim(id=TARGET, text="Owner example uses the cobalt protocol.", subject="owner-example",
                  predicate="uses", object="cobalt-protocol", authored_by="codex-remote", valid_from="2026-01-01",
                  evidence=[Evidence(episode="ep_2026-01-01_001", start=3, end=30, kind="user", hash="abcdef012345")])]
    rows += [Claim(id=f"clm_{i:05d}", text=f"Owner example uses tool-{i} for alpha-project work.",
                   subject="owner-example", predicate="uses", object=f"tool-{i}", valid_from="2026-09-01",
                   valid_to="2026-09-02" if i % 4 == 0 else None) for i in range(n)]
    rows.append(Claim(id="clm_ancient", text=ANCIENT, subject="owner-example", predicate="supports",
                      object="garnet-protocol", valid_from="2020-01-01", valid_to="2020-02-01"))
    body = claims.write_claims("## Summary\nThe owner of this synthetic bank.\n", rows)
    markdown_parser.write(memory / "entities" / "owner-example.md",
                          {"name": "Owner Example", "type": "person", "owner": True}, body)
    return (memory / "entities" / "owner-example.md").read_text(encoding="utf-8")


_NEXT = re.compile(r"cicada_recall_detail\(entity_id=\"owner-example\", start=(\d+)\)")


def _read_all(ctx, budget):
    """Follow the continuation calls the replies name, as an agent would."""
    parts, start, calls = [], None, 0
    while True:
        out = str(mcp_tools.recall_detail(ctx, "owner-example", start=start))
        calls += 1
        assert len(out) <= budget + 400, len(out)
        body, sep, footer = out.rpartition("\n— lines ")
        assert sep, out[-300:]
        parts.append(body)
        match = _NEXT.search(footer)
        if match is None:
            assert "end of the page" in footer
            return "".join(parts), calls
        start = int(match.group(1))


def test_a_page_under_budget_is_returned_verbatim(tmp_path):
    memory = _bank(tmp_path, git=False)
    page = _big_page(memory, n=5)
    assert str(mcp_tools.recall_detail(_ctx(memory), "owner-example")) == page


def test_an_over_budget_page_is_read_whole_in_parts_through_the_tool(tmp_path):
    memory = _bank(tmp_path, git=False)
    page = _big_page(memory)
    assert len(page) > mcp_tools.RECALL_DETAIL_BUDGET
    whole, calls = _read_all(_ctx(memory), mcp_tools.RECALL_DETAIL_BUDGET)
    assert calls >= 2 and whole == page
    assert TARGET in whole and ANCIENT in whole and "abcdef012345" in whole


def test_a_remote_reader_with_default_scopes_reaches_every_claim_id_and_old_history(tmp_path):
    memory = _bank(tmp_path, git=False)
    page = _big_page(memory, n=200)
    ctx = _remote_ctx(memory)
    assert ctx.can("cicada_recall_detail") and not ctx.can("cicada_ask")
    whole, calls = _read_all(ctx, mcp_tools.REMOTE_DETAIL_BUDGET)
    assert whole == page and calls >= 2
    assert mcp_tools.REMOTE_DETAIL_BUDGET + 400 < 24_000      # under the remote connector's result cap
    # The id an agent needs to withdraw its own claim, read back in a later session:
    assert TARGET in whole
    assert agentic_write.retract_claim(memory, "owner-example", TARGET, reason="Synthetic correction.",
                                       author="codex-remote")["action"] == "retracted"


def test_a_start_past_the_end_says_so(tmp_path):
    memory = _bank(tmp_path, git=False)
    _big_page(memory)
    out = mcp_tools.recall_detail(_ctx(memory), "owner-example", start=10**6)
    assert "has" in out and "lines" in out and out.code == "out_of_range"


def test_cli_get_pages_with_start_and_a_bounded_read_still_slices_the_whole_page(tmp_path):
    memory = _bank(tmp_path, git=False)
    page = _big_page(memory)
    first = envelope(run_cli(["get", "owner-example", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path)))
    assert first["ok"] is True and "cicada get owner-example --start " in first["text"]
    total = len(page.splitlines())
    part = envelope(run_cli(["get", "owner-example", "--from", "1", "--count", str(total), "--json"],
                            _env(tmp_path, memory), cwd=_work(tmp_path)))
    assert part["text"] == "\n".join(page.splitlines())
