import XCTest
@testable import CicadaApp

/// G104 slice 3 (T4): a run's Corrections — the wire, the plain words, and Restore.
@MainActor
final class CorrectionsSectionTests: XCTestCase {
    private let withCorrections = """
    {"id":"run-a","state":"finished","corrections":{"conversationsRevised":2,"revised":["ep_a","ep_b"],
     "claimsWithdrawn":3,"claimsSuperseded":1,"passagesRewritten":4,
     "pagesArchived":[{"page":"alpha-page","episode":"ep_a","restorable":true},
                      {"page":"beta-page","episode":"ep_b","restorable":false}],
     "pagesKept":[{"page":"gamma-page","episode":"ep_a","support":"other_conversation"},
                  {"page":"delta-page","episode":"ep_a","support":"other_conversation"},
                  {"page":"eps-page","episode":"ep_b","support":"person_source"}],
     "aliasesDropped":2,"heldDropped":0,"questionsWithdrawn":1}}
    """

    private func detail(_ json: String) throws -> SleepRunDetail {
        try JSONDecoder().decode(SleepRunDetail.self, from: Data(json.utf8))
    }

    func test_theWireDecodesAndARunWithNoRevisionHasNone() throws {
        let c = try XCTUnwrap(try detail(withCorrections).corrections)
        XCTAssertEqual(c.conversationsRevised, 2)
        XCTAssertEqual([c.claimsWithdrawn, c.claimsSuperseded, c.passagesRewritten], [3, 1, 4])
        XCTAssertEqual(c.pagesArchived.map(\.page), ["alpha-page", "beta-page"])
        XCTAssertEqual(c.pagesArchived.map(\.restorable), [true, false])
        XCTAssertEqual(c.pagesKept.count, 3)
        XCTAssertNil(try detail(#"{"id":"r","corrections":null}"#).corrections)
        XCTAssertNil(try detail(#"{"id":"r"}"#).corrections)
        let fixture = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("fixtures/sleep-run-detail.json")
        XCTAssertNil(try JSONDecoder().decode(SleepRunDetail.self, from: Data(contentsOf: fixture)).corrections,
                     "the server's own run with no revision says null")
    }

    func test_theLinesSayEachNonZeroCountInPlainWords() throws {
        let c = try XCTUnwrap(try detail(withCorrections).corrections)
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(CorrectionsPresentation.lines(c, locale: en), [
            "2 conversations were edited after they were read.",
            "3 claims only the removed words supported were withdrawn",
            "1 claim replaced by what the edit now says",
            "4 passages rewritten",
            "2 aliases dropped",
            "1 question withdrawn",
        ])
        XCTAssertEqual(CorrectionsPresentation.archivedLine(c, locale: en),
                       "2 pages archived, because only the edited words supported them")
        XCTAssertEqual(CorrectionsPresentation.keptLine(c, locale: en),
                       "3 pages kept because something else supports them (another conversation, a source you added)")
    }

    /// G244 (ruling 76): a revised entry may name who edited its source; the plain id list still decodes.
    func test_aRevisedEntryNamesWhoEditedItsSourceWhenTheServerSaid() throws {
        let en = Locale(identifier: "en_US")
        let plain = try XCTUnwrap(try detail(withCorrections).corrections)
        XCTAssertEqual(plain.revised.map(\.episode), ["ep_a", "ep_b"])
        XCTAssertNil(CorrectionsPresentation.editedByLine(plain, locale: en), "an id list names nobody")

        let all = try XCTUnwrap(try detail(#"""
        {"id":"r","corrections":{"conversationsRevised":2,"revised":[{"episode":"ep_a","by":"claude-code"},{"episode":"ep_b","by":"claude-code"}]}}
        """#).corrections)
        XCTAssertEqual(all.revised.map(\.by), ["claude-code", "claude-code"])
        XCTAssertEqual(CorrectionsPresentation.editedByLine(all, locale: en), "Edited by Claude Code")

        let mixed = try XCTUnwrap(try detail(#"""
        {"id":"r","corrections":{"conversationsRevised":3,"revised":["ep_a",{"episode":"ep_b","by":"codex"},{"episode":"ep_c","by":"claude-code"},{"episode":"ep_d","by":"claude-code"}]}}
        """#).corrections)
        XCTAssertEqual(CorrectionsPresentation.editedByLine(mixed, locale: en), "2 edited by Claude Code, 1 edited by Codex")

        // The server's own shape: an id list plus `by: {episode id: harness}`.
        let served = try XCTUnwrap(try detail(#"""
        {"id":"r","corrections":{"conversationsRevised":2,"revised":["ep_a","ep_b"],"by":{"ep_b":"claude-code"}}}
        """#).corrections)
        XCTAssertEqual(served.revised.map(\.by), [nil, "claude-code"])
        XCTAssertEqual(CorrectionsPresentation.editedByLine(served, locale: en), "1 edited by Claude Code")
    }

    func test_anUnknownSupportIsNeverTheRawEnum() throws {
        let c = try XCTUnwrap(try detail(#"""
        {"id":"r","corrections":{"conversationsRevised":1,"pagesKept":[{"page":"p","episode":"e","support":"made_up_kind"}]}}
        """#).corrections)
        XCTAssertEqual(CorrectionsPresentation.keptLine(c, locale: Locale(identifier: "en_US")),
                       "1 page kept because something else supports it")
        XCTAssertNil(Copy.Corrections.supportWords("made_up_kind"))
    }

    func test_noStringNamesAProviderOrAModel() {
        let words = ["owner", "project", "media", "pinned", "contacts", "person_source", "import", "other_conversation",
                     "surviving_claim", "authored_commit", "waiting_conversation"].compactMap(Copy.Corrections.supportWords)
        XCTAssertEqual(words.count, 11, "every enum the server sends has a word")
        let all = (words + [Copy.Corrections.title, Copy.Corrections.restore, Copy.Corrections.restoreFailed,
                            Copy.Corrections.restoreHelp, Copy.Corrections.revised(2), Copy.Corrections.heldDropped(2)])
            .joined(separator: " ").lowercased()
        for banned in ["claude", "gpt", "openai", "anthropic", "gemini", "ollama", "llm", "model"] {
            XCTAssertFalse(all.contains(banned), banned)
        }
    }

    private func vm(fetchRun: @escaping (String) async throws -> SleepRunDetail,
                    restore: @escaping (String) async throws -> Void) -> SleepViewModel {
        let offline = URLError(.notConnectedToInternet)
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        return SleepViewModel(
            store: store, fetchSleepStatus: { throw offline }, requestCancel: { throw offline },
            fetchHistory: { throw offline }, fetchDetail: { _ in throw offline }, fetchEngine: { throw offline },
            putSchedule: { _ in throw offline }, requestEnd: { throw offline }, requestRetry: { _ in throw offline },
            fetchRunOptions: { throw offline }, putRunOptions: { _ in throw offline }, fetchQueue: { throw offline },
            fetchRun: fetchRun, restoreCorrection: restore, fetchEpisodes: { _ in throw offline },
            fetchSchedule: { throw offline })
    }

    func test_restoringAPageCallsTheRouteThenReadsTheRunAgain() async throws {
        var restored: [String] = []
        var fetches = 0
        let after = try detail(withCorrections.replacingOccurrences(
            of: #"{"page":"alpha-page","episode":"ep_a","restorable":true}"#,
            with: #"{"page":"alpha-page","episode":"ep_a","restorable":false}"#))
        let model = vm(fetchRun: { _ in fetches += 1; return after }, restore: { restored.append($0) })
        await model.restoreCorrectedPage("alpha-page", inRun: "run-a")
        XCTAssertEqual(restored, ["alpha-page"])
        XCTAssertEqual(fetches, 1)
        XCTAssertEqual(model.runDetails["run-a"]?.corrections?.pagesArchived.map(\.restorable), [false, false])
        XCTAssertTrue(model.restoringPages.isEmpty)
        XCTAssertTrue(model.restoreFailedPages.isEmpty)
    }

    func test_aRefusalIsNoFailureButAnUnreachableServerIs() async throws {
        let after = try detail(withCorrections)
        let refused = vm(fetchRun: { _ in after }, restore: { _ in throw APIError.httpError(409, "not archived by a correction") })
        await refused.restoreCorrectedPage("alpha-page", inRun: "run-a")
        XCTAssertTrue(refused.restoreFailedPages.isEmpty)
        XCTAssertNotNil(refused.runDetails["run-a"], "the refetch is the truth")

        let down = vm(fetchRun: { _ in after }, restore: { _ in throw URLError(.notConnectedToInternet) })
        await down.restoreCorrectedPage("alpha-page", inRun: "run-a")
        XCTAssertEqual(down.restoreFailedPages, ["alpha-page"])
        XCTAssertNil(down.runDetails["run-a"])
    }
}
