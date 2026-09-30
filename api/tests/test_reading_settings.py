"""G166 (spec §7.2, ruling 14 amended 2026-09-30) — the person's reading settings: a machine
file outside every bank, a versioned acknowledgement before the switch, and per-site
permissions that start empty and are granted only for a site Cicada's reader could not read."""
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
    assert snap == {"agentEnabled": False, "allowedSites": {}, "ackedAt": None, "ackCurrent": False}
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


def test_sites_start_empty():
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    assert reading_settings.allowed_sites() == {} and reading_settings.site_allowed("linkedin") is False


def test_site_patch_stamps_and_removes():
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    snap = reading_settings.update(sites={"linkedin": True, "paperfold.io": True}, surfaced={"linkedin", "paperfold.io"},
                                   today=date(2026, 9, 30))
    assert snap["allowedSites"] == {"linkedin": "2026-09-30", "paperfold.io": "2026-09-30"}
    # a grant keeps its first day; false removes
    snap = reading_settings.update(sites={"linkedin": True, "paperfold.io": False}, today=date(2026, 10, 2))
    assert snap["allowedSites"] == {"linkedin": "2026-09-30"}
    snap = reading_settings.update(sites={"linkedin": False})
    assert snap["allowedSites"] == {} and "agent_sites" not in json.loads(reading_settings.path().read_text())


def test_bad_site_key_refuses_whole():
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    with pytest.raises(reading_settings.SettingsError) as err:
        reading_settings.update(sites={"linkedin": True, "Not A Site": True}, surfaced={"linkedin"})
    assert "Not A Site" in str(err.value)
    assert reading_settings.allowed_sites() == {}
    with pytest.raises(reading_settings.SettingsError):
        reading_settings.update(sites={"t.co": True}, surfaced={"t.co"})  # never offered, whatever


def test_a_grant_for_a_site_that_was_never_surfaced_is_refused():
    """A permission for a site nothing has asked about would be a pre-picked list through the side door."""
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    with pytest.raises(reading_settings.SettingsError) as err:
        reading_settings.update(sites={"paperfold.io": True}, surfaced={"linkedin"})
    assert "paperfold.io" in str(err.value) and "nothing to allow" in str(err.value)
    assert reading_settings.allowed_sites() == {}
    # taking one back never needs it to be surfaced
    reading_settings.update(sites={"paperfold.io": False})


def test_a_grant_counts_only_while_the_master_is_on():
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    reading_settings.update(sites={"linkedin": True}, surfaced={"linkedin"})
    assert reading_settings.site_allowed("linkedin") is True
    reading_settings.update(agent_enabled_=False)
    assert reading_settings.site_allowed("linkedin") is False
    assert reading_settings.allowed_sites() == {"linkedin": reading_settings.allowed_sites()["linkedin"]}, "kept"
    assert reading_settings.update(agent_enabled_=True)["agentEnabled"] is True, "no second sheet"
    assert reading_settings.site_allowed("linkedin") is True


def test_a_site_grant_while_off_needs_the_sheet_and_the_acknowledgement_can_ride_along():
    with pytest.raises(reading_settings.SettingsError) as err:
        reading_settings.update(sites={"linkedin": True}, surfaced={"linkedin"})
    assert "I understand" in str(err.value) and not reading_settings.path().exists()
    snap = reading_settings.update(agent_enabled_=True, acknowledge=True, sites={"linkedin": True},
                                   surfaced={"linkedin"})
    assert snap["agentEnabled"] is True and "linkedin" in snap["allowedSites"], "one call from the sheet"
    # acknowledged already: a grant is stored while the switch is off, and counts once it is on
    reading_settings.update(agent_enabled_=False)
    reading_settings.update(sites={"linkedin": False})
    snap = reading_settings.update(sites={"linkedin": True}, surfaced={"linkedin"})
    assert snap["agentEnabled"] is False and "linkedin" in snap["allowedSites"]
    assert reading_settings.site_allowed("linkedin") is False


def test_ack_version_2_re_asks_a_v1_acknowledgement():
    assert reading_settings.ACK_VERSION == 2
    reading_settings.path().parent.mkdir(parents=True, exist_ok=True)
    reading_settings.path().write_text(json.dumps({"agent": True, "agent_ack": {"date": "2026-09-29", "v": 1}}))
    assert reading_settings.ack_current() is False
    assert reading_settings.agent_enabled() is False, "the switch reads off until they read the new sheet"
    assert reading_settings.snapshot()["ackCurrent"] is False


def test_a_stale_agent_hosts_key_grants_nothing_and_is_dropped_on_write():
    reading_settings.path().parent.mkdir(parents=True, exist_ok=True)
    reading_settings.path().write_text(json.dumps({"agent": True, "agent_hosts": ["x", "linkedin"],
                                                   "agent_ack": {"date": "2026-09-29", "v": 2}}))
    assert reading_settings.allowed_sites() == {} and reading_settings.site_allowed("x") is False
    reading_settings.update(agent_enabled_=False)
    assert "agent_hosts" not in json.loads(reading_settings.path().read_text())


def test_a_hand_edited_file_grants_nothing_for_an_invalid_key():
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    data = json.loads(reading_settings.path().read_text())
    data["agent_sites"] = {"linkedin": "2026-09-30", "Bad Key": "2026-09-30", "t.co": "2026-09-30", "a/b": "x"}
    reading_settings.path().write_text(json.dumps(data))
    assert reading_settings.allowed_sites() == {"linkedin": "2026-09-30"}


def test_no_op_patch_writes_nothing():
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    reading_settings.update(sites={"linkedin": True}, surfaced={"linkedin"})
    before = reading_settings.path().stat().st_mtime_ns
    reading_settings.update(sites={"linkedin": True})
    reading_settings.update(sites={"paperfold.io": False})
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
