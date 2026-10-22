import Foundation

/// The Settings panel's sidebar rows: eleven since the Hyrum audit's B1 (2026-10-22). The first five were Track C's,
/// replacing the old four-tab `TabView`.
///
/// R7 (binding): raw values are machine keys, never the display string —
/// `case searchFiles` (implicit raw value `"searchFiles"`), NOT a case
/// whose raw value retypes its own display string. Two
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
/// and the link backfill); Advanced closed Engines & keys until 2026-10-22. New cases only, so
/// every persisted raw value still restores (K1).
///
/// G166 — Reading the web sits after Integrations in Customize: which sites the person's own agent may read for them and
/// how it reads them. A new case only, so every persisted raw value still restores.
///
/// Settings defaults (owner, 2026-10-22): Advanced is gone — the backend's status, the MCP command, the token's path,
/// the environment switches and the settings file were technical values nobody sets here. A saved `"advanced"` raw value
/// no longer names a case, so `restored(from:)` opens General, as it does for any retired section.
///
/// Hyrum audit B1 (2026-10-22): fourteen sections became eleven. Memory's one card (*How things fade*) joined Search &
/// files, now *Search & memory*; From anywhere joined Devices, now *Devices & access*; Plans & keys joined Engines. The
/// three retired raw values are `retired` below: a saved selection, a deep link or a search hit that named one opens
/// its new home on the row that inherited it, never General and never blank. `SettingsAnchorsTests` holds that.
///
/// O5 — Skills (G138) closes Customize: what your agents can add, installed
/// only by the agent's own installer after consent (R-O26).
///
/// Search & files (owner, 2026-10-14) sits between Privacy & data and Memory: the folders Cicada keeps and how well
/// search understands what it finds, in one place. Its sidebar label is short ("Search & files"); its page title is
/// the question it answers ("What Cicada can look through") — `pageTitle`. A new case only, so every persisted raw
/// value still restores.
enum SettingsSection: String, CaseIterable, Identifiable {
    // Declared in sidebar order — `SettingsGroup.sections` filters this list,
    // and `SettingsKitTests` pins that the groups read it back unchanged.
    case general, you, privacy, searchFiles, sleep, integrations, reading, agents, devices, skills, engines

    var id: String { rawValue }

    var title: String {
        switch self {
        case .general: Copy.general
        case .you: Copy.youSection
        case .privacy: Copy.privacyAndData
        case .searchFiles: Copy.SearchFiles.sidebar
        case .sleep: Copy.sleepSettings
        case .integrations: Copy.integrations
        case .reading: Copy.Reading.pageTitle
        case .agents: Copy.agents
        case .devices: Copy.Devices.sidebar
        case .skills: Copy.skills
        case .engines: Copy.engines
        }
    }

    /// The page header's title: the sidebar's label, except where the page asks its own question (Search & files).
    var pageTitle: String {
        switch self {
        case .searchFiles: Copy.SearchFiles.pageTitle
        default: title
        }
    }

    /// The header's second line (design §2.1) — and a search field at 0.4.
    var subtitle: String {
        switch self {
        case .general: Copy.generalSubtitle
        case .you: Copy.youSubtitle
        case .privacy: Copy.privacySubtitle
        case .searchFiles: Copy.SearchFiles.subtitle
        case .sleep: Copy.sleepSettingsSubtitle
        case .integrations: Copy.integrationsSubtitle
        case .reading: Copy.Reading.pageSubtitle
        case .agents: Copy.agentsSubtitle
        case .devices: Copy.Devices.subtitle
        case .skills: Copy.skillsSubtitle
        case .engines: Copy.enginesSubtitle
        }
    }

    var icon: String {
        switch self {
        case .general: "gearshape"
        case .you: "person.crop.circle"
        case .privacy: "hand.raised"
        case .searchFiles: "doc.text.magnifyingglass"
        case .sleep: "moon.zzz"
        case .integrations: "puzzlepiece.extension"
        case .reading: "globe"
        case .agents: "cable.connector"
        case .devices: "laptopcomputer.and.iphone"
        case .skills: "sparkles"
        case .engines: "cpu"
        }
    }

    var group: SettingsGroup {
        switch self {
        case .general, .you, .privacy, .searchFiles, .sleep: .cicada
        case .integrations, .reading, .agents, .devices, .skills: .customize
        case .engines: .enginesAndKeys
        }
    }

    /// Maps a persisted `@AppStorage` raw value onto a section, the same
    /// tolerant-restore shape `AppTab.restored(from:)` already established
    /// for the main sidebar — `nil` (first launch) or an unrecognized value
    /// (a retired case, or a future rename) both fall back to `.general`
    /// rather than trapping the reader on a section that no longer exists.
    static func restored(from raw: String?) -> SettingsSection {
        guard let raw else { return .general }
        return SettingsSection(rawValue: raw) ?? retired[raw]?.section ?? .general
    }

    /// Hyrum audit B1 (2026-10-22): a section that merged into another, by its old raw value, with the row on the new
    /// page that inherited it, whose anchor is the old header's (`page:<raw>`, which docs and harness scripts name).
    /// Read by `restored(from:)` and `restoredLanding(from:legacyAgentsMode:)` (a saved `cicada.settingsSection`).
    static let retired: [String: (section: SettingsSection, row: SettingsRowID)] = [
        "memory": (.searchFiles, .memoryGroup),
        "remote": (.devices, .fromAnywhere),
        "plansAndKeys": (.engines, .plansAndKeys),
    ]

    /// R-O11 — the retired "On this Mac / From anywhere" segment was persisted
    /// under `cicada.agentsMode`. A person who left Agents on "From anywhere"
    /// reopens where From anywhere lives now (Devices & access, since B1); everything else restores as before.
    static func restored(from raw: String?, legacyAgentsMode: String?) -> SettingsSection {
        restoredLanding(from: raw, legacyAgentsMode: legacyAgentsMode).section
    }

    /// Where the panel opens for a saved selection: the section, and the group a retired page became (nil for a page
    /// that still exists, which opens at its top as before).
    static func restoredLanding(from raw: String?, legacyAgentsMode: String?) -> (section: SettingsSection, row: SettingsRowID?) {
        if raw == SettingsSection.agents.rawValue, legacyAgentsMode == "anywhere" { return (.devices, .fromAnywhere) }
        if let raw, let moved = retired[raw] { return (moved.section, moved.row) }
        return (restored(from: raw), nil)
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
