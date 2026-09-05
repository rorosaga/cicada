import Foundation

/// G126 R9 — the Feed hand-off. CLAUDE.md's Companion App section confirms
/// "The app has no NotificationCenter-based cross-window messaging today";
/// this is a small `@Observable` class injected into both scenes via
/// `.environment`, matching how every other cross-view-model coordination in
/// this app already works (thin observed classes, not notifications), so an
/// Integrations row's "Import in Feed →" can switch the sidebar to Feed AND
/// stage that tile for the `+` sheet without either view knowing about the
/// other directly.
@Observable
@MainActor
final class AppRouter {
    var pendingTab: AppTab?
    var pendingAddSource: AddSourceTile?

    /// Sets both fields together — a `pendingAddSource` with no matching
    /// tab-switch would stage a sheet nobody ever sees, since `FeedView`
    /// only consumes it once it's actually on screen.
    func routeToFeedAddSource(_ tile: AddSourceTile) {
        pendingTab = .feed
        pendingAddSource = tile
    }

    /// Reads then clears in one call so a caller (`FeedView.onAppear` AND
    /// its `onChange(of: router.pendingAddSource)`, which can both fire for
    /// the same hand-off) can never re-consume a stale tile.
    @discardableResult
    func consumeAddSource() -> AddSourceTile? {
        defer { pendingAddSource = nil }
        return pendingAddSource
    }
}
