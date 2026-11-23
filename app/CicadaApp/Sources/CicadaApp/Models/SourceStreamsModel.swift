import Foundation
import Observation

/// G245 — what `GET /sources/streams` last said, in memory for the app. **Not a Store domain, on purpose** (CLAUDE.md,
/// Sync: a read that is not a Store domain says so and caches in memory): a Store domain is hydrated from disk and moves
/// by SSE deltas under a `VersionVector` mapping, and this answer has neither — the backend sends no delta for it, and a
/// stale copy on disk would draw a stream's count and health from a past run. It is also a new route a backend may not
/// ship yet (404), which a Store domain's never-blank hydration cannot say: here a 404 is the page's own state, "no
/// streams yet", and every caller falls back to the catalogue row. The shape is `ReadingSitesCache`'s: revalidated with
/// the ETag when the Sources page appears, when the channels move and after a write or a check; emptied on a bank switch
/// (counts are per bank, an answer in flight across the switch is dropped by its epoch); a failure or a 304 keeps what
/// is held — never blank (DR-43).
@Observable
@MainActor
final class SourceStreamsModel {
    enum Phase: Equatable {
        case idle
        case loading
        case loaded
        /// The backend answered 404: it ships no streams yet. The page draws the catalogue row.
        case absent
        case failed
    }

    typealias Fetch = @MainActor (String?) async throws -> Conditional<SourceStreamsResponse>

    private(set) var value: SourceStreamsResponse?
    private(set) var phase: Phase = .idle
    @ObservationIgnored private var etag: String?
    @ObservationIgnored private var epoch = 0
    /// The newest read: a slower, older answer never replaces it.
    @ObservationIgnored private var reads = 0
    @ObservationIgnored private let fetch: Fetch

    init(fetch: Fetch? = nil) {
        self.fetch = fetch ?? { try await APIClient.shared.fetchSourceStreams(etag: $0) }
    }

    /// The source's streams, or none (older backend, source not named, nothing read yet).
    func source(_ id: String) -> SourceStreamsSource? { value?.source(id) }

    /// Read or revalidate. Never an ETag with nothing held: a 304 would leave nothing to draw.
    func refresh() async {
        let started = epoch
        reads &+= 1
        let read = reads
        if value == nil { phase = .loading }
        do {
            let answer = try await fetch(value == nil ? nil : etag)
            guard started == epoch, read == reads else { return }
            if let fresh = answer.value {
                value = fresh
                etag = answer.etag
            }
            phase = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch, read == reads else { return }
            value = nil
            etag = nil
            phase = .absent
        } catch {
            guard started == epoch, read == reads, !SyncCancellation.isCancellation(error) else { return }
            // Keep what is held; with nothing held the page is on its catalogue rows, which is what `.failed` says.
            phase = value == nil ? .failed : .loaded
        }
    }

    /// A check's own answer (`POST /sources/streams/check`) is the same rows as the GET: it replaces what is held.
    /// The ETag is dropped, since the next GET is a different body than the one the tag named.
    func apply(_ fresh: SourceStreamsResponse) {
        reads &+= 1
        value = fresh
        etag = nil
        phase = .loaded
    }

    /// Forget everything — a bank switch.
    func reset() {
        epoch &+= 1
        reads &+= 1
        value = nil
        etag = nil
        phase = .idle
    }
}
