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
            // A failure is no answer to come back to: it would sit in Recent and show the same wall tomorrow.
            if !response.isEngineFailure {
                history = AskHistory.push(entry, into: history)
                await store.cache.save(history, etag: nil, domain: .askHistory, bank: store.bank)
            }
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

    /// What the person reads when the request itself failed: a sentence and what to do, never a status code, a raw
    /// body or the system's wording (G199 for the app: the cause is in the log).
    nonisolated static func describe(_ error: Error) -> String {
        if let apiError = error as? APIError {
            switch apiError {
            case .serverUnreachable: return Copy.AskWords.unreachable
            case .httpError(let code, let body): return httpMessage(code: code, body: body)
            case .decodingError: return Copy.AskWords.unreadableAnswer
            }
        }
        if let url = error as? URLError {
            switch url.code {
            case .timedOut: return Copy.AskWords.timedOut
            case .cancelled: return Copy.AskWords.cancelled
            default: return Copy.AskWords.unreachable
            }
        }
        return Copy.AskWords.failed
    }

    /// A refusal the backend wrote for the person (a 4xx with a sentence in `detail`) is shown as written; anything
    /// else, a 5xx above all, is the generic line.
    nonisolated static func httpMessage(code: Int, body: String) -> String {
        guard (400..<500).contains(code),
              let data = body.data(using: .utf8),
              let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let detail = json["detail"] as? String,
              !detail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              detail.count <= 240 else { return Copy.AskWords.failed }
        return detail
    }
}
