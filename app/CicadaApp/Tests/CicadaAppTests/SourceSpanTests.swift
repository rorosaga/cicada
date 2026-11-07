import XCTest
@testable import CicadaApp

/// ROR-16, G118 — the one shape of "this part of this source", and what the Reader does with it.
final class SourceSpanTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    private func doc(kind: String?, focus: EpisodeFocus? = nil, text: String = "user: words here\nassistant: noted",
                     turns: [EpisodeTurn] = []) -> EpisodeText {
        var doc = EpisodeText(episode: "ep_2026-09-01_001", kind: "episode", text: text, length: text.unicodeScalars.count,
                              hash: "abc", truncated: false, title: "T", turns: turns, focus: focus)
        doc.sourceKind = kind
        return doc
    }

    func testASpanThatMayBeDrawnHasARange() throws {
        let span = try decode(SourceSpan.self, #"{"source":"ep_1","status":"current","kind":"user","hash":"h","at":{"type":"text","start":3,"end":9},"claimId":"c","current":true}"#)
        XCTAssertEqual(span.range, 3..<9)
        XCTAssertEqual(span.claimId, "c")
    }

    func testWhatMayNotBeDrawnHasNoRangeWhateverIsSent() throws {
        for status in ["stale", "held", "unlocated", "something-new"] {
            let span = try decode(SourceSpan.self, #"{"source":"ep_1","status":"\#(status)","at":{"type":"text","start":3,"end":9}}"#)
            XCTAssertNil(span.range, status)
        }
    }

    /// The room left for other media: a time range or a PDF's page decodes, draws nothing, and the source still opens.
    func testAnotherMediumDecodesAndDrawsNothing() throws {
        for at in [#"{"type":"time","fromS":12,"toS":40}"#, #"{"type":"pdf","page":3}"#] {
            let span = try decode(SourceSpan.self, #"{"source":"ep_1","status":"current","at":\#(at)}"#)
            XCTAssertNil(span.range, at)
            guard case .other = span.at else { return XCTFail(at) }
        }
    }

    func testTheGroupsFoldToOnePlaceEach() throws {
        let spans = try decode(SourceSpans.self, #"""
        {"source":"ep_1","sourceKind":"note","hash":"h","length":40,"groups":[
          {"page":"a","name":"A","type":"project","spans":[{"source":"ep_1","status":"current","at":{"type":"text","start":10,"end":14}},
                                                           {"source":"ep_1","status":"held"}]},
          {"page":"b","name":"B","type":"tool","spans":[{"source":"ep_1","status":"current","at":{"type":"text","start":0,"end":4}},
                                                        {"source":"ep_1","status":"current","at":{"type":"text","start":10,"end":14}}]}]}
        """#)
        XCTAssertEqual(spans.ranges, [0..<4, 10..<14])
    }

    // MARK: What the Reader does

    private func present(_ focus: ReaderTarget.Focus, doc: EpisodeText) -> ReaderPresentation {
        ReaderPresentation.resolve(target: ReaderTarget(episode: doc.episode, focus: focus), doc: doc,
                                   textCount: ScalarText(doc.text).count)
    }

    /// The server judged it: an asked span it sent no place for is never drawn from the target's own offsets, and is
    /// never apologised for. A held span and a gap line both arrive this way.
    func testAnAskedSpanTheServerPlacedNowhereDrawsNothingAndSaysNothing() {
        let held = SourceSpan(source: "ep_1", status: .held)
        let p = present(.span(start: 3, end: 9, hash: "h", derived: false),
                        doc: doc(kind: "note", focus: EpisodeFocus(start: nil, end: nil, span: held)))
        XCTAssertNil(p.focus)
        XCTAssertEqual(p.banners, [])
        XCTAssertNil(p.landing, "no place travelled, so nothing to land near")
    }

    func testAStaleSpanStaysHonest() {
        let stale = SourceSpan(source: "ep_1", status: .stale)
        let p = present(.span(start: 3, end: 9, hash: "h", derived: false),
                        doc: doc(kind: "note", focus: EpisodeFocus(start: nil, end: nil, stale: true, span: stale)))
        XCTAssertNil(p.focus)
        XCTAssertEqual(p.banners, [.stale])
    }

    func testNothingToLocateOpensTheSourceWithNoApology() {
        XCTAssertEqual(present(.none, doc: doc(kind: "note")).banners, [])
        XCTAssertEqual(present(.mention(entityId: "bob-example"), doc: doc(kind: "note")).banners, [],
                       "a name not found says nothing")
    }

    func testACitationAlwaysHasASourceToOpen() {
        let reasoning = Evidence(episode: "ep_1", start: -1, end: -1, kind: .reasoning)
        XCTAssertEqual(ReaderTarget.evidence(reasoning, subjectId: nil)?.episode, "ep_1")
        XCTAssertEqual(ReaderTarget.evidence(reasoning, subjectId: nil)?.focus, ReaderTarget.Focus.none)
        var held = ProvenanceSpan(episode: "ep_1", start: nil, end: nil, kind: .user, excerpt: "")
        held.held = true
        XCTAssertEqual(ReaderTarget.best(held, subjectId: nil).focus, ReaderTarget.Focus.none)
    }

    /// One document is not "You · turn 1" and has no turn count; a conversation keeps both.
    func testOnlyAConversationCountsTurns() {
        let text = "Rover arm: the camera needs work."
        let turn = EpisodeTurn(index: 1, start: 0, contentStart: 0, end: text.unicodeScalars.count, role: "user")
        let note = doc(kind: "note", text: text, turns: [turn])
        let block = ReaderLayout.blocks(doc: note, scalars: ScalarText(text), focus: 11..<20, focusStyle: .focus)[0]
        XCTAssertEqual(block.speaker, "")
        XCTAssertFalse(block.showsTurnNumber)
        XCTAssertEqual(block.washes.map(\.range), [11..<20], "and its words still wash")
        XCTAssertFalse(ReaderHeader.meta(note).contains("turn"))

        let chat = doc(kind: "conversation", text: text, turns: [turn])
        XCTAssertTrue(ReaderLayout.blocks(doc: chat, scalars: ScalarText(text), focus: nil, focusStyle: .focus)[0].showsTurnNumber)
        XCTAssertTrue(ReaderHeader.meta(chat).contains("turn"))
    }

    func testACitationSaysWhatItOpens() {
        XCTAssertEqual(Copy.Provenance.showIn("note"), "Show in note")
        XCTAssertEqual(Copy.Provenance.showIn("meeting"), "Show in meeting")
        XCTAssertEqual(Copy.Provenance.showIn("conversation"), "Show in conversation")
        XCTAssertEqual(Copy.Provenance.showIn(nil), "Show source")
    }

    /// DR-60 and the picture rail, read off the component: a key moves the column in one frame, and it draws no picture.
    func testTheComponentNeverAnimatesAKeyAndLoadsNoPicture() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp/Views/Provenance/SourceSpansView.swift")
        let source = try String(contentsOf: root, encoding: .utf8)
        XCTAssertTrue(source.contains("Instant.run { proxy.scrollTo(request.id"))
        XCTAssertFalse(source.contains("AsyncImage"))
        XCTAssertFalse(source.contains("Image("))
    }

    @MainActor
    func testTheSpansAreCachedUnderTheirETagAndForgottenOnABankSwitch() async {
        let api = FakeProvenanceAPI()
        api.sourceSpans = SourceSpans(source: "ep_1", sourceKind: "note", hash: "h", length: 1, groups: [])
        let cache = ProvenanceCache(api: api)
        let first = await cache.sourceSpans(source: "ep_1")
        XCTAssertEqual(first.value?.sourceKind, "note")
        let second = await cache.sourceSpans(source: "ep_1")
        XCTAssertEqual(second.value?.sourceKind, "note", "a 304 keeps the copy")
        XCTAssertEqual(api.sourceSpansAsks, 2, "revalidated on every ask")
    }
}
