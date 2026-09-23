import SwiftUI

/// The Sleep page's motion budget, as numbers instead of habits (G125 v3
/// Task 8, spec R-A13). The budget itself is written out in prose above
/// `SleepView` — this file is the one place its durations are spelled, and
/// `SleepNumbersLintTests` fails the build on a literal `duration:` anywhere
/// else under `Views/Sleep/` (the same exemption shape
/// `FontLiteralLintTests` grants `Theme/CicadaTheme.swift`).
///
/// Two rules the type exists to make unforgettable:
///
/// - **Nothing here exceeds `maxDuration`.** The stage pulse is the single
///   exception and lives on `SleepStages.pulsePeriod` with its own ≤ 1.2 s
///   cap, because a breath is a *state* indicator and a settle is a
///   *transition*.
/// - **Reduce Motion returns `nil`, which is SwiftUI for "jump to the new
///   value".** That is the terminal frame, the same place
///   `BookwormView.frameIndex(…reduceMotion:)` and `stagePulse(…)` hold. A
///   `.animation(...)` modifier that takes a non-optional literal is how
///   Reduce Motion gets silently skipped, which is exactly what this replaced
///   on the hero meter and the stage strip.
enum SleepMotion {

    /// The ceiling every settle on this page sits under.
    static let maxDuration: TimeInterval = 0.4

    /// A value-driven bar easing between two readings — the hero meter's
    /// blocks and the stage strip's Read fill. Short enough that a live cycle
    /// reads as *moving*, never as *drifting*.
    static let settleDuration: TimeInterval = 0.35

    /// The book pile restacking when a cycle reads through it. Slightly
    /// longer than a bar because several spines move at once and the eye is
    /// tracking a shape, not a length.
    static let pileDuration: TimeInterval = 0.4

    /// A row opening or closing under the reader's own click. Fast, because
    /// the reader asked for it and is already looking at the answer.
    static let disclosureDuration: TimeInterval = 0.15

    // Track Z Z5 — the room responds. Named to mirror Meadow's `CicadaMotion`
    // so Z10's swap is a rename, not a re-derivation.

    /// One beat frame (R-Z12) — pinned equal to `BookwormSprites.reactionInterval`
    /// by `SleepNumbersLintTests`, so the sprite and the page share one beat clock.
    static let beatFrameInterval: TimeInterval = 0.12
    /// Every beat is at most three frames, so ≤ 0.36 s ≤ `maxDuration`.
    static let maxBeatFrames = 3
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
    static let hoverDuration: TimeInterval = 0.15

    // Track Z Z8 — the window shows weather.

    /// The window's pane crossfading on a mood change (R-Z12's one state beat
    /// besides the cheer) — at the ceiling, never above it.
    static let weatherDuration: TimeInterval = 0.4

    static func settle(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: settleDuration)
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

    static func hover(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeOut(duration: hoverDuration)
    }

    static func weather(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: weatherDuration)
    }
}
