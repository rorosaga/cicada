import SwiftUI

// MARK: - The run, as one quiet object (owner 2026-11-26)
//
// "redesign how when sleep is in progress, how that shows. Design rn is hella ugly. something minimal like a loading
// bar with some other stuff is good, no need to explain everything. something minimal that informs the user."
//
// A run used to be seven or eight things (the status chip, a sentence that explained the stage, the stage stepper, a
// bar, a legend of five counts, a "Running 27 m" caption, the engine's note), three of them counting different
// quantities, hung under the room's row so the page jumped when a run started. Now it is ONE object in the block
// beside the room, in the slot the status chip held, so the block keeps the room's height in every state:
//
//     [dot] Sorting                                   74 of 287 · 27 min
//     ━━━━━━━━━━━━━━━━━━━━━░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
//
// It answers three questions at a glance: is it working (the word and its live mark), how far along is it (the one
// count and the one bar), can I stop it (the run bar's Pause under it, unchanged). Paused, just finished, stopped and
// failed are the same object with their own word. Everything else the old stack said is a `.help` or VoiceOver's value;
// the one thing that may sit under the bar is a note that changes what the person should do or expect (`RunLine.note`).

/// What the run object says, pure so `SleepRunObjectTests` holds every state without a view. Built from the page's own
/// reading (`SleepPageModel`), so it can never disagree with the controls beside it (H1).
struct RunLine: Equatable {
    enum Kind: Equatable { case running, pausing, waiting, paused, finished, stopped, failed }

    /// The one line that may sit under the bar. Never an explanation of a stage.
    struct Note: Equatable {
        enum Style: Equatable {
            /// A glyph beside words, never colour alone (DR-7): conversations that could not be read.
            case caution
            /// A quiet fact: what a stop does while it files.
            case plain
            /// Words whose last clause is a link (`tailLink`): "See what changed ›".
            case link
            /// A sentence that is itself quiet and opens Past sleeps: the words in `textSecondary` with a small chevron,
            /// so a whole line is never accent-blue (DR-5's links are a clause, not a paragraph).
            case detail
            /// The first run's link to the person's own page.
            case ownerPage
        }
        var text: String
        var style: Style = .plain
        var action: SentenceAction? = nil
        /// The note's tooltip, when it has more to say than where it goes.
        var help: String? = nil
    }

    var kind: Kind
    /// The step in a word ("Sorting"), or what the run is doing or did ("Paused. Your plan window is full", "Filed 287
    /// conversations", "Stopped while sorting").
    var word: String
    /// The word's tooltip: what the stage does, the old stage caption's words.
    var help: String? = nil
    /// The quiet breathing mark: only while a step is really running.
    var live = false
    /// A glyph beside the word for a stop that needs a look (DR-7: warning is for a stopped run).
    var warns = false
    /// The run's own count: conversations filed of the ones frozen at its start. Nothing else is counted on screen.
    var count: String? = nil
    /// How long it has read, measured (G107 — never a remaining time).
    var elapsed: String? = nil
    /// The bar's arithmetic (`RunProgress`); `nil` draws no fill, ever (P15).
    var progress: RunProgress? = nil
    /// Reading with nothing countable (the old single-pass shape): a breathing track, no invented fraction.
    var indeterminate = false
    var note: Note? = nil

    /// The words the object's trailing edge carries: "74 of 287 · 27 min".
    var trailing: [String] { [count, elapsed].compactMap { $0 } }

    /// `nil` when the page has no run to show: the status chip and its sentence stay (idle, caught up, a refused night).
    /// - Parameters:
    ///   - recentCycleCommit: the room's memory of a completion it watched — the "See what changed" window.
    ///   - canOpenOwnerPage: the owner's page exists in the graph, so the first run's link has somewhere to go.
    static func from(_ page: SleepPageModel, recentCycleCommit: String? = nil, canOpenOwnerPage: Bool = false,
                     locale: Locale = .autoupdatingCurrent) -> RunLine? {
        // A queue the page cannot see outranks everything (the sentence's L1/L2, with its Retry).
        guard case .loaded = page.queueLoad else { return nil }
        let drain = page.drain
        let progress = RunProgress.from(drain)
        let count = progress.map { Copy.SleepV5.runCount($0.filed, $0.frozen, locale) }
        let elapsed = drain?.elapsedMs.flatMap { $0 > 0 ? Copy.SleepV5.elapsed(ms: $0) : nil }
        let stage = page.runningStage.map { SleepStages.all[max(1, min(SleepStages.all.count, $0)) - 1] }

        // 1. A run reading right now.
        if page.isRunning {
            let running = stage ?? SleepStages.all[0]
            if page.pausing {
                return RunLine(kind: .pausing, word: Copy.SleepV5.pausing, help: Copy.SleepV5.pausingTail, live: true,
                               count: count, elapsed: elapsed, progress: progress, indeterminate: progress == nil)
            }
            if let cause = drain?.waiting {
                return RunLine(kind: .waiting, word: trimmed(Copy.SleepV5.waitingForNetworkLead),
                               help: Copy.SleepV5.waitingForNetworkTail(cause), count: count, elapsed: elapsed,
                               progress: progress, indeterminate: progress == nil)
            }
            var note: Note?
            if let failure = batchFailureNote(drain: drain, activeStage: page.runningStage, locale: locale) {
                note = Note(text: failure, style: .caution)
            } else if let progress, progress.couldNotBeRead > 0 {
                note = Note(text: Copy.SleepV5.couldNotBeRead(progress.couldNotBeRead, locale), style: .caution)
            } else if running.number == SleepStages.all.count {
                note = Note(text: Copy.SleepV5.filingWhisper)
            } else if let drain, canOpenOwnerPage, drain.active, drain.firstRun == true,
                      drain.committedBatches == 1, drain.ownerPage != nil {
                note = Note(text: Copy.SleepV5.seeYourPage, style: .ownerPage)
            }
            return RunLine(kind: .running, word: running.progressive, help: purpose(of: running, drain: drain),
                           live: true, count: count, elapsed: elapsed, progress: progress,
                           indeterminate: progress == nil, note: note)
        }

        // 2. A run that waits paused: the pause's own words — why, and what to do — with the bar held.
        if page.paused != nil {
            let sentence = roomSentence(page.roomContext(recentCycleCommit: recentCycleCommit, locale: locale))
            // A pause record keeps its own counts, so the bar is held even when the run's drain is gone (a restart).
            let held = progress ?? page.paused.map {
                RunProgress(frozen: $0.frozen, filed: min($0.filed, $0.frozen), read: 0,
                            waiting: max(0, $0.frozen - $0.filed), couldNotBeRead: 0, calls: nil, finished: false,
                            batches: 0)
            }
            // The promise of an armed automatic continue (ruling 15) is in the note's own words ("Continues after
            // 3:14 PM"); why it will — "you said so for the runs you start" — is its tooltip, not a second line.
            let help = page.autoContinueWhen.map(Copy.SleepV5.willContinueBySelf)
            return RunLine(kind: .paused, word: trimmed(sentence.lead), warns: sentence.tone == .warning,
                           progress: held.flatMap { $0.frozen > 0 ? $0 : nil }, note: sentence.tail.map { tail in
                               Note(text: tail, style: sentence.action == nil ? .plain : .detail, action: sentence.action,
                                    help: help)
                           })
        }

        // 3. A run that failed: where it stopped, and where to look.
        if page.cycleError != nil {
            return RunLine(kind: .failed, word: Copy.SleepV5.stoppedWhile(page.stoppedStage.map { SleepStages.all[$0 - 1].progressive }),
                           warns: true, count: count, progress: progress,
                           note: Note(text: Copy.SleepV5.readingStoppedTail, style: .detail, action: .openDetails(.lastCycle)))
        }

        // 4. A run that was stopped (a cancel, or a limit): where it stopped, what stays, the bar where it stopped.
        if page.stoppedEarly, let progress {
            let limit = drain?.stop?.reason == "plan_limit"
            let text = limit ? (drain?.stop?.limit == "key_limit" ? Copy.SleepV5.keyLimitTail : Copy.SleepV5.stoppedAtLimit)
                             : Copy.SleepV5.stoppedKeepsFiled
            return RunLine(kind: .stopped, word: Copy.SleepV5.stoppedWhile(page.stoppedStage.map { SleepStages.all[$0 - 1].progressive }),
                           count: Copy.SleepV5.runCount(progress.filed, progress.frozen, locale), progress: progress,
                           note: Note(text: text, style: .detail, action: .openDetails(.lastCycle)))
        }

        // 5. A run that just finished: what it filed, the bar full, and the way to what changed. Nothing cheers.
        if let drain, drain.finished, drain.filed > 0, let progress,
           recentCycleCommit != nil || isDigesting(page.mood) {
            // The way to what changed is the sentence's own T7 tail, said once.
            let sentence = roomSentence(page.roomContext(recentCycleCommit: recentCycleCommit, locale: locale))
            let link = sentence.action == .whatChanged ? sentence.tail : nil
            return RunLine(kind: .finished, word: trimmed(Copy.SleepV5.filedLead(drain.filed, locale)),
                           elapsed: elapsed, progress: progress,
                           note: link.map { Note(text: $0, style: .link, action: .whatChanged) })
        }
        return nil
    }

    /// The word's tooltip: what the stage does. Sort and Decide keep the counted stages' own sentences.
    private static func purpose(of stage: SleepStage, drain: SleepDrainInfo?) -> String {
        switch stage.number {
        case 2 where drain?.stages != nil: Copy.SleepV5.sortingTail
        case 3 where drain?.stages != nil: Copy.SleepV5.decidingTail
        default: stage.detail
        }
    }

    private static func isDigesting(_ mood: BookwormState) -> Bool {
        if case .digesting = mood { return true }
        return false
    }

    /// The chip's rule (`statusParts`): the object ends on its last word, not on a stop.
    private static func trimmed(_ lead: String) -> String {
        var text = lead
        while let end = text.last, end == "." || end == " " { text.removeLast() }
        return text
    }
}

// MARK: - The view

/// The object, drawn: one line, one bar, and at most one note. Left-aligned on the block's edge in every layout — the
/// bar spans exactly the run bar's card under it. `RoomSentenceView` puts it in the status slot.
struct RunObjectView: View {
    let run: RunLine
    var perform: (SentenceAction) -> Void = { _ in }
    var openOwnerPage: () -> Void = {}

    /// The bar's height before `uiScale`: thin, a line and not a gauge.
    static let barHeight: CGFloat = 4
    /// The live mark's diameter before `uiScale`.
    static let markSize: CGFloat = 7

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            line
            bar
            if let note = run.note { noteView(note) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
    }

    private var line: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
            if run.warns && !run.live {
                Image(systemName: "exclamationmark.triangle")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.warning)
                    .accessibilityHidden(true)
            }
            Text(verbatim: run.word)
                .font(CicadaTheme.font(size: 15, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
                .help(run.help ?? "")
            // The live mark follows the word, so the word keeps its place whatever the run is doing.
            if run.live {
                LiveDot(diameter: CicadaTheme.scaled(Self.markSize))
                    .accessibilityHidden(true)
            }
            Spacer(minLength: CicadaTheme.spacingMD)
            if !run.trailing.isEmpty { trailing }
        }
        .accessibilityElement(children: .combine)
    }

    /// "74 of 287 · 27 min": the count in `textSecondary`, the time a step quieter, tabular digits so the line does not
    /// shimmer as they change.
    private var trailing: some View {
        let count = run.count.map { Text(verbatim: $0).foregroundStyle(CicadaTheme.textSecondary) }
        let elapsed = run.elapsed.map { Text(verbatim: $0).foregroundStyle(CicadaTheme.textTertiary) }
        let dot = Text(verbatim: " · ").foregroundStyle(CicadaTheme.textTertiary)
        let joined: Text = switch (count, elapsed) {
        case let (count?, elapsed?): count + dot + elapsed
        case let (count?, nil): count
        case let (nil, elapsed?): elapsed
        default: Text(verbatim: "")
        }
        return joined
            .font(CicadaTheme.metaFont)
            .monospacedDigit()
            .lineLimit(1)
            .fixedSize()
    }

    @ViewBuilder
    private var bar: some View {
        if let progress = run.progress {
            RunMeter(progress: progress)
        } else if run.indeterminate {
            BreathingBar()
                .frame(height: CicadaTheme.scaled(Self.barHeight))
                .accessibilityHidden(true)
        }
    }

    @ViewBuilder
    private func noteView(_ note: RunLine.Note) -> some View {
        switch note.style {
        case .caution:
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: "exclamationmark.triangle")
                    .foregroundStyle(CicadaTheme.warning)
                    .accessibilityHidden(true)
                Text(verbatim: note.text)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            .font(CicadaTheme.captionFont)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityElement(children: .combine)
        case .plain:
            Text(verbatim: note.text)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        case .ownerPage:
            InlineLink(title: note.text, action: openOwnerPage)
        case .detail:
            if let action = note.action {
                Button { perform(action) } label: {
                    HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
                        Text(verbatim: note.text)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .multilineTextAlignment(.leading)
                        Image(systemName: "chevron.right")
                            .font(CicadaTheme.icon(.disclosure))
                            .foregroundStyle(CicadaTheme.accentText)
                            .accessibilityHidden(true)
                    }
                    .font(CicadaTheme.captionFont)
                    .fixedSize(horizontal: false, vertical: true)
                }
                .buttonStyle(.cicadaPlain)
                .help(note.help ?? Copy.sleepDetails)
            }
        case .link:
            if let action = note.action {
                let link = tailLink(note.text)
                let prefix = String(note.text.dropLast(link.count))
                Button { perform(action) } label: {
                    (Text(verbatim: prefix).foregroundStyle(CicadaTheme.textTertiary)
                     + Text(verbatim: link).foregroundStyle(CicadaTheme.accentText))
                        .font(CicadaTheme.captionFont)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .buttonStyle(.cicadaPlain)
            } else {
                Text(verbatim: note.text)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// The bar: filed in `textPrimary` (ink, not the accent — DR-5), read-and-not-yet-filed a lighter stretch in
/// `textTertiary`, on a `bgBadge` track, the block's full width. One accessibility element with a value (A11); its
/// `.help` is the list the old legend printed (the batch's position, what waits, the calls made). A fill settles with
/// `SleepMotion` (DR-61); Reduce Motion holds the terminal frame (DR-66).
struct RunMeter: View {
    let progress: RunProgress
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
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
        .frame(height: CicadaTheme.scaled(RunObjectView.barHeight))
        .help(progress.accessibilityValue())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Copy.SleepV5.progressLabel)
        .accessibilityValue(progress.accessibilityValue())
    }
}
