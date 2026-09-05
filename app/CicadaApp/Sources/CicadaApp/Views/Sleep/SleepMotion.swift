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

    static func settle(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: settleDuration)
    }

    static func pile(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: pileDuration)
    }

    static func disclosure(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: disclosureDuration)
    }
}
