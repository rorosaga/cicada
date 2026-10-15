import Foundation

// The Skills page's wire (owner 2026-10-15): `GET /skills` (`api/services/skill_inventory.py::snapshot`), camelCase.
// Every field decodes leniently (`KeyedDecodingContainer.lenient`) so a server a field ahead or behind never blanks
// the page.

struct SkillsPageData: Decodable, Equatable, Sendable {
    var agents: [SkillAgentInfo] = []
    var installed: [InstalledSkill] = []
    var suggested: [SuggestedSkill] = []
    var drafts: [SkillDraft] = []
    var noticed: [NoticedSkill] = []
    var requests: [SkillRequest] = []
    var checkedAt: String?
    var uv = UvInfo()
    var jobs: [SkillJob] = []

    enum CodingKeys: String, CodingKey { case agents, installed, suggested, drafts, noticed, requests, checkedAt, uv, jobs }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        agents = c.lenient(.agents, [])
        installed = c.lenient(.installed, [])
        suggested = c.lenient(.suggested, [])
        drafts = c.lenient(.drafts, [])
        noticed = c.lenient(.noticed, [])
        requests = c.lenient(.requests, [])
        checkedAt = c.lenient(.checkedAt)
        uv = c.lenient(.uv, UvInfo())
        jobs = c.lenient(.jobs, [])
    }
}

struct SkillAgentInfo: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var label: String
    var folder: String = ""
}

struct UvInfo: Decodable, Equatable, Sendable {
    var present = false
    var installUrl = "https://docs.astral.sh/uv/getting-started/installation/"
    var installCommand = ""

    enum CodingKeys: String, CodingKey { case present, installUrl, installCommand }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        present = c.lenient(.present, false)
        installUrl = c.lenient(.installUrl, installUrl)
        installCommand = c.lenient(.installCommand, "")
    }
}

/// One agent's hold on one skill: in its own folder (`on`), seen through a folder it also reads (`through`), or not.
struct SkillAgentState: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var label: String
    var state: String
    var canToggle: Bool = true
    var note: String?

    var isOn: Bool { state != "off" }

    enum CodingKeys: String, CodingKey { case id, label, state, canToggle, note }

    init(id: String, label: String, state: String, canToggle: Bool = true, note: String? = nil) {
        self.id = id; self.label = label; self.state = state; self.canToggle = canToggle; self.note = note
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        label = c.lenient(.label, "")
        state = c.lenient(.state, "off")
        canToggle = c.lenient(.canToggle, true)
        note = c.lenient(.note)
    }
}

struct SkillSource: Decodable, Equatable, Sendable {
    var kind = "local"
    var label = ""
    var url: String?
    var via: String?
}

struct SkillVersion: Decodable, Equatable, Sendable {
    var label = ""
    var commit: String?
    var ref: String?
    var tool: String?
    var text: String?
}

/// One change an update brings: a commit that touched the skill, or a release with its notes.
struct SkillChange: Decodable, Equatable, Sendable {
    var title = ""
    var date: String?
    var detail: String?
    var url: String?
}

struct SkillUpdate: Decodable, Equatable, Sendable {
    var state = "unknown"
    var latest: String?
    var changes: [SkillChange]?
    var link: String?
    var linkLabel: String?
    var error: String?
    var checkedAt: String?
}

struct SkillTool: Decodable, Equatable, Sendable {
    var command = ""
    var package = ""
    var installed = false
    var version: String?
    var from: String?
    var text = "unknown"
    var textVersion: String?
    var uv = true
}

struct SkillPermission: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var label: String
    var granted: Bool
}

struct SkillPermissions: Decodable, Equatable, Sendable {
    var app = ""
    var ready = false
    var items: [SkillPermission] = []
    var line: String?
}

struct SkillFolder: Decodable, Equatable, Sendable {
    var path: String
    var linked = false
    var byCicada = false
}

struct SkillDetails: Decodable, Equatable, Sendable {
    var folders: [SkillFolder] = []
    var commit: String?
    var ref: String?
    var path: String?
    var installedAt: String?
    var licence: String?
}

struct InstalledSkill: Decodable, Equatable, Sendable, Identifiable {
    var name: String
    var title: String
    var description = ""
    var source = SkillSource()
    var version = SkillVersion()
    var update = SkillUpdate()
    var agents: [SkillAgentState] = []
    var tool: SkillTool?
    var permissions: SkillPermissions?
    var catalogId: String?
    var details = SkillDetails()

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, title, description, source, version, update, agents, tool, permissions, catalogId, details
    }

    init(name: String, title: String) { self.name = name; self.title = title }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c.lenient(.name, "")
        title = c.lenient(.title, name)
        description = c.lenient(.description, "")
        source = c.lenient(.source, SkillSource())
        version = c.lenient(.version, SkillVersion())
        update = c.lenient(.update, SkillUpdate())
        agents = c.lenient(.agents, [])
        tool = c.lenient(.tool)
        permissions = c.lenient(.permissions)
        catalogId = c.lenient(.catalogId)
        details = c.lenient(.details, SkillDetails())
    }
}

struct SkillManualStep: Decodable, Equatable, Sendable {
    var agent: String
    var label: String
    var text: String
}

struct SuggestedSkill: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var title: String
    var summary = ""
    var why: String?
    var publisher: String?
    var sourceUrl: String?
    var licence: String?
    var symbol: String?
    var mark: String?
    var reach: String?
    var method = "copy"
    var manual: [SkillManualStep] = []

    enum CodingKeys: String, CodingKey {
        case id, title, summary, why, publisher, sourceUrl, licence, symbol, mark, reach, method, manual
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        title = c.lenient(.title, id)
        summary = c.lenient(.summary, "")
        why = c.lenient(.why)
        publisher = c.lenient(.publisher)
        sourceUrl = c.lenient(.sourceUrl)
        licence = c.lenient(.licence)
        symbol = c.lenient(.symbol)
        mark = c.lenient(.mark)
        reach = c.lenient(.reach)
        method = c.lenient(.method, "copy")
        manual = c.lenient(.manual, [])
    }
}

struct SkillDraft: Decodable, Equatable, Sendable, Identifiable {
    var name: String
    var description = ""
    var authorLabel = ""
    var reason: String?
    var updated: String?
    var text = ""

    var id: String { name }
}

struct NoticedSkill: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var name: String
    var description = ""
    var state = "held"
    var conversations = 0
}

struct SkillRequest: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var action: String
    var name: String?
    var source: String?
    var agents: [String] = []
    var reason = ""
    var author = ""
    var at: String?

    enum CodingKeys: String, CodingKey { case id, action, name, source, agents, reason, author, at }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        action = c.lenient(.action, "")
        name = c.lenient(.name)
        source = c.lenient(.source)
        agents = c.lenient(.agents, [])
        reason = c.lenient(.reason, "")
        author = c.lenient(.author, "")
        at = c.lenient(.at)
    }
}

struct SkillJob: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var kind = ""
    var label = ""
    var state = "running"
    var step: String?
    var message: String?

    var running: Bool { state == "running" }
}

/// `POST /skills/preview`: either a skill to show (with its `planId`), or the repo's skills to choose from.
struct SkillPreview: Decodable, Equatable, Sendable {
    struct File: Decodable, Equatable, Sendable { var path: String; var size: Int; var script: Bool }
    struct Repo: Decodable, Equatable, Sendable {
        var repo: String?
        var url: String?
        var licence: String?
        var commit: String?
        var commitUrl: String?
    }
    struct Choice: Decodable, Equatable, Sendable, Identifiable {
        var path: String
        var name: String
        var id: String { path }
    }

    var planId: String?
    var name: String?
    var description: String?
    var skillMd: String?
    var skillMdCut: Bool?
    var files: [File]?
    var scripts: [String]?
    var repo: Repo?
    var agents: [String]?
    var choices: [Choice]?
}

/// `GET /skills/onboarding`.
struct SkillsOnboardingOffer: Decodable, Equatable, Sendable {
    struct Suggestion: Decodable, Equatable, Sendable, Identifiable {
        var id: String
        var title: String?
        var line: String?
        var asks: String?
        var `default`: Bool?
        var needsUv: Bool?
        var installed: Bool?
    }

    var suggestions: [Suggestion] = []
    var uv = UvInfo()
    var agents: [String] = []
}
