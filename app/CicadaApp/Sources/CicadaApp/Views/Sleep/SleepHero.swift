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
/// `sleep_run` telemetry join — `—` when no row joined.
///
/// P6 — every input is a domain the `Store` already holds: the active bank's
/// `entityCount` from `GET /banks`, the `sourcesOverview` rows with captures,
/// and `sleepVM.history`. No new fetch, no new endpoint, and specifically not
/// `/healthz` (auth-free, un-ETagged, not a Store domain — reading it would
/// add a second freshness model to a page built entirely from last-known-good
/// projections). The readout is identical; only its source moves.
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

// MARK: - The hero view

/// The readout that sits under the study room: the promoted count with its
/// qualifier chip, the 24-block meter that always names its noun, the three
/// measured tiles, and **the one** Consolidate/Cancel control the Sleep page
/// keeps (R-A7, upgrading G125 R10 — the study list's footer lost its
/// button, and `FixWaveTests` now walks all of `Views/Sleep/` to keep it
/// that way).
///
/// Every input is resolved by the caller, once per body evaluation (H1), so
/// the hero can never disagree with the book pile or the queue card about
/// which cycle's counts it is showing.
struct SleepHeroView: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    let mood: BookwormState
    let debt: SleepDebtView?
    /// The sums of `resolveOriginCounts` — the running meter's two numbers.
    let read: Int
    let total: Int
    /// `sleepVM.queuedEpisodes.count`, passed in rather than re-derived: it
    /// is what the Consolidate button enables on, and the page already has it.
    let queuedCount: Int

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            countRow
            if let meter = heroMeter(mood: mood, debt: debt, read: read, total: total) {
                meterView(meter)
            }
            tilesRow
            controlRow
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: The count + its qualifier chip

    private var countRow: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
            if let count = heroCount(mood, debt: debt), count > 0 {
                Text("\(count)")
                    .font(CicadaTheme.font(size: 44, weight: .semibold, design: .rounded))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.episodesWaiting(count))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            qualifierChip
            Spacer(minLength: 0)
        }
        // The bracket line survives here as the group's VoiceOver label — the
        // numeral and the chip are two halves of one sentence, and reading
        // them as separate elements would say "205" then "behind" (P8).
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(sleepDebtBracketText(mood, debt: debt))
    }

    private var qualifierChip: some View {
        Text(heroQualifier(mood, debt: debt))
            .font(CicadaTheme.font(size: 11, weight: .semibold))
            .foregroundStyle(sleepDebtBracketColor(mood))
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.vertical, 3)
            .background(sleepDebtBracketColor(mood).opacity(0.12))
            .clipShape(Capsule())
    }

    // MARK: The meter

    /// R-A5: **the label is ALWAYS drawn above the bar** — a bar without its
    /// noun is a bare percentage, which is the thing this page refuses to
    /// show. `heroMeter` returning `nil` is what hides the whole group; there
    /// is no path that draws the blocks alone.
    private func meterView(_ meter: HeroMeter) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(meter.label)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            HStack(spacing: 3) {
                ForEach(0..<HeroMeter.blockCount, id: \.self) { index in
                    RoundedRectangle(cornerRadius: 1.5)
                        .fill(index < meter.filledBlocks ? CicadaTheme.accent : CicadaTheme.surfaceElevated)
                        .frame(width: 8, height: 12)
                }
            }
            .animation(.easeInOut(duration: 0.35), value: meter.filledBlocks)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(meter.label)
    }

    // MARK: The three tiles

    private var tilesRow: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingXL) {
            ForEach(heroTiles(entityCount: activeBankEntityCount,
                              sourceCount: feedingSourceCount,
                              lastDurationMs: lastMeasuredCycleMs)) { tile in
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

    /// The same rows the Memory sources panel projects, counted once: a
    /// source that has captured nothing is not feeding anything.
    private var feedingSourceCount: Int? {
        store.sourcesOverview.value.map { rows in rows.filter { $0.episodes > 0 }.count }
    }

    /// The most recent cycle that actually consolidated something — a
    /// `decay` commit is pure arithmetic over unmentioned entities (the G85
    /// split) and its wall-clock says nothing about how long a cycle takes.
    private var lastMeasuredCycleMs: Int? {
        sleepVM.history.first { $0.kind != "decay" }?.durationMs
    }

    // MARK: The one Consolidate/Cancel control (R-A7)

    private var controlRow: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                consolidateButton
                if sleepVM.isRunning {
                    cancelButton
                }
                Spacer(minLength: 0)
            }
            // The standing quota ruling, shown at the moment of choice rather
            // than hidden: what THIS button would spend. Absent when the
            // preview hasn't loaded — a guess would be worse than silence.
            if let manual = sleepVM.enginePreview?.manual {
                Text(Copy.runsOn(engine: manual.engine))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            if sleepVM.isRunning {
                Text(Copy.cancelSleepExplainer)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
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
            .foregroundStyle(isIdleAndEmpty ? CicadaTheme.textTertiary : .white)
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(isIdleAndEmpty ? CicadaTheme.surfaceElevated : CicadaTheme.accent.opacity(0.9))
            .clipShape(Capsule())
        }
        .buttonStyle(.cicadaPlain)
        .disabled(sleepVM.isRunning || queuedCount == 0)
        .help(queuedCount == 0 ? "Nothing queued right now" : "Run the Sleep cycle now")
        .accessibilityLabel(Copy.consolidateNow)
    }

    private var isIdleAndEmpty: Bool { queuedCount == 0 && !sleepVM.isRunning }

    /// Only shown while a cycle is running — it is the one live control the
    /// running state offers (the trigger itself is disabled and read-only for
    /// "Consolidating…"), which is why it moved here with the button rather
    /// than staying in the queue card's footer. Cooperative, not instant;
    /// `Copy.cancelSleepExplainer` says so both here and in the caption.
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
