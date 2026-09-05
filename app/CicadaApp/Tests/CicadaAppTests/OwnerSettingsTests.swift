import XCTest
@testable import CicadaApp

/// G117 — `OwnerSettings` mirrors the backend's `OwnerSettingsResponse`
/// (`api/models/schemas.py`). Decode-tolerance rail: an older payload
/// missing `handle`/`email` must still decode rather than fail the whole
/// response.
final class OwnerSettingsTests: XCTestCase {
    func testDecodesAnOlderPayloadMissingHandleAndEmail() throws {
        let json = #"{"name":"Bob Example","observer":"bob-example","entityId":"bob-example"}"#
        let decoded = try JSONDecoder().decode(OwnerSettings.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.name, "Bob Example")
        XCTAssertNil(decoded.handle)
        XCTAssertNil(decoded.email)
        XCTAssertEqual(decoded.observer, "bob-example")
        XCTAssertEqual(decoded.entityId, "bob-example")
    }

    func testDecodesAFullPayload() throws {
        let json = #"""
        {"name":"Bob Example","handle":"@bob","email":"bob@example.com",
         "observer":"bob-example","entityId":"bob-example"}
        """#
        let decoded = try JSONDecoder().decode(OwnerSettings.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.handle, "@bob")
        XCTAssertEqual(decoded.email, "bob@example.com")
    }
}
