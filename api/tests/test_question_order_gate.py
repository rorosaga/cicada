"""Ruling 70, requirement 2: no caller orders or picks a question by its stored ``priority``.

The stored ``priority`` stays on disk and on the wire for an older client, and ``question_order`` falls back to it for
one item it cannot score. Everything else that sorts, picks or breaks a tie between questions uses the score
(``question_order``) or the served ``orderIndex``. This test reads the source of ``api/`` and the app and fails on a new
sort or pick keyed on a question's raw priority, so the order cannot quietly come back.

How a site is found: a line with a sort or pick token (``sort``, ``sorted``, ``max``, ``min``, ``key=``, ``precedes``,
``ordered``, ``tieBreak``) whose STATEMENT (the line and the lines its brackets keep open, at most :data:`SPAN`) names
``priority`` as a field (``.priority``, ``"priority"``) in an inbox or question context (``inbox``, ``question``,
``InboxItem``, ``nudge``, ``fm``, ``item``, ``.meta``). A web-lookup candidate's ``priority`` or an entity page's
"sections in priority order" is no question and is not matched, and no directory is excluded wholesale except the tests
and vendored code themselves.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPAN = 8

SORT = re.compile(r"\bsort\b|\bsorted\b|\bmax\b|\bmin\b|\bkey\s*=|\bprecedes\b|\bordered\b|\btieBreak\b|\breverse\b")
FIELD = re.compile(r"""\.priority\b|["']priority["']|-\s*priority\b|\bpriority\s*[,)]""")
CONTEXT = re.compile(r"inbox|question|InboxItem|nudge|\bfm\b|\bitems?\b|\.meta\b", re.IGNORECASE)

#: ``(path relative to the repo, a substring of the matched line) -> why this is not a sort by raw priority``.
ALLOWED = {
    ("api/services/inbox_service.py", "items.sort("):
        "the key is the item's SCORE (`scores`); `i.priority` is only the value for an item with no score, which "
        "`_item_from_file` always gives one",
    ("api/services/question_order.py", 'return max(0.0, min(1.0, _f(fm.get("priority"), 0.0)))'):
        "the one fallback: an item the formula cannot read scores as its stored priority, clamped to 0..1 (not a sort)",
    ("app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxColumns.swift", "static func precedes("):
        "the older-server fallback, used only when SOME question carries no `orderIndex` (`usesServedOrder`)",
    ("app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxColumns.swift", "static func ordered("):
        "the list's order: the served `orderIndex` when every question has one; its body holds the older-server fallback",
    ("app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxColumns.swift", ".sorted { a, b in"):
        "the same fallback: the served `orderIndex` is compared first, priority only for a list an older server sent",
    ("app/CicadaApp/Sources/CicadaApp/Search/QuickIndex.swift", "tieBreak: served ? -Double(item.orderIndex ?? 0)"):
        "the palette's tie-break is `orderIndex` when every question has one; priority only for an older server",
}


def statement(lines: list[str], start: int) -> list[str]:
    """The line at ``start`` and the lines after it while its brackets stay open (at most ``SPAN``)."""
    out, depth = [], 0
    for ln in lines[start:start + SPAN]:
        out.append(ln)
        depth += sum(ln.count(c) for c in "([{") - sum(ln.count(c) for c in ")]}")
        if depth <= 0:
            break
    return out


def sites(rel: str, text: str, comment: str) -> list[tuple[str, str]]:
    """``(rel, the matched line)`` for every sort or pick in ``text`` keyed on a question's raw priority."""
    lines = text.splitlines()
    found, covered = [], -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if i <= covered or stripped.startswith(comment) or not SORT.search(ln):
            continue
        span = statement(lines, i)
        body = "\n".join(x for x in span if not x.strip().startswith(comment))
        # The context may sit on the declaration just above (`precedes(_ a: InboxItem …`) or in the same statement.
        around = "\n".join(lines[max(0, i - 1):i]) + "\n" + body
        if FIELD.search(body) and CONTEXT.search(around):
            found.append((rel, stripped))
            covered = i + len(span) - 1   # one statement is one site
    return found


def scan() -> list[tuple[str, str]]:
    out = []
    for path in sorted((ROOT / "api").rglob("*.py")):
        parts = path.relative_to(ROOT).parts
        if "tests" in parts or ".venv" in parts or "vendor" in parts:
            continue
        out += sites(str(path.relative_to(ROOT)), path.read_text(encoding="utf-8", errors="replace"), "#")
    for path in sorted((ROOT / "app/CicadaApp/Sources").rglob("*.swift")):
        out += sites(str(path.relative_to(ROOT)), path.read_text(encoding="utf-8", errors="replace"), "//")
    return out


def allowed(rel: str, line: str) -> bool:
    return any(rel == f and frag in line for f, frag in ALLOWED)


def test_no_caller_sorts_or_picks_a_question_by_its_raw_priority():
    stray = [(rel, line) for rel, line in scan() if not allowed(rel, line)]
    assert stray == [], (
        "a question must be ordered by `question_order` (the score) or the served `orderIndex`, never by its stored "
        f"priority (ruling 70). If a site is not about questions, narrow the matcher; if it is a fallback, name it with a reason: {stray}")


def test_every_allowlisted_site_still_exists():
    hits = scan()
    gone = [(f, frag) for f, frag in ALLOWED if not any(rel == f and frag in line for rel, line in hits)]
    assert gone == [], f"an allowlisted site is gone or no longer matches; delete its entry: {gone}"


def test_the_matcher_catches_a_sort_by_priority_and_leaves_other_priorities_alone():
    """The gate proves itself: a sample of each shape that must be caught, and of each that must not be."""
    caught = [
        ("x.py", "    items.sort(key=lambda d: (-float(d.meta.get('priority') or 0.0), d.ref))  # inbox rows", "#"),
        ("x.py", "    ranked = sorted(inbox_items, key=lambda it: -it.priority)", "#"),
        ("x.py", "    items.sort(\n        key=lambda i: (\n            -float(fm['priority']),\n        )\n    )  # question items", "#"),
        ("x.py", "    best = max(questions, key=lambda q: q.get(\"priority\", 0))", "#"),
        ("X.swift", "    let top = inbox.max { $0.priority < $1.priority }", "//"),
        ("X.swift", "    items.sorted { $0.priority > $1.priority }  // InboxItem", "//"),
        ("X.swift", "    static func precedes(_ a: InboxItem, _ b: InboxItem) -> Bool {\n        a.priority > b.priority\n    }", "//"),
        ("X.swift", "    FindRow(title: t, tieBreak: item.priority) // InboxItem", "//"),
    ]
    for rel, text, comment in caught:
        assert sites(rel, text, comment), f"the gate would miss: {text!r}"
    quiet = [
        # a web lookup's candidate and an entity page's sections are not questions
        ("x.py", "    due.sort(key=lambda c: -c.priority)", "#"),
        ("x.py", "    sections = sorted(blocks, key=lambda b: b.priority)  # priority order of page sections", "#"),
        # a comment, a priority that is only stored
        ("x.py", "    # items.sort(key=lambda i: i.priority)  -- the old inbox order", "#"),
        ("x.py", "    item = {'kind': 'removal', 'priority': 0.4, 'status': 'pending'}", "#"),
        ("X.swift", "    // items.sorted { $0.priority > $1.priority }  InboxItem", "//"),
        ("X.swift", "    reminders.sorted { $0.priority < $1.priority }", "//"),
    ]
    for rel, text, comment in quiet:
        assert sites(rel, text, comment) == [], f"the gate would flag an unrelated line: {text!r}"
