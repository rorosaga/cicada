"""The History tab pages "Older changes" by the page the route serves (part B, 2026-10-29; #244 before it): the app's
`HistoryPager.pageSize` and `page_history.DEFAULT_LIMIT` are one number."""
from __future__ import annotations

import re
from pathlib import Path

from api.services import page_history

SWIFT = (Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Sources" / "CicadaApp" / "Models"
         / "PageHistory.swift")


def test_the_app_pages_history_by_the_served_page():
    found = re.findall(r"static let pageSize = (\d+)", SWIFT.read_text(encoding="utf-8"))
    assert found == [str(page_history.DEFAULT_LIMIT)]
