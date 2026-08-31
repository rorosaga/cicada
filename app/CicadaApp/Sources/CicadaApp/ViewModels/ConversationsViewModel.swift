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

    func load(limit: Int = 20) async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            conversations = try await api.fetchRecentConversations(limit: limit)
            unknownIds = []
            hasLoaded = true
            errorMessage = nil
        } catch {
            errorMessage = "Couldn't load conversations"
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
        } catch {
            return .failed("Couldn't reach Cicada's backend")
        }
    }

    /// "Copy command" — same 400/409 handling, no launch. The command was
    /// built backend-side from a UUID-gated id, so it is safe to put on the
    /// pasteboard verbatim.
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
        } catch {
            return .failed("Couldn't reach Cicada's backend")
        }
    }
}
