# Releasing Cicada

How a version of Cicada gets from `dev` to a tester's Mac (G182). Plan and rulings:
[`docs/plans/2026-10-05-g182-releases.md`](plans/2026-10-05-g182-releases.md).

**Two channels.** `dev` is the developer channel: the owner's Mac follows it through `scripts/dev/auto-update.sh`, and
every build from a checkout (`make dev`, `make install-app`) is a *developer build* that never updates itself. A
**release** is a promotion of `dev` to `main`, a `vX.Y.Z` tag, and a GitHub Release built by CI. Installed release
apps update themselves from it.

## Cut a release (owner)

1. **Check `dev` is ready.** Suites green (`api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`,
   `cd app/CicadaApp && swift test`), and the last dry run green (below). Optional: `make release-app` builds the
   installable app on this Mac and smoke-tests it in a temp folder; it installs nothing.
2. **Run `make release VERSION=x.y.z`.** It works in a temporary worktree — your checkout is never switched — and:
   bumps `VERSION`, `api/pyproject.toml` and uv.lock's project line on `dev`; merges `dev` into `main` ("Release
   vX.Y.Z"); tags `vX.Y.Z`; shows what it will push and asks; then pushes dev, main and the tag in one atomic push.
   `scripts/release/release.sh x.y.z --dry-run` does everything but push. Use the next minor (`0.4.0`) for features,
   the next patch (`0.3.1`) for fixes; the first release is `0.3.0` (`make release VERSION=0.3.0` publishes the
   version already in `VERSION`).
3. **Watch CI:** `gh run watch $(gh run list --workflow=release.yml -L1 --json databaseId -q '.[0].databaseId')`.
   The tag runs `.github/workflows/release.yml` on `macos-26`: build with the backend → smoke test in a temp folder →
   zip → Ed25519 signature (checked against the committed public key) → `latest.json` → a GitHub Release with
   generated notes, `Cicada-x.y.z.zip`, its `.sig` and `latest.json`. About 10 minutes.
4. **Send testers the install line** (next section). Installed apps pick the release up within six hours, or at once
   from Cicada → Check for Updates….

**A hotfix for an older line** (after a newer release exists) must not become "latest", or every app would be offered
it: publish it with `gh release create … --latest=false` by hand.

**Dry run without releasing:** push any commit to `ci/release-dry-run` (`git push -f origin HEAD:ci/release-dry-run`)
or run the workflow from the Actions tab. It builds, smoke-tests and signs, and uploads the zip, `.sig` and
`latest.json` as an artifact — nothing is published.

## What testers run

Apple silicon (M1 or later), macOS 14 or later. In Terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/main/scripts/install-release.sh | bash
```

It finds the latest release, downloads the zip with `curl`, checks its sha256 against `latest.json` and its signature
with `codesign --verify`, puts Cicada.app in `~/Applications` (or `/Applications`), moves an older copy to the Trash,
and opens it. Files `curl` downloads carry no quarantine flag, so macOS opens the app without asking even though it is
not notarized yet.

**From the browser instead:** download `Cicada-x.y.z.zip` from the Releases page, unzip it, drag Cicada into
Applications and open it. Because a browser marks the download as quarantined and the app isn't notarized yet, macOS
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

- `make release VERSION=0.3.0` — `VERSION` is already 0.3.0, so it promotes `dev` as is (no bump commit).
- The dry runs so far were pushed to `ci/release-dry-run`; that branch is deleted after use and recreated by the next
  `git push -f origin HEAD:ci/release-dry-run`.
- Promotion merges are `--no-ff`, so `main`'s history shows each release as one merge.

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
