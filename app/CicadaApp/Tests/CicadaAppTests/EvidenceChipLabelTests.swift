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
