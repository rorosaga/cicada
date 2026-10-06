"""Benchmark-only service clock, transparent observers and provider substitution."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import date, datetime
import functools
import importlib
import inspect
import sys
import time
from unittest.mock import patch

# Preload clock-bearing pipeline/tail dependencies before installing the clock.
# A clock outside this list is not silently claimed to be controlled.
CLOCK_MODULES = (
    'sleep_cycle', 'conflict_resolver', 'claim_pipeline', 'claim_reconciler',
    'inbox_generator', 'inbox_questions', 'episode_staging', 'episode_ids',
    'agentic_write', 'state_dictionary', 'sleep_paused', 'sleep_runs',
    'claim_expiry', 'followups', 'source_links', 'pending_store', 'progress',
    'owner_identity', 'hub_builder', 'entity_extractor', 'entity_resolver',
    'skill_extractor', 'vector_index', 'search_index', 'ask_service',
    'mcp_tools', 'sleep_debt', 'sleep_progress', 'sleep_run_prefs',
)


class Runtime:
    def __init__(self, clock, settings, fake=None):
        self.clock, self.settings, self.fake = clock, settings, fake
        self.timings, self.clock_modules, self.calls = [], [], []
        self.write_starts = {}
        self.current_batch = None
        self.embedding_calls = []
        self.stack = ExitStack()

    def observe(self, module, name, label):
        original = getattr(module, name)

        def start(args):
            from api.services import sleep_cycle
            cid = (args[1] if label in ('batch', 'drain') else self.current_batch or sleep_cycle.get_sleep_state().cycle_id)
            if label == 'write_start':
                self.write_starts[cid] = time.perf_counter()
            return time.perf_counter(), cid

        def finish(started, cid, ok):
            self.timings.append({'stage': label, 'cycle': cid, 'wall_seconds': time.perf_counter() - started, 'ok': ok})
            if label == 'pipeline' and cid in self.write_starts:
                self.timings.append({'stage': 'write', 'cycle': cid,
                                     'wall_seconds': time.perf_counter() - self.write_starts.pop(cid), 'ok': ok})

        if inspect.iscoroutinefunction(original):
            @functools.wraps(original)
            async def wrapper(*args, **kwargs):
                started, cid = start(args)
                previous_batch = self.current_batch
                if label == 'batch':
                    self.current_batch = cid
                ok = False
                try:
                    value = await original(*args, **kwargs)
                    ok = True
                    return value
                finally:
                    finish(started, cid, ok)
                    if label == 'batch':
                        self.current_batch = previous_batch
        else:
            @functools.wraps(original)
            def wrapper(*args, **kwargs):
                started, cid = start(args)
                ok = False
                try:
                    value = original(*args, **kwargs)
                    ok = True
                    return value
                finally:
                    finish(started, cid, ok)
        self.stack.enter_context(patch.object(module, name, wrapper))

    def __enter__(self):
        modules = [importlib.import_module('api.services.' + name) for name in CLOCK_MODULES]
        from api.services import providers, sleep_cycle
        original_factory = providers.resolve_llm_fn

        def pin(settings, **kwargs):
            if settings.llm_mode != 'codex' or settings.codex_model != self.settings.codex_model:
                raise RuntimeError('subscription-only pin lost; refusing fallback')
            fn = original_factory(settings, **kwargs)
            asynchronous = kwargs.get('is_async', inspect.iscoroutinefunction(kwargs.get('completion')))

            def record(started, result=None, exc=None):
                from api.services import telemetry
                self.calls.append({'stage': kwargs.get('stage'), 'model': settings.codex_model,
                                   'wall_seconds': time.perf_counter() - started,
                                   'tokens': telemetry.usage_from_response(result) if result is not None else None,
                                   'ok': exc is None, 'error': type(exc).__name__ if exc else None,
                                   'retry': None})

            async def async_call(**kw):
                started = time.perf_counter()
                try:
                    response = await fn(**kw)
                except Exception as exc:
                    record(started, exc=exc)
                    raise
                record(started, response)
                return response

            def call(**kw):
                started = time.perf_counter()
                try:
                    response = fn(**kw)
                except Exception as exc:
                    record(started, exc=exc)
                    raise
                record(started, response)
                return response
            return async_call if asynchronous else call

        factory = self.fake.resolve if self.fake else pin
        # Replace existing imported aliases as well as dynamic factory imports.
        for module in [providers, *modules]:
            if getattr(module, 'resolve_llm_fn', None) is original_factory:
                self.stack.enter_context(patch.object(module, 'resolve_llm_fn', factory))
        if not self.fake:
            for name in ('resolve_embed_fn', 'resolve_embed_fn_for_model'):
                original_embed_factory = getattr(providers, name)
                def measured_factory(*args, _original=original_embed_factory, **kwargs):
                    fn, model = _original(*args, **kwargs)
                    return self.measured_embed(fn), model
                self.stack.enter_context(patch.object(providers, name, measured_factory))
        if self.fake:
            from .engine import embed
            self.stack.enter_context(patch.object(providers, 'resolve_embed_fn', lambda *a, **k: (self.measured_embed(embed), 'fake-hash-v1')))
            self.stack.enter_context(patch.object(providers, 'resolve_embed_fn_for_model', lambda *a, **k: (self.measured_embed(embed), 'fake-hash-v1')))
            # Tests fail closed on accidental network, including downloads.
            import socket
            def no_network(*args, **kwargs):
                raise RuntimeError('offline benchmark forbids network access')
            self.stack.enter_context(patch.object(socket.socket, 'connect', no_network))
            self.stack.enter_context(patch.object(socket, 'create_connection', no_network))
        observers = (
            ('entity_extractor', 'extract', 'extraction'),
            ('entity_resolver', 'resolve', 'resolution'),
            ('conflict_resolver', 'resolve_and_prune', 'conflicts'),
            ('skill_extractor', 'detect_patterns', 'patterns'),
            ('inbox_generator', 'generate', 'write_start'),
            ('sleep_cycle', '_run_stages', 'pipeline'),
            ('sleep_cycle', '_finalize', 'commit'),
            ('sleep_cycle', '_run_batch', 'batch'),
            ('sleep_cycle', 'run', 'drain'),
            ('sleep_cycle', '_run_engine_independent_tail', 'tail'),
            ('sleep_cycle', '_sync_vector_indexes', 'index'),
        )
        for module, name, label in observers:
            self.observe(importlib.import_module('api.services.' + module), name, label)
        for name in ('index_entities', 'index_episodes', 'index_claims'):
            from api.services.vector_index import SqliteVecIndexer
            self.observe(SqliteVecIndexer, name, name)
        from api.services import search_index
        self.observe(search_index, 'refresh', 'index_lexical')
        return self

    def measured_embed(self, fn):
        def measured(texts, *, is_query=False):
            started = time.perf_counter()
            try:
                return fn(texts, is_query=is_query)
            finally:
                self.embedding_calls.append({'batch': self.current_batch, 'texts': len(texts),
                    'characters': sum(map(len, texts)), 'query': is_query,
                    'wall_seconds': time.perf_counter() - started})
        return measured

    @contextmanager
    def frozen(self):
        clock = self.clock
        class FrozenDate(date):
            @classmethod
            def today(cls):
                return clock.date()
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.astimezone(tz) if tz else clock.replace(tzinfo=None)
            @classmethod
            def utcnow(cls):
                from datetime import timezone
                return clock.astimezone(timezone.utc).replace(tzinfo=None)
        with ExitStack() as stack:
            covered = []
            for name, module in list(sys.modules.items()):
                if not name.startswith('api.services.') or name in ('api.services.codex_app_server', 'api.services.plan_limits', 'api.services.telemetry'):
                    continue
                for attr, original, replacement in (('date', date, FrozenDate), ('datetime', datetime, FrozenDatetime)):
                    if getattr(module, attr, None) is original:
                        stack.enter_context(patch.object(module, attr, replacement))
                        covered.append(f'{name}.{attr}')
            self.clock_modules = sorted(set(self.clock_modules + covered))
            yield

    def __exit__(self, *args):
        return self.stack.__exit__(*args)
