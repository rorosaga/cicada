import XCTest
@testable import CicadaApp

/// G132 ruling 51f, slice 1 — the app's side of the home-network door: when Local Network is asked (owner D4), what
/// Bonjour posts, when a network hint goes, the route in words (never an address), the relay under Advanced (D9), and
/// the bundle's usage text. No socket, no Bonjour call and no prompt: the rules are pure, the live seams are read as
/// source.
@MainActor
final class LocalNetworkTests: XCTestCase {
    private func defaults(_ name: String) throws -> UserDefaults {
        let d = try XCTUnwrap(UserDefaults(suiteName: "LocalNetworkTests.\(name)"))
        d.removePersistentDomain(forName: "LocalNetworkTests.\(name)")
        return d
    }

    // MARK: When it is asked (D4)

    func testTheStepComesOnceAtTheFirstShareAndItsRowStaysUntilAllowed() throws {
        let d = try defaults("step")
        let memory = LocalNetworkMemory(defaults: d)
        XCTAssertTrue(LocalNetworkStep.due(defaults: d, memory: memory), "never asked: the first click shows the step")
        XCTAssertFalse(LocalNetworkStep.rowShown(defaults: d, memory: memory), "nothing on the page before that click")
        LocalNetworkStep.markSeen(defaults: d)
        XCTAssertFalse(LocalNetworkStep.due(defaults: d, memory: memory), "once: Continue without allowing ends it")
        XCTAssertTrue(LocalNetworkStep.rowShown(defaults: d, memory: memory), "the row stays so it can still be given")
        memory.note(.granted)
        XCTAssertFalse(LocalNetworkStep.rowShown(defaults: d, memory: memory))
        memory.note(.denied)
        XCTAssertTrue(LocalNetworkStep.rowShown(defaults: d, memory: memory), "refused: the row opens the setting")
        let fresh = try defaults("step2")
        LocalNetworkMemory(defaults: fresh).note(.denied)
        XCTAssertFalse(LocalNetworkStep.due(defaults: fresh, memory: LocalNetworkMemory(defaults: fresh)),
                       "answered once (either way): macOS never asks again, so neither does the step")
    }

    func testTheMemoryReadsNotYetUntilAnAnswerAndTheProbeVerdictIsStrict() throws {
        let memory = LocalNetworkMemory(defaults: try defaults("memory"))
        XCTAssertEqual(memory.state, .notYet)
        XCTAssertFalse(memory.asked)
        memory.note(.granted)
        XCTAssertEqual(memory.state, .granted)
        memory.note(.notYet)
        XCTAssertFalse(memory.asked)
        XCTAssertEqual(LocalNetworkVerdict.state(foundSelf: true, policyDenied: true, finished: false), .granted)
        XCTAssertEqual(LocalNetworkVerdict.state(foundSelf: false, policyDenied: true, finished: true), .denied)
        XCTAssertNil(LocalNetworkVerdict.state(foundSelf: false, policyDenied: false, finished: true),
                     "no answer yet (the prompt still up): nothing is remembered")
        XCTAssertNil(LocalNetworkVerdict.state(foundSelf: false, policyDenied: true, finished: false),
                     "a refusal while the prompt is up is not an answer yet")
    }

    /// Review of #573: a refused answer is re-checked on the app's return only after the person's own Allow click,
    /// at most once per window, never two probes at once.
    func testTheReturnRecheckIsThrottledNeverOverlapsAndNeedsAnEarlierAsk() throws {
        let t = Date(timeIntervalSince1970: 1_800_000_000)
        var gate = LocalNetworkRecheckGate()
        XCTAssertFalse(gate.due(state: .denied, askedBefore: false, now: t), "never asked by a click: never probed")
        XCTAssertFalse(gate.due(state: .notYet, askedBefore: true, now: t))
        XCTAssertFalse(gate.due(state: .granted, askedBefore: true, now: t))
        XCTAssertTrue(gate.due(state: .denied, askedBefore: true, now: t))
        gate.started(at: t)
        XCTAssertFalse(gate.due(state: .denied, askedBefore: true, now: t.addingTimeInterval(60)), "one at a time")
        gate.finished()
        XCTAssertFalse(gate.due(state: .denied, askedBefore: true,
                                now: t.addingTimeInterval(CicadaTiming.localNetworkRecheckEvery - 1)))
        XCTAssertTrue(gate.due(state: .denied, askedBefore: true, now: t.addingTimeInterval(CicadaTiming.localNetworkRecheckEvery)))
        let memory = LocalNetworkMemory(defaults: try defaults("asked"))
        XCTAssertFalse(memory.askedBefore)
        memory.noteAsked(at: t)
        XCTAssertTrue(memory.askedBefore)
        let discovery = try source("Services/LanDiscovery.swift")
        XCTAssertTrue(discovery.contains("memory.noteAsked()"), "the ask records the click")
        XCTAssertTrue(discovery.contains("recheck.due(state: memory.state, askedBefore: memory.askedBefore"))
    }

    /// Review of #573: another memory is another instance name, so a bank switch refreshes Bonjour at once.
    func testABankSwitchRefreshesDiscovery() throws {
        let app = try source("CicadaApp.swift")
        let block = try XCTUnwrap(app.components(separatedBy: ".onChange(of: store.banks.value?.active)").dropFirst().first)
        XCTAssertTrue(block.prefix(400).contains("LanDiscovery.shared.refresh()"))
    }

    func testLocalNetworkIsAPromptRowThatNeverAsksFromItsProbe() throws {
        XCTAssertEqual(MacPermission.localNetwork.way, .prompt)
        XCTAssertEqual(MacPermissionRows.action(.localNetwork, state: .notYet), .ask)
        XCTAssertEqual(Copy.MacPermissions.name(.localNetwork), Copy.LocalNetwork.name)
        let live = try source("Services/MacPermissionsLive.swift")
        let probe = try XCTUnwrap(live.components(separatedBy: "struct LiveMacPermissionAsker").first)
        XCTAssertFalse(probe.contains("LanDiscovery"), "the probe reads the remembered answer, never a Bonjour call")
        let discovery = try source("Services/LanDiscovery.swift")
        XCTAssertTrue(discovery.contains("guard memory.state == .granted"),
                      "discovery runs only once the person allowed it — nothing advertises or browses unasked")
    }

    // MARK: What Bonjour posts

    func testOnlyThisMemorysPrivateDoorsArePostedAndAConflictRenameStillMatches() {
        XCTAssertTrue(LanRules.matches("c-abc", instance: "c-abc"))
        XCTAssertTrue(LanRules.matches("c-abc (2)", instance: "c-abc"), "every device advertises the one name")
        XCTAssertFalse(LanRules.matches("c-abcd", instance: "c-abc"))
        XCTAssertFalse(LanRules.matches("cicada-probe-1f", instance: "c-abc"))
        for host in ["192.168.1.4", "10.0.0.2", "172.20.1.1", "fd12:3456::1"] { XCTAssertTrue(LanRules.usable(host), host) }
        for host in ["8.8.8.8", "172.32.0.1", "127.0.0.1", "fe80::1%en0", "fe80::1", "2001:db8::1", "100.100.1.1", "x"] {
            XCTAssertFalse(LanRules.usable(host), host)
        }
        let rows: [(name: String, host: String, port: Int)] = [
            ("c-abc", "192.168.1.4", 50123), ("c-abc", "192.168.1.4", 50123), ("c-abc (2)", "10.0.0.9", 50124),
            ("c-abc", "fe80::1", 50123), ("c-other", "192.168.1.5", 50125), ("c-abc", "192.168.1.6", 0),
        ]
        XCTAssertEqual(LanRules.doors(rows, instance: "c-abc"),
                       [FoundDoor(host: "10.0.0.9", port: 50124), FoundDoor(host: "192.168.1.4", port: 50123)])
        let many = (1...40).map { (name: "c-abc", host: "10.0.0.\($0)", port: 50000) }
        XCTAssertEqual(LanRules.doors(many, instance: "c-abc").count, 16, "the backend's own bound")
    }

    /// Ruling 51f (owner 2026-11-03): the door is UDP, so it is a `._udp` service browsed over UDP; the configured
    /// HTTPS listener alone stays `._tcp`. The advertisement and the browse both follow `/sync/discovery`'s `type`.
    func testTheDoorIsAUDPServiceAndTheAdvertisementFollowsThePlansType() throws {
        XCTAssertEqual(LanRules.serviceType, "_cicada._udp")
        XCTAssertEqual(LanRules.httpsServiceType, "_cicada._tcp")
        XCTAssertTrue(LanRules.isUDP(LanRules.serviceType))
        XCTAssertFalse(LanRules.isUDP(LanRules.httpsServiceType))
        let text = try source("Services/LanDiscovery.swift")
        XCTAssertTrue(text.contains("DNSServiceRegister(&ref, 0, 0, what.name, type,"), "advertised under the plan's type")
        XCTAssertFalse(text.contains("using: .tcp)"), "no browse pinned to TCP")
    }

    func testTheWireDecodesWithDefaults() throws {
        let plan = try JSONDecoder().decode(DiscoveryPlan.self, from: Data(
            #"{"type":"_cicada._udp","browse":"c-abc","advertise":{"name":"c-abc","port":50123},"nonce":"n"}"#.utf8))
        XCTAssertEqual(plan.advertise, .init(name: "c-abc", port: 50123, door: false))
        XCTAssertEqual(plan.type, LanRules.serviceType)
        let none = try JSONDecoder().decode(DiscoveryPlan.self, from: Data(
            #"{"type":"_cicada._tcp","browse":"c-abc","advertise":null,"nonce":"n"}"#.utf8))
        XCTAssertNil(none.advertise)
        let routes = try JSONDecoder().decode(SyncRoutes.self, from: Data(
            #"{"toHome":{"active":"lan","queued":false,"moves":1,"lastMoveAt":1.0,"routes":[{"kind":"lan","carrier":"door","state":"active"}]},"door":{"open":true},"lanDial":true}"#.utf8))
        XCTAssertEqual(routes.toHome.active, "lan")
        XCTAssertEqual(routes.toHome.routes, [.init(kind: "lan", state: "active")])
        XCTAssertTrue(routes.lanDial)
        let bare = try JSONDecoder().decode(SyncRoutes.self, from: Data("{}".utf8))
        XCTAssertNil(bare.toHome.active)
        XCTAssertFalse(bare.toHome.queued)
        let outbox = try JSONDecoder().decode(ReplicaState.Outbox.self, from: Data(
            #"{"waiting":1,"held":0,"rejected":0,"captures":0,"full":true}"#.utf8))
        XCTAssertEqual(outbox.full, true)
        XCTAssertNil(try JSONDecoder().decode(ReplicaState.Outbox.self, from: Data(
            #"{"waiting":1,"held":0,"rejected":0,"captures":0}"#.utf8)).full, "an older backend sends none")
    }

    // MARK: Network hints

    func testAHintIsDebouncedAReturnAtMostEveryHalfMinute() {
        var gate = NetworkHintGate()
        let t = Date(timeIntervalSince1970: 1_800_000_000)
        XCTAssertTrue(gate.due(.returned, now: t))
        gate.sent(.returned, at: t)
        XCTAssertFalse(gate.due(.returned, now: t.addingTimeInterval(CicadaTiming.networkReturnEvery - 1)))
        XCTAssertTrue(gate.due(.returned, now: t.addingTimeInterval(CicadaTiming.networkReturnEvery)))
        XCTAssertTrue(gate.due(.changed, now: t), "a network change is its own")
        gate.sent(.changed, at: t)
        XCTAssertFalse(gate.due(.changed, now: t.addingTimeInterval(1)))
        XCTAssertTrue(gate.due(.changed, now: t.addingTimeInterval(CicadaTiming.networkChangeSettle)))
    }

    // MARK: The route in words

    func testTheRouteIsAWordAndNeverAnAddress() {
        XCTAssertEqual(LanRules.routeWord("lan"), "Same network")
        XCTAssertEqual(LanRules.routeWord("tailnet"), "Tailscale")
        XCTAssertEqual(LanRules.routeWord("tailscale"), "Tailscale")
        XCTAssertEqual(LanRules.routeWord("configured"), "Your address")
        XCTAssertEqual(LanRules.routeWord("relay"), "Relay")
        XCTAssertNil(LanRules.routeWord(nil))
        XCTAssertEqual(ConnectionModelText.how("lan"), "Same network", "a device on the door reads as its route")
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let contact = "2027-01-15T07:58:00Z"
        let using = MemoryCopyModel.routeLine(SyncRoutes(toHome: .init(active: "lan", queued: false)),
                                              lastContact: contact, now: now)
        XCTAssertEqual(using?.hasPrefix("Same network · reached "), true, using ?? "")
        XCTAssertEqual(Copy.LocalNetwork.reached(now.addingTimeInterval(24), now: now), "reached just now",
                       "a sighting later in the timeline's minute is never in the future")
        XCTAssertFalse(Copy.AgentsPage.seen(now.addingTimeInterval(24), now: now).contains("in "))
        let queued = MemoryCopyModel.routeLine(SyncRoutes(toHome: .init(active: nil, queued: true)), lastContact: nil,
                                               now: now)
        XCTAssertEqual(queued, "Queued")
        XCTAssertNil(MemoryCopyModel.routeLine(nil, lastContact: contact, now: now))
        for line in [using ?? "", queued ?? ""] + Copy.LocalNetwork.labels {
            XCTAssertNil(line.range(of: #"\d+\.\d+\.\d+\.\d+|:\d{2,5}\b|wss?://|https?://"#, options: .regularExpression),
                         "no address or port is ever shown: \(line)")
        }
    }

    // MARK: Words, the fold, the bundle

    func testTheWordsAreShortAndSaidOnce() {
        XCTAssertLessThanOrEqual(OnboardingWords.count([Copy.LocalNetwork.unlocks]), 12)
        XCTAssertLessThanOrEqual(OnboardingWords.count([Copy.LocalNetwork.firewall]), 12)
        XCTAssertLessThanOrEqual(OnboardingWords.count([Copy.Relay.detailOff]), 12)
        XCTAssertLessThanOrEqual(OnboardingWords.count([Copy.Relay.detailOn]), 16)
        XCTAssertFalse(Copy.LocalNetwork.unlocks.contains("Wi-Fi"), "a wired Mac is on a network too (owner 2026-11-03)")
        XCTAssertFalse(Copy.LocalNetwork.unlocks.lowercased().contains(Copy.LocalNetwork.name.lowercased()),
                       "the row's line never repeats its name")
        for line in Copy.LocalNetwork.labels { XCTAssertFalse(line.contains("!"), line) }
    }

    func testTheRelaySitsUnderAdvancedAndItsFoldOpensForASearchHit() throws {
        let relay = try source("Views/Settings/RelaySection.swift")
        XCTAssertTrue(relay.contains("DisclosureGroup(isExpanded: $advancedOpen)"), "under Advanced (owner D9)")
        XCTAssertTrue(relay.contains("@AppStorage(\"cicada.settings.devices.advancedOpen\") private var advancedOpen = false"),
                      "folded by default, the viewer's choice remembered (DR-39)")
        XCTAssertTrue(relay.contains("focus?.landed == .relay"), "a search hit on the relay opens its fold")
    }

    func testTheBundleCarriesTheLocalNetworkTextAndTheBonjourTypeForEveryBuild() throws {
        let bundleScript = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("bundle.sh")
        let text = try String(contentsOf: bundleScript, encoding: .utf8)
        XCTAssertEqual(text.components(separatedBy: "<key>NSLocalNetworkUsageDescription</key>").count - 1, 1,
                       "one plist serves the release and the developer bundle")
        XCTAssertNotNil(text.range(of: "<key>NSLocalNetworkUsageDescription</key><string>[^<]{20,}</string>",
                                   options: .regularExpression))
        XCTAssertTrue(text.contains("<key>NSBonjourServices</key><array>"
                                    + LanRules.serviceTypes.map { "<string>\($0)</string>" }.joined() + "</array>"),
                      "both types the backend may name: the UDP door, and HTTPS with the door off")
        XCTAssertNil(text.range(of: "<key>NSLocalNetworkUsageDescription</key><string>[^<]*Wi-Fi", options: .regularExpression))
    }

    private func source(_ path: String) throws -> String {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        return try String(contentsOf: root.appendingPathComponent(path), encoding: .utf8)
    }
}
