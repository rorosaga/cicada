import XCTest
import SwiftUI
@testable import CicadaApp

/// DR-71 — every link view drawn offscreen, light and dark (never the app): the prose's URL, address and mention, the
/// bookmark wide and narrow (and with its view menu), the embeds (a video's play button, a PDF's card), a screenshot
/// from a saved look, the look swatch, each degraded state said in words, and the switcher's popover. Each must draw at its width; the PNGs are written only when `LINK_RENDER_DIR` names a
/// folder. Synthetic URLs only; nothing is fetched (no picture path loads without a Store and a backend).
final class LinkRenderTests: XCTestCase {
    private let seats = "https://blog.example.com/seats"

    private var fact: LinkFact {
        LinkFact(url: seats, site: "example.com", pageId: "seats-post", title: "How we priced seats",
                 description: "A walk through the move from flat plans to usage-based billing, with the numbers we used.",
                 savedAt: "2026-10-02", readAt: "2026-10-03T08:00:00Z", preview: "/entities/seats-post/preview?v=abc",
                 looks: [LinkFact.Look(id: "2026-10-14-seats", day: "2026-10-14", image: "/design/2026-10-14-seats/image?v=ab",
                                       palette: [DesignColour(hex: "#1F2A44", share: 0.5), DesignColour(hex: "#F4EFE6", share: 0.3),
                                                 DesignColour(hex: "#E8553D", share: 0.2)])])
    }

    private static let article = """
    ## Article
    ### Pricing
    They moved to usage billing after the [pricing page](https://example.com/pricing) redesign \
    ([plain](https://example.com/plain "url")) \
    (https://example.com/pricing). The team wrote it up in \
    [How we priced seats](https://blog.example.com/seats "mention"), and the old flat plan is gone.

    [How we priced seats](https://blog.example.com/seats "bookmark")

    [Getting started](https://docs.example.com/start "screenshot")

    ## Links
    - [Getting started](https://docs.example.com/start) — the setup guide we followed
    - [Roadmap](https://alpha.example.org/roadmap "look") — linked when the launch date moved
    """

    @MainActor
    func testEveryViewDrawsLightAndDark() async throws {
        let dir = ProcessInfo.processInfo.environment["LINK_RENDER_DIR"].flatMap { $0.isEmpty ? nil : $0 }
        if let dir { try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true) }
        let ref = LinkGrammar.links(in: "[How we priced seats](https://blog.example.com/seats \"bookmark\")")[0]
        let shot = try XCTUnwrap(LinkCardModel.shot(fact))
        let plain = LinkGrammar.links(in: "- [How we priced seats](https://blog.example.com/seats) — the write-up")[0]
        let video = LinkGrammar.links(in: "[A talk](https://www.youtube.com/watch?v=dQw4w9WgXcQ \"embed\")")[0]
        let pdf = LinkGrammar.links(in: "[The paper](https://papers.example.org/seats.pdf \"embed\")")[0]
        let key = WikiArticleCache.Key(markdown: Self.article, dropping: WikiArticle.ownSurfaces)
        _ = WikiArticleCache.shared.article(key)
        await WikiArticleCache.shared.build(key)
        defer { CicadaTheme.mode = .dark }
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            CicadaTheme.uiScale = 1
            let views: [(String, CGFloat, AnyView)] = [
                ("article", 640, AnyView(WikiPageView(key: key))),
                ("bookmark-wide", 560, AnyView(BookmarkCard(fact: fact, ref: ref))),
                ("bookmark-narrow", 360, AnyView(BookmarkCard(fact: fact, ref: ref))),
                ("bookmark-unread", 560, AnyView(BookmarkCard(fact: .unknown("https://alpha.example.org/roadmap"),
                                                              status: Copy.Links.noCapture))),
                ("screenshot", 560, AnyView(CaptureCard(fact: fact, shot: shot, ref: ref))),
                ("look", 560, AnyView(LookSwatch(fact: fact, look: fact.looks[0]))),
                ("switcher", 400, AnyView(LinkLineList(refs: [ref], entityId: "alpha-project"))),
                ("bookmark-with-menu", 640, AnyView(LinkBlockView(ref: plain, note: "the write-up", entityId: "alpha-project"))),
                ("embed-video", 560, AnyView(LinkEmbedView(ref: video, fact: .unknown(video.url),
                                                           embed: try XCTUnwrap(LinkEmbed.of(video.url))))),
                ("embed-pdf", 560, AnyView(LinkEmbedView(ref: pdf, fact: .unknown(pdf.url), embed: .pdf))),
                ("image-from-the-web", 560, AnyView(ProseImage(url: "https://example.com/chart.png", alt: "Revenue chart"))),
            ]
            for (name, width, view) in views {
                let framed = view
                    .padding(CicadaTheme.spacingLG)
                    .frame(width: width + CicadaTheme.spacingLG * 2)
                    .background(CicadaTheme.bgBase)
                    .environment(\.colorScheme, mode == .dark ? .dark : .light)
                let renderer = ImageRenderer(content: framed)
                renderer.proposedSize = ProposedViewSize(width: width + CicadaTheme.spacingLG * 2, height: nil)
                renderer.scale = 2
                let image = try XCTUnwrap(renderer.nsImage, name)
                XCTAssertGreaterThan(image.size.height, CicadaTheme.spacingLG * 2, "\(name) drew nothing")
                if let dir {
                    let tiff = try XCTUnwrap(image.tiffRepresentation)
                    let png = try XCTUnwrap(NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]))
                    try png.write(to: URL(fileURLWithPath: dir)
                        .appendingPathComponent("link-\(name)-\(mode == .dark ? "dark" : "light").png"))
                }
            }
        }
    }
}
