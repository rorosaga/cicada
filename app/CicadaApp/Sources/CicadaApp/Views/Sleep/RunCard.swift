import AppKit
import SwiftUI

// MARK: - The run card's words (owner 2026-10-26)

/// One consolidation as Past nights shows it (owner 2026-10-26: "this consolidation ran at this time and it included
/// this thing, with a dropdown … In the consolidation card you can see exactly how much of your plan it used, what model
/// it used"): when it ran and who started it, one line of what it included, the engine and models, the plan usage or
/// cost with its basis (ruling 12 — `CycleUsageText`'s words), how long it read, and how it ended. Pure, so
/// `RunCardModelTests` holds every word without a view.
///
/// A run that read in batches is one card, its figures the server's whole-run numbers (`SleepRunRef`), never summed
/// from the visible page of history; a plain cycle is one card from its own commit. A decay pass or an inbox
/// resolution is not a consolidation, so it gets no card (it stays in git and the page's own history).
struct RunCardModel: Equatable, Identifiable {
    enum Outcome: Equatable {
        case finished, reading, pausedPlanLimit, pausedReserve, paused, stopped, failed

        var words: String {
            switch self {
            case .finished: Copy.RunCard.finished
            case .reading: Copy.RunCard.reading
            case .pausedPlanLimit: Copy.RunCard.pausedPlanLimit
            case .pausedReserve: Copy.RunCard.pausedReserve
            case .paused: Copy.RunCard.paused
            case .stopped: Copy.RunCard.stopped
            case .failed: Copy.RunCard.failed
            }
        }

        /// A run the person may want to act on (continue, see why) wears the warning glyph; nothing else is coloured.
        var needsYou: Bool { self == .failed || self == .pausedPlanLimit || self == .pausedReserve || self == .paused }
    }

    let id: String
    let key: SleepConsolidatedKey
    /// When it ran (aware ISO): a run's start, else the commit's date.
    let ranAt: String
    /// "You started it" / "On schedule"; `nil` when not recorded (a plain cycle).
    let starter: String?
    /// "Missed 3:00 AM — caught up at 8:12 AM" for a scheduled catch-up.
    let catchUp: String?
    let summary: String
    let engine: String?
    let models: [String]
    let usage: CycleUsageSummary?
    let durationMs: Int?
    let outcome: Outcome
    /// The run's batch commits (a plain cycle's one), newest first — their own figures sit in the dropdown's details.
    let members: [SleepHistoryEntry]
    /// G235 — "1 conversation may hold a password"; `nil` when this run has nothing to say.
    var sensitiveLine: String? = nil

    /// "Claude Code (your plan) · claude-haiku-5-5" — the engine in words (the person's own choice, `Copy.engineLabel`)
    /// and the models the ledger says ran; `nil` when neither was recorded.
    var engineWords: String? {
        let parts = [engine.map(Copy.engineLabel), models.isEmpty ? nil : models.joined(separator: ", ")].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// The plan share or cost with its basis (ruling 12); "Usage not recorded" when nothing was.
    func usageLine(locale: Locale = .autoupdatingCurrent) -> String? {
        CycleUsageText.summaryLine(kind: "sleep", summary: usage, locale: locale)
    }

    var usageHelp: String? { CycleUsageText.summaryHelp(usage) }

    var durationText: String? {
        guard let durationMs, durationMs > 0 else { return nil }
        return SleepHistoryPresentation.durationText(ms: durationMs)
    }

    /// Every card Past nights draws, newest first: one per run, one per plain Sleep cycle; decay and inbox commits drop.
    static func cards(_ entries: [SleepHistoryEntry], details: [String: SleepRunDetail] = [:],
                      locale: Locale = .autoupdatingCurrent, timeZone: TimeZone = .current) -> [RunCardModel] {
        PastNightItem.group(entries).compactMap {
            make($0, detail: nil, details: details, locale: locale, timeZone: timeZone)
        }
    }

    static func make(_ item: PastNightItem, detail: SleepRunDetail? = nil, details: [String: SleepRunDetail] = [:],
                     locale: Locale = .autoupdatingCurrent, timeZone: TimeZone = .current) -> RunCardModel? {
        switch item {
        case .cycle(let entry):
            guard entry.kind == "sleep" else { return nil }
            let conversations = entry.episodes > 0 ? entry.episodes : (entry.sessions > 0 ? entry.sessions : nil)
            return RunCardModel(
                id: entry.commitHash, key: .commit(entry.commitHash), ranAt: entry.date, starter: nil, catchUp: nil,
                summary: Copy.RunCard.summary(conversations: conversations, created: entry.entitiesCreated,
                                              updated: entry.entitiesUpdated, archived: entry.entitiesArchived,
                                              removed: entry.entitiesRemoved, faded: entry.entitiesFaded,
                                              locale: locale),
                engine: entry.engine ?? entry.usageSummary?.engine,
                models: entry.authors.filter { $0 != "user" }, usage: entry.usageSummary,
                durationMs: entry.durationMs, outcome: .finished, members: [entry])
        case .run(let ref, let members):
            let newest = members[0]
            let models = !ref.models.isEmpty ? ref.models
                : Array(NSOrderedSet(array: members.flatMap { $0.authors }.filter { $0 != "user" })) as? [String] ?? []
            return RunCardModel(
                id: "run:\(ref.id)", key: .run(ref.id), ranAt: ref.startedAt ?? newest.date,
                starter: ref.startedBy == "schedule" ? Copy.RunCard.startedBySchedule : Copy.RunCard.startedByYou,
                catchUp: RunPresentation.catchUp(ref, timeZone: timeZone),
                summary: Copy.RunCard.summary(conversations: ref.filed, created: ref.created, updated: ref.updated,
                                              archived: ref.archived, removed: ref.removed, faded: ref.faded,
                                              locale: locale),
                engine: newest.engine ?? ref.usageSummary?.engine, models: models,
                usage: ref.usageSummary ?? (members.count == 1 ? newest.usageSummary : nil),
                durationMs: ref.readMs > 0 ? ref.readMs : nil,
                outcome: outcome(ref, detail: detail ?? details[ref.id]), members: members,
                sensitiveLine: ref.sensitive.map { Copy.Sensitive.runLine(conversations: $0.conversations, kinds: $0.kinds, locale) })
        }
    }

    /// How a run ended: its state, and for a paused one the reason of its open pause when its detail has loaded.
    static func outcome(_ ref: SleepRunRef, detail: SleepRunDetail?) -> Outcome {
        switch ref.state {
        case "running": return .reading
        case "failed": return .failed
        case "ended": return .stopped
        case "paused":
            switch detail?.pauses.last?.reason {
            case "plan_window", "plan_limit": return .pausedPlanLimit
            case "reserve": return .pausedReserve
            default: return .paused
            }
        default: return .finished
        }
    }

    /// "Nov 22" style heading parts: the day and the time, each in the reader's zone.
    func dayText(timeZone: TimeZone = .current) -> String { SleepHistoryPresentation.dateText(ranAt, timeZone: timeZone) }
    func timeText(timeZone: TimeZone = .current) -> String { SleepHistoryPresentation.timeText(ranAt, timeZone: timeZone) }

    /// The card's first words (owner 2026-11-24): "Today, 2:10 AM", "Yesterday, 11:40 PM", else "Nov 22, 3:00 AM". A
    /// legacy date with no hour says the day alone, never a fabricated midnight.
    func whenText(now: Date = Date(), timeZone: TimeZone = .current) -> String {
        let time = timeText(timeZone: timeZone)
        let day = Self.dayWord(ranAt, now: now, timeZone: timeZone) ?? dayText(timeZone: timeZone)
        return time == "—" ? day : "\(day), \(time)"
    }

    /// "Today" / "Yesterday" for an instant in the reader's zone; nil for any other day.
    static func dayWord(_ iso: String, now: Date = Date(), timeZone: TimeZone = .current) -> String? {
        guard iso.contains("T"), let date = SleepHistoryPresentation.parsed(iso) else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        if calendar.isDate(date, inSameDayAs: now) { return Copy.RunCard.today }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: yesterday) {
            return Copy.RunCard.yesterday
        }
        return nil
    }

    /// Whether a conversation's own timestamp falls on the run's day (its row then says no date: said once).
    func isSameDay(as iso: String, timeZone: TimeZone = .current) -> Bool {
        guard let a = SleepHistoryPresentation.parsed(ranAt), let b = SleepHistoryPresentation.parsed(iso) else { return false }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = iso.contains("T") ? timeZone : (TimeZone(identifier: "UTC") ?? timeZone)
        let day = calendar.dateComponents([.year, .month, .day], from: b)
        calendar.timeZone = timeZone
        return calendar.dateComponents([.year, .month, .day], from: a) == day
    }

    /// The head's one quiet line after the day: who started it, and how long it read (nothing for what was not recorded).
    var metaLine: String? {
        let parts = [starter, durationText.map(Copy.RunCard.took)].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// Everything the card's head draws, in words, for VoiceOver.
    /// `pages` is what a closed card's chips say (the dots are colour, so the words ride here), `sources` the origins its
    /// marks show.
    func accessibilityLabel(summary shown: String? = nil, pages: String? = nil, sources: [String] = [],
                            locale: Locale = .autoupdatingCurrent) -> String {
        var parts = [whenText()]
        parts += [starter, catchUp, shown ?? summary, sources.isEmpty ? nil : Copy.RunCard.readFrom(sources), pages,
                  engineWords, usageLine(locale: locale), durationText, outcome.words]
            .compactMap { $0 }
        return parts.joined(separator: ", ")
    }
}

/// How the dropdown moves (DR-60, DR-61): only a pointer's click eases, on `CicadaMotion.groupExpand`. A key press, an
/// action with no event of its own, and an assistive press (VoiceOver's VO-Space, Switch Control — routed through
/// `assistive(_:)`, because `NSApp.currentEvent` is then whatever came last, often a click) open it in one frame;
/// Reduce Motion never animates.
enum RunCardMotion {
    private static let pointerEvents: Set<NSEvent.EventType> = [
        .leftMouseDown, .leftMouseUp, .rightMouseDown, .rightMouseUp, .otherMouseDown, .otherMouseUp,
    ]

    @MainActor private static var pressingAssistively = false

    static func animation(eventType: NSEvent.EventType?, reduceMotion: Bool) -> Animation? {
        guard let eventType, pointerEvents.contains(eventType) else { return nil }
        return CicadaMotion.groupExpand(reduceMotion: reduceMotion)
    }

    /// The motion for the action running now: none inside an assistive press, else by its event.
    @MainActor
    static func current(reduceMotion: Bool) -> Animation? {
        pressingAssistively ? nil : animation(eventType: NSApp.currentEvent?.type, reduceMotion: reduceMotion)
    }

    /// Runs an assistive press's action so `current` answers one frame whatever event came last.
    @MainActor
    static func assistive(_ action: () -> Void) {
        pressingAssistively = true
        defer { pressingAssistively = false }
        action()
    }
}

/// A page's and a conversation's words, pure.
enum RunItemGroups {
    /// A page's label: its name as the bank has it now, else the graph's name for the id, else the id verbatim.
    static func pageLabel(_ page: SleepConsolidated.Page, names: EntityNames) -> String {
        // G227 (owner 2026-10-29): a page here IS a chip, so a shared title's qualifier rides inside it after a
        // middle dot — the plain name first, never a parenthesis.
        if let name = page.name, !name.isEmpty, let q = page.qualifier, !q.isEmpty { return Copy.RunCard.qualified(name, q) }
        if let shown = page.displayName, !shown.isEmpty { return shown }
        if let name = page.name, !name.isEmpty { return name }
        return names.display(page.id)
    }

    /// A conversation's label: its title, else "Untitled conversation" (the id stays in `.help`).
    static func conversationLabel(_ c: SleepConsolidated.Conversation) -> String {
        let title = (c.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return title.isEmpty ? Copy.RunCard.untitled : title
    }
}

// MARK: - The card

/// One consolidation as a card, in the Queue's source-card chrome (owner 2026-11-24: "apply the same cards into the past
/// reads … showing less unnecessary information and avoiding repetition"). The whole head is the button, no chevron, its
/// ring lifting under the pointer. Line one: when it ran, then one quiet meta line (who started it, how long it read), and
/// at the trailing edge how it ended when it did not simply finish and the sources it read as their marks. Line two: what
/// it read and what that did to the memory, said once. Closed, a line of page chips as a preview; opened, the card of each
/// source with its conversations and their pages (`RunItemsView`). DR-9 (a ring, no shadow), DR-37 (a card holds a group),
/// DR-39 (starts collapsed), DR-52 (real marks), DR-60/61 (a key never animates).
struct RunCardView: View {
    let card: RunCardModel
    let isOpen: Bool
    let items: SleepConsolidated?
    let itemsFailed: Bool
    /// The run's detail (models, cost, batches) for a run; a plain cycle's comes from its commit's detail.
    let runDetail: SleepRunDetail?
    let cycleDetail: SleepCycleDetail?
    /// False when no card recorded usage (say it once, 2026-10-19).
    var showsUsage = true
    let onToggle: () -> Void
    var onSelectEntity: ((String) -> Void)?
    /// Asked once the card is on screen: its items carry the marks and the page names the card shows.
    var onAppear: () -> Void = {}
    /// The machine the page is narrowed to (`MachineStatus.id`), and every machine (for a conversation's machine name).
    var machineId: String? = nil
    var machines: [MachineStatus] = []
    /// Renders seed these (the snapshot): a live card opens on All with no page open.
    var initialFilter: SleepConsolidated.Change? = nil
    var initiallyOpenPage: String? = nil

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(Store.self) private var store: Store?

    /// What the card says it did: the items' own counts once they have loaded (they carry archived and removed pages,
    /// and narrow to a machine), else the history's figures.
    private var summary: String { items.map { RunItemsModel.summary($0, machineId: machineId) } ?? card.summary }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            head
            // G235: one quiet line, outside the card's own button, and the way to the one review.
            if let line = card.sensitiveLine {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(line)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    InlineLink(title: Copy.Sensitive.review) { router?.routeToInbox() }
                }
                .padding(.horizontal, Self.padding)
                .padding(.bottom, CicadaTheme.scaled(10))
            }
            if isOpen {
                RunItemsView(card: card, items: items, failed: itemsFailed, runDetail: runDetail,
                             cycleDetail: cycleDetail, showsUsage: showsUsage, onSelectEntity: onSelectEntity,
                             machines: machines, machineId: machineId, initialFilter: initialFilter,
                             initiallyOpenPage: initiallyOpenPage)
                    .padding(.horizontal, RunItemsView.inset)
                    .padding(.bottom, RunItemsView.inset)
                    .transition(.opacity)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .sourceCardChrome(lit: hovering && !isOpen)
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .onAppear(perform: onAppear)
    }

    static var padding: CGFloat { CicadaTheme.spacingMD + CicadaTheme.scaled(2) }

    private var head: some View {
        let preview = RunItemsModel.preview(items, machineId: machineId)
        let origins = RunItemsModel.origins(items, machineId: machineId)
        return Button(action: onToggle) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
                    Text(card.whenText())
                        .font(CicadaTheme.rowFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textPrimary)
                    if let meta = card.metaLine {
                        Text(meta)
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: CicadaTheme.spacingSM)
                    // DR-38: a card with a summary has finished; only another ending is worth a word.
                    if card.outcome != .finished { outcome }
                    if !origins.isEmpty { RunSourceMarks(origins: origins) }
                }
                Text(summary)
                    .font(CicadaTheme.bodyFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                if !isOpen, !preview.pages.isEmpty {
                    RunPagePreview(pages: preview.pages, total: preview.total)
                        .padding(.top, CicadaTheme.scaled(2))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, Self.padding)
            .padding(.vertical, CicadaTheme.spacingMD)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(card.catchUp ?? "")
        .accessibilityElement(children: .combine)
        .accessibilityLabel(card.accessibilityLabel(
            summary: summary,
            pages: isOpen ? nil : RunPagePreview.spoken(preview.pages, total: preview.total, names: store?.entityNames ?? .empty),
            sources: origins.map { OriginIconography.label(for: $0) }))
        .accessibilityValue(isOpen ? Copy.Lists.expanded : Copy.Lists.collapsed)
        // DR-60: an assistive press opens the card in one frame, whatever event came last.
        .modifier(AssistivePress(action: { RunCardMotion.assistive(onToggle) }))
    }

    private var outcome: some View {
        HStack(spacing: CicadaTheme.scaled(4)) {
            if card.outcome.needsYou {
                Image(systemName: "exclamationmark.triangle")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.warning)
                    .accessibilityHidden(true)
            }
            Text(card.outcome.words)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(card.outcome.needsYou ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
        }
    }
}

/// The sources a consolidation read, as their real marks (DR-52), overlapping like a stack of faces, most-read first;
/// a fourth source and beyond is a "+N" after the last mark. Drawn only once the items say what it read.
struct RunSourceMarks: View {
    let origins: [String]

    static let places = 3
    static var mark: CGFloat { CicadaTheme.scaled(20) }
    static var step: CGFloat { CicadaTheme.scaled(15) }
    static var knock: CGFloat { CicadaTheme.scaled(2) }
    static var moreGap: CGFloat { CicadaTheme.scaled(4) }

    var body: some View {
        let shown = origins.count > Self.places ? Array(origins.prefix(Self.places - 1)) : origins
        let extra = origins.count - shown.count
        // The marks overlap like a stack of faces; the "+N" is not one of them — it follows the last mark with a gap, so
        // no mark can cover its plus.
        HStack(spacing: Self.moreGap) {
            ZStack(alignment: .topLeading) {
                ForEach(Array(shown.enumerated()), id: \.element) { i, origin in
                    tile { StudyListCard.mark(origin, size: Self.mark) }
                        .offset(x: CGFloat(i) * Self.step)
                        .zIndex(Double(Self.places - i))
                }
            }
            .frame(width: Self.mark + 2 * Self.knock + CGFloat(max(shown.count - 1, 0)) * Self.step,
                   height: Self.mark + 2 * Self.knock, alignment: .topLeading)
            if extra > 0 {
                Text(Copy.RunCard.moreSources(extra))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .fixedSize()
            }
        }
        .help(origins.isEmpty ? "" : Copy.RunCard.readFrom(origins.map { OriginIconography.label(for: $0) }))
        .accessibilityHidden(true)   // the card's label says what it read (`accessibilityLabel(sources:)`)
    }

    /// One place: the mark (or a stand-in) on a quiet tile, knocked out of the card by 2 pt so overlaps stay legible.
    private func tile<C: View>(@ViewBuilder _ content: () -> C) -> some View {
        content()
            .frame(width: Self.mark, height: Self.mark)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBadge))
            .padding(Self.knock)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall + Self.knock).fill(CicadaTheme.bgFocus))
    }
}
