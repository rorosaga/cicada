import SwiftUI

// source-page-v3 (owner 2026-10-29: "Better generalizable components for each sources page like searching and what
// comes from the sources and etc. has to be worked on, so a better design for it and a better status for when it's
// connected and not so much text.") — one template every source's page is drawn on, top to bottom:
//
//   1. the head (`DetailHeader`, DR-74) and ONE status line (`SourceStatusLine`): dot + word + what follows it
//      ("Connected · last item today"), and "What Cicada reads" as a quiet text button opening the full words (the
//      connect sheets' pattern, DESIGN_RULES §9 2026-10-29) — no paragraph above the list;
//   2. one search (`CicadaSearchField`, the in-page field every list uses) as the list's own header — it replaces
//      the "What came in" heading, so nothing names the list twice (DR-38);
//   3. what came in (`SourceItemsSection`): one row per the source's natural unit — a chat, a watched day, a saved
//      thing, a note, a conversation — at most `SourceItemsRules.cap` rows, then a plain "All N" (DR-81); a group row
//      and "All N" open in the column's place, never in place (DR-81), with "‹ <source>" and Esc to return;
//   4. the source's own settings, last, under one label (`SourcePageSettings`), the same shape everywhere.

/// The status line under a source page's head.
struct SourceStatusLine: View {
    let status: SourcePageStatus
    /// The full words behind "What Cicada reads"; no link when there are none.
    let facts: [String]
    let title: String

    @State private var showFacts = false

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { _ in
            let today = ISODay.today()
            HStack(spacing: CicadaTheme.spacingSM) {
                if case .syncing = status { ProgressView().controlSize(.small) }
                StatusWord(word: status.word, tone: status.tone)
                if let detail = status.detail(today: today) {
                    Text("· \(detail)")  // count-lint:ok — words (a day, an action, a reader's own progress line)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(status.tone == .attention ? CicadaTheme.warning : CicadaTheme.textTertiary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .help(detail)
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if !facts.isEmpty {
                    TextButton(title: Copy.SourcePage.whatItReads, inline: true) { showFacts = true }
                }
            }
            .frame(minHeight: CicadaTheme.scaled(24))
            .accessibilityElement(children: .contain)
            .accessibilityLabel(status.line(today: today))
        }
        .sheet(isPresented: $showFacts) {
            SettingsSheet(title: title, onClose: { showFacts = false }) {
                ConnectFactsPage(paragraphs: facts) { showFacts = false }
            }
        }
    }
}

/// The search at the head of what came in: the one in-page field (⌘F, Esc clears, a second Esc leaves).
struct SourceSearchHeader: View {
    @Binding var query: String
    let prompt: String

    var body: some View {
        CicadaSearchField(text: $query, prompt: prompt)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// What came in from one channel, capped (DR-81) — or, inside the "All N" drill, every row a page at a time.
struct SourceItemsSection: View {
    let channel: String
    var saved = false
    let query: String
    /// Nil: every row, paged ("Show more"); else at most this many, then "All N".
    var cap: Int? = SourceItemsRules.cap
    /// Shown above the rows when a page lists several channels (Folders: one per folder).
    var label: String? = nil
    let onDrill: (SourceDrill) -> Void

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(Store.self) private var store: Store?

    private var noun: (one: String, many: String) {
        CapturedItems.noun(channel: channel, countNoun: store?.channels.value?.first { $0.id == channel }?.countNoun)
    }

    /// Re-read when the search settles and whenever the channels or the overview move (a sync that brought something
    /// in lands here too; a 304 moves nothing).
    private var refreshKey: String {
        "\(channel)|\(SourceSearch.normalized(query))|\(store?.channels.loadedAt?.timeIntervalSinceReferenceDate ?? 0)"
            + "|\(store?.sourcesOverview.loadedAt?.timeIntervalSinceReferenceDate ?? 0)"
    }

    var body: some View {
        if let cache {
            VStack(alignment: .leading, spacing: 0) {
                if let label { SectionLabel(label).frame(minHeight: CicadaTheme.scaled(28), alignment: .leading) }
                content(cache)
            }
            .task(id: refreshKey) {
                if !SourceSearch.normalized(query).isEmpty {
                    try? await Task.sleep(for: SourceSearch.debounce)
                    guard !Task.isCancelled else { return }
                }
                await cache.refresh(channel, query: query)
            }
        }
    }

    @ViewBuilder
    private func content(_ cache: ChannelItemsCache) -> some View {
        // Never blank (DR-43): while a search is read the last list it had stays, else the unsearched list.
        let list = cache.list(channel, query: query)
            ?? (SourceSearch.normalized(query).isEmpty ? nil : cache.list(channel))
        if let list {
            if list.items.isEmpty {
                empty
            } else {
                let rows = cap.map { Array(list.items.prefix($0)) } ?? list.items
                let today = ISODay.today()
                LazyVStack(spacing: saved ? CicadaTheme.scaled(RowMetrics.twoLineGap) : 0) {
                    ForEach(rows, id: \.self) { item in row(item, today: today) }
                }
                footer(list, shown: rows.count, cache: cache)
            }
        } else {
            switch cache.phase(channel, query: query) {
            case .failed(let why): note(why)
            case .gone: note(Copy.capturedNone)
            case .idle, .loading, .loaded:
                ListSkeleton(message: Copy.capturedLoading, rows: 3).padding(.vertical, CicadaTheme.spacingSM)
            }
        }
    }

    @ViewBuilder
    private var empty: some View {
        if SourceSearch.normalized(query).isEmpty {
            note(saved ? Copy.savedListNone : channel == "contacts-local" ? Copy.capturedNoPeople : Copy.capturedNone)
        } else {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                note(Copy.SourcePage.noMatch(query))
                SearchAllMemoryRow(query: query).padding(.horizontal, CicadaTheme.scaled(10))
            }
        }
    }

    @ViewBuilder
    private func row(_ item: ChannelItem, today: ISODay) -> some View {
        if item.kind == .chat {
            SourceGroupRow(item: item, today: today) { onDrill(.chat(item)) }
        } else if item.videos != nil {
            SourceGroupRow(item: item, today: today, dayTitle: true) { onDrill(.day(item)) }
        } else if saved {
            SavedItemRow(item: item, today: today, route: CapturedItemRoute.of(item, interactive: true), open: go,
                         leftLine: CapturedItems.leftLine(item, channel: channel))
        } else {
            CapturedItemRow(item: item, today: today, route: CapturedItemRoute.of(item, interactive: true), open: go,
                            leftLine: CapturedItems.leftLine(item, channel: channel))
        }
    }

    @ViewBuilder
    private func footer(_ list: ChannelItemsList, shown: Int, cache: ChannelItemsCache) -> some View {
        if let cap, list.total > cap {
            TextButton(title: Copy.SourcePage.all(list.total), help: Copy.SourcePage.allHelp) {
                onDrill(.all(channel: channel))
            }
            .padding(.top, CicadaTheme.spacingXS)
        } else if cap == nil, list.hasMore {
            let loading = cache.isLoadingMore(channel, query: query)
            HStack(spacing: CicadaTheme.spacingSM) {
                TextButton(title: loading ? Copy.capturedLoadingMore : Copy.capturedShowMore) {
                    Task { await cache.loadMore(channel, query: query) }
                }
                .disabled(loading)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(Copy.capturedShown(list.items.count, of: list.total, noun: noun))
                    .font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
            }
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(2)
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
            .padding(.horizontal, CicadaTheme.scaled(10))
            .help(text)
    }

    private func go(_ route: CapturedItemRoute) { SourcePageRouting.go(route, router: router, provenance: provenance) }
}

/// Where a row of a source page opens — the same hand-offs as every captured list.
@MainActor
enum SourcePageRouting {
    static func go(_ route: CapturedItemRoute, router: AppRouter?, provenance: ProvenanceRouter?) {
        switch route {
        case .reader(let episode, let title):
            router?.closeSettings()
            provenance?.open(ReaderTarget(episode: episode, knownTitle: title))
        case .feed(let id):
            router?.routeToSavedItem(id)
        case .entity(let id):
            router?.routeToClustersEntity(id)
        }
    }
}

/// One group — a chat (its face, who it is with, how many conversations, its newest day) or a watched day (the day,
/// how many videos) — as a one-line row that opens its items in the column (DR-81: never in place). Hover is a fill
/// (DR-48, DR-63); the chevron says it opens a list.
struct SourceGroupRow: View {
    let item: ChannelItem
    let today: ISODay
    /// A watched day's row is titled by the day itself, said once.
    var dayTitle = false
    let open: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let day = dayTitle ? nil : SavedItemText.day(item, today: today)
        let title = dayTitle ? WatchedDayText.day(item, today: today).text : item.title
        let count = SourceItemsRules.groupCount(item)
        Button(action: open) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let chat = item.chat {
                    ChatFace(id: chat.id, label: chat.label, photo: chat.photo, side: CicadaTheme.scaled(22))
                }
                Text(title)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                // A group chat says so with the chat picker's own pill (DR-44), never a second word in the title.
                if item.group == true { Tag(text: Copy.Chats.group) }
                Spacer(minLength: CicadaTheme.spacingSM)
                Text([count, day?.text].compactMap { $0 }.joined(separator: " · "))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .fixedSize()
                Image(systemName: "chevron.right")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
            }
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .padding(.horizontal, CicadaTheme.scaled(10))
            .rowHoverFill(hovering: hovering)
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(dayTitle ? WatchedDayText.day(item, today: today).help : Copy.SourcePage.groupOpenHelp)
        .accessibilityLabel([title, count, day?.help].compactMap { $0 }.joined(separator: ", "))
        .accessibilityHint(Copy.SourcePage.groupOpenHelp)
    }
}

/// A chat's conversations, opened in the column: one row per conversation by its day and message count, each opening
/// in the Reader. The chat is not named again under its own title.
struct SourceChatConversations: View {
    let item: ChannelItem

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(AppRouter.self) private var router: AppRouter?

    var body: some View {
        let today = ISODay.today()
        Group {
            if let cache, let page = cache.sittings(item.id) {
                LazyVStack(spacing: 0) {
                    ForEach(page.sittings) { sitting in
                        let words = ChatSittingsText.sitting(sitting, today: today)
                        CapturedSittingRow(text: words.text, help: words.help) {
                            SourcePageRouting.go(.reader(episode: sitting.id, title: item.title),
                                                 router: router, provenance: provenance)
                        }
                    }
                }
            } else if let cache, cache.sittingsFailed(item.id) {
                InPlaceNote(text: Copy.chatSittingsFailed)
            } else {
                InPlaceNote(text: Copy.chatSittingsLoading)
            }
        }
        .task(id: item.id) { await cache?.refreshSittings(item.id) }
    }
}

/// A watched day's videos, opened in the column (a `LazyVStack`, so each still is asked only as its row shows).
struct SourceDayVideos: View {
    let item: ChannelItem

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(AppRouter.self) private var router: AppRouter?

    var body: some View {
        Group {
            if let cache, let day = cache.day(item.id) {
                if day.videos.isEmpty {
                    InPlaceNote(text: Copy.watchedDayEmpty)
                } else {
                    LazyVStack(spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                        ForEach(day.videos) { video in
                            WatchedVideoRow(video: video, episode: day.episode) { route in
                                switch route {
                                case .saved(let id): router?.routeToSavedItem(id)
                                case .browser(let url): LinkOpen.browserOpen(url)
                                }
                            }
                        }
                    }
                }
            } else if let cache, cache.dayFailed(item.id) {
                InPlaceNote(text: Copy.watchedDayFailed)
            } else {
                InPlaceNote(text: Copy.watchedDayLoading)
            }
        }
        .task(id: item.id) { await cache?.refreshDay(item.id) }
    }
}

/// The drill's head: "‹ <source>" (Esc), then what is open, once.
struct SourceDrillHead: View {
    let source: String
    let title: String?
    let onBack: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            TextButton(title: "‹ \(source)", help: Copy.SourcePage.backHelp, action: onBack)
                .keyboardShortcut(.cancelAction)
                .padding(.leading, -CicadaTheme.scaled(10))
            if let title {
                Text(title)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
            }
        }
    }
}

/// The source's own settings, last on its page and the same shape everywhere: one label, then the source's controls
/// (its ticks, history, Refresh, Choose…, Disconnect, switches, an import's button) as its own row draws them under a
/// source head (`sourceDetailHeadShown`: no second mark or name, no second list).
struct SourcePageSettings<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.SourcePage.settings)
            content()
                .environment(\.sourceDetailHeadShown, true)
        }
        .padding(.top, CicadaTheme.spacingMD)
    }
}
