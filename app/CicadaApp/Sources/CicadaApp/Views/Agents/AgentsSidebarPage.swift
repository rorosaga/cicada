import AppKit
import SwiftUI

/// The Agents page (ruling 36 D6, G217; ⌘9, appended so no shortcut moved — DR-22): every agent that reads and writes
/// Cicada, one row per provider umbrella from `GET /providers` — `LogoTile` · name · where · last seen · its
/// conversations · a dot and one word (`/agents/live`, polled every 3 s while the page shows). A row opens its detail
/// (DR-74): the products under the umbrella and how each connects, its chat export's import, whether its page edits
/// write at once or propose (G198's trust list), *Copy setup prompt*, and — for a harness with hooks — *Remembers
/// automatically*. *Add an agent token* (DR-75) makes a G213 token for a personal agent that cannot use MCP and shows
/// its one paragraph once. It replaced the Agents page; that page's anchors land here (`SettingsSection.retired`).
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
        } list: { plan in
            list(narrow: plan.listStyle != .wide)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        } detail: { plan in
            if let umbrella = open {
                AgentDetailColumn(umbrella: umbrella, summary: AgentSummary.of(umbrella, live: live,
                                                                               sources: store.sourcesOverview.value ?? []),
                                  live: live,
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

    private func list(narrow: Bool) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(umbrellas.enumerated()), id: \.element.id) { index, umbrella in
                        if index > 0 { SettingsDivider() }
                        let summary = AgentSummary.of(umbrella, live: live, sources: store.sourcesOverview.value ?? [])
                        Button { selected = umbrella.id } label: {
                            ConnectionLine(logo: umbrella.logo, name: umbrella.label, systemFallback: "sparkles",
                                           detail: summary.line(now: Date()),
                                           status: (summary.presence().word, summary.presence().on),
                                           detailLines: 1, statusBelowName: narrow) { EmptyView() }
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
            // The list starts under the eyebrow like every list page's (looks pass: a 40 pt top inset left a hole).
            .padding(narrow ? ListInsets.of(.triage)
                            : EdgeInsets(top: 0, leading: CicadaTheme.spacingGutter, bottom: CicadaTheme.spacingGutter,
                                         trailing: CicadaTheme.spacingGutter))
            .padding(.top, CicadaTheme.spacingSM)
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

    /// Connected (green) when seen just now, configured, with conversations, or seen before (the line says when); else
    /// Not connected.
    func presence(now: Date = Date()) -> Copy.Presence {
        Copy.Presence.of(seen: lastSeen, configured: connected, conversations: conversations, now: now)
    }

    /// "on this machine · 3 min ago · 12 conversations", or "… · last seen Oct 21 · …" — each part only when known.
    /// Where it was seen, never where it could connect: a row nothing has seen says nothing (ruling 39 — "on this
    /// machine" stood under nearly every row; the detail's Products say how each one connects).
    func line(now: Date) -> String {
        var parts: [String] = []
        let whereWord = via.flatMap { $0 == "remote" ? Copy.AgentsPage.connectsWord("remote") : Copy.AgentsPage.connectsWord("stdio") }
        if let whereWord { parts.append(whereWord) }
        if let lastSeen {
            parts.append(presence(now: now) == .connected ? Copy.AgentsPage.seen(lastSeen, now: now)
                                                          : Copy.AgentsPage.lastSeen(lastSeen))
        }
        if conversations > 0 { parts.append(Copy.AgentsPage.conversations(conversations)) }
        return parts.joined(separator: " · ")
    }

    /// A product's own mark when the set has one under its logical name (`claude-code`, `codex` → OpenAI's), else none.
    static func mark(_ id: String) -> String? { LogoImage.exists(name: id) ? id : nil }

    static func tokenLine(_ token: AgentToken) -> String {
        var parts: [String] = [token.scopes.joined(separator: ", ")]
        if let used = token.lastUsedAt.flatMap(ISODate.parse) { parts.append(Copy.AgentsPage.seen(used)) }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

/// The Products list of an umbrella's detail, pure (tested). A way that is two products (`remoteLabel`, ruling 39) is
/// two lines: the local app by its own name with how it connects here ("Claude Desktop · on this machine"), and the
/// remote surface by its name with the connector and the account's export ("claude.ai · from anywhere · by export") —
/// so the connector is never named after the Mac app.
enum AgentProducts {
    struct Line: Equatable, Identifiable {
        let id: String
        let wayId: String
        let name: String
        let connects: [String]
    }

    static let remoteConnects: Set<String> = ["remote", "export"]

    static func lines(_ ways: [ProviderWay]) -> [Line] {
        ways.flatMap { way -> [Line] in
            guard let remote = way.remoteLabel, !remote.isEmpty else {
                return [Line(id: way.id, wayId: way.id, name: way.label, connects: way.connects)]
            }
            let here = way.connects.filter { !remoteConnects.contains($0) }
            let there = way.connects.filter { remoteConnects.contains($0) }
            var out: [Line] = []
            if !here.isEmpty { out.append(Line(id: way.id, wayId: way.id, name: way.label, connects: here)) }
            if !there.isEmpty { out.append(Line(id: "\(way.id)#remote", wayId: way.id, name: remote, connects: there)) }
            return out
        }
    }
}

/// One umbrella's detail (DR-74): its products and how each connects, its chat export, page edits, setup prompt.
private struct AgentDetailColumn: View {
    let umbrella: ProviderUmbrella
    let summary: AgentSummary
    let live: [AgentLiveRow]
    let backLabel: String?
    let onClose: () -> Void

    @Environment(AppRouter.self) private var router: AppRouter?
    @State private var editors = PageEditorsModel()
    @State private var copied = false
    /// The connect steps the old Agents settings page drew (Connect for me, Open in Cursor, the copied prompt, the commands),
    /// for the product chosen below (install.md and `make doctor` name them).
    @State private var setup = AgentsSetupModel()
    @State private var product: String?
    @State private var linkFor: RemoteApp?
    private let runtime = CicadaRuntime.current

    /// The catalog's pills this umbrella's products are (Claude Code, the Claude app …), else Another agent for a
    /// product that connects through the generic prompt.
    private var entries: [AgentCatalogEntry] {
        var out: [AgentCatalogEntry] = []
        for way in umbrella.ways {
            let entry = AgentCatalog.entry(for: way.id) ?? (way.setup.contains("other") ? AgentCatalog.entry(for: "other") : nil)
            if let entry, !out.contains(where: { $0.id == entry.id }) { out.append(entry) }
        }
        return out
    }
    private var entry: AgentCatalogEntry? { entries.first { $0.id == product } ?? entries.first }

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
                DetailHeader(title: umbrella.label, blurb: Optional(summary.line(now: Date())).flatMap { $0.isEmpty ? nil : $0 }, backLabel: backLabel,
                             onShowList: onClose, closeHelp: Copy.Projects.closeHelp, onClose: onClose) {
                    LogoTile(logo: umbrella.logo, name: umbrella.label)
                }
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    SectionLabel(Copy.AgentsPage.products)
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(AgentProducts.lines(umbrella.ways).enumerated()), id: \.element.id) { index, line in
                            if index > 0 { SettingsDivider() }
                            ConnectionLine(logo: AgentSummary.mark(line.wayId), name: line.name, systemFallback: "terminal",
                                           detail: line.connects.compactMap(Copy.AgentsPage.connectsWord)
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
                                ConnectionLine(logo: AgentSummary.mark(agent.harness), name: agent.label,
                                               systemFallback: "terminal") {
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
                if let entry {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        if entries.count > 1 {
                            Picker(Copy.AgentsPage.products, selection: Binding(get: { entry.id },
                                                                               set: { product = $0 })) {
                                ForEach(entries, id: \.id) { Text($0.name).tag($0.id) }
                            }
                            .pickerStyle(.segmented)
                            .labelsHidden()
                            .fixedSize()
                        }
                        AgentSetupSteps(
                            entry: entry,
                            steps: AgentSteps.steps(for: entry, setups: setup.setups,
                                                    wiring: setup.wiring?.agents.first { $0.id == entry.id },
                                                    live: live.first { $0.id == entry.id },
                                                    remoteReady: setup.remote?.enabled == true
                                                        && setup.remote?.effectiveUrl != nil),
                            header: AgentSteps.header(for: entry, wiring: setup.wiring?.agents.first { $0.id == entry.id }),
                            honesty: AgentSteps.honesty(for: entry),
                            connected: live.contains { $0.id == entry.id && $0.connected },
                            binaries: Set(setup.wiring?.agents.compactMap(\.binary) ?? []),
                            runtime: runtime,
                            memoryRoot: setup.memoryRoot,
                            deeplink: AgentSetupCatalog.all(runtime: runtime, memoryRoot: setup.memoryRoot)
                                .first { $0.id == entry.id }?.deeplink?.url,
                            onConnected: { Task { await setup.refreshWiring() } },
                            onOpenFromAnywhere: { router?.openSettings(.devices, row: .fromAnywhere) },
                            onCreateLink: { linkFor = $0 })
                    }
                    .padding(CicadaTheme.spacingMD)
                    .settingsCardSurface()
                    .task(id: entry.id) { await setup.select(entry) }
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    if entry == nil, let harness = setupHarness {
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
        .task { await setup.load() }
        .sheet(item: $linkFor) { app in
            NewConnectorSheet(initialApp: app) { linkFor = nil }
        }
    }

    private func copySetup(_ harness: String) {
        Task { @MainActor in
            guard let setup = try? await APIClient.shared.fetchAgentSetup(harness: harness) else { return }
            AppPasteboard.copy(setup.prompt ?? setup.display.joined(separator: "\n"))
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

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            Text(Copy.AgentsPage.addToken).font(CicadaTheme.titleFont).foregroundStyle(CicadaTheme.textPrimary)
            if let created {
                Text(Copy.AgentsPage.shownOnce)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                // The paragraph is something the person copies (DR-19): the one copy box.
                ScrollView { CommandBox(command: created.prompt) }
                    .frame(maxHeight: CicadaTheme.scaled(240))
                HStack {
                    Spacer()
                    NeutralButton(title: Copy.Devices.done, size: .compact) { onClose() }
                }
            } else {
                TextField("", text: $name)
                    .cicadaField(prompt: Copy.AgentsPage.tokenName, isEmpty: name.isEmpty)
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
