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

    @ObservationIgnored private let api: any ProjectsAPI
    @ObservationIgnored private var listETag: String?
    @ObservationIgnored private var timelineETags: [String: String] = [:]
    @ObservationIgnored private var recent: [String] = []
    @ObservationIgnored private var epoch = 0

    init(api: any ProjectsAPI = APIClient.shared) { self.api = api }

    func phase(_ id: String) -> Phase { timelinePhases[id] ?? .idle }

    /// What the page draws for a project.
    func display(_ id: String) -> ProjectTimeline? { timelines[id] }

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
            timelinePhases[id] = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            timelines[id] = nil
            timelineETags[id] = nil
            timelinePhases[id] = .gone
        } catch {
            guard started == epoch else { return }
            timelinePhases[id] = timelines[id] == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    private func store(_ value: ProjectTimeline, etag: String?, for id: String) {
        timelines[id] = value
        timelineETags[id] = etag
        recent.removeAll { $0 == id }
        recent.append(id)
        while recent.count > Self.timelineCapacity {
            let old = recent.removeFirst()
            timelines[old] = nil
            timelineETags[old] = nil
            timelinePhases[old] = nil
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
