import Foundation

/// `PATCH /projects/{id}/milestones/{slug}` — a rename, a new state, or both (the server applies the name first).
struct MilestoneChange: Equatable, Sendable {
    var name: String?
    var status: String?
    var target: String?
    var on: String?

    var body: [String: Any] {
        var body: [String: Any] = [:]
        if let name { body["name"] = name }
        if let status { body["status"] = status }
        if let target { body["target"] = target }
        if let on { body["on"] = on }
        return body
    }
}

/// G141 PJ-5 (R-PP19) — one of the Projects page's five writes, run by `Store.perform` like every write the app sends:
/// its optimistic half paints `ProjectsCache` (the page's data lives there, not in a Store domain — R-PP3), its
/// request goes out through `SyncAPI`, and a failure rolls the paint back and toasts in plain words. The server's
/// answer (the claim, the day and how the day was decided) is kept in `result` for the Log's confirmation and its Undo
/// (`SyncSafariTabs`' memo pattern). `refreshDomains` is empty: the page revalidates the cache itself, and the Store
/// follows the bank's own sync events.
struct ProjectWrite: Mutation {
    enum Action: Equatable {
        case addMilestone(name: String, target: String?)
        case changeMilestone(slug: String, change: MilestoneChange)
        case log(text: String, status: String, when: String?)
        case settle(claimId: String, status: String)
        case withdraw(claimId: String)
    }

    let projectId: String
    let action: Action
    let cache: ProjectsCache
    /// The viewer's today: the day an optimistic paint is dated.
    let day: ISODay
    let overlayId = UUID()
    private let memo = MutationMemo<ProjectWriteResponse>()
    private let failure = MutationMemo<any Error>()

    init(projectId: String, action: Action, cache: ProjectsCache, day: ISODay) {
        self.projectId = projectId
        self.action = action
        self.cache = cache
        self.day = day
    }

    var result: ProjectWriteResponse? { memo.value }

    /// R-PP19 — painted only where the answer is known before the server speaks. Never the Log: its day comes from
    /// the words, decided by `when.py`.
    var overlay: ProjectOverlay? {
        let change: ProjectOverlay.Change
        switch action {
        case .addMilestone(let name, let target):
            change = .milestoneAdded(name: name, target: target)
        case .changeMilestone(let slug, let c):
            if c.status == "done" {
                change = .milestoneDone(slug: slug)
            } else if let name = c.name {
                change = .milestoneRenamed(slug: slug, name: name)
            } else {
                return nil
            }
        case .log:
            return nil
        case .settle(let claimId, let status):
            change = status == "ongoing" ? .threadRestated(claimId: claimId) : .threadSettled(claimId: claimId)
        case .withdraw(let claimId):
            change = .withdrawn(claimId: claimId)
        }
        return ProjectOverlay(id: overlayId, projectId: projectId, change: change, day: day)
    }

    func optimistic(_ store: Store) async {
        if let overlay { cache.add(overlay) }
    }

    func request(_ api: any SyncAPI) async throws {
        do {
            switch action {
            case .addMilestone(let name, let target):
                memo.value = try await api.addProjectMilestone(project: projectId, name: name, target: target)
            case .changeMilestone(let slug, let change):
                memo.value = try await api.changeProjectMilestone(project: projectId, slug: slug, change: change)
            case .log(let text, let status, let when):
                memo.value = try await api.logProjectHappening(project: projectId, text: text, status: status, when: when)
            case .settle(let claimId, let status):
                memo.value = try await api.settleProjectThread(project: projectId, claimId: claimId, status: status)
            case .withdraw(let claimId):
                memo.value = try await api.withdrawProjectHappening(project: projectId, claimId: claimId)
            }
        } catch {
            failure.value = error
            throw error
        }
    }

    func rollback(_ store: Store) async {
        cache.remove(overlayId: overlayId)
    }

    var failureMessage: String { ProjectWriteFailure.message(failure.value) }
}

/// R-PP19 — a failed write in words. A 409 (Sleep is writing) and a 422 (a date the words could not settle) carry
/// `routers/projects.py`'s own sentences, written for the person; every other failure gets this page's words — a 400's
/// or a 404's detail names ids and field names (DR-54).
enum ProjectWriteFailure {
    static func message(_ error: (any Error)?) -> String {
        guard let api = error as? APIError else { return Copy.Projects.saveFailed }
        switch api {
        case .httpError(let code, let body) where code == 409 || code == 422:
            return detail(body) ?? (code == 409 ? Copy.Projects.sleepBusy : Copy.Projects.saveFailed)
        case .httpError(404, _):
            return Copy.Projects.notOnProject
        case .serverUnreachable:
            return Copy.Projects.backendDown
        default:
            return Copy.Projects.saveFailed
        }
    }

    /// FastAPI's `{"detail": "…"}`, when the detail is a sentence (a validation error's detail is a list — not ours).
    static func detail(_ body: String) -> String? {
        guard let data = body.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = object["detail"] as? String, !detail.isEmpty else { return nil }
        return detail
    }
}

/// R-PP20 — while Sleep runs every Projects write answers 409 (`_guard`, `routers/projects.py`), so the controls say
/// so before a click (DR-41: disabled, with the reason in `.help`).
enum ProjectWriteGate {
    static func blocked(_ status: StatusSnapshot?) -> Bool { status?.sleep.status == "running" }
}

/// R-PP21 — the Log's confirmation: the day the server chose, with its distance, and how it was decided.
enum ProjectLogWords {
    static func confirmation(_ name: String, answer: ProjectWriteResponse, sentDay: Bool, today: ISODay,
                             locale: Locale = .autoupdatingCurrent) -> String {
        let day = ISODay(answer.day) ?? today
        let when = Copy.Projects.dayAndDistance(RelativeDay.absolute(day, today: today, locale: locale),
                                                RelativeDay.distance(day, today: today))
        let how = answer.dateBasis == "stated" ? Copy.Projects.fromYourWords
            : (sentDay ? Copy.Projects.fromTheChip : Copy.Projects.noDayInWords)
        return Copy.Projects.logged(name, day: when, how: how)
    }
}
