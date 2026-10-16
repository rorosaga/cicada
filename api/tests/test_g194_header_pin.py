"""G194 D1 — one number for "old material" on both sides: the prompts' `source_dates.OLD_AFTER_DAYS` and the app's
entity-card header (`EntityHeaderWords.oldAfterDays`), which says "last mentioned <Mon YYYY>" past it."""
from __future__ import annotations

import re
from pathlib import Path

from api.services import source_dates

SWIFT = Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Sources" / "CicadaApp" / "Models" / "EntityPresentation.swift"


def test_the_app_header_and_the_prompts_share_the_old_material_threshold():
    found = re.findall(r"static let oldAfterDays = (\d+)", SWIFT.read_text(encoding="utf-8"))
    assert found == [str(source_dates.OLD_AFTER_DAYS)] == ["90"]
