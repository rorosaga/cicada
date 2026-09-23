import XCTest
@testable import CicadaApp

/// Design §4.4 / §4.10 — the Reader's decisions: which turn a wash lands in,
/// who is speaking, which time is shown, and what the banner says.
final class ReaderTurnsTests: XCTestCase {

    private let utc = TimeZone(identifier: "UTC")!
    /// en_GB for clock times ("14:31" on every ICU); en_US for days — en_GB's
    /// September abbreviation differs between ICU versions ("Sep"/"Sept").
    private let gb = Locale(identifier: "en_GB")
    private let us = Locale(identifier: "en_US")

    /// `user: can we stop?\nassistant: Yes. we moved the index to sqlite-vec.`
    /// Offsets are what `evidence.turns` returns for this text (turn starts at
    /// the marker line, `contentStart` skips `role: `).
    private func conversation(harness: String? = "claude-code", origin: String? = "claude-code",
                              ts: String? = nil, focus: EpisodeFocus? = nil,
                              truncated: Bool = false) -> EpisodeText {
        let text = "user: can we stop?\nassistant: Yes. we moved the index to sqlite-vec."
        return EpisodeText(
            episode: "ep_2026-09-03_004", text: text, truncated: truncated, title: "Index choice",
            timestamp: "2026-09-03T10:00:00+00:00", harness: harness, origin: origin,
            conversationId: "ses_alpha", captureKind: "transcript",
            turns: [EpisodeTurn(index: 1, start: 0, contentStart: 6, end: 18, role: "user", marker: "user"),
                    EpisodeTurn(index: 2, start: 19, contentStart: 30, end: 68, role: "assistant",
                                marker: "assistant", speaker: "assistant", ts: ts)],
            focus: focus)
    }

    private func blocks(_ doc: EpisodeText, focus: Range<Int>?, style: ReaderWash.Style = .focus,
                        others: [Range<Int>] = []) -> [ReaderBlock] {
        ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: focus, focusStyle: style,
                            others: others, locale: gb, timeZone: utc)
    }

    // MARK: Layout

    func testTurnsCarryTheirContentWithoutTheMarkerAndAHarnessSpeaker() {
        let out = blocks(conversation(), focus: nil)
        XCTAssertEqual(out.map(\.text), ["can we stop?", "Yes. we moved the index to sqlite-vec."])
        XCTAssertEqual(out.map(\.speaker), [Copy.you, "Claude Code"])
        XCTAssertEqual(out.map(\.mark), [nil, "claude-code"], "a named agent wears its mark; the person does not")
        XCTAssertEqual(out.map(\.contentStart), [6, 30])
    }

    func testAWashLandsInsideItsTurnInLocalOffsets() {
        let doc = conversation()
        let start = ScalarText(doc.text).slice(0, 68).distance(of: "sqlite-vec")!
        let out = blocks(doc, focus: start..<(start + 10))
        XCTAssertEqual(out[0].washes, [])
        XCTAssertEqual(out[1].washes, [ReaderWash(range: (start - 30)..<(start - 20), style: .focus)])
        XCTAssertEqual(ScalarText(out[1].text).slice(start - 30, start - 20), "sqlite-vec")
        XCTAssertTrue(out[1].holdsFocus)
    }

    func testASpanCrossingATurnBoundaryIsSplitIntoTwoWashes() {
        // From "stop?" in turn 1 into "Yes." in turn 2.
        let out = blocks(conversation(), focus: 13..<34)
        XCTAssertEqual(out[0].washes, [ReaderWash(range: 7..<12, style: .focus)], "\"stop?\" — to the end of turn 1")
        XCTAssertEqual(out[1].washes, [ReaderWash(range: 0..<4, style: .focus)], "\"Yes.\" — the marker is skipped")
    }

    func testOtherSpansWashFainterAndNeverDuplicateTheFocus() {
        let out = blocks(conversation(), focus: 30..<34, others: [30..<34, 6..<9])
        XCTAssertEqual(out[0].washes, [ReaderWash(range: 0..<3, style: .other)])
        XCTAssertEqual(out[1].washes, [ReaderWash(range: 0..<4, style: .focus)])
    }

    // MARK: A long turn is cut into chunks (final review)

    /// One 50K-scalar turn with no markers: a note, or a file with no
    /// headings. Lines are 40 scalars ("alpha-project line 00000 …\n").
    private func longTurn(scalars: Int = 50_000) -> EpisodeText {
        var text = ""
        var n = 0
        while text.unicodeScalars.count < scalars {
            text += "alpha-project line " + String(format: "%05d", n) + " bob-example ok\n"
            n += 1
        }
        let count = text.unicodeScalars.count
        return EpisodeText(episode: "ep_2026-09-03_009", text: text, title: "A long note",
                           turns: [EpisodeTurn(index: 1, start: 0, contentStart: 0, end: count, role: "user",
                                               marker: "user")])
    }

    func testALongTurnIsCutIntoChunksOnLineBreaksThatLoseNoWords() {
        let doc = longTurn()
        let out = blocks(doc, focus: nil)
        XCTAssertGreaterThan(out.count, 1, "one Text per 400K turn froze the main thread for 11 s")
        XCTAssertTrue(out.allSatisfy { $0.text.unicodeScalars.count <= ReaderLayout.chunkLimit })
        XCTAssertEqual(out.map(\.chunk), Array(0..<out.count))
        XCTAssertEqual(Set(out.map(\.index)), [1], "every chunk belongs to the one turn")
        XCTAssertEqual(out.filter(\.startsTurn).count, 1, "the speaker line is drawn once")
        XCTAssertEqual(Set(out.map(\.id)).count, out.count, "each chunk is its own scroll and rotor target")
        // Each cut drops exactly the "\n" it was made on, so the pieces joined
        // by line breaks are the document again, and every chunk's own
        // offsets point at its own words.
        XCTAssertEqual(out.map(\.text).joined(separator: "\n"), doc.text)
        let scalars = ScalarText(doc.text)
        for block in out {
            XCTAssertEqual(scalars.slice(block.contentStart, block.contentStart + block.text.unicodeScalars.count),
                           block.text)
        }
        for block in out.dropLast() {
            XCTAssertFalse(block.text.hasSuffix("\n"), "a break at a cut would draw a blank line")
        }
    }

    func testAWashAcrossAChunkBoundaryIsSplitIntoTwoLocalRanges() {
        let doc = longTurn()
        let first = blocks(doc, focus: nil)
        let boundary = first[1].contentStart   // one past the dropped "\n"
        let out = blocks(doc, focus: (boundary - 11)..<(boundary + 5))
        let firstLength = out[0].text.unicodeScalars.count
        XCTAssertEqual(out[0].washes, [ReaderWash(range: (firstLength - 10)..<firstLength, style: .focus)],
                       "the tail of chunk 0, in chunk 0's own offsets")
        XCTAssertEqual(out[1].washes, [ReaderWash(range: 0..<5, style: .focus)],
                       "the head of chunk 1, in chunk 1's own offsets")
        XCTAssertTrue(out[2...].allSatisfy(\.washes.isEmpty))
        XCTAssertEqual(ReaderLayout.blockID(containing: boundary + 2, in: out), out[1].id,
                       "landing addresses the chunk that holds the words")
    }

    func testAHardCutNeverTearsACombiningMarkFromItsLetter() {
        // No line break or space anywhere: "é" as e + U+0301, repeated.
        let text = String(repeating: "e\u{0301}", count: 3_000)
        let scalars = ScalarText(text)
        let cuts = ReaderLayout.chunks(0..<scalars.count, in: scalars)
        XCTAssertGreaterThan(cuts.count, 1)
        XCTAssertEqual(cuts.map(\.count).reduce(0, +), scalars.count, "a hard cut drops nothing")
        for cut in cuts.dropFirst() {
            XCTAssertFalse(scalars.scalars[cut.lowerBound].properties.isGraphemeExtend,
                           "a chunk never opens on a combining mark")
        }
    }

    // MARK: Times — shown only when stored

    func testATimeIsShownOnlyWhenTheEpisodeStoresOne() {
        XCTAssertEqual(blocks(conversation(), focus: nil).map(\.time), [nil, nil], "never inferred")
        let stamped = blocks(conversation(ts: "2026-09-03T14:31:00+00:00"), focus: nil)
        XCTAssertEqual(stamped.map(\.time), [nil, "14:31"])
    }

    func testTimeLabelsReadEveryShapeABankHolds() {
        XCTAssertEqual(ReaderTime.label("2026-09-03T14:31:00Z", locale: gb, timeZone: utc), "14:31")
        XCTAssertEqual(ReaderTime.label("2026-09-03T14:31:00.123+00:00", locale: gb, timeZone: utc), "14:31")
        XCTAssertEqual(ReaderTime.label("2026-09-03T14:31:00.123456+00:00", locale: gb, timeZone: utc), "14:31",
                       "microseconds — `episode_ids.utc_now_iso`'s own shape, and every epoch an importer converts")
        XCTAssertEqual(ReaderTime.label("2026-09-03T14:31:00", locale: gb, timeZone: utc), "14:31",
                       "a naive stamp is read in the viewer's zone (G114)")
        XCTAssertEqual(ReaderTime.label("00:23:41", locale: gb, timeZone: utc), "00:23:41",
                       "a meeting offset passes through")
        XCTAssertNil(ReaderTime.label(nil))
        XCTAssertNil(ReaderTime.label("   "))
        XCTAssertNil(ReaderTime.label("not a time"))
    }

    func testTheDayComesFromTheTimestampElseTheEpisodeId() {
        XCTAssertEqual(ReaderTime.day(timestamp: "2026-09-03T10:00:00Z", episode: "x", locale: us, timeZone: utc),
                       "Sep 3, 2026")
        XCTAssertEqual(ReaderTime.day(timestamp: nil, episode: "ep_2026-08-12_007", locale: us, timeZone: utc),
                       "Aug 12, 2026")
        XCTAssertNil(ReaderTime.day(timestamp: nil, episode: "media-example-com", locale: us, timeZone: utc))
    }

    // MARK: Speakers

    func testSpeakersNeverPrintARoleWordAsANameAndAMeetingSpeakerIsNeverYou() {
        func speaker(_ role: String, marker: String? = nil, name: String? = nil,
                     harness: String? = nil, origin: String? = nil) -> String {
            EvidenceSpeaker.turnSpeaker(EpisodeTurn(index: 1, start: 0, contentStart: 0, end: 1, role: role,
                                                    marker: marker, speaker: name),
                                        harness: harness, origin: origin)
        }
        XCTAssertEqual(speaker("user", marker: "user", name: "user"), Copy.you, "an importer sidecar role is not a name")
        XCTAssertEqual(speaker("user", marker: "system"), Copy.Provenance.setupMessage)
        XCTAssertEqual(speaker("user", marker: "unknown"), Copy.Provenance.unlabelledMessage)
        XCTAssertEqual(speaker("user", marker: nil), Copy.you, "a marker-less note is the person's (R4)")
        XCTAssertEqual(speaker("assistant", harness: "codex"), "Codex")
        XCTAssertEqual(speaker("assistant", origin: "chatgpt-export"), "ChatGPT")
        XCTAssertEqual(speaker("assistant", harness: "mcp"), Copy.Provenance.theAgent, "mcp names no product")
        XCTAssertEqual(speaker("assistant"), Copy.Provenance.theAgent)
        XCTAssertEqual(speaker("speaker", name: "Speaker 2"), "Speaker 2")
        XCTAssertEqual(speaker("speaker", name: "assistant"), Copy.Provenance.someoneElse)
        XCTAssertEqual(speaker("speaker"), Copy.Provenance.someoneElse, "R-N2 — never \"You\"")
        XCTAssertEqual(speaker("page"), "")

        // The mark beside a named agent follows the SAME precedence as its name.
        XCTAssertEqual(EvidenceSpeaker.agentOrigin(harness: "codex", origin: "codex"), "codex")
        XCTAssertEqual(EvidenceSpeaker.agentOrigin(harness: nil, origin: "chatgpt-export"), "chatgpt-export",
                       "an import wears its vendor's mark")
        XCTAssertNil(EvidenceSpeaker.agentOrigin(harness: "mcp", origin: "mcp"), "no product named, no mark")
        XCTAssertNil(EvidenceSpeaker.agentOrigin(harness: nil, origin: "telegram"))
    }

    // MARK: Presentation — the honesty rules (§4.9)

    private func present(_ focus: ReaderTarget.Focus, doc: EpisodeText) -> ReaderPresentation {
        ReaderPresentation.resolve(target: ReaderTarget(episode: doc.episode, focus: focus), doc: doc,
                                   textCount: ScalarText(doc.text).count)
    }

    func testAStaleSpanNeverWashesButStillLandsNearItsWords() {
        let doc = conversation(focus: EpisodeFocus(start: nil, end: nil, kind: .assistant, stale: true))
        let p = present(.span(start: 58, end: 68, hash: "old", derived: false), doc: doc)
        XCTAssertNil(p.focus)
        XCTAssertEqual(p.banners, [.stale])
        XCTAssertEqual(p.landing, 58)
    }

    func testAGrownSpanWashesAndSaysTheConversationContinued() {
        let doc = conversation(focus: EpisodeFocus(start: 58, end: 68, kind: .assistant, grown: true))
        let p = present(.span(start: 58, end: 68, hash: "h", derived: false), doc: doc)
        XCTAssertEqual(p.focus, 58..<68)
        XCTAssertEqual(p.focusStyle, .focus)
        XCTAssertEqual(p.banners, [.grown])
    }

    func testADerivedTargetBoldsAndSaysSoEvenWhenTheServerSawOffsets() {
        let doc = conversation(focus: EpisodeFocus(start: 58, end: 68, kind: .assistant))
        let p = present(.span(start: 58, end: 68, hash: nil, derived: true), doc: doc)
        XCTAssertEqual(p.focusStyle, .mention, "an inbox cause found by name stays found by name (R-PB16)")
        XCTAssertEqual(p.banners, [.derived])
    }

    func testAMentionTargetUsesTheServersDerivedFocusOrSaysItFoundNothing() {
        let found = conversation(focus: EpisodeFocus(start: 58, end: 68, kind: .derived, derived: true))
        XCTAssertEqual(present(.mention(entityId: "sqlite-vec"), doc: found).focus, 58..<68)
        XCTAssertEqual(present(.mention(entityId: "sqlite-vec"), doc: found).banners, [.derived])
        let missed = conversation(focus: nil)
        let p = present(.mention(entityId: "bob-example"), doc: missed)
        XCTAssertNil(p.focus)
        XCTAssertEqual(p.banners, [.notFound])
        XCTAssertNil(p.landing, "nothing found opens at the top")
    }

    func testInferredAndStaleTargetsOpenAtTheTopUnderTheirBanner() {
        XCTAssertEqual(present(.inferred, doc: conversation()).banners, [.inferred])
        XCTAssertEqual(present(.stale, doc: conversation()).banners, [.stale])
        XCTAssertNil(present(.inferred, doc: conversation()).landing)
    }

    func testWordsPastTheCapAreNotWashedAndTheTruncationIsSaid() {
        let doc = conversation(focus: EpisodeFocus(start: 500, end: 510), truncated: true)
        let p = present(.span(start: 500, end: 510, hash: nil, derived: false), doc: doc)
        XCTAssertNil(p.focus)
        XCTAssertEqual(p.banners, [.truncated])
    }

    // MARK: Header

    func testTheCaptureLineIsHonestAboutWhatWasKept() {
        XCTAssertEqual(ReaderHeader.captureLine(conversation()), Copy.Provenance.captureHonesty)
        let imported = EpisodeText(episode: "ep_1", text: "user: hi", origin: "chatgpt-export")
        XCTAssertEqual(ReaderHeader.captureLine(imported), Copy.Provenance.importedFrom("ChatGPT"))
        XCTAssertNil(ReaderHeader.captureLine(EpisodeText(episode: "ep_1", text: "a note", origin: "telegram")))
        XCTAssertNil(ReaderHeader.captureLine(EpisodeText(episode: "ep_1", text: "water the plants", origin: "telegram",
                                                          captureKind: "reminder")),
                     "a Telegram /remind note is stamped too, and holds exactly what was sent — the line would lie")
        XCTAssertNil(ReaderHeader.captureLine(EpisodeText(episode: "media-x", kind: "page", text: "t")))
    }

    func testTheMetaLineNamesTheAgentTheDayAndTheTurns() {
        XCTAssertEqual(ReaderHeader.meta(conversation(), locale: us, timeZone: utc),
                       "Claude Code · Sep 3, 2026 · 2 turns")
        let page = EpisodeText(episode: "media-example-com", kind: "page", text: "t",
                               turns: [EpisodeTurn(index: 1, start: 0, contentStart: 0, end: 1, role: "page")])
        XCTAssertEqual(ReaderHeader.meta(page, locale: us, timeZone: utc), Copy.Provenance.fromThePage)
    }
}

private extension String {
    /// Scalar offset of `needle` — test-only, so fixtures can say "where
    /// sqlite-vec is" instead of hard-coding a number a reader must re-count.
    func distance(of needle: String) -> Int? {
        guard let r = range(of: needle) else { return nil }
        return unicodeScalars.distance(from: unicodeScalars.startIndex, to: r.lowerBound)
    }
}
