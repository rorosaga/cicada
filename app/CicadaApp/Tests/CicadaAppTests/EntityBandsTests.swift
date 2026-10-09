import XCTest
@testable import CicadaApp

/// G180 parity — the entity card's bands are served by the backend (`api/services/entity_bands.py`, `bands` on
/// `GET /entities/{id}`); the app's `EntityHeaderWords` / `FadeWords` twin reads the SAME table,
/// `api/tests/fixtures/entity_bands.json`. Move a threshold on one side only and the other goes red.
final class EntityBandsTests: XCTestCase {
    private struct Fixture: Decodable {
        struct LastMentioned: Decodable {
            let today: String
            let cases: [[String?]]
        }
        let confidence: [[Band]]
        let fadePace: [[Band]]
        let lastMentioned: LastMentioned
    }

    /// A row is `[number, band]`.
    private enum Band: Decodable {
        case number(Double), word(String)
        init(from decoder: Decoder) throws {
            let c = try decoder.singleValueContainer()
            if let d = try? c.decode(Double.self) { self = .number(d) } else { self = .word(try c.decode(String.self)) }
        }
        var number: Double? { if case let .number(d) = self { d } else { nil } }
        var word: String? { if case let .word(w) = self { w } else { nil } }
    }

    private func fixture() throws -> Fixture {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/entity_bands.json")
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: file))
    }

    private static let confidenceWords = ["very": "very confident", "fairly": "fairly confident",
                                          "unsure": "unsure", "doubtful": "doubtful"]

    private static func band(_ pace: FadeWords.Pace) -> String {
        switch pace {
        case .never: "never"
        case .verySlowly: "very_slowly"
        case .slowly: "slowly"
        case .usual: "usual"
        case .quickly: "quickly"
        }
    }

    func testConfidenceWordsFollowTheServersBands() throws {
        let rows = try fixture().confidence
        XCTAssertGreaterThanOrEqual(rows.count, 5)
        for row in rows {
            let value = try XCTUnwrap(row[0].number), band = try XCTUnwrap(row[1].word)
            XCTAssertEqual(EntityHeaderWords.confidence(value), Self.confidenceWords[band], "\(value)")
        }
    }

    func testFadePaceFollowsTheServersBands() throws {
        let rows = try fixture().fadePace
        XCTAssertGreaterThanOrEqual(rows.count, 5)
        for row in rows {
            let rate = try XCTUnwrap(row[0].number), band = try XCTUnwrap(row[1].word)
            XCTAssertEqual(Self.band(FadeWords.pace(ratePerWeek: rate)), band, "\(rate)")
        }
    }

    func testTheOldDayFollowsTheServersRule() throws {
        let table = try fixture().lastMentioned
        let today = try XCTUnwrap(ISODay(table.today))
        XCTAssertGreaterThanOrEqual(table.cases.count, 5)
        for row in table.cases {
            let raw = row[0], expected = row[1]
            XCTAssertEqual(EntityHeaderWords.oldDay(raw, today: today)?.description, expected, raw ?? "nil")
        }
    }
}
