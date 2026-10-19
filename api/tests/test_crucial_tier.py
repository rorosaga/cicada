"""The crucial tier holds (owner 2026-10-19): every line of the backend and Swift lists names a test that exists, so a
renamed or deleted test cannot silently drop a rail out of the daily run; and the rails that are a number are pinned
here, where the tier always runs them."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from api.tests import _crucial

SWIFT_TESTS = _crucial.SWIFT_LIST.parent / "CicadaAppTests"


def _defined(tree: ast.Module) -> set[tuple[str, ...]]:
    names: set[tuple[str, ...]] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add((node.name,))
        elif isinstance(node, ast.ClassDef):
            names.add((node.name,))
            for inner in node.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add((node.name, inner.name))
    return names


def test_every_backend_line_names_a_test_that_exists():
    entries = _crucial.backend_entries()
    assert len(entries) >= 50, "the list was read"
    missing = []
    for file, path in entries:
        source = _crucial.TESTS / file
        if not source.is_file():
            missing.append(file)
            continue
        if path and path not in _defined(ast.parse(source.read_text(encoding="utf-8"))):
            missing.append("::".join((file, *path)))
    assert not missing, f"crucial.txt names tests that do not exist: {missing}"


def test_every_swift_line_names_a_test_that_exists():
    sources = {p.stem: p.read_text(encoding="utf-8") for p in SWIFT_TESTS.glob("*.swift")}
    everything = "\n".join(sources.values())
    entries = _crucial.lines(_crucial.SWIFT_LIST)
    assert len(entries) >= 20, "the list was read"
    missing = []
    for line in entries:
        cls, _, method = line.partition("/")
        found = re.search(rf"\bclass {re.escape(cls)}\s*:", everything)
        if not found:
            missing.append(line)
            continue
        if method:
            body = everything[found.end():]
            nxt = re.search(r"\n(?:final )?class \w+\s*:", body)
            body = body[: nxt.start()] if nxt else body
            extensions = "".join(m.group(0) for m in re.finditer(
                rf"extension {re.escape(cls)}\b.*?(?=\n(?:final )?class |\nextension |\Z)", everything, re.S))
            if not re.search(rf"func {re.escape(method)}\s*\(", body + extensions):
                missing.append(line)
    assert not missing, f"crucial-tests.txt names tests that do not exist: {missing}"


def test_the_swift_filter_matches_a_class_whole_and_a_method_alone():
    pattern = re.compile(_crucial.swift_filter())
    assert pattern.search("CicadaAppTests.UpdateVerifierTests/testAWrongHashIsRefused")
    assert pattern.search("CicadaAppTests.StoreTests/testNotModifiedKeepsExistingValue")
    assert not pattern.search("CicadaAppTests.StoreTests/testEntityCacheIsMemoised")
    assert not pattern.search("CicadaAppTests.PictureStoreTests/testNotModifiedKeepsExistingValue")


def test_the_marker_lands_on_what_the_list_names(request):
    assert request.node.get_closest_marker("crucial") is not None


@pytest.mark.parametrize("module, name, bound", [
    ("api.services.handshake", "MAX_TOKENS", 1800),          # the handshake is <= 1,800 tokens
    ("api.services.link_enrichment", "FETCH_TIMEOUT_S", 4),  # the ToS rail: 4 s
    ("api.services.link_enrichment", "FETCH_MAX_BYTES", 512 * 1024),  # the ToS rail: <= 512 KB
])
def test_the_rails_that_are_numbers_hold(module, name, bound):
    import importlib

    assert 0 < getattr(importlib.import_module(module), name) <= bound
