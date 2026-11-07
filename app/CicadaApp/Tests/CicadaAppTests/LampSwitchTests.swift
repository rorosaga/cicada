import AppKit
import XCTest
@testable import CicadaApp

// The lamp's second door and its click (owner 2026-11-07). Every test runs on a recording player: nothing here makes a
// sound or reads the Mac's real sound settings.

@MainActor
private final class RecordingLampPlayer: LampSoundPlayer {
    private(set) var played: [(LampSoundMoment, Float)] = []
    func play(_ moment: LampSoundMoment, volume: Float) { played.append((moment, volume)) }
}

@MainActor
final class LampSwitchTests: XCTestCase {
    private let audible = SystemSoundSettings(interfaceSoundsOn: true, muted: false, alertVolume: 0.5)
    private let app = OnboardingSoundHost(runningTests: false, verifyCopy: false)

    private func lamp(_ settings: SystemSoundSettings? = nil, host: OnboardingSoundHost? = nil)
        -> (LampSound, RecordingLampPlayer) {
        let player = RecordingLampPlayer()
        let current = settings ?? audible
        return (LampSound(player: player, settings: { current }, host: host ?? app), player)
    }

    func testEachDirectionClicksItsOwnSoundAtTheAlertVolume() {
        let (sound, player) = lamp()
        XCTAssertTrue(sound.click(on: true, inDemo: false))
        XCTAssertTrue(sound.click(on: false, inDemo: false))
        XCTAssertEqual(player.played.map(\.0), [.on, .off])
        XCTAssertEqual(player.played.map(\.1), [0.5, 0.5])
    }

    func testTheMacsSoundSettingsAndTheHostDecide() {
        for quiet in [SystemSoundSettings(interfaceSoundsOn: false, muted: false, alertVolume: 1),
                      SystemSoundSettings(interfaceSoundsOn: true, muted: true, alertVolume: 1),
                      SystemSoundSettings(interfaceSoundsOn: true, muted: false, alertVolume: 0)] {
            let (sound, player) = lamp(quiet)
            XCTAssertFalse(sound.click(on: true, inDemo: false))
            XCTAssertTrue(player.played.isEmpty)
        }
        for host in [OnboardingSoundHost(runningTests: true, verifyCopy: false),
                     OnboardingSoundHost(runningTests: false, verifyCopy: true)] {
            let (sound, player) = lamp(host: host)
            XCTAssertFalse(sound.click(on: true, inDemo: false))
            XCTAssertTrue(player.played.isEmpty)
        }
        let (sound, player) = lamp()
        XCTAssertFalse(sound.click(on: true, inDemo: true), "never in a demo bank")
        XCTAssertTrue(player.played.isEmpty)
    }

    func testBothClicksAreBundledSmallAndShort() throws {
        for moment in LampSoundMoment.allCases {
            let url = try XCTUnwrap(Bundle.cicadaResources.cicadaResource(moment.rawValue, ext: "wav", in: "sounds"))
            let size = try FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int ?? .max
            XCTAssertLessThan(size, 20_000, moment.rawValue)
            let sound = try XCTUnwrap(NSSound(contentsOf: url, byReference: true))
            XCTAssertLessThanOrEqual(sound.duration, 0.3, moment.rawValue)
        }
    }

    // MARK: One state, one write

    private func makeVM(put: @escaping (ScheduleConfig) async throws -> ScheduleConfig, sound: LampSound) -> SleepViewModel {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let vm = SleepViewModel(store: store, putSchedule: put)
        vm.lampSound = sound
        return vm
    }

    func testTheSwitchWritesThroughTheOneRuleAndClicksOnce() async throws {
        let (sound, player) = lamp()
        var sent: [ScheduleConfig] = []
        let vm = makeVM(put: { sent.append($0); return $0 }, sound: sound)
        XCTAssertFalse(vm.lampSwitchOn)
        let task = try XCTUnwrap(vm.setLamp(true))
        XCTAssertTrue(vm.lampSwitchOn, "the switch shows the value in flight")
        XCTAssertNil(vm.setLamp(false), "a second flip waits for the first")
        await task.value
        XCTAssertEqual(sent.map(\.mode), ["daily"])
        XCTAssertTrue(vm.lampSwitchOn)
        XCTAssertNil(vm.lampWriting)
        XCTAssertEqual(player.played.map(\.0), [.on])
        await vm.setLamp(false)?.value
        XCTAssertFalse(vm.lampSwitchOn)
        XCTAssertEqual(vm.schedule.mode, "manual")
        XCTAssertEqual(player.played.map(\.0), [.on, .off])
    }

    func testAFailedWriteSnapsBackWithNoClick() async throws {
        struct Refused: Error {}
        let (sound, player) = lamp()
        let vm = makeVM(put: { _ in throw Refused() }, sound: sound)
        await vm.setLamp(true)?.value
        XCTAssertFalse(vm.lampSwitchOn, "still the schedule the backend has")
        XCTAssertTrue(vm.lampWriteFailed)
        XCTAssertTrue(player.played.isEmpty)
    }

    func testFlippingToWhatItAlreadyIsMakesNoClick() async throws {
        let (sound, player) = lamp()
        let vm = makeVM(put: { $0 }, sound: sound)
        await vm.setLamp(false)?.value
        XCTAssertTrue(player.played.isEmpty)
    }
}
