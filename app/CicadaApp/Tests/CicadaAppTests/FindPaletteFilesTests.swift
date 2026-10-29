import XCTest
@testable import CicadaApp

/// Files in the app (2026-10-29) — the find palette's Files group: a recording's words with where in it, a video's
/// kept frame with its own thumbnail or no mark at all, asked only by the hybrid pass, never a "More…" that fetches
/// nothing, and a hit that opens the file where this Mac last saw it.
@MainActor
final class FindPaletteFilesTests: XCTestCase {
    static let wire = """
    {"results": [
      {"id": "0123456789abcdef@125", "name": "team sync.m4a", "type": "audio", "status": "active", "confidence": 0,
       "score": 0.21, "snippet": "We went over the budget for the quarter.", "kind": "file", "snippetOffsets": [],
       "matchedField": "semantic", "subtitle": "the recording's words, at 2:05", "fileId": "0123456789abcdef",
       "atSeconds": 125.0, "endSeconds": 140.0},
      {"id": "frame:fedcba9876543210@63000", "name": "talk.mov at 1:03", "type": "image", "status": "active",
       "confidence": 0, "score": 0.12, "snippet": "", "kind": "image", "matchedField": "semantic",
       "imageSource": "frame", "fileId": "fedcba9876543210", "atSeconds": 63.0,
       "thumbnail": "/files/fedcba9876543210/frames/63000"},
      {"id": "frame:fedcba9876543210@9000", "name": "talk.mov at 0:09", "type": "image", "status": "active",
       "confidence": 0, "score": 0.1, "snippet": "", "kind": "image", "matchedField": "semantic",
       "imageSource": "frame", "fileId": "fedcba9876543210", "atSeconds": 9.0},
      {"id": "look:a-look", "name": "A look", "type": "image", "status": "active", "confidence": 0, "score": 0.3,
       "snippet": "", "kind": "image", "matchedField": "semantic", "imageSource": "look", "thumbnail": "/design/a/image"}
    ], "totals": {}, "mode": "hybrid", "indexState": "ready"}
    """

    private func rows() -> [FindRow] {
        FindServerRows.rows(FakeFindSearch.decode(Self.wire), query: "budget", context: .init())
    }

    func testARecordingReadsAsTheRecordingsWordsWithWhereInIt() throws {
        let row = try XCTUnwrap(rows().first { $0.key.kind == .file && $0.mark == .symbol("waveform") })
        XCTAssertEqual(row.group, .files)
        XCTAssertEqual(row.title, "team sync.m4a")
        XCTAssertEqual(row.detail, "the recording's words, at 2:05", "never the person's words")
        XCTAssertEqual(row.snippet, "We went over the budget for the quarter.")
        XCTAssertNil(row.speaker, "no \"You said\": nobody in particular said it")
        XCTAssertEqual(row.badge, "Recording")
        XCTAssertEqual(row.destination, .addedFile(id: "0123456789abcdef", at: 125))
        XCTAssertEqual(row.secondary, .revealAddedFile(id: "0123456789abcdef"))
        XCTAssertEqual(FindRowText.primaryVerb(row.destination), "Open file")
        XCTAssertEqual(FindRowText.secondaryVerb(row.secondary), "Show in Finder")
        XCTAssertTrue(FindRowText.accessibilityLabel(row).hasPrefix("Recording, team sync.m4a, the recording's words"))
    }

    func testAFrameShowsItsOwnThumbnailOrNoMarkNeverAStandIn() throws {
        let frames = rows().filter { $0.badge == "Video" }
        XCTAssertEqual(frames.count, 2)
        XCTAssertEqual(frames[0].mark, .still(path: "/files/fedcba9876543210/frames/63000"))
        XCTAssertEqual(frames[0].title, "talk.mov at 1:03")
        XCTAssertEqual(frames[0].detail, Copy.findFrameDetail)
        XCTAssertEqual(frames[1].mark, .blank, "no thumbnail on this Mac: no mark at all (#512)")
        XCTAssertEqual(FindRowText.kindLabel(frames[0]), "Video frame")
        XCTAssertFalse(rows().contains { $0.key.id == "look:a-look" }, "only a video's frames join Files")
    }

    func testTheGroupCountsWhatItHoldsAndNeverAsksForMore() {
        let response = FakeFindSearch.decode(Self.wire)
        let built = FindServerRows.rows(response, query: "budget", context: .init())
        let totals = FindServerRows.totals(response, rows: built, kinds: FindServerRows.hybridKinds, perKind: 8)
        XCTAssertEqual(totals[.files], .exact(3))
        XCTAssertNil(FindServerRows.kind(for: .files), "no prefix pass for files: expanding fetches nothing")
        XCTAssertFalse(FindServerRows.kinds.contains("file"), "the prefix pass never asks for files")
        XCTAssertTrue(FindGroupID.files > .sources && FindGroupID.files < .inbox)
        XCTAssertEqual(FindGroupID.files.title, "Files")
    }

    private func model(_ api: FakeFindSearch) -> FindPaletteModel {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let model = FindPaletteModel(store: store, api: api, sleeper: { _ in try Task.checkCancellation() })
        model.install(QuickIndex.build(FindFixtures.inputs()))
        return model
    }

    func testOnlyTheHybridPassAsksForFilesAndTheGroupAppears() async {
        let api = FakeFindSearch()
        api.response = FakeFindSearch.decode(Self.wire)
        let m = model(api)
        m.setQuery("budget")
        await m.serverTask?.value
        XCTAssertEqual(api.calls.map(\.mode), ["prefix", "hybrid"])
        XCTAssertEqual(api.calls[0].kinds, FindServerRows.kinds)
        XCTAssertEqual(api.calls[1].kinds, FindServerRows.hybridKinds)
        let files = m.sections.first { $0.group == .files }
        XCTAssertEqual(files?.rows.count, 3)
        XCTAssertNil(files?.more, "three rows, all shown: no Show all, no More…")
    }

    func testAnAddedFileIsOpenedWhereThisMacLastSawItAndAMovedOneSaysSo() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "files-places-\(UUID().uuidString)"))
        let places = MediaFilePlaces(defaults: defaults)
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("memo-\(UUID().uuidString).m4a")
        try Data("x".utf8).write(to: file)
        places.remember("0123456789abcdef", file)
        XCTAssertEqual(places.url(of: "0123456789abcdef")?.path, file.path)
        try FileManager.default.removeItem(at: file)
        XCTAssertNil(places.url(of: "0123456789abcdef"), "moved or deleted: nothing to open")
        XCTAssertNil(places.url(of: "ffffffffffffffff"))
    }

    /// The palette's open and type cost with a Files group in the hybrid answer — the merge a keystroke pays when the
    /// hybrid pass lands (the local tier is unchanged). Prints p50/p95 with and without the Files hits.
    func testBenchOpenAndTypeWithAndWithoutFiles() async {
        func measure(_ response: MemorySearchResponse) async -> (Double, Double) {
            var samples: [Double] = []
            for i in 0..<60 {
                let api = FakeFindSearch()
                api.response = response
                let m = model(api)
                let started = DispatchTime.now().uptimeNanoseconds
                m.present()
                m.setQuery(i % 2 == 0 ? "alpha" : "alpha p")
                await m.serverTask?.value
                _ = m.sections
                samples.append(Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000)
            }
            samples.sort()
            return (samples[samples.count / 2], samples[Int(Double(samples.count - 1) * 0.95)])
        }
        // The same answer twice — once as it was, once with the Files hits added — so the delta is the Files group.
        let base = FakeFindSearch.decode(FindServerTests.wire)
        let files = FakeFindSearch.decode(Self.wire)
        let without = await measure(base)
        let withFiles = await measure(MemorySearchResponse(results: base.results + files.results, totals: base.totals,
                                                           mode: "hybrid", indexState: "ready"))
        print("FILES_BENCH open+type+both passes: without Files p50 \(String(format: "%.2f", without.0)) ms, "
              + "p95 \(String(format: "%.2f", without.1)) ms; with Files p50 \(String(format: "%.2f", withFiles.0)) ms, "
              + "p95 \(String(format: "%.2f", withFiles.1)) ms")
        XCTAssertLessThan(withFiles.1, 300, "the debug budget QuickIndexLatencyTests uses")
    }
}
