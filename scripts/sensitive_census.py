"""How often `sensitive_text` would speak up on a real bank (G235): counts only. Writes nothing.

Prints numbers per kind, per source and per speaker, plus the shape of each password hit (quoted, digits, letters only)
so a wrong alarm rate can be judged without reading a word. Never a value, an episode id, a title, a path or a line.
A source outside the known list prints as ``other``, so no folder or file name can reach the output.

Reads the bank's episode files only: no backend, no git, no index, no network, no telemetry.

Usage: api/.venv/bin/python scripts/sensitive_census.py --memory /path/to/bank
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.services import authorship, episode_scrub, evidence, markdown_parser, sensitive_text  # noqa: E402

#: Sources that may print by name: enums the writers themselves use. Anything else is ``other``.
KNOWN_SOURCES = frozenset(episode_scrub.WRITERS) | frozenset({
    "claude-code", "claude_code", "codex", "cursor", "gemini", "gemini-cli", "opencode", "chatgpt", "claude", "claude-web",
    "claude_memory", "mcp", "mcp-remote", "cli", "bookmark", "rss", "whatsapp", "imessage", "messages", "telegram-chats",
    "wispr", "wispr-flow", "hex", "apple-notes", "notes", "folder", "calendar", "reminders", "notion", "readwise",
    "agent-memory", "contacts", "github", "goodreads", "apple-books",
})


def _shape(value: str) -> str:
    digits = any(c.isdigit() for c in value)
    letters = any(c.isalpha() for c in value)
    other = any(not c.isalnum() for c in value)
    if digits and not letters:
        return "digits-only"
    if letters and not digits and not other:
        return "letters-only"
    if letters and not digits:
        return "letters+symbols"
    return "letters+digits"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--memory", required=True, type=Path)
    args = parser.parse_args(argv)
    episodes = args.memory / "episodes"
    if not episodes.is_dir():
        print("no episodes directory")
        return 2

    started = time.perf_counter()
    total = chars = flagged = waiting = waiting_flagged = unreadable = saved = redacted = 0
    by_kind: Counter = Counter()
    conversations_by_kind: Counter = Counter()
    by_source: Counter = Counter()
    by_speaker: Counter = Counter()
    by_session: Counter = Counter()
    shapes: Counter = Counter()
    per_conversation: Counter = Counter()
    waiting_by_source: Counter = Counter()
    agent_only: Counter = Counter()
    distinct: Counter = Counter()
    for path in sorted(episodes.glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 - one unreadable file is one count, never its name
            unreadable += 1
            continue
        fm, body = parsed.frontmatter or {}, parsed.body or ""
        total += 1
        chars += len(body)
        unread = fm.get("processed") is not True
        waiting += int(unread)
        redacted += int(episode_scrub.REDACTED in body)
        override = authorship.of(fm)
        saved += int(override == evidence.SAVE_KIND)
        session = bool(fm.get("harness") or fm.get("capture_kind") == "transcript")
        hits = sensitive_text.find(body, harness=session, override=override, gaps=evidence.gap_ranges(fm, body))
        if not hits:
            continue
        flagged += 1
        waiting_flagged += int(unread)
        source = str(fm.get("source") or "unknown")
        source = source if source in KNOWN_SOURCES else "other"
        for kind in {h.kind for h in hits}:
            conversations_by_kind[kind] += 1
            by_source[(kind, source)] += 1
            by_session[(kind, "session" if session else "not a session")] += 1
            if unread:
                waiting_by_source[(kind, source)] += 1
            of_kind = [h for h in hits if h.kind == kind]
            if all(evidence.speaker_kind(body, h.start) == "assistant" for h in of_kind):
                agent_only[kind] += 1
            # How many different values a conversation repeats: a count, never the values.
            distinct[(kind, min(len({body[h.start:h.end] for h in of_kind}), 5))] += 1
        per_conversation[min(len(hits), 5)] += 1
        for hit in hits:
            by_kind[hit.kind] += 1
            speaker = evidence.speaker_kind(body, hit.start)
            by_speaker[(hit.kind, speaker)] += 1
            if hit.kind == sensitive_text.PASSWORD:
                shapes[_shape(body[hit.start:hit.end])] += 1

    took = time.perf_counter() - started
    print(f"episodes: {total} (unreadable {unreadable}, saved items never read {saved}, waiting for Sleep {waiting})")
    print(f"characters read: {chars}  seconds: {took:.1f}")
    print(f"conversations with a replaced secret already in them: {redacted}")
    print(f"conversations with at least one hit: {flagged} (waiting for Sleep: {waiting_flagged})")
    print(f"hits per conversation (5 = 5 or more): {dict(sorted(per_conversation.items()))}")
    for kind in sensitive_text.KINDS:
        print(f"{kind}: {by_kind[kind]} hits in {conversations_by_kind[kind]} conversations")
    print("by source:")
    for (kind, source), n in sorted(by_source.items()):
        print(f"  {kind} {source}: {n}")
    print("by session or not:")
    for (kind, where), n in sorted(by_session.items()):
        print(f"  {kind} {where}: {n}")
    print("by speaker:")
    for (kind, speaker), n in sorted(by_speaker.items()):
        print(f"  {kind} {speaker}: {n}")
    print(f"password hits by shape: {dict(sorted(shapes.items()))}")
    print("waiting for Sleep, by source:")
    for (kind, source), n in sorted(waiting_by_source.items()):
        print(f"  {kind} {source}: {n}")
    print(f"conversations where only an agent's lines hold this kind: {dict(sorted(agent_only.items()))}")
    print("conversations by how many different values of a kind they hold (5 = 5 or more):")
    for (kind, n_values), n in sorted(distinct.items()):
        print(f"  {kind} {n_values} different: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
