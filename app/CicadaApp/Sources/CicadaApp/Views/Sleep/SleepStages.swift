import SwiftUI

// MARK: - The five stages, once (G125 v3 Task 5 — spec R-A8, plan P15/P16)
//
// 2026-11-26: the page's stepper retired (`SleepRunObject.swift` says the one running step in a word); the five stages
// stay as the sentence's words, the popover's rows and the run object's `.help`.

/// One stage of the nightly batch. `title` is DERIVED (`"Stage 2 · Sort"`)
/// rather than stored so the popover's long form and the strip's short label
/// can never disagree about which number a stage is.
///
/// The five `detail` strings are the popover's own copy, moved here verbatim
/// — this type is a hoist, not a rewrite (P16).
struct SleepStage: Identifiable, Equatable {
    let id: String
    /// 1…5, in pipeline order. `SleepStatusResponse.stage` counts COMPLETED
    /// stages, so a running cycle's active stage is `activeStage(completed:)`
    /// — the one translation (R-Z14), read by the strip, the page mood, the
    /// menu bar and onboarding alike.
    let number: Int
    /// The short word: one syllable of the pipeline, no numeral.
    let shortLabel: String
    /// The word for this stage while it runs ("Sorting…", Track Z
    /// L5) — stored beside `shortLabel` so the sentence and the run object read one
    /// array (P16) instead of a second map that could drift.
    let progressive: String
    /// The popover's sentence.
    let detail: String
    /// SF Symbol for the popover row.
    let symbol: String

    /// `"Stage 3 · Decide"` — the popover's row title, composed rather than
    /// typed a second time.
    var title: String { "Stage \(number) · \(shortLabel)" }
}

/// **The one array (P16).** Both the Sleep page's run object and the `?`
/// popover (*How Cicada sleeps*) read this; `HowSleepWorksContent`'s own
/// docstring already declares it "not a second source of truth" for the
/// pipeline, and a second hand-typed list inside the strip would have made it
/// one anyway. The reference sketch's Collect/Cluster/Extract/Strengthen
/// naming was refused for the same reason: it would be a fourth name for the
/// five stages `CLAUDE.md`, `sleep_cycle.py` and this popover already agree on.
enum SleepStages {
    static let all: [SleepStage] = [
        SleepStage(id: "stage1", number: 1, shortLabel: "Read", progressive: "Reading",
                   detail: "Each episode is read once for people, projects, tools and ideas.",
                   symbol: "book"),
        SleepStage(id: "stage2", number: 2, shortLabel: "Sort", progressive: "Sorting",
                   detail: "New mentions are matched against what you already have.",
                   symbol: "arrow.triangle.merge"),
        SleepStage(id: "stage3", number: 3, shortLabel: "Decide", progressive: "Deciding",
                   detail: "Contradictions become questions on Home; old beliefs fade.",
                   symbol: "questionmark.circle"),
        SleepStage(id: "stage4", number: 4, shortLabel: "Notice", progressive: "Noticing",
                   detail: "Habits that recur become skills.",
                   symbol: "sparkles"),
        SleepStage(id: "stage5", number: 5, shortLabel: "File", progressive: "Filing",
                   detail: "Everything is written to the graph and committed with its provenance.",
                   symbol: "checkmark.seal"),
    ]

    /// The breathing period of the current stage's live dot, in seconds (R-A13's
    /// motion budget: nothing on this page cycles faster than 1.2 s). Named, not
    /// a literal inside a view, so the budget is assertable in a test; the dot
    /// breathes on its own layer (`LiveDot`), never through a `TimelineView`.
    static let pulsePeriod: TimeInterval = 1.2

    /// The dimmest the live dot ever gets. A dot that fades toward 0 reads
    /// as "gone" rather than "working", which is the opposite of what a live
    /// instrument should say.
    static let pulseFloor: Double = 0.55
}
