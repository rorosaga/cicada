import SwiftUI
import AppKit

/// Two jobs, one view.
///
/// **Bundled mode** (`LogoImage(name:)`) is the original: a small square PNG
/// from `Resources/logos/<name>.png` keyed by a provider id (`claude-code`,
/// `codex`, `chrome`, …), loaded off the main thread and cached for the life
/// of the process.
///
/// **Entity mode** (`LogoImage(entityId:name:type:)`, G59) renders an entity's
/// own logo: `GET /entities/{id}/logo` via `LogoStore` (memory + disk cached),
/// falling back to a monogram on the entity-type color. Always a **circle**
/// with a 1-pt hairline ring, so an entity reads the same in the detail card,
/// the inbox, the cluster list and an Ask citation.
struct LogoImage: View {
    enum Source: Equatable {
        case bundled(String)
        case entity(id: String, name: String, type: EntityType)
    }

    let source: Source
    var size: CGFloat = 28

    @Environment(Store.self) private var store
    @State private var image: NSImage?

    init(name: String, size: CGFloat = 28) {
        self.source = .bundled(name)
        self.size = size
    }

    init(entityId: String, name: String, type: EntityType = .concept, size: CGFloat = 28) {
        self.source = .entity(id: entityId, name: name, type: type)
        self.size = size
    }

    var body: some View {
        Group {
            switch source {
            case .bundled:
                bundledBody
            case let .entity(_, name, type):
                entityBody(name: name, type: type)
            }
        }
        .frame(width: size, height: size)
        .task(id: taskKey) { await load() }
    }

    private var taskKey: String {
        switch source {
        case let .bundled(name): "bundled:\(name)"
        case let .entity(id, _, _): "entity:\(id):\(store.bank)"
        }
    }

    @ViewBuilder
    private var bundledBody: some View {
        if let image {
            Image(nsImage: image).resizable().interpolation(.high).scaledToFit()
        } else {
            Image(systemName: "app")
                .resizable().scaledToFit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(size * 0.2)
        }
    }

    @ViewBuilder
    private func entityBody(name: String, type: EntityType) -> some View {
        ZStack {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFill()
            } else {
                CicadaTheme.entityColor(for: type)
                Text(Self.monogram(for: name))
                    .font(CicadaTheme.font(size: size * 0.42, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))
        .accessibilityLabel(name)
    }

    private func load() async {
        switch source {
        case let .bundled(name):
            image = await Self.bundledImage(for: name)
        case let .entity(id, _, _):
            image = await LogoStore.shared.image(entityId: id, bank: store.bank)
        }
    }

    /// Initials for the monogram fallback: the first letter or digit of the
    /// first two words, uppercased. `?` when there is nothing usable — never
    /// an empty circle.
    static func monogram(for name: String) -> String {
        let words = name
            .split(whereSeparator: { $0.isWhitespace || $0 == "/" || $0 == "_" || $0 == "-" })
            .compactMap { word -> Character? in
                word.first(where: { $0.isLetter || $0.isNumber })
            }
        let initials = words.prefix(2)
        return initials.isEmpty ? "?" : String(initials).uppercased()
    }

    /// Cheap synchronous existence check for a *bundled* logo (a bundle
    /// resource lookup, not a file read) so callers can pick a fallback layout
    /// without waiting on the async PNG decode.
    static func exists(name: String) -> Bool {
        Bundle.cicadaResources.url(forResource: name, withExtension: "png", subdirectory: "Resources/logos") != nil
    }

    // MARK: - Bundled cache

    @MainActor
    private static var cache: [String: NSImage] = [:]

    private static func bundledImage(for name: String) async -> NSImage? {
        if let cached = await MainActor.run(body: { cache[name] }) { return cached }
        let loaded = await Task.detached(priority: .utility) {
            guard let url = Bundle.cicadaResources.url(
                forResource: name, withExtension: "png", subdirectory: "Resources/logos"
            ) else { return nil as NSImage? }
            return NSImage(contentsOf: url)
        }.value
        if let loaded { await MainActor.run { cache[name] = loaded } }
        return loaded
    }

    // MARK: - Platform tile (Task 13)

    /// Linear-style "Connected accounts" tile: a rounded-square card with a
    /// subtle background and a hairline border, the brand mark centered and
    /// inset so a full-bleed source PNG (X's plain black square, same deal as
    /// the existing `codex.png`) and a transparent-cornered one (Instagram,
    /// Reddit, …) read the same. Radius scales proportionally with `size` (8pt
    /// at the reference 40pt).
    ///
    /// Missing-logo fallback is `systemFallback` — the tile's OWN existing SF
    /// Symbol, not a generic glyph — checked with the same synchronous
    /// `exists(name:)` lookup `AddSourceTile.tileButton` used before this
    /// existed, so a platform with no fetched PNG (or, vanishingly rarely, a
    /// corrupt one `LogoImage`'s own decode falls back on) never renders
    /// blank.
    ///
    /// `bundleId` is the R-L1 rung and wins over the PNG: an app installed on
    /// this Mac carries a mark that is by definition current, and R2 forbids
    /// ever committing one for Safari or Apple Notes. It defaults to `nil` so
    /// the call sites that have no app behind them (the platform rows) read
    /// exactly as before. R6 — this is the SAME precedence `OriginMark` runs,
    /// deliberately: the Sleep desk, the Sources grid, the `+` catalog and
    /// Settings → Integrations must not disagree about what Safari looks like.
    static func platformTile(name: String, bundleId: String? = nil, size: CGFloat = 40,
                             systemFallback: String = "app") -> some View {
        PlatformTile(name: name, bundleId: bundleId, size: size, systemFallback: systemFallback)
    }
}

private struct PlatformTile: View {
    let name: String
    /// The installed app whose icon is this tile's mark, when there is one
    /// (R-L1). Nil on every machine where that app is absent, which is why
    /// the PNG and SF Symbol rungs below it stay.
    var bundleId: String?
    let size: CGFloat
    let systemFallback: String

    /// 8pt at the reference 40pt size, scaling proportionally either way.
    private var cornerRadius: CGFloat { size * 0.2 }
    private var markSize: CGFloat { Self.markSize(for: size) }

    static func markSize(for size: CGFloat) -> CGFloat { size * 0.6 }

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: cornerRadius)
                .fill(CicadaTheme.surfaceElevated)
            RoundedRectangle(cornerRadius: cornerRadius)
                .stroke(CicadaTheme.border, lineWidth: 1)
            if let bundleId, let icon = InstalledAppIcon.image(bundleId: bundleId, size: markSize) {
                Image(nsImage: icon)
                    .resizable().interpolation(.high).scaledToFit()
                    .frame(width: markSize, height: markSize)
            } else if LogoImage.exists(name: name) {
                LogoImage(name: name, size: markSize)
                    .clipShape(RoundedRectangle(cornerRadius: cornerRadius * 0.5))
            } else {
                Image(systemName: systemFallback)
                    .font(CicadaTheme.font(size: size * 0.42, weight: .medium))
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}
