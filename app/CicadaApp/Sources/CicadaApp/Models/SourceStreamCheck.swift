import Foundation
import Observation

// G245 (plan 3.3) — **Check now** (a source's page) and **Check connections** (the root). Every stream that is on ends
// a check in one definite word and a time:
//   Read · Signed out · Couldn't read · Needs access · Your AI app reads it next · Not installed.
//
// Who answers depends on how the stream is read:
// - `how: app` — this app runs that reader now, for the readers that already have a run-now (`ChannelActions.sync`'s
//   routes); a missing permission is said with its fix and nothing is run (never a prompt).
// - `how: click` — nothing runs: noticing saves is the per-Mac flag plus Accessibility, so the word is the overlay's.
// - `how: account` / `how: browser` — the backend's part, one `POST /sources/streams/check` for every source that has
//   one. An account's own check answers read, signed out or couldn't read. A browser list cannot be opened by Cicada
//   (G166): the backend stamps the request and the row says "Your AI app reads it next", with the last result beside it.
//   A check **never lifts a pause**: a signed-out list keeps saying so.
//
// A stream that is off or unavailable is not checked: nothing is read from it, so it has no word to give — except an
// app removed from this Mac, which says Not installed.

@Observable
@MainActor
final class SourceStreamCheckModel {
    struct Result: Equatable, Sendable {
        let streamId: String
        let word: StreamWord
        let at: Date
        /// For "Your AI app reads it next": how the list read before this check was asked, to show beside it.
        let previous: StreamWord?
    }

    struct Deps {
        var now: @MainActor () -> Date = { Date() }
        /// Runs one app reader now by its channel id (`ChannelActions.sync`); throws when it could not read.
        var runReader: @MainActor (String) async throws -> String
        /// `POST /sources/streams/check` (`APIClient.checkSourceStreams`); empty asks for every source.
        var askBackend: @MainActor ([String]) async throws -> SourceStreamsResponse

        @MainActor static func live(runReader: @escaping @MainActor (String) async throws -> String) -> Deps {
            Deps(runReader: runReader, askBackend: { try await APIClient.shared.checkSourceStreams(sources: $0) })
        }
    }

    private(set) var results: [String: Result] = [:]
    /// Stream ids whose reader is running or whose answer is awaited.
    private(set) var checking: Set<String> = []
    private(set) var isChecking = false
    /// The backend could not be asked (older backend, no network): said once, with the app's own results still kept.
    private(set) var failure: String?
    private(set) var lastCheckedAt: Date?
    @ObservationIgnored private let deps: Deps
    @ObservationIgnored private var epoch = 0

    init(deps: Deps) { self.deps = deps }

    func result(_ streamId: String) -> Result? { results[streamId] }

    /// Forget every result — a bank switch.
    func reset() {
        epoch &+= 1
        results = [:]
        checking = []
        isChecking = false
        failure = nil
        lastCheckedAt = nil
    }

    /// Check `sources` (catalogue ids; empty is every source `current` holds). `resolve` turns the backend's own answer
    /// into resolved streams with the app's overlay on it (the page supplies its live app state); `publish` hands that
    /// answer to the streams cache, so the page redraws from it.
    func check(sources: [String], current: ResolvedStreams, resolve: (SourceStreamsResponse) -> ResolvedStreams,
               publish: (SourceStreamsResponse) -> Void) async {
        guard !isChecking else { return }
        let started = epoch
        isChecking = true
        failure = nil
        defer { if started == epoch { isChecking = false } }

        let ids = sources.isEmpty ? Array(current.sources.keys).sorted() : sources
        let targets = ids.flatMap { current.streams($0) }
        var backend: [ResolvedStream] = []
        var readers: [ResolvedStream] = []
        for target in targets {
            let stream = target.stream
            if stream.state == .unavailable, target.word == .notInstalled {
                record(target, word: .notInstalled)
            } else if stream.state != .on {
                continue
            } else if stream.how == .click || (stream.owner == .app && target.reader == nil) {
                // Nothing to run: the overlay's own word (the flag, the permission) is the answer.
                if target.word.isCheckWord { record(target, word: target.word) }
            } else if target.word == .needsAccess || target.word == .notInstalled {
                record(target, word: target.word)
            } else if stream.owner == .app || stream.how == .app, target.reader != nil {
                readers.append(target)
            } else {
                backend.append(target)
            }
        }
        checking = Set((readers + backend).map(\.id))

        // The backend's part goes out first and is awaited last, so a slow reader never holds it back.
        let askedSources = Array(Set(backend.map(\.source))).sorted()
        let asked: Task<SourceStreamsResponse?, Never>? = askedSources.isEmpty ? nil : Task { @MainActor in
            do { return try await self.deps.askBackend(askedSources) } catch { return nil }
        }

        for target in readers {
            guard let channel = target.reader else { continue }
            do {
                _ = try await deps.runReader(channel)
                guard started == epoch else { return }
                record(target, word: .read)
            } catch {
                guard started == epoch else { return }
                // A stop the person made is no result; any other failure is a read that did not happen.
                if SyncCancellation.isCancellation(error) { checking.remove(target.id); continue }
                record(target, word: .couldntRead)
            }
        }

        if let asked {
            let answer = await asked.value
            guard started == epoch else { return }
            if let answer {
                publish(answer)
                let fresh = resolve(answer)
                for target in backend {
                    guard let now = fresh.stream(target.id) else { checking.remove(target.id); continue }
                    record(now, word: Self.backendWord(now), previous: Self.previous(now))
                }
            } else {
                failure = Copy.Streams.checkFailed
                for target in backend { checking.remove(target.id) }
            }
        }
        lastCheckedAt = deps.now()
    }

    private func record(_ target: ResolvedStream, word: StreamWord, previous: StreamWord? = nil) {
        results[target.id] = Result(streamId: target.id, word: word, at: deps.now(), previous: previous)
        checking.remove(target.id)
    }

    /// What a stream the backend checked ends in: its own word when that is one of the six, else the nearest honest one.
    /// A browser list is asked of the person's AI app; an account the service did not confirm is a read that did not
    /// happen. Never a word that lifts a pause.
    static func backendWord(_ resolved: ResolvedStream) -> StreamWord {
        let word = resolved.word
        if word.isCheckWord { return word }
        // A pause is never lifted by asking: it stays a read that did not happen.
        if word == .paused { return .couldntRead }
        return resolved.stream.how == .browser ? .yourAIAppReadsNext : .couldntRead
    }

    /// How a browser list read before the check was asked: its resting word with the request set aside.
    static func previous(_ resolved: ResolvedStream) -> StreamWord? {
        guard resolved.stream.how == .browser, resolved.stream.checkRequestedAt != nil else { return nil }
        var before = resolved.stream
        before.checkRequestedAt = nil
        let word = StreamWord.resting(before)
        return word == .read || word == .couldntRead || word == .signedOut ? word : nil
    }
}
