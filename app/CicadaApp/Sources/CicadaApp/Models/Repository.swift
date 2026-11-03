import Foundation

// G230 — repositories on the graph. Authoritative shapes: `api/routers/github_repos.py` (`RepoRow`, `RepoLists`,
// `RepoDetail`). Every field past the name decodes tolerantly: an older backend, or a page written before a key
// existed, must still draw.

/// The project page a repository already is (`linked`: its trusted `repo` source; `origin`: born from a checkout of
/// it, by the hook's salted origin hash) or might be (`name`: a project with exactly its name — a suggestion only).
struct RepoProject: Codable, Equatable, Sendable {
    var project: String
    var name: String
    var how: String

    /// A match the person or the record already made — never a guess by name.
    var isSettled: Bool { how == "linked" || how == "origin" }
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
    var project: RepoProject?

    enum CodingKeys: String, CodingKey {
        case id, fullName, url, description, language, topics, ownerKind, archived, fork, starred
        case isPrivate = "private"
        case starredAt, unstarredOn, owned, added, entityId, project
    }

    init(id: Int, fullName: String, url: String, description: String? = nil, language: String? = nil,
         topics: [String] = [], ownerKind: String = "User", isPrivate: Bool = false, archived: Bool = false,
         fork: Bool = false, starred: Bool = false, starredAt: String? = nil, unstarredOn: String? = nil,
         owned: Bool = false, added: Bool = false, entityId: String? = nil, project: RepoProject? = nil) {
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

/// `POST /sources/github/repos`.
struct RepoAddResult: Codable, Equatable, Sendable {
    var entityId: String
    var fullName: String
    var created: Bool
}

/// `POST /sources/github/repos/project`.
struct RepoProjectResult: Codable, Equatable, Sendable {
    var project: String
    var created: Bool
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

/// `GET /entities/{id}/repository` — a repository page's (or a linked project's) card.
struct RepositoryDetail: Codable, Equatable, Sendable {
    var repo: RepoRow
    var readme: RepositoryReadme

    init(repo: RepoRow, readme: RepositoryReadme) {
        self.repo = repo
        self.readme = readme
    }

    /// The wire is one flat object: the row's keys plus `readme`.
    init(from decoder: Decoder) throws {
        repo = try RepoRow(from: decoder)
        let c = try decoder.container(keyedBy: ReadmeKey.self)
        readme = try c.decodeIfPresent(RepositoryReadme.self, forKey: .readme) ?? RepositoryReadme(state: "missing")
    }

    func encode(to encoder: Encoder) throws {
        try repo.encode(to: encoder)
        var c = encoder.container(keyedBy: ReadmeKey.self)
        try c.encode(readme, forKey: .readme)
    }

    private enum ReadmeKey: String, CodingKey { case readme }
}
