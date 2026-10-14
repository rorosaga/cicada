import XCTest
@testable import CicadaApp

/// G198 (owner ruling 2026-10-14) — agents editing pages: the `page_edit` inbox kind, the "Who wrote it" payload
/// (`GET /entities/{id}/blame`) and the trusted-editors list (`GET/PUT /settings/editors`). Synthetic values only.
final class PageEditsTests: XCTestCase {

    // MARK: The inbox kind

    private static let pageEditJSON = #"""
    [{"id":"inbox-031","kind":"page_edit","requiredInput":"choice","status":"pending","priority":0.5,
      "entityId":"alpha-project","entityName":"Alpha Project","title":"Change Alpha Project?","createdDate":"2026-10-14",
      "question":"An agent suggests a change to Alpha Project: the person spelled the name for me",
      "options":[{"key":"apply","label":"Apply the change"},{"key":"dismiss","label":"Leave the page as it is"}],
      "allowOther":false,"allowDefer":true,
      "body":"Why: the person spelled the name for me\n\n- Replace “Alpah” with “Alpha” (every time it appears)",
      "cause":{"tier":"item","episodeId":"ep_2026-10-14_001","excerpt":"it is spelled Alpha","spanKind":"asserted"}}]
    """#

    func testPageEditDecodesAsItsOwnKind() throws {
        let items = try JSONDecoder().decode([InboxItem].self, from: Data(Self.pageEditJSON.utf8))
        XCTAssertEqual(items.map(\.kind), [.pageEdit])
        XCTAssertEqual(InboxKind.pageEdit.label, "Page edit")
        XCTAssertNotEqual(InboxKind.pageEdit.label, InboxKind.unknown.label)
        XCTAssertEqual(items[0].options.map(\.key), ["apply", "dismiss"])
        XCTAssertFalse(items[0].allowOther)
        XCTAssertTrue(items[0].allowDefer)
        XCTAssertEqual(FocusCardVariant.of(items[0]), .options)
        XCTAssertTrue(InboxTabs.order.contains(.pageEdit))
    }

    /// The preview IS the change: it shows even when the person's quoted words fill the quote hero.
    func testThePreviewShowsBesideACause() throws {
        let item = try JSONDecoder().decode([InboxItem].self, from: Data(Self.pageEditJSON.utf8))[0]
        XCTAssertTrue(item.hasCause)
        XCTAssertTrue(InboxBodyPreview.shows(item, hasQuote: true))
        var legacy = item
        legacy.kind = .clarification
        XCTAssertFalse(InboxBodyPreview.shows(legacy, hasQuote: true), "other kinds keep the old rule")
        legacy.body = ""
        legacy.kind = .pageEdit
        XCTAssertFalse(InboxBodyPreview.shows(legacy, hasQuote: false), "nothing to show")
    }

    // MARK: Who wrote it

    private static let blameJSON = #"""
    {"entityId":"alpha-project",
     "commits":[{"hash":"aaa1","date":"2026-10-14","subject":"Page edit 2026-10-14","author":"claude-code",
                 "authorKind":"harness","reason":"the person spelled the name for me","trigger":"mcp/claude-code"},
                {"hash":"bbb2","date":"2026-10-12","subject":"Page edit 2026-10-12","author":"cursor",
                 "authorKind":"harness","reason":"a stale sentence","acceptedBy":"user"},
                {"hash":"ccc3","date":"2026-10-01","subject":"Sleep cycle 2026-10-01","author":"model-example",
                 "authorKind":"model"}],
     "sections":[{"title":"(lead)","lineStart":5,"lineEnd":6,"contributors":[]},
                 {"title":"Summary","lineStart":7,"lineEnd":9,
                  "contributors":[{"author":"claude-code","authorKind":"harness","lines":1,"lastDate":"2026-10-14",
                                   "commits":["aaa1"]},
                                  {"author":"model-example","authorKind":"model","lines":2,"lastDate":"2026-10-01",
                                   "commits":["ccc3"]}]},
                 {"title":"Article › How it works","lineStart":10,"lineEnd":12,
                  "contributors":[{"author":"cursor","authorKind":"harness","lines":1,"lastDate":"2026-10-12",
                                   "commits":["bbb2"]},
                                  {"author":"uncommitted","authorKind":"uncommitted","lines":1}]}],
     "uncommittedLines":1}
    """#

    func testBlameDecodesAndNamesEachPart() throws {
        let blame = try JSONDecoder().decode(PageBlame.self, from: Data(Self.blameJSON.utf8))
        XCTAssertEqual(blame.entityId, "alpha-project")
        XCTAssertEqual(blame.commits.count, 3)
        XCTAssertEqual(blame.uncommittedLines, 1)
        // A part with no written line is left out.
        XCTAssertEqual(PageBlameWords.sections(blame).map(\.title), ["Summary", "Article › How it works"])
        XCTAssertTrue(WhoWroteItSection.shows(blame))
        XCTAssertFalse(WhoWroteItSection.shows(PageBlame(entityId: "x")))
        XCTAssertFalse(WhoWroteItSection.shows(nil))

        let summary = blame.sections[1]
        let edit = summary.contributors[0]
        XCTAssertEqual(PageBlameWords.reason(edit, in: blame), "“the person spelled the name for me”")
        XCTAssertNil(PageBlameWords.reason(summary.contributors[1], in: blame), "a Sleep commit gives no reason")
        let locale = Locale(identifier: "en_US")
        XCTAssertTrue(PageBlameWords.detail(edit, locale: locale).hasPrefix("1 line · "))
        XCTAssertTrue(PageBlameWords.detail(summary.contributors[1], locale: locale).hasPrefix("2 lines"))

        let article = blame.sections[2]
        XCTAssertEqual(PageBlameWords.reason(article.contributors[0], in: blame),
                       "“a stale sentence” · accepted by you")
        XCTAssertEqual(PageBlameWords.name(article.contributors[1]), Copy.PageEdits.notSavedYet)
        XCTAssertEqual(PageBlameWords.title(PageBlameSection(title: "(lead)")), Copy.PageEdits.lead)
    }

    func testBlameDecodingIsTolerant() throws {
        let blame = try JSONDecoder().decode(PageBlame.self, from: Data(#"{"entityId":"x"}"#.utf8))
        XCTAssertEqual(blame, PageBlame(entityId: "x"))
        let section = PageBlameSection(title: "Key Facts", contributors: (0..<5).map {
            PageBlameContributor(author: "a\($0)", lines: 1)
        })
        XCTAssertEqual(PageBlameWords.visible(section).count, PageBlameWords.visibleContributors)
        XCTAssertEqual(PageBlameWords.more(section), "and 2 more")
    }

    // MARK: The trusted editors

    private static let editorsJSON = #"""
    {"trusted":[{"harness":"claude-code","label":"Claude Code","since":"2026-10-14"}],
     "candidates":[{"harness":"claude-code","label":"Claude Code"},{"harness":"cursor","label":"Cursor"}]}
    """#

    func testEditorsDecodeAndSayWhoAsksFirst() throws {
        let editors = try JSONDecoder().decode(PageEditorsResponse.self, from: Data(Self.editorsJSON.utf8))
        XCTAssertTrue(editors.isTrusted("claude-code"))
        XCTAssertFalse(editors.isTrusted("cursor"))
        XCTAssertEqual(editors.rows.map(\.harness), ["claude-code", "cursor"])
        XCTAssertEqual(PageEditorsWords.detail("cursor", in: editors), Copy.PageEdits.asksFirst)
        XCTAssertTrue(PageEditorsWords.detail("claude-code", in: editors, locale: Locale(identifier: "en_US"))
            .hasPrefix("Allowed since "))
        // A trusted agent the backend no longer lists stays switchable.
        let orphan = PageEditorsResponse(trusted: [PageEditor(harness: "gemini-cli", label: "Gemini CLI")],
                                         candidates: editors.candidates)
        XCTAssertEqual(orphan.rows.map(\.harness), ["claude-code", "cursor", "gemini-cli"])
        let empty = try JSONDecoder().decode(PageEditorsResponse.self, from: Data("{}".utf8))
        XCTAssertEqual(empty, PageEditorsResponse())
    }

    @MainActor
    func testATurnedOnSwitchShowsAtOnceAndComesBackOnRefusal() async throws {
        let start = try JSONDecoder().decode(PageEditorsResponse.self, from: Data(Self.editorsJSON.utf8))
        let refusal = Data(#"{"detail":"cursor can't be allowed right now. Nothing was changed."}"#.utf8)
        var asked: [(String, Bool)] = []
        let model = PageEditorsModel(deps: .init(
            load: { start },
            set: { harness, on in
                asked.append((harness, on))
                throw APIError.httpError(400, String(decoding: refusal, as: UTF8.self))
            }))
        await model.load()
        XCTAssertEqual(model.editors, start)
        await model.set("cursor", on: true, today: "2026-10-14")
        XCTAssertEqual(asked.map(\.0), ["cursor"])
        XCTAssertEqual(model.editors, start, "a refusal puts the switch back")
        XCTAssertNotNil(model.note)
        XCTAssertTrue(model.busy.isEmpty)
    }

    @MainActor
    func testAnAcceptedSwitchKeepsTheServersAnswer() async throws {
        let start = try JSONDecoder().decode(PageEditorsResponse.self, from: Data(Self.editorsJSON.utf8))
        let after = start.setting("cursor", on: true, today: "2026-10-14")
        XCTAssertTrue(after.isTrusted("cursor"))
        XCTAssertFalse(after.setting("cursor", on: false, today: "2026-10-14").isTrusted("cursor"))
        let model = PageEditorsModel(deps: .init(load: { start }, set: { _, _ in after }))
        await model.load()
        await model.set("cursor", on: true)
        XCTAssertEqual(model.editors, after)
        XCTAssertNil(model.note)
    }
}
