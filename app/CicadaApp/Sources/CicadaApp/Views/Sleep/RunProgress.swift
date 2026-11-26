import SwiftUI

// MARK: - The run's progress, in counts (Sleep page v5, G163)

/// What the run object's bar draws for a run that reads in batches: finished work only, from the objects that did
/// it (spec 4.2). `filed + read + waiting + couldNotBeRead + skipped == frozen` at every step, `calls` and `filed` only
/// grow, and there is no remaining time anywhere (G107). Pure, so `SleepV5ProgressBarTests` holds the arithmetic.
/// Since 2026-11-26 the screen shows one count of it (`filed` of `frozen`, `RunLine`); the rest — the batch's position,
/// what waits, the calls made — is the bar's `.help` and its VoiceOver value (`accessibilityValue`).
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
/// that could not be read and get one more try, in words beside a glyph — never colour alone (DR-7). It is the run
/// object's caution note while it reads. `nil` when nothing failed or the run is not reading.
func batchFailureNote(drain: SleepDrainInfo?, activeStage: Int?, locale: Locale = .autoupdatingCurrent) -> String? {
    guard let drain, drain.active, let activeStage, activeStage <= 2,
          let batch = drain.batchState, batch.failed > 0 else { return nil }
    return "\(Copy.SleepV5.couldNotBeRead(batch.failed, locale)), \(Copy.SleepV5.oneMoreTry)"
}
