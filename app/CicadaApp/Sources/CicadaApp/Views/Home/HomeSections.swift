import SwiftUI

/// Today / Needs you / Last read (design §6.3, R-IB9). Thin renderers over
/// `HomeFigures`: every number here is computed there and table-tested, so a
/// view can only choose where a number sits, never what it says. Each number
/// appears once and each is a link to the page that owns it; nothing here is a
/// trigger (the waiting line opens the Sleep page — never a Consolidate, G125
/// R10 in steady state).
///
/// Internal, not `private`: `HomeView.swift` composes them from another file.
struct HomeSections: View {
    let today: Date
    let gettingStartedVisible: Bool
    @Binding var selectedTab: AppTab

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            TodaySection(today: today, gettingStartedVisible: gettingStartedVisible, selectedTab: $selectedTab)
            NeedsYouSection(selectedTab: $selectedTab)
            LastReadSection(selectedTab: $selectedTab)
        }
    }
}

// MARK: - The card and its rows

/// A `surface` card with the Settings card-title style — content, not chrome,
/// so it is opaque (R-M5: glass stays chrome).
struct HomeCard<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(title)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingLG)
        .background(CicadaTheme.surface, in: RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge))
    }
}

/// One row that opens something: a real `Button` (VoiceOver, H6) with a
/// `surfaceHover` fill on hover — never a lift, these are dense rows (R9 §3.2).
struct HomeRowButton<Label: View>: View {
    let action: () -> Void
    @ViewBuilder let label: Label

    @State private var hovered = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            label
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, CicadaTheme.spacingSM)
                .padding(.vertical, CicadaTheme.spacingXS)
                .background(hovered ? CicadaTheme.surfaceHover : Color.clear,
                            in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
        }
        .buttonStyle(.cicadaPlain)
        .onHover { inside in
            withAnimation(CicadaMotion.hover(reduceMotion: reduceMotion)) { hovered = inside }
        }
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
        HomeCard(title: Copy.homeToday) {
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
        HStack(spacing: CicadaTheme.spacingSM) {
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
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .help(Copy.homeCapturedHelp)
                Spacer(minLength: CicadaTheme.spacingSM)
                ForEach(figures.origins, id: \.sourceId) { chip in
                    Button { router.routeToSourceDetail(chip.sourceId) } label: {
                        OriginMark(origin: chip.mark, size: CicadaTheme.scaled(16))
                            .markHover()
                    }
                    .buttonStyle(.cicadaPlain)
                    .help(chip.label + " · " + Copy.homeCapturedToday(chip.count))
                    .accessibilityLabel(chip.label + ", " + Copy.homeCapturedToday(chip.count))
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
    }

    private var waiting: some View {
        let status = store.status.value
        let worm = status.map { deriveBookwormState($0, justFinishedAt: nil) } ?? .awake
        return HStack(spacing: CicadaTheme.spacingSM) {
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
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            // A link to the page that owns the queue — never a Sleep trigger (G125 R10).
            Button(Copy.homeOpenSleep) { selectedTab = .sleep }
                .buttonStyle(.cicadaPlain)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.accent)
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
    }
}

// MARK: - Needs you

struct NeedsYouSection: View {
    @Binding var selectedTab: AppTab

    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router

    var body: some View {
        let figures = HomeFigures.needsYou(store.visibleInbox)
        HomeCard(title: Copy.homeNeedsYou) {
            if figures.shown.isEmpty {
                Text(Copy.homeNothingNeedsYou)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.spacingSM)
            } else {
                ForEach(figures.shown) { item in
                    HomeRowButton(action: {
                        // The palette's own route onto one card (`router.pendingInboxItem`).
                        router.pendingInboxItem = item.id
                        selectedTab = .inbox
                    }) {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Image(systemName: item.kind.icon)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .accessibilityHidden(true)
                            Text(item.question ?? item.title)
                                .font(CicadaTheme.bodyFont)
                                .foregroundStyle(CicadaTheme.textPrimary)
                                .lineLimit(1)
                            Spacer(minLength: CicadaTheme.spacingSM)
                            if let harness = item.cause?.harness {
                                OriginMark(origin: harness, size: CicadaTheme.scaled(14))
                                    .accessibilityHidden(true)
                            }
                        }
                    }
                }
                if figures.total > HomeFigures.needsYouLimit {
                    Button(Copy.homeAllInbox(figures.total)) { selectedTab = .inbox }
                        .buttonStyle(.cicadaPlain)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.accent)
                        .padding(.horizontal, CicadaTheme.spacingSM)
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
        HomeCard(title: Copy.homeLastRead) {
            switch HomeFigures.lastRead(sleepVM.history, loaded: sleepVM.historyLoaded,
                                        hasRunBefore: sleepVM.status?.debt.hasRunBefore
                                            ?? store.status.value.map { $0.lastSleepAt != nil },
                                        lastSleepAt: store.status.value?.lastSleepAt) {
            case .loading:
                HomeUnknown()
                    .padding(.horizontal, CicadaTheme.spacingSM)
            case .never:
                Text(Copy.homeNothingReadYet)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.spacingSM)
            case .entry(let entry):
                read(entry)
            case .earlier(let at):
                // Off the history page: the day the status gives, and the page
                // that owns the rest — never counts this card did not read.
                HStack(spacing: CicadaTheme.spacingSM) {
                    if let day = at.flatMap({ HomeFigures.day($0, locale: .autoupdatingCurrent) }) {
                        Text(day)
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                    } else {
                        HomeUnknown()
                    }
                    Spacer(minLength: CicadaTheme.spacingSM)
                    Button(Copy.homeOpenSleep) { selectedTab = .sleep }
                        .buttonStyle(.cicadaPlain)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.accent)
                }
                .padding(.horizontal, CicadaTheme.spacingSM)
            }
        }
    }

    private func read(_ entry: SleepHistoryEntry) -> some View {
        let chips = HomeFigures.chips(entry, nodes: store.graph.value?.nodes ?? [])
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(HomeFigures.lastReadLine(entry))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer(minLength: CicadaTheme.spacingSM)
                Button(Copy.homeOpenSleep) { selectedTab = .sleep }
                    .buttonStyle(.cicadaPlain)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.accent)
            }
            if !chips.shown.isEmpty {
                HStack(spacing: CicadaTheme.spacingXS) {
                    ForEach(chips.shown, id: \.id) { chip in
                        Button {
                            selectedTab = .graph
                            graphVM.revealEntity(id: chip.id)
                        } label: {
                            Text(chip.name)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textPrimary)
                                .lineLimit(1)
                                .padding(.horizontal, CicadaTheme.spacingSM)
                                .padding(.vertical, CicadaTheme.spacingXS)
                                .background(CicadaTheme.surfaceHover, in: Capsule())
                        }
                        .buttonStyle(.cicadaPlain)
                    }
                    if chips.more > 0 {
                        Text(Copy.homeMoreChips(chips.more))
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
    }
}
