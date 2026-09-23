"""R-PJB17: the one table PJ-5's Swift twin will read too."""
import json
from pathlib import Path

import pytest

from api.services import project_state

CASES = json.loads((Path(__file__).parent / "fixtures" / "timeline_state.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_timeline_state_matches_the_shared_fixture(case):
    assert project_state.timeline_state(case["input"], case["today"]) == case["expected"]


def test_quiet_threshold_rounds_half_up_like_swift():
    assert project_state.quiet_threshold(10.25) == 21 and project_state.quiet_threshold(10.5) == 21
    assert project_state.quiet_threshold(3.0) == 14 and project_state.quiet_threshold(None) == 14
