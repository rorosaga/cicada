import XCTest
@testable import CicadaApp

/// Design §4.2 / §4.10 — every evidence kind has a plain label; a derived
/// match never says "You said"; an agent with no known harness is "The
/// agent"; a legacy claim gets derived chips, capped; and the footer's author
/// and trust pills speak plain words.
final class EvidenceChipLabelTests: XCTestCase {

    private let utc = TimeZone(identifier: "UTC")!
    private let us = Locale(identifier: "en_US")

    // MARK: Labels

    func testEveryKindMapsToAPlainLabel() {
        for kind in EvidenceKind.allCases {
            XCTAssertFalse(EvidenceLabel.speaker(kind: kind, agent: nil).isEmpty, "\(kind)")
        }
        XCTAssertEqual(EvidenceLabel.speaker(kind: .user, agent: "Claude Code"), "You said")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .assistant, agent: "Claude Code"), "Claude Code replied")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .assistant, agent: nil), "The agent replied")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .page, agent: nil), "From the page")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .speaker, agent: nil, speakerName: "Speaker 2"), "Speaker 2 said")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .speaker, agent: nil, speakerName: "user"), "Someone else said",
                       "a role word is not a meeting speaker's name")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .reasoning, agent: nil), "Inferred")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .unknown, agent: nil), "Inferred", "unknown renders like reasoning")
    }

    func testADerivedChipNeverClaimsASpeaker() {
        for agent in [nil, "Claude Code"] {
            let label = EvidenceLabel.speaker(kind: .derived, agent: agent)
            XCTAssertEqual(label, "Mentioned here")
            XCTAssertNotEqual(label, "You said")
        }
    }

    func testChipTextCarriesTheDayFromTheEpisodeIdAndAPageHasNone() {
        let span = EvidenceChipModel(source: .stored(Evidence(episode: "ep_2026-09-03_004", start: 1, end: 5,
                                                              kind: .assistant)))
        let meta = EvidenceDocMeta(title: "Index choice", harness: "claude-code", origin: nil)
        XCTAssertEqual(EvidenceLabel.chipText(span, meta: meta, locale: us, timeZone: utc),
                       "Claude Code replied · Sep 3")
        XCTAssertEqual(EvidenceLabel.chipText(span, meta: nil, locale: us, timeZone: utc),
                       "The agent replied · Sep 3", "no known harness — never a guess")
        let page = EvidenceChipModel(source: .stored(Evidence(episode: "media-example-com", start: 0, end: 4,
                                                              kind: .page)))
        XCTAssertEqual(EvidenceLabel.chipText(page, meta: nil, locale: us, timeZone: utc), "From the page")
    }

    /// Round-4 C3 (R-FA14, DR-57 §9) — an agent span whose turn carries a model reads as the agent line.
    func testAnAgentChipWithAModelSaysTheAgentLine() {
        let meta = EvidenceDocMeta(title: nil, harness: "claude-code", origin: nil)
        let withModel = EvidenceChipModel(source: .stored(Evidence(episode: "ep_2026-09-24_001", start: 0, end: 5,
                                                                   kind: .assistant, model: "claude-opus-5-5",
                                                                   effort: "high")))
        XCTAssertEqual(EvidenceLabel.chipText(withModel, meta: meta, locale: us, timeZone: utc),
                       "Claude Code · Opus 5.5 · high effort · Sep 24")
        XCTAssertEqual(EvidenceLabel.chipText(withModel, meta: nil, locale: us, timeZone: utc),
                       "The agent · Opus 5.5 · high effort · Sep 24")
        let noModel = EvidenceChipModel(source: .stored(Evidence(episode: "ep_2026-09-24_001", start: 0, end: 5,
                                                                 kind: .assistant)))
        XCTAssertEqual(EvidenceLabel.chipText(noModel, meta: meta, locale: us, timeZone: utc),
                       "Claude Code replied · Sep 24", "without a model the chip is byte-for-byte today's")
        let user = EvidenceChipModel(source: .stored(Evidence(episode: "ep_2026-09-24_001", start: 0, end: 5,
                                                              kind: .user, model: "claude-opus-5-5")))
        XCTAssertEqual(EvidenceLabel.chipText(user, meta: meta, locale: us, timeZone: utc), "You said · Sep 24",
                       "a model on the person's span is ignored — it is not who spoke")
        XCTAssertTrue(EvidenceLabel.accessibility(withModel, meta: meta, opens: false, locale: us, timeZone: utc)
            .hasPrefix("Claude Code · Opus 5.5 · high effort, September 24"))
    }

    /// G166 (spec 8.5) — Cicada never had the page an agent read and cannot check the quote, so the chip, its
    /// VoiceOver label and the Reader's turn say whose reading it is, never a bare "From the page".
    func testAQuoteAnAgentReportedFromAPageSaysWhoReadItAndNeverABareFromThePage() {
        let quote = EvidenceChipModel(source: .stored(Evidence(episode: "ep_2026-09-03_004", start: 1, end: 5,
                                                               kind: .page)))
        let meta = EvidenceDocMeta(title: "Read: A post", harness: "claude-code", origin: "mcp",
                                   source: EvidenceSpeaker.pageReadSource)
        XCTAssertEqual(EvidenceLabel.chipText(quote, meta: meta, locale: us, timeZone: utc),
                       "From the page, as Claude Code read it · Sep 3")
        XCTAssertEqual(EvidenceLabel.chipText(quote, meta: nil, locale: us, timeZone: utc), "From the page · Sep 3",
                       "no episode facts: an ordinary page quote keeps its label")
        XCTAssertEqual(EvidenceLabel.speaker(kind: .page, agent: nil, source: EvidenceSpeaker.pageReadSource),
                       "From the page, as an agent read it")
        XCTAssertTrue(EvidenceLabel.accessibility(quote, meta: meta, opens: false, locale: us, timeZone: utc)
            .hasPrefix("From the page, as Claude Code read it, September 3"))
        XCTAssertEqual(EvidenceLabel.speaker(kind: .assistant, agent: "Claude Code", source: "page-read"),
                       "Claude Code replied", "only a page quote is relabelled")
        let turn = EpisodeTurn(index: 2, start: 0, contentStart: 0, end: 1, role: "page",
                               marker: "attachment [blog.bob-example.org]")
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(turn, harness: "claude-code", origin: "mcp",
                                                   source: EvidenceSpeaker.pageReadSource),
                       "From the page, as Claude Code read it")
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(turn, harness: nil, origin: nil),
                       "Attached · blog.bob-example.org", "an upload's extracted text is still an attachment")
    }

    func testTheEpisodeSourceRidesBothProvenanceWires() throws {
        let text = try JSONDecoder().decode(EpisodeText.self, from: Data(
            #"{"episode":"ep_2026-09-03_004","source":"page-read","text":"x"}"#.utf8))
        XCTAssertTrue(text.isPageRead)
        let none = try JSONDecoder().decode(EpisodeText.self, from: Data(#"{"episode":"ep_1","text":"x"}"#.utf8))
        XCTAssertNil(none.source)
        let row = try JSONDecoder().decode(ProvenanceConversation.self, from: Data(
            #"{"episodeId":"ep_2026-09-03_004","source":"page-read","harness":"claude-code"}"#.utf8))
        let index = EvidenceDocIndex.from(EntityProvenance(entityId: "media-a", conversations: [row]))
        XCTAssertEqual(index.meta("ep_2026-09-03_004")?.source, "page-read")
    }

    func testTheAccessibilityLabelIsASentence() {
        let chip = EvidenceChipModel(source: .stored(Evidence(episode: "ep_2026-09-03_004", start: 1, end: 5,
                                                              kind: .user)))
        XCTAssertEqual(EvidenceLabel.accessibility(chip, meta: EvidenceDocMeta(title: "Index choice"), opens: true,
                                                   locale: us, timeZone: utc),
                       "You said, September 3, in Index choice. Opens the conversation.")
        XCTAssertEqual(EvidenceLabel.accessibility(chip, meta: nil, opens: false, locale: us, timeZone: utc),
                       "You said, September 3.")
    }

    // MARK: Which chips

    func testStoredEvidenceGivesOneChipPerEntryWithDuplicatesFolded() {
        let a = Evidence(episode: "ep_1", start: 1, end: 5, kind: .user, hash: "h")
        let b = Evidence(episode: "ep_2", start: -1, end: -1, kind: .reasoning, hash: "h")
        let chips = EvidenceChipModel.chips(evidence: [a, a, b], sourceEpisodes: ["ep_9"], subjectId: "alpha-project")
        XCTAssertEqual(chips.map(\.kind), [.user, .reasoning], "evidence wins over source_episodes")
    }

    func testALegacyClaimGetsDerivedChipsForItsEpisodesCappedAtThree() {
        let chips = EvidenceChipModel.chips(
            evidence: [],
            sourceEpisodes: ["ep_1", "ep_2", "ep_1", "media-example-com", "ep_3", "ep_4"],
            subjectId: "alpha-project")
        XCTAssertEqual(chips.map(\.episode), ["ep_1", "ep_2", "ep_3"])
        XCTAssertTrue(chips.allSatisfy { $0.kind == .derived })
        XCTAssertEqual(chips.first?.target(subjectId: "alpha-project", meta: nil)?.focus,
                       .mention(entityId: "alpha-project"))
        XCTAssertEqual(EvidenceChipModel.chips(evidence: [], sourceEpisodes: ["ep_1"], subjectId: ""), [],
                       "no subject means no name to search for")
    }

    func testReasoningWithoutADocumentHasNowhereToOpen() {
        let chip = EvidenceChipModel(source: .stored(Evidence(episode: "", start: -1, end: -1, kind: .reasoning)))
        XCTAssertNil(chip.target(subjectId: "alpha-project", meta: nil))
    }

    func testTheDocIndexCoversEveryEpisodeOfEveryConversation() {
        let provenance = EntityProvenance(entityId: "alpha-project", conversations: [
            ProvenanceConversation(conversationId: "ses_alpha", episodeId: "ep_2",
                                   episodeIds: ["ep_1", "ep_2"], title: "Index choice", harness: "claude-code"),
        ])
        let index = EvidenceDocIndex.from(provenance)
        XCTAssertEqual(index.meta("ep_1")?.title, "Index choice")
        XCTAssertEqual(index.meta("ep_2")?.harness, "claude-code")
        XCTAssertNil(index.meta("ep_3"))
        XCTAssertEqual(EvidenceDocIndex.from(nil), .empty)
    }

    // MARK: Author and trust pills

    func testTrustLabelsArePlainWords() {
        XCTAssertEqual(SourceTrust.userStated.label, "You told Cicada")
        XCTAssertEqual(SourceTrust.agentExtracted.label, "Cicada noticed")
        XCTAssertEqual(SourceTrust.agentReflected.label, "Cicada concluded")
        XCTAssertEqual(SourceTrust.external.label, "From a source")
        XCTAssertEqual(SourceTrust.unknown.label, "Not recorded")
    }

    func testAuthorKindFallsBackToTheIdWhenAnOlderBackendSendsNone() {
        XCTAssertEqual(ContributorIdentity.kind(author: "cicada"), "system")
        XCTAssertEqual(ContributorIdentity.kind(author: "user"), "user")
        XCTAssertEqual(ContributorIdentity.kind(author: ""), "unknown")
        XCTAssertEqual(ContributorIdentity.kind(author: "claude-sonnet-4-5"), "model")
        XCTAssertEqual(ContributorIdentity.kind(author: "claude-web", serverKind: "harness"), "harness",
                       "the server's bucket wins")
        XCTAssertEqual(AuthorPill("cicada").kind, "system")
    }

    func testAHarnessAuthorIsNamedAfterItsApp() {
        XCTAssertEqual(ContributorIdentity.displayName(author: "claude-code", kind: "harness"), "Claude Code")
    }

    // MARK: Lint (design §1.1)

    /// A delay in the provenance views is a named `CicadaTiming` constant,
    /// never a literal — the rule M1's motion lint states for durations,
    /// extended to the dwell and grace this track introduces (R-PU18).
    func testProvenanceViewsSpellNoLiteralDelay() throws {
        let literal = try NSRegularExpression(pattern: #"\.seconds\(\s*[0-9]"#)
        var scanned = 0
        for file in try ThemeTokenTests.swiftSources() where file.path.contains("/Views/Provenance/") {
            scanned += 1
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertNil(literal.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
                         "\(file.lastPathComponent) spells a literal delay — use CicadaTiming")
        }
        XCTAssertGreaterThan(scanned, 0, "the scope matched nothing — this lint would pass vacuously")
    }
}
