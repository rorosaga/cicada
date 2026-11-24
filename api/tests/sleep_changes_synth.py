"""A synthetic run shaped like the measured one (owner 2026-11-24): one main commit touching thousands of entity files,
nearly all of them bookkeeping alone — the decay watermark moved on every claim, confidence also moved on a share of
them (silence), a few pages with only frontmatter stamps, and a handful changed in substance. Synthetic names only.
Used by the changes tests and by the speed measurement (``python -m`` from a scratch script)."""
from __future__ import annotations

import subprocess

from api.services import claims, claims_ledger, markdown_parser

DAY_BEFORE, DAY = "2026-10-01", "2026-10-02"


def _git(repo, *args, stdin=None):
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True, input=stdin).stdout


def claim_entry(page: str, i: int, *, decayed=DAY_BEFORE, confidence=0.8, text=None, **more) -> dict:
    return {"id": f"{page}-c{i}", "text": text or f"{page} fact {i}", "subject": page, "predicate": "relates-to",
            "object": f"thing-{i}", "object_kind": "literal", "observer": "agent", "context": "general",
            "epistemic": "explicit", "source_trust": "agent_extracted", "confidence": confidence,
            "valid_from": "2026-09-01", "valid_to": None, "superseded_by": None, "supersedes": None,
            "recorded_at": "2026-09-01", "source_episodes": ["ep_2026-09-01_000"], "premises": [],
            "authored_by": "model-a", "origin": None, "session_id": None, "session_ids": [],
            "decayed_through": decayed, **more}


def page_text(page: str, entries: list[dict], *, prose: str = "A short paragraph about it.", **fm) -> tuple[dict, str]:
    frontmatter = {"id": page, "name": page.replace("-", " ").title(), "type": "concept", "status": "active",
                   "confidence": 0.8, "created": "2026-09-01", "last_referenced": DAY_BEFORE,
                   "decayed_through": DAY_BEFORE, "learned_on": DAY_BEFORE, "version": 1,
                   "source_episodes": ["ep_2026-09-01_000"], **fm}
    body = prose + "\n\n```claims\n" + "\n".join(claims._jsonl_line(e) for e in entries) + "\n```"
    return frontmatter, body


def write_page(memory, page: str, entries: list[dict], **kw) -> None:
    fm, body = page_text(page, entries, **kw)
    markdown_parser.write(memory / "entities" / f"{page}.md", fm, body)


def big_run(tmp_path, *, pages: int = 2000, per_page: int = 3, faded_every: int = 7, substance: int = 5,
            stamp_only: int = 3, big_ledger: bool = False, ledger_claims: int = 40):
    """``(memory, commit)``: a bank with ``pages`` pages and one commit (subject ``Sleep cycle … (batch 1 of 1)``, a
    manifest line a page) that moved ``decayed_through`` on every claim, ``confidence`` on every ``faded_every``-th
    page, only the stamps on ``stamp_only`` more, and changed ``substance`` pages in substance (a fact withdrawn, a fact
    added, a prose line, a changed end date, a new alias). ``big_ledger`` makes the first page one whose claims overflowed
    into its ledger file, bookkeeping moving in the ledger."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    ids = [f"page-{i:04d}" for i in range(pages)]
    for i, pid in enumerate(ids):
        write_page(memory, pid, [claim_entry(pid, k) for k in range(per_page)])
    ledger_lines: list[str] = []
    if big_ledger:
        pid = ids[0]
        kept = [claim_entry(pid, k) for k in range(per_page)]
        old = [claim_entry(pid, 100 + k) for k in range(ledger_claims)]
        ledger_lines = [claims._jsonl_line(e) for e in old]
        fm, body = page_text(pid, kept)
        fm["claims_ledger"] = {"claims": len(old), "hash": claims_ledger._stamp(ledger_lines)[0]["hash"]}
        (memory / "entities" / f"{pid}.md").write_text(
            "---\n" + _yaml(fm) + "---\n\n" + body + "\n", encoding="utf-8")
        (memory / "entities" / f"{pid}{claims_ledger.SUFFIX}").write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "base")
    manifest = []
    for i, pid in enumerate(ids):
        faded = i % faded_every == 0
        entries = [claim_entry(pid, k, decayed=DAY, confidence=0.5 if faded else 0.8) for k in range(per_page)]
        extra = {}
        if i < substance:
            kind = i % 5
            if kind == 0:
                entries = entries[:-1]                                   # a fact withdrawn
            elif kind == 1:
                entries.append(claim_entry(pid, 99, decayed=DAY))        # a fact added
            elif kind == 2:
                entries[0]["valid_to"] = "2026-09-30"                    # a fact's end
            elif kind == 3:
                extra["aliases"] = ["An Alias"]
        prose = "A short paragraph about it." + (" And a new line." if i < substance and i % 5 == 4 else "")
        stamp = {"decayed_through": DAY, "last_referenced": DAY, "learned_on": DAY, "version": 2}
        fm, body = page_text(pid, entries, prose=prose, **{**stamp, **extra},
                             **({"confidence": 0.5} if faded else {}))
        if i == 0 and big_ledger:
            old = [claim_entry(pid, 100 + k, decayed=DAY, confidence=0.5) for k in range(ledger_claims)]
            new_lines = [claims._jsonl_line(e) for e in old]
            fm["claims_ledger"] = {"claims": len(old), "hash": claims_ledger._stamp(new_lines)[0]["hash"]}
            (memory / "entities" / f"{pid}{claims_ledger.SUFFIX}").write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            (memory / "entities" / f"{pid}.md").write_text("---\n" + _yaml(fm) + "---\n\n" + body + "\n", encoding="utf-8")
        elif i >= pages - stamp_only:
            fm2, body2 = page_text(pid, [claim_entry(pid, k) for k in range(per_page)], **stamp)
            markdown_parser.write(memory / "entities" / f"{pid}.md", fm2, body2)
        else:
            markdown_parser.write(memory / "entities" / f"{pid}.md", fm, body)
        manifest.append(f"entities/{pid}.md: updated (source: n/a, trigger: sleep/decay)")
    _git(memory, "add", "-A")
    message = "Sleep cycle 2026-10-02 (batch 1 of 1)\n\n" + "\n".join(manifest) + "\n"
    # The message goes in on stdin: 2,000 manifest lines as one argument is past Linux's 128 KB limit for a single
    # argument (E2BIG), which a Mac does not have.
    _git(memory, "commit", "-q", "-F", "-", stdin=message)
    return memory, _git(memory, "rev-parse", "HEAD").strip()


def _yaml(fm: dict) -> str:
    import yaml

    return yaml.dump(fm, default_flow_style=False, sort_keys=False)
