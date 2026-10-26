import AppKit
import SwiftUI

/// The state of the Sources page (G166). Last-known-good: a fetch that fails keeps the previous answer (the
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
        var setMethod: @MainActor (String, String) async throws -> AgentMethodWriteResponse
        var addPage: @MainActor (String) async throws -> AgentMethodPage
        /// G166 exploring — the signed-in switch (D2 amended). Last, with the live call as its default, so every
        /// existing `Deps(...)` stays source-compatible.
        var writeExplore: @MainActor (Bool) async throws -> ReadingSettingsResponse = {
            try await APIClient.shared.setReadingSettings(exploreSignedIn: $0)
        }
        /// G166 exploring — a Never explore patch `{site: true|false}` (D3).
        var writeNever: @MainActor ([String: Bool]) async throws -> ReadingSettingsResponse = {
            try await APIClient.shared.setReadingSettings(neverExplore: $0)
        }
        /// G71 (2026-10-16) — a YouTube list patch `{watch_later|history: true|false}`.
        var writeYouTube: @MainActor ([String: Bool]) async throws -> ReadingSettingsResponse = {
            try await APIClient.shared.setReadingSettings(youtubeLists: $0)
        }
        /// G206 — a saved-list patch `{x|instagram|linkedin: true|false}` (the Sources page's switch, 2026-10-23); the
        /// flag turns agent reading on with the first-use acknowledgement in the same call — and never a `sites` grant.
        var writeSaved: @MainActor ([String: Bool], Bool) async throws -> ReadingSettingsResponse = { lists, enable in
            try await APIClient.shared.setReadingSettings(agentEnabled: enable ? true : nil, acknowledge: enable,
                                                          savedLists: lists)
        }

        @MainActor static var live: Deps {
            Deps(fetch: { try await APIClient.shared.fetchReadingSettings() },
                 write: { on, sites, ack in
                     try await APIClient.shared.setReadingSettings(agentEnabled: on, sites: sites, acknowledge: ack)
                 },
                 prompt: { try await APIClient.shared.fetchReadingPrompt() },
                 fetchSites: { try await APIClient.shared.fetchReadingSites() },
                 fetchMethods: { try await APIClient.shared.fetchAgentMethods() },
                 setMethod: { try await APIClient.shared.setAgentMethod(job: $0, choice: $1) },
                 addPage: { try await APIClient.shared.addSkillPage(skill: $0) })
        }
    }

    /// How the person's agent reads pages, and (ruling 17, G178) how it watches videos. Same mechanism, same rows.
    static let job = "reading"
    static let watchJob = "watching"

    private(set) var settings: ReadingSettingsResponse?
    private(set) var sites: ReadingSitesResponse?
    private(set) var methods: AgentMethodJob?
    private(set) var watchMethods: AgentMethodJob?
    private(set) var note: String?
    private(set) var methodNote: String?
    /// The job whose group shows `methodNote` (the choice or the page add that made it).
    private(set) var methodNoteJob = ReadingAgentModel.job
    private(set) var busy = false
    private let deps: Deps

    init(deps: Deps) { self.deps = deps }
    convenience init() { self.init(deps: .live) }

    var enabled: Bool { settings?.agentEnabled ?? false }
    /// G166 exploring: on by default (D2 amended).
    var exploreSignedIn: Bool { settings?.exploreSignedIn ?? true }

    /// The sites the person said never to explore, in site order.
    var neverExplore: [String] { (settings?.neverExplore ?? [:]).keys.sorted() }

    /// Add (`true`) or lift (`false`) one site's Never explore. A name that is not a site is the server's 422 sentence.
    @discardableResult
    func setNeverExplore(_ site: String, _ on: Bool) async -> Bool {
        let key = site.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            .replacingOccurrences(of: "https://", with: "").replacingOccurrences(of: "http://", with: "")
            .replacingOccurrences(of: "www.", with: "").split(separator: "/").first.map(String.init) ?? ""
        guard !key.isEmpty else { return false }
        busy = true
        defer { busy = false }
        do {
            settings = try await deps.writeNever([key: on])
            note = nil
            return true
        } catch APIError.httpError(let code, let body) where code == 422 {
            note = ProjectWriteFailure.detail(body) ?? Copy.Reading.saveFailed
            return false
        } catch {
            note = Copy.Reading.saveFailed
            return false
        }
    }

    /// G206 — turn one site's saved list on or off. Refused (422, said in the backend's sentence) while agent reading is
    /// off or its acknowledgement is not current; on again lifts a sign-in pause.
    ///
    /// `acknowledge` (the first-use sheet's Turn on, in its saved-list mode) turns agent reading on with the
    /// acknowledgement and the list in one call — the site itself is never granted (review of #448).
    @discardableResult
    func setSavedList(_ site: String, _ on: Bool, acknowledge: Bool = false) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            settings = try await deps.writeSaved([site: on], acknowledge && on)
            note = nil
            return true
        } catch APIError.httpError(let code, let body) where code == 422 {
            note = ProjectWriteFailure.detail(body) ?? Copy.Reading.saveFailed
            return false
        } catch {
            note = Copy.Reading.saveFailed
            return false
        }
    }

    /// G71 — turn one YouTube list on or off. On again lifts a sign-in pause (Try again).
    @discardableResult
    func setYouTubeList(_ list: YouTubeList, _ on: Bool) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            settings = try await deps.writeYouTube([list.rawValue: on])
            note = nil
            return true
        } catch APIError.httpError(let code, let body) where code == 422 {
            note = ProjectWriteFailure.detail(body) ?? Copy.Reading.saveFailed
            return false
        } catch {
            note = Copy.Reading.saveFailed
            return false
        }
    }

    /// The signed-in switch: off explores in a private, cookie-less context; on uses the person's everyday session.
    @discardableResult
    func setExploreSignedIn(_ on: Bool) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            settings = try await deps.writeExplore(on)
            note = nil
            return true
        } catch {
            note = Copy.Reading.saveFailed
            return false
        }
    }

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
        await refreshMethods()
    }

    private func refreshMethods() async {
        if let all = try? await deps.fetchMethods() {
            methods = all.job(Self.job)
            watchMethods = all.job(Self.watchJob)
        }
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
    func choose(_ id: String, job: String = ReadingAgentModel.job) async {
        guard id != (job == Self.watchJob ? watchMethods : methods)?.chosen else { return }
        busy = true
        defer { busy = false }
        methodNoteJob = job
        do {
            let answer = try await deps.setMethod(job, id)
            if job == Self.watchJob { watchMethods = answer.job } else { methods = answer.job }
            methodNote = Copy.Reading.pageNote(answer.pageState)
        } catch APIError.httpError(let code, let body) where code == 409 || code == 422 {
            methodNote = ProjectWriteFailure.detail(body) ?? Copy.Reading.saveFailed
        } catch {
            methodNote = Copy.Reading.saveFailed
        }
    }

    /// "Add to your graph" for an installed skill that has no page yet.
    func addPage(_ skill: String, job: String = ReadingAgentModel.job) async {
        busy = true
        defer { busy = false }
        methodNoteJob = job
        do {
            let page = try await deps.addPage(skill)
            methodNote = Copy.Reading.pageNote(page.state ?? "created")
            await refreshMethods()
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

/// the Sources page (G166): "With an agent" (the person's own agent reads pages Cicada's reader could not, in
/// their own signed-in browser; off by default), "How your agent reads" (a choice the person makes — never something
/// Cicada detects) and "Sites that need your browser" (every site Cicada's reader could not read, each with its favicon,
/// a measured count and a switch). Turning on raises the first-use sheet and nothing changes until its button is pressed.
/// Direction D: group cards of Settings rows, neutral controls, the sheet's one prominent action.
///
/// Hyrum audit B23 (2026-10-22): while the switch is off, how the agent reads and watches waits under one fold (DR-39);
/// the choices are still the person's to make ahead, and a search hit or link on one opens the fold.
struct ReadingWebView: View {
    @State private var model = ReadingAgentModel()
    /// DR-39 — the person's own open or closed, per viewer, never synced. A landing opens it for this view only
    /// (`methodsLanded`), so following a link never rewrites what the person chose.
    @AppStorage("cicada.reading.methodsOpen") private var methodsStored = false
    @State private var methodsLanded = false
    private var methodsOpen: Bool { methodsStored || methodsLanded }
    @State private var showSheet = false
    /// The site whose switch raised the sheet: it rides the "Turn on" call.
    @State private var pendingSite: String?
    /// A reading skill whose "Install…" was clicked: its own detail opens here as the page's one sub-page (R-O5), since
    /// the Skills list shows only five and a lower-ranked skill has no card to open there (critic M5).
    @State private var openSkill: RecommendedSkill?
    /// G166 exploring — the Never explore field's draft.
    @State private var neverDraft = ""
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
            focus?.escapeBack = escapeBack(skillOpen: open != nil)
        }
        .onChange(of: focus?.landedNonce ?? 0) { _, _ in
            openSkill = nil
            if let row = focus?.landed, ReadingMethodsFold.holds(row) { methodsLanded = true }
        }
        // A landing from another page selects this one and lands in the same pass, before this view exists, so only the
        // row still washed (`highlighted`, the hold) counts here; a landing long past never reopens the fold.
        .onAppear { if let row = focus?.highlighted, ReadingMethodsFold.holds(row) { methodsLanded = true } }
        .onDisappear { focus?.escapeBack = nil }
    }

    /// Esc's "back" while a skill's detail is open — a typed helper, so `body` stays inside the type checker's
    /// release-build budget.
    private func escapeBack(skillOpen: Bool) -> (() -> Void)? {
        skillOpen ? { closeSkill() } : nil
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
        SettingsPage(heading: .reading) {
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
                    // G166 exploring (D2 amended): the person's signed-in session by default, off in one switch.
                    SettingsDivider()
                    SettingsRow(.readingExploreSignedIn, title: Copy.Explore.signedInTitle,
                                detail: Copy.Explore.signedInDetail) {
                        Toggle(Copy.Explore.signedInLabel, isOn: Binding(
                            get: { model.exploreSignedIn },
                            set: { on in Task { await model.setExploreSignedIn(on) } }))
                            .toggleStyle(.switch)
                            .labelsHidden()
                            .disabled(model.busy)
                    }
                }
            }
            youtubeGroup
            if model.enabled {
                methodsGroup
                watchMethodsGroup
            } else if model.methods != nil || model.watchMethods != nil {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    DisclosureHeader(title: Copy.Reading.methodsFold, isOpen: methodsOpen) {
                        if methodsOpen { methodsStored = false; methodsLanded = false } else { methodsStored = true }
                    }
                    if methodsOpen {
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                            methodsGroup
                            watchMethodsGroup
                        }
                    }
                }
            }
            sitesGroup
            neverExploreGroup
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
                introRow((model.methodNoteJob == ReadingAgentModel.job ? model.methodNote : nil) ?? Copy.Reading.methodsDetail, color: CicadaTheme.textSecondary)
                    .settingsRow(.readingMethods)
                ForEach(job.options) { option in
                    SettingsDivider()
                    methodRow(option, chosen: job.chosen == option.id, job: ReadingAgentModel.job)
                }
            }
            Text(Copy.Reading.methodsFooter)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// How your agent watches (ruling 17): the same choice for the video hand-off, one per job.
    @ViewBuilder private var watchMethodsGroup: some View {
        if let job = model.watchMethods {
            SettingsGroupCard(header: Copy.Reading.watchMethodsGroup) {
                introRow((model.methodNoteJob == ReadingAgentModel.watchJob ? model.methodNote : nil) ?? Copy.Reading.watchMethodsDetail, color: CicadaTheme.textSecondary)
                    .settingsRow(.watchingMethods)
                ForEach(job.options) { option in
                    SettingsDivider()
                    methodRow(option, chosen: job.chosen == option.id, job: ReadingAgentModel.watchJob)
                }
            }
            Text(Copy.Reading.methodsFooter)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func methodRow(_ option: AgentMethodOption, chosen: Bool, job: String) -> some View {
        SettingsRowShell(job == ReadingAgentModel.watchJob ? .watchingMethod(option.id) : .readingMethod(option.id)) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                Button {
                    Task { await model.choose(option.id, job: job) }
                } label: {
                    HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                        Image(systemName: chosen ? "largecircle.fill.circle" : "circle")
                            .font(CicadaTheme.icon(.inline))
                            .foregroundStyle(chosen ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                            .accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                                Text(option.title)
                                    .font(CicadaTheme.rowFont)
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
                .accessibilityLabel(job == ReadingAgentModel.watchJob ? Copy.Reading.watchRadioLabel(option.title)
                                 : Copy.Reading.methodRadioLabel(option.title))
                .accessibilityAddTraits(chosen ? [.isSelected] : [])
                Spacer(minLength: CicadaTheme.scaled(16))
                if option.isSkill { skillAction(option, job: job) }
            }
        }
    }

    @ViewBuilder private func skillAction(_ option: AgentMethodOption, job: String) -> some View {
        switch MethodRowWords.action(option) {
        case .openInGraph(let id):
            NeutralButton(title: Copy.Reading.openInGraph, size: .compact) { openPage(id) }
        case .addToGraph:
            NeutralButton(title: Copy.Reading.addToGraph, size: .compact, isDisabled: model.busy,
                          help: Copy.Reading.addToGraphHelp) {
                Task { await model.addPage(option.id, job: job) }
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

    // MARK: Your YouTube lists (G71, 2026-10-16)

    /// Shown only while agent reading is on: the lists ride the same first-use sheet and the same never-sign-in rule.
    @ViewBuilder private var youtubeGroup: some View {
        if model.enabled, let settings = model.settings {
            SettingsGroupCard(header: Copy.Reading.youtubeGroup) {
                introRow(Copy.Reading.youtubeIntro, color: CicadaTheme.textSecondary)
                    .settingsRow(.readingYouTube)
                ForEach(YouTubeList.allCases) { list in
                    SettingsDivider()
                    SettingsRowShell(.readingYouTubeList(list.rawValue)) {
                        HStack(alignment: .firstTextBaseline) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(YouTubeListWords.title(list))
                                    .font(CicadaTheme.bodyFont)
                                    .foregroundStyle(CicadaTheme.textPrimary)
                                Text(YouTubeListWords.detail(list, on: settings.youtubeLists.isOn(list),
                                                             status: settings.youtube))
                                    .font(CicadaTheme.captionFont)
                                    .foregroundStyle(CicadaTheme.textTertiary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            Spacer()
                            Toggle(YouTubeListWords.title(list), isOn: Binding(
                                get: { settings.youtubeLists.isOn(list) },
                                set: { on in Task { await model.setYouTubeList(list, on) } }))
                                .toggleStyle(.switch)
                                .labelsHidden()
                                .disabled(model.busy)
                        }
                    }
                }
            }
        }
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

    /// G166 exploring (D3): sites an agent never explores, machine-wide. Add one by name; remove one in a tap.
    @ViewBuilder private var neverExploreGroup: some View {
        SettingsGroupCard(header: Copy.Explore.neverGroup) {
            SettingsRow(.readingNeverExplore, title: Copy.Explore.neverTitle, detail: Copy.Explore.neverDetail) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    TextField(Copy.Explore.neverPlaceholder, text: $neverDraft)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: CicadaTheme.scaled(160))
                        .onSubmit { addNever() }
                    NeutralButton(title: Copy.Explore.neverAdd, size: .compact, help: Copy.Explore.neverAddHelp) {
                        addNever()
                    }
                    .disabled(neverDraft.trimmingCharacters(in: .whitespaces).isEmpty || model.busy)
                }
            }
            ForEach(model.neverExplore, id: \.self) { site in
                SettingsDivider()
                SettingsRowShell(.readingNever(site)) {
                    HStack {
                        Text(site)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                        Spacer()
                        NeutralButton(title: Copy.Explore.neverRemove, size: .compact,
                                      help: Copy.Explore.neverRemoveHelp) {
                            Task { await model.setNeverExplore(site, false) }
                        }
                    }
                }
            }
        }
    }

    private func addNever() {
        let draft = neverDraft
        Task { if await model.setNeverExplore(draft, true) { neverDraft = "" } }
    }

    private func siteRow(_ site: ReadingSite) -> some View {
        SettingsRowShell(.readingSite(site.site)) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                    SiteIcon(site: site.site, label: site.label)
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                        Text(site.label)
                            .font(CicadaTheme.rowFont)
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
    /// G206 — the sheet was raised by a saved list's switch: Turn on enables agent reading and that list, never the
    /// site's pages (review of #448: it granted the site and left the list off).
    var savedList = false
    /// 2026-10-26 — raised by a YouTube list's switch on the Sources page's YouTube row: Turn on enables agent reading
    /// with the acknowledgement, then that list.
    var youtubeList: YouTubeList? = nil
    let done: () -> Void
    @State private var understood = false
    @State private var failure: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach([Copy.Reading.sheetHow, Copy.Reading.sheetOnlyAsks, Copy.Reading.sheetInstruction,
                     Copy.Reading.sheetTerms, Copy.Reading.sheetExploring, Copy.Reading.sheetSaferExport],
                    id: \.self) { paragraph in
                Text(paragraph)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let label {
                Text(savedList ? Copy.Reading.sheetAlsoReadsList(label) : Copy.Reading.sheetAlsoAllows(label))
                    .font(CicadaTheme.rowFont)
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
                        let ok = if let youtubeList {
                            await model.setEnabled(true, acknowledge: true, site: nil)
                                ? await model.setYouTubeList(youtubeList, true) : false
                        } else if savedList, let site {
                            await model.setSavedList(site, true, acknowledge: true)
                        } else {
                            await model.setEnabled(true, acknowledge: true, site: site)
                        }
                        if ok { done() }
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

/// Which landings open Reading's method fold (Hyrum audit B23): the two groups and any one choice in them.
enum ReadingMethodsFold {
    static func holds(_ row: SettingsRowID) -> Bool {
        row == .readingMethods || row == .watchingMethods
            || row.item(of: "readingMethod") != nil || row.item(of: "watchingMethod") != nil
    }
}

/// Reading the web's switches as a sheet on the Sources page (D6 retired the Settings page; 2026-10-22 fix round):
/// the master switch behind the one-time versioned consent sheet (on by default once accepted), the signed-in session
/// (ruling 25), the YouTube lists, Never explore, how the agent reads and watches, and the sites that need the browser.
/// `ReadingWebView` itself, unchanged, with the Skills data it reads and a Done.
struct ReadingInBrowserSheet: View {
    var onClose: () -> Void
    @State private var skillsVM = SkillsViewModel()

    var body: some View {
        VStack(spacing: 0) {
            // G61 (owner 2026-10-26) — the quick add and every page's where-to-check, first: what is read lives above
            // the switches for how it is read.
            AddedSourcesSection()
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.top, CicadaTheme.spacingLG)
                .padding(.bottom, CicadaTheme.spacingMD)
            Divider()
            ReadingWebView()
                .environment(skillsVM)
                .task { await skillsVM.load() }
            HStack {
                Spacer()
                NeutralButton(title: Copy.Reading.done, size: .compact, shortcut: .cancelAction) { onClose() }
            }
            .padding(CicadaTheme.spacingMD)
        }
        .frame(width: CicadaTheme.scaled(680), height: CicadaTheme.scaled(700))
        .background(CicadaTheme.bgBase)
    }
}
