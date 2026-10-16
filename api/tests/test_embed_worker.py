"""A long document embed runs in a child process (``embed_worker``, 2026-10-09): Core ML holds the GIL for every
predict, and a background re-embed of an owner-sized bank in the backend's own process starved the event loop
(``/healthz`` and the capture hook's POST past 10 s). The child here is a stand-in (``embed_worker_stub``) with the
same call shape that can hold its own GIL the way Core ML does; nothing is downloaded.
"""
from __future__ import annotations

import os
import signal
import threading
import time

import numpy as np
import pytest

from api.config import Settings
from api.services import embed_worker, embedding_health, sleep_cycle
from api.services import embedding_models as em
from api.services.coreml_embedder import EmbedderUnavailable
from api.tests import test_embeddinggemma2 as gemma2
from api.tests.embed_worker_stub import hold_gil, vectors
from api.tests.test_embeddinggemma2 import E5, GEMMA, _bank, _build_with, _meta, _wait

mac15, two_models = gemma2.mac15, gemma2.two_models   # the same fixtures: both models present, Core ML faked

STUB = "api.tests.embed_worker_stub:make"


@pytest.fixture
def worker_on(tmp_path, monkeypatch):
    monkeypatch.setenv(embed_worker.ENV, "on")
    monkeypatch.setattr(embed_worker, "FACTORY", STUB)
    pidfile = tmp_path / "pids"
    monkeypatch.setenv("EMBED_STUB_PIDFILE", str(pidfile))
    embed_worker.shutdown()
    yield pidfile
    embed_worker.shutdown()


def _pids(pidfile) -> set[int]:
    if not pidfile.exists():
        return set()
    return {int(line.split()[0]) for line in pidfile.read_text().splitlines()}


def _texts(n, word="alpha"):
    return [f"{word} project passage {i}" for i in range(n)]


def test_a_long_batch_embeds_in_a_child_and_a_short_one_here(worker_on):
    here = []

    def fallback(texts, *, is_query=False):
        here.append(len(texts))
        return vectors(texts, 768, "g")

    embed = embed_worker.documents(GEMMA, fallback)
    texts = _texts(40)
    out = embed(texts)
    assert np.allclose(out, vectors(texts, 768, "g")), "the same model, the same vectors"
    assert here == [] and _pids(worker_on) and os.getpid() not in _pids(worker_on)
    embed(_texts(embed_worker.MIN_TEXTS - 1))
    embed(["a query"], is_query=True)
    assert here == [embed_worker.MIN_TEXTS - 1, 1], "a few documents and every query stay in this process"


def test_a_batch_longer_than_one_request_is_split_in_order(worker_on, monkeypatch):
    monkeypatch.setattr(embed_worker, "BATCH", 7)
    texts = _texts(30)
    out = embed_worker.documents(GEMMA, None)(texts)
    assert np.allclose(out, vectors(texts, 768, "g"))
    assert [int(line.split()[1]) for line in worker_on.read_text().splitlines()] == [7, 7, 7, 7, 2]


def test_while_the_child_embeds_this_process_keeps_its_gil(worker_on, monkeypatch):
    """The bug itself: a predict that holds the GIL for 400 ms stalls every thread when it runs here, and none
    when it runs in the child."""
    monkeypatch.setenv("EMBED_STUB_HOLD_MS", "400")
    embed = embed_worker.documents(GEMMA, None)
    embed(_texts(16, "warm"))          # the child's start (an interpreter and numpy) is not what is measured

    def longest_gap(work) -> float:
        done = threading.Event()
        t = threading.Thread(target=lambda: (work(), done.set()), daemon=True)
        gaps, last = [], time.perf_counter()
        t.start()
        while not done.is_set():
            time.sleep(0.001)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now
        t.join()
        return max(gaps)

    in_child = longest_gap(lambda: embed(_texts(16)))
    in_here = longest_gap(lambda: hold_gil(400))
    assert in_here > 0.3, "the stand-in holds the GIL the way Core ML does"
    assert in_child < 0.15, f"the event loop's thread waited {in_child * 1000:.0f} ms"


def test_a_child_that_died_is_replaced(worker_on):
    embed = embed_worker.documents(GEMMA, None)
    embed(_texts(16))
    first = embed_worker._worker(GEMMA).pid
    os.kill(first, signal.SIGKILL)
    _wait(lambda: embed_worker._worker(GEMMA)._proc.poll() is not None)
    assert np.allclose(embed(_texts(16, "beta")), vectors(_texts(16, "beta"), 768, "g"))
    assert embed_worker._worker(GEMMA).pid != first


def test_the_child_exits_when_idle_or_when_the_backend_goes_away(worker_on):
    import io
    import pickle

    r, w = os.pipe()
    with os.fdopen(r, "rb") as inp, os.fdopen(w, "wb"):
        assert embed_worker.serve(GEMMA, STUB, inp, io.BytesIO(), idle_s=0.05) == 0, "nothing came: it exits"
    r, w = os.pipe()
    os.write(w, pickle.dumps(("embed", ["alpha"])))
    os.close(w)                                   # the backend wrote one request and went away
    out = io.BytesIO()
    with os.fdopen(r, "rb") as inp:
        assert embed_worker.serve(GEMMA, STUB, inp, out, idle_s=5) == 0
    status, payload = pickle.loads(out.getvalue())
    assert status == "ok" and np.allclose(payload, vectors(["alpha"], 768, "g"))
    # And the parent's side: a child that exited between two requests is replaced without a word.
    embed = embed_worker.documents(GEMMA, None)
    embed(_texts(16))
    worker = embed_worker._worker(GEMMA)
    worker._proc.stdin.close()                    # what the child sees when it is told nothing more is coming
    _wait(lambda: worker._proc.poll() is not None)
    assert embed(_texts(16, "beta")).shape == (16, 768)


def test_the_childs_error_reaches_the_caller_as_itself(worker_on):
    embed = embed_worker.documents(GEMMA, None)
    with pytest.raises(EmbedderUnavailable) as caught:
        embed(_texts(15) + ["fail:missing"])
    assert embedding_health.classify(caught.value) == "model_missing", "Settings still says the right sentence"
    assert embed(_texts(16)).shape == (16, 768), "and the same child keeps serving"


def test_only_an_on_device_model_and_only_with_the_switch_on(two_models, monkeypatch):
    monkeypatch.setenv(embed_worker.ENV, "on")
    assert embed_worker.eligible(GEMMA) and embed_worker.eligible(E5)
    assert not embed_worker.eligible("text-embedding-3-small"), "a hosted model waits on the network, not the GIL"
    assert not embed_worker.eligible(None)
    monkeypatch.setenv(embed_worker.ENV, "off")
    assert not embed_worker.eligible(GEMMA)


# --------------------------------------------------------------------------- the background re-embed, end to end

def test_the_re_embed_embeds_in_the_child_and_keeps_every_rule(two_models, worker_on, tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_BACKGROUND_REINDEX", "on")
    bank = _bank(tmp_path, n_pages=80)        # more than one stoppable chunk of pages and of claims
    _build_with(bank, E5, 384)
    two_models.update(e5=0, gemma=0)
    em.REINDEX._set(state="idle")
    assert em.start_reindex_if_needed(bank, Settings())
    assert _wait(lambda: em.REINDEX.snapshot()["state"] == "done", timeout=60)
    meta = _meta(bank)
    assert {meta[f"model:{k}"] for k in ("entities", "claims", "episodes")} == {GEMMA}
    assert {meta[f"dim:{k}"] for k in ("entities", "claims", "episodes")} == {"768"}
    child_texts = sum(int(line.split()[1]) for line in worker_on.read_text().splitlines())
    assert child_texts == 160 and os.getpid() not in _pids(worker_on), "every long chunk went to the child"
    assert two_models["gemma"] == 3, "the three short passages stayed here, with the same model"
    from api.services.vector_index import SqliteVecIndexer

    assert all(SqliteVecIndexer(bank).search_kinds("alpha project", {"entities": 3, "claims": 3}).values())


def test_with_the_child_the_job_still_gives_way_when_sleep_starts(two_models, worker_on, tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_BACKGROUND_REINDEX", "on")
    bank = _bank(tmp_path, n_pages=80)
    _build_with(bank, E5, 384)
    before = _meta(bank)
    state = sleep_cycle.get_sleep_state()
    real = embed_worker._Worker.embed

    def sleep_starts_after_one_chunk(self, texts):
        out = real(self, texts)
        state.status = "running"
        return out

    monkeypatch.setattr(embed_worker._Worker, "embed", sleep_starts_after_one_chunk)
    monkeypatch.setattr(state, "status", "idle")
    em.REINDEX._set(state="idle")
    assert em.start_reindex_if_needed(bank, Settings())
    assert _wait(lambda: em.REINDEX.snapshot()["state"] == "waiting", timeout=60)
    assert _meta(bank) == before, "it gave way before writing: every table as it was"
    state.status = "idle"


def test_sleeps_own_long_sync_embeds_in_the_child_too(two_models, worker_on, tmp_path, monkeypatch):
    bank = _bank(tmp_path, n_pages=40)
    _build_with(bank, GEMMA, 768)
    for i in range(40):                       # forty edited pages: one long batch for Sleep's entity sync
        page = bank / "entities" / f"page-{i}.md"
        page.write_text(page.read_text().replace("A synthetic page", "An edited page"))
    two_models.update(e5=0, gemma=0)
    assert sleep_cycle._sync_vector_indexes(bank) == []
    assert sum(int(line.split()[1]) for line in worker_on.read_text().splitlines()) == 40
    assert two_models["gemma"] == 0


# --------------------------------------------------------------------------- the download's warm-up

def test_the_downloads_warm_up_loads_the_model_in_a_child(mac15, worker_on):
    """The Neural Engine compile (≈ 90 s the first time) holds the GIL for as long as it takes; after a download it
    ran inside the backend. Here the child loads the real Core ML runtime against a fake folder and fails: the error
    is the download's own sentence, and nothing was loaded in this process."""
    from api.services import model_fetch
    from api.tests.test_embeddinggemma2 import _FakeModel, _gemma_folder

    folder = _gemma_folder(mac15 / "models")
    with pytest.raises(model_fetch.FetchError):
        model_fetch._warm(folder, lambda *a: None)
    assert _FakeModel.loads == [], "no function was loaded in the backend's own process"
    with pytest.raises(RuntimeError):
        embed_worker.warm_in_child(mac15 / "not-a-model")
