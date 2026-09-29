import SwiftUI

/// The state of Settings → Agents → "Reading pages" (G166). Last-known-good: a fetch that fails keeps the previous
/// answer (the never-blank rule). Collaborators are injected so a test drives it with no network, like
/// `AutoRecallModel`. Not a Store domain: fetched when the page opens and after every write, which answers with the new
/// settings.
@MainActor
@Observable
final class ReadingAgentModel {
    struct Deps {
        var fetch: @MainActor () async throws -> ReadingSettingsResponse
        var write: @MainActor (Bool?, [String]?, Bool) async throws -> ReadingSettingsResponse
        var prompt: @MainActor () async throws -> String

        @MainActor static var live: Deps {
            Deps(fetch: { try await APIClient.shared.fetchReadingSettings() },
                 write: { on, hosts, ack in
                     try await APIClient.shared.setReadingSettings(agentEnabled: on, agentHosts: hosts, acknowledge: ack)
                 },
                 prompt: { try await APIClient.shared.fetchReadingPrompt() })
        }
    }

    private(set) var settings: ReadingSettingsResponse?
    private(set) var note: String?
    private(set) var busy = false
    private let deps: Deps

    init(deps: Deps) { self.deps = deps }
    convenience init() { self.init(deps: .live) }

    var enabled: Bool { settings?.agentEnabled ?? false }

    /// The first-use sheet is for a person who has not acknowledged its current wording. Turning the switch back on
    /// after an off keeps the acknowledgement and the per-site choices (the server's rule), so it asks nothing.
    var needsFirstUseSheet: Bool { !(settings?.ackCurrent ?? false) }

    /// The sites already allowed, which the sheet opens with ticked so a re-acknowledgement never drops them.
    var heldHosts: Set<String> { Set(settings?.agentHosts ?? []) }

    func load() async {
        do {
            settings = try await deps.fetch()
            note = nil
        } catch {
            if settings == nil { note = Copy.Reading.loadFailed }
        }
    }

    /// Turning the switch off, or on with an acknowledgement given in the sheet (a current one is sent with it).
    func setEnabled(_ on: Bool, acknowledge: Bool = false, hosts: [String]? = nil) async -> Bool {
        await write(on: on, hosts: hosts, acknowledge: acknowledge)
    }

    func setHost(_ key: String, allowed: Bool) async {
        var held = settings?.agentHosts ?? []
        held.removeAll { $0 == key }
        if allowed { held.append(key) }
        _ = await write(on: nil, hosts: held, acknowledge: false)
    }

    func promptText() async -> String? { try? await deps.prompt() }

    private func write(on: Bool?, hosts: [String]?, acknowledge: Bool) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            settings = try await deps.write(on, hosts, acknowledge)
            note = nil
            return true
        } catch APIError.httpError(let code, let body) where code == 409 || code == 422 {
            note = ProjectWriteFailure.detail(body) ?? Copy.Reading.saveFailed
            return false
        } catch {
            note = Copy.Reading.saveFailed
            return false
        }
    }
}

/// Settings → Agents → "Reading pages" (G166, spec §7.2): "Let an agent read pages for you" — off by default. The
/// person's own agent (Claude Code or Codex with a browser skill, or the Claude and ChatGPT apps) reads the pages they
/// choose with "Ask an agent", in their own signed-in session. Turning it on raises the first-use sheet and nothing
/// changes until its button is pressed; the five per-site switches (all off) sit in the sheet and, once on, in rows
/// here. Direction D: one group card of Settings rows, neutral controls, the sheet's one prominent action.
struct ReadingAgentGroup: View {
    @State private var model = ReadingAgentModel()
    @State private var showSheet = false
    @Environment(Store.self) private var store

    var body: some View {
        SettingsGroupCard(header: Copy.Reading.group) {
            SettingsRow(.agentsReading, title: Copy.Reading.switchTitle,
                        detail: model.note ?? Copy.Reading.switchDetail) {
                Toggle(Copy.Reading.switchLabel, isOn: Binding(
                    get: { model.enabled || showSheet },
                    set: { on in
                        if !on {
                            Task { _ = await model.setEnabled(false) }
                        } else if model.needsFirstUseSheet {
                            showSheet = true
                        } else {
                            // Acknowledged already: the sites are kept, so none is sent.
                            Task { _ = await model.setEnabled(true) }
                        }
                    }))
                    .toggleStyle(.switch)
                    .labelsHidden()
                    .disabled(model.settings == nil || model.busy)
                    .help(model.settings == nil ? Copy.Reading.loadFailed : "")
            }
            if model.enabled, let settings = model.settings {
                ForEach(settings.hostSwitches) { site in
                    SettingsDivider()
                    hostRow(site, settings: settings)
                }
                SettingsDivider()
                promptRow(settings)
            }
        }
        // R-HS16 — a sheet centred on the window, never a popover at the panel's edge.
        .sheet(isPresented: $showSheet) {
            SettingsSheet(title: Copy.Reading.sheetTitle, onClose: { showSheet = false }) {
                ReadingFirstUseSheet(model: model) { showSheet = false }
            }
        }
        .task(id: store.isConnected) { await model.load() }
    }

    private func hostRow(_ site: ReadingHostSwitch, settings: ReadingSettingsResponse) -> some View {
        SettingsRowShell(.readingHost(site.key)) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(site.label)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(site.note ?? Copy.Reading.hostSwitchDetail)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: CicadaTheme.scaled(16))
                Toggle(Copy.Reading.hostSwitchLabel(site.label), isOn: Binding(
                    get: { settings.agentHosts.contains(site.key) },
                    set: { on in Task { await model.setHost(site.key, allowed: on) } }))
                    .toggleStyle(.switch)
                    .labelsHidden()
                    .disabled(model.busy)
            }
        }
    }

    private func promptRow(_ settings: ReadingSettingsResponse) -> some View {
        SettingsRowShell(.readingPrompt) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                Text(settings.lastAgentRead.flatMap { ReadWords.day($0) }.map(Copy.Reading.lastRead)
                     ?? Copy.Reading.copyPromptHelp)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: CicadaTheme.scaled(16))
                NeutralButton(title: Copy.Reading.copyPrompt, size: .compact, help: Copy.Reading.copyPromptHelp) {
                    Task {
                        if let text = await model.promptText() {
                            AppPasteboard.copy(text)
                            store.toast = Copy.Reading.promptCopied
                        }
                    }
                }
            }
        }
    }
}

/// A padded row body that is a landing anchor, for rows whose whole layout is their own.
private struct SettingsRowShell<Content: View>: View {
    let id: SettingsRowID
    @ViewBuilder var content: () -> Content

    init(_ id: SettingsRowID, @ViewBuilder content: @escaping () -> Content) {
        self.id = id
        self.content = content
    }

    var body: some View {
        content()
            .padding(.vertical, CicadaTheme.spacingSM + CicadaTheme.scaled(2))
            .padding(.horizontal, CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
            .settingsRow(id)
    }
}

/// The first-use sheet (spec §7.2): what asking does, what Cicada does not promise, the sites' terms, the five per-site
/// switches (all off) and an "I understand" that must be ticked before the button works (DR-41: 45 % and a `.help`
/// saying why). Nothing changes until "Turn on". It does not say an agent never posts, messages or fills a form:
/// Cicada cannot enforce that, so it does not promise it.
private struct ReadingFirstUseSheet: View {
    let model: ReadingAgentModel
    let done: () -> Void
    @State private var understood = false
    @State private var sites: Set<String>
    @State private var failure: String?

    init(model: ReadingAgentModel, done: @escaping () -> Void) {
        self.model = model
        self.done = done
        _sites = State(initialValue: model.heldHosts)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach([Copy.Reading.sheetHow, Copy.Reading.sheetOnlyAsks, Copy.Reading.sheetTerms,
                     Copy.Reading.sheetSaferExport], id: \.self) { paragraph in
                Text(paragraph)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(Copy.Reading.sheetSites)
                .font(CicadaTheme.font(size: 13, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                ForEach(model.settings?.hostSwitches ?? []) { site in
                    Toggle(site.label, isOn: Binding(
                        get: { sites.contains(site.key) },
                        set: { on in if on { sites.insert(site.key) } else { sites.remove(site.key) } }))
                        .toggleStyle(.checkbox)
                        .font(CicadaTheme.bodyFont)
                        .help(site.note ?? "")
                }
            }
            Toggle(Copy.Reading.sheetUnderstand, isOn: $understood)
                .toggleStyle(.checkbox)
                .font(CicadaTheme.font(size: 13, weight: .medium))
            if let failure {
                Text(failure)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                TextButton(title: Copy.Reading.sheetNotNow, action: done)
                PrimaryActionButton(title: Copy.Reading.sheetTurnOn) {
                    Task {
                        let hosts = (model.settings?.hostSwitches ?? []).map(\.key).filter { sites.contains($0) }
                        if await model.setEnabled(true, acknowledge: true, hosts: hosts) { done() }
                        else { failure = model.note }
                    }
                }
                .disabled(!understood || model.busy)
                .opacity(understood ? 1 : NeutralButton.disabledOpacity)
                .help(understood ? "" : Copy.Reading.sheetTurnOnHelp)
            }
        }
    }
}
