import XCTest
@testable import CicadaApp

/// Owner ruling 2026-10-16 — "Settled by a check": the wire decodes, undo is one tap with rollback, and a citation
/// becomes a tracked source only on the person's tap. Synthetic values only (example-film, tool-a).
@MainActor
final class FakeSettledChecksAPI: SettledChecksAPI {
    var rows: [SettledCheck] = []
    var failUndo = false
    var failTrack = false
    var failFetch = false
    private(set) var undone: [String] = []
    /// The bank each write named (`BankScope.origin`, G183(d)).
    private(set) var writeBanks: [String?] = []
    private(set) var trackedCalls: [(String, String, String?)] = []

    func fetchSettledChecks() async throws -> [SettledCheck] {
        if failFetch { throw APIError.serverUnreachable }
        return rows
    }

    func undoSettledCheck(id: String) async throws {
        writeBanks.append(BankScope.origin)
        if failUndo { throw APIError.serverUnreachable }
        undone.append(id)
        rows.removeAll { $0.id == id }
    }

    func trackCitation(entityId: String, ref: String, predicate: String?) async throws {
        writeBanks.append(BankScope.origin)
        if failTrack { throw APIError.serverUnreachable }
        trackedCalls.append((entityId, ref, predicate))
    }
}

@MainActor
final class SettledChecksTests: XCTestCase {
    private let film = SettledCheck(id: "inbox-101", entityId: "example-film", entityName: "Example Film",
                                    answer: "a 2019 film", ref: "https://films.film-example.net/example-film",
                                    host: "films.film-example.net", quote: "Example Film is a 2019 film.",
                                    settledAt: "2026-10-16T08:00:00+00:00", settledByKind: "sleep")
    private let repo = SettledCheck(id: "inbox-301", entityId: "beta-project", entityName: "Beta Project",
                                    answer: "merged", ref: "commit:abc1234", host: "git", scope: "repo")

    func testTheWireDecodesCamelCaseAndToleratesMissingFields() throws {
        let json = """
        [{"id": "inbox-101", "kind": "clarification", "entityId": "example-film", "entityName": "Example Film",
          "answer": "a 2019 film", "predicate": "description", "ref": "https://films.film-example.net/x",
          "host": "films.film-example.net", "quote": "q", "settledAt": "2026-10-16T08:00:00+00:00",
          "settledBy": "fake-model", "settledByKind": "sleep", "scope": "public", "claimId": "clm_x",
          "episode": "ep_2026-10-16_001", "held": false, "hasPage": true},
         {"id": "inbox-102"}]
        """
        let rows = try JSONDecoder().decode([SettledCheck].self, from: Data(json.utf8))
        XCTAssertEqual(rows.map(\.id), ["inbox-101", "inbox-102"])
        XCTAssertEqual(rows[0].predicate, "description")
        XCTAssertTrue(rows[0].canTrack)
        XCTAssertFalse(rows[1].canTrack, "no page: nothing to track a source on")
        XCTAssertEqual(rows[1].scope, "public")
    }

    func testARepoAnswerOffersNoTracking() {
        XCTAssertFalse(repo.canTrack, "a commit is no place to re-check")
    }

    func testUndoIsOneTapAndRefreshesTheInbox() async {
        let api = FakeSettledChecksAPI()
        api.rows = [film, repo]
        let model = SettledChecks(api: api)
        await model.load()
        var refreshed = 0
        await model.undo(film) { refreshed += 1 }
        XCTAssertEqual(api.undone, ["inbox-101"])
        XCTAssertEqual(model.rows.map(\.id), ["inbox-301"])
        XCTAssertEqual(refreshed, 1)
    }

    func testAFailedUndoPutsTheRowBackAndSaysSo() async {
        let api = FakeSettledChecksAPI()
        api.rows = [film, repo]
        api.failUndo = true
        let model = SettledChecks(api: api)
        await model.load()
        var refreshed = 0
        await model.undo(film) { refreshed += 1 }
        XCTAssertEqual(model.rows.map(\.id), ["inbox-101", "inbox-301"])
        XCTAssertEqual(model.message, Copy.Inbox.settledUndoFailed)
        XCTAssertEqual(refreshed, 0)
    }

    func testTrackingIsOnlyThePersonsTapAndUsesTheirAddSourceRoute() async {
        let api = FakeSettledChecksAPI()
        api.rows = [film]
        let model = SettledChecks(api: api)
        await model.load()
        XCTAssertTrue(api.trackedCalls.isEmpty, "loading the list tracks nothing")
        await model.track(film)
        XCTAssertEqual(api.trackedCalls.count, 1)
        XCTAssertEqual(api.trackedCalls[0].0, "example-film")
        XCTAssertEqual(api.trackedCalls[0].1, film.ref)
        XCTAssertTrue(model.tracked.contains("inbox-101"))
        await model.track(film)
        XCTAssertEqual(api.trackedCalls.count, 1, "a second tap does nothing")
        await model.track(repo)
        XCTAssertEqual(api.trackedCalls.count, 1, "a repo answer is never tracked")
    }

    func testAFailedReloadKeepsWhatWasShown() async {
        final class Flaky: SettledChecksAPI, @unchecked Sendable {
            var fail = false
            let row: SettledCheck
            init(row: SettledCheck) { self.row = row }
            func fetchSettledChecks() async throws -> [SettledCheck] {
                if fail { throw APIError.serverUnreachable }
                return [row]
            }
            func undoSettledCheck(id: String) async throws {}
            func trackCitation(entityId: String, ref: String, predicate: String?) async throws {}
        }
        let api = Flaky(row: film)
        let model = SettledChecks(api: api)
        await model.load()
        api.fail = true
        await model.load()
        XCTAssertEqual(model.rows.map(\.id), ["inbox-101"], "never blank (DR-43)")
    }

    /// Settled rows carry inbox ids, which repeat across memories (`inbox-101` in each): rows loaded in one memory are
    /// never shown — nor undone, nor tracked — in another.
    func testABankSwitchNeverShowsTheOtherMemorysRows() async {
        var bank = "alpha"
        let api = FakeSettledChecksAPI()
        api.rows = [film]
        let model = SettledChecks(api: api, bank: { bank })
        await model.load()
        await model.track(film)
        XCTAssertEqual(model.rows.map(\.id), ["inbox-101"])
        bank = "beta"
        api.failFetch = true
        await model.load()
        XCTAssertTrue(model.rows.isEmpty, "alpha's rows are not beta's, even when beta's read fails")
        XCTAssertTrue(model.tracked.isEmpty)
    }

    func testAnUndoOrTrackNamesTheMemoryItsRowCameFrom() async {
        var bank = "alpha"
        let api = FakeSettledChecksAPI()
        api.rows = [film, repo]
        let model = SettledChecks(api: api, bank: { bank })
        await model.load()
        bank = "beta"   // switched; the Inbox has not reloaded yet
        await model.track(film)
        await model.undo(film)
        XCTAssertEqual(api.writeBanks, ["alpha", "alpha"], "a stale row is refused by the server, never applied in beta")
    }
}
