import SwiftUI

// G230 — GitHub's row on the Sources page, under the connect panel every token account uses: add one repository by its
// link (a public one needs no connection), and the repositories the person owns from the last sync, each offered one
// action — added as a project, or linked to the project that has its name (owner 2026-11-03: "i'd rather it said 'Add
// as a project'"). A pasted link to one of their own is offered the same; anyone else's is added as a page. Nothing
// here makes a page on its own: every write is the person's click (ruling 45; ruling 36 D4).
//
// Not a Store domain: `GET /sources/github/repos` is read when the panel opens and after every write, kept here in
// memory (CLAUDE.md, Sync).
//
// DR-40 (one neutral Add; each row's action a compact `NeutralButton`, a settled project a `TextButton` to it),
// DR-44 (flags are `Tag`s), DR-47 (`SectionLabel`), DR-50 (the empty list said in words), DR-76 (the app's field).

/// The pure decisions: what the field accepts and what each row offers.
enum GitHubReposLogic {
    /// `owner/name` from a pasted repository link (or a bare `owner/name`), as the backend's `parse_repo` reads it;
    /// nil for anything else, so the field says so before a request is sent.
    static func repository(_ text: String) -> String? {
        var raw = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty, !raw.contains(" ") else { return nil }
        if raw.hasPrefix("git@github.com:") {
            raw = String(raw.dropFirst("git@github.com:".count))
        } else if let url = URL(string: raw), let scheme = url.scheme?.lowercased() {
            guard ["http", "https"].contains(scheme), let host = url.host?.lowercased(),
                  host == "github.com" || host == "www.github.com", url.user == nil, url.port == nil else { return nil }
            raw = url.path
        } else if raw.lowercased().hasPrefix("github.com/") || raw.lowercased().hasPrefix("www.github.com/") {
            raw = String(raw.drop(while: { $0 != "/" }))
        }
        let parts = raw.split(separator: "/").map(String.init)
        guard parts.count >= 2 else { return nil }
        var name = parts[1]
        if name.hasSuffix(".git") { name = String(name.dropLast(4)) }
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._"))
        guard !parts[0].isEmpty, !name.isEmpty, name != ".", name != "..",
              parts[0].unicodeScalars.allSatisfy({ allowed.contains($0) && $0 != "." && $0 != "_" }),
              name.unicodeScalars.allSatisfy({ allowed.contains($0) }) else { return nil }
        return "\(parts[0])/\(name)"
    }

    /// What one of the person's repositories offers, in order.
    enum Offer: Equatable {
        /// It already is a project page (linked, or born from a checkout of it).
        case project(id: String, name: String)
        /// A project has its name: link them, or start a new one.
        case link(id: String, name: String)
        /// Nothing yet: add it as a project.
        case make
    }

    /// The person's own repository a pasted link names, as the last sync listed it — nil for anyone else's (or before
    /// a sync), which the field adds as a page.
    static func owned(_ text: String, in lists: RepoLists) -> RepoRow? {
        guard let full = repository(text)?.lowercased() else { return nil }
        return lists.owned.first { $0.fullName.lowercased() == full }
    }

    static func offer(_ repo: RepoRow) -> Offer {
        guard let project = repo.project else { return .make }
        return project.isSettled ? .project(id: project.project, name: project.name)
                                 : .link(id: project.project, name: project.name)
    }

    /// "Private · Python" — the row's second line.
    static func detail(_ repo: RepoRow) -> String {
        Eyebrow.text(repo.isPrivate ? Copy.GitHub.isPrivate : "", repo.archived ? Copy.GitHub.isArchived : "",
                     repo.fork ? Copy.GitHub.isFork : "", repo.language ?? "", repo.description ?? "")
    }
}

/// The panel's state with no view in it. Every call goes through `Deps`, so tests run with no network.
@MainActor
@Observable
final class GitHubReposModel {
    struct Deps {
        var fetch: @MainActor () async throws -> RepoLists
        var add: @MainActor (String) async throws -> RepoAddResult
        var project: @MainActor (String, String?) async throws -> RepoProjectResult

        @MainActor static var live: Deps {
            Deps(fetch: { try await APIClient.shared.fetchGitHubRepos() },
                 add: { try await APIClient.shared.addGitHubRepo($0) },
                 project: { try await APIClient.shared.makeRepoProject(fullName: $0, project: $1) })
        }
    }

    private(set) var lists = RepoLists()
    private(set) var loaded = false
    private(set) var busy = false
    /// The last write's sentence, or why a read failed (the list keeps what it had).
    private(set) var note: String?
    @ObservationIgnored private let deps: Deps

    init(deps: Deps) { self.deps = deps }
    convenience init() { self.init(deps: .live) }

    func load() async {
        do {
            lists = try await deps.fetch()
            loaded = true
        } catch {
            note = Copy.GitHub.couldNotRead
        }
    }

    /// The person's Add. Returns whether it landed (the field clears then).
    @discardableResult
    func add(_ text: String) async -> Bool {
        guard let repo = GitHubReposLogic.repository(text) else { note = Copy.GitHub.notALink; return false }
        busy = true
        defer { busy = false }
        do {
            let result = try await deps.add(repo)
            note = result.created ? Copy.GitHub.added(result.fullName) : Copy.GitHub.updated(result.fullName)
        } catch {
            note = Self.describe(error)
            return false
        }
        await load()
        return true
    }

    /// The field's one button (and its Return): a link to one of the person's own repositories gets that
    /// repository's offer — added as a project, or linked to the project with its name — anyone else's is added as a
    /// page. Returns whether it landed (the field clears then).
    @discardableResult
    func submit(_ text: String) async -> Bool {
        guard let mine = GitHubReposLogic.owned(text, in: lists) else { return await add(text) }
        switch GitHubReposLogic.offer(mine) {
        case .project(_, let name):
            note = Copy.GitHub.alreadyProject(name)
            return false
        case .link:
            return await project(mine, link: mine.project)
        case .make:
            return await project(mine, link: nil)
        }
    }

    /// "Add as a project" (`project` nil) or "Link to <name>".
    @discardableResult
    func project(_ repo: RepoRow, link project: RepoProject?) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            let result = try await deps.project(repo.fullName, project?.project)
            note = result.created ? Copy.GitHub.started(repo.name) : Copy.GitHub.linked(project?.name ?? repo.name)
        } catch {
            note = Self.describe(error)
            return false
        }
        await load()
        return true
    }

    static func describe(_ error: Error) -> String {
        if case APIError.httpError(_, let body) = error, let detail = ServerDetail.sentence(body) { return detail }
        return Copy.GitHub.failed
    }
}

struct GitHubReposSection: View {
    /// The owned list's own scroll height: the controls above stay in reach.
    var listHeight: CGFloat = 220
    @Environment(AppRouter.self) private var router
    @State private var model = GitHubReposModel()
    @State private var linkText = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            addForm
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
        .task { await model.load() }
    }

    private var addForm: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SectionLabel(Copy.GitHub.addTitle)
            Text(Copy.GitHub.addIntro).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: CicadaTheme.spacingSM) {
                TextField("", text: $linkText)
                    .focused($focused)
                    .cicadaField(isFocused: focused, prompt: Copy.GitHub.linkPrompt, isEmpty: linkText.isEmpty)
                    .onSubmit { add() }
                fieldAction
            }
        }
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
            if let page = repo.entityId {
                TextButton(title: Copy.GitHub.inMemory, help: repo.fullName) { router.routeToEntity(page) }
            }
            offerView(repo)
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
    }

    @ViewBuilder
    private func offerView(_ repo: RepoRow) -> some View {
        switch GitHubReposLogic.offer(repo) {
        case .project(let id, let name):
            TextButton(title: Copy.GitHub.yourProject(name), help: name) { router.routeToProject(id) }
        case .link(_, let name):
            NeutralButton(title: Copy.GitHub.linkTo(name), size: .compact, isDisabled: model.busy,
                          help: Copy.GitHub.linkToHelp(name)) {
                Task { await model.project(repo, link: repo.project) }
            }
        case .make:
            NeutralButton(title: Copy.GitHub.addAsProject, size: .compact, isDisabled: model.busy,
                          help: Copy.GitHub.addAsProjectHelp) {
                Task { await model.project(repo, link: nil) }
            }
        }
    }

    /// The field's button: Add for anyone else's repository, the row's own offer for one of the person's.
    @ViewBuilder
    private var fieldAction: some View {
        if let mine = GitHubReposLogic.owned(linkText, in: model.lists) {
            switch GitHubReposLogic.offer(mine) {
            case .project(let id, let name):
                TextButton(title: Copy.GitHub.yourProject(name), help: name) { router.routeToProject(id) }
            case .link(_, let name):
                NeutralButton(title: Copy.GitHub.linkTo(name), size: .compact, isDisabled: model.busy,
                              help: Copy.GitHub.linkToHelp(name)) { add() }
            case .make:
                NeutralButton(title: Copy.GitHub.addAsProject, size: .compact, isDisabled: model.busy,
                              help: Copy.GitHub.addAsProjectHelp) { add() }
            }
        } else {
            NeutralButton(title: Copy.GitHub.add, size: .compact,
                          isDisabled: linkText.trimmingCharacters(in: .whitespaces).isEmpty || model.busy,
                          help: Copy.GitHub.addHelp) { add() }
        }
    }

    private func add() {
        let text = linkText
        Task { if await model.submit(text) { linkText = "" } }
    }
}
