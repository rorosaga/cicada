import AppKit
import CoreText

/// The bundled display face (G137, spec R-M3): Instrument Serif, SIL OFL 1.1,
/// registered with CoreText for this process at launch (`CicadaApp.init`).
///
/// **Why CoreText, not `ATSApplicationFontsPath`.** The Info.plist key would
/// need `bundle.sh` to copy the TTFs into `Contents/Resources` — a second
/// place the fonts live and a second layout to get wrong. Registering from
/// `Bundle.cicadaResources` reads them where every other resource lives.
///
/// **Why the bare `"fonts"` directory.** `Bundle.cicadaResource(_:ext:in:)`'s
/// docstring has the measurement: `bundle.sh` re-nests the resource bundle for
/// `codesign`, consuming the `Resources` path component, so a
/// `"Resources/fonts"` lookup resolves under `swift test` and fails in every
/// shipped app — the PR #70 bug.
///
/// **A missing font is not an error.** SwiftUI falls back to the system face
/// for an unknown PostScript name, so a bundle that lost its fonts renders SF
/// titles, not blank ones. `registerBundled` therefore never throws; it
/// reports which faces it made available, and `CicadaFontsTests` holds it to
/// that in both bundle layouts. `CicadaTheme.displayFont` is the only code
/// that names these faces (`FontLiteralLintTests`).
enum CicadaFonts {
    static let displayRegular = "InstrumentSerif-Regular"
    static let displayItalic = "InstrumentSerif-Italic"
    static let all = [displayRegular, displayItalic]
    static let directory = "fonts"

    /// Registers every bundled display face in `bundle` (process scope) and
    /// returns the PostScript names that were FOUND in that bundle and
    /// resolve afterwards. Idempotent: a second registration of the same file
    /// fails with `kCTFontManagerErrorAlreadyRegistered` (105, measured), and
    /// the name still resolves, so it is reported.
    @discardableResult
    static func registerBundled(in bundle: Bundle = .cicadaResources) -> [String] {
        all.filter { name in
            guard let url = bundle.cicadaResource(name, ext: "ttf", in: directory) else { return false }
            var error: Unmanaged<CFError>?
            if !CTFontManagerRegisterFontsForURL(url as CFURL, .process, &error) {
                // 105 is benign. Anything else leaves the name unresolved and
                // the check below says so — the title degrades to SF.
                _ = error?.takeRetainedValue()
            }
            return NSFont(name: name, size: 12) != nil
        }
    }
}
