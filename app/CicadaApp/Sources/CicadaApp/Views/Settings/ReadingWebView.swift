import AppKit
import SwiftUI

/// The state of Settings → Reading the web (G166). Last-known-good: a fetch that fails keeps the previous answer (the
/// never-blank rule). Collaborators are injected so a test drives it with no network, like `AutoRecallModel`. Not a Store
/// domain: fetched when the page opens and refreshed after every write.
@MainActor
@Observable
final class ReadingAgentModel {
    struct Deps {
        var fetch: @MainActor () async throws -> ReadingSettingsResponse
        /// (master switch, a `{site: allowed}` patch, acknowledge)
        var write: @MainActor (Bool?, [String: Bool]?, Bool) async throws -> ReadingSettingsResponse
        var prompt: @MainActor () async throws -> String
        var fetchSites: @MainActor () async throws -> ReadingSitesResponse
        var fetchMethods: @MainActor () async throws -> AgentMethodsResponse
        var setMethod: @MainActor (String) async throws -> AgentMethodWriteResponse
        var addPage: @MainActor (String) async throws -> AgentMethodPage

        @MainActor static var live: Deps {
            Deps(fetch: { try await APIClient.shared.fetchReadingSettings() },
                 write: { on, sites, ack in
                     try await APIClient.shared.setReadingSettings(agentEnabled: on, sites: sites, acknowledge: ack)
                 },
                 prompt: { try await APIClient.shared.fetchReadingPrompt() },
                 fetchSites: { try await APIClient.shared.fetchReadingSites() },
                 fetchMethods: { try await APIClient.shared.fetchAgentMethods() },
                 setMethod: { try await APIClient.shared.setAgentMethod(job: ReadingAgentModel.job, choice: $0) },
                 addPage: { try await APIClient.shared.addSkillPage(skill: $0) })
        }
    }

    /// The one job today: how the person's agent reads pages.
    static let job = "reading"

    private(set) var settings: ReadingSettingsResponse?
    private(set) var sites: ReadingSitesResponse?
    private(set) var methods: AgentMethodJob?
    private(set) var note: String?
    private(set) var methodNote: String?
    private(set) var busy = false
    private let deps: Deps

    init(deps: Deps) { self.deps = deps }
    convenience init() { self.init(deps: .live) }

    var enabled: Bool { settings?.agentEnabled ?? false }

    /// The first-use sheet is for a person who has not acknowledged its current wording. Turning the switch back on
    /// after an off keeps the acknowledgement and the per-site choices (the server's rule), so it asks nothing.
    var needsFirstUseSheet: Bool { !(settings?.ackCurrent ?? false) }

    func load() async {
        do {
            settings = try await deps.fetch()
            note = nil
        } catch {
            if settings == nil { note = Copy.Reading.loadFailed }
        }
        await refreshSites()
        if let all = try? await deps.fetchMethods() { methods = all.job(Self.job) }
    }

    /// The switch and the acknowledgement only — what the Feed's "Let an agent read <site>" needs to decide whether to
    /// raise the first-use sheet (the sites list is a bank scan it does not need).
    func loadSettings() async {
        if let fresh = try? await deps.fetch() { settings = fresh }
    }

    func refreshSites() async {
        if let fresh = try? await deps.fetchSites() { sites = fresh }
    }

    /// Turning the switch off, or on with an acknowledgement given in the sheet (a current one is stored already). A
    /// `site` rides the same call: flipping a site while the switch is off is one call (acknowledgement, switch, site).
    func setEnabled(_ on: Bool, acknowledge: Bool = false, site: String? = nil) async -> Bool {
        await write(on: on, sites: site.map { [$0: true] }, acknowledge: acknowledge)
    }

    /// One site's switch. With the switch off (and a current acknowledgement already given) allowing a site turns the
    /// switch on in the same call; the first-use sheet is the view's job when the acknowledgement is not current.
    /// Turning a site on also lifts its "not signed in" pause on the server, so it doubles as "try again".
    func setSite(_ key: String, allowed: Bool) async -> Bool {
        await write(on: allowed && !enabled ? true : nil, sites: [key: allowed], acknowledge: false)
    }

    func promptText() async -> String? { try? await deps.prompt() }

    /// Choosing how the agent reads. The server files a chosen skill's page in the graph and says what happened.
    func choose(_ id: String) async {
        guard id != methods?.chosen else { return }
        busy = true
        defer { busy = false }
        do {
            let answer = try await deps.setMethod(id)
            methods = answer.job
            methodNote = Copy.Reading.pageNote(answer.pageState)
        } catch APIError.httpError(let code, let body) where code == 409 || code == 422 {
            methodNote = ProjectWriteFailure.detail(body) ?? Copy.Reading.saveFailed
        } catch {
            methodNote = Copy.Reading.saveFailed
        }
    }

    /// "Add to your graph" for an installed skill that has no page yet.
    func addPage(_ skill: String) async {
        busy = true
        defer { busy = false }
        do {
            let page = try await deps.addPage(skill)
            methodNote = Copy.Reading.pageNote(page.state ?? "created")
            if let all = try? await deps.fetchMethods() { methods = all.job(Self.job) }
        } catch APIError.httpError(let code, let body) where code == 409 || code == 404 {
            methodNote = ProjectWriteFailure.detail(body) ?? Copy.Reading.saveFailed
        } catch {
            methodNote = Copy.Reading.saveFailed
        }
    }

    private func write(on: Bool?, sites patch: [String: Bool]?, acknowledge: Bool) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            settings = try await deps.write(on, patch, acknowledge)
            note = nil
            await refreshSites()
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

/// Settings → Reading the web (G166): "With an agent" (the person's own agent reads pages Cicada's reader could not, in
/// their own signed-in browser; off by default), "How your agent reads" (a choice the person makes — never something
/// Cicada detects) and "Sites that need your browser" (every site Cicada's reader could not read, each with its favicon,
/// a measured count and a switch). Turning on raises the first-use sheet and nothing changes until its button is pressed.
/// Direction D: group cards of Settings rows, neutral controls, the sheet's one prominent action.
struct ReadingWebView: View {
    @State private var model = ReadingAgentModel()
    @State private var showSheet = false
    /// The site whose switch raised the sheet: it rides the "Turn on" call.
    @State private var pendingSite: String?
    /// A reading skill whose "Install…" was clicked: its own detail opens here as the page's one sub-page (R-O5), since
    /// the Skills list shows only five and a lower-ranked skill has no card to open there (critic M5).
    @State private var openSkill: RecommendedSkill?
    @Environment(Store.self) private var store
    @Environment(SkillsViewModel.self) private var skillsVM
    @Environment(SettingsFocus.self) private var focus: SettingsFocus?

    var body: some View {
        Group {
            if let skill = openSkill {
                SkillDetailView(skill: skill, section: .reading) { closeSkill() }
            } else {
                page
            }
        }
        // R-O5 — while the skill's detail is open, Esc goes back to this page instead of closing the panel.
        .onChange(of: openSkill?.id, initial: true) { _, open in
            focus?.escapeBack = open == nil ? nil : { closeSkill() }
        }
        .onChange(of: focus?.landedNonce ?? 0) { _, _ in openSkill = nil }
        .onDisappear { focus?.escapeBack = nil }
    }

    /// Back from a skill's detail: an install or a copied prompt may have changed what is installed, so both lists
    /// are read again.
    private func closeSkill() {
        openSkill = nil
        Task {
            await model.load()
            await skillsVM.load()
        }
    }

    private var page: some View {
        SettingsPage(section: .reading) {
            SettingsGroupCard(header: Copy.Reading.withAgentGroup) {
                SettingsRow(.readingAgent, title: Copy.Reading.switchTitle,
                            detail: model.note ?? Copy.Reading.switchDetail) {
                    Toggle(Copy.Reading.switchLabel, isOn: Binding(
                        get: { model.enabled || (showSheet && pendingSite == nil) },
                        set: { on in
                            if !on {
                                Task { _ = await model.setEnabled(false) }
                            } else if model.needsFirstUseSheet {
                                pendingSite = nil
                                showSheet = true
                            } else {
                                Task { _ = await model.setEnabled(true) }
                            }
                        }))
                        .toggleStyle(.switch)
                        .labelsHidden()
                        .disabled(model.settings == nil || model.busy)
                        .help(ReadingSwitchHelp.text(model.settings))
                }
                if model.enabled, let settings = model.settings {
                    SettingsDivider()
                    promptRow(settings)
                }
            }
            methodsGroup
            sitesGroup
        }
        // R-HS16 — a sheet centred on the window, never a popover at the panel's edge.
        .sheet(isPresented: $showSheet) {
            SettingsSheet(title: Copy.Reading.sheetTitle, onClose: { showSheet = false }) {
                ReadingFirstUseSheet(model: model, site: pendingSite, label: siteLabel(pendingSite)) { showSheet = false }
            }
        }
        .task(id: store.isConnected) { await model.load() }
    }

    private func siteLabel(_ key: String?) -> String? {
        guard let key else { return nil }
        return model.sites?.sites.first { $0.site == key }?.label ?? key
    }

    // MARK: How your agent reads

    @ViewBuilder private var methodsGroup: some View {
        if let job = model.methods {
            SettingsGroupCard(header: Copy.Reading.methodsGroup) {
                introRow(model.methodNote ?? Copy.Reading.methodsDetail, color: CicadaTheme.textSecondary)
                    .settingsRow(.readingMethods)
                ForEach(job.options) { option in
                    SettingsDivider()
                    methodRow(option, chosen: job.chosen == option.id)
                }
            }
            Text(Copy.Reading.methodsFooter)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func methodRow(_ option: AgentMethodOption, chosen: Bool) -> some View {
        SettingsRowShell(.readingMethod(option.id)) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                Button {
                    Task { await model.choose(option.id) }
                } label: {
                    HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                        Image(systemName: chosen ? "largecircle.fill.circle" : "circle")
                            .font(CicadaTheme.icon(.inline))
                            .foregroundStyle(chosen ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                            .accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                                Text(option.title)
                                    .font(CicadaTheme.font(size: 13, weight: .medium))
                                    .foregroundStyle(CicadaTheme.textPrimary)
                                if option.isSkill { Tag(text: Copy.Reading.skillTag) }
                            }
                            Text(MethodRowWords.detail(option))
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .multilineTextAlignment(.leading)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .disabled(model.busy)
                .accessibilityLabel(Copy.Reading.methodRadioLabel(option.title))
                .accessibilityAddTraits(chosen ? [.isSelected] : [])
                Spacer(minLength: CicadaTheme.scaled(16))
                if option.isSkill { skillAction(option) }
            }
        }
    }

    @ViewBuilder private func skillAction(_ option: AgentMethodOption) -> some View {
        switch MethodRowWords.action(option) {
        case .openInGraph(let id):
            NeutralButton(title: Copy.Reading.openInGraph, size: .compact) { openPage(id) }
        case .addToGraph:
            NeutralButton(title: Copy.Reading.addToGraph, size: .compact, isDisabled: model.busy,
                          help: Copy.Reading.addToGraphHelp) {
                Task { await model.addPage(option.id) }
            }
        case .install:
            NeutralButton(title: Copy.Reading.installSkill, size: .compact, help: Copy.Reading.installSkillHelp) {
                openSkill = option.skill
            }
        case .none:
            EmptyView()
        }
    }

    @Environment(AppRouter.self) private var router

    private func openPage(_ id: String) { router.routeToEntity(id) }

    /// A group's opening sentence, padded like a row. The caller adds the landing anchor (the index lint reads it
    /// spelled out at the call site).
    private func introRow(_ text: String, color: Color) -> some View {
        Text(text)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, CicadaTheme.spacingSM + CicadaTheme.scaled(2))
            .padding(.horizontal, CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: Sites that need your browser

    @ViewBuilder private var sitesGroup: some View {
        SettingsGroupCard(header: Copy.Reading.sitesGroup) {
            introRow(Copy.Reading.sitesIntro, color: CicadaTheme.textSecondary)
                .settingsRow(.readingSites)
            if let list = model.sites?.sites, !list.isEmpty {
                ForEach(list) { site in
                    SettingsDivider()
                    siteRow(site)
                }
            } else if model.sites != nil {
                SettingsDivider()
                SettingsRowShell(.readingSitesEmpty) {
                    Text(Copy.Reading.sitesEmpty)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        if model.sites?.sites.isEmpty == false {
            Text(Copy.Reading.sitesIconNote)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func siteRow(_ site: ReadingSite) -> some View {
        SettingsRowShell(.readingSite(site.site)) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                    SiteIcon(site: site.site, label: site.label)
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                        Text(site.label)
                            .font(CicadaTheme.font(size: 13, weight: .medium))
                            .foregroundStyle(CicadaTheme.textPrimary)
                        Text(ReadingSiteWords.line(site))
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: CicadaTheme.scaled(16))
                    Toggle(Copy.Reading.siteSwitchLabel(site.label), isOn: Binding(
                        get: { ReadingSiteWords.switchOn(site) },
                        set: { on in flip(site, on: on) }))
                        .toggleStyle(.switch)
                        .labelsHidden()
                        .disabled(model.settings == nil || model.busy)
                }
                if ReadingSiteWords.isPaused(site) {
                    HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                        Text(Copy.Reading.needsLoginNote)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: CicadaTheme.scaled(16))
                        NeutralButton(title: Copy.Reading.tryAgain, size: .compact, isDisabled: model.busy,
                                      help: Copy.Reading.tryAgainHelp) {
                            Task { _ = await model.setSite(site.site, allowed: true) }
                        }
                    }
                    .padding(.leading, CicadaTheme.scaled(30))
                }
            }
        }
    }

    private func flip(_ site: ReadingSite, on: Bool) {
        if on, model.needsFirstUseSheet {
            pendingSite = site.site
            showSheet = true
        } else {
            Task { _ = await model.setSite(site.site, allowed: on) }
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

/// The first-use sheet (spec §7.2): what asking does, what Cicada does not promise, the sites' terms and an
/// "I understand" that must be ticked before the button works (DR-41: 45 % and a `.help` saying why). Nothing changes
/// until "Turn on". There is no site picker: a site is switched on in the list, and when that raised this sheet the
/// one line says so and the switch rides the same call. It carries Cicada's instruction to the agent (no credentials
/// typed, nothing posted, messaged or changed) together with the honest limit that Cicada can't see or enforce what
/// happens in the browser — an instruction, never a promise (ruling 14, R-RW8). Internal so the Feed's "Let an agent
/// read <site>" raises the same sheet.
struct ReadingFirstUseSheet: View {
    let model: ReadingAgentModel
    let site: String?
    let label: String?
    let done: () -> Void
    @State private var understood = false
    @State private var failure: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach([Copy.Reading.sheetHow, Copy.Reading.sheetOnlyAsks, Copy.Reading.sheetInstruction,
                     Copy.Reading.sheetTerms, Copy.Reading.sheetSaferExport], id: \.self) { paragraph in
                Text(paragraph)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let label {
                Text(Copy.Reading.sheetAlsoAllows(label))
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
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
                        if await model.setEnabled(true, acknowledge: true, site: site) { done() }
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

/// The master switch's `.help`, pure: why it can't be read, or why it reads off after an older acknowledgement
/// (the sheet's wording changed, so an earlier "I understand" no longer counts — critic L6(b)); else nothing.
enum ReadingSwitchHelp {
    static func text(_ settings: ReadingSettingsResponse?) -> String {
        guard let settings else { return Copy.Reading.loadFailed }
        if settings.ackedAt != nil, !settings.ackCurrent { return Copy.Reading.reAskHelp }
        return ""
    }
}
