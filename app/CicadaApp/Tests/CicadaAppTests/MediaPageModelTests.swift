import XCTest
@testable import CicadaApp

/// ROR-117 / G43 (ruling 68) — an added recording, video or photo is a page. What the page decides before any player
/// exists: the wire it decodes, the line of facts, when a stamp seeks, that an empty section is not drawn, and how the
/// model that made the words is named where a page shows who contributed. Fixtures only; no file, no player.
final class MediaPageModelTests: XCTestCase {
    private let en = Locale(identifier: "en_US")
    private let today = ISODay(year: 2026, month: 11, day: 5)

    private func block(_ json: String) throws -> MediaBlock {
        try JSONDecoder().decode(MediaBlock.self, from: Data(json.utf8))
    }

    func testAFilePageDecodesWithNoLinkAndOlderBackendsDecodeWithoutTheKeys() throws {
        let file = try block(#"{"url":"","mediaType":"recording","kind":"file","fileId":"0123456789abcdef","durationS":65,"recordedAt":"2026-03-02T10:00:00+00:00"}"#)
        XCTAssertTrue(file.isFile)
        XCTAssertFalse(file.hasURL)
        XCTAssertEqual(file.fileId, "0123456789abcdef")
        let link = try block(#"{"url":"https://example.com/a","mediaType":"bookmark"}"#)
        XCTAssertFalse(link.isFile)
        XCTAssertNil(link.fileId)
        let noId = try block(#"{"url":"","mediaType":"recording","kind":"file"}"#)
        XCTAssertFalse(noId.isFile, "a file page without the store's id has nothing to play")
    }

    func testTheFactsAreKindLengthAndItsOwnDateAndNothingElse() throws {
        let rec = try block(#"{"url":"","mediaType":"recording","kind":"file","fileId":"0123456789abcdef","durationS":65,"recordedAt":"2026-03-02T10:00:00+00:00"}"#)
        XCTAssertEqual(MediaPageModel.facts(rec, today: today, locale: en), "Recording · 1:05 · Mar 2")
        let photo = try block(#"{"url":"","mediaType":"photo","kind":"file","fileId":"0123456789abcdef"}"#)
        XCTAssertEqual(MediaPageModel.facts(photo, today: today, locale: en), "Photo", "a photo has no length, an undated one no date")
        let hour = try block(#"{"url":"","mediaType":"video","kind":"file","fileId":"0123456789abcdef","durationS":3725,"recordedAt":"2025-12-30T08:00:00+00:00"}"#)
        XCTAssertEqual(MediaPageModel.facts(hour, today: today, locale: en), "Video · 1:02:05 · Dec 30, 2025")
    }

    func testAStampSeeksOnlyWhereAPlayerIs() {
        let url = URL(fileURLWithPath: "/tmp/x.m4a")
        XCTAssertTrue(MediaPageModel.canSeek(.play(url: url, kind: .audio, start: 0)))
        XCTAssertFalse(MediaPageModel.canSeek(.photo(url: url)))
        XCTAssertFalse(MediaPageModel.canSeek(.missing), "a file that is not on this Mac has no player to seek")
    }

    func testThePlayerAreaFitsTheKindAndASentenceNeedsLess() {
        let url = URL(fileURLWithPath: "/tmp/x")
        XCTAssertGreaterThan(MediaPageModel.playerHeight(.play(url: url, kind: .video, start: 0)),
                             MediaPageModel.playerHeight(.play(url: url, kind: .audio, start: 0)))
        XCTAssertLessThan(MediaPageModel.playerHeight(.missing), MediaPageModel.playerHeight(.photo(url: url)))
    }

    func testTheWordsDecodeAndAFileWithNoneDrawsNone() throws {
        let json = #"{"segments":[{"start":0,"end":4.5,"text":"Hello there."}],"transcribedBy":"Speech model A","language":"en","wordsBy":"the recording"}"#
        let words = try JSONDecoder().decode(FileTranscript.self, from: Data(json.utf8))
        XCTAssertEqual(words.segments, [.init(start: 0, end: 4.5, text: "Hello there.")])
        XCTAssertTrue(MediaPageModel.hasWords(words))
        XCTAssertFalse(MediaPageModel.hasWords(FileTranscript(segments: [], transcribedBy: nil, language: nil)))
        XCTAssertFalse(MediaPageModel.hasWords(nil))
    }

    func testAnEmptySectionIsNotDrawnAndASectionWithContentIs() {
        let empty = WikiArticle.build("## Summary\n\n## Why it matters\n")
        XCTAssertTrue(empty.rows.isEmpty, "the empty sections a recording's page starts with draw nothing (DR-81)")
        let filled = WikiArticle.build("## Why it matters\n\nBecause of the budget.\n")
        XCTAssertEqual(filled.rows.count, 2)
        let nested = WikiArticle.build("## Notes\n### Small\ntext")
        XCTAssertEqual(nested.rows.count, 3, "a ### under it is content")
        let fenced = WikiArticle.build("## Why it matters\n\n```claims\n[]\n```\n")
        XCTAssertTrue(fenced.rows.isEmpty, "only the claims fence under it: still nothing to draw")
    }

    func testTheTranscriberIsAContributorChipWithNoCountsAndWordsOfItsOwn() throws {
        let json = #"{"author":"Speech model A","kind":"model","provider":"other","claims":0,"commits":0,"models":[],"role":"transcribed"}"#
        let chip = try JSONDecoder().decode(ProvenanceContributor.self, from: Data(json.utf8))
        XCTAssertTrue(chip.transcribedTheWords)
        XCTAssertEqual(ProvenanceSummary.chipCount(chip), "transcript")
        XCTAssertNil(ProvenanceSummary.writersSentence(EntityProvenance(entityId: "a", contributors: [chip])),
                     "the transcriber did not write the page")
        let plain = ProvenanceContributor(author: "user", kind: "user", claims: 2)
        XCTAssertFalse(plain.transcribedTheWords)
        XCTAssertEqual(ProvenanceSummary.chipCount(plain), "2 beliefs")
    }

    func testTheSheetLinksToThePageOnlyOnceTheFileHasOne() throws {
        let with = try JSONDecoder().decode(AddedFile.self, from: Data(#"{"id":"0123456789abcdef","name":"Standup","kind":"audio","page":"file-standup"}"#.utf8))
        let without = try JSONDecoder().decode(AddedFile.self, from: Data(#"{"id":"0123456789abcdef","name":"Standup","kind":"audio"}"#.utf8))
        XCTAssertEqual(with.page, "file-standup")
        XCTAssertNil(without.page)
    }
}
