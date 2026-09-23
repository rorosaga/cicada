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

    /// R-Z13's two budgets: one line of 30 pt serif, two of 22 pt italic.
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
/// rounded digits (never serif digits), the qualifier in the tone's colour,
/// everything else in the serif. The runs always concatenate back to `lead`.
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
    switch ctx.mood {
    case .sleeping:
        let running = stage(ctx)
        guard running.number == 1 else { return SentenceLine(lead: "\(running.progressive)…") }  // L5
        guard ctx.total > 0 else { return SentenceLine(lead: "Reading…") }                       // L4
        let numeral = "\(count(ctx.read)) of \(count(ctx.total))"
        return SentenceLine(lead: "Reading \(numeral).", numeral: numeral)                      // L3
    case .error:
        return SentenceLine(lead: "The last cycle failed.", tone: .danger)                      // L6
    case .digesting:
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
    if case .sleeping = ctx.mood { return SentenceTail(text: stage(ctx).detail) }                // T2 (P16)
    if case .error = ctx.mood, let clause = sentenceClause(ctx.cycleError) {                     // T3
        return SentenceTail(text: clause, tone: .danger, action: .openDetails(.lastCycle))
    }
    if ctx.cancelled {                                                                           // T4
        return SentenceTail(text: "Stopped early — nothing was lost.", action: .openDetails(.lastCycle))
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
        return SentenceTail(text: count > 0 ? "My first night — nothing's been filed yet."
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
/// Meadow's faces (Z10, Z-B12): the lead in Instrument Serif at 30 pt, shrinking
/// only to the display floor; the tail in New York italic at 22 pt — two lines
/// of text, which is what the quote face is optically sized for.
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

    /// Z9 — a feed line outranks an answer and the status (§7.4): during a
    /// drag the slot asks "Is that for me?", after a drop it tells what
    /// happened, driven by the router's own phase (Z-B9).
    private var feedShown: FeedPhase? {
        room.flatMap { RoomModel.feedPhase(drag: $0.drag, result: $0.feedResult, intakePhase: intake.phase) }
    }

    /// The line on show: a feed line, else the answer rung the worm is on,
    /// else the status. An index that outlived its ladder (the facts changed
    /// under it) falls back to the status rather than trapping.
    private var shown: SentenceLine {
        if let feed = feedShown { return feedLine(feed, asleep: feedAsleep) }
        return shownRung.map { answers[$0] } ?? line
    }

    /// What the cross-fade keys on: the kind of line, never its words, so a
    /// status tick ("Read a of b") updates in place (Task 6 review r1).
    private var slot: SlotKey {
        if let feed = feedShown { return .feed(feed) }
        return shownRung.map { .rung($0) } ?? .status
    }

    /// Which rung is on show — `nil` for the status. The cross-fade keys on
    /// THIS, not on the line (Task 6 review r1): keyed on the whole line,
    /// every status tick ("Read a of b" during a cycle) rebuilt the slot and
    /// its tail Button, dropping keyboard focus off the link. A status change
    /// now updates in place; only status ⇄ answer and rung → rung fade.
    private var shownRung: Int? {
        room?.answerIndex.flatMap { answers.indices.contains($0) ? $0 : nil }
    }

    var body: some View {
        let shown = shown
        let slot = slot
        ZStack {
            VStack(spacing: CicadaTheme.spacingXS) {
                leadText(shown)
                    .font(CicadaTheme.displayFont(size: Self.leadSize))
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
            guard let landing = room?.intakeChanged(from: old, to: new) else { return }
            AccessibilityNotification.Announcement(feedLine(.landed(landing), asleep: feedAsleep).spoken).post()
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
        let tailFont = CicadaTheme.quoteFont(size: Self.tailSize)
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

/// What the slot shows: the status, an answer rung, or a feed line (Z9).
private enum SlotKey: Hashable {
    case status
    case rung(Int)
    case feed(FeedPhase)
}

/// What the dwell task restarts on: the line on show, and whether the pointer
/// is inside the room or the sentence.
private struct DwellKey: Equatable {
    let slot: SlotKey
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
