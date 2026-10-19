import SwiftUI

// MARK: - The wire

/// Sources v4 (owner 2026-10-19: "What I watched in one day: a dropdown and you see all the videos I watched that
/// day") — `GET /sources/watch-history/days/{episode}`: one watched day's videos, in the order watched. Read from the
/// day's own record; no model reads it (ruling 30).
struct WatchedDay: Codable, Hashable, Sendable {
    let episode: String
    let day: String
    let platform: String
    let videos: [WatchedVideo]

    enum CodingKeys: String, CodingKey { case episode, day, platform, videos }

    init(episode: String, day: String, platform: String = "youtube", videos: [WatchedVideo]) {
        self.episode = episode; self.day = day; self.platform = platform; self.videos = videos
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        day = try c.decodeIfPresent(String.self, forKey: .day) ?? ""
        platform = try c.decodeIfPresent(String.self, forKey: .platform) ?? ""
        videos = (try? c.decodeIfPresent([WatchedVideo].self, forKey: .videos)) ?? []
    }
}

struct WatchedVideo: Codable, Hashable, Sendable, Identifiable {
    let url: String
    let title: String
    var channel: String? = nil
    var times: [String] = []
    /// A YouTube video's id — the key its still is asked under (`SourcePictures.stillPath`).
    var videoId: String? = nil
    /// The saved page when the person also saved this video: a click lands where a saved item opens.
    var mediaEntityId: String? = nil

    var id: String { url }

    enum CodingKeys: String, CodingKey { case url, title, channel, times, videoId, mediaEntityId }

    init(url: String, title: String, channel: String? = nil, times: [String] = [], videoId: String? = nil,
         mediaEntityId: String? = nil) {
        self.url = url; self.title = title; self.channel = channel; self.times = times
        self.videoId = videoId; self.mediaEntityId = mediaEntityId
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decode(String.self, forKey: .url)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        channel = try? c.decodeIfPresent(String.self, forKey: .channel)
        times = (try? c.decodeIfPresent([String].self, forKey: .times)) ?? []
        videoId = try? c.decodeIfPresent(String.self, forKey: .videoId)
        mediaEntityId = try? c.decodeIfPresent(String.self, forKey: .mediaEntityId)
    }
}

extension APIClient {
    /// An episode id lands in a PATH: encoded like a channel id.
    nonisolated static func watchedDayPath(_ episode: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return "/sources/watch-history/days/\(episode.addingPercentEncoding(withAllowedCharacters: allowed) ?? episode)"
    }

    func fetchWatchedDay(episode: String, etag: String?) async throws -> Conditional<WatchedDay> {
        try await getConditional(Self.watchedDayPath(episode), etag: etag)
    }
}

// MARK: - The pure words

/// A watched day's and a watched video's words, pure (DR-58: computed when read).
enum WatchedDayText {
    /// The day's row: the day itself, said once ("Today", "Yesterday", a weekday, "Oct 3"), its full date in `.help`.
    static func day(_ item: ChannelItem, today: ISODay, locale: Locale = .autoupdatingCurrent)
        -> (text: String, help: String) {
        guard let day = ISODay(item.day) else { return (item.title, item.title) }
        return (RelativeDay.phrase(day, today: today, locale: locale), RelativeDay.full(day, locale: locale))
    }

    /// When a video was watched, on this Mac's clock ("8:04 PM", "8:04 PM, 9:10 PM"); empty when the door knew only
    /// the day.
    static func times(_ stamps: [String], locale: Locale = .autoupdatingCurrent,
                      timeZone: TimeZone = .autoupdatingCurrent) -> String {
        let parse = ISO8601DateFormatter()
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let out = DateFormatter()
        out.locale = locale
        out.timeZone = timeZone
        out.dateStyle = .none
        out.timeStyle = .short
        return stamps.compactMap { parse.date(from: $0) ?? fractional.date(from: $0) }
            .map { out.string(from: $0) }
            .joined(separator: ", ")
    }

    /// The video's second line: who made it and when it was watched.
    static func line(_ video: WatchedVideo, locale: Locale = .autoupdatingCurrent,
                     timeZone: TimeZone = .autoupdatingCurrent) -> String? {
        let parts = [video.channel, times(video.times, locale: locale, timeZone: timeZone)]
            .compactMap { $0?.isEmpty == false ? $0 : nil }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

/// Where a watched video opens: the saved item's own page when the person also saved it (Sleep › Saved), else the
/// provider's own watch page in the browser — the link target every other link uses (`LinkOpen`).
enum WatchedVideoRoute: Equatable {
    case saved(String)
    case browser(String)

    static func of(_ video: WatchedVideo) -> WatchedVideoRoute {
        if let id = video.mediaEntityId, !id.isEmpty { return .saved(id) }
        return .browser(video.url)
    }
}

// MARK: - The rows

/// Sources v4 — one watched day: the day, said once, and how many videos; a click opens the day in place to its videos
/// (DR-39: collapsed until asked; the read happens only then, and so does each still).
struct WatchedDayRow: View {
    let item: ChannelItem
    let today: ISODay

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(AppRouter.self) private var router: AppRouter?
    @State private var open: Bool

    init(item: ChannelItem, today: ISODay, initiallyOpen: Bool = false) {
        self.item = item
        self.today = today
        _open = State(initialValue: initiallyOpen)
    }
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let day = WatchedDayText.day(item, today: today)
        VStack(alignment: .leading, spacing: 0) {
            Button { Instant.run { open.toggle() } } label: {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: open ? "chevron.down" : "chevron.right")
                        .font(CicadaTheme.icon(.inline))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .frame(width: CicadaTheme.scaled(12))
                    Text(day.text)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                        .help(day.help)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if let n = item.videos {
                        Text(Copy.watchedVideos(n))
                            .font(CicadaTheme.metaFont)
                            .monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
                .padding(.horizontal, CicadaTheme.scaled(10))
                .background(hovering ? CicadaTheme.bgHover : Color.clear,
                            in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .onHover { hovering = $0 }
            .accessibilityLabel([day.help, item.videos.map { Copy.watchedVideos($0) }].compactMap { $0 }
                .joined(separator: ", "))
            .accessibilityValue(open ? Copy.Lists.expanded : Copy.Lists.collapsed)
            if open, let cache { videos(cache) }
        }
        .task(id: open) {
            guard open, let cache else { return }
            await cache.refreshDay(item.id)
        }
    }

    @ViewBuilder
    private func videos(_ cache: ChannelItemsCache) -> some View {
        if let day = cache.day(item.id) {
            if day.videos.isEmpty {
                note(Copy.watchedDayEmpty)
            } else {
                VStack(spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                    ForEach(day.videos) { video in
                        WatchedVideoRow(video: video) { route in
                            switch route {
                            case .saved(let id): router?.routeToSavedItem(id)
                            case .browser(let url): LinkOpen.browserOpen(url)
                            }
                        }
                    }
                }
                .padding(.leading, CicadaTheme.scaled(22))
            }
        } else if cache.dayFailed(item.id) {
            note(Copy.watchedDayFailed)
        } else {
            HStack(spacing: CicadaTheme.spacingXS) {
                ProgressView().controlSize(.small)
                note(Copy.watchedDayLoading)
            }
            .padding(.leading, CicadaTheme.scaled(22))
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
            .padding(.leading, CicadaTheme.scaled(32))
    }
}

/// One watched video (DR-34: a 56 pt two-line row): its still, the title, and who made it and when it was watched. A
/// click opens it where every link opens (`WatchedVideoRoute`); hover is a fill (DR-48, DR-63).
struct WatchedVideoRow: View {
    let video: WatchedVideo
    let open: (WatchedVideoRoute) -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let line = WatchedDayText.line(video)
        let route = WatchedVideoRoute.of(video)
        Button { open(route) } label: {
            HStack(spacing: CicadaTheme.scaled(10)) {
                VideoStill(videoId: video.videoId)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    Text(video.title)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    if let line {
                        Text(line)
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
            .padding(.horizontal, CicadaTheme.scaled(10))
            .background(hovering ? CicadaTheme.bgHover : Color.clear,
                        in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(route == .browser(video.url) ? Copy.watchedOpenHelp : Copy.watchedOpenSavedHelp)
        .accessibilityLabel([video.title, line].compactMap { $0 }.joined(separator: ", "))
    }
}

/// A video's still at 16:9, asked of Cicada's own API (which asks YouTube's own thumbnail host for that id only, behind
/// the picture gate) — until it arrives, or when there is none, a quiet play glyph on the selected fill.
private struct VideoStill: View {
    let videoId: String?

    @Environment(Store.self) private var store: Store?
    @State private var image: NSImage?

    var body: some View {
        let width = CicadaTheme.scaled(64)
        let height = width * 9 / 16
        ZStack {
            CicadaTheme.shape(CicadaTheme.scaled(4)).fill(CicadaTheme.bgSelected)
            if let image {
                Image(nsImage: image).resizable().interpolation(.high).scaledToFill()
                    .frame(width: width, height: height)
                    .clipShape(CicadaTheme.shape(CicadaTheme.scaled(4)))
            } else {
                Image(systemName: "play.fill")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .frame(width: width, height: height)
        .accessibilityHidden(true)
        .task(id: "\(store?.bank ?? "")|\(videoId ?? "")") {
            guard let path = SourcePictures.stillPath(videoId: videoId) else { image = nil; return }
            image = await SourcePictureStore.shared.image(path: path, bank: store?.bank ?? "")
        }
    }
}
