import XCTest
@testable import CicadaApp

/// G135 (R-R7, R-R34) — every decision the "From anywhere" page makes is a pure
/// function with a table test, the brief's sentences are pinned word for word,
/// and the app catalog is held to the backend's by one shared fixture.
final class RemoteConnectorTests: XCTestCase {

    private struct Catalog: Decodable {
        struct App: Decodable { let id: String; let harness: String; let delivery: String }
        struct Scope: Decodable { let id: String; let `default`: Bool }
        let apps: [App]
        let scopes: [Scope]
    }

    private func catalog() throws -> Catalog {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let data = try Data(contentsOf: root.appendingPathComponent("api/tests/fixtures/remote_catalog.json"))
        return try JSONDecoder().decode(Catalog.self, from: data)
    }

    func testAppsAndScopesMatchTheBackendCatalog() throws {
        let c = try catalog()
        XCTAssertEqual(RemoteApp.allCases.map(\.rawValue), c.apps.map(\.id))
        XCTAssertEqual(RemoteApp.allCases.map(\.harness), c.apps.map(\.harness))
        XCTAssertEqual(RemoteApp.allCases.map(\.delivery), c.apps.map(\.delivery))
        XCTAssertEqual(RemoteScope.allCases.map(\.rawValue), c.scopes.map(\.id))
        XCTAssertEqual(RemoteScope.allCases.map(\.isDefault), c.scopes.map(\.default))
    }

    func testTheBriefsSentencesAreWordForWord() {
        XCTAssertEqual(RemoteScope.summary(RemoteScope.defaults), "Can search, read and record. Can't delete or rewrite.")
        XCTAssertEqual(Copy.remoteSwitchTitle, "Let AI apps outside this Mac use your memory.")
        XCTAssertEqual(Copy.remoteSwitchDetail, "Works while this Mac is awake and online. Everything still lives here.")
        XCTAssertEqual(Copy.remoteShownOnce, "You won't see this again. Revoke any time.")
        XCTAssertEqual(Copy.remoteNeverOpensTunnel, "Cicada never opens a tunnel on its own.")
        XCTAssertEqual(Copy.onThisMac, "On this Mac")
        XCTAssertEqual(Copy.fromAnywhere, "From anywhere")
    }

    func testTheSummaryJoinsWhateverIsGranted() {
        XCTAssertEqual(RemoteScope.summary([.search]), "Can search. Can't delete or rewrite.")
        XCTAssertEqual(RemoteScope.summary([.search, .read]), "Can search and read. Can't delete or rewrite.")
        XCTAssertEqual(RemoteScope.summary(Set(RemoteScope.allCases)),
                       "Can search, read, record, read raw conversations, answer questions and ask. Can't delete or rewrite.")
    }

    private let link = "https://mac.example-tailnet.ts.net/c/cic_rc_ab12cd34_SECRET/mcp"
    private let mcpURL = "https://mac.example-tailnet.ts.net/mcp"
    private let token = "cic_rc_ab12cd34_SECRET"

    func testEveryAppHasAtMostThreeStepsAndSomethingToDraw() {
        for app in RemoteApp.allCases {
            let steps = app.steps(link: link, mcpURL: mcpURL, token: token)
            XCTAssertFalse(steps.isEmpty, app.rawValue)
            XCTAssertLessThanOrEqual(steps.count, 3, app.rawValue)
            XCTAssertFalse(app.symbol.isEmpty, app.rawValue)
        }
    }

    func testLinkAppsHandOutTheLinkAndNeverAHeader() {
        for app in [RemoteApp.claude, .chatgpt, .perplexity] {
            let snippets = app.steps(link: link, mcpURL: mcpURL, token: token).compactMap(\.snippet)
            XCTAssertEqual(snippets, [link], app.rawValue)
        }
    }

    func testHeaderAppsCarryTheAddressAndTheBearerToken() {
        func snippets(_ app: RemoteApp) -> String {
            app.steps(link: link, mcpURL: mcpURL, token: token).compactMap(\.snippet).joined(separator: "\n")
        }
        XCTAssertTrue(snippets(.claudeCode).contains("claude mcp add --transport http --scope user cicada-remote \(mcpURL)"))
        XCTAssertTrue(snippets(.claudeCode).contains("Authorization: Bearer \(token)"))
        XCTAssertTrue(snippets(.geminiCLI).contains("gemini mcp add --transport http --header \"Authorization: Bearer \(token)\" cicada-remote \(mcpURL)"))
        XCTAssertTrue(snippets(.codex).contains("bearer_token_env_var = \"CICADA_TOKEN\"") && snippets(.codex).contains("export CICADA_TOKEN=\(token)"))
        XCTAssertTrue(snippets(.cursor).contains("${env:CICADA_TOKEN}") && snippets(.cursor).contains(mcpURL))
        XCTAssertTrue(snippets(.vscode).contains("${input:cicada-token}") && snippets(.vscode).contains(token))
        XCTAssertTrue(snippets(.other).contains(link) && snippets(.other).contains(mcpURL))
    }

    func testTheHonestLimitsAreSaid() {
        XCTAssertTrue(RemoteApp.chatgpt.note?.contains("Phone support") ?? false)
        XCTAssertTrue(RemoteApp.claude.steps(link: link, mcpURL: mcpURL, token: token).map(\.text).joined().contains("phone"))
        XCTAssertTrue(Copy.remoteGeminiApp.contains("Gemini CLI"))
        XCTAssertEqual(RemoteExpiry.allCases.map(\.days), [7, 30, 90])  // every connector expires (R-R3)
    }

    private func connector(state: String = "active", expiresAt: String? = nil,
                           lastUsedAt: String? = nil, lastClient: String? = nil) -> RemoteConnector {
        RemoteConnector(id: "ab12cd34", label: "Phone", app: "claude", scopes: ["search", "read", "record"],
                        createdAt: "2026-09-01T00:00:00+00:00", expiresAt: expiresAt, revokedAt: nil,
                        lastUsedAt: lastUsedAt, lastClient: lastClient, state: state)
    }

    func testExpiryText() {
        let now = ISO8601DateFormatter().date(from: "2026-09-23T12:00:00Z")!
        XCTAssertEqual(RemoteConnectorText.expiry(connector(), now: now), "No expiry")
        XCTAssertEqual(RemoteConnectorText.expiry(connector(expiresAt: "2026-10-20T12:00:00+00:00"), now: now), "Expires in 27 days")
        XCTAssertEqual(RemoteConnectorText.expiry(connector(expiresAt: "2026-09-24T12:00:00+00:00"), now: now), "Expires in 1 day")
        XCTAssertEqual(RemoteConnectorText.expiry(connector(expiresAt: "2026-09-23T15:00:00+00:00"), now: now), "Expires today")
        XCTAssertEqual(RemoteConnectorText.expiry(connector(state: "expired"), now: now), "Expired")
        XCTAssertEqual(RemoteConnectorText.expiry(connector(state: "revoked"), now: now), "Revoked")
    }

    func testLastUsedText() {
        let now = ISO8601DateFormatter().date(from: "2026-09-23T12:00:00Z")!
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(RemoteConnectorText.lastUsed(connector(), now: now, locale: en), "Never used")
        XCTAssertEqual(RemoteConnectorText.lastUsed(connector(lastUsedAt: "2026-09-23T11:57:00+00:00", lastClient: "claude-ai"),
                                                    now: now, locale: en), "Last used 3 minutes ago by claude-ai")
        XCTAssertEqual(RemoteConnectorText.lastUsed(connector(lastUsedAt: "2026-09-23T11:57:00+00:00"), now: now, locale: en),
                       "Last used 3 minutes ago")
    }

    private func status(enabled: Bool = true, error: String? = nil, effective: String? = nil,
                        reachable: Bool? = nil, tailscale: String = "missing", ngrok: Bool = false) -> RemoteStatus {
        RemoteStatus(enabled: enabled, port: 8765, listenerUp: error == nil, listenerError: error,
                     publicBaseUrl: nil, detectedUrl: effective, effectiveUrl: effective, tailscale: tailscale,
                     ngrokInstalled: ngrok, reachable: reachable, funnelCommand: "tailscale funnel --bg 8765",
                     ngrokCommand: "ngrok http 8765 --inspect=false")
    }

    func testReachSummary() {
        let url = "https://mac.example-tailnet.ts.net"
        XCTAssertEqual(RemoteReach.of(status(enabled: false)), .off)
        guard case .problem = RemoteReach.of(status(error: "port 8765 is already in use")) else { return XCTFail() }
        XCTAssertEqual(RemoteReach.of(status(effective: url, reachable: true)), .reachable(url))
        XCTAssertEqual(RemoteReach.of(status(effective: url, reachable: false)), .unreachable(url))
        XCTAssertEqual(RemoteReach.of(status(effective: url)), .checking(url))
        guard case let .setUp(_, funnel) = RemoteReach.of(status(tailscale: "no-funnel")) else { return XCTFail() }
        XCTAssertEqual(funnel, "tailscale funnel --bg 8765")
        guard case let .setUp(_, ngrok) = RemoteReach.of(status(ngrok: true)) else { return XCTFail() }
        XCTAssertEqual(ngrok, "ngrok http 8765 --inspect=false")
        guard case let .setUp(_, none) = RemoteReach.of(status()) else { return XCTFail() }
        XCTAssertNil(none)
    }

    func testDecodesTheWirePayloads() throws {
        let json = """
        {"connector": {"id": "ab12cd34", "label": "Phone", "app": "claude", "scopes": ["read", "search"],
          "createdAt": "2026-09-23T12:00:00+00:00", "expiresAt": null, "revokedAt": null,
          "lastUsedAt": null, "lastClient": null, "state": "active"},
         "token": "cic_rc_ab12cd34_SECRET", "link": null, "mcpUrl": null}
        """.data(using: .utf8)!
        let created = try JSONDecoder().decode(RemoteConnectorCreated.self, from: json)
        XCTAssertEqual(created.connector.remoteApp, .claude)
        XCTAssertEqual(created.connector.grantedScopes, [.search, .read])
    }

    func testRemoteHarnessOriginsWearTheirMarks() {
        XCTAssertEqual(OriginIconography.logoName(for: "claude-web"), "claude")
        XCTAssertEqual(OriginIconography.logoName(for: "chatgpt"), "chatgpt")
        XCTAssertEqual(OriginIconography.logoName(for: "claude-code-remote"), "claude-code")
        XCTAssertEqual(OriginIconography.logoName(for: "codex-remote"), "codex")
        XCTAssertNil(OriginIconography.logoName(for: "perplexity"))
        XCTAssertEqual(OriginIconography.label(for: "claude-web"), "Claude")
        XCTAssertEqual(OriginIconography.label(for: "vscode"), "VS Code")
        XCTAssertNotEqual(OriginIconography.symbol(for: "perplexity"), "tray")
    }

    func testGrokGetsItsLinkInsideAMessageNeverAHeader() {
        let snippets = RemoteApp.grok.steps(link: link, mcpURL: mcpURL, token: token).compactMap(\.snippet)
        XCTAssertEqual(snippets.count, 1)
        XCTAssertTrue(snippets[0].contains(link))
        XCTAssertFalse(snippets[0].contains("Bearer"))
        XCTAssertEqual(OriginIconography.label(for: "grok"), "Grok")
        XCTAssertNil(OriginIconography.logoName(for: "grok"))
    }

    func testCreatingSendsTheChosenExpiry() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/remote/connectors")
            let body = try XCTUnwrap(Self.bodyJSON(request))
            XCTAssertEqual(body["expiresInDays"] as? Int, 7)
            XCTAssertEqual(body["scopes"] as? [String], ["search"])
            let out = """
            {"connector": {"id": "ab12cd34", "label": "Desk", "app": "cursor", "scopes": ["search"],
              "createdAt": "2026-09-23T12:00:00+00:00", "state": "active"}, "token": "cic_rc_ab12cd34_SECRET"}
            """.data(using: .utf8)!
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, out)
        }
        let api = APIClient(session: MockURLProtocol.makeSession())
        let created = try await api.createRemoteConnector(app: "cursor", label: "Desk", scopes: ["search"], expiresInDays: 7)
        XCTAssertEqual(created.connector.id, "ab12cd34")
    }

    private static func bodyJSON(_ request: URLRequest) -> [String: Any]? {
        let data: Data = request.httpBodyStream.map { stream in
            stream.open(); defer { stream.close() }
            var data = Data()
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let read = stream.read(&buffer, maxLength: buffer.count)
                if read <= 0 { break }
                data.append(buffer, count: read)
            }
            return data
        } ?? request.httpBody ?? Data()
        return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    }
}
