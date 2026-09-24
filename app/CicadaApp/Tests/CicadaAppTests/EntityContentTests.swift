import XCTest
@testable import CicadaApp

/// R-DG18 … R-DG22 — the Content tab's words, pure.
final class EntityContentTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func source(_ json: String) throws -> EntitySource {
        try JSONDecoder().decode(EntitySource.self, from: Data(json.utf8))
    }

    /// Decode tolerance: an older backend omits S1's three fields.
    func testASourceDecodesWithAndWithoutTheS1Fields() throws {
        let old = try source(#"{"ref":"https://example.com/team","kind":"url","addedBy":"user","addedAt":"2026-08-30"}"#)
        XCTAssertNil(old.access); XCTAssertNil(old.accepted); XCTAssertNil(old.onlyMe)
        let new = try source(#"{"ref":"~/notes/alpha.md","kind":"path","predicate":"uses","access":"local","addedBy":"claude-code","addedAt":"2026-09-21","accepted":true,"onlyMe":false}"#)
        XCTAssertEqual(new.access, "local"); XCTAssertEqual(new.accepted, true); XCTAssertEqual(new.onlyMe, false)
        // G61 S1 keys a source on (ref, predicate): one link can back two facts, so two rows, two identities.
        let uses = try source(#"{"ref":"https://example.com/team","kind":"url","predicate":"uses","addedBy":"user","addedAt":""}"#)
        let worksAt = try source(#"{"ref":"https://example.com/team","kind":"url","predicate":"works-at","addedBy":"user","addedAt":""}"#)
        XCTAssertNotEqual(uses.id, worksAt.id)
    }

    func testWhichFactASourceBacksUp() {
        XCTAssertEqual(FactSourceWords.forFact(nil), "For any fact")
        XCTAssertEqual(FactSourceWords.forFact(" "), "For any fact")
        XCTAssertEqual(FactSourceWords.forFact("works-at"), "For works at")
        XCTAssertEqual(FactSourceWords.forFact("uses"), "For uses")
    }

    /// R-DG18 — the stated access wins; unstated, only the kind speaks; an unstated url says nothing (the
    /// refused-host rule lives in `fact_sources.effective_access`).
    func testHowASourceCanBeRead() {
        XCTAssertEqual(FactSourceWords.readBy(access: "public", kind: "url"), "Public page")
        XCTAssertEqual(FactSourceWords.readBy(access: "signed_in", kind: "url"), "Needs sign-in")
        XCTAssertEqual(FactSourceWords.readBy(access: "local", kind: "note"), "A file on this Mac")
        XCTAssertEqual(FactSourceWords.readBy(access: "signed_in", kind: "app"), "Needs sign-in", "stated wins")
        XCTAssertEqual(FactSourceWords.readBy(access: nil, kind: "path"), "A file on this Mac")
        XCTAssertEqual(FactSourceWords.readBy(access: nil, kind: "repo"), "A file on this Mac")
        XCTAssertEqual(FactSourceWords.readBy(access: nil, kind: "app"), "An app")
        XCTAssertNil(FactSourceWords.readBy(access: nil, kind: "url"))
        XCTAssertNil(FactSourceWords.readBy(access: nil, kind: "note"))
        XCTAssertNil(FactSourceWords.readBy(access: "unknown", kind: "path"), "a stated unknown says nothing")
    }

    /// `fact_sources.voiced_hint`'s voices, with the app's mark (DR-52); a model id never reaches the screen (DR-54).
    func testWhoAddedASource() {
        XCTAssertEqual(FactSourceWords.addedBy("user").words, "Added by you")
        XCTAssertEqual(FactSourceWords.addedBy("").words, "Added by you")
        XCTAssertEqual(FactSourceWords.addedBy("cicada").words, "Found by Cicada")
        let app = FactSourceWords.addedBy("claude-code")
        XCTAssertEqual(app.words, "Added by Claude Code")
        XCTAssertEqual(app.origin, "claude-code")
        XCTAssertEqual(FactSourceWords.addedBy("gpt-5.4-mini").words, "Found by an agent")
        XCTAssertNil(FactSourceWords.addedBy("gpt-5.4-mini").origin)
        XCTAssertEqual(FactSourceWords.addedBy("agent").words, "Found by an agent")
    }

    func testTheWholeLine() throws {
        let s = try source(#"{"ref":"https://example.com/team","kind":"url","predicate":"works-at","addedBy":"gpt-5.4-mini","addedAt":"2026-08-30","accepted":true}"#)
        let line = FactSourceWords.line(s, locale: us)
        XCTAssertTrue(line.isLink)
        XCTAssertEqual(line.forFact, "For works at")
        XCTAssertNil(line.readBy)
        XCTAssertEqual(line.addedBy, "Found by an agent · Aug 30")
        XCTAssertEqual(line.note, "You chose to use this")
        XCTAssertTrue(line.help.contains("gpt-5.4-mini"), "the id is reachable in help only (DR-54)")
        XCTAssertEqual(FactSourceWords.note(accepted: true, onlyMe: true), "Only you know this", "only-me wins")
        XCTAssertNil(FactSourceWords.note(accepted: nil, onlyMe: nil))
    }

    /// R-DG19 — the first visible question about this page, in the Inbox's own order.
    func testTheOpenQuestionIsTheInboxsFirstForThisPage() throws {
        func item(_ id: String, _ entity: String) throws -> InboxItem {
            try JSONDecoder().decode(InboxItem.self, from: Data(#"{"id":"\#(id)","kind":"conflict","requiredInput":"choice","title":"\#(id)","priority":0.5,"createdDate":"2026-09-01","entityId":"\#(entity)"}"#.utf8))
        }
        let items = [try item("inbox-001", "bob-example"), try item("inbox-002", "alpha-project"), try item("inbox-003", "alpha-project")]
        XCTAssertEqual(EntityOpenQuestion.first(in: items, entityId: "alpha-project")?.id, "inbox-002")
        XCTAssertNil(EntityOpenQuestion.first(in: items, entityId: "nothing-here"))
    }

    /// R-DG21 — a repository in words, with neutral tags (DR-7).
    func testRepositoryWords() {
        XCTAssertEqual(RepoWords.status("ok"), "On this Mac")
        XCTAssertEqual(RepoWords.status("other_device"), "On another Mac")
        XCTAssertEqual(RepoWords.status("missing"), "Not found on this Mac")
        XCTAssertEqual(RepoWords.status("not_a_repo"), "Not a git folder")
        XCTAssertEqual(RepoWords.status("git_unavailable"), "git isn't installed")
        XCTAssertEqual(RepoWords.status("timeout"), "git didn't answer")
        XCTAssertEqual(RepoWords.status("something_new"), "Can't tell right now", "never a raw status id (DR-54)")
        XCTAssertEqual(RepoWords.tags(branch: "main", dirty: 2, ahead: 1, behind: 0), ["main", "2 changed files", "1 ahead"])
        XCTAssertEqual(RepoWords.tags(branch: nil, dirty: 1, ahead: nil, behind: 3), ["1 changed file", "3 behind"])
    }

    /// R-DG21 — Details' words.
    func testDetailsWords() {
        XCTAssertEqual(DetailsWords.fades(.evergreen), "Never")
        XCTAssertEqual(DetailsWords.fades(.durable), "Slowly")
        XCTAssertEqual(DetailsWords.fades(.active), "If it stops coming up")
        XCTAssertEqual(DetailsWords.fades(.volatile), "Quickly — it's expected to change")
        let now = ISO8601DateFormatter().date(from: "2026-09-22T12:00:00Z")!
        XCTAssertEqual(DetailsWords.lastMentioned("2026-08-25", now: now, locale: us), "Aug 25, 2026 · 4 weeks ago")
        XCTAssertEqual(DetailsWords.lastMentioned("", now: now, locale: us), "—")
        let pages = [Entity(id: "bob-example", name: "Bob Example", type: .person, status: .active, confidence: 0.9,
                            created: "", lastReferenced: "", decayRate: 0, sourceEpisodes: [], tags: [], related: [],
                            version: 1, markdownContent: "", history: [])]
        XCTAssertEqual(DetailsWords.relatedTarget("bob-example", in: pages), "bob-example")
        XCTAssertEqual(DetailsWords.relatedTarget("bob example", in: pages), "bob-example", "a name matches its page")
        XCTAssertNil(DetailsWords.relatedTarget("Nobody", in: pages))
    }

    /// R-DG22 — two chips on the row; everything else in help.
    func testABeliefsHelpAndAge() throws {
        let c = try JSONDecoder().decode(Claim.self, from: Data(#"{"id":"c1","text":"t","observer":"agent","context":"engineering","confidence":0.85,"authoredBy":"gpt-5.4-mini","validFrom":"2026-04-01","recordedAt":"2026-08-10T12:00:00Z"}"#.utf8))
        XCTAssertEqual(BeliefWords.help(c), "Cicada · Engineering · gpt-5.4-mini at 0.85")
        let now = ISO8601DateFormatter().date(from: "2026-09-22T12:00:00Z")!
        let age = try XCTUnwrap(BeliefWords.age(c, now: now, locale: us))
        XCTAssertEqual(age.text, "6mo")
        XCTAssertTrue(age.help.hasPrefix("True since Apr 1, 2026"))
        XCTAssertTrue(age.help.contains("noted Aug 10, 2026"))
    }
}
