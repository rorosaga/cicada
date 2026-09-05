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
    /// stages, so a running cycle's active stage is `stage + 1` — see
    /// `stageStripState`, which is the one place that translation happens.
    let number: Int
    /// The strip's word: one syllable of the pipeline, no numeral.
    let shortLabel: String
    /// The popover's sentence.
    let detail: String
    /// SF Symbol for the popover row (the strip draws a pixel icon instead —
    /// `StageIconSprites`).
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
        SleepStage(id: "stage1", number: 1, shortLabel: "Read",
                   detail: "Each episode is read once for people, projects, tools and ideas.",
                   symbol: "book"),
        SleepStage(id: "stage2", number: 2, shortLabel: "Sort",
                   detail: "New mentions are matched against what you already have.",
                   symbol: "arrow.triangle.merge"),
        SleepStage(id: "stage3", number: 3, shortLabel: "Decide",
                   detail: "Contradictions become questions in your Inbox; old beliefs fade.",
                   symbol: "questionmark.circle"),
        SleepStage(id: "stage4", number: 4, shortLabel: "Notice",
                   detail: "Habits that recur become skills.",
                   symbol: "sparkles"),
        SleepStage(id: "stage5", number: 5, shortLabel: "File",
                   detail: "Everything is written to the graph and committed with its provenance.",
                   symbol: "checkmark.seal"),
    ]

    /// The breathing period of the active pip, in seconds (R-A13's motion
    /// budget: nothing on this page cycles faster than 1.2 s). Named, not a
    /// literal inside a view, so the budget is assertable in a test and a
    /// `TimelineView` cannot quietly drive it at some other rate.
    static let pulsePeriod: TimeInterval = 1.2

    /// Ticks per breath. 12 is smooth enough to read as breathing at this
    /// size and cheap enough that the strip costs nothing while a cycle runs.
    static let pulseSteps = 12

    /// The dimmest the active pip ever gets. A pip that fades toward 0 reads
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
                     read: Int, total: Int) -> [StagePip] {
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
        guard index == done else { return .pending }
        // Only Read carries a fill, and only once the cycle knows its totals.
        let isRead = index == 0
        guard isRead, total > 0 else { return .active(fill: nil) }
        return .active(fill: Double(read) / Double(total))
    }
}

/// Whether the strip ends with the `.happy` worm — the mark that says "and
/// there is nothing waiting" (R-A8). It shows only when the hero has **no
/// numeral to promote**, so the page never draws a count and a "caught up"
/// worm at the same time; `heroCount` is the same function the hero itself
/// asks, so the two can only agree.
func stageStripShowsCaughtUpWorm(mood: BookwormState, debt: SleepDebtView?) -> Bool {
    guard case .happy = mood else { return false }
    return heroCount(mood, debt: debt) == nil
}

// MARK: - The motion budget (R-A13)

/// The active pip's breath, as a pure function of the clock — the same shape
/// `BookwormView.frameIndex(at:…)` uses, and for the same reasons: no `Timer`
/// to leak, no `@State` to reset on a state change, and two strips on one
/// screen breathe in step.
///
/// **Reduce Motion holds the terminal frame** (R-A13) — a single constant
/// value, never a slower breath, because "slower" is still motion. The held
/// value is the phase-0 value (fully lit), so the pip a person with Reduce
/// Motion on sees is the brightest one, not an arbitrary mid-breath dimming.
///
/// Periodic in `SleepStages.pulsePeriod` by construction, which is what makes
/// the budget testable: the constant IS the breath.
func stagePulse(at date: Date, reduceMotion: Bool) -> Double {
    guard !reduceMotion else { return 1.0 }
    let period = SleepStages.pulsePeriod
    let phase = date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: period) / period
    // cos is even, so a negative phase (a date before the reference epoch)
    // mirrors rather than trapping or going out of range.
    let wave = 0.5 + 0.5 * cos(2 * Double.pi * phase)
    return SleepStages.pulseFloor + (1 - SleepStages.pulseFloor) * wave
}

// MARK: - The five 16×16 icons

/// The strip's icons: five 16-cell grids in `DeskPalette`, drawn at 32 pt
/// through the same `PixelRenderer` as the room and the worm.
///
/// **16, not 24 (P12's other half).** A stage icon sits beside a caption at
/// body size; authoring it on the worm's 24-cell grid and shrinking it would
/// be the second pixel scale P12 forbids. `PixelRenderer` takes the grid size
/// as a parameter precisely so a smaller drawing can be a smaller GRID rather
/// than a smaller rendering of a big one.
///
/// **At most three hues each.** Sixteen cells is not enough resolution to
/// carry four colours — the icon turns to mud at the size it is actually
/// drawn. `StageIconTests` fails on a fourth.
///
/// Hues are chosen from `DeskPalette`'s mid-tones (`c`, `n`, `i`, `g`) rather
/// than its darkest and lightest, because the strip sits on the page surface
/// in BOTH themes: the room's night palette can put `k` on a dark window
/// because the window frames it, and an icon has nothing to frame it.
enum StageIconSprites {
    static let size = 16

    /// An open book, spine down the middle: Stage 1 reads each episode once.
    static let read: PixelGrid = [
        "................",
        "................",
        "................",
        "................",
        ".cccccccccccccc.",   // 4  cover
        ".cuuuuuucuuuuuc.",   // 5  pages, spine at col 8
        ".cuuuuuucuuuuuc.",   // 6
        ".cuuuuuucuuuuuc.",   // 7
        ".cuuuuuucuuuuuc.",   // 8
        ".cuuuuuucuuuuuc.",   // 9
        ".cuuuuuucuuuuuc.",   // 10
        ".cccccccccccccc.",   // 11
        "................",
        "................",
        "................",
        "................",
    ]

    /// Two streams merging into one: Stage 2 matches new mentions against what
    /// the bank already holds. Deliberately the same idea as the popover's
    /// `arrow.triangle.merge`.
    static let sort: PixelGrid = [
        "................",
        "................",
        "................",
        "ii..........ii..",   // 3
        ".ii........ii...",   // 4
        "..ii......ii....",   // 5
        "...ii....ii.....",   // 6
        "....ii..ii......",   // 7
        ".....iiii.......",   // 8  they meet
        "......nn........",   // 9  and continue as one
        "......nn........",   // 10
        "......nn........",   // 11
        "......nn........",   // 12
        "................",
        "................",
        "................",
    ]

    /// A question mark: Stage 3's contradictions become questions in the Inbox.
    static let decide: PixelGrid = [
        "................",
        "................",
        "....cccccc......",   // 2
        "...cc....cc.....",   // 3
        "..cc......cc....",   // 4
        "..........cc....",   // 5
        ".........cc.....",   // 6
        ".......ccc......",   // 7
        "......cc........",   // 8
        "......cc........",   // 9
        "................",
        "......nn........",   // 11 the dot
        "......nn........",   // 12
        "................",
        "................",
        "................",
    ]

    /// A four-point spark: Stage 4 notices the habit that keeps recurring.
    static let notice: PixelGrid = [
        "................",
        "................",
        "................",
        ".......nn.......",   // 3
        ".......nn.......",   // 4
        "......nnnn......",   // 5
        "....nnnnnnnn....",   // 6
        ".nnnnnnssnnnnnn.",   // 7  the lit core
        ".nnnnnnssnnnnnn.",   // 8
        "....nnnnnnnn....",   // 9
        "......nnnn......",   // 10
        ".......nn.......",   // 11
        ".......nn.......",   // 12
        "................",
        "................",
        "................",
    ]

    /// A check: Stage 5 writes everything to the graph and commits it.
    static let file: PixelGrid = [
        "................",
        "................",
        "................",
        "................",
        "................",
        ".............hh.",   // 5  the stroke's lit tip
        "............gg..",   // 6
        "...........gg...",   // 7
        "..gg......gg....",   // 8
        "...gg....gg.....",   // 9
        "....gg..gg......",   // 10
        ".....gggg.......",   // 11
        "......gg........",   // 12
        "................",
        "................",
        "................",
    ]

    /// The icon for a stage. Keyed by `number` rather than by `id` so a stage
    /// renamed in `SleepStages.all` keeps its drawing — the number is the
    /// stable half of a stage's identity (`sleep_cycle.py` counts them).
    static func grid(for stage: SleepStage) -> PixelGrid {
        switch stage.number {
        case 1: return read
        case 2: return sort
        case 3: return decide
        case 4: return notice
        default: return file
        }
    }
}
