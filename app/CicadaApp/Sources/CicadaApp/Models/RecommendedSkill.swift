import Foundation

/// Wire mirror of `api/models/skill_schemas.py` (G138). Every field but the
/// identity ones defaults, so an older or newer backend still decodes.
struct RecommendedSkillsResponse: Decodable, Equatable {
    var reviewedAt: String = ""
    var maxShown: Int = 5
    var catalogSize: Int = 0
    var recommended: [RecommendedSkill] = []
    var installed: [RecommendedSkill] = []

    enum CodingKeys: String, CodingKey { case reviewedAt, maxShown, catalogSize, recommended, installed }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        reviewedAt = (try? c.decode(String.self, forKey: .reviewedAt)) ?? ""
        maxShown = (try? c.decode(Int.self, forKey: .maxShown)) ?? 5
        catalogSize = (try? c.decode(Int.self, forKey: .catalogSize)) ?? 0
        recommended = (try? c.decode([RecommendedSkill].self, forKey: .recommended)) ?? []
        installed = (try? c.decode([RecommendedSkill].self, forKey: .installed)) ?? []
    }
}

struct RecommendedSkill: Decodable, Identifiable, Equatable {
    let id: String
    var kind = "skill"
    var rank = 999
    var title = ""
    var summary = ""
    var why = ""
    var publisher = ""
    var sourceUrl = ""
    var licence = ""
    var mark: String?
    var symbol = "sparkles"
    var endpoint: String?
    var needs = SkillNeeds()
    var terms: SkillTerms?
    var cicadaNote: String?
    var agents: [String] = []
    var state: [String: String] = [:]
    var install: [String: SkillInstallPlan] = [:]

    enum CodingKeys: String, CodingKey {
        case id, kind, rank, title, summary, why, publisher, sourceUrl, licence, mark, symbol, endpoint
        case needs, terms, cicadaNote, agents, state, install
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = (try? c.decode(String.self, forKey: .kind)) ?? "skill"
        rank = (try? c.decode(Int.self, forKey: .rank)) ?? 999
        title = (try? c.decode(String.self, forKey: .title)) ?? id
        summary = (try? c.decode(String.self, forKey: .summary)) ?? ""
        why = (try? c.decode(String.self, forKey: .why)) ?? ""
        publisher = (try? c.decode(String.self, forKey: .publisher)) ?? ""
        sourceUrl = (try? c.decode(String.self, forKey: .sourceUrl)) ?? ""
        licence = (try? c.decode(String.self, forKey: .licence)) ?? ""
        mark = try? c.decode(String.self, forKey: .mark)
        symbol = (try? c.decode(String.self, forKey: .symbol)) ?? "sparkles"
        endpoint = try? c.decode(String.self, forKey: .endpoint)
        needs = (try? c.decode(SkillNeeds.self, forKey: .needs)) ?? SkillNeeds()
        terms = try? c.decode(SkillTerms.self, forKey: .terms)
        cicadaNote = try? c.decode(String.self, forKey: .cicadaNote)
        agents = (try? c.decode([String].self, forKey: .agents)) ?? []
        state = (try? c.decode([String: String].self, forKey: .state)) ?? [:]
        install = (try? c.decode([String: SkillInstallPlan].self, forKey: .install)) ?? [:]
    }
}

struct SkillNeeds: Decodable, Equatable {
    struct Key: Decodable, Equatable {
        let name: String
        var optional = true
        enum CodingKeys: String, CodingKey { case name, optional }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            name = (try? c.decode(String.self, forKey: .name)) ?? ""
            optional = (try? c.decode(Bool.self, forKey: .optional)) ?? true
        }
    }
    var binaries: [String] = []
    var keys: [Key] = []
    var accounts: [String] = []
    var network: [String] = []
    var writes: [String] = []
    var allowedTools: String?
    var hooks: [String] = []
    var firstRun: String?
    var limits: [String] = []

    init() {}
    enum CodingKeys: String, CodingKey { case binaries, keys, accounts, network, writes, allowedTools, hooks, firstRun, limits }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        binaries = (try? c.decode([String].self, forKey: .binaries)) ?? []
        keys = (try? c.decode([Key].self, forKey: .keys)) ?? []
        accounts = (try? c.decode([String].self, forKey: .accounts)) ?? []
        network = (try? c.decode([String].self, forKey: .network)) ?? []
        writes = (try? c.decode([String].self, forKey: .writes)) ?? []
        allowedTools = try? c.decode(String.self, forKey: .allowedTools)
        hooks = (try? c.decode([String].self, forKey: .hooks)) ?? []
        firstRun = try? c.decode(String.self, forKey: .firstRun)
        limits = (try? c.decode([String].self, forKey: .limits)) ?? []
    }
}

// Synthesized `Decodable` throws on a missing key even when the property has a
// default, so each of these decodes by hand — a field the server leaves out
// takes its default.
struct SkillTerms: Decodable, Equatable {
    let summary: String
    let url: String
    var safeUses: [String] = []

    enum CodingKeys: String, CodingKey { case summary, url, safeUses }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        summary = (try? c.decode(String.self, forKey: .summary)) ?? ""
        url = (try? c.decode(String.self, forKey: .url)) ?? ""
        safeUses = (try? c.decode([String].self, forKey: .safeUses)) ?? []
    }
}

struct SkillInstallStep: Decodable, Equatable {
    let argv: [String]
    var tolerateFailure = false

    init(argv: [String], tolerateFailure: Bool = false) {
        self.argv = argv
        self.tolerateFailure = tolerateFailure
    }
    enum CodingKeys: String, CodingKey { case argv, tolerateFailure }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        argv = (try? c.decode([String].self, forKey: .argv)) ?? []
        tolerateFailure = (try? c.decode(Bool.self, forKey: .tolerateFailure)) ?? false
    }
}

struct SkillInstallPlan: Decodable, Equatable {
    var runnable = true
    var steps: [SkillInstallStep] = []
    var env: [String: String] = [:]

    init(runnable: Bool = true, steps: [SkillInstallStep] = [], env: [String: String] = [:]) {
        self.runnable = runnable
        self.steps = steps
        self.env = env
    }
    enum CodingKeys: String, CodingKey { case runnable, steps, env }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        runnable = (try? c.decode(Bool.self, forKey: .runnable)) ?? true
        steps = (try? c.decode([SkillInstallStep].self, forKey: .steps)) ?? []
        env = (try? c.decode([String: String].self, forKey: .env)) ?? [:]
    }
}

/// The agents a skill installs into, in the app's words and marks.
enum SkillAgent {
    static func label(_ id: String) -> String {
        switch id { case "claude-code": "Claude Code"; case "codex": "Codex"; default: id }
    }
    static func mark(_ id: String) -> String { id == "codex" ? "codex" : "claude-code" }
    static func stateLabel(_ state: String) -> String {
        switch state { case "installed": "Installed"; case "unknown": "Set up in the agent"; default: "Not installed" }
    }
}
