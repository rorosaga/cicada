import SwiftUI
import XCTest
@testable import CicadaApp

/// 2026-11-24 (owner, DESIGN_RULES §9) — the one quiet line that says who asked a question and when. Pure: the words
/// are `InboxAskedLine`'s, so a test reads them without a view. The server half is `api/tests/test_question_origin.py`.
final class InboxAskedByTests: XCTestCase {
    private func item(_ extra: String = "", created: String = "2026-11-11") throws -> InboxItem {
        let json = #"{"id":"inbox-001","kind":"merge_suggestion","requiredInput":"merge","title":"Same person?","createdDate":"\#(created)"\#(extra)}"#
        return try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    private let today = ISODay(year: 2026, month: 11, day: 24)

    func testASleepStepIsNamedByWhatItDoesAndWhenItWasFirstAsked() throws {
        let asked = try item(#","askedBy":{"step":"duplicate_check","how":"rule","by":"Sleep's duplicate check"}"#)
        XCTAssertEqual(InboxAskedLine.text(asked, today: today), "Asked 13 days ago by Sleep's duplicate check")
        XCTAssertEqual(InboxAskedLine.text(try item(#","askedBy":{"how":"rule","by":"Sleep's decay check"}"#, created: "2026-11-23"),
                                           today: today), "Asked yesterday by Sleep's decay check")
        XCTAssertEqual(InboxAskedLine.text(try item(#","askedBy":{"how":"rule","by":"Sleep's decay check"}"#, created: "2026-11-24"),
                                           today: today), "Asked today by Sleep's decay check")
    }

    func testAnAgentIsTheHarnessTheRecordNamesOrJustAnAgent() throws {
        let named = try item(#","askedBy":{"how":"agent","by":"an agent","agent":"claude-code"}"#, created: "2026-11-03")
        XCTAssertEqual(InboxAskedLine.text(named, today: today), "Asked 3 weeks ago by Claude Code")
        for agent in [#","agent":null"#, #","agent":"mcp""#, #","agent":"unknown""#, ""] {
            let bare = try item(#","askedBy":{"how":"agent","by":"an agent"\#(agent)}"#)
            XCTAssertEqual(InboxAskedLine.text(bare, today: today), "Asked 13 days ago by an agent", agent)
        }
    }

    func testUnknownIsShownAsNothingNeverAGuess() throws {
        // No who: only when.
        XCTAssertEqual(InboxAskedLine.text(try item(), today: today), "Asked 13 days ago")
        XCTAssertEqual(InboxAskedLine.text(try item(#","askedBy":{}"#), today: today), "Asked 13 days ago")
        XCTAssertEqual(InboxAskedLine.text(try item(#","askedBy":{"how":"rule","by":"  "}"#), today: today), "Asked 13 days ago")
        // No day: nothing at all, even when who is known.
        XCTAssertNil(InboxAskedLine.text(try item(#","askedBy":{"by":"Sleep's decay check"}"#, created: ""), today: today))
        XCTAssertNil(InboxAskedLine.text(try item(created: "soon"), today: today))
        // A future day (clock skew) reads "today", never a negative age.
        XCTAssertEqual(InboxAskedLine.text(try item(created: "2026-12-01"), today: today), "Asked today")
    }

    func testAnOlderServerOrCacheDecodesWithNoAskedBy() throws {
        XCTAssertNil(try item().askedBy)
        // A field this build cannot read costs the field, never the card.
        let broken = try item(#","askedBy":"not an object""#)
        XCTAssertNil(broken.askedBy)
        // The snapshot cache round-trips it.
        let asked = try item(#","askedBy":{"step":"decay_check","how":"rule","by":"Sleep's decay check","agent":null}"#)
        let again = try JSONDecoder().decode(InboxItem.self, from: JSONEncoder().encode(asked))
        XCTAssertEqual(again.askedBy, InboxAskedBy(step: "decay_check", how: "rule", by: "Sleep's decay check"))
    }

    func testTheHoverSaysWhatKindOfAskerItWasAndTheFirstAskingInFull() throws {
        let asked = try item(#","askedBy":{"how":"rule","by":"Sleep's duplicate check"},"updatedDate":"2026-11-20""#)
        let help = try XCTUnwrap(InboxAskedLine.help(asked, locale: Locale(identifier: "en_US")))
        XCTAssertTrue(help.contains("No model read anything for it."), help)
        XCTAssertTrue(help.contains("Asked on Wednesday, November 11, 2026"), help)
        XCTAssertTrue(help.contains("Seen again on Friday, November 20, 2026"), help)
        // Seen again the same day it was first asked adds nothing.
        let same = try item(#","askedBy":{"how":"model","by":"Sleep's read of a conversation"},"updatedDate":"2026-11-11""#)
        let sameHelp = try XCTUnwrap(InboxAskedLine.help(same, locale: Locale(identifier: "en_US")))
        XCTAssertFalse(sameHelp.contains("Seen again"), sameHelp)
        XCTAssertTrue(sameHelp.contains("A model read a conversation"), sameHelp)
        XCTAssertNil(InboxAskedLine.help(try item(created: ""), locale: Locale(identifier: "en_US")))
    }

    /// Every `how` the server can send (`question_origin.HOWS`) has a sentence, and none of the words names a provider
    /// or a model (CLAUDE.md, "Copy is provider-neutral"): a model's name stays where provenance already shows it.
    func testEveryHowHasWordsAndNoWordNamesAProviderOrAModel() throws {
        let banned = ["claude", "anthropic", "openai", "gpt", "gemini", "haiku", "sonnet", "opus", "codex", "ollama"]
        for how in ["rule", "model", "agent", "check"] {
            let words = try XCTUnwrap(Copy.Inbox.AskedBy.how(how), how).lowercased()
            XCTAssertFalse(banned.contains { words.contains($0) }, words)
        }
        XCTAssertNil(Copy.Inbox.AskedBy.how(nil))
        XCTAssertNil(Copy.Inbox.AskedBy.how("a-step-from-a-newer-server"))
    }

    func testHomesLeadQuestionCarriesTheLineAndItsHover() throws {
        let asked = try item(#","askedBy":{"how":"rule","by":"Sleep's duplicate check"},"entityId":"alpha","entityName":"Alpha","mergeTargetHint":"beta""#)
        let now = Date(timeIntervalSince1970: 1_795_000_000)   // 2026-11-18 in every zone
        let figures = HomeQuestions.figures([asked], now: now)
        XCTAssertEqual(figures.rows.first?.asked, InboxAskedLine.text(asked, today: .today(now: now)))
        XCTAssertEqual(figures.rows.first?.askedHelp, InboxAskedLine.help(asked))
        // No day, no line: the row carries nothing for the card to draw.
        let undated = try item(#","askedBy":{"how":"rule","by":"Sleep's duplicate check"},"entityId":"alpha","entityName":"Alpha","mergeTargetHint":"beta""#, created: "")
        XCTAssertNil(HomeQuestions.figures([undated], now: now).rows.first?.asked)
    }

    /// Owner 2026-11-25: the line a bubble or a lead card draws on its own wraps, never truncates, and never wants more
    /// width than it is given, at a narrow and a wide column, at both zooms, in both themes.
    @MainActor
    func testTheLineOnItsOwnWrapsAndFitsEveryWidthInBothThemes() throws {
        let words = "Asked 13 days ago by Sleep's check for people with no name, the longest step there is"
        defer { CicadaTheme.uiScale = 1.0; CicadaTheme.mode = .dark }
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for scale in [1.0, 1.4] {
                CicadaTheme.uiScale = scale
                var heights: [CGFloat] = []
                for width: CGFloat in [260, 720] {
                    let proposed = width * CGFloat(scale)
                    let renderer = ImageRenderer(content: AskedByText(text: words, wraps: true))
                    renderer.proposedSize = ProposedViewSize(width: proposed, height: nil)
                    let size = try XCTUnwrap(renderer.nsImage).size
                    XCTAssertLessThanOrEqual(size.width, proposed + 0.5)
                    heights.append(size.height)
                }
                XCTAssertGreaterThan(heights[0], heights[1], "narrow wraps to more lines instead of truncating")
            }
        }
    }
}
