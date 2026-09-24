import Foundation

/// Round-4 decision 6 (F-10, R-HO16) — Settings → General → Show in menu bar: whether the bookworm sits in the menu bar.
/// Per viewer, on by default. Hiding it never strands Cicada: the app keeps its Dock icon (`.regular` activation,
/// `CicadaApp.init`), so a closed window is always one click away.
enum MenuBarPreference {
    static let defaultsKey = "cicada.menuBar.visible"

    static func isVisible(_ defaults: UserDefaults = .standard) -> Bool {
        defaults.object(forKey: defaultsKey) as? Bool ?? true
    }
}
