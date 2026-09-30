import Foundation
import Observation

/// G162 — the honest state of every saved video and the person's queue, in memory. `ProjectsCache` / `BacklogCache`'s
/// twin: one for the app (owned by `CicadaApp`), revalidated with the server's ETag when a page that shows it appears
/// or a sync version event moves what the ETag folds (`VideoRefresh`), emptied on a bank switch (episode and page ids
/// repeat across banks) with an answer in flight across the switch dropped by its epoch. Never blank: a failed or 304
/// answer keeps the last value (DR-43). Never a Store domain — no `VersionVector` mapping, nothing on disk.
///
/// A lease lapsing (or a failed row expiring) writes nothing, so nothing else would tell the app: both reads carry
/// `nextChangeAt` and the cache schedules ONE revalidation there (H2), cancelled and rescheduled on each answer and
/// on a bank switch. Nothing re-derives a video's state (P13): the server is the only deriver.
@Observable
@MainActor
final class VideoStateCache {
    enum Phase: Equatable { case idle, loading, loaded, gone, failed(String) }

    private(set) var state: VideosStateResponse?
    private(set) var phase: Phase = .idle
    /// The Sleep page and the sentence only need the counts.
    private(set) var summaryOnly: VideoSummary?
    /// Queue changes painted over the server's answer until an answer holds them (`Paint`).
    private(set) var paints: [String: Paint] = [:]

    /// One optimistic change: the person just queued a video (with what they asked for) or took it out.
    enum Paint: Equatable {
        case queued(VideoWant)
        case removed
    }

    @ObservationIgnored private let api: any VideosAPI
    @ObservationIgnored private var stateETag: String?
    @ObservationIgnored private var summaryETag: String?
    @ObservationIgnored private var epoch = 0
    @ObservationIgnored private var timer: Task<Void, Never>?
    @ObservationIgnored private let now: @Sendable () -> Date
    @ObservationIgnored private let sleeper: @Sendable (TimeInterval) async throws -> Void
    /// Fired each time the timer wakes, for tests.
    @ObservationIgnored var onScheduled: ((Date) -> Void)?

    init(api: any VideosAPI = APIClient.shared, now: @escaping @Sendable () -> Date = { Date() },
         sleeper: @escaping @Sendable (TimeInterval) async throws -> Void = { try await Task.sleep(nanoseconds: UInt64($0 * 1_000_000_000)) }) {
        self.api = api
        self.now = now
        self.sleeper = sleeper
    }

    // MARK: - What the views read

    /// True once the backend answered 404: an older backend has no video routes, so every video addition disappears
    /// and nothing is invented.
    var isGone: Bool { phase == .gone }

    /// The items with every pending paint over them, in the server's order.
    var items: [VideoStateItem] {
        guard let state else { return [] }
        return state.items.map(painted)
    }

    /// One video by the Feed's own row id (`mediaEntityId|url`).
    func item(feedId: String) -> VideoStateItem? {
        state?.items.first { $0.id == feedId }.map(painted)
    }

    /// One video by its url-index key (the queue's identity).
    func item(key: String) -> VideoStateItem? {
        state?.items.first { $0.key == key }.map(painted)
    }

    /// The counts: recounted over the painted items while a paint is pending (so a Queue tap moves the strip at once),
    /// else the server's own block, else the Sleep page's summary read.
    var summary: VideoSummary? {
        if let state {
            guard !paints.isEmpty else { return state.queue }
            return VideoSummary.count(items: items, batch: state.queue.batch, nextChangeAt: state.queue.nextChangeAt)
        }
        return summaryOnly
    }

    private func painted(_ item: VideoStateItem) -> VideoStateItem {
        guard let paint = paints[item.key] else { return item }
        var out = item
        switch paint {
        case .queued(let want):
            out.queueState = .queued
            out.want = want
            out.failedCode = nil
            out.failedReason = nil
            out.claimedBy = nil
        case .removed:
            out.queueState = nil
            out.want = nil
            out.failedCode = nil
            out.failedReason = nil
            out.claimedBy = nil
            out.batch = nil
        }
        return out
    }

    // MARK: - Reads

    /// Forget everything — a bank switch (`ContentView`).
    func reset() {
        epoch &+= 1
        timer?.cancel()
        timer = nil
        state = nil
        summaryOnly = nil
        paints = [:]
        stateETag = nil
        summaryETag = nil
        phase = .idle
    }

    func refresh() async {
        let started = epoch
        if state == nil { phase = .loading }
        do {
            // Never an ETag with nothing cached: a 304 would leave the page with nothing to draw.
            let answer = try await api.fetchVideoState(etag: state == nil ? nil : stateETag)
            guard started == epoch else { return }
            if let value = answer.value {
                state = value
                stateETag = answer.etag
                settlePaints(against: value)
            }
            phase = .loaded
            schedule(after: state?.nextChangeAt ?? state?.queue.nextChangeAt)
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            state = nil
            stateETag = nil
            summaryOnly = nil
            paints = [:]
            phase = .gone
        } catch {
            guard started == epoch else { return }
            phase = state == nil ? .failed(Copy.Videos.loadFailed(error)) : .loaded
        }
    }

    /// The counts alone, for the Sleep page (no per-video rows).
    func refreshSummary() async {
        guard state == nil else { return await refresh() }
        let started = epoch
        do {
            let answer = try await api.fetchVideoSummary(etag: summaryOnly == nil ? nil : summaryETag)
            guard started == epoch else { return }
            if let value = answer.value {
                summaryOnly = value
                summaryETag = answer.etag
            }
            schedule(after: summaryOnly?.nextChangeAt)
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            summaryOnly = nil
            phase = .gone
        } catch {
            // Never blank: the last counts stand.
        }
    }

    /// A fresh answer that shows a painted change settles it.
    private func settlePaints(against value: VideosStateResponse) {
        for item in value.items {
            switch paints[item.key] {
            case .queued?: if item.isQueued { paints[item.key] = nil }
            case .removed?: if !item.isQueued { paints[item.key] = nil }
            case nil: break
            }
        }
    }

    // MARK: - The one revalidation at nextChangeAt (H2)

    private func schedule(after iso: String?) {
        timer?.cancel()
        timer = nil
        guard let iso, let due = Self.parse(iso) else { return }
        let started = epoch
        let wait = max(1, due.timeIntervalSince(now()))
        onScheduled?(due)
        timer = Task { [sleeper] in
            do { try await sleeper(wait) } catch { return }
            guard !Task.isCancelled else { return }
            await self.wake(epoch: started)
        }
    }

    private func wake(epoch started: Int) async {
        guard started == epoch else { return }
        // A stale ETag would answer 304 for a state that moved without a write: ask for the body.
        stateETag = nil
        summaryETag = nil
        if state != nil { await refresh() } else { await refreshSummary() }
    }

    nonisolated static func parse(_ iso: String) -> Date? {
        let full = ISO8601DateFormatter()
        full.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = full.date(from: iso) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        return plain.date(from: iso)
    }

    // MARK: - Writes (painted, rolled back with the server's sentence)

    /// Queue one video. Returns the sentence to show when it failed, nil on success.
    @discardableResult
    func queue(key: String, want: VideoWant) async -> String? {
        let started = epoch
        let before = paints[key]
        paints[key] = .queued(want)
        do {
            _ = try await api.putVideoQueue(key: key, want: want)
            guard started == epoch else { return nil }
            await refresh()
            return nil
        } catch {
            guard started == epoch else { return nil }
            paints[key] = before
            return Copy.Videos.writeFailed(error)
        }
    }

    @discardableResult
    func remove(key: String) async -> String? {
        let started = epoch
        let before = paints[key]
        paints[key] = .removed
        do {
            try await api.deleteVideoQueue(key: key)
            guard started == epoch else { return nil }
            await refresh()
            return nil
        } catch {
            guard started == epoch else { return nil }
            paints[key] = before
            return Copy.Videos.writeFailed(error)
        }
    }

    @discardableResult
    func retry(key: String) async -> String? {
        let started = epoch
        let before = paints[key]
        paints[key] = .queued(item(key: key)?.want ?? .transcript)
        do {
            _ = try await api.retryVideo(key: key)
            guard started == epoch else { return nil }
            await refresh()
            return nil
        } catch {
            guard started == epoch else { return nil }
            paints[key] = before
            return Copy.Videos.writeFailed(error)
        }
    }

    /// The run's one write: every selected video into the queue, one batch, and the prompt to copy.
    func handoff(items: [(key: String, want: VideoWant)], method: VideoMethod) async -> Result<VideoHandoffResponse, VideoWriteFailure> {
        let started = epoch
        do {
            let response = try await api.handoffVideos(items: items, method: method)
            if started == epoch { await refresh() }
            return .success(response)
        } catch {
            return .failure(VideoWriteFailure(sentence: Copy.Videos.writeFailed(error)))
        }
    }

    /// The prompt for `count` waiting videos, for the preview and for "Copy the prompt again".
    func prompt(count: Int?, method: VideoMethod?) async -> String? {
        try? await api.fetchVideoPrompt(count: count, method: method).prompt
    }
}

struct VideoWriteFailure: Error, Equatable { let sentence: String }

/// When the video reads are asked for again: a sync version event that moved a component both ETags fold
/// (`entities`, `episodes`, `sources`, `videoQueue`) or the bank itself. The queue's own component is `videoQueue` — it
/// has no `VersionVector` mapping (it is not a Store domain), and an unmapped component still reaches `store.version`.
/// A Sleep tick alone does not: nothing the video views show moved.
enum VideoRefresh {
    static let components = ["videoQueue", "episodes", "entities", "sources", "bank"]

    static func shouldRevalidate(old: VersionVector?, new: VersionVector?) -> Bool {
        guard let new else { return false }
        guard let old else { return true }
        return components.contains { old.components[$0] != new.components[$0] }
    }
}

extension VideoSummary {
    /// The server's `summary_from` rule over items — used only to repaint the counts while a Queue or Remove tap waits
    /// for its answer: `unread` is state none with no queue entry, `read` is everything else with none, and Queued is
    /// `queued + claimed + failed`.
    static func count(items: [VideoStateItem], batch: VideoBatch?, nextChangeAt: String?) -> VideoSummary {
        var out = VideoSummary(total: items.count, batch: batch, nextChangeAt: nextChangeAt)
        for item in items {
            switch item.queueState {
            case .queued?: out.queued += 1
            case .claimed?: out.claimed += 1
            case .failed?: out.failed += 1
            case nil: if item.state == .none { out.unread += 1 } else { out.read += 1 }
            }
        }
        return out
    }
}
