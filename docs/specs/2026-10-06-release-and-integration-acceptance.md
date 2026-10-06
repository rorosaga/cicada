# G182 — Working releases today, website access and every integration

**Owner direction, 2026-10-06:** GitHub releases must work today, automatically synchronized with `main` so the website can link them. When the CLI/server package is ready, publish tested install commands on the website and make access from different agent harnesses easy. Test every integration after consolidation: agents must actually use the memory and be able to contribute.

[G182](../goals/memory-evolution.md#g182) owns release/main/website delivery; [G76](../goals/memory-evolution.md#g76) and G10 own client acceptance; G180/G181/G187 own CLI/package/platform delivery; G158 owns the separate website. The full [client matrix](../goals/TODO.md#client-trial-matrix--support-must-be-demonstrated) is the execution checklist. Only documentation was changed here: no release, tag, branch promotion, website publish, consolidation or external-client test has been performed.

## Today: a release people can download and use

The current [release workflow](../../.github/workflows/release.yml) builds on a version tag and publishes the zip, signature and update manifest. [RELEASING.md](../RELEASING.md) describes the current manually initiated promotion/tag process and signing limitations. Existing workflow code is a foundation; the dated October 6 listing had no published release.

Completion requires:

1. Publish an actual versioned GitHub Release containing the supported app/backend artifact, verification materials and usable notes. Resolve applicable integrity, packaging and release checks. Record actual supported OS/architecture and Developer ID/notarization status; missing optional distribution polish must not be described as shipped.
2. Download the public artifact through the same route a new person uses; verify integrity, installation, launch, backend lifecycle, agent registration, ordinary recall and an attributed write. Check the update path against a real installed prior artifact when available; record an untested first-release update scenario explicitly.
3. Make the website's download link resolve to the correct published asset, with version/platform and setup instructions matching that artifact. Inspect the actual website repository before claiming this is implemented. Verify from the public link, not a local build or CI-only artifact.
4. Execute the integration matrix below against the release build after an actual consolidation. Keep each unsupported/blocked route visible with its cause and fallback; incomplete matrix coverage cannot be reported as “every integration works.”

The deadline is **2026-10-06**, an owner delivery priority rather than evidence that any of these outcomes is already complete.

## Automatic release, main and website alignment

The owner now requests automatic synchronization. This is a release-scoped amendment to older manual-only delivery sketches. Implementation remains on `dev`, with PRs targeting `dev`; design an explicit release trigger/version selection that automates the approved promotion/tag/build/publication sequence and website/update references.

- Make the release version, source revision on `main`, tag, built artifact and update manifest agree. Define the trigger, prerequisite checks, concurrency/idempotence and clear failure states; reject an artifact/tag that points to an unrelated source revision.
- A failed build/verification/publication must not advertise a new downloadable or updatable version. Specify recovery for partially completed promotion/tag/publication and rollback behavior without overwriting existing released assets or force-pushing branch history.
- Keep website “latest supported release” and app update metadata on the same verified release. A stable asset link or generated release metadata is acceptable if it is tested; automate subsequent updates so each release does not depend on a manual website edit. Older-line hotfixes must not replace latest accidentally.
- This request does not define every `dev` push as a production release. Choose and document the release-specific automation in the implementation plan, updating the current release instructions and any affected branch-policy rail together when implemented.

## Later: installation commands and easy harness access

Add this as a completion slice of G182/G158 when G180/G181/G187 provide actual supported installation:

- Copyable, verified CLI/server install commands for the routes that really ship (brew, curl, package or container as selected), platform requirements, update/uninstall/service instructions and an app-free option. Label native Windows versus WSL based on G187 acceptance.
- A short “Connect your agent” chooser covering every supported harness: shell CLI plus portable skill when available, local MCP for compatible desktop/CLI clients, and the scoped remote connector for web/phone/server use. Configuration/setup should use the same G50 capability contract; avoid asking people to reconstruct URLs, commands and scopes from several developer documents.
- Run fresh install → connect → read consolidated fixture memory → attributed contribution on each advertised route. A successful package install, copied config or connected status alone does not establish usable Cicada access. Keep unavailable automatic capture/continuity capabilities explicit.

Publish commands only after testing them against released artifacts; a proposed package name or installation method is not a working command.

## Every-integration post-consolidation protocol

Enumerate all catalog harnesses: **Claude Code, Codex, Cursor, Claude Desktop, ChatGPT, Grok, OpenCode, Hermes, OpenClaw and Gemini CLI**. Test Claude web and ChatGPT desktop/web separately where supported. Enumerate the actual iPhone apps/accounts/routes tested; mobile support cannot be inferred from a desktop result. Reconcile the checklist against the catalog whenever an integration is added/removed. Provider engines such as local/key-backed models have separate engine execution acceptance under G50/G122/G148.

Use an isolated synthetic bank and the supported current connection path. Run real consolidation first, then for **each client/route**:

1. Open a fresh session with no answer-containing recap. Discover Cicada, recall a known consolidated fact/relationship and answer with inspectable evidence. Ask an absent-fact question to check unsupported assertions.
2. Make an allowed contribution through the production interface with true actor/session provenance. Verify the bank/evidence/owned commit, then retrieve that contribution in another fresh session, preferably another client. If a new episode needs Sleep, consolidate it before judging semantic availability; distinguish direct claim visibility from episode processing.
3. Correct or withdraw a contribution through the permitted author/user path; verify historical attribution and current versus superseded knowledge. Check the active bank and that denied write/source scopes or revoked credentials do not leak words or mutate memory.
4. Check deterministic capture and startup/rollover continuity separately where supported. MCP read/write does not establish a Stop hook or automatic session continuation. G110 acceptance still requires no manual handoff prompt and no Sleep prerequisite for working-context continuity.

For every route record **PASS / FAIL / BLOCKED / UNSUPPORTED**, date, release/build, OS/client version, account availability, connection/setup method and generic reproduction evidence. Keep recall/use, contribution/persistence, source scopes, automatic capture and continuity as separate results. Unsupported operations are absent or intelligibly unavailable; do not mark them as passing tests. Public documentation contains no personal question text, private handles, thread titles, credentials or bank facts.

Unresolved issues feed their existing IDs: setup/capability G50/G76/G135, continuation G110, provenance G118, source/video G61/G22/G162, ingestion G179/G188 and integrity G183/G104. [G148's rebuilt benchmark](2026-10-06-system-benchmark-rebuild.md) measures consolidation/performance; it complements real-client acceptance rather than replacing it.
