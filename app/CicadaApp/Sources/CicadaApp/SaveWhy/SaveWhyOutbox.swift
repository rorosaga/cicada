import Foundation

/// G191, review B1 — answers the backend could not take yet. The bookmark sync runs inside Sleep's write window, so the
/// panel can show while Sleep holds the pages and `POST /sources/saved-why` answers 409; a backend restart drops the
/// request outright. Either way the person's words must not vanish: the answer is held here (per Mac, outside every
/// bank) with the time the person gave it, and sent again when Sleep's writing flag goes false, after every bookmark
/// sync and on launch. It is dropped only when the backend refuses it for good (422: the answer is invalid) or after
/// `maxAge`, the backend's own bound on a client's `at`.
///
/// **Never lost to a dismissal (owner 2026-10-19: "I bookmarked a website, explained what interested me, and pressed
/// anywhere else on the screen … In Cicada I see that it didn't save").** Two ways an answer used to vanish: an answer
/// given before the backend confirmed the bookmark lived only in memory and was dropped when the confirmation did not
/// come within `SaveWhyPolicy.confirmBound` (a sync refused while Sleep wrote never confirms), and a 404 ("that link
/// isn't saved yet" — its sync had not run) dropped a held answer for good. Now an answer about a link the app's own
/// diff named is held here at once, `awaiting` its sync: it is never posted before a sync of its browser lands (the
/// rail: no answer until a sync confirms the bookmark), and a 404 holds it for the next sync rather than dropping it.
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
        /// The browser it was saved in (2026-10-19), so a sync of that browser releases it.
        var channel: String? = nil
        /// True while no sync of `channel` has landed since the answer was given: never posted until one does.
        var awaiting: Bool? = nil
        /// An edit of the answer said at this time (the star on a page already saved), not a new answer.
        var editAt: String? = nil
        /// The memory it was given in (2026-10-19, the split-brain rule): sent only while that memory is active.
        var bank: String? = nil

        var isAwaiting: Bool { awaiting == true }
    }

    enum Verdict: Equatable {
        /// Try again later: Sleep was writing (409), the backend was unreachable, or it failed on its side.
        case hold
        /// The link is not saved yet (404): kept for the next sync, never a reason to stop the pass.
        case waitForSync
        /// Never retry: the backend said this answer can never land (422, …).
        case drop
    }

    /// What a failed post means for the held answer. A 404 on an edit is final (the answer it names is gone, a sync
    /// will not bring it back); on a new answer it means the link is not saved yet.
    static func verdict(for error: Error, editing: Bool = false) -> Verdict {
        if case APIError.httpError(let code, _) = error {
            if code == 404 { return editing ? .drop : .waitForSync }
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

    /// A sync of `channel` landed: every answer awaiting it may go now — except one still waiting to learn whether
    /// its bookmark was removed in the bubble (`except`).
    func release(channel: String, except: String? = nil) {
        let releasable: (Entry) -> Bool = { $0.isAwaiting && $0.channel == channel && $0.url != except }
        guard entries.contains(where: releasable) else { return }
        entries = entries.map { var e = $0; if releasable(e) { e.awaiting = nil }; return e }
    }

    /// Whether an answer given at `at` about `url` is already held.
    func holds(url: String, at: Date) -> Bool { entries.contains { $0.url == url && $0.at == at } }

    /// The backend agreed about `url`: its awaiting answers may go now.
    func release(url: String) {
        guard entries.contains(where: { $0.isAwaiting && $0.url == url }) else { return }
        entries = entries.map { var e = $0; if e.isAwaiting && e.url == url { e.awaiting = nil }; return e }
    }

    /// The bookmark this answer is about was removed in the browser's bubble: never posted.
    func discardAwaiting(url: String) { entries = entries.filter { !($0.isAwaiting && $0.url == url) } }

    func expired(_ entry: Entry, now: Date) -> Bool { now.timeIntervalSince(entry.at) > Self.maxAge }
}
