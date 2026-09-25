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
/// that answers "who does Cicada's thinking". `remote` (A1) is From anywhere,
/// promoted out of Agents' segmented picker so it can be deep-linked and
/// searched like any other section.
///
/// O4 — the Cicada group gains You (the owner, G117), Privacy & data (what
/// stays on this Mac and how to take it away), and Memory (the derived index
/// and the link backfill); Advanced closes Engines & keys. New cases only, so
/// every persisted raw value still restores (K1).
///
/// O5 — Skills (G138) closes Customize: what your agents can add, installed
/// only by the agent's own installer after consent (R-O26).
enum SettingsSection: String, CaseIterable, Identifiable {
    // Declared in sidebar order — `SettingsGroup.sections` filters this list,
    // and `SettingsKitTests` pins that the groups read it back unchanged.
    case general, you, privacy, memory, sleep, integrations, agents, remote, skills, engines, plansAndKeys, advanced

    var id: String { rawValue }

    var title: String {
        switch self {
        case .general: Copy.general
        case .you: Copy.youSection
        case .privacy: Copy.privacyAndData
        case .memory: Copy.memorySection
        case .sleep: Copy.sleepSettings
        case .integrations: Copy.integrations
        case .agents: Copy.agents
        case .remote: Copy.fromAnywhere
        case .skills: Copy.skills
        case .engines: Copy.engines
        case .plansAndKeys: Copy.plansAndKeys
        case .advanced: Copy.advanced
        }
    }

    /// The header's second line (design §2.1) — and a search field at 0.4.
    var subtitle: String {
        switch self {
        case .general: Copy.generalSubtitle
        case .you: Copy.youSubtitle
        case .privacy: Copy.privacySubtitle
        case .memory: Copy.memorySubtitle
        case .sleep: Copy.sleepSettingsSubtitle
        case .integrations: Copy.integrationsSubtitle
        case .agents: Copy.agentsSubtitle
        case .remote: Copy.remoteSubtitle
        case .skills: Copy.skillsSubtitle
        case .engines: Copy.enginesSubtitle
        case .plansAndKeys: Copy.plansAndKeysSubtitle
        case .advanced: Copy.advancedSubtitle
        }
    }

    var icon: String {
        switch self {
        case .general: "gearshape"
        case .you: "person.crop.circle"
        case .privacy: "hand.raised"
        case .memory: "books.vertical"
        case .sleep: "moon.zzz"
        case .integrations: "puzzlepiece.extension"
        case .agents: "cable.connector"
        case .remote: "dot.radiowaves.left.and.right"
        case .skills: "sparkles"
        case .engines: "cpu"
        // K4: `creditcard` read as a price on a page that must never show one.
        case .plansAndKeys: "key.horizontal"
        case .advanced: "wrench.and.screwdriver"
        }
    }

    var group: SettingsGroup {
        switch self {
        case .general, .you, .privacy, .memory, .sleep: .cicada
        case .integrations, .agents, .remote, .skills: .customize
        case .engines, .plansAndKeys, .advanced: .enginesAndKeys
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

    /// R-O11 — the retired "On this Mac / From anywhere" segment was persisted
    /// under `cicada.agentsMode`. A person who left Agents on "From anywhere"
    /// reopens on the row that inherited it; everything else restores as before.
    static func restored(from raw: String?, legacyAgentsMode: String?) -> SettingsSection {
        let section = restored(from: raw)
        return section == .agents && legacyAgentsMode == "anywhere" ? .remote : section
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
