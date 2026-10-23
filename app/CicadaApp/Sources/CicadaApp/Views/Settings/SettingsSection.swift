import Foundation

/// The Settings panel's sidebar rows. History: Track C's five replaced a four-tab `TabView`; G139 grew them to
/// fourteen; the Hyrum audit's B1 made eleven; ruling 36 D6 made six. R7 (binding): raw values are machine keys, never
/// display strings — `title` computes the display string from `Copy.*`.
///
/// Ruling 36 D6 (owner, 2026-10-22): Settings in six — General · You · Intelligence · Sleep · Devices · Privacy & data,
/// under 400 words. Sources and Agents became sidebar pages; Skills already was one. Every retired raw value keeps a
/// home (`retired`): a saved selection, a deep link, a palette recent or a search hit that named a gone page lands on
/// the row that inherited it, or on the page it became — never blank. `SettingsAnchorsTests` holds that.
enum SettingsSection: String, CaseIterable, Identifiable {
    // Declared in sidebar order. Raw values are machine keys (R7) and `@AppStorage("cicada.settingsSection")`'s
    // persisted identity: the five that survive keep theirs; `intelligence` is new.
    case general, you, intelligence, sleep, devices, privacy

    var id: String { rawValue }

    var title: String {
        switch self {
        case .general: Copy.general
        case .you: Copy.youSection
        case .intelligence: Copy.Intelligence.title
        case .sleep: Copy.sleepSettings
        case .devices: Copy.Devices.sidebar
        case .privacy: Copy.privacyAndData
        }
    }

    /// The page header's title — the sidebar's label (no page asks its own question since D6).
    var pageTitle: String { title }

    /// The header's second line. D6's word budget: none — the title is the page's whole introduction. Kept as a
    /// property (empty) so search, which matches it, needs no special case.
    var subtitle: String { "" }

    var icon: String {
        switch self {
        case .general: "gearshape"
        case .you: "person.crop.circle"
        case .intelligence: "cpu"
        case .sleep: "moon.zzz"
        case .devices: "laptopcomputer.and.iphone"
        case .privacy: "hand.raised"
        }
    }

    var group: SettingsGroup { .cicada }

    /// Maps a persisted `@AppStorage` raw value onto a section: `nil` (first launch), an unrecognized value, or a
    /// retired page that became a sidebar page all open General — the panel cannot show a page.
    static func restored(from raw: String?) -> SettingsSection {
        guard let raw else { return .general }
        if let section = SettingsSection(rawValue: raw) { return section }
        if case let .settings(section, _)? = retired[raw] { return section }
        return .general
    }

    /// Every retired section by its old raw value, with its new home: a row on a surviving section (whose anchor
    /// keeps the old page header's id where docs and harness scripts name it), or the sidebar page it became.
    ///
    /// - B1 (2026-10-22): Memory → Privacy's search row (its fade explainer became the page cards' "?", UI-B);
    ///   From anywhere → Devices; Plans & keys → Intelligence.
    /// - D6 (2026-10-22): Engines → Intelligence's In use row; Search & memory → Privacy's search row (its folders are
    ///   a source now); Integrations and Reading the web → the Sources page (per-site reading lives on sources);
    ///   Agents → the Agents page; Skills → the Skills page.
    static let retired: [String: SettingsHome] = [
        "memory": .settings(.privacy, .searchMeaning),
        "remote": .settings(.devices, .fromAnywhere),
        "plansAndKeys": .settings(.intelligence, .plansAndKeys),
        "engines": .settings(.intelligence, .engineChoice),
        "searchFiles": .settings(.privacy, .searchMeaning),
        "integrations": .page(.sources),
        "reading": .readingInBrowser,
        "agents": .page(.agents),
        "skills": .page(.skills),
    ]

    /// R-O11 — the retired "On this Mac / From anywhere" segment was persisted under `cicada.agentsMode`. A person who
    /// left Agents on "From anywhere" reopens where From anywhere lives now (Devices).
    static func restored(from raw: String?, legacyAgentsMode: String?) -> SettingsSection {
        restoredLanding(from: raw, legacyAgentsMode: legacyAgentsMode).section
    }

    /// Where the panel opens for a saved selection: the section, and the row a retired page became (nil for a page
    /// that still exists, which opens at its top as before).
    static func restoredLanding(from raw: String?, legacyAgentsMode: String?) -> (section: SettingsSection, row: SettingsRowID?) {
        if raw == "agents", legacyAgentsMode == "anywhere" { return (.devices, .fromAnywhere) }
        if let raw, case let .settings(section, row)? = retired[raw] { return (section, row) }
        return (restored(from: raw), nil)
    }
}

/// Where a retired Settings page lives now: a row on a surviving section, a sidebar page (D6), or the Sources page's
/// *Reading in your browser* sheet (Reading the web's switches, 2026-10-22 fix round).
enum SettingsHome: Equatable {
    case settings(SettingsSection, SettingsRowID?)
    case page(AppTab)
    case readingInBrowser

    /// The row a retired page's anchor became, when it became a row.
    var row: SettingsRowID? {
        if case let .settings(_, row) = self { return row }
        return nil
    }
}

/// The sidebar's heading. One since D6: six rows need no grouping, so the sidebar draws no label.
enum SettingsGroup: String, CaseIterable, Identifiable {
    case cicada

    var id: String { rawValue }
    var title: String { Copy.groupCicada }
    var sections: [SettingsSection] { SettingsSection.allCases.filter { $0.group == self } }
}
