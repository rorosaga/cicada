"""G182 phase 3 — each bank is built with its own model; the larger model is an optional download."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config
from api.config import Settings
from api.services import embedding_models as em
from api.services import coreml_embedder, onnx_embedder, providers


def _bundle(root: Path) -> None:
    d = root / "multilingual-e5-small"
    d.mkdir(parents=True)
    (d / "model.onnx").write_bytes(b"x")
    (d / "tokenizer.json").write_text("{}")
    (d / onnx_embedder.MANIFEST).write_text(json.dumps({"id": em.SMALL_ID, "dimensions": 384}))


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("CICADA_EMBEDDING_MODE", "CICADA_EMBEDDING_MODEL", "CICADA_EMBEDDING_MODEL_LOCAL",
              "CICADA_BUNDLED_MODELS", "CICADA_DISTRIBUTION"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    bank = tmp_path / "bank"
    bank.mkdir()
    return bank


def test_a_choice_is_kept_outside_the_bank_per_bank(env, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    em.set_bank_choice(env, em.SMALL_ID)
    assert em.bank_choice(env) == em.SMALL_ID and em.bank_choice(other) is None
    assert em.choices_path().parent == Path(tmp_path / "home")
    assert not any(env.iterdir()), "nothing is written into the bank"
    em.set_bank_choice(env, None)
    assert em.bank_choice(env) is None


def test_build_model_order(env, tmp_path, monkeypatch):
    _bundle(tmp_path / "models")
    monkeypatch.setenv("CICADA_BUNDLED_MODELS", str(tmp_path / "models"))
    s = Settings()
    assert em.build_model(env, s) == em.SMALL_ID, "a fresh bank: the bundled default"
    monkeypatch.setattr(em, "recorded_model", lambda bank: em.LARGE_ID)
    monkeypatch.setattr(em, "sentence_transformers_available", lambda: True)
    monkeypatch.setattr(em, "_in_hf_cache", lambda mid: True)
    assert em.build_model(env, s) == em.LARGE_ID, "a bank built with EmbeddingGemma keeps it"
    em.set_bank_choice(env, em.SMALL_ID)
    assert em.build_model(env, s) == em.SMALL_ID, "the person's choice wins"
    em.set_bank_choice(env, None)
    monkeypatch.setattr(em, "sentence_transformers_available", lambda: False)
    assert em.build_model(env, s) == em.LARGE_ID, "a larger-model bank is never re-embedded behind the person's back"
    monkeypatch.setattr(em, "recorded_model", lambda bank: "sentence-transformers/all-MiniLM-L6-v2")
    assert em.build_model(env, s) == em.SMALL_ID, "another recorded model this Mac can't run falls back to the default"


def test_an_explicit_setting_still_switches_every_bank(env, monkeypatch):
    monkeypatch.setenv("CICADA_EMBEDDING_MODEL_LOCAL", "google/embeddinggemma-300m")
    monkeypatch.setattr(em, "recorded_model", lambda bank: "text-embedding-3-small")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert em.build_model(env, Settings()) == "google/embeddinggemma-300m"


def test_the_large_model_in_a_release_needs_its_download(env, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_DISTRIBUTION", "release")
    monkeypatch.setattr(em, "sentence_transformers_available", lambda: True)
    assert not em.is_available(em.LARGE_ID)
    folder = tmp_path / "snap"
    folder.mkdir()
    em._write_json(em.models_path(), {em.LARGE_ID: str(folder)})
    assert em.is_available(em.LARGE_ID)
    assert providers._local_source(em.LARGE_ID) == str(folder)
    assert providers._local_source("other/model") == "other/model"


def test_the_build_side_routes_through_the_banks_model(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(em, "build_model", lambda bank, settings, environ=None: em.SMALL_ID)
    monkeypatch.setattr(providers, "resolve_embed_fn_for_model",
                        lambda mid, settings=None, **kw: (seen.setdefault("mid", mid), mid))
    fn, mid = providers.resolve_embed_fn(Settings(), memory_path=env)
    assert seen["mid"] == mid == em.SMALL_ID == "intfloat/multilingual-e5-small"


def test_status_and_routes(env, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(env))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    _bundle(tmp_path / "models")
    monkeypatch.setenv("CICADA_BUNDLED_MODELS", str(tmp_path / "models"))
    monkeypatch.setattr(em, "sentence_transformers_available", lambda: False)
    # A Mac without the Neural Engine model, whatever runs the suite: on macOS 15+ with coremltools in the
    # venv, the host would offer EmbeddingGemma 2 first (test_embeddinggemma2 covers that side).
    monkeypatch.setattr(coreml_embedder, "supported", lambda: False)
    started = []
    monkeypatch.setattr(em, "_run_install", lambda token, environ: started.append(token))
    config.get_settings.cache_clear()
    from api import main

    try:
        with TestClient(main.app) as client:
            body = client.get("/embeddings").json()
            assert body["model"] == em.SMALL_ID and body["nextModel"] == em.SMALL_ID
            assert [m["id"] for m in body["models"]] == [em.SMALL_ID, em.LARGE_ID]
            assert [m["available"] for m in body["models"]] == [True, False]
            assert client.post("/embeddings/choice", json={"model": "evil/model"}).status_code == 400
            assert client.post("/embeddings/choice", json={"model": em.LARGE_ID}).status_code == 409
            assert client.post("/embeddings/choice", json={"model": em.SMALL_ID}).json()["choice"] == em.SMALL_ID
            assert client.post("/embeddings/install", json={"hfToken": "nope"}).status_code == 400
            ok = client.post("/embeddings/install", json={"hfToken": "hf_" + "a" * 30})
            assert ok.status_code == 202
    finally:
        config.get_settings.cache_clear()
        em.JOB._set(state="idle", step="", error="")
    assert started == ["hf_" + "a" * 30]


def test_the_token_is_never_logged_or_stored(env, monkeypatch):
    monkeypatch.setattr(em, "sentence_transformers_available", lambda: True)

    def fake_download(token, environ):
        raise RuntimeError("Hugging Face didn't accept that token. Check it has read access and try again.")

    monkeypatch.setattr(em, "_download_model", fake_download)
    secret = "hf_" + "s" * 30
    em._run_install(secret, {"CICADA_HOME": str(env.parent / "home")})
    snap = em.JOB.snapshot()
    assert snap["state"] == "failed" and secret not in json.dumps(snap)
    home = env.parent / "home"
    assert not home.exists() or secret not in "".join(p.read_text(errors="ignore") for p in home.rglob("*") if p.is_file())
    em.JOB._set(state="idle", step="", error="")


def test_availability_is_honest(env, monkeypatch, tmp_path):
    monkeypatch.setattr(em, "sentence_transformers_available", lambda: True)
    assert not em.is_available(em.SMALL_ID), "never downloaded through sentence-transformers when not bundled"
    monkeypatch.setattr(em, "_in_hf_cache", lambda mid: False)
    assert not em.is_available(em.LARGE_ID), "gated and not downloaded: choosing it would fail every sync"
    monkeypatch.setattr(em, "_in_hf_cache", lambda mid: True)
    assert em.is_available(em.LARGE_ID), "a developer's cached copy"
    assert em.is_available("sentence-transformers/all-MiniLM-L6-v2")


def test_the_extras_lock_is_hashed_pinned_and_disjoint_from_the_bundle():
    import re
    import tomllib

    root = Path(__file__).resolve().parents[2]
    lock = em.EXTRAS_LOCK.read_text(encoding="utf-8")
    pins = dict(re.findall(r"^([A-Za-z0-9_.-]+)==(\S+)", lock, re.M))
    assert "sentence-transformers" in pins and "torch" in pins
    assert lock.count("--hash=sha256:") >= len(pins)
    bundled = set(re.findall(r"^([A-Za-z0-9_.-]+)==", (root / "scripts/release/requirements.lock").read_text(), re.M))
    pruned = {"hf-xet"}  # locked for the bundle, removed by build-backend.sh, needed by the extras
    assert not set(pins) & (bundled - pruned), "a shared package always comes from the bundle"
    assert pruned <= set(pins)
    build = (root / "scripts/release/build-backend.sh").read_text()
    assert all(f'"$SITE"/{n.replace("-", "_")}' in build for n in pruned), "the prune list and the lock agree"
    uv = tomllib.loads((root / "api" / "uv.lock").read_text(encoding="utf-8"))
    dev = {}
    for p in uv["package"]:
        dev.setdefault(p["name"], set()).add(p.get("version"))
    drift = {n: v for n, v in pins.items() if n in dev and v not in dev[n]}
    assert not drift, f"re-run scripts/release/lock-requirements.sh: {drift}"


def test_a_failed_install_leaves_nothing_half_installed(env, monkeypatch):
    home = env.parent / "home"
    monkeypatch.setattr(em, "sentence_transformers_available", lambda: False)

    def fail(target, environ):
        target.mkdir(parents=True)
        (target / "torch").mkdir()
        raise RuntimeError("Couldn't install the larger model's runtime. Check your connection and free space, then try again.")

    monkeypatch.setattr(em, "_pip_install", fail)
    em._run_install("hf_" + "x" * 30, {"CICADA_HOME": str(home)})
    assert em.JOB.snapshot()["state"] == "failed"
    assert not (home / "extras" / "site-packages.partial").exists()
    em.JOB._set(state="idle", step="", error="")


def test_the_choice_waits_for_a_running_drain(env, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main
    from api.services import sleep_cycle

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(env))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    monkeypatch.setattr(em, "is_available", lambda mid, environ=None: True)
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    monkeypatch.setattr(sleep_cycle.get_sleep_state(), "status", "running")
    try:
        with TestClient(main.app) as client:
            r = client.post("/embeddings/choice", json={"model": em.SMALL_ID})
        assert r.status_code == 409 and "Sleep" in r.json()["detail"]
    finally:
        config.get_settings.cache_clear()
