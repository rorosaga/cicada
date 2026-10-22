import AppKit
import SwiftUI

/// Onboarding v2, step 3 (G217, ruling 36 D3): the agents found on this machine, one `LogoTile` row each
/// (`AgentStepRows`: the backend's wiring says it is installed, the Claude app is here, or `/agents/live` saw it).
/// Each row's one verb is Settings' own: *Connect* runs Connect for me plus Remembers automatically (R-OB12) — its
/// commands shown before the click that runs them (spec decision 14), through `AgentConnect.run` with the one wiring
/// answer's binaries (R-FA15); the Claude app's *Connect* is *Set up Claude*'s config merge; Cursor's opens its own
/// catalog link; everything else is *Copy setup prompt*. A Claude Code wired through the plugin answers no argv, so
/// it is offered nothing to run (the plugin is the canonical door). The row turns green when the agent first calls
/// Cicada (`AgentLiveProbe`, polled every 3 s while the step shows, R-AG15). Below: any other agent's prompt, and
/// *Add an agent token* for personal agents (G213). DR-40, DR-48, DR-52.
struct AgentsStep: View {
    let live: AgentLiveProbe

    @State private var model = AgentsSetupModel()
    @State private var expanded: String?
    @State private var running: String?
    @State private var started: Set<String> = []
    @State private var outcome: [String: String] = [:]
    @State private var copied: String?
    @State private var addingToken = false
    private let runtime = CicadaRuntime.current

    private var claudeAppInstalled: Bool {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: LocalInventory.claudeDesktopBundleId) != nil
    }

    private var rows: [AgentStepRow] {
        AgentStepRows.rows(wiring: model.wiring, live: live.rows, setups: model.setups,
                           claudeAppInstalled: claudeAppInstalled)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            OnboardingHeadline(title: Copy.agentsTitle, subline: Copy.agentsSubline)
            VStack(alignment: .leading, spacing: 0) {
                if rows.isEmpty, model.wiring != nil {
                    Text(Copy.agentsNoneFound)
                        .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                        .padding(CicadaTheme.spacingMD)
                }
                ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                    if index > 0 { SettingsDivider() }
                    agentRow(row)
                }
            }
            .settingsCardSurface()
            VStack(alignment: .leading, spacing: 0) {
                anotherAgent
                SettingsDivider()
                ConnectionLine(logo: "instinct", name: Copy.agentsPersonal, detail: Copy.agentsPersonalNames,
                               detailLines: 1) {
                    NeutralButton(title: Copy.AgentsPage.addToken, size: .compact) { addingToken = true }
                }
            }
            .settingsCardSurface()
        }
        .task { await live.run() }
        .task {
            await model.load()
            for entry in AgentCatalog.all { await model.select(entry) }
        }
        .sheet(isPresented: $addingToken) { AddAgentTokenSheet { addingToken = false } }
    }

    // MARK: A row

    private func agentRow(_ row: AgentStepRow) -> some View {
        let status = AgentStepRows.status(row, started: started.contains(row.id))
        return ConnectionLine(logo: row.entry.mark, name: row.entry.name, systemFallback: row.entry.symbol,
                              detail: outcome[row.id], status: status, detailLines: 2) {
            action(row)
        } below: {
            if expanded == row.id, case .connect(let steps) = row.action { commands(row, steps) }
        }
    }

    @ViewBuilder
    private func action(_ row: AgentStepRow) -> some View {
        switch row.action {
        case .none, .preparing:
            EmptyView()
        case .connect:
            if expanded != row.id {
                NeutralButton(title: Copy.agentsConnect, size: .compact) { expanded = row.id }
            }
        case .setUpClaude:
            NeutralButton(title: Copy.agentsConnect, size: .compact) { setUpClaude(row) }
        case .openCursor:
            NeutralButton(title: Copy.agentsConnect, size: .compact) { openCursor(row) }
        case .copy(let text):
            NeutralButton(title: copied == row.id ? Copy.agentCopied : Copy.agentCopyPrompt,
                          systemImage: copied == row.id ? "checkmark" : "doc.on.doc", size: .compact) {
                copy(text, id: row.id)
            }
        }
    }

    /// The one click that runs them, then the exact commands it runs (spec decision 14) — in a short scroll, so a
    /// stranger sees the button first and every command is still there to read before the click.
    private func commands(_ row: AgentStepRow, _ steps: [AgentWiringStep]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.agentConnectHow).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: CicadaTheme.spacingSM)
                TextButton(title: Copy.Intelligence.cancel, inline: true) { expanded = nil }
                NeutralButton(title: running == row.id ? Copy.agentConnecting : Copy.agentsRun, size: .compact,
                              isDisabled: running != nil) { run(row, steps) }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    ForEach(steps, id: \.self) { CommandBox(command: $0.display) }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(AgentsStepLayout.commandsHeight))
        }
        .padding(.leading, LogoTile.tileSide(.regular) + CicadaTheme.spacingMD)
        .privacySensitive()
    }

    private var anotherAgent: some View {
        let other = AgentCatalog.entry(for: "other")
        let prompt = model.setups["other"].flatMap { $0.kind == "prompt" ? $0.prompt : nil }
        return ConnectionLine(logo: nil, name: Copy.agentsAnother, systemFallback: other?.symbol ?? "ellipsis") {
            if let prompt, !prompt.isEmpty {
                NeutralButton(title: copied == "other" ? Copy.agentCopied : Copy.agentCopyPrompt,
                              systemImage: copied == "other" ? "checkmark" : "doc.on.doc", size: .compact) {
                    copy(prompt, id: "other")
                }
            }
        }
    }

    // MARK: What the buttons do — Settings' own paths

    private func run(_ row: AgentStepRow, _ steps: [AgentWiringStep]) {
        running = row.id
        let binaries = Set(model.wiring?.agents.compactMap(\.binary) ?? [])
        Task { @MainActor in
            let result = await AgentConnect.run(steps, runtime: runtime, binaries: binaries)
            running = nil
            switch result {
            case .done:
                expanded = nil
                started.insert(row.id)
                outcome[row.id] = nil
                await model.refreshWiring()
            case .refused: outcome[row.id] = Copy.agentRefused
            case .failed(let why): outcome[row.id] = why
            }
        }
    }

    private func setUpClaude(_ row: AgentStepRow) {
        let memory = model.memoryRoot.flatMap { $0.isEmpty ? nil : $0 } ?? runtime.memoryRootDefault
        let server = ClaudeDesktopConfig.server(command: runtime.mcpCommand.command, args: runtime.mcpCommand.args,
                                                memory: memory)
        let result = ClaudeDesktopConfig.apply(server: server, at: ClaudeDesktopConfig.configURL())
        switch result {
        case .done, .alreadySetUp: started.insert(row.id); outcome[row.id] = AgentQuickSetup.caption(result)
        case .claudeNotSetUp, .leftUntouched, .failed: outcome[row.id] = AgentQuickSetup.caption(result)
        }
    }

    private func openCursor(_ row: AgentStepRow) {
        guard let url = AgentSetupCatalog.all(runtime: runtime, memoryRoot: model.memoryRoot)
            .first(where: { $0.id == "cursor" })?.deeplink?.url else { return }
        NSWorkspace.shared.open(url)
        started.insert(row.id)
    }

    private func copy(_ text: String, id: String) {
        AppPasteboard.copy(text)
        copied = id
        started.insert(id)
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(CicadaTiming.copiedConfirmation))
            if copied == id { copied = nil }
        }
    }
}

enum AgentsStepLayout {
    /// The commands' scroll: about two commands at 1×, so Run stays on screen with the next agent's row.
    static let commandsHeight: CGFloat = 200
}
