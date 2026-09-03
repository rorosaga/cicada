import XCTest
@testable import CicadaApp

final class VersionVectorTests: XCTestCase {
    func testNilOldMeansEverything() {
        let v = VersionVector(version: "1", components: ["entities": "a"])
        XCTAssertEqual(v.changedDomains(since: nil), Set(SyncDomain.allCases))
    }
    func testMapsComponents() {
        let old = VersionVector(version: "1", components: ["entities": "a", "inbox": "1", "bank": "x", "sleep": "idle:"])
        let new = VersionVector(version: "2", components: ["entities": "b", "inbox": "1", "bank": "x", "sleep": "idle:"])
        XCTAssertEqual(new.changedDomains(since: old), [.graph, .contributors, .origins, .sourcesOverview, .inbox])
        let bank = VersionVector(version: "3", components: ["entities": "b", "inbox": "1", "bank": "y", "sleep": "idle:"])
        XCTAssertEqual(bank.changedDomains(since: new), Set(SyncDomain.allCases))
        XCTAssertEqual(new.changedDomains(since: new), [])
    }

    /// G97 / G115 R3 — `GET /inbox` embeds entity- and episode-derived context
    /// (the cause excerpt, the entity type), so its ETag is computed over
    /// `inbox`+`entities`+`episodes` on the server. The client half: a bump to
    /// either component must refresh `.inbox`, or `SnapshotCache` keeps stale
    /// context until the inbox itself moves.
    func testEntitiesAndEpisodesRefreshTheInbox() {
        let old = VersionVector(version: "1", components: ["entities": "a", "episodes": "1:1", "bank": "x"])
        let ent = VersionVector(version: "2", components: ["entities": "b", "episodes": "1:1", "bank": "x"])
        XCTAssertTrue(ent.changedDomains(since: old).contains(.inbox))
        let eps = VersionVector(version: "3", components: ["entities": "b", "episodes": "2:2", "bank": "x"])
        XCTAssertTrue(eps.changedDomains(since: ent).contains(.inbox))
    }

    /// The logo cache lives outside the memory bank, so a Sleep warm-up or an
    /// on-demand fetch bumps only the `logos` component — and `/graph` is the
    /// only payload carrying `hasLogo`.
    func testLogosComponentRefreshesTheGraph() {
        let old = VersionVector(version: "1", components: ["logos": "a", "bank": "x"])
        let new = VersionVector(version: "2", components: ["logos": "b", "bank": "x"])
        XCTAssertEqual(new.changedDomains(since: old), [.graph])
    }

    /// `sync_service.components` folds `feeds.yaml` and `calendars.yaml` into
    /// the `sources` component, so a `sources` bump must refresh the calendar
    /// list too — subscribing to an ICS feed changes nothing else. G124 R7:
    /// the Sources overview rides it as well (its ETag covers `sync_state.json`
    /// and the registries, which live in this component).
    func testSourcesComponentAlsoRefreshesFeedsAndCalendars() {
        let base = ["sources": "a", "bank": "x"]
        let old = VersionVector(version: "1", components: base)
        let new = VersionVector(version: "2", components: ["sources": "b", "bank": "x"])
        XCTAssertEqual(new.changedDomains(since: old), [.sources, .feeds, .calendars, .channels, .sourcesOverview])
    }

    /// `sync_service.components`'s `"telemetry"` key tracks the ledger's
    /// current `events-YYYY-MM.jsonl` mtime — a bump there must refresh the
    /// usage dashboard's `consumption` domain (G51).
    func testTelemetryComponentRefreshesConsumption() {
        let old = VersionVector(version: "1", components: ["telemetry": "a", "bank": "x"])
        let new = VersionVector(version: "2", components: ["telemetry": "b", "bank": "x"])
        XCTAssertEqual(new.changedDomains(since: old), [.consumption])
    }
}
