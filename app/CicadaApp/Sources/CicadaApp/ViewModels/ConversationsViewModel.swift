import AppKit
import Foundation

/// What happened when the user asked to reopen a conversation.
enum ResumeOutcome: Equatable {
    case launched(String)   // the terminal app that opened
    case copied(String)     // the command now on the clipboard
    case gone               // 409 — the transcript was retention-cleaned
    case failed(String)
}

/// G48 §4 — the Conversations section's state. On-demand fetch: no Store
/// domain and no SnapshotCache entry, following `/contributors/commits`.
@MainActor
@Observable
final class ConversationsViewModel {

    private(set) var conversations: [ConversationSummary] = []
    /// Ids `load(ids:)` asked for that the bank does not know (a real 404, not
    /// "fell off the end of the recent page"). Empty after every `load()`.
    private(set) var unknownIds: [String] = []
    private(set) var hasLoaded = false
    private(set) var isLoading = false
    private(set) var errorMessage: String?
    var selectedId: String?
    /// G136 R-SU22 — titles past the capped page that match, fetched with
    /// `q=` (applied before the cap, G136 R17). Empty below the cap: the local
    /// filter already saw every row.
    private(set) var beyondCap: [ConversationSummary] = []
    /// The query `beyondCap` answers. The view reads the rows through
    /// `beyondCap(for:)`, so between a keystroke and its debounced widening
    /// the previous query's server rows never sit under the new filter.
    private(set) var beyondCapQuery: String?

    /// `beyondCap` when it answers `query`; empty otherwise.
    func beyondCap(for query: String) -> [ConversationSummary] {
        beyondCapQuery == query ? beyondCap : []
    }

    private let api: any SyncAPI
    private let launch: (String, String?) -> TerminalLauncher.Outcome

    init(
        api: any SyncAPI = APIClient.shared,
        launch: @escaping (String, String?) -> TerminalLauncher.Outcome
            = { command, cwd in TerminalLauncher.launch(command: command, cwd: cwd) }
    ) {
        self.api = api
        self.launch = launch
    }

    func conversation(id: String) -> ConversationSummary? {
        conversations.first { $0.id == id }
    }

    /// A row can offer Resume only when the BACKEND said so. The app never
    /// decides resumability for itself.
    func canResume(_ id: String) -> Bool { conversation(id: id)?.resumable == true }

    /// G124 R5 — `harness`/`origin` are forwarded to the backend, which
    /// filters before its cap; the view model never filters a capped page.
    func load(limit: Int = 20, harness: String? = nil, origin: String? = nil) async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            conversations = try await api.fetchRecentConversations(limit: limit, harness: harness, origin: origin, query: nil)
            unknownIds = []
            hasLoaded = true
            errorMessage = nil
        } catch {
            errorMessage = "Couldn't load conversations"
        }
    }

    /// G136 R-SU22 — widen a source's title filter past the capped page. Asks
    /// only when the loaded page HIT the cap and the query has a token the
    /// server searches (`ConversationSearch.needsServer`); otherwise clears.
    func searchBeyondCap(query: String, harness: String? = nil, origin: String? = nil) async {
        guard ConversationSearch.needsServer(loaded: conversations.count, query: query) else {
            beyondCap = []
            beyondCapQuery = nil
            return
        }
        do {
            let rows = try await api.fetchRecentConversations(limit: ConversationSearch.cap, harness: harness,
                                                              origin: origin, query: query)
            // A widening superseded by the next keystroke never lands over it.
            guard !Task.isCancelled else { return }
            beyondCap = rows
            beyondCapQuery = query
        } catch {
            // The loaded page still filters; a failed widening is not an error to show.
            guard !Task.isCancelled else { return }
            beyondCap = []
            beyondCapQuery = nil
        }
    }

    /// Load an explicit set of conversations BY ID — the popover's path.
    ///
    /// Each id is resolved against the WHOLE bank (`GET /conversations/{id}`),
    /// never by looking it up inside a capped `/recent` page: the live bank
    /// already holds more conversations than that page can carry, so absence
    /// from it means "not recent", not "this bank forgot it". Ids the backend
    /// really doesn't know land in `unknownIds` so the UI can say so exactly.
    func load(ids: [String]) async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            var found: [ConversationSummary] = []
            var missing: [String] = []
            for id in ids {
                if let conversation = try await api.fetchConversation(id: id) {
                    found.append(conversation)
                } else {
                    missing.append(id)
                }
            }
            conversations = found
            unknownIds = missing
            hasLoaded = true
            errorMessage = nil
        } catch {
            // A transport failure is NOT "the bank doesn't have it" — say the
            // honest thing and leave `hasLoaded` false so nothing claims a miss.
            errorMessage = "Couldn't load conversations"
        }
    }

    func resume(_ id: String) async -> ResumeOutcome {
        do {
            let descriptor = try await api.resumeConversation(id: id)
            switch launch(descriptor.displayCommand, descriptor.cwd) {
            case .ghostty: return .launched("Ghostty")
            case .terminal: return .launched("Terminal")
            case .clipboard: return .copied(descriptor.displayCommand)
            }
        } catch APIError.httpError(409, _) {
            return .gone
        } catch APIError.httpError(400, _) {
            return .failed("This conversation can't be resumed")
        } catch APIError.httpError(404, _) {
            // The bank genuinely has no record of this conversation (see
            // `POST /conversations/{id}/resume`'s 404 vs. 409 vs. 400
            // contract) — a missing conversation, not a reachability problem.
            // Reads distinctly from the generic "Couldn't reach Cicada's
            // backend" catch-all below.
            return .failed("This conversation is no longer available in this bank")
        } catch {
            return .failed("Couldn't reach Cicada's backend")
        }
    }

    /// "Copy command" — same 400/409/404 handling as `resume`, no launch. The
    /// command was built backend-side from a UUID-gated id, so it is safe to
    /// put on the pasteboard verbatim.
    func copyCommand(for id: String) async -> ResumeOutcome {
        do {
            let descriptor = try await api.resumeConversation(id: id)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(descriptor.displayCommand, forType: .string)
            return .copied(descriptor.displayCommand)
        } catch APIError.httpError(409, _) {
            return .gone
        } catch APIError.httpError(400, _) {
            return .failed("This conversation can't be resumed")
        } catch APIError.httpError(404, _) {
            // Same PR #20 round-2 review fix as `resume`: a bank switch or
            // deletion between the row rendering and the tap is a missing
            // conversation, not a backend outage — say so distinctly from
            // the generic catch-all below.
            return .failed("This conversation is no longer available in this bank")
        } catch {
            return .failed("Couldn't reach Cicada's backend")
        }
    }
}
