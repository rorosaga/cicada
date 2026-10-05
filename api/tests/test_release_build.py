"""G182 — the release build's invariants, read from the scripts (nothing is built here).

The developer environment keeps sentence-transformers and torch (the owner's bank uses
EmbeddingGemma); the release set is pyproject's list without them, so a fresh install
carries no torch. Signing is inside out and never `--deep`.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release"


def _names(lines) -> set[str]:
    out = set()
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(re.split(r"[<>=!~\[ ;]", line, 1)[0].lower().replace("_", "-"))
    return out


def test_the_release_set_is_pyproject_without_torch():
    project = tomllib.loads((ROOT / "api" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dev = _names(project["dependencies"])
    release = _names((RELEASE / "requirements.in").read_text(encoding="utf-8").splitlines())
    assert "sentence-transformers" in dev, "the developer environment keeps it (owner, 2026-10-05)"
    assert dev - {"sentence-transformers"} <= release, "every other runtime dependency ships"
    assert not {"sentence-transformers", "torch", "transformers"} & release
    assert {"onnxruntime", "tokenizers", "numpy", "certifi"} <= release


def test_the_lock_is_hashed_and_torch_free():
    lock = (RELEASE / "requirements.lock").read_text(encoding="utf-8")
    pins = re.findall(r"^([A-Za-z0-9_.-]+)==", lock, re.M)
    assert pins and lock.count("--hash=sha256:") >= len(pins)
    assert not {p.lower() for p in pins} & {"torch", "sentence-transformers", "transformers"}
    assert "/var/folders" not in lock and "/tmp/" not in lock


def test_the_lock_keeps_the_developer_locks_versions():
    """Ruling 3: where the two sets overlap, the release runs what the developer lock runs."""
    lock = (RELEASE / "requirements.lock").read_text(encoding="utf-8")
    release = {n.lower().replace("_", "-"): v for n, v in re.findall(r"^([A-Za-z0-9_.-]+)==([^ \\\n]+)", lock, re.M)}
    uv = tomllib.loads((ROOT / "api" / "uv.lock").read_text(encoding="utf-8"))
    dev: dict[str, set[str]] = {}
    for p in uv["package"]:
        if "version" in p:  # a package can be forked per platform marker (numpy is): any locked version counts
            dev.setdefault(p["name"].lower().replace("_", "-"), set()).add(p["version"])
    drift = {n: (v, sorted(dev[n])) for n, v in release.items() if n in dev and v not in dev[n]}
    assert not drift, f"re-run scripts/release/lock-requirements.sh: {drift}"


def test_build_backend_never_bundles_untracked_files_or_torch():
    script = (RELEASE / "build-backend.sh").read_text(encoding="utf-8")
    assert "git ls-files" in script and "^api/\\.env" in script, "a person's api/.env can never ride along"
    assert "--require-hashes" in script and "--only-binary :all:" in script
    assert "for banned in torch sentence_transformers transformers" in script
    assert "enable_load_extension(True)" in script, "sqlite-vec needs loadable extensions"
    assert "PYTHONPYCACHEPREFIX" in script, "nothing is written inside the signed app"


def test_inputs_are_pinned_by_hash():
    inputs = (RELEASE / "inputs.env").read_text(encoding="utf-8")
    for key in ("PBS_SHA256", "GIT_SHA256", "GIT_COPYING_SHA256"):
        assert re.search(rf'^{key}="[0-9a-f]{{64}}"$', inputs, re.M), key
    assert re.search(r'^MODEL_REVISION="[0-9a-f]{40}"$', inputs, re.M)
    assert len(re.findall(r":[0-9a-f]{64}\"?$", inputs, re.M)) == 3


def test_signing_is_inside_out_and_never_deep():
    script = (RELEASE / "sign-app.sh").read_text(encoding="utf-8")
    signing = [l for l in script.splitlines() if l.strip().startswith("codesign") and "--verify" not in l]
    assert signing and not any("--deep" in l for l in signing)
    assert "--options runtime" in script and "Cicada.entitlements" in script
    bundle = (ROOT / "app" / "CicadaApp" / "bundle.sh").read_text(encoding="utf-8")
    assert "--with-backend" in bundle and "plutil -replace CicadaDistribution -string release" in bundle
    assert "scripts/release/sign-app.sh" in bundle


def test_the_predicate_seed_ships_inside_api():
    from api.services import predicates

    assert predicates._SEED_PATH == ROOT / "api" / "data" / "predicates-seed.yaml"
    assert predicates._SEED_PATH.is_file()
