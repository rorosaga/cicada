import XCTest
@testable import CicadaApp

/// R-V5: the Feed row says an item is a video before you open it, and the
/// preview sheet is big enough to be a player. Both are pure functions so
/// they are tested without a view.
final class FeedVideoRowTests: XCTestCase {
    private func kind(_ url: String) -> MediaPreviewModel.Kind {
        MediaPreviewModel(block: MediaBlock(url: url, mediaType: "bookmark"), title: "t").kind
    }

    func testTheBadgeShowsForPlayableRefsOnly() {
        // R14/R6: the badge means "this plays"; an external-only provider gets
        // no badge because tapping it would not play anything.
        XCTAssertEqual(VideoRef.resolve("https://vimeo.com/123456789")?.isPlayable, true)
        XCTAssertEqual(VideoRef.resolve("https://example.com/media/clip.mp4")?.isPlayable, true)
        XCTAssertEqual(VideoRef.resolve("https://www.twitch.tv/videos/1234567890")?.isPlayable, false)
        XCTAssertNil(VideoRef.resolve("https://example.com/articles/how-to-example"))
    }

    func testTheSheetGrowsForVideoKindsOnly() {
        // 480x270 inside a 480x520 sheet reads as a regression, not a player.
        XCTAssertEqual(FeedPreviewLayout.sheetSize(for: kind("https://vimeo.com/123456789")),
                       CGSize(width: 720, height: 560))
        XCTAssertEqual(FeedPreviewLayout.sheetSize(for: kind("https://example.com/media/clip.mp4")),
                       CGSize(width: 720, height: 560))
        XCTAssertEqual(FeedPreviewLayout.sheetSize(for: kind("https://example.com/articles/how-to-example")),
                       CGSize(width: 480, height: 520))
        XCTAssertEqual(FeedPreviewLayout.sheetSize(for: kind("https://example.com/photo.jpg")),
                       CGSize(width: 480, height: 520))
    }
}
