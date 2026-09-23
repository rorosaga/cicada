import SwiftUI

// MARK: - The hero readout (G125 v3, spec R-A4…R-A7)

/// The numeral the hero promotes — and `nil` when the state has none.
///
/// P8: `sleepDebtBracketText` is **re-composed** from this function and
/// `bracketTail`, never rewritten, so the twelve strings `SleepMoodTests`
/// asserts survive byte-for-byte. Two details the existing strings force,
/// read off the switch rather than guessed:
///
/// - `.curious`'s numeral comes from the CASE's associated value, not from
///   `debt` — `"[ 47 episodes behind ]"` is asserted with `debt: nil`.
/// - `.reading` is `debt?.unprocessedCount ?? 0` and therefore **never nil**:
///   `"[ 0 to read ]"` with a nil debt is an asserted string. The hero VIEW is
///   what decides not to draw a `0`; this function does not lie about it.
func heroCount(_ state: BookwormState, debt: SleepDebtView?) -> Int? {
    switch state {
    case .awake, .sleeping, .digesting, .happy, .error:
        return nil
    case .curious(let count):
        return count
    case .reading:
        return debt?.unprocessedCount ?? 0
    case .hungry:
        // A long gap with an empty queue is genuinely countless — the caption
        // says "overdue — hasn't consolidated in a while" and shows no
        // numeral, so neither does the hero.
        let count = debt?.unprocessedCount ?? 0
        return count > 0 ? count : nil
    }
}

/// The short chip beside the numeral (R-A4). Deliberately NOT `bracketTail`:
/// the tail is a caption phrase that carries the pluralised noun, the chip is
/// one or two words naming the state.
///
/// P9 — `first run` outranks `behind`/`overdue`: nothing has ever been
/// consolidated in this bank, so calling the queue a *backlog* would be
/// wrong. It needs a count to be about, so an empty queue with
/// `hasRunBefore == false` keeps its own word.
func heroQualifier(_ state: BookwormState, debt: SleepDebtView?) -> String {
    switch state {
    case .awake:
        return "awake"
    case .sleeping:
        return "sleeping"
    case .digesting:
        return "digesting"
    case .happy:
        return "caught up"
    case .error:
        return "failed"
    case .curious(let count):
        return firstRunWord(count: count, debt: debt) ?? "behind"
    case .reading:
        let count = debt?.unprocessedCount ?? 0
        // `intakeInFlight` holds `.reading` with an as-yet-unrefreshed queue
        // count of 0 (G125 R2) — nothing is behind, the worm is simply busy.
        guard count > 0 else { return "reading" }
        return firstRunWord(count: count, debt: debt) ?? "behind"
    case .hungry:
        let count = debt?.unprocessedCount ?? 0
        return firstRunWord(count: count, debt: debt) ?? "overdue"
    }
}

/// `"first run"` when Sleep has demonstrably never run in this bank and there
/// is a queue to describe; `nil` (fall through to the state's own word)
/// otherwise. A nil debt means "not loaded", never "has not run" — an unknown
/// must not be reported as a fact.
private func firstRunWord(count: Int, debt: SleepDebtView?) -> String? {
    (debt?.hasRunBefore == false && count > 0) ? "first run" : nil
}

/// The caption tail — everything the bracket line says after the numeral.
/// It owns the pluralisation, so it takes the same count `heroCount` returns.
func bracketTail(_ state: BookwormState, debt: SleepDebtView?) -> String {
    switch state {
    case .awake:
        return "awake"
    case .sleeping(let stage):
        return "sleeping · stage \(stage) of 5"
    case .digesting:
        return "digesting"
    case .happy:
        return "caught up"
    case .curious(let count):
        return "episode\(count == 1 ? "" : "s") behind"
    case .reading:
        return "to read"
    case .hungry:
        let count = debt?.unprocessedCount ?? 0
        guard count > 0 else { return "overdue — hasn't consolidated in a while" }
        return "episode\(count == 1 ? "" : "s") behind — overdue"
    case .error:
        return "last cycle failed"
    }
}

// MARK: - The meter (R-A5)

/// **The bar never renders without its noun.** One bar with two exclusive
/// meanings and never a bare `%`:
///
/// - idle → `Rested 12%` from `debt.restedPct`, and **nothing at all** when
///   `restedPct == nil` (no baseline: Sleep has never run in this bank, and a
///   fabricated 100% would be a lie);
/// - running → `Read 138 of 203`, where both numbers are the sums of
///   `resolveOriginCounts`'s `readByOrigin`/`queueByOrigin` — already
///   resolved ONCE per body evaluation (H1) — so the label's two numbers and
///   the bar's fraction come from one reading. Deliberately **not**
///   `progressPct`, which is a different scalar on a different cadence and
///   would let the words and the fill disagree (P7).
///
/// A running cycle past Stage 1 has no per-episode unit at all
/// (`sleep_cycle.progress_pct` returns `None`), so `total == 0` draws no bar
/// rather than `Read 0 of 0` — the stage strip is the running instrument.
enum HeroMeter: Equatable {
    case rested(pct: Int)
    case reading(read: Int, total: Int)

    /// The reference's segmented bar: 24 whole blocks, never a fractional one.
    static let blockCount = 24

    var label: String {
        switch self {
        case .rested(let pct): "Rested \(pct)%"
        case .reading(let read, let total): "Read \(read) of \(total)"
        }
    }

    /// Clamped to `0...1`: a backend that reports a rested percentage above
    /// 100 (or a read count past its own total) is a bug, and the bar must
    /// not overflow its 24 blocks because of it. The LABEL still shows the
    /// raw numbers — the honest reading is the one worth seeing.
    var fraction: Double {
        switch self {
        case .rested(let pct):
            return min(1, max(0, Double(pct) / 100))
        case .reading(let read, let total):
            guard total > 0 else { return 0 }
            return min(1, max(0, Double(read) / Double(total)))
        }
    }

    var filledBlocks: Int {
        min(Self.blockCount, max(0, Int((fraction * Double(Self.blockCount)).rounded())))
    }
}

func heroMeter(mood: BookwormState, debt: SleepDebtView?, read: Int, total: Int) -> HeroMeter? {
    if case .sleeping = mood {
        guard total > 0 else { return nil }
        return .reading(read: read, total: total)
    }
    guard let pct = debt?.restedPct else { return nil }
    return .rested(pct: pct)
}

/// The breakdown behind `Rested n%` — hover text on the meter's label, and
/// `nil` (no tooltip at all) for everything else.
///
/// Round-2 live check, R-A5: the page drew `Rested n%` in the hero's labelled
/// meter AND again two rows below it as `Rested n% — volume v%, age a%`. One
/// number on screen twice is exactly what this page refuses; the duplicate
/// line is gone and its one piece of extra information — which of the two
/// ratios the backend combined is doing the work — moved here, where a
/// breakdown belongs.
///
/// `.reading` gets nothing: `Read a of b` already shows both of its numbers,
/// so there is nothing left to explain, and inventing a tooltip for it would
/// put a second meaning on the same hover.
func heroMeterHelp(_ meter: HeroMeter, debt: SleepDebtView?) -> String? {
    guard case .rested = meter, let debt else { return nil }
    return Copy.restedBreakdown(volumePct: debt.volumePct, agePct: debt.agePct)
}

// MARK: - The three tiles (R-A6)

/// One hero tile: a measured value and the noun that says what it counts.
/// `reason` is non-nil **only** when `value` is `—` (R-A14/P18: a dash is a
/// value with a reason, never a blank and never a zero standing in for an
/// unknown) and is shown on hover.
struct HeroTile: Equatable, Identifiable {
    let id: String
    let label: String
    let value: String
    let reason: String?
}

/// Present tense or measured, never a forecast (R-A6, and G107's estimate
/// deferral is binding): what is in memory right now, how many sources feed
/// it right now, and how long the last cycle actually took according to the
/// `sleep_run` telemetry join — `—` when no row joined. "The last cycle" is
/// the newest `kind == "sleep"` commit (Z-P3, `lastCycleEntry`): neither the
/// G85 `(decay)` commit nor an inbox-resolution commit is a cycle.
///
/// P6 — every input is a domain the `Store` already holds: the active bank's
/// `entityCount` from `GET /banks`, the `sourcesOverview` rows with captures,
/// and `sleepVM.history` (through `SleepPageModel`). No new fetch, no new
/// endpoint, and specifically not `/healthz` (auth-free, un-ETagged, not a
/// Store domain — reading it would add a second freshness model to a page
/// built entirely from last-known-good projections). The readout is identical; only its source moves.
func heroTiles(entityCount: Int?, sourceCount: Int?, lastDurationMs: Int?) -> [HeroTile] {
    [
        HeroTile(
            id: "entities",
            label: Copy.entitiesInMemory(entityCount),
            value: entityCount.map(String.init) ?? "—",
            reason: entityCount == nil ? Copy.bankListNotLoaded : nil
        ),
        HeroTile(
            id: "sources",
            label: Copy.sourcesFeeding(sourceCount),
            value: sourceCount.map(String.init) ?? "—",
            reason: sourceCount == nil ? Copy.sourceOverviewNotLoaded : nil
        ),
        HeroTile(
            id: "lastCycle",
            label: Copy.lastCycle,
            value: SleepHistoryPresentation.durationText(ms: lastDurationMs),
            reason: lastDurationMs == nil ? Copy.noTimingRecorded : nil
        ),
    ]
}

// MARK: - The readout (Details › Readout)

/// Details › Readout (Track Z §4.2): the meter that never renders without its
/// noun (R-A5), the three measured tiles (R-A6), the no-baseline line, and the
/// engine the last cycle ran on. It stays in THIS file so "Rested" is still
/// spelled by exactly one file (`SleepNumbersLintTests`).
///
/// It was the hero that sat under the study room. Track Z Z2 took its other
/// halves away: the promoted count and its qualifier chip became the room's
/// sentence lead (`roomSentence`, which asks `heroCount`/`heroQualifier`
/// rather than re-deriving them — parity by construction), and the one
/// Consolidate/Cancel control became `SleepControlRow` below. Z3 moved what was
/// left into Details, and took the no-baseline line and the engine line with
/// it, so every number the default view no longer shows lives in one card.
///
/// Every input is resolved by the caller, once per body evaluation (H1), so
/// the readout can never disagree with the book pile or the queue about
/// which cycle's counts it is showing.
struct SleepReadoutView: View {
    @Environment(Store.self) private var store
    /// R-A13: the meter's blocks ease between two readings, and Reduce Motion
    /// has to reach that easing. It did not before Task 8 — the modifier took
    /// a non-optional literal, which is how a `.animation(...)` silently skips
    /// the setting.
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    let mood: BookwormState
    let debt: SleepDebtView?
    /// The sums of `resolveOriginCounts` — the running meter's two numbers.
    let read: Int
    let total: Int
    /// The newest `kind == "sleep"` commit's measured duration
    /// (`SleepPageModel.lastCycle`, Z-P3). It used to be read here as
    /// `history.first { $0.kind != "decay" }`, which also matched an inbox
    /// resolution commit — the person's own answer timed as "the last cycle".
    let lastDurationMs: Int?
    let lastEngine: String?
    let engineDetail: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("READOUT")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
            if let meter = heroMeter(mood: mood, debt: debt, read: read, total: total) {
                meterView(meter)
            } else {
                noBaselineLine
            }
            tilesRow
            if let engine = lastEngine {
                engineLine(engine, detail: engineDetail)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    // MARK: No baseline

    /// The one thing the meter CANNOT say: that there is no baseline at all.
    /// Moved from `SleepView.moodDetailLine` (Track Z Z3).
    ///
    /// G125 v3 Task 5 (R-A8) deleted this line's running branch — the
    /// `Text("Stage \(stage) of 5")` and the bare `ProgressView` the stage
    /// strip replaced. The round-2 live check deleted its idle branch for the
    /// same reason one step further on: it drew `Rested n% — volume v%, age
    /// a%` directly under a meter already labelled `Rested n%`, so **the same
    /// number was on screen twice** (R-A5 — one number, one place). The
    /// volume/age split is the meter label's hover text now (`heroMeterHelp`).
    ///
    /// What is left is the branch the meter has no way to draw. `heroMeter`
    /// returns `nil` when `restedPct` is nil, so without this line a bank
    /// where Sleep has never run would show nothing at all where the meter
    /// sits — and silence reads as "fine", which is the opposite of the truth.
    ///
    /// The `.sleeping` guard survives as an explicit empty branch: a baseline
    /// is what the queue looks like BETWEEN cycles, so mid-cycle it would sit
    /// stale next to a live readout.
    @ViewBuilder
    private var noBaselineLine: some View {
        if case .sleeping = mood {
            EmptyView()
        } else if let debt, debt.restedPct == nil {
            // No baseline: the queue is empty and Sleep has never run in
            // this bank — an honest state, not a fabricated 100%.
            Text("No baseline yet — Sleep hasn't run in this bank.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    // MARK: Engine line

    /// Which engine the last cycle ran on. Named, not implied — a Sleep page
    /// that says "check API credits" while running on a subscription is the
    /// exact confusion this replaces. Moved from `SleepView.engineLine`
    /// (Track Z Z3); the engine now wears its real mark (Z-P26).
    private func engineLine(_ engine: String, detail: String?) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text("ENGINE")
                .font(CicadaTheme.font(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.1)
            EngineMark(engine: engine, size: 12)
            Text(Copy.engineLabel(engine))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            if let detail, !detail.isEmpty {
                Text("· \(detail)")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(2)
            }
            Spacer()
        }
    }

    // MARK: The meter

    /// R-A5: **the label is ALWAYS drawn above the bar** — a bar without its
    /// noun is a bare percentage, which is the thing this page refuses to
    /// show. `heroMeter` returning `nil` is what hides the whole group; there
    /// is no path that draws the blocks alone.
    ///
    /// The label is also the only place the Rested breakdown lives now
    /// (`heroMeterHelp`): the volume/age split is one hover away instead of a
    /// second copy of `Rested n%` printed under the stage strip. An empty help
    /// string renders no tooltip, the same way `tilesRow` spells "no reason".
    private func meterView(_ meter: HeroMeter) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(meter.label)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .help(heroMeterHelp(meter, debt: debt) ?? "")
            HStack(spacing: 3) {
                ForEach(0..<HeroMeter.blockCount, id: \.self) { index in
                    RoundedRectangle(cornerRadius: 1.5)
                        .fill(index < meter.filledBlocks ? CicadaTheme.accent : CicadaTheme.surfaceElevated)
                        .frame(width: 8, height: 12)
                }
            }
            .animation(SleepMotion.settle(reduceMotion: reduceMotion), value: meter.filledBlocks)
        }
        .accessibilityElement(children: .ignore)
        // A tooltip is sighted-only, and the breakdown it carries is the same
        // sentence the deleted line used to read out loud. It joins the label
        // here so VoiceOver keeps hearing it (R-A15: every mark has a text
        // twin) rather than losing it with the duplicate.
        .accessibilityLabel(
            [meter.label, heroMeterHelp(meter, debt: debt)]
                .compactMap { $0 }
                .joined(separator: " — "))
    }

    // MARK: The three tiles

    private var tilesRow: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingXL) {
            ForEach(heroTiles(entityCount: activeBankEntityCount,
                              sourceCount: feedingSourceCount,
                              lastDurationMs: lastDurationMs)) { tile in
                VStack(alignment: .leading, spacing: 1) {
                    Text(tile.value)
                        .font(CicadaTheme.font(size: 15, weight: .semibold, design: .rounded))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(tile.label)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                // An empty help string renders no tooltip, so a real value
                // carries none — the reason belongs to the dash (P18).
                .help(tile.reason ?? "")
                .accessibilityElement(children: .combine)
                .accessibilityLabel("\(tile.value) \(tile.label)\(tile.reason.map { " — \($0)" } ?? "")")
            }
            Spacer(minLength: 0)
        }
    }

    /// The ACTIVE bank's entity count from `GET /banks` (P6) — `nil` until
    /// the roster has loaded, which reads as `—` rather than a zero.
    private var activeBankEntityCount: Int? {
        store.banks.value?.banks.first { $0.active }?.entityCount
    }

    /// The same `sourcesOverview` rows the Sources grid draws, counted once:
    /// a source that has captured nothing is not feeding anything.
    private var feedingSourceCount: Int? {
        store.sourcesOverview.value.map { rows in rows.filter { $0.episodes > 0 }.count }
    }
}

// MARK: - The one control (R-A7, Track Z §4.2)

/// What the caption under the one control says: the engine THIS click would
/// run on (ruling 4, at the moment of choice), or what Cancel does while a
/// cycle runs; `nil` until the preview loads — a guessed engine is worse than
/// silence.
func controlCaption(isRunning: Bool, manualEngine: String?) -> String? {
    if isRunning { return Copy.cancelCaption }
    return manualEngine.map { Copy.runsOn(engine: $0) }
}

/// The page's ONE Consolidate/Cancel control (R-A7, G125 R10). While a cycle
/// runs the one control IS Cancel — the disabled "Consolidating…" twin pill is
/// gone (design §4.2). `FixWaveTests` pins `sleepVM.triggerManually()` to this
/// file.
///
/// `consolidateEnabled` and `queuedCount` come from `SleepPageModel`, the one
/// reading the sentence above it also drew from, so the button can never be
/// live while the sentence says there is nothing to read.
struct SleepControlRow: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    let consolidateEnabled: Bool
    let queuedCount: Int
    let manualEngine: String?

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if sleepVM.isRunning { cancelButton } else { consolidateButton }
            if let caption = controlCaption(isRunning: sleepVM.isRunning, manualEngine: manualEngine) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    if !sleepVM.isRunning, let engine = manualEngine { EngineMark(engine: engine) }
                    Text(caption)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var consolidateButton: some View {
        Button {
            Task {
                await sleepVM.triggerManually()
                await store.refresh([.status, .channels])
            }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                if sleepVM.isRunning {
                    ProgressView().controlSize(.small).frame(width: 12, height: 12)
                } else {
                    Image(systemName: "moon.fill").font(CicadaTheme.font(size: 12))
                }
                Text(sleepVM.isRunning ? Copy.consolidating : Copy.consolidateNow)
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
            }
            .foregroundStyle(consolidateEnabled ? .white : CicadaTheme.textTertiary)
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(consolidateEnabled ? CicadaTheme.accent.opacity(0.9) : CicadaTheme.surfaceElevated)
            .clipShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(!consolidateEnabled)
        .help(queuedCount == 0 ? "Nothing queued right now" : "Run the Sleep cycle now")
        .accessibilityLabel(Copy.consolidateNow)
    }

    /// Only shown while a cycle is running, and then INSTEAD of Consolidate
    /// (design §4.2): the one control is Cancel for as long as there is a
    /// cycle to stop. Cooperative, not instant — the long
    /// `Copy.cancelSleepExplainer` is its tooltip, and the one-line
    /// `Copy.cancelCaption` beside it says the short form.
    private var cancelButton: some View {
        Button {
            Task { await sleepVM.cancel() }
        } label: {
            HStack(spacing: 4) {
                if sleepVM.isCancelling {
                    ProgressView().controlSize(.small).frame(width: 10, height: 10)
                } else {
                    Image(systemName: "xmark").font(CicadaTheme.font(size: 10, weight: .semibold))
                }
                Text(sleepVM.isCancelling ? Copy.cancellingSleep : Copy.cancelSleep)
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
            }
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(CicadaTheme.surfaceElevated)
            .clipShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(sleepVM.isCancelling)
        .help(Copy.cancelSleepExplainer)
        .accessibilityLabel(Copy.cancelSleep)
    }
}

/// The engine a caption names, with its real mark (round-3 brief: "use logos
/// whenever possible"; Z-P26). `claude-cli` IS Claude Code, so it borrows that
/// origin's mark; an API key has no vendor to show.
struct EngineMark: View {
    let engine: String
    var size: CGFloat = 14

    var body: some View {
        switch engine {
        case "claude-cli":
            OriginMark(origin: "claude-code", size: size)
        case "ollama":
            LogoImage(name: "ollama", size: size)
        default:
            Image(systemName: "key")
                .font(CicadaTheme.font(size: size * 0.8, weight: .medium))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: size, height: size)
        }
    }
}
