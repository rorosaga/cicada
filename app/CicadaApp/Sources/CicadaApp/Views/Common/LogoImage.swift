import SwiftUI
import AppKit

/// Shared bundled-logo loader. Several setup pages (Connections, Connect,
/// Capture sources) render a small square PNG from `Resources/logos/<name>.png`
/// keyed by a provider id (`claude-code`, `codex`, `chrome`, …). Loading those
/// with `NSImage(contentsOf:)` directly inside `body` blocks the main thread
/// on disk I/O every time the view re-renders. `LogoImage` loads each name at
/// most once, off the main thread, and caches the decoded `NSImage` for the
/// lifetime of the process so every subsequent render (and every other view
/// asking for the same name) is a synchronous dictionary lookup.
struct LogoImage: View {
    let name: String
    var size: CGFloat = 28

    @State private var image: NSImage?

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
            } else {
                Image(systemName: "app")
                    .resizable()
                    .scaledToFit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(size * 0.2)
            }
        }
        .frame(width: size, height: size)
        .task(id: name) {
            image = await Self.image(for: name)
        }
    }

    /// Cheap synchronous existence check (a bundle resource lookup, not a file
    /// read) so callers can pick a fallback layout — e.g. a brand-colored
    /// monogram tile instead of the "app" placeholder — without waiting on
    /// the async PNG decode.
    static func exists(name: String) -> Bool {
        Bundle.module.url(forResource: name, withExtension: "png", subdirectory: "Resources/logos") != nil
    }

    // MARK: - Cache

    @MainActor
    private static var cache: [String: NSImage] = [:]

    /// Returns the cached image for `name`, loading it off the main thread on
    /// first request and storing the result back on the main actor. A miss
    /// (no bundled PNG for this id) is not cached — see comment below — so a
    /// dropped-in logo picked up mid-session still resolves.
    private static func image(for name: String) async -> NSImage? {
        if let cached = await MainActor.run(body: { cache[name] }) {
            return cached
        }
        let loaded = await Task.detached(priority: .utility) {
            guard let url = Bundle.module.url(
                forResource: name, withExtension: "png", subdirectory: "Resources/logos"
            ) else { return nil as NSImage? }
            return NSImage(contentsOf: url)
        }.value
        if let loaded {
            await MainActor.run { cache[name] = loaded }
        }
        return loaded
    }
}
