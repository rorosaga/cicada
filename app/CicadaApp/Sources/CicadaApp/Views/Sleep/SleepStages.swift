import SwiftUI

// MARK: - The five stages, once (G125 v3 Task 5 — spec R-A8, plan P15/P16)

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
    /// The strip's word: one syllable of the pipeline, no numeral.
    let shortLabel: String
    /// The sentence's word for this stage while it runs ("Sorting…", Track Z
    /// L5) — stored beside `shortLabel` so the strip and the sentence read one
    /// array (P16) instead of a second map that could drift.
    let progressive: String
    /// The popover's sentence.
    let detail: String
    /// SF Symbol for the popover row (the stepper draws a state marker instead).
    let symbol: String

    /// `"Stage 3 · Decide"` — the popover's row title, composed rather than
    /// typed a second time.
    var title: String { "Stage \(number) · \(shortLabel)" }
}

/// **The one array (P16).** Both the Sleep page's stage strip and the `?`
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
                   detail: "Contradictions become questions in your Inbox; old beliefs fade.",
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

// MARK: - The strip's state

/// What one pip in the strip is showing.
///
/// `active(fill:)` carries a fraction for **Read only** (P15). Stages 2–5 have
/// no per-episode unit at all — `sleep_cycle.progress_pct` returns `None` past
/// stage 0 — so a fraction there would be invented, and inventing one is
/// exactly the "bare percentage with no noun" this page refuses.
enum StagePip: Equatable {
    /// Finished in the cycle the strip is describing.
    case done
    /// Running right now. `fill` is Read's `read / total`, and `nil` for every
    /// other stage (and for Read itself before the cycle has any totals).
    case active(fill: Double?)
    /// Not started, and something is still expected to start it.
    case pending
    /// Never reached, and never will be — the cycle stopped first. Distinct
    /// from `pending` on purpose: nothing is coming.
    case skipped
    /// The stage the cycle died in.
    case failed

    /// The text twin of the pip's colour, for VoiceOver. Every art bit on this
    /// page has one (R-A15).
    var accessibilityWord: String {
        switch self {
        case .done: "done"
        case .active: "in progress"
        case .pending: "not started"
        case .skipped: "not reached"
        case .failed: "failed"
        }
    }
}

/// The whole strip, as a pure function of the cycle's state — always exactly
/// five pips, one per `SleepStages.all` entry, in order.
///
/// `stage` is `SleepStatusResponse.stage`: the number of stages that have
/// **completed** (`sleep_cycle.py` sets `_state.stage = 1` only after Stage 1
/// returns). So while running, index `stage` is the stage in flight; when
/// idle, `stage` is simply how far the last cycle got.
///
/// **A cancel or a failure freezes the strip where it stopped (P15).** The
/// obvious implementation — reset to all-pending once `isRunning` goes false —
/// would erase the two or three stages that really ran, which is the one thing
/// a person wants to see after cancelling. Stages the cycle never reached are
/// `skipped`, not `pending`: nothing is coming to run them.
///
/// `error` outranks `cancelled` because a failed cycle is the news (the same
/// precedence `deriveSleepPageMood` gives `.error`), and both outrank the idle
/// reading below them.
func stageStripState(stage: Int, isRunning: Bool, cancelled: Bool, error: Bool,
                     read: Int, total: Int, stages: [SleepDrainInfo.Stage]? = nil) -> [StagePip] {
    // A backend that reports a stage outside 0…5 is a bug; clamp rather than
    // index out of range, so a bad number degrades to a plausible strip.
    let done = max(0, min(SleepStages.all.count, stage))
    return SleepStages.all.indices.map { index in
        if index < done { return .done }
        if error {
            // `index == done` is the stage it died in; the ones after it were
            // never reached. A cycle that failed after Stage 5 has no pip left
            // to fail on and simply reads as five done.
            return index == done ? .failed : .skipped
        }
        if cancelled { return .skipped }
        guard isRunning else { return .pending }
        guard index == activeStage(completed: stage) - 1 else { return .pending }
        // Read, Sort and Decide carry a fill — only from finished work over a total fixed when the stage began
        // (P15 as amended, Sleep page v5); Notice and File never do.
        if index == 1 || index == 2, let counted = stages?.first(where: { $0.id == (index == 1 ? "sort" : "decide") }),
           let stageTotal = counted.total, stageTotal > 0 {
            return .active(fill: Double(min(counted.done, stageTotal)) / Double(stageTotal))
        }
        let isRead = index == 0
        guard isRead, total > 0 else { return .active(fill: nil) }
        return .active(fill: Double(read) / Double(total))
    }
}

/// R-Z6 — whether the strip is on the page at all. It is the live instrument
/// while a cycle runs and the frozen record after a cancel or failure (P15);
/// an idle page after a clean cycle has no news for it, and the design's
/// default view is the room, one sentence, one button and one whisper line.
func stageStripIsVisible(isRunning: Bool, cancelled: Bool, failed: Bool) -> Bool {
    isRunning || cancelled || failed
}
