import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The Skills page (owner 2026-10-15): the wire decodes leniently, the model sends the person's clicks and follows a
/// job, and no Swift file writes into an
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
                       "cursor wants to give macos-harness to Codex")
    }

    func testABrokenSectionNeverBlanksThePage() throws {
        let page = try JSONDecoder().decode(SkillsPageData.self,
                                            from: Data(#"{"installed": "not a list", "agents": []}"#.utf8))
        XCTAssertEqual(page.installed, [])
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

    /// The agents cell reads "Claude Code, Codex +1 ▾"; a through-agent has a hollow tick and "through Claude Code".
    func testTheAgentsCellSummarisesAndNamesTheFolderAnAgentReadsThrough() {
        let agents = [SkillAgentState(id: "claude-code", label: "Claude Code", state: "on"),
                      SkillAgentState(id: "codex", label: "Codex", state: "on"),
                      SkillAgentState(id: "cursor", label: "Cursor", state: "through", canToggle: false,
                                      note: "Has it through Claude Code's folder."),
                      SkillAgentState(id: "hermes", label: "Hermes", state: "off")]
        XCTAssertEqual(SkillAgentWords.summary(agents), "Claude Code, Codex +1")
        XCTAssertEqual(SkillAgentWords.summary([agents[3]]), "None")
        XCTAssertEqual(SkillAgentWords.through(agents[2]), "through Claude Code")
        XCTAssertNil(SkillAgentWords.through(agents[0]))
        XCTAssertEqual(agents.map(SkillAgentWords.glyph), ["checkmark.square", "checkmark.square",
                                                           "checkmark.square.dashed", "square"])
        XCTAssertEqual(Copy.Skills.changesTitle(from: "v0.1.13", to: "v0.2.0"), "v0.1.13 → v0.2.0")
    }

    /// G201 slice (a): plugins decode as their own read-only group, every skill carries its kind as a word, the weight
    /// line says what each agent loads as an estimate, and a flip sends the row's key.
    static let pluginPayload = """
    {"agents": [], "installed": [{"name": "notes-helper", "title": "notes-helper", "kind": "generic",
                                  "kindBy": "person", "kindKey": "installed:notes-helper"}],
     "drafts": [{"name": "standup", "description": "d", "authorLabel": "Codex", "text": "",
                 "kind": "about-you", "kindBy": "cicada", "kindKey": "draft:standup"}],
     "noticed": [{"id": "retry-loop", "name": "Retry loop", "description": "d", "state": "held", "conversations": 1}],
     "plugins": [{"id": "alpha-kit@market-a", "name": "alpha-kit", "marketplace": "market-a", "version": "1.2.0",
                  "scope": "user", "enabled": true, "canToggle": false, "note": "n", "futureField": 1,
                  "skills": [{"name": "plan-it", "description": "Plan.", "userOnly": false, "kind": "generic",
                              "kindBy": "cicada", "kindKey": "plugin:alpha-kit@market-a/plan-it"},
                             {"name": "ship-it", "description": "Ship.", "userOnly": true, "kind": "generic",
                              "kindBy": "cicada", "kindKey": "plugin:alpha-kit@market-a/ship-it"}]},
                 {"id": "beta-lsp@market-b", "name": "beta-lsp", "marketplace": "market-b", "version": "",
                  "scope": "project", "enabled": null, "canToggle": false, "skills": []}],
     "weight": {"agents": [{"id": "claude-code", "label": "Claude Code", "skills": 3, "fromPlugins": 2,
                            "userOnly": 1, "descriptionTokens": 1234},
                           {"id": "codex", "label": "Codex", "skills": 0, "fromPlugins": 0, "userOnly": 0,
                            "descriptionTokens": 0}],
                "basis": "An estimate.", "estimate": true}}
    """

    func testPluginsDecodeAsTheirOwnGroupWithKindsAndWeight() throws {
        let page = try JSONDecoder().decode(SkillsPageData.self, from: Data(Self.pluginPayload.utf8))
        XCTAssertEqual(page.plugins.map(\.id), ["alpha-kit@market-a", "beta-lsp@market-b"])
        let alpha = page.plugins[0]
        XCTAssertFalse(alpha.canToggle)
        XCTAssertEqual(alpha.skills.map(\.userOnly), [false, true])
        XCTAssertEqual(SkillPluginWords.state(alpha), "On")
        XCTAssertEqual(SkillPluginWords.state(page.plugins[1]), "Per project")
        XCTAssertEqual(SkillPluginWords.meta(alpha), "v1.2.0 · market-a")
        XCTAssertEqual(SkillPluginWords.meta(page.plugins[1]), "market-b")
        XCTAssertEqual(page.installed[0].kind, SkillKind(kind: "generic", by: "person", key: "installed:notes-helper"))
        XCTAssertEqual(page.drafts[0].kind.kind, "about-you")
        // A noticed skill from an older backend has no kind: it reads "Not sure", never a guess.
        XCTAssertEqual(SkillPluginWords.kind(page.noticed[0].kind.kind), "Not sure")
        XCTAssertEqual(["about-you", "generic", "unknown"].map(SkillPluginWords.kind), ["About you", "Generic", "Not sure"])
        let line = try XCTUnwrap(SkillPluginWords.weight(page.weight))
        XCTAssertTrue(line.hasPrefix("Loaded every session: Claude Code 3 skills, about "), line)
        XCTAssertFalse(line.contains("Codex"), "an agent that loads nothing is left out")
        XCTAssertNil(SkillPluginWords.weight(SkillsWeight()))
    }

    func testAnOlderBackendWithoutPluginsStillDecodes() throws {
        let page = try JSONDecoder().decode(SkillsPageData.self, from: Data(Self.payload.utf8))
        XCTAssertEqual(page.plugins, [])
        XCTAssertEqual(page.weight, SkillsWeight())
        XCTAssertEqual(page.installed.first?.kind.kind, "unknown")
    }

    func testAKindFlipSendsTheRowsKeyAndNothingWhenUnchanged() async throws {
        let api = FakeSkillsAPI()
        api.page = try JSONDecoder().decode(SkillsPageData.self, from: Data(Self.pluginPayload.utf8))
        let model = SkillsPageModel(api: api, pollInterval: .milliseconds(1))
        await model.load()
        let skill = try XCTUnwrap(model.data?.plugins.first?.skills.first)
        await model.setKind(skill.kind, to: "generic")
        XCTAssertTrue(api.kinds.isEmpty, "choosing what it already is sends nothing")
        await model.setKind(skill.kind, to: "about-you")
        XCTAssertEqual(api.kinds.first?.key, "plugin:alpha-kit@market-a/plan-it")
        XCTAssertEqual(api.kinds.first?.kind, "about-you")
    }

    /// G201 slice (a)'s review render: the table with its Kind column, the weight line and the Plugins group, light
    /// and dark, offscreen on synthetic data. Env-gated: `CICADA_SKILLS_SNAPSHOTS=<dir>`.
    func testWriteThePluginsGroupRender() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_SKILLS_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_SKILLS_SNAPSHOTS=<dir> to write the review render")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        CicadaTheme.uiScale = 1
        var merged = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(Self.payload.utf8)) as? [String: Any])
        let plugins = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(Self.pluginPayload.utf8)) as? [String: Any])
        merged["plugins"] = plugins["plugins"]
        merged["weight"] = plugins["weight"]
        let api = FakeSkillsAPI()
        api.page = try JSONDecoder().decode(SkillsPageData.self, from: JSONSerialization.data(withJSONObject: merged))
        let model = SkillsPageModel(api: api, pollInterval: .milliseconds(1))
        await model.load()
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let view = SkillsPageView(model: model, tab: .constant(nil), selected: .constant(nil))
                .environment(\.colorScheme, mode == .dark ? .dark : .light)
            let host = NSHostingView(rootView: view)
            host.frame = NSRect(x: 0, y: 0, width: 1376, height: 640)
            let window = NSWindow(contentRect: host.frame.offsetBy(dx: -20_000, dy: -20_000), styleMask: [.borderless],
                                  backing: .buffered, defer: false)
            window.appearance = NSAppearance(named: mode == .dark ? .darkAqua : .aqua)
            window.contentView = host
            window.orderFrontRegardless()
            defer { window.orderOut(nil) }
            host.layoutSubtreeIfNeeded()
            RunLoop.main.run(until: Date().addingTimeInterval(0.3))
            host.layoutSubtreeIfNeeded()
            let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
            host.cacheDisplay(in: host.bounds, to: rep)
            let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
            try png.write(to: URL(fileURLWithPath: dir).appendingPathComponent("skills-plugins-\(mode == .dark ? "dark" : "light").png"))
        }
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
    var toggles: [(name: String, agent: String, on: Bool)] = []
    var jobStates: [String] = []
    var kinds: [(key: String, kind: String?)] = []

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
    func setSkillKind(key: String, kind: String?) async throws { kinds.append((key, kind)) }
}
