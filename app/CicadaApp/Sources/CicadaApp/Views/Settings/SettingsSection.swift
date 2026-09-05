import Foundation

/// The Settings scene's five sidebar rows (Track C — replacing the old
/// four-tab `TabView` with a `NavigationSplitView`, adding the new
/// Integrations section for G126 alongside G122's engine picker on Sleep).
///
/// R7 (binding): raw values are machine keys, never the display string —
/// `case plansAndKeys` (implicit raw value `"plansAndKeys"`), NOT a case
/// whose raw value retypes `Copy.plansAndKeys`'s own display string. Two
/// reasons: `CopyConstantsTests`'s `testNoViewRetypesAPointerLiteral` bans
/// that literal outside `Copy.swift` itself, and a raw value doubles as
/// `@AppStorage("cicada.settingsSection")`'s
/// persisted identity — coupling it to a *display* string means a future
/// Copy rename (this task alone renamed "Schedule" to "Sleep") would either
/// break a saved selection or force a silent identity migration. `title`
/// computes the display string from `Copy.*` instead, so the two can move
/// independently.
enum SettingsSection: String, CaseIterable, Identifiable {
    case general, sleep, integrations, agents, plansAndKeys

    var id: String { rawValue }

    var title: String {
        switch self {
        case .general: Copy.general
        case .sleep: Copy.sleepSettings
        case .integrations: Copy.integrations
        case .agents: Copy.agents
        case .plansAndKeys: Copy.plansAndKeys
        }
    }

    var icon: String {
        switch self {
        case .general: "gearshape"
        case .sleep: "moon.zzz"
        case .integrations: "puzzlepiece.extension"
        case .agents: "cable.connector"
        case .plansAndKeys: "creditcard"
        }
    }

    /// Maps a persisted `@AppStorage` raw value onto a section, the same
    /// tolerant-restore shape `AppTab.restored(from:)` already established
    /// for the main sidebar — `nil` (first launch) or an unrecognized value
    /// (a retired case, or a future rename) both fall back to `.general`
    /// rather than trapping the reader on a section that no longer exists.
    static func restored(from raw: String?) -> SettingsSection {
        guard let raw, let section = SettingsSection(rawValue: raw) else {
            return .general
        }
        return section
    }
}
