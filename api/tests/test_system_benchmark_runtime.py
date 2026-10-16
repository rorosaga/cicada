"""Benchmark instrumentation must preserve the production semantics it measures."""
import asyncio
from datetime import date, datetime, timezone

import pytest
import yaml

from api.config import Settings
from benchmarks.system.engine import FakeEngine
from benchmarks.system.runtime import Runtime


def test_frozen_clock_accepts_real_yaml_dates_and_datetimes():
    from api.services import decay_policy, episode_ids, state_dictionary, turn_authorship
    values = yaml.safe_load('day: 2040-01-01\nstamp: 2040-01-01T12:00:00Z\n')
    clock = datetime(2041, 2, 3, 12, tzinfo=timezone.utc)
    runtime = Runtime(clock, Settings(_env_file=None))
    with runtime.frozen():
        assert isinstance(datetime(2040, 1, 1), episode_ids.datetime)
        assert isinstance(values['stamp'], state_dictionary.datetime)
        assert isinstance(values['stamp'], turn_authorship.datetime)
        assert isinstance(date(2040, 1, 1), decay_policy.date)
        assert decay_policy._as_list(values['day']) == [values['day']]
        assert episode_ids.to_utc_iso(values['stamp']) == '2040-01-01T12:00:00+00:00'
        assert turn_authorship._second(values['stamp']) == values['stamp']
        assert episode_ids.datetime.now(timezone.utc) == clock
        assert decay_policy.date.today() == clock.date()
    assert episode_ids.datetime is datetime
    assert decay_policy.date is date


@pytest.mark.parametrize("asynchronous", [False, True, None])
@pytest.mark.parametrize("failure", [False, True])
def test_fake_completion_keeps_real_provider_binding_and_accounting(monkeypatch, asynchronous, failure):
    from api.services import engine_errors, providers, sleep_drain, telemetry
    counted, emitted = [], []
    monkeypatch.setattr(sleep_drain, 'note_call', counted.append)
    monkeypatch.setattr(telemetry, 'record', emitted.append)
    settings = Settings(_env_file=None, llm_mode='local', ollama_model='deterministic-v1',
                        litellm_model='deterministic-v1')
    fake = FakeEngine()
    if failure:
        fake.arm('failure')
    with Runtime(datetime(2040, 1, 1, tzinfo=timezone.utc), settings, fake):
        async def unused_transport(**kwargs):
            raise AssertionError('original completion must be replaced')
        fn = providers.resolve_llm_fn(settings, stage='skills', is_async=asynchronous,
                                      completion=unused_transport)
        def invoke():
            result = fn(messages=[{'role': 'user', 'content': 'Synthetic empty skill input.'}])
            return asyncio.run(result) if asynchronous is not False else result
        if failure:
            with pytest.raises(engine_errors.EngineUnavailable):
                invoke()
        else:
            assert invoke().choices[0].message.content == '{"skills": []}'
    assert len(counted) == 1
    assert len(emitted) == 1
    assert emitted[0].stage == 'skills'
    assert emitted[0].model == 'ollama/deterministic-v1'
    assert emitted[0].ok is not failure
    assert fake.calls[0]['model'] == 'ollama/deterministic-v1'
