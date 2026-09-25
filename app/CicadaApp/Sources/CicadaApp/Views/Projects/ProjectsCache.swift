import Foundation
import Observation

/// G141 PJ-5 — the Projects page's in-memory cache (R-PP3, R-PJ7; spec §10.1). One for the app, owned by `CicadaApp`
/// as `@State` beside `ProvenanceCache`, so a tab switch keeps what was read and the page repaints at once.
///
/// **Never a Store domain.** Both reads are fetched on demand and revalidated with `If-None-Match` — a 304 costs
/// nothing and keeps the page honest after a Sleep cycle. There is no `SnapshotCache` entry and no `VersionVector`
/// mapping, so the ship-together rule has nothing to pair; the page asks again when a sync version event moves a
/// component both ETags fold (`ProjectsRefresh`).
///
/// **Never blank.** A failed or 304 answer keeps the last value; an error is shown only when there is nothing to show
/// (DR-43). **Not keyed by bank**, so a bank switch empties it (`reset()`) — project ids repeat across banks — and an
/// answer in flight across the switch is dropped by its epoch rather than painted under the new bank.
@Observable
@MainActor
final class ProjectsCache {
    enum Phase: Equatable { case idle, loading, loaded, gone, failed(String) }

    /// Detail payloads are ~20–30 KB each; a dozen covers any afternoon of clicking.
    static let timelineCapacity = 12

    private(set) var list: ProjectsResponse?
    private(set) var listPhase: Phase = .idle
    private(set) var timelines: [String: ProjectTimeline] = [:]
    private(set) var timelinePhases: [String: Phase] = [:]
    /// R-PP19 — writes painted over `timelines` until the server's answer holds them (Task 5).
    private(set) var overlays: [String: [ProjectOverlay]] = [:]

    /// R-FA2 — changes whenever what `display(id)` returns may change (a fresh answer, a 404, an overlay added or
    /// removed), and only then, so the column re-derives off the main actor exactly when it must. One global
    /// counter, never reset, so a revision handed out before a bank switch can never match one after it.
    private(set) var revisions: [String: Int] = [:]
    @ObservationIgnored private var nextRevision = 1

    @ObservationIgnored private let api: any ProjectsAPI
    @ObservationIgnored private var listETag: String?
    @ObservationIgnored private var timelineETags: [String: String] = [:]
    @ObservationIgnored private var recent: [String] = []
    @ObservationIgnored private var epoch = 0

    init(api: any ProjectsAPI = APIClient.shared) { self.api = api }

    func phase(_ id: String) -> Phase { timelinePhases[id] ?? .idle }

    func revision(_ id: String) -> Int { revisions[id] ?? 0 }

    private func bump(_ id: String) {
        revisions[id] = nextRevision
        nextRevision &+= 1
    }

    /// What the page draws for a project: the server's answer with every pending write painted over it (R-PP19).
    func display(_ id: String) -> ProjectTimeline? {
        timelines[id].map { ProjectOverlay.apply(overlays[id] ?? [], to: $0) }
    }

    /// Forget everything — a bank switch (`ContentView`, R-PU26's reason).
    func reset() {
        epoch &+= 1
        list = nil
        listPhase = .idle
        listETag = nil
        timelines = [:]
        timelinePhases = [:]
        timelineETags = [:]
        recent = []
        overlays = [:]
        revisions = [:]   // `nextRevision` runs on: a revision from before the switch never matches one after it.
    }

    func refreshList() async {
        let started = epoch
        if list == nil { listPhase = .loading }
        do {
            // Never an ETag with nothing cached: a 304 would leave the page with nothing to draw.
            let answer = try await api.fetchProjects(etag: list == nil ? nil : listETag)
            guard started == epoch else { return }
            if let value = answer.value {
                list = value
                listETag = answer.etag
            }
            listPhase = .loaded
        } catch {
            guard started == epoch else { return }
            listPhase = list == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    func refreshTimeline(_ id: String) async {
        let started = epoch
        if timelines[id] == nil { timelinePhases[id] = .loading }
        do {
            let answer = try await api.fetchProjectTimeline(id: id, etag: timelines[id] == nil ? nil : timelineETags[id])
            guard started == epoch else { return }
            if let value = answer.value { store(value, etag: answer.etag, for: id) }
            // A fresh answer holds every write the server accepted before it; a 304 changes nothing.
            if answer.value != nil { overlays[id]?.removeAll(where: \.confirmed) }
            timelinePhases[id] = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            timelines[id] = nil
            timelineETags[id] = nil
            timelinePhases[id] = .gone
            bump(id)
        } catch {
            guard started == epoch else { return }
            timelinePhases[id] = timelines[id] == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    private func store(_ value: ProjectTimeline, etag: String?, for id: String) {
        timelines[id] = value
        timelineETags[id] = etag
        bump(id)
        recent.removeAll { $0 == id }
        recent.append(id)
        while recent.count > Self.timelineCapacity {
            let old = recent.removeFirst()
            timelines[old] = nil
            timelineETags[old] = nil
            timelinePhases[old] = nil
            bump(old)
        }
    }

    // MARK: - Optimistic writes (R-PP19)

    func add(_ overlay: ProjectOverlay) {
        overlays[overlay.projectId, default: []].append(overlay)
        bump(overlay.projectId)
    }

    func remove(overlayId: UUID) {
        for key in Array(overlays.keys) {
            let before = overlays[key]?.count ?? 0
            overlays[key]?.removeAll { $0.id == overlayId }
            if (overlays[key]?.count ?? 0) != before { bump(key) }
        }
    }

    /// The server accepted it: the paint stays until the next fresh answer, which holds the write.
    func confirm(_ overlayId: UUID) {
        for key in overlays.keys {
            if let i = overlays[key]?.firstIndex(where: { $0.id == overlayId }) { overlays[key]?[i].confirmed = true }
        }
    }
}

/// R-PP3 — when the visible Projects page asks again: a sync version event that moved a component both `/projects`
/// ETags fold (`entities`, `episodes`, `inbox`; `routers/projects.py`) or the bank itself. A Sleep tick alone does
/// not: nothing the page shows moved.
enum ProjectsRefresh {
    static let components = ["entities", "episodes", "inbox", "bank"]

    static func shouldRevalidate(old: VersionVector?, new: VersionVector?) -> Bool {
        guard let new else { return false }
        guard let old else { return true }
        return components.contains { old.components[$0] != new.components[$0] }
    }
}

/// R-PP19 — a write painted over the cached timeline before the server answers: only what the answer cannot change —
/// a thread settled or restated today, a milestone done today or renamed, a new milestone, a withdrawal. A milestone
/// added here has no slot yet (`pending-…`), so nothing acts on it until the answer lands.
struct ProjectOverlay: Identifiable, Equatable {
    enum Change: Equatable {
        case threadSettled(claimId: String)
        case threadRestated(claimId: String)
        case milestoneDone(slug: String)
        case milestoneRenamed(slug: String, name: String)
        case milestoneAdded(name: String, target: String?)
        case withdrawn(claimId: String)
    }

    let id: UUID
    let projectId: String
    let change: Change
    let day: ISODay
    var confirmed = false

    static func apply(_ overlays: [ProjectOverlay], to timeline: ProjectTimeline) -> ProjectTimeline {
        var t = timeline
        for o in overlays {
            let day = o.day.description
            switch o.change {
            case .threadSettled(let id):
                t.now.threads.removeAll { $0.claimId == id }
            case .threadRestated(let id):
                if let i = t.now.threads.firstIndex(where: { $0.claimId == id }) { t.now.threads[i].lastHeard = day }
            case .milestoneDone(let slug):
                if let i = t.milestones.firstIndex(where: { $0.slug == slug }) {
                    t.milestones[i].status = "done"
                    t.milestones[i].doneOn = day
                }
            case .milestoneRenamed(let slug, let name):
                if let i = t.milestones.firstIndex(where: { $0.slug == slug }) { t.milestones[i].name = name }
            case .milestoneAdded(let name, let target):
                t.milestones.append(ProjectMilestone(slug: "pending-\(o.id.uuidString)", name: name, status: "planned",
                                                     target: target))
            case .withdrawn(let id):
                t.items.removeAll { $0.id == id }
                t.now.threads.removeAll { $0.claimId == id }
            }
        }
        return t
    }
}
