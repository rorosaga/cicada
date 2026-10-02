import SwiftUI

/// Sleep's chrome timings. Sprite frame timings are sheet data within CicadaMotion's caps (ruling 18).
/// Reduce Motion jumps chrome transitions and holds sprite key frames.
enum SleepMotion {

    /// The ceiling every settle on this page sits under.
    static let maxDuration: TimeInterval = CicadaMotion.maxDuration

    /// A value-driven bar easing between two readings — the hero meter's
    /// blocks and the stage strip's Read fill. Short enough that a live cycle
    /// reads as *moving*, never as *drifting*.
    static let settleDuration: TimeInterval = CicadaMotion.settleDuration

    /// The book pile restacking when a cycle reads through it. Slightly
    /// longer than a bar because several spines move at once and the eye is
    /// tracking a shape, not a length.
    static let pileDuration: TimeInterval = 0.4

    /// A row opening or closing under the reader's own click. Fast, because
    /// the reader asked for it and is already looking at the answer.
    static let disclosureDuration: TimeInterval = 0.15

    // Track Z Z5 — the room responds.

    /// The status ⇄ answer cross-fade in the sentence slot (opacity only — a
    /// slot whose height is reserved never slides).
    static let sentenceDuration: TimeInterval = 0.18
    /// A rate limit, not an animation: one perk per two seconds however the
    /// pointer wanders in and out of the worm (§6.2 — a worm that twitches on
    /// every crossing is noise, not a response).
    static let perkCooldown: TimeInterval = 2
    /// A dwell, not an animation (I4): an answer returns to the status sentence
    /// after this long with the pointer outside the room and the sentence.
    static let answerDwell: Duration = .seconds(12)

    // Track Z Z6 — the props become controls.

    /// A spine lifting under the pointer (§7.1), and — with feeding — the drop
    /// outline. Quick, because it answers a pointer that is already there.
    static let hoverDuration: TimeInterval = CicadaMotion.hoverDuration

    // Track Z Z8 — the window shows weather.

    /// The window's pane crossfading on a mood change (R-Z12's one state beat
    /// besides the cheer) — at the ceiling, never above it.
    static let weatherDuration: TimeInterval = 0.4

    static func settle(reduceMotion: Bool) -> Animation? {
        CicadaMotion.settle(reduceMotion: reduceMotion)
    }

    static func pile(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: pileDuration)
    }

    static func disclosure(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: disclosureDuration)
    }

    static func sentence(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: sentenceDuration)
    }

    /// Meadow's hover: easeInOut since Z10 (it was easeOut; both 0.15 s).
    static func hover(reduceMotion: Bool) -> Animation? {
        CicadaMotion.hover(reduceMotion: reduceMotion)
    }

    static func weather(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: weatherDuration)
    }
}
