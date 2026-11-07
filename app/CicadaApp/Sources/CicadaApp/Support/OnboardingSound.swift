import AppKit
import AudioToolbox
import CoreAudio

// Onboarding's two sounds (owner 2026-10-24, "Yes, soft and rare"; DESIGN_RULES §9, after HeyClicky's onboarding). The
// only sound in Cicada: one short built-in macOS sound when a permission lands and one when the person's agent first
// calls, each at most once per onboarding run, at the Mac's alert volume. Silent when the person turned off "Play user
// interface sound effects", when the Mac is muted, under `swift test`, in a demo bank and in a verify-cicada copy.
// Nothing is bundled: the sounds are macOS's own (`NSSound(named:)`), so there is nothing to license. The player and the
// Mac's sound settings are injected, so tests never make a sound.

/// The two moments, and the macOS sound each one plays.
enum OnboardingSoundMoment: CaseIterable, Hashable {
    /// The drag helper or a preflight sees a permission the person was asked for granted.
    case permissionGranted
    /// The Agents step's live check: the person's agent called Cicada for the first time (`FirstAgentCall`).
    case firstAgentCall

    /// A built-in sound in `/System/Library/Sounds`, the shortest and quietest two: Tink is a tap, Pop a lighter click.
    var soundName: NSSound.Name {
        switch self {
        case .permissionGranted: "Tink"
        case .firstAgentCall: "Pop"
        }
    }
}

/// What the Mac's own sound settings say right now.
struct SystemSoundSettings: Equatable {
    /// System Settings → Sound → "Play user interface sound effects".
    var interfaceSoundsOn: Bool
    /// The default output device is muted (or its volume is at zero).
    var muted: Bool
    /// System Settings → Sound → Alert volume, 0…1 of the output volume.
    var alertVolume: Float

    /// Reads the live settings: the two keys macOS keeps in the global domain (falling back to `com.apple.systemsound`,
    /// where older systems keep them; absent means the system default, on and full), and the default output device's
    /// mute and volume through Core Audio (a device with neither property reads as not muted).
    static func live() -> SystemSoundSettings {
        SystemSoundSettings(interfaceSoundsOn: preference("com.apple.sound.uiaudio.enabled")?.boolValue ?? true,
                            muted: OutputDevice.isMuted(),
                            alertVolume: preference("com.apple.sound.beep.volume")?.floatValue ?? 1)
    }

    /// A number, never a bridged `Float` cast: `0.519374 as? Float` fails because the double is not exact in a float.
    private static func preference(_ key: String) -> NSNumber? {
        if let value = UserDefaults.standard.object(forKey: key) as? NSNumber { return value }
        return CFPreferencesCopyAppValue(key as CFString, "com.apple.systemsound" as CFString) as? NSNumber
    }

    /// The default output device through Core Audio: muted, or its main volume at zero.
    private enum OutputDevice {
        static func isMuted() -> Bool {
            guard let device = defaultOutput() else { return false }
            if let mute: UInt32 = read(device, kAudioDevicePropertyMute), mute != 0 { return true }
            if let volume: Float32 = read(device, kAudioHardwareServiceDeviceProperty_VirtualMainVolume), volume <= 0 {
                return true
            }
            return false
        }

        private static func defaultOutput() -> AudioObjectID? {
            var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultOutputDevice,
                                                     mScope: kAudioObjectPropertyScopeGlobal,
                                                     mElement: kAudioObjectPropertyElementMain)
            var device = AudioObjectID(kAudioObjectUnknown)
            var size = UInt32(MemoryLayout<AudioObjectID>.size)
            let status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil,
                                                    &size, &device)
            return status == noErr && device != kAudioObjectUnknown ? device : nil
        }

        private static func read<T>(_ device: AudioObjectID, _ selector: AudioObjectPropertySelector) -> T? {
            var address = AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioDevicePropertyScopeOutput,
                                                     mElement: kAudioObjectPropertyElementMain)
            guard AudioObjectHasProperty(device, &address) else { return nil }
            let value = UnsafeMutablePointer<T>.allocate(capacity: 1)
            defer { value.deallocate() }
            var size = UInt32(MemoryLayout<T>.size)
            guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, value) == noErr else { return nil }
            return value.pointee
        }
    }
}

/// Plays a named macOS sound. Live: `NSSound(named:)`; tests pass a recorder.
@MainActor
protocol OnboardingSoundPlayer {
    func play(_ name: NSSound.Name, volume: Float)
}

struct LiveOnboardingSoundPlayer: OnboardingSoundPlayer {
    func play(_ name: NSSound.Name, volume: Float) {
        // A second guard: a live player made under `swift test` stays silent whatever the caller decided.
        guard !AppPasteboard.isRunningTests, let sound = NSSound(named: name)?.copy() as? NSSound else { return }
        sound.volume = volume
        sound.play()
    }
}

/// Where this process runs: under `swift test`, or as a verify-cicada copy (its bundle id `com.rorosaga.cicada.verify.<run>`).
struct OnboardingSoundHost: Equatable {
    var runningTests: Bool
    var verifyCopy: Bool

    static let verifyBundlePrefix = "com.rorosaga.cicada.verify."

    static var live: OnboardingSoundHost {
        OnboardingSoundHost(runningTests: AppPasteboard.isRunningTests,
                            verifyCopy: Bundle.main.bundleIdentifier?.hasPrefix(verifyBundlePrefix) == true)
    }
}

/// One onboarding run's sounds. The view holds one for the run; each moment is spent the first time it happens —
/// played if the Mac allows it then, silent if not — and never plays again in this run, so a second permission or a
/// second agent never makes a second sound. Never a response to a key or a click in Cicada: both moments are events
/// from outside it (System Settings, the person's agent), so DR-60's keyboard rule has nothing to hold back.
@MainActor
final class OnboardingSound {
    private(set) var spent: Set<OnboardingSoundMoment> = []

    private let player: any OnboardingSoundPlayer
    private let settings: () -> SystemSoundSettings
    private let host: OnboardingSoundHost

    /// Nil `player`: the live `NSSound` one.
    init(player: (any OnboardingSoundPlayer)? = nil,
         settings: @escaping () -> SystemSoundSettings = SystemSoundSettings.live,
         host: OnboardingSoundHost = .live) {
        self.player = player ?? LiveOnboardingSoundPlayer()
        self.settings = settings
        self.host = host
    }

    /// The moment happened. Returns whether a sound played.
    @discardableResult
    func moment(_ moment: OnboardingSoundMoment, inDemo: Bool) -> Bool {
        guard spent.insert(moment).inserted else { return false }
        guard !host.runningTests, !host.verifyCopy, !inDemo else { return false }
        let now = settings()
        guard Self.audible(now) else { return false }
        player.play(moment.soundName, volume: now.alertVolume)
        return true
    }

    /// The person's own settings allow a sound: interface sounds on, not muted, an alert volume above zero.
    static func audible(_ settings: SystemSoundSettings) -> Bool {
        settings.interfaceSoundsOn && !settings.muted && settings.alertVolume > 0
    }
}
