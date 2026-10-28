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
/// answer in flight across the switch is dropped by its epoch rather than painted under the new bank. Within one bank,
/// overlapping refreshes of one resource are ordered by `RequestGenerations` (audit 2026-10-05 P2-6): only the newest
/// request's answer is kept, and a confirmed write's paint is cleared only by an answer requested after it was confirmed.
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
    /// Ruling 45 — the tied conversations, per project (`GET /projects/{id}/conversations`), fetched on demand.
    private(set) var conversations: [String: ProjectConversationsPage] = [:]
    /// Ruling 45 — the person's ownership, header, tie and influence writes painted over the list, the timeline and
    /// the conversations until an answer requested after the server confirmed them holds them.
    private(set) var paints: [ProjectPaint] = []

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
    @ObservationIgnored private var generations = RequestGenerations()
    /// The generation that was newest for its project when each overlay was confirmed — an answer requested no later
    /// than that may predate the write, so it does not clear the paint.
    @ObservationIgnored private var confirmedAt: [UUID: Int] = [:]
    @ObservationIgnored private var conversationETags: [String: String] = [:]
    /// Ruling 45 — a clock for paints: a paint confirmed at tick `t` is settled by any answer requested after `t`.
    @ObservationIgnored private var paintClock = 0
    private static let listKey = "\u{0}list"

    init(api: any ProjectsAPI = APIClient.shared) { self.api = api }

    func phase(_ id: String) -> Phase { timelinePhases[id] ?? .idle }

    func revision(_ id: String) -> Int { revisions[id] ?? 0 }

    private func bump(_ id: String) {
        revisions[id] = nextRevision
        nextRevision &+= 1
    }

    /// What the page draws for a project: the server's answer with every pending write painted over it (R-PP19).
    func display(_ id: String) -> ProjectTimeline? {
        timelines[id].map { ProjectPaint.apply(paints, to: ProjectOverlay.apply(overlays[id] ?? [], to: $0)) }
    }

    /// The list with the person's pending ownership and header writes painted over it (ruling 45).
    var displayList: ProjectsResponse? { list.map { ProjectPaint.apply(paints, to: $0) } }

    /// The tied conversations with a pending untie painted out.
    func displayConversations(_ id: String) -> ProjectConversationsPage? {
        conversations[id].map { ProjectPaint.apply(paints, to: $0, project: id) }
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
        confirmedAt = [:]
        conversations = [:]
        conversationETags = [:]
        paints = []
        revisions = [:]   // `nextRevision` runs on: a revision from before the switch never matches one after it.
    }

    func refreshList() async {
        let started = epoch
        let tick = paintClock
        let generation = generations.begin(Self.listKey)
        if list == nil { listPhase = .loading }
        do {
            // Never an ETag with nothing cached: a 304 would leave the page with nothing to draw.
            let answer = try await api.fetchProjects(etag: list == nil ? nil : listETag)
            // A superseded answer is still taken when nothing is shown yet — never blank (DR-43).
            guard started == epoch, generations.isLatest(Self.listKey, generation) || list == nil else { return }
            if let value = answer.value {
                list = value
                listETag = answer.etag
            }
            if answer.value != nil || answer.notModified { settlePaints(requestedAt: tick, read: Self.listKey) }
            listPhase = .loaded
        } catch {
            guard started == epoch, generations.isLatest(Self.listKey, generation) else { return }
            listPhase = list == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    func refreshTimeline(_ id: String) async {
        let started = epoch
        let tick = paintClock
        let generation = generations.begin(id)
        if timelines[id] == nil { timelinePhases[id] = .loading }
        do {
            let answer = try await api.fetchProjectTimeline(id: id, etag: timelines[id] == nil ? nil : timelineETags[id])
            guard started == epoch, generations.isLatest(id, generation) || timelines[id] == nil else { return }
            if let value = answer.value { store(value, etag: answer.etag, for: id) }
            if answer.value != nil || answer.notModified { settlePaints(requestedAt: tick, read: "t:\(id)") }
            // Any answer — fresh or a 304 over what is cached — holds every write the server accepted before it was
            // REQUESTED, so it settles a paint confirmed before then.
            if answer.value != nil || answer.notModified {
                overlays[id]?.removeAll { $0.confirmed && (confirmedAt[$0.id] ?? 0) < generation }
                confirmedAt = confirmedAt.filter { key, _ in overlays.values.contains { $0.contains { $0.id == key } } }
            }
            timelinePhases[id] = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch, generations.isLatest(id, generation) else { return }
            timelines[id] = nil
            timelineETags[id] = nil
            timelinePhases[id] = .gone
            bump(id)
        } catch {
            guard started == epoch, generations.isLatest(id, generation) else { return }
            timelinePhases[id] = timelines[id] == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    /// Ruling 45 — the conversations tied to a project, revalidated with the server's ETag; never blank.
    func refreshConversations(_ id: String) async {
        let started = epoch
        let tick = paintClock
        do {
            let answer = try await api.fetchProjectConversations(id: id, etag: conversations[id] == nil ? nil
                                                                     : conversationETags[id])
            guard started == epoch else { return }
            if let value = answer.value {
                conversations[id] = value
                conversationETags[id] = answer.etag
            }
            if answer.value != nil || answer.notModified { settlePaints(requestedAt: tick, read: "c:\(id)") }
        } catch {
            // Last-known-good stays (DR-43); the panel says nothing new rather than blanking.
        }
    }

    // MARK: - Ruling 45 paints

    func paint(_ change: ProjectChange, id: UUID) {
        paints.append(ProjectPaint(id: id, change: change))
        if let project = change.projectId { bump(project) }
    }

    func unpaint(_ id: UUID) {
        let gone = paints.filter { $0.id == id }
        paints.removeAll { $0.id == id }
        for p in gone { if let project = p.change.projectId { bump(project) } }
    }

    /// The server accepted it: the paint stays until every read that draws it has answered after now — the list, the
    /// project's timeline, its conversations — so no surface flashes the old words while another answers first.
    func confirmPaint(_ id: UUID) {
        paintClock &+= 1
        guard let i = paints.firstIndex(where: { $0.id == id }) else { return }
        paints[i].confirmedAt = paintClock
        paints[i].awaiting = ProjectPaint.reads(paints[i].change)
        if paints[i].awaiting.isEmpty { paints.remove(at: i) }
    }

    private func settlePaints(requestedAt tick: Int, read: String) {
        var changed = false
        for i in paints.indices where (paints[i].confirmedAt ?? Int.max) <= tick && paints[i].awaiting.contains(read) {
            paints[i].awaiting.remove(read)
            changed = true
        }
        guard changed else { return }
        paints.removeAll { $0.confirmedAt != nil && $0.awaiting.isEmpty }
        for key in timelines.keys { bump(key) }
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
            if let i = overlays[key]?.firstIndex(where: { $0.id == overlayId }) {
                overlays[key]?[i].confirmed = true
                confirmedAt[overlayId] = generations.current(key)
            }
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


/// Ruling 45 — one of the person's ownership, header, tie or influence writes, painted over what the server last said
/// until an answer requested after its confirmation holds it. Only what the answer cannot change: a project moved in
/// or out of the list, the header's new words, a conversation untied, an influence taken back. A new project, an
/// accepted grouping, a tie and a new influence wait for the server (their id or row comes from it).
struct ProjectPaint: Identifiable, Equatable {
    let id: UUID
    let change: ProjectChange
    var confirmedAt: Int?
    /// The reads that still have to answer (after the confirmation) before the paint goes.
    var awaiting: Set<String> = []

    /// Which reads draw this paint: the list (`ProjectsCache.listKey`), a timeline (`t:<id>`), conversations (`c:<id>`).
    static func reads(_ change: ProjectChange) -> Set<String> {
        let list = "\u{0}list"
        switch change {
        case .accept(let id, _), .dismiss(let id), .header(let id, _, _): return [list, "t:\(id)"]
        case .tie(let id, _, true): return ["t:\(id)", "c:\(id)"]
        case .withdrawInfluence(let id, _, _, _, _), .tiePage(let id, _, _, _, _): return ["t:\(id)"]
        case .create, .tie, .addInfluence: return []
        }
    }

    init(id: UUID, change: ProjectChange) {
        self.id = id
        self.change = change
    }

    static func apply(_ paints: [ProjectPaint], to list: ProjectsResponse) -> ProjectsResponse {
        var out = list
        for p in paints {
            switch p.change {
            case .accept(let id, let name):
                if let i = out.projects.firstIndex(where: { $0.id == id }) {
                    out.projects[i].mine = true
                    if let name, !name.isEmpty { out.projects[i].name = name }
                }
                out.suggested.removeAll { $0.id == id }
            case .dismiss(let id):
                if let i = out.projects.firstIndex(where: { $0.id == id }) { out.projects[i].mine = false }
                if let i = out.suggested.firstIndex(where: { $0.id == id }), !out.suggested[i].dismissed {
                    out.suggested[i].dismissed = true
                    out.dismissed += 1
                } else if let row = list.projects.first(where: { $0.id == id }),
                          !out.suggested.contains(where: { $0.id == id }) {
                    out.suggested.append(SuggestedProject(id: id, name: row.name, dismissed: true))
                    out.dismissed += 1
                }
            case .header(let id, let name, let description):
                if let i = out.projects.firstIndex(where: { $0.id == id }) {
                    if let name, !name.isEmpty { out.projects[i].name = name }
                    if let description {
                        out.projects[i].description = description.isEmpty ? nil : description
                        if !description.isEmpty { out.projects[i].oneLiner = description }
                    }
                }
            default:
                break
            }
        }
        return out
    }

    static func apply(_ paints: [ProjectPaint], to timeline: ProjectTimeline) -> ProjectTimeline {
        var t = timeline
        for p in paints where p.change.projectId == timeline.project.id {
            switch p.change {
            case .header(_, let name, let description):
                if let name, !name.isEmpty { t.project.name = name }
                if let description {
                    t.project.description = description.isEmpty ? nil : description
                    t.project.descriptionBy = ProjectDescriptionBy(by: "user", day: nil)
                }
            case .accept(_, let name):
                t.project.mine = true
                if let name, !name.isEmpty { t.project.name = name }
            case .dismiss:
                t.project.mine = false
            case .withdrawInfluence(_, let claimId, _, let ref, _):
                t.influences.removeAll { ($0.claimId != nil && $0.claimId == claimId) || ($0.ref != nil && $0.ref == ref) }
            case .tie(_, _, true):
                t.conversationCount = max(0, t.conversationCount - 1)
            case .tiePage(_, let entity, let name, let type, let remove):
                t = ProjectPagesPaint.apply(t, entity: entity, name: name, type: type, remove: remove)
            default:
                break
            }
        }
        return t
    }

    static func apply(_ paints: [ProjectPaint], to page: ProjectConversationsPage, project: String)
        -> ProjectConversationsPage {
        var out = page
        for p in paints {
            if case .tie(let id, let episode, true) = p.change, id == project,
               out.conversations.contains(where: { $0.episodeId == episode }) {
                out.conversations.removeAll { $0.episodeId == episode }
                out.total = max(0, out.total - 1)
            }
        }
        return out
    }
}
