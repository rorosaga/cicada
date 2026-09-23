import Foundation

/// Track I T5 — the one intake's wire types, decoded tolerantly: every field has
/// a default, so a response from an older backend (or a 202 carrying only a job)
/// still decodes.
struct IntakeIgnored: Codable, Hashable {
    let name: String
    let reason: String
}

struct IntakeCounts: Codable, Hashable {
    var conversations = 0, memories = 0, projects = 0, prompts = 0, items = 0

    init(conversations: Int = 0, memories: Int = 0, projects: Int = 0, prompts: Int = 0, items: Int = 0) {
        self.conversations = conversations; self.memories = memories; self.projects = projects
        self.prompts = prompts; self.items = items
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversations = (try? c.decodeIfPresent(Int.self, forKey: .conversations)) ?? 0
        memories = (try? c.decodeIfPresent(Int.self, forKey: .memories)) ?? 0
        projects = (try? c.decodeIfPresent(Int.self, forKey: .projects)) ?? 0
        prompts = (try? c.decodeIfPresent(Int.self, forKey: .prompts)) ?? 0
        items = (try? c.decodeIfPresent(Int.self, forKey: .items)) ?? 0
    }

    static func + (a: IntakeCounts, b: IntakeCounts) -> IntakeCounts {
        IntakeCounts(conversations: a.conversations + b.conversations, memories: a.memories + b.memories,
                     projects: a.projects + b.projects, prompts: a.prompts + b.prompts, items: a.items + b.items)
    }
}

struct IntakeDelta: Codable, Hashable {
    var new = 0, grown = 0, unchanged = 0

    init(new: Int = 0, grown: Int = 0, unchanged: Int = 0) { self.new = new; self.grown = grown; self.unchanged = unchanged }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        new = (try? c.decodeIfPresent(Int.self, forKey: .new)) ?? 0
        grown = (try? c.decodeIfPresent(Int.self, forKey: .grown)) ?? 0
        unchanged = (try? c.decodeIfPresent(Int.self, forKey: .unchanged)) ?? 0
    }

    static func + (a: IntakeDelta, b: IntakeDelta) -> IntakeDelta {
        IntakeDelta(new: a.new + b.new, grown: a.grown + b.grown, unchanged: a.unchanged + b.unchanged)
    }
}

struct IntakeTitle: Codable, Hashable {
    let title: String
    let date: String?
}

struct IntakeDateRange: Codable, Hashable {
    let from: String?
    let to: String?
}

/// `POST /intake/sniff` — what a dropped file is, staging nothing (G71 §4.3).
/// `recognized: false` with a `reason` is a file to name as unreadable; with no
/// reason and `ignored` set it is a quiet skip (a lone `user.json`, R-IA11).
struct IntakeSniff: Decodable, Equatable {
    var recognized = false
    var kind = "unknown"
    var vendor: String?
    var origin: String?
    var platform: String?
    var members: [String] = []
    var ignored: [IntakeIgnored] = []
    var counts = IntakeCounts()
    var dateRange: IntakeDateRange?
    var delta = IntakeDelta()
    var titles: [IntakeTitle] = []
    var titlesTruncated = false
    var reason: String?
    var warnings: [String] = []

    init(recognized: Bool = false, kind: String = "unknown", vendor: String? = nil, origin: String? = nil,
         platform: String? = nil, members: [String] = [], ignored: [IntakeIgnored] = [],
         counts: IntakeCounts = IntakeCounts(), dateRange: IntakeDateRange? = nil, delta: IntakeDelta = IntakeDelta(),
         titles: [IntakeTitle] = [], titlesTruncated: Bool = false, reason: String? = nil, warnings: [String] = []) {
        self.recognized = recognized; self.kind = kind; self.vendor = vendor; self.origin = origin
        self.platform = platform; self.members = members; self.ignored = ignored; self.counts = counts
        self.dateRange = dateRange; self.delta = delta; self.titles = titles
        self.titlesTruncated = titlesTruncated; self.reason = reason; self.warnings = warnings
    }

    enum CodingKeys: String, CodingKey {
        case recognized, kind, vendor, origin, platform, members, ignored, counts, dateRange, delta
        case titles, titlesTruncated, reason, warnings
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        recognized = (try? c.decodeIfPresent(Bool.self, forKey: .recognized)) ?? false
        kind = (try? c.decodeIfPresent(String.self, forKey: .kind)) ?? "unknown"
        vendor = (try? c.decodeIfPresent(String.self, forKey: .vendor)) ?? nil
        origin = (try? c.decodeIfPresent(String.self, forKey: .origin)) ?? nil
        platform = (try? c.decodeIfPresent(String.self, forKey: .platform)) ?? nil
        members = (try? c.decodeIfPresent([String].self, forKey: .members)) ?? []
        ignored = (try? c.decodeIfPresent([IntakeIgnored].self, forKey: .ignored)) ?? []
        counts = (try? c.decodeIfPresent(IntakeCounts.self, forKey: .counts)) ?? IntakeCounts()
        dateRange = (try? c.decodeIfPresent(IntakeDateRange.self, forKey: .dateRange)) ?? nil
        delta = (try? c.decodeIfPresent(IntakeDelta.self, forKey: .delta)) ?? IntakeDelta()
        titles = (try? c.decodeIfPresent([IntakeTitle].self, forKey: .titles)) ?? []
        titlesTruncated = (try? c.decodeIfPresent(Bool.self, forKey: .titlesTruncated)) ?? false
        reason = (try? c.decodeIfPresent(String.self, forKey: .reason)) ?? nil
        warnings = (try? c.decodeIfPresent([String].self, forKey: .warnings)) ?? []
    }
}

struct IntakeJobRef: Codable, Hashable {
    let id: String
    let total: Int
}

/// `POST /intake/import` — 200 with counts, or 202 with `job` (Track I T2b).
struct IntakeImportResponse: Decodable, Equatable {
    var episodesStaged = 0
    var episodesUpdated = 0
    var duplicatesSkipped = 0
    var dateRange: IntakeDateRange?
    var format = "unknown"
    var active = true
    var bank = "default"
    var vendor: String?
    var origin: String?
    var job: IntakeJobRef?

    init(episodesStaged: Int = 0, episodesUpdated: Int = 0, duplicatesSkipped: Int = 0, dateRange: IntakeDateRange? = nil,
         format: String = "unknown", active: Bool = true, bank: String = "default", vendor: String? = nil,
         origin: String? = nil, job: IntakeJobRef? = nil) {
        self.episodesStaged = episodesStaged; self.episodesUpdated = episodesUpdated
        self.duplicatesSkipped = duplicatesSkipped; self.dateRange = dateRange; self.format = format
        self.active = active; self.bank = bank; self.vendor = vendor; self.origin = origin; self.job = job
    }

    enum CodingKeys: String, CodingKey {
        case episodesStaged, episodesUpdated, duplicatesSkipped, dateRange, format, active, bank, vendor, origin, job
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episodesStaged = (try? c.decodeIfPresent(Int.self, forKey: .episodesStaged)) ?? 0
        episodesUpdated = (try? c.decodeIfPresent(Int.self, forKey: .episodesUpdated)) ?? 0
        duplicatesSkipped = (try? c.decodeIfPresent(Int.self, forKey: .duplicatesSkipped)) ?? 0
        dateRange = (try? c.decodeIfPresent(IntakeDateRange.self, forKey: .dateRange)) ?? nil
        format = (try? c.decodeIfPresent(String.self, forKey: .format)) ?? "unknown"
        active = (try? c.decodeIfPresent(Bool.self, forKey: .active)) ?? true
        bank = (try? c.decodeIfPresent(String.self, forKey: .bank)) ?? "default"
        vendor = (try? c.decodeIfPresent(String.self, forKey: .vendor)) ?? nil
        origin = (try? c.decodeIfPresent(String.self, forKey: .origin)) ?? nil
        job = (try? c.decodeIfPresent(IntakeJobRef.self, forKey: .job)) ?? nil
    }
}

/// `GET /intake/jobs/{id}` — the backend always sends every field; a missing
/// `error` decodes as nil because it is optional.
struct IntakeJobStatus: Decodable, Equatable {
    var id: String
    var total = 0, staged = 0, created = 0, updated = 0, skipped = 0
    var done = false
    var error: String?
}

/// The three chat vendors the intake names, each with its real mark (Track L:
/// `OriginIconography.logoName(for:)` over the export origin).
enum ChatVendor: String, CaseIterable, Identifiable, Hashable {
    case claude, chatgpt, gemini
    var id: String { rawValue }
    var origin: String { "\(rawValue)-export" }
    var channelId: String { "chat-export:\(rawValue)" }
    var title: String {
        switch self {
        case .claude: "Claude"
        case .chatgpt: "ChatGPT"
        case .gemini: "Gemini"
        }
    }
    var walkthrough: WalkthroughVendor {
        switch self {
        case .claude: .claude
        case .chatgpt: .chatgpt
        case .gemini: .gemini
        }
    }
}

/// One file's sniff, or why it could not be sniffed.
struct IntakeFileSniff: Equatable {
    let url: URL
    var sniff: IntakeSniff? = nil
    var error: String? = nil
}
