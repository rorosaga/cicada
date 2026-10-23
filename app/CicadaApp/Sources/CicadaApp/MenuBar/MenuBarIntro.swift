import Foundation

/// Owner 2026-10-23 — the menu-bar bookworm waits until onboarding has introduced it: "have the little worm with the
/// number appear only after explaining it … then when clicking next it appears in the taskbar." Its own per-viewer key,
/// beside the person's Show in menu bar switch (`MenuBarPreference`), which keeps its key and meaning: the worm shows
/// only when the switch is on AND the intro is not waiting.
///
/// Hyrum (mode B): `cicada.menuBar.visible` is untouched. The new key `cicada.menuBar.intro` holds a word — `waiting`
/// or `done` — and an absent key reads `done`, so everyone who ran an earlier build keeps their worm exactly as it was.
/// It is written `waiting` only once, at the launch of a fresh install (no `cicada.` key in this app's defaults yet),
/// so the worm never flashes in the menu bar for the seconds the backend takes to answer the first-run gate.
enum MenuBarIntro {
    static let defaultsKey = "cicada.menuBar.intro"

    enum Phase: String, Equatable {
        /// Onboarding has not introduced the worm yet: the status item stays hidden.
        case waiting
        /// Introduced, skipped, or a person from before this gate: the switch alone decides.
        case done
    }

    static func phase(_ defaults: UserDefaults = .standard) -> Phase {
        defaults.string(forKey: defaultsKey).flatMap(Phase.init(rawValue:)) ?? .done
    }

    /// The menu-bar item shows when the person's switch is on and the intro is not waiting.
    static func shows(preference: Bool, phase: Phase) -> Bool {
        preference && phase != .waiting
    }

    /// A fresh install has none of Cicada's own keys yet. Any `cicada.` key means an earlier run of this app (an
    /// onboarded bank, a theme, a step reached, the switch itself), and that person's worm is left alone.
    static func isFreshInstall(keys: some Sequence<String>) -> Bool {
        !keys.contains { $0.hasPrefix("cicada.") }
    }

    /// Called once, first thing at launch, before anything writes a `cicada.` key. Writes `waiting` only on a fresh
    /// install whose key is absent; every other launch reads what is stored.
    @discardableResult
    static func prepareAtLaunch(_ defaults: UserDefaults = .standard,
                                keys: (() -> [String])? = nil) -> Phase {
        guard defaults.object(forKey: defaultsKey) == nil else { return phase(defaults) }
        let existing = keys?() ?? Array(defaults.dictionaryRepresentation().keys)
        if isFreshInstall(keys: existing) {
            defaults.set(Phase.waiting.rawValue, forKey: defaultsKey)
            return .waiting
        }
        return .done
    }

    /// The step was passed (Continue, ⏎ or Skip), onboarding ended any other way, or the first-run gate decided no
    /// onboarding is coming. Never set back to waiting: a rerun meets a worm already in the menu bar.
    static func finish(_ defaults: UserDefaults = .standard) {
        defaults.set(Phase.done.rawValue, forKey: defaultsKey)
    }

    /// Whether a waiting worm should be let out without its step: every input of the first-run gate is known and the
    /// gate will not raise onboarding (a bank with pages, an onboarded bank, the demo), and onboarding is not showing.
    /// Unknown is never "no onboarding" — the gate's own rule (`FirstRunGate`).
    static func settlesWithoutStep(bankResolved: Bool, graphLoaded: Bool, gateShows: Bool,
                                   onboardingShowing: Bool) -> Bool {
        bankResolved && graphLoaded && !gateShows && !onboardingShowing
    }
}

/// How the waiting worm arrives in the menu bar.
enum MenuBarReveal: Equatable {
    /// The step's Continue by pointer: the worm flies from the step to its place (`MenuBarFlight`).
    case fly(from: CGRect)
    /// Reduce Motion: no flight, the status item fades in (DR-66).
    case fade
    /// ⏎ (a key never animates, DR-60), Skip, Set up later, the demo, or the gate settling: it is simply there.
    case instant

    /// Reduce Motion turns a flight into a fade; nothing else changes.
    func resolved(reduceMotion: Bool) -> MenuBarReveal {
        if case .fly = self, reduceMotion { return .fade }
        return self
    }
}
