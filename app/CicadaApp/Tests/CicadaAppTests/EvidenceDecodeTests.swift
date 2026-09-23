import XCTest
@testable import CicadaApp

/// G118 slice 2 (design §4.1, §4.10) — the provenance payloads decode from
/// the server's exact camelCase shape, and every one of them degrades rather
/// than throws: an older backend, a legacy claim or a kind this build has
/// never heard of must never blank a view (R10).
final class EvidenceDecodeTests: XCTestCase {

    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(json.utf8))
    }

    // MARK: Claim

    func testAClaimCarriesItsEvidenceAndAuthorFields() throws {
        let claim = try decode(Claim.self, """
        {"id": "clm_2026-09-03_001", "text": "alpha-project uses sqlite-vec",
         "authoredBy": "claude-sonnet-4-5", "origin": "sleep",
         "evidence": [{"episode": "ep_2026-09-03_004", "start": 930, "end": 951,
                       "kind": "assistant", "hash": "a1b2c3d4e5f6"}],
         "sessionIds": ["ses_alpha"], "recordedAt": "2026-09-03T10:00:00+00:00",
         "authorKind": "model", "authorProvider": "anthropic"}
        """)
        XCTAssertEqual(claim.evidence, [Evidence(episode: "ep_2026-09-03_004", start: 930, end: 951,
                                                 kind: .assistant, hash: "a1b2c3d4e5f6")])
        XCTAssertEqual(claim.sessionIds, ["ses_alpha"])
        XCTAssertEqual(claim.origin, "sleep")
        XCTAssertEqual(claim.recordedAt, "2026-09-03T10:00:00+00:00")
        XCTAssertEqual(claim.authorKind, "model")
        XCTAssertEqual(claim.authorProvider, "anthropic")
    }

    func testAClaimWithoutEvidenceDecodesToAnEmptyList() throws {
        let claim = try decode(Claim.self, #"{"id": "clm_legacy", "text": "t", "sourceEpisodes": ["ep_2026-01-01_001"]}"#)
        XCTAssertEqual(claim.evidence, [])
        XCTAssertEqual(claim.sessionIds, [])
        XCTAssertNil(claim.origin)
        XCTAssertNil(claim.authorKind)
        XCTAssertNil(claim.authorProvider)
        XCTAssertEqual(claim.sourceEpisodes, ["ep_2026-01-01_001"])
    }

    // MARK: Evidence

    func testAnUnknownKindDecodesToUnknownAndIsNeverASpan() throws {
        let ev = try decode(Evidence.self, #"{"episode": "ep_2026-09-03_004", "start": 1, "end": 9, "kind": "hologram"}"#)
        XCTAssertEqual(ev.kind, .unknown)
        XCTAssertFalse(ev.isSpan, "an unknown kind renders like reasoning (§4.10)")
    }

    func testReasoningIsNeverASpanEvenWithOffsets() {
        XCTAssertFalse(Evidence(episode: "ep_2026-09-03_004", start: -1, end: -1, kind: .reasoning).isSpan)
        XCTAssertFalse(Evidence(episode: "ep_2026-09-03_004", start: 3, end: 9, kind: .reasoning).isSpan)
        XCTAssertFalse(Evidence(episode: "", start: 3, end: 9, kind: .user).isSpan, "no document, no span")
        XCTAssertFalse(Evidence(episode: "ep_x", start: 9, end: 9, kind: .user).isSpan, "an empty range is no span")
        XCTAssertTrue(Evidence(episode: "ep_x", start: 3, end: 9, kind: .user).isSpan)
        XCTAssertTrue(Evidence(episode: "media-example-com", start: 0, end: 4, kind: .page).isSpan)
    }

    func testEvidenceMissingEveryFieldIsReasoningNotACrash() throws {
        let ev = try decode(Evidence.self, "{}")
        XCTAssertEqual(ev.kind, .reasoning, "the server's own default kind")
        XCTAssertEqual(ev.start, -1)
        XCTAssertFalse(ev.isSpan)
    }

    func testDerivedIsAReadKindThatNeverClaimsOffsets() {
        XCTAssertFalse(EvidenceKind.derived.hasOffsets)
        XCTAssertEqual(EvidenceKind(wire: "DERIVED"), .derived)
        XCTAssertEqual(EvidenceKind(wire: nil), .unknown)
    }

    // MARK: /span

    func testASliceOneSpanPayloadHasNoGrownAndReadsAsNotGrown() throws {
        let span = try decode(EpisodeSpan.self, """
        {"episode": "ep_2026-09-03_004", "text": "sqlite-vec", "before": "moved to ", "after": " so",
         "start": 9, "end": 19, "length": 22, "stale": false, "kind": "assistant"}
        """)
        XCTAssertFalse(span.grown)
        XCTAssertEqual(span.kind, .assistant)
        XCTAssertEqual(span.before + span.text + span.after, "moved to sqlite-vec so")
    }

    // MARK: /text

    func testEpisodeTextDecodesTurnsFocusAndHeader() throws {
        let doc = try decode(EpisodeText.self, """
        {"episode": "ep_2026-09-03_004", "kind": "episode", "text": "user: hi\\nassistant: hello",
         "length": 26, "hash": "a1b2c3d4e5f6", "truncated": false, "title": "Index choice",
         "timestamp": "2026-09-03T10:00:00+00:00", "harness": "claude-code", "origin": "claude-code",
         "conversationId": "ses_alpha", "captureKind": "transcript",
         "turns": [{"index": 1, "start": 0, "contentStart": 6, "end": 8, "role": "user", "marker": "user"},
                   {"index": 2, "start": 9, "contentStart": 20, "end": 26, "role": "assistant",
                    "marker": "assistant", "ts": "2026-09-03T10:01:00+00:00", "speaker": "assistant"}],
         "focus": {"start": 20, "end": 26, "kind": "assistant", "derived": false, "stale": false, "grown": true}}
        """)
        XCTAssertEqual(doc.turns.count, 2)
        XCTAssertEqual(doc.turns[1].contentStart, 20)
        XCTAssertEqual(doc.turns[1].ts, "2026-09-03T10:01:00+00:00")
        XCTAssertNil(doc.turns[0].ts, "a time is never inferred")
        XCTAssertEqual(doc.focus?.range, 20..<26)
        XCTAssertEqual(doc.focus?.grown, true)
        XCTAssertEqual(doc.captureKind, "transcript", "the Stop hook's own stamp (`transcript_capture.CAPTURE_KIND`)")
        XCTAssertFalse(doc.isPage)
    }

    func testAStaleFocusHasNoRangeToWash() throws {
        let focus = try decode(EpisodeFocus.self, #"{"start": null, "end": null, "kind": "user", "stale": true}"#)
        XCTAssertNil(focus.range, "R-PB2 — stale never highlights")
        XCTAssertTrue(focus.stale)
    }

    // MARK: /provenance

    func testEntityProvenanceDecodesAndDefaultsEverythingOptional() throws {
        let full = try decode(EntityProvenance.self, """
        {"entityId": "alpha-project", "entityName": "Alpha project", "entityType": "project",
         "contributors": [{"author": "claude-sonnet-4-5", "kind": "model", "provider": "anthropic",
                           "claims": 12, "commits": 3},
                          {"author": "user", "kind": "user", "claims": 4, "commits": 2}],
         "conversations": [{"conversationId": "ses_alpha", "episodeId": "ep_2026-09-03_004",
                            "episodeIds": ["ep_2026-09-03_004"], "title": "Index choice",
                            "harness": "claude-code", "timestamp": "2026-09-03T10:00:00+00:00",
                            "claimCount": 5, "available": true,
                            "best": {"episode": "ep_2026-09-03_004", "start": 930, "end": 951,
                                     "hash": "a1b2c3d4e5f6", "kind": "derived", "excerpt": "…sqlite-vec…",
                                     "excerptStart": 900, "mentionOffsets": [[30, 40]],
                                     "stale": false, "grown": false, "derived": true}}],
         "pages": [{"entityId": "media-example-com", "name": "example.com", "claimCount": 1}],
         "inferredCount": 2, "totals": {"claims": 18, "withSpan": 9, "legacy": 7, "conversations": 3},
         "commitsTruncated": false}
        """)
        XCTAssertEqual(full.contributors.map(\.author), ["claude-sonnet-4-5", "user"])
        XCTAssertNil(full.contributors[1].provider)
        XCTAssertEqual(full.conversations.first?.best?.displayKind, .derived,
                       "a derived match is never labelled with a speaker (§4.9)")
        XCTAssertEqual(full.totals.withSpan, 9)
        XCTAssertEqual(full.pages.first?.name, "example.com")

        let bare = try decode(EntityProvenance.self, #"{"entityId": "alpha-project"}"#)
        XCTAssertEqual(bare.contributors, [])
        XCTAssertEqual(bare.totals, ProvenanceTotals())
        XCTAssertFalse(bare.commitsTruncated)
    }

    func testAStaleBestQuoteTravelsWithoutOffsets() throws {
        let best = try decode(ProvenanceSpan.self, """
        {"episode": "ep_2026-09-03_004", "start": null, "end": null, "kind": "user",
         "excerpt": "the words may have moved", "stale": true}
        """)
        XCTAssertNil(best.start)
        XCTAssertTrue(best.stale)
        XCTAssertEqual(best.displayKind, .user)
    }

    // MARK: /citations

    func testCitationsDecodeSpanDerivedAndReasoningRows() throws {
        let payload = try decode(EpisodeCitations.self, """
        {"episode": "ep_2026-09-03_004", "partial": true,
         "citations": [
           {"claimId": "clm_1", "subjectId": "alpha-project", "subjectName": "Alpha project",
            "subjectType": "project", "text": "uses sqlite-vec", "current": true, "authoredBy": "claude-sonnet-4-5",
            "observer": "agent", "evidence": {"episode": "ep_2026-09-03_004", "start": 930, "end": 951,
            "kind": "assistant", "hash": "a1b2c3d4e5f6"}, "kind": "assistant", "start": 930, "end": 951},
           {"claimId": "clm_2", "subjectId": "bob-example", "kind": "derived", "derived": true,
            "start": 12, "end": 23},
           {"claimId": "clm_3", "subjectId": "bob-example", "kind": "reasoning",
            "evidence": {"episode": "ep_2026-09-03_004", "start": -1, "end": -1, "kind": "reasoning"}}],
         "entities": [{"entityId": "alpha-project", "name": "Alpha project", "type": "project"}]}
        """)
        XCTAssertTrue(payload.partial)
        XCTAssertEqual(payload.citations.map(\.displayKind), [.assistant, .derived, .reasoning])
        XCTAssertEqual(payload.citations[0].range, 930..<951)
        XCTAssertNil(payload.citations[2].range)
        XCTAssertEqual(Set(payload.citations.map(\.id)).count, 3, "every row keeps its own identity")
    }

    // MARK: History + Ask

    func testHistoryEntryAndAskCitationCarryTheNewFieldsAndToleratesTheirAbsence() throws {
        let entry = try decode(EntityHistoryEntry.self, """
        {"date": "2026-09-03", "changeType": "updated", "description": "d", "author": "cicada",
         "authorKind": "system", "authorProvider": null}
        """)
        XCTAssertEqual(entry.authorKind, "system")
        XCTAssertNil(entry.authorProvider)
        let old = try decode(EntityHistoryEntry.self, #"{"date": "2026-01-01", "changeType": "created", "description": "d"}"#)
        XCTAssertNil(old.authorKind)

        let cited = try decode(AskCitation.self, """
        {"entityId": "alpha-project", "entityName": "Alpha project", "filePath": "", "snippet": "s",
         "claimId": "clm_1", "evidence": [{"episode": "ep_2026-09-03_004", "start": 1, "end": 5,
         "kind": "user", "hash": "h"}]}
        """)
        XCTAssertEqual(cited.claimId, "clm_1")
        XCTAssertEqual(cited.evidence.first?.kind, .user)
        let plain = try decode(AskCitation.self, #"{"entityId": "alpha-project"}"#)
        XCTAssertNil(plain.claimId)
        XCTAssertEqual(plain.evidence, [])
    }
}
