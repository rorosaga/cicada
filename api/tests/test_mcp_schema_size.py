"""G148: what `tools/list` costs an agent on every request, whatever it asks.

A client that loads every tool schema pays this each time, so the stdio table's size is held: it was 103,111
characters (58 tools, `len(json.dumps(TOOLS))`) before the descriptions were cut to what changes an agent's choice or
its arguments, and 73,956 after. The bound below is that size plus about 5%. A new tool or a longer description has to
fit in it, or shorten something else; raise it only with a reason in the PR, never by habit.
"""
import json

from _stdio_server import stdio_server

AFTER = 73_956
BOUND = int(AFTER * 1.05)


def test_the_tool_list_stays_small():
    size = len(json.dumps(stdio_server().TOOLS))
    assert size <= BOUND, (
        f"tools/list is {size:,} characters, over {BOUND:,} (G148). Cut a description to what changes an agent's "
        "choice or arguments (when to use it, a rail, the shape of a non-obvious argument), not the structure.")

