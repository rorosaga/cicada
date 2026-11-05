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

    /// Ruling 47 tier 2: a token connector says what it reads and where the token comes from; an older backend's
    /// payload (no `reads`) still decodes.
    func testATokenConnectorDecodesWhatItReadsAndAsksForTheToken() throws {
        let json = """
        {"id": "notion-api", "label": "Notion", "connected": false,
         "fields": [{"name": "CICADA_NOTION_TOKEN", "label": "Notion connection token", "secret": true,
                     "present": false}],
         "lastSync": null, "lastError": null, "detail": null, "loginMode": "credentials",
         "reads": "Reads the pages you shared with the connection.", "tokenHelp": "notion.so/profile/integrations",
         "tier": 2}
        """.data(using: .utf8)!
        let status = try JSONDecoder().decode(ConnectorStatus.self, from: json)
        XCTAssertTrue(status.isTokenConnector)
        XCTAssertEqual(status.reads, "Reads the pages you shared with the connection.")
        // Owner 2026-11-05: no token is asked for. With no sign-in to offer, the panel says where it comes in instead;
        // what it reads is said once, whether or not it is connected.
        XCTAssertEqual(ConnectorSetupState.action(status), .none)
        XCTAssertEqual(ConnectorSetupState.stepLabel(status), Copy.Connect.noSignIn)
        XCTAssertEqual(ConnectorSetupState.readsLine(status), "Reads the pages you shared with the connection.")
        let older = """
        {"id": "reddit", "label": "Reddit", "connected": false, "fields": [], "loginMode": "credentials"}
        """.data(using: .utf8)!
        let legacy = try JSONDecoder().decode(ConnectorStatus.self, from: older)
        XCTAssertFalse(legacy.isTokenConnector)
        XCTAssertNil(legacy.reads)
        XCTAssertNil(ConnectorSetupState.readsLine(legacy))
    }

    func testCredentialConnectorIsNotOAuth() {
        let status = ConnectorStatus(
            id: "reddit", label: "Reddit", connected: false, fields: [],
            lastSync: nil, lastError: nil, detail: nil, loginMode: "credentials")
        XCTAssertFalse(status.isOAuth)
    }

    // MARK: - The one sign-in (owner 2026-11-05: no form for a token, key or password)

    private func status(connected: Bool = false, appSignIn: Bool? = nil, how: String? = nil,
                        reconnect: Bool? = nil) -> ConnectorStatus {
        ConnectorStatus(id: "notion-api", label: "Notion", connected: connected,
                        fields: [ConnectorField(name: "CICADA_NOTION_TOKEN", label: "Token", secret: true, present: false)],
                        lastSync: nil, lastError: nil, detail: nil, loginMode: "credentials",
                        appSignIn: appSignIn, how: how, reconnect: reconnect)
    }

    func testANotConnectedSourceWithASignInOffersConnectAndNothingElse() {
        let s = status(appSignIn: true)
        XCTAssertEqual(ConnectorSetupState.action(s), .connect)
        XCTAssertNil(ConnectorSetupState.stepLabel(s))
        XCTAssertEqual(Copy.Connect.connect("Notion"), "Connect Notion")
    }

    func testALapsedSignInAsksAgainAndAConnectedOneOffersNoSignIn() {
        XCTAssertEqual(ConnectorSetupState.action(status(appSignIn: true, how: "reconnect")), .signInAgain)
        XCTAssertEqual(ConnectorSetupState.action(status(appSignIn: true, reconnect: true)), .signInAgain)
        // A pasted-token connection keeps its row, Refresh and Disconnect; no sign-in is pushed on it.
        let connected = status(connected: true, appSignIn: true, how: "token")
        XCTAssertEqual(ConnectorSetupState.action(connected), .none)
        XCTAssertEqual(ConnectorSetupState.stepLabel(connected), "Connected")
    }

    func testASourceWithNoSignInSaysSoAndOffersNoForm() {
        XCTAssertEqual(ConnectorSetupState.action(status()), .none)
        XCTAssertEqual(ConnectorSetupState.stepLabel(status()), Copy.Connect.noSignIn)
    }

    func testTheSignInFlagsDecodeAndAnOlderBackendStillDecodes() throws {
        let json = """
        {"id": "notion-api", "label": "Notion", "connected": false, "fields": [], "loginMode": "credentials",
         "appSignIn": true, "how": "reconnect", "reconnect": true}
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(ConnectorStatus.self, from: json)
        XCTAssertEqual(s.appSignIn, true)
        XCTAssertEqual(s.how, "reconnect")
        XCTAssertEqual(s.reconnect, true)
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

    /// M1 (final review): X's pay-per-use billing (`resourcesRead`) must
    /// reach the "Sync now" summary, not just the connected-channel row.
    func testSyncSummaryReportsBilledReadsForAPayPerUseConnector() {
        XCTAssertEqual(
            ConnectorSetupState.syncSummary(
                ConnectorSyncResult(status: "ok", reason: nil, new: 3, seen: 5,
                                    error: nil, resourcesRead: 5)),
            "3 new · 5 seen · 5 reads billed")
        // Every non-billed connector's response always carries a literal 0
        // — must not append a "0 reads billed" tail.
        XCTAssertEqual(
            ConnectorSetupState.syncSummary(
                ConnectorSyncResult(status: "ok", reason: nil, new: 3, seen: 5,
                                    error: nil, resourcesRead: 0)),
            "3 new · 5 seen")
    }

    /// M1 (final review): `resourcesRead` must decode even when the key is
    /// absent from the payload (an older backend, or a hand-written test
    /// fixture like `testSyncConnectorPOSTsAndDecodesTheResult` below).
    func testConnectorSyncResultDecodesWithoutResourcesReadPresent() throws {
        let json = #"{"status": "ok", "reason": null, "new": 4, "seen": 9, "error": null}"#
            .data(using: .utf8)!
        let result = try JSONDecoder().decode(ConnectorSyncResult.self, from: json)
        XCTAssertEqual(result.resourcesRead, 0)
    }

    // MARK: - Transport

    /// Parses a request body the same way `EntitySourceTests` does
    /// (`EntitySourceTests.swift:129-143`, the cited `MockURLProtocol`
    /// precedent) — under the mock, a JSON body sometimes arrives via
    /// `httpBodyStream` rather than `httpBody`.
    private static func jsonBody(_ request: URLRequest) -> [String: Any]? {
        let data = request.httpBodyStream.map { stream -> Data in
            stream.open()
            defer { stream.close() }
            var data = Data()
            let bufferSize = 1024
            var buffer = [UInt8](repeating: 0, count: bufferSize)
            while stream.hasBytesAvailable {
                let read = stream.read(&buffer, maxLength: bufferSize)
                if read <= 0 { break }
                data.append(buffer, count: read)
            }
            return data
        } ?? request.httpBody ?? Data()
        return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    }

    func testFetchConnectorsGETsAndDecodesTheEnvelope() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/sources/connectors")
            let body = """
            {"connectors": [
                {"id": "pinterest", "label": "Pinterest", "connected": false, "fields": [],
                 "lastSync": null, "lastError": null, "detail": null, "loginMode": "oauth"},
                {"id": "reddit", "label": "Reddit", "connected": true, "fields": [],
                 "lastSync": "2026-08-30T10:00:00Z", "lastError": null, "detail": null,
                 "loginMode": "credentials"}
            ]}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let api = APIClient(session: MockURLProtocol.makeSession())
        let connectors = try await api.fetchConnectors()
        XCTAssertEqual(connectors.map(\.id), ["pinterest", "reddit"])
        XCTAssertFalse(connectors[0].connected)
        XCTAssertTrue(connectors[1].connected)
    }

    func testSaveCredentialsPutsTheFieldsAndDecodesTheStatus() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "PUT")
            XCTAssertEqual(request.url?.path, "/sources/connectors/reddit/credentials")
            let payload = Self.jsonBody(request)
            XCTAssertEqual(payload?["fields"] as? [String: String],
                           ["REDDIT_CLIENT_ID": "client-id-placeholder"])
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

    /// `forgetConnector` is the one method that had to diverge from the
    /// brief's snippet — `APIClient`'s `delete(_:body:)` helper returns raw
    /// `Data`, not a generic `Decodable`, so it decodes manually the same way
    /// `removeKey` does. This test is that workaround's only coverage.
    func testForgetConnectorDELETEsAndDecodesTheRawDataResponse() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/sources/connectors/pinterest/credentials")
            let body = """
            {"id": "pinterest", "label": "Pinterest", "connected": false,
             "fields": [{"name": "PINTEREST_APP_ID", "label": "App ID",
                         "secret": false, "present": false}],
             "lastSync": null, "lastError": null, "detail": null, "loginMode": "oauth"}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let api = APIClient(session: MockURLProtocol.makeSession())
        let status = try await api.forgetConnector("pinterest")
        XCTAssertEqual(status.id, "pinterest")
        XCTAssertFalse(status.connected)
        XCTAssertFalse(status.fields[0].present)
    }

    func testSyncConnectorPOSTsAndDecodesTheResult() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/sources/connectors/reddit/sync")
            let body = #"{"status": "ok", "reason": null, "new": 4, "seen": 9, "error": null}"#
                .data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let api = APIClient(session: MockURLProtocol.makeSession())
        let result = try await api.syncConnector("reddit")
        XCTAssertEqual(result.status, "ok")
        XCTAssertEqual(result.new, 4)
        XCTAssertEqual(result.seen, 9)
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
