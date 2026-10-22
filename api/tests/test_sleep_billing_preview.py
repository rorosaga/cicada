"""How a run is billed, by engine id alone (Sleep page v5, B9). No provider is named: the app words it
from this enum and the engine label the person already chose. Ruling 4 stays visible through its one
door: a scheduled preview is a plan only while the person's "Scheduled runs may use my plan" switch is on
(4b), which it is unless they turned it off (4c, 2026-10-19) — and, since ruling 16, a scheduled run reads
everything waiting."""
from __future__ import annotations

import pytest

from test_sleep_engine_prefs import client  # noqa: F401  (the hermetic fixture)

from api.services import sleep_engine_prefs


@pytest.mark.parametrize("engine,billing", [
    ("claude-cli", "plan"), ("codex-cli", "plan"), ("litellm", "charged"), ("ollama", "local"),
    ("something-new", "unknown"), (None, "unknown"),
])
def test_the_billing_enum_comes_from_the_engine_id(engine, billing):
    assert sleep_engine_prefs.billing_for(engine) == billing


def test_a_default_install_previews_charged_on_both_triggers(client):
    prev = client.get("/sleep/engine").json()["preview"]
    assert prev["manual"]["billing"] == "charged" and prev["scheduled"]["billing"] == "charged"


def test_the_scheduled_preview_is_a_plan_only_through_the_persons_switch(client):
    """TODO ruling 4c (owner, 2026-10-19): "Make scheduled runs run on the plan by default." With the switch never
    set, a scheduled run resolves exactly as one the person starts would; only their explicit off keeps it off a
    plan, and then `SUBSCRIPTION_MODES` keeps it off the plan as ruling 4 always did."""
    for mode, model in (("codex", "gpt-5.6-luna"), ("agent", "sonnet")):
        client.put("/sleep/engine", json={"mode": mode, "model": model})
        prev = client.get("/sleep/engine").json()["preview"]
        assert (prev["manual"]["billing"], prev["scheduled"]["billing"]) == ("plan", "plan"), (
            mode, "ruling 4c: the switch is on by default, so a scheduled run may use the plan you chose")
    assert client.put("/sleep/run-options", json={"scheduledUsePlan": False}).json()["scheduledUsePlan"] is False
    for mode, model in (("codex", "gpt-5.6-luna"), ("agent", "sonnet")):
        client.put("/sleep/engine", json={"mode": mode, "model": model})
        prev = client.get("/sleep/engine").json()["preview"]
        assert prev["manual"]["billing"] == "plan", "a run you start may use the plan you chose"
        assert prev["scheduled"]["billing"] != "plan", (mode, "ruling 4: with the switch off, never a plan")


def test_no_provider_name_rides_the_billing_field(client):
    text = str(client.get("/sleep/engine").json()["preview"]).lower()
    for name in ("openai", "anthropic", "claude plan", "chatgpt"):
        assert name not in text.replace("claude-cli", "").replace("codex-cli", ""), name
