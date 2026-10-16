import SwiftUI

/// G191 v3 — a bookmark's reasons, changed on its page (the Feed's detail): one answer edited (`at` names it) or one
/// added (`at` nil). Run by `Store.perform` like every write. The page's list is painted with the change at once and
/// replaced by the server's own list when it lands; a failure restores it and toasts. The list lives on the page
/// (`@State`), not in a Store domain — `GET /sources` brings the same answers back on the `.sources` refresh.
struct SavedWhyWrite: Mutation {
    let url: String
    /// The answer's `at` when editing one; nil adds a new answer, said now.
    let at: String?
    let answer: SavedWhyAnswer
    let answers: Binding<[SavedWhyRecord]>
    let labels: [String: String]
    private let previous = MutationMemo<[SavedWhyRecord]>()
    private let failure = MutationMemo<any Error>()

    init(url: String, at: String?, answer: SavedWhyAnswer, answers: Binding<[SavedWhyRecord]>,
         labels: [String: String] = [:]) {
        self.url = url
        self.at = at
        self.answer = answer
        self.answers = answers
        self.labels = labels
    }

    func optimistic(_ store: Store) async {
        previous.value = answers.wrappedValue
        answers.wrappedValue = Self.applying(answer, at: at, to: answers.wrappedValue, labels: labels)
    }

    func request(_ api: any SyncAPI) async throws {
        do {
            let reply = try await api.writeSavedWhy(url: url, at: at, answer: answer)
            if let history = reply.history, !history.isEmpty { answers.wrappedValue = history }
            else { answers.wrappedValue = Self.applying(answer, at: at, to: previous.value ?? [], labels: labels,
                                                        record: reply.savedWhy) }
        } catch {
            failure.value = error
            throw error
        }
    }

    func rollback(_ store: Store) async {
        if let previous = previous.value { answers.wrappedValue = previous }
    }

    var failureMessage: String { BookmarkWriteFailure.message(failure.value, fallback: Copy.Bookmarks.editFailed) }

    var refreshDomains: Set<SyncDomain> { [.sources] }

    /// The list as the server will hold it: the answer at `at` replaced (its times kept), or a new one added last.
    static func applying(_ answer: SavedWhyAnswer, at: String?, to list: [SavedWhyRecord], labels: [String: String],
                         record: SavedWhyRecord? = nil) -> [SavedWhyRecord] {
        var shaped = record ?? SavedWhyRecord(reasons: answer.reasons, labels: answer.reasons.map { labels[$0] ?? $0 },
                                              project: answer.project, text: answer.text, at: at)
        if let at, let i = list.firstIndex(where: { $0.at == at }) {
            var out = list
            shaped.at = list[i].at
            shaped.addedAt = shaped.addedAt ?? list[i].addedAt
            shaped.editedAt = shaped.editedAt ?? ISO8601DateFormatter().string(from: Date())
            out[i] = shaped
            return out
        }
        if shaped.at == nil { shaped.at = ISO8601DateFormatter().string(from: Date()) }
        return list + [shaped]
    }
}

/// G191 v3 — Remove on a bookmark's page: Cicada forgets it (`POST /sources/bookmarks/remove`, the page archived and
/// its episode tombstoned — never deleted). Nothing is painted first: the page closes on success and the `.sources`
/// refresh drops the row everywhere (the Feed, the history, a source page).
struct BookmarkRemove: Mutation {
    let url: String
    private let failure = MutationMemo<any Error>()

    init(url: String) { self.url = url }

    func optimistic(_ store: Store) async {}

    func request(_ api: any SyncAPI) async throws {
        do {
            try await api.removeBookmark(url: url)
        } catch {
            failure.value = error
            throw error
        }
    }

    func rollback(_ store: Store) async {}

    var failureMessage: String { BookmarkWriteFailure.message(failure.value, fallback: Copy.Bookmarks.removeFailed) }

    var refreshDomains: Set<SyncDomain> { [.sources, .sourcesOverview, .channels] }
}

/// The server's own sentence for a refused write (Sleep holding the pages, a link not saved, an empty answer), else
/// `fallback`; a backend that is down says so.
enum BookmarkWriteFailure {
    static func message(_ error: (any Error)?, fallback: String) -> String {
        guard let api = error as? APIError else { return fallback }
        switch api {
        case .httpError(let code, let body) where [400, 404, 409, 422].contains(code):
            return ProjectWriteFailure.detail(body) ?? fallback
        case .serverUnreachable: return Copy.Graph.sourceBackendDown
        default: return fallback
        }
    }
}

/// G191 v3 — removing the bookmark from Chrome too, through Apple Events (`ChromeBookmarkScript`), after the person
/// confirmed. The app reads Chrome's `Bookmarks` file (no permission) to find the bookmark's nodes; the first delete
/// asks macOS's one-time "Cicada wants to control Google Chrome" — only at this moment, never before.
enum ChromeBookmarkRemoval {
    enum Outcome: Equatable {
        case removed(Int)
        /// Chrome holds no copy (or its file could not be read).
        case notInChrome
        /// The script ran and deleted nothing: the profile Chrome has open does not hold that bookmark.
        case noneMatched
        /// Only under Mobile bookmarks, which Apple Events cannot reach.
        case unreachable
        /// The person (or macOS) refused Automation.
        case denied
        case failed(String)
    }

    /// What Remove would do in Chrome, read from Chrome's default-profile file (no permission): nil when Chrome holds
    /// no copy of `url` there.
    static func plan(url: String, lastSavedAt: String?) async -> ChromeRemovalPlan? {
        guard let data = try? await BrowserFileReader.read(.chromeBookmarks) else { return nil }
        let entries = await Task.detached { BookmarkFileParse.chromium(data) }.value
        let plan = ChromeRemovalPlan.make(url: url, lastSavedAt: lastSavedAt, entries: entries)
        return plan.copies.isEmpty && plan.unreachable == 0 ? nil : plan
    }

    /// Delete `nodes` (the plan's target, or every copy when the person asked) — each only if Chrome's node still holds
    /// `url`. The URL rides as the script's argument, never in its source.
    static func remove(_ url: String, nodes: [BookmarkEntry], unreachable: Int = 0,
                       run: (String, String) async -> ChildProcess.Output = { script, url in
                           await ChildProcess.run(URL(fileURLWithPath: "/usr/bin/osascript"),
                                                  arguments: ["-e", script, url], timeout: 30)
                       }) async -> Outcome {
        if nodes.isEmpty { return unreachable > 0 ? .unreachable : .notInChrome }
        guard let script = ChromeBookmarkScript.delete(nodes) else { return .failed("no bookmark to address") }
        return outcome(await run(script, url))
    }

    /// osascript's answer: the number the script really deleted on stdout; -1743 is "not authorised".
    static func outcome(_ output: ChildProcess.Output) -> Outcome {
        if output.status == 0 && !output.timedOut {
            let deleted = Int(output.stdout.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0
            return deleted > 0 ? .removed(deleted) : .noneMatched
        }
        if output.stderr.contains("-1743") || output.stderr.contains("-1744")
            || output.stderr.localizedCaseInsensitiveContains("not authorized") {
            return .denied
        }
        if output.timedOut { return .failed("Chrome did not answer") }
        let line = output.stderr.split(separator: "\n").last.map(String.init)?
            .trimmingCharacters(in: .whitespaces) ?? ""
        return .failed(line.isEmpty ? "Chrome refused" : String(line.prefix(120)))
    }

    static func message(_ outcome: Outcome) -> String {
        switch outcome {
        case .removed(let n): return Copy.Bookmarks.removedFromChrome(n)
        case .notInChrome: return Copy.Bookmarks.removed
        case .noneMatched: return Copy.Bookmarks.chromeNoneMatched
        case .unreachable: return Copy.Bookmarks.chromeMobileOnly
        case .denied: return Copy.Bookmarks.chromeDenied
        case .failed(let why): return Copy.Bookmarks.chromeFailed(why)
        }
    }
}
