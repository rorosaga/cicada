"""G166 (spec §7.2) — the person's reading settings: a machine file outside every
bank, an acknowledgement before the switch, per-site switches that start empty."""
from __future__ import annotations

import json
import stat
from datetime import date

import pytest

from api.services import reading_settings


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def test_the_default_is_off_and_empty():
    snap = reading_settings.snapshot()
    assert snap == {"agentEnabled": False, "agentHosts": [], "ackedAt": None, "ackCurrent": False}
    assert not reading_settings.path().exists(), "reading never creates the file"


def test_turning_on_needs_the_acknowledgement():
    with pytest.raises(reading_settings.SettingsError) as err:
        reading_settings.update(agent_enabled_=True)
    assert "I understand" in str(err.value)
    assert reading_settings.agent_enabled() is False and not reading_settings.path().exists()


def test_the_acknowledgement_can_ride_the_same_call_and_is_dated():
    snap = reading_settings.update(agent_enabled_=True, acknowledge=True, today=date(2026, 9, 29))
    assert snap["agentEnabled"] is True and snap["ackedAt"] == "2026-09-29" and snap["ackCurrent"] is True
    data = json.loads(reading_settings.path().read_text())
    assert data["agent_ack"] == {"date": "2026-09-29", "v": reading_settings.ACK_VERSION}
    assert stat.S_IMODE(reading_settings.path().stat().st_mode) == 0o600


def test_a_new_wording_asks_again(monkeypatch):
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    monkeypatch.setattr(reading_settings, "ACK_VERSION", reading_settings.ACK_VERSION + 1)
    assert reading_settings.ack_current() is False
    assert reading_settings.agent_enabled() is False, "an old acknowledgement no longer counts"
    with pytest.raises(reading_settings.SettingsError):
        reading_settings.update(agent_enabled_=True)


def test_turning_off_keeps_the_acknowledgement_and_the_sites():
    reading_settings.update(agent_enabled_=True, acknowledge=True, agent_hosts=["x", "linkedin"])
    reading_settings.update(agent_enabled_=False)
    assert reading_settings.agent_enabled() is False
    assert reading_settings.allowed_hosts() == ("linkedin", "x")
    assert reading_settings.update(agent_enabled_=True)["agentEnabled"] is True, "no second sheet"


def test_a_bad_site_key_is_refused_whole():
    with pytest.raises(reading_settings.SettingsError) as err:
        reading_settings.update(agent_hosts=["x", "reddit"])
    assert "reddit" in str(err.value)
    assert reading_settings.allowed_hosts() == ()


def test_hosts_keep_the_sheets_order_and_a_hand_edited_file_grants_nothing_unknown():
    reading_settings.update(agent_hosts=["tiktok", "x", "linkedin", "x"])
    assert reading_settings.allowed_hosts() == ("linkedin", "x", "tiktok")
    data = json.loads(reading_settings.path().read_text())
    data["agent_hosts"] = ["x", "reddit", 7]
    reading_settings.path().write_text(json.dumps(data))
    assert reading_settings.allowed_hosts() == ("x",)


def test_a_no_op_call_writes_nothing():
    reading_settings.update(agent_hosts=["x"])
    before = reading_settings.path().stat().st_mtime_ns
    reading_settings.update(agent_hosts=["x"])
    assert reading_settings.path().stat().st_mtime_ns == before


def test_the_file_is_read_on_every_call():
    """Two processes read it (the backend and the stdio server): nothing is cached."""
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    assert reading_settings.agent_enabled() is True
    data = json.loads(reading_settings.path().read_text())
    data["agent"] = False
    reading_settings.path().write_text(json.dumps(data))
    assert reading_settings.agent_enabled() is False


def test_a_corrupt_file_reads_as_off():
    reading_settings.path().parent.mkdir(parents=True, exist_ok=True)
    reading_settings.path().write_text("{not json")
    assert reading_settings.snapshot()["agentEnabled"] is False
