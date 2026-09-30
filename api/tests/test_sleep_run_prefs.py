"""Reading options (Sleep page v5, B1): batch size, the opt-in continue-after-reset switch
(TODO ruling 15) and the reserve line. Stored beside the engine choice, snapshotted per run."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from drain_harness import episode_ids, install, seed_bank, settings

from api import main
from api.services import sleep_cycle, sleep_run_prefs
from api.services.connections import registry as registry_module


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()


@pytest.fixture
def client():
    return TestClient(main.app)


def test_defaults_are_the_setting_off_and_off(client):
    body = client.get("/sleep/run-options").json()
    assert body["batchSize"] == sleep_cycle.DEFAULT_EPISODE_CAP, "no choice made: the setting is the batch size"
    assert body["batchSizeChoices"] == [10, 25, 50], "50 is the ceiling: a commit records at most 50 conversations"
    assert body["continueAfterReset"] is False, "TODO ruling 15: off by default"
    assert body["reservePct"] is None and body["reserveChoices"] == [5, 10, 20, 30]


def test_a_put_merges_round_trips_and_clears(client):
    assert client.put("/sleep/run-options", json={"batchSize": 10}).json()["batchSize"] == 10
    body = client.put("/sleep/run-options", json={"continueAfterReset": True, "reservePct": 20}).json()
    assert (body["batchSize"], body["continueAfterReset"], body["reservePct"]) == (10, True, 20), "a partial body merges"
    assert client.get("/sleep/run-options").json() == body
    cleared = client.put("/sleep/run-options", json={"reservePct": None, "continueAfterReset": False}).json()
    assert cleared["reservePct"] is None and cleared["continueAfterReset"] is False and cleared["batchSize"] == 10


@pytest.mark.parametrize("body", [{"batchSize": 100}, {"batchSize": 7}, {"reservePct": 15}, {"reservePct": 50},
                                  {"continueAfterReset": None}])
def test_values_outside_the_choices_are_a_422_and_write_nothing(client, body):
    before = client.get("/sleep/run-options").json()
    assert client.put("/sleep/run-options", json=body).status_code == 422
    assert client.get("/sleep/run-options").json() == before


def test_the_options_live_in_the_machine_wide_prefs_never_a_bank(client, tmp_path):
    client.put("/sleep/run-options", json={"batchSize": 50, "continueAfterReset": True})
    from api.services.auth import cicada_home

    prefs = json.loads((cicada_home() / "connections.json").read_text())
    assert prefs["sleep-run"] == {"batch_size": 50, "continue_after_reset": True}


def test_a_hand_edited_prefs_file_reads_as_the_defaults(client):
    from api.services.auth import cicada_home

    (cicada_home() / "connections.json").write_text(json.dumps(
        {"sleep-run": {"batch_size": "lots", "continue_after_reset": "yes", "reserve_pct": 99}}))
    opts = sleep_run_prefs.load(registry_module.get_registry(settings(None)))
    assert opts == sleep_run_prefs.RunOptions(None, False, None), "never a reason to spend more"


def test_a_run_reads_in_batches_of_the_chosen_size_not_the_env_setting(tmp_path, monkeypatch, client):
    ids = episode_ids(23)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    client.put("/sleep/run-options", json={"batchSize": 10})
    asyncio.run(sleep_cycle.run(
        settings(memory, sleep_max_episodes_per_cycle=25), "sleep_pref", user_triggered=True, drain=True))
    assert [len(b) for b in rig.extract_batches] == [10, 10, 3]
    assert sleep_cycle.get_sleep_state().drain.batch_size == 10


def test_changing_the_options_mid_run_does_not_change_the_running_drain(tmp_path, monkeypatch, client):
    ids = episode_ids(23)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    client.put("/sleep/run-options", json={"batchSize": 10})

    async def flip(batch_no, episodes):
        if batch_no == 1:
            client.put("/sleep/run-options", json={"batchSize": 50, "continueAfterReset": True, "reservePct": 5})

    rig.on_extract = flip
    asyncio.run(sleep_cycle.run(
        settings(memory, sleep_max_episodes_per_cycle=25), "sleep_flip", user_triggered=True, drain=True))
    assert [len(b) for b in rig.extract_batches] == [10, 10, 3], "a run snapshots its options when it starts"
    ds = sleep_cycle.get_sleep_state().drain
    assert ds.continue_after_reset is False and ds.reserve_pct is None
