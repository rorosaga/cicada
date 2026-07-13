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
    /// the dispatch in `content(for:)` / `body` below — kept in sync
    /// deliberately (small enum, unlikely to drift) so the parent can decide
    /// layout inclusion without instantiating a view. Location entities
    /// always qualify: `LocationHero` itself degrades to an icon+name
    /// placeholder while geocoding or on failure, so there's always
    /// something worth the layout slot.
    static func hasPreviewableAsset(for entity: Entity) -> Bool {
        if entity.type == .location { return true }
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
        if entity.type == .location {
            LocationHero(entity: entity)
        } else if let media = entity.media, media.hasURL {
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

// MARK: - Location hero (single-pin MapKit map)
//
// A `location`-type entity's hero: a small MapKit map centered on the entity,
// one pin. Geocoding (`CLGeocoder`) is async and can fail or take a moment,
// so this always renders SOMETHING — an icon+name placeholder while
// resolving or on failure, the map once resolved — never an empty slot
// (mirrors `HeroPreview.hasPreviewableAsset` always returning true for
// `.location`). Results are cached in-memory per entity id (`resolveCache`)
// so re-renders (tab switches, scroll, parent re-layout) never re-geocode.

private struct LocationHero: View {
    let entity: Entity

    @State private var coordinate: CLLocationCoordinate2D?
    @State private var isResolved = false

    /// entity id → resolved coordinate, or `nil` for "geocoded and failed".
    /// The outer `Optional` from the dictionary lookup distinguishes "never
    /// attempted" (cache miss) from "attempted, no result" (cached `nil`).
    @MainActor
    private static var resolveCache: [String: CLLocationCoordinate2D?] = [:]

    var body: some View {
        Group {
            if let coordinate {
                mapView(coordinate)
            } else {
                placeholder
            }
        }
        .task(id: entity.id) {
            await resolve()
        }
    }

    @MainActor
    private func resolve() async {
        if let cached = Self.resolveCache[entity.id] {
            coordinate = cached
            isResolved = true
            return
        }

        // Prefer a lat/lon declared directly in frontmatter — no geocoding
        // round-trip needed, and immune to geocoder ambiguity. The backend
        // doesn't emit these keys today, but frontmatter is user/agent
        // editable, so honor them opportunistically if present.
        if let declared = Self.declaredCoordinate(from: entity.rawMarkdown) {
            coordinate = declared
            Self.resolveCache[entity.id] = declared
            isResolved = true
            return
        }

        do {
            let placemarks = try await CLGeocoder().geocodeAddressString(entity.name)
            let resolved = placemarks.first?.location?.coordinate
            coordinate = resolved
            Self.resolveCache[entity.id] = resolved
        } catch {
            coordinate = nil
            Self.resolveCache[entity.id] = nil
        }
        isResolved = true
    }

    private func mapView(_ coordinate: CLLocationCoordinate2D) -> some View {
        Map(initialPosition: .region(
            MKCoordinateRegion(
                center: coordinate,
                span: MKCoordinateSpan(latitudeDelta: 0.08, longitudeDelta: 0.08)
            )
        )) {
            Marker(entity.name, coordinate: coordinate)
        }
        .frame(maxWidth: .infinity)
        .frame(height: HeroPreview.maxHeight)
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius))
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                .stroke(CicadaTheme.border, lineWidth: 1)
        )
        .overlay(alignment: .bottomTrailing) {
            openInMapsButton(coordinate)
                .padding(CicadaTheme.spacingSM)
        }
    }

    private func openInMapsButton(_ coordinate: CLLocationCoordinate2D) -> some View {
        Button {
            let query = entity.name.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? entity.name
            let urlString = "https://maps.apple.com/?ll=\(coordinate.latitude),\(coordinate.longitude)&q=\(query)"
            if let url = URL(string: urlString) {
                NSWorkspace.shared.open(url)
            }
        } label: {
            Image(systemName: "arrow.up.forward.app")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .padding(6)
                .background(.ultraThinMaterial, in: Circle())
        }
        .buttonStyle(.plain)
        .help("Open in Maps")
    }

    /// Icon + name shown while resolving or when geocoding produced no
    /// coordinate — the "hide the map on failure" fallback. Not a loading
    /// spinner-only state: a location card without a pin is still worth
    /// showing the name in, so this doubles as the failure state too.
    private var placeholder: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            if isResolved {
                Image(systemName: "mappin.slash.circle")
                    .font(.system(size: 28))
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                ProgressView().controlSize(.small)
            }
            Text(entity.name)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity)
        .frame(height: HeroPreview.maxHeight)
        .background(CicadaTheme.surfaceHover.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius))
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius)
                .stroke(CicadaTheme.border, lineWidth: 1)
        )
    }

    /// Best-effort `lat:`/`lon:` (or `latitude:`/`longitude:`) top-level
    /// frontmatter scalars, mirroring the block-extraction style of
    /// `Entity.parseMediaFrontmatter` but reading UN-indented keys instead of
    /// a nested block. No backend support for these keys exists today — this
    /// only pays off if frontmatter is hand-edited or a future backend adds
    /// them — so it degrades to `nil` (→ geocoding) whenever absent.
    private static func declaredCoordinate(from raw: String) -> CLLocationCoordinate2D? {
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
