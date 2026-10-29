import XCTest
import SwiftUI
import MapKit
@testable import CicadaApp

/// Part B of the page redesign (ruling 48 parts 5, 6 and 14; DR-77): the History tab's rows from the backend's own
/// `api/tests/fixtures/page_history.json`, its filters and words; the place map's phases and its rail (a private place
/// is never looked up on its own; nothing on the card's first layout waits on the map).
final class PageHistoryTests: XCTestCase {
    private static func rows() throws -> [EntityHistoryEntry] {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let file = root.appendingPathComponent("api/tests/fixtures/page_history.json")
        let object = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any]
        let data = try JSONSerialization.data(withJSONObject: object?["rows"] ?? [])
        return try JSONDecoder().decode([EntityHistoryEntry].self, from: data)
    }

    // MARK: History

    func testTheBackendsRowsDecodeWithBucketTimeAndSummary() throws {
        let rows = try Self.rows()
        XCTAssertEqual(rows.map(\.bucket), ["you", "sleep", "agents", "upkeep", "sleep"])
        XCTAssertEqual(rows[1].summary?.plusClaims, 3)
        XCTAssertEqual(rows[1].summary?.lines.count, 3)
        XCTAssertNotNil(HistoryRowWords.instant(rows[0]))
    }

    func testAllLeavesUpkeepOutAndEachTabIsItsBucket() throws {
        let rows = try Self.rows()
        XCTAssertEqual(HistoryBucket.filter(rows, nil).count, 4)
        XCTAssertEqual(HistoryBucket.filter(rows, .upkeep).map(\.trigger), ["sleep/decay"])
        XCTAssertEqual(HistoryBucket.filter(rows, .sleep).count, 2)
        let counts = HistoryBucket.counts(rows)
        XCTAssertEqual(counts[nil], 4)
        XCTAssertEqual(counts[Optional(HistoryBucket.you)], 1)
        XCTAssertEqual(counts[Optional(HistoryBucket.agents)], 1)
    }

    func testAnOlderBackendsRowGetsTheSameBucketFromItsDoor() throws {
        var row = try Self.rows()[2]
        row.bucket = ""
        XCTAssertEqual(HistoryBucket.of(row), .agents)
        row.via = "unknown"
        XCTAssertEqual(HistoryBucket.of(row), .agents, "a harness author is an agent")
    }

    func testEachRowSaysWhatHappenedAsASentence() throws {
        let rows = try Self.rows()
        XCTAssertEqual(HistoryRowWords.sentence(rows[0]), "You updated the page")
        XCTAssertEqual(HistoryRowWords.sentence(rows[1]), "\(ModelNames.display("claude-sonnet-5")) added 3 beliefs")
        XCTAssertEqual(HistoryRowWords.sentence(rows[3]), Copy.Graph.historyDecay)
        XCTAssertEqual(HistoryRowWords.sentence(rows[4]), "\(ModelNames.display("claude-haiku-4-5")) wrote this page")
        XCTAssertEqual(HistoryRowWords.detail(rows[1]), "Read 2 conversations · +3 beliefs · 1 ended")
        XCTAssertTrue(HistoryRowWords.changed(rows[1]).contains("+3 beliefs"))
        XCTAssertTrue(HistoryRowWords.changed(rows[0]).contains("how fast it fades"))
    }

    /// The person's rows wear the owner page's picture (G146's precedence through `EntityPicture`); with no owner page
    /// named yet there is no face to borrow, and the contributor avatar stands in.
    func testThePersonsRowsWearTheOwnersPage() throws {
        let decode = { (json: String) in try JSONDecoder().decode(GraphNode.self, from: Data(json.utf8)) }
        let owner = try decode(#"{"id":"bob-example","name":"Bob Example","type":"person","status":"active","confidence":0.9,"isOwner":true}"#)
        let other = try decode(#"{"id":"alpha-project","name":"Alpha Project","type":"project","status":"active","confidence":0.5}"#)
        XCTAssertEqual(HistoryWriterMark.ownerNode([other, owner])?.id, "bob-example")
        XCTAssertNil(HistoryWriterMark.ownerNode([other]))
        XCTAssertNil(HistoryWriterMark.ownerNode(nil))
    }

    func testThePagerAppendsOlderPagesOnce() throws {
        let rows = try Self.rows()
        var pager = HistoryPager()
        pager.received(Array(rows.prefix(3)), more: true)
        XCTAssertEqual(pager.nextSkip, 3)
        pager.received(Array(rows.suffix(3)), more: false)
        XCTAssertEqual(pager.rows.count, 5, "a commit served twice is shown once")
        XCTAssertFalse(pager.hasMore)
    }

    @MainActor
    func testTheTabReadsOnlyWhenShownAndOnePage() async throws {
        let rows = try Self.rows()
        var calls: [Int] = []
        let view = EntityHistoryView(entityId: "alpha-place", load: { _, skip in
            calls.append(skip)
            return (rows, false)
        })
        XCTAssertTrue(calls.isEmpty, "building the view reads nothing")
        let host = NSHostingView(rootView: view.frame(width: 700, height: 600).environment(Store()))
        host.layoutSubtreeIfNeeded()
        for _ in 0..<20 where calls.isEmpty { try await Task.sleep(for: .milliseconds(20)) }
        XCTAssertEqual(calls, [0])
    }

    // MARK: Places

    private final class Recorder: @unchecked Sendable {
        var loads = 0
        var located: [String] = []
        var stored: [(Double?, Double?, String)] = []
    }

    private struct FixedGeocoder: PlaceGeocoding {
        let recorder: Recorder
        let answer: CLLocationCoordinate2D?
        func locate(_ query: String) async throws -> CLLocationCoordinate2D? {
            recorder.located.append(query)
            return answer
        }
    }

    private func services(_ state: PlaceState, _ r: Recorder, answer: CLLocationCoordinate2D?) -> PlaceServices {
        PlaceServices(
            load: { _ in r.loads += 1; return state },
            store: { id, lat, lon, by in
                r.stored.append((lat, lon, by))
                return PlaceState(entityId: id, coordinates: lat.map {
                    PageBlocks.Coordinates(lat: $0, lon: lon ?? 0, label: "Example Park", source: "page", by: by)
                })
            },
            remove: { id in PlaceState(entityId: id) },
            unplaced: { [] },
            geocoder: FixedGeocoder(recorder: r, answer: answer),
            still: { _ in NSImage(size: NSSize(width: 8, height: 8)) })
    }

    private static func place(raw: String = "---\nname: Example Park\ntype: location\n---\nA park.\n") throws -> Entity {
        let object: [String: Any] = ["id": "example-park", "name": "Example Park", "type": "location", "status": "active",
                                     "confidence": 1, "created": "2024-01-01", "lastReferenced": "2024-01-01",
                                     "decayRate": 0, "markdownContent": "A park.", "rawMarkdown": raw]
        return try JSONDecoder().decode(Entity.self, from: JSONSerialization.data(withJSONObject: object))
    }

    func testThePhaseStartsFromWhatTheCardServed() {
        XCTAssertEqual(PlacePhase.initial(nil), .reading)
        let c = PageBlocks.Coordinates(lat: 1, lon: 2, label: "x", source: "page", by: nil)
        XCTAssertEqual(PlacePhase.initial(c), .placed(c))
    }

    @MainActor
    func testAPrivatePlaceIsNeverLookedUpOnItsOwn() async throws {
        PlaceBackfill.resetForTests()
        let r = Recorder()
        let state = PlaceState(entityId: "example-park",
                               geocode: .init(allowed: false, reason: "home", query: "Example Park"))
        let host = NSHostingView(rootView: PlaceMap(entity: try Self.place(),
                                                    services: services(state, r, answer: nil)).frame(width: 600))
        host.layoutSubtreeIfNeeded()
        for _ in 0..<20 where r.loads == 0 { try await Task.sleep(for: .milliseconds(20)) }
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(r.loads, 1)
        XCTAssertTrue(r.located.isEmpty, "a private place waits for the person's click")
        XCTAssertTrue(r.stored.isEmpty)
    }

    @MainActor
    func testAPublicPlaceIsPlacedOnceByTheMacsGeocoder() async throws {
        PlaceBackfill.resetForTests()
        let r = Recorder()
        let state = PlaceState(entityId: "example-park",
                               geocode: .init(allowed: true, reason: "public_place", query: "Example Park, Example City"))
        let host = NSHostingView(rootView: PlaceMap(entity: try Self.place(),
                                                    services: services(state, r, answer: CLLocationCoordinate2D(
                                                        latitude: 40.41, longitude: -3.70))).frame(width: 600))
        host.layoutSubtreeIfNeeded()
        for _ in 0..<40 where r.stored.isEmpty { try await Task.sleep(for: .milliseconds(20)) }
        XCTAssertEqual(r.located, ["Example Park, Example City"])
        XCTAssertEqual(r.stored.first?.2, "geocoder")
        XCTAssertEqual(r.stored.first?.0, 40.41)
    }

    /// No map work blocks the card: the first layout of a place page's map is the placeholder alone — the place read,
    /// the geocoder and the snapshot all start after it, off the layout pass. Measured: a first layout with the map
    /// costs about what one without it does (budget 50 ms over the bare frame, basis: this Mac, debug build).
    @MainActor
    func testTheMapNeverBlocksTheFirstLayout() throws {
        let r = Recorder()
        let state = PlaceState(entityId: "example-park")
        func firstLayout<V: View>(_ v: V) -> Double {
            let host = NSHostingView(rootView: v.frame(width: 600, height: 300))
            let t = CFAbsoluteTimeGetCurrent()
            host.layoutSubtreeIfNeeded()
            return (CFAbsoluteTimeGetCurrent() - t) * 1000
        }
        _ = firstLayout(Color.clear)   // warm SwiftUI itself
        let bare = (0..<5).map { _ in firstLayout(Color.clear) }.sorted()[2]
        let withMap = try (0..<5).map { _ in
            firstLayout(PlaceMap(entity: try Self.place(), services: services(state, r, answer: nil)))
        }.sorted()[2]
        XCTAssertEqual(r.loads, 0, "the place is read after the first layout, never inside it")
        XCTAssertLessThan(withMap - bare, 50, "first layout with the map \(withMap) ms vs \(bare) ms bare")
    }
}
