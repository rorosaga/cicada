import SwiftUI

/// Today / Needs you / Last read (design §6.3, R-IB9). Thin renderers over
/// `HomeFigures`: every number here is computed there and table-tested, so a
/// view can only choose where a number sits, never what it says. Each number
/// appears once and each is a link to the page that owns it; nothing here is a
/// trigger (the waiting line opens the Sleep page — never a Consolidate, G125
/// R10 in steady state).
///
/// In Direction D's list grammar (DS-3b): a `SectionLabel` over one grouped
/// block, 36 pt rows, links in `accentText` (R-HS6). F-09: Today is one row to
/// Sources (R-HO11), Needs you the Inbox's icon rows with *Open Inbox* (R-HO12).
///
/// Owner 2026-10-14 ("Graduate + Needs you first"; Home review #5, #8, #9): `HomeView` places the blocks in the
/// order `HomeArrangement` gives; a line with one destination is a whole-row button (no trailing "Sleep ›" — the
/// waiting line opens Sleep, Last read opens that read in Sleep's Details); an empty block is its label and a short
/// note, never a card holding one grey line (DR-37); and when all three are empty, one block says so once.
///
/// Internal, not `private`: `HomeView.swift` composes them from another file.

// MARK: - The block and its lines

/// DR-20, DR-37 — a Home section: its `SectionLabel` above one grouped block (`glassCard()`:
/// `bgFocus`, `cornerRadius`, a resting ring), 4 pt inside so a row's hover fill sits concentric
/// (DR-12). It replaced the old Home card, whose label sat inside a padded `surface` card (P1,
/// R-HS6).
struct HomeBlock<Content: View>: View {
    let title: String
    /// F-09 — a block may carry one link at its label's right (Needs you's *Open Inbox*, DR-5 use 5).
    var linkTitle: String? = nil
    var linkAction: (() -> Void)? = nil
    /// Owner 2026-10-14 (review #8, DR-37) — set when the block has nothing to show: the label reads
    /// "Needs you · nothing right now" and no card is drawn under it.
    var emptyNote: String? = nil
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(HomeLayout.labelGap)) {
            HStack(alignment: .firstTextBaseline) {
                SectionLabel(emptyNote.map { Copy.homeEmptyLabel(title, note: $0) } ?? title)
                Spacer(minLength: CicadaTheme.spacingSM)
                if let linkTitle, let linkAction { InlineLink(title: linkTitle, action: linkAction) }
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            if emptyNote == nil {
                VStack(alignment: .leading, spacing: 0) { content }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(CicadaTheme.scaled(HomeLayout.blockInset))
                    .glassCard()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Review #5, #9 — a line with one destination is one button: the whole 36 pt row, a `bgHover` fill on hover (DR-48),
/// a trailing chevron, and its hover says where it goes (DR-69). Never a trigger.
struct HomeRowButton<Content: View>: View {
    let help: String
    /// Words in place of the chevron ("Show ›"), drawn as a text button's label: the row itself is the button.
    var trailingLabel: String? = nil
    let action: () -> Void
    @ViewBuilder let content: Content

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HomeLine {
                content
                Spacer(minLength: CicadaTheme.spacingSM)
                if let trailingLabel {
                    Text(trailingLabel)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                } else {
                    Image(systemName: "chevron.right")
                        .font(CicadaTheme.icon(.list))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .accessibilityHidden(true)
                }
            }
            .rowHoverFill(hovering: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(help)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

/// Review #8 (DR-37, DR-38, DR-50's content rule) — Today, Needs you and Last read all empty: one block with the
/// truthful line and at most one action, instead of three cards of "nothing". Not `EmptyStateView` itself: that is a
/// whole page's state, with art and a primary, and Home has no primary (R-HS3).
struct HomeEmptyBlock: View {
    @Environment(IntakeRouter.self) private var intake

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            // One icon (2026-10-22): the worm stays in the study room (DR-13), never on Home's working surface.
            Image(systemName: "tray.and.arrow.down")
                .font(CicadaTheme.font(size: 20))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(Copy.homeNothingYetTitle)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                Text(Copy.homeNothingYetLine)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.intakeChooseFile, size: .compact) { intake.present(from: .home) }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
        .accessibilityElement(children: .contain)
    }
}

/// One line in a block (DR-34): the list row's 36 pt from `RowMetrics`, 10 pt in.
struct HomeLine<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(10)) { content }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
    }
}

/// "—" with a reason on hover: a value that is not known yet is said to be
/// unknown, never guessed (R-A14).
private struct HomeUnknown: View {
    var body: some View {
        Text(verbatim: "—")
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .help(Copy.homeLoading)
            .accessibilityLabel(Copy.homeLoading)
    }
}

// MARK: - Today

struct TodaySection: View {
    let today: Date
    let gettingStartedVisible: Bool
    /// Review #8 — nothing captured and nothing waiting: the label says it, no card.
    var empty = false
    @Binding var selectedTab: AppTab

    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(MessagesWatcher.self) private var messages: MessagesWatcher?

    var body: some View {
        let figures = HomeFigures.today(store.sourcesOverview.value, today: today)
        HomeBlock(title: Copy.homeToday, emptyNote: empty ? Copy.homeTodayNothingYet : nil) {
            captured(figures)
            if HomeLayout.showsWaitingInToday(gettingStartedVisible: gettingStartedVisible,
                                              hasRunBefore: hasRunBefore) {
                waiting
            }
        }
    }

    /// The first read is what Getting started's read row is about; before its
    /// status lands, a recorded last Sleep is the same fact from `/status`.
    private var hasRunBefore: Bool {
        sleepVM.status?.debt.hasRunBefore ?? (store.status.value?.lastSleepAt != nil)
    }

    @ViewBuilder
    private func captured(_ figures: HomeToday) -> some View {
        switch figures.captured {
        case nil:
            HomeLine { HomeUnknown() }
        case 0?:
            HomeLine {
                Text(Copy.homeNothingCapturedToday)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        case let n?:
            // F-09 (R-HO11) — one row, one link: the Sources page owns what came in.
            HomeRowButton(help: Copy.homeCapturedHelp, action: { selectedTab = .sources }) {
                Text(Copy.homeCapturedToday(n))
                    .font(CicadaTheme.bodyFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary)
                if !figures.origins.isEmpty {
                    HStack(spacing: CicadaTheme.scaled(6)) {
                        Text(Copy.homeMostly)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                        ForEach(Array(figures.origins.enumerated()), id: \.element.sourceId) { index, chip in
                            if index > 0 {
                                Text(Copy.Inbox.dot).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                            }
                            // DR-52 — the service's real mark beside its name.
                            OriginMark(origin: chip.mark, size: CicadaTheme.scaled(14))
                            Text(Copy.homeOriginCount(chip.label, chip.count))
                                .font(CicadaTheme.metaFont)
                                .monospacedDigit()
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                        }
                    }
                }
            }
            .accessibilityLabel(Copy.homeTodayAccessibility(n, origins: figures.origins.map { ($0.label, $0.count) }))
        }
    }

    /// Review #5/#9 — the whole line opens the Sleep page, the page that owns the queue; never a Sleep trigger
    /// (G125 R10), and no trailing "Sleep ›" beside it.
    private var waiting: some View {
        let status = store.status.value
        return HomeRowButton(help: Copy.homeOpenSleepHelp, action: { selectedTab = .sleep }) {
            // Sleep's glyph, never the worm: the study room is the one illustration (DR-13, not on a row).
            Image(systemName: "moon")
                .font(CicadaTheme.icon(.list))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
            switch status?.episodes.unprocessed {
            case nil:
                HomeUnknown()
            case 0?:
                Text(Copy.homeNothingWaiting)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            case let n?:
                Text(Copy.homeWaiting(n))
                    .font(CicadaTheme.bodyFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary)
                // G179 — the ticked Messages conversations among them, as stacked profile bubbles (hover names one).
                MessageBubbleStack(size: 18, interactive: false)
            }
        }
        .task(id: store.status.value?.episodes.unprocessed) { await messages?.refreshWaiting() }
    }
}

// MARK: - Needs you

/// Ruling 48 (1), (2) — owner 2026-10-28: the questions live on Home (and on each page), the Inbox off the rail.
/// *Catch me up* stands apart as its own block (`07-home-b`); under it each row leads with the page it is about — its
/// face, logo or type glyph (DR-48: a picture or a glyph, the kind moves to `.help`) — the question in plain words with
/// its reason, and a link to the page (`06-home-a`). One row per page, the pages the person uses most first (the
/// server's order, `page_use`). *All N questions* opens the full list as Home's sub-view — never a fold (part 17).
/// Drawn from the Store's disk-hydrated snapshot: Home never waits on `GET /inbox`.
struct NeedsYouSection: View {
    /// Review #8 — the inbox is loaded and empty: "Needs you · nothing right now", no card.
    var empty = false
    @Binding var selectedTab: AppTab
    let openPage: (String) -> Void
    let startCatchup: ([String]) -> Void

    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router

    var body: some View {
        let items = store.visibleInbox
        // DR-58 — an age is computed when read, never stored.
        let figures = HomeQuestions.figures(items, now: .now)
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(HomeLayout.blockGap)) {
            if !figures.catchUp.isEmpty {
                CatchupBlock(questions: figures.catchUp.count, pages: figures.catchUpPages) {
                    startCatchup(figures.catchUp)
                }
            }
            HomeBlock(title: figures.rows.isEmpty ? Copy.homeNeedsYouCount(figures.total)
                          : Copy.Catchup.pagesWithAQuestion,
                      linkTitle: figures.total > 0 ? Copy.Catchup.allQuestions(figures.total) : nil,
                      linkAction: { selectedTab = .inbox }, emptyNote: empty ? Copy.homeNeedsYouNothing : nil) {
                if figures.rows.isEmpty {
                    // Only the list's own kinds wait (an agent's request, the link review): the list says what they are.
                    HomeRowButton(help: Copy.Catchup.allHelp, action: { selectedTab = .inbox }) {
                        Text(figures.total > 0 ? Copy.Catchup.allQuestions(figures.total) : Copy.homeNothingNeedsYou)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                } else {
                    ForEach(figures.rows) { row in
                        HomeQuestionRow(row: row, openPage: openPage) {
                            router.pendingInboxItem = row.id
                            selectedTab = .inbox
                        }
                    }
                }
            }
        }
    }
}

/// Ruling 48 (1) — *Catch me up*, its own block above the questions (`07-home-b`): the chat glyph, what it will ask,
/// and *Start* — a `NeutralButton`, never the accent (Home has no primary, DR-40). The same session is one sentence
/// away in any agent with Cicada, and the line says so.
struct CatchupBlock: View {
    let questions: Int
    let pages: Int
    let start: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            Image(systemName: "bubble.left")
                .font(CicadaTheme.icon(.list))
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(36), height: CicadaTheme.scaled(36))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgOption))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(Copy.Catchup.title)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                Text(Copy.Catchup.blockLine(questions: questions, pages: pages))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.Catchup.start, size: .compact, help: Copy.Catchup.startHelp, action: start)
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
        .accessibilityElement(children: .contain)
    }
}

/// One page with a question (`06-home-a`'s row): the page's picture, the question in plain words, its reason and the
/// page as a link, and the question's age. The row opens the question in the full list; the link opens the page.
struct HomeQuestionRow: View {
    let row: HomeQuestions.Row
    let openPage: (String) -> Void
    let open: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: open) {
            HStack(alignment: .center, spacing: CicadaTheme.scaled(10)) {
                picture
                VStack(alignment: .leading, spacing: 2) {
                    Text(row.question)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: CicadaTheme.scaled(4)) {
                        if let reason = row.reason, !reason.isEmpty {
                            Text(reason)
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                                .truncationMode(.tail)
                        }
                        if !row.entityId.isEmpty {
                            if row.reason?.isEmpty == false {
                                Text(Copy.Inbox.dot).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                            }
                            InlineLink(title: row.entityName, help: Copy.Catchup.openPage(row.entityName)) {
                                openPage(row.entityId)
                            }
                            .font(CicadaTheme.metaFont)
                            .fixedSize()
                        }
                        if row.onPage > 1 {
                            Text(Copy.Inbox.dot).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                            Text(Copy.Catchup.moreOnPage(row.onPage))
                                .font(CicadaTheme.metaFont)
                                .monospacedDigit()
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .fixedSize()
                        }
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(row.age)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(row.ageHelp)
                Image(systemName: "chevron.right")
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .padding(.vertical, CicadaTheme.scaled(6))
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
            .rowHoverFill(hovering: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.Catchup.answerHelp + " · " + row.kind.label)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }

    /// DR-48 — a picture or a glyph, never both: the page's own face, logo or type glyph; a question with no page
    /// carries its kind's glyph.
    @ViewBuilder
    private var picture: some View {
        if row.entityId.isEmpty {
            KindGlyph(kind: row.kind)
                .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
        } else {
            EntityPicture(id: row.entityId, name: row.entityName, type: row.entityType ?? .concept, size: 28)
        }
    }
}

// MARK: - Needs your browser (G166)

/// Its own block, not a line inside Needs you (whose count is the Inbox's): the saved pages whose sites Cicada's reader
/// could not read and the person has not allowed yet, with up to three of those sites' icons. It links to the
/// Sources page, which owns the number (D6); nothing here asks or reads anything. Hidden at zero and once every
/// listed site is allowed.
struct ReadingSitesSection: View {
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(ReadingSitesCache.self) private var cache

    var body: some View {
        Group {
            if let figures = HomeReadingLine.figures(cache.value) {
                HomeBlock(title: Copy.Reading.homeBlockTitle, linkTitle: Copy.Reading.homeOpenReading,
                          linkAction: open) {
                    Button(action: open) {
                        HomeLine {
                            HStack(spacing: -CicadaTheme.scaled(4)) {
                                ForEach(figures.sites) { site in
                                    SiteIcon(site: site.site, label: site.label, size: .inline)
                                }
                            }
                            Text(Copy.Reading.homePagesNeedBrowser(figures.count))
                                .font(CicadaTheme.bodyFont)
                                .foregroundStyle(CicadaTheme.textPrimary)
                            Spacer(minLength: 0)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.cicadaPlain)
                }
            }
        }
        .task(id: store.sources.loadedAt) { await cache.refresh() }
    }

    private func open() { router.open(.readingInBrowser) }
}

// MARK: - Last read

struct LastReadSection: View {
    /// Review #8 — no read ever ran: "Last time Cicada read · not yet", no card.
    var empty = false
    @Binding var selectedTab: AppTab

    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(AppRouter.self) private var router

    var body: some View {
        HomeBlock(title: Copy.homeLastRead, emptyNote: empty ? Copy.homeLastReadNotYet : nil) {
            switch HomeFigures.lastRead(sleepVM.history, loaded: sleepVM.historyLoaded,
                                        failed: sleepVM.historyFailed,
                                        hasRunBefore: sleepVM.status?.debt.hasRunBefore
                                            ?? store.status.value.map { $0.lastSleepAt != nil },
                                        lastSleepAt: store.status.value?.lastSleepAt) {
            case .loading:
                // Owner 2026-10-14 — words, not a bare "—": a box that is only a dash reads as broken.
                HomeLine {
                    Text(Copy.homeLastReadLoading)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            case .failed:
                HomeRowButton(help: Copy.homeLastReadHelp, action: openDetails) {
                    Text(Copy.homeLastReadFailed)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            case .never:
                HomeLine {
                    Text(Copy.homeNothingReadYet)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            case .entry(let entry):
                read(entry)
            case .earlier(let at):
                // Off the history page: the day the status gives, and the page
                // that owns the rest — never counts this block did not read.
                HomeRowButton(help: Copy.homeLastReadHelp, action: openDetails) {
                    if let when = at.flatMap({ HomeFigures.when($0) }) {
                        Text(when)
                            .font(CicadaTheme.bodyFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textPrimary)
                    } else {
                        Text(Copy.homeLastReadEarlier)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                }
            }
        }
    }

    private func read(_ entry: SleepHistoryEntry) -> some View {
        let chips = HomeFigures.chips(entry, nodes: store.graph.value?.nodes ?? [])
        return VStack(alignment: .leading, spacing: 0) {
            HomeRowButton(help: Copy.homeLastReadHelp, action: openDetails) {
                Text(HomeFigures.lastReadLine(entry))
                    .font(CicadaTheme.bodyFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            if !chips.shown.isEmpty {
                // DR-44 — the one pill, with the page type's dot inside it; a click opens the graph.
                HStack(spacing: CicadaTheme.scaled(6)) {
                    ForEach(chips.shown, id: \.id) { chip in
                        Button {
                            selectedTab = .graph
                            graphVM.revealEntity(id: chip.id)
                        } label: {
                            // Review #5 — the 18 pt pill (DR-44) inside a 24 pt hit frame.
                            Tag(text: chip.name, dot: CicadaTheme.entityColor(for: chip.type))
                                .frame(minHeight: CicadaTheme.scaled(HomeTargets.tagHitHeight))
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.cicadaPlain)
                        .help(Copy.homeShowOnGraph(chip.name))
                    }
                    if chips.more > 0 {
                        Text(Copy.homeMoreChips(chips.more))
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                .padding(.horizontal, CicadaTheme.scaled(10))
                .padding(.bottom, CicadaTheme.spacingXS)
            }
        }
    }

    /// Review #9 — Last read opens *that read* in the Sleep page's Details, not the page again.
    private func openDetails() { router.routeToSleepDetails(.lastCycle) }
}
