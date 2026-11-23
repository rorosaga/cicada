import Foundation
import XCTest
@testable import CicadaApp

/// G245 — the `GET /sources/streams` wire as plan 2.1 states it, for every Sources test and render test that needs a
/// streams answer. Synthetic only (placeholders). Resolved from THIS file's own path, `ProjectFixtures`' rule:
/// …/Tests/CicadaAppTests/SourceStreamsFixture.swift → …/Tests/fixtures/sources-streams.json.
enum SourceStreamsFixture {
    static let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()   // CicadaAppTests
        .deletingLastPathComponent()   // Tests
        .appendingPathComponent("fixtures/sources-streams.json")

    static let data: Data = {
        // A missing fixture must fail loudly: a test over no streams passes vacuously.
        guard let data = try? Data(contentsOf: url) else { fatalError("missing \(url.path)") }
        return data
    }()

    static func load() throws -> SourceStreamsResponse {
        try JSONDecoder().decode(SourceStreamsResponse.self, from: data)
    }

    /// The clock the fixture's dates are read against: a few hours after `x.bookmarks`' last read.
    static let now = ISODate.parse("2026-11-24T12:00:00Z")!
}
