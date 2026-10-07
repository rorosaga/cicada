"""G110 A2: immutable-first-text paging through the real captured source."""
import re
from pathlib import Path

import pytest

from api.services import continuity, handshake
from api.tests.test_continuity_on_demand import A, REPORT, _stop, env  # noqa: F401

FIRST = "".join(f"word-{i:04d} " for i in range(1600))[:-1] + "."
CURSOR = re.compile(r'before="(first:\d+@[0-9a-f]{12})"')


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_all_16k_initial_characters_are_reachable_and_append_does_not_stale_cursor(env, harness):
    assert len(FIRST) == 16000
    result = _stop(env, harness, A, [("user", FIRST), ("assistant", REPORT)])
    args = {"session": result["episodeId"]}
    out = env["server"].handle_tool("cicada_continue", args)
    assert FIRST[:2000] in out and REPORT in out and len(out) <= continuity.REPLY_CAP
    read = 2000
    cursor = CURSOR.search(out)
    assert cursor is not None
    _stop(env, harness, A, [("user", FIRST), ("assistant", REPORT), ("user", "new question"), ("assistant", "new result")])
    while cursor:
        token = cursor.group(1)
        assert int(token.split(":")[1].split("@")[0]) == read
        out = env["server"].handle_tool("cicada_continue", {**args, "before": token})
        assert FIRST[read:read + 2000] in out and "initial request changed" not in out.lower()
        assert len(out) <= continuity.REPLY_CAP and "quoted as history" in out
        read += min(2000, len(FIRST) - read)
        cursor = CURSOR.search(out)
    assert read == len(FIRST)
    # A rewritten initial message restarts safely instead of splicing the old continuation.
    _stop(env, harness, A, [("user", "changed " + FIRST), ("assistant", REPORT)])
    changed = env["server"].handle_tool("cicada_continue", {**args, "before": token})
    assert "initial request changed" in changed.lower() and "changed " + FIRST[:100] in changed
    assert len(changed) <= continuity.REPLY_CAP


@pytest.mark.parametrize("variant", handshake.VARIANTS)
def test_optional_state_guidance_fits_primers_and_matches_the_installed_skill_source(variant):
    text = handshake.build(None, variant=variant, bank="alpha")
    assert "brief `State:`" in text and "optional" in text.lower()
    assert text.count("brief `State:`") == 1 and len(text) // 4 <= handshake.MAX_TOKENS
    assert "brief `State:`" in Path("SKILL.md").read_text()


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_initial_page_bad_offsets_restart_and_calls_obey_existing_schema(env, harness):
    from api.services import evidence
    from api.tests.test_handshake_r12 import _check

    result = _stop(env, harness, A, [("user", FIRST), ("assistant", REPORT)])
    schemas = {t["name"]: set(t["inputSchema"].get("properties", {})) for t in env["server"].TOOLS}
    for token in ("first:bad", f"first:16000@{evidence.body_hash(FIRST)}", f"first:999999@{evidence.body_hash(FIRST)}"):
        text = env["server"].handle_tool("cicada_continue", {"session": result["episodeId"], "before": token})
        assert "restarting its first page" in text and FIRST[:2000] in text and len(text) <= continuity.REPLY_CAP
        _check(text, schemas)
