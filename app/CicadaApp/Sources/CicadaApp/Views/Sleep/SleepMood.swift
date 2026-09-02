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
func deriveSleepPageMood(
    status: SleepStatusResponse?,
    debt: SleepDebtView?,
    justFinishedAt: Date?,
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
    return .curious(count: debt.unprocessedCount)
}

// MARK: - Interim text presentation (G107 tracks real mascot art)

/// The mascot sprite (`BookwormView`) is a ~16×16 template-rendered menu-bar
/// glyph — blown up to page size it reads as a low-res smear, and template
/// mode is tinted uniformly, so it physically cannot show mood. Real art is
/// tracked separately (backlog G107); the interim is deliberately plain: one
/// monospaced, bracketed line of TEXT, no ASCII art, no emoji, no drawn
/// character. Reuses the SAME `BookwormState` `deriveSleepPageMood` produces
/// — only the rendering differs from the mascot everywhere else in the app.
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
    case .hungry: CicadaTheme.warning
    case .error: CicadaTheme.danger
    }
}
