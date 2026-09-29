import Foundation

/// Every sentence the Sleep page's Details and engine menu say about cost, as pure functions of the
/// wire values (2026-09-28 ruling; `CycleUsageTextTests`). Strings and figures are built here, in
/// `Copy` and `UsageFormat`, so a `%` or a `$` never sits on a `Text(` line under `Views/Sleep`
/// (`SleepNumbersLintTests`). Relative words are derived from an absolute time at read and never
/// stored (DR-58); the absolute time rides in `.help`.
enum CycleUsageText {
    // MARK: A plan window

    /// "5-hour window 12% → 18%".
    static func windowShift(window: String, before: Double, after: Double) -> String {
        "\(Copy.SleepUsage.window(window)) \(UsageFormat.percent(fraction: before)) → \(UsageFormat.percent(fraction: after))"
    }

    // MARK: One line per cycle (Past nights, Last cycle)

    /// The row's one line, or nil when a row has nothing to say: an inbox or decay commit never has
    /// a `sleep_run`, so it is never "not recorded". A cycle with no summary reads as not recorded.
    static func summaryLine(kind: String, summary: CycleUsageSummary?, locale: Locale = .autoupdatingCurrent) -> String? {
        guard kind == "sleep" else { return nil }
        guard let s = summary else { return Copy.SleepUsage.notRecorded }
        let source = Copy.SleepUsage.source(connection: s.connection, engine: s.engine)
        let plan = s.plan.map { windowShift(window: $0.window, before: $0.before, after: $0.after) }
        let charged = s.costUsd.map { UsageFormat.currency($0, locale: locale) }
        let list = s.equivCostUsd.map { UsageFormat.currency($0, locale: locale) }
        switch s.basis {
        case "charged":
            guard let charged else { return Copy.SleepUsage.notRecorded }
            return Copy.SleepUsage.charged(charged, on: source)
        case "list":
            let cost = list.map { Copy.SleepUsage.atListPrice($0) }
            if let plan { return [source, plan, cost].compactMap { $0 }.joined(separator: " · ") }
            guard let cost else { return source ?? Copy.SleepUsage.notRecorded }
            return [cost.prefix(1).uppercased() + cost.dropFirst(), source].compactMap { $0 }.joined(separator: " · ")
        case "plan":
            return [source, plan].compactMap { $0 }.joined(separator: " · ")
        case "free":
            return Copy.SleepUsage.ranLocally
        case "mixed":
            let parts = [charged.map { Copy.SleepUsage.chargedTotal($0) }, list.map { Copy.SleepUsage.atListPrice($0) }, plan]
            return parts.compactMap { $0 }.joined(separator: " · ")
        default:
            return Copy.SleepUsage.noCalls
        }
    }

    /// `.help` for a line that carries a plan window — the honest limit.
    static func summaryHelp(_ summary: CycleUsageSummary?) -> String? {
        summary?.plan == nil ? nil : Copy.SleepUsage.planNote
    }

    // MARK: An opened cycle (Details, Models)

    /// One `(engine, model)`: "claude-sonnet-5-5 · 14 calls · 1 failed · 182,340 tokens in · 9,120 tokens out
    /// · about $0.42 at list price". A plan call reports no tokens and says so; a figure that is unknown is
    /// left out, never zero.
    static func modelLine(_ m: CycleUsageModel, locale: Locale = .autoupdatingCurrent) -> String {
        var parts = [m.model ?? Copy.SleepUsage.source(connection: nil, engine: m.engine) ?? "Model",
                     Copy.SleepUsage.calls(m.calls, locale: locale)]
        if m.failedCalls > 0 { parts.append(Copy.SleepUsage.failed(m.failedCalls, locale: locale)) }
        if m.inputTokens == 0, m.outputTokens == 0 {
            parts.append(Copy.SleepUsage.tokensNotReported)
        } else {
            parts.append(Copy.SleepUsage.tokensIn(m.inputTokens, locale: locale))
            parts.append(Copy.SleepUsage.tokensOut(m.outputTokens, locale: locale))
        }
        switch m.basis {
        case "charged":
            if let c = m.costUsd {
                parts.append(Copy.SleepUsage.chargedTotal(UsageFormat.currency(c, locale: locale)))
            }
        case "list":
            if let e = m.equivCostUsd {
                parts.append(Copy.SleepUsage.atListPrice(UsageFormat.currency(e, locale: locale)))
            }
        case "free":
            parts.append(Copy.SleepUsage.ranLocally)
        default: break
        }
        return parts.joined(separator: " · ")
    }

    /// "Total · $0.42 charged" / "Total · about $0.42 at list price"; nil when no money figure exists.
    static func totalLine(_ u: CycleUsage, locale: Locale = .autoupdatingCurrent) -> String? {
        let charged = u.totalCostUsd.map { Copy.SleepUsage.chargedTotal(UsageFormat.currency($0, locale: locale)) }
        let list = u.totalEquivUsd.map { Copy.SleepUsage.atListPrice(UsageFormat.currency($0, locale: locale)) }
        let figures = [charged, list].compactMap { $0 }
        return figures.isEmpty ? nil : "Total · " + figures.joined(separator: " · ")
    }

    /// One row per plan window: "Claude plan · 5-hour window 12% → 18%". The second element is the
    /// row's help: the honest limit, plus why a Claude "before" is not a pre-cycle reading.
    static func planRows(_ u: CycleUsage) -> [(text: String, help: String)] {
        guard let plan = u.plan else { return [] }
        let source = Copy.SleepUsage.source(connection: plan.connection ?? u.connection, engine: u.engine)
        return plan.windows.map { w in
            let text = [source, windowShift(window: w.window, before: w.before, after: w.after)]
                .compactMap { $0 }.joined(separator: " · ")
            let help = w.beforeIsFirstSeen ? Copy.SleepUsage.planNote + " " + Copy.SleepUsage.firstSeenNote
                : Copy.SleepUsage.planNote
            return (text, help)
        }
    }

    /// The whole opened-cycle block. `nil` usage is "not recorded"; a recorded cycle with nothing called
    /// is "No model calls".
    static func detailLines(_ u: CycleUsage?, kind: String = "sleep", locale: Locale = .autoupdatingCurrent)
        -> (models: [String], total: String?, plan: [(text: String, help: String)], empty: String?) {
        guard kind == "sleep" else { return ([], nil, [], nil) }
        guard let u, u.recorded else { return ([], nil, [], Copy.SleepUsage.notRecorded) }
        let plan = planRows(u)
        if u.models.isEmpty { return ([], nil, plan, plan.isEmpty ? Copy.SleepUsage.noCalls : nil) }
        return (u.models.map { modelLine($0, locale: locale) }, totalLine(u, locale: locale), plan, nil)
    }

    // MARK: The engine menu

    private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func parseAsOf(_ s: String?) -> Date? {
        guard let s else { return nil }
        return iso.date(from: s) ?? isoFractional.date(from: s)
    }

    /// A reading older than this is said to be "as of" its day instead of presented as current.
    static let staleAfter: TimeInterval = 60 * 60

    /// "3:40 PM" within a day, "Fri 3:40 PM" beyond it — derived from the absolute time at read (DR-58).
    static func resetText(_ resetsAt: Int, now: Date, locale: Locale, timeZone: TimeZone) -> String {
        let date = Date(timeIntervalSince1970: TimeInterval(resetsAt))
        let f = DateFormatter()
        f.locale = locale
        f.timeZone = timeZone
        f.setLocalizedDateFormatFromTemplate(date.timeIntervalSince(now) > 24 * 3600 ? "EEE jmm" : "jmm")
        return f.string(from: date)
    }

    static func relative(_ date: Date, now: Date, locale: Locale) -> String {
        let f = RelativeDateTimeFormatter()
        f.locale = locale
        f.dateTimeStyle = .named
        f.unitsStyle = .full
        return f.localizedString(for: date, relativeTo: now)
    }

    /// A plan row's caption in the engine menu: "18% of 5-hour window · resets 3:40 PM"; the busiest
    /// window of the ChatGPT plan reads "31% used · resets Fri 3:40 PM". A reading over an hour old
    /// is "as of yesterday" instead of a resets time (the absolute one is in `help`), and a window
    /// that has reset since says so. Nil when the usage has no figure to state.
    static func planCaption(_ u: SleepEngineUsage, now: Date = Date(), locale: Locale = .autoupdatingCurrent,
                            timeZone: TimeZone = .current) -> (caption: String, help: String)? {
        guard u.kind == "plan-window", let used = u.usedFraction else { return nil }
        let share = UsageFormat.percent(fraction: used)
        let window = u.window ?? "fullest"
        let head = window == "fullest" ? "\(share) used" : "\(share) of \(Copy.SleepUsage.window(window))"
        let asOf = parseAsOf(u.asOf)
        let resetDate = u.resetsAt.map { Date(timeIntervalSince1970: TimeInterval($0)) }
        var help = head
        if let resetDate { help += " · " + Copy.SleepUsage.resets(resetText(u.resetsAt ?? 0, now: now, locale: locale, timeZone: timeZone)) }
        if let asOf { help += " · " + Copy.SleepUsage.asOf(relative(asOf, now: now, locale: locale)) }
        if let resetDate, resetDate <= now { return (Copy.SleepUsage.windowReset, help) }
        if let asOf, now.timeIntervalSince(asOf) > staleAfter {
            return ("\(head) · " + Copy.SleepUsage.asOf(relative(asOf, now: now, locale: locale)), help)
        }
        if resetDate != nil, let at = u.resetsAt {
            return ("\(head) · " + Copy.SleepUsage.resets(resetText(at, now: now, locale: locale, timeZone: timeZone)), help)
        }
        return (head, help)
    }

    /// A key card's caption: "$0.40 in · $1.60 out per million tokens".
    static func priceCaption(_ u: SleepEngineUsage, locale: Locale = .autoupdatingCurrent) -> String? {
        guard u.kind == "list-price", let i = u.inputPerMillionUsd, let o = u.outputPerMillionUsd else { return nil }
        return "\(UsageFormat.currency(i, locale: locale)) in · \(UsageFormat.currency(o, locale: locale)) out per million tokens"
    }

    /// A model picker entry's price: "$0.40 / $1.60".
    static func modelPrice(_ p: SleepEngineModelPrice?, locale: Locale = .autoupdatingCurrent) -> String? {
        guard let p, let i = p.inputPerMillionUsd, let o = p.outputPerMillionUsd else { return nil }
        return "\(UsageFormat.currency(i, locale: locale)) / \(UsageFormat.currency(o, locale: locale))"
    }

    /// The card's caption and help in the engine menu, or nil to keep the existing caption.
    static func caption(for candidate: SleepEngineCandidate, now: Date = Date(), locale: Locale = .autoupdatingCurrent,
                        timeZone: TimeZone = .current) -> (caption: String, help: String)? {
        guard let u = candidate.usage else { return nil }
        if let plan = planCaption(u, now: now, locale: locale, timeZone: timeZone) { return plan }
        if let price = priceCaption(u, locale: locale) { return (price, price) }
        return nil
    }

    /// "Last cycle: $0.42 charged" from the candidate that says so, the one a cycle you start would
    /// use first.
    static func lastCycleLine(_ candidates: [SleepEngineCandidate], preferring id: String?,
                              locale: Locale = .autoupdatingCurrent) -> String? {
        let ordered = candidates.sorted { ($0.id == id ? 0 : 1) < ($1.id == id ? 0 : 1) }
        guard let cost = ordered.lazy.compactMap({ $0.usage?.lastCycleCostUsd }).first else { return nil }
        return Copy.SleepUsage.lastCycle(UsageFormat.currency(cost, locale: locale))
    }
}
