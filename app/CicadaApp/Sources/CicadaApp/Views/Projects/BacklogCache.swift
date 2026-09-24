import Foundation
import Observation

/// G150 (R-B18) — the Backlog section's in-memory cache, `ProjectsCache`'s twin: one for the app, owned by
/// `CicadaApp`, revalidated with the server's ETag when the section appears, an item opens, a write lands, or a sync
/// event moves `backlog`/`entities`/`bank` (`BacklogRefresh`); emptied on a bank switch (ids repeat across banks), and
/// an answer in flight across the switch is dropped by its epoch. Never blank: a failed or 304 answer keeps the last
/// value (DR-43). Only a status move is painted before the server answers (R-B22).
@Observable
@MainActor
final class BacklogCache {
    enum Phase: Equatable { case idle, loading, loaded, gone, failed(String) }

    /// An item is a few KB; twenty covers an afternoon of reading.
    static let itemCapacity = 20

    private(set) var lists: [String: BacklogList] = [:]
    private(set) var listPhases: [String: Phase] = [:]
    private(set) var items: [String: BacklogItem] = [:]
    private(set) var itemPhases: [String: Phase] = [:]
    /// R-B22 — status moves painted over the server's answer, keyed `project/item`, until an answer holds them.
    private(set) var paints: [String: BacklogStatus] = [:]

    @ObservationIgnored private let api: any BacklogAPI
    @ObservationIgnored private var listETags: [String: String] = [:]
    @ObservationIgnored private var itemETags: [String: String] = [:]
    @ObservationIgnored private var recent: [String] = []
    @ObservationIgnored private var epoch = 0

    init(api: any BacklogAPI = APIClient.shared) { self.api = api }

    nonisolated static func key(_ project: String, _ item: String) -> String { "\(project)/\(item)" }

    func listPhase(_ project: String) -> Phase { listPhases[project] ?? .idle }
    func itemPhase(_ project: String, _ item: String) -> Phase { itemPhases[Self.key(project, item)] ?? .idle }

    /// What the section draws: the server's list with every pending move painted over it, counts included.
    func list(_ project: String) -> BacklogList? {
        guard var list = lists[project] else { return nil }
        for i in list.items.indices {
            let old = list.items[i].status
            guard let painted = paints[Self.key(project, list.items[i].id)], painted.rawValue != old else { continue }
            list.counts[old] = max(0, (list.counts[old] ?? 0) - 1)
            list.counts[painted.rawValue, default: 0] += 1
            list.items[i].status = painted.rawValue
        }
        return list
    }

    func item(_ project: String, _ item: String) -> BacklogItem? {
        guard var value = items[Self.key(project, item)] else { return nil }
        if let painted = paints[Self.key(project, item)] { value.summary.status = painted.rawValue }
        return value
    }

    func paint(_ project: String, _ item: String, _ status: BacklogStatus) { paints[Self.key(project, item)] = status }

    func unpaint(_ project: String, _ item: String) { paints[Self.key(project, item)] = nil }

    /// Forget everything — a bank switch (`ContentView`, R-PU26's reason).
    func reset() {
        epoch &+= 1
        lists = [:]
        listPhases = [:]
        items = [:]
        itemPhases = [:]
        paints = [:]
        listETags = [:]
        itemETags = [:]
        recent = []
    }

    func refreshList(_ project: String) async {
        let started = epoch
        if lists[project] == nil { listPhases[project] = .loading }
        do {
            // Never an ETag with nothing cached: a 304 would leave the section with nothing to draw.
            let answer = try await api.fetchBacklog(project: project, etag: lists[project] == nil ? nil : listETags[project])
            guard started == epoch else { return }
            if let value = answer.value {
                lists[project] = value
                listETags[project] = answer.etag
                // A fresh answer that holds a painted move settles it.
                for row in value.items where paints[Self.key(project, row.id)]?.rawValue == row.status {
                    paints[Self.key(project, row.id)] = nil
                }
            }
            listPhases[project] = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            lists[project] = nil
            listETags[project] = nil
            listPhases[project] = .gone
        } catch {
            guard started == epoch else { return }
            listPhases[project] = lists[project] == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    func refreshItem(_ project: String, _ item: String) async {
        let key = Self.key(project, item)
        let started = epoch
        if items[key] == nil { itemPhases[key] = .loading }
        do {
            let answer = try await api.fetchBacklogItem(project: project, item: item,
                                                        etag: items[key] == nil ? nil : itemETags[key])
            guard started == epoch else { return }
            if let value = answer.value {
                store(value, etag: answer.etag, key: key)
                if paints[key]?.rawValue == value.summary.status { paints[key] = nil }
            }
            itemPhases[key] = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            items[key] = nil
            itemETags[key] = nil
            itemPhases[key] = .gone
        } catch {
            guard started == epoch else { return }
            itemPhases[key] = items[key] == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    private func store(_ value: BacklogItem, etag: String?, key: String) {
        items[key] = value
        itemETags[key] = etag
        recent.removeAll { $0 == key }
        recent.append(key)
        while recent.count > Self.itemCapacity {
            let old = recent.removeFirst()
            items[old] = nil
            itemETags[old] = nil
            itemPhases[old] = nil
        }
    }
}

/// R-B18 — when the Projects page asks the backlog again: a sync version event that moved what its ETags fold
/// (`backlog`, `entities`) or the bank itself. A Sleep tick alone does not: nothing the section shows moved.
enum BacklogRefresh {
    static let components = ["backlog", "entities", "bank"]

    static func shouldRevalidate(old: VersionVector?, new: VersionVector?) -> Bool {
        guard let new else { return false }
        guard let old else { return true }
        return components.contains { old.components[$0] != new.components[$0] }
    }
}
