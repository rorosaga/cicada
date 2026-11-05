import SwiftUI

// ROR-108 (owner 2026-11-05: "I'd rather have the channels and then a drop-down of all the things in those channels we're
// getting") — the RSS page's content: every feed followed, each opening in place to what it brought in, newest first, a
// page at a time (DESIGN_RULES §9 2026-11-05, DR-34, DR-48, DR-60). The backend files the items and says how each feed's
// last check went (`GET /sources/channels/rss/collections`, `ChannelItemsCache`, never a Store domain); nothing here
// fetches a feed, and a row names no picture from the web: its mark is a bundled one the backend names, or its own site's
// icon asked of the backend (`FeedChannelMark`, DR-12, DR-52).

enum FeedChannelText {
    static let channel = "rss"

    /// A row's right edge: a failed last check first, in the backend's words, then how many items; a feed with nothing
    /// and no failure says that.
    static func meta(_ feed: SourceCollection, locale: Locale = .autoupdatingCurrent) -> String {
        let count = feed.count > 0 ? Copy.SourceBrowser.count(feed.count, channel: channel, locale: locale) : nil
        let parts = [feed.problem, count].compactMap { $0 }
        return parts.isEmpty ? Copy.SourceBrowser.feedNothingYet : parts.joined(separator: " · ")
    }

    /// The feed's own address and last check, in `.help` only.
    static func help(_ feed: SourceCollection, locale: Locale = .autoupdatingCurrent) -> String {
        let checked = ISODay(feed.polled).map { Copy.SourceBrowser.feedChecked(RelativeDay.full($0, locale: locale)) }
        return [feed.name, feed.url, checked].compactMap { $0 }.joined(separator: ", ")
    }

    /// The feeds to draw; empty when the backend names none, and the page keeps its plain list.
    static func feeds(_ tree: ChannelCollections?) -> [SourceCollection] {
        tree?.accounts.flatMap(\.collections) ?? []
    }
}

/// A feed's mark, decided once for both forms of its row: the bundled mark the backend names, else its site's own icon
/// and then that site's monogram (the saved link's rule), else, with no site (*Other*), a monogram of its name.
enum FeedChannelMarkModel: Equatable {
    case bundled(String)
    case link(SavedLinkMarkModel.Mark)

    static func of(_ feed: SourceCollection, markExists: (String) -> Bool = LogoImage.exists(name:)) -> Self {
        if let mark = feed.mark, markExists(mark) { return .bundled(mark) }
        return .link(SavedLinkMarkModel.mark(site: feed.site, host: feed.site, title: feed.name, door: .feed(feed.id)))
    }
}

/// The mark before a feed's name: always the same square, so rows stay aligned before and after an icon arrives.
struct FeedChannelMark: View {
    let feed: SourceCollection

    var body: some View {
        let side = CicadaTheme.scaled(SiteIconLayout.Size.inline.points)
        Group {
            switch FeedChannelMarkModel.of(feed) {
            case .bundled(let name): LogoImage(name: name, size: side)
            case .link(let mark): SavedLinkMark(mark: mark, size: .inline)
            }
        }
        .frame(width: side, height: side)
        .accessibilityHidden(true)
    }
}

struct FeedChannelsList: View {
    var saved = false
    let onDrill: (SourceDrill) -> Void

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(Store.self) private var store: Store?

    /// Re-read when the channels move (a poll lands here too; a 304 moves nothing).
    private var refreshKey: String {
        "\(store?.channels.loadedAt?.timeIntervalSinceReferenceDate ?? 0)"
    }

    var body: some View {
        let feeds = FeedChannelText.feeds(cache?.collections(FeedChannelText.channel))
        Group {
            if feeds.isEmpty {
                SourceItemsSection(channel: FeedChannelText.channel, saved: saved, query: "", onDrill: onDrill)
            } else {
                VStack(spacing: 0) {
                    ForEach(feeds) { FeedChannelRow(feed: $0, saved: saved, onDrill: onDrill) }
                }
            }
        }
        .task(id: refreshKey) {
            await cache?.refreshCollections(FeedChannelText.channel)
            // The page's status line and search prompt read the channel's whole list.
            await cache?.refresh(FeedChannelText.channel)
        }
    }
}

/// One feed: opens in place to its items when it has any; with none there is nothing to open, so no chevron acts.
struct FeedChannelRow: View {
    let feed: SourceCollection
    var saved = false
    let onDrill: (SourceDrill) -> Void

    @State private var open = false

    var body: some View {
        if feed.count > 0 {
            InPlaceDisclosureRow(title: feed.name, help: FeedChannelText.help(feed),
                                 count: FeedChannelText.meta(feed), open: $open) { FeedChannelMark(feed: feed) } content: {
                SourceItemsSection(channel: SourceListKey.make(FeedChannelText.channel, collection: feed.id),
                                   saved: saved, query: "", cap: nil, onDrill: onDrill)
                    .padding(.leading, CicadaTheme.scaled(22))
            }
        } else {
            HStack(spacing: CicadaTheme.spacingSM) {
                DisclosureChevron(isOpen: false).hidden()
                FeedChannelMark(feed: feed)
                Text(feed.name)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .help(FeedChannelText.help(feed))
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(FeedChannelText.meta(feed))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .padding(.horizontal, CicadaTheme.scaled(10))
            .accessibilityElement(children: .combine)
        }
    }
}
