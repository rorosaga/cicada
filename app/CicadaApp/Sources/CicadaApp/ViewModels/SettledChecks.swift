import Foundation
import Observation

/// Owner ruling 2026-10-16 — the Inbox's "Settled by a check" list: questions a web lookup (or the person's own agent)
/// answered with a cited belief. In memory only (not a Store domain, `api.md`): loaded when the Inbox appears and
/// whenever its questions change, never blank on a failed reload (DR-43). Undo removes the row at once and puts it
/// back if the server refuses (writes are optimistic with rollback); a successful undo refreshes the inbox, where the
/// question is back.
@Observable
@MainActor
final class SettledChecks {
    private(set) var rows: [SettledCheck] = []
    /// Rows whose citation the person made a tracked source in this session.
    private(set) var tracked: Set<String> = []
    private(set) var busy: Set<String> = []
    var message: String?

    @ObservationIgnored private let api: any SettledChecksAPI

    init(api: any SettledChecksAPI = APIClient.shared) { self.api = api }

    func load() async {
        do {
            rows = try await api.fetchSettledChecks()
        } catch {
            // Never blank: a failed reload keeps what was shown.
        }
    }

    /// The one-tap undo. `then` runs after the server took it back (the Inbox refreshes its questions there).
    func undo(_ row: SettledCheck, then: @escaping @MainActor () async -> Void = {}) async {
        guard !busy.contains(row.id), let at = rows.firstIndex(of: row) else { return }
        busy.insert(row.id)
        rows.remove(at: at)
        defer { busy.remove(row.id) }
        do {
            try await api.undoSettledCheck(id: row.id)
            message = nil
            await then()
        } catch {
            rows.insert(row, at: min(at, rows.count))
            message = Copy.Inbox.settledUndoFailed
        }
    }

    /// "Track this source": the citation joins the page's sources as the person's own — only on this tap.
    func track(_ row: SettledCheck) async {
        guard row.canTrack, !tracked.contains(row.id), !busy.contains(row.id) else { return }
        busy.insert(row.id)
        defer { busy.remove(row.id) }
        do {
            try await api.trackCitation(entityId: row.entityId, ref: row.ref,
                                        predicate: row.predicate.isEmpty ? nil : row.predicate)
            tracked.insert(row.id)
            message = nil
        } catch {
            message = Copy.Inbox.settledTrackFailed
        }
    }
}
