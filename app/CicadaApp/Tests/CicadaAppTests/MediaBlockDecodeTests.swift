import XCTest
@testable import CicadaApp

/// Plan R16: the client decodes the two new keys BEFORE the backend produces
/// them, and absence is the test — an older backend (or any non-video page)
/// must decode with neither key present.
final class MediaBlockDecodeTests: XCTestCase {
    func testMediaBlockDecodesWithoutTheNewKeys() throws {
        let json = #"{"url":"https://example.com/a","mediaType":"bookmark"}"#
        let block = try JSONDecoder().decode(MediaBlock.self, from: Data(json.utf8))
        XCTAssertNil(block.provider)
        XCTAssertNil(block.durationS)
    }

    func testMediaBlockDecodesWithTheNewKeys() throws {
        let json = #"{"url":"https://vimeo.com/123456789","mediaType":"url","provider":"vimeo","durationS":95}"#
        let block = try JSONDecoder().decode(MediaBlock.self, from: Data(json.utf8))
        XCTAssertEqual(block.provider, "vimeo")
        XCTAssertEqual(block.durationS, 95)
    }

    func testMediaFeedItemDecodesWithoutTheNewKeys() throws {
        let json = #"{"mediaEntityId":"media-a","url":"https://example.com/a","title":"A","mediaType":"url"}"#
        let item = try JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
        XCTAssertNil(item.provider)
        XCTAssertNil(item.durationS)
    }

    func testTheRawFrontmatterFallbackReadsTheNewKeys() throws {
        // The backend may not surface the nested block; Entity rebuilds it
        // from rawMarkdown (Entity.parseMediaFrontmatter) and must not drop
        // the keys.
        let raw = """
        ---
        name: A clip
        type: media
        media:
          url: https://www.loom.com/share/abc123def4567890abc123def4567890
          media_type: url
          provider: loom
          duration_s: 421
        ---
        body
        """
        let block = try XCTUnwrap(Entity.parseMediaFrontmatter(raw))
        XCTAssertEqual(block.provider, "loom")
        XCTAssertEqual(block.durationS, 421)
    }
}
