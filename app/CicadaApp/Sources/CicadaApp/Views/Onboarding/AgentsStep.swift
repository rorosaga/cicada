import AppKit
import SwiftUI

/// Onboarding v2, step 3 (G217, ruling 36 D3): one row per provider umbrella (`GET /providers`, as the Agents page
/// lists them) holding the products of it found on this machine (`AgentStepRows`: the backend's wiring says it is
/// installed, the Claude app is here, or `/agents/live` saw it) — Anthropic: Claude Code · Claude app; OpenAI: Codex …
/// The umbrella's own mark in a `LogoTile`, never a product badge. Its one *Connect* opens each found product's own
/// action, Settings' own: Connect for me plus Remembers automatically (R-OB12) through `AgentConnect.run` with the one
/// wiring answer's binaries (R-FA15) — "Cicada runs exactly these commands…" with *Run these*, the commands behind a
/// collapsed *Show commands*, readable before the click (spec decision 14); the Claude app's *Set up Claude* merge;
/// Cursor's catalog link; else *Copy setup prompt*. A Claude Code wired through the plugin answers no argv, so
/// it is offered nothing to run (the plugin is the canonical door). The row turns green when the agent first calls
/// Cicada (`AgentLiveProbe`, polled every 3 s while the step shows, R-AG15). Onboarding v3 (2026-10-24, after
/// HeyClicky's mic check): one live check — a chip with the exact words to say to the person's own agent and a copy
/// button; when that agent's first call lands (`FirstAgentCall`, the backend's last-seen times) the chip gives way to
/// a small confirmation. Continue stays enabled: connecting can wait. *Another agent* and *Personal agents* fold under
/// one remembered *Other agents* disclosure (DR-39). DR-5, DR-39, DR-40, DR-48, DR-52, DR-66.
struct AgentsStep: View {
    let live: AgentLiveProbe

    @State private var model = AgentsSetupModel()
    @State private var expanded: String?
    @State private var running: String?
    @State private var started: Set<String> = []
    @State private var outcome: [String: String] = [:]
    @State private var copied: String?
    @State private var addingToken = false
    /// DR-39 — each viewer's choice is remembered. A new key; nothing else reads it.
    @AppStorage("cicada.onboarding.otherAgents") private var otherOpen = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private let runtime = CicadaRuntime.current

    private var claudeAppInstalled: Bool {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: LocalInventory.claudeDesktopBundleId) != nil
    }

    @State private var directory = ProviderDirectory.shared

    private var rows: [AgentUmbrellaRow] {
        AgentStepRows.umbrellas(directory.agents,
                                products: AgentStepRows.rows(wiring: model.wiring, live: live.rows, setups: model.setups,
                                                             claudeAppInstalled: claudeAppInstalled))
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
                    umbrellaRow(row)
                }
            }
            .settingsCardSurface()
            tryIt
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                DisclosureHeader(title: Copy.agentsOther, summary: Copy.agentsOtherSummary, isOpen: otherOpen) {
                    otherOpen.toggle()
                }
                if otherOpen {
                    VStack(alignment: .leading, spacing: 0) {
                        anotherAgent
                        SettingsDivider()
                        // Five agents, so no one agent's mark speaks for them: a glyph, like "Another agent" (looks pass).
                        ConnectionLine(logo: nil, name: Copy.agentsPersonal, systemFallback: "person",
                                       detail: Copy.agentsPersonalNames, detailLines: 1) {
                            NeutralButton(title: Copy.AgentsPage.addToken, size: .compact) { addingToken = true }
                        }
                    }
                    .settingsCardSurface()
                }
            }
        }
        .task { await live.run() }
        .task { await directory.load() }
        .task {
            await model.load()
            for entry in AgentCatalog.all { await model.select(entry) }
        }
        .sheet(isPresented: $addingToken) { AddAgentTokenSheet { addingToken = false } }
    }

    // MARK: The one live check

    /// The chip with the exact words to try, until the first call lands; then the confirmation, in the agent's own name.
    /// The swap is an event, not a keyboard action: it fades (and grows a touch) on DR-61's card fade, a plain fade under
    /// Reduce Motion (DR-66).
    @ViewBuilder
    private var tryIt: some View {
        Group {
            if let caller = live.firstCall {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "checkmark.circle.fill")
                        .font(CicadaTheme.icon(.inline))
                        .foregroundStyle(CicadaTheme.success)
                        .accessibilityHidden(true)
                    Text(Copy.agentsFirstCall(AgentTryPrompt.callerName(caller, rows: rows)))
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                }
                .transition(reduceMotion ? .opacity : .opacity.combined(with: .scale(scale: 0.96)))
                .accessibilityElement(children: .combine)
            } else {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(Copy.agentsTryLead)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Text(Copy.agentsTryAsk(AgentTryPrompt.agentName(rows)))
                            .font(CicadaTheme.rowFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .textSelection(.enabled)
                        IconButton(systemName: copied == "try" ? "checkmark" : "doc.on.doc",
                                   help: Copy.agentsTryCopyHelp, accessibilityLabel: Copy.agentsTryCopyHelp) {
                            copy(Copy.agentsTryPrompt, id: "try")
                        }
                    }
                    .padding(.leading, CicadaTheme.spacingSM)
                    .padding(.vertical, CicadaTheme.scaled(2))
                    .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
                    .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                }
                .transition(.opacity)
            }
        }
        .animation(CicadaMotion.cardFade(reduceMotion: reduceMotion), value: live.firstCall)
    }

    // MARK: An umbrella

    private func umbrellaRow(_ row: AgentUmbrellaRow) -> some View {
        let status = AgentStepRows.status(row, started: started)
        return ConnectionLine(logo: row.logo, name: row.label, systemFallback: "sparkles", detail: row.detail,
                              status: status, detailLines: 1) {
            if !row.actionable.isEmpty, expanded != row.id {
                NeutralButton(title: Copy.agentsConnect, size: .compact) { expanded = row.id }
            }
        } below: {
            if expanded == row.id {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(row.actionable) { product in productLine(product) }
                    HStack {
                        Spacer()
                        TextButton(title: Copy.agentsDone, inline: true) { expanded = nil }
                    }
                }
                .padding(.leading, LogoTile.tileSide(.regular) + CicadaTheme.spacingMD)
            }
        }
    }

    /// One found product under its umbrella: its name, then its own action (Settings' path).
    private func productLine(_ product: AgentStepRow) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(product.name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                Spacer(minLength: CicadaTheme.spacingSM)
                action(product)
            }
            if case .connect(let steps) = product.action { commands(product, steps) }
            if let outcome = outcome[product.id] {
                Text(outcome).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    @ViewBuilder
    private func action(_ row: AgentStepRow) -> some View {
        switch row.action {
        case .none, .preparing:
            EmptyView()
        case .connect(let steps):
            NeutralButton(title: running == row.id ? Copy.agentConnecting : Copy.agentsRun, size: .compact,
                          isDisabled: running != nil) { run(row, steps) }
        case .setUpClaude:
            NeutralButton(title: Copy.agentSetUpClaude, size: .compact) { setUpClaude(row) }
        case .openCursor:
            NeutralButton(title: Copy.agentOpenInCursor, size: .compact) { openCursor(row) }
        case .copy(let text):
            NeutralButton(title: copied == row.id ? Copy.agentCopied : Copy.agentCopyPrompt,
                          systemImage: copied == row.id ? "checkmark" : "doc.on.doc", size: .compact) {
                copy(text, id: row.id)
            }
        }
    }

    /// "Cicada runs exactly these commands…" beside *Run these*; the commands themselves behind a collapsed *Show
    /// commands* (DR-39), one click from being read before the run (spec decision 14).
    private func commands(_ row: AgentStepRow, _ steps: [AgentWiringStep]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.agentConnectHow).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            DisclosureGroup(Copy.agentsShowCommands) {
                ScrollView {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        ForEach(steps, id: \.self) { CommandBox(command: $0.display) }
                    }
                }
                .frame(maxHeight: CicadaTheme.scaled(AgentsStepLayout.commandsHeight))
            }
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
        }
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
                // The umbrella stays open: its other products may still have a step.
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
