import Foundation

// G230 — repositories on the graph. Authoritative shapes: `api/routers/github_repos.py` (`RepoRow`, `RepoLists`,
// `RepoDetail`). Every field past the name decodes tolerantly: an older backend, or a page written before a key
// existed, must still draw.

/// A project a repository belongs to — linked by the person (`user`), a trusted agent (`agent`), the hook's salted
/// origin hash of the project's own checkout (`origin`), or before projects listed theirs (`linked`) — or might
/// (`name`: a project with exactly its name, a suggestion; `other`: any project the card offers).
struct RepoProject: Codable, Equatable, Hashable, Sendable {
    var project: String
    var name: String
    var how: String

    /// A link the person, an agent or the record made — never a guess by name.
    var isSettled: Bool { ["linked", "origin", "user", "agent"].contains(how) }
}

/// One repository as the backend lists it: GitHub's record as the page or the last sync keeps it.
struct RepoRow: Codable, Equatable, Identifiable, Sendable {
    var id: Int
    var fullName: String
    var url: String
    var description: String?
    var language: String?
    var topics: [String]
    var ownerKind: String
    var isPrivate: Bool
    var archived: Bool
    var fork: Bool
    var starred: Bool
    var starredAt: String?
    var unstarredOn: String?
    var owned: Bool
    var added: Bool
    var entityId: String?
    /// The first project it belongs to, else a suggestion.
    var project: RepoProject?
    /// Every project it belongs to (owner 2026-11-03: "a project might reference several repos").
    var projects: [RepoProject]

    enum CodingKeys: String, CodingKey {
        case id, fullName, url, description, language, topics, ownerKind, archived, fork, starred
        case isPrivate = "private"
        case starredAt, unstarredOn, owned, added, entityId, project, projects
    }

    init(id: Int, fullName: String, url: String, description: String? = nil, language: String? = nil,
         topics: [String] = [], ownerKind: String = "User", isPrivate: Bool = false, archived: Bool = false,
         fork: Bool = false, starred: Bool = false, starredAt: String? = nil, unstarredOn: String? = nil,
         owned: Bool = false, added: Bool = false, entityId: String? = nil, project: RepoProject? = nil,
         projects: [RepoProject] = []) {
        self.id = id
        self.fullName = fullName
        self.url = url
        self.description = description
        self.language = language
        self.topics = topics
        self.ownerKind = ownerKind
        self.isPrivate = isPrivate
        self.archived = archived
        self.fork = fork
        self.starred = starred
        self.starredAt = starredAt
        self.unstarredOn = unstarredOn
        self.owned = owned
        self.added = added
        self.entityId = entityId
        self.project = project
        self.projects = projects
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(Int.self, forKey: .id) ?? 0
        fullName = try c.decode(String.self, forKey: .fullName)
        url = try c.decodeIfPresent(String.self, forKey: .url) ?? "https://github.com/\(fullName)"
        description = try c.decodeIfPresent(String.self, forKey: .description)
        language = try c.decodeIfPresent(String.self, forKey: .language)
        topics = (try? c.decodeIfPresent([String].self, forKey: .topics)) ?? []
        ownerKind = try c.decodeIfPresent(String.self, forKey: .ownerKind) ?? "User"
        isPrivate = try c.decodeIfPresent(Bool.self, forKey: .isPrivate) ?? false
        archived = try c.decodeIfPresent(Bool.self, forKey: .archived) ?? false
        fork = try c.decodeIfPresent(Bool.self, forKey: .fork) ?? false
        starred = try c.decodeIfPresent(Bool.self, forKey: .starred) ?? false
        starredAt = try c.decodeIfPresent(String.self, forKey: .starredAt)
        unstarredOn = try c.decodeIfPresent(String.self, forKey: .unstarredOn)
        owned = try c.decodeIfPresent(Bool.self, forKey: .owned) ?? false
        added = try c.decodeIfPresent(Bool.self, forKey: .added) ?? false
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId)
        project = try? c.decodeIfPresent(RepoProject.self, forKey: .project)
        projects = (try? c.decodeIfPresent([RepoProject].self, forKey: .projects)) ?? []
    }

    /// `owner` of `owner/name`.
    var owner: String { fullName.split(separator: "/").first.map(String.init) ?? fullName }
    /// `name` of `owner/name`.
    var name: String { fullName.split(separator: "/").dropFirst().first.map(String.init) ?? fullName }
}

/// `GET /sources/github/repos`.
struct RepoLists: Codable, Equatable, Sendable {
    var connected: Bool
    var owned: [RepoRow]
    var starred: [RepoRow]

    init(connected: Bool = false, owned: [RepoRow] = [], starred: [RepoRow] = []) {
        self.connected = connected
        self.owned = owned
        self.starred = starred
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        owned = try c.decodeIfPresent([RepoRow].self, forKey: .owned) ?? []
        starred = try c.decodeIfPresent([RepoRow].self, forKey: .starred) ?? []
    }
}

/// `POST /sources/github/repos/project` — a link, an unlink, or a new project from the repository.
struct RepoProjectResult: Codable, Equatable, Sendable {
    var project: String
    var created: Bool
    var linked: Bool

    init(project: String, created: Bool, linked: Bool = true) {
        self.project = project
        self.created = created
        self.linked = linked
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = try c.decode(String.self, forKey: .project)
        created = try c.decodeIfPresent(Bool.self, forKey: .created) ?? false
        linked = try c.decodeIfPresent(Bool.self, forKey: .linked) ?? true
    }
}

/// `GET /entities/{id}/repositories` — a project's repositories, and the repository pages it could link.
struct ProjectRepositories: Codable, Equatable, Sendable {
    var project: String
    var repos: [RepoRow]
    var candidates: [RepoRow]

    init(project: String, repos: [RepoRow] = [], candidates: [RepoRow] = []) {
        self.project = project
        self.repos = repos
        self.candidates = candidates
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
        repos = (try? c.decodeIfPresent([RepoRow].self, forKey: .repos)) ?? []
        candidates = (try? c.decodeIfPresent([RepoRow].self, forKey: .candidates)) ?? []
    }
}

/// `GET /sources/github/connect` — connecting with a code (GitHub's device flow; owner 2026-11-03: "cant we just do
/// oauth? like a connect?"). `available` is false until this build's GitHub app is registered: the token is then the
/// fallback.
struct GitHubConnectStatus: Codable, Equatable, Sendable {
    var available: Bool
    var connected: Bool
    /// `app` (connected by code) or `token` (a pasted token).
    var how: String?
    /// Connected by code: whether Cicada is installed on the person's account (what lets it see their repositories).
    var installed: Bool?
    var installUrl: String?
    var grantsUrl: String?
    /// Connected by code, but GitHub no longer renews the sign-in: Reconnect, never Connected.
    var reconnect: Bool
    var pending: GitHubConnectCode?
    var words: String?

    init(available: Bool = false, connected: Bool = false, how: String? = nil, installed: Bool? = nil,
         installUrl: String? = nil, grantsUrl: String? = nil, reconnect: Bool = false,
         pending: GitHubConnectCode? = nil, words: String? = nil) {
        self.available = available
        self.connected = connected
        self.how = how
        self.installed = installed
        self.installUrl = installUrl
        self.grantsUrl = grantsUrl
        self.reconnect = reconnect
        self.pending = pending
        self.words = words
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        available = try c.decodeIfPresent(Bool.self, forKey: .available) ?? false
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        how = try c.decodeIfPresent(String.self, forKey: .how)
        installed = try c.decodeIfPresent(Bool.self, forKey: .installed)
        installUrl = try c.decodeIfPresent(String.self, forKey: .installUrl)
        grantsUrl = try c.decodeIfPresent(String.self, forKey: .grantsUrl)
        reconnect = try c.decodeIfPresent(Bool.self, forKey: .reconnect) ?? false
        pending = try? c.decodeIfPresent(GitHubConnectCode.self, forKey: .pending)
        words = try c.decodeIfPresent(String.self, forKey: .words)
    }
}

/// The code the person enters on GitHub, where, and how often to ask again. Never the device code itself.
struct GitHubConnectCode: Codable, Equatable, Sendable {
    var userCode: String
    var verificationUri: String
    var expiresAt: Int
    var interval: Int
}

/// `POST /sources/github/connect/poll`.
struct GitHubConnectPoll: Codable, Equatable, Sendable {
    /// pending | connected | denied | expired | error | none
    var state: String
    var interval: Int?
    var words: String?
    var status: GitHubConnectStatus?
}

/// A repository's README preview, kept outside every bank: words only (no HTML, no picture, no link target).
struct RepositoryReadme: Codable, Equatable, Sendable {
    /// `fresh` | `stale` | `missing` (not read yet) | `none` (the repository has no README)
    var state: String
    var text: String?
    var truncated: Bool
    var path: String?
    var fetchedAt: String?

    init(state: String, text: String? = nil, truncated: Bool = false, path: String? = nil, fetchedAt: String? = nil) {
        self.state = state
        self.text = text
        self.truncated = truncated
        self.path = path
        self.fetchedAt = fetchedAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "missing"
        text = try c.decodeIfPresent(String.self, forKey: .text)
        truncated = try c.decodeIfPresent(Bool.self, forKey: .truncated) ?? false
        path = try c.decodeIfPresent(String.self, forKey: .path)
        fetchedAt = try c.decodeIfPresent(String.self, forKey: .fetchedAt)
    }
}

/// `GET /entities/{id}/repository` — a repository page's card.
struct RepositoryDetail: Codable, Equatable, Sendable {
    var repo: RepoRow
    var readme: RepositoryReadme
    /// Projects it could be linked to: a suggestion first, then every other live project.
    var candidates: [RepoProject]

    init(repo: RepoRow, readme: RepositoryReadme, candidates: [RepoProject] = []) {
        self.repo = repo
        self.readme = readme
        self.candidates = candidates
    }

    /// The wire is one flat object: the row's keys plus `readme` and `candidates`.
    init(from decoder: Decoder) throws {
        repo = try RepoRow(from: decoder)
        let c = try decoder.container(keyedBy: ExtraKey.self)
        readme = try c.decodeIfPresent(RepositoryReadme.self, forKey: .readme) ?? RepositoryReadme(state: "missing")
        candidates = (try? c.decodeIfPresent([RepoProject].self, forKey: .candidates)) ?? []
    }

    func encode(to encoder: Encoder) throws {
        try repo.encode(to: encoder)
        var c = encoder.container(keyedBy: ExtraKey.self)
        try c.encode(readme, forKey: .readme)
        try c.encode(candidates, forKey: .candidates)
    }

    private enum ExtraKey: String, CodingKey { case readme, candidates }
}
