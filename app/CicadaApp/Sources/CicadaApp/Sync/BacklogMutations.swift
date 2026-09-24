import Foundation

/// `PATCH /backlog/{project}/{item}` from the app — a title or a status (R-B20: triage, `paid` and links stay for
/// agents and scripts in v1).
struct BacklogChange: Equatable, Sendable {
    var title: String?
    var status: String?

    var body: [String: Any] {
        var body: [String: Any] = [:]
        if let title { body["title"] = title }
        if let status { body["status"] = status }
        return body
    }
}

/// G150 (R-B22) — one of the Backlog section's three writes, run by `Store.perform` like every write the app sends.
/// Only a status move is painted before the server answers (its result is known); a failure rolls it back and
/// toasts in plain words; the server's answer — the item as it now stands — is kept in `result`, so an add can open
/// what it filed. `refreshDomains` is empty: the page revalidates `BacklogCache` itself.
struct BacklogWrite: Mutation {
    enum Action: Equatable {
        case add(title: String, description: String)
        case note(item: String, text: String, status: BacklogStatus?)
        case update(item: String, change: BacklogChange)
    }

    let projectId: String
    let action: Action
    let cache: BacklogCache
    private let memo = MutationMemo<BacklogItem>()
    private let failure = MutationMemo<any Error>()

    init(projectId: String, action: Action, cache: BacklogCache) {
        self.projectId = projectId
        self.action = action
        self.cache = cache
    }

    var result: BacklogItem? { memo.value }

    /// The move this write paints, if any.
    var paint: (item: String, status: BacklogStatus)? {
        switch action {
        case .add:
            return nil
        case .note(let item, _, let status):
            return status.map { (item: item, status: $0) }
        case .update(let item, let change):
            return change.status.flatMap(BacklogStatus.init(rawValue:)).map { (item: item, status: $0) }
        }
    }

    func optimistic(_ store: Store) async {
        if let paint { cache.paint(projectId, paint.item, paint.status) }
    }

    func request(_ api: any SyncAPI) async throws {
        do {
            switch action {
            case .add(let title, let description):
                memo.value = try await api.addBacklogItem(project: projectId, title: title, description: description)
            case .note(let item, let text, let status):
                memo.value = try await api.addBacklogNote(project: projectId, item: item, note: text,
                                                          status: status?.rawValue)
            case .update(let item, let change):
                memo.value = try await api.updateBacklogItem(project: projectId, item: item, change: change)
            }
        } catch {
            failure.value = error
            throw error
        }
    }

    func rollback(_ store: Store) async {
        if let paint { cache.unpaint(projectId, paint.item) }
    }

    var failureMessage: String { BacklogWriteFailure.message(failure.value) }
}

/// R-B22 — a failed write in words: a 409 carries `routers/backlog.py`'s own sentence (Sleep is writing, or the idea
/// is already on the backlog — both written for the person); every other failure gets this section's words, because
/// a 400's or a 404's detail names fields and ids (DR-54).
enum BacklogWriteFailure {
    static func message(_ error: (any Error)?) -> String {
        guard let api = error as? APIError else { return Copy.Projects.Backlog.saveFailed }
        switch api {
        case .httpError(409, let body):
            return ProjectWriteFailure.detail(body) ?? Copy.Projects.sleepBusy
        case .httpError(404, _):
            return Copy.Projects.Backlog.gone
        case .serverUnreachable:
            return Copy.Projects.backendDown
        default:
            return Copy.Projects.Backlog.saveFailed
        }
    }
}
