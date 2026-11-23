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

    /// The sources a card's marks show (owner 2026-11-23: "cards with logos"): each origin the read's conversations
    /// came from once, the one it read most first (ties keep the conversations' order). Empty until its items load.
    static func origins(_ items: SleepConsolidated?) -> [String] {
        guard let items else { return [] }
        var counts: [String: Int] = [:]
        var order: [String] = []
        for c in items.conversations {
            if counts[c.origin] == nil { order.append(c.origin) }
            counts[c.origin, default: 0] += 1
        }
        return order.enumerated()
            .sorted { (counts[$0.element] ?? 0, -$0.offset) > (counts[$1.element] ?? 0, -$1.offset) }
            .map(\.element)
    }

    /// The pages a card names before it is opened: new ones first, then the updated, as far as listed; and how many
    /// it changed in all (the server's whole counts, so "+N" never undercounts a capped list).
    static func pagePreview(_ items: SleepConsolidated?) -> (pages: [SleepConsolidated.Page], total: Int) {
        guard let items else { return ([], 0) }
        let pages = items.created + items.updated
        let total = items.count("created", items.created.count) + items.count("updated", items.updated.count)
        return (pages, max(total, pages.count))
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
                                              updated: entry.entitiesUpdated, locale: locale),
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

    /// "Today, 7:27 AM" style heading parts: the day and the time, each in the reader's zone.
    func dayText(timeZone: TimeZone = .current) -> String { SleepHistoryPresentation.dateText(ranAt, timeZone: timeZone) }
    func timeText(timeZone: TimeZone = .current) -> String { SleepHistoryPresentation.timeText(ranAt, timeZone: timeZone) }

    /// Everything the card's head draws, in words, for VoiceOver.
    func accessibilityLabel(locale: Locale = .autoupdatingCurrent) -> String {
        var parts = [dayText()]
        let time = timeText()
        if time != "—" { parts.append(time) }
        parts += [starter, catchUp, summary, engineWords, usageLine(locale: locale), durationText, outcome.words]
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

/// The dropdown's groups, pure: each group's title, its count (the server's whole count) and its rows.
enum RunItemGroups {
    /// Rows a group shows before "Show all N".
    static let preview = 8

    struct Group: Equatable, Identifiable {
        enum Kind: String, Equatable { case conversations, created, updated, raised, settled }
        let kind: Kind
        let title: String
        let count: Int
        var id: String { kind.rawValue }
    }

    /// The groups that hold anything, in reading order: what it read, what it made, what it changed, then questions.
    static func groups(_ items: SleepConsolidated) -> [Group] {
        [
            Group(kind: .conversations, title: Copy.RunCard.conversationsRead,
                  count: items.count("conversations", items.conversations.count)),
            Group(kind: .created, title: Copy.RunCard.pagesCreated, count: items.count("created", items.created.count)),
            Group(kind: .updated, title: Copy.RunCard.pagesUpdated, count: items.count("updated", items.updated.count)),
            Group(kind: .raised, title: Copy.RunCard.questionsRaised,
                  count: items.count("questions_raised", items.questionsRaised.count)),
            Group(kind: .settled, title: Copy.RunCard.questionsSettled,
                  count: items.count("questions_settled", items.questionsSettled.count)),
        ].filter { $0.count > 0 }
    }

    /// A page's label: its name as the bank has it now, else the graph's name for the id, else the id verbatim.
    static func pageLabel(_ page: SleepConsolidated.Page, names: EntityNames) -> String {
        // G227 (owner 2026-10-29): a page here IS a `Tag`, so a shared title's qualifier rides inside it after a
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

/// One consolidation as a card (owner 2026-11-23: "a better redesign that fits the cards with logos and less dense and
/// less amount of info … I want to easily see what was consolidated"): the sources it read as their marks, when it ran,
/// one line of what it read and what that changed, and the pages it changed by name. The engine, models, plan usage or
/// cost and how long it read live in the dropdown's "Models and batches" (ruling 12's figures, each with its basis).
/// DR-9 (a ring, no shadow), DR-37 (a card holds a group), DR-39 (starts collapsed), DR-44 (pages are `Tag`s), DR-52
/// (real marks), DR-60/61 (a key never animates). No chevron (owner 2026-11-23, as on Waiting's source cards): the whole
/// card opens on a click, and its ring lifts under the pointer.
struct RunCardView: View {
    let card: RunCardModel
    let isOpen: Bool
    let items: SleepConsolidated?
    let itemsFailed: Bool
    /// The run's detail (models, cost, batches) for a run; a plain cycle's comes from its commit's detail.
    let runDetail: SleepRunDetail?
    let cycleDetail: SleepCycleDetail?
    /// False when Past nights' label already says no card recorded usage (say it once, 2026-10-19).
    var showsUsage = true
    let onToggle: () -> Void
    var onSelectEntity: ((String) -> Void)?
    /// Asked once the card is on screen: its items carry the marks and the page names the card shows.
    var onAppear: () -> Void = {}

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(AppRouter.self) private var router: AppRouter?

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
                .padding(.leading, Self.textInset)
                .padding(.trailing, Self.padding)
                .padding(.bottom, CicadaTheme.scaled(10))
            }
            if isOpen {
                RunItemsView(card: card, items: items, failed: itemsFailed, runDetail: runDetail,
                             cycleDetail: cycleDetail, showsUsage: showsUsage, onSelectEntity: onSelectEntity)
                    .padding(.leading, Self.textInset - CicadaTheme.scaled(8))
                    .padding(.trailing, Self.padding)
                    .padding(.bottom, Self.padding)
                    .transition(.opacity)
            }
        }
        .background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgFocus))
        .ringed(hovering && !isOpen ? .strong : .resting, in: CicadaTheme.shape(CicadaTheme.radiusLarge))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .onAppear(perform: onAppear)
    }

    static var padding: CGFloat { CicadaTheme.spacingLG }
    /// Where the card's words start, so the dropdown lines up under the summary.
    static var textInset: CGFloat { padding }

    private var head: some View {
        let preview = RunCardModel.pagePreview(items)
        return Button(action: onToggle) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                    HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                        Text("\(card.dayText()), \(card.timeText())")
                            .font(CicadaTheme.rowFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textPrimary)
                        if let starter = card.starter {
                            Text(starter)
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                        Spacer(minLength: CicadaTheme.spacingSM)
                        // DR-38: a card with a summary has finished; only another ending is worth a word.
                        if card.outcome != .finished { outcome }
                    }
                    // The sources it read, as their marks, leading the line that says what it read (owner 2026-11-23).
                    HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
                        let origins = RunCardModel.origins(items)
                        if !origins.isEmpty { RunSourceMarks(origins: origins) }
                        Text(card.summary)
                            .font(CicadaTheme.bodyFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if !preview.pages.isEmpty {
                        RunPagePreview(pages: preview.pages, total: preview.total)
                    }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(Self.padding)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(card.catchUp ?? "")
        .accessibilityElement(children: .combine)
        .accessibilityLabel(card.accessibilityLabel())
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
/// a fourth source and beyond is a "+N" on the last place. Drawn only once the items say what it read.
struct RunSourceMarks: View {
    let origins: [String]

    static let places = 3
    static var mark: CGFloat { CicadaTheme.scaled(20) }
    static var step: CGFloat { CicadaTheme.scaled(15) }
    static var knock: CGFloat { CicadaTheme.scaled(2) }

    var body: some View {
        let shown = origins.count > Self.places ? Array(origins.prefix(Self.places - 1)) : origins
        let extra = origins.count - shown.count
        let places = shown.count + (extra > 0 ? 1 : 0)
        ZStack(alignment: .topLeading) {
            ForEach(Array(shown.enumerated()), id: \.element) { i, origin in
                tile { StudyListCard.mark(origin, size: Self.mark) }
                    .offset(x: CGFloat(i) * Self.step)
                    .zIndex(Double(Self.places - i))
            }
            if extra > 0 {
                tile {
                    Text(Copy.RunCard.moreSources(extra))
                        .font(CicadaTheme.badgeFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .offset(x: CGFloat(shown.count) * Self.step)
            }
        }
        .frame(width: Self.mark + 2 * Self.knock + CGFloat(max(places - 1, 0)) * Self.step,
               height: Self.mark + 2 * Self.knock, alignment: .topLeading)
        .help(origins.isEmpty ? "" : Copy.RunCard.readFrom(origins.map { OriginIconography.label(for: $0) }))
        .accessibilityHidden(true)   // the card's label says what it read
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

/// The pages a closed card names, on one line: as many as fit, then "+N" for the rest (owner 2026-11-23: "easily
/// see what was consolidated"). Neutral `Tag`s (DR-44); a click anywhere opens the card, where each page opens.
struct RunPagePreview: View {
    let pages: [SleepConsolidated.Page]
    let total: Int
    @Environment(Store.self) private var store: Store?

    var body: some View {
        let names = store?.entityNames ?? .empty
        let labels = pages.prefix(6).map { RunItemGroups.pageLabel($0, names: names) }
        ViewThatFits(in: .horizontal) {
            ForEach(Array(stride(from: labels.count, through: 1, by: -1)), id: \.self) { n in
                row(Array(labels.prefix(n)))
            }
            row([])
        }
    }

    private func row(_ shown: [String]) -> some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            ForEach(Array(shown.enumerated()), id: \.offset) { _, label in
                Tag(text: label).lineLimit(1).fixedSize()
            }
            if total > shown.count {
                Text(Copy.RunCard.morePages(total - shown.count))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize()
            }
        }
    }
}

// MARK: - The dropdown

/// What the consolidation read and changed: its conversations (open in the Reader), every page it made or changed —
/// each one's change a click away (owner 2026-11-23: "see from it what page or chunk of page/pages was modified") —
/// then its questions and, under one fold, the engine, plan usage or cost, time and batches (ruling 12).
struct RunItemsView: View {
    let card: RunCardModel
    let items: SleepConsolidated?
    let failed: Bool
    let runDetail: SleepRunDetail?
    let cycleDetail: SleepCycleDetail?
    var showsUsage = true
    var onSelectEntity: ((String) -> Void)?

    @State private var openGroups: Set<String> = []
    @State private var showingAll: Set<String> = []
    @State private var detailsOpen = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if let items {
                if !items.conversations.isEmpty {
                    section(Copy.RunCard.conversationsRead, count: items.count("conversations", items.conversations.count)) {
                        let all = showingAll.contains("conversations")
                        let list = all ? items.conversations : Array(items.conversations.prefix(RunItemGroups.preview))
                        ForEach(list) { ConsolidatedConversationRow(conversation: $0) }
                        more("conversations", shown: list.count, total: items.conversations.count)
                    }
                }
                let pages = RunCardModel.pagePreview(items)
                if !pages.pages.isEmpty {
                    section(Copy.RunCard.pagesChanged, count: pages.total) {
                        let all = showingAll.contains("pages")
                        let list = all ? pages.pages : Array(pages.pages.prefix(RunItemGroups.preview))
                        let made = Set(items.created.map(\.id))
                        ForEach(list) { page in
                            RunPageRow(page: page, isNew: made.contains(page.id),
                                       commits: page.commits.isEmpty && items.commits.count == 1 ? items.commits
                                                                                                : page.commits,
                                       onSelectEntity: onSelectEntity)
                        }
                        more("pages", shown: list.count, total: pages.pages.count)
                    }
                }
                questions(items)
                if items.truncated {
                    note(Copy.RunCard.moreNotListed)
                }
            } else if failed {
                note(Copy.RunCard.unavailable)
            } else {
                note(Copy.RunCard.loading)
            }
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                DisclosureHeader(title: Copy.RunCard.detailsTitle, isOpen: detailsOpen, fillsWidth: true) {
                    let animation = RunCardMotion.current(reduceMotion: reduceMotion)
                    withAnimation(animation) { detailsOpen.toggle() }
                }
                if detailsOpen {
                    details.transition(.opacity)
                }
            }
            if let replaced = runDetail?.replaced, replaced > 0 {
                note(Copy.Sensitive.replaced(replaced))
            }
        }
    }

    private func section<C: View>(_ title: String, count: Int, @ViewBuilder rows: () -> C) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
            SectionLabel(Eyebrow.text(title, Copy.RunCard.count(count, .autoupdatingCurrent)))
                .padding(.horizontal, CicadaTheme.scaled(8))
                .padding(.bottom, CicadaTheme.scaled(2))
            // Lazy, like every "All N" (inbox freeze, 2026-10-29).
            LazyVStack(alignment: .leading, spacing: 0) { rows() }
        }
    }

    /// The questions it raised and settled: a fold each, closed — they are the Inbox's, the card only points at them.
    @ViewBuilder
    private func questions(_ items: SleepConsolidated) -> some View {
        let groups = RunItemGroups.groups(items).filter { $0.kind == .raised || $0.kind == .settled }
        if !groups.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ForEach(groups) { group in
                    DisclosureHeader(title: group.title, summary: Copy.RunCard.count(group.count, .autoupdatingCurrent),
                                     summaryWhenOpen: true, isOpen: openGroups.contains(group.id), fillsWidth: true,
                                     spokenTitle: group.title) { toggleGroup(group.id) }
                    if openGroups.contains(group.id) {
                        let questions = group.kind == .raised ? items.questionsRaised : items.questionsSettled
                        let all = showingAll.contains(group.id)
                        let list = all ? questions : Array(questions.prefix(RunItemGroups.preview))
                        LazyVStack(alignment: .leading, spacing: 0) {
                            ForEach(list) { ConsolidatedQuestionRow(question: $0) }
                            more(group.id, shown: list.count, total: questions.count)
                        }
                        .padding(.leading, CicadaTheme.scaled(18))
                        .transition(.opacity)
                    }
                }
            }
        }
    }

    private func toggleGroup(_ id: String) {
        let animation = RunCardMotion.current(reduceMotion: reduceMotion)
        withAnimation(animation) { openGroups.formSymmetricDifference([id]) }
    }

    private func toggleShowAll(_ id: String) {
        let animation = RunCardMotion.current(reduceMotion: reduceMotion)
        withAnimation(animation) { showingAll.formSymmetricDifference([id]) }
    }

    @ViewBuilder
    private func more(_ id: String, shown: Int, total: Int) -> some View {
        if total > RunItemGroups.preview, shown < total || showingAll.contains(id) {
            TextButton(title: showingAll.contains(id) ? Copy.RunCard.showFewer : Copy.RunCard.showAll(total)) {
                toggleShowAll(id)
            }
            .padding(.horizontal, CicadaTheme.scaled(8))
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(minHeight: CicadaTheme.scaled(DisclosureHeader.height), alignment: .leading)
    }

    /// The facts the card's head no longer carries — the engine and models, the plan share or cost with its basis on
    /// hover (ruling 12), how long it read, a scheduled catch-up — then the run's batches or the cycle's models.
    @ViewBuilder
    private var details: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                if let words = card.engineWords {
                    HStack(spacing: CicadaTheme.scaled(5)) {
                        if let engine = card.engine {
                            EngineMark(engine: engine, size: CicadaTheme.scaled(12), model: card.models.first)
                        }
                        Text(words).lineLimit(1).truncationMode(.tail)
                    }
                }
                if showsUsage, let usage = card.usageLine() {
                    Text(usage).monospacedDigit().help(card.usageHelp ?? "")
                }
                if let took = card.durationText {
                    Text(Copy.RunCard.took(took)).monospacedDigit()
                }
                if let catchUp = card.catchUp {
                    Text(catchUp).monospacedDigit()
                }
            }
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            switch card.key {
            case .run:
                RunDetailBlock(detail: runDetail, onSelectEntity: onSelectEntity)
            case .commit:
                CycleUsageBlock(detail: cycleDetail)
            }
        }
        .padding(.leading, CicadaTheme.scaled(18))
    }
}

/// One page the read made or changed (owner 2026-11-23): its name, "New" when the read made it, and — a click away —
/// what changed on it: one diff from before the read's first commit that touched it to after its last (`?since=`), in
/// the History tab's `DiffView`. The arrow opens the page. A page gone since shows its name and opens nothing.
struct RunPageRow: View {
    let page: SleepConsolidated.Page
    let isNew: Bool
    /// The read's commits that changed the page, oldest first; empty when not recorded (an older backend).
    let commits: [String]
    var onSelectEntity: ((String) -> Void)?
    /// Tests hand the loader in; the live row reads the backend.
    /// Renders seed it open (the snapshot); a live row starts closed.
    var initiallyOpen = false
    var loadDiff: (String, String, String?) async throws -> EntityDiff = { id, until, since in
        if let since { try await APIClient.shared.fetchEntityCommitDiff(id: id, commitHash: until, since: since) }
        else { try await APIClient.shared.fetchEntityCommitDiff(id: id, commitHash: until) }
    }

    @State private var open = false
    @State private var diff: EntityDiff?
    @State private var failed = false
    @State private var hovering = false
    @Environment(Store.self) private var store: Store?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var canShowChange: Bool { !page.gone && !commits.isEmpty }

    var body: some View {
        let label = RunItemGroups.pageLabel(page, names: store?.entityNames ?? .empty)
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: CicadaTheme.scaled(2)) {
                Button { press(label) } label: {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(label)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(page.gone ? CicadaTheme.textTertiary : CicadaTheme.textPrimary)
                            .lineLimit(1)
                            .truncationMode(.tail)
                        if isNew { Tag(text: Copy.RunCard.newPage) }
                        Spacer(minLength: CicadaTheme.spacingSM)
                        // Said on the row the pointer is on, and on an open one — never down every row (less dense).
                        if canShowChange && (hovering || open) {
                            Text(open ? Copy.RunCard.hideChange : Copy.RunCard.showChange)
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(hovering ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                        }
                    }
                    .padding(.horizontal, CicadaTheme.scaled(8))
                    .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
                    .rowHoverFill(hovering: hovering)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .onHover { hovering = $0 }
                .disabled(page.gone)
                .help(page.gone ? Copy.RunCard.goneHelp : canShowChange ? Copy.RunCard.changeHelp(label) : page.id)
                .accessibilityLabel(canShowChange ? Copy.RunCard.changeHelp(label) : Copy.RunCard.openPage(label))
                .accessibilityValue(canShowChange ? (open ? Copy.Lists.expanded : Copy.Lists.collapsed) : "")
                if !page.gone {
                    IconButton(systemName: "arrow.up.right", help: Copy.RunCard.openPage(label)) {
                        onSelectEntity?(page.id)
                    }
                }
            }
            if open {
                change
                    .padding(.horizontal, CicadaTheme.scaled(8))
                    .padding(.vertical, CicadaTheme.spacingXS)
                    .transition(.opacity)
            }
        }
        .onAppear { if initiallyOpen { open = true } }
        .task(id: open) { if open, diff == nil { await fetch() } }
    }

    private func press(_ label: String) {
        guard canShowChange else { onSelectEntity?(page.id); return }
        let animation = RunCardMotion.current(reduceMotion: reduceMotion)
        withAnimation(animation) { open.toggle() }
    }

    @ViewBuilder
    private var change: some View {
        if let diff {
            if DiffModel(diff).isEmpty {
                Text(Copy.RunCard.noChange)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                // The diff scrolls inside a short window, so one long page never pushes the rest of the card away.
                ScrollView(.vertical) { DiffView(diff: diff) }
                    .frame(height: Self.height(lines: DiffModel(diff).lines.count))
                    .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
                    .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                    .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            }
        } else if failed {
            DiffView.error { Task { await fetch() } }
        } else {
            DiffView.loading
        }
    }

    /// The diff's window: its rows' height up to twelve rows, then it scrolls.
    static func height(lines: Int) -> CGFloat {
        CicadaTheme.scaled(CGFloat(min(max(lines, 1), 12)) * 18 + 8)
    }

    private func fetch() async {
        guard let until = commits.last else { return }
        failed = false
        do {
            diff = try await loadDiff(page.id, until, commits.count > 1 ? commits.first : nil)
        } catch {
            failed = true
        }
    }
}

/// One conversation the run read: its real mark (DR-52), its title, its day; a click opens it in the Reader.
private struct ConsolidatedConversationRow: View {
    let conversation: SleepConsolidated.Conversation
    @Environment(ProvenanceRouter.self) private var reader: ProvenanceRouter?
    @State private var hovering = false

    var body: some View {
        let label = RunItemGroups.conversationLabel(conversation)
        Button {
            reader?.open(ReaderTarget(episode: conversation.id, knownTitle: conversation.title))
        } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                OriginMark(origin: conversation.origin, size: CicadaTheme.scaled(12))
                Text(label)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: CicadaTheme.spacingSM)
                if let ts = conversation.timestamp {
                    Text(SleepHistoryPresentation.dateText(ts))
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .rowHoverFill(hovering: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(conversation.id)
        .accessibilityLabel(Copy.RunCard.openConversation(label))
    }
}

/// One question the run raised or settled; a click opens it in the Inbox.
private struct ConsolidatedQuestionRow: View {
    let question: SleepConsolidated.Question
    @Environment(AppRouter.self) private var router: AppRouter?
    @State private var hovering = false

    var body: some View {
        let label = (question.title ?? "").isEmpty ? question.id : (question.title ?? question.id)
        Button { router?.routeToInboxItem(question.id) } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(label)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .rowHoverFill(hovering: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel(Copy.RunCard.openQuestion(label))
    }
}
