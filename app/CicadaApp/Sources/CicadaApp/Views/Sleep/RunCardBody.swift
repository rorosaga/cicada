import AppKit
import SwiftUI

// MARK: - The opened card (owner 2026-11-24)
//
// *"Make it easy to see what was consolidated, an easy view to see the pages affected per source, if it was an update,
// creation or deletion of entity pages … apply the same cards into the past reads."* The opened run is the Queue's
// nesting read the other way round: the run's card holds one card per source (the source's real mark and name), a source
// holds the conversations it fed, a conversation holds the pages it fed as chips, each chip's dot saying what the read
// did to the page. Nothing here repeats the head's totals.

/// What a click on a page chip loads: the read's change on one page, ready to draw — why, its facts, its text in
/// blocks (`GET /sleep/runs/{id}/pages/{page}/change`, items-6). Injected by the page from its view model, so no view
/// under `Views/Sleep` calls the API itself; renders hand in a fixed change.
typealias RunPageChangeLoader = (_ key: SleepConsolidatedKey, _ page: String) async throws -> SleepPageChange

private struct RunPageChangeLoaderKey: EnvironmentKey {
    static let defaultValue: RunPageChangeLoader = { _, _ in throw CancellationError() }
}

extension EnvironmentValues {
    var runPageChangeLoader: RunPageChangeLoader {
        get { self[RunPageChangeLoaderKey.self] }
        set { self[RunPageChangeLoaderKey.self] = newValue }
    }
}

/// What the opened card and its parts share, so a source card takes one value instead of a dozen arguments.
struct RunBodyContext {
    let card: RunCardModel
    let machines: [MachineStatus]
    let machineId: String?
    /// The consolidation's commits, for a page that does not name its own (a single-commit read).
    let commits: [String]
    var onSelectEntity: ((String) -> Void)?
}

enum RunBodyLimits {
    /// Conversations a source shows before "All N" (DR-81: at most five rows).
    static let conversations = 5
    /// Page chips a conversation shows before "+N more", and an upkeep group before its own.
    static let chips = 8
    static let questions = 5
}

// MARK: - A page as a chip

/// A page as its chip face: its picture where it has one (a person's photo or initials, a company's logo, a media
/// thumbnail — never initials for anything else, DR-48), its name, and a small dot saying what the read did to it: green
/// for new, none for updated or faded, grey for archived, red for removed (DR-7: one meaning each, and never alone — the
/// words are in `.help` and VoiceOver). Drawn alone in a closed card's preview; `RunPageChip` is the same face as a button.
struct RunPageChipFace: View {
    let page: SleepConsolidated.Page
    let label: String
    var hovering = false
    @Environment(Store.self) private var store: Store?
    @State private var imageArrived = false

    private var type: EntityType { EntityType(rawValue: page.type ?? "") ?? .unknown }
    private var slotShown: Bool { type == .person || imageArrived }
    private var hasPicture: Bool {
        guard let store, !page.gone else { return false }
        return !EntityPictureLayout.isEmpty(type, picture: store.picture(for: page.id))
    }

    static func dot(_ change: SleepConsolidated.Change?) -> Color? {
        switch change {
        case .created: CicadaTheme.success
        case .archived: CicadaTheme.textTertiary
        case .removed: CicadaTheme.danger
        case .updated, .faded, nil: nil
        }
    }

    var body: some View {
        // No spacing of its own: a part that is not drawn must take no gap either (a picture still on its way is a
        // zero-width host, and `HStack` spacing would have left its 6 pt behind it).
        HStack(spacing: 0) {
            if let dot = Self.dot(page.change) {
                Circle().fill(dot)
                    .frame(width: CicadaTheme.scaled(Tag.dotSize), height: CicadaTheme.scaled(Tag.dotSize))
                    .padding(.trailing, Self.gap)
                    .accessibilityHidden(true)
            }
            if hasPicture {
                let well = EntityPictureLayout.frame(type, size: CicadaTheme.scaled(16))
                // `EntityPicture` is 20 pt at the least (C11); the chip's 16 is that, drawn at four fifths. A page that
                // is not a person takes its slot only once its image has really arrived (a missing file draws no empty
                // well and no gap), a person's initials are the picture.
                EntityPicture(id: page.id, name: label, type: type, size: 20, imageArrived: $imageArrived)
                    .scaleEffect(0.8)
                    .frame(width: slotShown ? well.width : 0, height: well.height)
                    .opacity(slotShown ? 1 : 0)
                    .clipped()
                    .padding(.trailing, slotShown ? Self.gap : 0)
                    .accessibilityHidden(true)
            }
            Text(label)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(page.gone ? CicadaTheme.textTertiary : CicadaTheme.textPrimary)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        .padding(.horizontal, CicadaTheme.scaled(8))
        .frame(height: CicadaTheme.scaled(Self.height))
        .rowHoverFill(hovering: hovering)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
        .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
            .strokeBorder(CicadaTheme.ring(hovering ? .strong : .resting), lineWidth: 1))
        .fixedSize()
    }

    static let height: CGFloat = 24
    static var gap: CGFloat { CicadaTheme.scaled(6) }
}

/// A chip that shows what the read changed on its page: a click opens the diff under the conversation's chips, which
/// carries the way to open the page (one more click). A page with no recorded change opens the page at once; a page gone
/// since is the name alone.
struct RunPageChip: View {
    let page: SleepConsolidated.Page
    let label: String
    let canShowChange: Bool
    let isOpen: Bool
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let change = page.change ?? .updated
        Button(action: action) {
            RunPageChipFace(page: page, label: label, hovering: hovering || isOpen)
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .disabled(page.gone)
        .help(page.gone ? "\(label) — \(Copy.RunCard.goneHelp)" : Copy.RunCard.pageHelp(label, change, canShow: canShowChange))
        .accessibilityLabel(Copy.RunCard.pageLabel(label, change))
        .accessibilityHint(page.gone ? "" : canShowChange ? Copy.RunCard.changeHint : Copy.RunCard.openPage(label))
        .accessibilityValue(canShowChange && !page.gone ? (isOpen ? Copy.Lists.expanded : Copy.Lists.collapsed) : "")
    }
}

/// The pages a closed card names, on one line: as many as fit, new first, then "+N" for the rest. Display only — the
/// whole head is the button that opens the card, where each chip opens its change.
struct RunPagePreview: View {
    let pages: [SleepConsolidated.Page]
    let total: Int
    @Environment(Store.self) private var store: Store?

    static let shown = 6

    /// The previewed pages in words, each with what the read did to it (the dot's twin for VoiceOver), and how many more.
    static func spoken(_ pages: [SleepConsolidated.Page], total: Int, names: EntityNames) -> String? {
        let named = pages.prefix(shown).map { Copy.RunCard.pageLabel(RunItemGroups.pageLabel($0, names: names), $0.change ?? .updated) }
        guard !named.isEmpty else { return nil }
        let rest = total - named.count
        return (named + (rest > 0 ? [Copy.RunCard.morePages(rest)] : [])).joined(separator: "; ")
    }

    var body: some View {
        let names = store?.entityNames ?? .empty
        let chips = pages.prefix(Self.shown).map { (page: $0, label: RunItemGroups.pageLabel($0, names: names)) }
        ViewThatFits(in: .horizontal) {
            ForEach(Array(stride(from: chips.count, through: 1, by: -1)), id: \.self) { n in
                row(Array(chips.prefix(n)))
            }
            row([])
        }
    }

    private func row(_ shown: [(page: SleepConsolidated.Page, label: String)]) -> some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            ForEach(Array(shown.enumerated()), id: \.offset) { _, chip in
                RunPageChipFace(page: chip.page, label: chip.label)
                    .help(Copy.RunCard.pageHelp(chip.label, chip.page.change ?? .updated, canShow: false))
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

// MARK: - The opened card

/// What the consolidation read and did, opened in place: a filter of the page changes, a card per source, the pages no
/// conversation stands behind, one quiet line for the questions, and — the one fold, at the very bottom — the run's own
/// details (engine, models, batches, plan usage or cost with its basis: ruling 12).
struct RunItemsView: View {
    let card: RunCardModel
    let items: SleepConsolidated?
    let failed: Bool
    let runDetail: SleepRunDetail?
    let cycleDetail: SleepCycleDetail?
    var showsUsage = true
    var onSelectEntity: ((String) -> Void)?
    var machines: [MachineStatus] = []
    var machineId: String? = nil
    /// Renders seed these (the snapshot); a live card opens on All with no page open.
    var initialFilter: SleepConsolidated.Change? = nil
    var initiallyOpenPage: String? = nil

    @State private var filter: SleepConsolidated.Change?
    @State private var openPage: String?
    @State private var showingAll: Set<String> = []
    @State private var questionsOpen = false
    @State private var detailsOpen = false
    @State private var seeded = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let items {
                content(items)
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
            .padding(.horizontal, Self.inset)
            if let replaced = runDetail?.replaced, replaced > 0 {
                note(Copy.Sensitive.replaced(replaced))
            }
        }
        .onAppear {
            guard !seeded else { return }
            seeded = true
            if let initialFilter { filter = initialFilter }
            if let initiallyOpenPage { openPage = initiallyOpenPage }
        }
    }

    /// Where the opened card's own words start: under the head's, inside the card's 8 pt edge.
    static var inset: CGFloat { CicadaTheme.spacingSM }

    @ViewBuilder
    private func content(_ items: SleepConsolidated) -> some View {
        let context = RunBodyContext(card: card, machines: machines, machineId: machineId, commits: items.commits,
                                     onSelectEntity: onSelectEntity)
        let counts = RunItemsModel.counts(items, machineId: machineId)
        let kinds = RunItemsModel.filterKinds(counts)
        // A machine change can leave the picked kind with no page, or hide the tabs: draw by what can be seen.
        let shownFilter = RunItemsModel.effectiveFilter(filter, kinds: kinds, counts: counts)
        let partial = RunItemsModel.countsArePartial(items, machineId: machineId)
        if partial { note(Copy.RunCard.countsPartial) }
        if !kinds.isEmpty { filterTabs(kinds, counts: counts, selected: shownFilter) }
        let layout = RunItemsModel.body(items, filter: shownFilter, machineId: machineId)
        ForEach(layout.sources) { source in
            RunSourceCard(source: source, context: context, openPage: $openPage, showingAll: $showingAll)
        }
        ForEach(layout.steps) { group in
            RunLeftoverCard(pages: group.pages, kind: .step(group.step), context: context,
                            openPage: $openPage, showingAll: $showingAll)
        }
        if !layout.leftover.isEmpty {
            RunLeftoverCard(pages: layout.leftover, kind: .undated, context: context,
                            openPage: $openPage, showingAll: $showingAll)
        }
        if !layout.unlisted.isEmpty {
            RunLeftoverCard(pages: layout.unlisted, kind: .unlisted, context: context,
                            openPage: $openPage, showingAll: $showingAll)
        }
        if layout.isEmpty { note(Copy.RunCard.nothingListed) }
        if machineId == nil { questions(items) }
        if items.truncated && !partial { note(Copy.RunCard.moreNotListed) }
    }

    /// All · New · Updated · Archived · Removed · Faded, with counts, only the kinds that happened (and none when one kind
    /// is all there is). All counts the pages that really changed; Faded is the trailing, quiet one — pages whose facts
    /// only lost confidence to silence, never in All. Single-select; a second tap returns to All (DR-45). Never the accent.
    private func filterTabs(_ kinds: [SleepConsolidated.Change], counts: [SleepConsolidated.Change: Int],
                            selected: SleepConsolidated.Change?) -> some View {
        var tabs: [TextTab<SleepConsolidated.Change>] = [
            TextTab(id: nil, label: Copy.RunCard.filterAll, count: RunItemsModel.changed(counts))
        ]
        for kind in kinds {
            tabs.append(TextTab(id: kind, label: Copy.RunCard.filterWord(kind), count: counts[kind]))
        }
        return TextTabs(tabs: tabs, selection: Binding(get: { selected }, set: { filter = $0; openPage = nil }))
            .accessibilityLabel(Copy.RunCard.filterLabel)
            .padding(.horizontal, Self.inset - CicadaTheme.scaled(2))
            .padding(.top, CicadaTheme.scaled(2))
    }

    /// One quiet line for the questions the read raised and settled; a click shows them, each opens in the Inbox. They
    /// are the Inbox's own, so no more than a line is spent on them here.
    @ViewBuilder
    private func questions(_ items: SleepConsolidated) -> some View {
        let counts = RunItemsModel.questionCounts(items)
        if let line = Copy.RunCard.questionsLine(raised: counts.raised, settled: counts.settled) {
            let rows = RunItemsModel.questions(items)
            VStack(alignment: .leading, spacing: 0) {
                QuestionsLine(line: line, isOpen: questionsOpen) {
                    let animation = RunCardMotion.current(reduceMotion: reduceMotion)
                    withAnimation(animation) { questionsOpen.toggle() }
                }
                if questionsOpen {
                    let all = showingAll.contains("questions")
                    let shown = all ? rows : Array(rows.prefix(RunBodyLimits.questions))
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(shown, id: \.question.id) { ConsolidatedQuestionRow(question: $0.question, settled: $0.settled) }
                        if rows.count > RunBodyLimits.questions {
                            TextButton(title: all ? Copy.RunCard.showFewer : Copy.RunCard.showAll(rows.count)) {
                                showingAll.formSymmetricDifference(["questions"])
                            }
                            .padding(.horizontal, CicadaTheme.scaled(8))
                        }
                    }
                    .transition(.opacity)
                }
            }
            .padding(.horizontal, CicadaTheme.scaled(2))
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(.horizontal, Self.inset)
            .frame(minHeight: CicadaTheme.scaled(DisclosureHeader.height), alignment: .leading)
    }

    /// The facts the head does not carry — the engine and models, the plan share or cost with its basis on hover (ruling
    /// 12), a scheduled catch-up — then the run's batches or the cycle's models. How long it read is the head's.
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

/// The questions line: its words, and "Show" / "Hide" on the line the pointer is on or that is open — never down it
/// at rest (less dense). No chevron.
private struct QuestionsLine: View {
    let line: String
    let isOpen: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(line)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
                Spacer(minLength: CicadaTheme.spacingSM)
                if hovering || isOpen {
                    Text(isOpen ? Copy.RunCard.hideQuestions : Copy.RunCard.showQuestions)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(hovering ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                }
            }
            .padding(.horizontal, CicadaTheme.scaled(8))
            .frame(minHeight: CicadaTheme.scaled(DisclosureHeader.height))
            .rowHoverFill(hovering: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel(line)
        .accessibilityValue(isOpen ? Copy.Lists.expanded : Copy.Lists.collapsed)
    }
}

// MARK: - A source's card

/// One source of the read, as the Queue draws a source: its real mark (24 pt) and its name, what it fed in a quiet count,
/// then the conversations it fed — five, then "All N" — each with its pages as chips under it.
struct RunSourceCard: View {
    let source: RunItemsModel.Source
    let context: RunBodyContext
    @Binding var openPage: String?
    @Binding var showingAll: Set<String>

    static var markSize: CGFloat { CicadaTheme.scaled(24) }
    static var gap: CGFloat { CicadaTheme.spacingSM }

    var body: some View {
        let all = showingAll.contains(source.id)
        let rows = all ? source.rows : Array(source.rows.prefix(RunBodyLimits.conversations))
        // A row draws its own mark only when it differs from the source's (a saved link's site, a call app) and only when
        // there is a real one to draw; a row with none has no slot, its title on the row's leading edge.
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: Self.gap) {
                StudyListCard.mark(source.origin, size: Self.markSize)
                Text(OriginIconography.label(for: source.origin))
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(Copy.RunCard.conversationsIn(source.rows.count))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .accessibilityElement(children: .combine)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(10)) {
                ForEach(rows) { row in
                    RunConversationRow(row: row, context: context, openPage: $openPage,
                                       showingAll: $showingAll)
                }
                if source.rows.count > RunBodyLimits.conversations {
                    TextButton(title: all ? Copy.RunCard.showFewer : Copy.RunCard.showAll(source.rows.count), inline: true) {
                        showingAll.formSymmetricDifference([source.id])
                    }
                }
            }
        }
        .softCard(ground: .nested, inset: .roomy, fillsWidth: true)
    }
}

/// One conversation: its mark (when it is not the source's own), its title, a quiet line (the machine's name when it is
/// not this one, the day when it is not the run's), and under it the pages it fed. The row opens the conversation in the
/// Reader.
struct RunConversationRow: View {
    let row: RunItemsModel.Row
    let context: RunBodyContext
    @Binding var openPage: String?
    @Binding var showingAll: Set<String>

    @Environment(ProvenanceRouter.self) private var reader: ProvenanceRouter?
    @Environment(Store.self) private var store: Store?
    @State private var hovering = false
    /// A saved link's own site icon, once the backend has served one (cached per site; a miss stays a miss).
    @State private var siteIcon: NSImage?

    private var c: SleepConsolidated.Conversation { row.conversation }
    private var markSide: CGFloat { CicadaTheme.scaled(16) }
    private var rowMark: RunItemsModel.RowMark? { RunItemsModel.rowMark(c) }
    /// The mark that really exists: a call app's, a family's bundled mark, or the site's fetched icon. Never a letter.
    private var hasMarkSlot: Bool {
        switch rowMark {
        case .callApp?: true
        case .site(let key)?: RunItemsModel.siteMarkDraws(site: key, favicon: siteIcon != nil)
        case nil: false
        }
    }

    private var meta: String? {
        let machine = context.machineId == nil ? MachinesStrip.deviceName(c.device, in: context.machines) : nil
        let day = c.timestamp.flatMap { context.card.isSameDay(as: $0) ? nil : SleepHistoryPresentation.dateText($0) }
        return RunItemsModel.rowMeta(machineName: machine, day: day)
    }

    var body: some View {
        let label = RunItemGroups.conversationLabel(c)
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
            Button {
                reader?.open(ReaderTarget(episode: c.id, knownTitle: c.title))
            } label: {
                HStack(spacing: CicadaTheme.scaled(8)) {
                    if hasMarkSlot { mark.frame(width: markSide, height: markSide) }
                    Text(label)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if let meta {
                        Text(meta)
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                .padding(.horizontal, CicadaTheme.scaled(6))
                .frame(minHeight: CicadaTheme.scaled(28))
                .rowHoverFill(hovering: hovering)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .onHover { hovering = $0 }
            .help(c.id)
            .accessibilityLabel(Copy.RunCard.openConversation(label))
            .task(id: "\(store?.bank ?? "")|\(c.id)") { await loadSiteIcon() }
            if !row.pages.isEmpty {
                RunPageChips(pages: row.pages, groupId: c.id, parent: .init(conversation: c.id), context: context,
                             openPage: $openPage, showingAll: $showingAll)
                    .padding(.leading, CicadaTheme.scaled(6) + (hasMarkSlot ? markSide + CicadaTheme.scaled(8) : 0))
            }
        }
    }

    private func loadSiteIcon() async {
        guard case .site(let key)? = rowMark, let store else { return }
        siteIcon = await SiteIconStore.shared.image(site: key, bank: store.bank, entity: nil, saved: .episode(c.id))
    }

    @ViewBuilder
    private var mark: some View {
        switch rowMark {
        case .site(let key)?:
            // The site's own icon or a bundled family mark; the monogram rung (`SiteIcon`'s fallback) is not drawn here.
            if let siteIcon {
                Image(nsImage: siteIcon).resizable().interpolation(.high).scaledToFit()
                    .clipShape(CicadaTheme.shape(CicadaTheme.scaled(SiteIconLayout.cornerRadius)))
                    .accessibilityHidden(true)
            } else if case .bundled(let name) = SiteIconLayout.rung(favicon: false, site: key) {
                LogoImage(name: name, size: markSide).accessibilityHidden(true)
            }
        case .callApp(let app)?:
            OriginMark(origin: app, size: markSide)
                .help(c.meeting?.app ?? "")
                .accessibilityLabel(c.meeting?.app ?? "")
        case nil:
            Color.clear
        }
    }
}

/// The pages no conversation of the read stands behind, under the step that changed them (owner 2026-11-24: "what
/// influenced this change?"): one card a step, named in plain words and wearing Cicada's own mark. Two more groups the
/// backend makes when it cannot say a step or a conversation: the pages a conversation past its list fed, and — only from
/// an older backend, which says neither — one card of every page.
struct RunLeftoverCard: View {
    enum Kind: Equatable {
        case step(SleepConsolidated.Step)
        case unlisted
        /// An older backend: neither a conversation nor a step is said for any page.
        case undated
    }

    let pages: [SleepConsolidated.Page]
    let kind: Kind
    let context: RunBodyContext
    @Binding var openPage: String?
    @Binding var showingAll: Set<String>

    static let unlistedGroupId = "unlisted"
    static let undatedGroupId = "undated"

    private var title: String {
        switch kind {
        case .step(let step): Copy.RunChange.stepTitle(step)
        case .unlisted: Copy.RunCard.unlistedTitle
        case .undated: Copy.RunCard.pagesTitle
        }
    }

    private var groupId: String {
        switch kind {
        case .step(let step): "step.\(step.rawValue)"
        case .unlisted: Self.unlistedGroupId
        case .undated: Self.undatedGroupId
        }
    }

    private var help: String {
        switch kind {
        case .step: Copy.RunChange.stepHelp
        case .unlisted: Copy.RunCard.unlistedHelp
        case .undated: ""
        }
    }

    private var parent: RunPageChangeModel.Parent {
        if case .step(let step) = kind { return .init(step: step) }
        return .none
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: RunSourceCard.gap) {
                if case .step = kind { OriginMark(origin: "cicada", size: RunSourceCard.markSize) }
                Text(title)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(Copy.RunCard.pagesIn(pages.count))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .help(help)
            .accessibilityElement(children: .combine)
            RunPageChips(pages: pages, groupId: groupId, parent: parent, context: context, openPage: $openPage,
                         showingAll: $showingAll)
        }
        .softCard(ground: .nested, inset: .roomy, fillsWidth: true)
    }
}

/// A conversation's (or a step group's) pages as a flowing set of chips, eight before "+N more"; the chip a click opened
/// shows what the read changed on it, in place, under the chips. `parent` is the card the chips sit under, so the opened
/// change never says again what that card already said.
struct RunPageChips: View {
    let pages: [SleepConsolidated.Page]
    let groupId: String
    var parent: RunPageChangeModel.Parent = .none
    let context: RunBodyContext
    @Binding var openPage: String?
    @Binding var showingAll: Set<String>

    @Environment(Store.self) private var store: Store?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private func key(_ page: SleepConsolidated.Page) -> String { "\(groupId)|\(page.id)" }

    private func commits(_ page: SleepConsolidated.Page) -> [String] {
        page.commits.isEmpty && context.commits.count == 1 ? context.commits : page.commits
    }

    var body: some View {
        let names = store?.entityNames ?? .empty
        let id = "chips.\(groupId)"
        let all = showingAll.contains(id)
        let shown = all ? pages : Array(pages.prefix(RunBodyLimits.chips))
        let open = shown.first { key($0) == openPage } ?? pages.first { key($0) == openPage }
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            FlowLayout(spacing: CicadaTheme.scaled(6)) {
                ForEach(shown) { page in
                    let label = RunItemGroups.pageLabel(page, names: names)
                    RunPageChip(page: page, label: label, canShowChange: !page.gone && !commits(page).isEmpty,
                                isOpen: key(page) == openPage) {
                        press(page)
                    }
                }
                if pages.count > RunBodyLimits.chips {
                    TextButton(title: all ? Copy.RunCard.showFewer : Copy.RunCard.moreOnRow(pages.count - shown.count),
                               inline: true) {
                        showingAll.formSymmetricDifference([id])
                    }
                }
            }
            if let open, !open.gone {
                RunPageChange(page: open, label: RunItemGroups.pageLabel(open, names: names), key: context.card.key,
                              parent: parent, onOpen: { context.onSelectEntity?(open.id) })
                    .id("\(context.card.id)|\(key(open))")
                    .transition(.opacity)
            }
        }
    }

    private func press(_ page: SleepConsolidated.Page) {
        guard !page.gone else { return }
        guard !commits(page).isEmpty else { context.onSelectEntity?(page.id); return }
        let animation = RunCardMotion.current(reduceMotion: reduceMotion)
        withAnimation(animation) { openPage = openPage == key(page) ? nil : key(page) }
    }
}

// MARK: - What the read changed on a page

// `RunPageChange` and its parts: `RunPageChangeView.swift`.

/// One question the read raised or settled; a click opens it in the Inbox.
private struct ConsolidatedQuestionRow: View {
    let question: SleepConsolidated.Question
    let settled: Bool
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
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(settled ? Copy.RunCard.questionSettledWord : Copy.RunCard.questionRaisedWord)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
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
