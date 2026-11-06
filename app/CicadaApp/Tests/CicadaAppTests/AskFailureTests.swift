import XCTest
@testable import CicadaApp

/// Ask says what happened and what to do (G148, 2026-11-06): the backend's failure answer decodes and is not an
/// answer to come back to; a request that failed shows a sentence, never a status code, a raw body or the system's words.
final class AskFailureTests: XCTestCase {
    private func decode(_ json: String) throws -> AskResponse {
        try JSONDecoder().decode(AskResponse.self, from: Data(json.utf8))
    }

    func testAFailureAnswerDecodesWithItsCodeAndReset() throws {
        let r = try decode(#"{"answer":"Your plan's week is used up. Ask again after Tue 14:00.","confidence":0,"failure":"plan_weekly","resetsAt":1790000000}"#)
        XCTAssertEqual(r.failure, "plan_weekly")
        XCTAssertEqual(r.resetsAt, 1_790_000_000)
        XCTAssertTrue(r.isEngineFailure)
    }

    func testAnOlderBackendAnswerHasNoFailure() throws {
        let r = try decode(#"{"answer":"alpha","confidence":0.8}"#)
        XCTAssertNil(r.failure)
        XCTAssertFalse(r.isEngineFailure)
    }

    func testAnUnreadableReplyStaysALowConfidenceAnswer() throws {
        let r = try decode(#"{"answer":"I retrieved related memory but could not synthesize a reliable answer.","confidence":0.15,"failure":"unreadable"}"#)
        XCTAssertFalse(r.isEngineFailure)
    }

    func testNoEngineIsAFailureToo() throws {
        XCTAssertTrue(try decode(#"{"answer":"x","confidence":0,"failure":"no_engine"}"#).isEngineFailure)
    }

    func testAMalformedFailureFieldNeverBlanksTheAnswer() throws {
        let r = try decode(#"{"answer":"x","confidence":0.5,"failure":7,"resetsAt":"soon"}"#)
        XCTAssertEqual(r.answer, "x")
        XCTAssertNil(r.failure)
    }

    func testATimeoutAndAnUnreachableBackendAreSentences() {
        XCTAssertEqual(AskViewModel.describe(URLError(.timedOut)), Copy.AskWords.timedOut)
        XCTAssertEqual(AskViewModel.describe(URLError(.cannotConnectToHost)), Copy.AskWords.unreachable)
        XCTAssertEqual(AskViewModel.describe(APIError.serverUnreachable), Copy.AskWords.unreachable)
        XCTAssertFalse(Copy.AskWords.timedOut.contains("The request"))
    }

    func testAServerErrorNeverShowsItsBody() {
        let said = AskViewModel.describe(APIError.httpError(500, "Traceback (most recent call last): ValueError at /Users/x"))
        XCTAssertEqual(said, Copy.AskWords.failed)
        XCTAssertFalse(said.contains("500"))
    }

    func testARefusalTheBackendWroteForThePersonIsShownAsWritten() {
        let body = #"{"detail":"Sleep is writing the pages. Ask again in a moment."}"#
        XCTAssertEqual(AskViewModel.describe(APIError.httpError(409, body)), "Sleep is writing the pages. Ask again in a moment.")
        XCTAssertEqual(AskViewModel.describe(APIError.httpError(409, "not json")), Copy.AskWords.failed)
    }

    func testAskWaitsLongerThanTheIdleDefault() {
        XCTAssertGreaterThan(APIClient.askTimeout, 300)
    }
}
