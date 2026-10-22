import Foundation
import Observation

/// The Skills page's state (owner 2026-10-15). Not a Store domain: `GET /skills` is a read of a few folders the page
/// loads when shown and after each action, cached here in memory. Every decision is the backend's
/// (`api/services/skill_actions.py`); this model only sends the person's clicks and shows what came back.
@MainActor
@Observable
final class SkillsPageModel {
    enum Phase: Equatable { case idle, loading, loaded, failed(String) }

    private(set) var data: SkillsPageData?
    private(set) var phase: Phase = .idle
    /// Names (or ids) with an action in flight, so their buttons wait.
    private(set) var busy: Set<String> = []
    private(set) var checking = false
    /// The last refusal or failure, in the backend's words.
    var message: String?
    private(set) var jobs: [SkillJob] = []

    private let api: SkillsAPI
    private let pollInterval: Duration

    init(api: SkillsAPI = APIClient.shared, pollInterval: Duration = .seconds(1)) {
        self.api = api
        self.pollInterval = pollInterval
    }

    var updatesAvailable: [InstalledSkill] { data?.installed.filter { $0.update.state == "available" } ?? [] }

    func load() async {
        if data == nil { phase = .loading }
        do {
            let fresh = try await api.skillsPage()
            data = fresh
            phase = .loaded
            jobs = fresh.jobs.filter(\.running)
        } catch {
            // DR-43 — never blank over good data: a failed reload keeps what is shown and says why.
            if data == nil { phase = .failed(SkillsError.words(error)) } else { message = SkillsError.words(error) }
        }
    }

    /// The page opening re-checks only when the last check is over an hour old (the backend decides).
    func appeared() async {
        await load()
        try? await api.checkSkillUpdates(auto: true)
        await load()
    }

    func checkNow() async {
        checking = true
        defer { checking = false }
        do { try await api.checkSkillUpdates(auto: false) } catch { message = SkillsError.words(error) }
        await load()
    }

    private func perform(_ key: String, _ work: () async throws -> SkillJob?) async {
        busy.insert(key)
        message = nil
        defer { busy.remove(key) }
        do {
            if let job = try await work() { await follow(job) }
        } catch {
            message = SkillsError.words(error)
        }
        await load()
    }

    /// Poll a background job until it ends; a failure's sentence becomes the page's message.
    func follow(_ job: SkillJob) async {
        var current = job
        jobs.removeAll { $0.id == job.id }
        jobs.append(current)
        while current.running, !Task.isCancelled {
            try? await Task.sleep(for: pollInterval)
            guard let next = try? await api.skillJob(job.id) else { break }
            current = next
            if let i = jobs.firstIndex(where: { $0.id == job.id }) { jobs[i] = next }
        }
        jobs.removeAll { $0.id == job.id }
        if current.state == "failed" { message = current.message ?? Copy.Skills.somethingWrong }
    }

    func toggle(_ skill: InstalledSkill, agent: SkillAgentState, requestId: String? = nil) async {
        await perform(skill.name) {
            try await api.setSkill(skill.name, agent: agent.id, on: !agent.isOn, requestId: requestId)
            return nil
        }
    }

    func update(_ name: String, requestId: String? = nil) async {
        await perform(name) { try await api.updateSkill(name, requestId: requestId) }
    }

    func updateAll() async {
        await perform("update-all") { try await api.updateAllSkills() }
    }

    func refresh(_ name: String, requestId: String? = nil) async {
        await perform(name) { try await api.refreshSkill(name, requestId: requestId); return nil }
    }

    func remove(_ name: String) async {
        await perform(name) { try await api.removeSkill(name); return nil }
    }

    func installSuggested(_ id: String, agents: [String]) async {
        await perform(id) { try await api.installSkill(planId: nil, suggestion: id, agents: agents, requestId: nil) }
    }

    func installPlan(_ planId: String, agents: [String], requestId: String?) async -> Bool {
        var ok = false
        await perform(planId) {
            let job = try await api.installSkill(planId: planId, suggestion: nil, agents: agents, requestId: requestId)
            ok = true
            return job
        }
        return ok
    }

    func publish(_ name: String, agents: [String]) async {
        await perform(name) { try await api.publishDraft(name, agents: agents); return nil }
    }

    func discard(_ name: String) async {
        await perform(name) { try await api.discardDraft(name); return nil }
    }

    func dismiss(_ request: SkillRequest) async {
        await perform(request.id) { try await api.dismissSkillRequest(request.id); return nil }
    }

    /// "Do it" on an agent's request that needs no preview (update, on, off, refresh). An install opens the
    /// Add sheet instead, so the person sees the files first.
    func approve(_ request: SkillRequest) async {
        guard let name = request.name else { return }
        switch request.action {
        case "update": await update(name, requestId: request.id)
        case "refresh": await refresh(name, requestId: request.id)
        case "on", "off":
            guard let agent = request.agents.first else { return }
            await perform(request.id) {
                try await api.setSkill(name, agent: agent, on: request.action == "on", requestId: request.id)
                return nil
            }
        default: break
        }
    }

    /// The person's word on what kind of skill this is (ruling 35 §5). The backend stores it; the page reloads.
    func setKind(_ kind: SkillKind, to choice: String) async {
        guard !kind.key.isEmpty, choice != kind.kind else { return }
        await perform(kind.key) { try await api.setSkillKind(key: kind.key, kind: choice); return nil }
    }

    func preview(_ source: String, choose: String? = nil) async throws -> SkillPreview {
        try await api.previewSkill(source: source, choose: choose)
    }
}

/// The plugins group and the weight line, in words, pure (G201 slice (a)).
enum SkillPluginWords {
    /// "On", "Off", or "Per project" when Claude Code keeps the switch in a project's settings.
    static func state(_ plugin: SkillPlugin) -> String {
        switch plugin.enabled {
        case true?: Copy.Skills.pluginOn
        case false?: Copy.Skills.pluginOff
        case nil: Copy.Skills.pluginPerProject
        }
    }

    /// "v1.2.0 · market-a" — the version and where it came from, one meta line.
    static func meta(_ plugin: SkillPlugin) -> String {
        [plugin.version.isEmpty ? nil : "v\(plugin.version)", plugin.marketplace.isEmpty ? nil : plugin.marketplace]
            .compactMap { $0 }.joined(separator: " · ")
    }

    /// The kind as one word: "About you", "Generic", "Not sure".
    static func kind(_ kind: String) -> String {
        switch kind {
        case "about-you": Copy.Skills.kindAboutYou
        case "generic": Copy.Skills.kindGeneric
        default: Copy.Skills.kindUnknown
        }
    }

    /// "Claude Code 14 skills, about 1,200 tokens · Codex 3 skills, about 150 tokens" — nil when nothing loads.
    static func weight(_ weight: SkillsWeight) -> String? {
        let parts = weight.agents.filter { $0.skills > 0 }.map {
            Copy.Skills.weightPart($0.label, skills: $0.skills, tokens: $0.descriptionTokens)
        }
        return parts.isEmpty ? nil : Copy.Skills.weightLead + parts.joined(separator: " · ")
    }
}

/// Words for an agent's request, pure.
enum SkillRequestWords {
    static func line(_ request: SkillRequest, agents: [SkillAgentInfo]) -> String {
        let who = request.authorLabel ?? agents.first { $0.id == request.author }?.label
            ?? (request.author.isEmpty ? "An agent" : request.author)
        let name = request.name ?? ""
        let agent = request.agents.first.map { id in agents.first { $0.id == id }?.label ?? id } ?? ""
        let what: String
        switch request.action {
        case "install": what = Copy.Skills.askInstall(request.source ?? "a skill")
        case "update": what = Copy.Skills.askUpdate(name)
        case "on": what = Copy.Skills.askOn(name, agent)
        case "off": what = Copy.Skills.askOff(name, agent)
        default: what = Copy.Skills.askRefresh(name)
        }
        return Copy.Skills.asked(who, what)
    }
}
