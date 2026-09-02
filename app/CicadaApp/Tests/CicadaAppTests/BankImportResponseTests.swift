import XCTest
@testable import CicadaApp

/// G87 / Wave-1 1.6 — `POST /banks/{name}/import` now reports whether the
/// target bank is the one Sleep actually consolidates, so the app can branch
/// its toast on the backend's authoritative answer instead of re-deriving it
/// client-side from (possibly stale) roster state.
final class BankImportResponseTests: XCTestCase {

    private func decode(_ json: String) throws -> BankImportResponse {
        try JSONDecoder().decode(BankImportResponse.self, from: Data(json.utf8))
    }

    func testDecodesActiveTrue() throws {
        let resp = try decode("""
        {"episodesStaged":2,"episodesUpdated":0,"duplicatesSkipped":0,
         "format":"claude","dateRange":{"from":"2025-11-03","to":"2026-02-24"},
         "active":true}
        """)
        XCTAssertTrue(resp.active)
    }

    func testDecodesActiveFalse() throws {
        let resp = try decode("""
        {"episodesStaged":2,"episodesUpdated":0,"duplicatesSkipped":0,
         "format":"claude","dateRange":null,"active":false}
        """)
        XCTAssertFalse(resp.active)
    }

    /// A legacy backend that hasn't shipped this field yet must not read as
    /// "not active" — that would wrongly warn on every import.
    func testMissingActiveDefaultsToTrue() throws {
        let resp = try decode("""
        {"episodesStaged":1,"episodesUpdated":0,"duplicatesSkipped":0,
         "format":"claude","dateRange":null}
        """)
        XCTAssertTrue(resp.active)
    }
}
