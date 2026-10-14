import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Design taste (2026-10-14) — the Looks page: its wire, its cache, its refresh rule, the shrink before a screenshot
/// leaves the Mac, and offscreen renders of the board in both appearances (`LOOKS_RENDER_DIR`). Synthetic only: made-up
/// pages drawn here, example.com links.
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

    /// DR-40 — the composer has exactly one primary action, Save, and it is the house primary button.
    func testTheComposerHasOnePrimaryActionAndItIsSave() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Looks/LooksPage.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertEqual(text.components(separatedBy: "PrimaryActionButton(").count - 1, 1)
        XCTAssertTrue(text.contains("PrimaryActionButton(title: saving ? Copy.Looks.saving : Copy.Looks.save"))
        XCTAssertFalse(text.contains(".borderedProminent"), "never a hand-rolled primary")
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

    func testRenderTheBoardForReview() throws {
        guard let dir = ProcessInfo.processInfo.environment["LOOKS_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set LOOKS_RENDER_DIR to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        let refs = Self.fixtures.map(\.0)
        let images = Dictionary(uniqueKeysWithValues: Self.fixtures.map { ($0.0.id, $0.1) })
        let tile: (DesignRefSummary) -> AnyView = { ref in
            AnyView(Image(nsImage: images[ref.id]!).resizable().scaledToFill())
        }
        let vision = DesignVision(supported: true, installed: false, downloadBytes: 309_277_919)
        let open = refs[4]
        let detail = DesignRef(summary: open, note: open.notePreview, snippets: [DesignSnippet(lang: "css", code:
            ":root { --bg: #14161c; --panel: #1d2029; --accent: #7c9cff; }\n.panel { border-radius: 10px; padding: 18px; }")])
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let name = mode == .dark ? "dark" : "light"
            let board = LooksBoardView(refs: refs, total: refs.count, phase: .loaded, vision: vision, searching: false,
                                       searchNote: nil, query: .constant(""), open: nil, detail: nil, writeError: nil,
                                       tile: tile)
                .background(CicadaTheme.bgBase)
            try snapshot(board, size: CGSize(width: 1180, height: 760), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("looks-board-\(name).png"))
            let opened = LooksBoardView(refs: refs, total: refs.count, phase: .loaded,
                                        vision: DesignVision(supported: true, installed: true), searching: true,
                                        searchNote: nil, query: .constant("dark dashboard"), open: open, detail: detail,
                                        writeError: nil, tile: tile)
                .background(CicadaTheme.bgBase)
            try snapshot(opened, size: CGSize(width: 1180, height: 900), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("looks-open-\(name).png"))
            let empty = LooksBoardView(refs: [], total: 0, phase: .loaded, vision: vision, searching: false,
                                       searchNote: nil, query: .constant(""), open: nil, detail: nil, writeError: nil,
                                       tile: tile)
                .background(CicadaTheme.bgBase)
            try snapshot(empty, size: CGSize(width: 1000, height: 520), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("looks-empty-\(name).png"))
            let composer = LooksComposer(input: LooksComposerInput(image: images[refs[3].id]!, data: Data(), ext: "png",
                                                                   via: "paste"),
                                         saving: false, error: nil, onCancel: {}, onFindSimilar: { _ in },
                                         onSave: { _ in })
            try snapshot(composer, size: CGSize(width: 460, height: 560), mode: mode,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("looks-composer-\(name).png"))
            // A hosting view's capture cannot draw Liquid Glass (the window server composites it), so the actions row —
            // whose Save is the glass-prominent primary — is also rendered through SwiftUI's own renderer.
            let actions = LooksComposerActions(saving: false, onCancel: {}, onFindSimilar: {}, onSave: {})
                .frame(width: 412).padding(24).background(CicadaTheme.bgPane)
                .environment(\.colorScheme, mode == .dark ? .dark : .light)
            let renderer = ImageRenderer(content: actions)
            renderer.scale = 2
            let tiff = try XCTUnwrap(renderer.nsImage?.tiffRepresentation)
            let png = try XCTUnwrap(NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]))
            try png.write(to: URL(fileURLWithPath: dir).appendingPathComponent("looks-composer-actions-\(name).png"))
        }
    }
}

private final class KeyableWindow: NSWindow {
    override var canBecomeKey: Bool { true }
}

private extension NSColor {
    var brightnessComponentSafe: CGFloat { usingColorSpace(.sRGB)?.brightnessComponent ?? 0 }
}
