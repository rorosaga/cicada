import Foundation

/// The Skills page's routes (owner 2026-10-15; `api/routers/skills.py`). Not a Store domain: the page loads it when
/// shown and after each action, and caches it in memory (`SkillsPageModel`). On a protocol so the model's tests fake it.
protocol SkillsAPI: Sendable {
    func skillsPage() async throws -> SkillsPageData
    func checkSkillUpdates(auto: Bool) async throws
    func previewSkill(source: String, choose: String?) async throws -> SkillPreview
    func installSkill(planId: String?, suggestion: String?, agents: [String], requestId: String?) async throws
        -> SkillJob?
    func updateSkill(_ name: String, requestId: String?) async throws -> SkillJob?
    func updateAllSkills() async throws -> SkillJob?
    func setSkill(_ name: String, agent: String, on: Bool, requestId: String?) async throws
    func refreshSkill(_ name: String, requestId: String?) async throws
    func removeSkill(_ name: String) async throws
    func publishDraft(_ name: String, agents: [String]) async throws
    func discardDraft(_ name: String) async throws
    func dismissSkillRequest(_ id: String) async throws
    func skillJob(_ id: String) async throws -> SkillJob
    func skillsOnboarding() async throws -> SkillsOnboardingOffer
    func answerSkillsOnboarding(install: [String], agents: [String]) async throws -> SkillJob?
}

/// A job, when the answer carries one (`{"job": {...}}`).
private struct JobEnvelope: Decodable { var job: SkillJob? }

extension APIClient: SkillsAPI {
    nonisolated static func skillPath(_ parts: String...) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return "/skills/" + parts.map { $0.addingPercentEncoding(withAllowedCharacters: allowed) ?? $0 }
            .joined(separator: "/")
    }

    private func decode<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        do { return try JSONDecoder().decode(type, from: data) } catch { throw APIError.decodingError("\(error)") }
    }

    private func requestBody(_ requestId: String?) -> [String: Any] {
        requestId.map { ["requestId": $0] } ?? [:]
    }

    func skillsPage() async throws -> SkillsPageData {
        try decode(SkillsPageData.self, try await skillsRequest("GET", "/skills"))
    }

    func checkSkillUpdates(auto: Bool) async throws {
        _ = try await skillsRequest("POST", "/skills/check", body: ["auto": auto])
    }

    func previewSkill(source: String, choose: String?) async throws -> SkillPreview {
        var body: [String: Any] = ["source": source]
        if let choose { body["choose"] = choose }
        return try decode(SkillPreview.self, try await skillsRequest("POST", "/skills/preview", body: body))
    }

    func installSkill(planId: String?, suggestion: String?, agents: [String], requestId: String?) async throws
        -> SkillJob? {
        var body: [String: Any] = ["agents": agents]
        if let planId { body["planId"] = planId }
        if let suggestion { body["suggestion"] = suggestion }
        if let requestId { body["requestId"] = requestId }
        let data = try await skillsRequest("POST", "/skills/install", body: body, timeout: 300)
        return (try? JSONDecoder().decode(JobEnvelope.self, from: data))?.job
    }

    func updateSkill(_ name: String, requestId: String?) async throws -> SkillJob? {
        let data = try await skillsRequest("POST", Self.skillPath(name, "update"), body: requestBody(requestId))
        return try decode(JobEnvelope.self, data).job
    }

    func updateAllSkills() async throws -> SkillJob? {
        try decode(JobEnvelope.self, try await skillsRequest("POST", "/skills/update-all", body: [:])).job
    }

    func setSkill(_ name: String, agent: String, on: Bool, requestId: String?) async throws {
        var body: [String: Any] = ["on": on]
        if let requestId { body["requestId"] = requestId }
        _ = try await skillsRequest("PUT", Self.skillPath(name, "agents", agent), body: body)
    }

    func refreshSkill(_ name: String, requestId: String?) async throws {
        _ = try await skillsRequest("POST", Self.skillPath(name, "refresh"), body: requestBody(requestId))
    }

    func removeSkill(_ name: String) async throws {
        _ = try await skillsRequest("DELETE", Self.skillPath(name))
    }

    func publishDraft(_ name: String, agents: [String]) async throws {
        _ = try await skillsRequest("POST", Self.skillPath("drafts", name, "publish"), body: ["agents": agents])
    }

    func discardDraft(_ name: String) async throws {
        _ = try await skillsRequest("DELETE", Self.skillPath("drafts", name))
    }

    func dismissSkillRequest(_ id: String) async throws {
        _ = try await skillsRequest("POST", Self.skillPath("requests", id, "dismiss"), body: [:])
    }

    func skillJob(_ id: String) async throws -> SkillJob {
        try decode(SkillJob.self, try await skillsRequest("GET", Self.skillPath("jobs", id)))
    }

    func skillsOnboarding() async throws -> SkillsOnboardingOffer {
        try decode(SkillsOnboardingOffer.self, try await skillsRequest("GET", "/skills/onboarding"))
    }

    func answerSkillsOnboarding(install: [String], agents: [String]) async throws -> SkillJob? {
        let data = try await skillsRequest("POST", "/skills/onboarding", body: ["install": install, "agents": agents])
        return try decode(JobEnvelope.self, data).job
    }
}

/// The sentence a refusal carries (`{"detail": "…"}`), or a plain one when the backend could not be reached.
enum SkillsError {
    static func words(_ error: Error) -> String {
        if case APIError.httpError(_, let body) = error,
           let data = body.data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let detail = object["detail"] as? String, !detail.isEmpty {
            return detail
        }
        if case APIError.serverUnreachable = error { return Copy.Skills.unreachable }
        if (error as? URLError) != nil { return Copy.Skills.unreachable }
        return Copy.Skills.somethingWrong
    }
}
