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
struct SettingsScene: View {
    @AppStorage("cicada.settingsSection") private var sectionRaw = SettingsSection.general.rawValue
    @State private var selection: SettingsSection = .general

    var body: some View {
        NavigationSplitView {
            List(SettingsSection.allCases, selection: $selection) { section in
                Label(section.title, systemImage: section.icon).tag(section)
            }
            .navigationSplitViewColumnWidth(min: 160, ideal: 180, max: 220)
        } detail: {
            detailView
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(CicadaTheme.background)
        }
        .frame(minWidth: Self.windowWidth, minHeight: Self.windowHeight)
        .onAppear { selection = SettingsSection.restored(from: sectionRaw) }
        .onChange(of: selection) { _, newValue in sectionRaw = newValue.rawValue }
        // recent-work #9 — `onAppear` fires once per view lifetime, and this
        // is a separate window that is usually ALREADY open when
        // `EmptyStateView`'s "Open Integrations" seeds the key. Mirroring the
        // stored value back onto `selection` makes the pair symmetric: the
        // `onChange(of: selection)` above writes, this one reads.
        .onChange(of: sectionRaw) { _, raw in selection = SettingsSection.restored(from: raw) }
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
        case .sleep: SettingsSleepView()
        case .integrations: IntegrationsView()
        case .agents: ConnectView()
        case .plansAndKeys: ConnectionsView()
        }
    }
}
