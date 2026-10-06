# Releasing Cicada

How a version of Cicada gets from `dev` to a tester's Mac (G182). Plan and rulings:
[`docs/plans/2026-10-05-g182-releases.md`](plans/2026-10-05-g182-releases.md).

**Two channels.** `dev` is the developer channel: the owner's Mac follows it through `scripts/dev/auto-update.sh`, and
every build from a checkout (`make dev`, `make install-app`) is a *developer build* that never updates itself. `main`
holds only releases (TODO ruling 19): **a release is a pull request from `dev` to `main`, and merging it is the
release.** CI then tags `vX.Y.Z` at the merge commit, builds, verifies and publishes the GitHub Release. Nobody tags by
hand. Installed release apps update themselves from it.

**`VERSION` is the one version.** It is plain semver (`0.4.0`), and everything that stamps a version must equal it:
`api/pyproject.toml`, uv.lock's `cicada-api` entry, the app's `CFBundleShortVersionString` (stamped by `bundle.sh`),
the tag, the release title (`Cicada X.Y.Z`) and `latest.json`. `scripts/release/check_version.py` is the one judge —
CI, the release PR check and `make release` all ask it — and any disagreement fails the run.

## Cut a release (owner)

1. **Check `dev` is ready.** Suites green (`api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`,
   `cd app/CicadaApp && swift test`), and the last dry run green (below). Optional: `make release-app` builds the
   installable app on this Mac and smoke-tests it in a temp folder; it installs nothing.
2. **Bump the version: `make release VERSION=x.y.z`.** It works in a temporary worktree — your checkout is never
   switched — and bumps `VERSION`, `api/pyproject.toml` and uv.lock's project line on a `release/vx.y.z` branch off
   `origin/dev`, shows what it will push and asks, then pushes that branch and opens a PR to `dev` titled
   `chore(release): x.y.z`. It refuses a version that already has a tag or is not greater than the latest one. Use
   the next minor (`0.4.0`) for features, the next patch (`0.3.1`) for fixes. Merge that PR into `dev` as usual. If
   `dev` already says the version you want (the first release: `VERSION` is 0.3.0 and nothing is tagged), there is
   nothing to bump — skip to step 3.
3. **Open the release PR: `make release-pr`.** It opens `dev` → `main` titled `Release vX.Y.Z`, refusing a version
   that is already released (and pointing at the PR when one is already open). The **Release PR** check
   (`.github/workflows/release-check.yml`) fails the PR unless its head is this repo's `dev`, every version stamp
   agrees, and `VERSION` is untagged and greater than the latest tag.
4. **Merge it with *Create a merge commit*.** That is the release. (A squash or rebase would give `main` commits `dev`
   does not have, and the next release PR would carry them back.)
5. **Watch CI:** `gh run watch $(gh run list --workflow=release.yml -L1 --json databaseId -q '.[0].databaseId')`.
   About 10 minutes. Then send testers the install line (next section). Installed apps pick the release up within six
   hours, or at once from Cicada → Check for Updates….

Both commands take `--dry-run` (`scripts/release/release.sh bump x.y.z --dry-run`, `… pr --dry-run`): every check, no
push, no PR. Neither ever pushes `main`, creates a tag or force-pushes.

## What CI does on `main`

`.github/workflows/release.yml` runs on every push to `main`, one run at a time (`concurrency: release`; a running
release is never cancelled, though a run still *waiting* is replaced by a newer push to `main`, which carries the same
or a newer `VERSION`):

1. **Plan** (ubuntu, seconds). Every version stamp agrees; then the remote's `v*` tags decide. `v$VERSION` already
   tagged → "already released", nothing is built or published, and the run is **green** (so re-running a merge, or a
   merge that carries no bump, is harmless). `VERSION` not greater than the latest tag → the run **fails**.
   Otherwise it releases, and the new release becomes "latest".
2. **Build** (`macos-26`, arm64, Xcode 26): `bundle.sh --release --with-backend` with the commit count as the build
   number → the app's `CFBundleShortVersionString` checked against `VERSION` → `smoke-test.sh` in a temp folder (its
   `/healthz` must report `VERSION` too) → zip → Ed25519 signature (checked against the committed public key) →
   `latest.json` (checked against `VERSION`) → `Cicada-macos-arm64.zip`, the same bytes under a name that never
   changes. Uploaded as a run artifact.
3. **Publish** (ubuntu, the only job with write access; `scripts/release/publish.sh`): judges `VERSION` again against
   the live tags (a re-run reuses the plan job's answer, and a newer release may exist by then), then creates the
   GitHub Release as a **draft** at the merged commit, titled `Cicada X.Y.Z`, with `Cicada-X.Y.Z.zip`, its `.sig`, `latest.json` and
   `Cicada-macos-arm64.zip`; notes are a fixed header (Apple silicon, macOS 14+, not notarized yet → Open Anyway; the
   install line) followed by notes generated from the PRs merged since the previous tag. It checks every asset's name
   and size, and only then publishes the draft — which is when GitHub creates the tag.

**The website's download link** is `https://github.com/rorosaga/cicada/releases/latest/download/Cicada-macos-arm64.zip`:
it always resolves to the newest release, so no release needs a website edit.

**A failed run advertises nothing.** A build or verification failure stops before the publish job: no tag, no release.
A publish failure deletes the draft it made (a draft has no tag yet, so no tag is touched). A published release is never edited,
re-uploaded to or deleted, and nothing force-pushes. **To recover**, fix the cause on `dev`, then either re-run the
failed run (*Re-run all jobs*, or *Re-run failed jobs* — both judge the version again), or run the Release workflow by
hand on `main` (Actions → Release → Run workflow → `main`), which
re-attempts publishing the untagged `VERSION`. If the fix changed code, merge it into `dev` and run `make release-pr`
again: the version is still untagged, so merging that PR releases it. A draft left behind by a cancelled run is never
public; the next run replaces it.

**A hotfix for an older line** (after a newer release exists) is never published by CI and never becomes "latest", or
every app would be offered a downgrade: CI fails a `VERSION` that isn't greater than the latest tag. Build it with a
dry run and publish it by hand with `gh release create … --latest=false` (an owner decision, case by case).

**Dry run without releasing:** push any commit to `ci/release-dry-run` (`git push -f origin HEAD:ci/release-dry-run`)
or run the workflow from the Actions tab on any branch but `main`. It builds, smoke-tests and signs, and uploads the
zip, `.sig`, `latest.json` and the stable-name zip as an artifact — nothing is published, whatever the tags say.

## What testers run

Apple silicon (M1 or later), macOS 14 or later. In Terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/main/scripts/install-release.sh | bash
```

It finds the latest release, downloads the zip with `curl`, checks its sha256 against `latest.json` and its signature
with `codesign --verify`, puts Cicada.app in `~/Applications` (or `/Applications`), moves an older copy to the Trash,
and opens it. Files `curl` downloads carry no quarantine flag, so macOS opens the app without asking even though it is
not notarized yet.

**From the browser instead:** download `Cicada-macos-arm64.zip` (or `Cicada-x.y.z.zip`, the same file) from the
Releases page, unzip it, drag Cicada into Applications and open it. Because a browser marks the download as quarantined and the app isn't notarized yet, macOS
refuses the first time ("Apple could not verify…"). Open **System Settings → Privacy & Security**, scroll to Security,
click **Open Anyway** next to Cicada, and confirm. (Control-click → Open no longer bypasses this on macOS 15 and later.)
Once a Developer ID is in place this step disappears.

**Where things live on a tester's Mac:** the app in `~/Applications/Cicada.app`; memory in `~/cicada/memory`; Cicada's
own files in `~/.cicada` (the launchers in `~/.cicada/bin`, logs in `~/.cicada/logs` — `backend.log`, `update.log` —,
the bytecode cache in `cache/pycache`, the optional larger search model's runtime in `extras/` and weights in
`models/`, and the updater's one-shot notes `update-failed.json` / `update-deferred.json`). Agents and hooks run `~/.cicada/bin/cicada-*`, which the app re-points at
itself each time it opens, so moving or updating the app never breaks them.

**Updates.** A release app checks GitHub's latest release on launch and every six hours while Settings → General →
*Install updates automatically* is on (the default). It downloads the new zip, verifies its sha256 and its Ed25519
signature against the key built into the app, and installs it when you quit (or at once with *Restart to update*):
the old copy goes to the Trash, the background service is restarted on the new copy. A failed install keeps the old
app and says why. With the switch off, Cicada never checks on its own; Cicada → Check for Updates… still does.
Developer builds never update themselves.

**Search model.** A fresh install searches by meaning with the small model built into the app. Settings → Memory →
Search model offers the larger one (EmbeddingGemma): about 2 GB, installed into `~/.cicada`, downloaded once with the
tester's own Hugging Face token (they accept the model's license there first). Each memory keeps the model it was
built with.

## Before the first release (owner)

- `VERSION` already says 0.3.0 and nothing is tagged, so the first release needs no bump: `make release-pr`, then merge.
- `main` trails `dev` but its own commits are old promotion merges, so the release PR merges cleanly.
- The dry runs so far were pushed to `ci/release-dry-run`; that branch is deleted after use and recreated by the next
  `git push -f origin HEAD:ci/release-dry-run`.

## The update signing key

An Ed25519 keypair. The private key is the repo secret `CICADA_UPDATE_SIGNING_KEY` (PEM, PKCS#8) and the owner's
backup at `~/.cicada/release/update-signing-key.pem` (mode 0600); the public key is
`scripts/release/update-public-key.txt` (raw 32 bytes, base64), stamped into each release app as
`CicadaUpdatePublicKey`. **Never commit or print the private key.**

To rotate it (only if it leaks): generate a new pair, `gh secret set CICADA_UPDATE_SIGNING_KEY <
new-key.pem`, commit the new public key, and cut a release **signed with the old key** that carries the new public key
— an installed app only trusts the key it was built with. Then the next release can be signed with the new key.

## Adding a Developer ID and notarization later

Without a Developer ID, builds are signed ad hoc — inside out, never with `--deep` — so the move is small:

1. **Enrol** in the Apple Developer Program (99 USD/yr; an individual can; the legal name shows as the developer).
   As Account Holder, create a **Developer ID Application** certificate; export it as a `.p12`.
2. **CI secrets:** `MACOS_CERT_P12` (base64 of the `.p12`), `MACOS_CERT_PASSWORD`, and for notarization an App Store
   Connect API key: `NOTARY_KEY_ID`, `NOTARY_ISSUER_ID`, `NOTARY_KEY_P8` (base64).
3. **Sign with it:** in `release.yml`, import the certificate into a temporary keychain (`security create-keychain`,
   `security import … -T /usr/bin/codesign`, `security set-key-partition-list`), and set
   `CICADA_SIGN_IDENTITY: "Developer ID Application: <Name> (<TEAMID>)"` on the build step. `sign-app.sh` then adds
   `--options runtime` (the hardened runtime) and `--timestamp` to every Mach-O, and `--entitlements
   scripts/release/Cicada.entitlements` to the app and the executables inside it (the interpreter, git).
4. **Entitlements** (`scripts/release/Cicada.entitlements`) start from what embedded Python needs:
   `com.apple.security.cs.allow-unsigned-executable-memory` (ctypes, onnxruntime) and
   `com.apple.security.cs.disable-library-validation` (the optional search model installs packages into
   `~/.cicada/extras`, not signed by your Team ID). Remove the second if that download is ever dropped. Check them
   against the first `notarytool` log; add `com.apple.security.cs.allow-jit` only if the log asks.
5. **Notarize and staple** after signing, before zipping:
   ```sh
   ditto -c -k --keepParent Cicada.app notarize.zip
   xcrun notarytool submit notarize.zip --key AuthKey.p8 --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER_ID" --wait
   xcrun stapler staple Cicada.app
   ```
   then zip the stapled app for the release (so an offline first launch works). `notarytool log <id>` lists every file
   Apple rejected.
6. **If notarization objects to code under `Contents/Resources`,** move `backend/` to `Contents/Frameworks/` (or
   `Contents/Helpers/`) and update `CicadaRuntime.bundledBin` and the launcher target; the layout is otherwise the
   same. Python apps built with Briefcase and py2app notarize with signed code under `Resources`, so try as is first.
7. Optionally a `.dmg` (`hdiutil create`, signed and notarized too) and a Homebrew cask — both only after signing,
   since Homebrew quarantines every cask download.

After that, a browser download opens without *Open Anyway*, and the curl line keeps working unchanged.
