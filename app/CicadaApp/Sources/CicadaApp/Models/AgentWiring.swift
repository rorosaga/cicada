import Foundation

/// Mirror of `GET /agents/wiring` (Track I T3). Read-only facts plus the exact
/// argv the app may run after the person's click (`AgentConnect`).
///
/// Every field the backend model defaults (`api/models/schemas.py`
/// `AgentWiringStep`/`AgentWiringRow`/`AgentWiringResponse`) decodes when it
/// is absent (the plan's decode-tolerance rule): an older or trimmed payload
/// must still render the rows it can, never fail the whole strip.
struct AgentWiringStep: Codable, Hashable {
    let step: String
    let display: String
    let argv: [String]
    let touches: [String]

    init(step: String, display: String, argv: [String], touches: [String]) {
        self.step = step; self.display = display; self.argv = argv; self.touches = touches
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        step = try c.decode(String.self, forKey: .step)
        argv = try c.decode([String].self, forKey: .argv)
        display = (try? c.decodeIfPresent(String.self, forKey: .display)) ?? argv.joined(separator: " ")
        touches = (try? c.decodeIfPresent([String].self, forKey: .touches)) ?? []
    }
}

struct AgentWiring: Codable, Hashable, Identifiable {
    let id: String
    let installed: Bool
    let binary: String?
    let recall: String
    let autosave: String
    let connect: [AgentWiringStep]
    let detail: String?
    /// G149 — the recall hooks' state (`on | off | stale | invalid | n/a`) and
    /// the two command sets Settings → Agents → Remembers automatically may
    /// run. They are kept apart from `connect` because onboarding's Turn on
    /// runs `connect` and nothing else (R-H11).
    let autorecall: String
    let autorecallOn: [AgentWiringStep]
    let autorecallOff: [AgentWiringStep]

    init(id: String, installed: Bool, binary: String?, recall: String, autosave: String,
         connect: [AgentWiringStep], detail: String?, autorecall: String = "n/a",
         autorecallOn: [AgentWiringStep] = [], autorecallOff: [AgentWiringStep] = []) {
        self.id = id; self.installed = installed; self.binary = binary; self.recall = recall
        self.autosave = autosave; self.connect = connect; self.detail = detail
        self.autorecall = autorecall; self.autorecallOn = autorecallOn; self.autorecallOff = autorecallOff
    }

    /// A missing `recall` reads as `unknown`, never `off`: `off` is the state
    /// that offers an `mcp add`, which fails on a server already registered
    /// (R-IA15). What is offered still comes from `connect` alone.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        installed = (try? c.decodeIfPresent(Bool.self, forKey: .installed)) ?? false
        binary = try? c.decodeIfPresent(String.self, forKey: .binary)
        recall = (try? c.decodeIfPresent(String.self, forKey: .recall)) ?? "unknown"
        autosave = (try? c.decodeIfPresent(String.self, forKey: .autosave)) ?? "n/a"
        connect = (try? c.decodeIfPresent([AgentWiringStep].self, forKey: .connect)) ?? []
        detail = try? c.decodeIfPresent(String.self, forKey: .detail)
        // An older backend sends none of the three: `n/a` lists no row (R-H18).
        autorecall = (try? c.decodeIfPresent(String.self, forKey: .autorecall)) ?? "n/a"
        autorecallOn = (try? c.decodeIfPresent([AgentWiringStep].self, forKey: .autorecallOn)) ?? []
        autorecallOff = (try? c.decodeIfPresent([AgentWiringStep].self, forKey: .autorecallOff)) ?? []
    }
}

struct AgentWiringResponse: Codable, Hashable {
    let agents: [AgentWiring]
    let python: String
    let repo: String
    let memory: String

    init(agents: [AgentWiring], python: String, repo: String, memory: String) {
        self.agents = agents; self.python = python; self.repo = repo; self.memory = memory
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        agents = (try? c.decodeIfPresent([AgentWiring].self, forKey: .agents)) ?? []
        python = (try? c.decodeIfPresent(String.self, forKey: .python)) ?? ""
        repo = (try? c.decodeIfPresent(String.self, forKey: .repo)) ?? ""
        memory = (try? c.decodeIfPresent(String.self, forKey: .memory)) ?? ""
    }
}
