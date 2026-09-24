import XCTest
@testable import CicadaApp

/// Design §1.4 — one Reader, one stack; and the in-memory cache behind it
/// (R-PB11: never a Store domain, ETags for this cache only).
@MainActor
final class ProvenanceRouterTests: XCTestCase {

    // MARK: Targets

    func testAnEvidenceSpanOpensOnItsWordsAndReasoningOpensUnderItsBanner() {
        let span = Evidence(episode: "ep_1", start: 3, end: 9, kind: .user, hash: "h")
        XCTAssertEqual(ReaderTarget.evidence(span, subjectId: "alpha-project")?.focus,
                       .span(start: 3, end: 9, hash: "h", derived: false))
        let inferred = Evidence(episode: "ep_1", start: -1, end: -1, kind: .reasoning, hash: "h")
        XCTAssertEqual(ReaderTarget.evidence(inferred, subjectId: nil)?.focus, .inferred)
        XCTAssertNil(ReaderTarget.evidence(Evidence(episode: "", start: -1, end: -1, kind: .reasoning),
                                           subjectId: nil), "reasoning with no document has nowhere to open")
    }

    func testABestQuoteOpensExactlyBoldOrUnderTheStaleBanner() {
        let asserted = ProvenanceSpan(episode: "ep_1", start: 5, end: 9, hash: "h", kind: .assistant, excerpt: "")
        XCTAssertEqual(ReaderTarget.best(asserted, subjectId: "a").focus,
                       .span(start: 5, end: 9, hash: "h", derived: false))
        let derived = ProvenanceSpan(episode: "ep_1", start: 5, end: 9, hash: "whole", kind: .derived,
                                     excerpt: "", derived: true)
        XCTAssertEqual(ReaderTarget.best(derived, subjectId: "a").focus,
                       .span(start: 5, end: 9, hash: nil, derived: true),
                       "a derived match's hash is the whole text's — never sent as a span hash")
        let stale = ProvenanceSpan(episode: "ep_1", start: nil, end: nil, kind: .user, excerpt: "", stale: true)
        XCTAssertEqual(ReaderTarget.best(stale, subjectId: "a").focus, .stale)
    }

    func testTheQueryIsTheOneTheServerTakes() {
        XCTAssertEqual(ReaderTarget(episode: "e", focus: .mention(entityId: "a")).query, .mention(entityId: "a"))
        XCTAssertEqual(ReaderTarget(episode: "e", focus: .inferred).query, ReaderFocusQuery.none)
        XCTAssertEqual(ReaderTarget(episode: "e", focus: .span(start: 1, end: 2, hash: nil, derived: true)).query,
                       .span(start: 1, end: 2, hash: nil))
    }

    // MARK: Router

    func testOpenPresentsPushesAndBumpsTheRevisionEvenForTheSameTarget() {
        let router = ProvenanceRouter()
        let a = ReaderTarget(episode: "ep_a")
        router.open(a)
        XCTAssertTrue(router.isPresented)
        XCTAssertEqual(router.stack, [a])
        let r1 = router.revision
        router.open(a)
        XCTAssertEqual(router.stack, [a], "the same target is not pushed twice")
        XCTAssertGreaterThan(router.revision, r1, "but a presenter still hears it")
    }

    func testBackPopsAndCloseKeepsTheStackUntilTheNextOpen() {
        let router = ProvenanceRouter()
        router.open(ReaderTarget(episode: "ep_a"))
        router.open(ReaderTarget(episode: "ep_b"))
        XCTAssertTrue(router.canGoBack)
        router.back()
        XCTAssertEqual(router.current?.episode, "ep_a")
        router.back()
        XCTAssertEqual(router.current?.episode, "ep_a", "never pops the last target")
        router.close()
        XCTAssertFalse(router.isPresented)
        XCTAssertEqual(router.current?.episode, "ep_a", "no empty Reader during the closing animation")
        router.open(ReaderTarget(episode: "ep_c"))
        XCTAssertEqual(router.stack.map(\.episode), ["ep_c"], "a fresh open from closed starts a fresh trail")
    }

    func testTheTrailIsCapped() {
        let router = ProvenanceRouter()
        for i in 0..<(ProvenanceRouter.maxDepth + 5) { router.open(ReaderTarget(episode: "ep_\(i)")) }
        XCTAssertEqual(router.stack.count, ProvenanceRouter.maxDepth)
        XCTAssertEqual(router.current?.episode, "ep_\(ProvenanceRouter.maxDepth + 4)")
    }

    // MARK: LRU

    func testTheLRUEvictsTheLeastRecentlyRead() {
        var lru = LRUCache<String, Int>(capacity: 2)
        lru.set("a", 1)
        lru.set("b", 2)
        XCTAssertEqual(lru.get("a"), 1)   // a is now the most recent
        lru.set("c", 3)
        XCTAssertNil(lru.get("b"))
        XCTAssertEqual(lru.get("a"), 1)
        XCTAssertEqual(lru.get("c"), 3)
        XCTAssertEqual(lru.count, 2)
    }

    // MARK: Cache

    func testASpanIsFetchedOnceAndServedFromMemory() async {
        let api = FakeProvenanceAPI()
        let cache = ProvenanceCache(api: api)
        let ev = Evidence(episode: "ep_1", start: 1, end: 2, kind: .user, hash: "h")
        _ = await cache.span(ev)
        _ = await cache.span(ev)
        XCTAssertEqual(api.spanCalls, 1)
    }

    func testForgettingSpansRefetchesThemButKeepsTheDocumentsValidator() async {
        // Final review — `/span` has no ETag but its stale/grown flags are
        // per request, so a bank change must drop the previews; documents
        // already revalidate and keep their last-known-good copy.
        let api = FakeProvenanceAPI()
        let cache = ProvenanceCache(api: api)
        let ev = Evidence(episode: "ep_1", start: 1, end: 2, kind: .user, hash: "h")
        _ = await cache.span(ev)
        _ = await cache.document(episode: "ep_1", focus: .none)
        cache.forgetSpans()
        _ = await cache.span(ev)
        XCTAssertEqual(api.spanCalls, 2, "a rewritten episode's preview is asked again, not served stale")
        _ = await cache.document(episode: "ep_1", focus: .none)
        XCTAssertEqual(api.lastTextETag, "\"v1\"", "documents are untouched — they revalidate by ETag")
    }

    func testADocumentRevalidatesWithItsETagAndKeepsTheValueOnA304() async {
        let api = FakeProvenanceAPI()
        let cache = ProvenanceCache(api: api)
        let first = await cache.document(episode: "ep_1", focus: .none)
        XCTAssertEqual(first.value?.title, "Index choice")
        api.textNotModified = true
        let second = await cache.document(episode: "ep_1", focus: .none)
        XCTAssertEqual(second.value?.title, "Index choice")
        XCTAssertEqual(api.lastTextETag, "\"v1\"", "the stored validator is sent back")
    }

    func testA404IsGoneEvenWithSomethingCachedAndAnyOtherFailureIsLastKnownGood() async {
        let api = FakeProvenanceAPI()
        let cache = ProvenanceCache(api: api)
        _ = await cache.document(episode: "ep_1", focus: .none)
        api.textError = APIError.serverUnreachable
        let offline = await cache.document(episode: "ep_1", focus: .none)
        XCTAssertEqual(offline.value?.title, "Index choice", "never blank on a transport failure")
        api.textError = APIError.httpError(404, "gone")
        let gone = await cache.document(episode: "ep_1", focus: .none)
        if case .gone = gone {} else { XCTFail("a 404 must read as gone, not as the cached copy") }
    }

    // MARK: A span the document no longer reaches (R-PU25)

    func testASpanPastTheEndOfARewrittenDocumentOpensTheWholeDocumentAsStale() async {
        let api = FakeProvenanceAPI()
        // `/text` 422s a pair past the end (`provenance.SpanOutOfRange`) once a
        // rewrite made the document shorter than the span.
        api.spanFocusError = APIError.httpError(422, "span [900, 951) is outside the document (length 8)")
        let cache = ProvenanceCache(api: api)
        let load = await cache.document(episode: "ep_1", focus: .span(start: 900, end: 951, hash: "h"))
        XCTAssertEqual(load.value?.title, "Index choice", "the words moved; the conversation did not vanish")
        XCTAssertEqual(load.value?.focus?.stale, true)
        XCTAssertNil(load.value?.focus?.range, "R-PB2 — stale never washes")
        guard let doc = load.value else { return XCTFail("the whole document opens") }
        let p = ReaderPresentation.resolve(
            target: ReaderTarget(episode: "ep_1", focus: .span(start: 900, end: 951, hash: "h", derived: false)),
            doc: doc, textCount: ScalarText(doc.text).count)
        XCTAssertEqual(p.banners, [.stale])
        XCTAssertEqual(p.landing, 7, "lands on the last words the document still has")
    }

    func testASpanPreviewPastTheEndReadsAsStaleNotAsAFailure() async {
        let api = FakeProvenanceAPI()
        api.spanError = APIError.httpError(422, "span [900, 951) is outside the document (length 8)")
        let cache = ProvenanceCache(api: api)
        let load = await cache.span(Evidence(episode: "ep_1", start: 900, end: 951, kind: .user, hash: "h"))
        XCTAssertEqual(load.value?.stale, true)
        XCTAssertEqual(load.value?.text, "", "no words to quote — the preview says they moved")
    }

    // MARK: A bank switch (R-PU26)

    func testResetForgetsEverythingSoAnotherBanksIdsAreNeverServed() async {
        let api = FakeProvenanceAPI()
        let cache = ProvenanceCache(api: api)
        let ev = Evidence(episode: "ep_1", start: 1, end: 2, kind: .user, hash: "h")
        _ = await cache.span(ev)
        _ = await cache.document(episode: "ep_1", focus: .none)
        cache.reset()
        _ = await cache.span(ev)
        XCTAssertEqual(api.spanCalls, 2, "episode ids restart every day in every bank — a cached span is refetched")
        api.textError = APIError.serverUnreachable
        let offline = await cache.document(episode: "ep_1", focus: .none)
        if case .failed = offline {} else { XCTFail("no last-known-good copy survives a bank switch") }
        XCTAssertNil(api.lastTextETag, "the old bank's validator is forgotten too")
    }

    /// R-DI9 — a swap onto the same conversation re-lands in place: no new Back step.
    func testRefocusReplacesTheTopForTheSameDocumentAndOpensAnyOther() {
        let router = ProvenanceRouter()
        router.open(ReaderTarget(episode: "ep_1", focus: .span(start: 1, end: 5, hash: nil, derived: true)))
        let before = router.revision
        let next = ReaderTarget(episode: "ep_1", focus: .span(start: 9, end: 14, hash: nil, derived: true))
        router.refocus(next)
        XCTAssertEqual(router.stack, [next])
        XCTAssertGreaterThan(router.revision, before, "the palette and the Belief Timeline still step aside")
        router.refocus(ReaderTarget(episode: "ep_2"))
        XCTAssertEqual(router.stack.map(\.episode), ["ep_1", "ep_2"], "another document is a real step")
        XCTAssertTrue(router.canGoBack)
    }
}

/// A scripted `ProvenanceAPI` for the cache and view-model tests.
final class FakeProvenanceAPI: ProvenanceAPI, @unchecked Sendable {
    var spanCalls = 0
    var spanError: Error?
    var textNotModified = false
    var textError: Error?
    /// Thrown only for a `.span` focus — a document that still exists but no
    /// longer reaches the asked-for offsets.
    var spanFocusError: Error?
    var lastTextETag: String?
    var provenance = EntityProvenance(entityId: "alpha-project")
    var citations = EpisodeCitations(episode: "ep_1")

    func fetchEpisodeSpan(episode: String, start: Int, end: Int, hash: String?) async throws -> EpisodeSpan {
        spanCalls += 1
        if let spanError { throw spanError }
        let json = #"{"episode": "\#(episode)", "text": "x", "start": \#(start), "end": \#(end)}"#
        return try JSONDecoder().decode(EpisodeSpan.self, from: Data(json.utf8))
    }

    func fetchEpisodeText(episode: String, focus: ReaderFocusQuery, etag: String?) async throws
        -> Conditional<EpisodeText> {
        lastTextETag = etag
        if case .span = focus, let spanFocusError { throw spanFocusError }
        if let textError { throw textError }
        if textNotModified { return Conditional(value: nil, etag: etag, notModified: true) }
        return Conditional(value: EpisodeText(episode: episode, text: "user: hi", title: "Index choice"),
                           etag: "\"v1\"", notModified: false)
    }

    func fetchEntityProvenance(entityId: String, etag: String?) async throws -> Conditional<EntityProvenance> {
        Conditional(value: provenance, etag: "\"p1\"", notModified: false)
    }

    func fetchEpisodeCitations(episode: String, etag: String?) async throws -> Conditional<EpisodeCitations> {
        Conditional(value: citations, etag: "\"c1\"", notModified: false)
    }
}
