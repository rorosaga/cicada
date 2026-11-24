import SwiftUI

// G245 (ruling 78, plan 3.2 item 3) — a list source's Items: `TextTabs` per stream that holds items (All first), a folder
// menu beside the tabs when the stream keeps folders, then item cards in the queue card's layout — the title, two lines
// of the person's own words, and the footer `author · posted Sunday · Bookmarks · Likes · read`. Five by default, then
// "All N" opens the whole list in the page's place (DR-81). A row the backend sends no `lists`, `folders` or `depth` for
// (it ships apart from this build) simply says less.
//
// Applies DR-37 (an item with words and a source is its own card), DR-45 (tabs, one selected), DR-52 (a real mark or
// none), DR-60/61 (a key never animates, one hover ease), DR-81; the 2026-11-23 soft-card line (`softCardRow(ground:
// .page)` — an item on a source's page stands on the page, as the Feed's saved items do).

/// One item as a card. The whole card is one button; where it opens is the same hand-off as every captured list.
struct SourceItemCard: View {
    let item: ChannelItem
    /// Whether the card names its site (a mark and the host): only away from the source's own page, where every item is
    /// from that site and saying so again is noise (DR-38). Never a letter: `SiteIcon` draws the family's real mark.
    var showsSite = false
    /// The list whose tab is open: not said again on a card that is on it.
    var omittingList: String?
    let today: ISODay
    let route: CapturedItemRoute?
    let open: (CapturedItemRoute) -> Void

    var body: some View {
        if let route {
            Button { open(route) } label: { card }
                .buttonStyle(.cicadaPlain)
                .help(Copy.capturedOpenHelp(item.kind))
                .accessibilityLabel(spoken)
                .accessibilityHint(Copy.capturedOpenHelp(item.kind))
        } else {
            card.accessibilityElement(children: .ignore).accessibilityLabel(spoken)
        }
    }

    private var card: some View {
        HStack(alignment: .center, spacing: CicadaTheme.scaled(12)) {
            if let still = SavedItemText.stillPath(item) { VideoStill(path: still) }
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                Text(item.title)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                if let words = SourceItemCardText.words(item) {
                    Text(words)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                footer
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .softCardRow(ground: .page)
    }

    private var footer: some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            if showsSite, SavedItemText.stillPath(item) == nil, item.book != true {
                SavedLinkMark(mark: SavedItemText.mark(item), size: .inline)
            }
            Text(SourceItemCardText.footer(item, today: today, showsSite: showsSite, omitting: omittingList).joined(separator: " · "))
                .monospacedDigit()
        }
        .font(CicadaTheme.metaFont)
        .foregroundStyle(CicadaTheme.textTertiary)
        .lineLimit(1)
        .truncationMode(.tail)
    }

    private var spoken: String {
        ([item.title, SourceItemCardText.words(item)].compactMap { $0 } + SourceItemCardText.footer(item, today: today, showsSite: showsSite, omitting: omittingList))
            .joined(separator: ", ")
    }
}

/// One item of a list: its card, and — only when the backend told this row it may (`ChannelItem.keep`, G246) — the quiet
/// "Keep as a page" under it (DR-40: a text button; DR-38: nothing said twice, so a row that has a page, a work and every
/// row while the posts-as-rows switch is off carry nothing). The card and the control are two things, so the control is
/// never a button inside the card's own.
struct SourceItemRow: View {
    let item: ChannelItem
    var omittingList: String?
    let today: ISODay
    let route: CapturedItemRoute?
    let open: (CapturedItemRoute) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SourceItemCard(item: item, omittingList: omittingList, today: today, route: route, open: open)
            if SourceItemRow.offersKeep(item) { KeepAsPageControl(row: item.id, word: item.keep) }
        }
    }

    /// Whether a row draws the control at all: only for a media row the backend marked `row` or `kept`.
    static func offersKeep(_ item: ChannelItem) -> Bool {
        item.kind == .media && KeepAsPage.offer(KeepAsPage.seeded(item.keep, page: item.id)) != nil
    }
}

/// The tabs and the folder menu in one row (tabs left, the menu at the trailing edge); nothing at all with one list.
struct SourceStreamTabsRow: View {
    let tabs: [TextTab<String>]
    @Binding var selection: String?
    /// The folders the selected stream keeps, and the one chosen (nil is every folder); empty draws no menu.
    var folders: [String] = []
    @Binding var folder: String?
    /// G246 — the page that stands for what is open (the list's, or the chosen folder's), when it has one: a quiet link
    /// at the trailing edge, drawn only when the backend named a page. `openPage` is handed the page's id.
    var page: SourceStreamItems.PageLink?
    var openPage: (String) -> Void = { _ in }

    @State private var menuOpen = false

    var body: some View {
        if !tabs.isEmpty || !folders.isEmpty || page != nil {
            HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                if !tabs.isEmpty {
                    TextTabs(tabs: tabs, selection: Binding(get: { selection }, set: { chosen in
                        // A tab switch is instant (DR-61), and leaves the folder behind: it names another stream's.
                        Instant.run { selection = chosen; folder = nil }
                    }))
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if let page {
                    TextButton(title: page.title, help: page.help, inline: true) { openPage(page.id) }
                        .accessibilityIdentifier("source-list-page-link")
                }
                if !folders.isEmpty { folderMenu }
            }
            .frame(minHeight: CicadaTheme.scaled(TextTabs<String>.height))
        }
    }

    private var folderMenu: some View {
        NeutralButton(title: folder ?? Copy.Streams.allFolders, trailingSystemImage: "chevron.down", size: .compact,
                      help: Copy.Streams.allFoldersHelp) { menuOpen.toggle() }
            .popover(isPresented: $menuOpen, arrowEdge: .bottom) {
                VStack(alignment: .leading, spacing: 0) {
                    pick(nil, title: Copy.Streams.allFolders)
                    ForEach(folders, id: \.self) { pick($0, title: $0) }
                }
                .padding(CicadaTheme.spacingSM)
                .frame(minWidth: CicadaTheme.scaled(180), alignment: .leading)
            }
    }

    private func pick(_ name: String?, title: String) -> some View {
        Button {
            Instant.run { folder = name }
            menuOpen = false
        } label: {
            HStack {
                Text(title).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingMD)
                if folder == name {
                    Image(systemName: "checkmark").font(CicadaTheme.icon(.inline)).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .padding(.horizontal, CicadaTheme.spacingSM)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
    }
}

/// A list source's cards for one selection of stream and folder, read from the items route. `cap` nil is the whole list,
/// paged ("Show more"); else at most `cap` cards, then "All N" (which opens `onAll`).
struct SourceStreamCards: View {
    /// The list key (`SourceListKey.make(channel, stream:, folder:)`) the cache holds and the route is asked under.
    let key: String
    /// The page's one search: a list under a search is held beside the plain one (never blank while it is read).
    var query = ""
    var cap: Int? = SourceStreamItems.cap
    /// The open tab's list name, left off each card's footer.
    var omittingList: String?
    let onAll: (String) -> Void

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(Store.self) private var store: Store?

    private var refreshKey: String {
        "\(key)|\(SourceSearch.normalized(query))|\(store?.channels.loadedAt?.timeIntervalSinceReferenceDate ?? 0)"
            + "|\(store?.sourcesOverview.loadedAt?.timeIntervalSinceReferenceDate ?? 0)"
    }

    var body: some View {
        if let cache {
            content(cache)
                .task(id: refreshKey) {
                    if !SourceSearch.normalized(query).isEmpty {
                        try? await Task.sleep(for: SourceSearch.debounce)
                        guard !Task.isCancelled else { return }
                    }
                    await cache.refresh(key, query: query)
                }
        }
    }

    @ViewBuilder
    private func content(_ cache: ChannelItemsCache) -> some View {
        let searching = !SourceSearch.normalized(query).isEmpty
        if let list = cache.list(key, query: query) ?? (searching ? cache.list(key) : nil) {
            if list.items.isEmpty {
                note(searching ? Copy.SourcePage.noMatch(query) : Copy.Streams.noItemsYet)
            } else {
                let rows = cap.map { Array(list.items.prefix($0)) } ?? list.items
                let today = ISODay.today()
                VStack(alignment: .leading, spacing: CicadaTheme.cardGap) {
                    ForEach(rows, id: \.self) { item in
                        SourceItemRow(item: item, omittingList: omittingList, today: today,
                                      route: CapturedItemRoute.of(item, interactive: true),
                                      open: { SourcePageRouting.go($0, router: router, provenance: provenance) })
                    }
                    footer(list, shown: rows.count, cache: cache)
                }
            }
        } else {
            switch cache.phase(key, query: query) {
            case .failed(let why): note(why)
            case .gone: note(Copy.capturedNone)
            case .idle, .loading, .loaded: ListSkeleton(message: Copy.capturedLoading, rows: 3)
            }
        }
    }

    @ViewBuilder
    private func footer(_ list: ChannelItemsList, shown: Int, cache: ChannelItemsCache) -> some View {
        if let cap, list.total > cap {
            TextButton(title: Copy.SourcePage.all(list.total), help: Copy.SourcePage.allHelp, inline: true, flushLeading: true) { onAll(key) }
        } else if cap == nil, list.hasMore {
            let loading = cache.isLoadingMore(key, query: query)
            HStack(spacing: CicadaTheme.spacingSM) {
                TextButton(title: loading ? Copy.capturedLoadingMore : Copy.capturedShowMore, inline: true, flushLeading: true) {
                    Task { await cache.loadMore(key, query: query) }
                }
                .disabled(loading)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(Copy.capturedShown(list.items.count, of: list.total, noun: ("item", "items")))
                    .font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
            }
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(2)
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
    }
}

/// The Items of a list source: tabs per stream that holds items, the folder menu, the cards. Owns the tab and the folder
/// (a per-viewer convenience, never stored); the page hands it the channel the cards read and the streams.
struct SourceStreamItemsSection: View {
    let channel: String
    let streams: [ResolvedStream]
    var query = ""
    /// The channel the watched history's days are listed under, when the source has one (YouTube): the History tab's content.
    var historyChannel: String?
    let onAll: (String) -> Void
    /// A watched day opens in the page's place.
    var onDrill: (SourceDrill) -> Void = { _ in }

    @State private var tab: String?
    @State private var folder: String?
    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(AppRouter.self) private var router: AppRouter?

    /// `startTab` is the stream the page opens on (nil is All): a hand-off or a render names it.
    init(channel: String, streams: [ResolvedStream], query: String = "", startTab: String? = nil,
         historyChannel: String? = nil, onAll: @escaping (String) -> Void, onDrill: @escaping (SourceDrill) -> Void = { _ in }) {
        self.channel = channel
        self.streams = streams
        self.query = query
        self.historyChannel = historyChannel
        self.onAll = onAll
        self.onDrill = onDrill
        _tab = State(initialValue: startTab)
    }

    var body: some View {
        let selected = SourceStreamItems.effective(tab, streams: streams)
        let history = SourceStreamItems.showsHistory(tab, streams: streams) && historyChannel != nil
        let folderStream = SourceStreamItems.folderStream(selected, streams: streams)
        let key = SourceStreamItems.key(channel: channel, stream: history ? nil : selected, folder: folderStream == nil ? nil : folder)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            SourceStreamTabsRow(tabs: SourceStreamItems.tabs(streams), selection: $tab,
                                folders: folderStream == nil ? [] : folderNames, folder: $folder,
                                page: SourceStreamItems.pageLink(tab, folder: folderStream == nil ? nil : folder, streams: streams),
                                openPage: { SourcePageRouting.go(.entity($0), router: router, provenance: provenance) })
            if history, let historyChannel {
                // The watched days, in the source's own rows (a day opens to its videos), under their own tab.
                SourceItemsSection(channel: historyChannel, query: query, onDrill: onDrill)
            } else {
                SourceStreamCards(key: key, query: query,
                                  omittingList: selected.flatMap { id in streams.first { $0.id == id }?.stream.label }, onAll: onAll)
            }
        }
        .task(id: folderStream?.id) {
            if folderStream != nil { await cache?.refreshCollections(channel) }
        }
    }

    private var folderNames: [String] {
        let rows = cache?.list(SourceStreamItems.key(channel: channel, stream: SourceStreamItems.effective(tab, streams: streams),
                                                     folder: nil))?.items ?? []
        return SourceStreamItems.folderNames(collections: cache?.collections(channel), items: rows)
    }
}
