import Foundation
import Observation

/// G166 — the sites Cicada's own reader could not read (`GET /reading/sites`), for Home's one line. In memory for the
/// app, `ProjectsCache`'s pattern: revalidated with the server's ETag when Home appears or the sources move, emptied on a
/// bank switch (the counts are per bank), and an answer in flight across the switch is dropped by its epoch. Never
/// blank: a failed or 304 answer keeps the last value. Not a Store domain, no `VersionVector` mapping, nothing on disk.
@Observable
@MainActor
final class ReadingSitesCache {
    typealias Fetch = @MainActor (String?) async throws -> Conditional<ReadingSitesResponse>

    private(set) var value: ReadingSitesResponse?
    @ObservationIgnored private var etag: String?
    @ObservationIgnored private var epoch = 0
    @ObservationIgnored private let fetch: Fetch

    init(fetch: Fetch? = nil) {
        self.fetch = fetch ?? { try await APIClient.shared.fetchReadingSites(etag: $0) }
    }

    func refresh() async {
        let started = epoch
        // Never an ETag with nothing held: a 304 would leave nothing to draw.
        guard let answer = try? await fetch(value == nil ? nil : etag), started == epoch else { return }
        if let fresh = answer.value {
            value = fresh
            etag = answer.etag
        }
    }

    /// Forget everything — a bank switch.
    func reset() {
        epoch &+= 1
        value = nil
        etag = nil
    }
}

/// Home's "N saved pages need your browser to be read": pure, so the view and the tests read one function. Shown only
/// while a site that is not allowed has pages waiting; the count is the server's own (`waitingNotAllowed`), never an
/// inbox count, and at most three of those sites lend their icons, busiest first.
enum HomeReadingLine {
    struct Figures: Equatable {
        let count: Int
        let sites: [ReadingSite]
    }

    static let maxIcons = 3

    static func figures(_ response: ReadingSitesResponse?) -> Figures? {
        guard let response else { return nil }
        let waiting = response.sites.filter { !$0.allowed && $0.waiting > 0 }
        let count = response.waitingNotAllowed
        guard count > 0, !waiting.isEmpty else { return nil }
        let busiest = waiting.enumerated()
            .sorted { $0.element.waiting != $1.element.waiting ? $0.element.waiting > $1.element.waiting : $0.offset < $1.offset }
            .map(\.element)
        return Figures(count: count, sites: Array(busiest.prefix(maxIcons)))
    }
}
