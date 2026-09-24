import SwiftUI

/// Settings, as a panel inside the main window (DR-33; the owner, 2026-09-23: "a window inside
/// the app, like the one in claude desktop app"). It replaced the `Settings{}` scene.
///
/// **What survives the move.** Everything the scene did:
/// - the G139 groups (Cicada · Customize · Engines & keys);
/// - `SettingsIndex` over `QuickMatch` (the palette's one ranker, so Settings and ⌘K never rank
///   one name two ways);
/// - `SettingsResultsView`;
/// - `SettingsFocus`'s select → scroll → wash → announce landing;
/// - the remembered section.
///
/// **What it stopped needing.** The panel lives in the SAME window as everything that opens it,
/// so three things went:
/// - the cross-window `UserDefaults` seeds (R-DS22);
/// - `SettingsLink`;
/// - a second environment list and a second `.preferredColorScheme`.
///
/// **Layout.** 880 × 620 at 1×, inset ≥ 40 pt, `radiusLarge`, a floating surface over the panel
/// scrim. The sidebar is `bgPane`, 220 pt, and starts with a `CicadaSearchField`. The detail
/// keeps each page's own header, with an `esc` keycap and a close × at its top-right.
///
/// **Modal (R-DS21).** The shell under it is inert. ⌘K waits. Esc closes it through the close
/// control's `.cancelAction`, which is a visible control's shortcut, never a hidden one.
struct SettingsPanel: View {
    @AppStorage("cicada.settingsSection") private var sectionRaw = SettingsSection.general.rawValue
    @AppStorage(ThemeStore.defaultsKey) private var appearanceRaw = AppearancePreference.dark.rawValue
    /// Round-4 D4 — the Scene row's live value in search results.
    @AppStorage(HeroScenePreference.defaultsKey) private var heroSceneRaw = HeroScenePreference.automatic.rawValue
    @State private var selection: SettingsSection = .general
    @State private var focus = SettingsFocus()
    /// Skills' data (G138) lives here, not in the page, so search can index the recommended
    /// skills while another section is showing.
    @State private var skillsVM = SkillsViewModel()
    @State private var query = ""
    /// Picking a sidebar row after typing shows that section; typing again brings the results back.
    @State private var pickedSinceTyping = false
    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(AppRouter.self) private var router
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// Names and ids only feed the index (never a command).
    private let agents = AgentCatalog.all

    // Carried over unchanged from the retired scene — the index is the same index.
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
        inputs.heroScene = .stored(heroSceneRaw)
        inputs.uiScale = CicadaTheme.uiScale
        inputs.connections = store.connections.value ?? []
        return inputs
    }

    var body: some View {
        GeometryReader { geo in
            let size = SettingsPanelLayout.size(container: geo.size)
            ZStack {
                CicadaTheme.scrimPanel
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture { router.closeSettings() }
                    .accessibilityHidden(true)
                HStack(spacing: 0) {
                    sidebar
                        .frame(width: CicadaTheme.scaled(SettingsPanelLayout.sidebarWidth))
                        .frame(maxHeight: .infinity)
                        .background(CicadaTheme.bgPane)
                    detail
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .columnEdge(.leading)
                }
                .frame(width: size.width, height: size.height)
                .clipShape(CicadaTheme.shape(CicadaTheme.radiusLarge))
                .floatingSurface(in: CicadaTheme.shape(CicadaTheme.radiusLarge), fill: CicadaTheme.bgBase)
                .accessibilityElement(children: .contain)
                .accessibilityLabel(Copy.settings)
                .accessibilityAddTraits(.isModal)
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .environment(focus)
        .environment(skillsVM)
        .task { await skillsVM.load() }
        .onAppear {
            selection = SettingsSection.restored(from: sectionRaw,
                                                 legacyAgentsMode: UserDefaults.standard.string(forKey: "cicada.agentsMode"))
            UserDefaults.standard.removeObject(forKey: "cicada.agentsMode")   // read once (R-O11)
            apply(router.consumeSettings())
        }
        // A link fired while the panel is already open re-lands in place (R-DS22).
        .onChange(of: router.pendingSettings) { _, _ in apply(router.consumeSettings()) }
        .onChange(of: selection) { _, newValue in sectionRaw = newValue.rawValue }
        .onChange(of: query) { _, _ in
            pickedSinceTyping = false
            focus.matchedRows = trimmedQuery.isEmpty ? [] : Set(hits.map(\.entry.anchor))
        }
        // G139 — every in-panel landing (pointer, search hit, link) arrives as a nonce'd request.
        .onChange(of: focus.request) { _, request in land(request) }
    }

    private var sidebar: some View {
        let hits = self.hits
        let counts = SettingsIndex.counts(hits)
        return VStack(alignment: .leading, spacing: 0) {
            // R-DS21 — Esc in this field does what the ×'s key equivalent does:
            // back out of an open sub-page first, else close the panel (R-O5).
            CicadaSearchField(text: $query, prompt: Copy.searchSettings, onSubmit: openTopHit,
                              onEscape: { focus.escape { router.closeSettings() } })
                .padding(.horizontal, CicadaTheme.spacingMD)
                .padding(.top, CicadaTheme.scaled(14))
                .padding(.bottom, CicadaTheme.spacingSM)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(10)) {
                    ForEach(SettingsGroup.allCases) { group in
                        let sections = group.sections.filter { trimmedQuery.isEmpty || counts[$0, default: 0] > 0 }
                        if !sections.isEmpty {
                            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                                SectionLabel(group.title)
                                    .frame(height: CicadaTheme.scaled(24))
                                    .padding(.horizontal, CicadaTheme.scaled(10))
                                ForEach(sections) { section in
                                    SettingsSidebarRow(section: section,
                                                       isSelected: selection == section && !showingResults,
                                                       count: trimmedQuery.isEmpty ? 0 : counts[section, default: 0]) {
                                        selection = section
                                        pickedSinceTyping = true
                                    }
                                }
                            }
                        }
                    }
                    if !trimmedQuery.isEmpty && hits.isEmpty {
                        Text(Copy.noSettingsMatch(trimmedQuery))
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .padding(.horizontal, CicadaTheme.scaled(10))
                    }
                }
                .padding(.horizontal, CicadaTheme.scaled(10))
                .padding(.bottom, CicadaTheme.spacingLG)
            }
        }
    }

    private var detail: some View {
        Group {
            if showingResults {
                SettingsResultsView(query: trimmedQuery, hits: hits,
                                    liveValue: { SettingsLiveValue.text(for: $0.id, liveInputs) },
                                    open: open)
            } else {
                detailView
            }
        }
        .environment(\.settingsHeaderTrailingInset, CicadaTheme.scaled(SettingsPanelLayout.closeClusterWidth))
        .overlay(alignment: .topTrailing) {
            HStack(spacing: CicadaTheme.spacingSM) {
                KeyHint("esc").help(Copy.pressEscToClose)
                IconButton(systemName: "xmark", help: Copy.closeSettingsHelp, accessibilityLabel: Copy.closeSettings,
                           shortcut: .cancelAction) { focus.escape { router.closeSettings() } }
            }
            .padding(.top, CicadaTheme.scaled(18))
            .padding(.trailing, CicadaTheme.spacingLG)
        }
    }

    // Carried over unchanged from the retired scene.
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

    /// A request from `openSettings`: land on its section (and row). A bare ⌘, or gear keeps
    /// the remembered section.
    private func apply(_ request: SettingsRequest?) {
        guard let request, let section = request.section else { return }
        query = ""
        focus.go(section, row: request.row)
    }

    private func open(_ entry: SettingsEntry) {
        pickedSinceTyping = true
        focus.go(entry.section, row: entry.anchor)
    }

    private func openTopHit() {
        if let top = SettingsSearchLanding.topHit(trimmedQuery, in: entries) { open(top) }
    }

    /// The retired scene's `apply`, unchanged: select, then land and announce.
    private func land(_ request: SettingsFocus.Request?) {
        guard let request else { return }
        selection = request.section
        guard let row = request.row else { return }
        let name = SettingsSearchLanding.announcement(section: request.section, row: row, in: entries)
        focus.land(on: row, announcing: name, reduceMotion: reduceMotion)
    }
}

/// DR-33 — the panel's geometry, pure.
enum SettingsPanelLayout {
    static let width: CGFloat = 880
    static let height: CGFloat = 620
    static let sidebarWidth: CGFloat = 220
    static let minimumInset: CGFloat = 40
    /// `esc` keycap + gap + 28 pt close × + trailing padding.
    static let closeClusterWidth: CGFloat = 88

    static func size(container: CGSize) -> CGSize {
        CGSize(width: max(0, min(CicadaTheme.scaled(width), container.width - 2 * minimumInset)),
               height: max(0, min(CicadaTheme.scaled(height), container.height - 2 * minimumInset)))
    }
}

/// A sidebar row (DR-33 "in the rail's row tokens"): 32 pt, a 16 pt glyph that acknowledges
/// the pointer, `rowFont`. `textTertiary` at rest; `bgHover` + `textPrimary` on hover;
/// `bgSelected` + `textPrimary` when chosen — never the accent. While a query is active it
/// carries its match count in tabular figures, and VoiceOver reads it as a value.
private struct SettingsSidebarRow: View {
    let section: SettingsSection
    let isSelected: Bool
    var count: Int = 0
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(10)) {
                Image(systemName: section.icon)
                    .font(CicadaTheme.icon(.sidebar))
                    .frame(width: CicadaTheme.iconPoints(.sidebar))
                    .iconHover(hovering: hovering)
                Text(section.title)
                    .font(CicadaTheme.rowFont)
                    .lineLimit(1)
                Spacer(minLength: 0)
                if count > 0 {
                    Text(UsageFormat.count(count))
                        .font(CicadaTheme.font(size: 11, weight: .medium))
                        .monospacedDigit()
                        .foregroundStyle(isSelected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary)
                }
            }
            .foregroundStyle(isSelected || hovering ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(height: CicadaTheme.scaled(32))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(isSelected ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : Color.clear)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])
        .accessibilityValue(count > 0 ? Copy.matchingSettings(count) : "")
    }
}
