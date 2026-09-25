import SwiftUI

// MARK: - MediaPreview (G11, Track V)
//
// Renders a rich, in-app preview of a saved media item, dispatching on the
// item's URL first and its stored `media_type` only afterwards (R-V1 — see
// `MediaPreviewModel.Kind`):
//   • image      → inline `ImageThumbnail` + tap-to-enlarge `ImageLightbox`
//   • embedVideo → thumbnail with a play affordance → embedded `WebView`
//                  running the provider's own player (YouTube, Vimeo, TikTok,
//                  Loom), at an embed url DERIVED from the entity's own saved
//                  url by `VideoRef` — never fetched, never lifted out of a
//                  provider's HTML (R-V4).
//   • fileVideo  → a real AVKit player in place (`VideoPlayerView`) for a
//                  direct `.mp4/.m4v/.mov/.webm/.m3u8` url or a `file://`
//                  clip the user saved themselves.
//   • instagram  → thumbnail/placeholder + "Open in Instagram" (login-walled,
//                  no in-app embed)
//   • url/bookmark (website) → an Open-Graph preview card (thumbnail + title +
//                  site + description) + a "Preview site" button → `WebView`
//                  loading ONLY the entity's stored url. A video we recognise
//                  but deliberately do not play (Twitch, a TikTok shortlink)
//                  lands here too, and honestly (R6).
// An "Open externally" affordance is always present as the robust fallback —
// for a local file that means Finder, not a browser (R9). The view is fed a
// normalized `MediaPreviewModel` so it works identically from an entity's
// `MediaBlock` and from a Feed `MediaFeedItem`.

/// Normalized input for `MediaPreview`. Built from a `MediaBlock` (entity
/// detail) or a `MediaFeedItem` (Feed). `description` is only available from the
/// entity body, so it's optional.
struct MediaPreviewModel {
    let url: String
    let mediaType: String
    let title: String
    let site: String?
    let channel: String?
    let thumbnail: String?
    var description: String? = nil

    init(block: MediaBlock, title: String, description: String? = nil) {
        self.url = block.url
        self.mediaType = block.mediaType
        self.title = title
        self.site = block.site
        self.channel = block.channel
        self.thumbnail = block.thumbnail
        self.description = description
    }

    init(item: MediaFeedItem) {
        self.url = item.url
        self.mediaType = item.mediaType
        self.title = item.title
        self.site = item.site
        self.channel = item.channel
        self.thumbnail = item.thumbnail
        self.description = nil
    }

    /// The kind of preview to render.
    ///
    /// R-V1: the **URL** decides. `mediaType` is a hint consulted only after
    /// the URL has been asked, because it is not trustworthy for video: the
    /// browser-sync path stamps `bookmark` on everything it imports and the
    /// TikTok export path stamps `url`, so a page's stored type says nothing
    /// about whether it is playable. Deriving at read is also what lets every
    /// item already on a bank start playing with no bank rewrite and no
    /// `url_index.json` migration (plan R1 / R15).
    ///
    /// An `external` ref (Twitch, a TikTok shortlink) deliberately gets **no
    /// new case** — there is nothing new to offer a video we have decided not
    /// to play, so it falls through to the website card it already was (R6).
    enum Kind: Equatable { case image, embedVideo(VideoRef), fileVideo(VideoRef), instagram, website }

    /// The resolved video reference for this item's url, if any. `nil` means
    /// "not a video" — never an error, never a network call (R2).
    var videoRef: VideoRef? { VideoRef.resolve(url) }

    var kind: Kind {
        if let ref = videoRef {
            switch ref.kind {
            case .embed: return .embedVideo(ref)
            case .file:  return .fileVideo(ref)
            case .external: break   // R6 — fall through to the legacy branches
            }
        }
        if (resolvedURL?.host ?? "").contains("instagram.com") { return .instagram }
        switch mediaType.lowercased() {
        case "instagram": return .instagram
        default:
            // For url/bookmark, treat as an image if the url itself points at an
            // image file. Otherwise it's a website card (the thumbnail, if any,
            // is the og:image — shown inside the card, not as a bare image).
            return MediaURLHelpers.isImageURL(url) ? .image : .website
        }
    }

    var resolvedURL: URL? { URL(string: url) }
    var thumbnailURL: URL? { thumbnail.flatMap { URL(string: $0) } }
}

// MARK: - URL helpers

/// What is left here after Track V: the image heuristic, and nothing else.
///
/// The three YouTube helpers this enum used to carry (`youtubeID`,
/// `youtubeEmbedURL`, `youtubeHeroEmbedURL`) are gone — `VideoRef` parses
/// every provider's id, including the `/live/` and `playlist?list=` shapes
/// they never handled, and a second YouTube id parser living beside it is
/// precisely the drift R-V8 exists to prevent. Their autoplay rule survives
/// as `VideoRef.autoplayURL` (R11) and their deliberate hero exception —
/// a hero renders on every visit, so it never autoplays — survives as the
/// hero reading `embedURL` directly.
enum MediaURLHelpers {
    /// Heuristic: does this url point directly at an image file?
    static func isImageURL(_ raw: String) -> Bool {
        guard let url = URL(string: raw) else { return false }
        let ext = url.pathExtension.lowercased()
        return ["jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "svg", "avif"].contains(ext)
    }
}

// MARK: - MediaPreview

struct MediaPreview: View {
    let model: MediaPreviewModel

    @State private var showSitePreview = false
    @State private var showVideoPlayer = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            switch model.kind {
            case .image:                imagePreview
            case .embedVideo(let ref):  embedVideoPreview(ref)
            case .fileVideo(let ref):   fileVideoPreview(ref)
            case .instagram:            instagramPreview
            case .website:              websitePreview
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .sheet(isPresented: $showSitePreview) { sitePreviewSheet }
        .sheet(isPresented: $showVideoPlayer) { videoPlayerSheet }
    }

    // MARK: image

    @ViewBuilder
    private var imagePreview: some View {
        if let url = model.resolvedURL {
            ImageThumbnail(url: url, width: 360, height: 220)
        } else {
            unavailable
        }
    }

    // MARK: embed video (YouTube, Vimeo, TikTok, Loom)

    /// Thumbnail + play badge → the provider's own player in a sheet. Reaching
    /// the sheet requires an `autoplayURL`; without one there is nothing to
    /// play in-app and the tap hands the watch url to the browser, which is
    /// what the YouTube-only version of this branch already did for a url
    /// whose id would not parse.
    @ViewBuilder
    private func embedVideoPreview(_ ref: VideoRef) -> some View {
        Button {
            if ref.autoplayURL != nil {
                showVideoPlayer = true
            } else {
                NSWorkspace.shared.open(ref.watchURL)
            }
        } label: {
            ZStack {
                if let thumb = model.thumbnailURL {
                    AsyncImage(url: thumb) { phase in
                        if case .success(let image) = phase {
                            image.resizable().scaledToFill()
                        } else {
                            CicadaTheme.surfaceHover
                        }
                    }
                } else {
                    CicadaTheme.surfaceHover
                }

                // Play affordance overlay.
                Image(systemName: "play.circle.fill")
                    .font(CicadaTheme.font(size: 48))
                    .foregroundStyle(.white.opacity(0.92))
                    .shadow(radius: 6)
            }
            .frame(width: 360, height: 202)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.cicadaPlain)
        .help("Play video")

        if let channel = model.channel, !channel.isEmpty {
            Label(channel, systemImage: "person.crop.circle")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        openExternallyButton
    }

    // MARK: file video (a direct url or a local clip)

    /// A real player in place — no thumbnail, no sheet. A file the user saved
    /// as a direct url is the one video Cicada can hand straight to AVKit
    /// (R-V4: never a stream Cicada resolved itself), so there is nothing to
    /// gain from making them tap through to it.
    ///
    /// Width is `maxWidth: .infinity`, not the `360` the thumbnail branches
    /// use: R-V5 widens the Feed sheet for video precisely because a small
    /// player in a big sheet reads as a regression, and a player pinned to 360
    /// would leave that widening doing nothing. No `.aspectRatio` either — an
    /// `NSViewRepresentable` has no intrinsic size, so a ratio here would be
    /// computed from the proposal rather than from the clip; `AVPlayerView`'s
    /// own `videoGravity = .resizeAspect` already letterboxes the real picture
    /// inside whatever box it is given, which is what keeps a portrait clip
    /// correct.
    @ViewBuilder
    private func fileVideoPreview(_ ref: VideoRef) -> some View {
        VideoPlayerView(url: ref.watchURL)
            .frame(maxWidth: .infinity, minHeight: 202, maxHeight: 360)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )

        if let channel = model.channel, !channel.isEmpty {
            Label(channel, systemImage: "person.crop.circle")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        externalAffordance(for: ref)
    }

    // MARK: instagram

    @ViewBuilder
    private var instagramPreview: some View {
        ZStack {
            if let thumb = model.thumbnailURL {
                AsyncImage(url: thumb) { phase in
                    if case .success(let image) = phase {
                        image.resizable().scaledToFill()
                    } else { instagramPlaceholder }
                }
            } else {
                instagramPlaceholder
            }
        }
        .frame(width: 360, height: 220)
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(CicadaTheme.border, lineWidth: 1)
        )

        // Instagram is login-walled — no in-app embed, only an external open.
        Button {
            if let url = model.resolvedURL { NSWorkspace.shared.open(url) }
        } label: {
            Label("Open in Instagram", systemImage: "arrow.up.right.square")
                .font(CicadaTheme.font(size: 12, weight: .medium))
                .foregroundStyle(CicadaTheme.mediaPink)
        }
        .buttonStyle(.cicadaPlain)
    }

    private var instagramPlaceholder: some View {
        ZStack {
            CicadaTheme.mediaPink.opacity(0.12)
            Image(systemName: "camera.aperture")
                .font(CicadaTheme.font(size: 30))
                .foregroundStyle(CicadaTheme.mediaPink.opacity(0.7))
        }
    }

    // MARK: website / bookmark

    @ViewBuilder
    private var websitePreview: some View {
        // Open-Graph preview card: thumbnail (og:image) + title + site + description.
        VStack(alignment: .leading, spacing: 0) {
            if let thumb = model.thumbnailURL {
                AsyncImage(url: thumb) { phase in
                    if case .success(let image) = phase {
                        image.resizable().scaledToFill()
                    } else {
                        siteThumbPlaceholder
                    }
                }
                .frame(height: 160)
                .frame(maxWidth: .infinity)
                .clipped()
            }

            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if let site = model.site, !site.isEmpty {
                    Text(site.uppercased())
                        .font(CicadaTheme.font(size: 10, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Text(model.title.isEmpty ? model.url : model.title)
                    .font(CicadaTheme.font(size: 14, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(2)
                if let desc = model.description, !desc.isEmpty {
                    Text(desc)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(3)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(CicadaTheme.spacingMD)
        }
        .frame(maxWidth: 420, alignment: .leading)
        .background(CicadaTheme.surface)
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(CicadaTheme.border, lineWidth: 1)
        )

        HStack(spacing: CicadaTheme.spacingMD) {
            Button { showSitePreview = true } label: {
                Label("Preview site", systemImage: "safari")
                    .font(CicadaTheme.font(size: 12, weight: .medium))
                    .foregroundStyle(CicadaTheme.accent)
            }
            .buttonStyle(.cicadaPlain)
            .help("Preview the saved page in-app")

            openExternallyButton
        }
    }

    private var siteThumbPlaceholder: some View {
        ZStack {
            CicadaTheme.surfaceHover
            Image(systemName: "globe")
                .font(CicadaTheme.font(size: 28))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    // MARK: shared affordances

    /// R9: a local file's "external" is Finder, not a browser. Handing a
    /// `file://` url to `NSWorkspace.open` launches whatever app claims the
    /// extension, which is a different (and often unwanted) action from "show
    /// me where this lives"; for every other provider the browser is still the
    /// right answer. "Open externally" is present on every video branch (R-V5)
    /// — this only decides *which* external.
    @ViewBuilder
    private func externalAffordance(for ref: VideoRef) -> some View {
        if ref.provider == .local {
            Button {
                NSWorkspace.shared.activateFileViewerSelecting([ref.watchURL])
            } label: {
                Label("Reveal in Finder", systemImage: "folder")
                    .font(CicadaTheme.font(size: 12))
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            .buttonStyle(.cicadaPlain)
            .help("Show the file in Finder")
        } else {
            openExternallyButton
        }
    }

    private var openExternallyButton: some View {
        Button {
            if let url = model.resolvedURL { NSWorkspace.shared.open(url) }
        } label: {
            Label("Open externally", systemImage: "arrow.up.right.square")
                .font(CicadaTheme.font(size: 12))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .buttonStyle(.cicadaPlain)
        .help("Open in your browser")
    }

    private var unavailable: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: "questionmark.circle")
                .font(CicadaTheme.font(size: 12))
            Text("No preview available")
                .font(CicadaTheme.captionFont)
        }
        .foregroundStyle(CicadaTheme.textTertiary)
    }

    // MARK: sheets

    @ViewBuilder
    private var sitePreviewSheet: some View {
        if let url = model.resolvedURL {
            WebPreviewSheet(
                title: model.title.isEmpty ? (model.site ?? "Preview") : model.title,
                url: url,
                externalURL: url
            )
        }
    }

    /// The provider's own player, opened by the embed branch's play badge.
    ///
    /// An `if let`, never `ref.embedURL!`: a force-unwrap in a sheet builder
    /// would turn a classification bug into a crash, which is why the
    /// YouTube-only version of this sheet was already written as a
    /// conditional. `autoplayURL` first because the user just tapped play
    /// (R11); `embedURL` is the fallback for a provider where autoplay is not
    /// a documented param. "Open externally" lands on `watchURL` — the real
    /// page, never the embed.
    @ViewBuilder
    private var videoPlayerSheet: some View {
        if let ref = model.videoRef, let playerURL = ref.autoplayURL ?? ref.embedURL {
            WebPreviewSheet(
                title: model.title.isEmpty ? "Video" : model.title,
                url: playerURL,
                externalURL: ref.watchURL
            )
        }
    }
}
