import SwiftUI

// MARK: - HeroPreview (G23/G25)
//
// A prominent image-rich preview rendered at the very TOP of an entity's
// rendered-markdown tab (see `EntityDetailCard.renderedMarkdownView`, ABOVE
// the G24 `SummaryBox`). Makes entity pages image-rich: a YouTube hero gets
// an in-app embedded player, a website/bookmark hero gets an OG-style card,
// and any entity carrying a usable thumbnail gets a hero image.
//
// Reuses the existing media machinery rather than reinventing it:
//   • `MediaPreviewModel` / `MediaURLHelpers` (MediaPreview.swift) for the
//     url → kind dispatch and YouTube id/embed-url extraction.
//   • `WebView` (WebView.swift) for the embedded player — the ONLY url ever
//     loaded is the entity's own media url (or the embed url derived from
//     it), mirroring the "only the media's url" invariant elsewhere.
//   • `ImageLightbox` (ImageLightbox.swift) for tap-to-enlarge.
//
// Renders NOTHING when the entity has no previewable asset — no empty card,
// no reserved layout slot. Callers should gate inclusion with
// `HeroPreview.hasPreviewableAsset(for:)` (see EntityDetailCard) rather than
// always inserting `HeroPreview` and relying on it to self-collapse, so a
// non-previewable entity doesn't even cost a VStack spacing gap.
struct HeroPreview: View {
    let entity: Entity

    /// Bounded hero height (spec: "bounded in height, e.g. hero max ~220pt").
    static let maxHeight: CGFloat = 220

    /// Whether this entity has anything worth rendering as a hero. Mirrors
    /// the dispatch in `content(for:)` below — kept in sync deliberately
    /// (small enum, unlikely to drift) so the parent can decide layout
    /// inclusion without instantiating a view.
    static func hasPreviewableAsset(for entity: Entity) -> Bool {
        guard let media = entity.media, media.hasURL else { return false }
        let model = MediaPreviewModel(block: media, title: entity.name)
        switch model.kind {
        case .youtube, .image:
            return true
        case .instagram:
            return model.thumbnailURL != nil
        case .website:
            return model.thumbnailURL != nil || !(model.site ?? "").isEmpty
        }
    }

    var body: some View {
        if let media = entity.media, media.hasURL {
            content(for: MediaPreviewModel(block: media, title: entity.name))
        }
    }

    @ViewBuilder
    private func content(for model: MediaPreviewModel) -> some View {
        switch model.kind {
        case .youtube:
            YouTubeHero(model: model)

        case .image:
            if let url = model.resolvedURL {
                HeroImage(url: url)
            }

        case .instagram:
            // Login-walled — no in-app embed, but a saved thumbnail is still
            // a "usable image" per the catch-all rule.
            if let thumb = model.thumbnailURL {
                HeroImage(url: thumb)
            }

        case .website:
            if model.thumbnailURL != nil {
                WebsiteHero(model: model)
            } else if let site = model.site, !site.isEmpty {
                CompactSiteHero(model: model)
            }
        }
    }
}

// MARK: - YouTube hero (in-app playback)

private struct YouTubeHero: View {
    let model: MediaPreviewModel

    var body: some View {
        if let embedURL = MediaURLHelpers.youtubeHeroEmbedURL(from: model.url) {
            WebView(url: embedURL)
                .frame(maxWidth: .infinity)
                .frame(height: HeroPreview.maxHeight)
                .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius))
                .overlay(
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                        .stroke(CicadaTheme.border, lineWidth: 1)
                )
        } else {
            // Couldn't cleanly extract a video id — fall back to the
            // thumbnail with a play badge that opens the url externally.
            thumbnailFallback
        }
    }

    private var thumbnailFallback: some View {
        Button {
            if let url = model.resolvedURL { NSWorkspace.shared.open(url) }
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

                Image(systemName: "play.circle.fill")
                    .font(.system(size: 52))
                    .foregroundStyle(.white.opacity(0.92))
                    .shadow(radius: 8)
            }
            .frame(maxWidth: .infinity)
            .frame(height: HeroPreview.maxHeight)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .help("Open video")
    }
}

// MARK: - Hero image (any entity with a usable thumbnail/image url)

private struct HeroImage: View {
    let url: URL
    @State private var showLightbox = false

    var body: some View {
        Button { showLightbox = true } label: {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFill()
                case .failure:
                    placeholder(symbol: "photo")
                case .empty:
                    ZStack {
                        CicadaTheme.surfaceHover
                        ProgressView().controlSize(.small)
                    }
                @unknown default:
                    placeholder(symbol: "photo")
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: HeroPreview.maxHeight)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .help("Click to enlarge")
        .sheet(isPresented: $showLightbox) {
            ImageLightbox(url: url)
        }
    }

    private func placeholder(symbol: String) -> some View {
        ZStack {
            CicadaTheme.mediaPink.opacity(0.1)
            Image(systemName: symbol)
                .font(.system(size: 28))
                .foregroundStyle(CicadaTheme.mediaPink.opacity(0.6))
        }
    }
}

// MARK: - Website / bookmark hero (OG-style card)

private struct WebsiteHero: View {
    let model: MediaPreviewModel

    var body: some View {
        Button {
            if let url = model.resolvedURL { NSWorkspace.shared.open(url) }
        } label: {
            VStack(alignment: .leading, spacing: 0) {
                if let thumb = model.thumbnailURL {
                    AsyncImage(url: thumb) { phase in
                        if case .success(let image) = phase {
                            image.resizable().scaledToFill()
                        } else {
                            siteThumbPlaceholder
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .frame(height: HeroPreview.maxHeight - 64)
                    .clipped()
                }

                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    if let site = model.site, !site.isEmpty {
                        Text(site.uppercased())
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    Text(model.title.isEmpty ? model.url : model.title)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(2)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(CicadaTheme.spacingMD)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .help("Open \(model.site ?? "site")")
    }

    private var siteThumbPlaceholder: some View {
        ZStack {
            CicadaTheme.surfaceHover
            Image(systemName: "globe")
                .font(.system(size: 26))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}

// MARK: - Compact site hero (bookmark with a site, no thumbnail)

private struct CompactSiteHero: View {
    let model: MediaPreviewModel

    var body: some View {
        Button {
            if let url = model.resolvedURL { NSWorkspace.shared.open(url) }
        } label: {
            HStack(spacing: CicadaTheme.spacingMD) {
                ZStack {
                    Circle().fill(CicadaTheme.surfaceHover)
                    Image(systemName: "globe")
                        .font(.system(size: 18))
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .frame(width: 40, height: 40)

                VStack(alignment: .leading, spacing: 2) {
                    if let site = model.site, !site.isEmpty {
                        Text(site.uppercased())
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    Text(model.title.isEmpty ? model.url : model.title)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                }

                Spacer()

                Image(systemName: "arrow.up.right.square")
                    .font(.system(size: 12))
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            .padding(CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}
