import AppKit
import SwiftUI

// G230 — GitHub's row on the Sources page: connecting with a code (owner 2026-11-03: "why are you asking for a token
// for github? cant we just do oauth? like a connect?"), then the repositories the person owns, each with its page —
// made on sync, never added by hand (owner 2026-11-03: "there shouldn't be added manually, always sync and make their
// initial markdowns") — and the projects it belongs to. Linking a repository to a project happens on either page
// (`RepositoryCard`, `ProjectRepositoriesSection`): the rows here only open them.
//
// Not a Store domain: `GET /sources/github/connect` and `GET /sources/github/repos` are read when the panel opens and
// after every step, kept here in memory (CLAUDE.md, Sync).
//
// DR-40 (one primary per step — Connect, then Install — every other control a `NeutralButton` or a `TextButton`),
// DR-47 (`SectionLabel`), DR-50 (the empty list said in words), DR-56 (the code in the app's monospaced type),
// DR-71 (theme tokens only, light and dark).

/// The pure decisions: what a row says.
enum GitHubReposLogic {
    /// "Private · Python · Notes." — the row's second line.
    static func detail(_ repo: RepoRow) -> String {
        Eyebrow.text(repo.isPrivate ? Copy.GitHub.isPrivate : "", repo.archived ? Copy.GitHub.isArchived : "",
                     repo.fork ? Copy.GitHub.isFork : "", repo.language ?? "", repo.description ?? "")
    }

    /// The projects a row shows (at most two), and how many more.
    static func projects(_ repo: RepoRow, limit: Int = 2) -> (shown: [RepoProject], more: Int) {
        (Array(repo.projects.prefix(limit)), max(0, repo.projects.count - limit))
    }
}

/// The repository list's state with no view in it. Every call goes through `Deps`, so tests run with no network.
@MainActor
@Observable
final class GitHubReposModel {
    struct Deps {
        var fetch: @MainActor () async throws -> RepoLists
        var project: @MainActor (String, String?, Bool) async throws -> RepoProjectResult

        @MainActor static var live: Deps {
            Deps(fetch: { try await APIClient.shared.fetchGitHubRepos() },
                 project: { try await APIClient.shared.makeRepoProject(fullName: $0, project: $1, remove: $2) })
        }
    }

    private(set) var lists = RepoLists()
    private(set) var loaded = false
    /// Why a read failed (the list keeps what it had).
    private(set) var note: String?
    @ObservationIgnored private let deps: Deps

    init(deps: Deps) { self.deps = deps }
    convenience init() { self.init(deps: .live) }

    func load() async {
        do {
            lists = try await deps.fetch()
            loaded = true
            note = nil
        } catch {
            note = Copy.GitHub.couldNotRead
        }
    }

    static func describe(_ error: Error) -> String {
        if case APIError.httpError(_, let body) = error, let detail = ServerDetail.sentence(body) { return detail }
        return Copy.GitHub.failed
    }
}

// MARK: - Connecting with a code

/// Where the connect panel is, decided from the backend's answer alone.
enum GitHubConnectStep: Equatable {
    /// This build's GitHub app is not registered: the token is the way in.
    case unavailable
    case disconnected
    /// The code is on screen; the panel asks the backend every `interval` seconds.
    case code(GitHubConnectCode)
    /// Connected by code, but Cicada is not installed on the person's account: their repositories are out of reach.
    case install(url: String)
    /// Connected by code, but the sign-in lapsed (its refresh token expired or was revoked): connect again.
    case reconnect
    case connected(byToken: Bool)

    static func from(_ status: GitHubConnectStatus) -> GitHubConnectStep {
        if let code = status.pending { return .code(code) }
        if status.connected {
            if status.how == "app", status.reconnect { return .reconnect }
            if status.how == "app", status.installed == false, let url = status.installUrl { return .install(url: url) }
            return .connected(byToken: status.how == "token")
        }
        return status.available ? .disconnected : .unavailable
    }

    /// The whole minutes a code has left at `now` (seconds since 1970).
    static func minutesLeft(_ code: GitHubConnectCode, now: Double) -> Int {
        max(0, Int(((Double(code.expiresAt) - now) / 60).rounded(.up)))
    }
}

@MainActor
@Observable
final class GitHubConnectModel {
    struct Deps {
        var status: @MainActor () async throws -> GitHubConnectStatus
        var start: @MainActor () async throws -> GitHubConnectCode
        var poll: @MainActor () async throws -> GitHubConnectPoll
        var installation: @MainActor () async throws -> GitHubConnectStatus
        var cancel: @MainActor () async throws -> Void
        var sync: @MainActor () async throws -> ConnectorSyncResult
        var disconnect: @MainActor () async throws -> Void
        var open: @MainActor (URL) -> Void
        var sleep: @MainActor (Int) async -> Void

        @MainActor static var live: Deps {
            Deps(status: { try await APIClient.shared.fetchGitHubConnect() },
                 start: { try await APIClient.shared.startGitHubConnect() },
                 poll: { try await APIClient.shared.pollGitHubConnect() },
                 installation: { try await APIClient.shared.checkGitHubInstallation() },
                 cancel: { try await APIClient.shared.cancelGitHubConnect() },
                 sync: { try await APIClient.shared.syncConnector("github") },
                 disconnect: { _ = try await APIClient.shared.forgetConnector("github") },
                 open: { NSWorkspace.shared.open($0) },
                 sleep: { try? await Task.sleep(nanoseconds: UInt64(max(1, $0)) * 1_000_000_000) })
        }
    }

    private(set) var status = GitHubConnectStatus()
    private(set) var loaded = false
    private(set) var busy = false
    /// What the last step did, or why it did not (the backend's own sentence when it has one).
    private(set) var note: String?
    /// Set when the last step connected or synced, so the repository list reads again.
    private(set) var generation = 0
    @ObservationIgnored private let deps: Deps
    @ObservationIgnored private var polling: Task<Void, Never>?

    init(deps: Deps) { self.deps = deps }
    convenience init() { self.init(deps: .live) }

    var step: GitHubConnectStep { .from(status) }

    func load() async {
        do {
            status = try await deps.status()
            loaded = true
            if case .code = step { startPolling() }
        } catch {
            note = Copy.GitHub.couldNotConnect
        }
    }

    /// Connect GitHub: the code comes up, GitHub's page opens in the person's browser, and the panel waits.
    func connect() async {
        busy = true
        defer { busy = false }
        do {
            let code = try await deps.start()
            status.pending = code
            note = nil
            if let url = URL(string: code.verificationUri), url.host?.lowercased() == "github.com" { deps.open(url) }
            startPolling()
        } catch {
            note = GitHubReposModel.describe(error)
        }
    }

    /// One poll; the loop calls it every interval. Returns whether to keep asking.
    @discardableResult
    func pollOnce() async -> Bool {
        do {
            let answer = try await deps.poll()
            if let next = answer.status { status = next }
            switch answer.state {
            case "pending":
                if let interval = answer.interval, var code = status.pending {
                    code.interval = interval
                    status.pending = code
                }
                return true
            case "connected":
                status.pending = nil
                note = nil
                generation += 1
                return false
            default:
                status.pending = nil
                note = answer.words
                return false
            }
        } catch {
            note = Copy.GitHub.couldNotConnect
            return false
        }
    }

    private func startPolling() {
        polling?.cancel()
        polling = Task { [weak self] in
            while let self, !Task.isCancelled, let code = self.status.pending {
                await self.deps.sleep(code.interval)
                if Task.isCancelled { return }
                if !(await self.pollOnce()) { return }
            }
        }
    }

    func stop() {
        polling?.cancel()
        polling = nil
    }

    func cancel() async {
        stop()
        try? await deps.cancel()
        status.pending = nil
        note = nil
    }

    func openInstall() {
        if case .install(let raw) = step, let url = URL(string: raw), url.host?.lowercased() == "github.com" {
            deps.open(url)
        }
    }

    /// I installed it: ask GitHub again; installed, sync at once so the repositories come in.
    func checkInstalled() async {
        busy = true
        defer { busy = false }
        do {
            status = try await deps.installation()
            if status.installed == true {
                note = ConnectorSetupState.syncSummary(try await deps.sync())
                generation += 1
            } else {
                note = status.words ?? Copy.GitHub.notInstalledYet
            }
        } catch {
            note = GitHubReposModel.describe(error)
        }
    }

    func refresh() async {
        busy = true
        defer { busy = false }
        do {
            note = ConnectorSetupState.syncSummary(try await deps.sync())
            generation += 1
        } catch {
            note = GitHubReposModel.describe(error)
        }
    }

    func disconnect() async {
        busy = true
        defer { busy = false }
        do {
            try await deps.disconnect()
            status = try await deps.status()
            note = Copy.GitHub.disconnected
            generation += 1
        } catch {
            note = GitHubReposModel.describe(error)
        }
    }

    func openApplications() {
        if let url = URL(string: status.grantsUrl ?? "https://github.com/settings/applications") { deps.open(url) }
    }
}

/// GitHub's connect panel: one primary per step (DR-40) — Connect GitHub, then (by code, not installed yet) Install on
/// GitHub — and the token, the old way, behind "Use a token instead" (only where the build's app is not registered,
/// or when the person asks for it).
struct GitHubConnectPanel: View {
    @Bindable var model: GitHubConnectModel
    @Binding var vendor: WalkthroughVendor
    @State private var showToken = false
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if !model.loaded {
                ProgressView().controlSize(.small)
            } else {
                stepView
            }
            if let note = model.note {
                Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .task { await model.load() }
        .onDisappear { model.stop() }
    }

    @ViewBuilder
    private var stepView: some View {
        switch model.step {
        case .unavailable:
            // Until this build's app is registered there is no code to show: the token stays the fallback, behind
            // its own disclosure — never the panel's default.
            line(Copy.GitHub.notSetUp)
            tokenToggle
            if showToken { ConnectorSetupPanel(connectorId: "github", vendors: [], vendor: $vendor) }
        case .disconnected:
            line(Copy.GitHub.reads)
            HStack(spacing: CicadaTheme.spacingSM) {
                tokenToggle
                Spacer(minLength: CicadaTheme.spacingSM)
                PrimaryActionButton(title: Copy.GitHub.connect) { Task { await model.connect() } }
                    .disabled(model.busy)
                    .help(Copy.GitHub.connectHelp)
            }
            if showToken { ConnectorSetupPanel(connectorId: "github", vendors: [], vendor: $vendor) }
        case .code(let code):
            codeView(code)
        case .install:
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(Copy.GitHub.installTitle).font(CicadaTheme.font(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                line(Copy.GitHub.installWhy)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                TextButton(title: Copy.GitHub.installedCheck, flushLeading: true) {
                    Task { await model.checkInstalled() }
                }
                .disabled(model.busy)
                Spacer(minLength: CicadaTheme.spacingSM)
                PrimaryActionButton(title: Copy.GitHub.install, systemImage: "arrow.up.right") { model.openInstall() }
                    .disabled(model.busy)
            }
            connectedControls
        case .reconnect:
            Text(Copy.GitHub.signedOut).font(CicadaTheme.font(size: 12, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            line(Copy.GitHub.signedOutWhy)
            HStack(spacing: CicadaTheme.spacingSM) {
                Spacer(minLength: CicadaTheme.spacingSM)
                PrimaryActionButton(title: Copy.GitHub.reconnect) { Task { await model.connect() } }
                    .disabled(model.busy)
                    .help(Copy.GitHub.connectHelp)
            }
            connectedControls
        case .connected(let byToken):
            Text(byToken ? Copy.GitHub.connectedByToken : Copy.GitHub.connected)
                .font(CicadaTheme.font(size: 12, weight: .semibold)).foregroundStyle(CicadaTheme.textPrimary)
            line(Copy.GitHub.reads)
            connectedControls
        }
    }

    private func codeView(_ code: GitHubConnectCode) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.GitHub.enterCode)
            Text(code.userCode)
                .font(CicadaTheme.font(size: 22, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textPrimary)
                .textSelection(.enabled)
                .accessibilityLabel("\(Copy.GitHub.enterCode): \(code.userCode)")
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: Copy.GitHub.openGitHub, systemImage: "arrow.up.right", size: .compact,
                              help: code.verificationUri) {
                    if let url = URL(string: code.verificationUri), url.host?.lowercased() == "github.com" {
                        NSWorkspace.shared.open(url)
                    }
                }
                NeutralButton(title: copied ? Copy.GitHub.copied : Copy.GitHub.copyCode, size: .compact) {
                    AppPasteboard.copy(code.userCode)
                    copied = true
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                TextButton(title: Copy.GitHub.cancel) { Task { await model.cancel() } }
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text(Copy.GitHub.waiting).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            line(Copy.GitHub.expiresIn(GitHubConnectStep.minutesLeft(code, now: Date().timeIntervalSince1970)))
        }
    }

    private var connectedControls: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: Copy.GitHub.refresh, size: .compact, isDisabled: model.busy) {
                    Task { await model.refresh() }
                }
                NeutralButton(title: Copy.GitHub.disconnect, size: .compact, isDisabled: model.busy) {
                    Task { await model.disconnect() }
                }
                Spacer(minLength: 0)
            }
        }
    }

    private var tokenToggle: some View {
        TextButton(title: showToken ? Copy.GitHub.hideToken : Copy.GitHub.useToken, flushLeading: true) {
            showToken.toggle()
        }
    }

    private func line(_ text: String) -> some View {
        Text(text).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// GitHub's detail on the Sources page: the connect panel, then the repositories — read again after each connect,
/// install check or sync.
struct GitHubSourcePanel: View {
    @Binding var vendor: WalkthroughVendor
    @State private var connect = GitHubConnectModel()

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            GitHubConnectPanel(model: connect, vendor: $vendor)
            GitHubReposSection(generation: connect.generation)
        }
    }
}

// MARK: - The repositories

struct GitHubReposSection: View {
    /// Bumped by the connect panel after a connect or a sync: the list reads again.
    var generation: Int = 0
    /// The owned list's own scroll height: the controls above stay in reach.
    var listHeight: CGFloat = 220
    @Environment(AppRouter.self) private var router
    @State private var model = GitHubReposModel()

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if let note = model.note {
                Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            yours
            if !model.lists.starred.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    SectionLabel(Copy.GitHub.starredTitle)
                    Text(Copy.GitHub.starredCount(model.lists.starred.count))
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .task(id: generation) { await model.load() }
    }

    @ViewBuilder
    private var yours: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SectionLabel(Copy.GitHub.yoursTitle)
            if model.loaded && model.lists.owned.isEmpty {
                Text(Copy.GitHub.yoursEmpty).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            } else if !model.lists.owned.isEmpty {
                Text(Copy.GitHub.yoursIntro).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(model.lists.owned) { row($0) }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: CicadaTheme.scaled(listHeight))
            }
        }
    }

    private func row(_ repo: RepoRow) -> some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
            VStack(alignment: .leading, spacing: 2) {
                Text(repo.fullName).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1).truncationMode(.middle).help(repo.url)
                let detail = GitHubReposLogic.detail(repo)
                if !detail.isEmpty {
                    Text(detail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            let projects = GitHubReposLogic.projects(repo)
            ForEach(projects.shown, id: \.project) { project in
                TextButton(title: Copy.GitHub.inProject(project.name), help: project.name) {
                    router.routeToEntity(project.project)
                }
            }
            if projects.more > 0 {
                Text(Copy.GitHub.moreProjects(projects.more)).font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            if let page = repo.entityId {
                NeutralButton(title: Copy.GitHub.open, size: .compact, help: repo.fullName) {
                    router.routeToEntity(page)
                }
            }
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
    }
}
