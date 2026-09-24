"""Round-4 D4 (G144) — scripts/gen-tz-coordinates.py, the generator of the app's time zone → coordinates table.

Every case runs over a synthetic tzdata directory in tmp_path: the network is never touched, and no real zone's
coordinates are asserted beyond the generator's own arithmetic.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "gen-tz-coordinates.py"


def _generator():
    # The file name has hyphens (a script, not a module), so it is loaded by path.
    spec = importlib.util.spec_from_file_location("gen_tz_coordinates", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tzdata(tmp_path: Path) -> Path:
    d = tmp_path / "tzdata"
    d.mkdir()
    (d / "zone1970.tab").write_text(
        "# This file is in the public domain.\n"
        "DE,NO\t+5230+01322\tEurope/Berlin\n"
        "US\t+404251-0740023\tAmerica/New_York\tEastern (most areas)\n",
        encoding="utf-8",
    )
    (d / "zone.tab").write_text(
        "# This file is in the public domain.\n"
        "NO\t+5955+01045\tEurope/Oslo\n"
        "DE\t+5000+01000\tEurope/Berlin\n",
        encoding="utf-8",
    )
    (d / "backward").write_text(
        "Link\tEurope/Berlin\tArctic/Example\n"
        "Link\tArctic/Example\tAntarctica/Example\t# a link to a link\n"
        "Link\tNowhere/Unknown\tEtc/Orphan\n",
        encoding="utf-8",
    )
    (d / "version").write_text("2099z\n", encoding="utf-8")
    return d


def test_iso6709_degrees_minutes_and_seconds():
    gen = _generator()
    lat, lon = gen.parse_iso6709("+404251-0740023")
    assert lat == pytest.approx(40.7142, abs=1e-4)
    assert lon == pytest.approx(-74.0064, abs=1e-4)
    lat, lon = gen.parse_iso6709("-7750+16636")
    assert lat == pytest.approx(-77.8333, abs=1e-4)
    assert lon == pytest.approx(166.6, abs=1e-4)
    with pytest.raises(ValueError):
        gen.parse_iso6709("40N74W")


def test_zone1970_wins_then_zone_tab_fills_then_links_resolve(tmp_path):
    zones = _generator().build(_tzdata(tmp_path))
    assert zones["Europe/Berlin"] == [52.5, 13.37], "zone1970.tab wins where both tables name a zone"
    assert zones["Europe/Oslo"] == [59.92, 10.75], "zone.tab fills a zone zone1970.tab folds into another"
    assert zones["Arctic/Example"] == zones["Europe/Berlin"]
    assert zones["Antarctica/Example"] == zones["Europe/Berlin"], "a link to a link resolves"
    assert "Etc/Orphan" not in zones, "a link to nothing is left out, never guessed"
    assert zones["America/New_York"] == [40.71, -74.01], "rounded to 2 decimals (R-FA5)"


def test_main_writes_the_resource_with_its_source_and_version(tmp_path):
    out = tmp_path / "scene" / "tz-coordinates.json"
    assert _generator().main(["--tzdata", str(_tzdata(tmp_path)), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["version"] == "2099z"
    assert "public domain" in payload["source"]
    assert payload["zones"]["Europe/Oslo"] == [59.92, 10.75]
