import Foundation

/// G218 — what a trace may hold, applied in the app before anything leaves it. The backend serves the lists
/// (`trace_policy.served`) and applies them again on every row; the compiled-in lists below are the floor that holds
/// even before the backend answered (password managers, the login window, Cicada itself).
struct TracePolicy: Equatable, Sendable {
    /// Never recorded, whatever the backend says.
    static let floorNeverApps: Set<String> = [
        "com.1password.1password", "com.agilebits.onepassword7", "com.bitwarden.desktop", "com.apple.Passwords",
        "com.apple.keychainaccess", "com.apple.SecurityAgent", "com.apple.loginwindow", "com.apple.ScreenSaver.Engine",
    ]
    static let floorSelfPrefix = "com.rorosaga.cicada"
    static let floorTitleOff: Set<String> = ["com.apple.mail", "com.apple.MobileSMS"]

    var settings: TraceSettings
    var lists: TracePolicyLists
    /// This app's own bundle id (a verification copy runs under its own).
    var ownBundleId: String?

    /// Nothing of this app's moment is recorded, not even its name.
    func neverRecorded(_ bundleId: String) -> Bool {
        if Self.floorNeverApps.contains(bundleId) || lists.neverApps.contains(bundleId) { return true }
        if bundleId.hasPrefix(Self.floorSelfPrefix) || (!lists.selfPrefix.isEmpty && bundleId.hasPrefix(lists.selfPrefix)) {
            return true
        }
        if let own = ownBundleId, bundleId == own { return true }
        return settings.excludedApps.contains(bundleId)
    }

    /// Titles: on, and the app is not a chat or mail app unless the person turned its titles on.
    func titleAllowed(_ bundleId: String) -> Bool {
        guard settings.titles else { return false }
        let off = Self.floorTitleOff.contains(bundleId) || lists.titleOffApps.contains(bundleId)
        return !off || settings.titleApps.contains(bundleId)
    }

    /// The browser name (`chrome`, `brave`…) whose URL may be read, when the person allowed it.
    func urlBrowser(_ bundleId: String) -> String? {
        guard let name = lists.urlBrowsers.first(where: { $0.value.contains(bundleId) })?.key,
              settings.browsers.contains(name) else { return nil }
        return name
    }

    /// A site the person excluded: the whole moment is dropped.
    func hostExcluded(_ host: String) -> Bool {
        let h = Self.bareHost(host)
        return settings.excludedSites.contains { h == $0 || h.hasSuffix("." + $0) }
    }

    static func bareHost(_ host: String) -> String {
        let lower = host.lowercased()
        return lower.hasPrefix("www.") ? String(lower.dropFirst(4)) : lower
    }

    /// Scheme, host and path; the query only for the keys that name the content (YouTube's `v`); no fragment.
    func cleanURL(_ raw: String) -> (url: String, host: String)? {
        guard var parts = URLComponents(string: raw), let scheme = parts.scheme?.lowercased(),
              scheme == "http" || scheme == "https", let host = parts.host?.lowercased(), !host.isEmpty else {
            return nil
        }
        let keys = lists.contentKeys.first { host == $0.key || host.hasSuffix("." + $0.key) }?.value ?? []
        let kept = (parts.queryItems ?? []).filter { keys.contains($0.name) && !($0.value ?? "").isEmpty }
        parts.queryItems = kept.isEmpty ? nil : Array(kept.prefix(2))
        parts.fragment = nil
        parts.user = nil
        parts.password = nil
        parts.port = nil
        parts.scheme = scheme
        parts.host = host
        guard let url = parts.string else { return nil }
        return (String(url.prefix(400)), host)
    }

    /// A browser's window title carries the browser's name and the profile after the page's title; the tab's own
    /// title (from the browser) is used instead whenever it is known.
    static func trimTitle(_ title: String) -> String {
        let one = title.split(whereSeparator: \.isNewline).joined(separator: " ")
        return String(one.trimmingCharacters(in: .whitespaces).prefix(300))
    }
}

/// When a screenshot is taken. Event-driven, after Screenpipe: a frame when a new span starts (another app, window or
/// page in front), and then one every `steadyInterval` while the same span continues — never on a fast timer, never
/// while idle, locked or paused, and never two within `minGap`.
///
/// **The numbers (owner 2026-10-28: "a low screenshot frequency is probably best").** `minGap` 5 min and
/// `steadyInterval` 15 min (were 1 min and 5 min): a heavy eight-hour day is at most 96 moments, a quiet one ~32.
/// Measured on this Mac (synthetic 1280×800 screen of dense text, `maxSide` 1280, JPEG 0.6): ~0.5 MB a frame at worst
/// (a typical mixed screen ~0.2–0.3 MB), JPEG encode ~10 ms, on-device text recognition ~0.65 s wall and ~1.1 s CPU at
/// utility priority. Per connected screen that is ≤ ~30 MB and ~2 CPU-minutes a heavy day — ≤ ~0.2 GB for the
/// seven days screenshots are kept — against ~150 MB and ~9 CPU-minutes a day at the old cadence (480 moments).
/// Battery follows the CPU: a couple of minutes of one core a day, off the main thread.
struct TraceFrameCadence: Equatable, Sendable {
    var minGap: TimeInterval = 300
    var steadyInterval: TimeInterval = 900
    var maxSide = 1280

    func shouldCapture(now: Date, spanStartedAt: Date, spanIsNew: Bool, lastFrameAt: Date?,
                       lastFrameSpanStart: Date?) -> Bool {
        if let last = lastFrameAt, now.timeIntervalSince(last) < minGap { return false }
        if spanIsNew { return true }
        guard let last = lastFrameAt, lastFrameSpanStart == spanStartedAt else {
            // This span has no frame yet (its start was inside another frame's minGap): take it now.
            return true
        }
        return now.timeIntervalSince(last) >= steadyInterval
    }
}

/// Every connected screen (owner 2026-10-28). Which apps may appear on a screen's picture: only an app the policy may
/// describe — never a browser (one appears only through its vetted front window), a chat or mail app whose titles stay
/// off, an app left out, a password manager, Cicada itself, or a system surface that shows other apps' words
/// (notification banners, Spotlight).
enum TraceScreens {
    static let max = 8
    static let overlays: Set<String> = [
        "com.apple.notificationcenterui", "com.apple.UserNotificationCenter", "com.apple.Spotlight",
        "com.apple.screencaptureui", "com.apple.WindowManager",
    ]

    /// `isBrowser`: a named browser, or any app registered to open https: links (review of #456, B3).
    static func shown(_ policy: TracePolicy,
                      isBrowser: @escaping @Sendable (String) -> Bool) -> @Sendable (String) -> Bool {
        { bundle in
            !bundle.isEmpty && !overlays.contains(bundle) && !policy.neverRecorded(bundle)
                && policy.titleAllowed(bundle) && !policy.isBrowser(bundle) && !isBrowser(bundle)
        }
    }
}
