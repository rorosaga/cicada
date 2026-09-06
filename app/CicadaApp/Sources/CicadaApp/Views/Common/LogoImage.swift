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
        // R-L5: reading `CicadaTheme.mode` (through `resolvedName`) HERE is
        // what subscribes the view to the theme and what changes the task id
        // on a flip, so the mark reloads its `-dark` sibling. Keying on the
        // bare name repaints nothing — the `.task` never re-runs and the
        // previous theme's `NSImage` stays on screen.
        case let .bundled(name): "bundled:\(Self.resolvedName(for: name) ?? name)"
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

    /// The file to load for `name` under the active theme (R-L5): a
    /// `<name>-dark` sibling when the theme is dark and one is bundled, else
    /// `<name>`, else nil. Only monochrome marks ship a sibling (R4 of the
    /// Track L plan) — a coloured mark reads in both themes and is never
    /// recoloured, so `chrome` resolves to `chrome` in either.
    ///
    /// Reading `CicadaTheme.mode` inside a SwiftUI `body` subscribes the view
    /// to the theme, so a light/dark flip repaints the mark with no extra
    /// wiring — the same mechanism every `CicadaTheme.<token>` call site uses.
    /// `taskKey` is where that read happens for the bundled path.
    ///
    /// A name that already carries the suffix is returned untouched: the
    /// sibling is a file in its own right and asking for it by name must never
    /// look for `x-dark-dark`.
    static func resolvedName(for name: String) -> String? {
        if CicadaTheme.mode == .dark, !name.hasSuffix("-dark"), exists(name: "\(name)-dark") {
            return "\(name)-dark"
        }
        return exists(name: name) ? name : nil
    }

    /// Cheap synchronous existence check for a *bundled* logo (a bundle
    /// resource lookup, not a file read) so callers can pick a fallback layout
    /// without waiting on the async PNG decode.
    ///
    /// Deliberately still asks about the BASE file: it is the layout gate every
    /// caller uses, and the pairing invariant `LogoAssetTests
    /// .testEveryDarkSiblingHasABaseMark` holds means a `-dark` never exists
    /// without one, so a dark-mode caller can never be gated out of a mark it
    /// actually ships.
    ///
    /// The empty-name guard that three `logoName ?? ""` call sites depend on
    /// (`ConnectedChannelRow.rowIcon`, `IntegrationsView.mark`, `MemberMark`,
    /// all taking the tile whenever EITHER rung exists per R6) now lives in
    /// `Bundle.cicadaResource`, which is also what makes this lookup answer
    /// the same in a `swift test` bundle and in a shipped `Cicada.app` — read
    /// its docstring before changing the subdirectory here.
    static func exists(name: String) -> Bool {
        Bundle.cicadaResources.cicadaResource(name, ext: "png", in: "logos") != nil
    }

    // MARK: - Bundled cache

    @MainActor
    private static var cache: [String: NSImage] = [:]

    /// R-L5: the cache key is the **resolved** name, not the requested one. A
    /// theme flip must not serve the other theme's cached bytes — `chatgpt` and
    /// `chatgpt-dark` are two different files and two different entries.
    private static func bundledImage(for name: String) async -> NSImage? {
        // `?? name` used to sit here and it re-opened the empty-name hole
        // `exists(name:)` closes: `resolvedName("")` is nil, the fallback fed
        // `""` straight back into the bundle lookup, and Foundation answered
        // with the directory's first file. A nil resolution means no such mark
        // ships — the second lookup could only ever fail or lie.
        guard let file = resolvedName(for: name) else { return nil }
        if let cached = await MainActor.run(body: { cache[file] }) { return cached }
        let loaded = await Task.detached(priority: .utility) {
            guard let url = Bundle.cicadaResources.cicadaResource(file, ext: "png", in: "logos")
            else { return nil as NSImage? }
            return NSImage(contentsOf: url)
        }.value
        if let loaded { await MainActor.run { cache[file] = loaded } }
        return loaded
    }

    // MARK: - Platform tile (Task 13)

    /// Linear-style "Connected accounts" tile: a rounded-square card with a
    /// subtle background and a hairline border, the brand mark centered, inset
    /// and clipped to the card's curvature so a full-bleed source PNG
    /// (`claude-code`, `claude-desktop`, `hermes` — the three rasters whose
    /// background IS the mark) and a transparent-cornered one (Instagram,
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
                // The clip stays, at the CARD's own curvature scaled to the
                // mark (`cornerRadius * markSize / size` — a constant 0.2 of
                // whatever it is drawn at). R-L5 dropped it on a premise that
                // measurement disproved: recutting `x` and `codex` with alpha
                // did not leave "no full-bleed square", because `claude-code`
                // and `claude-desktop` are 256 px rasters whose every pixel is
                // opaque (corners 0.996, sampled minimum 1.00) and `hermes` is
                // a black plate with only a 1-px feathered edge (corner 0.02,
                // 0.91 one pixel in). All three reach here — `claude-desktop`
                // through `chat-export:claude` on the Feed strip and Settings →
                // Integrations, `claude-code` through `claude-plan` — and drew
                // hard corners inside a rounded card. The old radius was
                // `cornerRadius * 0.5`, which read SQUARER than the card
                // because 0.5 is not the card's ratio; this one is, so the mark
                // and the card curve alike. It is a no-op for every mark whose
                // corners are already transparent (25 of the 27 bundled), which
                // is why it costs nothing to apply unconditionally rather than
                // maintaining a list of which rasters are opaque.
                LogoImage(name: name, size: markSize)
                    .clipShape(RoundedRectangle(cornerRadius: cornerRadius * (markSize / size)))
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
