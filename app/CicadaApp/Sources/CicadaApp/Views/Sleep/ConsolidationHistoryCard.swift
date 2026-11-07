import SwiftUI

/// Pure presentation for one `SleepHistoryEntry` (G125 R4/R5) — how long a
/// cycle took, its one-line summary, and its git-short date, each a static
/// function so wording is asserted in `SleepHistoryPresentationTests`
/// without standing up `ConsolidationHistoryCard` itself.
enum SleepHistoryPresentation {
    /// `nil` (no `sleep_run` ledger row joined — telemetry off, or the row
    /// predates this cycle) reads as an honest "—", never a guess (R5).
    /// Below a minute: whole seconds. Below an hour: minutes + the leftover
    /// seconds, both floored (so "4 m 12 s" means exactly that, not rounded).
    /// An hour or more: hours + minutes, both taken from the ROUNDED total
    /// minute count — at that scale seconds are noise, and a floor would
    /// under-report a cycle that ran 61.7 minutes as "1 h 1 m" instead of
    /// "1 h 2 m".
    static func durationText(ms: Int?) -> String {
        guard let ms, ms >= 0 else { return "—" }
        let totalSeconds = ms / 1000
        if totalSeconds < 60 {
            return "\(totalSeconds) s"
        }
        if totalSeconds < 3600 {
            let minutes = totalSeconds / 60
            let seconds = totalSeconds % 60
            return seconds > 0 ? "\(minutes) m \(seconds) s" : "\(minutes) m"
        }
        let totalMinutes = Int((Double(ms) / 60_000).rounded())
        let hours = totalMinutes / 60
        let remMinutes = totalMinutes % 60
        return remMinutes > 0 ? "\(hours) h \(remMinutes) m" : "\(hours) h"
    }

    /// A decay-only commit (the G85 split's `Sleep cycle <date> (decay)`) is
    /// pure arithmetic over entities never mentioned — no extraction ran, so
    /// "+N new · M updated" would credit an LLM for work it never did. Every
    /// other kind counts entities the manifest actually attributes to
    /// `sleep/extraction`/`sleep/promotion`/etc.
    ///
    /// G125 v3 Task 7 (budget row #18): a real cycle now leads with what it
    /// READ — "2 episodes → +12 new · 8 updated" answers "where did those
    /// entities come from" in the same glance. The prefix is drawn **only when
    /// there is a count** (P18): `episodes` decodes to its default zero on an
    /// older backend, a cached snapshot or an inbox commit, and "0 episodes →"
    /// would be a fabricated zero standing in for an unknown.
    static func summaryLine(_ e: SleepHistoryEntry) -> String {
        if e.kind == "decay" { return "decay pass" }
        guard let read = readPhrase(e) else { return writtenPhrase(e) }
        return "\(read) → \(writtenPhrase(e))"
    }

    /// What the cycle WROTE. Always present — a real cycle that created and
    /// updated nothing still says so, since `0` here is a measurement, not the
    /// absent count `episodes` can be.
    private static func writtenPhrase(_ e: SleepHistoryEntry) -> String {
        "+\(e.entitiesCreated) new · \(e.entitiesUpdated) updated"
    }

    /// What the cycle READ, or `nil` when there is no count to state (P18):
    /// `episodes` decodes to its default zero on an older backend, a cached
    /// snapshot or an inbox commit, and "0 episodes →" would be a fabricated
    /// zero standing in for an unknown.
    private static func readPhrase(_ e: SleepHistoryEntry) -> String? {
        guard e.episodes > 0 else { return nil }
        return "\(e.episodes) conversation\(e.episodes == 1 ? "" : "s")"
    }

    /// The headline as the LINES it should be drawn on — the round-2 live
    /// check's second finding.
    ///
    /// The row's headline was one `.lineLimit(1)` line, and in the right
    /// column (about a third of the page above 1000 pt, and no wider at 1.4×
    /// zoom while the text grows with it) it truncated mid-word:
    /// "18 episodes → +5 new · 929 updat…". The counts are the whole content
    /// of the row, so an ellipsis eats exactly what it exists to report
    /// (R-A11), and a truncated number is a worse dash than `—` (R-A14).
    ///
    /// The compact form breaks at the arrow — what the cycle read on the first
    /// line, what it wrote on the second — rather than letting the wrap land
    /// wherever the glyphs happen to run out. The arrow stays on the first
    /// line as the "continues below" cue.
    ///
    /// Two rows have nothing to break and get one line at any width: a decay
    /// commit ("decay pass" — arithmetic, not extraction) and a cycle with no
    /// episode count, whose whole headline is already the written half. A
    /// caller that draws these never gets an empty second line.
    static func headlineLines(_ e: SleepHistoryEntry, compact: Bool) -> [String] {
        guard compact, e.kind != "decay", let read = readPhrase(e) else { return [summaryLine(e)] }
        return ["\(read) →", writtenPhrase(e)]
    }

    /// The row's badge slot (G125 v3 Task 7): which engine ran the cycle, and
    /// who authored its writes — both already parsed server-side, neither
    /// invented.
    ///
    /// An absent engine drops the pill's LEFT half rather than defaulting to
    /// one: `Cicada-Engine:` is "omitted entirely rather than guessed" when no
    /// LLM ran (CLAUDE.md), which is exactly the case for a decay or
    /// state-snapshot commit. Only the first author is named — the expanded
    /// detail below already lists every one of them, and a badge is one fact
    /// wide. Both halves missing → no pill at all, never an empty badge.
    static func enginePill(_ e: SleepHistoryEntry) -> String? {
        let parts = [e.engine.map(Copy.engineLabel), e.authors.first.map(authorLabel)].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// `date` arrives as git's `--date=iso-strict` (`2026-09-05T21:41:00+00:00`)
    /// since R-A11, and as the older `--date=short` (`yyyy-MM-dd`) from any
    /// snapshot cached before that. git renders BOTH in the COMMIT's own
    /// zone — the previous comment here claimed `--date=short` was "anchored
    /// UTC" and the formatter pinned UTC, which would shift the displayed
    /// hour the moment a time existed. The offset is parsed for real and the
    /// result displayed in the reader's zone; `timeZone` is injectable so the
    /// tests never depend on the runner's locale.
    static func parsed(_ iso: String) -> Date? {
        let withOffset = ISO8601DateFormatter()
        withOffset.formatOptions = [.withInternetDateTime]
        if let d = withOffset.date(from: iso) { return d }
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        dayOnly.locale = Locale(identifier: "en_US_POSIX")
        return dayOnly.date(from: String(iso.prefix(10)))
    }

    /// A raw string that fails to parse is shown as-is rather than hidden
    /// behind a blank field. A date-only value carries no zone of its own, so
    /// it keeps the UTC anchor it was parsed with — re-projecting a bare day
    /// into the reader's zone is what would slide it to the previous day.
    static func dateText(_ iso: String, timeZone: TimeZone = .current) -> String {
        guard let date = parsed(iso) else { return iso }
        let f = DateFormatter()
        f.dateFormat = "MMM d"
        f.timeZone = iso.contains("T") ? timeZone : TimeZone(identifier: "UTC")
        f.locale = Locale(identifier: "en_US_POSIX")
        return f.string(from: date)
    }

    /// `—`, never a fabricated midnight, for a value that carries no time
    /// (R-A14): a legacy `--date=short` row genuinely does not know the hour.
    static func timeText(_ iso: String, timeZone: TimeZone = .current) -> String {
        guard iso.contains("T"), let date = parsed(iso) else { return "—" }
        let f = DateFormatter()
        f.dateFormat = "h:mm a"
        f.timeZone = timeZone
        f.locale = Locale(identifier: "en_US_POSIX")
        return f.string(from: date)
    }

    /// `authors` are model ids ("gpt-5.4-mini") except the literal `user` —
    /// never shown as the raw literal, since a person reads it as "you", not
    /// as a model that ran.
    static func authorLabel(_ author: String) -> String {
        author == "user" ? "you" : author
    }
}

/// "PAST NIGHTS" (G125 R4/R12) — the Sleep page's history, newest first, one card per consolidation (owner
/// 2026-10-26: "Just say: this consolidation ran at this time and it included this thing, with a dropdown"). A run that
/// read in batches is one card (`PastNightItem.group`), a plain cycle one card; a decay pass and an inbox resolution
/// are not consolidations and get none (`RunCardModel.cards`). Opening a card asks the caller (`onToggle`) to flip its
/// open state and fetch its items, and its run's or commit's detail — this view never fetches on its own.
struct ConsolidationHistoryCard: View {
    let entries: [SleepHistoryEntry]
    let details: [String: SleepCycleDetail]
    /// The open plain cycle (its commit) and the open run (its id) — one card is open at a time.
    let expanded: String?
    var expandedRun: String? = nil
    var runDetails: [String: SleepRunDetail] = [:]
    var items: [SleepConsolidatedKey: SleepConsolidated] = [:]
    var itemsFailed: Set<SleepConsolidatedKey> = []
    let onToggle: (RunCardModel) -> Void
    var onSelectEntity: ((String) -> Void)?
    /// A card on screen asks for its items once (`SleepViewModel.loadConsolidated`): they carry its question count.
    var onLoadItems: (SleepConsolidatedKey) -> Void = { _ in }

    var body: some View {
        let cards = RunCardModel.cards(entries, details: runDetails, items: items)
        // Say it once (owner 2026-10-19): what no card recorded is said on the section's label, not on every card.
        let layout = PastNightsLayout(entries)
        SleepDetailsSection(title: layout.title) {
            if cards.isEmpty {
                Text("Nothing consolidated yet.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.scaled(10))
                    .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            } else {
                LazyVStack(alignment: .leading, spacing: CicadaTheme.scaled(10)) {
                    ForEach(cards) { card in
                        RunCardView(card: card, isOpen: isOpen(card), items: items[card.key],
                                    itemsFailed: itemsFailed.contains(card.key), runDetail: runDetail(card),
                                    cycleDetail: details[card.members[0].commitHash],
                                    showsUsage: !layout.usageSaidOnce,
                                    onToggle: { onToggle(card) }, onSelectEntity: onSelectEntity,
                                    onAppear: { if items[card.key] == nil { onLoadItems(card.key) } })
                    }
                }
            }
        }
    }

    private func isOpen(_ card: RunCardModel) -> Bool {
        switch card.key {
        case .run(let id): expandedRun == id
        case .commit(let hash): expanded == hash
        }
    }

    private func runDetail(_ card: RunCardModel) -> SleepRunDetail? {
        if case .run(let id) = card.key { return runDetails[id] }
        return nil
    }

    /// Everything a cycle's row draws, in words — kept for the cycle summaries other surfaces read.
    static func rowAccessibilityLabel(_ entry: SleepHistoryEntry) -> String {
        var parts = [SleepHistoryPresentation.dateText(entry.date)]
        let time = SleepHistoryPresentation.timeText(entry.date)
        if time != "—" { parts.append(time) }
        parts.append(SleepHistoryPresentation.summaryLine(entry))
        if let pill = SleepHistoryPresentation.enginePill(entry) { parts.append(pill) }
        return parts.joined(separator: ", ")
    }
}

/// A plain cycle's models and what it cost, each with its basis (ruling 12; 2026-09-28) — the run card's details for
/// a cycle that was not a run. A plan run leads with how much of the plan it used (owner 2026-10-16); the total, then
/// the list-price equivalent under it; a plan's window before → after with the honest limit.
struct CycleUsageBlock: View {
    let detail: SleepCycleDetail?

    var body: some View {
        if let d = detail {
            content(CycleUsageText.detailLines(d.usage, kind: d.kind))
        } else {
            Text(Copy.SleepV5.runLoading)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    @ViewBuilder
    private func content(_ lines: (models: [String], total: String?, plan: [(text: String, help: String)], empty: String?,
                                   share: (text: String, help: String)?, equiv: String?)) -> some View {
        if let empty = lines.empty {
            Text(empty)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        } else if !lines.models.isEmpty || !lines.plan.isEmpty || lines.share != nil {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                if let share = lines.share {
                    Text(share.text)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                        .help(share.help)
                        .padding(.bottom, CicadaTheme.scaled(2))
                }
                SectionLabel(Copy.SleepUsage.modelsTitle)
                ForEach(lines.models, id: \.self) { line in
                    Text(line)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let total = lines.total {
                    Text(total)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textPrimary)
                }
                if let equiv = lines.equiv {
                    Text(equiv)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                ForEach(Array(lines.plan.enumerated()), id: \.offset) { _, row in
                    Text(row.text)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .help(row.help)
                }
                if !lines.plan.isEmpty {
                    Text(Copy.SleepUsage.planNote)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

/// Say it once (owner 2026-10-19) — what Past nights draws once instead of on every row: the day on its first row
/// only (the rows under it are the same day), and, when no row recorded its usage or its time, one note on the
/// section's label ("Past nights · usage and time not recorded") instead of "Usage not recorded" and "—" on each.
/// Pure, so the rule is tested without a view.
struct PastNightsLayout {
    let items: [PastNightItem]
    /// The items that draw their day: the first of each day, newest first.
    let datedIds: Set<String>
    let usageSaidOnce: Bool
    let durationSaidOnce: Bool

    init(_ entries: [SleepHistoryEntry]) {
        items = PastNightItem.group(entries)
        var dated: Set<String> = []
        var lastDay: String?
        for item in items {
            let iso: String
            switch item {
            case .cycle(let entry): iso = entry.date
            case .run(let ref, let members): iso = ref.startedAt ?? members[0].date
            }
            let day = SleepHistoryPresentation.dateText(iso)
            if day != lastDay { dated.insert(item.id) }
            lastDay = day
        }
        datedIds = dated
        // Over EVERY cycle row the section can draw — a run's batches included, which draw these lines when the run is
        // open (review of #363): one batch with usage means each row says its own, so no row's figure is ever hidden
        // under a label that says it was not recorded (ruling 12).
        let cycles = entries.filter { $0.kind == "sleep" }
        usageSaidOnce = cycles.count > 1 && cycles.allSatisfy { $0.usageSummary == nil }
        durationSaidOnce = cycles.count > 1 && cycles.allSatisfy { $0.durationMs == nil }
    }

    var title: String {
        switch (usageSaidOnce, durationSaidOnce) {
        case (true, true): Eyebrow.text(Copy.SleepUsage.pastNights, Copy.SleepUsage.usageAndTimeNotRecorded)
        case (true, false): Eyebrow.text(Copy.SleepUsage.pastNights, Copy.SleepUsage.usageNotRecordedNote)
        case (false, true): Eyebrow.text(Copy.SleepUsage.pastNights, Copy.SleepUsage.timeNotRecordedNote)
        case (false, false): Copy.SleepUsage.pastNights
        }
    }
}
