import XCTest
@testable import CicadaApp

/// G217 / G212 / G213 / G50 — the connection model's wire, decoded leniently, and the pure pieces its pages draw.
final class ConnectionModelTests: XCTestCase {
    func testProvidersDecodeLenientlyWithTheirWaysAndIntelligence() throws {
        let body = #"{"providers":[{"id":"anthropic","label":"Anthropic","logo":"claude","tier":1,"#
            + #""ways":[{"id":"claude-code","label":"Claude Code","connects":["stdio","hooks"],"setup":["claude-code"]}],"#
            + #""intelligence":[{"connection":"claude-plan","label":"Use my Claude plan","kind":"plan"}],"later":[]},"#
            + #"{"id":"local","label":"This machine","logo":null,"tier":3,"intelligence":[{"connection":"ollama","label":"A model","kind":"local","surprise":1}]}],"#
            + #""pills":[]}"#
        let answer = try JSONDecoder().decode(ProvidersResponse.self, from: Data(body.utf8))
        XCTAssertEqual(answer.providers.map(\.id), ["anthropic", "local"])
        XCTAssertEqual(answer.providers[0].ways.first?.setup, ["claude-code"])
        XCTAssertNil(answer.providers[1].logo)
        XCTAssertEqual(ProviderDirectory.connectionId("ollama"), "ollama-local", "/connections names it so")
        XCTAssertEqual(ProviderDirectory.connectionId("byok-xai"), "byok-xai")
    }

    func testDeviceStatusNamesTheServerAndSaysHowEachConnects() throws {
        let body = #"{"devices":[{"id":null,"name":"studio-mac","role":"server","current":true,"connected":true,"#
            + #""how":"local","lastSeenAt":"2026-10-22T17:11:43Z","queue":3},{"id":"d1","name":"phone-example","#
            + #""role":"device","connected":false,"how":"tailscale","lastSeenAt":null,"queue":0}]}"#
        let rows = try JSONDecoder().decode(DeviceStatusResponse.self, from: Data(body.utf8)).devices
        XCTAssertTrue(rows[0].isServer)
        XCTAssertEqual(rows[0].id, "server")
        XCTAssertEqual(DevicesSettingsView.detail(rows[0], now: Date()), "this machine · 3 waiting")
        XCTAssertEqual(DevicesSettingsView.detail(rows[1], now: Date()), "Tailscale")
        XCTAssertEqual(DevicesSettingsView.symbol(rows[1]), "iphone")
        XCTAssertEqual(DevicesSettingsView.symbol(rows[0]), "desktopcomputer")
    }

    func testTheKeyLineShowsOnlyTheLastFourWhereItLivesAndWhenChecked() {
        XCTAssertEqual(Copy.Intelligence.keyLine(hint: "…a1b2", store: "file", verifiedAt: nil),
                       "…a1b2 · secrets file · not checked")
        XCTAssertTrue(Copy.Intelligence.keyLine(hint: "a1b2", store: "environment", verifiedAt: "2026-10-22T10:00:00Z")
            .hasPrefix("…a1b2 · environment · checked "))
    }

    func testTheBackendsRefusalSentenceIsRead() {
        let refused = APIError.httpError(422, #"{"detail":"This key was refused by Example. Nothing was saved."}"#)
        XCTAssertEqual(ConnectionModelText.detail(refused)?.code, 422)
        XCTAssertEqual(ConnectionModelText.detail(refused)?.text, "This key was refused by Example. Nothing was saved.")
        XCTAssertNil(ConnectionModelText.detail(APIError.serverUnreachable))
    }

    func testThePairingPayloadIsCompactSortedJSONAndTheQRDraws() {
        let json = PairingPayload.json(PairingQR(v: 1, url: nil, code: "ABCD-EFGH"))
        XCTAssertEqual(json, #"{"code":"ABCD-EFGH","v":1}"#)
        XCTAssertNotNil(PairingQRImage.image(json))
        XCTAssertEqual(PairingPayload.address("https://studio.example.ts.net/"), "https://studio.example.ts.net")
        XCTAssertNil(PairingPayload.address("http://192.168.1.4:8000"), "plain http only to this machine")
        XCTAssertEqual(PairingPayload.address("http://127.0.0.1:8000"), "http://127.0.0.1:8000")
    }

    func testAnAgentRowSumsItsWaysAndSaysWhereItWasSeen() {
        let umbrella = ProviderUmbrella(id: "openai", label: "OpenAI", logo: "openai",
                                        ways: [ProviderWay(id: "codex", label: "Codex", connects: ["stdio", "hooks"]),
                                               ProviderWay(id: "chatgpt", label: "ChatGPT", connects: ["remote"])])
        let live = [AgentLiveRow(id: "codex", connected: true, lastSeenAt: "2026-10-22T10:00:00Z", via: "mcp"),
                    AgentLiveRow(id: "claude-code", connected: true)]
        let summary = AgentSummary.of(umbrella, live: live, sources: [])
        XCTAssertTrue(summary.connected)
        XCTAssertEqual(summary.connects, ["stdio", "hooks", "remote"])
        XCTAssertTrue(summary.line(now: Date()).hasPrefix("on this machine · "))
        XCTAssertFalse(AgentSummary.of(umbrella, live: [AgentLiveRow(id: "claude-code", connected: true)],
                                       sources: []).connected, "another umbrella's sighting is not this one's")
    }

    func testAPastedProfileLinkIsKeptAsIsWithItsServicesMark() {
        XCTAssertEqual(ProfileLink.normalized("linkedin.com/in/bob-example"), "https://linkedin.com/in/bob-example")
        XCTAssertNil(ProfileLink.normalized("not a link"))
        XCTAssertEqual(ProfileLink.mark("https://www.linkedin.com/in/bob-example"), "linkedin")
        XCTAssertEqual(ProfileLink.mark("https://scholar.google.com/citations?user=x"), "scholar")
        XCTAssertNil(ProfileLink.mark("https://bob-example.org"))
        XCTAssertEqual(ProfileLink.label("https://www.bob-example.org/"), "bob-example.org")
        XCTAssertTrue(ProfileLink.needsConnecting("https://x.com/bob-example"))
        XCTAssertFalse(ProfileLink.needsConnecting("https://github.com/bob-example"))
    }

    func testTheAgentsPageIsTheNinthCellAndNoShortcutMoved() {
        XCTAssertEqual(AppTab.allCases.last, .agents)
        XCTAssertEqual(RailItem.digit(for: .agents), 9)
        XCTAssertEqual(RailItem.digit(for: .projects), 8)
        XCTAssertEqual(AppTab.restored(from: "Agents"), .agents)
    }

    func testLogoTileSizesAreTheOwnersOne() {
        XCTAssertEqual(LogoTile.tileSide(.regular), CicadaTheme.scaled(36))
        XCTAssertEqual(LogoTile.markSide(.regular), CicadaTheme.scaled(26))
        XCTAssertEqual(LogoTile.tileSide(.dense), CicadaTheme.scaled(24))
        for slug in LogoSet.all { XCTAssertTrue(LogoImage.exists(name: slug), slug) }
    }
}
