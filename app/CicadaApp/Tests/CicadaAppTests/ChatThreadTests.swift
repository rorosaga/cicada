import SwiftUI
import XCTest
@testable import CicadaApp

/// Owner 2026-11-23 — a chat's card opens what waits of it as ONE conversation (never a sitting at a time), under a
/// faded snippet of what Sleep already read and a dotted line; and a source that changed since Sleep read it shows
/// what was already read faded.
@MainActor
final class ChatThreadTests: XCTestCase {
    private typealias Line = ReaderChatTests.Line
    private let us = Locale(identifier: "en_US")
    private let utc = TimeZone(identifier: "UTC")!
    private let now = ISO8601DateFormatter().date(from: "2026-11-23T12:00:00Z")!

    private func item(_ id: String, chat: String, messages: Int = 1, processed: Bool = false,
                      at: String = "2026-11-23T10:00:00Z") throws -> EpisodeQueueItem {
        let json: [String: Any] = ["id": id, "timestamp": at, "source": "imessage", "origin": "imessage", "title": id,
                                   "preview": "", "processed": processed,
                                   "chat": ["id": chat, "name": "bob-example", "messages": messages]]
        return try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    private func sitting(_ episode: String, _ lines: [Line]) -> EpisodeText {
        ReaderChatTests.conversation(lines, episode: episode, title: "Messages with bob-example", timestamp: lines.first?.ts,
                                     origin: "imessage", conversationId: "imessage:0123456789abcdef:k1",
                                     correspondent: "bob-example")
    }

    private func words(_ rows: [ReaderChat.Row]) -> [String] {
        rows.compactMap {
            switch $0.kind {
            case let .message(m): m.block.text
            case let .day(label): "[\(label)]"
            case .boundary: "[line]"
            default: nil
            }
        }
    }

    private func layout(_ docs: [EpisodeText], before: EpisodeText? = nil, complete: Bool = true) -> ChatThread.Layout {
        ChatThread.layout(docs, before: before, complete: complete, now: now, locale: us, timeZone: utc)
    }

    // MARK: Where the card opens

    func testTheCardOpensItsWaitingSittingsOldestFirstWithTheOneReadJustBefore() throws {
        let entries = ChatGroups.entries([try item("s4", chat: "bob", messages: 5),
                                          try item("s3", chat: "bob", messages: 7),
                                          try item("s2", chat: "bob", processed: true),
                                          try item("s1", chat: "bob", processed: true)])
        guard case .chat(let group) = entries[0] else { return XCTFail("a chat") }
        let target = try XCTUnwrap(ChatThread.target(group, title: "bob-example"))
        let thread = try XCTUnwrap(target.thread)
        XCTAssertEqual(thread.sittings, ["s3", "s4"], "what waits, oldest first: one conversation")
        XCTAssertEqual(thread.before, "s2", "the sitting read just before, for the snippet above the line")
        XCTAssertEqual(thread.messages, 12)
        XCTAssertTrue(thread.waiting)
        XCTAssertEqual(target.episode, "s4")
        XCTAssertEqual(target.knownTitle, "bob-example")
        XCTAssertEqual(ChatThread.loadOrder(shown: thread.sittings, before: thread.before, hasEarlier: false),
                       ["s4", "s3", "s2"], "newest first — the end the chat opens on fills first — the snippet's sitting last")
    }

    /// Owner 2026-11-25: the chat opened from the Sleep queue sat at its oldest message with no way down. Every chat
    /// opens at the newest; the load order never depends on how much waits.
    func testALongWaitLoadsNewestFirstAndOnlyAsksForTheSnippetOnceNothingEarlierIsLeft() {
        let sittings = (1...40).map { "s\($0)" }
        let shown = ChatThread.shown(sittings, pages: 1, size: ChatThread.waitingPage)
        XCTAssertEqual(ChatThread.loadOrder(shown: shown, before: "s0", hasEarlier: true).first, "s40")
        XCTAssertFalse(ChatThread.loadOrder(shown: shown, before: "s0", hasEarlier: true).contains("s0"),
                       "earlier sittings are still to show: no snippet yet")
        XCTAssertEqual(ChatThread.loadOrder(shown: ["s1", "s2"], before: "s0", hasEarlier: false), ["s2", "s1", "s0"])
        XCTAssertEqual(ChatThread.loadOrder(shown: [], before: nil, hasEarlier: false), [])
    }

    func testAChatWithNothingWaitingOpensWholeOrAsItsOneDocument() throws {
        guard case .chat(let one) = ChatGroups.entries([try item("s1", chat: "bob", processed: true)])[0],
              case .chat(let two) = ChatGroups.entries([try item("s2", chat: "bob", processed: true),
                                                        try item("s1", chat: "bob", processed: true)])[0]
        else { return XCTFail("chats") }
        XCTAssertNil(ChatThread.target(one, title: "bob-example")?.thread, "one read sitting keeps the Reader's own view")
        let thread = try XCTUnwrap(ChatThread.target(two, title: "bob-example")?.thread)
        XCTAssertEqual(thread.sittings, ["s1", "s2"])
        XCTAssertFalse(thread.waiting)
        XCTAssertNil(thread.before)
        XCTAssertEqual(ChatThread.loadOrder(shown: thread.sittings, before: nil, hasEarlier: false), ["s2", "s1"])
        XCTAssertEqual(ChatThread.shown((1...40).map(String.init), pages: 1).count, ChatThread.page)
        XCTAssertTrue(ChatThread.hasEarlier((1...40).map(String.init), pages: 1))
    }

    // MARK: One conversation

    func testSittingsReadOnAsOneConversationWithTheDaySaidOnceWhereItChanges() {
        let morning = sitting("s1", [Line(marker: "user", text: "are we on for Friday?", ts: "2026-11-21T09:00:00+00:00"),
                                     Line(marker: "speaker:bob", text: "yes", ts: "2026-11-21T09:01:00+00:00")])
        let evening = sitting("s2", [Line(marker: "speaker:bob", text: "bring the map", ts: "2026-11-21T19:00:00+00:00")])
        let next = sitting("s3", [Line(marker: "user", text: "packed", ts: "2026-11-22T08:00:00+00:00")])
        let got = layout([morning, evening, next])
        XCTAssertEqual(got.sections.map(\.id), ["s1", "s2", "s3"])
        XCTAssertEqual(got.sections.flatMap { words($0.rows) },
                       ["[Saturday]", "are we on for Friday?", "yes", "bring the map", "[Yesterday]", "packed"],
                       "the same day is said once across two sittings")
        XCTAssertEqual(got.sections[1].rows.first?.gap, .newRun, "a later sitting starts apart, never glued on")
        XCTAssertEqual(got.sections[2].rows.first?.gap, .section)
        XCTAssertTrue(got.context.isEmpty, "nothing read before: no snippet and no line")
    }

    func testTheSnippetIsTheEndOfTheSittingReadBeforeAndWaitsForTheOldestOne() {
        let read = sitting("s0", (1...6).map { Line(marker: $0 % 2 == 0 ? "user" : "speaker:bob", text: "old \($0)",
                                                    ts: "2026-11-20T10:0\($0):00+00:00") })
        let waiting = sitting("s1", [Line(marker: "user", text: "new one", ts: "2026-11-21T09:00:00+00:00")])
        let got = layout([waiting], before: read)
        XCTAssertEqual(words(got.context), ["old 4", "old 5", "old 6"], "just a bit: the last three messages")
        XCTAssertEqual(got.contextDoc?.episode, "s0")
        XCTAssertEqual(got.context.first?.gap, ReaderChat.Gap.none)
        XCTAssertEqual(words(got.sections[0].rows), ["[Saturday]", "new one"])
        XCTAssertTrue(layout([waiting], before: read, complete: false).context.isEmpty,
                      "while earlier sittings are still to show, the line is not drawn in the wrong place")
    }

    func testASittingThatGrewStartsAtItsFirstNewMessageUnderWhatWasRead() {
        var grew = sitting("s1", [Line(marker: "user", text: "old question", ts: "2026-11-21T09:00:00+00:00"),
                                  Line(marker: "speaker:bob", text: "old answer", ts: "2026-11-21T09:01:00+00:00"),
                                  Line(marker: "user", text: "new question", ts: "2026-11-21T10:00:00+00:00"),
                                  Line(marker: "speaker:bob", text: "new answer", ts: "2026-11-21T10:01:00+00:00")])
        let start = grew.turns[2].start
        grew.changes = EpisodeChanges(state: "updated", changed: [[start, grew.text.unicodeScalars.count]])
        let other = sitting("s0", [Line(marker: "user", text: "far older", ts: "2026-11-19T09:00:00+00:00")])
        let got = layout([grew], before: other)
        XCTAssertEqual(words(got.context), ["old question", "old answer"], "its own read part, not another sitting's")
        XCTAssertEqual(got.contextDoc?.episode, "s1")
        XCTAssertEqual(words(got.sections[0].rows), ["[Saturday]", "new question", "new answer"],
                       "the day is said where the new messages start")
    }

    // MARK: The line in the Reader's own chat, and the fade

    func testAConversationThatWentOnGetsOneLineAboveItsFirstNewTurn() {
        let doc = ReaderChatTests.claudeCodeSession()
        let blocks = ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: nil, focusStyle: .focus,
                                         locale: us, timeZone: utc)
        let newFrom = ReaderChanges.firstTurn([doc.turns[5].start..<doc.text.unicodeScalars.count], blocks: blocks)
        XCTAssertEqual(newFrom, 6)
        let rows = ReaderChat.rows(blocks: blocks, doc: doc, newFrom: newFrom, now: now, locale: us, timeZone: utc)
        let at = try? XCTUnwrap(rows.firstIndex { $0.id == .boundary })
        XCTAssertEqual(rows.filter { $0.id == .boundary }.count, 1)
        XCTAssertEqual(at.flatMap { rows[$0 + 1].block?.index }, 6, "the line sits right above the first unread turn")
        XCTAssertEqual(at.map { rows[$0].gap }, .section)
        let whole = ReaderChat.rows(blocks: blocks, doc: doc, newFrom: 1, now: now, locale: us, timeZone: utc)
        XCTAssertFalse(whole.contains { $0.id == .boundary }, "a conversation Sleep never read has nothing above a line")
        XCTAssertNil(ReaderChanges.firstTurn([], blocks: blocks))
    }

    func testOnlyWordsSleepAlreadyReadStepBack() {
        let segments: [CitedSpan.Segment] = [.init(text: "read before ", mark: .plain),
                                             .init(text: "added since", mark: .changed),
                                             .init(text: " cited", mark: .current)]
        let faded = CitedSpan.fallback(segments, plain: .gray)
        let colours = faded.runs.map { $0.swiftUI.foregroundColor }
        XCTAssertEqual(colours, [.gray, nil, nil], "a changed or cited stretch keeps the passage's own ink")
        XCTAssertTrue(CitedSpan.fallback(segments).runs.allSatisfy { $0.swiftUI.foregroundColor == nil },
                      "nothing fades unless the source changed")
    }
}
