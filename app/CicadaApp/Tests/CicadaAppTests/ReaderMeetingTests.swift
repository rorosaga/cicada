import XCTest
@testable import CicadaApp

/// ROR-142 follow-up (2026-11-23): a meeting transcript's reader — speakers said in words, every run named, the
/// recorder's summary a header card and never a bubble, and the facts and the voices note under the title.
/// Placeholders only; no real meeting.
@MainActor
final class ReaderMeetingTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!
    private let us = Locale(identifier: "en_US")
    private let now = ISO8601DateFormatter().date(from: "2026-11-03T20:00:00Z")!

    /// A meeting as `GET /episodes/{id}/text` serves it: the summary first (turn 1, no stored time), then speaker lines
    /// whose `speaker` is the name the server derived and `speakerKind` what a missing name is.
    private func meeting(voices: Bool = true, summary: Bool = true) -> EpisodeText {
        var lines: [(marker: String, role: String, text: String, ts: String?, speaker: String?, kind: String?)] = []
        if summary {
            lines.append(("assistant", "assistant",
                          "Summary (written by Hex)\n> They agreed to ship the beta.\n> Docs come first.", nil, nil, nil))
        }
        lines += [
            ("speaker:speaker-1", "speaker", "Hello, shall we start?", "2026-11-03T15:01:00+00:00", "Speaker 1", "numbered"),
            ("user", "user", "Yes, go ahead.", "2026-11-03T15:01:03+00:00", "user", nil),
            ("speaker:speaker-2", "speaker", "The beta is ready.", "2026-11-03T15:01:09+00:00", "Speaker 2", "numbered"),
            ("user", "user", "Great.", "2026-11-03T15:01:12+00:00", "user", nil),
            ("speaker:speaker-2", "speaker", "Docs are next.", "2026-11-03T15:01:15+00:00", "Speaker 2", "numbered"),
            ("speaker:them", "speaker", "Sounds good to me.", "2026-11-03T15:01:20+00:00", nil, "group"),
            ("speaker:unknown", "speaker", "Who is that?", "2026-11-03T15:01:25+00:00", nil, "unknown"),
        ]
        var text = ""
        var turns: [EpisodeTurn] = []
        for (i, line) in lines.enumerated() {
            if i > 0 { text += "\n" }
            let start = text.unicodeScalars.count
            let prefix = "\(line.marker): "
            text += prefix + line.text
            turns.append(EpisodeTurn(index: i + 1, start: start, contentStart: start + prefix.unicodeScalars.count,
                                     end: text.unicodeScalars.count, role: line.role, marker: line.marker, speaker: line.speaker,
                                     ts: line.ts, speakerKind: line.kind))
        }
        var doc = EpisodeText(episode: "ep_2026-11-03_001", text: text, title: "Alpha planning",
                              timestamp: "2026-11-03T15:01:00+00:00", origin: "folder", turns: turns)
        doc.meeting = EpisodeMeeting(recorder: "hex", summaryTurn: summary ? 1 : nil,
                                     summaryWriter: "Written on this Mac by a recorder model.", durationS: 1013, app: "Video Call",
                                     attendees: 2, voicesSplitBy: voices ? "Example-Diarizer 2" : nil, voices: voices ? 2 : nil)
        return doc
    }

    private func rows(_ doc: EpisodeText) -> (blocks: [ReaderBlock], rows: [ReaderChat.Row]) {
        let blocks = ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: nil, focusStyle: .focus,
                                         locale: us, timeZone: utc)
        return (blocks, ReaderChat.rows(blocks: blocks, doc: doc, now: now, locale: us, timeZone: utc))
    }

    private func messages(_ rows: [ReaderChat.Row]) -> [ReaderChat.Message] {
        rows.compactMap { if case let .message(m) = $0.kind { m } else { nil } }
    }

    func testAPlaceholderReadsAsWordsAndTheGroupTrackAsOthersOnTheCall() {
        let doc = meeting()
        let said = rows(doc).blocks.filter(\.startsTurn).map(\.speaker)
        XCTAssertEqual(said, [Copy.Provenance.theAgent, "Speaker 1", Copy.you, "Speaker 2", Copy.you, "Speaker 2",
                              "Others on the call", Copy.Provenance.someoneElse])
        XCTAssertFalse(said.contains { $0.contains("speaker:") })
    }

    func testTheSummaryIsNoBubbleAndEveryRunOfAVoiceIsNamed() {
        let doc = meeting()
        let out = messages(rows(doc).rows)
        XCTAssertEqual(out.count, 7, "the summary turn is the header card, not a message")
        XCTAssertFalse(out.contains { $0.block.text.hasPrefix("Summary (written by") })
        // Speaker 2 speaks, the person answers, Speaker 2 again: both runs carry the name beside the avatar.
        let named = out.filter { $0.side == .other }.map { $0.header?.name }
        XCTAssertEqual(named, ["Speaker 1", "Speaker 2", "Speaker 2", "Others on the call", Copy.Provenance.someoneElse])
        for message in out where message.side == .other {
            guard case let .face(face)? = message.header?.avatar else { return XCTFail("a voice wears a face") }
            XCTAssertEqual(LogoImage.monogram(for: face).first, message.header?.name?.first, "initials match the shown name")
        }
    }

    func testAnOrdinaryChatStillNamesItsOtherSideOnce() {
        // The one-to-one rule is unchanged: only a meeting names every run.
        var doc = meeting(summary: false)
        doc.meeting = nil
        let out = messages(rows(doc).rows).filter { $0.side == .other }
        XCTAssertEqual(out.map { $0.header?.name }, ["Speaker 1", "Speaker 2", nil, "Others on the call", Copy.Provenance.someoneElse])
    }

    func testTheHeaderCarriesTheFactsTheSummaryAndTheVoicesNote() throws {
        let doc = meeting()
        let header = try XCTUnwrap(ReaderChat.meetingHeader(doc: doc, blocks: rows(doc).blocks))
        XCTAssertEqual(header.title, "Summary · written by Hex")
        XCTAssertEqual(header.facts, "17 min · Video Call · 2 attendees")
        XCTAssertEqual(header.voices, "Voices split on this Mac by Example-Diarizer 2 (2 voices). Speaker numbers are its guess.")
        XCTAssertEqual(header.writer, "Written on this Mac by a recorder model.")
        let words = header.summary.flatMap { ReaderText.segments($0) }.map(\.text).joined()
        XCTAssertFalse(words.contains("Summary (written by"), "the heading line is the card's title, not its words")
        XCTAssertTrue(words.contains("They agreed to ship the beta."))
        XCTAssertFalse(words.contains(">"), "the quote markers the stored body carries are not drawn")
    }

    func testAMeetingWithNoSummaryStillSaysItsFactsAndAnOrdinaryChatHasNoHeader() throws {
        let bare = meeting(voices: false, summary: false)
        let header = try XCTUnwrap(ReaderChat.meetingHeader(doc: bare, blocks: rows(bare).blocks))
        XCTAssertNil(header.title)
        XCTAssertFalse(header.hasSummary)
        XCTAssertNil(header.voices)
        XCTAssertEqual(messages(rows(bare).rows).count, 7)
        var chat = meeting()
        chat.meeting = nil
        XCTAssertNil(ReaderChat.meetingHeader(doc: chat, blocks: rows(chat).blocks))
    }

    func testACitedSummaryKeepsTheCardOpen() throws {
        let doc = meeting()
        let blocks = ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: 40..<60, focusStyle: .focus,
                                         locale: us, timeZone: utc)
        let header = try XCTUnwrap(ReaderChat.meetingHeader(doc: doc, blocks: blocks))
        XCTAssertTrue(header.holdsFocus)
    }

    func testTheWireDecodesTheMeetingAndTheSpeakerKind() throws {
        let json = """
        {"episode":"ep_2026-11-03_001","kind":"episode","text":"x","length":1,"hash":"h","truncated":false,"title":"T",
         "turns":[{"index":1,"start":0,"contentStart":0,"end":1,"role":"speaker","marker":"speaker:them","speaker":null,
                   "speakerKind":"group"}],
         "meeting":{"recorder":"hex","summaryTurn":1,"durationS":60,"attendees":3,"voicesSplitBy":"Example-Diarizer 2","voices":2}}
        """
        let doc = try JSONDecoder().decode(EpisodeText.self, from: Data(json.utf8))
        XCTAssertEqual(doc.turns.first?.speakerKind, "group")
        XCTAssertEqual(doc.meeting, EpisodeMeeting(recorder: "hex", summaryTurn: 1, durationS: 60, attendees: 3,
                                                   voicesSplitBy: "Example-Diarizer 2", voices: 2))
        let old = try JSONDecoder().decode(EpisodeText.self, from: Data(#"{"episode":"e","text":"x"}"#.utf8))
        XCTAssertNil(old.meeting)
    }

    func testARecordersFolderWearsItsAppsIconAndFallsBackToTheFolder() {
        XCTAssertEqual(OriginIconography.appBundleId(for: "hex"), "anomaly.hex")
        XCTAssertEqual(OriginIconography.label(for: "hex"), "Hex")
        XCTAssertEqual(OriginIconography.symbol(for: "hex"), OriginIconography.symbol(for: "folder"),
                       "with Hex not installed, the folder's own glyph")
    }

    func testTheReaderTitleWearsTheRecordersMarkNotTheFolders() {
        XCTAssertEqual(ReaderHeader.markOrigin(harness: nil, origin: "folder", recorder: "hex"), "hex")
        XCTAssertEqual(ReaderHeader.markOrigin(harness: nil, origin: "folder"), "folder")
        XCTAssertEqual(ReaderHeader.markOrigin(harness: "claude-code", origin: "folder", recorder: "hex"), "claude-code")
    }
}
