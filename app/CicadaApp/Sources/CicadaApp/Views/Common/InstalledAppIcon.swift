import AppKit
import SwiftUI

/// The icon of an app installed on THIS Mac, by bundle id (R-L1).
///
/// Cicada only offers a Chrome / Safari / Apple Notes channel because it reads
/// that app's own files off this Mac, so the app is present by construction and
/// its icon is already on disk. Using it redistributes nothing (the trademark
/// question evaporates — R-L3 forbids committing Apple's marks), never goes
/// stale when a vendor rebrands, and degrades cleanly: `urlForApplication`
/// returns nil on a machine where the app was removed and the caller falls
/// through to the bundled PNG, then to the SF Symbol.
///
/// Two caveats worth stating rather than discovering: the icon is
/// Launch-Services-resolved, so asking for `com.google.Chrome` on a machine
/// running Chrome Canary answers with whichever bundle claims that id; and
/// `NSWorkspace.icon(forFile:)` is main-actor work, so it is cached exactly the
/// way `LogoImage.cache` caches a decoded PNG — a repaint is a dictionary hit,
/// never a Launch Services round-trip.
@MainActor
enum InstalledAppIcon {
    /// `nil` is cached too (as `.some(nil)`): "this app is not installed" is an
    /// answer worth remembering, or every frame of a scrolling list re-asks
    /// Launch Services the same question.
    private static var cache: [String: NSImage?] = [:]

    static func image(bundleId: String, size: CGFloat) -> NSImage? {
        if let cached = cache[bundleId] { return cached?.copyResized(to: size) }
        let resolved: NSImage? = NSWorkspace.shared
            .urlForApplication(withBundleIdentifier: bundleId)
            .map { NSWorkspace.shared.icon(forFile: $0.path) }
        cache[bundleId] = resolved
        return resolved?.copyResized(to: size)
    }
}

private extension NSImage {
    /// `icon(forFile:)` hands back a multi-representation image whose nominal
    /// `size` is whatever Launch Services felt like; setting `size` on a copy
    /// is what makes AppKit pick the right rep at draw time. A copy, never the
    /// cached instance — the cache is shared across every call site and sizes
    /// differ per surface (14 pt in the Sleep queue, 28 pt in a tile).
    func copyResized(to size: CGFloat) -> NSImage {
        let resized = copy() as! NSImage
        resized.size = NSSize(width: size, height: size)
        return resized
    }
}
