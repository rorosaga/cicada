import XCTest
@testable import CicadaApp

/// R-V5: the Feed row says an item is a video before you open it. The preview
/// sheet this file also sized retired with R-DL16 — the player is as wide as the
/// Feed's detail column now — so only `VideoRef`'s answer is left to pin.
final class FeedVideoRowTests: XCTestCase {
    func testTheBadgeShowsForPlayableRefsOnly() {
        // R14/R6: the badge means "this plays"; an external-only provider gets
        // no badge because tapping it would not play anything.
        XCTAssertEqual(VideoRef.resolve("https://vimeo.com/123456789")?.isPlayable, true)
        XCTAssertEqual(VideoRef.resolve("https://example.com/media/clip.mp4")?.isPlayable, true)
        XCTAssertEqual(VideoRef.resolve("https://www.twitch.tv/videos/1234567890")?.isPlayable, false)
        XCTAssertNil(VideoRef.resolve("https://example.com/articles/how-to-example"))
    }
}
