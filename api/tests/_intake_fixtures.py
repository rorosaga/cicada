"""Synthetic chat exports for the one-intake tests (Track I T2) and the live pass.

Stdlib only, so the orchestrator can write them anywhere without the API
installed:

    api/.venv/bin/python api/tests/_intake_fixtures.py <dir>

Every value is a placeholder (alpha-project, bob-example, example.com); the
shapes are the ones the parsers in ``api/routers/conversations.py`` document,
never copied from a real export. Underscore prefix: pytest never collects it;
sibling tests import it as ``from _intake_fixtures import …`` (the
``_synthetic_bank`` pattern — ``api/tests`` has no ``__init__.py``).
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path


def claude_conversations(n: int = 2, *, grown: bool = False) -> list[dict]:
    out = []
    for i in range(n):
        day = 1 + (i % 27)
        stamp = f"2026-02-{day:02d}T12:00"
        msgs = [
            {"uuid": f"c{i}-m0", "sender": "human", "text": f"How is alpha-project going? ({i})",
             "content": [], "created_at": f"{stamp}:00.000000Z"},
            {"uuid": f"c{i}-m1", "sender": "assistant", "text": "It ships on Friday.",
             "content": [], "created_at": f"{stamp}:05.000000Z"},
        ]
        if grown and i == 0:
            msgs.append({"uuid": "c0-m2", "sender": "human", "text": "Ask bob-example to review it.",
                         "content": [], "created_at": f"{stamp}:40.000000Z"})
        out.append({"uuid": f"conv-{i}", "name": f"alpha-project check-in {i}",
                    "created_at": f"{stamp}:00.000000Z", "updated_at": f"{stamp}:{50 if grown and i == 0 else 30}.000000Z",
                    "chat_messages": msgs})
    return out


def claude_memories() -> list[dict]:
    return [{"conversations_memory": "Works on alpha-project with bob-example.",
             "project_memories": {"p-0123456789": "alpha-project stores vectors in sqlite-vec."},
             "updated_at": "2026-03-01T09:00:00Z"}]


def claude_projects() -> list[dict]:
    return [{"name": "alpha-project", "description": "A synthetic project.", "prompt_template": "",
             "created_at": "2026-01-10T08:00:00Z"},
            {"name": "How to use Claude", "description": "default", "prompt_template": "",
             "created_at": "2026-01-01T00:00:00Z"}]


def chatgpt_conversations(n: int = 2) -> list[dict]:
    out = []
    for i in range(n):
        t0 = 1_700_000_000 + i * 86_400
        out.append({"conversation_id": f"gpt-{i}", "title": f"bob-example notes {i}",
                    "create_time": t0, "update_time": t0 + 60, "mapping": {
                        "a": {"message": {"author": {"role": "user"},
                                          "content": {"parts": [f"Draft a note for bob-example ({i})"]},
                                          "create_time": t0}},
                        "b": {"message": {"author": {"role": "assistant"},
                                          "content": {"parts": ["Here is a short note."]},
                                          "create_time": t0 + 30}}}})
    return out


CHAT_HTML = "<html><body><div id=\"root\"></div><script>var jsonData = [];</script></body></html>"

GEMINI_ENTRIES = (
    ("Summarize my alpha-project notes", "Here is a summary of alpha-project.", "Feb 24, 2026, 12:39:02 PM PST"),
    ("Plan a visit to example.com", None, "Nov 3, 2025, 8:00:00 AM PST"),
)


def gemini_activity_html(entries=GEMINI_ENTRIES, *, product: str = "Gemini Apps", verb: str = "Prompted") -> str:
    """Takeout's documented cell: a header cell naming the product, then a
    content cell holding ``<verb>&nbsp;<prompt><br><date>`` and, for Gemini,
    the reply after the date."""
    cells = []
    for prompt, reply, when in entries:
        tail = f"<br><p>{reply}</p>" if reply else ""
        cells.append(
            '<div class="outer-cell mdl-cell mdl-cell--12-col"><div class="mdl-grid">'
            f'<div class="header-cell mdl-cell mdl-cell--12-col"><p class="mdl-typography--title">{product}<br></p></div>'
            f'<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">{verb}\u00a0{prompt}<br>{when}{tail}</div>'
            '</div></div>')
    return "<!DOCTYPE html><html><body>" + "".join(cells) + "</body></html>"


BOOKMARKS_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE><H1>Bookmarks</H1>
<DL><p><DT><H3>alpha-project</H3><DL><p>
<DT><A HREF="https://example.com/one" ADD_DATE="1700000000">One</A>
<DT><A HREF="https://example.com/two" ADD_DATE="1700000100">Two</A>
</DL><p></DL><p>
"""


def _zip(files: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data if isinstance(data, bytes) else data.encode())
    return buf.getvalue()


def claude_zip(n: int = 2) -> bytes:
    return _zip({"conversations.json": json.dumps(claude_conversations(n)),
                 "memories.json": json.dumps(claude_memories()),
                 "projects.json": json.dumps(claude_projects()),
                 "users.json": json.dumps([{"uuid": "u-1", "full_name": "bob-example",
                                            "email_address": "bob@example.com"}])})


def chatgpt_loose_files(n: int = 2) -> dict[str, bytes | str]:
    return {"conversations.json": json.dumps(chatgpt_conversations(n)),
            "chat.html": CHAT_HTML,
            "user.json": json.dumps({"id": "user-1", "email": "bob@example.com"}),
            "message_feedback.json": "[]",
            "model_comparisons.json": "[]",
            "shared_conversations.json": json.dumps([{"id": "s-1", "conversation_id": "gpt-0", "title": "x"}]),
            "file-0001.png": b"\x89PNG\r\n"}


def chatgpt_zip(n: int = 2) -> bytes:
    return _zip(chatgpt_loose_files(n))


def gemini_takeout_zip() -> bytes:
    return _zip({"Takeout/My Activity/Gemini Apps/MyActivity.html": gemini_activity_html(),
                 "Takeout/My Activity/Gemini Apps/image-1.png": b"\x89PNG\r\n",
                 "Takeout/My Activity/Search/MyActivity.html":
                     gemini_activity_html((("example.com opening hours", None, "Jan 5, 2026, 9:00:00 AM PST"),),
                                          product="Search", verb="Searched for"),
                 "Takeout/archive_browser.html": "<html><body>index</body></html>"})


def write_all(directory: Path) -> list[Path]:
    """The live pass's inputs (§ Verification): three zips, a loose ChatGPT
    folder, a 50-conversation Claude file (the background job), a bookmarks page."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in {"claude-export.zip": claude_zip(),
                       "chatgpt-export.zip": chatgpt_zip(),
                       "gemini-takeout.zip": gemini_takeout_zip(),
                       "claude-50.json": json.dumps(claude_conversations(50)).encode(),
                       "bookmarks.html": BOOKMARKS_HTML.encode()}.items():
        (directory / name).write_bytes(data)
        written.append(directory / name)
    folder = directory / "chatgpt-export"
    folder.mkdir(exist_ok=True)
    for name, data in chatgpt_loose_files().items():
        (folder / name).write_bytes(data if isinstance(data, bytes) else data.encode())
    written.append(folder)
    return written


if __name__ == "__main__":
    for path in write_all(Path(sys.argv[1])):
        print(path)
