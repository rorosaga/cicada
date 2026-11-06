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
                    // ROR-118 (round 1, Home) — the chevron answers the pointer only; a resting row is its words.
                    Image(systemName: "chevron.right")
                        .font(CicadaTheme.icon(.list))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .opacity(hovering ? 1 : 0)
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

/// ROR-118 (round 1, Home) — Today and Last read are not cards: their rows stand on the window, one quiet list under
/// the lead question, so the page has one card that leads and the rest is what follows it (restraint).
struct HomePulse<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(HomeLayout.pulseGap)) { content }
            .frame(maxWidth: .infinity, alignment: .leading)
            // The rows' own 10 pt inset plus this 6 puts their glyphs on the lead card's 16 pt edge.
            .padding(.horizontal, CicadaTheme.scaled(6))
    }
}

/// One glyph style for every pulse row (ROR-118): a neutral SF Symbol on a 28 pt `bgOption` tile — never an emoji, a
/// favicon or a coloured dot standing in for it (DR-5, DR-50's one-icon rule).
struct HomeGlyphTile: View {
    let systemName: String

    var body: some View {
        Image(systemName: systemName)
            .font(CicadaTheme.icon(.list))
            .foregroundStyle(CicadaTheme.textSecondary)
            .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
            .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgOption))
            .accessibilityHidden(true)
    }
}

/// A link that is not blue (ROR-118): a page's name or "All N questions" in the secondary text colour, primary on hover,
/// inside `InlineLink`'s 28 pt layout-neutral hit frame. The accent stays for what the person is asked to do.
struct QuietLink: View {
    let title: String
    var help: String? = nil
    var chevron = false
    let action: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(3)) {
                Text(title)
                    .font(CicadaTheme.metaMediumFont)
                    .monospacedDigit()
                if chevron {
                    Image(systemName: "chevron.right")
                        .font(CicadaTheme.captionFont)
                        .accessibilityHidden(true)
                }
            }
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .modifier(InlineLinkTarget(hovering: hovering))
        }
        .buttonStyle(.cicadaPlain)
        .help(help ?? title)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
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

/// ROR-118 (round 1, Home) — Today is two quiet rows, no card and no label: what came in (the busiest origins as their
/// real marks, names and counts on hover) and what waits to be read. The glyphs are one style (`HomeGlyphTile`).
struct TodaySection: View {
    let today: Date
    let gettingStartedVisible: Bool
    /// Review #8 — nothing captured and nothing waiting: the label says it, no card.
    var empty = false
    @Binding var selectedTab: AppTab

    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(MessagesWatcher.self) private var messages: MessagesWatcher?
    @Environment(AwaySyncTracker.self) private var awaySync: AwaySyncTracker?

    var body: some View {
        let figures = HomeFigures.today(store.sourcesOverview.value, today: today)
        if empty && awaySync?.view == nil {
            HomeBlock(title: Copy.homeToday, emptyNote: Copy.homeTodayNothingYet) { EmptyView() }
        } else {
            HomePulse {
                captured(figures)
                if HomeLayout.showsWaitingInToday(gettingStartedVisible: gettingStartedVisible,
                                                  hasRunBefore: hasRunBefore) {
                    waiting
                }
                if let sync = awaySync?.view { syncing(sync) }
            }
        }
    }

    /// G229 — what this Mac is still syncing after it was closed, under what waits: the same words as the Sleep page's
    /// line, a source that could not be read in its `warning` clause (DR-7). The row opens Sleep, where each failure's
    /// fix is said in full.
    private func syncing(_ sync: MachineAwaySync) -> some View {
        HomeRowButton(help: Copy.AwaySync.openSleepHelp, action: { selectedTab = .sleep }) {
            HomeGlyphTile(systemName: sync.isReading ? "arrow.triangle.2.circlepath" : "checkmark")
            let failed = AwaySyncWords.failures(sync).map(\.lead).joined(separator: " ")
            (Text(AwaySyncWords.line(sync)).foregroundStyle(CicadaTheme.textSecondary)
             + Text(verbatim: failed.isEmpty ? "" : " " + failed).foregroundStyle(CicadaTheme.warning))
                .font(CicadaTheme.bodyFont)
                .monospacedDigit()
                .lineLimit(2)
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
            HomeLine { HomeGlyphTile(systemName: "tray.and.arrow.down"); HomeUnknown() }
        case 0?:
            HomeLine {
                HomeGlyphTile(systemName: "tray.and.arrow.down")
                Text(Copy.homeNothingCapturedToday)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        case let n?:
            // F-09 (R-HO11) — one row, one link: the Sources page owns what came in.
            HomeRowButton(help: Copy.homeCapturedHelp, action: { selectedTab = .sources }) {
                HomeGlyphTile(systemName: "tray.and.arrow.down")
                Text(Copy.homeCapturedToday(n))
                    .font(CicadaTheme.bodyFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary)
                if !figures.origins.isEmpty {
                    // DR-52 amended (§9, 2026-11-06) — on Home the busiest origins are their real marks alone, in one
                    // row of one size; each one's name and count is its hover, and the row's accessibility label.
                    HStack(spacing: CicadaTheme.scaled(6)) {
                        ForEach(figures.origins, id: \.sourceId) { chip in
                            OriginMark(origin: chip.mark, size: CicadaTheme.scaled(16))
                                .help(Copy.homeOriginCount(chip.label, chip.count))
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
            HomeGlyphTile(systemName: "moon")
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
/// ROR-118 (round 1, Home): ONE question leads — the page the person uses most, its picture, the question in 17 pt and
/// its reason in 14 — with *Catch me up* (the chat over all of them) and *All N questions* in the card's foot, so the
/// rest is one click away and no two rows repeat each other's copy. A row still opens that question in the list; the
/// page's name opens the page. Drawn from the Store's disk-hydrated snapshot: Home never waits on `GET /inbox`.
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
        if empty {
            HomeBlock(title: Copy.homeNeedsYouCount(figures.total), emptyNote: Copy.homeNeedsYouNothing) { EmptyView() }
        } else if let lead = figures.rows.first {
            LeadQuestionCard(row: lead, total: figures.total, catchUp: figures.catchUp, pages: figures.catchUpPages,
                             openPage: openPage, startCatchup: startCatchup,
                             open: {
                                 router.pendingInboxItem = lead.id
                                 selectedTab = .inbox
                             },
                             openAll: { selectedTab = .inbox })
        } else {
            // Only the list's own kinds wait (an agent's request, the link review): the list says what they are.
            HomeBlock(title: Copy.homeNeedsYouCount(figures.total), emptyNote: nil) {
                HomeRowButton(help: Copy.Catchup.allHelp, action: { selectedTab = .inbox }) {
                    Text(figures.total > 0 ? Copy.Catchup.allQuestions(figures.total) : Copy.homeNothingNeedsYou)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
    }
}

/// The lead question (ROR-118, round 1; `06-home-a`'s row grown into the page's one card): the page's picture
/// (DR-48: a face, logo or initials — nothing when it has none, never a type glyph), the question in `headingFont`, its
/// reason in `bodyFont` secondary, the page's name and the question's age on a meta line, and in the foot *Catch me up*
/// — a `NeutralButton`, never the accent (Home has no primary, DR-40), its hover saying the same session is one sentence
/// away in any agent with Cicada — and *All N questions*.
struct LeadQuestionCard: View {
    let row: HomeQuestions.Row
    let total: Int
    let catchUp: [String]
    let pages: Int
    let openPage: (String) -> Void
    let startCatchup: ([String]) -> Void
    let open: () -> Void
    let openAll: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var pictureSlot: CGFloat { CicadaTheme.scaled(HomeLayout.leadPicture) + CicadaTheme.scaled(14) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button(action: open) {
                HStack(alignment: .top, spacing: CicadaTheme.scaled(14)) {
                    if !row.entityId.isEmpty {
                        EntityPicture(id: row.entityId, name: row.entityName, type: row.entityType ?? .unknown,
                                      size: HomeLayout.leadPicture, collapsesWhenEmpty: true)
                    }
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                        Text(row.question)
                            .font(CicadaTheme.headingFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(3)
                            .fixedSize(horizontal: false, vertical: true)
                            .multilineTextAlignment(.leading)
                        if let reason = row.reason, !reason.isEmpty {
                            Text(reason)
                                .font(CicadaTheme.bodyFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(3)
                                .fixedSize(horizontal: false, vertical: true)
                                .multilineTextAlignment(.leading)
                        }
                    }
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .help(Copy.Catchup.answerHelp + " · " + row.kind.label)
            .accessibilityAddTraits(.isHeader)

            meta
                .padding(.leading, row.entityId.isEmpty ? 0 : pictureSlot)
                .padding(.top, CicadaTheme.scaled(2))

            HStack(spacing: CicadaTheme.spacingMD) {
                if !catchUp.isEmpty {
                    NeutralButton(title: Copy.Catchup.title, size: .compact,
                                  help: Copy.Catchup.blockLine(questions: catchUp.count, pages: pages)) {
                        startCatchup(catchUp)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if total > 0 {
                    QuietLink(title: Copy.Catchup.allQuestions(total), help: Copy.Catchup.allHelp, chevron: true,
                              action: openAll)
                }
            }
            .padding(.top, CicadaTheme.scaled(14))
        }
        .padding(CicadaTheme.scaled(HomeLayout.leadInset))
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
        .accessibilityElement(children: .contain)
    }

    /// The page's name (opens the page), how many questions it holds when more than this one, and the question's age.
    private var meta: some View {
        HStack(spacing: CicadaTheme.scaled(4)) {
            if !row.entityId.isEmpty {
                QuietLink(title: row.entityName, help: Copy.Catchup.openPage(row.entityName)) { openPage(row.entityId) }
                    .fixedSize()
            }
            if row.onPage > 1 {
                dot
                Text(Copy.Catchup.moreOnPage(row.onPage))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize()
            }
            // ROR-118 (DR-38) — a row with no known age says nothing there, not a dash.
            if row.age != "—" {
                if !row.entityId.isEmpty || row.onPage > 1 { dot }
                Text(row.age)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(row.ageHelp)
            }
        }
    }

    private var dot: some View {
        Text(Copy.Inbox.dot).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
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

/// ROR-118 (round 1, Home) — the newest Sleep commit as one row in the pulse list (no card, no label: "Last read" is its
/// own first words), its pages a line of plain names under it — no pill, no coloured dot — each opening the graph.
struct LastReadSection: View {
    /// Review #8 — no read ever ran: "Last time Cicada read · not yet", no card.
    var empty = false
    @Binding var selectedTab: AppTab

    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(AppRouter.self) private var router

    var body: some View {
        if empty {
            HomeBlock(title: Copy.homeLastRead, emptyNote: Copy.homeLastReadNotYet) { EmptyView() }
        } else {
            HomePulse { content }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch HomeFigures.lastRead(sleepVM.history, loaded: sleepVM.historyLoaded,
                                    failed: sleepVM.historyFailed,
                                    hasRunBefore: sleepVM.status?.debt.hasRunBefore
                                        ?? store.status.value.map { $0.lastSleepAt != nil },
                                    lastSleepAt: store.status.value?.lastSleepAt) {
        case .loading:
            // Owner 2026-10-14 — words, not a bare "—": a box that is only a dash reads as broken.
            HomeLine {
                HomeGlyphTile(systemName: "clock")
                Text(Copy.homeLastReadLoading)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        case .failed:
            HomeRowButton(help: Copy.homeLastReadHelp, action: openDetails) {
                HomeGlyphTile(systemName: "clock")
                Text(Copy.homeLastReadFailed)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        case .never:
            HomeLine {
                HomeGlyphTile(systemName: "clock")
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
                HomeGlyphTile(systemName: "clock")
                if let when = at.flatMap({ HomeFigures.when($0) }) {
                    lastReadWords(when)
                } else {
                    Text(Copy.homeLastReadEarlier)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
    }

    /// "Last read" in the secondary colour, then the figures in the primary.
    private func lastReadWords(_ figures: String) -> some View {
        (Text(Copy.homeLastReadShort + "  ").foregroundStyle(CicadaTheme.textSecondary)
         + Text(figures).foregroundStyle(CicadaTheme.textPrimary))
            .font(CicadaTheme.bodyFont)
            .monospacedDigit()
            .lineLimit(1)
    }

    private func read(_ entry: SleepHistoryEntry) -> some View {
        let chips = HomeFigures.chips(entry, nodes: store.graph.value?.nodes ?? [])
        return VStack(alignment: .leading, spacing: 0) {
            HomeRowButton(help: Copy.homeLastReadHelp, action: openDetails) {
                HomeGlyphTile(systemName: "clock")
                lastReadWords(HomeFigures.lastReadLine(entry))
            }
            if !chips.shown.isEmpty {
                // Plain names under the row's words (its 10 pt inset + the 28 pt glyph + 10 pt gap); a click opens the
                // graph on that page. Never a pill with a coloured dot (ROR-118: one style of mark on this page).
                HStack(spacing: CicadaTheme.scaled(4)) {
                    ForEach(Array(chips.shown.enumerated()), id: \.element.id) { index, chip in
                        Button {
                            selectedTab = .graph
                            graphVM.revealEntity(id: chip.id)
                        } label: {
                            Text(chip.name + (index < chips.shown.count - 1 || chips.more > 0 ? "," : ""))
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
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
                    Spacer(minLength: 0)
                }
                .padding(.leading, CicadaTheme.scaled(10 + 28 + 10))
            }
        }
    }

    /// Review #9 — Last read opens *that read* in the Sleep page's Details, not the page again.
    private func openDetails() { router.routeToSleepDetails(.lastCycle) }
}
