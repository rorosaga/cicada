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

    /// Fix round 2026-10-22: Connected when seen just now; Set up when configured, with conversations, or seen
    /// before (its line then says the day); Not set up otherwise — for agents and paired devices alike.
    func testPresenceIsConnectedSetUpOrNotSetUp() {
        let now = Date()
        XCTAssertEqual(Copy.Presence.of(seen: now.addingTimeInterval(-60), configured: false, conversations: 0, now: now),
                       .connected)
        XCTAssertEqual(Copy.Presence.of(seen: nil, configured: false, conversations: 14, now: now), .setUp,
                       "an agent with captured conversations is never Off")
        XCTAssertEqual(Copy.Presence.of(seen: now.addingTimeInterval(-86_400), configured: false, conversations: 0,
                                        now: now), .setUp)
        XCTAssertEqual(Copy.Presence.of(seen: nil, configured: true, conversations: 0, now: now), .setUp)
        XCTAssertEqual(Copy.Presence.of(seen: nil, configured: false, conversations: 0, now: now), .notSetUp)
        XCTAssertEqual(Copy.Presence.setUp.word, "Set up")
        XCTAssertEqual(Copy.Presence.notSetUp.word, "Not set up")
        XCTAssertFalse(Copy.Presence.setUp.on)

        let umbrella = ProviderUmbrella(id: "anthropic", label: "Anthropic", logo: "claude",
                                        ways: [ProviderWay(id: "claude-code", label: "Claude Code", connects: ["stdio"])])
        let source = try? JSONDecoder().decode(SourceOverview.self, from: Data(
            #"{"id":"harness:claude-code","label":"Claude Code","kind":"agent","mark":"claude-code","conversations":14,"episodes":14,"entities":0,"items":0,"connected":true,"actions":[],"origins":[],"harness":"claude-code","activity":{},"intent":"captured"}"#.utf8))
        if let source {
            XCTAssertEqual(AgentSummary.of(umbrella, live: [], sources: [source]).presence(now: now), .setUp)
        }
        XCTAssertEqual(AgentSummary.of(umbrella, live: [], sources: []).presence(now: now), .notSetUp)

        let device = DeviceStatusRow(deviceId: "d1", name: "Studio laptop", connected: false,
                                     lastSeenAt: "2026-10-20T10:00:00Z")
        XCTAssertEqual(DevicesSettingsView.presence(device, now: now), .setUp)
        XCTAssertTrue(DevicesSettingsView.detail(device, now: now).hasPrefix("last seen "))
        XCTAssertEqual(DevicesSettingsView.presence(DeviceStatusRow(deviceId: "d2", name: "New"), now: now), .notSetUp)
    }

    /// #432 (additive): the answer may carry `reach.serveCommand`; an older backend's answer without it still decodes.
    func testThePairingAnswerReadsReachWhenPresentAndWithout() throws {
        let with = #"{"pairing":{"id":"p1","state":"waiting","expiresAt":"2026-10-22T10:10:00Z"},"code":"ABCD-EFGH","#
            + #""qr":{"v":1,"url":null,"code":"ABCD-EFGH"},"reach":{"serveCommand":"tailscale serve --bg --https=8443 8000"}}"#
        let older = #"{"pairing":{"id":"p1","state":"waiting"},"code":"ABCD-EFGH","qr":{"v":1,"url":null,"code":"ABCD-EFGH"}}"#
        XCTAssertEqual(try JSONDecoder().decode(PairingCreated.self, from: Data(with.utf8)).reach?.serveCommand,
                       "tailscale serve --bg --https=8443 8000")
        XCTAssertNil(try JSONDecoder().decode(PairingCreated.self, from: Data(older.utf8)).reach)
        let missing = #"{"pairing":{"id":"p1","state":"waiting"},"code":"ABCD-EFGH","qr":{"v":1,"url":null,"code":"ABCD-EFGH"},"#
            + #""reach":{"tailscale":"missing","url":null,"public":false,"serveCommand":"tailscale serve --bg --https=8443 8000"}}"#
        XCTAssertNil(try JSONDecoder().decode(PairingCreated.self, from: Data(missing.utf8)).reach?.shownServeCommand,
                     "no serve command where Tailscale is not installed")
        let served = #"{"pairing":{"id":"p1","state":"waiting"},"code":"ABCD-EFGH","kind":"capture","#
            + #""qr":{"v":1,"url":"https://mac.example.ts.net:8443","code":"ABCD-EFGH"},"#
            + #""reach":{"tailscale":"no-funnel","url":"https://mac.example.ts.net:8443","public":false,"serveCommand":null}}"#
        let answer = try JSONDecoder().decode(PairingCreated.self, from: Data(served.utf8))
        XCTAssertEqual(answer.qr.url, "https://mac.example.ts.net:8443")
        XCTAssertNil(answer.reach?.shownServeCommand)
        XCTAssertEqual(PairingKind.capture.rawValue, "capture")
        XCTAssertEqual(PairingKind.full.rawValue, "full")
    }
}
