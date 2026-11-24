import XCTest
@testable import CicadaApp

/// G212 — the Sleep page's machines: each by its own name; a machine's queue. 2026-11-24: drawn as chips in the title
/// row (a light, the name, a house for the home, what waits) and narrowing the Queue and Past sleeps.
final class MachinesStripTests: XCTestCase {
    private let wire = """
    {"devices": [
      {"id": null, "name": "Studio-Mac", "role": "server", "current": true, "connected": true, "how": "local",
       "lastSeenAt": "2026-10-22T10:00:00Z", "queue": 23},
      {"id": "dev_a", "name": "server-a", "role": "device", "current": false, "connected": true, "how": "tailscale",
       "lastSeenAt": "2026-10-22T09:59:00Z", "queue": 160},
      {"id": "dev_b", "name": "laptop-b", "role": "device", "connected": false, "how": null, "queue": 0}],
     "connectedWithinSeconds": 600}
    """

    func testTheWireDecodes() throws {
        let list = try JSONDecoder().decode(MachineStatusList.self, from: Data(wire.utf8))
        XCTAssertEqual(list.devices.map(\.id), ["server", "dev_a", "dev_b"])
        XCTAssertEqual(list.devices.map(\.name), ["Studio-Mac", "server-a", "laptop-b"])
        XCTAssertEqual(list.devices.map(\.queue), [23, 160, 0])
        // An older backend sends none of the 2026-11-24 keys: every one defaults to "nothing to say".
        XCTAssertEqual(list.devices.map(\.home), [false, false, false])
        XCTAssertEqual(list.devices.map(\.keepsCopy), [false, false, false])
        XCTAssertEqual(list.devices.map(\.revoked), [false, false, false])
        XCTAssertNil(list.devices[1].behind)
        XCTAssertNil(list.devices[1].unsent)
    }

    func testTheNewKeysDecodeAndTheMemberwiseInitDefaultsThem() throws {
        let row = try JSONDecoder().decode(MachineStatus.self, from: Data("""
        {"id": "dev_c", "name": "device-c", "role": "device", "connected": true, "how": "tailscale", "queue": 2,
         "home": true, "keepsCopy": true, "behind": 3, "unsent": 1, "revoked": false}
        """.utf8))
        XCTAssertTrue(row.home); XCTAssertTrue(row.keepsCopy)
        XCTAssertEqual(row.behind, 3); XCTAssertEqual(row.unsent, 1); XCTAssertFalse(row.revoked)
        let old = MachineStatus(deviceId: "x", name: "device-x", connected: true, how: nil, queue: 0)
        XCTAssertFalse(old.home); XCTAssertNil(old.behind); XCTAssertFalse(old.revoked)
    }

    // MARK: the chips

    private func machine(_ id: String?, _ name: String = "device-a", role: String = "device", connected: Bool = true,
                         how: String? = nil, queue: Int = 0, current: Bool = false, home: Bool = false,
                         keepsCopy: Bool = false, behind: Int? = nil, unsent: Int? = nil, revoked: Bool = false,
                         catchUp: MachineAwaySync? = nil, lastSeenAt: String? = nil) -> MachineStatus {
        MachineStatus(deviceId: id, name: name, role: role, connected: connected, how: how, lastSeenAt: lastSeenAt,
                      queue: queue, current: current, catchUp: catchUp, home: home, keepsCopy: keepsCopy,
                      behind: behind, unsent: unsent, revoked: revoked)
    }

    /// The light: green = heard from; amber = heard from and syncing, behind, or holding conversations it has not
    /// sent; grey = not heard from or removed, whatever it last reported. Never the accent.
    func testTheLightIsGreenAmberOrGrey() {
        XCTAssertEqual(MachinesStrip.light(machine("a")), .ok)
        XCTAssertEqual(MachinesStrip.light(machine("a", behind: 0)), .ok, "caught up is green")
        XCTAssertEqual(MachinesStrip.light(machine("a", behind: 3)), .attention)
        XCTAssertEqual(MachinesStrip.light(machine("a", unsent: 2)), .attention)
        XCTAssertEqual(MachinesStrip.light(machine("a", catchUp: MachineAwaySync(state: "reading"))), .attention)
        XCTAssertEqual(MachinesStrip.light(machine("a", catchUp: MachineAwaySync(state: "done"))), .ok)
        XCTAssertEqual(MachinesStrip.light(machine("a", connected: false)), .quiet)
        XCTAssertEqual(MachinesStrip.light(machine("a", connected: false, behind: 9, unsent: 4)), .quiet,
                       "a machine not heard from is grey; what it last reported is stale")
        XCTAssertEqual(MachinesStrip.light(machine("a", connected: true, revoked: true)), .quiet)
    }

    func testTheHouseIsTheBackendsHomeAndTheServerOnAnOlderBackend() {
        let server = machine(nil, "device-s", role: "server", home: false)
        let other = machine("b", "device-b")
        XCTAssertTrue(MachinesStrip.isHome(server, in: [server, other]), "an older backend names no home: the server is it")
        XCTAssertFalse(MachinesStrip.isHome(other, in: [server, other]))
        let moved = machine("b", "device-b", home: true)
        XCTAssertFalse(MachinesStrip.isHome(server, in: [server, moved]), "once the backend names one, only it wears the house")
        XCTAssertTrue(MachinesStrip.isHome(moved, in: [server, moved]))
    }

    func testTheCountIsShownOnlyAboveZeroAndARemovedDeviceSaysSo() {
        XCTAssertNil(MachinesStrip.chipCount(machine("a", queue: 0)))
        XCTAssertEqual(MachinesStrip.chipCount(machine("a", queue: 3)), 3)
        XCTAssertEqual(MachinesStrip.displayName(machine("a", "device-a")), "device-a")
        XCTAssertEqual(MachinesStrip.displayName(machine("a", "device-a", revoked: true)), "device-a (removed)")
        XCTAssertEqual(MachinesStrip.displayName(machine("a", "Removed device", revoked: true)), "Removed device",
                       "the backend's own placeholder is not said twice")
    }

    /// The light is never alone: the help (and the VoiceOver label) says it in words.
    func testTheHelpSaysWhatTheLightAndTheHouseMean() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let fiveMin = ISO8601DateFormatter().string(from: now.addingTimeInterval(-5 * 60))
        let server = machine(nil, "device-s", role: "server", home: true, keepsCopy: true)
        let behind = machine("b", "device-b", how: "tailscale", queue: 2, keepsCopy: true, behind: 3, lastSeenAt: fiveMin)
        let all = [server, behind]
        XCTAssertEqual(MachinesStrip.help(server, in: all, now: now), "device-s — runs Sleep")
        XCTAssertEqual(MachinesStrip.help(behind, in: all, now: now),
                       "device-b — keeps a copy over Tailscale · 3 changes behind · 2 waiting · heard from 5 min ago")
        let gone = machine("c", "device-c", connected: false, lastSeenAt: fiveMin)
        XCTAssertEqual(MachinesStrip.help(gone, in: all + [gone], now: now), "device-c — last heard from 5 min ago")
        let never = machine("d", "device-d", connected: false)
        XCTAssertEqual(MachinesStrip.help(never, in: all + [never], now: now), "device-d — not heard from yet")
        let removed = machine("e", "device-e", queue: 1, revoked: true)
        XCTAssertEqual(MachinesStrip.help(removed, in: all + [removed], now: now),
                       "device-e (removed) — 1 waiting · removed, its conversations still wait")
        let unsent = machine("f", "device-f", unsent: 1)
        XCTAssertTrue(MachinesStrip.help(unsent, in: all + [unsent], now: now).contains("1 conversation not sent yet"))
    }

    /// A card says the machine it came from only when it is another one, and only with two machines or more.
    func testACardNamesAnotherMachineNeverThisOneOrTheOnlyOne() throws {
        let server = machine(nil, "device-s", role: "server", current: true)
        let other = machine("dev_a", "device-a")
        let episodes = try JSONDecoder().decode([EpisodeQueueItem].self, from: Data("""
        [{"id": "e1", "timestamp": "2026-10-22T08:00:00Z", "source": "mcp", "preview": "", "processed": false},
         {"id": "e2", "timestamp": "2026-10-22T08:00:00Z", "source": "mcp", "preview": "", "processed": false,
          "device": "dev_a"}]
        """.utf8))
        XCTAssertNil(MachinesStrip.originName(of: episodes[0], in: [server, other]), "this computer's own: no name")
        XCTAssertEqual(MachinesStrip.originName(of: episodes[1], in: [server, other]), "device-a")
        XCTAssertNil(MachinesStrip.originName(of: episodes[1], in: [server]), "one machine has nothing to tell apart")
        // On a client, the server is the other machine.
        let client = machine("dev_a", "device-a", current: true)
        let home = machine(nil, "device-s", role: "server")
        XCTAssertEqual(MachinesStrip.originName(of: episodes[0], in: [home, client]), "device-s")
        XCTAssertNil(MachinesStrip.originName(of: episodes[1], in: [home, client]))
        let item = episodes[1]
        XCTAssertTrue(EpisodeRowText.footer(item, target: nil, machine: "device-a").contains("device-a"))
        XCTAssertFalse(EpisodeRowText.footer(item, target: nil).contains("device-a"))
    }

    func testAMachinesQueueIsItsOwnEpisodesAndTheServersHaveNoDevice() throws {
        let list = try JSONDecoder().decode(MachineStatusList.self, from: Data(wire.utf8))
        let episodes = try JSONDecoder().decode([EpisodeQueueItem].self, from: Data("""
        [{"id": "e1", "timestamp": "2026-10-22T08:00:00Z", "source": "mcp", "preview": "", "processed": false},
         {"id": "e2", "timestamp": "2026-10-22T08:00:00Z", "source": "mcp", "preview": "", "processed": false,
          "device": "dev_a"}]
        """.utf8))
        XCTAssertEqual(MachinesStrip.episodes(episodes, machine: list.devices[0]).map(\.id), ["e1"])
        XCTAssertEqual(MachinesStrip.episodes(episodes, machine: list.devices[1]).map(\.id), ["e2"])
        XCTAssertEqual(MachinesStrip.episodes(episodes, machine: nil).count, 2)
    }

    /// The strip's poll lives on the view model (no Sleep view reaches `APIClient`, R-Z10); a failed poll keeps the
    /// last answer rather than blanking the strip.
    @MainActor
    func testThePollKeepsTheLastAnswerWhenOneFails() async throws {
        let list = try JSONDecoder().decode(MachineStatusList.self, from: Data(wire.utf8))
        var replies: [Result<MachineStatusList, Error>] = [.success(list), .failure(URLError(.notConnectedToInternet))]
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let vm = SleepViewModel(store: store, fetchMachines: { try replies.removeFirst().get() })
        XCTAssertTrue(vm.machines.isEmpty)
        await vm.loadMachines()
        XCTAssertEqual(vm.machines.map(\.id), ["server", "dev_a", "dev_b"])
        await vm.loadMachines()
        XCTAssertEqual(vm.machines.map(\.id), ["server", "dev_a", "dev_b"], "a failed poll never blanks the strip")
    }
}
