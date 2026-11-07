import AppKit

// The lamp's click (owner 2026-11-07: "add also a sfx for it"; DESIGN_RULES §9, 2026-11-07). The second sound in Cicada
// after onboarding's two, and the first Cicada makes itself: two short clicks synthesised for it by
// `scripts/make_lamp_sounds.py` (original, nothing sampled, nothing to license), `Resources/sounds/lamp-on.wav` and
// `lamp-off.wav`, about 110 ms each. It plays when the schedule really changed (the write landed), whichever of the
// lamp's two doors made the change, at the Mac's alert volume, and by the same rules as onboarding's: silent when "Play
// user interface sound effects" is off, the Mac is muted or the alert volume is zero, and never under `swift test`, in a
// demo bank or in a verify-cicada copy.

enum LampSoundMoment: String, CaseIterable {
    case on = "lamp-on"
    case off = "lamp-off"

    static func landing(on: Bool) -> LampSoundMoment { on ? .on : .off }
}

/// Plays one bundled click. Live: `NSSound(contentsOf:)`; tests pass a recorder.
@MainActor
protocol LampSoundPlayer {
    func play(_ moment: LampSoundMoment, volume: Float)
}

struct LiveLampSoundPlayer: LampSoundPlayer {
    func play(_ moment: LampSoundMoment, volume: Float) {
        // A second guard: a live player made under `swift test` stays silent whatever the caller decided.
        guard !AppPasteboard.isRunningTests,
              let url = Bundle.cicadaResources.cicadaResource(moment.rawValue, ext: "wav", in: "sounds"),
              let sound = NSSound(contentsOf: url, byReference: true) else { return }
        sound.volume = volume
        sound.play()
    }
}

@MainActor
final class LampSound {
    private let player: any LampSoundPlayer
    private let settings: () -> SystemSoundSettings
    private let host: OnboardingSoundHost

    init(player: (any LampSoundPlayer)? = nil,
         settings: @escaping () -> SystemSoundSettings = SystemSoundSettings.live,
         host: OnboardingSoundHost = .live) {
        self.player = player ?? LiveLampSoundPlayer()
        self.settings = settings
        self.host = host
    }

    /// The lamp went on or off. Returns whether a click played.
    @discardableResult
    func click(on: Bool, inDemo: Bool) -> Bool {
        guard !host.runningTests, !host.verifyCopy, !inDemo else { return false }
        let now = settings()
        guard OnboardingSound.audible(now) else { return false }
        player.play(.landing(on: on), volume: now.alertVolume)
        return true
    }
}
