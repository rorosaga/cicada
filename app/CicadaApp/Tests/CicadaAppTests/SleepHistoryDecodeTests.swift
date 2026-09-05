import XCTest
@testable import CicadaApp

/// G125 Task 4 — decode tolerance for the models the Sleep page's history
/// card and schedule-mode picker read. An older backend predates every field
/// beyond the original four on `SleepHistoryEntry` (and `SleepStatusResponse`'s
/// `queueByOrigin`/`readByOrigin`, and `EpisodeQueueItem`'s `chars`) — every
/// one of them must default rather than fail the whole decode.
final class SleepHistoryDecodeTests: XCTestCase {

    func testOlderHistoryPayloadDecodesWithDefaults() throws {
        let json = """
        {"commitHash":"abc","date":"2026-09-01","message":"Sleep cycle 2026-09-01","filesChanged":[]}
        """.data(using: .utf8)!
        let e = try JSONDecoder().decode(SleepHistoryEntry.self, from: json)
        XCTAssertEqual(e.kind, "sleep")
        XCTAssertNil(e.durationMs)
        XCTAssertEqual(e.authors, [])
        XCTAssertNil(e.engine)
        XCTAssertEqual(e.entitiesCreated, 0)
        XCTAssertEqual(e.id, "abc")
    }

    func testFullHistoryPayloadDecodesEveryField() throws {
        let json = """
        {"commitHash":"abc123","date":"2026-09-01","message":"Sleep cycle 2026-09-01",
         "filesChanged":["entities/alpha-project.md"],"engine":"litellm","kind":"sleep",
         "entitiesCreated":1,"entitiesUpdated":2,"episodes":2,"sessions":2,
         "authors":["gpt-5.4-mini"],"durationMs":4200}
        """.data(using: .utf8)!
        let e = try JSONDecoder().decode(SleepHistoryEntry.self, from: json)
        XCTAssertEqual(e.engine, "litellm")
        XCTAssertEqual(e.entitiesCreated, 1)
        XCTAssertEqual(e.entitiesUpdated, 2)
        XCTAssertEqual(e.episodes, 2)
        XCTAssertEqual(e.sessions, 2)
        XCTAssertEqual(e.authors, ["gpt-5.4-mini"])
        XCTAssertEqual(e.durationMs, 4200)
    }

    func testSleepCycleDetailDecodesEpisodesByOriginAndEntities() throws {
        let json = """
        {"commitHash":"abc123","date":"2026-09-01","message":"Sleep cycle 2026-09-01",
         "filesChanged":[],"kind":"sleep",
         "entities":[{"id":"alpha-project","action":"created","trigger":"sleep/extraction","sourceEpisode":"ep_2026-09-01_001"}],
         "truncated":false,"episodesByOrigin":{"claude-code":1,"safari-tab":1},"inboxChanges":1}
        """.data(using: .utf8)!
        let d = try JSONDecoder().decode(SleepCycleDetail.self, from: json)
        XCTAssertEqual(d.episodesByOrigin, ["claude-code": 1, "safari-tab": 1])
        XCTAssertEqual(d.entities.first?.id, "alpha-project")
        XCTAssertEqual(d.entities.first?.sourceEpisode, "ep_2026-09-01_001")
        XCTAssertFalse(d.truncated)
        XCTAssertEqual(d.inboxChanges, 1)
    }

    /// A cycle detail's `entities[i].sourceEpisode` is absent for a decay-only
    /// manifest line (`source: n/a` server-side) — must decode to `nil`, not
    /// throw.
    func testSleepCycleEntityToleratesMissingSourceEpisode() throws {
        let json = #"{"id":"old-thing","action":"updated","trigger":"sleep/decay"}"#.data(using: .utf8)!
        let e = try JSONDecoder().decode(SleepCycleEntity.self, from: json)
        XCTAssertNil(e.sourceEpisode)
    }

    func testSleepStatusResponseWithoutQueueByOriginDecodesToEmptyDicts() throws {
        let json = """
        {"status":"idle","stage":0,"totalStages":5,"episodesTotal":0,"entitiesCreated":0,
         "entitiesUpdated":0,"relationshipsCreated":0,"skillsDetected":0}
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(SleepStatusResponse.self, from: json)
        XCTAssertEqual(s.queueByOrigin, [:])
        XCTAssertEqual(s.readByOrigin, [:])
    }

    func testSleepStatusResponseDecodesQueueByOriginWhenPresent() throws {
        let json = """
        {"status":"running","stage":0,"totalStages":5,"episodesTotal":3,"entitiesCreated":0,
         "entitiesUpdated":0,"relationshipsCreated":0,"skillsDetected":0,
         "queueByOrigin":{"claude-code":2,"safari-tab":1},"readByOrigin":{"claude-code":1}}
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(SleepStatusResponse.self, from: json)
        XCTAssertEqual(s.queueByOrigin, ["claude-code": 2, "safari-tab": 1])
        XCTAssertEqual(s.readByOrigin, ["claude-code": 1])
    }

    func testEpisodeQueueItemWithoutCharsDefaultsToZero() throws {
        let json = """
        {"id":"ep_2026-09-01_001","timestamp":"2026-09-01T01:00:00Z","source":"test",
         "preview":"…","processed":false}
        """.data(using: .utf8)!
        let item = try JSONDecoder().decode(EpisodeQueueItem.self, from: json)
        XCTAssertEqual(item.chars, 0)
        XCTAssertEqual(item.origin, "unknown")
    }

    func testEpisodeQueueItemDecodesCharsWhenPresent() throws {
        let json = """
        {"id":"ep_2026-09-01_001","timestamp":"2026-09-01T01:00:00Z","source":"test",
         "origin":"telegram","preview":"…","chars":12,"processed":false}
        """.data(using: .utf8)!
        let item = try JSONDecoder().decode(EpisodeQueueItem.self, from: json)
        XCTAssertEqual(item.chars, 12)
    }

    /// `SleepEventPayload`'s two new SSE fields (G125 R3) are optional and
    /// `nil`-tolerant, same posture as every other field on this type.
    func testSleepEventPayloadDecodesQueueAndReadByOriginWhenPresent() throws {
        let json = """
        {"status":"running","stage":0,"totalStages":5,"queueByOrigin":{"safari-tab":300},"readByOrigin":{"safari-tab":1}}
        """.data(using: .utf8)!
        let p = try JSONDecoder().decode(SleepEventPayload.self, from: json)
        XCTAssertEqual(p.queueByOrigin, ["safari-tab": 300])
        XCTAssertEqual(p.readByOrigin, ["safari-tab": 1])
    }

    func testSleepEventPayloadWithoutQueueByOriginDecodesToNil() throws {
        let json = #"{"status":"idle","stage":0,"totalStages":5}"#.data(using: .utf8)!
        let p = try JSONDecoder().decode(SleepEventPayload.self, from: json)
        XCTAssertNil(p.queueByOrigin)
        XCTAssertNil(p.readByOrigin)
    }
}
