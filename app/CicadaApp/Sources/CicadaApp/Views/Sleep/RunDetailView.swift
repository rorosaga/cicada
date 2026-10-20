import SwiftUI

// MARK: - Past nights, one row per run (Sleep page v5, A8)

/// One Past nights item: a plain cycle's commit, or a run that read in batches folded into one row. A run's numbers
/// come from the server's `run` summary on its entries (critic M4) — never summed from the visible page of history,
/// which one long run can fill. An entry with a `drainId` but no `run` (telemetry off, an older backend) stays a
/// row of its own, as before.
enum PastNightItem: Identifiable, Equatable {
    case cycle(SleepHistoryEntry)
    case run(SleepRunRef, [SleepHistoryEntry])

    var id: String {
        switch self {
        case .cycle(let entry): entry.commitHash
        case .run(let ref, _): "run:\(ref.id)"
        }
    }

    static func group(_ entries: [SleepHistoryEntry]) -> [PastNightItem] {
        var items: [PastNightItem] = []
        var position: [String: Int] = [:]
        for entry in entries {
            guard let drainId = entry.drainId, let ref = entry.run, ref.id == drainId else {
                items.append(.cycle(entry))
                continue
            }
            if let at = position[drainId], case .run(let first, var members) = items[at] {
                members.append(entry)
                items[at] = .run(first, members)
            } else {
                position[drainId] = items.count
                items.append(.run(ref, [entry]))
            }
        }
        return items
    }
}

/// Pure words for a run's row and its opened detail, so `SleepV5RunDetailTests` holds them.
enum RunPresentation {
    static func duration(_ ms: Int?) -> String? {
        guard let ms, ms > 0 else { return nil }
        return SleepHistoryPresentation.durationText(ms: ms)
    }

    /// "286 conversations · 12 batches · 1 pause".
    static func summary(_ ref: SleepRunRef, locale: Locale = .autoupdatingCurrent) -> String {
        Copy.SleepV5.groupSummary(filed: ref.filed, batches: ref.batches, pauses: ref.pauses, locale)
    }

    /// "Reading all · 286 conversations · 12 batches · 1 pause".
    static func title(_ ref: SleepRunRef, locale: Locale = .autoupdatingCurrent) -> String {
        [Copy.SleepV5.readingAll, summary(ref, locale: locale)].joined(separator: " · ")
    }

    /// "Read for 2 h 14 m, paused 4 h 37 m. 1 conversation could not be read."
    static func times(_ ref: SleepRunRef, locale: Locale = .autoupdatingCurrent) -> String? {
        Copy.SleepV5.groupTimes(readFor: duration(ref.readMs), pausedFor: ref.pauses > 0 ? duration(ref.pausedMs) : nil,
                                parked: ref.parked, locale)
    }

    /// "Missed 3:00 AM — caught up at 8:12 AM" for a scheduled run that stood in for a time the Mac slept or was off
    /// through (owner 2026-10-19); `nil` for every other run. The missed time carries its day when it is not the
    /// run's own day (a 03:00 caught up after the next midnight).
    static func catchUp(_ ref: SleepRunRef, timeZone: TimeZone = .current) -> String? {
        guard ref.startedBy == "schedule", let missed = ref.catchUpFor, let start = ref.startedAt else { return nil }
        let at = SleepHistoryPresentation.timeText(start, timeZone: timeZone)
        var missedText = SleepHistoryPresentation.timeText(missed, timeZone: timeZone)
        guard missedText != "—", at != "—" else { return nil }
        let day = SleepHistoryPresentation.dateText(missed, timeZone: timeZone)
        if day != SleepHistoryPresentation.dateText(start, timeZone: timeZone) { missedText = "\(day), \(missedText)" }
        return Copy.SleepV5.catchUpLine(missed: missedText, at: at, failed: ref.state == "failed")
    }

    /// The batches table's first column: "Batch 5 · 9 filed · 16 not filed".
    static func batchLine(_ batch: SleepRunDetail.Batch, locale: Locale = .autoupdatingCurrent) -> String {
        Copy.SleepV5.batchRow(batch.index, filed: batch.filed, notFiled: batch.notFiled, locale)
    }

    /// "Paused 11:04 AM to 3:41 PM · to leave room in your plan".
    static func pauseLine(_ pause: SleepRunDetail.Pause, timeZone: TimeZone = .current) -> String {
        let from = SleepHistoryPresentation.timeText(pause.startedAt, timeZone: timeZone)
        let to = pause.endedAt.map { SleepHistoryPresentation.timeText($0, timeZone: timeZone) }
        return Copy.SleepV5.pauseRow(from: from, to: to, reason: pause.reason)
    }
}

/// A run's row in Past nights: its day and start, "Reading all", the run's own numbers, and a chevron.
struct PastRunRow: View {
    let ref: SleepRunRef
    let newest: SleepHistoryEntry
    let isExpanded: Bool
    /// Say it once — the day only on the first row of that day (`PastNightsLayout`).
    var showsDate = true
    let onToggle: () -> Void
    @State private var hovering = false

    var body: some View {
        let start = ref.startedAt ?? newest.date
        Button(action: onToggle) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                Text(showsDate ? SleepHistoryPresentation.dateText(start) : "")
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(48), alignment: .leading)
                Text(SleepHistoryPresentation.timeText(start))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(width: CicadaTheme.scaled(60), alignment: .leading)
                VStack(alignment: .leading, spacing: 1) {
                    Text(RunPresentation.title(ref))
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    if let caughtUp = RunPresentation.catchUp(ref) {
                        // Owner 2026-10-19 — a schedule's missed time, said in words on the run's own row (DR-48 rows).
                        Text(caughtUp)
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if let times = RunPresentation.times(ref) {
                        Text(times)
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                // The engine in words beside its mark, as a cycle row says it (review of #363): the readout leaves its
                // engine row to Past nights' newest row, which may be this one.
                if let pill = SleepHistoryPresentation.enginePill(newest) {
                    HStack(spacing: CicadaTheme.scaled(4)) {
                        if let engine = newest.engine {
                            EngineMark(engine: engine, size: CicadaTheme.scaled(12))
                        }
                        Text(pill)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                            .truncationMode(.tail)
                    }
                    .frame(maxWidth: CicadaTheme.scaled(250), alignment: .trailing)
                }
                DisclosureChevron(isOpen: isExpanded)
                    .frame(width: CicadaTheme.scaled(28))
            }
            .padding(.leading, CicadaTheme.scaled(10))
            .padding(.trailing, CicadaTheme.scaled(4))
            .padding(.vertical, CicadaTheme.scaled(6))
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                .fill(hovering ? CicadaTheme.bgHover : Color.clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityElement(children: .combine)
        .accessibilityLabel([Copy.SleepV5.readingAll, RunPresentation.summary(ref), RunPresentation.catchUp(ref),
                             RunPresentation.times(ref)]
            .compactMap { $0 }.joined(separator: ", "))
    }
}

/// A run opened in Past nights (A8): the models it called and what it cost (in `CycleUsageText`'s words, each with
/// its basis), the pages it touched, and the batches with the pauses between them. Ids, counts and enums only; a
/// model's name is the ledger's own — the person's engine — and which stages it served is data, never copy.
struct RunDetailBlock: View {
    let detail: SleepRunDetail?
    var onSelectEntity: ((String) -> Void)?
    /// The graph's names, so a touched page reads as its name and never as its id (DR-54); optional, so a preview
    /// or a test without a Store still renders.
    @Environment(Store.self) private var store: Store?

    /// A touched page's label: the page's name when the graph holds it, else its id verbatim (never humanised).
    static func pageLabel(_ id: String, names: EntityNames) -> String { names.display(id) }

    var body: some View {
        if let detail {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                usage(detail)
                pages(detail)
                batches(detail)
            }
        } else {
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text(Copy.SleepV5.runLoading)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    @ViewBuilder
    private func usage(_ detail: SleepRunDetail) -> some View {
        let lines = CycleUsageText.detailLines(detail.usage)
        if lines.empty == nil, !lines.models.isEmpty || !lines.plan.isEmpty || lines.share != nil {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                if let share = lines.share {
                    // Owner 2026-10-16 — a plan run leads with how much of the plan it used, its basis in the line.
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
        } else if let empty = lines.empty {
            Text(empty)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    @ViewBuilder
    private func pages(_ detail: SleepRunDetail) -> some View {
        if let pages = detail.pages, pages.created > 0 || !pages.first.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                SectionLabel(Copy.SleepV5.pagesItTouched)
                FlowLayout(spacing: 6) {
                    let names = store?.entityNames ?? .empty
                    ForEach(pages.first.prefix(8), id: \.self) { id in
                        // The page's neutral pill (DR-44), never an accent label (DR-5); the id stays in `.help`.
                        Button { onSelectEntity?(id) } label: { Tag(text: Self.pageLabel(id, names: names)) }
                            .buttonStyle(.cicadaPlain)
                            .help(id)
                    }
                }
                Text(Copy.SleepV5.pagesSummary(created: pages.created, ownerTouched: pages.ownerTouched))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    @ViewBuilder
    private func batches(_ detail: SleepRunDetail) -> some View {
        if !detail.batches.isEmpty || !detail.pauses.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                SectionLabel(Copy.SleepV5.batchesTitle)
                ForEach(detail.batches) { batch in
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(RunPresentation.batchLine(batch))
                            .foregroundStyle(CicadaTheme.textSecondary)
                        Spacer(minLength: CicadaTheme.spacingSM)
                        if let took = RunPresentation.duration(batch.tookMs) {
                            Text(took).foregroundStyle(CicadaTheme.textTertiary)
                        }
                        Text(Copy.SleepV5.callsMade(batch.calls)).foregroundStyle(CicadaTheme.textTertiary)
                        ForEach(batch.windows) { w in
                            Text(CycleUsageText.windowShift(window: w.window, before: w.before, after: w.after))
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .lineLimit(1)
                }
                ForEach(Array(detail.pauses.enumerated()), id: \.offset) { _, pause in
                    Text(RunPresentation.pauseLine(pause))
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
    }
}
