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
    /// `items` are the dropdowns' lists as far as they have loaded (`SleepViewModel.consolidated`): the card's question
    /// count is the dropdown's own, so the two never disagree; before a card's items load it names no questions.
    static func cards(_ entries: [SleepHistoryEntry], details: [String: SleepRunDetail] = [:],
                      items: [SleepConsolidatedKey: SleepConsolidated] = [:],
                      locale: Locale = .autoupdatingCurrent, timeZone: TimeZone = .current) -> [RunCardModel] {
        PastNightItem.group(entries).compactMap {
            make($0, detail: nil, details: details, items: items, locale: locale, timeZone: timeZone)
        }
    }

    /// The questions a card names: the dropdown's raised and settled, whole counts; `nil` until its items load.
    static func questions(_ items: SleepConsolidated?) -> Int? {
        guard let items else { return nil }
        return items.count("questions_raised", items.questionsRaised.count)
            + items.count("questions_settled", items.questionsSettled.count)
    }

    static func make(_ item: PastNightItem, detail: SleepRunDetail? = nil, details: [String: SleepRunDetail] = [:],
                     items: [SleepConsolidatedKey: SleepConsolidated] = [:],
                     locale: Locale = .autoupdatingCurrent, timeZone: TimeZone = .current) -> RunCardModel? {
        switch item {
        case .cycle(let entry):
            guard entry.kind == "sleep" else { return nil }
            let conversations = entry.episodes > 0 ? entry.episodes : (entry.sessions > 0 ? entry.sessions : nil)
            return RunCardModel(
                id: entry.commitHash, key: .commit(entry.commitHash), ranAt: entry.date, starter: nil, catchUp: nil,
                summary: Copy.RunCard.summary(conversations: conversations, created: entry.entitiesCreated,
                                              updated: entry.entitiesUpdated,
                                              questions: questions(items[.commit(entry.commitHash)]), locale: locale),
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
                                              questions: questions(items[.run(ref.id)]), locale: locale),
                engine: newest.engine ?? ref.usageSummary?.engine, models: models,
                usage: ref.usageSummary ?? (members.count == 1 ? newest.usageSummary : nil),
                durationMs: ref.readMs > 0 ? ref.readMs : nil,
                outcome: outcome(ref, detail: detail ?? details[ref.id]), members: members)
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

/// DR-9, DR-37 (a card holds a group — here one consolidation's head and its dropdown), DR-39 (the dropdown starts
/// collapsed), DR-44 (pages are `Tag`s), DR-48 (rows), DR-52 (real marks), DR-53 (`DisclosureChevron`), DR-60/61 (a key
/// never animates). A resting ring on `bgFocus`, no shadow; §9 2026-10-26 records the owner's card over the list rows.
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
    /// Asked once the card is on screen: its items carry the question count its summary names (the dropdown's own).
    var onAppear: () -> Void = {}

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            head
            if isOpen {
                RunItemsView(card: card, items: items, failed: itemsFailed, runDetail: runDetail,
                             cycleDetail: cycleDetail, onSelectEntity: onSelectEntity)
                    .padding(.horizontal, CicadaTheme.scaled(14))
                    .padding(.bottom, CicadaTheme.scaled(14))
                    .transition(.opacity)
            }
        }
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
        .ringed(hovering && !isOpen ? .strong : .resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .onAppear(perform: onAppear)
    }

    private var head: some View {
        Button(action: onToggle) {
            HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    HStack(spacing: CicadaTheme.spacingSM) {
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
                        outcome
                    }
                    if let catchUp = card.catchUp {
                        Text(catchUp)
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    Text(card.summary)
                        .font(CicadaTheme.bodyFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    meta
                }
                DisclosureChevron(isOpen: isOpen)
                    .padding(.top, CicadaTheme.scaled(4))
            }
            .padding(CicadaTheme.scaled(14))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
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

    /// The engine's mark and words, the plan usage or cost (its basis on hover), and how long it read — one wrapping
    /// line of `textTertiary` facts.
    private var meta: some View {
        FlowLayout(spacing: CicadaTheme.scaled(10)) {
            if let words = card.engineWords {
                HStack(spacing: CicadaTheme.scaled(4)) {
                    if let engine = card.engine {
                        EngineMark(engine: engine, size: CicadaTheme.scaled(12), model: card.models.first)
                    }
                    Text(words).lineLimit(1).truncationMode(.tail)
                }
            }
            if showsUsage, let usage = card.usageLine() {
                Text(usage)
                    .monospacedDigit()
                    .help(card.usageHelp ?? "")
            }
            if let took = card.durationText {
                Text(took).monospacedDigit()
            }
        }
        .font(CicadaTheme.metaFont)
        .foregroundStyle(CicadaTheme.textTertiary)
    }
}

// MARK: - The dropdown

/// What the consolidation read and wrote, grouped (DR-39 folds through `DisclosureHeader`, the one fold): the
/// conversations open to the Reader, pages open to the page, questions open in the Inbox. Then its models and
/// batches — ruling 12's figures, each with its basis — under one fold of their own.
struct RunItemsView: View {
    let card: RunCardModel
    let items: SleepConsolidated?
    let failed: Bool
    let runDetail: SleepRunDetail?
    let cycleDetail: SleepCycleDetail?
    var onSelectEntity: ((String) -> Void)?

    @State private var openGroups: Set<String> = ["conversations", "created"]
    @State private var showingAll: Set<String> = []
    @State private var detailsOpen = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let items {
                ForEach(RunItemGroups.groups(items)) { group in
                    DisclosureHeader(title: group.title, summary: Copy.RunCard.count(group.count, .autoupdatingCurrent),
                                     summaryWhenOpen: true, isOpen: openGroups.contains(group.id), fillsWidth: true,
                                     spokenTitle: group.title) { toggleGroup(group.id) }
                    if openGroups.contains(group.id) {
                        rows(group, items)
                            .transition(.opacity)
                    }
                }
                if items.truncated {
                    note(Copy.RunCard.moreNotListed)
                }
            } else if failed {
                note(Copy.RunCard.unavailable)
            } else {
                note(Copy.RunCard.loading)
            }
            DisclosureHeader(title: Copy.RunCard.detailsTitle, isOpen: detailsOpen, fillsWidth: true) {
                let animation = RunCardMotion.current(reduceMotion: reduceMotion)
                withAnimation(animation) { detailsOpen.toggle() }
            }
            if detailsOpen {
                details.transition(.opacity)
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
    private func rows(_ group: RunItemGroups.Group, _ items: SleepConsolidated) -> some View {
        let all = showingAll.contains(group.id)
        VStack(alignment: .leading, spacing: 0) {
            switch group.kind {
            case .conversations:
                let list = all ? items.conversations : Array(items.conversations.prefix(RunItemGroups.preview))
                ForEach(list) { ConsolidatedConversationRow(conversation: $0) }
                more(group, shown: list.count, total: items.conversations.count)
            case .created, .updated:
                let pages = group.kind == .created ? items.created : items.updated
                let list = all ? pages : Array(pages.prefix(RunItemGroups.preview * 3))
                ConsolidatedPageTags(pages: list, onSelectEntity: onSelectEntity)
                    .padding(.vertical, CicadaTheme.scaled(4))
                more(group, shown: list.count, total: pages.count)
            case .raised, .settled:
                let questions = group.kind == .raised ? items.questionsRaised : items.questionsSettled
                let list = all ? questions : Array(questions.prefix(RunItemGroups.preview))
                ForEach(list) { ConsolidatedQuestionRow(question: $0) }
                more(group, shown: list.count, total: questions.count)
            }
        }
        .padding(.leading, CicadaTheme.scaled(18))
    }

    @ViewBuilder
    private func more(_ group: RunItemGroups.Group, shown: Int, total: Int) -> some View {
        if total > RunItemGroups.preview, shown < total || showingAll.contains(group.id) {
            TextButton(title: showingAll.contains(group.id) ? Copy.RunCard.showFewer : Copy.RunCard.showAll(total)) {
                toggleShowAll(group.id)
            }
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .frame(minHeight: CicadaTheme.scaled(DisclosureHeader.height), alignment: .leading)
    }

    @ViewBuilder
    private var details: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
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

/// The pages a run made or changed, as neutral `Tag`s by name (DR-44, DR-54): a click opens the page; a page gone since
/// shows its id and opens nothing.
private struct ConsolidatedPageTags: View {
    let pages: [SleepConsolidated.Page]
    var onSelectEntity: ((String) -> Void)?
    @Environment(Store.self) private var store: Store?

    var body: some View {
        let names = store?.entityNames ?? .empty
        FlowLayout(spacing: 6) {
            ForEach(pages) { page in
                let label = RunItemGroups.pageLabel(page, names: names)
                if page.gone {
                    Tag(text: label).opacity(0.6).help(Copy.RunCard.goneHelp)
                } else {
                    Button { onSelectEntity?(page.id) } label: { Tag(text: label) }
                        .buttonStyle(.cicadaPlain)
                        .help(page.id)
                        .accessibilityLabel(Copy.RunCard.openPage(label))
                }
            }
        }
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
