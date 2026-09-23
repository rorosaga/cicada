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
///
/// G139 (Settings v3) — each section now also knows its `subtitle` (the
/// detail header's second line) and its `group` (the sidebar heading it sits
/// under); the raw values did not move, so a saved selection survives.
/// `engines` (A3) is new and sits first under Engines & keys: the one page
/// that answers "who does Cicada's thinking".
enum SettingsSection: String, CaseIterable, Identifiable {
    // Declared in sidebar order — `SettingsGroup.sections` filters this list,
    // and `SettingsKitTests` pins that the groups read it back unchanged.
    case general, sleep, integrations, agents, engines, plansAndKeys

    var id: String { rawValue }

    var title: String {
        switch self {
        case .general: Copy.general
        case .sleep: Copy.sleepSettings
        case .integrations: Copy.integrations
        case .agents: Copy.agents
        case .engines: Copy.engines
        case .plansAndKeys: Copy.plansAndKeys
        }
    }

    /// The header's second line (design §2.1) — and a search field at 0.4.
    var subtitle: String {
        switch self {
        case .general: Copy.generalSubtitle
        case .sleep: Copy.sleepSettingsSubtitle
        case .integrations: Copy.integrationsSubtitle
        case .agents: Copy.agentsSubtitle
        case .engines: Copy.enginesSubtitle
        case .plansAndKeys: Copy.plansAndKeysSubtitle
        }
    }

    var icon: String {
        switch self {
        case .general: "gearshape"
        case .sleep: "moon.zzz"
        case .integrations: "puzzlepiece.extension"
        case .agents: "cable.connector"
        case .engines: "cpu"
        // K4: `creditcard` read as a price on a page that must never show one.
        case .plansAndKeys: "key.horizontal"
        }
    }

    var group: SettingsGroup {
        switch self {
        case .general, .sleep: .cicada
        case .integrations, .agents: .customize
        case .engines, .plansAndKeys: .enginesAndKeys
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

/// The sidebar's three headings (spec decision 17): what Cicada is, what you
/// plug into it, and who does its thinking. Data, not layout — the sidebar and
/// the search results both read it.
enum SettingsGroup: String, CaseIterable, Identifiable {
    case cicada, customize, enginesAndKeys

    var id: String { rawValue }

    var title: String {
        switch self {
        case .cicada: Copy.groupCicada
        case .customize: Copy.groupCustomize
        case .enginesAndKeys: Copy.groupEnginesAndKeys
        }
    }

    var sections: [SettingsSection] { SettingsSection.allCases.filter { $0.group == self } }
}
