import SwiftUI

/// Settings → Intelligence (ruling 36 D1/D6, G50, G217): who consolidates the memory. One list from `GET /providers`
/// joined to `/connections`: the person's plans, then API keys — a local model only as a quiet last row, never pitched
/// (D1) — and one *In use* row on top. It replaced Engines and Plans & keys; their anchors land here
/// (`SettingsSection.retired`). The scheduled-plan switch (ruling 4c) sits below, worded as the ruling words it.
///
/// A key is pasted, checked with its provider (`PUT /connections/{id}/key`: 422 refused, nothing saved; 503 provider
/// unreachable — *Save without checking*), and then shown only as its last four, where it lives and when it was
/// checked, with the provider's own terms note (the Gemini free tier, Together's retention).
struct IntelligenceView: View {
    @Environment(Store.self) private var store
    @Environment(ConnectionsViewModel.self) private var connectionsVM
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(SleepViewModel.self) private var sleepVM
    @State private var directory = ProviderDirectory.shared

    var body: some View {
        SettingsPage(section: .intelligence) {
            SettingsGroupCard {
                inUse.settingsRow(.engineChoice)
            }
            group(Copy.Intelligence.plans, kind: "plan").settingsRow(.plansAndKeys)
            group(Copy.Intelligence.keys, kind: "key")
            SettingsGroupCard {
                SettingsRow(.sleepUsePlan, title: Copy.ServerPlan.usePlanTitle) {
                    Toggle(Copy.ServerPlan.usePlanTitle, isOn: Binding(get: { usePlan }, set: { setUsePlan($0) }))
                        .labelsHidden()
                        .toggleStyle(.switch)
                }
                // R-E13 (Engines' switch, kept reachable): only where a plan is in use, off by default.
                if let response = engineVM.response, EngineOption.showsOverageToggle(selectedMode: response.selected) {
                    SettingsDivider()
                    SettingsRow(.engineOverage, title: Copy.keepGoingOnExtraUsage) {
                        Toggle(Copy.keepGoingOnExtraUsage, isOn: Binding(get: { response.allowOverage }, set: { on in
                            Task { await engineVM.set(mode: response.mode, model: nil, disambiguationModel: nil,
                                                      allowOverage: on) }
                        }))
                        .labelsHidden()
                        .toggleStyle(.switch)
                    }
                }
                // G139's "Use my Claude plan when I start" — only under an API key, where it does something.
                if engineVM.response?.mode == "byok", let plan = claudePlan, plan.showsSleepEngineToggle {
                    SettingsDivider()
                    SettingsRow(.engineAutoClaude, title: Copy.useClaudePlanWhenIStart) {
                        Toggle(Copy.useClaudePlanWhenIStart, isOn: Binding(get: { plan.useForSleep }, set: { on in
                            Task {
                                await connectionsVM.setUseForSleep(plan.id, on: on)
                                await engineVM.load()
                            }
                        }))
                        .labelsHidden()
                        .toggleStyle(.switch)
                    }
                }
            }
        }
        .task {
            await directory.load()
            if engineVM.response == nil { await engineVM.load() }
            if sleepVM.runOptions == nil { await sleepVM.loadRunOptions() }
        }
    }

    private var claudePlan: ConnectionStatus? {
        (store.connections.value ?? []).first { $0.id == "claude-plan" }
    }

    /// The chosen card's models, when it offers a choice (the plan's model, a key's model).
    private var modelChoice: (candidate: SleepEngineCandidate, models: [String])? {
        guard let response = engineVM.response, response.selected != "auto", !response.isPinnedByEnvironment,
              let candidate = response.candidates.first(where: { $0.id == response.selected }),
              candidate.models.count > 1 else { return nil }
        return (candidate, candidate.models)
    }

    // MARK: In use

    private var inUse: some View {
        let response = engineVM.response
        let preview = response?.preview?.manual
        let name = preview.map { EngineOption.previewName(engine: $0.engine, model: $0.model) } ?? Copy.Intelligence.auto
        let mark = preview.flatMap { EngineOption.previewMark(engine: $0.engine, model: $0.model) }
            ?? response.flatMap { Self.connection(forCard: $0.selected, provider: $0.provider) }
                .flatMap { ConnectionMark.logoName(connectionId: $0) }
        let isAuto = response?.selected == "auto"
        return ConnectionLine(logo: mark, name: name, systemFallback: "cpu",
                              detail: response?.isPinnedByEnvironment == true ? Copy.Intelligence.pinned
                                  : (isAuto ? Copy.Intelligence.auto : nil)) {
            if let choice = modelChoice, let response {
                Menu(response.model.isEmpty ? Copy.Intelligence.inUse : response.model) {
                    ForEach(choice.models, id: \.self) { model in
                        Button(model) {
                            guard let write = EngineWrite.model(model, mode: EngineWrite.mode(of: choice.candidate),
                                                                current: response.model) else { return }
                            Task { await engineVM.apply(write) }
                        }
                    }
                }
                .fixedSize()
            } else {
                Text(Copy.Intelligence.inUse)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            if !isAuto, response?.isPinnedByEnvironment == false {
                TextButton(title: Copy.Intelligence.useAuto, help: Copy.Intelligence.useHelp, inline: true) {
                    choose(card: "auto")
                }
            }
        }
    }

    // MARK: Groups

    @ViewBuilder
    private func group(_ header: String, kind: String) -> some View {
        let items = directory.intelligence.filter { kind == "plan" ? $0.item.kind == "plan" : $0.item.kind != "plan" }
            .sorted { ($0.item.kind == "local" ? 1 : 0) < ($1.item.kind == "local" ? 1 : 0) }
        if !items.isEmpty {
            SettingsGroupCard(header: header) {
                ForEach(Array(items.enumerated()), id: \.element.item.id) { index, pair in
                    if index > 0 { SettingsDivider() }
                    IntelligenceRow(umbrella: pair.umbrella, item: pair.item,
                                    connection: connection(for: pair.item),
                                    inUse: inUseConnection == ProviderDirectory.connectionId(pair.item.connection),
                                    canChoose: engineVM.response?.isPinnedByEnvironment == false,
                                    onUse: { use(pair.item) })
                        .settingsRow(.connection(ProviderDirectory.connectionId(pair.item.connection)))
                }
            }
        }
    }

    private func connection(for item: ProviderIntelligence) -> ConnectionStatus? {
        let id = ProviderDirectory.connectionId(item.connection)
        return (store.connections.value ?? []).first { $0.id == id }
    }

    /// The connection the chosen card reads through, when one is chosen (nil under Auto).
    private var inUseConnection: String? {
        guard let response = engineVM.response, response.selected != "auto" else { return nil }
        return Self.connection(forCard: response.selected, provider: response.provider)
    }

    static func connection(forCard card: String, provider: String?) -> String? {
        if card == "byok" { return provider.map { "byok-\($0)" } }
        return EngineOption.connectionId(for: card)
    }

    // MARK: Choosing

    private func use(_ item: ProviderIntelligence) {
        guard let response = engineVM.response, let write = Self.write(using: item, response: response) else { return }
        Task { await engineVM.apply(write) }
    }

    private func choose(card: String) {
        guard let response = engineVM.response, let write = Self.write(card: card, response: response) else { return }
        Task { await engineVM.apply(write) }
    }

    /// The one write a row's *Use* sends — shared with onboarding's Intelligence step, so both choose alike.
    static func write(using item: ProviderIntelligence, response: SleepEngineResponse) -> EngineWrite? {
        let id = ProviderDirectory.connectionId(item.connection)
        switch id {
        case "claude-plan": return write(card: "agent", response: response)
        case "chatgpt-plan": return write(card: "codex", response: response)
        case "byok-openrouter": return write(card: "openrouter", response: response)
        case "ollama-local": return write(card: "local", response: response)
        default:
            guard let provider = response.providers.first(where: { $0.connectionId == id }) else { return nil }
            return EngineOption.providerWrite(provider, selectedCard: response.selected, currentModel: response.model)
        }
    }

    static func write(card: String, response: SleepEngineResponse) -> EngineWrite? {
        guard let candidate = response.candidates.first(where: { $0.id == card }) else { return nil }
        return EngineWrite.choosing(candidate, current: response.selected)
    }

    // MARK: The scheduled-plan switch (ruling 4c)

    private var usePlan: Bool { sleepVM.runOptions?.scheduledUsePlan ?? SleepRunOptions().scheduledUsePlan }

    private func setUsePlan(_ on: Bool) {
        store.bankTask {
            guard await sleepVM.updateRunOptions(.scheduledUsePlan(on)) else { return }
            await sleepVM.load()
            await engineVM.load()
        }
    }
}

/// One plan or key: its umbrella's mark, its name, a dot and one word, and its one action. A key row opens in place
/// to take a key. Onboarding's Intelligence step draws the same row (one sign-in and one paste → Verify, never two).
struct IntelligenceRow: View {
    let umbrella: ProviderUmbrella
    let item: ProviderIntelligence
    let connection: ConnectionStatus?
    let inUse: Bool
    let canChoose: Bool
    let onUse: () -> Void

    @Environment(ConnectionsViewModel.self) private var connectionsVM
    @Environment(Store.self) private var store
    @State private var editing = false
    @State private var key = ""
    @State private var checking = false
    @State private var problem: String?
    @State private var offerUnchecked = false

    private var connected: Bool { connection?.connected ?? false }
    private var isKey: Bool { item.kind == "key" }
    private var isLocal: Bool { item.kind == "local" }
    private var isSignIn: Bool { connection?.login?.mode == "oauth" }

    var body: some View {
        ConnectionLine(logo: isLocal ? nil : umbrella.logo,
                       name: isLocal ? Copy.Intelligence.local : item.label,
                       systemFallback: isLocal ? "desktopcomputer" : "key",
                       detail: detail,
                       status: isLocal ? nil : (connected ? (isKey ? Copy.Status.saved : Copy.Status.connected)
                                                          : Copy.Status.off, connected),
                       quiet: isLocal) {
            actions
        } below: {
            if editing { keyEntry }
            if let pending = connectionsVM.pendingLogin, pending.connectionId == connection?.id {
                DeviceCodePanel(session: pending, onRetry: signIn)
            }
        }
    }

    private var detail: String? {
        if isKey, connected {
            let line = Copy.Intelligence.keyLine(hint: connection?.keyHint, store: connection?.keyStore,
                                                 verifiedAt: connection?.verifiedAt)
            return [line, item.note ?? connection?.termsNote].compactMap { $0 }.joined(separator: "\n")
        }
        // The terms note shows before a key is pasted (the Gemini free tier, Together's retention) — and only then.
        if isKey, editing { return item.note ?? connection?.termsNote }
        return nil
    }

    @ViewBuilder private var actions: some View {
        if inUse {
            EmptyView()
        } else if connected, canChoose {
            TextButton(title: Copy.Intelligence.use, help: Copy.Intelligence.useHelp, inline: true, action: onUse)
        }
        if isLocal {
            EmptyView()
        } else if isKey && !isSignIn {
            if connected {
                TextButton(title: Copy.Intelligence.remove, inline: true) {
                    guard let id = connection?.id else { return }
                    Task { await connectionsVM.removeKey(id) }
                }
            } else if !editing {
                NeutralButton(title: Copy.Intelligence.addKey, size: .compact) { editing = true }
            }
        } else if connected {
            TextButton(title: Copy.Intelligence.signOut, inline: true) {
                guard let id = connection?.id else { return }
                Task { await connectionsVM.logout(id) }
            }
        } else if connection?.available ?? false || isSignIn {
            NeutralButton(title: Copy.Intelligence.signIn, size: .compact, action: signIn)
        }
    }

    private var keyEntry: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                SecureField(Copy.Intelligence.pasteKey, text: $key)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { save(check: true) }
                    .disabled(checking)
                if checking { ProgressView().controlSize(.small) }
                NeutralButton(title: Copy.Intelligence.verify, size: .compact,
                              isDisabled: checking || key.trimmingCharacters(in: .whitespaces).isEmpty) {
                    save(check: true)
                }
                TextButton(title: Copy.Intelligence.cancel, inline: true) { reset() }
            }
            if let problem {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(problem)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    if offerUnchecked {
                        TextButton(title: Copy.Intelligence.saveUnchecked, inline: true) { save(check: false) }
                    }
                }
            }
        }
        .padding(.leading, LogoTile.tileSide(.regular) + CicadaTheme.spacingMD)
    }

    private func signIn() {
        guard let id = connection?.id ?? Optional(ProviderDirectory.connectionId(item.connection)) else { return }
        Task { _ = await connectionsVM.beginLogin(id) }
    }

    private func save(check: Bool) {
        let value = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        let id = ProviderDirectory.connectionId(item.connection)
        checking = true
        problem = nil
        offerUnchecked = false
        Task { @MainActor in
            defer { checking = false }
            do {
                _ = try await APIClient.shared.saveKey(id, key: value, check: check)
                reset()
                await connectionsVM.load(fresh: true)
            } catch {
                let answer = ConnectionModelText.detail(error)
                problem = answer?.text ?? error.localizedDescription
                offerUnchecked = answer?.code == 503
            }
        }
    }

    private func reset() {
        key = ""
        editing = false
        problem = nil
        offerUnchecked = false
    }
}
