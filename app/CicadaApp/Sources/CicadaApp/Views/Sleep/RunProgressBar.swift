import SwiftUI

// MARK: - The run's progress, in counts (Sleep page v5, G163)

/// What the bar under the strip draws for a run that reads in batches: finished work only, from the objects that did
/// it (spec 4.2). `filed + read + waiting + couldNotBeRead + skipped == frozen` at every step, `calls` and `filed` only
/// grow, and there is no remaining time anywhere (G107). Pure, so `SleepV5ProgressBarTests` holds the arithmetic.
struct RunProgress: Equatable {
    var frozen: Int
    var filed: Int
    /// Read in the running batch and not yet filed — zero once the run is not reading (there is no journal: a pause
    /// reads that part again, so it is never shown as kept).
    var read: Int
    var waiting: Int
    var couldNotBeRead: Int
    var calls: Int?
    var finished: Bool
    var batches: Int
    /// Which batch is reading and of how many — only while a run of more than one batch reads; it leads the legend.
    var batchIndex: Int? = nil
    var batchTotal: Int? = nil

    static func from(_ drain: SleepDrainInfo?) -> RunProgress? {
        guard let drain, drain.frozen > 0, drain.batchState != nil || drain.byOrigin != nil else { return nil }
        let reading = drain.active ? (drain.batchState?.read ?? 0) : 0
        let origins = drain.byOrigin?.values
        let failed = origins.map { $0.reduce(0) { $0 + $1.couldNotBeRead + $1.parked } } ?? (drain.parked ?? 0)
        let skipped = origins.map { $0.reduce(0) { $0 + $1.skipped } } ?? drain.skipped
        let filed = min(drain.filed, drain.frozen)
        let waiting = max(0, drain.frozen - filed - reading - failed - skipped)
        let position = drain.active && drain.batches > 1 && drain.batch > 0
        return RunProgress(frozen: drain.frozen, filed: filed, read: reading, waiting: waiting, couldNotBeRead: failed,
                           calls: drain.calls, finished: drain.finished,
                           batches: drain.committedBatches ?? drain.batch,
                           batchIndex: position ? drain.batch : nil, batchTotal: position ? drain.batches : nil)
    }

    var filedFraction: Double { frozen > 0 ? Double(filed) / Double(frozen) : 0 }
    var readFraction: Double { frozen > 0 ? Double(read) / Double(frozen) : 0 }

    /// The legend's words, left to right; zero terms are left out, except `filed`, which always leads — after the batch
    /// position while a run of several batches reads.
    func legend(locale: Locale = .autoupdatingCurrent) -> [String] {
        if finished {
            return [Copy.SleepV5.filed(filed, locale), Copy.SleepV5.batches(batches, locale)]
                + (couldNotBeRead > 0 ? [Copy.SleepV5.couldNotBeRead(couldNotBeRead, locale)] : [])
        }
        var parts = [Copy.SleepV5.filed(filed, locale)]
        if let batchIndex, let batchTotal { parts.insert(Copy.SleepV5.batchOf(batchIndex, batchTotal, locale), at: 0) }
        if read > 0 { parts.append(Copy.SleepV5.readWaitingToFile(read, locale)) }
        if waiting > 0 { parts.append(Copy.SleepV5.waiting(waiting, locale)) }
        if couldNotBeRead > 0 { parts.append(Copy.SleepV5.couldNotBeRead(couldNotBeRead, locale)) }
        return parts
    }

    /// One accessibility value for the whole bar (A11).
    func accessibilityValue(locale: Locale = .autoupdatingCurrent) -> String {
        (legend(locale: locale) + [calls.map { Copy.SleepV5.callsMade($0, locale) }].compactMap { $0 })
            .joined(separator: ", ")
    }
}

/// The one thing the stage caption said that nothing else on the page says (2026-10-16): conversations in the batch
/// that could not be read and get one more try, in words beside a glyph — never colour alone (DR-7). The running
/// stage's name is the sentence's lead and the stepper's current step, so the caption that repeated it ("Filing. It
/// cannot be stopped now.", "Reading conversations") retired. `nil` when nothing failed or the run is not reading.
func batchFailureNote(drain: SleepDrainInfo?, activeStage: Int?, locale: Locale = .autoupdatingCurrent) -> String? {
    guard let drain, drain.active, let activeStage, activeStage <= 2,
          let batch = drain.batchState, batch.failed > 0 else { return nil }
    return "\(Copy.SleepV5.couldNotBeRead(batch.failed, locale)), \(Copy.SleepV5.oneMoreTry)"
}

/// The bar: filed in `textPrimary`, read-and-waiting in `textTertiary`, on a `bgBadge` track, the column's full width
/// like the stepper above it; the legend centred below, the calls made closing it. One accessibility element with a
/// value (A11); a fill settles with `SleepMotion` (DR-61) and Reduce Motion holds the terminal frame (DR-66).
struct RunProgressBar: View {
    let progress: RunProgress
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(CicadaTheme.bgBadge)
                    Capsule().fill(CicadaTheme.textTertiary)
                        .frame(width: geo.size.width * min(1, progress.filedFraction + progress.readFraction))
                    Capsule().fill(CicadaTheme.textPrimary)
                        .frame(width: geo.size.width * min(1, progress.filedFraction))
                }
                .animation(SleepMotion.settle(reduceMotion: reduceMotion), value: progress)
            }
            .frame(height: CicadaTheme.scaled(6))
            // The counts under the bar, centred like every line of the room's column (2026-10-16): the calls made
            // close the line in `textTertiary` instead of standing alone at the bar's right end.
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                ForEach(Array(progress.legend().enumerated()), id: \.offset) { index, words in
                    if index > 0 {
                        Text(verbatim: "·").foregroundStyle(CicadaTheme.textTertiary)
                    }
                    HStack(spacing: CicadaTheme.spacingXS) {
                        if words.hasSuffix(Copy.SleepV5.couldNotBeReadPhrase) {
                            Image(systemName: "exclamationmark.triangle")
                                .foregroundStyle(CicadaTheme.warning)
                        }
                        Text(words)
                    }
                }
                if let calls = progress.calls {
                    Text(verbatim: "·").foregroundStyle(CicadaTheme.textTertiary)
                    Text(Copy.SleepV5.callsMade(calls))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .frame(maxWidth: .infinity)
            .font(CicadaTheme.captionFont)
            .monospacedDigit()
            .foregroundStyle(CicadaTheme.textSecondary)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Copy.SleepV5.progressLabel)
        .accessibilityValue(progress.accessibilityValue())
    }
}

/// The batch's failure note under the stepper, centred (A3, DR-7): a glyph beside words, never colour alone.
struct RunFailureNote: View {
    let text: String

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: "exclamationmark.triangle")
                .foregroundStyle(CicadaTheme.warning)
                .accessibilityHidden(true)
            Text(text)
        }
        .font(CicadaTheme.captionFont)
        .foregroundStyle(CicadaTheme.textSecondary)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}
