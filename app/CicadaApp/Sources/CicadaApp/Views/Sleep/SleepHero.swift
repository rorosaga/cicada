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

    /// DESIGN_RULES §10 (Sleep): "'Rested 0%' becomes a sentence instead of 26 empty boxes" (R-HS15).
    /// The noun stays first (R-A5); the rest says what the number means from facts the page already
    /// holds — the queue's count and the mood — never a guess. The volume/age split stays on hover
    /// (`heroMeterHelp`).
    func sentence(unprocessed: Int, mood: BookwormState) -> String {
        switch self {
        case .reading(let read, let total):
            return "Read \(UsageFormat.count(read)) of \(UsageFormat.count(total)) so far."
        case .rested(let pct):
            if unprocessed == 0 { return "Fully rested — nothing is waiting." }
            if case .hungry = mood { return "Rested \(pct)% — the backlog is overdue." }
            return "Rested \(pct)% — based on how much is waiting, and for how long."
        }
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

// MARK: - The readout rows (R-A6, R-HS15)

/// Details › Readout as rows (R-HS15): R-A6's measured values — present tense, never a forecast —
/// and the last cycle's engine, each a key on the left and its value on the right, `—` with its
/// reason on hover for anything unknown (R-A14/P18). Counts go through `UsageFormat` (DR-21: the
/// tiles printed `String(n)`, so a German reader saw 1904, not 1.904). Every input is a Store domain
/// or `SleepPageModel` (P6).
///
/// "The last cycle" is the newest `kind == "sleep"` commit (Z-P3, `lastCycleEntry`): neither the G85
/// `(decay)` commit nor an inbox-resolution commit is a cycle, and its duration is the `sleep_run`
/// telemetry join — `—` when no row joined (G107: a measured duration or nothing).
struct ReadoutRow: Equatable, Identifiable {
    let id: String
    let key: String
    let value: String
    let reason: String?
    /// The engine the value names, for its mark (DR-52); nil on every other row.
    let engine: String?
}

func readoutRows(entityCount: Int?, sourceCount: Int?, lastDurationMs: Int?, lastEngine: String?,
                 engineDetail: String?, locale: Locale = .autoupdatingCurrent) -> [ReadoutRow] {
    let entities = entityCount.map { "\(UsageFormat.count($0, locale: locale)) \($0 == 1 ? "entity" : "entities")" }
    let sources = sourceCount.map { "\(UsageFormat.count($0, locale: locale)) \($0 == 1 ? "source" : "sources")" }
    let engine = lastEngine.map { id in
        ([Copy.engineLabel(id)] + [engineDetail].compactMap { $0 }.filter { !$0.isEmpty }).joined(separator: " · ")
    }
    return [
        ReadoutRow(id: "entities", key: Copy.SleepDetailsWords.inMemory, value: entities ?? "—",
                   reason: entityCount == nil ? Copy.bankListNotLoaded : nil, engine: nil),
        ReadoutRow(id: "sources", key: Copy.SleepDetailsWords.feedingIt, value: sources ?? "—",
                   reason: sourceCount == nil ? Copy.sourceOverviewNotLoaded : nil, engine: nil),
        ReadoutRow(id: "lastCycle", key: Copy.SleepDetailsWords.lastCycleTook,
                   value: SleepHistoryPresentation.durationText(ms: lastDurationMs),
                   reason: lastDurationMs == nil ? Copy.noTimingRecorded : nil, engine: nil),
        ReadoutRow(id: "engine", key: Copy.SleepDetailsWords.lastEngine, value: engine ?? "—",
                   reason: lastEngine == nil ? Copy.SleepDetailsWords.noEngineYet : nil, engine: lastEngine),
    ]
}

// MARK: - The readout (Details › Readout)

/// Details › Readout (Track Z §4.2): the meter's sentence that never renders
/// without its noun (R-A5), the no-baseline line, and four measured key–value
/// rows (R-A6, R-HS15) — the three former tiles and the engine the last cycle
/// ran on. It stays in THIS file so "Rested" is still
/// spelled by exactly one file (`SleepNumbersLintTests`).
///
/// It was the hero that sat under the study room. Track Z Z2 took its other
/// halves away: the promoted count and its qualifier chip became the room's
/// sentence lead (`roomSentence`, which asks `heroCount`/`heroQualifier`
/// rather than re-deriving them — parity by construction), and the one
/// Consolidate/Cancel control became `SleepControlRow` below. Z3 moved what was
/// left into Details, and took the no-baseline line and the engine line with
/// it, so every number the default view no longer shows lives in one section.
///
/// Every input is resolved by the caller, once per body evaluation (H1), so
/// the readout can never disagree with the book pile or the queue about
/// which cycle's counts it is showing.
struct SleepReadoutView: View {
    @Environment(Store.self) private var store

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

    /// R-HS15 — the meter is a sentence and the tiles and the engine line are key–value rows, under
    /// the section's label, no card (DR-37). R-A5 still holds: `heroMeter` returning `nil` is what
    /// hides the sentence, and no path draws a bare percentage. A `.rested` meter only exists when
    /// `debt` does, so the `?? 0` below never speaks.
    var body: some View {
        SleepDetailsSection(title: "Readout") {
            if let meter = heroMeter(mood: mood, debt: debt, read: read, total: total) {
                let sentence = meter.sentence(unprocessed: debt?.unprocessedCount ?? 0, mood: mood)
                Text(sentence)
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    // An empty help string renders no tooltip — `.reading` has nothing to explain.
                    .help(heroMeterHelp(meter, debt: debt) ?? "")
                    .padding(.horizontal, CicadaTheme.scaled(10))
                    .padding(.top, CicadaTheme.scaled(6))
                    .padding(.bottom, CicadaTheme.spacingSM)
                    // A tooltip is sighted-only, so the breakdown joins the label here (R-A15:
                    // every mark has a text twin), as it did on the meter's label.
                    .accessibilityLabel([sentence, heroMeterHelp(meter, debt: debt)]
                        .compactMap { $0 }
                        .joined(separator: " — "))
            } else {
                noBaselineLine
                    .padding(.horizontal, CicadaTheme.scaled(10))
            }
            ForEach(readoutRows(entityCount: activeBankEntityCount, sourceCount: feedingSourceCount,
                                lastDurationMs: lastDurationMs, lastEngine: lastEngine,
                                engineDetail: engineDetail)) { readoutRow($0) }
        }
    }

    /// A key–value row (DR-34: `RowMetrics.keyValue`): the key in `textTertiary`, the engine's mark
    /// when the row names one, the value in 13 medium, tabular.
    private func readoutRow(_ row: ReadoutRow) -> some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Text(row.key)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(150), alignment: .leading)
            if let engine = row.engine { EngineMark(engine: engine, size: CicadaTheme.scaled(12)) }
            Text(row.value)
                .font(CicadaTheme.rowFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(2)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.keyValue))
        // An empty help string renders no tooltip, so a real value carries none — the reason
        // belongs to the dash (P18).
        .help(row.reason ?? "")
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(row.key), \(row.value)\(row.reason.map { " — \($0)" } ?? "")")
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
    /// volume/age split is the sentence's hover text now (`heroMeterHelp`).
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
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
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

/// While a cycle runs, what Cancel does; otherwise nothing — the engine menu beside the control
/// names what a click would run (R-HS9), the fact the retired "Runs on …" caption stated, so
/// printing both would say it twice (DR-38).
func controlCaption(isRunning: Bool) -> String? {
    isRunning ? Copy.cancelCaption : nil
}

/// The page's ONE Consolidate/Cancel control (R-A7, G125 R10). While a cycle
/// runs the one control IS Cancel — the disabled "Consolidating…" twin pill is
/// gone (design §4.2). `FixWaveTests` pins `sleepVM.triggerManually()` to this
/// file.
///
/// `consolidateEnabled` and `queuedCount` come from `SleepPageModel`, the one
/// reading the sentence above it also drew from, so the button can never be
/// live while the sentence says there is nothing to read.
///
/// Beside it sits the engine menu (`EngineQuickMenuButton`), which names what a cycle you start
/// would run (R-HS8); the caption beside the pair is Cancel's while a cycle runs and nothing
/// otherwise (R-HS9).
struct SleepControlRow: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    let consolidateEnabled: Bool
    let queuedCount: Int

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if sleepVM.isRunning { cancelButton } else { consolidateButton }
            // The owner's quick switch (R-HS8, R-HS9). It stays while a cycle runs: a change
            // applies to the next one (G80).
            EngineQuickMenuButton()
            if let caption = controlCaption(isRunning: sleepVM.isRunning) {
                Text(caption)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .frame(maxWidth: .infinity)
    }

    /// The page's one prominent action (R-M5, Z-B14): `.glassProminent`,
    /// accent-tinted, on macOS 26 and `.borderedProminent` before, through the
    /// shared `PrimaryActionButton` so its ink follows the key-window rule. It
    /// lifts on hover because it is the one thing on the page that starts
    /// something; Cancel beside it stays quiet.
    private var consolidateButton: some View {
        PrimaryActionButton(title: Copy.consolidateNow, systemImage: "moon.fill") {
            Task {
                await sleepVM.triggerManually()
                await store.refresh([.status, .channels])
            }
        }
        .font(CicadaTheme.font(size: 12, weight: .semibold))
        .controlSize(.large)
        .disabled(!consolidateEnabled)
        .hoverLift()
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

/// The engine a line names, with its real mark (round-3 brief: "use logos
/// whenever possible"; Z-P26; DR-52). `claude-cli` IS Claude Code, so it borrows that
/// origin's mark; an API key has no vendor to show.
struct EngineMark: View {
    let engine: String
    var size: CGFloat = 14

    /// Which mark an engine wears (R-HS13): the Claude plan runs Claude Code's own binary, the ChatGPT
    /// plan wears its card's mark (`EngineOption.previewMark`), Ollama its own, and an API key — which
    /// has no vendor — a key. `codex-cli` drew the key before DS-3b (DR-52).
    enum Source: Equatable {
        case origin(String)
        case logo(String)
        case symbol(String)
    }

    static func source(for engine: String) -> Source {
        switch engine {
        case "claude-cli": .origin("claude-code")
        case "codex-cli": EngineOption.previewMark(engine: engine).map(Source.logo) ?? .symbol("key")
        case "ollama": .logo("ollama")
        default: .symbol("key")
        }
    }

    var body: some View {
        switch Self.source(for: engine) {
        case .origin(let origin):
            OriginMark(origin: origin, size: size)
        case .logo(let name):
            LogoImage(name: name, size: size)
        case .symbol(let name):
            Image(systemName: name)
                .font(CicadaTheme.font(size: size * 0.8, weight: .medium))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: size, height: size)
        }
    }
}
