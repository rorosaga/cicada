import Foundation

/// G191 v2 — one switch that works (owner 2026-10-14: bookmarked in Chrome, nothing appeared). Measured cause: "Ask why"
/// was off, and so was the bookmark watch of every browser — two switches the person did not know about, and the
/// question can only follow a bookmark the watch sees. So turning "Ask why" on turns on the bookmark watch of every
/// browser on this Mac that Cicada can sync, in the same step, and the row then says what is watched, what still needs
/// a permission (by name, with its one click) and that the next bookmark is the first one asked about.
///
/// **Consent.** Turning the switch on is the person choosing to have their bookmarks watched — the row names the
/// browsers before they flip it (`Copy.SaveWhy.willWatch`). It re-enables a browser whose watch was turned off, on
/// purpose: that is the measured case. Turning the switch off stops the question and leaves every watch as it is —
/// the bookmarks themselves are still captured as they always were.
///
/// **The seed.** `BrowserWatcher.enable` syncs through the watch's own path but not as a live event, and a browser read
/// for the first time is a first sync, so turning on never asks about the bookmarks already there (`SaveWhyPolicy`).
///
/// **Access.** Chrome and the other Chromium browsers keep their bookmarks under `~/Library/Application Support`,
/// which needs no permission. Safari keeps `Bookmarks.plist` in `~/Library/Safari`, which macOS protects: reading it
/// (and watching its folder) needs Full Disk Access for Cicada — no other route exists (Safari offers no bookmarks API
/// to another app or to a web extension). The watcher's open probe (`BrowserFileAccess`) tells a refusal from an
/// absence, so the row names the permission only when it is really missing.
enum SaveWhySetup {
    /// The bookmark channels this switch watches: every installed browser Cicada can sync, in catalog order.
    static func channels(inventory: BrowserInventory) -> [String] {
        inventory.supported.compactMap(\.bookmarksChannel)
    }

    /// The switch went on: record it, and turn on every installed browser's bookmark watch that is not on yet.
    /// Returns the channels it turned on (for tests; the row reads the watcher's lights).
    @MainActor
    @discardableResult
    static func turnOn(prefs: SaveWhyPrefs, inventory: BrowserInventory, watcher: BrowserWatcher) -> [String] {
        prefs.enabled = true
        let off = channels(inventory: inventory).filter { !watcher.isEnabled($0) }
        for channel in off { watcher.enable(channel) }
        return off
    }

    /// What the row says under the switch once it is on.
    struct Status: Equatable {
        /// Browsers whose bookmarks are watched now (by name).
        var watching: [String] = []
        /// Browsers turned on whose file macOS refuses — each needs Full Disk Access.
        var needsFullDiskAccess: [String] = []
        /// Installed browsers whose watch is off (the person turned it off after turning this on).
        var off: [String] = []
    }

    static func status(inventory: BrowserInventory, state: (String) -> BrowserWatchState?,
                       isEnabled: (String) -> Bool) -> Status {
        var status = Status()
        for spec in inventory.supported {
            guard let channel = spec.bookmarksChannel else { continue }
            let light = state(channel)
            if light == .blocked { status.needsFullDiskAccess.append(spec.name); continue }
            if !isEnabled(channel) || light == .off { status.off.append(spec.name); continue }
            if light == .absent { continue }   // installed but no bookmarks file yet: nothing to watch, nothing to fix
            status.watching.append(spec.name)
        }
        return status
    }

    /// The row's lines, in order: the permission (the one thing to do), then what is watched with the seed sentence,
    /// then a browser left off. Empty when the switch is off.
    static func lines(enabled: Bool, status: Status) -> [String] {
        guard enabled else { return [] }
        var lines: [String] = []
        for name in status.needsFullDiskAccess { lines.append(Copy.SaveWhy.needsFullDiskAccess(name)) }
        if status.watching.isEmpty {
            if status.needsFullDiskAccess.isEmpty { lines.append(Copy.SaveWhy.nothingWatched) }
        } else {
            lines.append(Copy.SaveWhy.watching(status.watching))
        }
        if !status.off.isEmpty { lines.append(Copy.SaveWhy.leftOff(status.off)) }
        return lines
    }
}

/// G245 (plan 7.1 item 8) — what a browser's page says about asking why, in one quiet line: whether the question is on,
/// and whether this browser's bookmarks are watched, so a bookmark that asks nothing is never a mystery. Pure.
enum BrowserAskWhyLine {
    struct Line: Equatable {
        var text: String
        /// True when the person has something to do (turn this browser's bookmarks on, use the Default profile).
        var isAttention: Bool
    }

    /// `otherProfile`: the browser is using a profile Cicada does not read (Chrome's, see `ChromeProfile`).
    static func lines(name: String, askWhy: Bool, watched: Bool, otherProfile: Bool) -> [Line] {
        var out: [Line] = []
        if !askWhy {
            out.append(Line(text: Copy.SaveWhy.askWhyOff, isAttention: false))
        } else if !watched {
            out.append(Line(text: Copy.SaveWhy.askWhyNotWatched(name), isAttention: true))
        } else if otherProfile {
            out.append(Line(text: Copy.SaveWhy.otherProfile(name), isAttention: true))
        } else {
            out.append(Line(text: Copy.SaveWhy.askingHere(name), isAttention: false))
        }
        return out
    }
}

/// G245 — the Chrome profile in use. Cicada reads only the Default profile's bookmarks (R-SR1: reading every `Profile N`
/// would bring in a profile nobody ticked), so a bookmark made in another profile is in no file Cicada reads: the bubble
/// would open a question nothing can confirm. Chrome keeps the profile it used last in its `Local State` (no permission
/// is needed to read it).
enum ChromeProfile {
    /// The profile Chrome used last, from the bytes of `Local State`; nil when the file names none.
    static func lastUsed(inLocalState data: Data) -> String? {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let profile = root["profile"] as? [String: Any] else { return nil }
        return profile["last_used"] as? String
    }

    static var localState: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Google/Chrome/Local State")
    }

    /// The profile in use now, or nil when it cannot be told (no Chrome, an unreadable file).
    static func inUse(at url: URL = localState) -> String? {
        (try? Data(contentsOf: url)).flatMap(lastUsed(inLocalState:))
    }

    /// Whether a bookmark made in this profile is one Cicada reads. An unknown profile counts as read: Chrome with no
    /// `Local State` is Chrome with one profile.
    static func isRead(_ profile: String?) -> Bool { profile == nil || profile == "Default" }
}

/// G191 v2 — the test harness the coordinator runs on a real Mac: a hidden menu-bar item that shows the panel now, for
/// a sample bookmark, without waiting for a real one. Visible only when `defaults write <bundle id>
/// cicada.debug.saveWhyPreview -bool YES` is set AND the app is a developer build — never in a release (G182) app,
/// whatever its defaults say. The panel it shows writes nothing (`SaveWhyCenter.preview`).
enum SaveWhyPreview {
    static let defaultsKey = "cicada.debug.saveWhyPreview"

    /// One preview per browser the owner uses most (2026-10-14: "test … in both Safari and Chrome").
    static let browsers: [(channel: String, name: String)] = [("chrome-bookmarks", "Chrome"),
                                                              ("safari-bookmarks", "Safari")]

    static func isAvailable(flag: Bool, distribution: CicadaRuntime.Distribution) -> Bool {
        flag && distribution == .developer
    }

    static func isAvailable(defaults: UserDefaults = .standard, runtime: CicadaRuntime = .current) -> Bool {
        isAvailable(flag: defaults.bool(forKey: defaultsKey), distribution: runtime.distribution)
    }

    /// A synthetic bookmark (placeholder site), stamped now.
    static func sample(channel: String, now: Date = Date()) -> FreshBookmark {
        let browser = channel.replacingOccurrences(of: "-bookmarks", with: "")
        return FreshBookmark(url: "https://alpha.example/notes/on-design", title: "Alpha example — notes on design",
                             origin: "\(browser)-bookmark", channel: channel, episodeId: "",
                             addedAt: ISO8601DateFormatter().string(from: now))
    }

    /// Used only when the backend does not answer, so the look can still be checked. The live labels come from
    /// `GET /sources/saved-why/options`.
    static let sampleOptions = SavedWhyOptions.basic
}
