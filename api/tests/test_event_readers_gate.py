"""R-PJ3 / M12: every module that reads closed claims says what an event is.

A module that calls `parse_claims(` (or reads the FTS claim payload) AND looks
at `valid_to`/`superseded_by` must call `is_event(` or `is_record(`, or be named
below with the reason it may not."""
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
READS = re.compile(r"parse_claims\(|claims_about\(|_lexical_claims|claim_subject_hits")
CLOSED = re.compile(r"valid_to|superseded_by")
KNOWS = re.compile(r"\bis_event\(|\bis_record\(|_is_history\(")
EXEMPT = {
    "api/services/claims.py": "defines is_event/is_record",
    "api/services/agentic_write.py": "a writer; refuses event predicates (§5.1)",
    "api/services/progress.py": "the event writer",
    "api/services/claim_expiry.py": "a writer; never reads `target`, only expected_end/due",
    "api/services/claim_seeder.py": "a writer of fresh claims",
    "api/services/decay_watermark_migration.py": "one-shot migration over open claims",
    "api/services/graph_builder.py": "current-only: _claim_edge_row drops closed and literal claims",
    "api/services/transclusion_resolver.py": "current-only (_is_valid)",
    "api/services/vector_index.py": "indexes open claims only",
    "api/services/logo_service.py": "current-only",
    "api/services/papers.py": "writes its own external claims",
    "api/services/inbox_service.py": "a resolver: closes the claims a question names",
}
HISTORY_READERS = ("api/services/mcp_tools.py", "api/routers/claims.py", "api/services/provenance.py",
                   "api/services/search_service.py", "api/services/search_index.py")


def _modules():
    for root in (REPO / "api", REPO / "mcp"):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".venv", "tests", "__pycache__"}]
            for name in filenames:
                if name.endswith(".py"):
                    path = Path(dirpath) / name
                    yield path.relative_to(REPO).as_posix(), path.read_text(encoding="utf-8")


def test_every_closed_claim_reader_knows_events():
    offenders = [rel for rel, text in _modules()
                 if READS.search(text) and CLOSED.search(text) and not KNOWS.search(text) and rel not in EXEMPT]
    assert offenders == [], offenders


def test_the_named_history_readers_call_is_event():
    texts = dict(_modules())
    assert [r for r in HISTORY_READERS if "is_event(" not in texts[r] and "_is_history(" not in texts[r]] == []


def test_the_gate_found_what_it_exists_for():
    found = {rel for rel, text in _modules() if READS.search(text) and CLOSED.search(text)}
    assert set(HISTORY_READERS) <= found | {"api/services/search_index.py"}
