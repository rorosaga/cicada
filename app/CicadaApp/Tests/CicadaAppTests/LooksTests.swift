import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Design taste (2026-10-14) — looks: their wire, their cache, the refresh rule, the shrink before a screenshot leaves
/// the Mac, and — since the Looks page went to the pages of the things looks show (owner 2026-10-20) — a page's looks,
/// Clusters' "has looks" filter and offscreen renders of the card's section and an opened look in both appearances
/// (`LOOKS_RENDER_DIR`). Synthetic only: made-up pages drawn here, example.com links.
@MainActor
final class LooksTests: XCTestCase {

    // MARK: The wire

    static let boardJSON = """
    {"refs": [{"id": "2026-10-13-dashboard-example-com", "title": "Quiet dark dashboard",
               "url": "https://dashboard.example.com/overview", "site": "dashboard.example.com",
               "captured": "2026-10-13T16:30:00Z", "day": "2026-10-13", "addedBy": "user", "addedByKind": "user",
               "via": "demo", "image": {"url": "/design/2026-10-13-dashboard-example-com/image?v=abc123def456",
               "width": 960, "height": 600, "bytes": 4619},
               "palette": [{"hex": "#171920", "share": 0.81}, {"hex": "#e2e6f0", "share": 0.11}],
               "look": ["dark", "muted", "blue"], "fonts": ["Inter"], "tags": [], "notePreview": "Calm panels."},
              {"id": "2026-10-10-look"}],
     "vision": {"supported": true, "installed": false, "downloadBytes": 309277919, "installing": false,
                "step": "", "error": ""},
     "indexedImages": 0}
    """

    func testTheBoardDecodesAndFillsWhatAnOlderServerLeftOut() throws {
        let board = try JSONDecoder().decode(DesignBoard.self, from: Data(Self.boardJSON.utf8))
        XCTAssertEqual(board.refs.count, 2)
        XCTAssertEqual(board.refs[0].palette.first, DesignColour(hex: "#171920", share: 0.81))
        XCTAssertEqual(board.refs[0].image?.aspect ?? 0, 1.6, accuracy: 0.001)
        XCTAssertEqual(board.refs[1].displayName, Copy.Looks.untitled, "no title and no site: the plain name")
        XCTAssertTrue(board.vision.supported && !board.vision.installed)
        let full = try JSONDecoder().decode(DesignRef.self, from: Data("""
        {"id": "x-1", "note": "Liked it", "snippets": [{"lang": "css", "code": "a{}"}], "path": "design/x-1.md"}
        """.utf8))
        XCTAssertEqual(full.summary.id, "x-1")
        XCTAssertEqual(full.snippets, [DesignSnippet(lang: "css", code: "a{}")])
    }

    func testAScreenshotPathIsCicadasOwnApiNeverAnotherHost() {
        XCTAssertEqual(PictureURL.parse("/design/a-1/image?v=abc"), .api(path: "/design/a-1/image?v=abc"))
        XCTAssertNil(PictureURL.parse("/design/../entities/x"))
        XCTAssertTrue(StoredPreviewPath.loads("/design/a-1/image?v=abc"))
        XCTAssertFalse(StoredPreviewPath.loads("https://dashboard.example.com/shot.png"))
    }

    func testOnlyADesignOrBankMoveAsksTheBoardAgain() {
        let a = VersionVector(version: "1", components: ["design": "x", "bank": "b", "entities": "e"])
        let entities = VersionVector(version: "2", components: ["design": "x", "bank": "b", "entities": "f"])
        let design = VersionVector(version: "3", components: ["design": "y", "bank": "b", "entities": "f"])
        XCTAssertFalse(LooksRefresh.shouldRevalidate(old: a, new: entities))
        XCTAssertTrue(LooksRefresh.shouldRevalidate(old: entities, new: design))
        XCTAssertTrue(LooksRefresh.shouldRevalidate(old: nil, new: a))
    }

    func testTheWordsAreSentencesWithoutAProviderName() {
        XCTAssertEqual(Copy.Looks.eyebrowCount(1), "1 saved")
        XCTAssertEqual(Copy.Looks.share(0.814), "81 %")
        XCTAssertEqual(Copy.Looks.savedLine(day: "2026-10-13", by: "you", via: Copy.Looks.via("paste")),
                       "2026-10-13 · by you · pasted")
        XCTAssertTrue(Copy.Looks.pictureDownload(309_277_919).contains("309 MB"))
        for text in [Copy.Looks.pictureOff, Copy.Looks.pictureDownload(1), Copy.Looks.pictureUnsupported,
                     Copy.Looks.emptyMessage] {
            for name in ["Gemma", "Google", "Core ML", "Hugging", "OpenAI", "Claude"] {
                XCTAssertFalse(text.contains(name), "provider-neutral: \(text)")
            }
        }
    }

    // MARK: The cache

    actor FakeAPI: DesignAPI {
        var board: DesignBoard
        var etag = "\"e1\""
        var saved: [DesignUpload] = []
        var deleted: [String] = []
        var searches: [(String?, Bool)] = []
        var refuseSave: String?

        init(board: DesignBoard) { self.board = board }

        func fetchDesignBoard(etag: String?) async throws -> Conditional<DesignBoard> {
            if etag == self.etag { return Conditional(value: nil, etag: etag, notModified: true) }
            return Conditional(value: board, etag: self.etag, notModified: false)
        }
        func fetchDesignRef(id: String, etag: String?) async throws -> Conditional<DesignRef> {
            guard let s = board.refs.first(where: { $0.id == id }) else { throw APIError.httpError(404, "{}") }
            return Conditional(value: DesignRef(summary: s, note: "note of \(id)"), etag: "\"r\"", notModified: false)
        }
        func saveDesignRef(_ upload: DesignUpload) async throws -> DesignRef {
            if let refuseSave { throw APIError.httpError(409, "{\"detail\": \"\(refuseSave)\"}") }
            saved.append(upload)
            let s = DesignRefSummary(id: "2026-10-14-new", title: upload.title ?? "")
            board.refs.insert(s, at: 0)
            etag = "\"e2\""
            return DesignRef(summary: s, note: upload.note ?? "")
        }
        func deleteDesignRef(id: String) async throws {
            deleted.append(id)
            board.refs.removeAll { $0.id == id }
            etag = "\"e3\""
        }
        func searchDesign(query: String?, image: Data?, ext: String?) async throws -> DesignSearchResult {
            searches.append((query, image != nil))
            let ids = board.refs.map(\.id).reversed()
            return DesignSearchResult(results: ids.map { DesignHit(id: $0, score: 1, legs: ["words"]) }, mode: "words",
                                      missing: image != nil ? ["image_model"] : [])
        }
        func installImageModel() async throws {}
        func setRefusal(_ text: String?) { refuseSave = text }
        var attached: [(String, String?)] = []
        func attachDesignRef(id: String, entity: String?) async throws -> DesignRef {
            guard let i = board.refs.firstIndex(where: { $0.id == id }) else { throw APIError.httpError(404, "{}") }
            if entity == "missing-page" {
                throw APIError.httpError(422, "{\"detail\": \"That page isn't in memory, so the look can't go on it.\"}")
            }
            attached.append((id, entity))
            board.refs[i].entity = entity
            etag = "\"e4-\(attached.count)\""
            return DesignRef(summary: board.refs[i], note: "")
        }
        var edits: [(String, String, String, String)] = []
        func editDesignRef(id: String, title: String, url: String, note: String) async throws -> DesignRef {
            guard let i = board.refs.firstIndex(where: { $0.id == id }) else { throw APIError.httpError(404, "{}") }
            edits.append((id, title, url, note))
            board.refs[i].title = title
            board.refs[i].noteBy = "user"
            etag = "\"e5-\(edits.count)\""
            return DesignRef(summary: board.refs[i], note: note)
        }
        func similarDesign(id: String) async throws -> DesignSearchResult {
            DesignSearchResult(results: board.refs.map { DesignHit(id: $0.id, score: 1, legs: ["picture"]) },
                               mode: "picture", missing: [])
        }
    }

    private func board() throws -> DesignBoard {
        try JSONDecoder().decode(DesignBoard.self, from: Data(Self.boardJSON.utf8))
    }

    func testTheCacheIsNeverBlankAndASearchReRanksWhatTheBoardHolds() async throws {
        let api = FakeAPI(board: try board())
        let cache = LooksCache(api: api)
        await cache.refresh()
        XCTAssertEqual(cache.visible.map(\.id), ["2026-10-13-dashboard-example-com", "2026-10-10-look"])
        await cache.refresh()   // a 304 keeps the board
        XCTAssertEqual(cache.visible.count, 2)
        await cache.search(query: "dark")
        XCTAssertEqual(cache.visible.map(\.id), ["2026-10-10-look", "2026-10-13-dashboard-example-com"])
        XCTAssertNil(cache.searchNote)
        await cache.search(query: "", image: Data([1, 2, 3]), ext: "png")
        XCTAssertEqual(cache.searchNote, Copy.Looks.pictureMissing, "a picture search without the model says so")
        cache.clearSearch()
        XCTAssertNil(cache.ranking)
        await cache.refreshRef("2026-10-10-look")
        XCTAssertEqual(cache.refs["2026-10-10-look"]?.note, "note of 2026-10-10-look")
    }

    func testASaveLandsOnTheBoardAndARefusalIsTheServersOwnSentence() async throws {
        let api = FakeAPI(board: try board())
        let cache = LooksCache(api: api)
        await cache.refresh()
        let upload = DesignUpload(image: Data([0x89]), ext: "png", url: "https://dashboard.example.com", title: "New",
                                  note: "Liked", via: "paste")
        let ref = await cache.save(upload)
        XCTAssertEqual(ref?.summary.id, "2026-10-14-new")
        XCTAssertEqual(cache.visible.first?.id, "2026-10-14-new")
        await api.setRefusal("Cicada has its demo memory open.")
        let refused = await cache.save(upload)
        XCTAssertNil(refused)
        XCTAssertEqual(cache.writeError, "Cicada has its demo memory open.")
        await cache.remove("2026-10-14-new")
        XCTAssertFalse(cache.visible.contains { $0.id == "2026-10-14-new" })
        cache.reset()
        XCTAssertTrue(cache.visible.isEmpty && cache.phase == .idle, "a bank switch empties it")
    }

    // MARK: Looks on pages (owner 2026-10-20)

    func testAPagesLooksTheOnesOnNoPageAndThePagesThatHaveThem() async throws {
        var board = try board()
        board.refs[0].entity = "alpha-project"
        let api = FakeAPI(board: board)
        let cache = LooksCache(api: api)
        await cache.refresh()
        XCTAssertEqual(cache.looks(on: "alpha-project").map(\.id), ["2026-10-13-dashboard-example-com"])
        XCTAssertEqual(cache.unplaced.map(\.id), ["2026-10-10-look"])
        XCTAssertEqual(cache.pagesWithLooks, ["alpha-project"])
        // Putting the unplaced look on the page reads the board again, so every surface shows the move.
        let moved = await cache.attach("2026-10-10-look", to: "alpha-project")
        XCTAssertTrue(moved)
        XCTAssertEqual(cache.looks(on: "alpha-project").count, 2)
        XCTAssertTrue(cache.unplaced.isEmpty)
        let refused = await cache.attach("2026-10-10-look", to: "missing-page")
        XCTAssertFalse(refused)
        XCTAssertEqual(cache.writeError, "That page isn't in memory, so the look can't go on it.",
                       "the server's own sentence")
        await cache.attach("2026-10-10-look", to: nil)
        XCTAssertEqual(cache.unplaced.map(\.id), ["2026-10-10-look"], "taken off a page, kept")
        await cache.loadSimilar("2026-10-10-look")
        XCTAssertEqual(cache.similar["2026-10-10-look"], ["2026-10-13-dashboard-example-com"], "never itself")
        cache.reset()
        XCTAssertTrue(cache.pagesWithLooks.isEmpty && cache.similar.isEmpty, "a bank switch empties it")
    }

    /// Review of #384 — the person's own words on a look, from its sheet: what they liked becomes theirs.
    func testThePersonsOwnWordsOnALook() async throws {
        let api = FakeAPI(board: try board())
        let cache = LooksCache(api: api)
        await cache.refresh()
        let saved = await cache.edit("2026-10-10-look", title: "Calm panels", url: "", note: "Mine.")
        XCTAssertTrue(saved)
        XCTAssertEqual(cache.refs["2026-10-10-look"]?.note, "Mine.")
        XCTAssertEqual(cache.board?.refs.first { $0.id == "2026-10-10-look" }?.title, "Calm panels",
                       "the board is read again, so every surface shows the new name")
        let refused = await cache.edit("2026-01-01-none", title: "", url: "", note: "")
        XCTAssertFalse(refused)
    }

    func testAPastedLinkMustBeAWebsite() {
        XCTAssertEqual(PageLooks.link("  https://dashboard.example.com/overview \n"), "https://dashboard.example.com/overview")
        XCTAssertEqual(PageLooks.link("http://studio.example.com"), "http://studio.example.com")
        XCTAssertNil(PageLooks.link("dashboard.example.com"), "no scheme: said, never guessed")
        XCTAssertNil(PageLooks.link("file:///Users/x/shot.png"))
        XCTAssertNil(PageLooks.link("https://"))
        XCTAssertNil(PageLooks.link(""))
    }

    func testASimilarLookSaysThePageItIsOn() {
        let on = DesignRefSummary(id: "a", entity: "alpha-project")
        XCTAssertEqual(PageLooks.place(on, names: ["alpha-project": "Alpha Project"]), "On Alpha Project")
        XCTAssertEqual(PageLooks.place(on, names: [:]), "On alpha-project")
        XCTAssertEqual(PageLooks.place(DesignRefSummary(id: "b"), names: [:]), Copy.Looks.notOnAPage)
    }

    func testAPictureDroppedOnAPageIsPostedWithThePage() async throws {
        let api = FakeAPI(board: try board())
        let cache = LooksCache(api: api)
        await cache.refresh()
        let said = await PageLooks.drop(Self.page(width: 400, height: 250, background: .white, accent: .black),
                                        on: "alpha-project", cache: cache)
        XCTAssertEqual(said, Copy.Looks.dropped)
        let saved = await api.saved
        XCTAssertEqual(saved.first?.entity, "alpha-project")
        XCTAssertEqual(saved.first?.via, "drop")
        await api.setRefusal("Cicada has its demo memory open.")
        let refused = await PageLooks.drop(Self.page(width: 300, height: 200, background: .black, accent: .white),
                                           on: "alpha-project", cache: cache)
        XCTAssertEqual(refused, "Cicada has its demo memory open.")
    }

    func testTheArticleLeavesTheLooksSectionToTheCard() {
        let markdown = """
        ## Summary
        Alpha Project is a synthetic page.

        ## Key Facts
        - It has panels.

        ## Looks
        - [Quiet dark dashboard](../design/2026-10-13-dashboard-example-com.md) · dashboard.example.com · 2026-10-13
          ![Quiet dark dashboard](../assets/design/2026-10-13-dashboard-example-com.png)
        """
        let article = WikiArticle.build(markdown)
        let text = article.rows.map { String($0.text.characters) }.joined(separator: "\n")
        XCTAssertTrue(text.contains("It has panels."))
        XCTAssertFalse(text.contains("Quiet dark dashboard"), "the card draws the looks itself, from the looks")
    }

    // MARK: Before a screenshot leaves the Mac

    func testABigCaptureIsShrunkUnderTheServersBound() throws {
        let huge = Self.page(width: 5120, height: 2880, background: NSColor(white: 0.1, alpha: 1),
                             accent: NSColor(srgbRed: 0.49, green: 0.61, blue: 1, alpha: 1))
        let prepared = try XCTUnwrap(DesignImageShrink.prepare(huge))
        let rep = try XCTUnwrap(NSBitmapImageRep(data: prepared.data))
        XCTAssertLessThanOrEqual(max(rep.pixelsWide, rep.pixelsHigh), 2560)
        XCTAssertLessThan(prepared.data.count, 4 * 1024 * 1024)
        XCTAssertTrue(["png", "jpg"].contains(prepared.ext))
        let small = Self.page(width: 400, height: 250, background: .white, accent: .black)
        let kept = try XCTUnwrap(DesignImageShrink.prepare(small))
        let pixels = try XCTUnwrap(small.cgImage(forProposedRect: nil, context: nil, hints: nil)).width
        XCTAssertEqual(NSBitmapImageRep(data: kept.data)?.pixelsWide, pixels, "never enlarged")
    }

    // MARK: Offscreen renders (never the app)

    /// A made-up page in four colours, the demo's `website` drawing in AppKit: a bar, a headline, a button, cards.
    static func page(width: CGFloat, height: CGFloat, background: NSColor, accent: NSColor,
                     surface: NSColor? = nil, ink: NSColor? = nil, cards: Int = 3) -> NSImage {
        let image = NSImage(size: NSSize(width: width, height: height))
        image.lockFocusFlipped(true)
        let s = width / 960
        let surface = surface ?? background.blended(withFraction: 0.08, of: .white) ?? background
        let ink = ink ?? (background.brightnessComponentSafe < 0.5 ? NSColor(white: 0.9, alpha: 1)
                                                                    : NSColor(white: 0.1, alpha: 1))
        func box(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat, _ c: NSColor, _ r: CGFloat = 0) {
            c.setFill()
            NSBezierPath(roundedRect: NSRect(x: x * s, y: y * s, width: w * s, height: h * s), xRadius: r * s,
                         yRadius: r * s).fill()
        }
        background.setFill()
        NSRect(x: 0, y: 0, width: width, height: height).fill()
        box(0, 0, 960, 56, surface)
        box(40, 22, 90, 12, ink, 6)
        box(40, 110, 520, 36, ink, 8)
        box(40, 158, 380, 24, ink, 8)
        box(40, 206, 470, 10, ink.withAlphaComponent(0.45), 4)
        box(40, 228, 430, 10, ink.withAlphaComponent(0.45), 4)
        box(40, 290, 150, 40, accent, 10)
        let cw = (880 - CGFloat(cards - 1) * 20) / CGFloat(cards)
        for i in 0..<cards {
            let x = 40 + CGFloat(i) * (cw + 20)
            box(x, 370, cw, 190, surface, 10)
            box(x + 18, 392, 44, 44, accent.withAlphaComponent(1 - 0.25 * CGFloat(i)), 8)
            box(x + 18, 456, cw - 58, 12, ink, 4)
            box(x + 18, 484, cw - 36, 8, ink.withAlphaComponent(0.5), 3)
        }
        image.unlockFocus()
        return image
    }

    static let fixtures: [(DesignRefSummary, NSImage)] = {
        func rgb(_ r: Int, _ g: Int, _ b: Int) -> NSColor {
            NSColor(srgbRed: CGFloat(r) / 255, green: CGFloat(g) / 255, blue: CGFloat(b) / 255, alpha: 1)
        }
        func ref(_ id: String, _ title: String, _ site: String, _ day: String, _ palette: [(String, Double)],
                 _ look: [String], _ fonts: [String], _ note: String, by: String = "user") -> DesignRefSummary {
            DesignRefSummary(id: id, title: title, url: "https://\(site)", site: site, captured: day + "T16:30:00Z",
                             day: day, addedBy: by, addedByKind: by == "user" ? "user" : "agent", via: "demo",
                             image: DesignImage(url: "/design/\(id)/image?v=0", width: 960, height: 600, bytes: 1),
                             palette: palette.map { DesignColour(hex: $0.0, share: $0.1) }, look: look, fonts: fonts,
                             notePreview: note)
        }
        return [
            (ref("2026-10-13-studio-example-com", "Pastel portfolio", "studio.example.com", "2026-10-13",
                 [("#fde8ef", 0.74), ("#faf5f8", 0.17), ("#5a3e8c", 0.05), ("#3a2a52", 0.04)], ["light", "muted", "pink"],
                 [], "Soft pink and plum, big rounded tiles. Playful but the type stays serious."),
             page(width: 960, height: 600, background: rgb(253, 232, 239), accent: rgb(90, 62, 140),
                  surface: rgb(250, 245, 248), ink: rgb(58, 42, 82))),
            (ref("2026-10-10-docs-example-com", "Terminal-green docs", "docs.example.com", "2026-10-10",
                 [("#0d1210", 0.78), ("#141c18", 0.14), ("#b6f2c1", 0.05), ("#36d07a", 0.03)], ["dark", "vivid", "green"],
                 ["JetBrains Mono"], "Docs that feel like a terminal: mono type, green on near-black.", by: "claude-code"),
             page(width: 960, height: 600, background: rgb(13, 18, 16), accent: rgb(54, 208, 122),
                  surface: rgb(20, 28, 24), ink: rgb(182, 242, 193), cards: 4)),
            (ref("2026-10-05-launch-example-com", "Bright product launch", "launch.example.com", "2026-10-05",
                 [("#ffffff", 0.7), ("#f2f4ff", 0.2), ("#3b5bfd", 0.06), ("#111827", 0.04)], ["light", "vivid", "blue"],
                 [], "Lots of white, rounded cards, a confident blue button."),
             page(width: 960, height: 600, background: .white, accent: rgb(59, 91, 253), surface: rgb(242, 244, 255),
                  ink: rgb(17, 24, 39), cards: 4)),
            (ref("2026-09-30-journal-example-com", "Warm editorial essay page", "journal.example.com", "2026-09-30",
                 [("#f6f1e7", 0.75), ("#ede5d6", 0.15), ("#2b2620", 0.06), ("#c8553d", 0.04)], ["light", "muted", "red"],
                 ["Fraunces", "Georgia"], "Serif headlines on warm paper, generous margins, a single rust accent."),
             page(width: 960, height: 600, background: rgb(246, 241, 231), accent: rgb(200, 85, 61),
                  surface: rgb(237, 229, 214), ink: rgb(43, 38, 32))),
            (ref("2026-09-23-dashboard-example-com", "Quiet dark dashboard", "dashboard.example.com", "2026-09-23",
                 [("#171920", 0.81), ("#e2e6f0", 0.1), ("#7c9cff", 0.05), ("#2a2e3a", 0.04)], ["dark", "muted", "blue"],
                 ["Inter"], "The calm dark panels and one soft blue for the only action. Nothing shouts."),
             page(width: 960, height: 600, background: rgb(20, 22, 28), accent: rgb(124, 156, 255),
                  surface: rgb(29, 32, 41), ink: rgb(226, 230, 240))),
        ]
    }()

    private func snapshot<V: View>(_ view: V, size: CGSize, mode: AppColorScheme, to url: URL) throws {
        let host = NSHostingView(rootView: view.environment(\.colorScheme, mode == .dark ? .dark : .light))
        host.frame = NSRect(origin: .zero, size: size)
        // Rendered as the key window draws it, far off screen: the composer is a sheet the person is typing in, and an
        // inactive window's prominent button gives up its accent fill (`PrimaryActionInk`, AppKit's own rule).
        let window = KeyableWindow(contentRect: host.frame.offsetBy(dx: -20_000, dy: -20_000), styleMask: [.borderless],
                                   backing: .buffered, defer: false)
        window.appearance = NSAppearance(named: mode == .dark ? .darkAqua : .aqua)
        window.contentView = host
        window.orderFrontRegardless()
        window.makeKey()
        defer { window.orderOut(nil) }
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.4))
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }

    func testRenderThePageLooksForReview() throws {
        guard let dir = ProcessInfo.processInfo.environment["LOOKS_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set LOOKS_RENDER_DIR to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        var refs = Self.fixtures.map(\.0)
        for i in refs.indices { refs[i].entity = i < 2 ? "alpha-project" : (i == 2 ? "beta-project" : nil) }
        let images = Dictionary(uniqueKeysWithValues: Self.fixtures.map { ($0.0.id, $0.1) })
        let tile: (DesignRefSummary) -> AnyView = { ref in
            AnyView(Image(nsImage: images[ref.id]!).resizable().scaledToFill())
        }
        let open = refs[4]
        let detail = DesignRef(summary: open, note: open.notePreview, snippets: [DesignSnippet(lang: "css", code:
            ":root { --bg: #14161c; --panel: #1d2029; --accent: #7c9cff; }\n.panel { border-radius: 10px; padding: 18px; }")],
            specimens: [DesignSpecimen(family: "Newsreader", generic: "serif",
                                       roles: [.init(role: "body", size: 19, weight: 400), .init(role: "drop_cap", size: 88)]),
                        DesignSpecimen(family: "Inter", generic: "sans-serif",
                                       roles: [.init(role: "heading", size: 56, weight: 700)])])
        let names = ["alpha-project": "Alpha Project", "beta-project": "Beta Project"]
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let name = mode == .dark ? "dark" : "light"
            // A page with looks: its tiles, then the ways to add one (a link, a drop, a saved look on no page).
            let section = PageLooksBlock(refs: Array(refs.prefix(2)), unplaced: Array(refs.suffix(2)),
                                         entityId: "alpha-project", tile: tile, emptyOpen: .constant(false),
                                         onOpen: { _ in })
                .padding(32).frame(width: 760, alignment: .topLeading).background(CicadaTheme.bgBase)
            try snapshot(section, size: CGSize(width: 760, height: 420), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("page-looks-\(name).png"))
            // A page with none: the remembered disclosure, opened.
            let empty = PageLooksBlock(refs: [], unplaced: Array(refs.suffix(2)), entityId: "gamma-project",
                                       tile: tile, emptyOpen: .constant(true), onOpen: { _ in })
                .padding(32).frame(width: 760, alignment: .topLeading).background(CicadaTheme.bgBase)
            try snapshot(empty, size: CGSize(width: 760, height: 180), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("page-looks-empty-\(name).png"))
            // A look opened large from its page: the detail, the looks like it (each saying its page), Take it off.
            let extra = PageLookExtra(similar: Array(refs.prefix(3)), names: names, onPage: true, tile: tile,
                                      onOpenPage: { _ in }, onTakeOff: {})
            let sheet = LooksDetailColumn(summary: open, detail: detail, image: tile(open), onClose: {}, onRemove: {},
                                          extra: AnyView(extra))
            try snapshot(sheet, size: CGSize(width: 760, height: 1500), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("page-look-open-\(name).png"))
            var zoom = LooksZoom()
            zoom.present(open.id, from: .zero, style: .instant)
            let enlarged = LooksZoomOverlay(zoom: zoom, summary: open, onClose: { _ in })
            try snapshot(enlarged, size: CGSize(width: 1180, height: 760), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("looks-enlarged-\(name).png"))
            // Clusters' Looks tab: every look, each saying the page it is on (one on none).
            let gallery = LooksGallery(refs: refs, total: refs.count, phase: .loaded, names: names, searching: false,
                                       note: nil, query: .constant(""), tile: tile)
                .padding(.top, 24).background(CicadaTheme.bgBase)
            try snapshot(gallery, size: CGSize(width: 1180, height: 760), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("clusters-looks-\(name).png"))
            // The sheet's own part: the person's words, put it on a page, the similar looks.
            let words = VStack(alignment: .leading, spacing: 24) {
                PageLookEdit(summary: open, detail: detail, onSave: { _, _, _ in })
                PageLookPlace(onPage: true, rank: { _ in [] }, onPlace: { _ in })
            }
            .padding(32).frame(width: 760, alignment: .topLeading).background(CicadaTheme.bgPane)
            try snapshot(words, size: CGSize(width: 760, height: 420), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("page-look-words-\(name).png"))
            // Clusters' View menu with the new filter on.
            let menu = ClustersViewMenu(types: .constant(Set(EntityType.selectableCases)), labels: .constant([]),
                                        labelCounts: [("design", 3), ("work", 2)], typeCounts: [.project: 4, .tool: 2],
                                        expandAll: .constant(false), onlyWithLooks: .constant(true), looksCount: 2)
            try snapshot(menu, size: CGSize(width: 260, height: 600), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("clusters-view-menu-looks-\(name).png"))
        }
    }
}

private final class KeyableWindow: NSWindow {
    override var canBecomeKey: Bool { true }
}

private extension NSColor {
    var brightnessComponentSafe: CGFloat { usingColorSpace(.sRGB)?.brightnessComponent ?? 0 }
}
