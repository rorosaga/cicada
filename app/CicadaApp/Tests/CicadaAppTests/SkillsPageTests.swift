import XCTest
@testable import CicadaApp

/// The Skills page (owner 2026-10-15): the wire decodes leniently, the model sends the person's clicks and follows a
/// job, onboarding's defaults tick the two harnesses and never the video skill, and no Swift file writes into an
/// agent's skill folder (the backend's `skill_store` is the one writer).
@MainActor
final class SkillsPageTests: XCTestCase {
    static let payload = """
    {"agents": [{"id": "claude-code", "label": "Claude Code", "folder": "~/.claude/skills"},
                {"id": "codex", "label": "Codex", "folder": "~/.codex/skills"}],
     "installed": [{"name": "macos-harness", "title": "Control your Mac", "description": "Use apps.",
                    "source": {"kind": "github", "label": "browser-use/macos-harness",
                               "url": "https://github.com/browser-use/macos-harness", "via": null},
                    "version": {"label": "v0.2.1", "tool": "0.2.1", "text": "0.1.2"},
                    "update": {"state": "available", "latest": "v0.3.0", "linkLabel": "Release notes",
                               "link": "https://example.com/r", "changes": [{"title": "v0.3.0", "date": "2026-10-20",
                                                                            "detail": "Faster reads.", "url": ""}]},
                    "agents": [{"id": "claude-code", "label": "Claude Code", "state": "on", "canToggle": true},
                               {"id": "codex", "label": "Codex", "state": "through", "canToggle": false,
                                "note": "Has it through the shared skills folder."}],
                    "tool": {"command": "macos-harness", "package": "macos-harness", "installed": true,
                             "version": "0.2.1", "from": "browser-use/macos-harness", "text": "older", "uv": true},
                    "permissions": {"app": "Terminal", "ready": false, "items": [], "line": "macOS has not given x."},
                    "catalogId": "macos-harness", "futureField": 3,
                    "details": {"folders": [{"path": "~/.claude/skills/macos-harness", "linked": false, "byCicada": true}],
                                "commit": null, "ref": null, "path": null, "installedAt": null, "licence": null}}],
     "suggested": [{"id": "watch", "kind": "skill", "title": "Watch a video", "summary": "Watches.", "method": "copy"}],
     "drafts": [{"name": "release-notes", "description": "Writes notes.", "author": "codex", "authorLabel": "Codex",
                 "reason": "Every Friday.", "created": "x", "updated": "x", "revision": 1, "state": "held",
                 "text": "---\\nname: release-notes\\n---\\n"}],
     "noticed": [], "requests": [{"id": "r1", "action": "on", "name": "macos-harness", "source": null,
                                  "agents": ["codex"], "reason": "Codex too.", "author": "cursor", "session": null,
                                  "at": "2026-10-15T00:00:00+00:00"}],
     "checkedAt": "2026-10-15T00:00:00+00:00", "uv": {"present": true, "installUrl": "https://x", "installCommand": "c"},
     "jobs": [], "reviewedAt": "2026-09-23"}
    """

    func testThePageDecodesWithAFieldItDoesNotKnow() throws {
        let page = try JSONDecoder().decode(SkillsPageData.self, from: Data(Self.payload.utf8))
        let skill = try XCTUnwrap(page.installed.first)
        XCTAssertEqual(skill.tool?.text, "older")
        XCTAssertEqual(skill.update.changes?.first?.detail, "Faster reads.")
        XCTAssertEqual(skill.agents.map(\.isOn), [true, true])
        XCTAssertFalse(skill.agents[1].canToggle)
        XCTAssertEqual(page.drafts.first?.authorLabel, "Codex")
        XCTAssertEqual(SkillRequestWords.line(page.requests[0], agents: page.agents),
                       "cursor asked to give macos-harness to Codex")
    }

    func testABrokenSectionNeverBlanksThePage() throws {
        let page = try JSONDecoder().decode(SkillsPageData.self,
                                            from: Data(#"{"installed": "not a list", "agents": []}"#.utf8))
        XCTAssertEqual(page.installed, [])
    }

    func testOnboardingTicksTheTwoHarnessesNeverTheVideoSkillAndNothingNeedingUvWithoutIt() {
        typealias S = SkillsOnboardingOffer.Suggestion
        let offer = [S(id: "browser-harness", default: true, needsUv: true, installed: false),
                     S(id: "macos-harness", default: true, needsUv: true, installed: false),
                     S(id: "watch", default: false, needsUv: false, installed: false)]
        XCTAssertEqual(SkillsStepModel.defaults(offer, uvPresent: true), ["browser-harness", "macos-harness"])
        XCTAssertEqual(SkillsStepModel.defaults(offer, uvPresent: false), [])
        var installed = offer
        installed[1].installed = true
        XCTAssertEqual(SkillsStepModel.defaults(installed, uvPresent: true), ["browser-harness"])
    }

    func testNoThanksPostsAnEmptyAnswer() async {
        let api = FakeSkillsAPI()
        api.offer = SkillsOnboardingOffer(suggestions: [.init(id: "macos-harness", default: true, needsUv: true,
                                                              installed: false)],
                                          uv: { var u = UvInfo(); u.present = true; return u }(), agents: [])
        let step = SkillsStepModel(api: api)
        await step.load()
        XCTAssertEqual(step.ticked, ["macos-harness"])
        step.noThanks()
        await step.submit()
        XCTAssertEqual(api.answers, [[]])
        XCTAssertTrue(step.answered)
    }

    func testAToggleSendsTheOppositeOfWhatIsShownAndAJobIsFollowedToTheEnd() async throws {
        let api = FakeSkillsAPI()
        api.page = try JSONDecoder().decode(SkillsPageData.self, from: Data(Self.payload.utf8))
        let model = SkillsPageModel(api: api, pollInterval: .milliseconds(1))
        await model.load()
        let skill = try XCTUnwrap(model.data?.installed.first)
        await model.toggle(skill, agent: skill.agents[0])
        XCTAssertEqual(api.toggles.first?.on, false)
        api.jobStates = ["running", "failed"]
        await model.update("macos-harness")
        XCTAssertEqual(model.message, "uv couldn't install it.")
        XCTAssertTrue(model.jobs.isEmpty)
        XCTAssertEqual(model.updatesAvailable.map(\.name), ["macos-harness"])
    }

    /// The backend's `skill_store` writes every skill folder; the app names none (it used to, R-O26).
    func testNoSwiftFileNamesAnAgentsSkillFolder() throws {
        let offenders = try ThemeTokenTests.swiftSources().filter { file in
            let code = try String(contentsOf: file, encoding: .utf8)
                .components(separatedBy: .newlines)
                .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
                .joined(separator: "\n")
            return code.contains(".claude/skills") || code.contains(".agents/skills")
        }.map(\.lastPathComponent)
        XCTAssertEqual(offenders, [])
    }
}

private final class FakeSkillsAPI: SkillsAPI, @unchecked Sendable {
    var page = SkillsPageData()
    var offer = SkillsOnboardingOffer()
    var answers: [[String]] = []
    var toggles: [(name: String, agent: String, on: Bool)] = []
    var jobStates: [String] = []

    func skillsPage() async throws -> SkillsPageData { page }
    func checkSkillUpdates(auto: Bool) async throws {}
    func previewSkill(source: String, choose: String?) async throws -> SkillPreview { SkillPreview() }
    func installSkill(planId: String?, suggestion: String?, agents: [String], requestId: String?) async throws
        -> SkillJob? { nil }
    func updateSkill(_ name: String, requestId: String?) async throws -> SkillJob? {
        SkillJob(id: "j1", kind: "update", label: name, state: "running")
    }
    func updateAllSkills() async throws -> SkillJob? { nil }
    func setSkill(_ name: String, agent: String, on: Bool, requestId: String?) async throws {
        toggles.append((name, agent, on))
    }
    func refreshSkill(_ name: String, requestId: String?) async throws {}
    func removeSkill(_ name: String) async throws {}
    func publishDraft(_ name: String, agents: [String]) async throws {}
    func discardDraft(_ name: String) async throws {}
    func dismissSkillRequest(_ id: String) async throws {}
    func skillJob(_ id: String) async throws -> SkillJob {
        let state = jobStates.isEmpty ? "done" : jobStates.removeFirst()
        return SkillJob(id: id, kind: "update", label: "x", state: state,
                        message: state == "failed" ? "uv couldn't install it." : nil)
    }
    func skillsOnboarding() async throws -> SkillsOnboardingOffer { offer }
    func answerSkillsOnboarding(install: [String], agents: [String]) async throws -> SkillJob? {
        answers.append(install)
        return nil
    }
}
