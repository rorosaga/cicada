"""G180 parity — the entity card's bands are computed behind the API, so a browser client never re-derives them.

`entity_bands` and the app's `EntityHeaderWords` / `FadeWords` read one table (`fixtures/entity_bands.json`); the
words a person reads stay in each client's copy, the bands come from the backend."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from api.services import entity_bands, source_dates

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "entity_bands.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("value,band", FIXTURE["confidence"])
def test_confidence_band(value, band):
    assert entity_bands.confidence_band(value) == band


@pytest.mark.parametrize("rate,pace", FIXTURE["fadePace"])
def test_fade_pace(rate, pace):
    assert entity_bands.fade_pace(rate) == pace


@pytest.mark.parametrize("raw,expected", FIXTURE["lastMentioned"]["cases"])
def test_last_mentioned_day(raw, expected):
    today = date.fromisoformat(FIXTURE["lastMentioned"]["today"])
    got = entity_bands.last_mentioned(raw, today)
    assert (got.isoformat() if got else None) == expected


def test_the_old_threshold_is_the_one_prose_uses():
    assert entity_bands.OLD_AFTER_DAYS is source_dates.OLD_AFTER_DAYS


def test_a_nan_confidence_is_doubtful():
    assert entity_bands.confidence_band(float("nan")) == "doubtful"


def test_get_entity_serves_the_bands(tmp_path):
    import asyncio
    from types import SimpleNamespace

    from _synthetic_bank import _bank, _entity
    from api.routers import entities as entities_router

    memory = _bank(tmp_path, git=True)
    _entity(memory, "old-notes", confidence=0.9, last_referenced="2020-01-05", decay_class="evergreen")
    settings = SimpleNamespace(memory_path=memory)
    fresh = asyncio.run(entities_router.get_entity("alpha-project", settings=settings)).model_dump(mode="json")
    old = asyncio.run(entities_router.get_entity("old-notes", settings=settings)).model_dump(mode="json")
    assert fresh["bands"]["confidence"] == "very"
    assert fresh["bands"]["fadePace"] == entity_bands.fade_pace(fresh["decay"]["effectiveRatePerWeek"])
    assert old["bands"] == {"confidence": "very", "fadePace": "never", "lastMentioned": "2020-01-05"}
