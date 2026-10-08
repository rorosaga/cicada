"""`cicada_recall_detail` fits an agent's context (F5, benchmarks/scale).

A 3,500-claim owner page returned 3.1 M characters — past any client's tool-output limit, so the tool failed on the
one page agents ask about most. Over the budget the machine layer is replaced by one line naming its size and the
tools that rank it; a page under the budget is unchanged byte for byte, and a bounded `cicada get` still reads the
whole page in parts.
"""
from __future__ import annotations

from _cli import envelope, run_cli
from _synthetic_bank import _bank, _entity
from api.services import claims, markdown_parser, mcp_tools
from api.services.claims import Claim
from test_cli_unit2 import _env, _work


def _ctx(memory):
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown")


def _big_page(memory, n=2000):
    rows = [Claim(id=f"clm_{i:05d}", text=f"Owner example uses tool-{i} for alpha-project work.", subject="owner-example",
                  predicate="uses", object=f"tool-{i}", valid_from="2026-09-01",
                  valid_to="2026-09-02" if i % 4 == 0 else None) for i in range(n)]
    body = claims.write_claims("## Summary\nThe owner of this synthetic bank.\n\n## Key Facts\n- Works on alpha-project.\n", rows)
    markdown_parser.write(memory / "entities" / "owner-example.md",
                          {"name": "Owner Example", "type": "person", "owner": True}, body)


def test_a_small_page_is_returned_verbatim(tmp_path):
    memory = _bank(tmp_path, git=False)
    _big_page(memory, n=5)
    page = (memory / "entities" / "owner-example.md").read_text(encoding="utf-8")
    assert "```claims" in page
    assert str(mcp_tools.recall_detail(_ctx(memory), "owner-example")) == page


def test_an_over_budget_fence_is_replaced_by_its_size_and_the_ranking_tools(tmp_path):
    memory = _bank(tmp_path, git=False)
    _big_page(memory)
    page = (memory / "entities" / "owner-example.md").read_text(encoding="utf-8")
    assert len(page) > mcp_tools.RECALL_DETAIL_BUDGET
    out = mcp_tools.recall_detail(_ctx(memory), "owner-example")
    assert len(out) < mcp_tools.RECALL_DETAIL_BUDGET
    assert "```claims" not in out and "clm_00001" not in out
    assert "## Summary\nThe owner of this synthetic bank." in out and "owner: true" in out
    assert "1,500 current beliefs (2,000 in all)" in out
    assert "cicada_recall" in out and "cicada_ask" in out
    assert out.data["entity_id"] == "owner-example"


def test_cli_get_whole_is_elided_but_a_bounded_read_sees_every_line(tmp_path):
    memory = _bank(tmp_path, git=False)
    _big_page(memory)
    page = (memory / "entities" / "owner-example.md").read_text(encoding="utf-8")
    whole = envelope(run_cli(["get", "owner-example", "--json"], _env(tmp_path, memory), cwd=_work(tmp_path)))
    assert whole["ok"] is True and "```claims" not in whole["text"] and "--from" in whole["text"]
    total = len(page.splitlines())
    part = envelope(run_cli(["get", "owner-example", "--from", "1", "--count", str(total), "--json"],
                            _env(tmp_path, memory), cwd=_work(tmp_path)))
    assert part["text"] == "\n".join(page.splitlines())
    assert part["data"]["total_lines"] == total
