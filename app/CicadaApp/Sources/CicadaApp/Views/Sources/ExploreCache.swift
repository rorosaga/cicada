import Foundation
import Observation

/// G166 exploring — the run and the Explore sheet's counts, in memory. `VideoStateCache`'s twin: one for the app (owned
/// by `CicadaApp`), revalidated with the server's ETag when the Sources page appears or a sync version event moves what
/// the ETag folds (`ExploreRefresh`), emptied on a bank switch with an answer in flight across the switch dropped by its
/// epoch. Never blank: a failed or 304 answer keeps the last value (DR-43). Never a Store domain. Nothing here derives a
/// site's state: the server is the only deriver.
@Observable
@MainActor
final class ExploreCache {
    enum Phase: Equatable { case idle, loading, loaded, gone, failed(String) }

    private(set) var state: ExploreState?
    private(set) var candidates: ExploreCandidates?
    private(set) var phase: Phase = .idle
    /// The prompt the last start or "Copy for an agent" produced, for the sheet to show and copy.
    private(set) var prompt: String?
    private(set) var note: String?
    private(set) var busy = false
    /// A page that shows the run has asked for it; the sync-driven revalidation reads only then.
    private(set) var wantsReads = false

    @ObservationIgnored private let api: any ExploreAPI
    @ObservationIgnored private var stateETag: String?
    @ObservationIgnored private var candidatesETag: String?
    @ObservationIgnored private var epoch = 0

    init(api: any ExploreAPI = APIClient.shared) { self.api = api }

    /// True once the backend answered 404: an older backend has no explore routes, and the button disappears.
    var isGone: Bool { phase == .gone }
    var batch: ExploreBatch? { state?.batch }

    /// The card shows while a run exists (running, stopped or done) — the server drops a finished one after a day.
    var showsCard: Bool { batch != nil }

    /// The chip for a saved link's row, by the Feed's own row id (`mediaEntityId|url`).
    func item(mediaEntityId: String, url: String?) -> ExploreItem? {
        state?.items.first { $0.mediaEntityId == mediaEntityId && ($0.url == url || url == nil) }
    }

    func reset() {
        epoch &+= 1
        state = nil
        candidates = nil
        stateETag = nil
        candidatesETag = nil
        prompt = nil
        note = nil
        phase = .idle
    }

    func revalidate() async {
        guard wantsReads else { return }
        await refresh()
    }

    func refresh() async {
        wantsReads = true
        let started = epoch
        if state == nil { phase = .loading }
        do {
            let answer = try await api.fetchExploreState(etag: state == nil ? nil : stateETag)
            guard started == epoch else { return }
            if let value = answer.value {
                state = value
                stateETag = answer.etag
            }
            phase = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            state = nil
            stateETag = nil
            phase = .gone
        } catch {
            guard started == epoch else { return }
            phase = state == nil ? .failed(Copy.Explore.loadFailed(error)) : .loaded
        }
    }

    func refreshCandidates() async {
        let started = epoch
        do {
            let answer = try await api.fetchExploreCandidates(etag: candidates == nil ? nil : candidatesETag)
            guard started == epoch else { return }
            if let value = answer.value {
                candidates = value
                candidatesETag = answer.etag
            }
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            phase = .gone
        } catch {
            // Never blank: the last counts stand.
        }
    }

    /// Why the sheet's Explore button can't be pressed, or nil when it can (DR-41: the help says why).
    func blockedReason(scope: ExploreScope) -> String? {
        guard let c = candidates else { return Copy.Explore.startHelpNone }
        if c.demo { return Copy.Explore.startHelpDemo }
        if !c.agentEnabled { return Copy.Explore.startHelpOff }
        if !c.skillVerified { return Copy.Explore.startHelpSkill }
        let count = scope == .all ? c.eligible : c.neverExplored
        return count == 0 ? Copy.Explore.startHelpNone : nil
    }

    /// The person's click: one batch, then the prompt to copy. Returns true on success.
    @discardableResult
    func start(scope: ExploreScope, origins: [String] = []) async -> Bool {
        busy = true
        defer { busy = false }
        let started = epoch
        do {
            let response = try await api.startExplore(scope: scope, origins: origins)
            guard started == epoch else { return false }
            prompt = response.prompt
            note = nil
            await refresh()
            return true
        } catch APIError.httpError(let code, let body) where code == 409 || code == 422 {
            note = ProjectWriteFailure.detail(body) ?? Copy.Explore.saveFailed
            return false
        } catch {
            note = Copy.Explore.saveFailed
            return false
        }
    }

    /// One tap stops the run: waiting sites are dropped, a site an agent holds finishes.
    func stop() async {
        busy = true
        defer { busy = false }
        do {
            _ = try await api.stopExplore()
            note = nil
            await refresh()
        } catch {
            note = Copy.Explore.saveFailed
        }
    }

    /// "Copy for an agent": the prompt again, to add another worker. Copies it and keeps it for the sheet.
    @discardableResult
    func copyPrompt() async -> Bool {
        do {
            let text = try await api.fetchExplorePrompt().prompt
            prompt = text
            AppPasteboard.copy(text)
            return true
        } catch {
            note = Copy.Explore.saveFailed
            return false
        }
    }
}

/// The components `/explore/state`'s ETag folds: the queue file, the capture records, the saved links, the person's
/// reading settings, and a bank switch.
enum ExploreRefresh {
    static let components = ["exploreQueue", "captures", "sources", "reading", "bank"]

    static func shouldRevalidate(old: VersionVector?, new: VersionVector?) -> Bool {
        guard let new else { return false }
        guard let old else { return true }
        return components.contains { old.components[$0] != new.components[$0] }
    }
}
