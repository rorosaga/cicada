import SwiftUI
import XCTest
@testable import CicadaApp

/// The Reader's chat layout (owner, 2026-10-19): which documents are chats, the rows (sides, runs, day separators,
/// folding, Cicada's gap note), the keys, the speed on a long conversation, and that nothing outgrows the column.
/// Every conversation here is synthetic.
@MainActor
final class ReaderChatTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!
    private let gb = Locale(identifier: "en_GB")
    private let us = Locale(identifier: "en_US")
    /// 2026-10-19 15:00 UTC, a Monday.
    private let now = ISO8601DateFormatter().date(from: "2026-10-19T15:00:00Z")!

    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    // MARK: Fixtures

    /// One line of a synthetic conversation: the marker as written, the words, the stored time.
    struct Line {
        let marker: String?
        let text: String
        var ts: String? = nil
        var model: String? = nil
    }

    /// Builds the episode text and the turns `evidence.turns` would return for it: one block per line, offsets in
    /// scalars, `contentStart` past "marker: ".
    static func conversation(_ lines: [Line], episode: String = "ep_2026-10-19_001", title: String = "A conversation",
                             timestamp: String? = "2026-10-19T09:00:00+00:00", harness: String? = nil,
                             origin: String? = nil, conversationId: String? = nil, captureKind: String? = nil,
                             correspondent: String? = nil, focus: EpisodeFocus? = nil,
                             truncated: Bool = false, agent: EpisodeAgent? = nil, forcedRole: String? = nil,
                             relay: EpisodeRelay? = nil) -> EpisodeText {
        var text = ""
        var turns: [EpisodeTurn] = []
        for (i, line) in lines.enumerated() {
            if i > 0 { text += "\n" }
            let start = text.unicodeScalars.count
            let prefix = line.marker.map { "\($0): " } ?? ""
            text += prefix + line.text
            let role: String
            switch line.marker {
            case "user": role = "user"
            case "assistant": role = "assistant"
            case let m? where m.hasPrefix("speaker:"): role = "speaker"
            case nil where line.text.hasPrefix("[Cicada: "): role = "gap"
            default: role = "user"
            }
            // `evidence.turns`: a declared `evidence_kind` forces every turn's role; the marker stays as written.
            turns.append(EpisodeTurn(index: i + 1, start: start, contentStart: start + prefix.unicodeScalars.count,
                                     end: text.unicodeScalars.count, role: role == "gap" ? role : (forcedRole ?? role),
                                     marker: role == "gap" ? "gap" : line.marker, ts: line.ts, model: line.model))
        }
        var doc = EpisodeText(episode: episode, text: text, truncated: truncated, title: title, timestamp: timestamp,
                              harness: harness, origin: origin, conversationId: conversationId,
                              captureKind: captureKind, turns: turns, focus: focus, agent: agent,
                              correspondent: correspondent)
        doc.relay = relay
        return doc
    }

    /// A Messages sitting over two days: the person and a contact, short messages in runs.
    static func messagesSitting() -> EpisodeText {
        conversation([
            Line(marker: "speaker:sam", text: "Are we still on for the trail this weekend?", ts: "2026-10-18T17:02:00+00:00"),
            Line(marker: "speaker:sam", text: "I can bring the small stove.", ts: "2026-10-18T17:03:00+00:00"),
            Line(marker: "user", text: "Yes! Saturday morning works.", ts: "2026-10-18T17:20:00+00:00"),
            Line(marker: "user", text: "I'll pack the map and the water filter.", ts: "2026-10-18T17:21:00+00:00"),
            Line(marker: "speaker:sam", text: "Perfect. 7:30 at the north lot?", ts: "2026-10-19T08:10:00+00:00"),
            Line(marker: "user", text: "See you there.", ts: "2026-10-19T08:41:00+00:00"),
        ], title: "Messages with Sam · 2026-10-18", timestamp: "2026-10-18T17:02:00+00:00", origin: "imessage",
           conversationId: "imessage:0123456789abcdef:k1", correspondent: "Sam")
    }

    /// A Claude Code session: the person's turns and each final reply, a model per reply, one long reply.
    static func claudeCodeSession(focus: EpisodeFocus? = nil) -> EpisodeText {
        let long = (1...14).map { "Step \($0): moved the index for alpha-project to sqlite-vec and re-ran the bench." }
            .joined(separator: "\n")
        return conversation([
            Line(marker: "user", text: "can we switch the vector index to sqlite-vec?", ts: "2026-10-19T09:00:00+00:00"),
            Line(marker: "assistant", text: "Yes. I'll move the index and keep the old table until the new one commits.",
                 ts: "2026-10-19T09:02:00+00:00", model: "claude-opus-5-5"),
            Line(marker: "user", text: "go ahead, and measure it", ts: "2026-10-19T09:05:00+00:00"),
            Line(marker: "assistant", text: long, ts: "2026-10-19T09:31:00+00:00", model: "claude-opus-5-5"),
            Line(marker: nil, text: "[Cicada: 40 turns from 2026-10-19T09:40:00Z to 2026-10-19T11:10:00Z were not kept]"),
            Line(marker: "user", text: "ship it", ts: "2026-10-19T11:12:00+00:00"),
            Line(marker: "assistant", text: "Done — the PR is open against dev.", ts: "2026-10-19T11:14:00+00:00",
                 model: "claude-opus-5-5"),
        ], title: "Index switch", harness: "claude-code", origin: "claude-code", conversationId: "ses_alpha",
           captureKind: "transcript", focus: focus, agent: EpisodeAgent(model: "claude-opus-5-5"))
    }

    /// A chat export with one very long reply (47k characters).
    static func exportWithLongReply() -> EpisodeText {
        let paragraph = "The plan has three parts: the reading list, the schedule, and the notes you keep as you go. "
        let reply = String(repeating: paragraph, count: 500)
        return conversation([
            Line(marker: "user", text: "Can you write me a full study plan?", ts: "2025-03-02T10:00:00+00:00"),
            Line(marker: "assistant", text: reply, ts: "2025-03-02T10:01:00+00:00"),
            Line(marker: "user", text: "Thanks — shorter version?", ts: "2025-03-02T10:05:00+00:00"),
            Line(marker: "assistant", text: "Read one chapter a day, write three lines after each.",
                 ts: "2025-03-02T10:06:00+00:00"),
        ], episode: "ep_2025-03-02_004", title: "Study plan", timestamp: "2025-03-02T10:00:00+00:00",
           origin: "chatgpt-export", conversationId: "conv-1")
    }

    private func rows(_ doc: EpisodeText, focus: Range<Int>? = nil, expanded: Set<Int> = [],
                      keepOpen: Set<Int> = []) -> (blocks: [ReaderBlock], rows: [ReaderChat.Row]) {
        let blocks = ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: focus, focusStyle: .focus,
                                         locale: gb, timeZone: utc)
        return (blocks, ReaderChat.rows(blocks: blocks, doc: doc, expanded: expanded, keepOpen: keepOpen, now: now,
                                        locale: us, timeZone: utc))
    }

    /// A clock time as the Reader prints it here (ICU decides whether an hour under ten is padded).
    private func clock(_ ts: String) -> String? { ReaderTime.label(ts, locale: gb, timeZone: utc) }

    private func messages(_ rows: [ReaderChat.Row]) -> [ReaderChat.Message] {
        rows.compactMap { if case let .message(m) = $0.kind { m } else { nil } }
    }

    private func days(_ rows: [ReaderChat.Row]) -> [String] {
        rows.compactMap { if case let .day(d) = $0.kind { d } else { nil } }
    }

    // MARK: Which documents are chats

    func testConversationsAreChatsAndEverythingElseKeepsTheDocumentView() {
        XCTAssertTrue(ReaderChat.isChat(Self.messagesSitting()))
        XCTAssertTrue(ReaderChat.isChat(Self.claudeCodeSession()))
        XCTAssertTrue(ReaderChat.isChat(Self.exportWithLongReply()))
        // The person's own written turns alone are still a conversation (a session whose replies were not kept).
        XCTAssertTrue(ReaderChat.isChat(Self.conversation([Line(marker: "user", text: "hello")])))
        // A note with no marker, a saved page, a feed item and a watch record are documents.
        XCTAssertFalse(ReaderChat.isChat(Self.conversation([Line(marker: nil, text: "Saved: a link about tents")])))
        XCTAssertFalse(ReaderChat.isChat(EpisodeText(episode: "alpha-project", kind: "page", text: "A page.",
                                                     turns: [EpisodeTurn(index: 1, start: 0, contentStart: 0, end: 7,
                                                                         role: "page")])))
        XCTAssertFalse(ReaderChat.isChat(Self.conversation([Line(marker: "user", text: "a headline")], origin: "rss")))
        var watch = Self.conversation([Line(marker: "user", text: "watched")])
        watch = EpisodeText(episode: watch.episode, text: watch.text, turns: watch.turns, watch: EpisodeWatch())
        XCTAssertFalse(ReaderChat.isChat(watch))
    }

    func testAMessagesSittingNamesItsChatForThePicture() {
        XCTAssertEqual(ReaderChat.messagesChat(Self.messagesSitting()), "0123456789abcdef")
        XCTAssertNil(ReaderChat.messagesChat(Self.claudeCodeSession()))
    }

    // MARK: Rows

    func testThePersonIsOnTheRightAndNoRowSaysTurn() {
        let (_, out) = rows(Self.messagesSitting())
        let sides = messages(out).map(\.side)
        XCTAssertEqual(sides, [.other, .other, .person, .person, .other, .person])
        for row in out {
            if case let .message(m) = row.kind {
                XCTAssertFalse((m.header?.name ?? "").contains("turn"))
                XCTAssertFalse((m.header?.time ?? "").contains("turn"))
            }
        }
    }

    func testDaySeparatorsReplaceADateOnEveryTurn() {
        let (_, out) = rows(Self.messagesSitting())
        XCTAssertEqual(days(out), ["Yesterday", "Today"])
        guard case .day = out.first?.kind else { return XCTFail("the history opens on its day") }
        // A conversation with no stored turn times shows its own day once.
        let plain = Self.conversation([Line(marker: "user", text: "hi"), Line(marker: "assistant", text: "hello")],
                                      timestamp: "2026-10-12T08:00:00+00:00", harness: "claude-code")
        XCTAssertEqual(days(rows(plain).rows), ["Mon, Oct 12"])
    }

    func testARunShowsItsFaceNameAndTimeOnceAndTheNameOnlyWhenItChanges() {
        let out = messages(rows(Self.messagesSitting()).rows)
        // Sam's first run: the face and the time — the title already names Sam (DR-38); the run's second message:
        // nothing above it.
        XCTAssertEqual(out[0].header, ReaderChat.Header(avatar: .face("Sam"), name: nil, time: clock("2026-10-18T17:02:00+00:00")))
        XCTAssertNil(out[1].header)
        // The person's run: the time alone, once.
        XCTAssertEqual(out[2].header, ReaderChat.Header(avatar: .none, name: nil, time: clock("2026-10-18T17:20:00+00:00")))
        XCTAssertNil(out[3].header)
        // Sam again, the next day: the face and the time.
        XCTAssertEqual(out[4].header, ReaderChat.Header(avatar: .face("Sam"), name: nil, time: clock("2026-10-19T08:10:00+00:00")))
    }

    func testMessagesFarApartStartANewRun() {
        let doc = Self.conversation([
            Line(marker: "user", text: "one", ts: "2026-10-19T08:00:00+00:00"),
            Line(marker: "user", text: "two", ts: "2026-10-19T08:10:00+00:00"),
            Line(marker: "user", text: "three", ts: "2026-10-19T09:00:00+00:00"),
        ])
        let out = rows(doc).rows.filter { if case .message = $0.kind { true } else { false } }
        XCTAssertEqual(out.map(\.gap), [.newRun, .inRun, .newRun], "under its day, a run, the same run, a new one")
        XCTAssertEqual(messages(out).map { $0.header?.time }, [clock("2026-10-19T08:00:00+00:00"), nil, clock("2026-10-19T09:00:00+00:00")])
    }

    func testAnAgentWearsItsMarkAndIsNamedOnlyWhereTheHeaderDoesNot() {
        let out = messages(rows(Self.claudeCodeSession()).rows)
        let agent = out.filter { $0.side == .other && $0.header != nil }
        XCTAssertEqual(agent.first?.header?.avatar, .mark("claude-code"))
        XCTAssertTrue(agent.allSatisfy { $0.header?.name == nil }, "the meta line names Claude Code · Opus 5.5")
        XCTAssertTrue(agent.allSatisfy { $0.header?.time != nil })
        // A reply from another model than the one the header names says so.
        let mixed = Self.conversation([Line(marker: "user", text: "hi"),
                                       Line(marker: "assistant", text: "hello", model: "claude-sonnet-5"),
                                       Line(marker: "user", text: "again"),
                                       Line(marker: "assistant", text: "hi again", model: "claude-opus-5-5")],
                                      harness: "claude-code", origin: "claude-code",
                                      agent: EpisodeAgent(model: "claude-opus-5-5"))
        let names = messages(rows(mixed).rows).filter { $0.side == .other }.map { $0.header?.name }
        XCTAssertNotNil(names[0])
        XCTAssertEqual(names[1], ReaderChat.namedParty(mixed), "back to another model: named again")
    }

    // MARK: Relayed conversations (ruling 32)

    func testARelayedConversationIsSidedByItsWrittenMarkersAndThePersonIsNeverYou() {
        let doc = Self.conversation([
            Line(marker: "user", text: "Help me plan the launch.", ts: "2026-10-19T09:00:00+00:00"),
            Line(marker: "assistant", text: "Here is a checklist.", ts: "2026-10-19T09:01:00+00:00"),
            Line(marker: "user", text: "Add a rollback step.", ts: "2026-10-19T09:02:00+00:00"),
        ], harness: "chatgpt", origin: "chatgpt", captureKind: "transcript", forcedRole: "assistant",
           relay: EpisodeRelay(app: "chatgpt", label: "ChatGPT"))
        XCTAssertEqual(doc.turns.map(\.role), ["assistant", "assistant", "assistant"], "the fixture forces the roles")
        XCTAssertTrue(ReaderChat.isChat(doc))
        let out = messages(rows(doc).rows)
        XCTAssertEqual(out.map(\.side), [.person, .other, .person], "the marker says who spoke, not the forced role")
        XCTAssertEqual(out[0].header?.name, "Relayed by ChatGPT")
        XCTAssertNil(out[2].header?.name, "said once")
        XCTAssertTrue(out.allSatisfy { $0.speaker != Copy.you })
        XCTAssertEqual(out[2].speaker, "Relayed by ChatGPT", "VoiceOver says it too")
        XCTAssertEqual(out[1].header?.avatar, .mark("chatgpt"))
        // Each change of marker is a new run.
        XCTAssertEqual(rows(doc).rows.filter { if case .message = $0.kind { true } else { false } }.map(\.gap),
                       [.newRun, .newRun, .newRun])
        // The header never says "Your words…", and names the app once — on the person's run, not in the meta.
        XCTAssertEqual(ReaderHeader.captureLine(doc), Copy.Provenance.relayHonesty)
        XCTAssertFalse(ReaderHeader.captureLine(doc)?.contains("Your words") ?? true)
        XCTAssertFalse(ReaderHeader.meta(doc).contains("ChatGPT"))
    }

    func testAMarkerlessDocumentWithAForcedRoleIsNotAChat() {
        // An agent-written folder file, a memory export entry: `evidence_kind: assistant`, no turn markers.
        let note = Self.conversation([Line(marker: nil, text: "The person prefers mornings for deep work.")],
                                     forcedRole: "assistant")
        XCTAssertEqual(note.turns.first?.role, "assistant")
        XCTAssertFalse(ReaderChat.isChat(note))
        let attached = Self.conversation([Line(marker: "attachment [plan.pdf]", text: "> page one")],
                                         forcedRole: "assistant")
        XCTAssertFalse(ReaderChat.isChat(attached), "an attachment alone is a document")
    }

    func testCicadasGapNoteIsAQuietRowNotAMessage() {
        let out = rows(Self.claudeCodeSession()).rows
        let gaps = out.compactMap { if case let .gap(_, words) = $0.kind { words } else { nil } }
        let at = { (ts: String) in ReaderTime.label(ts, locale: self.us, timeZone: self.utc) ?? "" }
        XCTAssertEqual(gaps, ["40 turns from \(at("2026-10-19T09:40:00Z")) to \(at("2026-10-19T11:10:00Z")) were not kept"])
        XCTAssertEqual(ReaderChat.gapWords("[Cicada: part of this reply was not kept]"), "Part of this reply was not kept")
    }

    // MARK: Folding

    func testALongReplyFoldsBehindShowMore() throws {
        let doc = Self.exportWithLongReply()
        let (blocks, out) = rows(doc)
        XCTAssertGreaterThan(blocks.filter { $0.index == 2 }.count, 10, "a 47k reply is many blocks")
        let reply = try XCTUnwrap(messages(out).first { $0.block.index == 2 })
        XCTAssertTrue(reply.folded)
        XCTAssertLessThanOrEqual(reply.block.text.unicodeScalars.count, ReaderChat.previewScalars + 1)
        XCTAssertTrue(reply.block.text.hasSuffix("…"))
        XCTAssertEqual(messages(out).filter { $0.block.index == 2 }.count, 1, "one preview, not every block")
        XCTAssertTrue(out.contains { $0.kind == .toggle(turn: 2, side: .other, expanded: false) })

        let open = rows(doc, expanded: [2]).rows
        let pieces = messages(open).filter { $0.block.index == 2 }
        XCTAssertEqual(pieces.count, blocks.filter { $0.index == 2 }.count)
        XCTAssertEqual(pieces.first?.piece, .first)
        XCTAssertEqual(pieces.last?.piece, .last)
        XCTAssertTrue(open.contains { $0.kind == .toggle(turn: 2, side: .other, expanded: true) })
    }

    func testTooManyLinesFoldsAtALineBreakWithNoEllipsis() throws {
        let out = messages(rows(Self.claudeCodeSession()).rows)
        let long = try XCTUnwrap(out.first { $0.block.index == 4 })
        XCTAssertTrue(long.folded)
        XCTAssertEqual(long.block.text.components(separatedBy: "\n").count, ReaderChat.previewLines)
        XCTAssertTrue(long.block.text.hasSuffix("bench."), "a whole line ends as written: \(long.block.text.suffix(12))")
    }

    func testAMidLineCutDropsItsTrailingPunctuationBeforeTheEllipsis() throws {
        // Sentences of 40 scalars: the back half of the 480 window holds spaces, and the one the cut lands on
        // follows a full stop — the preview must end "…", never ".…".
        let sentence = "Read one chapter, then write a summary. "
        let text = String(repeating: sentence, count: 40)
        let block = ReaderBlock(index: 1, chunk: 0, role: "assistant", speaker: "ChatGPT", mark: nil, time: nil,
                                text: text, contentStart: 0, washes: [ReaderWash(range: 470..<479, style: .focus)])
        let preview = try XCTUnwrap(ReaderChat.preview(block))
        XCTAssertTrue(preview.text.hasSuffix("…"))
        XCTAssertFalse(preview.text.hasSuffix(".…"))
        XCTAssertFalse(preview.text.dropLast().last.map { ".,;:… ".contains($0) } ?? true)
        let kept = preview.text.unicodeScalars.count - 1
        XCTAssertTrue(preview.washes.allSatisfy { $0.range.upperBound <= kept }, "a wash is clipped to the kept words")
    }

    func testTheTurnACitationLandsInNeverFolds() throws {
        let doc = Self.claudeCodeSession()
        let start = try XCTUnwrap(ScalarText(doc.text).offset(of: "Step 9"))
        let (_, out) = rows(doc, focus: start..<(start + 6), keepOpen: [4])
        let reply = try XCTUnwrap(messages(out).first { $0.block.index == 4 })
        XCTAssertFalse(reply.folded)
        XCTAssertTrue(reply.block.holdsFocus)
        XCTAssertFalse(out.contains { if case .toggle(4, _, _) = $0.kind { true } else { false } },
                       "nothing to fold back while the cited words are in it")
        // Landing and the rotors address the very block the document view would.
        XCTAssertTrue(out.contains { $0.scrollID == AnyHashable(ReaderBlock.Key(turn: 4, chunk: 0)) })
    }

    func testAPreviewKeepsAWashThatFitsAndClipsOneThatRunsPast() throws {
        let block = ReaderBlock(index: 1, chunk: 0, role: "assistant", speaker: "Claude", mark: nil, time: nil,
                                text: String(repeating: "word ", count: 400), contentStart: 0,
                                washes: [ReaderWash(range: 10..<20, style: .other),
                                         ReaderWash(range: 470..<600, style: .other)])
        let preview = try XCTUnwrap(ReaderChat.preview(block))
        let count = preview.text.unicodeScalars.count - 1   // the "…"
        XCTAssertEqual(preview.washes.first, ReaderWash(range: 10..<20, style: .other))
        XCTAssertTrue(preview.washes.allSatisfy { $0.range.upperBound <= count })
    }

    // MARK: Days and keys

    func testDayLabelsAreRelativeAndComputedWhenRead() {
        func day(_ iso: String) -> String {
            ReaderChat.dayLabel(ISO8601DateFormatter().date(from: iso)!, now: now, locale: us, timeZone: utc)
        }
        XCTAssertEqual(day("2026-10-19T01:00:00Z"), "Today")
        XCTAssertEqual(day("2026-10-18T23:00:00Z"), "Yesterday")
        XCTAssertEqual(day("2026-10-15T12:00:00Z"), "Thursday")
        XCTAssertEqual(day("2026-09-03T12:00:00Z"), "Thu, Sep 3")
        XCTAssertEqual(day("2025-03-02T12:00:00Z"), "Mar 2, 2025")
    }

    func testKeysMoveFromTheRowAtTheTop() {
        // Opened at the newest: the column shows rows 16…19 of 20, so row 16 is at the top. ↑ must move at once —
        // the old cursor sat on row 19 and asked for row 18 at the top, which the scroll view clamped: nothing moved.
        let opened = ReaderChatKeys.target(.previous, top: 16, count: 20)
        XCTAssertEqual(opened?.index, 15)
        XCTAssertEqual(opened?.alignsTop, true)
        XCTAssertEqual(ReaderChatKeys.target(.pageUp, top: 16, count: 20)?.index, 11)
        XCTAssertEqual(ReaderChatKeys.target(.next, top: 16, count: 20)?.index, 17)
        XCTAssertEqual(ReaderChatKeys.target(.pageDown, top: 17, count: 20)?.index, 19, "the newest is an end")
        // A trackpad scroll moved the top to row 3: the keys start there, not where they last left off.
        XCTAssertEqual(ReaderChatKeys.target(.previous, top: 3, count: 20)?.index, 2)
        XCTAssertEqual(ReaderChatKeys.target(.first, top: 9, count: 20).map { [$0.index, $0.alignsTop ? 1 : 0] }, [0, 1])
        XCTAssertEqual(ReaderChatKeys.target(.last, top: 0, count: 20).map { [$0.index, $0.alignsTop ? 1 : 0] }, [19, 0])
        XCTAssertEqual(ReaderChatKeys.target(.previous, top: nil, count: 20)?.index, 18, "before the view has said")
        XCTAssertNil(ReaderChatKeys.target(.last, top: nil, count: 0))
    }

    // MARK: Saying each thing once

    func testAChatTitleDropsTheDayItsSeparatorsSay() {
        XCTAssertEqual(ReaderHeader.title(Self.messagesSitting()), "Messages with Sam")
        XCTAssertEqual(ReaderHeader.title(Self.claudeCodeSession()), "Index switch")
        let note = EpisodeText(episode: "ep_2026-10-18_002", text: "A note.", title: "Notes · 2026-10-18",
                               turns: [EpisodeTurn(index: 1, start: 0, contentStart: 0, end: 7)])
        XCTAssertEqual(ReaderHeader.title(note), "Notes · 2026-10-18", "a document keeps its title")
    }

    func testAChatMetaDropsTheDayAndTheCountAndNamesTheVendorOnce() {
        XCTAssertEqual(ReaderHeader.meta(Self.claudeCodeSession(), locale: us, timeZone: utc), "Claude Code · Opus 5.5")
        XCTAssertEqual(ReaderHeader.meta(Self.messagesSitting(), locale: us, timeZone: utc), "")
        let export = Self.exportWithLongReply()
        XCTAssertEqual(ReaderHeader.meta(export, locale: us, timeZone: utc), "", "the capture line names the export's vendor")
        XCTAssertEqual(ReaderHeader.captureLine(export), Copy.Provenance.importedFrom("ChatGPT"))
        // The document view is unchanged.
        let note = EpisodeText(episode: "ep_2026-10-18_002", text: "A note.", timestamp: "2026-10-18T10:00:00+00:00",
                               turns: [EpisodeTurn(index: 1, start: 0, contentStart: 0, end: 7)])
        XCTAssertEqual(ReaderHeader.meta(note, locale: us, timeZone: utc), "Oct 18, 2026 · 1 turn")
    }

    // MARK: What never folds

    func testKeepOpenHoldsTheLandingTurnAndEveryTurnWithACitedSpan() throws {
        // A 47k reply is many blocks; a quote in its third block keeps the WHOLE turn open.
        let doc = Self.exportWithLongReply()
        let scalars = ScalarText(doc.text)
        let all = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: nil, focusStyle: .focus)
        let third = try XCTUnwrap(all.first { $0.index == 2 && $0.chunk == 2 })
        let quote = (third.contentStart + 10)..<(third.contentStart + 40)
        let blocks = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: quote, focusStyle: .focus)
        let landing = ReaderLayout.blockID(containing: quote.lowerBound, in: blocks)
        XCTAssertEqual(landing, ReaderBlock.Key(turn: 2, chunk: 2))
        XCTAssertEqual(ReaderChat.keepOpen(blocks: blocks, landing: landing), [2])
        let built = ReaderChat.rows(blocks: blocks, doc: doc, keepOpen: ReaderChat.keepOpen(blocks: blocks, landing: landing),
                                    now: now, locale: us, timeZone: utc)
        XCTAssertTrue(built.contains { $0.scrollID == AnyHashable(ReaderBlock.Key(turn: 2, chunk: 2)) },
                      "the block landed on is drawn, so the scroll can reach it")
        XCTAssertFalse(built.contains { if case .toggle(2, _, _) = $0.kind { true } else { false } })

        // A found name (derived, bold, not washed as a quote) still holds the focus.
        let derived = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: quote, focusStyle: .mention)
        XCTAssertEqual(ReaderChat.keepOpen(blocks: derived, landing: nil), [2])

        // A focus with no range to wash (a stale quote, a name not found) lands by offset alone: that turn stays open.
        let plain = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: nil, focusStyle: .focus)
        let stale = ReaderLayout.blockID(containing: third.contentStart, in: plain)
        XCTAssertEqual(ReaderChat.keepOpen(blocks: plain, landing: stale), [2])
        XCTAssertEqual(ReaderChat.keepOpen(blocks: plain, landing: nil), [], "nothing landed: everything may fold")
    }

    // MARK: Speed

    func testA500TurnSessionAndA47kExportBuildTheirRowsInstantly() {
        var lines: [Line] = []
        for i in 0..<500 {
            let minute = String(format: "%02d", i % 60)
            let hour = String(format: "%02d", 8 + i / 60)
            lines.append(Line(marker: i.isMultiple(of: 2) ? "user" : "assistant",
                              text: String(repeating: "a sentence about the work. ", count: i.isMultiple(of: 7) ? 80 : 4),
                              ts: "2026-10-19T\(hour):\(minute):00+00:00"))
        }
        let session = Self.conversation(lines, harness: "claude-code", origin: "claude-code")
        let export = Self.exportWithLongReply()
        for doc in [session, export] {
            let clock = ContinuousClock()
            let elapsed = clock.measure {
                let scalars = ScalarText(doc.text)
                let blocks = ReaderLayout.blocks(doc: doc, scalars: scalars, focus: nil, focusStyle: .focus)
                _ = ReaderChat.rows(blocks: blocks, doc: doc)
            }
            XCTAssertLessThan(elapsed, .milliseconds(250), "\(doc.title): \(elapsed)")
        }
    }

    // MARK: Fit

    func testAChatNeverWantsMoreThanItsColumn() throws {
        let store = Self.store()
        let token = "https://example.com/" + String(repeating: "x", count: 300)
        let doc = Self.conversation([Line(marker: "user", text: "look: \(token)"),
                                     Line(marker: "assistant", text: "Seen. \(token)")], harness: "claude-code")
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for scale in [0.8, 1.0, 1.4] {
                CicadaTheme.uiScale = scale
                for column: CGFloat in [304, 364] {
                    let width = column * CGFloat(scale)
                    let built = rows(doc)
                    let renderer = ImageRenderer(content: ReaderChatView(rows: built.rows, landingTurn: nil, revealed: true)
                        .environment(store))
                    renderer.proposedSize = ProposedViewSize(width: width, height: nil)
                    let size = try XCTUnwrap(renderer.nsImage).size
                    XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(column) × \(scale): \(size.width)")
                }
            }
        }
    }

    // MARK: Snapshots (for the PR; CICADA_READER_CHAT_SNAPSHOTS=<dir>)

    func test_writeTheChatLayoutForComparison() throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_READER_CHAT_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_READER_CHAT_SNAPSHOTS=<dir> to write the chat layout")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let session = Self.claudeCodeSession()
        let quoteStart = try XCTUnwrap(ScalarText(session.text).offset(of: "keep the old table"))
        let quoteEnd = try XCTUnwrap(ScalarText(session.text).offset(of: "one commits")) + "one commits".count
        let quote = quoteStart..<quoteEnd
        let cases: [(String, EpisodeText, Range<Int>?, Set<Int>)] = [
            ("messages-sitting", Self.messagesSitting(), nil, []),
            ("claude-code-session", session, nil, []),
            ("export-long-reply", Self.exportWithLongReply(), nil, []),
            ("highlighted-quote", session, quote, []),
            ("relayed", Self.conversation([
                Line(marker: "user", text: "Help me plan the launch for next week.", ts: "2026-10-19T09:00:00+00:00"),
                Line(marker: "assistant", text: "Here is a checklist: scope, owners, dates.", ts: "2026-10-19T09:01:00+00:00"),
                Line(marker: "user", text: "Add a rollback step after the dates.", ts: "2026-10-19T09:02:00+00:00"),
            ], title: "Launch plan", harness: "chatgpt", origin: "chatgpt", captureKind: "transcript",
               forcedRole: "assistant", relay: EpisodeRelay(app: "chatgpt", label: "ChatGPT")), nil, []),
        ]
        let store = Self.store()
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for (name, doc, focus, expanded) in cases {
                let blocks = ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: focus,
                                                 focusStyle: .focus, locale: gb, timeZone: utc)
                var keepOpen = Set(blocks.filter(\.holdsFocus).map(\.index))
                if let focus, let key = ReaderLayout.blockID(containing: focus.lowerBound, in: blocks) {
                    keepOpen.insert(key.turn)
                }
                let built = ReaderChat.rows(blocks: blocks, doc: doc, expanded: expanded, keepOpen: keepOpen, now: now,
                                            locale: us, timeZone: utc)
                let landing = focus.flatMap { ReaderLayout.blockID(containing: $0.lowerBound, in: blocks)?.turn }
                let view = VStack(alignment: .leading, spacing: 0) {
                    ReaderColumnHeader(canGoBack: false, onBack: {}, page: nil,
                                       markOrigin: ReaderHeader.markOrigin(harness: doc.harness, origin: doc.origin),
                                       episode: doc.episode, title: ReaderHeader.title(doc),
                                       meta: ReaderHeader.meta(doc, locale: us, timeZone: utc), canResume: false,
                                       agent: nil, onResume: {}, onClose: {})
                    if let line = ReaderHeader.captureLine(doc) {
                        Text(line)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
                            .padding(.bottom, CicadaTheme.spacingSM)
                    }
                    ReaderChatView(rows: built, landingTurn: landing, revealed: true)
                        .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
                        .padding(.bottom, CicadaTheme.scaled(24))
                }
                .frame(width: 420)
                .background(CicadaTheme.bgPane)
                .environment(store)
                let renderer = ImageRenderer(content: view)
                renderer.scale = 2
                renderer.proposedSize = ProposedViewSize(width: 420, height: nil)
                let image = try XCTUnwrap(renderer.nsImage)
                let tiff = try XCTUnwrap(image.tiffRepresentation)
                let png = try XCTUnwrap(NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]))
                try png.write(to: URL(fileURLWithPath: dir)
                    .appendingPathComponent("\(name)-\(mode == .dark ? "dark" : "light").png"))
            }
        }
    }

    static func store() -> Store {
        Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
              api: FakeSyncAPI())
    }
}

private extension ScalarText {
    /// The scalar offset of `needle`'s first occurrence.
    func offset(of needle: String) -> Int? {
        let hay = scalars
        let n = Array(needle.unicodeScalars)
        guard !n.isEmpty, hay.count >= n.count else { return nil }
        for i in 0...(hay.count - n.count) where Array(hay[i..<(i + n.count)]) == n { return i }
        return nil
    }
}
