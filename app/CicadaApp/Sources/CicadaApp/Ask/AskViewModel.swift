import Foundation
import Observation

/// Backs the ⌘K Ask panel (G52, spec §5.9). `POST /ask` returns a grounded
/// answer with wikilink-style citations and an explicit gap list — this VM
/// owns the request lifecycle plus a small per-bank history ring buffer
/// persisted through `Store.cache` under the `.askHistory` domain (which the
/// Store's own refresh/version-vector plumbing deliberately ignores — see
/// `Sync/Store.swift`).
@Observable
@MainActor
final class AskViewModel {
    private let store: Store

    var question: String = ""
    /// The most recent answer. Deliberately never cleared while a new
    /// request is in flight — `AskPanel` dims it via `isAsking` instead of
    /// blanking the panel between question and answer.
    var answer: AskResponse?
    var isAsking = false
    var error: String?
    var history: [AskHistoryEntry] = []

    init(store: Store) {
        self.store = store
    }

    /// Load persisted history for the currently active bank. Called by
    /// `AskPanel.onAppear` — cheap (one disk read) and keeps the VM itself
    /// free of a bootstrap step every caller has to remember to run.
    func loadHistory() async {
        let hit = await store.cache.load(.askHistory, bank: store.bank, as: [AskHistoryEntry].self)
        history = hit?.value ?? []
    }

    /// Submit `question` to `POST /ask`. No-op on a blank/whitespace-only
    /// question. Errors are surfaced inline; the previous answer (if any)
    /// stays on screen throughout.
    func ask() async {
        let trimmed = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isAsking else { return }
        isAsking = true
        error = nil
        defer { isAsking = false }
        do {
            let response = try await APIClient.shared.ask(query: trimmed)
            answer = response
            let entry = AskHistoryEntry(question: trimmed, askedAt: Date(), answer: response)
            history = AskHistory.push(entry, into: history)
            await store.cache.save(history, etag: nil, domain: .askHistory, bank: store.bank)
        } catch {
            self.error = Self.describe(error)
        }
    }

    /// Re-run a past question from history — used when the user taps a
    /// recent-question row.
    func select(_ entry: AskHistoryEntry) {
        question = entry.question
        if let answer = entry.answer { self.answer = answer }
    }

    private static func describe(_ error: Error) -> String {
        if let apiError = error as? APIError {
            switch apiError {
            case .serverUnreachable: return "Cicada backend is unreachable."
            case .httpError(let code, let message): return "Ask failed (\(code)): \(message)"
            case .decodingError: return "Couldn't parse the answer."
            }
        }
        return error.localizedDescription
    }
}
