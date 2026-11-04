import SwiftUI

// 2026-11-04 — the two This Mac pages whose items are not notes in folders: the meeting recorders (recorder → folder →
// meetings, each with its day and how long it ran) and Contacts (the people in memory as a grid of faces). Both fill
// the standard source page's `content` slot and read the backend's lists (`ChannelItemsCache`), never this Mac's store.

/// A recorder's meetings: its folders when it has several (one row each, DR-34), else the one folder's meetings.
struct MeetingsBrowser: View {
    /// The recorder's meeting folders, as channels (`meetings:<id>`), with their names.
    let folders: [(id: String, label: String)]
    /// The page's title, what a folder's back button returns to ("‹ Hex").
    let sourceTitle: String

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @State private var open: String?
    @State private var query = ""

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let open, folders.count > 1, let folder = folders.first(where: { $0.id == open }) {
                SourceBrowserHead(back: sourceTitle, title: folder.label) { Instant.run { self.open = nil; query = "" } }
            }
            if let channel = shownChannel {
                SourceSearchHeader(query: $query, prompt: Copy.SourceBrowser.search(
                    cache?.list(channel)?.all ?? cache?.list(channel)?.total, channel: channel))
                MeetingList(channel: channel, query: query)
            } else {
                VStack(spacing: 0) {
                    ForEach(folders, id: \.id) { folder in
                        SourceBrowserRow(title: folder.label, meta: count(folder.id)) {
                            Image(systemName: "folder")
                                .font(CicadaTheme.icon(.list))
                                .foregroundStyle(CicadaTheme.textSecondary)
                        } open: { Instant.run { open = folder.id } }
                    }
                }
                // The rows' counts come from each folder's own list.
                .task(id: folders.map(\.id).joined(separator: "|")) {
                    for folder in folders { await cache?.refresh(folder.id) }
                }
            }
        }
    }

    private var shownChannel: String? { folders.count == 1 ? folders[0].id : open }

    private func count(_ channel: String) -> String? {
        (cache?.list(channel)).map { Copy.SourceBrowser.count($0.all ?? $0.total, channel: channel) }
    }
}

/// One folder's meetings, newest first, a page at a time; a row opens the meeting in the Reader.
struct MeetingList: View {
    let channel: String
    let query: String

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(Store.self) private var store: Store?

    private var refreshKey: String {
        "\(channel)|\(SourceSearch.normalized(query))|\(store?.channels.loadedAt?.timeIntervalSinceReferenceDate ?? 0)"
    }

    var body: some View {
        Group {
            if let cache {
                let list = cache.list(channel, query: query)
                    ?? (SourceSearch.normalized(query).isEmpty ? nil : cache.list(channel))
                if let list {
                    if list.items.isEmpty {
                        InPlaceNote(text: SourceSearch.normalized(query).isEmpty ? Copy.SourceBrowser.nothing
                                    : Copy.SourcePage.noMatch(query))
                    } else {
                        LazyVStack(spacing: 0) {
                            ForEach(list.items, id: \.self) { item in
                                MeetingRow(item: item) {
                                    SourcePageRouting.go(.reader(episode: item.id, title: item.title),
                                                         router: router, provenance: provenance)
                                }
                            }
                        }
                        if list.hasMore {
                            TextButton(title: cache.isLoadingMore(channel, query: query) ? Copy.capturedLoadingMore
                                       : Copy.capturedShowMore) {
                                Task { await cache.loadMore(channel, query: query) }
                            }
                        }
                    }
                } else if case .failed(let why) = cache.phase(channel, query: query) {
                    InPlaceNote(text: why)
                } else {
                    ListSkeleton(message: Copy.SourceBrowser.loading, rows: 3)
                }
            }
        }
        .task(id: refreshKey) {
            if !SourceSearch.normalized(query).isEmpty {
                try? await Task.sleep(for: SourceSearch.debounce)
                guard !Task.isCancelled else { return }
            }
            await cache?.refresh(channel, query: query)
        }
    }
}

/// A meeting: its title, then its day and how long it ran in meta ink; the full date on hover (DR-58).
struct MeetingRow: View {
    let item: ChannelItem
    let open: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let meta = MeetingRowText.meta(item)
        Button(action: open) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "waveform")
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(width: CicadaTheme.scaled(24))
                    .accessibilityHidden(true)
                Text(item.title)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(meta.text)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .fixedSize()
            }
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .padding(.horizontal, CicadaTheme.scaled(10))
            .rowHoverFill(hovering: hovering)
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(meta.help)
        .accessibilityLabel([item.title, meta.help].joined(separator: ", "))
        .accessibilityHint(Copy.capturedOpenHelp(item.kind))
    }
}

/// A meeting row's meta words, pure (`SourceBrowserTests`): "Tue, Nov 3 · 32 min"; the full date (and length) on
/// hover.
enum MeetingRowText {
    static func meta(_ item: ChannelItem, locale: Locale = .autoupdatingCurrent,
                     calendar: Calendar = .autoupdatingCurrent) -> (text: String, help: String) {
        let length = SourceBrowserText.duration(item.durationS)
        guard let day = ISODay(item.day) else { return (length ?? "", length ?? "") }
        let date = day.date(in: calendar)
        let short = DateFormatter()
        short.locale = locale
        short.calendar = calendar
        short.timeZone = calendar.timeZone
        short.setLocalizedDateFormatFromTemplate("EEEMMMd")
        let full = DateFormatter()
        full.locale = locale
        full.calendar = calendar
        full.timeZone = calendar.timeZone
        full.dateStyle = .full
        return ([short.string(from: date), length].compactMap { $0 }.joined(separator: " · "),
                [full.string(from: date), length].compactMap { $0 }.joined(separator: " · "))
    }
}

/// Contacts: the people in memory that a card matched, as a grid of faces — each person's picture by the one picture
/// precedence (the person's choice, then their Contacts photo, …), else their monogram — under the page's one search.
/// A face opens the person's page. Never a card's other facts (G154): the backend lists the page's name only.
struct ContactsGrid: View {
    static let channel = "contacts-local"

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(Store.self) private var store: Store?
    @State private var query = ""

    private var refreshKey: String {
        "\(SourceSearch.normalized(query))|\(store?.channels.loadedAt?.timeIntervalSinceReferenceDate ?? 0)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SourceSearchHeader(query: $query, prompt: Copy.SourceBrowser.search(
                cache?.list(Self.channel)?.all ?? cache?.list(Self.channel)?.total, channel: Self.channel))
            grid
        }
        .task(id: refreshKey) {
            if !SourceSearch.normalized(query).isEmpty {
                try? await Task.sleep(for: SourceSearch.debounce)
                guard !Task.isCancelled else { return }
            }
            await cache?.refresh(Self.channel, query: query)
        }
    }

    @ViewBuilder
    private var grid: some View {
        if let cache {
            let list = cache.list(Self.channel, query: query)
                ?? (SourceSearch.normalized(query).isEmpty ? nil : cache.list(Self.channel))
            if let list {
                if list.items.isEmpty {
                    InPlaceNote(text: SourceSearch.normalized(query).isEmpty ? Copy.SourceBrowser.contactsNone
                                : Copy.SourcePage.noMatch(query))
                } else {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: CicadaTheme.scaled(ContactsGridMetrics.cell),
                                                           maximum: CicadaTheme.scaled(ContactsGridMetrics.cell + 24)),
                                                 spacing: CicadaTheme.spacingSM)],
                              alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        ForEach(list.items, id: \.self) { item in
                            ContactCell(item: item) {
                                SourcePageRouting.go(.entity(item.id), router: router, provenance: provenance)
                            }
                        }
                    }
                    if list.hasMore {
                        TextButton(title: cache.isLoadingMore(Self.channel, query: query) ? Copy.capturedLoadingMore
                                   : Copy.capturedShowMore) {
                            Task { await cache.loadMore(Self.channel, query: query) }
                        }
                    }
                }
            } else if case .failed(let why) = cache.phase(Self.channel, query: query) {
                InPlaceNote(text: why)
            } else {
                ListSkeleton(message: Copy.SourceBrowser.loading, rows: 2)
            }
        }
    }
}

enum ContactsGridMetrics {
    /// A cell's side: the face (48) and the name under it.
    static let cell: CGFloat = 96
    static let face: CGFloat = 48
}

/// One person: their face, their name under it in one line; hover a fill (DR-48).
struct ContactCell: View {
    let item: ChannelItem
    let open: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: open) {
            VStack(spacing: CicadaTheme.spacingXS) {
                EntityPicture(id: item.id, name: item.title, type: .person, size: ContactsGridMetrics.face)
                Text(item.title)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, CicadaTheme.spacingSM)
            .padding(.horizontal, CicadaTheme.spacingXS)
            .rowHoverFill(hovering: hovering)
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(Copy.SourceBrowser.contactHelp(item.title))
        .accessibilityLabel(item.title)
        .accessibilityHint(Copy.SourceBrowser.contactHelp(item.title))
    }
}
