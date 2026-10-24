import AppKit
import XCTest
@testable import CicadaApp

// Onboarding's two sounds (owner 2026-10-24, "Yes, soft and rare"; DESIGN_RULES §9). Every test runs on a recording
// player: nothing here makes a sound or reads the Mac's real sound settings.

@MainActor
private final class RecordingPlayer: OnboardingSoundPlayer {
    private(set) var played: [(name: NSSound.Name, volume: Float)] = []
    func play(_ name: NSSound.Name, volume: Float) { played.append((name, volume)) }
}

@MainActor
final class OnboardingSoundTests: XCTestCase {
    private let audible = SystemSoundSettings(interfaceSoundsOn: true, muted: false, alertVolume: 0.5)
    private let app = OnboardingSoundHost(runningTests: false, verifyCopy: false)

    private func make(_ settings: SystemSoundSettings? = nil, host: OnboardingSoundHost? = nil)
        -> (OnboardingSound, RecordingPlayer) {
        let player = RecordingPlayer()
        let current = settings ?? audible
        return (OnboardingSound(player: player, settings: { current }, host: host ?? app), player)
    }

    func testEachMomentPlaysItsOwnSystemSoundOnceAtTheAlertVolume() {
        let (sound, player) = make()
        XCTAssertTrue(sound.moment(.permissionGranted, inDemo: false))
        XCTAssertTrue(sound.moment(.firstAgentCall, inDemo: false))
        XCTAssertEqual(player.played.map(\.name), ["Tink", "Pop"])
        XCTAssertEqual(player.played.map(\.volume), [0.5, 0.5])
    }

    func testAMomentNeverPlaysTwice() {
        let (sound, player) = make()
        sound.moment(.permissionGranted, inDemo: false)
        XCTAssertFalse(sound.moment(.permissionGranted, inDemo: false))
        XCTAssertFalse(sound.moment(.permissionGranted, inDemo: false))
        sound.moment(.firstAgentCall, inDemo: false)
        XCTAssertFalse(sound.moment(.firstAgentCall, inDemo: false))
        XCTAssertEqual(player.played.count, 2)
    }

    func testInterfaceSoundsOffIsSilent() {
        let (sound, player) = make(SystemSoundSettings(interfaceSoundsOn: false, muted: false, alertVolume: 1))
        XCTAssertFalse(sound.moment(.permissionGranted, inDemo: false))
        XCTAssertFalse(sound.moment(.firstAgentCall, inDemo: false))
        XCTAssertTrue(player.played.isEmpty)
    }

    func testAMutedMacIsSilent() {
        let (sound, player) = make(SystemSoundSettings(interfaceSoundsOn: true, muted: true, alertVolume: 1))
        XCTAssertFalse(sound.moment(.permissionGranted, inDemo: false))
        XCTAssertFalse(sound.moment(.firstAgentCall, inDemo: false))
        XCTAssertTrue(player.played.isEmpty)
    }

    func testAZeroAlertVolumeIsSilent() {
        let (sound, player) = make(SystemSoundSettings(interfaceSoundsOn: true, muted: false, alertVolume: 0))
        XCTAssertFalse(sound.moment(.firstAgentCall, inDemo: false))
        XCTAssertTrue(player.played.isEmpty)
    }

    /// A moment that happened while the Mac was silent is spent: unmuting later never replays it.
    func testASilentMomentIsSpentNotDeferred() {
        var settings = SystemSoundSettings(interfaceSoundsOn: true, muted: true, alertVolume: 1)
        let player = RecordingPlayer()
        let sound = OnboardingSound(player: player, settings: { settings }, host: app)
        sound.moment(.permissionGranted, inDemo: false)
        settings.muted = false
        XCTAssertFalse(sound.moment(.permissionGranted, inDemo: false))
        XCTAssertTrue(player.played.isEmpty)
        XCTAssertTrue(sound.moment(.firstAgentCall, inDemo: false))
    }

    func testADemoBankIsSilent() {
        let (sound, player) = make()
        XCTAssertFalse(sound.moment(.permissionGranted, inDemo: true))
        XCTAssertFalse(sound.moment(.firstAgentCall, inDemo: true))
        XCTAssertTrue(player.played.isEmpty)
    }

    func testTestsAndTheVerifyCopyAreSilent() {
        for host in [OnboardingSoundHost(runningTests: true, verifyCopy: false),
                     OnboardingSoundHost(runningTests: false, verifyCopy: true)] {
            let (sound, player) = make(host: host)
            sound.moment(.permissionGranted, inDemo: false)
            sound.moment(.firstAgentCall, inDemo: false)
            XCTAssertTrue(player.played.isEmpty, "\(host)")
        }
    }

    /// The default host is read from this process: under `swift test` it says so, so an `OnboardingSound()` built by
    /// any view a test hosts stays silent even with a player that would play.
    func testTheLiveHostKnowsItIsUnderTests() {
        XCTAssertTrue(OnboardingSoundHost.live.runningTests)
        XCTAssertFalse(OnboardingSoundHost.live.verifyCopy)
        let player = RecordingPlayer()
        let sound = OnboardingSound(player: player, settings: { self.audible })
        sound.moment(.permissionGranted, inDemo: false)
        XCTAssertTrue(player.played.isEmpty)
    }

    /// verify-cicada stamps its copy `com.rorosaga.cicada.verify.<run id>`; the person's own app is
    /// `com.rorosaga.cicada`, which must never match.
    func testTheVerifyPrefixMatchesTheVerifyStampOnly() {
        XCTAssertTrue("com.rorosaga.cicada.verify.my-check".hasPrefix(OnboardingSoundHost.verifyBundlePrefix))
        XCTAssertFalse("com.rorosaga.cicada".hasPrefix(OnboardingSoundHost.verifyBundlePrefix))
    }

    /// Both sounds are built-in macOS sounds, so nothing is bundled.
    func testTheSoundsAreTheSystemsOwn() {
        for moment in OnboardingSoundMoment.allCases {
            XCTAssertTrue(FileManager.default.fileExists(atPath: "/System/Library/Sounds/\(moment.soundName).aiff"),
                          "\(moment.soundName)")
        }
    }

    // MARK: Never outside onboarding — a source lint

    /// …/Tests/CicadaAppTests/<this file> → …/Sources/CicadaApp
    private var sourcesRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp")
    }

    /// Only `OnboardingSound.swift` makes a sound, and only `OnboardingView` holds one: no other surface plays one.
    func testOnlyOnboardingMakesASound() throws {
        let files = FileManager.default.enumerator(at: sourcesRoot, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL }.filter { $0.pathExtension == "swift" } ?? []
        XCTAssertFalse(files.isEmpty, "found no sources — the lint would pass vacuously")
        let players = ["NSSound(", "AudioServicesPlay", "NSSound.beep", "NSBeep("]
        var holders: [String] = []
        for file in files {
            let text = try String(contentsOf: file, encoding: .utf8)
            if file.lastPathComponent != "OnboardingSound.swift" {
                for needle in players where text.contains(needle) {
                    XCTFail("\(file.lastPathComponent) plays a sound (`\(needle)`): sound is allowed only for onboarding's two moments (DESIGN_RULES §9, 2026-10-24)")
                }
            }
            if text.contains("OnboardingSound()") || text.contains(".moment(.") { holders.append(file.lastPathComponent) }
        }
        XCTAssertEqual(holders, ["OnboardingView.swift"])
    }
}
