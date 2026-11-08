import Foundation
import Observation

/// 2026-11-08 — the person's own Google Books API key: an optional source for a book Open Library left without a
/// description. The backend owns it (`GET|PUT|DELETE /sources/google-books`); this is one client. The key goes to the
/// backend once and is never read back: the status holds only whether one is saved and the last problem in words.
struct GoogleBooksKeyStatus: Codable, Equatable {
    var connected: Bool
    var whatItDoes: String
    var freeWords: String
    var keyUrl: String
    var problem: String?
    var problemWords: String?
}

@MainActor
@Observable
final class GoogleBooksKeyModel {
    static let shared = GoogleBooksKeyModel()
    /// The Sources entry's id.
    static let id = "google-books"

    private(set) var status: GoogleBooksKeyStatus?
    private(set) var saving = false
    /// Why the last Save was refused, in the backend's words.
    private(set) var failure: String?

    var connected: Bool { status?.connected ?? false }

    func refresh() async {
        if let fresh = try? await APIClient.shared.fetchGoogleBooksKey() { status = fresh }
    }

    /// The person's Save: the backend checks the key with Google and keeps it only if Google accepts it.
    func save(_ key: String) async -> Bool {
        saving = true
        failure = nil
        defer { saving = false }
        do {
            status = try await APIClient.shared.saveGoogleBooksKey(key)
            return true
        } catch APIError.httpError(_, let body) {
            failure = IntakeFailureWords.detail(in: body) ?? Copy.googleBooksSaveFailed
        } catch {
            failure = Copy.googleBooksSaveFailed
        }
        return false
    }

    func remove() async {
        failure = nil
        if let fresh = try? await APIClient.shared.removeGoogleBooksKey() { status = fresh }
    }
}
