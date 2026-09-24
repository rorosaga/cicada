import XCTest
@testable import CicadaApp

/// Round-4 C3/C4 (D1, R-FA14) — a model id as a person reads it, and every surface that names who wrote a belief.
final class ModelNamesTests: XCTestCase {
    func testModelIdsReadAsPeopleSayThem() {
        let table: [(String, String)] = [
            ("claude-opus-5-5", "Opus 5.5"), ("claude-sonnet-5", "Sonnet 5"), ("gpt-5.5-codex", "GPT-5.5 Codex"),
            ("claude-opus-5-5[1m]", "Opus 5.5"), ("claude-sonnet-4-5-20250929", "Sonnet 4.5"),
            ("claude-3-5-sonnet-20241022", "Sonnet 3.5"), ("claude-haiku-4-5", "Haiku 4.5"),
            ("gpt-4o-mini", "GPT-4o mini"), ("gemini-2.5-pro", "Gemini 2.5 Pro"),
            ("o3", "o3"), ("llama3.1:8b", "llama3.1:8b"), ("claude-mystery-x", "claude-mystery-x"), ("", ""),
        ]
        for (raw, expected) in table { XCTAssertEqual(ModelNames.display(raw), expected, raw) }
    }

    func testEffortInWords() {
        XCTAssertEqual(ModelNames.effort("high"), "high effort")
        XCTAssertEqual(ModelNames.effort("XHIGH"), "extra-high effort")
        XCTAssertEqual(ModelNames.effort("max"), "max effort")
        XCTAssertNil(ModelNames.effort("turbo"), "an unknown level says nothing rather than a guess")
        XCTAssertNil(ModelNames.effort(nil))
    }

    func testTheAgentLine() {
        XCTAssertEqual(ModelNames.agentLine(agent: "Claude Code", harness: "claude-code", model: "claude-opus-5-5", effort: "high"),
                       "Claude Code · Opus 5.5 · high effort")
        XCTAssertEqual(ModelNames.agentLine(agent: "Claude Desktop", harness: "claude-desktop", model: nil, effort: nil),
                       "Claude Desktop · model not shared by this app", "D1 — an app with no capture says so")
        XCTAssertEqual(ModelNames.agentLine(agent: "Claude Code", harness: "claude-code", model: nil, effort: nil),
                       "Claude Code", "a capturing harness before D1: nothing added, never a guess")
        XCTAssertNil(ModelNames.agentLine(agent: nil, harness: nil, model: nil, effort: nil))
    }

    private let docJSON = #"""
        {"episode":"ep_1","text":"assistant: hi","harness":"claude-code","agent":{"model":"claude-opus-5-5","effort":"high"},
         "turns":[{"index":0,"start":0,"contentStart":11,"end":13,"role":"assistant","model":"claude-opus-5-5","effort":"high"}]}
        """#

    func testTheNewFieldsDecodeAndAreOptional() throws {
        let ev = try JSONDecoder().decode(Evidence.self, from: Data(#"""
            {"episode":"ep_2026-09-24_001","start":0,"end":5,"kind":"assistant","hash":"h","model":"claude-opus-5-5","effort":"high"}
            """#.utf8))
        XCTAssertEqual(ev.model, "claude-opus-5-5")
        XCTAssertEqual(ev.effort, "high")
        let legacy = try JSONDecoder().decode(Evidence.self, from: Data(#"{"episode":"ep_x","start":0,"end":1,"kind":"user"}"#.utf8))
        XCTAssertNil(legacy.model)
        let claim = try JSONDecoder().decode(Claim.self, from: Data(#"""
            {"id":"clm_1","authoredBy":"claude-code","authorKind":"harness","authorModel":"claude-opus-5-5","authorEffort":"xhigh"}
            """#.utf8))
        XCTAssertEqual(claim.authorModel, "claude-opus-5-5")
        XCTAssertEqual(claim.authorEffort, "xhigh")
        XCTAssertNil(try JSONDecoder().decode(Claim.self, from: Data(#"{"id":"clm_2"}"#.utf8)).authorModel)
        let doc = try JSONDecoder().decode(EpisodeText.self, from: Data(docJSON.utf8))
        XCTAssertEqual(doc.agent?.model, "claude-opus-5-5")
        XCTAssertEqual(doc.turns.first?.effort, "high")
        let contributor = try JSONDecoder().decode(ProvenanceContributor.self, from: Data(#"""
            {"author":"claude-code","kind":"harness","claims":3,"models":[{"model":"claude-opus-5-5","effort":"high","beliefs":2},{"model":"claude-sonnet-5","beliefs":1}]}
            """#.utf8))
        XCTAssertEqual(contributor.models.map(\.model), ["claude-opus-5-5", "claude-sonnet-5"])
        XCTAssertEqual(try JSONDecoder().decode(ProvenanceContributor.self, from: Data(#"{"author":"a"}"#.utf8)).models, [])
    }

    /// The global decode-tolerance rule: a mistyped optional from a backend a shape ahead never fails the whole value.
    func testAMistypedModelFieldNeverFailsTheWholeValue() throws {
        let claim = try JSONDecoder().decode(Claim.self, from: Data(#"{"id":"clm_3","text":"t","authorModel":42,"authorEffort":["x"]}"#.utf8))
        XCTAssertEqual(claim.text, "t")
        XCTAssertNil(claim.authorModel)
        let ev = try JSONDecoder().decode(Evidence.self, from: Data(#"{"episode":"ep_x","start":0,"end":1,"kind":"assistant","model":{"a":1}}"#.utf8))
        XCTAssertEqual(ev.end, 1)
        XCTAssertNil(ev.model)
        let doc = try JSONDecoder().decode(EpisodeText.self, from: Data(#"{"episode":"ep_1","text":"x","agent":"opus"}"#.utf8))
        XCTAssertNil(doc.agent)
        let c = try JSONDecoder().decode(ProvenanceContributor.self, from: Data(#"{"author":"a","claims":2,"models":"opus"}"#.utf8))
        XCTAssertEqual(c.claims, 2)
        XCTAssertEqual(c.models, [])
    }

    /// The Store's on-disk cache re-encodes these types: the new keys survive a round trip.
    func testTheNewFieldsRoundTripThroughEncoding() throws {
        let ev = Evidence(episode: "ep_1", start: 0, end: 2, kind: .assistant, model: "claude-opus-5-5", effort: "high")
        let back = try JSONDecoder().decode(Evidence.self, from: JSONEncoder().encode(ev))
        XCTAssertEqual(back, ev)
        let doc = try JSONDecoder().decode(EpisodeText.self, from: Data(docJSON.utf8))
        XCTAssertEqual(try JSONDecoder().decode(EpisodeText.self, from: JSONEncoder().encode(doc)), doc)
    }

    // MARK: The Reader (C4)

    func testTheReaderSaysTheAgentLine() throws {
        let doc = try JSONDecoder().decode(EpisodeText.self, from: Data(docJSON.utf8))
        XCTAssertEqual(ReaderHeader.meta(doc), "Claude Code · Opus 5.5 · high effort · 1 turn")
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(doc.turns[0], harness: doc.harness, origin: doc.origin),
                       "Claude Code · Opus 5.5 · high effort")

        let desktop = EpisodeText(episode: "ep_2", text: "x", harness: "claude-desktop")
        XCTAssertTrue(ReaderHeader.meta(desktop).hasPrefix("Claude Desktop · model not shared by this app"),
                      ReaderHeader.meta(desktop))
        let preD1 = EpisodeText(episode: "ep_3", text: "x", harness: "claude-code",
                                turns: [EpisodeTurn(index: 0, start: 0, contentStart: 0, end: 1, role: "assistant")])
        XCTAssertTrue(ReaderHeader.meta(preD1).hasPrefix("Claude Code · "), ReaderHeader.meta(preD1))
        XCTAssertFalse(ReaderHeader.meta(preD1).contains("not shared"))
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(preD1.turns[0], harness: "claude-code", origin: nil), "Claude Code",
                       "a turn with no model is today's label")
    }
}
