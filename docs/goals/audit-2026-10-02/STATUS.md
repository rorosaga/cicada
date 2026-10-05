# Audit 2026-10-02 — fix status

Revalidated on `dev` `efd5386e` (2026-10-05); see the README's revalidation table for the evidence.

| ID | Revalidation | Fix | PR |
|---|---|---|---|
| A01 | confirmed | **fixed** — revision-checked retirement under `episode_lock` | #168 |
| A02 | confirmed | **fixed** — temp file + fsync + `os.replace` | #168 |
| K01 | confirmed | **fixed** — `create_episode` (hard-link, never replaces) + `episode_lock` for dedup | #168 |
| A03 | confirmed (static) | open | — |
| A04 | confirmed | open | — |
| A05/A06 | confirmed (static) | open | — |
| A07 | confirmed | open | — |
| A08 | confirmed (static) | open | — |
| A09 | confirmed | open | — |
| A10 | confirmed (static) | open | — |
| A11 | confirmed (static) | open | — |
| A12 | gone (fixed by G176) | nothing to do | — |

The A02 probe in `repros/storage.py` now uses an implementation-independent fault (an unencodable body):
on `efd5386e` it prints `old_file_preserved: false, bytes_remaining: 0`; on PR #168, `true`.
