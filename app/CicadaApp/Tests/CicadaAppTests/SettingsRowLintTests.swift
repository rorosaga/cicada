import XCTest
@testable import CicadaApp

/// Design §2.6 — every static row the index names is rendered by exactly one
/// view, or a search would land on nothing (indexed but deleted) or on the
/// wrong one (rendered twice).
final class SettingsRowLintTests: XCTestCase {
    static let scanned = ["/Views/Settings/", "/Views/Connect/", "/Views/Connections/"]

    func testEveryStaticRowIsRenderedExactlyOnce() throws {
        let files = try ThemeTokenTests.swiftSources().filter { f in Self.scanned.contains { f.path.contains($0) } }
        XCTAssertFalse(files.isEmpty)
        let texts = try files.map { try String(contentsOf: $0, encoding: .utf8) }
        for entry in SettingsIndex.staticEntries where entry.anchor == entry.id && !entry.id.rawValue.contains(":") {
            let name = entry.id.rawValue
            let needles = ["SettingsRow(.\(name),", ".settingsRow(.\(name))"]
            let count = texts.reduce(0) { total, text in
                total + needles.reduce(0) { $0 + text.components(separatedBy: $1).count - 1 }
            }
            XCTAssertEqual(count, 1, "\(name) is indexed but rendered \(count) times")
        }
    }

    func testStaticIdsAreBareCamelCaseSoTheLintCanSpellThem() {
        for id in SettingsIndex.staticIDs where !id.rawValue.contains(":") {
            XCTAssertNotNil(id.rawValue.range(of: "^[a-z][A-Za-z]+$", options: .regularExpression), id.rawValue)
        }
    }
}
