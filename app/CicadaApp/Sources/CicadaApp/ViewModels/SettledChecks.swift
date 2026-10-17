import Foundation
import Observation

/// Owner ruling 2026-10-16 — the Inbox's "Settled by a check" list: questions a web lookup (or the person's own agent)
/// answered with a cited belief. In memory only (not a Store domain, `api.md`): loaded when the Inbox appears and
/// whenever its questions change, never blank on a failed reload (DR-43). Undo removes the row at once and puts it
/// back if the server refuses (writes are optimistic with rollback); a successful undo refreshes the inbox, where the
/// question is back. **Per memory:** a row's id is an inbox id, and those repeat across memories, so the rows belong to
/// the bank they were read in — another bank's read starts empty (even when it fails), and an undo or a track names the
/// bank its row came from (G183(d)), so a row left on screen across a switch is refused, never applied to the other
/// memory's question of the same id.
@Observable
@MainActor
final class SettledChecks {
    private(set) var rows: [SettledCheck] = []
    /// Rows whose citation the person made a tracked source in this session.
    private(set) var tracked: Set<String> = []
    private(set) var busy: Set<String> = []
    var message: String?

    @ObservationIgnored private let api: any SettledChecksAPI
    @ObservationIgnored private let bank: @MainActor () -> String?
    /// The memory `rows` were read in.
    @ObservationIgnored private var rowsBank: String?

    init(api: any SettledChecksAPI = APIClient.shared, bank: @escaping @MainActor () -> String? = { BankScope.onScreen }) {
        self.api = api
        self.bank = bank
    }

    func load() async {
        let reading = bank()
        if reading != rowsBank {
            // Another memory: what was shown is not its own, so it starts empty rather than "never blank".
            rows = []
            tracked = []
            message = nil
            rowsBank = reading
        }
        do {
            let fresh = try await api.fetchSettledChecks()
            guard bank() == reading else { return }   // switched while reading: the next load is the new memory's
            rows = fresh
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
            try await BankScope.bound(to: rowsBank) { try await api.undoSettledCheck(id: row.id) }
            message = nil
            await then()
        } catch {
            rows.insert(row, at: min(at, rows.count))
            message = row.bySleep ? Copy.Inbox.settledSleepUndoFailed : Copy.Inbox.settledUndoFailed
        }
    }

    /// "Track this source": the citation joins the page's sources as the person's own — only on this tap.
    func track(_ row: SettledCheck) async {
        guard row.canTrack, !tracked.contains(row.id), !busy.contains(row.id) else { return }
        busy.insert(row.id)
        defer { busy.remove(row.id) }
        do {
            try await BankScope.bound(to: rowsBank) {
                try await api.trackCitation(entityId: row.entityId, ref: row.ref,
                                            predicate: row.predicate.isEmpty ? nil : row.predicate)
            }
            tracked.insert(row.id)
            message = nil
        } catch {
            message = Copy.Inbox.settledTrackFailed
        }
    }
}
