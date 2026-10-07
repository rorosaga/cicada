import SwiftUI

// MARK: - The sentence slot's value (Track Z R-Z5, R-Z13, design §5)

/// How a line is tinted. With a `qualifier`, only that word takes the tone;
/// without one, the whole lead does. Colour is never the only carrier (§11):
/// the qualifier IS a word ("overdue") and every danger lead says "failed" or
/// "can't" in words.
enum SentenceTone: Hashable { case plain, warning, danger }

/// Details' four sections, and the scroll anchor each one carries (Task 4).
enum DetailsSection: String, CaseIterable, Hashable {
    case lastCycle, waiting, readout, pastNights
    var anchorID: String { "details.\(rawValue)" }
}

/// Where a tail link goes. Every case is a destination that exists on the page
/// or one tab away (R-Z2: a link that does nothing is a lie). Z-P5 rendered an
/// action as words until its destination existed; since Task 8 all five do.
enum SentenceAction: Hashable {
    case retry
    case openInbox
    case openDetails(DetailsSection)
    case openLamp
    case whatChanged
}

/// A service a line names. The round-3 rule is that a service named in the UI
/// shows its real mark (Z-P26). The slot draws this mark beside the tail:
/// `.origin` through `OriginMark` and `.engine` through `EngineMark`. It is a
/// value on the line so a test can read it; the view never guesses one from
/// the words.
enum SentenceMark: Hashable {
    case origin(String)
    case engine(String)
}

/// One line in the slot — the status sentence, or one rung of the worm's
/// answers (Task 6).
///
/// `lead` is the WHOLE visible lead (Z-P7): `numeral` and `qualifier` name
/// substrings of it that the view draws in SF rounded digits and in the
/// tone's colour. So the ≤ 40 rule, the "!" ban and VoiceOver all read one
/// string, and a number can sit mid-sentence ("Reading 138 of 203.").
/// `Hashable` so the slot can key its cross-fade on the line shown (Task 6).
struct SentenceLine: Hashable {
    var lead: String
    var numeral: String? = nil
    var qualifier: String? = nil
    var tone: SentenceTone = .plain
    var tail: String? = nil
    var tailTone: SentenceTone = .plain
    var action: SentenceAction? = nil
    /// The service the tail names, if any, drawn beside it as its mark.
    var mark: SentenceMark? = nil

    /// R-Z13's two budgets: one line of the 30 pt display face, two of 22 pt italic.
    static let maxLead = 40
    static let maxTail = 80

    /// What VoiceOver reads — the visible words, in order (§5).
    var spoken: String { [lead, tail].compactMap { $0 }.joined(separator: " ") }
}

enum SentenceRunKind: Equatable { case plain, numeral, qualifier }

struct SentenceRun: Equatable {
    let text: String
    let kind: SentenceRunKind
}

/// The lead cut into the runs the view draws differently — the numeral in SF
/// rounded digits (never the display face's digits), the qualifier in the
/// tone's colour, everything else in the display face. The runs always concatenate back to `lead`.
func sentenceRuns(_ line: SentenceLine) -> [SentenceRun] {
    var runs = [SentenceRun(text: line.lead, kind: .plain)]
    func carve(_ needle: String?, as kind: SentenceRunKind) {
        guard let needle, !needle.isEmpty else { return }
        var out: [SentenceRun] = []
        var carved = false
        for run in runs {
            guard !carved, run.kind == .plain, let range = run.text.range(of: needle) else {
                out.append(run)
                continue
            }
            let before = String(run.text[..<range.lowerBound])
            let after = String(run.text[range.upperBound...])
            if !before.isEmpty { out.append(SentenceRun(text: before, kind: .plain)) }
            out.append(SentenceRun(text: needle, kind: kind))
            if !after.isEmpty { out.append(SentenceRun(text: after, kind: .plain)) }
            carved = true
        }
        runs = out
    }
    carve(line.numeral, as: .numeral)
    carve(line.qualifier, as: .qualifier)
    return runs
}

/// Z-P8 — "a tail action renders its last words as a link", defined: the text
/// after the tail's last " — ", else the whole tail.
func tailLink(_ tail: String) -> String {
    guard let range = tail.range(of: " — ", options: .backwards) else { return tail }
    return String(tail[range.upperBound...])
}

/// The first line of `text`, cut on a word at `limit` with "…" — a tail is a
/// line, not a log. `nil` when there is nothing to say.
func sentenceClause(_ text: String?, limit: Int = SentenceLine.maxTail) -> String? {
    guard let first = text?.split(whereSeparator: \.isNewline).first
            .map({ String($0).trimmingCharacters(in: .whitespaces) }),
          !first.isEmpty else { return nil }
    guard first.count > limit else { return first }
    let cut = first.prefix(limit - 1)
    let onWord = cut.lastIndex(of: " ").map { cut[..<$0] } ?? cut
    return onWord.trimmingCharacters(in: CharacterSet(charactersIn: " ,;:—-")) + "…"
}

/// A backend sentence shown as the page's own (Z-P26): first letter up, a
/// closing stop if it has none — never reworded.
func sentenceCase(_ text: String?) -> String? {
    guard let trimmed = text?.trimmingCharacters(in: .whitespacesAndNewlines),
          let first = trimmed.first else { return nil }
    let cased = first.uppercased() + trimmed.dropFirst()
    return ".?…".contains(cased.last!) ? cased : cased + "."
}

// MARK: - What the sentence reads

/// Every fact the sentence and the answers read, resolved by the page
/// (`SleepPageModel.roomContext`). Nothing here reaches for a clock (R8).
struct RoomContext: Equatable {
    var mood: BookwormState = .awake
    var debt: SleepDebtView? = nil
    var queueLoad: StudyListCard.LoadState = .loaded(count: 0)
    /// 1…5 while running (R-Z14).
    var activeStage: Int? = nil
    var read: Int = 0
    var total: Int = 0
    var cycleError: String? = nil
    var cancelled: Bool = false
    var capped: Bool = false
    /// "Consolidate reads everything" (G163): a person-started run's measured progress
    /// and stop, `nil` when the last cycle was not one. Counts and one reason only.
    var drain: SleepDrainInfo? = nil
    /// The plan pause's reset time has passed (resolved by the page against its `now`, so the sentence stays
    /// clock-free): the pause is over, and the tail stops saying it.
    var planPauseLapsed: Bool = false
    var indexWarning: String? = nil
    var scheduleMode: String = "manual"
    var topOriginLabel: String? = nil
    /// The top row's origin id, for T12's mark.
    var topOrigin: String? = nil
    var locale: Locale = .autoupdatingCurrent

    // Task 6 — facts only the answer ladder reads (§6.3). Each is nil when
    // unknown, and a rung whose fact is nil is omitted (`wormAnswers`).
    var oldestWait: String? = nil
    var lampLit: Bool = false
    /// "Sep 24, 3:00 AM", or "after the next import settles"; nil when unknown.
    var nextRunWhen: String? = nil
    /// The scheduled engine's id, only when it differs from manual (ruling 4).
    /// An id rather than the sentence, so the rung can draw its mark.
    var scheduledEngine: String? = nil
    var lastCycle: LastCycleFacts? = nil
    var cycleCreated: Int = 0
    var cycleUpdated: Int = 0
    var lastEngine: String? = nil
    var engineDetail: String? = nil
    var inboxTotal: Int? = nil
    /// Task 8 (T7) — the commit the last real completion produced, while its
    /// "See what changed ›" link lives (`RoomModel.recentCycleCommit`).
    var recentCycleCommit: String? = nil

    // Sleep page v5 — the run's own facts (G163; rulings 13, 15, 16). Each nil when unknown.
    /// The paused run; its rungs outrank every idle rung (news before state).
    var paused: SleepPausedRun? = nil
    /// How often a run saves — the first night's tail says it.
    var batchSize: Int = 25
    /// The paused run's reset time in words ("after 3:40 PM"), resolved by the page (clock-free).
    var resetWhen: String? = nil
    /// When an armed automatic continue fires, in words; nil unless armed.
    var autoContinueWhen: String? = nil
    /// Pause was asked for and the run has not stopped yet.
    var pausing: Bool = false
}

/// The status sentence (design §5): the first matching lead row, then the
/// first matching tail row, so news always outranks state.
func roomSentence(_ ctx: RoomContext) -> SentenceLine {
    var line = sentenceLead(ctx)
    if let tail = sentenceTail(ctx) {
        line.tail = tail.text
        line.tailTone = tail.tone
        line.action = tail.action
        line.mark = tail.mark
    }
    return line
}

private struct SentenceTail {
    let text: String
    var tone: SentenceTone = .plain
    var action: SentenceAction? = nil
    var mark: SentenceMark? = nil
}

private func stage(_ ctx: RoomContext) -> SleepStage {
    SleepStages.all[max(1, min(SleepStages.all.count, ctx.activeStage ?? 1)) - 1]
}

private func sentenceLead(_ ctx: RoomContext) -> SentenceLine {
    switch ctx.queueLoad {
    case .failed: return SentenceLine(lead: "I can't see the queue.", tone: .danger)          // L1
    case .loading: return SentenceLine(lead: "Checking what's waiting…")                        // L2
    case .loaded: break
    }
    let count = { (n: Int) in UsageFormat.count(n, locale: ctx.locale) }
    if case .sleeping = ctx.mood, ctx.pausing { return SentenceLine(lead: Copy.SleepV5.pausingLead) }   // V1
    if let paused = ctx.paused { return pausedLead(paused) }                                       // V2
    switch ctx.mood {
    case .sleeping:
        let running = stage(ctx)
        if let counted = countedStageLead(ctx, stage: running.number) { return counted }        // V3 (P15)
        if running.number == SleepStages.all.count, ctx.drain?.stages != nil {                  // V4
            return SentenceLine(lead: Copy.SleepV5.filingLead)
        }
        guard running.number == 1 else { return SentenceLine(lead: "\(running.progressive)…") }  // L5
        // A run that reads in batches counts the batch it is on ("Reading 14 of 25."); the tail carries the run's.
        if let batch = ctx.drain?.batchState, ctx.drain?.active == true, batch.total > 0 {      // V7
            let numeral = "\(count(min(batch.read, batch.total))) of \(count(batch.total))"
            return SentenceLine(lead: "Reading \(numeral).", numeral: numeral)
        }
        guard ctx.total > 0 else { return SentenceLine(lead: "Reading…") }                       // L4
        let numeral = "\(count(ctx.read)) of \(count(ctx.total))"
        return SentenceLine(lead: "Reading \(numeral).", numeral: numeral)                      // L3
    case .error:
        return SentenceLine(lead: "The last cycle failed.", tone: .danger)                      // L6
    case .digesting:
        if let drain = ctx.drain, drain.finished, drain.filed > 0 {                              // V5
            let numeral = count(drain.filed)
            return SentenceLine(lead: Copy.SleepV5.filedLead(drain.filed, ctx.locale), numeral: numeral)
        }
        return SentenceLine(lead: "Filed.")                                                     // L7
    case .reading, .hungry, .curious:
        if let n = heroCount(ctx.mood, debt: ctx.debt), n > 0 {                                  // L8
            let numeral = count(n)
            // `heroQualifier` is asked, not re-derived: "first run" (P9) outranks
            // "overdue", and the tail says it in words (T8).
            guard heroQualifier(ctx.mood, debt: ctx.debt) == "overdue" else {
                return SentenceLine(lead: "\(numeral) to read.", numeral: numeral)
            }
            return SentenceLine(lead: "\(numeral) to read — overdue.", numeral: numeral,
                                qualifier: "overdue", tone: .warning)
        }
        if case .hungry = ctx.mood { return SentenceLine(lead: "Nothing new to read.") }        // L9
        return SentenceLine(lead: "Something new just arrived.")                                // L8b, Z-P6
    case .happy:
        return SentenceLine(lead: "All caught up.")                                             // L10
    case .awake:
        return SentenceLine(lead: "Listening.")                                                 // L11
    }
}

private func sentenceTail(_ ctx: RoomContext) -> SentenceTail? {
    if case .failed(let message) = ctx.queueLoad {                                               // T1
        return SentenceTail(text: sentenceClause(message) ?? "Try again.", tone: .danger, action: .retry)
    }
    if case .sleeping = ctx.mood, ctx.pausing {                                                  // V1
        return SentenceTail(text: Copy.SleepV5.pausingTail)
    }
    if let paused = ctx.paused { return pausedTail(paused, ctx) }                                 // V2
    if case .sleeping = ctx.mood {                                                               // T2 (P16)
        if let drain = ctx.drain, drain.active, drain.firstRun == true, drain.committedBatches == 1,
           let owner = drain.ownerPage {                                                          // V6 (first save)
            let firstBatch = min(drain.batchSize > 0 ? drain.batchSize : ctx.batchSize, drain.filed)
            return SentenceTail(text: Copy.SleepV5.firstSaveTail(filed: firstBatch, beliefs: owner.beliefs,
                                                                 ctx.locale))
        }
        let number = stage(ctx).number
        if number == 2, countedStageLead(ctx, stage: 2) != nil {                                  // V3 tails
            return SentenceTail(text: Copy.SleepV5.sortingTail)
        }
        if number == 3, countedStageLead(ctx, stage: 3) != nil {
            return SentenceTail(text: Copy.SleepV5.decidingTail)
        }
        if let drain = ctx.drain, drain.active, drain.batches > 1 {                              // T2b (G163)
            return SentenceTail(text: drainProgressClause(drain, locale: ctx.locale))
        }
        return SentenceTail(text: stage(ctx).detail)
    }
    if case .error = ctx.mood, let clause = sentenceClause(ctx.cycleError) {                     // T3
        return SentenceTail(text: clause, tone: .danger, action: .openDetails(.lastCycle))
    }
    if ctx.cancelled {                                                                           // T4
        if let drain = ctx.drain {                                                               // T4b (G163)
            // A cancel in batch 1 filed nothing, and the batch that was reading is dropped: not "nothing was lost".
            let text = drain.filed > 0 ? drainCancelledClause(drain, locale: ctx.locale)
                : "Stopped — nothing filed; the batch being read is read again."
            return SentenceTail(text: text, action: .openDetails(.lastCycle))
        }
        return SentenceTail(text: "Stopped early — nothing was lost.", action: .openDetails(.lastCycle))
    }
    if let drain = ctx.drain, !drain.active, drain.stop?.reason == "plan_limit", !ctx.planPauseLapsed {  // T4c (G163)
        // The vendor's own sentence carries the reset time, so it is never clipped: one too long for the tail
        // points at Details, where the paused row shows it whole.
        let vendor = drain.stop?.sentence.flatMap { $0.split(whereSeparator: \.isNewline).first }
            .map { String($0).trimmingCharacters(in: .whitespaces) }
        let text = vendor.flatMap { !$0.isEmpty && $0.count <= SentenceLine.maxTail ? $0 : nil }
            ?? (vendor == nil ? "Stopped at your plan's limit — the rest wait."
                              : "Stopped at your plan's limit — the reset time is in Details.")
        return SentenceTail(text: text, tone: .warning, action: .openDetails(.lastCycle))
    }
    if ctx.capped {                                                                              // T5
        return SentenceTail(text: "The rest wait for the next cycle.", action: .openDetails(.lastCycle))
    }
    if let warning = ctx.indexWarning, !warning.isEmpty {                                        // T6
        return SentenceTail(text: "Finished with a warning — it's in Details.", tone: .warning,
                            action: .openDetails(.lastCycle))
    }
    if ctx.recentCycleCommit != nil {                                                             // T7
        return SentenceTail(text: "See what changed ›", action: .whatChanged)
    }
    let count = ctx.debt?.unprocessedCount ?? 0
    if ctx.debt?.hasRunBefore == false {                                                         // T8 / T9
        return SentenceTail(text: count > 0 ? Copy.SleepV5.firstNightTail(batchSize: ctx.batchSize, ctx.locale)
                                            : "Nothing's been filed in this memory yet.")
    }
    if case .hungry = ctx.mood, let hours = ctx.debt?.hoursSinceLastCycle, hours >= 48 {         // T10
        return SentenceTail(text: "It's been \(Int(hours / 24)) days.")
    }
    if count > 0, ctx.scheduleMode == "manual" {                                                 // T11
        return SentenceTail(text: "The lamp is off — I read when you ask.", action: .openLamp)
    }
    if case .reading = ctx.mood, let label = ctx.topOriginLabel {                                // T12
        let text = "The \(label) pile is the big one."
        if text.count <= SentenceLine.maxTail {
            return SentenceTail(text: text, mark: ctx.topOrigin.map { SentenceMark.origin($0) })
        }
    }
    // T13 (Z9, Z-B19) — only once the queue has loaded: "Checking what's
    // waiting…" never carries an invitation.
    if case .happy = ctx.mood, case .loaded = ctx.queueLoad {                                    // T13
        return SentenceTail(text: "Drop a file on me to add it to the pile.")
    }
    return nil                                                                                   // T14
}

// MARK: Sleep page v5 rungs

/// "Sorting 31 of 86." / "Deciding 4 of 12." — only from a stage that counts something finished and whose total is
/// fixed (P15 as amended): Read keeps its own rung (L3), Notice and File never carry a fraction.
private func countedStageLead(_ ctx: RoomContext, stage number: Int) -> SentenceLine? {
    let id: String
    switch number {
    case 2: id = "sort"
    case 3: id = "decide"
    default: return nil
    }
    guard let counted = ctx.drain?.stages?.first(where: { $0.id == id }), let total = counted.total, total > 0 else {
        return nil
    }
    let done = min(counted.done, total)
    let numeral = "\(UsageFormat.count(done, locale: ctx.locale)) of \(UsageFormat.count(total, locale: ctx.locale))"
    let lead = id == "sort" ? Copy.SleepV5.sortingLead(done, total, ctx.locale)
                            : Copy.SleepV5.decidingLead(done, total, ctx.locale)
    return SentenceLine(lead: lead, numeral: numeral)
}

/// The paused run's lead, by why it paused. Never a failure's tone: a pause is a fact about a run, and it waits.
private func pausedLead(_ paused: SleepPausedRun) -> SentenceLine {
    switch paused.reason {
    case "reserve": SentenceLine(lead: Copy.SleepV5.pausedReserveLead)
    case "plan_window": SentenceLine(lead: Copy.SleepV5.pausedPlanWindowLead)
    case "plan_weekly": SentenceLine(lead: Copy.SleepV5.pausedPlanWeeklyLead)
    case "overage": SentenceLine(lead: Copy.SleepV5.pausedOverageLead)
    case "engine": SentenceLine(lead: paused.engineKind == "transient"
                               ? Copy.SleepV5.pausedEngineLead : Copy.SleepV5.pausedEngineFixLead, tone: .warning)
    case "restart": SentenceLine(lead: Copy.SleepV5.restartLead)
    case "bank_switched": SentenceLine(lead: Copy.SleepV5.bankSwitchedLead)
    default: SentenceLine(lead: Copy.SleepV5.pausedLead)
    }
}

/// The paused run's tail: what is filed, and when it can go on. Never "read and kept" — there is no journal, so the
/// part a Pause interrupted is read again (G163 SL-1).
private func pausedTail(_ paused: SleepPausedRun, _ ctx: RoomContext) -> SentenceTail {
    let (filed, frozen, locale) = (paused.filed, paused.frozen, ctx.locale)
    switch paused.reason {
    case "user":
        return SentenceTail(text: Copy.SleepV5.pausedByYouTail(filed: filed, frozen: frozen, locale))
    case "reserve":
        if let when = ctx.autoContinueWhen {
            return SentenceTail(text: Copy.SleepV5.continuesAfter(when, filed: filed, frozen: frozen, locale),
                                action: .openDetails(.lastCycle))
        }
        return SentenceTail(text: Copy.SleepV5.continueWhenYouLike(filed: filed, frozen: frozen, locale),
                            action: .openDetails(.lastCycle))
    case "plan_window", "overage":
        if let when = ctx.autoContinueWhen {
            return SentenceTail(text: Copy.SleepV5.continuesAfter(when, filed: filed, frozen: frozen, locale),
                                action: .openDetails(.lastCycle))
        }
        return SentenceTail(text: ctx.resetWhen.map(Copy.SleepV5.resetsContinue) ?? Copy.SleepV5.continueWhenItResets,
                            action: .openDetails(.lastCycle))
    case "plan_weekly":
        return SentenceTail(text: ctx.resetWhen.map(Copy.SleepV5.resetsThenContinue) ?? Copy.SleepV5.continueWhenItResets,
                            action: .openDetails(.lastCycle))
    case "engine":
        let text = paused.engineKind == "transient"
            ? Copy.SleepV5.continueToTryAgain(filed: filed, frozen: frozen, locale)
            : Copy.SleepV5.continueWhenFixed(filed: filed, frozen: frozen, locale)
        return SentenceTail(text: text,
                            tone: .warning, action: .openDetails(.lastCycle))
    case "restart":
        return SentenceTail(text: Copy.SleepV5.restartTail(filed: filed, frozen: frozen, locale))
    case "bank_switched":
        return SentenceTail(text: Copy.SleepV5.bankSwitchedTail)
    default:
        return SentenceTail(text: Copy.SleepV5.continueWhenYouLike(filed: filed, frozen: frozen, locale))
    }
}

/// The tail while a person-started run reads: which batch, and how much of what it set out to
/// read is already filed. Measured counts only (G107), in the reader's locale.
func drainProgressClause(_ drain: SleepDrainInfo, locale: Locale) -> String {
    let count = { (n: Int) in UsageFormat.count(n, locale: locale) }
    return "Batch \(count(drain.batch)) of \(count(drain.batches)) · \(count(drain.filed)) of \(count(drain.frozen)) filed."
}

/// After a cancel of a person-started run: what earlier batches filed stays filed. The batch that
/// was still reading is dropped (its reads are paid again next time), so this never says
/// "nothing was lost".
func drainCancelledClause(_ drain: SleepDrainInfo, locale: Locale) -> String {
    let filed = UsageFormat.count(drain.filed, locale: locale)
    return "Stopped — \(filed) filed stay filed; the rest wait."
}

/// The lamp's twin in words (§7.2): the schedule, then when the next run is —
/// or that the lamp is off.
func whisperLine(scheduleText: String, nextRunText: String, lampLit: Bool) -> String {
    lampLit ? "\(scheduleText) · \(nextRunText)" : "\(scheduleText) — the lamp is off"
}

// MARK: - The slot

/// The one place the worm speaks (R-Z5), directly under the room. Its height
/// is reserved — one lead line, two tail lines (`lineLimit(2, reservesSpace:)`)
/// — so a longer tail, an answer or no tail at all never reflows what sits
/// below it.
///
/// Meadow's faces (Z10, Z-B12; F1 R-FX13): the lead in the display face — SF
/// Pro Display semibold at 30 pt with `displayTracking`, shrinking only to the
/// display floor; the tail in the display face's italic (SF italic) at 22 pt —
/// the owner asked for a minimal sans, so the sentence no longer uses the
/// quote face.
struct RoomSentenceView: View {
    static let leadSize: CGFloat = 30
    static let tailSize: CGFloat = 22
    /// The lead fits one line by shrinking no further than the display
    /// face's own floor (R-M3) — the old 0.7 would have reached 21 pt.
    static var leadMinimumScale: CGFloat { CicadaTheme.displayMinimumSize / leadSize }

    /// The status sentence — what the slot shows whenever no answer is up.
    let line: SentenceLine
    /// Task 6 — the worm's answer ladder (`wormAnswers`). An answer REPLACES
    /// the status in this one slot (R-Z5, R-Z7): the worm never speaks in a
    /// second place.
    var answers: [SentenceLine] = []
    /// The room's interaction state; `nil` shows the status only.
    var room: RoomModel? = nil
    /// Track Z Z9 — whether the worm is asleep: all a feed line needs besides
    /// the router's phase (a sleeping worm reads it "after this nap").
    var feedAsleep = false
    /// Every `SentenceAction` has a destination since Task 8 built the last
    /// one (`.whatChanged`), so a tail with an action always renders as a
    /// link — Z-P5's `canPerform` seam existed only while some did not.
    var perform: (SentenceAction) -> Void = { _ in }

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(IntakeRouter.self) private var intake

    /// What the slot shows — `RoomModel.slot`'s ranking (final review,
    /// finding 1): a drag's "Is that for me?", then the answer rung the
    /// person asked for, then the drop's line driven by the router's own
    /// phase (Z-B9), then the status. The cross-fade keys on THIS, never on
    /// the line's words (Task 6 review r1): keyed on the whole line, every
    /// status tick ("Read a of b" during a cycle) rebuilt the slot and its
    /// tail Button, dropping keyboard focus off the link. A status change
    /// updates in place; only a change of kind or rung fades.
    private var slot: RoomSlot {
        guard let room else { return .status }
        return RoomModel.slot(drag: room.drag, result: room.feedResult, intakePhase: intake.phase,
                              answerIndex: room.answerIndex, answerCount: answers.count)
    }

    /// The line on show. Every read is the slot's, so what VoiceOver says and
    /// what a poke announces are what the slot shows.
    private func line(for slot: RoomSlot) -> SentenceLine {
        switch slot {
        case .status: line
        case .rung(let index): answers[index]
        case .feed(let feed): feedLine(feed, asleep: feedAsleep)
        }
    }

    var body: some View {
        let slot = slot
        let shown = line(for: slot)
        ZStack {
            VStack(spacing: CicadaTheme.spacingXS) {
                leadText(shown)
                    .font(CicadaTheme.displayFont(size: Self.leadSize))
                    .tracking(CicadaTheme.displayTracking(size: Self.leadSize))
                    .lineLimit(1)
                    .minimumScaleFactor(Self.leadMinimumScale)
                tailView(shown)
            }
            // Keyed on the kind of line so a status ⇄ answer ⇄ feed change
            // cross-fades (opacity only — the slot's height is reserved, so
            // nothing slides).
            .id(slot)
            .transition(.opacity)
        }
        .animation(SleepMotion.sentence(reduceMotion: reduceMotion), value: slot)
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .onHover { room?.pointerInSentence = $0 }
        // Every read below is `shown`, never `line`: VoiceOver reads what is
        // on screen, and the action follows the link that is on screen.
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(shown.spoken)
        .accessibilityActions {
            if let action = shown.action, let tail = shown.tail {
                Button(tailLink(tail)) { perform(action) }
            }
        }
        .accessibilitySortPriority(RoomA11yOrder.sentence)
        .task(id: DwellKey(slot: slot,
                           inside: (room?.pointerInRoom ?? false) || (room?.pointerInSentence ?? false))) {
            // I4 / Z-B11 — an answer or a finished feed line returns to the
            // status after `answerDwell` with the pointer outside the room and
            // the sentence; any re-entry restarts this task.
            guard let room, room.answerIndex != nil || room.feedResult?.isTerminal == true,
                  !room.pointerInRoom, !room.pointerInSentence else { return }
            try? await Task.sleep(for: SleepMotion.answerDwell)
            guard !Task.isCancelled else { return }
            room.dismissSlot()
        }
        // Z-B9 — the room's drop follows the router's phase; a landing is
        // announced because the person pressed Done (§11).
        .onChange(of: intake.phase) { old, new in
            guard let ended = room?.intakeChanged(from: old, to: new,
                                                  overlayPresented: intake.isOverlayPresented) else { return }
            AccessibilityNotification.Announcement(feedLine(ended, asleep: feedAsleep).spoken).post()
        }
    }

    private func color(_ tone: SentenceTone, plain: Color) -> Color {
        switch tone {
        case .plain: plain
        case .warning: CicadaTheme.warning
        case .danger: CicadaTheme.danger
        }
    }

    private func leadText(_ line: SentenceLine) -> Text {
        let plainColor = line.qualifier == nil ? color(line.tone, plain: CicadaTheme.textPrimary) : CicadaTheme.textPrimary
        return sentenceRuns(line).reduce(Text(verbatim: "")) { text, run in
            switch run.kind {
            case .plain:
                return text + Text(verbatim: run.text).foregroundStyle(plainColor)
            case .numeral:
                return text + Text(verbatim: run.text)
                    .font(CicadaTheme.font(size: Self.leadSize, weight: .medium, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(plainColor)
            case .qualifier:
                return text + Text(verbatim: run.text).foregroundStyle(color(line.tone, plain: CicadaTheme.textPrimary))
            }
        }
    }

    /// The tail, with the mark of the service it names beside it (Z-P26). The
    /// slot is one ignored-children element, so the mark adds nothing to what
    /// VoiceOver reads. The words already name the service.
    private func tailView(_ line: SentenceLine) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingXS) {
            if let mark = line.mark {
                SentenceMarkView(mark: mark)
                    .padding(.top, CicadaTheme.spacingXS)
            }
            tailText(line)
        }
    }

    @ViewBuilder
    private func tailText(_ line: SentenceLine) -> some View {
        let tail = line.tail ?? " "
        let tailFont = CicadaTheme.displayFont(size: Self.tailSize, italic: true)
        let tailColor = color(line.tailTone, plain: CicadaTheme.textSecondary)
        if let action = line.action, line.tail != nil {
            let link = tailLink(tail)
            let prefix = String(tail.dropLast(link.count))
            Button { perform(action) } label: {
                (Text(verbatim: prefix).foregroundStyle(tailColor)
                 + Text(verbatim: link).foregroundStyle(CicadaTheme.accent))
                    .font(tailFont)
                    .lineLimit(2, reservesSpace: true)
            }
            .buttonStyle(.cicadaPlain)
        } else {
            Text(verbatim: tail)
                .font(tailFont)
                .foregroundStyle(tailColor)
                .lineLimit(2, reservesSpace: true)
        }
    }
}

/// What the dwell task restarts on: the line on show, and whether the pointer
/// is inside the room or the sentence.
private struct DwellKey: Equatable {
    let slot: RoomSlot
    let inside: Bool
}

/// A `SentenceMark`, drawn. At 18 pt it sits beside the 22 pt italic tail
/// without out-weighing it.
private struct SentenceMarkView: View {
    let mark: SentenceMark

    var body: some View {
        switch mark {
        case .origin(let origin): OriginMark(origin: origin, size: 18)
        case .engine(let engine): EngineMark(engine: engine, size: 18)
        }
    }
}
