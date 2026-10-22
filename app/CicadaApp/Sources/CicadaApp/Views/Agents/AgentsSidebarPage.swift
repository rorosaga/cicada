import AppKit
import SwiftUI

/// The Agents page (ruling 36 D6, G217; ⌘9, appended so no shortcut moved — DR-22): every agent that reads and writes
/// Cicada, one row per provider umbrella from `GET /providers` — `LogoTile` · name · where · last seen · its
/// conversations · a dot and one word (`/agents/live`, polled every 3 s while the page shows). A row opens its detail
/// (DR-74): the products under the umbrella and how each connects, its chat export's import, whether its page edits
/// write at once or propose (G198's trust list), *Copy setup prompt*, and — for a harness with hooks — *Remembers
/// automatically*. *Add an agent token* (DR-75) makes a G213 token for a personal agent that cannot use MCP and shows
/// its one paragraph once. It replaced Settings → Agents; that page's anchors land here (`SettingsSection.retired`).
///
/// None of its reads is a Store domain: `/providers` is static per release (`ProviderDirectory`), `/agents/live` is a
/// live probe and agent tokens are machine-global — each kept in memory, said here (CLAUDE.md, Sync).
struct AgentsSidebarPage: View {
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @State private var directory = ProviderDirectory.shared
    @State private var live: [AgentLiveRow] = []
    @State private var tokens: [AgentToken] = []
    @State private var selected: String?
    @State private var adding = false

    private var umbrellas: [ProviderUmbrella] { directory.agents }
    private var open: ProviderUmbrella? { selected.flatMap { id in umbrellas.first { $0.id == id } } }

    var body: some View {
        ProgressiveColumns(hasDetail: open != nil, hasTrailing: false,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { _ in
            EyebrowRow(eyebrow: Copy.AgentsPage.title) {
                PageAddButton(title: Copy.AgentsPage.addToken, help: Copy.AgentsPage.addToken) { adding = true }
            }
        } list: { _ in
            list.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        } detail: { plan in
            if let umbrella = open {
                AgentDetailColumn(umbrella: umbrella, summary: AgentSummary.of(umbrella, live: live,
                                                                               sources: store.sourcesOverview.value ?? []),
                                  backLabel: plan.listHidden ? Copy.AgentsPage.back : nil,
                                  onClose: { selected = nil })
                    .id(umbrella.id)
                    .columnEdge()
            }
        } trailing: { _ in EmptyView() }
            .background(CicadaTheme.bgBase)
            .task { await directory.load() }
            .task { await pollLive() }
            .task { await loadTokens() }
            .onRailReselect(.agents, router: router) {
                router?.popToRoot(reduceMotion: reduceMotion) { selected = nil }
            }
            .sheet(isPresented: $adding) {
                AddAgentTokenSheet { adding = false; Task { await loadTokens() } }
            }
    }

    private var list: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(umbrellas.enumerated()), id: \.element.id) { index, umbrella in
                        if index > 0 { SettingsDivider() }
                        let summary = AgentSummary.of(umbrella, live: live, sources: store.sourcesOverview.value ?? [])
                        Button { selected = umbrella.id } label: {
                            ConnectionLine(logo: umbrella.logo, name: umbrella.label, systemFallback: "sparkles",
                                           detail: summary.line(now: Date()),
                                           status: (summary.connected ? Copy.Status.connected : Copy.Status.off,
                                                    summary.connected)) { EmptyView() }
                                .background(selected == umbrella.id ? CicadaTheme.bgSelected : Color.clear)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.cicadaPlain)
                        .accessibilityAddTraits(selected == umbrella.id ? [.isSelected] : [])
                    }
                }
                .settingsCardSurface()
                if !tokens.isEmpty {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        SectionLabel(Copy.AgentsPage.tokens).padding(.horizontal, CicadaTheme.spacingXS)
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(Array(tokens.enumerated()), id: \.element.id) { index, token in
                                if index > 0 { SettingsDivider() }
                                ConnectionLine(logo: nil, name: token.name, systemFallback: "key",
                                               detail: AgentSummary.tokenLine(token),
                                               status: (token.state == "active" ? Copy.Status.active : Copy.Status.off,
                                                        token.state == "active")) {
                                    if token.state == "active" {
                                        TextButton(title: Copy.AgentsPage.revoke, inline: true) {
                                            Task {
                                                try? await APIClient.shared.revokeAgentToken(token.id)
                                                await loadTokens()
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        .settingsCardSurface()
                    }
                }
                VStack(alignment: .leading, spacing: 0) {
                    CommandLineToolSetting()
                }
                .settingsCardSurface()
            }
            .padding(CicadaTheme.spacingGutter)
            .frame(maxWidth: CicadaTheme.scaled(760), alignment: .leading)
        }
    }

    private func pollLive() async {
        while !Task.isCancelled {
            if let answer = try? await APIClient.shared.fetchAgentLive() { live = answer.agents }
            try? await Task.sleep(for: .seconds(3))
        }
    }

    private func loadTokens() async {
        tokens = (try? await APIClient.shared.fetchAgentTokens()) ?? tokens
    }
}

/// What one umbrella's row says, pure (tested): any of its ways connected, the latest sighting, where it was seen,
/// and how many conversations its harnesses brought in.
struct AgentSummary: Equatable {
    var connected = false
    var lastSeen: Date?
    var via: String?
    var conversations = 0
    var connects: [String] = []

    static func of(_ umbrella: ProviderUmbrella, live: [AgentLiveRow], sources: [SourceOverview]) -> AgentSummary {
        let ids = Set(umbrella.ways.map(\.id))
        let rows = live.filter { ids.contains($0.id) }
        var out = AgentSummary()
        out.connected = rows.contains { $0.connected }
        let seen = rows.compactMap { row in row.lastSeenAt.flatMap(ISODate.parse).map { (row, $0) } }
            .max { $0.1 < $1.1 }
        out.lastSeen = seen?.1
        out.via = seen?.0.via
        out.conversations = sources.filter { source in
            ids.contains(source.harness ?? "") || ids.contains(source.id) || !ids.isDisjoint(with: source.origins)
        }.reduce(0) { $0 + $1.conversations }
        var connects: [String] = []
        for way in umbrella.ways { for c in way.connects where !connects.contains(c) { connects.append(c) } }
        out.connects = connects
        return out
    }

    /// "on this machine · 3 min ago · 12 conversations" — each part only when known.
    func line(now: Date) -> String {
        var parts: [String] = []
        let whereWord = via.flatMap { $0 == "remote" ? Copy.AgentsPage.connectsWord("remote") : Copy.AgentsPage.connectsWord("stdio") }
            ?? connects.first.flatMap(Copy.AgentsPage.connectsWord)
        if let whereWord { parts.append(whereWord) }
        if let lastSeen { parts.append(Copy.AgentsPage.seen(lastSeen, now: now)) }
        if conversations > 0 { parts.append(Copy.AgentsPage.conversations(conversations)) }
        return parts.joined(separator: " · ")
    }

    static func tokenLine(_ token: AgentToken) -> String {
        var parts: [String] = [token.scopes.joined(separator: ", ")]
        if let used = token.lastUsedAt.flatMap(ISODate.parse) { parts.append(Copy.AgentsPage.seen(used)) }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

/// One umbrella's detail (DR-74): its products and how each connects, its chat export, page edits, setup prompt.
private struct AgentDetailColumn: View {
    let umbrella: ProviderUmbrella
    let summary: AgentSummary
    let backLabel: String?
    let onClose: () -> Void

    @Environment(AppRouter.self) private var router: AppRouter?
    @State private var editors = PageEditorsModel()
    @State private var copied = false

    private var setupHarness: String? { umbrella.ways.lazy.compactMap(\.setup.first).first }
    private var exportTile: AddSourceTile? {
        switch umbrella.id {
        case "anthropic": .claudeExport
        case "openai": .chatgptExport
        case "google": .geminiExport
        default: nil
        }
    }
    private var editorRows: [PageEditor] {
        let ids = Set(umbrella.ways.map(\.id) + umbrella.ways.flatMap(\.setup))
        return (editors.editors?.rows ?? []).filter { ids.contains($0.harness) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                DetailHeader(title: umbrella.label, blurb: summary.line(now: Date()), backLabel: backLabel,
                             onShowList: onClose, closeHelp: Copy.Projects.closeHelp, onClose: onClose) {
                    LogoTile(logo: umbrella.logo, name: umbrella.label)
                }
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    SectionLabel(Copy.AgentsPage.products)
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(umbrella.ways.enumerated()), id: \.element.id) { index, way in
                            if index > 0 { SettingsDivider() }
                            ConnectionLine(logo: nil, name: way.label, systemFallback: "app.connected.to.app.below.fill",
                                           detail: way.connects.compactMap(Copy.AgentsPage.connectsWord)
                                               .joined(separator: " · ")) { EmptyView() }
                        }
                    }
                    .settingsCardSurface()
                }
                if !editorRows.isEmpty, let response = editors.editors {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        SectionLabel(Copy.AgentsPage.trust)
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(editorRows) { agent in
                                ConnectionLine(logo: nil, name: agent.label, systemFallback: "pencil") {
                                    Picker(Copy.AgentsPage.trust, selection: Binding(
                                        get: { response.isTrusted(agent.harness) },
                                        set: { on in Task { await editors.set(agent.harness, on: on) } })) {
                                        Text(Copy.AgentsPage.writesAtOnce).tag(true)
                                        Text(Copy.AgentsPage.proposes).tag(false)
                                    }
                                    .pickerStyle(.menu)
                                    .labelsHidden()
                                    .fixedSize()
                                    .disabled(editors.busy.contains(agent.harness))
                                }
                            }
                        }
                        .settingsCardSurface()
                    }
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    if let harness = setupHarness {
                        NeutralButton(title: copied ? Copy.AgentsPage.copied : Copy.AgentsPage.copyPrompt,
                                      systemImage: "doc.on.doc", size: .compact) { copySetup(harness) }
                    }
                    if let tile = exportTile {
                        TextButton(title: Copy.AgentsPage.importExport) { router?.routeToAddSource(tile) }
                    }
                }
                if umbrella.ways.contains(where: { $0.connects.contains("hooks") }) {
                    AutoRecallGroup()
                }
            }
            .padding(.horizontal, CicadaTheme.spacingGutter)
            .padding(.bottom, CicadaTheme.spacingXL)
        }
        .task { await editors.load() }
    }

    private func copySetup(_ harness: String) {
        Task { @MainActor in
            guard let setup = try? await APIClient.shared.fetchAgentSetup(harness: harness) else { return }
            let text = setup.prompt ?? setup.display.joined(separator: "\n")
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
            copied = true
        }
    }
}

/// *Add an agent token* (G213): a name, then the one paragraph the agent needs — shown once, copied on a click.
struct AddAgentTokenSheet: View {
    var onClose: () -> Void
    @State private var name = ""
    @State private var created: AgentTokenCreated?
    @State private var busy = false
    @State private var problem: String?
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text(Copy.AgentsPage.addToken).font(CicadaTheme.titleFont).foregroundStyle(CicadaTheme.textPrimary)
            if let created {
                Text(Copy.AgentsPage.shownOnce)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                ScrollView {
                    Text(created.prompt)
                        .font(CicadaTheme.font(size: 12, weight: .regular, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(CicadaTheme.spacingMD)
                }
                .frame(maxHeight: CicadaTheme.scaled(220))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
                .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
                HStack {
                    Spacer()
                    NeutralButton(title: copied ? Copy.AgentsPage.copied : Copy.AgentsPage.copy,
                                  systemImage: "doc.on.doc", size: .compact) {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(created.prompt, forType: .string)
                        copied = true
                    }
                    NeutralButton(title: Copy.Devices.done, size: .compact) { onClose() }
                }
            } else {
                TextField(Copy.AgentsPage.tokenName, text: $name)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(make)
                if let problem {
                    Text(problem).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    Spacer()
                    TextButton(title: Copy.DevicesPage.cancel) { onClose() }
                    NeutralButton(title: Copy.AgentsPage.make, size: .compact,
                                  isDisabled: busy || name.trimmingCharacters(in: .whitespaces).isEmpty, action: make)
                }
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(520))
        .background(CicadaTheme.background)
    }

    private func make() {
        let value = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, !busy else { return }
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do {
                created = try await APIClient.shared.createAgentToken(name: value)
            } catch {
                problem = ConnectionModelText.detail(error)?.text ?? error.localizedDescription
            }
        }
    }
}
