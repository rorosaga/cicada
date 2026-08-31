import XCTest
@testable import CicadaApp

/// G71 §2 — guided credential entry for the two direct-API connectors. The
/// panel never sees a credential value coming back: the backend reports only
/// whether each field is present.
final class ConnectorSetupTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Decoding

    func testConnectorStatusDecodesFieldsWithoutValues() throws {
        let json = """
        {"id": "pinterest", "label": "Pinterest", "connected": false,
         "fields": [{"name": "PINTEREST_APP_ID", "label": "App ID",
                     "secret": false, "present": true},
                    {"name": "PINTEREST_APP_SECRET", "label": "App secret",
                     "secret": true, "present": false}],
         "lastSync": null, "lastError": null, "detail": null,
         "loginMode": "oauth"}
        """.data(using: .utf8)!
        let status = try JSONDecoder().decode(ConnectorStatus.self, from: json)
        XCTAssertEqual(status.fields.count, 2)
        XCTAssertTrue(status.fields[0].present)
        XCTAssertTrue(status.fields[1].secret)
        XCTAssertTrue(status.isOAuth)
    }

    func testOAuthConnectorWithSavedAppButNoTokenStillNeedsAuthorization() throws {
        let status = ConnectorStatus(
            id: "pinterest", label: "Pinterest", connected: false,
            fields: [ConnectorField(name: "PINTEREST_APP_ID", label: "App ID",
                                    secret: false, present: true),
                     ConnectorField(name: "PINTEREST_APP_SECRET", label: "App secret",
                                    secret: true, present: true)],
            lastSync: nil, lastError: nil, detail: nil, loginMode: "oauth")
        XCTAssertTrue(status.needsAuthorization)
    }

    func testCredentialConnectorNeverNeedsAuthorization() {
        let status = ConnectorStatus(
            id: "reddit", label: "Reddit", connected: false, fields: [],
            lastSync: nil, lastError: nil, detail: nil, loginMode: "credentials")
        XCTAssertFalse(status.needsAuthorization)
        XCTAssertFalse(status.isOAuth)
    }

    // MARK: - Copy

    func testStepLabelWalksTheUserThroughTheOAuthFlow() {
        let unsaved = ConnectorStatus(
            id: "pinterest", label: "Pinterest", connected: false,
            fields: [ConnectorField(name: "PINTEREST_APP_ID", label: "App ID",
                                    secret: false, present: false)],
            lastSync: nil, lastError: nil, detail: nil, loginMode: "oauth")
        XCTAssertEqual(ConnectorSetupState.stepLabel(unsaved), "Step 1 of 2 — save your app keys")

        let saved = ConnectorStatus(
            id: "pinterest", label: "Pinterest", connected: false,
            fields: [ConnectorField(name: "PINTEREST_APP_ID", label: "App ID",
                                    secret: false, present: true)],
            lastSync: nil, lastError: nil, detail: nil, loginMode: "oauth")
        XCTAssertEqual(ConnectorSetupState.stepLabel(saved),
                       "Step 2 of 2 — authorize in your browser")

        let connected = ConnectorStatus(
            id: "pinterest", label: "Pinterest", connected: true, fields: [],
            lastSync: "2026-08-30T10:00:00Z", lastError: nil, detail: nil, loginMode: "oauth")
        XCTAssertEqual(ConnectorSetupState.stepLabel(connected), "Connected")
    }

    func testSyncSummaryReportsEachOutcomeHonestly() {
        XCTAssertEqual(
            ConnectorSetupState.syncSummary(
                ConnectorSyncResult(status: "ok", reason: nil, new: 12, seen: 40, error: nil)),
            "12 new · 40 seen")
        XCTAssertEqual(
            ConnectorSetupState.syncSummary(
                ConnectorSyncResult(status: "ok", reason: nil, new: 0, seen: 40, error: nil)),
            "Nothing new · 40 seen")
        XCTAssertEqual(
            ConnectorSetupState.syncSummary(
                ConnectorSyncResult(status: "skipped", reason: "not connected",
                                    new: 0, seen: 0, error: nil)),
            "Skipped — not connected")
        XCTAssertEqual(
            ConnectorSetupState.syncSummary(
                ConnectorSyncResult(status: "error", reason: nil, new: 0, seen: 0,
                                    error: "RuntimeError: 429 rate limited")),
            "Sync failed — RuntimeError: 429 rate limited")
    }

    // MARK: - Transport

    func testSaveCredentialsPutsTheFieldsAndDecodesTheStatus() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "PUT")
            XCTAssertEqual(request.url?.path, "/sources/connectors/reddit/credentials")
            let body = """
            {"id": "reddit", "label": "Reddit", "connected": true, "fields": [],
             "lastSync": null, "lastError": null, "detail": null,
             "loginMode": "credentials"}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let api = APIClient(session: MockURLProtocol.makeSession())
        let status = try await api.saveConnectorCredentials(
            "reddit", fields: ["REDDIT_CLIENT_ID": "client-id-placeholder"])
        XCTAssertTrue(status.connected)
    }

    func testAuthorizeReturnsTheVendorUrl() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/sources/connectors/pinterest/authorize")
            let body = #"{"authorizeUrl": "https://www.pinterest.com/oauth/?x=1", "state": "s"}"#
                .data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let api = APIClient(session: MockURLProtocol.makeSession())
        let result = try await api.authorizeConnector("pinterest")
        XCTAssertEqual(result.authorizeUrl, "https://www.pinterest.com/oauth/?x=1")
    }
}
