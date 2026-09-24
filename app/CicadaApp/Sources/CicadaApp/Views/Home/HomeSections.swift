import SwiftUI

/// Today / Needs you / Last read (design §6.3, R-IB9). Thin renderers over
/// `HomeFigures`: every number here is computed there and table-tested, so a
/// view can only choose where a number sits, never what it says. Each number
/// appears once and each is a link to the page that owns it; nothing here is a
/// trigger (the waiting line opens the Sleep page — never a Consolidate, G125
/// R10 in steady state).
///
/// In Direction D's list grammar (DS-3b): a `SectionLabel` over one grouped
/// block, 36 pt rows, links in `accentText` (R-HS6).
///
/// Internal, not `private`: `HomeView.swift` composes them from another file.
struct HomeSections: View {
    let today: Date
    let gettingStartedVisible: Bool
    /// R-HS4 — the Inbox's slot floors, measured from Home's own column (`HomeLayout`).
    let needsYouSlots: InboxRowSlots
    @Binding var selectedTab: AppTab

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(HomeLayout.blockGap)) {
            TodaySection(today: today, gettingStartedVisible: gettingStartedVisible, selectedTab: $selectedTab)
            NeedsYouSection(needsYouSlots: needsYouSlots, selectedTab: $selectedTab)
            LastReadSection(selectedTab: $selectedTab)
        }
    }
}

// MARK: - The block and its lines

/// DR-20, DR-37 — a Home section: its `SectionLabel` above one grouped block (`glassCard()`:
/// `bgFocus`, `cornerRadius`, a resting ring), 4 pt inside so a row's hover fill sits concentric
/// (DR-12). It replaced the old Home card, whose label sat inside a padded `surface` card (P1,
/// R-HS6).
struct HomeBlock<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(HomeLayout.labelGap)) {
            SectionLabel(title)
                .padding(.horizontal, CicadaTheme.scaled(10))
            VStack(alignment: .leading, spacing: 0) { content }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(CicadaTheme.scaled(HomeLayout.blockInset))
                .glassCard()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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
    @Binding var selectedTab: AppTab

    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(AppRouter.self) private var router

    var body: some View {
        let figures = HomeFigures.today(store.sourcesOverview.value, today: today)
        HomeBlock(title: Copy.homeToday) {
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
        HomeLine {
            switch figures.captured {
            case nil:
                HomeUnknown()
            case 0?:
                Text(Copy.homeNothingCapturedToday)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            case let n?:
                Text(Copy.homeCapturedToday(n))
                    .font(CicadaTheme.bodyFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .help(Copy.homeCapturedHelp)
                Spacer(minLength: CicadaTheme.spacingSM)
                ForEach(figures.origins, id: \.sourceId) { chip in
                    // DR-52 — the service's real mark, bare, nodding on hover (`markHover`).
                    Button { router.routeToSourceDetail(chip.sourceId) } label: {
                        OriginMark(origin: chip.mark, size: CicadaTheme.scaled(16))
                            .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                            .contentShape(Rectangle())
                            .markHover()
                    }
                    .buttonStyle(.cicadaPlain)
                    .help(chip.label + " · " + Copy.homeCapturedToday(chip.count))
                    .accessibilityLabel(chip.label + ", " + Copy.homeCapturedToday(chip.count))
                }
            }
        }
    }

    private var waiting: some View {
        let status = store.status.value
        let worm = status.map { deriveBookwormState($0, justFinishedAt: nil) } ?? .awake
        return HomeLine {
            BookwormView(state: worm, pointSize: 24)
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
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            // A link to the page that owns the queue — never a Sleep trigger (G125 R10).
            InlineLink(title: Copy.homeOpenSleep) { selectedTab = .sleep }
        }
    }
}

// MARK: - Needs you

struct NeedsYouSection: View {
    let needsYouSlots: InboxRowSlots
    @Binding var selectedTab: AppTab

    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router

    var body: some View {
        let figures = HomeFigures.needsYou(store.visibleInbox)
        // DR-58 — an age is computed when read, never stored.
        let now = Date.now
        HomeBlock(title: Copy.homeNeedsYou) {
            if figures.shown.isEmpty {
                HomeLine {
                    Text(Copy.homeNothingNeedsYou)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
            } else {
                ForEach(figures.shown) { item in
                    // R-HS4 — the Inbox's own STATE 0 row, so a question reads here exactly as it does
                    // there; the palette's hand-off (`pendingInboxItem`) lands it in STATE 1.
                    InboxRow(item: item, style: .wide, slots: needsYouSlots, selected: false, now: now) {
                        router.pendingInboxItem = item.id
                        selectedTab = .inbox
                    }
                }
                if figures.total > HomeFigures.needsYouLimit {
                    HomeLine {
                        InlineLink(title: Copy.homeAllInbox(figures.total)) { selectedTab = .inbox }
                    }
                }
            }
        }
    }
}

// MARK: - Last read

struct LastReadSection: View {
    @Binding var selectedTab: AppTab

    @Environment(Store.self) private var store
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        HomeBlock(title: Copy.homeLastRead) {
            switch HomeFigures.lastRead(sleepVM.history, loaded: sleepVM.historyLoaded,
                                        hasRunBefore: sleepVM.status?.debt.hasRunBefore
                                            ?? store.status.value.map { $0.lastSleepAt != nil },
                                        lastSleepAt: store.status.value?.lastSleepAt) {
            case .loading:
                HomeLine { HomeUnknown() }
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
                HomeLine {
                    if let day = at.flatMap({ HomeFigures.day($0, locale: .autoupdatingCurrent) }) {
                        Text(day)
                            .font(CicadaTheme.bodyFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textPrimary)
                    } else {
                        HomeUnknown()
                    }
                    Spacer(minLength: CicadaTheme.spacingSM)
                    InlineLink(title: Copy.homeOpenSleep) { selectedTab = .sleep }
                }
            }
        }
    }

    private func read(_ entry: SleepHistoryEntry) -> some View {
        let chips = HomeFigures.chips(entry, nodes: store.graph.value?.nodes ?? [])
        return VStack(alignment: .leading, spacing: 0) {
            HomeLine {
                Text(HomeFigures.lastReadLine(entry))
                    .font(CicadaTheme.bodyFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer(minLength: CicadaTheme.spacingSM)
                InlineLink(title: Copy.homeOpenSleep) { selectedTab = .sleep }
            }
            if !chips.shown.isEmpty {
                // DR-44 — the one pill, with the page type's dot inside it; a click opens the graph.
                HStack(spacing: CicadaTheme.scaled(6)) {
                    ForEach(chips.shown, id: \.id) { chip in
                        Button {
                            selectedTab = .graph
                            graphVM.revealEntity(id: chip.id)
                        } label: {
                            Tag(text: chip.name, dot: CicadaTheme.entityColor(for: chip.type))
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
                .padding(.vertical, CicadaTheme.spacingSM)
            }
        }
    }
}
