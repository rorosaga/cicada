import Foundation

/// What the person chose in Settings → General → Appearance (G139, R-O4) —
/// distinct from `AppColorScheme`, which stays the RESOLVED two-value mode
/// every token, the window chrome, the Meadow art and graph.js's palette twin
/// paint from. Persisted under the `cicada.colorScheme` key the sidebar's
/// sun/moon toggle has always written, so `"light"`/`"dark"` decode exactly as
/// before and only `"system"` is new.
enum AppearancePreference: String, CaseIterable, Identifiable {
    case system, light, dark

    var id: String { rawValue }

    var label: String {
        switch self {
        case .system: Copy.appearanceSystem
        case .light: Copy.appearanceLight
        case .dark: Copy.appearanceDark
        }
    }

    /// Unknown or absent → dark: the app's original look, and the default
    /// `ThemeStore` has always had.
    static func stored(_ raw: String?) -> AppearancePreference {
        raw.flatMap(Self.init(rawValue:)) ?? .dark
    }

    func resolved(systemIsDark: Bool) -> AppColorScheme {
        switch self {
        case .light: .light
        case .dark: .dark
        case .system: systemIsDark ? .dark : .light
        }
    }

    /// macOS writes `AppleInterfaceStyle = Dark` into the global domain in Dark
    /// Mode and removes it in Light. Read through `defaults` so a test can
    /// inject a suite and no `NSApp` is touched in a headless run.
    static func systemIsDark(_ defaults: UserDefaults = .standard) -> Bool {
        defaults.string(forKey: "AppleInterfaceStyle") == "Dark"
    }

    /// Posted (distributed) when the system appearance flips.
    static let systemChangedNotification = Notification.Name("AppleInterfaceThemeChangedNotification")
}
