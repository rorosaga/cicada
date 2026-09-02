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
}
