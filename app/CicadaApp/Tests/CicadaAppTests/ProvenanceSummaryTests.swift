import XCTest
@testable import CicadaApp

/// Design §4.5 / §4.10 — "Where this came from" in sentences: zero, one and
/// many conversations, mixed agents, harness authors, legacy-only pages, and
/// coverage stated rather than implied.
final class ProvenanceSummaryTests: XCTestCase {

    private func row(_ ep: String, harness: String? = nil, origin: String? = nil,
                     conversation: String? = nil, available: Bool = true) -> ProvenanceConversation {
        ProvenanceConversation(conversationId: conversation, episodeId: ep, harness: harness, origin: origin,
                               available: available)
    }

    // MARK: Conversations

    func testNoConversationsSaysSoPlainly() {
        let p = EntityProvenance(entityId: "alpha-project")
        XCTAssertEqual(ProvenanceSummary.conversationsSentence(p), "Recorded before Cicada kept conversation links.")
    }

    func testOneConversationAndOnePlace() {
        let p = EntityProvenance(entityId: "a", conversations: [row("ep_1", harness: "claude-code")],
                                 totals: ProvenanceTotals(conversations: 1))
        XCTAssertEqual(ProvenanceSummary.conversationsSentence(p), "From 1 conversation in Claude Code.")
    }

    func testManyConversationsAcrossPlacesAreBrokenDownMostFirst() {
        let p = EntityProvenance(entityId: "a", conversations: [
            row("ep_1", harness: "claude-code"), row("ep_2", harness: "claude-code"),
            row("ep_3", origin: "chatgpt-export"), row("ep_4", origin: "telegram"),
        ], totals: ProvenanceTotals(conversations: 4))
        XCTAssertEqual(ProvenanceSummary.conversationsSentence(p),
                       "From 4 conversations: 2 in Claude Code, 1 in ChatGPT and 1 in Telegram.")
    }

    func testAPartialPayloadStatesOnlyTheHonestTotal() {
        let p = EntityProvenance(entityId: "a", conversations: [row("ep_1", harness: "claude-code")],
                                 totals: ProvenanceTotals(conversations: 57))
        XCTAssertEqual(ProvenanceSummary.conversationsSentence(p), "From 57 conversations.",
                       "a breakdown of 50 shipped rows would be a sample, not the truth (R-PB7)")
    }

    func testAnUnknownPlaceIsOtherPlacesNeverARawId() {
        XCTAssertEqual(ProvenanceSummary.placeName(harness: nil, origin: nil), "other places")
        XCTAssertEqual(ProvenanceSummary.placeName(harness: "unknown", origin: "unknown"), "other places")
    }

    // MARK: Writers

    func testWritersNameTheModelWithItsVendorAndYouInLowerCase() {
        let p = EntityProvenance(entityId: "a", contributors: [
            ProvenanceContributor(author: "claude-sonnet-4-5", kind: "model", provider: "anthropic", claims: 12),
            ProvenanceContributor(author: "user", kind: "user", claims: 4),
            ProvenanceContributor(author: "unknown", kind: "unknown", commits: 9),
        ])
        XCTAssertEqual(ProvenanceSummary.writersSentence(p), "Written by Claude (claude-sonnet-4-5) and you.",
                       "a legacy untrailered commit is its chip's to explain, not the sentence's")
    }

    func testAHarnessAuthorIsNamedAfterItsAppAndAnUnmatchedModelKeepsItsId() {
        let p = EntityProvenance(entityId: "a", contributors: [
            ProvenanceContributor(author: "claude-code", kind: "harness", claims: 2),
            ProvenanceContributor(author: "mcp-agentic-write", kind: "model", provider: "other", claims: 1),
            ProvenanceContributor(author: "cicada", kind: "system", commits: 3),
        ])
        XCTAssertEqual(ProvenanceSummary.writersSentence(p), "Written by Claude Code, mcp-agentic-write and Cicada.")
    }

    func testMoreThanThreeWritersFoldIntoOthers() {
        let p = EntityProvenance(entityId: "a", contributors: (1...5).map {
            ProvenanceContributor(author: "model-\($0)", kind: "model", provider: "other", claims: 1)
        })
        XCTAssertEqual(ProvenanceSummary.writersSentence(p), "Written by model-1, model-2, model-3 and 2 others.")
        XCTAssertNil(ProvenanceSummary.writersSentence(EntityProvenance(entityId: "a")))
    }

    func testChipCountUsesTwoNounsNeverOneNumberForTwoThings() {
        XCTAssertEqual(ProvenanceSummary.chipCount(ProvenanceContributor(author: "u", kind: "user",
                                                                        claims: 12, commits: 3)),
                       "12 beliefs · 3 edits")
        XCTAssertEqual(ProvenanceSummary.chipCount(ProvenanceContributor(author: "cicada", kind: "system",
                                                                        commits: 1)), "1 edit")
    }

    // MARK: Coverage

    func testCoverageIsStatedAndLegacyIsExplained() {
        let t = ProvenanceTotals(claims: 18, withSpan: 9, legacy: 7, conversations: 3)
        XCTAssertEqual(ProvenanceSummary.coverage(t), "9 of 18 beliefs here have an exact quote.")
        XCTAssertEqual(ProvenanceSummary.legacyNote(t), "7 were noted before Cicada kept exact quotes.")
        XCTAssertEqual(ProvenanceSummary.coverage(ProvenanceTotals(claims: 1)),
                       "0 of 1 belief here has an exact quote.")
        XCTAssertEqual(ProvenanceSummary.legacyNote(ProvenanceTotals(claims: 1, legacy: 1)),
                       "1 was noted before Cicada kept exact quotes.")
        XCTAssertNil(ProvenanceSummary.legacyNote(ProvenanceTotals(claims: 3, withSpan: 3)))
        XCTAssertEqual(ProvenanceSummary.coverage(ProvenanceTotals()), Copy.Provenance.noBeliefs)
    }

    func testTheAlsoLineListsPagesThenInferred() {
        let p = EntityProvenance(entityId: "a", pages: [ProvenancePage(entityId: "media-example-com",
                                                                        name: "example.com", claimCount: 1)],
                                 inferredCount: 2)
        XCTAssertEqual(ProvenanceSummary.alsoItems(p),
                       ["From the page example.com · 1 belief", "Inferred by Cicada · 2 beliefs"])
    }

    // MARK: History hand-off

    func testOnlyAvailableConversationsMapToAnEpisode() {
        let p = EntityProvenance(entityId: "a", conversations: [
            row("ep_2", conversation: "ses_alpha"),
            row("ep_9", conversation: "ses_gone", available: false),
            row("ep_5"),
        ])
        XCTAssertEqual(ProvenanceSummary.episodeByConversation(p), ["ses_alpha": "ep_2"])
        XCTAssertEqual(ProvenanceSummary.episodeByConversation(nil), [:])
    }

    // MARK: Models (round-4 C4, R-FA14)

    func testAHarnessChipNamesItsModels() throws {
        let c = try JSONDecoder().decode(ProvenanceContributor.self, from: Data(#"""
            {"author":"claude-code","kind":"harness","claims":3,"models":[{"model":"claude-opus-5-5","effort":"high","beliefs":2},{"model":"claude-sonnet-5","beliefs":1}]}
            """#.utf8))
        XCTAssertEqual(ProvenanceSummary.modelsLine(c), "Opus 5.5 · high effort, Sonnet 5")
        XCTAssertEqual(ProvenanceSummary.modelsHelp(c), ["Opus 5.5 · high effort — 2 beliefs", "Sonnet 5 — 1 belief"])

        let three = ProvenanceContributor(author: "codex", kind: "harness", claims: 6, models: [
            ContributorModel(model: "gpt-5.5-codex", beliefs: 1),
            ContributorModel(model: "claude-opus-5-5", effort: "max", beliefs: 3),
            ContributorModel(model: "claude-sonnet-5", beliefs: 2),
        ])
        XCTAssertEqual(ProvenanceSummary.modelsLine(three), "Opus 5.5 · max effort, Sonnet 5, +1 more")
    }

    func testAHarnessWithNoModelsSaysOnlyWhatIsTrue() {
        XCTAssertEqual(ProvenanceSummary.modelsLine(ProvenanceContributor(author: "claude-desktop", kind: "harness")),
                       "model not shared by this app")
        XCTAssertNil(ProvenanceSummary.modelsLine(ProvenanceContributor(author: "claude-code", kind: "harness")),
                     "a write from before D1: nothing added")
        XCTAssertNil(ProvenanceSummary.modelsLine(ProvenanceContributor(author: "gpt-5.4-mini", kind: "model")))
        XCTAssertNil(ProvenanceSummary.modelsLine(ProvenanceContributor(author: "user", kind: "user")))
        XCTAssertEqual(ProvenanceSummary.modelsHelp(ProvenanceContributor(author: "claude-desktop", kind: "harness")), [])
    }

    func testVendorNamesOnlyForProvidersWeCanName() {
        XCTAssertEqual(ContributorIdentity.vendorName(provider: "anthropic"), "Claude")
        XCTAssertEqual(ContributorIdentity.vendorName(provider: "openai"), "OpenAI")
        XCTAssertEqual(ContributorIdentity.vendorName(provider: "google"), "Google",
                       "`google` also answers for Gemma (`git_service._PROVIDER_SUBSTRINGS`) — a family name would guess")
        XCTAssertNil(ContributorIdentity.vendorName(provider: "other"))
        XCTAssertNil(ContributorIdentity.vendorName(provider: nil))
    }
}
