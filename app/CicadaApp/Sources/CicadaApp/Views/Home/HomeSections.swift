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
            // The rows' own 10 pt inset plus this 8 puts their glyphs on the lead card's 18 pt text edge.
            .padding(.horizontal, CicadaTheme.scaled(8))
    }
}

/// One glyph style for every pulse row (ROR-118; round 2 drops the tile): a neutral SF Symbol in a 20 pt column, tertiary
/// ink, no box behind it — never an emoji, a favicon or a coloured dot standing in for it (DR-5, DR-50's one-icon rule),
/// so every row's words start on one edge.
struct HomeGlyphTile: View {
    let systemName: String

    var body: some View {
        Image(systemName: systemName)
            .font(CicadaTheme.font(size: 15))
            .foregroundStyle(CicadaTheme.textTertiary)
            .frame(width: CicadaTheme.scaled(HomeLayout.rowGlyph), height: CicadaTheme.scaled(HomeLayout.rowGlyph))
            .accessibilityHidden(true)
    }
}

/// The words of a pulse row — one size, one ink on every row (round 2: the figure was white on one row and grey on
/// the next).
private struct HomeRowWords: ViewModifier {
    func body(content: Content) -> some View {
        content
            .font(CicadaTheme.bodyFont)
            .monospacedDigit()
            .foregroundStyle(CicadaTheme.textSecondary)
            .lineLimit(1)
    }
}

private extension View {
    func homeRowWords() -> some View { modifier(HomeRowWords()) }
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

/// ROR-118 (round 3, Home) — Today is one line, no card and no label: what came in and what waits, each figure a link
/// (the busiest origins are the first one's hover).
struct TodaySection: View {
    let today: Date
    let gettingStartedVisible: Bool
    /// Review #8 — nothing captured and nothing waiting: the label says it, no card.
    var empty = false
    /// Round 4 — the newest read joins this line (one status line, not three blocks): set by `HomeView` when Last read
    /// sits right under Today and both have something to say.
    var includesLastRead = false
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
                statLine(figures)
                if let sync = awaySync?.view { syncing(sync) }
            }
        }
    }

    /// ROR-118 round 4 — what came in, what waits and when memory was last read are ONE centred line under the question,
    /// each a link to the page that owns it; figures in the primary ink, words in the secondary, so the line reads as
    /// the page's one status and not as three footnotes.
    private func statLine(_ figures: HomeToday) -> some View {
        HStack(spacing: CicadaTheme.scaled(HomeLayout.statGap)) {
            captured(figures)
            if HomeLayout.showsWaitingInToday(gettingStartedVisible: gettingStartedVisible, hasRunBefore: hasRunBefore) {
                statDot
                waiting
            }
            if includesLastRead {
                statDot
                LastReadSegment(selectedTab: $selectedTab, joinsStatusLine: true)
            }
        }
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .center)
    }

    private var statDot: some View {
        Text(Copy.Inbox.dot).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
            .accessibilityHidden(true)
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
            HomeUnknown()
        case 0?:
            Text(Copy.homeNothingCapturedToday)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        case let n?:
            // F-09 (R-HO11) — one link, one page: Sources owns what came in. The busiest origins are its hover (names
            // and counts) and its accessibility label, not a strip of marks beside it.
            HomeStatLink(figure: UsageFormat.count(n), words: Copy.homeCapturedWords,
                         help: ([Copy.homeCapturedHelp] + figures.origins.map { Copy.homeOriginCount($0.label, $0.count) })
                            .joined(separator: " · "),
                         label: Copy.homeTodayAccessibility(n, origins: figures.origins.map { ($0.label, $0.count) }),
                         action: { selectedTab = .sources })
        }
    }

    /// Review #5/#9 — the figure opens the Sleep page, the page that owns the queue; never a Sleep trigger (G125 R10).
    @ViewBuilder
    private var waiting: some View {
        switch store.status.value?.episodes.unprocessed {
        case nil:
            HomeUnknown()
        case 0?:
            Text(Copy.homeNothingWaiting)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        case let n?:
            HomeStatLink(figure: UsageFormat.count(n), words: Copy.homeWaitingWords, help: Copy.homeOpenSleepHelp,
                         label: Copy.homeWaiting(n), action: { selectedTab = .sleep }) {
                // G179 — the ticked Messages conversations among them, as stacked profile bubbles (hover names one).
                MessageBubbleStack(size: 18, interactive: false)
            }
            .task(id: n) { await messages?.refreshWaiting() }
        }
    }
}

/// ROR-118 round 3 — a figure and its noun as one link: the figure in the primary ink at medium weight, the noun in the
/// secondary, both primary under the pointer, inside `InlineLink`'s layout-neutral hit frame. What `TodaySection`'s rows
/// were (a glyph, grey words, a hover chevron) is this one line.
struct HomeStatLink<Trailing: View>: View {
    /// Round 4 — words before the figure ("Last read Today 1:54 PM"): the secondary ink, like the words after it.
    var lead = ""
    let figure: String
    var words = ""
    let help: String
    var label: String? = nil
    let action: () -> Void
    @ViewBuilder var trailing: Trailing

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(6)) {
                let words = hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary
                (Text(lead.isEmpty ? "" : lead + " ").foregroundStyle(words)
                 + Text(figure).font(CicadaTheme.font(size: 14, weight: .semibold)).foregroundStyle(CicadaTheme.textPrimary)
                 + Text(self.words.isEmpty ? "" : " " + self.words).foregroundStyle(words))
                    .font(CicadaTheme.bodyFont)
                    .monospacedDigit()
                    .lineLimit(1)
                trailing
            }
            .modifier(InlineLinkTarget(hovering: hovering))
        }
        .buttonStyle(.cicadaPlain)
        .help(help)
        .accessibilityLabel(label ?? [lead, figure, words].filter { !$0.isEmpty }.joined(separator: " "))
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}

extension HomeStatLink where Trailing == EmptyView {
    init(lead: String = "", figure: String, words: String = "", help: String, label: String? = nil,
         action: @escaping () -> Void) {
        self.init(lead: lead, figure: figure, words: words, help: help, label: label, action: action) { EmptyView() }
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
    /// Round 5 — Answer is the surface's one accent primary (DR-5 (2), DR-40) unless Getting started's own read pill is up.
    var answerIsPrimary = true
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
            LeadQuestionCard(row: lead, drawsPicture: HomeQuestions.reservesPicture([lead], store: store),
                             total: figures.total, catchUp: figures.catchUp, pages: figures.catchUpPages,
                             answerIsPrimary: answerIsPrimary, openPage: openPage, startCatchup: startCatchup,
                             open: {
                                 router.pendingInboxItem = lead.id
                                 selectedTab = .inbox
                             })
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

/// The lead question (ROR-118, rounds 1 and 4): the page's picture (DR-48: a face, logo or initials, opening the page;
/// nothing when it has none, never a type glyph), the question in 15 pt medium, and under it the one next act. Round 4:
/// *Answer* is a `NeutralButton` (the card's only filled control, so it is found at a glance; Home has no accent
/// primary, DR-40) opening the question in the Inbox's list, where the rest wait; *Catch me up* is the one quiet link
/// beside it. The page's name, its age and "N more on this page" are the question's hover and accessibility hint, not a
/// second line of small grey type, and *All N questions* is gone (Answer lands in the list).
struct LeadQuestionCard: View {
    let row: HomeQuestions.Row
    /// The page has something to draw (`HomeQuestions.reservesPicture`): with none, the card has no slot for it and its
    /// question starts at the card's own edge.
    let drawsPicture: Bool
    let total: Int
    let catchUp: [String]
    let pages: Int
    var answerIsPrimary = true
    let openPage: (String) -> Void
    let startCatchup: ([String]) -> Void
    let open: () -> Void

    /// The question's hover and, for a reader with no pointer, its hint: what it is, the reason, the page, the age, how
    /// many more wait.
    private var help: String {
        var lines: [String?] = [Copy.Catchup.answerHelp + " · " + row.kind.label, row.reason]
        if !row.entityId.isEmpty { lines.append(row.entityName) }
        if row.age != "—" { lines.append(row.ageHelp) }
        if total > 1 { lines.append(Copy.Catchup.allQuestions(total)) }
        return lines.compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: "\n")
    }

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.scaled(14)) {
            if drawsPicture && !row.entityId.isEmpty {
                Button { openPage(row.entityId) } label: {
                    EntityPicture(id: row.entityId, name: row.entityName, type: row.entityType ?? .unknown,
                                  size: HomeLayout.leadPicture, collapsesWhenEmpty: true)
                }
                .buttonStyle(.cicadaPlain)
                .help(Copy.Catchup.openPage(row.entityName))
            }
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(14)) {
                Button(action: open) {
                    // 15 pt medium: under the field's 17 pt, so the field leads and this is what it asks. Balanced, so
                    // the lines come out even whatever the string (no word left alone on the last line).
                    BalancedLines {
                        Text(row.question)
                            .font(CicadaTheme.font(size: 15, weight: .medium))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                            .multilineTextAlignment(.leading)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .help(help)
                .accessibilityHint(help)
                .accessibilityAddTraits(.isHeader)

                HStack(spacing: CicadaTheme.scaled(12)) {
                    if answerIsPrimary {
                        PrimaryActionButton(title: Copy.Catchup.answer, help: help, action: open)
                            .controlSize(.large)
                    } else {
                        NeutralButton(title: Copy.Catchup.answer, help: help, action: open)
                    }
                    if !catchUp.isEmpty {
                        NeutralButton(title: Copy.Catchup.title,
                                      help: Copy.Catchup.blockLine(questions: catchUp.count, pages: pages)) {
                            startCatchup(catchUp)
                        }
                    }
                    Spacer(minLength: 0)
                }
            }
        }
        .padding(CicadaTheme.scaled(HomeLayout.leadInset))
        .frame(maxWidth: .infinity, alignment: .leading)
        // Round 5 — three steps, by weight: the ground, this card one step up in dark (`bgFocus`, with the resting ring)
        // and the field above it a step more, so the layers separate and the field still leads (DR-9: a ring, no shadow).
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius)
            .fill(CicadaTheme.mode == .dark ? CicadaTheme.bgFocus : Color.clear))
        .ringed(.resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .accessibilityElement(children: .contain)
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

/// ROR-118 (rounds 3 and 4, Home) — the newest Sleep commit: "Last read <when>" (a link to that read's details) and the
/// pages it touched as pictures, each a button that shows the page on the graph (its name is the hover and the
/// accessibility label; a page with no picture draws nothing, never a type glyph, and stays one click away in the read's
/// details). Round 4: it is the status line's last segment when it sits under Today (`TodaySection.includesLastRead`), its
/// own centred line otherwise; the counts ("4 updated") are the link's hover and accessibility label.
struct LastReadSegment: View {
    @Binding var selectedTab: AppTab
    /// Round 5 — the segment ends the status line, which already says "today" in its first words: the read's own "Today"
    /// is dropped there ("Last read 2:07 PM"), never when it stands alone or the read was another day.
    var joinsStatusLine = false

    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(AppRouter.self) private var router

    /// A one-line state ("Loading…", "Nothing read yet"): plain words.
    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
    }

    var body: some View {
        switch HomeFigures.lastRead(sleepVM.history, loaded: sleepVM.historyLoaded,
                                    failed: sleepVM.historyFailed,
                                    hasRunBefore: sleepVM.status?.debt.hasRunBefore
                                        ?? store.status.value.map { $0.lastSleepAt != nil },
                                    lastSleepAt: store.status.value?.lastSleepAt) {
        case .loading:
            // Owner 2026-10-14 — words, not a bare "—": a box that is only a dash reads as broken.
            note(Copy.homeLastReadLoading)
        case .failed:
            lastReadLink(figure: Copy.homeLastReadFailed, lead: "", label: nil)
        case .never:
            note(Copy.homeNothingReadYet)
        case .entry(let entry):
            read(entry)
        case .earlier(let at):
            // Off the history page: the day the status gives, and the page that owns the rest — never counts this
            // block did not read.
            if let when = at.flatMap({ HomeFigures.when($0) }) {
                lastReadLink(figure: when, lead: Copy.homeLastReadShort, label: nil)
            } else {
                lastReadLink(figure: Copy.homeLastReadEarlier, lead: "", label: nil)
            }
        }
    }

    /// "Last read Today 1:39 PM": a link to that read in the Sleep page's Details (review #9), never a trigger.
    private func lastReadLink(figure: String, lead: String, label: String?, help: String = Copy.homeLastReadHelp)
        -> some View {
        HomeStatLink(lead: lead, figure: figure, help: help, label: label, action: openDetails)
    }

    private func read(_ entry: SleepHistoryEntry) -> some View {
        let chips = HomeFigures.chips(entry, nodes: store.graph.value?.nodes ?? [])
        let when = HomeFigures.when(entry.date) ?? String(entry.date.prefix(10))
        let shownWhen = joinsStatusLine ? HomeFigures.withoutToday(when) : when
        let line = HomeFigures.lastReadLine(entry)
        // Round 5 — the pictures say what they are: "updated", before them, only while one is drawn (a page with no
        // picture is not drawn, so its word would stand over nothing).
        let drawsChips = EntityPictureLayout.anyDrawn(chips.shown.map { (type: $0.type, picture: store.picture(for: $0.id)) })
        return HStack(spacing: CicadaTheme.scaled(HomeLayout.statGap)) {
            lastReadLink(figure: shownWhen, lead: Copy.homeLastReadShort,
                         label: Copy.homeLastReadShort + " " + when + ": " + line,
                         help: Copy.homeLastReadHelp + " · " + line)
            if drawsChips {
                Text(Copy.homeLastReadTouched)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .accessibilityHidden(true)
            }
            // One size, one ring, side by side: the pictures read as one group (a page with none is simply not there).
            HStack(spacing: CicadaTheme.scaled(4)) {
                ForEach(chips.shown, id: \.id) { chip in pageChip(chip) }
            }
        }
    }

    /// One page the read touched, as its picture alone (collapsing to nothing when it has none); a click shows it on
    /// the graph.
    private func pageChip(_ chip: HomeChip) -> some View {
        Button {
            selectedTab = .graph
            graphVM.revealEntity(id: chip.id)
        } label: {
            EntityPicture(id: chip.id, name: chip.name, type: chip.type, size: HomeLayout.chipPicture,
                          collapsesWhenEmpty: true)
                // A 24 pt hit frame in height only, so a page with no picture still takes no width.
                .frame(minHeight: CicadaTheme.scaled(HomeTargets.tagHitHeight))
                .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.homeShowOnGraph(chip.name))
        .accessibilityLabel(Copy.homeShowOnGraph(chip.name))
    }

    /// Review #9 — Last read opens *that read* in the Sleep page's Details, not the page again.
    private func openDetails() { router.routeToSleepDetails(.lastCycle) }
}

/// Last read as its own line, for when it does not sit under Today (the first week's order, or Today has nothing).
struct LastReadSection: View {
    /// Review #8 — no read ever ran: "Last time Cicada read · not yet", no card.
    var empty = false
    @Binding var selectedTab: AppTab

    var body: some View {
        if empty {
            HomeBlock(title: Copy.homeLastRead, emptyNote: Copy.homeLastReadNotYet) { EmptyView() }
        } else {
            LastReadSegment(selectedTab: $selectedTab)
                .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .center)
        }
    }
}
