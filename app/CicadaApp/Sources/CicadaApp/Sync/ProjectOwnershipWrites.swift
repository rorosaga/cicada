import Foundation

/// Projects v2 (TODO ruling 45) — the person's project writes beyond the timeline's five: start one, take or leave a
/// suggestion, edit the header, tie or untie a conversation, add or take back an influence. One enum so the transport
/// stays one requirement on `SyncAPI` (every route answers `ProjectOwnershipResponse`, 409 while Sleep writes).
enum ProjectChange: Equatable, Sendable {
    case create(name: String, description: String)
    case accept(id: String, name: String?)
    case dismiss(id: String)
    case header(id: String, name: String?, description: String?)
    case tie(id: String, episode: String, remove: Bool)
    case addInfluence(id: String, url: String?, what: String?, entity: String?, how: String?, note: String?)
    case withdrawInfluence(id: String, claimId: String?, page: String?, ref: String?, predicate: String?)
    /// Decision 10 (2026-10-28): Pages in this project — Add a page (`name` paints the row at once) or "Not part of it".
    case tiePage(id: String, entity: String, name: String?, type: String?, remove: Bool)

    var projectId: String? {
        switch self {
        case .create: return nil
        case .accept(let id, _), .dismiss(let id), .header(let id, _, _), .tie(let id, _, _),
             .addInfluence(let id, _, _, _, _, _), .withdrawInfluence(let id, _, _, _, _),
             .tiePage(let id, _, _, _, _):
            return id
        }
    }

    /// `(method, path, body)` for `routers/projects.py`.
    var route: (method: String, path: String, body: [String: Any]) {
        func set(_ body: inout [String: Any], _ key: String, _ value: String?) {
            if let value, !value.isEmpty { body[key] = value }
        }
        switch self {
        case .create(let name, let description):
            return ("POST", "/projects", ["name": name, "description": description])
        case .accept(let id, let name):
            var body: [String: Any] = [:]
            set(&body, "name", name)
            return ("POST", APIClient.projectPath(id, "accept"), body)
        case .dismiss(let id):
            return ("POST", APIClient.projectPath(id, "dismiss"), [:])
        case .header(let id, let name, let description):
            var body: [String: Any] = [:]
            if let name { body["name"] = name }
            if let description { body["description"] = description }
            return ("PATCH", APIClient.projectPath(id), body)
        case .tie(let id, let episode, let remove):
            return ("POST", APIClient.projectPath(id, "conversations"), ["episode": episode, "remove": remove])
        case .addInfluence(let id, let url, let what, let entity, let how, let note):
            var body: [String: Any] = [:]
            set(&body, "url", url)
            set(&body, "what", what)
            set(&body, "entity", entity)
            set(&body, "how", how)
            set(&body, "note", note)
            return ("POST", APIClient.projectPath(id, "influences"), body)
        case .withdrawInfluence(let id, let claimId, let page, let ref, let predicate):
            var body: [String: Any] = [:]
            set(&body, "claimId", claimId)
            set(&body, "page", page)
            set(&body, "ref", ref)
            set(&body, "predicate", predicate)
            return ("POST", APIClient.projectPath(id, "influences", "withdraw"), body)
        case .tiePage(let id, let entity, _, _, let remove):
            return ("POST", APIClient.projectPath(id, "pages"), ["entity": entity, "remove": remove])
        }
    }
}

/// One `ProjectChange`, run by `Store.perform` like every write: its optimistic half paints `ProjectsCache` (the list
/// moves a project in or out of the person's list; the header shows the new words; an influence taken back leaves),
/// a failure rolls the paint back and toasts in words, and the answer is kept for the caller (a created project's id).
struct ProjectOwnershipWrite: Mutation {
    let change: ProjectChange
    let cache: ProjectsCache
    let overlayId = UUID()
    private let memo = MutationMemo<ProjectOwnershipResponse>()
    private let failure = MutationMemo<any Error>()

    init(_ change: ProjectChange, cache: ProjectsCache) {
        self.change = change
        self.cache = cache
    }

    var result: ProjectOwnershipResponse? { memo.value }

    func optimistic(_ store: Store) async {
        cache.paint(change, id: overlayId)
    }

    func request(_ api: any SyncAPI) async throws {
        do {
            memo.value = try await api.sendProjectChange(change)
        } catch {
            failure.value = error
            throw error
        }
    }

    func rollback(_ store: Store) async {
        cache.unpaint(overlayId)
    }

    var failureMessage: String { ProjectWriteFailure.message(failure.value) }
}
