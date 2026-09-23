import XCTest
@testable import CicadaApp

/// G138 — the wire, and the budget rule (at most five recommended at once).
final class RecommendedSkillTests: XCTestCase {
    private let payload = #"""
    {"reviewedAt":"2026-09-23","maxShown":5,"catalogSize":9,
     "recommended":[
      {"id":"watch","kind":"skill","rank":1,"title":"Watch a video","summary":"s","sourceUrl":"https://example.com","licence":"MIT",
       "symbol":"play.rectangle","agents":["claude-code","codex"],"state":{"claude-code":"not_installed","codex":"not_installed"},
       "needs":{"binaries":["ffmpeg"],"keys":[{"name":"GROQ_API_KEY","optional":true}]},
       "terms":{"summary":"t","url":"https://www.youtube.com/t/terms","safeUses":["your own recordings"]},
       "cicadaNote":"Cicada itself never downloads video.",
       "install":{"claude-code":{"runnable":true,"steps":[{"argv":["claude","plugin","install","watch@claude-video"],"tolerateFailure":false}],"env":{"CICADA_CAPTURE":"off"}}}},
      {"id":"a","kind":"skill","title":"A","summary":"s","sourceUrl":"https://example.com","licence":"MIT"},
      {"id":"b","kind":"skill","title":"B","summary":"s","sourceUrl":"https://example.com","licence":"MIT"},
      {"id":"c","kind":"skill","title":"C","summary":"s","sourceUrl":"https://example.com","licence":"MIT"},
      {"id":"d","kind":"skill","title":"D","summary":"s","sourceUrl":"https://example.com","licence":"MIT"},
      {"id":"e","kind":"skill","title":"E","summary":"s","sourceUrl":"https://example.com","licence":"MIT"}],
     "installed":[]}
    """#

    func testDecodesTolerantlyAndNeverShowsMoreThanFive() throws {
        let response = try JSONDecoder().decode(RecommendedSkillsResponse.self, from: Data(payload.utf8))
        let watch = try XCTUnwrap(response.recommended.first)
        XCTAssertEqual(watch.terms?.safeUses, ["your own recordings"])
        XCTAssertEqual(watch.install["claude-code"]?.steps.first?.argv.first, "claude")
        XCTAssertEqual(response.recommended[1].agents, [], "missing fields default")
        XCTAssertEqual(SkillsViewModel.shown(from: response).count, 5, "the budget rule, even if a server sent six")
    }

    func testAgentLabelsAndMarks() {
        XCTAssertEqual(SkillAgent.label("claude-code"), "Claude Code")
        XCTAssertEqual(SkillAgent.label("codex"), "Codex")
        XCTAssertEqual(SkillAgent.mark("claude-code"), "claude-code")
        XCTAssertEqual(SkillAgent.mark("codex"), "codex")
        XCTAssertEqual(SkillAgent.stateLabel("installed"), "Installed")
        XCTAssertEqual(SkillAgent.stateLabel("unknown"), "Set up in the agent")
    }

    func testSkillsIsACustomizeRow() {
        XCTAssertEqual(SettingsGroup.customize.sections, [.integrations, .agents, .remote, .skills])
        XCTAssertEqual(SettingsSection.skills.icon, "sparkles")
    }
}
