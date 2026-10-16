import Foundation

/// G191, review B1 — answers the backend could not take yet. The bookmark sync runs inside Sleep's write window, so the
/// panel can show while Sleep holds the pages and `POST /sources/saved-why` answers 409; a backend restart drops the
/// request outright. Either way the person's words must not vanish: the answer is held here (per Mac, outside every
/// bank) with the time the person gave it, and sent again when Sleep's writing flag goes false and on launch. It is
/// dropped when the backend refuses it for good (404: the link is not saved; 422: the answer is invalid) or after
/// `maxAge`, the backend's own bound on a client's `at`.
struct SaveWhyOutbox {
    static let key = "cicada.saveWhy.pending"
    /// Matches `saved_why.MAX_CLIENT_AGE`: an older `at` would be refused anyway.
    static let maxAge: TimeInterval = 24 * 60 * 60
    /// A small queue: one answer per link, and a stuck backend must not grow it forever.
    static let capacity = 20

    struct Entry: Codable, Equatable {
        let url: String
        let answer: SavedWhyAnswer
        let at: Date
        /// G191 v3 — the moment of saving it answers (the browser's instant), when known.
        var addedAt: String? = nil
    }

    enum Verdict: Equatable {
        /// Try again later: Sleep was writing (409), the backend was unreachable, or it failed on its side.
        case hold
        /// Never retry: the backend said this answer can never land (404, 422, …).
        case drop
    }

    /// What a failed post means for the held answer.
    static func verdict(for error: Error) -> Verdict {
        if case APIError.httpError(let code, _) = error {
            return code == 409 || code == 401 || code == 408 || code == 429 || code >= 500 ? .hold : .drop
        }
        if case APIError.serverUnreachable = error { return .hold }
        if error is URLError { return .hold }
        return .drop
    }

    let defaults: UserDefaults

    var entries: [Entry] {
        get {
            guard let data = defaults.data(forKey: Self.key) else { return [] }
            return (try? JSONDecoder().decode([Entry].self, from: data)) ?? []
        }
        nonmutating set {
            if newValue.isEmpty { defaults.removeObject(forKey: Self.key); return }
            defaults.set(try? JSONEncoder().encode(Array(newValue.suffix(Self.capacity))), forKey: Self.key)
        }
    }

    /// One held answer per moment of saving: the same answer held again replaces itself; another save's answer for
    /// the same link (G191 v3: a re-save is a new dated reason) is kept beside it.
    func hold(_ entry: Entry) {
        entries = entries.filter { !($0.url == entry.url && ($0.at == entry.at || ($0.addedAt != nil
            && $0.addedAt == entry.addedAt))) } + [entry]
    }

    func remove(_ entry: Entry) { entries = entries.filter { $0 != entry } }

    func expired(_ entry: Entry, now: Date) -> Bool { now.timeIntervalSince(entry.at) > Self.maxAge }
}
