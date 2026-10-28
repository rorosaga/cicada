import Foundation

/// G218 — activity traces on the wire. The backend (`api/routers/traces.py`) keeps them sealed outside every bank; these
/// are only the shapes the app posts and reads. Nothing here is ever written to disk by the app.

/// The person's choices, as `trace_store.DEFAULTS` names them.
struct TraceSettings: Codable, Equatable, Sendable {
    var enabled = false
    var consentVersion = 0
    var consentedAt: String?
    var screenshots = true
    var titles = true
    var titleApps: [String] = []
    var browsers: [String] = []
    var excludedApps: [String] = []
    var excludedSites: [String] = []
    /// "What you watch and read" (2026-10-28, ruling 39b generalised to every site): on with traces.
    var watchAndRead = true
    /// "Learn from my day" (2026-10-28, the two old nested switches as one): off by default.
    var learnFromDay = false
    var timelineDays = 30
    var shotDays = 7
    var pausedSince: String?
    var pausedUntil: String?

    enum CodingKeys: String, CodingKey {
        case enabled, screenshots, titles, browsers
        case consentVersion = "consent_version", consentedAt = "consented_at", titleApps = "title_apps"
        case excludedApps = "excluded_apps", excludedSites = "excluded_sites"
        case watchAndRead = "watch_and_read", learnFromDay = "learn_from_day"
        case timelineDays = "timeline_days", shotDays = "shot_days"
        case pausedSince = "paused_since", pausedUntil = "paused_until"
    }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? false
        consentVersion = try c.decodeIfPresent(Int.self, forKey: .consentVersion) ?? 0
        consentedAt = try c.decodeIfPresent(String.self, forKey: .consentedAt)
        screenshots = try c.decodeIfPresent(Bool.self, forKey: .screenshots) ?? true
        titles = try c.decodeIfPresent(Bool.self, forKey: .titles) ?? true
        titleApps = try c.decodeIfPresent([String].self, forKey: .titleApps) ?? []
        browsers = try c.decodeIfPresent([String].self, forKey: .browsers) ?? []
        excludedApps = try c.decodeIfPresent([String].self, forKey: .excludedApps) ?? []
        excludedSites = try c.decodeIfPresent([String].self, forKey: .excludedSites) ?? []
        // A backend from before 2026-10-28 answers with the old keys only (Hyrum, both ways).
        let old = try decoder.container(keyedBy: OldKeys.self)
        watchAndRead = try c.decodeIfPresent(Bool.self, forKey: .watchAndRead)
            ?? old.decodeIfPresent(Bool.self, forKey: .youtubeToWatchHistory) ?? true
        learnFromDay = try c.decodeIfPresent(Bool.self, forKey: .learnFromDay)
            ?? old.decodeIfPresent(Bool.self, forKey: .learnFromSummary) ?? false
        timelineDays = try c.decodeIfPresent(Int.self, forKey: .timelineDays) ?? 30
        shotDays = try c.decodeIfPresent(Int.self, forKey: .shotDays) ?? 7
        pausedSince = try c.decodeIfPresent(String.self, forKey: .pausedSince)
        pausedUntil = try c.decodeIfPresent(String.self, forKey: .pausedUntil)
    }

    private enum OldKeys: String, CodingKey {
        case youtubeToWatchHistory = "youtube_to_watch_history", learnFromSummary = "learn_from_summary"
    }

    /// `paused_until`'s value for a pause that lasts until the person resumes (`trace_store.UNTIL_RESUMED`).
    static let untilResumed = "until-resumed"

    /// Whether a pause covers `now`.
    func isPaused(at now: Date) -> Bool {
        guard pausedSince != nil, let until = pausedUntil else { return false }
        if until == Self.untilResumed { return true }
        guard let end = TraceClock.parse(until) else { return false }
        return now < end
    }
}

/// The lists the backend serves (`trace_policy.served`): the app applies them before anything leaves it.
struct TracePolicyLists: Codable, Equatable, Sendable {
    var neverApps: [String] = []
    var selfPrefix = "com.rorosaga.cicada"
    var titleOffApps: [String] = []
    var urlBrowsers: [String: [String]] = [:]
    var contentKeys: [String: [String]] = [:]
    /// Every browser the backend knows (`trace_policy.KNOWN_BROWSERS`): described only through a verified tab.
    var knownBrowsers: [String] = []

    enum CodingKeys: String, CodingKey {
        case neverApps = "never_apps", selfPrefix = "self_prefix", titleOffApps = "title_off_apps"
        case urlBrowsers = "url_browsers", contentKeys = "content_keys", knownBrowsers = "known_browsers"
    }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        neverApps = try c.decodeIfPresent([String].self, forKey: .neverApps) ?? []
        selfPrefix = try c.decodeIfPresent(String.self, forKey: .selfPrefix) ?? "com.rorosaga.cicada"
        titleOffApps = try c.decodeIfPresent([String].self, forKey: .titleOffApps) ?? []
        urlBrowsers = try c.decodeIfPresent([String: [String]].self, forKey: .urlBrowsers) ?? [:]
        contentKeys = try c.decodeIfPresent([String: [String]].self, forKey: .contentKeys) ?? [:]
        knownBrowsers = try c.decodeIfPresent([String].self, forKey: .knownBrowsers) ?? []
    }
}

/// The store's state, for the Traces page: counts and sizes only.
struct TraceStoreStatus: Codable, Equatable, Sendable {
    var enabled = false
    var paused = false
    var pausedUntil: String?
    var days = 0
    var oldestDay: String?
    var screenshotDays = 0
    var bytes = 0
    var key = ""
    var timelineDays = 30
    var shotDays = 7

    enum CodingKeys: String, CodingKey {
        case enabled, paused, days, bytes, key
        case pausedUntil = "paused_until", oldestDay = "oldest_day", screenshotDays = "screenshot_days"
        case timelineDays = "timeline_days", shotDays = "shot_days"
    }
}

/// `GET /sources/traces/settings` and every settings write's answer.
struct TraceSettingsAnswer: Codable, Equatable, Sendable {
    var settings: TraceSettings
    var status: TraceStoreStatus
    var policy: TracePolicyLists
    var consentVersion: Int
    /// The sheet version from which screenshots cover every connected screen (`trace_store.ALL_SCREENS_CONSENT`);
    /// nil from an older backend, which keeps the front window only.
    var allScreensConsent: Int?

    enum CodingKeys: String, CodingKey {
        case settings, status, policy
        case consentVersion = "consent_version", allScreensConsent = "all_screens_consent"
    }
}

/// One focus span as the app posts it: what was in front, from when to when.
struct TraceSpan: Codable, Equatable, Sendable {
    var id: String
    var start: String
    var end: String
    var bundleId: String
    var app: String
    var title: String?
    var url: String?
    /// The app opens https: links (a browser, listed or not): the backend keeps its title only beside a verified URL.
    var browser: Bool?

    enum CodingKeys: String, CodingKey {
        case id, start, end, app, title, url, browser
        case bundleId = "bundle_id"
    }
}

struct TraceSyncResult: Codable, Equatable, Sendable {
    var received = 0
    var kept = 0
    var excluded = 0
    var duplicate = 0
    var invalid = 0
    var paused = 0
    var promotedFiles = 0

    enum CodingKeys: String, CodingKey {
        case received, kept, excluded, duplicate, invalid, paused
        case promotedFiles = "promoted_files"
    }
}

/// One screenshot as the app posts it (`POST /sources/traces/frames`), the image downscaled JPEG in base64.
struct TraceFramePost: Codable, Equatable, Sendable {
    var id: String
    var at: String
    var bundleId: String
    var app: String
    var host: String
    var spanId: String
    var width: Int
    var height: Int
    var image: String
    var text: String
    var browser = false
    /// Every connected screen (2026-10-28): this is screen `display` of `displays`; 0 for a front-window frame.
    var display = 0
    var displays = 0

    enum CodingKeys: String, CodingKey {
        case id, at, app, host, width, height, image, text, browser, display, displays
        case bundleId = "bundle_id", spanId = "span_id"
    }
}

/// A span as the store kept it (the policy re-applied: a URL is cleaned, a title may be gone).
struct TraceStoredSpan: Codable, Equatable, Sendable, Identifiable {
    var id: String
    var start: String
    var end: String
    var bundleId: String
    var app: String
    var title: String?
    var url: String?
    var host: String?

    enum CodingKeys: String, CodingKey {
        case id, start, end, app, title, url, host
        case bundleId = "bundle_id"
    }
}

/// A kept screenshot's record — never its pixels or text (those are fetched behind Touch ID).
struct TraceFrameMeta: Codable, Equatable, Sendable, Identifiable {
    var id: String
    var at: String
    var bundleId: String
    var app: String
    var width: Int
    var height: Int
    var spanId: String?
    var hasText: Bool
    /// Which screen of how many, when more than one was connected.
    var display: Int?
    var displays: Int?

    enum CodingKeys: String, CodingKey {
        case id, at, app, width, height, display, displays
        case bundleId = "bundle_id", spanId = "span_id", hasText = "has_text"
    }
}

struct TraceTimeline: Codable, Equatable, Sendable {
    var day: String
    var spans: [TraceStoredSpan]
    var frames: [TraceFrameMeta]
    var unreadable: Int
    /// The most screens connected at any screenshot that day (1 when unknown).
    var screens: Int?
}

/// `GET /sources/traces/day-cards` — one kept day: its counts, the screens connected, and the id of the screenshot that
/// stands for it (pixels only after Touch ID, like every screenshot).
struct TraceDayCard: Codable, Equatable, Sendable, Identifiable {
    var day: String
    var spans: Int
    var seconds: Int
    var apps: Int
    var sites: Int
    var frames: Int
    var screens: Int
    var cover: String?
    var id: String { day }
}

/// `GET /sources/traces/preview` — the counted digest Sleep would read for one day, and its words.
struct TraceDigestPreview: Codable, Equatable, Sendable {
    struct Project: Codable, Equatable, Sendable, Identifiable {
        var id: String
        var name: String
        var seconds: Int
        var apps: [String]
    }

    struct Reading: Codable, Equatable, Sendable {
        var seconds = 0
        var pages = 0
        var sites: [String] = []
        var siteCount = 0
        var apps: [String] = []

        enum CodingKeys: String, CodingKey { case seconds, pages, sites, apps, siteCount = "site_count" }
    }

    struct Watching: Codable, Equatable, Sendable {
        var seconds = 0
        var videos = 0
        var platforms: [String] = []
    }

    struct Calls: Codable, Equatable, Sendable {
        var seconds = 0
        var count = 0
        var apps: [String] = []
    }

    struct Rest: Codable, Equatable, Sendable {
        var seconds = 0
        var apps: [String] = []
        var busiestSwitches = 0

        enum CodingKeys: String, CodingKey { case seconds, apps, busiestSwitches = "busiest_switches" }
    }

    struct Counts: Codable, Equatable, Sendable {
        var day: String
        var totalSeconds: Int
        var projects: [Project]
        var reading: Reading
        var watching: Watching
        var calls: Calls
        var rest: Rest

        enum CodingKeys: String, CodingKey {
            case day, projects, reading, watching, calls
            case totalSeconds = "total_seconds", rest = "else"
        }
    }

    var day: String
    var counts: Counts?
    var text: String?
}

/// `GET /sources/traces/added` — what traces added to memory, and the removals that can still be undone.
struct TraceAdded: Codable, Equatable, Sendable {
    struct Item: Codable, Equatable, Sendable, Identifiable {
        var entityId: String
        var claimId: String
        var text: String
        var progress: Bool
        var day: String?
        var id: String { "\(entityId)/\(claimId)" }

        enum CodingKeys: String, CodingKey {
            case text, progress, day
            case entityId = "entity_id", claimId = "claim_id"
        }
    }

    struct Removal: Codable, Equatable, Sendable, Identifiable {
        var id: String
        var day: String?
        var count: Int
    }

    var beliefs = 0
    var progress = 0
    var since: String?
    var items: [Item] = []
    var removals: [Removal] = []
}

/// `POST /sources/traces/remove-from-memory`.
struct TraceRemoval: Codable, Equatable, Sendable {
    var removalId: String?
    var removed: Int

    enum CodingKeys: String, CodingKey { case removed, removalId = "removal_id" }
}

/// `POST /sources/traces/delete`.
struct TraceDeleted: Codable, Equatable, Sendable {
    var spans: Int
    var frames: Int
}

struct TraceSearchHit: Codable, Equatable, Sendable, Identifiable {
    var kind: String
    var at: String
    var end: String?
    var app: String?
    var title: String?
    var url: String?
    var snippet: String?
    var id: String
}

struct TraceFrameText: Codable, Equatable, Sendable {
    var id: String
    var at: String
    var app: String?
    var text: String
}

/// Zoned ISO stamps, both ways (a trace's instant always carries its zone; the backend refuses a naive one).
enum TraceClock {
    static func stamp(_ date: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f.string(from: date)
    }

    static func parse(_ raw: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        if let d = f.date(from: raw) { return d }
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: raw)
    }
}
