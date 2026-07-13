import SwiftUI

// MARK: - MediaPreview (G11)
//
// Renders a rich, in-app preview of a saved media item, dispatching on
// `media_type`:
//   • image    → inline `ImageThumbnail` + tap-to-enlarge `ImageLightbox`
//   • youtube  → thumbnail with a play affordance → embedded `WebView` player
//                (YouTube embed url DERIVED from the entity's own watch url)
//   • instagram→ thumbnail/placeholder + "Open in Instagram" (login-walled,
//                no in-app embed)
//   • url/bookmark (website) → an Open-Graph preview card (thumbnail + title +
//                site + description) + a "Preview site" button → `WebView`
//                loading ONLY the entity's stored url.
// A global "Open externally" affordance is always present as the robust
// fallback. The view is fed a normalized `MediaPreviewModel` so it works
// identically from an entity's `MediaBlock` and from a Feed `MediaFeedItem`.

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

    /// The kind of preview to render. Centralizes the heuristic so the view body
    /// stays declarative.
    enum Kind { case image, youtube, instagram, website }

    var kind: Kind {
        switch mediaType.lowercased() {
        case "youtube": return .youtube
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

enum MediaURLHelpers {
    /// Heuristic: does this url point directly at an image file?
    static func isImageURL(_ raw: String) -> Bool {
        guard let url = URL(string: raw) else { return false }
        let ext = url.pathExtension.lowercased()
        return ["jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "svg", "avif"].contains(ext)
    }

    /// Extract a YouTube video id from a watch / youtu.be / embed url, then build
    /// the privacy-preserving embed url. Returns nil if no id is found. The id is
    /// derived ONLY from the entity's own stored url (security rule).
    static func youtubeEmbedURL(from raw: String) -> URL? {
        guard let id = youtubeID(from: raw) else { return nil }
        // autoplay=1: the user already tapped the play affordance to open the
        // player sheet, so starting playback immediately matches their intent.
        return URL(string: "https://www.youtube-nocookie.com/embed/\(id)?autoplay=1")
    }

    /// Embed url for the HERO player (G23/G25) — same id-extraction as
    /// `youtubeEmbedURL` above, but WITHOUT `autoplay=1`. The hero renders
    /// inline at the top of the entity page on every visit (not behind an
    /// explicit tap like the sheet player), so autoplaying would be
    /// surprising; the user presses play in-page instead.
    static func youtubeHeroEmbedURL(from raw: String) -> URL? {
        guard let id = youtubeID(from: raw) else { return nil }
        return URL(string: "https://www.youtube-nocookie.com/embed/\(id)")
    }

    static func youtubeID(from raw: String) -> String? {
        guard let comps = URLComponents(string: raw) else { return nil }
        // youtu.be/<id>
        if let host = comps.host, host.contains("youtu.be") {
            let id = comps.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            return id.isEmpty ? nil : id
        }
        // youtube.com/watch?v=<id>
        if let v = comps.queryItems?.first(where: { $0.name == "v" })?.value, !v.isEmpty {
            return v
        }
        // youtube.com/embed/<id>  or  /shorts/<id>
        let parts = comps.path.split(separator: "/").map(String.init)
        if let idx = parts.firstIndex(where: { $0 == "embed" || $0 == "shorts" }),
           idx + 1 < parts.count {
            return parts[idx + 1]
        }
        return nil
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
            case .image:    imagePreview
            case .youtube:  youtubePreview
            case .instagram: instagramPreview
            case .website:  websitePreview
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

    // MARK: youtube

    @ViewBuilder
    private var youtubePreview: some View {
        Button {
            if MediaURLHelpers.youtubeEmbedURL(from: model.url) != nil {
                showVideoPlayer = true
            } else if let url = model.resolvedURL {
                NSWorkspace.shared.open(url)
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
                    .font(.system(size: 48))
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
        .buttonStyle(.plain)
        .help("Play video")

        if let channel = model.channel, !channel.isEmpty {
            Label(channel, systemImage: "person.crop.circle")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        openExternallyButton
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
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(CicadaTheme.mediaPink)
        }
        .buttonStyle(.plain)
    }

    private var instagramPlaceholder: some View {
        ZStack {
            CicadaTheme.mediaPink.opacity(0.12)
            Image(systemName: "camera.aperture")
                .font(.system(size: 30))
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
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Text(model.title.isEmpty ? model.url : model.title)
                    .font(.system(size: 14, weight: .semibold))
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
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(CicadaTheme.accent)
            }
            .buttonStyle(.plain)
            .help("Preview the saved page in-app")

            openExternallyButton
        }
    }

    private var siteThumbPlaceholder: some View {
        ZStack {
            CicadaTheme.surfaceHover
            Image(systemName: "globe")
                .font(.system(size: 28))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    // MARK: shared affordances

    private var openExternallyButton: some View {
        Button {
            if let url = model.resolvedURL { NSWorkspace.shared.open(url) }
        } label: {
            Label("Open externally", systemImage: "arrow.up.right.square")
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .buttonStyle(.plain)
        .help("Open in your browser")
    }

    private var unavailable: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: "questionmark.circle")
                .font(.system(size: 12))
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

    @ViewBuilder
    private var videoPlayerSheet: some View {
        if let embed = MediaURLHelpers.youtubeEmbedURL(from: model.url),
           let external = model.resolvedURL {
            WebPreviewSheet(
                title: model.title.isEmpty ? "Video" : model.title,
                url: embed,
                externalURL: external
            )
        }
    }
}
