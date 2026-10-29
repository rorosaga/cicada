import SwiftUI
import MapKit

// MARK: - HeroPreview (G23/G25 + location map pin)
//
// A prominent image-rich preview rendered at the very TOP of an entity's
// rendered-markdown tab (see `EntityDetailCard.renderedMarkdownView`, ABOVE
// the G24 `SummaryBox`). Makes entity pages image-rich: a YouTube hero gets
// an in-app embedded player, a website/bookmark hero gets an OG-style card,
// any entity carrying a usable thumbnail gets a hero image, and a `location`
// entity gets a single-pin MapKit map.
//
// Reuses the existing media machinery rather than reinventing it:
//   • `MediaPreviewModel` (MediaPreview.swift) for the url → kind dispatch,
//     and `VideoRef` (VideoRef.swift) for the provider and its embed url —
//     derived from the entity's own saved url, never fetched (R-V1/R-V4).
//   • `WebView` (WebView.swift) for a provider's embedded player and
//     `VideoPlayerView` (VideoPlayerView.swift) for a direct/local file — the
//     ONLY url ever loaded is the entity's own media url (or the embed url
//     derived from it), mirroring the "only the media's url" invariant
//     elsewhere.
//   • `StoredPreview` for every picture: the one Cicada stores, never a provider's URL (owner rulings 2026-10-14).
//
// KNOWN, DISCLOSED, NOT FIXED HERE: a `media` entity page renders BOTH this
// hero and `MediaPreview` — `EntityDetailCard.contentTab` shows the preview
// card and, inside `renderedMarkdownView`, the hero, as siblings in one
// VStack. That predates Track V (a YouTube thumbnail card above a hero embed);
// after it, the same clip has two players on one page. It is safe because
// neither starts on its own — `AVPlaybackController` constructs paused and the
// embed hero never autoplays (R11) — and collapsing the two surfaces is an
// `EntityDetailCard` layout decision that belongs to whoever takes it, not a
// video-renderer change smuggled in here.
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
    /// the dispatch in `content(for:)` / `body` below — kept in sync
    /// deliberately (small enum, unlikely to drift) so the parent can decide
    /// layout inclusion without instantiating a view. Location entities
    /// always qualify: `LocationHero` itself degrades to an icon+name
    /// placeholder while geocoding or on failure, so there's always
    /// something worth the layout slot. A `.fileVideo` qualifies for the same
    /// reason even when the file has moved — `VideoPlayerView` renders the
    /// "can't read this file" card with the path and Reveal in Finder (R9),
    /// which is more useful than silently dropping the hero.
    static func hasPreviewableAsset(for entity: Entity) -> Bool {
        if entity.type == .location { return true }
        guard let media = entity.media, media.hasURL else { return false }
        let model = MediaPreviewModel(block: media, title: entity.name)
        switch model.kind {
        case .embedVideo, .fileVideo:
            return true
        case .image:
            // Owner rulings 2026-10-14: only the picture Cicada stores — the provider's URL is never loaded.
            return model.hasPicture
        case .instagram:
            return model.hasPicture
        case .website:
            return model.hasPicture || !(model.site ?? "").isEmpty
        }
    }

    var body: some View {
        if entity.type == .location {
            LocationHero(entity: entity)
        } else if let media = entity.media, media.hasURL {
            content(for: MediaPreviewModel(block: media, title: entity.name))
        }
    }

    @ViewBuilder
    private func content(for model: MediaPreviewModel) -> some View {
        switch model.kind {
        case .embedVideo(let ref):
            EmbedVideoHero(model: model, ref: ref)

        case .fileVideo(let ref):
            FileVideoHero(ref: ref)

        case .image:
            if model.hasPicture {
                HeroStoredImage(path: model.preview)
            }

        case .instagram:
            // Login-walled — no in-app embed, but a saved thumbnail is still
            // a "usable image" per the catch-all rule.
            if model.hasPicture {
                HeroStoredImage(path: model.preview)
            }

        case .website:
            if model.hasPicture {
                WebsiteHero(model: model)
            } else if let site = model.site, !site.isEmpty {
                CompactSiteHero(model: model)
            }
        }
    }
}

// MARK: - Embed-provider hero (in-app playback)

/// A provider's own player, inline at the top of the entity page — YouTube,
/// Vimeo, TikTok or Loom, whichever `VideoRef` resolved from the entity's own
/// saved url. It was `YouTubeHero` until Track V, when the embed url stopped
/// coming from a YouTube-only helper and started coming from `VideoRef`; the
/// name went with the parser.
///
/// It reads `ref.embedURL` and **never `ref.autoplayURL`** — a hero renders on
/// every visit to the page rather than behind an explicit tap, so autoplaying
/// would be surprising (R11). That was the YouTube-only rule
/// `youtubeHeroEmbedURL` carried, and generalizing the player must not lose it.
private struct EmbedVideoHero: View {
    let model: MediaPreviewModel
    let ref: VideoRef

    var body: some View {
        if let embedURL = ref.embedURL {
            WebView(url: embedURL)
                .frame(maxWidth: .infinity)
                .frame(height: HeroPreview.maxHeight)
                .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
                .overlay(
                    CicadaTheme.shape(CicadaTheme.cornerRadius)
                        .stroke(CicadaTheme.border, lineWidth: 1)
                )
        } else {
            // Defensive only: a `.embedVideo` kind means `VideoRef` resolved
            // `kind == .embed`, and every embed row in the fixture carries an
            // `embedUrl` — so this branch is unreachable today. Kept rather
            // than force-unwrapped because the alternative to a thumbnail is a
            // crash on the entity page, and because a future provider whose
            // `URL(string:)` fails would land here quietly.
            thumbnailFallback
        }
    }

    private var thumbnailFallback: some View {
        Button {
            if let url = model.resolvedURL { NSWorkspace.shared.open(url) }
        } label: {
            ZStack {
                if model.hasPicture {
                    StoredPreview(path: model.preview) { CicadaTheme.surfaceHover }
                } else {
                    CicadaTheme.surfaceHover
                }

                Image(systemName: "play.circle.fill")
                    .font(CicadaTheme.font(size: 52))
                    .foregroundStyle(.white.opacity(0.92))
                    .shadow(radius: 8)
            }
            .frame(maxWidth: .infinity)
            .frame(height: HeroPreview.maxHeight)
            .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
            .overlay(
                CicadaTheme.shape(CicadaTheme.cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.cicadaPlain)
        .help("Open video")
    }
}

// MARK: - Direct / local file hero (AVKit in place)

/// A direct `.mp4/.m4v/.mov/.webm/.m3u8` url or a `file://` clip the user
/// saved themselves: a real transport-controlled player at the top of the
/// page, not a thumbnail that has to be tapped.
///
/// Starts **paused** by construction — `AVPlaybackController` builds its
/// player without calling `play()` — which is what makes it safe in a hero
/// slot that renders on every visit, the same rule `EmbedVideoHero` follows by
/// refusing `autoplayURL` (R11).
///
/// `VideoPlayerView` decides for itself whether the file is readable and shows
/// the fix (path + Reveal in Finder) when it is not (R9), so this slot is
/// never a black rectangle — which is also why `hasPreviewableAsset` returns
/// true for a `.fileVideo` whose file has since moved: the card explaining
/// that is worth the slot, for the same reason `LocationHero` always is.
private struct FileVideoHero: View {
    let ref: VideoRef

    var body: some View {
        VideoPlayerView(url: ref.watchURL)
            .frame(maxWidth: .infinity)
            .frame(height: HeroPreview.maxHeight)
            .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
            .overlay(
                CicadaTheme.shape(CicadaTheme.cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
    }
}

// MARK: - Hero stored picture (a login-walled page's saved preview)

/// The stored preview at hero size — a saved image, or a login-walled page's saved preview.
private struct HeroStoredImage: View {
    let path: String?

    var body: some View {
        StoredPreview(path: path) {
            ZStack {
                CicadaTheme.mediaPink.opacity(0.1)
                Image(systemName: "photo")
                    .font(CicadaTheme.font(size: 28))
                    .foregroundStyle(CicadaTheme.mediaPink.opacity(0.6))
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: HeroPreview.maxHeight)
        .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
        .overlay(
            CicadaTheme.shape(CicadaTheme.cornerRadius)
                .stroke(CicadaTheme.border, lineWidth: 1)
        )
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
                if model.hasPicture {
                    StoredPreview(path: model.preview) { siteThumbPlaceholder }
                    .frame(maxWidth: .infinity)
                    .frame(height: HeroPreview.maxHeight - 64)
                    .clipped()
                }

                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    if let site = model.site, !site.isEmpty {
                        Text(site.uppercased())
                            .font(CicadaTheme.font(size: 10, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    Text(model.title.isEmpty ? model.url : model.title)
                        .font(CicadaTheme.font(size: 15, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(2)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(CicadaTheme.spacingMD)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.surface)
            .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
            .overlay(
                CicadaTheme.shape(CicadaTheme.cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.cicadaPlain)
        .help("Open \(model.site ?? "site")")
    }

    private var siteThumbPlaceholder: some View {
        ZStack {
            CicadaTheme.surfaceHover
            Image(systemName: "globe")
                .font(CicadaTheme.font(size: 26))
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
                        .font(CicadaTheme.font(size: 18))
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .frame(width: 40, height: 40)

                VStack(alignment: .leading, spacing: 2) {
                    if let site = model.site, !site.isEmpty {
                        Text(site.uppercased())
                            .font(CicadaTheme.font(size: 10, weight: .semibold))
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    Text(model.title.isEmpty ? model.url : model.title)
                        .font(CicadaTheme.font(size: 14, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)
                }

                Spacer()

                Image(systemName: "arrow.up.right.square")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            .padding(CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.surface)
            .clipShape(CicadaTheme.shape(CicadaTheme.cornerRadius))
            .overlay(
                CicadaTheme.shape(CicadaTheme.cornerRadius)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.cicadaPlain)
    }
}

// MARK: - Location hero (ruling 48 part 6: a still of the native map, from stored coordinates)
//
// A `location` page's hero is `PlaceMap`: a still drawn from the coordinates the page stores, never a geocode on open
// (until 2026-10-29 this view geocoded the page's NAME through Apple on every first open). It always renders
// something — a quiet placeholder until the still is drawn — so `HeroPreview.hasPreviewableAsset` keeps returning true
// for `.location`.

struct LocationHero: View {
    let entity: Entity

    var body: some View {
        PlaceMap(entity: entity)
    }

    /// Best-effort `lat:`/`lon:` (or `latitude:`/`longitude:`) top-level
    /// frontmatter scalars, mirroring the block-extraction style of
    /// `Entity.parseMediaFrontmatter` but reading UN-indented keys instead of
    /// a nested block. No backend support for these keys exists today — this
    /// only pays off if frontmatter is hand-edited or a future backend adds
    /// them — so it degrades to `nil` (→ geocoding) whenever absent.
    static func declaredCoordinate(from raw: String) -> CLLocationCoordinate2D? {
        guard !raw.isEmpty else { return nil }
        let lines = raw.components(separatedBy: "\n")
        var fmLines: [String] = []
        var inBlock = false
        for line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed == "---" {
                if inBlock { break }   // closing fence
                inBlock = true
                continue
            }
            if inBlock { fmLines.append(line) }
        }
        guard !fmLines.isEmpty else { return nil }

        var lat: Double?
        var lon: Double?
        for line in fmLines {
            // Only top-level (unindented) scalar keys.
            guard let first = line.first, first != " ", first != "\t" else { continue }
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard let colon = trimmed.firstIndex(of: ":") else { continue }
            let key = String(trimmed[..<colon]).trimmingCharacters(in: .whitespaces).lowercased()
            var value = String(trimmed[trimmed.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
            if value.count >= 2, value.first == "\"", value.last == "\"" {
                value = String(value.dropFirst().dropLast())
            }
            switch key {
            case "lat", "latitude": lat = Double(value)
            case "lon", "lng", "longitude": lon = Double(value)
            default: break
            }
        }
        guard let lat, let lon else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lon)
    }
}
