import Foundation

extension Bundle {
    /// The app's SwiftPM resource bundle, found **next to the executable first**.
    ///
    /// SwiftPM's generated `Bundle.module` looks in `Bundle.main.bundleURL/
    /// CicadaApp_CicadaApp.bundle` (i.e. `Cicada.app/CicadaApp_CicadaApp.bundle`,
    /// which `bundle.sh` never creates — the bundle lives in `Contents/MacOS/`)
    /// and then falls back to the absolute **build** path under the developer's
    /// `~/Documents`. On a debug build launched by LaunchServices that fallback
    /// is the first thing the app touches, and macOS answers with a "Cicada
    /// would like to access files in your Documents folder" prompt that blocks
    /// the main thread inside `GraphView.makeNSView` — no window, no menu-bar
    /// item, nothing to click. Seen for real on 2026-09-02 after every
    /// re-signed `make dev` (an ad-hoc signature is a new TCC identity, so the
    /// prompt returns each build). Launching from a terminal hid the bug: the
    /// child inherits the terminal's Full Disk Access.
    ///
    /// Resolving relative to `executableURL` never leaves the app bundle, so
    /// the prompt cannot fire. `Bundle.module` stays as the fallback for
    /// `swift test` (where the executable is the test runner) and for any
    /// layout this helper does not know.
    static let cicadaResources: Bundle = {
        if let exe = Bundle.main.executableURL {
            let beside = exe.deletingLastPathComponent().appendingPathComponent("CicadaApp_CicadaApp.bundle")
            if let bundle = Bundle(url: beside) { return bundle }
        }
        return Bundle.module
    }()

    /// One bundled resource, addressed by the directory it sits in under
    /// `Sources/CicadaApp/Resources/` — `"logos"`, `"walkthroughs"` — and
    /// found in **both** layouts this bundle ships in.
    ///
    /// The layout is not one thing, and that is the whole bug. SwiftPM emits a
    /// FLAT bundle whose root holds the copied `Resources/` directory, so
    /// `resourceURL` is `<bundle>/Resources` and CFBundle's second search
    /// location, `<bundle>/…`, makes the redundant prefix `"Resources/logos"`
    /// resolve there anyway. `bundle.sh` then RE-NESTS that bundle for
    /// `codesign` (`mv Resources Contents/Resources`, so a `.bundle` with no
    /// `Info.plist` cannot make it refuse to sign the app): `resourceURL`
    /// becomes `<bundle>/Contents/Resources`, the `Resources` path component
    /// is consumed by the move, and `"Resources/logos"` matches nothing under
    /// either search location. Measured on the installed app —
    /// `urls(forResourcesWithExtension: "png", subdirectory: "Resources/logos")`
    /// returned 0 there and 27 for `"logos"`, while `swift test` runs against
    /// the flat layout where both work, which is why every asset test passed
    /// over a shipped app that could not find a single mark.
    ///
    /// Passing the bare directory is what works in both, so every caller goes
    /// through here rather than spelling a prefix that is true of only one
    /// build.
    ///
    /// **The empty-name guard is load-bearing** and lives here so it covers
    /// every caller: Foundation resolves an EMPTY resource name to the FIRST
    /// matching file in the directory (measured: `""` + `png` + `logos`
    /// answers `rss.png`), and callers that take a mark whenever *either* rung
    /// exists pass `logoName ?? ""` — which would draw an unrelated brand.
    func cicadaResource(_ name: String, ext: String, in directory: String) -> URL? {
        guard !name.isEmpty else { return nil }
        return url(forResource: name, withExtension: ext, subdirectory: directory)
    }

    /// Every bundled resource of one extension in one `Resources/` directory,
    /// under the same both-layouts rule as `cicadaResource`. `[]`, never nil,
    /// so a caller cannot mistake "no such directory" for "the bundle is fine".
    func cicadaResources(ext: String, in directory: String) -> [URL] {
        urls(forResourcesWithExtension: ext, subdirectory: directory) ?? []
    }
}
