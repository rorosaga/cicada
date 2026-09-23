import Foundation

/// The facts of one past cycle an answer names (from `lastCycleEntry`, Z-P3 —
/// a `kind == "sleep"` commit, never the decay split or an inbox answer).
struct LastCycleFacts: Equatable {
    let episodes: Int
    let created: Int
    let updated: Int
    /// `SleepHistoryPresentation.durationText`, or `nil` when no measured
    /// duration joined — the clause is dropped, never estimated (G107).
    let durationText: String?

    init(episodes: Int, created: Int, updated: Int, durationText: String?) {
        self.episodes = episodes; self.created = created; self.updated = updated
        self.durationText = durationText
    }

    init(_ entry: SleepHistoryEntry) {
        self.init(episodes: entry.episodes, created: entry.entitiesCreated, updated: entry.entitiesUpdated,
                  durationText: entry.durationMs.map { SleepHistoryPresentation.durationText(ms: $0) })
    }
}

/// The answer ladder (Track Z §6.3): what the worm says when clicked, one rung
/// per click, back to the status sentence after the last. Pure and clock-free
/// (R8): ages and dates arrive already resolved by the page. A rung whose
/// facts are unknown is omitted; no rung restates the status numeral (R-Z7);
/// every rung obeys R-Z13's budgets, and one that would not is dropped rather
/// than truncated — a cut answer is not a true one.
func wormAnswers(_ ctx: RoomContext) -> [SentenceLine] {
    let rungs: [SentenceLine?]
    switch ctx.mood {
    case .reading, .hungry, .curious:
        rungs = [SentenceLine(lead: "Waiting for a night.", tail: ctx.oldestWait.map { "The oldest has waited \($0)." }),
                 whenRung(ctx), lastTimeRung(ctx), inboxRung(ctx)]
    case .happy:
        rungs = [SentenceLine(lead: "Nothing to read.", tail: "Everything captured has been filed."),
                 whenRung(ctx), lastTimeRung(ctx), inboxRung(ctx)]
    case .sleeping:
        let stage = SleepStages.all[max(1, min(SleepStages.all.count, ctx.activeStage ?? 1)) - 1]
        rungs = [SentenceLine(lead: "\(stage.title).", numeral: "\(stage.number)", tail: stage.detail),
                 engineRung(ctx, verb: "Running on")]
    case .digesting:
        rungs = [SentenceLine(lead: "Just filed that cycle.",
                              tail: "+\(count(ctx.cycleCreated, ctx)) new · \(count(ctx.cycleUpdated, ctx)) updated."),
                 whenRung(ctx)]
    case .error:
        let clause = sentenceClause(ctx.cycleError)
        rungs = [SentenceLine(lead: "The last cycle failed.", tone: .danger, tail: clause, tailTone: .danger,
                              action: clause == nil ? nil : .openDetails(.lastCycle)),
                 engineRung(ctx, verb: "It ran on"), lastTimeRung(ctx)]
    case .awake:
        rungs = [SentenceLine(lead: "I haven't heard from Cicada yet.", tail: "This fills in as soon as it answers.")]
    }
    return rungs.compactMap { $0 }.filter {
        $0.lead.count <= SentenceLine.maxLead && ($0.tail?.count ?? 0) <= SentenceLine.maxTail
    }
}

private func count(_ n: Int, _ ctx: RoomContext) -> String { UsageFormat.count(n, locale: ctx.locale) }

/// Rung 2 — when. Lamp off: say so and point at the lamp (Z6 makes that
/// link live; until then Z-P5 renders it as words).
private func whenRung(_ ctx: RoomContext) -> SentenceLine? {
    guard ctx.lampLit else {
        return SentenceLine(lead: "The lamp is off — I read when you ask.",
                            tail: "Press Consolidate now, or light the lamp.", action: .openLamp)
    }
    guard let when = ctx.nextRunWhen else { return nil }
    // A date takes the numeral's rounded digits; "after the next import
    // settles" is words and stays in the display face.
    return SentenceLine(lead: "Next: \(when).", numeral: when.contains(where: \.isNumber) ? when : nil,
                        tail: ctx.scheduledEngine.map { "\(Copy.scheduledRunsOn(engine: $0))." },
                        mark: ctx.scheduledEngine.map { SentenceMark.engine($0) })
}

/// Rung 3 — last time. `episodes == 0` is an older backend's default, an
/// unknown rather than a fact, so the rung is omitted.
private func lastTimeRung(_ ctx: RoomContext) -> SentenceLine? {
    guard let last = ctx.lastCycle, last.episodes > 0 else { return nil }
    let n = count(last.episodes, ctx)
    let tail = "+\(count(last.created, ctx)) new · \(count(last.updated, ctx)) updated"
        + (last.durationText.map { ", in \($0)" } ?? "") + "."
    return SentenceLine(lead: "Last time I read \(n) \(last.episodes == 1 ? "episode" : "episodes").",
                        numeral: n, tail: tail, action: .openDetails(.pastNights))
}

/// Rung 4 — you (spec decision 16: the last rung may point to the Inbox).
private func inboxRung(_ ctx: RoomContext) -> SentenceLine? {
    guard let n = ctx.inboxTotal, n > 0 else { return nil }
    if n == 1 {
        return SentenceLine(lead: "1 question waits for you.", numeral: "1", tail: "It's in the Inbox.", action: .openInbox)
    }
    let numeral = count(n, ctx)
    return SentenceLine(lead: "\(numeral) questions wait for you.", numeral: numeral,
                        tail: "They're in the Inbox.", action: .openInbox)
}

/// The engine a running or failed cycle used, with its mark (Z-P26). The
/// backend's `engineDetail` is shown sentence-cased, never reworded.
private func engineRung(_ ctx: RoomContext, verb: String) -> SentenceLine? {
    guard let engine = ctx.lastEngine else { return nil }
    // One under the budget: `sentenceCase` may append a stop, and an
    // 80-character clause plus "." failed the ladder's fit filter, which
    // dropped the whole engine rung (Task 6 review r1).
    return SentenceLine(lead: "\(verb) \(Copy.engineLabel(engine)).",
                        tail: sentenceCase(sentenceClause(ctx.engineDetail, limit: SentenceLine.maxTail - 1)),
                        mark: .engine(engine))
}
