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

    /// Owner 2026-10-26: "Light, dark, or system; the default is system." Unknown or absent → System, so a person who
    /// never chose follows their Mac; a stored `"light"` / `"dark"` (the retired sidebar toggle's, or Settings') is an
    /// explicit choice and is kept on upgrade. Every `@AppStorage` of the key defaults to this value's raw string.
    static let defaultChoice: AppearancePreference = .system

    static func stored(_ raw: String?) -> AppearancePreference {
        raw.flatMap(Self.init(rawValue:)) ?? defaultChoice
    }

    /// The picker's order, left to right: the two explicit looks, then the one that follows the Mac.
    static let pickerOrder: [AppearancePreference] = [.light, .dark, .system]

    /// ← / → on the picker: the neighbour in `pickerOrder`, stopping at either end.
    static func stepped(_ from: AppearancePreference, by: Int) -> AppearancePreference {
        guard let at = pickerOrder.firstIndex(of: from) else { return from }
        return pickerOrder[min(max(at + by, 0), pickerOrder.count - 1)]
    }

    /// What a tile's hover says.
    var help: String {
        switch self {
        case .system: Copy.appearanceSystemHelp
        case .light: Copy.appearanceLightHelp
        case .dark: Copy.appearanceDarkHelp
        }
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
