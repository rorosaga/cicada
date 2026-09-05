import SwiftUI

// MARK: - Sleep debt resolution (SSE-first, REST fallback)

/// A merged, presentation-ready read of "how far behind is Sleep" — Rested %
/// and its components. `resolveSleepDebt` prefers the continuously-updating
/// SSE `sleep` event (so the number moves even while idle, with no separate
/// poll loop) and falls back to whatever the last `/sleep/status` fetch
/// returned whenever the SSE stream hasn't produced a debt block yet (cold
/// start, or momentarily reconnecting) — same "never blank, last-known-good"
/// posture the rest of the Store already has.
struct SleepDebtView: Equatable {
    var restedPct: Int?
    var volumePct: Int
    var agePct: Int
    var unprocessedCount: Int
    var hasRunBefore: Bool
    var hoursSinceLastCycle: Double?
}

/// Pure so the SSE-vs-REST precedence is unit-testable without a live
/// connection. `sse` wins field-by-field only when it actually carries a
/// value (an SSE payload predating this field, or one that hasn't ticked
/// since reconnect, decodes those as `nil`) — never a partial merge that
/// mixes a stale SSE `unprocessedCount` with a fresher REST `restedPct`, so
/// this returns SSE's own full reading or REST's, never a hybrid of both.
func resolveSleepDebt(sse: SleepEventPayload?, status: SleepStatusResponse?) -> SleepDebtView? {
    if let sse, let unprocessedCount = sse.unprocessedCount {
        return SleepDebtView(
            restedPct: sse.restedPct,
            volumePct: sse.volumePct ?? 0,
            agePct: sse.agePct ?? 0,
            unprocessedCount: unprocessedCount,
            hasRunBefore: sse.hasRunBefore ?? false,
            hoursSinceLastCycle: sse.hoursSinceLastCycle
        )
    }
    guard let debt = status?.debt else { return nil }
    return SleepDebtView(
        restedPct: debt.restedPct,
        volumePct: debt.volumePct,
        agePct: debt.agePct,
        unprocessedCount: debt.unprocessedCount,
        hasRunBefore: debt.hasRunBefore,
        hoursSinceLastCycle: debt.hoursSinceLastCycle
    )
}

/// Same SSE-first, REST-fallback precedence as `resolveSleepDebt`, for the
/// single Progress % scalar.
func resolveProgressPct(sse: SleepEventPayload?, status: SleepStatusResponse?) -> Int? {
    sse?.progressPct ?? status?.progressPct
}

/// Same SSE-first, REST-fallback precedence again (G125 Task 7), for the two
/// per-origin dicts the desk card's book pile and study list both read.
/// `sse`'s own dict wins only when it is non-nil — an SSE payload predating
/// G125 R3, or one that hasn't ticked since reconnect, decodes both as `nil`
/// and must fall back to the last REST `/sleep/status` fetch rather than
/// being read as "nothing queued". Neither source ever returns `nil` itself
/// (both `SleepStatusResponse` fields default to `[:]` on decode), so the
/// only genuinely empty result is "no status has loaded yet at all".
func resolveOriginCounts(
    sse: SleepEventPayload?,
    status: SleepStatusResponse?
) -> (queueByOrigin: [String: Int], readByOrigin: [String: Int]) {
    let queue = sse?.queueByOrigin ?? status?.queueByOrigin ?? [:]
    let read = sse?.readByOrigin ?? status?.readByOrigin ?? [:]
    return (queue, read)
}

// MARK: - Mood derivation (reuses BookwormState — see MenuBar/BookwormState.swift)

/// The Sleep page's OWN mood derivation. Reuses the same `BookwormState`
/// cases the menu-bar bookworm derives to, but from DIFFERENT inputs: Sleep
/// debt (unprocessed queue + time since Sleep last ran), not the menu bar's
/// inbox-item count + capture staleness (`deriveBookwormState` in
/// `MenuBar/BookwormState.swift`, untouched by this — different question,
/// different derivation, same vocabulary of states).
///
/// Precedence (highest wins), mirroring `deriveBookwormState`'s own stated
/// order: sleeping > error > digesting > hungry > curious > happy > awake.
///
/// - `justFinishedAt`: set by the caller the moment its own poll observes a
///   running -> idle transition (mirrors `MenuBarManager`'s own tracking);
///   `.digesting` shows for 6s after, matching the menu bar's window.
/// - `intakeInFlight`: `Store.intakeInFlight` (G125 R2) — the upload overlay
///   sets this while an import/upload is landing. It forces `.reading` ahead
///   of happy/hungry (the worm is visibly busy consuming what just arrived,
///   even if the queue reads 0 because the fetch hasn't caught up yet) but
///   never ahead of sleeping/error/digesting — those three are already-true
///   facts about the LAST or CURRENT cycle, and intake-in-flight is only a
///   hint about what is about to be queued.
func deriveSleepPageMood(
    status: SleepStatusResponse?,
    debt: SleepDebtView?,
    justFinishedAt: Date?,
    intakeInFlight: Bool = false,
    now: Date = .now
) -> BookwormState {
    guard let status else { return .awake }
    if status.status == "running" {
        return .sleeping(stage: max(1, min(5, status.stage)))
    }
    if let err = status.error, !err.isEmpty {
        return .error   // R6: the failure is the news, not the six-second chew
    }
    if let f = justFinishedAt, now.timeIntervalSince(f) < 6 {
        return .digesting
    }
    if intakeInFlight {
        return .reading
    }
    guard let debt else { return .awake }
    if debt.unprocessedCount == 0 {
        return .happy
    }
    // "Large debt" — rested has fallen to a fifth or less — OR "long gap"
    // — Sleep hasn't run in two days — either is enough to read as hungry,
    // matching the OR the spec asked for (not requiring both at once).
    let largeDebt = (debt.restedPct ?? 100) <= 20
    let longGap = (debt.hoursSinceLastCycle ?? 0) > 48
    if largeDebt || longGap {
        return .hungry
    }
    // R2: the Sleep page reads a non-empty, non-overdue queue as "reading",
    // never "curious" — `.curious` on this page would collide with the menu
    // bar's own meaning of the same case (inbox items), and the study desk's
    // whole point is showing the worm at work on what's queued.
    return .reading
}

// MARK: - Bracket caption (G107: rendered under the page mascot)

/// The bracketed, monospaced status line is the caption `BookwormView` shows
/// beneath the 24×24 colour sprite on the Sleep page (ruling R9). From
/// 2026-09-01 until the art shipped on 2026-09-02 it was the WHOLE mascot —
/// the old ~16×16 template glyph could not show mood at page scale, so the
/// interim ruling was one line of plain text; the 2026-09-02 ask superseded
/// that, and the text survived as the caption rather than the character.
/// It still reuses the SAME `BookwormState` `deriveSleepPageMood` produces,
/// so the worm and its caption can never disagree about the mood.
func sleepDebtBracketText(_ state: BookwormState, debt: SleepDebtView?) -> String {
    switch state {
    case .awake:
        return "[ awake ]"
    case .sleeping(let stage):
        return "[ sleeping · stage \(stage) of 5 ]"
    case .digesting:
        return "[ digesting ]"
    case .happy:
        return "[ caught up ]"
    case .curious(let count):
        return "[ \(count) episode\(count == 1 ? "" : "s") behind ]"
    case .reading:
        // Same count the bubble reads (unprocessedCount), but this is the
        // caption under the sprite, not the bubble's sentence (Task 5
        // interface: `"[ N to read ]"`) — `0` still says "0 to read" rather
        // than something bespoke, since `intakeInFlight` can hold `.reading`
        // with an as-yet-unrefreshed queue count of 0 (R2).
        return "[ \(debt?.unprocessedCount ?? 0) to read ]"
    case .hungry:
        let count = debt?.unprocessedCount ?? 0
        guard count > 0 else { return "[ overdue — hasn't consolidated in a while ]" }
        return "[ \(count) episode\(count == 1 ? "" : "s") behind — overdue ]"
    case .error:
        return "[ last cycle failed ]"
    }
}

/// Semantic color per mood, drawn entirely from `CicadaTheme` — no new
/// palette. Deliberately calm: `hungry` (the worst backlog state) tops out at
/// `.warning`, never `.danger` — a backlog is information, not an alarm
/// (UX principle 4: "non-intrusive nudging"). `error` is the one state
/// allowed `.danger` — a failed cycle is an alarm, a backlog is not (G107, R9).
func sleepDebtBracketColor(_ state: BookwormState) -> Color {
    switch state {
    case .awake: CicadaTheme.textTertiary
    case .sleeping, .digesting: CicadaTheme.accent
    case .happy: CicadaTheme.success
    case .curious: CicadaTheme.textSecondary
    case .reading: CicadaTheme.textSecondary
    case .hungry: CicadaTheme.warning
    case .error: CicadaTheme.danger
    }
}
