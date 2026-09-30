import XCTest
@testable import CicadaApp

/// G61 S3 (shadow) — an agent's report on an inbox question decodes leniently, reads in words, and changes nothing.
final class InboxCheckTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func item(checks: String) throws -> InboxItem {
        let json = """
        {"id":"inbox-010","kind":"conflict","requiredInput":"choice","status":"pending","title":"Where does Bob Example work now?",
         "question":"Where does Bob Example work now?","entityId":"bob-example","entityName":"Bob Example",
         "options":[{"key":"a","label":"company-a"},{"key":"b","label":"company-b"}],
         "createdDate":"2026-09-01","allowOther":true,"allowDefer":true\(checks.isEmpty ? "" : ",\"checks\":\(checks)")}
        """
        return try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    private let supports = #"{"at":"2026-10-02T09:00:00+00:00","checker":"claude-code","checkerKind":"agent","host":"team-labs.io","ref":"https://team-labs.io/staff","outcome":"supports","optionKey":"b","quote":"Bob Example joined company-b"}"#

    func testAnOlderBackendDecodesWithNoChecks() throws {
        XCTAssertEqual(try item(checks: "").checks, [])
    }

    func testAFindingDecodesAndAnUnreadableOneIsDroppedAlone() throws {
        let card = try item(checks: "[\(supports), {\"nonsense\": true}, 7]")
        XCTAssertEqual(card.checks.count, 1)
        XCTAssertEqual(card.checks[0].optionKey, "b")
        XCTAssertEqual(card.checks[0].quote, "Bob Example joined company-b")
        XCTAssertEqual(card.checks[0].host, "team-labs.io")
    }

    func testASupportsFindingReadsInWordsAndNamesTheOptionNeverTheHarness() throws {
        let card = try item(checks: "[\(supports)]")
        let line = try XCTUnwrap(InboxCheckWords.lines(card, locale: us).first)
        XCTAssertEqual(line.heading, "Your agent looked at team-labs.io · Oct 2")
        XCTAssertEqual(line.quote, "Bob Example joined company-b")
        XCTAssertEqual(line.result, "It points to “company-b”.")
        for text in [line.heading, line.result, Copy.Inbox.checkCaption] {
            XCTAssertFalse(text.lowercased().contains("claude"), "no provider or harness is named")
        }
    }

    func testEveryOutcomeHasItsOwnSentenceAndAConnectedAppIsNamedAsOne() throws {
        func result(_ outcome: String, extra: String = "") throws -> String {
            let f = #"{"at":"2026-10-02T09:00:00+00:00","checker":"x","checkerKind":"remote","host":"team-labs.io","outcome":"\#(outcome)"\#(extra)}"#
            return InboxCheckWords.lines(try item(checks: "[\(f)]"), locale: us)[0].result
        }
        XCTAssertEqual(try result("proposes", extra: #","proposedValue":"company-c""#), "It suggests another answer: “company-c”.")
        XCTAssertEqual(try result("proposes"), "It suggests another answer.")
        XCTAssertEqual(try result("contradicts_all"), "It doesn’t match any of these answers.")
        XCTAssertEqual(try result("unclear"), "It wasn’t clear.")
        XCTAssertEqual(try result("supports", extra: #","optionKey":"zz""#), "It points to one of these answers.")
        let f = #"{"at":"2026-10-02T09:00:00+00:00","checker":"x","checkerKind":"remote","host":"","outcome":"unclear"}"#
        XCTAssertEqual(InboxCheckWords.lines(try item(checks: "[\(f)]"), locale: us)[0].heading,
                       "An app you connected looked at a source · Oct 2")
    }

    func testAFindingChangesNothingAboutTheQuestion() throws {
        let with = try item(checks: "[\(supports)]")
        let without = try item(checks: "")
        XCTAssertEqual(with.options.map(\.key), without.options.map(\.key), "no option is added, removed or reordered")
        XCTAssertEqual(with.recommendedKey, without.recommendedKey, "nothing is recommended by a check")
        XCTAssertEqual(with.status, "pending")
        XCTAssertEqual(InboxCheckWords.lines(with, locale: us).count, 1)
    }

    func testTheCaptionNamesWhoReportedLikeTheHeadingDoes() throws {
        XCTAssertEqual(InboxCheckWords.caption(try item(checks: "[\(supports)]")),
                       "What your agent reported, not checked by Cicada. Nothing changed; you decide.")
        let remote = #"{"at":"2026-10-02T09:00:00+00:00","checker":"x","checkerKind":"remote","host":"h","outcome":"unclear"}"#
        XCTAssertEqual(InboxCheckWords.caption(try item(checks: "[\(remote)]")),
                       "What an app you connected reported, not checked by Cicada. Nothing changed; you decide.")
    }

    func testAtMostTwoAreShownNewestFirst() throws {
        func f(_ day: String, _ quote: String) -> String {
            #"{"at":"2026-10-0\#(day)T09:00:00+00:00","checker":"x","host":"team-labs.io","outcome":"unclear","quote":"\#(quote)"}"#
        }
        let card = try item(checks: "[\(f("1", "old")), \(f("3", "newest")), \(f("2", "middle"))]")
        XCTAssertEqual(InboxCheckWords.lines(card, locale: us).map(\.quote), ["newest", "middle"])
    }
}

final class ReadingSiteChecksTests: XCTestCase {
    func testASiteListedOnlyForQuestionsSaysSoInCountsAndNothingElse() throws {
        let json = #"{"site":"team-labs.io","label":"team-labs.io","wall":null,"allowed":false,"granted":false,"since":null,"waiting":0,"read":0,"needsLogin":0,"checks":3,"note":null,"iconHost":"team-labs.io"}"#
        let site = try JSONDecoder().decode(ReadingSite.self, from: Data(json.utf8))
        XCTAssertEqual(site.checks, 3)
        XCTAssertEqual(ReadingSiteWords.line(site), "3 questions could be checked here")
        var allowed = site
        allowed.allowed = true
        allowed.granted = true
        XCTAssertEqual(ReadingSiteWords.line(allowed), "3 questions your agent can check here")
    }

    func testAnOlderBackendHasNoChecksAndTheLineIsUnchanged() throws {
        let json = #"{"site":"x","label":"X","wall":"walled","allowed":true,"granted":true,"since":null,"waiting":2,"read":0,"needsLogin":0,"note":null,"iconHost":null}"#
        let site = try JSONDecoder().decode(ReadingSite.self, from: Data(json.utf8))
        XCTAssertEqual(site.checks, 0)
        XCTAssertNil(ReadingSiteWords.checkLine(site))
        XCTAssertTrue(ReadingSiteWords.line(site).hasPrefix("2 pages are queued for your agent"))
    }

    func testWaitingPagesAndQuestionsShareALine() {
        let site = ReadingSite(site: "x", label: "X", wall: "walled", allowed: true, waiting: 1, checks: 2)
        XCTAssertEqual(ReadingSiteWords.line(site), "1 page is queued for your agent · 2 questions your agent can check here · Cicada never asks this site for pages")
    }
}
