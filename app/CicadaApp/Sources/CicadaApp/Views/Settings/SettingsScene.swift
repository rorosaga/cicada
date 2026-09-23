import SwiftUI

/// The native Settings window — ⌘, and the sidebar's footer gear (G68 §1).
///
/// Track C: a `NavigationSplitView` sidebar over `SettingsSection`, replacing
/// the old four-tab `TabView` — five sections now that Integrations (G126)
/// joins General, Sleep, Agents and Plans & keys. Every section is setup, not
/// workspace: you visit it once and then rarely again, but a sidebar scales
/// to a fifth row better than a `TabView`'s row of tab items does, and it
/// gives Integrations room to grow its own categorized list without
/// squeezing the tab bar.
///
/// `selection` mirrors `sectionRaw` rather than binding `List` directly to
/// the `@AppStorage` string — `SettingsSection.restored(from:)` needs to run
/// once on appear so a retired/bogus persisted value falls back to
/// `.general` (the same tolerant-restore shape `AppTab.restored(from:)`
/// already uses for the main sidebar) instead of `List` selecting nothing.
///
/// G139 — grouped sidebar over `SettingsGroup`, glyphs that acknowledge
/// hover, and one `SettingsFocus` handed to every page: a pointer, a search
/// hit or a deep link asks the focus, and this scene applies the section and
/// lands the row.
///
/// G139 (O2) — the sidebar starts with a search field. Typing filters the
/// sections to those with matches, badges each with its count, and swaps the
/// detail pane for `SettingsResultsView`; picking a result (or Return on the
/// top hit) lands on the row. The index is `SettingsIndex` over `QuickMatch`,
/// rebuilt from the snapshots this window already holds — never a fetch.
struct SettingsScene: View {
    @AppStorage("cicada.settingsSection") private var sectionRaw = SettingsSection.general.rawValue
    /// G139 (R-O15) — the row half of a deep link; read here, written only by
    /// `SettingsSectionLink`.
    @AppStorage("cicada.settingsRowFocus") private var rowSeed = ""
    @AppStorage(ThemeStore.defaultsKey) private var appearanceRaw = AppearancePreference.dark.rawValue
    @State private var selection: SettingsSection = .general

    @State private var focus = SettingsFocus()
    /// Skills' data (G138) lives here, not in the page, so search can index
    /// the recommended skills while another section is showing.
    @State private var skillsVM = SkillsViewModel()
    @State private var query = ""
    /// Picking a sidebar row after typing shows that section (with its
    /// matches barred); typing again brings the results back (design §2.4).
    @State private var pickedSinceTyping = false
    @State private var lastSeed: SettingsRowFocusSeed.Seed?
    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// Names and ids only feed the index (never a command).
    private let agents = AgentSetupCatalog.all(home: BackendProcess.installRoot().path)

    private var entries: [SettingsEntry] {
        SettingsIndex.pageEntries + SettingsIndex.staticEntries + SettingsIndex.dynamicEntries(
            channels: store.channels.value ?? [],
            harnessRows: IntegrationHarnessRows.rows(from: store.sourcesOverview.value ?? []),
            exportOnly: IntegrationsView.exportOnlyTiles,   // the page's own list, never a retyped copy
            connections: store.connections.value ?? [],
            agents: agents,
            skills: skillsVM.all)
    }
    private var trimmedQuery: String { query.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var hits: [SettingsHit] { SettingsIndex.search(trimmedQuery, in: entries) }
    private var showingResults: Bool { !trimmedQuery.isEmpty && !pickedSinceTyping }
    private var liveInputs: SettingsLiveValue.Inputs {
        var inputs = SettingsLiveValue.Inputs()
        inputs.scheduleMode = sleepVM.schedule.mode
        inputs.appearance = AppearancePreference.stored(appearanceRaw)
        inputs.uiScale = CicadaTheme.uiScale
        inputs.connections = store.connections.value ?? []
        return inputs
    }

    /// `nil` while the results page shows, so no sidebar row claims the detail
    /// pane; `selection` itself stays non-optional, so the `@AppStorage`
    /// mirror below is untouched (design §2.4).
    private var sidebarSelection: Binding<SettingsSection?> {
        Binding(get: { showingResults ? nil : selection },
                set: { if let section = $0 { selection = section; pickedSinceTyping = true } })
    }

    var body: some View {
        let hits = self.hits
        let counts = SettingsIndex.counts(hits)
        NavigationSplitView {
            List(selection: sidebarSelection) {
                ForEach(SettingsGroup.allCases) { group in
                    let sections = group.sections.filter { trimmedQuery.isEmpty || counts[$0, default: 0] > 0 }
                    if !sections.isEmpty {
                        Section(group.title) {
                            ForEach(sections) { section in
                                SettingsSidebarLabel(section: section,
                                                     isSelected: selection == section && !showingResults,
                                                     badge: trimmedQuery.isEmpty ? 0 : counts[section, default: 0])
                                    .tag(section)
                            }
                        }
                    }
                }
                if !trimmedQuery.isEmpty && hits.isEmpty {
                    Text(Copy.noSettingsMatch(trimmedQuery))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .selectionDisabled()
                }
            }
            .navigationSplitViewColumnWidth(min: CicadaTheme.scaled(180),
                                            ideal: CicadaTheme.scaled(210),
                                            max: CicadaTheme.scaled(240))
        } detail: {
            Group {
                if showingResults {
                    SettingsResultsView(query: trimmedQuery, hits: hits,
                                        liveValue: { SettingsLiveValue.text(for: $0.id, liveInputs) },
                                        open: open)
                } else {
                    detailView
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(CicadaTheme.background)
        }
        .searchable(text: $query, placement: .sidebar, prompt: Copy.searchSettings)
        .onSubmit(of: .search) { if let top = hits.first { open(top.entry) } }
        .onChange(of: query) { _, _ in
            pickedSinceTyping = false
            focus.matchedRows = trimmedQuery.isEmpty ? [] : Set(self.hits.map(\.entry.anchor))
        }
        .environment(focus)
        .environment(skillsVM)
        .task { await skillsVM.load() }
        .frame(minWidth: Self.windowWidth, minHeight: Self.windowHeight)
        .onAppear {
            selection = SettingsSection.restored(from: sectionRaw,
                                                 legacyAgentsMode: UserDefaults.standard.string(forKey: "cicada.agentsMode"))
            UserDefaults.standard.removeObject(forKey: "cicada.agentsMode")   // read once (R-O11)
            consumeRowSeed()
        }
        .onChange(of: selection) { _, newValue in sectionRaw = newValue.rawValue }
        // recent-work #9 — `onAppear` fires once per view lifetime, and this
        // is a separate window that is usually ALREADY open when
        // `EmptyStateView`'s "Open Integrations" seeds the key. Mirroring the
        // stored value back onto `selection` makes the pair symmetric: the
        // `onChange(of: selection)` above writes, this one reads.
        .onChange(of: sectionRaw) { _, raw in selection = SettingsSection.restored(from: raw) }
        // R-O15 — a deep link into an already-open window changes the row
        // seed after the section seed; land on it the same way.
        .onChange(of: rowSeed) { _, _ in consumeRowSeed() }
        // G139 — every in-window landing (pointer, search hit, deep link)
        // arrives here as a nonce'd request, so the same section twice still
        // re-lands.
        .onChange(of: focus.request) { _, request in apply(request) }
    }

    private func open(_ entry: SettingsEntry) {
        pickedSinceTyping = true
        focus.go(entry.section, row: entry.anchor)
    }

    private func apply(_ request: SettingsFocus.Request?) {
        guard let request else { return }
        selection = request.section
        guard let row = request.row else { return }
        // VoiceOver hears where it landed: "Sleep, Runs", not just "Sleep".
        let name = SettingsIndex.entry(for: row, in: entries).map { "\(request.section.title), \($0.title)" }
            ?? request.section.title
        focus.land(on: row, announcing: name, reduceMotion: reduceMotion)
    }

    /// New AND fresh only (R-O15): the key outlives the window in
    /// UserDefaults, so without both checks every relaunch — and every
    /// re-render that re-reads it — would land on an old row again.
    private func consumeRowSeed() {
        guard let seed = SettingsRowFocusSeed.parse(rowSeed), seed != lastSeed,
              SettingsRowFocusSeed.isFresh(seed) else { return }
        lastSeed = seed
        focus.go(SettingsSection.restored(from: sectionRaw), row: seed.row)
    }

    /// G130 — every font and spacing token inside this window scales with
    /// `CicadaTheme.uiScale`, so a fixed frame clips at the top of
    /// `ThemeStore.scaleRange` (1.4). `minWidth`/`minHeight` rather than a
    /// hard `frame` so the person can still make the window bigger.
    static var windowWidth: CGFloat { CicadaTheme.scaled(900) }
    static var windowHeight: CGFloat { CicadaTheme.scaled(640) }

    @ViewBuilder private var detailView: some View {
        switch selection {
        case .general: SettingsGeneralView()
        case .you: YouView()
        case .privacy: PrivacyView()
        case .memory: MemoryView()
        case .sleep: SettingsSleepView()
        case .integrations: IntegrationsView()
        case .agents: ConnectView()
        case .remote: FromAnywhereView()
        case .skills: SkillsView()
        case .engines: EnginesView()
        case .plansAndKeys: ConnectionsView()
        case .advanced: AdvancedView()
        }
    }
}

/// A sidebar row: the section's glyph acknowledges the pointer once (M1's
/// `iconHover`, design §2.5) and bounces when the row becomes selected.
///
/// While a query is active the row carries its match count as a native
/// sidebar badge, and VoiceOver reads it as a value (design §2.4).
private struct SettingsSidebarLabel: View {
    let section: SettingsSection
    let isSelected: Bool
    var badge: Int = 0
    @State private var hovering = false

    var body: some View {
        Label {
            Text(section.title)
        } icon: {
            Image(systemName: section.icon).iconHover(hovering: hovering, selected: isSelected)
        }
        .badge(badge)
        .accessibilityValue(badge > 0 ? Copy.matchingSettings(badge) : "")
        .onHover { hovering = $0 }
    }
}
