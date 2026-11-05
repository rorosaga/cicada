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

    /// A row's name: the full "owner/name" for someone else's repository, the name alone for one's own.
    static func name(_ repo: RepoRow, showOwner: Bool) -> String {
        guard !showOwner, let slash = repo.fullName.firstIndex(of: "/") else { return repo.fullName }
        return String(repo.fullName[repo.fullName.index(after: slash)...])
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
                if status.syncing { watchSync() }
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
        watching?.cancel()
        watching = nil
    }

    func cancel() async {
        stop()
        try? await deps.cancel()
        status.pending = nil
        note = nil
    }

    @ObservationIgnored private var watching: Task<Void, Never>?

    /// 2026-11-04 — the first sync the backend started on its own (`status.syncing`): asked again every two seconds,
    /// for at most five minutes; when it ends, the lists read again.
    func watchSync() {
        watching?.cancel()
        watching = Task { [weak self] in
            for _ in 0..<150 {
                guard let self, !Task.isCancelled else { return }
                await self.deps.sleep(2)
                guard let next = try? await self.deps.status() else { continue }
                self.status = next
                if !next.syncing {
                    self.generation += 1
                    return
                }
            }
        }
    }

    /// *Install on GitHub*: the install page in the browser, then GitHub is asked every five seconds (for at most
    /// three minutes) whether Cicada is installed — the person does not have to come back and say so. Installed, the
    /// repositories come in at once.
    func openInstallAndWatch() {
        openInstall()
        watching?.cancel()
        watching = Task { [weak self] in
            for _ in 0..<36 {
                guard let self, !Task.isCancelled else { return }
                await self.deps.sleep(5)
                guard let next = try? await self.deps.installation() else { continue }
                if next.installed == true {
                    await self.checkInstalled()
                    return
                }
            }
        }
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

// MARK: - The page (owner 2026-11-04)

/// GitHub's source page on the standard layout (owner 2026-11-04: "Before connection … just like connect GitHub and
/// that's it. Then while it's connecting … it can just be the code and copy the code and maybe the button to like
/// reopen the GitHub page … after it's connected … one part for my repos, maybe one for the starred repos").
///
/// - Not connected: *Connect GitHub*, nothing else.
/// - Connecting: the code, large, with *Copy* and *Open GitHub*, *Cancel* quiet, one line of time left.
/// - Connected: *Your repositories* and *Starred*, each a list of rows (`GitHubRepoRow`); the install step, only while
///   Cicada is not installed on the person's account, is one quiet row with one button.
/// - Footer: Refresh and Disconnect.
struct GitHubSourcePage: View {
    let row: SourceCatalogRow
    var backLabel: String? = nil
    var onShowList: () -> Void = {}
    let onClose: () -> Void

    @State private var connect: GitHubConnectModel
    @State private var repos: GitHubReposModel
    @State private var vendor: WalkthroughVendor = .claude

    /// The models are injected only by tests and the offscreen renders; the app uses the live ones.
    init(row: SourceCatalogRow, backLabel: String? = nil, onShowList: @escaping () -> Void = {},
         onClose: @escaping () -> Void, connect: GitHubConnectModel? = nil, repos: GitHubReposModel? = nil) {
        self.row = row
        self.backLabel = backLabel
        self.onShowList = onShowList
        self.onClose = onClose
        _connect = State(initialValue: connect ?? GitHubConnectModel())
        _repos = State(initialValue: repos ?? GitHubReposModel())
    }
    /// Which list fills the column (DR-81's "All N"), or nil for the page.
    @State private var drill: GitHubRepoList.Kind?
    @Environment(Store.self) private var store

    var body: some View {
        SourcePageLayout(title: row.entry.title, origin: row.entry.origin, status: status, backLabel: backLabel,
                         onShowList: onShowList, onClose: onClose) {
            if drill == nil { GitHubConnectSlot(model: connect, vendor: $vendor) }
        } content: {
            if let drill {
                SourceDrillHead(source: row.entry.title, title: nil) { self.drill = nil }
                GitHubRepoList(kind: drill, rows: rows(drill), cap: nil) { _ in }
            } else {
                if let note = repos.note { SourceConnectLine(text: note, isAttention: true) }
                if !repos.lists.owned.isEmpty {
                    GitHubRepoList(kind: .owned, rows: repos.lists.owned) { drill = $0 }
                }
                if !repos.lists.starred.isEmpty {
                    GitHubRepoList(kind: .starred, rows: repos.lists.starred) { drill = $0 }
                }
            }
        } footer: {
            if drill == nil, connect.status.connected {
                SourcePageFooter(actions: [
                    .refresh(isDisabled: connect.busy || connect.status.syncing) { Task { await connect.refresh() } },
                    .disconnect(row.entry.title, message: Copy.GitHub.disconnectDetail) {
                        Task { await connect.disconnect() }
                    },
                ], note: connect.note)
            }
        }
        .task(id: connect.generation) {
            await repos.load()
            await store.refresh([.channels, .sourcesOverview])
        }
        .onDisappear { connect.stop() }
    }

    private func rows(_ kind: GitHubRepoList.Kind) -> [RepoRow] {
        kind == .owned ? repos.lists.owned : repos.lists.starred
    }

    /// The head's one line, from the sign-in itself: a code waiting reads "Needs you · enter the code on GitHub", the
    /// first sync "Syncing", a lapsed sign-in "Needs you · sign in again", else the catalogue's own status.
    private var status: SourcePageStatus {
        if connect.status.syncing { return .syncing(detail: nil) }
        switch connect.step {
        case .code: return .needsYou(Copy.GitHub.enterCodeStatus)
        case .reconnect: return .needsYou(Copy.SourcePage.signInAgain)
        case .unavailable, .disconnected: return .off(lastItem: nil)
        case .install, .connected:
            let latest = store.channels.value?.first { $0.id == "github" }?.lastSyncDate
                .map { ISODay.today(now: $0).description }
            return .connected(lastItem: latest)
        }
    }
}

/// GitHub's connect area, one state at a time (DR-5: one primary).
struct GitHubConnectSlot: View {
    @Bindable var model: GitHubConnectModel
    @Binding var vendor: WalkthroughVendor
    @State private var showToken = false

    var body: some View {
        Group {
            if !model.loaded {
                ProgressView().controlSize(.small)
            } else {
                switch model.step {
                case .unavailable:
                    // Until this build's app is registered there is no code to show: the token is the way in.
                    SourceConnectArea(line: Copy.GitHub.notSetUp) {
                        ConnectorSetupPanel(connectorId: "github", vendors: [], vendor: $vendor)
                    }
                case .disconnected:
                    SourceConnectArea(primary: SourcePrimaryAction(title: Copy.GitHub.connect, help: Copy.GitHub.connectHelp,
                                                                   isDisabled: model.busy) {
                        Task { await model.connect() }
                    }, line: model.note, lineIsAttention: model.note != nil)
                case .code(let code):
                    GitHubCodeView(code: code) { Task { await model.cancel() } }
                case .install:
                    SourceConnectArea(ways: [SourceWayIn(
                        id: "install", icon: .mark("github"), title: Copy.GitHub.installLine,
                        control: .button(Copy.GitHub.install) { model.openInstallAndWatch() },
                        help: Copy.GitHub.installHelp, isDisabled: model.busy)])
                case .reconnect:
                    SourceConnectArea(primary: SourcePrimaryAction(title: Copy.GitHub.reconnect, help: Copy.GitHub.connectHelp,
                                                                   isDisabled: model.busy) {
                        Task { await model.connect() }
                    }, line: Copy.GitHub.signedOut, lineIsAttention: true)
                case .connected:
                    EmptyView()
                }
            }
        }
        .task { await model.load() }
    }
}

/// The code to enter on GitHub, large, with Copy and Open GitHub beside it and Cancel quiet; one line of time left.
/// The code is set in the copyable face (DR-19's allowlist: a code the person types).
struct GitHubCodeView: View {
    let code: GitHubConnectCode
    let onCancel: () -> Void
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                Text(code.userCode)
                    .font(CicadaTheme.font(size: 28, weight: .semibold, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .textSelection(.enabled)
                    .accessibilityLabel(Copy.GitHub.codeLabel(code.userCode))
                NeutralButton(title: copied ? Copy.GitHub.copied : Copy.GitHub.copyCode, systemImage: "doc.on.doc",
                              size: .compact) {
                    AppPasteboard.copy(code.userCode)
                    copied = true
                }
                NeutralButton(title: Copy.GitHub.openGitHub, systemImage: "arrow.up.right", size: .compact,
                              help: code.verificationUri) {
                    if let url = URL(string: code.verificationUri), url.host?.lowercased() == "github.com" {
                        NSWorkspace.shared.open(url)
                    }
                }
                Spacer(minLength: 0)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    SourceConnectLine(text: Copy.GitHub.expiresIn(
                        GitHubConnectStep.minutesLeft(code, now: context.date.timeIntervalSince1970)))
                }
                TextButton(title: Copy.GitHub.cancel, action: onCancel)
                Spacer(minLength: 0)
            }
        }
    }
}

// MARK: - The repositories

/// One of GitHub's two lists — *Your repositories* or *Starred* — at most 12 rows, then *All N* (DR-81, the
/// 2026-10-29 source-page cap), opened in the column's place.
struct GitHubRepoList: View {
    enum Kind: Equatable { case owned, starred }

    let kind: Kind
    let rows: [RepoRow]
    var cap: Int? = SourceItemsRules.cap
    let onAll: (Kind) -> Void

    var body: some View {
        let shown = cap.map { Array(rows.prefix($0)) } ?? rows
        SourceSection(title: kind == .owned ? Copy.GitHub.yoursTitle : Copy.GitHub.starredTitle,
                      count: UsageFormat.count(rows.count)) {
            LazyVStack(spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                ForEach(shown) { GitHubRepoRow(repo: $0, showOwner: kind == .starred) }
            }
            if let cap, rows.count > cap {
                TextButton(title: Copy.SourcePage.all(rows.count), help: Copy.SourcePage.allHelp) { onAll(kind) }
                    .padding(.top, CicadaTheme.spacingXS)
            }
        }
    }
}

/// A repository: the owner's picture when an organisation owns it (its page's picture), else GitHub's own mark (the
/// 2026-10-28 rule: a saved thing with no picture of its own wears its source's mark); the name, the description under
/// it, and the language on the right. A click opens its page; its context menu opens it on GitHub and in the projects
/// it belongs to.
struct GitHubRepoRow: View {
    let repo: RepoRow
    /// Starred: "owner/name"; one's own: the name alone (the owner is the person).
    var showOwner = false

    @Environment(AppRouter.self) private var router
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button { open() } label: {
            HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                GitHubRepoPicture(entityId: repo.entityId, side: CicadaTheme.scaled(24))
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(GitHubReposLogic.name(repo, showOwner: showOwner))
                            .font(CicadaTheme.rowFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        if repo.isPrivate { Tag(text: Copy.GitHub.isPrivate) }
                        if repo.archived { Tag(text: Copy.GitHub.isArchived) }
                    }
                    if let description = repo.description, !description.isEmpty {
                        Text(description)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                            .truncationMode(.tail)
                    }
                }
                .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.textMaxWidth), alignment: .leading)
                Spacer(minLength: CicadaTheme.spacingSM)
                if let language = repo.language {
                    Text(language)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                        .fixedSize()
                }
            }
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine))
            .padding(.trailing, ItemPlaceControl.reserve(.github))
            .padding(.horizontal, CicadaTheme.scaled(10))
            .rowHoverFill(hovering: hovering)
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(repo.description.map { "\(repo.fullName) — \($0)" } ?? repo.fullName)
        .contextMenu {
            Button(Copy.GitHub.openOnGitHub) {
                if let url = URL(string: repo.url), url.host?.lowercased() == "github.com" { NSWorkspace.shared.open(url) }
            }
            ForEach(repo.projects, id: \.project) { project in
                Button(Copy.GitHub.inProject(project.name)) { router.routeToEntity(project.project) }
            }
        }
        .accessibilityLabel([GitHubReposLogic.name(repo, showOwner: showOwner), repo.description, repo.language]
            .compactMap { $0 }.joined(separator: ", "))
        .modifier(ItemPlaceControl(kind: .github, title: repo.fullName) {
            ItemPlace(kind: ItemPlaceKind.github.rawValue, url: repo.url)
        })
    }

    private func open() {
        if let page = repo.entityId {
            router.routeToEntity(page)
        } else if let url = URL(string: repo.url), url.host?.lowercased() == "github.com" {
            NSWorkspace.shared.open(url)
        }
    }
}

/// A repository row's picture: its page's own picture (an organisation's avatar, kept by the backend on the ToS rail;
/// a personal account's is never asked) from Cicada's API, else GitHub's real mark (DR-52).
struct GitHubRepoPicture: View {
    let entityId: String?
    let side: CGFloat
    @Environment(Store.self) private var store: Store?
    @State private var image: NSImage?

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image).resizable().interpolation(.high).scaledToFill()
                    .frame(width: side, height: side)
                    .clipShape(CicadaTheme.shape(CicadaTheme.radiusXS))
            } else {
                OriginMark(origin: "github", size: side * 0.75)
            }
        }
        .frame(width: side, height: side)
        .accessibilityHidden(true)
        .task(id: "\(store?.bank ?? "")|\(entityId ?? "")") {
            guard let entityId, let path = SourcePictures.pagePicturePath("/entities/\(entityId)/picture") else {
                image = nil
                return
            }
            image = await SourcePictureStore.shared.image(path: path, bank: store?.bank ?? "")
        }
    }
}
