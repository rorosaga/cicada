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

    static func from(_ drain: SleepDrainInfo?) -> RunProgress? {
        guard let drain, drain.frozen > 0, drain.batchState != nil || drain.byOrigin != nil else { return nil }
        let reading = drain.active ? (drain.batchState?.read ?? 0) : 0
        let origins = drain.byOrigin?.values
        let failed = origins.map { $0.reduce(0) { $0 + $1.couldNotBeRead + $1.parked } } ?? (drain.parked ?? 0)
        let skipped = origins.map { $0.reduce(0) { $0 + $1.skipped } } ?? drain.skipped
        let filed = min(drain.filed, drain.frozen)
        let waiting = max(0, drain.frozen - filed - reading - failed - skipped)
        return RunProgress(frozen: drain.frozen, filed: filed, read: reading, waiting: waiting, couldNotBeRead: failed,
                           calls: drain.calls, finished: drain.finished,
                           batches: drain.committedBatches ?? drain.batch)
    }

    var filedFraction: Double { frozen > 0 ? Double(filed) / Double(frozen) : 0 }
    var readFraction: Double { frozen > 0 ? Double(read) / Double(frozen) : 0 }

    /// The legend's words, left to right; zero terms are left out, except `filed`, which always leads.
    func legend(locale: Locale = .autoupdatingCurrent) -> [String] {
        if finished {
            return [Copy.SleepV5.filed(filed, locale), Copy.SleepV5.batches(batches, locale)]
                + (couldNotBeRead > 0 ? [Copy.SleepV5.couldNotBeRead(couldNotBeRead, locale)] : [])
        }
        var parts = [Copy.SleepV5.filed(filed, locale)]
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

/// The caption under the strip, in words (A3): what the running stage is doing, and a failure as words beside a
/// glyph — never colour alone (DR-7). `nil` when the run is not reading in batches.
func stageCaption(drain: SleepDrainInfo?, activeStage: Int?, locale: Locale = .autoupdatingCurrent) -> (text: String, failed: String?)? {
    guard let drain, drain.active, let activeStage, let batch = drain.batchState else { return nil }
    let failed = batch.failed > 0
        ? "\(Copy.SleepV5.couldNotBeRead(batch.failed, locale)), \(Copy.SleepV5.oneMoreTry)" : nil
    switch activeStage {
    case 1: return (Copy.SleepV5.readingCaption, failed)
    case 2: return (Copy.SleepV5.sortingCaption(read: batch.read, failed: batch.failed, locale), nil)
    case 3: return (Copy.SleepV5.decidingCaption(pages: drain.stages?.first { $0.id == "decide" }?.total, locale), nil)
    case 4: return (Copy.SleepV5.noticingCaption, nil)
    default: return (Copy.SleepV5.filingCaption, nil)
    }
}

/// The bar: filed in `textPrimary`, read-and-waiting in `textTertiary`, on a `bgBadge` track; the legend below with
/// the calls made on its right. One accessibility element with a value (A11); a fill settles with `SleepMotion`
/// (DR-61) and Reduce Motion holds the terminal frame (DR-66).
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
                Spacer(minLength: CicadaTheme.spacingSM)
                if let calls = progress.calls {
                    Text(Copy.SleepV5.callsMade(calls))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
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

/// The caption line under the strip (A3).
struct StageCaptionLine: View {
    let text: String
    let failed: String?

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(text)
            if let failed {
                Text(verbatim: "·").foregroundStyle(CicadaTheme.textTertiary)
                Image(systemName: "exclamationmark.triangle")
                    .foregroundStyle(CicadaTheme.warning)
                    .accessibilityHidden(true)
                Text(failed)
            }
            Spacer(minLength: 0)
        }
        .font(CicadaTheme.captionFont)
        .foregroundStyle(CicadaTheme.textSecondary)
        .accessibilityElement(children: .combine)
    }
}
