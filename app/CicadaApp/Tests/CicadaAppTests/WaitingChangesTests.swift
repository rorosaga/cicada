import XCTest
@testable import CicadaApp

/// Owner 2026-11-23 — a waiting episode's marker (new / updated / deleted at its source) and, in the Reader, what
/// changed since Sleep last read it.
final class WaitingChangesTests: XCTestCase {
    private func item(change: String?, processed: Bool = false) throws -> EpisodeQueueItem {
        var json: [String: Any] = ["id": "ep_1", "timestamp": "2026-11-23T10:00:00Z", "source": "apple-notes",
                                   "origin": "apple-notes", "title": "Groceries", "preview": "", "processed": processed]
        if let change { json["change"] = change }
        return try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    // MARK: The Waiting card

    func testOnlyAWaitingEpisodeWearsAMarkerAndItsMeaningIsAlsoInWords() throws {
        XCTAssertEqual(EpisodeChange.of(try item(change: "new")), .new)
        XCTAssertEqual(EpisodeChange.of(try item(change: "updated")), .updated)
        XCTAssertEqual(EpisodeChange.of(try item(change: "removed")), .removed)
        XCTAssertNil(EpisodeChange.of(try item(change: "updated", processed: true)), "a read episode wears none")
        XCTAssertNil(EpisodeChange.of(try item(change: "something-newer")), "an unknown word is no marker")
        XCTAssertNil(EpisodeChange.of(try item(change: nil)), "an older backend")

        let now = Date(timeIntervalSince1970: 1_795_000_000)
        XCTAssertFalse(EpisodeRowText.footer(try item(change: "new"), target: nil, now: now).contains("new"),
                       "most of a queue is new: the dot is enough")
        XCTAssertEqual(EpisodeRowText.footer(try item(change: "updated"), target: nil, now: now).last, "updated")
        XCTAssertEqual(EpisodeRowText.footer(try item(change: "removed"), target: nil, now: now).last,
                       "deleted at its source")
        XCTAssertTrue(EpisodeRowText.cardLabel(try item(change: "new"), target: nil, now: now).hasSuffix(", new"),
                      "VoiceOver hears what the dot shows")
        XCTAssertTrue(EpisodeRowText.help(try item(change: "updated"), kind: nil).hasPrefix("Updated: changed since"))
        XCTAssertNotEqual(EpisodeChange.new.color, EpisodeChange.updated.color)
    }

    // MARK: The Reader

    private func doc(_ text: String, changes: EpisodeChanges?) -> EpisodeText {
        var doc = EpisodeText(episode: "ep_1", text: text, title: "Groceries",
                              turns: [EpisodeTurn(index: 0, start: 0, contentStart: 0, end: text.unicodeScalars.count)])
        doc.changes = changes
        return doc
    }

    func testTheChangedStretchesDropTheirLineBreakAndJoinTheirNeighbours() {
        let text = "Groceries\nmilk\noat milk\nbread\ncoffee\ntea"
        //          0         10    15        24     30      37
        let changes = EpisodeChanges(state: "updated", changed: [[15, 24], [30, 37], [37, 40], [900, 950]])
        let got = ReaderChanges.ranges(doc(text, changes: changes), scalars: ScalarText(text))
        XCTAssertEqual(got, [15..<23, 30..<40], "the line break is dropped; touching lines join; past the text: none")
        XCTAssertEqual(ReaderChanges.ranges(doc(text, changes: .init(state: "new")), scalars: ScalarText(text)), [])
        XCTAssertEqual(ReaderChanges.ranges(doc(text, changes: nil), scalars: ScalarText(text)), [])
    }

    func testACitedSpanKeepsItsOwnWashInsideAChangedStretch() {
        XCTAssertEqual(ReaderChanges.minus([10..<30], cutting: [15..<20]), [10..<15, 20..<30])
        XCTAssertEqual(ReaderChanges.minus([10..<30], cutting: [5..<12, 28..<40]), [12..<28])
        XCTAssertEqual(ReaderChanges.minus([10..<30], cutting: []), [10..<30])
        XCTAssertEqual(ReaderChanges.minus([10..<30], cutting: [0..<40]), [])
    }

    func testTheReaderWashesWhatChangedSaysSoAndLandsOnIt() {
        let text = "Groceries\nmilk\noat milk\nbread"
        let changes = EpisodeChanges(state: "updated", changed: [[15, 24]], removed: ["eggs"])
        let updated = doc(text, changes: changes)
        let scalars = ScalarText(text)
        let presentation = ReaderPresentation.resolve(target: ReaderTarget(episode: "ep_1"), doc: updated,
                                                      textCount: scalars.count)
        XCTAssertEqual(presentation.banners.first, .updated(parts: 1, removed: ["eggs"]))
        XCTAssertEqual(presentation.landing, 15, "opened for no span, the Reader lands on the first change")
        let blocks = ReaderLayout.blocks(doc: updated, scalars: scalars, focus: nil, focusStyle: .focus,
                                         changed: ReaderChanges.ranges(updated, scalars: scalars))
        XCTAssertEqual(blocks.flatMap(\.washes), [ReaderWash(range: 15..<23, style: .changed)])
        XCTAssertEqual(blocks.flatMap(ReaderText.segments).filter { $0.mark == .changed }.map(\.text), ["oat milk"])

        let deleted = doc(text, changes: .init(state: "removed"))
        XCTAssertEqual(ReaderPresentation.resolve(target: ReaderTarget(episode: "ep_1"), doc: deleted,
                                                  textCount: scalars.count).banners, [.deletedAtSource])
        let fresh = doc(text, changes: .init(state: "new"))
        XCTAssertEqual(ReaderPresentation.resolve(target: ReaderTarget(episode: "ep_1"), doc: fresh,
                                                  textCount: scalars.count).banners, [], "a new source says nothing")
    }

    func testTheSentenceSaysWhatTheWashMeans() {
        XCTAssertEqual(Copy.Provenance.updated(parts: 1, removed: 0),
                       "Changed since Sleep last read it. The highlighted part is new.")
        XCTAssertEqual(Copy.Provenance.updated(parts: 3, removed: 1),
                       "Changed since Sleep last read it. The 3 highlighted parts are new; one part was taken out.")
        XCTAssertEqual(Copy.Provenance.updated(parts: 0, removed: 2),
                       "Changed since Sleep last read it. 2 parts were taken out.")
        XCTAssertEqual(Copy.Provenance.updated(parts: 0, removed: 0), "Changed since Sleep last read it.")
    }

    func testAnOlderBackendsDocumentDecodesWithNoChanges() throws {
        let old = try JSONDecoder().decode(EpisodeText.self, from: Data(#"{"episode":"ep_1","text":"x"}"#.utf8))
        XCTAssertNil(old.changes)
        let new = try JSONDecoder().decode(EpisodeText.self, from: Data(
            #"{"episode":"ep_1","text":"x","changes":{"state":"updated","changed":[[0,1]],"removed":["y"]}}"#.utf8))
        XCTAssertEqual(new.changes, EpisodeChanges(state: "updated", changed: [[0, 1]], removed: ["y"]))
    }
}
