"""#244 — the app pages "Older changes" from the end of the window `GET /entities/{id}` serves: the app's
`HistoryPaging.window` and `git_service.MAX_PROVENANCE_COMMITS` are one number."""
from __future__ import annotations

import re
from pathlib import Path

from api.services import git_service

SWIFT = (Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Sources" / "CicadaApp" / "Views" / "Graph"
         / "HistoryTabState.swift")


def test_the_app_pages_history_from_the_served_window():
    found = re.findall(r"static let window = (\d+)", SWIFT.read_text(encoding="utf-8"))
    assert found == [str(git_service.MAX_PROVENANCE_COMMITS)]
