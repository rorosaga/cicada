import XCTest
@testable import CicadaApp

/// G212 — the Sleep page's machines strip: each machine by its own name, how, what waits; a machine's queue.
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

    func testTheWireDecodesAndEachLineSaysNameHowAndWaiting() throws {
        let list = try JSONDecoder().decode(MachineStatusList.self, from: Data(wire.utf8))
        XCTAssertEqual(list.devices.map(\.id), ["server", "dev_a", "dev_b"])
        XCTAssertEqual(MachinesStrip.line(list.devices[0]), "Studio-Mac · Local · 23 waiting")
        XCTAssertEqual(MachinesStrip.line(list.devices[1]), "server-a · Tailscale · 160 waiting")
        XCTAssertEqual(MachinesStrip.line(list.devices[2]), "laptop-b", "nothing waits, how unknown: the name alone")
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
