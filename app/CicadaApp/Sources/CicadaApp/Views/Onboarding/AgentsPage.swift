import SwiftUI

/// F-04 (G145; owner: "the higgsfield … pattern … a checkmark next to the agent that was connected … multiple agents
/// connected at the same time") — the selector of `AgentCatalog.featured` with a live ✓ (`AgentLiveProbe`, polled
/// while this page shows, R-AG15), the chosen agent's numbered steps (`AgentSetupSteps`), and the pointer to
/// Settings → Agents. Claude Code's and Codex's Connect for me also turns on Remembers automatically (R-OB12). The
/// probe belongs to the frame, so You're set reads its last answer. No made-up beliefs (R-OB13). DR-5, DR-7, DR-40,
/// DR-44, DR-52.
struct AgentsPage: View {
    let live: AgentLiveProbe

    @State private var model = AgentsSetupModel()
    @State private var selected = "claude-code"
    @State private var linkFor: RemoteApp?
    @Environment(AppRouter.self) private var router
    private let home = BackendProcess.installRoot().path

    private var entry: AgentCatalogEntry { AgentCatalog.entry(for: selected) ?? AgentCatalog.featured[0] }
    private var agentWiring: AgentWiring? { model.wiring?.agents.first { $0.id == entry.id } }
    private var remoteReady: Bool { model.remote?.enabled == true && model.remote?.effectiveUrl != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            OnboardingHeadline(title: Copy.agentsPageTitle, subline: Copy.agentsPageSubline)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack {
                    SectionLabel(Copy.agentsYourAgents)
                    Spacer()
                    Text(Copy.agentsConnectedSummary(live.connectedCount))
                        .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                AgentSelector(entries: AgentCatalog.featured, selection: $selected, connected: live.connected,
                              justConnected: live.justConnected)
                AgentSetupSteps(
                    entry: entry,
                    steps: AgentSteps.steps(for: entry, setups: model.setups, wiring: agentWiring,
                                            live: live.rows[entry.id], remoteReady: remoteReady,
                                            bundleAutoRecall: true),
                    header: AgentSteps.header(for: entry, wiring: agentWiring),
                    honesty: AgentSteps.honesty(for: entry),
                    connected: live.connected.contains(entry.id),
                    footer: entry.id == "codex" ? Copy.autoRecallCodexTrust : nil,
                    binaries: Set(model.wiring?.agents.compactMap(\.binary) ?? []),
                    home: home,
                    memoryRoot: model.memoryRoot,
                    deeplink: AgentSetupCatalog.all(home: home, memoryRoot: model.memoryRoot)
                        .first { $0.id == "cursor" }?.deeplink?.url,
                    onConnected: { Task { await model.refreshWiring() } },
                    onOpenFromAnywhere: { _ = router.openSettings(.remote) },
                    onCreateLink: { linkFor = $0 })
            }
            OnboardingPointerLine(lead: Copy.agentsFoot, section: .agents, label: Copy.onboardingSettingsAgents)
        }
        // R-AG15 — cancelled by SwiftUI when the page leaves, so nothing polls behind another page.
        .task { await live.run() }
        .task { await model.load() }
        .onChange(of: selected, initial: true) { _, id in
            guard let pill = AgentCatalog.entry(for: id) else { return }
            Task { await model.select(pill) }
        }
        .sheet(item: $linkFor) { app in
            NewConnectorSheet(initialApp: app) {
                linkFor = nil
                Task { await model.load() }
            }
        }
    }
}
