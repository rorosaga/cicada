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
        let shift = "\(Copy.SleepUsage.window(window)) \(UsageFormat.percent(fraction: before)) → \(UsageFormat.percent(fraction: after))"
        // A window that rolled over mid-cycle reads lower after than before; say so rather than show a fall.
        return after < before ? "\(shift) · \(Copy.SleepUsage.windowRolledOver)" : shift
    }

    // MARK: One line per cycle (Past nights, Last cycle)

    /// The row's one line, or nil when a row has nothing to say: an inbox or decay commit never has
    /// a `sleep_run`, so it is never "not recorded". A cycle with no summary reads as not recorded.
    static func summaryLine(kind: String, summary: CycleUsageSummary?, locale: Locale = .autoupdatingCurrent) -> String? {
        guard kind == "sleep" else { return nil }
        guard let s = summary else { return Copy.SleepUsage.notRecorded }
        let source = Copy.SleepUsage.source(connection: s.connection, engine: s.engine)
        if isPlan(s), s.basis != nil {
            // Owner 2026-10-16 — a plan run leads with how much of the plan it used; its list-price equivalent is
            // in the help (`summaryHelp`), never the line. A real charge in the same run (continued on another
            // engine) still shows.
            let lead = shareLine(s.planShare, limit: 1, locale: locale)
                ?? s.plan.map { windowShift(window: $0.window, before: $0.before, after: $0.after) + " · "
                    + Copy.SleepUsage.planCoversAll }
                ?? Copy.SleepUsage.shareNotRead
            let charged = s.costUsd.map { Copy.SleepUsage.chargedTotal(UsageFormat.currency($0, locale: locale)) }
            return [source, lead, charged].compactMap { $0 }.joined(separator: " · ")
        }
        // The limit is said in the line itself: a plan's share covers all use of the plan.
        let plan = s.plan.map {
            windowShift(window: $0.window, before: $0.before, after: $0.after) + " · " + Copy.SleepUsage.planCoversAll
        }
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

    /// Past reads' "What it cost" for the latest finished cycle (a drain's whole run). A plan run leads with its
    /// share of the plan (`shareLine`, owner 2026-10-16), else its window's before → after, and no price; a real
    /// charge in the same run (a run continued on another engine) still shows.
    static func lastCycleLine(_ summary: CycleUsageSummary?, locale: Locale = .autoupdatingCurrent) -> String? {
        guard let s = summary else { return nil }
        if isPlan(s), s.basis == nil {
            // A plan run that called nothing used nothing to word: its plan, and a window if one was read.
            return [Copy.SleepUsage.source(connection: s.connection, engine: s.engine),
                    s.plan.map { windowShift(window: $0.window, before: $0.before, after: $0.after) + " · "
                        + Copy.SleepUsage.planCoversAll }]
                .compactMap { $0 }.joined(separator: " · ")
        }
        return summaryLine(kind: "sleep", summary: s, locale: locale)
    }

    /// The run spent a plan, not money: a plan connection or engine, or a plan window it moved.
    static func isPlan(_ s: CycleUsageSummary) -> Bool {
        ["claude-plan", "chatgpt-plan"].contains(s.connection ?? "") || ["claude-cli", "codex-cli"].contains(s.engine ?? "")
            || s.plan != nil
    }

    /// The run spent a plan (the opened-cycle form of `isPlan`).
    static func isPlan(_ u: CycleUsage) -> Bool {
        ["claude-plan", "chatgpt-plan"].contains(u.connection ?? "") || ["claude-cli", "codex-cli"].contains(u.engine ?? "")
            || u.plan != nil
    }

    /// `.help` for a row's line: on a plan run, every window's share with each basis in full and the list-price
    /// equivalent ("would have cost…"); a bare window shift carries the honest limit; nil otherwise.
    static func summaryHelp(_ summary: CycleUsageSummary?, locale: Locale = .autoupdatingCurrent) -> String? {
        guard let s = summary else { return nil }
        if isPlan(s), let help = shareHelp(s.planShare, equivUsd: s.equivCostUsd, locale: locale) { return help }
        return s.plan == nil ? nil : Copy.SleepUsage.planNote
    }

    // MARK: A plan run's share (owner 2026-10-16: "how much of the plan, instead of money")

    /// "about 3% of your weekly limit", "under 1% of the 5-hour window", "about 0.4% of your weekly limit" — nil
    /// for a share with no figure. Never "0%": below a tenth of a point an estimate reads "under 0.1%".
    static func shareFigure(_ s: CycleUsagePlanShare, locale: Locale = .autoupdatingCurrent) -> String? {
        let limit = Copy.SleepUsage.limit(s.window)
        switch s.basis {
        case "measured":
            guard let v = s.share, v > 0 else { return nil }
            return Copy.SleepUsage.about(UsageFormat.share(fraction: v, locale: locale), of: limit)
        case "under":
            guard let u = s.under, u > 0 else { return nil }
            return Copy.SleepUsage.under(UsageFormat.share(fraction: u, locale: locale), of: limit)
        case "estimated":
            guard let v = s.share, v >= 0 else { return nil }
            if v < 0.001 { return Copy.SleepUsage.under(UsageFormat.share(fraction: 0.001, locale: locale), of: limit) }
            return Copy.SleepUsage.about(UsageFormat.share(fraction: v, locale: locale), of: limit)
        default:
            return nil
        }
    }

    /// The share as one line: the first `limit` windows in the server's order (weekly first), then the basis
    /// in words — once when every figure shares it, else each figure's own. "measured" only when the reading
    /// moved; an unmoved reading says so; an estimate is never presented as a measurement.
    static func shareLine(_ shares: [CycleUsagePlanShare], limit: Int = 2, locale: Locale = .autoupdatingCurrent) -> String? {
        let shown = Array(shares.compactMap { s in shareFigure(s, locale: locale).map { (basisWord(s.basis), $0) } }
            .prefix(limit))
        guard let first = shown.first else { return nil }
        if shown.allSatisfy({ $0.0 == first.0 }) { return (shown.map(\.1) + [first.0]).joined(separator: " · ") }
        return shown.map { "\($0.1) (\($0.0))" }.joined(separator: " · ")
    }

    /// A share's basis in words: `measured` (the reading moved), `under` (it did not), `estimated`.
    static func basisWord(_ basis: String) -> String {
        switch basis {
        case "measured": Copy.SleepUsage.measured
        case "under": Copy.SleepUsage.unmoved
        default: Copy.SleepUsage.estimated
        }
    }

    /// The share's help: every window's figure, each basis that appears said in full, the plan's honest limit,
    /// and the list-price equivalent as the secondary figure. Nil when there is no share to explain.
    static func shareHelp(_ shares: [CycleUsagePlanShare], equivUsd: Double?, locale: Locale = .autoupdatingCurrent) -> String? {
        let figures = shares.compactMap { shareFigure($0, locale: locale) }
        guard !figures.isEmpty else { return nil }
        var notes = [figures.joined(separator: " · ").prefix(1).uppercased()
            + figures.joined(separator: " · ").dropFirst() + "."]
        let bases = Set(shares.map(\.basis))
        if bases.contains("measured") { notes.append(Copy.SleepUsage.measuredNote) }
        if bases.contains("measured") || bases.contains("under") { notes.append(Copy.SleepUsage.planNote) }
        if bases.contains("under") { notes.append(Copy.SleepUsage.underNote) }
        if bases.contains("estimated") {
            notes.append(Copy.SleepUsage.estimatedNote(samples: shares.compactMap(\.samples).max()))
            if shares.contains(where: { $0.basis == "estimated" && $0.under != nil }) {
                notes.append(Copy.SleepUsage.estimateCappedNote)
            }
        }
        if let line = equivLine(equivUsd, locale: locale) { notes.append(line + ".") }
        return notes.joined(separator: " ")
    }

    /// "Would have cost about $0.49 on an API key" — a plan run's list-price equivalent, the secondary figure.
    static func equivLine(_ equivUsd: Double?, locale: Locale = .autoupdatingCurrent) -> String? {
        guard let equivUsd else { return nil }
        let line = Copy.SleepUsage.wouldHaveCost(UsageFormat.currency(equivUsd, locale: locale))
        return line.prefix(1).uppercased() + line.dropFirst()
    }

    // MARK: An opened cycle (Details, Models)

    /// One `(engine, model)`: "claude-sonnet-5-5 · 14 calls · 1 failed · 182,340 tokens in · 9,120 tokens out
    /// · about $0.42 at list price". A plan call reports no tokens and says so; a figure that is unknown is
    /// left out, never zero.
    /// `priced: false` on a plan run: its list-price figure is the run's one secondary "would have cost" line.
    static func modelLine(_ m: CycleUsageModel, priced: Bool = true, locale: Locale = .autoupdatingCurrent) -> String {
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
        case "list" where !priced:
            break
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
    /// is "No model calls". A plan run (owner 2026-10-16) leads with `share` — how much of the plan it used, with
    /// its basis — and its dollars move to `equiv`, the secondary "would have cost" line; its models carry no
    /// price, and its total only a real charge.
    static func detailLines(_ u: CycleUsage?, kind: String = "sleep", locale: Locale = .autoupdatingCurrent)
        -> (models: [String], total: String?, plan: [(text: String, help: String)], empty: String?,
            share: (text: String, help: String)?, equiv: String?) {
        guard kind == "sleep" else { return ([], nil, [], nil, nil, nil) }
        guard let u, u.recorded else { return ([], nil, [], Copy.SleepUsage.notRecorded, nil, nil) }
        let plan = planRows(u)
        if u.models.isEmpty { return ([], nil, plan, plan.isEmpty ? Copy.SleepUsage.noCalls : nil, nil, nil) }
        guard isPlan(u) else {
            return (u.models.map { modelLine($0, locale: locale) }, totalLine(u, locale: locale), plan, nil, nil, nil)
        }
        let share = shareLine(u.planShare, locale: locale).map { line in
            (text: line, help: shareHelp(u.planShare, equivUsd: nil, locale: locale) ?? line)
        }
        let charged = u.totalCostUsd.map { "Total · " + Copy.SleepUsage.chargedTotal(UsageFormat.currency($0, locale: locale)) }
        return (u.models.map { modelLine($0, priced: false, locale: locale) }, charged, plan, nil, share,
                equivLine(u.totalEquivUsd, locale: locale))
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

    /// "Last cycle: $0.42 charged" — or, on a plan (owner 2026-10-16), "Last run: under 1% of your weekly limit ·
    /// reading unchanged" — from the candidate that says so, the one a cycle you start would use first. The second
    /// element is the help: the share's bases in full and the plan run's list-price equivalent ("would have cost…").
    static func lastCycle(_ candidates: [SleepEngineCandidate], preferring id: String?,
                          locale: Locale = .autoupdatingCurrent) -> (line: String, help: String?)? {
        let ordered = candidates.sorted { ($0.id == id ? 0 : 1) < ($1.id == id ? 0 : 1) }
        for candidate in ordered {
            guard let u = candidate.usage else { continue }
            if let shares = u.lastRunShare, let line = shareLine(shares, locale: locale) {
                return (Copy.SleepUsage.lastRun(line), shareHelp(shares, equivUsd: u.lastRunEquivUsd, locale: locale))
            }
            if let cost = u.lastCycleCostUsd {
                return (Copy.SleepUsage.lastCycle(UsageFormat.currency(cost, locale: locale)), nil)
            }
        }
        return nil
    }

    /// The menu's one line (`lastCycle`), without its help.
    static func lastCycleLine(_ candidates: [SleepEngineCandidate], preferring id: String?,
                              locale: Locale = .autoupdatingCurrent) -> String? {
        lastCycle(candidates, preferring: id, locale: locale)?.line
    }
}
